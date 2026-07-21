"""Author feeds: chain integrity, anti-rollback, fork detection (§22.4)."""

import pytest

from kerf_pub import (
    Identity, FeedEntry, FeedHead, PubClient, InMemoryPubStore, PubError,
    check_fork,
)
from kerf_pub.errors import (
    ERR_PUB_FEED_SIG_INVALID,
    ERR_PUB_FEED_ROLLBACK,
    ERR_PUB_FEED_CHAIN_BROKEN,
)


def test_feed_head_sign_verify():
    idn = Identity.generate()
    head = FeedHead(pub=idn.pub, seq=0, tip=_h(), ts=1).sign(idn)
    head.verify()
    assert FeedHead.from_cbor(head.to_cbor()).tip == head.tip


def test_feed_head_bad_sig_rejected():
    idn = Identity.generate()
    head = FeedHead(pub=idn.pub, seq=0, tip=_h(), ts=1).sign(idn)
    head.sig = bytes(64)
    with pytest.raises(PubError) as ei:
        head.verify()
    assert ei.value.code == ERR_PUB_FEED_SIG_INVALID


def test_genesis_shape_rules():
    with pytest.raises(PubError) as ei:
        FeedEntry(seq=0, announce=_h(), ts=1, prev=_h()).check_shape()
    assert ei.value.code == ERR_PUB_FEED_CHAIN_BROKEN
    with pytest.raises(PubError) as ei:
        FeedEntry(seq=1, announce=_h(), ts=1, prev=None).check_shape()
    assert ei.value.code == ERR_PUB_FEED_CHAIN_BROKEN


async def test_resolve_walks_and_verifies_chain():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn)
    a1 = await client.publish({"f": b"one"})
    a2 = await client.publish({"f": b"two"})
    a3 = await client.publish({"f": b"three"})
    entries = await client.resolve(idn.pub)
    assert [e.seq for e in entries] == [0, 1, 2]
    assert [e.announce for e in entries] == [a1, a2, a3]
    # prev chain links each entry to its predecessor
    assert entries[0].prev is None
    assert entries[1].prev == entries[0].id
    assert entries[2].prev == entries[1].id


async def test_anti_rollback_rejects_stale_head():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn)
    await client.publish({"f": b"one"})
    await client.publish({"f": b"two"})   # watermark now at seq 1
    await client.resolve(idn.pub)         # accept seq 1

    # Forge a stale head at seq 0 signed by the real author.
    entry0 = FeedEntry.from_cbor(await store.get_feed_entry_by_seq(idn.pub, 0))
    stale = FeedHead(pub=idn.pub, seq=0, tip=entry0.id, ts=1).sign(idn)
    await store.put_feed_head(idn.pub, stale.to_cbor())
    with pytest.raises(PubError) as ei:
        await client.resolve(idn.pub)
    assert ei.value.code == ERR_PUB_FEED_ROLLBACK


async def test_broken_prev_chain_detected():
    store = InMemoryPubStore()
    idn = Identity.generate()
    client = PubClient(store=store, identity=idn)
    await client.publish({"f": b"one"})
    await client.publish({"f": b"two"})
    # Rewrite entry at seq 1 so its prev no longer resolves to seq 0.
    e1 = FeedEntry.from_cbor(await store.get_feed_entry_by_seq(idn.pub, 1))
    forged = FeedEntry(seq=1, announce=e1.announce, ts=e1.ts, prev=_h())
    await store.put_feed_entry(idn.pub, 1, forged.id, forged.to_cbor())
    # Point the head at the forged entry so tip matches but the chain is broken.
    head = FeedHead(pub=idn.pub, seq=1, tip=forged.id, ts=1).sign(idn)
    await store.put_feed_head(idn.pub, head.to_cbor())
    await store.set_accepted_seq(idn.pub, 0)
    with pytest.raises(PubError) as ei:
        await client.resolve(idn.pub)
    assert ei.value.code == ERR_PUB_FEED_CHAIN_BROKEN


def test_fork_detection_same_seq_two_entries():
    a = FeedEntry(seq=1, announce=_h(b"a"), ts=1, prev=_h(b"p"))
    b = FeedEntry(seq=1, announce=_h(b"b"), ts=1, prev=_h(b"p"))
    with pytest.raises(PubError) as ei:
        check_fork(a, b)
    assert ei.value.code == ERR_PUB_FEED_CHAIN_BROKEN


# ── helpers ───────────────────────────────────────────────────────────────────
def _h(seed: bytes = b"x"):
    from kerf_pub import hashing
    return hashing.mhash(seed)


# ── §22.4.1 fixed-width `seq`/`ts` decode guards ──────────────────────────────
# The §22 field tables type `seq` and `ts` as u64. Python ints are signed and
# arbitrary-precision, so a bare `int(m[k])` admitted values no u64-typed
# implementation (the Rust `dmtap-core::pubobj`) can represent — a cross-engine
# disagreement about whether an object is well-formed at all. The monotonic-seq
# rule of §22.4.2 is only meaningful over the totally-ordered domain the spec
# defines, so the width is enforced at the decode boundary.

def _neg_entry_cbor(seq: int) -> bytes:
    from kerf_pub import cbor
    return cbor.encode({1: seq, 2: _h(b"a"), 3: _h(b"b"), 4: 1234})


@pytest.mark.parametrize("bad", [-1, -(2 ** 63)])
def test_feed_entry_rejects_negative_seq(bad):
    with pytest.raises(PubError) as ei:
        FeedEntry.from_cbor(_neg_entry_cbor(bad))
    assert ei.value.code == ERR_PUB_FEED_CHAIN_BROKEN


def test_feed_entry_rejects_negative_ts():
    from kerf_pub import cbor
    raw = cbor.encode({1: 1, 2: _h(b"a"), 3: _h(b"b"), 4: -1})
    with pytest.raises(PubError) as ei:
        FeedEntry.from_cbor(raw)
    assert ei.value.code == ERR_PUB_FEED_CHAIN_BROKEN


def test_feed_entry_accepts_u64_max_seq():
    """The boundary itself is legal — the guard rejects *outside* u64, not at it."""
    from kerf_pub import cbor
    raw = cbor.encode({1: 2 ** 64 - 1, 2: _h(b"a"), 3: _h(b"b"), 4: 1})
    assert FeedEntry.from_cbor(raw).seq == 2 ** 64 - 1


@pytest.mark.parametrize("bad", [-1, -5])
def test_feed_head_rejects_negative_seq(bad):
    from kerf_pub import cbor
    raw = cbor.encode({1: 0, 2: 0x01, 3: b"\x02" * 32, 4: bad,
                       5: _h(b"t"), 6: 1, 7: b"\x04" * 32, 8: b"\x05" * 64})
    with pytest.raises(PubError) as ei:
        FeedHead.from_cbor(raw)
    assert ei.value.code == ERR_PUB_FEED_SIG_INVALID


def test_feed_head_rejects_bool_seq():
    """`bool` is an `int` subclass in Python; it is not a spec-legal u64."""
    from kerf_pub import cbor
    raw = cbor.encode({1: 0, 2: 0x01, 3: b"\x02" * 32, 4: True,
                       5: _h(b"t"), 6: 1, 7: b"\x04" * 32, 8: b"\x05" * 64})
    with pytest.raises(PubError) as ei:
        FeedHead.from_cbor(raw)
    assert ei.value.code == ERR_PUB_FEED_SIG_INVALID


def test_manifest_rejects_negative_size_and_oversized_chunk_sz():
    from kerf_pub import cbor
    from kerf_pub import PubManifest
    from kerf_pub.errors import ERR_PUB_UNSUPPORTED_VERSION
    base = {1: _h(b"id"), 2: 10, 3: 4, 4: [_h(b"c")], 6: 0x01}
    with pytest.raises(PubError) as ei:
        PubManifest.from_cbor(cbor.encode({**base, 2: -1}))
    assert ei.value.code == ERR_PUB_UNSUPPORTED_VERSION
    with pytest.raises(PubError) as ei:  # chunk_sz is u32, not u64
        PubManifest.from_cbor(cbor.encode({**base, 3: 2 ** 32}))
    assert ei.value.code == ERR_PUB_UNSUPPORTED_VERSION
