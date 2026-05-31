"""
tests/test_cost_rollup_currency.py
===================================

Validation tests for kerf_plm.cost_rollup_currency.

Per ISO 4217:2015 (currency codes), ISO 10303-44:2021 (STEP AP44 product
structure / cost semantics), and the APICS dictionary "rolled-up cost".

Test matrix
-----------
CRC-01  Three-currency oracle: USD 10 + EUR 15 + ZAR 200 → 37.3 USD.
CRC-02  Missing FX rate flagged in unresolved_currencies, excluded from total.
CRC-03  Single-currency input: rollup == sum(unit_cost * qty) unchanged.
CRC-04  Per-currency breakdown sums to total_cost.
CRC-05  Empty entries list → total_cost == 0.0, empty breakdown.
CRC-06  Target EUR: same oracle converted to EUR base.
CRC-07  Partial missing FX: only the missing currencies excluded; resolved ones summed.
CRC-08  Negative unit_cost raises ValueError at MultiCurrencyBomEntry construction.
CRC-09  Zero qty raises ValueError at MultiCurrencyBomEntry construction.
CRC-10  FxRateSnapshot missing target_currency raises ValueError at construction.
CRC-11  Same source currency as target: no FX conversion applied (identity).
CRC-12  Multiple entries same currency: breakdown single key, correct total.
CRC-13  Fractional qty applied correctly.
CRC-14  Re-export from kerf_plm top-level works.
CRC-15  honest_caveat is a non-empty string mentioning FX.
CRC-16  fx_snapshot_date propagated to result.
CRC-17  All-missing FX: total_cost == 0.0, all currencies in unresolved.
CRC-18  ZAR target currency: USD cost converted correctly.
"""

from __future__ import annotations

import pytest

from kerf_plm.cost_rollup_currency import (
    CurrencyRolledUpCost,
    FxRateSnapshot,
    MultiCurrencyBomEntry,
    rollup_cost_multi_currency,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

STANDARD_FX = FxRateSnapshot(
    target_currency="USD",
    snapshot_date="2025-06-01",
    rates={"USD": 1.0, "EUR": 1.10, "ZAR": 0.054, "GBP": 1.27, "JPY": 0.0068, "CNY": 0.14},
)


def entry(pn: str, name: str, cost: float, currency: str, qty: float = 1.0) -> MultiCurrencyBomEntry:
    return MultiCurrencyBomEntry(
        part_number=pn,
        name=name,
        unit_cost=cost,
        currency=currency,
        qty=qty,
    )


# ---------------------------------------------------------------------------
# CRC-01  Three-currency oracle
# ---------------------------------------------------------------------------

def test_three_currency_oracle_usd():
    """CRC-01: USD 10×1 + EUR 15×1 + ZAR 200×1 → 37.3 USD.

    10.00 (USD) + 15 * 1.10 (EUR→USD) + 200 * 0.054 (ZAR→USD)
    = 10.00 + 16.50 + 10.80
    = 37.30 USD
    """
    entries = [
        entry("PN-USD", "US Widget", 10.0, "USD"),
        entry("PN-EUR", "EU Bearing", 15.0, "EUR"),
        entry("PN-ZAR", "SA Fastener", 200.0, "ZAR"),
    ]
    result = rollup_cost_multi_currency(entries, STANDARD_FX)
    assert result.total_cost == pytest.approx(37.30, rel=1e-6)
    assert result.target_currency == "USD"
    assert result.unresolved_currencies == []


# ---------------------------------------------------------------------------
# CRC-02  Missing FX rate flagged, excluded from total
# ---------------------------------------------------------------------------

def test_missing_fx_rate_flagged():
    """CRC-02: BRL not in snapshot → flagged in unresolved_currencies, excluded from total."""
    entries = [
        entry("PN-USD1", "US Part", 10.0, "USD"),
        entry("PN-BRL1", "BR Part", 50.0, "BRL"),
    ]
    result = rollup_cost_multi_currency(entries, STANDARD_FX)
    assert "BRL" in result.unresolved_currencies
    # total is USD 10 only (BRL excluded)
    assert result.total_cost == pytest.approx(10.0, rel=1e-6)


# ---------------------------------------------------------------------------
# CRC-03  Single-currency input: no FX conversion
# ---------------------------------------------------------------------------

def test_single_currency_no_conversion():
    """CRC-03: All USD entries → total = sum(unit_cost * qty), no FX factor applied."""
    entries = [
        entry("PN-A", "Part A", 5.0, "USD", qty=2.0),
        entry("PN-B", "Part B", 3.0, "USD", qty=4.0),
        entry("PN-C", "Part C", 1.5, "USD", qty=1.0),
    ]
    # 5*2 + 3*4 + 1.5*1 = 10 + 12 + 1.5 = 23.5
    result = rollup_cost_multi_currency(entries, STANDARD_FX)
    assert result.total_cost == pytest.approx(23.5, rel=1e-6)
    assert result.unresolved_currencies == []


# ---------------------------------------------------------------------------
# CRC-04  Per-currency breakdown sums to total_cost
# ---------------------------------------------------------------------------

def test_by_currency_breakdown_sums_to_total():
    """CRC-04: Sum of by_currency_breakdown values == total_cost."""
    entries = [
        entry("PN-1", "A", 10.0, "USD"),
        entry("PN-2", "B", 15.0, "EUR"),
        entry("PN-3", "C", 200.0, "ZAR"),
    ]
    result = rollup_cost_multi_currency(entries, STANDARD_FX)
    breakdown_total = sum(result.by_currency_breakdown.values())
    assert breakdown_total == pytest.approx(result.total_cost, rel=1e-6)


# ---------------------------------------------------------------------------
# CRC-05  Empty entries list
# ---------------------------------------------------------------------------

def test_empty_entries_zero_total():
    """CRC-05: No entries → total_cost == 0.0, empty breakdown, no unresolved."""
    result = rollup_cost_multi_currency([], STANDARD_FX)
    assert result.total_cost == 0.0
    assert result.by_currency_breakdown == {}
    assert result.unresolved_currencies == []


# ---------------------------------------------------------------------------
# CRC-06  EUR target: USD-priced part converted to EUR
# ---------------------------------------------------------------------------

def test_target_eur_converts_usd_correctly():
    """CRC-06: USD 10 → EUR: 10 * 1.0 / 1.10 ≈ 9.0909 EUR."""
    fx_eur = FxRateSnapshot(
        target_currency="EUR",
        snapshot_date="2025-06-01",
        rates={"USD": 1.0, "EUR": 1.10, "ZAR": 0.054},
    )
    entries = [entry("PN-USD-EUR", "US Part", 10.0, "USD")]
    result = rollup_cost_multi_currency(entries, fx_eur)
    expected = 10.0 * 1.0 / 1.10  # USD→EUR
    assert result.total_cost == pytest.approx(expected, rel=1e-5)
    assert result.target_currency == "EUR"


# ---------------------------------------------------------------------------
# CRC-07  Partial missing FX: only missing excluded, resolved ones summed
# ---------------------------------------------------------------------------

def test_partial_missing_fx_partial_total():
    """CRC-07: EUR resolved + TWD missing → total == EUR part only; TWD in unresolved."""
    entries = [
        entry("PN-EU2", "EU Part", 20.0, "EUR"),     # 20 * 1.10 = 22 USD
        entry("PN-TWD", "TW Part", 1000.0, "TWD"),   # TWD not in snapshot
    ]
    result = rollup_cost_multi_currency(entries, STANDARD_FX)
    assert result.total_cost == pytest.approx(22.0, rel=1e-6)
    assert "TWD" in result.unresolved_currencies
    assert "EUR" not in result.unresolved_currencies


# ---------------------------------------------------------------------------
# CRC-08  Negative unit_cost raises ValueError
# ---------------------------------------------------------------------------

def test_negative_unit_cost_raises():
    """CRC-08: unit_cost < 0 raises ValueError at MultiCurrencyBomEntry construction."""
    with pytest.raises(ValueError, match="unit_cost must be >= 0"):
        MultiCurrencyBomEntry(
            part_number="PN-NEG",
            name="Bad Part",
            unit_cost=-5.0,
            currency="USD",
            qty=1.0,
        )


# ---------------------------------------------------------------------------
# CRC-09  Zero qty raises ValueError
# ---------------------------------------------------------------------------

def test_zero_qty_raises():
    """CRC-09: qty=0 raises ValueError at MultiCurrencyBomEntry construction."""
    with pytest.raises(ValueError, match="qty must be > 0"):
        MultiCurrencyBomEntry(
            part_number="PN-ZERO",
            name="Zero Qty",
            unit_cost=5.0,
            currency="USD",
            qty=0.0,
        )


# ---------------------------------------------------------------------------
# CRC-10  FxRateSnapshot missing target_currency raises ValueError
# ---------------------------------------------------------------------------

def test_fx_snapshot_missing_target_raises():
    """CRC-10: target_currency absent from rates raises ValueError."""
    with pytest.raises(ValueError, match="target_currency 'GBP' must be present in rates"):
        FxRateSnapshot(
            target_currency="GBP",
            snapshot_date="2025-06-01",
            rates={"USD": 1.0, "EUR": 1.10},
        )


# ---------------------------------------------------------------------------
# CRC-11  Same source as target: identity conversion
# ---------------------------------------------------------------------------

def test_same_source_as_target_identity():
    """CRC-11: When source == target, no FX factor applied; cost passes through."""
    entries = [entry("PN-SAME", "Same Currency Part", 42.5, "USD")]
    result = rollup_cost_multi_currency(entries, STANDARD_FX)
    assert result.total_cost == pytest.approx(42.5, rel=1e-9)


# ---------------------------------------------------------------------------
# CRC-12  Multiple entries same currency: single breakdown key
# ---------------------------------------------------------------------------

def test_multiple_same_currency_entries_single_breakdown_key():
    """CRC-12: Three EUR parts → single 'EUR' key in by_currency_breakdown."""
    entries = [
        entry("PN-E1", "EU1", 10.0, "EUR", qty=1.0),
        entry("PN-E2", "EU2", 5.0, "EUR", qty=2.0),
        entry("PN-E3", "EU3", 3.0, "EUR", qty=3.0),
    ]
    # extended EUR: 10 + 10 + 9 = 29 EUR → 29 * 1.10 = 31.90 USD
    result = rollup_cost_multi_currency(entries, STANDARD_FX)
    assert set(result.by_currency_breakdown.keys()) == {"EUR"}
    assert result.total_cost == pytest.approx(29.0 * 1.10, rel=1e-6)


# ---------------------------------------------------------------------------
# CRC-13  Fractional qty applied correctly
# ---------------------------------------------------------------------------

def test_fractional_qty():
    """CRC-13: qty=2.5 correctly scales unit_cost before FX conversion."""
    entries = [entry("PN-FRAC", "Fractional Part", 4.0, "EUR", qty=2.5)]
    # 4.0 * 2.5 = 10.0 EUR → 10.0 * 1.10 = 11.0 USD
    result = rollup_cost_multi_currency(entries, STANDARD_FX)
    assert result.total_cost == pytest.approx(11.0, rel=1e-6)


# ---------------------------------------------------------------------------
# CRC-14  Re-export from kerf_plm top-level
# ---------------------------------------------------------------------------

def test_reexport_from_kerf_plm():
    """CRC-14: New symbols importable from kerf_plm top-level."""
    from kerf_plm import (
        CurrencyRolledUpCost as _CRC,
        FxRateSnapshot as _FX,
        MultiCurrencyBomEntry as _MCBE,
        rollup_cost_multi_currency as _rollup,
    )
    assert _MCBE is MultiCurrencyBomEntry
    assert _FX is FxRateSnapshot
    assert _CRC is CurrencyRolledUpCost
    assert _rollup is rollup_cost_multi_currency


# ---------------------------------------------------------------------------
# CRC-15  honest_caveat mentions FX
# ---------------------------------------------------------------------------

def test_honest_caveat_present_and_mentions_fx():
    """CRC-15: honest_caveat is a non-empty string that mentions FX."""
    result = rollup_cost_multi_currency([], STANDARD_FX)
    assert isinstance(result.honest_caveat, str)
    assert len(result.honest_caveat) > 30
    assert "FX" in result.honest_caveat or "fx" in result.honest_caveat.lower()


# ---------------------------------------------------------------------------
# CRC-16  fx_snapshot_date propagated to result
# ---------------------------------------------------------------------------

def test_snapshot_date_propagated():
    """CRC-16: fx_snapshot_date in result matches the FxRateSnapshot."""
    fx = FxRateSnapshot(
        target_currency="USD",
        snapshot_date="2025-12-31",
        rates={"USD": 1.0},
    )
    result = rollup_cost_multi_currency([], fx)
    assert result.fx_snapshot_date == "2025-12-31"


# ---------------------------------------------------------------------------
# CRC-17  All-missing FX: total_cost == 0.0
# ---------------------------------------------------------------------------

def test_all_missing_fx_zero_total():
    """CRC-17: All entry currencies absent from snapshot → total_cost == 0.0."""
    fx = FxRateSnapshot(
        target_currency="USD",
        snapshot_date="2025-06-01",
        rates={"USD": 1.0},
    )
    entries = [
        entry("PN-BRL2", "BRL Part", 100.0, "BRL"),
        entry("PN-INR1", "INR Part", 5000.0, "INR"),
    ]
    result = rollup_cost_multi_currency(entries, fx)
    assert result.total_cost == 0.0
    assert set(result.unresolved_currencies) == {"BRL", "INR"}


# ---------------------------------------------------------------------------
# CRC-18  ZAR target: USD converted to ZAR correctly
# ---------------------------------------------------------------------------

def test_zar_target_currency():
    """CRC-18: USD 10 → ZAR: 10 * 1.0 / 0.054 ≈ 185.185 ZAR."""
    fx_zar = FxRateSnapshot(
        target_currency="ZAR",
        snapshot_date="2025-06-01",
        rates={"USD": 1.0, "EUR": 1.10, "ZAR": 0.054},
    )
    entries = [entry("PN-USD-ZAR", "US Part", 10.0, "USD")]
    result = rollup_cost_multi_currency(entries, fx_zar)
    expected = 10.0 * 1.0 / 0.054  # USD→ZAR
    assert result.total_cost == pytest.approx(expected, rel=1e-5)
    assert result.target_currency == "ZAR"


# ---------------------------------------------------------------------------
# CRC-19  Per-currency breakdown keys match source currencies present in BOM
# ---------------------------------------------------------------------------

def test_by_currency_breakdown_keys_correct():
    """CRC-19: by_currency_breakdown keys == set of resolved source currencies."""
    entries = [
        entry("PN-USD2", "US", 10.0, "USD"),
        entry("PN-GBP1", "GB", 5.0, "GBP"),
        entry("PN-MISS", "Missing", 99.0, "SGD"),  # SGD not in STANDARD_FX
    ]
    result = rollup_cost_multi_currency(entries, STANDARD_FX)
    assert set(result.by_currency_breakdown.keys()) == {"USD", "GBP"}
    assert "SGD" in result.unresolved_currencies


# ---------------------------------------------------------------------------
# CRC-20  qty=1 default: extended == unit_cost
# ---------------------------------------------------------------------------

def test_qty_one_extended_equals_unit_cost():
    """CRC-20: qty=1 → extended cost is identical to unit_cost."""
    e = MultiCurrencyBomEntry(
        part_number="PN-Q1", name="Part", unit_cost=7.77, currency="USD", qty=1.0
    )
    result = rollup_cost_multi_currency([e], STANDARD_FX)
    assert result.total_cost == pytest.approx(7.77, rel=1e-9)
