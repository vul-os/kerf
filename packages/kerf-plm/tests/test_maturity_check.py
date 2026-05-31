"""
tests/test_maturity_check.py
============================

Validation tests for kerf_plm.maturity_check.

Per NASA SP-2016-6105 Rev 2 (TRL 1–9) and ISO/IEC 15288:2023 §6.3.

Test matrix
-----------
MC-01  All TRL-9 children (equal qty) → low risk.
MC-02  All TRL-7 children → low risk (boundary).
MC-03  Weighted average in [5,7) → medium risk.
MC-04  Weighted average in [3,5) with no TRL ≤ 2 → high risk.
MC-05  Any TRL-2 component → critical risk (regardless of average).
MC-06  Any TRL-1 component → critical risk.
MC-07  weighted_avg < 3 (all TRL-1 or 2) → critical risk.
MC-08  blocker_count = count of components with TRL < 5.
MC-09  Empty children list → low risk default, weighted_avg_trl == 0.0.
MC-10  Quantity weighting: high-qty TRL-9 pulls avg up vs low-qty TRL-3.
MC-11  Missing qty_per_child key defaults to 1.0.
MC-12  Invalid TRL (0) raises ValueError.
MC-13  Invalid TRL (10) raises ValueError.
MC-14  qty ≤ 0 raises ValueError.
MC-15  Empty parent_pn raises ValueError.
MC-16  Re-export: ComponentMaturity, MaturityReport, assess_bom_maturity
       importable from kerf_plm.
MC-17  honest_caveat is a non-empty string in every report.
MC-18  recommendation is a non-empty string in every report.
"""

from __future__ import annotations

import pytest

from kerf_plm.maturity_check import (
    ComponentMaturity,
    MaturityReport,
    assess_bom_maturity,
    HONEST_CAVEAT,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_comp(
    part_number: str,
    trl_level: int,
    manufacturer_qualified: bool = True,
    has_drawings: bool = True,
    has_supplier: bool = True,
    has_test_data: bool = True,
) -> ComponentMaturity:
    """Convenience factory for ComponentMaturity with sensible defaults."""
    return ComponentMaturity(
        part_number=part_number,
        trl_level=trl_level,
        manufacturer_qualified=manufacturer_qualified,
        has_drawings=has_drawings,
        has_supplier=has_supplier,
        has_test_data=has_test_data,
    )


# ---------------------------------------------------------------------------
# MC-01 — all TRL-9 → low risk
# ---------------------------------------------------------------------------

def test_mc01_all_trl9_low_risk():
    children = [
        make_comp("PN-001", 9),
        make_comp("PN-002", 9),
        make_comp("PN-003", 9),
    ]
    report = assess_bom_maturity("ASSY-001", children, {})
    assert report.risk_level == "low"
    assert report.weighted_avg_trl == pytest.approx(9.0)
    assert report.blocker_count == 0


# ---------------------------------------------------------------------------
# MC-02 — all TRL-7 → low risk (boundary)
# ---------------------------------------------------------------------------

def test_mc02_all_trl7_low_risk_boundary():
    children = [make_comp(f"PN-{i:03d}", 7) for i in range(5)]
    report = assess_bom_maturity("ASSY-002", children, {})
    assert report.risk_level == "low"
    assert report.weighted_avg_trl == pytest.approx(7.0)


# ---------------------------------------------------------------------------
# MC-03 — weighted avg in [5,7) → medium risk
# ---------------------------------------------------------------------------

def test_mc03_medium_risk():
    # TRL 6 children
    children = [make_comp(f"PN-{i:03d}", 6) for i in range(4)]
    report = assess_bom_maturity("ASSY-003", children, {})
    assert report.risk_level == "medium"
    assert 5.0 <= report.weighted_avg_trl < 7.0


# ---------------------------------------------------------------------------
# MC-04 — mixed TRL with one TRL-3, none ≤ 2 → high risk
# ---------------------------------------------------------------------------

def test_mc04_high_risk_mixed_trl():
    # Majority TRL-5, one TRL-3 — avg lands between 3 and 5
    children = [
        make_comp("PN-001", 3),
        make_comp("PN-002", 5),
        make_comp("PN-003", 5),
    ]
    qty = {"PN-001": 1.0, "PN-002": 1.0, "PN-003": 1.0}
    report = assess_bom_maturity("ASSY-004", children, qty)
    expected_avg = (3 + 5 + 5) / 3
    assert report.weighted_avg_trl == pytest.approx(expected_avg, abs=1e-3)
    assert report.risk_level == "high"
    # blocker_count: TRL < 5 → PN-001 (TRL-3)
    assert report.blocker_count == 1


# ---------------------------------------------------------------------------
# MC-05 — any TRL-2 component → critical (even if average is ok)
# ---------------------------------------------------------------------------

def test_mc05_critical_on_trl2():
    children = [
        make_comp("PN-001", 9),
        make_comp("PN-002", 9),
        make_comp("PN-003", 2),
    ]
    qty = {"PN-001": 100.0, "PN-002": 100.0, "PN-003": 1.0}
    report = assess_bom_maturity("ASSY-005", children, qty)
    # Average is very high (dominated by TRL-9 at qty 100)
    # but a TRL-2 component must force critical
    assert report.risk_level == "critical"
    assert report.blocker_count >= 1


# ---------------------------------------------------------------------------
# MC-06 — any TRL-1 component → critical
# ---------------------------------------------------------------------------

def test_mc06_critical_on_trl1():
    children = [
        make_comp("PN-A", 9),
        make_comp("PN-B", 1),
    ]
    report = assess_bom_maturity("ASSY-006", children, {})
    assert report.risk_level == "critical"


# ---------------------------------------------------------------------------
# MC-07 — all low TRL → critical via average < 3
# ---------------------------------------------------------------------------

def test_mc07_critical_by_low_average():
    children = [
        make_comp("PN-X", 2),
        make_comp("PN-Y", 2),
        make_comp("PN-Z", 2),
    ]
    report = assess_bom_maturity("ASSY-007", children, {})
    assert report.risk_level == "critical"
    assert report.weighted_avg_trl == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# MC-08 — blocker_count = count(TRL < 5)
# ---------------------------------------------------------------------------

def test_mc08_blocker_count_correct():
    children = [
        make_comp("PN-1", 1),  # blocker
        make_comp("PN-2", 2),  # blocker
        make_comp("PN-3", 3),  # blocker
        make_comp("PN-4", 4),  # blocker
        make_comp("PN-5", 5),  # NOT a blocker (TRL == 5 is not < 5)
        make_comp("PN-6", 6),
        make_comp("PN-7", 9),
    ]
    report = assess_bom_maturity("ASSY-008", children, {})
    assert report.blocker_count == 4


# ---------------------------------------------------------------------------
# MC-09 — empty children → low risk default, weighted_avg_trl == 0.0
# ---------------------------------------------------------------------------

def test_mc09_empty_children_low_risk():
    report = assess_bom_maturity("ASSY-009", [], {})
    assert report.risk_level == "low"
    assert report.weighted_avg_trl == 0.0
    assert report.blocker_count == 0
    assert report.parent_pn == "ASSY-009"


# ---------------------------------------------------------------------------
# MC-10 — quantity weighting pulls average toward high-qty component
# ---------------------------------------------------------------------------

def test_mc10_qty_weighting():
    children = [
        make_comp("FASTENER", 9),
        make_comp("PROTOTYPE", 3),
    ]
    qty = {"FASTENER": 200.0, "PROTOTYPE": 1.0}
    report = assess_bom_maturity("ASSY-010", children, qty)
    expected_avg = (9 * 200 + 3 * 1) / 201
    assert report.weighted_avg_trl == pytest.approx(expected_avg, abs=1e-3)
    # Expected avg ~8.96 → low risk
    assert report.risk_level == "low"


# ---------------------------------------------------------------------------
# MC-11 — missing qty_per_child key defaults to 1.0
# ---------------------------------------------------------------------------

def test_mc11_missing_qty_defaults_to_one():
    children = [
        make_comp("A", 7),
        make_comp("B", 7),
    ]
    # Only supply qty for A; B should default to 1.0
    report = assess_bom_maturity("ASSY-011", children, {"A": 2.0})
    expected_avg = (7 * 2 + 7 * 1) / 3
    assert report.weighted_avg_trl == pytest.approx(expected_avg, abs=1e-3)


# ---------------------------------------------------------------------------
# MC-12 — invalid TRL (0) raises ValueError
# ---------------------------------------------------------------------------

def test_mc12_trl_too_low_raises():
    with pytest.raises(ValueError, match="trl_level must be in 1"):
        make_comp("PN-BAD", 0)


# ---------------------------------------------------------------------------
# MC-13 — invalid TRL (10) raises ValueError
# ---------------------------------------------------------------------------

def test_mc13_trl_too_high_raises():
    with pytest.raises(ValueError, match="trl_level must be in 1"):
        make_comp("PN-BAD", 10)


# ---------------------------------------------------------------------------
# MC-14 — qty <= 0 raises ValueError
# ---------------------------------------------------------------------------

def test_mc14_qty_zero_raises():
    children = [make_comp("PN-001", 7)]
    with pytest.raises(ValueError, match="qty for part"):
        assess_bom_maturity("ASSY-014", children, {"PN-001": 0.0})


def test_mc14b_qty_negative_raises():
    children = [make_comp("PN-001", 7)]
    with pytest.raises(ValueError, match="qty for part"):
        assess_bom_maturity("ASSY-014b", children, {"PN-001": -1.0})


# ---------------------------------------------------------------------------
# MC-15 — empty parent_pn raises ValueError
# ---------------------------------------------------------------------------

def test_mc15_empty_parent_pn_raises():
    with pytest.raises(ValueError, match="parent_pn must be a non-empty string"):
        assess_bom_maturity("", [], {})


def test_mc15b_whitespace_parent_pn_raises():
    with pytest.raises(ValueError, match="parent_pn must be a non-empty string"):
        assess_bom_maturity("   ", [], {})


# ---------------------------------------------------------------------------
# MC-16 — re-export from kerf_plm
# ---------------------------------------------------------------------------

def test_mc16_re_export_from_kerf_plm():
    from kerf_plm import ComponentMaturity as CM
    from kerf_plm import MaturityReport as MR
    from kerf_plm import assess_bom_maturity as abm

    assert CM is ComponentMaturity
    assert MR is MaturityReport
    assert abm is assess_bom_maturity


# ---------------------------------------------------------------------------
# MC-17 — honest_caveat is present and non-empty in every report
# ---------------------------------------------------------------------------

def test_mc17_honest_caveat_always_present():
    scenarios = [
        # empty
        ("ASSY-A", [], {}),
        # all TRL-9
        ("ASSY-B", [make_comp("X", 9)], {}),
        # critical
        ("ASSY-C", [make_comp("Y", 1)], {}),
    ]
    for pn, children, qty in scenarios:
        report = assess_bom_maturity(pn, children, qty)
        assert isinstance(report.honest_caveat, str)
        assert len(report.honest_caveat) > 10, (
            f"honest_caveat too short for {pn}: {report.honest_caveat!r}"
        )


# ---------------------------------------------------------------------------
# MC-18 — recommendation is always non-empty
# ---------------------------------------------------------------------------

def test_mc18_recommendation_always_present():
    scenarios = [
        ("R-LOW", [make_comp("P", 9)], {}, "low"),
        ("R-MED", [make_comp("P", 6)], {}, "medium"),
        ("R-HIGH", [make_comp("P", 4)], {}, "high"),
        ("R-CRIT", [make_comp("P", 2)], {}, "critical"),
    ]
    for pn, children, qty, expected_risk in scenarios:
        report = assess_bom_maturity(pn, children, qty)
        assert report.risk_level == expected_risk
        assert isinstance(report.recommendation, str)
        assert len(report.recommendation) > 10, (
            f"recommendation too short for risk={expected_risk}: "
            f"{report.recommendation!r}"
        )


# ---------------------------------------------------------------------------
# Additional edge-case: TRL boundary at exactly 5 is NOT a blocker
# ---------------------------------------------------------------------------

def test_trl5_not_a_blocker():
    children = [make_comp("PN-TRL5", 5)]
    report = assess_bom_maturity("ASSY-BOUNDARY", children, {})
    assert report.blocker_count == 0


# ---------------------------------------------------------------------------
# Additional: weighted avg exactly at 7.0 → low
# ---------------------------------------------------------------------------

def test_avg_exactly_7_is_low():
    children = [
        make_comp("A", 7),
        make_comp("B", 7),
    ]
    report = assess_bom_maturity("ASSY-E7", children, {})
    assert report.risk_level == "low"


# ---------------------------------------------------------------------------
# Additional: weighted avg exactly at 5.0 → medium (not high)
# ---------------------------------------------------------------------------

def test_avg_exactly_5_is_medium():
    children = [make_comp("A", 5)]
    report = assess_bom_maturity("ASSY-E5", children, {})
    assert report.risk_level == "medium"
    assert report.blocker_count == 0


# ---------------------------------------------------------------------------
# Additional: weighted avg exactly at 3.0 → high (not critical, no TRL<=2)
# ---------------------------------------------------------------------------

def test_avg_exactly_3_is_high():
    children = [make_comp("A", 3)]
    report = assess_bom_maturity("ASSY-E3", children, {})
    assert report.risk_level == "high"
    assert report.blocker_count == 1
