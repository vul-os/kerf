"""
test_shop_drawings.py — pytest suite for kerf_woodworking.shop_drawings.

DoD oracles:
  1. panel_shop_drawing returns a ShopDrawing with at least 2 views (front + side).
  2. Front view has outline lines (4 sides) and dimension annotations.
  3. Bore holes appear in the front view when passed.
  4. Edge banding indicators added for banded edges.
  5. cabinet_shop_drawing returns 3 views (front_elevation, side_elevation, plan_view).
  6. Cabinet BOM contains at least 4 parts (sides, top, bottom, back).
  7. Door outlines present in front_elevation for door_count > 0.
  8. shop_drawing_to_dict is JSON-serialisable with all required keys.
  9. Invalid panel dimensions raise ValueError.
  10. Grain arrow present in front view for grain='length' and grain='width'.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_woodworking.shop_drawings import (
    panel_shop_drawing,
    cabinet_shop_drawing,
    shop_drawing_to_dict,
    ShopDrawing,
    View,
    Line,
    Dimension,
    HoleAnnotation,
)


# ---------------------------------------------------------------------------
# DoD oracle 1: panel_shop_drawing views
# ---------------------------------------------------------------------------

class TestPanelShopDrawingViews:
    def test_returns_shop_drawing(self):
        sd = panel_shop_drawing("shelf_1", 800.0, 300.0)
        assert isinstance(sd, ShopDrawing)

    def test_at_least_two_views(self):
        """Front view + side view at minimum."""
        sd = panel_shop_drawing("panel", 600.0, 400.0)
        assert len(sd.views) >= 2

    def test_front_view_present(self):
        sd = panel_shop_drawing("p", 600.0, 400.0)
        view_names = [v.name for v in sd.views]
        assert "front" in view_names

    def test_side_view_present(self):
        sd = panel_shop_drawing("p", 600.0, 400.0)
        view_names = [v.name for v in sd.views]
        assert "side" in view_names

    def test_include_section_adds_view(self):
        sd = panel_shop_drawing("p", 600.0, 400.0, include_section=True)
        view_names = [v.name for v in sd.views]
        assert "section" in view_names

    def test_no_section_without_flag(self):
        sd = panel_shop_drawing("p", 600.0, 400.0, include_section=False)
        view_names = [v.name for v in sd.views]
        assert "section" not in view_names


# ---------------------------------------------------------------------------
# DoD oracle 2: front view outline and dimensions
# ---------------------------------------------------------------------------

class TestPanelFrontView:
    def _front(self, l, w):
        sd = panel_shop_drawing("t", l, w)
        return next(v for v in sd.views if v.name == "front")

    def test_front_view_has_lines(self):
        front = self._front(600.0, 400.0)
        assert len(front.lines) >= 4, "Front view should have at least 4 outline lines"

    def test_front_view_has_dimensions(self):
        front = self._front(600.0, 400.0)
        assert len(front.dimensions) >= 2, "Expected at least 2 dimensions (length + width)"

    def test_dimension_values_match_panel(self):
        """Dimensions should encode the correct mm values."""
        l, w = 750.0, 320.0
        front = self._front(l, w)
        values = [d.value_mm for d in front.dimensions]
        assert l in values, f"Length {l} not in dimension values {values}"
        assert w in values, f"Width {w} not in dimension values {values}"

    def test_outline_covers_panel_extent(self):
        """One line should reach x2=length_mm and one y2=width_mm."""
        l, w = 900.0, 450.0
        front = self._front(l, w)
        xs = [max(li.x1, li.x2) for li in front.lines]
        ys = [max(li.y1, li.y2) for li in front.lines]
        assert any(abs(x - l) < 1.0 for x in xs), f"No line reaches x={l}"
        assert any(abs(y - w) < 1.0 for y in ys), f"No line reaches y={w}"


# ---------------------------------------------------------------------------
# DoD oracle 3: bore holes in front view
# ---------------------------------------------------------------------------

class TestPanelHoles:
    def test_holes_appear_in_front_view(self):
        holes = [
            {"x": 37.0, "y": 100.0, "diameter_mm": 5.0, "depth_mm": 11.0,
             "kind": "shelf_pin", "label": "test hole"},
        ]
        sd = panel_shop_drawing("s", 600.0, 400.0, holes=holes)
        front = next(v for v in sd.views if v.name == "front")
        assert len(front.holes) == 1
        hole = front.holes[0]
        assert abs(hole.cx - 37.0) < 0.1
        assert abs(hole.cy - 100.0) < 0.1
        assert abs(hole.diameter_mm - 5.0) < 0.1

    def test_multiple_holes(self):
        holes = [
            {"x": 37.0, "y": h_y, "diameter_mm": 5.0, "depth_mm": 11.0,
             "kind": "shelf_pin", "label": f"pin {i}"}
            for i, h_y in enumerate([96, 128, 160, 192])
        ]
        sd = panel_shop_drawing("s2", 700.0, 500.0, holes=holes)
        front = next(v for v in sd.views if v.name == "front")
        assert len(front.holes) == 4

    def test_no_holes_when_not_passed(self):
        sd = panel_shop_drawing("s3", 500.0, 300.0)
        front = next(v for v in sd.views if v.name == "front")
        assert len(front.holes) == 0


# ---------------------------------------------------------------------------
# DoD oracle 4: edge banding indicators
# ---------------------------------------------------------------------------

class TestEdgeBanding:
    def test_bottom_edge_banding_adds_line(self):
        """A banded bottom edge adds an indicator line to the front view."""
        sd = panel_shop_drawing("e", 600.0, 400.0, edge_banding={"bottom": "pvc_white"})
        front = next(v for v in sd.views if v.name == "front")
        eb_lines = [l for l in front.lines if "EB:" in l.label]
        assert len(eb_lines) >= 1, "Expected at least one edge banding indicator line"

    def test_all_four_edges_banded(self):
        sd = panel_shop_drawing("e2", 600.0, 400.0, edge_banding={
            "top": "pvc_white", "bottom": "pvc_white",
            "left": "pvc_white", "right": "pvc_white",
        })
        front = next(v for v in sd.views if v.name == "front")
        eb_lines = [l for l in front.lines if "EB:" in l.label]
        assert len(eb_lines) == 4

    def test_no_banding_no_eb_lines(self):
        sd = panel_shop_drawing("e3", 600.0, 400.0, edge_banding={"top": "none"})
        front = next(v for v in sd.views if v.name == "front")
        eb_lines = [l for l in front.lines if "EB:" in l.label]
        assert len(eb_lines) == 0


# ---------------------------------------------------------------------------
# DoD oracle 5: cabinet_shop_drawing views
# ---------------------------------------------------------------------------

class TestCabinetShopDrawingViews:
    def _base_drawing(self):
        return cabinet_shop_drawing("B1", "base", 600.0, 762.0, 610.0)

    def test_returns_shop_drawing(self):
        sd = self._base_drawing()
        assert isinstance(sd, ShopDrawing)

    def test_three_views(self):
        sd = self._base_drawing()
        assert len(sd.views) == 3

    def test_front_elevation_present(self):
        sd = self._base_drawing()
        view_names = [v.name for v in sd.views]
        assert "front_elevation" in view_names

    def test_side_elevation_present(self):
        sd = self._base_drawing()
        view_names = [v.name for v in sd.views]
        assert "side_elevation" in view_names

    def test_plan_view_present(self):
        sd = self._base_drawing()
        view_names = [v.name for v in sd.views]
        assert "plan_view" in view_names

    def test_wall_cabinet_drawing(self):
        sd = cabinet_shop_drawing("W1", "wall", 500.0, 762.0, 330.0)
        assert len(sd.views) == 3

    def test_tall_cabinet_drawing(self):
        sd = cabinet_shop_drawing("T1", "tall", 600.0, 2100.0, 610.0)
        assert len(sd.views) == 3


# ---------------------------------------------------------------------------
# DoD oracle 6: cabinet BOM has parts
# ---------------------------------------------------------------------------

class TestCabinetBOM:
    def test_bom_has_at_least_four_parts(self):
        """Cabinet BOM must include sides, top, bottom, back."""
        sd = cabinet_shop_drawing("B2", "base", 600.0, 762.0, 610.0)
        assert len(sd.bill_of_materials) >= 4

    def test_bom_has_side_part(self):
        sd = cabinet_shop_drawing("B3", "base", 600.0, 762.0, 610.0)
        part_ids = [p["part_id"] for p in sd.bill_of_materials]
        assert any("side" in pid for pid in part_ids)

    def test_bom_has_door_when_door_count_gt_0(self):
        sd = cabinet_shop_drawing("B4", "base", 600.0, 762.0, 610.0, door_count=2)
        part_ids = [p["part_id"] for p in sd.bill_of_materials]
        assert any("door" in pid for pid in part_ids)

    def test_bom_shelf_present_when_shelf_count_gt_0(self):
        sd = cabinet_shop_drawing("B5", "base", 600.0, 762.0, 610.0, shelf_count=3)
        part_ids = [p["part_id"] for p in sd.bill_of_materials]
        assert any("shelf" in pid for pid in part_ids)

    def test_bom_parts_have_required_fields(self):
        sd = cabinet_shop_drawing("B6", "base", 600.0, 762.0, 610.0)
        for part in sd.bill_of_materials:
            assert "part_id" in part
            assert "length_mm" in part
            assert "width_mm" in part
            assert "thickness_mm" in part
            assert "qty" in part


# ---------------------------------------------------------------------------
# DoD oracle 7: door outlines in front elevation
# ---------------------------------------------------------------------------

class TestCabinetDoorOutlines:
    def test_door_lines_in_front_elevation(self):
        """Front elevation should have visible lines for door outlines."""
        sd = cabinet_shop_drawing("D1", "base", 600.0, 762.0, 610.0, door_count=1)
        front = next(v for v in sd.views if v.name == "front_elevation")
        visible_lines = [l for l in front.lines if l.layer == "visible"]
        # At least the cabinet outline (4 lines) + door outline (4 lines)
        assert len(visible_lines) >= 8

    def test_two_doors_more_lines_than_one(self):
        sd1 = cabinet_shop_drawing("D2", "base", 900.0, 762.0, 610.0, door_count=1)
        sd2 = cabinet_shop_drawing("D3", "base", 900.0, 762.0, 610.0, door_count=2)
        front1 = next(v for v in sd1.views if v.name == "front_elevation")
        front2 = next(v for v in sd2.views if v.name == "front_elevation")
        assert len(front2.lines) > len(front1.lines)

    def test_shelf_hidden_lines_present(self):
        sd = cabinet_shop_drawing("S1", "base", 600.0, 762.0, 610.0, shelf_count=2)
        front = next(v for v in sd.views if v.name == "front_elevation")
        hidden = [l for l in front.lines if l.layer == "hidden"]
        assert len(hidden) >= 2  # shelf lines + toe kick


# ---------------------------------------------------------------------------
# DoD oracle 8: shop_drawing_to_dict JSON-serialisable
# ---------------------------------------------------------------------------

class TestShopDrawingDict:
    def test_json_serialisable_panel(self):
        sd = panel_shop_drawing("p", 600.0, 400.0)
        d = shop_drawing_to_dict(sd)
        json.dumps(d)  # must not raise

    def test_json_serialisable_cabinet(self):
        sd = cabinet_shop_drawing("C1", "base", 600.0, 762.0, 610.0)
        d = shop_drawing_to_dict(sd)
        json.dumps(d)

    def test_dict_has_expected_keys(self):
        sd = panel_shop_drawing("p2", 400.0, 300.0)
        d = shop_drawing_to_dict(sd)
        for key in ("part_id", "part_description", "views", "bill_of_materials",
                    "notes", "revision"):
            assert key in d

    def test_views_are_list(self):
        sd = panel_shop_drawing("p3", 500.0, 300.0)
        d = shop_drawing_to_dict(sd)
        assert isinstance(d["views"], list)
        assert len(d["views"]) >= 2

    def test_view_dict_has_geometry(self):
        sd = panel_shop_drawing("p4", 600.0, 400.0)
        d = shop_drawing_to_dict(sd)
        view = d["views"][0]
        assert "lines" in view
        assert "dimensions" in view
        assert "holes" in view
        assert "arcs" in view

    def test_line_coords_are_numbers(self):
        sd = panel_shop_drawing("p5", 700.0, 350.0)
        d = shop_drawing_to_dict(sd)
        front = next(v for v in d["views"] if v["name"] == "front")
        for line in front["lines"]:
            for coord in ("x1", "y1", "x2", "y2"):
                assert isinstance(line[coord], (int, float)), (
                    f"Line coord {coord} is not a number: {line[coord]}"
                )


# ---------------------------------------------------------------------------
# DoD oracle 9: invalid dimensions raise
# ---------------------------------------------------------------------------

class TestInvalidInputs:
    def test_invalid_panel_length_raises(self):
        with pytest.raises(ValueError):
            panel_shop_drawing("bad", -100.0, 400.0)

    def test_invalid_panel_width_raises(self):
        with pytest.raises(ValueError):
            panel_shop_drawing("bad", 600.0, 0.0)

    def test_invalid_cabinet_type_raises(self):
        with pytest.raises(ValueError):
            cabinet_shop_drawing("bad", "upper", 600.0, 762.0, 610.0)

    def test_invalid_cabinet_dimensions_raise(self):
        with pytest.raises(ValueError):
            cabinet_shop_drawing("bad", "base", -100.0, 762.0, 610.0)


# ---------------------------------------------------------------------------
# DoD oracle 10: grain arrow present
# ---------------------------------------------------------------------------

class TestGrainArrow:
    def test_grain_length_arrow_in_front_view(self):
        sd = panel_shop_drawing("g1", 800.0, 300.0, grain_direction="length")
        front = next(v for v in sd.views if v.name == "front")
        grain_lines = [l for l in front.lines if "grain" in l.label]
        assert len(grain_lines) >= 1, "Expected grain arrow for grain='length'"

    def test_grain_width_arrow_in_front_view(self):
        sd = panel_shop_drawing("g2", 800.0, 300.0, grain_direction="width")
        front = next(v for v in sd.views if v.name == "front")
        grain_lines = [l for l in front.lines if "grain" in l.label]
        assert len(grain_lines) >= 1, "Expected grain arrow for grain='width'"
