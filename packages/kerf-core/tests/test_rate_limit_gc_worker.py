"""Hermetic tests for RateLimitGCWorker.run_once().

Tests use a FakePool / FakeConn to simulate rate_limit_buckets rows.
No Postgres required.

Covers:
  - GC pass removes rows older than 24h.
  - GC pass leaves rows younger than 24h intact.
  - Multiple GC runs are idempotent.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any


# ---------------------------------------------------------------------------
# Fake pool that simulates DELETE ... WHERE window_start < now() - interval
# ---------------------------------------------------------------------------

class FakeBucketsPool:
    """Simulates a pool that tracks rate_limit_buckets rows."""

    def __init__(self, rows: list[dict]):
        # Each row: {"bucket_key": str, "window_start": datetime}
        self._rows = list(rows)
        self._deleted: list[dict] = []
        self._last_delete_tag: str = "DELETE 0"

    def acquire(self):
        return _FakeConnCtx(self)

    def row_count(self) -> int:
        return len(self._rows)

    def deleted_count(self) -> int:
        return len(self._deleted)


class _FakeConnCtx:
    def __init__(self, pool: FakeBucketsPool):
        self._pool = pool

    async def __aenter__(self):
        return _FakeConn(self._pool)

    async def __aexit__(self, *_):
        pass


class _FakeConn:
    def __init__(self, pool: FakeBucketsPool):
        self._pool = pool

    async def execute(self, query: str, *args) -> str:
        query_lower = query.lower()
        if "delete from rate_limit_buckets" in query_lower:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
            old = [r for r in self._pool._rows if r["window_start"] < cutoff]
            kept = [r for r in self._pool._rows if r["window_start"] >= cutoff]
            self._pool._deleted.extend(old)
            self._pool._rows = kept
            tag = f"DELETE {len(old)}"
            self._pool._last_delete_tag = tag
            return tag
        return "OK"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def _make_pool(ages_hours: list[float]) -> FakeBucketsPool:
    """Build a FakePool with rows at the given ages (in hours before now)."""
    rows = []
    now = datetime.now(timezone.utc)
    for age in ages_hours:
        rows.append({
            "bucket_key": f"test:age{age}",
            "window_start": now - timedelta(hours=age),
        })
    return FakeBucketsPool(rows)


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_gc_removes_old_rows():
    """Rows older than 24 h must be deleted."""
    pool = _make_pool([25.0, 30.0, 48.0])  # all 3 rows are > 24h old
    assert pool.row_count() == 3

    from kerf_core.workers.rate_limit_gc_worker import RateLimitGCWorker
    worker = RateLimitGCWorker(pool)
    _run(worker.run_once(pool))

    assert pool.row_count() == 0
    assert pool.deleted_count() == 3


def test_gc_leaves_fresh_rows():
    """Rows younger than 24 h must survive."""
    pool = _make_pool([0.5, 1.0, 23.9])  # all 3 rows are < 24h old
    assert pool.row_count() == 3

    from kerf_core.workers.rate_limit_gc_worker import RateLimitGCWorker
    worker = RateLimitGCWorker(pool)
    _run(worker.run_once(pool))

    assert pool.row_count() == 3
    assert pool.deleted_count() == 0


def test_gc_mixed_rows():
    """Old rows are deleted; fresh rows are kept."""
    pool = _make_pool([0.5, 25.0, 2.0, 30.0])  # 2 old, 2 fresh
    assert pool.row_count() == 4

    from kerf_core.workers.rate_limit_gc_worker import RateLimitGCWorker
    worker = RateLimitGCWorker(pool)
    _run(worker.run_once(pool))

    assert pool.row_count() == 2
    assert pool.deleted_count() == 2


def test_gc_empty_table_is_noop():
    """GC on an empty table must not error."""
    pool = _make_pool([])
    from kerf_core.workers.rate_limit_gc_worker import RateLimitGCWorker
    worker = RateLimitGCWorker(pool)
    deleted = _run(worker.run_once(pool))
    assert deleted == 0


def test_gc_idempotent():
    """Running GC twice removes old rows on first pass; second is a no-op."""
    pool = _make_pool([25.0, 26.0])
    from kerf_core.workers.rate_limit_gc_worker import RateLimitGCWorker
    worker = RateLimitGCWorker(pool)
    _run(worker.run_once(pool))
    assert pool.row_count() == 0

    _run(worker.run_once(pool))  # second run: nothing to delete
    assert pool.row_count() == 0
    assert pool.deleted_count() == 2  # only 2 rows were ever deleted
