"""
Hermetic tests for kerf_cad_core.cam_gcode_emit — G-code emitter.

Coverage:
  emit_gcode — linear toolpath produces G01 lines
  emit_gcode — rapid moves produce G00 lines
  emit_gcode — CW arc produces G02 with correct I/J
  emit_gcode — CCW arc produces G03 with correct I/J
  emit_gcode — tool change emits M05 + T.. M06
  emit_gcode — feedrate change emits F word; modal suppression
  emit_gcode — spindle on/off emits M03 / M05 with S word
  emit_gcode — program number emits O-number
  emit_gcode — header comment emitted in parentheses
  emit_gcode — program ends with M02
  emit_gcode — round-trip: emit → parse_gcode → same waypoints
  emit_gcode — oracle G-code: manual 5-waypoint sample
  emit_gcode — I/J arc centre offsets: circle quadrant oracle check
  emit_gcode — warning emitted when no F on first feed move
  cam_emit_gcode LLM tool — happy path
  cam_emit_gcode LLM tool — missing toolpath → error
  cam_emit_gcode LLM tool — bad JSON → error

All tests are pure-Python and hermetic: no OCC, no DB, no network.

References:
  NIST RS-274/NGC Interpreter Version 3 (Kramer et al. 2000).
  Smid, P. CNC Programming Handbook (2008) §3.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import uuid

import pytest

from kerf_cad_core.cam_gcode_emit import (
    emit_gcode,
    GcodeProgram,
    rapid,
    linear,
    arc_cw,
    arc_ccw,
    spindle_on,
    spindle_off,
    tool_change,
    comment,
)
from kerf_cad_core.gcode.post import parse_gcode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _ctx():
    try:
        from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
        return ProjectCtx(
            pool=None, storage=None,
            project_id=uuid.uuid4(), user_id=uuid.uuid4(),
            role="owner", http_client=None,
        )
    except Exception:
        return None


def _args_bytes(**kwargs) -> bytes:
    return json.dumps(kwargs).encode()


def _ok(raw: str) -> dict:
    d = json.loads(raw)
    # ok_payload returns the dict directly (no "ok" wrapper);
    # err_payload returns {"error": ..., "code": ...}
    assert "error" not in d, f"Expected success payload, got: {d}"
    return d


def _err(raw: str) -> dict:
    d = json.loads(raw)
    # err_payload returns {"error": ..., "code": ...}
    assert "error" in d or d.get("ok") is False, f"Expected error, got: {d}"
    return d


ABS_TOL = 1e-4  # 0.1 µm — well within 4 decimal place formatting


# ===========================================================================
# 1. Rapid move → G00
# ===========================================================================

class TestRapidMove:

    def test_rapid_produces_g00(self):
        prog = emit_gcode([rapid(10.0, 20.0, 5.0)])
        assert "G00" in prog.text

    def test_rapid_xyz_present(self):
        prog = emit_gcode([rapid(1.5, 2.5, 3.5)])
        assert "X1.5" in prog.text
        assert "Y2.5" in prog.text
        assert "Z3.5" in prog.text

    def test_rapid_no_f_word(self):
        """Rapid moves must NOT emit an F word (they run at machine rapid rate)."""
        prog = emit_gcode([rapid(10.0, 0.0, 0.0)])
        # Find the G00 line
        g00_lines = [l for l in prog.text.splitlines() if "G00" in l]
        assert g00_lines, "No G00 line found"
        for line in g00_lines:
            assert "F" not in line, f"F word in G00 line: {line!r}"


# ===========================================================================
# 2. Linear move → G01
# ===========================================================================

class TestLinearMove:

    def test_linear_produces_g01(self):
        prog = emit_gcode([linear(5.0, 10.0, -2.0, f=300.0)])
        assert "G01" in prog.text

    def test_linear_emits_f_word(self):
        prog = emit_gcode([linear(5.0, 0.0, 0.0, f=500.0)])
        assert "F500." in prog.text

    def test_linear_modal_f_suppressed(self):
        """Second linear move at same F should NOT repeat F word."""
        toolpath = [
            linear(5.0, 0.0, 0.0, f=300.0),
            linear(10.0, 0.0, 0.0, f=300.0),
        ]
        prog = emit_gcode(toolpath)
        f_count = prog.text.count("F300.")
        assert f_count == 1, f"Expected F300. once (modal), found {f_count} times"

    def test_linear_f_change_emitted(self):
        """Different F on second move must emit new F word."""
        toolpath = [
            linear(5.0, 0.0, 0.0, f=300.0),
            linear(10.0, 0.0, 0.0, f=600.0),
        ]
        prog = emit_gcode(toolpath)
        assert "F300." in prog.text
        assert "F600." in prog.text

    def test_linear_no_f_generates_warning(self):
        prog = emit_gcode([linear(5.0, 0.0, 0.0)])  # no F, no prior modal
        assert prog.warnings, "Expected warning for missing F"

    def test_10_waypoint_toolpath_all_g01(self):
        """10-waypoint linear toolpath — every motion line is G01 (or modal G01)."""
        toolpath = [linear(float(i), 0.0, 0.0, f=200.0) for i in range(1, 11)]
        prog = emit_gcode(toolpath)
        # At least 1 G01 block present; all motion blocks should be linear
        assert "G01" in prog.text
        assert "G00" not in prog.text  # no rapid


# ===========================================================================
# 3. Circular arcs → G02 / G03 with I/J
# ===========================================================================

class TestArcMoves:

    # Oracle: 90° CW arc from (10, 0) to (0, 10), centre at origin.
    # Start point (10, 0); centre = (0, 0); I = 0-10 = -10, J = 0-0 = 0
    _CW_90 = arc_cw(x=0.0, y=10.0, z=0.0, i=-10.0, j=0.0, f=200.0,
                    comment="90deg CW arc")

    # Oracle: 90° CCW arc from (10, 0) to (0, 10), centre at origin.
    # Same start/end, opposite direction: G03
    _CCW_90 = arc_ccw(x=0.0, y=10.0, z=0.0, i=-10.0, j=0.0, f=200.0,
                      comment="90deg CCW arc")

    def test_arc_cw_produces_g02(self):
        prog = emit_gcode([self._CW_90])
        assert "G02" in prog.text

    def test_arc_ccw_produces_g03(self):
        prog = emit_gcode([self._CCW_90])
        assert "G03" in prog.text

    def test_arc_cw_ij_offsets_oracle(self):
        """CW arc I/J match the oracle values I=-10, J=0."""
        prog = emit_gcode([self._CW_90])
        assert "I-10." in prog.text
        # J0 should be present
        assert "J0." in prog.text

    def test_arc_ccw_g03_ij_present(self):
        prog = emit_gcode([self._CCW_90])
        assert "I-10." in prog.text
        assert "J0." in prog.text

    def test_arc_cw_no_arc_ccw_code(self):
        prog = emit_gcode([self._CW_90])
        assert "G03" not in prog.text

    def test_arc_radius_quarter_circle(self):
        """
        Quarter-circle CW from (r,0) → (0,r).  I/J offsets = centre - start.
        Oracle: start=(5,0,0), end=(0,5,0), centre=(0,0,0) → I=-5, J=0.
        """
        r = 5.0
        wp = arc_cw(x=0.0, y=r, z=0.0, i=-r, j=0.0, f=300.0)
        prog = emit_gcode([wp])
        assert "G02" in prog.text
        # _fmt(-5.0, 4) → "I-5."
        assert "I-5." in prog.text

    def test_arc_with_feedrate_emits_f(self):
        prog = emit_gcode([self._CW_90])
        assert "F200." in prog.text


# ===========================================================================
# 4. Tool change → M06
# ===========================================================================

class TestToolChange:

    def test_tool_change_emits_m06(self):
        prog = emit_gcode([tool_change(2)])
        assert "M06" in prog.text

    def test_tool_change_emits_t_word(self):
        prog = emit_gcode([tool_change(3)])
        assert "T03" in prog.text

    def test_tool_change_preceded_by_m05(self):
        """M05 (spindle stop) must appear before M06 (Smid 2008 §3.12)."""
        prog = emit_gcode([spindle_on(1000), tool_change(2)])
        m05_pos = prog.text.find("M05")
        m06_pos = prog.text.find("M06")
        assert m05_pos != -1 and m06_pos != -1
        assert m05_pos < m06_pos, "M05 must precede M06"

    def test_multiple_tool_changes(self):
        toolpath = [tool_change(1), tool_change(2), tool_change(3)]
        prog = emit_gcode(toolpath)
        assert prog.text.count("M06") == 3

    def test_tool_number_formatting(self):
        """Tool numbers should be zero-padded to 2 digits."""
        prog = emit_gcode([tool_change(5)])
        assert "T05" in prog.text


# ===========================================================================
# 5. Spindle on/off
# ===========================================================================

class TestSpindle:

    def test_spindle_on_emits_m03(self):
        prog = emit_gcode([spindle_on(1500)])
        assert "M03" in prog.text

    def test_spindle_on_emits_s_word(self):
        prog = emit_gcode([spindle_on(2000)])
        # _fmt(2000, 0) = "2000" (no decimal point for integer S-word)
        assert "S2000" in prog.text
        assert "S2000 M03" in prog.text

    def test_spindle_off_emits_m05(self):
        prog = emit_gcode([spindle_off()])
        assert "M05" in prog.text


# ===========================================================================
# 6. Program structure
# ===========================================================================

class TestProgramStructure:

    def test_program_ends_with_m02(self):
        prog = emit_gcode([rapid(0, 0, 0)])
        assert "M02" in prog.text

    def test_program_number_emits_o_word(self):
        prog = emit_gcode([rapid(0, 0, 0)], program_number=1234)
        assert "O1234" in prog.text

    def test_header_comment_emitted(self):
        prog = emit_gcode([rapid(0, 0, 0)], header_comment="Test program")
        assert "(Test program)" in prog.text

    def test_startup_defaults_present(self):
        """G17 G21 G90 G94 block must appear for safe startup (NIST §3.4)."""
        prog = emit_gcode([rapid(0, 0, 0)])
        assert "G17" in prog.text
        assert "G21" in prog.text
        assert "G90" in prog.text

    def test_line_count_nonzero(self):
        prog = emit_gcode([rapid(0, 0, 0)])
        assert prog.line_count > 0

    def test_comment_waypoint(self):
        prog = emit_gcode([comment("Setup complete")])
        assert "(Setup complete)" in prog.text

    def test_inline_comment_on_move(self):
        prog = emit_gcode([rapid(5.0, 0.0, 0.0, comment="approach")])
        assert "(approach)" in prog.text


# ===========================================================================
# 7. Round-trip: emit → parse_gcode → same endpoints
# ===========================================================================

class TestRoundTrip:

    def test_linear_round_trip_endpoints(self):
        """Emit 5 linear moves then parse → endpoints match oracle."""
        oracle = [(1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0),
                  (4.0, 0.0, 0.0), (5.0, 0.0, 0.0)]
        toolpath = [linear(x, y, z, f=300.0) for x, y, z in oracle]
        prog = emit_gcode(toolpath)

        parsed = parse_gcode(prog.text)

        # Collect feed-move end points
        feed_segs = [s for s in parsed["segments"] if s["type"] == "feed"]
        assert len(feed_segs) == len(oracle), (
            f"Expected {len(oracle)} feed segs, got {len(feed_segs)}"
        )
        for seg, (ox, oy, oz) in zip(feed_segs, oracle):
            ex, ey, ez = seg["end"]
            assert abs(ex - ox) < ABS_TOL, f"X mismatch: {ex} vs {ox}"
            assert abs(ey - oy) < ABS_TOL, f"Y mismatch: {ey} vs {oy}"
            assert abs(ez - oz) < ABS_TOL, f"Z mismatch: {ez} vs {oz}"

    def test_rapid_round_trip_endpoints(self):
        """Emit 3 rapid moves then parse → rapid endpoints match."""
        oracle = [(10.0, 0.0, 5.0), (20.0, 10.0, 5.0), (0.0, 0.0, 10.0)]
        toolpath = [rapid(x, y, z) for x, y, z in oracle]
        prog = emit_gcode(toolpath)

        parsed = parse_gcode(prog.text)
        rapid_segs = [s for s in parsed["segments"] if s["type"] == "rapid"]
        assert len(rapid_segs) == len(oracle)
        for seg, (ox, oy, oz) in zip(rapid_segs, oracle):
            ex, ey, ez = seg["end"]
            assert abs(ex - ox) < ABS_TOL
            assert abs(ey - oy) < ABS_TOL
            assert abs(ez - oz) < ABS_TOL


# ===========================================================================
# 8. Oracle G-code: manual sample
# ===========================================================================

class TestOracleGcode:
    """Manual oracle: verify exact output against a known-good reference.

    Reference program (Smid 2008 §3.1 example pattern adapted):
      Tool 1, spindle 2500 RPM, rapid to (0,0,2), plunge to Z-2, cut to (50,0),
      arc CW to (100, 0) with R=25 (centre at 75,0 → I=25, J=0),
      retract, program end.
    """

    def _make_oracle_toolpath(self):
        return [
            tool_change(1),
            spindle_on(2500),
            rapid(0.0, 0.0, 2.0),
            linear(0.0, 0.0, -2.0, f=100.0, comment="plunge"),
            linear(50.0, 0.0, -2.0, f=250.0),
            arc_cw(100.0, 0.0, -2.0, i=25.0, j=0.0, f=250.0,
                   comment="CW arc R25"),
            rapid(0.0, 0.0, 50.0),
        ]

    def test_oracle_contains_all_codes(self):
        prog = emit_gcode(self._make_oracle_toolpath(), program_number=1)
        text = prog.text
        assert "O0001" in text, "Missing O-number"
        assert "T01 M06" in text, "Missing tool change"
        assert "S2500 M03" in text, "Missing spindle-on"
        assert "G00" in text, "Missing rapid"
        assert "G01" in text, "Missing linear"
        assert "G02" in text, "Missing CW arc"
        assert "M02" in text, "Missing program end"

    def test_oracle_arc_ij(self):
        prog = emit_gcode(self._make_oracle_toolpath())
        g02_line = next(
            (l for l in prog.text.splitlines() if "G02" in l), None
        )
        assert g02_line is not None, "No G02 line found"
        assert "I25." in g02_line, f"Expected I25. in {g02_line!r}"
        assert "J0." in g02_line, f"Expected J0. in {g02_line!r}"

    def test_oracle_comment_in_parens(self):
        prog = emit_gcode(self._make_oracle_toolpath())
        assert "(plunge)" in prog.text
        assert "(CW arc R25)" in prog.text


# ===========================================================================
# 9. LLM tool — cam_emit_gcode
# ===========================================================================

class TestCamEmitGcodeTool:
    """Happy-path and error-path tests for the cam_emit_gcode LLM tool wrapper."""

    def _import_tool(self):
        """Import the tool function; skip if kerf_chat unavailable."""
        try:
            from kerf_cad_core.cam_gcode_emit import _run_cam_emit_gcode
            return _run_cam_emit_gcode
        except ImportError:
            pytest.skip("kerf_chat not installed — LLM tool tests skipped")

    def test_happy_path_linear(self):
        fn = self._import_tool()
        ctx = _ctx()
        toolpath = [
            {"type": "spindle_on", "s": 1000},
            {"type": "linear", "x": 10.0, "y": 0.0, "z": 0.0, "f": 300.0},
            {"type": "linear", "x": 20.0, "y": 0.0, "z": 0.0},
        ]
        raw = _run(fn(ctx, _args_bytes(toolpath=toolpath)))
        d = _ok(raw)
        assert "gcode" in d
        assert "G01" in d["gcode"]
        assert d["line_count"] > 0

    def test_happy_path_arc(self):
        fn = self._import_tool()
        ctx = _ctx()
        toolpath = [
            {"type": "arc_cw", "x": 0.0, "y": 10.0, "z": 0.0,
             "i": -10.0, "j": 0.0, "f": 200.0},
        ]
        raw = _run(fn(ctx, _args_bytes(toolpath=toolpath)))
        d = _ok(raw)
        assert "G02" in d["gcode"]
        assert "I-10." in d["gcode"]

    def test_happy_path_tool_change(self):
        fn = self._import_tool()
        ctx = _ctx()
        toolpath = [{"type": "tool_change", "tool": 3}]
        raw = _run(fn(ctx, _args_bytes(toolpath=toolpath)))
        d = _ok(raw)
        assert "M06" in d["gcode"]
        assert "T03" in d["gcode"]

    def test_missing_toolpath_returns_error(self):
        fn = self._import_tool()
        ctx = _ctx()
        raw = _run(fn(ctx, _args_bytes()))
        _err(raw)

    def test_bad_json_returns_error(self):
        fn = self._import_tool()
        ctx = _ctx()
        raw = _run(fn(ctx, b"not-json"))
        _err(raw)

    def test_program_number_in_output(self):
        fn = self._import_tool()
        ctx = _ctx()
        toolpath = [{"type": "rapid", "x": 0.0, "y": 0.0, "z": 5.0}]
        raw = _run(fn(ctx, _args_bytes(toolpath=toolpath, program_number=42)))
        d = _ok(raw)
        assert "O0042" in d["gcode"]

    def test_header_comment_in_output(self):
        fn = self._import_tool()
        ctx = _ctx()
        toolpath = [{"type": "rapid", "x": 0.0, "y": 0.0, "z": 0.0}]
        raw = _run(fn(ctx, _args_bytes(
            toolpath=toolpath,
            header_comment="kerf test program",
        )))
        d = _ok(raw)
        assert "(kerf test program)" in d["gcode"]

    def test_dialect_field_present(self):
        fn = self._import_tool()
        ctx = _ctx()
        toolpath = [{"type": "rapid", "x": 0.0, "y": 0.0, "z": 0.0}]
        raw = _run(fn(ctx, _args_bytes(toolpath=toolpath)))
        d = _ok(raw)
        assert "dialect" in d
        assert "Fanuc" in d["dialect"]
