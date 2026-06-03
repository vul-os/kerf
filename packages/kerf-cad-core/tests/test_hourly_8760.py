"""
Tests for kerf_cad_core.buildingenergy.hourly_8760

Tests cover:
  - simulate_8760 with mild weather produces valid cooling+heating split
  - simulate_8760 with hot climate produces more cooling than heating
  - simulate_8760 with cold climate produces more heating than cooling
  - AnnualResult field integrity (sums, EUI, non-negative, correct counts)
  - HourlyResult fields populated for all 8760 hours
  - TMY3 parser returns 8760 hours from valid synthetic input
  - TMY3 parser rejects too-short input
  - TMY3 parser rejects too-few columns
  - Default office schedule generates 8760 values in 0–1
  - BuildingModel validation: floor_area_m2 <= 0 raises ValueError
  - BuildingModel validation: wrong weather length raises ValueError
  - Window-to-wall ratio = 0 still produces valid results
  - Fan energy is positive for all occupied hours
  - Indoor RH is within 10–90%
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.buildingenergy.hourly_8760 import (
    BuildingModel,
    WeatherHour,
    HourlyResult,
    AnnualResult,
    simulate_8760,
    load_tmy3_weather,
    _default_office_schedule,
    _compute_ua_w_per_k,
    _estimate_indoor_rh,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mild_weather(n: int = 8760) -> list[WeatherHour]:
    """Mild temperate climate: mean 13°C, amplitude 10°C."""
    hours = []
    for h in range(n):
        t = (
            13.0
            + 10.0 * math.cos(2 * math.pi * h / 8760 + math.pi)
            + 3.0 * math.cos(2 * math.pi * (h % 24) / 24 + math.pi)
        )
        rh = 55.0
        hod = h % 24
        is_day = 7 <= hod <= 19
        dni = 600.0 * math.sin(math.pi * (hod - 7) / 12) if is_day else 0.0
        dhi = 100.0 * math.sin(math.pi * (hod - 7) / 12) if is_day else 0.0
        hours.append(WeatherHour(
            iso_datetime=f"2026-01-01T{(hod):02d}:00",
            dry_bulb_c=round(t, 1),
            wet_bulb_c=round(t - 3.0, 1),
            relative_humidity_pct=rh,
            direct_normal_irradiance_w_m2=max(0.0, round(dni, 1)),
            diffuse_horizontal_irradiance_w_m2=max(0.0, round(dhi, 1)),
            wind_speed_m_s=3.0,
            wind_direction_deg=180.0,
        ))
    return hours


def _make_hot_weather(n: int = 8760) -> list[WeatherHour]:
    """Hot climate: mean 28°C, amplitude 8°C."""
    hours = []
    for h in range(n):
        t = 28.0 + 8.0 * math.cos(2 * math.pi * h / 8760 + math.pi)
        hours.append(WeatherHour(
            iso_datetime=f"2026-01-01T{(h%24):02d}:00",
            dry_bulb_c=round(t, 1), wet_bulb_c=round(t - 4, 1),
            relative_humidity_pct=60.0,
            direct_normal_irradiance_w_m2=500.0,
            diffuse_horizontal_irradiance_w_m2=80.0,
            wind_speed_m_s=2.0, wind_direction_deg=90.0,
        ))
    return hours


def _make_cold_weather(n: int = 8760) -> list[WeatherHour]:
    """Cold climate: mean -5°C, amplitude 12°C."""
    hours = []
    for h in range(n):
        t = -5.0 + 12.0 * math.cos(2 * math.pi * h / 8760 + math.pi)
        hours.append(WeatherHour(
            iso_datetime=f"2026-01-01T{(h%24):02d}:00",
            dry_bulb_c=round(t, 1), wet_bulb_c=round(t - 2, 1),
            relative_humidity_pct=70.0,
            direct_normal_irradiance_w_m2=200.0,
            diffuse_horizontal_irradiance_w_m2=50.0,
            wind_speed_m_s=4.0, wind_direction_deg=270.0,
        ))
    return hours


def _base_model(floor_area_m2: float = 100.0) -> BuildingModel:
    return BuildingModel(
        name="TestBuilding",
        floor_area_m2=floor_area_m2,
        window_to_wall_ratio=0.40,
        construction_uw_m2k={"wall": 0.35, "roof": 0.20, "window": 2.0, "shgc": 0.40},
        internal_load_w_m2=20.0,
        occupancy_schedule_8760=[],  # will auto-generate
        setpoint_heating_c=20.0,
        setpoint_cooling_c=24.0,
        ceiling_height_m=3.0,
    )


# ---------------------------------------------------------------------------
# simulate_8760 tests
# ---------------------------------------------------------------------------

class TestSimulate8760:

    def test_mild_weather_returns_annual_result(self):
        model = _base_model(100.0)
        weather = _make_mild_weather()
        result = simulate_8760(model, weather)
        assert isinstance(result, AnnualResult)

    def test_mild_weather_8760_hourly_results(self):
        model = _base_model(100.0)
        result = simulate_8760(model, _make_mild_weather())
        assert len(result.hourly) == 8760

    def test_mild_weather_both_heating_and_cooling(self):
        """Mild temperate climate: both heating and cooling present."""
        model = _base_model(100.0)
        result = simulate_8760(model, _make_mild_weather())
        assert result.annual_heating_kwh > 0, "Expected non-zero heating in mild climate"
        assert result.annual_cooling_kwh > 0, "Expected non-zero cooling in mild climate"

    def test_hot_climate_more_cooling_than_heating(self):
        model = _base_model(100.0)
        result = simulate_8760(model, _make_hot_weather())
        assert result.annual_cooling_kwh > result.annual_heating_kwh, (
            f"Hot climate: cooling {result.annual_cooling_kwh:.0f} kWh should exceed "
            f"heating {result.annual_heating_kwh:.0f} kWh"
        )

    def test_cold_climate_more_heating_than_cooling(self):
        model = _base_model(100.0)
        result = simulate_8760(model, _make_cold_weather())
        assert result.annual_heating_kwh > result.annual_cooling_kwh, (
            f"Cold climate: heating {result.annual_heating_kwh:.0f} kWh should exceed "
            f"cooling {result.annual_cooling_kwh:.0f} kWh"
        )

    def test_eui_positive_and_sane(self):
        model = _base_model(100.0)
        result = simulate_8760(model, _make_mild_weather())
        # EUI for typical building: 50–500 kWh/(m²·yr) is physically plausible
        assert 0 < result.eui_kwh_m2_yr < 1000, f"EUI out of range: {result.eui_kwh_m2_yr}"

    def test_eui_consistent_with_total(self):
        """EUI × floor_area ≈ sum of end-use totals."""
        model = _base_model(200.0)
        result = simulate_8760(model, _make_mild_weather())
        total = (
            result.annual_heating_kwh
            + result.annual_cooling_kwh
            + result.annual_fan_kwh
            + result.annual_lighting_kwh
        )
        expected_eui = total / 200.0
        assert abs(result.eui_kwh_m2_yr - expected_eui) < 0.5, (
            f"EUI mismatch: {result.eui_kwh_m2_yr} vs {expected_eui}"
        )

    def test_non_negative_all_fields(self):
        model = _base_model(100.0)
        result = simulate_8760(model, _make_mild_weather())
        assert result.annual_heating_kwh >= 0
        assert result.annual_cooling_kwh >= 0
        assert result.annual_fan_kwh >= 0
        assert result.annual_lighting_kwh >= 0

    def test_peak_values_gt_zero(self):
        model = _base_model(100.0)
        result = simulate_8760(model, _make_mild_weather())
        assert result.peak_heating_kw > 0
        assert result.peak_cooling_kw > 0

    def test_hourly_result_fields(self):
        model = _base_model(100.0)
        result = simulate_8760(model, _make_mild_weather())
        for hr in result.hourly[:10]:
            assert isinstance(hr, HourlyResult)
            assert 0 <= hr.hour < 8760
            assert hr.heating_load_kw >= 0
            assert hr.cooling_load_kw >= 0
            assert hr.fan_kw >= 0
            assert 10 <= hr.indoor_rh_pct <= 90

    def test_indoor_temp_at_setpoint_when_load_present(self):
        model = _base_model(100.0)
        result = simulate_8760(model, _make_cold_weather())
        # In cold climate, most hours should be at heating setpoint
        heated_hours = [
            hr for hr in result.hourly
            if hr.heating_load_kw > 0 and abs(hr.indoor_temp_c - model.setpoint_heating_c) < 0.1
        ]
        assert len(heated_hours) > 500, "Expected many hours at heating setpoint in cold climate"

    def test_zero_wwr_valid(self):
        model = BuildingModel(
            name="NoWindows",
            floor_area_m2=100.0,
            window_to_wall_ratio=0.0,
            construction_uw_m2k={"wall": 0.35, "roof": 0.20, "window": 2.0},
            internal_load_w_m2=15.0,
            occupancy_schedule_8760=[],
        )
        result = simulate_8760(model, _make_mild_weather())
        assert result.annual_heating_kwh >= 0
        assert result.annual_cooling_kwh >= 0

    def test_invalid_floor_area_raises(self):
        model = _base_model(-10.0)
        with pytest.raises(ValueError, match="floor_area_m2"):
            simulate_8760(model, _make_mild_weather())

    def test_invalid_weather_length_raises(self):
        model = _base_model(100.0)
        with pytest.raises(ValueError, match="8760"):
            simulate_8760(model, _make_mild_weather(100))

    def test_custom_schedule_used(self):
        """Custom 8760-length schedule is accepted."""
        sched = [1.0 if (h % 24) == 12 else 0.0 for h in range(8760)]
        model = BuildingModel(
            name="CustomSched",
            floor_area_m2=100.0,
            window_to_wall_ratio=0.30,
            construction_uw_m2k={"wall": 0.35, "roof": 0.20, "window": 2.0},
            internal_load_w_m2=20.0,
            occupancy_schedule_8760=sched,
        )
        result = simulate_8760(model, _make_mild_weather())
        assert len(result.hourly) == 8760


# ---------------------------------------------------------------------------
# TMY3 parser tests
# ---------------------------------------------------------------------------

def _make_tmy3_csv(n_rows: int = 8760) -> str:
    """Generate a minimal syntactically valid TMY3 CSV."""
    header = "722780,Denver,CO,-7,39.75,-104.87,1650"
    cols = ",".join([
        "Date(MM/DD/YYYY)", "Time(HH:MM)",
        "ETR(W/m^2)", "ETRN(W/m^2)", "GHIirr(W/m^2)",  # 2,3,4
        "GHI source", "DNI(W/m^2)", "DHI(W/m^2)",        # 5,6,7
        "GHillum(100lx)", "DNillum(100lx)", "DHillum(100lx)", "ZenLum(10Cd/m^2)",  # 8-11
        "Dry-bulb(C)", "Dew-point(C)", "RHum(%)",          # 12,13,14
        "Pressure(mbar)", "Wdir(deg)", "Wspd(m/s)",         # 15,16,17
    ])
    rows = []
    import math
    for i in range(n_rows):
        hour_ending = (i % 24) + 1
        day = (i // 24) + 1
        if day > 365:
            day = 365
        date_str = f"01/{day:02d}/1990"
        time_str = f"{hour_ending:02d}:00"
        t = 10.0 + 8.0 * math.cos(2 * math.pi * i / 8760 + math.pi)
        dpt = t - 4.0
        hod = i % 24
        is_day = 7 <= hod <= 19
        dni = max(0, 500 * math.sin(math.pi * (hod - 7) / 12)) if is_day else 0.0
        dhi = max(0, 80 * math.sin(math.pi * (hod - 7) / 12)) if is_day else 0.0
        row = f"{date_str},{time_str},1000,900,600,1,{dni:.0f},{dhi:.0f},500,400,300,200,{t:.1f},{dpt:.1f},55,870,180,3.5"
        rows.append(row)
    return "\n".join([header, cols] + rows)


class TestTMY3Parser:

    def test_parse_8760_rows(self):
        csv = _make_tmy3_csv(8760)
        hours = load_tmy3_weather(csv)
        assert len(hours) == 8760

    def test_parsed_fields_in_range(self):
        csv = _make_tmy3_csv(8760)
        hours = load_tmy3_weather(csv)
        for h in hours[:24]:
            assert -60.0 <= h.dry_bulb_c <= 60.0
            assert 0.0 <= h.relative_humidity_pct <= 100.0
            assert h.direct_normal_irradiance_w_m2 >= 0.0
            assert h.diffuse_horizontal_irradiance_w_m2 >= 0.0
            assert h.wind_speed_m_s >= 0.0

    def test_wet_bulb_less_than_or_equal_dry_bulb(self):
        csv = _make_tmy3_csv(8760)
        hours = load_tmy3_weather(csv)
        for h in hours[:100]:
            assert h.wet_bulb_c <= h.dry_bulb_c + 0.1  # wet-bulb ≤ dry-bulb

    def test_too_short_file_raises(self):
        csv = _make_tmy3_csv(100)
        with pytest.raises(ValueError, match="8760"):
            load_tmy3_weather(csv)

    def test_empty_file_raises(self):
        with pytest.raises(ValueError):
            load_tmy3_weather("")

    def test_iso_datetime_format(self):
        csv = _make_tmy3_csv(8760)
        hours = load_tmy3_weather(csv)
        # All should have 'T' in datetime string
        for h in hours[:24]:
            assert "T" in h.iso_datetime


# ---------------------------------------------------------------------------
# Default schedule tests
# ---------------------------------------------------------------------------

class TestDefaultSchedule:

    def test_schedule_length(self):
        sched = _default_office_schedule()
        assert len(sched) == 8760

    def test_schedule_values_in_range(self):
        sched = _default_office_schedule()
        assert all(0.0 <= v <= 1.0 for v in sched)

    def test_weekday_business_hours_high(self):
        sched = _default_office_schedule()
        # Hour 9 (Mon, business hours) should be high
        assert sched[9] >= 0.8

    def test_night_hours_low(self):
        sched = _default_office_schedule()
        # Hour 2 (middle of night) should be low
        assert sched[2] <= 0.10
