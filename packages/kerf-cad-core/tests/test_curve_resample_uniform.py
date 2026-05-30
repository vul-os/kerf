"""
Tests for curve_resample_uniform.py — NURBS-CURVE-RESAMPLE-UNIFORM

Analytic oracles
----------------
1. Unit circle (radius 1, rational NURBS): 100 uniform-arc samples →
   consecutive point distances = 2π/100 ± 0.001.
2. Non-uniform-CP cubic: 50 samples → distances uniform to ± 2% of mean.
3. Parabola: arc-uniform vs parameter-uniform → arc-uniform has lower
   distance variance (proves even spread vs endpoint bunching).
4. Oracle distances on line: length = sqrt(2), resample to 10 →
   each step = sqrt(2)/10 within 1e-6.
5. Degenerate (zero-length) curve → ResampleResult.degenerate=True;
   all points equal start point.
6. fit=True returns a NurbsCurve whose degree and num_ctrl are sane.
7. ResampleResult.arc_lengths[0]==0 and arc_lengths[-1]==total_length.
8. samples=1 → exactly 2 points: start and end.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    make_circle_nurbs,
    make_line_nurbs,
    de_boor,
)
from kerf_cad_core.geom.curve_toolkit import interp_curve
from kerf_cad_core.geom.curve_resample_uniform import (
    ResampleResult,
    resample_uniform_arc_length,
)

_ORIGIN = np.array([0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parabola_curve(n_ctrl: int = 20) -> NurbsCurve:
    """Non-uniform-CP parabola y = x^2 for x in [-1, 1].

    Uses centripetal parameterisation so the control points cluster
    near x=0 (the flat part), creating non-uniform parameter spacing
    if evaluated uniformly in u.
    """
    xs = np.linspace(-1.0, 1.0, n_ctrl)
    pts = np.column_stack([xs, xs ** 2, np.zeros(n_ctrl)])
    return interp_curve(pts, degree=3, param="chord")


def _cubic_wave() -> NurbsCurve:
    """Degree-3 spline through a sine-wave; non-uniform tangent speeds."""
    xs = np.linspace(0.0, 2.0 * math.pi, 40)
    pts = np.column_stack([xs, np.sin(xs), np.zeros_like(xs)])
    return interp_curve(pts, degree=3)


def _line_45deg() -> NurbsCurve:
    """Degree-1 NURBS from (0,0,0) to (1,1,0); length = sqrt(2)."""
    ctrl = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 0.0]])
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=ctrl, knots=knots)


def _degenerate_curve() -> NurbsCurve:
    """Degree-1 NURBS with coincident endpoints → zero length."""
    ctrl = np.array([[1.0, 2.0, 3.0], [1.0, 2.0, 3.0]])
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=ctrl, knots=knots)


def _consecutive_distances(pts: np.ndarray) -> np.ndarray:
    """Return array of |pts[i+1] - pts[i]| for all i."""
    return np.linalg.norm(np.diff(pts, axis=0), axis=1)


# ---------------------------------------------------------------------------
# Test 1: unit circle, 100 samples — depth bar
# ---------------------------------------------------------------------------

def test_circle_100_uniform_arc_distances():
    """Unit circle: 100 arc-uniform samples → step distance = 2π/100 ± 0.001."""
    circle = make_circle_nurbs(center=_ORIGIN, radius=1.0)
    result = resample_uniform_arc_length(circle, samples=100)

    assert isinstance(result, ResampleResult)
    assert len(result.points) == 101
    assert not result.degenerate

    dists = _consecutive_distances(result.points)
    expected = 2.0 * math.pi / 100.0  # ≈ 0.06283
    assert dists.max() - dists.min() < 0.001, (
        f"Distance spread too large: max={dists.max():.6f} min={dists.min():.6f}"
    )
    np.testing.assert_allclose(dists, expected, atol=0.001)


# ---------------------------------------------------------------------------
# Test 2: circle total_length ≈ 2π
# ---------------------------------------------------------------------------

def test_circle_total_length():
    """Unit circle total_length should be 2π within 1e-6."""
    circle = make_circle_nurbs(center=_ORIGIN, radius=1.0)
    result = resample_uniform_arc_length(circle, samples=50)
    assert abs(result.total_length - 2.0 * math.pi) < 1e-6


# ---------------------------------------------------------------------------
# Test 3: non-uniform-CP cubic — uniform distances
# ---------------------------------------------------------------------------

def test_cubic_wave_uniform_arc_distances():
    """Cubic wave: 50 arc-uniform samples → distances uniform within 2% of mean."""
    curve = _cubic_wave()
    result = resample_uniform_arc_length(curve, samples=50)

    dists = _consecutive_distances(result.points)
    mean_d = dists.mean()
    assert mean_d > 0.0
    relative_spread = (dists.max() - dists.min()) / mean_d
    assert relative_spread < 0.02, (
        f"Relative spread {relative_spread:.4f} exceeds 2% tolerance"
    )


# ---------------------------------------------------------------------------
# Test 4: parabola — arc-uniform vs parameter-uniform variance
# ---------------------------------------------------------------------------

def test_parabola_arc_vs_param_uniform():
    """Parabola: arc-uniform distances have strictly lower variance than
    parameter-uniform distances (proves even spread vs endpoint bunching)."""
    N = 50
    curve = _parabola_curve()

    # Arc-uniform
    result_arc = resample_uniform_arc_length(curve, samples=N)
    dists_arc = _consecutive_distances(result_arc.points)

    # Parameter-uniform (reference)
    u0 = float(curve.knots[curve.degree])
    u1 = float(curve.knots[-(curve.degree + 1)])
    us_param = np.linspace(u0, u1, N + 1)
    pts_param = np.array([de_boor(curve, float(u)) for u in us_param])
    dists_param = _consecutive_distances(pts_param)

    var_arc = float(np.var(dists_arc))
    var_param = float(np.var(dists_param))

    assert var_arc < var_param, (
        f"Arc-uniform variance {var_arc:.6e} should be < param-uniform "
        f"variance {var_param:.6e}"
    )


# ---------------------------------------------------------------------------
# Test 5: oracle distances on 45° line
# ---------------------------------------------------------------------------

def test_line_oracle_distances():
    """45° line (length=sqrt(2)): 10 samples → each step = sqrt(2)/10 within 1e-6."""
    line = _line_45deg()
    result = resample_uniform_arc_length(line, samples=10)

    expected_step = math.sqrt(2.0) / 10.0
    dists = _consecutive_distances(result.points)
    np.testing.assert_allclose(dists, expected_step, atol=1e-6)


# ---------------------------------------------------------------------------
# Test 6: degenerate (zero-length) curve
# ---------------------------------------------------------------------------

def test_degenerate_curve():
    """Zero-length curve → degenerate=True; all points == start point."""
    curve = _degenerate_curve()
    result = resample_uniform_arc_length(curve, samples=10)

    assert result.degenerate is True
    assert result.total_length == 0.0

    # All points should be equal to the start control point
    start_pt = np.array([1.0, 2.0, 3.0])
    for pt in result.points:
        np.testing.assert_allclose(pt, start_pt, atol=1e-12)


# ---------------------------------------------------------------------------
# Test 7: arc_lengths bookkeeping
# ---------------------------------------------------------------------------

def test_arc_lengths_bookkeeping():
    """arc_lengths[0]==0, arc_lengths[-1]==total_length; monotone."""
    curve = _cubic_wave()
    result = resample_uniform_arc_length(curve, samples=30)

    assert result.arc_lengths[0] == 0.0
    assert abs(result.arc_lengths[-1] - result.total_length) < 1e-12
    # Monotone
    diffs = np.diff(result.arc_lengths)
    assert (diffs >= 0).all(), "arc_lengths not monotonically non-decreasing"


# ---------------------------------------------------------------------------
# Test 8: samples=1 → 2 points (start and end)
# ---------------------------------------------------------------------------

def test_single_interval():
    """samples=1 → exactly 2 points at curve start and end."""
    line = _line_45deg()
    result = resample_uniform_arc_length(line, samples=1)

    assert len(result.points) == 2
    assert len(result.parameters) == 2
    assert len(result.arc_lengths) == 2

    # points[0] at start, points[1] at end
    u0 = float(line.knots[line.degree])
    u1 = float(line.knots[-(line.degree + 1)])
    np.testing.assert_allclose(result.points[0], de_boor(line, u0), atol=1e-12)
    np.testing.assert_allclose(result.points[1], de_boor(line, u1), atol=1e-12)


# ---------------------------------------------------------------------------
# Test 9: fit=True returns a sensible NurbsCurve
# ---------------------------------------------------------------------------

def test_fit_returns_curve():
    """fit=True returns a NurbsCurve with consistent degree and CP count."""
    curve = _cubic_wave()
    result = resample_uniform_arc_length(curve, samples=20, fit=True)

    assert result.fitted_curve is not None
    fc = result.fitted_curve
    assert fc.degree >= 1
    assert len(fc.control_points) >= fc.degree + 1
    # Knot count = n_ctrl + degree + 1
    assert len(fc.knots) == len(fc.control_points) + fc.degree + 1


# ---------------------------------------------------------------------------
# Test 10: non-uniform CP weights (rational NURBS) — distances still uniform
# ---------------------------------------------------------------------------

def test_rational_circle_non_uniform_cp():
    """Rational circle with known non-uniform CP spacing: 100 resample →
    distances near 2π/100.  Tests the rational path through curve_derivative."""
    circle = make_circle_nurbs(center=_ORIGIN, radius=1.0)
    result = resample_uniform_arc_length(circle, samples=100)
    dists = _consecutive_distances(result.points)
    expected = 2.0 * math.pi / 100.0
    np.testing.assert_allclose(dists, expected, atol=0.001)


# ---------------------------------------------------------------------------
# Test 11: parameters monotonically increasing
# ---------------------------------------------------------------------------

def test_parameters_monotone():
    """Returned parameters must be monotonically non-decreasing."""
    curve = _parabola_curve()
    result = resample_uniform_arc_length(curve, samples=40)
    diffs = np.diff(result.parameters)
    assert (diffs >= -1e-15).all(), "parameters not monotonically non-decreasing"


# ---------------------------------------------------------------------------
# Test 12: large circle (radius=5) — scale-correct
# ---------------------------------------------------------------------------

def test_large_circle_radius_5():
    """Circle radius=5: total_length = 10π; 50 samples each ~10π/50."""
    circle = make_circle_nurbs(center=_ORIGIN, radius=5.0)
    result = resample_uniform_arc_length(circle, samples=50)
    assert abs(result.total_length - 10.0 * math.pi) < 1e-4
    dists = _consecutive_distances(result.points)
    np.testing.assert_allclose(dists, 10.0 * math.pi / 50.0, atol=0.01)
