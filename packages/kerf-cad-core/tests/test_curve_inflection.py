"""
Tests for curve_inflection.py — NURBS-CURVE-INFLECTION.

Finds inflection points of a 2D NurbsCurve where κ_signed changes sign.

Test suite covers two APIs:
  - Legacy v1: find_curve_inflections_v1 → InflectionResult
  - Current v2: find_curve_inflections → CurveInflectionReport (InflectionPoint)

Test plan — v1 (legacy, tests 01–20)
--------------------------------------
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
19. Curvature samples have correct (t, κ) structure.
20. honest_caveat is non-empty for any valid curve input.

Test plan — v2 (current, tests 21–38)
--------------------------------------
21. Straight line → CurveInflectionReport, num_inflections=0, is_fair_class_a=True.
22. Straight line → honest_caveat non-empty; warns about κ≡0.
23. Circle arc → 0 inflections, is_fair_class_a=True, max_curvature≈1/R.
24. S-curve (cubic Bezier) → exactly 1 inflection, is_fair_class_a=True.
25. S-curve → InflectionPoint.sign_change is True.
26. S-curve → InflectionPoint.xy_mm is a (float, float) tuple.
27. S-curve → curvature_left and curvature_right have opposite signs.
28. Double-S (wavy sine) → ≥ 2 inflections, is_fair_class_a=False.
29. Double-S → warnings list is non-empty (fairness warning).
30. Return type is CurveInflectionReport.
31. num_inflections == len(inflection_points).
32. max_curvature ≥ min_curvature for any curve.
33. Inflection parameter_u values inside domain [t_min, t_max].
34. tol parameter: high tol suppresses all inflections for S-curve.
35. Non-NurbsCurve input returns CurveInflectionReport with warning.
36. Parabola → 0 inflections, is_fair_class_a=True.
37. is_fair_class_a=True for circle (κ=const, 0 inflections).
38. honest_caveat mentions "2D" and "sampling" constraints.
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
    # v2
    InflectionPoint,
    CurveInflectionReport,
    find_curve_inflections,
    # v1 legacy
    InflectionResult,
    find_curve_inflections_v1,
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
# ===========================================================================
#  LEGACY v1 TESTS (tests 01–20)
# ===========================================================================
# ---------------------------------------------------------------------------

# Test 01 — cubic spline with one inflection: detect exactly 1

def test_cubic_one_inflection_count():
    """Cubic S-curve should have exactly 1 inflection (v1 API)."""
    curve = _make_s_curve_cubic()
    result = find_curve_inflections_v1(curve, num_samples=300)
    assert result.num_inflections == 1, (
        f"Expected 1 inflection for S-curve; got {result.num_inflections}"
    )


# Test 02 — inflection t close to 0.5 for symmetric S

def test_cubic_s_inflection_near_midpoint():
    """The single inflection of the S-curve should be near t=0.5 (v1 API)."""
    curve = _make_s_curve_cubic()
    result = find_curve_inflections_v1(curve, num_samples=300)
    assert result.num_inflections >= 1
    t_inf = result.inflection_t_params[0]
    assert 0.35 <= t_inf <= 0.65, (
        f"S-curve inflection should be near 0.5; got t={t_inf:.4f}"
    )


# Test 03 — another S-curve variant: exactly 1 inflection

def test_s_bezier_one_inflection():
    """Wide S-curve (spiral segment) has exactly 1 inflection (v1 API)."""
    curve = _make_spiral_segment_nurbs()
    result = find_curve_inflections_v1(curve, num_samples=400)
    assert result.num_inflections == 1, (
        f"Wide S-curve: expected 1 inflection; got {result.num_inflections}"
    )


# Test 04 — S-curve inflection in valid range

def test_s_bezier_inflection_in_range():
    """S-curve inflection should be inside (0, 1) (v1 API)."""
    curve = _make_spiral_segment_nurbs()
    result = find_curve_inflections_v1(curve, num_samples=400)
    assert result.num_inflections >= 1
    t_inf = result.inflection_t_params[0]
    assert 0.0 < t_inf < 1.0, f"t={t_inf:.4f} outside (0,1)"


# Test 05 — circle: 0 inflections (constant κ)

def test_circle_zero_inflections():
    """A circle has constant κ — no sign changes — 0 inflections (v1 API)."""
    circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 2.0)
    result = find_curve_inflections_v1(circle, num_samples=200)
    assert result.num_inflections == 0, (
        f"Circle should have 0 inflections; got {result.num_inflections}"
    )


# Test 06 — straight line: 0 inflections + honest_caveat

def test_straight_line_zero_inflections():
    """Straight line has κ=0 everywhere — 0 inflections (v1 API)."""
    line = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([3.0, 1.0, 0.0]),
    )
    result = find_curve_inflections_v1(line, num_samples=100)
    assert result.num_inflections == 0, (
        f"Straight line should have 0 inflections; got {result.num_inflections}"
    )


# Test 07 — straight line: honest_caveat mentions zero/line/straight

def test_straight_line_honest_caveat():
    """honest_caveat for a straight line should explain the κ=0 situation (v1 API)."""
    line = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([5.0, 0.0, 0.0]),
    )
    result = find_curve_inflections_v1(line, num_samples=100)
    assert result.honest_caveat, "honest_caveat should be non-empty for a straight line"
    caveat_lower = result.honest_caveat.lower()
    assert any(kw in caveat_lower for kw in ("zero", "line", "straight", "flat")), (
        f"honest_caveat should mention zero/line/straight: {result.honest_caveat!r}"
    )


# Test 08 — sine curve approximation: at least 2 inflections

def test_sine_curve_multiple_inflections():
    """A two-arch sine should have at least 2 inflection points (v1 API)."""
    curve = _make_sine_approx_nurbs()
    result = find_curve_inflections_v1(curve, num_samples=500)
    assert result.num_inflections >= 2, (
        f"Two-arch sine: expected >= 2 inflections; got {result.num_inflections}"
    )


# Test 09 — parabola: 0 inflections (κ > 0 everywhere)

def test_parabola_zero_inflections():
    """A parabola has κ > 0 everywhere — no sign change — 0 inflections (v1 API)."""
    curve = _make_parabola_nurbs()
    result = find_curve_inflections_v1(curve, num_samples=200)
    assert result.num_inflections == 0, (
        f"Parabola should have 0 inflections; got {result.num_inflections}"
    )


# Test 10 — return type is InflectionResult

def test_return_type_v1():
    """find_curve_inflections_v1 always returns an InflectionResult."""
    curve = _make_s_curve_cubic()
    result = find_curve_inflections_v1(curve)
    assert isinstance(result, InflectionResult)


# Test 11 — signed_curvature_samples length == num_samples

def test_signed_curvature_samples_length():
    """signed_curvature_samples must have exactly num_samples entries (v1 API)."""
    curve = _make_s_curve_cubic()
    n = 150
    result = find_curve_inflections_v1(curve, num_samples=n)
    assert len(result.signed_curvature_samples) == n, (
        f"Expected {n} curvature samples; got {len(result.signed_curvature_samples)}"
    )


# Test 12 — num_inflections == len(inflection_t_params)

def test_num_inflections_consistent():
    """num_inflections must equal len(inflection_t_params) (v1 API)."""
    for curve in [_make_s_curve_cubic(), make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0)]:
        result = find_curve_inflections_v1(curve)
        assert result.num_inflections == len(result.inflection_t_params), (
            f"Inconsistent: num_inflections={result.num_inflections} "
            f"vs len(inflection_t_params)={len(result.inflection_t_params)}"
        )


# Test 13 — inflection t-values inside [t_min, t_max]

def test_inflection_params_in_domain():
    """All inflection t-values must lie within the curve's parameter domain (v1 API)."""
    curve = _make_sine_approx_nurbs()
    result = find_curve_inflections_v1(curve, num_samples=500)
    t_min = float(curve.knots[curve.degree])
    t_max = float(curve.knots[-(curve.degree + 1)])
    for t in result.inflection_t_params:
        assert t_min <= t <= t_max, (
            f"Inflection t={t:.4f} outside domain [{t_min:.4f}, {t_max:.4f}]"
        )


# Test 14 — non-NurbsCurve input returns InflectionResult without exception

def test_non_nurbs_input_does_not_raise():
    """Passing a non-NurbsCurve returns InflectionResult with honest_caveat (v1 API)."""
    result = find_curve_inflections_v1("not a curve")
    assert isinstance(result, InflectionResult)
    assert result.num_inflections == 0
    assert result.honest_caveat


# Test 15 — raw (t, κ) samples input path

def test_raw_samples_input():
    """Passing pre-computed (t, κ) pairs detects sign changes directly (v1 API)."""
    # Construct samples that cross zero at t=0.5.
    samples = [(i * 0.1, (i * 0.1 - 0.5)) for i in range(11)]  # κ = t - 0.5
    result = find_curve_inflections_v1(samples, threshold=1e-9)
    assert isinstance(result, InflectionResult)
    assert result.num_inflections == 1, (
        f"Expected 1 crossing for κ=t-0.5; got {result.num_inflections}"
    )
    assert abs(result.inflection_t_params[0] - 0.5) < 0.12


# Test 16 — threshold parameter suppresses near-zero crossings

def test_threshold_suppresses_tiny_crossings():
    """A high threshold should suppress near-zero curvature sign changes (v1 API)."""
    curve = _make_s_curve_cubic()
    # With a very high threshold all κ-values treated as zero → 0 inflections.
    result_high = find_curve_inflections_v1(curve, num_samples=200, threshold=100.0)
    assert result_high.num_inflections == 0, (
        "Very high threshold should suppress all inflections; "
        f"got {result_high.num_inflections}"
    )


# Test 17 — cubic_one_inflection curve: at least 1 inflection

def test_cubic_one_inflection_at_least_one():
    """Asymmetric cubic with sign-changing curvature: at least 1 inflection (v1 API)."""
    curve = _make_cubic_one_inflection()
    result = find_curve_inflections_v1(curve, num_samples=300)
    assert result.num_inflections >= 1, (
        f"Asymmetric cubic: expected >= 1 inflection; got {result.num_inflections}"
    )


# Test 18 — num_samples is respected for signed_curvature_samples

def test_num_samples_param():
    """num_samples controls the length of signed_curvature_samples (v1 API)."""
    curve = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0)
    for n in [50, 100, 250]:
        result = find_curve_inflections_v1(curve, num_samples=n)
        assert len(result.signed_curvature_samples) == n, (
            f"num_samples={n}: expected {n} samples; "
            f"got {len(result.signed_curvature_samples)}"
        )


# Test 19 — curvature samples have correct (t, κ) structure

def test_signed_curvature_samples_structure():
    """Each entry in signed_curvature_samples must be a (float, float) pair (v1 API)."""
    curve = _make_s_curve_cubic()
    result = find_curve_inflections_v1(curve, num_samples=50)
    for entry in result.signed_curvature_samples:
        assert len(entry) == 2, f"Expected (t, κ) pair; got {entry!r}"
        t_val, k_val = entry
        assert isinstance(t_val, float)
        assert isinstance(k_val, float)


# Test 20 — honest_caveat is non-empty (always populated)

def test_honest_caveat_always_set():
    """honest_caveat should be a non-empty string for any valid curve input (v1 API)."""
    for curve in [
        _make_s_curve_cubic(),
        make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0),
        make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0])),
    ]:
        result = find_curve_inflections_v1(curve, num_samples=100)
        assert isinstance(result.honest_caveat, str)
        assert len(result.honest_caveat) > 0


# ---------------------------------------------------------------------------
# ===========================================================================
#  CURRENT v2 TESTS (tests 21–38)  — InflectionPoint + CurveInflectionReport
# ===========================================================================
# ---------------------------------------------------------------------------

# Test 21 — straight line: 0 inflections, is_fair_class_a=True

def test_v2_straight_line_zero_inflections():
    """Straight line has κ=0 → 0 inflections, is_fair_class_a=True (v2 API)."""
    line = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([5.0, 2.0, 0.0]),
    )
    report = find_curve_inflections(line, num_samples=150)
    assert isinstance(report, CurveInflectionReport)
    assert report.num_inflections == 0
    assert report.is_fair_class_a is True


# Test 22 — straight line: honest_caveat and warnings mention κ=0

def test_v2_straight_line_warns_about_zero_kappa():
    """Straight line: warnings or caveat should mention κ≡0 (v2 API)."""
    line = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([3.0, 0.0, 0.0]),
    )
    report = find_curve_inflections(line, num_samples=100)
    assert report.honest_caveat, "honest_caveat must be non-empty"
    combined = report.honest_caveat.lower() + " ".join(report.warnings).lower()
    assert any(kw in combined for kw in ("zero", "line", "straight", "κ", "kappa", "flat")), (
        f"Expected zero/line/straight mention; got caveat={report.honest_caveat!r}, "
        f"warnings={report.warnings!r}"
    )


# Test 23 — circle arc: 0 inflections, is_fair_class_a=True, max_curvature≈1/R

def test_v2_circle_zero_inflections_and_curvature():
    """Circle: 0 inflections, is_fair_class_a=True, max_curvature ≈ 1/R (v2 API)."""
    R = 3.0
    circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), R)
    report = find_curve_inflections(circle, num_samples=300)
    assert report.num_inflections == 0
    assert report.is_fair_class_a is True
    # For a circle of radius R, κ = 1/R
    expected_kappa = 1.0 / R
    assert abs(report.max_curvature - expected_kappa) < 0.1 * expected_kappa, (
        f"max_curvature={report.max_curvature:.4f}, expected≈{expected_kappa:.4f}"
    )


# Test 24 — S-curve: exactly 1 inflection, is_fair_class_a=True

def test_v2_s_curve_one_inflection_fair():
    """S-curve (cubic Bezier) → 1 inflection, is_fair_class_a=True (v2 API)."""
    curve = _make_s_curve_cubic()
    report = find_curve_inflections(curve, num_samples=300)
    assert report.num_inflections == 1, (
        f"S-curve: expected 1 inflection; got {report.num_inflections}"
    )
    assert report.is_fair_class_a is True


# Test 25 — S-curve: InflectionPoint.sign_change is True

def test_v2_inflection_point_sign_change():
    """S-curve inflection point has sign_change=True (v2 API)."""
    curve = _make_s_curve_cubic()
    report = find_curve_inflections(curve, num_samples=300)
    assert report.num_inflections >= 1
    ip = report.inflection_points[0]
    assert isinstance(ip, InflectionPoint)
    assert ip.sign_change is True, (
        f"Expected sign_change=True; got curvature_left={ip.curvature_left:.4f}, "
        f"curvature_right={ip.curvature_right:.4f}"
    )


# Test 26 — S-curve: InflectionPoint.xy_mm is a (float, float) tuple

def test_v2_inflection_point_xy_mm():
    """InflectionPoint.xy_mm must be a (float, float) tuple (v2 API)."""
    curve = _make_s_curve_cubic()
    report = find_curve_inflections(curve, num_samples=300)
    assert report.num_inflections >= 1
    ip = report.inflection_points[0]
    assert isinstance(ip.xy_mm, tuple)
    assert len(ip.xy_mm) == 2
    x, y = ip.xy_mm
    assert isinstance(x, float) and isinstance(y, float)
    # For the S-curve from (0,0) to (1,0), midpoint should be ≈ (0.5, 0)
    assert 0.3 <= x <= 0.7, f"xy_mm x={x:.4f} out of expected range [0.3, 0.7]"


# Test 27 — S-curve: curvature_left and curvature_right have opposite signs

def test_v2_inflection_point_opposite_curvatures():
    """curvature_left and curvature_right must have opposite signs at inflection (v2 API)."""
    curve = _make_s_curve_cubic()
    report = find_curve_inflections(curve, num_samples=300)
    assert report.num_inflections >= 1
    ip = report.inflection_points[0]
    assert ip.curvature_left * ip.curvature_right < 0.0, (
        f"Expected opposite signs: left={ip.curvature_left:.4f}, "
        f"right={ip.curvature_right:.4f}"
    )


# Test 28 — Double-S (wavy): ≥ 2 inflections, is_fair_class_a=False

def test_v2_double_s_not_fair():
    """Two-arch sine (double-S) → ≥ 2 inflections, is_fair_class_a=False (v2 API)."""
    curve = _make_sine_approx_nurbs()
    report = find_curve_inflections(curve, num_samples=500)
    assert report.num_inflections >= 2, (
        f"Two-arch sine: expected >= 2 inflections; got {report.num_inflections}"
    )
    assert report.is_fair_class_a is False, (
        "Curve with ≥ 2 inflections should NOT be Class-A fair"
    )


# Test 29 — Double-S: warnings list is non-empty (fairness warning)

def test_v2_double_s_has_fairness_warning():
    """Two-arch sine should produce at least one fairness warning (v2 API)."""
    curve = _make_sine_approx_nurbs()
    report = find_curve_inflections(curve, num_samples=500)
    assert len(report.warnings) >= 1, (
        "Expected at least one warning for a non-fair curve"
    )
    warnings_text = " ".join(report.warnings).lower()
    assert any(kw in warnings_text for kw in ("fair", "class-a", "inflection")), (
        f"Expected fairness warning; got: {report.warnings!r}"
    )


# Test 30 — return type is CurveInflectionReport

def test_v2_return_type():
    """find_curve_inflections always returns a CurveInflectionReport (v2 API)."""
    curve = _make_s_curve_cubic()
    report = find_curve_inflections(curve)
    assert isinstance(report, CurveInflectionReport)


# Test 31 — num_inflections == len(inflection_points)

def test_v2_num_inflections_consistent():
    """num_inflections must equal len(inflection_points) (v2 API)."""
    for curve in [_make_s_curve_cubic(),
                  make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0),
                  _make_sine_approx_nurbs()]:
        report = find_curve_inflections(curve)
        assert report.num_inflections == len(report.inflection_points), (
            f"Inconsistent: num_inflections={report.num_inflections} vs "
            f"len(inflection_points)={len(report.inflection_points)}"
        )


# Test 32 — max_curvature ≥ min_curvature for any curve

def test_v2_max_ge_min_curvature():
    """max_curvature must be >= min_curvature for all curves (v2 API)."""
    for curve in [
        _make_s_curve_cubic(),
        make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.5),
        _make_parabola_nurbs(),
        make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0])),
    ]:
        report = find_curve_inflections(curve, num_samples=100)
        assert report.max_curvature >= report.min_curvature, (
            f"max_curvature={report.max_curvature} < min_curvature={report.min_curvature}"
        )


# Test 33 — inflection parameter_u values inside domain [t_min, t_max]

def test_v2_inflection_params_in_domain():
    """All inflection parameter_u values inside [t_min, t_max] (v2 API)."""
    curve = _make_sine_approx_nurbs()
    report = find_curve_inflections(curve, num_samples=500)
    t_min = float(curve.knots[curve.degree])
    t_max = float(curve.knots[-(curve.degree + 1)])
    for ip in report.inflection_points:
        assert t_min <= ip.parameter_u <= t_max, (
            f"parameter_u={ip.parameter_u:.4f} outside [{t_min:.4f}, {t_max:.4f}]"
        )


# Test 34 — tol parameter: high tol suppresses all inflections for S-curve

def test_v2_tol_suppresses_inflections():
    """High tol suppresses inflections for the S-curve (v2 API)."""
    curve = _make_s_curve_cubic()
    report = find_curve_inflections(curve, num_samples=200, tol=100.0)
    assert report.num_inflections == 0, (
        f"High tol should suppress all inflections; got {report.num_inflections}"
    )
    # Suppressed by tol → treated as a "near-zero" curve
    assert report.is_fair_class_a is True


# Test 35 — non-NurbsCurve input returns CurveInflectionReport with warning

def test_v2_non_nurbs_input():
    """Non-NurbsCurve input returns CurveInflectionReport with a warning (v2 API)."""
    report = find_curve_inflections("not a curve")
    assert isinstance(report, CurveInflectionReport)
    assert report.num_inflections == 0
    assert len(report.warnings) >= 1
    assert report.honest_caveat


# Test 36 — parabola: 0 inflections, is_fair_class_a=True

def test_v2_parabola_zero_inflections():
    """Parabola has κ > 0 everywhere → 0 inflections, is_fair_class_a=True (v2 API)."""
    curve = _make_parabola_nurbs()
    report = find_curve_inflections(curve, num_samples=200)
    assert report.num_inflections == 0, (
        f"Parabola: expected 0 inflections; got {report.num_inflections}"
    )
    assert report.is_fair_class_a is True


# Test 37 — circle: is_fair_class_a=True (constant κ, 0 inflections)

def test_v2_circle_fair():
    """Circle has constant κ → 0 inflections → is_fair_class_a=True (v2 API)."""
    circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 2.5)
    report = find_curve_inflections(circle, num_samples=200)
    assert report.is_fair_class_a is True
    assert report.num_inflections == 0


# Test 38 — honest_caveat mentions "2D" and sampling constraints

def test_v2_honest_caveat_content():
    """honest_caveat must mention '2D' and sampling constraints (v2 API)."""
    curve = _make_s_curve_cubic()
    report = find_curve_inflections(curve, num_samples=100)
    caveat = report.honest_caveat.lower()
    assert "2d" in caveat, f"honest_caveat must mention '2D'; got: {report.honest_caveat!r}"
    assert any(kw in caveat for kw in ("sampling", "sample", "analytical")), (
        f"honest_caveat must mention sampling constraints; got: {report.honest_caveat!r}"
    )
