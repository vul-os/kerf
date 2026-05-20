"""
test_conditioning_audit.py
==========================
GK-69 — Numerical-conditioning audit of Newton solvers.

Oracle contract
---------------
1. Ill-conditioned / tangent-intersection cases either:
   (a) converge to the correct point (residual < generous tolerance), OR
   (b) return the structured sentinel (None / empty list / empty dict).
   They NEVER diverge to ±inf/NaN and NEVER raise.

2. Well-conditioned cases produce the same results as before (regression
   guard on all existing intersection / inversion contracts).

Hermetic: pure Python + NumPy only, no OCCT, no network, no database.

Covered solvers
---------------
* _newton_curve_surface   (intersection.py) — tangent-grazing line/surface
* _newton_surf_surf_point (intersection.py) — near-tangent plane/plane SSI
* _newton_curve_curve     (intersection.py) — nearly-parallel curves
* _newton_surface         (inversion.py)    — degenerate patch (collapsed u-row)
* _newton_curve           (inversion.py, via closest_point_curve) — cusped pt
* closest_point_surface   (inversion.py)    — pole / degenerate surface patch
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, NurbsSurface
from kerf_cad_core.geom.intersection import (
    _newton_curve_surface,
    _newton_surf_surf_point,
    _newton_curve_curve,
    _COND_THRESHOLD,
    curve_surface_intersect,
    surface_surface_intersect,
    curve_curve_intersect,
    _surf_eval,
    _curve_eval,
)
from kerf_cad_core.geom.inversion import (
    closest_point_curve,
    closest_point_surface,
    _newton_surface,
    _surf_partials,
    _COND_THRESHOLD as _INV_COND_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Geometry factories (hermetic analytic primitives)
# ---------------------------------------------------------------------------

def make_line_curve(p0, p1) -> NurbsCurve:
    """Degree-1 NurbsCurve straight line from p0 to p1."""
    cp = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=cp, knots=knots)


def make_flat_surface_xy(
    x0=0.0, x1=1.0, y0=0.0, y1=1.0, z=0.0, nu=3, nv=3
) -> NurbsSurface:
    """Bilinear flat patch in the z=const plane."""
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [
                x0 + (x1 - x0) * i / (nu - 1),
                y0 + (y1 - y0) * j / (nv - 1),
                z,
            ]

    def _k(n):
        inner = max(0, n - 2)
        return np.concatenate([
            np.zeros(2),
            np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else [],
            np.ones(2),
        ])

    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=_k(nu), knots_v=_k(nv),
    )


def make_flat_surface_xz(
    x0=0.0, x1=1.0, z0=0.0, z1=1.0, y=0.0, nu=3, nv=3
) -> NurbsSurface:
    """Bilinear flat patch in the y=const plane."""
    cp = np.zeros((nu, nv, 3))
    for i in range(nu):
        for j in range(nv):
            cp[i, j] = [x0 + (x1 - x0) * i / (nu - 1), y, z0 + (z1 - z0) * j / (nv - 1)]

    def _k(n):
        inner = max(0, n - 2)
        return np.concatenate([
            np.zeros(2),
            np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else [],
            np.ones(2),
        ])

    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=_k(nu), knots_v=_k(nv),
    )


def make_degenerate_surface() -> NurbsSurface:
    """Surface with a collapsed u-row: all u=0 control points map to the same
    3-D location (pole).  This makes the Jacobian near-singular at u=0."""
    # 3x3 bilinear patch; first column is collapsed to a single point (pole).
    pole = np.array([0.5, 0.5, 0.0])
    cp = np.array([
        [pole, pole, pole],
        [[0.0, 0.0, 0.0], [0.0, 0.5, 0.0], [0.0, 1.0, 0.0]],
        [[1.0, 0.0, 0.0], [1.0, 0.5, 0.0], [1.0, 1.0, 0.0]],
    ], dtype=float)
    knots = np.array([0.0, 0.0, 0.5, 1.0, 1.0])
    return NurbsSurface(
        degree_u=1, degree_v=1,
        control_points=cp,
        knots_u=knots, knots_v=knots,
    )


# ---------------------------------------------------------------------------
# Section 1 — _COND_THRESHOLD constants are exported correctly
# ---------------------------------------------------------------------------

class TestConditionConstants:
    def test_intersection_cond_threshold_positive(self):
        assert _COND_THRESHOLD > 0

    def test_intersection_cond_threshold_finite(self):
        assert np.isfinite(_COND_THRESHOLD)

    def test_inversion_cond_threshold_positive(self):
        assert _INV_COND_THRESHOLD > 0

    def test_inversion_cond_threshold_finite(self):
        assert np.isfinite(_INV_COND_THRESHOLD)


# ---------------------------------------------------------------------------
# Section 2 — _newton_curve_surface: ill-conditioned / tangent grazing
# ---------------------------------------------------------------------------

class TestNewtonCurveSurfaceConditioning:
    """A line that grazes the z=0 plane (tangent intersection) produces
    a near-singular Jacobian because the curve tangent lies in the surface.
    The solver must not diverge or raise."""

    def _grazing_line_on_xy_plane(self):
        """Line lying exactly in the z=0 plane — the most degenerate case."""
        return make_line_curve([0.0, 0.0, 0.0], [1.0, 1.0, 0.0])

    def _xy_surface(self):
        return make_flat_surface_xy()

    def test_tangent_grazing_no_raise(self):
        """No exception on a line tangent to the surface."""
        curve = self._grazing_line_on_xy_plane()
        surf = self._xy_surface()
        # Should not raise
        result = _newton_curve_surface(curve, surf, 0.5, 0.5, 0.5)
        # Either converged or returned None — never an exception

    def test_tangent_grazing_result_is_none_or_valid(self):
        """Result is None or a valid (finite) triple."""
        curve = self._grazing_line_on_xy_plane()
        surf = self._xy_surface()
        result = _newton_curve_surface(curve, surf, 0.5, 0.5, 0.5)
        if result is not None:
            t, u, v = result
            assert np.isfinite(t)
            assert np.isfinite(u)
            assert np.isfinite(v)

    def test_tangent_grazing_no_divergence(self):
        """If result is returned, the residual is not astronomically large."""
        curve = self._grazing_line_on_xy_plane()
        surf = self._xy_surface()
        result = _newton_curve_surface(curve, surf, 0.5, 0.5, 0.5)
        if result is not None:
            t, u, v = result
            S = _surf_eval(surf, u, v)
            C = _curve_eval(curve, t)
            assert np.linalg.norm(S - C) < 1e3  # not diverged

    def test_public_api_tangent_no_raise(self):
        """Public curve_surface_intersect never raises on tangent input."""
        curve = self._grazing_line_on_xy_plane()
        surf = self._xy_surface()
        hits = curve_surface_intersect(curve, surf)
        assert isinstance(hits, list)

    def test_well_conditioned_still_converges(self):
        """Regression: a transverse (well-conditioned) intersection still works."""
        curve = make_line_curve([0.5, 0.5, -1.0], [0.5, 0.5, 1.0])
        surf = make_flat_surface_xy()
        result = _newton_curve_surface(curve, surf, 0.5, 0.5, 0.5)
        assert result is not None
        t, u, v = result
        S = _surf_eval(surf, u, v)
        C = _curve_eval(curve, t)
        assert np.linalg.norm(S - C) < 1e-4

    def test_nearly_tangent_no_nan(self):
        """A nearly-tangent line (small z component) must not produce NaN."""
        # z component 1e-8 → near-singular but not exactly
        curve = make_line_curve([0.0, 0.0, -1e-8], [1.0, 1.0, 1e-8])
        surf = make_flat_surface_xy()
        result = _newton_curve_surface(curve, surf, 0.5, 0.5, 0.5)
        if result is not None:
            t, u, v = result
            assert not np.isnan(t)
            assert not np.isnan(u)
            assert not np.isnan(v)


# ---------------------------------------------------------------------------
# Section 3 — _newton_surf_surf_point: near-tangent / identical planes
# ---------------------------------------------------------------------------

class TestNewtonSurfSurfConditioning:
    """Two identical (or nearly identical) planes produce a Jacobian J of
    rank < 3 because dpA ≈ dpB, so JJT is near-singular."""

    def test_identical_planes_no_raise(self):
        """Two identical planes — JJT = 0 — must not raise."""
        surf_a = make_flat_surface_xy()
        surf_b = make_flat_surface_xy()
        # No exception expected
        result = _newton_surf_surf_point(surf_a, surf_b, 0.5, 0.5, 0.5, 0.5)
        # Result is None or a valid 4-tuple

    def test_identical_planes_result_finite_or_none(self):
        """Result is None or contains only finite numbers."""
        surf_a = make_flat_surface_xy()
        surf_b = make_flat_surface_xy()
        result = _newton_surf_surf_point(surf_a, surf_b, 0.5, 0.5, 0.5, 0.5)
        if result is not None:
            uA, vA, uB, vB = result
            for val in (uA, vA, uB, vB):
                assert np.isfinite(val), f"Non-finite output: {val}"

    def test_nearly_tangent_planes_no_divergence(self):
        """Two planes nearly coincident (z-offset of 1e-9) — no divergence."""
        surf_a = make_flat_surface_xy(z=0.0)
        surf_b = make_flat_surface_xy(z=1e-9)
        result = _newton_surf_surf_point(surf_a, surf_b, 0.5, 0.5, 0.5, 0.5)
        if result is not None:
            uA, vA, uB, vB = result
            PA = _surf_eval(surf_a, uA, vA)
            PB = _surf_eval(surf_b, uB, vB)
            assert np.linalg.norm(PA - PB) < 1e3  # not diverged

    def test_perpendicular_planes_converges(self):
        """Regression: perpendicular planes (well-conditioned SSI) still converge."""
        surf_a = make_flat_surface_xy()
        surf_b = make_flat_surface_xz()
        result = _newton_surf_surf_point(surf_a, surf_b, 0.5, 0.0, 0.5, 0.5)
        assert result is not None
        uA, vA, uB, vB = result
        PA = _surf_eval(surf_a, uA, vA)
        PB = _surf_eval(surf_b, uB, vB)
        assert np.linalg.norm(PA - PB) < 1e-4

    def test_public_ssi_identical_no_raise(self):
        """surface_surface_intersect on identical planes never raises."""
        surf_a = make_flat_surface_xy()
        surf_b = make_flat_surface_xy()
        result = surface_surface_intersect(surf_a, surf_b)
        assert isinstance(result, dict)
        assert "ok" in result


# ---------------------------------------------------------------------------
# Section 4 — _newton_curve_curve: nearly-parallel / tangent curves
# ---------------------------------------------------------------------------

class TestNewtonCurveCurveConditioning:
    """Nearly-parallel (or fully-parallel) lines produce a near-rank-1 Jacobian
    J = [dA/dt, -dB/dt]; JtJ becomes near-singular."""

    def test_parallel_curves_no_raise(self):
        """Fully parallel lines — no exception."""
        ca = make_line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        cb = make_line_curve([0.0, 0.1, 0.0], [1.0, 0.1, 0.0])
        result = _newton_curve_curve(ca, cb, 0.5, 0.5)
        # No exception; may be None

    def test_parallel_curves_result_finite_or_none(self):
        """Parallel lines: result is None or finite parameters."""
        ca = make_line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        cb = make_line_curve([0.0, 0.1, 0.0], [1.0, 0.1, 0.0])
        result = _newton_curve_curve(ca, cb, 0.5, 0.5)
        if result is not None:
            ta, tb = result
            assert np.isfinite(ta)
            assert np.isfinite(tb)

    def test_nearly_parallel_no_nan(self):
        """Nearly-parallel lines (small angle) produce no NaN."""
        ca = make_line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        cb = make_line_curve([0.0, 0.0, 1e-9], [1.0, 0.0, -1e-9])
        result = _newton_curve_curve(ca, cb, 0.5, 0.5)
        if result is not None:
            ta, tb = result
            assert not np.isnan(ta)
            assert not np.isnan(tb)

    def test_crossing_lines_still_converge(self):
        """Regression: crossing lines (well-conditioned) still find the hit."""
        ca = make_line_curve([0.0, 0.5, 0.0], [1.0, 0.5, 0.0])
        cb = make_line_curve([0.5, 0.0, 0.0], [0.5, 1.0, 0.0])
        result = _newton_curve_curve(ca, cb, 0.5, 0.5)
        assert result is not None
        ta, tb = result
        A = _curve_eval(ca, ta)
        B = _curve_eval(cb, tb)
        assert np.linalg.norm(A - B) < 1e-4

    def test_public_api_parallel_no_raise(self):
        """curve_curve_intersect on parallel lines never raises."""
        ca = make_line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        cb = make_line_curve([0.0, 0.1, 0.0], [1.0, 0.1, 0.0])
        hits = curve_curve_intersect(ca, cb)
        assert isinstance(hits, list)

    def test_antiparallel_no_raise(self):
        """Anti-parallel lines (same direction reversed) — no exception."""
        ca = make_line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        cb = make_line_curve([1.0, 0.0, 0.0], [0.0, 0.0, 0.0])
        result = _newton_curve_curve(ca, cb, 0.5, 0.5)
        if result is not None:
            ta, tb = result
            assert np.isfinite(ta) and np.isfinite(tb)


# ---------------------------------------------------------------------------
# Section 5 — _newton_surface (inversion.py): degenerate / pole patch
# ---------------------------------------------------------------------------

class TestNewtonSurfaceInversionConditioning:
    """Point inversion on a surface with a degenerate u-row (pole) where
    Su ≈ 0; the Jacobian [[j11, j12], [j12, j22]] is near-singular."""

    def test_degenerate_surface_no_raise(self):
        """closest_point_surface on a pole-degenerate surface never raises."""
        surf = make_degenerate_surface()
        P = np.array([0.5, 0.5, 0.0])
        # No exception
        result = closest_point_surface(surf, P)
        assert len(result) == 4  # (u, v, point, dist)

    def test_degenerate_surface_result_finite(self):
        """All outputs are finite on a degenerate surface patch."""
        surf = make_degenerate_surface()
        P = np.array([0.5, 0.5, 0.0])
        u, v, pt, dist = closest_point_surface(surf, P)
        assert np.isfinite(u)
        assert np.isfinite(v)
        assert np.all(np.isfinite(pt))
        assert np.isfinite(dist)

    def test_degenerate_surface_dist_nonnegative(self):
        """Distance must be >= 0 even for degenerate input."""
        surf = make_degenerate_surface()
        P = np.array([0.5, 0.5, 0.0])
        _, _, _, dist = closest_point_surface(surf, P)
        assert dist >= 0.0

    def test_flat_surface_inversion_unchanged(self):
        """Regression: flat surface inversion (well-conditioned) returns correct foot."""
        surf = make_flat_surface_xy()
        P = np.array([0.5, 0.5, 1.0])  # directly above centre
        u, v, pt, dist = closest_point_surface(surf, P)
        assert abs(pt[2]) < 1e-6   # foot lies on z=0
        assert abs(pt[0] - 0.5) < 0.05
        assert abs(pt[1] - 0.5) < 0.05
        assert abs(dist - 1.0) < 1e-4

    def test_ill_conditioned_2x2_system_lstsq_fallback(self):
        """Directly test _newton_surface with a collapsed-Su scenario via the
        degenerate patch — it should return a finite (u, v, dist) triple."""
        surf = make_degenerate_surface()
        u_min, u_max = 0.0, 1.0
        v_min, v_max = 0.0, 1.0
        P = np.array([0.3, 0.7, 0.0])
        # Seed near the pole (u ~0), where Su → 0
        u0, v0 = 0.01, 0.5
        u_out, v_out, dist = _newton_surface(
            surf, P, u0, v0, u_min, u_max, v_min, v_max, tol=1e-8
        )
        assert np.isfinite(u_out)
        assert np.isfinite(v_out)
        assert np.isfinite(dist)
        assert dist >= 0.0


# ---------------------------------------------------------------------------
# Section 6 — closest_point_curve: cusped / zero-tangent curve
# ---------------------------------------------------------------------------

class TestClosestPointCurveConditioning:
    """A degenerate curve where the control points are all coincident (zero
    tangent everywhere) exercises the c1n < _EPS guard in _newton_curve."""

    def _zero_length_curve(self):
        """Degree-2 curve with all control points at the origin → C'(t) ≡ 0."""
        cp = np.zeros((3, 3))
        knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
        return NurbsCurve(degree=2, control_points=cp, knots=knots)

    def test_zero_length_curve_no_raise(self):
        """closest_point_curve on a zero-length curve never raises."""
        curve = self._zero_length_curve()
        P = np.array([1.0, 0.0, 0.0])
        t, pt, d = closest_point_curve(curve, P)
        # Just no exception; result can be anything finite

    def test_zero_length_curve_result_finite(self):
        """All outputs are finite for a zero-length (degenerate) curve."""
        curve = self._zero_length_curve()
        P = np.array([1.0, 0.0, 0.0])
        t, pt, d = closest_point_curve(curve, P)
        assert np.isfinite(t)
        assert np.all(np.isfinite(pt))
        assert np.isfinite(d)
        assert d >= 0.0

    def test_zero_length_curve_distance_correct(self):
        """Distance from a zero-length curve (collapsed to origin) is |P|."""
        curve = self._zero_length_curve()
        P = np.array([3.0, 4.0, 0.0])
        _, _, d = closest_point_curve(curve, P)
        assert abs(d - 5.0) < 1e-6

    def test_regular_curve_inversion_unchanged(self):
        """Regression: normal line segment inversion still returns exact foot."""
        curve = make_line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        P = np.array([0.3, 0.5, 0.0])
        t, pt, d = closest_point_curve(curve, P)
        assert abs(pt[0] - 0.3) < 1e-4
        assert abs(pt[1]) < 1e-4
        assert abs(d - 0.5) < 1e-4


# ---------------------------------------------------------------------------
# Section 7 — No-diverge guarantee: ill-conditioned inputs never produce inf
# ---------------------------------------------------------------------------

class TestNoDivergenceGuarantee:
    """Cross-cutting tests that ill-conditioned inputs produce only finite
    outputs from all three public intersection functions."""

    def test_curve_surface_intersect_tangent_no_inf(self):
        """Public CSI on a tangent line produces finite hits (if any)."""
        curve = make_line_curve([0.0, 0.5, 0.0], [1.0, 0.5, 0.0])
        surf = make_flat_surface_xy()  # curve in the surface plane
        hits = curve_surface_intersect(curve, surf)
        for h in hits:
            assert np.isfinite(h["t"])
            assert np.isfinite(h["u"])
            assert np.isfinite(h["v"])
            for c in h["point"]:
                assert np.isfinite(c)

    def test_ssi_tangent_planes_no_inf(self):
        """Public SSI on near-tangent planes produces finite branch points."""
        surf_a = make_flat_surface_xy(z=0.0)
        surf_b = make_flat_surface_xy(z=1e-8)
        result = surface_surface_intersect(surf_a, surf_b)
        assert isinstance(result, dict)
        for branch in result.get("branches", []):
            for pt in branch.get("points", []):
                for c in pt:
                    assert np.isfinite(c), f"Non-finite branch point component: {c}"

    def test_curve_curve_parallel_no_inf(self):
        """Public CCI on parallel lines produces finite hits (if any)."""
        ca = make_line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        cb = make_line_curve([0.0, 1e-8, 0.0], [1.0, 1e-8, 0.0])
        hits = curve_curve_intersect(ca, cb)
        for h in hits:
            assert np.isfinite(h["ta"])
            assert np.isfinite(h["tb"])
            for c in h["point"]:
                assert np.isfinite(c)

    def test_inversion_degenerate_patch_no_inf(self):
        """closest_point_surface on a degenerate patch produces finite output."""
        surf = make_degenerate_surface()
        for P in [
            np.array([0.0, 0.0, 0.0]),
            np.array([0.5, 0.5, 1.0]),
            np.array([1.0, 1.0, -1.0]),
        ]:
            u, v, pt, dist = closest_point_surface(surf, P)
            assert np.isfinite(u), f"u not finite for P={P}"
            assert np.isfinite(v), f"v not finite for P={P}"
            assert np.all(np.isfinite(pt)), f"pt not finite for P={P}"
            assert np.isfinite(dist), f"dist not finite for P={P}"


# ---------------------------------------------------------------------------
# Section 8 — Regression: well-conditioned cases unchanged
# ---------------------------------------------------------------------------

class TestWellConditionedRegression:
    """Ensure that the condition-number guards do NOT affect well-conditioned
    (non-degenerate) Newton solves — all existing contracts must hold."""

    def test_vertical_line_pierces_xy_plane(self):
        """Line through (0.5, 0.5, -1) to (0.5, 0.5, 1) hits z=0 at (0.5, 0.5, 0)."""
        curve = make_line_curve([0.5, 0.5, -1.0], [0.5, 0.5, 1.0])
        surf = make_flat_surface_xy()
        hits = curve_surface_intersect(curve, surf)
        assert len(hits) >= 1
        hit = min(hits, key=lambda h: abs(h["point"][2]))
        assert abs(hit["point"][0] - 0.5) < 0.01
        assert abs(hit["point"][1] - 0.5) < 0.01
        assert abs(hit["point"][2]) < 0.01

    def test_perpendicular_planes_have_branch(self):
        """Two perpendicular planes always produce at least one branch."""
        surf_a = make_flat_surface_xy()
        surf_b = make_flat_surface_xz()
        result = surface_surface_intersect(surf_a, surf_b)
        assert result["ok"]
        assert result["branch_count"] >= 1

    def test_crossing_lines_produce_one_hit(self):
        """Two crossing lines give exactly one hit near the expected point."""
        ca = make_line_curve([0.0, 0.5, 0.0], [1.0, 0.5, 0.0])
        cb = make_line_curve([0.5, 0.0, 0.0], [0.5, 1.0, 0.0])
        hits = curve_curve_intersect(ca, cb)
        assert len(hits) >= 1
        pt = hits[0]["point"]
        assert abs(pt[0] - 0.5) < 0.01
        assert abs(pt[1] - 0.5) < 0.01

    def test_flat_surface_inversion_foot_perpendicular(self):
        """Foot of projection onto flat surface is orthogonal to both partials."""
        surf = make_flat_surface_xy()
        P = np.array([0.5, 0.5, 1.0])
        u, v, pt, dist = closest_point_surface(surf, P)
        r = pt - P
        # _surf_partials in inversion.py returns (S, Su, Sv, Suu, Suv, Svv)
        _S, du, dv, *_ = _surf_partials(surf, u, v)
        assert abs(float(np.dot(r, du))) < 1e-4
        assert abs(float(np.dot(r, dv))) < 1e-4

    def test_line_inversion_foot_correct(self):
        """Closest point on a line from (0,0,0)→(1,0,0) to P=(0.7, 0.3, 0) is (0.7, 0, 0)."""
        curve = make_line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        P = np.array([0.7, 0.3, 0.0])
        t, pt, d = closest_point_curve(curve, P)
        assert abs(pt[0] - 0.7) < 1e-4
        assert abs(pt[1]) < 1e-4
        assert abs(d - 0.3) < 1e-4
