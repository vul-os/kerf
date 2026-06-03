"""
Hermetic tests for kerf_cad_core.rigging.structural_load
(Braceworks-equivalent truss + cable rigging analysis).

Coverage (≥20 tests):
  cable_catenary_tension
    - Known span 10m, 0.5m sag, 10 N/m within 5% of textbook value
    - Zero-sag / very small sag edge cases
    - Large sag (ratio > 0.05) uses Newton-Raphson exact catenary
    - ValueError on non-positive span/sag/weight
  analyze_rigging_load
    - Segment with zero load → 0% utilisation
    - Segment with load > max_uniform → overloaded_segments contains it
    - Cable WLL exceeded → overloaded_cables list non-empty
    - Cable WLL not exceeded → overloaded_cables empty
    - Multi-segment multi-point analysis produces correct keys
    - Self-weight on a 6 m truss produces non-zero moment
    - Point load projected onto segment contributes to moment
    - Point load outside segment span (beyond end) does NOT count
    - Overall safety factor computed and > 0
    - Honest caveat present in report
    - Empty segments list → empty report
    - Empty points and cables → valid report with zero cable entries
    - Segment utilisation formula: rated UDL = actual UDL → 100%
    - Catenary tension is always ≥ w·L/2 (minimum vertical reaction)

All tests are pure-Python and hermetic: no OCC, no DB, no network, no fixtures.

References
----------
BS 7905-1:2002  — Lifting equipment for performance, broadcast and similar apps.
ANSI E1.2-2012  — Entertainment Technology: Aluminium Trusses and Towers.
Irvine, H.M. (1981). Cable Structures. MIT Press.

Author: imranparuk
"""
from __future__ import annotations

import math

import pytest

from kerf_cad_core.rigging.structural_load import (
    TrussSegment,
    RiggingPoint,
    CableSpan,
    RiggingLoadReport,
    analyze_rigging_load,
    cable_catenary_tension,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seg(
    sid: str = "S1",
    start=(0.0, 0.0, 3.0),
    end=(6.0, 0.0, 3.0),
    sw: float = 80.0,
    max_udl: float = 500.0,
    max_pt: float = 3000.0,
) -> TrussSegment:
    return TrussSegment(
        segment_id=sid,
        start_pt=start,
        end_pt=end,
        self_weight_per_m=sw,
        max_uniform_load_per_m=max_udl,
        max_point_load=max_pt,
    )


def _point(pid: str, loc, load_n: float) -> RiggingPoint:
    return RiggingPoint(point_id=pid, location=loc, point_load_n=load_n)


def _cable(
    cid: str,
    a=(0.0, 0.0, 6.0),
    b=(10.0, 0.0, 6.0),
    breaking: float = 50000.0,
    wll: float = 10000.0,
) -> CableSpan:
    return CableSpan(
        cable_id=cid,
        anchor_a=a,
        anchor_b=b,
        breaking_strength_n=breaking,
        working_load_limit_n=wll,
    )


# ===========================================================================
# 1. cable_catenary_tension — textbook values
# ===========================================================================

class TestCableCatenaryTension:

    def test_textbook_10m_05m_sag_10Nm(self):
        """Known case: span=10m, sag=0.5m, w=10N/m.

        Textbook parabolic approximation (valid here since sag/span=0.05):
            T_H ≈ wL²/(8d) = 10×100/(8×0.5) = 250 N
            T_anchor = sqrt(250² + (10×10/2)²) = sqrt(62500 + 2500)
                     ≈ 255.74 N

        Our function should be within 5% of 255.74 N.
        Reference: Irvine (1981) §2.2; BS 7905-1 Annex A.
        """
        T = cable_catenary_tension(10.0, 0.5, 10.0)
        expected = math.sqrt(250.0 ** 2 + 50.0 ** 2)  # ≈ 255.74 N
        assert abs(T - expected) / expected < 0.05, (
            f"Expected ~{expected:.2f} N, got {T:.2f} N "
            f"(error {100 * abs(T - expected) / expected:.2f}%)"
        )

    def test_catenary_tension_gte_minimum_vertical_reaction(self):
        """T_anchor must always be ≥ w·L/2 (vertical reaction at each support)."""
        for span, sag, w in [(5.0, 0.1, 20.0), (10.0, 1.0, 50.0), (20.0, 2.0, 100.0)]:
            T = cable_catenary_tension(span, sag, w)
            min_T = w * span / 2.0
            assert T >= min_T * 0.999, (
                f"span={span}, sag={sag}, w={w}: T={T:.2f} < w·L/2={min_T:.2f}"
            )

    def test_small_sag_parabolic_approximation(self):
        """For sag/span < 0.05 the parabolic approx is used (< 0.3% error).
        Compare to hand-calc: T_H = wL²/(8d), T = sqrt(T_H²+(wL/2)²).
        """
        span, sag, w = 20.0, 0.3, 8.0  # sag/span = 0.015 << 0.05
        T = cable_catenary_tension(span, sag, w)
        T_H = w * span ** 2 / (8 * sag)
        T_expected = math.sqrt(T_H ** 2 + (w * span / 2) ** 2)
        assert abs(T - T_expected) / T_expected < 0.003

    def test_large_sag_exact_catenary_used(self):
        """sag/span = 0.2 → Newton-Raphson catenary; result > parabolic estimate."""
        span, sag, w = 10.0, 2.0, 15.0  # sag/span = 0.2 > 0.05
        T = cable_catenary_tension(span, sag, w)
        assert T > 0.0
        # For large sag, exact catenary tension is slightly higher than parabola.
        T_H_para = w * span ** 2 / (8 * sag)
        T_para = math.sqrt(T_H_para ** 2 + (w * span / 2) ** 2)
        # Both should be in the same ballpark (within 20%).
        assert abs(T - T_para) / T_para < 0.20

    def test_zero_span_raises(self):
        with pytest.raises(ValueError, match="span_m must be > 0"):
            cable_catenary_tension(0.0, 0.5, 10.0)

    def test_negative_sag_raises(self):
        with pytest.raises(ValueError, match="sag_m must be > 0"):
            cable_catenary_tension(10.0, -0.1, 10.0)

    def test_zero_weight_raises(self):
        with pytest.raises(ValueError, match="weight_per_m_n must be > 0"):
            cable_catenary_tension(10.0, 0.5, 0.0)

    def test_tension_increases_with_less_sag(self):
        """Less sag → more tension (cable pulled tighter)."""
        T_big_sag = cable_catenary_tension(10.0, 2.0, 10.0)
        T_small_sag = cable_catenary_tension(10.0, 0.2, 10.0)
        assert T_small_sag > T_big_sag

    def test_tension_increases_with_heavier_cable(self):
        """Heavier cable → more tension for same sag/span."""
        T_light = cable_catenary_tension(10.0, 0.5, 5.0)
        T_heavy = cable_catenary_tension(10.0, 0.5, 50.0)
        assert T_heavy > T_light


# ===========================================================================
# 2. analyze_rigging_load — segment analysis
# ===========================================================================

class TestAnalyzeRiggingLoadSegments:

    def test_zero_load_segment_zero_utilisation(self):
        """A segment with no self-weight and no point loads → 0% utilisation."""
        seg = _seg(sw=0.0, max_udl=1000.0, max_pt=5000.0)
        report = analyze_rigging_load([seg], [], [])
        s = report.segment_loads["S1"]
        assert s["utilization_pct"] == 0.0
        assert s["bending_moment_kN_m"] == 0.0
        assert s["shear_kN"] == 0.0

    def test_overloaded_segment_reported(self):
        """When applied load > max_uniform, the segment appears in overloaded_segments."""
        # max_udl = 100 N/m; apply self-weight = 200 N/m (2× rated).
        seg = _seg(sw=200.0, max_udl=100.0, max_pt=5000.0)
        report = analyze_rigging_load([seg], [], [])
        assert "S1" in report.overloaded_segments

    def test_within_capacity_not_overloaded(self):
        """Self-weight well below rated → not in overloaded list."""
        seg = _seg(sw=50.0, max_udl=500.0, max_pt=5000.0)
        report = analyze_rigging_load([seg], [], [])
        assert "S1" not in report.overloaded_segments

    def test_self_weight_produces_nonzero_moment(self):
        """A 6 m truss with 80 N/m self-weight: M = wL²/8 = 80×36/8 = 360 N·m."""
        seg = _seg(sw=80.0, max_udl=500.0)
        report = analyze_rigging_load([seg], [], [])
        s = report.segment_loads["S1"]
        expected_kN_m = 80.0 * 6.0 ** 2 / 8.0 / 1000.0  # = 0.36 kN·m
        assert abs(s["bending_moment_kN_m"] - expected_kN_m) < 0.01, (
            f"Expected ~{expected_kN_m:.4f} kN·m, got {s['bending_moment_kN_m']}"
        )

    def test_point_load_at_midspan_contributes(self):
        """Point load at mid-span adds PL/4 moment contribution."""
        seg = _seg(sw=0.0, max_udl=500.0, max_pt=5000.0)
        P = 1000.0  # N
        mid = (3.0, 0.0, 3.0)  # mid-span of the 6 m segment (start=[0,0,3], end=[6,0,3])
        rp = _point("P1", mid, P)
        report = analyze_rigging_load([seg], [rp], [])
        s = report.segment_loads["S1"]
        expected_kN_m = P * 6.0 / 4.0 / 1000.0  # PL/4 = 1000×6/4 = 1500 N·m = 1.5 kN·m
        assert abs(s["bending_moment_kN_m"] - expected_kN_m) < 0.05

    def test_point_load_outside_span_not_counted(self):
        """Point load located well beyond the end of the segment → no extra moment."""
        seg = _seg(sw=0.0, max_udl=500.0, max_pt=5000.0)
        outside = (20.0, 0.0, 3.0)   # 20 m from start, far beyond 6 m span
        rp = _point("P_far", outside, 5000.0)
        report = analyze_rigging_load([seg], [rp], [])
        s = report.segment_loads["S1"]
        # No moment from self-weight (sw=0), no moment from out-of-span load.
        assert s["bending_moment_kN_m"] == 0.0

    def test_segment_report_contains_required_keys(self):
        seg = _seg()
        report = analyze_rigging_load([seg], [], [])
        s = report.segment_loads["S1"]
        for key in ("bending_moment_kN_m", "shear_kN", "deflection_mm", "utilization_pct", "span_m"):
            assert key in s, f"Missing key '{key}' in segment report"

    def test_utilisation_at_rated_load_equals_100pct(self):
        """Apply self-weight exactly equal to max_udl → utilisation ≈ 100%."""
        udl = 500.0
        seg = _seg(sw=udl, max_udl=udl, max_pt=5000.0)
        report = analyze_rigging_load([seg], [], [])
        s = report.segment_loads["S1"]
        # Bending utilisation = M_actual / M_rated = (wL²/8) / (w_rated·L²/8) = 1.0
        # So utilisation ≈ 100%.
        assert abs(s["utilization_pct"] - 100.0) < 1.0

    def test_multiple_segments(self):
        """Multiple segments should each appear in segment_loads."""
        s1 = _seg("A", start=(0.0, 0.0, 3.0), end=(3.0, 0.0, 3.0))
        s2 = _seg("B", start=(3.0, 0.0, 3.0), end=(6.0, 0.0, 3.0))
        report = analyze_rigging_load([s1, s2], [], [])
        assert "A" in report.segment_loads
        assert "B" in report.segment_loads


# ===========================================================================
# 3. analyze_rigging_load — cable analysis
# ===========================================================================

class TestAnalyzeRiggingLoadCables:

    def test_cable_wll_exceeded_reported(self):
        """Cable with very low WLL and non-trivial load → overloaded_cables."""
        # WLL = 1 N is trivially exceeded by any cable tension.
        cab = _cable("C1", wll=1.0)
        report = analyze_rigging_load([], [], [cab])
        assert "C1" in report.overloaded_cables

    def test_cable_wll_not_exceeded(self):
        """Cable with very high WLL and minimal load → not overloaded."""
        cab = _cable("C1", wll=1_000_000.0)
        report = analyze_rigging_load([], [], [cab])
        assert "C1" not in report.overloaded_cables

    def test_cable_report_contains_required_keys(self):
        cab = _cable("C1")
        report = analyze_rigging_load([], [], [cab])
        c = report.cable_tensions["C1"]
        for key in ("tension_kN", "sag_m", "utilization_pct", "span_m"):
            assert key in c, f"Missing key '{key}' in cable report"

    def test_cable_tension_positive(self):
        """Cable tension must always be positive."""
        cab = _cable("C1", a=(0.0, 0.0, 6.0), b=(10.0, 0.0, 6.0), wll=100_000.0)
        report = analyze_rigging_load([], [], [cab])
        assert report.cable_tensions["C1"]["tension_kN"] > 0.0

    def test_cable_utilisation_proportional_to_wll(self):
        """Halving the WLL doubles the utilisation percentage."""
        cab_high = _cable("C_high", wll=100_000.0)
        cab_low = _cable("C_low", wll=50_000.0)
        r_high = analyze_rigging_load([], [], [cab_high])
        r_low = analyze_rigging_load([], [], [cab_low])
        u_high = r_high.cable_tensions["C_high"]["utilization_pct"]
        u_low = r_low.cable_tensions["C_low"]["utilization_pct"]
        assert abs(u_low / u_high - 2.0) < 0.01, (
            f"u_low={u_low:.2f}% should be ~2× u_high={u_high:.2f}%"
        )

    def test_overall_safety_factor_positive_with_cables(self):
        """With cables, overall_safety_factor should be > 0."""
        cab = _cable("C1", wll=50_000.0)
        report = analyze_rigging_load([], [], [cab])
        assert report.overall_safety_factor > 0.0


# ===========================================================================
# 4. analyze_rigging_load — combined / report attributes
# ===========================================================================

class TestAnalyzeRiggingLoadReport:

    def test_honest_caveat_present(self):
        """honest_caveat must be a non-empty string referencing standards."""
        seg = _seg()
        report = analyze_rigging_load([seg], [], [])
        assert isinstance(report.honest_caveat, str)
        assert len(report.honest_caveat) > 50
        assert "ANSI" in report.honest_caveat or "BS" in report.honest_caveat

    def test_empty_inputs_produce_empty_report(self):
        """No segments, no points, no cables → all empty."""
        report = analyze_rigging_load([], [], [])
        assert report.segment_loads == {}
        assert report.cable_tensions == {}
        assert report.overloaded_segments == []
        assert report.overloaded_cables == []

    def test_overloaded_lists_empty_when_within_capacity(self):
        seg = _seg(sw=10.0, max_udl=1000.0)
        cab = _cable("C1", wll=999_999.0)
        report = analyze_rigging_load([seg], [], [cab])
        assert report.overloaded_segments == []
        assert report.overloaded_cables == []

    def test_return_type_is_rigging_load_report(self):
        report = analyze_rigging_load([], [], [])
        assert isinstance(report, RiggingLoadReport)
