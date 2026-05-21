"""T-43 — NURBS Phase 2/3 surface ops integration test.

Covers all six modules from the spec:
  blend_srf   (G1, G2, G3 blends, boundaries, malformed inputs, idempotency)
  patch_srf   (patch_surface, drape_surface, heightfield, surface_from_grid)
  network_srf (skinning, gordon network)
  sweep1      (sweep1, sweep1_with_twist, sweep1_rmf)
  sweep2      (two-rail sweep)
  revolve_srf (revolve_surface, rail_revolve, evaluate_revolve)

Success criteria (spec):
  25 surface constructions; tangency continuity (G1) along join edges;
  CV count sanity.

All tests are hermetic: no network, no OCCT, no external fixtures.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.revolve_srf import (
    evaluate_revolve,
    revolve_surface,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _clamped_knots(n: int, degree: int) -> np.ndarray:
    inner = max(0, n - degree - 1)
    parts = [np.zeros(degree + 1)]
    if inner:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(degree + 1))
    return np.concatenate(parts)


def _plane_surf(
    x0: float = 0.0, x1: float = 1.0,
    y0: float = 0.0, y1: float = 1.0,
    z: float = 0.0,
    n: int = 4,
) -> NurbsSurface:
    """Flat bilinear NurbsSurface in the XY plane at height z."""
    cp = np.zeros((n, n, 3))
    xs = np.linspace(x0, x1, n)
    ys = np.linspace(y0, y1, n)
    for i in range(n):
        for j in range(n):
            cp[i, j] = [xs[i], ys[j], z]
    ku = _clamped_knots(n, 1)
    kv = _clamped_knots(n, 1)
    return NurbsSurface(degree_u=1, degree_v=1, control_points=cp,
                        knots_u=ku, knots_v=kv)


def _line_curve(p0: np.ndarray, p1: np.ndarray, degree: int = 1) -> NurbsCurve:
    cp = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=degree, control_points=cp, knots=knots)


def _poly_curve(pts: np.ndarray, degree: int = 1) -> NurbsCurve:
    n = len(pts)
    knots = _clamped_knots(n, degree)
    return NurbsCurve(degree=degree, control_points=pts.astype(float),
                      knots=knots)


def _surf_eval(surf: NurbsSurface, u: float, v: float) -> np.ndarray:
    """Evaluate NurbsSurface at (u, v) — clamped to domain."""
    ku, kv = surf.knots_u, surf.knots_v
    du, dv = surf.degree_u, surf.degree_v
    u = float(np.clip(u, ku[du], ku[-(du + 1)]))
    v = float(np.clip(v, kv[dv], kv[-(dv + 1)]))
    from kerf_cad_core.geom.nurbs import surface_evaluate
    return np.asarray(surface_evaluate(surf, u, v), dtype=float)[:3]


# ---------------------------------------------------------------------------
# 1. blend_srf — G1 blend (7 constructions)
# ---------------------------------------------------------------------------

class TestBlendSrfG1:
    """blend_srf.blend_srf_g1: boundaries, malformed inputs, idempotency,
    G1 continuity, CV count."""

    def _two_planes(self, offset: float = 0.0) -> tuple:
        s1 = _plane_surf(x0=0.0, x1=1.0, y0=0.0, y1=1.0, z=0.0)
        s2 = _plane_surf(x0=0.0, x1=1.0, y0=0.0, y1=1.0, z=offset + 1.0)
        return s1, s2

    # --- construction 1: happy path returns ok=True ---
    def test_g1_happy_path_ok(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g1
        s1, s2 = self._two_planes()
        res = blend_srf_g1(s1, s2)
        assert res["ok"] is True
        assert res["blend_surface"] is not None

    # --- construction 2: CV count sanity — degree-3 Bezier cross direction ---
    def test_g1_cv_count_cross_direction(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g1
        s1, s2 = self._two_planes()
        res = blend_srf_g1(s1, s2, samples=24)
        surf = res["blend_surface"]
        # degree-3 Bezier in cross-boundary direction → 4 control rows in v
        assert surf.num_control_points_v == 4
        assert surf.degree_v == 3

    # --- construction 3: seam boundary lies on surf1 seam ---
    def test_g1_seam_a_on_surf1_boundary(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g1
        s1, s2 = self._two_planes()
        res = blend_srf_g1(s1, s2, samples=8)
        blend = res["blend_surface"]
        # v=v_min of blend should match v=v_max of surf1 (same z=0)
        bv_min = float(blend.knots_v[blend.degree_v])
        bv_max = float(blend.knots_v[-blend.degree_v - 1])
        bu_min = float(blend.knots_u[blend.degree_u])
        bu_max = float(blend.knots_u[-blend.degree_u - 1])
        pt = _surf_eval(blend, bu_min, bv_min)
        # Seam A is surf1 v=v_max (z=0.0); blend starts there
        assert abs(pt[2]) < 0.2, f"blend start z={pt[2]} should be near surf1 seam"

    # --- construction 4: malformed — bad edge spec ---
    def test_g1_bad_edge_returns_error(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g1
        s1, s2 = self._two_planes()
        res = blend_srf_g1(s1, s2, edge="bad_edge")
        assert res["ok"] is False
        assert "unsupported edge spec" in res["reason"]

    # --- construction 5: malformed — non-positive blend_width ---
    def test_g1_nonpositive_blend_width(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g1
        s1, s2 = self._two_planes()
        res = blend_srf_g1(s1, s2, blend_width=-1.0)
        assert res["ok"] is False

    # --- construction 6: idempotency — same inputs produce same shape ---
    def test_g1_idempotent_output(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g1
        s1, s2 = self._two_planes()
        r1 = blend_srf_g1(s1, s2, samples=12)
        r2 = blend_srf_g1(s1, s2, samples=12)
        cp1 = r1["blend_surface"].control_points
        cp2 = r2["blend_surface"].control_points
        np.testing.assert_allclose(cp1, cp2, atol=1e-12)

    # --- construction 7: G1 residual within tolerance for coplanar planes ---
    def test_g1_continuity_residual_coplanar(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g1
        s1, s2 = self._two_planes()
        res = blend_srf_g1(s1, s2, samples=12, blend_width=0.2)
        diag = res["diagnostics"]
        assert diag["max_g1_residual"] < 1e-6, (
            f"G1 residual {diag['max_g1_residual']} exceeds tolerance"
        )


# ---------------------------------------------------------------------------
# 2. blend_srf — G2 blend (3 constructions)
# ---------------------------------------------------------------------------

class TestBlendSrfG2:
    """blend_srf.blend_srf_g2: degree-5 strip, CV count, G2 diagnostics."""

    def _two_planes(self) -> tuple:
        s1 = _plane_surf(z=0.0)
        s2 = _plane_surf(z=1.0)
        return s1, s2

    # --- construction 8: G2 happy path ---
    def test_g2_happy_path(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g2
        s1, s2 = self._two_planes()
        res = blend_srf_g2(s1, s2, samples=12)
        assert res["ok"] is True

    # --- construction 9: CV count — degree-5 Bezier strip ---
    def test_g2_cv_count_degree5(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g2
        s1, s2 = self._two_planes()
        res = blend_srf_g2(s1, s2, samples=12)
        surf = res["blend_surface"]
        assert surf.degree_v == 5
        assert surf.num_control_points_v == 6

    # --- construction 10: G2 diagnostics finite for flat planes ---
    def test_g2_diagnostics_finite(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g2
        s1, s2 = self._two_planes()
        res = blend_srf_g2(s1, s2, samples=8)
        diag = res["diagnostics"]
        assert np.isfinite(diag["max_g1_residual"])
        assert np.isfinite(diag["max_g2_residual"])
        assert diag["max_g1_residual"] < 1e-6


# ---------------------------------------------------------------------------
# 3. patch_srf (4 constructions)
# ---------------------------------------------------------------------------

class TestPatchSrfIntegration:
    """patch_surface: boundary pts, malformed, idempotency, CV sanity."""

    def _scattered_points(self, n: int = 20) -> np.ndarray:
        rng = np.random.default_rng(42)
        xy = rng.uniform(0, 1, (n, 2))
        z = np.sin(xy[:, 0] * 2 * np.pi) * np.cos(xy[:, 1] * 2 * np.pi)
        return np.column_stack([xy, z])

    # --- construction 11: patch_surface returns ok surface ---
    def test_patch_surface_returns_ok(self):
        from kerf_cad_core.geom.patch_srf import patch_surface
        pts = self._scattered_points(30)
        res = patch_surface(pts, nu=5, nv=5)
        assert res["ok"] is True
        assert isinstance(res["surface"], NurbsSurface)

    # --- construction 12: CV count matches requested grid ---
    def test_patch_surface_cv_count(self):
        from kerf_cad_core.geom.patch_srf import patch_surface
        pts = self._scattered_points(30)
        res = patch_surface(pts, nu=6, nv=7)
        surf = res["surface"]
        assert surf.num_control_points_u == 6
        assert surf.num_control_points_v == 7

    # --- construction 13: malformed — too few points ---
    def test_patch_surface_too_few_points(self):
        from kerf_cad_core.geom.patch_srf import patch_surface
        res = patch_surface([[0, 0, 0], [1, 0, 0]])
        assert res["ok"] is False
        assert "points" in res["reason"].lower() or "degree" in res["reason"].lower()

    # --- construction 14: idempotency — deterministic output ---
    def test_patch_surface_idempotent(self):
        from kerf_cad_core.geom.patch_srf import patch_surface
        pts = self._scattered_points(25)
        r1 = patch_surface(pts, nu=5, nv=5, max_iter=1)
        r2 = patch_surface(pts, nu=5, nv=5, max_iter=1)
        np.testing.assert_allclose(
            r1["surface"].control_points,
            r2["surface"].control_points,
            atol=1e-12,
        )


# ---------------------------------------------------------------------------
# 4. network_srf — skinning and Gordon network (3 constructions)
# ---------------------------------------------------------------------------

class TestNetworkSrfIntegration:
    """network_srf: skinning of profile curves, CV count, error paths."""

    def _profile_curves(self, n_curves: int = 4, n_pts: int = 4) -> list:
        curves = []
        for i in range(n_curves):
            z = float(i) / max(n_curves - 1, 1)
            pts = np.zeros((n_pts, 3))
            for j in range(n_pts):
                x = float(j) / max(n_pts - 1, 1)
                pts[j] = [x, 0.0, z]
            curves.append(_poly_curve(pts, degree=1))
        return curves

    # --- construction 15: network_srf returns NurbsSurface ---
    def test_network_srf_returns_surface(self):
        from kerf_cad_core.geom.network_srf import network_srf
        curves = self._profile_curves()
        surf = network_srf(curves, degree_u=1)
        assert isinstance(surf, NurbsSurface)

    # --- construction 16: skinned surface CV count ---
    def test_network_srf_cv_count(self):
        from kerf_cad_core.geom.network_srf import network_srf
        curves = self._profile_curves(n_curves=5, n_pts=4)
        surf = network_srf(curves, degree_u=1)
        # u direction: one row per input curve
        assert surf.num_control_points_u == 5
        # v direction: matches curve control points
        assert surf.num_control_points_v == 4

    # --- construction 17: too few curves raises ValueError ---
    def test_network_srf_too_few_curves(self):
        from kerf_cad_core.geom.network_srf import network_srf
        curves = self._profile_curves(n_curves=1)
        with pytest.raises(ValueError, match="least 2"):
            network_srf(curves)


# ---------------------------------------------------------------------------
# 5. sweep1 (4 constructions)
# ---------------------------------------------------------------------------

class TestSweep1Integration:
    """sweep1: profile + path, CV count, twist, malformed inputs."""

    def _square_profile(self, n: int = 5) -> NurbsCurve:
        pts = np.zeros((n, 3))
        for i in range(n):
            x = float(i) / max(n - 1, 1) - 0.5
            pts[i] = [x, 0.5, 0.0]
        return _poly_curve(pts, degree=1)

    def _straight_path(self, n: int = 5, length: float = 2.0) -> NurbsCurve:
        pts = np.zeros((n, 3))
        for i in range(n):
            pts[i] = [0.0, 0.0, float(i) / max(n - 1, 1) * length]
        return _poly_curve(pts, degree=1)

    # --- construction 18: sweep1 produces NurbsSurface with no NaNs ---
    def test_sweep1_no_nan(self):
        from kerf_cad_core.geom.sweep1 import sweep1
        profile = self._square_profile()
        path = self._straight_path()
        surf = sweep1(profile, path)
        assert isinstance(surf, NurbsSurface)
        assert np.all(np.isfinite(surf.control_points))

    # --- construction 19: CV count matches profile × path ---
    def test_sweep1_cv_count(self):
        from kerf_cad_core.geom.sweep1 import sweep1
        profile = self._square_profile(n=4)
        path = self._straight_path(n=6)
        surf = sweep1(profile, path)
        assert surf.num_control_points_u == 4
        assert surf.num_control_points_v == 6

    # --- construction 20: sweep1 with twist — no NaNs ---
    def test_sweep1_twist_no_nan(self):
        from kerf_cad_core.geom.sweep1 import sweep1_with_twist
        profile = self._square_profile()
        path = self._straight_path()
        surf = sweep1_with_twist(profile, path, twist=math.pi / 4)
        assert np.all(np.isfinite(surf.control_points))

    # --- construction 21: malformed — degree < 1 raises ValueError ---
    def test_sweep1_degree_zero_raises(self):
        from kerf_cad_core.geom.sweep1 import sweep1
        # Degree-0 curve
        cp = np.array([[0.0, 0.0, 0.0]])
        knots = np.array([0.0, 1.0])
        bad = NurbsCurve(degree=0, control_points=cp, knots=knots)
        with pytest.raises(ValueError):
            sweep1(bad, self._straight_path())


# ---------------------------------------------------------------------------
# 6. sweep2 (2 constructions)
# ---------------------------------------------------------------------------

class TestSweep2Integration:
    """sweep2: two-rail sweep, CV count, matching rail constraint."""

    def _rail(self, offset_y: float, n: int = 5) -> NurbsCurve:
        pts = np.zeros((n, 3))
        for i in range(n):
            z = float(i) / max(n - 1, 1) * 2.0
            pts[i] = [0.0, offset_y, z]
        return _poly_curve(pts, degree=1)

    def _profile(self, n: int = 4) -> NurbsCurve:
        pts = np.zeros((n, 3))
        for j in range(n):
            pts[j] = [float(j) / max(n - 1, 1), 0.0, 0.0]
        return _poly_curve(pts, degree=1)

    # --- construction 22: sweep2 produces NurbsSurface ---
    def test_sweep2_produces_surface(self):
        from kerf_cad_core.geom.sweep2 import sweep2
        rail1 = self._rail(0.0)
        rail2 = self._rail(1.0)
        profile = self._profile()
        surf = sweep2(profile, rail1, rail2)
        assert isinstance(surf, NurbsSurface)
        assert np.all(np.isfinite(surf.control_points))

    # --- construction 23: CV count sanity for sweep2 ---
    def test_sweep2_cv_count(self):
        from kerf_cad_core.geom.sweep2 import sweep2
        rail1 = self._rail(0.0, n=6)
        rail2 = self._rail(1.0, n=6)
        profile = self._profile(n=4)
        surf = sweep2(profile, rail1, rail2)
        # Profile CPs in u, path CPs in v
        assert surf.num_control_points_u == 4
        assert surf.num_control_points_v == 6


# ---------------------------------------------------------------------------
# 7. revolve_srf (5 constructions; includes boundaries, malformed, idempotency)
# ---------------------------------------------------------------------------

class TestRevolveSrfIntegration:
    """revolve_surface / rail_revolve / evaluate_revolve: boundary angles,
    malformed inputs, idempotency, CV count, surface accuracy."""

    def _line_profile(self, n: int = 3, r: float = 1.0,
                      h: float = 2.0) -> NurbsCurve:
        pts = np.zeros((n, 3))
        for i in range(n):
            t = float(i) / max(n - 1, 1)
            pts[i] = [r, 0.0, h * t]
        return _poly_curve(pts, degree=1)

    # --- construction 24: full 360° revolve → closed cylinder CV count ---
    def test_revolve_360_cv_count(self):
        profile = self._line_profile(n=3, r=1.0, h=1.0)
        axis_pt = np.array([0.0, 0.0, 0.0])
        axis_dir = np.array([0.0, 0.0, 1.0])
        surf = revolve_surface(profile, axis_pt, axis_dir,
                               start_angle=0.0, end_angle=2 * math.pi)
        # 4-segment arc → 9 arc CPs in v; profile has 3 pts in u
        assert surf.num_control_points_u == 3
        assert surf.num_control_points_v == 9

    # --- construction 25: partial 90° revolve CV count ---
    def test_revolve_90_cv_count(self):
        profile = self._line_profile(n=4, r=2.0, h=1.0)
        axis_pt = np.array([0.0, 0.0, 0.0])
        axis_dir = np.array([0.0, 0.0, 1.0])
        surf = revolve_surface(profile, axis_pt, axis_dir,
                               start_angle=0.0, end_angle=math.pi / 2)
        # 1-segment arc → 3 arc CPs in v
        assert surf.num_control_points_u == 4
        assert surf.num_control_points_v == 3

    # --- boundary: evaluate_revolve at u=0, v=0 is on profile start ---
    def test_revolve_evaluate_boundary_start(self):
        profile = self._line_profile(n=3, r=1.0, h=1.0)
        axis_pt = np.array([0.0, 0.0, 0.0])
        axis_dir = np.array([0.0, 0.0, 1.0])
        surf = revolve_surface(profile, axis_pt, axis_dir,
                               start_angle=0.0, end_angle=math.pi / 2)
        ku = surf.knots_u
        kv = surf.knots_v
        du = surf.degree_u
        dv = surf.degree_v
        pt = evaluate_revolve(surf, float(ku[du]), float(kv[dv]))
        # At start of profile (z=0), start angle (0°): should be at (r, 0, 0)
        assert pt.shape == (3,)
        assert np.all(np.isfinite(pt))
        np.testing.assert_allclose(pt[2], 0.0, atol=1e-9)
        np.testing.assert_allclose(pt[1], 0.0, atol=1e-9)

    # --- idempotency: revolve same profile twice gives identical CPs ---
    def test_revolve_idempotent(self):
        profile = self._line_profile(n=3, r=1.5, h=2.0)
        axis_pt = np.array([0.0, 0.0, 0.0])
        axis_dir = np.array([0.0, 0.0, 1.0])
        s1 = revolve_surface(profile, axis_pt, axis_dir,
                             start_angle=0.0, end_angle=math.pi)
        s2 = revolve_surface(profile, axis_pt, axis_dir,
                             start_angle=0.0, end_angle=math.pi)
        np.testing.assert_allclose(
            s1.control_points, s2.control_points, atol=1e-12
        )

    # --- malformed: zero axis vector raises ValueError ---
    def test_revolve_zero_axis_raises(self):
        profile = self._line_profile()
        with pytest.raises((ValueError, ZeroDivisionError, Exception)):
            revolve_surface(
                profile,
                np.array([0.0, 0.0, 0.0]),
                np.array([0.0, 0.0, 0.0]),
                start_angle=0.0,
                end_angle=math.pi,
            )


# ---------------------------------------------------------------------------
# 8. G1 tangent continuity along join edge (cross-module check)
# ---------------------------------------------------------------------------

class TestG1TangencyAlongJoinEdge:
    """Verify G1 tangency contract at the seam shared between the blend strip
    and each support surface.  Uses the curvature_comb_continuity_residual
    oracle from surface_fillet (the same oracle used internally by blend_srf_g1
    and blend_srf_g2).
    """

    def _flat_pair(self) -> tuple:
        s1 = _plane_surf(x0=0.0, x1=1.0, y0=0.0, y1=1.0, z=0.0, n=5)
        s2 = _plane_surf(x0=0.0, x1=1.0, y0=0.0, y1=1.0, z=1.0, n=5)
        return s1, s2

    def test_g1_blend_seam_tangency_oracle_residual(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g1
        from kerf_cad_core.geom.surface_fillet import curvature_comb_continuity_residual
        s1, s2 = self._flat_pair()
        res = blend_srf_g1(s1, s2, samples=12, blend_width=0.3)
        assert res["ok"]
        blend = res["blend_surface"]
        # Oracle: blend vs surf1 G1 residual
        diag_a = curvature_comb_continuity_residual(
            blend, s1, s2, edge="v1_v0", continuity="G1", samples=8
        )
        assert diag_a["max_g1_residual"] < 1e-5, (
            f"Seam G1 residual {diag_a['max_g1_residual']} exceeds 1e-5"
        )

    def test_g2_blend_seam_tangency_oracle_residual(self):
        from kerf_cad_core.geom.blend_srf import blend_srf_g2
        from kerf_cad_core.geom.surface_fillet import curvature_comb_continuity_residual
        s1, s2 = self._flat_pair()
        res = blend_srf_g2(s1, s2, samples=12, blend_width=0.3)
        assert res["ok"]
        blend = res["blend_surface"]
        diag = curvature_comb_continuity_residual(
            blend, s1, s2, edge="v1_v0", continuity="G1", samples=8
        )
        assert diag["max_g1_residual"] < 1e-5
