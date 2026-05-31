"""
Tests for kerf_cad_core.geom.curve_line_fit — NURBS-curve straight-line fitting.

All tests are hermetic: no OCC, no database, no network.

Groups
------
 1. Exact horizontal line (0,0)→(10,0)  — origin centroid, dir=(1,0), rms<1e-12
 2. Exact diagonal line (5,5)→(15,15)   — dir proportional to (1,1)/√2
 3. Vertical line (0,0)→(0,10)          — dir=(0,1), rms<1e-12
 4. Negative-slope line (-5,5)→(5,-5)   — dir=(1,0) negated correctly
 5. Off-origin horizontal                — origin at midpoint, correct dir
 6. Circle (NOT a line)                  — rms huge, honest caveat
 7. Noisy line                           — rms close to noise std
 8. NurbsCurve input (make_line_nurbs)   — exact line → rms<1e-12
 9. Raw list-of-lists input              — API accepts plain Python lists
10. Single-point / 1-point degenerate   — graceful result, caveat set
11. All-identical points (degenerate)   — graceful, direction placeholder
12. Direction unit-length               — ‖dir‖ = 1.0 always
13. Linearity R² > 0.999 for exact line
14. Large-offset line                   — translation invariance
15. LineFitResult fields typed correctly (is_planar_line always True)
16. Diagonal fit: perpendicular residuals < 1e-10 (exact samples)
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.curve_line_fit import LineFitResult, fit_line_to_curve
from kerf_cad_core.geom.nurbs import make_line_nurbs, make_circle_nurbs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _line_points(x0: float, y0: float, x1: float, y1: float, n: int = 200) -> np.ndarray:
    """Exact uniformly-spaced 2D point sample along a line segment."""
    t = np.linspace(0.0, 1.0, n)
    xs = x0 + t * (x1 - x0)
    ys = y0 + t * (y1 - y0)
    return np.column_stack([xs, ys])


def _circle_points(cx: float, cy: float, r: float, n: int = 200) -> np.ndarray:
    """Exact analytical circle sample."""
    theta = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    return np.column_stack([cx + r * np.cos(theta), cy + r * np.sin(theta)])


# ---------------------------------------------------------------------------
# 1. Exact horizontal line (0,0)→(10,0)
# ---------------------------------------------------------------------------

class TestExactHorizontalLine:
    """fit_line_to_curve on a horizontal line → origin=(5,0), dir=(1,0), rms≈0."""

    def setup_method(self):
        pts = _line_points(0.0, 0.0, 10.0, 0.0, n=100)
        self.result = fit_line_to_curve(pts)

    def test_origin_x(self):
        assert abs(self.result.origin_xy[0] - 5.0) < 1e-12

    def test_origin_y(self):
        assert abs(self.result.origin_xy[1] - 0.0) < 1e-12

    def test_direction_is_unit(self):
        dx, dy = self.result.direction_xy
        assert abs(math.hypot(dx, dy) - 1.0) < 1e-12

    def test_direction_horizontal(self):
        dx, dy = self.result.direction_xy
        # Direction should be (±1, 0); canonicalized to (+1, 0)
        assert abs(abs(dx) - 1.0) < 1e-10
        assert abs(dy) < 1e-10

    def test_rms_near_zero(self):
        assert self.result.rms_residual_mm < 1e-12

    def test_max_near_zero(self):
        assert self.result.max_residual_mm < 1e-12

    def test_is_planar_line_true(self):
        assert self.result.is_planar_line is True


# ---------------------------------------------------------------------------
# 2. Exact diagonal line (5,5)→(15,15)
# ---------------------------------------------------------------------------

class TestExactDiagonalLine:
    """45° diagonal — direction proportional to (1,1)/√2."""

    def setup_method(self):
        pts = _line_points(5.0, 5.0, 15.0, 15.0, n=200)
        self.result = fit_line_to_curve(pts)

    def test_direction_45deg(self):
        dx, dy = self.result.direction_xy
        inv_sqrt2 = 1.0 / math.sqrt(2.0)
        assert abs(abs(dx) - inv_sqrt2) < 1e-10, f"dx={dx}"
        assert abs(abs(dy) - inv_sqrt2) < 1e-10, f"dy={dy}"

    def test_dx_equals_dy(self):
        dx, dy = self.result.direction_xy
        assert abs(abs(dx) - abs(dy)) < 1e-10

    def test_rms_near_zero(self):
        assert self.result.rms_residual_mm < 1e-12

    def test_origin_at_centroid(self):
        # Midpoint of (5,5)→(15,15) is (10,10)
        assert abs(self.result.origin_xy[0] - 10.0) < 1e-10
        assert abs(self.result.origin_xy[1] - 10.0) < 1e-10


# ---------------------------------------------------------------------------
# 3. Circle (NOT a line) — large residual, honest caveat
# ---------------------------------------------------------------------------

class TestCircleNotALine:
    """A circle should produce large rms residual and a populated caveat."""

    def setup_method(self):
        pts = _circle_points(cx=0.0, cy=0.0, r=5.0, n=200)
        self.result = fit_line_to_curve(pts)

    def test_rms_is_large(self):
        # For a circle of radius 5, the average perpendicular distance to
        # the best-fit line through the center is ≈ π/4 × r ≈ 3.93 mm
        assert self.result.rms_residual_mm > 1.0, (
            f"Expected large RMS for circle, got {self.result.rms_residual_mm}"
        )

    def test_caveat_populated(self):
        assert self.result.honest_caveat != "", (
            "Expected honest_caveat to be non-empty for circle input"
        )

    def test_direction_still_unit(self):
        dx, dy = self.result.direction_xy
        assert abs(math.hypot(dx, dy) - 1.0) < 1e-12

    def test_is_planar_line_true(self):
        assert self.result.is_planar_line is True


# ---------------------------------------------------------------------------
# 4. Noisy line — rms close to noise std
# ---------------------------------------------------------------------------

class TestNoisyLine:
    """Add Gaussian noise in the perpendicular direction; rms should ≈ noise std."""

    def test_noisy_line_rms_matches_noise(self):
        rng = np.random.default_rng(42)
        noise_std = 0.05  # mm

        # Exact horizontal line samples
        t = np.linspace(0.0, 20.0, 500)
        pts = np.column_stack([t, np.zeros_like(t)])

        # Add pure perpendicular (y) noise
        pts[:, 1] += rng.normal(0.0, noise_std, size=len(t))

        result = fit_line_to_curve(pts)

        # RMS should be within 20% of the noise std (asymptotes to noise_std
        # for large N because the perpendicular residuals *are* the noise)
        assert abs(result.rms_residual_mm - noise_std) < 0.20 * noise_std, (
            f"RMS={result.rms_residual_mm:.4f}, expected ≈{noise_std}"
        )

    def test_noisy_line_direction_nearly_horizontal(self):
        rng = np.random.default_rng(0)
        t = np.linspace(0.0, 10.0, 300)
        pts = np.column_stack([t, rng.normal(0.0, 0.01, size=len(t))])
        result = fit_line_to_curve(pts)
        dx, dy = result.direction_xy
        assert abs(abs(dx) - 1.0) < 0.01, f"dx={dx}"
        assert abs(dy) < 0.01, f"dy={dy}"


# ---------------------------------------------------------------------------
# 5. NurbsCurve input via make_line_nurbs
# ---------------------------------------------------------------------------

class TestNurbsCurveInput:
    """Pass a proper NurbsCurve object; should handle sampling internally."""

    def test_line_nurbs_horizontal(self):
        curve = make_line_nurbs(
            np.array([0.0, 0.0]), np.array([10.0, 0.0])
        )
        result = fit_line_to_curve(curve, num_samples=50)
        assert result.rms_residual_mm < 1e-12
        dx, dy = result.direction_xy
        assert abs(abs(dx) - 1.0) < 1e-10
        assert abs(dy) < 1e-10

    def test_line_nurbs_diagonal(self):
        curve = make_line_nurbs(
            np.array([0.0, 0.0]), np.array([10.0, 10.0])
        )
        result = fit_line_to_curve(curve, num_samples=100)
        assert result.rms_residual_mm < 1e-12
        dx, dy = result.direction_xy
        inv_sqrt2 = 1.0 / math.sqrt(2.0)
        assert abs(abs(dx) - inv_sqrt2) < 1e-10
        assert abs(abs(dy) - inv_sqrt2) < 1e-10


# ---------------------------------------------------------------------------
# 6. Raw list-of-lists input
# ---------------------------------------------------------------------------

def test_list_of_lists_input():
    """fit_line_to_curve accepts plain Python list-of-lists."""
    pts = [[i * 1.0, 0.0] for i in range(20)]
    result = fit_line_to_curve(pts)
    assert result.rms_residual_mm < 1e-12
    dx, _ = result.direction_xy
    assert abs(abs(dx) - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# 7. Degenerate / edge cases
# ---------------------------------------------------------------------------

def test_single_point_graceful():
    """Only 1 point: return graceful result with caveat."""
    result = fit_line_to_curve([[3.0, 4.0]])
    assert "Only 1 point" in result.honest_caveat or not math.isfinite(result.rms_residual_mm)
    assert result.is_planar_line is True


def test_all_identical_points_graceful():
    """All points identical: return graceful result with caveat."""
    pts = [[5.0, 5.0]] * 50
    result = fit_line_to_curve(pts)
    assert "degenerate" in result.honest_caveat.lower() or result.rms_residual_mm == 0.0
    assert result.is_planar_line is True


# ---------------------------------------------------------------------------
# 8. Direction is always a unit vector
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pts,label", [
    (_line_points(0, 0, 1, 0), "horizontal"),
    (_line_points(0, 0, 0, 1), "vertical"),
    (_line_points(0, 0, 1, 1), "diagonal"),
    (_line_points(-3, 7, 15, -2), "arbitrary"),
    (_circle_points(0, 0, 5), "circle"),
])
def test_direction_always_unit(pts, label):
    result = fit_line_to_curve(pts)
    dx, dy = result.direction_xy
    assert abs(math.hypot(dx, dy) - 1.0) < 1e-10, (
        f"Direction not unit for {label}: ({dx}, {dy})"
    )


# ---------------------------------------------------------------------------
# 9. Vertical line
# ---------------------------------------------------------------------------

def test_vertical_line_direction():
    """Vertical line (0,0)→(0,10): direction should be (0,1)."""
    pts = _line_points(0.0, 0.0, 0.0, 10.0, n=100)
    result = fit_line_to_curve(pts)
    dx, dy = result.direction_xy
    assert abs(dx) < 1e-10, f"dx={dx} should be ~0 for vertical line"
    assert abs(abs(dy) - 1.0) < 1e-10
    assert result.rms_residual_mm < 1e-12


def test_vertical_line_rms_near_zero():
    pts = _line_points(3.0, -5.0, 3.0, 15.0, n=200)
    result = fit_line_to_curve(pts)
    assert result.rms_residual_mm < 1e-12


# ---------------------------------------------------------------------------
# 10. Translation invariance (large-offset line)
# ---------------------------------------------------------------------------

def test_large_offset_translation_invariance():
    """Line at large offset — origin and direction should still be correct."""
    pts = _line_points(1e6, 2e6, 1e6 + 10.0, 2e6, n=100)
    result = fit_line_to_curve(pts)
    assert abs(result.origin_xy[0] - (1e6 + 5.0)) < 1e-6
    assert abs(result.origin_xy[1] - 2e6) < 1e-6
    dx, dy = result.direction_xy
    assert abs(abs(dx) - 1.0) < 1e-8
    assert abs(dy) < 1e-8
    assert result.rms_residual_mm < 1e-6


# ---------------------------------------------------------------------------
# 11. LineFitResult fields have correct types
# ---------------------------------------------------------------------------

def test_result_field_types():
    pts = _line_points(0.0, 0.0, 5.0, 5.0, n=50)
    result = fit_line_to_curve(pts)
    assert isinstance(result, LineFitResult)
    assert isinstance(result.origin_xy, tuple) and len(result.origin_xy) == 2
    assert isinstance(result.direction_xy, tuple) and len(result.direction_xy) == 2
    assert isinstance(result.rms_residual_mm, float)
    assert isinstance(result.max_residual_mm, float)
    assert isinstance(result.is_planar_line, bool)
    assert isinstance(result.honest_caveat, str)
    assert result.is_planar_line is True


# ---------------------------------------------------------------------------
# 12. max_residual >= rms_residual
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pts,label", [
    (_line_points(0, 0, 10, 0), "exact"),
    (_circle_points(0, 0, 5), "circle"),
])
def test_max_ge_rms(pts, label):
    result = fit_line_to_curve(pts)
    if math.isfinite(result.rms_residual_mm) and math.isfinite(result.max_residual_mm):
        assert result.max_residual_mm >= result.rms_residual_mm - 1e-14, (
            f"{label}: max={result.max_residual_mm} < rms={result.rms_residual_mm}"
        )


# ---------------------------------------------------------------------------
# 13. Perpendicular residuals for exact diagonal are near-zero
# ---------------------------------------------------------------------------

def test_diagonal_perpendicular_residuals_exact():
    """For a 45° exact line, perpendicular residuals should be < 1e-10."""
    pts = _line_points(0.0, 0.0, 10.0, 10.0, n=200)
    result = fit_line_to_curve(pts)
    assert result.rms_residual_mm < 1e-10
    assert result.max_residual_mm < 1e-10


# ---------------------------------------------------------------------------
# 14. Num-samples parameter respected for NurbsCurve
# ---------------------------------------------------------------------------

def test_num_samples_parameter():
    """num_samples controls how many points are evaluated from a NurbsCurve."""
    curve = make_line_nurbs(np.array([0.0, 0.0]), np.array([10.0, 0.0]))
    for ns in [2, 10, 50, 200]:
        result = fit_line_to_curve(curve, num_samples=ns)
        assert result.rms_residual_mm < 1e-11, f"num_samples={ns} gave rms={result.rms_residual_mm}"
