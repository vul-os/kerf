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
