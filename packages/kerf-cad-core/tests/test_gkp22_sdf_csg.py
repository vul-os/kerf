"""Tests for GK-P22: SDF CSG + marching-cubes extraction."""
from __future__ import annotations
import math
import pytest
from kerf_cad_core.geom.sdf_csg import (
    SdfField,
    sdf_sphere,
    sdf_box,
    sdf_cylinder,
    sdf_union,
    sdf_subtract,
    sdf_intersect,
    marching_cubes,
)


# ---------------------------------------------------------------------------
# Primitive SDF correctness
# ---------------------------------------------------------------------------

class TestSdfPrimitives:
    def test_sphere_at_center_is_minus_r(self):
        s = sdf_sphere(0, 0, 0, 1.0)
        assert abs(s(0, 0, 0) - (-1.0)) < 1e-10

    def test_sphere_at_surface_is_zero(self):
        s = sdf_sphere(0, 0, 0, 1.0)
        assert abs(s(1, 0, 0)) < 1e-10
        assert abs(s(0, 1, 0)) < 1e-10
        assert abs(s(0, 0, 1)) < 1e-10

    def test_sphere_outside_positive(self):
        s = sdf_sphere(0, 0, 0, 1.0)
        assert s(2, 0, 0) > 0.0

    def test_sphere_offset_center(self):
        s = sdf_sphere(1, 2, 3, 0.5)
        # At center → -r
        assert abs(s(1, 2, 3) - (-0.5)) < 1e-10
        # On surface along x
        assert abs(s(1.5, 2, 3)) < 1e-10

    def test_box_at_center_is_negative(self):
        b = sdf_box(0, 0, 0, 1.0, 1.0, 1.0)
        # Center of box — all dims inside, max negative component = -1.0
        val = b(0, 0, 0)
        assert val < 0.0

    def test_box_on_face_is_zero(self):
        b = sdf_box(0, 0, 0, 1.0, 1.0, 1.0)
        assert abs(b(1.0, 0, 0)) < 1e-10

    def test_box_outside_positive(self):
        b = sdf_box(0, 0, 0, 1.0, 1.0, 1.0)
        assert b(2.0, 0, 0) > 0.0

    def test_cylinder_at_center_is_negative(self):
        c = sdf_cylinder(0, 0, 0, 1.0, 2.0)
        val = c(0, 0, 0)
        assert val < 0.0

    def test_cylinder_on_curved_surface_is_zero(self):
        c = sdf_cylinder(0, 0, 0, 1.0, 4.0)
        # On curved side at mid-height
        assert abs(c(1.0, 0, 0)) < 1e-10

    def test_cylinder_outside_positive(self):
        c = sdf_cylinder(0, 0, 0, 1.0, 2.0)
        assert c(2.0, 0, 0) > 0.0


# ---------------------------------------------------------------------------
# CSG operations (exact, k=0)
# ---------------------------------------------------------------------------

class TestSdfCSGExact:
    def test_union_inside_either(self):
        a = sdf_sphere(0, 0, 0, 1.0)
        b = sdf_sphere(1.5, 0, 0, 1.0)
        u = sdf_union(a, b)
        # Center of first sphere → inside union
        assert u(0, 0, 0) < 0.0
        # Center of second sphere → inside union
        assert u(1.5, 0, 0) < 0.0

    def test_union_outside_both_positive(self):
        a = sdf_sphere(0, 0, 0, 0.5)
        b = sdf_sphere(5, 0, 0, 0.5)
        u = sdf_union(a, b)
        # Midpoint at (2.5, 0, 0) — outside both
        assert u(2.5, 0, 0) > 0.0

    def test_subtract_removes_volume(self):
        a = sdf_sphere(0, 0, 0, 2.0)
        b = sdf_sphere(0, 0, 0, 1.0)
        diff = sdf_subtract(a, b)
        # At center (inside b), diff should be outside (positive after subtraction)
        assert diff(0, 0, 0) > 0.0
        # Outside a → still outside
        assert diff(3, 0, 0) > 0.0

    def test_subtract_outside_b_stays_inside_a(self):
        a = sdf_sphere(0, 0, 0, 2.0)
        b = sdf_sphere(5, 0, 0, 1.0)  # far away
        diff = sdf_subtract(a, b)
        # Near a center but far from b → still inside a
        assert diff(0, 0, 0) < 0.0

    def test_intersect_inside_both(self):
        a = sdf_sphere(0, 0, 0, 2.0)
        b = sdf_sphere(0, 0, 0, 1.5)
        inter = sdf_intersect(a, b)
        # Inside both → inside intersection
        assert inter(0, 0, 0) < 0.0

    def test_intersect_outside_either(self):
        a = sdf_sphere(0, 0, 0, 1.0)
        b = sdf_sphere(3, 0, 0, 1.0)
        inter = sdf_intersect(a, b)
        # Near first sphere: outside second → outside intersection
        assert inter(0, 0, 0) > 0.0


# ---------------------------------------------------------------------------
# CSG operator sugar
# ---------------------------------------------------------------------------

class TestSdfOperators:
    def test_pipe_operator_is_union(self):
        a = sdf_sphere(0, 0, 0, 1.0)
        b = sdf_sphere(1.5, 0, 0, 1.0)
        u = a | b
        assert u(0, 0, 0) < 0.0

    def test_and_operator_is_intersect(self):
        a = sdf_sphere(0, 0, 0, 2.0)
        b = sdf_sphere(0, 0, 0, 1.5)
        inter = a & b
        assert inter(0, 0, 0) < 0.0

    def test_sub_operator_is_subtract(self):
        a = sdf_sphere(0, 0, 0, 2.0)
        b = sdf_sphere(0, 0, 0, 1.0)
        diff = a - b
        assert diff(0, 0, 0) > 0.0

    def test_neg_flips_sign(self):
        a = sdf_sphere(0, 0, 0, 1.0)
        neg_a = -a
        # Was negative at center, now positive
        assert neg_a(0, 0, 0) > 0.0
        # Was positive outside, now negative
        assert neg_a(2, 0, 0) < 0.0


# ---------------------------------------------------------------------------
# Smooth blend (k > 0)
# ---------------------------------------------------------------------------

class TestSdfSmoothBlend:
    def test_smooth_union_between_exact_and_smooth(self):
        # Two unit spheres at distance 2 (just touching)
        a = sdf_sphere(-1, 0, 0, 1.0)
        b = sdf_sphere(1, 0, 0, 1.0)
        exact = sdf_union(a, b, k=0.0)
        smooth = sdf_union(a, b, k=0.3)
        # At the touching point (0,0,0) both should be <= 0;
        # smooth blend should be <= exact union at that point (smoother = more inside)
        v_exact = exact(0, 0, 0)
        v_smooth = smooth(0, 0, 0)
        assert v_smooth <= v_exact + 1e-10  # smooth union is at least as inside

    def test_smooth_union_k0_equals_min(self):
        a = sdf_sphere(0, 0, 0, 1.0)
        b = sdf_sphere(3, 0, 0, 1.0)
        exact = sdf_union(a, b, k=0.0)
        # At origin: min(a, b) = a = -1.0
        assert abs(exact(0, 0, 0) - (-1.0)) < 1e-10

    def test_smooth_subtract_blend_positive_at_center(self):
        a = sdf_sphere(0, 0, 0, 2.0)
        b = sdf_sphere(0, 0, 0, 1.0)
        diff_exact = sdf_subtract(a, b, k=0.0)
        diff_smooth = sdf_subtract(a, b, k=0.3)
        # Both should be positive at center (inside the subtracted hole)
        assert diff_exact(0, 0, 0) > 0.0
        assert diff_smooth(0, 0, 0) > 0.0


# ---------------------------------------------------------------------------
# Marching cubes
# ---------------------------------------------------------------------------

class TestMarchingCubes:
    def test_sphere_mesh_nonempty(self):
        s = sdf_sphere(0, 0, 0, 0.5)
        bounds = (-1, -1, -1, 1, 1, 1)
        mesh = marching_cubes(s, bounds, resolution=16)
        assert isinstance(mesh, dict)
        assert "vertices" in mesh
        assert "faces" in mesh
        assert len(mesh["vertices"]) > 0
        assert len(mesh["faces"]) > 0

    def test_sphere_mesh_all_finite(self):
        s = sdf_sphere(0, 0, 0, 0.5)
        bounds = (-1, -1, -1, 1, 1, 1)
        mesh = marching_cubes(s, bounds, resolution=16)
        import math as _math
        for v in mesh["vertices"]:
            assert len(v) == 3
            for coord in v:
                assert _math.isfinite(coord), f"Non-finite vertex coordinate: {coord}"

    def test_sphere_mesh_triangles_only(self):
        s = sdf_sphere(0, 0, 0, 0.5)
        bounds = (-1, -1, -1, 1, 1, 1)
        mesh = marching_cubes(s, bounds, resolution=16)
        for f in mesh["faces"]:
            assert len(f) == 3, f"Expected triangle, got {len(f)}-gon"

    def test_sphere_mesh_valid_face_indices(self):
        s = sdf_sphere(0, 0, 0, 0.5)
        bounds = (-1, -1, -1, 1, 1, 1)
        mesh = marching_cubes(s, bounds, resolution=16)
        n_verts = len(mesh["vertices"])
        for f in mesh["faces"]:
            for idx in f:
                assert 0 <= idx < n_verts, f"Face index {idx} out of range [0, {n_verts})"

    def test_sphere_mesh_vertices_near_surface(self):
        """All mesh vertices should be approximately on the SDF zero-crossing."""
        r = 0.5
        s = sdf_sphere(0, 0, 0, r)
        bounds = (-1, -1, -1, 1, 1, 1)
        mesh = marching_cubes(s, bounds, resolution=20)
        for v in mesh["vertices"]:
            dist = math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)
            # Within 15% of radius given 20-sample grid
            assert abs(dist - r) < 0.15, f"Vertex at distance {dist} from center, expected ~{r}"

    def test_box_mesh_nonempty(self):
        b = sdf_box(0, 0, 0, 0.4, 0.4, 0.4)
        bounds = (-1, -1, -1, 1, 1, 1)
        mesh = marching_cubes(b, bounds, resolution=16)
        assert len(mesh["vertices"]) > 0
        assert len(mesh["faces"]) > 0

    def test_empty_field_returns_empty_mesh(self):
        """SDF that is positive everywhere → no surface → empty mesh."""
        # Sphere far outside the bounds
        s = sdf_sphere(100, 100, 100, 0.1)
        bounds = (-1, -1, -1, 1, 1, 1)
        mesh = marching_cubes(s, bounds, resolution=8)
        assert len(mesh["faces"]) == 0

    def test_higher_resolution_more_faces(self):
        s = sdf_sphere(0, 0, 0, 0.5)
        bounds = (-1, -1, -1, 1, 1, 1)
        mesh_lo = marching_cubes(s, bounds, resolution=10)
        mesh_hi = marching_cubes(s, bounds, resolution=20)
        assert len(mesh_hi["faces"]) > len(mesh_lo["faces"])
