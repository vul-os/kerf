"""
Tests for curve_inflection.py — NURBS-CURVE-INFLECTION.

Finds inflection points of a 2D NurbsCurve where κ_signed changes sign.

Test plan (12+ tests)
---------------------
01. Cubic spline with one inflection near t=0.5: detects exactly 1 inflection.
02. Cubic spline with one inflection: inflection t is close to 0.5.
03. S-shaped cubic Bezier: exactly 1 inflection detected.
04. S-curve inflection: parameter in [0.4, 0.6] (near midpoint).
05. Circle (constant curvature): 0 inflections.
06. Straight line (κ=0 everywhere): 0 inflections + honest_caveat non-empty.
07. Straight line: honest_caveat mentions "zero" or "line" or "straight".
08. Sine curve approximation: multiple inflections (≥ 2 per arch crossing).
09. Parabola y = x²: 0 inflections (monotone curvature sign).
10. Return type is InflectionResult dataclass.
11. signed_curvature_samples length equals num_samples.
12. num_inflections == len(inflection_t_params).
13. Inflection t-values are within parameter domain [t_min, t_max].
14. Non-NurbsCurve input returns InflectionResult (no exception).
15. Raw (t, κ) samples input works correctly (direct sign-change detection).
16. Threshold parameter: raising threshold to 0.5 suppresses near-zero crossings.
17. High-curvature spiral-like curve: at least 1 inflection detected.
18. num_samples parameter is respected: len(signed_curvature_samples) == num_samples.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    make_circle_nurbs,
    make_line_nurbs,
)
from kerf_cad_core.geom.curve_inflection import (
    InflectionResult,
    find_curve_inflections,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_s_curve_cubic() -> NurbsCurve:
    """Degree-3 Bezier with control points forming an S.

    CPs: (0,0), (0.5,1), (0.5,-1), (1,0) — classical S-curve with one
    inflection near t=0.5.
    """
    cps = np.array([
        [0.0,  0.0, 0.0],
        [0.5,  1.0, 0.0],
        [0.5, -1.0, 0.0],
        [1.0,  0.0, 0.0],
    ])
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=cps, knots=knots)


def _make_cubic_one_inflection() -> NurbsCurve:
    """Degree-3 Bezier with a single inflection near t=0.5.

    Control points: (0,0), (1,-2), (2,2), (3,0).
    The y-coordinates alternate sign, creating an S-shape with one inflection.
    """
    cps = np.array([
        [0.0,  0.0, 0.0],
        [1.0, -2.0, 0.0],
        [2.0,  2.0, 0.0],
        [3.0,  0.0, 0.0],
    ])
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=cps, knots=knots)


def _make_sine_approx_nurbs() -> NurbsCurve:
    """A degree-3 NURBS approximating sin(x) over [0, 3π] — multiple arches.

    Two full arches of a sine: expects inflection points near x = π and x = 2π
    (parameter crossings ≈ 1/3 and 2/3 of the domain).
    We interpolate key points of y = sin(2πx) on [0, 1] using a dense
    degree-3 NURBS.
    """
    # 13 control points along a two-arch sine shape
    n = 13
    xs = np.linspace(0, 1, n)
    ys = np.sin(4 * np.pi * xs)
    cps = np.column_stack([xs, ys, np.zeros(n)])
    # Uniform clamped knot vector for degree 3
    m = n + 3 + 1  # m = n+p+1 total knots, n control points, p=degree=3
    # Clamped: first p+1 at 0, last p+1 at 1, interior uniform
    inner = np.linspace(0, 1, m - 2 * (3))
    knots = np.concatenate([[0.0, 0.0, 0.0], inner, [1.0, 1.0, 1.0]])
    return NurbsCurve(degree=3, control_points=cps, knots=knots)


def _make_parabola_nurbs() -> NurbsCurve:
    """Exact degree-2 Bezier for y = x² over [-1, 1].

    For y = x², curvature is always positive (κ > 0 everywhere, monotone in
    magnitude).  No sign change → 0 inflections.
    """
    cps = np.array([[-1.0, 1.0, 0.0],
                    [ 0.0, -1.0, 0.0],
                    [ 1.0,  1.0, 0.0]])
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=2, control_points=cps, knots=knots)


def _make_spiral_segment_nurbs() -> NurbsCurve:
    """A degree-3 cubic that curves sharply one way then the other.

    Control points: (0,0), (2,1), (4,-1), (6,0) — wider S than the unit S.
    Has at least one inflection.
    """
    cps = np.array([
        [0.0,  0.0, 0.0],
        [2.0,  1.5, 0.0],
        [4.0, -1.5, 0.0],
        [6.0,  0.0, 0.0],
    ])
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=cps, knots=knots)


# ---------------------------------------------------------------------------
# Test 01 — cubic spline with one inflection: detect exactly 1
# ---------------------------------------------------------------------------

def test_cubic_one_inflection_count():
    """Cubic S-curve should have exactly 1 inflection."""
    curve = _make_s_curve_cubic()
    result = find_curve_inflections(curve, num_samples=300)
    assert result.num_inflections == 1, (
        f"Expected 1 inflection for S-curve; got {result.num_inflections}"
    )


# ---------------------------------------------------------------------------
# Test 02 — inflection t close to 0.5 for symmetric S
# ---------------------------------------------------------------------------

def test_cubic_s_inflection_near_midpoint():
    """The single inflection of the S-curve should be near t=0.5."""
    curve = _make_s_curve_cubic()
    result = find_curve_inflections(curve, num_samples=300)
    assert result.num_inflections >= 1
    t_inf = result.inflection_t_params[0]
    assert 0.35 <= t_inf <= 0.65, (
        f"S-curve inflection should be near 0.5; got t={t_inf:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 03 — another S-curve variant: exactly 1 inflection
# ---------------------------------------------------------------------------

def test_s_bezier_one_inflection():
    """Wide S-curve (spiral segment) has exactly 1 inflection."""
    curve = _make_spiral_segment_nurbs()
    result = find_curve_inflections(curve, num_samples=400)
    assert result.num_inflections == 1, (
        f"Wide S-curve: expected 1 inflection; got {result.num_inflections}"
    )


# ---------------------------------------------------------------------------
# Test 04 — S-curve inflection in valid range
# ---------------------------------------------------------------------------

def test_s_bezier_inflection_in_range():
    """S-curve inflection should be inside (0, 1)."""
    curve = _make_spiral_segment_nurbs()
    result = find_curve_inflections(curve, num_samples=400)
    assert result.num_inflections >= 1
    t_inf = result.inflection_t_params[0]
    assert 0.0 < t_inf < 1.0, f"t={t_inf:.4f} outside (0,1)"


# ---------------------------------------------------------------------------
# Test 05 — circle: 0 inflections (constant κ)
# ---------------------------------------------------------------------------

def test_circle_zero_inflections():
    """A circle has constant κ — no sign changes — 0 inflections."""
    circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 2.0)
    result = find_curve_inflections(circle, num_samples=200)
    assert result.num_inflections == 0, (
        f"Circle should have 0 inflections; got {result.num_inflections}"
    )


# ---------------------------------------------------------------------------
# Test 06 — straight line: 0 inflections + honest_caveat
# ---------------------------------------------------------------------------

def test_straight_line_zero_inflections():
    """Straight line has κ=0 everywhere — 0 inflections."""
    line = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([3.0, 1.0, 0.0]),
    )
    result = find_curve_inflections(line, num_samples=100)
    assert result.num_inflections == 0, (
        f"Straight line should have 0 inflections; got {result.num_inflections}"
    )


# ---------------------------------------------------------------------------
# Test 07 — straight line: honest_caveat mentions zero/line/straight
# ---------------------------------------------------------------------------

def test_straight_line_honest_caveat():
    """honest_caveat for a straight line should explain the κ=0 situation."""
    line = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([5.0, 0.0, 0.0]),
    )
    result = find_curve_inflections(line, num_samples=100)
    assert result.honest_caveat, "honest_caveat should be non-empty for a straight line"
    caveat_lower = result.honest_caveat.lower()
    assert any(kw in caveat_lower for kw in ("zero", "line", "straight", "flat")), (
        f"honest_caveat should mention zero/line/straight: {result.honest_caveat!r}"
    )


# ---------------------------------------------------------------------------
# Test 08 — sine curve approximation: at least 2 inflections
# ---------------------------------------------------------------------------

def test_sine_curve_multiple_inflections():
    """A two-arch sine should have at least 2 inflection points."""
    curve = _make_sine_approx_nurbs()
    result = find_curve_inflections(curve, num_samples=500)
    assert result.num_inflections >= 2, (
        f"Two-arch sine: expected >= 2 inflections; got {result.num_inflections}"
    )


# ---------------------------------------------------------------------------
# Test 09 — parabola: 0 inflections (κ > 0 everywhere)
# ---------------------------------------------------------------------------

def test_parabola_zero_inflections():
    """A parabola has κ > 0 everywhere — no sign change — 0 inflections."""
    curve = _make_parabola_nurbs()
    result = find_curve_inflections(curve, num_samples=200)
    assert result.num_inflections == 0, (
        f"Parabola should have 0 inflections; got {result.num_inflections}"
    )


# ---------------------------------------------------------------------------
# Test 10 — return type is InflectionResult
# ---------------------------------------------------------------------------

def test_return_type():
    """find_curve_inflections always returns an InflectionResult."""
    curve = _make_s_curve_cubic()
    result = find_curve_inflections(curve)
    assert isinstance(result, InflectionResult)


# ---------------------------------------------------------------------------
# Test 11 — signed_curvature_samples length == num_samples
# ---------------------------------------------------------------------------

def test_signed_curvature_samples_length():
    """signed_curvature_samples must have exactly num_samples entries."""
    curve = _make_s_curve_cubic()
    n = 150
    result = find_curve_inflections(curve, num_samples=n)
    assert len(result.signed_curvature_samples) == n, (
        f"Expected {n} curvature samples; got {len(result.signed_curvature_samples)}"
    )


# ---------------------------------------------------------------------------
# Test 12 — num_inflections == len(inflection_t_params)
# ---------------------------------------------------------------------------

def test_num_inflections_consistent():
    """num_inflections must equal len(inflection_t_params)."""
    for curve in [_make_s_curve_cubic(), make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0)]:
        result = find_curve_inflections(curve)
        assert result.num_inflections == len(result.inflection_t_params), (
            f"Inconsistent: num_inflections={result.num_inflections} "
            f"vs len(inflection_t_params)={len(result.inflection_t_params)}"
        )


# ---------------------------------------------------------------------------
# Test 13 — inflection t-values inside [t_min, t_max]
# ---------------------------------------------------------------------------

def test_inflection_params_in_domain():
    """All inflection t-values must lie within the curve's parameter domain."""
    curve = _make_sine_approx_nurbs()
    result = find_curve_inflections(curve, num_samples=500)
    t_min = float(curve.knots[curve.degree])
    t_max = float(curve.knots[-(curve.degree + 1)])
    for t in result.inflection_t_params:
        assert t_min <= t <= t_max, (
            f"Inflection t={t:.4f} outside domain [{t_min:.4f}, {t_max:.4f}]"
        )


# ---------------------------------------------------------------------------
# Test 14 — non-NurbsCurve input returns InflectionResult without exception
# ---------------------------------------------------------------------------

def test_non_nurbs_input_does_not_raise():
    """Passing a non-NurbsCurve returns InflectionResult with honest_caveat."""
    result = find_curve_inflections("not a curve")
    assert isinstance(result, InflectionResult)
    assert result.num_inflections == 0
    assert result.honest_caveat


# ---------------------------------------------------------------------------
# Test 15 — raw (t, κ) samples input path
# ---------------------------------------------------------------------------

def test_raw_samples_input():
    """Passing pre-computed (t, κ) pairs detects sign changes directly."""
    # Construct samples that cross zero at t=0.5.
    samples = [(i * 0.1, (i * 0.1 - 0.5)) for i in range(11)]  # κ = t - 0.5
    result = find_curve_inflections(samples, threshold=1e-9)
    assert isinstance(result, InflectionResult)
    assert result.num_inflections == 1, (
        f"Expected 1 crossing for κ=t-0.5; got {result.num_inflections}"
    )
    assert abs(result.inflection_t_params[0] - 0.5) < 0.12


# ---------------------------------------------------------------------------
# Test 16 — threshold parameter suppresses near-zero crossings
# ---------------------------------------------------------------------------

def test_threshold_suppresses_tiny_crossings():
    """A high threshold should suppress near-zero curvature sign changes."""
    curve = _make_s_curve_cubic()
    # With a very high threshold all κ-values treated as zero → 0 inflections.
    result_high = find_curve_inflections(curve, num_samples=200, threshold=100.0)
    assert result_high.num_inflections == 0, (
        "Very high threshold should suppress all inflections; "
        f"got {result_high.num_inflections}"
    )


# ---------------------------------------------------------------------------
# Test 17 — cubic_one_inflection curve: at least 1 inflection
# ---------------------------------------------------------------------------

def test_cubic_one_inflection_at_least_one():
    """Asymmetric cubic with sign-changing curvature: at least 1 inflection."""
    curve = _make_cubic_one_inflection()
    result = find_curve_inflections(curve, num_samples=300)
    assert result.num_inflections >= 1, (
        f"Asymmetric cubic: expected >= 1 inflection; got {result.num_inflections}"
    )


# ---------------------------------------------------------------------------
# Test 18 — num_samples is respected for signed_curvature_samples
# ---------------------------------------------------------------------------

def test_num_samples_param():
    """num_samples controls the length of signed_curvature_samples."""
    curve = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0)
    for n in [50, 100, 250]:
        result = find_curve_inflections(curve, num_samples=n)
        assert len(result.signed_curvature_samples) == n, (
            f"num_samples={n}: expected {n} samples; "
            f"got {len(result.signed_curvature_samples)}"
        )


# ---------------------------------------------------------------------------
# Test 19 — curvature samples have correct (t, κ) structure
# ---------------------------------------------------------------------------

def test_signed_curvature_samples_structure():
    """Each entry in signed_curvature_samples must be a (float, float) pair."""
    curve = _make_s_curve_cubic()
    result = find_curve_inflections(curve, num_samples=50)
    for entry in result.signed_curvature_samples:
        assert len(entry) == 2, f"Expected (t, κ) pair; got {entry!r}"
        t_val, k_val = entry
        assert isinstance(t_val, float)
        assert isinstance(k_val, float)


# ---------------------------------------------------------------------------
# Test 20 — circle: honest_caveat is non-empty (always populated)
# ---------------------------------------------------------------------------

def test_honest_caveat_always_set():
    """honest_caveat should be a non-empty string for any valid curve input."""
    for curve in [
        _make_s_curve_cubic(),
        make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0),
        make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0])),
    ]:
        result = find_curve_inflections(curve, num_samples=100)
        assert isinstance(result.honest_caveat, str)
        assert len(result.honest_caveat) > 0
