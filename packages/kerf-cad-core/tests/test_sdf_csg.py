"""Tests for kerf_cad_core.sdf.csg — SDF primitives, CSG ops, smooth blends.

≥ 20 tests covering:
- sdf_sphere correctness (center, surface, outside)
- sdf_box inside/outside/boundary
- sdf_cylinder_z correctness
- sdf_plane correctness
- sdf_union / sdf_intersection / sdf_subtraction
- sdf_smooth_union (Quilez smooth-min bridge)
- sdf_smooth_intersection / sdf_smooth_subtraction
- sdf_translate / sdf_scale / sdf_rotate (Lipschitz property)
- Batched (N,3) input
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.sdf.csg import (
    SDF,
    sdf_sphere,
    sdf_box,
    sdf_cylinder_z,
    sdf_plane,
    sdf_union,
    sdf_intersection,
    sdf_subtraction,
    sdf_smooth_union,
    sdf_smooth_intersection,
    sdf_smooth_subtraction,
    sdf_translate,
    sdf_scale,
    sdf_rotate,
)


# ---------------------------------------------------------------------------
# Helper: evaluate an SDF at a single point given as a tuple/list
# ---------------------------------------------------------------------------

def _eval(sdf: SDF, x: float, y: float, z: float) -> float:
    """Evaluate *sdf* at (x, y, z) and return a Python float."""
    return float(sdf(np.array([[x, y, z]], dtype=np.float64))[0])


# ===========================================================================
# sdf_sphere
# ===========================================================================

class TestSdfSphere:
    def test_sphere_at_center_is_minus_radius(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        assert abs(_eval(s, 0, 0, 0) - (-1.0)) < 1e-12

    def test_sphere_at_radius_distance_is_zero(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        assert abs(_eval(s, 1, 0, 0)) < 1e-12
        assert abs(_eval(s, 0, 1, 0)) < 1e-12
        assert abs(_eval(s, 0, 0, 1)) < 1e-12

    def test_sphere_outside_is_positive(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        assert _eval(s, 2, 0, 0) > 0.0
        assert abs(_eval(s, 2, 0, 0) - 1.0) < 1e-12

    def test_sphere_gradient_at_surface_x(self):
        """Central-difference gradient at (1,0,0) should be ≈ (1,0,0)."""
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        h = 1e-5
        gx = (_eval(s, 1 + h, 0, 0) - _eval(s, 1 - h, 0, 0)) / (2 * h)
        gy = (_eval(s, 1, h, 0) - _eval(s, 1, -h, 0)) / (2 * h)
        gz = (_eval(s, 1, 0, h) - _eval(s, 1, 0, -h)) / (2 * h)
        assert abs(gx - 1.0) < 1e-4
        assert abs(gy) < 1e-4
        assert abs(gz) < 1e-4

    def test_sphere_offset_center(self):
        s = sdf_sphere((1.0, 2.0, 3.0), 0.5)
        assert abs(_eval(s, 1, 2, 3) - (-0.5)) < 1e-12
        assert abs(_eval(s, 1.5, 2, 3)) < 1e-12

    def test_sphere_batched_input(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        pts = np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=np.float64)
        result = s(pts)
        assert result.shape == (3,)
        assert abs(result[0] - (-1.0)) < 1e-12
        assert abs(result[1]) < 1e-12
        assert abs(result[2] - 1.0) < 1e-12


# ===========================================================================
# sdf_box
# ===========================================================================

class TestSdfBox:
    def test_box_center_is_negative(self):
        b = sdf_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        assert _eval(b, 0, 0, 0) < 0.0

    def test_box_center_value(self):
        """For a unit half-extents box, center is at distance -1 (nearest face)."""
        b = sdf_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        # Exact interior SDF = min negative component = -1.0
        val = _eval(b, 0, 0, 0)
        assert abs(val - (-1.0)) < 1e-12

    def test_box_face_is_zero(self):
        b = sdf_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        assert abs(_eval(b, 1.0, 0, 0)) < 1e-12
        assert abs(_eval(b, 0, 1.0, 0)) < 1e-12
        assert abs(_eval(b, 0, 0, 1.0)) < 1e-12

    def test_box_outside_positive(self):
        b = sdf_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        assert _eval(b, 2.0, 0, 0) > 0.0
        assert abs(_eval(b, 2.0, 0, 0) - 1.0) < 1e-12

    def test_box_corner_distance(self):
        """Corner of unit half-extent box at (1,1,1) — point is on corner."""
        b = sdf_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        # On corner: SDF should be 0
        assert abs(_eval(b, 1.0, 1.0, 1.0)) < 1e-12

    def test_box_outside_corner_distance(self):
        """Point at (2,2,2) for unit box: distance = sqrt((1)²+(1)²+(1)²) = sqrt(3)."""
        b = sdf_box((0.0, 0.0, 0.0), (1.0, 1.0, 1.0))
        expected = math.sqrt(3.0)
        assert abs(_eval(b, 2.0, 2.0, 2.0) - expected) < 1e-12


# ===========================================================================
# sdf_cylinder_z
# ===========================================================================

class TestSdfCylinderZ:
    def test_cylinder_center_negative(self):
        c = sdf_cylinder_z((0.0, 0.0, 0.0), 1.0, 2.0)
        assert _eval(c, 0, 0, 0) < 0.0

    def test_cylinder_curved_surface_zero(self):
        """Mid-height point on the curved wall should be at SDF ≈ 0."""
        c = sdf_cylinder_z((0.0, 0.0, 0.0), 1.0, 4.0)
        assert abs(_eval(c, 1.0, 0, 0)) < 1e-12

    def test_cylinder_outside_positive(self):
        c = sdf_cylinder_z((0.0, 0.0, 0.0), 1.0, 2.0)
        assert _eval(c, 2.0, 0, 0) > 0.0


# ===========================================================================
# sdf_plane
# ===========================================================================

class TestSdfPlane:
    def test_plane_positive_on_normal_side(self):
        p = sdf_plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        assert _eval(p, 0, 0, 1) > 0.0
        assert abs(_eval(p, 0, 0, 1) - 1.0) < 1e-12

    def test_plane_negative_below(self):
        p = sdf_plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        assert _eval(p, 0, 0, -1) < 0.0

    def test_plane_zero_on_plane(self):
        p = sdf_plane((0.0, 0.0, 0.0), (0.0, 0.0, 1.0))
        assert abs(_eval(p, 1.0, 2.0, 0.0)) < 1e-12


# ===========================================================================
# Sharp CSG operations
# ===========================================================================

class TestSharpCSG:
    def test_union_inside_first(self):
        a = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        b = sdf_sphere((3.0, 0.0, 0.0), 1.0)
        u = sdf_union(a, b)
        assert _eval(u, 0, 0, 0) < 0.0

    def test_union_inside_second(self):
        a = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        b = sdf_sphere((3.0, 0.0, 0.0), 1.0)
        u = sdf_union(a, b)
        assert _eval(u, 3, 0, 0) < 0.0

    def test_union_outside_both(self):
        a = sdf_sphere((0.0, 0.0, 0.0), 0.5)
        b = sdf_sphere((5.0, 0.0, 0.0), 0.5)
        u = sdf_union(a, b)
        assert _eval(u, 2.5, 0, 0) > 0.0

    def test_subtraction_removes_volume(self):
        """Subtracting a small sphere from a large one leaves interior positive near origin."""
        a = sdf_sphere((0.0, 0.0, 0.0), 2.0)
        b = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        diff = sdf_subtraction(a, b)
        # At origin (inside b), subtraction flips sign → positive
        assert _eval(diff, 0, 0, 0) > 0.0

    def test_subtraction_outside_b_stays_inside_a(self):
        a = sdf_sphere((0.0, 0.0, 0.0), 2.0)
        b = sdf_sphere((10.0, 0.0, 0.0), 0.5)  # far away
        diff = sdf_subtraction(a, b)
        assert _eval(diff, 0, 0, 0) < 0.0

    def test_intersection_inside_both(self):
        a = sdf_sphere((0.0, 0.0, 0.0), 2.0)
        b = sdf_sphere((0.0, 0.0, 0.0), 1.5)
        inter = sdf_intersection(a, b)
        assert _eval(inter, 0, 0, 0) < 0.0

    def test_intersection_outside_one(self):
        a = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        b = sdf_sphere((3.0, 0.0, 0.0), 1.0)
        inter = sdf_intersection(a, b)
        # Near first sphere but outside second → outside intersection
        assert _eval(inter, 0, 0, 0) > 0.0


# ===========================================================================
# Smooth CSG operations
# ===========================================================================

class TestSmoothCSG:
    def test_smooth_union_creates_bridge(self):
        """Two spheres 1.5R apart; smooth union should have negative value between them."""
        a = sdf_sphere((-0.75, 0.0, 0.0), 1.0)
        b = sdf_sphere((0.75, 0.0, 0.0), 1.0)
        su = sdf_smooth_union(a, b, k=0.5)
        # Midpoint between spheres should be inside the smooth union
        v = _eval(su, 0, 0, 0)
        sharp = min(_eval(a, 0, 0, 0), _eval(b, 0, 0, 0))
        # Smooth union pulls the value down (more inside)
        assert v <= sharp + 1e-10

    def test_smooth_union_k0_approaches_sharp(self):
        """For very small k, smooth union ≈ sharp union."""
        a = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        b = sdf_sphere((3.0, 0.0, 0.0), 1.0)
        su = sdf_smooth_union(a, b, k=1e-9)
        u = sdf_union(a, b)
        pts = np.array([[0, 0, 0], [3, 0, 0], [1.5, 0, 0]], dtype=np.float64)
        np.testing.assert_allclose(su(pts), u(pts), atol=1e-6)

    def test_smooth_subtraction_positive_at_center(self):
        a = sdf_sphere((0.0, 0.0, 0.0), 2.0)
        b = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        ss = sdf_smooth_subtraction(a, b, k=0.3)
        assert _eval(ss, 0, 0, 0) > 0.0

    def test_smooth_intersection_inside_both(self):
        a = sdf_sphere((0.0, 0.0, 0.0), 2.0)
        b = sdf_sphere((0.0, 0.0, 0.0), 1.5)
        si = sdf_smooth_intersection(a, b, k=0.1)
        assert _eval(si, 0, 0, 0) < 0.0

    def test_smooth_union_csg_dedup(self):
        """Union of identical spheres ≡ single sphere (within blend tolerance).

        For smin(a, a, k), the maximum deviation is k/4 (at h=0.5).
        With k=0.01, max_dev = 0.0025.  We use atol = k/4 + eps.
        """
        a = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        b = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        k = 0.01
        su = sdf_smooth_union(a, b, k=k)
        # At any point, smooth union of identical SDFs deviates by at most k/4
        pts = np.random.default_rng(42).uniform(-2, 2, (50, 3))
        vals_su = su(pts)
        vals_a = a(pts)
        # smooth union can only pull values down (≤ a), by at most k/4
        diff = vals_a - vals_su
        assert np.all(diff >= -1e-12), "smooth union must not exceed sharp min"
        assert np.all(diff <= k / 4.0 + 1e-12), f"max deviation {np.max(diff):.6f} > k/4 = {k/4:.6f}"


# ===========================================================================
# Transforms
# ===========================================================================

class TestTransforms:
    def test_translate_moves_sphere(self):
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        st = sdf_translate(s, (2.0, 0.0, 0.0))
        # New center at (2, 0, 0)
        assert abs(_eval(st, 2, 0, 0) - (-1.0)) < 1e-12
        # Old center (0,0,0) is now 2 units from new center → outside
        assert abs(_eval(st, 0, 0, 0) - 1.0) < 1e-12

    def test_scale_preserves_lipschitz(self):
        """sdf_scale(f, s): gradient at zero-set should remain ≤ 1+ε."""
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        ss = sdf_scale(s, 2.0)
        # Center of scaled sphere at (0,0,0) → value = -2 (radius doubled)
        assert abs(_eval(ss, 0, 0, 0) - (-2.0)) < 1e-12
        # Surface at distance 2 along x
        assert abs(_eval(ss, 2, 0, 0)) < 1e-12

    def test_scale_gradient_lipschitz(self):
        """Gradient magnitude near the zero-set of a scaled SDF should be ≈ 1."""
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)
        ss = sdf_scale(s, 3.0)
        h = 1e-5
        # Gradient at (3, 0, 0) (on scaled sphere surface)
        gx = (_eval(ss, 3 + h, 0, 0) - _eval(ss, 3 - h, 0, 0)) / (2 * h)
        gy = (_eval(ss, 3, h, 0) - _eval(ss, 3, -h, 0)) / (2 * h)
        gz = (_eval(ss, 3, 0, h) - _eval(ss, 3, 0, -h)) / (2 * h)
        grad_mag = math.sqrt(gx ** 2 + gy ** 2 + gz ** 2)
        assert abs(grad_mag - 1.0) < 1e-3

    def test_rotate_90deg_z_axis(self):
        """Rotating a sphere (centred off-axis) by 90° around Z-axis."""
        # Sphere centred at (1, 0, 0)
        s = sdf_sphere((1.0, 0.0, 0.0), 0.5)
        sr = sdf_rotate(s, (0.0, 0.0, 1.0), math.pi / 2)
        # After 90° rotation around Z, centre moves to (0, 1, 0)
        assert abs(_eval(sr, 0, 1, 0) - (-0.5)) < 1e-10

    def test_rotate_preserves_distances(self):
        """Distance from any point to the surface should be preserved under rotation."""
        s = sdf_sphere((0.0, 0.0, 0.0), 1.0)  # symmetric — rotation leaves it invariant
        sr = sdf_rotate(s, (0.0, 0.0, 1.0), math.pi / 3)
        pts = np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype=np.float64)
        np.testing.assert_allclose(s(pts), sr(pts), atol=1e-12)
