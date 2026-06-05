"""
Tests for kerf_bim.tools.site_terrain — site terrain mesh modelling.

All tools take points as [[x,y,z], ...] lists (not dicts).

Coverage
--------
- bim_terrain_from_points: basic TIN build, degenerate (< 3 points)
- bim_terrain_from_contours: contour set → TIN
- bim_terrain_analyse: slope/aspect stats (min, max, mean present)
- bim_terrain_contours: contour polyline generation
- bim_terrain_cut_fill: earthwork volumes between two terrain surfaces
"""

from __future__ import annotations

import asyncio
import json

import pytest


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flat_grid(z: float = 0.0, n: int = 4):
    """Return n×n grid of XYZ lists at constant Z."""
    return [[float(i), float(j), z] for i in range(n) for j in range(n)]


def _sloped_points():
    """Gentle slope in X direction (0.5m rise per 1m run)."""
    return [
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.5], [2.0, 0.0, 1.0],
        [0.0, 1.0, 0.0], [1.0, 1.0, 0.5], [2.0, 1.0, 1.0],
        [0.0, 2.0, 0.0], [1.0, 2.0, 0.5], [2.0, 2.0, 1.0],
    ]


def _survey_points():
    """Realistic survey point cloud."""
    return [
        [0.0,  0.0,  100.0], [10.0, 0.0,  102.5], [20.0, 0.0,  105.0],
        [0.0,  10.0, 101.0], [10.0, 10.0, 103.0], [20.0, 10.0, 106.0],
        [0.0,  20.0, 99.0],  [10.0, 20.0, 101.5], [20.0, 20.0, 104.0],
    ]


# ---------------------------------------------------------------------------
# 1. bim_terrain_from_points
# ---------------------------------------------------------------------------

class TestTerrainFromPoints:
    def _call(self, points, **kwargs) -> dict:
        from kerf_bim.tools.site_terrain import run_bim_terrain_from_points
        params = {"points": points, **kwargs}
        return json.loads(_run(run_bim_terrain_from_points(params, None)))

    def test_basic_tin_from_grid(self):
        result = self._call(_flat_grid())
        assert result["ok"] is True
        assert result["point_count"] == 16

    def test_survey_points(self):
        result = self._call(_survey_points())
        assert result["ok"] is True
        assert result["point_count"] == 9

    def test_triangle_count_positive(self):
        result = self._call(_survey_points())
        assert result["triangle_count"] > 0

    def test_elevation_range_present(self):
        result = self._call(_survey_points())
        assert "elevation" in result
        elev = result["elevation"]
        assert "min" in elev
        assert "max" in elev
        assert elev["min"] <= elev["max"]

    def test_elevation_values_correct(self):
        result = self._call(_survey_points())
        assert result["elevation"]["min"] == pytest.approx(99.0, abs=0.01)
        assert result["elevation"]["max"] == pytest.approx(106.0, abs=0.01)

    def test_too_few_points_error(self):
        result = self._call([[0.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
        assert "error" in result

    def test_material_parameter(self):
        result = self._call(_survey_points(), material="rock")
        assert result["ok"] is True
        assert result["material"] == "rock"

    def test_flat_surface_valid(self):
        result = self._call(_flat_grid(z=5.0, n=3))
        assert result["ok"] is True
        assert result["triangle_count"] > 0

    def test_surface_and_plan_area_present(self):
        result = self._call(_survey_points())
        assert "surface_area" in result
        assert "plan_area" in result
        assert result["plan_area"] > 0


# ---------------------------------------------------------------------------
# 2. bim_terrain_from_contours
# ---------------------------------------------------------------------------

class TestTerrainFromContours:
    def _call(self, contour_sets, **kwargs) -> dict:
        from kerf_bim.tools.site_terrain import run_bim_terrain_from_contours
        params = {"contour_sets": contour_sets, **kwargs}
        return json.loads(_run(run_bim_terrain_from_contours(params, None)))

    def _simple_contour_sets(self):
        # contour_sets: [{elevation, points: [[x,y], ...]}, ...]
        return [
            {"elevation": 100.0, "points": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]},
            {"elevation": 102.0, "points": [[2.0, 2.0], [8.0, 2.0],  [8.0, 8.0],   [2.0, 8.0]]},
            {"elevation": 104.0, "points": [[4.0, 4.0], [6.0, 4.0],  [6.0, 6.0],   [4.0, 6.0]]},
        ]

    def test_basic_contours(self):
        result = self._call(self._simple_contour_sets())
        assert result["ok"] is True

    def test_point_count_positive(self):
        result = self._call(self._simple_contour_sets())
        assert result["point_count"] > 0

    def test_elevation_range(self):
        result = self._call(self._simple_contour_sets())
        assert result["elevation"]["min"] == pytest.approx(100.0, abs=0.01)
        assert result["elevation"]["max"] == pytest.approx(104.0, abs=0.01)

    def test_contour_count_returned(self):
        result = self._call(self._simple_contour_sets())
        assert result["contour_count"] == 3

    def test_too_few_contour_sets_error(self):
        result = self._call([{"elevation": 100.0, "points": [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]}])
        assert "error" in result

    def test_empty_contour_sets_error(self):
        result = self._call([])
        assert "error" in result


# ---------------------------------------------------------------------------
# 3. bim_terrain_analyse
# ---------------------------------------------------------------------------

class TestTerrainAnalyse:
    def _call(self, points, **kwargs) -> dict:
        from kerf_bim.tools.site_terrain import run_bim_terrain_analyse
        params = {"points": points, **kwargs}
        return json.loads(_run(run_bim_terrain_analyse(params, None)))

    def test_slope_stats_present(self):
        result = self._call(_sloped_points())
        assert result["ok"] is True
        assert "slope" in result
        assert "min" in result["slope"]
        assert "max" in result["slope"]
        assert "mean" in result["slope"]

    def test_aspect_stats_present(self):
        result = self._call(_sloped_points())
        assert "aspect" in result

    def test_slope_in_degrees(self):
        result = self._call(_sloped_points())
        # A 0.5/1.0 rise/run slope = 26.6° — should be between 0 and 90
        assert 0.0 <= result["slope"]["mean"] <= 90.0

    def test_slope_classes_present(self):
        result = self._call(_sloped_points())
        assert "slope_classes" in result

    def test_flat_surface_low_slope(self):
        result = self._call(_flat_grid())
        assert result["ok"] is True
        assert result["slope"]["max"] < 5.0  # essentially flat

    def test_survey_points_analysis(self):
        result = self._call(_survey_points())
        assert result["ok"] is True
        assert result["slope"]["min"] >= 0.0

    def test_too_few_points_error(self):
        result = self._call([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        assert "error" in result

    def test_triangle_count_positive(self):
        result = self._call(_survey_points())
        assert result["triangle_count"] > 0


# ---------------------------------------------------------------------------
# 4. bim_terrain_contours
# ---------------------------------------------------------------------------

class TestTerrainContours:
    def _call(self, points, **kwargs) -> dict:
        from kerf_bim.tools.site_terrain import run_bim_terrain_contours
        params = {"points": points, **kwargs}
        return json.loads(_run(run_bim_terrain_contours(params, None)))

    def test_contours_generated(self):
        result = self._call(_survey_points())
        assert result["ok"] is True
        assert "contours" in result

    def test_contour_count_nonnegative(self):
        result = self._call(_survey_points())
        assert result["contour_count"] >= 0

    def test_custom_interval(self):
        result = self._call(_survey_points(), interval=1.0)
        assert result["ok"] is True

    def test_contour_structure_when_present(self):
        result = self._call(_survey_points(), interval=1.0)
        if result["contour_count"] > 0:
            c = result["contours"][0]
            assert "elevation" in c

    def test_flat_grid_minimal_contours(self):
        # A flat surface has no elevation range so at most 1 boundary contour
        result = self._call(_flat_grid(z=100.0), interval=1.0)
        assert result["ok"] is True
        assert result["contour_count"] <= 1

    def test_too_few_points_error(self):
        result = self._call([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        assert "error" in result

    def test_interval_in_result(self):
        result = self._call(_survey_points(), interval=2.0)
        assert result["ok"] is True
        assert result["interval_m"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 5. bim_terrain_cut_fill
# ---------------------------------------------------------------------------

class TestTerrainCutFill:
    def _call(self, existing_points, proposed_points, **kwargs) -> dict:
        from kerf_bim.tools.site_terrain import run_bim_terrain_cut_fill
        params = {"existing_points": existing_points, "proposed_points": proposed_points, **kwargs}
        return json.loads(_run(run_bim_terrain_cut_fill(params, None)))

    def _high_terrain(self):
        """Terrain at z=200 (well above proposed at z=100)."""
        return [[float(i), float(j), 200.0] for i in range(4) for j in range(4)]

    def _low_terrain(self):
        """Terrain at z=0 (well below proposed at z=100)."""
        return [[float(i), float(j), 0.0] for i in range(4) for j in range(4)]

    def _flat_100(self):
        return [[float(i), float(j), 100.0] for i in range(4) for j in range(4)]

    def test_pure_cut(self):
        # existing high, proposed low → all cut
        existing = self._high_terrain()
        proposed = _flat_grid(z=100.0)
        result = self._call(existing, proposed)
        assert result["ok"] is True
        assert result["cut_m3"] > 0
        assert result["fill_m3"] == pytest.approx(0.0, abs=0.01)

    def test_pure_fill(self):
        # existing low, proposed high → all fill
        existing = self._low_terrain()
        proposed = _flat_grid(z=100.0)
        result = self._call(existing, proposed)
        assert result["ok"] is True
        assert result["fill_m3"] > 0
        assert result["cut_m3"] == pytest.approx(0.0, abs=0.01)

    def _flat_100(self):
        return [[float(i), float(j), 100.0] for i in range(4) for j in range(4)]

    def test_net_volume_present(self):
        result = self._call(_survey_points(), self._flat_100())
        assert result["ok"] is True
        assert "net_m3" in result

    def test_flat_vs_flat_zero_volumes(self):
        same = _flat_grid(z=100.0)
        result = self._call(same, list(same))  # identical terrains
        assert result["ok"] is True
        assert result["cut_m3"] == pytest.approx(0.0, abs=0.1)
        assert result["fill_m3"] == pytest.approx(0.0, abs=0.1)

    def test_too_few_existing_error(self):
        result = self._call([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], _survey_points())
        assert "error" in result

    def test_too_few_proposed_error(self):
        result = self._call(_survey_points(), [[0.0, 0.0, 0.0]])
        assert "error" in result

    def test_grid_spacing_parameter(self):
        result = self._call(_survey_points(), self._flat_100(), grid_spacing=0.5)
        assert result["ok"] is True
        assert result["grid_spacing_m"] == pytest.approx(0.5)
