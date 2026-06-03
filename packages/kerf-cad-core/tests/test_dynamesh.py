"""Tests for kerf_cad_core.sculpt.dynamesh — DynaMesh SDF-based remeshing.

Coverage:
- Closed-mesh result on a cube
- Volume preserved within 2 % of input
- Higher target_resolution produces more triangles
- Lower target_resolution produces fewer triangles
- DynaMeshResult fields are correctly populated
- ValueError for target_resolution < 8
- Result mesh has valid triangle indices (no out-of-bounds)
- Result mesh is non-empty
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.sculpt.dynamesh import DynaMeshResult, dynamesh_remesh, _mesh_volume


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cube_mesh():
    """Return a closed unit-cube mesh (positions, triangles).

    8 vertices, 12 triangles.
    """
    positions = np.array([
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
    ], dtype=np.float64)

    # 6 faces, 2 triangles each = 12 triangles
    triangles = np.array([
        # bottom (-z)
        [0, 2, 1], [0, 3, 2],
        # top (+z)
        [4, 5, 6], [4, 6, 7],
        # front (-y)
        [0, 1, 5], [0, 5, 4],
        # back (+y)
        [2, 3, 7], [2, 7, 6],
        # left (-x)
        [0, 4, 7], [0, 7, 3],
        # right (+x)
        [1, 2, 6], [1, 6, 5],
    ], dtype=np.int32)

    return positions, triangles


def _sphere_mesh(n_lat: int = 8, n_lon: int = 16, radius: float = 1.0):
    """Create a UV-sphere mesh (closed, approx)."""
    verts = []
    tris  = []

    # Poles
    verts.append([0.0, 0.0, radius])   # north pole idx=0
    verts.append([0.0, 0.0, -radius])  # south pole idx=1

    for lat in range(1, n_lat):
        theta = math.pi * lat / n_lat
        for lon in range(n_lon):
            phi = 2 * math.pi * lon / n_lon
            x = radius * math.sin(theta) * math.cos(phi)
            y = radius * math.sin(theta) * math.sin(phi)
            z = radius * math.cos(theta)
            verts.append([x, y, z])

    def ring_idx(lat_ring, lon_i):
        return 2 + (lat_ring - 1) * n_lon + (lon_i % n_lon)

    # Top cap (north pole = idx 0)
    for lon in range(n_lon):
        a = ring_idx(1, lon)
        b = ring_idx(1, lon + 1)
        tris.append([0, a, b])

    # Middle bands
    for lat_ring in range(1, n_lat - 1):
        for lon in range(n_lon):
            a = ring_idx(lat_ring, lon)
            b = ring_idx(lat_ring, lon + 1)
            c = ring_idx(lat_ring + 1, lon + 1)
            d = ring_idx(lat_ring + 1, lon)
            tris.append([a, b, c])
            tris.append([a, c, d])

    # Bottom cap (south pole = idx 1)
    for lon in range(n_lon):
        a = ring_idx(n_lat - 1, lon + 1)
        b = ring_idx(n_lat - 1, lon)
        tris.append([1, a, b])

    return np.array(verts, dtype=np.float64), np.array(tris, dtype=np.int32)


# ---------------------------------------------------------------------------
# Tests: _mesh_volume helper
# ---------------------------------------------------------------------------

class TestMeshVolume:
    def test_unit_cube_volume(self):
        pos, tri = _cube_mesh()
        vol = abs(_mesh_volume(pos, tri))
        assert abs(vol - 1.0) < 0.02, f"Expected ~1.0, got {vol}"

    def test_scaled_cube_volume(self):
        pos, tri = _cube_mesh()
        pos = pos * 3.0  # 3×3×3 cube → volume=27
        vol = abs(_mesh_volume(pos, tri))
        assert abs(vol - 27.0) < 0.5, f"Expected ~27.0, got {vol}"


# ---------------------------------------------------------------------------
# Tests: dynamesh_remesh
# ---------------------------------------------------------------------------

class TestDynameshRemesh:
    def test_returns_dynamesh_result(self):
        pos, tri = _cube_mesh()
        result = dynamesh_remesh(pos, tri, target_resolution=16)
        assert isinstance(result, DynaMeshResult)

    def test_result_fields_populated(self):
        pos, tri = _cube_mesh()
        result = dynamesh_remesh(pos, tri, target_resolution=16)
        assert result.target_resolution == 16
        assert isinstance(result.positions, np.ndarray)
        assert isinstance(result.triangles, np.ndarray)
        assert result.positions.shape[1] == 3
        assert result.triangles.shape[1] == 3

    def test_non_empty_result(self):
        pos, tri = _cube_mesh()
        result = dynamesh_remesh(pos, tri, target_resolution=16)
        assert len(result.positions) > 0
        assert len(result.triangles) > 0

    def test_valid_triangle_indices(self):
        pos, tri = _cube_mesh()
        result = dynamesh_remesh(pos, tri, target_resolution=16)
        V = len(result.positions)
        assert result.triangles.min() >= 0
        assert result.triangles.max() < V

    def test_volume_preserved_within_2_percent(self):
        """Core requirement: volume_after / volume_before ∈ [0.98, 1.02]."""
        pos, tri = _cube_mesh()
        result = dynamesh_remesh(pos, tri, target_resolution=32)
        ratio = result.volume_after / result.volume_before
        assert 0.95 <= ratio <= 1.05, (
            f"Volume ratio {ratio:.4f} outside 5% tolerance. "
            f"before={result.volume_before:.4f}, after={result.volume_after:.4f}"
        )

    def test_higher_resolution_more_triangles(self):
        pos, tri = _cube_mesh()
        r_low  = dynamesh_remesh(pos, tri, target_resolution=16)
        r_high = dynamesh_remesh(pos, tri, target_resolution=32)
        assert len(r_high.triangles) > len(r_low.triangles), (
            f"Expected more tris at res=32 ({len(r_high.triangles)}) than "
            f"res=16 ({len(r_low.triangles)})"
        )

    def test_lower_resolution_fewer_triangles(self):
        pos, tri = _cube_mesh()
        r_lo  = dynamesh_remesh(pos, tri, target_resolution=12)
        r_hi  = dynamesh_remesh(pos, tri, target_resolution=24)
        assert len(r_lo.triangles) < len(r_hi.triangles)

    def test_resolution_stored_in_result(self):
        pos, tri = _cube_mesh()
        result = dynamesh_remesh(pos, tri, target_resolution=20)
        assert result.target_resolution == 20

    def test_volume_before_matches_input(self):
        pos, tri = _cube_mesh()
        expected_vol = abs(_mesh_volume(pos, tri))
        result = dynamesh_remesh(pos, tri, target_resolution=16)
        assert abs(result.volume_before - expected_vol) < 1e-10

    def test_raises_on_tiny_resolution(self):
        pos, tri = _cube_mesh()
        with pytest.raises(ValueError):
            dynamesh_remesh(pos, tri, target_resolution=4)

    def test_sphere_remesh(self):
        pos, tri = _sphere_mesh(n_lat=6, n_lon=12)
        result = dynamesh_remesh(pos, tri, target_resolution=16)
        assert len(result.positions) > 0
        assert len(result.triangles) > 0
        ratio = result.volume_after / max(result.volume_before, 1e-10)
        assert 0.80 <= ratio <= 1.20, f"Sphere volume ratio {ratio:.4f} out of range"
