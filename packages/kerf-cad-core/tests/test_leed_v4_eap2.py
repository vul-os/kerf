"""
Tests for kerf_cad_core.buildingenergy.leed_v4_eap2

Tests cover:
  - 5% savings → prerequisite_met=True
  - 4% savings → prerequisite_met=False
  - 0% savings → prerequisite_met=False
  - Negative savings → prerequisite_met=False
  - 6% savings → 1 EAc1 point
  - 50% savings → 18 EAc1 points (maximum)
  - 30% savings → 13 points (from tier table)
  - Core & Shell gets 2% bonus → 4% savings gives 1 point
  - Renewable offset reduces net proposed EUI
  - Prerequisites not met → 0 EAc1 points
  - Invalid proposed EUI raises ValueError
  - Invalid baseline EUI raises ValueError
  - energy_savings_pct formula correct
  - Point detail narrative is non-empty when prereq met
  - LEED v4.0 rating system accepted
"""
from __future__ import annotations

import pytest

from kerf_cad_core.buildingenergy.leed_v4_eap2 import (
    LeedEAp2Spec,
    LeedEAp2Report,
    evaluate_leed_v4_eap2,
    _leed_eac1_points,
    _EAP2_MIN_PCT,
    _LEED_V41_POINTS_TABLE,
)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _spec(
    proposed_eui: float,
    baseline_eui: float,
    project_type: str = "new_construction",
    renewables: float = 0.0,
) -> LeedEAp2Spec:
    return LeedEAp2Spec(
        project_type=project_type,
        proposed_annual_eui=proposed_eui,
        baseline_annual_eui=baseline_eui,
        renewables_offset_kwh_m2=renewables,
    )


def _savings_pct(proposed: float, baseline: float) -> float:
    return (baseline - proposed) / baseline * 100.0


# ---------------------------------------------------------------------------
# EAp2 prerequisite tests
# ---------------------------------------------------------------------------

class TestLeedEAp2Prerequisite:

    def test_5pct_savings_prereq_met(self):
        """5% savings meets EAp2 minimum threshold."""
        baseline = 160.0
        proposed = baseline * (1 - 0.05)
        report = evaluate_leed_v4_eap2(_spec(proposed, baseline))
        assert report.prerequisite_met is True, (
            f"5% savings should meet EAp2; savings={report.energy_savings_pct:.2f}%"
        )

    def test_4pct_savings_prereq_not_met(self):
        """4% savings is below 5% minimum → prerequisite NOT met."""
        baseline = 160.0
        proposed = baseline * (1 - 0.04)
        report = evaluate_leed_v4_eap2(_spec(proposed, baseline))
        assert report.prerequisite_met is False, (
            f"4% savings should fail EAp2; savings={report.energy_savings_pct:.2f}%"
        )

    def test_4pct_yields_zero_eac1_points(self):
        baseline = 160.0
        proposed = baseline * (1 - 0.04)
        report = evaluate_leed_v4_eap2(_spec(proposed, baseline))
        assert report.optional_eac1_points == 0

    def test_0pct_savings_prereq_not_met(self):
        report = evaluate_leed_v4_eap2(_spec(160.0, 160.0))
        assert report.prerequisite_met is False

    def test_negative_savings_prereq_not_met(self):
        """Building worse than baseline → not met."""
        report = evaluate_leed_v4_eap2(_spec(180.0, 160.0))
        assert report.prerequisite_met is False
        assert report.energy_savings_pct < 0

    def test_minimum_threshold_is_5_for_new_construction(self):
        report = evaluate_leed_v4_eap2(_spec(150.0, 160.0))
        assert report.minimum_threshold_pct == 5.0

    def test_minimum_threshold_is_5_for_major_renovation(self):
        spec = _spec(150.0, 160.0, project_type="major_renovation")
        report = evaluate_leed_v4_eap2(spec)
        assert report.minimum_threshold_pct == 5.0

    def test_minimum_threshold_is_3_for_core_and_shell(self):
        spec = _spec(155.0, 160.0, project_type="core_and_shell")
        report = evaluate_leed_v4_eap2(spec)
        assert report.minimum_threshold_pct == 3.0

    def test_core_and_shell_3pct_prereq_met(self):
        """Core & Shell: 3.1% savings meets 3% threshold."""
        baseline = 160.0
        proposed = baseline * (1 - 0.031)
        spec = _spec(proposed, baseline, project_type="core_and_shell")
        report = evaluate_leed_v4_eap2(spec)
        assert report.prerequisite_met is True


# ---------------------------------------------------------------------------
# EAc1 optional points tests
# ---------------------------------------------------------------------------

class TestLeedEAc1Points:

    def test_6pct_savings_earns_1_point(self):
        baseline = 160.0
        proposed = baseline * (1 - 0.06)
        report = evaluate_leed_v4_eap2(_spec(proposed, baseline))
        assert report.optional_eac1_points >= 1, (
            f"6% savings should earn ≥1 EAc1 point; got {report.optional_eac1_points}"
        )

    def test_10pct_savings_earns_3_points(self):
        baseline = 160.0
        proposed = baseline * (1 - 0.10)
        report = evaluate_leed_v4_eap2(_spec(proposed, baseline))
        assert report.optional_eac1_points >= 3

    def test_30pct_savings_earns_13_points(self):
        baseline = 160.0
        proposed = baseline * (1 - 0.30)
        report = evaluate_leed_v4_eap2(_spec(proposed, baseline))
        assert report.optional_eac1_points == 13, (
            f"30% savings should yield 13 points; got {report.optional_eac1_points}"
        )

    def test_50pct_savings_earns_max_18_points(self):
        baseline = 160.0
        proposed = baseline * (1 - 0.50)
        report = evaluate_leed_v4_eap2(_spec(proposed, baseline))
        assert report.optional_eac1_points == 18

    def test_60pct_savings_still_max_18_points(self):
        baseline = 160.0
        proposed = baseline * (1 - 0.60)
        report = evaluate_leed_v4_eap2(_spec(proposed, baseline))
        assert report.optional_eac1_points == 18  # capped at 18

    def test_points_monotonically_increasing(self):
        """Higher savings always gives same or more points."""
        baseline = 200.0
        prev_pts = 0
        for pct in [5, 6, 8, 10, 12, 14, 16, 18, 20, 26, 30, 38, 46, 50]:
            proposed = baseline * (1 - pct / 100.0)
            report = evaluate_leed_v4_eap2(_spec(proposed, baseline))
            assert report.optional_eac1_points >= prev_pts, (
                f"{pct}% savings: points {report.optional_eac1_points} < previous {prev_pts}"
            )
            prev_pts = report.optional_eac1_points

    def test_core_and_shell_bonus_at_4pct(self):
        """Core & Shell: 4% savings + 2% bonus = 6% effective → 1 point."""
        baseline = 160.0
        proposed = baseline * (1 - 0.04)  # only 4% savings
        spec = _spec(proposed, baseline, project_type="core_and_shell")
        report = evaluate_leed_v4_eap2(spec)
        # 4% < 5% NC threshold but ≥3% C&S threshold → prereq met
        assert report.prerequisite_met is True
        # With 2% bonus: effective 6% → 1 point
        assert report.optional_eac1_points >= 1


# ---------------------------------------------------------------------------
# Renewable offset tests
# ---------------------------------------------------------------------------

class TestRenewableOffset:

    def test_renewable_offset_reduces_net_eui(self):
        spec = _spec(proposed_eui=150.0, baseline_eui=160.0, renewables=10.0)
        report = evaluate_leed_v4_eap2(spec)
        assert report.net_proposed_eui < 150.0
        assert abs(report.net_proposed_eui - 140.0) < 0.01

    def test_renewable_offset_improves_points(self):
        baseline = 200.0
        proposed_no_pv = baseline * 0.94  # 6% savings → 1 point
        proposed_with_pv = proposed_no_pv - 10.0  # PV offsets 10 kWh/m²
        spec_no_pv = _spec(proposed_no_pv, baseline)
        spec_with_pv = _spec(proposed_no_pv, baseline, renewables=10.0)
        r_no = evaluate_leed_v4_eap2(spec_no_pv)
        r_yes = evaluate_leed_v4_eap2(spec_with_pv)
        assert r_yes.optional_eac1_points >= r_no.optional_eac1_points


# ---------------------------------------------------------------------------
# Report fields tests
# ---------------------------------------------------------------------------

class TestLeedReportFields:

    def test_savings_pct_formula(self):
        baseline = 160.0
        proposed = 140.0
        report = evaluate_leed_v4_eap2(_spec(proposed, baseline))
        expected = (baseline - proposed) / baseline * 100.0
        assert abs(report.energy_savings_pct - expected) < 0.01

    def test_point_detail_non_empty_when_prereq_met(self):
        report = evaluate_leed_v4_eap2(_spec(140.0, 160.0))
        assert len(report.point_detail) >= 1
        assert any("MET" in d.upper() or "prerequisite" in d.lower() for d in report.point_detail)

    def test_caveat_non_empty(self):
        report = evaluate_leed_v4_eap2(_spec(140.0, 160.0))
        assert len(report.honest_caveat) > 30

    def test_leed_v40_rating_system_accepted(self):
        spec = LeedEAp2Spec(
            project_type="new_construction",
            proposed_annual_eui=140.0,
            baseline_annual_eui=160.0,
            rating_system="BD+C v4.0",
        )
        report = evaluate_leed_v4_eap2(spec)
        assert isinstance(report, LeedEAp2Report)

    def test_invalid_proposed_eui_raises(self):
        with pytest.raises(ValueError, match="proposed_annual_eui"):
            evaluate_leed_v4_eap2(_spec(0.0, 160.0))

    def test_invalid_baseline_eui_raises(self):
        with pytest.raises(ValueError, match="baseline_annual_eui"):
            evaluate_leed_v4_eap2(_spec(140.0, 0.0))

    def test_schools_project_type_accepted(self):
        spec = _spec(130.0, 145.0, project_type="schools")
        report = evaluate_leed_v4_eap2(spec)
        assert isinstance(report, LeedEAp2Report)
