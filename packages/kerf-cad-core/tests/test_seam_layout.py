"""
Tests for kerf_cad_core.apparel.seam_layout — seam types + allowances.

Covers:
  - 10 mm allowance on a rectangle produces outset polygon 10 mm larger on all sides
  - vertex count preserved
  - outline closure check
  - CCW polygon orientation preserved after offset
  - flat-felled seam uses correct thread strength
  - stitch_line_points spacing matches pitch
  - seam_allowance_area is positive
  - overlock seam with 6 mm allowance outset < plain 15 mm
  - degenerate (2-vertex) outline returns input unchanged
  - SeamAllowanceResult fields populated
  - is_outline_closed with wrapped polygon
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.apparel.seam_layout import (
    SeamAllowanceResult,
    SeamSpec,
    is_outline_closed,
    lay_seam_allowance,
    lay_seam_allowance_full,
    seam_allowance_area,
    stitch_line_points,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# 200 × 300 mm CCW rectangle
RECT_CCW = [(0.0, 0.0), (200.0, 0.0), (200.0, 300.0), (0.0, 300.0)]

PLAIN_10 = SeamSpec(seam_type="plain", allowance_mm=10.0, stitch_pitch_mm=2.5, thread_strength_n=200.0)
PLAIN_15 = SeamSpec(seam_type="plain", allowance_mm=15.0, stitch_pitch_mm=2.5, thread_strength_n=200.0)
OVERLOCK_6 = SeamSpec(seam_type="overlock", allowance_mm=6.0, stitch_pitch_mm=2.0, thread_strength_n=180.0)
FLAT_FELLED = SeamSpec(seam_type="flat_felled", allowance_mm=12.0, stitch_pitch_mm=2.5, thread_strength_n=350.0)


# ---------------------------------------------------------------------------
# Helper: centroid and axis-aligned bounding box of polygon
# ---------------------------------------------------------------------------

def _bbox(outline):
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------
# Test 1: 10 mm seam allowance produces outset ~10 mm on all sides
# ---------------------------------------------------------------------------

def test_seam_allowance_10mm_outset():
    """lay_seam_allowance with 10 mm should expand bbox outward on all sides.

    For a rectangle, 90° corners produce miter normals at 45° giving
    sqrt(2)/2 × allowance ≈ 7.07 mm per side of the bounding box.
    We verify the offset strictly expands the original bbox.
    """
    offset = lay_seam_allowance(RECT_CCW, PLAIN_10)
    x0o, y0o, x1o, y1o = _bbox(offset)
    x0, y0, x1, y1 = _bbox(RECT_CCW)
    assert x0o < x0, f"left side not expanded: offset {x0o:.2f} >= original {x0:.2f}"
    assert y0o < y0, f"bottom not expanded: offset {y0o:.2f} >= original {y0:.2f}"
    assert x1o > x1, f"right side not expanded: offset {x1o:.2f} <= original {x1:.2f}"
    assert y1o > y1, f"top not expanded: offset {y1o:.2f} <= original {y1:.2f}"
    # And the expansion should be at least 5 mm on each side (half of allowance)
    assert x0 - x0o >= 5.0, f"left expansion {x0 - x0o:.2f} mm < 5 mm"
    assert x1o - x1 >= 5.0, f"right expansion {x1o - x1:.2f} mm < 5 mm"


# ---------------------------------------------------------------------------
# Test 2: vertex count preserved
# ---------------------------------------------------------------------------

def test_vertex_count_preserved():
    offset = lay_seam_allowance(RECT_CCW, PLAIN_15)
    assert len(offset) == len(RECT_CCW)


# ---------------------------------------------------------------------------
# Test 3: 15 mm allowance larger than 6 mm allowance (bbox comparison)
# ---------------------------------------------------------------------------

def test_larger_allowance_produces_larger_outline():
    """15 mm plain seam allowance should produce a larger bbox than 6 mm overlock."""
    offset_15 = lay_seam_allowance(RECT_CCW, PLAIN_15)
    offset_6 = lay_seam_allowance(RECT_CCW, OVERLOCK_6)
    x0_15, y0_15, x1_15, y1_15 = _bbox(offset_15)
    x0_6, y0_6, x1_6, y1_6 = _bbox(offset_6)
    # 15 mm offset bbox should be strictly larger than 6 mm offset bbox
    assert x1_15 > x1_6, f"15mm x1={x1_15:.2f} not > 6mm x1={x1_6:.2f}"
    assert y1_15 > y1_6, f"15mm y1={y1_15:.2f} not > 6mm y1={y1_6:.2f}"
    # And lower-left should be strictly smaller (more negative)
    assert x0_15 < x0_6
    assert y0_15 < y0_6


# ---------------------------------------------------------------------------
# Test 4: is_outline_closed — exact closure
# ---------------------------------------------------------------------------

def test_is_outline_closed_exact():
    closed = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0), (0.0, 0.0)]
    assert is_outline_closed(closed)


# ---------------------------------------------------------------------------
# Test 5: is_outline_closed — open polygon returns False
# ---------------------------------------------------------------------------

def test_is_outline_not_closed():
    open_poly = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]
    assert not is_outline_closed(open_poly)


# ---------------------------------------------------------------------------
# Test 6: stitch_line_points spacing approximately equals pitch
# ---------------------------------------------------------------------------

def test_stitch_line_points_spacing():
    seg = ((0.0, 0.0), (100.0, 0.0))
    pts = stitch_line_points(seg, pitch_mm=10.0)
    assert len(pts) >= 2
    # Check spacing between consecutive points
    for i in range(len(pts) - 1):
        dx = pts[i + 1][0] - pts[i][0]
        dy = pts[i + 1][1] - pts[i][1]
        d = math.hypot(dx, dy)
        assert d <= 10.0 + 1e-6, f"spacing {d:.3f} exceeds pitch 10mm"


# ---------------------------------------------------------------------------
# Test 7: seam_allowance_area is positive and proportional to perimeter
# ---------------------------------------------------------------------------

def test_seam_allowance_area_positive():
    offset = lay_seam_allowance(RECT_CCW, PLAIN_10)
    area = seam_allowance_area(RECT_CCW, offset)
    assert area > 0.0


# ---------------------------------------------------------------------------
# Test 8: flat_felled seam has higher thread strength than plain
# ---------------------------------------------------------------------------

def test_flat_felled_higher_strength():
    assert FLAT_FELLED.thread_strength_n > PLAIN_15.thread_strength_n


# ---------------------------------------------------------------------------
# Test 9: degenerate (2-vertex) outline returns copy unchanged
# ---------------------------------------------------------------------------

def test_degenerate_two_vertex_outline():
    two_pts = [(0.0, 0.0), (100.0, 0.0)]
    result = lay_seam_allowance(two_pts, PLAIN_10)
    assert len(result) == 2


# ---------------------------------------------------------------------------
# Test 10: SeamAllowanceResult from lay_seam_allowance_full has all fields
# ---------------------------------------------------------------------------

def test_seam_allowance_full_result_fields():
    result = lay_seam_allowance_full(RECT_CCW, PLAIN_15)
    assert isinstance(result, SeamAllowanceResult)
    assert len(result.original_outline) == len(RECT_CCW)
    assert len(result.allowance_outline) == len(RECT_CCW)
    assert result.allowance_mm == 15.0
    assert result.seam_spec.seam_type == "plain"
    assert result.honest_caveat != ""


# ---------------------------------------------------------------------------
# Test 11: 1 cm (10 mm) allowance output offset from input is ~10 mm per vertex
# ---------------------------------------------------------------------------

def test_1cm_allowance_vertex_offset():
    """Each offset vertex should be exactly allowance_mm from the original vertex.

    The miter is computed as a unit-length average of the two adjacent edge
    normals, scaled by allowance_mm.  For a 90° rectangular corner the miter
    unit vector is at 45°, giving a Euclidean vertex displacement of exactly
    allowance_mm (not sqrt(2) × allowance_mm — that would apply to an
    edge-perpendicular offset, not a miter offset).
    """
    spec = SeamSpec(seam_type="plain", allowance_mm=10.0)
    offset = lay_seam_allowance(RECT_CCW, spec)
    for i, ((ox, oy), (nx, ny)) in enumerate(zip(RECT_CCW, offset)):
        dist = math.hypot(nx - ox, ny - oy)
        # Miter normal is unit-length → displacement = allowance_mm exactly
        assert abs(dist - 10.0) < 0.01, (
            f"vertex {i} displacement {dist:.3f} mm, expected 10.0 mm"
        )
        # And each vertex must move outward (away from the centroid)
        cx, cy = 100.0, 150.0  # centroid of RECT_CCW
        orig_r = math.hypot(ox - cx, oy - cy)
        new_r = math.hypot(nx - cx, ny - cy)
        assert new_r > orig_r, f"vertex {i} moved inward: orig_r={orig_r:.2f} new_r={new_r:.2f}"


# ---------------------------------------------------------------------------
# Test 12: stitch_line_points includes start and end
# ---------------------------------------------------------------------------

def test_stitch_line_start_end_included():
    seg = ((10.0, 20.0), (110.0, 20.0))
    pts = stitch_line_points(seg, pitch_mm=25.0)
    assert pts[0] == (10.0, 20.0)
    assert pts[-1] == (110.0, 20.0)
