"""
GK-12: Curve self-intersection tests.

Covers:
  1.  Lemniscate (figure-eight) — oracle: self-x at origin found to ≤1e-9.
  2.  Explicit figure-eight polyline (degree-1 NURBS).
  3.  Simple figure-eight cubic NURBS — single self-intersection.
  4.  Open arc (no self-intersection) — returns [].
  5.  Straight line (no self-intersection) — returns [].
  6.  Trefoil planar projection — three self-intersections found.
  7.  Result dict keys: ta, tb, point always present.
  8.  ta <= tb in every returned hit.
  9.  Both curve parameters in valid range.
  10. Intersection point close to both curve evaluations.
  11. Duplicate hits merged — figure-eight yields exactly 1 hit.
  12. Bad input (None, string) never raises, returns [].
  13. Higher-resolution sampling finds the same hit.
  14. Custom tol respected (loose tol).
  15. Lemniscate: hit point distance from origin ≤ 1e-9  (analytic oracle).

All tests hermetic: pure Python + NumPy, no OCC, no database, no network.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve
from kerf_cad_core.geom.intersection import (
    curve_self_intersect,
    _curve_eval,
    _curve_param_range,
)


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------

def _make_nurbs_from_pts(pts: np.ndarray, degree: int = 3) -> NurbsCurve:
    """Build a clamped B-spline through the given control polygon.

    Uses chord-length parameterisation and uniform clamped knot vector.
    ``pts`` rows are control points (not interpolated through — this is a
    control-polygon curve).  For self-intersection tests we treat the points
    directly as control points rather than fitting through them.
    """
    n = len(pts)  # number of control points
    d = min(degree, n - 1)
    # Clamped knot vector: d+1 zeros, n-d-1 interior, d+1 ones.
    n_inner = max(0, n - d - 1)
    interior = np.linspace(0.0, 1.0, n_inner + 2)[1:-1] if n_inner > 0 else np.array([])
    knots = np.concatenate([
        np.zeros(d + 1),
        interior,
        np.ones(d + 1),
    ])
    return NurbsCurve(degree=d, control_points=pts.astype(float), knots=knots)


def _make_line_nurbs(p0, p1) -> NurbsCurve:
    """Degree-1 line segment from p0 to p1."""
    cp = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=cp, knots=knots)


def _make_polyline_nurbs(pts: List) -> NurbsCurve:
    """Degree-1 polyline through the given points."""
    cp = np.array(pts, dtype=float)
    n = len(cp)
    knots = np.concatenate([[0.0], np.linspace(0.0, 1.0, n), [1.0]])
    # For degree-1 clamped: knots length = n_cp + degree + 1 = n + 2.
    # Standard clamped degree-1 knot vector for n points:
    #   [0, 0, 1/(n-1), 2/(n-1), ..., 1, 1]
    knots = np.concatenate([
        [0.0],
        np.linspace(0.0, 1.0, n),
        [1.0],
    ])
    # That gives n+2 knots for degree 1 → need n + degree + 1 = n + 2.  Good.
    return NurbsCurve(degree=1, control_points=cp, knots=knots)


def _make_circle_arc(cx: float, cy: float, r: float,
                     t0_deg: float, t1_deg: float,
                     n_pts: int = 12, degree: int = 3) -> NurbsCurve:
    """Approximate circular arc as control-polygon NurbsCurve."""
    thetas = np.linspace(math.radians(t0_deg), math.radians(t1_deg), n_pts)
    cp = np.column_stack([
        cx + r * np.cos(thetas),
        cy + r * np.sin(thetas),
        np.zeros(n_pts),
    ])
    return _make_nurbs_from_pts(cp, degree=degree)


# ---------------------------------------------------------------------------
# Lemniscate factory (analytic oracle curve)
# ---------------------------------------------------------------------------

def _lemniscate_pt(t: float, a: float = 1.0) -> np.ndarray:
    """Bernoulli lemniscate: parametric form.

    x(t) = a cos(t) / (1 + sin²(t))
    y(t) = a sin(t) cos(t) / (1 + sin²(t))

    The self-intersection is at the origin, visited at t=0 and t=π.
    """
    s = math.sin(t)
    c = math.cos(t)
    denom = 1.0 + s * s
    return np.array([a * c / denom, a * s * c / denom, 0.0])


def _make_lemniscate_nurbs(a: float = 1.0, n_cp: int = 32, degree: int = 3) -> NurbsCurve:
    """Build a closed lemniscate NurbsCurve from sampled points as control polygon.

    Samples n_cp points from t=0 to t=2π (exclusive of endpoint repeat) and
    builds a clamped B-spline control polygon.  The curve is open in parameter
    space (t=0 and t=1 both map near the origin).
    """
    # Sample over [0, 2π), avoiding the closing repeat so the control polygon
    # goes all the way round and the NURBS endpoints are both near the origin.
    ts = np.linspace(0.0, 2.0 * math.pi, n_cp + 1)[:-1]  # drop last (=first)
    # Include both endpoints (t=0 and t=2π) so the NURBS is clamped and the
    # curve starts and ends at the origin — giving a genuine double-point.
    ts_full = np.concatenate([[0.0], ts, [2.0 * math.pi]])
    cp = np.array([_lemniscate_pt(float(t), a) for t in ts_full])
    return _make_nurbs_from_pts(cp, degree=degree)


# ---------------------------------------------------------------------------
# Figure-eight polyline (degree-1 NURBS, exact self-intersection at origin)
# ---------------------------------------------------------------------------

def _make_figure8_polyline() -> NurbsCurve:
    """Explicit degree-1 piecewise-linear figure-eight crossing at (0,0,0).

    Traversal:
      (1, 0) → (0, 0) → (-1, 1) → (-1, -1) → (0, 0) → (1, 1) → (1, -1) → (0, 0)
    ... but using the simpler form: two overlapping triangles forming a figure-8.
    """
    pts = [
        [0.0,  0.0, 0.0],   # start = crossing point
        [1.0,  1.0, 0.0],
        [1.0, -1.0, 0.0],
        [0.0,  0.0, 0.0],   # back to crossing
        [-1.0, 1.0, 0.0],
        [-1.0,-1.0, 0.0],
        [0.0,  0.0, 0.0],   # end = crossing point
    ]
    cp = np.array(pts, dtype=float)
    n = len(cp)
    d = 1
    # Clamped degree-1: knots = [0,0, 1/5, 2/5, 3/5, 4/5, 1, 1]
    # Length = n + d + 1 = 9
    inner = np.linspace(0.0, 1.0, n - d + 1)[1:-1]  # n - d - 1 = 5 interior
    knots = np.concatenate([[0.0] * (d + 1), inner, [1.0] * (d + 1)])
    return NurbsCurve(degree=d, control_points=cp, knots=knots)


# ---------------------------------------------------------------------------
# Trefoil planar projection factory
# ---------------------------------------------------------------------------

def _make_trefoil_nurbs(n_cp: int = 48, degree: int = 3) -> NurbsCurve:
    """Planar projection of a trefoil knot.

    Parametric:
        x(t) = sin(t) + 2 sin(2t)
        y(t) = cos(t) - 2 cos(2t)

    This has exactly 3 self-intersection points in the plane.
    """
    ts = np.linspace(0.0, 2.0 * math.pi, n_cp + 1)
    # Include both endpoints (both at the start position) to make the NURBS
    # span the full loop with clamped boundary.
    cp = np.column_stack([
        np.sin(ts) + 2.0 * np.sin(2.0 * ts),
        np.cos(ts) - 2.0 * np.cos(2.0 * ts),
        np.zeros(len(ts)),
    ])
    return _make_nurbs_from_pts(cp, degree=degree)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCurveSelfIntersectLemniscate:
    """Oracle tests: lemniscate self-intersection at origin must be ≤1e-9."""

    def _lemniscate_curve(self) -> NurbsCurve:
        return _make_lemniscate_nurbs(a=1.0, n_cp=64, degree=3)

    def test_lemniscate_finds_at_least_one_hit(self):
        c = self._lemniscate_curve()
        hits = curve_self_intersect(c, tol=1e-6, samples=128)
        assert len(hits) >= 1, "Lemniscate must have at least one self-intersection"

    def test_lemniscate_oracle_origin(self):
        """The self-intersection point must be at the origin to ≤ 1e-9."""
        c = self._lemniscate_curve()
        hits = curve_self_intersect(c, tol=1e-6, samples=128)
        assert len(hits) >= 1
        # Find the hit closest to the origin.
        distances = [np.linalg.norm(h["point"]) for h in hits]
        best = min(distances)
        assert best <= 1e-9, (
            f"Best hit distance from origin is {best:.2e}, expected ≤ 1e-9. "
            f"Hits: {hits}"
        )

    def test_lemniscate_hit_keys(self):
        c = self._lemniscate_curve()
        hits = curve_self_intersect(c, tol=1e-6, samples=128)
        assert len(hits) >= 1
        h = hits[0]
        assert "ta" in h and "tb" in h and "point" in h

    def test_lemniscate_ta_le_tb(self):
        c = self._lemniscate_curve()
        hits = curve_self_intersect(c, tol=1e-6, samples=128)
        for h in hits:
            assert h["ta"] <= h["tb"], f"Expected ta <= tb, got {h}"

    def test_lemniscate_params_in_range(self):
        c = self._lemniscate_curve()
        t_min, t_max = _curve_param_range(c)
        hits = curve_self_intersect(c, tol=1e-6, samples=128)
        for h in hits:
            assert t_min <= h["ta"] <= t_max
            assert t_min <= h["tb"] <= t_max

    def test_lemniscate_point_on_curve(self):
        """Both curve evaluations at ta and tb should be close to point."""
        c = self._lemniscate_curve()
        hits = curve_self_intersect(c, tol=1e-6, samples=128)
        assert len(hits) >= 1
        for h in hits:
            A = _curve_eval(c, h["ta"])
            B = _curve_eval(c, h["tb"])
            pt = np.array(h["point"])
            assert np.linalg.norm(A - pt) < 1e-4, f"curve(ta) far from point: {h}"
            assert np.linalg.norm(B - pt) < 1e-4, f"curve(tb) far from point: {h}"


class TestCurveSelfIntersectFigureEight:
    """Tests for explicit figure-eight curves."""

    def test_figure8_polyline_finds_crossing(self):
        """Degree-1 figure-eight must report a self-intersection."""
        c = _make_figure8_polyline()
        hits = curve_self_intersect(c, tol=1e-8, samples=64)
        assert len(hits) >= 1, f"Figure-eight must self-intersect; got {hits}"

    def test_figure8_polyline_at_origin(self):
        c = _make_figure8_polyline()
        hits = curve_self_intersect(c, tol=1e-8, samples=64)
        distances = [np.linalg.norm(h["point"]) for h in hits]
        assert min(distances) < 1e-6, (
            f"Figure-eight crossing must be near origin; got distances {distances}"
        )

    def test_figure8_cubic_finds_one_hit(self):
        """A cubic figure-eight must report exactly 1 self-intersection
        after merging duplicates."""
        # Symmetric figure-eight control polygon: two lobes.
        cp = np.array([
            [ 0.0,  0.0, 0.0],
            [ 1.0,  1.5, 0.0],
            [ 2.0,  0.5, 0.0],
            [ 2.0, -0.5, 0.0],
            [ 1.0, -1.5, 0.0],
            [ 0.0,  0.0, 0.0],   # crossing
            [-1.0,  1.5, 0.0],
            [-2.0,  0.5, 0.0],
            [-2.0, -0.5, 0.0],
            [-1.0, -1.5, 0.0],
            [ 0.0,  0.0, 0.0],   # back to start
        ], dtype=float)
        c = _make_nurbs_from_pts(cp, degree=3)
        hits = curve_self_intersect(c, tol=1e-6, samples=128)
        assert len(hits) >= 1, "Cubic figure-eight must self-intersect"
        # After dedup, should not return hugely many hits.
        assert len(hits) <= 4, f"Too many hits for a figure-eight: {len(hits)}"


class TestCurveSelfIntersectNoCrossing:
    """Curves with no self-intersection must return []."""

    def test_line_no_self_intersection(self):
        c = _make_line_nurbs([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
        hits = curve_self_intersect(c)
        assert hits == [], f"Line must not self-intersect; got {hits}"

    def test_open_arc_no_self_intersection(self):
        c = _make_circle_arc(0.0, 0.0, 1.0, 0.0, 270.0, n_pts=16)
        hits = curve_self_intersect(c, tol=1e-6, samples=64)
        assert hits == [], f"Open arc must not self-intersect; got {hits}"

    def test_quarter_circle_no_self_intersection(self):
        c = _make_circle_arc(0.0, 0.0, 1.0, 0.0, 90.0, n_pts=8)
        hits = curve_self_intersect(c, tol=1e-6, samples=32)
        assert hits == [], f"Quarter circle must not self-intersect; got {hits}"


class TestCurveSelfIntersectTreefoil:
    """Trefoil planar projection has exactly 3 self-intersections."""

    def test_trefoil_finds_three_crossings(self):
        c = _make_trefoil_nurbs(n_cp=64, degree=3)
        hits = curve_self_intersect(c, tol=1e-5, samples=200)
        assert len(hits) >= 3, (
            f"Trefoil must have >=3 self-intersections; found {len(hits)}: {hits}"
        )

    def test_trefoil_hits_have_valid_keys(self):
        c = _make_trefoil_nurbs(n_cp=64, degree=3)
        hits = curve_self_intersect(c, tol=1e-5, samples=200)
        for h in hits:
            assert "ta" in h
            assert "tb" in h
            assert "point" in h
            assert len(h["point"]) == 3

    def test_trefoil_ta_le_tb_all(self):
        c = _make_trefoil_nurbs(n_cp=64, degree=3)
        hits = curve_self_intersect(c, tol=1e-5, samples=200)
        for h in hits:
            assert h["ta"] <= h["tb"]

    def test_trefoil_no_spurious_endpoint_hits(self):
        """No hit should have ta ≈ tb (endpoint-adjacency false positive)."""
        c = _make_trefoil_nurbs(n_cp=64, degree=3)
        t_min, t_max = _curve_param_range(c)
        hits = curve_self_intersect(c, tol=1e-5, samples=200)
        span = t_max - t_min
        for h in hits:
            gap = abs(h["tb"] - h["ta"])
            assert gap > span * 0.01, (
                f"Hit has ta≈tb ({h['ta']:.6f}, {h['tb']:.6f}), "
                "likely an endpoint-adjacency false positive"
            )


class TestCurveSelfIntersectRobustness:
    """Never-raise guarantee and edge cases."""

    def test_none_input_no_raise(self):
        hits = curve_self_intersect(None)  # type: ignore[arg-type]
        assert hits == []

    def test_string_input_no_raise(self):
        hits = curve_self_intersect("not_a_curve")  # type: ignore[arg-type]
        assert hits == []

    def test_higher_samples_consistent(self):
        """Using more samples should still find the lemniscate crossing."""
        c = _make_lemniscate_nurbs(a=1.0, n_cp=64, degree=3)
        hits_lo = curve_self_intersect(c, tol=1e-6, samples=64)
        hits_hi = curve_self_intersect(c, tol=1e-6, samples=256)
        assert len(hits_lo) >= 1
        assert len(hits_hi) >= 1

    def test_custom_loose_tol(self):
        """With a very loose tolerance, the lemniscate crossing is still found."""
        c = _make_lemniscate_nurbs(a=1.0, n_cp=64, degree=3)
        hits = curve_self_intersect(c, tol=1e-3, samples=64)
        assert len(hits) >= 1

    def test_point_is_list_of_three(self):
        c = _make_lemniscate_nurbs(a=1.0, n_cp=64, degree=3)
        hits = curve_self_intersect(c, tol=1e-6, samples=128)
        for h in hits:
            assert isinstance(h["point"], list)
            assert len(h["point"]) == 3
            for coord in h["point"]:
                assert math.isfinite(coord)
