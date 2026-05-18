"""Three-bucket quota enforcement — T-117.

Tests the actual enforcement points in kerf_billing.buckets.pick_bucket and
kerf_billing.spend.commit_spend against the shared local Postgres.

DB contract
-----------
- Uses ``DATABASE_URL`` from the environment; skips if not set.
- Creates uniquely-suffixed users / model_prices rows.
- Cleans up via DELETE (never TRUNCATE/DROP) in a finally block.
- Passes regardless of other pre-existing rows in the DB.

Enforcement points asserted
---------------------------
1. ``pick_bucket`` (pure selector): kerf_free rejects non-cheap models;
   free quota exhaustion falls through to paid/402; byo wins when toggle on.
2. ``load_user_billing`` + ``load_model_info``: DB round-trip snapshot loaders.
3. ``commit_spend`` (KerfFree path): decrements free_tokens_*_remaining in DB,
   inserts usage_events row with payer='kerf_free'.
4. ``commit_spend`` (KerfPaid path): debits credits_usd from
   cloud_user_balances, inserts usage_events row with payer='kerf_paid'.
5. ``commit_spend`` (Byo path): inserts usage_events row with payer='byo_X',
   leaves cloud_user_balances entirely unchanged.
"""
from __future__ import annotations

import os
import uuid
import asyncio
from typing import Optional

import pytest
import asyncpg

from kerf_billing.buckets import (
    Byo,
    InsufficientCredits,
    KerfFree,
    KerfPaid,
    ModelInfo,
    UserBilling,
    load_model_info,
    load_user_billing,
    pick_bucket,
)
from kerf_billing.spend import commit_spend


# ── DB fixture helpers ───────────────────────────────────────────────────────

_DB_URL: Optional[str] = os.environ.get("DATABASE_URL")


def _db_required():
    """Skip this test if no DATABASE_URL is set."""
    if not _DB_URL:
        pytest.skip("DATABASE_URL not set")


async def _pool() -> asyncpg.Pool:
    """Return a fresh asyncpg pool for the test DB."""
    return await asyncpg.create_pool(_DB_URL, min_size=1, max_size=3, timeout=10)


# ── Unique-suffix helpers (avoid collision with live data) ───────────────────

def _uid(label: str) -> str:
    """Stable uuid-shaped string unique to this test run."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"t117-{label}-{uuid.uuid4()}"))


def _email(label: str) -> str:
    return f"t117-{label}-{uuid.uuid4().hex[:8]}@test.invalid"


# ── Pure pick_bucket tests (no DB required) ──────────────────────────────────

class TestPickBucketKerfFree:
    """kerf_free: only cheap-tier models are allowed; quota exhaustion blocks."""

    def _user(self, **kw):
        defaults = dict(
            user_id="u-test",
            prefer_byo=False,
            credits_usd=0.0,
            free_tokens_in_remaining=100_000,
            free_tokens_out_remaining=20_000,
            byo_providers=frozenset(),
        )
        defaults.update(kw)
        return UserBilling(**defaults)

    def _cheap_model(self):
        return ModelInfo(provider="anthropic", model_id="claude-haiku-4", cheap_tier_eligible=True)

    def _expensive_model(self):
        return ModelInfo(provider="anthropic", model_id="claude-opus-4", cheap_tier_eligible=False)

    # --- cheap model + free quota → kerf_free ---
    def test_cheap_model_with_quota_picks_free(self):
        result = pick_bucket(self._user(), self._cheap_model(), estimated_cost_usd=0.001)
        assert isinstance(result, KerfFree), (
            "kerf_free MUST be chosen for a cheap-tier model when free quota remains"
        )

    # --- non-cheap model → must NOT route to kerf_free ---
    def test_non_cheap_model_is_rejected_from_free(self):
        """A non-cheap model under a zero-credit, no-byo user → InsufficientCredits."""
        result = pick_bucket(
            self._user(credits_usd=0.0),
            self._expensive_model(),
            estimated_cost_usd=0.10,
        )
        assert not isinstance(result, KerfFree), (
            "kerf_free MUST NOT accept a non-cheap-tier model — enforcement gap!"
        )
        assert isinstance(result, InsufficientCredits), (
            "With no credits and no BYO, a non-cheap model must return InsufficientCredits"
        )

    # --- non-cheap model but has credits → KerfPaid (not KerfFree) ---
    def test_non_cheap_model_with_credits_routes_to_paid_not_free(self):
        result = pick_bucket(
            self._user(credits_usd=5.0),
            self._expensive_model(),
            estimated_cost_usd=0.10,
        )
        assert isinstance(result, KerfPaid), (
            "Non-cheap model with sufficient credits must route to KerfPaid, not KerfFree"
        )
        assert not isinstance(result, KerfFree), (
            "Non-cheap model MUST NOT be served from kerf_free even when credits exist"
        )

    # --- free quota exhausted → falls through to paid or 402 ---
    def test_free_quota_exhausted_in_tokens_blocks_free(self):
        result = pick_bucket(
            self._user(free_tokens_in_remaining=0, credits_usd=0.0),
            self._cheap_model(),
            estimated_cost_usd=0.001,
        )
        # No free quota, no credits → InsufficientCredits
        assert isinstance(result, InsufficientCredits), (
            "Exhausted free-in quota must block the request when no credits exist"
        )

    def test_free_quota_exhausted_falls_to_paid_when_credits_available(self):
        result = pick_bucket(
            self._user(free_tokens_in_remaining=0, credits_usd=5.0),
            self._cheap_model(),
            estimated_cost_usd=0.001,
        )
        assert isinstance(result, KerfPaid), (
            "Exhausted free quota with credits available must route to KerfPaid"
        )

    def test_estimate_exceeds_remaining_quota_blocks_free(self):
        """Partial-fit: estimate > remaining → kerf_free refuses the request."""
        result = pick_bucket(
            self._user(free_tokens_in_remaining=100, free_tokens_out_remaining=100),
            self._cheap_model(),
            estimated_cost_usd=0.0,
            estimated_input_tokens=10_000,
            estimated_output_tokens=10_000,
        )
        assert not isinstance(result, KerfFree), (
            "pick_bucket must refuse kerf_free when estimate exceeds remaining quota"
        )


class TestPickBucketKerfPaid:
    """kerf_paid: any model allowed; credits must cover estimated cost."""

    def _user(self, credits=10.0, free_in=0):
        return UserBilling(
            user_id="u-paid",
            prefer_byo=False,
            credits_usd=credits,
            free_tokens_in_remaining=free_in,
            free_tokens_out_remaining=0,
            byo_providers=frozenset(),
        )

    def test_any_model_allowed_with_credits(self):
        """kerf_paid places no restriction on model tier."""
        for cheap in (True, False):
            m = ModelInfo(provider="anthropic", model_id="m", cheap_tier_eligible=cheap)
            result = pick_bucket(self._user(), m, estimated_cost_usd=0.50)
            assert isinstance(result, KerfPaid), (
                f"KerfPaid must accept cheap_tier_eligible={cheap} when credits cover cost"
            )

    def test_insufficient_credits_returns_sentinel(self):
        result = pick_bucket(
            self._user(credits=0.001),
            ModelInfo(provider="anthropic", model_id="m", cheap_tier_eligible=False),
            estimated_cost_usd=1.0,
        )
        assert isinstance(result, InsufficientCredits)

    def test_zero_credits_returns_insufficient(self):
        result = pick_bucket(
            self._user(credits=0.0),
            ModelInfo(provider="anthropic", model_id="m", cheap_tier_eligible=False),
            estimated_cost_usd=0.01,
        )
        assert isinstance(result, InsufficientCredits)


class TestPickBucketByo:
    """byo: prefer_byo flag + key present → Byo bucket; zero billing."""

    def _user(self, provider="anthropic"):
        return UserBilling(
            user_id="u-byo",
            prefer_byo=True,
            credits_usd=0.0,
            free_tokens_in_remaining=0,
            free_tokens_out_remaining=0,
            byo_providers=frozenset([provider]),
        )

    def test_byo_picked_when_toggle_and_key_present(self):
        m = ModelInfo(provider="anthropic", model_id="any-model", cheap_tier_eligible=False)
        result = pick_bucket(self._user(), m, estimated_cost_usd=5.0)
        assert isinstance(result, Byo)
        assert result.provider == "anthropic"

    def test_byo_wins_over_free_tier(self):
        """BYO takes priority over kerf_free even when free quota exists."""
        u = UserBilling(
            user_id="u-byo2",
            prefer_byo=True,
            credits_usd=10.0,
            free_tokens_in_remaining=100_000,
            free_tokens_out_remaining=20_000,
            byo_providers=frozenset(["anthropic"]),
        )
        m = ModelInfo(provider="anthropic", model_id="cheap-m", cheap_tier_eligible=True)
        result = pick_bucket(u, m, estimated_cost_usd=0.001)
        assert isinstance(result, Byo), (
            "BYO must beat kerf_free when prefer_byo is True and key is present"
        )

    def test_byo_skipped_when_no_key_for_provider(self):
        """prefer_byo=True but key absent → falls through to free/paid/402."""
        u = UserBilling(
            user_id="u-byo3",
            prefer_byo=True,
            credits_usd=0.0,
            free_tokens_in_remaining=0,
            free_tokens_out_remaining=0,
            byo_providers=frozenset(["openai"]),  # anthropic key missing
        )
        m = ModelInfo(provider="anthropic", model_id="m", cheap_tier_eligible=False)
        result = pick_bucket(u, m, estimated_cost_usd=0.5)
        assert not isinstance(result, Byo), (
            "BYO must not be chosen when the user lacks a key for the model's provider"
        )


# ── DB-backed tests (require real Postgres) ──────────────────────────────────
#
# Each test class creates a unique test user + balance row, runs its
# assertion, then deletes those rows in a finally block.

class TestLoadUserBillingFromDB:
    """load_user_billing reads the correct snapshot from Postgres."""

    async def test_load_snapshot_reflects_db_state(self):
        _db_required()
        pool = await _pool()
        user_id = _uid("load-ub")
        try:
            async with pool.acquire() as conn:
                # Insert test user
                await conn.execute(
                    """
                    INSERT INTO users (id, email, name)
                    VALUES ($1, $2, 'T117 load_user_billing test')
                    """,
                    user_id, _email("load-ub"),
                )
                # Insert balance with known quota
                await conn.execute(
                    """
                    INSERT INTO cloud_user_balances
                        (user_id, credits_usd, free_tokens_in_remaining, free_tokens_out_remaining)
                    VALUES ($1, 7.50, 55000, 11000)
                    """,
                    user_id,
                )

            snapshot = await load_user_billing(pool, user_id)
            assert snapshot.user_id == user_id
            assert snapshot.credits_usd == pytest.approx(7.50)
            assert snapshot.free_tokens_in_remaining == 55_000
            assert snapshot.free_tokens_out_remaining == 11_000
            assert snapshot.prefer_byo is False
            assert snapshot.byo_providers == frozenset()
        finally:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM cloud_user_balances WHERE user_id = $1", user_id
                )
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            await pool.close()


class TestLoadModelInfoFromDB:
    """load_model_info reads cheap_tier_eligible from model_prices."""

    async def test_cheap_flag_loaded_correctly(self):
        _db_required()
        pool = await _pool()
        provider = "t117-test"
        model_id_cheap = f"t117-cheap-{uuid.uuid4().hex[:8]}"
        model_id_dear = f"t117-dear-{uuid.uuid4().hex[:8]}"
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO model_prices
                        (provider, model_id, input_per_mtok, output_per_mtok,
                         cheap_tier_eligible, raw_json)
                    VALUES ($1, $2, 0.25, 1.25, TRUE, '{}')
                    """,
                    provider, model_id_cheap,
                )
                await conn.execute(
                    """
                    INSERT INTO model_prices
                        (provider, model_id, input_per_mtok, output_per_mtok,
                         cheap_tier_eligible, raw_json)
                    VALUES ($1, $2, 15.00, 75.00, FALSE, '{}')
                    """,
                    provider, model_id_dear,
                )

            cheap_info = await load_model_info(pool, provider, model_id_cheap)
            dear_info = await load_model_info(pool, provider, model_id_dear)

            assert cheap_info is not None
            assert cheap_info.cheap_tier_eligible is True

            assert dear_info is not None
            assert dear_info.cheap_tier_eligible is False

            # load_model_info for an unknown model returns None
            missing = await load_model_info(pool, provider, "does-not-exist")
            assert missing is None
        finally:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM model_prices WHERE provider = $1", provider
                )
            await pool.close()


class TestCommitSpendKerfFree:
    """KerfFree path: decrements quota in DB, writes usage_events with payer='kerf_free'."""

    async def test_free_quota_decremented_and_event_written(self):
        _db_required()
        pool = await _pool()
        user_id = _uid("free-spend")
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, email, name) VALUES ($1, $2, 'T117 free spend')",
                    user_id, _email("free-spend"),
                )
                await conn.execute(
                    """
                    INSERT INTO cloud_user_balances
                        (user_id, credits_usd, free_tokens_in_remaining, free_tokens_out_remaining)
                    VALUES ($1, 0, 50000, 10000)
                    """,
                    user_id,
                )

            await commit_spend(
                pool,
                bucket=KerfFree(),
                user_id=user_id,
                project_id=None,
                model="t117-cheap-model",
                input_tokens=1000,
                output_tokens=200,
                cogs_usd=0.001,
                billed_usd=0.001,
            )

            async with pool.acquire() as conn:
                bal = await conn.fetchrow(
                    "SELECT free_tokens_in_remaining, free_tokens_out_remaining "
                    "FROM cloud_user_balances WHERE user_id = $1",
                    user_id,
                )
                ev = await conn.fetchrow(
                    "SELECT payer, input_tokens, output_tokens, usd_cost "
                    "FROM usage_events WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                    user_id,
                )

            # Quota decremented
            assert bal["free_tokens_in_remaining"] == 49_000, (
                "free_tokens_in_remaining should be decremented by input_tokens (1000)"
            )
            assert bal["free_tokens_out_remaining"] == 9_800, (
                "free_tokens_out_remaining should be decremented by output_tokens (200)"
            )

            # credits_usd not touched (no money deducted for free tier)
            async with pool.acquire() as conn:
                cbal = await conn.fetchrow(
                    "SELECT credits_usd FROM cloud_user_balances WHERE user_id = $1",
                    user_id,
                )
            assert float(cbal["credits_usd"]) == pytest.approx(0.0), (
                "KerfFree must NOT deduct credits_usd — it only decrements token quota"
            )

            # usage_events row written with payer='kerf_free'
            assert ev is not None
            assert ev["payer"] == "kerf_free", (
                "usage_events.payer must be 'kerf_free' for the KerfFree bucket"
            )
            assert ev["input_tokens"] == 1000
            assert ev["output_tokens"] == 200
        finally:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM usage_events WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM cloud_user_balances WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            await pool.close()

    async def test_free_quota_clamps_at_zero_not_negative(self):
        """GREATEST(0, ...) ensures quota never goes below 0."""
        _db_required()
        pool = await _pool()
        user_id = _uid("free-clamp")
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, email, name) VALUES ($1, $2, 'T117 free clamp')",
                    user_id, _email("free-clamp"),
                )
                await conn.execute(
                    """
                    INSERT INTO cloud_user_balances
                        (user_id, credits_usd, free_tokens_in_remaining, free_tokens_out_remaining)
                    VALUES ($1, 0, 50, 50)
                    """,
                    user_id,
                )

            # Commit more tokens than remaining quota
            await commit_spend(
                pool,
                bucket=KerfFree(),
                user_id=user_id,
                project_id=None,
                model="t117-cheap-model",
                input_tokens=200,
                output_tokens=200,
                cogs_usd=0.001,
                billed_usd=0.001,
            )

            async with pool.acquire() as conn:
                bal = await conn.fetchrow(
                    "SELECT free_tokens_in_remaining, free_tokens_out_remaining "
                    "FROM cloud_user_balances WHERE user_id = $1",
                    user_id,
                )
            assert bal["free_tokens_in_remaining"] == 0, (
                "free_tokens_in_remaining must clamp to 0, not go negative"
            )
            assert bal["free_tokens_out_remaining"] == 0, (
                "free_tokens_out_remaining must clamp to 0, not go negative"
            )
        finally:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM usage_events WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM cloud_user_balances WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            await pool.close()


class TestCommitSpendKerfPaid:
    """KerfPaid path: debits credits_usd, writes usage_events with payer='kerf_paid'.

    Regression guard (T-117 / T-141): ``_commit_paid`` previously used the
    SQL literal ``-$2`` (unary minus on an untyped asyncpg parameter), which
    raised ``AmbiguousFunctionError`` so the KerfPaid debit never executed.
    Fixed in spend.py to ``VALUES ($1, -$2::numeric)``; these tests now
    assert the debit really happens.
    """

    async def test_credits_debited_and_event_written(self):
        _db_required()
        pool = await _pool()
        user_id = _uid("paid-spend")
        initial_credits = 10.0
        billed = 0.012  # post-markup amount
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, email, name) VALUES ($1, $2, 'T117 paid spend')",
                    user_id, _email("paid-spend"),
                )
                await conn.execute(
                    """
                    INSERT INTO cloud_user_balances (user_id, credits_usd)
                    VALUES ($1, $2)
                    """,
                    user_id, initial_credits,
                )

            await commit_spend(
                pool,
                bucket=KerfPaid(),
                user_id=user_id,
                project_id=None,
                model="t117-expensive-model",
                input_tokens=500,
                output_tokens=100,
                cogs_usd=0.01,
                billed_usd=billed,
            )

            async with pool.acquire() as conn:
                bal = await conn.fetchrow(
                    "SELECT credits_usd FROM cloud_user_balances WHERE user_id = $1",
                    user_id,
                )
                ev = await conn.fetchrow(
                    "SELECT payer, input_tokens, output_tokens, usd_cost "
                    "FROM usage_events WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                    user_id,
                )

            # Balance debited
            assert float(bal["credits_usd"]) == pytest.approx(initial_credits - billed), (
                f"credits_usd must be decremented by billed_usd ({billed})"
            )

            # usage_events row written with payer='kerf_paid'
            assert ev is not None
            assert ev["payer"] == "kerf_paid", (
                "usage_events.payer must be 'kerf_paid' for the KerfPaid bucket"
            )
            assert ev["input_tokens"] == 500
            assert ev["output_tokens"] == 100
            assert float(ev["usd_cost"]) == pytest.approx(billed)
        finally:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM usage_events WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM cloud_user_balances WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            await pool.close()

    async def test_paid_debit_via_cloud_debit_balance_function(self):
        """The cloud_debit_balance() stored function and the inline upsert
        in _commit_paid produce identical semantics — verify both paths
        result in the same final balance."""
        _db_required()
        pool = await _pool()
        user_id = _uid("paid-fn")
        initial_credits = 5.0
        billed = 0.60
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, email, name) VALUES ($1, $2, 'T117 debit fn')",
                    user_id, _email("paid-fn"),
                )
                # Use cloud_debit_balance() directly (negative = credit)
                await conn.execute(
                    "SELECT cloud_debit_balance($1::uuid, $2)",
                    user_id, -initial_credits,
                )

            # commit_spend uses the inline upsert (same semantics)
            await commit_spend(
                pool,
                bucket=KerfPaid(),
                user_id=user_id,
                project_id=None,
                model="t117-model",
                input_tokens=100,
                output_tokens=50,
                cogs_usd=0.50,
                billed_usd=billed,
            )

            async with pool.acquire() as conn:
                bal = await conn.fetchrow(
                    "SELECT credits_usd FROM cloud_user_balances WHERE user_id = $1",
                    user_id,
                )
            assert float(bal["credits_usd"]) == pytest.approx(initial_credits - billed)
        finally:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM usage_events WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM cloud_user_balances WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            await pool.close()


class TestCommitSpendByo:
    """Byo path: zero billing — no balance movement, payer='byo_<provider>'."""

    async def test_byo_no_balance_movement(self):
        _db_required()
        pool = await _pool()
        user_id = _uid("byo-spend")
        initial_credits = 3.0
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, email, name) VALUES ($1, $2, 'T117 byo spend')",
                    user_id, _email("byo-spend"),
                )
                await conn.execute(
                    """
                    INSERT INTO cloud_user_balances (user_id, credits_usd,
                        free_tokens_in_remaining, free_tokens_out_remaining)
                    VALUES ($1, $2, 80000, 16000)
                    """,
                    user_id, initial_credits,
                )

            await commit_spend(
                pool,
                bucket=Byo(provider="anthropic"),
                user_id=user_id,
                project_id=None,
                model="t117-byo-model",
                input_tokens=300,
                output_tokens=80,
                cogs_usd=0.003,
                billed_usd=0.0,
            )

            async with pool.acquire() as conn:
                bal = await conn.fetchrow(
                    "SELECT credits_usd, free_tokens_in_remaining, free_tokens_out_remaining "
                    "FROM cloud_user_balances WHERE user_id = $1",
                    user_id,
                )
                ev = await conn.fetchrow(
                    "SELECT payer, usd_cost "
                    "FROM usage_events WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                    user_id,
                )

            # credits_usd untouched
            assert float(bal["credits_usd"]) == pytest.approx(initial_credits), (
                "BYO must NOT deduct credits_usd — zero billing path"
            )
            # free quota also untouched
            assert bal["free_tokens_in_remaining"] == 80_000, (
                "BYO must NOT decrement free token quota"
            )
            assert bal["free_tokens_out_remaining"] == 16_000, (
                "BYO must NOT decrement free token quota"
            )

            # usage_events written (for user-visible dashboard) with payer='byo_anthropic'
            assert ev is not None
            assert ev["payer"] == "byo_anthropic", (
                "BYO usage_events.payer must be 'byo_<provider>'"
            )
            assert float(ev["usd_cost"]) == pytest.approx(0.0), (
                "BYO usd_cost must be 0 — kerf incurs no cost"
            )
        finally:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM usage_events WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM cloud_user_balances WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            await pool.close()

    async def test_byo_different_providers_payer_suffix(self):
        """payer string is 'byo_<provider>' for any provider, not a fixed string."""
        _db_required()
        pool = await _pool()
        user_id = _uid("byo-prov")
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, email, name) VALUES ($1, $2, 'T117 byo prov')",
                    user_id, _email("byo-prov"),
                )

            await commit_spend(
                pool,
                bucket=Byo(provider="openai"),
                user_id=user_id,
                project_id=None,
                model="gpt-4o",
                input_tokens=50,
                output_tokens=20,
                cogs_usd=0.001,
                billed_usd=0.0,
            )

            async with pool.acquire() as conn:
                ev = await conn.fetchrow(
                    "SELECT payer FROM usage_events WHERE user_id = $1",
                    user_id,
                )
            assert ev["payer"] == "byo_openai"
        finally:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM usage_events WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            await pool.close()


class TestEndToEndBucketEnforcement:
    """Full selector + DB snapshot + spend commit in one flow."""

    async def test_kerf_free_full_flow(self):
        """load_user_billing → pick_bucket → commit_spend for the free path."""
        _db_required()
        pool = await _pool()
        user_id = _uid("e2e-free")
        provider = "t117-e2e"
        model_id = f"t117-cheap-{uuid.uuid4().hex[:8]}"
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, email, name) VALUES ($1, $2, 'T117 e2e free')",
                    user_id, _email("e2e-free"),
                )
                await conn.execute(
                    """
                    INSERT INTO cloud_user_balances
                        (user_id, credits_usd, free_tokens_in_remaining, free_tokens_out_remaining)
                    VALUES ($1, 0, 10000, 2000)
                    """,
                    user_id,
                )
                await conn.execute(
                    """
                    INSERT INTO model_prices
                        (provider, model_id, input_per_mtok, output_per_mtok,
                         cheap_tier_eligible, raw_json)
                    VALUES ($1, $2, 0.25, 1.25, TRUE, '{}')
                    """,
                    provider, model_id,
                )

            billing = await load_user_billing(pool, user_id)
            model_info = await load_model_info(pool, provider, model_id)

            assert model_info is not None
            assert model_info.cheap_tier_eligible is True

            bucket = pick_bucket(
                billing, model_info,
                estimated_cost_usd=0.001,
                estimated_input_tokens=500,
                estimated_output_tokens=100,
            )
            assert isinstance(bucket, KerfFree), (
                "E2E: cheap model + free quota must route to KerfFree"
            )

            await commit_spend(
                pool,
                bucket=bucket,
                user_id=user_id,
                project_id=None,
                model=model_id,
                input_tokens=500,
                output_tokens=100,
                cogs_usd=0.001,
                billed_usd=0.001,
            )

            async with pool.acquire() as conn:
                bal = await conn.fetchrow(
                    "SELECT free_tokens_in_remaining, free_tokens_out_remaining "
                    "FROM cloud_user_balances WHERE user_id = $1",
                    user_id,
                )
            assert bal["free_tokens_in_remaining"] == 9_500
            assert bal["free_tokens_out_remaining"] == 1_900
        finally:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM usage_events WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM cloud_user_balances WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM model_prices WHERE provider = $1", provider)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            await pool.close()

    async def test_non_cheap_model_rejected_from_free_e2e(self):
        """Full DB flow confirms non-cheap model cannot land in KerfFree."""
        _db_required()
        pool = await _pool()
        user_id = _uid("e2e-reject")
        provider = "t117-e2e-reject"
        model_id = f"t117-dear-{uuid.uuid4().hex[:8]}"
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO users (id, email, name) VALUES ($1, $2, 'T117 e2e reject')",
                    user_id, _email("e2e-reject"),
                )
                await conn.execute(
                    """
                    INSERT INTO cloud_user_balances
                        (user_id, credits_usd, free_tokens_in_remaining, free_tokens_out_remaining)
                    VALUES ($1, 0, 100000, 20000)
                    """,
                    user_id,
                )
                await conn.execute(
                    """
                    INSERT INTO model_prices
                        (provider, model_id, input_per_mtok, output_per_mtok,
                         cheap_tier_eligible, raw_json)
                    VALUES ($1, $2, 15.00, 75.00, FALSE, '{}')
                    """,
                    provider, model_id,
                )

            billing = await load_user_billing(pool, user_id)
            model_info = await load_model_info(pool, provider, model_id)

            assert model_info is not None
            assert model_info.cheap_tier_eligible is False

            bucket = pick_bucket(billing, model_info, estimated_cost_usd=0.50)

            assert not isinstance(bucket, KerfFree), (
                "ENFORCEMENT GAP: a non-cheap-tier model routed to KerfFree! "
                f"cheap_tier_eligible=False model '{model_id}' must never reach kerf_free."
            )
            # Zero credits → should be InsufficientCredits
            assert isinstance(bucket, InsufficientCredits), (
                "Non-cheap model + zero credits must return InsufficientCredits (HTTP 402)"
            )
        finally:
            async with pool.acquire() as conn:
                await conn.execute("DELETE FROM cloud_user_balances WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM model_prices WHERE provider = $1", provider)
                await conn.execute("DELETE FROM users WHERE id = $1", user_id)
            await pool.close()
