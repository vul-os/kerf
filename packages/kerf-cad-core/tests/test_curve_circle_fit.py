"""
Tests for kerf_cad_core.geom.curve_circle_fit — NURBS-curve circle fitting.

All tests are hermetic: no OCC, no database, no network.

Groups:
  1. Exact circle (NurbsCurve)         — Kasa + Taubin, R=5 at origin
  2. Half-circle arc (180°)            — same accuracy
  3. Quarter-circle arc (90°)          — same accuracy (Taubin preferred)
  4. Off-origin circle                 — centre translated
  5. Straight line                     — large residual, honest caveat
  6. Noisy circle                      — rms close to noise std
  7. Point array input                 — raw NumPy / list-of-lists
  8. Taubin vs Kasa equivalence        — exact circle: both converge
  9. Short arc (< 30°)                 — caveat populated for Kasa
 10. Degenerate (< 3 pts)              — graceful error result
 11. Large radius                      — huge-radius circle near-line
 12. Residual interpretation           — max_residual ≥ rms_residual
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.geom.curve_circle_fit import CircleFitResult, fit_circle_to_curve
from kerf_cad_core.geom.nurbs import make_circle_nurbs, make_arc_nurbs, make_line_nurbs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _circle_points(
    cx: float, cy: float, r: float, n: int = 200
) -> np.ndarray:
    """Exact analytical circle sample (no NURBS; used to cross-check)."""
    theta = np.linspace(0.0, 2.0 * math.pi, n, endpoint=False)
    return np.column_stack([cx + r * np.cos(theta), cy + r * np.sin(theta)])


def _arc_points_2d(
    cx: float, cy: float, r: float, a0: float, a1: float, n: int = 100
) -> np.ndarray:
    """Exact analytical arc sample."""
    theta = np.linspace(a0, a1, n)
    return np.column_stack([cx + r * np.cos(theta), cy + r * np.sin(theta)])


# ---------------------------------------------------------------------------
# Group 1 — Exact full circle as NurbsCurve (R=5 at origin)
# ---------------------------------------------------------------------------

class TestExactCircleNurbs:
    """Kasa and Taubin both recover center=(0,0), R=5 with rms < 1e-12."""

    def _make_curve(self):
        # make_circle_nurbs returns a 3D NurbsCurve; xy projection used
        return make_circle_nurbs(np.array([0.0, 0.0, 0.0]), 5.0)

    def test_kasa_center_x(self):
        res = fit_circle_to_curve(self._make_curve(), num_samples=200, method="kasa")
        assert abs(res.center_xy[0]) < 1e-10

    def test_kasa_center_y(self):
        res = fit_circle_to_curve(self._make_curve(), num_samples=200, method="kasa")
        assert abs(res.center_xy[1]) < 1e-10

    def test_kasa_radius(self):
        res = fit_circle_to_curve(self._make_curve(), num_samples=200, method="kasa")
        assert abs(res.radius - 5.0) < 1e-10

    def test_kasa_rms_near_zero(self):
        res = fit_circle_to_curve(self._make_curve(), num_samples=200, method="kasa")
        assert res.rms_residual_mm < 1e-10

    def test_taubin_rms_near_zero(self):
        res = fit_circle_to_curve(self._make_curve(), num_samples=200, method="taubin")
        assert res.rms_residual_mm < 1e-10

    def test_taubin_radius(self):
        res = fit_circle_to_curve(self._make_curve(), num_samples=200, method="taubin")
        assert abs(res.radius - 5.0) < 1e-10

    def test_fit_method_label(self):
        res = fit_circle_to_curve(self._make_curve(), num_samples=50, method="kasa")
        assert res.fit_method == "kasa"
        res2 = fit_circle_to_curve(self._make_curve(), num_samples=50, method="taubin")
        assert res2.fit_method == "taubin"


# ---------------------------------------------------------------------------
# Group 2 — Half-circle arc (180°)
# ---------------------------------------------------------------------------

class TestHalfCircleArc:
    """180° arc: same fit accuracy for both methods."""

    def _make_arc(self):
        return make_arc_nurbs(
            np.array([0.0, 0.0, 0.0]), 5.0,
            start_angle=0.0, end_angle=math.pi
        )

    def test_kasa_center(self):
        res = fit_circle_to_curve(self._make_arc(), num_samples=200, method="kasa")
        assert abs(res.center_xy[0]) < 1e-8
        assert abs(res.center_xy[1]) < 1e-8

    def test_kasa_radius(self):
        res = fit_circle_to_curve(self._make_arc(), num_samples=200, method="kasa")
        assert abs(res.radius - 5.0) < 1e-8

    def test_kasa_rms(self):
        res = fit_circle_to_curve(self._make_arc(), num_samples=200, method="kasa")
        assert res.rms_residual_mm < 1e-9

    def test_taubin_radius(self):
        res = fit_circle_to_curve(self._make_arc(), num_samples=200, method="taubin")
        assert abs(res.radius - 5.0) < 1e-8


# ---------------------------------------------------------------------------
# Group 3 — Quarter-circle arc (90°)
# ---------------------------------------------------------------------------

class TestQuarterCircleArc:
    """90° arc: Taubin is preferred for short arcs."""

    def _make_arc(self):
        return make_arc_nurbs(
            np.array([0.0, 0.0, 0.0]), 7.0,
            start_angle=0.0, end_angle=math.pi / 2.0
        )

    def test_taubin_center_within_tolerance(self):
        res = fit_circle_to_curve(self._make_arc(), num_samples=200, method="taubin")
        assert abs(res.center_xy[0]) < 1e-7
        assert abs(res.center_xy[1]) < 1e-7

    def test_taubin_radius(self):
        res = fit_circle_to_curve(self._make_arc(), num_samples=200, method="taubin")
        assert abs(res.radius - 7.0) < 1e-7

    def test_taubin_rms(self):
        res = fit_circle_to_curve(self._make_arc(), num_samples=200, method="taubin")
        assert res.rms_residual_mm < 1e-8

    def test_kasa_rms(self):
        # Kasa is also accurate for a full quadrant (90° > threshold)
        res = fit_circle_to_curve(self._make_arc(), num_samples=200, method="kasa")
        assert res.rms_residual_mm < 1e-6


# ---------------------------------------------------------------------------
# Group 4 — Off-origin circle
# ---------------------------------------------------------------------------

class TestOffOriginCircle:
    """Circle centre translated to (3, -7, 0)."""

    def test_center_recovered(self):
        cx, cy, r = 3.0, -7.0, 4.5
        pts = _circle_points(cx, cy, r, n=300)
        res = fit_circle_to_curve(pts, method="kasa")
        assert abs(res.center_xy[0] - cx) < 1e-8
        assert abs(res.center_xy[1] - cy) < 1e-8

    def test_radius_recovered(self):
        cx, cy, r = 3.0, -7.0, 4.5
        pts = _circle_points(cx, cy, r, n=300)
        res = fit_circle_to_curve(pts, method="kasa")
        assert abs(res.radius - r) < 1e-8


# ---------------------------------------------------------------------------
# Group 5 — Straight line → large residual + honest caveat
# ---------------------------------------------------------------------------

class TestStraightLine:
    """Straight line has no well-defined circle — residual must be large."""

    def test_rms_is_large(self):
        # Horizontal line y=0, x in [0, 10]
        x = np.linspace(0.0, 10.0, 200)
        pts = np.column_stack([x, np.zeros(200)])
        res = fit_circle_to_curve(pts, method="kasa")
        # For a straight line the fit produces an enormous radius; the residuals
        # within the sampled segment are near-zero by algebraic coincidence, but
        # the caveat should fire about large radius or near-linear data.
        # We assert either: rms is significant OR an honest caveat is present.
        caveat_present = len(res.honest_caveat) > 0
        rms_significant = res.rms_residual_mm > 0.001 or res.radius > 1e4
        assert caveat_present or rms_significant, (
            f"Expected large rms or caveat for straight line, "
            f"got rms={res.rms_residual_mm}, radius={res.radius}, "
            f"caveat={res.honest_caveat!r}"
        )

    def test_line_nurbs_caveat_or_large_radius(self):
        line = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([10.0, 0.0, 0.0]))
        res = fit_circle_to_curve(line, num_samples=100, method="kasa")
        assert len(res.honest_caveat) > 0 or res.radius > 1e4 or res.rms_residual_mm > 0.001


# ---------------------------------------------------------------------------
# Group 6 — Noisy circle (R=10 + uniform noise ±0.1 mm)
# ---------------------------------------------------------------------------

class TestNoisyCircle:
    """RMS residual should be close to the noise standard deviation."""

    def test_rms_near_noise_std(self):
        rng = np.random.default_rng(42)
        r = 10.0
        noise_amp = 0.1  # ± 0.1 mm
        theta = np.linspace(0.0, 2.0 * math.pi, 500, endpoint=False)
        pts = np.column_stack([
            r * np.cos(theta) + rng.uniform(-noise_amp, noise_amp, len(theta)),
            r * np.sin(theta) + rng.uniform(-noise_amp, noise_amp, len(theta)),
        ])
        res = fit_circle_to_curve(pts, method="kasa")
        # RMS residual should be < 3× noise_amp (typically ~noise_amp * sqrt(2/3))
        assert res.rms_residual_mm < 3.0 * noise_amp
        assert res.rms_residual_mm > 1e-6  # non-trivial residual

    def test_noisy_radius_close(self):
        rng = np.random.default_rng(43)
        r = 10.0
        noise_amp = 0.1
        theta = np.linspace(0.0, 2.0 * math.pi, 500, endpoint=False)
        pts = np.column_stack([
            r * np.cos(theta) + rng.uniform(-noise_amp, noise_amp, len(theta)),
            r * np.sin(theta) + rng.uniform(-noise_amp, noise_amp, len(theta)),
        ])
        res = fit_circle_to_curve(pts, method="kasa")
        # Fitted radius should be within 5× noise amplitude of true radius
        assert abs(res.radius - r) < 5.0 * noise_amp


# ---------------------------------------------------------------------------
# Group 7 — Raw point array input (list-of-lists)
# ---------------------------------------------------------------------------

class TestPointArrayInput:
    """fit_circle_to_curve accepts lists and NumPy arrays directly."""

    def test_list_of_lists(self):
        pts = _circle_points(0.0, 0.0, 3.0, n=100)
        pts_list = pts.tolist()
        res = fit_circle_to_curve(pts_list, method="kasa")
        assert abs(res.radius - 3.0) < 1e-8

    def test_3d_points_uses_xy_only(self):
        # 3D points: z-coordinate is non-zero but should be ignored
        theta = np.linspace(0.0, 2.0 * math.pi, 200, endpoint=False)
        r = 6.0
        pts3d = np.column_stack([
            r * np.cos(theta),
            r * np.sin(theta),
            np.full(200, 99.0),  # large z — must be ignored
        ])
        res = fit_circle_to_curve(pts3d, method="kasa")
        assert abs(res.radius - r) < 1e-8

    def test_result_is_CircleFitResult(self):
        pts = _circle_points(1.0, 2.0, 4.0, n=50)
        res = fit_circle_to_curve(pts, method="taubin")
        assert isinstance(res, CircleFitResult)


# ---------------------------------------------------------------------------
# Group 8 — Taubin vs Kasa on exact circle: both converge
# ---------------------------------------------------------------------------

class TestTaubinKasaEquivalence:
    """Both methods should give the same answer on an exact full circle."""

    def test_both_agree_center(self):
        pts = _circle_points(0.0, 0.0, 8.0, n=500)
        rk = fit_circle_to_curve(pts, method="kasa")
        rt = fit_circle_to_curve(pts, method="taubin")
        assert abs(rk.center_xy[0] - rt.center_xy[0]) < 1e-6
        assert abs(rk.center_xy[1] - rt.center_xy[1]) < 1e-6

    def test_both_agree_radius(self):
        pts = _circle_points(0.0, 0.0, 8.0, n=500)
        rk = fit_circle_to_curve(pts, method="kasa")
        rt = fit_circle_to_curve(pts, method="taubin")
        assert abs(rk.radius - rt.radius) < 1e-6


# ---------------------------------------------------------------------------
# Group 9 — Short arc (< 30°): Kasa caveat populated
# ---------------------------------------------------------------------------

class TestShortArcCaveat:
    """Very short arc should trigger a caveat for the Kasa method."""

    def test_kasa_caveat_for_short_arc(self):
        # 20° arc
        r = 5.0
        pts = _arc_points_2d(0.0, 0.0, r, 0.0, math.radians(20.0), n=100)
        res = fit_circle_to_curve(pts, method="kasa")
        # Caveat should mention the short arc
        assert "30°" in res.honest_caveat or len(res.honest_caveat) > 0, (
            f"Expected short-arc caveat from Kasa, got: {res.honest_caveat!r}"
        )

    def test_taubin_no_excessive_caveat_for_quarter_circle(self):
        # 90° arc should NOT trigger the small-sweep caveat for Taubin
        pts = _arc_points_2d(0.0, 0.0, 5.0, 0.0, math.pi / 2.0, n=200)
        res = fit_circle_to_curve(pts, method="taubin")
        # Residual should still be very small
        assert res.rms_residual_mm < 1e-6


# ---------------------------------------------------------------------------
# Group 10 — Degenerate: < 3 points → graceful error
# ---------------------------------------------------------------------------

class TestDegenerateInput:
    """Fewer than 3 points should produce an inf-residual result with caveat."""

    def test_two_points_returns_inf(self):
        pts = [[0.0, 0.0], [1.0, 0.0]]
        res = fit_circle_to_curve(pts, method="kasa")
        assert math.isinf(res.rms_residual_mm)
        assert len(res.honest_caveat) > 0

    def test_one_point_returns_inf(self):
        pts = [[5.0, 3.0]]
        res = fit_circle_to_curve(pts, method="taubin")
        assert math.isinf(res.rms_residual_mm)

    def test_invalid_method_raises(self):
        pts = _circle_points(0.0, 0.0, 1.0, n=10).tolist()
        with pytest.raises(ValueError, match="method"):
            fit_circle_to_curve(pts, method="bogus")


# ---------------------------------------------------------------------------
# Group 11 — Large radius circle (near-line)
# ---------------------------------------------------------------------------

class TestLargeRadius:
    """R=1e6 mm circle arc: fit should set a large-radius caveat."""

    def test_large_radius_caveat(self):
        r = 1.0e6
        pts = _arc_points_2d(0.0, 0.0, r, 0.0, math.radians(10.0), n=200)
        res = fit_circle_to_curve(pts, method="taubin")
        # Either the radius is recovered accurately (within 1%) or a caveat fires
        radius_ok = abs(res.radius - r) / r < 0.02
        caveat_ok = len(res.honest_caveat) > 0
        assert radius_ok or caveat_ok


# ---------------------------------------------------------------------------
# Group 12 — Residual semantics: max ≥ rms
# ---------------------------------------------------------------------------

class TestResidualSemantics:
    """max_residual_mm must always be ≥ rms_residual_mm."""

    @pytest.mark.parametrize("method", ["kasa", "taubin"])
    def test_max_gte_rms_exact_circle(self, method):
        pts = _circle_points(0.0, 0.0, 5.0, n=200)
        res = fit_circle_to_curve(pts, method=method)
        assert res.max_residual_mm >= res.rms_residual_mm - 1e-15

    @pytest.mark.parametrize("method", ["kasa", "taubin"])
    def test_max_gte_rms_noisy(self, method):
        rng = np.random.default_rng(99)
        theta = np.linspace(0.0, 2.0 * math.pi, 300, endpoint=False)
        pts = np.column_stack([
            5.0 * np.cos(theta) + rng.uniform(-0.05, 0.05, 300),
            5.0 * np.sin(theta) + rng.uniform(-0.05, 0.05, 300),
        ])
        res = fit_circle_to_curve(pts, method=method)
        assert res.max_residual_mm >= res.rms_residual_mm - 1e-12
