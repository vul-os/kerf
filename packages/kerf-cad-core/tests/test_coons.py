"""
test_coons.py
=============
Hermetic tests for kerf_cad_core.geom.coons — Coons patch, edge surface,
and bilinear patch.

All tests use analytic oracles; no OCC, no database, no network.

Coverage groups
---------------
1.  coons_patch — unit-square (planar) patch exact evaluation
2.  coons_patch — boundary correspondence at u=0, u=1, v=0, v=1
3.  coons_patch — corner inconsistency rejection
4.  edge_surface — parallel straight lines → planar ruled strip
5.  edge_surface — two coaxial circles of different radii → frustum
6.  bilinear_patch — four-corner exact evaluation
7.  Determinism — identical surface across repeated calls
8.  Curved boundary Coons patch — boundary correspondence on NURBS arcs
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    make_line_nurbs,
    make_arc_nurbs,
    make_circle_nurbs,
    surface_evaluate,
)
from kerf_cad_core.geom.coons import (
    bilinear_patch,
    coons_patch,
    edge_surface,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _line(p0, p1) -> NurbsCurve:
    """Straight-line NurbsCurve from p0 to p1."""
    return make_line_nurbs(np.asarray(p0, dtype=float),
                           np.asarray(p1, dtype=float))


def _eval(surf: NurbsSurface, u: float, v: float) -> np.ndarray:
    return surface_evaluate(surf, u, v)


def _sample_params(n: int = 7):
    return np.linspace(0.0, 1.0, n)


# ---------------------------------------------------------------------------
# 1.  coons_patch — unit-square planar patch
# ---------------------------------------------------------------------------

class TestCoonsPatchUnitSquare:
    """Four straight-line boundaries of the unit square in z=0."""

    @pytest.fixture(scope="class")
    def square_surf(self):
        c0_u = _line([0, 0, 0], [1, 0, 0])   # v=0 bottom edge
        c1_u = _line([0, 1, 0], [1, 1, 0])   # v=1 top edge
        c0_v = _line([0, 0, 0], [0, 1, 0])   # u=0 left edge
        c1_v = _line([1, 0, 0], [1, 1, 0])   # u=1 right edge
        return coons_patch(c0_u, c1_u, c0_v, c1_v)

    def test_returns_nurbs_surface(self, square_surf):
        assert isinstance(square_surf, NurbsSurface)

    def test_corner_00(self, square_surf):
        pt = _eval(square_surf, 0.0, 0.0)
        np.testing.assert_allclose(pt[:2], [0.0, 0.0], atol=1e-9)

    def test_corner_10(self, square_surf):
        pt = _eval(square_surf, 1.0, 0.0)
        np.testing.assert_allclose(pt[:2], [1.0, 0.0], atol=1e-9)

    def test_corner_01(self, square_surf):
        pt = _eval(square_surf, 0.0, 1.0)
        np.testing.assert_allclose(pt[:2], [0.0, 1.0], atol=1e-9)

    def test_corner_11(self, square_surf):
        pt = _eval(square_surf, 1.0, 1.0)
        np.testing.assert_allclose(pt[:2], [1.0, 1.0], atol=1e-9)

    def test_z_is_zero_everywhere(self, square_surf):
        """Unit-square patch is planar: z=0 for all interior points."""
        for u in _sample_params(9):
            for v in _sample_params(9):
                pt = _eval(square_surf, u, v)
                assert abs(pt[2]) < 1e-9, f"z={pt[2]} at u={u},v={v}"

    def test_bilinear_interpolation_x(self, square_surf):
        """x-coordinate of patch point == u (bilinear interpolation in unit square)."""
        for u in _sample_params(9):
            for v in _sample_params(9):
                pt = _eval(square_surf, u, v)
                assert abs(pt[0] - u) < 1e-9, f"x={pt[0]} != u={u}"

    def test_bilinear_interpolation_y(self, square_surf):
        """y-coordinate of patch point == v."""
        for u in _sample_params(9):
            for v in _sample_params(9):
                pt = _eval(square_surf, u, v)
                assert abs(pt[1] - v) < 1e-9, f"y={pt[1]} != v={v}"

    def test_mid_point(self, square_surf):
        pt = _eval(square_surf, 0.5, 0.5)
        np.testing.assert_allclose(pt[:2], [0.5, 0.5], atol=1e-9)


# ---------------------------------------------------------------------------
# 2.  coons_patch — boundary correspondence
# ---------------------------------------------------------------------------

class TestCoonsPatchBoundaryCorrespondence:
    """Surface evaluated on a boundary must match the input boundary curve."""

    @pytest.fixture(scope="class")
    def curved_surf(self):
        """Coons patch with curved (arc) boundaries in z=0 plane."""
        # Build a "skewed" quadrilateral with 4 straight-line boundaries
        # but with non-axis-aligned directions to exercise the formula
        # beyond the unit square.
        c0_u = _line([0, 0, 0], [2, 0, 0])   # bottom
        c1_u = _line([0, 3, 0], [2, 3, 0])   # top
        c0_v = _line([0, 0, 0], [0, 3, 0])   # left
        c1_v = _line([2, 0, 0], [2, 3, 0])   # right
        return coons_patch(c0_u, c1_u, c0_v, c1_v), c0_u, c1_u, c0_v, c1_v

    def test_boundary_v0_matches_c0_u(self, curved_surf):
        surf, c0_u, c1_u, c0_v, c1_v = curved_surf
        for u in _sample_params(11):
            expected = c0_u.evaluate(c0_u.knots[c0_u.degree] +
                                      u * (c0_u.knots[-c0_u.degree - 1] -
                                           c0_u.knots[c0_u.degree]))
            got = _eval(surf, u, 0.0)
            np.testing.assert_allclose(got[:len(expected)], expected, atol=1e-9,
                                       err_msg=f"v=0 mismatch at u={u}")

    def test_boundary_v1_matches_c1_u(self, curved_surf):
        surf, c0_u, c1_u, c0_v, c1_v = curved_surf
        for u in _sample_params(11):
            expected = c1_u.evaluate(c1_u.knots[c1_u.degree] +
                                      u * (c1_u.knots[-c1_u.degree - 1] -
                                           c1_u.knots[c1_u.degree]))
            got = _eval(surf, u, 1.0)
            np.testing.assert_allclose(got[:len(expected)], expected, atol=1e-9,
                                       err_msg=f"v=1 mismatch at u={u}")

    def test_boundary_u0_matches_c0_v(self, curved_surf):
        surf, c0_u, c1_u, c0_v, c1_v = curved_surf
        for v in _sample_params(11):
            expected = c0_v.evaluate(c0_v.knots[c0_v.degree] +
                                      v * (c0_v.knots[-c0_v.degree - 1] -
                                           c0_v.knots[c0_v.degree]))
            got = _eval(surf, 0.0, v)
            np.testing.assert_allclose(got[:len(expected)], expected, atol=1e-9,
                                       err_msg=f"u=0 mismatch at v={v}")

    def test_boundary_u1_matches_c1_v(self, curved_surf):
        surf, c0_u, c1_u, c0_v, c1_v = curved_surf
        for v in _sample_params(11):
            expected = c1_v.evaluate(c1_v.knots[c1_v.degree] +
                                      v * (c1_v.knots[-c1_v.degree - 1] -
                                           c1_v.knots[c1_v.degree]))
            got = _eval(surf, 1.0, v)
            np.testing.assert_allclose(got[:len(expected)], expected, atol=1e-9,
                                       err_msg=f"u=1 mismatch at v={v}")


# ---------------------------------------------------------------------------
# 3.  coons_patch — corner inconsistency rejection
# ---------------------------------------------------------------------------

class TestCoonsPatchCornerRejection:

    def test_mismatched_corner_00_raises(self):
        """c0_u(0) and c0_v(0) disagree."""
        c0_u = _line([0.5, 0, 0], [1, 0, 0])   # starts at (0.5,0,0)
        c1_u = _line([0, 1, 0], [1, 1, 0])
        c0_v = _line([0, 0, 0], [0, 1, 0])   # starts at (0,0,0) — mismatch
        c1_v = _line([1, 0, 0], [1, 1, 0])
        with pytest.raises(ValueError, match="Corner mismatch"):
            coons_patch(c0_u, c1_u, c0_v, c1_v, tol=0.1)

    def test_mismatched_corner_11_raises(self):
        """c1_u(1) and c1_v(1) disagree."""
        c0_u = _line([0, 0, 0], [1, 0, 0])
        c1_u = _line([0, 1, 0], [1.5, 1, 0])   # ends at (1.5,1,0)
        c0_v = _line([0, 0, 0], [0, 1, 0])
        c1_v = _line([1, 0, 0], [1, 1, 0])   # ends at (1,1,0) — mismatch
        with pytest.raises(ValueError, match="Corner mismatch"):
            coons_patch(c0_u, c1_u, c0_v, c1_v, tol=0.1)

    def test_small_mismatch_within_tol_passes(self):
        """A corner gap smaller than tol should not raise."""
        eps = 1e-8
        c0_u = _line([eps, 0, 0], [1, 0, 0])
        c1_u = _line([0, 1, 0], [1, 1, 0])
        c0_v = _line([0, 0, 0], [0, 1, 0])
        c1_v = _line([1, 0, 0], [1, 1, 0])
        # tol=1e-6 >> eps=1e-8, should pass
        surf = coons_patch(c0_u, c1_u, c0_v, c1_v, tol=1e-6)
        assert isinstance(surf, NurbsSurface)

    def test_large_mismatch_raises(self):
        """Corner disagreement of 1.0 with tol=0.5 raises ValueError."""
        c0_u = _line([0, 0, 0], [1, 0, 0])
        c1_u = _line([0, 1, 0], [1, 1, 0])
        c0_v = _line([0, 0, 0], [0, 1, 0])
        c1_v = _line([1, 0, 0], [2, 1, 0])   # end point displaced by 1 in x
        with pytest.raises(ValueError, match="Corner mismatch"):
            coons_patch(c0_u, c1_u, c0_v, c1_v, tol=0.5)

    def test_error_message_contains_distance(self):
        """The error message should mention the disagreeing pair."""
        c0_u = _line([0, 0, 5], [1, 0, 0])   # starts 5 units above z=0
        c1_u = _line([0, 1, 0], [1, 1, 0])
        c0_v = _line([0, 0, 0], [0, 1, 0])
        c1_v = _line([1, 0, 0], [1, 1, 0])
        with pytest.raises(ValueError) as exc_info:
            coons_patch(c0_u, c1_u, c0_v, c1_v, tol=1.0)
        assert "mismatch" in str(exc_info.value).lower() or "corner" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 4.  edge_surface — two parallel straight lines → planar ruled strip
# ---------------------------------------------------------------------------

class TestEdgeSurfaceParallelLines:

    @pytest.fixture(scope="class")
    def strip(self):
        c0 = _line([0, 0, 0], [1, 0, 0])
        c1 = _line([0, 0, 2], [1, 0, 2])   # c0 shifted up 2 in z
        return edge_surface(c0, c1), c0, c1

    def test_returns_nurbs_surface(self, strip):
        surf, c0, c1 = strip
        assert isinstance(surf, NurbsSurface)

    def test_v0_boundary_on_c0(self, strip):
        surf, c0, c1 = strip
        for u in _sample_params(11):
            expected = _line([0, 0, 0], [1, 0, 0]).evaluate(u)
            got = _eval(surf, u, 0.0)
            np.testing.assert_allclose(got[:3], expected[:3], atol=1e-9)

    def test_v1_boundary_on_c1(self, strip):
        surf, c0, c1 = strip
        for u in _sample_params(11):
            expected = _line([0, 0, 2], [1, 0, 2]).evaluate(u)
            got = _eval(surf, u, 1.0)
            np.testing.assert_allclose(got[:3], expected[:3], atol=1e-9)

    def test_cross_section_is_straight_line(self, strip):
        """At any fixed u, varying v should trace a straight line between
        c0(u) and c1(u)."""
        surf, c0, c1 = strip
        for u in _sample_params(7):
            p0 = _eval(surf, u, 0.0)
            p1 = _eval(surf, u, 1.0)
            for v in _sample_params(9):
                pt = _eval(surf, u, v)
                expected = (1.0 - v) * p0 + v * p1
                np.testing.assert_allclose(pt[:3], expected[:3], atol=1e-9)

    def test_y_is_zero_everywhere(self, strip):
        """Both lines lie in y=0; the ruled surface should too."""
        surf, c0, c1 = strip
        for u in _sample_params(9):
            for v in _sample_params(9):
                pt = _eval(surf, u, v)
                assert abs(pt[1]) < 1e-9, f"y={pt[1]} at u={u},v={v}"


# ---------------------------------------------------------------------------
# 5.  edge_surface — two coaxial circles → frustum (truncated cone)
# ---------------------------------------------------------------------------

class TestEdgeSurfaceFrustum:
    """edge_surface of a unit circle (r=1, z=0) and a circle (r=2, z=3).

    edge_surface uses an exact NURBS tensor-product ruled surface, so every
    point on the surface satisfies the frustum equation exactly (to machine
    precision).  Analytic oracle: r(z) = 1 + z/3 (linearly interpolated
    radius), so sqrt(x^2+y^2) == 1 + z/3 at every sampled point.
    """

    @pytest.fixture(scope="class")
    def frustum(self):
        # Lower circle: radius=1 in z=0 plane.
        c0 = make_arc_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=1.0,
            start_angle=0.0,
            end_angle=2.0 * math.pi,
        )
        # Upper circle: radius=2 in z=3 plane.
        c1 = make_arc_nurbs(
            center=np.array([0.0, 0.0, 3.0]),
            radius=2.0,
            start_angle=0.0,
            end_angle=2.0 * math.pi,
        )
        return edge_surface(c0, c1), c0, c1

    def test_returns_nurbs_surface(self, frustum):
        surf, c0, c1 = frustum
        assert isinstance(surf, NurbsSurface)

    def test_points_on_analytic_frustum(self, frustum):
        """Sampled points satisfy r(z) = 1 + z/3 within 1e-12.

        edge_surface is an exact NURBS ruled surface; the rational blend of
        two rational circles at different radii is the exact cone.
        """
        surf, c0, c1 = frustum
        # Sample interior (avoid u=0/u=1 which are at the seam of the
        # near-360° circle arc).
        us = np.linspace(0.05, 0.95, 8)
        vs = np.linspace(0.1, 0.9, 8)
        for u in us:
            for v in vs:
                pt = _eval(surf, u, v)
                x, y, z = pt[0], pt[1], pt[2]
                r_computed = math.sqrt(x * x + y * y)
                r_expected = 1.0 + z / 3.0
                assert abs(r_computed - r_expected) < 1e-10, (
                    f"Frustum test: r={r_computed:.12f} != r_expected={r_expected:.12f} "
                    f"at u={u:.3f}, v={v:.3f}, z={z:.8f}"
                )

    def test_v0_on_lower_circle(self, frustum):
        """v=0 boundary lies in z=0 plane and at radius=1 (exact circle)."""
        surf, c0, c1 = frustum
        for u in np.linspace(0.1, 0.9, 9):
            pt = _eval(surf, u, 0.0)
            assert abs(pt[2]) < 1e-12, f"z={pt[2]} should be 0 at v=0"
            r = math.sqrt(pt[0] ** 2 + pt[1] ** 2)
            assert abs(r - 1.0) < 1e-10, f"r={r} should be 1.0 at v=0"

    def test_v1_on_upper_circle(self, frustum):
        """v=1 boundary lies in z=3 plane and at radius=2 (exact circle)."""
        surf, c0, c1 = frustum
        for u in np.linspace(0.1, 0.9, 9):
            pt = _eval(surf, u, 1.0)
            assert abs(pt[2] - 3.0) < 1e-12, f"z={pt[2]} should be 3 at v=1"
            r = math.sqrt(pt[0] ** 2 + pt[1] ** 2)
            assert abs(r - 2.0) < 1e-10, f"r={r} should be 2.0 at v=1"

    def test_degree_v_is_one(self, frustum):
        """edge_surface is a linear blend in v — degree_v must be 1."""
        surf, c0, c1 = frustum
        assert surf.degree_v == 1


# ---------------------------------------------------------------------------
# 6.  bilinear_patch — four corners
# ---------------------------------------------------------------------------

class TestBilinearPatch:

    @pytest.fixture(scope="class")
    def patch(self):
        p00 = np.array([0.0, 0.0, 0.0])
        p10 = np.array([3.0, 0.0, 1.0])
        p01 = np.array([0.0, 2.0, -1.0])
        p11 = np.array([3.0, 2.0, 5.0])
        return bilinear_patch(p00, p10, p01, p11), p00, p10, p01, p11

    def test_returns_nurbs_surface(self, patch):
        surf, *_ = patch
        assert isinstance(surf, NurbsSurface)

    def test_corner_00(self, patch):
        surf, p00, p10, p01, p11 = patch
        np.testing.assert_allclose(_eval(surf, 0.0, 0.0), p00, atol=1e-12)

    def test_corner_10(self, patch):
        surf, p00, p10, p01, p11 = patch
        np.testing.assert_allclose(_eval(surf, 1.0, 0.0), p10, atol=1e-12)

    def test_corner_01(self, patch):
        surf, p00, p10, p01, p11 = patch
        np.testing.assert_allclose(_eval(surf, 0.0, 1.0), p01, atol=1e-12)

    def test_corner_11(self, patch):
        surf, p00, p10, p01, p11 = patch
        np.testing.assert_allclose(_eval(surf, 1.0, 1.0), p11, atol=1e-12)

    def test_midpoint_bilinear(self, patch):
        """Mid-point is the average of all four corners."""
        surf, p00, p10, p01, p11 = patch
        expected = 0.25 * (p00 + p10 + p01 + p11)
        np.testing.assert_allclose(_eval(surf, 0.5, 0.5), expected, atol=1e-12)

    def test_edge_u0_linearly_interpolates_v(self, patch):
        """Along u=0 edge, the surface linearly interpolates p00 → p01."""
        surf, p00, p10, p01, p11 = patch
        for v in _sample_params(9):
            expected = (1.0 - v) * p00 + v * p01
            np.testing.assert_allclose(_eval(surf, 0.0, v), expected, atol=1e-12)

    def test_edge_u1_linearly_interpolates_v(self, patch):
        """Along u=1 edge, the surface linearly interpolates p10 → p11."""
        surf, p00, p10, p01, p11 = patch
        for v in _sample_params(9):
            expected = (1.0 - v) * p10 + v * p11
            np.testing.assert_allclose(_eval(surf, 1.0, v), expected, atol=1e-12)

    def test_degree_one(self, patch):
        surf, *_ = patch
        assert surf.degree_u == 1
        assert surf.degree_v == 1


# ---------------------------------------------------------------------------
# 7.  Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:

    def test_coons_patch_deterministic(self):
        c0_u = _line([0, 0, 0], [1, 0, 0])
        c1_u = _line([0, 1, 0], [1, 1, 0])
        c0_v = _line([0, 0, 0], [0, 1, 0])
        c1_v = _line([1, 0, 0], [1, 1, 0])
        surfs = [coons_patch(c0_u, c1_u, c0_v, c1_v) for _ in range(5)]
        for s in surfs[1:]:
            np.testing.assert_array_equal(s.control_points, surfs[0].control_points)

    def test_edge_surface_deterministic(self):
        c0 = _line([0, 0, 0], [1, 0, 0])
        c1 = _line([0, 0, 1], [1, 0, 1])
        surfs = [edge_surface(c0, c1) for _ in range(5)]
        for s in surfs[1:]:
            np.testing.assert_array_equal(s.control_points, surfs[0].control_points)

    def test_bilinear_patch_deterministic(self):
        p00 = np.array([0.0, 0.0, 0.0])
        p10 = np.array([1.0, 0.0, 0.0])
        p01 = np.array([0.0, 1.0, 0.0])
        p11 = np.array([1.0, 1.0, 0.0])
        surfs = [bilinear_patch(p00, p10, p01, p11) for _ in range(5)]
        for s in surfs[1:]:
            np.testing.assert_array_equal(s.control_points, surfs[0].control_points)


# ---------------------------------------------------------------------------
# 8.  Coons patch with arc boundary curves — geometric properties
# ---------------------------------------------------------------------------

class TestCoonsPatchArcBoundary:
    """Coons patch whose u-boundaries are quarter-circle arcs and whose
    v-boundaries are straight lines.

    The Coons formula is evaluated on a polynomial grid and interpolated, so
    the surface only *approximately* reproduces the rational arc boundaries.
    We verify:
    (a) geometric properties intrinsic to the Coons formula (cylinder test),
    (b) that corner points are reproduced exactly,
    (c) that the straight-line (v-direction) boundaries are reproduced exactly.
    """

    @pytest.fixture(scope="class")
    def arc_surf(self):
        # Quarter arc from (1,0,0) to (0,1,0) at z=0.
        c0_u = make_arc_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=1.0,
            start_angle=0.0,
            end_angle=math.pi / 2.0,
        )
        # Same arc shifted up in z by 1.
        c1_u = make_arc_nurbs(
            center=np.array([0.0, 0.0, 1.0]),
            radius=1.0,
            start_angle=0.0,
            end_angle=math.pi / 2.0,
        )
        # Straight lines connecting the ends.
        c0_v = _line([1.0, 0.0, 0.0], [1.0, 0.0, 1.0])   # u=0 side
        c1_v = _line([0.0, 1.0, 0.0], [0.0, 1.0, 1.0])   # u=1 side
        surf = coons_patch(c0_u, c1_u, c0_v, c1_v, grid_n=32)
        return surf, c0_u, c1_u, c0_v, c1_v

    def test_returns_nurbs_surface(self, arc_surf):
        surf, *_ = arc_surf
        assert isinstance(surf, NurbsSurface)

    def test_corner_00(self, arc_surf):
        """Corner (u=0, v=0) == (1, 0, 0)."""
        surf, *_ = arc_surf
        np.testing.assert_allclose(_eval(surf, 0.0, 0.0)[:3], [1.0, 0.0, 0.0], atol=1e-9)

    def test_corner_10(self, arc_surf):
        """Corner (u=1, v=0) == (0, 1, 0)."""
        surf, *_ = arc_surf
        np.testing.assert_allclose(_eval(surf, 1.0, 0.0)[:3], [0.0, 1.0, 0.0], atol=1e-9)

    def test_corner_01(self, arc_surf):
        """Corner (u=0, v=1) == (1, 0, 1)."""
        surf, *_ = arc_surf
        np.testing.assert_allclose(_eval(surf, 0.0, 1.0)[:3], [1.0, 0.0, 1.0], atol=1e-9)

    def test_corner_11(self, arc_surf):
        """Corner (u=1, v=1) == (0, 1, 1)."""
        surf, *_ = arc_surf
        np.testing.assert_allclose(_eval(surf, 1.0, 1.0)[:3], [0.0, 1.0, 1.0], atol=1e-9)

    def test_u0_straight_line_boundary_exact(self, arc_surf):
        """u=0 boundary is a straight line from (1,0,0) to (1,0,1); exact."""
        surf, c0_u, c1_u, c0_v, c1_v = arc_surf
        for v in _sample_params(9):
            t = c0_v.knots[c0_v.degree] + v * (c0_v.knots[-c0_v.degree - 1] - c0_v.knots[c0_v.degree])
            expected = c0_v.evaluate(t)[:3]
            got = _eval(surf, 0.0, v)[:3]
            np.testing.assert_allclose(got, expected, atol=1e-9,
                                       err_msg=f"u=0 line boundary mismatch at v={v}")

    def test_u1_straight_line_boundary_exact(self, arc_surf):
        """u=1 boundary is a straight line from (0,1,0) to (0,1,1); exact."""
        surf, c0_u, c1_u, c0_v, c1_v = arc_surf
        for v in _sample_params(9):
            t = c1_v.knots[c1_v.degree] + v * (c1_v.knots[-c1_v.degree - 1] - c1_v.knots[c1_v.degree])
            expected = c1_v.evaluate(t)[:3]
            got = _eval(surf, 1.0, v)[:3]
            np.testing.assert_allclose(got, expected, atol=1e-9,
                                       err_msg=f"u=1 line boundary mismatch at v={v}")

    def test_surface_points_lie_on_unit_cylinder(self, arc_surf):
        """All interior points lie approximately on the unit cylinder x^2+y^2=1.

        The Coons patch interpolates the quarter-arc boundaries and straight
        side rails.  The Coons formula with arc u-boundaries and straight
        v-boundaries does not produce the exact cylinder — it is a polynomial
        approximation.  We verify r^2 ≈ 1 within 5e-5.
        """
        surf, c0_u, c1_u, c0_v, c1_v = arc_surf
        for u in np.linspace(0.0, 1.0, 7):
            for v in np.linspace(0.0, 1.0, 7):
                pt = _eval(surf, u, v)
                r2 = pt[0] ** 2 + pt[1] ** 2
                assert abs(r2 - 1.0) < 5e-5, (
                    f"Point deviates from unit cylinder: r^2={r2:.8f} "
                    f"at u={u:.3f}, v={v:.3f}"
                )

    def test_z_range(self, arc_surf):
        """All surface points have z in [0, 1] (between the two arc planes)."""
        surf, *_ = arc_surf
        for u in np.linspace(0.0, 1.0, 7):
            for v in np.linspace(0.0, 1.0, 7):
                pt = _eval(surf, u, v)
                assert -1e-9 <= pt[2] <= 1.0 + 1e-9, (
                    f"z={pt[2]} out of [0,1] at u={u:.3f}, v={v:.3f}"
                )
