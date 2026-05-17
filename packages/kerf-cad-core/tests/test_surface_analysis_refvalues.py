"""
test_surface_analysis_refvalues.py
===================================
Hermetic reference-value tests for the single-point analytic curvature suite
in ``kerf_cad_core.geom.surface_analysis``.

All surfaces are built as **exact** rational NURBS from first principles so
that the analytic ground-truth values are known to floating-point precision:

Sphere radius R
    K = 1/R²  everywhere,  H = 1/R (abs),  k1 = k2 = 1/R (abs).
    Built by revolving a rational quadratic semicircle arc (make_arc_nurbs)
    around the z-axis using the 9-column rational circle construction.
    Reference: Piegl & Tiller §8.1.

Cylinder radius R, axis z
    K = 0  everywhere,  H = ±1/(2R),  {|k1|,|k2|} = {0, 1/R}.
    Built as a 9-CP rational circle × degree-1 linear extrusion.
    Reference: do Carmo §3.3.

Torus, major radius R, minor radius r (R > r)
    K(outer equator) =  1/(r(R+r)),   K(inner equator) = −1/(r(R−r)).
    Built by revolving a rational circle (meridian) around the z-axis.
    Reference: do Carmo §3.3; Goldman CAGD 2005.

Plane z = 0
    K = 0, H = 0, k1 = k2 = 0 exactly.

Draft angle
    Vertical wall (tangent to z) vs z-pull: 0°.
    Surface whose normal is at 60° from z: 30° draft vs z-pull.
    Reference: definition: draft = arcsin(n̂ · pull̂).

Deviation
    surf vs itself  → (0, 0) within 1e-12.
    Two spheres of radii R and R + d → max deviation = d within 1e-6.

Determinism
    Same (surf, u, v) → identical results across 5 independent calls.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface, make_arc_nurbs
from kerf_cad_core.geom.surface_analysis import (
    deviation,
    draft_angle,
    gaussian_curvature,
    mean_curvature,
    principal_curvatures,
    zebra_stripe,
)


# ---------------------------------------------------------------------------
# Analytic NURBS surface primitives
# ---------------------------------------------------------------------------

def _make_nurbs_sphere(R: float = 1.0) -> NurbsSurface:
    """Exact rational NURBS sphere of radius R via semicircle revolution.

    Meridian: rational quadratic arc from south pole (0,0,−R) to north pole
    (0,0,+R) in the xz-plane, built with ``make_arc_nurbs``.  Each row of
    the 5×9 control-point grid is the meridian CP scaled by the circle
    construction; the weight tensor is the outer product of the two 1-D
    rational weight vectors.

    All sampled points satisfy ||p|| = R to machine precision.

    Reference: Piegl & Tiller §8.1.
    """
    arc = make_arc_nurbs(
        center=np.zeros(3),
        radius=R,
        start_angle=-math.pi / 2,
        end_angle=math.pi / 2,
        x_axis=np.array([1.0, 0.0, 0.0]),
        y_axis=np.array([0.0, 0.0, 1.0]),
    )
    s = math.sqrt(2.0) / 2.0
    # Rational 9-point full circle in the xy-plane
    circle_offsets = np.array([
        [1., 0.], [1., 1.], [0., 1.], [-1., 1.], [-1., 0.],
        [-1., -1.], [0., -1.], [1., -1.], [1., 0.],
    ])
    circle_weights = np.array([1., s, 1., s, 1., s, 1., s, 1.])
    circle_knots = np.array([0., 0., 0., 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1., 1., 1.])

    nrow, ncol = arc.num_control_points, 9
    cp = np.zeros((nrow, ncol, 3))
    wts = np.zeros((nrow, ncol))
    for i in range(nrow):
        xi = arc.control_points[i, 0]   # radial distance from z-axis
        zi = arc.control_points[i, 2]   # height
        wi = float(arc.weights[i])
        for j in range(ncol):
            cp[i, j] = [circle_offsets[j, 0] * xi,
                        circle_offsets[j, 1] * xi,
                        zi]
            wts[i, j] = wi * circle_weights[j]

    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=cp,
        knots_u=arc.knots.copy(),
        knots_v=circle_knots.copy(),
        weights=wts,
    )


def _make_nurbs_cylinder(R: float = 1.0, height: float = 2.0) -> NurbsSurface:
    """Exact rational NURBS cylinder of radius R, height along z.

    u-direction: rational quadratic 9-point full circle.
    v-direction: degree-1 linear in z (2 control points).
    """
    s = math.sqrt(2.0) / 2.0
    circle_offsets = np.array([
        [1., 0.], [1., 1.], [0., 1.], [-1., 1.], [-1., 0.],
        [-1., -1.], [0., -1.], [1., -1.], [1., 0.],
    ])
    circle_weights = np.array([1., s, 1., s, 1., s, 1., s, 1.])
    knots_u = np.array([0., 0., 0., 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1., 1., 1.])
    knots_v = np.array([0., 0., 1., 1.])

    cp = np.zeros((9, 2, 3))
    wts = np.zeros((9, 2))
    for i in range(9):
        for j, z in enumerate([0.0, height]):
            cp[i, j] = [circle_offsets[i, 0] * R,
                        circle_offsets[i, 1] * R,
                        z]
            wts[i, j] = circle_weights[i]

    return NurbsSurface(
        degree_u=2, degree_v=1,
        control_points=cp,
        knots_u=knots_u, knots_v=knots_v,
        weights=wts,
    )


def _make_nurbs_torus(R_major: float = 3.0, r_minor: float = 1.0) -> NurbsSurface:
    """Exact rational NURBS torus via 9×9 rational control-point grid.

    Constructed by revolving a rational full circle (meridian, in the xz-plane
    centred at (R_major, 0, 0) with radius r_minor) around the z-axis using
    the same 9-point circle revolution.

    Outer equator parameter: u = 0 (or u = 1).
    Inner equator parameter: u = 0.5.

    Analytic Gaussian curvature (do Carmo §3.3, Goldman CAGD 2005):
        K(phi) = cos(phi) / (r_minor * (R_major + r_minor * cos(phi)))
        K_outer_eq = K(0)   = 1 / (r_minor * (R_major + r_minor))
        K_inner_eq = K(pi)  = −1 / (r_minor * (R_major − r_minor))
    """
    s = math.sqrt(2.0) / 2.0
    meridian_offsets = np.array([
        [1., 0.], [1., 1.], [0., 1.], [-1., 1.], [-1., 0.],
        [-1., -1.], [0., -1.], [1., -1.], [1., 0.],
    ])
    meridian_weights = np.array([1., s, 1., s, 1., s, 1., s, 1.])
    revolution_offsets = np.array([
        [1., 0.], [1., 1.], [0., 1.], [-1., 1.], [-1., 0.],
        [-1., -1.], [0., -1.], [1., -1.], [1., 0.],
    ])
    revolution_weights = np.array([1., s, 1., s, 1., s, 1., s, 1.])
    circle_knots = np.array([0., 0., 0., 0.25, 0.25, 0.5, 0.5, 0.75, 0.75, 1., 1., 1.])

    cp = np.zeros((9, 9, 3))
    wts = np.zeros((9, 9))
    for i in range(9):
        xm = R_major + r_minor * meridian_offsets[i, 0]
        zm = r_minor * meridian_offsets[i, 1]
        wi = meridian_weights[i]
        for j in range(9):
            cp[i, j] = [revolution_offsets[j, 0] * xm,
                        revolution_offsets[j, 1] * xm,
                        zm]
            wts[i, j] = wi * revolution_weights[j]

    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=cp,
        knots_u=circle_knots.copy(),
        knots_v=circle_knots.copy(),
        weights=wts,
    )


def _make_nurbs_plane(size: float = 1.0) -> NurbsSurface:
    """Flat plane z = 0 on [0, size] × [0, size] as a bilinear NURBS patch."""
    cp = np.array([
        [[0., 0., 0.], [0., size, 0.]],
        [[size, 0., 0.], [size, size, 0.]],
    ])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=np.array([0., 0., 1., 1.]),
        knots_v=np.array([0., 0., 1., 1.]),
    )


def _make_slope_surface_30deg_draft() -> NurbsSurface:
    """Flat surface whose normal is at 60° from z (yields 30° draft vs z-pull).

    Surface parametrised as z = x * sqrt(3).  First partials:
        dp/du = [1, 0, sqrt(3)],  dp/dv = [0, 1, 0].
    Normal (unnormalized): cross(dp/du, dp/dv) = [−sqrt(3), 0, 1].
    Normalised n_z component = 1 / sqrt(4) = 0.5  →  arcsin(0.5) = 30°.
    """
    slope = math.sqrt(3.0)
    cp = np.array([
        [[0., 0., 0.], [0., 1., 0.]],
        [[1., 0., slope], [1., 1., slope]],
    ])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=np.array([0., 0., 1., 1.]),
        knots_v=np.array([0., 0., 1., 1.]),
    )


def _make_vertical_wall() -> NurbsSurface:
    """Vertical wall in the xz-plane; normal is [0, 1, 0] (perpendicular to z)."""
    cp = np.array([
        [[0., 0., 0.], [0., 0., 1.]],
        [[1., 0., 0.], [1., 0., 1.]],
    ])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=np.array([0., 0., 1., 1.]),
        knots_v=np.array([0., 0., 1., 1.]),
    )


# ---------------------------------------------------------------------------
# Helper: safe interior UV samples (away from clamped-knot boundaries)
# ---------------------------------------------------------------------------

def _interior_uv_samples(surf: NurbsSurface, n: int = 4) -> list:
    u0 = float(surf.knots_u[0])
    u1 = float(surf.knots_u[-1])
    v0 = float(surf.knots_v[0])
    v1 = float(surf.knots_v[-1])
    # Avoid exact endpoints which may be polar/degenerate
    eps_u = (u1 - u0) * 0.05
    eps_v = (v1 - v0) * 0.05
    us = np.linspace(u0 + eps_u, u1 - eps_u, n)
    vs = np.linspace(v0 + eps_v, v1 - eps_v, n)
    return [(float(u), float(v)) for u in us for v in vs]


# ===========================================================================
# 1. Sphere — gaussian_curvature
# ===========================================================================

class TestSphereGaussianCurvature:
    """K = 1/R² everywhere on a sphere of radius R.

    Reference: do Carmo §3.3 eq. (6); Piegl & Tiller §8.1.
    """

    @pytest.mark.parametrize("R", [1.0, 2.0, 0.5, 5.0])
    def test_K_equals_1_over_R2_at_interior_points(self, R):
        surf = _make_nurbs_sphere(R)
        K_expected = 1.0 / (R * R)
        for u, v in _interior_uv_samples(surf, n=4):
            K = gaussian_curvature(surf, u, v)
            assert abs(K - K_expected) < 1e-6, (
                f"R={R} u={u:.3f} v={v:.3f}: K={K:.8f} expected={K_expected:.8f} "
                f"err={abs(K - K_expected):.2e}"
            )

    def test_K_positive_on_sphere(self):
        """Sphere is a convex closed surface: K > 0 everywhere."""
        surf = _make_nurbs_sphere(R=1.5)
        for u, v in _interior_uv_samples(surf, n=5):
            K = gaussian_curvature(surf, u, v)
            assert K > 0.0, f"K={K} must be positive on sphere"


# ===========================================================================
# 2. Sphere — mean_curvature
# ===========================================================================

class TestSphereMeanCurvature:
    """H = ±1/R on a sphere of radius R (sign depends on normal orientation)."""

    @pytest.mark.parametrize("R", [1.0, 2.0, 3.0])
    def test_abs_H_equals_1_over_R(self, R):
        surf = _make_nurbs_sphere(R)
        H_expected = 1.0 / R
        for u, v in _interior_uv_samples(surf, n=4):
            H = mean_curvature(surf, u, v)
            assert abs(abs(H) - H_expected) < 1e-6, (
                f"R={R} u={u:.3f} v={v:.3f}: |H|={abs(H):.8f} "
                f"expected={H_expected:.8f} err={abs(abs(H) - H_expected):.2e}"
            )

    def test_H_constant_on_sphere(self):
        """Mean curvature is uniform on a sphere."""
        surf = _make_nurbs_sphere(R=2.0)
        H_vals = [mean_curvature(surf, u, v)
                  for u, v in _interior_uv_samples(surf, n=5)]
        assert max(H_vals) - min(H_vals) < 1e-6, (
            f"H varies on sphere: max={max(H_vals):.8f} min={min(H_vals):.8f}"
        )


# ===========================================================================
# 3. Sphere — principal_curvatures
# ===========================================================================

class TestSpherePrincipalCurvatures:
    """k1 = k2 = ±1/R on an umbilic sphere."""

    @pytest.mark.parametrize("R", [1.0, 2.0, 0.5])
    def test_k1_equals_k2_equals_1_over_R(self, R):
        surf = _make_nurbs_sphere(R)
        kappa_expected = 1.0 / R
        for u, v in _interior_uv_samples(surf, n=4):
            k1, k2 = principal_curvatures(surf, u, v)
            assert abs(abs(k1) - kappa_expected) < 1e-6, (
                f"R={R}: |k1|={abs(k1):.8f} expected={kappa_expected:.8f}"
            )
            assert abs(abs(k2) - kappa_expected) < 1e-6, (
                f"R={R}: |k2|={abs(k2):.8f} expected={kappa_expected:.8f}"
            )

    def test_k1_plus_k2_equals_2H(self):
        """Fundamental relation: k1 + k2 = 2H."""
        surf = _make_nurbs_sphere(R=1.0)
        for u, v in _interior_uv_samples(surf, n=3):
            k1, k2 = principal_curvatures(surf, u, v)
            H = mean_curvature(surf, u, v)
            assert abs(k1 + k2 - 2.0 * H) < 1e-10, (
                f"k1+k2={k1+k2:.10f} 2H={2*H:.10f}"
            )

    def test_k1_times_k2_equals_K(self):
        """Fundamental relation: k1 * k2 = K."""
        surf = _make_nurbs_sphere(R=2.0)
        for u, v in _interior_uv_samples(surf, n=3):
            k1, k2 = principal_curvatures(surf, u, v)
            K = gaussian_curvature(surf, u, v)
            assert abs(k1 * k2 - K) < 1e-10, (
                f"k1*k2={k1*k2:.10f} K={K:.10f}"
            )


# ===========================================================================
# 4. Cylinder — gaussian_curvature
# ===========================================================================

class TestCylinderGaussianCurvature:
    """K = 0 everywhere on a cylinder (one principal curvature is zero).

    Reference: do Carmo §3.3, ruling direction has zero normal curvature.
    """

    @pytest.mark.parametrize("R", [1.0, 1.5, 3.0])
    def test_K_exactly_zero(self, R):
        surf = _make_nurbs_cylinder(R)
        for u, v in _interior_uv_samples(surf, n=4):
            K = gaussian_curvature(surf, u, v)
            assert abs(K) < 1e-9, (
                f"R={R} u={u:.3f} v={v:.3f}: K={K:.2e} expected 0"
            )


# ===========================================================================
# 5. Cylinder — mean_curvature and principal_curvatures
# ===========================================================================

class TestCylinderCurvature:
    """H = ±1/(2R);  {|k1|, |k2|} = {0, 1/R}."""

    @pytest.mark.parametrize("R", [1.0, 2.0])
    def test_abs_H_equals_1_over_2R(self, R):
        surf = _make_nurbs_cylinder(R)
        H_expected = 1.0 / (2.0 * R)
        for u, v in _interior_uv_samples(surf, n=4):
            H = mean_curvature(surf, u, v)
            assert abs(abs(H) - H_expected) < 1e-9, (
                f"R={R}: |H|={abs(H):.8f} expected={H_expected:.8f}"
            )

    @pytest.mark.parametrize("R", [1.0, 1.5])
    def test_principal_curvatures_are_0_and_1_over_R(self, R):
        surf = _make_nurbs_cylinder(R)
        for u, v in _interior_uv_samples(surf, n=4):
            k1, k2 = principal_curvatures(surf, u, v)
            sorted_abs = sorted([abs(k1), abs(k2)])
            assert sorted_abs[0] < 1e-9, (
                f"R={R}: smaller |k|={sorted_abs[0]:.2e} should be 0"
            )
            assert abs(sorted_abs[1] - 1.0 / R) < 1e-9, (
                f"R={R}: larger |k|={sorted_abs[1]:.8f} expected={1/R:.8f}"
            )


# ===========================================================================
# 6. Torus — gaussian_curvature at analytic extrema
# ===========================================================================

class TestTorusGaussianCurvature:
    """Torus with R_major=3, r_minor=1: analytic K at inner and outer equators.

    K_outer = 1/(r*(R+r)) = 1/4.
    K_inner = −1/(r*(R−r)) = −1/2.

    These values are the maximum and minimum K on this torus.

    Reference: do Carmo §3.3; Goldman, CAGD 22(7) 2005.
    """
    R, r = 3.0, 1.0

    def test_K_outer_equator(self):
        surf = _make_nurbs_torus(self.R, self.r)
        K_expected = 1.0 / (self.r * (self.R + self.r))
        # Outer equator: u = 0.0 (first CP of meridian is outer point)
        for v in [0.1, 0.3, 0.5, 0.7]:
            K = gaussian_curvature(surf, 0.0, v)
            assert abs(K - K_expected) < 1e-6, (
                f"Outer equator v={v}: K={K:.8f} expected={K_expected:.8f}"
            )

    def test_K_inner_equator(self):
        surf = _make_nurbs_torus(self.R, self.r)
        K_expected = -1.0 / (self.r * (self.R - self.r))
        # Inner equator: u = 0.5 (half of the meridian period)
        for v in [0.1, 0.3, 0.5, 0.7]:
            K = gaussian_curvature(surf, 0.5, v)
            assert abs(K - K_expected) < 1e-6, (
                f"Inner equator v={v}: K={K:.8f} expected={K_expected:.8f}"
            )

    def test_K_positive_on_outer_half(self):
        """K > 0 on the outer half (|phi| < pi/2)."""
        surf = _make_nurbs_torus(self.R, self.r)
        # u ∈ [0, 0.25): outer quarter, K should be positive
        for u in [0.05, 0.1, 0.15, 0.2]:
            K = gaussian_curvature(surf, u, 0.3)
            assert K > 0, f"u={u}: K={K} should be positive on outer quarter"

    def test_K_negative_on_inner_half(self):
        """K < 0 on the inner half (pi/2 < |phi| < pi)."""
        surf = _make_nurbs_torus(self.R, self.r)
        # u ∈ (0.25, 0.5]: inner quarter, K should be negative
        for u in [0.3, 0.35, 0.4, 0.45]:
            K = gaussian_curvature(surf, u, 0.3)
            assert K < 0, f"u={u}: K={K} should be negative on inner quarter"

    def test_K_at_top_is_zero(self):
        """At u=0.25 (top of torus, phi=pi/2), cos(phi)=0 → K=0."""
        surf = _make_nurbs_torus(self.R, self.r)
        K = gaussian_curvature(surf, 0.25, 0.3)
        assert abs(K) < 1e-6, f"Top torus K={K:.2e} should be 0"


# ===========================================================================
# 7. Plane — curvatures exactly zero
# ===========================================================================

class TestPlaneZeroCurvature:
    """K = H = k1 = k2 = 0 exactly on a flat plane."""

    def test_K_zero_on_plane(self):
        surf = _make_nurbs_plane()
        for u, v in _interior_uv_samples(surf, n=5):
            K = gaussian_curvature(surf, u, v)
            assert K == 0.0, f"Plane K={K} must be exactly 0"

    def test_H_zero_on_plane(self):
        surf = _make_nurbs_plane()
        for u, v in _interior_uv_samples(surf, n=5):
            H = mean_curvature(surf, u, v)
            assert H == 0.0, f"Plane H={H} must be exactly 0"

    def test_principal_curvatures_zero_on_plane(self):
        surf = _make_nurbs_plane()
        for u, v in _interior_uv_samples(surf, n=5):
            k1, k2 = principal_curvatures(surf, u, v)
            assert k1 == 0.0, f"Plane k1={k1} must be exactly 0"
            assert k2 == 0.0, f"Plane k2={k2} must be exactly 0"


# ===========================================================================
# 8. Draft angle
# ===========================================================================

class TestDraftAngle:
    """draft_angle(surf, u, v, pull_dir) = arcsin(n · pull_hat) in degrees."""

    def test_vertical_wall_zero_draft_vs_z(self):
        """Wall normal = [0,1,0] ⊥ z: draft vs z-pull = 0°."""
        surf = _make_vertical_wall()
        for u, v in _interior_uv_samples(surf, n=4):
            angle = draft_angle(surf, u, v, [0.0, 0.0, 1.0])
            assert abs(angle) < 1e-9, (
                f"Vertical wall draft={angle:.2e}° expected 0°"
            )

    def test_30deg_draft_surface(self):
        """Surface with slope sqrt(3) gives exactly 30° draft vs z-pull."""
        surf = _make_slope_surface_30deg_draft()
        for u, v in _interior_uv_samples(surf, n=4):
            angle = draft_angle(surf, u, v, [0.0, 0.0, 1.0])
            assert abs(angle - 30.0) < 1e-9, (
                f"30° slope: draft={angle:.8f}° expected 30°"
            )

    def test_plane_90deg_draft_vs_z(self):
        """Plane z=0 has normal [0,0,1]; draft vs z-pull = 90°."""
        surf = _make_nurbs_plane()
        for u, v in _interior_uv_samples(surf, n=4):
            angle = draft_angle(surf, u, v, [0.0, 0.0, 1.0])
            assert abs(angle - 90.0) < 1e-9, (
                f"Plane draft={angle:.8f}° expected 90°"
            )

    def test_draft_returns_nan_for_zero_pull(self):
        """Zero pull_dir returns nan."""
        surf = _make_nurbs_plane()
        angle = draft_angle(surf, 0.5, 0.5, [0.0, 0.0, 0.0])
        assert math.isnan(angle)

    def test_draft_negated_pull_gives_negative_angle(self):
        """Plane with reversed pull_dir: angle = −90°."""
        surf = _make_nurbs_plane()
        angle = draft_angle(surf, 0.5, 0.5, [0.0, 0.0, -1.0])
        assert abs(angle + 90.0) < 1e-9, f"Expected -90°, got {angle}"


# ===========================================================================
# 9. Deviation
# ===========================================================================

class TestDeviation:
    """deviation(surf_a, surf_b, samples) → (max_dev, mean_dev)."""

    def test_same_surface_zero_deviation_plane(self):
        """Plane vs itself: deviation = 0 exactly."""
        surf = _make_nurbs_plane()
        max_dev, mean_dev = deviation(surf, surf, samples=8)
        assert max_dev < 1e-12, f"Same-surface max_dev={max_dev:.2e}"
        assert mean_dev < 1e-12, f"Same-surface mean_dev={mean_dev:.2e}"

    def test_same_surface_zero_deviation_sphere(self):
        """Sphere vs itself: deviation = 0 exactly."""
        surf = _make_nurbs_sphere(R=1.0)
        max_dev, mean_dev = deviation(surf, surf, samples=8)
        assert max_dev < 1e-12, f"Sphere self max_dev={max_dev:.2e}"

    def test_offset_spheres_deviation_equals_d(self):
        """Two spheres of radii R and R+d: max deviation = d within 1e-6."""
        R, d = 1.0, 0.1
        s_a = _make_nurbs_sphere(R)
        s_b = _make_nurbs_sphere(R + d)
        max_dev, _ = deviation(s_a, s_b, samples=8)
        assert abs(max_dev - d) < 1e-6, (
            f"Offset sphere max_dev={max_dev:.8f} expected={d}"
        )

    def test_offset_spheres_mean_deviation_equals_d(self):
        """Mean deviation of two concentric spheres differing by d = d."""
        R, d = 2.0, 0.2
        s_a = _make_nurbs_sphere(R)
        s_b = _make_nurbs_sphere(R + d)
        _, mean_dev = deviation(s_a, s_b, samples=8)
        assert abs(mean_dev - d) < 1e-6, (
            f"Offset sphere mean_dev={mean_dev:.8f} expected={d}"
        )


# ===========================================================================
# 10. Zebra stripe
# ===========================================================================

class TestZebraStripe:
    """zebra_stripe returns analytic stripe value in [0, 1]."""

    def test_stripe_value_in_range(self):
        """stripe value ∈ [0, 1] at every interior point."""
        surf = _make_nurbs_sphere(R=1.0)
        for u, v in _interior_uv_samples(surf, n=5):
            val = zebra_stripe(surf, u, v, n_stripes=8)
            assert 0.0 <= val <= 1.0, f"stripe={val} out of [0,1]"

    def test_plane_normal_parallel_to_view_gives_1(self):
        """Plane z=0 has n=[0,0,1]; view=[0,0,1]: n·view=1,
        cos(n_stripes*pi*1) = cos(k*pi) = ±1 → stripe = 0 or 1."""
        surf = _make_nurbs_plane()
        val = zebra_stripe(surf, 0.5, 0.5, n_stripes=2, view_dir=[0., 0., 1.])
        # n·view=1, cos(2*pi*1)=cos(2pi)=1, stripe=0.5+0.5=1.0
        assert abs(val - 1.0) < 1e-12, f"Expected 1.0, got {val}"

    def test_default_view_dir_is_z(self):
        """Calling without view_dir defaults to z=[0,0,1]."""
        surf = _make_nurbs_plane()
        val_default = zebra_stripe(surf, 0.5, 0.5, n_stripes=2)
        val_z = zebra_stripe(surf, 0.5, 0.5, n_stripes=2, view_dir=[0., 0., 1.])
        assert val_default == val_z

    def test_stripe_returns_nan_at_degenerate_point(self):
        """A surface with zero cross-product → nan."""
        # Create a degenerate surface (all CPs the same)
        cp = np.zeros((2, 2, 3))
        surf = NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
            knots_u=np.array([0., 0., 1., 1.]),
            knots_v=np.array([0., 0., 1., 1.]))
        val = zebra_stripe(surf, 0.5, 0.5, n_stripes=8)
        assert math.isnan(val)


# ===========================================================================
# 11. Determinism
# ===========================================================================

class TestDeterminism:
    """Same surf + same (u, v) → identical results across multiple calls."""

    def test_gaussian_curvature_deterministic(self):
        surf = _make_nurbs_sphere(R=1.0)
        vals = [gaussian_curvature(surf, 0.3, 0.4) for _ in range(5)]
        assert all(v == vals[0] for v in vals), f"Non-deterministic: {vals}"

    def test_mean_curvature_deterministic(self):
        surf = _make_nurbs_cylinder(R=2.0)
        vals = [mean_curvature(surf, 0.2, 0.6) for _ in range(5)]
        assert all(v == vals[0] for v in vals), f"Non-deterministic: {vals}"

    def test_principal_curvatures_deterministic(self):
        surf = _make_nurbs_torus(R_major=3.0, r_minor=1.0)
        vals = [principal_curvatures(surf, 0.1, 0.2) for _ in range(5)]
        k1s = [v[0] for v in vals]
        k2s = [v[1] for v in vals]
        assert all(k == k1s[0] for k in k1s), f"k1 non-deterministic"
        assert all(k == k2s[0] for k in k2s), f"k2 non-deterministic"

    def test_draft_angle_deterministic(self):
        surf = _make_slope_surface_30deg_draft()
        vals = [draft_angle(surf, 0.5, 0.5, [0., 0., 1.]) for _ in range(5)]
        assert all(v == vals[0] for v in vals), f"Non-deterministic: {vals}"
