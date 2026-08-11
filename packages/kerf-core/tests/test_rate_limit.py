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


# ── configurable per-bucket limits ──────────────────────────────────────────

def test_an_override_replaces_the_declared_limit(monkeypatch):
    """The numbers at each call site are defaults, not law.

    /auth/register allows 5 an hour per IP. That is per-IP, so an office behind
    one NAT hits it on the sixth colleague, and the e2e suite hits it whenever
    it seeds more than five accounts. Operators need to raise it without
    editing code.
    """
    from kerf_core.config import Settings

    settings = Settings(rate_limit_overrides={"auth:register": 50})
    assert settings.rate_limit_overrides["auth:register"] == 50


def test_an_override_of_zero_disables_the_bucket():
    from kerf_core.config import Settings

    settings = Settings(rate_limit_overrides={"auth:login": 0})
    assert settings.rate_limit_overrides["auth:login"] == 0


def test_overrides_default_to_empty_so_call_site_numbers_apply():
    from kerf_core.config import Settings

    assert Settings().rate_limit_overrides == {}


def test_overrides_are_read_from_toml():
    """[rate_limits] keys are free text, so a new limiter is tunable without a
    config-schema change."""
    import tempfile, pathlib as _pathlib
    from kerf_core.config import Settings

    with tempfile.TemporaryDirectory() as d:
        path = _pathlib.Path(d) / "kerf.toml"
        path.write_text('[rate_limits]\n"auth:register" = 42\n"some:future" = 7\n')
        settings = Settings.load(str(path))

    assert settings.rate_limit_overrides == {"auth:register": 42, "some:future": 7}


@pytest.mark.asyncio
async def test_the_override_reaches_the_dependency_not_just_the_settings(tmp_path):
    """Settings carrying the number is not the same as the limiter using it.

    This drives the real FastAPI dependency against a real SQLite pool: a
    bucket declared at 2/window must admit a third call once the override
    raises it, and a bucket overridden to 0 must admit everything.
    """
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    import kerf_core.config as config_mod
    import kerf_core.db.connection as conn_mod
    from kerf_core.dependencies import rate_limit
    from kerf_core.db.migrations.runner import run_sqlite_migrations
    from kerf_core.db.sqlite_backend import create_sqlite_pool

    url = f"sqlite://{tmp_path}/rl.db"
    await run_sqlite_migrations(url)
    pool = await create_sqlite_pool(url, max_size=2)
    conn_mod._pool = pool

    original = config_mod.get_settings
    try:
        settings = config_mod.Settings(
            rate_limit_overrides={"probe:raised": 5, "probe:off": 0})
        config_mod.get_settings = lambda: settings
        # dependencies.py imports get_settings inside the handler, so patching
        # the module attribute is enough.

        app = FastAPI()

        @app.get("/raised")
        async def raised(_: None = Depends(rate_limit(2, 3600, "probe:raised"))):
            return {"ok": True}

        @app.get("/off")
        async def off(_: None = Depends(rate_limit(1, 3600, "probe:off"))):
            return {"ok": True}

        @app.get("/declared")
        async def declared(_: None = Depends(rate_limit(2, 3600, "probe:declared"))):
            return {"ok": True}

        with TestClient(app) as client:
            # Declared 2, overridden to 5 — the third call must be admitted.
            assert [client.get("/raised").status_code for _ in range(5)] == [200] * 5
            assert client.get("/raised").status_code == 429

            # Overridden to 0 — disabled entirely.
            assert all(client.get("/off").status_code == 200 for _ in range(10))

            # No override — the declared 2 still applies.
            assert [client.get("/declared").status_code for _ in range(2)] == [200, 200]
            assert client.get("/declared").status_code == 429
    finally:
        config_mod.get_settings = original
        conn_mod._pool = None
        await pool.close()
