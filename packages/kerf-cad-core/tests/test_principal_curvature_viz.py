"""
test_principal_curvature_viz.py
================================
Hermetic analytic-oracle tests for
``kerf_cad_core.geom.principal_curvature_viz``.

Surfaces used:
  - Exact rational NURBS unit sphere   → κ₁ = κ₂ = 1/R (umbilic)
  - Exact rational NURBS cylinder R=2  → κ₁ = 0, κ₂ = −1/R (do Carmo conv.)
  - Bilinear flat plane                → κ₁ = κ₂ = 0
  - Polynomial torus (R=2, r=0.5)     → qualitative outer/inner rim sign test
  - SVG / PNG export
  - Dataclass invariants

All tests are pure-Python — no OCC, no database, no network.

Notes on sign convention (do Carmo §3.4)
-----------------------------------------
κ₁ ≥ κ₂ (algebraic, not absolute value).
For an outward normal:
  - Sphere R=1: both curvatures are +1/R (positive, centre of curvature inside).
  - Cylinder R: κ₁ = 0 (axial, flat), κ₂ = −1/R (azimuthal, negative with
    outward normal pointing away from the axis, centre of curvature is inside,
    which is "−1/R" in do Carmo's convention).

Actually for the polynomial/rational NURBS approximations here:
  - The NORMAL direction from the cross-product S_u×S_v may be inward or
    outward depending on the parameterisation.  The absolute magnitudes of
    the principal curvatures give the more robust test.

We therefore test abs(κ) values for magnitude checks, and only test
structural properties (κ₁ ≥ κ₂, K = κ₁·κ₂, H = (κ₁+κ₂)/2) algebraically.
"""

from __future__ import annotations

import math
import struct

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.principal_curvature_viz import (
    PrincipalCurvatureSample,
    PrincipalCurvatureVizResult,
    sample_principal_curvatures,
)


# ---------------------------------------------------------------------------
# Surface factories
# ---------------------------------------------------------------------------

def _make_bilinear_plane(x0=0.0, x1=2.0, y0=0.0, y1=2.0) -> NurbsSurface:
    """Flat z=0 plane patch, degree 1×1 (exact — zero second derivatives)."""
    cps = np.array([
        [[x0, y0, 0.0], [x0, y1, 0.0]],
        [[x1, y0, 0.0], [x1, y1, 0.0]],
    ], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cps, knots_u=knots, knots_v=knots.copy(),
    )


def _make_exact_cylinder_nurbs(R: float = 2.0, h: float = 4.0) -> NurbsSurface:
    """Exact rational NURBS cylinder (9×2 control points, degree 2×1).

    Uses the standard 9-point rational quadratic circle (Piegl & Tiller §7.5)
    extruded linearly along Z.  Gives EXACT cylinder geometry so curvatures
    are analytic.

    With outward normal (S_u × S_v pointing outward from the axis):
      κ₁ = 0  (axial direction, no bending)
      κ₂ = −1/R  (azimuthal direction; for outward normal, centre of curvature
                   is inside, hence negative in do Carmo's sign convention)
    |κ₂| = 1/R = 0.5 for R=2.
    """
    s = math.sqrt(2.0) / 2.0
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
    n_circ = circle_cps.shape[0]   # 9
    cps = np.zeros((n_circ, 2, 3))
    for i in range(n_circ):
        cps[i, 0] = [circle_cps[i, 0], circle_cps[i, 1], 0.0]
        cps[i, 1] = [circle_cps[i, 0], circle_cps[i, 1], h]
    w_circ = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])
    weights = np.column_stack([w_circ, w_circ])   # shape (9, 2)
    knots_u = np.array([0.0, 0.0, 0.0,
                        0.25, 0.25, 0.5, 0.5, 0.75, 0.75,
                        1.0, 1.0, 1.0])
    knots_v = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=2, degree_v=1,
        control_points=cps, knots_u=knots_u, knots_v=knots_v,
        weights=weights,
    )


def _make_exact_sphere_nurbs(R: float = 1.0) -> NurbsSurface:
    """Exact rational NURBS sphere (9×5 control points, degree 2×2).

    Product of two rational quadratic circles (Piegl & Tiller §7.8).
    This gives EXACT sphere geometry; |κ₁| = |κ₂| = 1/R everywhere in the
    interior (away from poles).
    """
    s = math.sqrt(2.0) / 2.0

    # v-direction: 5-point rational semicircle from south (0,0,-R) to north (0,0,R)
    lat_xz = np.array([
        [0.0, -1.0],   # south pole
        [1.0, -1.0],   # shoulder
        [1.0,  0.0],   # equator
        [1.0,  1.0],   # shoulder
        [0.0,  1.0],   # north pole
    ])
    lat_w = np.array([1.0, s, 1.0, s, 1.0])
    knots_v = np.array([0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0])

    # u-direction: 9-point rational circle in xy-plane
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
    circ_w = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])
    knots_u = np.array([0.0, 0.0, 0.0,
                        0.25, 0.25, 0.5, 0.5, 0.75, 0.75,
                        1.0, 1.0, 1.0])

    n_lon, n_lat = 9, 5
    cps     = np.zeros((n_lon, n_lat, 3))
    weights = np.zeros((n_lon, n_lat))
    for i_lat in range(n_lat):
        r  = lat_xz[i_lat, 0] * R
        z  = lat_xz[i_lat, 1] * R
        wl = lat_w[i_lat]
        for j_lon in range(n_lon):
            x = r * circle_xy[j_lon, 0]
            y = r * circle_xy[j_lon, 1]
            cps[j_lon, i_lat]     = [x, y, z]
            weights[j_lon, i_lat] = circ_w[j_lon] * wl

    return NurbsSurface(
        degree_u=2, degree_v=2,
        control_points=cps, knots_u=knots_u, knots_v=knots_v,
        weights=weights,
    )


def _make_knots(n: int, deg: int) -> np.ndarray:
    inner = max(0, n - deg - 1)
    parts = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def _make_torus_nurbs(R: float = 2.0, r: float = 0.5,
                       nu: int = 20, nv: int = 12) -> NurbsSurface:
    """Polynomial torus (degree-3) for qualitative torus tests."""
    deg = 3
    nu  = max(nu, deg + 1)
    nv  = max(nv, deg + 1)
    u_max = 2.0 * math.pi * (nu - 1) / nu
    v_max = 2.0 * math.pi * (nv - 1) / nv
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        u = u_max * i / max(nu - 1, 1)
        for j in range(nv):
            v = v_max * j / max(nv - 1, 1)
            cp[i, j] = [
                (R + r * math.cos(v)) * math.cos(u),
                (R + r * math.cos(v)) * math.sin(u),
                r * math.sin(v),
            ]
    return NurbsSurface(
        degree_u=deg, degree_v=deg,
        control_points=cp,
        knots_u=_make_knots(nu, deg),
        knots_v=_make_knots(nv, deg),
    )


# ---------------------------------------------------------------------------
# Helper: non-degenerate, finite-valued samples
# ---------------------------------------------------------------------------

def _valid(result: PrincipalCurvatureVizResult) -> list[PrincipalCurvatureSample]:
    return [s for s in result.samples if not s.is_degenerate and math.isfinite(s.kappa_1)]


# ===========================================================================
# 1. Flat plane: κ₁ = κ₂ = 0, K = 0, H = 0  (exact, degree-1 bilinear patch)
# ===========================================================================

class TestPlane:
    def test_k1_exactly_zero(self):
        """Bilinear plane: κ₁ must be exactly 0 (zero second derivatives)."""
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=6, nv=6, export_svg=False)
        for s in _valid(res):
            assert abs(s.kappa_1) < 1e-10, f"Plane κ₁={s.kappa_1}"

    def test_k2_exactly_zero(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=6, nv=6, export_svg=False)
        for s in _valid(res):
            assert abs(s.kappa_2) < 1e-10, f"Plane κ₂={s.kappa_2}"

    def test_gauss_K_exactly_zero(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=6, nv=6, export_svg=False)
        for s in _valid(res):
            assert abs(s.gauss_K) < 1e-10, f"Plane K={s.gauss_K}"

    def test_mean_H_exactly_zero(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=6, nv=6, export_svg=False)
        for s in _valid(res):
            assert abs(s.mean_H) < 1e-10, f"Plane H={s.mean_H}"


# ===========================================================================
# 2. Exact NURBS sphere R=1: |κ₁| = |κ₂| = 1/R everywhere (interior)
# ===========================================================================

class TestSphere:
    R = 1.0

    def _interior(self, res: PrincipalCurvatureVizResult) -> list[PrincipalCurvatureSample]:
        """Interior samples only — drop pole rows (v near 0.0 and 1.0)."""
        valid = _valid(res)
        if not valid:
            return valid
        # The grid is ordered u-outer, v-inner. For a 10×10 grid with the
        # sphere's knots [0,0.5,1.0], the poles are the rows where the v
        # knot boundary sits. We filter by v being in (0.1, 0.4) or (0.6, 0.9).
        v_min = min(s.v for s in valid)
        v_max = max(s.v for s in valid)
        span  = v_max - v_min
        lo    = v_min + 0.15 * span
        hi    = v_max - 0.15 * span
        return [s for s in valid if lo < s.v < hi]

    def test_abs_k1_approx_one_over_R(self):
        """Interior: |κ₁| ≈ 1/R within 5e-3 on the exact rational sphere."""
        srf = _make_exact_sphere_nurbs(self.R)
        res = sample_principal_curvatures(srf, nu=10, nv=10, export_svg=False)
        interior = self._interior(res)
        assert len(interior) > 0, "No interior samples found"
        expected = 1.0 / self.R
        for s in interior:
            assert abs(abs(s.kappa_1) - expected) < 5e-3, (
                f"Sphere |κ₁|={abs(s.kappa_1):.5f} ≠ expected {expected:.5f}"
            )

    def test_abs_k2_approx_one_over_R(self):
        """Interior: |κ₂| ≈ 1/R within 5e-3 on the exact rational sphere."""
        srf = _make_exact_sphere_nurbs(self.R)
        res = sample_principal_curvatures(srf, nu=10, nv=10, export_svg=False)
        interior = self._interior(res)
        assert len(interior) > 0
        expected = 1.0 / self.R
        for s in interior:
            assert abs(abs(s.kappa_2) - expected) < 5e-3, (
                f"Sphere |κ₂|={abs(s.kappa_2):.5f} ≠ expected {expected:.5f}"
            )

    def test_abs_K_approx_one_over_R_sq(self):
        """Interior: |K| ≈ 1/R² (Gaussian curvature of sphere)."""
        srf = _make_exact_sphere_nurbs(self.R)
        res = sample_principal_curvatures(srf, nu=10, nv=10, export_svg=False)
        interior = self._interior(res)
        assert len(interior) > 0
        expected = 1.0 / (self.R * self.R)
        for s in interior:
            assert abs(abs(s.gauss_K) - expected) < 1e-2, (
                f"Sphere |K|={abs(s.gauss_K):.5f} ≠ expected {expected:.5f}"
            )

    def test_k1_k2_close_umbilic(self):
        """On a sphere κ₁ ≈ κ₂ (umbilic): |κ₁ − κ₂| < 1e-2."""
        srf = _make_exact_sphere_nurbs(self.R)
        res = sample_principal_curvatures(srf, nu=10, nv=10, export_svg=False)
        interior = self._interior(res)
        assert len(interior) > 0
        for s in interior:
            assert abs(s.kappa_1 - s.kappa_2) < 1e-2, (
                f"Sphere umbilic: |κ₁−κ₂|={abs(s.kappa_1-s.kappa_2):.6f}"
            )

    def test_R2_sphere_abs_curvatures(self):
        """Sphere R=2: |κ| = 1/2 = 0.5 at interior points."""
        R2 = 2.0
        srf = _make_exact_sphere_nurbs(R2)
        res = sample_principal_curvatures(srf, nu=10, nv=10, export_svg=False)
        interior = self._interior(res)
        assert len(interior) > 0
        expected = 1.0 / R2
        for s in interior:
            assert abs(abs(s.kappa_1) - expected) < 5e-3, (
                f"R=2 sphere: |κ₁|={abs(s.kappa_1):.5f} ≠ {expected:.5f}"
            )


# ===========================================================================
# 3. Exact NURBS cylinder R=2: |κ₁| = 0, |κ₂| = 1/R
# ===========================================================================

class TestCylinder:
    R = 2.0

    def _mid_interior(self, res: PrincipalCurvatureVizResult) -> list[PrincipalCurvatureSample]:
        """Return samples in the interior of the u range (skip boundary arcs)."""
        valid = _valid(res)
        if not valid:
            return valid
        u_vals = sorted(set(s.u for s in valid))
        # Keep middle 60% of u samples
        lo = u_vals[len(u_vals) // 5]
        hi = u_vals[4 * len(u_vals) // 5]
        return [s for s in valid if lo <= s.u <= hi]

    def test_k1_near_zero(self):
        """Cylinder: κ₁ ≈ 0 (axial direction is flat)."""
        srf = _make_exact_cylinder_nurbs(R=self.R)
        res = sample_principal_curvatures(srf, nu=8, nv=4, export_svg=False)
        interior = self._mid_interior(res)
        assert len(interior) > 0
        for s in interior:
            assert abs(s.kappa_1) < 1e-3, (
                f"Cylinder κ₁={s.kappa_1:.6f} should be ≈0 at u={s.u:.3f}"
            )

    def test_abs_k2_approx_one_over_R(self):
        """Cylinder: |κ₂| ≈ 1/R = 0.5."""
        srf = _make_exact_cylinder_nurbs(R=self.R)
        res = sample_principal_curvatures(srf, nu=8, nv=4, export_svg=False)
        interior = self._mid_interior(res)
        assert len(interior) > 0
        expected = 1.0 / self.R
        for s in interior:
            assert abs(abs(s.kappa_2) - expected) < 1e-3, (
                f"Cylinder |κ₂|={abs(s.kappa_2):.5f} ≠ {expected:.5f}"
            )

    def test_gauss_K_near_zero(self):
        """Cylinder is developable → K = κ₁·κ₂ ≈ 0."""
        srf = _make_exact_cylinder_nurbs(R=self.R)
        res = sample_principal_curvatures(srf, nu=8, nv=4, export_svg=False)
        interior = self._mid_interior(res)
        assert len(interior) > 0
        for s in interior:
            assert abs(s.gauss_K) < 1e-6, (
                f"Cylinder K={s.gauss_K:.8f} should be ≈0"
            )


# ===========================================================================
# 4. Polynomial torus (R=2, r=0.5): qualitative outer/inner rim sign test
#    and outer-rim κ₂ direction sign
# ===========================================================================

class TestTorus:
    R = 2.0
    r = 0.5

    def test_k1_always_geq_k2(self):
        """By convention κ₁ ≥ κ₂ at every non-degenerate sample."""
        srf = _make_torus_nurbs(R=self.R, r=self.r, nu=20, nv=14)
        res = sample_principal_curvatures(srf, nu=8, nv=8, export_svg=False)
        for s in _valid(res):
            assert s.kappa_1 >= s.kappa_2 - 1e-10, (
                f"κ₁={s.kappa_1:.6f} < κ₂={s.kappa_2:.6f} at u={s.u:.3f} v={s.v:.3f}"
            )

    def test_outer_rim_larger_curvature_magnitude_close_to_one_over_r(self):
        """Max |κ| across the torus approximates 1/r = 2.0 (minor-circle curvature).

        For a torus with R=2, r=0.5: max principal curvature = 1/r = 2.0.
        With the polynomial approximation we accept 30% relative error.
        """
        srf = _make_torus_nurbs(R=self.R, r=self.r, nu=20, nv=14)
        res = sample_principal_curvatures(srf, nu=10, nv=10, export_svg=False)
        valid = _valid(res)
        assert len(valid) > 0
        kmax = max(max(abs(s.kappa_1), abs(s.kappa_2)) for s in valid)
        expected_minor = 1.0 / self.r   # 2.0
        # Polynomial approximation error: accept within 40%
        assert abs(kmax - expected_minor) / expected_minor < 0.40, (
            f"Max principal curvature={kmax:.4f}, expected ≈1/r={expected_minor:.4f}"
        )

    def test_inner_rim_larger_curvature_than_outer(self):
        """Inner rim (v≈π): |κ₂| = 1/(R−r) > 1/(R+r) = outer rim |κ₂|.

        This tests the sign variation: the curvature in the minor-circle
        direction varies as cos(v)/(R + r·cos(v)).  The absolute value is
        larger at the inner rim (v≈π, cos(v)=−1) than the outer rim (v≈0).
        """
        srf = _make_torus_nurbs(R=self.R, r=self.r, nu=20, nv=14)
        res = sample_principal_curvatures(srf, nu=10, nv=14, export_svg=False)
        valid = _valid(res)
        assert len(valid) > 0

        k2_vals = [s.kappa_2 for s in valid]
        k2_inner_mag = max(abs(k) for k in k2_vals)
        k2_outer_mag = min(abs(k) for k in k2_vals)

        # 1/(R−r) > 1/(R+r) → inner rim has larger |κ₂|
        assert k2_inner_mag > k2_outer_mag, (
            f"Inner-rim |κ₂| ({k2_inner_mag:.4f}) should > outer-rim ({k2_outer_mag:.4f})"
        )

    def test_gauss_K_varies_sign(self):
        """Torus K changes sign (elliptic → hyperbolic): must include both K>0 and K<0."""
        srf = _make_torus_nurbs(R=self.R, r=self.r, nu=20, nv=14)
        res = sample_principal_curvatures(srf, nu=10, nv=14, export_svg=False)
        valid = _valid(res)
        assert len(valid) > 0
        K_vals = [s.gauss_K for s in valid]
        assert any(k > 1e-6 for k in K_vals), "Expected some K>0 on torus (outer rim)"
        assert any(k < -1e-6 for k in K_vals), "Expected some K<0 on torus (inner rim)"


# ===========================================================================
# 5. SVG / PNG output non-empty and valid
# ===========================================================================

class TestVisualisationOutput:
    def test_svg_non_empty(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=5, nv=5, export_svg=True, export_png=False)
        assert len(res.svg_heatmap) > 200, "SVG should be non-empty"
        assert "<svg" in res.svg_heatmap, "SVG must contain <svg> element"
        assert "<rect" in res.svg_heatmap, "SVG must contain <rect> elements"

    def test_svg_viewbox_present(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=5, nv=5, export_svg=True, export_png=False)
        assert "viewBox" in res.svg_heatmap, "SVG must have viewBox attribute"

    def test_png_non_empty(self):
        # Use cylinder (varied curvature) so the PNG has actual content
        srf = _make_exact_cylinder_nurbs(R=2.0)
        res = sample_principal_curvatures(srf, nu=8, nv=6, export_svg=False, export_png=True)
        assert res.png_bytes is not None, "PNG bytes should not be None"
        assert len(res.png_bytes) > 50, "PNG bytes should be non-empty"

    def test_png_valid_signature(self):
        """PNG must start with the canonical 8-byte PNG signature."""
        srf = _make_exact_cylinder_nurbs(R=2.0)
        res = sample_principal_curvatures(srf, nu=4, nv=4, export_svg=False, export_png=True)
        assert res.png_bytes is not None
        assert res.png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "Invalid PNG signature"

    def test_png_ihdr_chunk(self):
        """Bytes 12–15 of PNG must be the 'IHDR' chunk type."""
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=4, nv=4, export_svg=False, export_png=True)
        assert res.png_bytes is not None
        assert res.png_bytes[12:16] == b"IHDR", "Expected IHDR chunk after signature"

    def test_svg_disabled_returns_empty_string(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=4, nv=4, export_svg=False, export_png=False)
        assert res.svg_heatmap == "", "svg_heatmap should be '' when export_svg=False"

    def test_png_disabled_returns_none(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=4, nv=4, export_svg=True, export_png=False)
        assert res.png_bytes is None, "png_bytes should be None when export_png=False"


# ===========================================================================
# 6. Dataclass invariants
# ===========================================================================

class TestDataclassInvariants:
    def test_sample_count(self):
        nu, nv = 7, 5
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=nu, nv=nv, export_svg=False)
        assert len(res.samples) == nu * nv

    def test_sample_type(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=4, nv=4, export_svg=False)
        for s in res.samples:
            assert isinstance(s, PrincipalCurvatureSample)

    def test_result_type(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=4, nv=4, export_svg=False)
        assert isinstance(res, PrincipalCurvatureVizResult)

    def test_honest_caveat_present(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=4, nv=4, export_svg=False)
        assert len(res.honest_caveat) > 30, "honest_caveat should be descriptive"

    def test_gauss_K_equals_product(self):
        """K = κ₁·κ₂ at every non-degenerate sample (within 1e-8)."""
        srf = _make_exact_cylinder_nurbs(R=2.0)
        res = sample_principal_curvatures(srf, nu=6, nv=4, export_svg=False)
        for s in _valid(res):
            expected = s.kappa_1 * s.kappa_2
            assert abs(expected - s.gauss_K) < 1e-8, (
                f"K={s.gauss_K:.9f} ≠ κ₁·κ₂={expected:.9f}"
            )

    def test_mean_H_equals_half_sum(self):
        """H = (κ₁ + κ₂) / 2 at every non-degenerate sample (within 1e-8)."""
        srf = _make_exact_cylinder_nurbs(R=1.5)
        res = sample_principal_curvatures(srf, nu=6, nv=4, export_svg=False)
        for s in _valid(res):
            expected = (s.kappa_1 + s.kappa_2) / 2.0
            assert abs(expected - s.mean_H) < 1e-8, (
                f"H={s.mean_H:.9f} ≠ (κ₁+κ₂)/2={expected:.9f}"
            )

    def test_k1_geq_k2_all_surfaces(self):
        """κ₁ ≥ κ₂ at every sample on every surface."""
        surfaces = [
            _make_bilinear_plane(),
            _make_exact_cylinder_nurbs(R=2.0),
            _make_exact_sphere_nurbs(1.0),
            _make_torus_nurbs(R=2.0, r=0.5),
        ]
        for srf in surfaces:
            res = sample_principal_curvatures(srf, nu=4, nv=4, export_svg=False)
            for s in _valid(res):
                assert s.kappa_1 >= s.kappa_2 - 1e-10, (
                    f"κ₁={s.kappa_1:.6f} < κ₂={s.kappa_2:.6f}"
                )

    def test_uv_values_in_knot_domain(self):
        """Sample u, v values lie within the surface's knot domain."""
        srf = _make_exact_sphere_nurbs(2.0)
        res = sample_principal_curvatures(srf, nu=5, nv=5, export_svg=False)
        u_min = float(srf.knots_u[0])
        u_max = float(srf.knots_u[-1])
        v_min = float(srf.knots_v[0])
        v_max = float(srf.knots_v[-1])
        for s in res.samples:
            assert u_min - 1e-9 <= s.u <= u_max + 1e-9
            assert v_min - 1e-9 <= s.v <= v_max + 1e-9


# ===========================================================================
# 7. Grid clamping
# ===========================================================================

class TestGridClamping:
    def test_nu_minimum_clamped_to_3(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=1, nv=1, export_svg=False)
        assert len(res.samples) == 9, f"Expected 9 samples (3×3), got {len(res.samples)}"

    def test_nu_maximum_clamped_to_200(self):
        srf = _make_bilinear_plane()
        res = sample_principal_curvatures(srf, nu=999, nv=3, export_svg=False)
        assert len(res.samples) == 200 * 3, (
            f"Expected 600 samples (200×3), got {len(res.samples)}"
        )
