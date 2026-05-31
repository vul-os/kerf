"""
Tests for kerf_cam.boring_cycle — G85/G86/G89 boring canned cycles.

References
----------
* NIST RS-274/NGC §3.8.4 — G85 feed-out, G86 spindle-stop-out, G89 dwell-out
* Machinery's Handbook 31e §1162 — Boring surface finish guidance

Run:
    pytest packages/kerf-cam/tests/test_boring_cycle.py -v
"""

from __future__ import annotations

import asyncio
import json
import re

import pytest

from kerf_cam.boring_cycle import (
    BoreHoleSpec,
    BoreCycleResult,
    _fmt,
    _dwell_s_to_p_word,
    _estimate_boring_cycle_time,
    generate_boring_cycle,
    cam_generate_boring_cycle_spec,
    run_cam_generate_boring_cycle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _hole(cycle_type: str = "G85", **kw) -> BoreHoleSpec:
    """Return a BoreHoleSpec with sensible defaults, overrideable via kw."""
    defaults = dict(
        x_mm=0.0,
        y_mm=0.0,
        depth_mm=20.0,
        feed_mm_per_min=100.0,
        spindle_rpm=1200.0,
        rapid_z_mm=10000.0,
        work_top_z_mm=0.0,
        cycle_type=cycle_type,
        dwell_s=0.0,
        retract_mm=2.0,
    )
    defaults.update(kw)
    return BoreHoleSpec(**defaults)


def _run_async(coro):
    return asyncio.run(coro)


def _ctx():
    from kerf_cam._compat import ProjectCtx
    return ProjectCtx()


# ---------------------------------------------------------------------------
# 1. G85 block field correctness (NIST RS-274/NGC §3.8.4)
# ---------------------------------------------------------------------------

class TestG85BlockFields:
    def test_g85_emits_g85_code(self):
        """G85 cycle must emit G85 keyword."""
        result = generate_boring_cycle([_hole("G85")])
        assert "G85" in result.gcode

    def test_g85_x_field_correct(self):
        result = generate_boring_cycle([_hole("G85", x_mm=12.5)])
        assert "X12.5" in result.gcode

    def test_g85_y_field_correct(self):
        result = generate_boring_cycle([_hole("G85", y_mm=33.0)])
        assert "Y33.0" in result.gcode

    def test_g85_z_field_is_negative_for_positive_depth(self):
        """Z in G85 must be work_top_z − depth_mm (typically negative)."""
        result = generate_boring_cycle([_hole("G85", depth_mm=20.0, work_top_z_mm=0.0)])
        # Z = 0 - 20 = -20
        match = re.search(r"G85.*Z(-\d+\.?\d*)", result.gcode)
        assert match, "G85 line must contain Z field"
        z_val = float(match.group(1))
        assert z_val < 0.0, f"Z should be negative (bore downward), got {z_val}"

    def test_g85_z_depth_value_exact(self):
        """Z = work_top_z_mm - depth_mm."""
        result = generate_boring_cycle([_hole("G85", depth_mm=15.0, work_top_z_mm=5.0)])
        # Expected Z = 5.0 - 15.0 = -10.0
        assert "Z-10.0" in result.gcode

    def test_g85_r_field_present(self):
        """R plane must be present in G85 block."""
        result = generate_boring_cycle([_hole("G85", work_top_z_mm=0.0, retract_mm=2.0)])
        # R = 0.0 + 2.0 = 2.0
        assert "R2.0" in result.gcode

    def test_g85_f_field_correct(self):
        """F word must equal the supplied feed rate."""
        result = generate_boring_cycle([_hole("G85", feed_mm_per_min=80.0)])
        match = re.search(r"G85.*F(\d+\.?\d*)", result.gcode)
        assert match, "G85 line must contain F field"
        assert pytest.approx(float(match.group(1)), abs=0.01) == 80.0

    def test_g85_no_p_word(self):
        """G85 must NOT emit a P (dwell) word — P is G89-specific."""
        result = generate_boring_cycle([_hole("G85")])
        # Extract G85 line only
        g85_line = next(
            ln for ln in result.gcode.splitlines() if ln.startswith("G85")
        )
        assert "P" not in g85_line, f"G85 line must not contain P: {g85_line!r}"


# ---------------------------------------------------------------------------
# 2. G89 block — dwell P-word (NIST RS-274/NGC §3.8.4)
# ---------------------------------------------------------------------------

class TestG89BlockFields:
    def test_g89_emits_g89_code(self):
        result = generate_boring_cycle([_hole("G89", dwell_s=0.5)])
        assert "G89" in result.gcode

    def test_g89_includes_p_word(self):
        """G89 with dwell_s > 0 must include a P word."""
        result = generate_boring_cycle([_hole("G89", dwell_s=1.0)])
        g89_line = next(
            ln for ln in result.gcode.splitlines() if ln.startswith("G89")
        )
        assert "P" in g89_line, f"G89 line must include P dwell: {g89_line!r}"

    def test_g89_p_word_in_microseconds(self):
        """G89 P-word must be dwell in microseconds (NIST §3.8.4)."""
        dwell_s = 0.5
        result = generate_boring_cycle([_hole("G89", dwell_s=dwell_s)])
        g89_line = next(
            ln for ln in result.gcode.splitlines() if ln.startswith("G89")
        )
        # NIST: P is microseconds; 0.5 s = 500000 μs
        assert "P500000" in g89_line, (
            f"Expected P500000 (0.5 s in μs) in G89 line: {g89_line!r}"
        )

    def test_g89_p_1s_dwell(self):
        """1.0 s dwell → P1000000 (1 000 000 μs)."""
        result = generate_boring_cycle([_hole("G89", dwell_s=1.0)])
        g89_line = next(
            ln for ln in result.gcode.splitlines() if ln.startswith("G89")
        )
        assert "P1000000" in g89_line

    def test_g89_x_y_z_r_f_present(self):
        """G89 block must have X, Y, Z, R, P, F fields."""
        result = generate_boring_cycle([
            _hole("G89", x_mm=10.0, y_mm=5.0, depth_mm=20.0, dwell_s=0.3)
        ])
        g89_line = next(
            ln for ln in result.gcode.splitlines() if ln.startswith("G89")
        )
        for field in ("X", "Y", "Z", "R", "P", "F"):
            assert field in g89_line, f"G89 line missing {field!r}: {g89_line!r}"

    def test_dwell_s_to_p_word_conversion(self):
        """Unit test for _dwell_s_to_p_word."""
        assert _dwell_s_to_p_word(0.0) == 0
        assert _dwell_s_to_p_word(1.0) == 1_000_000
        assert _dwell_s_to_p_word(0.5) == 500_000
        assert _dwell_s_to_p_word(0.001) == 1_000
        # Minimum 1 μs for any positive dwell
        assert _dwell_s_to_p_word(1e-9) == 1


# ---------------------------------------------------------------------------
# 3. G86 — spindle-stop + M05 (single-point boring bar)
# ---------------------------------------------------------------------------

class TestG86BlockFields:
    def test_g86_emits_g86_code(self):
        result = generate_boring_cycle([_hole("G86")])
        assert "G86" in result.gcode

    def test_g86_emits_m05_spindle_stop(self):
        """G86 must emit M05 (spindle stop) after the cycle for drag-free retract."""
        result = generate_boring_cycle([_hole("G86")])
        code_lines = result.gcode.splitlines()
        assert any("M05" in ln for ln in code_lines), (
            "G86 program must contain M05 spindle stop"
        )

    def test_g86_m05_after_g86_block(self):
        """M05 spindle-stop must appear after the G86 block."""
        result = generate_boring_cycle([_hole("G86")])
        lines = result.gcode.splitlines()
        # Find first G86 and first M05 that follows it
        g86_idx = next(i for i, ln in enumerate(lines) if ln.startswith("G86"))
        m05_indices = [i for i, ln in enumerate(lines) if "M05" in ln and i > g86_idx]
        assert m05_indices, "M05 must appear after G86 line"

    def test_g86_no_p_word(self):
        """G86 must NOT have a P (dwell) word."""
        result = generate_boring_cycle([_hole("G86")])
        g86_line = next(
            ln for ln in result.gcode.splitlines() if ln.startswith("G86")
        )
        assert "P" not in g86_line, f"G86 must not have P word: {g86_line!r}"

    def test_g86_x_y_z_r_f_present(self):
        result = generate_boring_cycle([_hole("G86", x_mm=5.0, y_mm=10.0)])
        g86_line = next(
            ln for ln in result.gcode.splitlines() if ln.startswith("G86")
        )
        for field in ("X", "Y", "Z", "R", "F"):
            assert field in g86_line, f"G86 line missing {field!r}: {g86_line!r}"


# ---------------------------------------------------------------------------
# 4. G80 — canned cycle cancellation after multi-hole sequence
# ---------------------------------------------------------------------------

class TestG80Cancellation:
    def test_g80_present_single_hole_g85(self):
        result = generate_boring_cycle([_hole("G85")])
        assert "G80" in result.gcode

    def test_g80_present_single_hole_g86(self):
        result = generate_boring_cycle([_hole("G86")])
        assert "G80" in result.gcode

    def test_g80_present_single_hole_g89(self):
        result = generate_boring_cycle([_hole("G89", dwell_s=0.5)])
        assert "G80" in result.gcode

    def test_g80_after_last_boring_block_multi_hole(self):
        """G80 must appear after all boring cycle blocks."""
        holes = [
            _hole("G85", x_mm=0.0),
            _hole("G86", x_mm=20.0),
            _hole("G89", x_mm=40.0, dwell_s=0.3),
        ]
        result = generate_boring_cycle(holes)
        g80_pos = result.gcode.rfind("G80")
        # Find last occurrence of any of the boring codes
        last_bore = max(
            result.gcode.rfind("G85"),
            result.gcode.rfind("G86"),
            result.gcode.rfind("G89"),
        )
        assert g80_pos > last_bore, "G80 must follow the last boring cycle block"

    def test_g80_appears_exactly_once(self):
        """G80 must appear exactly once regardless of hole count."""
        holes = [_hole("G85", x_mm=i * 15.0) for i in range(4)]
        result = generate_boring_cycle(holes)
        g80_count = len(re.findall(r"\bG80\b", result.gcode))
        assert g80_count == 1, f"Expected exactly 1 G80, found {g80_count}"

    def test_multi_hole_all_holes_present(self):
        holes = [
            _hole("G85", x_mm=0.0, y_mm=0.0),
            _hole("G85", x_mm=25.0, y_mm=0.0),
            _hole("G85", x_mm=50.0, y_mm=0.0),
        ]
        result = generate_boring_cycle(holes)
        assert result.num_holes == 3
        # All three X positions should appear in non-comment code
        assert "X0.0" in result.gcode
        assert "X25.0" in result.gcode
        assert "X50.0" in result.gcode


# ---------------------------------------------------------------------------
# 5. Cycle time estimation
# ---------------------------------------------------------------------------

class TestCycleTime:
    def test_cycle_time_positive(self):
        result = generate_boring_cycle([_hole("G85")])
        assert result.total_machining_time_s > 0.0

    def test_g85_depth_feed_contributes_to_time(self):
        """Deeper bore should yield longer cycle time for G85."""
        shallow = generate_boring_cycle([_hole("G85", depth_mm=5.0)])
        deep = generate_boring_cycle([_hole("G85", depth_mm=40.0)])
        assert deep.total_machining_time_s > shallow.total_machining_time_s

    def test_g89_dwell_adds_to_cycle_time(self):
        """G89 with dwell_s > 0 should have longer cycle time than G89 without."""
        no_dwell = generate_boring_cycle([_hole("G89", dwell_s=0.0)])
        with_dwell = generate_boring_cycle([_hole("G89", dwell_s=3.0)])
        diff = with_dwell.total_machining_time_s - no_dwell.total_machining_time_s
        assert abs(diff - 3.0) < 0.5, (
            f"Dwell of 3.0 s should add ~3 s to cycle time; diff={diff:.3f}"
        )

    def test_multi_hole_time_larger_than_single(self):
        one = generate_boring_cycle([_hole("G85")])
        four = generate_boring_cycle([_hole("G85", x_mm=i * 20.0) for i in range(4)])
        assert four.total_machining_time_s > one.total_machining_time_s

    def test_g86_includes_spindle_stop_delay(self):
        """G86 cycle time must be larger than a simple feed-in + rapid-out model
        due to the spindle-stop delay (~0.5 s) modelled internally."""
        result = generate_boring_cycle([_hole("G86", depth_mm=10.0, feed_mm_per_min=200.0)])
        # Feed-in at 200 mm/min for 10 mm = 3 s; the total must exceed 3 s
        t_feed_only = (10.0 / 200.0) * 60.0  # 3 s
        assert result.total_machining_time_s > t_feed_only

    def test_estimate_boring_cycle_time_g85_basic(self):
        """Unit-test _estimate_boring_cycle_time for G85:
        feed-in + feed-out (both at same rate)."""
        hole = _hole("G85", depth_mm=10.0, feed_mm_per_min=100.0, rapid_z_mm=10000.0)
        t = _estimate_boring_cycle_time(hole)
        # feed-in: (10/100)*60 = 6s; feed-out: 6s; approach rapid: (5/10000)*60 = 0.03s
        expected_approx = 6.0 + 6.0 + (5.0 / 10000.0) * 60.0
        assert abs(t - expected_approx) < 0.1, (
            f"Expected ~{expected_approx:.2f}s, got {t:.3f}s"
        )


# ---------------------------------------------------------------------------
# 6. Surface finish class (MH 31e §1162)
# ---------------------------------------------------------------------------

class TestSurfaceFinishClass:
    def test_g85_surface_finish_0p8_um(self):
        result = generate_boring_cycle([_hole("G85")])
        assert "0.8" in result.surface_finish_class

    def test_g86_surface_finish_1p6_um(self):
        result = generate_boring_cycle([_hole("G86")])
        assert "1.6" in result.surface_finish_class

    def test_g89_surface_finish_0p4_um(self):
        result = generate_boring_cycle([_hole("G89", dwell_s=0.5)])
        assert "0.4" in result.surface_finish_class

    def test_mixed_cycles_report_all_classes(self):
        holes = [_hole("G85"), _hole("G89", dwell_s=0.3)]
        result = generate_boring_cycle(holes)
        # Both Ra classes should appear
        assert "0.8" in result.surface_finish_class
        assert "0.4" in result.surface_finish_class


# ---------------------------------------------------------------------------
# 7. BoreHoleSpec validation
# ---------------------------------------------------------------------------

class TestBoreHoleSpecValidation:
    def test_valid_spec_no_error(self):
        spec = _hole("G85")
        assert spec.depth_mm == 20.0

    def test_zero_depth_raises(self):
        with pytest.raises(ValueError, match="depth_mm"):
            _hole("G85", depth_mm=0.0)

    def test_negative_depth_raises(self):
        with pytest.raises(ValueError, match="depth_mm"):
            _hole("G85", depth_mm=-5.0)

    def test_zero_feed_raises(self):
        with pytest.raises(ValueError, match="feed_mm_per_min"):
            _hole("G85", feed_mm_per_min=0.0)

    def test_zero_spindle_rpm_raises(self):
        with pytest.raises(ValueError, match="spindle_rpm"):
            _hole("G85", spindle_rpm=0.0)

    def test_invalid_cycle_type_raises(self):
        with pytest.raises(ValueError, match="cycle_type"):
            _hole("G82")

    def test_negative_dwell_raises(self):
        with pytest.raises(ValueError, match="dwell_s"):
            _hole("G89", dwell_s=-0.1)

    def test_negative_retract_raises(self):
        with pytest.raises(ValueError, match="retract_mm"):
            _hole("G85", retract_mm=-1.0)

    def test_empty_holes_raises(self):
        with pytest.raises(ValueError, match="empty"):
            generate_boring_cycle([])


# ---------------------------------------------------------------------------
# 8. G-code program structure
# ---------------------------------------------------------------------------

class TestGCodeStructure:
    def test_percent_delimiters(self):
        """RS-274/NGC programs start and end with %."""
        result = generate_boring_cycle([_hole("G85")])
        lines = result.gcode.strip().split('\n')
        assert lines[0].strip() == '%'
        assert lines[-1].strip() == '%'

    def test_declares_g21_metric(self):
        result = generate_boring_cycle([_hole("G85")])
        assert "G21" in result.gcode

    def test_declares_g90_absolute(self):
        result = generate_boring_cycle([_hole("G85")])
        assert "G90" in result.gcode

    def test_declares_g94_feed_per_min(self):
        result = generate_boring_cycle([_hole("G85")])
        assert "G94" in result.gcode

    def test_spindle_on_m03_emitted(self):
        """M03 spindle-on must be present for any boring cycle."""
        result = generate_boring_cycle([_hole("G85")])
        assert "M03" in result.gcode


# ---------------------------------------------------------------------------
# 9. Honest caveat content
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    def test_caveat_mentions_single_point_bar(self):
        result = generate_boring_cycle([_hole("G85")])
        assert "single-point" in result.honest_caveat.lower()

    def test_caveat_mentions_no_roughing_finishing(self):
        result = generate_boring_cycle([_hole("G85")])
        caveat_lower = result.honest_caveat.lower()
        assert "roughing" in caveat_lower or "finishing" in caveat_lower

    def test_caveat_mentions_microseconds(self):
        result = generate_boring_cycle([_hole("G89", dwell_s=0.5)])
        assert "microsecond" in result.honest_caveat.lower()

    def test_caveat_mentions_acceleration(self):
        result = generate_boring_cycle([_hole("G85")])
        caveat_lower = result.honest_caveat.lower()
        assert "acceleration" in caveat_lower or "ramp" in caveat_lower


# ---------------------------------------------------------------------------
# 10. LLM tool (async, no DB)
# ---------------------------------------------------------------------------

class TestLLMTool:
    def test_tool_spec_name(self):
        assert cam_generate_boring_cycle_spec.name == "cam_generate_boring_cycle"

    def test_tool_runs_g85_single_hole(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{
                "x_mm": 10.0, "y_mm": 20.0,
                "depth_mm": 25.0,
                "feed_mm_per_min": 80.0,
                "spindle_rpm": 1500.0,
                "cycle_type": "G85",
            }]
        }).encode()
        raw = _run_async(run_cam_generate_boring_cycle(ctx, args))
        result = json.loads(raw)
        assert "gcode" in result
        assert "G85" in result["gcode"]
        assert result["num_holes"] == 1
        assert "0.8" in result["surface_finish_class"]

    def test_tool_runs_g86_single_hole(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{
                "x_mm": 0.0, "y_mm": 0.0,
                "depth_mm": 30.0,
                "feed_mm_per_min": 60.0,
                "spindle_rpm": 800.0,
                "cycle_type": "G86",
            }]
        }).encode()
        raw = _run_async(run_cam_generate_boring_cycle(ctx, args))
        result = json.loads(raw)
        assert "G86" in result["gcode"]
        assert "M05" in result["gcode"]
        assert "1.6" in result["surface_finish_class"]

    def test_tool_runs_g89_with_dwell(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{
                "x_mm": 5.0, "y_mm": 5.0,
                "depth_mm": 15.0,
                "feed_mm_per_min": 50.0,
                "spindle_rpm": 2000.0,
                "cycle_type": "G89",
                "dwell_s": 0.5,
            }]
        }).encode()
        raw = _run_async(run_cam_generate_boring_cycle(ctx, args))
        result = json.loads(raw)
        gcode = result["gcode"]
        assert "G89" in gcode
        assert "P500000" in gcode
        assert "0.4" in result["surface_finish_class"]

    def test_tool_multi_hole_g80_present(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [
                {"x_mm": 0.0, "y_mm": 0.0, "depth_mm": 20.0,
                 "feed_mm_per_min": 100.0, "spindle_rpm": 1000.0, "cycle_type": "G85"},
                {"x_mm": 30.0, "y_mm": 0.0, "depth_mm": 20.0,
                 "feed_mm_per_min": 100.0, "spindle_rpm": 1000.0, "cycle_type": "G85"},
            ]
        }).encode()
        raw = _run_async(run_cam_generate_boring_cycle(ctx, args))
        result = json.loads(raw)
        assert "G80" in result["gcode"]
        assert result["num_holes"] == 2

    def test_tool_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run_async(run_cam_generate_boring_cycle(ctx, b"not-json"))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_empty_holes_returns_error(self):
        ctx = _ctx()
        args = json.dumps({"holes": []}).encode()
        raw = _run_async(run_cam_generate_boring_cycle(ctx, args))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_missing_required_field_returns_error(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{"x_mm": 0.0, "y_mm": 0.0}]  # missing required fields
        }).encode()
        raw = _run_async(run_cam_generate_boring_cycle(ctx, args))
        result = json.loads(raw)
        assert "error" in result

    def test_tool_invalid_cycle_type_returns_error(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{
                "x_mm": 0.0, "y_mm": 0.0,
                "depth_mm": 10.0,
                "feed_mm_per_min": 100.0,
                "spindle_rpm": 1000.0,
                "cycle_type": "G82",
            }]
        }).encode()
        raw = _run_async(run_cam_generate_boring_cycle(ctx, args))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_honest_caveat_present(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{
                "x_mm": 0.0, "y_mm": 0.0,
                "depth_mm": 10.0,
                "feed_mm_per_min": 100.0,
                "spindle_rpm": 1000.0,
                "cycle_type": "G85",
            }]
        }).encode()
        raw = _run_async(run_cam_generate_boring_cycle(ctx, args))
        result = json.loads(raw)
        assert "honest_caveat" in result
        assert len(result["honest_caveat"]) > 50
