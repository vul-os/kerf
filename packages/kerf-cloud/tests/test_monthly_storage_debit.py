"""Integration tests for monthly_storage_debit (T-135).

Requires a live Postgres connection via DATABASE_URL env var.
Run: DATABASE_URL=postgres://pc@localhost:5432/kerf?sslmode=disable python3 -m pytest packages/kerf-cloud/tests/test_monthly_storage_debit.py -q

Test workspaces and blob rows are created with unique suffixes and cleaned up
in a finally block — the live DB is never dropped/truncated/reset.
"""
from __future__ import annotations

import math
import os
import uuid

import asyncpg
import pytest
import pytest_asyncio

from kerf_cloud.usage import monthly_storage_debit

DATABASE_URL = os.environ.get("DATABASE_URL", "postgres://pc@localhost:5432/kerf?sslmode=disable")

# Pricing constants (must match config defaults)
FREE_BYTES = 50 * 1024 * 1024          # 50 MB
RATE_PER_GB_MONTH = 0.20

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def expected_cost(billable_bytes: int) -> float:
    chargeable = max(0, billable_bytes - FREE_BYTES)
    return (chargeable / (1024.0 ** 3)) * RATE_PER_GB_MONTH


async def _create_test_user(conn, suffix: str) -> uuid.UUID:
    uid = uuid.uuid4()
    email = f"t135-test-{suffix}@example-kerf-test.invalid"
    await conn.execute(
        "INSERT INTO users (id, email, password_hash, name) VALUES ($1, $2, 'x', $3)",
        uid, email, f"T135 Test {suffix}",
    )
    return uid


async def _create_test_workspace(conn, user_id: uuid.UUID, suffix: str) -> uuid.UUID:
    wid = uuid.uuid4()
    slug = f"t135-ws-{suffix}"
    await conn.execute(
        "INSERT INTO workspaces (id, slug, name, created_by) VALUES ($1, $2, $3, $4)",
        wid, slug, f"T135 Workspace {suffix}", user_id,
    )
    return wid


async def _create_blob(conn, oid: str, size_bytes: int, first_workspace_id) -> None:
    await conn.execute(
        """
        INSERT INTO blob_objects (oid, size_bytes, first_workspace_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (oid) DO NOTHING
        """,
        oid, size_bytes, first_workspace_id,
    )


async def _seed_balance(conn, user_id: uuid.UUID, amount: float) -> None:
    await conn.execute(
        """
        INSERT INTO cloud_user_balances (user_id, credits_usd)
        VALUES ($1, $2)
        ON CONFLICT (user_id) DO UPDATE SET credits_usd = $2
        """,
        user_id, amount,
    )


async def _get_balance(conn, user_id: uuid.UUID) -> float:
    val = await conn.fetchval(
        "SELECT credits_usd FROM cloud_user_balances WHERE user_id = $1",
        user_id,
    )
    return float(val) if val is not None else 0.0


async def _get_storage_events(conn, user_id: uuid.UUID):
    return await conn.fetch(
        "SELECT * FROM usage_events WHERE user_id = $1 AND kind = 'storage'",
        user_id,
    )


async def _cleanup(conn, user_ids, blob_oids):
    # Order: blobs first (FK from blob_objects → workspaces is SET NULL, but
    # we delete them to keep the DB clean), then workspaces (FK workspaces →
    # users has no cascade), then users (cascades cloud_user_balances,
    # usage_events, etc.).
    if blob_oids:
        await conn.execute(
            "DELETE FROM blob_objects WHERE oid = ANY($1::text[])",
            list(blob_oids),
        )
    if user_ids:
        await conn.execute(
            "DELETE FROM workspaces WHERE created_by = ANY($1::uuid[])",
            list(user_ids),
        )
        await conn.execute(
            "DELETE FROM users WHERE id = ANY($1::uuid[])",
            list(user_ids),
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

async def test_above_free_tier_is_debited_correct_amount(pool):
    """Workspace with 100 MB owned blobs (50 MB over free tier) gets charged."""
    suffix = str(uuid.uuid4())[:8]
    user_ids: list[uuid.UUID] = []
    blob_oids: list[str] = []

    try:
        async with pool.acquire() as conn:
            uid = await _create_test_user(conn, suffix)
            user_ids.append(uid)
            wid = await _create_test_workspace(conn, uid, suffix)

            blob_size = 100 * 1024 * 1024
            oid = f"t135-oid-{suffix}-100mb"
            blob_oids.append(oid)
            await _create_blob(conn, oid, blob_size, wid)
            await _seed_balance(conn, uid, 10.00)

        await monthly_storage_debit(pool)

        async with pool.acquire() as conn:
            bal = await _get_balance(conn, uid)
            events = await _get_storage_events(conn, uid)

        want_cost = expected_cost(blob_size)

        assert len(events) == 1, f"Expected 1 storage event, got {len(events)}"
        ev = events[0]
        assert ev["kind"] == "storage"
        assert ev["bytes_delta"] == blob_size
        assert ev["payer"] == "kerf_paid"
        # usd_cost is numeric(12,6) — 6 decimal places. Use abs_tol for comparison.
        assert math.isclose(float(ev["usd_cost"]), want_cost, abs_tol=1e-5), (
            f"usd_cost {float(ev['usd_cost']):.8f} != expected {want_cost:.8f}"
        )
        assert math.isclose(bal, 10.00 - want_cost, abs_tol=1e-4), (
            f"balance {bal:.8f} != expected {10.00 - want_cost:.8f}"
        )

    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, user_ids, blob_oids)


async def test_fork_workspace_pays_zero(pool):
    """A workspace that only holds blob_refs (not first_workspace_id) pays nothing."""
    suffix = str(uuid.uuid4())[:8]
    user_ids: list[uuid.UUID] = []
    blob_oids: list[str] = []

    try:
        async with pool.acquire() as conn:
            uid_owner = await _create_test_user(conn, f"{suffix}-own")
            user_ids.append(uid_owner)
            wid_owner = await _create_test_workspace(conn, uid_owner, f"{suffix}-own")

            uid_fork = await _create_test_user(conn, f"{suffix}-fork")
            user_ids.append(uid_fork)

            # Blob attributed to owner only — fork workspace has no blob_objects rows
            oid = f"t135-oid-{suffix}-fork"
            blob_oids.append(oid)
            await _create_blob(conn, oid, 200 * 1024 * 1024, wid_owner)

            await _seed_balance(conn, uid_owner, 5.00)
            await _seed_balance(conn, uid_fork, 5.00)

        await monthly_storage_debit(pool)

        async with pool.acquire() as conn:
            fork_events = await _get_storage_events(conn, uid_fork)
            fork_bal = await _get_balance(conn, uid_fork)

        assert len(fork_events) == 0, (
            f"Fork workspace should have 0 storage events, got {len(fork_events)}"
        )
        assert math.isclose(fork_bal, 5.00, rel_tol=1e-6), (
            f"Fork balance should be unchanged 5.00, got {fork_bal}"
        )

    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, user_ids, blob_oids)


async def test_under_free_tier_no_charge(pool):
    """A workspace with only 10 MB of owned blobs (under 50 MB free) is not charged."""
    suffix = str(uuid.uuid4())[:8]
    user_ids: list[uuid.UUID] = []
    blob_oids: list[str] = []

    try:
        async with pool.acquire() as conn:
            uid = await _create_test_user(conn, suffix)
            user_ids.append(uid)
            wid = await _create_test_workspace(conn, uid, suffix)

            oid = f"t135-oid-{suffix}-10mb"
            blob_oids.append(oid)
            await _create_blob(conn, oid, 10 * 1024 * 1024, wid)
            await _seed_balance(conn, uid, 3.00)

        await monthly_storage_debit(pool)

        async with pool.acquire() as conn:
            events = await _get_storage_events(conn, uid)
            bal = await _get_balance(conn, uid)

        assert len(events) == 0, (
            f"Under-free-tier workspace should have 0 events, got {len(events)}"
        )
        assert math.isclose(bal, 3.00, rel_tol=1e-6), (
            f"Balance should be unchanged 3.00, got {bal}"
        )

    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, user_ids, blob_oids)


async def test_orphan_null_workspace_not_billed(pool):
    """A blob_objects row with first_workspace_id = NULL is not billed to anyone."""
    suffix = str(uuid.uuid4())[:8]
    blob_oids: list[str] = []

    try:
        async with pool.acquire() as conn:
            oid = f"t135-oid-{suffix}-orphan"
            blob_oids.append(oid)
            await _create_blob(conn, oid, 500 * 1024 * 1024, None)

            count_before = await conn.fetchval(
                "SELECT COUNT(*) FROM usage_events WHERE kind='storage'"
            )

        await monthly_storage_debit(pool)

        async with pool.acquire() as conn:
            count_after = await conn.fetchval(
                "SELECT COUNT(*) FROM usage_events WHERE kind='storage'"
            )
            # Orphan blob still exists with NULL workspace
            orphan_exists = await conn.fetchval(
                "SELECT COUNT(*) FROM blob_objects WHERE oid = $1 AND first_workspace_id IS NULL",
                oid,
            )

        assert count_after == count_before, (
            f"No new storage events should be written for orphan blobs "
            f"(before={count_before}, after={count_after})"
        )
        assert orphan_exists == 1, "Orphan blob row should still exist with NULL workspace"

    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, [], blob_oids)


async def test_usage_event_row_written_with_correct_fields(pool):
    """Verify all fields on the usage_events row are correct for a billed workspace."""
    suffix = str(uuid.uuid4())[:8]
    user_ids: list[uuid.UUID] = []
    blob_oids: list[str] = []

    try:
        async with pool.acquire() as conn:
            uid = await _create_test_user(conn, suffix)
            user_ids.append(uid)
            wid = await _create_test_workspace(conn, uid, suffix)

            blob_size = 60 * 1024 * 1024  # 10 MB over free tier
            oid = f"t135-oid-{suffix}-60mb"
            blob_oids.append(oid)
            await _create_blob(conn, oid, blob_size, wid)
            await _seed_balance(conn, uid, 20.00)

        await monthly_storage_debit(pool)

        async with pool.acquire() as conn:
            events = await _get_storage_events(conn, uid)
            bal = await _get_balance(conn, uid)

        assert len(events) == 1
        ev = events[0]
        assert ev["user_id"] == uid
        assert ev["project_id"] is None
        assert ev["kind"] == "storage"
        assert ev["bytes_delta"] == blob_size
        assert ev["payer"] == "kerf_paid"

        want_cost = expected_cost(blob_size)
        # usd_cost is numeric(12,6) — 6 decimal places; abs_tol accommodates rounding.
        assert math.isclose(float(ev["usd_cost"]), want_cost, abs_tol=1e-5)
        assert math.isclose(bal, 20.00 - want_cost, abs_tol=1e-4)

    finally:
        async with pool.acquire() as conn:
            await _cleanup(conn, user_ids, blob_oids)
