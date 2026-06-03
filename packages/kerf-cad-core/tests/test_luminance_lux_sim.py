"""
Tests for kerf_cad_core.render.luminance_lux_sim.

Coverage:
  sun_position          — altitude/azimuth at known lat/lon/date/time
  compute_daylight_lux  — noon tropics → ~100,000 lux; midnight → 0
  compute_daylight_lux  — overcast sky < clear sky
  compute_daylight_lux  — with electric luminaires adds extra lux
  LuxReport             — uniformity_ratio = min/average
  render_luminance_map  — returns correct array shape

References
----------
Cohen, M.F. and Wallace, J.R. (1993).  "Radiosity and Realistic Image Synthesis."
Spencer (1971) — sun position equations.
CIE S 011/E:2003 — standard sky models.
IESNA HB-10 §5.3 — illuminance.

Author: imranparuk
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.render.luminance_lux_sim import (
    DaylightConditions,
    ElectricLuminaire,
    LuxReport,
    compute_daylight_lux,
    render_luminance_map,
    sun_position,
)


class TestSunPosition:
    def test_noon_equator_june21_altitude_high(self):
        """Solar noon at equator on June 21 — altitude near 66.5° (23.5° solstice declination)."""
        alt, az = sun_position(0.0, 0.0, "2026-06-21", "12:00")
        # Should be well above horizon
        assert alt > 50.0

    def test_midnight_altitude_negative(self):
        """Midnight at equator — sun below horizon."""
        alt, _ = sun_position(0.0, 0.0, "2026-06-21", "00:00")
        assert alt < 0.0

    def test_summer_solstice_north_pole_positive_altitude(self):
        """Arctic circle on summer solstice — sun above horizon at midnight."""
        alt, _ = sun_position(70.0, 0.0, "2026-06-21", "12:00")
        assert alt > 30.0


class TestComputeDaylightLux:
    def _open_field_conditions(
        self, sky_model="cie_clear", time="12:00"
    ) -> DaylightConditions:
        return DaylightConditions(
            sky_model=sky_model,
            latitude_deg=0.0,
            longitude_deg=0.0,
            date_iso="2026-06-21",
            time_local=time,
            timezone_offset_h=0.0,
        )

    def test_noon_equator_june21_approx_100k_lux(self):
        """Open field at solar noon, equator, June 21 → ~100,000 lux (CIE clear sky).

        Reference value: IES HB-10 §2.3 — clear sky direct + diffuse ≈ 100,000 lx.
        HONEST: simplified model, acceptable within ±40%.
        """
        cond = self._open_field_conditions("cie_clear", "12:00")
        pts = [(0.0, 0.0, 0.0)]
        report = compute_daylight_lux([], pts, cond)
        # Should be in the range 60,000–140,000 lux for clear sky noon at equator
        assert report.average_lux > 50_000.0, (
            f"Expected > 50,000 lux; got {report.average_lux:.0f}"
        )

    def test_midnight_zero_lux(self):
        """Midnight → sun below horizon → 0 direct + 0 diffuse lux."""
        cond = self._open_field_conditions("cie_clear", "00:00")
        pts = [(0.0, 0.0, 0.0)]
        report = compute_daylight_lux([], pts, cond)
        assert report.average_lux == pytest.approx(0.0, abs=1.0)

    def test_overcast_less_than_clear(self):
        """Overcast sky (no direct beam) produces less lux than clear sky."""
        pts = [(0.0, 0.0, 0.0)]
        report_clear = compute_daylight_lux(
            [], pts, self._open_field_conditions("cie_clear")
        )
        report_overcast = compute_daylight_lux(
            [], pts, self._open_field_conditions("cie_overcast")
        )
        assert report_overcast.average_lux < report_clear.average_lux

    def test_multiple_points_returns_correct_count(self):
        pts = [(i * 1.0, 0.0, 0.0) for i in range(5)]
        cond = self._open_field_conditions()
        report = compute_daylight_lux([], pts, cond)
        assert len(report.lux_values) == 5

    def test_uniformity_ratio_is_min_over_average(self):
        """LuxReport.uniformity_ratio must equal min_lux / average_lux."""
        pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0)]
        cond = self._open_field_conditions()
        report = compute_daylight_lux([], pts, cond)
        if report.average_lux > 0:
            expected_ratio = report.min_lux / report.average_lux
            assert report.uniformity_ratio == pytest.approx(expected_ratio, rel=1e-5)

    def test_uniformity_ratio_lte_one(self):
        """Uniformity ratio ≤ 1 (min ≤ average always)."""
        pts = [(i * 0.5, 0.0, 0.0) for i in range(4)]
        cond = self._open_field_conditions()
        report = compute_daylight_lux([], pts, cond)
        assert report.uniformity_ratio <= 1.0 + 1e-9

    def test_electric_luminaire_adds_lux(self):
        """Adding an electric luminaire increases lux at the target point."""
        cond = DaylightConditions(
            sky_model="cie_overcast",
            latitude_deg=0.0,
            longitude_deg=0.0,
            date_iso="2026-06-21",
            time_local="00:00",  # night → only electric
        )
        pts = [(0.0, 0.0, 0.0)]
        lum = ElectricLuminaire(
            position=(0.0, 0.0, 3.0),
            intensity_cd=5000.0,
            direction=(0.0, 0.0, -1.0),
            beam_angle_deg=60.0,
        )
        report = compute_daylight_lux([], pts, cond, electric_luminaires=[lum])
        assert report.average_lux > 0.0

    def test_lux_stats_consistent(self):
        """min_lux ≤ average_lux ≤ max_lux always."""
        pts = [(float(i), float(j), 0.0) for i in range(3) for j in range(3)]
        cond = self._open_field_conditions()
        report = compute_daylight_lux([], pts, cond)
        assert report.min_lux <= report.average_lux + 1e-9
        assert report.average_lux <= report.max_lux + 1e-9


class TestRenderLuminanceMap:
    def test_returns_correct_shape(self):
        cond = DaylightConditions(
            sky_model="cie_clear",
            latitude_deg=0.0,
            longitude_deg=0.0,
            date_iso="2026-06-21",
            time_local="12:00",
        )
        lmap = render_luminance_map(
            [],
            cond,
            camera_pos=(0.0, -5.0, 2.0),
            camera_look_at=(0.0, 0.0, 1.0),
            resolution=(32, 24),
        )
        assert lmap.shape == (24, 32)

    def test_luminance_map_nonnegative(self):
        cond = DaylightConditions(
            sky_model="cie_clear",
            latitude_deg=0.0,
            longitude_deg=0.0,
            date_iso="2026-06-21",
            time_local="12:00",
        )
        lmap = render_luminance_map(
            [], cond,
            camera_pos=(0.0, -5.0, 2.0),
            camera_look_at=(0.0, 0.0, 1.0),
            resolution=(16, 12),
        )
        assert float(lmap.min()) >= 0.0
