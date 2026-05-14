"""Live pricing surface — wired through model_prices via kerf-pricing."""
from __future__ import annotations

import pytest

from kerf_cloud.pricing import (
    KERF_MARKUP_PCT,
    Money,
    UnknownModelError,
    apply_markup,
    get_tier_limits,
    storage_cost_per_gb_month,
    storage_daily_cost,
    token_cogs,
    token_cost,
)
from kerf_pricing.queries import ModelPrice


# ---------------------------------------------------------------------------
# Helpers — minimal pool fake supporting fetchrow
# ---------------------------------------------------------------------------
class _FakeConn:
    def __init__(self, rows: dict[tuple[str, str], dict]) -> None:
        self.rows = rows

    async def fetchrow(self, sql: str, *args):
        provider, model = args
        return self.rows.get((provider, model))


class _FakePool:
    def __init__(self, rows: dict[tuple[str, str], dict]) -> None:
        self.rows = rows

    def acquire(self):
        rows = self.rows

        class _Acq:
            async def __aenter__(self_inner):
                return _FakeConn(rows)

            async def __aexit__(self_inner, exc_type, exc, tb):
                return False

        return _Acq()


def _row(in_p=3.0, out_p=15.0, cache=None, cheap=False):
    return {
        "provider": "anthropic",
        "model_id": "claude-sonnet-4-7",
        "input_per_mtok": in_p,
        "output_per_mtok": out_p,
        "cache_read_per_mtok": cache,
        "max_input_tokens": 200_000,
        "cheap_tier_eligible": cheap,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestApplyMarkup:
    def test_default_markup_is_20pct(self):
        assert KERF_MARKUP_PCT == 20.0
        assert apply_markup(1.0) == pytest.approx(1.20)

    def test_zero_markup_passthrough(self):
        assert apply_markup(1.0, 0.0) == pytest.approx(1.0)

    def test_negative_markup_arithmetic(self):
        # Discount semantics — used by free-tier accounting (we record COGS,
        # not a discounted price, so this shouldn't fire in production but
        # the math has to behave).
        assert apply_markup(1.0, -50.0) == pytest.approx(0.5)


class TestTokenCost:
    async def test_lookup_returns_marked_up(self):
        pool = _FakePool({("anthropic", "claude-sonnet-4-7"): _row()})
        cost = await token_cost(
            pool, "anthropic", "claude-sonnet-4-7", 1_000_000, 0,
        )
        # 1Mtok in @ $3 = $3 raw → $3.60 marked up 20%
        assert cost == pytest.approx(3.60)

    async def test_lookup_explicit_markup(self):
        pool = _FakePool({("anthropic", "claude-sonnet-4-7"): _row()})
        cost = await token_cost(
            pool, "anthropic", "claude-sonnet-4-7", 1_000_000, 0,
            markup_pct=0.0,
        )
        assert cost == pytest.approx(3.0)

    async def test_unknown_raises(self):
        pool = _FakePool({})
        with pytest.raises(UnknownModelError) as exc_info:
            await token_cost(pool, "acme", "gpt-99", 100, 100)
        assert exc_info.value.provider == "acme"
        assert exc_info.value.model_id == "gpt-99"

    async def test_cogs_passes_through_to_compute_cost(self):
        pool = _FakePool({("anthropic", "claude-sonnet-4-7"): _row(cache=0.30)})
        # All cached input — should pick up the cache rate
        cogs = await token_cogs(
            pool, "anthropic", "claude-sonnet-4-7",
            input_tokens=1_000_000, output_tokens=0,
            cached_input_tokens=1_000_000,
        )
        # No markup applied
        assert cogs == pytest.approx(0.30)


class TestStorageHelpers:
    def test_storage_cost_per_gb_month(self):
        assert storage_cost_per_gb_month(0.20) == 0.20

    def test_storage_daily_cost(self):
        # 1 GB at $0.20/mo → ~$0.00667/day
        assert storage_daily_cost(1024**3, 0.20) == pytest.approx(0.20 / 30.0)


class TestTierLimits:
    def test_free_tier_defaults(self):
        free = get_tier_limits("free")
        assert free["max_projects"] == 3
        assert free["storage_bytes"] == 50 * 1024 * 1024

    def test_unknown_tier_falls_back_to_free(self):
        assert get_tier_limits("ultra-platinum") == get_tier_limits("free")
