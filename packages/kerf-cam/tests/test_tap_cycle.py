"""
Tests for kerf_cam.tap_cycle — G84/G74 tapping canned cycle.

References
----------
* NIST RS-274/NGC §3.8.4 — G84 right-hand, G74 left-hand tapping cycles
* Machinery's Handbook 31e §1934 — tap drill sizes & feed coupling (F = pitch × rpm)
* Fanuc 0i/30i-series OM §13.3.3 — M29 rigid-tap engage

Run:
    pytest packages/kerf-cam/tests/test_tap_cycle.py -v
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from kerf_cam.tap_cycle import (
    TapHoleSpec,
    TapCycleResult,
    _fmt,
    _compute_feed,
    _estimate_tap_cycle_time,
    generate_tap_cycle,
    cam_generate_tap_cycle_spec,
    run_cam_generate_tap_cycle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_hole(**kw) -> TapHoleSpec:
    """Return a TapHoleSpec with sensible defaults, overrideable via kw."""
    defaults = dict(
        x_mm=0.0,
        y_mm=0.0,
        depth_mm=12.0,
        thread_pitch_mm=1.0,    # M6×1.0
        spindle_rpm=1000.0,
        direction="right",
        rapid_z_mm=10000.0,
        work_top_z_mm=0.0,
        dwell_s=0.0,
    )
    defaults.update(kw)
    return TapHoleSpec(**defaults)


def _run_async(coro):
    return asyncio.run(coro)


def _ctx():
    from kerf_cam._compat import ProjectCtx
    return ProjectCtx()


# ---------------------------------------------------------------------------
# 1. Feed coupling (MH 31e §1934: F = pitch × rpm)
# ---------------------------------------------------------------------------

class TestFeedCoupling:
    def test_m6x1_1000rpm_feed_exact(self):
        """M6×1.0 thread at 1000 rpm: feed must be exactly 1000 mm/min."""
        feed = _compute_feed(pitch_mm=1.0, rpm=1000.0)
        assert feed == pytest.approx(1000.0, abs=1e-9), (
            f"Expected 1000.0 mm/min, got {feed}"
        )

    def test_m8x1p25_800rpm(self):
        """M8×1.25 at 800 rpm: feed = 1.25 × 800 = 1000 mm/min."""
        feed = _compute_feed(pitch_mm=1.25, rpm=800.0)
        assert feed == pytest.approx(1000.0, abs=1e-9)

    def test_m10x1p5_500rpm(self):
        """M10×1.5 at 500 rpm: feed = 1.5 × 500 = 750 mm/min."""
        feed = _compute_feed(pitch_mm=1.5, rpm=500.0)
        assert feed == pytest.approx(750.0, abs=1e-9)

    def test_feed_in_result_matches_computed(self):
        """generate_tap_cycle result.computed_feed_mm_per_min must equal pitch × rpm."""
        hole = _simple_hole(thread_pitch_mm=1.0, spindle_rpm=1000.0)
        result = generate_tap_cycle([hole])
        assert result.computed_feed_mm_per_min == pytest.approx(1000.0, abs=1e-3)

    def test_feed_appears_in_gcode(self):
        """F word in the G84 block must equal the computed feed."""
        hole = _simple_hole(thread_pitch_mm=1.0, spindle_rpm=1000.0)
        result = generate_tap_cycle([hole])
        # F1000.0 should appear in the G84 line
        assert "F1000.0" in result.gcode or "F1000" in result.gcode


# ---------------------------------------------------------------------------
# 2. G84 / G74 cycle code selection
# ---------------------------------------------------------------------------

class TestCycleCodeSelection:
    def test_right_hand_emits_g84(self):
        """direction='right' must emit G84 (right-hand tapping)."""
        result = generate_tap_cycle([_simple_hole(direction="right")])
        assert "G84" in result.gcode

    def test_left_hand_emits_g74(self):
        """direction='left' must emit G74 (left-hand tapping)."""
        result = generate_tap_cycle([_simple_hole(direction="left")])
        assert "G74" in result.gcode

    def test_right_hand_no_g74(self):
        """A right-hand tap program must NOT contain G74."""
        result = generate_tap_cycle([_simple_hole(direction="right")])
        # Strip comment lines before checking
        code_lines = [
            ln for ln in result.gcode.splitlines()
            if not ln.strip().startswith("(")
        ]
        assert "G74" not in "\n".join(code_lines)

    def test_left_hand_no_g84(self):
        """A left-hand tap program must NOT contain G84."""
        result = generate_tap_cycle([_simple_hole(direction="left")])
        code_lines = [
            ln for ln in result.gcode.splitlines()
            if not ln.strip().startswith("(")
        ]
        assert "G84" not in "\n".join(code_lines)


# ---------------------------------------------------------------------------
# 3. G84/G74 block field correctness (NIST RS-274/NGC §3.8.4)
# ---------------------------------------------------------------------------

class TestCycleBlockFields:
    def test_x_y_present_in_gcode(self):
        result = generate_tap_cycle([_simple_hole(x_mm=15.0, y_mm=25.5)])
        assert "X15.0" in result.gcode
        assert "Y25.5" in result.gcode

    def test_z_field_is_negative_for_positive_depth(self):
        """Z in G84 must be ≤ work_top_z (drilled downward)."""
        result = generate_tap_cycle([_simple_hole(depth_mm=12.0, work_top_z_mm=0.0)])
        match = re.search(r"G8[47].*Z(-\d+\.?\d*)", result.gcode)
        assert match, "G84/G74 line should contain Z field"
        z_val = float(match.group(1))
        assert z_val < 0, f"Expected negative Z (downward), got {z_val}"

    def test_z_depth_value_correct(self):
        """Z = work_top_z - depth_mm."""
        result = generate_tap_cycle([
            _simple_hole(depth_mm=10.0, work_top_z_mm=5.0)
        ])
        # Expected Z = 5.0 - 10.0 = -5.0
        assert "Z-5.0" in result.gcode

    def test_r_field_above_work_surface(self):
        """R plane must be above the work surface."""
        result = generate_tap_cycle([_simple_hole(work_top_z_mm=0.0)])
        match = re.search(r"G8[47].*R(\d+\.?\d*)", result.gcode)
        assert match, "G84/G74 line should contain R field"
        r_val = float(match.group(1))
        assert r_val >= 0.0, f"R plane should be >= work top (0.0), got {r_val}"

    def test_f_field_equals_pitch_times_rpm(self):
        """F word must equal pitch × rpm (MH §1934)."""
        result = generate_tap_cycle([
            _simple_hole(thread_pitch_mm=1.25, spindle_rpm=800.0)
        ])
        # Expected F = 1.25 × 800 = 1000.0
        match = re.search(r"G8[47].*F(\d+\.?\d*)", result.gcode)
        assert match, "G84/G74 line should contain F field"
        f_val = float(match.group(1))
        assert abs(f_val - 1000.0) < 1e-3, f"F should be 1000.0, got {f_val}"


# ---------------------------------------------------------------------------
# 4. Rigid tap M29 emission (Fanuc convention)
# ---------------------------------------------------------------------------

class TestRigidTapM29:
    def test_rigid_tap_true_emits_m29(self):
        """rigid_tap=True must emit M29 before G84."""
        result = generate_tap_cycle([_simple_hole()], rigid_tap=True)
        assert "M29" in result.gcode

    def test_m29_has_spindle_speed(self):
        """M29 block must carry the S (spindle speed) word."""
        result = generate_tap_cycle([_simple_hole(spindle_rpm=1200.0)], rigid_tap=True)
        # M29 S1200 (or S1200.0)
        assert re.search(r"M29\s+S1200", result.gcode), (
            "M29 must be followed by S<spindle_rpm>"
        )

    def test_m29_precedes_g84_in_gcode(self):
        """M29 must appear before G84 in the non-comment lines of the output."""
        result = generate_tap_cycle([_simple_hole(direction="right")], rigid_tap=True)
        # Filter out comment lines so header mentions of G84/G74 don't interfere
        code_lines = [
            ln for ln in result.gcode.splitlines()
            if not ln.strip().startswith("(")
        ]
        code_noncomment = "\n".join(code_lines)
        m29_pos = code_noncomment.index("M29")
        g84_pos = code_noncomment.index("G84")
        assert m29_pos < g84_pos, "M29 must precede G84 in non-comment code"

    def test_rigid_tap_false_no_m29(self):
        """rigid_tap=False must NOT emit M29 (e.g. for LinuxCNC)."""
        result = generate_tap_cycle([_simple_hole()], rigid_tap=False)
        assert "M29" not in result.gcode

    def test_multi_hole_m29_per_hole(self):
        """Each hole gets its own M29 when rigid_tap=True."""
        holes = [_simple_hole(x_mm=0.0), _simple_hole(x_mm=20.0)]
        result = generate_tap_cycle(holes, rigid_tap=True)
        m29_count = len(re.findall(r"\bM29\b", result.gcode))
        assert m29_count == 2, f"Expected 2 M29 blocks, found {m29_count}"


# ---------------------------------------------------------------------------
# 5. G80 canned-cycle cancellation
# ---------------------------------------------------------------------------

class TestG80Cancellation:
    def test_g80_present_single_hole(self):
        result = generate_tap_cycle([_simple_hole()])
        assert "G80" in result.gcode

    def test_g80_after_last_tap_block(self):
        """G80 must appear after all G84/G74 blocks."""
        holes = [_simple_hole(x_mm=0.0), _simple_hole(x_mm=30.0)]
        result = generate_tap_cycle(holes)
        g80_pos = result.gcode.rfind("G80")
        g8x_pos = max(result.gcode.rfind("G84"), result.gcode.rfind("G74"))
        assert g80_pos > g8x_pos, "G80 must follow the last G84/G74 block"

    def test_g80_appears_exactly_once(self):
        """G80 must appear exactly once (one cancel after all holes)."""
        holes = [_simple_hole(x_mm=i * 10.0) for i in range(4)]
        result = generate_tap_cycle(holes)
        g80_count = len(re.findall(r"\bG80\b", result.gcode))
        assert g80_count == 1, f"Expected exactly 1 G80, found {g80_count}"


# ---------------------------------------------------------------------------
# 6. Multi-hole sequence
# ---------------------------------------------------------------------------

class TestMultiHole:
    def _four_holes(self) -> TapCycleResult:
        return generate_tap_cycle([
            _simple_hole(x_mm=0.0, y_mm=0.0, depth_mm=10.0),
            _simple_hole(x_mm=20.0, y_mm=0.0, depth_mm=10.0),
            _simple_hole(x_mm=20.0, y_mm=20.0, depth_mm=10.0),
            _simple_hole(x_mm=0.0, y_mm=20.0, depth_mm=10.0),
        ])

    def test_num_holes_correct(self):
        result = self._four_holes()
        assert result.num_holes == 4

    def test_four_g84_blocks(self):
        result = self._four_holes()
        g84_lines = [
            ln for ln in result.gcode.splitlines()
            if ln.strip().startswith("G84")
        ]
        assert len(g84_lines) == 4

    def test_empty_holes_raises(self):
        with pytest.raises(ValueError, match="empty"):
            generate_tap_cycle([])


# ---------------------------------------------------------------------------
# 7. TapHoleSpec validation
# ---------------------------------------------------------------------------

class TestTapHoleSpecValidation:
    def test_valid_spec_no_error(self):
        spec = _simple_hole()
        assert spec.depth_mm == 12.0

    def test_zero_depth_raises(self):
        with pytest.raises(ValueError, match="depth_mm"):
            _simple_hole(depth_mm=0.0)

    def test_negative_depth_raises(self):
        with pytest.raises(ValueError, match="depth_mm"):
            _simple_hole(depth_mm=-5.0)

    def test_zero_pitch_raises(self):
        with pytest.raises(ValueError, match="thread_pitch_mm"):
            _simple_hole(thread_pitch_mm=0.0)

    def test_zero_rpm_raises(self):
        with pytest.raises(ValueError, match="spindle_rpm"):
            _simple_hole(spindle_rpm=0.0)

    def test_invalid_direction_raises(self):
        with pytest.raises(ValueError, match="direction"):
            _simple_hole(direction="up")

    def test_negative_dwell_raises(self):
        with pytest.raises(ValueError, match="dwell_s"):
            _simple_hole(dwell_s=-1.0)


# ---------------------------------------------------------------------------
# 8. G-code header and delimiters
# ---------------------------------------------------------------------------

class TestGCodeStructure:
    def test_gcode_has_percent_delimiters(self):
        """RS-274/NGC programs start and end with %."""
        result = generate_tap_cycle([_simple_hole()])
        lines = result.gcode.strip().split('\n')
        assert lines[0].strip() == '%'
        assert lines[-1].strip() == '%'

    def test_gcode_declares_g21_metric(self):
        """Program must declare G21 (metric mode)."""
        result = generate_tap_cycle([_simple_hole()])
        assert "G21" in result.gcode

    def test_gcode_declares_g90_absolute(self):
        """Program must declare G90 (absolute distances)."""
        result = generate_tap_cycle([_simple_hole()])
        assert "G90" in result.gcode

    def test_gcode_declares_g94_feed_per_min(self):
        """Program must declare G94 (feed per minute)."""
        result = generate_tap_cycle([_simple_hole()])
        assert "G94" in result.gcode


# ---------------------------------------------------------------------------
# 9. Dwell handling
# ---------------------------------------------------------------------------

class TestDwell:
    def test_dwell_emitted_when_set(self):
        result = generate_tap_cycle([_simple_hole(dwell_s=1.5)])
        assert "G4" in result.gcode

    def test_no_dwell_when_zero(self):
        result = generate_tap_cycle([_simple_hole(dwell_s=0.0)])
        assert "G4" not in result.gcode

    def test_dwell_adds_to_cycle_time(self):
        no_dwell = generate_tap_cycle([_simple_hole(dwell_s=0.0)])
        with_dwell = generate_tap_cycle([_simple_hole(dwell_s=2.0)])
        diff = with_dwell.total_machining_time_s - no_dwell.total_machining_time_s
        assert abs(diff - 2.0) < 0.1, f"Dwell should add ~2s, got diff={diff:.3f}s"


# ---------------------------------------------------------------------------
# 10. Cycle time model
# ---------------------------------------------------------------------------

class TestCycleTime:
    def test_time_positive(self):
        result = generate_tap_cycle([_simple_hole()])
        assert result.total_machining_time_s > 0

    def test_more_holes_longer_time(self):
        one = generate_tap_cycle([_simple_hole()])
        three = generate_tap_cycle([_simple_hole(), _simple_hole(), _simple_hole()])
        assert three.total_machining_time_s > one.total_machining_time_s

    def test_deeper_hole_longer_time(self):
        shallow = generate_tap_cycle([_simple_hole(depth_mm=5.0)])
        deep = generate_tap_cycle([_simple_hole(depth_mm=20.0)])
        assert deep.total_machining_time_s > shallow.total_machining_time_s


# ---------------------------------------------------------------------------
# 11. Honest caveat
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    def test_caveat_mentions_floating_holder(self):
        result = generate_tap_cycle([_simple_hole()])
        caveat_lower = result.honest_caveat.lower()
        assert "floating" in caveat_lower

    def test_caveat_mentions_feed_coupling(self):
        result = generate_tap_cycle([_simple_hole()])
        assert "pitch" in result.honest_caveat.lower() or "f =" in result.honest_caveat.lower()

    def test_caveat_mentions_acceleration(self):
        result = generate_tap_cycle([_simple_hole()])
        caveat_lower = result.honest_caveat.lower()
        assert "acceleration" in caveat_lower or "ramp" in caveat_lower


# ---------------------------------------------------------------------------
# 12. LLM tool (async, no DB)
# ---------------------------------------------------------------------------

class TestLLMTool:
    def test_tool_spec_name(self):
        assert cam_generate_tap_cycle_spec.name == "cam_generate_tap_cycle"

    def test_tool_runs_single_right_hole(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{
                "x_mm": 0.0, "y_mm": 0.0,
                "depth_mm": 12.0,
                "thread_pitch_mm": 1.0,
                "spindle_rpm": 1000.0,
                "direction": "right",
            }]
        }).encode()
        raw = _run_async(run_cam_generate_tap_cycle(ctx, args))
        result = json.loads(raw)
        assert "gcode" in result
        assert "G84" in result["gcode"]
        assert result["num_holes"] == 1
        assert result["computed_feed_mm_per_min"] == pytest.approx(1000.0, abs=0.001)

    def test_tool_runs_left_hand_hole(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{
                "x_mm": 5.0, "y_mm": 5.0,
                "depth_mm": 10.0,
                "thread_pitch_mm": 1.25,
                "spindle_rpm": 800.0,
                "direction": "left",
            }]
        }).encode()
        raw = _run_async(run_cam_generate_tap_cycle(ctx, args))
        result = json.loads(raw)
        gcode = result["gcode"]
        assert "G74" in gcode
        # G84 must NOT appear in non-comment lines (header may mention G84/G74)
        code_lines = [
            ln for ln in gcode.splitlines()
            if not ln.strip().startswith("(")
        ]
        assert "G84" not in "\n".join(code_lines)

    def test_tool_rigid_tap_false_no_m29(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{
                "x_mm": 0.0, "y_mm": 0.0,
                "depth_mm": 10.0,
                "thread_pitch_mm": 1.0,
                "spindle_rpm": 1000.0,
                "direction": "right",
            }],
            "rigid_tap": False,
        }).encode()
        raw = _run_async(run_cam_generate_tap_cycle(ctx, args))
        result = json.loads(raw)
        assert "M29" not in result["gcode"]

    def test_tool_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run_async(run_cam_generate_tap_cycle(ctx, b"not-json"))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_empty_holes_returns_error(self):
        ctx = _ctx()
        args = json.dumps({"holes": []}).encode()
        raw = _run_async(run_cam_generate_tap_cycle(ctx, args))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_missing_required_field_returns_error(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{"x_mm": 0.0, "y_mm": 0.0}]  # missing required fields
        }).encode()
        raw = _run_async(run_cam_generate_tap_cycle(ctx, args))
        result = json.loads(raw)
        assert "error" in result

    def test_tool_multi_hole_g80_present(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [
                {"x_mm": 0.0, "y_mm": 0.0, "depth_mm": 10.0,
                 "thread_pitch_mm": 1.0, "spindle_rpm": 1000.0, "direction": "right"},
                {"x_mm": 25.0, "y_mm": 0.0, "depth_mm": 10.0,
                 "thread_pitch_mm": 1.0, "spindle_rpm": 1000.0, "direction": "right"},
            ]
        }).encode()
        raw = _run_async(run_cam_generate_tap_cycle(ctx, args))
        result = json.loads(raw)
        assert "G80" in result["gcode"]
        assert result["num_holes"] == 2

    def test_tool_honest_caveat_present(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{
                "x_mm": 5.0, "y_mm": 5.0,
                "depth_mm": 10.0,
                "thread_pitch_mm": 1.0,
                "spindle_rpm": 1000.0,
                "direction": "right",
            }]
        }).encode()
        raw = _run_async(run_cam_generate_tap_cycle(ctx, args))
        result = json.loads(raw)
        assert "honest_caveat" in result
        assert len(result["honest_caveat"]) > 20
