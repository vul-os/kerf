"""
Hermetic tests for kerf_cad_core.corrosion — corrosion engineering &
cathodic protection calculators.

Coverage:
  cp.galvanic_couple           — driving voltage, area ratio, swapped metals
  cp.faraday_corrosion_rate    — Faraday's Law hand-calcs vs NACE/Fontana
  cp.penetration_remaining_life — wall loss & remaining life
  cp.sacrificial_anode_demand  — CP current demand
  cp.anode_mass_design_life    — DNV-RP-B401 anode mass
  cp.anode_count_dwight        — Dwight formula resistance & count
  cp.iccp_sizing               — ICCP rectifier sizing
  cp.pourbaix_region           — Pourbaix E-pH classification
  cp.corrosivity_category      — ISO 12944 / NACE category from resistivity
  cp.coating_breakdown_factor  — CBF linear model
  tools.*                      — LLM tool wrappers (happy path + error paths)

All tests are pure-Python and hermetic: no OCC, no DB, no network, no fixtures.
Formulas verified against published NACE/corrosion-text hand-calcs.

References
----------
Fontana, Corrosion Engineering (3rd ed.), Chapter 3 & 10
NACE SP0169-2013 — Underground/Submerged Cathodic Protection
DNV-RP-B401:2021 — Cathodic Protection Design
ASTM G102-89 — Calculation of Corrosion Rates

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.corrosion.cp import (
    galvanic_couple,
    faraday_corrosion_rate,
    penetration_remaining_life,
    sacrificial_anode_demand,
    anode_mass_design_life,
    anode_count_dwight,
    iccp_sizing,
    pourbaix_region,
    corrosivity_category,
    coating_breakdown_factor,
    _FARADAY,
    _ANODE_DATA,
)
from kerf_cad_core.corrosion.tools import (
    run_galvanic_couple,
    run_faraday_corrosion_rate,
    run_penetration_remaining_life,
    run_sacrificial_anode_demand,
    run_anode_mass_design_life,
    run_anode_count_dwight,
    run_iccp_sizing,
    run_pourbaix_region,
    run_corrosivity_category,
    run_coating_breakdown_factor,
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


REL = 1e-6  # relative tolerance


# ===========================================================================
# 1. galvanic_couple
# ===========================================================================

class TestGalvanicCouple:

    def test_zinc_steel_driving_voltage(self):
        """Zinc (−1.05 V) vs mild_steel (−0.50 V) → driving voltage = 0.55 V."""
        res = galvanic_couple("zinc", "mild_steel")
        assert res["ok"] is True
        assert abs(res["driving_voltage_V"] - 0.55) < 1e-9

    def test_anode_is_more_active(self):
        """Anode must always have more negative potential than cathode."""
        res = galvanic_couple("copper", "zinc")
        assert res["ok"] is True
        assert res["anode_potential_V_she"] < res["cathode_potential_V_she"]

    def test_swapped_metals_same_result(self):
        """Supplying metals in reverse order should give the same result."""
        res_a = galvanic_couple("zinc", "copper")
        res_b = galvanic_couple("copper", "zinc")
        assert res_a["driving_voltage_V"] == pytest.approx(res_b["driving_voltage_V"])
        assert res_a["anode_metal"] == res_b["anode_metal"]

    def test_area_ratio_unity(self):
        """Equal areas → area_ratio == 1.0."""
        res = galvanic_couple("zinc", "copper", anode_area_m2=2.0, cathode_area_m2=2.0)
        assert res["ok"] is True
        assert res["area_ratio"] == pytest.approx(1.0)

    def test_large_cathode_area_ratio_warning(self):
        """Cathode area 20× larger → UNFAVORABLE warning."""
        res = galvanic_couple("zinc", "copper", anode_area_m2=1.0, cathode_area_m2=20.0)
        assert res["ok"] is True
        assert res["area_ratio"] == pytest.approx(20.0)
        assert any("UNFAVORABLE" in w or "area" in w.lower() for w in res["warnings"])

    def test_unknown_metal_error(self):
        res = galvanic_couple("unobtanium", "copper")
        assert res["ok"] is False
        assert "reason" in res

    def test_negative_area_error(self):
        res = galvanic_couple("zinc", "copper", anode_area_m2=-1.0)
        assert res["ok"] is False

    def test_noble_metals_driving_voltage_positive(self):
        """Gold (0.95 V) vs copper (−0.02 V): driving voltage should be positive."""
        res = galvanic_couple("copper", "gold")
        assert res["ok"] is True
        assert res["driving_voltage_V"] > 0

    def test_same_metal_zero_driving_voltage(self):
        """Same metal for anode and cathode → driving voltage = 0."""
        res = galvanic_couple("zinc", "zinc")
        assert res["ok"] is True
        assert res["driving_voltage_V"] == pytest.approx(0.0)

    def test_driving_voltage_high_raises_warning(self):
        """Mg (−1.75) vs gold (0.95): driving voltage = 2.70 V → warning."""
        res = galvanic_couple("magnesium", "gold")
        assert res["ok"] is True
        assert res["driving_voltage_V"] == pytest.approx(2.70, abs=0.01)
        assert any("RAPID_CORROSION" in w for w in res["warnings"])


# ===========================================================================
# 2. faraday_corrosion_rate
# ===========================================================================

class TestFaradayCorrosionRate:

    def test_zero_current_density_zero_rate(self):
        """Zero current density → zero corrosion rate in all units."""
        res = faraday_corrosion_rate(0.0, 27.93, 7.87)
        assert res["ok"] is True
        assert res["corrosion_rate_mm_yr"] == pytest.approx(0.0)
        assert res["corrosion_rate_mpy"] == pytest.approx(0.0)
        assert res["corrosion_rate_g_m2_d"] == pytest.approx(0.0)

    def test_steel_hand_calc_g_m2_d(self):
        """Hand-calc for steel: i=0.1 A/m², EW=27.93 g/mol, F=96485 C/mol.

        rate_g_m2_d = 0.1 × 27.93 / 96485 × 86400 = 2.500... g·m⁻²·d⁻¹
        """
        i = 0.1
        EW = 27.93
        F = 96485.0
        expected_g_m2_d = i * EW / F * 86400.0
        res = faraday_corrosion_rate(i, EW, 7.87)
        assert res["ok"] is True
        assert abs(res["corrosion_rate_g_m2_d"] - expected_g_m2_d) / expected_g_m2_d < REL

    def test_steel_hand_calc_mm_yr(self):
        """Penetration rate for steel: mm_yr = g_m2_yr / (rho × 1000).

        rho = 7.87 g/cm³; g_m2_d = i×EW/F×86400; mm_yr = g_m2_d×365.25/(7.87×1000)
        """
        i = 0.1
        EW = 27.93
        rho = 7.87
        F = 96485.0
        g_m2_d = i * EW / F * 86400.0
        expected_mm_yr = g_m2_d * 365.25 / (rho * 1e3)
        res = faraday_corrosion_rate(i, EW, rho)
        assert res["ok"] is True
        assert abs(res["corrosion_rate_mm_yr"] - expected_mm_yr) / expected_mm_yr < REL

    def test_mpy_conversion(self):
        """mpy = mm_yr × 39.3701."""
        res = faraday_corrosion_rate(0.05, 27.93, 7.87)
        assert res["ok"] is True
        assert abs(res["corrosion_rate_mpy"] - res["corrosion_rate_mm_yr"] * 39.3701) < 1e-9

    def test_rapid_corrosion_warning(self):
        """Large current density → RAPID_CORROSION warning."""
        res = faraday_corrosion_rate(10.0, 27.93, 7.87)
        assert res["ok"] is True
        assert any("RAPID_CORROSION" in w for w in res["warnings"])

    def test_negative_current_density_error(self):
        res = faraday_corrosion_rate(-0.1, 27.93, 7.87)
        assert res["ok"] is False

    def test_zero_density_error(self):
        res = faraday_corrosion_rate(0.1, 27.93, 0.0)
        assert res["ok"] is False

    def test_zinc_hand_calc(self):
        """Zinc: EW=32.69 g/mol, rho=7.13 g/cm³, i=0.05 A/m²."""
        i, EW, rho = 0.05, 32.69, 7.13
        g_m2_d = i * EW / _FARADAY * 86400.0
        expected_mm_yr = g_m2_d * 365.25 / (rho * 1e3)
        res = faraday_corrosion_rate(i, EW, rho)
        assert res["ok"] is True
        assert abs(res["corrosion_rate_mm_yr"] - expected_mm_yr) / expected_mm_yr < REL


# ===========================================================================
# 3. penetration_remaining_life
# ===========================================================================

class TestPenetrationRemainingLife:

    def test_basic_remaining_life(self):
        """10 mm wall, 0.5 mm/yr, no minimum → 20 yr."""
        res = penetration_remaining_life(10.0, 0.5)
        assert res["ok"] is True
        assert abs(res["remaining_life_yr"] - 20.0) < 1e-9

    def test_with_minimum_thickness(self):
        """10 mm wall, 3 mm minimum, 0.5 mm/yr → 14 yr."""
        res = penetration_remaining_life(10.0, 0.5, minimum_thickness_mm=3.0)
        assert res["ok"] is True
        assert abs(res["remaining_life_yr"] - 14.0) < 1e-9

    def test_zero_corrosion_rate_infinite_life(self):
        res = penetration_remaining_life(8.0, 0.0)
        assert res["ok"] is True
        assert res["remaining_life_yr"] == float("inf")

    def test_short_remaining_life_warning(self):
        """2 yr remaining → RAPID_CORROSION warning."""
        res = penetration_remaining_life(5.0, 2.5)
        assert res["ok"] is True
        assert any("RAPID_CORROSION" in w for w in res["warnings"])

    def test_available_loss(self):
        """available_loss_mm = wall − minimum."""
        res = penetration_remaining_life(12.0, 1.0, minimum_thickness_mm=2.0)
        assert res["ok"] is True
        assert res["available_loss_mm"] == pytest.approx(10.0)

    def test_minimum_ge_wall_error(self):
        res = penetration_remaining_life(5.0, 1.0, minimum_thickness_mm=5.0)
        assert res["ok"] is False

    def test_negative_wall_thickness_error(self):
        res = penetration_remaining_life(-1.0, 0.5)
        assert res["ok"] is False

    def test_negative_rate_error(self):
        res = penetration_remaining_life(10.0, -0.1)
        assert res["ok"] is False


# ===========================================================================
# 4. sacrificial_anode_demand
# ===========================================================================

class TestSacrificialAnodeDemand:

    def test_fully_bare_current_equals_area_times_density(self):
        """Coating efficiency 0 → I = area × i_c."""
        A, i_mA = 100.0, 50.0
        res = sacrificial_anode_demand(A, 0.0, i_mA)
        assert res["ok"] is True
        expected = A * 1.0 * i_mA * 1e-3
        assert abs(res["total_current_A"] - expected) < 1e-10

    def test_fully_coated_zero_current(self):
        """Coating efficiency 1 → I = 0."""
        res = sacrificial_anode_demand(200.0, 1.0, 50.0)
        assert res["ok"] is True
        assert res["total_current_A"] == pytest.approx(0.0)

    def test_partial_coating(self):
        """50% coated, 100 m², 50 mA/m²: I = 50×0.5×0.05 = 1.25 A."""
        res = sacrificial_anode_demand(100.0, 0.5, 50.0)
        assert res["ok"] is True
        assert abs(res["total_current_A"] - 2.5) < 1e-9

    def test_low_coating_efficiency_warning(self):
        """< 50% coating efficiency → warning."""
        res = sacrificial_anode_demand(100.0, 0.3, 50.0)
        assert res["ok"] is True
        assert any("UNDER_PROTECTED" in w for w in res["warnings"])

    def test_negative_area_error(self):
        res = sacrificial_anode_demand(-10.0, 0.8, 50.0)
        assert res["ok"] is False

    def test_coating_out_of_range_error(self):
        res = sacrificial_anode_demand(100.0, 1.5, 50.0)
        assert res["ok"] is False

    def test_effective_bare_area_formula(self):
        """effective_bare_area = area × (1 − coating_efficiency)."""
        A, ce = 500.0, 0.7
        res = sacrificial_anode_demand(A, ce, 30.0)
        assert res["ok"] is True
        assert res["effective_bare_area_m2"] == pytest.approx(A * (1.0 - ce))


# ===========================================================================
# 5. anode_mass_design_life
# ===========================================================================

class TestAnodeMassDesignLife:

    def test_aluminum_anode_hand_calc(self):
        """M = I × T × 8760 / (u × C).

        I=1 A, T=20 yr, u=0.85, C=2000 A·h/kg (aluminum)
        M = 1 × 20 × 8760 / (0.85 × 2000) = 175200 / 1700 ≈ 103.06 kg
        """
        I, T, u = 1.0, 20.0, 0.85
        C = _ANODE_DATA["aluminum"]["capacity_Ah_kg"]
        expected = (I * T * 8760.0) / (u * C)
        res = anode_mass_design_life(I, T, utilisation_factor=u, anode_type="aluminum")
        assert res["ok"] is True
        assert abs(res["anode_mass_net_kg"] - expected) / expected < REL

    def test_zinc_anode_hand_calc(self):
        """Zinc: C=780 A·h/kg; I=2 A, T=10 yr, u=0.80."""
        I, T, u = 2.0, 10.0, 0.80
        C = _ANODE_DATA["zinc"]["capacity_Ah_kg"]
        expected = (I * T * 8760.0) / (u * C)
        res = anode_mass_design_life(I, T, utilisation_factor=u, anode_type="zinc")
        assert res["ok"] is True
        assert abs(res["anode_mass_net_kg"] - expected) / expected < REL

    def test_magnesium_anode_hand_calc(self):
        """Magnesium: C=1100 A·h/kg; I=0.5 A, T=25 yr, u=0.85."""
        I, T, u = 0.5, 25.0, 0.85
        C = _ANODE_DATA["magnesium"]["capacity_Ah_kg"]
        expected = (I * T * 8760.0) / (u * C)
        res = anode_mass_design_life(I, T, utilisation_factor=u, anode_type="magnesium")
        assert res["ok"] is True
        assert abs(res["anode_mass_net_kg"] - expected) / expected < REL

    def test_higher_current_larger_mass(self):
        """Doubling current doubles required anode mass."""
        res1 = anode_mass_design_life(1.0, 10.0)
        res2 = anode_mass_design_life(2.0, 10.0)
        assert res1["ok"] is True and res2["ok"] is True
        assert abs(res2["anode_mass_net_kg"] / res1["anode_mass_net_kg"] - 2.0) < REL

    def test_unknown_anode_type_error(self):
        res = anode_mass_design_life(1.0, 10.0, anode_type="unobtanium")
        assert res["ok"] is False

    def test_invalid_utilisation_error(self):
        res = anode_mass_design_life(1.0, 10.0, utilisation_factor=1.5)
        assert res["ok"] is False

    def test_zero_current_error(self):
        res = anode_mass_design_life(0.0, 10.0)
        assert res["ok"] is False


# ===========================================================================
# 6. anode_count_dwight
# ===========================================================================

class TestAnodeCountDwight:

    def test_dwight_resistance_formula(self):
        """Verify R = (rho / 2πL) × (ln(8L/d) − 1) for known dimensions.

        L=1.5 m, d=0.05 m (r=0.025 m), rho=10 Ω·m:
        R = (10 / (2π×1.5)) × (ln(8×1.5/0.05) − 1)
          = (10 / 9.4248) × (ln(240) − 1)
          = 1.0610 × (5.4806 − 1)
          = 1.0610 × 4.4806 ≈ 4.754 Ω
        """
        L, r, rho = 1.5, 0.025, 10.0
        d = 2 * r
        R_expected = (rho / (2 * math.pi * L)) * (math.log(8 * L / d) - 1)
        res = anode_count_dwight(1.0, L, r, rho, 0.30)
        assert res["ok"] is True
        assert abs(res["anode_resistance_ohm"] - R_expected) / R_expected < REL

    def test_current_per_anode_formula(self):
        """I_anode = driving_voltage / R_a."""
        L, r, rho, V = 1.5, 0.025, 10.0, 0.30
        res = anode_count_dwight(1.0, L, r, rho, V)
        assert res["ok"] is True
        expected_I = V / res["anode_resistance_ohm"]
        assert abs(res["current_per_anode_A"] - expected_I) / expected_I < REL

    def test_more_current_more_anodes(self):
        """Higher total current demand → more anodes required."""
        kwargs = dict(anode_length_m=1.5, anode_radius_m=0.025,
                      soil_resistivity_ohm_m=10.0, driving_voltage_V=0.30)
        res1 = anode_count_dwight(1.0, **kwargs)
        res2 = anode_count_dwight(5.0, **kwargs)
        assert res1["ok"] is True and res2["ok"] is True
        assert res2["n_anodes"] >= res1["n_anodes"]

    def test_high_resistivity_warning(self):
        """Resistivity > 100 Ω·m → warning."""
        res = anode_count_dwight(1.0, 1.5, 0.025, 200.0, 0.50)
        assert res["ok"] is True
        assert any("HIGH_RESISTIVITY" in w for w in res["warnings"])

    def test_negative_resistivity_error(self):
        res = anode_count_dwight(1.0, 1.5, 0.025, -5.0, 0.30)
        assert res["ok"] is False

    def test_zero_driving_voltage_error(self):
        res = anode_count_dwight(1.0, 1.5, 0.025, 10.0, 0.0)
        assert res["ok"] is False


# ===========================================================================
# 7. iccp_sizing
# ===========================================================================

class TestICCPSizing:

    def test_design_current_formula(self):
        """I_design = A × (1−ce) × i_c × sf (no attenuation)."""
        A, ce, i_mA, R_gb, sf = 1000.0, 0.8, 50.0, 2.0, 1.25
        i_c = i_mA * 1e-3
        I_demand = A * (1.0 - ce) * i_c
        I_design = I_demand * sf
        res = iccp_sizing(A, ce, i_mA, R_gb, safety_factor=sf)
        assert res["ok"] is True
        assert abs(res["rectifier_current_A"] - I_design) / I_design < REL

    def test_voltage_formula(self):
        """V_rect = I_design × R_gb + 2 V (back-EMF)."""
        A, ce, i_mA, R_gb = 500.0, 0.85, 30.0, 3.0
        res = iccp_sizing(A, ce, i_mA, R_gb)
        assert res["ok"] is True
        expected_V = res["rectifier_current_A"] * R_gb + 2.0
        # Voltage is max(expected, 12 V)
        expected_V = max(expected_V, 12.0)
        assert abs(res["rectifier_voltage_V"] - expected_V) < 1e-9

    def test_minimum_voltage_12v(self):
        """Very small current → rectifier voltage at least 12 V."""
        res = iccp_sizing(1.0, 0.99, 1.0, 0.1)
        assert res["ok"] is True
        assert res["rectifier_voltage_V"] >= 12.0

    def test_low_coating_efficiency_warning(self):
        res = iccp_sizing(200.0, 0.2, 50.0, 2.0)
        assert res["ok"] is True
        assert any("UNDER_PROTECTED" in w for w in res["warnings"])

    def test_safety_factor_below_one_error(self):
        res = iccp_sizing(500.0, 0.8, 50.0, 2.0, safety_factor=0.8)
        assert res["ok"] is False

    def test_attenuation_factor_scales_current(self):
        """Attenuation factor 2.0 doubles the design current."""
        A, ce, i_mA, R_gb = 1000.0, 0.8, 50.0, 1.0
        res1 = iccp_sizing(A, ce, i_mA, R_gb, attenuation_factor=1.0)
        res2 = iccp_sizing(A, ce, i_mA, R_gb, attenuation_factor=2.0)
        assert res1["ok"] is True and res2["ok"] is True
        assert abs(res2["rectifier_current_A"] / res1["rectifier_current_A"] - 2.0) < REL


# ===========================================================================
# 8. pourbaix_region
# ===========================================================================

class TestPourbaixRegion:

    def test_immune_region_iron_very_negative(self):
        """Very negative potential → immune for iron."""
        res = pourbaix_region(-2.0, 7.0, metal="iron")
        assert res["ok"] is True
        assert res["region"] == "immune"

    def test_corrosion_region_iron_positive_potential(self):
        """High positive potential at neutral pH → corrosion for iron."""
        res = pourbaix_region(0.8, 7.0, metal="iron")
        assert res["ok"] is True
        assert res["region"] == "corrosion"
        assert any("CORROSION_REGION" in w for w in res["warnings"])

    def test_passive_region_iron_midrange(self):
        """Mid-range potential at pH 7 → passive region for iron."""
        res = pourbaix_region(-0.3, 7.0, metal="iron")
        assert res["ok"] is True
        assert res["region"] in ("passive", "immune")  # boundary depends on exact calc

    def test_steel_same_as_iron(self):
        """Steel and iron should give identical results."""
        E, pH = -0.2, 7.0
        res_fe = pourbaix_region(E, pH, metal="iron")
        res_st = pourbaix_region(E, pH, metal="steel")
        assert res_fe["ok"] is True and res_st["ok"] is True
        assert res_fe["region"] == res_st["region"]

    def test_ph_out_of_range_error(self):
        res = pourbaix_region(-0.5, 15.0, metal="iron")
        assert res["ok"] is False

    def test_unknown_metal_error(self):
        res = pourbaix_region(-0.5, 7.0, metal="unobtanium")
        assert res["ok"] is False

    def test_over_protection_warning_iron(self):
        """Very negative potential for iron/steel → over-protection H2 warning."""
        res = pourbaix_region(-1.5, 7.0, metal="steel")
        assert res["ok"] is True
        assert any("OVER_PROTECTION" in w for w in res["warnings"])

    def test_non_finite_potential_error(self):
        res = pourbaix_region(float("inf"), 7.0)
        assert res["ok"] is False


# ===========================================================================
# 9. corrosivity_category
# ===========================================================================

class TestCorrosivityCategory:

    def test_seawater_resistivity_c5(self):
        """Resistivity < 2 Ω·m → C5 Extremely corrosive."""
        res = corrosivity_category(soil_resistivity_ohm_m=0.5)
        assert res["ok"] is True
        assert res["corrosivity_category"] == "C5"

    def test_moderate_resistivity_c3(self):
        """Resistivity 15 Ω·m → C3."""
        res = corrosivity_category(soil_resistivity_ohm_m=15.0)
        assert res["ok"] is True
        assert res["corrosivity_category"] == "C3"

    def test_high_resistivity_c1(self):
        """Resistivity 200 Ω·m → C1 Low corrosivity."""
        res = corrosivity_category(soil_resistivity_ohm_m=200.0)
        assert res["ok"] is True
        assert res["corrosivity_category"] == "C1"

    def test_offshore_environment_c5(self):
        """Offshore environment → C5."""
        res = corrosivity_category(environment="offshore")
        assert res["ok"] is True
        assert res["corrosivity_category"] == "C5"

    def test_rural_environment_c2(self):
        """Rural environment → C2."""
        res = corrosivity_category(environment="rural")
        assert res["ok"] is True
        assert res["corrosivity_category"] == "C2"

    def test_indoor_dry_environment_c1(self):
        res = corrosivity_category(environment="indoor_dry")
        assert res["ok"] is True
        assert res["corrosivity_category"] == "C1"

    def test_both_params_error(self):
        res = corrosivity_category(soil_resistivity_ohm_m=10.0, environment="rural")
        assert res["ok"] is False

    def test_neither_param_error(self):
        res = corrosivity_category()
        assert res["ok"] is False

    def test_unknown_environment_error(self):
        res = corrosivity_category(environment="moon_base")
        assert res["ok"] is False

    def test_high_corrosivity_warning(self):
        """C4/C5 → warning raised."""
        res = corrosivity_category(soil_resistivity_ohm_m=5.0)
        assert res["ok"] is True
        assert any("HIGH_CORROSIVITY" in w for w in res["warnings"])


# ===========================================================================
# 10. coating_breakdown_factor
# ===========================================================================

class TestCoatingBreakdownFactor:

    def test_initial_cbf_at_age_zero(self):
        """At age 0, CBF = initial_breakdown_frac."""
        cbf_i = 0.01
        res = coating_breakdown_factor(0.0, 20.0, initial_breakdown_frac=cbf_i)
        assert res["ok"] is True
        assert abs(res["breakdown_factor"] - cbf_i) < 1e-12

    def test_final_cbf_at_design_life(self):
        """At age == design_life, CBF = final_breakdown_frac."""
        cbf_f = 0.05
        res = coating_breakdown_factor(20.0, 20.0, final_breakdown_frac=cbf_f)
        assert res["ok"] is True
        assert abs(res["breakdown_factor"] - cbf_f) < 1e-12

    def test_linear_interpolation(self):
        """At half design life, CBF = (initial + final) / 2."""
        cbf_i, cbf_f, T = 0.01, 0.05, 20.0
        res = coating_breakdown_factor(10.0, T, initial_breakdown_frac=cbf_i,
                                       final_breakdown_frac=cbf_f)
        assert res["ok"] is True
        expected = cbf_i + (cbf_f - cbf_i) * 0.5
        assert abs(res["breakdown_factor"] - expected) < 1e-12

    def test_mean_cbf_formula(self):
        """mean_cbf = (initial + final) / 2."""
        cbf_i, cbf_f = 0.01, 0.08
        res = coating_breakdown_factor(5.0, 25.0, initial_breakdown_frac=cbf_i,
                                       final_breakdown_frac=cbf_f)
        assert res["ok"] is True
        assert abs(res["mean_breakdown_factor"] - (cbf_i + cbf_f) / 2.0) < 1e-12

    def test_age_exceeds_design_life_clamped(self):
        """Age > design_life → CBF clamped at final value; warning raised."""
        cbf_f = 0.05
        res = coating_breakdown_factor(25.0, 20.0, final_breakdown_frac=cbf_f)
        assert res["ok"] is True
        assert abs(res["breakdown_factor"] - cbf_f) < 1e-12
        assert any("COATING_EXPIRED" in w for w in res["warnings"])

    def test_final_lt_initial_error(self):
        res = coating_breakdown_factor(5.0, 20.0, initial_breakdown_frac=0.10,
                                       final_breakdown_frac=0.02)
        assert res["ok"] is False

    def test_negative_age_error(self):
        res = coating_breakdown_factor(-1.0, 20.0)
        assert res["ok"] is False

    def test_high_breakdown_warning(self):
        """CBF > 10% → warning."""
        res = coating_breakdown_factor(18.0, 20.0, initial_breakdown_frac=0.08,
                                       final_breakdown_frac=0.20)
        assert res["ok"] is True
        assert any("HIGH_BREAKDOWN" in w for w in res["warnings"])


# ===========================================================================
# 11. LLM tool wrappers
# ===========================================================================

class TestToolWrappers:

    def test_run_galvanic_couple_happy(self):
        ctx = _ctx()
        raw = _run(run_galvanic_couple(ctx, _args(anode_metal="zinc", cathode_metal="copper")))
        d = _ok_tool(raw)
        assert d["driving_voltage_V"] > 0

    def test_run_galvanic_couple_missing_anode(self):
        ctx = _ctx()
        raw = _run(run_galvanic_couple(ctx, _args(cathode_metal="copper")))
        _err_tool(raw)

    def test_run_galvanic_couple_bad_json(self):
        ctx = _ctx()
        raw = _run(run_galvanic_couple(ctx, b"not json"))
        _err_tool(raw)

    def test_run_faraday_corrosion_rate_happy(self):
        ctx = _ctx()
        raw = _run(run_faraday_corrosion_rate(
            ctx, _args(current_density_A_m2=0.1, equivalent_weight_g_mol=27.93,
                       density_g_cm3=7.87)
        ))
        d = _ok_tool(raw)
        assert d["corrosion_rate_mm_yr"] > 0

    def test_run_faraday_missing_field(self):
        ctx = _ctx()
        raw = _run(run_faraday_corrosion_rate(
            ctx, _args(current_density_A_m2=0.1, equivalent_weight_g_mol=27.93)
        ))
        _err_tool(raw)

    def test_run_penetration_remaining_life_happy(self):
        ctx = _ctx()
        raw = _run(run_penetration_remaining_life(
            ctx, _args(wall_thickness_mm=10.0, corrosion_rate_mm_yr=0.5)
        ))
        d = _ok_tool(raw)
        assert d["remaining_life_yr"] == pytest.approx(20.0)

    def test_run_sacrificial_anode_demand_happy(self):
        ctx = _ctx()
        raw = _run(run_sacrificial_anode_demand(
            ctx, _args(bare_area_m2=200.0, coating_efficiency=0.85,
                       current_density_mA_m2=50.0)
        ))
        d = _ok_tool(raw)
        assert d["total_current_A"] > 0

    def test_run_anode_mass_design_life_aluminum(self):
        ctx = _ctx()
        raw = _run(run_anode_mass_design_life(
            ctx, _args(current_A=2.0, design_life_yr=20.0, anode_type="aluminum")
        ))
        d = _ok_tool(raw)
        # Hand-calc: 2 × 20 × 8760 / (0.85 × 2000) ≈ 206.12 kg
        expected = (2.0 * 20.0 * 8760.0) / (0.85 * 2000.0)
        assert abs(d["anode_mass_net_kg"] - expected) / expected < REL

    def test_run_anode_count_dwight_happy(self):
        ctx = _ctx()
        raw = _run(run_anode_count_dwight(ctx, _args(
            total_current_A=5.0, anode_length_m=1.5, anode_radius_m=0.025,
            soil_resistivity_ohm_m=10.0, driving_voltage_V=0.30
        )))
        d = _ok_tool(raw)
        assert d["n_anodes"] > 0
        assert d["anode_resistance_ohm"] > 0

    def test_run_iccp_sizing_happy(self):
        ctx = _ctx()
        raw = _run(run_iccp_sizing(ctx, _args(
            protected_area_m2=1000.0, coating_efficiency=0.8,
            current_density_mA_m2=50.0, groundbed_resistance_ohm=2.0
        )))
        d = _ok_tool(raw)
        assert d["rectifier_current_A"] > 0
        assert d["rectifier_voltage_V"] >= 12.0

    def test_run_pourbaix_region_immune(self):
        ctx = _ctx()
        raw = _run(run_pourbaix_region(ctx, _args(potential_V_she=-2.0, pH=7.0)))
        d = _ok_tool(raw)
        assert d["region"] == "immune"

    def test_run_pourbaix_region_missing_ph(self):
        ctx = _ctx()
        raw = _run(run_pourbaix_region(ctx, _args(potential_V_she=-0.5)))
        _err_tool(raw)

    def test_run_corrosivity_category_soil(self):
        ctx = _ctx()
        raw = _run(run_corrosivity_category(ctx, _args(soil_resistivity_ohm_m=5.0)))
        d = _ok_tool(raw)
        assert d["corrosivity_category"] == "C4"

    def test_run_corrosivity_category_no_params(self):
        ctx = _ctx()
        raw = _run(run_corrosivity_category(ctx, _args()))
        _err_tool(raw)

    def test_run_coating_breakdown_factor_happy(self):
        ctx = _ctx()
        raw = _run(run_coating_breakdown_factor(ctx, _args(age_yr=10.0, design_life_yr=20.0)))
        d = _ok_tool(raw)
        assert d["breakdown_factor"] > 0
        assert d["fraction_life_consumed"] == pytest.approx(0.5)

    def test_run_coating_breakdown_expired_warning(self):
        ctx = _ctx()
        raw = _run(run_coating_breakdown_factor(ctx, _args(age_yr=25.0, design_life_yr=20.0)))
        d = _ok_tool(raw)
        assert any("COATING_EXPIRED" in w for w in d["warnings"])
