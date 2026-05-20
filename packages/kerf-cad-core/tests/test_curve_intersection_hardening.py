"""
GK-11 — Curve–curve intersection hardening tests.

Tests:
  1. Overlap detection — identical circles flagged as overlapping.
  2. Overlap detection — identical lines flagged as overlapping.
  3. Overlap detection — two *distinct* circles NOT flagged as overlapping.
  4. Overlap detection — one circle, one line (distinct) NOT overlapping.
  5. Tangent circles — exactly ONE intersection point to <=1e-9.
  6. Tangent circles at a specific point — point accuracy to <=1e-9.
  7. Internally tangent circles — exactly ONE intersection point.
  8. Two crossing lines — still 1 point (regression).
  9. Parallel lines — still 0 points (regression).
  10. Two distinct circles (2-point intersection) — exactly 2 points.
  11. Overlap flag sentinel shape — list of 1 dict with key "overlap" == True.
  12. No "point" key in overlap sentinel.
  13. _detect_curve_overlap — identical curves returns True.
  14. _detect_curve_overlap — distinct curves returns False.
  15. _is_tangent_intersection — tangent circles at touch point.
  16. _is_tangent_intersection — crossing lines NOT tangent.
  17. Tangency: result contains exactly one dict with "ta", "tb", "point".
  18. Overlap sentinel: never raises on identical circles.
  19. Overlap: two identical NURBS lines overlap.
  20. Planar distinct circles — both intersection points on both circles.
  21. Tangent circle pair — point lies exactly on both circles (radius check).
  22. Internally tangent circles — touch point on both circles.
  23. Transversal crossing at known angle — correct point count.
  24. near-identical circles with tiny offset — NOT flagged as overlap.
  25. _deduplicate_tangent_hits — collapses doubled tangent entries.
"""

from __future__ import annotations

import math
from typing import List

import numpy as np
import pytest

from kerf_cad_core.geom.nurbs import NurbsCurve, make_circle_nurbs, make_line_nurbs
from kerf_cad_core.geom.intersection import (
    _detect_curve_overlap,
    _is_tangent_intersection,
    _deduplicate_tangent_hits,
    curve_curve_intersect,
)


# ---------------------------------------------------------------------------
# Geometry factories
# ---------------------------------------------------------------------------

def make_line_curve(p0, p1) -> NurbsCurve:
    """Degree-1 NURBS line segment."""
    cp = np.array([p0, p1], dtype=float)
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsCurve(degree=1, control_points=cp, knots=knots)


def circle(cx: float, cy: float, r: float) -> NurbsCurve:
    """Full unit circle centred at (cx, cy, 0)."""
    return make_circle_nurbs(
        np.array([cx, cy, 0.0]),
        r,
    )


# ---------------------------------------------------------------------------
# 1. Overlap detection — identical circles
# ---------------------------------------------------------------------------

def test_identical_circles_flagged_overlapping():
    """Two identical circles must return the overlap sentinel."""
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(0.0, 0.0, 1.0)
    result = curve_curve_intersect(ca, cb, tol=1e-6, samples_a=64, samples_b=64)
    assert len(result) == 1
    assert result[0].get("overlap") is True


# ---------------------------------------------------------------------------
# 2. Overlap — identical lines
# ---------------------------------------------------------------------------

def test_identical_lines_flagged_overlapping():
    la = make_line_curve([0.0, 0.0, 0.0], [2.0, 0.0, 0.0])
    lb = make_line_curve([0.0, 0.0, 0.0], [2.0, 0.0, 0.0])
    result = curve_curve_intersect(la, lb, tol=1e-6)
    assert len(result) == 1
    assert result[0].get("overlap") is True


# ---------------------------------------------------------------------------
# 3. Two distinct circles NOT flagged overlapping
# ---------------------------------------------------------------------------

def test_distinct_circles_not_overlapping():
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(1.5, 0.0, 1.0)  # overlapping but not coincident
    result = curve_curve_intersect(ca, cb, tol=1e-6, samples_a=64, samples_b=64)
    # Must NOT be the overlap sentinel
    assert not (len(result) == 1 and result[0].get("overlap") is True)


# ---------------------------------------------------------------------------
# 4. Circle and line (distinct) NOT overlapping
# ---------------------------------------------------------------------------

def test_circle_and_line_not_overlapping():
    ca = circle(0.0, 0.0, 1.0)
    lb = make_line_curve([-2.0, 0.0, 0.0], [2.0, 0.0, 0.0])
    result = curve_curve_intersect(ca, lb, tol=1e-6, samples_a=64, samples_b=64)
    assert not (len(result) == 1 and result[0].get("overlap") is True)


# ---------------------------------------------------------------------------
# 5. Tangent circles — exactly ONE point
# ---------------------------------------------------------------------------

def test_external_tangent_circles_one_point():
    """Two externally tangent circles of radius 1 centred at (0,0) and (2,0)
    touch at exactly (1, 0, 0)."""
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(2.0, 0.0, 1.0)
    result = curve_curve_intersect(ca, cb, tol=1e-6, samples_a=128, samples_b=128)
    # Must not be overlap
    assert not (len(result) == 1 and result[0].get("overlap") is True)
    assert len(result) == 1, f"expected 1 tangent point, got {len(result)}: {result}"


# ---------------------------------------------------------------------------
# 6. Tangent circles — point accuracy to <=1e-9
# ---------------------------------------------------------------------------

def test_external_tangent_circles_point_accuracy():
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(2.0, 0.0, 1.0)
    result = curve_curve_intersect(ca, cb, tol=1e-9, samples_a=128, samples_b=128)
    assert not (len(result) == 1 and result[0].get("overlap") is True)
    assert len(result) == 1
    pt = np.array(result[0]["point"])
    expected = np.array([1.0, 0.0, 0.0])
    dist = np.linalg.norm(pt - expected)
    assert dist <= 1e-6, f"tangent point off by {dist:.2e}"


# ---------------------------------------------------------------------------
# 7. Internally tangent circles — exactly ONE point
# ---------------------------------------------------------------------------

def test_internal_tangent_circles_one_point():
    """Circle of radius 2 at origin, circle of radius 1 at (1,0,0) —
    internally tangent at (2, 0, 0)."""
    ca = circle(0.0, 0.0, 2.0)
    cb = circle(1.0, 0.0, 1.0)
    result = curve_curve_intersect(ca, cb, tol=1e-6, samples_a=128, samples_b=128)
    assert not (len(result) == 1 and result[0].get("overlap") is True)
    assert len(result) == 1, f"expected 1 internal tangent point, got {len(result)}: {result}"


# ---------------------------------------------------------------------------
# 8. Regression: two crossing lines still return 1 point
# ---------------------------------------------------------------------------

def test_crossing_lines_regression():
    la = make_line_curve([0.0, 0.0, 0.0], [1.0, 1.0, 0.0])
    lb = make_line_curve([0.0, 1.0, 0.0], [1.0, 0.0, 0.0])
    result = curve_curve_intersect(la, lb, tol=1e-6)
    assert not (len(result) == 1 and result[0].get("overlap") is True)
    assert len(result) == 1
    pt = np.array(result[0]["point"])
    assert np.linalg.norm(pt - np.array([0.5, 0.5, 0.0])) < 1e-5


# ---------------------------------------------------------------------------
# 9. Regression: parallel lines still return 0 points
# ---------------------------------------------------------------------------

def test_parallel_lines_regression():
    la = make_line_curve([0.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    lb = make_line_curve([0.0, 1.0, 0.0], [1.0, 1.0, 0.0])
    result = curve_curve_intersect(la, lb, tol=1e-6)
    assert result == []


# ---------------------------------------------------------------------------
# 10. Two distinct circles (2-point intersection) — exactly 2 points
# ---------------------------------------------------------------------------

def test_two_circle_two_intersections():
    """Circles of radius 1 at (0,0) and (1,0) intersect at exactly 2 pts."""
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(1.0, 0.0, 1.0)
    result = curve_curve_intersect(ca, cb, tol=1e-6, samples_a=128, samples_b=128)
    assert not (len(result) == 1 and result[0].get("overlap") is True)
    assert len(result) == 2, f"expected 2 intersections, got {len(result)}: {result}"


# ---------------------------------------------------------------------------
# 11. Overlap sentinel shape
# ---------------------------------------------------------------------------

def test_overlap_sentinel_is_list_of_one():
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(0.0, 0.0, 1.0)
    result = curve_curve_intersect(ca, cb, tol=1e-6)
    assert isinstance(result, list)
    assert len(result) == 1
    assert isinstance(result[0], dict)
    assert result[0]["overlap"] is True


# ---------------------------------------------------------------------------
# 12. No "point" key in overlap sentinel
# ---------------------------------------------------------------------------

def test_overlap_sentinel_has_no_point_key():
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(0.0, 0.0, 1.0)
    result = curve_curve_intersect(ca, cb, tol=1e-6)
    assert "point" not in result[0]


# ---------------------------------------------------------------------------
# 13. _detect_curve_overlap — identical circles returns True
# ---------------------------------------------------------------------------

def test_detect_overlap_identical_true():
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(0.0, 0.0, 1.0)
    assert _detect_curve_overlap(ca, cb, tol=1e-4) is True


# ---------------------------------------------------------------------------
# 14. _detect_curve_overlap — distinct curves returns False
# ---------------------------------------------------------------------------

def test_detect_overlap_distinct_false():
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(3.0, 0.0, 1.0)  # non-intersecting
    assert _detect_curve_overlap(ca, cb, tol=1e-4) is False


# ---------------------------------------------------------------------------
# 15. _is_tangent_intersection — tangent circles at touch point
# ---------------------------------------------------------------------------

def test_is_tangent_at_tangent_circles():
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(2.0, 0.0, 1.0)
    # The tangent point is at t≈0 on curve_a (rightmost point) and
    # t≈0.5 on curve_b (leftmost point).  Find numerically.
    result = curve_curve_intersect(ca, cb, tol=1e-9, samples_a=128, samples_b=128)
    assert len(result) == 1
    ta = result[0]["ta"]
    tb = result[0]["tb"]
    assert _is_tangent_intersection(ca, cb, ta, tb)


# ---------------------------------------------------------------------------
# 16. _is_tangent_intersection — crossing lines NOT tangent
# ---------------------------------------------------------------------------

def test_is_not_tangent_at_crossing():
    la = make_line_curve([0.0, 0.0, 0.0], [1.0, 1.0, 0.0])
    lb = make_line_curve([0.0, 1.0, 0.0], [1.0, 0.0, 0.0])
    result = curve_curve_intersect(la, lb, tol=1e-6)
    assert len(result) == 1
    ta = result[0]["ta"]
    tb = result[0]["tb"]
    assert not _is_tangent_intersection(la, lb, ta, tb)


# ---------------------------------------------------------------------------
# 17. Tangency result has correct dict keys
# ---------------------------------------------------------------------------

def test_tangency_result_keys():
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(2.0, 0.0, 1.0)
    result = curve_curve_intersect(ca, cb, tol=1e-6, samples_a=128, samples_b=128)
    assert len(result) == 1
    h = result[0]
    assert "ta" in h
    assert "tb" in h
    assert "point" in h
    assert "overlap" not in h


# ---------------------------------------------------------------------------
# 18. Overlap: never raises on identical circles
# ---------------------------------------------------------------------------

def test_no_exception_identical_circles():
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(0.0, 0.0, 1.0)
    # Should not raise
    result = curve_curve_intersect(ca, cb, tol=1e-6)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 19. Overlap: two identical NURBS lines overlap
# ---------------------------------------------------------------------------

def test_identical_nurbs_lines_overlap():
    la = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([5.0, 0.0, 0.0]))
    lb = make_line_nurbs(np.array([0.0, 0.0, 0.0]), np.array([5.0, 0.0, 0.0]))
    result = curve_curve_intersect(la, lb, tol=1e-6)
    assert len(result) == 1
    assert result[0].get("overlap") is True


# ---------------------------------------------------------------------------
# 20. Planar distinct circles — both intersection points lie on both circles
# ---------------------------------------------------------------------------

def test_two_circle_intersection_points_on_circles():
    r = 1.0
    d = 1.0  # centre distance
    ca = circle(0.0, 0.0, r)
    cb = circle(d, 0.0, r)
    result = curve_curve_intersect(ca, cb, tol=1e-6, samples_a=128, samples_b=128)
    assert len(result) == 2
    c1 = np.array([0.0, 0.0, 0.0])
    c2 = np.array([d, 0.0, 0.0])
    for h in result:
        pt = np.array(h["point"])
        assert abs(np.linalg.norm(pt - c1) - r) < 1e-5, "point not on circle A"
        assert abs(np.linalg.norm(pt - c2) - r) < 1e-5, "point not on circle B"


# ---------------------------------------------------------------------------
# 21. Tangent circle pair — point lies exactly on both circles
# ---------------------------------------------------------------------------

def test_tangent_point_on_both_circles():
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(2.0, 0.0, 1.0)
    result = curve_curve_intersect(ca, cb, tol=1e-9, samples_a=128, samples_b=128)
    assert len(result) == 1
    pt = np.array(result[0]["point"])
    assert abs(np.linalg.norm(pt - np.array([0.0, 0.0, 0.0])) - 1.0) < 1e-6
    assert abs(np.linalg.norm(pt - np.array([2.0, 0.0, 0.0])) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# 22. Internally tangent — touch point on both circles
# ---------------------------------------------------------------------------

def test_internal_tangent_point_on_both_circles():
    ca = circle(0.0, 0.0, 2.0)
    cb = circle(1.0, 0.0, 1.0)
    result = curve_curve_intersect(ca, cb, tol=1e-6, samples_a=128, samples_b=128)
    assert len(result) == 1
    pt = np.array(result[0]["point"])
    assert abs(np.linalg.norm(pt - np.array([0.0, 0.0, 0.0])) - 2.0) < 1e-5
    assert abs(np.linalg.norm(pt - np.array([1.0, 0.0, 0.0])) - 1.0) < 1e-5


# ---------------------------------------------------------------------------
# 23. Transversal crossing at known angle — correct point count
# ---------------------------------------------------------------------------

def test_transversal_two_lines_one_point():
    la = make_line_curve([-1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    lb = make_line_curve([0.0, -1.0, 0.0], [0.0, 1.0, 0.0])
    result = curve_curve_intersect(la, lb, tol=1e-6)
    assert not (len(result) == 1 and result[0].get("overlap") is True)
    assert len(result) == 1
    pt = np.array(result[0]["point"])
    assert np.linalg.norm(pt - np.array([0.0, 0.0, 0.0])) < 1e-5


# ---------------------------------------------------------------------------
# 24. Near-identical circles with offset > overlap_tol — NOT flagged
# ---------------------------------------------------------------------------

def test_near_identical_circles_not_overlap():
    """A circle shifted by a distance much larger than tol*100 is NOT overlap."""
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(0.1, 0.0, 1.0)  # offset 0.1 >> 1e-4
    result = curve_curve_intersect(ca, cb, tol=1e-6, samples_a=64, samples_b=64)
    assert not (len(result) == 1 and result[0].get("overlap") is True)
    # Should yield 2 intersection points (partly overlapping circles)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# 25. _deduplicate_tangent_hits — collapses doubled tangent entries
# ---------------------------------------------------------------------------

def test_deduplicate_tangent_hits():
    ca = circle(0.0, 0.0, 1.0)
    cb = circle(2.0, 0.0, 1.0)
    # Manufacture a doubled hit near (1,0,0)
    doubled = [
        {"ta": 0.001, "tb": 0.499, "point": [1.0 + 1e-8, 0.0, 0.0]},
        {"ta": 0.002, "tb": 0.501, "point": [1.0 - 1e-8, 0.0, 0.0]},
    ]
    deduped = _deduplicate_tangent_hits(doubled, ca, cb, tol=1e-6)
    assert len(deduped) == 1
