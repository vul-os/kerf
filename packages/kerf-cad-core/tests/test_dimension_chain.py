"""
Tests for kerf_cad_core.gdt.dimension_chain — ASME Y14.5-2018 §5.3 tolerance stack-up.

Reference oracle (3-link case):
  Link A: nominal=100 mm, tol=±0.5 mm, direction=positive  → s·d=+100, t_max=0.5
  Link B: nominal= 30 mm, tol=±0.2 mm, direction=negative  → s·d=−30,  t_max=0.2
  Link C: nominal= 20 mm, tol=±0.1 mm, direction=negative  → s·d=−20,  t_max=0.1

Nominal gap  = 100 − 30 − 20 = 50 mm
WC total     = 0.5 + 0.2 + 0.1 = 0.8 mm
  G_wc_min   = 50 − 0.8 = 49.2 mm
  G_wc_max   = 50 + 0.8 = 50.8 mm
RSS total    = sqrt(0.5² + 0.2² + 0.1²) = sqrt(0.25 + 0.04 + 0.01) = sqrt(0.30) ≈ 0.5477...
  G_rss_min  = 50 − 0.5477... ≈ 49.4523 mm
  G_rss_max  = 50 + 0.5477... ≈ 50.5477 mm
Dominant     = Link A (t_max = 0.5 is largest)
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.gdt.dimension_chain import (
    DimensionLink,
    DimensionChainReport,
    compute_dimension_chain,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_link(link_id: str, nominal: float, t_plus: float, t_minus: float,
              direction: str = "positive") -> DimensionLink:
    return DimensionLink(
        link_id=link_id,
        nominal_mm=nominal,
        tol_plus_mm=t_plus,
        tol_minus_mm=t_minus,
        direction=direction,
    )


# ---------------------------------------------------------------------------
# Test 1 — Nominal gap for the 3-link reference oracle
# ---------------------------------------------------------------------------

def test_nominal_gap_3link_oracle():
    """Nominal gap = 100 − 30 − 20 = 50 mm."""
    chain = [
        make_link("A", 100.0, 0.5, 0.5, "positive"),
        make_link("B",  30.0, 0.2, 0.2, "negative"),
        make_link("C",  20.0, 0.1, 0.1, "negative"),
    ]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    assert abs(report.nominal_gap_mm - 50.0) < 1e-9


# ---------------------------------------------------------------------------
# Test 2 — Worst-case min for 3-link oracle
# ---------------------------------------------------------------------------

def test_worst_case_min_3link_oracle():
    """WC_min = 50 − 0.8 = 49.2 mm."""
    chain = [
        make_link("A", 100.0, 0.5, 0.5, "positive"),
        make_link("B",  30.0, 0.2, 0.2, "negative"),
        make_link("C",  20.0, 0.1, 0.1, "negative"),
    ]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    assert abs(report.worst_case_min_mm - 49.2) < 1e-9


# ---------------------------------------------------------------------------
# Test 3 — Worst-case max for 3-link oracle
# ---------------------------------------------------------------------------

def test_worst_case_max_3link_oracle():
    """WC_max = 50 + 0.8 = 50.8 mm."""
    chain = [
        make_link("A", 100.0, 0.5, 0.5, "positive"),
        make_link("B",  30.0, 0.2, 0.2, "negative"),
        make_link("C",  20.0, 0.1, 0.1, "negative"),
    ]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    assert abs(report.worst_case_max_mm - 50.8) < 1e-9


# ---------------------------------------------------------------------------
# Test 4 — RSS min for 3-link oracle
# ---------------------------------------------------------------------------

def test_rss_min_3link_oracle():
    """RSS_min = 50 − sqrt(0.30) ≈ 49.452."""
    chain = [
        make_link("A", 100.0, 0.5, 0.5, "positive"),
        make_link("B",  30.0, 0.2, 0.2, "negative"),
        make_link("C",  20.0, 0.1, 0.1, "negative"),
    ]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    expected = 50.0 - math.sqrt(0.30)
    assert abs(report.rss_min_mm - expected) < 1e-9


# ---------------------------------------------------------------------------
# Test 5 — RSS max for 3-link oracle
# ---------------------------------------------------------------------------

def test_rss_max_3link_oracle():
    """RSS_max = 50 + sqrt(0.30) ≈ 50.548."""
    chain = [
        make_link("A", 100.0, 0.5, 0.5, "positive"),
        make_link("B",  30.0, 0.2, 0.2, "negative"),
        make_link("C",  20.0, 0.1, 0.1, "negative"),
    ]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    expected = 50.0 + math.sqrt(0.30)
    assert abs(report.rss_max_mm - expected) < 1e-9


# ---------------------------------------------------------------------------
# Test 6 — Dominant link for 3-link oracle
# ---------------------------------------------------------------------------

def test_dominant_link_3link_oracle():
    """Link A has largest t_max=0.5; others are 0.2 and 0.1."""
    chain = [
        make_link("A", 100.0, 0.5, 0.5, "positive"),
        make_link("B",  30.0, 0.2, 0.2, "negative"),
        make_link("C",  20.0, 0.1, 0.1, "negative"),
    ]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    assert report.dominant_link == "A"


# ---------------------------------------------------------------------------
# Test 7 — links_count
# ---------------------------------------------------------------------------

def test_links_count():
    chain = [
        make_link("A", 100.0, 0.5, 0.5, "positive"),
        make_link("B",  30.0, 0.2, 0.2, "negative"),
        make_link("C",  20.0, 0.1, 0.1, "negative"),
    ]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    assert report.links_count == 3


# ---------------------------------------------------------------------------
# Test 8 — Symmetric bilateral tolerances: t+ == t−
# ---------------------------------------------------------------------------

def test_symmetric_tolerances_wc_correct():
    """Symmetric tolerance ±0.25 gives T_WC = 0.25 (same as asymmetric with t_max=0.25)."""
    chain = [make_link("X", 50.0, 0.25, 0.25, "positive")]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    assert abs(report.worst_case_min_mm - 49.75) < 1e-9
    assert abs(report.worst_case_max_mm - 50.25) < 1e-9


# ---------------------------------------------------------------------------
# Test 9 — Asymmetric tolerances: t_max picks the larger half
# ---------------------------------------------------------------------------

def test_asymmetric_tolerance_picks_larger_half():
    """Link with +0.3/−0.1 → t_max=0.3; WC = 0.3."""
    chain = [make_link("Y", 20.0, 0.3, 0.1, "positive")]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    assert abs(report.worst_case_min_mm - (20.0 - 0.3)) < 1e-9
    assert abs(report.worst_case_max_mm - (20.0 + 0.3)) < 1e-9


# ---------------------------------------------------------------------------
# Test 10 — Single-link chain: RSS == WC (sqrt of one term = that term)
# ---------------------------------------------------------------------------

def test_single_link_rss_equals_wc():
    """With one link, T_RSS = sqrt(t²) = t = T_WC."""
    chain = [make_link("Z", 10.0, 0.4, 0.4, "positive")]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    assert abs(report.rss_min_mm - report.worst_case_min_mm) < 1e-9
    assert abs(report.rss_max_mm - report.worst_case_max_mm) < 1e-9


# ---------------------------------------------------------------------------
# Test 11 — RSS is always less aggressive (tighter range) than WC
# ---------------------------------------------------------------------------

def test_rss_less_aggressive_than_wc():
    """For N>1 links: T_RSS < T_WC → rss range strictly inside wc range."""
    chain = [
        make_link("A", 80.0, 0.4, 0.4, "positive"),
        make_link("B", 30.0, 0.3, 0.3, "negative"),
    ]
    report = compute_dimension_chain(chain, 0.0, 200.0)
    assert report.rss_min_mm > report.worst_case_min_mm
    assert report.rss_max_mm < report.worst_case_max_mm


# ---------------------------------------------------------------------------
# Test 12 — All-positive chain
# ---------------------------------------------------------------------------

def test_all_positive_chain():
    """Two positive links: gap = 10 + 20 = 30; WC spread = ±0.6."""
    chain = [
        make_link("P1", 10.0, 0.3, 0.3, "positive"),
        make_link("P2", 20.0, 0.3, 0.3, "positive"),
    ]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    assert abs(report.nominal_gap_mm - 30.0) < 1e-9
    assert abs(report.worst_case_min_mm - 29.4) < 1e-9
    assert abs(report.worst_case_max_mm - 30.6) < 1e-9


# ---------------------------------------------------------------------------
# Test 13 — All-negative chain (gap should be negative)
# ---------------------------------------------------------------------------

def test_all_negative_chain():
    """Three negative links: gap = −50; WC spread = ±0.8."""
    chain = [
        make_link("N1", 20.0, 0.4, 0.4, "negative"),
        make_link("N2", 15.0, 0.2, 0.2, "negative"),
        make_link("N3", 15.0, 0.2, 0.2, "negative"),
    ]
    report = compute_dimension_chain(chain, -100.0, 0.0)
    assert abs(report.nominal_gap_mm - (-50.0)) < 1e-9
    assert abs(report.worst_case_max_mm - (-50.0 + 0.8)) < 1e-9
    assert abs(report.worst_case_min_mm - (-50.0 - 0.8)) < 1e-9


# ---------------------------------------------------------------------------
# Test 14 — dominant_link picks correct ID when middle link is largest
# ---------------------------------------------------------------------------

def test_dominant_link_middle():
    """Middle link has t_max=0.8 > others (0.2, 0.3)."""
    chain = [
        make_link("first",  5.0, 0.2, 0.2, "positive"),
        make_link("middle", 5.0, 0.8, 0.8, "positive"),
        make_link("last",   5.0, 0.3, 0.3, "negative"),
    ]
    report = compute_dimension_chain(chain, 0.0, 100.0)
    assert report.dominant_link == "middle"


# ---------------------------------------------------------------------------
# Test 15 — Zero-tolerance links contribute nothing to stack-up
# ---------------------------------------------------------------------------

def test_zero_tolerance_link_ignored_in_stackup():
    """A zero-tolerance link does not increase T_WC or T_RSS."""
    chain_with_zero = [
        make_link("A", 50.0, 0.5, 0.5, "positive"),
        make_link("B", 10.0, 0.0, 0.0, "negative"),  # zero tolerance
    ]
    chain_without = [make_link("A", 50.0, 0.5, 0.5, "positive")]
    # Nominal gap differs (40 vs 50) but spread should be same (only link A contributes)
    r_with = compute_dimension_chain(chain_with_zero, 0.0, 100.0)
    r_without = compute_dimension_chain(chain_without, 0.0, 100.0)
    wc_spread_with = r_with.worst_case_max_mm - r_with.worst_case_min_mm
    wc_spread_without = r_without.worst_case_max_mm - r_without.worst_case_min_mm
    assert abs(wc_spread_with - wc_spread_without) < 1e-9


# ---------------------------------------------------------------------------
# Test 16 — DimensionLink validation: bad direction raises ValueError
# ---------------------------------------------------------------------------

def test_bad_direction_raises():
    with pytest.raises(ValueError, match="direction must be one of"):
        DimensionLink(
            link_id="bad",
            nominal_mm=10.0,
            tol_plus_mm=0.1,
            tol_minus_mm=0.1,
            direction="sideways",
        )


# ---------------------------------------------------------------------------
# Test 17 — DimensionLink validation: negative tol raises ValueError
# ---------------------------------------------------------------------------

def test_negative_tolerance_raises():
    with pytest.raises(ValueError, match="tol_plus_mm must be >= 0"):
        DimensionLink(
            link_id="neg_tol",
            nominal_mm=10.0,
            tol_plus_mm=-0.1,
            tol_minus_mm=0.1,
            direction="positive",
        )


# ---------------------------------------------------------------------------
# Test 18 — compute_dimension_chain: empty chain raises ValueError
# ---------------------------------------------------------------------------

def test_empty_chain_raises():
    with pytest.raises(ValueError, match="chain must not be empty"):
        compute_dimension_chain([], 0.0, 10.0)


# ---------------------------------------------------------------------------
# Test 19 — target_gap_min > target_gap_max raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_target_gap_order_raises():
    chain = [make_link("A", 10.0, 0.1, 0.1, "positive")]
    with pytest.raises(ValueError, match="target_gap_min_mm.*<=.*target_gap_max_mm"):
        compute_dimension_chain(chain, 5.0, 2.0)


# ---------------------------------------------------------------------------
# Test 20 — honest_caveat is non-empty
# ---------------------------------------------------------------------------

def test_honest_caveat_nonempty():
    chain = [make_link("A", 10.0, 0.1, 0.1, "positive")]
    report = compute_dimension_chain(chain, 0.0, 20.0)
    assert report.honest_caveat
    assert len(report.honest_caveat) > 30


# ---------------------------------------------------------------------------
# Test 21 — to_dict() round-trip
# ---------------------------------------------------------------------------

def test_report_to_dict_keys():
    chain = [make_link("A", 10.0, 0.1, 0.1, "positive")]
    report = compute_dimension_chain(chain, 0.0, 20.0)
    d = report.to_dict()
    expected_keys = {
        "nominal_gap_mm", "worst_case_min_mm", "worst_case_max_mm",
        "rss_min_mm", "rss_max_mm", "links_count", "dominant_link",
        "honest_caveat",
    }
    assert set(d.keys()) == expected_keys


# ---------------------------------------------------------------------------
# Test 22 — DimensionLink.to_dict() / from_dict() round-trip
# ---------------------------------------------------------------------------

def test_dimension_link_dict_roundtrip():
    link = make_link("shaft", 100.0, 0.05, 0.03, "positive")
    d = link.to_dict()
    restored = DimensionLink.from_dict(d)
    assert restored.link_id == link.link_id
    assert restored.nominal_mm == link.nominal_mm
    assert restored.tol_plus_mm == link.tol_plus_mm
    assert restored.tol_minus_mm == link.tol_minus_mm
    assert restored.direction == link.direction


# ---------------------------------------------------------------------------
# Test 23 — Large chain: 10 links, equal tolerances, RSS scaling
# ---------------------------------------------------------------------------

def test_large_chain_rss_scaling():
    """
    10 positive links, each nominal=1.0, tol=0.1:
    Nominal gap = 10.0
    T_RSS = sqrt(10 × 0.01) = sqrt(0.10) ≈ 0.3162...
    T_WC  = 10 × 0.1 = 1.0
    """
    chain = [make_link(f"L{i}", 1.0, 0.1, 0.1, "positive") for i in range(10)]
    report = compute_dimension_chain(chain, 0.0, 20.0)
    assert abs(report.nominal_gap_mm - 10.0) < 1e-9
    assert abs(report.worst_case_min_mm - 9.0) < 1e-9
    assert abs(report.worst_case_max_mm - 11.0) < 1e-9
    expected_rss = math.sqrt(10 * 0.01)
    assert abs(report.rss_min_mm - (10.0 - expected_rss)) < 1e-9
    assert abs(report.rss_max_mm - (10.0 + expected_rss)) < 1e-9


# ---------------------------------------------------------------------------
# Test 24 — Bralla §1 example: tolerance accumulation for a pin-in-hole
#           (simulated: positive housing depth 50±0.3, negative pin length 48±0.2)
# ---------------------------------------------------------------------------

def test_pin_in_hole_clearance():
    """
    Housing depth (positive) = 50.0 ± 0.3
    Pin length   (negative)  = 48.0 ± 0.2
    Nominal gap = 50 − 48 = 2.0 mm
    WC: gap_min = 2.0 − 0.5 = 1.5 mm; gap_max = 2.0 + 0.5 = 2.5 mm
    RSS: T_RSS = sqrt(0.09 + 0.04) = sqrt(0.13) ≈ 0.3606
    """
    chain = [
        make_link("housing_depth", 50.0, 0.3, 0.3, "positive"),
        make_link("pin_length",    48.0, 0.2, 0.2, "negative"),
    ]
    report = compute_dimension_chain(chain, 0.5, 4.0)
    assert abs(report.nominal_gap_mm - 2.0) < 1e-9
    assert abs(report.worst_case_min_mm - 1.5) < 1e-9
    assert abs(report.worst_case_max_mm - 2.5) < 1e-9
    expected_rss = math.sqrt(0.09 + 0.04)
    assert abs(report.rss_min_mm - (2.0 - expected_rss)) < 1e-9
    assert abs(report.rss_max_mm - (2.0 + expected_rss)) < 1e-9
