"""
Contract tests for kerf-interior.

All tests are hermetic — no DB, no network, no async.

Key oracle values (from the task brief)
-----------------------------------------
- ADA wheelchair turning circle = 60 in / 1524 mm diameter
  → code must generate 1524 ± 5 mm; values outside this bracket must fail.
- Reach-range high check fires at > 48 in / 1219 mm.
- Corridor-clearance check fires when corridor < 36 in / 914 mm.
"""
from __future__ import annotations

import math
import pytest

from kerf_interior.clearance import (
    TURNING_CIRCLE_DIAMETER_MM,
    MIN_CORRIDOR_WIDTH_MM,
    MAX_REACH_HIGH_MM,
    MIN_REACH_LOW_MM,
    MIN_KNEE_CLEARANCE_HEIGHT_MM,
    MIN_KNEE_CLEARANCE_DEPTH_MM,
    ADAViolation,
    audit_clearances,
    check_turning_radius,
    check_corridor_clearance,
    check_knee_clearance,
    check_reach_range,
    turning_circle_diameter_mm,
)
from kerf_interior.furniture import (
    FurnitureItem,
    make_chair,
    make_desk,
    make_sofa,
    make_table,
)
from kerf_interior.space_planning import (
    CirculationPath,
    PlacedItem,
    RoomLayout,
    make_room,
)


# ==========================================================================
# clearance.py — constant oracle checks
# ==========================================================================

class TestADAConstants:
    """Verify that the module-level constants match the ADA/ANSI spec."""

    def test_turning_circle_is_1524_mm(self):
        assert TURNING_CIRCLE_DIAMETER_MM == pytest.approx(1524.0, abs=0.1)

    def test_min_corridor_is_914_mm(self):
        assert MIN_CORRIDOR_WIDTH_MM == pytest.approx(914.0, abs=0.1)

    def test_max_reach_high_is_1219_mm(self):
        assert MAX_REACH_HIGH_MM == pytest.approx(1219.0, abs=0.1)

    def test_min_reach_low_is_381_mm(self):
        assert MIN_REACH_LOW_MM == pytest.approx(381.0, abs=0.1)

    def test_knee_clearance_height_is_686_mm(self):
        assert MIN_KNEE_CLEARANCE_HEIGHT_MM == pytest.approx(686.0, abs=0.1)

    def test_knee_clearance_depth_is_483_mm(self):
        assert MIN_KNEE_CLEARANCE_DEPTH_MM == pytest.approx(483.0, abs=0.1)


# ==========================================================================
# clearance.py — turning_circle_diameter_mm()
# ==========================================================================

class TestTurningCircleDiameterMm:
    """turning_circle_diameter_mm() must return exactly 1524 ± 5 mm."""

    def test_default_returns_1524(self):
        d = turning_circle_diameter_mm()
        assert abs(d - 1524.0) <= 5.0, (
            f"Default turning circle diameter {d} mm is outside 1524 ± 5 mm"
        )

    def test_radius_arg_doubles_to_diameter(self):
        # 762 mm radius → 1524 mm diameter
        d = turning_circle_diameter_mm(radius_mm=762.0)
        assert d == pytest.approx(1524.0, abs=5.0)

    def test_canonical_value_is_exactly_1524(self):
        assert turning_circle_diameter_mm() == 1524.0


# ==========================================================================
# clearance.py — check_turning_radius()
# ==========================================================================

class TestCheckTurningRadius:
    """Turning-radius checks fire below 1524 mm; clear above it."""

    def test_compliant_at_exact_diameter(self):
        violations = check_turning_radius(1524.0)
        assert violations == []

    def test_compliant_with_tolerance(self):
        # 1519 mm is within the default 5 mm tolerance
        violations = check_turning_radius(1519.0)
        assert violations == []

    def test_violation_below_tolerance(self):
        # 1518 mm is outside default 5 mm tolerance
        violations = check_turning_radius(1518.0)
        assert len(violations) == 1
        v = violations[0]
        assert v.rule == "turning_radius"
        assert v.actual_mm == pytest.approx(1518.0)
        assert v.limit_mm == pytest.approx(1524.0)

    def test_violation_for_very_small_diameter(self):
        violations = check_turning_radius(1000.0)
        assert len(violations) == 1
        assert violations[0].deficit_mm == pytest.approx(524.0, abs=1.0)

    def test_violation_message_contains_60in(self):
        violations = check_turning_radius(1000.0)
        assert "1524" in violations[0].message
        assert "60" in violations[0].message

    def test_compliant_generously_above(self):
        violations = check_turning_radius(2000.0)
        assert violations == []

    def test_custom_tolerance_zero(self):
        # With zero tolerance, exactly 1524 must pass; 1523.9 must fail.
        assert check_turning_radius(1524.0, tolerance_mm=0.0) == []
        assert len(check_turning_radius(1523.9, tolerance_mm=0.0)) == 1

    def test_violation_is_ada_violation_type(self):
        violations = check_turning_radius(1000.0)
        assert isinstance(violations[0], ADAViolation)


# ==========================================================================
# clearance.py — check_corridor_clearance()
# ==========================================================================

class TestCheckCorridorClearance:
    """Corridor check fires when width < 914 mm (36 in)."""

    def test_compliant_at_exact_minimum(self):
        assert check_corridor_clearance(914.0) == []

    def test_compliant_above_minimum(self):
        assert check_corridor_clearance(1200.0) == []

    def test_violation_at_913_mm(self):
        violations = check_corridor_clearance(913.0)
        assert len(violations) == 1
        v = violations[0]
        assert v.rule == "corridor_width"
        assert v.actual_mm == pytest.approx(913.0)
        assert v.limit_mm == pytest.approx(914.0)

    def test_violation_at_500_mm(self):
        violations = check_corridor_clearance(500.0)
        assert len(violations) == 1
        assert violations[0].deficit_mm == pytest.approx(414.0, abs=1.0)

    def test_violation_message_contains_36in_and_914mm(self):
        violations = check_corridor_clearance(800.0)
        msg = violations[0].message
        assert "914" in msg
        assert "36" in msg

    def test_zero_width_fires(self):
        assert len(check_corridor_clearance(0.0)) == 1

    def test_borderline_with_tolerance(self):
        # 913 with 1 mm tolerance should pass
        assert check_corridor_clearance(913.0, tolerance_mm=1.0) == []
        # but 912 with 1 mm tolerance should fail
        assert len(check_corridor_clearance(912.0, tolerance_mm=1.0)) == 1


# ==========================================================================
# clearance.py — check_reach_range()
# ==========================================================================

class TestCheckReachRange:
    """Reach-range check fires above 1219 mm (48 in) or below 381 mm (15 in)."""

    def test_compliant_midrange(self):
        # 900 mm is well within range
        assert check_reach_range(900.0) == []

    def test_compliant_at_high_limit(self):
        assert check_reach_range(1219.0) == []

    def test_compliant_at_low_limit(self):
        assert check_reach_range(381.0) == []

    def test_violation_above_high_limit(self):
        # 1220 mm > 1219 mm — must fire
        violations = check_reach_range(1220.0)
        assert len(violations) == 1
        v = violations[0]
        assert v.rule == "reach_range_high"
        assert v.actual_mm == pytest.approx(1220.0)
        assert v.limit_mm == pytest.approx(1219.0)

    def test_violation_well_above_high_limit(self):
        # 1500 mm >> 1219 mm
        violations = check_reach_range(1500.0)
        assert len(violations) >= 1
        rules = {v.rule for v in violations}
        assert "reach_range_high" in rules

    def test_violation_below_low_limit(self):
        violations = check_reach_range(380.0)
        assert len(violations) == 1
        assert violations[0].rule == "reach_range_low"

    def test_violation_message_contains_48in_for_high(self):
        violations = check_reach_range(1300.0)
        assert "1219" in violations[0].message
        assert "48" in violations[0].message

    def test_check_high_only(self):
        v = check_reach_range(300.0, check_high=True, check_low=False)
        # 300 mm is below low limit but we disabled low check
        assert v == []

    def test_check_low_only(self):
        v = check_reach_range(1500.0, check_high=False, check_low=True)
        # 1500 mm is above high limit but we disabled high check
        assert v == []


# ==========================================================================
# clearance.py — check_knee_clearance()
# ==========================================================================

class TestCheckKneeClearance:
    """Knee-clearance checks (ADA §306.3)."""

    def test_compliant(self):
        assert check_knee_clearance(686.0, 483.0) == []

    def test_height_violation(self):
        violations = check_knee_clearance(685.0, 483.0)
        assert len(violations) == 1
        assert violations[0].rule == "knee_clearance_height"

    def test_depth_violation(self):
        violations = check_knee_clearance(686.0, 482.0)
        assert len(violations) == 1
        assert violations[0].rule == "knee_clearance_depth"

    def test_both_violations(self):
        violations = check_knee_clearance(600.0, 400.0)
        rules = {v.rule for v in violations}
        assert "knee_clearance_height" in rules
        assert "knee_clearance_depth" in rules

    def test_above_minimums_compliant(self):
        assert check_knee_clearance(900.0, 600.0) == []


# ==========================================================================
# clearance.py — audit_clearances() batch helper
# ==========================================================================

class TestAuditClearances:
    def test_empty_call_returns_no_violations(self):
        assert audit_clearances() == []

    def test_all_compliant(self):
        result = audit_clearances(
            turning_diameter_mm=1600.0,
            corridor_widths_mm=[1000.0, 1200.0],
            knee_clearances=[(700.0, 500.0)],
            reach_heights_mm=[800.0, 1000.0],
        )
        assert result == []

    def test_mixed_violations(self):
        result = audit_clearances(
            turning_diameter_mm=1000.0,       # fail
            corridor_widths_mm=[800.0],        # fail
            reach_heights_mm=[1500.0],         # fail high
        )
        rules = {v.rule for v in result}
        assert "turning_radius" in rules
        assert "corridor_width" in rules
        assert "reach_range_high" in rules


# ==========================================================================
# furniture.py
# ==========================================================================

class TestMakeChair:
    def test_default_dimensions(self):
        c = make_chair()
        assert c.kind == "chair"
        assert c.width_mm == pytest.approx(500.0)
        assert c.depth_mm == pytest.approx(500.0)
        assert c.seat_height_mm == pytest.approx(450.0)

    def test_ada_clearance_enabled_by_default(self):
        c = make_chair()
        assert c.clearance_front_mm >= 914.0

    def test_ada_clearance_disabled(self):
        c = make_chair(with_ada_clearance=False)
        assert c.clearance_front_mm < 914.0

    def test_custom_dimensions(self):
        c = make_chair(name="Lounge Chair", width_mm=700.0, depth_mm=750.0)
        assert c.name == "Lounge Chair"
        assert c.width_mm == pytest.approx(700.0)

    def test_metadata_passthrough(self):
        c = make_chair(finish="oak", manufacturer="Herman Miller")
        assert c.metadata["finish"] == "oak"
        assert c.metadata["manufacturer"] == "Herman Miller"

    def test_serialise_round_trip(self):
        c = make_chair()
        c2 = FurnitureItem.from_dict(c.to_dict())
        assert c2.kind == "chair"
        assert c2.width_mm == pytest.approx(c.width_mm)


class TestMakeDesk:
    def test_default_dimensions(self):
        d = make_desk()
        assert d.kind == "desk"
        assert d.width_mm == pytest.approx(1500.0)
        assert d.depth_mm == pytest.approx(750.0)
        assert d.height_mm == pytest.approx(730.0)

    def test_knee_clearance_stored_in_metadata(self):
        d = make_desk()
        assert d.metadata["knee_clearance_height_mm"] == pytest.approx(686.0)
        assert d.metadata["knee_clearance_depth_mm"] == pytest.approx(483.0)

    def test_custom_knee_clearance(self):
        d = make_desk(knee_clearance_height_mm=700.0, knee_clearance_depth_mm=500.0)
        assert d.metadata["knee_clearance_height_mm"] == pytest.approx(700.0)

    def test_ada_clearance_front(self):
        d = make_desk()
        assert d.clearance_front_mm >= 914.0


class TestMakeSofa:
    def test_default_3_seat(self):
        s = make_sofa()
        assert s.kind == "sofa"
        # 3 seats × 600 + 2 × 150 arms = 2100
        assert s.width_mm == pytest.approx(2100.0, abs=1.0)
        assert s.metadata["seats"] == 3

    def test_single_seat(self):
        s = make_sofa(seats=1)
        assert s.width_mm == pytest.approx(600.0 + 2 * 150.0, abs=1.0)

    def test_invalid_seat_count(self):
        with pytest.raises(ValueError):
            make_sofa(seats=0)
        with pytest.raises(ValueError):
            make_sofa(seats=6)

    def test_clearance_envelope(self):
        s = make_sofa()
        env_w, env_d = s.clearance_envelope_mm
        assert env_d > s.depth_mm


class TestMakeTable:
    def test_default_dimensions(self):
        t = make_table()
        assert t.kind == "table"
        assert t.width_mm == pytest.approx(900.0)
        assert t.height_mm == pytest.approx(750.0)

    def test_ada_clearance_on_all_sides(self):
        t = make_table(with_ada_clearance=True)
        assert t.clearance_front_mm >= 914.0
        assert t.clearance_back_mm >= 914.0
        assert t.clearance_left_mm >= 914.0
        assert t.clearance_right_mm >= 914.0

    def test_seats_stored_in_metadata(self):
        t = make_table(seats=8)
        assert t.metadata["seats"] == 8

    def test_footprint_area_m2(self):
        t = make_table(width_mm=1000.0, depth_mm=1000.0)
        assert t.footprint_area_m2 == pytest.approx(1.0, abs=0.01)


# ==========================================================================
# space_planning.py — make_room / RoomLayout
# ==========================================================================

class TestMakeRoom:
    def test_basic_creation(self):
        room = make_room("Office", 5000.0, 4000.0)
        assert room.name == "Office"
        assert room.width_mm == pytest.approx(5000.0)
        assert room.depth_mm == pytest.approx(4000.0)
        assert room.ceiling_height_mm == pytest.approx(2700.0)

    def test_area_m2(self):
        room = make_room("Test", 5000.0, 4000.0)
        assert room.area_m2 == pytest.approx(20.0, abs=0.01)

    def test_perimeter_mm(self):
        room = make_room("Test", 5000.0, 4000.0)
        assert room.perimeter_mm == pytest.approx(18000.0, abs=1.0)

    def test_metadata_passthrough(self):
        room = make_room("Office", 5000.0, 4000.0, level="L1", building="HQ")
        assert room.metadata["level"] == "L1"
        assert room.metadata["building"] == "HQ"


class TestRoomLayoutPlace:
    def setup_method(self):
        self.room = make_room("Test Room", 6000.0, 5000.0)

    def test_place_item_returns_placed_item(self):
        chair = make_chair()
        placed = self.room.place(chair, 1000.0, 1000.0)
        assert isinstance(placed, PlacedItem)
        assert placed.x_mm == pytest.approx(1000.0)
        assert placed.y_mm == pytest.approx(1000.0)

    def test_placed_item_added_to_room(self):
        chair = make_chair()
        self.room.place(chair, 500.0, 500.0)
        assert len(self.room.items) == 1

    def test_place_multiple_items(self):
        for i in range(5):
            self.room.place(make_chair(), float(i * 600), 500.0)
        assert len(self.room.items) == 5

    def test_bounding_box(self):
        desk = make_desk(width_mm=1500.0, depth_mm=750.0)
        placed = self.room.place(desk, 0.0, 0.0)
        xmin, ymin, xmax, ymax = placed.bounding_box
        assert xmin == pytest.approx(0.0)
        assert ymin == pytest.approx(0.0)
        assert xmax == pytest.approx(1500.0)
        assert ymax == pytest.approx(750.0)

    def test_display_name_uses_label(self):
        chair = make_chair(name="Default Chair")
        placed = self.room.place(chair, 0.0, 0.0, label="Reception Chair")
        assert placed.display_name == "Reception Chair"

    def test_display_name_falls_back_to_item_name(self):
        chair = make_chair(name="Task Chair")
        placed = self.room.place(chair, 0.0, 0.0)
        assert placed.display_name == "Task Chair"


class TestCirculationPaths:
    def setup_method(self):
        self.room = make_room("Test", 6000.0, 5000.0)

    def test_add_path(self):
        path = self.room.add_circulation_path(
            "Main aisle", (0.0, 2500.0), (6000.0, 2500.0), 1200.0
        )
        assert path.clear_width_mm == pytest.approx(1200.0)
        assert len(self.room.circulation_paths) == 1

    def test_path_length(self):
        path = self.room.add_circulation_path(
            "Horizontal", (0.0, 0.0), (3000.0, 4000.0), 1000.0
        )
        # 3-4-5 triangle scaled by 1000
        assert path.length_mm == pytest.approx(5000.0, abs=1.0)

    def test_compliant_path_no_violations(self):
        self.room.add_circulation_path(
            "Wide aisle", (0.0, 0.0), (6000.0, 0.0), 1200.0
        )
        violations = self.room.audit_circulation()
        assert violations == []

    def test_narrow_path_fires_violation(self):
        # 800 mm < 914 mm ADA minimum
        self.room.add_circulation_path(
            "Narrow aisle", (0.0, 0.0), (6000.0, 0.0), 800.0
        )
        violations = self.room.audit_circulation()
        assert len(violations) == 1
        assert violations[0].rule == "corridor_width"

    def test_borderline_903mm_fires(self):
        # 903 mm < 914 mm
        self.room.add_circulation_path("Tight", (0, 0), (1000, 0), 903.0)
        violations = self.room.audit_circulation()
        assert len(violations) >= 1

    def test_exactly_914mm_compliant(self):
        self.room.add_circulation_path("Exact", (0, 0), (1000, 0), 914.0)
        violations = self.room.audit_circulation()
        assert violations == []


# ==========================================================================
# space_planning.py — ADA audit integration
# ==========================================================================

class TestAuditAll:
    def setup_method(self):
        self.room = make_room("Meeting Room", 8000.0, 5000.0)

    def test_empty_room_no_violations(self):
        violations = self.room.audit_all()
        assert violations == []

    def test_turning_diameter_pass(self):
        violations = self.room.audit_all(turning_diameter_mm=1600.0)
        assert violations == []

    def test_turning_diameter_fail(self):
        violations = self.room.audit_all(turning_diameter_mm=1000.0)
        rules = {v.rule for v in violations}
        assert "turning_radius" in rules

    def test_reach_heights_pass(self):
        violations = self.room.audit_all(reach_heights_mm=[900.0, 1100.0])
        assert violations == []

    def test_reach_heights_fail_high(self):
        # 1300 mm > 1219 mm
        violations = self.room.audit_all(reach_heights_mm=[1300.0])
        rules = {v.rule for v in violations}
        assert "reach_range_high" in rules

    def test_full_scenario(self):
        """A configured room with desk, circulation, and reach heights."""
        desk = make_desk()
        self.room.place(desk, 200.0, 200.0)
        self.room.add_circulation_path("Main", (0, 2500), (8000, 2500), 1200.0)
        violations = self.room.audit_all(
            turning_diameter_mm=1524.0,
            reach_heights_mm=[1100.0],
        )
        assert violations == []

    def test_summary_has_expected_keys(self):
        summary = self.room.summary()
        for key in ("name", "width_mm", "depth_mm", "area_m2",
                    "item_count", "circulation_path_count",
                    "ada_violations", "violations"):
            assert key in summary, f"Missing key: {key!r}"

    def test_summary_violation_count(self):
        self.room.add_circulation_path("Narrow", (0, 0), (1000, 0), 700.0)
        summary = self.room.summary()
        assert summary["ada_violations"] >= 1

    def test_placed_item_to_dict(self):
        desk = make_desk()
        placed = self.room.place(desk, 0.0, 0.0)
        d = placed.to_dict()
        assert d["x_mm"] == pytest.approx(0.0)
        assert d["y_mm"] == pytest.approx(0.0)
        assert "item" in d


# ==========================================================================
# Integration: turning-circle oracle
# ==========================================================================

class TestTurningCircleOracle:
    """The pytest oracle from the task brief: ADA turning circle = 1524 ± 5 mm."""

    def test_canonical_value_within_5mm(self):
        d = turning_circle_diameter_mm()
        assert abs(d - 1524.0) <= 5.0, (
            f"turning_circle_diameter_mm() = {d} is outside 1524 ± 5 mm"
        )

    def test_check_fires_below_tolerance_bracket(self):
        # 1518 mm is outside 1524 - 5 = 1519 mm lower bound
        v = check_turning_radius(1518.0)
        assert len(v) == 1

    def test_check_passes_inside_tolerance_bracket(self):
        # 1519 mm is exactly at the 5 mm tolerance lower bound → should pass
        v = check_turning_radius(1519.0)
        assert v == []

    def test_check_passes_at_nominal(self):
        assert check_turning_radius(1524.0) == []

    def test_check_passes_above_nominal(self):
        assert check_turning_radius(1600.0) == []


# ==========================================================================
# Integration: reach-range oracle
# ==========================================================================

class TestReachRangeOracle:
    """Oracle: reach-range high check fires at > 48 in / 1219 mm."""

    @pytest.mark.parametrize("height", [1220.0, 1300.0, 1500.0, 2000.0])
    def test_fires_above_1219mm(self, height):
        violations = check_reach_range(height)
        rules = {v.rule for v in violations}
        assert "reach_range_high" in rules, (
            f"Expected reach_range_high violation at {height} mm, got {rules}"
        )

    @pytest.mark.parametrize("height", [381.0, 500.0, 900.0, 1219.0])
    def test_no_high_violation_at_or_below_1219mm(self, height):
        violations = check_reach_range(height)
        high_violations = [v for v in violations if v.rule == "reach_range_high"]
        assert high_violations == [], (
            f"Unexpected reach_range_high violation at {height} mm"
        )


# ==========================================================================
# Integration: corridor clearance oracle
# ==========================================================================

class TestCorridorClearanceOracle:
    """Oracle: corridor check fires when corridor < 36 in / 914 mm."""

    @pytest.mark.parametrize("width", [913.0, 800.0, 500.0, 1.0])
    def test_fires_below_914mm(self, width):
        violations = check_corridor_clearance(width)
        assert len(violations) == 1
        assert violations[0].rule == "corridor_width", (
            f"Expected corridor_width violation at {width} mm"
        )

    @pytest.mark.parametrize("width", [914.0, 1000.0, 1200.0, 2000.0])
    def test_no_violation_at_or_above_914mm(self, width):
        violations = check_corridor_clearance(width)
        assert violations == [], (
            f"Unexpected violation at {width} mm: {violations}"
        )
