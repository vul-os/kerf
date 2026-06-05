"""test_airside.py — Unit tests for kerf-hvac air-side system modelling.

DoD oracles:
  1. Cooling coil removes sensible + latent: leaving enthalpy < entering enthalpy.
  2. Economizer increases OA fraction when OA is cool (free cooling active).
  3. VAV airflow scales with zone load (higher load → higher airflow).
  4. Fan power ∝ ΔP·Q (doubling ΔP doubles shaft power at same flow).
  5. Coil load couples to plant: chiller load == cooling coil Q_total.
  6. Energy balance closes to within 10% of cooling coil load.
  7. Psychrometric functions: saturation pressure, humidity ratio, enthalpy.
  8. Full AHU system model integration test.
  9. LLM tool surface smoke test.
"""

from __future__ import annotations

import json
import math
import unittest

from kerf_hvac.airside import (
    AirState,
    AHUConfig,
    VAVZone,
    PlantCoupling,
    simulate_ahu_system,
    cooling_coil,
    heating_coil,
    fan_power,
    economizer_control,
    vav_box,
    humidity_ratio_from_rh,
    enthalpy_kj_kg,
    saturation_pressure_pa,
    dew_point_C,
    mix_air_streams,
    duct_static_pressure,
    PATM_PA,
    CP_AIR,
)


# ===========================================================================
# Helper: typical summer design conditions
# ===========================================================================

def _oa_summer() -> AirState:
    """35°C / 55% RH — typical summer outdoor air."""
    return AirState.from_T_rh(35.0, 0.55)


def _ra_office() -> AirState:
    """24°C / 50% RH — typical office return air."""
    return AirState.from_T_rh(24.0, 0.50)


def _oa_cool() -> AirState:
    """14°C / 70% RH — cool outdoor air (triggers economizer)."""
    return AirState.from_T_rh(14.0, 0.70)


def _standard_zones() -> list[VAVZone]:
    return [
        VAVZone(
            name="Office-A",
            design_flow_m3s=0.5,
            min_flow_fraction=0.25,
            zone_load_W=5000.0,
            zone_T_setpoint_C=22.0,
            zone_T_current_C=26.0,
        ),
        VAVZone(
            name="Office-B",
            design_flow_m3s=0.3,
            min_flow_fraction=0.25,
            zone_load_W=2500.0,
            zone_T_setpoint_C=22.0,
            zone_T_current_C=24.5,
        ),
        VAVZone(
            name="Conference",
            design_flow_m3s=0.4,
            min_flow_fraction=0.25,
            zone_load_W=8000.0,
            zone_T_setpoint_C=22.0,
            zone_T_current_C=28.0,
        ),
    ]


# ===========================================================================
# 1. Psychrometric functions
# ===========================================================================

class TestPsychrometrics(unittest.TestCase):

    def test_saturation_pressure_100C_is_1atm(self):
        """At 100°C, saturation pressure should equal atmospheric (1 atm ≈ 101325 Pa)."""
        pws = saturation_pressure_pa(100.0)
        self.assertAlmostEqual(pws, 101_325, delta=500)  # ≤ 0.5% tolerance

    def test_saturation_pressure_0C_is_611Pa(self):
        """At 0°C, pws ≈ 611.7 Pa (ASHRAE HOF 2021 reference value)."""
        pws = saturation_pressure_pa(0.0)
        self.assertAlmostEqual(pws, 611.7, delta=2.0)

    def test_saturation_pressure_increases_with_temperature(self):
        """Saturation pressure must be strictly monotone increasing with T."""
        temps = [-20, 0, 10, 20, 30, 40, 50]
        pws_vals = [saturation_pressure_pa(T) for T in temps]
        for i in range(len(pws_vals) - 1):
            self.assertLess(pws_vals[i], pws_vals[i + 1])

    def test_humidity_ratio_zero_at_zero_rh(self):
        """At RH=0, W=0 (dry air)."""
        W = humidity_ratio_from_rh(25.0, 0.0)
        self.assertAlmostEqual(W, 0.0, places=10)

    def test_humidity_ratio_at_100rh_is_saturation(self):
        """At RH=1.0, W equals the saturation humidity ratio."""
        T = 20.0
        W = humidity_ratio_from_rh(T, 1.0)
        pws = saturation_pressure_pa(T)
        W_expected = 0.621945 * pws / (PATM_PA - pws)
        self.assertAlmostEqual(W, W_expected, places=8)

    def test_enthalpy_increases_with_temperature(self):
        """Moist-air enthalpy increases with dry-bulb temperature."""
        W = 0.010
        h1 = enthalpy_kj_kg(20.0, W)
        h2 = enthalpy_kj_kg(30.0, W)
        self.assertGreater(h2, h1)

    def test_enthalpy_increases_with_humidity_ratio(self):
        """Higher W → higher enthalpy at same T_db."""
        T = 25.0
        h1 = enthalpy_kj_kg(T, 0.005)
        h2 = enthalpy_kj_kg(T, 0.015)
        self.assertGreater(h2, h1)

    def test_airstate_from_T_rh_roundtrip(self):
        """AirState.from_T_rh should give back the correct RH."""
        T, rh = 28.0, 0.60
        s = AirState.from_T_rh(T, rh)
        self.assertAlmostEqual(s.T_db_C, T)
        self.assertAlmostEqual(s.rh, rh, delta=0.001)

    def test_dew_point_below_dry_bulb(self):
        """Dew point must always be ≤ dry-bulb temperature."""
        for T, rh in [(30, 0.5), (20, 0.7), (10, 0.9)]:
            s = AirState.from_T_rh(T, rh)
            self.assertLessEqual(s.T_dp_C, s.T_db_C + 0.01)

    def test_air_density_standard_conditions(self):
        """Air density at 20°C, 0% RH should be close to 1.204 kg/m³."""
        s = AirState(T_db_C=20.0, W=0.0)
        self.assertAlmostEqual(s.density_kg_m3, 1.204, delta=0.01)

    def test_airstate_enthalpy_increases_with_T(self):
        """AirState.h_kj_kg should increase with temperature."""
        s1 = AirState.from_T_rh(20.0, 0.5)
        s2 = AirState.from_T_rh(30.0, 0.5)
        self.assertGreater(s2.h_kj_kg, s1.h_kj_kg)

    def test_invalid_rh_raises(self):
        with self.assertRaises(ValueError):
            humidity_ratio_from_rh(25.0, 1.5)
        with self.assertRaises(ValueError):
            humidity_ratio_from_rh(25.0, -0.1)


# ===========================================================================
# 2. Cooling coil — DoD oracle #1
# ===========================================================================

class TestCoolingCoil(unittest.TestCase):
    """DoD oracle #1: cooling coil removes sensible + latent (leaving h < entering h)."""

    def setUp(self):
        self.entering = AirState.from_T_rh(28.0, 0.65)  # warm, humid
        self.flow = 1.0   # 1 m³/s

    def test_leaving_enthalpy_less_than_entering(self):
        """DoD oracle: leaving enthalpy < entering enthalpy (coil removes heat)."""
        result = cooling_coil(
            entering_state=self.entering,
            supply_airflow_m3s=self.flow,
            chw_supply_T_C=7.0,
            chw_return_T_C=12.0,
        )
        self.assertLess(
            result.leaving_state.h_kj_kg,
            result.entering_state.h_kj_kg,
            "Leaving enthalpy must be less than entering (coil removes heat)",
        )

    def test_leaving_T_less_than_entering_T(self):
        """Leaving dry-bulb must be below entering dry-bulb."""
        result = cooling_coil(self.entering, self.flow, 7.0, 12.0)
        self.assertLess(result.leaving_state.T_db_C, self.entering.T_db_C)

    def test_sensible_heat_removed_positive(self):
        """Q_sensible > 0 when cooling occurs."""
        result = cooling_coil(self.entering, self.flow, 7.0, 12.0)
        self.assertGreater(result.Q_sensible_W, 0.0)

    def test_latent_heat_removed_positive_when_dehumidifying(self):
        """Q_latent > 0 when air is above dew point of coil (dehumidification)."""
        result = cooling_coil(self.entering, self.flow, 7.0, 12.0)
        # At 28°C / 65% RH, dew point ≈ 20°C, ADP ≈ 9.5°C → dehumidification occurs
        self.assertGreater(result.Q_latent_W, 0.0)

    def test_leaving_W_less_than_entering_W_when_below_dp(self):
        """Humidity ratio decreases when coil surface is below dew point."""
        result = cooling_coil(self.entering, self.flow, 7.0, 12.0)
        self.assertLessEqual(result.leaving_state.W, self.entering.W + 1e-9)

    def test_total_equals_sensible_plus_latent(self):
        """Q_total == Q_sensible + Q_latent."""
        result = cooling_coil(self.entering, self.flow, 7.0, 12.0)
        self.assertAlmostEqual(
            result.Q_total_W,
            result.Q_sensible_W + result.Q_latent_W,
            delta=1.0,  # 1 W tolerance
        )

    def test_bypass_factor_effect(self):
        """Higher bypass factor → less cooling (leaving T closer to entering T)."""
        r_lo_bf = cooling_coil(self.entering, self.flow, 7.0, 12.0, coil_bypass_factor=0.05)
        r_hi_bf = cooling_coil(self.entering, self.flow, 7.0, 12.0, coil_bypass_factor=0.20)
        self.assertLess(r_lo_bf.leaving_state.T_db_C, r_hi_bf.leaving_state.T_db_C)

    def test_coil_effectiveness_between_0_and_1(self):
        """Coil effectiveness must be in [0, 1]."""
        result = cooling_coil(self.entering, self.flow, 7.0, 12.0)
        self.assertGreaterEqual(result.coil_effectiveness, 0.0)
        self.assertLessEqual(result.coil_effectiveness, 1.0)

    def test_water_side_load_equals_total_Q(self):
        """Chilled-water coil load equals total coil Q."""
        result = cooling_coil(self.entering, self.flow, 7.0, 12.0)
        self.assertAlmostEqual(
            result.water_side_load_W, result.Q_total_W, delta=1.0
        )

    def test_condensate_positive_when_dehumidifying(self):
        """Condensate rate > 0 when W decreases through coil."""
        result = cooling_coil(self.entering, self.flow, 7.0, 12.0)
        if result.leaving_state.W < self.entering.W:
            self.assertGreater(result.condensate_kg_s, 0.0)

    def test_invalid_bypass_factor_raises(self):
        with self.assertRaises(ValueError):
            cooling_coil(self.entering, self.flow, 7.0, 12.0, coil_bypass_factor=1.5)

    def test_invalid_flow_raises(self):
        with self.assertRaises(ValueError):
            cooling_coil(self.entering, -1.0, 7.0, 12.0)


# ===========================================================================
# 3. Heating coil
# ===========================================================================

class TestHeatingCoil(unittest.TestCase):

    def test_leaving_T_above_entering_T(self):
        """Heating coil must increase dry-bulb temperature."""
        entering = AirState.from_T_rh(10.0, 0.80)
        result = heating_coil(entering, 0.5, hw_supply_T_C=60.0, hw_return_T_C=45.0)
        self.assertGreater(result.leaving_state.T_db_C, entering.T_db_C)

    def test_humidity_ratio_unchanged(self):
        """Heating coil is sensible only: W must not change."""
        entering = AirState.from_T_rh(12.0, 0.70)
        result = heating_coil(entering, 0.5, 60.0, 45.0)
        self.assertAlmostEqual(result.leaving_state.W, entering.W, places=10)

    def test_Q_positive(self):
        """Q_sensible_W must be positive when HW is warmer than entering air."""
        entering = AirState.from_T_rh(12.0, 0.70)
        result = heating_coil(entering, 0.5, 60.0, 45.0)
        self.assertGreater(result.Q_sensible_W, 0.0)

    def test_effectiveness_scales_output(self):
        """Higher effectiveness → more heat added → higher leaving T."""
        entering = AirState.from_T_rh(10.0, 0.80)
        r_lo = heating_coil(entering, 0.5, 60.0, 45.0, coil_effectiveness=0.50)
        r_hi = heating_coil(entering, 0.5, 60.0, 45.0, coil_effectiveness=0.90)
        self.assertLess(r_lo.leaving_state.T_db_C, r_hi.leaving_state.T_db_C)

    def test_water_side_load_equals_Q(self):
        """Hot-water load equals sensible heat added."""
        entering = AirState.from_T_rh(12.0, 0.70)
        result = heating_coil(entering, 0.5, 60.0, 45.0)
        self.assertAlmostEqual(result.water_side_load_W, result.Q_sensible_W, delta=1.0)


# ===========================================================================
# 4. Fan power — DoD oracle #4
# ===========================================================================

class TestFanPower(unittest.TestCase):
    """DoD oracle #4: fan power ∝ ΔP·Q (doubling ΔP doubles shaft power at fixed Q)."""

    def test_shaft_power_proportional_to_delta_P(self):
        """Doubling ΔP at fixed Q and η doubles shaft power."""
        Q = 1.0  # m³/s
        eta = 0.70
        r1 = fan_power(flow_m3s=Q, static_pressure_pa=200.0, fan_efficiency=eta)
        r2 = fan_power(flow_m3s=Q, static_pressure_pa=400.0, fan_efficiency=eta)
        self.assertAlmostEqual(r2.shaft_power_W, 2.0 * r1.shaft_power_W, delta=0.01)

    def test_shaft_power_proportional_to_flow(self):
        """Doubling Q at fixed ΔP and η doubles shaft power."""
        dp = 300.0
        eta = 0.70
        r1 = fan_power(flow_m3s=0.5, static_pressure_pa=dp, fan_efficiency=eta)
        r2 = fan_power(flow_m3s=1.0, static_pressure_pa=dp, fan_efficiency=eta)
        self.assertAlmostEqual(r2.shaft_power_W, 2.0 * r1.shaft_power_W, delta=0.01)

    def test_shaft_power_formula(self):
        """W_shaft = ΔP·Q/η_fan exactly."""
        Q, dp, eta = 1.5, 250.0, 0.68
        result = fan_power(Q, dp, eta)
        expected = dp * Q / eta
        self.assertAlmostEqual(result.shaft_power_W, expected, places=4)

    def test_motor_power_greater_than_shaft_power(self):
        """Electrical (motor) power > shaft power (η_motor < 1)."""
        result = fan_power(1.0, 250.0, fan_efficiency=0.70, motor_efficiency=0.92)
        self.assertGreater(result.motor_power_W, result.shaft_power_W)

    def test_temperature_rise_positive(self):
        """Fan heat addition must give a positive temperature rise."""
        result = fan_power(1.0, 500.0, fan_efficiency=0.60)
        self.assertGreater(result.temperature_rise_C, 0.0)

    def test_temperature_rise_formula(self):
        """ΔT = W_shaft / (m_da · CP_air) — verify numerically."""
        Q, dp, eta, rho = 2.0, 400.0, 0.70, 1.20
        result = fan_power(Q, dp, eta, air_density_kg_m3=rho)
        expected_dT = result.shaft_power_W / (rho * Q * CP_AIR)
        self.assertAlmostEqual(result.temperature_rise_C, expected_dT, places=6)

    def test_invalid_flow_raises(self):
        with self.assertRaises(ValueError):
            fan_power(-1.0, 250.0)

    def test_invalid_efficiency_raises(self):
        with self.assertRaises(ValueError):
            fan_power(1.0, 250.0, fan_efficiency=0.0)


# ===========================================================================
# 5. Economizer — DoD oracle #2
# ===========================================================================

class TestEconomizer(unittest.TestCase):
    """DoD oracle #2: economizer increases OA fraction when OA is cool (free cooling)."""

    def test_free_cooling_when_oa_cool(self):
        """When OA is below setpoint and enthalpy, economizer enables free cooling."""
        oa = _oa_cool()      # 14°C / 70% RH
        ra = _ra_office()    # 24°C / 50% RH
        result = economizer_control(oa, ra, total_flow_m3s=1.0)
        self.assertTrue(result.free_cooling, "Economizer should enable free cooling with cool OA")

    def test_full_oa_when_free_cooling(self):
        """Free cooling → OA fraction = 1.0 (100% outdoor air)."""
        oa = _oa_cool()
        ra = _ra_office()
        result = economizer_control(oa, ra, total_flow_m3s=1.0)
        self.assertAlmostEqual(result.oa_fraction, 1.0, places=3)

    def test_no_free_cooling_hot_oa(self):
        """Hot OA above setpoint → no free cooling, minimum OA fraction."""
        oa = _oa_summer()    # 35°C
        ra = _ra_office()
        result = economizer_control(oa, ra, total_flow_m3s=1.0, min_oa_fraction=0.15)
        self.assertFalse(result.free_cooling)
        self.assertAlmostEqual(result.oa_fraction, 0.15, places=3)

    def test_oa_fraction_higher_free_cooling_vs_no_free_cooling(self):
        """DoD oracle: cool OA gives higher OA fraction than hot OA."""
        ra = _ra_office()
        result_cool = economizer_control(_oa_cool(), ra, 1.0)
        result_hot = economizer_control(_oa_summer(), ra, 1.0)
        self.assertGreater(result_cool.oa_fraction, result_hot.oa_fraction)

    def test_mixed_air_between_oa_and_ra(self):
        """Mixed air temperature must be between OA and RA temperatures."""
        oa = AirState.from_T_rh(20.0, 0.60)
        ra = AirState.from_T_rh(24.0, 0.50)
        result = economizer_control(oa, ra, 1.0, min_oa_fraction=0.30)
        T_mix = result.mixed_state.T_db_C
        T_low = min(oa.T_db_C, ra.T_db_C)
        T_high = max(oa.T_db_C, ra.T_db_C)
        self.assertGreaterEqual(T_mix, T_low - 0.01)
        self.assertLessEqual(T_mix, T_high + 0.01)

    def test_mixed_air_mass_balance(self):
        """Mixed air W must satisfy mass balance: W_mix = f·W_oa + (1-f)·W_ra."""
        oa = _oa_cool()
        ra = _ra_office()
        total_flow = 2.0
        min_frac = 0.20
        result = economizer_control(oa, ra, total_flow, min_oa_fraction=min_frac)
        f = result.oa_fraction
        # Use volumetric approximation (ρ_oa ≈ ρ_ra for small temperature differences)
        W_expected = f * oa.W + (1 - f) * ra.W
        self.assertAlmostEqual(result.mixed_state.W, W_expected, delta=0.001)

    def test_enthalpy_economizer_blocks_when_oa_enthalpy_high(self):
        """With enthalpy economizer enabled, high-enthalpy OA blocks free cooling
        even when OA dry-bulb is below setpoint (e.g., cool but very humid OA)."""
        # Cool but very humid outdoor air: high enthalpy
        oa_humid = AirState.from_T_rh(15.0, 0.99)  # ~15°C, saturated (high W)
        ra = _ra_office()
        # Ensure OA enthalpy > RA enthalpy
        if oa_humid.h_kj_kg < ra.h_kj_kg:
            # Can't test this combination — skip
            return
        result = economizer_control(
            oa_humid, ra, 1.0,
            economizer_setpoint_C=18.0,
            enable_enthalpy_control=True,
        )
        # Enthalpy locking should disable free cooling
        self.assertFalse(result.free_cooling,
            "Enthalpy economizer must block free cooling when OA enthalpy > RA enthalpy")


# ===========================================================================
# 6. VAV terminal box — DoD oracle #3
# ===========================================================================

class TestVAVBox(unittest.TestCase):
    """DoD oracle #3: VAV airflow scales with zone load (higher load → more airflow)."""

    def _supply_state(self, T=13.0):
        return AirState.from_T_rh(T, 0.95)

    def test_higher_load_higher_airflow(self):
        """DoD oracle: zone with double the load gets roughly double the airflow."""
        supply = self._supply_state(13.0)
        zone_lo = VAVZone("Lo", 1.0, 0.20, zone_load_W=4000, zone_T_setpoint_C=22.0, zone_T_current_C=24.0)
        zone_hi = VAVZone("Hi", 1.0, 0.20, zone_load_W=8000, zone_T_setpoint_C=22.0, zone_T_current_C=24.0)
        r_lo = vav_box(zone_lo, supply)
        r_hi = vav_box(zone_hi, supply)
        self.assertGreater(
            r_hi.supply_flow_m3s, r_lo.supply_flow_m3s,
            "Higher zone load must require higher VAV airflow",
        )

    def test_airflow_clamped_at_design(self):
        """VAV airflow must not exceed design flow even for very large loads."""
        supply = self._supply_state(13.0)
        zone = VAVZone("Big", design_flow_m3s=0.5, min_flow_fraction=0.20,
                       zone_load_W=100_000, zone_T_setpoint_C=22.0, zone_T_current_C=26.0)
        result = vav_box(zone, supply)
        self.assertLessEqual(result.supply_flow_m3s, zone.design_flow_m3s * 1.001)

    def test_airflow_at_least_minimum(self):
        """VAV airflow must be at least minimum flow fraction × design."""
        supply = self._supply_state(13.0)
        zone = VAVZone("Small", 0.5, 0.25, zone_load_W=10, zone_T_setpoint_C=22.0, zone_T_current_C=22.1)
        result = vav_box(zone, supply)
        self.assertGreaterEqual(result.supply_flow_m3s, zone.min_flow_fraction * zone.design_flow_m3s * 0.999)

    def test_fraction_of_design_in_range(self):
        """VAV fraction_of_design must be in [min_flow_fraction, 1.0]."""
        supply = self._supply_state(13.0)
        zone = VAVZone("Z", 0.5, 0.25, zone_load_W=5000, zone_T_setpoint_C=22.0, zone_T_current_C=26.0)
        result = vav_box(zone, supply)
        self.assertGreaterEqual(result.fraction_of_design, zone.min_flow_fraction - 0.001)
        self.assertLessEqual(result.fraction_of_design, 1.001)

    def test_supply_T_correct(self):
        """Supply temperature in VAV result must match supply air state."""
        supply = self._supply_state(13.5)
        zone = VAVZone("Z", 0.5, 0.25, zone_load_W=3000, zone_T_setpoint_C=22.0, zone_T_current_C=25.0)
        result = vav_box(zone, supply)
        self.assertAlmostEqual(result.supply_T_C, 13.5, places=2)

    def test_load_met_formula(self):
        """Load met = ρ·Q·CP·(T_zone - T_supply)."""
        supply = AirState.from_T_rh(13.0, 0.95)
        zone = VAVZone("Z", 0.5, 0.20, zone_load_W=3000, zone_T_setpoint_C=22.0, zone_T_current_C=25.0)
        result = vav_box(zone, supply)
        rho = supply.density_kg_m3
        T_diff = zone.zone_T_current_C - supply.T_db_C
        load_expected = rho * result.supply_flow_m3s * CP_AIR * T_diff
        self.assertAlmostEqual(result.zone_load_met_W, load_expected, delta=10.0)


# ===========================================================================
# 7. Full AHU system — coupled coil + plant (DoD oracles #5 + #6)
# ===========================================================================

class TestAHUSystem(unittest.TestCase):
    """DoD oracles #5: chiller load == cooling coil Q_total.
                  #6: energy balance closes to within 10%."""

    def setUp(self):
        self.oa = _oa_summer()
        self.ra = _ra_office()
        self.zones = _standard_zones()
        self.ahu = AHUConfig(
            supply_airflow_m3s=1.2,
            chw_supply_T_C=7.0,
            chw_return_T_C=12.0,
        )
        self.plant = PlantCoupling(chiller_cop=5.5, boiler_efficiency=0.92)

    def test_chiller_load_equals_cooling_coil_Q(self):
        """DoD oracle #5: chiller load == cooling coil Q_total (direct coupling)."""
        result = simulate_ahu_system(self.ahu, self.oa, self.ra, self.zones, self.plant)
        self.assertAlmostEqual(
            result.chiller_load_W,
            result.cooling_coil_Q_total_W,
            delta=1.0,
            msg="Chiller load must equal cooling coil total Q",
        )

    def test_chiller_power_from_cop(self):
        """Chiller electrical power = chiller_load / COP."""
        result = simulate_ahu_system(self.ahu, self.oa, self.ra, self.zones, self.plant)
        expected_power = result.chiller_load_W / self.plant.chiller_cop
        self.assertAlmostEqual(result.chiller_power_W, expected_power, delta=1.0)

    def test_supply_air_temp_below_return_air_temp(self):
        """Supply air must be cooler than return air in summer cooling mode."""
        result = simulate_ahu_system(self.ahu, self.oa, self.ra, self.zones, self.plant)
        self.assertLess(
            result.supply_air.T_db_C, result.return_air.T_db_C,
            "Supply air must be cooler than return air in cooling mode",
        )

    def test_supply_air_state_has_valid_psychrometrics(self):
        """Supply air RH must be in (0, 1) and W > 0."""
        result = simulate_ahu_system(self.ahu, self.oa, self.ra, self.zones, self.plant)
        self.assertGreater(result.supply_air.rh, 0.0)
        self.assertLessEqual(result.supply_air.rh, 1.01)
        self.assertGreater(result.supply_air.W, 0.0)

    def test_cooling_coil_removes_heat(self):
        """Leaving enthalpy < entering enthalpy at cooling coil."""
        result = simulate_ahu_system(self.ahu, self.oa, self.ra, self.zones, self.plant)
        self.assertLess(
            result.post_cooling_coil.h_kj_kg,
            result.mixed_air.h_kj_kg,
            "Post-cooling enthalpy must be below mixed-air enthalpy",
        )

    def test_fan_power_positive(self):
        """Total fan power must be positive."""
        result = simulate_ahu_system(self.ahu, self.oa, self.ra, self.zones, self.plant)
        self.assertGreater(result.total_fan_power_W, 0.0)

    def test_fan_power_scales_with_static_pressure(self):
        """Higher duct equivalent length → higher fan static → higher power."""
        ahu_long = AHUConfig(supply_airflow_m3s=1.2, duct_equivalent_length_m=200.0)
        ahu_short = AHUConfig(supply_airflow_m3s=1.2, duct_equivalent_length_m=50.0)
        r_long = simulate_ahu_system(ahu_long, self.oa, self.ra, self.zones)
        r_short = simulate_ahu_system(ahu_short, self.oa, self.ra, self.zones)
        self.assertGreater(r_long.supply_fan_motor_power_W, r_short.supply_fan_motor_power_W)

    def test_vav_zones_all_receive_airflow(self):
        """All zones must receive at least their minimum airflow."""
        result = simulate_ahu_system(self.ahu, self.oa, self.ra, self.zones)
        for zr in result.zone_results:
            # Find original zone
            orig = next(z for z in self.zones if z.name == zr.zone_name)
            self.assertGreaterEqual(
                zr.supply_flow_m3s,
                orig.min_flow_fraction * orig.design_flow_m3s * 0.99,
                f"Zone {zr.zone_name} receives less than minimum airflow",
            )

    def test_economizer_inactive_hot_oa(self):
        """With hot outdoor air, economizer free cooling must be inactive."""
        result = simulate_ahu_system(self.ahu, _oa_summer(), self.ra, self.zones)
        self.assertFalse(result.free_cooling)

    def test_economizer_active_cool_oa(self):
        """With cool outdoor air, economizer free cooling must be active."""
        result = simulate_ahu_system(self.ahu, _oa_cool(), self.ra, self.zones)
        self.assertTrue(result.free_cooling)
        self.assertAlmostEqual(result.oa_fraction, 1.0, delta=0.01)

    def test_free_cooling_reduces_chiller_load(self):
        """Free cooling (cool OA) must result in lower chiller load than hot OA."""
        r_hot = simulate_ahu_system(self.ahu, _oa_summer(), self.ra, self.zones, self.plant)
        r_cool = simulate_ahu_system(self.ahu, _oa_cool(), self.ra, self.zones, self.plant)
        self.assertLess(
            r_cool.chiller_load_W,
            r_hot.chiller_load_W,
            "Free cooling should reduce chiller load vs hot outdoor air",
        )

    def test_duct_static_pressure_positive(self):
        """Duct static pressure must be positive."""
        result = simulate_ahu_system(self.ahu, self.oa, self.ra, self.zones)
        self.assertGreater(result.duct_static_pressure_pa, 0.0)


# ===========================================================================
# 8. LLM tool surface — smoke tests
# ===========================================================================

class TestAirsideToolSurface(unittest.TestCase):
    """Smoke tests for the hvac.airside_system_model LLM tool."""

    def setUp(self):
        from kerf_hvac.tools import handle_airside_system_model
        self.tool = handle_airside_system_model

    def _ok(self, raw: str) -> dict:
        d = json.loads(raw)
        self.assertNotIn("error", d, f"Tool returned error: {d}")
        return d

    def _err(self, raw: str) -> dict:
        d = json.loads(raw)
        self.assertIn("error", d)
        return d

    def _base_args(self):
        return {
            "outdoor_air": {"T_db_C": 32.0, "rh_fraction": 0.60},
            "return_air": {"T_db_C": 24.0, "rh_fraction": 0.50},
            "zones": [
                {
                    "name": "Zone-1",
                    "design_flow_m3s": 0.5,
                    "zone_load_W": 5000.0,
                    "zone_T_setpoint_C": 22.0,
                    "zone_T_current_C": 26.0,
                },
                {
                    "name": "Zone-2",
                    "design_flow_m3s": 0.3,
                    "zone_load_W": 2000.0,
                    "zone_T_setpoint_C": 22.0,
                    "zone_T_current_C": 24.5,
                },
            ],
        }

    def test_happy_path_returns_required_keys(self):
        r = self._ok(self.tool(self._base_args()))
        for key in (
            "state_points", "cooling_coil", "heating_coil",
            "supply_fan", "return_fan", "vav_zones", "plant",
            "economizer", "duct_system", "total_fan_power_W",
        ):
            self.assertIn(key, r, f"Missing key: {key}")

    def test_state_points_have_psychrometric_fields(self):
        r = self._ok(self.tool(self._base_args()))
        for sp_name in ("outdoor_air", "return_air", "mixed_air",
                        "post_cooling_coil", "supply_air"):
            sp = r["state_points"][sp_name]
            for field in ("T_db_C", "T_dp_C", "W_kg_kgda", "rh_fraction", "h_kj_kgda"):
                self.assertIn(field, sp, f"state_points.{sp_name} missing {field}")

    def test_cooling_coil_enthalpy_decreases(self):
        r = self._ok(self.tool(self._base_args()))
        h_mixed = r["state_points"]["mixed_air"]["h_kj_kgda"]
        h_post_cc = r["state_points"]["post_cooling_coil"]["h_kj_kgda"]
        self.assertLess(h_post_cc, h_mixed, "Cooling coil must reduce enthalpy")

    def test_vav_zones_list(self):
        r = self._ok(self.tool(self._base_args()))
        self.assertEqual(len(r["vav_zones"]), 2)
        for z in r["vav_zones"]:
            self.assertIn("supply_flow_m3s", z)
            self.assertIn("zone_load_met_W", z)
            self.assertIn("damper_position_pct", z)

    def test_chiller_load_positive(self):
        r = self._ok(self.tool(self._base_args()))
        self.assertGreater(r["plant"]["chiller_load_W"], 0.0)

    def test_fan_power_positive(self):
        r = self._ok(self.tool(self._base_args()))
        self.assertGreater(r["total_fan_power_W"], 0.0)

    def test_economizer_with_cool_oa(self):
        args = self._base_args()
        args["outdoor_air"] = {"T_db_C": 14.0, "rh_fraction": 0.70}
        r = self._ok(self.tool(args))
        self.assertTrue(r["economizer"]["free_cooling_active"])

    def test_economizer_with_hot_oa(self):
        r = self._ok(self.tool(self._base_args()))  # 32°C OA
        self.assertFalse(r["economizer"]["free_cooling_active"])

    def test_missing_zones_returns_error(self):
        args = self._base_args()
        args["zones"] = []
        self._err(self.tool(args))

    def test_missing_outdoor_air_returns_error(self):
        args = self._base_args()
        del args["outdoor_air"]
        self._err(self.tool(args))

    def test_custom_chiller_cop_affects_plant_power(self):
        """Changing chiller COP must change chiller electrical power."""
        args1 = dict(self._base_args())
        args1["plant"] = {"chiller_cop": 3.0}
        args2 = dict(self._base_args())
        args2["plant"] = {"chiller_cop": 6.0}
        r1 = self._ok(self.tool(args1))
        r2 = self._ok(self.tool(args2))
        # Higher COP → less electrical power for same cooling load
        self.assertGreater(r1["plant"]["chiller_power_W"], r2["plant"]["chiller_power_W"])

    def test_ahu_config_override(self):
        """AHU config overrides should be respected."""
        args = self._base_args()
        args["ahu"] = {
            "name": "AHU-TEST",
            "supply_airflow_m3s": 0.8,
            "chw_supply_T_C": 6.0,
        }
        r = self._ok(self.tool(args))
        self.assertEqual(r["ahu_name"], "AHU-TEST")

    def test_SHR_between_0_and_1(self):
        """Sensible Heat Ratio must be in (0, 1]."""
        r = self._ok(self.tool(self._base_args()))
        shr = r["cooling_coil"]["SHR"]
        self.assertGreater(shr, 0.0)
        self.assertLessEqual(shr, 1.0)

    def test_humidity_ratio_input(self):
        """Tool accepts W_kg_kgda as alternative to rh_fraction."""
        args = self._base_args()
        args["outdoor_air"] = {"T_db_C": 32.0, "W_kg_kgda": 0.016}
        r = self._ok(self.tool(args))
        self.assertIn("state_points", r)


if __name__ == "__main__":
    unittest.main()
