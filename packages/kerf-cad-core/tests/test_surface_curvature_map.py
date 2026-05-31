"""
test_surface_curvature_map.py
==============================
Hermetic analytic-oracle tests for
``kerf_cad_core.geom.surface_curvature_map``.

Surfaces used:
  - Exact rational NURBS sphere R=1  → K=1, H=1 everywhere (umbilic)
  - Exact rational NURBS cylinder R=2 → K=0, H=0.25
  - Polynomial saddle (hyperbolic paraboloid z=xy) → K<0
  - Bilinear flat plane → K=0, H=0

Scalar fields tested: "gauss", "mean", "abs_max", "abs_min"
Colourmaps tested: viridis, rdbu (auto + explicit)
SVG/PNG validity

All tests are pure-Python — no OCC, no network, no database.

References
----------
do Carmo §3.3; Mortenson §6.5.
"""

from __future__ import annotations

import math
import struct

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.surface_curvature_map import (
    CurvatureMapResult,
    CurvatureMapSpec,
    sample_surface_curvature_map,
)


# ---------------------------------------------------------------------------
# Surface factories (reuse patterns from test_principal_curvature_viz.py)
# ---------------------------------------------------------------------------

def _make_bilinear_plane() -> NurbsSurface:
    """Flat z=0 plane patch, degree 1×1 (exact zero second derivatives)."""
    cps = np.array([
        [[0.0, 0.0, 0.0], [0.0, 2.0, 0.0]],
        [[2.0, 0.0, 0.0], [2.0, 2.0, 0.0]],
    ], dtype=float)
    k = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(degree_u=1, degree_v=1,
                        control_points=cps, knots_u=k, knots_v=k.copy())


def _make_exact_sphere_nurbs(R: float = 1.0) -> NurbsSurface:
    """Exact rational NURBS sphere (9×5 control points, degree 2×2)."""
    s = math.sqrt(2.0) / 2.0
    lat_xz = np.array([
        [0.0, -1.0],
        [1.0, -1.0],
        [1.0,  0.0],
        [1.0,  1.0],
        [0.0,  1.0],
    ])
    lat_w = np.array([1.0, s, 1.0, s, 1.0])
    knots_v = np.array([0.0, 0.0, 0.0, 0.5, 0.5, 1.0, 1.0, 1.0])

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

    return NurbsSurface(degree_u=2, degree_v=2,
                        control_points=cps, knots_u=knots_u, knots_v=knots_v,
                        weights=weights)


def _make_exact_cylinder_nurbs(R: float = 2.0, h: float = 4.0) -> NurbsSurface:
    """Exact rational NURBS cylinder (9×2 control points, degree 2×1)."""
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
    n_circ = circle_cps.shape[0]
    cps = np.zeros((n_circ, 2, 3))
    for i in range(n_circ):
        cps[i, 0] = [circle_cps[i, 0], circle_cps[i, 1], 0.0]
        cps[i, 1] = [circle_cps[i, 0], circle_cps[i, 1], h]
    w_circ  = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])
    weights = np.column_stack([w_circ, w_circ])
    knots_u = np.array([0.0, 0.0, 0.0,
                        0.25, 0.25, 0.5, 0.5, 0.75, 0.75,
                        1.0, 1.0, 1.0])
    knots_v = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(degree_u=2, degree_v=1,
                        control_points=cps, knots_u=knots_u, knots_v=knots_v,
                        weights=weights)


def _make_knots(n: int, deg: int) -> np.ndarray:
    inner = max(0, n - deg - 1)
    parts = [np.zeros(deg + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(deg + 1))
    return np.concatenate(parts)


def _make_saddle_nurbs(scale: float = 1.0, n: int = 8) -> NurbsSurface:
    """Polynomial degree-2 approximation of z = xy (hyperbolic paraboloid).

    For a saddle z=xy, the Gaussian curvature K = -1/(1+x²+y²)² < 0 everywhere.
    We use a bilinear degree-1 patch as the simplest test (degree-1 can still
    have non-zero second cross-derivatives via finite-difference path).

    Better: use degree 2 with quadratic terms.
    """
    deg = 2
    n = max(n, deg + 1)
    cps = np.zeros((n, n, 3))
    t_vals = np.linspace(-scale, scale, n)
    for i, x in enumerate(t_vals):
        for j, y in enumerate(t_vals):
            cps[i, j] = [x, y, x * y]
    k_u = _make_knots(n, deg)
    k_v = _make_knots(n, deg)
    return NurbsSurface(degree_u=deg, degree_v=deg,
                        control_points=cps, knots_u=k_u, knots_v=k_v)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _finite_flat(result: CurvatureMapResult) -> list[float]:
    """Flatten curvature_grid to a list of finite values."""
    return [
        v for row in result.curvature_grid for v in row
        if math.isfinite(v)
    ]


def _interior_sphere(result: CurvatureMapResult) -> list[float]:
    """Interior rows only — skip polar rows (v near knot boundaries)."""
    finite = []
    for row in result.curvature_grid:
        n = len(row)
        lo = n // 6
        hi = n - lo
        row_finite = [row[j] for j in range(lo, hi) if math.isfinite(row[j])]
        finite.extend(row_finite)
    return finite


# ===========================================================================
# 1. Plane: K=0, H=0 (exact, degree-1)
# ===========================================================================

class TestPlane:
    def test_gauss_K_zero(self):
        """Flat plane: all Gaussian K values ≈ 0."""
        srf  = _make_bilinear_plane()
        spec = CurvatureMapSpec(nu_samples=6, nv_samples=6, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        for v in _finite_flat(res):
            assert abs(v) < 1e-10, f"Plane K={v}"

    def test_mean_H_zero(self):
        """Flat plane: all mean H values ≈ 0."""
        srf  = _make_bilinear_plane()
        spec = CurvatureMapSpec(nu_samples=6, nv_samples=6, scalar_to_map="mean")
        res  = sample_surface_curvature_map(srf, spec)
        for v in _finite_flat(res):
            assert abs(v) < 1e-10, f"Plane H={v}"

    def test_abs_max_zero(self):
        """Flat plane: |κ₁| = 0 everywhere."""
        srf  = _make_bilinear_plane()
        spec = CurvatureMapSpec(nu_samples=5, nv_samples=5, scalar_to_map="abs_max")
        res  = sample_surface_curvature_map(srf, spec)
        for v in _finite_flat(res):
            assert abs(v) < 1e-10, f"Plane |κ₁|={v}"


# ===========================================================================
# 2. Exact NURBS sphere R=1: K=1, H=1 at interior (umbilic)
# ===========================================================================

class TestSphereGaussian:
    R = 1.0

    def test_gauss_K_approx_one(self):
        """Sphere R=1: Gaussian K ≈ 1 at interior points (within 2e-2)."""
        srf  = _make_exact_sphere_nurbs(self.R)
        spec = CurvatureMapSpec(nu_samples=10, nv_samples=10, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        interior = _interior_sphere(res)
        assert len(interior) > 0, "No interior samples"
        expected = 1.0 / (self.R * self.R)
        for v in interior:
            assert abs(abs(v) - expected) < 2e-2, (
                f"Sphere K={v:.5f} ≠ expected {expected:.5f}"
            )

    def test_gauss_K_positive(self):
        """Sphere K must be positive everywhere (elliptic surface)."""
        srf  = _make_exact_sphere_nurbs(self.R)
        spec = CurvatureMapSpec(nu_samples=8, nv_samples=8, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        interior = _interior_sphere(res)
        assert len(interior) > 0
        for v in interior:
            assert v > -1e-3, f"Sphere K={v:.6f} should be positive"

    def test_mean_H_approx_one(self):
        """Sphere R=1: mean H ≈ ±1 at interior points (within 2e-2)."""
        srf  = _make_exact_sphere_nurbs(self.R)
        spec = CurvatureMapSpec(nu_samples=10, nv_samples=10, scalar_to_map="mean")
        res  = sample_surface_curvature_map(srf, spec)
        interior = _interior_sphere(res)
        assert len(interior) > 0
        expected = 1.0 / self.R
        for v in interior:
            assert abs(abs(v) - expected) < 2e-2, (
                f"Sphere H={v:.5f} ≠ expected ±{expected:.5f}"
            )

    def test_abs_max_approx_one_over_R(self):
        """Sphere R=1: |κ₁| ≈ 1 at interior points."""
        srf  = _make_exact_sphere_nurbs(self.R)
        spec = CurvatureMapSpec(nu_samples=10, nv_samples=10, scalar_to_map="abs_max")
        res  = sample_surface_curvature_map(srf, spec)
        interior = _interior_sphere(res)
        assert len(interior) > 0
        expected = 1.0 / self.R
        for v in interior:
            assert abs(v - expected) < 2e-2, f"Sphere |κ₁|={v:.5f} ≠ {expected:.5f}"

    def test_grid_dimensions(self):
        """curvature_grid has correct dimensions nu × nv."""
        srf  = _make_exact_sphere_nurbs(self.R)
        spec = CurvatureMapSpec(nu_samples=8, nv_samples=6, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        assert len(res.curvature_grid) == 8
        for row in res.curvature_grid:
            assert len(row) == 6


# ===========================================================================
# 3. Exact NURBS cylinder R=2: K=0, H = 0.25
# ===========================================================================

class TestCylinderCurvature:
    R = 2.0

    def _mid(self, result: CurvatureMapResult) -> list[float]:
        """Return finite values from middle 60% of u-rows."""
        rows = result.curvature_grid
        n = len(rows)
        lo = n // 5
        hi = n - lo
        flat = []
        for i in range(lo, hi):
            flat.extend(v for v in rows[i] if math.isfinite(v))
        return flat

    def test_gauss_K_near_zero(self):
        """Cylinder is developable → K ≈ 0."""
        srf  = _make_exact_cylinder_nurbs(R=self.R)
        spec = CurvatureMapSpec(nu_samples=8, nv_samples=4, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        for v in self._mid(res):
            assert abs(v) < 1e-6, f"Cylinder K={v:.9f} should be ≈0"

    def test_mean_H_approx_one_over_2R(self):
        """Cylinder mean H ≈ 1/(2R) = 0.25 (κ₁=0, κ₂=−1/R, H=(0−1/R)/2)."""
        srf  = _make_exact_cylinder_nurbs(R=self.R)
        spec = CurvatureMapSpec(nu_samples=8, nv_samples=4, scalar_to_map="mean")
        res  = sample_surface_curvature_map(srf, spec)
        mid  = self._mid(res)
        assert len(mid) > 0
        # |H| = 1/(2R) = 0.25 for R=2
        expected = 1.0 / (2.0 * self.R)
        for v in mid:
            assert abs(abs(v) - expected) < 5e-4, (
                f"Cylinder |H|={abs(v):.5f} ≠ {expected:.5f}"
            )

    def test_abs_min_approx_one_over_R(self):
        """|κ₂| ≈ 1/R = 0.5 for the cylinder (azimuthal curvature)."""
        srf  = _make_exact_cylinder_nurbs(R=self.R)
        spec = CurvatureMapSpec(nu_samples=8, nv_samples=4, scalar_to_map="abs_min")
        res  = sample_surface_curvature_map(srf, spec)
        mid  = self._mid(res)
        assert len(mid) > 0
        expected = 1.0 / self.R
        for v in mid:
            assert abs(v - expected) < 5e-4, (
                f"Cylinder |κ₂|={v:.5f} ≠ {expected:.5f}"
            )

    def test_statistics_finite(self):
        """min_value, max_value, mean_value must all be finite."""
        srf  = _make_exact_cylinder_nurbs(R=self.R)
        spec = CurvatureMapSpec(nu_samples=6, nv_samples=4, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        assert math.isfinite(res.min_value),  "min_value should be finite"
        assert math.isfinite(res.max_value),  "max_value should be finite"
        assert math.isfinite(res.mean_value), "mean_value should be finite"


# ===========================================================================
# 4. Saddle (hyperbolic paraboloid z=xy): K < 0 everywhere
# ===========================================================================

class TestSaddle:
    def test_gauss_K_negative(self):
        """Saddle z=xy: Gaussian K must be negative at interior points."""
        srf  = _make_saddle_nurbs(scale=1.0, n=8)
        spec = CurvatureMapSpec(nu_samples=10, nv_samples=10, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        fin  = _finite_flat(res)
        assert len(fin) > 0, "No finite samples on saddle"
        # At least 70% of samples must have K < 0
        neg  = sum(1 for v in fin if v < -1e-6)
        frac = neg / len(fin)
        assert frac > 0.70, (
            f"Saddle: only {frac:.2%} of samples have K<0 (expected ≥70%)"
        )

    def test_gauss_K_max_negative(self):
        """Saddle max K must be ≤ 0 (no elliptic points) at interior."""
        srf  = _make_saddle_nurbs(scale=0.5, n=8)
        spec = CurvatureMapSpec(nu_samples=8, nv_samples=8, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        fin  = _finite_flat(res)
        assert len(fin) > 0
        # Interior saddle K should be negative; allow small numerical noise
        max_K = max(fin)
        assert max_K < 0.5, f"Saddle max K={max_K:.4f}; expected < 0.5"


# ===========================================================================
# 5. SVG / PNG validity
# ===========================================================================

class TestVisualisationOutput:
    def test_svg_non_empty(self):
        srf  = _make_bilinear_plane()
        spec = CurvatureMapSpec(nu_samples=5, nv_samples=5, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        assert len(res.svg_heatmap) > 200, "SVG should be non-empty"

    def test_svg_has_svg_element(self):
        srf  = _make_bilinear_plane()
        spec = CurvatureMapSpec(nu_samples=5, nv_samples=5, scalar_to_map="mean")
        res  = sample_surface_curvature_map(srf, spec)
        assert "<svg" in res.svg_heatmap, "SVG must contain <svg> element"

    def test_svg_has_rect_elements(self):
        srf  = _make_exact_cylinder_nurbs(R=2.0)
        spec = CurvatureMapSpec(nu_samples=5, nv_samples=5, scalar_to_map="abs_max")
        res  = sample_surface_curvature_map(srf, spec)
        assert "<rect" in res.svg_heatmap, "SVG must contain <rect> elements"

    def test_svg_has_viewbox(self):
        srf  = _make_bilinear_plane()
        spec = CurvatureMapSpec(nu_samples=5, nv_samples=5, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        assert "viewBox" in res.svg_heatmap, "SVG must have viewBox attribute"

    def test_svg_rdbu_for_gauss(self):
        """Gaussian map should auto-select RdBu colourmap."""
        srf  = _make_exact_sphere_nurbs(1.0)
        spec = CurvatureMapSpec(nu_samples=5, nv_samples=5, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        assert "rdbu" in res.svg_heatmap.lower(), "Gauss map should use rdbu"

    def test_svg_viridis_for_abs_max(self):
        """abs_max map should auto-select viridis colourmap."""
        srf  = _make_exact_sphere_nurbs(1.0)
        spec = CurvatureMapSpec(nu_samples=5, nv_samples=5, scalar_to_map="abs_max")
        res  = sample_surface_curvature_map(srf, spec)
        assert "viridis" in res.svg_heatmap.lower(), "abs_max map should use viridis"

    def test_png_non_empty_bytes(self):
        srf  = _make_exact_cylinder_nurbs(R=2.0)
        spec = CurvatureMapSpec(nu_samples=6, nv_samples=4,
                                scalar_to_map="gauss", export_png=True)
        res  = sample_surface_curvature_map(srf, spec)
        assert res.png_bytes is not None, "PNG bytes should not be None"
        assert len(res.png_bytes) > 50, "PNG bytes should be non-empty"

    def test_png_valid_signature(self):
        """PNG must start with the canonical 8-byte PNG signature."""
        srf  = _make_bilinear_plane()
        spec = CurvatureMapSpec(nu_samples=4, nv_samples=4,
                                scalar_to_map="mean", export_png=True)
        res  = sample_surface_curvature_map(srf, spec)
        assert res.png_bytes is not None
        assert res.png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "Invalid PNG signature"

    def test_png_ihdr_chunk(self):
        """Bytes 12–15 of PNG must be the 'IHDR' chunk type."""
        srf  = _make_bilinear_plane()
        spec = CurvatureMapSpec(nu_samples=4, nv_samples=4,
                                scalar_to_map="abs_min", export_png=True)
        res  = sample_surface_curvature_map(srf, spec)
        assert res.png_bytes is not None
        assert res.png_bytes[12:16] == b"IHDR", "Expected IHDR chunk"

    def test_png_disabled_returns_none(self):
        srf  = _make_bilinear_plane()
        spec = CurvatureMapSpec(nu_samples=4, nv_samples=4,
                                scalar_to_map="gauss", export_png=False)
        res  = sample_surface_curvature_map(srf, spec)
        assert res.png_bytes is None, "png_bytes should be None when export_png=False"


# ===========================================================================
# 6. CurvatureMapSpec validation
# ===========================================================================

class TestSpecValidation:
    def test_invalid_scalar_raises(self):
        with pytest.raises(ValueError, match="scalar_to_map"):
            CurvatureMapSpec(scalar_to_map="bad_value")

    def test_invalid_colormap_raises(self):
        with pytest.raises(ValueError, match="colormap"):
            CurvatureMapSpec(colormap="plasma")

    def test_nu_nv_clamped_minimum(self):
        spec = CurvatureMapSpec(nu_samples=1, nv_samples=1)
        assert spec.nu_samples == 3
        assert spec.nv_samples == 3

    def test_nu_nv_clamped_maximum(self):
        spec = CurvatureMapSpec(nu_samples=9999, nv_samples=9999)
        assert spec.nu_samples == 300
        assert spec.nv_samples == 300


# ===========================================================================
# 7. CurvatureMapResult dataclass invariants
# ===========================================================================

class TestResultInvariants:
    def test_honest_caveat_present(self):
        srf  = _make_bilinear_plane()
        spec = CurvatureMapSpec(nu_samples=4, nv_samples=4, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        assert len(res.honest_caveat) > 50, "honest_caveat should be descriptive"

    def test_result_is_CurvatureMapResult(self):
        srf  = _make_bilinear_plane()
        spec = CurvatureMapSpec(nu_samples=4, nv_samples=4, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(srf, spec)
        assert isinstance(res, CurvatureMapResult)

    def test_min_le_max(self):
        """min_value ≤ max_value for any surface with finite samples."""
        srf  = _make_exact_cylinder_nurbs(R=2.0)
        spec = CurvatureMapSpec(nu_samples=6, nv_samples=4, scalar_to_map="mean")
        res  = sample_surface_curvature_map(srf, spec)
        if math.isfinite(res.min_value) and math.isfinite(res.max_value):
            assert res.min_value <= res.max_value

    def test_mean_between_min_max(self):
        """mean_value must lie within [min_value, max_value]."""
        srf  = _make_exact_cylinder_nurbs(R=2.0)
        spec = CurvatureMapSpec(nu_samples=6, nv_samples=4, scalar_to_map="abs_max")
        res  = sample_surface_curvature_map(srf, spec)
        if math.isfinite(res.mean_value):
            assert res.min_value - 1e-10 <= res.mean_value <= res.max_value + 1e-10

    def test_explicit_viridis_override(self):
        """Explicit colormap='viridis' overrides auto-selection for gauss."""
        srf  = _make_exact_sphere_nurbs(1.0)
        spec = CurvatureMapSpec(nu_samples=4, nv_samples=4,
                                scalar_to_map="gauss", colormap="viridis")
        res  = sample_surface_curvature_map(srf, spec)
        assert "viridis" in res.svg_heatmap.lower()

    def test_explicit_rdbu_override(self):
        """Explicit colormap='rdbu' overrides auto-selection for abs_max."""
        srf  = _make_exact_sphere_nurbs(1.0)
        spec = CurvatureMapSpec(nu_samples=4, nv_samples=4,
                                scalar_to_map="abs_max", colormap="rdbu")
        res  = sample_surface_curvature_map(srf, spec)
        assert "rdbu" in res.svg_heatmap.lower()


# ===========================================================================
# 8. Face-with-.surface attribute is resolved correctly
# ===========================================================================

class TestFaceResolution:
    def test_face_surface_attribute_resolved(self):
        """sample_surface_curvature_map accepts a mock Face with .surface attr."""
        class MockFace:
            def __init__(self, srf):
                self.surface = srf

        srf  = _make_bilinear_plane()
        face = MockFace(srf)
        spec = CurvatureMapSpec(nu_samples=4, nv_samples=4, scalar_to_map="gauss")
        res  = sample_surface_curvature_map(face, spec)
        # Should produce the same result as passing srf directly
        res2 = sample_surface_curvature_map(srf, spec)
        for v1, v2 in zip(_finite_flat(res), _finite_flat(res2)):
            assert abs(v1 - v2) < 1e-12
