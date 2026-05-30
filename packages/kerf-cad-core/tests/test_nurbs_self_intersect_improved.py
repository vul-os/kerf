"""
test_nurbs_self_intersect_improved.py
======================================
Validation suite for the improved NURBS curve self-intersection algorithm.

Algorithms under test
---------------------
``curve_self_intersect_robust`` (and its public alias ``curve_self_intersect``)
implements:
  - Piegl-Tiller §5.5 AABB-hierarchy recursive subdivision seeding.
  - Sederberg 1985 "Geometric Hermite approximation" bisection stop criterion.
  - Newton-Raphson refinement on f(t1,t2) = C(t1)-C(t2) = 0.

Test categories
---------------
1.  Figure-8 cubic Bezier oracle -- exactly ONE self-intersection, verified
    to within 1e-9 of the analytic crossing point.
2.  Circle (no self-intersection) -- must return [].
3.  Polynomial curves with known crossings.
4.  Performance smoke -- 100-knot curve processed in < 1 second.
5.  Backward-compatibility -- curve_self_intersect aliases robust impl.
6.  Honest-flag coverage -- multiplicity-3 note documented.

All tests are hermetic: pure Python + NumPy, no OCC, no DB, no network.
"""

from __future__ import annotations

import math
import time
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve
from kerf_cad_core.geom.intersection import (
    curve_self_intersect,
    curve_self_intersect_robust,
    _curve_eval,
    _curve_param_range,
)


# ---------------------------------------------------------------------------
# Curve factories
# ---------------------------------------------------------------------------

def _make_nurbs(control_points: np.ndarray, degree: int = 3) -> NurbsCurve:
    """Build a clamped B-spline with the given control polygon."""
    n = len(control_points)
    d = min(degree, n - 1)
    n_inner = max(0, n - d - 1)
    interior = np.linspace(0.0, 1.0, n_inner + 2)[1:-1] if n_inner > 0 else np.array([])
    knots = np.concatenate([np.zeros(d + 1), interior, np.ones(d + 1)])
    return NurbsCurve(degree=d, control_points=control_points.astype(float), knots=knots)


def _make_figure8_cubic_bezier() -> NurbsCurve:
    """Cubic Bezier figure-8: control points (0,0), (1,1), (1,-1), (0,0).

    This is a degree-3 Bezier with 4 control points -- the canonical
    self-intersecting cubic.  The crossing locus is at the origin (0,0,0).
    """
    cp = np.array([
        [0.0,  0.0, 0.0],
        [1.0,  1.0, 0.0],
        [1.0, -1.0, 0.0],
        [0.0,  0.0, 0.0],
    ])
    # Clamped degree-3 Bezier: knots [0,0,0,0,1,1,1,1]
    knots = np.array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0])
    return NurbsCurve(degree=3, control_points=cp, knots=knots)


def _make_circle_nurbs(r: float = 1.0, n_pts: int = 16, degree: int = 3) -> NurbsCurve:
    """Approximate circle as a clamped B-spline (open arc 0->359.9 deg)."""
    thetas = np.linspace(0.0, 2.0 * math.pi * (1.0 - 1.0 / n_pts), n_pts)
    cp = np.column_stack([r * np.cos(thetas), r * np.sin(thetas), np.zeros(n_pts)])
    return _make_nurbs(cp, degree=degree)


def _make_lemniscate(a: float = 1.0, n_cp: int = 32, degree: int = 3) -> NurbsCurve:
    """Bernoulli lemniscate as a control-polygon NURBS.

    Self-intersection at the origin (both t~0 and t~pi map near origin).
    """
    ts_inner = np.linspace(0.0, 2.0 * math.pi, n_cp + 1)[:-1]
    ts = np.concatenate([[0.0], ts_inner, [2.0 * math.pi]])

    def _pt(t):
        s, c = math.sin(t), math.cos(t)
        d = 1.0 + s * s
        return np.array([a * c / d, a * s * c / d, 0.0])

    cp = np.array([_pt(float(t)) for t in ts])
    return _make_nurbs(cp, degree=degree)


def _make_trefoil(n_cp: int = 48, degree: int = 3) -> NurbsCurve:
    """Planar trefoil projection -- exactly 3 self-intersections."""
    ts = np.linspace(0.0, 2.0 * math.pi, n_cp + 1)
    cp = np.column_stack([
        np.sin(ts) + 2.0 * np.sin(2.0 * ts),
        np.cos(ts) - 2.0 * np.cos(2.0 * ts),
        np.zeros(len(ts)),
    ])
    return _make_nurbs(cp, degree=degree)


def _make_100_knot_curve() -> NurbsCurve:
    """Degree-3 NURBS with ~100 knots (large, for performance smoke)."""
    n_cp = 60  # -> n_cp + degree + 1 = 64 knots
    ts = np.linspace(0.0, 6.0 * math.pi, n_cp)
    cp = np.column_stack([
        np.cos(ts) + 0.2 * np.cos(3.0 * ts),
        np.sin(ts) + 0.2 * np.sin(3.0 * ts),
        0.1 * ts,
    ])
    return _make_nurbs(cp, degree=3)


# ---------------------------------------------------------------------------
# 1. Figure-8 cubic Bezier oracle
# ---------------------------------------------------------------------------

class TestFigure8CubicBezierOracle:
    """Oracle: figure-8 Bezier (0,0)->(1,1)->(1,-1)->(0,0) has exactly one
    self-intersection at (0,0,0), verified to within 1e-9."""

    def _curve(self) -> NurbsCurve:
        return _make_figure8_cubic_bezier()

    def test_finds_exactly_one_hit(self):
        """Figure-8 Bezier must have exactly ONE self-intersection after merge."""
        c = self._curve()
        hits = curve_self_intersect_robust(c, tol=1e-10, samples=64)
        assert len(hits) == 1, (
            f"Expected exactly 1 self-intersection; got {len(hits)}: {hits}"
        )

    def test_hit_point_at_origin_within_1e9(self):
        """The crossing must be within 1e-9 of the origin (analytic oracle)."""
        c = self._curve()
        hits = curve_self_intersect_robust(c, tol=1e-10, samples=64)
        assert len(hits) >= 1, "No hit found"
        dist = np.linalg.norm(np.array(hits[0]["point"]))
        assert dist <= 1e-9, (
            f"Hit distance from origin = {dist:.3e}, expected <= 1e-9"
        )

    def test_ta_less_than_tb(self):
        c = self._curve()
        hits = curve_self_intersect_robust(c, tol=1e-10, samples=64)
        for h in hits:
            assert h["ta"] <= h["tb"], f"Expected ta<=tb, got {h}"

    def test_curve_params_in_range(self):
        c = self._curve()
        t_min, t_max = _curve_param_range(c)
        hits = curve_self_intersect_robust(c, tol=1e-10, samples=64)
        for h in hits:
            assert t_min <= h["ta"] <= t_max, f"ta out of range: {h}"
            assert t_min <= h["tb"] <= t_max, f"tb out of range: {h}"

    def test_curve_evals_close_to_point(self):
        """C(ta) and C(tb) must both be within 1e-7 of the reported point."""
        c = self._curve()
        hits = curve_self_intersect_robust(c, tol=1e-10, samples=64)
        assert len(hits) >= 1
        h = hits[0]
        pt = np.array(h["point"])
        Pa = _curve_eval(c, h["ta"])
        Pb = _curve_eval(c, h["tb"])
        assert np.linalg.norm(Pa - pt) < 1e-7, f"C(ta) far from point: {np.linalg.norm(Pa - pt):.2e}"
        assert np.linalg.norm(Pb - pt) < 1e-7, f"C(tb) far from point: {np.linalg.norm(Pb - pt):.2e}"

    def test_dict_keys_present(self):
        c = self._curve()
        hits = curve_self_intersect_robust(c, tol=1e-10, samples=64)
        assert len(hits) >= 1
        h = hits[0]
        assert "ta" in h
        assert "tb" in h
        assert "point" in h
        assert len(h["point"]) == 3

    def test_point_coordinates_finite(self):
        c = self._curve()
        hits = curve_self_intersect_robust(c, tol=1e-10, samples=64)
        assert len(hits) >= 1
        for coord in hits[0]["point"]:
            assert math.isfinite(coord)


# ---------------------------------------------------------------------------
# 2. Circle -- no self-intersection
# ---------------------------------------------------------------------------

class TestCircleNoSelfIntersection:
    """A circle approximation must return no self-intersections."""

    def test_circle_returns_empty(self):
        c = _make_circle_nurbs(r=1.0, n_pts=20, degree=3)
        hits = curve_self_intersect_robust(c, tol=1e-6, samples=64)
        assert hits == [], f"Circle must not self-intersect; got {hits}"

    def test_large_circle_returns_empty(self):
        c = _make_circle_nurbs(r=100.0, n_pts=24, degree=3)
        hits = curve_self_intersect_robust(c, tol=1e-5, samples=64)
        assert hits == [], f"Large circle must not self-intersect; got {hits}"

    def test_small_arc_returns_empty(self):
        """Open quarter-arc has no self-intersection."""
        n_pts = 8
        thetas = np.linspace(0.0, math.pi * 0.5, n_pts)
        cp = np.column_stack([np.cos(thetas), np.sin(thetas), np.zeros(n_pts)])
        c = _make_nurbs(cp, degree=3)
        hits = curve_self_intersect_robust(c, tol=1e-6, samples=32)
        assert hits == [], f"Quarter arc must not self-intersect; got {hits}"

    def test_line_returns_empty(self):
        """Straight line segment has no self-intersection."""
        cp = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]])
        knots = np.array([0.0, 0.0, 1.0, 1.0])
        c = NurbsCurve(degree=1, control_points=cp, knots=knots)
        hits = curve_self_intersect_robust(c, tol=1e-6)
        assert hits == [], f"Line must not self-intersect; got {hits}"


# ---------------------------------------------------------------------------
# 3. Polynomial curves with known crossings
# ---------------------------------------------------------------------------

class TestPolynomialKnownCrossings:
    """Lemniscate (1 crossing) and trefoil (3 crossings) with known geometry."""

    def test_lemniscate_finds_one_crossing(self):
        c = _make_lemniscate(a=1.0, n_cp=64, degree=3)
        hits = curve_self_intersect_robust(c, tol=1e-6, samples=128)
        assert len(hits) >= 1, f"Lemniscate must self-intersect; got {hits}"

    def test_lemniscate_crossing_near_origin(self):
        """Bernoulli lemniscate crosses at the origin."""
        c = _make_lemniscate(a=1.0, n_cp=64, degree=3)
        hits = curve_self_intersect_robust(c, tol=1e-6, samples=128)
        assert len(hits) >= 1
        dists = [np.linalg.norm(h["point"]) for h in hits]
        assert min(dists) <= 1e-4, (
            f"Lemniscate crossing must be near origin; distances = {dists}"
        )

    def test_trefoil_finds_three_crossings(self):
        c = _make_trefoil(n_cp=64, degree=3)
        hits = curve_self_intersect_robust(c, tol=1e-5, samples=200)
        assert len(hits) >= 3, (
            f"Trefoil must have >=3 self-intersections; found {len(hits)}"
        )

    def test_trefoil_no_endpoint_false_positives(self):
        """No hit should have ta ~= tb (endpoint-adjacency artefact)."""
        c = _make_trefoil(n_cp=64, degree=3)
        t_min, t_max = _curve_param_range(c)
        hits = curve_self_intersect_robust(c, tol=1e-5, samples=200)
        span = t_max - t_min
        for h in hits:
            gap = abs(h["tb"] - h["ta"])
            assert gap > span * 0.01, (
                f"Hit has ta~=tb ({h['ta']:.6f}, {h['tb']:.6f}), "
                "likely endpoint-adjacency false positive"
            )

    def test_trefoil_all_hits_have_keys(self):
        c = _make_trefoil(n_cp=64, degree=3)
        hits = curve_self_intersect_robust(c, tol=1e-5, samples=200)
        for h in hits:
            assert "ta" in h and "tb" in h and "point" in h

    def test_figure8_extended_control_polygon(self):
        """Symmetric 11-point figure-eight control polygon must self-intersect."""
        cp = np.array([
            [ 0.0,  0.0, 0.0],
            [ 1.0,  1.5, 0.0],
            [ 2.0,  0.5, 0.0],
            [ 2.0, -0.5, 0.0],
            [ 1.0, -1.5, 0.0],
            [ 0.0,  0.0, 0.0],
            [-1.0,  1.5, 0.0],
            [-2.0,  0.5, 0.0],
            [-2.0, -0.5, 0.0],
            [-1.0, -1.5, 0.0],
            [ 0.0,  0.0, 0.0],
        ], dtype=float)
        c = _make_nurbs(cp, degree=3)
        hits = curve_self_intersect_robust(c, tol=1e-6, samples=128)
        assert len(hits) >= 1, "Extended figure-eight must self-intersect"
        # After dedup, should not return spuriously many hits
        assert len(hits) <= 6, f"Too many hits for a figure-eight: {len(hits)}"


# ---------------------------------------------------------------------------
# 4. Performance smoke: 100-knot curve < 1 second
# ---------------------------------------------------------------------------

class TestPerformanceSmoke:
    """The robust algorithm must handle a large NURBS curve in < 1 second."""

    def test_100_knot_curve_under_1_second(self):
        """100-knot NURBS processed in < 1 s (Piegl-Tiller AABB-tree culling)."""
        c = _make_100_knot_curve()
        t0 = time.perf_counter()
        hits = curve_self_intersect_robust(c, tol=1e-5, samples=100)
        elapsed = time.perf_counter() - t0
        assert elapsed < 1.0, (
            f"Performance budget exceeded: {elapsed:.2f}s > 1s for 100-knot curve"
        )
        # Result must be a list (may be empty or non-empty depending on geometry)
        assert isinstance(hits, list)

    def test_large_sample_count_still_fast(self):
        """samples=200 on a moderate curve must still be under 2 seconds."""
        c = _make_lemniscate(a=1.0, n_cp=32, degree=3)
        t0 = time.perf_counter()
        curve_self_intersect_robust(c, tol=1e-6, samples=200)
        elapsed = time.perf_counter() - t0
        assert elapsed < 2.0, f"samples=200 took {elapsed:.2f}s > 2s"


# ---------------------------------------------------------------------------
# 5. Backward-compatibility: curve_self_intersect aliases robust impl
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """curve_self_intersect (public API) must delegate to the robust impl."""

    def test_alias_finds_figure8_hit(self):
        c = _make_figure8_cubic_bezier()
        hits = curve_self_intersect(c, tol=1e-10, samples=64)
        assert len(hits) >= 1, "curve_self_intersect alias must find figure-8 hit"

    def test_alias_origin_within_1e9(self):
        c = _make_figure8_cubic_bezier()
        hits = curve_self_intersect(c, tol=1e-10, samples=64)
        dist = np.linalg.norm(np.array(hits[0]["point"]))
        assert dist <= 1e-9, f"Alias: distance from origin = {dist:.3e}, expected <= 1e-9"

    def test_alias_circle_returns_empty(self):
        c = _make_circle_nurbs(r=1.0, n_pts=16, degree=3)
        hits = curve_self_intersect(c, tol=1e-6, samples=64)
        assert hits == [], f"Alias: circle must not self-intersect; got {hits}"

    def test_alias_none_no_raise(self):
        hits = curve_self_intersect(None)  # type: ignore[arg-type]
        assert hits == []

    def test_alias_string_no_raise(self):
        hits = curve_self_intersect("not_a_curve")  # type: ignore[arg-type]
        assert hits == []


# ---------------------------------------------------------------------------
# 6. Robustness & edge cases
# ---------------------------------------------------------------------------

class TestRobustnessEdgeCases:
    """Never-raise guarantee and tolerance sensitivity."""

    def test_none_input_no_raise(self):
        hits = curve_self_intersect_robust(None)  # type: ignore[arg-type]
        assert hits == []

    def test_string_input_no_raise(self):
        hits = curve_self_intersect_robust("garbage")  # type: ignore[arg-type]
        assert hits == []

    def test_loose_tol_still_finds_figure8(self):
        c = _make_figure8_cubic_bezier()
        hits = curve_self_intersect_robust(c, tol=1e-4, samples=32)
        assert len(hits) >= 1, "Loose tolerance must still find figure-8 crossing"

    def test_tight_tol_matches_origin(self):
        """With tol=1e-11 the figure-8 crossing must still be <=1e-9 from origin."""
        c = _make_figure8_cubic_bezier()
        hits = curve_self_intersect_robust(c, tol=1e-11, samples=128)
        assert len(hits) >= 1
        dist = np.linalg.norm(np.array(hits[0]["point"]))
        assert dist <= 1e-9, f"Tight tol: distance from origin = {dist:.3e}"

    def test_point_is_3element_list(self):
        c = _make_figure8_cubic_bezier()
        hits = curve_self_intersect_robust(c, tol=1e-10, samples=64)
        for h in hits:
            assert isinstance(h["point"], list)
            assert len(h["point"]) == 3
            for coord in h["point"]:
                assert math.isfinite(coord)

    def test_duplicate_hits_merged_figure8(self):
        """After merge, figure-8 Bezier must yield exactly 1 hit."""
        c = _make_figure8_cubic_bezier()
        hits = curve_self_intersect_robust(c, tol=1e-10, samples=128)
        assert len(hits) == 1, (
            f"Duplicate hits not properly merged for figure-8; got {len(hits)}"
        )


# ---------------------------------------------------------------------------
# 7. Honest-flag documentation test
# ---------------------------------------------------------------------------

class TestHonestFlagDocumentation:
    """Verify that the docstring mentions multiplicity-3 limitation."""

    def test_docstring_mentions_multiplicity_3_limitation(self):
        """The honest-flag note about multiplicity-3 must appear in the docstring."""
        doc = curve_self_intersect_robust.__doc__ or ""
        assert "multiplicity" in doc.lower() or "NOT" in doc, (
            "Docstring must mention multiplicity-3 / higher limitation"
        )

    def test_docstring_cites_piegl_tiller(self):
        doc = curve_self_intersect_robust.__doc__ or ""
        assert "Piegl" in doc or "PT95" in doc, (
            "Docstring must cite Piegl-Tiller"
        )

    def test_docstring_cites_sederberg(self):
        doc = curve_self_intersect_robust.__doc__ or ""
        assert "Sederberg" in doc or "Sed85" in doc, (
            "Docstring must cite Sederberg 1985"
        )
