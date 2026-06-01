"""
Tests for kerf_cad_core.geom.edge_curve_extend
================================================
BREP-EDGE-CURVE-EXTEND: extend a B-rep edge's NurbsCurve beyond its parametric
domain by ΔL mm, preserving G1 or G2 continuity at the join.

References
----------
- Piegl & Tiller s10.4 -- tangent extrapolation for curve extension.
- Piegl & Tiller s5.3 -- B-spline derivatives for G2 boundary conditions.
- Mortenson s3.7 -- parametric extension by tangent segment.
- Patrikalakis-Maekawa s3.4 -- curvature-continuous (G2) curve extension.
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
    knots = np.array([0.0, 0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=cps, knots=knots)


def _unit_tangent_at_end(curve: NurbsCurve, end: str = "end") -> np.ndarray:
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
    degree = curve.degree
    u_start = float(curve.knots[degree])
    T = curve_derivative(curve, u_start, order=1)
    t_len = float(np.linalg.norm(T))
    return T / (t_len if t_len > 1e-14 else 1.0)


def _has_nan_inf(curve: NurbsCurve, n_samples: int = 20) -> bool:
    degree = curve.degree
    n = curve.num_control_points - 1
    u0 = float(curve.knots[degree])
    u1 = float(curve.knots[n + 1])
    for u in np.linspace(u0, u1, n_samples):
        pt = curve.evaluate(float(u))
        if np.any(np.isnan(pt)) or np.any(np.isinf(pt)):
            return True
    return False


def _curvature_at_end(curve: NurbsCurve, end: str = "end") -> float:
    """Return unsigned geometric curvature kappa = |C'xC''| / |C'|^3 at boundary."""
    degree = curve.degree
    n = curve.num_control_points - 1
    u_start = float(curve.knots[degree])
    u_end = float(curve.knots[n + 1])
    u_eval = u_end if end == "end" else u_start
    D1 = curve_derivative(curve, u_eval, order=1)
    D2 = curve_derivative(curve, u_eval, order=2)
    d1_norm = float(np.linalg.norm(D1))
    if d1_norm < 1e-12:
        return float("nan")
    if D1.shape[0] == 2:
        cross_mag = abs(D1[0] * D2[1] - D1[1] * D2[0])
    else:
        cross = np.cross(D1[:3], D2[:3])
        cross_mag = float(np.linalg.norm(cross))
    return cross_mag / d1_norm ** 3


# ---------------------------------------------------------------------------
# Test 1
# ---------------------------------------------------------------------------

def test_straight_line_end_point():
    """Straight line (0,0,0)->(1,0,0) extended by 0.5 at 'end' -> (1.5,0,0)."""
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
    result = extend_edge_curve(curve, delta_length_mm=0.5, end="end")
    ext = result.extended_curve
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    end_pt = ext.evaluate(u_max)
    assert end_pt.shape[0] >= 3
    assert abs(end_pt[0] - 1.5) < 1e-9, f"x should be 1.5, got {end_pt[0]}"
    assert abs(end_pt[1]) < 1e-9, f"y should be 0, got {end_pt[1]}"
    assert abs(end_pt[2]) < 1e-9, f"z should be 0, got {end_pt[2]}"


# ---------------------------------------------------------------------------
# Test 2
# ---------------------------------------------------------------------------

def test_straight_line_start_point():
    """Straight line (0,0,0)->(1,0,0) extended by 0.5 at 'start' -> (-0.5,0,0)."""
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
    result = extend_edge_curve(curve, delta_length_mm=0.5, end="start")
    ext = result.extended_curve
    degree = ext.degree
    u_min = float(ext.knots[degree])
    start_pt = ext.evaluate(u_min)
    assert abs(start_pt[0] - (-0.5)) < 1e-9, f"x should be -0.5, got {start_pt[0]}"
    assert abs(start_pt[1]) < 1e-9, f"y should be 0, got {start_pt[1]}"
    assert abs(start_pt[2]) < 1e-9, f"z should be 0, got {start_pt[2]}"


# ---------------------------------------------------------------------------
# Test 3
# ---------------------------------------------------------------------------

def test_arc_length_extended():
    """Extended arc length approx original + delta_length_mm."""
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
    delta = 0.5
    result = extend_edge_curve(curve, delta_length_mm=delta, end="end")
    expected = result.original_length_mm + delta
    assert abs(result.extended_length_mm - expected) < 1e-3
    assert result.extended_length_mm > result.original_length_mm


# ---------------------------------------------------------------------------
# Test 4
# ---------------------------------------------------------------------------

def test_g1_tangent_straight_line():
    """Tangent just before and just after join must be colinear (G1)."""
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
    orig_tan = _unit_tangent_at_end(curve, end="end")
    result = extend_edge_curve(curve, delta_length_mm=0.5, end="end")
    ext = result.extended_curve
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    u_min = float(ext.knots[ext.degree])
    u_mid = 0.5 * (u_min + u_max)
    ext_tan_raw = curve_derivative(ext, u_mid, order=1)
    ext_tan_len = float(np.linalg.norm(ext_tan_raw))
    ext_tan = ext_tan_raw / (ext_tan_len if ext_tan_len > 1e-14 else 1.0)
    dot = float(np.dot(orig_tan, ext_tan))
    assert dot > 0.9999, f"G1 tangent dot = {dot:.6f}"


# ---------------------------------------------------------------------------
# Test 5
# ---------------------------------------------------------------------------

def test_circle_quarter_extend_g1():
    """Quarter-circle extended by pi/4*R should have G1 tangent at join."""
    from kerf_cad_core.geom.curve_toolkit import interp_curve
    R = 1.0
    n_pts = 30
    ts = np.linspace(0.0, math.pi / 2.0, n_pts)
    pts = np.column_stack([R * np.cos(ts), R * np.sin(ts), np.zeros(n_pts)])
    curve = interp_curve(pts, degree=3)
    delta = math.pi / 4.0
    result = extend_edge_curve(curve, delta_length_mm=delta, end="end")
    assert result.end_continuity_achieved == "G1"
    orig_tan = _unit_tangent_at_end(curve, end="end")
    ext = result.extended_curve
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    u_min = float(ext.knots[ext.degree])
    u_far_end = u_min + (u_max - u_min) * 0.98
    ext_tan_raw = curve_derivative(ext, u_far_end, order=1)
    ext_tan_len = float(np.linalg.norm(ext_tan_raw))
    ext_tan = ext_tan_raw / (ext_tan_len if ext_tan_len > 1e-14 else 1.0)
    dot = float(np.dot(orig_tan, ext_tan))
    assert dot > 0.9999, f"Circle quarter G1 dot = {dot:.6f}"


# ---------------------------------------------------------------------------
# Test 6
# ---------------------------------------------------------------------------

def test_cubic_spline_g1_end():
    """Cubic spline extended at end: tangent dot product > 0.9999."""
    curve = _make_cubic_spline()
    delta = 0.3
    orig_tan = _unit_tangent_at_end(curve, end="end")
    result = extend_edge_curve(curve, delta_length_mm=delta, end="end")
    ext = result.extended_curve
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    u_min = float(ext.knots[ext.degree])
    u_near_end = u_min + (u_max - u_min) * 0.99
    ext_tan_raw = curve_derivative(ext, u_near_end, order=1)
    ext_tan_len = float(np.linalg.norm(ext_tan_raw))
    ext_tan = ext_tan_raw / (ext_tan_len if ext_tan_len > 1e-14 else 1.0)
    dot = float(np.dot(orig_tan, ext_tan))
    assert dot > 0.9999, f"Cubic spline G1 dot = {dot:.6f}"


# ---------------------------------------------------------------------------
# Test 7
# ---------------------------------------------------------------------------

def test_cubic_spline_g1_start():
    """Cubic spline extended at start: G1 tangent dot product > 0.9999."""
    curve = _make_cubic_spline()
    delta = 0.3
    orig_tan = _unit_tangent_at_end(curve, end="start")
    result = extend_edge_curve(curve, delta_length_mm=delta, end="start")
    assert result.end_continuity_achieved == "G1"
    ext = result.extended_curve
    degree = ext.degree
    u_min = float(ext.knots[degree])
    u_max = float(ext.knots[ext.num_control_points])
    u_near_start = u_min + (u_max - u_min) * 0.01
    ext_tan_raw = curve_derivative(ext, u_near_start, order=1)
    ext_tan_len = float(np.linalg.norm(ext_tan_raw))
    ext_tan = -ext_tan_raw / (ext_tan_len if ext_tan_len > 1e-14 else 1.0)
    dot = float(np.dot(orig_tan, ext_tan))
    assert dot > 0.9999, f"Start extension G1 dot = {dot:.6f}"


# ---------------------------------------------------------------------------
# Test 8
# ---------------------------------------------------------------------------

def test_negative_delta_raises():
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
    with pytest.raises(ValueError, match="delta_length_mm"):
        extend_edge_curve(curve, delta_length_mm=-1.0)


# ---------------------------------------------------------------------------
# Test 9
# ---------------------------------------------------------------------------

def test_zero_delta_raises():
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
    with pytest.raises(ValueError, match="delta_length_mm"):
        extend_edge_curve(curve, delta_length_mm=0.0)


# ---------------------------------------------------------------------------
# Test 10
# ---------------------------------------------------------------------------

def test_invalid_end_raises():
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
    with pytest.raises(ValueError, match="end"):
        extend_edge_curve(curve, delta_length_mm=1.0, end="middle")


# ---------------------------------------------------------------------------
# Test 11: continuity='G2' now implemented, returns G2
# ---------------------------------------------------------------------------

def test_g2_accepted_and_returns_g2():
    """Requesting G2 should succeed and return G2 continuity achieved."""
    curve = _make_cubic_spline()
    result = extend_edge_curve(curve, delta_length_mm=0.2, continuity="G2")
    assert result.end_continuity_achieved == "G2", (
        f"Should be G2, got {result.end_continuity_achieved!r}"
    )
    assert "G2" in result.honest_caveat, "Caveat should mention G2"
    assert "not yet implemented" not in result.honest_caveat.lower(), (
        "Caveat must not say G2 is 'not yet implemented'; got: "
        + result.honest_caveat[:120]
    )


# ---------------------------------------------------------------------------
# Test 12
# ---------------------------------------------------------------------------

def test_2d_curve_extend():
    """A 2D curve (control points in R2) extends without error."""
    cps = np.array([[0.0, 0.0], [1.0, 1.0], [2.0, 0.0]], dtype=float)
    knots = np.array([0.0, 0.0, 0.0, 1.0, 1.0, 1.0])
    curve = NurbsCurve(degree=2, control_points=cps, knots=knots)
    result = extend_edge_curve(curve, delta_length_mm=0.5, end="end")
    ext = result.extended_curve
    assert ext.num_control_points > curve.num_control_points
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    end_pt = ext.evaluate(u_max)
    assert not np.any(np.isnan(end_pt)), "Extended endpoint has NaN"
    assert not np.any(np.isinf(end_pt)), "Extended endpoint has Inf"


# ---------------------------------------------------------------------------
# Test 13
# ---------------------------------------------------------------------------

def test_degree1_upgrades():
    """A degree-1 curve should be degree-raised when appending a cubic extension."""
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([2.0, 0.0, 0.0]))
    assert curve.degree == 1
    result = extend_edge_curve(curve, delta_length_mm=1.0, end="end")
    ext = result.extended_curve
    assert ext.degree >= 3, f"Expected degree >= 3, got {ext.degree}"
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    end_pt = ext.evaluate(u_max)
    assert abs(end_pt[0] - 3.0) < 1e-9, f"Expected x=3.0, got {end_pt[0]}"


# ---------------------------------------------------------------------------
# Test 14
# ---------------------------------------------------------------------------

def test_no_nan_inf():
    """Extended curve must evaluate without NaN/Inf across full domain."""
    curve = _make_cubic_spline()
    result = extend_edge_curve(curve, delta_length_mm=0.5, end="end")
    assert not _has_nan_inf(result.extended_curve, n_samples=50)


# ---------------------------------------------------------------------------
# Test 15
# ---------------------------------------------------------------------------

def test_reexport_dataclass():
    """EdgeExtendResult should be importable from kerf_cad_core.geom."""
    from kerf_cad_core.geom import EdgeExtendResult as EER  # noqa: F401
    assert EER is EdgeExtendResult


# ---------------------------------------------------------------------------
# Test 16
# ---------------------------------------------------------------------------

def test_reexport_function():
    """extend_edge_curve should be importable from kerf_cad_core.geom."""
    from kerf_cad_core.geom import extend_edge_curve as eec  # noqa: F401
    assert eec is extend_edge_curve


# ---------------------------------------------------------------------------
# Test 17
# ---------------------------------------------------------------------------

def test_original_length_positive():
    """original_length_mm should be > 0 for a non-degenerate curve."""
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([3.0, 4.0, 0.0]))
    result = extend_edge_curve(curve, delta_length_mm=1.0)
    assert result.original_length_mm > 0.0
    assert abs(result.original_length_mm - 5.0) < 1e-3, (
        f"Expected approx 5.0, got {result.original_length_mm}"
    )


# ---------------------------------------------------------------------------
# Test 18
# ---------------------------------------------------------------------------

def test_extended_length_greater():
    """extended_length_mm must always exceed original_length_mm."""
    curve = _make_cubic_spline()
    result = extend_edge_curve(curve, delta_length_mm=0.1)
    assert result.extended_length_mm > result.original_length_mm


# ---------------------------------------------------------------------------
# Test 19
# ---------------------------------------------------------------------------

def test_diagonal_line_end_point():
    """Line (0,0,0)->(3,4,0) extended by 5 at end -> (6,8,0)."""
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([3.0, 4.0, 0.0]))
    delta = 5.0
    result = extend_edge_curve(curve, delta_length_mm=delta, end="end")
    ext = result.extended_curve
    n = ext.num_control_points - 1
    u_max = float(ext.knots[n + 1])
    end_pt = ext.evaluate(u_max)
    assert abs(end_pt[0] - 6.0) < 1e-9, f"x should be 6.0, got {end_pt[0]}"
    assert abs(end_pt[1] - 8.0) < 1e-9, f"y should be 8.0, got {end_pt[1]}"
    assert abs(end_pt[2]) < 1e-9, f"z should be 0, got {end_pt[2]}"


# ---------------------------------------------------------------------------
# Test 20
# ---------------------------------------------------------------------------

def test_start_point_preserved_on_end_extension():
    """When extending at 'end', the start of the curve must be unchanged."""
    curve = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([1.0, 0.0, 0.0]))
    result = extend_edge_curve(curve, delta_length_mm=0.5, end="end")
    ext = result.extended_curve
    degree = ext.degree
    u_min = float(ext.knots[degree])
    start_pt = ext.evaluate(u_min)
    assert abs(start_pt[0]) < 1e-9, f"Start x should be 0, got {start_pt[0]}"
    assert abs(start_pt[1]) < 1e-9, f"Start y should be 0, got {start_pt[1]}"


# ---------------------------------------------------------------------------
# Test 21: continuity level is reflected in end_continuity_achieved
# ---------------------------------------------------------------------------

def test_continuity_string():
    """end_continuity_achieved reflects continuity level: G1->'G1', G2->'G2'."""
    curve = _make_cubic_spline()
    result_g1 = extend_edge_curve(curve, delta_length_mm=0.2, continuity="G1")
    assert result_g1.end_continuity_achieved == "G1", (
        f"continuity='G1': got {result_g1.end_continuity_achieved!r}"
    )
    result_g2 = extend_edge_curve(curve, delta_length_mm=0.2, continuity="G2")
    assert result_g2.end_continuity_achieved == "G2", (
        f"continuity='G2': got {result_g2.end_continuity_achieved!r}"
    )


# ===========================================================================
# G2 curvature-continuous extension tests (Patrikalakis-Maekawa s3.4)
# ===========================================================================


# ---------------------------------------------------------------------------
# Test 22: G2 parabola -- curvature continuous across join
# ---------------------------------------------------------------------------

def test_g2_parabola_curvature_continuity():
    """Extending parabola y=x^2 with G2: B'(0) and B''(0) match C'(u_end), C''(u_end)."""
    from kerf_cad_core.geom.curve_toolkit import interp_curve
    from kerf_cad_core.geom.edge_curve_extend import _make_g2_extension

    xs = np.linspace(0.0, 1.0, 20)
    pts = np.column_stack([xs, xs ** 2, np.zeros(20)])
    curve = interp_curve(pts, degree=3)

    delta = 0.3
    result_g2 = extend_edge_curve(curve, delta_length_mm=delta, continuity="G2")
    assert result_g2.end_continuity_achieved == "G2"

    n_orig = curve.num_control_points - 1
    u_eval = float(curve.knots[n_orig + 1])
    D1 = curve_derivative(curve, u_eval, order=1)
    D2 = curve_derivative(curve, u_eval, order=2)
    P0 = curve.evaluate(u_eval)
    tan_unit = D1 / np.linalg.norm(D1)
    P_end = P0 + tan_unit * delta

    Q = _make_g2_extension(P0, D1, D2, P_end)

    B_D1 = 5.0 * (Q[1] - Q[0])
    assert np.allclose(B_D1, D1, atol=1e-10), (
        f"G2 parabola: B'(0) != D1: diff={np.linalg.norm(B_D1 - D1):.2e}"
    )
    B_D2 = 20.0 * (Q[0] - 2.0 * Q[1] + Q[2])
    assert np.allclose(B_D2, D2, atol=1e-10), (
        f"G2 parabola: B''(0) != D2: diff={np.linalg.norm(B_D2 - D2):.2e}"
    )


# ---------------------------------------------------------------------------
# Test 23: G2 circle arc -- curvature matches at join
# ---------------------------------------------------------------------------

def test_g2_circle_arc_curvature():
    """Extending circle arc with G2: extension B'(0)=D1, B''(0)=D2; kappa_orig ~1/R."""
    from kerf_cad_core.geom.curve_toolkit import interp_curve
    from kerf_cad_core.geom.edge_curve_extend import _make_g2_extension

    R = 1.0
    n_pts = 40
    ts = np.linspace(0.0, math.pi / 2.0, n_pts)
    pts = np.column_stack([R * np.cos(ts), R * np.sin(ts), np.zeros(n_pts)])
    curve = interp_curve(pts, degree=3)

    delta = 0.2
    result_g2 = extend_edge_curve(curve, delta_length_mm=delta, continuity="G2")
    assert result_g2.end_continuity_achieved == "G2"

    n_orig = curve.num_control_points - 1
    u_eval = float(curve.knots[n_orig + 1])
    D1 = curve_derivative(curve, u_eval, order=1)
    D2 = curve_derivative(curve, u_eval, order=2)
    P0 = curve.evaluate(u_eval)
    tan_unit = D1 / np.linalg.norm(D1)
    P_end = P0 + tan_unit * delta

    Q = _make_g2_extension(P0, D1, D2, P_end)
    B_D1 = 5.0 * (Q[1] - Q[0])
    B_D2 = 20.0 * (Q[0] - 2.0 * Q[1] + Q[2])

    assert np.allclose(B_D1, D1, atol=1e-10), (
        f"Circle G2: B'(0) != D1: diff={np.linalg.norm(B_D1 - D1):.2e}"
    )
    assert np.allclose(B_D2, D2, atol=1e-10), (
        f"Circle G2: B''(0) != D2: diff={np.linalg.norm(B_D2 - D2):.2e}"
    )

    kappa_orig = _curvature_at_end(curve, end="end")
    assert abs(kappa_orig - 1.0 / R) < 0.05, (
        f"Original circle curvature should be approx {1.0/R:.3f}, got {kappa_orig:.4f}"
    )


# ---------------------------------------------------------------------------
# Test 24: G2 cubic spline -- 2nd derivative continuous at join
# ---------------------------------------------------------------------------

def test_g2_cubic_spline_second_derivative():
    """Cubic spline with G2: B''(0) of extension matches C''(u_end)."""
    from kerf_cad_core.geom.edge_curve_extend import _make_g2_extension

    curve = _make_cubic_spline()
    delta = 0.3

    n_orig = curve.num_control_points - 1
    u_eval = float(curve.knots[n_orig + 1])
    D1 = curve_derivative(curve, u_eval, order=1)
    D2 = curve_derivative(curve, u_eval, order=2)
    P0 = curve.evaluate(u_eval)
    tan_unit = D1 / np.linalg.norm(D1)
    P_end = P0 + tan_unit * delta

    Q = _make_g2_extension(P0, D1, D2, P_end)

    B_D1 = 5.0 * (Q[1] - Q[0])
    assert np.allclose(B_D1, D1, atol=1e-10), (
        f"Cubic G2: B'(0) mismatch: diff={np.linalg.norm(B_D1 - D1):.2e}"
    )
    B_D2 = 20.0 * (Q[0] - 2.0 * Q[1] + Q[2])
    assert np.allclose(B_D2, D2, atol=1e-10), (
        f"Cubic G2: B''(0) mismatch: diff={np.linalg.norm(B_D2 - D2):.2e}"
    )


# ---------------------------------------------------------------------------
# Test 25: G2 has lower curvature jump than G1
# ---------------------------------------------------------------------------

def test_g2_lower_curvature_jump_than_g1():
    """G2 extension has strictly smaller curvature jump at join than G1."""
    from kerf_cad_core.geom.curve_toolkit import interp_curve
    from kerf_cad_core.geom.edge_curve_extend import _make_g2_extension

    n_pts = 30
    ts = np.linspace(0.0, math.pi / 2.0, n_pts)
    pts = np.column_stack([2.0 * np.cos(ts), np.sin(ts), np.zeros(n_pts)])
    curve = interp_curve(pts, degree=3)

    delta = 0.4
    kappa_orig = _curvature_at_end(curve, end="end")
    assert kappa_orig > 0.1, f"Original curvature should be significant, got {kappa_orig:.4f}"

    # G1 extension: kappa=0 from extension side -> jump = kappa_orig.
    kappa_jump_g1 = kappa_orig

    # G2 extension: compute kappa at t=0 from Bezier patch.
    n_orig = curve.num_control_points - 1
    u_eval = float(curve.knots[n_orig + 1])
    D1 = curve_derivative(curve, u_eval, order=1)
    D2 = curve_derivative(curve, u_eval, order=2)
    P0 = curve.evaluate(u_eval)
    tan_unit = D1 / float(np.linalg.norm(D1))
    P_end = P0 + tan_unit * delta
    Q = _make_g2_extension(P0, D1, D2, P_end)
    B_D1 = 5.0 * (Q[1] - Q[0])
    B_D2 = 20.0 * (Q[0] - 2.0 * Q[1] + Q[2])
    if B_D1.shape[0] == 2:
        cross_mag = abs(B_D1[0] * B_D2[1] - B_D1[1] * B_D2[0])
    else:
        cross = np.cross(B_D1[:3], B_D2[:3])
        cross_mag = float(np.linalg.norm(cross))
    kappa_ext_g2 = cross_mag / float(np.linalg.norm(B_D1)) ** 3
    kappa_jump_g2 = abs(kappa_ext_g2 - kappa_orig)

    result_g2 = extend_edge_curve(curve, delta_length_mm=delta, continuity="G2")
    assert result_g2.end_continuity_achieved == "G2"

    assert kappa_jump_g2 < kappa_jump_g1, (
        f"G2 jump ({kappa_jump_g2:.4f}) must be less than G1 jump ({kappa_jump_g1:.4f})"
    )
    assert kappa_jump_g2 < 1e-8, (
        f"G2 curvature jump should be approx 0, got {kappa_jump_g2:.2e}"
    )


# ---------------------------------------------------------------------------
# Test 26: G2 caveat does NOT mention 'not yet implemented'
# ---------------------------------------------------------------------------

def test_g2_caveat_no_not_yet_implemented():
    """G2 honest_caveat must not say 'not yet implemented' (it is now)."""
    curve = _make_cubic_spline()
    result = extend_edge_curve(curve, delta_length_mm=0.5, continuity="G2")
    caveat = result.honest_caveat.lower()
    assert "not yet implemented" not in caveat, (
        "G2 caveat must not say 'not yet implemented'; got: "
        + result.honest_caveat[:120]
    )
    assert "g2" in caveat, "G2 caveat should mention G2"
    assert "g3" in caveat, "G2 caveat should honestly note G3 is not enforced"


# ---------------------------------------------------------------------------
# Test 27: G2 extension at start -- curvature continuous
# ---------------------------------------------------------------------------

def test_g2_start_extension_curvature():
    """G2 extension at 'start': B'(0) and B''(0) match outward D1/D2 at u_start."""
    from kerf_cad_core.geom.edge_curve_extend import _make_g2_extension

    curve = _make_cubic_spline()
    delta = 0.25

    degree = curve.degree
    u_start = float(curve.knots[degree])
    D1_start = curve_derivative(curve, u_start, order=1)
    D2_start = curve_derivative(curve, u_start, order=2)
    D1_out = -D1_start
    D2_out = -D2_start

    P0 = curve.evaluate(u_start)
    tan_unit = D1_out / np.linalg.norm(D1_out)
    P_end = P0 + tan_unit * delta

    Q = _make_g2_extension(P0, D1_out, D2_out, P_end)
    B_D1 = 5.0 * (Q[1] - Q[0])
    B_D2 = 20.0 * (Q[0] - 2.0 * Q[1] + Q[2])

    assert np.allclose(B_D1, D1_out, atol=1e-10), (
        f"G2 start: B'(0) != D1_out: diff={np.linalg.norm(B_D1 - D1_out):.2e}"
    )
    assert np.allclose(B_D2, D2_out, atol=1e-10), (
        f"G2 start: B''(0) != D2_out: diff={np.linalg.norm(B_D2 - D2_out):.2e}"
    )

    result = extend_edge_curve(curve, delta_length_mm=delta, end="start", continuity="G2")
    assert result.end_continuity_achieved == "G2"
    assert not _has_nan_inf(result.extended_curve, n_samples=30)


# ---------------------------------------------------------------------------
# Test 28: G2 extension produces degree-5 curve
# ---------------------------------------------------------------------------

def test_g2_extension_is_quintic():
    """G2 extension uses quintic (degree-5) Bezier -> merged curve is degree 5."""
    curve = _make_cubic_spline()
    result = extend_edge_curve(curve, delta_length_mm=0.4, continuity="G2")
    assert result.extended_curve.degree == 5, (
        f"G2 extension should produce degree-5 curve, got {result.extended_curve.degree}"
    )
    assert result.extended_curve.num_control_points > curve.num_control_points


# ---------------------------------------------------------------------------
# Test 29: G2 extended curve has no NaN/Inf
# ---------------------------------------------------------------------------

def test_g2_no_nan_inf():
    """G2 extended curve must evaluate without NaN/Inf across full domain."""
    curve = _make_cubic_spline()
    result = extend_edge_curve(curve, delta_length_mm=0.5, continuity="G2")
    assert not _has_nan_inf(result.extended_curve, n_samples=60)


# ---------------------------------------------------------------------------
# Test 30: G2 extended length > original length
# ---------------------------------------------------------------------------

def test_g2_extended_length_greater():
    """G2 extended_length_mm must exceed original_length_mm."""
    curve = _make_cubic_spline()
    result = extend_edge_curve(curve, delta_length_mm=0.3, continuity="G2")
    assert result.extended_length_mm > result.original_length_mm, (
        f"G2 extended={result.extended_length_mm:.6f} <= "
        f"original={result.original_length_mm:.6f}"
    )
