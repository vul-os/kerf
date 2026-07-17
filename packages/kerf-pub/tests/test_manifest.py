"""PubManifest: build/verify roundtrip, tamper detection, key-5 trap (§22.2)."""

import pytest

from kerf_pub import PubManifest, PubError
from kerf_pub import cbor, hashing
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
