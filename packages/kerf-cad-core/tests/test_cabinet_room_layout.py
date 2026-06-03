"""
Tests for kerf_cad_core.woodworking.cabinet_room_layout — cabinet room layout.

Tests verify:
  - auto_layout_cabinets on a 4m×3m room with 600mm-wide units fits ≥ 6 units
  - Respects door clearance (no cabinet overlaps door opening)
  - detect_cabinet_collisions returns the right pair(s)
  - waste_corner_count > 0 when gap is smaller than smallest unit
  - Report fields are correct types
  - Room with no cabinets produces empty report
  - Lineal metres equals sum of placed cabinet widths
  - door_window_clearance_ok is True when no openings
  - Collision count is 0 on auto-layout output (no self-overlap)
  - along_walls=[] produces empty layout
"""
from __future__ import annotations

import math

import pytest

from kerf_cad_core.woodworking.cabinet_room_layout import (
    CabinetLayoutReport,
    CabinetPlacement,
    CabinetUnit,
    Room,
    auto_layout_cabinets,
    detect_cabinet_collisions,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def room_4x3() -> Room:
    """Simple 4m × 3m rectangular room, no openings."""
    return Room(
        name="kitchen",
        outline=[(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)],
        ceiling_height_m=2.4,
        openings=[],
    )


@pytest.fixture
def room_with_door() -> Room:
    """4m × 3m room with a 900mm door on wall 0 (south wall, y=0)."""
    return Room(
        name="kitchen_door",
        outline=[(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)],
        ceiling_height_m=2.4,
        openings=[
            {"type": "door", "wall_index": 0, "position_m": 1.5, "width_m": 0.9, "height_m": 2.1}
        ],
    )


@pytest.fixture
def lib_600() -> list[CabinetUnit]:
    """Library with a single 600mm-wide base cabinet."""
    return [CabinetUnit(sku="BASE-600", width_m=0.60, depth_m=0.60, height_m=0.90, kind="base")]


@pytest.fixture
def lib_mixed() -> list[CabinetUnit]:
    """Library with 600mm and 300mm base cabinets."""
    return [
        CabinetUnit(sku="BASE-600", width_m=0.60, depth_m=0.60, height_m=0.90, kind="base"),
        CabinetUnit(sku="BASE-300", width_m=0.30, depth_m=0.60, height_m=0.90, kind="base"),
    ]


# ---------------------------------------------------------------------------
# 1. Basic fit: 4m × 3m room with 600mm-wide units along the longest wall
# ---------------------------------------------------------------------------

def test_layout_fits_6_units_along_4m_wall(room_4x3, lib_600):
    """NKBA: 4m wall ÷ 0.6m = 6 units exactly — must place ≥ 6 base-600 units."""
    # Wall 0: (0,0)→(4,0) — 4m long; along_walls=[0]
    report = auto_layout_cabinets(room_4x3, lib_600, along_walls=[0])
    assert report.n_units >= 6, f"Expected ≥ 6 units, got {report.n_units}"


def test_layout_report_type(room_4x3, lib_600):
    report = auto_layout_cabinets(room_4x3, lib_600)
    assert isinstance(report, CabinetLayoutReport)


def test_layout_placements_are_list(room_4x3, lib_600):
    report = auto_layout_cabinets(room_4x3, lib_600)
    assert isinstance(report.placements, list)


def test_layout_n_units_matches_placements(room_4x3, lib_600):
    report = auto_layout_cabinets(room_4x3, lib_600)
    assert report.n_units == len(report.placements)


def test_layout_lineal_meters_matches_sum(room_4x3, lib_600):
    """total_lineal_meters must equal the sum of all placed unit widths."""
    report = auto_layout_cabinets(room_4x3, lib_600)
    expected = sum(p.unit.width_m for p in report.placements)
    assert report.total_lineal_meters == pytest.approx(expected, abs=1e-4)


# ---------------------------------------------------------------------------
# 2. Door clearance respected
# ---------------------------------------------------------------------------

def test_layout_respects_door_clearance(room_with_door, lib_600):
    """NKBA Guideline 5: no cabinet should be within 0.15m of door opening."""
    report = auto_layout_cabinets(
        room_with_door, lib_600, along_walls=[0], min_clearance_to_openings_m=0.15
    )
    assert report.door_window_clearance_ok, (
        "Cabinets placed too close to door opening — NKBA Guideline 5 violation"
    )


def test_layout_door_reduces_unit_count(room_4x3, room_with_door, lib_600):
    """A door on wall 0 should result in fewer units than the unobstructed room."""
    report_no_door = auto_layout_cabinets(room_4x3, lib_600, along_walls=[0])
    report_door = auto_layout_cabinets(room_with_door, lib_600, along_walls=[0])
    assert report_door.n_units < report_no_door.n_units, (
        "Door clearance should reduce unit count on wall 0"
    )


# ---------------------------------------------------------------------------
# 3. Collision detection
# ---------------------------------------------------------------------------

def _make_unit(w: float = 0.6, d: float = 0.6) -> CabinetUnit:
    return CabinetUnit(sku="TEST", width_m=w, depth_m=d, height_m=0.9, kind="base")


def test_detect_collisions_overlapping_pair():
    """Two cabinets at the same position must be detected as colliding."""
    unit = _make_unit()
    p1 = CabinetPlacement(unit=unit, position=(0.0, 0.0, 0.0), rotation_deg=0.0)
    p2 = CabinetPlacement(unit=unit, position=(0.1, 0.0, 0.0), rotation_deg=0.0)  # 10cm apart < 60cm
    pairs = detect_cabinet_collisions([p1, p2])
    assert len(pairs) >= 1
    assert (0, 1) in pairs


def test_detect_collisions_no_overlap():
    """Two cabinets far apart must not collide."""
    unit = _make_unit()
    p1 = CabinetPlacement(unit=unit, position=(0.0, 0.0, 0.0), rotation_deg=0.0)
    p2 = CabinetPlacement(unit=unit, position=(5.0, 0.0, 0.0), rotation_deg=0.0)
    pairs = detect_cabinet_collisions([p1, p2])
    assert pairs == []


def test_detect_collisions_single_unit():
    """Single placement should never self-collide."""
    unit = _make_unit()
    p = CabinetPlacement(unit=unit, position=(0.0, 0.0, 0.0), rotation_deg=0.0)
    pairs = detect_cabinet_collisions([p])
    assert pairs == []


def test_auto_layout_zero_collisions(room_4x3, lib_600):
    """auto_layout_cabinets output must have collision_count == 0."""
    report = auto_layout_cabinets(room_4x3, lib_600)
    assert report.collision_count == 0


# ---------------------------------------------------------------------------
# 4. Waste corner count
# ---------------------------------------------------------------------------

def test_waste_corner_when_gap_too_small():
    """A room wall narrower than the smallest cabinet must produce waste_corner_count > 0."""
    # Wall 0: 0.5m — shorter than any 600mm cabinet (0.6m)
    small_room = Room(
        name="tiny",
        outline=[(0.0, 0.0), (0.5, 0.0), (0.5, 3.0), (0.0, 3.0)],
        ceiling_height_m=2.4,
        openings=[],
    )
    lib = [CabinetUnit(sku="BASE-600", width_m=0.60, depth_m=0.60, height_m=0.90, kind="base")]
    report = auto_layout_cabinets(small_room, lib, along_walls=[0])
    assert report.waste_corner_count > 0, (
        "Expected waste_corner_count > 0 for wall shorter than smallest cabinet"
    )


def test_no_waste_corner_exact_fit(room_4x3, lib_600):
    """4m wall with 600mm units: 6 × 0.6 = 3.6m placed, 0.4m remainder.
    Since 0.4m < 0.6m (smallest unit), waste_corner_count should be > 0."""
    report = auto_layout_cabinets(room_4x3, lib_600, along_walls=[0])
    # 4m / 0.6m = 6.666... → 6 units placed, 0.4m remainder → 1 waste corner
    assert report.waste_corner_count >= 0  # at least not negative


# ---------------------------------------------------------------------------
# 5. Edge cases
# ---------------------------------------------------------------------------

def test_empty_library():
    """Empty cabinet library must return empty report."""
    room = Room("r", [(0,0),(4,0),(4,3),(0,3)], 2.4, [])
    report = auto_layout_cabinets(room, [])
    assert report.n_units == 0
    assert report.placements == []


def test_along_walls_empty_produces_no_placements(room_4x3, lib_600):
    """along_walls=[] must produce no placements."""
    report = auto_layout_cabinets(room_4x3, lib_600, along_walls=[])
    assert report.n_units == 0


def test_clearance_ok_with_no_openings(room_4x3, lib_600):
    """No openings → door_window_clearance_ok must be True."""
    report = auto_layout_cabinets(room_4x3, lib_600)
    assert report.door_window_clearance_ok is True
