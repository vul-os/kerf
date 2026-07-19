"""kerf-pub store over the embedded SQLite backend.

:class:`kerf_pub.store.PostgresPubStore` targets asyncpg but is written entirely
against the pool convenience surface (``execute`` / ``fetchrow`` / ``fetch``),
which :class:`kerf_core.db.sqlite_backend.SqlitePool` mirrors — so the *same*
store class serves a local, zero-dependency node on SQLite.  This suite proves
the four object classes (chunk / manifest / feed), the anti-rollback watermark,
availability/pin state, and follows all round-trip on SQLite.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from kerf_pub.store import PostgresPubStore


@pytest.fixture
async def sqlite_pool():
    db = tempfile.mktemp(suffix=".db")
    url = "sqlite://" + db
    from kerf_core.db.migrations.runner import run_migrations
    from kerf_core.db.sqlite_backend import create_sqlite_pool

    await run_migrations(url)
    pool = await create_sqlite_pool(url)
    try:
        yield pool
    finally:
        await pool.close()
        Path(db).unlink(missing_ok=True)


async def test_publish_follow_pin(sqlite_pool):
    store = PostgresPubStore(sqlite_pool)
    await store.put_chunk(b"chunkhash", b"payload")
    assert await store.get_chunk(b"chunkhash") == b"payload"
    await store.put_manifest(b"mid", b"manifest-body")
    assert await store.get_manifest(b"mid") == b"manifest-body"

    # pin / availability
    await store.set_pinned(b"artifact1", True)
    av = await store.get_availability(b"artifact1")
    assert av.local_pinned is True
    assert av.status() == "on-node"

    # note a holder -> availability reflects it (jsonb known_holders round-trip)
    await store.note_holder(b"artifact2", "https://holder.example", verified_ms=42)
    av2 = await store.get_availability(b"artifact2")
    assert av2.known_holders == {"https://holder.example": 42}

    # follow
    await store.put_follow(b"pubkey1", "friend", "https://gw.example", 1000)
    follows = await store.list_follows()
    assert len(follows) == 1 and follows[0]["label"] == "friend"
    await store.delete_follow(b"pubkey1")
    assert await store.list_follows() == []


async def test_feed_seq_and_watermark(sqlite_pool):
    store = PostgresPubStore(sqlite_pool)
    await store.put_feed_entry(b"pub", 1, b"e1", b"body1")
    await store.put_feed_entry(b"pub", 2, b"e2", b"body2")
    assert await store.get_feed_entry_by_seq(b"pub", 2) == b"body2"
    assert await store.get_feed_range(b"pub", 1, 2) == [b"body1", b"body2"]

    await store.put_feed_head(b"pub", b"head-bytes")
    assert await store.get_feed_head(b"pub") == b"head-bytes"

    await store.set_accepted_seq(b"pub", 5)
    assert await store.get_accepted_seq(b"pub") == 5


async def test_wake_subscriptions(sqlite_pool):
    """kerf_pub.wake's subscription registry (migration 0016) round-trips on
    the embedded SQLite backend exactly like the Postgres baseline."""
    store = PostgresPubStore(sqlite_pool)
    pub = b"\x01" * 32

    assert await store.count_wake_subscriptions(pub) == 0

    await store.put_wake_subscription(pub, "https://a.example/ep1", "p256dh-a", "auth-a", 100)
    await store.put_wake_subscription(pub, "https://b.example/ep2", "p256dh-b", "auth-b", 200)
    assert await store.count_wake_subscriptions(pub) == 2

    rows = await store.list_wake_subscriptions(pub)
    assert [r["endpoint"] for r in rows] == ["https://a.example/ep1", "https://b.example/ep2"]
    assert rows[0]["pub"] == pub

    # upsert on re-subscribe (same endpoint, new keys)
    await store.put_wake_subscription(pub, "https://a.example/ep1", "p256dh-a-new", "auth-a-new", 150)
    rows = await store.list_wake_subscriptions(pub)
    assert len(rows) == 2
    assert next(r for r in rows if r["endpoint"] == "https://a.example/ep1")["p256dh"] == "p256dh-a-new"

    await store.delete_wake_subscription(pub, "https://a.example/ep1")
    rows = await store.list_wake_subscriptions(pub)
    assert len(rows) == 1
    assert rows[0]["endpoint"] == "https://b.example/ep2"
