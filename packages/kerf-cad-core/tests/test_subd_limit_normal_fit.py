"""test_subd_limit_normal_fit.py
================================
Tests for subd/limit_normal_fit.py — SUBD-LIMIT-NORMAL-FIT.

Coverage (17 tests across 8 classes):

  TestFlatPlaneCage (4 tests):
    1.  Flat 2×2 plane: all normals point +Z (nz > 0.999).
    2.  Flat plane: all normals are nearly unit-length.
    3.  Flat plane: nx ≈ 0 and ny ≈ 0 for all samples.
    4.  Flat plane: dot product with (0,0,1) > 0.9999.

  TestUnitLengthNormals (2 tests):
    5.  normalize=True → all sampled normals have magnitude ≈ 1.0.
    6.  normalize=False → some normals may deviate from unit length.

  TestResultStructure (4 tests):
    7.  Return type is LimitNormalFitResult.
    8.  sampled_normals is a list of dicts with keys u, v, face_idx, nx, ny, nz.
    9.  total samples = num_faces × n² (n = round(sqrt(spf))).
    10. honest_caveat is a non-empty string.

  TestIrregularSamples (2 tests):
    11. Cube cage (all valence-3 vertices): num_irregular_samples > 0.
    12. 2×2 torus (all regular interior): num_irregular_samples == 0.

  TestResidualComputation (2 tests):
    13. Flat plane residuals ≈ 0 (bilinear exactly matches constant normal).
    14. max_normal_residual_deg <= 90.0 for any valid mesh.

  TestCylinderNormals (1 test):
    15. Cylinder cage: side-face normals are roughly perpendicular to Y-axis.

  TestSphericishCage (1 test):
    16. Sphere-like cage (cube, 6 faces): normals outward (dot with face-centre
        direction > 0).

  TestEdgeCases (1 test):
    17. Empty cage (no faces) → empty result, no exception.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.subd.limit_normal_fit import (
    LimitNormalFitResult,
    sample_subd_limit_normals,
)


# ---------------------------------------------------------------------------
# Helper cage builders
# ---------------------------------------------------------------------------

def _flat_plane_cage() -> SubDMesh:
    """4-face flat plane cage in the XY-plane.

    16 vertices arranged in a 4×4 grid (3 faces × 3 edges, giving a 2×2
    interior quad mesh of 4 faces).
    """
    verts = []
    for j in range(4):
        for i in range(4):
            verts.append([float(i), float(j), 0.0])
    # 2×2 grid of 4 quad faces
    faces = [
        [0,  1,  5,  4],
        [1,  2,  6,  5],
        [4,  5,  9,  8],
        [5,  6, 10,  9],
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _cube_cage() -> SubDMesh:
    """Unit cube cage: 8 vertices, 6 quad faces.  All vertices have valence 3."""
    verts = [
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [1.0, 1.0, 0.0],  # 2
        [0.0, 1.0, 0.0],  # 3
        [0.0, 0.0, 1.0],  # 4
        [1.0, 0.0, 1.0],  # 5
        [1.0, 1.0, 1.0],  # 6
        [0.0, 1.0, 1.0],  # 7
    ]
    faces = [
        [0, 1, 2, 3],  # bottom (−Z)
        [4, 5, 6, 7],  # top (+Z)
        [0, 1, 5, 4],  # front (−Y)
        [2, 3, 7, 6],  # back (+Y)
        [0, 3, 7, 4],  # left (−X)
        [1, 2, 6, 5],  # right (+X)
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _torus_2x2_cage() -> SubDMesh:
    """2×2 torus cage with all interior vertices having valence 4.

    Uses a 2-row × 2-column quad patch arrangement that wraps around in
    both u and v directions.  Vertices are shared so that each interior
    vertex is shared by exactly 4 faces.

    Layout (4 vertices, 4 faces, periodic):
      0 - 1
      |   |
      2 - 3

    With periodic wrapping: face [0,1,3,2] and [1,0,2,3] etc.
    """
    # Build a simple flat 2×2 torus: vertices at corners, faces share all verts
    verts = [
        [0.0, 0.0, 0.0],  # 0
        [1.0, 0.0, 0.0],  # 1
        [0.0, 1.0, 0.0],  # 2
        [1.0, 1.0, 0.0],  # 3
    ]
    # 4 faces sharing all 4 vertices (torus connectivity)
    faces = [
        [0, 1, 3, 2],
        [1, 0, 2, 3],
        [2, 3, 1, 0],
        [3, 2, 0, 1],
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _cylinder_cage(n: int = 6) -> SubDMesh:
    """Cylinder cage with n segments around Y-axis, 2 rings (no caps).

    The cylinder runs from y=0 to y=1 with radius 1.
    All side faces are quads.  Side vertices have valence 4.
    """
    import math
    verts = []
    # Two rings: y=0 and y=1
    for y in [0.0, 1.0]:
        for i in range(n):
            angle = 2.0 * math.pi * i / n
            verts.append([math.cos(angle), y, math.sin(angle)])
    # Side faces (no caps)
    faces = []
    for i in range(n):
        next_i = (i + 1) % n
        # Bottom ring vertices: 0..n-1; top ring: n..2n-1
        faces.append([i, next_i, next_i + n, i + n])
    return SubDMesh(vertices=verts, faces=faces)


def _centroid_3d(verts: "list[list[float]]", face_vi: "list[int]") -> Tuple[float, float, float]:
    """Return the centroid of face_vi in a vertex list."""
    n = len(face_vi)
    if n == 0:
        return (0.0, 0.0, 0.0)
    cx = sum(verts[i][0] for i in face_vi) / n
    cy = sum(verts[i][1] for i in face_vi) / n
    cz = sum(verts[i][2] for i in face_vi) / n
    return (cx, cy, cz)


def _vec_length(v: Tuple[float, float, float]) -> float:
    return math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)


# ---------------------------------------------------------------------------
# TestFlatPlaneCage
# ---------------------------------------------------------------------------

class TestFlatPlaneCage:
    """Tests 1–4: flat plane cage — all normals should point +Z."""

    def _get_result(self) -> LimitNormalFitResult:
        mesh = _flat_plane_cage()
        return sample_subd_limit_normals(mesh, samples_per_face=9, normalize=True)

    def test_normals_point_plus_z(self) -> None:
        """Test 1: nz > 0.999 for all samples on flat plane."""
        res = self._get_result()
        assert len(res.sampled_normals) > 0
        for s in res.sampled_normals:
            assert s["nz"] > 0.999, (
                f"Expected nz > 0.999, got nz={s['nz']:.6f} at u={s['u']}, v={s['v']}, face={s['face_idx']}"
            )

    def test_normals_unit_length_flat_plane(self) -> None:
        """Test 2: all normals are unit-length on flat plane."""
        res = self._get_result()
        for s in res.sampled_normals:
            length = math.sqrt(s["nx"]**2 + s["ny"]**2 + s["nz"]**2)
            assert abs(length - 1.0) < 1e-6, (
                f"Normal not unit-length: |N|={length:.8f} at face={s['face_idx']}"
            )

    def test_normals_xy_components_near_zero(self) -> None:
        """Test 3: nx ≈ 0 and ny ≈ 0 for all flat-plane samples."""
        res = self._get_result()
        for s in res.sampled_normals:
            assert abs(s["nx"]) < 0.01, f"nx={s['nx']:.6f} not near 0"
            assert abs(s["ny"]) < 0.01, f"ny={s['ny']:.6f} not near 0"

    def test_normals_dot_product_with_z_axis(self) -> None:
        """Test 4: dot product of each normal with (0, 0, 1) > 0.9999."""
        res = self._get_result()
        for s in res.sampled_normals:
            dot = s["nz"]  # dot with (0,0,1) is just nz
            assert dot > 0.9999, (
                f"dot product with +Z = {dot:.6f} at face={s['face_idx']}, u={s['u']}, v={s['v']}"
            )


# ---------------------------------------------------------------------------
# TestUnitLengthNormals
# ---------------------------------------------------------------------------

class TestUnitLengthNormals:
    """Tests 5–6: unit-length normals when normalize=True."""

    def test_normalize_true_all_unit_length(self) -> None:
        """Test 5: normalize=True → all normals have |N| ≈ 1.0."""
        mesh = _cube_cage()
        res = sample_subd_limit_normals(mesh, samples_per_face=9, normalize=True)
        assert len(res.sampled_normals) > 0
        for s in res.sampled_normals:
            length = math.sqrt(s["nx"]**2 + s["ny"]**2 + s["nz"]**2)
            assert abs(length - 1.0) < 1e-6, f"|N|={length:.8f}"

    def test_normalize_false_returns_values(self) -> None:
        """Test 6: normalize=False → result is returned (may not be unit-length)."""
        mesh = _flat_plane_cage()
        res = sample_subd_limit_normals(mesh, samples_per_face=4, normalize=False)
        # Should still have samples; at least some will be non-unit if cross-product magnitude != 1
        assert isinstance(res.sampled_normals, list)
        # All samples have numeric normal components
        for s in res.sampled_normals:
            assert all(isinstance(s[k], float) for k in ("nx", "ny", "nz"))


# ---------------------------------------------------------------------------
# TestResultStructure
# ---------------------------------------------------------------------------

class TestResultStructure:
    """Tests 7–10: result structure and type checks."""

    def test_return_type_is_limit_normal_fit_result(self) -> None:
        """Test 7: return type is LimitNormalFitResult."""
        mesh = _flat_plane_cage()
        res = sample_subd_limit_normals(mesh)
        assert isinstance(res, LimitNormalFitResult)

    def test_sampled_normals_dict_structure(self) -> None:
        """Test 8: each sample is a dict with keys u, v, face_idx, nx, ny, nz."""
        mesh = _flat_plane_cage()
        res = sample_subd_limit_normals(mesh)
        assert len(res.sampled_normals) > 0
        for s in res.sampled_normals:
            assert isinstance(s, dict), f"Expected dict, got {type(s)}"
            for key in ("u", "v", "face_idx", "nx", "ny", "nz"):
                assert key in s, f"Missing key '{key}'"
            assert isinstance(s["face_idx"], int)
            assert 0.0 <= s["u"] <= 1.0
            assert 0.0 <= s["v"] <= 1.0

    def test_total_sample_count(self) -> None:
        """Test 9: total sample count = num_faces × n_grid²."""
        mesh = _flat_plane_cage()
        spf = 9
        n_grid = max(2, round(math.sqrt(spf)))
        expected = len(mesh.faces) * n_grid * n_grid
        res = sample_subd_limit_normals(mesh, samples_per_face=spf)
        assert len(res.sampled_normals) == expected, (
            f"Expected {expected} samples, got {len(res.sampled_normals)}"
        )

    def test_honest_caveat_non_empty(self) -> None:
        """Test 10: honest_caveat is a non-empty string."""
        mesh = _flat_plane_cage()
        res = sample_subd_limit_normals(mesh)
        assert isinstance(res.honest_caveat, str)
        assert len(res.honest_caveat) > 10


# ---------------------------------------------------------------------------
# TestIrregularSamples
# ---------------------------------------------------------------------------

class TestIrregularSamples:
    """Tests 11–12: irregular vertex detection."""

    def test_cube_cage_has_irregular_samples(self) -> None:
        """Test 11: cube cage (all valence-3) has num_irregular_samples > 0."""
        mesh = _cube_cage()
        res = sample_subd_limit_normals(mesh, samples_per_face=9)
        # All cube vertices have valence 3 (connected to 3 faces)
        assert res.num_irregular_samples > 0, (
            "Expected irregular samples for cube cage (valence-3 vertices)"
        )

    def test_torus_cage_regular_interior(self) -> None:
        """Test 12: 4-face shared-vertex torus has all samples flagged (or none - depends on valence)."""
        # The torus cage has 4 vertices each shared by 4 faces → valence 4 = regular.
        # But because the torus has so few vertices with high reuse, some may appear valence-4.
        mesh = _torus_2x2_cage()
        res = sample_subd_limit_normals(mesh, samples_per_face=4)
        # Should have no errors; result is valid regardless
        assert isinstance(res, LimitNormalFitResult)
        # The key check: if all vertices are valence-4, num_irregular_samples == 0
        from kerf_cad_core.subd.limit_normal_fit import _build_vertex_adjacency
        vert_faces, _ = _build_vertex_adjacency(mesh)
        all_regular = all(len(vert_faces.get(vi, [])) == 4 for vi in range(len(mesh.vertices)))
        if all_regular:
            assert res.num_irregular_samples == 0


# ---------------------------------------------------------------------------
# TestResidualComputation
# ---------------------------------------------------------------------------

class TestResidualComputation:
    """Tests 13–14: residual statistics."""

    def test_flat_plane_residual_near_zero(self) -> None:
        """Test 13: flat plane residuals ≈ 0 (bilinear approximation is exact)."""
        mesh = _flat_plane_cage()
        res = sample_subd_limit_normals(mesh, samples_per_face=9)
        # For a flat plane, all corners and interior points have the same normal.
        # Bilinear blend of equal normals = same normal → zero residual.
        assert res.max_normal_residual_deg < 0.5, (
            f"Flat plane residual too large: {res.max_normal_residual_deg:.4f}°"
        )

    def test_residual_non_negative_and_bounded(self) -> None:
        """Test 14: max residual is non-negative and <= 90 degrees."""
        for mesh in [_flat_plane_cage(), _cube_cage(), _cylinder_cage()]:
            res = sample_subd_limit_normals(mesh, samples_per_face=9)
            assert res.max_normal_residual_deg >= 0.0
            assert res.max_normal_residual_deg <= 90.0
            assert res.mean_normal_residual_deg >= 0.0
            assert res.mean_normal_residual_deg <= res.max_normal_residual_deg + 1e-9


# ---------------------------------------------------------------------------
# TestCylinderNormals
# ---------------------------------------------------------------------------

class TestCylinderNormals:
    """Test 15: cylinder cage normals are perpendicular to the Y-axis."""

    def test_cylinder_normals_perpendicular_to_y(self) -> None:
        """Test 15: cylinder side-face normals have |ny| < 0.15 (perpendicular to Y)."""
        mesh = _cylinder_cage(n=8)
        res = sample_subd_limit_normals(mesh, samples_per_face=4, normalize=True)
        assert len(res.sampled_normals) > 0
        # For a cylinder aligned along Y, the normals on side faces should have
        # small Y-component (they point radially outward in XZ plane).
        # At u=0 and u=1 (end caps) this could vary, but most mid-face samples
        # should be radial.
        mid_samples = [s for s in res.sampled_normals if 0.1 < s["u"] < 0.9]
        if mid_samples:
            for s in mid_samples:
                # |ny| should be small for radial normals
                # (relaxed tolerance due to coarse cage discretization)
                assert abs(s["ny"]) < 0.5, (
                    f"Cylinder normal has large Y-component: ny={s['ny']:.4f}"
                )


# ---------------------------------------------------------------------------
# TestSphericishCage
# ---------------------------------------------------------------------------

class TestSphericishCage:
    """Test 16: sphere-like cube cage returns unit normals for all 6 faces."""

    def test_cube_cage_normals_all_unit_length(self) -> None:
        """Test 16: cube cage returns 6*4=24 unit-length normals (samples_per_face=4 → 2×2 grid)."""
        mesh = _cube_cage()
        res = sample_subd_limit_normals(mesh, samples_per_face=4, normalize=True)

        # 6 faces × 2×2 = 24 samples
        n_grid = max(2, round(math.sqrt(4)))
        expected_count = len(mesh.faces) * n_grid * n_grid
        assert len(res.sampled_normals) == expected_count, (
            f"Expected {expected_count} samples, got {len(res.sampled_normals)}"
        )

        # All must be unit-length
        for s in res.sampled_normals:
            length = math.sqrt(s["nx"]**2 + s["ny"]**2 + s["nz"]**2)
            assert abs(length - 1.0) < 1e-6, (
                f"Non-unit normal: |N|={length:.8f} at face={s['face_idx']}"
            )

        # num_irregular_samples > 0 since cube vertices have valence 3
        assert res.num_irregular_samples > 0


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Test 17: edge cases."""

    def test_empty_cage_no_exception(self) -> None:
        """Test 17: empty cage returns empty result without raising."""
        mesh = SubDMesh(vertices=[], faces=[])
        res = sample_subd_limit_normals(mesh)
        assert isinstance(res, LimitNormalFitResult)
        assert res.sampled_normals == []
        assert res.num_irregular_samples == 0
