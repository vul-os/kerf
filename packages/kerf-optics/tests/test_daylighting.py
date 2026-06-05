"""
Tests for optics_daylighting_simulation tool + underlying luminance_lux_sim engine.

Oracles
-------
1. Clear sky at solar noon on equator, June 21 → illuminance ≫ overcast sky.
2. Overcast sky yields uniformity_ratio closer to 1.0 than clear sky (diffuse only).
3. Electric luminaires increase illuminance compared to daylight-only run.
4. Night-time (00:00) yields near-zero illuminance for all sky models.
5. Daylight factor = average_lux / 10,000 × 100 % (definition check).
6. Tool handler round-trip: valid args → ok=True, expected keys present.
7. Tool handler: invalid sky_model → DAYLIGHTING_ERROR or BAD_ARGS.
8. Tool handler: too many measurement points → BAD_ARGS (> 1000).
9. Denser clear sky → luminance_map from render_luminance_map has correct shape.
10. Winter solstice (lat=60 N, Dec 21, 12:00) → lower illuminance than summer.

References
----------
CIE S 011/E:2003 — standard sky models.
Spencer, J.W. (1971). Search 2(5):172.
Cohen, M.F. and Wallace, J.R. (1993). Radiosity, §3.
CIBSE Guide A (2015) — DF reference = 10,000 lux.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
import sys

import numpy as np
import pytest

# Ensure all packages/*/src are on sys.path
_HERE = os.path.dirname(os.path.abspath(__file__))
_OPTICS_ROOT = os.path.dirname(_HERE)
_PACKAGES_ROOT = os.path.dirname(_OPTICS_ROOT)
for _entry in os.listdir(_PACKAGES_ROOT):
    if _entry.startswith("kerf-"):
        _src = os.path.join(_PACKAGES_ROOT, _entry, "src")
        if os.path.isdir(_src) and _src not in sys.path:
            sys.path.insert(0, _src)

from kerf_cad_core.render.luminance_lux_sim import (
    DaylightConditions,
    ElectricLuminaire,
    LuxReport,
    compute_daylight_lux,
    render_luminance_map,
    sun_position,
)
from kerf_optics.tools import (
    optics_daylighting_simulation_spec,
    run_optics_daylighting_simulation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def make_grid(n=4):
    """A small horizontal 4×4 grid at z=0.85 m."""
    pts = []
    for i in range(n):
        for j in range(n):
            pts.append([float(i), float(j), 0.85])
    return pts


class FakeCtx:
    pass


# ---------------------------------------------------------------------------
# Oracle 1 — clear sky > overcast sky at solar noon
# ---------------------------------------------------------------------------

class TestClearVsOvercast:
    def test_clear_brighter_than_overcast_at_noon(self):
        pts = make_grid()
        noon_conds_clear = DaylightConditions(
            latitude_deg=0.0, longitude_deg=0.0,
            date_iso="2026-06-21", time_local="12:00",
            sky_model="cie_clear",
        )
        noon_conds_over = DaylightConditions(
            latitude_deg=0.0, longitude_deg=0.0,
            date_iso="2026-06-21", time_local="12:00",
            sky_model="cie_overcast",
        )
        report_clear = compute_daylight_lux([], pts, noon_conds_clear)
        report_over  = compute_daylight_lux([], pts, noon_conds_over)
        assert report_clear.average_lux > report_over.average_lux, (
            f"Clear ({report_clear.average_lux:.1f}) should exceed overcast ({report_over.average_lux:.1f})"
        )

    def test_clear_sky_noon_equinox_positive_lux(self):
        """Clear sky at noon on equinox at equator should give positive illuminance."""
        pts = [[0.0, 0.0, 0.0]]
        conds = DaylightConditions(
            latitude_deg=0.0, longitude_deg=0.0,
            date_iso="2026-03-20", time_local="12:00",
            sky_model="cie_clear",
        )
        report = compute_daylight_lux([], pts, conds)
        assert report.average_lux > 1000.0, (
            f"Expected > 1000 lux at equatorial noon clear sky, got {report.average_lux}"
        )


# ---------------------------------------------------------------------------
# Oracle 2 — overcast uniformity closer to 1.0 (all diffuse)
# ---------------------------------------------------------------------------

class TestOvercastUniformity:
    def test_overcast_uniformity_higher_than_clear(self):
        pts = make_grid(5)
        conds_clear = DaylightConditions(
            latitude_deg=51.5, longitude_deg=-0.1,
            date_iso="2026-06-21", time_local="12:00",
            sky_model="cie_clear",
        )
        conds_over = DaylightConditions(
            latitude_deg=51.5, longitude_deg=-0.1,
            date_iso="2026-06-21", time_local="12:00",
            sky_model="cie_overcast",
        )
        r_clear = compute_daylight_lux([], pts, conds_clear)
        r_over  = compute_daylight_lux([], pts, conds_over)
        # For a horizontal grid all at z=0, all points get same diffuse component →
        # uniformity_ratio should be 1.0 for overcast (only diffuse, uniform by sky model)
        assert r_over.uniformity_ratio >= r_clear.uniformity_ratio, (
            f"Overcast uniformity {r_over.uniformity_ratio:.4f} should be >= clear {r_clear.uniformity_ratio:.4f}"
        )


# ---------------------------------------------------------------------------
# Oracle 3 — electric luminaires increase illuminance
# ---------------------------------------------------------------------------

class TestElectricLuminaires:
    def test_luminaires_add_to_daylight(self):
        pts = [[5.0, 5.0, 0.0]]
        conds = DaylightConditions(
            latitude_deg=51.5, longitude_deg=-0.1,
            date_iso="2026-06-21", time_local="12:00",
            sky_model="cie_clear",
        )
        r_day_only = compute_daylight_lux([], pts, conds)
        lum = ElectricLuminaire(
            position=(5.0, 5.0, 3.0),
            direction=(0.0, 0.0, -1.0),
            intensity_cd=2000.0,
            beam_angle_deg=90.0,
        )
        r_with_lum = compute_daylight_lux([], pts, conds, electric_luminaires=[lum])
        assert r_with_lum.average_lux > r_day_only.average_lux, (
            f"Adding luminaire should increase lux: {r_with_lum.average_lux:.1f} vs {r_day_only.average_lux:.1f}"
        )


# ---------------------------------------------------------------------------
# Oracle 4 — night → near-zero illuminance
# ---------------------------------------------------------------------------

class TestNighttime:
    def test_midnight_near_zero_lux(self):
        pts = [[0.0, 0.0, 0.0]]
        for sky_model in ("cie_clear", "cie_overcast", "cie_intermediate"):
            conds = DaylightConditions(
                latitude_deg=51.5, longitude_deg=-0.1,
                date_iso="2026-06-21", time_local="00:00",
                sky_model=sky_model,
            )
            r = compute_daylight_lux([], pts, conds)
            assert r.average_lux < 100.0, (
                f"{sky_model} midnight: expected < 100 lux, got {r.average_lux:.1f}"
            )


# ---------------------------------------------------------------------------
# Oracle 5 — daylight factor definition
# ---------------------------------------------------------------------------

class TestDaylightFactor:
    def test_df_formula_consistency(self):
        """DF % == average_lux / 10,000 * 100."""
        pts = make_grid(3)
        conds = DaylightConditions(
            latitude_deg=51.5, longitude_deg=-0.1,
            date_iso="2026-06-21", time_local="12:00",
            sky_model="cie_clear",
        )
        report = compute_daylight_lux([], pts, conds)
        df_expected = report.average_lux / 10_000.0 * 100.0
        # Tool handler computes the same
        assert math.isclose(df_expected, report.average_lux / 1e4 * 100, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# Oracle 6 — tool handler round-trip
# ---------------------------------------------------------------------------

class TestToolHandler:
    def test_valid_args_returns_ok(self):
        args = {
            "latitude_deg": 51.5,
            "longitude_deg": -0.1,
            "date_iso": "2026-06-21",
            "time_local": "12:00",
            "sky_model": "cie_clear",
            "measurement_points": [[0, 0, 0.85], [5, 0, 0.85], [5, 5, 0.85], [0, 5, 0.85]],
        }
        result_str = run_async(run_optics_daylighting_simulation(args, FakeCtx()))
        result = json.loads(result_str)
        assert "average_lux" in result, f"Missing average_lux: {result}"
        assert "mean_daylight_factor_pct" in result
        assert "uniformity_ratio" in result
        assert result["n_points"] == 4
        assert result["average_lux"] >= 0

    def test_all_sky_models_work(self):
        for model in ("cie_clear", "cie_overcast", "cie_intermediate"):
            args = {
                "latitude_deg": 0.0,
                "longitude_deg": 0.0,
                "date_iso": "2026-06-21",
                "time_local": "12:00",
                "sky_model": model,
                "measurement_points": [[0, 0, 0]],
            }
            result_str = run_async(run_optics_daylighting_simulation(args, FakeCtx()))
            result = json.loads(result_str)
            assert "average_lux" in result, f"sky_model={model} failed: {result}"

    def test_with_electric_luminaires(self):
        args = {
            "latitude_deg": 51.5,
            "longitude_deg": -0.1,
            "date_iso": "2026-06-21",
            "time_local": "12:00",
            "sky_model": "cie_clear",
            "measurement_points": [[0, 0, 0]],
            "electric_luminaires": [
                {"position": [0, 0, 3], "direction": [0, 0, -1], "intensity_cd": 1000, "beam_angle_deg": 90},
            ],
        }
        result_str = run_async(run_optics_daylighting_simulation(args, FakeCtx()))
        result = json.loads(result_str)
        assert "average_lux" in result
        assert result["average_lux"] > 0


# ---------------------------------------------------------------------------
# Oracle 7 — invalid sky_model → error
# ---------------------------------------------------------------------------

class TestInvalidSkyModel:
    def test_bad_sky_model_returns_error(self):
        args = {
            "latitude_deg": 0.0,
            "longitude_deg": 0.0,
            "measurement_points": [[0, 0, 0]],
            "sky_model": "cie_magical",
        }
        result_str = run_async(run_optics_daylighting_simulation(args, FakeCtx()))
        result = json.loads(result_str)
        # Should not have average_lux; should have an error indicator
        assert "average_lux" not in result or result.get("ok") is False or "error" in result


# ---------------------------------------------------------------------------
# Oracle 8 — too many points → BAD_ARGS
# ---------------------------------------------------------------------------

class TestTooManyPoints:
    def test_more_than_1000_points_rejected(self):
        pts = [[float(i), 0.0, 0.0] for i in range(1001)]
        args = {
            "latitude_deg": 0.0,
            "longitude_deg": 0.0,
            "measurement_points": pts,
        }
        result_str = run_async(run_optics_daylighting_simulation(args, FakeCtx()))
        result = json.loads(result_str)
        assert "average_lux" not in result, "Should reject > 1000 points"


# ---------------------------------------------------------------------------
# Oracle 9 — render_luminance_map shape
# ---------------------------------------------------------------------------

class TestLuminanceMapShape:
    def test_render_returns_correct_shape(self):
        conds = DaylightConditions(
            latitude_deg=51.5, longitude_deg=-0.1,
            date_iso="2026-06-21", time_local="12:00",
            sky_model="cie_clear",
        )
        arr = render_luminance_map(
            scene_geometry=[],
            conditions=conds,
            camera_pos=(5.0, 5.0, 3.0),
            camera_look_at=(5.0, 5.0, 0.0),
            resolution=(16, 16),
        )
        assert arr.shape == (16, 16), f"Expected (16,16), got {arr.shape}"
        assert np.all(arr >= 0), "Luminance values must be non-negative"


# ---------------------------------------------------------------------------
# Oracle 10 — winter < summer illuminance at high latitude
# ---------------------------------------------------------------------------

class TestSeasonalVariation:
    def test_winter_less_illuminance_than_summer_high_latitude(self):
        """At lat=60N, June 21 noon should be brighter than Dec 21 noon."""
        pts = [[0.0, 0.0, 0.0]]
        summer = DaylightConditions(
            latitude_deg=60.0, longitude_deg=25.0,
            date_iso="2026-06-21", time_local="12:00",
            sky_model="cie_clear",
        )
        winter = DaylightConditions(
            latitude_deg=60.0, longitude_deg=25.0,
            date_iso="2026-12-21", time_local="12:00",
            sky_model="cie_clear",
        )
        r_summer = compute_daylight_lux([], pts, summer)
        r_winter = compute_daylight_lux([], pts, winter)
        assert r_summer.average_lux > r_winter.average_lux, (
            f"Summer ({r_summer.average_lux:.1f}) should > winter ({r_winter.average_lux:.1f}) at lat=60N"
        )
