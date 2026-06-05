"""
Tests for kerf_energy ASHRAE 90.1 Appendix G + LEED EAp2 + Title 24 compliance.

Test oracles
------------
1. Efficient proposed building (superior envelope + HVAC) → PCI < 1.0 and
   positive % improvement vs. the 90.1 baseline.
2. Baseline system selection returns correct 90.1 system class for representative
   building size / type / climate combinations.
3. LEED EAc2 points are monotonically non-decreasing with % improvement.
4. Title 24 compliance: proposed TDV < baseline TDV → pass.
5. energy_ashrae901_appendixg_report tool round-trips through JSON correctly.
6. energy_leed_eap2_points tool returns correct prerequisite + points.
7. energy_title24_compliance tool returns PASS for an efficient building.
"""
from __future__ import annotations

import json
import math
import asyncio
import pytest

from kerf_energy.ashrae901_appendixg import (
    ProposedBuildingSpec,
    compute_appendixg_report,
    select_ashrae901_baseline_system,
    _leed_eac2_points,
    _check_title24,
    EndUseBreakdown,
    _synthesise_weather,
    _simulate_building_v2,
)
from kerf_energy.compliance_tools import (
    run_energy_ashrae901_appendixg_report,
    run_energy_leed_eap2_points,
    run_energy_title24_compliance,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _Ctx:
    """Minimal stub for ProjectCtx."""
    pass


def _run(coro):
    """Run coroutine synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


def _efficient_spec(**overrides) -> ProposedBuildingSpec:
    """Return a high-efficiency proposed building spec (CZ4 office, 3 floors)."""
    defaults = dict(
        name="Test Office",
        building_type="office",
        floor_area_m2=5000.0,
        num_floors=3,
        climate_zone=4,
        heating_fuel="gas",
        window_to_wall_ratio=0.35,
        u_wall=0.20,        # well below baseline 0.513 for CZ4
        u_roof=0.10,        # well below baseline 0.220
        u_window=1.50,      # below baseline 3.407
        shgc=0.25,
        internal_load_w_m2=20.0,
        hvac_heating_cop=0.95,   # 95% AFUE condensing gas
        hvac_cooling_cop=5.5,    # high-efficiency chiller
        climate_mean_c=8.0,
        climate_amplitude_c=12.0,
    )
    defaults.update(overrides)
    return ProposedBuildingSpec(**defaults)


def _baseline_spec(**overrides) -> ProposedBuildingSpec:
    """Return a proposed spec that matches the baseline (should give PCI ~ 1)."""
    # Use baseline envelope values for CZ4
    defaults = dict(
        name="Baseline-Match Office",
        building_type="office",
        floor_area_m2=5000.0,
        num_floors=3,
        climate_zone=4,
        heating_fuel="gas",
        window_to_wall_ratio=0.40,  # same as baseline cap
        u_wall=0.513,               # exactly at CZ4 baseline
        u_roof=0.220,
        u_window=3.407,
        shgc=0.40,
        internal_load_w_m2=20.0,
        hvac_heating_cop=0.80,      # baseline System 3: gas furnace 80% AFUE
        hvac_cooling_cop=3.10,      # baseline System 3: packaged DX COP
        climate_mean_c=8.0,
        climate_amplitude_c=12.0,
    )
    defaults.update(overrides)
    return ProposedBuildingSpec(**defaults)


# ---------------------------------------------------------------------------
# Oracle 1 — Efficient proposed building → PCI < 1, positive % improvement
# ---------------------------------------------------------------------------

class TestPCIOracle:

    def test_efficient_building_pci_less_than_1(self):
        """An efficient proposed building must yield PCI < 1.0."""
        report = compute_appendixg_report(_efficient_spec())
        assert report.performance_cost_index < 1.0, (
            f"Expected PCI < 1.0 for efficient building; got {report.performance_cost_index}"
        )

    def test_efficient_building_positive_pct_improvement(self):
        """Efficient building must show positive % improvement over baseline."""
        report = compute_appendixg_report(_efficient_spec())
        assert report.pct_better_than_baseline > 0.0, (
            f"Expected positive % improvement; got {report.pct_better_than_baseline:.2f}%"
        )

    def test_efficient_building_ashrae_compliant(self):
        """Efficient building must be ASHRAE 90.1 compliant."""
        report = compute_appendixg_report(_efficient_spec())
        assert report.ashrae_901_compliant is True

    def test_pci_formula_equals_cost_ratio(self):
        """PCI must equal proposed_cost / baseline_cost."""
        report = compute_appendixg_report(_efficient_spec())
        expected_pci = report.proposed_annual_cost_usd / report.baseline_annual_cost_usd
        assert math.isclose(report.performance_cost_index, expected_pci, rel_tol=1e-4), (
            f"PCI {report.performance_cost_index} ≠ cost ratio {expected_pci}"
        )

    def test_pct_better_matches_pci(self):
        """pct_better = (1 - PCI) × 100 must hold."""
        report = compute_appendixg_report(_efficient_spec())
        expected_pct = (1.0 - report.performance_cost_index) * 100.0
        assert math.isclose(report.pct_better_than_baseline, expected_pct, rel_tol=1e-3), (
            f"pct_better {report.pct_better_than_baseline:.3f} ≠ (1-PCI)×100 = {expected_pct:.3f}"
        )

    def test_poor_building_pci_greater_than_1(self):
        """A poorly-insulated building with inefficient HVAC must have PCI > 1."""
        poor_spec = ProposedBuildingSpec(
            name="Inefficient Building",
            building_type="office",
            floor_area_m2=5000.0,
            num_floors=2,
            climate_zone=4,
            heating_fuel="gas",
            window_to_wall_ratio=0.60,   # over-glazed
            u_wall=1.5,                  # very poor insulation (»baseline 0.513)
            u_roof=0.8,                  # very poor roof
            u_window=6.5,               # single-pane equivalent
            shgc=0.70,
            internal_load_w_m2=20.0,
            hvac_heating_cop=0.60,       # old furnace 60% AFUE
            hvac_cooling_cop=2.0,        # very inefficient cooling
            climate_mean_c=8.0,
            climate_amplitude_c=12.0,
        )
        report = compute_appendixg_report(poor_spec)
        assert report.performance_cost_index > 1.0, (
            f"Expected PCI > 1.0 for inefficient building; got {report.performance_cost_index}"
        )
        assert report.pct_better_than_baseline < 0.0

    def test_report_has_human_readable(self):
        """Report must include non-empty human_readable text."""
        report = compute_appendixg_report(_efficient_spec())
        assert len(report.human_readable) > 100
        assert "PCI" in report.human_readable
        assert "ASHRAE" in report.human_readable

    def test_end_use_breakdown_nonnegative(self):
        """All end-use values must be non-negative."""
        report = compute_appendixg_report(_efficient_spec())
        for eu in (report.baseline_end_use, report.proposed_end_use):
            assert eu.heating_kwh >= 0.0
            assert eu.cooling_kwh >= 0.0
            assert eu.fan_kwh >= 0.0
            assert eu.lighting_kwh >= 0.0
            assert eu.total_kwh >= 0.0

    def test_baseline_total_equals_sum_of_end_uses(self):
        """Baseline total_kwh ≈ heating + cooling + fan + lighting."""
        report = compute_appendixg_report(_efficient_spec())
        b = report.baseline_end_use
        expected = b.heating_kwh + b.cooling_kwh + b.fan_kwh + b.lighting_kwh
        assert math.isclose(b.total_kwh, expected, rel_tol=0.01), (
            f"Baseline total {b.total_kwh} ≠ sum of end-uses {expected}"
        )


# ---------------------------------------------------------------------------
# Oracle 2 — Baseline system selection per ASHRAE 90.1 Table G3.1.1
# ---------------------------------------------------------------------------

class TestBaselineSystemSelection:

    def test_small_nonres_gas_cz4_is_system3(self):
        """Small non-residential (≤75,000 ft², ≤3 floors) gas CZ4 → System 3 (PSZ-AC)."""
        sys = select_ashrae901_baseline_system("office", 5000.0, 3, 4, "gas")
        assert sys == 3, f"Expected System 3 (PSZ-AC) for small office CZ4; got {sys}"

    def test_small_nonres_electric_cz4_is_system4(self):
        """Small non-residential electric → System 4 (PSZ-HP)."""
        sys = select_ashrae901_baseline_system("office", 5000.0, 3, 4, "electric")
        assert sys == 4, f"Expected System 4 (PSZ-HP); got {sys}"

    def test_large_nonres_gas_is_system7(self):
        """Large non-residential (>150,000 ft²) gas → System 7 (Central VAV+reheat)."""
        # 150,000 ft² = 13,935 m²; use 15,000 m² to exceed threshold
        sys = select_ashrae901_baseline_system("office", 15000.0, 4, 4, "gas")
        assert sys == 7, f"Expected System 7 (VAV+reheat) for large office; got {sys}"

    def test_large_nonres_electric_is_system8(self):
        """Large non-residential electric → System 8 (VAV+PFP)."""
        sys = select_ashrae901_baseline_system("office", 15000.0, 4, 4, "electric")
        assert sys == 8, f"Expected System 8 (VAV+PFP); got {sys}"

    def test_residential_lowrise_gas_is_system1(self):
        """Residential ≤4 floors gas → System 1 (PTAC)."""
        sys = select_ashrae901_baseline_system("residential", 2000.0, 3, 4, "gas")
        assert sys == 1, f"Expected System 1 (PTAC); got {sys}"

    def test_residential_lowrise_electric_is_system2(self):
        """Residential ≤4 floors electric → System 2 (PTHP)."""
        sys = select_ashrae901_baseline_system("residential", 2000.0, 3, 4, "electric")
        assert sys == 2, f"Expected System 2 (PTHP); got {sys}"

    def test_medium_nonres_gas_is_system5(self):
        """Medium non-residential (>75,000 ft², ≤5 floors) gas → System 5 (Pkg VAV)."""
        # 75,000 ft² < area ≤ 150,000 ft²: use 8000 m² (≈86,111 ft²)
        sys = select_ashrae901_baseline_system("office", 8000.0, 4, 4, "gas")
        assert sys == 5, f"Expected System 5 (Pkg VAV+reheat); got {sys}"

    def test_tall_nonres_gas_is_system7(self):
        """Non-residential > 5 floors → System 7 (Central VAV) regardless of area."""
        sys = select_ashrae901_baseline_system("office", 5000.0, 6, 4, "gas")
        assert sys == 7, f"Expected System 7 for >5 floor building; got {sys}"

    def test_system_number_in_valid_range(self):
        """System selection must always return 1–8."""
        combos = [
            ("office", 1000, 1, 1, "gas"),
            ("office", 1000, 1, 8, "electric"),
            ("residential", 500, 2, 3, "gas"),
            ("hospital", 20000, 7, 4, "gas"),
            ("warehouse", 3000, 1, 2, "electric"),
        ]
        for btype, area, floors, cz, fuel in combos:
            sys = select_ashrae901_baseline_system(btype, area, floors, cz, fuel)
            assert 1 <= sys <= 8, f"System {sys} out of range 1–8 for {btype}"


# ---------------------------------------------------------------------------
# Oracle 3 — LEED points monotonically increase with % improvement
# ---------------------------------------------------------------------------

class TestLEEDPointsMonotonicity:

    def test_leed_points_zero_below_6_pct(self):
        """Below 6% improvement → 0 EAc2 points (EAp2 may be met at 5% but no EAc2)."""
        # Note: _leed_eac2_points checks against table, below 6% → 0 pts
        assert _leed_eac2_points(0.0) == 0
        assert _leed_eac2_points(5.9) == 0

    def test_leed_points_1_at_6_pct(self):
        assert _leed_eac2_points(6.0) == 1

    def test_leed_points_18_at_50_pct(self):
        assert _leed_eac2_points(50.0) == 18

    def test_leed_points_capped_at_18(self):
        assert _leed_eac2_points(80.0) == 18

    def test_leed_points_monotonically_nondecreasing(self):
        """LEED points must never decrease as % improvement increases."""
        prev = 0
        for pct in range(0, 60):
            pts = _leed_eac2_points(float(pct))
            assert pts >= prev, (
                f"Points decreased: {pct}% → {pts} points, prev was {prev}"
            )
            prev = pts

    def test_leed_points_increase_through_tiers(self):
        """Validate tier transitions per LEED v4.1 EAc2 table."""
        assert _leed_eac2_points(8.0) >= 2
        assert _leed_eac2_points(10.0) >= 3
        assert _leed_eac2_points(20.0) >= 8
        assert _leed_eac2_points(30.0) >= 13

    def test_report_leed_points_increase_with_efficiency(self):
        """More efficient proposed building earns more LEED points."""
        # Moderately efficient: just above baseline
        spec_low = ProposedBuildingSpec(
            name="Moderate",
            building_type="office",
            floor_area_m2=5000.0,
            num_floors=3,
            climate_zone=4,
            heating_fuel="gas",
            window_to_wall_ratio=0.40,
            u_wall=0.40,       # slightly below baseline
            u_roof=0.18,
            u_window=3.0,
            shgc=0.35,
            internal_load_w_m2=20.0,
            hvac_heating_cop=0.82,
            hvac_cooling_cop=3.5,
            climate_mean_c=8.0,
            climate_amplitude_c=12.0,
        )
        # Highly efficient: large improvements
        spec_high = _efficient_spec()
        r_low = compute_appendixg_report(spec_low)
        r_high = compute_appendixg_report(spec_high)
        assert r_high.leed_eac2_points >= r_low.leed_eac2_points, (
            f"High-efficiency building ({r_high.leed_eac2_points} pts) should "
            f"not earn fewer LEED points than moderate ({r_low.leed_eac2_points} pts)"
        )


# ---------------------------------------------------------------------------
# Oracle 4 — Title 24 pass when proposed TDV < baseline TDV
# ---------------------------------------------------------------------------

class TestTitle24Compliance:

    def test_efficient_building_passes_title24(self):
        """An efficient building in CZ6 (LA) should pass Title 24."""
        efficient_eu = EndUseBreakdown(
            heating_kwh=1000.0,    # low heating
            cooling_kwh=5000.0,
            fan_kwh=2000.0,
            lighting_kwh=3000.0,
            total_kwh=11000.0,
            eui_kwh_m2_yr=44.0,
        )
        compliant, margin = _check_title24(efficient_eu, 250.0, 6, "gas")
        assert compliant is True, (
            f"Expected Title 24 PASS for efficient building; margin={margin:.1f}%"
        )
        assert margin > 0.0

    def test_inefficient_building_fails_title24(self):
        """A very inefficient building should fail Title 24."""
        inefficient_eu = EndUseBreakdown(
            heating_kwh=50000.0,
            cooling_kwh=80000.0,
            fan_kwh=20000.0,
            lighting_kwh=30000.0,
            total_kwh=180000.0,
            eui_kwh_m2_yr=360.0,
        )
        compliant, margin = _check_title24(inefficient_eu, 500.0, 6, "gas")
        assert compliant is False, "Expected Title 24 FAIL for inefficient building"
        assert margin < 0.0

    def test_title24_margin_positive_when_compliant(self):
        """Margin must be positive when compliant."""
        eu = EndUseBreakdown(
            heating_kwh=500.0, cooling_kwh=2000.0, fan_kwh=800.0,
            lighting_kwh=1200.0, total_kwh=4500.0, eui_kwh_m2_yr=36.0,
        )
        compliant, margin = _check_title24(eu, 125.0, 3, "gas")
        if compliant:
            assert margin > 0.0
        else:
            assert margin <= 0.0

    def test_report_includes_title24_when_ca_cz_specified(self):
        """compute_appendixg_report returns Title 24 result when CA CZ given."""
        spec = _efficient_spec(california_climate_zone=6)
        report = compute_appendixg_report(spec)
        assert report.title24_compliant is not None
        assert report.title24_margin_pct is not None

    def test_report_skips_title24_when_no_ca_cz(self):
        """compute_appendixg_report returns None Title 24 when CA CZ not given."""
        spec = _efficient_spec(california_climate_zone=None)
        report = compute_appendixg_report(spec)
        assert report.title24_compliant is None
        assert report.title24_margin_pct is None


# ---------------------------------------------------------------------------
# Oracle 5 — Tool round-trip via JSON (energy_ashrae901_appendixg_report)
# ---------------------------------------------------------------------------

class TestAppendixGTool:

    def test_tool_returns_valid_json(self):
        """Tool must return valid JSON string."""
        args = json.dumps({
            "building_type": "office",
            "floor_area_m2": 5000.0,
            "num_floors": 3,
            "climate_zone": 4,
            "heating_fuel": "gas",
            "window_to_wall_ratio": 0.35,
            "u_wall": 0.20,
            "u_roof": 0.10,
            "u_window": 1.50,
            "shgc": 0.25,
            "internal_load_w_m2": 20.0,
            "hvac_heating_cop": 0.95,
            "hvac_cooling_cop": 5.5,
            "climate_mean_c": 8.0,
            "climate_amplitude_c": 12.0,
        }).encode()
        result = _run(run_energy_ashrae901_appendixg_report(_Ctx(), args))
        data = json.loads(result)
        assert isinstance(data, dict)

    def test_tool_efficient_building_pci_less_than_1(self):
        """Tool returns PCI < 1.0 for efficient building."""
        args = json.dumps({
            "building_type": "office",
            "floor_area_m2": 5000.0,
            "num_floors": 3,
            "climate_zone": 4,
            "u_wall": 0.20,
            "u_roof": 0.10,
            "u_window": 1.50,
            "shgc": 0.25,
            "hvac_heating_cop": 0.95,
            "hvac_cooling_cop": 5.5,
        }).encode()
        result = _run(run_energy_ashrae901_appendixg_report(_Ctx(), args))
        data = json.loads(result)
        assert data.get("performance_cost_index", 1.0) < 1.0, (
            f"Expected PCI < 1.0; got {data.get('performance_cost_index')}"
        )

    def test_tool_missing_required_field_returns_error(self):
        """Missing required field must return error payload."""
        args = json.dumps({
            "building_type": "office",
            "floor_area_m2": 5000.0,
            # missing: num_floors, climate_zone, u_wall, u_roof, u_window, shgc, COPs
        }).encode()
        result = _run(run_energy_ashrae901_appendixg_report(_Ctx(), args))
        data = json.loads(result)
        # Should be an error response (either {"error": ...} or {"ok": false})
        has_error = "error" in data or data.get("ok") is False
        assert has_error, f"Expected error response; got {data}"

    def test_tool_invalid_climate_zone_returns_error(self):
        """Climate zone 0 must return error."""
        args = json.dumps({
            "building_type": "office",
            "floor_area_m2": 5000.0,
            "num_floors": 3,
            "climate_zone": 0,   # invalid
            "u_wall": 0.20, "u_roof": 0.10, "u_window": 1.50, "shgc": 0.25,
            "hvac_heating_cop": 0.95, "hvac_cooling_cop": 5.5,
        }).encode()
        result = _run(run_energy_ashrae901_appendixg_report(_Ctx(), args))
        data = json.loads(result)
        has_error = "error" in data or data.get("ok") is False
        assert has_error, f"Expected error for invalid CZ; got {data}"

    def test_tool_report_includes_baseline_system(self):
        """Tool result must include baseline_system_number and baseline_system_name."""
        args = json.dumps({
            "building_type": "office",
            "floor_area_m2": 5000.0,
            "num_floors": 3,
            "climate_zone": 4,
            "u_wall": 0.20, "u_roof": 0.10, "u_window": 1.50, "shgc": 0.25,
            "hvac_heating_cop": 0.95, "hvac_cooling_cop": 5.5,
        }).encode()
        result = _run(run_energy_ashrae901_appendixg_report(_Ctx(), args))
        data = json.loads(result)
        assert "baseline_system_number" in data
        assert "baseline_system_name" in data
        assert 1 <= data["baseline_system_number"] <= 8

    def test_tool_result_includes_end_use_breakdowns(self):
        """Tool must return baseline_end_use and proposed_end_use dicts."""
        args = json.dumps({
            "building_type": "office",
            "floor_area_m2": 5000.0,
            "num_floors": 3,
            "climate_zone": 4,
            "u_wall": 0.20, "u_roof": 0.10, "u_window": 1.50, "shgc": 0.25,
            "hvac_heating_cop": 0.95, "hvac_cooling_cop": 5.5,
        }).encode()
        result = _run(run_energy_ashrae901_appendixg_report(_Ctx(), args))
        data = json.loads(result)
        for key in ("baseline_end_use", "proposed_end_use"):
            assert key in data, f"Missing {key} in result"
            eu = data[key]
            assert "heating_kwh" in eu
            assert "cooling_kwh" in eu
            assert "total_kwh" in eu


# ---------------------------------------------------------------------------
# Oracle 6 — energy_leed_eap2_points tool
# ---------------------------------------------------------------------------

class TestLeedEap2PointsTool:

    def test_tool_15pct_improvement_meets_prereq(self):
        """15% improvement → EAp2 prerequisite met."""
        args = json.dumps({"pct_better_than_baseline": 15.0}).encode()
        result = _run(run_energy_leed_eap2_points(_Ctx(), args))
        data = json.loads(result)
        assert data.get("prerequisite_met") is True

    def test_tool_3pct_fails_prereq_for_new_construction(self):
        """3% improvement < 5% → EAp2 not met for new construction."""
        args = json.dumps({
            "pct_better_than_baseline": 3.0,
            "project_type": "new_construction",
        }).encode()
        result = _run(run_energy_leed_eap2_points(_Ctx(), args))
        data = json.loads(result)
        assert data.get("prerequisite_met") is False
        assert data.get("eac2_points_earned") == 0

    def test_tool_higher_pct_earns_more_points(self):
        """30% improvement earns more points than 10% improvement."""
        args_10 = json.dumps({"pct_better_than_baseline": 10.0}).encode()
        args_30 = json.dumps({"pct_better_than_baseline": 30.0}).encode()
        r10 = json.loads(_run(run_energy_leed_eap2_points(_Ctx(), args_10)))
        r30 = json.loads(_run(run_energy_leed_eap2_points(_Ctx(), args_30)))
        assert r30.get("eac2_points_earned", 0) > r10.get("eac2_points_earned", 0), (
            f"30% improvement should earn more than 10%; "
            f"got {r30.get('eac2_points_earned')} vs {r10.get('eac2_points_earned')}"
        )

    def test_tool_renewables_offset_improves_points(self):
        """Adding renewable offset increases effective savings → more points."""
        # 7% raw savings: normally 1 EAc2 point
        args_no_rv = json.dumps({"pct_better_than_baseline": 7.0}).encode()
        # 7% + 5% renewables offset = 12% effective → should earn 4 points
        args_with_rv = json.dumps({
            "pct_better_than_baseline": 7.0,
            "renewables_offset_pct": 5.0,
        }).encode()
        r_no = json.loads(_run(run_energy_leed_eap2_points(_Ctx(), args_no_rv)))
        r_rv = json.loads(_run(run_energy_leed_eap2_points(_Ctx(), args_with_rv)))
        assert r_rv.get("eac2_points_earned", 0) >= r_no.get("eac2_points_earned", 0)

    def test_tool_missing_pct_better_returns_error(self):
        """Missing pct_better_than_baseline → error."""
        args = json.dumps({"project_type": "new_construction"}).encode()
        result = _run(run_energy_leed_eap2_points(_Ctx(), args))
        data = json.loads(result)
        has_error = "error" in data or data.get("ok") is False
        assert has_error

    def test_tool_point_detail_non_empty(self):
        """point_detail list must be non-empty."""
        args = json.dumps({"pct_better_than_baseline": 20.0}).encode()
        result = _run(run_energy_leed_eap2_points(_Ctx(), args))
        data = json.loads(result)
        assert len(data.get("point_detail", [])) >= 1


# ---------------------------------------------------------------------------
# Oracle 7 — energy_title24_compliance tool
# ---------------------------------------------------------------------------

class TestTitle24Tool:

    def test_tool_efficient_building_passes(self):
        """An efficient CZ6 office building should pass Title 24."""
        args = json.dumps({
            "california_climate_zone": 6,
            "building_type": "office",
            "floor_area_m2": 500.0,
            "annual_heating_kwh": 500.0,
            "annual_cooling_kwh": 3000.0,
            "annual_fan_kwh": 1000.0,
            "annual_lighting_kwh": 2000.0,
            "heating_fuel": "gas",
        }).encode()
        result = _run(run_energy_title24_compliance(_Ctx(), args))
        data = json.loads(result)
        assert data.get("compliant") is True, (
            f"Expected Title 24 PASS; got {data}"
        )
        assert data.get("pass_fail_badge") == "PASS"
        assert data.get("margin_pct", -1.0) > 0.0

    def test_tool_very_inefficient_building_fails(self):
        """A very inefficient building must fail Title 24."""
        args = json.dumps({
            "california_climate_zone": 6,
            "building_type": "office",
            "floor_area_m2": 100.0,    # small area → high TDV per m²
            "annual_heating_kwh": 100000.0,
            "annual_cooling_kwh": 100000.0,
            "annual_fan_kwh": 50000.0,
            "annual_lighting_kwh": 50000.0,
        }).encode()
        result = _run(run_energy_title24_compliance(_Ctx(), args))
        data = json.loads(result)
        assert data.get("compliant") is False
        assert data.get("pass_fail_badge") == "FAIL"

    def test_tool_includes_tdv_breakdown(self):
        """Tool result must include TDV breakdown by end-use."""
        args = json.dumps({
            "california_climate_zone": 3,
            "building_type": "office",
            "floor_area_m2": 500.0,
            "annual_heating_kwh": 2000.0,
            "annual_cooling_kwh": 5000.0,
        }).encode()
        result = _run(run_energy_title24_compliance(_Ctx(), args))
        data = json.loads(result)
        breakdown = data.get("tdv_breakdown", {})
        for key in ("heating_kbtu_m2_yr", "cooling_kbtu_m2_yr", "total_kbtu_m2_yr"):
            assert key in breakdown, f"Missing {key} in TDV breakdown"

    def test_tool_invalid_ca_cz_returns_error(self):
        """CEC CZ out of range (0 or 17) must return error."""
        for bad_cz in (0, 17):
            args = json.dumps({
                "california_climate_zone": bad_cz,
                "building_type": "office",
                "floor_area_m2": 500.0,
                "annual_heating_kwh": 2000.0,
                "annual_cooling_kwh": 5000.0,
            }).encode()
            result = _run(run_energy_title24_compliance(_Ctx(), args))
            data = json.loads(result)
            has_error = "error" in data or data.get("ok") is False
            assert has_error, f"Expected error for CZ={bad_cz}; got {data}"

    def test_tool_invalid_building_type_returns_error(self):
        """Unknown building type must return error."""
        args = json.dumps({
            "california_climate_zone": 6,
            "building_type": "casino",  # not in allowed list
            "floor_area_m2": 500.0,
            "annual_heating_kwh": 2000.0,
            "annual_cooling_kwh": 5000.0,
        }).encode()
        result = _run(run_energy_title24_compliance(_Ctx(), args))
        data = json.loads(result)
        has_error = "error" in data or data.get("ok") is False
        assert has_error

    def test_tool_margin_positive_iff_compliant(self):
        """Margin pct is positive if compliant, non-positive otherwise."""
        args_eff = json.dumps({
            "california_climate_zone": 6,
            "building_type": "office",
            "floor_area_m2": 500.0,
            "annual_heating_kwh": 500.0,
            "annual_cooling_kwh": 3000.0,
            "annual_fan_kwh": 800.0,
            "annual_lighting_kwh": 1500.0,
        }).encode()
        data = json.loads(_run(run_energy_title24_compliance(_Ctx(), args_eff)))
        if data.get("compliant"):
            assert data.get("margin_pct", -1) > 0
        else:
            assert data.get("margin_pct", 1) <= 0


# ---------------------------------------------------------------------------
# Additional integration: weather synthesis
# ---------------------------------------------------------------------------

class TestWeatherSynthesis:

    def test_synthesise_weather_returns_8760(self):
        """_synthesise_weather returns exactly 8760 tuples."""
        w = _synthesise_weather(13.0, 10.0)
        assert len(w) == 8760

    def test_synthesise_weather_tuple_structure(self):
        """Each weather tuple has (dry_bulb_c, dni, dhi, rh) format."""
        w = _synthesise_weather()
        t_out, dni, dhi, rh = w[100]
        assert isinstance(t_out, float)
        assert dni >= 0.0
        assert dhi >= 0.0
        assert 0.0 <= rh <= 100.0

    def test_simulate_building_v2_returns_enduse(self):
        """_simulate_building_v2 returns an EndUseBreakdown."""
        weather = _synthesise_weather(13.0, 10.0)
        eu = _simulate_building_v2(
            floor_area_m2=1000.0,
            wwr=0.35,
            u_wall=0.30,
            u_roof=0.15,
            u_window=2.0,
            shgc=0.30,
            internal_load_w_m2=20.0,
            heating_cop=0.90,
            cooling_cop=4.0,
            ceiling_height_m=3.5,
            weather=weather,
        )
        assert isinstance(eu, EndUseBreakdown)
        assert eu.total_kwh > 0.0
        assert eu.eui_kwh_m2_yr > 0.0
