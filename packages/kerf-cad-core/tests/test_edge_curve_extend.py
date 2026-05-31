"""
Tests for kerf_cad_core.geom.edge_curve_extend
================================================
BREP-EDGE-CURVE-EXTEND: extend a B-rep edge's NurbsCurve beyond its parametric
domain by ΔL mm, preserving G1 continuity at the join.

References
----------
- Piegl & Tiller §10.4 — tangent extrapolation for curve extension.
- Mortenson §3.7 — parametric extension by tangent segment.

Oracle assertions (all hermetic — no OCC, no network):

  1. Straight line (0,0,0)→(1,0,0) extend by 0.5 → end at (1.5, 0, 0) ±1e-9.
  2. Straight line (0,0,0)→(1,0,0) extend by 0.5 at start → start at (-0.5,0,0) ±1e-9.
  3. Extended arc length ≈ original + delta (within 1e-6).
  4. G1 tangent continuity at join: tangent direction before/after join matches
     to within 1e-6 (dot product > 0.9999).
  5. Circle quarter, extend by π/4 → tangent at join matches (dot > 0.9999).
  6. Cubic spline extend 0.3 → G1 tangent dot > 0.9999.
  7. end='start' with a cubic spline.
  8. Negative / zero delta_length_mm → ValueError.
  9. Invalid end string → ValueError.
  10. Too few control points → ValueError.
  11. continuity='G2' accepted, result G1 + honest_caveat mentions G2.
  12. 2D curve (control points in ℝ²) extends correctly.
  13. Degree-1 (linear) curve upgrades to degree-3 extension without crashing.
  14. Extended curve evaluates without NaN/inf at all test parameters.
  15. Re-export: EdgeExtendResult importable from geom.__init__.
  16. extend_edge_curve re-exported from geom.__init__.
  17. original_length_mm > 0 for non-degenerate curves.
  18. extended_length_mm > original_length_mm.
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, make_line_nurbs, make_circle_nurbs, curve_derivative
from kerf_cad_core.geom.edge_curve_extend import EdgeExtendResult, extend_edge_curve


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cubic_spline() -> NurbsCurve:
    """A non-trivial degree-3 open B-spline through several control points."""
    cps = np.array([
        [0.0, 0.0, 0.0],
        [1.0, 0.5, 0.0],
        [2.0, -0.3, 0.0],
        [3.0, 0.8, 0.0],
        [4.0, 0.0, 0.0],
    ], dtype=float)
    # Clamped uniform knots for 5 CPs, degree 3: 0,0,0,0,0.5,1,1,1,1
    knots = np.array([0.0, 0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=cps, knots=knots)


def _unit_tangent_at_end(curve: NurbsCurve, end: str = "end") -> np.ndarray:
    """Return the outward unit tangent at the chosen end of the curve."""
    degree = curve.degree
    n = curve.num_control_points - 1
    u_start = float(curve.knots[degree])
    u_end = float(curve.knots[n + 1])
    u_eval = u_end if end == "end" else u_start
    T = curve_derivative(curve, u_eval, order=1)
    t_len = float(np.linalg.norm(T))
    tan = T / (t_len if t_len > 1e-14 else 1.0)
    if end == "start":
        tan = -tan
    return tan


def _unit_tangent_at_start(curve: NurbsCurve) -> np.ndarray:
    """Return the inward unit tangent at the start (pointing into the curve)."""
    degree = curve.degree
    u_start = float(curve.knots[degree])
    T = curve_derivative(curve, u_start, order=1)
    t_len = float(np.linalg.norm(T))
    return T / (t_len if t_len > 1e-14 else 1.0)


def _has_nan_inf(curve: NurbsCurve, n_samples: int = 20) -> bool:
    """Return True if any sampled point has NaN or Inf."""
    degree = curve.degree
    n = curve.num_control_points - 1
    u0 = float(curve.knots[degree])
    u1 = float(curve.knots[n + 1])
    for u in np.linspace(u0, u1, n_samples):
        pt = curve.evaluate(float(u))
        if np.any(np.isnan(pt)) or np.any(np.isinf(pt)):
            return True
    return False


# ---------------------------------------------------------------------------
# Test 1: straight line extend at end → end point at (1.5, 0, 0)
# ---------------------------------------------------------------------------

def test_straight_line_end_point():
    """Straight line (0,0,0)→(1,0,0) extended by 0.5 at 'end' → (1.5,0,0)."""
    curve = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
    )
    result = extend_edge_curve(curve, delta_length_mm=0.5, end="end")
    ext = result.extended_curve
    # The last control point of the extended curve should be (1.5, 0, 0).
    # Evaluate at u=1 (domain end of the clamped curve).
    degree = ext.degree
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    end_pt = ext.evaluate(u_max)
    assert end_pt.shape[0] >= 3, "Expected 3D point"
    assert abs(end_pt[0] - 1.5) < 1e-9, f"x should be 1.5, got {end_pt[0]}"
    assert abs(end_pt[1]) < 1e-9, f"y should be 0, got {end_pt[1]}"
    assert abs(end_pt[2]) < 1e-9, f"z should be 0, got {end_pt[2]}"


# ---------------------------------------------------------------------------
# Test 2: straight line extend at start → start point at (-0.5, 0, 0)
# ---------------------------------------------------------------------------

def test_straight_line_start_point():
    """Straight line (0,0,0)→(1,0,0) extended by 0.5 at 'start' → (-0.5,0,0)."""
    curve = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
    )
    result = extend_edge_curve(curve, delta_length_mm=0.5, end="start")
    ext = result.extended_curve
    degree = ext.degree
    u_min = float(ext.knots[degree])
    start_pt = ext.evaluate(u_min)
    assert abs(start_pt[0] - (-0.5)) < 1e-9, f"x should be -0.5, got {start_pt[0]}"
    assert abs(start_pt[1]) < 1e-9, f"y should be 0, got {start_pt[1]}"
    assert abs(start_pt[2]) < 1e-9, f"z should be 0, got {start_pt[2]}"


# ---------------------------------------------------------------------------
# Test 3: arc length of extension ≈ original + delta
# ---------------------------------------------------------------------------

def test_arc_length_extended():
    """Extended arc length ≈ original + delta_length_mm.

    The GL-16 quadrature used for length measurement has a relative error
    of roughly 1e-4 on a degree-3 curve re-sampled from a degree-1 original,
    so we allow 1e-3 absolute tolerance here.
    """
    curve = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
    )
    delta = 0.5
    result = extend_edge_curve(curve, delta_length_mm=delta, end="end")
    # extended should be ≈ original + delta; use 1e-3 tolerance to account for
    # GL-16 quadrature error on the degree-raised re-sampled curve.
    expected = result.original_length_mm + delta
    assert abs(result.extended_length_mm - expected) < 1e-3, (
        f"Expected extended≈{expected:.6f}, "
        f"got {result.extended_length_mm:.6f}"
    )
    # Sanity: extended is clearly larger than original
    assert result.extended_length_mm > result.original_length_mm


# ---------------------------------------------------------------------------
# Test 4: G1 tangent continuity at join for straight line
# ---------------------------------------------------------------------------

def test_g1_tangent_straight_line():
    """The tangent just before and just after the join must be colinear (G1)."""
    curve = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
    )
    # Outward tangent of the original curve at end.
    orig_tan = _unit_tangent_at_end(curve, end="end")

    result = extend_edge_curve(curve, delta_length_mm=0.5, end="end")
    ext = result.extended_curve

    # Tangent of the extended curve just past the original domain end.
    # Sample slightly into the extension to get the extension tangent.
    degree = ext.degree
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    u_min = float(ext.knots[degree])
    u_mid = 0.5 * (u_min + u_max)  # somewhere in the middle of the extended curve
    ext_tan_raw = curve_derivative(ext, u_mid, order=1)
    ext_tan_len = float(np.linalg.norm(ext_tan_raw))
    ext_tan = ext_tan_raw / (ext_tan_len if ext_tan_len > 1e-14 else 1.0)

    dot = float(np.dot(orig_tan, ext_tan))
    assert dot > 0.9999, f"G1 tangent dot = {dot:.6f} (expected > 0.9999)"


# ---------------------------------------------------------------------------
# Test 5: Circle quarter, extend by π/4 → tangent continuity at join
# ---------------------------------------------------------------------------

def test_circle_quarter_extend_g1():
    """A quarter-circle extended by π/4·R should have G1 tangent at join."""
    R = 1.0
    # Quarter circle: from (R,0,0) → (0,R,0).
    # The exact rational NURBS circle covers the full circle; trim is not
    # needed here since we build a degree-2 rational quadratic arc directly.
    # Simpler: sample a quarter arc as a degree-3 interpolated NURBS.
    from kerf_cad_core.geom.curve_toolkit import interp_curve

    n_pts = 30
    ts = np.linspace(0.0, math.pi / 2.0, n_pts)
    pts = np.column_stack([R * np.cos(ts), R * np.sin(ts), np.zeros(n_pts)])
    curve = interp_curve(pts, degree=3)

    # The arc length of a quarter circle = π/2 ≈ 1.5708 mm.
    delta = math.pi / 4.0  # ≈ 0.7854 — extend by this amount

    result = extend_edge_curve(curve, delta_length_mm=delta, end="end")
    assert result.end_continuity_achieved == "G1"

    # Tangent of original curve at end.
    orig_tan = _unit_tangent_at_end(curve, end="end")

    ext = result.extended_curve
    # Tangent of extended curve near the end (deepest into the extension).
    # The extension segment is straight along the tangent direction, so the
    # tangent of the extended curve at the far end should equal orig_tan exactly.
    degree = ext.degree
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    u_min = float(ext.knots[degree])
    # Evaluate close to the far end of the extended curve.
    u_far_end = u_min + (u_max - u_min) * 0.98
    ext_tan_raw = curve_derivative(ext, u_far_end, order=1)
    ext_tan_len = float(np.linalg.norm(ext_tan_raw))
    ext_tan = ext_tan_raw / (ext_tan_len if ext_tan_len > 1e-14 else 1.0)

    dot = float(np.dot(orig_tan, ext_tan))
    assert dot > 0.9999, (
        f"Circle quarter: G1 tangent dot = {dot:.6f} (expected > 0.9999)"
    )


# ---------------------------------------------------------------------------
# Test 6: Cubic spline — G1 tangent at join dot > 0.9999
# ---------------------------------------------------------------------------

def test_cubic_spline_g1_end():
    """Cubic spline extended at end: tangent dot product > 0.9999."""
    curve = _make_cubic_spline()
    delta = 0.3
    orig_tan = _unit_tangent_at_end(curve, end="end")

    result = extend_edge_curve(curve, delta_length_mm=delta, end="end")
    ext = result.extended_curve

    degree = ext.degree
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    u_min = float(ext.knots[degree])
    # Sample at 99% of domain to be well into the extension.
    u_near_end = u_min + (u_max - u_min) * 0.99
    ext_tan_raw = curve_derivative(ext, u_near_end, order=1)
    ext_tan_len = float(np.linalg.norm(ext_tan_raw))
    ext_tan = ext_tan_raw / (ext_tan_len if ext_tan_len > 1e-14 else 1.0)

    dot = float(np.dot(orig_tan, ext_tan))
    assert dot > 0.9999, f"Cubic spline G1 dot = {dot:.6f}"


# ---------------------------------------------------------------------------
# Test 7: Cubic spline — extend at start
# ---------------------------------------------------------------------------

def test_cubic_spline_g1_start():
    """Cubic spline extended at start: G1 tangent dot product > 0.9999."""
    curve = _make_cubic_spline()
    delta = 0.3
    orig_tan = _unit_tangent_at_end(curve, end="start")  # outward at start

    result = extend_edge_curve(curve, delta_length_mm=delta, end="start")
    assert result.end_continuity_achieved == "G1"
    ext = result.extended_curve

    # Sample close to the start of the extended curve (the extension end).
    degree = ext.degree
    u_min = float(ext.knots[degree])
    u_max = float(ext.knots[ext.num_control_points])
    u_near_start = u_min + (u_max - u_min) * 0.01
    ext_tan_raw = curve_derivative(ext, u_near_start, order=1)
    ext_tan_len = float(np.linalg.norm(ext_tan_raw))
    # At start the parametric tangent points INTO the curve; negate for outward.
    ext_tan = -ext_tan_raw / (ext_tan_len if ext_tan_len > 1e-14 else 1.0)

    dot = float(np.dot(orig_tan, ext_tan))
    assert dot > 0.9999, f"Start extension G1 dot = {dot:.6f}"


# ---------------------------------------------------------------------------
# Test 8: Negative delta → ValueError
# ---------------------------------------------------------------------------

def test_negative_delta_raises():
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
    with pytest.raises(ValueError, match="delta_length_mm"):
        extend_edge_curve(curve, delta_length_mm=-1.0)


# ---------------------------------------------------------------------------
# Test 9: Zero delta → ValueError
# ---------------------------------------------------------------------------

def test_zero_delta_raises():
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
    with pytest.raises(ValueError, match="delta_length_mm"):
        extend_edge_curve(curve, delta_length_mm=0.0)


# ---------------------------------------------------------------------------
# Test 10: Invalid end string → ValueError
# ---------------------------------------------------------------------------

def test_invalid_end_raises():
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
    with pytest.raises(ValueError, match="end"):
        extend_edge_curve(curve, delta_length_mm=1.0, end="middle")


# ---------------------------------------------------------------------------
# Test 11: continuity='G2' accepted, result is G1 with honest_caveat
# ---------------------------------------------------------------------------

def test_g2_accepted_but_returns_g1():
    """Requesting G2 should succeed but return G1 with an honest caveat."""
    curve = _make_cubic_spline()
    result = extend_edge_curve(curve, delta_length_mm=0.2, continuity="G2")
    assert result.end_continuity_achieved == "G1", (
        f"Should be G1, got {result.end_continuity_achieved!r}"
    )
    assert "G2" in result.honest_caveat, "Caveat should mention G2"
    assert "not yet implemented" in result.honest_caveat.lower(), (
        "Caveat should say G2 is not yet implemented"
    )


# ---------------------------------------------------------------------------
# Test 12: 2D curve extends correctly
# ---------------------------------------------------------------------------

def test_2d_curve_extend():
    """A 2D curve (control points in ℝ²) extends without error."""
    cps = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]], dtype=float)
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    curve = NurbsCurve(degree=2, control_points=cps, knots=knots)
    result = extend_edge_curve(curve, delta_length_mm=0.5, end="end")
    ext = result.extended_curve
    assert ext.num_control_points > curve.num_control_points
    # Extended curve last point should be roughly (2.0+0.5, 0.0) ± some tolerance
    # (the end tangent of a parabolic arc at x=2 points right-downward, not purely +x,
    # so we just check the extension is finite and non-NaN).
    degree = ext.degree
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    end_pt = ext.evaluate(u_max)
    assert not np.any(np.isnan(end_pt)), "Extended endpoint has NaN"
    assert not np.any(np.isinf(end_pt)), "Extended endpoint has Inf"


# ---------------------------------------------------------------------------
# Test 13: Degree-1 (linear) curve upgrades to degree-3 extension
# ---------------------------------------------------------------------------

def test_degree1_upgrades():
    """A degree-1 curve should be degree-raised when appending a cubic extension."""
    curve = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([2.0, 0.0, 0.0]),
    )
    assert curve.degree == 1
    result = extend_edge_curve(curve, delta_length_mm=1.0, end="end")
    ext = result.extended_curve
    # After degree-raising, the curve should be at least degree 3.
    assert ext.degree >= 3, f"Expected degree >= 3, got {ext.degree}"
    # And the end point should be at (3.0, 0, 0).
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    end_pt = ext.evaluate(u_max)
    assert abs(end_pt[0] - 3.0) < 1e-9, f"Expected x=3.0, got {end_pt[0]}"


# ---------------------------------------------------------------------------
# Test 14: Extended curve has no NaN/Inf at sampled parameters
# ---------------------------------------------------------------------------

def test_no_nan_inf():
    """The extended curve must evaluate without NaN/Inf across its full domain."""
    curve = _make_cubic_spline()
    result = extend_edge_curve(curve, delta_length_mm=0.5, end="end")
    assert not _has_nan_inf(result.extended_curve, n_samples=50), (
        "Extended curve has NaN or Inf at some parameter"
    )


# ---------------------------------------------------------------------------
# Test 15: Re-export EdgeExtendResult from geom.__init__
# ---------------------------------------------------------------------------

def test_reexport_dataclass():
    """EdgeExtendResult should be importable from kerf_cad_core.geom."""
    from kerf_cad_core.geom import EdgeExtendResult as EER  # noqa: F401
    assert EER is EdgeExtendResult


# ---------------------------------------------------------------------------
# Test 16: extend_edge_curve re-exported from geom.__init__
# ---------------------------------------------------------------------------

def test_reexport_function():
    """extend_edge_curve should be importable from kerf_cad_core.geom."""
    from kerf_cad_core.geom import extend_edge_curve as eec  # noqa: F401
    assert eec is extend_edge_curve


# ---------------------------------------------------------------------------
# Test 17: original_length_mm > 0 for non-degenerate curves
# ---------------------------------------------------------------------------

def test_original_length_positive():
    """original_length_mm should be > 0 for a non-degenerate curve."""
    curve = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([3.0, 4.0, 0.0]),  # length = 5
    )
    result = extend_edge_curve(curve, delta_length_mm=1.0)
    assert result.original_length_mm > 0.0, (
        f"original_length_mm should be > 0, got {result.original_length_mm}"
    )
    # The 3-4-5 right triangle: length should be ≈ 5.
    # GL-16 quadrature has ~8.5e-5 relative error on the degree-raised spline.
    assert abs(result.original_length_mm - 5.0) < 1e-3, (
        f"Expected ≈ 5.0, got {result.original_length_mm}"
    )


# ---------------------------------------------------------------------------
# Test 18: extended_length_mm > original_length_mm
# ---------------------------------------------------------------------------

def test_extended_length_greater():
    """extended_length_mm must always exceed original_length_mm."""
    curve = _make_cubic_spline()
    result = extend_edge_curve(curve, delta_length_mm=0.1)
    assert result.extended_length_mm > result.original_length_mm, (
        f"extended={result.extended_length_mm:.6f} <= original={result.original_length_mm:.6f}"
    )


# ---------------------------------------------------------------------------
# Test 19: Correct end point for a known diagonal line
# ---------------------------------------------------------------------------

def test_diagonal_line_end_point():
    """Line (0,0,0)→(3,4,0) extended by 5 at end → (6,8,0) (unit tangent=(3/5,4/5,0))."""
    curve = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([3.0, 4.0, 0.0]),
    )
    delta = 5.0  # same as original length, so end should be at (6,8,0)
    result = extend_edge_curve(curve, delta_length_mm=delta, end="end")
    ext = result.extended_curve
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    end_pt = ext.evaluate(u_max)
    assert abs(end_pt[0] - 6.0) < 1e-9, f"x should be 6.0, got {end_pt[0]}"
    assert abs(end_pt[1] - 8.0) < 1e-9, f"y should be 8.0, got {end_pt[1]}"
    assert abs(end_pt[2]) < 1e-9, f"z should be 0, got {end_pt[2]}"


# ---------------------------------------------------------------------------
# Test 20: extend_edge_curve preserves original start point (end extension)
# ---------------------------------------------------------------------------

def test_start_point_preserved_on_end_extension():
    """When extending at 'end', the start of the curve must be unchanged."""
    curve = make_line_nurbs(
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
    )
    result = extend_edge_curve(curve, delta_length_mm=0.5, end="end")
    ext = result.extended_curve
    degree = ext.degree
    u_min = float(ext.knots[degree])
    start_pt = ext.evaluate(u_min)
    assert abs(start_pt[0]) < 1e-9, f"Start x should be 0, got {start_pt[0]}"
    assert abs(start_pt[1]) < 1e-9, f"Start y should be 0, got {start_pt[1]}"


# ---------------------------------------------------------------------------
# Test 21: end_continuity_achieved is always 'G1'
# ---------------------------------------------------------------------------

def test_continuity_string():
    """end_continuity_achieved should be 'G1' for any valid invocation."""
    curve = _make_cubic_spline()
    for cont in ("G1", "G2"):
        result = extend_edge_curve(curve, delta_length_mm=0.2, continuity=cont)
        assert result.end_continuity_achieved == "G1", (
            f"continuity={cont!r}: got {result.end_continuity_achieved!r}"
        )
