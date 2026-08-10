"""Tests for kerf_core.rate_limit.enforce, against a REAL database.

These used to run against a FakePool that pattern-matched the arguments and
never looked at the SQL. Every assertion below passed while the actual
statement was unparseable on the embedded backend: ``enforce`` built its
window with ``to_timestamp(floor(extract(epoch from now()) / $2) * $2)``,
which is Postgres-only, so on a default (SQLite) install every rate-limited
route — /auth/register, /auth/login — answered 500. A fake that accepts any
SQL cannot catch a dialect error, so the fake is gone: these run against a
real SQLite database opened through kerf's own adapter
(``create_sqlite_pool``), which applies the same dialect translation
production does. No Postgres, no network, no service container — the
embedded backend is stdlib.

Covers:
  - First request under limit returns immediately, count=1.
  - 11th request to a 10-per-60s limit raises HTTPException(429).
  - The 429 includes a Retry-After header.
  - The 429 body has the expected JSON shape.
  - Concurrent calls from the same key serialise correctly (no
    over-allowance — the UPSERT is atomic).
  - Sliding window: a request 61 s later starts a new window (count
    resets).
  - The statement actually executes on the embedded backend (implied by
    every test above, and asserted directly in the round-trip test).
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from kerf_core.db.sqlite_backend import create_sqlite_pool

# Mirrors migrations_sqlite/0001_core_identity.sql. Kept here rather than
# running the whole migration set so a limiter test stays a limiter test.
_DDL = """
create table if not exists rate_limit_buckets (
    bucket_key   text not null,
    window_start text not null,
    count        integer not null default 0,
    primary key (bucket_key, window_start)
)
"""


@pytest.fixture
async def pool(tmp_path):
    """A real SQLite pool with the rate_limit_buckets table created.

    A file (not :memory:) so the pool's several connections all see the same
    rows — which is what makes the concurrency test meaningful.
    """
    p = await create_sqlite_pool(f"sqlite://{tmp_path / 'rl.db'}", max_size=4)
    await p.execute(_DDL)
    yield p
    await p.close()


async def _enforce(pool, key, max_per_window, window_seconds=60, *, now=None):
    """Call enforce, optionally pinning the clock it derives its window from."""
    from kerf_core.rate_limit import enforce

    if now is None:
        await enforce(pool, key, max_per_window, window_seconds)
        return
    with patch("kerf_core.rate_limit.time.time", return_value=now):
        await enforce(pool, key, max_per_window, window_seconds)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_first_request_does_not_raise(pool):
    await _enforce(pool, "test:user1", max_per_window=10, window_seconds=60)


@pytest.mark.asyncio
async def test_statement_round_trips_on_the_embedded_backend(pool):
    """The regression test proper: the UPSERT parses, runs, and counts.

    A dialect error here is exactly the failure that shipped — it surfaced as
    sqlite3.OperationalError: near "from": syntax error, five frames below an
    HTTP 500.
    """
    for expected in (1, 2, 3):
        await _enforce(pool, "test:roundtrip", max_per_window=10, window_seconds=60)
        row = await pool.fetchrow(
            "SELECT count FROM rate_limit_buckets WHERE bucket_key = $1",
            "test:roundtrip",
        )
        assert row is not None, "no bucket row was written"
        assert row["count"] == expected

    rows = await pool.fetch(
        "SELECT bucket_key FROM rate_limit_buckets WHERE bucket_key = $1",
        "test:roundtrip",
    )
    assert len(rows) == 1, "each call must UPSERT one row, not insert a new one"


@pytest.mark.asyncio
async def test_requests_under_limit_succeed(pool):
    for _ in range(10):
        await _enforce(pool, "test:user2", max_per_window=10, window_seconds=60)


@pytest.mark.asyncio
async def test_11th_request_raises_429(pool):
    for _ in range(10):
        await _enforce(pool, "test:user3", max_per_window=10, window_seconds=60)

    with pytest.raises(HTTPException) as exc_info:
        await _enforce(pool, "test:user3", max_per_window=10, window_seconds=60)

    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_429_has_retry_after_header(pool):
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
async def test_429_body_has_json_shape(pool):
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
async def test_different_keys_are_independent(pool):
    """Two different keys do not interfere with each other."""
    for _ in range(10):
        await _enforce(pool, "test:user_a", max_per_window=10, window_seconds=60)

    # user_b still has a fresh window — should not raise
    await _enforce(pool, "test:user_b", max_per_window=10, window_seconds=60)


@pytest.mark.asyncio
async def test_sliding_window_new_window_resets_count(pool):
    """A request 61 s later lands in a new window; count starts at 1."""
    base_time = 1_700_000_000.0  # arbitrary fixed epoch, already window-aligned

    for _ in range(10):
        await _enforce(pool, "test:slide", max_per_window=10, window_seconds=60, now=base_time)

    # 11th in the same window → 429
    with pytest.raises(HTTPException) as exc_info:
        await _enforce(pool, "test:slide", max_per_window=10, window_seconds=60, now=base_time)
    assert exc_info.value.status_code == 429

    # 61 s later → a different window_start, so a different row
    await _enforce(pool, "test:slide", max_per_window=10, window_seconds=60, now=base_time + 61)

    rows = await pool.fetch(
        "SELECT count FROM rate_limit_buckets WHERE bucket_key = $1 ORDER BY window_start",
        "test:slide",
    )
    assert [r["count"] for r in rows] == [11, 1], (
        "expected two window rows — the old one at its final count and a fresh one at 1"
    )


@pytest.mark.asyncio
async def test_concurrent_calls_no_over_allowance(pool):
    """Concurrent calls for one key must not over-allow.

    Against the real database this is a genuine concurrency test: the pool
    hands each coroutine its own connection, and correctness rests on the
    UPSERT being atomic rather than on the test's own bookkeeping.
    """
    limit = 5
    calls = 10
    results: list[str] = []

    async def attempt(_i):
        try:
            await _enforce(pool, "test:concurrent", max_per_window=limit, window_seconds=60)
            results.append("ok")
        except HTTPException as e:
            if e.status_code == 429:
                results.append("429")
            else:
                raise

    await asyncio.gather(*[attempt(i) for i in range(calls)])

    assert results.count("ok") == limit, f"expected exactly {limit} allowed, got {results}"
    assert results.count("429") == calls - limit
