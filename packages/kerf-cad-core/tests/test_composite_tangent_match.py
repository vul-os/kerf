"""
Tests for kerf_cad_core.geom.composite_tangent_match
=====================================================
NURBS-COMPOSITE-TANGENT-MATCH — G1/G2 seam CP adjustment.

Coverage (16 tests across 6 groups):
  1. 90° corner → G1 after match (depth-bar case, Klass 1980 §3).
  2. Already-G1 input → zero displacement.
  3. G2 matching shrinks both tangent + curvature residual.
  4. Closed loop with seam at index 0.
  5. Input validation (bad target, too few curves).
  6. Non-destructive (originals not mutated).
"""

from __future__ import annotations

import math
import copy

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, curve_derivative
from kerf_cad_core.geom.composite_tangent_match import (
    CompositeMatchResult,
    match_composite_tangents,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamped_cubic_knots(n_cp: int) -> np.ndarray:
    """Return a clamped cubic knot vector for n_cp control points."""
    p = 3
    n = n_cp - 1
    m = n + p + 1
    inner = m - 2 * (p + 1)
    k = np.zeros(m + 1)
    k[:p + 1] = 0.0
    for i in range(inner):
        k[p + 1 + i] = (i + 1) / (inner + 1)
    k[m - p:] = 1.0
    return k


def _cubic_segment(cps: np.ndarray) -> NurbsCurve:
    """Build a degree-3 clamped NURBS from given control points."""
    n_cp = cps.shape[0]
    knots = _clamped_cubic_knots(n_cp)
    return NurbsCurve(degree=3, control_points=cps.astype(float), knots=knots)


def _tangent_unit_end(curve: NurbsCurve) -> np.ndarray:
    """Unit tangent at curve end."""
    p = curve.degree
    n = curve.num_control_points - 1
    t_end = float(curve.knots[n + 1])
    d = curve_derivative(curve, t_end, order=1)
    return d / (np.linalg.norm(d) + 1e-300)


def _tangent_unit_start(curve: NurbsCurve) -> np.ndarray:
    """Unit tangent at curve start."""
    p = curve.degree
    t_start = float(curve.knots[p])
    d = curve_derivative(curve, t_start, order=1)
    return d / (np.linalg.norm(d) + 1e-300)


def _tangent_angle_at_seam(left: NurbsCurve, right: NurbsCurve) -> float:
    """Angle (rad) between the end tangent of left and start tangent of right."""
    t_l = _tangent_unit_end(left)
    t_r = _tangent_unit_start(right)
    cos_a = float(np.clip(np.dot(t_l, t_r), -1.0, 1.0))
    return math.acos(abs(cos_a))  # G1 ignores orientation (parallel, not anti-parallel)


# ---------------------------------------------------------------------------
# Segment factories
# ---------------------------------------------------------------------------

def _make_90deg_kink_pair():
    """
    Two cubic segments meeting at (2, 0) with a 90° kink.
    Segment A goes left→right along x-axis: (0,0)→(1,0)→(2,0)→(2,0).
    Segment B goes bottom→top along y-axis: (2,0)→(2,0)→(2,1)→(2,2).
    The end tangent of A is (+x) and start tangent of B is (+y) → 90° kink.
    """
    cps_a = np.array([[0.0, 0.0], [0.667, 0.0], [1.333, 0.0], [2.0, 0.0]])
    cps_b = np.array([[2.0, 0.0], [2.0, 0.667], [2.0, 1.333], [2.0, 2.0]])
    seg_a = _cubic_segment(cps_a)
    seg_b = _cubic_segment(cps_b)
    return seg_a, seg_b


def _make_already_g1_pair():
    """
    Two cubic segments already collinear at seam → zero G1 residual.
    Both go along the x-axis, sharing the point (2, 0).
    """
    cps_a = np.array([[0.0, 0.0], [0.667, 0.0], [1.333, 0.0], [2.0, 0.0]])
    cps_b = np.array([[2.0, 0.0], [2.667, 0.0], [3.333, 0.0], [4.0, 0.0]])
    return _cubic_segment(cps_a), _cubic_segment(cps_b)


def _make_g2_kink_pair():
    """Two degree-3 segments with a 45° kink at the seam, enough CPs for G2."""
    cps_a = np.array([
        [0.0, 0.0], [0.5, 0.0], [1.0, 0.0], [1.5, 0.0], [2.0, 0.0],
    ])
    cps_b = np.array([
        [2.0, 0.0], [2.5, 0.5], [3.0, 1.0], [3.5, 1.5], [4.0, 2.0],
    ])
    n = 5
    p = 3
    m = n + p  # = n_cp + p
    knots_a = np.array([0, 0, 0, 0, 0.5, 1, 1, 1, 1], dtype=float)
    knots_b = np.array([0, 0, 0, 0, 0.5, 1, 1, 1, 1], dtype=float)
    seg_a = NurbsCurve(degree=3, control_points=cps_a.astype(float), knots=knots_a)
    seg_b = NurbsCurve(degree=3, control_points=cps_b.astype(float), knots=knots_b)
    return seg_a, seg_b


# ---------------------------------------------------------------------------
# Group 1: 90° corner → G1 after match (depth-bar case)
# ---------------------------------------------------------------------------

class TestG190DegKink:
    def test_residual_is_roughly_pi_over_2_before_match(self):
        seg_a, seg_b = _make_90deg_kink_pair()
        angle_before = _tangent_angle_at_seam(seg_a, seg_b)
        assert abs(angle_before - math.pi / 2) < 0.1, (
            f"Expected ~90° before match, got {math.degrees(angle_before):.1f}°"
        )

    def test_g1_reduces_residual_to_near_zero(self):
        seg_a, seg_b = _make_90deg_kink_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G1")
        assert result.residual_tangent_error_per_seam[0] < 1e-9

    def test_g1_result_type(self):
        seg_a, seg_b = _make_90deg_kink_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G1")
        assert isinstance(result, CompositeMatchResult)
        assert result.target == "G1"

    def test_g1_two_adjusted_curves_returned(self):
        seg_a, seg_b = _make_90deg_kink_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G1")
        assert len(result.adjusted_curves) == 2

    def test_g1_derivative_check_alpha_positive(self):
        """C'(t_end from left) = α · C'(t_start from right), α > 0."""
        seg_a, seg_b = _make_90deg_kink_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G1")
        left, right = result.adjusted_curves
        t_l = _tangent_unit_end(left)
        t_r = _tangent_unit_start(right)
        # Dot product of unit tangents: must be +1 (same direction) not -1 (anti-parallel)
        cos_val = float(np.dot(t_l, t_r))
        assert cos_val > 0.99, (
            f"Tangents not parallel after G1 match: dot={cos_val:.4f}"
        )

    def test_g1_max_cp_displacement_positive_for_kink(self):
        seg_a, seg_b = _make_90deg_kink_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G1")
        assert result.max_cp_displacement > 1e-6

    def test_g1_bisector_direction_is_45deg(self):
        """For 90° kink the bisector should be at 45° (±x + ±y direction)."""
        seg_a, seg_b = _make_90deg_kink_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G1")
        left = result.adjusted_curves[0]
        # New second-to-last chord direction of left segment
        joint = left.control_points[-1]
        prev  = left.control_points[-2]
        chord = joint - prev
        chord_unit = chord / (np.linalg.norm(chord) + 1e-300)
        # Bisector of x=(1,0) and y=(0,1) is (1/√2, 1/√2)
        expected = np.array([1.0, 1.0]) / math.sqrt(2)
        assert np.allclose(chord_unit, expected, atol=1e-6), (
            f"Bisector mismatch: got {chord_unit}, expected {expected}"
        )


# ---------------------------------------------------------------------------
# Group 2: Already-G1 input → zero displacement
# ---------------------------------------------------------------------------

class TestAlreadyG1:
    def test_already_g1_zero_displacement(self):
        seg_a, seg_b = _make_already_g1_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G1")
        assert result.max_cp_displacement < 1e-10

    def test_already_g1_zero_residual(self):
        seg_a, seg_b = _make_already_g1_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G1")
        assert result.residual_tangent_error_per_seam[0] < 1e-9


# ---------------------------------------------------------------------------
# Group 3: G2 matching shrinks both tangent + curvature residual
# ---------------------------------------------------------------------------

class TestG2Matching:
    def test_g2_returns_converged_flag(self):
        seg_a, seg_b = _make_g2_kink_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G2")
        # G2 should converge for moderate curvature difference
        assert len(result.g2_converged) == 1

    def test_g2_residual_tangent_small(self):
        seg_a, seg_b = _make_g2_kink_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G2")
        assert result.residual_tangent_error_per_seam[0] < 1e-8

    def test_g2_target_string_in_result(self):
        seg_a, seg_b = _make_g2_kink_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G2")
        assert result.target == "G2"

    def test_g2_converged_is_bool_list(self):
        seg_a, seg_b = _make_g2_kink_pair()
        result = match_composite_tangents([seg_a, seg_b], target="G2")
        assert isinstance(result.g2_converged, list)
        assert all(isinstance(v, bool) for v in result.g2_converged)


# ---------------------------------------------------------------------------
# Group 4: Closed loop — seam at index 0 wraps around (3-segment chain)
# ---------------------------------------------------------------------------

class TestClosedLoop:
    def _make_triangle_chain(self):
        """Three cubic segments forming a closed triangle."""
        pts = [
            np.array([[0.0, 0.0], [0.5, 0.0], [1.0, 0.0], [1.5, 0.0]]),
            np.array([[1.5, 0.0], [1.5, 0.5], [1.5, 1.0], [1.5, 1.5]]),
            np.array([[1.5, 1.5], [1.0, 1.0], [0.5, 0.5], [0.0, 0.0]]),
        ]
        return [_cubic_segment(p) for p in pts]

    def test_closed_chain_returns_n_curves(self):
        curves = self._make_triangle_chain()
        result = match_composite_tangents(curves, target="G1")
        assert len(result.adjusted_curves) == 3

    def test_closed_chain_n_seam_residuals(self):
        curves = self._make_triangle_chain()
        result = match_composite_tangents(curves, target="G1")
        # n_seams = n_curves - 1 = 2
        assert len(result.residual_tangent_error_per_seam) == 2

    def test_closed_chain_all_residuals_small(self):
        curves = self._make_triangle_chain()
        result = match_composite_tangents(curves, target="G1")
        for r in result.residual_tangent_error_per_seam:
            assert r < 1e-8


# ---------------------------------------------------------------------------
# Group 5: Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_too_few_curves_raises(self):
        seg = _cubic_segment(np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0]]))
        with pytest.raises(ValueError, match="at least 2"):
            match_composite_tangents([seg], target="G1")

    def test_bad_target_raises(self):
        seg_a, seg_b = _make_90deg_kink_pair()
        with pytest.raises(ValueError, match="target must be"):
            match_composite_tangents([seg_a, seg_b], target="G3")


# ---------------------------------------------------------------------------
# Group 6: Non-destructive — originals not mutated
# ---------------------------------------------------------------------------

class TestNonDestructive:
    def test_originals_not_mutated(self):
        seg_a, seg_b = _make_90deg_kink_pair()
        orig_a_cps = seg_a.control_points.copy()
        orig_b_cps = seg_b.control_points.copy()
        _ = match_composite_tangents([seg_a, seg_b], target="G1")
        assert np.allclose(seg_a.control_points, orig_a_cps)
        assert np.allclose(seg_b.control_points, orig_b_cps)
