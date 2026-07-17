"""Four-verb client: local publish/fetch/resolve, zero-socket, submit stub."""

import pytest

from kerf_pub import (
    Identity, PubClient, InMemoryPubStore, PubManifest, PubAnnounce,
    ArtifactMetadata, ArtifactFormat, Units, extract_artifact, PubError,
)
from kerf_pub.objects import KIND_PART, FMT_NATIVE, ROLE_CANONICAL
from kerf_pub.store import STATUS_ON_NODE, STATUS_UNREACHABLE, STATUS_AVAILABLE


async def test_publish_then_fetch_local():
    idn = Identity.generate()
    client = PubClient(store=InMemoryPubStore(), identity=idn)
    payload = b"solid body of a part" * 1000
    aid = await client.publish({"native": payload})

    ann = PubAnnounce.from_cbor(await client.store.get_announce(aid))
    ann.verify(expected_id=aid)
    root = ann.roots[0]
    assert await client.fetch(root) == payload


async def test_publish_embeds_and_extracts_artifact_metadata():
    idn = Identity.generate()
    client = PubClient(store=InMemoryPubStore(), identity=idn)
    body = b"native-cad-bytes"
    native_root = PubManifest.build(body).id
    am = ArtifactMetadata(
        name="Widget", description="", artifact_kind=KIND_PART,
        formats=[ArtifactFormat(FMT_NATIVE, native_root, ROLE_CANONICAL)],
        units=Units(length_unit="mm"), license="MIT",
    )
    aid = await client.publish({"native": body}, artifact_metadata=am)
    ann = PubAnnounce.from_cbor(await client.store.get_announce(aid))
    back = extract_artifact(ann.meta)
    assert back.name == "Widget"
    # the built manifest root matches the one recorded in the metadata (deterministic)
    assert native_root in ann.roots


async def test_zero_socket_no_gateway_no_network():
    # No gateways configured: resolve of an unknown author returns [] (no socket),
    # and fetch of an unpinned blob fails locally rather than dialing out.
    client = PubClient(store=InMemoryPubStore(), identity=Identity.generate())
    assert client.online is False
    assert await client.resolve(Identity.generate().pub) == []
    with pytest.raises(PubError):
        await client.fetch(PubManifest.build(b"never-pinned").id)


async def test_resolve_returns_verified_entries():
    idn = Identity.generate()
    client = PubClient(store=InMemoryPubStore(), identity=idn)
    await client.publish({"f": b"a"})
    await client.publish({"f": b"b"})
    entries = await client.resolve(idn.pub)
    assert [e.seq for e in entries] == [0, 1]


async def test_availability_status_transitions():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn)
    aid = await client.publish({"f": b"x"})
    # published locally → pinned → on-node
    assert (await store.get_availability(aid)).status() == STATUS_ON_NODE

    other = PubManifest.build(b"elsewhere").id
    assert (await store.get_availability(other)).status() == STATUS_UNREACHABLE
    await store.note_holder(other, "https://gw.example", verified_ms=None)
    assert (await store.get_availability(other)).status() == STATUS_AVAILABLE


async def test_submit_not_implemented():
    client = PubClient(store=InMemoryPubStore(), identity=Identity.generate())
    with pytest.raises(NotImplementedError):
        await client.submit({"job": "topo-opt"})


def test_identity_persistence(tmp_path):
    p = tmp_path / "identity.key"
    a = Identity.load_or_create(p)
    b = Identity.load_or_create(p)  # loads the same key back
    assert a.pub == b.pub
    assert p.read_bytes() == a._seed
