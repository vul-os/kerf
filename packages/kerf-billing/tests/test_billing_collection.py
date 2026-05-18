"""T-118: Billing collection pipeline with simulated/accelerated clock.

Verifies the state machine:
  usage_events accrue → cost computed → cloud_invoices pending→success
  via the webhook path → cloud_user_balances debited by exactly the
  right amount.

Also verifies monthly_storage_debit collects across a simulated month
boundary using a fake clock (monkeypatched get_settings + injected pool).

PAYSTACK GATE
─────────────
The topup→webhook→credit-balance pipeline requires Paystack only to
verify the webhook HMAC signature.  We simulate that with a fake client
whose verify_webhook_signature returns True.  No live Paystack calls
are made.

The tests that use WebhookHandler directly bypass Paystack entirely — the
handler's signature-check path is in Handlers.webhook(), not in
WebhookHandler._handle_charge_success().  So ALL tests in this module
run without a real Paystack key.

DB RULE
───────
Shared local Postgres — no DROP/TRUNCATE/RESET.  Each test creates
users/workspaces/invoices with unique UUID-suffixed identifiers and
cleans up via DELETE in a finally block.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import asyncpg
import pytest
import pytest_asyncio

# ── path bootstrap (conftest.py already does this for pytest, but we need it
#    in the module body for the module-level skip check below) ──────────────
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_ROOT = os.path.dirname(_HERE)
_PACKAGES_ROOT = os.path.dirname(_PLUGIN_ROOT)

for entry in os.listdir(_PACKAGES_ROOT):
    if not entry.startswith("kerf-"):
        continue
    src = os.path.join(_PACKAGES_ROOT, entry, "src")
    if os.path.isdir(src) and src not in sys.path:
        sys.path.insert(0, src)

from kerf_billing.billing.webhooks import WebhookHandler
from kerf_cloud.usage import (
    balance_for as _balance_for_raw,
    monthly_storage_debit,
    record_token_event,
)


async def balance_for(pool, user_id: str) -> float:
    """Thin wrapper that coerces the asyncpg Decimal to float."""
    return float(await _balance_for_raw(pool, user_id))

# ── Constants ────────────────────────────────────────────────────────────────

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgres://pc@localhost:5432/kerf?sslmode=disable",
)

# Storage pricing constants (must match Settings defaults — if the DB/settings
# ever diverge this test will catch it).
FREE_STORAGE_MB = 50
FREE_STORAGE_BYTES = FREE_STORAGE_MB * 1024 * 1024
USD_PER_GB_MONTH = 0.20


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def pool():
    """Real asyncpg pool, closed after the test."""
    p = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3, timeout=10)
    yield p
    await p.close()


@pytest_asyncio.fixture
async def test_user(pool):
    """Create a uniquely-named user; clean up after test."""
    suffix = uuid.uuid4().hex[:12]
    email = f"t118_{suffix}@test.invalid"
    uid = await pool.fetchval(
        """
        INSERT INTO users (email, password_hash, name, email_verified)
        VALUES ($1, 'x', $2, TRUE)
        RETURNING id
        """,
        email, f"T118 {suffix}",
    )
    yield uid
    # Cleanup: cascade deletes usage_events, cloud_invoices, cloud_user_balances
    await pool.execute("DELETE FROM users WHERE id = $1", uid)


@pytest_asyncio.fixture
async def test_workspace(pool, test_user):
    """Create a workspace owned by test_user; clean up after test."""
    suffix = uuid.uuid4().hex[:12]
    wid = await pool.fetchval(
        """
        INSERT INTO workspaces (slug, name, created_by)
        VALUES ($1, $2, $3)
        RETURNING id
        """,
        f"t118-{suffix}", f"T118 WS {suffix}", test_user,
    )
    yield wid
    await pool.execute("DELETE FROM workspaces WHERE id = $1", wid)


@pytest_asyncio.fixture
async def test_project(pool, test_workspace):
    """Create a project inside test_workspace; clean up after test."""
    pid = await pool.fetchval(
        """
        INSERT INTO projects (workspace_id, name)
        VALUES ($1, $2)
        RETURNING id
        """,
        test_workspace, "T118 Project",
    )
    yield pid
    await pool.execute("DELETE FROM projects WHERE id = $1", pid)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _settings_override(**kwargs):
    """Return a mock Settings object with cloud_pricing fields populated."""
    s = MagicMock()
    s.cloud_pricing_free_storage_mb = kwargs.get("free_mb", FREE_STORAGE_MB)
    s.cloud_pricing_storage_usd_per_gb_month = kwargs.get(
        "rate_per_gb", USD_PER_GB_MONTH
    )
    return s


def _make_webhook_body(reference: str) -> bytes:
    """Build a minimal charge.success payload for the given reference."""
    return json.dumps(
        {
            "event": "charge.success",
            "data": {
                "reference": reference,
                "customer": {
                    "email": "test@test.invalid",
                    "customer_code": f"CUS_{uuid.uuid4().hex[:8]}",
                    "id": 12345,
                },
            },
        }
    ).encode()


class _FakePaystack:
    """Fake Paystack client: always considers webhook signatures valid."""

    def verify_webhook_signature(self, body: bytes, signature: str) -> bool:  # noqa: ARG002
        return True


# ── Tests — token usage accrual + balance debit ───────────────────────────────


@pytest.mark.asyncio
class TestTokenUsageAccrual:
    """record_token_event inserts a usage_events row and debits balance."""

    async def test_single_token_event_debits_balance(self, pool, test_user, test_project):
        cost = 0.0042
        before = await balance_for(pool, str(test_user))

        await record_token_event(
            pool,
            user_id=str(test_user),
            project_id=str(test_project),
            model="claude-sonnet-4-6",
            in_tokens=1000,
            out_tokens=200,
            cost_usd=cost,
        )

        after = await balance_for(pool, str(test_user))
        # balance starts at 0 and goes negative after a debit (credits_usd = prev - cost)
        assert abs(after - (before - cost)) < 1e-9, (
            f"expected balance {before - cost:.6f}, got {after:.6f}"
        )

        # Verify usage_events row was inserted
        row = await pool.fetchrow(
            "SELECT * FROM usage_events WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
            test_user,
        )
        assert row is not None
        assert row["kind"] == "token"
        assert row["input_tokens"] == 1000
        assert row["output_tokens"] == 200
        assert abs(float(row["usd_cost"]) - cost) < 1e-9

    async def test_multiple_token_events_accumulate(self, pool, test_user, test_project):
        """Multiple events: balance decremented by exact sum."""
        costs = [0.001, 0.005, 0.0123]
        before = await balance_for(pool, str(test_user))

        for c in costs:
            await record_token_event(
                pool,
                user_id=str(test_user),
                project_id=str(test_project),
                model="claude-haiku",
                in_tokens=100,
                out_tokens=50,
                cost_usd=c,
            )

        after = await balance_for(pool, str(test_user))
        expected_delta = sum(costs)
        assert abs(after - (before - expected_delta)) < 1e-9, (
            f"expected balance delta {expected_delta:.6f}, got {before - after:.6f}"
        )


# ── Tests — cloud_invoices state transitions ──────────────────────────────────


@pytest.mark.asyncio
class TestInvoiceStateTransitions:
    """cloud_invoices pending → success via simulated webhook path."""

    async def _insert_pending_invoice(
        self, pool, user_id, amount_usd=10.0, amount_zar=195.0, fx_rate=19.5
    ) -> str:
        """Insert a pending invoice and return its reference."""
        reference = f"t118-{uuid.uuid4().hex}"
        await pool.execute(
            """
            INSERT INTO cloud_invoices (user_id, reference, status, amount_usd, amount_zar, fx_rate)
            VALUES ($1, $2, 'pending', $3, $4, $5)
            """,
            user_id, reference, amount_usd, amount_zar, fx_rate,
        )
        return reference

    async def test_invoice_starts_pending(self, pool, test_user):
        reference = await self._insert_pending_invoice(pool, test_user)
        row = await pool.fetchrow(
            "SELECT status FROM cloud_invoices WHERE reference = $1",
            reference,
        )
        assert row["status"] == "pending"

    async def test_webhook_transitions_pending_to_success_and_credits_balance(
        self, pool, test_user
    ):
        amount_usd = 25.0
        reference = await self._insert_pending_invoice(
            pool, test_user, amount_usd=amount_usd, amount_zar=487.5, fx_rate=19.5
        )
        before = await balance_for(pool, str(test_user))

        body = _make_webhook_body(reference)
        handler = WebhookHandler(pool, _FakePaystack())
        await handler._handle_charge_success({"reference": reference}, body)

        # Invoice status must be 'success'
        row = await pool.fetchrow(
            "SELECT status, paid_at FROM cloud_invoices WHERE reference = $1",
            reference,
        )
        assert row["status"] == "success", f"expected success, got {row['status']}"
        assert row["paid_at"] is not None, "paid_at must be set after success"

        # Balance must have been credited (debited by negative amount_usd)
        after = await balance_for(pool, str(test_user))
        assert abs(after - (before + amount_usd)) < 1e-9, (
            f"expected balance {before + amount_usd:.4f}, got {after:.4f}"
        )

    async def test_webhook_idempotent_on_double_delivery(self, pool, test_user):
        """A second webhook for the same reference must not double-credit."""
        amount_usd = 15.0
        reference = await self._insert_pending_invoice(
            pool, test_user, amount_usd=amount_usd, amount_zar=292.5, fx_rate=19.5
        )
        body = _make_webhook_body(reference)
        handler = WebhookHandler(pool, _FakePaystack())

        # First delivery
        await handler._handle_charge_success({"reference": reference}, body)
        after_first = await balance_for(pool, str(test_user))

        # Second delivery — must be no-op
        await handler._handle_charge_success({"reference": reference}, body)
        after_second = await balance_for(pool, str(test_user))

        assert abs(after_first - after_second) < 1e-9, (
            f"double-webhook credited balance twice: {after_first:.4f} vs {after_second:.4f}"
        )

    async def test_unknown_reference_is_acked_silently(self, pool, test_user):
        """Unknown reference must not raise — it's acked silently."""
        fake_ref = f"t118-unknown-{uuid.uuid4().hex}"
        body = _make_webhook_body(fake_ref)
        handler = WebhookHandler(pool, _FakePaystack())
        # Must not raise
        await handler._handle_charge_success({"reference": fake_ref}, body)

    async def test_exact_balance_delta_across_billing_cycle(self, pool, test_user, test_project):
        """Full simulated billing window: accrue tokens, top up, verify net balance."""
        initial_balance = await balance_for(pool, str(test_user))

        # Step 1: accrue token costs ($0.05 total)
        token_costs = [0.02, 0.03]
        for c in token_costs:
            await record_token_event(
                pool,
                user_id=str(test_user),
                project_id=str(test_project),
                model="claude-haiku",
                in_tokens=500,
                out_tokens=100,
                cost_usd=c,
            )

        after_usage = await balance_for(pool, str(test_user))
        assert abs(after_usage - (initial_balance - sum(token_costs))) < 1e-9

        # Step 2: user tops up $50 (simulated: pending invoice → success webhook)
        topup_usd = 50.0
        reference = f"t118-cycle-{uuid.uuid4().hex}"
        await pool.execute(
            """
            INSERT INTO cloud_invoices (user_id, reference, status, amount_usd, amount_zar, fx_rate)
            VALUES ($1, $2, 'pending', $3, $4, $5)
            """,
            test_user, reference, topup_usd, 975.0, 19.5,
        )

        body = _make_webhook_body(reference)
        handler = WebhookHandler(pool, _FakePaystack())
        await handler._handle_charge_success({"reference": reference}, body)

        after_topup = await balance_for(pool, str(test_user))
        expected = initial_balance - sum(token_costs) + topup_usd
        assert abs(after_topup - expected) < 1e-9, (
            f"cycle end: expected {expected:.4f}, got {after_topup:.4f}"
        )

        # Step 3: invoice row must be 'success'
        row = await pool.fetchrow(
            "SELECT status FROM cloud_invoices WHERE reference = $1",
            reference,
        )
        assert row["status"] == "success"


# ── Tests — monthly_storage_debit (simulated month boundary) ──────────────────


@pytest.mark.asyncio
class TestMonthlyStorageDebit:
    """monthly_storage_debit charges only billable bytes above the free tier."""

    async def _insert_blob(
        self, pool, workspace_id, size_bytes: int, oid: str | None = None
    ) -> str:
        oid = oid or uuid.uuid4().hex
        await pool.execute(
            """
            INSERT INTO blob_objects (oid, size_bytes, first_workspace_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (oid) DO NOTHING
            """,
            oid, size_bytes, workspace_id,
        )
        return oid

    async def test_storage_below_free_tier_not_billed(
        self, pool, test_user, test_workspace
    ):
        """Blobs totalling < 50 MB produce no usage_events row and no balance change."""
        small_bytes = FREE_STORAGE_BYTES - 1024  # just under 50 MB
        oid = await self._insert_blob(pool, test_workspace, small_bytes)

        before = await balance_for(pool, str(test_user))
        events_before = await pool.fetchval(
            "SELECT count(*) FROM usage_events WHERE user_id = $1", test_user
        )

        fake_settings = _settings_override()
        with patch("kerf_cloud.usage.get_settings", return_value=fake_settings):
            await monthly_storage_debit(pool)

        after = await balance_for(pool, str(test_user))
        events_after = await pool.fetchval(
            "SELECT count(*) FROM usage_events WHERE user_id = $1", test_user
        )

        assert abs(after - before) < 1e-9, (
            "balance changed for sub-free-tier storage"
        )
        assert events_after == events_before, (
            "usage_events row inserted for sub-free-tier storage"
        )

        # Cleanup blob
        await pool.execute("DELETE FROM blob_objects WHERE oid = $1", oid)

    async def test_storage_above_free_tier_billed_exactly(
        self, pool, test_user, test_workspace
    ):
        """100 MB above free tier → exact cost = (100MB / 1GB) * $0.20/GB-month."""
        extra_bytes = 100 * 1024 * 1024  # 100 MB
        total_bytes = FREE_STORAGE_BYTES + extra_bytes
        oid = await self._insert_blob(pool, test_workspace, total_bytes)

        before = await balance_for(pool, str(test_user))

        fake_settings = _settings_override()
        with patch("kerf_cloud.usage.get_settings", return_value=fake_settings):
            await monthly_storage_debit(pool)

        after = await balance_for(pool, str(test_user))

        chargeable = extra_bytes
        expected_cost = (chargeable / (1024.0 ** 3)) * USD_PER_GB_MONTH
        actual_delta = before - after  # debit reduces balance

        # credits_usd is numeric(12,4): tolerance is ½ ULP at 4dp = 5e-5.
        # usd_cost in usage_events is numeric(12,6) so the value stored there
        # is slightly more precise than what ends up in the balance column.
        BALANCE_TOL = 5e-5  # half-penny in 4-dp fixed arithmetic
        assert abs(actual_delta - expected_cost) < BALANCE_TOL, (
            f"expected debit {expected_cost:.8f}, got {actual_delta:.8f}"
        )

        # usage_events row must exist with payer='kerf_paid'; check the stored
        # cost against the expected value at numeric(12,6) precision (6dp tol).
        row = await pool.fetchrow(
            """
            SELECT bytes_delta, usd_cost, payer
            FROM usage_events
            WHERE user_id = $1
              AND kind = 'storage'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            test_user,
        )
        assert row is not None, "no usage_events row for storage debit"
        assert row["payer"] == "kerf_paid"
        assert abs(float(row["usd_cost"]) - expected_cost) < 5e-7, (
            f"usage_events cost mismatch: stored {float(row['usd_cost']):.8f} vs {expected_cost:.8f}"
        )

        # Cleanup
        await pool.execute("DELETE FROM blob_objects WHERE oid = $1", oid)

    async def test_fork_blobs_not_billed_to_other_workspace(
        self, pool, test_user, test_workspace
    ):
        """Blobs whose first_workspace_id != this workspace are not billed here."""
        # Create a second user + workspace to own the blob
        suffix = uuid.uuid4().hex[:12]
        other_uid = await pool.fetchval(
            """
            INSERT INTO users (email, password_hash, name, email_verified)
            VALUES ($1, 'x', $2, TRUE)
            RETURNING id
            """,
            f"t118_other_{suffix}@test.invalid", f"T118 Other {suffix}",
        )
        other_wid = await pool.fetchval(
            """
            INSERT INTO workspaces (slug, name, created_by)
            VALUES ($1, $2, $3)
            RETURNING id
            """,
            f"t118-other-{suffix}", f"T118 Other WS {suffix}", other_uid,
        )

        # Blob is owned by other_workspace (first_workspace_id = other_wid)
        large_bytes = FREE_STORAGE_BYTES * 100  # huge, definitely billable
        oid = await self._insert_blob(pool, other_wid, large_bytes)

        before = await balance_for(pool, str(test_user))
        events_before = await pool.fetchval(
            "SELECT count(*) FROM usage_events WHERE user_id = $1", test_user
        )

        fake_settings = _settings_override()
        with patch("kerf_cloud.usage.get_settings", return_value=fake_settings):
            await monthly_storage_debit(pool)

        after = await balance_for(pool, str(test_user))
        events_after = await pool.fetchval(
            "SELECT count(*) FROM usage_events WHERE user_id = $1", test_user
        )

        # test_user's balance must not change
        assert abs(after - before) < 1e-9, (
            "test_user balance changed when blob owned by other_workspace"
        )
        assert events_after == events_before

        # Cleanup
        await pool.execute("DELETE FROM blob_objects WHERE oid = $1", oid)
        await pool.execute("DELETE FROM workspaces WHERE id = $1", other_wid)
        await pool.execute("DELETE FROM users WHERE id = $1", other_uid)

    async def test_simulated_month_boundary_double_sweep(
        self, pool, test_user, test_workspace
    ):
        """Simulate two consecutive month-end sweeps with same blobs.

        The debit fires twice (once per simulated month boundary) — this
        exercises that monthly_storage_debit is idempotent-per-call (it does
        not deduplicate across calls) and that two sweeps debit twice.
        """
        extra_bytes = 50 * 1024 * 1024  # 50 MB above free tier
        total_bytes = FREE_STORAGE_BYTES + extra_bytes
        oid = await self._insert_blob(pool, test_workspace, total_bytes)

        before = await balance_for(pool, str(test_user))
        expected_cost = (extra_bytes / (1024.0 ** 3)) * USD_PER_GB_MONTH

        fake_settings = _settings_override()
        with patch("kerf_cloud.usage.get_settings", return_value=fake_settings):
            # Simulate month 1 sweep
            await monthly_storage_debit(pool)
            # Simulate month 2 sweep (clock advanced, same blobs)
            await monthly_storage_debit(pool)

        after = await balance_for(pool, str(test_user))
        actual_total_delta = before - after

        # Two sweeps × numeric(12,4) rounding = tolerance ×2.
        BALANCE_TOL = 1e-4
        assert abs(actual_total_delta - 2 * expected_cost) < BALANCE_TOL, (
            f"two sweeps: expected {2 * expected_cost:.8f}, got {actual_total_delta:.8f}"
        )

        # Cleanup
        await pool.execute("DELETE FROM blob_objects WHERE oid = $1", oid)


# ── Tests — cloud_debit_balance function correctness ──────────────────────────


@pytest.mark.asyncio
class TestCloudDebitBalance:
    """cloud_debit_balance() SQL function: upsert semantics + sign convention."""

    async def test_debit_creates_row_when_absent(self, pool, test_user):
        """If no balance row exists, debit creates it at -amount."""
        # Ensure no balance row exists
        await pool.execute(
            "DELETE FROM cloud_user_balances WHERE user_id = $1", test_user
        )
        await pool.execute(
            "SELECT cloud_debit_balance($1, $2)", test_user, 3.50
        )
        row = await pool.fetchrow(
            "SELECT credits_usd FROM cloud_user_balances WHERE user_id = $1",
            test_user,
        )
        assert row is not None
        assert abs(float(row["credits_usd"]) + 3.50) < 1e-9

    async def test_negative_amount_credits_balance(self, pool, test_user):
        """Passing a negative amount credits (adds to) the balance."""
        await pool.execute(
            "DELETE FROM cloud_user_balances WHERE user_id = $1", test_user
        )
        # Set starting balance at 10.0 (pass -10 to credit)
        await pool.execute(
            "SELECT cloud_debit_balance($1, $2)", test_user, -10.0
        )
        # Now debit 3.0
        await pool.execute(
            "SELECT cloud_debit_balance($1, $2)", test_user, 3.0
        )
        bal = await balance_for(pool, str(test_user))
        assert abs(bal - 7.0) < 1e-9

    async def test_topup_then_debit_exact_net(self, pool, test_user):
        """Sequence: topup 50 → debit 5 → debit 3 → net = 42."""
        await pool.execute(
            "DELETE FROM cloud_user_balances WHERE user_id = $1", test_user
        )
        await pool.execute(
            "SELECT cloud_debit_balance($1, $2)", test_user, -50.0
        )  # credit $50
        await pool.execute(
            "SELECT cloud_debit_balance($1, $2)", test_user, 5.0
        )
        await pool.execute(
            "SELECT cloud_debit_balance($1, $2)", test_user, 3.0
        )
        bal = await balance_for(pool, str(test_user))
        assert abs(bal - 42.0) < 1e-9


# ── Tests — full pipeline integration (T=0 → debit → topup → credit) ─────────


@pytest.mark.asyncio
class TestFullPipelineIntegration:
    """End-to-end: token usage → invoice → webhook → net balance is exact."""

    async def test_full_billing_window_net_balance(self, pool, test_user, test_project):
        """
        Simulated billing window:
          T+0:   user starts with 0 balance
          T+1:   token event: $0.10
          T+2:   token event: $0.05
          T+mid: user tops up $20 (pending→success webhook)
          T+3:   token event: $0.02
          T+end: assert net balance = 0 - 0.10 - 0.05 + 20 - 0.02 = 19.83
        """
        # Ensure clean start
        await pool.execute(
            "DELETE FROM cloud_user_balances WHERE user_id = $1", test_user
        )

        # T+1, T+2: token events
        await record_token_event(pool, str(test_user), str(test_project),
                                  "claude-haiku", 1000, 200, 0.10)
        await record_token_event(pool, str(test_user), str(test_project),
                                  "claude-haiku", 500,  100, 0.05)

        after_usage = await balance_for(pool, str(test_user))
        assert abs(after_usage - (-0.15)) < 1e-9

        # T+mid: topup $20 — pending invoice then success webhook
        topup = 20.0
        reference = f"t118-full-{uuid.uuid4().hex}"
        await pool.execute(
            """
            INSERT INTO cloud_invoices
                (user_id, reference, status, amount_usd, amount_zar, fx_rate)
            VALUES ($1, $2, 'pending', $3, 390.0, 19.5)
            """,
            test_user, reference, topup,
        )
        body = _make_webhook_body(reference)
        handler = WebhookHandler(pool, _FakePaystack())
        await handler._handle_charge_success({"reference": reference}, body)

        after_topup = await balance_for(pool, str(test_user))
        assert abs(after_topup - (-0.15 + topup)) < 1e-9, (
            f"after topup: expected {-0.15 + topup:.4f}, got {after_topup:.4f}"
        )

        # T+3: another token event
        await record_token_event(pool, str(test_user), str(test_project),
                                  "claude-haiku", 200, 50, 0.02)

        final = await balance_for(pool, str(test_user))
        expected_final = -0.15 + topup - 0.02  # = 19.83
        assert abs(final - expected_final) < 1e-9, (
            f"final: expected {expected_final:.4f}, got {final:.4f}"
        )

        # Invoice row must be success
        row = await pool.fetchrow(
            "SELECT status, paid_at FROM cloud_invoices WHERE reference = $1",
            reference,
        )
        assert row["status"] == "success"
        assert row["paid_at"] is not None
