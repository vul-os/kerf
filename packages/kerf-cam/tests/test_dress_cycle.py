"""
Tests for kerf_cam.dress_cycle — grinding wheel dressing cycle G-code generator.

References
----------
* Machinery's Handbook 31e §1145 — Wheel dressing
* Sandvik Coromant CoroGrind Grinding Handbook §5 — Wheel conditioning

Run (from repo root):
    pytest packages/kerf-cam/tests/test_dress_cycle.py -v
"""

from __future__ import annotations

import asyncio
import json
import math
import re

import pytest

from kerf_cam.dress_cycle import (
    DressSpec,
    DressCycleResult,
    _fmt,
    _estimate_dress_time,
    _recommended_traverse,
    _dress_advisory,
    generate_dress_cycle,
    cam_generate_dress_cycle_spec,
    run_cam_generate_dress_cycle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(
    wheel_diameter_mm: float = 200.0,
    wheel_width_mm: float = 25.0,
    dresser_type: str = "single_point_diamond",
    depth_per_pass_mm: float = 0.05,
    total_dress_amount_mm: float = 0.25,
    traverse_rate_mm_per_min: float = 100.0,
    dress_x_start_mm: float = -105.0,
    dress_z_start_mm: float = 0.0,
) -> DressSpec:
    """Return a DressSpec with sensible defaults, overrideable via kwargs."""
    return DressSpec(
        wheel_diameter_mm=wheel_diameter_mm,
        wheel_width_mm=wheel_width_mm,
        dresser_type=dresser_type,
        depth_per_pass_mm=depth_per_pass_mm,
        total_dress_amount_mm=total_dress_amount_mm,
        traverse_rate_mm_per_min=traverse_rate_mm_per_min,
        dress_x_start_mm=dress_x_start_mm,
        dress_z_start_mm=dress_z_start_mm,
    )


def _run_async(coro):
    return asyncio.run(coro)


def _ctx():
    from kerf_cam._compat import ProjectCtx
    return ProjectCtx()


# ---------------------------------------------------------------------------
# 1. Pass count arithmetic (task requirement test case)
# ---------------------------------------------------------------------------

class TestPassCount:
    def test_canonical_5_passes(self):
        """Wheel 200mm OD, 25mm wide, single-point, 0.05mm/pass, 0.25mm total → 5 passes."""
        result = generate_dress_cycle(_spec(
            wheel_diameter_mm=200.0,
            wheel_width_mm=25.0,
            dresser_type="single_point_diamond",
            depth_per_pass_mm=0.05,
            total_dress_amount_mm=0.25,
        ))
        assert result.num_passes == 5

    def test_pass_count_ceil_rounding(self):
        """Non-integer division rounds up: 0.25 / 0.06 = 4.17 → 5 passes."""
        result = generate_dress_cycle(_spec(
            depth_per_pass_mm=0.06,
            total_dress_amount_mm=0.25,
        ))
        assert result.num_passes == math.ceil(0.25 / 0.06)

    def test_single_pass_exact(self):
        """total == depth → exactly 1 pass."""
        result = generate_dress_cycle(_spec(
            depth_per_pass_mm=0.01,
            total_dress_amount_mm=0.01,
        ))
        assert result.num_passes == 1

    def test_large_total_increases_passes(self):
        """Increasing total_dress_amount must increase num_passes."""
        r_small = generate_dress_cycle(_spec(total_dress_amount_mm=0.10))
        r_large = generate_dress_cycle(_spec(total_dress_amount_mm=0.50))
        assert r_large.num_passes > r_small.num_passes

    def test_smaller_depth_increases_passes(self):
        """Halving depth_per_pass should double num_passes (exact case)."""
        r_coarse = generate_dress_cycle(_spec(depth_per_pass_mm=0.05, total_dress_amount_mm=0.20))
        r_fine = generate_dress_cycle(_spec(depth_per_pass_mm=0.025, total_dress_amount_mm=0.20))
        assert r_fine.num_passes == 2 * r_coarse.num_passes


# ---------------------------------------------------------------------------
# 2. Cycle time — task requirement
# ---------------------------------------------------------------------------

class TestCycleTime:
    def test_cycle_time_positive(self):
        result = generate_dress_cycle(_spec())
        assert result.machining_time_s > 0.0

    def test_higher_traverse_rate_reduces_time(self):
        """Higher traverse rate → shorter cycle time (task requirement)."""
        slow = generate_dress_cycle(_spec(traverse_rate_mm_per_min=50.0))
        fast = generate_dress_cycle(_spec(traverse_rate_mm_per_min=250.0))
        assert fast.machining_time_s < slow.machining_time_s

    def test_more_passes_increases_time(self):
        """More passes (larger total) → longer cycle time."""
        r_few = generate_dress_cycle(_spec(total_dress_amount_mm=0.10))
        r_many = generate_dress_cycle(_spec(total_dress_amount_mm=0.50))
        assert r_many.machining_time_s > r_few.machining_time_s

    def test_cycle_time_scales_with_wheel_width(self):
        """Wider wheel → more traverse distance → longer time."""
        narrow = generate_dress_cycle(_spec(wheel_width_mm=10.0))
        wide = generate_dress_cycle(_spec(wheel_width_mm=50.0))
        assert wide.machining_time_s > narrow.machining_time_s

    def test_cycle_time_estimate_formula(self):
        """Unit-check _estimate_dress_time against manual calculation.

        5 passes, 25mm wheel, 100mm/min traverse, 3000mm/min rapid retract:
          traverse/pass = (25/100)*60 = 15 s
          retract/pass  = (25/3000)*60 = 0.5 s
          total         = 5 * (15 + 0.5) = 77.5 s
        """
        s = _spec(
            wheel_width_mm=25.0,
            traverse_rate_mm_per_min=100.0,
            depth_per_pass_mm=0.05,
            total_dress_amount_mm=0.25,
        )
        t = _estimate_dress_time(s, 5)
        expected = 5 * ((25.0 / 100.0) * 60.0 + (25.0 / 3000.0) * 60.0)
        assert abs(t - expected) < 0.01


# ---------------------------------------------------------------------------
# 3. Total dress distance
# ---------------------------------------------------------------------------

class TestTotalDressDistance:
    def test_total_distance_equals_passes_times_width(self):
        """total_dress_distance_mm = num_passes × wheel_width_mm."""
        s = _spec(wheel_width_mm=25.0, depth_per_pass_mm=0.05, total_dress_amount_mm=0.25)
        result = generate_dress_cycle(s)
        expected = result.num_passes * 25.0
        assert abs(result.total_dress_distance_mm - expected) < 1e-6

    def test_total_distance_increases_with_more_passes(self):
        r1 = generate_dress_cycle(_spec(total_dress_amount_mm=0.10))
        r2 = generate_dress_cycle(_spec(total_dress_amount_mm=0.50))
        assert r2.total_dress_distance_mm > r1.total_dress_distance_mm


# ---------------------------------------------------------------------------
# 4. G-code program structure (NIST RS-274/NGC §3.5)
# ---------------------------------------------------------------------------

class TestGCodeStructure:
    def test_percent_delimiters(self):
        """RS-274/NGC programs must start and end with %."""
        result = generate_dress_cycle(_spec())
        lines = result.gcode.strip().split("\n")
        assert lines[0].strip() == "%"
        assert lines[-1].strip() == "%"

    def test_declares_g21_metric(self):
        result = generate_dress_cycle(_spec())
        assert "G21" in result.gcode

    def test_declares_g90_absolute(self):
        result = generate_dress_cycle(_spec())
        assert "G90" in result.gcode

    def test_declares_g94_feed_per_min(self):
        result = generate_dress_cycle(_spec())
        assert "G94" in result.gcode

    def test_g28_reference_return_at_end(self):
        """G28 return-to-reference must be present after dressing passes."""
        result = generate_dress_cycle(_spec())
        assert "G28" in result.gcode

    def test_m30_end_of_program(self):
        result = generate_dress_cycle(_spec())
        assert "M30" in result.gcode

    def test_m05_spindle_off(self):
        result = generate_dress_cycle(_spec())
        assert "M05" in result.gcode

    def test_rapid_to_start_present(self):
        """First motion should be G00 rapid to dress start."""
        result = generate_dress_cycle(_spec())
        g00_lines = [ln for ln in result.gcode.splitlines() if ln.startswith("G00")]
        assert g00_lines, "Expected at least one G00 rapid move"

    def test_traverse_g01_with_f_word(self):
        """Traverse passes must emit G01 with F (feed) word."""
        result = generate_dress_cycle(_spec())
        g01_traverse = [
            ln for ln in result.gcode.splitlines()
            if ln.startswith("G01") and "F" in ln and "Z" in ln
        ]
        assert g01_traverse, "Expected G01 traverse lines with F word"

    def test_correct_pass_count_blocks_in_gcode(self):
        """Number of '(Pass N of M)' comment lines equals num_passes."""
        result = generate_dress_cycle(_spec(
            depth_per_pass_mm=0.05, total_dress_amount_mm=0.25
        ))
        pass_comments = [
            ln for ln in result.gcode.splitlines()
            if ln.startswith("(Pass ") and "of" in ln
        ]
        assert len(pass_comments) == result.num_passes


# ---------------------------------------------------------------------------
# 5. G-code field values
# ---------------------------------------------------------------------------

class TestGCodeFieldValues:
    def test_traverse_end_z_equals_start_plus_width(self):
        """Z traverse endpoint = dress_z_start_mm + wheel_width_mm."""
        s = _spec(dress_z_start_mm=10.0, wheel_width_mm=30.0)
        result = generate_dress_cycle(s)
        expected_z = 10.0 + 30.0  # 40.0
        # Look for G01 Z40.0 in gcode
        assert f"Z{_fmt(expected_z)}" in result.gcode

    def test_traverse_rate_in_f_word(self):
        """F word must match traverse_rate_mm_per_min."""
        s = _spec(traverse_rate_mm_per_min=150.0)
        result = generate_dress_cycle(s)
        # G01 traverse lines must contain F150.0
        traverse_lines = [
            ln for ln in result.gcode.splitlines()
            if ln.startswith("G01") and "F" in ln
        ]
        assert any("F150.0" in ln for ln in traverse_lines), (
            f"Expected F150.0 in traverse lines; got: {traverse_lines}"
        )

    def test_infeed_x_decrements_per_pass(self):
        """Each pass should infeed X further (more negative) than the previous."""
        s = _spec(
            dress_x_start_mm=-100.0,
            depth_per_pass_mm=0.05,
            total_dress_amount_mm=0.15,
        )
        result = generate_dress_cycle(s)
        # Extract X values from G01 infeed lines (G01 X... without Z/F)
        infeed_xs = []
        for ln in result.gcode.splitlines():
            if ln.startswith("G01 X") and "Z" not in ln and "F" not in ln:
                m = re.match(r"G01 X(-?\d+\.?\d*)", ln)
                if m:
                    infeed_xs.append(float(m.group(1)))
        assert len(infeed_xs) == result.num_passes, (
            f"Expected {result.num_passes} infeed lines, got {len(infeed_xs)}"
        )
        for j in range(1, len(infeed_xs)):
            assert infeed_xs[j] < infeed_xs[j - 1], (
                f"X infeed must decrease each pass; pass {j}: {infeed_xs[j]} >= {infeed_xs[j-1]}"
            )

    def test_z_retract_returns_to_start(self):
        """After each traverse, G00 must retract Z to dress_z_start_mm."""
        s = _spec(dress_z_start_mm=5.0, wheel_width_mm=20.0)
        result = generate_dress_cycle(s)
        retract_lines = [
            ln for ln in result.gcode.splitlines()
            if ln.startswith("G00 Z")
        ]
        assert retract_lines, "Expected G00 Z retract lines"
        for ln in retract_lines:
            assert f"Z{_fmt(5.0)}" in ln, (
                f"Retract line must return to Z=5.0; got: {ln!r}"
            )


# ---------------------------------------------------------------------------
# 6. Rotary diamond dresser
# ---------------------------------------------------------------------------

class TestRotaryDiamond:
    def test_rotary_diamond_accepted(self):
        s = _spec(dresser_type="rotary_diamond", depth_per_pass_mm=0.02,
                  traverse_rate_mm_per_min=200.0)
        result = generate_dress_cycle(s)
        assert result.num_passes > 0

    def test_rotary_diamond_in_gcode_header(self):
        s = _spec(dresser_type="rotary_diamond", depth_per_pass_mm=0.02,
                  traverse_rate_mm_per_min=200.0)
        result = generate_dress_cycle(s)
        assert "rotary_diamond" in result.gcode

    def test_rotary_recommended_traverse_higher(self):
        """Rotary diamond midpoint traverse rate > single-point midpoint."""
        sp_rec = _recommended_traverse("single_point_diamond")
        ro_rec = _recommended_traverse("rotary_diamond")
        assert ro_rec > sp_rec


# ---------------------------------------------------------------------------
# 7. DressSpec validation
# ---------------------------------------------------------------------------

class TestDressSpecValidation:
    def test_valid_spec_no_error(self):
        s = _spec()
        assert s.num_passes if False else True  # noqa (just checking no exception)

    def test_zero_wheel_diameter_raises(self):
        with pytest.raises(ValueError, match="wheel_diameter_mm"):
            _spec(wheel_diameter_mm=0.0)

    def test_negative_wheel_width_raises(self):
        with pytest.raises(ValueError, match="wheel_width_mm"):
            _spec(wheel_width_mm=-1.0)

    def test_zero_wheel_width_raises(self):
        with pytest.raises(ValueError, match="wheel_width_mm"):
            _spec(wheel_width_mm=0.0)

    def test_invalid_dresser_type_raises(self):
        with pytest.raises(ValueError, match="dresser_type"):
            _spec(dresser_type="cup_wheel")

    def test_zero_depth_per_pass_raises(self):
        with pytest.raises(ValueError, match="depth_per_pass_mm"):
            _spec(depth_per_pass_mm=0.0)

    def test_negative_depth_per_pass_raises(self):
        with pytest.raises(ValueError, match="depth_per_pass_mm"):
            _spec(depth_per_pass_mm=-0.01)

    def test_zero_total_dress_amount_raises(self):
        with pytest.raises(ValueError, match="total_dress_amount_mm"):
            _spec(total_dress_amount_mm=0.0)

    def test_zero_traverse_rate_raises(self):
        with pytest.raises(ValueError, match="traverse_rate_mm_per_min"):
            _spec(traverse_rate_mm_per_min=0.0)


# ---------------------------------------------------------------------------
# 8. Advisory / safe-band checking (MH 31e §1145)
# ---------------------------------------------------------------------------

class TestSafeBandAdvisory:
    def test_no_advisory_within_band(self):
        """Spec within MH 31e §1145 bands should produce no advisory text."""
        s = _spec(
            dresser_type="single_point_diamond",
            traverse_rate_mm_per_min=150.0,  # in [50, 300]
            depth_per_pass_mm=0.010,         # in [0.002, 0.025]
        )
        advisory = _dress_advisory(s)
        assert advisory == ""

    def test_advisory_for_slow_traverse(self):
        """Traverse rate below safe band must trigger advisory."""
        s = _spec(traverse_rate_mm_per_min=10.0)  # below 50 mm/min
        advisory = _dress_advisory(s)
        assert "traverse_rate" in advisory

    def test_advisory_for_deep_infeed(self):
        """Depth above safe band must trigger advisory."""
        s = _spec(depth_per_pass_mm=0.10)  # above 0.025 mm for single_point
        advisory = _dress_advisory(s)
        assert "depth_per_pass" in advisory

    def test_out_of_band_caveat_included_in_result(self):
        """Out-of-band spec must include ADVISORY in honest_caveat."""
        result = generate_dress_cycle(_spec(traverse_rate_mm_per_min=10.0))
        assert "ADVISORY" in result.honest_caveat


# ---------------------------------------------------------------------------
# 9. Honest caveat content
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    def test_caveat_mentions_open_loop(self):
        result = generate_dress_cycle(_spec())
        assert "open-loop" in result.honest_caveat.lower()

    def test_caveat_mentions_no_closed_loop(self):
        result = generate_dress_cycle(_spec())
        caveat_lower = result.honest_caveat.lower()
        assert "closed-loop" in caveat_lower or "ae" in caveat_lower

    def test_caveat_mentions_uni_directional(self):
        result = generate_dress_cycle(_spec())
        assert "uni-directional" in result.honest_caveat.lower()

    def test_caveat_mentions_mh31e(self):
        result = generate_dress_cycle(_spec())
        assert "MH 31e" in result.honest_caveat or "§1145" in result.honest_caveat

    def test_recommended_traverse_rate_correct_single_point(self):
        """Recommended traverse midpoint for single_point: (50+300)/2 = 175 mm/min."""
        result = generate_dress_cycle(_spec(dresser_type="single_point_diamond"))
        assert result.recommended_traverse_rate_mm_per_min == pytest.approx(175.0, abs=0.1)

    def test_recommended_traverse_rate_correct_rotary(self):
        """Recommended traverse midpoint for rotary: (100+800)/2 = 450 mm/min."""
        result = generate_dress_cycle(_spec(
            dresser_type="rotary_diamond",
            depth_per_pass_mm=0.02,
            traverse_rate_mm_per_min=300.0,
        ))
        assert result.recommended_traverse_rate_mm_per_min == pytest.approx(450.0, abs=0.1)


# ---------------------------------------------------------------------------
# 10. LLM tool (async, no DB)
# ---------------------------------------------------------------------------

class TestLLMTool:
    def test_tool_spec_name(self):
        assert cam_generate_dress_cycle_spec.name == "cam_generate_dress_cycle"

    def test_tool_canonical_5_passes(self):
        """Canonical test case: 200mm OD, 25mm wide, 0.05mm/pass, 0.25mm total → 5 passes."""
        ctx = _ctx()
        args = json.dumps({
            "wheel_diameter_mm": 200.0,
            "wheel_width_mm": 25.0,
            "dresser_type": "single_point_diamond",
            "depth_per_pass_mm": 0.05,
            "total_dress_amount_mm": 0.25,
            "traverse_rate_mm_per_min": 100.0,
            "dress_x_start_mm": -105.0,
            "dress_z_start_mm": 0.0,
        }).encode()
        raw = _run_async(run_cam_generate_dress_cycle(ctx, args))
        result = json.loads(raw)
        assert "gcode" in result
        assert result["num_passes"] == 5
        assert "G21" in result["gcode"]

    def test_tool_returns_honest_caveat(self):
        ctx = _ctx()
        args = json.dumps({
            "wheel_diameter_mm": 150.0,
            "wheel_width_mm": 20.0,
            "dresser_type": "single_point_diamond",
            "depth_per_pass_mm": 0.010,
            "total_dress_amount_mm": 0.10,
            "traverse_rate_mm_per_min": 100.0,
            "dress_x_start_mm": -80.0,
            "dress_z_start_mm": 0.0,
        }).encode()
        raw = _run_async(run_cam_generate_dress_cycle(ctx, args))
        result = json.loads(raw)
        assert "honest_caveat" in result
        assert len(result["honest_caveat"]) > 50

    def test_tool_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run_async(run_cam_generate_dress_cycle(ctx, b"not-json"))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_missing_required_field_returns_error(self):
        ctx = _ctx()
        args = json.dumps({
            "wheel_diameter_mm": 200.0,
            # missing most required fields
        }).encode()
        raw = _run_async(run_cam_generate_dress_cycle(ctx, args))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_invalid_dresser_type_returns_error(self):
        ctx = _ctx()
        args = json.dumps({
            "wheel_diameter_mm": 200.0,
            "wheel_width_mm": 25.0,
            "dresser_type": "cup_wheel",
            "depth_per_pass_mm": 0.05,
            "total_dress_amount_mm": 0.25,
            "traverse_rate_mm_per_min": 100.0,
            "dress_x_start_mm": -105.0,
            "dress_z_start_mm": 0.0,
        }).encode()
        raw = _run_async(run_cam_generate_dress_cycle(ctx, args))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_zero_depth_per_pass_returns_error(self):
        ctx = _ctx()
        args = json.dumps({
            "wheel_diameter_mm": 200.0,
            "wheel_width_mm": 25.0,
            "dresser_type": "single_point_diamond",
            "depth_per_pass_mm": 0.0,
            "total_dress_amount_mm": 0.25,
            "traverse_rate_mm_per_min": 100.0,
            "dress_x_start_mm": -105.0,
            "dress_z_start_mm": 0.0,
        }).encode()
        raw = _run_async(run_cam_generate_dress_cycle(ctx, args))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_rotary_diamond_accepted(self):
        ctx = _ctx()
        args = json.dumps({
            "wheel_diameter_mm": 250.0,
            "wheel_width_mm": 30.0,
            "dresser_type": "rotary_diamond",
            "depth_per_pass_mm": 0.02,
            "total_dress_amount_mm": 0.20,
            "traverse_rate_mm_per_min": 300.0,
            "dress_x_start_mm": -130.0,
            "dress_z_start_mm": 0.0,
        }).encode()
        raw = _run_async(run_cam_generate_dress_cycle(ctx, args))
        result = json.loads(raw)
        assert "gcode" in result
        assert "error" not in result
        assert result["num_passes"] == 10

    def test_tool_total_dress_distance_correct(self):
        ctx = _ctx()
        args = json.dumps({
            "wheel_diameter_mm": 200.0,
            "wheel_width_mm": 25.0,
            "dresser_type": "single_point_diamond",
            "depth_per_pass_mm": 0.05,
            "total_dress_amount_mm": 0.25,
            "traverse_rate_mm_per_min": 100.0,
            "dress_x_start_mm": -105.0,
            "dress_z_start_mm": 0.0,
        }).encode()
        raw = _run_async(run_cam_generate_dress_cycle(ctx, args))
        result = json.loads(raw)
        # 5 passes × 25 mm width = 125 mm
        assert abs(result["total_dress_distance_mm"] - 125.0) < 1e-6

    def test_tool_machining_time_positive(self):
        ctx = _ctx()
        args = json.dumps({
            "wheel_diameter_mm": 200.0,
            "wheel_width_mm": 25.0,
            "dresser_type": "single_point_diamond",
            "depth_per_pass_mm": 0.05,
            "total_dress_amount_mm": 0.25,
            "traverse_rate_mm_per_min": 100.0,
            "dress_x_start_mm": -105.0,
            "dress_z_start_mm": 0.0,
        }).encode()
        raw = _run_async(run_cam_generate_dress_cycle(ctx, args))
        result = json.loads(raw)
        assert result["machining_time_s"] > 0.0
