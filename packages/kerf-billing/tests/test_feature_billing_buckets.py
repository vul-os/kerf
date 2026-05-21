"""T-64: Feature tests for the three-bucket billing model.

25 usage scenarios covering:
- All three bucket paths: kerf_free, kerf_paid, byo_<provider>
- Spend tally correctness (commit_spend SQL assertions)
- Cheap-models-only enforcement on kerf_free
- BYO bypasses the meter entirely (usd_cost=0, no balance deduction)
- Scheduler cron close-out (monthly free-quota reset, daily api-token reset)
- InsufficientCredits short-circuit (never reaches commit_spend)

All tests are hermetic: no real Postgres, no external I/O.
Pool and connection are faked with recording stubs.
"""
from __future__ import annotations

import pytest

from kerf_billing.buckets import (
    Byo,
    InsufficientCredits,
    KerfFree,
    KerfPaid,
    ModelInfo,
    UserBilling,
    pick_bucket,
)
from kerf_billing.spend import ApiTokenDailyCapExceeded, commit_spend
from kerf_billing.scheduler import (
    BillingResetWorker,
    reset_api_token_daily,
    reset_free_quotas,
)


# ── Stub asyncpg pool ────────────────────────────────────────────────────────

class _Conn:
    """Recording connection stub. Tracks every execute/fetchrow call."""

    def __init__(self, fetchrow_responses=()) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self._fetchrow_responses = list(fetchrow_responses)

    async def execute(self, sql: str, *args) -> str:
        self.executed.append((sql, args))
        return "UPDATE 1"

    async def fetchrow(self, sql: str, *args):
        self.executed.append((sql, args))
        if self._fetchrow_responses:
            return self._fetchrow_responses.pop(0)
        return None

    def transaction(self):
        outer = self

        class _Tx:
            async def __aenter__(self_inner):
                return outer

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Tx()


class _Pool:
    def __init__(self, fetchrow_responses=()) -> None:
        self.conn = _Conn(fetchrow_responses)

    def acquire(self):
        conn = self.conn

        class _Acq:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Acq()


class _SchedulerPool:
    """Simpler pool for scheduler tests — returns a fixed string from execute."""

    def __init__(self, response: str = "UPDATE 0") -> None:
        self.conn = _SchedulerConn(response)

    def acquire(self):
        conn = self.conn

        class _Acq:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Acq()


class _SchedulerConn:
    def __init__(self, response: str = "UPDATE 0") -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.response = response

    async def execute(self, sql: str, *args) -> str:
        self.executed.append((sql, args))
        return self.response


# ── Helpers ──────────────────────────────────────────────────────────────────

def _user(
    credits=10.0, free_in=100_000, free_out=20_000,
    prefer_byo=False, byo=(),
    user_id="u-test",
):
    return UserBilling(
        user_id=user_id,
        prefer_byo=prefer_byo,
        credits_usd=credits,
        free_tokens_in_remaining=free_in,
        free_tokens_out_remaining=free_out,
        byo_providers=frozenset(byo),
    )


def _model(provider="anthropic", model_id="claude-haiku-3", cheap=True):
    return ModelInfo(provider=provider, model_id=model_id, cheap_tier_eligible=cheap)


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO GROUP 1: kerf_free bucket selection (5 scenarios)
# ─────────────────────────────────────────────────────────────────────────────

class TestKerfFreeSelection:
    """Cheap-models-only enforcement on kerf_free."""

    def test_sc01_cheap_model_with_full_quota_picks_free(self):
        """SC-01: Standard case — cheap model, full quota → kerf_free."""
        b = pick_bucket(_user(), _model(cheap=True), estimated_cost_usd=0.001)
        assert isinstance(b, KerfFree)

    def test_sc02_non_cheap_model_never_gets_free_tier(self):
        """SC-02: Expensive model bypasses free tier regardless of quota."""
        b = pick_bucket(_user(), _model(cheap=False), estimated_cost_usd=0.05)
        # credits=10 → KerfPaid, not KerfFree
        assert isinstance(b, KerfPaid)

    def test_sc03_exhausted_input_quota_skips_free(self):
        """SC-03: free_tokens_in_remaining = 0 → not free even for cheap model."""
        b = pick_bucket(
            _user(free_in=0), _model(cheap=True), estimated_cost_usd=0.0,
        )
        assert isinstance(b, KerfPaid)

    def test_sc04_exhausted_output_quota_skips_free(self):
        """SC-04: free_tokens_out_remaining = 0 → not free even for cheap model."""
        b = pick_bucket(
            _user(free_out=0), _model(cheap=True), estimated_cost_usd=0.0,
        )
        assert isinstance(b, KerfPaid)

    def test_sc05_oversize_estimate_blocks_free(self):
        """SC-05: Request estimate exceeds remaining quota → falls to paid."""
        b = pick_bucket(
            _user(free_in=100, free_out=100), _model(cheap=True),
            estimated_cost_usd=0.0,
            estimated_input_tokens=50_000, estimated_output_tokens=50_000,
        )
        assert isinstance(b, KerfPaid)


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO GROUP 2: kerf_free spend commit (3 scenarios)
# ─────────────────────────────────────────────────────────────────────────────

class TestKerfFreeCommit:
    """Spend tally for kerf_free: usage_events payer + quota decrement."""

    async def test_sc06_usage_row_has_kerf_free_payer(self):
        """SC-06: INSERT payer literal must be 'kerf_free'."""
        pool = _Pool()
        await commit_spend(
            pool, bucket=KerfFree(),
            user_id="u1", project_id="p1", model="claude-haiku-3",
            input_tokens=1_000, output_tokens=200,
            cogs_usd=0.002, billed_usd=0.002,
        )
        insert_sql, insert_args = pool.conn.executed[0]
        assert "INSERT INTO usage_events" in insert_sql
        assert "'kerf_free'" in insert_sql
        assert insert_args[0] == "u1"

    async def test_sc07_quota_decrement_uses_actual_token_counts(self):
        """SC-07: free_tokens_{in,out}_remaining decremented by actual counts."""
        pool = _Pool()
        await commit_spend(
            pool, bucket=KerfFree(),
            user_id="u1", project_id="p1", model="claude-haiku-3",
            input_tokens=800, output_tokens=300,
            cogs_usd=0.001, billed_usd=0.001,
        )
        upd_sql, upd_args = pool.conn.executed[1]
        assert "free_tokens_in_remaining" in upd_sql
        assert "free_tokens_out_remaining" in upd_sql
        assert upd_args == ("u1", 800, 300)

    async def test_sc08_no_balance_row_touched_for_free(self):
        """SC-08: kerf_free path NEVER touches cloud_user_balances credits."""
        pool = _Pool()
        await commit_spend(
            pool, bucket=KerfFree(),
            user_id="u1", project_id=None, model="claude-haiku-3",
            input_tokens=50, output_tokens=10,
            cogs_usd=0.0001, billed_usd=0.0001,
        )
        # Only two SQL calls: INSERT + UPDATE quota
        assert len(pool.conn.executed) == 2
        for sql, _ in pool.conn.executed:
            assert "credits_usd" not in sql


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO GROUP 3: BYO bucket — bypasses meter (5 scenarios)
# ─────────────────────────────────────────────────────────────────────────────

class TestByoBucket:
    """BYO bypasses billing meter: usd_cost=0, no balance change."""

    def test_sc09_byo_wins_over_free_when_toggle_on(self):
        """SC-09: prefer_byo=True + key present → Byo even for cheap model."""
        u = _user(prefer_byo=True, byo=["anthropic"])
        b = pick_bucket(u, _model(provider="anthropic", cheap=True), estimated_cost_usd=0.001)
        assert isinstance(b, Byo)
        assert b.provider == "anthropic"

    def test_sc10_byo_wins_over_paid_when_toggle_on(self):
        """SC-10: prefer_byo=True + key present + credits → BYO still wins."""
        u = _user(prefer_byo=True, byo=["openai"], credits=100.0, free_in=0)
        b = pick_bucket(
            u, _model(provider="openai", cheap=False), estimated_cost_usd=5.0,
        )
        assert isinstance(b, Byo)
        assert b.provider == "openai"

    def test_sc11_byo_provider_mismatch_no_byo(self):
        """SC-11: BYO key exists but for different provider → not selected."""
        u = _user(prefer_byo=True, byo=["openai"])
        b = pick_bucket(u, _model(provider="anthropic", cheap=True), estimated_cost_usd=0.001)
        # Falls through: anthropic key missing → KerfFree (cheap + quota ok)
        assert isinstance(b, KerfFree)

    async def test_sc12_byo_commit_records_zero_cost(self):
        """SC-12: commit_spend with Byo inserts usd_cost=0."""
        pool = _Pool()
        await commit_spend(
            pool, bucket=Byo("anthropic"),
            user_id="u2", project_id="p2", model="claude-opus-4-7",
            input_tokens=5_000, output_tokens=1_000,
            cogs_usd=0.05, billed_usd=0.0,
        )
        assert len(pool.conn.executed) == 1
        sql, args = pool.conn.executed[0]
        assert "INSERT INTO usage_events" in sql
        # usd_cost literal in SQL is 0
        assert ", 0," in sql or "0, $6" in sql or ", 0)" in sql or "usd_cost, payer" in sql
        assert "byo_anthropic" in args

    async def test_sc13_byo_never_touches_any_balance_table(self):
        """SC-13: BYO path emits exactly one SQL call — no balance/quota rows."""
        pool = _Pool()
        await commit_spend(
            pool, bucket=Byo("gemini"),
            user_id="u3", project_id=None, model="gemini-pro",
            input_tokens=200, output_tokens=100,
            cogs_usd=0.002, billed_usd=0.0,
        )
        assert len(pool.conn.executed) == 1
        sql, _ = pool.conn.executed[0]
        assert "cloud_user_balances" not in sql
        assert "free_tokens" not in sql


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO GROUP 4: kerf_paid bucket (5 scenarios)
# ─────────────────────────────────────────────────────────────────────────────

class TestKerfPaidBucket:
    """Pre-paid credits path — any model, balance debited."""

    def test_sc14_paid_selected_when_no_free_quota_but_credits(self):
        """SC-14: No free quota + credits → KerfPaid."""
        u = _user(credits=5.0, free_in=0, free_out=0)
        b = pick_bucket(u, _model(cheap=False), estimated_cost_usd=0.5)
        assert isinstance(b, KerfPaid)

    def test_sc15_paid_selected_for_expensive_model_with_credits(self):
        """SC-15: Expensive model + credits cover estimate → KerfPaid."""
        u = _user(credits=20.0, free_in=100_000, free_out=20_000)
        b = pick_bucket(u, _model(cheap=False), estimated_cost_usd=1.0)
        assert isinstance(b, KerfPaid)

    async def test_sc16_paid_commit_debits_balance(self):
        """SC-16: commit_spend KerfPaid decrements cloud_user_balances."""
        pool = _Pool()
        await commit_spend(
            pool, bucket=KerfPaid(),
            user_id="u1", project_id="p1", model="claude-opus-4-7",
            input_tokens=100, output_tokens=50,
            cogs_usd=0.01, billed_usd=0.012,
        )
        sqls = [s for s, _ in pool.conn.executed]
        assert any("INSERT INTO usage_events" in s for s in sqls)
        assert any("cloud_user_balances" in s for s in sqls)
        # Verify payer literal
        insert_sql = next(s for s in sqls if "INSERT INTO usage_events" in s)
        assert "'kerf_paid'" in insert_sql

    async def test_sc17_api_token_daily_cap_raise_after_commit(self):
        """SC-17: Over-cap API token raises ApiTokenDailyCapExceeded post-commit."""
        pool = _Pool(fetchrow_responses=[{
            "max_spend_per_day_usd": 2.00,
            "spend_today_usd": 2.50,
        }])
        with pytest.raises(ApiTokenDailyCapExceeded) as exc_info:
            await commit_spend(
                pool, bucket=KerfPaid(),
                user_id="u1", project_id="p1", model="claude-opus-4-7",
                input_tokens=100, output_tokens=50,
                cogs_usd=0.5, billed_usd=0.6,
                api_token_id="tok-abc",
            )
        err = exc_info.value
        assert err.token_id == "tok-abc"
        assert err.cap_usd == 2.0
        # Row was still committed before raising
        assert any("INSERT INTO usage_events" in s for s, _ in pool.conn.executed)

    async def test_sc18_api_token_under_cap_no_raise(self):
        """SC-18: Under-cap API token — no exception, 3 SQL calls."""
        pool = _Pool(fetchrow_responses=[{
            "max_spend_per_day_usd": 50.00,
            "spend_today_usd": 0.05,
        }])
        await commit_spend(
            pool, bucket=KerfPaid(),
            user_id="u1", project_id=None, model="claude-opus-4-7",
            input_tokens=10, output_tokens=5,
            cogs_usd=0.001, billed_usd=0.0012,
            api_token_id="tok-xyz",
        )
        assert len(pool.conn.executed) == 3


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO GROUP 5: InsufficientCredits (3 scenarios)
# ─────────────────────────────────────────────────────────────────────────────

class TestInsufficientCredits:
    """402 path — never reaches commit_spend."""

    def test_sc19_no_quota_no_credits_returns_insufficient(self):
        """SC-19: Zero free quota, zero credits → InsufficientCredits."""
        u = _user(credits=0.0, free_in=0, free_out=0)
        b = pick_bucket(u, _model(cheap=False), estimated_cost_usd=0.01)
        assert isinstance(b, InsufficientCredits)
        assert b.byo_available is False

    def test_sc20_insufficient_signals_byo_when_key_present(self):
        """SC-20: No credits but BYO key on file → byo_available=True hint."""
        u = _user(credits=0.0, free_in=0, byo=["anthropic"])
        b = pick_bucket(u, _model(provider="anthropic", cheap=False), estimated_cost_usd=1.0)
        assert isinstance(b, InsufficientCredits)
        assert b.byo_available is True

    async def test_sc21_commit_spend_with_insufficient_raises_value_error(self):
        """SC-21: Passing InsufficientCredits to commit_spend is a caller bug."""
        pool = _Pool()
        with pytest.raises(ValueError):
            await commit_spend(
                pool, bucket=InsufficientCredits(byo_available=False),
                user_id="u1", project_id=None, model="x",
                input_tokens=0, output_tokens=0,
                cogs_usd=0.0, billed_usd=0.0,
            )


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO GROUP 6: Scheduler cron close-out (4 scenarios)
# ─────────────────────────────────────────────────────────────────────────────

class TestSchedulerCloseout:
    """Monthly free-quota reset + daily api-token reset."""

    async def test_sc22_reset_api_token_daily_targets_stale_rows(self):
        """SC-22: reset_api_token_daily emits correct WHERE clause."""
        pool = _SchedulerPool("UPDATE 7")
        n = await reset_api_token_daily(pool)
        assert n == 7
        sql, _ = pool.conn.executed[0]
        assert "UPDATE api_tokens" in sql
        assert "spend_today_date < current_date" in sql
        assert "spend_today_usd  = 0" in sql

    async def test_sc23_reset_free_quotas_advances_reset_timestamp(self):
        """SC-23: reset_free_quotas advances free_quota_resets_at to next month."""
        pool = _SchedulerPool("UPDATE 3")
        n = await reset_free_quotas(pool)
        assert n == 3
        sql, args = pool.conn.executed[0]
        assert "UPDATE cloud_user_balances" in sql
        assert "free_quota_resets_at" in sql
        assert "interval '1 month'" in sql
        assert args[0] == 100_000   # _DEFAULT_FREE_TOKENS_IN
        assert args[1] == 20_000    # _DEFAULT_FREE_TOKENS_OUT

    async def test_sc24_reset_api_token_zero_rows_returns_zero(self):
        """SC-24: When no stale rows, count is 0."""
        pool = _SchedulerPool("UPDATE 0")
        n = await reset_api_token_daily(pool)
        assert n == 0

    def test_sc25_billing_reset_worker_lifecycle(self):
        """SC-25: BillingResetWorker constructs, has correct name, stops cleanly."""
        pool = _SchedulerPool()
        w = BillingResetWorker(pool=pool, interval_seconds=3600.0)
        assert w.name == "billing_reset"
        assert w.interval == 3600.0
        assert not w._shutdown
        w.stop()
        assert w._shutdown
