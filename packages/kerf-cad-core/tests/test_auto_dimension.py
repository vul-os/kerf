"""
Tests for kerf_cad_core.drawings.auto_dimension

Pure-Python, hermetic — no OCC, no database, no project context required.
Covers >= 25 test cases:

 1.  Four views generated (front/top/right/iso) all present in output.
 2.  Each view has a non-empty "label" key.
 3.  Each view has a bbox dict with x/y/w/h.
 4.  Overall length dimension placed on front view.
 5.  Overall height dimension placed on front view.
 6.  Overall width dimension placed on top view.
 7.  Hole-table row count equals unique-diameter count, not raw hole count.
 8.  Hole-table qty sums to total hole count for each diameter group.
 9.  Thread callout label contains M-spec (e.g. "M6").
10.  Thread callout label contains pitch value.
11.  Thread callout label contains depth DP suffix when depth provided.
12.  Fillet R callout label contains "R" prefix.
13.  Fillet callout count matches unique radii.
14.  Sheet size A3 → width_mm=420, height_mm=297.
15.  Sheet border is a closed polyline (first == last point).
16.  Sheet title_block is a closed polyline.
17.  DXF export returns non-empty string.
18.  DXF export contains "ENTITIES" section marker.
19.  DXF export returns empty string for drawing with ok=False.
20.  SVG export returns non-empty string.
21.  SVG export contains <svg and </svg>.
22.  SVG export contains view label (e.g. "FRONT").
23.  SVG export returns empty string for drawing with ok=False.
24.  GD&T frame appears (at least one frame generated for valid bbox).
25.  GD&T frame label contains parallelism or perpendicularity symbol.
26.  GD&T position tolerance present when >= 2 holes.
27.  Missing-input error path (part not a dict).
28.  Unknown sheet size returns error.
29.  Part with no bbox still produces ok drawing (graceful degradation).
30.  Section note present when internal_features=True.
31.  Section note absent when internal_features=False or omitted.
32.  Title block contains part name.
33.  Title block contains material.
34.  meta.scale is a positive float.
35.  meta.view_names is a list of 4 view names.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest

from kerf_cad_core.drawings.auto_dimension import (
    auto_dimension,
    dxf_export,
    svg_export,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bracket() -> Dict[str, Any]:
    """Minimal bracket part with holes, fillets, and bbox."""
    return {
        "name": "Bracket A",
        "material": "Steel 1045",
        "revision": "A",
        "drawn_by": "Eng",
        "project": "TestProj",
        "bbox": {"length": 100.0, "width": 50.0, "height": 30.0},
        "holes": [
            {
                "diameter_mm": 6.0,
                "depth_mm": 20.0,
                "x_mm": 20.0, "y_mm": 15.0, "z_mm": 30.0,
                "threaded": True,
                "thread_pitch_mm": 1.0,
                "countersunk": False,
                "counterbored": False,
            },
            {
                "diameter_mm": 6.0,
                "depth_mm": 20.0,
                "x_mm": 80.0, "y_mm": 15.0, "z_mm": 30.0,
                "threaded": True,
                "thread_pitch_mm": 1.0,
                "countersunk": False,
                "counterbored": False,
            },
            {
                "diameter_mm": 10.0,
                "depth_mm": None,
                "x_mm": 50.0, "y_mm": 25.0, "z_mm": 30.0,
                "threaded": False,
                "thread_pitch_mm": None,
                "countersunk": True,
                "counterbored": False,
            },
        ],
        "fillets": [
            {"radius_mm": 3.0, "count": 4, "face": "edge"},
            {"radius_mm": 1.5, "count": 2, "face": "top"},
        ],
        "internal_features": False,
    }


def _run(part: Any = None, sheet: str = "A3") -> Dict[str, Any]:
    if part is None:
        part = _bracket()
    return auto_dimension(part, sheet=sheet)


# ---------------------------------------------------------------------------
# 1–3: Views structure
# ---------------------------------------------------------------------------

class TestViewsPresence:
    def test_four_views_generated(self):
        d = _run()
        assert d["ok"] is True
        for v in ("front", "top", "right", "iso"):
            assert v in d["views"], f"missing view: {v}"

    def test_each_view_has_label(self):
        d = _run()
        for v in ("front", "top", "right", "iso"):
            assert "label" in d["views"][v]
            assert isinstance(d["views"][v]["label"], str)
            assert len(d["views"][v]["label"]) > 0

    def test_each_view_has_bbox(self):
        d = _run()
        for v in ("front", "top", "right", "iso"):
            bbox = d["views"][v]["bbox"]
            for key in ("x", "y", "w", "h"):
                assert key in bbox, f"view {v} bbox missing {key}"


# ---------------------------------------------------------------------------
# 4–6: Overall dimensions on correct views
# ---------------------------------------------------------------------------

class TestOverallDimensions:
    def test_length_dim_on_front_view(self):
        d = _run()
        front_dims = d["views"]["front"]["dimensions"]
        labels = [dim["label"] for dim in front_dims]
        assert any("L=" in lb for lb in labels), f"no length dim on front: {labels}"

    def test_height_dim_on_front_view(self):
        d = _run()
        front_dims = d["views"]["front"]["dimensions"]
        labels = [dim["label"] for dim in front_dims]
        assert any("H=" in lb for lb in labels), f"no height dim on front: {labels}"

    def test_width_dim_on_top_view(self):
        d = _run()
        top_dims = d["views"]["top"]["dimensions"]
        labels = [dim["label"] for dim in top_dims]
        assert any("W=" in lb for lb in labels), f"no width dim on top: {labels}"

    def test_overall_dims_in_annotations(self):
        d = _run()
        overall = d["annotations"]["overall_dims"]
        assert len(overall) >= 4, "expected at least L,H on front and L,W on top"

    def test_dim_value_matches_bbox(self):
        d = _run()
        front_dims = d["views"]["front"]["dimensions"]
        l_dim = next((dm for dm in front_dims if "L=" in dm.get("label", "")), None)
        assert l_dim is not None
        assert abs(l_dim["value_mm"] - 100.0) < 1e-6


# ---------------------------------------------------------------------------
# 7–8: Hole table
# ---------------------------------------------------------------------------

class TestHoleTable:
    def test_hole_table_row_count_equals_unique_diameters(self):
        d = _run()
        table = d["annotations"]["hole_table"]
        # bracket has diameters 6.0 (×2, threaded) and 10.0 (×1) → 2 unique groups
        assert len(table) == 2

    def test_hole_table_qty_sums_to_total(self):
        d = _run()
        table = d["annotations"]["hole_table"]
        total_qty = sum(row["qty"] for row in table)
        assert total_qty == 3  # 3 holes total

    def test_hole_table_row_has_required_keys(self):
        d = _run()
        for row in d["annotations"]["hole_table"]:
            for key in ("label", "diameter_mm", "qty", "position_2d"):
                assert key in row, f"hole table row missing {key}"

    def test_no_holes_gives_empty_table(self):
        part = {**_bracket(), "holes": []}
        d = _run(part)
        assert d["annotations"]["hole_table"] == []


# ---------------------------------------------------------------------------
# 9–11: Thread callouts
# ---------------------------------------------------------------------------

class TestThreadCallouts:
    def test_thread_callout_present(self):
        d = _run()
        calls = d["annotations"]["thread_callouts"]
        assert len(calls) >= 1

    def test_thread_callout_contains_m_spec(self):
        d = _run()
        calls = d["annotations"]["thread_callouts"]
        labels = [c["label"] for c in calls]
        assert any("M6" in lb for lb in labels), f"no M6 in thread callouts: {labels}"

    def test_thread_callout_contains_pitch(self):
        d = _run()
        calls = d["annotations"]["thread_callouts"]
        labels = [c["label"] for c in calls]
        assert any("1.0" in lb for lb in labels), f"no pitch 1.0 in: {labels}"

    def test_thread_callout_contains_dp_when_depth_given(self):
        d = _run()
        calls = d["annotations"]["thread_callouts"]
        labels = [c["label"] for c in calls]
        assert any("DP" in lb for lb in labels), f"no DP suffix in: {labels}"

    def test_no_threads_gives_empty_callouts(self):
        part = {**_bracket(), "holes": [
            {"diameter_mm": 8.0, "x_mm": 10.0, "y_mm": 10.0, "z_mm": 0.0,
             "threaded": False, "depth_mm": None,
             "countersunk": False, "counterbored": False}
        ]}
        d = _run(part)
        assert d["annotations"]["thread_callouts"] == []


# ---------------------------------------------------------------------------
# 12–13: Fillet callouts
# ---------------------------------------------------------------------------

class TestFilletCallouts:
    def test_fillet_callout_label_has_r_prefix(self):
        d = _run()
        calls = d["annotations"]["fillet_callouts"]
        assert len(calls) >= 1
        for c in calls:
            assert c["label"].startswith("R"), f"fillet label missing R prefix: {c['label']}"

    def test_fillet_callout_count_matches_unique_radii(self):
        d = _run()
        calls = d["annotations"]["fillet_callouts"]
        # bracket has radii 3.0 and 1.5 → 2 unique
        assert len(calls) == 2

    def test_no_fillets_gives_empty_callouts(self):
        part = {**_bracket(), "fillets": []}
        d = _run(part)
        assert d["annotations"]["fillet_callouts"] == []


# ---------------------------------------------------------------------------
# 14–16: Sheet dimensions and borders
# ---------------------------------------------------------------------------

class TestSheetGeometry:
    def test_a3_width_and_height(self):
        d = _run(sheet="A3")
        s = d["sheet"]
        assert abs(s["width_mm"] - 420.0) < 1e-6
        assert abs(s["height_mm"] - 297.0) < 1e-6

    def test_sheet_border_is_closed(self):
        d = _run()
        border = d["sheet"]["border"]
        assert len(border) >= 4
        assert border[0] == border[-1], "border not closed"

    def test_title_block_border_is_closed(self):
        d = _run()
        tb = d["sheet"]["title_block"]
        assert len(tb) >= 4
        assert tb[0] == tb[-1], "title_block not closed"

    def test_a4_sheet_size(self):
        d = _run(sheet="A4")
        s = d["sheet"]
        assert abs(s["width_mm"] - 297.0) < 1e-6
        assert abs(s["height_mm"] - 210.0) < 1e-6


# ---------------------------------------------------------------------------
# 17–23: DXF and SVG export
# ---------------------------------------------------------------------------

class TestDxfExport:
    def test_dxf_non_empty(self):
        d = _run()
        dxf = dxf_export(d)
        assert len(dxf) > 0

    def test_dxf_contains_entities_section(self):
        d = _run()
        dxf = dxf_export(d)
        assert "ENTITIES" in dxf

    def test_dxf_returns_empty_for_bad_drawing(self):
        dxf = dxf_export({"ok": False, "reason": "test"})
        assert dxf == ""

    def test_dxf_contains_view_label(self):
        d = _run()
        dxf = dxf_export(d)
        assert "FRONT" in dxf or "VIEWNOTE" in dxf or "VIEWLABEL" in dxf

    def test_dxf_contains_thread_callout_text(self):
        d = _run()
        dxf = dxf_export(d)
        # "M6" should appear in the DXF TEXT entity
        assert "M6" in dxf

    def test_dxf_ends_with_eof(self):
        d = _run()
        dxf = dxf_export(d)
        assert dxf.strip().endswith("EOF")


class TestSvgExport:
    def test_svg_non_empty(self):
        d = _run()
        svg = svg_export(d)
        assert len(svg) > 0

    def test_svg_has_opening_and_closing_tags(self):
        d = _run()
        svg = svg_export(d)
        assert "<svg" in svg
        assert "</svg>" in svg

    def test_svg_contains_front_label(self):
        d = _run()
        svg = svg_export(d)
        assert "FRONT" in svg

    def test_svg_returns_empty_for_bad_drawing(self):
        svg = svg_export({"ok": False, "reason": "test"})
        assert svg == ""

    def test_svg_contains_fillet_callout(self):
        d = _run()
        svg = svg_export(d)
        assert "R3" in svg or "R1" in svg

    def test_svg_contains_thread_callout(self):
        d = _run()
        svg = svg_export(d)
        assert "M6" in svg


# ---------------------------------------------------------------------------
# 24–26: GD&T frames
# ---------------------------------------------------------------------------

class TestGdtFrames:
    def test_gdt_frame_present_for_valid_bbox(self):
        d = _run()
        frames = d["annotations"]["gdt_frames"]
        assert len(frames) >= 1

    def test_gdt_frame_label_contains_symbol(self):
        d = _run()
        frames = d["annotations"]["gdt_frames"]
        labels = [f["label"] for f in frames]
        # at least one of parallelism (//) or perpendicularity (⊥)
        assert any("//" in lb or "⊥" in lb for lb in labels), f"no GD&T symbol in: {labels}"

    def test_gdt_position_tol_present_for_multiple_holes(self):
        d = _run()
        frames = d["annotations"]["gdt_frames"]
        labels = [f["label"] for f in frames]
        # position symbol ⊕ or positional tolerance
        assert any("⊕" in lb or "0.10" in lb for lb in labels), f"no position tol in: {labels}"

    def test_gdt_frame_has_datum(self):
        d = _run()
        for frame in d["annotations"]["gdt_frames"]:
            assert "datum" in frame


# ---------------------------------------------------------------------------
# 27–28: Error paths
# ---------------------------------------------------------------------------

class TestErrorPaths:
    def test_non_dict_part_returns_error(self):
        d = auto_dimension("not a dict")
        assert d["ok"] is False

    def test_none_part_returns_error(self):
        d = auto_dimension(None)
        assert d["ok"] is False

    def test_unknown_sheet_size_returns_error(self):
        d = auto_dimension(_bracket(), sheet="Z99")
        assert d["ok"] is False
        assert "Z99" in d.get("reason", "")

    def test_list_part_returns_error(self):
        d = auto_dimension([1, 2, 3])
        assert d["ok"] is False


# ---------------------------------------------------------------------------
# 29: No bbox — graceful degradation
# ---------------------------------------------------------------------------

class TestNoBbox:
    def test_part_without_bbox_still_ok(self):
        part = {"name": "NoBox", "material": "Al"}
        d = _run(part)
        assert d["ok"] is True

    def test_part_without_bbox_has_four_views(self):
        part = {"name": "NoBox"}
        d = _run(part)
        for v in ("front", "top", "right", "iso"):
            assert v in d["views"]

    def test_no_bbox_overall_dims_empty(self):
        part = {"name": "NoBox"}
        d = _run(part)
        # No bbox → no L/H/W dims
        front_dims = d["views"]["front"]["dimensions"]
        assert len(front_dims) == 0


# ---------------------------------------------------------------------------
# 30–31: Section note
# ---------------------------------------------------------------------------

class TestSectionNote:
    def test_section_note_present_when_internal_features(self):
        part = {**_bracket(), "internal_features": True}
        d = _run(part)
        assert d["annotations"]["section_note"] is not None
        assert isinstance(d["annotations"]["section_note"], str)
        assert len(d["annotations"]["section_note"]) > 0

    def test_section_note_absent_when_no_internal_features(self):
        d = _run()
        assert d["annotations"]["section_note"] is None

    def test_section_note_absent_when_key_missing(self):
        part = {k: v for k, v in _bracket().items() if k != "internal_features"}
        d = _run(part)
        assert d["annotations"]["section_note"] is None


# ---------------------------------------------------------------------------
# 32–35: Title block and meta
# ---------------------------------------------------------------------------

class TestTitleBlock:
    def test_title_block_contains_part_name(self):
        d = _run()
        tb = d["annotations"]["title_block"]
        assert "Bracket A" in tb["name"]

    def test_title_block_contains_material(self):
        d = _run()
        tb = d["annotations"]["title_block"]
        assert "Steel" in tb["material"]

    def test_meta_scale_is_positive(self):
        d = _run()
        assert isinstance(d["meta"]["scale"], float)
        assert d["meta"]["scale"] > 0

    def test_meta_view_names_has_four(self):
        d = _run()
        vnames = d["meta"]["view_names"]
        assert isinstance(vnames, list)
        assert len(vnames) == 4
        for v in ("front", "top", "right", "iso"):
            assert v in vnames
