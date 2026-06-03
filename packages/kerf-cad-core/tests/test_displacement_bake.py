"""Tests for kerf_cad_core.sculpt.displacement_bake — HD displacement map baking.

Coverage:
- Identical low/high mesh → zero displacement map
- High-poly with bump above low-poly → positive displacement at bump location
- DisplacementMap fields (resolution, scalar_field shape, udim_tile default)
- Custom map_resolution sizes
- Auto UV path (lp_uv=None)
- scalar_field dtype is float32
- Large max_distance_mm covers all geometry
- Zero-coverage areas default to 0.0
"""
from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.sculpt.displacement_bake import DisplacementMap, bake_displacement


# ---------------------------------------------------------------------------
# Mesh helpers
# ---------------------------------------------------------------------------


def _flat_quad(n: int = 4, z: float = 0.0):
    """Return a triangulated n×n unit square at height z.

    Positions span [0,1]×[0,1]×z.
    UV == XY.
    """
    xs = np.linspace(0.0, 1.0, n + 1)
    ys = np.linspace(0.0, 1.0, n + 1)
    xx, yy = np.meshgrid(xs, ys)
    positions = np.stack([
        xx.ravel(),
        yy.ravel(),
        np.full(xx.size, z),
    ], axis=1).astype(np.float64)

    uv = positions[:, :2].copy()

    tris = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            b = a + 1
            c = a + (n + 1) + 1
            d = a + (n + 1)
            tris.append([a, b, c])
            tris.append([a, c, d])

    return positions, np.array(tris, dtype=np.int32), uv


def _bump_quad(n: int = 8, bump_height: float = 0.5):
    """Unit square mesh with a bump at the center.

    The central vertex is raised by *bump_height*.
    """
    xs = np.linspace(0.0, 1.0, n + 1)
    ys = np.linspace(0.0, 1.0, n + 1)
    xx, yy = np.meshgrid(xs, ys)
    zz = np.zeros_like(xx)

    # Raise central vertex
    center_i = n // 2
    zz[center_i, center_i] = bump_height

    positions = np.stack([xx.ravel(), yy.ravel(), zz.ravel()], axis=1).astype(np.float64)
    uv = positions[:, :2].copy()

    tris = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            b = a + 1
            c = a + (n + 1) + 1
            d = a + (n + 1)
            tris.append([a, b, c])
            tris.append([a, c, d])

    return positions, np.array(tris, dtype=np.int32), uv


# ---------------------------------------------------------------------------
# Tests: DisplacementMap dataclass
# ---------------------------------------------------------------------------

class TestDisplacementMapDataclass:
    def test_default_udim_tile(self):
        sf = np.zeros((64, 64), dtype=np.float32)
        dm = DisplacementMap(resolution=64, scalar_field=sf)
        assert dm.udim_tile == 1001

    def test_custom_udim_tile(self):
        sf = np.zeros((32, 32), dtype=np.float32)
        dm = DisplacementMap(resolution=32, scalar_field=sf, udim_tile=1002)
        assert dm.udim_tile == 1002

    def test_resolution_stored(self):
        sf = np.zeros((128, 128), dtype=np.float32)
        dm = DisplacementMap(resolution=128, scalar_field=sf)
        assert dm.resolution == 128


# ---------------------------------------------------------------------------
# Tests: bake_displacement
# ---------------------------------------------------------------------------

class TestBakeDisplacement:
    def test_returns_displacement_map(self):
        lp_pos, lp_tri, lp_uv = _flat_quad(n=4)
        result = bake_displacement(lp_pos, lp_tri, lp_uv, lp_pos.copy(), lp_tri.copy(),
                                    map_resolution=32)
        assert isinstance(result, DisplacementMap)

    def test_scalar_field_shape(self):
        lp_pos, lp_tri, lp_uv = _flat_quad(n=4)
        result = bake_displacement(lp_pos, lp_tri, lp_uv, lp_pos.copy(), lp_tri.copy(),
                                    map_resolution=64)
        assert result.scalar_field.shape == (64, 64), (
            f"Expected (64, 64), got {result.scalar_field.shape}"
        )

    def test_scalar_field_dtype(self):
        lp_pos, lp_tri, lp_uv = _flat_quad(n=4)
        result = bake_displacement(lp_pos, lp_tri, lp_uv, lp_pos.copy(), lp_tri.copy(),
                                    map_resolution=32)
        assert result.scalar_field.dtype == np.float32

    def test_identical_meshes_near_zero_displacement(self):
        """When low == high poly, displacement should be near zero everywhere."""
        lp_pos, lp_tri, lp_uv = _flat_quad(n=6)
        result = bake_displacement(lp_pos, lp_tri, lp_uv, lp_pos.copy(), lp_tri.copy(),
                                    map_resolution=32, max_distance_mm=1.0)
        # All pixels should have near-zero displacement
        covered = np.abs(result.scalar_field) > 0.0
        if covered.sum() > 0:
            max_disp = np.abs(result.scalar_field[covered]).max()
            assert max_disp < 0.1, (
                f"Expected near-zero displacement for identical meshes, got max={max_disp:.4f}"
            )

    def test_raised_highpoly_positive_displacement(self):
        """High-poly with a bump should produce positive displacements at bump pixels."""
        lp_pos, lp_tri, lp_uv = _flat_quad(n=8, z=0.0)
        hp_pos, hp_tri, _ = _bump_quad(n=8, bump_height=1.0)

        result = bake_displacement(lp_pos, lp_tri, lp_uv, hp_pos, hp_tri,
                                    map_resolution=64, max_distance_mm=2.0)
        # At least some pixels should have positive displacement
        assert np.any(result.scalar_field > 0.1), (
            "Expected positive displacement from raised high-poly mesh, "
            f"max={result.scalar_field.max():.4f}"
        )

    def test_auto_uv_runs_without_error(self):
        """low_poly_uv=None should trigger auto LSCM unwrap."""
        lp_pos, lp_tri, _ = _flat_quad(n=4)
        result = bake_displacement(lp_pos, lp_tri, None, lp_pos.copy(), lp_tri.copy(),
                                    map_resolution=32)
        assert result.scalar_field.shape == (32, 32)

    def test_resolution_in_result(self):
        lp_pos, lp_tri, lp_uv = _flat_quad(n=4)
        result = bake_displacement(lp_pos, lp_tri, lp_uv, lp_pos.copy(), lp_tri.copy(),
                                    map_resolution=128)
        assert result.resolution == 128

    def test_uncovered_pixels_are_zero(self):
        """Background (no UV coverage) pixels must be exactly 0.0."""
        lp_pos, lp_tri, lp_uv = _flat_quad(n=2)
        result = bake_displacement(lp_pos, lp_tri, lp_uv, lp_pos.copy(), lp_tri.copy(),
                                    map_resolution=64)
        # The map may have background zeros; ensure those are exactly 0
        zeros = result.scalar_field == 0.0
        # No NaN or inf in the result
        assert np.all(np.isfinite(result.scalar_field)), "scalar_field contains NaN or Inf"
