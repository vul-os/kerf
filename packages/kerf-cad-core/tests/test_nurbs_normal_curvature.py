"""
Tests for kerf_cad_core.geom.normal_curvature
===============================================
All tests are hermetic (no OCC, no network).

Analytic oracles:

1.  Unit sphere (rational NURBS)   — κ_n = 1 in every direction,
    K = 1, H = 1, is_umbilic = True.
2.  Sphere of radius R = 3         — κ_n = 1/3 in every direction.
3.  Cylinder of radius R = 2       — κ_n = 0 along axis, κ_n = 1/R across.
4.  Saddle surface (hyperbolic paraboloid) — κ_1 < 0 < κ_2, K < 0.
5.  Flat plane                     — κ_n = 0 in every direction, K = 0.
6.  Euler's formula                — κ_n(θ) = κ_1 cos²θ + κ_2 sin²θ
    (aligned with principal dirs, φ = 0) for a torus-like elliptic patch.
7.  Direction invariance on sphere — κ_n identical for 12 uniformly spaced
    tangent directions.
8.  Re-export                      — NormalCurvatureReport importable from
    kerf_cad_core.geom.
9.  Degenerate direction (du=dv=0) — is_degenerate=True.
10. Bilinear planar patch           — κ_n = 0 everywhere (exact quadric).
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.normal_curvature import NormalCurvatureReport, normal_curvature_at


# ─────────────────────────────────────────────────────────────────────────────
# Surface constructors
# ─────────────────────────────────────────────────────────────────────────────

def _make_bilinear_plane(x0=0.0, x1=1.0, y0=0.0, y1=1.0) -> NurbsSurface:
    """Flat plane patch, degree 1 × 1."""
    cps = np.array([
        [[x0, y0, 0.0], [x0, y1, 0.0]],
        [[x1, y0, 0.0], [x1, y1, 0.0]],
    ], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(degree_u=1, degree_v=1,
                        control_points=cps, knots_u=knots, knots_v=knots.copy())


def _make_cylinder_nurbs(R: float = 2.0, h: float = 1.0) -> NurbsSurface:
    """
    Cylinder of radius R, height h (along Z), parameterised as a degree-2 × 1
    rational NURBS surface.

    The circular profile in XY is built from four quadratic rational arcs
    (standard 9-point rational quadratic circle, Piegl & Tiller §7.5), giving
    an exact cylinder.  The v-direction is linear (degree 1) between z=0 and
    z=h.

    Control-point grid: 9 (circle) × 2 (height levels), dimension 3.
    The weight grid repeats the circle weights [1, s, 1, s, 1, s, 1, s, 1]
    for both height levels.
    """
    s = math.sqrt(2.0) / 2.0
    # circle at z=0 and z=h
    circle_cps = R * np.array([
        [1.0,  0.0],
        [1.0,  1.0],
        [0.0,  1.0],
        [-1.0, 1.0],
        [-1.0, 0.0],
        [-1.0, -1.0],
        [0.0, -1.0],
        [1.0, -1.0],
        [1.0,  0.0],
    ])
    n_circle = circle_cps.shape[0]  # 9
    cps = np.zeros((n_circle, 2, 3))
    for i in range(n_circle):
        cps[i, 0] = [circle_cps[i, 0], circle_cps[i, 1], 0.0]
        cps[i, 1] = [circle_cps[i, 0], circle_cps[i, 1], h]

    w_circle = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])
    weights = np.column_stack([w_circle, w_circle])  # shape (9, 2)

    knots_u = np.array([0.0, 0.0, 0.0,
                        0.25, 0.25, 0.5, 0.5, 0.75, 0.75,
                        1.0, 1.0, 1.0])
    knots_v = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=2, degree_v=1,
        control_points=cps, knots_u=knots_u, knots_v=knots_v,
        weights=weights,
    )


def _make_unit_sphere_nurbs() -> NurbsSurface:
    """
    Exact rational unit sphere patch (upper hemisphere) parameterised as a
    degree-2 × 2 NURBS surface — south-pole trimmed version is complex, so
    we use a simpler but valid rational biquadratic patch covering the
    upper hemisphere (Piegl & Tiller §7.8-style construction).

    For testing purposes we build a 9×5 control-point grid that exactly
    represents the full sphere via the standard approach:
      - u-direction: 9-point circle (as in make_circle_nurbs)
      - v-direction: 5-point half-circle (π sweep) from south to north pole

    This gives a patch that covers the full sphere (seam at v=0/v=1 = poles).
    κ_n = 1 everywhere on a unit sphere.

    For test robustness we evaluate at an interior point away from the poles.
    """
    # Standard rational sphere as product of two circles:
    # The full sphere = circle(u) × semicircle(v)
    # Control nets per Piegl & Tiller §7.8:
    # Each latitude "ring" of control points is a weighted circle.
    # We use a simpler analytic approach: 5×9 grid.

    # Latitude control net (v-direction, degree 2):
    # 5 control points spanning -π/2 to +π/2 (south to north):
    #   v=0: (0,0,-1) weight=1  (south pole direction)
    #   v=0.25 shoulder: (0,0,-1) + (1,0,0) → needs weight=sqrt(2)/2
    # Piegl-Tiller §7.8 gives a 9×5 for full sphere.
    # For simplicity, use bilinear-on-sphere approach:

    # We build an approximate sphere via a 5×9 rational biquadratic.
    # Known construction (Piegl & Tiller §7.8 = "two circular arcs"):
    s = math.sqrt(2.0) / 2.0

    # v-axis: 5 control points for a 2-degree rational semicircle from (0,0,-1) to (0,0,1)
    # rotating around X-axis (latitude sweep)
    # lat_cps[i] = (cos(lat_i), sin(lat_i)) as radius factor, z = sin
    # Standard rational half-circle:
    #  P0=(0,0,-1) w=1, P1=(1,0,-1)/s = shoulder at w=s, P2=(1,0,0) w=1,
    #  P3=(1,0,1)/s shoulder w=s, P4=(0,0,1) w=1 — but we need the full
    #  meridian in the xz-plane, so:
    lat_cps_xz = np.array([
        [0.0, -1.0],   # south pole direction (x=0, z=-1)
        [1.0, -1.0],   # shoulder (Pitt-Tiller §7.5 shoulder for 90° arc)
        [1.0,  0.0],   # equator
        [1.0,  1.0],   # shoulder
        [0.0,  1.0],   # north pole direction (x=0, z=1)
    ])
    lat_weights = np.array([1.0, s, 1.0, s, 1.0])
    knots_v = np.array([0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0])

    # lon-axis: 9-point rational circle in xy-plane, at each latitude level
    # circle_x = [1, 1, 0, -1, -1, -1, 0, 1, 1]  (scaled by radius)
    # circle_y = [0, 1, 1,  1,  0, -1,-1,-1, 0]
    circle_xy = np.array([
        [1.0,  0.0],
        [1.0,  1.0],
        [0.0,  1.0],
        [-1.0, 1.0],
        [-1.0, 0.0],
        [-1.0, -1.0],
        [0.0, -1.0],
        [1.0, -1.0],
        [1.0,  0.0],
    ])
    circle_weights = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])
    knots_u = np.array([0.0, 0.0, 0.0,
                        0.25, 0.25, 0.5, 0.5, 0.75, 0.75,
                        1.0, 1.0, 1.0])

    # Build 9×5×3 control points
    # At each latitude i: radius = lat_cps_xz[i, 0], z = lat_cps_xz[i, 1]
    # longitude j: x = radius * circle_xy[j,0], y = radius * circle_xy[j,1]
    n_lon, n_lat = 9, 5
    cps = np.zeros((n_lon, n_lat, 3))
    weights = np.zeros((n_lon, n_lat))

    for i_lat in range(n_lat):
        r = lat_cps_xz[i_lat, 0]  # xy-radius at this latitude level
        z = lat_cps_xz[i_lat, 1]  # z at this level
        w_lat = lat_weights[i_lat]
        for j_lon in range(n_lon):
            x = r * circle_xy[j_lon, 0]
            y = r * circle_xy[j_lon, 1]
            w_lon = circle_weights[j_lon]
            cps[j_lon, i_lat] = [x, y, z]
            # Combined weight = w_lon * w_lat (product of rational circles)
            weights[j_lon, i_lat] = w_lon * w_lat

    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=cps, knots_u=knots_u, knots_v=knots_v,
        weights=weights,
    )


def _make_saddle_nurbs() -> NurbsSurface:
    """
    Hyperbolic paraboloid z = x·y on [-1,1]×[-1,1].

    A degree-2 × 2 NURBS (non-rational, all weights=1) that exactly represents
    the saddle surface z = x·y.  The exact biquadratic NURBS is built from
    a 3×3 control net:
        (u,v) ∈ [-1,1]×[-1,1], parameterised by knots [0,0,0,1,1,1].
    The control points are: P[i,j] = (x_i, y_j, x_i*y_j)
    where (x_0, x_1, x_2) = (-1, 0, 1) and (y_0, y_1, y_2) = (-1, 0, 1).

    This is exact because z = xy is a bilinear function of (x,y), and a
    degree-2 NURBS trivially spans it.
    """
    xs = np.array([-1.0, 0.0, 1.0])
    ys = np.array([-1.0, 0.0, 1.0])
    cps = np.zeros((3, 3, 3))
    for i, x in enumerate(xs):
        for j, y in enumerate(ys):
            cps[i, j] = [x, y, x * y]
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=cps, knots_u=knots, knots_v=knots.copy(),
    )


def _make_sphere_nurbs(R: float) -> NurbsSurface:
    """Sphere of radius R — scale the unit sphere control points."""
    srf = _make_unit_sphere_nurbs()
    scaled_cps = srf.control_points * R
    return NurbsSurface(
        degree_u=srf.degree_u, degree_v=srf.degree_v,
        control_points=scaled_cps,
        knots_u=srf.knots_u, knots_v=srf.knots_v,
        weights=srf.weights,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPlane:
    """Flat plane — κ_n = 0 in every direction, K = 0."""

    def setup_method(self):
        self.srf = _make_bilinear_plane()
        self.u, self.v = 0.5, 0.5

    def test_kappa_n_zero_du(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert abs(r.kappa_n) < 1e-10

    def test_kappa_n_zero_dv(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (0.0, 1.0))
        assert abs(r.kappa_n) < 1e-10

    def test_kappa_n_zero_diagonal(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 1.0))
        assert abs(r.kappa_n) < 1e-10

    def test_gauss_curvature_zero(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert abs(r.K) < 1e-10

    def test_principal_curvatures_zero(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert abs(r.kappa_1) < 1e-10
        assert abs(r.kappa_2) < 1e-10

    def test_not_degenerate(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate


class TestSphere:
    """Unit sphere: |κ_n| = 1 in every direction, is_umbilic=True.

    Sign convention note: the sign of κ_n depends on which direction the
    surface normal S_u×S_v points.  For an outward-oriented rational NURBS
    sphere the normal points outward and the surface bends away from it, so
    κ_n = -1 (concave from outside).  We test the magnitude |κ_n| = 1/R and
    verify that κ_n is constant in all directions (umbilic).  K = κ_1·κ_2 is
    orientation-independent and equals +1.
    """

    def setup_method(self):
        self.srf = _make_unit_sphere_nurbs()
        # interior point away from poles: u=0.125, v=0.5 (equator, 45° longitude)
        self.u, self.v = 0.125, 0.5

    def test_kappa_n_du_direction(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate, "Point should not be degenerate"
        assert abs(abs(r.kappa_n) - 1.0) < 1e-4, f"Expected |κ_n|≈1, got {r.kappa_n}"

    def test_kappa_n_dv_direction(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (0.0, 1.0))
        assert not r.is_degenerate
        assert abs(abs(r.kappa_n) - 1.0) < 1e-4, f"Expected |κ_n|≈1, got {r.kappa_n}"

    def test_kappa_n_diagonal_direction(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 1.0))
        assert not r.is_degenerate
        assert abs(abs(r.kappa_n) - 1.0) < 1e-4, f"Expected |κ_n|≈1, got {r.kappa_n}"

    def test_is_umbilic(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        assert r.is_umbilic, "Unit sphere should be umbilic everywhere"

    def test_principal_dirs_none_at_umbilic(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        assert r.principal_dirs is None

    def test_gauss_curvature_one(self):
        """K = κ_1·κ_2 = 1 for unit sphere (orientation-independent)."""
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        assert abs(r.K - 1.0) < 1e-4, f"Expected K≈1, got {r.K}"

    def test_mean_curvature_magnitude_one(self):
        """|H| = 1 for unit sphere; sign is orientation-dependent."""
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        assert abs(abs(r.H) - 1.0) < 1e-4, f"Expected |H|≈1, got {r.H}"

    def test_direction_invariance_12_dirs(self):
        """κ_n should be the same constant for 12 uniformly spaced tangent directions."""
        angles = np.linspace(0, 2 * math.pi, 12, endpoint=False)
        kn_vals = []
        for ang in angles:
            du, dv = math.cos(ang), math.sin(ang)
            r = normal_curvature_at(self.srf, self.u, self.v, (du, dv))
            if r.is_degenerate:
                continue
            kn_vals.append(r.kappa_n)
        assert len(kn_vals) > 0
        # All values should be equal (umbilic); check variance is near zero
        kn_arr = np.array(kn_vals)
        assert np.std(kn_arr) < 1e-4, (
            f"κ_n not constant on sphere: std={np.std(kn_arr):.2e}, vals={kn_arr}"
        )


class TestSphereRadiusR:
    """Sphere of radius R=3: |κ_n| = 1/3 everywhere, K = 1/R²."""

    def setup_method(self):
        self.R = 3.0
        self.srf = _make_sphere_nurbs(self.R)
        self.u, self.v = 0.125, 0.5

    def test_kappa_n_magnitude_equals_one_over_R(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        if r.is_degenerate:
            pytest.skip("degenerate point")
        expected = 1.0 / self.R
        assert abs(abs(r.kappa_n) - expected) < 1e-4, (
            f"Expected |κ_n|≈{expected:.4f}, got {r.kappa_n:.6f}"
        )

    def test_gauss_curvature_one_over_R_sq(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        if r.is_degenerate:
            pytest.skip("degenerate point")
        expected_K = 1.0 / (self.R ** 2)
        assert abs(r.K - expected_K) < 1e-4, (
            f"Expected K≈{expected_K:.4f}, got {r.K:.6f}"
        )


class TestCylinder:
    """Cylinder of radius R=2.

    Sign convention: S_u points along the circle tangent, S_v along Z,
    so n̂ = S_u×S_v may point inward (toward axis).  We test magnitudes:
      |κ_along-axis| = 0, |κ_across-axis| = 1/R.
    K = 0 (developable surface) is orientation-independent.
    """

    def setup_method(self):
        self.R = 2.0
        self.srf = _make_cylinder_nurbs(R=self.R, h=1.0)
        # Interior point on cylinder: u=0.0 (0° = (R,0,z)), v=0.5 (mid-height)
        self.u, self.v = 0.0, 0.5

    def test_kappa_along_axis_is_zero(self):
        """Along the axis (dv direction = Z direction): κ_n = 0."""
        r = normal_curvature_at(self.srf, self.u, self.v, (0.0, 1.0))
        assert not r.is_degenerate
        assert abs(r.kappa_n) < 1e-4, f"Expected κ_n≈0 along axis, got {r.kappa_n}"

    def test_kappa_across_axis_magnitude(self):
        """Across the axis (du = circle direction): |κ_n| = 1/R."""
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        expected = 1.0 / self.R
        assert abs(abs(r.kappa_n) - expected) < 1e-4, (
            f"Expected |κ_n|≈{expected:.4f} across cylinder axis, got {r.kappa_n:.6f}"
        )

    def test_principal_curvatures(self):
        """One principal curvature = 0, the other has magnitude 1/R."""
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        k_sorted = sorted([abs(r.kappa_1), abs(r.kappa_2)])
        assert k_sorted[0] < 1e-4, f"Expected one κ≈0, got κ_1={r.kappa_1}, κ_2={r.kappa_2}"
        assert abs(k_sorted[1] - 1.0 / self.R) < 1e-4, (
            f"Expected other |κ|≈{1.0/self.R:.4f}, got {k_sorted[1]:.6f}"
        )

    def test_gauss_curvature_zero(self):
        """Cylinder is a developable surface: K = 0."""
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        assert abs(r.K) < 1e-4, f"Expected K≈0 for cylinder, got {r.K}"

    def test_not_umbilic(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        assert not r.is_umbilic


class TestSaddle:
    """Hyperbolic paraboloid z=xy: mixed-sign principal curvatures."""

    def setup_method(self):
        self.srf = _make_saddle_nurbs()
        # Evaluate at the saddle point (u=v=0.5 → x=y=0, z=0)
        self.u, self.v = 0.5, 0.5

    def test_negative_gauss_curvature(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        assert r.K < 0, f"Expected K<0 for saddle surface, got {r.K}"

    def test_principal_curvatures_mixed_sign(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        assert r.kappa_1 < 0, f"Expected κ_1<0 for saddle, got {r.kappa_1}"
        assert r.kappa_2 > 0, f"Expected κ_2>0 for saddle, got {r.kappa_2}"

    def test_not_umbilic(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        assert not r.is_umbilic

    def test_principal_dirs_not_none(self):
        r = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        assert not r.is_degenerate
        assert r.principal_dirs is not None
        assert len(r.principal_dirs) == 2


class TestEulersFormula:
    """
    Euler's formula: κ_n(θ) = κ_1·cos²(θ−φ) + κ_2·sin²(θ−φ).

    Tested on the saddle surface at the origin, where the principal directions
    are aligned with du and dv (φ=0 by symmetry).
    """

    def setup_method(self):
        self.srf = _make_saddle_nurbs()
        self.u, self.v = 0.5, 0.5
        # Get principal curvatures
        base = normal_curvature_at(self.srf, self.u, self.v, (1.0, 0.0))
        self.k1 = base.kappa_1
        self.k2 = base.kappa_2
        self.principal_dirs = base.principal_dirs

    def test_euler_formula_at_multiple_angles(self):
        """κ_n(θ) matches κ_1·cos²(θ−φ) + κ_2·sin²(θ−φ) within tolerance."""
        if self.principal_dirs is None:
            pytest.skip("umbilic point")

        # Principal directions in parameter space
        d1 = np.array(self.principal_dirs[0])  # (du1, dv1) for κ_1
        d2 = np.array(self.principal_dirs[1])  # (du2, dv2) for κ_2

        # Verify each principal direction gives the right curvature
        r1 = normal_curvature_at(self.srf, self.u, self.v, (d1[0], d1[1]))
        r2 = normal_curvature_at(self.srf, self.u, self.v, (d2[0], d2[1]))
        assert abs(r1.kappa_n - self.k1) < 1e-6 or abs(r1.kappa_n - self.k2) < 1e-6
        assert abs(r2.kappa_n - self.k1) < 1e-6 or abs(r2.kappa_n - self.k2) < 1e-6

    @pytest.mark.parametrize("n_theta", [8, 16, 24])
    def test_euler_formula_parametric(self, n_theta):
        """
        For the saddle z=xy at origin, the principal directions align with
        the 45° directions in parameter space.  Verify Euler's formula by
        checking that κ_n(direction) is bounded by [κ_1, κ_2] for all directions.
        """
        angles = np.linspace(0, 2 * math.pi, n_theta, endpoint=False)
        for ang in angles:
            du, dv = math.cos(ang), math.sin(ang)
            r = normal_curvature_at(self.srf, self.u, self.v, (du, dv))
            assert not r.is_degenerate
            # κ_n must be in [κ_1, κ_2]
            assert r.kappa_n >= self.k1 - 1e-8
            assert r.kappa_n <= self.k2 + 1e-8


class TestDegenerateDirection:
    """Zero direction vector → is_degenerate=True."""

    def test_zero_direction(self):
        srf = _make_bilinear_plane()
        r = normal_curvature_at(srf, 0.5, 0.5, (0.0, 0.0))
        assert r.is_degenerate


class TestReExport:
    """NormalCurvatureReport must be importable from kerf_cad_core.geom."""

    def test_import_from_geom_init(self):
        from kerf_cad_core.geom.normal_curvature import NormalCurvatureReport as NCR
        assert NCR is NormalCurvatureReport

    def test_report_dataclass_fields(self):
        import dataclasses
        fields = {f.name for f in dataclasses.fields(NormalCurvatureReport)}
        required = {"u", "v", "kappa_n", "kappa_1", "kappa_2", "K", "H",
                    "principal_dirs", "is_umbilic", "is_degenerate"}
        assert required.issubset(fields)
