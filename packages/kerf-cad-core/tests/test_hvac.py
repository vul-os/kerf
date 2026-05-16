"""
Hermetic tests for kerf_cad_core.hvac — HVAC duct sizing calculations.

Coverage:
  ducts.cfm_from_sensible_load     — ASHRAE 1.08·CFM·ΔT formula
  ducts.round_duct_diameter        — area and diameter from CFM + velocity
  ducts.rect_equiv_diameter        — Huebscher equivalent diameter
  ducts.duct_friction_loss         — Darcy-Weisbach friction loss
  ducts.duct_fitting_loss          — dynamic loss coefficient
  ducts.size_duct_equal_friction   — equal-friction duct sizing
  ducts.size_duct_velocity_reduction — velocity-reduction method
  ducts.branch_static_pressure     — total static pressure for a branch
  ducts.fan_law_scale              — fan-law affinity scaling
  tools.*                          — LLM tool wrappers (happy path + error paths)

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas are verified algebraically against ASHRAE hand-calc references.

References
----------
ASHRAE Handbook — Fundamentals (2021), Chapter 21: Duct Design
Huebscher (1948) ASHVE Trans. 54

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.hvac.ducts import (
    cfm_from_sensible_load,
    round_duct_diameter,
    rect_equiv_diameter,
    duct_friction_loss,
    duct_fitting_loss,
    size_duct_equal_friction,
    size_duct_velocity_reduction,
    branch_static_pressure,
    fan_law_scale,
)
from kerf_cad_core.hvac.tools import (
    run_cfm_from_sensible_load,
    run_round_duct_diameter,
    run_rect_equiv_diameter,
    run_duct_friction_loss,
    run_duct_fitting_loss,
    run_size_equal_friction,
    run_size_velocity_reduction,
    run_branch_static_pressure,
    run_fan_law_scale,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok_tool(raw: str) -> dict:
    d = json.loads(raw)
    assert d.get("ok") is True, f"Expected ok=True, got: {d}"
    return d


def _err_tool(raw: str) -> dict:
    d = json.loads(raw)
    is_ok_false = d.get("ok") is False
    is_err_payload = "error" in d and "code" in d
    assert is_ok_false or is_err_payload, f"Expected error response, got: {d}"
    return d


REL = 1e-4   # relative tolerance for floating-point HVAC checks


# ===========================================================================
# 1. cfm_from_sensible_load
# ===========================================================================

class TestCfmFromSensibleLoad:

    def test_ashrae_formula_20F_differential(self):
        """CFM = Q / (1.08 × ΔT): 24 000 BTU/h at 20 °F → 1111 CFM."""
        res = cfm_from_sensible_load(24_000.0, 20.0)
        assert res["ok"] is True
        expected = 24_000.0 / (1.08 * 20.0)
        assert abs(res["cfm"] - expected) / expected < REL

    def test_heating_load_example(self):
        """Heating: 50 000 BTU/h, ΔT=50 °F → CFM = 50000/(1.08×50) ≈ 925.9."""
        res = cfm_from_sensible_load(50_000.0, 50.0)
        assert res["ok"] is True
        expected = 50_000.0 / (1.08 * 50.0)
        assert abs(res["cfm"] - expected) / expected < REL

    def test_doubling_load_doubles_cfm(self):
        """Doubling the BTU/h load must double CFM at same ΔT."""
        r1 = cfm_from_sensible_load(10_000.0, 20.0)
        r2 = cfm_from_sensible_load(20_000.0, 20.0)
        assert abs(r2["cfm"] / r1["cfm"] - 2.0) < REL

    def test_doubling_delta_T_halves_cfm(self):
        """Doubling ΔT must halve CFM at same load."""
        r1 = cfm_from_sensible_load(10_000.0, 15.0)
        r2 = cfm_from_sensible_load(10_000.0, 30.0)
        assert abs(r2["cfm"] / r1["cfm"] - 0.5) < 1e-9

    def test_factor_is_108(self):
        """Sensible heat factor returned must be 1.08."""
        res = cfm_from_sensible_load(12_000.0, 20.0)
        assert res["factor"] == pytest.approx(1.08)

    def test_warns_on_small_delta_T(self):
        """delta_T_F < 10 °F should produce a warning."""
        res = cfm_from_sensible_load(10_000.0, 5.0)
        assert res["ok"] is True
        assert len(res["warnings"]) > 0

    def test_zero_load_returns_error(self):
        res = cfm_from_sensible_load(0.0, 20.0)
        assert res["ok"] is False

    def test_negative_delta_T_returns_error(self):
        res = cfm_from_sensible_load(10_000.0, -20.0)
        assert res["ok"] is False


# ===========================================================================
# 2. round_duct_diameter
# ===========================================================================

class TestRoundDuctDiameter:

    def test_area_and_diameter_algebraic(self):
        """Area = CFM/V (ft²), D = 2·√(Area/π) converted to inches."""
        cfm, vel = 1000.0, 600.0
        res = round_duct_diameter(cfm, vel)
        assert res["ok"] is True
        area_expected = cfm / vel
        d_ft = 2.0 * math.sqrt(area_expected / math.pi)
        d_in_expected = d_ft * 12.0
        assert abs(res["diameter_in"] - d_in_expected) / d_in_expected < REL
        assert abs(res["area_ft2"] - area_expected) / area_expected < REL

    def test_higher_velocity_gives_smaller_duct(self):
        """Increasing velocity should produce a smaller diameter at same CFM."""
        r1 = round_duct_diameter(500.0, 500.0)
        r2 = round_duct_diameter(500.0, 1000.0)
        assert r2["diameter_in"] < r1["diameter_in"]

    def test_higher_cfm_gives_larger_duct(self):
        """Increasing CFM should produce a larger diameter at same velocity."""
        r1 = round_duct_diameter(500.0, 600.0)
        r2 = round_duct_diameter(1000.0, 600.0)
        assert r2["diameter_in"] > r1["diameter_in"]

    def test_area_scales_with_cfm(self):
        """Area = CFM/V, so doubling CFM at same V doubles area."""
        r1 = round_duct_diameter(400.0, 600.0)
        r2 = round_duct_diameter(800.0, 600.0)
        assert abs(r2["area_ft2"] / r1["area_ft2"] - 2.0) < REL

    def test_over_velocity_warning(self):
        """Velocity > 1500 fpm should produce a warning."""
        res = round_duct_diameter(2000.0, 2000.0)
        assert res["ok"] is True
        assert len(res["warnings"]) > 0

    def test_zero_cfm_returns_error(self):
        res = round_duct_diameter(0.0, 600.0)
        assert res["ok"] is False

    def test_negative_velocity_returns_error(self):
        res = round_duct_diameter(500.0, -600.0)
        assert res["ok"] is False


# ===========================================================================
# 3. rect_equiv_diameter  (Huebscher)
# ===========================================================================

class TestRectEquivDiameter:

    def test_square_duct_algebraic(self):
        """Square duct (a=b): D_e = 1.30 × a^0.625 / (2a)^0.25 × a^0.625."""
        a = b = 12.0  # 12×12 in.
        res = rect_equiv_diameter(a, b)
        assert res["ok"] is True
        expected = 1.30 * (a * b) ** 0.625 / (a + b) ** 0.25
        assert abs(res["equiv_diameter_in"] - expected) / expected < REL

    def test_16x10_duct_known_value(self):
        """16×10 in. rect duct: D_e = 1.30 × (160)^0.625 / (26)^0.25 ≈ 13.0 in."""
        res = rect_equiv_diameter(16.0, 10.0)
        assert res["ok"] is True
        expected = 1.30 * (16.0 * 10.0) ** 0.625 / (16.0 + 10.0) ** 0.25
        assert abs(res["equiv_diameter_in"] - expected) / expected < REL

    def test_symmetry(self):
        """rect_equiv_diameter(a, b) == rect_equiv_diameter(b, a) (commutative)."""
        r1 = rect_equiv_diameter(20.0, 12.0)
        r2 = rect_equiv_diameter(12.0, 20.0)
        assert abs(r1["equiv_diameter_in"] - r2["equiv_diameter_in"]) < 1e-9

    def test_aspect_ratio_computed_correctly(self):
        """Aspect ratio must be max/min."""
        res = rect_equiv_diameter(24.0, 8.0)
        assert res["aspect_ratio"] == pytest.approx(3.0, rel=1e-6)

    def test_high_aspect_ratio_warns(self):
        """Aspect ratio > 4:1 should produce a warning."""
        res = rect_equiv_diameter(30.0, 6.0)  # 5:1
        assert res["ok"] is True
        assert len(res["warnings"]) > 0

    def test_zero_width_returns_error(self):
        res = rect_equiv_diameter(0.0, 12.0)
        assert res["ok"] is False

    def test_negative_height_returns_error(self):
        res = rect_equiv_diameter(12.0, -6.0)
        assert res["ok"] is False


# ===========================================================================
# 4. duct_friction_loss
# ===========================================================================

class TestDuctFrictionLoss:

    def test_friction_rate_per_100ft_consistent(self):
        """friction_loss_in_wg == friction_rate_in_per_100ft × length_ft / 100."""
        res = duct_friction_loss(cfm=1000.0, diameter_in=12.0, length_ft=100.0)
        assert res["ok"] is True
        expected = res["friction_rate_in_per_100ft"] * 100.0 / 100.0
        assert abs(res["friction_loss_in_wg"] - expected) / max(expected, 1e-9) < REL

    def test_friction_scales_with_length(self):
        """Doubling duct length doubles friction loss."""
        r1 = duct_friction_loss(800.0, 10.0, 50.0)
        r2 = duct_friction_loss(800.0, 10.0, 100.0)
        assert abs(r2["friction_loss_in_wg"] / r1["friction_loss_in_wg"] - 2.0) < REL

    def test_larger_diameter_lower_loss(self):
        """Larger diameter duct has lower friction loss at same CFM and length."""
        r_small = duct_friction_loss(500.0, 8.0, 100.0)
        r_large = duct_friction_loss(500.0, 12.0, 100.0)
        assert r_large["friction_loss_in_wg"] < r_small["friction_loss_in_wg"]

    def test_velocity_computed_from_area(self):
        """Velocity (fpm) must match CFM / area."""
        cfm, d_in = 600.0, 10.0
        res = duct_friction_loss(cfm, d_in, 80.0)
        assert res["ok"] is True
        area_ft2 = math.pi * (d_in / 12.0) ** 2 / 4.0
        v_expected = cfm / area_ft2
        assert abs(res["velocity_fpm"] - v_expected) / v_expected < REL

    def test_loss_pa_conversion(self):
        """friction_loss_Pa == friction_loss_in_wg × 249.089.

        Use a larger duct loss so that the independently-rounded in.w.g.
        (5 dp) and Pa (3 dp) outputs do not amplify quantisation error in
        the ratio beyond the standard ASHRAE constant.
        """
        res = duct_friction_loss(2000.0, 12.0, 200.0)
        assert res["ok"] is True
        assert abs(res["friction_loss_Pa"] / res["friction_loss_in_wg"] - 249.089) < 0.05

    def test_over_velocity_warning(self):
        """High CFM through small duct should warn about over-velocity."""
        res = duct_friction_loss(5000.0, 8.0, 100.0)
        assert res["ok"] is True
        assert len(res["warnings"]) > 0

    def test_negative_roughness_returns_error(self):
        res = duct_friction_loss(800.0, 12.0, 100.0, roughness_ft=-0.001)
        assert res["ok"] is False

    def test_zero_length_returns_error(self):
        res = duct_friction_loss(800.0, 12.0, 0.0)
        assert res["ok"] is False


# ===========================================================================
# 5. duct_fitting_loss
# ===========================================================================

class TestDuctFittingLoss:

    def test_velocity_pressure_formula(self):
        """V_p = (V/4005)²; ΔP = C × V_p."""
        cfm, d_in, C = 800.0, 10.0, 0.3
        area_ft2 = math.pi * (d_in / 12.0) ** 2 / 4.0
        v_fpm = cfm / area_ft2
        V_p_expected = (v_fpm / 4005.0) ** 2
        dP_expected = C * V_p_expected
        res = duct_fitting_loss(cfm, d_in, C)
        assert res["ok"] is True
        assert abs(res["fitting_loss_in_wg"] - dP_expected) / dP_expected < REL
        assert abs(res["velocity_pressure_in_wg"] - V_p_expected) / V_p_expected < REL

    def test_zero_C_gives_zero_loss(self):
        """C=0 fitting (straight through) must give zero dynamic loss."""
        res = duct_fitting_loss(500.0, 10.0, 0.0)
        assert res["ok"] is True
        assert res["fitting_loss_in_wg"] == 0.0

    def test_loss_scales_with_C(self):
        """Doubling C must double ΔP."""
        r1 = duct_fitting_loss(600.0, 10.0, 0.25)
        r2 = duct_fitting_loss(600.0, 10.0, 0.50)
        assert abs(r2["fitting_loss_in_wg"] / r1["fitting_loss_in_wg"] - 2.0) < 1e-9

    def test_pa_conversion(self):
        """Pa == in.wg × 249.089."""
        res = duct_fitting_loss(800.0, 12.0, 0.5)
        assert abs(res["fitting_loss_Pa"] / res["fitting_loss_in_wg"] - 249.089) < 0.01

    def test_velocity_fpm_consistent_with_cfm(self):
        """velocity_fpm must match CFM/area."""
        cfm, d_in = 400.0, 8.0
        res = duct_fitting_loss(cfm, d_in, 0.2)
        area = math.pi * (d_in / 12.0) ** 2 / 4.0
        v_expected = cfm / area
        assert abs(res["velocity_fpm"] - v_expected) / v_expected < REL

    def test_negative_C_returns_error(self):
        res = duct_fitting_loss(500.0, 10.0, -0.1)
        assert res["ok"] is False

    def test_zero_diameter_returns_error(self):
        res = duct_fitting_loss(500.0, 0.0, 0.3)
        assert res["ok"] is False


# ===========================================================================
# 6. size_duct_equal_friction
# ===========================================================================

class TestSizeDuctEqualFriction:

    def test_round_trip_friction_rate(self):
        """Sized diameter should produce friction rate close to target."""
        target = 0.10   # in. w.g./100 ft
        res = size_duct_equal_friction(1000.0, target)
        assert res["ok"] is True
        # Verify by computing friction loss at sized diameter
        fl = duct_friction_loss(1000.0, res["diameter_in"], 100.0)
        assert abs(fl["friction_rate_in_per_100ft"] - target) / target < 0.02

    def test_higher_cfm_requires_larger_duct(self):
        """Higher CFM at same friction rate must require larger diameter."""
        r1 = size_duct_equal_friction(500.0, 0.10)
        r2 = size_duct_equal_friction(2000.0, 0.10)
        assert r2["diameter_in"] > r1["diameter_in"]

    def test_lower_friction_rate_larger_duct(self):
        """Lower friction rate (more conservative) requires larger duct."""
        r_low = size_duct_equal_friction(800.0, 0.05)
        r_high = size_duct_equal_friction(800.0, 0.15)
        assert r_low["diameter_in"] > r_high["diameter_in"]

    def test_resulting_velocity_is_positive(self):
        """Sized duct must give positive velocity."""
        res = size_duct_equal_friction(600.0, 0.08)
        assert res["ok"] is True
        assert res["velocity_fpm"] > 0

    def test_zero_cfm_returns_error(self):
        res = size_duct_equal_friction(0.0, 0.10)
        assert res["ok"] is False

    def test_negative_friction_rate_returns_error(self):
        res = size_duct_equal_friction(500.0, -0.10)
        assert res["ok"] is False


# ===========================================================================
# 7. size_duct_velocity_reduction
# ===========================================================================

class TestSizeDuctVelocityReduction:

    def test_returns_correct_section_count(self):
        """Number of returned sections must match input length."""
        cfms = [2000.0, 1500.0, 800.0, 400.0]
        vels = [1200.0, 900.0, 700.0, 500.0]
        res = size_duct_velocity_reduction(cfms, vels)
        assert res["ok"] is True
        assert len(res["sections"]) == 4

    def test_diameters_consistent_with_round_duct(self):
        """Each section diameter must match round_duct_diameter independently."""
        cfms = [1000.0, 500.0]
        vels = [800.0, 600.0]
        res = size_duct_velocity_reduction(cfms, vels)
        assert res["ok"] is True
        for sec, cfm, vel in zip(res["sections"], cfms, vels):
            ref = round_duct_diameter(cfm, vel)
            assert abs(sec["diameter_in"] - ref["diameter_in"]) < 1e-6

    def test_decreasing_velocity_decreasing_size(self):
        """Decreasing velocity schedule with same CFM gives increasing diameters."""
        cfms = [1000.0, 1000.0, 1000.0]
        vels = [1200.0, 800.0, 500.0]
        res = size_duct_velocity_reduction(cfms, vels)
        assert res["ok"] is True
        diams = [s["diameter_in"] for s in res["sections"]]
        assert diams[0] < diams[1] < diams[2]

    def test_mismatched_list_lengths_returns_error(self):
        res = size_duct_velocity_reduction([1000.0, 500.0], [800.0])
        assert res["ok"] is False

    def test_empty_list_returns_error(self):
        res = size_duct_velocity_reduction([], [])
        assert res["ok"] is False

    def test_single_section(self):
        """Single-section list must succeed and return one section."""
        res = size_duct_velocity_reduction([400.0], [600.0])
        assert res["ok"] is True
        assert len(res["sections"]) == 1


# ===========================================================================
# 8. branch_static_pressure
# ===========================================================================

class TestBranchStaticPressure:

    def _simple_section(self, cfm=800.0, diameter_in=12.0, length_ft=100.0, fittings=None):
        sec = {"cfm": cfm, "diameter_in": diameter_in, "length_ft": length_ft}
        if fittings is not None:
            sec["fittings"] = fittings
        return sec

    def test_single_straight_section_matches_friction_loss(self):
        """Single straight section without fittings matches duct_friction_loss."""
        sec = self._simple_section(cfm=800.0, diameter_in=12.0, length_ft=150.0)
        res = branch_static_pressure([sec])
        assert res["ok"] is True
        ref = duct_friction_loss(800.0, 12.0, 150.0)
        assert abs(res["total_static_pressure_in_wg"] - ref["friction_loss_in_wg"]) < REL

    def test_two_sections_sum_correctly(self):
        """Total SP must equal sum of individual section totals."""
        s1 = self._simple_section(800.0, 12.0, 100.0)
        s2 = self._simple_section(400.0, 8.0, 80.0)
        res = branch_static_pressure([s1, s2])
        assert res["ok"] is True
        manual = (
            duct_friction_loss(800.0, 12.0, 100.0)["friction_loss_in_wg"]
            + duct_friction_loss(400.0, 8.0, 80.0)["friction_loss_in_wg"]
        )
        assert abs(res["total_static_pressure_in_wg"] - manual) < REL

    def test_fitting_adds_to_section_total(self):
        """Adding a fitting must increase the section total over straight loss alone."""
        sec_no_fit = self._simple_section(600.0, 10.0, 50.0)
        sec_with_fit = self._simple_section(600.0, 10.0, 50.0, fittings=[{"C": 0.25}])
        r_no = branch_static_pressure([sec_no_fit])
        r_with = branch_static_pressure([sec_with_fit])
        assert r_with["total_static_pressure_in_wg"] > r_no["total_static_pressure_in_wg"]

    def test_fitting_loss_consistent_with_fitting_tool(self):
        """Fitting loss in branch must equal duct_fitting_loss output."""
        cfm, d_in, C = 700.0, 10.0, 0.4
        sec = self._simple_section(cfm, d_in, 100.0, fittings=[{"C": C}])
        res = branch_static_pressure([sec])
        assert res["ok"] is True
        fit_ref = duct_fitting_loss(cfm, d_in, C)
        assert abs(
            res["sections"][0]["fitting_loss_in_wg"] - fit_ref["fitting_loss_in_wg"]
        ) < REL

    def test_pa_conversion(self):
        """total_static_pressure_Pa == total_static_pressure_in_wg × 249.089.

        A larger branch loss keeps the ratio of the independently-rounded
        in.w.g. (4 dp) and Pa (2 dp) totals within the ASHRAE constant.
        """
        sec = self._simple_section(cfm=2000.0, diameter_in=12.0, length_ft=300.0)
        res = branch_static_pressure([sec])
        assert abs(
            res["total_static_pressure_Pa"] / res["total_static_pressure_in_wg"] - 249.089
        ) < 0.05

    def test_missing_cfm_returns_error(self):
        res = branch_static_pressure([{"diameter_in": 12.0, "length_ft": 50.0}])
        assert res["ok"] is False

    def test_empty_sections_returns_error(self):
        res = branch_static_pressure([])
        assert res["ok"] is False


# ===========================================================================
# 9. fan_law_scale
# ===========================================================================

class TestFanLawScale:

    def test_sp_scales_as_square_of_cfm_ratio(self):
        """SP₂ = SP₁ × (CFM₂/CFM₁)²."""
        cfm1, sp1, bhp1, cfm2 = 1000.0, 1.5, 2.0, 1200.0
        res = fan_law_scale(cfm1, sp1, bhp1, cfm2)
        assert res["ok"] is True
        r = cfm2 / cfm1
        assert abs(res["sp2_in_wg"] / sp1 - r ** 2) < 1e-9

    def test_bhp_scales_as_cube_of_cfm_ratio(self):
        """BHP₂ = BHP₁ × (CFM₂/CFM₁)³."""
        cfm1, sp1, bhp1, cfm2 = 1000.0, 1.5, 2.0, 1200.0
        res = fan_law_scale(cfm1, sp1, bhp1, cfm2)
        assert res["ok"] is True
        r = cfm2 / cfm1
        assert abs(res["bhp2"] / bhp1 - r ** 3) < 1e-9

    def test_speed_ratio_is_cfm_ratio(self):
        """speed_ratio == CFM₂ / CFM₁."""
        cfm1, sp1, bhp1, cfm2 = 800.0, 1.2, 1.5, 1000.0
        res = fan_law_scale(cfm1, sp1, bhp1, cfm2)
        assert abs(res["speed_ratio"] - cfm2 / cfm1) < 1e-9

    def test_equal_cfm_unchanged(self):
        """CFM₂ == CFM₁ must leave SP and BHP unchanged."""
        res = fan_law_scale(1000.0, 2.0, 3.0, 1000.0)
        assert res["ok"] is True
        assert abs(res["sp2_in_wg"] - 2.0) < 1e-9
        assert abs(res["bhp2"] - 3.0) < 1e-9

    def test_reducing_cfm_reduces_sp_and_bhp(self):
        """Reducing airflow must reduce both SP and BHP."""
        res = fan_law_scale(1000.0, 2.0, 3.0, 700.0)
        assert res["sp2_in_wg"] < 2.0
        assert res["bhp2"] < 3.0

    def test_large_speed_ratio_warns(self):
        """Speed ratio > 1.2 should generate a warning."""
        res = fan_law_scale(1000.0, 2.0, 3.0, 1500.0)  # r = 1.5
        assert res["ok"] is True
        assert len(res["warnings"]) > 0

    def test_very_low_speed_ratio_warns(self):
        """Speed ratio < 0.5 should generate a warning."""
        res = fan_law_scale(1000.0, 2.0, 3.0, 400.0)   # r = 0.4
        assert res["ok"] is True
        assert len(res["warnings"]) > 0

    def test_pa_conversion(self):
        """sp2_Pa == sp2_in_wg × 249.089."""
        res = fan_law_scale(1000.0, 1.5, 2.5, 1100.0)
        assert abs(res["sp2_Pa"] / res["sp2_in_wg"] - 249.089) < 0.01

    def test_negative_cfm1_returns_error(self):
        res = fan_law_scale(-500.0, 1.5, 2.0, 800.0)
        assert res["ok"] is False

    def test_zero_sp1_returns_error(self):
        res = fan_law_scale(1000.0, 0.0, 2.0, 1200.0)
        assert res["ok"] is False


# ===========================================================================
# 9b. CITABLE ASHRAE reference cases
#
# Cross-checked against ASHRAE Handbook — Fundamentals (2021), Chapter 21
# "Duct Design": the Friction Chart (Fig. 10) and the circular-equivalent
# of rectangular ducts table (computed from Eq. 19, the Huebscher 1948
# relation D_e = 1.30·(ab)^0.625/(a+b)^0.25).
#
# The friction-loss reference values below were derived independently from
# the Darcy-Weisbach equation with the gravitational conversion constant
# g_c = 32.174 lbm·ft/(lbf·s²) and the Colebrook-White friction factor for
# galvanised sheet metal (ε = 0.00015 ft), which is exactly how the ASHRAE
# Friction Chart is constructed.  These confirm a defect fix: the prior
# implementation omitted g_c and over-predicted friction loss by ~32×.
# ===========================================================================

class TestASHRAEReferenceCases:

    def test_huebscher_equiv_diameter_table_12x12(self):
        """ASHRAE Ch.21 equivalent-diameter table: 12×12 in → D_e ≈ 13.1 in."""
        res = rect_equiv_diameter(12.0, 12.0)
        assert res["ok"] is True
        assert abs(res["equiv_diameter_in"] - 13.1) < 0.1

    def test_huebscher_equiv_diameter_table_18x6(self):
        """ASHRAE Ch.21 equivalent-diameter table: 18×6 in → D_e ≈ 11.0 in."""
        res = rect_equiv_diameter(18.0, 6.0)
        assert res["ok"] is True
        assert abs(res["equiv_diameter_in"] - 11.0) < 0.1

    def test_huebscher_equiv_diameter_table_24x12(self):
        """ASHRAE Ch.21 equivalent-diameter table: 24×12 in → D_e ≈ 18.3 in."""
        res = rect_equiv_diameter(24.0, 12.0)
        assert res["ok"] is True
        assert abs(res["equiv_diameter_in"] - 18.3) < 0.1

    def test_huebscher_equiv_diameter_table_36x18(self):
        """ASHRAE Ch.21 equivalent-diameter table: 36×18 in → D_e ≈ 27.4 in."""
        res = rect_equiv_diameter(36.0, 18.0)
        assert res["ok"] is True
        assert abs(res["equiv_diameter_in"] - 27.4) < 0.1

    def test_friction_chart_1000cfm_12in(self):
        """ASHRAE Friction Chart: 1000 CFM in a 12 in round duct →
        velocity ≈ 1273 fpm and friction rate ≈ 0.18 in. w.g./100 ft
        (galvanised, ε = 0.00015 ft).  This is the principal defect-fix
        reference: the pre-fix code returned ≈ 5.8 (≈32× too high)."""
        res = duct_friction_loss(1000.0, 12.0, 100.0)
        assert res["ok"] is True
        assert abs(res["velocity_fpm"] - 1273.2) < 1.0
        assert abs(res["friction_rate_in_per_100ft"] - 0.180) < 0.01

    def test_friction_chart_400cfm_10in(self):
        """ASHRAE Friction Chart: 400 CFM in a 10 in duct → V ≈ 733 fpm,
        friction rate ≈ 0.083 in. w.g./100 ft."""
        res = duct_friction_loss(400.0, 10.0, 100.0)
        assert res["ok"] is True
        assert abs(res["velocity_fpm"] - 733.4) < 1.0
        assert abs(res["friction_rate_in_per_100ft"] - 0.083) < 0.01

    def test_friction_chart_2000cfm_14in(self):
        """ASHRAE Friction Chart: 2000 CFM in a 14 in duct → V ≈ 1871 fpm,
        friction rate ≈ 0.30 in. w.g./100 ft."""
        res = duct_friction_loss(2000.0, 14.0, 100.0)
        assert res["ok"] is True
        assert abs(res["velocity_fpm"] - 1870.6) < 1.0
        assert abs(res["friction_rate_in_per_100ft"] - 0.304) < 0.01

    def test_equal_friction_sizing_chart_point(self):
        """ASHRAE equal-friction method: 1000 CFM at the common design rate
        of 0.10 in. w.g./100 ft sizes to ≈ 13.5 in round duct flowing at
        ≈ 1000 fpm — directly readable off the ASHRAE Friction Chart."""
        res = size_duct_equal_friction(1000.0, 0.10)
        assert res["ok"] is True
        assert abs(res["diameter_in"] - 13.5) < 0.2
        assert abs(res["velocity_fpm"] - 1000.0) < 15.0

    def test_velocity_pressure_unit_constant(self):
        """ASHRAE Ch.21 Eq.: V_p = (V/4005)² in. w.g. for standard air;
        at exactly 4005 fpm the velocity pressure is exactly 1.0 in. w.g."""
        # Size CFM so velocity equals 4005 fpm in a 12 in duct.
        area_ft2 = math.pi * (12.0 / 12.0) ** 2 / 4.0
        cfm = 4005.0 * area_ft2
        res = duct_fitting_loss(cfm, 12.0, 1.0)
        assert res["ok"] is True
        assert abs(res["velocity_fpm"] - 4005.0) < 0.5
        assert abs(res["velocity_pressure_in_wg"] - 1.0) < 1e-3

    def test_sensible_factor_ashrae_standard_air(self):
        """ASHRAE standard-air sensible relation Q = 1.08·CFM·ΔT:
        24 000 BTU/h at ΔT = 20 °F → exactly 1111.11 CFM."""
        res = cfm_from_sensible_load(24_000.0, 20.0)
        assert res["ok"] is True
        assert abs(res["cfm"] - 1111.11) < 0.01


# ===========================================================================
# 10. LLM tool wrappers
# ===========================================================================

class TestToolWrappers:

    def test_run_cfm_from_sensible_load_happy(self):
        ctx = _ctx()
        raw = _run(run_cfm_from_sensible_load(ctx, _args(Q_btuh=24000.0, delta_T_F=20.0)))
        d = _ok_tool(raw)
        expected = 24000.0 / (1.08 * 20.0)
        assert abs(d["cfm"] - expected) / expected < REL

    def test_run_cfm_from_sensible_load_missing_Q(self):
        ctx = _ctx()
        raw = _run(run_cfm_from_sensible_load(ctx, _args(delta_T_F=20.0)))
        _err_tool(raw)

    def test_run_round_duct_diameter_happy(self):
        ctx = _ctx()
        raw = _run(run_round_duct_diameter(ctx, _args(cfm=1000.0, velocity_fpm=600.0)))
        d = _ok_tool(raw)
        assert d["diameter_in"] > 0

    def test_run_round_duct_diameter_bad_json(self):
        ctx = _ctx()
        raw = _run(run_round_duct_diameter(ctx, b"not valid json"))
        _err_tool(raw)

    def test_run_rect_equiv_diameter_happy(self):
        ctx = _ctx()
        raw = _run(run_rect_equiv_diameter(ctx, _args(a_in=16.0, b_in=10.0)))
        d = _ok_tool(raw)
        assert d["equiv_diameter_in"] > 0

    def test_run_rect_equiv_diameter_missing_b(self):
        ctx = _ctx()
        raw = _run(run_rect_equiv_diameter(ctx, _args(a_in=16.0)))
        _err_tool(raw)

    def test_run_duct_friction_loss_happy(self):
        ctx = _ctx()
        raw = _run(run_duct_friction_loss(ctx, _args(cfm=1000.0, diameter_in=12.0, length_ft=100.0)))
        d = _ok_tool(raw)
        assert d["friction_loss_in_wg"] > 0

    def test_run_duct_friction_loss_missing_length(self):
        ctx = _ctx()
        raw = _run(run_duct_friction_loss(ctx, _args(cfm=1000.0, diameter_in=12.0)))
        _err_tool(raw)

    def test_run_duct_fitting_loss_happy(self):
        ctx = _ctx()
        raw = _run(run_duct_fitting_loss(ctx, _args(cfm=800.0, diameter_in=10.0, C=0.3)))
        d = _ok_tool(raw)
        assert d["fitting_loss_in_wg"] >= 0

    def test_run_duct_fitting_loss_missing_C(self):
        ctx = _ctx()
        raw = _run(run_duct_fitting_loss(ctx, _args(cfm=800.0, diameter_in=10.0)))
        _err_tool(raw)

    def test_run_size_equal_friction_happy(self):
        ctx = _ctx()
        raw = _run(run_size_equal_friction(ctx, _args(cfm=1000.0, friction_rate_in_per_100ft=0.10)))
        d = _ok_tool(raw)
        assert d["diameter_in"] > 0

    def test_run_size_equal_friction_missing_friction_rate(self):
        ctx = _ctx()
        raw = _run(run_size_equal_friction(ctx, _args(cfm=1000.0)))
        _err_tool(raw)

    def test_run_size_velocity_reduction_happy(self):
        ctx = _ctx()
        raw = _run(run_size_velocity_reduction(ctx, _args(
            cfm_list=[2000.0, 1000.0, 500.0],
            velocity_fpm_list=[1200.0, 800.0, 600.0],
        )))
        d = _ok_tool(raw)
        assert len(d["sections"]) == 3

    def test_run_size_velocity_reduction_missing_list(self):
        ctx = _ctx()
        raw = _run(run_size_velocity_reduction(ctx, _args(cfm_list=[1000.0])))
        _err_tool(raw)

    def test_run_branch_static_pressure_happy(self):
        ctx = _ctx()
        sections = [
            {"cfm": 800.0, "diameter_in": 12.0, "length_ft": 100.0,
             "fittings": [{"C": 0.25}]},
            {"cfm": 400.0, "diameter_in": 8.0, "length_ft": 60.0},
        ]
        raw = _run(run_branch_static_pressure(ctx, _args(sections=sections)))
        d = _ok_tool(raw)
        assert d["total_static_pressure_in_wg"] > 0

    def test_run_branch_static_pressure_missing_sections(self):
        ctx = _ctx()
        raw = _run(run_branch_static_pressure(ctx, _args()))
        _err_tool(raw)

    def test_run_fan_law_scale_happy(self):
        ctx = _ctx()
        raw = _run(run_fan_law_scale(ctx, _args(cfm1=1000.0, sp1=1.5, bhp1=2.0, cfm2=1200.0)))
        d = _ok_tool(raw)
        r = 1200.0 / 1000.0
        assert abs(d["sp2_in_wg"] - 1.5 * r ** 2) < 1e-6

    def test_run_fan_law_scale_missing_bhp1(self):
        ctx = _ctx()
        raw = _run(run_fan_law_scale(ctx, _args(cfm1=1000.0, sp1=1.5, cfm2=1200.0)))
        _err_tool(raw)
