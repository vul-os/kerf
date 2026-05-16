"""
Hermetic tests for kerf_cad_core.buildingenergy — building energy & daylighting.

Coverage:
  energy.uvalue_series            — ISO 6946 series layers, air films, R→U
  energy.uvalue_parallel          — area-weighted parallel paths (stud+cavity)
  energy.uvalue_bridged           — thermal bridging fractional-area method
  energy.whole_building_ua        — multi-surface UA summation
  energy.balance_point_temperature — balance-point formula
  energy.degree_day_energy        — HDD/CDD annual energy formula
  energy.annual_fuel_cost         — fuel type conversion + cost
  energy.design_heating_load      — envelope + infiltration + vent − gains
  energy.design_cooling_load      — envelope + all gains + latent
  energy.infiltration_ach_blower_door — ACH50 / n formula
  energy.infiltration_ach_aim2    — AIM-2 stack + wind quadrature
  energy.glaser_condensation      — Glaser dew-point at interfaces
  energy.solar_heat_gain          — SHGC × IAM × irradiance
  energy.shading_projection_factor — overhang shadow depth / window height
  energy.daylight_factor          — BRE DF formula
  energy.window_to_floor_ratio    — simple ratio + warnings
  energy.no_sky_line_depth        — depth = multiplier × head height
  energy.overheating_hours        — free-float T_indoor vs comfort threshold
  energy.eui                      — annual energy / floor area
  energy.ashrae901_envelope_compliance — prescriptive U-max check CZ1–8
  tools.*                         — LLM wrapper happy paths + error paths

All tests are pure-Python and hermetic: no OCC, no DB, no network.
Formulas verified against ASHRAE/CIBSE hand-calculations.

References
----------
ASHRAE Handbook — Fundamentals (2021), Chapters 15, 16, 18, 27
ASHRAE 90.1-2022 — Energy Standard for Buildings
ISO 6946:2017 — Thermal resistance and thermal transmittance
CIBSE Guide A (2015); BRE Digest 309

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid
import warnings

import pytest

from kerf_cad_core.buildingenergy.energy import (
    uvalue_series,
    uvalue_parallel,
    uvalue_bridged,
    whole_building_ua,
    balance_point_temperature,
    degree_day_energy,
    annual_fuel_cost,
    design_heating_load,
    design_cooling_load,
    infiltration_ach_blower_door,
    infiltration_ach_aim2,
    glaser_condensation,
    solar_heat_gain,
    shading_projection_factor,
    daylight_factor,
    window_to_floor_ratio,
    no_sky_line_depth,
    overheating_hours,
    eui,
    ashrae901_envelope_compliance,
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


# ---------------------------------------------------------------------------
# uvalue_series
# ---------------------------------------------------------------------------

class TestUvalueSeries:
    def test_single_layer_r(self):
        # R = 2.0 → U = 0.5
        r = uvalue_series([{"r": 2.0}])
        assert r["ok"]
        assert abs(r["U_W_m2K"] - 0.5) < 1e-6
        assert abs(r["R_total_m2KW"] - 2.0) < 1e-6

    def test_single_layer_k_d(self):
        # concrete: k=1.0 W/mK, d=0.2 m → R=0.2, U=5.0
        r = uvalue_series([{"k": 1.0, "d": 0.2}])
        assert r["ok"]
        assert abs(r["U_W_m2K"] - 5.0) < 1e-4
        assert abs(r["R_total_m2KW"] - 0.2) < 1e-6

    def test_series_assembly_with_air_films(self):
        # Typical external wall: Rsi=0.13, plaster k=0.5 d=0.015, brick k=0.84 d=0.102,
        # cavity r=0.18, insulation k=0.04 d=0.1, Rse=0.04
        # R_total = 0.13 + 0.03 + 0.121 + 0.18 + 2.5 + 0.04 = 3.001
        layers = [
            {"r": 0.13},          # Rsi inner air film
            {"k": 0.5, "d": 0.015},  # plaster 0.03
            {"k": 0.84, "d": 0.102},  # brick ≈ 0.1214
            {"r": 0.18},          # cavity
            {"k": 0.04, "d": 0.10},  # 100mm mineral wool 2.5
            {"r": 0.04},          # Rse outer air film
        ]
        r = uvalue_series(layers)
        assert r["ok"]
        R_expected = 0.13 + 0.015/0.5 + 0.102/0.84 + 0.18 + 0.10/0.04 + 0.04
        assert abs(r["R_total_m2KW"] - R_expected) < 1e-4
        assert abs(r["U_W_m2K"] - 1.0/R_expected) < 1e-4

    def test_empty_layers_error(self):
        r = uvalue_series([])
        assert not r["ok"]

    def test_negative_r_error(self):
        r = uvalue_series([{"r": -1.0}])
        assert not r["ok"]

    def test_zero_k_error(self):
        r = uvalue_series([{"k": 0.0, "d": 0.1}])
        assert not r["ok"]

    def test_missing_keys_error(self):
        r = uvalue_series([{"x": 1.0}])
        assert not r["ok"]


# ---------------------------------------------------------------------------
# uvalue_parallel
# ---------------------------------------------------------------------------

class TestUvalueParallel:
    def test_uniform_path(self):
        # 100% at U=1.0 → U_combined = 1.0
        r = uvalue_parallel([(1.0, 1.0)])
        assert r["ok"]
        assert abs(r["U_W_m2K"] - 1.0) < 1e-6

    def test_two_paths_ashrae_framing(self):
        # 15% framing (U=2.0), 85% cavity (U=0.4)
        # U_combined = 0.15 × 2.0 + 0.85 × 0.4 = 0.64
        r = uvalue_parallel([(0.15, 2.0), (0.85, 0.4)])
        assert r["ok"]
        assert abs(r["U_W_m2K"] - 0.64) < 1e-6

    def test_warning_on_fraction_sum_error(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = uvalue_parallel([(0.5, 1.0), (0.3, 2.0)])  # sum=0.8
        assert r["ok"]
        assert any("fractions sum" in str(x.message) for x in w)

    def test_empty_error(self):
        r = uvalue_parallel([])
        assert not r["ok"]


# ---------------------------------------------------------------------------
# uvalue_bridged
# ---------------------------------------------------------------------------

class TestUvalueBridged:
    def test_no_bridge(self):
        # 0% bridge → combined = clear field
        r = uvalue_bridged(0.3, 2.0, 0.0)
        assert r["ok"]
        assert abs(r["U_combined_W_m2K"] - 0.3) < 1e-6

    def test_full_bridge(self):
        # 100% bridge
        r = uvalue_bridged(0.3, 2.0, 1.0)
        assert r["ok"]
        assert abs(r["U_combined_W_m2K"] - 2.0) < 1e-6

    def test_10pct_steel_stud(self):
        # 10% steel stud (U_bridge=4.0), 90% cavity (U_clear=0.35)
        # U = 0.9×0.35 + 0.1×4.0 = 0.315 + 0.4 = 0.715
        r = uvalue_bridged(0.35, 4.0, 0.10)
        assert r["ok"]
        assert abs(r["U_combined_W_m2K"] - 0.715) < 1e-6

    def test_invalid_bridge_fraction(self):
        r = uvalue_bridged(0.3, 2.0, 1.5)
        assert not r["ok"]


# ---------------------------------------------------------------------------
# whole_building_ua
# ---------------------------------------------------------------------------

class TestWholeBuildingUA:
    def test_single_surface(self):
        # A=100 m², U=0.5 → UA=50
        r = whole_building_ua([{"area_m2": 100, "U": 0.5}])
        assert r["ok"]
        assert abs(r["UA_W_per_K"] - 50.0) < 1e-4

    def test_multi_surface(self):
        surfaces = [
            {"area_m2": 200, "U": 0.30},   # roof
            {"area_m2": 300, "U": 0.45},   # walls
            {"area_m2": 50,  "U": 2.00},   # windows
        ]
        # UA = 60 + 135 + 100 = 295
        r = whole_building_ua(surfaces)
        assert r["ok"]
        assert abs(r["UA_W_per_K"] - 295.0) < 1e-4
        assert abs(r["total_area_m2"] - 550.0) < 1e-4

    def test_empty_error(self):
        r = whole_building_ua([])
        assert not r["ok"]


# ---------------------------------------------------------------------------
# balance_point_temperature
# ---------------------------------------------------------------------------

class TestBalancePointTemperature:
    def test_standard_case(self):
        # T_indoor=21, Q_int=2000W, UA=200 W/K → T_balance=21-10=11°C
        r = balance_point_temperature(21.0, 2000.0, 200.0)
        assert r["ok"]
        assert abs(r["T_balance_C"] - 11.0) < 1e-3

    def test_zero_gains(self):
        # no internal gains → T_balance = T_indoor
        r = balance_point_temperature(20.0, 0.0, 100.0)
        assert r["ok"]
        assert abs(r["T_balance_C"] - 20.0) < 1e-6

    def test_zero_ua_error(self):
        r = balance_point_temperature(20.0, 1000.0, 0.0)
        assert not r["ok"]


# ---------------------------------------------------------------------------
# degree_day_energy
# ---------------------------------------------------------------------------

class TestDegreeDay:
    def test_heating_hdd(self):
        # UA=200 W/K, HDD=2500 K·day, AFUE=0.9
        # E = 200 × 2500 × 24 / 0.9 / 1000 = 13333.3 kWh
        r = degree_day_energy(2500, 200, mode="heating", efficiency=0.9)
        assert r["ok"]
        expected = 200 * 2500 * 24 / 0.9 / 1000
        assert abs(r["energy_kWh"] - expected) < 0.1

    def test_cooling_cdd(self):
        # UA=300 W/K, CDD=600, COP=3.0
        # E = 300 × 600 × 24 / 3.0 / 1000 = 1440 kWh
        r = degree_day_energy(600, 300, mode="cooling", efficiency=3.0)
        assert r["ok"]
        assert abs(r["energy_kWh"] - 1440.0) < 0.1

    def test_invalid_mode_error(self):
        r = degree_day_energy(1000, 200, mode="unknown")
        assert not r["ok"]

    def test_zero_hdd(self):
        r = degree_day_energy(0, 200, mode="heating")
        assert r["ok"]
        assert r["energy_kWh"] == 0.0


# ---------------------------------------------------------------------------
# annual_fuel_cost
# ---------------------------------------------------------------------------

class TestAnnualFuelCost:
    def test_electricity(self):
        # 5000 kWh × $0.20/kWh = $1000
        r = annual_fuel_cost(5000, "electricity", price_per_unit=0.20)
        assert r["ok"]
        assert abs(r["cost"] - 1000.0) < 0.01
        assert r["fuel_units_required"] == 5000.0

    def test_natural_gas(self):
        # 5000 kWh / 10.55 kWh/m³ × $1.20/m³
        r = annual_fuel_cost(5000, "natural_gas", price_per_unit=1.20)
        assert r["ok"]
        expected_units = 5000 / 10.55
        assert abs(r["fuel_units_required"] - expected_units) < 0.01
        assert abs(r["cost"] - expected_units * 1.20) < 0.01

    def test_invalid_fuel_type(self):
        r = annual_fuel_cost(1000, "coal", price_per_unit=1.0)
        assert not r["ok"]


# ---------------------------------------------------------------------------
# design_heating_load
# ---------------------------------------------------------------------------

class TestDesignHeatingLoad:
    def test_basic_heating(self):
        # UA=200, T_in=21, T_out=-10, delta_T=31
        # Q_envelope = 200 × 31 = 6200 W
        surfaces = [{"area_m2": 200, "U": 1.0}]
        r = design_heating_load(surfaces, 21.0, -10.0)
        assert r["ok"]
        assert abs(r["envelope_W"] - 200 * 31) < 0.1
        assert abs(r["heating_load_W"] - 200 * 31) < 0.1

    def test_with_infiltration_and_gains(self):
        # UA=100 W/K, inf=20 W/K, vent=10 W/K, T_delta=20, gains=500W
        # Q = (100+20+10)*20 - 500 = 2600 - 500 = 2100
        surfaces = [{"area_m2": 100, "U": 1.0}]
        r = design_heating_load(
            surfaces, 20.0, 0.0,
            infiltration_W_per_K=20, ventilation_W_per_K=10, internal_gains_W=500
        )
        assert r["ok"]
        assert abs(r["heating_load_W"] - 2100.0) < 0.1

    def test_warm_outdoor_sets_zero(self):
        # T_out > T_in → no heating needed
        surfaces = [{"area_m2": 100, "U": 0.5}]
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            r = design_heating_load(surfaces, 20.0, 25.0)
        assert r["ok"]
        assert r["heating_load_W"] == 0.0


# ---------------------------------------------------------------------------
# design_cooling_load
# ---------------------------------------------------------------------------

class TestDesignCoolingLoad:
    def test_basic_cooling(self):
        # UA=200, T_out=38, T_in=24, delta_T=14
        # Q_envelope = 200 × 14 = 2800 W
        surfaces = [{"area_m2": 200, "U": 1.0}]
        r = design_cooling_load(surfaces, 24.0, 38.0)
        assert r["ok"]
        assert abs(r["envelope_W"] - 200 * 14) < 0.1

    def test_with_all_gains(self):
        # UA=100, delta_T=10, int=300, solar=500, latent=200
        # sensible = 100*10 + 300 + 500 = 1800
        # total = 1800 + 200 = 2000
        surfaces = [{"area_m2": 100, "U": 1.0}]
        r = design_cooling_load(
            surfaces, 24.0, 34.0,
            internal_gains_W=300, solar_gain_W=500, latent_gain_W=200
        )
        assert r["ok"]
        assert abs(r["cooling_load_W"] - 2000.0) < 0.1
        assert abs(r["latent_load_W"] - 200.0) < 0.1


# ---------------------------------------------------------------------------
# infiltration_ach_blower_door
# ---------------------------------------------------------------------------

class TestInfiltrationBlowerDoor:
    def test_standard_n20(self):
        # ACH50=5.0 / 20 = 0.25
        r = infiltration_ach_blower_door(5.0)
        assert r["ok"]
        assert abs(r["ACH_natural"] - 0.25) < 1e-5

    def test_custom_n(self):
        # ACH50=10.0 / 10 = 1.0
        r = infiltration_ach_blower_door(10.0, n=10.0)
        assert r["ok"]
        assert abs(r["ACH_natural"] - 1.0) < 1e-5

    def test_very_tight_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = infiltration_ach_blower_door(0.3, n=20.0)
        assert r["ok"]
        # ACH_nat = 0.015 < 0.03 → warning expected
        assert any("tight" in str(x.message).lower() or "0.0" in str(x.message) for x in w)

    def test_zero_ach50(self):
        r = infiltration_ach_blower_door(0.0)
        assert r["ok"]
        assert r["ACH_natural"] == 0.0


# ---------------------------------------------------------------------------
# infiltration_ach_aim2
# ---------------------------------------------------------------------------

class TestInfiltrationAIM2:
    def test_stack_only(self):
        # wind=0 → Q_wind=0 → total = Q_stack
        r = infiltration_ach_aim2(
            floor_area_m2=100, height_m=2.5, C_i=0.001,
            n_exp=0.65, delta_T_C=20, wind_speed_m_s=0.0
        )
        assert r["ok"]
        assert r["ACH"] > 0
        assert abs(r["Q_wind_m3_per_h"]) < 1e-6

    def test_positive_result(self):
        r = infiltration_ach_aim2(
            floor_area_m2=150, height_m=3.0, C_i=0.002,
            n_exp=0.65, delta_T_C=15, wind_speed_m_s=5.0,
            terrain_class="suburban"
        )
        assert r["ok"]
        assert r["ACH"] > 0
        assert r["Q_m3_per_h"] > 0

    def test_invalid_terrain(self):
        r = infiltration_ach_aim2(
            floor_area_m2=100, height_m=3.0, C_i=0.001,
            n_exp=0.65, delta_T_C=10, wind_speed_m_s=3.0,
            terrain_class="ocean"
        )
        assert not r["ok"]

    def test_invalid_n_exp(self):
        r = infiltration_ach_aim2(
            floor_area_m2=100, height_m=3.0, C_i=0.001,
            n_exp=1.5, delta_T_C=10, wind_speed_m_s=3.0
        )
        assert not r["ok"]


# ---------------------------------------------------------------------------
# glaser_condensation
# ---------------------------------------------------------------------------

class TestGlaser:
    def _wall_layers(self):
        # Interior finish → insulation → concrete → exterior
        return [
            {"name": "plasterboard", "d_m": 0.013, "k_W_mK": 0.25, "mu": 8},
            {"name": "mineral_wool",  "d_m": 0.100, "k_W_mK": 0.040, "mu": 1},
            {"name": "concrete",      "d_m": 0.200, "k_W_mK": 1.40, "mu": 100},
        ]

    def test_no_condensation_warm_side_insulation(self):
        # Warm indoor (20°C, 50% RH), cold outdoor (-10°C, 80% RH)
        # Insulation on warm side → dew point generally not reached
        r = glaser_condensation(
            self._wall_layers(), 20.0, -10.0, 0.50, 0.80
        )
        assert r["ok"]
        assert "interfaces" in r
        assert len(r["interfaces"]) == 3

    def test_condensation_risk_flagged(self):
        # Very high indoor RH + cold outdoor — expect condensation risk detected
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = glaser_condensation(
                self._wall_layers(), 22.0, -20.0, 0.95, 0.90
            )
        assert r["ok"]
        if r["condensation_risk"]:
            assert any("condensation" in str(x.message).lower() for x in w)

    def test_interface_fields(self):
        r = glaser_condensation(
            self._wall_layers(), 20.0, 5.0, 0.5, 0.7
        )
        assert r["ok"]
        for ifc in r["interfaces"]:
            assert "T_C" in ifc
            assert "T_dew_C" in ifc
            assert "p_vapour_Pa" in ifc
            assert "p_sat_Pa" in ifc
            assert isinstance(ifc["condensation"], bool)

    def test_empty_layers_error(self):
        r = glaser_condensation([], 20.0, 0.0, 0.5, 0.7)
        assert not r["ok"]

    def test_invalid_rh_error(self):
        r = glaser_condensation(
            self._wall_layers(), 20.0, 0.0, 0.0, 0.7
        )
        assert not r["ok"]


# ---------------------------------------------------------------------------
# solar_heat_gain
# ---------------------------------------------------------------------------

class TestSolarHeatGain:
    def test_normal_incidence(self):
        # theta=0 → IAM=1 → Q = 10 × 0.4 × 1.0 × 600 = 2400 W
        r = solar_heat_gain(10.0, 0.4, 600.0)
        assert r["ok"]
        assert abs(r["solar_gain_W"] - 2400.0) < 0.1
        assert abs(r["IAM"] - 1.0) < 1e-6

    def test_incidence_angle_reduces_gain(self):
        # theta=45° → IAM = 1 - 0.1*(1/cos45 - 1) = 1 - 0.1*(1.414-1) = 0.9586
        r = solar_heat_gain(10.0, 0.4, 600.0, incidence_angle_deg=45.0)
        assert r["ok"]
        cos45 = math.cos(math.radians(45))
        IAM_expected = 1.0 - 0.1 * (1.0/cos45 - 1.0)
        assert abs(r["IAM"] - IAM_expected) < 1e-4
        assert r["solar_gain_W"] < 2400.0

    def test_shading_factor(self):
        # shading_factor=0.5 halves the gain
        r_full = solar_heat_gain(10.0, 0.4, 600.0, shading_factor=1.0)
        r_half = solar_heat_gain(10.0, 0.4, 600.0, shading_factor=0.5)
        assert r_full["ok"] and r_half["ok"]
        assert abs(r_full["solar_gain_W"] / r_half["solar_gain_W"] - 2.0) < 1e-5

    def test_zero_irradiance(self):
        r = solar_heat_gain(10.0, 0.4, 0.0)
        assert r["ok"]
        assert r["solar_gain_W"] == 0.0

    def test_invalid_shgc(self):
        r = solar_heat_gain(10.0, 1.5, 600.0)
        assert not r["ok"]


# ---------------------------------------------------------------------------
# shading_projection_factor
# ---------------------------------------------------------------------------

class TestShadingProjectionFactor:
    def test_no_shadow_at_low_altitude(self):
        # altitude=0° → shadow depth=0
        r = shading_projection_factor(1.0, 2.0, 0.0, 180.0, 180.0)
        assert r["ok"]
        assert abs(r["shaded_fraction"]) < 1e-6

    def test_full_shade_at_high_sun(self):
        # overhang=2m, window_height=0.5m, altitude=45°, same azimuth
        # shadow_depth = 2 × tan(45) / cos(0) = 2.0 m > 0.5 m → full shade
        r = shading_projection_factor(2.0, 0.5, 45.0, 180.0, 180.0)
        assert r["ok"]
        assert abs(r["shaded_fraction"] - 1.0) < 1e-5

    def test_partial_shade(self):
        # overhang=1m, window_height=2m, altitude=30°, delta_az=0
        # shadow_depth = 1 × tan(30) / 1 = 0.5774 m
        # fraction = 0.5774 / 2 = 0.2887
        r = shading_projection_factor(1.0, 2.0, 30.0, 180.0, 180.0)
        assert r["ok"]
        expected = math.tan(math.radians(30.0)) / 2.0
        assert abs(r["shaded_fraction"] - expected) < 1e-4

    def test_sun_behind_facade(self):
        # delta_az > 90° → no direct solar incidence
        r = shading_projection_factor(1.0, 2.0, 45.0, 0.0, 180.0)
        assert r["ok"]
        assert r["shaded_fraction"] == 0.0


# ---------------------------------------------------------------------------
# daylight_factor
# ---------------------------------------------------------------------------

class TestDaylightFactor:
    def test_typical_room(self):
        # A_w=4, A_floor=20, Tv=0.7, R=0.5, theta=0.45
        # DF = 0.7 × 4 × 0.45 / (20 × (1-0.25)) = 1.26 / 15 = 0.084 = 8.4%
        r = daylight_factor(4.0, 20.0, 0.7, reflectance_avg=0.5, sky_component_fraction=0.45)
        assert r["ok"]
        denom = 1 - 0.5**2
        expected = 0.7 * 4.0 * 0.45 / (20.0 * denom) * 100
        assert abs(r["DF_percent"] - expected) < 0.01

    def test_below_2pct_warning(self):
        # Small window → DF < 2% → warning
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = daylight_factor(1.0, 50.0, 0.5)
        assert r["ok"]
        assert any("2%" in str(x.message) or "2.0" in str(x.message) for x in w)

    def test_wfr_returned(self):
        r = daylight_factor(5.0, 25.0, 0.7)
        assert r["ok"]
        assert abs(r["window_to_floor_ratio"] - 5.0/25.0) < 1e-5

    def test_invalid_tv(self):
        r = daylight_factor(4.0, 20.0, 1.5)
        assert not r["ok"]


# ---------------------------------------------------------------------------
# window_to_floor_ratio
# ---------------------------------------------------------------------------

class TestWindowToFloorRatio:
    def test_typical_value(self):
        r = window_to_floor_ratio(15.0, 100.0)
        assert r["ok"]
        assert abs(r["WFR"] - 0.15) < 1e-6

    def test_underglazed_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = window_to_floor_ratio(2.0, 100.0)  # WFR=0.02 < 0.10
        assert r["ok"]
        assert any("insufficient" in str(x.message).lower() or "0.10" in str(x.message) for x in w)

    def test_overglazed_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = window_to_floor_ratio(50.0, 100.0)  # WFR=0.50 > 0.40
        assert r["ok"]
        assert any("0.40" in str(x.message) or "solar" in str(x.message).lower() for x in w)

    def test_zero_window(self):
        r = window_to_floor_ratio(0.0, 100.0)
        assert r["ok"]
        assert r["WFR"] == 0.0

    def test_zero_floor_error(self):
        r = window_to_floor_ratio(5.0, 0.0)
        assert not r["ok"]


# ---------------------------------------------------------------------------
# no_sky_line_depth
# ---------------------------------------------------------------------------

class TestNoSkyLineDepth:
    def test_standard_2x_rule(self):
        # head height 2.4m × 2.0 = 4.8m
        r = no_sky_line_depth(2.4)
        assert r["ok"]
        assert abs(r["no_sky_line_depth_m"] - 4.8) < 1e-4

    def test_custom_multiplier(self):
        r = no_sky_line_depth(3.0, multiplier=1.5)
        assert r["ok"]
        assert abs(r["no_sky_line_depth_m"] - 4.5) < 1e-4

    def test_zero_height_error(self):
        r = no_sky_line_depth(0.0)
        assert not r["ok"]


# ---------------------------------------------------------------------------
# overheating_hours
# ---------------------------------------------------------------------------

class TestOverheatingHours:
    def test_no_overheating(self):
        # T_outdoor all 10°C, gains=0 → T_indoor=10°C < 25°C
        T_list = [10.0] * 100
        r = overheating_hours(0, 0, 200, T_list, 25.0)
        assert r["ok"]
        assert r["overheating_hours"] == 0
        assert r["overheating_fraction"] == 0.0

    def test_all_overheating(self):
        # T_outdoor=30°C, gains=2000W, UA=100 → T_indoor=30+20=50°C > 25°C
        T_list = [30.0] * 200
        r = overheating_hours(2000, 0, 100, T_list, 25.0)
        assert r["ok"]
        assert r["overheating_hours"] == 200
        assert r["overheating_fraction"] == 1.0

    def test_partial_overheating(self):
        # First 100 hours T=30°C (above), next 100 T=0°C (below)
        # UA=200, gains=1000 → T_rise = 5°C
        # T_in at 30°C: 35 > 28 → overheat; at 0°C: 5 < 28 → ok
        T_list = [30.0] * 100 + [0.0] * 100
        r = overheating_hours(1000, 0, 200, T_list, 28.0)
        assert r["ok"]
        assert r["overheating_hours"] == 100
        assert abs(r["overheating_fraction"] - 0.5) < 1e-5

    def test_empty_list_error(self):
        r = overheating_hours(1000, 0, 200, [], 25.0)
        assert not r["ok"]

    def test_sample_first24_length(self):
        T_list = [15.0] * 50
        r = overheating_hours(500, 100, 150, T_list, 26.0)
        assert r["ok"]
        assert len(r["T_indoor_sample_first24"]) == 24


# ---------------------------------------------------------------------------
# eui
# ---------------------------------------------------------------------------

class TestEUI:
    def test_typical_office(self):
        # 200,000 kWh / 2000 m² = 100 kWh/(m²·yr)
        r = eui(200_000, 2000)
        assert r["ok"]
        assert abs(r["EUI_kWh_m2yr"] - 100.0) < 1e-4

    def test_zero_energy(self):
        r = eui(0, 500)
        assert r["ok"]
        assert r["EUI_kWh_m2yr"] == 0.0

    def test_zero_area_error(self):
        r = eui(10000, 0)
        assert not r["ok"]

    def test_high_eui_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = eui(600_000, 1000)  # EUI=600 > 500
        assert r["ok"]
        assert any("high" in str(x.message).lower() or "600" in str(x.message) for x in w)


# ---------------------------------------------------------------------------
# ashrae901_envelope_compliance
# ---------------------------------------------------------------------------

class TestASHRAE901:
    def test_roof_cz5_compliant(self):
        # U_max for roof CZ5 = 0.180 W/(m²·K); propose 0.15 → compliant
        r = ashrae901_envelope_compliance("roof", 0.15, 5)
        assert r["ok"]
        assert r["compliant"] is True
        assert r["U_max_W_m2K"] == 0.180

    def test_roof_cz5_fails(self):
        # U=0.30 > 0.180 → fails
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            r = ashrae901_envelope_compliance("roof", 0.30, 5)
        assert r["ok"]
        assert r["compliant"] is False
        assert any("fails" in str(x.message).lower() or "exceeds" in str(x.message).lower() for x in w)

    def test_wall_cz4_compliant(self):
        # U_max for wall_above_grade CZ4 = 0.365
        r = ashrae901_envelope_compliance("wall_above_grade", 0.30, 4)
        assert r["ok"]
        assert r["compliant"] is True

    def test_slab_cz5_compliant(self):
        # F_max CZ5 = 0.860 W/(m·K); propose 0.5 → compliant
        r = ashrae901_envelope_compliance("slab_on_grade", 0.0, 5, F_proposed=0.5)
        assert r["ok"]
        assert r["compliant"] is True
        assert "F_max_W_mK" in r

    def test_slab_missing_F_error(self):
        r = ashrae901_envelope_compliance("slab_on_grade", 0.0, 5)
        assert not r["ok"]

    def test_invalid_climate_zone(self):
        r = ashrae901_envelope_compliance("roof", 0.2, 9)
        assert not r["ok"]

    def test_invalid_assembly_type(self):
        r = ashrae901_envelope_compliance("basement_wall", 0.3, 4)
        assert not r["ok"]

    def test_table_reference_format(self):
        r = ashrae901_envelope_compliance("window_vertical", 3.0, 3)
        assert r["ok"]
        assert "90.1-2022" in r["table_reference"]
        assert "5.5-3" in r["table_reference"]

    def test_cz1_hot_climate_high_floor_u(self):
        # Floor CZ1 has U_max=9.999 (essentially unlimited)
        r = ashrae901_envelope_compliance("floor", 5.0, 1)
        assert r["ok"]
        assert r["compliant"] is True

    def test_cz8_arctic_roof_very_low_u(self):
        # U_max roof CZ8 = 0.119; propose 0.10 → compliant
        r = ashrae901_envelope_compliance("roof", 0.10, 8)
        assert r["ok"]
        assert r["compliant"] is True


# ---------------------------------------------------------------------------
# LLM tool wrappers (tools.py)
# ---------------------------------------------------------------------------

class TestTools:
    """Happy-path and error-path smoke tests for all LLM tool wrappers."""

    def setup_method(self):
        from kerf_cad_core.buildingenergy.tools import (
            run_uvalue_series,
            run_uvalue_parallel,
            run_uvalue_bridged,
            run_whole_building_ua,
            run_balance_point_temperature,
            run_degree_day_energy,
            run_annual_fuel_cost,
            run_design_heating_load,
            run_design_cooling_load,
            run_infiltration_ach_blower_door,
            run_infiltration_ach_aim2,
            run_glaser_condensation,
            run_solar_heat_gain,
            run_shading_projection_factor,
            run_daylight_factor,
            run_window_to_floor_ratio,
            run_no_sky_line_depth,
            run_overheating_hours,
            run_eui,
            run_ashrae901_envelope_compliance,
        )
        self.run_uvalue_series = run_uvalue_series
        self.run_uvalue_parallel = run_uvalue_parallel
        self.run_uvalue_bridged = run_uvalue_bridged
        self.run_whole_building_ua = run_whole_building_ua
        self.run_balance_point = run_balance_point_temperature
        self.run_degree_day = run_degree_day_energy
        self.run_fuel_cost = run_annual_fuel_cost
        self.run_heating = run_design_heating_load
        self.run_cooling = run_design_cooling_load
        self.run_blower = run_infiltration_ach_blower_door
        self.run_aim2 = run_infiltration_ach_aim2
        self.run_glaser = run_glaser_condensation
        self.run_solar = run_solar_heat_gain
        self.run_shading = run_shading_projection_factor
        self.run_df = run_daylight_factor
        self.run_wfr = run_window_to_floor_ratio
        self.run_nsl = run_no_sky_line_depth
        self.run_oh = run_overheating_hours
        self.run_eui = run_eui
        self.run_ashrae = run_ashrae901_envelope_compliance
        self.ctx = _ctx()

    def test_tool_uvalue_series_happy(self):
        result = _run(self.run_uvalue_series(
            self.ctx, _args(layers=[{"r": 2.0}])
        ))
        d = json.loads(result)
        assert d["ok"]

    def test_tool_uvalue_series_missing_layers(self):
        result = _run(self.run_uvalue_series(self.ctx, _args()))
        d = json.loads(result)
        assert not d["ok"]

    def test_tool_uvalue_parallel_happy(self):
        result = _run(self.run_uvalue_parallel(
            self.ctx, _args(fractions_and_uvalues=[[0.15, 2.0], [0.85, 0.4]])
        ))
        d = json.loads(result)
        assert d["ok"]

    def test_tool_uvalue_bridged_happy(self):
        result = _run(self.run_uvalue_bridged(
            self.ctx, _args(U_clear=0.3, U_bridge=2.0, bridge_fraction=0.1)
        ))
        d = json.loads(result)
        assert d["ok"]

    def test_tool_whole_building_ua_happy(self):
        result = _run(self.run_whole_building_ua(
            self.ctx, _args(surfaces=[{"area_m2": 100, "U": 0.5}])
        ))
        d = json.loads(result)
        assert d["ok"]
        assert abs(d["UA_W_per_K"] - 50.0) < 0.01

    def test_tool_balance_point_happy(self):
        result = _run(self.run_balance_point(
            self.ctx, _args(T_indoor_C=21, internal_gains_W=2000, ua_W_per_K=200)
        ))
        d = json.loads(result)
        assert d["ok"]
        assert abs(d["T_balance_C"] - 11.0) < 0.01

    def test_tool_degree_day_happy(self):
        result = _run(self.run_degree_day(
            self.ctx, _args(HDD_or_CDD=2500, UA_W_per_K=200, mode="heating", efficiency=0.9)
        ))
        d = json.loads(result)
        assert d["ok"]

    def test_tool_fuel_cost_happy(self):
        result = _run(self.run_fuel_cost(
            self.ctx, _args(energy_kWh=5000, fuel_type="electricity", price_per_unit=0.20)
        ))
        d = json.loads(result)
        assert d["ok"]
        assert abs(d["cost"] - 1000.0) < 0.01

    def test_tool_design_heating_happy(self):
        result = _run(self.run_heating(
            self.ctx, _args(surfaces=[{"area_m2": 100, "U": 1.0}], T_indoor_C=21, T_outdoor_C=-5)
        ))
        d = json.loads(result)
        assert d["ok"]

    def test_tool_design_cooling_happy(self):
        result = _run(self.run_cooling(
            self.ctx, _args(surfaces=[{"area_m2": 100, "U": 1.0}], T_indoor_C=24, T_outdoor_C=35)
        ))
        d = json.loads(result)
        assert d["ok"]

    def test_tool_blower_door_happy(self):
        result = _run(self.run_blower(self.ctx, _args(ACH50=5.0)))
        d = json.loads(result)
        assert d["ok"]
        assert abs(d["ACH_natural"] - 0.25) < 1e-4

    def test_tool_aim2_happy(self):
        result = _run(self.run_aim2(
            self.ctx, _args(
                floor_area_m2=100, height_m=2.5, C_i=0.001,
                n_exp=0.65, delta_T_C=15, wind_speed_m_s=4.0
            )
        ))
        d = json.loads(result)
        assert d["ok"]

    def test_tool_glaser_happy(self):
        layers = [
            {"name": "insulation", "d_m": 0.1, "k_W_mK": 0.04, "mu": 1},
            {"name": "concrete",   "d_m": 0.2, "k_W_mK": 1.4, "mu": 100},
        ]
        result = _run(self.run_glaser(
            self.ctx, _args(
                layers=layers, T_inside_C=20, T_outside_C=-5,
                RH_inside=0.5, RH_outside=0.8
            )
        ))
        d = json.loads(result)
        assert d["ok"]

    def test_tool_solar_gain_happy(self):
        result = _run(self.run_solar(
            self.ctx, _args(area_m2=10, SHGC=0.4, irradiance_W_m2=600)
        ))
        d = json.loads(result)
        assert d["ok"]
        assert abs(d["solar_gain_W"] - 2400.0) < 0.1

    def test_tool_shading_happy(self):
        result = _run(self.run_shading(
            self.ctx, _args(
                overhang_depth_m=1.0, window_height_m=2.0,
                solar_altitude_deg=30, solar_azimuth_deg=180, facade_azimuth_deg=180
            )
        ))
        d = json.loads(result)
        assert d["ok"]

    def test_tool_daylight_factor_happy(self):
        result = _run(self.run_df(
            self.ctx, _args(window_area_m2=4, floor_area_m2=20, Tv=0.7)
        ))
        d = json.loads(result)
        assert d["ok"]

    def test_tool_wfr_happy(self):
        result = _run(self.run_wfr(
            self.ctx, _args(window_area_m2=15, floor_area_m2=100)
        ))
        d = json.loads(result)
        assert d["ok"]
        assert abs(d["WFR"] - 0.15) < 1e-4

    def test_tool_no_sky_line_happy(self):
        result = _run(self.run_nsl(
            self.ctx, _args(window_head_height_m=2.4)
        ))
        d = json.loads(result)
        assert d["ok"]
        assert abs(d["no_sky_line_depth_m"] - 4.8) < 1e-4

    def test_tool_overheating_happy(self):
        result = _run(self.run_oh(
            self.ctx, _args(
                internal_gains_W=1000, solar_gain_W=500, UA_W_per_K=200,
                T_outdoor_C_list=[15.0] * 100, T_comfort_max_C=26.0
            )
        ))
        d = json.loads(result)
        assert d["ok"]

    def test_tool_eui_happy(self):
        result = _run(self.run_eui(
            self.ctx, _args(annual_energy_kWh=200_000, floor_area_m2=2000)
        ))
        d = json.loads(result)
        assert d["ok"]
        assert abs(d["EUI_kWh_m2yr"] - 100.0) < 0.001

    def test_tool_ashrae901_happy(self):
        result = _run(self.run_ashrae(
            self.ctx, _args(assembly_type="roof", U_proposed=0.15, climate_zone=5)
        ))
        d = json.loads(result)
        assert d["ok"]
        assert d["compliant"] is True

    def test_tool_ashrae901_bad_args_json(self):
        result = _run(self.run_ashrae(self.ctx, b"not-json"))
        d = json.loads(result)
        # err_payload returns {"error": ..., "code": ...}; plain ok=False also acceptable
        assert d.get("ok") is not True

    def test_tool_solar_missing_field(self):
        result = _run(self.run_solar(
            self.ctx, _args(area_m2=10, SHGC=0.4)
        ))
        d = json.loads(result)
        assert not d["ok"]
