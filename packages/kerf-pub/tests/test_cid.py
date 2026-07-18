"""CIDv1 (raw codec) derivation (:mod:`kerf_pub.cid`) and the standalone
IPFS fetch-adapter unit (:mod:`kerf_pub.ipfs`) — the IPFS-fallback
integration through :meth:`kerf_pub.client.PubClient.hydrate_pin` is covered
by ``test_pin_hydration.py``; this file is the pure-function / single-unit
layer underneath it.
"""

from __future__ import annotations

import base64
import hashlib

from kerf_pub.cid import cid_for_chunk
from kerf_pub.hashing import HASH_PREFIX, mhash
from kerf_pub.ipfs import IPFSGatewayFetcher, default_ipfs_gateway_url, ENV_IPFS_GATEWAY_URL


# ── cid_for_chunk: known-good vectors, derived by hand ──────────────────────
#
# kerf ships HASH_PREFIX = 0x12 (SHA2-256, hashing.py). A kerf-pub chunk hash
# is `h = HASH_PREFIX ‖ SHA2-256(plaintext)` (33 bytes). Deriving its CIDv1:
#
#   1. multihash = varint(code=0x12) ‖ varint(digest_len=32=0x20) ‖ digest
#      Both varints are < 0x80 so each is exactly one raw byte:
#      multihash = 0x12 0x20 ‖ digest                              (34 bytes)
#   2. cid_bytes = varint(version=1) ‖ varint(codec=raw=0x55) ‖ multihash
#      Both are again single-byte varints:
#      cid_bytes = 0x01 0x55 ‖ multihash                           (36 bytes)
#   3. textual CID = multibase-prefix 'b' ‖ base32(cid_bytes), RFC 4648
#      lowercase alphabet, NO padding.
#
# Vector 1 — plaintext = b"" (the empty chunk PubManifest.split_chunks()
# produces for a zero-length blob, objects.py:split_chunks):
#
#   SHA2-256("") = e3b0c442 98fc1c14 9afbf4c8 996fb924 27ae41e4 6649b934
#                  ca495991 b7852b85                       (well-known value)
#   h            = 12 e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934
#                     ca495991b7852b85
#   multihash    = 12 20 <digest>
#   cid_bytes    = 01 55 12 20 <digest>
#
# base32(cid_bytes) was cross-checked two independent ways: (a) running this
# module's own bit-shifting `_b32_encode_nopad` against `cid_bytes`, and
# (b) `base64.b32encode(cid_bytes).decode().lower().rstrip("=")` (Python's
# stdlib RFC 4648 implementation) — both agree, and the result matches the
# well-known real-world CID for an empty raw-codec/sha256 IPFS object:
_EMPTY_CID = "bafkreihdwdcefgh4dqkjv67uzcmw7ojee6xedzdetojuzjevtenxquvyku"


def test_cid_for_chunk_empty_chunk_vector():
    assert HASH_PREFIX == 0x12, "vector assumes the shipped SHA2-256 prefix"
    h = mhash(b"")
    assert cid_for_chunk(h) == _EMPTY_CID

    # independent cross-check of the same 36 bytes via stdlib base32.
    digest = hashlib.sha256(b"").digest()
    cid_bytes = bytes([0x01, 0x55, 0x12, 0x20]) + digest
    expected = "b" + base64.b32encode(cid_bytes).decode().lower().rstrip("=")
    assert cid_for_chunk(h) == expected


def test_cid_for_chunk_nonempty_vector_matches_stdlib_cross_check():
    payload = b"hello-kerf-pub"
    h = mhash(payload)
    digest = hashlib.sha256(payload).digest()
    cid_bytes = bytes([0x01, 0x55, 0x12, 0x20]) + digest
    expected = "b" + base64.b32encode(cid_bytes).decode().lower().rstrip("=")
    assert cid_for_chunk(h) == expected
    assert cid_for_chunk(h).startswith("bafkrei")  # CIDv1 raw+sha256 signature prefix


def test_cid_for_chunk_is_deterministic_and_injective_over_distinct_inputs():
    a = cid_for_chunk(mhash(b"one"))
    b = cid_for_chunk(mhash(b"two"))
    assert a != b
    assert cid_for_chunk(mhash(b"one")) == a  # deterministic


def test_cid_for_chunk_rejects_malformed_hash():
    import pytest
    with pytest.raises(ValueError):
        cid_for_chunk(b"too-short")


# ── IPFSGatewayFetcher: single-unit fetch + verification discipline ────────


async def test_ipfs_fetcher_builds_correct_url_and_returns_bytes(monkeypatch):
    payload = b"chunk-bytes-on-ipfs"
    h = mhash(payload)
    cid = cid_for_chunk(h)
    seen_urls = []

    def fake_http_get(url: str):
        seen_urls.append(url)
        return payload

    monkeypatch.setattr(IPFSGatewayFetcher, "_http_get", staticmethod(fake_http_get))
    fetcher = IPFSGatewayFetcher("https://ipfs.example/")  # trailing slash stripped
    got = await fetcher.fetch_chunk(h)

    assert got == payload
    assert seen_urls == [f"https://ipfs.example/ipfs/{cid}"]


async def test_ipfs_fetcher_returns_none_on_network_failure(monkeypatch):
    def fake_http_get(url: str):
        raise ConnectionError("gateway unreachable")

    monkeypatch.setattr(IPFSGatewayFetcher, "_http_get", staticmethod(fake_http_get))
    fetcher = IPFSGatewayFetcher("https://ipfs.example")
    assert await fetcher.fetch_chunk(mhash(b"whatever")) is None


def test_ipfs_fetcher_does_not_verify_itself():
    """fetch_chunk() returns raw bytes verbatim — self-verification against
    h_i is the CALLER's job (PubClient._fetch_chunk_verified), the same
    untrusted-holder discipline applied to every other gateway."""
    import inspect
    src = inspect.getsource(IPFSGatewayFetcher.fetch_chunk)
    assert "verify_chunk" not in src


# ── per-node config convention ──────────────────────────────────────────────


def test_default_ipfs_gateway_url_absent_by_default(monkeypatch):
    monkeypatch.delenv(ENV_IPFS_GATEWAY_URL, raising=False)
    assert default_ipfs_gateway_url() is None


def test_default_ipfs_gateway_url_reads_env(monkeypatch):
    monkeypatch.setenv(ENV_IPFS_GATEWAY_URL, "https://ipfs.io")
    assert default_ipfs_gateway_url() == "https://ipfs.io"


def test_default_ipfs_gateway_url_blank_env_is_absent(monkeypatch):
    monkeypatch.setenv(ENV_IPFS_GATEWAY_URL, "   ")
    assert default_ipfs_gateway_url() is None
