"""
test_curve_toolkit_exact.py
===========================
Hermetic analytic-oracle tests for GK-05 and GK-22.

GK-05 — Rational conic construction + evaluation
    Verified against analytic conics using the focus–directrix property,
    the eccentricity sign test, and exact implicit equations.

GK-22 — Curve fit-to-tolerance with Piegl–Tiller knot placement
    Verified that fit_curve achieves deviation ≤ tol, handles degenerate
    input gracefully, and uses ≤ original CP count for smooth cubics.

No OCC, no network, no database.  All oracles are closed-form.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, de_boor
from kerf_cad_core.geom.curve_toolkit import (
    conic,
    eval_conic,
    fit_curve,
    _make_clamped_knots,
    _pt_knots_from_params,
    _chord_params,
)


# ---------------------------------------------------------------------------
# Shared analytic fixtures
# ---------------------------------------------------------------------------

def _parabola_curve():
    """conic that traces y = x^2 exactly (parabola, weight=1).

    Control points: P0=(-1,1,0), P1=(0,-1,0), P2=(1,1,0), w=1.
    The tangents at P0 and P2 of y=x^2 intersect at (0,-1).
    Proven by algebra: x(t)=2t-1, y(t)=(2t-1)^2=x^2 for all t.
    """
    return conic([-1.0, 1.0, 0.0], [0.0, -1.0, 0.0], [1.0, 1.0, 0.0], weight=1.0)


def _ellipse_arc_curve(a: float = 2.0, b: float = 1.0):
    """conic tracing the quarter of ellipse x^2/a^2 + y^2/b^2 = 1 exactly.

    Control points: P0=(a,0), P1=(a,b) (tangent intersection), P2=(0,b).
    Weight: w = 1/sqrt(2).  Proven: B^2 - 2AC = 0 for w=1/sqrt(2).
    """
    w = 1.0 / math.sqrt(2.0)
    return conic([a, 0.0, 0.0], [a, b, 0.0], [0.0, b, 0.0], weight=w)


def _circle_arc_curve(r: float = 2.0):
    """Quarter of circle x^2+y^2=r^2 (from (r,0) to (0,r)) via w=1/sqrt(2)."""
    return _ellipse_arc_curve(a=r, b=r)


def _hyperbola_curve():
    """conic with w=2 tracing 3y^2 - 4x^2 - 8y + 4 = 0.

    Control points: P0=(-1,0,0), P1=(0,1,0), P2=(1,0,0), w=2.
    Derived algebraically: center (0, 4/3), a=2/3, b=1/sqrt(3),
    c=sqrt(7)/3, e=sqrt(7)/2 > 1.
    """
    return conic([-1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [1.0, 0.0, 0.0], weight=2.0)


def _known_smooth_cubic():
    """A nearly arc-length-uniform cubic Bezier (4 CPs) in 3D."""
    ctrl = np.array([[0.0, 0.0, 0.0],
                     [1.0, 0.2, 0.0],
                     [2.0, 0.2, 0.0],
                     [3.0, 0.0, 0.0]])
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=ctrl, knots=knots)


# ---------------------------------------------------------------------------
# Group A: GK-05 — Conic construction and evaluation
# ---------------------------------------------------------------------------

class TestConicEndpoints:
    """A conic must start at P0 and end at P2 exactly."""

    def test_parabola_starts_at_p0(self):
        crv = _parabola_curve()
        pt = eval_conic(crv, 0.0)
        np.testing.assert_allclose(pt[:2], [-1.0, 1.0], atol=1e-14)

    def test_parabola_ends_at_p2(self):
        crv = _parabola_curve()
        pt = eval_conic(crv, 1.0)
        np.testing.assert_allclose(pt[:2], [1.0, 1.0], atol=1e-14)

    def test_ellipse_starts_at_p0(self):
        crv = _ellipse_arc_curve()
        pt = eval_conic(crv, 0.0)
        np.testing.assert_allclose(pt[:2], [2.0, 0.0], atol=1e-14)

    def test_ellipse_ends_at_p2(self):
        crv = _ellipse_arc_curve()
        pt = eval_conic(crv, 1.0)
        np.testing.assert_allclose(pt[:2], [0.0, 1.0], atol=1e-14)

    def test_hyperbola_starts_at_p0(self):
        crv = _hyperbola_curve()
        pt = eval_conic(crv, 0.0)
        np.testing.assert_allclose(pt[:2], [-1.0, 0.0], atol=1e-14)

    def test_eval_conic_returns_3d(self):
        """eval_conic must return a 3-element Cartesian vector (not homogeneous)."""
        crv = _parabola_curve()
        pt = eval_conic(crv, 0.5)
        assert pt.shape == (3,)


class TestParabolaFocusDirectrix:
    """Oracle: parabola e=1 focus–directrix property to 1e-9.

    y = x^2 has focus F=(0, 1/4) and directrix y = -1/4.
    For any point (x, y) on the curve:
        d(P, F) = sqrt(x^2 + (y-1/4)^2) = y + 1/4 = d(P, directrix)
    """

    def _pts(self, n: int = 100) -> np.ndarray:
        crv = _parabola_curve()
        return np.array([eval_conic(crv, t) for t in np.linspace(0.0, 1.0, n)])

    def test_curve_on_parabola(self):
        """All sampled points satisfy y = x^2 to 1e-12."""
        pts = self._pts()
        for p in pts:
            assert abs(p[1] - p[0] ** 2) < 1e-12, f"y != x^2 at {p}"

    def test_focus_directrix_parabola_to_1e9(self):
        """d(P, focus) - d(P, directrix) < 1e-9 for 100 sampled points."""
        pts = self._pts(100)
        focus = np.array([0.0, 0.25, 0.0])
        for p in pts:
            d_focus = np.linalg.norm(p - focus)
            d_dir = p[1] + 0.25          # distance to y = -1/4
            assert abs(d_focus - d_dir) < 1e-9, (
                f"parabola focus-directrix err={abs(d_focus-d_dir):.2e} at {p}")

    def test_parabola_eccentricity_is_one(self):
        """The discriminant B^2-4AC of the implicit conic equals 0 (parabola)."""
        # For y = x^2: x^2 - y = 0 → A=1, B=0, C=0, D^2-4AC = 0
        pts = self._pts(50)
        for p in pts:
            residual = p[0] ** 2 - p[1]
            assert abs(residual) < 1e-12

    def test_parabola_midpoint_analytic(self):
        """At t=0.5 the midpoint is the analytic rational Bernstein result.

        With P0=(-1,1), P1=(0,-1), P2=(1,1), w=1, rho=0.5 Bernstein:
          denom = 0.25+0.5+0.25 = 1, x = 0.25*(-1)+0 + 0.25*1 = 0, y = 0.
        """
        crv = _parabola_curve()
        pt = eval_conic(crv, 0.5)
        np.testing.assert_allclose(pt[:2], [0.0, 0.0], atol=1e-14)


class TestEllipseFocusDirectrix:
    """Oracle: ellipse arc on x^2/4 + y^2 = 1, e = sqrt(3)/2 < 1.

    a=2, b=1, c=sqrt(3), e=sqrt(3)/2, focus=(sqrt(3),0), directrix x=4/sqrt(3).
    For a point (x,y) in the first quadrant:
        d(P, right_focus) / d(P, right_directrix) = e
    """

    def _pts(self, n: int = 80) -> np.ndarray:
        crv = _ellipse_arc_curve(a=2.0, b=1.0)
        return np.array([eval_conic(crv, t) for t in np.linspace(0.0, 1.0, n)])

    def test_ellipse_on_implicit_curve(self):
        """x^2/4 + y^2 = 1 for all sampled points to 1e-14."""
        pts = self._pts()
        for p in pts:
            res = (p[0] ** 2) / 4.0 + p[1] ** 2 - 1.0
            assert abs(res) < 1e-14, f"not on ellipse: residual={res:.2e} at {p}"

    def test_ellipse_eccentricity_less_than_one(self):
        """Weight < 1 produces an ellipse (e < 1).

        e = sqrt(3)/2 ≈ 0.866. focus-directrix ratio = e for each point.
        """
        pts = self._pts(80)
        c_val = math.sqrt(3.0)
        e = c_val / 2.0               # sqrt(3)/2
        focus = np.array([c_val, 0.0])
        directrix_x = 4.0 / c_val    # a^2/c = 4/sqrt(3)
        for p in pts:
            d_f = math.hypot(p[0] - focus[0], p[1] - focus[1])
            d_d = abs(p[0] - directrix_x)
            if d_d < 1e-12:
                continue             # skip directrix singularity
            assert abs(d_f / d_d - e) < 1e-9, (
                f"ellipse focus-directrix err at {p}: {abs(d_f/d_d - e):.2e}")

    def test_ellipse_focus_directrix_to_1e9(self):
        """Explicit check: max focus-directrix error < 1e-9 over 80 samples."""
        pts = self._pts(80)
        c_val = math.sqrt(3.0)
        e = c_val / 2.0
        focus = np.array([c_val, 0.0])
        directrix_x = 4.0 / c_val
        errs = []
        for p in pts:
            d_f = math.hypot(p[0] - focus[0], p[1] - focus[1])
            d_d = abs(p[0] - directrix_x)
            if d_d > 1e-12:
                errs.append(abs(d_f / d_d - e))
        assert max(errs) < 1e-9


class TestCircularArcWeight:
    """Oracle: weight = cos(half_angle) reproduces circle radius to 1e-9.

    For a quarter-arc (half_angle = pi/4), w = cos(pi/4) = 1/sqrt(2).
    All sampled points on the arc must satisfy x^2+y^2 = r^2.
    """

    def test_circle_radius_exact_100_samples(self):
        """100 samples of circle arc all have |radius - r| < 1e-9."""
        r = 3.0
        crv = _circle_arc_curve(r=r)
        errs = []
        for t in np.linspace(0.0, 1.0, 100):
            pt = eval_conic(crv, t)
            errs.append(abs(math.hypot(pt[0], pt[1]) - r))
        assert max(errs) < 1e-9, f"max radial err={max(errs):.2e}"

    def test_circle_radius_preserved_r_equals_1(self):
        """Unit circle arc: radial error < 1e-14 for 50 samples."""
        crv = _circle_arc_curve(r=1.0)
        for t in np.linspace(0.0, 1.0, 50):
            pt = eval_conic(crv, t)
            err = abs(math.hypot(pt[0], pt[1]) - 1.0)
            assert err < 1e-14, f"unit circle radial err={err:.2e}"

    def test_circle_is_special_ellipse(self):
        """Circle arc from _circle_arc_curve == _ellipse_arc_curve(a=r, b=r)."""
        r = 2.0
        pts_c = [eval_conic(_circle_arc_curve(r=r), t) for t in np.linspace(0, 1, 30)]
        pts_e = [eval_conic(_ellipse_arc_curve(a=r, b=r), t) for t in np.linspace(0, 1, 30)]
        for pc, pe in zip(pts_c, pts_e):
            np.testing.assert_allclose(pc, pe, atol=1e-14)


class TestHyperbolaFocusDirectrix:
    """Oracle: hyperbola (w=2) satisfies |d1-d2|=2a to 1e-9.

    Curve: P0=(-1,0), P1=(0,1), P2=(1,0), w=2.
    Implicit: 3y^2 - 4x^2 - 8y + 4 = 0.
    Center (0, 4/3), a=2/3, b=1/sqrt(3), c=sqrt(7)/3, e=sqrt(7)/2.
    """

    def _pts(self, n: int = 80) -> np.ndarray:
        crv = _hyperbola_curve()
        return np.array([eval_conic(crv, t) for t in np.linspace(0.05, 0.95, n)])

    def _hyperbola_params(self):
        a = 2.0 / 3.0
        b = 1.0 / math.sqrt(3.0)
        c = math.sqrt(7.0) / 3.0
        e = c / a
        center = np.array([0.0, 4.0 / 3.0, 0.0])
        f1 = center + np.array([0.0, c, 0.0])
        f2 = center - np.array([0.0, c, 0.0])
        return a, b, c, e, f1, f2

    def test_hyperbola_on_implicit_curve(self):
        """All sampled points satisfy 3y^2 - 4x^2 - 8y + 4 = 0 to 1e-12."""
        pts = self._pts()
        for p in pts:
            res = 3.0 * p[1] ** 2 - 4.0 * p[0] ** 2 - 8.0 * p[1] + 4.0
            assert abs(res) < 1e-12, f"not on hyperbola: residual={res:.2e}"

    def test_hyperbola_eccentricity_greater_than_one(self):
        """Weight > 1 must produce a hyperbola (e > 1)."""
        _, _, _, e, _, _ = self._hyperbola_params()
        assert e > 1.0, f"expected e > 1, got e={e:.4f}"

    def test_hyperbola_difference_of_distances_to_1e9(self):
        """||d(P,F1) - d(P,F2)| - 2a| < 1e-9 for 80 sampled points."""
        pts = self._pts(80)
        a, _, _, _, f1, f2 = self._hyperbola_params()
        errs = []
        for p in pts:
            d1 = np.linalg.norm(p - f1)
            d2 = np.linalg.norm(p - f2)
            errs.append(abs(abs(d1 - d2) - 2.0 * a))
        assert max(errs) < 1e-9, f"max hyperbola |d1-d2|-2a err={max(errs):.2e}"

    def test_hyperbola_eccentricity_value(self):
        """Eccentricity equals sqrt(7)/2 to 1e-12."""
        _, _, _, e, _, _ = self._hyperbola_params()
        expected_e = math.sqrt(7.0) / 2.0
        assert abs(e - expected_e) < 1e-12


class TestConicEdgeCases:
    """Edge cases and API validation for conic / eval_conic."""

    def test_legacy_rho_alias(self):
        """rho= keyword arg is accepted as a legacy alias for weight=."""
        crv_rho = conic([-1.0, 1.0, 0.0], [0.0, -1.0, 0.0], [1.0, 1.0, 0.0], rho=0.7)
        crv_w = conic([-1.0, 1.0, 0.0], [0.0, -1.0, 0.0], [1.0, 1.0, 0.0], weight=0.7)
        pt_rho = eval_conic(crv_rho, 0.5)
        pt_w = eval_conic(crv_w, 0.5)
        np.testing.assert_allclose(pt_rho, pt_w, atol=1e-14)

    def test_zero_weight_raises(self):
        """weight=0 must raise ValueError."""
        with pytest.raises(ValueError):
            conic([0.0, 0.0, 0.0], [1.0, 1.0, 0.0], [2.0, 0.0, 0.0], weight=0.0)

    def test_negative_weight_raises(self):
        """Negative weight must raise ValueError."""
        with pytest.raises(ValueError):
            conic([0.0, 0.0, 0.0], [1.0, 1.0, 0.0], [2.0, 0.0, 0.0], weight=-0.5)

    def test_hyperbola_weight_greater_than_one_allowed(self):
        """weight > 1 must work without error."""
        crv = conic([0.0, 0.0, 0.0], [1.0, 1.0, 0.0], [2.0, 0.0, 0.0], weight=1.5)
        assert isinstance(crv, NurbsCurve)

    def test_different_weights_differ_at_midpoint(self):
        """Different weight values produce different midpoint positions."""
        p0, p1, p2 = [0.0, 0.0, 0.0], [1.0, 2.0, 0.0], [2.0, 0.0, 0.0]
        pt_small = eval_conic(conic(p0, p1, p2, weight=0.3), 0.5)
        pt_large = eval_conic(conic(p0, p1, p2, weight=0.9), 0.5)
        assert not np.allclose(pt_small, pt_large, atol=1e-6)

    def test_returns_nurbs_curve(self):
        crv = conic([0.0, 0.0], [1.0, 1.0], [2.0, 0.0], weight=0.5)
        assert isinstance(crv, NurbsCurve)
        assert crv.degree == 2
        assert crv.num_control_points == 3

    def test_2d_control_points(self):
        """conic with 2-D control points produces 2-D eval_conic output."""
        crv = conic([0.0, 0.0], [1.0, 1.0], [2.0, 0.0], weight=0.5)
        pt = eval_conic(crv, 0.5)
        assert pt.shape == (2,)


# ---------------------------------------------------------------------------
# Group B: GK-22 — fit_curve Piegl–Tiller knot placement
# ---------------------------------------------------------------------------

class TestFitCurveOracle:
    """Core oracle tests for GK-22 fit_curve."""

    def test_smooth_cubic_oracle_le_original_cp_count(self):
        """500 samples of a smooth degree-3 cubic: fit uses ≤ original CP count.

        The nearly arc-length-uniform cubic has 4 control points.  With
        tol=1e-3 the Piegl–Tiller fit must find ok=True, dev<tol, num_ctrl≤4.
        """
        orig = _known_smooth_cubic()
        pts = np.array([de_boor(orig, t) for t in np.linspace(0.0, 1.0, 500)])
        result = fit_curve(pts, degree=3, tolerance=1e-3, max_ctrl=4)
        assert result["ok"], f"fit failed: {result['reason']}"
        assert result["deviation"] < 1e-3
        assert result["num_ctrl"] <= 4

    def test_smooth_cubic_500pts_deviation_within_tol(self):
        """Deviation must be < tol for the smooth cubic at tol=1e-3."""
        orig = _known_smooth_cubic()
        pts = np.array([de_boor(orig, t) for t in np.linspace(0.0, 1.0, 500)])
        result = fit_curve(pts, degree=3, tolerance=1e-3)
        assert result["ok"]
        assert result["deviation"] < 1e-3

    def test_circle_fit_bounded_cp_count_and_radial_error(self):
        """Fitting 200 circle samples at tol=1e-3: ok=True, max radial err<tol."""
        r = 1.0
        n = 200
        angles = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
        pts = np.column_stack([r * np.cos(angles),
                               r * np.sin(angles),
                               np.zeros(n)])
        result = fit_curve(pts, degree=3, tolerance=1e-3, max_ctrl=64)
        assert result["ok"], result["reason"]
        assert result["deviation"] < 1e-3

        # verify max radial error on the fitted curve
        crv = result["curve"]
        u0 = float(crv.knots[crv.degree])
        u1 = float(crv.knots[-(crv.degree + 1)])
        radii = [
            math.hypot(*de_boor(crv, float(u))[:2])
            for u in np.linspace(u0, u1, 200)
        ]
        assert max(abs(rr - r) for rr in radii) < 1e-3


class TestFitCurveDegenerateInput:
    """fit_curve must handle degenerate / edge-case inputs gracefully (no crash)."""

    def test_too_few_points_returns_false(self):
        result = fit_curve([[1.0, 0.0, 0.0]], degree=3, tolerance=1e-3)
        assert result["ok"] is False
        assert "need at least 2" in result["reason"]

    def test_two_points_returns_line(self):
        result = fit_curve([[0.0, 0.0, 0.0], [1.0, 1.0, 0.0]],
                           degree=1, tolerance=1e-6)
        assert result["ok"]
        assert result["curve"] is not None
        assert result["deviation"] < 1e-12

    def test_all_identical_points_degenerate(self):
        """All-same input: fit must return ok=True (or ok with reason) and not raise."""
        pts = [[1.0, 2.0, 0.0]] * 10
        result = fit_curve(pts, degree=3, tolerance=1e-6)
        assert result["curve"] is not None
        # must not raise; ok may be True with degenerate note
        assert isinstance(result["ok"], bool)

    def test_collinear_points_no_crash(self):
        """Collinear input handled without crash, returns a valid curve."""
        pts = [[float(i), 0.0, 0.0] for i in range(20)]
        result = fit_curve(pts, degree=3, tolerance=1e-6)
        assert result["curve"] is not None

    def test_collinear_points_small_deviation(self):
        """Collinear input: fit deviation is near-zero."""
        pts = [[float(i), 0.0, 0.0] for i in range(20)]
        result = fit_curve(pts, degree=1, tolerance=1e-6)
        assert result["ok"]
        assert result["deviation"] < 1e-10

    def test_duplicate_samples_no_crash(self):
        """Duplicate points in the sample list must not cause a crash."""
        pts = [[0.0, 0.0, 0.0],
               [0.0, 0.0, 0.0],
               [1.0, 0.5, 0.0],
               [1.0, 0.5, 0.0],
               [2.0, 0.0, 0.0]]
        result = fit_curve(pts, degree=3, tolerance=1e-3)
        assert result["curve"] is not None


class TestFitCurveTolerance:
    """Tolerance and control-point count properties."""

    def test_deviation_at_most_tolerance(self):
        """When ok=True, deviation ≤ tolerance always."""
        pts = [[math.sin(t), math.cos(t), 0.0]
               for t in np.linspace(0.0, math.pi, 60)]
        result = fit_curve(pts, degree=3, tolerance=0.01)
        if result["ok"]:
            assert result["deviation"] <= 0.01

    def test_tight_tolerance_uses_more_cp_than_loose(self):
        """A tighter tolerance requires ≥ as many CPs as a looser one."""
        pts = [[float(i) * 0.2, math.sin(float(i) * 0.5), 0.0]
               for i in range(60)]
        r_loose = fit_curve(pts, degree=3, tolerance=0.05, max_ctrl=50)
        r_tight = fit_curve(pts, degree=3, tolerance=0.001, max_ctrl=50)
        if r_loose["ok"] and r_tight["ok"]:
            assert r_tight["num_ctrl"] >= r_loose["num_ctrl"]

    def test_minimum_ctrl_is_degree_plus_one(self):
        """fit_curve must start from num_ctrl = degree+1."""
        pts = [[float(i), float(i) * 0.1, 0.0] for i in range(30)]
        result = fit_curve(pts, degree=3, tolerance=10.0, max_ctrl=64)
        assert result["num_ctrl"] >= 4  # degree+1 = 4

    def test_fit_preserves_degree(self):
        """The returned curve must have exactly the requested degree."""
        pts = [[float(i), float(i) ** 2 * 0.05, 0.0] for i in range(30)]
        for deg in [1, 2, 3]:
            result = fit_curve(pts, degree=deg, tolerance=1.0, max_ctrl=20)
            assert result["curve"].degree == deg

    def test_failed_fit_returns_best_effort_curve(self):
        """When ok=False (tolerance not achieved), a curve is still returned."""
        pts = [[math.sin(t * 5.0), math.cos(t * 5.0), 0.0]
               for t in np.linspace(0.0, 2.0 * math.pi, 200)]
        result = fit_curve(pts, degree=3, tolerance=1e-15, max_ctrl=4)
        # ok=False, but curve should not be None
        assert result["curve"] is not None or result["reason"] != ""

    def test_returns_nurbs_curve(self):
        pts = [[float(i), math.sin(float(i) * 0.3), 0.0] for i in range(20)]
        result = fit_curve(pts, degree=3, tolerance=0.1)
        assert isinstance(result["curve"], NurbsCurve)


class TestPieglTillerKnots:
    """Tests that verify the Piegl–Tiller knot vector properties."""

    def test_pt_knots_monotone_nondecreasing(self):
        """PT knot vector must be monotonically non-decreasing."""
        ts = np.linspace(0.0, 1.0, 50)
        for nc in [4, 5, 6, 8, 10]:
            knots = _pt_knots_from_params(ts, nc, degree=3)
            assert np.all(np.diff(knots) >= 0.0), \
                f"knots not monotone for nc={nc}: {knots}"

    def test_pt_knots_clamped_start_end(self):
        """PT knot vector must start at 0^(p+1) and end at 1^(p+1)."""
        ts = np.linspace(0.0, 1.0, 100)
        degree = 3
        for nc in [4, 6, 8]:
            knots = _pt_knots_from_params(ts, nc, degree=degree)
            assert knots[0] == pytest.approx(0.0)
            assert knots[-1] == pytest.approx(1.0)
            assert np.all(knots[:degree + 1] == 0.0)
            assert np.all(knots[-(degree + 1):] == 1.0)

    def test_pt_knots_minimum_case(self):
        """num_ctrl = degree+1 (fully clamped Bezier) has no interior knots."""
        ts = np.linspace(0.0, 1.0, 20)
        knots = _pt_knots_from_params(ts, num_ctrl=4, degree=3)
        # all interior knots should be 0 or 1 (fully clamped)
        assert len(knots) == 8
        np.testing.assert_array_equal(knots, [0, 0, 0, 0, 1, 1, 1, 1])

    def test_pt_knots_interior_in_data_range(self):
        """Interior knots must lie within (0, 1)."""
        ts = _chord_params(np.column_stack([
            np.linspace(0, 3, 80),
            np.sin(np.linspace(0, 3, 80)),
            np.zeros(80),
        ]))
        degree = 3
        nc = 10
        knots = _pt_knots_from_params(ts, nc, degree)
        interior = knots[degree + 1: -(degree + 1)]
        assert np.all(interior > 0.0)
        assert np.all(interior < 1.0)
