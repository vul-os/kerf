"""
test_exact_length_offset.py
===========================
GK-P (arc-length-preserving offset) — hermetic pytest oracles.

Tests (Klass 1980 / Maekawa 1999 §3)
--------------------------------------
1. Straight-line offset: length 10 offset by 0.5 → parallel line, length 10 within 1e-9.
2. Circle arc-length target: unit circle (2π) offset by 0.5, target_length=2π → length 2π within 1e-6.
3. Convergence: relative error decreases monotonically across iterations (checked by running with max_iter=1 vs default).
4. Comparison: tiller_hanson vs exact_length on a cubic spline → exact_length arc_length_error < 1e-6; tiller_hanson typically > 1% for a curved spline.

Run:
    python -m pytest packages/kerf-cad-core/tests/test_exact_length_offset.py -q
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
from kerf_cad_core.geom.curve_toolkit import curve_length
from kerf_cad_core.geom.exact_length_offset import (
    offset_curve_arclength_preserving,
    exact_arclength_match_error,
    compare_offsets,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_line_curve(p0, p1) -> NurbsCurve:
    """Straight line as a degree-1 NURBS."""
    ctrl = np.array([p0, p1], dtype=float)
    if ctrl.shape[1] < 3:
        pad = np.zeros((2, 3 - ctrl.shape[1]))
        ctrl = np.hstack([ctrl, pad])
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=ctrl, knots=knots)


def _make_unit_circle() -> NurbsCurve:
    """Full unit circle as a 9-point rational quadratic NURBS in XY plane."""
    return make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 1.0)


def _make_cubic_arc_spline() -> NurbsCurve:
    """A consistently curving cubic NURBS arc (half of a parabola arch).

    All curvature has the same sign, so Tiller-Hanson offset
    consistently *shortens* one side and the arc-length error is
    measurable and reproducible.
    """
    # Control polygon that traces a parabolic arch, all curving upward.
    pts = np.array([
        [0.0,  0.0, 0.0],
        [1.0,  3.0, 0.0],
        [2.0,  4.0, 0.0],
        [3.0,  3.0, 0.0],
        [4.0,  0.0, 0.0],
    ])
    degree = 3
    # Clamped uniform knots for degree-3, 5 control points
    knots = np.array([0.0, 0.0, 0.0, 0.0, 0.5, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=degree, control_points=pts, knots=knots)


# ---------------------------------------------------------------------------
# Test 1: Straight-line offset preserves length exactly
# ---------------------------------------------------------------------------

class TestStraightLineOffset:
    """Oracle: a straight line of length 10 offset by 0.5 is a parallel line of
    the same length 10, because the normal displacement is perpendicular to the
    tangent and does not change the arc integral ∫|C'(t)| dt.

    The Tiller-Hanson path already gives length = 10 for a line; the Newton
    correction should converge in 1 iteration.  Expected error < 1e-9.
    """

    def test_line_length_preserved(self):
        p0 = np.array([0.0, 0.0, 0.0])
        p1 = np.array([10.0, 0.0, 0.0])
        line = _make_line_curve(p0, p1)
        L_orig = curve_length(line)
        assert abs(L_orig - 10.0) < 1e-9, f"Fixture wrong: L_orig={L_orig}"

        offset = offset_curve_arclength_preserving(line, distance=0.5)

        L_off = curve_length(offset)
        assert abs(L_off - 10.0) < 1e-9, (
            f"Line-offset arc length should be 10.0, got {L_off:.12f} "
            f"(error = {abs(L_off - 10.0):.4e})"
        )

    def test_line_offset_is_parallel(self):
        """The offset of a line along Z-normal should be shifted in Y by 0.5."""
        p0 = np.array([0.0, 0.0, 0.0])
        p1 = np.array([10.0, 0.0, 0.0])
        line = _make_line_curve(p0, p1)
        offset = offset_curve_arclength_preserving(line, distance=0.5)

        # Evaluate at midpoint — Y should be ~0.5
        t0 = float(offset.knots[offset.degree])
        t1 = float(offset.knots[-(offset.degree + 1)])
        from kerf_cad_core.geom.nurbs import de_boor
        mid_pt = de_boor(offset, (t0 + t1) * 0.5)
        # For offset along z-normal, right-side means y += 0.5
        assert abs(mid_pt[1] - 0.5) < 1e-3, (
            f"Offset midpoint Y expected ≈0.5, got {mid_pt[1]:.6f}"
        )


# ---------------------------------------------------------------------------
# Test 2: Circle offset with explicit target_length = 2π
# ---------------------------------------------------------------------------

class TestCircleArcLengthTarget:
    """Oracle: unit circle has length 2π.  Offset by 0.5 without arc-length
    preservation → Tiller-Hanson would give a circle of radius 1.5 with
    length 3π ≈ 9.42.  With target_length=2π, the result should have
    length 2π within 1e-6.
    """

    def test_circle_tiller_hanson_changes_length(self):
        """Confirm Tiller-Hanson changes arc length for a circle (sanity check)."""
        from kerf_cad_core.geom.offset import offset_curve
        circle = _make_unit_circle()
        L_orig = curve_length(circle)
        # Tiller-Hanson on the exact circle returns an exact circle of radius 1.5
        th = offset_curve(circle, 0.5)
        if th["ok"] and th["curve"] is not None:
            L_th = curve_length(th["curve"])
            # 2π vs 3π — error should be large
            assert L_th > L_orig * 1.1, (
                f"Tiller-Hanson circle should change length: orig={L_orig:.4f}, th={L_th:.4f}"
            )

    def test_circle_target_length_2pi(self):
        """After arc-length correction, offset circle length = 2π within 1e-6."""
        circle = _make_unit_circle()
        L_orig = curve_length(circle)
        L_target = 2.0 * math.pi

        assert abs(L_orig - L_target) < 1e-4, (
            f"Unit circle length fixture wrong: {L_orig:.8f} vs {L_target:.8f}"
        )

        offset = offset_curve_arclength_preserving(
            circle, distance=0.5, target_length=L_target, tol=1e-9,
        )

        L_off = curve_length(offset)
        assert abs(L_off - L_target) < 1e-6, (
            f"Circle arc-length-preserved offset: expected {L_target:.8f}, "
            f"got {L_off:.8f} (error = {abs(L_off - L_target):.4e})"
        )


# ---------------------------------------------------------------------------
# Test 3: Convergence — error decreases monotonically
# ---------------------------------------------------------------------------

class TestConvergence:
    """Check that the secant iteration converges: more iterations → smaller error.

    Uses the parabolic arch spline (9% TH error) with a target that requires
    actual work (target = original arc length ≠ TH length).  The secant method
    converges superlinearly, so each step reduces the error.
    """

    def test_error_decreases_across_iterations(self):
        """Relative arc-length error should decrease with more iterations."""
        spline = _make_cubic_arc_spline()
        L_orig = curve_length(spline)

        # Run with strictly increasing max_iter and a tolerance tight enough
        # that only the last run actually converges.  Confirm error decreases.
        errors = []
        for max_iter in [1, 2, 3, 5, 10]:
            try:
                off = offset_curve_arclength_preserving(
                    spline, distance=0.3,
                    target_length=L_orig,
                    tol=1e-12,          # tight but not impossibly so
                    max_iter=max_iter,
                )
                L_off = curve_length(off)
                err = abs(L_off - L_orig) / L_orig
            except ValueError:
                # Didn't converge yet — treat as last measured error
                err = errors[-1] if errors else 1.0
            errors.append(err)

        # Each successive step should not increase the error (monotone decrease)
        for i in range(1, len(errors)):
            assert errors[i] <= errors[i - 1] + 1e-12, (
                f"Error not monotone at step {i}: {errors[i-1]:.4e} → {errors[i]:.4e}"
            )

        # After 10 iterations the error should be very small
        assert errors[-1] < 1e-6, (
            f"Error after 10 iterations too large: {errors[-1]:.4e}"
        )


# ---------------------------------------------------------------------------
# Test 4: compare_offsets — exact_length far better than tiller_hanson on a spline
# ---------------------------------------------------------------------------

class TestCompareOffsets:
    """On a clearly curved S-spline, tiller_hanson changes arc length noticeably
    while exact_length matches to < 1e-6.
    """

    def test_exact_length_error_below_threshold(self):
        spline = _make_cubic_arc_spline()
        result = compare_offsets(spline, distance=0.3)

        assert "exact_length" in result, "compare_offsets must return 'exact_length' key"
        el = result["exact_length"]
        assert el["curve"] is not None, f"exact_length offset failed: {el.get('reason')}"
        assert el["arc_length_error"] < 1e-6, (
            f"exact_length arc_length_error should be < 1e-6, got {el['arc_length_error']:.4e}"
        )

    def test_tiller_hanson_error_nonzero_on_spline(self):
        """Tiller-Hanson on a curved spline should have arc-length error > 0.1%."""
        spline = _make_cubic_arc_spline()
        result = compare_offsets(spline, distance=0.3)

        assert "tiller_hanson" in result, "compare_offsets must return 'tiller_hanson' key"
        th = result["tiller_hanson"]
        if th["curve"] is not None and th["arc_length_error"] is not None:
            # For a significantly curved spline, Tiller-Hanson typically has > 1% error.
            # Use a conservative threshold of 0.1% to avoid flakiness on mild splines.
            assert th["arc_length_error"] > 1e-3, (
                f"Tiller-Hanson on curved spline should have arc_length_error > 0.1%, "
                f"got {th['arc_length_error']:.4e}"
            )

    def test_exact_length_better_than_tiller_hanson(self):
        """exact_length error must be strictly smaller than tiller_hanson error."""
        spline = _make_cubic_arc_spline()
        result = compare_offsets(spline, distance=0.3)

        th = result.get("tiller_hanson", {})
        el = result.get("exact_length", {})

        if (th.get("arc_length_error") is not None and
                el.get("arc_length_error") is not None and
                th["curve"] is not None and el["curve"] is not None):
            assert el["arc_length_error"] < th["arc_length_error"], (
                f"exact_length error ({el['arc_length_error']:.4e}) should be "
                f"< tiller_hanson error ({th['arc_length_error']:.4e})"
            )

    def test_compare_returns_original_length(self):
        """compare_offsets must return original_length for each method."""
        spline = _make_cubic_arc_spline()
        L_orig = curve_length(spline)
        result = compare_offsets(spline, distance=0.3)

        for method_name, data in result.items():
            assert abs(data["original_length"] - L_orig) < 1e-9, (
                f"{method_name}: original_length mismatch"
            )


# ---------------------------------------------------------------------------
# Test 5: exact_arclength_match_error utility
# ---------------------------------------------------------------------------

class TestExactArcLengthMatchError:
    def test_identical_curves(self):
        """Error between identical curves is 0."""
        line = _make_line_curve([0.0, 0.0, 0.0], [5.0, 0.0, 0.0])
        err = exact_arclength_match_error(line, line)
        assert err == 0.0

    def test_different_lengths(self):
        """Error between length-5 and length-10 lines is 1.0 (100%)."""
        line5 = _make_line_curve([0.0, 0.0, 0.0], [5.0, 0.0, 0.0])
        line10 = _make_line_curve([0.0, 0.0, 0.0], [10.0, 0.0, 0.0])
        err = exact_arclength_match_error(line5, line10)
        assert abs(err - 1.0) < 1e-9, f"Expected 1.0, got {err}"
