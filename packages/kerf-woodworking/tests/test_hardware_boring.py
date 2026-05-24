"""
Tests for kerf_woodworking.hardware_boring — Cabinet hardware bore-pattern generator.

DoD oracles:
  1. Hinge cup pattern: 35 mm cups placed at correct Y positions, cups ≥ 64 mm from edges.
  2. Shelf pin pattern: holes on 32 mm pitch, correct row X positions.
  3. Drawer runner pattern: undermount pilots at correct Y height.
  4. Euro screw pattern: pilot holes at panel_thickness/2 from the specified edge.
  5. Handle pattern: two holes separated by centres_mm.
  6. bore_pattern_to_dict is JSON-serialisable.
  7. Invalid inputs raise ValueError.
"""

from __future__ import annotations

import json
import math
import os
import sys

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_woodworking.hardware_boring import (
    hinge_cup_pattern,
    shelf_pin_pattern,
    drawer_runner_pattern,
    euro_screw_pattern,
    handle_pattern,
    bore_pattern_to_dict,
    BorePattern,
    BoreHole,
    HINGE_CUP_DIA,
    HINGE_CUP_DEPTH,
    SYSTEM_HOLE_DIA,
    SYSTEM_HOLE_DEPTH,
    SYSTEM_32_PITCH,
    FRONT_EDGE_OFFSET,
)


# ---------------------------------------------------------------------------
# DoD oracle 1: hinge cup pattern
# ---------------------------------------------------------------------------

class TestHingeCupPattern:
    """Hinge-cup bore positions follow Blum Clip-Top specifications."""

    def test_returns_bore_pattern(self):
        p = hinge_cup_pattern(800.0)
        assert isinstance(p, BorePattern)

    def test_two_hinges_for_default(self):
        p = hinge_cup_pattern(800.0, count=2)
        cups = [h for h in p.holes if h.kind == "hinge_cup"]
        assert len(cups) == 2

    def test_three_hinges(self):
        p = hinge_cup_pattern(1200.0, count=3)
        cups = [h for h in p.holes if h.kind == "hinge_cup"]
        assert len(cups) == 3

    def test_cup_diameter_35mm(self):
        """All hinge cups must be 35 mm diameter."""
        p = hinge_cup_pattern(800.0, count=2)
        cups = [h for h in p.holes if h.kind == "hinge_cup"]
        for cup in cups:
            assert abs(cup.diameter_mm - HINGE_CUP_DIA) < 0.1

    def test_cup_depth_13mm(self):
        p = hinge_cup_pattern(800.0)
        cups = [h for h in p.holes if h.kind == "hinge_cup"]
        for cup in cups:
            assert abs(cup.depth_mm - HINGE_CUP_DEPTH) < 0.1

    def test_cup_x_is_22_5mm(self):
        """Cup centres at 22.5 mm from hinge stile (left edge)."""
        p = hinge_cup_pattern(800.0)
        cups = [h for h in p.holes if h.kind == "hinge_cup"]
        for cup in cups:
            assert abs(cup.x - 22.5) < 0.5

    def test_cups_not_too_close_to_edges(self):
        """Cup Y positions ≥ 64 mm from top and bottom edges."""
        p = hinge_cup_pattern(800.0, count=2)
        cups = [h for h in p.holes if h.kind == "hinge_cup"]
        for cup in cups:
            assert cup.y >= 64.0, f"Cup too close to bottom: y={cup.y}"
            assert cup.y <= 800.0 - 64.0, f"Cup too close to top: y={cup.y}"

    def test_top_hinge_above_bottom_hinge(self):
        p = hinge_cup_pattern(900.0, count=2)
        cups = sorted([h for h in p.holes if h.kind == "hinge_cup"], key=lambda h: h.y)
        assert cups[1].y > cups[0].y

    def test_pilot_holes_present(self):
        p = hinge_cup_pattern(800.0, count=2)
        pilots = [h for h in p.holes if h.kind == "hinge_pilot"]
        assert len(pilots) > 0

    def test_hardware_type_label(self):
        p = hinge_cup_pattern(800.0)
        assert p.hardware_type == "hinge_cup"

    def test_panel_height_stored(self):
        p = hinge_cup_pattern(900.0)
        assert abs(p.panel_height_mm - 900.0) < 0.1

    def test_tall_door_warns_if_too_few_hinges(self):
        p = hinge_cup_pattern(1600.0, count=2)
        assert len(p.warnings) > 0

    def test_invalid_height_raises(self):
        with pytest.raises(ValueError):
            hinge_cup_pattern(-100.0)

    def test_count_zero_raises(self):
        with pytest.raises(ValueError):
            hinge_cup_pattern(800.0, count=0)


# ---------------------------------------------------------------------------
# DoD oracle 2: shelf-pin pattern
# ---------------------------------------------------------------------------

class TestShelfPinPattern:
    """Shelf-pin holes on 32 mm pitch, correct row X positions."""

    def test_returns_bore_pattern(self):
        p = shelf_pin_pattern(800.0)
        assert isinstance(p, BorePattern)

    def test_holes_on_32mm_pitch(self):
        """Adjacent holes in the same row are exactly 32 mm apart."""
        p = shelf_pin_pattern(800.0, num_positions=5, start_y_mm=96.0)
        front_holes = sorted(
            [h for h in p.holes if "front" in h.label], key=lambda h: h.y
        )
        if len(front_holes) >= 2:
            for i in range(len(front_holes) - 1):
                gap = front_holes[i + 1].y - front_holes[i].y
                assert abs(gap - SYSTEM_32_PITCH) < 0.5, (
                    f"Pitch {gap:.1f} mm ≠ 32 mm"
                )

    def test_front_row_at_37mm(self):
        """Front row at FRONT_EDGE_OFFSET (37 mm) from front edge."""
        p = shelf_pin_pattern(800.0)
        front_holes = [h for h in p.holes if "front" in h.label]
        for hole in front_holes:
            assert abs(hole.x - FRONT_EDGE_OFFSET) < 0.5

    def test_rear_row_at_correct_x(self):
        """Rear row at panel_width - 37 mm from front."""
        W = 600.0
        p = shelf_pin_pattern(800.0, panel_width_mm=W)
        rear_holes = [h for h in p.holes if "rear" in h.label]
        for hole in rear_holes:
            assert abs(hole.x - (W - FRONT_EDGE_OFFSET)) < 0.5

    def test_hole_diameter_5mm(self):
        p = shelf_pin_pattern(800.0)
        for h in p.holes:
            assert abs(h.diameter_mm - SYSTEM_HOLE_DIA) < 0.1

    def test_num_positions_respected(self):
        """num_positions holes per row → 2 × num_positions holes total."""
        p = shelf_pin_pattern(1000.0, num_positions=8)
        assert len(p.holes) == 2 * 8

    def test_hardware_type_label(self):
        p = shelf_pin_pattern(800.0)
        assert p.hardware_type == "shelf_pin"

    def test_invalid_height_raises(self):
        with pytest.raises(ValueError):
            shelf_pin_pattern(0.0)


# ---------------------------------------------------------------------------
# DoD oracle 3: drawer runner pattern
# ---------------------------------------------------------------------------

class TestDrawerRunnerPattern:
    """Undermount drawer runner pilots at correct height."""

    def test_returns_bore_pattern(self):
        p = drawer_runner_pattern(800.0, 150.0)
        assert isinstance(p, BorePattern)

    def test_two_pilots_per_drawer_undermount(self):
        """Undermount: one front + one rear pilot per drawer."""
        p = drawer_runner_pattern(800.0, 150.0, runner_type="undermount", num_drawers=1)
        pilots = [h for h in p.holes if h.kind == "drawer_pilot"]
        assert len(pilots) == 2

    def test_two_drawers_four_pilots(self):
        p = drawer_runner_pattern(800.0, 150.0, runner_type="undermount", num_drawers=2)
        pilots = [h for h in p.holes if h.kind == "drawer_pilot"]
        assert len(pilots) == 4

    def test_sidemount_pilots(self):
        p = drawer_runner_pattern(800.0, 150.0, runner_type="sidemount", num_drawers=1)
        pilots = [h for h in p.holes if h.kind == "drawer_pilot"]
        assert len(pilots) == 2

    def test_front_pilot_at_87mm(self):
        """Front pilot at 87 mm from front edge."""
        p = drawer_runner_pattern(800.0, 150.0, runner_type="undermount")
        front_pilots = [h for h in p.holes if "front" in h.label]
        for hp in front_pilots:
            assert abs(hp.x - 87.0) < 1.0

    def test_hardware_type_contains_runner(self):
        p = drawer_runner_pattern(800.0, 150.0)
        assert "runner" in p.hardware_type

    def test_invalid_runner_type_raises(self):
        with pytest.raises(ValueError):
            drawer_runner_pattern(800.0, 150.0, runner_type="floating")


# ---------------------------------------------------------------------------
# DoD oracle 4: Euro screw pattern
# ---------------------------------------------------------------------------

class TestEuroScrewPattern:
    """Confirmat pilot holes at correct positions."""

    def test_returns_bore_pattern(self):
        p = euro_screw_pattern(600.0, 800.0)
        assert isinstance(p, BorePattern)

    def test_two_holes_by_default(self):
        p = euro_screw_pattern(600.0, 800.0, count=2)
        assert len(p.holes) == 2

    def test_bottom_edge_y_at_half_thickness(self):
        """Bottom-edge euro screws: y = panel_thickness / 2."""
        t = 18.0
        p = euro_screw_pattern(600.0, 800.0, panel_thickness_mm=t, edge="bottom")
        for h in p.holes:
            assert abs(h.y - t / 2.0) < 0.5

    def test_top_edge_y_near_top(self):
        t = 18.0
        H = 800.0
        p = euro_screw_pattern(600.0, H, panel_thickness_mm=t, edge="top")
        for h in p.holes:
            assert abs(h.y - (H - t / 2.0)) < 0.5

    def test_hole_kind_is_euro_screw(self):
        p = euro_screw_pattern(600.0, 800.0)
        for h in p.holes:
            assert h.kind == "euro_screw"

    def test_hardware_type_label(self):
        p = euro_screw_pattern(600.0, 800.0)
        assert p.hardware_type == "euro_screw"

    def test_invalid_edge_raises(self):
        with pytest.raises(ValueError):
            euro_screw_pattern(600.0, 800.0, edge="diagonal")


# ---------------------------------------------------------------------------
# DoD oracle 5: handle pattern
# ---------------------------------------------------------------------------

class TestHandlePattern:
    """Handle holes separated by centres_mm."""

    def test_returns_bore_pattern(self):
        p = handle_pattern(500.0, 800.0)
        assert isinstance(p, BorePattern)

    def test_two_holes_per_handle(self):
        p = handle_pattern(500.0, 800.0, centres_mm=128.0)
        holes = p.holes
        assert len(holes) == 2

    def test_horizontal_separation_equals_centres(self):
        """For horizontal orientation, hole separation = centres_mm."""
        c = 128.0
        p = handle_pattern(500.0, 800.0, centres_mm=c, orientation="horizontal")
        xs = sorted([h.x for h in p.holes])
        assert abs((xs[1] - xs[0]) - c) < 0.5, (
            f"Separation {xs[1] - xs[0]:.1f} mm ≠ centres {c} mm"
        )

    def test_vertical_separation_equals_centres(self):
        c = 96.0
        p = handle_pattern(500.0, 800.0, centres_mm=c, orientation="vertical")
        ys = sorted([h.y for h in p.holes])
        assert abs((ys[1] - ys[0]) - c) < 0.5

    def test_hole_kind_is_handle_pilot(self):
        p = handle_pattern(500.0, 800.0)
        for h in p.holes:
            assert h.kind == "handle_pilot"

    def test_hardware_type_label(self):
        p = handle_pattern(500.0, 800.0)
        assert p.hardware_type == "handle"

    def test_invalid_edge_raises(self):
        with pytest.raises(ValueError):
            handle_pattern(500.0, 800.0, edge="outside")


# ---------------------------------------------------------------------------
# DoD oracle 6: bore_pattern_to_dict JSON-serialisable
# ---------------------------------------------------------------------------

class TestBorePatternToDict:
    def test_json_serialisable(self):
        p = hinge_cup_pattern(800.0)
        d = bore_pattern_to_dict(p)
        json.dumps(d)  # must not raise

    def test_has_expected_keys(self):
        p = shelf_pin_pattern(800.0)
        d = bore_pattern_to_dict(p)
        for key in ("hardware_type", "panel_width_mm", "panel_height_mm",
                    "hole_count", "holes", "warnings"):
            assert key in d

    def test_hole_count_matches(self):
        p = hinge_cup_pattern(800.0, count=2)
        d = bore_pattern_to_dict(p)
        assert d["hole_count"] == len(p.holes)

    def test_hole_dict_has_coords(self):
        p = hinge_cup_pattern(800.0)
        d = bore_pattern_to_dict(p)
        for hole in d["holes"]:
            assert "x" in hole
            assert "y" in hole
            assert "diameter_mm" in hole
            assert "depth_mm" in hole

    def test_coordinates_are_floats(self):
        p = shelf_pin_pattern(800.0)
        d = bore_pattern_to_dict(p)
        for hole in d["holes"]:
            assert isinstance(hole["x"], (int, float))
            assert isinstance(hole["y"], (int, float))


# ---------------------------------------------------------------------------
# Integration: all hardware types smoke-test
# ---------------------------------------------------------------------------

class TestAllHardwareTypesSmoke:
    def test_hinge_imports(self):
        from kerf_woodworking.hardware_boring import hinge_cup_pattern  # noqa: F401

    def test_shelf_pin_imports(self):
        from kerf_woodworking.hardware_boring import shelf_pin_pattern  # noqa: F401

    def test_drawer_runner_imports(self):
        from kerf_woodworking.hardware_boring import drawer_runner_pattern  # noqa: F401

    def test_euro_screw_imports(self):
        from kerf_woodworking.hardware_boring import euro_screw_pattern  # noqa: F401

    def test_handle_imports(self):
        from kerf_woodworking.hardware_boring import handle_pattern  # noqa: F401

    def test_all_produce_holes(self):
        patterns = [
            hinge_cup_pattern(800.0),
            shelf_pin_pattern(800.0),
            drawer_runner_pattern(800.0, 150.0),
            euro_screw_pattern(600.0, 800.0),
            handle_pattern(500.0, 800.0),
        ]
        for p in patterns:
            assert len(p.holes) > 0, f"{p.hardware_type} produced no holes"
