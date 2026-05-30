"""
Tests for kerf_cad_core.geom.conic_detect — NURBS rational conic detection.

All tests are hermetic (no OCC, no DB, no network).  Analytical oracles are
used throughout: every expected value is derived from the exact construction,
not from the module under test.

Test groups
-----------
1. test_nurbs_unit_circle      — 9-point rational quadratic → circle; r=1; center=(0,0,0)
2. test_nurbs_ellipse          — scaled circle → ellipse; a=2, b=1
3. test_nonconic_cubic_spline  — degree-3 cubic spline → detect returns None
4. test_tilted_circle          — circle tilted 45° → still 'circle'; normal correctly oriented
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, make_circle_nurbs
from kerf_cad_core.geom.conic_detect import (
    detect_conic,
    extract_canonical_circle,
    simplify_curve,
    ConicInfo,
    CircleParams,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ellipse_nurbs(a: float, b: float,
                        center: np.ndarray = None,
                        x_axis: np.ndarray = None,
                        y_axis: np.ndarray = None) -> NurbsCurve:
    """Exact rational quadratic NURBS ellipse via scaled circle construction.

    An ellipse with semi-axes a (x) and b (y) can be constructed by scaling
    the unit circle control points: CP_x *= a, CP_y *= b.
    The weights remain the same as the standard circle (√2/2 for shoulders).
    This is the exact algebraic construction — every sample point satisfies
    (x/a)²+(y/b)²=1 to machine precision.
    """
    if center is None:
        center = np.zeros(3)
    else:
        center = np.asarray(center, dtype=float).ravel()[:3]

    if x_axis is None:
        x_axis = np.array([1.0, 0.0, 0.0])
    if y_axis is None:
        y_axis = np.array([0.0, 1.0, 0.0])

    X = np.asarray(x_axis, dtype=float)[:3]
    Y = np.asarray(y_axis, dtype=float)[:3]
    X = X / (np.linalg.norm(X) + 1e-300)
    Y = Y / (np.linalg.norm(Y) + 1e-300)

    s = math.sqrt(2.0) / 2.0
    # Control-point offsets in local frame (scaled by a, b)
    offs = [
        ( a,  0.0),
        ( a,  b),
        ( 0.0,  b),
        (-a,  b),
        (-a,  0.0),
        (-a, -b),
        ( 0.0, -b),
        ( a, -b),
        ( a,  0.0),
    ]
    cps = np.array([center + dx * X + dy * Y for (dx, dy) in offs])
    weights = np.array([1.0, s, 1.0, s, 1.0, s, 1.0, s, 1.0])
    knots = np.array([0.0, 0.0, 0.0,
                      0.25, 0.25, 0.5, 0.5, 0.75, 0.75,
                      1.0, 1.0, 1.0])
    return NurbsCurve(degree=2, control_points=cps, knots=knots, weights=weights)


def _make_cubic_spline() -> NurbsCurve:
    """Degree-3 open B-spline that clearly is not a conic (sinusoidal shape)."""
    # 8 CPs in an S-curve shape.
    cps = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 2.0, 0.0],
        [2.0, -1.0, 0.0],
        [3.0, 1.5, 0.0],
        [4.0, -0.5, 0.0],
        [5.0, 2.0, 0.0],
        [6.0, 0.5, 0.0],
        [7.0, 0.0, 0.0],
    ])
    n = len(cps)
    degree = 3
    # Clamped uniform knot vector
    interior = np.linspace(0, 1, n - degree + 1)[1:-1]
    knots = np.concatenate([
        np.zeros(degree + 1),
        interior,
        np.ones(degree + 1),
    ])
    return NurbsCurve(degree=degree, control_points=cps, knots=knots, weights=None)


# ---------------------------------------------------------------------------
# Test 1: NURBS unit circle
# ---------------------------------------------------------------------------

class TestNurbsUnitCircle:
    """9-point rational quadratic unit circle → kind='circle'; radius=1; center=(0,0,0)."""

    def setup_method(self):
        self.curve = make_circle_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=1.0,
        )
        self.info = detect_conic(self.curve, tol=1e-6)

    def test_detected_as_conic(self):
        assert self.info is not None, "unit circle must be detected as a conic"

    def test_kind_is_circle(self):
        assert self.info.kind == 'circle', f"expected 'circle', got '{self.info.kind}'"

    def test_radius(self):
        r = (self.info.radii[0] + self.info.radii[1]) / 2.0
        assert abs(r - 1.0) < 1e-9, f"expected radius 1.0, got {r}"

    def test_center(self):
        c = self.info.center
        assert np.allclose(c, [0.0, 0.0, 0.0], atol=1e-9), \
            f"expected center (0,0,0), got {c}"

    def test_eccentricity(self):
        assert abs(self.info.eccentricity) < 1e-9, \
            f"circle eccentricity must be 0, got {self.info.eccentricity}"

    def test_plane_normal_unit(self):
        n = self.info.plane_normal
        assert abs(np.linalg.norm(n) - 1.0) < 1e-9

    def test_extract_canonical_circle(self):
        cp = extract_canonical_circle(self.curve, tol=1e-6)
        assert cp is not None
        assert abs(cp.radius - 1.0) < 1e-9
        assert np.allclose(cp.center, [0.0, 0.0, 0.0], atol=1e-9)

    def test_simplify_returns_conic_info(self):
        result = simplify_curve(self.curve, tol=1e-6)
        assert isinstance(result, ConicInfo)
        assert result.kind == 'circle'


# ---------------------------------------------------------------------------
# Test 2: NURBS ellipse (scaled circle)
# ---------------------------------------------------------------------------

class TestNurbsEllipse:
    """Scaled circle (a=2, b=1) → kind='ellipse'; major=2, minor=1 within 1e-6."""

    def setup_method(self):
        self.a = 2.0
        self.b = 1.0
        self.curve = _make_ellipse_nurbs(self.a, self.b)
        self.info = detect_conic(self.curve, tol=1e-6)

    def test_detected_as_conic(self):
        assert self.info is not None, "scaled-circle ellipse must be detected"

    def test_kind_is_ellipse(self):
        assert self.info.kind == 'ellipse', f"expected 'ellipse', got '{self.info.kind}'"

    def test_major_axis(self):
        major = self.info.radii[0]
        assert abs(major - self.a) < 1e-6 * self.a + 1e-9, \
            f"expected major={self.a}, got {major}"

    def test_minor_axis(self):
        minor = self.info.radii[1]
        assert abs(minor - self.b) < 1e-6 * self.b + 1e-9, \
            f"expected minor={self.b}, got {minor}"

    def test_center_near_origin(self):
        assert np.allclose(self.info.center, [0.0, 0.0, 0.0], atol=1e-6)

    def test_eccentricity(self):
        # e = sqrt(1 - (b/a)²) = sqrt(1 - 0.25) = sqrt(0.75) ≈ 0.8660
        expected_e = math.sqrt(1.0 - (self.b / self.a)**2)
        assert abs(self.info.eccentricity - expected_e) < 1e-5, \
            f"expected eccentricity {expected_e:.6f}, got {self.info.eccentricity:.6f}"

    def test_simplify_returns_conic_info(self):
        result = simplify_curve(self.curve, tol=1e-6)
        assert isinstance(result, ConicInfo)
        assert result.kind == 'ellipse'


# ---------------------------------------------------------------------------
# Test 3: non-conic cubic spline → None
# ---------------------------------------------------------------------------

class TestNonConicCubicSpline:
    """A degree-3 cubic S-spline is not a conic → detect returns None."""

    def setup_method(self):
        self.curve = _make_cubic_spline()

    def test_degree_gate(self):
        # Degree 3 > 2, so must return None immediately.
        info = detect_conic(self.curve, tol=1e-6)
        assert info is None, "cubic spline must not be detected as a conic"

    def test_simplify_returns_nurbs_curve(self):
        result = simplify_curve(self.curve, tol=1e-6)
        assert isinstance(result, NurbsCurve), \
            "simplify_curve must return NurbsCurve for a non-conic"
        # Must be the same object (no copy).
        assert result is self.curve

    def test_extract_canonical_circle_returns_none(self):
        cp = extract_canonical_circle(self.curve, tol=1e-6)
        assert cp is None


# ---------------------------------------------------------------------------
# Test 4: Tilted circle (45° around X axis)
# ---------------------------------------------------------------------------

class TestTiltedCircle:
    """Unit circle tilted 45° around X axis → still 'circle'; normal correctly oriented."""

    def setup_method(self):
        # Tilt: plane normal should be [0, -sin45, cos45] = [0, -√2/2, √2/2]
        angle = math.pi / 4.0
        # X axis stays [1,0,0]; Y axis tilts to [0, cos45, sin45]
        x_axis = np.array([1.0, 0.0, 0.0])
        y_axis = np.array([0.0, math.cos(angle), math.sin(angle)])
        self.curve = make_circle_nurbs(
            center=np.array([0.0, 0.0, 0.0]),
            radius=1.0,
            x_axis=x_axis,
            y_axis=y_axis,
        )
        self.expected_normal = np.array([0.0, -math.sin(angle), math.cos(angle)])
        self.info = detect_conic(self.curve, tol=1e-6)

    def test_detected_as_conic(self):
        assert self.info is not None, "tilted circle must be detected"

    def test_kind_is_circle(self):
        assert self.info.kind == 'circle', f"expected 'circle', got '{self.info.kind}'"

    def test_radius(self):
        r = (self.info.radii[0] + self.info.radii[1]) / 2.0
        assert abs(r - 1.0) < 1e-6, f"expected radius 1.0, got {r}"

    def test_plane_normal_direction(self):
        n = self.info.plane_normal
        # Allow sign flip (normal can point either way).
        dot = abs(float(np.dot(n, self.expected_normal)))
        assert dot > 1.0 - 1e-6, \
            f"plane_normal {n} should be parallel to {self.expected_normal}; |dot|={dot}"

    def test_center_near_origin(self):
        assert np.allclose(self.info.center, [0.0, 0.0, 0.0], atol=1e-6)

    def test_plane_normal_unit(self):
        n = self.info.plane_normal
        assert abs(np.linalg.norm(n) - 1.0) < 1e-9
