"""Integration tests for StorageBillingWorker / run_monthly_storage_debit_if_needed.

Requires a live Postgres connection via DATABASE_URL.
Run:
    DATABASE_URL=postgres://pc@localhost:5432/kerf?sslmode=disable \
        pytest packages/kerf-billing/tests/test_storage_billing_worker.py -q

Each test creates uniquely-suffixed rows and cleans up in a finally block.
No DROP / CREATE / TRUNCATE — shared live DB.

Scenarios verified
------------------
1. First tick of the month → sweep runs (returns True), storage is debited.
2. Second tick within the same month → no-op (returns False), no double-bill.
3. Tick after month boundary → sweep runs again (returns True), new debit.
4. StorageBillingWorker unit construction / stop() (no DB required).
"""
from __future__ import annotations

import math
import os
import uuid
from datetime import datetime, timezone

import asyncpg
import pytest
import pytest_asyncio

from kerf_billing.scheduler import (
    StorageBillingWorker,
    run_monthly_storage_debit_if_needed,
)

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgres://pc@localhost:5432/kerf?sslmode=disable"
)

FREE_BYTES = 50 * 1024 * 1024   # 50 MB — must match config default
RATE_PER_GB_MONTH = 0.20        # must match config default

pytestmark = pytest.mark.asyncio

_TAG = "t402r3-"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expected_cost(billable_bytes: int) -> float:
    chargeable = max(0, billable_bytes - FREE_BYTES)
    return (chargeable / (1024.0 ** 3)) * RATE_PER_GB_MONTH


async def _make_user(conn: asyncpg.Connection, suffix: str) -> uuid.UUID:
    uid = uuid.uuid4()
    email = f"{_TAG}{suffix}@example-kerf-t402.invalid"
    await conn.execute(
        "INSERT INTO users (id, email, password_hash, name) VALUES ($1, $2, 'x', $3)",
        uid, email, f"T402 Test {suffix}",
    )
    return uid


async def _make_workspace(conn: asyncpg.Connection, user_id: uuid.UUID, suffix: str) -> uuid.UUID:
    wid = uuid.uuid4()
    slug = f"{_TAG}ws-{suffix}"
    await conn.execute(
        "INSERT INTO workspaces (id, slug, name, created_by) VALUES ($1, $2, $3, $4)",
        wid, slug, f"T402 Workspace {suffix}", user_id,
    )
    return wid


async def _make_blob(conn: asyncpg.Connection, oid: str, size_bytes: int, workspace_id: uuid.UUID) -> None:
    await conn.execute(
        """
        INSERT INTO blob_objects (oid, size_bytes, first_workspace_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (oid) DO NOTHING
        """,
        oid, size_bytes, workspace_id,
    )


async def _seed_balance(conn: asyncpg.Connection, user_id: uuid.UUID, amount: float) -> None:
    await conn.execute(
        """
        INSERT INTO cloud_user_balances (user_id, credits_usd)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET credits_usd = $2
        """,
        user_id, amount,
    )


async def _get_balance(conn: asyncpg.Connection, user_id: uuid.UUID) -> float:
    val = await conn.fetchval(
        "SELECT credits_usd FROM cloud_user_balances WHERE user_id = $1",
        user_id,
    )
    return float(val) if val is not None else 0.0


async def _count_storage_events(conn: asyncpg.Connection, user_id: uuid.UUID) -> int:
    return await conn.fetchval(
        "SELECT COUNT(*) FROM usage_events WHERE user_id = $1 AND kind = 'storage'",
        user_id,
    )


async def _reset_state_row(conn: asyncpg.Connection) -> None:
    """Reset the idempotency guard to '' so tests start from a clean slate."""
    await conn.execute(
        """
        INSERT INTO billing_scheduler_state (id, last_storage_debit_month)
        VALUES (1, '')
        ON CONFLICT (id) DO UPDATE SET last_storage_debit_month = ''
        """
    )


async def _cleanup(conn: asyncpg.Connection, user_ids: list[uuid.UUID], blob_oids: list[str]) -> None:
    if blob_oids:
        await conn.execute(
            "DELETE FROM blob_objects WHERE oid = ANY($1::text[])",
            blob_oids,
        )
    if user_ids:
        await conn.execute(
            "DELETE FROM workspaces WHERE created_by = ANY($1::uuid[])",
            user_ids,
        )
        await conn.execute(
            "DELETE FROM users WHERE id = ANY($1::uuid[])",
            user_ids,
        )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4)
    yield p
    await p.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_first_tick_runs_sweep(pool):
    """First tick of the month: sweep runs and storage is debited."""
    suffix = str(uuid.uuid4())[:8]
    user_ids: list[uuid.UUID] = []
    blob_oids: list[str] = []

    try:
        async with pool.acquire() as conn:
            await _reset_state_row(conn)
            uid = await _make_user(conn, suffix)
            user_ids.append(uid)
            wid = await _make_workspace(conn, uid, suffix)
            oid = f"{_TAG}oid-{suffix}-100mb"
            blob_oids.append(oid)
            await _make_blob(conn, oid, 100 * 1024 * 1024, wid)
            await _seed_balance(conn, uid, 10.00)

        now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        ran = await run_monthly_storage_debit_if_needed(pool, _now=now)
        assert ran is True, "First tick should have run the sweep"

        async with pool.acquire() as conn:
            n = await _count_storage_events(conn, uid)
            bal = await _get_balance(conn, uid)

        assert n == 1, f"Expected 1 storage event, got {n}"
        want_cost = _expected_cost(100 * 1024 * 1024)
        assert math.isclose(bal, 10.00 - want_cost, abs_tol=1e-4), (
            f"balance {bal:.8f} != expected {10.00 - want_cost:.8f}"
        )

    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, user_ids, blob_oids)


async def test_second_tick_same_month_is_noop(pool):
    """Second tick within the same month: no-op, no double-bill."""
    suffix = str(uuid.uuid4())[:8]
    user_ids: list[uuid.UUID] = []
    blob_oids: list[str] = []

    try:
        async with pool.acquire() as conn:
            await _reset_state_row(conn)
            uid = await _make_user(conn, suffix)
            user_ids.append(uid)
            wid = await _make_workspace(conn, uid, suffix)
            oid = f"{_TAG}oid-{suffix}-100mb-noop"
            blob_oids.append(oid)
            await _make_blob(conn, oid, 100 * 1024 * 1024, wid)
            await _seed_balance(conn, uid, 10.00)

        now = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

        # First tick — should run.
        ran1 = await run_monthly_storage_debit_if_needed(pool, _now=now)
        assert ran1 is True, "First tick should have run"

        async with pool.acquire() as conn:
            n_after_first = await _count_storage_events(conn, uid)
            bal_after_first = await _get_balance(conn, uid)

        # Second tick in the same month — must be a no-op.
        now2 = datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)
        ran2 = await run_monthly_storage_debit_if_needed(pool, _now=now2)
        assert ran2 is False, "Second tick in same month should be a no-op"

        async with pool.acquire() as conn:
            n_after_second = await _count_storage_events(conn, uid)
            bal_after_second = await _get_balance(conn, uid)

        assert n_after_second == n_after_first, (
            f"No-op tick must not write new storage events "
            f"(before={n_after_first}, after={n_after_second})"
        )
        assert math.isclose(bal_after_second, bal_after_first, rel_tol=1e-9), (
            f"Balance should be unchanged after no-op tick: {bal_after_second}"
        )

    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, user_ids, blob_oids)


async def test_tick_next_month_debits_again(pool):
    """Tick after month boundary: sweep runs again (new debit for the next month)."""
    suffix = str(uuid.uuid4())[:8]
    user_ids: list[uuid.UUID] = []
    blob_oids: list[str] = []

    try:
        async with pool.acquire() as conn:
            await _reset_state_row(conn)
            uid = await _make_user(conn, suffix)
            user_ids.append(uid)
            wid = await _make_workspace(conn, uid, suffix)
            oid = f"{_TAG}oid-{suffix}-100mb-next"
            blob_oids.append(oid)
            await _make_blob(conn, oid, 100 * 1024 * 1024, wid)
            await _seed_balance(conn, uid, 20.00)

        # Month 1 tick.
        month1 = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        ran1 = await run_monthly_storage_debit_if_needed(pool, _now=month1)
        assert ran1 is True

        async with pool.acquire() as conn:
            n_after_month1 = await _count_storage_events(conn, uid)

        # Month 2 tick — must run again.
        month2 = datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        ran2 = await run_monthly_storage_debit_if_needed(pool, _now=month2)
        assert ran2 is True, "Tick in new month should run the sweep"

        async with pool.acquire() as conn:
            n_after_month2 = await _count_storage_events(conn, uid)

        assert n_after_month2 == n_after_month1 + 1, (
            f"Expected one new storage event for month 2 "
            f"(had {n_after_month1}, now {n_after_month2})"
        )

    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, user_ids, blob_oids)


class TestStorageBillingWorkerUnit:
    """Unit tests — no DB required."""

    def test_constructible_and_stoppable(self):
        worker = StorageBillingWorker(pool=object(), interval_seconds=60.0)
        assert worker.name == "storage_billing"
        assert not worker._shutdown
        worker.stop()
        assert worker._shutdown
