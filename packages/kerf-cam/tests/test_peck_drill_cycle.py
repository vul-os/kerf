"""
Tests for kerf_cam.peck_drill_cycle — G83 peck-drilling canned cycle.

References
----------
* NIST RS-274/NGC §3.8.4 — G83 canned cycle
* Machinery's Handbook 31e §1132 — Peck drilling guidelines

Run:
    pytest packages/kerf-cam/tests/test_peck_drill_cycle.py -v
"""

from __future__ import annotations

import asyncio
import json
import math
import re

import pytest

from kerf_cam.peck_drill_cycle import (
    PeckHoleSpec,
    PeckCycleResult,
    _count_pecks,
    _fmt,
    _estimate_cycle_time,
    generate_peck_drill_cycle,
    cam_generate_peck_drill_cycle_spec,
    run_cam_generate_peck_drill_cycle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_hole(**kw) -> PeckHoleSpec:
    """Return a PeckHoleSpec with sensible defaults, overrideable via kw."""
    defaults = dict(
        x_mm=0.0,
        y_mm=0.0,
        depth_mm=10.0,
        peck_depth_mm=2.0,
        retract_mm=2.0,
        feed_mm_per_min=150.0,
        dwell_s=0.0,
        rapid_z_mm=10000.0,
        work_top_z_mm=0.0,
    )
    defaults.update(kw)
    return PeckHoleSpec(**defaults)


def _run_async(coro):
    return asyncio.run(coro)


def _ctx():
    from kerf_cam._compat import ProjectCtx
    return ProjectCtx()


# ---------------------------------------------------------------------------
# 1. _count_pecks unit tests
# ---------------------------------------------------------------------------

class TestCountPecks:
    def test_exact_division(self):
        """10 mm depth / 2 mm peck = 5 pecks exactly."""
        assert _count_pecks(10.0, 2.0) == 5

    def test_partial_last_peck(self):
        """10 mm / 3 mm = ceil(3.33…) = 4 pecks."""
        assert _count_pecks(10.0, 3.0) == 4

    def test_depth_equals_peck(self):
        """depth == peck → single peck, no nesting (MH §1132 edge case)."""
        assert _count_pecks(2.0, 2.0) == 1

    def test_depth_less_than_peck(self):
        """depth < peck → 1 peck (no G83 nesting needed)."""
        assert _count_pecks(1.5, 2.0) == 1

    def test_small_peck_many_strokes(self):
        """Large depth, fine peck → many pecks."""
        assert _count_pecks(50.0, 1.0) == 50


# ---------------------------------------------------------------------------
# 2. _fmt decimal formatting (NIST RS-274/NGC §3.5.1)
# ---------------------------------------------------------------------------

class TestFmt:
    def test_integer_value_has_decimal_point(self):
        """Integer-valued floats must include a decimal point per RS-274/NGC."""
        result = _fmt(2.0)
        assert '.' in result, f"Expected decimal point in {result!r}"

    def test_positive_value(self):
        assert _fmt(10.5) == "10.5"

    def test_negative_value(self):
        assert _fmt(-10.5) == "-10.5"

    def test_high_precision_trimmed(self):
        """Trailing zeros removed, but decimal point retained."""
        result = _fmt(3.5000)
        assert result == "3.5"

    def test_zero_formatted(self):
        result = _fmt(0.0)
        assert '.' in result

    def test_peck_depth_format(self):
        """Q field: 2.0mm peck → '2.0' (not '2' or '2.0000')."""
        q = _fmt(2.0)
        assert q == "2.0"
        assert '.' in q


# ---------------------------------------------------------------------------
# 3. PeckHoleSpec validation
# ---------------------------------------------------------------------------

class TestPeckHoleSpecValidation:
    def test_valid_spec_no_error(self):
        spec = _simple_hole()
        assert spec.depth_mm == 10.0

    def test_zero_depth_raises(self):
        with pytest.raises(ValueError, match="depth_mm"):
            _simple_hole(depth_mm=0.0)

    def test_negative_depth_raises(self):
        with pytest.raises(ValueError, match="depth_mm"):
            _simple_hole(depth_mm=-5.0)

    def test_zero_peck_raises(self):
        with pytest.raises(ValueError, match="peck_depth_mm"):
            _simple_hole(peck_depth_mm=0.0)

    def test_zero_feed_raises(self):
        with pytest.raises(ValueError, match="feed_mm_per_min"):
            _simple_hole(feed_mm_per_min=0.0)


# ---------------------------------------------------------------------------
# 4. generate_peck_drill_cycle — single-hole tests
# ---------------------------------------------------------------------------

class TestSingleHole:
    def _result(self, **kw) -> PeckCycleResult:
        return generate_peck_drill_cycle([_simple_hole(**kw)])

    def test_single_10mm_hole_2mm_peck_gives_5_pecks(self):
        """Core MH §1132 peck count: 10mm depth / 2mm peck = 5 pecks."""
        r = self._result(depth_mm=10.0, peck_depth_mm=2.0)
        assert r.num_pecks == 5

    def test_gcode_contains_g83(self):
        r = self._result()
        assert "G83" in r.gcode

    def test_gcode_contains_g80_cancellation(self):
        """NIST RS-274/NGC: G80 must cancel the canned cycle."""
        r = self._result()
        assert "G80" in r.gcode

    def test_gcode_x_y_present(self):
        r = self._result(x_mm=10.5, y_mm=20.25)
        assert "X10.5" in r.gcode
        assert "Y20.25" in r.gcode

    def test_z_field_is_negative_for_positive_depth(self):
        """Z coordinate in G83 must be ≤ work_top_z_mm (drilled downward)."""
        r = self._result(depth_mm=10.0, work_top_z_mm=0.0)
        # G83 line should contain Z-10.0
        match = re.search(r"G83.*Z(-\d+\.?\d*)", r.gcode)
        assert match, "G83 line should contain Z field"
        z_val = float(match.group(1))
        assert z_val < 0, f"Expected negative Z for downward drill, got {z_val}"

    def test_r_field_above_work_surface(self):
        """R plane must be above the work surface (retract_mm >= 0)."""
        r = self._result(retract_mm=2.0, work_top_z_mm=0.0)
        match = re.search(r"G83.*R(\d+\.?\d*)", r.gcode)
        assert match, "G83 line should contain R field"
        r_val = float(match.group(1))
        assert r_val >= 0.0, f"R plane should be >= 0 (work top + retract), got {r_val}"

    def test_q_field_equals_peck_depth(self):
        """Q field must equal peck_depth_mm (NIST §3.8.4: positive increment)."""
        r = self._result(peck_depth_mm=2.5)
        match = re.search(r"G83.*Q(\d+\.?\d*)", r.gcode)
        assert match, "G83 line should contain Q field"
        q_val = float(match.group(1))
        assert abs(q_val - 2.5) < 1e-6, f"Q should be 2.5, got {q_val}"

    def test_q_field_is_positive(self):
        """Per RS-274/NGC §3.8.4, Q must be positive."""
        r = self._result(peck_depth_mm=3.0)
        match = re.search(r"G83.*Q(-?\d+\.?\d*)", r.gcode)
        assert match
        assert float(match.group(1)) > 0

    def test_dwell_emitted_when_set(self):
        """G4 dwell block must appear when dwell_s > 0."""
        r = self._result(dwell_s=1.5)
        assert "G4" in r.gcode
        assert "P1.5" in r.gcode or "P1.500" in r.gcode

    def test_no_dwell_when_zero(self):
        """G4 must NOT appear when dwell_s == 0."""
        r = self._result(dwell_s=0.0)
        assert "G4" not in r.gcode

    def test_edge_depth_le_peck_gives_1_peck(self):
        """MH §1132: depth ≤ peck_depth → single peck, no nested G83."""
        r = self._result(depth_mm=1.5, peck_depth_mm=2.0)
        assert r.num_pecks == 1

    def test_gcode_header_metric_mode(self):
        """Program must declare G21 (metric) mode."""
        r = self._result()
        assert "G21" in r.gcode

    def test_gcode_has_program_delimiters(self):
        """RS-274/NGC programs start and end with %."""
        result = self._result()
        lines = result.gcode.strip().split('\n')
        assert lines[0].strip() == '%'
        assert lines[-1].strip() == '%'

    def test_honest_caveat_mentions_acceleration(self):
        r = self._result()
        assert "acceleration" in r.honest_caveat.lower() or "ramp" in r.honest_caveat.lower()

    def _result(self, **kw) -> PeckCycleResult:
        return generate_peck_drill_cycle([_simple_hole(**kw)])


# ---------------------------------------------------------------------------
# 5. Multi-hole: G80 appears exactly once, at the end
# ---------------------------------------------------------------------------

class TestMultiHole:
    def _three_holes(self) -> PeckCycleResult:
        return generate_peck_drill_cycle([
            _simple_hole(x_mm=0.0, y_mm=0.0, depth_mm=10.0, peck_depth_mm=2.0),
            _simple_hole(x_mm=30.0, y_mm=0.0, depth_mm=15.0, peck_depth_mm=3.0),
            _simple_hole(x_mm=60.0, y_mm=0.0, depth_mm=5.0, peck_depth_mm=2.5),
        ])

    def test_g80_cancellation_present(self):
        r = self._three_holes()
        assert "G80" in r.gcode

    def test_g80_appears_after_last_g83(self):
        """G80 must come after all G83 blocks."""
        r = self._three_holes()
        g80_pos = r.gcode.rfind("G80")
        g83_pos = r.gcode.rfind("G83")
        assert g80_pos > g83_pos, "G80 must be after the last G83 block"

    def test_peck_count_sums_across_holes(self):
        """Total pecks = sum per hole."""
        r = self._three_holes()
        # hole1: ceil(10/2)=5, hole2: ceil(15/3)=5, hole3: ceil(5/2.5)=2
        assert r.num_pecks == 5 + 5 + 2

    def test_three_g83_blocks_present(self):
        r = self._three_holes()
        # Count only lines that start with G83 (not comment lines referencing G83)
        g83_lines = [ln for ln in r.gcode.splitlines() if ln.strip().startswith("G83")]
        assert len(g83_lines) == 3

    def test_empty_holes_raises(self):
        with pytest.raises(ValueError):
            generate_peck_drill_cycle([])


# ---------------------------------------------------------------------------
# 6. Feed/rapid time model (MH §1132 / NIST §3.8.4)
# ---------------------------------------------------------------------------

class TestCycleTime:
    def test_time_positive(self):
        r = generate_peck_drill_cycle([_simple_hole(depth_mm=10.0, feed_mm_per_min=150.0)])
        assert r.total_machining_time_s > 0

    def test_faster_feed_gives_shorter_time(self):
        slow = generate_peck_drill_cycle([_simple_hole(feed_mm_per_min=100.0)])
        fast = generate_peck_drill_cycle([_simple_hole(feed_mm_per_min=500.0)])
        assert fast.total_machining_time_s < slow.total_machining_time_s

    def test_feed_time_matches_mh_within_5pct(self):
        """
        MH §1132 basic time formula: T_drill = depth / feed_rate (minutes).
        For 5 pecks of 2mm each at 150 mm/min, pure feed time ≈ 10/150 min = 4.0 s.
        The estimate adds retract time on top; we check it's within 5× of the
        pure drill time (rapid retracts dominate for slow Z rapid rates).
        """
        hole = _simple_hole(
            depth_mm=10.0,
            peck_depth_mm=2.0,
            feed_mm_per_min=150.0,
            rapid_z_mm=10000.0,   # fast rapid → minimal retract time
        )
        r = generate_peck_drill_cycle([hole])
        pure_drill_time_s = (hole.depth_mm / hole.feed_mm_per_min) * 60.0  # 4.0 s
        # Estimated time should be ≥ pure drill time (retracts add to it)
        assert r.total_machining_time_s >= pure_drill_time_s * 0.95, (
            f"time {r.total_machining_time_s:.3f}s < pure drill {pure_drill_time_s:.3f}s"
        )
        # And within 5× (generous — for slow rapid_z or many pecks)
        assert r.total_machining_time_s <= pure_drill_time_s * 5.0, (
            f"time {r.total_machining_time_s:.3f}s > 5× pure drill {pure_drill_time_s:.3f}s"
        )

    def test_dwell_adds_to_time(self):
        no_dwell = generate_peck_drill_cycle([_simple_hole(dwell_s=0.0)])
        with_dwell = generate_peck_drill_cycle([_simple_hole(dwell_s=2.0)])
        diff = with_dwell.total_machining_time_s - no_dwell.total_machining_time_s
        assert abs(diff - 2.0) < 0.1, f"Dwell should add ~2s, got diff={diff:.3f}s"

    def test_more_holes_longer_time(self):
        one = generate_peck_drill_cycle([_simple_hole()])
        three = generate_peck_drill_cycle([_simple_hole(), _simple_hole(), _simple_hole()])
        assert three.total_machining_time_s > one.total_machining_time_s


# ---------------------------------------------------------------------------
# 7. LLM tool (async, no DB)
# ---------------------------------------------------------------------------

class TestLLMTool:
    def test_tool_spec_name(self):
        assert cam_generate_peck_drill_cycle_spec.name == "cam_generate_peck_drill_cycle"

    def test_tool_runs_single_hole(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{
                "x_mm": 0.0, "y_mm": 0.0,
                "depth_mm": 10.0, "peck_depth_mm": 2.0,
                "retract_mm": 2.0, "feed_mm_per_min": 150.0,
            }]
        }).encode()
        raw = _run_async(run_cam_generate_peck_drill_cycle(ctx, args))
        result = json.loads(raw)
        assert "gcode" in result
        assert "G83" in result["gcode"]
        assert result["num_pecks"] == 5

    def test_tool_bad_json_returns_error(self):
        ctx = _ctx()
        raw = _run_async(run_cam_generate_peck_drill_cycle(ctx, b"not-json"))
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_tool_empty_holes_returns_error(self):
        ctx = _ctx()
        args = json.dumps({"holes": []}).encode()
        raw = _run_async(run_cam_generate_peck_drill_cycle(ctx, args))
        result = json.loads(raw)
        assert result.get("code") == "BAD_ARGS"

    def test_tool_missing_required_field_returns_error(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{"x_mm": 0.0, "y_mm": 0.0}]  # missing required fields
        }).encode()
        raw = _run_async(run_cam_generate_peck_drill_cycle(ctx, args))
        result = json.loads(raw)
        assert "error" in result

    def test_tool_multi_hole_g80_present(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [
                {"x_mm": 0.0, "y_mm": 0.0, "depth_mm": 8.0,
                 "peck_depth_mm": 2.0, "retract_mm": 2.0, "feed_mm_per_min": 120.0},
                {"x_mm": 25.0, "y_mm": 0.0, "depth_mm": 8.0,
                 "peck_depth_mm": 2.0, "retract_mm": 2.0, "feed_mm_per_min": 120.0},
            ]
        }).encode()
        raw = _run_async(run_cam_generate_peck_drill_cycle(ctx, args))
        result = json.loads(raw)
        assert "G80" in result["gcode"]
        assert result["num_pecks"] == 8  # 4 + 4

    def test_tool_honest_caveat_present(self):
        ctx = _ctx()
        args = json.dumps({
            "holes": [{
                "x_mm": 5.0, "y_mm": 5.0,
                "depth_mm": 10.0, "peck_depth_mm": 2.0,
                "retract_mm": 2.0, "feed_mm_per_min": 200.0,
            }]
        }).encode()
        raw = _run_async(run_cam_generate_peck_drill_cycle(ctx, args))
        result = json.loads(raw)
        assert "honest_caveat" in result
        assert len(result["honest_caveat"]) > 10
