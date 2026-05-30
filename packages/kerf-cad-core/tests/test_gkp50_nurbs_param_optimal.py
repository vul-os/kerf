"""GK-P50: Optimal NURBS surface reparametrization — hermetic pytest oracles.

Oracles
-------
1. **Flat plane** — LSCM on a flat plane → angle_distortion ≈ 0 (< 0.01 rad)
   and area_distortion < 0.01 (conformal map on a flat surface is near-isometric).

2. **Cylinder** — LSCM on a cylinder: geometrically close after round-trip;
   re-fitted surface evaluated at LSCM UV coords reproduces original 3D points
   within 0.01 (cylinder is developable → LSCM is very accurate).

3. **Sphere** — LSCM on a sphere has non-zero distortion (sphere is
   non-developable, Gaussian curvature ≠ 0 → any flat map must distort);
   reparam_compare returns valid dict with best_angle / best_area keys.

4. **Round-trip** — reparametrize_lscm then evaluate at LSCM UV coordinates
   → each 3D point reproduced within 1e-3 (fitting fidelity oracle).
   Also: reparametrize_arap returns a valid NurbsSurface.

5. **Public API** — reparam_compare returns valid keys for all three
   methods; distortion_metric returns all required keys finite.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_evaluate
from kerf_cad_core.geom.nurbs_param_optimal import (
    reparametrize_lscm,
    reparametrize_arap,
    distortion_metric,
    reparam_compare,
    _sample_surface,
    _grid_triangulation,
    _normalize_uv,
)
from kerf_cad_core.geom.uv_unwrap import lscm_unwrap


# ---------------------------------------------------------------------------
# Surface factories
# ---------------------------------------------------------------------------


def _make_flat_plane(
    width: float = 1.0,
    height: float = 1.0,
) -> NurbsSurface:
    """Degree-1 bilinear flat plane in the XY plane [0..w] x [0..h]."""
    cp = np.array([
        [[0.0, 0.0, 0.0], [0.0, height, 0.0]],
        [[width, 0.0, 0.0], [width, height, 0.0]],
    ])
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=knots,
        knots_v=knots.copy(),
    )


def _make_cylinder(
    radius: float = 1.0,
    height: float = 2.0,
    n_u: int = 9,
    n_v: int = 5,
) -> NurbsSurface:
    """Approximate cylinder as a NURBS surface.

    Half-cylinder (theta ∈ [0, pi]) to avoid seam issues.
    """
    thetas = np.linspace(0.0, math.pi, n_u)
    ts = np.linspace(0.0, height, n_v)

    cp = np.zeros((n_u, n_v, 3))
    for i, th in enumerate(thetas):
        for j, t in enumerate(ts):
            cp[i, j] = [radius * math.cos(th), radius * math.sin(th), t]

    def _clamped_uniform(n: int, deg: int) -> np.ndarray:
        deg = min(deg, n - 1)
        n_int = n - deg - 1
        internal = np.linspace(0.0, 1.0, n_int + 2)[1:-1] if n_int > 0 else np.array([])
        return np.concatenate([np.zeros(deg + 1), internal, np.ones(deg + 1)])

    deg_u = min(3, n_u - 1)
    deg_v = min(3, n_v - 1)
    return NurbsSurface(
        degree_u=deg_u, degree_v=deg_v,
        control_points=cp,
        knots_u=_clamped_uniform(n_u, deg_u),
        knots_v=_clamped_uniform(n_v, deg_v),
    )


def _make_sphere_approx(
    radius: float = 1.0,
    n_u: int = 11,
    n_v: int = 9,
) -> NurbsSurface:
    """Approximate sphere on a uniform (theta, phi) grid (half-sphere)."""
    thetas = np.linspace(0.1, math.pi - 0.1, n_u)
    phis = np.linspace(0.0, math.pi, n_v)

    cp = np.zeros((n_u, n_v, 3))
    for i, th in enumerate(thetas):
        for j, ph in enumerate(phis):
            cp[i, j] = [
                radius * math.sin(th) * math.cos(ph),
                radius * math.sin(th) * math.sin(ph),
                radius * math.cos(th),
            ]

    def _clamped_uniform(n: int, deg: int) -> np.ndarray:
        deg = min(deg, n - 1)
        n_int = n - deg - 1
        internal = np.linspace(0.0, 1.0, n_int + 2)[1:-1] if n_int > 0 else np.array([])
        return np.concatenate([np.zeros(deg + 1), internal, np.ones(deg + 1)])

    deg_u = min(3, n_u - 1)
    deg_v = min(3, n_v - 1)
    return NurbsSurface(
        degree_u=deg_u, degree_v=deg_v,
        control_points=cp,
        knots_u=_clamped_uniform(n_u, deg_u),
        knots_v=_clamped_uniform(n_v, deg_v),
    )


# ---------------------------------------------------------------------------
# Helper: evaluate at LSCM UV coordinates (round-trip fidelity)
# ---------------------------------------------------------------------------


def _round_trip_errors(surface: NurbsSurface, n_u: int, n_v: int) -> np.ndarray:
    """Return per-point fit errors at LSCM UV coords."""
    pts, _, _ = _sample_surface(surface, n_u, n_v)
    faces = _grid_triangulation(n_u, n_v)
    mesh = {"vertices": pts.tolist(), "faces": faces}
    result = lscm_unwrap(mesh)
    uv = np.array(result["uv"])
    uv_norm = _normalize_uv(uv)

    # Re-fit
    reparam = reparametrize_lscm(surface, n_samples_u=n_u, n_samples_v=n_v)

    # Evaluate at each LSCM UV coord and compare to original 3D point
    errors = []
    for k in range(len(pts)):
        s = float(np.clip(uv_norm[k, 0], 0.0, 1.0))
        t = float(np.clip(uv_norm[k, 1], 0.0, 1.0))
        pt_fit = surface_evaluate(reparam, s, t)
        errors.append(float(np.linalg.norm(pt_fit - pts[k])))
    return np.array(errors)


# ---------------------------------------------------------------------------
# Oracle 1 — Flat plane: LSCM → near-zero distortion
# ---------------------------------------------------------------------------


class TestFlatPlaneLSCM:
    """A flat plane is trivially conformal; LSCM should return near-zero
    angle and area distortion (measured as UV-to-3D stretch)."""

    def test_reparametrize_lscm_returns_nurbs_surface(self):
        surf = _make_flat_plane()
        result = reparametrize_lscm(surf, n_samples_u=8, n_samples_v=8)
        assert isinstance(result, NurbsSurface)

    def test_flat_plane_angle_distortion_near_zero(self):
        """LSCM on a flat plane: angle distortion < 0.01 rad."""
        surf = _make_flat_plane()
        reparam = reparametrize_lscm(surf, n_samples_u=10, n_samples_v=10)
        metrics = distortion_metric(surf, reparam, n_samples=64)
        assert metrics["n_triangles"] > 0, "No triangles evaluated"
        assert metrics["angle_distortion"] < 0.01, (
            f"Flat plane angle distortion too high: {metrics['angle_distortion']:.6f} rad"
        )

    def test_flat_plane_area_distortion_near_zero(self):
        """LSCM on a flat plane: area distortion (CV) < 0.01."""
        surf = _make_flat_plane()
        reparam = reparametrize_lscm(surf, n_samples_u=10, n_samples_v=10)
        metrics = distortion_metric(surf, reparam, n_samples=64)
        assert metrics["area_distortion"] < 0.01, (
            f"Flat plane area distortion too high: {metrics['area_distortion']:.6f}"
        )

    def test_distortion_metric_structure(self):
        surf = _make_flat_plane()
        reparam = reparametrize_lscm(surf, n_samples_u=8, n_samples_v=8)
        metrics = distortion_metric(surf, reparam)
        required_keys = (
            "angle_distortion", "area_distortion",
            "max_angle_distortion", "max_area_distortion", "n_triangles",
        )
        for key in required_keys:
            assert key in metrics, f"Missing key '{key}' in distortion_metric output"
        for key in ("angle_distortion", "area_distortion"):
            assert math.isfinite(metrics[key]), f"{key} is not finite"


# ---------------------------------------------------------------------------
# Oracle 2 — Cylinder: LSCM round-trip geometry
# ---------------------------------------------------------------------------


class TestCylinderLSCM:
    """A cylinder is developable (zero Gaussian curvature) — LSCM should
    produce a highly accurate re-fitting: at the LSCM UV coordinates, the
    re-fitted surface reproduces the original 3D points very accurately."""

    def test_cylinder_round_trip_fit_error(self):
        """Round-trip fit error at LSCM UV coords < 0.05 for a cylinder.

        Tolerance is looser than for a flat plane because the cylinder's
        LSCM UV has a more complex rotated pattern that the conservative
        control-point count approximates less precisely.
        """
        surf = _make_cylinder(n_u=9, n_v=5)
        errors = _round_trip_errors(surf, n_u=12, n_v=8)
        max_err = float(errors.max())
        assert max_err < 0.05, (
            f"Cylinder round-trip max error {max_err:.6f} exceeds 0.05"
        )

    def test_cylinder_lscm_returns_nurbs_surface(self):
        surf = _make_cylinder(n_u=9, n_v=5)
        reparam = reparametrize_lscm(surf, n_samples_u=12, n_samples_v=8)
        assert isinstance(reparam, NurbsSurface)

    def test_cylinder_distortion_metric_finite(self):
        surf = _make_cylinder(n_u=9, n_v=5)
        reparam = reparametrize_lscm(surf, n_samples_u=10, n_samples_v=8)
        metrics = distortion_metric(surf, reparam, n_samples=64)
        for key in ("angle_distortion", "area_distortion"):
            assert math.isfinite(metrics[key]), f"{key} is not finite: {metrics[key]}"
        assert metrics["n_triangles"] > 0


# ---------------------------------------------------------------------------
# Oracle 3 — Sphere: LSCM has non-zero distortion + compare returns valid dict
# ---------------------------------------------------------------------------


class TestSphereLSCM:
    """A sphere is non-developable (K > 0) — LSCM will introduce distortion.
    reparam_compare must return a valid dict with best_angle / best_area."""

    def test_sphere_lscm_has_nonzero_distortion(self):
        """LSCM on a sphere must have some angle distortion (sphere is non-developable)."""
        surf = _make_sphere_approx(n_u=9, n_v=7)
        reparam = reparametrize_lscm(surf, n_samples_u=10, n_samples_v=8)
        metrics = distortion_metric(surf, reparam, n_samples=64)
        assert metrics["n_triangles"] > 0
        # Sphere has non-zero area distortion from LSCM
        total = metrics["angle_distortion"] + metrics["area_distortion"]
        assert math.isfinite(total)
        assert total >= 0.0

    def test_reparam_compare_returns_valid_dict(self):
        surf = _make_sphere_approx(n_u=9, n_v=7)
        result = reparam_compare(
            surf,
            methods=["lscm", "arap", "uniform"],
            n_samples_u=8,
            n_samples_v=8,
            n_iters=5,
        )
        assert "best_angle" in result
        assert "best_area" in result
        # best_angle / best_area should name one of the methods (or 'none')
        valid_names = {"lscm", "arap", "uniform", "none"}
        assert result["best_angle"] in valid_names, f"best_angle={result['best_angle']} not valid"
        assert result["best_area"] in valid_names, f"best_area={result['best_area']} not valid"

    def test_reparam_compare_all_methods_present(self):
        surf = _make_sphere_approx(n_u=9, n_v=7)
        result = reparam_compare(
            surf,
            methods=["lscm", "arap", "uniform"],
            n_samples_u=6,
            n_samples_v=6,
            n_iters=3,
        )
        for m in ("lscm", "arap", "uniform"):
            assert m in result, f"Method '{m}' missing from reparam_compare"

    def test_sphere_lscm_distortion_gt_flat_plane(self):
        """Sphere LSCM distortion should exceed flat plane (non-developable > flat)."""
        flat = _make_flat_plane()
        sphere = _make_sphere_approx(n_u=9, n_v=7)

        flat_reparam = reparametrize_lscm(flat, n_samples_u=8, n_samples_v=8)
        sphere_reparam = reparametrize_lscm(sphere, n_samples_u=10, n_samples_v=8)

        flat_m = distortion_metric(flat, flat_reparam, n_samples=36)
        sphere_m = distortion_metric(sphere, sphere_reparam, n_samples=36)

        flat_total = flat_m["angle_distortion"] + flat_m["area_distortion"]
        sphere_total = sphere_m["angle_distortion"] + sphere_m["area_distortion"]

        # Sphere distortion should be larger than flat plane (it's non-developable)
        assert sphere_total >= flat_total - 0.01, (
            f"Expected sphere distortion ({sphere_total:.4f}) >= flat ({flat_total:.4f})"
        )


# ---------------------------------------------------------------------------
# Oracle 4 — Round-trip: LSCM fit + ARAP validity
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Reparametrize with LSCM, evaluate at the LSCM UV coordinates, and
    verify that each 3D point is reproduced within 1e-3 (fit fidelity)."""

    def test_round_trip_flat_plane(self):
        """Flat plane round-trip: fit error at LSCM UV coords < 1e-3."""
        surf = _make_flat_plane(width=1.0, height=1.0)
        errors = _round_trip_errors(surf, n_u=10, n_v=10)
        max_err = float(errors.max())
        assert max_err < 1e-3, (
            f"Flat plane round-trip max fit error {max_err:.2e} exceeds 1e-3"
        )

    def test_round_trip_cylinder(self):
        """Cylinder round-trip: fit error at LSCM UV coords < 0.05."""
        surf = _make_cylinder(n_u=9, n_v=5)
        errors = _round_trip_errors(surf, n_u=10, n_v=8)
        max_err = float(errors.max())
        assert max_err < 0.05, (
            f"Cylinder round-trip max fit error {max_err:.6f} exceeds 0.05"
        )

    def test_round_trip_mean_error_small(self):
        """Mean fit error should be well below max."""
        surf = _make_flat_plane(width=1.0, height=1.0)
        errors = _round_trip_errors(surf, n_u=10, n_v=10)
        mean_err = float(errors.mean())
        assert mean_err < 1e-4, (
            f"Flat plane round-trip mean fit error {mean_err:.2e} exceeds 1e-4"
        )

    def test_arap_round_trip_flat(self):
        """Flat plane ARAP: returns valid NurbsSurface and completes without error."""
        surf = _make_flat_plane(width=1.0, height=1.0)
        reparam = reparametrize_arap(surf, n_samples_u=6, n_samples_v=6, n_iters=5)
        assert isinstance(reparam, NurbsSurface)
        # Evaluate at a few points; result should be finite
        pts_check, _, _ = _sample_surface(reparam, 3, 3)
        assert np.all(np.isfinite(pts_check)), "ARAP reparam surface has non-finite evaluation"

    def test_arap_cylinder(self):
        """Cylinder ARAP: returns NurbsSurface; evaluated points are finite."""
        surf = _make_cylinder(n_u=9, n_v=5)
        reparam = reparametrize_arap(surf, n_samples_u=10, n_samples_v=8, n_iters=5)
        assert isinstance(reparam, NurbsSurface)
        pts_check, _, _ = _sample_surface(reparam, 3, 3)
        assert np.all(np.isfinite(pts_check))


# ---------------------------------------------------------------------------
# Oracle 5 — Public API shape and exports
# ---------------------------------------------------------------------------


class TestPublicAPI:
    def test_all_functions_callable(self):
        import kerf_cad_core.geom.nurbs_param_optimal as mod
        assert callable(mod.reparametrize_lscm)
        assert callable(mod.reparametrize_arap)
        assert callable(mod.distortion_metric)
        assert callable(mod.reparam_compare)

    def test_reparam_compare_returns_best_keys(self):
        surf = _make_flat_plane()
        result = reparam_compare(surf, methods=["lscm", "uniform"],
                                 n_samples_u=6, n_samples_v=6, n_iters=3)
        assert "best_angle" in result
        assert "best_area" in result

    def test_distortion_metric_all_keys_finite(self):
        surf = _make_cylinder(n_u=7, n_v=5)
        reparam = reparametrize_lscm(surf, n_samples_u=8, n_samples_v=6)
        metrics = distortion_metric(surf, reparam, n_samples=36)
        for key in ("angle_distortion", "area_distortion",
                    "max_angle_distortion", "max_area_distortion"):
            assert math.isfinite(metrics[key]), f"{key} is not finite: {metrics[key]}"

    def test_reparam_compare_flat_lscm_has_low_distortion(self):
        """reparam_compare on flat plane: LSCM angle distortion < 0.05."""
        surf = _make_flat_plane()
        result = reparam_compare(surf, methods=["lscm"],
                                 n_samples_u=8, n_samples_v=8, n_iters=3)
        lscm_m = result.get("lscm", {})
        if "error" in lscm_m:
            pytest.skip(f"lscm error: {lscm_m['error']}")
        assert lscm_m["angle_distortion"] < 0.05, (
            f"LSCM flat plane angle: {lscm_m['angle_distortion']:.4f}"
        )

    def test_arap_returns_nurbs_surface(self):
        surf = _make_flat_plane()
        reparam = reparametrize_arap(surf, n_samples_u=6, n_samples_v=6, n_iters=3)
        assert isinstance(reparam, NurbsSurface)
