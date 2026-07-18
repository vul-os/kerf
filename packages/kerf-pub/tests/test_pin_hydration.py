"""Pin hydration (§22.5.3 swarm fetch over HTTPS gateways) —
:meth:`kerf_pub.client.PubClient.hydrate_pin` and the
``POST /api/pub/pin/{id}`` / ``POST /api/pub/pin/{id}/hydrate`` endpoints.

The HTTP layer is mocked by monkeypatching ``PubClient._http_get`` (the one
synchronous network call every gateway fetch funnels through, via
``asyncio.to_thread``) with a small in-memory "fake gateway" that serves
bytes straight out of a real :class:`~kerf_pub.store.InMemoryPubStore` —
so served bytes are byte-identical to what the real §22.5.1 gateway router
would return for the same store, without opening a socket in tests.
"""

from __future__ import annotations

import base64

import pytest

from kerf_pub import Identity, InMemoryPubStore, PubClient, PubError, PubManifest
from kerf_pub.client import HydrationResult
from kerf_pub.errors import ERR_PUB_NOT_SERVED
from kerf_pub.hashing import mhash
from kerf_pub.objects import DEFAULT_CHUNK_SZ
from kerf_pub.store import STATUS_AVAILABLE, STATUS_ON_NODE, STATUS_UNREACHABLE


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


# ── fake gateway HTTP layer ─────────────────────────────────────────────────


class FakeGateway:
    """Stands in for one §22.5.1 HTTP gateway, backed by a real PubStore.

    ``up=False`` simulates the gateway being entirely unreachable (connection
    failure — caught and treated as ROTATE_RETRY by the client, same as a
    real network error). ``corrupt_chunks`` simulates a holder serving
    wrong-but-plausible bytes for specific chunk hashes (§22.5.3
    ERR_PUB_CHUNK_HASH_MISMATCH / ROTATE_RETRY); ``missing_chunks`` simulates
    a holder that simply never had that chunk (a clean 404).
    """

    def __init__(self, base_url: str, store: InMemoryPubStore):
        self.base_url = base_url
        self.store = store
        self.up = True
        self.corrupt_chunks: set[bytes] = set()
        self.missing_chunks: set[bytes] = set()
        self.requests: list[str] = []  # path log, for order assertions

    def get(self, path: str) -> bytes | None:
        self.requests.append(path)
        if not self.up:
            raise ConnectionError(f"{self.base_url} is down")
        if path.startswith("announce/"):
            return _run(self.store.get_announce(_b64_decode(path.split("/", 1)[1])))
        if path.startswith("manifest/"):
            return _run(self.store.get_manifest(_b64_decode(path.split("/", 1)[1])))
        if path.startswith("chunk/"):
            h = _b64_decode(path.split("/", 1)[1])
            if h in self.missing_chunks:
                return None
            data = _run(self.store.get_chunk(h))
            if data is not None and h in self.corrupt_chunks:
                return b"\x00CORRUPTED\x00" + data
            return data
        return None


def _run(coro):
    import asyncio
    return asyncio.run(coro)


class FakeIPFSGateway:
    """Stands in for an IPFS HTTP gateway: served bytes keyed by CID."""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.up = True
        self.by_cid: dict[str, bytes] = {}
        self.requests: list[str] = []

    def get(self, path: str) -> bytes | None:
        self.requests.append(path)
        if not self.up:
            raise ConnectionError(f"{self.base_url} is down")
        assert path.startswith("ipfs/")
        cid = path.split("/", 1)[1]
        return self.by_cid.get(cid)


_KERF_REGISTRY: dict[str, FakeGateway] = {}
_IPFS_REGISTRY: dict[str, FakeIPFSGateway] = {}


def register_kerf_gateway(store: InMemoryPubStore, base_url: str) -> FakeGateway:
    gw = FakeGateway(base_url, store)
    _KERF_REGISTRY[base_url] = gw
    return gw


def register_ipfs_gateway(base_url: str) -> FakeIPFSGateway:
    gw = FakeIPFSGateway(base_url)
    _IPFS_REGISTRY[base_url] = gw
    return gw


def _split(url: str, marker: str) -> tuple[str, str]:
    base, _, path = url.partition(marker)
    return base, path


def _fake_kerf_http_get(url: str) -> bytes | None:
    base, path = _split(url, "/.well-known/dmtap-pub/")
    gw = _KERF_REGISTRY.get(base)
    if gw is None:
        raise ConnectionError(f"no fake gateway registered for {base}")
    return gw.get(path)


def _fake_ipfs_http_get(url: str) -> bytes | None:
    base, path = _split(url, "/")
    # base_url may itself contain no extra path; reconstruct by finding the
    # registered base as a prefix (ipfs URLs are "{base}/ipfs/{cid}").
    for candidate, gw in _IPFS_REGISTRY.items():
        if url.startswith(candidate + "/"):
            return gw.get(url[len(candidate) + 1:])
    raise ConnectionError(f"no fake ipfs gateway registered for {url}")


@pytest.fixture(autouse=True)
def _patch_network(monkeypatch):
    _KERF_REGISTRY.clear()
    _IPFS_REGISTRY.clear()
    monkeypatch.setattr(PubClient, "_http_get", staticmethod(_fake_kerf_http_get))
    from kerf_pub.ipfs import IPFSGatewayFetcher
    monkeypatch.setattr(IPFSGatewayFetcher, "_http_get", staticmethod(_fake_ipfs_http_get))
    yield
    _KERF_REGISTRY.clear()
    _IPFS_REGISTRY.clear()


# ── fixtures: a publisher with a multi-chunk artifact ───────────────────────


async def _seed_publisher() -> tuple[InMemoryPubStore, bytes, bytes]:
    """A store with one published multi-chunk blob. Returns
    (origin_store, announce_id, manifest_root)."""
    origin = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=origin, identity=idn)
    # Force >1 chunk so rotate/partial/missing behavior is exercised.
    payload = (b"A" * DEFAULT_CHUNK_SZ) + (b"B" * DEFAULT_CHUNK_SZ) + b"tail-bytes"
    aid = await client.publish({"native": payload})
    manifest = PubManifest.build(payload)
    assert len(manifest.chunks) == 3
    return origin, aid, manifest.id


# ── happy path: fully local already (publish already hydrated it) ──────────


async def test_hydrate_pin_local_only_is_immediately_full():
    origin, aid, _root = await _seed_publisher()
    # Simulate "pin was previously cleared" (e.g. user unpinned, still local
    # in the swarm cache) — hydrate_pin must recognize fully-local content
    # needs zero network calls, even with no gateways configured at all.
    await origin.set_pinned(aid, False)

    client = PubClient(store=origin, identity=None, gateways=[])
    result = await client.hydrate_pin(aid)

    assert result == HydrationResult(pinned=True, hydrated=True, missing_chunks=0)
    assert (await origin.get_availability(aid)).status() == STATUS_ON_NODE


# ── happy path: full swarm fetch from a remote gateway ──────────────────────


async def test_hydrate_pin_full_fetch_from_gateway():
    origin, aid, root = await _seed_publisher()
    register_kerf_gateway(origin, "https://gw1.example")

    follower = InMemoryPubStore()
    client = PubClient(store=follower, identity=None, gateways=["https://gw1.example"])

    result = await client.hydrate_pin(aid)

    assert result.pinned is True
    assert result.hydrated is True
    assert result.missing_chunks == 0
    assert result.error is None
    assert (await follower.get_availability(aid)).status() == STATUS_ON_NODE

    # Every manifest + chunk actually landed locally, verified.
    manifest_raw = await follower.get_manifest(root)
    assert manifest_raw is not None
    manifest = PubManifest.from_cbor(manifest_raw)
    manifest.verify()
    for h in manifest.chunks:
        assert await follower.get_chunk(h) is not None


# ── rotate-on-corrupt-chunk (§22.5.3, ERR_PUB_CHUNK_HASH_MISMATCH) ──────────


async def test_hydrate_pin_rotates_off_corrupt_chunk():
    origin, aid, root = await _seed_publisher()
    manifest = PubManifest.from_cbor(await origin.get_manifest(root))
    target_chunk = manifest.chunks[1]

    gw_bad = register_kerf_gateway(origin, "https://bad.example")
    gw_bad.corrupt_chunks.add(target_chunk)
    gw_good = register_kerf_gateway(origin, "https://good.example")

    follower = InMemoryPubStore()
    client = PubClient(
        store=follower, identity=None,
        gateways=["https://bad.example", "https://good.example"],
    )
    result = await client.hydrate_pin(aid)

    # The corrupt gateway is rejected, not accepted-with-a-warning — the
    # second gateway's correct bytes are what ends up verified and stored.
    assert result == HydrationResult(pinned=True, hydrated=True, missing_chunks=0)
    stored = await follower.get_chunk(target_chunk)
    assert stored is not None
    from kerf_pub.hashing import verify_chunk
    assert verify_chunk(target_chunk, stored)
    assert b"CORRUPTED" not in stored


# ── partial hydration: a chunk unfetchable everywhere ───────────────────────


async def test_hydrate_pin_partial_when_chunk_missing_everywhere():
    origin, aid, root = await _seed_publisher()
    manifest = PubManifest.from_cbor(await origin.get_manifest(root))
    unfetchable = manifest.chunks[0]

    gw = register_kerf_gateway(origin, "https://gw1.example")
    gw.missing_chunks.add(unfetchable)

    follower = InMemoryPubStore()
    client = PubClient(store=follower, identity=None, gateways=["https://gw1.example"])
    result = await client.hydrate_pin(aid)

    assert result.pinned is True
    assert result.hydrated is False
    assert result.missing_chunks == 1
    assert result.error is not None

    # Bytes that WERE verified are persisted; availability is NOT on-node,
    # but the gateway that did respond is recorded as a known holder so
    # status reads "available", not "unreachable".
    avail = await follower.get_availability(aid)
    assert avail.local_pinned is False
    assert avail.status() == STATUS_AVAILABLE

    for h in manifest.chunks:
        if h == unfetchable:
            assert await follower.get_chunk(h) is None
        else:
            assert await follower.get_chunk(h) is not None


async def test_hydrate_pin_partial_unreachable_holder_status():
    """When NOTHING responds at all (every configured gateway is down), the
    partial result still comes back structured (never a raise) — but no
    holder can be recorded, so status stays unreachable."""
    origin, aid, root = await _seed_publisher()
    gw = register_kerf_gateway(origin, "https://gw1.example")
    gw.up = False

    follower = InMemoryPubStore()
    # Seed the announce locally (so the zero-socket announce-resolution
    # raise doesn't fire) but leave manifest/chunks remote-only.
    await follower.put_announce(aid, await origin.get_announce(aid))

    client = PubClient(store=follower, identity=None, gateways=["https://gw1.example"])
    result = await client.hydrate_pin(aid)

    assert result.hydrated is False
    assert result.pinned is True
    avail = await follower.get_availability(aid)
    assert avail.local_pinned is False
    assert avail.status() == STATUS_UNREACHABLE


# ── hydrate-retry recovers a partial pin ────────────────────────────────────


async def test_hydrate_retry_recovers_after_partial():
    origin, aid, root = await _seed_publisher()
    manifest = PubManifest.from_cbor(await origin.get_manifest(root))
    flaky_chunk = manifest.chunks[2]

    gw = register_kerf_gateway(origin, "https://gw1.example")
    gw.missing_chunks.add(flaky_chunk)

    follower = InMemoryPubStore()
    client = PubClient(store=follower, identity=None, gateways=["https://gw1.example"])

    first = await client.hydrate_pin(aid)
    assert first.hydrated is False
    assert first.missing_chunks == 1

    # The chunk becomes available (propagated to the holder) — retrying the
    # exact same hydrate_pin call now completes it.
    gw.missing_chunks.discard(flaky_chunk)
    second = await client.hydrate_pin(aid)

    assert second == HydrationResult(pinned=True, hydrated=True, missing_chunks=0)
    assert (await follower.get_availability(aid)).status() == STATUS_ON_NODE
    assert await follower.get_chunk(flaky_chunk) is not None


# ── zero-socket pin failure ──────────────────────────────────────────────


async def test_hydrate_pin_zero_socket_raises_clear_error():
    follower = InMemoryPubStore()
    client = PubClient(store=follower, identity=None, gateways=[])
    unknown_aid = mhash(b"never-published-and-not-local")

    with pytest.raises(PubError) as exc_info:
        await client.hydrate_pin(unknown_aid)
    assert exc_info.value.code == ERR_PUB_NOT_SERVED

    # Never a silent no-op: nothing was recorded as pinned/on-node.
    avail = await follower.get_availability(unknown_aid)
    assert avail.local_pinned is False
    assert avail.status() == STATUS_UNREACHABLE


async def test_hydrate_pin_announce_unreachable_on_configured_gateway_raises():
    """A gateway IS configured but doesn't have this particular announce —
    still a clear raise, not a partial result (there is nothing to persist
    or report progress on; we never even learned what to fetch)."""
    origin, _aid, _root = await _seed_publisher()
    register_kerf_gateway(origin, "https://gw1.example")

    follower = InMemoryPubStore()
    client = PubClient(store=follower, identity=None, gateways=["https://gw1.example"])
    unknown_aid = mhash(b"some-other-announce-nobody-has")

    with pytest.raises(PubError) as exc_info:
        await client.hydrate_pin(unknown_aid)
    assert exc_info.value.code == ERR_PUB_NOT_SERVED


# ── IPFS fetch-adapter fallback order ───────────────────────────────────────


async def test_hydrate_pin_falls_back_to_ipfs_after_kerf_gateways_fail():
    from kerf_pub.cid import cid_for_chunk

    origin, aid, root = await _seed_publisher()
    manifest = PubManifest.from_cbor(await origin.get_manifest(root))
    ipfs_only_chunk = manifest.chunks[0]

    gw = register_kerf_gateway(origin, "https://gw1.example")
    gw.missing_chunks.add(ipfs_only_chunk)  # kerf gateway lacks it

    ipfs_gw = register_ipfs_gateway("https://ipfs.example")
    ipfs_gw.by_cid[cid_for_chunk(ipfs_only_chunk)] = await origin.get_chunk(ipfs_only_chunk)

    follower = InMemoryPubStore()
    client = PubClient(
        store=follower, identity=None,
        gateways=["https://gw1.example"],
        ipfs_gateway_url="https://ipfs.example",
    )
    result = await client.hydrate_pin(aid)

    assert result == HydrationResult(pinned=True, hydrated=True, missing_chunks=0)
    assert await follower.get_chunk(ipfs_only_chunk) is not None
    # Order: the kerf gateway was tried (and asked) for the chunk BEFORE
    # IPFS was ever consulted (IPFS is strictly a fallback, never first).
    assert any(p == f"chunk/{_b64(ipfs_only_chunk)}" for p in gw.requests)
    assert any(p == f"ipfs/{cid_for_chunk(ipfs_only_chunk)}" for p in ipfs_gw.requests)


async def test_hydrate_pin_ipfs_never_consulted_for_manifest_or_announce():
    """Manifests/announces are kerf-object CBOR, not IPLD — IPFS must never
    even be asked for them, regardless of configuration."""
    origin, aid, root = await _seed_publisher()
    # No kerf gateway at all configured — only IPFS. The announce/manifest
    # therefore CANNOT be resolved (IPFS doesn't serve them), so this must
    # behave as the zero-socket case for the announce (no kerf gateway
    # configured) even though an "ipfs_gateway_url" is set.
    ipfs_gw = register_ipfs_gateway("https://ipfs.example")

    follower = InMemoryPubStore()
    client = PubClient(
        store=follower, identity=None, gateways=[],
        ipfs_gateway_url="https://ipfs.example",
    )
    with pytest.raises(PubError):
        await client.hydrate_pin(aid)
    assert ipfs_gw.requests == []  # never touched


async def test_hydrate_pin_ipfs_bytes_still_self_verify():
    """An IPFS gateway serving wrong-but-CID-plausible bytes is rejected the
    same way a corrupt kerf holder is — IPFS is untrusted too."""
    origin, aid, root = await _seed_publisher()
    manifest = PubManifest.from_cbor(await origin.get_manifest(root))
    target = manifest.chunks[0]

    from kerf_pub.cid import cid_for_chunk

    gw = register_kerf_gateway(origin, "https://gw1.example")
    gw.missing_chunks.add(target)

    ipfs_gw = register_ipfs_gateway("https://ipfs.example")
    ipfs_gw.by_cid[cid_for_chunk(target)] = b"not-the-real-chunk-bytes"

    follower = InMemoryPubStore()
    client = PubClient(
        store=follower, identity=None,
        gateways=["https://gw1.example"], ipfs_gateway_url="https://ipfs.example",
    )
    result = await client.hydrate_pin(aid)

    assert result.hydrated is False
    assert result.missing_chunks == 1
    assert await follower.get_chunk(target) is None
