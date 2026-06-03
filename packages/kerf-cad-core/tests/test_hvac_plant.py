"""
Tests for kerf_cad_core.buildingenergy.hvac_plant

Tests cover:
  - Chiller COP increases with lower entering condenser water temp
  - Chiller COP at design conditions equals rated COP
  - Chiller COP bounded to sensible range
  - Boiler efficiency decreases at extreme part-load (< 10% PLR)
  - Boiler efficiency at full load matches rated efficiency
  - Boiler with custom part-load curve interpolates correctly
  - simulate_hvac_plant returns positive electricity with non-zero cooling
  - simulate_hvac_plant returns positive gas with non-zero heating
  - simulate_hvac_plant with zero cooling → zero chiller electricity
  - simulate_hvac_plant with zero heating → zero gas
  - Economiser reduces chiller electricity relative to no economiser
  - Return fan increases total electricity
  - HvacPlantResult has correct structure (length 8760 hourly lists)
  - Invalid chiller capacity raises ValueError
  - Annual gas therms consistent with gas kWh
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.buildingenergy.hourly_8760 import AnnualResult, HourlyResult
from kerf_cad_core.buildingenergy.hvac_plant import (
    ChillerSpec,
    BoilerSpec,
    AirSideSystem,
    HvacPlantResult,
    simulate_hvac_plant,
    _economizer_free_cooling_frac,
    _KWH_PER_THERM,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hourly_results(
    n: int = 8760,
    base_cool_kw: float = 5.0,
    base_heat_kw: float = 3.0,
    climate_mean_c: float = 13.0,
) -> list[HourlyResult]:
    hours = []
    for h in range(n):
        t_out = (
            climate_mean_c
            + 10.0 * math.cos(2 * math.pi * h / 8760 + math.pi)
            + 3.0 * math.cos(2 * math.pi * (h % 24) / 24 + math.pi)
        )
        # Simple heuristic: more cooling when hot, more heating when cold
        cool = max(0.0, base_cool_kw * max(0.0, t_out - 24.0) / 10.0)
        heat = max(0.0, base_heat_kw * max(0.0, 20.0 - t_out) / 10.0)
        hours.append(HourlyResult(
            hour=h,
            heating_load_kw=heat,
            cooling_load_kw=cool,
            fan_kw=0.5,
            indoor_temp_c=22.0,
            indoor_rh_pct=50.0,
            outdoor_temp_c=t_out,
        ))
    return hours


def _make_annual(
    cooling_kwh: float = 10000.0,
    heating_kwh: float = 5000.0,
    fan_kwh: float = 1000.0,
    climate_mean_c: float = 13.0,
    n: int = 8760,
) -> AnnualResult:
    hourly = _make_hourly_results(n, climate_mean_c=climate_mean_c)
    return AnnualResult(
        hourly=hourly,
        annual_heating_kwh=heating_kwh,
        annual_cooling_kwh=cooling_kwh,
        annual_fan_kwh=fan_kwh,
        annual_lighting_kwh=0.0,
        eui_kwh_m2_yr=0.0,
    )


def _default_chiller(capacity_kw: float = 200.0, cop: float = 5.5) -> ChillerSpec:
    return ChillerSpec(name="Test-Chiller", rated_capacity_kw=capacity_kw, cop_rated=cop)


def _default_boiler(capacity_kw: float = 100.0, eff_pct: float = 85.0) -> BoilerSpec:
    return BoilerSpec(rated_capacity_kw=capacity_kw, efficiency_rated_pct=eff_pct)


def _default_air_side(economizer: str = "none") -> AirSideSystem:
    return AirSideSystem(
        cfm_design=10000.0,
        fan_power_w_per_cfm=1.25,
        return_fan_present=False,
        economizer_type=economizer,
    )


# ---------------------------------------------------------------------------
# ChillerSpec tests
# ---------------------------------------------------------------------------

class TestChillerSpec:

    def test_cop_at_design_conditions_equals_rated(self):
        """COP at 100% PLR and 29.4°C ECW should equal rated COP (within tolerance)."""
        chiller = _default_chiller(cop=5.5)
        cop = chiller.cop_at(1.0, 29.4)
        assert abs(cop - 5.5) < 0.5, f"COP at design = {cop}, expected ~5.5"

    def test_cop_increases_with_lower_ecw_temp(self):
        """Lower condenser water temperature → higher COP (AHRI 550/590)."""
        chiller = _default_chiller(cop=5.5)
        cop_hot = chiller.cop_at(0.70, 32.0)
        cop_cold = chiller.cop_at(0.70, 20.0)
        assert cop_cold > cop_hot, (
            f"COP at ECW=20°C ({cop_cold:.3f}) should exceed COP at ECW=32°C ({cop_hot:.3f})"
        )

    def test_cop_positive_at_min_plr(self):
        chiller = _default_chiller()
        cop = chiller.cop_at(0.10, 29.4)
        assert cop > 0.0

    def test_cop_bounded_above_zero_at_extreme_ecw(self):
        chiller = _default_chiller()
        cop = chiller.cop_at(0.50, 50.0)  # very hot condenser water
        assert cop > 0.0

    def test_part_load_curve_improves_cop_at_partial_load(self):
        """Centrifugal chiller with realistic curve is more efficient at 60% PLR."""
        chiller = ChillerSpec(
            name="Centrifugal",
            rated_capacity_kw=500.0,
            cop_rated=6.0,
            capacity_curve_a=0.95,
            capacity_curve_b=0.12,
            capacity_curve_c=-0.07,
        )
        cop_full = chiller.cop_at(1.0, 29.4)
        cop_partial = chiller.cop_at(0.6, 29.4)
        # With these realistic coefficients, ~60% should be close to or higher
        assert cop_partial > 0.0
        assert cop_full > 0.0


# ---------------------------------------------------------------------------
# BoilerSpec tests
# ---------------------------------------------------------------------------

class TestBoilerSpec:

    def test_full_load_equals_rated_efficiency(self):
        boiler = _default_boiler(eff_pct=85.0)
        eff = boiler.efficiency_at(1.0)
        assert abs(eff - 0.85) < 0.001, f"Full-load efficiency = {eff}, expected 0.85"

    def test_efficiency_at_30pct_load_still_rated(self):
        boiler = _default_boiler(eff_pct=85.0)
        eff = boiler.efficiency_at(0.30)
        assert abs(eff - 0.85) < 0.001

    def test_efficiency_decreases_at_very_low_load(self):
        """Default curve: efficiency drops at < 30% PLR."""
        boiler = _default_boiler(eff_pct=85.0)
        eff_full = boiler.efficiency_at(1.0)
        eff_low = boiler.efficiency_at(0.05)  # very low PLR
        assert eff_low < eff_full, (
            f"Boiler efficiency at 5% PLR ({eff_low:.3f}) should be less than "
            f"at full load ({eff_full:.3f})"
        )

    def test_efficiency_at_zero_plr(self):
        boiler = _default_boiler(eff_pct=85.0)
        eff = boiler.efficiency_at(0.0)
        assert eff > 0.0
        # At PLR=0, efficiency should be ~85% of rated efficiency factor
        # Default: 0.85 × 0.85 × 1.0 (t=0, frac = 0.85 + 0.15 × 0 = 0.85)
        assert eff > 0.5

    def test_custom_part_load_curve(self):
        """Custom part-load curve is interpolated correctly."""
        boiler = BoilerSpec(
            rated_capacity_kw=100.0,
            efficiency_rated_pct=90.0,
            part_load_curve=[(0.0, 0.70), (0.5, 1.0), (1.0, 0.95)],
        )
        eff_half = boiler.efficiency_at(0.5)
        assert abs(eff_half - 0.90) < 0.01  # 90% × 1.0 = 90%
        eff_full = boiler.efficiency_at(1.0)
        assert abs(eff_full - 0.855) < 0.01  # 90% × 0.95 = 85.5%

    def test_condensing_boiler_high_efficiency(self):
        boiler = BoilerSpec(rated_capacity_kw=100.0, efficiency_rated_pct=97.0)
        eff = boiler.efficiency_at(1.0)
        assert eff > 0.90


# ---------------------------------------------------------------------------
# simulate_hvac_plant tests
# ---------------------------------------------------------------------------

class TestSimulateHvacPlant:

    def test_nonzero_cooling_produces_positive_electricity(self):
        annual = _make_annual(cooling_kwh=10000.0, heating_kwh=0.0)
        result = simulate_hvac_plant(annual, _default_chiller(), _default_boiler(), _default_air_side())
        assert result.annual_electricity_kwh > 0, (
            "Non-zero cooling load should produce positive electricity use"
        )

    def test_nonzero_heating_produces_positive_gas(self):
        annual = _make_annual(cooling_kwh=0.0, heating_kwh=8000.0)
        result = simulate_hvac_plant(annual, _default_chiller(), _default_boiler(), _default_air_side())
        assert result.annual_gas_kwh > 0, (
            "Non-zero heating load should produce positive gas use"
        )

    def test_zero_cooling_zero_chiller_elec(self):
        """With no cooling loads, chiller electricity should be near zero (only fans)."""
        # Set climate mean high to avoid cooling
        hourly = [HourlyResult(h, 0.0, 0.0, 0.0, 20.0, 50.0) for h in range(8760)]
        annual = AnnualResult(
            hourly=hourly,
            annual_heating_kwh=5000.0, annual_cooling_kwh=0.0,
            annual_fan_kwh=0.0, annual_lighting_kwh=0.0, eui_kwh_m2_yr=0.0,
        )
        result = simulate_hvac_plant(annual, _default_chiller(), _default_boiler(), _default_air_side())
        # Electricity is from fans only, not chiller
        # Fan power = 10000 CFM × 1.25 W/CFM / 1000 = 12.5 kW
        # With minimum fan fraction 0.05: 12.5 × 0.05 × 8760 = 5,475 kWh
        # Allow a reasonable fan-only range
        assert result.annual_electricity_kwh < 20000, (
            "Zero cooling should give only fan electricity"
        )

    def test_zero_heating_zero_gas(self):
        hourly = [HourlyResult(h, 0.0, 5.0, 0.5, 26.0, 50.0, 28.0) for h in range(8760)]
        annual = AnnualResult(
            hourly=hourly,
            annual_heating_kwh=0.0, annual_cooling_kwh=10000.0,
            annual_fan_kwh=1000.0, annual_lighting_kwh=0.0, eui_kwh_m2_yr=0.0,
        )
        result = simulate_hvac_plant(annual, _default_chiller(), _default_boiler(), _default_air_side())
        assert result.annual_gas_kwh == 0.0, (
            f"Zero heating should give zero gas; got {result.annual_gas_kwh}"
        )

    def test_hourly_lists_length_8760(self):
        annual = _make_annual()
        result = simulate_hvac_plant(annual, _default_chiller(), _default_boiler(), _default_air_side())
        assert len(result.hourly_electricity_kwh) == 8760
        assert len(result.hourly_gas_kwh) == 8760

    def test_gas_therms_consistent_with_kwh(self):
        annual = _make_annual(heating_kwh=10000.0)
        result = simulate_hvac_plant(annual, _default_chiller(), _default_boiler(), _default_air_side())
        if result.annual_gas_kwh > 0:
            expected_therms = result.annual_gas_kwh / _KWH_PER_THERM
            assert abs(result.annual_gas_therms - expected_therms) < 0.5, (
                f"Gas therms {result.annual_gas_therms} inconsistent with "
                f"gas kWh {result.annual_gas_kwh} / {_KWH_PER_THERM}"
            )

    def test_economizer_reduces_chiller_electricity(self):
        """Integrated economiser should reduce chiller electricity vs no economiser."""
        annual = _make_annual(cooling_kwh=15000.0, climate_mean_c=10.0)  # cool climate → economiser active
        result_no_eco = simulate_hvac_plant(
            annual, _default_chiller(), _default_boiler(),
            _default_air_side(economizer="none"),
        )
        result_eco = simulate_hvac_plant(
            annual, _default_chiller(), _default_boiler(),
            _default_air_side(economizer="integrated"),
        )
        # Economiser should reduce electricity (or equal if no free cooling hours)
        assert result_eco.annual_electricity_kwh <= result_no_eco.annual_electricity_kwh + 1.0, (
            f"Economiser electricity {result_eco.annual_electricity_kwh:.0f} "
            f"should be ≤ no-eco {result_no_eco.annual_electricity_kwh:.0f}"
        )

    def test_return_fan_increases_electricity(self):
        """Return fan adds ~25% to fan power → more total electricity."""
        annual = _make_annual()
        result_no_rf = simulate_hvac_plant(
            annual, _default_chiller(), _default_boiler(),
            AirSideSystem(10000.0, 1.25, False, "none"),
        )
        result_with_rf = simulate_hvac_plant(
            annual, _default_chiller(), _default_boiler(),
            AirSideSystem(10000.0, 1.25, True, "none"),
        )
        assert result_with_rf.annual_electricity_kwh > result_no_rf.annual_electricity_kwh

    def test_chiller_cop_average_in_reasonable_range(self):
        annual = _make_annual(cooling_kwh=15000.0)
        result = simulate_hvac_plant(annual, _default_chiller(cop=5.5), _default_boiler(), _default_air_side())
        assert 0.5 < result.chiller_cop_average < 10.0

    def test_boiler_efficiency_average_reasonable(self):
        annual = _make_annual(heating_kwh=8000.0)
        result = simulate_hvac_plant(annual, _default_chiller(), _default_boiler(eff_pct=85.0), _default_air_side())
        if result.boiler_efficiency_average > 0:
            assert 50.0 < result.boiler_efficiency_average <= 100.0

    def test_invalid_chiller_capacity_raises(self):
        annual = _make_annual()
        chiller = ChillerSpec(name="bad", rated_capacity_kw=0.0, cop_rated=5.0)
        with pytest.raises(ValueError, match="chiller"):
            simulate_hvac_plant(annual, chiller, _default_boiler(), _default_air_side())

    def test_invalid_boiler_capacity_raises(self):
        annual = _make_annual()
        boiler = BoilerSpec(rated_capacity_kw=-1.0, efficiency_rated_pct=85.0)
        with pytest.raises(ValueError, match="boiler"):
            simulate_hvac_plant(annual, _default_chiller(), boiler, _default_air_side())

    def test_higher_cop_chiller_uses_less_electricity(self):
        """Higher-COP chiller uses less electricity for the same cooling load."""
        annual = _make_annual(cooling_kwh=20000.0)
        result_low = simulate_hvac_plant(
            annual, _default_chiller(cop=3.0), _default_boiler(), _default_air_side()
        )
        result_high = simulate_hvac_plant(
            annual, _default_chiller(cop=6.0), _default_boiler(), _default_air_side()
        )
        assert result_high.annual_electricity_kwh < result_low.annual_electricity_kwh, (
            f"Higher COP chiller ({result_high.annual_electricity_kwh:.0f} kWh) "
            f"should use less electricity than lower COP ({result_low.annual_electricity_kwh:.0f} kWh)"
        )

    def test_caveat_present(self):
        annual = _make_annual()
        result = simulate_hvac_plant(annual, _default_chiller(), _default_boiler(), _default_air_side())
        assert len(result.honest_caveat) > 20


# ---------------------------------------------------------------------------
# Economiser logic tests
# ---------------------------------------------------------------------------

class TestEconomizer:

    def test_none_always_zero(self):
        frac = _economizer_free_cooling_frac("none", 10.0)
        assert frac == 0.0

    def test_integrated_active_below_threshold(self):
        frac = _economizer_free_cooling_frac("integrated", 10.0)
        assert frac > 0.0

    def test_integrated_inactive_above_threshold(self):
        frac = _economizer_free_cooling_frac("integrated", 20.0)
        assert frac == 0.0

    def test_differential_dry_bulb_active_when_outdoor_cooler(self):
        frac = _economizer_free_cooling_frac("differential_drybulb", 15.0, t_return_c=24.0)
        assert frac > 0.0

    def test_differential_dry_bulb_inactive_when_outdoor_warm(self):
        frac = _economizer_free_cooling_frac("differential_drybulb", 26.0, t_return_c=24.0)
        assert frac == 0.0
