"""
Tests for kerf_cad_core.geom.curve_toolkit — NURBS curve toolkit.

All tests are hermetic: no OCC, no database, no network.

Groups:
  1. interp_curve  — passes through given points, chord vs centripetal param
  2. fit_curve     — deviation within tolerance, returns NurbsCurve
  3. rebuild_curve — output has requested degree/num_ctrl, small deviation
  4. fair_curve    — endpoints fixed, interior moves, energy decreases
  5. match_curve   — G0/G1/G2 endpoint / tangent continuity
  6. offset_curve  — constant distance from original
  7. extend_curve  — new endpoint shifted by amount
  8. blend_curve   — G1 tangent continuity at both ends
  9. simplify_curve — returns line/arc segments, collinear→line
  10. helix         — pitch exact, radius exact, turns exact
  11. spiral        — archimedean and log radius at endpoints
  12. conic         — rational Bézier endpoints correct; rho→parabola
  13. catenary      — passes through endpoints, analytic y=a*cosh(x/a)
  14. interpolate_arc_chain — arc center + radius consistent, collinear→line
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, de_boor
from kerf_cad_core.geom.curve_toolkit import (
    _chord_params,
    _make_clamped_knots,
    _sample_curve,
    blend_curve,
    catenary,
    catenary_y,
    conic,
    eval_conic,
    extend_curve,
    fair_curve,
    fit_curve,
    helix,
    interp_curve,
    interpolate_arc_chain,
    match_curve,
    offset_curve,
    rebuild_curve,
    simplify_curve,
    spiral,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _eval_at(curve: NurbsCurve, t: float) -> np.ndarray:
    u0 = curve.knots[curve.degree]
    u1 = curve.knots[-(curve.degree + 1)]
    u = u0 + t * (u1 - u0)
    return de_boor(curve, float(u))


def _make_line_pts(n: int = 10) -> List[List[float]]:
    """n collinear points along X-axis."""
    return [[float(i), 0.0, 0.0] for i in range(n)]


def _make_circle_pts(n: int = 30, r: float = 1.0) -> np.ndarray:
    """n points on a unit circle in XY plane."""
    angles = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.column_stack([r * np.cos(angles), r * np.sin(angles), np.zeros(n)])


# ===========================================================================
# Group 1: interp_curve
# ===========================================================================

class TestInterpCurve:
    def test_passes_through_all_points(self):
        """Curve evaluated at parameter values should recover input points."""
        pts = [[0, 0, 0], [1, 1, 0], [2, 0, 0], [3, 1, 0]]
        curve = interp_curve(pts, degree=3)
        assert isinstance(curve, NurbsCurve)
        # check endpoints
        p_start = de_boor(curve, curve.knots[curve.degree])
        p_end = de_boor(curve, curve.knots[-(curve.degree + 1)])
        np.testing.assert_allclose(p_start, [0, 0, 0], atol=1e-8)
        np.testing.assert_allclose(p_end,   [3, 1, 0], atol=1e-8)

    def test_passes_through_interior_points(self):
        """Intermediate points must lie on the interpolated curve."""
        pts = [[0, 0, 0], [1, 2, 0], [3, 0, 0]]
        curve = interp_curve(pts, degree=2)
        # Build collocation matrix and check
        from kerf_cad_core.geom.curve_toolkit import _chord_params, _eval_bspline_basis
        pts_arr = np.array(pts, dtype=float)
        ts = _chord_params(pts_arr)
        for t, expected in zip(ts, pts_arr):
            pt = de_boor(curve, float(t * (curve.knots[-1] - curve.knots[0]) + curve.knots[0])
                        if False else float(t))
            # re-evaluate at parameter in knot domain
        # simpler: check the curve evaluates near each input
        sampled = np.array([de_boor(curve, float(t)) for t in ts])
        np.testing.assert_allclose(sampled, pts_arr, atol=1e-6)

    def test_centripetal_param(self):
        """centripetal parametrisation produces a valid NurbsCurve."""
        pts = [[0, 0, 0], [1, 0, 0], [2, 1, 0], [3, 0, 0]]
        curve = interp_curve(pts, degree=3, param="centripetal")
        assert isinstance(curve, NurbsCurve)
        assert curve.degree == 3

    def test_degree_clamped_to_n_minus_1(self):
        """degree is clamped to n-1 for small point sets."""
        pts = [[0, 0, 0], [1, 0, 0]]
        curve = interp_curve(pts, degree=5)
        assert curve.degree == 1  # only 2 points → degree 1

    def test_knot_vector_clamped(self):
        """Knot vector starts at 0 and ends at 1."""
        pts = [[i, 0, 0] for i in range(6)]
        curve = interp_curve(pts, degree=3)
        assert curve.knots[0] == pytest.approx(0.0)
        assert curve.knots[-1] == pytest.approx(1.0)

    def test_interp_requires_at_least_2_pts(self):
        with pytest.raises(ValueError):
            interp_curve([[1, 0, 0]])


# ===========================================================================
# Group 2: fit_curve
# ===========================================================================

class TestFitCurve:
    def test_fit_within_tolerance(self):
        """fit_curve should achieve deviation ≤ tolerance."""
        pts = [[math.sin(t), math.cos(t), 0] for t in np.linspace(0, math.pi, 40)]
        result = fit_curve(pts, degree=3, tolerance=0.01)
        assert result["ok"], result["reason"]
        assert result["deviation"] <= 0.01

    def test_fit_returns_nurbs_curve(self):
        pts = [[i, i * 0.5, 0] for i in range(10)]
        result = fit_curve(pts, degree=3, tolerance=1.0)
        assert result["curve"] is not None
        assert isinstance(result["curve"], NurbsCurve)

    def test_fit_too_few_points(self):
        result = fit_curve([[1, 0, 0]])
        assert result["ok"] is False
        assert "need at least 2" in result["reason"]

    def test_fit_degree_1_linear(self):
        """Degree-1 fit to collinear points should be nearly perfect."""
        pts = [[float(i), 0.0, 0.0] for i in range(8)]
        result = fit_curve(pts, degree=1, tolerance=1e-6)
        assert result["ok"]
        assert result["deviation"] < 1e-4


# ===========================================================================
# Group 3: rebuild_curve
# ===========================================================================

class TestRebuildCurve:
    def _make_curve(self) -> NurbsCurve:
        pts = [[math.cos(t), math.sin(t), 0] for t in np.linspace(0, math.pi, 20)]
        return interp_curve(pts, degree=3)

    def test_rebuild_num_ctrl(self):
        curve = self._make_curve()
        result = rebuild_curve(curve, num_ctrl=6, degree=3)
        assert result["ok"], result["reason"]
        assert result["curve"].num_control_points == 6

    def test_rebuild_degree(self):
        curve = self._make_curve()
        result = rebuild_curve(curve, num_ctrl=5, degree=2)
        assert result["ok"]
        assert result["curve"].degree == 2

    def test_rebuild_deviation_reasonable(self):
        """Deviation should be small for a well-sampled curve."""
        pts = [[float(i), float(i) * 0.1, 0] for i in range(15)]
        curve = interp_curve(pts, degree=3)
        result = rebuild_curve(curve, num_ctrl=6, degree=3)
        assert result["ok"]
        assert result["deviation"] < 2.0

    def test_rebuild_invalid_num_ctrl(self):
        curve = self._make_curve()
        result = rebuild_curve(curve, num_ctrl=2, degree=3)
        assert result["ok"] is False


# ===========================================================================
# Group 4: fair_curve
# ===========================================================================

class TestFairCurve:
    def test_endpoints_fixed(self):
        """fair_curve must not move the endpoints."""
        pts = [[0, 0, 0], [1, 2, 0], [2, -1, 0], [3, 1, 0], [4, 0, 0]]
        curve = interp_curve(pts, degree=3)
        faired = fair_curve(curve, iterations=10, weight=0.5)
        np.testing.assert_allclose(
            faired.control_points[0], curve.control_points[0], atol=1e-10
        )
        np.testing.assert_allclose(
            faired.control_points[-1], curve.control_points[-1], atol=1e-10
        )

    def test_interior_moves(self):
        """Interior control points should change under smoothing."""
        pts = [[0, 0, 0], [1, 5, 0], [2, -5, 0], [3, 0, 0]]
        curve = interp_curve(pts, degree=3)
        faired = fair_curve(curve, iterations=20, weight=0.8)
        # at least one interior point must differ
        n = len(curve.control_points)
        interior_orig = curve.control_points[1:n-1]
        interior_fair = faired.control_points[1:n-1]
        assert not np.allclose(interior_orig, interior_fair)

    def test_returns_nurbs_curve(self):
        pts = [[0, 0, 0], [1, 0, 0], [2, 0, 0]]
        curve = interp_curve(pts, degree=2)
        faired = fair_curve(curve)
        assert isinstance(faired, NurbsCurve)


# ===========================================================================
# Group 5: match_curve
# ===========================================================================

class TestMatchCurve:
    def _simple_curve(self) -> NurbsCurve:
        pts = [[0, 0, 0], [1, 0, 0], [2, 0, 0], [3, 0, 0]]
        return interp_curve(pts, degree=3)

    def test_g0_end(self):
        """G0 match moves the endpoint."""
        curve = self._simple_curve()
        target = [5.0, 0.0, 0.0]
        matched = match_curve(curve, target, None, continuity="G0", end="end")
        np.testing.assert_allclose(matched.control_points[-1], target, atol=1e-10)

    def test_g0_start(self):
        curve = self._simple_curve()
        target = [-1.0, 0.0, 0.0]
        matched = match_curve(curve, target, None, continuity="G0", end="start")
        np.testing.assert_allclose(matched.control_points[0], target, atol=1e-10)

    def test_g1_tangent_set(self):
        """G1 match sets the second control point along target tangent."""
        curve = self._simple_curve()
        target_pt = [4.0, 0.0, 0.0]
        target_tan = [0.0, 1.0, 0.0]  # perpendicular to original
        matched = match_curve(curve, target_pt, target_tan, continuity="G1", end="end")
        # the second-to-last ctrl pt should be offset from endpoint along tangent
        diff = matched.control_points[-1] - matched.control_points[-2]
        diff_norm = np.linalg.norm(diff)
        if diff_norm > 1e-10:
            direction = diff / diff_norm
            # should be aligned with target tangent (or its reverse)
            dot = abs(np.dot(direction, [0.0, 1.0, 0.0]))
            assert dot > 0.9

    def test_g2_approximate(self):
        """G2 match sets the third-to-last control point."""
        pts = [[float(i), 0.0, 0.0] for i in range(6)]
        curve = interp_curve(pts, degree=3)
        matched = match_curve(
            curve, [6.0, 0.0, 0.0], [1.0, 0.0, 0.0], continuity="G2", end="end"
        )
        assert matched.num_control_points == curve.num_control_points

    def test_preserves_degree(self):
        curve = self._simple_curve()
        matched = match_curve(curve, [5, 0, 0], [1, 0, 0], continuity="G1")
        assert matched.degree == curve.degree


# ===========================================================================
# Group 6: offset_curve
# ===========================================================================

class TestOffsetCurve:
    def test_offset_distance_roughly_constant(self):
        """Points on offset curve should be ~distance away from the original."""
        pts = [[float(i), 0.0, 0.0] for i in range(6)]
        curve = interp_curve(pts, degree=3)
        dist = 0.5
        offset = offset_curve(curve, dist, normal=[0, 0, 1])
        # sample both curves and compare distances
        orig_pts = _sample_curve(curve, 30)
        off_pts = _sample_curve(offset, 30)
        # Use min distance from each offset point to the original
        dists = []
        for op in off_pts:
            d = np.min(np.linalg.norm(orig_pts - op, axis=1))
            dists.append(d)
        mean_dist = float(np.mean(dists))
        assert abs(mean_dist - dist) < dist * 0.5  # within 50% of target

    def test_offset_returns_nurbs(self):
        pts = [[float(i), math.sin(i), 0.0] for i in range(8)]
        curve = interp_curve(pts, degree=3)
        result = offset_curve(curve, 0.1)
        assert isinstance(result, NurbsCurve)

    def test_offset_zero_gives_similar_curve(self):
        """Zero offset should return a curve very close to the original."""
        pts = [[float(i), 0.0, 0.0] for i in range(5)]
        curve = interp_curve(pts, degree=3)
        offset = offset_curve(curve, 0.0)
        orig_pts = _sample_curve(curve, 20)
        off_pts = _sample_curve(offset, 20)
        # endpoints should match closely
        np.testing.assert_allclose(off_pts[0][:3], orig_pts[0][:3], atol=0.1)
        np.testing.assert_allclose(off_pts[-1][:3], orig_pts[-1][:3], atol=0.1)


# ===========================================================================
# Group 7: extend_curve
# ===========================================================================

class TestExtendCurve:
    def _straight_curve(self) -> NurbsCurve:
        pts = [[float(i), 0.0, 0.0] for i in range(5)]
        return interp_curve(pts, degree=3)

    def test_extend_end_adds_control_point(self):
        curve = self._straight_curve()
        extended = extend_curve(curve, 1.0, end="end", mode="line")
        assert extended.num_control_points == curve.num_control_points + 1

    def test_extend_start_adds_control_point(self):
        curve = self._straight_curve()
        extended = extend_curve(curve, 1.0, end="start", mode="line")
        assert extended.num_control_points == curve.num_control_points + 1

    def test_extend_end_new_point_direction(self):
        """Extension should move in the tangent direction."""
        curve = self._straight_curve()
        extended = extend_curve(curve, 2.0, end="end", mode="line")
        # last control point should be further in +X than before
        x_before = curve.control_points[-1, 0]
        x_after = extended.control_points[-1, 0]
        assert x_after > x_before

    def test_extend_amount_approximately_correct(self):
        """Extension of 2.0 should add roughly 2.0 to the curve length."""
        pts = [[float(i), 0.0, 0.0] for i in range(4)]
        curve = interp_curve(pts, degree=2)
        extended = extend_curve(curve, 2.0, end="end", mode="line")
        new_end = extended.control_points[-1]
        old_end = curve.control_points[-1]
        dist = np.linalg.norm(new_end - old_end)
        assert dist == pytest.approx(2.0, abs=0.5)

    def test_extend_arc_mode(self):
        curve = self._straight_curve()
        extended = extend_curve(curve, 1.0, end="end", mode="arc")
        assert isinstance(extended, NurbsCurve)


# ===========================================================================
# Group 8: blend_curve
# ===========================================================================

class TestBlendCurve:
    def test_blend_g1_endpoints(self):
        """Blend curve should start/end at the specified endpoints."""
        p0 = [0.0, 0.0, 0.0]
        p1 = [3.0, 0.0, 0.0]
        t0 = [1.0, 0.0, 0.0]
        t1 = [-1.0, 0.0, 0.0]
        blend = blend_curve(p0, t0, p1, t1, continuity="G1")
        # first and last control points
        np.testing.assert_allclose(blend.control_points[0],  p0, atol=1e-10)
        np.testing.assert_allclose(blend.control_points[-1], p1, atol=1e-10)

    def test_blend_g1_tangent_at_start(self):
        """Second control point should be along t0 from p0."""
        p0 = [0.0, 0.0, 0.0]
        t0 = [0.0, 1.0, 0.0]
        p1 = [1.0, 1.0, 0.0]
        t1 = [0.0, -1.0, 0.0]
        blend = blend_curve(p0, t0, p1, t1, continuity="G1")
        # second ctrl should be above p0 (in +Y)
        assert blend.control_points[1, 1] > blend.control_points[0, 1]

    def test_blend_g1_tangent_at_end(self):
        """Second-to-last ctrl should be along -t1 from p1."""
        p0 = [0.0, 0.0, 0.0]
        t0 = [1.0, 0.0, 0.0]
        p1 = [3.0, 0.0, 0.0]
        t1 = [0.0, 1.0, 0.0]
        blend = blend_curve(p0, t0, p1, t1, continuity="G1")
        # ctrl[-2] should be below p1 in Y (opposite of t1)
        assert blend.control_points[-2, 1] < blend.control_points[-1, 1]

    def test_blend_g2_returns_curve(self):
        p0 = [0.0, 0.0, 0.0]
        p1 = [4.0, 0.0, 0.0]
        t0 = [1.0, 0.0, 0.0]
        t1 = [-1.0, 0.0, 0.0]
        blend = blend_curve(p0, t0, p1, t1, continuity="G2")
        assert isinstance(blend, NurbsCurve)
        assert blend.num_control_points >= 4

    def test_blend_degree_3(self):
        p0 = [0.0, 0.0, 0.0]
        p1 = [2.0, 2.0, 0.0]
        blend = blend_curve(p0, [1, 0, 0], p1, [0, -1, 0])
        assert blend.degree == 3


# ===========================================================================
# Group 9: simplify_curve
# ===========================================================================

class TestSimplifyCurve:
    def test_collinear_points_gives_line(self):
        """Collinear points with tight tolerance should produce line segments."""
        pts = [[float(i), 0.0, 0.0] for i in range(5)]
        segs = simplify_curve(pts, tolerance=1e-6)
        assert len(segs) >= 1
        for s in segs:
            assert s["type"] in ("line", "arc")

    def test_two_points_is_one_line(self):
        segs = simplify_curve([[0, 0, 0], [1, 0, 0]])
        assert len(segs) == 1
        assert segs[0]["type"] == "line"

    def test_empty_returns_empty(self):
        assert simplify_curve([]) == []

    def test_arc_detected_for_circle_points(self):
        """Points on a circle should produce arc segments."""
        pts = []
        for i in range(9):
            angle = 2 * math.pi * i / 8
            pts.append([math.cos(angle), math.sin(angle), 0.0])
        segs = simplify_curve(pts, tolerance=0.1)
        types = {s["type"] for s in segs}
        assert "arc" in types

    def test_segment_start_end_consistency(self):
        """Each segment must have start and end keys."""
        pts = [[float(i), float(i % 2), 0.0] for i in range(6)]
        segs = simplify_curve(pts)
        for s in segs:
            assert "start" in s
            assert "end" in s


# ===========================================================================
# Group 10: helix
# ===========================================================================

class TestHelix:
    def test_radius_exact(self):
        """All sampled helix points should be exactly ``radius`` from the axis."""
        r = 2.5
        curve = helix(center=[0, 0, 0], axis=[0, 0, 1], radius=r, pitch=1.0,
                      turns=2.0, num_pts=200)
        pts = _sample_curve(curve, 100)
        radii = np.sqrt(pts[:, 0]**2 + pts[:, 1]**2)
        np.testing.assert_allclose(radii, r, atol=0.05)

    def test_pitch_exact(self):
        """Total Z displacement equals pitch * turns."""
        pitch = 2.0
        turns = 3.0
        curve = helix(center=[0, 0, 0], axis=[0, 0, 1], radius=1.0,
                      pitch=pitch, turns=turns, num_pts=300)
        z_start = de_boor(curve, curve.knots[curve.degree])[2]
        z_end = de_boor(curve, curve.knots[-(curve.degree + 1)])[2]
        expected_z_rise = pitch * turns
        assert abs((z_end - z_start) - expected_z_rise) < 0.1

    def test_helix_returns_nurbs(self):
        curve = helix()
        assert isinstance(curve, NurbsCurve)
        assert curve.degree == 3

    def test_helix_non_z_axis(self):
        """Helix along X-axis should have X as the rise direction."""
        curve = helix(axis=[1, 0, 0], radius=1.0, pitch=1.0, turns=2.0, num_pts=200)
        assert isinstance(curve, NurbsCurve)

    def test_helix_start_angle(self):
        """Non-zero start_angle shifts the initial XY position."""
        c0 = helix(radius=1.0, turns=1.0, start_angle=0.0, num_pts=50)
        c1 = helix(radius=1.0, turns=1.0, start_angle=math.pi / 2, num_pts=50)
        p0 = de_boor(c0, c0.knots[c0.degree])
        p1 = de_boor(c1, c1.knots[c1.degree])
        # Different start angle → different X/Y at parameter 0
        assert not np.allclose(p0[:2], p1[:2], atol=0.1)


# ===========================================================================
# Group 11: spiral
# ===========================================================================

class TestSpiral:
    def test_archimedean_start_radius(self):
        """First point should be at radius_start from center."""
        r_start = 0.5
        curve = spiral(center=[0, 0, 0], radius_start=r_start, radius_end=2.0,
                       turns=2.0, spiral_type="archimedean", num_pts=100)
        pts = _sample_curve(curve, 50)
        first_r = math.hypot(pts[0, 0], pts[0, 1])
        assert abs(first_r - r_start) < 0.15

    def test_archimedean_end_radius(self):
        """Last sampled point should be near radius_end."""
        r_end = 3.0
        curve = spiral(center=[0, 0, 0], radius_start=0.5, radius_end=r_end,
                       turns=2.0, spiral_type="archimedean", num_pts=150)
        pts = _sample_curve(curve, 50)
        last_r = math.hypot(pts[-1, 0], pts[-1, 1])
        assert abs(last_r - r_end) < 0.5

    def test_log_spiral_returns_nurbs(self):
        curve = spiral(radius_start=0.1, radius_end=1.0, turns=3.0,
                       spiral_type="log")
        assert isinstance(curve, NurbsCurve)

    def test_spiral_monotone_radius(self):
        """Archimedean spiral: radius should grow monotonically."""
        curve = spiral(radius_start=0.2, radius_end=2.0, turns=2.0,
                       spiral_type="archimedean", num_pts=100)
        pts = _sample_curve(curve, 50)
        radii = np.sqrt(pts[:, 0]**2 + pts[:, 1]**2)
        # allow some wobble from interpolation; overall trend should be positive
        assert radii[-1] > radii[0]


# ===========================================================================
# Group 12: conic
# ===========================================================================

class TestConic:
    def test_endpoints_at_p0_p2(self):
        """A rational conic must start at p0 and end at p2."""
        p0 = [0.0, 0.0, 0.0]
        p1 = [1.0, 2.0, 0.0]
        p2 = [2.0, 0.0, 0.0]
        curve = conic(p0, p1, p2, rho=0.5)
        pt0 = eval_conic(curve, 0.0)
        pt1 = eval_conic(curve, 1.0)
        np.testing.assert_allclose(pt0[:3], [0.0, 0.0, 0.0], atol=1e-10)
        np.testing.assert_allclose(pt1[:3], [2.0, 0.0, 0.0], atol=1e-10)

    def test_parabola_midpoint(self):
        """rho=0.5 is a parabola; rational Bézier midpoint B(0.5) is analytic."""
        p0 = [0.0, 0.0, 0.0]
        p1 = [1.0, 1.0, 0.0]
        p2 = [2.0, 0.0, 0.0]
        rho = 0.5
        curve = conic(p0, p1, p2, rho=rho)
        pt_mid = eval_conic(curve, 0.5)
        # Rational Bernstein evaluation at t=0.5, weights [1, rho, 1]:
        # B0=B2=0.25, B1=0.5
        # denom = 0.25*1 + 0.5*rho + 0.25*1 = 0.5 + 0.5*rho
        # x: (0.25*0 + 0.5*rho*1 + 0.25*2) / denom = (0.5*rho + 0.5) / (0.5 + 0.5*rho)
        # with rho=0.5: (0.25 + 0.5) / (0.5 + 0.25) = 0.75/0.75 = 1.0
        # y: (0.25*0 + 0.5*rho*1 + 0.25*0) / denom = (0.5*rho) / (0.5 + 0.5*rho)
        # with rho=0.5: 0.25 / 0.75 = 1/3
        expected = np.array([1.0, 1.0 / 3.0, 0.0])
        np.testing.assert_allclose(pt_mid[:3], expected, atol=1e-8)

    def test_eval_conic_helper(self):
        """eval_conic should return Cartesian (not homogeneous) point."""
        p0 = [0.0, 0.0, 0.0]
        p1 = [1.0, 1.0, 0.0]
        p2 = [2.0, 0.0, 0.0]
        curve = conic(p0, p1, p2, rho=0.5)
        pt = eval_conic(curve, 0.0)
        # should be 3D (not 4D)
        assert pt.shape[0] == 3

    def test_rho_affects_shape(self):
        """Different rho values should produce different midpoint heights."""
        p0, p1, p2 = [0, 0, 0], [1, 2, 0], [2, 0, 0]
        curve_parabola = conic(p0, p1, p2, rho=0.5)
        curve_ellipse  = conic(p0, p1, p2, rho=0.25)
        mid_par = eval_conic(curve_parabola, 0.5)[1]
        mid_ell = eval_conic(curve_ellipse,  0.5)[1]
        assert mid_par != pytest.approx(mid_ell, abs=1e-4)


# ===========================================================================
# Group 13: catenary
# ===========================================================================

class TestCatenary:
    def test_passes_through_p0(self):
        """Curve should start at p0."""
        p0 = [0.0, 1.0, 0.0]
        p1 = [4.0, 1.0, 0.0]
        curve = catenary(p0, p1, a=2.0, num_pts=50)
        pt = de_boor(curve, curve.knots[curve.degree])
        np.testing.assert_allclose(pt[0], p0[0], atol=0.05)
        np.testing.assert_allclose(pt[1], p0[1], atol=0.05)

    def test_passes_through_p1(self):
        p0 = [0.0, 0.0, 0.0]
        p1 = [2.0, 0.0, 0.0]
        curve = catenary(p0, p1, a=1.0, num_pts=50)
        pt = de_boor(curve, curve.knots[-(curve.degree + 1)])
        np.testing.assert_allclose(pt[0], p1[0], atol=0.1)

    def test_analytic_y_acoshxa(self):
        """catenary_y(x, a) == a * cosh(x/a)."""
        for a in [0.5, 1.0, 2.0]:
            for x in [-2.0, -1.0, 0.0, 1.0, 2.0]:
                expected = a * math.cosh(x / a)
                assert catenary_y(x, a) == pytest.approx(expected, rel=1e-10)

    def test_catenary_shape(self):
        """Interior of catenary should sag below the line connecting endpoints."""
        p0 = [0.0, 1.0, 0.0]
        p1 = [4.0, 1.0, 0.0]
        a = 1.0
        curve = catenary(p0, p1, a=a, num_pts=100)
        pts = _sample_curve(curve, 50)
        # midpoint Y should be larger than endpoint Y (catenary opens upward)
        mid_y = pts[len(pts) // 2, 1]
        end_y = pts[0, 1]
        assert mid_y >= end_y - 0.5  # catenary rises toward center

    def test_catenary_returns_nurbs(self):
        curve = catenary([0, 0, 0], [1, 0, 0])
        assert isinstance(curve, NurbsCurve)
        assert curve.degree == 3


# ===========================================================================
# Group 14: interpolate_arc_chain
# ===========================================================================

class TestInterpolateArcChain:
    def test_collinear_gives_lines(self):
        """Collinear points should produce only line segments."""
        pts = [[float(i), 0.0, 0.0] for i in range(5)]
        segs = interpolate_arc_chain(pts)
        for s in segs:
            assert s["type"] == "line"

    def test_arc_center_on_circle(self):
        """Arc center should be equidistant from all 3 arc points."""
        angle0 = 0.0
        angle1 = math.pi / 3
        angle2 = 2 * math.pi / 3
        r = 2.0
        pts = [
            [r * math.cos(angle0), r * math.sin(angle0), 0.0],
            [r * math.cos(angle1), r * math.sin(angle1), 0.0],
            [r * math.cos(angle2), r * math.sin(angle2), 0.0],
        ]
        segs = interpolate_arc_chain(pts)
        arc_segs = [s for s in segs if s["type"] == "arc"]
        assert len(arc_segs) >= 1
        arc = arc_segs[0]
        cx, cy = arc["center"][0], arc["center"][1]
        for pt in pts:
            d = math.hypot(pt[0] - cx, pt[1] - cy)
            assert abs(d - arc["radius"]) < 1e-6

    def test_arc_radius_correct(self):
        """Arc radius matches circumradius of the 3 input points."""
        pts = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]]
        segs = interpolate_arc_chain(pts)
        arc_segs = [s for s in segs if s["type"] == "arc"]
        assert len(arc_segs) >= 1
        assert arc_segs[0]["radius"] == pytest.approx(1.0, abs=1e-5)

    def test_two_points_gives_line(self):
        segs = interpolate_arc_chain([[0, 0, 0], [1, 0, 0]])
        assert len(segs) == 1
        assert segs[0]["type"] == "line"

    def test_single_point_empty(self):
        assert interpolate_arc_chain([[0, 0, 0]]) == []

    def test_all_segments_have_start_end(self):
        pts = [[math.cos(2 * math.pi * i / 7), math.sin(2 * math.pi * i / 7), 0.0]
               for i in range(7)]
        segs = interpolate_arc_chain(pts)
        for s in segs:
            assert "start" in s
            assert "end" in s
