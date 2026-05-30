"""
Tests for kerf_cad_core.geom.subd_limit_integrals
==================================================

SUBD-LIMIT-INTEGRAL-METRIC: exact-as-feasible integrals over a
Catmull-Clark SubD limit surface.

Oracle references
-----------------
1. Flat unit-quad (single 1×1 quad, z=0 plane):
   - area > 0, area < 1.5  (CC limit shrinks the surface slightly)
   - ∫H dA ≈ 0   (H=0 everywhere on a flat surface)
   - ∫K dA ≈ 0   (K=0 everywhere on a flat surface)

2. Sphere from CC cube (8 vertices at ±1, 6 quad faces):
   After CC subdivision the limit surface converges to a sphere.
   χ = V − E + F = 8 − 12 + 6 = 2  → ∫K dA = 4π ≈ 12.566 (Gauss-Bonnet,
   INDEPENDENT of radius/subdivision level).

3. Torus cage (topology genus-1, χ=0):
   - ∫K dA ≈ 0  (Gauss-Bonnet for χ=0)

4. Ribbon / ruled-surface cage:
   - ∫H dA is finite and non-zero (not a minimal surface)
   - area > 0
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.subd_limit_integrals import (
    SubDIntegralReport,
    compute_subd_integrals,
    integrate_area,
    integrate_gaussian_curvature,
    integrate_mean_curvature,
)


# ---------------------------------------------------------------------------
# Cage factories
# ---------------------------------------------------------------------------

def _flat_unit_quad() -> SubDMesh:
    """Single flat 1×1 quad in the z=0 plane."""
    verts = [[0., 0., 0.], [1., 0., 0.], [1., 1., 0.], [0., 1., 0.]]
    faces = [[0, 1, 2, 3]]
    return SubDMesh(vertices=verts, faces=faces)


def _cc_cube_unit() -> SubDMesh:
    """Unit CC cube cage: 8 vertices at ±1, 6 quad faces.

    χ = 8 − 12 + 6 = 2  → Gauss-Bonnet: ∫K dA = 4π.
    """
    verts = [
        [-1., -1., -1.], [ 1., -1., -1.], [ 1.,  1., -1.], [-1.,  1., -1.],
        [-1., -1.,  1.], [ 1., -1.,  1.], [ 1.,  1.,  1.], [-1.,  1.,  1.],
    ]
    faces = [
        [0, 1, 2, 3], [4, 5, 6, 7], [0, 1, 5, 4],
        [2, 3, 7, 6], [0, 3, 7, 4], [1, 2, 6, 5],
    ]
    return SubDMesh(vertices=verts, faces=faces)


def _torus_cage(R: float = 1.0, r: float = 0.3, nu: int = 8, nv: int = 6) -> SubDMesh:
    """Quad torus control cage.  χ = 0  → ∫K dA = 0."""
    verts = []
    for i in range(nu):
        theta = 2.0 * math.pi * i / nu
        for j in range(nv):
            phi = 2.0 * math.pi * j / nv
            x = (R + r * math.cos(phi)) * math.cos(theta)
            y = (R + r * math.cos(phi)) * math.sin(theta)
            z = r * math.sin(phi)
            verts.append([x, y, z])
    faces = []
    for i in range(nu):
        for j in range(nv):
            v00 = i * nv + j
            v10 = ((i + 1) % nu) * nv + j
            v11 = ((i + 1) % nu) * nv + (j + 1) % nv
            v01 = i * nv + (j + 1) % nv
            faces.append([v00, v10, v11, v01])
    return SubDMesh(vertices=verts, faces=faces)


def _ribbon_cage() -> SubDMesh:
    """Simple 2×1 ribbon (two quads) — open surface, H ≠ 0 generally."""
    verts = [
        [0., 0., 0.], [1., 0., 0.], [2., 0., 0.],
        [0., 1., 0.2], [1., 1., -0.2], [2., 1., 0.2],
    ]
    faces = [[0, 1, 4, 3], [1, 2, 5, 4]]
    return SubDMesh(vertices=verts, faces=faces)


# ---------------------------------------------------------------------------
# Tests: flat unit quad
# ---------------------------------------------------------------------------

class TestFlatUnitQuad:
    def test_area_positive(self):
        area = integrate_area(_flat_unit_quad(), subd_levels=2)
        assert area > 0.0, f"area must be positive, got {area}"

    def test_area_reasonable_magnitude(self):
        """Limit area of 1×1 quad is ≤1 (CC shrinks open boundary)."""
        area = integrate_area(_flat_unit_quad(), subd_levels=2)
        assert area < 1.5, f"area too large for flat quad: {area}"

    def test_mean_curvature_near_zero(self):
        """∫H dA ≈ 0 for a flat plane."""
        H_int = integrate_mean_curvature(_flat_unit_quad(), subd_levels=2)
        assert abs(H_int) < 1.0, f"∫H dA should be ~0 for flat plane, got {H_int}"

    def test_gaussian_curvature_near_zero(self):
        """∫K dA ≈ 0 for a flat plane."""
        K_int = integrate_gaussian_curvature(_flat_unit_quad(), subd_levels=2)
        assert abs(K_int) < 1.0, f"∫K dA should be ~0 for flat plane, got {K_int}"

    def test_report_returns_dataclass(self):
        rpt = compute_subd_integrals(_flat_unit_quad(), subd_levels=2)
        assert isinstance(rpt, SubDIntegralReport)
        assert rpt.area >= 0.0


# ---------------------------------------------------------------------------
# Tests: sphere from CC cube (Gauss-Bonnet)
# ---------------------------------------------------------------------------

class TestSphereFromCCCube:
    def test_euler_characteristic(self):
        rpt = compute_subd_integrals(_cc_cube_unit(), subd_levels=3)
        assert rpt.euler_characteristic == 2

    def test_gaussian_curvature_integral_near_4pi(self):
        """∫K dA should be near 4π ≈ 12.566 (Gauss-Bonnet, χ=2)."""
        K_int = integrate_gaussian_curvature(_cc_cube_unit(), subd_levels=3)
        target = 4.0 * math.pi
        assert abs(K_int - target) < 0.15 * target, (
            f"∫K dA = {K_int:.4f}, expected ~{target:.4f} (±15%)"
        )

    def test_gauss_bonnet_residual_lt_15pct(self):
        """Gauss-Bonnet residual should be < 15% for sphere-from-cube."""
        rpt = compute_subd_integrals(_cc_cube_unit(), subd_levels=3)
        gb = rpt.gauss_bonnet_residual
        assert not math.isnan(gb), "Gauss-Bonnet residual should not be NaN for χ=2"
        assert gb < 0.15, (
            f"Gauss-Bonnet residual {gb:.4f} > 15%. "
            f"∫K dA = {rpt.gaussian_curvature_integral:.4f}, "
            f"expected {rpt.gauss_bonnet_expected:.4f}"
        )

    def test_area_positive_and_reasonable(self):
        area = integrate_area(_cc_cube_unit(), subd_levels=3)
        assert area > 1.0, f"Sphere area should be > 1, got {area}"

    def test_mean_curvature_integral_positive(self):
        """Sphere has uniform positive mean curvature → ∫H dA > 0."""
        H_int = integrate_mean_curvature(_cc_cube_unit(), subd_levels=3)
        assert H_int > 0.0, f"∫H dA for a sphere should be > 0, got {H_int}"


# ---------------------------------------------------------------------------
# Tests: torus (χ=0, ∫K dA ≈ 0)
# ---------------------------------------------------------------------------

class TestTorusGaussBonnet:
    def test_euler_characteristic_zero(self):
        rpt = compute_subd_integrals(_torus_cage(), subd_levels=2)
        assert rpt.euler_characteristic == 0, (
            f"Torus χ should be 0, got {rpt.euler_characteristic}"
        )

    def test_gaussian_integral_near_zero(self):
        """∫K dA ≈ 0 for a torus (Gauss-Bonnet, χ=0)."""
        K_int = integrate_gaussian_curvature(_torus_cage(), subd_levels=2)
        # Generous tolerance: coarse cage + outer-ring extrapolation error
        assert abs(K_int) < 4.0, (
            f"|∫K dA| = {abs(K_int):.4f} should be near 0 for torus"
        )

    def test_area_positive(self):
        area = integrate_area(_torus_cage(), subd_levels=2)
        expected_area = 4.0 * math.pi ** 2 * 1.0 * 0.3
        assert area > 0.3 * expected_area, (
            f"Torus area {area:.4f} too small (smooth ref {expected_area:.4f})"
        )


# ---------------------------------------------------------------------------
# Tests: ribbon (finite non-zero ∫H dA)
# ---------------------------------------------------------------------------

class TestRibbon:
    def test_area_positive(self):
        area = integrate_area(_ribbon_cage(), subd_levels=2)
        assert area > 0.1, f"Ribbon area should be > 0.1, got {area}"

    def test_mean_curvature_finite(self):
        H_int = integrate_mean_curvature(_ribbon_cage(), subd_levels=2)
        assert not math.isnan(H_int), "∫H dA should not be NaN"
        assert math.isfinite(H_int), "∫H dA should be finite"

    def test_all_three_integrals_finite(self):
        rpt = compute_subd_integrals(_ribbon_cage(), subd_levels=2)
        assert math.isfinite(rpt.area)
        assert math.isfinite(rpt.mean_curvature_integral)
        assert math.isfinite(rpt.gaussian_curvature_integral)


# ---------------------------------------------------------------------------
# Tests: SubDIntegralReport completeness
# ---------------------------------------------------------------------------

class TestReportCompleteness:
    def test_report_fields(self):
        rpt = compute_subd_integrals(_cc_cube_unit(), subd_levels=2)
        for attr in [
            "area", "mean_curvature_integral", "gaussian_curvature_integral",
            "euler_characteristic", "gauss_bonnet_expected", "gauss_bonnet_residual",
            "gauss_bonnet_ok", "n_faces_integrated", "n_faces_skipped",
            "extraordinary_vertex_handling",
        ]:
            assert hasattr(rpt, attr), f"Report missing attribute: {attr}"

    def test_n_faces_integrated_positive(self):
        rpt = compute_subd_integrals(_cc_cube_unit(), subd_levels=2)
        assert rpt.n_faces_integrated > 0

    def test_gauss_bonnet_expected_matches_chi(self):
        rpt = compute_subd_integrals(_cc_cube_unit(), subd_levels=2)
        expected = 2.0 * math.pi * rpt.euler_characteristic
        assert abs(rpt.gauss_bonnet_expected - expected) < 1e-10

    def test_extraordinary_handling_documented(self):
        rpt = compute_subd_integrals(_cc_cube_unit(), subd_levels=2)
        assert len(rpt.extraordinary_vertex_handling) > 10
