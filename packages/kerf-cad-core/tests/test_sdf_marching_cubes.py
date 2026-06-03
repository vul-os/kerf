"""Tests for kerf_cad_core.sdf.marching_cubes — polygonize_sdf.

≥ 20 tests covering:
- Return type and shape correctness
- Vertex count / triangle count ≥ 100 for unit sphere at resolution=32
- Volume of extracted sphere mesh within 3% of 4π/3
- Normals are unit length (within 1e-6)
- Empty SDF (no zero-crossings) → empty mesh
- CSG dedup: smooth union of identical spheres ≡ single sphere volume within 1%
- sdf_translate / sdf_scale / sdf_rotate produce plausible meshes
- polygonize_sdf_chernyaev raises NotImplementedError
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.sdf.csg import (
    sdf_sphere,
    sdf_box,
    sdf_subtraction,
    sdf_smooth_union,
    sdf_translate,
    sdf_scale,
    sdf_rotate,
)
from kerf_cad_core.sdf.marching_cubes import (
    MarchingCubesResult,
    polygonize_sdf,
    polygonize_sdf_chernyaev,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mesh_volume(verts: np.ndarray, tris: np.ndarray) -> float:
    """Signed volume of a closed triangle mesh via the divergence theorem.

    V = (1/6) |Σ v0·(v1 × v2)|

    Reference: any standard computational geometry text.
    """
    v0 = verts[tris[:, 0]]
    v1 = verts[tris[:, 1]]
    v2 = verts[tris[:, 2]]
    signed_vols = np.einsum("ij,ij->i", v0, np.cross(v1, v2))
    return abs(float(signed_vols.sum()) / 6.0)


def _sphere_volume_expected(r: float) -> float:
    return (4.0 / 3.0) * math.pi * r ** 3


# ===========================================================================
# 1. Return type and structure
# ===========================================================================

class TestReturnType:
    @pytest.fixture(scope="class")
    def sphere_mesh(self) -> MarchingCubesResult:
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        return polygonize_sdf(s, (-1.5, -1.5, -1.5), (1.5, 1.5, 1.5), resolution=32)

    def test_is_marching_cubes_result(self, sphere_mesh):
        assert isinstance(sphere_mesh, MarchingCubesResult)

    def test_vertices_shape(self, sphere_mesh):
        assert sphere_mesh.vertices.ndim == 2
        assert sphere_mesh.vertices.shape[1] == 3

    def test_triangles_shape(self, sphere_mesh):
        assert sphere_mesh.triangles.ndim == 2
        assert sphere_mesh.triangles.shape[1] == 3

    def test_vertices_dtype(self, sphere_mesh):
        assert sphere_mesh.vertices.dtype == np.float64

    def test_triangles_dtype(self, sphere_mesh):
        assert sphere_mesh.triangles.dtype == np.int32

    def test_normals_shape(self, sphere_mesh):
        assert sphere_mesh.normals is not None
        assert sphere_mesh.normals.shape == sphere_mesh.vertices.shape

    def test_face_indices_in_range(self, sphere_mesh):
        V = len(sphere_mesh.vertices)
        assert int(sphere_mesh.triangles.min()) >= 0
        assert int(sphere_mesh.triangles.max()) < V


# ===========================================================================
# 2. Size checks for unit sphere at resolution=32
# ===========================================================================

class TestSphereSize:
    @pytest.fixture(scope="class")
    def mesh(self) -> MarchingCubesResult:
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        return polygonize_sdf(s, (-1.5, -1.5, -1.5), (1.5, 1.5, 1.5), resolution=32)

    def test_vertex_count_exceeds_100(self, mesh):
        assert len(mesh.vertices) > 100

    def test_triangle_count_exceeds_100(self, mesh):
        assert len(mesh.triangles) > 100


# ===========================================================================
# 3. Volume accuracy — unit sphere within 3% of 4π/3
# ===========================================================================

class TestSphereVolume:
    def test_sphere_volume_within_3pct(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        mesh = polygonize_sdf(s, (-1.5, -1.5, -1.5), (1.5, 1.5, 1.5), resolution=40)
        assert len(mesh.vertices) > 0, "mesh is empty"
        vol = _mesh_volume(mesh.vertices, mesh.triangles)
        expected = _sphere_volume_expected(1.0)
        rel_err = abs(vol - expected) / expected
        assert rel_err < 0.03, (
            f"Sphere volume: got {vol:.4f}, expected {expected:.4f}, "
            f"relative error {rel_err:.4%} > 3%"
        )


# ===========================================================================
# 4. Normals are unit length
# ===========================================================================

class TestNormals:
    def test_normals_unit_length(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        mesh = polygonize_sdf(s, (-1.5, -1.5, -1.5), (1.5, 1.5, 1.5), resolution=20)
        assert mesh.normals is not None
        norms = np.linalg.norm(mesh.normals, axis=1)
        assert np.all(np.abs(norms - 1.0) < 1e-6), (
            f"Max deviation from unit length: {np.max(np.abs(norms-1.0))}"
        )

    def test_normals_none_when_disabled(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        mesh = polygonize_sdf(
            s, (-1.5, -1.5, -1.5), (1.5, 1.5, 1.5), resolution=16,
            compute_normals=False,
        )
        assert mesh.normals is None


# ===========================================================================
# 5. Empty SDF → empty mesh
# ===========================================================================

class TestEmptyMesh:
    def test_no_zero_crossing_returns_empty(self):
        # Sphere far outside the bounds
        s = sdf_sphere((100.0, 0.0, 0.0), 0.1)
        mesh = polygonize_sdf(s, (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0), resolution=8)
        assert len(mesh.vertices) == 0
        assert len(mesh.triangles) == 0

    def test_empty_mesh_triangles_shape(self):
        s = sdf_sphere((100.0, 0.0, 0.0), 0.1)
        mesh = polygonize_sdf(s, (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0), resolution=8)
        assert mesh.triangles.shape == (0, 3)
        assert mesh.vertices.shape == (0, 3)


# ===========================================================================
# 6. CSG dedup: union of identical spheres ≡ single sphere volume (within 1%)
# ===========================================================================

class TestCSGDedup:
    def test_union_identical_spheres_same_volume(self):
        a = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        b = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        su = sdf_smooth_union(a, b, k=0.01)

        single = sdf_sphere((0.0, 0.0, 0.0), 1.0)

        mesh_union = polygonize_sdf(su, (-1.5, -1.5, -1.5), (1.5, 1.5, 1.5), resolution=32)
        mesh_single = polygonize_sdf(single, (-1.5, -1.5, -1.5), (1.5, 1.5, 1.5), resolution=32)

        vol_union = _mesh_volume(mesh_union.vertices, mesh_union.triangles)
        vol_single = _mesh_volume(mesh_single.vertices, mesh_single.triangles)

        rel_diff = abs(vol_union - vol_single) / vol_single
        assert rel_diff < 0.01, (
            f"Union volume {vol_union:.4f} vs single {vol_single:.4f}, "
            f"relative diff {rel_diff:.4%} > 1%"
        )


# ===========================================================================
# 7. sdf_subtraction produces valid mesh
# ===========================================================================

class TestSubtractionMesh:
    def test_subtraction_sphere_minus_box_mesh_nonempty(self):
        outer = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        inner = sdf_box((0.0, 0.0, 0.5), (0.5, 0.5, 0.5))
        diff = sdf_subtraction(outer, inner)
        mesh = polygonize_sdf(diff, (-1.5, -1.5, -1.5), (1.5, 1.5, 1.5), resolution=24)
        assert len(mesh.vertices) > 0
        assert len(mesh.triangles) > 0

    def test_subtraction_region_sign(self):
        """Points in sphere exterior should have negative SDF after sub."""
        outer = sdf_sphere((0.0, 0.0, 0.0), 2.0)
        inner = sdf_sphere((0.0, 0.0, 0.0), 0.5)
        diff = sdf_subtraction(outer, inner)
        # Point between the two spheres (1.0, 0, 0): inside outer, outside inner
        pts = np.array([[1.0, 0.0, 0.0]], dtype=np.float64)
        assert float(diff(pts)[0]) < 0.0


# ===========================================================================
# 8. Transform: sdf_translate / sdf_scale / sdf_rotate → plausible mesh
# ===========================================================================

class TestTransformMesh:
    def test_translated_sphere_mesh_nonempty(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 0.5)
        st = sdf_translate(s, (0.3, 0.3, 0.3))
        mesh = polygonize_sdf(st, (-0.5, -0.5, -0.5), (1.5, 1.5, 1.5), resolution=20)
        assert len(mesh.vertices) > 0

    def test_scaled_sphere_volume(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        ss = sdf_scale(s, 2.0)  # radius becomes 2.0
        mesh = polygonize_sdf(ss, (-3.0, -3.0, -3.0), (3.0, 3.0, 3.0), resolution=32)
        vol = _mesh_volume(mesh.vertices, mesh.triangles)
        expected = _sphere_volume_expected(2.0)
        rel_err = abs(vol - expected) / expected
        assert rel_err < 0.05, (
            f"Scaled sphere volume: got {vol:.4f}, expected {expected:.4f}, "
            f"relative error {rel_err:.4%}"
        )

    def test_rotated_sphere_symmetric(self):
        """Rotating a sphere (centred at origin) should give same mesh volume."""
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        sr = sdf_rotate(s, (0.0, 0.0, 1.0), math.pi / 4)
        mesh = polygonize_sdf(sr, (-1.5, -1.5, -1.5), (1.5, 1.5, 1.5), resolution=24)
        vol = _mesh_volume(mesh.vertices, mesh.triangles)
        expected = _sphere_volume_expected(1.0)
        rel_err = abs(vol - expected) / expected
        assert rel_err < 0.05


# ===========================================================================
# 9. polygonize_sdf_chernyaev raises NotImplementedError
# ===========================================================================

class TestChernyaev:
    def test_chernyaev_raises_not_implemented(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        with pytest.raises(NotImplementedError):
            polygonize_sdf_chernyaev(s, (-1.5, -1.5, -1.5), (1.5, 1.5, 1.5))


# ===========================================================================
# 10. Error handling
# ===========================================================================

class TestErrors:
    def test_resolution_less_than_2_raises(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        with pytest.raises(ValueError, match="resolution"):
            polygonize_sdf(s, (-1, -1, -1), (1, 1, 1), resolution=1)

    def test_invalid_bounds_raises(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        with pytest.raises(ValueError):
            polygonize_sdf(s, (1, 1, 1), (1, 1, 1))
