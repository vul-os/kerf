"""Tests for NURBS-CURVE-FIT-G2 (curve_fit_g2.py).

Covers:
  - Straight line with zero-curvature endpoints
  - Circle arc with matching tangent + curvature
  - G2 endpoint constraint residuals
  - Free-form 8-point curve with prescribed end conditions
  - Additional edge cases: minimal points, degenerate curvature, large dataset,
    degree parameter, non-unit tangents, planar vs 3D, etc.
"""
from __future__ import annotations

import math
import pytest
import numpy as np

from kerf_cad_core.geom.curve_fit_g2 import G2FitSpec, G2FitResult, fit_curve_g2
from kerf_cad_core.geom.nurbs import NurbsCurve, curve_derivative


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _eval_curve(curve: NurbsCurve, t: float) -> np.ndarray:
    return curve.evaluate(float(t))


def _deriv_curve(curve: NurbsCurve, t: float, order: int = 1) -> np.ndarray:
    return curve.derivative(float(t), order=order)


def _circle_arc_points(R: float, theta_start: float, theta_end: float, n: int):
    """n points on a circle arc in the XY plane."""
    thetas = np.linspace(theta_start, theta_end, n)
    pts = [(R * math.cos(th), R * math.sin(th), 0.0) for th in thetas]
    return pts, thetas


def _circle_tangent_at(R: float, theta: float, speed: float = 1.0):
    """C'(t) for a chord-length reparametrized circle (approximate using R*dθ/dt).
    Here we provide the parametric derivative for a unit-arc-length circle
    with total arc = R*(theta_end - theta_start).
    """
    # For a circle C(theta)=(R cos θ, R sin θ, 0), C'_θ = (-R sin θ, R cos θ, 0).
    # When chord-length parametrized, the chain rule gives a scaled version.
    # We pass the raw geometric tangent and let the solver normalise via lstsq.
    return (-R * math.sin(theta) * speed,
             R * math.cos(theta) * speed,
             0.0)


def _circle_curvature_at(R: float, theta: float, speed: float = 1.0):
    """C''(t) for a circle (second parametric derivative w.r.t. arc parameter)."""
    return (-R * math.cos(theta) * speed * speed,
            -R * math.sin(theta) * speed * speed,
            0.0)


# ---------------------------------------------------------------------------
# Test 1: Straight line — zero curvature endpoints, residual < 1e-9
# ---------------------------------------------------------------------------

def test_straight_line_zero_curvature():
    """4 collinear points with zero curvature at both ends."""
    pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)]
    T0 = (1.0, 0.0, 0.0)
    K0 = (0.0, 0.0, 0.0)
    T1 = (1.0, 0.0, 0.0)
    K1 = (0.0, 0.0, 0.0)

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=T0,
        start_curvature_xyz=K0,
        end_tangent_xyz=T1,
        end_curvature_xyz=K1,
    )
    result = fit_curve_g2(spec, degree=5)

    assert isinstance(result, G2FitResult)
    assert result.max_residual_mm < 1e-9, f"max_residual={result.max_residual_mm}"
    assert result.mean_residual_mm < 1e-9
    assert result.start_g2_residual < 1e-9
    assert result.end_g2_residual < 1e-9


def test_straight_line_8_points():
    """8 collinear points — residual must remain small."""
    n = 8
    pts = [(float(i), 0.0, 0.0) for i in range(n)]
    T0 = (1.0, 0.0, 0.0)
    K0 = (0.0, 0.0, 0.0)
    T1 = (1.0, 0.0, 0.0)
    K1 = (0.0, 0.0, 0.0)

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=T0,
        start_curvature_xyz=K0,
        end_tangent_xyz=T1,
        end_curvature_xyz=K1,
    )
    result = fit_curve_g2(spec, degree=5)
    assert result.max_residual_mm < 1e-9, f"max_residual={result.max_residual_mm}"
    assert result.start_g2_residual < 1e-9
    assert result.end_g2_residual < 1e-9


# ---------------------------------------------------------------------------
# Test 2: Circle arc — tangent + curvature matching, residual < 1e-6
# ---------------------------------------------------------------------------

def test_circle_arc_g2_residual():
    """6 points on a circle arc R=10; tangent + curvature at endpoints matched."""
    R = 10.0
    theta_start = 0.0
    theta_end = math.pi / 2.0
    n_pts = 6
    pts, thetas = _circle_arc_points(R, theta_start, theta_end, n_pts)

    # Arc length of the segment — used to approximate parametric speed.
    arc = R * (theta_end - theta_start)

    # C'(t) for a constant-arc-length parameter: magnitude ≈ arc.
    T0 = _circle_tangent_at(R, theta_start, speed=arc)
    T1 = _circle_tangent_at(R, theta_end, speed=arc)
    K0 = _circle_curvature_at(R, theta_start, speed=arc)
    K1 = _circle_curvature_at(R, theta_end, speed=arc)

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=T0,
        start_curvature_xyz=K0,
        end_tangent_xyz=T1,
        end_curvature_xyz=K1,
    )
    result = fit_curve_g2(spec, degree=5)

    assert result.max_residual_mm < 1e-6, f"max_residual={result.max_residual_mm}"
    assert result.mean_residual_mm < 1e-6


def test_circle_arc_g2_constraints_satisfied():
    """G2 endpoint constraints satisfied to within 1e-9 for circle arc."""
    R = 5.0
    theta_start = 0.0
    theta_end = math.pi / 3.0
    n_pts = 8
    pts, _ = _circle_arc_points(R, theta_start, theta_end, n_pts)

    arc = R * (theta_end - theta_start)
    T0 = _circle_tangent_at(R, theta_start, speed=arc)
    T1 = _circle_tangent_at(R, theta_end, speed=arc)
    K0 = _circle_curvature_at(R, theta_start, speed=arc)
    K1 = _circle_curvature_at(R, theta_end, speed=arc)

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=T0,
        start_curvature_xyz=K0,
        end_tangent_xyz=T1,
        end_curvature_xyz=K1,
    )
    result = fit_curve_g2(spec, degree=5)

    # Evaluate fitted curve derivative at endpoints directly.
    curve = result.fitted_curve
    C2_start = _deriv_curve(curve, 0.0, order=2)
    C2_end = _deriv_curve(curve, 1.0, order=2)
    C1_start = _deriv_curve(curve, 0.0, order=1)
    C1_end = _deriv_curve(curve, 1.0, order=1)

    assert np.linalg.norm(C2_start - np.array(K0)) < 1e-9
    assert np.linalg.norm(C2_end - np.array(K1)) < 1e-9
    assert np.linalg.norm(C1_start - np.array(T0)) < 1e-9
    assert np.linalg.norm(C1_end - np.array(T1)) < 1e-9


# ---------------------------------------------------------------------------
# Test 3: Explicit G2 constraint satisfaction (within 1e-9)
# ---------------------------------------------------------------------------

def test_g2_start_constraint():
    """G2 start-point second-derivative constraint satisfied < 1e-9."""
    pts = [(float(i), float(i) * float(i) * 0.1, 0.0) for i in range(10)]
    T0 = (1.0, 0.0, 0.0)
    K0 = (0.0, 0.5, 0.0)
    T1 = (1.0, 2.0, 0.0)
    K1 = (0.0, 0.5, 0.0)

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=T0,
        start_curvature_xyz=K0,
        end_tangent_xyz=T1,
        end_curvature_xyz=K1,
    )
    result = fit_curve_g2(spec, degree=5)

    C2_start = _deriv_curve(result.fitted_curve, 0.0, order=2)
    assert np.linalg.norm(C2_start - np.array(K0)) < 1e-9


def test_g2_end_constraint():
    """G2 end-point second-derivative constraint satisfied < 1e-9."""
    pts = [(float(i), math.sin(float(i) * 0.5), 0.0) for i in range(10)]
    T0 = (0.5, math.cos(0.0) * 0.5, 0.0)
    K0 = (0.0, -math.sin(0.0) * 0.25, 0.0)
    T1 = (0.5, math.cos(4.5) * 0.5, 0.0)
    K1 = (0.0, -math.sin(4.5) * 0.25, 0.0)

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=T0,
        start_curvature_xyz=K0,
        end_tangent_xyz=T1,
        end_curvature_xyz=K1,
    )
    result = fit_curve_g2(spec, degree=5)

    C2_end = _deriv_curve(result.fitted_curve, 1.0, order=2)
    assert np.linalg.norm(C2_end - np.array(K1)) < 1e-9


def test_g1_start_constraint():
    """G1 start tangent constraint satisfied < 1e-9."""
    pts = [(float(i), float(i) * 0.5, float(i) * 0.2) for i in range(10)]
    T0 = (2.0, 1.0, 0.4)
    K0 = (0.0, 0.0, 0.0)
    T1 = (1.0, 0.5, 0.2)
    K1 = (0.0, 0.0, 0.0)

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=T0,
        start_curvature_xyz=K0,
        end_tangent_xyz=T1,
        end_curvature_xyz=K1,
    )
    result = fit_curve_g2(spec, degree=5)

    C1_start = _deriv_curve(result.fitted_curve, 0.0, order=1)
    assert np.linalg.norm(C1_start - np.array(T0)) < 1e-9


def test_g1_end_constraint():
    """G1 end tangent constraint satisfied < 1e-9."""
    pts = [(float(i), float(i) * 0.3, float(i) * 0.1) for i in range(10)]
    T0 = (1.0, 0.3, 0.1)
    K0 = (0.0, 0.0, 0.0)
    T1 = (3.0, 0.9, 0.3)
    K1 = (0.0, 0.0, 0.0)

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=T0,
        start_curvature_xyz=K0,
        end_tangent_xyz=T1,
        end_curvature_xyz=K1,
    )
    result = fit_curve_g2(spec, degree=5)

    C1_end = _deriv_curve(result.fitted_curve, 1.0, order=1)
    assert np.linalg.norm(C1_end - np.array(T1)) < 1e-9


# ---------------------------------------------------------------------------
# Test 4: Free-form 8 points with prescribed end conditions
# ---------------------------------------------------------------------------

def test_freeform_8_points():
    """8 free-form 3-D points with generic prescribed end conditions."""
    pts = [
        (0.0, 0.0, 0.0),
        (1.0, 0.5, 0.2),
        (2.0, 1.2, 0.8),
        (3.0, 0.9, 1.5),
        (4.0, 0.3, 1.8),
        (5.0, -0.4, 1.2),
        (6.0, -0.2, 0.5),
        (7.0, 0.0, 0.0),
    ]
    T0 = (1.5, 1.0, 0.4)
    K0 = (0.0, -0.5, 0.2)
    T1 = (1.5, 0.5, -0.8)
    K1 = (0.0, -0.3, -0.4)

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=T0,
        start_curvature_xyz=K0,
        end_tangent_xyz=T1,
        end_curvature_xyz=K1,
    )
    result = fit_curve_g2(spec, degree=5)

    assert isinstance(result.fitted_curve, NurbsCurve)
    assert result.fitted_curve.degree == 5
    # G2 constraints tight.
    assert result.start_g2_residual < 1e-9
    assert result.end_g2_residual < 1e-9
    # G1 constraints tight.
    C1_start = _deriv_curve(result.fitted_curve, 0.0, order=1)
    C1_end = _deriv_curve(result.fitted_curve, 1.0, order=1)
    assert np.linalg.norm(C1_start - np.array(T0)) < 1e-9
    assert np.linalg.norm(C1_end - np.array(T1)) < 1e-9
    # Honest caveat non-empty.
    assert result.honest_caveat != ""


# ---------------------------------------------------------------------------
# Test 5: Return type and structure
# ---------------------------------------------------------------------------

def test_result_dataclass_fields():
    """G2FitResult has all required fields with correct types."""
    pts = [(float(i), 0.0, 0.0) for i in range(6)]
    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=(1.0, 0.0, 0.0),
        start_curvature_xyz=(0.0, 0.0, 0.0),
        end_tangent_xyz=(1.0, 0.0, 0.0),
        end_curvature_xyz=(0.0, 0.0, 0.0),
    )
    result = fit_curve_g2(spec)

    assert hasattr(result, "fitted_curve")
    assert hasattr(result, "max_residual_mm")
    assert hasattr(result, "mean_residual_mm")
    assert hasattr(result, "start_g2_residual")
    assert hasattr(result, "end_g2_residual")
    assert hasattr(result, "honest_caveat")
    assert isinstance(result.fitted_curve, NurbsCurve)
    assert isinstance(result.max_residual_mm, float)
    assert isinstance(result.mean_residual_mm, float)
    assert isinstance(result.honest_caveat, str)
    assert len(result.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Test 6: NurbsCurve properties
# ---------------------------------------------------------------------------

def test_nurbs_curve_degree_5_default():
    """Default output is degree 5."""
    pts = [(float(i), float(i) * 0.1, 0.0) for i in range(8)]
    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=(1.0, 0.1, 0.0),
        start_curvature_xyz=(0.0, 0.0, 0.0),
        end_tangent_xyz=(1.0, 0.1, 0.0),
        end_curvature_xyz=(0.0, 0.0, 0.0),
    )
    result = fit_curve_g2(spec)
    assert result.fitted_curve.degree == 5


def test_nurbs_curve_degree_3():
    """degree=3 produces degree-3 curve with G2 constraints satisfied."""
    pts = [(float(i), float(i) * 0.2, 0.0) for i in range(8)]
    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=(1.0, 0.2, 0.0),
        start_curvature_xyz=(0.0, 0.0, 0.0),
        end_tangent_xyz=(1.0, 0.2, 0.0),
        end_curvature_xyz=(0.0, 0.0, 0.0),
    )
    result = fit_curve_g2(spec, degree=3)
    assert result.fitted_curve.degree == 3
    assert result.start_g2_residual < 1e-9
    assert result.end_g2_residual < 1e-9


def test_nurbs_curve_knots_clamped():
    """Knot vector is clamped (first/last value repeated degree+1 times)."""
    pts = [(float(i), 0.0, 0.0) for i in range(8)]
    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=(1.0, 0.0, 0.0),
        start_curvature_xyz=(0.0, 0.0, 0.0),
        end_tangent_xyz=(1.0, 0.0, 0.0),
        end_curvature_xyz=(0.0, 0.0, 0.0),
    )
    result = fit_curve_g2(spec, degree=5)
    knots = result.fitted_curve.knots
    deg = result.fitted_curve.degree
    assert all(abs(knots[i] - 0.0) < 1e-14 for i in range(deg + 1)), \
        f"Start knots not clamped to 0: {knots[:deg+1]}"
    assert all(abs(knots[-(i + 1)] - 1.0) < 1e-14 for i in range(deg + 1)), \
        f"End knots not clamped to 1: {knots[-(deg+1):]}"


def test_control_points_shape():
    """Control points are (n, 3) shaped."""
    pts = [(float(i), float(i) * 0.3, float(i) * 0.1) for i in range(8)]
    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=(1.0, 0.3, 0.1),
        start_curvature_xyz=(0.0, 0.0, 0.0),
        end_tangent_xyz=(1.0, 0.3, 0.1),
        end_curvature_xyz=(0.0, 0.0, 0.0),
    )
    result = fit_curve_g2(spec)
    cp = result.fitted_curve.control_points
    assert cp.ndim == 2
    assert cp.shape[1] == 3


# ---------------------------------------------------------------------------
# Test 7: Endpoint interpolation
# ---------------------------------------------------------------------------

def test_start_endpoint_interpolated():
    """Fitted curve evaluates exactly at the first data point."""
    pts = [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.5, 0.0),
           (3.0, 1.5, 0.0), (4.0, 0.0, 0.0), (5.0, 1.0, 0.0)]
    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=(2.0, 2.0, 0.0),
        start_curvature_xyz=(0.0, -1.0, 0.0),
        end_tangent_xyz=(2.0, 1.0, 0.0),
        end_curvature_xyz=(0.0, 0.5, 0.0),
    )
    result = fit_curve_g2(spec)
    pt_start = _eval_curve(result.fitted_curve, 0.0)
    assert np.linalg.norm(pt_start - np.array([0.0, 0.0, 0.0])) < 1e-9


def test_end_endpoint_interpolated():
    """Fitted curve evaluates exactly at the last data point."""
    pts = [(0.0, 0.0, 0.0), (1.0, 1.0, 0.0), (2.0, 0.5, 0.0),
           (3.0, 1.5, 0.0), (4.0, 0.0, 0.0), (5.0, 1.0, 0.0)]
    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=(2.0, 2.0, 0.0),
        start_curvature_xyz=(0.0, -1.0, 0.0),
        end_tangent_xyz=(2.0, 1.0, 0.0),
        end_curvature_xyz=(0.0, 0.5, 0.0),
    )
    result = fit_curve_g2(spec)
    pt_end = _eval_curve(result.fitted_curve, 1.0)
    assert np.linalg.norm(pt_end - np.array([5.0, 1.0, 0.0])) < 1e-9


# ---------------------------------------------------------------------------
# Test 8: 3-D non-planar free-form curve
# ---------------------------------------------------------------------------

def test_3d_freeform_12_points():
    """12 3-D non-planar points — residuals finite, G2 constraints tight."""
    rng = np.random.default_rng(seed=42)
    base = np.linspace(0, 1, 12)
    pts_arr = np.column_stack([base, np.sin(base * 2 * math.pi), np.cos(base * 3)])
    pts = [tuple(p) for p in pts_arr]

    # Tangent and curvature from analytic derivatives of the parametric curve.
    def _f(t):
        return np.array([t, math.sin(t * 2 * math.pi), math.cos(t * 3)])

    def _df(t):
        return np.array([1.0, 2 * math.pi * math.cos(t * 2 * math.pi), -3 * math.sin(t * 3)])

    def _d2f(t):
        return np.array([0.0,
                         -4 * math.pi ** 2 * math.sin(t * 2 * math.pi),
                         -9 * math.cos(t * 3)])

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=tuple(_df(0.0)),
        start_curvature_xyz=tuple(_d2f(0.0)),
        end_tangent_xyz=tuple(_df(1.0)),
        end_curvature_xyz=tuple(_d2f(1.0)),
    )
    result = fit_curve_g2(spec, degree=5)

    assert result.start_g2_residual < 1e-9
    assert result.end_g2_residual < 1e-9
    assert math.isfinite(result.max_residual_mm)
    assert result.max_residual_mm >= 0.0


# ---------------------------------------------------------------------------
# Test 9: Non-zero 3D curvature vectors at both ends
# ---------------------------------------------------------------------------

def test_nonzero_3d_curvature_vectors():
    """G2 constraints with genuinely non-zero 3D curvature vectors."""
    n = 10
    pts = [(float(i), math.sin(float(i)), math.cos(float(i) * 0.5)) for i in range(n)]
    T0 = (1.0, 1.0, -0.5)
    K0 = (0.0, -1.0, -0.25)
    T1 = (1.0, math.cos(float(n - 1)), -0.5 * math.sin(float(n - 1) * 0.5))
    K1 = (0.0, -math.sin(float(n - 1)), -0.25 * math.cos(float(n - 1) * 0.5))

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=T0,
        start_curvature_xyz=K0,
        end_tangent_xyz=T1,
        end_curvature_xyz=K1,
    )
    result = fit_curve_g2(spec, degree=5)

    C2_start = _deriv_curve(result.fitted_curve, 0.0, order=2)
    C2_end = _deriv_curve(result.fitted_curve, 1.0, order=2)

    assert np.linalg.norm(C2_start - np.array(K0)) < 1e-9
    assert np.linalg.norm(C2_end - np.array(K1)) < 1e-9


# ---------------------------------------------------------------------------
# Test 10: Degree-2 raise (minimum allowed degree)
# ---------------------------------------------------------------------------

def test_degree_2_minimum_allowed():
    """degree=2 is the minimum for G2 — should not raise."""
    pts = [(float(i), float(i) ** 2 * 0.1, 0.0) for i in range(8)]
    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=(1.0, 0.0, 0.0),
        start_curvature_xyz=(0.0, 0.2, 0.0),
        end_tangent_xyz=(1.0, 1.4, 0.0),
        end_curvature_xyz=(0.0, 0.2, 0.0),
    )
    result = fit_curve_g2(spec, degree=2)
    assert result.fitted_curve.degree == 2
    assert result.start_g2_residual < 1e-9
    assert result.end_g2_residual < 1e-9


def test_degree_1_raises():
    """degree < 2 must raise ValueError."""
    pts = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)]
    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=(1.0, 0.0, 0.0),
        start_curvature_xyz=(0.0, 0.0, 0.0),
        end_tangent_xyz=(1.0, 0.0, 0.0),
        end_curvature_xyz=(0.0, 0.0, 0.0),
    )
    with pytest.raises(ValueError, match="degree must be >= 2"):
        fit_curve_g2(spec, degree=1)


# ---------------------------------------------------------------------------
# Test 11: Residuals are non-negative
# ---------------------------------------------------------------------------

def test_residuals_nonnegative():
    """max_residual_mm and mean_residual_mm are >= 0."""
    pts = [(float(i), float(i) * 0.7, float(i) * 0.3) for i in range(10)]
    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=(1.0, 0.7, 0.3),
        start_curvature_xyz=(0.0, 0.0, 0.0),
        end_tangent_xyz=(1.0, 0.7, 0.3),
        end_curvature_xyz=(0.0, 0.0, 0.0),
    )
    result = fit_curve_g2(spec)
    assert result.max_residual_mm >= 0.0
    assert result.mean_residual_mm >= 0.0
    assert result.max_residual_mm >= result.mean_residual_mm


# ---------------------------------------------------------------------------
# Test 12: G2 residual fields match manually computed residuals
# ---------------------------------------------------------------------------

def test_g2_residual_fields_match_manual():
    """start_g2_residual/end_g2_residual match manually evaluated C''."""
    pts = [(float(i), float(i) ** 2 * 0.05, 0.0) for i in range(10)]
    K0 = (0.0, 0.1, 0.0)
    K1 = (0.0, 0.1, 0.0)
    T0 = (1.0, 0.0, 0.0)
    T1 = (1.0, 0.9, 0.0)

    spec = G2FitSpec(
        data_points=pts,
        start_tangent_xyz=T0,
        start_curvature_xyz=K0,
        end_tangent_xyz=T1,
        end_curvature_xyz=K1,
    )
    result = fit_curve_g2(spec, degree=5)
    curve = result.fitted_curve

    C2_start = _deriv_curve(curve, 0.0, order=2)
    C2_end = _deriv_curve(curve, 1.0, order=2)

    expected_start = float(np.linalg.norm(C2_start - np.array(K0)))
    expected_end = float(np.linalg.norm(C2_end - np.array(K1)))

    assert abs(result.start_g2_residual - expected_start) < 1e-14
    assert abs(result.end_g2_residual - expected_end) < 1e-14
