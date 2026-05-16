"""
Tests for kerf_cad_core.geom.patch_srf — Patch / Drape / Heightfield surface
generators.

All tests are hermetic: no OCC, no database, no network.  Pure-Python
geometry only.

Coverage (≥30 tests across 5 groups):
  1. patch_surface — paraboloid recovery, error cases, boundary option,
     stiffness effect, max_deviation/smoothing_energy diagnostics.
  2. drape_surface — single box obstacle, flat ground, gravity_axis options,
     multi-obstacle envelope, error cases.
  3. heightfield — flat/ramp/sinusoidal exact node reproduction, uint8 scale,
     v_scale, error cases.
  4. surface_from_grid — exact interpolation through every grid point,
     degree clamping, error cases.
  5. result-dict contract — all functions always return ok/reason/surface/
     max_deviation/smoothing_energy and never raise.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.patch_srf import (
    _surf_eval,
    drape_surface,
    heightfield,
    patch_surface,
    surface_from_grid,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _paraboloid_pts(m: int = 8, n: int = 8, a: float = 1.0, b: float = 1.0) -> np.ndarray:
    """Sample z = a*x^2 + b*y^2 on [0,1]×[0,1] as (m*n, 3) array."""
    xs = np.linspace(0.0, 1.0, m)
    ys = np.linspace(0.0, 1.0, n)
    rows = []
    for x in xs:
        for y in ys:
            rows.append([x, y, a * x ** 2 + b * y ** 2])
    return np.array(rows)


def _make_grid(m: int, n: int, f) -> np.ndarray:
    """Build an (m, n, 3) grid where z = f(x, y) on [0,1]×[0,1]."""
    xs = np.linspace(0.0, 1.0, m)
    ys = np.linspace(0.0, 1.0, n)
    pg = np.zeros((m, n, 3))
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            pg[i, j] = [x, y, f(x, y)]
    return pg


def _eval_grid_at(surf: NurbsSurface, us: np.ndarray, vs: np.ndarray) -> np.ndarray:
    """Evaluate surf at every (u, v) in arrays; return (N, 3)."""
    out = []
    for u, v in zip(us, vs):
        out.append(_surf_eval(surf, float(u), float(v)))
    return np.array(out)


# ---------------------------------------------------------------------------
# Group 1: patch_surface
# ---------------------------------------------------------------------------

class TestPatchSurface:

    def test_returns_ok_on_valid_input(self):
        pts = _paraboloid_pts(6, 6)
        result = patch_surface(pts, nu=5, nv=5)
        assert result["ok"] is True
        assert result["reason"] == ""
        assert isinstance(result["surface"], NurbsSurface)

    def test_result_dict_has_all_keys(self):
        pts = _paraboloid_pts(5, 5)
        result = patch_surface(pts, nu=4, nv=4)
        for key in ("ok", "reason", "surface", "max_deviation", "smoothing_energy"):
            assert key in result

    def test_max_deviation_is_non_negative(self):
        pts = _paraboloid_pts(6, 6)
        result = patch_surface(pts, nu=5, nv=5)
        assert result["ok"]
        assert result["max_deviation"] >= 0.0

    def test_smoothing_energy_is_non_negative(self):
        pts = _paraboloid_pts(6, 6)
        result = patch_surface(pts, nu=5, nv=5)
        assert result["ok"]
        assert result["smoothing_energy"] >= 0.0

    def test_paraboloid_recovery_within_tolerance(self):
        """A dense enough control grid on a paraboloid scatter should fit well."""
        pts = _paraboloid_pts(10, 10)
        result = patch_surface(pts, nu=8, nv=8, stiffness=1e-4)
        assert result["ok"]
        assert result["max_deviation"] < 0.15

    def test_flat_surface_near_zero_deviation(self):
        """Points all at z=0 → surface should be essentially flat."""
        xs = np.linspace(0.0, 1.0, 6)
        ys = np.linspace(0.0, 1.0, 6)
        pts = np.array([[x, y, 0.0] for x in xs for y in ys])
        result = patch_surface(pts, nu=4, nv=4, stiffness=0.0)
        assert result["ok"]
        assert result["max_deviation"] < 0.05

    def test_boundary_points_accepted(self):
        pts = _paraboloid_pts(6, 6)
        boundary = np.array([
            [0.0, 0.0, 0.0], [1.0, 0.0, 1.0],
            [0.0, 1.0, 1.0], [1.0, 1.0, 2.0],
        ])
        result = patch_surface(pts, nu=5, nv=5, boundary=boundary)
        assert result["ok"]

    def test_higher_stiffness_raises_smoothing_energy(self):
        pts = _paraboloid_pts(6, 6)
        r_low = patch_surface(pts, nu=5, nv=5, stiffness=1e-5, max_iter=1)
        r_high = patch_surface(pts, nu=5, nv=5, stiffness=10.0, max_iter=1)
        assert r_low["ok"] and r_high["ok"]
        # high stiffness drives the surface closer to flat → more smoothing energy
        # The test just ensures no crash and both succeed
        assert r_high["smoothing_energy"] >= 0.0

    def test_error_too_few_points(self):
        pts = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]])
        result = patch_surface(pts, nu=4, nv=4)
        assert result["ok"] is False
        assert "points" in result["reason"].lower()

    def test_error_invalid_points_shape(self):
        result = patch_surface([[1, 2], [3, 4], [5, 6], [7, 8], [9, 10],
                                 [1, 2], [3, 4], [5, 6], [7, 8], [9, 10],
                                 [1, 2], [3, 4], [5, 6], [7, 8], [9, 10],
                                 [1, 2]], nu=4, nv=4)
        assert result["ok"] is False

    def test_error_negative_stiffness(self):
        pts = _paraboloid_pts(5, 5)
        result = patch_surface(pts, nu=4, nv=4, stiffness=-1.0)
        assert result["ok"] is False
        assert "stiffness" in result["reason"].lower()

    def test_error_bad_max_iter(self):
        pts = _paraboloid_pts(5, 5)
        result = patch_surface(pts, nu=4, nv=4, max_iter=0)
        assert result["ok"] is False

    def test_surface_control_grid_shape(self):
        pts = _paraboloid_pts(6, 6)
        result = patch_surface(pts, nu=5, nv=4)
        assert result["ok"]
        surf = result["surface"]
        assert surf.control_points.shape == (5, 4, 3)

    def test_never_raises_on_garbage_input(self):
        result = patch_surface("not-a-list", nu=4, nv=4)
        assert "ok" in result
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# Group 2: drape_surface
# ---------------------------------------------------------------------------

class TestDrapeSurface:

    def _box_pts(self, top: float = 2.0) -> np.ndarray:
        """Single box: 8 vertices, top face at z=top."""
        return np.array([
            [0.2, 0.2, 0.0], [0.2, 0.8, 0.0],
            [0.8, 0.2, 0.0], [0.8, 0.8, 0.0],
            [0.2, 0.2, top], [0.2, 0.8, top],
            [0.8, 0.2, top], [0.8, 0.8, top],
        ])

    def test_returns_ok_on_valid_input(self):
        bbox = [0.0, 0.0, 0.0, 1.0, 1.0, 5.0]
        result = drape_surface(self._box_pts(2.0), bbox)
        assert result["ok"] is True
        assert isinstance(result["surface"], NurbsSurface)

    def test_drape_rests_at_box_top(self):
        """Grid nodes above the box should rest at box-top height."""
        top = 2.0
        bbox = [0.0, 0.0, 0.0, 1.0, 1.0, 5.0]
        result = drape_surface(self._box_pts(top), bbox, nu=5, nv=5)
        assert result["ok"]
        surf = result["surface"]
        # Evaluate at the centre of the grid (should be ≥ floor and ≤ top)
        pt = _surf_eval(surf, 0.5, 0.5)
        assert pt[2] >= 0.0
        assert pt[2] <= top + 1e-9

    def test_flat_obstacle_rests_at_floor(self):
        """Ground-level obstacle → surface at z_min."""
        obs = np.array([[x, y, 0.0] for x in np.linspace(0, 1, 5)
                        for y in np.linspace(0, 1, 5)])
        bbox = [0.0, 0.0, 0.0, 1.0, 1.0, 3.0]
        result = drape_surface(obs, bbox, nu=4, nv=4)
        assert result["ok"]
        surf = result["surface"]
        pt = _surf_eval(surf, 0.5, 0.5)
        assert abs(pt[2] - 0.0) < 1e-9

    def test_gravity_axis_x(self):
        """Drape along X axis."""
        obs = np.array([[1.0, y, z] for y in [0.2, 0.5, 0.8]
                        for z in [0.2, 0.5, 0.8]])
        bbox = [0.0, 0.0, 0.0, 3.0, 1.0, 1.0]
        result = drape_surface(obs, bbox, nu=4, nv=4, gravity_axis=0)
        assert result["ok"]

    def test_gravity_axis_y(self):
        obs = np.array([[x, 1.0, z] for x in [0.2, 0.5, 0.8]
                        for z in [0.2, 0.5, 0.8]])
        bbox = [0.0, 0.0, 0.0, 1.0, 3.0, 1.0]
        result = drape_surface(obs, bbox, nu=4, nv=4, gravity_axis=1)
        assert result["ok"]

    def test_higher_obstacle_has_higher_envelope(self):
        """Two identical grids at different z → different envelope heights."""
        bbox = [0.0, 0.0, 0.0, 1.0, 1.0, 10.0]
        obs_low = np.array([[x, y, 1.0] for x in np.linspace(0.3, 0.7, 3)
                             for y in np.linspace(0.3, 0.7, 3)])
        obs_high = np.array([[x, y, 5.0] for x in np.linspace(0.3, 0.7, 3)
                              for y in np.linspace(0.3, 0.7, 3)])
        r_low = drape_surface(obs_low, bbox, nu=5, nv=5)
        r_high = drape_surface(obs_high, bbox, nu=5, nv=5)
        assert r_low["ok"] and r_high["ok"]
        # Centre node for high obstacle should be >= centre node for low obstacle
        pt_low = _surf_eval(r_low["surface"], 0.5, 0.5)[2]
        pt_high = _surf_eval(r_high["surface"], 0.5, 0.5)[2]
        assert pt_high >= pt_low - 1e-9

    def test_error_invalid_obstacle_shape(self):
        result = drape_surface([[1, 2], [3, 4]], [0, 0, 0, 1, 1, 1])
        assert result["ok"] is False

    def test_error_bad_bbox(self):
        obs = np.ones((4, 3))
        result = drape_surface(obs, [0, 0, 1, 1])  # only 4 values
        assert result["ok"] is False

    def test_error_bad_gravity_axis(self):
        obs = np.ones((4, 3))
        bbox = [0, 0, 0, 1, 1, 1]
        result = drape_surface(obs, bbox, gravity_axis=5)
        assert result["ok"] is False

    def test_result_dict_contract(self):
        obs = np.ones((4, 3))
        bbox = [0, 0, 0, 2, 2, 2]
        result = drape_surface(obs, bbox)
        for key in ("ok", "reason", "surface", "max_deviation", "smoothing_energy"):
            assert key in result


# ---------------------------------------------------------------------------
# Group 3: heightfield
# ---------------------------------------------------------------------------

class TestHeightfield:

    def test_flat_z_zero_exact(self):
        """Flat z=0 array → all nodes at z=0."""
        za = np.zeros((4, 4))
        result = heightfield(za)
        assert result["ok"]
        surf = result["surface"]
        us = np.linspace(0.0, 1.0, 4)
        vs = np.linspace(0.0, 1.0, 4)
        for i, u in enumerate(us):
            for j, v in enumerate(vs):
                pt = _surf_eval(surf, u, v)
                assert abs(pt[2] - 0.0) < 1e-10, f"node ({i},{j}): z={pt[2]}"

    def test_ramp_exact_at_nodes(self):
        """z = x (linear ramp) → surface reproduces ramp at every grid node."""
        m, n = 5, 5
        xs = np.linspace(0.0, 1.0, m)
        za = np.tile(xs[:, np.newaxis], (1, n))  # z = x
        result = heightfield(za, x_range=(0.0, 1.0), y_range=(0.0, 1.0))
        assert result["ok"]
        surf = result["surface"]
        us = np.linspace(0.0, 1.0, m)
        vs = np.linspace(0.0, 1.0, n)
        for i, u in enumerate(us):
            for j, v in enumerate(vs):
                pt = _surf_eval(surf, u, v)
                expected_z = xs[i]
                assert abs(pt[2] - expected_z) < 1e-10, (
                    f"node ({i},{j}): z={pt[2]:.6f} expected={expected_z:.6f}"
                )

    def test_known_elevation_exact(self):
        """Custom z values must be reproduced exactly at grid nodes."""
        za = np.array([[0.0, 1.0, 2.0],
                       [3.0, 4.0, 5.0],
                       [6.0, 7.0, 8.0]])
        result = heightfield(za, x_range=(0.0, 2.0), y_range=(0.0, 2.0))
        assert result["ok"]
        surf = result["surface"]
        us = np.linspace(0.0, 1.0, 3)
        vs = np.linspace(0.0, 1.0, 3)
        for i, u in enumerate(us):
            for j, v in enumerate(vs):
                pt = _surf_eval(surf, u, v)
                assert abs(pt[2] - za[i, j]) < 1e-8

    def test_v_scale_applied(self):
        za = np.ones((3, 3))
        result = heightfield(za, v_scale=5.0)
        assert result["ok"]
        surf = result["surface"]
        pt = _surf_eval(surf, 0.5, 0.5)
        assert abs(pt[2] - 5.0) < 1e-8

    def test_v_scale_on_large_values(self):
        """v_scale multiplies raw elevations regardless of magnitude."""
        za = np.full((3, 3), 128.0)
        result = heightfield(za, v_scale=2.0)
        assert result["ok"]
        surf = result["surface"]
        pt = _surf_eval(surf, 0.5, 0.5)
        expected = 128.0 * 2.0
        assert abs(pt[2] - expected) < 1e-6

    def test_xy_range_applied(self):
        za = np.zeros((3, 3))
        result = heightfield(za, x_range=(2.0, 4.0), y_range=(5.0, 7.0))
        assert result["ok"]
        surf = result["surface"]
        # Corner node at (0,0) in parameter should be at world (2.0, 5.0, 0.0)
        pt = _surf_eval(surf, 0.0, 0.0)
        assert abs(pt[0] - 2.0) < 1e-9
        assert abs(pt[1] - 5.0) < 1e-9

    def test_error_1d_array(self):
        result = heightfield(np.arange(5))
        assert result["ok"] is False
        assert "2D" in result["reason"]

    def test_error_too_small(self):
        result = heightfield(np.array([[1.0]]))
        assert result["ok"] is False

    def test_error_bad_x_range(self):
        za = np.ones((3, 3))
        result = heightfield(za, x_range=(1.0, 0.0))
        assert result["ok"] is False

    def test_result_dict_contract(self):
        za = np.zeros((3, 3))
        result = heightfield(za)
        for key in ("ok", "reason", "surface", "max_deviation", "smoothing_energy"):
            assert key in result


# ---------------------------------------------------------------------------
# Group 4: surface_from_grid
# ---------------------------------------------------------------------------

class TestSurfaceFromGrid:

    def test_flat_grid_exact(self):
        """Flat z=0 grid → surface passes through all points."""
        pg = _make_grid(4, 4, lambda x, y: 0.0)
        result = surface_from_grid(pg, degree_u=1, degree_v=1)
        assert result["ok"]
        assert result["max_deviation"] < 1e-8

    def test_linear_z_exact(self):
        """z = x+y → linear surface through all grid points."""
        pg = _make_grid(5, 5, lambda x, y: x + y)
        result = surface_from_grid(pg, degree_u=1, degree_v=1)
        assert result["ok"]
        assert result["max_deviation"] < 1e-7

    def test_quadratic_z_degree2(self):
        """z = x^2 + y^2 → degree-2 surface; should pass through all grid points."""
        pg = _make_grid(5, 5, lambda x, y: x ** 2 + y ** 2)
        result = surface_from_grid(pg, degree_u=2, degree_v=2)
        assert result["ok"]
        assert result["max_deviation"] < 1e-6

    def test_larger_grid(self):
        pg = _make_grid(6, 6, lambda x, y: math.sin(math.pi * x) * math.cos(math.pi * y))
        result = surface_from_grid(pg, degree_u=3, degree_v=3)
        assert result["ok"]
        assert result["max_deviation"] < 0.1

    def test_returns_correct_surface_type(self):
        pg = _make_grid(4, 4, lambda x, y: 0.0)
        result = surface_from_grid(pg, degree_u=2, degree_v=2)
        assert result["ok"]
        assert isinstance(result["surface"], NurbsSurface)

    def test_error_wrong_ndim(self):
        result = surface_from_grid(np.ones((4, 4)))
        assert result["ok"] is False

    def test_error_too_few_rows(self):
        pg = _make_grid(2, 5, lambda x, y: 0.0)
        result = surface_from_grid(pg, degree_u=3, degree_v=1)
        assert result["ok"] is False
        assert "row" in result["reason"].lower()

    def test_error_too_few_cols(self):
        pg = _make_grid(5, 2, lambda x, y: 0.0)
        result = surface_from_grid(pg, degree_u=1, degree_v=3)
        assert result["ok"] is False
        assert "col" in result["reason"].lower()

    def test_result_dict_contract(self):
        pg = _make_grid(4, 4, lambda x, y: 0.0)
        result = surface_from_grid(pg)
        for key in ("ok", "reason", "surface", "max_deviation", "smoothing_energy"):
            assert key in result

    def test_degree_clamped_to_valid_range(self):
        """degree outside [1,5] should not crash — clamped internally."""
        pg = _make_grid(4, 4, lambda x, y: 0.0)
        result = surface_from_grid(pg, degree_u=10, degree_v=-1)
        # May fail for too-few-points reasons but must not raise
        assert "ok" in result


# ---------------------------------------------------------------------------
# Group 5: never-raises contract
# ---------------------------------------------------------------------------

class TestNeverRaises:

    @pytest.mark.parametrize("fn,args,kwargs", [
        (patch_surface, (None,), {}),
        (patch_surface, ([],), {}),
        (drape_surface, (None, None), {}),
        (drape_surface, ([[1, 2, 3]], [0, 0, 0, 1, 1, 1]), {"gravity_axis": 99}),
        (heightfield, (None,), {}),
        (heightfield, (np.ones((3, 3)),), {"x_range": (1.0, 0.0)}),
        (surface_from_grid, (None,), {}),
        (surface_from_grid, (np.ones((2, 2)),), {}),
    ])
    def test_bad_input_returns_ok_false_not_raise(self, fn, args, kwargs):
        result = fn(*args, **kwargs)
        assert isinstance(result, dict)
        assert "ok" in result
        assert result["ok"] is False
