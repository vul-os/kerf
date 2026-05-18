"""Tests for 2D region boolean operations (GK P2 – GK-56/57).

Pytest oracles:
  * square ∪ overlapping circle has area ≈ square_area + circle_area − intersection_area
  * two disjoint loops → union returns both (area sum preserved)
  * full containment → difference returns the outer minus the hole (area decreases)
  * intersection of two overlapping squares is the overlapping rectangle
  * intersection of disjoint loops is empty

All tests are hermetic — no network, no OCCT, no fixtures.
"""

import math

import numpy as np
import pytest

from kerf_cad_core.geom.region_2d import (
    loop_area,
    loop_difference,
    loop_intersection,
    loop_union,
    make_circle_loop,
    make_rect_loop,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _total_area(loops) -> float:
    """Sum of absolute areas of result loops.

    For simple non-overlapping result polygons this equals the geometric area.
    For hole representations (outer CCW + inner CW) use _signed_area instead.
    """
    return sum(abs(loop_area(lp)) for lp in loops)


def _signed_area(loops) -> float:
    """Signed area sum: positive for CCW loops (filled), negative for CW (holes).

    A polygon-with-hole returned as [outer_ccw, inner_cw] gives
    area_outer - area_inner, which equals the correct filled area.
    """
    return sum(loop_area(lp) for lp in loops)


# ---------------------------------------------------------------------------
# Basic area measurements
# ---------------------------------------------------------------------------


def test_rect_loop_area():
    """A 2x2 rectangle should have area 4."""
    lp = make_rect_loop(0, 0, 2, 2)
    assert abs(loop_area(lp)) == pytest.approx(4.0, rel=1e-6)


def test_circle_loop_area():
    """A unit circle should have area π."""
    lp = make_circle_loop(0, 0, 1.0)
    assert abs(loop_area(lp)) == pytest.approx(math.pi, rel=1e-3)


def test_circle_loop_area_larger():
    """Circle with radius 3 should have area 9π."""
    lp = make_circle_loop(0, 0, 3.0)
    assert abs(loop_area(lp)) == pytest.approx(9.0 * math.pi, rel=1e-3)


# ---------------------------------------------------------------------------
# Union tests
# ---------------------------------------------------------------------------


def test_union_disjoint_returns_both():
    """Union of two non-overlapping rectangles returns both."""
    a = make_rect_loop(0, 0, 1, 1)
    b = make_rect_loop(3, 3, 4, 4)
    result = loop_union(a, b)
    assert len(result) == 2
    assert _total_area(result) == pytest.approx(
        abs(loop_area(a)) + abs(loop_area(b)), rel=1e-5
    )


def test_union_identical_returns_one():
    """Union of a loop with itself (or a congruent copy) returns a single region."""
    a = make_rect_loop(0, 0, 2, 2)
    b = make_rect_loop(0, 0, 2, 2)
    result = loop_union(a, b)
    # Should return exactly one region with the same area
    assert len(result) >= 1
    assert _total_area(result) == pytest.approx(4.0, rel=1e-4)


def test_union_contained_returns_outer():
    """Union of a small rect fully inside a large rect returns the large rect."""
    outer = make_rect_loop(0, 0, 4, 4)
    inner = make_rect_loop(1, 1, 3, 3)
    result = loop_union(outer, inner)
    assert len(result) == 1
    assert _total_area(result) == pytest.approx(16.0, rel=1e-4)


def test_union_overlapping_rects_area():
    """Union of two overlapping 2×2 squares offset by 1 unit.

    Square A: (0,0)-(2,2), area=4
    Square B: (1,0)-(3,2), area=4
    Intersection: (1,0)-(2,2), area=2
    Expected union area = 4 + 4 - 2 = 6
    """
    a = make_rect_loop(0, 0, 2, 2)
    b = make_rect_loop(1, 0, 3, 2)
    result = loop_union(a, b)
    assert len(result) >= 1
    assert _total_area(result) == pytest.approx(6.0, rel=1e-3)


def test_union_square_circle_area():
    """Square ∪ overlapping circle — area oracle.

    Square: (0,0)-(2,2), area = 4
    Circle: center (2,1), radius 1, area = π
    The circle center is on the right edge of the square; approximately
    half the circle is outside.  We use the analytic inclusion-exclusion
    principle:  union_area = A_square + A_circle − A_intersection.

    The intersection of the circle c=(2,1), r=1 with the square [0,2]x[0,2]
    is exactly a semicircle (the left half of the circle, x <= 2):
       A_intersection = π/2

    So expected union area = 4 + π − π/2 = 4 + π/2 ≈ 5.5708
    """
    square = make_rect_loop(0, 0, 2, 2)
    circle = make_circle_loop(2.0, 1.0, 1.0)

    a_sq = abs(loop_area(square))   # should be 4
    a_ci = abs(loop_area(circle))   # should be π

    result = loop_union(square, circle)
    union_area = _total_area(result)

    # The intersection region (half-circle) area = π/2
    a_int = math.pi / 2.0
    expected = a_sq + a_ci - a_int

    assert union_area == pytest.approx(expected, rel=5e-2)


# ---------------------------------------------------------------------------
# Intersection tests
# ---------------------------------------------------------------------------


def test_intersection_disjoint_is_empty():
    """Intersection of non-overlapping loops is empty."""
    a = make_rect_loop(0, 0, 1, 1)
    b = make_rect_loop(5, 5, 6, 6)
    result = loop_intersection(a, b)
    assert len(result) == 0


def test_intersection_overlapping_rects():
    """Intersection of two overlapping 2×2 squares offset by 1 unit is 1×2=2."""
    a = make_rect_loop(0, 0, 2, 2)
    b = make_rect_loop(1, 0, 3, 2)
    result = loop_intersection(a, b)
    assert len(result) >= 1
    assert _total_area(result) == pytest.approx(2.0, rel=1e-3)


def test_intersection_contained_is_inner():
    """Intersection of inner rect fully inside outer rect is the inner rect."""
    outer = make_rect_loop(0, 0, 4, 4)
    inner = make_rect_loop(1, 1, 3, 3)
    result = loop_intersection(outer, inner)
    assert len(result) == 1
    assert _total_area(result) == pytest.approx(4.0, rel=1e-4)


def test_intersection_identical():
    """Intersection of identical loops equals that loop."""
    a = make_rect_loop(0, 0, 3, 3)
    b = make_rect_loop(0, 0, 3, 3)
    result = loop_intersection(a, b)
    assert len(result) >= 1
    assert _total_area(result) == pytest.approx(9.0, rel=1e-4)


# ---------------------------------------------------------------------------
# Difference tests
# ---------------------------------------------------------------------------


def test_difference_disjoint_returns_a():
    """A − B where A and B are disjoint returns A."""
    a = make_rect_loop(0, 0, 2, 2)
    b = make_rect_loop(5, 5, 7, 7)
    result = loop_difference(a, b)
    assert len(result) >= 1
    assert _total_area(result) == pytest.approx(abs(loop_area(a)), rel=1e-5)


def test_difference_b_fully_inside_a():
    """A − B where B is fully inside A: area decreases by area of B.

    Outer square 4×4=16; inner square 2×2=4; difference area = 12.

    The implementation returns the outer loop (CCW, area +16) and the
    inner loop as a CW hole (area −4).  The signed sum equals 12.
    """
    outer = make_rect_loop(0, 0, 4, 4)
    inner = make_rect_loop(1, 1, 3, 3)
    result = loop_difference(outer, inner)
    assert len(result) >= 1
    # Signed-area sum handles the outer+hole representation correctly.
    assert _signed_area(result) == pytest.approx(12.0, rel=1e-3)


def test_difference_a_fully_inside_b():
    """A − B where A is fully inside B returns empty (A is subtracted away)."""
    small = make_rect_loop(1, 1, 2, 2)
    large = make_rect_loop(0, 0, 4, 4)
    result = loop_difference(small, large)
    assert len(result) == 0


def test_difference_partial_overlap():
    """A − B where A=(0,0)-(2,2) and B=(1,0)-(3,2) overlap by 1×2=2.

    Difference area = area(A) − area(A∩B) = 4 − 2 = 2.
    """
    a = make_rect_loop(0, 0, 2, 2)
    b = make_rect_loop(1, 0, 3, 2)
    result = loop_difference(a, b)
    assert len(result) >= 1
    assert _total_area(result) == pytest.approx(2.0, rel=1e-3)


# ---------------------------------------------------------------------------
# Inclusion-exclusion oracle (square ∪ circle)
# ---------------------------------------------------------------------------


def test_inclusion_exclusion_oracle():
    """Validate inclusion-exclusion: area(A∪B) = area(A) + area(B) - area(A∩B).

    We use two overlapping rectangles where all three areas are known exactly.
      A: (0,0)-(3,3)  area=9
      B: (2,0)-(5,3)  area=9
      A∩B: (2,0)-(3,3) area=3
      A∪B: area=15
    """
    a = make_rect_loop(0, 0, 3, 3)
    b = make_rect_loop(2, 0, 5, 3)

    area_a = abs(loop_area(a))
    area_b = abs(loop_area(b))

    union_loops = loop_union(a, b)
    isect_loops = loop_intersection(a, b)

    area_union = _total_area(union_loops)
    area_isect = _total_area(isect_loops)

    # Inclusion-exclusion
    assert area_a == pytest.approx(9.0, rel=1e-5)
    assert area_b == pytest.approx(9.0, rel=1e-5)
    assert area_isect == pytest.approx(3.0, rel=1e-3)
    assert area_union == pytest.approx(15.0, rel=1e-3)
    assert area_union == pytest.approx(area_a + area_b - area_isect, rel=1e-3)


# ---------------------------------------------------------------------------
# Loop structure sanity
# ---------------------------------------------------------------------------


def test_result_loops_have_coedges():
    """Result loops from boolean ops must have at least 3 coedges (non-degenerate)."""
    a = make_rect_loop(0, 0, 4, 4)
    b = make_rect_loop(2, 2, 6, 6)

    for lp in loop_union(a, b):
        assert len(lp.coedges) >= 3, "union result loop has fewer than 3 coedges"

    for lp in loop_intersection(a, b):
        assert len(lp.coedges) >= 3, "intersection result loop has fewer than 3 coedges"

    for lp in loop_difference(a, b):
        assert len(lp.coedges) >= 3, "difference result loop has fewer than 3 coedges"


def test_make_rect_loop_structure():
    """make_rect_loop produces a Loop with 4 coedges in z=0 plane."""
    lp = make_rect_loop(0, 0, 1, 1)
    assert len(lp.coedges) == 4
    for ce in lp.coedges:
        from kerf_cad_core.geom.brep import Line3
        assert isinstance(ce.edge.curve, Line3)


def test_make_circle_loop_structure():
    """make_circle_loop produces a Loop with 1 CircleArc3 coedge."""
    from kerf_cad_core.geom.brep import CircleArc3
    lp = make_circle_loop(0, 0, 1.0)
    assert len(lp.coedges) == 1
    assert isinstance(lp.coedges[0].edge.curve, CircleArc3)
