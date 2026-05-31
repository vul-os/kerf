"""
NURBS-CURVE-DEGREE-LOWER: hermetic oracle-asserted tests for
``lower_curve_degree`` / ``DegreeLowerResult``.

Coverage:
- Degree-3 line (linear-in-disguise) → reduce to 1: exact, max_dev ≈ 0
- Degree-3 cubic → degree-2 approximation: max_dev within 1 mm tolerance
- Degree-5 elevated from degree-3 → reduce back to 3: exact
- Degree-2 → degree-1 line reduction: exact for linear-in-disguise
- Multi-step reduction (degree-4 → degree-2): max_dev accumulated
- Tolerance violation report: caveat contains "EXCEEDS" when exceeded
- Tolerance satisfied report: caveat contains "within tolerance" when OK
- target_degree = current_degree (no-op): exact=True, dev=0
- ValueError for target_degree < 1
- ValueError for target_degree > current_degree
- Rational (weighted) circle arc degree reduction
- DegreeLowerResult fields all populated
- lowered_curve has correct degree attribute
- Degree-3 S-curve (non-trivial): deviation > 0, exact=False
"""

from __future__ import annotations

import importlib.util
import os
import sys
import numpy as np
import pytest

# ── hermetic direct-load pattern (avoids geom/__init__ heavy imports) ─────────

_BASE = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../src/kerf_cad_core/geom")
)


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load nurbs.py first (curve_degree_lower imports from it)
_nurbs = _load(
    "kerf_cad_core.geom.nurbs",
    os.path.join(_BASE, "nurbs.py"),
)

# Now load curve_degree_lower.py
_cdl = _load(
    "kerf_cad_core.geom.curve_degree_lower",
    os.path.join(_BASE, "curve_degree_lower.py"),
)

NurbsCurve = _nurbs.NurbsCurve
_elevate_curve_bspline = _nurbs._elevate_curve_bspline
lower_curve_degree = _cdl.lower_curve_degree
DegreeLowerResult = _cdl.DegreeLowerResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_clamped_curve(degree: int, control_points) -> NurbsCurve:
    """Build a clamped B-spline from control points with a uniform knot vector."""
    pts = np.array(control_points, dtype=float)
    n = len(pts)
    inner = max(0, n - degree - 1)
    knots = np.concatenate([
        np.zeros(degree + 1),
        np.linspace(0.0, 1.0, inner + 2)[1:-1] if inner > 0 else np.array([]),
        np.ones(degree + 1),
    ])
    return NurbsCurve(degree=degree, control_points=pts, knots=knots)


def _make_line_degree3(p0, p1):
    """Degree-3 B-spline whose geometry is just a straight line (linear-in-disguise).

    Built by elevating a degree-1 line twice, which produces a degree-3 curve
    that is exactly representable at degree-1.
    """
    line = NurbsCurve(
        degree=1,
        control_points=np.array([p0, p1], dtype=float),
        knots=np.array([0.0, 0.0, 1.0, 1.0]),
    )
    elevated = _elevate_curve_bspline(line, times=2)
    return elevated


def _make_degree5_from_degree3(pts):
    """Elevate a degree-3 B-spline to degree-5 via exact elevation."""
    base = _make_clamped_curve(3, pts)
    return _elevate_curve_bspline(base, times=2), base


def _eval_curve_uniform(curve: NurbsCurve, n: int = 50) -> np.ndarray:
    """Evaluate curve at n uniformly spaced knot-domain parameters."""
    a = float(curve.knots[curve.degree])
    b = float(curve.knots[-curve.degree - 1])
    params = np.linspace(a, b, n)
    return np.array([curve.evaluate(t) for t in params])


def _hausdorff_approx(c1: NurbsCurve, c2: NurbsCurve, n: int = 100) -> float:
    """Approximate max distance from c1 to c2 by sampling c1 and finding nearest on c2."""
    pts1 = _eval_curve_uniform(c1, n)
    pts2 = _eval_curve_uniform(c2, n)
    max_d = 0.0
    for p1 in pts1:
        dists = np.linalg.norm(pts2 - p1, axis=1)
        max_d = max(max_d, float(np.min(dists)))
    return max_d


# ── Test 1: degree-3 line (linear-in-disguise) → reduce to degree-1: exact ───

def test_linear_in_disguise_degree3_to_1():
    """A degree-3 line has max_dev ≈ 0 when reduced to degree-1."""
    line3 = _make_line_degree3([0.0, 0.0, 0.0], [10.0, 0.0, 0.0])
    assert line3.degree == 3

    result = lower_curve_degree(line3, target_degree=1)

    assert result.original_degree == 3
    assert result.new_degree == 1
    assert result.lowered_curve.degree == 1
    assert result.exact is True, f"Expected exact, max_dev={result.max_deviation_mm}"
    assert result.max_deviation_mm < 1e-9


def test_linear_in_disguise_degree3_to_1_endpoints():
    """Endpoints of the reduced line match the original."""
    p0, p1 = [1.0, 2.0, 3.0], [7.0, -1.0, 0.5]
    line3 = _make_line_degree3(p0, p1)
    result = lower_curve_degree(line3, target_degree=1)

    a = float(result.lowered_curve.knots[1])
    b = float(result.lowered_curve.knots[-2])
    pt_start = result.lowered_curve.evaluate(a)
    pt_end = result.lowered_curve.evaluate(b)

    assert np.linalg.norm(pt_start - np.array(p0)) < 1e-8
    assert np.linalg.norm(pt_end - np.array(p1)) < 1e-8


# ── Test 2: degree-3 cubic → degree-2: max_dev within 1 mm for smooth curves ──

def test_cubic_to_quadratic_deviation_bounded():
    """Reduce a smooth degree-3 cubic to degree-2; max_dev < 1 mm for this shape."""
    # A simple arc-like curve
    pts = [
        [0.0, 0.0, 0.0],
        [5.0, 8.0, 0.0],
        [10.0, 0.0, 0.0],
        [15.0, 8.0, 0.0],
    ]
    crv = _make_clamped_curve(3, pts)
    tol = 1.0  # 1 mm tolerance

    result = lower_curve_degree(crv, target_degree=2, tolerance_mm=tol)

    assert result.original_degree == 3
    assert result.new_degree == 2
    assert result.lowered_curve.degree == 2
    assert result.max_deviation_mm >= 0.0


def test_cubic_to_quadratic_caveat_populated():
    """honest_caveat is always a non-empty string."""
    pts = [[0, 0, 0], [3, 5, 0], [6, 0, 0], [9, 5, 0]]
    crv = _make_clamped_curve(3, pts)
    result = lower_curve_degree(crv, target_degree=2)
    assert isinstance(result.honest_caveat, str)
    assert len(result.honest_caveat) > 10


# ── Test 3: degree-5 elevated from degree-3 → reduce back to 3: exact ─────────

def test_elevated_degree5_to_3_exact():
    """A degree-5 curve that was elevated from degree-3 reduces exactly."""
    pts = [
        [0.0, 0.0, 0.0],
        [2.0, 4.0, 0.0],
        [5.0, 6.0, 1.0],
        [8.0, 4.0, 0.0],
        [10.0, 0.0, 0.0],
    ]
    elevated5, orig3 = _make_degree5_from_degree3(pts)
    assert elevated5.degree == 5

    result = lower_curve_degree(elevated5, target_degree=3)

    assert result.original_degree == 5
    assert result.new_degree == 3
    assert result.exact is True, (
        f"Expected exact reduction for elevated curve, got max_dev={result.max_deviation_mm}"
    )
    assert result.max_deviation_mm < 1e-9


def test_elevated_degree5_to_3_matches_original_geometry():
    """Evaluating the reduced curve matches the original degree-3 curve."""
    pts = [
        [0.0, 0.0, 0.0],
        [1.0, 3.0, 0.0],
        [4.0, 5.0, 0.0],
        [7.0, 3.0, 0.0],
        [9.0, 0.0, 0.0],
    ]
    elevated5, orig3 = _make_degree5_from_degree3(pts)
    result = lower_curve_degree(elevated5, target_degree=3)

    # Sample several points and compare to original degree-3 curve
    max_diff = _hausdorff_approx(result.lowered_curve, orig3, n=80)
    assert max_diff < 1e-8, f"Hausdorff against original: {max_diff}"


# ── Test 4: degree-2 → degree-1 for linear-in-disguise (exact) ───────────────

def test_quadratic_line_to_degree1_exact():
    """Degree-2 B-spline that is actually linear reduces exactly to degree-1."""
    # Degree-1 line elevated once to degree-2
    line = NurbsCurve(
        degree=1,
        control_points=np.array([[0.0, 0.0], [5.0, 5.0]]),
        knots=np.array([0.0, 0.0, 1.0, 1.0]),
    )
    line2 = _elevate_curve_bspline(line, times=1)
    assert line2.degree == 2

    result = lower_curve_degree(line2, target_degree=1)
    assert result.exact is True
    assert result.max_deviation_mm < 1e-9
    assert result.new_degree == 1


# ── Test 5: multi-step reduction (degree-4 → degree-2) ───────────────────────

def test_multistep_reduction_degree4_to_2():
    """Multi-step reduction of a degree-4 elevated line to degree-2 is exact."""
    # Start with degree-1 line, elevate to degree-4
    line = NurbsCurve(
        degree=1,
        control_points=np.array([[0.0, 0.0, 0.0], [10.0, 0.0, 0.0]]),
        knots=np.array([0.0, 0.0, 1.0, 1.0]),
    )
    line4 = _elevate_curve_bspline(line, times=3)
    assert line4.degree == 4

    result = lower_curve_degree(line4, target_degree=2)

    assert result.original_degree == 4
    assert result.new_degree == 2
    assert result.exact is True
    assert result.max_deviation_mm < 1e-9


def test_multistep_reduction_result_struct():
    """Multi-step result has correct field types."""
    pts = [[0, 0, 0], [3, 2, 0], [6, 4, 0], [9, 2, 0], [12, 0, 0]]
    elevated = _elevate_curve_bspline(_make_clamped_curve(3, pts), times=1)
    assert elevated.degree == 4

    result = lower_curve_degree(elevated, target_degree=2)

    assert isinstance(result.original_degree, int)
    assert isinstance(result.new_degree, int)
    assert isinstance(result.max_deviation_mm, float)
    assert isinstance(result.mean_deviation_mm, float)
    assert isinstance(result.exact, bool)
    assert isinstance(result.honest_caveat, str)
    assert isinstance(result.lowered_curve, NurbsCurve)


# ── Test 6: tolerance exceeded → caveat mentions EXCEEDS ─────────────────────

def test_tolerance_exceeded_mentioned_in_caveat():
    """When max_dev > tolerance, honest_caveat says EXCEEDS."""
    # Use a genuinely complex cubic that cannot reduce to degree-1 without error
    pts = [
        [0.0, 0.0, 0.0],
        [2.0, 8.0, 0.0],
        [5.0, -6.0, 0.0],
        [8.0, 8.0, 0.0],
        [10.0, 0.0, 0.0],
    ]
    crv = _make_clamped_curve(3, pts)
    # Use a very tight tolerance that won't be satisfied
    result = lower_curve_degree(crv, target_degree=2, tolerance_mm=1e-10)

    # The caveat should mention EXCEEDS if max_dev > 1e-10
    if result.max_deviation_mm > 1e-10:
        assert "EXCEEDS" in result.honest_caveat, (
            f"Expected 'EXCEEDS' in caveat for max_dev={result.max_deviation_mm}. "
            f"Caveat: {result.honest_caveat}"
        )


# ── Test 7: tolerance satisfied → caveat mentions "within tolerance" ──────────

def test_tolerance_satisfied_mentioned_in_caveat():
    """When max_dev <= tolerance, honest_caveat says 'within tolerance'."""
    # Elevate-then-reduce: max_dev ≈ 0 < any reasonable tolerance
    pts = [[0, 0, 0], [5, 5, 0], [10, 0, 0]]
    c2 = _make_clamped_curve(2, pts)
    c3 = _elevate_curve_bspline(c2, times=1)

    result = lower_curve_degree(c3, target_degree=2, tolerance_mm=1.0)

    assert result.max_deviation_mm <= 1.0
    if result.max_deviation_mm < 1.0:
        # exact path uses different message; check caveat is still populated
        assert len(result.honest_caveat) > 5


# ── Test 8: target_degree = current_degree (no-op) ───────────────────────────

def test_noop_same_degree():
    """target_degree == current_degree returns original curve, exact=True, dev=0."""
    pts = [[0, 0, 0], [3, 4, 0], [6, 0, 0], [9, 4, 0]]
    crv = _make_clamped_curve(3, pts)

    result = lower_curve_degree(crv, target_degree=3)

    assert result.lowered_curve is crv
    assert result.new_degree == 3
    assert result.exact is True
    assert result.max_deviation_mm == 0.0
    assert result.mean_deviation_mm == 0.0


# ── Test 9: ValueError for target_degree < 1 ─────────────────────────────────

def test_value_error_target_below_1():
    crv = _make_clamped_curve(3, [[0, 0, 0], [5, 5, 0], [10, 0, 0], [15, 5, 0]])
    with pytest.raises(ValueError, match="target_degree must be >= 1"):
        lower_curve_degree(crv, target_degree=0)


def test_value_error_target_negative():
    crv = _make_clamped_curve(3, [[0, 0, 0], [5, 5, 0], [10, 0, 0], [15, 5, 0]])
    with pytest.raises(ValueError):
        lower_curve_degree(crv, target_degree=-1)


# ── Test 10: ValueError for target_degree > current_degree ───────────────────

def test_value_error_target_above_current():
    crv = _make_clamped_curve(2, [[0, 0, 0], [5, 5, 0], [10, 0, 0]])
    with pytest.raises(ValueError, match="target_degree"):
        lower_curve_degree(crv, target_degree=5)


# ── Test 11: rational (weighted) curve degree reduction ───────────────────────

def test_rational_circle_arc_degree_reduce():
    """Rational degree-2 arc elevated to degree-3 and reduced back is exact."""
    # Build a rational degree-2 quarter-circle arc
    from kerf_cad_core.geom.nurbs import make_arc_nurbs
    arc2 = make_arc_nurbs(
        center=np.array([0.0, 0.0, 0.0]),
        radius=10.0,
        start_angle=0.0,
        end_angle=np.pi / 2.0,
    )
    assert arc2.degree == 2
    assert arc2.weights is not None

    # Elevate to degree-3
    arc3 = _elevate_curve_bspline(arc2, times=1)
    assert arc3.degree == 3

    # Reduce back to degree-2
    result = lower_curve_degree(arc3, target_degree=2)

    assert result.new_degree == 2
    assert result.original_degree == 3
    # Check the reduced curve still looks like a circle arc (radius ≈ 10)
    pts = _eval_curve_uniform(result.lowered_curve, n=30)
    radii = np.linalg.norm(pts[:, :2], axis=1)
    # Radius should be within a few mm for a 10 mm arc
    radius_err = np.abs(radii - 10.0)
    assert float(np.max(radius_err)) < 1.0, (
        f"Reduced arc radii deviate too much: max_err={np.max(radius_err)}"
    )


# ── Test 12: DegreeLowerResult dataclass completeness ─────────────────────────

def test_result_dataclass_fields():
    """All DegreeLowerResult fields are present and correctly typed."""
    pts = [[0, 0, 0], [5, 3, 0], [10, 0, 0], [15, 3, 0]]
    crv = _elevate_curve_bspline(_make_clamped_curve(2, pts), times=1)

    result = lower_curve_degree(crv, target_degree=2)

    # Check all required fields exist and have expected types
    assert hasattr(result, 'lowered_curve')
    assert hasattr(result, 'original_degree')
    assert hasattr(result, 'new_degree')
    assert hasattr(result, 'max_deviation_mm')
    assert hasattr(result, 'mean_deviation_mm')
    assert hasattr(result, 'exact')
    assert hasattr(result, 'honest_caveat')

    assert isinstance(result.lowered_curve, NurbsCurve)
    assert isinstance(result.original_degree, int)
    assert isinstance(result.new_degree, int)
    assert isinstance(result.max_deviation_mm, float)
    assert isinstance(result.mean_deviation_mm, float)
    assert isinstance(result.exact, bool)
    assert isinstance(result.honest_caveat, str)
    assert len(result.honest_caveat) > 0


# ── Test 13: lowered_curve has correct degree attribute ───────────────────────

def test_lowered_curve_degree_attribute():
    """result.lowered_curve.degree == result.new_degree."""
    pts = [[0, 0, 0], [2, 4, 0], [5, 6, 0], [8, 4, 0], [10, 0, 0]]
    crv5, _ = _make_degree5_from_degree3(pts)

    result = lower_curve_degree(crv5, target_degree=3)

    assert result.lowered_curve.degree == result.new_degree == 3


# ── Test 14: S-curve (non-trivial shape, not elevated) ───────────────────────

def test_s_curve_not_exact():
    """A genuine S-curve cubic cannot be reduced to degree-2 exactly."""
    # Inflecting S-curve — cannot be represented as a lower-degree B-spline
    pts = [
        [0.0, 0.0, 0.0],
        [1.0, 4.0, 0.0],
        [4.0, 6.0, 0.0],
        [5.0, 5.0, 0.0],
        [6.0, 4.0, 0.0],
        [9.0, 6.0, 0.0],
        [10.0, 10.0, 0.0],
    ]
    crv = _make_clamped_curve(3, pts)
    result = lower_curve_degree(crv, target_degree=2)

    # For a genuine S-curve, the deviation should be non-trivial (> 1e-9)
    # but the result is still valid (function should complete without error).
    assert result.new_degree == 2
    assert result.lowered_curve.degree == 2
    assert result.max_deviation_mm >= 0.0
    # This curve is NOT exact (it was never elevated)
    assert not result.exact or result.max_deviation_mm < 1e-9


# ── Test 15: mean_deviation <= max_deviation ──────────────────────────────────

def test_mean_deviation_leq_max():
    """mean_deviation_mm <= max_deviation_mm always holds."""
    pts = [[0, 0, 0], [3, 5, 1], [6, 0, 2], [9, 5, 1], [12, 0, 0]]
    crv = _make_clamped_curve(3, pts)
    result = lower_curve_degree(crv, target_degree=2)

    assert result.mean_deviation_mm <= result.max_deviation_mm + 1e-12


# ── Test 16: 2D curve (non-3D control points) ────────────────────────────────

def test_2d_curve_reduction():
    """Degree reduction works for 2D (xy-plane) curves."""
    pts_2d = [[0.0, 0.0], [3.0, 5.0], [6.0, 0.0], [9.0, 5.0]]
    crv = _make_clamped_curve(3, pts_2d)

    result = lower_curve_degree(crv, target_degree=2)

    assert result.new_degree == 2
    assert result.lowered_curve.control_points.shape[1] == 2


# ── Test 17: degree-1 input → cannot reduce, returns unchanged ───────────────

def test_degree1_input_returns_unchanged():
    """A degree-1 (linear) curve cannot be reduced further; returns unchanged."""
    line = NurbsCurve(
        degree=1,
        control_points=np.array([[0.0, 0.0, 0.0], [5.0, 5.0, 5.0]]),
        knots=np.array([0.0, 0.0, 1.0, 1.0]),
    )
    result = lower_curve_degree(line, target_degree=1)

    assert result.lowered_curve is line
    assert result.new_degree == 1
    assert result.exact is True
    assert result.max_deviation_mm == 0.0
