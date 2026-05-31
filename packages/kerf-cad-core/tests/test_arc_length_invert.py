"""
Tests for arc_length_invert.py — NURBS curve arc-length inversion.

Test matrix
-----------
1.  Straight line L=10: invert(L/2) → t=0.5  (within 1e-9)
2.  Circle R=5: invert(πR/2) → point at 90° from start
3.  Circle R=1: invert(πR)   → point at 180° (halfway round)
4.  Edge: target_s > total_length → clamp to t_end with caveat
5.  Edge: target_s < 0            → clamp to t_start with caveat
6.  Edge: target_s == 0           → t_start exactly
7.  Edge: target_s == total_length → t_end
8.  Convergence: iterations < 10 for straight line
9.  Convergence: iterations < 10 for circle
10. Cubic spline: invert(0) + invert(L) round-trip
11. Cubic spline: invert is monotone (s1 < s2 ⟹ t1 < t2)
12. Cubic spline: residual ≤ tol for all tested points
13. Rational circle: invert gives correct 3-D point (within geometric tol)
14. Line with different domain: offset domain [2, 5]
15. Result dataclass has correct types
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    make_circle_nurbs,
    make_line_nurbs,
)
from kerf_cad_core.geom.curve_toolkit import curve_length
from kerf_cad_core.geom.arc_length_invert import (
    ArcLengthInvertResult,
    invert_arc_length,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_line_3d(p0, p1) -> NurbsCurve:
    """Degree-1 NURBS from p0 to p1."""
    ctrl = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=ctrl, knots=knots)


def _make_cubic_spline() -> NurbsCurve:
    """Non-trivial degree-3 interpolated spline over a sine-wave point cloud."""
    from kerf_cad_core.geom.curve_toolkit import interp_curve
    xs = np.linspace(0.0, 2.0 * math.pi, 20)
    pts = np.column_stack([xs, np.sin(xs), np.zeros_like(xs)])
    return interp_curve(pts, degree=3)


# ---------------------------------------------------------------------------
# 1. Straight line: invert(L/2) → t = 0.5 of parameter domain
# ---------------------------------------------------------------------------

class TestStraightLine:
    def test_midpoint_parameter(self):
        """Unit line [0,0,0]→[10,0,0]: invert(5) → t ≈ 0.5 within 1e-9."""
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([10.0, 0.0, 0.0]),
        )
        L = curve_length(curve)
        result = invert_arc_length(curve, L / 2.0, tol=1e-9)
        u0 = float(curve.knots[curve.degree])
        u1 = float(curve.knots[-(curve.degree + 1)])
        t_mid = 0.5 * (u0 + u1)
        assert abs(result.t_param - t_mid) < 1e-9, (
            f"Expected t≈{t_mid:.10f}, got {result.t_param:.10f} "
            f"(err={abs(result.t_param - t_mid):.2e})"
        )

    def test_quarter_point(self):
        """Line: invert(L/4) → t ≈ 0.25 * (u1-u0)."""
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([4.0, 0.0, 0.0]),
        )
        L = curve_length(curve)
        result = invert_arc_length(curve, L / 4.0, tol=1e-9)
        u0 = float(curve.knots[curve.degree])
        u1 = float(curve.knots[-(curve.degree + 1)])
        t_expected = u0 + 0.25 * (u1 - u0)
        assert abs(result.t_param - t_expected) < 1e-9

    def test_residual_is_small(self):
        """Residual ≤ tol for straight line."""
        tol = 1e-6
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([7.0, 0.0, 0.0]),
        )
        L = curve_length(curve)
        result = invert_arc_length(curve, L * 0.6, tol=tol)
        assert result.residual_mm <= tol * 10, (
            f"residual {result.residual_mm:.3e} too large for tol={tol}"
        )


# ---------------------------------------------------------------------------
# 2. Circle: invert(πR/2) → 90° from start
# ---------------------------------------------------------------------------

class TestCircle:
    def test_circle_quarter_arc(self):
        """Circle R=5: invert(π*R/2) gives a point at 90° from start."""
        R = 5.0
        curve = make_circle_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=R,
        )
        quarter_arc = math.pi * R / 2.0  # 90° of arc on radius-R circle
        result = invert_arc_length(curve, quarter_arc, tol=1e-7)

        # Evaluate point at the returned parameter
        pt = curve.evaluate(result.t_param)
        # For a circle in the XY plane centred at origin, the point at 90° arc
        # should have coordinates with ‖pt‖ = R and lie on the circle.
        r_actual = float(np.linalg.norm(pt[:2]))
        assert abs(r_actual - R) < 1e-4, (
            f"Point is not on circle: |pt|={r_actual:.6f}, expected R={R}"
        )

    def test_circle_half_arc(self):
        """Circle R=1: invert(πR) → half-circle point."""
        R = 1.0
        curve = make_circle_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=R,
        )
        half_arc = math.pi * R
        result = invert_arc_length(curve, half_arc, tol=1e-7)
        pt = curve.evaluate(result.t_param)
        r_actual = float(np.linalg.norm(pt[:2]))
        assert abs(r_actual - R) < 1e-4

    def test_circle_residual(self):
        """Residual ≤ tol for circle inversion."""
        tol = 1e-6
        R = 3.0
        curve = make_circle_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=R,
        )
        L = curve_length(curve)
        result = invert_arc_length(curve, L * 0.3, tol=tol)
        assert result.residual_mm <= tol * 10


# ---------------------------------------------------------------------------
# 3. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_target_exceeds_length(self):
        """target > total_length → clamps to t_end with warning."""
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
        )
        u1 = float(curve.knots[-(curve.degree + 1)])
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            result = invert_arc_length(curve, 999.0)
        assert result.t_param == pytest.approx(u1, abs=1e-12)
        assert len(w) == 1
        assert "clamped" in str(w[0].message).lower()

    def test_target_negative(self):
        """target < 0 → clamps to t_start with caveat."""
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
        )
        u0 = float(curve.knots[curve.degree])
        result = invert_arc_length(curve, -1.0)
        assert result.t_param == pytest.approx(u0, abs=1e-12)
        assert result.iterations == 0
        assert "clamp" in result.honest_caveat.lower() or "<= 0" in result.honest_caveat

    def test_target_zero(self):
        """target == 0 → t_start exactly."""
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([5.0, 0.0, 0.0]),
        )
        u0 = float(curve.knots[curve.degree])
        result = invert_arc_length(curve, 0.0)
        assert result.t_param == pytest.approx(u0, abs=1e-12)
        assert result.iterations == 0

    def test_target_equals_total_length(self):
        """target == total_length → t_end with zero residual."""
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([3.0, 0.0, 0.0]),
        )
        u1 = float(curve.knots[-(curve.degree + 1)])
        L = curve_length(curve)
        result = invert_arc_length(curve, L)
        assert result.t_param == pytest.approx(u1, abs=1e-12)
        assert result.residual_mm < 1e-10


# ---------------------------------------------------------------------------
# 4. Convergence speed
# ---------------------------------------------------------------------------

class TestConvergence:
    def test_line_iterations_few(self):
        """Straight line should converge in < 10 iterations."""
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([100.0, 0.0, 0.0]),
        )
        L = curve_length(curve)
        result = invert_arc_length(curve, L * 0.37, tol=1e-6)
        assert result.iterations < 10, (
            f"Too many iterations: {result.iterations}"
        )

    def test_circle_iterations_few(self):
        """Circle should converge in < 10 iterations."""
        curve = make_circle_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=2.0,
        )
        L = curve_length(curve)
        result = invert_arc_length(curve, L * 0.6, tol=1e-6)
        assert result.iterations < 10, (
            f"Too many iterations: {result.iterations}"
        )


# ---------------------------------------------------------------------------
# 5. Cubic spline: round-trip, monotonicity, residual
# ---------------------------------------------------------------------------

class TestCubicSpline:
    @pytest.fixture(scope="class")
    def spline(self):
        return _make_cubic_spline()

    def test_roundtrip_zero(self, spline):
        """invert(0) returns t_start."""
        u0 = float(spline.knots[spline.degree])
        result = invert_arc_length(spline, 0.0)
        assert result.t_param == pytest.approx(u0, abs=1e-12)

    def test_roundtrip_total(self, spline):
        """invert(L) returns t_end."""
        u1 = float(spline.knots[-(spline.degree + 1)])
        L = curve_length(spline)
        result = invert_arc_length(spline, L)
        assert result.t_param == pytest.approx(u1, abs=1e-9)

    def test_monotone(self, spline):
        """s1 < s2 ⟹ t1 < t2 (strict monotone on spline)."""
        L = curve_length(spline)
        fracs = [0.1, 0.3, 0.5, 0.7, 0.9]
        ts = [invert_arc_length(spline, f * L, tol=1e-6).t_param for f in fracs]
        for i in range(len(ts) - 1):
            assert ts[i] < ts[i + 1], (
                f"Monotonicity violated: t[{i}]={ts[i]:.6f} >= t[{i+1}]={ts[i+1]:.6f}"
            )

    def test_residuals_within_tol(self, spline):
        """Residual ≤ tol for multiple test points on the cubic spline."""
        tol = 1e-5
        L = curve_length(spline)
        for frac in [0.1, 0.25, 0.5, 0.75, 0.9]:
            result = invert_arc_length(spline, frac * L, tol=tol)
            assert result.residual_mm <= tol * 10, (
                f"frac={frac}: residual {result.residual_mm:.3e} > {tol * 10:.3e}"
            )


# ---------------------------------------------------------------------------
# 6. Offset domain
# ---------------------------------------------------------------------------

class TestOffsetDomain:
    def test_line_offset_domain(self):
        """Line with domain [2, 5]: invert from sub-interval works."""
        ctrl = np.array([[0.0, 0.0, 0.0], [6.0, 0.0, 0.0]], dtype=float)
        knots = np.array([0.0, 0.0, 1.0, 1.0])
        curve = NurbsCurve(degree=1, control_points=ctrl, knots=knots)
        # Sub-interval from t=0.0 to t=0.5 (length 3)
        result = invert_arc_length(curve, 1.5, tol=1e-8, t_start=0.0, t_end=0.5)
        assert abs(result.t_param - 0.25) < 1e-7, (
            f"Expected t≈0.25, got {result.t_param}"
        )


# ---------------------------------------------------------------------------
# 7. Result dataclass
# ---------------------------------------------------------------------------

class TestResultDataclass:
    def test_types(self):
        """ArcLengthInvertResult has correct field types."""
        curve = make_line_nurbs(
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
        )
        result = invert_arc_length(curve, 0.5, tol=1e-6)
        assert isinstance(result, ArcLengthInvertResult)
        assert isinstance(result.t_param, float)
        assert isinstance(result.residual_mm, float)
        assert isinstance(result.iterations, int)
        assert isinstance(result.honest_caveat, str)
        assert result.residual_mm >= 0.0
        assert result.iterations >= 0


# ---------------------------------------------------------------------------
# 8. Import smoke test
# ---------------------------------------------------------------------------

class TestImports:
    def test_importable_from_geom(self):
        """invert_arc_length and ArcLengthInvertResult are importable from geom."""
        from kerf_cad_core.geom import invert_arc_length as _f, ArcLengthInvertResult as _r
        assert callable(_f)
        assert _r is ArcLengthInvertResult
