"""
kerf_plm.cost_rollup_currency
==============================

Multi-currency BOM cost rollup — flat-list variant with strict ISO 4217 FX
handling.  Complements ``bom_cost_rollup`` (multi-level tree) with a
simpler flat-BOM input model targeted at import/export cost sheets where
components arrive from different procurement regions, each priced in their
local currency.

Key design choices
------------------
- FX rates are caller-supplied via ``FxRateSnapshot`` (no live market feed).
- Rates are expressed as *units of source currency per 1 USD*, i.e.
  ``rate_to_usd: src_amount × rate == usd_amount``.  This matches the
  convention in ``bom_cost_rollup._DEFAULT_FX_RATES``.
- Missing-currency entries are *not* raised as errors; they are collected in
  ``CurrencyRolledUpCost.unresolved_currencies`` so callers can surface them
  gracefully.
- ``by_currency_breakdown`` shows the total *source-currency* contribution
  converted to the target currency, aggregated by ISO 4217 code.  Useful for
  cost-origin analysis (e.g. "47 % of cost is EUR-origin").

Honest caveats
--------------
- Snapshot-in-time FX only: no historical rate tracking, no intraday feed,
  no forward-curve discounting.  Rates may be stale the moment they are
  created.
- Static unit costs only: no scrap allowance, overhead absorption, yield
  costing, learning-curve amortisation, or activity-based costing.
- Quantities must be positive real numbers.
- Round-trip conversion (e.g. ZAR → USD → EUR) accumulates floating-point
  rounding; use ``round()`` on the final report for display.

References
----------
- ISO 4217:2015 — Currency codes.
- ISO 10303-44:2021 (STEP AP44 product structure) — BOM cost semantics.
- APICS Dictionary, 16th ed.: "rolled-up cost".
- Horngren, C.T. et al. *Cost Accounting: A Managerial Emphasis*, 16th ed. §7.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

HONEST_CAVEAT_CURRENCY = (
    "Snapshot-in-time FX only: no historical rate tracking, no live market feed, "
    "no forward-curve discounting — rates may be stale. "
    "Static unit costs only: no scrap allowance, overhead absorption, yield-based costing, "
    "learning-curve amortisation, or activity-based costing. "
    "ISO 4217 currency codes required. "
    "ISO 10303-44 product structure; APICS rolled-up cost definition."
)


@dataclass
class MultiCurrencyBomEntry:
    """A single flat-BOM line item with an explicit ISO 4217 currency.

    Parameters
    ----------
    part_number:  Unique part identifier (e.g. 'PN-001').
    name:         Human-readable part name.
    unit_cost:    Cost per unit in *currency*.  Must be >= 0.
    currency:     ISO 4217 currency code for *unit_cost* (e.g. 'USD', 'EUR').
    qty:          Quantity required.  Must be > 0.
    """

    part_number: str
    name: str
    unit_cost: float
    currency: str
    qty: float

    def __post_init__(self) -> None:
        if self.unit_cost < 0:
            raise ValueError(
                f"unit_cost must be >= 0 for part '{self.part_number}', "
                f"got {self.unit_cost}"
            )
        if self.qty <= 0:
            raise ValueError(
                f"qty must be > 0 for part '{self.part_number}', got {self.qty}"
            )
        if not self.currency or not isinstance(self.currency, str):
            raise ValueError(
                f"currency must be a non-empty ISO 4217 string for part "
                f"'{self.part_number}', got {self.currency!r}"
            )


@dataclass
class FxRateSnapshot:
    """A point-in-time snapshot of FX rates relative to USD.

    Rates are expressed as *units of source currency per 1 USD*:

        usd_amount = source_amount * rates[source_currency]

    So ``rates = {"USD": 1.0, "EUR": 1.10, "ZAR": 0.054}`` means
    1 EUR = 1.10 USD, 1 ZAR = 0.054 USD.

    Parameters
    ----------
    target_currency:  ISO 4217 code for the reporting currency.
    snapshot_date:    ISO 8601 date string (informational; not validated).
    rates:            Dict mapping ISO 4217 code → rate-to-USD.
                      The target_currency *must* be present in this dict.
    """

    target_currency: str
    snapshot_date: str
    rates: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.target_currency not in self.rates:
            raise ValueError(
                f"target_currency '{self.target_currency}' must be present in "
                f"rates dict.  Available: {sorted(self.rates)}"
            )

    def convert_to_target(self, amount: float, from_currency: str) -> float | None:
        """Convert *amount* from *from_currency* to target_currency.

        Returns ``None`` if *from_currency* is not in the rates dict.
        """
        if from_currency not in self.rates:
            return None
        if from_currency == self.target_currency:
            return amount
        # from_currency → USD → target_currency
        amount_usd = amount * self.rates[from_currency]
        return amount_usd / self.rates[self.target_currency]


@dataclass
class CurrencyRolledUpCost:
    """Result of a multi-currency flat BOM cost rollup.

    Attributes
    ----------
    total_cost:             Sum of all resolved line-item costs in
                            *target_currency*.  Lines with missing FX rates
                            are excluded from this total.
    target_currency:        ISO 4217 reporting currency code.
    fx_snapshot_date:       Snapshot date from the FxRateSnapshot (informational).
    by_currency_breakdown:  Per-source-currency total expressed in
                            *target_currency*.  Keys are ISO 4217 codes.
                            Useful for cost-origin analysis.
    unresolved_currencies:  Sorted list of ISO 4217 codes encountered in the
                            BOM that were absent from the FX snapshot.  Lines
                            using these currencies are excluded from total_cost.
    honest_caveat:          Plain-English scope-limitation statement.
    """

    total_cost: float
    target_currency: str
    fx_snapshot_date: str
    by_currency_breakdown: dict[str, float]
    unresolved_currencies: list[str]
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def rollup_cost_multi_currency(
    entries: list[MultiCurrencyBomEntry],
    fx: FxRateSnapshot,
) -> CurrencyRolledUpCost:
    """Roll up a flat BOM's line costs to a single target-currency total.

    Each entry's extended cost (``unit_cost × qty``) is converted to
    ``fx.target_currency`` using ``fx.rates``.  Entries whose currency is
    absent from the snapshot are tallied in ``unresolved_currencies`` and
    excluded from ``total_cost``.

    Parameters
    ----------
    entries:  Flat list of ``MultiCurrencyBomEntry`` items.
    fx:       ``FxRateSnapshot`` supplying the target currency and FX rates.

    Returns
    -------
    ``CurrencyRolledUpCost`` with total_cost, per-currency breakdown,
    unresolved currencies, and an honest caveat string.
    """
    total: float = 0.0
    # Accumulate converted cost per source-currency bucket
    by_currency: dict[str, float] = {}
    unresolved_set: set[str] = set()

    for entry in entries:
        extended = entry.unit_cost * entry.qty
        converted = fx.convert_to_target(extended, entry.currency)

        if converted is None:
            unresolved_set.add(entry.currency)
            continue

        total += converted
        by_currency[entry.currency] = by_currency.get(entry.currency, 0.0) + converted

    return CurrencyRolledUpCost(
        total_cost=round(total, 6),
        target_currency=fx.target_currency,
        fx_snapshot_date=fx.snapshot_date,
        by_currency_breakdown={k: round(v, 6) for k, v in by_currency.items()},
        unresolved_currencies=sorted(unresolved_set),
        honest_caveat=HONEST_CAVEAT_CURRENCY,
    )
