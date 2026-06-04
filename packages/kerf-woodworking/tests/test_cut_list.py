"""
test_cut_list.py — pytest suite for kerf_woodworking.cabinet_cut_list.

DoD coverage:
  1.  Cut-list for 5 base cabinets returns ≥1 item per cabinet.
  2.  Items are grouped by part_id (aggregation works).
  3.  Total sheet count ≥ 1 per material.
  4.  Waste percentage is between 0 and 100.
  5.  Estimated cost > 0.
  6.  Edge banding total > 0 when edge_banding != 'none'.
  7.  CutListReport has all required fields.
  8.  Single cabinet returns at least 4 parts (sides, top, bottom, back).
  9.  Door count propagates to cut list.
  10. Shelf count propagates to cut list.
  11. Face frame generates stile and rail parts.
  12. Empty placements returns empty report.

References: KCMA 2021 Cabinet Standards; Stanley (2010).
"""

from __future__ import annotations

import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_woodworking.cabinet_cut_list import (
    CabinetPlacement,
    CutListItem,
    CutListReport,
    generate_cut_list,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_base_cab(cabinet_id: str, width_mm: float = 600.0) -> CabinetPlacement:
    return CabinetPlacement(
        cabinet_id=cabinet_id,
        cabinet_type="base",
        width_mm=width_mm,
        height_mm=762.0,
        depth_mm=610.0,
        material='birch_ply_3/4"',
        back_material='birch_ply_1/4"',
        door_count=1,
        shelf_count=1,
        edge_banding="pvc_white",
        include_face_frame=False,
    )


def _five_base_cabinets() -> list[CabinetPlacement]:
    return [_make_base_cab(f"B{i+1}", 600.0) for i in range(5)]


# ---------------------------------------------------------------------------
# Test 1 & 2: 5 base cabinets → items grouped by part_id
# ---------------------------------------------------------------------------

class TestFiveBaseCabinets:
    def test_returns_items(self):
        """Cut list for 5 base cabinets must have ≥ 1 item."""
        report = generate_cut_list(_five_base_cabinets())
        assert len(report.items) >= 1

    def test_items_are_aggregated(self):
        """Identical parts across cabinets should be aggregated (count > 1)."""
        report = generate_cut_list(_five_base_cabinets())
        # The 5 identical base cabinets should aggregate side panels
        side_items = [i for i in report.items if "side" in i.part_id]
        if side_items:
            # All 5 cabinets have 2 sides each = 10 sides total, aggregated into 1 item
            total_side_count = sum(i.count for i in side_items)
            assert total_side_count == 10, f"Expected 10 side panels, got {total_side_count}"

    def test_items_grouped_by_part_id(self):
        """Each (part_id, material, dims) combination appears at most once."""
        report = generate_cut_list(_five_base_cabinets())
        seen_keys: set = set()
        for item in report.items:
            key = (item.part_id, item.material, round(item.length_mm, 1), round(item.width_mm, 1))
            assert key not in seen_keys, f"Duplicate part entry: {key}"
            seen_keys.add(key)

    # --- Test 3: Total sheet count ≥ 1 ---
    def test_total_sheet_count_at_least_one(self):
        """5 cabinets require at least 1 sheet per material."""
        report = generate_cut_list(_five_base_cabinets())
        assert len(report.total_sheets_required) >= 1
        for mat, n in report.total_sheets_required.items():
            assert n >= 1, f"Sheet count for {mat} should be ≥ 1, got {n}"

    # --- Test 4: Waste percentage in valid range ---
    def test_waste_pct_valid_range(self):
        """waste_pct must be in [0, 100]."""
        report = generate_cut_list(_five_base_cabinets())
        assert 0.0 <= report.waste_pct <= 100.0

    # --- Test 5: Estimated cost > 0 ---
    def test_estimated_cost_positive(self):
        """Estimated cost must be > 0 for material cabinets."""
        report = generate_cut_list(_five_base_cabinets())
        assert report.estimated_cost_usd > 0.0

    # --- Test 6: Edge banding total > 0 ---
    def test_edge_banding_total_positive(self):
        """Edge banding total lineal metres must be > 0 when banding is set."""
        report = generate_cut_list(_five_base_cabinets())
        assert report.total_lineal_meters_edge_banding > 0.0

    # --- Test 7: CutListReport has required fields ---
    def test_report_has_required_fields(self):
        """CutListReport must have all required fields."""
        report = generate_cut_list(_five_base_cabinets())
        assert hasattr(report, "items")
        assert hasattr(report, "total_sheets_required")
        assert hasattr(report, "total_lineal_meters_edge_banding")
        assert hasattr(report, "estimated_cost_usd")
        assert hasattr(report, "waste_pct")
        assert hasattr(report, "honest_caveat")
        assert "KCMA" in report.honest_caveat or "simplified" in report.honest_caveat.lower()


# ---------------------------------------------------------------------------
# Test 8: Single cabinet returns ≥ 4 parts
# ---------------------------------------------------------------------------

class TestSingleCabinet:
    def test_minimum_parts_for_single_cabinet(self):
        """Single cabinet must decompose to at least sides + top + bottom + back."""
        report = generate_cut_list([_make_base_cab("B1")])
        # Minimum 4 distinct part types
        part_ids = {item.part_id for item in report.items}
        assert len(part_ids) >= 4, f"Expected ≥4 part types, got {part_ids}"

    # --- Test 9: Door count propagates ---
    def test_door_count_propagates(self):
        """Cabinet with 2 doors should have a door entry with count=2."""
        cab = CabinetPlacement(
            cabinet_id="D2",
            cabinet_type="base",
            width_mm=900.0,
            height_mm=762.0,
            depth_mm=610.0,
            material='birch_ply_3/4"',
            back_material='birch_ply_1/4"',
            door_count=2,
            shelf_count=0,
            edge_banding="pvc_white",
        )
        report = generate_cut_list([cab])
        door_items = [i for i in report.items if "door" in i.part_id]
        assert len(door_items) >= 1
        total_doors = sum(i.count for i in door_items)
        assert total_doors == 2, f"Expected 2 doors, got {total_doors}"

    # --- Test 10: Shelf count propagates ---
    def test_shelf_count_propagates(self):
        """Cabinet with 3 shelves should have a shelf entry with count=3."""
        cab = CabinetPlacement(
            cabinet_id="S3",
            cabinet_type="wall",
            width_mm=600.0,
            height_mm=762.0,
            depth_mm=330.0,
            material='birch_ply_3/4"',
            back_material='birch_ply_1/4"',
            door_count=1,
            shelf_count=3,
            edge_banding="none",
        )
        report = generate_cut_list([cab])
        shelf_items = [i for i in report.items if "shelf" in i.part_id]
        assert len(shelf_items) >= 1
        total_shelves = sum(i.count for i in shelf_items)
        assert total_shelves == 3, f"Expected 3 shelves, got {total_shelves}"

    # --- Test 11: Face frame generates stile + rail ---
    def test_face_frame_generates_parts(self):
        """Cabinet with face frame should include ff_stile and ff_rail items."""
        cab = CabinetPlacement(
            cabinet_id="FF1",
            cabinet_type="base",
            width_mm=600.0,
            height_mm=762.0,
            depth_mm=610.0,
            material='birch_ply_3/4"',
            back_material='birch_ply_1/4"',
            door_count=1,
            shelf_count=1,
            edge_banding="none",
            include_face_frame=True,
        )
        report = generate_cut_list([cab])
        part_ids = {item.part_id for item in report.items}
        assert any("stile" in pid for pid in part_ids), f"No stile in {part_ids}"
        assert any("rail" in pid for pid in part_ids), f"No rail in {part_ids}"

    # --- Test 12: Empty placements returns empty report ---
    def test_empty_placements_returns_empty(self):
        """Empty placement list must return an empty CutListReport."""
        report = generate_cut_list([])
        assert report.items == []
        assert report.total_sheets_required == {}
        assert report.estimated_cost_usd == 0.0
        assert report.waste_pct == 0.0
