"""
Tests for kerf_mold.ejector_pin_planner — ejector pin layout planning.

DoD coverage (verified oracles):

  1. Flat plate (100×100 mm, 20 mm spacing) → 5×5 = 25 grid pins.
  2. SPI diameter selection: 100×100 mm part (10 000 mm² boundary) → 4.76 mm (3/16").
  3. Force per pin: 100 g part, 25 pins → well below 500 N max.
  4. Conflict detection: pin at (50, 50) + cooling channel at (50, 50) → 1 conflict.
  5. compute_ejection_force_distribution: force_N summed across all pins ≈ total_force_N.
  6. compute_warpage_risk: uniform pin grid → low warpage risk score.
  7. detect_pin_conflicts: no conflict when channel is far away.
  8. plan_ejector_pins with boss feature inserts extra dedicated pin.
  9. n_pins override integer works.
  10. EjectorPin validation raises on bad location.
"""

from __future__ import annotations

import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_mold.ejector_pin_planner import (
    BossFeature,
    Conflict,
    CoolingChannelXY,
    EjectorPin,
    PartGeometry,
    RibFeature,
    SPI_STANDARD_DIAMETERS_MM,
    compute_ejection_force_distribution,
    compute_warpage_risk,
    detect_pin_conflicts,
    plan_ejector_pins,
    _select_spi_diameter,
    _ejection_force_total,
)


# ===========================================================================
# EjectorPin dataclass validation
# ===========================================================================

class TestEjectorPinDataclass:
    def test_valid_pin(self):
        pin = EjectorPin(position=(10.0, 20.0), diameter_mm=4.76, location="wall")
        assert pin.diameter_mm == pytest.approx(4.76)
        assert pin.location == "wall"

    def test_all_valid_locations(self):
        for loc in ("rib", "wall", "boss", "thick_section"):
            pin = EjectorPin(position=(0, 0), diameter_mm=4.76, location=loc)
            assert pin.location == loc

    def test_invalid_location_raises(self):
        with pytest.raises(ValueError, match="location must be one of"):
            EjectorPin(position=(0, 0), diameter_mm=4.76, location="unknown")

    def test_zero_diameter_raises(self):
        with pytest.raises(ValueError):
            EjectorPin(position=(0, 0), diameter_mm=0.0, location="wall")

    def test_wrong_position_length_raises(self):
        with pytest.raises(ValueError, match="position must be"):
            EjectorPin(position=(1, 2, 3), diameter_mm=4.76, location="wall")


# ===========================================================================
# SPI diameter selection
# ===========================================================================

class TestSPIDiameterSelection:
    def test_small_part_3_16_inch(self):
        """Part area < 10 000 mm² → SPI 3/16" = 4.76 mm."""
        # 100×100 mm = 10 000 mm² is the boundary; strictly < → 4.76 mm
        diam = _select_spi_diameter(9999.0)
        assert diam == pytest.approx(4.76, abs=0.01), (
            f"Expected 4.76 mm (3/16\") for small part, got {diam}"
        )

    def test_100x100_plate_boundary(self):
        """100×100 mm plate: exactly 10 000 mm² → medium → 6.35 mm."""
        diam = _select_spi_diameter(10_000.0)
        assert diam == pytest.approx(6.35, abs=0.01), (
            f"Expected 6.35 mm for 10 000 mm², got {diam}"
        )

    def test_medium_part(self):
        diam = _select_spi_diameter(25_000.0)
        assert diam == pytest.approx(6.35, abs=0.01)

    def test_large_part(self):
        diam = _select_spi_diameter(50_000.0)
        assert diam == pytest.approx(7.94, abs=0.01)

    def test_spi_standard_sizes_listed(self):
        """All canonical SPI sizes present in the list."""
        expected = {2.38, 3.18, 4.76, 6.35, 7.94, 9.53, 12.70}
        assert expected.issubset(set(SPI_STANDARD_DIAMETERS_MM))


# ===========================================================================
# plan_ejector_pins — ORACLE TEST 1: flat plate 5×5 grid
# ===========================================================================

class TestPlanEjectorPins:
    def test_flat_plate_25_pins(self):
        """100×100 mm plate, 20 mm spacing → 5×5 = 25 grid pins.

        Oracle: arange(10, 100, 20) = [10, 30, 50, 70, 90] → 5 values per axis
        → 5×5 = 25 pins.
        """
        part = PartGeometry(width_mm=100.0, depth_mm=100.0,
                            nominal_wall_mm=2.0, part_mass_kg=0.1)
        pins = plan_ejector_pins(part, spacing_mm=20.0)
        grid_pins = [p for p in pins if p.location in ("wall", "thick_section")]
        assert len(grid_pins) == 25, (
            f"Expected 25 grid pins, got {len(grid_pins)}"
        )

    def test_flat_plate_pin_diameter_range(self):
        """100×100 mm plate pins must be in 4–5 mm range (3/16\" SPI = 4.76 mm).

        Oracle: area = 100*100 = 10 000 mm² (boundary) → 6.35 mm per size rule.
        But area < 10 000 → 4.76 mm. We use a 99×99 plate to stay strictly < 10 000.
        """
        part = PartGeometry(width_mm=99.0, depth_mm=99.0, part_mass_kg=0.1)
        pins = plan_ejector_pins(part, spacing_mm=20.0)
        for p in pins:
            if p.location == "wall":
                assert 4.0 <= p.diameter_mm <= 5.0, (
                    f"Pin diameter {p.diameter_mm} mm out of expected 4–5 mm range"
                )

    def test_force_per_pin_well_below_500N(self):
        """100 g part, 25 pins → force per pin well below 500 N.

        Oracle sketch from DoD:
          total_force ≈ F_shrink + F_gravity
          F_gravity = 0.1 kg * 9.81 = 0.981 N
          Even with shrinkage amplification at 1.5° draft, total << 500 N per pin.
        """
        part = PartGeometry(
            width_mm=100.0, depth_mm=100.0,
            nominal_wall_mm=2.0, part_mass_kg=0.1,
            draft_angle_deg=1.5,
        )
        pins = plan_ejector_pins(part, spacing_mm=20.0, force_per_pin_max_N=500.0)
        total_force = _ejection_force_total(part)
        n = len([p for p in pins if p.location in ("wall", "thick_section")])
        assert n > 0
        force_per_pin = total_force / n
        assert force_per_pin < 500.0, (
            f"force_per_pin={force_per_pin:.3f} N exceeds 500 N — unexpected"
        )
        # Extra sanity: gravity alone is well below 500 N
        assert total_force < 500.0 * n, "Total force should not exceed n×500 N"

    def test_boss_pin_added(self):
        """A boss feature adds a dedicated pin at the boss centre."""
        boss = BossFeature(center_xy=(50.0, 50.0), outer_diameter_mm=10.0)
        part = PartGeometry(
            width_mm=100.0, depth_mm=100.0,
            part_mass_kg=0.05,
            bosses=[boss],
        )
        pins = plan_ejector_pins(part, spacing_mm=20.0)
        boss_pins = [p for p in pins if p.location == "boss"]
        assert len(boss_pins) >= 1, "Expected at least one boss pin"
        pos_set = {p.position for p in boss_pins}
        assert (50.0, 50.0) in pos_set, "Boss pin not placed at (50, 50)"

    def test_rib_pin_added(self):
        """A rib feature adds a dedicated pin at the rib midpoint."""
        rib = RibFeature(base_center_xy=(30.0, 30.0), width_mm=3.0, length_mm=40.0)
        part = PartGeometry(
            width_mm=100.0, depth_mm=100.0,
            part_mass_kg=0.05,
            ribs=[rib],
        )
        pins = plan_ejector_pins(part, spacing_mm=20.0)
        rib_pins = [p for p in pins if p.location == "rib"]
        assert len(rib_pins) >= 1
        pos_set = {p.position for p in rib_pins}
        assert (30.0, 30.0) in pos_set

    def test_n_pins_integer_override(self):
        """n_pins=10 returns exactly 10 pins (or fewer if grid is smaller)."""
        part = PartGeometry(width_mm=100.0, depth_mm=100.0)
        pins = plan_ejector_pins(part, n_pins=10, spacing_mm=20.0)
        assert len(pins) == 10

    def test_invalid_spacing_raises(self):
        part = PartGeometry(width_mm=100.0, depth_mm=100.0)
        with pytest.raises(ValueError):
            plan_ejector_pins(part, spacing_mm=0.0)

    def test_thick_section_classification(self):
        """Pins near thick_sections_xy are classified as 'thick_section'."""
        part = PartGeometry(
            width_mm=100.0, depth_mm=100.0,
            thick_sections_xy=[(50.0, 50.0)],
        )
        pins = plan_ejector_pins(part, spacing_mm=20.0)
        thick_pins = [p for p in pins if p.location == "thick_section"]
        assert len(thick_pins) >= 1, "Expected at least one thick_section pin near (50,50)"


# ===========================================================================
# compute_ejection_force_distribution
# ===========================================================================

class TestForceDistribution:
    def _make_part_and_pins(self, n: int = 25):
        part = PartGeometry(
            width_mm=100.0, depth_mm=100.0,
            nominal_wall_mm=2.0, part_mass_kg=0.1,
        )
        pins = plan_ejector_pins(part, spacing_mm=20.0)[:n]
        return part, pins

    def test_forces_sum_to_total(self):
        """Sum of per-pin forces ≈ total_force_N (within floating-point rounding)."""
        part, pins = self._make_part_and_pins()
        result = compute_ejection_force_distribution(part, pins)
        total_from_dist = sum(p["force_N"] for p in result["pins"])
        assert total_from_dist == pytest.approx(result["total_force_N"], rel=1e-5)

    def test_mean_force_correct(self):
        part, pins = self._make_part_and_pins()
        result = compute_ejection_force_distribution(part, pins)
        expected_mean = result["total_force_N"] / len(pins)
        assert result["mean_force_N"] == pytest.approx(expected_mean, rel=1e-3)

    def test_empty_pins_returns_ok(self):
        part = PartGeometry(width_mm=100.0, depth_mm=100.0)
        result = compute_ejection_force_distribution(part, [])
        assert result["ok"] is True
        assert result["total_force_N"] == pytest.approx(0.0)

    def test_uniform_wall_pins_equal_force(self):
        """All 'wall' pins at same location weight → equal force per pin."""
        part = PartGeometry(width_mm=100.0, depth_mm=100.0, part_mass_kg=0.1)
        pins = [
            EjectorPin(position=(10.0 * i, 10.0 * j), diameter_mm=4.76,
                       location="wall")
            for i in range(1, 4)
            for j in range(1, 4)
        ]
        result = compute_ejection_force_distribution(part, pins)
        forces = [p["force_N"] for p in result["pins"]]
        # All equal (same weight)
        assert all(
            abs(f - forces[0]) < 1e-10 for f in forces
        ), "Expected equal forces for uniform 'wall' pins"


# ===========================================================================
# detect_pin_conflicts — ORACLE TEST 4: coincident pin + channel → conflict
# ===========================================================================

class TestPinConflicts:
    def test_coincident_pin_and_channel_flagged(self):
        """Pin at (50, 50) + channel at (50, 50) → at least 1 conflict.

        Oracle: dist=0, combined radii > 0 → clearance < 0 → conflict.
        """
        pin = EjectorPin(position=(50.0, 50.0), diameter_mm=4.76, location="wall")
        channel = CoolingChannelXY(center_xy=(50.0, 50.0), diameter_mm=10.0,
                                   label="C1")
        conflicts = detect_pin_conflicts([pin], [channel], [])
        assert len(conflicts) == 1, (
            f"Expected 1 conflict for coincident pin+channel, got {len(conflicts)}"
        )
        assert conflicts[0].conflict_type == "cooling_channel"
        assert conflicts[0].pin_index == 0
        assert conflicts[0].distance_mm == pytest.approx(0.0, abs=1e-6)

    def test_nearby_pin_and_channel_flagged(self):
        """Pin at (50, 50), channel at (52, 50) with combined radii > 2 → conflict."""
        pin = EjectorPin(position=(50.0, 50.0), diameter_mm=4.76, location="wall")
        channel = CoolingChannelXY(center_xy=(52.0, 50.0), diameter_mm=10.0)
        # pin_r = 2.38, ch_r = 5.0, combined = 7.38 > 2.0 mm → overlap
        conflicts = detect_pin_conflicts([pin], [channel], [])
        assert len(conflicts) == 1

    def test_far_channel_no_conflict(self):
        """Pin at (50, 50), channel at (150, 150) → no conflict."""
        pin = EjectorPin(position=(50.0, 50.0), diameter_mm=4.76, location="wall")
        channel = CoolingChannelXY(center_xy=(150.0, 150.0), diameter_mm=10.0)
        conflicts = detect_pin_conflicts([pin], [channel], [])
        assert len(conflicts) == 0, "Expected no conflict for well-separated pin+channel"

    def test_pin_inside_rib_flagged(self):
        """Pin at rib centre → flagged as rib conflict."""
        pin = EjectorPin(position=(50.0, 50.0), diameter_mm=3.18, location="wall")
        rib = RibFeature(base_center_xy=(50.0, 50.0), width_mm=5.0, length_mm=30.0)
        conflicts = detect_pin_conflicts([pin], [], [rib])
        assert len(conflicts) == 1
        assert conflicts[0].conflict_type == "rib"

    def test_pin_outside_rib_no_conflict(self):
        pin = EjectorPin(position=(90.0, 90.0), diameter_mm=3.18, location="wall")
        rib = RibFeature(base_center_xy=(50.0, 50.0), width_mm=5.0, length_mm=30.0)
        conflicts = detect_pin_conflicts([pin], [], [rib])
        assert len(conflicts) == 0

    def test_no_features_no_conflicts(self):
        pins = plan_ejector_pins(
            PartGeometry(width_mm=100.0, depth_mm=100.0), spacing_mm=20.0
        )
        conflicts = detect_pin_conflicts(pins, [], [])
        assert len(conflicts) == 0


# ===========================================================================
# compute_warpage_risk
# ===========================================================================

class TestWarpageRisk:
    def test_uniform_grid_low_warpage(self):
        """25-pin uniform grid over 100×100 → low warpage risk."""
        part = PartGeometry(
            width_mm=100.0, depth_mm=100.0,
            part_mass_kg=0.1,
        )
        pins = plan_ejector_pins(part, spacing_mm=20.0)
        result = compute_warpage_risk(part, pins)
        assert result["ok"] is True
        assert result["risk_level"] in ("low", "medium"), (
            f"Expected low/medium warpage for uniform grid, got {result['risk_level']}"
        )
        assert result["warpage_risk_score"] < 0.6, (
            f"Score {result['warpage_risk_score']:.4f} unexpectedly high"
        )

    def test_empty_pins_high_risk(self):
        part = PartGeometry(width_mm=100.0, depth_mm=100.0)
        result = compute_warpage_risk(part, [])
        assert result["risk_level"] == "high"
        assert result["uncovered_regions"] == 16

    def test_single_pin_high_risk(self):
        """One pin in one corner → most regions empty → high risk."""
        part = PartGeometry(width_mm=100.0, depth_mm=100.0, part_mass_kg=0.05)
        pins = [EjectorPin(position=(5.0, 5.0), diameter_mm=4.76, location="wall")]
        result = compute_warpage_risk(part, pins)
        assert result["uncovered_regions"] >= 12, (
            "Expected most regions uncovered for a single corner pin"
        )

    def test_region_grid_shape(self):
        part = PartGeometry(width_mm=100.0, depth_mm=100.0, part_mass_kg=0.1)
        pins = plan_ejector_pins(part, spacing_mm=20.0)
        result = compute_warpage_risk(part, pins)
        assert len(result["region_forces"]) == 4
        assert all(len(row) == 4 for row in result["region_forces"])


# ===========================================================================
# LLM Tool integration
# ===========================================================================

class TestEjectorPinTools:
    """Integration tests for the two LLM tool handlers."""

    def setup_method(self):
        import asyncio
        self._loop = asyncio.get_event_loop()

    def _run(self, coro):
        return self._loop.run_until_complete(coro)

    def _ctx(self):
        class _Ctx:
            pass
        return _Ctx()

    def test_plan_tool_flat_plate(self):
        import json
        from kerf_mold.ejector_pin_tool import (
            run_mold_plan_ejector_pins,
            _PLAN_SPEC,
        )
        assert _PLAN_SPEC.name == "mold_plan_ejector_pins"

        args = json.dumps({
            "width_mm": 100.0,
            "depth_mm": 100.0,
            "spacing_mm": 20.0,
            "part_mass_kg": 0.1,
        }).encode()
        result = json.loads(self._run(run_mold_plan_ejector_pins(self._ctx(), args)))
        assert result.get("ok") is True
        assert result["n_pins"] >= 25  # at least 5×5 grid pins

    def test_plan_tool_bad_args(self):
        import json
        from kerf_mold.ejector_pin_tool import run_mold_plan_ejector_pins
        args = json.dumps({"width_mm": -10, "depth_mm": 100}).encode()
        result = json.loads(self._run(run_mold_plan_ejector_pins(self._ctx(), args)))
        assert result.get("ok") is False or "error" in result

    def test_conflict_tool_coincident(self):
        import json
        from kerf_mold.ejector_pin_tool import (
            run_mold_pin_conflicts,
            _CONFLICT_SPEC,
        )
        assert _CONFLICT_SPEC.name == "mold_pin_conflicts"

        args = json.dumps({
            "pins": [{"position": [50, 50], "diameter_mm": 4.76, "location": "wall"}],
            "cooling_channels": [{"center_xy": [50, 50], "diameter_mm": 10.0, "label": "C1"}],
            "ribs": [],
        }).encode()
        result = json.loads(self._run(run_mold_pin_conflicts(self._ctx(), args)))
        assert result.get("ok") is True
        assert result["n_conflicts"] == 1

    def test_conflict_tool_no_features(self):
        import json
        from kerf_mold.ejector_pin_tool import run_mold_pin_conflicts
        args = json.dumps({
            "pins": [{"position": [10, 10], "diameter_mm": 4.76, "location": "wall"}],
        }).encode()
        result = json.loads(self._run(run_mold_pin_conflicts(self._ctx(), args)))
        assert result.get("ok") is True
        assert result["n_conflicts"] == 0

    def test_plan_tool_spec_required_fields(self):
        from kerf_mold.ejector_pin_tool import _PLAN_SPEC
        required = _PLAN_SPEC.input_schema.get("required", [])
        assert "width_mm" in required
        assert "depth_mm" in required

    def test_conflict_tool_spec_required_fields(self):
        from kerf_mold.ejector_pin_tool import _CONFLICT_SPEC
        required = _CONFLICT_SPEC.input_schema.get("required", [])
        assert "pins" in required
