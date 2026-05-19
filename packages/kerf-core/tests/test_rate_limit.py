"""Hermetic tests for kerf_core.rate_limit.enforce.

Tests use a FakePool / FakeConn that simulates rate_limit_buckets
in-memory. No Postgres required.

Covers:
  - First request under limit returns immediately, count=1.
  - 11th request to a 10-per-60s limit raises HTTPException(429).
  - The 429 includes a Retry-After header.
  - The 429 body has the expected JSON shape.
  - Concurrent calls from the same key serialise correctly (no
    over-allowance — UPSERT is atomic).
  - Sliding window: a request 61 s later starts a new window (count
    resets).
"""
from __future__ import annotations

import asyncio
import math
import time
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Fake pool that simulates rate_limit_buckets atomically in-process
# ---------------------------------------------------------------------------

class FakeBucketsStore:
    """Shared in-memory store for rate_limit_buckets rows."""

    def __init__(self):
        # {(bucket_key, window_start_epoch): count}
        self._buckets: dict[tuple[str, float], int] = {}

    def upsert(self, key: str, window_start_epoch: float) -> int:
        k = (key, window_start_epoch)
        self._buckets[k] = self._buckets.get(k, 0) + 1
        return self._buckets[k]

    def clear(self):
        self._buckets.clear()


class FakeConn:
    def __init__(self, store: FakeBucketsStore, now_epoch: float, window_seconds: float):
        self._store = store
        self._now = now_epoch
        self._w = window_seconds

    async def fetchrow(self, query: str, *args) -> dict:
        # args: (bucket_key, window_seconds_as_float)
        key = args[0]
        w = float(args[1])
        window_start = math.floor(self._now / w) * w
        count = self._store.upsert(key, window_start)
        return {"count": count}


class FakeConnCtx:
    def __init__(self, store, now_epoch, window_seconds):
        self._store = store
        self._now = now_epoch
        self._w = window_seconds

    async def __aenter__(self):
        return FakeConn(self._store, self._now, self._w)

    async def __aexit__(self, *_):
        pass


class FakePool:
    def __init__(self, store: FakeBucketsStore, now_epoch: float = None):
        self._store = store
        self._now = now_epoch if now_epoch is not None else time.time()
        self._window_seconds: float = 60.0

    def acquire(self):
        return FakeConnCtx(self._store, self._now, self._window_seconds)

    def set_now(self, t: float):
        self._now = t


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _enforce(pool, key, max_per_window, window_seconds=60):
    """Thin wrapper so tests don't need to patch time.time."""
    from kerf_core.rate_limit import enforce
    pool._window_seconds = float(window_seconds)
    await enforce(pool, key, max_per_window, window_seconds)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_request_does_not_raise():
    store = FakeBucketsStore()
    pool = FakePool(store)
    # Should not raise
    await _enforce(pool, "test:user1", max_per_window=10, window_seconds=60)


@pytest.mark.asyncio
async def test_requests_under_limit_succeed():
    store = FakeBucketsStore()
    pool = FakePool(store)
    for _ in range(10):
        await _enforce(pool, "test:user2", max_per_window=10, window_seconds=60)
    # 10th request must pass


@pytest.mark.asyncio
async def test_11th_request_raises_429():
    store = FakeBucketsStore()
    pool = FakePool(store)
    for _ in range(10):
        await _enforce(pool, "test:user3", max_per_window=10, window_seconds=60)

    with pytest.raises(HTTPException) as exc_info:
        await _enforce(pool, "test:user3", max_per_window=10, window_seconds=60)

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_429_has_retry_after_header():
    store = FakeBucketsStore()
    pool = FakePool(store)
    for _ in range(10):
        await _enforce(pool, "test:user4", max_per_window=10, window_seconds=60)

    with pytest.raises(HTTPException) as exc_info:
        await _enforce(pool, "test:user4", max_per_window=10, window_seconds=60)

    exc = exc_info.value
    assert exc.status_code == 429
    assert "Retry-After" in exc.headers
    retry_after = int(exc.headers["Retry-After"])
    assert 0 < retry_after <= 60


@pytest.mark.asyncio
async def test_429_body_has_json_shape():
    store = FakeBucketsStore()
    pool = FakePool(store)
    for _ in range(10):
        await _enforce(pool, "test:user5", max_per_window=10, window_seconds=60)

    with pytest.raises(HTTPException) as exc_info:
        await _enforce(pool, "test:user5", max_per_window=10, window_seconds=60)

    exc = exc_info.value
    assert exc.status_code == 429
    detail = exc.detail
    assert isinstance(detail, dict), f"Expected dict detail, got {type(detail)}: {detail}"
    assert detail.get("detail") == "rate limit exceeded"
    assert "retry_after" in detail
    assert isinstance(detail["retry_after"], int)


@pytest.mark.asyncio
async def test_different_keys_are_independent():
    """Two different keys do not interfere with each other."""
    store = FakeBucketsStore()
    pool = FakePool(store)

    for _ in range(10):
        await _enforce(pool, "test:user_a", max_per_window=10, window_seconds=60)

    # user_b still has a fresh window — should not raise
    await _enforce(pool, "test:user_b", max_per_window=10, window_seconds=60)


@pytest.mark.asyncio
async def test_sliding_window_new_window_resets_count():
    """A request 61 s later lands in a new window; count starts at 1."""
    store = FakeBucketsStore()
    base_time = 1_700_000_000.0  # arbitrary fixed epoch
    pool = FakePool(store, now_epoch=base_time)

    for _ in range(10):
        await _enforce(pool, "test:slide", max_per_window=10, window_seconds=60)

    # 11th in same window → 429
    with pytest.raises(HTTPException) as exc_info:
        await _enforce(pool, "test:slide", max_per_window=10, window_seconds=60)
    assert exc_info.value.status_code == 429

    # Move time forward by 61 seconds → new window
    pool.set_now(base_time + 61)

    # Should succeed again (new window, count=1)
    await _enforce(pool, "test:slide", max_per_window=10, window_seconds=60)


@pytest.mark.asyncio
async def test_concurrent_calls_no_over_allowance():
    """Concurrent calls for the same key serialise atomically via UPSERT.

    Because FakeBucketsStore.upsert() is synchronous (no await), there is
    no interleaving — this verifies the arithmetic is correct for N
    concurrent coroutines.
    """
    store = FakeBucketsStore()
    pool = FakePool(store)

    limit = 5
    calls = 10

    results = []

    async def attempt(i):
        try:
            await _enforce(pool, "test:concurrent", max_per_window=limit, window_seconds=60)
            results.append("ok")
        except HTTPException as e:
            if e.status_code == 429:
                results.append("429")
            else:
                raise

    await asyncio.gather(*[attempt(i) for i in range(calls)])

    ok_count = results.count("ok")
    rejected_count = results.count("429")

    assert ok_count == limit, f"Expected exactly {limit} successes, got {ok_count}"
    assert rejected_count == calls - limit, (
        f"Expected {calls - limit} rejections, got {rejected_count}"
    )
