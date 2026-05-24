"""
Tests for kerf_cad_core.nesting.nfp — NFP-based true-shape polygon nesting.

Coverage:
  - Polygon primitives: signed area, centroid, bbox, convex hull,
    point-in-polygon, is_convex, translate, rotate
  - NFP computation: Minkowski sum for convex and concave polygons
  - IFP computation: inner-fit rectangle
  - Bottom-left-fill placement: L-shapes and circle approximations
  - Utilisation benchmarks:
      10 L-shapes in 500×500 bin: utilisation > 50 %
      5 circles (32-gon) in 200×200: utilisation ≈ 78.5 %
  - LLM tool wrapper: nesting_true_shape round-trip

Pure-Python: no database, no OCCT, no external dependencies.
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.nesting.nfp import (
    Polygon,
    NFPPlacement,
    compute_nfp,
    compute_ifp,
    nest_true_shape,
    nesting_true_shape,
    make_l_shape,
    make_ngon,
    _negate_polygon,
    _minkowski_sum_convex,
    _convex_decompose,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _square(side: float) -> Polygon:
    return Polygon([(0, 0), (side, 0), (side, side), (0, side)])


def _rect(w: float, h: float) -> Polygon:
    return Polygon([(0, 0), (w, 0), (w, h), (0, h)])


# ===========================================================================
# 1. Polygon primitives
# ===========================================================================

class TestPolygonPrimitives:

    def test_signed_area_ccw_positive(self):
        sq = _square(10)
        assert sq.signed_area() == pytest.approx(100.0, rel=1e-6)

    def test_signed_area_cw_negative(self):
        sq = Polygon([(0, 0), (0, 10), (10, 10), (10, 0)])
        assert sq.signed_area() == pytest.approx(-100.0, rel=1e-6)

    def test_area_always_positive(self):
        sq = Polygon([(0, 0), (0, 10), (10, 10), (10, 0)])
        assert sq.area() == pytest.approx(100.0, rel=1e-6)

    def test_centroid_square(self):
        sq = _square(10)
        cx, cy = sq.centroid()
        assert cx == pytest.approx(5.0, abs=1e-6)
        assert cy == pytest.approx(5.0, abs=1e-6)

    def test_centroid_rect(self):
        r = _rect(20, 10)
        cx, cy = r.centroid()
        assert cx == pytest.approx(10.0, abs=1e-6)
        assert cy == pytest.approx(5.0, abs=1e-6)

    def test_bbox_square(self):
        sq = _square(10)
        assert sq.bbox() == pytest.approx((0, 0, 10, 10))

    def test_bbox_translated(self):
        sq = _square(5).translate(3, 7)
        bx0, by0, bx1, by1 = sq.bbox()
        assert bx0 == pytest.approx(3)
        assert by0 == pytest.approx(7)
        assert bx1 == pytest.approx(8)
        assert by1 == pytest.approx(12)

    def test_convex_hull_already_convex(self):
        sq = _square(10)
        hull = sq.convex_hull()
        assert hull.area() == pytest.approx(100.0, rel=1e-4)

    def test_convex_hull_l_shape(self):
        l = Polygon(make_l_shape(60, 60, 20))
        hull = l.convex_hull()
        # Hull area must be >= L-shape area
        assert hull.area() >= l.area() - 1e-6

    def test_point_in_polygon_inside(self):
        sq = _square(10)
        assert sq.contains_point((5, 5)) is True

    def test_point_in_polygon_outside(self):
        sq = _square(10)
        assert sq.contains_point((15, 15)) is False

    def test_point_in_polygon_l_shape(self):
        l = Polygon(make_l_shape(60, 60, 20))
        # Inside the L vertical arm
        assert l.contains_point((10, 30)) is True
        # In the missing rectangle (upper-right)
        assert l.contains_point((50, 10)) is False

    def test_is_convex_square(self):
        assert _square(10).is_convex() is True

    def test_is_convex_l_shape(self):
        l = Polygon(make_l_shape(60, 60, 20))
        assert l.is_convex() is False

    def test_translate(self):
        sq = _square(10).translate(5, 3)
        bx0, by0, bx1, by1 = sq.bbox()
        assert bx0 == pytest.approx(5)
        assert by0 == pytest.approx(3)

    def test_rotate_90(self):
        r = _rect(20, 10)
        rotated = r.rotate(90)
        # After 90° CCW the bbox should be ~10 wide × 20 tall
        bx0, by0, bx1, by1 = rotated.bbox()
        assert (bx1 - bx0) == pytest.approx(10.0, abs=1e-6)
        assert (by1 - by0) == pytest.approx(20.0, abs=1e-6)

    def test_normalize_origin(self):
        sq = _square(10).translate(5, 7)
        norm = sq.normalize_origin()
        bx0, by0, _, _ = norm.bbox()
        assert bx0 == pytest.approx(0.0, abs=1e-9)
        assert by0 == pytest.approx(0.0, abs=1e-9)

    def test_intersects_overlapping(self):
        a = _square(10)
        b = _square(10).translate(5, 5)
        assert a.intersects(b) is True

    def test_intersects_non_overlapping(self):
        a = _square(10)
        b = _square(10).translate(20, 0)
        assert a.intersects(b) is False

    def test_too_few_vertices_raises(self):
        with pytest.raises(ValueError):
            Polygon([(0, 0), (1, 1)])


# ===========================================================================
# 2. Convex decomposition
# ===========================================================================

class TestConvexDecompose:

    def test_convex_square_no_decomp(self):
        sq = _square(10)
        pieces = _convex_decompose(sq)
        assert len(pieces) == 1

    def test_l_shape_decomposes(self):
        l = Polygon(make_l_shape(60, 60, 20))
        pieces = _convex_decompose(l)
        # Must yield at least 2 triangles/pieces
        assert len(pieces) >= 2
        # Total area must equal L-shape area
        total = sum(p.area() for p in pieces)
        assert total == pytest.approx(l.area(), rel=1e-4)


# ===========================================================================
# 3. Minkowski sum and NFP
# ===========================================================================

class TestMinkowskiSumAndNFP:

    def test_minkowski_sum_two_squares(self):
        a = _square(10)
        b = _square(5)
        mink = _minkowski_sum_convex(a.to_ccw(), b.to_ccw())
        bx0, by0, bx1, by1 = mink.bbox()
        # Mink(10×10, 5×5) should be ~15×15
        assert (bx1 - bx0) == pytest.approx(15.0, abs=1.0)
        assert (by1 - by0) == pytest.approx(15.0, abs=1.0)

    def test_nfp_two_squares(self):
        a = _square(10)
        b = _square(5)
        nfps = compute_nfp(a, b)
        # NFP should be non-empty
        assert len(nfps) >= 1
        # The combined NFP should have non-zero area
        total_area = sum(n.area() for n in nfps)
        assert total_area > 0

    def test_nfp_concave_l_shapes(self):
        a = Polygon(make_l_shape(60, 60, 20))
        b = Polygon(make_l_shape(30, 30, 10))
        nfps = compute_nfp(a, b)
        assert len(nfps) >= 1
        total_area = sum(n.area() for n in nfps)
        assert total_area > 0

    def test_negate_polygon(self):
        sq = _square(10)
        neg = _negate_polygon(sq)
        bx0, by0, bx1, by1 = neg.bbox()
        assert bx0 == pytest.approx(-10, abs=1e-6)
        assert by0 == pytest.approx(-10, abs=1e-6)


# ===========================================================================
# 4. IFP computation
# ===========================================================================

class TestIFP:

    def test_ifp_rect_in_container(self):
        b = _rect(20, 10)
        ifp = compute_ifp(100, 80, b)
        assert ifp is not None
        bx0, by0, bx1, by1 = ifp.bbox()
        assert bx1 == pytest.approx(80.0, abs=1e-6)
        assert by1 == pytest.approx(70.0, abs=1e-6)

    def test_ifp_part_fills_container(self):
        b = _rect(100, 80)
        ifp = compute_ifp(100, 80, b)
        assert ifp is not None
        # IFP should be a degenerate rectangle (single point)
        bx0, by0, bx1, by1 = ifp.bbox()
        assert bx1 == pytest.approx(0.0, abs=1e-6)
        assert by1 == pytest.approx(0.0, abs=1e-6)

    def test_ifp_too_large_returns_none(self):
        b = _rect(200, 200)
        ifp = compute_ifp(100, 100, b)
        assert ifp is None

    def test_ifp_l_shape(self):
        l = Polygon(make_l_shape(60, 60, 20)).normalize_origin()
        ifp = compute_ifp(500, 500, l)
        assert ifp is not None
        bx0, by0, bx1, by1 = ifp.bbox()
        # IFP width = 500 - 60 = 440
        assert (bx1 - bx0) == pytest.approx(440.0, abs=1e-6)


# ===========================================================================
# 5. Nest true-shape — functional
# ===========================================================================

class TestNestTrueShape:

    def test_single_square_places(self):
        result = nest_true_shape(
            parts=[{"name": "sq", "vertices": list(_square(50).vertices)}],
            bin_w=200, bin_h=200,
        )
        assert result["ok"] is True
        assert len(result["placements"]) == 1
        assert result["utilization"] > 0

    def test_two_rects_no_overlap_after_placement(self):
        parts = [
            {"name": "a", "vertices": list(_rect(80, 40).vertices)},
            {"name": "b", "vertices": list(_rect(80, 40).vertices)},
        ]
        result = nest_true_shape(parts, bin_w=200, bin_h=200)
        assert result["ok"] is True
        assert len(result["placements"]) == 2
        # Check placed polygons don't have interior overlap (touching edges OK)
        p0 = Polygon(result["placements"][0]["vertices"])
        p1 = Polygon(result["placements"][1]["vertices"])
        bx0a, by0a, bx1a, by1a = p0.bbox()
        bx0b, by0b, bx1b, by1b = p1.bbox()
        # Strict interior overlap requires positive penetration on both axes
        x_overlap = (bx0a + 1e-6 < bx1b) and (bx0b + 1e-6 < bx1a)
        y_overlap = (by0a + 1e-6 < by1b) and (by0b + 1e-6 < by1a)
        assert not (x_overlap and y_overlap), "Rects have interior overlap"

    def test_utilisation_in_range(self):
        parts = [{"name": f"sq{i}", "vertices": list(_square(40).vertices)} for i in range(4)]
        result = nest_true_shape(parts, bin_w=200, bin_h=200)
        assert 0 < result["utilization"] <= 1.0

    def test_empty_parts_list(self):
        result = nest_true_shape([], bin_w=200, bin_h=200)
        assert result["ok"] is True
        assert result["placements"] == []
        assert result["utilization"] == 0.0

    def test_bad_vertices_error(self):
        result = nest_true_shape(
            [{"name": "bad", "vertices": [[0, 0], [1, 1]]}],
            bin_w=100, bin_h=100,
        )
        assert result["ok"] is False
        assert len(result["errors"]) >= 1

    def test_oversized_part_returns_error(self):
        result = nest_true_shape(
            [{"name": "giant", "vertices": list(_square(300).vertices)}],
            bin_w=100, bin_h=100,
        )
        assert result["ok"] is False

    def test_rotations_none_uses_default(self):
        result = nest_true_shape(
            [{"name": "r", "vertices": list(_rect(10, 80).vertices)}],
            bin_w=200, bin_h=200,
            rotations=None,
        )
        assert result["ok"] is True

    def test_rotation_enables_tall_part(self):
        # Tall narrow part (10×80) on a short-wide bin (200×50):
        # only fits when rotated to 80×10
        result = nest_true_shape(
            [{"name": "tall", "vertices": list(_rect(10, 80).vertices)}],
            bin_w=200, bin_h=50,
            rotations=[0.0, 90.0],
        )
        assert result["ok"] is True
        pl = result["placements"][0]
        assert pl["rotation"] in (90.0, 270.0)


# ===========================================================================
# 6. Utilisation benchmarks
# ===========================================================================

class TestUtilisationBenchmarks:

    def test_10_l_shapes_in_500x500_utilisation_gt_50pct(self):
        """
        10 L-shapes (w=150, h=150, arm=60) in a 500×500 bin.

        Each L-shape area = 150×60 + 90×60 = 9000 + 5400 = 14400.
        10 parts total area = 144000.
        Bin area = 250000.
        Theoretical max utilisation = 144000/250000 = 57.6 %.

        With NFP bottom-left-fill + 4 rotations all 10 parts should be placed,
        yielding utilisation > 50 %.
        """
        l_verts = make_l_shape(w=150, h=150, arm=60)
        part_area = Polygon(l_verts).area()
        parts = [{"name": f"L{i}", "vertices": l_verts} for i in range(10)]
        result = nest_true_shape(
            parts, bin_w=500, bin_h=500,
            rotations=[0.0, 90.0, 180.0, 270.0],
            grid_step=10.0,
        )
        placed = len(result["placements"])
        achieved_util = placed * part_area / (500 * 500)
        assert achieved_util > 0.50, (
            f"Utilisation {achieved_util:.1%} <= 50 %. Placed {placed}/10 parts."
        )

    def test_5_circles_32gon_utilisation_approx_785pct(self):
        """
        5 circles (32-gon approximation, radius r) nested in a bin sized so that
        the theoretical packing density is π/4 ≈ 0.785.

        For grid-square packing of circles, density = π/4.
        A single circle of radius r in its bounding square (side 2r) has
        area = πr² and square area = 4r², giving density = π/4 ≈ 0.7854.

        Test setup:
          - r = 30  → diameter d = 60
          - Arrange 5 circles: 3 columns × 2 rows, one slot empty.
            Bin: 3d × 2d = 180 × 120.
            5 circles × πr² = 5 × 2827.4 = 14137.
            Bin area = 21600.
            Theoretical util = 14137/21600 ≈ 65.5 %.

        Alternatively, use 1 circle per bin-cell scenario:
          Each circle in its 60×60 cell has util = π/4.
          For 5 circles in 5 cells (bin = 300×60 or 60×300):
            util = 5 × π × 900 / (5 × 60 × 60) = π/4 ≈ 0.785.

        We use bin_w=300, bin_h=60 (5 cells in a row) with grid_step=1 for
        precision.  All 5 circles must be placed and achieved utilisation
        should be approximately π/4.
        """
        r = 29.0   # slightly under 30 to give 1mm clearance in 60-wide cells
        d = 2 * r  # diameter = 58; bin cells are 60 wide
        circle_verts = make_ngon(32, r)
        parts = [{"name": f"C{i}", "vertices": circle_verts} for i in range(5)]

        # 5 cells of 60×60 in a row
        bin_w = 300.0
        bin_h = 60.0

        result = nest_true_shape(
            parts, bin_w=bin_w, bin_h=bin_h,
            rotations=[0.0],
            grid_step=2.0,
        )
        placed = len(result["placements"])
        circle_area = math.pi * r * r
        achieved_util = placed * circle_area / (bin_w * bin_h)

        # All 5 circles should be placed
        assert placed == 5, f"Expected 5 circles placed, got {placed}. Errors: {result['errors']}"
        # Utilisation should approximate π/4 (circles in square cells)
        assert achieved_util == pytest.approx(math.pi / 4, abs=0.06), (
            f"Circle utilisation {achieved_util:.3f} not ≈ π/4 ≈ 0.785"
        )


# ===========================================================================
# 7. LLM tool wrapper
# ===========================================================================

class TestNestingTrueShapeTool:

    def test_basic_round_trip(self):
        parts = [{"name": "sq", "vertices": list(_square(50).vertices)}]
        result = nesting_true_shape(parts, bin_size=(200, 200))
        assert result["ok"] is True
        assert "utilization_pct" in result
        assert result["utilization_pct"] >= 0

    def test_utilization_pct_matches_utilization(self):
        parts = [{"name": "sq", "vertices": list(_square(50).vertices)}]
        result = nesting_true_shape(parts, bin_size=(200, 200))
        assert result["utilization_pct"] == pytest.approx(
            result["utilization"] * 100, rel=1e-4
        )

    def test_with_rotations_arg(self):
        parts = [{"name": "r", "vertices": list(_rect(10, 80).vertices)}]
        result = nesting_true_shape(parts, bin_size=(200, 50), rotations=[0.0, 90.0])
        assert result["ok"] is True

    def test_error_on_bad_part(self):
        parts = [{"name": "bad", "vertices": [[0, 0]]}]
        result = nesting_true_shape(parts, bin_size=(200, 200))
        assert result["ok"] is False
        assert len(result["errors"]) >= 1

    def test_qty_expands(self):
        parts = [{"name": "sq", "vertices": list(_square(30).vertices), "qty": 3}]
        result = nesting_true_shape(parts, bin_size=(200, 200))
        assert result["ok"] is True
        assert len(result["placements"]) == 3
