"""Cloud-tier pricing helpers.

The per-token rate card used to live in a hardcoded ``RATES`` dict here.
That dict is gone — chat token COGS is now resolved from the
``model_prices`` table by the kerf-pricing plugin (daily-refreshed from
LiteLLM).  The remaining helpers in this module are about Money + storage +
tier limits.

Markup: a single ``KERF_MARKUP_PCT`` knob (20%, per docs/pricing) is applied
on top of provider COGS for the paid-bucket spend path; free-bucket spend
records actual COGS (no markup); BYO bucket records zero.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from kerf_pricing.queries import (
    ModelPrice,
    UnknownModelError,
    require_price,
)


# ---------------------------------------------------------------------------
# Money + constants
# ---------------------------------------------------------------------------
@dataclass
class Money:
    amount: float
    currency: str


# The Kerf paid-bucket markup, in percent.  Free-bucket spend is recorded
# at COGS (markup_pct=0).  BYO bucket is recorded at $0.  This value lives
# here (one knob) instead of being threaded through every caller so the
# whole pricing surface is auditable from one place.
KERF_MARKUP_PCT = 20.0


TIER_LIMITS = {
    "free": {
        "max_projects": 3,
        "storage_bytes": 50 * 1024 * 1024,
        "api_calls_per_month": 1000,
    },
    "starter": {
        "max_projects": 10,
        "storage_bytes": 1024 * 1024 * 1024,
        "api_calls_per_month": 10000,
    },
    "pro": {
        "max_projects": 50,
        "storage_bytes": 10 * 1024 * 1024 * 1024,
        "api_calls_per_month": 100000,
    },
    "enterprise": {
        "max_projects": -1,
        "storage_bytes": -1,
        "api_calls_per_month": -1,
    },
}


# ---------------------------------------------------------------------------
# Live token-cost resolution
# ---------------------------------------------------------------------------
def apply_markup(raw_cogs: float, markup_pct: float = KERF_MARKUP_PCT) -> float:
    """Apply the Kerf markup to a provider COGS figure.

    >>> apply_markup(1.0, 20.0)
    1.2
    """
    return raw_cogs * (1.0 + markup_pct / 100.0)


async def token_cost(
    pool,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    markup_pct: float = KERF_MARKUP_PCT,
    cached_input_tokens: int = 0,
) -> float:
    """Provider COGS × (1 + markup_pct/100), looked up live from model_prices.

    Raises ``UnknownModelError`` when (provider, model) isn't in the table;
    the caller MUST translate that into a 4xx — the previous "fall back to a
    median rate" behaviour silently mispriced unknown models.
    """
    price: ModelPrice = await require_price(pool, provider, model)
    cogs = price.compute_cost_usd(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
    )
    return apply_markup(cogs, markup_pct)


async def token_cogs(
    pool,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
) -> float:
    """Provider COGS only (no markup).  Used by the kerf_free bucket so the
    free-tier usage_events row records what the model actually cost Kerf,
    not what it would have cost the user."""
    price: ModelPrice = await require_price(pool, provider, model)
    return price.compute_cost_usd(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_input_tokens=cached_input_tokens,
    )


# Re-export so callers can `from kerf_cloud.pricing import UnknownModelError`
__all__ = [
    "Money",
    "KERF_MARKUP_PCT",
    "TIER_LIMITS",
    "UnknownModelError",
    "apply_markup",
    "token_cost",
    "token_cogs",
    "storage_cost_per_gb_month",
    "storage_daily_cost",
    "compute_price",
    "get_tier_limits",
]


# ---------------------------------------------------------------------------
# Storage helpers (unchanged from the old module)
# ---------------------------------------------------------------------------
def storage_cost_per_gb_month(usd_per_gb_month: float) -> float:
    return usd_per_gb_month


def storage_daily_cost(bytes_count: int, usd_per_gb_month: float) -> float:
    gb = bytes_count / (1024.0 * 1024.0 * 1024.0)
    return gb * (usd_per_gb_month / 30.0)


async def compute_price(pool, workspace_tier: str, usage: dict) -> Money:
    """Aggregate token + storage + api-call charges for a billing period.

    NB: now async (was sync) because token pricing is a DB lookup.  Callers:
    the cron-driven monthly invoice job (not the per-request chat handler —
    that path lives in the chat-handler bucket logic).
    """
    markup_pct = KERF_MARKUP_PCT
    storage_rate = 0.20

    total = 0.0

    if "input_tokens" in usage or "output_tokens" in usage:
        provider = usage.get("provider", "")
        model = usage.get("model", "")
        input_tok = usage.get("input_tokens", 0)
        output_tok = usage.get("output_tokens", 0)
        try:
            total += await token_cost(
                pool, provider, model, input_tok, output_tok, markup_pct,
            )
        except UnknownModelError:
            # Compute-price is offline / batch — silently skip rows whose
            # model is no longer in the table (e.g. retired).  Per-request
            # path is strict; this one isn't.
            pass

    if "storage_bytes" in usage:
        total += storage_daily_cost(usage["storage_bytes"], storage_rate)

    if "api_calls" in usage:
        total += usage["api_calls"] * 0.001

    return Money(amount=total, currency="USD")


def get_tier_limits(tier: str) -> dict:
    return TIER_LIMITS.get(tier, TIER_LIMITS["free"])
