"""PubManifest: build/verify roundtrip, tamper detection, key-5 trap (§22.2)."""

import pytest

from kerf_pub import PubManifest, PubError
from kerf_pub import cbor, hashing
from kerf_pub.objects import DEFAULT_CHUNK_SZ
from kerf_pub.errors import (
    ERR_PUB_MANIFEST_KEY_PRESENT,
    ERR_PUB_MANIFEST_HASH_MISMATCH,
)


def test_build_verify_roundtrip_single_chunk():
    m = PubManifest.build(b"hello world")
    m.verify()
    assert len(m.chunks) == 1
    assert m.size == 11
    assert m.id[0] == hashing.HASH_PREFIX
    assert len(m.id) == hashing.HASH_LEN
    m2 = PubManifest.from_cbor(m.to_cbor())
    m2.verify()
    assert m2.id == m.id and m2.chunks == m.chunks


def test_build_multi_chunk_merkle():
    data = bytes(range(256)) * 40  # > 4 KiB
    m = PubManifest.build(data, chunk_sz=1024)
    m.verify()
    assert len(m.chunks) == (len(data) + 1023) // 1024
    # each chunk hash is prefix ‖ digest of that plaintext slice
    for i, h in enumerate(m.chunks):
        assert hashing.verify_chunk(h, data[i * 1024:(i + 1) * 1024])


def test_deterministic_address_is_content_derived():
    assert PubManifest.build(b"abc").id == PubManifest.build(b"abc").id
    assert PubManifest.build(b"abc").id != PubManifest.build(b"abd").id


def test_empty_blob_is_one_empty_chunk():
    m = PubManifest.build(b"")
    m.verify()
    assert m.size == 0 and len(m.chunks) == 1


def test_tamper_root_detected():
    m = PubManifest.build(b"the quick brown fox", chunk_sz=4)
    # Corrupt the recorded root; verify must fail closed.
    m.id = bytes([m.id[0]]) + bytes(32)
    with pytest.raises(PubError) as ei:
        m.verify()
    assert ei.value.code == ERR_PUB_MANIFEST_HASH_MISMATCH


def test_tamper_chunk_list_detected():
    m = PubManifest.build(b"aaaabbbbcccc", chunk_sz=4)
    m.chunks[0] = hashing.mhash(b"zzzz")  # swap a chunk hash
    with pytest.raises(PubError) as ei:
        m.verify()
    assert ei.value.code == ERR_PUB_MANIFEST_HASH_MISMATCH


def test_key_5_rejected():
    # A PubManifest MUST NOT carry key 5 (the sealed-manifest key trap).
    m = PubManifest.build(b"data")
    raw = cbor.decode(m.to_cbor())
    raw[5] = b"leaked-key"
    poisoned = cbor.encode(raw)
    with pytest.raises(PubError) as ei:
        PubManifest.from_cbor(poisoned)
    assert ei.value.code == ERR_PUB_MANIFEST_KEY_PRESENT


def test_manifest_id_prefix_carried():
    m = PubManifest.build(b"x")
    # every hash in the object declares its algorithm via the multihash prefix
    assert m.id[0] == hashing.HASH_PREFIX
    assert all(h[0] == hashing.HASH_PREFIX for h in m.chunks)


# ── digest cut-over: BLAKE3 write path, SHA2-256 legacy read path ────────────
#
# kerf-pub v1 addressed public content under SHA2-256 (prefix 0x12); §22 v0
# REQUIRES BLAKE3-256 (0x1e), and interop with other implementations is only
# real under 0x1e (tests/test_conformance_vectors.py). The cut-over is
# write-only: nothing already pinned or already signed is invalidated.

def test_new_addresses_are_blake3_and_nothing_can_mint_a_legacy_one():
    m = PubManifest.build(b"hello world")
    assert m.id[0] == hashing.PREFIX_BLAKE3_256
    assert all(h[0] == hashing.PREFIX_BLAKE3_256 for h in m.chunks)


def test_legacy_sha2_manifest_still_verifies_after_the_cutover():
    """MIGRATION SAFETY: a manifest minted by the old build keeps verifying.

    This is the property that makes the cut-over non-destructive. A node's
    stored bytes are untouched, and — the part that cannot be re-derived — an
    already-signed PubAnnounce whose `roots` commit to 0x12 addresses stays
    verifiable, because its publisher's key is not available to re-sign.
    """
    data = b"pinned before the cut-over"
    chunks = PubManifest.split_chunks(data)
    legacy_hashes = [hashing.mhash_under(hashing.PREFIX_SHA2_256, c) for c in chunks]
    legacy = PubManifest(
        id=hashing.merkle_root(legacy_hashes), size=len(data),
        chunk_sz=DEFAULT_CHUNK_SZ, chunks=legacy_hashes,
    )
    assert legacy.id[0] == hashing.PREFIX_SHA2_256

    legacy.verify()                                   # root recomputes under 0x12
    assert PubManifest.from_cbor(legacy.to_cbor()).id == legacy.id
    for h, c in zip(legacy_hashes, chunks):
        assert hashing.verify_chunk(h, c)             # chunks still self-verify


def test_legacy_and_new_addresses_never_collide():
    """No downgrade: a 0x12 digest can never satisfy a 0x1e reference."""
    data = b"same bytes, two namings"
    new = hashing.mhash(data)
    legacy = hashing.mhash_under(hashing.PREFIX_SHA2_256, data)
    assert new != legacy
    assert not hashing.verify_chunk(new, b"other bytes")
    # Each address only ever verifies under the digest its own prefix names.
    assert hashing.verify_chunk(new, data) and hashing.verify_chunk(legacy, data)


def test_a_manifest_may_not_mix_digests_across_its_chunks():
    mixed = [hashing.mhash(b"a"), hashing.mhash_under(hashing.PREFIX_SHA2_256, b"b")]
    with pytest.raises(ValueError, match="mixes hash algorithms"):
        hashing.merkle_root(mixed)


def test_blake3_backends_agree_when_both_are_available():
    """The optional wheel and the pure-Python fallback must be byte-identical."""
    from kerf_pub.blake3_pure import blake3_256 as pure
    payloads = [b"", b"x", b"y" * 1023, b"z" * 1024, b"w" * 1025, b"q" * 4097]
    for p in payloads:
        assert hashing._digest_with(hashing.PREFIX_BLAKE3_256, p) == pure(p)
