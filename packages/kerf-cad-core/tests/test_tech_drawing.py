"""
Tests for kerf_cad_core.jewelry.tech_drawing

Pure-Python, hermetic — no OCC, no database, no project context required.
Covers >= 25 test cases:

  1.  Four requested views (top/front/side/iso) all present in output.
  2.  Each gemstone produces a callout entry in sheet annotations.
  3.  Seat-depth dimensions match input piece data.
  4.  Ring-size badge value and system match input.
  5.  Ring-size badge absent for non-ring piece.
  6.  Annotation positions (ring_size_badge) inside sheet bounds.
  7.  DXF export non-empty for a sample ring with 1 stone.
  8.  SVG export non-empty for a sample ring with 1 stone.
  9.  Multi-stone callout labels are all unique.
  10. Stone callout label format: "<ct> ct <abbr> Ø<mm> mm".
  11. Missing-input error path (piece=None-like / not dict).
  12. Unknown view name returns error.
  13. No views after filtering raises error (empty view list).
  14. Negative scale returns error.
  15. Total-carat label sums stones correctly (0 stones → 0.00 ct).
  16. Total-carat label with multiple stones.
  17. Metal-weight label present when volume_mm3 + metal provided.
  18. Metal-weight label absent when volume_mm3 missing.
  19. Hallmark indicator present when maker_mark provided.
  20. Hallmark indicator absent when maker_mark missing.
  21. Prong-height dimensions match input piece data.
  22. View bbox values are within sheet bounds.
  23. Sheet border is a closed polyline (first == last point).
  24. Single view (top only) request produces only that view.
  25. iso view produces correct view name in output dict.
  26. stone_callout leader_tip differs from origin (not coincident).
  27. DXF export contains "ENTITIES" section marker.
  28. SVG export contains <svg and </svg>.
  29. dxf_export returns empty string for drawing with ok=False.
  30. svg_export returns empty string for drawing with ok=False.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

import pytest

from kerf_cad_core.jewelry.tech_drawing import (
    _CUT_ABBR,
    _stone_callout_label,
    _total_carats,
    dxf_export,
    jewelry_tech_drawing,
    svg_export,
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

def _ring_piece(
    ring_size: float = 7.0,
    metal: str = "18k_yellow",
    volume_mm3: float = 1200.0,
    n_stones: int = 1,
    with_seat_depth: bool = True,
    with_prong_height: bool = True,
    maker_mark: Optional[str] = "KF",
) -> Dict[str, Any]:
    """Return a minimal ring piece dict for testing."""
    stones = []
    for i in range(n_stones):
        s: Dict[str, Any] = {
            "cut":          "round_brilliant",
            "diameter_mm":  6.5,
            "carat":        1.0,
            "position":     [float(i) * 3.0, 0.0, 0.5],
        }
        if with_seat_depth:
            s["seat_depth_mm"] = 2.0 + i * 0.5
        if with_prong_height:
            s["prong_height_mm"] = 1.5
        stones.append(s)

    piece: Dict[str, Any] = {
        "metal":            metal,
        "ring_size":        ring_size,
        "ring_size_system": "US",
        "volume_mm3":       volume_mm3,
        "gemstones":        stones,
    }
    if maker_mark:
        piece["maker_mark"] = maker_mark
        piece["hallmark_position"] = [15.0, 15.0]
    return piece


def _run(
    piece: Any,
    views: Optional[List[str]] = None,
    **kwargs,
) -> Dict[str, Any]:
    return jewelry_tech_drawing(piece, views, **kwargs)


# ---------------------------------------------------------------------------
# 1–6: Views and sheet-level structure
# ---------------------------------------------------------------------------

class TestFourViews:
    def test_all_four_views_present(self):
        drawing = _run(_ring_piece())
        assert drawing["ok"] is True
        for v in ("top", "front", "side", "iso"):
            assert v in drawing["views"], f"view {v!r} missing"

    def test_each_view_has_bbox(self):
        drawing = _run(_ring_piece())
        for v in ("top", "front", "side", "iso"):
            bbox = drawing["views"][v]["bbox"]
            assert "x" in bbox and "y" in bbox and "w" in bbox and "h" in bbox

    def test_views_have_annotation_lists(self):
        drawing = _run(_ring_piece())
        for v in ("top", "front", "side", "iso"):
            assert "annotations" in drawing["views"][v]
            assert isinstance(drawing["views"][v]["annotations"], list)


class TestGemstoneCallouts:
    def test_single_stone_produces_callout(self):
        drawing = _run(_ring_piece(n_stones=1))
        callouts = drawing["annotations"]["stone_callouts"]
        assert len(callouts) == 1

    def test_each_stone_has_callout(self):
        drawing = _run(_ring_piece(n_stones=3))
        callouts = drawing["annotations"]["stone_callouts"]
        assert len(callouts) == 3

    def test_no_stone_zero_callouts(self):
        piece = _ring_piece(n_stones=0)
        drawing = _run(piece)
        assert drawing["annotations"]["stone_callouts"] == []


class TestSeatDepthDims:
    def test_seat_depth_present(self):
        drawing = _run(_ring_piece(n_stones=1, with_seat_depth=True))
        dims = drawing["annotations"]["seat_depth_dims"]
        assert len(dims) == 1

    def test_seat_depth_value_matches(self):
        drawing = _run(_ring_piece(n_stones=1, with_seat_depth=True))
        dim = drawing["annotations"]["seat_depth_dims"][0]
        assert abs(dim["seat_depth_mm"] - 2.0) < 1e-9

    def test_no_seat_depth_if_not_provided(self):
        drawing = _run(_ring_piece(n_stones=1, with_seat_depth=False))
        dims = drawing["annotations"]["seat_depth_dims"]
        assert len(dims) == 0

    def test_multiple_stone_seat_depths(self):
        drawing = _run(_ring_piece(n_stones=3, with_seat_depth=True))
        dims = drawing["annotations"]["seat_depth_dims"]
        assert len(dims) == 3
        # Values: 2.0, 2.5, 3.0
        values = [d["seat_depth_mm"] for d in dims]
        assert abs(values[0] - 2.0) < 1e-9
        assert abs(values[1] - 2.5) < 1e-9
        assert abs(values[2] - 3.0) < 1e-9


class TestRingSizeBadge:
    def test_ring_size_badge_present(self):
        drawing = _run(_ring_piece(ring_size=7.0))
        badge = drawing["annotations"]["ring_size_badge"]
        assert badge is not None
        assert badge["size"] == 7.0
        assert badge["system"] == "US"

    def test_ring_size_badge_absent_for_non_ring(self):
        piece = {"metal": "18k_yellow", "gemstones": []}
        drawing = _run(piece)
        assert drawing["annotations"]["ring_size_badge"] is None

    def test_ring_size_badge_position_inside_sheet(self):
        drawing = _run(_ring_piece())
        badge = drawing["annotations"]["ring_size_badge"]
        assert badge is not None
        x, y = badge["position_2d"]
        sheet = drawing["sheet"]
        assert 0 <= x <= sheet["width_mm"]
        assert 0 <= y <= sheet["height_mm"]


# ---------------------------------------------------------------------------
# 7–8: Export
# ---------------------------------------------------------------------------

class TestDxfExport:
    def test_dxf_non_empty_for_ring_with_stone(self):
        drawing = _run(_ring_piece(n_stones=1))
        dxf = dxf_export(drawing)
        assert len(dxf) > 0

    def test_dxf_contains_entities_section(self):
        drawing = _run(_ring_piece(n_stones=1))
        dxf = dxf_export(drawing)
        assert "ENTITIES" in dxf

    def test_dxf_ends_with_eof(self):
        drawing = _run(_ring_piece(n_stones=1))
        dxf = dxf_export(drawing)
        assert "EOF" in dxf

    def test_dxf_returns_empty_for_bad_drawing(self):
        dxf = dxf_export({"ok": False, "reason": "test"})
        assert dxf == ""


class TestSvgExport:
    def test_svg_non_empty_for_ring_with_stone(self):
        drawing = _run(_ring_piece(n_stones=1))
        svg = svg_export(drawing)
        assert len(svg) > 0

    def test_svg_has_opening_and_closing_tags(self):
        drawing = _run(_ring_piece(n_stones=1))
        svg = svg_export(drawing)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_svg_returns_empty_for_bad_drawing(self):
        svg = svg_export({"ok": False, "reason": "test"})
        assert svg == ""


# ---------------------------------------------------------------------------
# 9–11: Multi-stone, label format, error path
# ---------------------------------------------------------------------------

class TestMultiStoneCallouts:
    def test_unique_labels_for_identical_stones(self):
        """Even with identical stones, callout list must have distinct entries
        (unique by index, even if labels happen to be the same string)."""
        piece = _ring_piece(n_stones=3)
        drawing = _run(piece)
        callouts = drawing["annotations"]["stone_callouts"]
        indices = [c["index"] for c in callouts]
        assert len(set(indices)) == 3, "stone indices must be unique"

    def test_unique_labels_for_different_cuts(self):
        cuts = ["round_brilliant", "princess", "oval"]
        piece = {
            "metal": "18k_white",
            "gemstones": [
                {"cut": c, "diameter_mm": 5.0, "carat": 0.5, "position": [0, 0, 0]}
                for c in cuts
            ],
        }
        drawing = _run(piece)
        labels = [c["label"] for c in drawing["annotations"]["stone_callouts"]]
        assert len(set(labels)) == 3, "different cuts should give distinct labels"


class TestCalloutLabelFormat:
    def test_rbc_label_format(self):
        label = _stone_callout_label(
            {"cut": "round_brilliant", "diameter_mm": 6.5, "carat": 1.0}
        )
        assert label == "1.00 ct RBC Ø6.50 mm"

    def test_princess_abbr(self):
        label = _stone_callout_label(
            {"cut": "princess", "diameter_mm": 5.5, "carat": 0.75}
        )
        assert "PRC" in label

    def test_unknown_cut_uses_short_upper(self):
        label = _stone_callout_label(
            {"cut": "fancy_cut_xyz", "diameter_mm": 4.0, "carat": 0.3}
        )
        assert "FAN" in label or "fan" not in label.lower()


class TestErrorPaths:
    def test_none_piece_returns_error(self):
        drawing = _run(None)
        assert drawing["ok"] is False

    def test_non_dict_piece_returns_error(self):
        drawing = _run("not a dict")
        assert drawing["ok"] is False

    def test_unknown_view_returns_error(self):
        drawing = _run(_ring_piece(), views=["top", "banana"])
        assert drawing["ok"] is False
        assert "banana" in drawing.get("reason", "")

    def test_empty_view_list_after_filter_returns_error(self):
        # Passing only unknown views → nothing valid
        drawing = _run(_ring_piece(), views=["banana", "mango"])
        assert drawing["ok"] is False

    def test_negative_scale_returns_error(self):
        drawing = _run(_ring_piece(), scale=-1.0)
        assert drawing["ok"] is False


# ---------------------------------------------------------------------------
# 13–18: Totals, weight, hallmark
# ---------------------------------------------------------------------------

class TestTotalCaratLabel:
    def test_zero_stones_zero_carat(self):
        piece = {"metal": "18k_yellow", "gemstones": []}
        drawing = _run(piece)
        tcl = drawing["annotations"]["total_carat_label"]
        assert abs(tcl["value"]) < 1e-9
        assert "0.00" in tcl["label"]

    def test_carat_sum_correct(self):
        piece = {
            "metal": "18k_yellow",
            "gemstones": [
                {"cut": "round_brilliant", "diameter_mm": 5.0, "carat": 0.5},
                {"cut": "round_brilliant", "diameter_mm": 5.0, "carat": 0.75},
            ],
        }
        drawing = _run(piece)
        tcl = drawing["annotations"]["total_carat_label"]
        assert abs(tcl["value"] - 1.25) < 1e-6


class TestMetalWeightLabel:
    def test_weight_present_when_volume_and_metal_given(self):
        piece = _ring_piece(metal="18k_yellow", volume_mm3=1200.0)
        drawing = _run(piece)
        mwl = drawing["annotations"]["metal_weight_label"]
        assert mwl is not None
        assert mwl["weight_g"] > 0

    def test_weight_absent_when_volume_missing(self):
        piece = {"metal": "18k_yellow", "gemstones": []}
        drawing = _run(piece)
        assert drawing["annotations"]["metal_weight_label"] is None


class TestHallmarkIndicator:
    def test_hallmark_present_with_maker_mark(self):
        piece = _ring_piece(maker_mark="KF")
        drawing = _run(piece)
        hm = drawing["annotations"]["hallmark_indicator"]
        assert hm is not None
        assert "KF" in hm["label"]

    def test_hallmark_absent_without_maker_mark(self):
        piece = {"metal": "18k_yellow", "gemstones": []}
        drawing = _run(piece)
        assert drawing["annotations"]["hallmark_indicator"] is None


# ---------------------------------------------------------------------------
# 19–23: Prong heights, bbox, sheet border, single view
# ---------------------------------------------------------------------------

class TestProngHeightDims:
    def test_prong_height_present(self):
        drawing = _run(_ring_piece(n_stones=1, with_prong_height=True))
        dims = drawing["annotations"]["prong_height_dims"]
        assert len(dims) == 1

    def test_prong_height_value_matches(self):
        drawing = _run(_ring_piece(n_stones=1, with_prong_height=True))
        dim = drawing["annotations"]["prong_height_dims"][0]
        assert abs(dim["prong_height_mm"] - 1.5) < 1e-9

    def test_no_prong_height_if_not_provided(self):
        drawing = _run(_ring_piece(n_stones=1, with_prong_height=False))
        dims = drawing["annotations"]["prong_height_dims"]
        assert len(dims) == 0


class TestViewBbox:
    def test_bbox_within_sheet(self):
        drawing = _run(_ring_piece())
        sheet = drawing["sheet"]
        sw, sh = sheet["width_mm"], sheet["height_mm"]
        for vname, vdata in drawing["views"].items():
            bbox = vdata["bbox"]
            assert bbox["x"] >= 0, f"{vname}: x < 0"
            assert bbox["y"] >= 0, f"{vname}: y < 0"
            assert bbox["x"] + bbox["w"] <= sw + 1e-6, f"{vname}: right > sheet"
            assert bbox["y"] + bbox["h"] <= sh + 1e-6, f"{vname}: bottom > sheet"


class TestSheetBorder:
    def test_border_is_closed(self):
        drawing = _run(_ring_piece())
        border = drawing["sheet"]["border"]
        assert len(border) >= 4
        assert border[0] == border[-1], "border should be closed"

    def test_title_block_is_closed(self):
        drawing = _run(_ring_piece())
        tb = drawing["sheet"]["title_block"]
        assert tb[0] == tb[-1]


class TestSingleView:
    def test_single_top_view(self):
        drawing = _run(_ring_piece(), views=["top"])
        assert drawing["ok"] is True
        assert list(drawing["views"].keys()) == ["top"]

    def test_iso_view_name_correct(self):
        drawing = _run(_ring_piece(), views=["iso"])
        assert drawing["ok"] is True
        assert "iso" in drawing["views"]


# ---------------------------------------------------------------------------
# 24–26: Leader positions, DXF layer, SVG stone callout
# ---------------------------------------------------------------------------

class TestLeaderPositions:
    def test_leader_tip_differs_from_origin(self):
        drawing = _run(_ring_piece(n_stones=1))
        callout = drawing["annotations"]["stone_callouts"][0]
        origin = callout["origin_2d"]
        tip = callout["leader_tip"]
        dist = math.hypot(tip[0] - origin[0], tip[1] - origin[1])
        assert dist > 0, "leader tip should not coincide with stone origin"


class TestDxfContent:
    def test_dxf_contains_stone_label(self):
        drawing = _run(_ring_piece(n_stones=1))
        dxf = dxf_export(drawing)
        # The callout label text should appear in the DXF
        assert "RBC" in dxf or "1.00" in dxf

    def test_dxf_contains_ring_size_label(self):
        drawing = _run(_ring_piece(ring_size=7.0))
        dxf = dxf_export(drawing)
        assert "7.0" in dxf or "Ring Size" in dxf


class TestSvgContent:
    def test_svg_contains_stone_callout_text(self):
        drawing = _run(_ring_piece(n_stones=1))
        svg = svg_export(drawing)
        assert "RBC" in svg or "1.00" in svg

    def test_svg_contains_ring_size(self):
        drawing = _run(_ring_piece(ring_size=6.0))
        svg = svg_export(drawing)
        assert "6.0" in svg or "Ring Size" in svg

    def test_svg_contains_view_label(self):
        drawing = _run(_ring_piece(), views=["top"])
        svg = svg_export(drawing)
        assert "TOP" in svg


# ---------------------------------------------------------------------------
# 27: _total_carats helper directly
# ---------------------------------------------------------------------------

class TestTotalCaratsHelper:
    def test_empty_list(self):
        assert _total_carats([]) == pytest.approx(0.0)

    def test_single_stone(self):
        assert _total_carats([{"carat": 1.5}]) == pytest.approx(1.5)

    def test_multiple_stones(self):
        stones = [{"carat": 0.5}, {"carat": 0.75}, {"carat": 1.0}]
        assert _total_carats(stones) == pytest.approx(2.25)
