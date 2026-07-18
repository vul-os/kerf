"""Gateway HTTP endpoints (§22.5.1) + plugin registration smoke tests."""

import base64

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kerf_pub import Identity, PubClient, InMemoryPubStore, PubManifest, PubAnnounce
from kerf_pub.objects import FeedHead
from kerf_pub import cbor
from kerf_pub.router import router


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


async def _seed_store():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn)
    aid = await client.publish({"native": b"hello-gateway" * 100})
    ann = PubAnnounce.from_cbor(await store.get_announce(aid))
    return store, idn, aid, ann


def _app(store) -> TestClient:
    app = FastAPI()
    app.state.pub_store = store
    app.include_router(router)
    return TestClient(app)


async def test_all_five_endpoints_serve():
    store, idn, aid, ann = await _seed_store()
    tc = _app(store)

    # feed head (mutable)
    r = tc.get(f"/.well-known/dmtap-pub/feed/{_b64(idn.pub)}/head")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/cbor"
    head = FeedHead.from_cbor(r.content)
    head.verify()
    assert head.pub == idn.pub
    assert "must-revalidate" in r.headers["cache-control"]

    # feed range
    r = tc.get(f"/.well-known/dmtap-pub/feed/{_b64(idn.pub)}/range?from=0&to=0")
    assert r.status_code == 200
    arr = cbor.decode(r.content)
    assert isinstance(arr, list) and len(arr) == 1

    # announce (immutable, ETag == address)
    r = tc.get(f"/.well-known/dmtap-pub/announce/{_b64(aid)}")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]
    assert r.headers["etag"].strip('"') == _b64(aid)
    PubAnnounce.from_cbor(r.content).verify(expected_id=aid)

    # manifest
    root = ann.roots[0]
    r = tc.get(f"/.well-known/dmtap-pub/manifest/{_b64(root)}")
    assert r.status_code == 200
    m = PubManifest.from_cbor(r.content)
    m.verify()
    assert m.id == root

    # chunk (raw plaintext bytes, self-verifying against h)
    from kerf_pub.hashing import verify_chunk
    h = m.chunks[0]
    r = tc.get(f"/.well-known/dmtap-pub/chunk/{_b64(h)}")
    assert r.status_code == 200
    assert verify_chunk(h, r.content)


def test_unknown_object_404():
    tc = _app(InMemoryPubStore())
    fake = _b64(b"\x12" + b"\x00" * 32)
    assert tc.get(f"/.well-known/dmtap-pub/announce/{fake}").status_code == 404
    assert tc.get(f"/.well-known/dmtap-pub/manifest/{fake}").status_code == 404
    assert tc.get(f"/.well-known/dmtap-pub/chunk/{fake}").status_code == 404
    assert tc.get(
        f"/.well-known/dmtap-pub/feed/{_b64(b'x' * 32)}/head").status_code == 404


async def test_plugin_registers_router_not_gated_by_cloud():
    from kerf_pub.plugin import register

    class Ctx:
        pool = None
        local_mode = True

    app = FastAPI()
    manifest = await register(app, Ctx())
    assert manifest.name == "pub"
    paths = {r.path for r in app.routes}
    assert "/.well-known/dmtap-pub/announce/{aid}" in paths
    # store wired even without a DB pool
    assert app.state.pub_store is not None
