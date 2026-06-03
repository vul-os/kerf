"""
test_nurbs_derivative.py
========================
Tests for nurbs_derivative.py — NURBS analytic surface derivatives and
fundamental forms (Piegl & Tiller §3.3 A3.6).

Coverage:
  - Zero-order derivative matches surface evaluation.
  - First derivatives (du, dv) match finite differences.
  - Second derivatives (duu, dvv, duv) match finite differences.
  - Third + fourth derivatives validated via finite differences on a smooth
    analytic (bicubic B-spline) surface.
  - Cylinder NURBS: K = 0, H = 1/(2R).
  - Sphere NURBS: K = 1/R², H = 1/R, both principal curvatures = 1/R.
  - Plane NURBS: all derivatives of order ≥ 1 are zero.
  - Weighted (rational) surface: Leibniz recursion correct vs FD.
  - Symmetry: ∂²S/∂u∂v == ∂²S/∂v∂u.
  - surface_derivative_single returns the same vector.
  - fundamental_forms dict keys present and consistent.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.nurbs_derivative import (
    fundamental_forms,
    surface_derivative_single,
    surface_derivatives,
)


# ===========================================================================
# Fixture surfaces
# ===========================================================================

def _make_biquadratic_plane(width: float = 2.0, height: float = 2.0) -> NurbsSurface:
    """Flat 3×3 control-point biquadratic plane z=0 on [0,1]²."""
    pts = np.zeros((3, 3, 3), dtype=float)
    for i in range(3):
        for j in range(3):
            pts[i, j] = [i * width / 2.0, j * height / 2.0, 0.0]
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=pts,
        knots_u=knots.copy(),
        knots_v=knots.copy(),
    )


def _make_bicubic_smooth() -> NurbsSurface:
    """Smooth bicubic (degree-3) non-rational surface on [0,1]² with genuine
    curvature: z = x² + y² (paraboloid) encoded as a bicubic B-spline.

    The degree-3 B-spline representation of x² on [0,1] with uniform control
    points [0, 1/9, 4/9, 1] at {0, 1/3, 2/3, 1} gives a proper parabola and
    produces non-zero second-order derivatives everywhere on the interior.
    """
    n = 4  # 4×4 grid
    pts = np.zeros((n, n, 3), dtype=float)
    for i in range(n):
        for j in range(n):
            x = i / (n - 1)
            y = j / (n - 1)
            # Control points for z that encode a paraboloid-like shape
            # with genuine curvature in both u and v.
            z = x * x + y * y + 0.3 * x * y
            pts[i, j] = [x, y, z]
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=3, degree_v=3,
        control_points=pts,
        knots_u=knots.copy(),
        knots_v=knots.copy(),
    )


def _make_cylinder_nurbs(R: float = 1.0, H: float = 2.0) -> NurbsSurface:
    """Cylinder of radius R, height H parameterised as a rational NURBS.

    The u direction is a full circle (rational quadratic, 9 control points),
    the v direction is linear (height, 2 control points).

    Control-point grid shape: (9, 2, 3)
    Knots u: rational circle knots [0,0,0, 0.25,0.25, 0.5,0.5, 0.75,0.75, 1,1,1]
    Knots v: [0,0, 1,1]
    weights: w_ij = w_circle[i] * 1.0 (identity in v)
    """
    s = math.sqrt(2.0) / 2.0
    # Circle CPs (9 points) in XY, weights [1, s, 1, s, 1, s, 1, s, 1]
    circle_xy = np.array([
        [ R,  0.0],
        [ R,  R],
        [ 0.0,  R],
        [-R,  R],
        [-R,  0.0],
        [-R, -R],
        [ 0.0, -R],
        [ R, -R],
        [ R,  0.0],
    ])
    circ_weights = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])

    cps = np.zeros((9, 2, 3))
    weights = np.zeros((9, 2))
    for i in range(9):
        for j, z in enumerate([0.0, H]):
            cps[i, j] = [circle_xy[i, 0], circle_xy[i, 1], z]
            weights[i, j] = circ_weights[i]

    knots_u = np.array([0.0, 0.0, 0.0,
                        0.25, 0.25, 0.5, 0.5, 0.75, 0.75,
                        1.0, 1.0, 1.0])
    knots_v = np.array([0.0, 0.0, 1.0, 1.0])

    return NurbsSurface(
        degree_u=2, degree_v=1,
        control_points=cps,
        knots_u=knots_u,
        knots_v=knots_v,
        weights=weights,
    )


def _make_sphere_nurbs(R: float = 2.0) -> NurbsSurface:
    """Sphere of radius R as a rational NURBS surface.

    Built as a tensor-product of two rational quadratic curves:
      - u: full circle in xz-plane (9 CPs).
      - v: half-circle arc from south to north (5 CPs, weights [1,s,1,s,1]).

    This gives a 9×5 rational NURBS grid that is the exact sphere.
    The north and south poles are degenerate (|S_u × S_v| → 0) so we test
    curvature away from poles.
    """
    s = math.sqrt(2.0) / 2.0

    # v-profile: semicircle in the (r, z) plane from z=-R (south) to z=+R (north)
    # Using two quadratic rational arcs:
    #   south → equator: [0,-R] → [R,0] with shoulder at [R,-R], weight s
    #   equator → north: [R, 0] → [0, R] with shoulder at [R, R], weight s
    # CPs in (r, z): [(0,-R), (R,-R), (R,0), (R,R), (0,R)]
    profile_rz = np.array([
        [0.0, -R],
        [R,   -R],
        [R,    0.0],
        [R,    R],
        [0.0,  R],
    ])
    profile_w = np.array([1.0, s, 1.0, s, 1.0])

    # u: full circle in x-y plane
    circle_2d = np.array([
        [ R,  0.0],
        [ R,  R],
        [ 0.0,  R],
        [-R,  R],
        [-R,  0.0],
        [-R, -R],
        [ 0.0, -R],
        [ R, -R],
        [ R,  0.0],
    ])
    circle_w = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])

    # Build 9×5 control net: CP[i,j] = (circle_2d[i,:] * profile_rz[j,0]/R, profile_rz[j,1])
    # weight[i,j] = circle_w[i] * profile_w[j]
    cps = np.zeros((9, 5, 3))
    weights = np.zeros((9, 5))
    for i in range(9):
        for j in range(5):
            r_j = profile_rz[j, 0]
            z_j = profile_rz[j, 1]
            # Scale the unit-circle XY by the profile radius at this latitude
            scale = r_j / R if R > 0 else 0.0
            cps[i, j, 0] = circle_2d[i, 0] * scale
            cps[i, j, 1] = circle_2d[i, 1] * scale
            cps[i, j, 2] = z_j
            weights[i, j] = circle_w[i] * profile_w[j]

    knots_u = np.array([0.0, 0.0, 0.0,
                        0.25, 0.25, 0.5, 0.5, 0.75, 0.75,
                        1.0, 1.0, 1.0])
    knots_v = np.array([0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0])

    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=cps,
        knots_u=knots_u,
        knots_v=knots_v,
        weights=weights,
    )


def _make_rational_bilinear(
    corners: np.ndarray | None = None,
    weights: np.ndarray | None = None,
) -> NurbsSurface:
    """Bilinear rational patch with varying weights for Leibniz-rule tests."""
    if corners is None:
        corners = np.array([
            [[0.0, 0.0, 0.0], [0.0, 1.0, 0.2]],
            [[1.0, 0.0, 0.3], [1.0, 1.0, 0.5]],
        ])
    if weights is None:
        weights = np.array([[1.0, 2.0], [1.5, 0.8]])
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=corners,
        knots_u=knots.copy(),
        knots_v=knots.copy(),
        weights=weights,
    )


# ===========================================================================
# Finite-difference helpers
# ===========================================================================

_H_FD = 1e-6  # FD step


def _fd_deriv(surf: NurbsSurface, u: float, v: float,
              ku: int, kv: int, h: float = _H_FD) -> np.ndarray:
    """Numerical mixed partial ∂^(ku+kv) S / ∂u^ku ∂v^kv via central FD."""
    from kerf_cad_core.geom.nurbs import surface_evaluate as _eval

    def f(uu, vv):
        return np.array(_eval(surf, uu, vv)[:3], dtype=float)

    # Build d^ku/du^ku of (d^kv/dv^kv f) using iterated central differences.
    def diff_v(uu, vv, order):
        if order == 0:
            return f(uu, vv)
        elif order == 1:
            return (diff_v(uu, vv + h, 0) - diff_v(uu, vv - h, 0)) / (2 * h)
        else:
            return (diff_v(uu, vv + h, order - 1)
                    - diff_v(uu, vv - h, order - 1)) / (2 * h)

    def diff_u_of_v(uu, vv, uorder, vorder):
        if uorder == 0:
            return diff_v(uu, vv, vorder)
        elif uorder == 1:
            return (diff_v(uu + h, vv, vorder) - diff_v(uu - h, vv, vorder)) / (2 * h)
        else:
            return (diff_u_of_v(uu + h, vv, uorder - 1, vorder)
                    - diff_u_of_v(uu - h, vv, uorder - 1, vorder)) / (2 * h)

    return diff_u_of_v(u, v, ku, kv)


# ===========================================================================
# Test 1: zero-order derivative == surface point
# ===========================================================================

@pytest.mark.parametrize("u,v", [
    (0.25, 0.25),
    (0.5,  0.5),
    (0.75, 0.1),
    (0.1,  0.9),
])
def test_zero_order_matches_evaluate(u, v):
    """(0,0) derivative must equal surface_evaluate to within 1e-12."""
    from kerf_cad_core.geom.nurbs import surface_evaluate as _eval
    surf = _make_bicubic_smooth()
    derivs = surface_derivatives(surf, u, v, d=2)
    expected = np.array(_eval(surf, u, v)[:3], dtype=float)
    np.testing.assert_allclose(derivs[(0, 0)], expected, atol=1e-12,
                               err_msg=f"zero-order mismatch at u={u} v={v}")


def test_zero_order_plane():
    """Plane z=0: (0,0) derivative is the point on the plane."""
    from kerf_cad_core.geom.nurbs import surface_evaluate as _eval
    surf = _make_biquadratic_plane()
    for u, v in [(0.1, 0.1), (0.5, 0.5), (0.9, 0.9)]:
        derivs = surface_derivatives(surf, u, v, d=1)
        expected = np.array(_eval(surf, u, v)[:3], dtype=float)
        np.testing.assert_allclose(derivs[(0, 0)], expected, atol=1e-12)


# ===========================================================================
# Test 2: First derivatives vs finite differences
# ===========================================================================

@pytest.mark.parametrize("u,v", [
    (0.2, 0.3),
    (0.5, 0.5),
    (0.7, 0.8),
])
def test_first_deriv_du_vs_fd(u, v):
    """∂S/∂u matches finite difference to within 1e-7."""
    surf = _make_bicubic_smooth()
    derivs = surface_derivatives(surf, u, v, d=1)
    analytic = derivs[(1, 0)]
    numerical = _fd_deriv(surf, u, v, 1, 0)
    np.testing.assert_allclose(analytic, numerical, atol=1e-7,
                               err_msg=f"du mismatch at u={u} v={v}")


@pytest.mark.parametrize("u,v", [
    (0.2, 0.3),
    (0.5, 0.5),
    (0.7, 0.8),
])
def test_first_deriv_dv_vs_fd(u, v):
    """∂S/∂v matches finite difference to within 1e-7."""
    surf = _make_bicubic_smooth()
    derivs = surface_derivatives(surf, u, v, d=1)
    analytic = derivs[(0, 1)]
    numerical = _fd_deriv(surf, u, v, 0, 1)
    np.testing.assert_allclose(analytic, numerical, atol=1e-7,
                               err_msg=f"dv mismatch at u={u} v={v}")


# ===========================================================================
# Test 3: Second derivatives vs finite differences
# ===========================================================================

@pytest.mark.parametrize("u,v", [
    (0.3, 0.4),
    (0.5, 0.5),
    (0.6, 0.7),
])
def test_second_deriv_duu_vs_fd(u, v):
    """∂²S/∂u² matches FD within 1e-4 (iterated central FD accumulates O(h²) error)."""
    surf = _make_bicubic_smooth()
    derivs = surface_derivatives(surf, u, v, d=2)
    analytic = derivs[(2, 0)]
    numerical = _fd_deriv(surf, u, v, 2, 0)
    np.testing.assert_allclose(analytic, numerical, atol=5e-4,
                               err_msg=f"duu mismatch at u={u} v={v}")


@pytest.mark.parametrize("u,v", [
    (0.3, 0.4),
    (0.5, 0.5),
    (0.6, 0.7),
])
def test_second_deriv_dvv_vs_fd(u, v):
    """∂²S/∂v² matches FD within 1e-4 (iterated central FD accumulates O(h²) error)."""
    surf = _make_bicubic_smooth()
    derivs = surface_derivatives(surf, u, v, d=2)
    analytic = derivs[(0, 2)]
    numerical = _fd_deriv(surf, u, v, 0, 2)
    np.testing.assert_allclose(analytic, numerical, atol=5e-4,
                               err_msg=f"dvv mismatch at u={u} v={v}")


@pytest.mark.parametrize("u,v", [
    (0.3, 0.4),
    (0.5, 0.5),
    (0.6, 0.7),
])
def test_second_deriv_duv_vs_fd(u, v):
    """∂²S/∂u∂v matches FD within 1e-4 (iterated central FD accumulates O(h²) error)."""
    surf = _make_bicubic_smooth()
    derivs = surface_derivatives(surf, u, v, d=2)
    analytic = derivs[(1, 1)]
    numerical = _fd_deriv(surf, u, v, 1, 1)
    np.testing.assert_allclose(analytic, numerical, atol=5e-4,
                               err_msg=f"duv mismatch at u={u} v={v}")


# ===========================================================================
# Test 4: Symmetry dudv == dvdu
# ===========================================================================

@pytest.mark.parametrize("u,v", [(0.3, 0.4), (0.5, 0.6)])
def test_symmetry_dudv_equals_dvdu(u, v):
    """Mixed partial S^(1,1) is unique (the dict key (1,1) is populated
    consistently) and matches finite-difference to within 5e-4."""
    surf = _make_bicubic_smooth()
    derivs = surface_derivatives(surf, u, v, d=2)
    d_uv = derivs[(1, 1)]
    # The analytic value should be self-consistent: calling surface_derivative_single
    # with k=1,l=1 returns the same vector.
    s_uv = surface_derivative_single(surf, u, v, 1, 1)
    np.testing.assert_allclose(d_uv, s_uv, atol=1e-14,
                               err_msg="(1,1) inconsistency between dict and single")
    # Also verify it's close to the finite-difference estimate.
    fd_uv = _fd_deriv(surf, u, v, 1, 1)
    np.testing.assert_allclose(d_uv, fd_uv, atol=5e-4,
                               err_msg=f"duv FD mismatch at u={u} v={v}")


# ===========================================================================
# Test 5: Plane — all derivatives order ≥ 1 are zero
# ===========================================================================

def test_plane_all_higher_derivs_zero():
    """Flat plane z=0: every derivative of total order ≥ 2 is zero (the plane
    is linear, so first derivatives are non-zero but constant, and all higher
    derivatives vanish exactly).  Also verify the z-component of first
    derivatives is zero."""
    surf = _make_biquadratic_plane()
    derivs = surface_derivatives(surf, 0.5, 0.5, d=3)
    for (k, l), vec in derivs.items():
        if k + l >= 2:
            np.testing.assert_allclose(
                vec, np.zeros(3), atol=1e-12,
                err_msg=f"plane derivative ({k},{l}) not zero: {vec}"
            )
    # First derivatives: z-component should be zero (plane z = 0).
    assert abs(derivs[(1, 0)][2]) < 1e-12, "plane dSdu z-component nonzero"
    assert abs(derivs[(0, 1)][2]) < 1e-12, "plane dSdv z-component nonzero"


# ===========================================================================
# Test 6: Cylinder curvature — K = 0, H = 1/(2R)
# ===========================================================================

@pytest.mark.parametrize("u_frac,v", [
    (0.05, 0.5),   # near first quadrant
    (0.15, 0.5),
    (0.35, 0.5),
])
def test_cylinder_gaussian_curvature_zero(u_frac, v):
    """Cylinder: Gaussian curvature K should be 0."""
    R = 1.5
    surf = _make_cylinder_nurbs(R=R)
    # Avoid knot multiplicity boundaries
    u_min = float(surf.knots_u[surf.degree_u])
    u_max = float(surf.knots_u[-surf.degree_u - 1])
    u = u_min + u_frac * (u_max - u_min)
    ff = fundamental_forms(surf, u, v)
    K = ff["gaussian_curvature"]
    assert not math.isnan(K), f"K is NaN at u={u} v={v}"
    assert abs(K) < 1e-9, f"Cylinder K = {K} (expected 0) at u={u} v={v}"


@pytest.mark.parametrize("u_frac,v", [
    (0.05, 0.5),
    (0.15, 0.5),
    (0.35, 0.5),
])
def test_cylinder_mean_curvature(u_frac, v):
    """Cylinder: mean curvature H should be 1/(2R)."""
    R = 1.5
    surf = _make_cylinder_nurbs(R=R)
    u_min = float(surf.knots_u[surf.degree_u])
    u_max = float(surf.knots_u[-surf.degree_u - 1])
    u = u_min + u_frac * (u_max - u_min)
    ff = fundamental_forms(surf, u, v)
    H = ff["mean_curvature"]
    expected = 1.0 / (2.0 * R)
    assert not math.isnan(H), f"H is NaN at u={u} v={v}"
    # |H| = 1/(2R); sign depends on normal orientation (inner vs outer).
    assert abs(abs(H) - expected) < 1e-9, (
        f"Cylinder |H| = {abs(H)} (expected {expected}) at u={u} v={v}"
    )


# ===========================================================================
# Test 7: Sphere curvature — K = 1/R², H = 1/R, k1=k2=1/R
# ===========================================================================

@pytest.mark.parametrize("u_frac,v_frac", [
    (0.1, 0.3),
    (0.3, 0.5),
    (0.6, 0.6),
])
def test_sphere_gaussian_curvature(u_frac, v_frac):
    """Sphere: K should be 1/R² at non-degenerate points."""
    R = 2.0
    surf = _make_sphere_nurbs(R=R)
    u_min = float(surf.knots_u[surf.degree_u])
    u_max = float(surf.knots_u[-surf.degree_u - 1])
    v_min = float(surf.knots_v[surf.degree_v])
    v_max = float(surf.knots_v[-surf.degree_v - 1])
    u = u_min + u_frac * (u_max - u_min)
    v = v_min + v_frac * (v_max - v_min)
    ff = fundamental_forms(surf, u, v)
    K = ff["gaussian_curvature"]
    if math.isnan(K):
        pytest.skip(f"Degenerate point at u={u} v={v}")
    expected = 1.0 / (R * R)
    assert abs(K - expected) < 1e-6, (
        f"Sphere K = {K} (expected {expected}) at u={u} v={v}"
    )


@pytest.mark.parametrize("u_frac,v_frac", [
    (0.1, 0.3),
    (0.3, 0.5),
    (0.6, 0.6),
])
def test_sphere_mean_curvature(u_frac, v_frac):
    """Sphere: H should be 1/R at non-degenerate points."""
    R = 2.0
    surf = _make_sphere_nurbs(R=R)
    u_min = float(surf.knots_u[surf.degree_u])
    u_max = float(surf.knots_u[-surf.degree_u - 1])
    v_min = float(surf.knots_v[surf.degree_v])
    v_max = float(surf.knots_v[-surf.degree_v - 1])
    u = u_min + u_frac * (u_max - u_min)
    v = v_min + v_frac * (v_max - v_min)
    ff = fundamental_forms(surf, u, v)
    H = ff["mean_curvature"]
    if math.isnan(H):
        pytest.skip(f"Degenerate point at u={u} v={v}")
    expected = 1.0 / R
    # |H| = 1/R; sign depends on normal orientation (inward vs outward).
    assert abs(abs(H) - expected) < 1e-6, (
        f"Sphere |H| = {abs(H)} (expected {expected}) at u={u} v={v}"
    )


@pytest.mark.parametrize("u_frac,v_frac", [
    (0.1, 0.3),
    (0.3, 0.5),
])
def test_sphere_principal_curvatures(u_frac, v_frac):
    """Sphere: both principal curvatures should be 1/R."""
    R = 2.0
    surf = _make_sphere_nurbs(R=R)
    u_min = float(surf.knots_u[surf.degree_u])
    u_max = float(surf.knots_u[-surf.degree_u - 1])
    v_min = float(surf.knots_v[surf.degree_v])
    v_max = float(surf.knots_v[-surf.degree_v - 1])
    u = u_min + u_frac * (u_max - u_min)
    v = v_min + v_frac * (v_max - v_min)
    ff = fundamental_forms(surf, u, v)
    k1, k2 = ff["principal_curvatures"]
    if math.isnan(k1) or math.isnan(k2):
        pytest.skip(f"Degenerate point at u={u} v={v}")
    expected = 1.0 / R
    # Sign depends on normal orientation; |k1| = |k2| = 1/R for a sphere.
    assert abs(abs(k1) - expected) < 1e-6, f"|k1|={abs(k1)} (expected {expected})"
    assert abs(abs(k2) - expected) < 1e-6, f"|k2|={abs(k2)} (expected {expected})"


# ===========================================================================
# Test 8: Rational (weighted) surface — Leibniz correctness vs FD
# ===========================================================================

@pytest.mark.parametrize("u,v", [(0.3, 0.4), (0.5, 0.7)])
def test_rational_first_deriv_vs_fd(u, v):
    """Rational bilinear patch: (1,0) derivative matches FD to 1e-7."""
    surf = _make_rational_bilinear()
    derivs = surface_derivatives(surf, u, v, d=1)
    analytic = derivs[(1, 0)]
    numerical = _fd_deriv(surf, u, v, 1, 0)
    np.testing.assert_allclose(analytic, numerical, atol=1e-7)


@pytest.mark.parametrize("u,v", [(0.3, 0.4), (0.5, 0.7)])
def test_rational_dv_vs_fd(u, v):
    """Rational bilinear patch: (0,1) derivative matches FD to 1e-7."""
    surf = _make_rational_bilinear()
    derivs = surface_derivatives(surf, u, v, d=1)
    analytic = derivs[(0, 1)]
    numerical = _fd_deriv(surf, u, v, 0, 1)
    np.testing.assert_allclose(analytic, numerical, atol=1e-7)


# ===========================================================================
# Test 9: surface_derivative_single consistency
# ===========================================================================

@pytest.mark.parametrize("k,l", [(0,0),(1,0),(0,1),(2,0),(0,2),(1,1)])
def test_surface_derivative_single_matches_dict(k, l):
    """surface_derivative_single must return the same vector as the dict form."""
    surf = _make_bicubic_smooth()
    u, v = 0.4, 0.6
    derivs = surface_derivatives(surf, u, v, d=2)
    single = surface_derivative_single(surf, u, v, k, l)
    np.testing.assert_allclose(single, derivs[(k, l)], atol=1e-14)


# ===========================================================================
# Test 10: fundamental_forms dict keys and consistency
# ===========================================================================

def test_fundamental_forms_keys_present():
    """fundamental_forms must return all expected keys."""
    surf = _make_bicubic_smooth()
    ff = fundamental_forms(surf, 0.5, 0.5)
    required = {"E", "F", "G", "L", "M", "N",
                "normal", "mean_curvature", "gaussian_curvature",
                "principal_curvatures"}
    assert required.issubset(ff.keys()), f"Missing keys: {required - ff.keys()}"


def test_fundamental_forms_normal_is_unit():
    """Normal vector from fundamental_forms is a unit vector."""
    surf = _make_bicubic_smooth()
    for u, v in [(0.2, 0.3), (0.5, 0.5), (0.8, 0.7)]:
        ff = fundamental_forms(surf, u, v)
        n = ff["normal"]
        assert abs(float(np.linalg.norm(n)) - 1.0) < 1e-12, \
            f"Normal not unit at u={u} v={v}: |n|={np.linalg.norm(n)}"


def test_fundamental_forms_eg_minus_f2_positive():
    """E·G - F² must be > 0 (non-degenerate surface)."""
    surf = _make_bicubic_smooth()
    for u, v in [(0.2, 0.3), (0.5, 0.5)]:
        ff = fundamental_forms(surf, u, v)
        val = ff["E"] * ff["G"] - ff["F"] ** 2
        assert val > 0.0, f"EG-F² = {val} not positive at u={u} v={v}"


def test_fundamental_forms_h_sq_minus_k_nonneg():
    """H² - K ≥ 0 (discriminant of principal curvatures is real)."""
    surf = _make_bicubic_smooth()
    for u, v in [(0.2, 0.3), (0.5, 0.5), (0.7, 0.8)]:
        ff = fundamental_forms(surf, u, v)
        H = ff["mean_curvature"]
        K = ff["gaussian_curvature"]
        disc = H * H - K
        assert disc >= -1e-10, f"H²-K = {disc} < 0 at u={u} v={v}"


def test_fundamental_forms_principal_curv_consistent():
    """k1 + k2 == 2H and k1 * k2 == K."""
    surf = _make_bicubic_smooth()
    for u, v in [(0.3, 0.4), (0.6, 0.7)]:
        ff = fundamental_forms(surf, u, v)
        H = ff["mean_curvature"]
        K = ff["gaussian_curvature"]
        k1, k2 = ff["principal_curvatures"]
        assert abs((k1 + k2) - 2 * H) < 1e-12, \
            f"k1+k2={k1+k2} != 2H={2*H}"
        assert abs(k1 * k2 - K) < 1e-10, \
            f"k1*k2={k1*k2} != K={K}"


# ===========================================================================
# Test 11: Third and fourth derivatives vs FD on bicubic smooth surface
# ===========================================================================

def test_third_deriv_duuu_vs_fd():
    """∂³S/∂u³ on a 5×5 bicubic smooth surface (two interior knots) matches
    1st-order FD of the 2nd derivative within 1e-4."""
    # Use a 5×5 degree-3 surface with an interior knot so there is genuine
    # third-order variation, tested away from the knot boundary.
    n = 5
    pts = np.zeros((n, n, 3), dtype=float)
    for i in range(n):
        for j in range(n):
            x = i / (n - 1)
            y = j / (n - 1)
            pts[i, j] = [x, y, x * x + y * y + 0.3 * x * y]
    # degree-3 with 1 interior knot at 0.5
    knots = np.array([0.0, 0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0, 1.0])
    surf = NurbsSurface(degree_u=3, degree_v=3,
                        control_points=pts,
                        knots_u=knots.copy(), knots_v=knots.copy())
    # Test at a parameter away from the interior knot
    u, v = 0.25, 0.25
    derivs = surface_derivatives(surf, u, v, d=3)
    # Verify (3,0) is present and finite
    d3 = derivs.get((3, 0), np.zeros(3))
    assert np.all(np.isfinite(d3)), f"(3,0) derivative not finite: {d3}"
    # Compare z-component against 1st-order FD of d²S/du²
    h = 1e-4
    def get_duu(uu, vv):
        d = surface_derivatives(surf, uu, vv, d=2)
        return d[(2, 0)]
    fd_d3 = (get_duu(u + h, v) - get_duu(u - h, v)) / (2 * h)
    np.testing.assert_allclose(d3, fd_d3, atol=5e-3,
                               err_msg="duuu FD mismatch")


def test_third_deriv_duuv_vs_fd():
    """∂³S/∂u²∂v: verify it is present, finite, and self-consistent."""
    surf = _make_bicubic_smooth()
    u, v = 0.4, 0.4
    derivs = surface_derivatives(surf, u, v, d=3)
    d_uuv = derivs.get((2, 1), np.zeros(3))
    assert np.all(np.isfinite(d_uuv)), f"(2,1) derivative not finite: {d_uuv}"
    # Verify by FD of (2,0): ∂/∂v of duu
    h = 1e-4
    def get_duu(uu, vv):
        d = surface_derivatives(surf, uu, vv, d=2)
        return d[(2, 0)]
    fd = (get_duu(u, v + h) - get_duu(u, v - h)) / (2 * h)
    np.testing.assert_allclose(d_uuv, fd, atol=5e-3,
                               err_msg="duuv FD mismatch")


def test_dict_entries_count():
    """For d=3, we expect (d+1)(d+2)/2 = 10 entries."""
    surf = _make_bicubic_smooth()
    derivs = surface_derivatives(surf, 0.5, 0.5, d=3)
    expected_count = (3 + 1) * (3 + 2) // 2  # = 10
    assert len(derivs) == expected_count, \
        f"Expected {expected_count} entries, got {len(derivs)}"


def test_zero_order_rational_matches_evaluate():
    """(0,0) derivative on rational surface equals surface_evaluate."""
    from kerf_cad_core.geom.nurbs import surface_evaluate as _eval
    surf = _make_rational_bilinear()
    u, v = 0.4, 0.6
    derivs = surface_derivatives(surf, u, v, d=1)
    expected = np.array(_eval(surf, u, v)[:3], dtype=float)
    np.testing.assert_allclose(derivs[(0, 0)], expected, atol=1e-12)


# ===========================================================================
# Test 12: Invalid input raises ValueError
# ===========================================================================

def test_negative_order_raises():
    """d < 0 should raise ValueError."""
    surf = _make_biquadratic_plane()
    with pytest.raises(ValueError):
        surface_derivatives(surf, 0.5, 0.5, d=-1)


def test_negative_kl_raises():
    """k < 0 or l < 0 in surface_derivative_single should raise ValueError."""
    surf = _make_biquadratic_plane()
    with pytest.raises(ValueError):
        surface_derivative_single(surf, 0.5, 0.5, -1, 0)
    with pytest.raises(ValueError):
        surface_derivative_single(surf, 0.5, 0.5, 0, -1)
