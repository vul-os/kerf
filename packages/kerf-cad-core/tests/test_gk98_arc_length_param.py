"""GK-98: Arc-length parameterization + curve length — hermetic pytest oracle.

Oracles
-------
1. Quarter unit-circle arc length = pi/2 (within 1e-6).
2. Line segment length = |p1 - p0| (within 1e-9).
3. arc_length_param.length_at(t_end) matches curve_length within 1e-4.
4. arc_length_param.t_at_length(s) round-trips: length_at(t_at_length(s)) ≈ s.
5. Public façade exports both symbols.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, make_circle_nurbs, make_line_nurbs, make_arc_nurbs
from kerf_cad_core.geom.curve_toolkit import curve_length, arc_length_param
import kerf_cad_core.geom as _geom_pkg


# ---------------------------------------------------------------------------
# Public export check
# ---------------------------------------------------------------------------

class TestPublicExports:
    def test_curve_length_exported(self):
        assert hasattr(_geom_pkg, "curve_length")
        assert _geom_pkg.curve_length is curve_length

    def test_arc_length_param_exported(self):
        assert hasattr(_geom_pkg, "arc_length_param")
        assert _geom_pkg.arc_length_param is arc_length_param


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_quarter_circle() -> NurbsCurve:
    """Exact rational NURBS quarter unit-circle in XY plane via make_arc_nurbs."""
    return make_arc_nurbs(
        center=np.array([0.0, 0.0, 0.0]),
        radius=1.0,
        start_angle=0.0,
        end_angle=math.pi / 2.0,
    )


def _make_line(p0, p1, degree: int = 1) -> NurbsCurve:
    """Straight line from p0 to p1 as a degree-1 NURBS."""
    ctrl = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=ctrl, knots=knots)


# ---------------------------------------------------------------------------
# curve_length oracle tests
# ---------------------------------------------------------------------------

class TestCurveLength:
    def test_quarter_circle_arc(self):
        """Arc length of a quarter unit-circle = pi/2."""
        curve = _make_quarter_circle()
        length = curve_length(curve)
        assert abs(length - math.pi / 2) < 1e-6, (
            f"Expected pi/2={math.pi/2:.8f}, got {length:.8f}"
        )

    def test_line_unit_length(self):
        """Line from (0,0) to (1,0) has length 1.0."""
        curve = _make_line([0.0, 0.0], [1.0, 0.0])
        length = curve_length(curve)
        assert abs(length - 1.0) < 1e-9, f"Expected 1.0, got {length}"

    def test_line_arbitrary_length(self):
        """Line from p0 to p1 has length |p1 - p0|."""
        p0 = np.array([1.0, 2.0, 3.0])
        p1 = np.array([4.0, 6.0, 3.0])
        expected = float(np.linalg.norm(p1 - p0))
        curve = _make_line(p0, p1)
        length = curve_length(curve)
        assert abs(length - expected) < 1e-9, (
            f"Expected {expected:.8f}, got {length:.8f}"
        )

    def test_zero_length_interval(self):
        """t0 == t1 should return 0."""
        curve = _make_line([0.0, 0.0], [1.0, 0.0])
        assert curve_length(curve, t0=0.5, t1=0.5) == 0.0

    def test_partial_line_length(self):
        """curve_length over half of a unit line = 0.5."""
        curve = _make_line([0.0, 0.0], [1.0, 0.0])
        length = curve_length(curve, t0=0.0, t1=0.5)
        assert abs(length - 0.5) < 1e-9, f"Expected 0.5, got {length}"

    def test_diagonal_3d_line(self):
        """Line (0,0,0) → (3,4,0): expected length 5."""
        p0 = np.array([0.0, 0.0, 0.0])
        p1 = np.array([3.0, 4.0, 0.0])
        curve = _make_line(p0, p1)
        length = curve_length(curve)
        assert abs(length - 5.0) < 1e-9, f"Expected 5.0, got {length}"


# ---------------------------------------------------------------------------
# arc_length_param oracle tests
# ---------------------------------------------------------------------------

class TestArcLengthParam:
    def test_total_length_matches_curve_length_line(self):
        """arc_length_param.total_length matches curve_length for a line."""
        p0 = np.array([0.0, 0.0])
        p1 = np.array([3.0, 4.0])
        curve = _make_line(p0, p1)
        alp = arc_length_param(curve, n=128)
        expected = curve_length(curve)
        assert abs(alp.total_length - expected) < 1e-4, (
            f"total_length {alp.total_length:.8f} != curve_length {expected:.8f}"
        )

    def test_total_length_quarter_circle(self):
        """arc_length_param.total_length ≈ pi/2 for quarter unit-circle."""
        curve = _make_quarter_circle()
        alp = arc_length_param(curve, n=256)
        assert abs(alp.total_length - math.pi / 2) < 1e-4, (
            f"Expected pi/2={math.pi/2:.6f}, got {alp.total_length:.6f}"
        )

    def test_length_at_start_is_zero(self):
        """length_at(t_start) == 0."""
        curve = _make_line([0.0, 0.0], [1.0, 0.0])
        alp = arc_length_param(curve, n=64)
        u0 = float(curve.knots[curve.degree])
        assert abs(alp.length_at(u0)) < 1e-12

    def test_length_at_end_is_total(self):
        """length_at(t_end) == total_length."""
        curve = _make_line([0.0, 0.0], [1.0, 0.0])
        alp = arc_length_param(curve, n=64)
        u1 = float(curve.knots[-(curve.degree + 1)])
        assert abs(alp.length_at(u1) - alp.total_length) < 1e-12

    def test_t_at_length_roundtrip(self):
        """length_at(t_at_length(s)) ≈ s for several s values on a line."""
        p0 = np.array([0.0, 0.0])
        p1 = np.array([5.0, 0.0])
        curve = _make_line(p0, p1)
        alp = arc_length_param(curve, n=128)
        for frac in [0.0, 0.25, 0.5, 0.75, 1.0]:
            s = frac * alp.total_length
            t = alp.t_at_length(s)
            s_back = alp.length_at(t)
            assert abs(s_back - s) < 1e-6, (
                f"Round-trip failed at frac={frac}: s={s:.6f}, s_back={s_back:.6f}"
            )

    def test_t_at_length_roundtrip_circle(self):
        """Round-trip on quarter circle: length_at(t_at_length(s)) ≈ s."""
        curve = _make_quarter_circle()
        alp = arc_length_param(curve, n=256)
        for frac in [0.0, 0.25, 0.5, 0.75, 1.0]:
            s = frac * alp.total_length
            t = alp.t_at_length(s)
            s_back = alp.length_at(t)
            assert abs(s_back - s) < 1e-4, (
                f"Round-trip failed at frac={frac}: s={s:.6f}, s_back={s_back:.6f}"
            )

    def test_length_at_midpoint_line(self):
        """For a unit line, length_at(0.5) ≈ 0.5."""
        curve = _make_line([0.0, 0.0], [1.0, 0.0])
        alp = arc_length_param(curve, n=64)
        assert abs(alp.length_at(0.5) - 0.5) < 1e-6
