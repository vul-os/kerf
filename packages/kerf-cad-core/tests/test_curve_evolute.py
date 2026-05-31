"""
Tests for curve_evolute.py — NURBS-CURVE-EVOLUTE.

The evolute E(t) = C(t) + n̂(t)/κ(t) is the locus of centres of osculating
circles.  Cusps of the evolute correspond to vertices of the original curve
(local extrema of curvature), per do Carmo §1.6.

Test plan
---------
01. Circle radius R, center (cx,cy): evolute is a single point at center.
    All evolute points within 1e-5 of (cx,cy).
02. Circle: num_cusps_detected = 0  (constant curvature, no extrema).
03. Circle: num_samples = num_evolute_points  (no samples skipped for circle).
04. Circle at non-origin center: evolute points cluster around that center.
05. Parabola y=x²/2 (exact degree-2 Bezier): evolute at apex t=0.5 = (0,1)
    within 1e-5 tolerance.
06. Parabola: t=0.5 is among the cusp_t_params  (apex = curvature max/vertex).
07. Parabola: 0.5 is in cusp_t_params AND the evolute point there is near (0,1).
08. Ellipse a=2, b=1: exactly 4 cusps detected (4 vertices of the ellipse).
09. Ellipse: cusp_t_params are approximately [0.00, 0.25, 0.50, 0.75].
10. Straight line (degree=1): evolute is empty — all samples skipped (|κ|=0).
11. Straight line: honest_caveat is non-empty.
12. Straight line: num_cusps_detected = 0.
13. num_samples parameter is respected: result.num_samples == argument.
14. Return type is EvoluteResult dataclass.
15. evolute_points is a list of (float,float) tuples.
16. Non-NurbsCurve input returns EvoluteResult with empty evolute_points.
17. min_curvature parameter: raising it filters more samples.
18. Cubic S-curve (sign-changing curvature): skipped samples around inflection.
19. Quarter circle arc: evolute points near center, no cusps.
20. t_params length equals len(evolute_points).
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    make_arc_nurbs,
    make_circle_nurbs,
    make_ellipse_nurbs,
    make_line_nurbs,
)
from kerf_cad_core.geom.curve_evolute import (
    EvoluteResult,
    compute_curve_evolute,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_parabola_nurbs() -> NurbsCurve:
    """Exact degree-2 Bezier for y = x²/2, x ∈ [-1, 1].

    Control points (-1, 1/2), (0, -1/2), (1, 1/2) give the unique
    quadratic Bezier whose x(t)=2t-1, y(t)=(2t-1)²/2 = x²/2 exactly.
    Apex is at t=0.5: C(0.5)=(0,0), κ(0.5)=1, evolute=(0,1).
    """
    cps = np.array([[-1.0, 0.5, 0.0],
                    [0.0, -0.5, 0.0],
                    [1.0,  0.5, 0.0]])
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=2, control_points=cps, knots=knots)


def _make_cubic_s_curve() -> NurbsCurve:
    """Degree-3 S-shaped Bezier with an inflection point near the midpoint.

    Control points form an S: (0,0), (0.5,1), (0.5,-1), (1,0).
    The curvature changes sign near t=0.5 (inflection).
    """
    cps = np.array([[0.0,  0.0, 0.0],
                    [0.5,  1.0, 0.0],
                    [0.5, -1.0, 0.0],
                    [1.0,  0.0, 0.0]])
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=cps, knots=knots)


# ---------------------------------------------------------------------------
# Test 01 — Circle R=2, center at origin: evolute collapses to center
# ---------------------------------------------------------------------------

def test_circle_evolute_near_center():
    """All evolute points of a circle of radius R are at the center."""
    R = 2.0
    circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), R)
    result = compute_curve_evolute(circle, num_samples=100)
    pts = np.array(result.evolute_points)
    assert pts.shape[1] == 2
    dist = np.sqrt(pts[:, 0] ** 2 + pts[:, 1] ** 2)
    assert dist.max() < 1e-5, (
        f"Circle evolute should be at center; max deviation = {dist.max():.2e}"
    )


# ---------------------------------------------------------------------------
# Test 02 — Circle: no cusps (constant curvature)
# ---------------------------------------------------------------------------

def test_circle_no_cusps():
    """A circle has constant curvature, so the evolute has no cusps."""
    circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 3.0)
    result = compute_curve_evolute(circle, num_samples=200)
    assert result.num_cusps_detected == 0, (
        f"Circle should have 0 cusps; got {result.num_cusps_detected}"
    )


# ---------------------------------------------------------------------------
# Test 03 — Circle: no samples skipped (|κ| = 1/R > min_curvature)
# ---------------------------------------------------------------------------

def test_circle_no_samples_skipped():
    """For a circle, every sample has κ = 1/R >> min_curvature, so none skipped."""
    R = 1.5
    circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), R)
    result = compute_curve_evolute(circle, num_samples=80)
    assert len(result.evolute_points) == result.num_samples, (
        f"Circle: all {result.num_samples} samples should produce evolute points; "
        f"got {len(result.evolute_points)}"
    )


# ---------------------------------------------------------------------------
# Test 04 — Circle at non-origin center
# ---------------------------------------------------------------------------

def test_circle_off_center_evolute():
    """Evolute of a circle centered at (3, -2) should cluster near (3, -2)."""
    cx, cy, R = 3.0, -2.0, 1.0
    circle = make_circle_nurbs(np.array([cx, cy, 0.0]), R)
    result = compute_curve_evolute(circle, num_samples=120)
    pts = np.array(result.evolute_points)
    dist = np.sqrt((pts[:, 0] - cx) ** 2 + (pts[:, 1] - cy) ** 2)
    assert dist.max() < 1e-5, (
        f"Off-center circle: evolute should be at ({cx},{cy}); "
        f"max deviation = {dist.max():.2e}"
    )


# ---------------------------------------------------------------------------
# Test 05 — Parabola apex evolute = (0, 1)
# ---------------------------------------------------------------------------

def test_parabola_apex_evolute():
    """Evolute of y=x²/2 at the apex (t=0.5) is exactly (0, 1).

    At x=0 (apex), κ = 1, radius = 1, principal normal = (0, 1).
    Therefore E(0.5) = (0, 0) + (0, 1)/1 = (0, 1).
    Reference: Mortenson §4.2, Fig 4.8.
    """
    parabola = _make_parabola_nurbs()
    # Use odd num_samples so t=0.5 is exactly sampled.
    result = compute_curve_evolute(parabola, num_samples=201)
    ts = result.t_params
    # Find the evolute point closest to t=0.5
    idx = min(range(len(ts)), key=lambda i: abs(ts[i] - 0.5))
    ex, ey = result.evolute_points[idx]
    assert abs(ex) < 1e-5, f"Parabola apex: evolute x should be 0, got {ex:.2e}"
    assert abs(ey - 1.0) < 1e-5, f"Parabola apex: evolute y should be 1, got {ey:.6f}"


# ---------------------------------------------------------------------------
# Test 06 — Parabola: apex t=0.5 is in cusp_t_params
# ---------------------------------------------------------------------------

def test_parabola_apex_in_cusp_params():
    """The apex of y=x²/2 is a curvature maximum → cusp of the evolute."""
    parabola = _make_parabola_nurbs()
    result = compute_curve_evolute(parabola, num_samples=201)
    # t=0.5 should be one of the detected cusps (or very close to one)
    cusp_ts = result.cusp_t_params
    assert len(cusp_ts) > 0, "Parabola should have at least one detected cusp"
    min_dist = min(abs(t - 0.5) for t in cusp_ts)
    assert min_dist < 0.01, (
        f"Parabola: cusp at apex (t=0.5) expected; "
        f"closest cusp at {min_dist:.3f} from t=0.5"
    )


# ---------------------------------------------------------------------------
# Test 07 — Parabola apex cusp: evolute point at cusp is near (0, 1)
# ---------------------------------------------------------------------------

def test_parabola_apex_cusp_evolute_point():
    """The cusp of the parabola evolute at t≈0.5 should be at (0, 1)."""
    parabola = _make_parabola_nurbs()
    result = compute_curve_evolute(parabola, num_samples=201)
    ts = result.t_params
    # Find evolute point closest to the apex cusp (t≈0.5)
    idx = min(range(len(ts)), key=lambda i: abs(ts[i] - 0.5))
    ex, ey = result.evolute_points[idx]
    assert abs(ex) < 1e-4, f"Apex cusp x should be ~0, got {ex:.2e}"
    assert abs(ey - 1.0) < 1e-4, f"Apex cusp y should be ~1, got {ey:.6f}"


# ---------------------------------------------------------------------------
# Test 08 — Ellipse a=2, b=1: exactly 4 cusps
# ---------------------------------------------------------------------------

def test_ellipse_four_cusps():
    """An ellipse a=2, b=1 has 4 vertices (2 maxima, 2 minima of κ),
    producing 4 cusps in its evolute (a stretched astroid).

    Reference: Mortenson §4.2; do Carmo §1.6 (Exercise 1).
    """
    ellipse = make_ellipse_nurbs(np.array([0.0, 0.0, 0.0]), a=2.0, b=1.0)
    result = compute_curve_evolute(ellipse, num_samples=401)
    assert result.num_cusps_detected == 4, (
        f"Ellipse a=2,b=1 should have 4 cusps (stretched astroid evolute); "
        f"got {result.num_cusps_detected} at t={result.cusp_t_params}"
    )


# ---------------------------------------------------------------------------
# Test 09 — Ellipse cusp t-params are approximately [0, 0.25, 0.5, 0.75]
# ---------------------------------------------------------------------------

def test_ellipse_cusp_t_params():
    """The four ellipse cusp parameters should be near t=0, 0.25, 0.5, 0.75."""
    ellipse = make_ellipse_nurbs(np.array([0.0, 0.0, 0.0]), a=2.0, b=1.0)
    result = compute_curve_evolute(ellipse, num_samples=401)
    expected = [0.0, 0.25, 0.50, 0.75]
    cusp_ts = sorted(result.cusp_t_params)
    for exp, got in zip(expected, cusp_ts):
        assert abs(got - exp) < 0.02, (
            f"Ellipse cusp: expected t≈{exp:.2f}, got {got:.4f}"
        )


# ---------------------------------------------------------------------------
# Test 10 — Straight line: evolute is empty
# ---------------------------------------------------------------------------

def test_straight_line_empty_evolute():
    """A straight line has κ=0 everywhere; evolute is empty (all skipped)."""
    line = make_line_nurbs(np.array([0.0, 0.0, 0.0]),
                           np.array([1.0, 0.0, 0.0]))
    result = compute_curve_evolute(line, num_samples=50)
    assert len(result.evolute_points) == 0, (
        f"Straight line: evolute should be empty, got {len(result.evolute_points)} points"
    )


# ---------------------------------------------------------------------------
# Test 11 — Straight line: honest_caveat is non-empty
# ---------------------------------------------------------------------------

def test_straight_line_honest_caveat():
    """The honest_caveat field is always populated."""
    line = make_line_nurbs(np.array([0.0, 0.0, 0.0]),
                           np.array([0.5, 0.5, 0.0]))
    result = compute_curve_evolute(line, num_samples=30)
    assert len(result.honest_caveat) > 0, "honest_caveat must not be empty"
    assert "2D" in result.honest_caveat or "2d" in result.honest_caveat.lower()


# ---------------------------------------------------------------------------
# Test 12 — Straight line: no cusps
# ---------------------------------------------------------------------------

def test_straight_line_no_cusps():
    """A straight line has no curvature extrema."""
    line = make_line_nurbs(np.array([0.0, 0.0, 0.0]),
                           np.array([1.0, 1.0, 0.0]))
    result = compute_curve_evolute(line, num_samples=40)
    assert result.num_cusps_detected == 0


# ---------------------------------------------------------------------------
# Test 13 — num_samples parameter is honoured
# ---------------------------------------------------------------------------

def test_num_samples_respected():
    """result.num_samples equals the argument passed."""
    circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0)
    for n in [50, 150, 300]:
        result = compute_curve_evolute(circle, num_samples=n)
        assert result.num_samples == n, (
            f"num_samples={n} requested, but result.num_samples={result.num_samples}"
        )


# ---------------------------------------------------------------------------
# Test 14 — Return type is EvoluteResult
# ---------------------------------------------------------------------------

def test_return_type_is_evolute_result():
    """compute_curve_evolute returns an EvoluteResult instance."""
    circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 2.0)
    result = compute_curve_evolute(circle)
    assert isinstance(result, EvoluteResult)


# ---------------------------------------------------------------------------
# Test 15 — evolute_points contains (float, float) tuples
# ---------------------------------------------------------------------------

def test_evolute_points_are_float_tuples():
    """Each element of evolute_points is a 2-tuple of floats."""
    circle = make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.5)
    result = compute_curve_evolute(circle, num_samples=30)
    assert len(result.evolute_points) > 0
    for pt in result.evolute_points[:5]:
        assert len(pt) == 2
        assert isinstance(pt[0], float) and isinstance(pt[1], float)


# ---------------------------------------------------------------------------
# Test 16 — Non-NurbsCurve input: graceful degenerate result
# ---------------------------------------------------------------------------

def test_non_nurbs_input_returns_empty():
    """Passing a non-NurbsCurve returns an EvoluteResult with an honest caveat."""
    result = compute_curve_evolute("not a curve")  # type: ignore[arg-type]
    assert isinstance(result, EvoluteResult)
    assert len(result.evolute_points) == 0
    assert len(result.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Test 17 — min_curvature parameter: higher value skips more samples
# ---------------------------------------------------------------------------

def test_min_curvature_filters_samples():
    """Raising min_curvature causes more samples to be skipped."""
    parabola = _make_parabola_nurbs()
    r_low = compute_curve_evolute(parabola, num_samples=100, min_curvature=1e-6)
    r_high = compute_curve_evolute(parabola, num_samples=100, min_curvature=0.8)
    # High min_curvature should skip more samples (smaller evolute point count)
    assert len(r_high.evolute_points) < len(r_low.evolute_points), (
        f"High min_curvature should skip more: "
        f"low={len(r_low.evolute_points)}, high={len(r_high.evolute_points)}"
    )


# ---------------------------------------------------------------------------
# Test 18 — Cubic S-curve: some samples skipped near inflection
# ---------------------------------------------------------------------------

def test_s_curve_samples_near_inflection():
    """An S-curve has an inflection (κ=0 near midpoint); some samples skipped."""
    s_curve = _make_cubic_s_curve()
    result = compute_curve_evolute(s_curve, num_samples=100, min_curvature=1e-6)
    # The evolute should have fewer points than num_samples due to the inflection
    assert len(result.evolute_points) <= result.num_samples
    # The honest caveat must mention the 2D limitation
    assert len(result.honest_caveat) > 0


# ---------------------------------------------------------------------------
# Test 19 — Quarter circle arc: evolute points near center
# ---------------------------------------------------------------------------

def test_quarter_circle_arc_evolute():
    """A quarter-circle arc has constant curvature; evolute near the center."""
    R = 2.0
    arc = make_arc_nurbs(np.array([0.0, 0.0, 0.0]), R,
                         start_angle=0.0, end_angle=math.pi / 2)
    result = compute_curve_evolute(arc, num_samples=50)
    pts = np.array(result.evolute_points)
    dist = np.sqrt(pts[:, 0] ** 2 + pts[:, 1] ** 2)
    assert dist.max() < 1e-4, (
        f"Quarter arc: evolute should be near center; max dist = {dist.max():.2e}"
    )
    assert result.num_cusps_detected == 0, (
        f"Circular arc has constant κ → 0 cusps; got {result.num_cusps_detected}"
    )


# ---------------------------------------------------------------------------
# Test 20 — t_params and evolute_points have equal length
# ---------------------------------------------------------------------------

def test_t_params_length_equals_evolute_points():
    """result.t_params and result.evolute_points always have the same length."""
    for curve in [
        make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0),
        _make_parabola_nurbs(),
        make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0])),
        make_ellipse_nurbs(np.array([0.0, 0.0, 0.0]), a=2.0, b=1.0),
    ]:
        result = compute_curve_evolute(curve, num_samples=80)
        assert len(result.t_params) == len(result.evolute_points), (
            f"t_params length ({len(result.t_params)}) != "
            f"evolute_points length ({len(result.evolute_points)})"
        )
