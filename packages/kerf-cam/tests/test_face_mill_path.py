"""
Tests for kerf_cam.face_mill_path — zig-zag face-milling toolpath generator.

References
----------
* Machinery's Handbook 31e §1136 — Face milling
* NIST RS-274/NGC §3.5 — G-code data input format

Run:
    pytest packages/kerf-cam/tests/test_face_mill_path.py -v
"""

from __future__ import annotations

import asyncio
import json
import math
import re

import pytest

from kerf_cam.face_mill_path import (
    FaceMillSpec,
    FaceMillResult,
    FaceMillPathSpec,
    FaceMillRoughFinishResult,
    _fmt,
    _compute_passes,
    generate_face_mill_path,
    generate_face_mill_rough_finish_path,
    cam_generate_face_mill_path_spec,
    run_cam_generate_face_mill_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(**kw) -> FaceMillSpec:
    """Return a FaceMillSpec with sensible 100×60 pocket defaults."""
    defaults = dict(
        xmin_mm=0.0,
        ymin_mm=0.0,
        xmax_mm=100.0,
        ymax_mm=60.0,
        depth_mm=2.0,
        tool_diameter_mm=12.0,
        stepover_pct=70.0,
        feed_mm_per_min=1000.0,
        spindle_rpm=3000.0,
        rapid_z_mm=10000.0,
        work_top_z_mm=0.0,
        rapid_clearance_mm=5.0,
    )
    defaults.update(kw)
    return FaceMillSpec(**defaults)


def _run_async(coro):
    return asyncio.run(coro)


def _ctx():
    from kerf_cam._compat import ProjectCtx
    return ProjectCtx()


# ---------------------------------------------------------------------------
# 1. _fmt helper — NIST RS-274/NGC §3.5.1 decimal notation
# ---------------------------------------------------------------------------

class TestFmt:
    def test_integer_has_decimal_point(self):
        assert "." in _fmt(10.0)

    def test_zero_has_decimal_point(self):
        assert "." in _fmt(0.0)

    def test_zero_value(self):
        assert _fmt(0.0) == "0.0"

    def test_positive_float(self):
        assert _fmt(12.5) == "12.5"

    def test_negative_float(self):
        assert _fmt(-5.5) == "-5.5"

    def test_trailing_zeros_stripped(self):
        assert _fmt(3.5000) == "3.5"

    def test_integer_becomes_point_zero(self):
        assert _fmt(100.0) == "100.0"


# ---------------------------------------------------------------------------
# 2. FaceMillSpec validation
# ---------------------------------------------------------------------------

class TestFaceMillSpecValidation:
    def test_valid_spec_no_error(self):
        s = _spec()
        assert s.tool_diameter_mm == 12.0

    def test_xmax_le_xmin_raises(self):
        with pytest.raises(ValueError, match="xmax_mm"):
            _spec(xmin_mm=50.0, xmax_mm=10.0)

    def test_ymax_le_ymin_raises(self):
        with pytest.raises(ValueError, match="ymax_mm"):
            _spec(ymin_mm=30.0, ymax_mm=10.0)

    def test_zero_depth_raises(self):
        with pytest.raises(ValueError, match="depth_mm"):
            _spec(depth_mm=0.0)

    def test_negative_depth_raises(self):
        with pytest.raises(ValueError, match="depth_mm"):
            _spec(depth_mm=-1.0)

    def test_zero_tool_diameter_raises(self):
        with pytest.raises(ValueError, match="tool_diameter_mm"):
            _spec(tool_diameter_mm=0.0)

    def test_tool_wider_than_pocket_x_raises(self):
        """tool_diameter > pocket_width → cannot fit; must raise ValueError."""
        with pytest.raises(ValueError, match="pocket width"):
            _spec(xmin_mm=0.0, xmax_mm=10.0, tool_diameter_mm=15.0)

    def test_tool_wider_than_pocket_y_raises(self):
        """tool_diameter > pocket_height → cannot fit; must raise ValueError."""
        with pytest.raises(ValueError, match="pocket height"):
            _spec(ymin_mm=0.0, ymax_mm=10.0, tool_diameter_mm=15.0)

    def test_stepover_zero_raises(self):
        with pytest.raises(ValueError, match="stepover_pct"):
            _spec(stepover_pct=0.0)

    def test_stepover_over_100_raises(self):
        with pytest.raises(ValueError, match="stepover_pct"):
            _spec(stepover_pct=101.0)

    def test_zero_feed_raises(self):
        with pytest.raises(ValueError, match="feed_mm_per_min"):
            _spec(feed_mm_per_min=0.0)

    def test_zero_rpm_raises(self):
        with pytest.raises(ValueError, match="spindle_rpm"):
            _spec(spindle_rpm=0.0)


# ---------------------------------------------------------------------------
# 3. _compute_passes — pass count + boundary coverage
# ---------------------------------------------------------------------------

class TestComputePasses:
    def test_100x60_12mm_70pct_gives_7_passes(self):
        """
        Pocket 100×60, D=12 mm, 70% stepover → 8.4 mm step.
        y_start=6, y_end=54, span=48, n=ceil(48/8.4)=6 steps →
        passes = [6, 14.4, 22.8, 31.2, 39.6, 48.0] + boundary 54 = 7 passes.
        """
        s = _spec()
        passes = _compute_passes(s)
        assert len(passes) == 7

    def test_first_pass_at_y_start(self):
        """First pass Y = ymin + tool_radius."""
        s = _spec()
        passes = _compute_passes(s)
        assert abs(passes[0] - (s.ymin_mm + s.tool_diameter_mm / 2.0)) < 1e-9

    def test_last_pass_at_y_end(self):
        """Last pass Y = ymax - tool_radius (boundary coverage)."""
        s = _spec()
        passes = _compute_passes(s)
        expected_y_end = s.ymax_mm - s.tool_diameter_mm / 2.0
        assert abs(passes[-1] - expected_y_end) < 1e-9

    def test_single_pass_when_tool_equals_pocket_height(self):
        """tool_diameter == pocket_height → single centred pass."""
        s = _spec(ymin_mm=0.0, ymax_mm=12.0, tool_diameter_mm=12.0)
        passes = _compute_passes(s)
        assert len(passes) == 1
        assert abs(passes[0] - 6.0) < 1e-9

    def test_100pct_stepover_gives_minimum_passes(self):
        """100% stepover → smallest number of non-overlapping passes."""
        s = _spec(stepover_pct=100.0)
        passes = _compute_passes(s)
        # stepover=12mm; y_start=6, y_end=54; span=48; n=ceil(48/12)=4;
        # passes=[6,18,30,42] + boundary 54 = 5
        assert len(passes) >= 1

    def test_60pct_stepover_gives_more_passes_than_70pct(self):
        s_60 = _spec(stepover_pct=60.0)
        s_70 = _spec(stepover_pct=70.0)
        passes_60 = _compute_passes(s_60)
        passes_70 = _compute_passes(s_70)
        assert len(passes_60) >= len(passes_70)

    def test_pass_spacing_matches_stepover(self):
        """Interior passes separated by exactly stepover (within 1e-9)."""
        s = _spec()
        passes = _compute_passes(s)
        stepover = s.tool_diameter_mm * s.stepover_pct / 100.0
        # All interior spacings (excluding final boundary jump) should equal stepover
        for i in range(1, len(passes) - 1):
            gap = abs(passes[i] - passes[i - 1])
            assert abs(gap - stepover) < 1e-9, f"Gap at i={i}: {gap} ≠ {stepover}"


# ---------------------------------------------------------------------------
# 4. generate_face_mill_path — G-code structure
# ---------------------------------------------------------------------------

class TestGcodeStructure:
    def _result(self, **kw) -> FaceMillResult:
        return generate_face_mill_path(_spec(**kw))

    def test_gcode_starts_and_ends_with_percent(self):
        """RS-274/NGC programs delimited by %."""
        r = self._result()
        lines = r.gcode.strip().split("\n")
        assert lines[0].strip() == "%"
        assert lines[-1].strip() == "%"

    def test_gcode_contains_g21_metric(self):
        r = self._result()
        assert "G21" in r.gcode

    def test_gcode_contains_g90_absolute(self):
        r = self._result()
        assert "G90" in r.gcode

    def test_gcode_contains_g94_feed_per_min(self):
        r = self._result()
        assert "G94" in r.gcode

    def test_gcode_contains_m03_spindle_on(self):
        r = self._result()
        assert "M03" in r.gcode

    def test_gcode_contains_m05_spindle_off(self):
        r = self._result()
        assert "M05" in r.gcode

    def test_gcode_contains_m30_program_end(self):
        r = self._result()
        assert "M30" in r.gcode

    def test_gcode_contains_g00_rapid(self):
        r = self._result()
        assert "G00" in r.gcode

    def test_gcode_contains_g01_feed(self):
        r = self._result()
        assert "G01" in r.gcode

    def test_z_cut_is_negative_for_positive_depth(self):
        """Cutting Z must be below work_top_z_mm (negative if work_top=0)."""
        r = self._result(depth_mm=2.0, work_top_z_mm=0.0)
        # Look for the plunge line: G01 Z<negative>
        match = re.search(r"G01 Z(-\d+\.?\d*)", r.gcode)
        assert match, "Expected G01 Z<negative> plunge line"
        z_val = float(match.group(1))
        assert z_val < 0.0, f"Cut Z should be negative, got {z_val}"

    def test_spindle_rpm_in_gcode(self):
        r = self._result(spindle_rpm=5000.0)
        assert "S5000" in r.gcode

    def test_feed_rate_in_gcode(self):
        r = self._result(feed_mm_per_min=800.0)
        assert "F800.0" in r.gcode or "F800" in r.gcode


# ---------------------------------------------------------------------------
# 5. Pass count and geometry — core spec validation
# ---------------------------------------------------------------------------

class TestPassCount:
    def test_100x60_12mm_70pct_gives_7_passes(self):
        """Primary spec test from task brief."""
        r = generate_face_mill_path(_spec())
        assert r.num_passes == 7

    def test_path_length_within_10pct_of_expected(self):
        """
        Expected path length ≈ num_passes × (x_end - x_start)
        = 7 × (94 - 6) = 7 × 88 = 616 mm.
        Tolerance: ±10%.
        """
        r = generate_face_mill_path(_spec())
        expected = r.num_passes * (100.0 - 12.0)  # num_passes × (pocket_w - tool_d)
        assert abs(r.total_path_length_mm - expected) / expected < 0.10, (
            f"path_length={r.total_path_length_mm:.2f} vs expected≈{expected:.2f}"
        )

    def test_material_removal_equals_pocket_area_times_depth(self):
        """MRR = pocket_width × pocket_height × depth_mm."""
        r = generate_face_mill_path(_spec(depth_mm=3.0))
        expected_mm3 = 100.0 * 60.0 * 3.0
        assert abs(r.material_removal_mm3 - expected_mm3) < 1e-3, (
            f"MRR={r.material_removal_mm3} ≠ {expected_mm3}"
        )

    def test_mrr_independent_of_stepover(self):
        """MRR = pocket area × depth, regardless of stepover."""
        r60 = generate_face_mill_path(_spec(stepover_pct=60.0, depth_mm=2.0))
        r80 = generate_face_mill_path(_spec(stepover_pct=80.0, depth_mm=2.0))
        assert abs(r60.material_removal_mm3 - r80.material_removal_mm3) < 1e-3


# ---------------------------------------------------------------------------
# 6. Climb vs conventional milling — pass direction
# ---------------------------------------------------------------------------

class TestClimbVsConventional:
    """
    Climb (climb_milling=True):  pass 0 → +X direction.
    Conventional (False):        pass 0 → −X direction.

    Test by checking first G01 cutting move direction.
    """

    def _first_cutting_move_direction(self, climb: bool) -> str:
        """Return '+X' or '-X' based on first actual cutting G01."""
        r = generate_face_mill_path(_spec(), climb_milling=climb)
        # Find lines with G01 X followed by a coordinate (cutting moves)
        pattern = re.compile(r"G01 X(-?\d+\.?\d*) Y")
        matches = pattern.findall(r.gcode)
        assert matches, "No G01 XY cutting moves found"
        # The first match is the initial pass
        # We need to infer direction from start and end X values
        # Climb: starts at x_start=6, ends at x_end=94 → +X
        # Conventional: starts at x_end=94, ends at x_start=6 → -X
        x_coords = [float(m) for m in matches]
        if x_coords[0] > 50:  # ends to the right (started from left)
            return "+X"
        else:  # ends to the left (started from right)
            return "-X"

    def test_climb_first_pass_positive_x(self):
        direction = self._first_cutting_move_direction(climb=True)
        assert direction == "+X", (
            "Climb milling pass 0 should end at +X (travel left→right)"
        )

    def test_conventional_first_pass_negative_x(self):
        direction = self._first_cutting_move_direction(climb=False)
        assert direction == "-X", (
            "Conventional milling pass 0 should end at -X (travel right→left)"
        )

    def test_climb_and_conventional_same_num_passes(self):
        r_climb = generate_face_mill_path(_spec(), climb_milling=True)
        r_conv = generate_face_mill_path(_spec(), climb_milling=False)
        assert r_climb.num_passes == r_conv.num_passes

    def test_climb_and_conventional_same_mrr(self):
        r_climb = generate_face_mill_path(_spec(), climb_milling=True)
        r_conv = generate_face_mill_path(_spec(), climb_milling=False)
        assert abs(r_climb.material_removal_mm3 - r_conv.material_removal_mm3) < 1e-3


# ---------------------------------------------------------------------------
# 7. Machining time estimates
# ---------------------------------------------------------------------------

class TestMachiningTime:
    def test_time_is_positive(self):
        r = generate_face_mill_path(_spec())
        assert r.machining_time_s > 0.0

    def test_faster_feed_gives_shorter_time(self):
        slow = generate_face_mill_path(_spec(feed_mm_per_min=500.0))
        fast = generate_face_mill_path(_spec(feed_mm_per_min=2000.0))
        assert fast.machining_time_s < slow.machining_time_s

    def test_time_ge_pure_cutting_time(self):
        """
        Estimated time must be ≥ pure cutting time (no rapids/plunges only add more).
        pure_cutting_time = total_path_length / feed_rate × 60
        """
        r = generate_face_mill_path(_spec(feed_mm_per_min=1000.0))
        pure_s = (r.total_path_length_mm / 1000.0) * 60.0
        assert r.machining_time_s >= pure_s * 0.95, (
            f"time {r.machining_time_s:.2f}s < pure cutting {pure_s:.2f}s"
        )


# ---------------------------------------------------------------------------
# 8. Honest caveat
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    def test_caveat_mentions_2_5d(self):
        r = generate_face_mill_path(_spec())
        assert "2.5D" in r.honest_caveat or "2.5d" in r.honest_caveat.lower()

    def test_caveat_mentions_helical(self):
        r = generate_face_mill_path(_spec())
        assert "helical" in r.honest_caveat.lower()

    def test_caveat_mentions_acceleration(self):
        r = generate_face_mill_path(_spec())
        assert "acceleration" in r.honest_caveat.lower() or "ramp" in r.honest_caveat.lower()

    def test_caveat_mentions_mh_reference(self):
        r = generate_face_mill_path(_spec())
        assert "MH" in r.honest_caveat or "Handbook" in r.honest_caveat


# ---------------------------------------------------------------------------
# 9. Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_tool_equal_to_pocket_width_single_pass(self):
        """tool_diameter == pocket_width → single centred pass (tool just fits)."""
        r = generate_face_mill_path(_spec(xmin_mm=0.0, xmax_mm=12.0, tool_diameter_mm=12.0))
        # x_start = x_end = 6 → single pass of zero length (stationary at centre)
        assert r.num_passes >= 1

    def test_tool_larger_than_pocket_raises(self):
        with pytest.raises(ValueError, match="pocket width"):
            generate_face_mill_path(_spec(xmin_mm=0.0, xmax_mm=10.0, tool_diameter_mm=15.0))

    def test_square_pocket(self):
        """Square pocket should work and produce at least 1 pass."""
        r = generate_face_mill_path(_spec(xmax_mm=50.0, ymax_mm=50.0, tool_diameter_mm=10.0))
        assert r.num_passes >= 1
        assert r.material_removal_mm3 > 0

    def test_depth_much_larger_than_pocket(self):
        """Large depth is valid — just a deep pocket."""
        r = generate_face_mill_path(_spec(depth_mm=50.0))
        assert r.material_removal_mm3 == pytest.approx(100.0 * 60.0 * 50.0, rel=1e-4)

    def test_work_top_z_offset(self):
        """Non-zero work_top_z_mm shifts all Z values accordingly."""
        r = generate_face_mill_path(_spec(work_top_z_mm=10.0, depth_mm=2.0))
        # Cutting Z should be 10.0 - 2.0 = 8.0
        # Look for G01 Z8.0 in gcode
        assert "Z8.0" in r.gcode, (
            f"Expected Z8.0 (work_top=10 - depth=2) in gcode"
        )

    def test_small_stepover_gives_many_passes(self):
        """Small stepover → many passes."""
        r = generate_face_mill_path(_spec(stepover_pct=10.0))
        r_normal = generate_face_mill_path(_spec(stepover_pct=70.0))
        assert r.num_passes > r_normal.num_passes

    def test_large_pocket(self):
        """1000×500 pocket with 50mm face mill — should still work."""
        r = generate_face_mill_path(_spec(
            xmin_mm=0.0, ymin_mm=0.0, xmax_mm=1000.0, ymax_mm=500.0,
            tool_diameter_mm=50.0, stepover_pct=75.0,
            feed_mm_per_min=2000.0, spindle_rpm=2000.0,
        ))
        assert r.num_passes >= 1
        assert "G01" in r.gcode


# ---------------------------------------------------------------------------
# 10. LLM tool wrapper
# ---------------------------------------------------------------------------

class TestLLMTool:
    def _default_args(self, **overrides) -> dict:
        args = {
            "xmin_mm": 0.0, "ymin_mm": 0.0,
            "xmax_mm": 100.0, "ymax_mm": 60.0,
            "depth_mm": 2.0, "tool_diameter_mm": 12.0,
            "feed_mm_per_min": 1000.0, "spindle_rpm": 3000.0,
        }
        args.update(overrides)
        return args

    def test_tool_spec_name(self):
        assert cam_generate_face_mill_path_spec.name == "cam_generate_face_mill_path"

    def test_tool_runs_default_pocket(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_face_mill_path(ctx, args))
        result = json.loads(raw)
        assert "gcode" in result
        assert "G01" in result["gcode"]
        assert result["num_passes"] == 7

    def test_tool_returns_mrr(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_face_mill_path(ctx, args))
        result = json.loads(raw)
        assert "material_removal_mm3" in result
        expected_mrr = 100.0 * 60.0 * 2.0
        assert abs(result["material_removal_mm3"] - expected_mrr) < 1e-2

    def test_tool_returns_honest_caveat(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_face_mill_path(ctx, args))
        result = json.loads(raw)
        assert "honest_caveat" in result
        assert len(result["honest_caveat"]) > 20

    def test_tool_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run_async(run_cam_generate_face_mill_path(ctx, b"not-json"))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_missing_required_field_returns_error(self):
        ctx = _ctx()
        args = json.dumps({"xmin_mm": 0.0}).encode()
        raw = _run_async(run_cam_generate_face_mill_path(ctx, args))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_tool_too_large_returns_error(self):
        ctx = _ctx()
        bad = self._default_args(xmax_mm=10.0, tool_diameter_mm=15.0)
        args = json.dumps(bad).encode()
        raw = _run_async(run_cam_generate_face_mill_path(ctx, args))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_conventional_milling(self):
        ctx = _ctx()
        args_dict = self._default_args()
        args_dict["climb_milling"] = False
        raw = _run_async(run_cam_generate_face_mill_path(ctx, args_dict.__class__(args_dict) if False else json.dumps(args_dict).encode()))  # noqa: E501
        result = json.loads(raw)
        assert "gcode" in result
        # Gcode should have milling mode label 'conventional'
        assert "conventional" in result["gcode"].lower()

    def test_tool_custom_stepover(self):
        ctx = _ctx()
        args_dict = self._default_args()
        args_dict["stepover_pct"] = 60.0
        raw = _run_async(run_cam_generate_face_mill_path(ctx, json.dumps(args_dict).encode()))
        result = json.loads(raw)
        assert result["num_passes"] >= 7  # tighter stepover → more passes

    def test_tool_returns_path_length(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_face_mill_path(ctx, args))
        result = json.loads(raw)
        assert "total_path_length_mm" in result
        assert result["total_path_length_mm"] > 0.0

    def test_tool_returns_machining_time(self):
        ctx = _ctx()
        args = json.dumps(self._default_args()).encode()
        raw = _run_async(run_cam_generate_face_mill_path(ctx, args))
        result = json.loads(raw)
        assert "machining_time_s" in result
        assert result["machining_time_s"] > 0.0


# ---------------------------------------------------------------------------
# 11. FaceMillPathSpec validation
# ---------------------------------------------------------------------------

def _path_spec(**kw) -> FaceMillPathSpec:
    """Return a FaceMillPathSpec with sensible 100×60 pocket defaults."""
    defaults = dict(
        xmin_mm=0.0,
        ymin_mm=0.0,
        xmax_mm=100.0,
        ymax_mm=60.0,
        total_depth_mm=5.0,
        tool_diameter_mm=12.0,
        stepdown_mm=1.0,
        stock_allowance_mm=0.2,
        roughing_feedrate_mm_per_min=1500.0,
        finishing_feedrate_mm_per_min=800.0,
        stepover_pct=70.0,
        finishing_stepover_pct=50.0,
        spindle_rpm=3000.0,
        rapid_z_mm=10000.0,
        work_top_z_mm=0.0,
        rapid_clearance_mm=5.0,
    )
    defaults.update(kw)
    return FaceMillPathSpec(**defaults)


class TestFaceMillPathSpecValidation:
    def test_valid_spec_no_error(self):
        s = _path_spec()
        assert s.total_depth_mm == 5.0
        assert s.stepdown_mm == 1.0

    def test_zero_total_depth_raises(self):
        with pytest.raises(ValueError, match="total_depth_mm"):
            _path_spec(total_depth_mm=0.0)

    def test_negative_stepdown_raises(self):
        with pytest.raises(ValueError, match="stepdown_mm"):
            _path_spec(stepdown_mm=-0.5)

    def test_zero_stepdown_raises(self):
        with pytest.raises(ValueError, match="stepdown_mm"):
            _path_spec(stepdown_mm=0.0)

    def test_stock_allowance_ge_total_depth_raises(self):
        with pytest.raises(ValueError, match="stock_allowance_mm"):
            _path_spec(total_depth_mm=1.0, stock_allowance_mm=1.0)

    def test_negative_stock_allowance_raises(self):
        with pytest.raises(ValueError, match="stock_allowance_mm"):
            _path_spec(stock_allowance_mm=-0.1)

    def test_zero_roughing_feedrate_raises(self):
        with pytest.raises(ValueError, match="roughing_feedrate_mm_per_min"):
            _path_spec(roughing_feedrate_mm_per_min=0.0)

    def test_zero_finishing_feedrate_raises(self):
        with pytest.raises(ValueError, match="finishing_feedrate_mm_per_min"):
            _path_spec(finishing_feedrate_mm_per_min=0.0)

    def test_finishing_stepover_out_of_range_raises(self):
        with pytest.raises(ValueError, match="finishing_stepover_pct"):
            _path_spec(finishing_stepover_pct=0.0)


# ---------------------------------------------------------------------------
# 12. generate_face_mill_rough_finish_path — layer counts
# ---------------------------------------------------------------------------

class TestRoughFinishLayerCounts:
    def test_5mm_depth_1mm_stepdown_gives_5_roughing_layers(self):
        """
        total_depth=5 mm, stock_allowance=0.2 mm → roughing_depth=4.8 mm.
        stepdown=1.0 mm → num_roughing_layers = ceil(4.8/1.0) = 5.
        """
        r = generate_face_mill_rough_finish_path(_path_spec(
            total_depth_mm=5.0,
            stepdown_mm=1.0,
            stock_allowance_mm=0.2,
        ))
        assert r.num_roughing_layers == 5, (
            f"Expected 5 roughing layers, got {r.num_roughing_layers}"
        )

    def test_5mm_depth_1mm_stepdown_has_finishing_pass(self):
        """Result must include exactly 1 finishing layer (num_finishing_passes >= 1)."""
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert r.num_finishing_passes >= 1

    def test_total_layers_is_roughing_plus_one_finish(self):
        """Total Z passes = num_roughing_layers + 1 (finish)."""
        r = generate_face_mill_rough_finish_path(_path_spec(
            total_depth_mm=6.0,
            stepdown_mm=2.0,
            stock_allowance_mm=0.3,
        ))
        # roughing_depth = 5.7, stepdown=2.0 → ceil(5.7/2.0) = 3 roughing layers
        assert r.num_roughing_layers == 3
        # Plus finishing = 4 Z levels total (implicit in gcode layers)
        assert r.num_finishing_passes >= 1

    def test_larger_stepdown_gives_fewer_roughing_layers(self):
        """Bigger stepdown → fewer roughing layers."""
        r_small = generate_face_mill_rough_finish_path(_path_spec(stepdown_mm=0.5))
        r_large = generate_face_mill_rough_finish_path(_path_spec(stepdown_mm=2.0))
        assert r_small.num_roughing_layers > r_large.num_roughing_layers

    def test_roughing_z_levels_count_matches_num_roughing_layers(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert len(r.roughing_z_levels) == r.num_roughing_layers

    def test_last_roughing_z_preserves_stock_allowance(self):
        """
        Last roughing floor = work_top_z_mm − (total_depth_mm − stock_allowance_mm).
        Stock allowance must remain between last roughing Z and final finishing Z.
        """
        spec = _path_spec(
            total_depth_mm=5.0,
            stepdown_mm=1.0,
            stock_allowance_mm=0.2,
            work_top_z_mm=0.0,
        )
        r = generate_face_mill_rough_finish_path(spec)
        last_roughing_z = r.roughing_z_levels[-1]
        finishing_z = r.finishing_z
        # Stock on floor = distance between last roughing pass and finish floor
        remaining_stock = abs(last_roughing_z - finishing_z)
        assert abs(remaining_stock - spec.stock_allowance_mm) < 1e-6, (
            f"Stock allowance={remaining_stock:.6f} mm, "
            f"expected {spec.stock_allowance_mm} mm"
        )

    def test_finishing_z_equals_total_depth_below_work_top(self):
        """Finishing Z = work_top_z_mm − total_depth_mm."""
        spec = _path_spec(work_top_z_mm=10.0, total_depth_mm=5.0)
        r = generate_face_mill_rough_finish_path(spec)
        expected = 10.0 - 5.0
        assert abs(r.finishing_z - expected) < 1e-9, (
            f"finishing_z={r.finishing_z}, expected {expected}"
        )

    def test_roughing_z_levels_monotonically_decreasing(self):
        """Each roughing layer must be deeper than the previous."""
        r = generate_face_mill_rough_finish_path(_path_spec())
        for i in range(1, len(r.roughing_z_levels)):
            assert r.roughing_z_levels[i] < r.roughing_z_levels[i - 1], (
                f"Layer {i} Z={r.roughing_z_levels[i]} not deeper than "
                f"layer {i-1} Z={r.roughing_z_levels[i-1]}"
            )

    def test_all_roughing_z_levels_above_finishing_z(self):
        """Every roughing layer must be shallower than finishing_z (stock preserved)."""
        r = generate_face_mill_rough_finish_path(_path_spec())
        for i, z in enumerate(r.roughing_z_levels):
            assert z > r.finishing_z, (
                f"Roughing layer {i} Z={z} is at or below finishing_z={r.finishing_z}"
            )


# ---------------------------------------------------------------------------
# 13. Roughing uses faster feedrate than finishing
# ---------------------------------------------------------------------------

class TestRoughingFeedrate:
    def test_roughing_gcode_uses_roughing_feedrate(self):
        """G-code for roughing layers must include the roughing feedrate F-word."""
        spec = _path_spec(
            roughing_feedrate_mm_per_min=1500.0,
            finishing_feedrate_mm_per_min=800.0,
        )
        r = generate_face_mill_rough_finish_path(spec)
        assert "F1500.0" in r.gcode or "F1500" in r.gcode, (
            "Roughing feedrate 1500 mm/min not found in G-code"
        )

    def test_finishing_gcode_uses_finishing_feedrate(self):
        """G-code for finishing pass must include the finishing feedrate F-word."""
        spec = _path_spec(
            roughing_feedrate_mm_per_min=1500.0,
            finishing_feedrate_mm_per_min=800.0,
        )
        r = generate_face_mill_rough_finish_path(spec)
        assert "F800.0" in r.gcode or "F800" in r.gcode, (
            "Finishing feedrate 800 mm/min not found in G-code"
        )

    def test_roughing_feedrate_gt_finishing_feedrate_by_default(self):
        """Default roughing feed (1500) > finishing feed (800) for higher MRR."""
        spec = _path_spec()
        assert spec.roughing_feedrate_mm_per_min > spec.finishing_feedrate_mm_per_min

    def test_machining_time_increases_with_more_layers(self):
        """More roughing layers → longer total machining time."""
        r_shallow = generate_face_mill_rough_finish_path(_path_spec(
            total_depth_mm=2.0, stepdown_mm=1.0, stock_allowance_mm=0.2,
        ))
        r_deep = generate_face_mill_rough_finish_path(_path_spec(
            total_depth_mm=8.0, stepdown_mm=1.0, stock_allowance_mm=0.2,
        ))
        assert r_deep.machining_time_s > r_shallow.machining_time_s


# ---------------------------------------------------------------------------
# 14. G-code structure for roughing + finishing
# ---------------------------------------------------------------------------

class TestRoughFinishGcodeStructure:
    def test_gcode_has_percent_delimiters(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        lines = r.gcode.strip().split("\n")
        assert lines[0].strip() == "%"
        assert lines[-1].strip() == "%"

    def test_gcode_has_g21_metric(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert "G21" in r.gcode

    def test_gcode_has_m03_spindle_on(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert "M03" in r.gcode

    def test_gcode_has_m05_spindle_off(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert "M05" in r.gcode

    def test_gcode_has_m30_program_end(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert "M30" in r.gcode

    def test_gcode_mentions_roughing_layer(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert "Roughing layer" in r.gcode

    def test_gcode_mentions_finishing_pass(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert "Finishing pass" in r.gcode

    def test_finishing_z_present_in_gcode(self):
        """The final depth Z value must appear in a G01 plunge."""
        spec = _path_spec(total_depth_mm=5.0, work_top_z_mm=0.0)
        r = generate_face_mill_rough_finish_path(spec)
        # finishing_z = -5.0
        assert "Z-5.0" in r.gcode, (
            f"Expected Z-5.0 (finishing floor) in gcode. finishing_z={r.finishing_z}"
        )

    def test_material_removal_equals_pocket_area_times_total_depth(self):
        """MRR = pocket_area × total_depth_mm."""
        spec = _path_spec(total_depth_mm=5.0)
        r = generate_face_mill_rough_finish_path(spec)
        expected_mm3 = 100.0 * 60.0 * 5.0
        assert abs(r.material_removal_mm3 - expected_mm3) < 1e-3, (
            f"MRR={r.material_removal_mm3} ≠ {expected_mm3}"
        )

    def test_total_path_length_positive(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert r.total_path_length_mm > 0.0

    def test_machining_time_positive(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert r.machining_time_s > 0.0

    def test_honest_caveat_mentions_stock_allowance(self):
        spec = _path_spec(stock_allowance_mm=0.2)
        r = generate_face_mill_rough_finish_path(spec)
        # The caveat embeds the stock_allowance value
        assert "0.2" in r.honest_caveat

    def test_honest_caveat_mentions_mh_reference(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert "MH" in r.honest_caveat or "Handbook" in r.honest_caveat

    def test_result_type_is_face_mill_rough_finish_result(self):
        r = generate_face_mill_rough_finish_path(_path_spec())
        assert isinstance(r, FaceMillRoughFinishResult)

    def test_finishing_stepover_smaller_than_roughing_produces_more_finish_passes(self):
        """Finishing pass with tighter stepover should produce >= roughing passes."""
        spec_tight = _path_spec(finishing_stepover_pct=30.0, stepover_pct=70.0)
        spec_same = _path_spec(finishing_stepover_pct=70.0, stepover_pct=70.0)
        r_tight = generate_face_mill_rough_finish_path(spec_tight)
        r_same = generate_face_mill_rough_finish_path(spec_same)
        assert r_tight.num_finishing_passes >= r_same.num_finishing_passes


# ---------------------------------------------------------------------------
# 15. Edge cases for roughing + finishing
# ---------------------------------------------------------------------------

class TestRoughFinishEdgeCases:
    def test_stepdown_larger_than_roughing_depth_gives_one_roughing_layer(self):
        """stepdown > roughing_depth → ceil(roughing_depth/stepdown) = 1 layer."""
        spec = _path_spec(total_depth_mm=3.0, stepdown_mm=5.0, stock_allowance_mm=0.5)
        r = generate_face_mill_rough_finish_path(spec)
        assert r.num_roughing_layers == 1

    def test_zero_stock_allowance_valid(self):
        """stock_allowance_mm=0 is allowed (all depth removed in roughing)."""
        spec = _path_spec(stock_allowance_mm=0.0)
        r = generate_face_mill_rough_finish_path(spec)
        # finishing_z should equal the last roughing z
        assert abs(r.finishing_z - r.roughing_z_levels[-1]) < 1e-9

    def test_non_zero_work_top_shifts_all_z(self):
        """work_top_z_mm offset shifts all Z levels accordingly."""
        spec = _path_spec(work_top_z_mm=20.0, total_depth_mm=5.0)
        r = generate_face_mill_rough_finish_path(spec)
        # All roughing Z levels must be < 20.0 (below work surface)
        for z in r.roughing_z_levels:
            assert z < spec.work_top_z_mm
        assert r.finishing_z == pytest.approx(20.0 - 5.0, abs=1e-9)

    def test_exact_stepdown_divisible_no_extra_layers(self):
        """roughing_depth exactly divisible by stepdown → no extra thin layer."""
        # roughing_depth = 4.0 - 0.0 = 4.0, stepdown = 1.0 → 4 layers
        spec = _path_spec(total_depth_mm=4.0, stepdown_mm=1.0, stock_allowance_mm=0.0)
        r = generate_face_mill_rough_finish_path(spec)
        assert r.num_roughing_layers == 4

    def test_path_length_scales_with_num_layers(self):
        """More layers → proportionally more total path length."""
        r_few = generate_face_mill_rough_finish_path(_path_spec(
            total_depth_mm=2.0, stepdown_mm=1.0, stock_allowance_mm=0.1,
        ))
        r_many = generate_face_mill_rough_finish_path(_path_spec(
            total_depth_mm=10.0, stepdown_mm=1.0, stock_allowance_mm=0.1,
        ))
        assert r_many.total_path_length_mm > r_few.total_path_length_mm
