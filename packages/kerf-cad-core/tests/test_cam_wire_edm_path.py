"""
Hermetic tests for kerf_cad_core.cam_wire_edm_path — wire-EDM G-code emitter.

Coverage:
  emit_wire_edm_gcode — square profile: G41/G42 present + correct D-register comment
  emit_wire_edm_gcode — square profile: all 4 G01 lines emitted
  emit_wire_edm_gcode — square profile (50x50 mm, wire 0.25 mm): D-register = 0.1500 mm
  emit_wire_edm_gcode — square profile: start offset by lead_in_mm
  emit_wire_edm_gcode — circular profile: G02/G03 with I/J present
  emit_wire_edm_gcode — circular profile: I/J values correct for half-arcs
  emit_wire_edm_gcode — arc_cw segment: G02 emitted
  emit_wire_edm_gcode — arc_ccw segment: G03 emitted
  emit_wire_edm_gcode — side=right -> G42 not G41
  emit_wire_edm_gcode — M50 before profile, M51 after
  emit_wire_edm_gcode — G40 at start (cancel compensation) + G40 after profile
  emit_wire_edm_gcode — G21 metric mode present
  emit_wire_edm_gcode — program number O-word emitted
  emit_wire_edm_gcode — wire_diameter scaling: D-register = radius + spark_gap
  emit_wire_edm_gcode — custom spark_gap: D-register reflects gap
  emit_wire_edm_gcode — feedrate appears in G01 line
  emit_wire_edm_gcode — ValueError: empty profile
  emit_wire_edm_gcode — ValueError: bad side value
  emit_wire_edm_gcode — ValueError: wire_diameter <= 0
  emit_wire_edm_gcode — ValueError: spark_gap < 0
  emit_wire_edm_gcode — complex profile with arcs: all segment types emitted
  emit_wire_edm_gcode — WireEDMProgram dataclass fields populated
  square_profile — dimensions: corners at expected coordinates
  square_profile — ValueError: side_mm <= 0
  circle_profile — start point at rightmost position
  circle_profile — ValueError: radius <= 0
  cam_emit_wire_edm_gcode LLM tool — happy path square returns ok + gcode
  cam_emit_wire_edm_gcode LLM tool — missing profile_2d -> error
  cam_emit_wire_edm_gcode LLM tool — missing start_xy -> error
  cam_emit_wire_edm_gcode LLM tool — bad JSON -> error
  cam_emit_wire_edm_gcode LLM tool — bad side value -> error

All tests are pure-Python and hermetic: no OCC, no DB, no network.

References:
  Tlusty, J. (2000). Manufacturing Processes and Equipment, §13.
  Fanuc wire-EDM manual B-59064EN/01.
  Rajurkar et al. (2013). CIRP Annals 62(2): 779-801.

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import math
import re
import uuid

import pytest

from kerf_cad_core.cam_wire_edm_path import (
    WireEDMProgram,
    emit_wire_edm_gcode,
    square_profile,
    circle_profile,
    _fmt,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _fake_ctx():
    class _Ctx:
        project_id = uuid.uuid4()
    return _Ctx()


def _lines(prog: WireEDMProgram) -> list[str]:
    return [ln for ln in prog.text.splitlines() if ln.strip()]


def _prog_square(side: str = "left", wire: float = 0.25, gap: float = 0.025) -> WireEDMProgram:
    """Emit a 50x50 mm square profile, centred at origin."""
    start, segs = square_profile(0, 0, 50)
    return emit_wire_edm_gcode(segs, start, wire_diameter_mm=wire, spark_gap_mm=gap, side=side)


# ---------------------------------------------------------------------------
# Unit: _fmt helper
# ---------------------------------------------------------------------------

def test_fmt_integer():
    assert _fmt(10.0) == "10."


def test_fmt_fractional():
    assert _fmt(0.135) == "0.135"


def test_fmt_negative():
    assert _fmt(-25.0) == "-25."


# ---------------------------------------------------------------------------
# square_profile builder
# ---------------------------------------------------------------------------

def test_square_profile_corners():
    start, segs = square_profile(0, 0, 50)
    assert start == (-25.0, -25.0)
    assert len(segs) == 4
    # Traverse: BL -> BR -> TR -> TL -> BL
    assert segs[0] == ("line", 25.0, -25.0)  # bottom-right
    assert segs[1] == ("line", 25.0, 25.0)   # top-right
    assert segs[2] == ("line", -25.0, 25.0)  # top-left
    assert segs[3] == ("line", -25.0, -25.0) # back to start


def test_square_profile_nonzero_centre():
    start, segs = square_profile(10, 20, 10)
    assert start == (5.0, 15.0)


def test_square_profile_zero_side_raises():
    with pytest.raises(ValueError, match="side_mm"):
        square_profile(0, 0, 0)


# ---------------------------------------------------------------------------
# circle_profile builder
# ---------------------------------------------------------------------------

def test_circle_profile_start():
    start, segs = circle_profile(0, 0, 25)
    assert start == (25.0, 0.0)
    assert len(segs) == 2


def test_circle_profile_zero_radius_raises():
    with pytest.raises(ValueError, match="radius_mm"):
        circle_profile(0, 0, 0)


def test_circle_profile_cw():
    start, segs = circle_profile(0, 0, 25, ccw=False)
    assert segs[0][0] == "arc_cw"


def test_circle_profile_ccw():
    start, segs = circle_profile(0, 0, 25, ccw=True)
    assert segs[0][0] == "arc_ccw"


# ---------------------------------------------------------------------------
# emit_wire_edm_gcode — basic G-code content
# ---------------------------------------------------------------------------

def test_g21_metric_present():
    prog = _prog_square()
    assert any(ln == "G21" for ln in _lines(prog))


def test_g40_cancel_at_start():
    prog = _prog_square()
    lns = _lines(prog)
    # G40 should appear early (before M50)
    m50_idx = next(i for i, ln in enumerate(lns) if ln.startswith("M50"))
    g40_idx = next(i for i, ln in enumerate(lns) if ln.strip() == "G40")
    assert g40_idx < m50_idx


def test_m50_before_profile():
    prog = _prog_square()
    lns = _lines(prog)
    m50_idx = next(i for i, ln in enumerate(lns) if ln.startswith("M50"))
    # First G01 profile line should come after M50
    first_g01 = next(i for i, ln in enumerate(lns) if ln.startswith("G01"))
    assert m50_idx < first_g01


def test_m51_after_profile():
    prog = _prog_square()
    lns = _lines(prog)
    # M51 should come after all G01 profile lines
    last_g01 = max(i for i, ln in enumerate(lns) if ln.startswith("G01"))
    m51_idx = next(i for i, ln in enumerate(lns) if ln.startswith("M51"))
    assert m51_idx > last_g01


def test_g40_cancel_after_profile():
    """G40 cancels compensation after the profile, before M51."""
    prog = _prog_square()
    lns = _lines(prog)
    m51_idx = next(i for i, ln in enumerate(lns) if ln.startswith("M51"))
    # G40 should appear close to end, before M51
    g40_indices = [i for i, ln in enumerate(lns) if ln.strip() == "G40"]
    # At least one G40 should be after the last G01
    last_g01 = max(i for i, ln in enumerate(lns) if ln.startswith("G01"))
    assert any(i > last_g01 for i in g40_indices)


def test_left_compensation_g41():
    prog = _prog_square(side="left")
    assert any("G41" in ln for ln in _lines(prog))
    assert not any("G42" in ln for ln in _lines(prog))


def test_right_compensation_g42():
    prog = _prog_square(side="right")
    assert any("G42" in ln for ln in _lines(prog))
    assert not any("G41" in ln for ln in _lines(prog))


def test_square_four_g01_lines():
    """Square profile -> exactly 4 G01 profile moves (not counting lead-in)."""
    prog = _prog_square()
    lns = _lines(prog)
    # Find G41/G42 activation line; G01 lines AFTER that are profile lines
    activation_idx = next(
        i for i, ln in enumerate(lns) if "G41" in ln or "G42" in ln
    )
    profile_g01 = [ln for ln in lns[activation_idx + 1:] if ln.startswith("G01")]
    assert len(profile_g01) == 4


def test_square_coordinates_correct():
    """The 4 G01 moves should hit the 4 corners of a 50x50 mm square."""
    start, segs = square_profile(0, 0, 50)
    prog = emit_wire_edm_gcode(segs, start, wire_diameter_mm=0.25, spark_gap_mm=0.025)
    lns = _lines(prog)
    activation_idx = next(i for i, ln in enumerate(lns) if "G41" in ln or "G42" in ln)
    profile_g01 = [ln for ln in lns[activation_idx + 1:] if ln.startswith("G01")]

    expected_corners = [
        (25.0, -25.0),
        (25.0, 25.0),
        (-25.0, 25.0),
        (-25.0, -25.0),
    ]
    for g01_line, (ex, ey) in zip(profile_g01, expected_corners):
        m = re.search(r"X([-\d.]+)\s+Y([-\d.]+)", g01_line)
        assert m, f"No X/Y in line: {g01_line}"
        gx = float(m.group(1))
        gy = float(m.group(2))
        assert math.isclose(gx, ex, abs_tol=1e-4), f"X mismatch: {gx} vs {ex}"
        assert math.isclose(gy, ey, abs_tol=1e-4), f"Y mismatch: {gy} vs {ey}"


# ---------------------------------------------------------------------------
# emit_wire_edm_gcode — D-register / compensation radius
# ---------------------------------------------------------------------------

def test_d_register_wire_025_gap_025():
    """wire 0.25 mm, gap 0.025 mm -> D = 0.125 + 0.025 = 0.150 mm"""
    prog = _prog_square(wire=0.25, gap=0.025)
    d_val = prog.compensation_radius
    assert math.isclose(d_val, 0.150, abs_tol=1e-6)


def test_d_register_in_header_comment():
    """D-register value appears in program header as a comment."""
    prog = _prog_square(wire=0.25, gap=0.025)
    assert any("0.1500" in ln for ln in _lines(prog))


def test_d_register_wire_020():
    """wire 0.20 mm -> D = 0.10 + 0.025 = 0.125 mm"""
    start, segs = square_profile(0, 0, 50)
    prog = emit_wire_edm_gcode(segs, start, wire_diameter_mm=0.20, spark_gap_mm=0.025)
    assert math.isclose(prog.compensation_radius, 0.125, abs_tol=1e-6)


def test_d_register_custom_gap():
    """Custom spark_gap_mm correctly changes D-register."""
    start, segs = square_profile(0, 0, 50)
    prog = emit_wire_edm_gcode(segs, start, wire_diameter_mm=0.25, spark_gap_mm=0.010)
    # 0.125 + 0.010 = 0.135
    assert math.isclose(prog.compensation_radius, 0.135, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# emit_wire_edm_gcode — lead-in
# ---------------------------------------------------------------------------

def test_lead_in_before_compensation_activation():
    """G00 rapid to lead-in point appears before G41/G42 activation block."""
    prog = _prog_square()
    lns = _lines(prog)
    g00_idx = next(i for i, ln in enumerate(lns) if ln.startswith("G00"))
    # Activation line starts with G41 or G42 (not a comment)
    activation_idx = next(
        i for i, ln in enumerate(lns)
        if (ln.startswith("G41") or ln.startswith("G42"))
    )
    assert g00_idx < activation_idx


def test_lead_in_distance():
    """G00 lead-in point is ~lead_in_mm away from profile start."""
    start, segs = square_profile(0, 0, 50)
    # Default lead_in_mm=2.0; profile starts at (-25, -25)
    prog = emit_wire_edm_gcode(segs, start, lead_in_mm=3.0)
    lns = _lines(prog)
    g00_line = next(ln for ln in lns if ln.startswith("G00"))
    m = re.search(r"X([-\d.]+)\s+Y([-\d.]+)", g00_line)
    assert m
    xi, yi = float(m.group(1)), float(m.group(2))
    x0, y0 = start
    dist = math.hypot(xi - x0, yi - y0)
    assert math.isclose(dist, 3.0, abs_tol=0.01)


# ---------------------------------------------------------------------------
# emit_wire_edm_gcode — feedrate
# ---------------------------------------------------------------------------

def test_feedrate_in_profile_g01():
    start, segs = square_profile(0, 0, 50)
    prog = emit_wire_edm_gcode(segs, start, feedrate_mm_min=2.5)
    lns = _lines(prog)
    activation_idx = next(i for i, ln in enumerate(lns) if "G41" in ln or "G42" in ln)
    profile_lines = [ln for ln in lns[activation_idx + 1:] if ln.startswith("G01")]
    assert all("F2.5" in ln for ln in profile_lines)


# ---------------------------------------------------------------------------
# emit_wire_edm_gcode — circular profile
# ---------------------------------------------------------------------------

def test_circle_g03_emitted():
    start, segs = circle_profile(0, 0, 25, ccw=True)
    prog = emit_wire_edm_gcode(segs, start)
    lns = _lines(prog)
    assert any(ln.startswith("G03") for ln in lns)


def test_circle_g02_emitted():
    start, segs = circle_profile(0, 0, 25, ccw=False)
    prog = emit_wire_edm_gcode(segs, start)
    lns = _lines(prog)
    assert any(ln.startswith("G02") for ln in lns)


def test_circle_ij_values():
    """For a circle centred at origin, I/J of each half-arc should be correct."""
    start, segs = circle_profile(0, 0, 25, ccw=True)
    prog = emit_wire_edm_gcode(segs, start)
    lns = _lines(prog)
    arc_lines = [ln for ln in lns if ln.startswith("G03")]
    assert len(arc_lines) == 2

    # First arc: start=(25,0) -> centre=(0,0), I=-25, J=0
    m = re.search(r"I([-\d.]+)\s+J([-\d.]+)", arc_lines[0])
    assert m
    i0, j0 = float(m.group(1)), float(m.group(2))
    assert math.isclose(i0, -25.0, abs_tol=1e-4)
    assert math.isclose(j0, 0.0, abs_tol=1e-4)

    # Second arc: start=(-25,0) -> centre=(0,0), I=+25, J=0
    m2 = re.search(r"I([-\d.]+)\s+J([-\d.]+)", arc_lines[1])
    assert m2
    i1, j1 = float(m2.group(1)), float(m2.group(2))
    assert math.isclose(i1, 25.0, abs_tol=1e-4)
    assert math.isclose(j1, 0.0, abs_tol=1e-4)


# ---------------------------------------------------------------------------
# emit_wire_edm_gcode — complex profile with arcs
# ---------------------------------------------------------------------------

def test_complex_profile_mixed_segments():
    """Profile: line + arc_cw + arc_ccw + line — all segment types emitted."""
    segs = [
        ("line", 10.0, 0.0),
        ("arc_cw", 15.0, 5.0, 10.0, 5.0),
        ("arc_ccw", 20.0, 0.0, 15.0, 0.0),
        ("line", 0.0, 0.0),
    ]
    prog = emit_wire_edm_gcode(segs, (0.0, 0.0))
    lns = _lines(prog)
    activation_idx = next(i for i, ln in enumerate(lns) if "G41" in ln or "G42" in ln)
    profile_lns = lns[activation_idx + 1:]
    kinds = [ln[:3] for ln in profile_lns if ln[:3] in ("G01", "G02", "G03")]
    assert "G01" in kinds
    assert "G02" in kinds
    assert "G03" in kinds


# ---------------------------------------------------------------------------
# emit_wire_edm_gcode — program number
# ---------------------------------------------------------------------------

def test_program_number_emitted():
    start, segs = square_profile(0, 0, 50)
    prog = emit_wire_edm_gcode(segs, start, program_number=42)
    assert any(ln == "O0042" for ln in _lines(prog))


def test_no_program_number_no_o_word():
    start, segs = square_profile(0, 0, 50)
    prog = emit_wire_edm_gcode(segs, start)
    assert not any(ln.startswith("O") and ln[1:].isdigit() for ln in _lines(prog))


# ---------------------------------------------------------------------------
# emit_wire_edm_gcode — WireEDMProgram dataclass
# ---------------------------------------------------------------------------

def test_dataclass_segment_count():
    start, segs = square_profile(0, 0, 50)
    prog = emit_wire_edm_gcode(segs, start)
    assert prog.segment_count == 4


def test_dataclass_compensation_side():
    prog = _prog_square(side="right")
    assert prog.compensation_side == "right"


def test_dataclass_line_count_positive():
    prog = _prog_square()
    assert prog.line_count > 0


# ---------------------------------------------------------------------------
# emit_wire_edm_gcode — error cases
# ---------------------------------------------------------------------------

def test_empty_profile_raises():
    with pytest.raises(ValueError, match="at least 1 segment"):
        emit_wire_edm_gcode([], (0.0, 0.0))


def test_bad_side_raises():
    with pytest.raises(ValueError, match="side must be"):
        emit_wire_edm_gcode([("line", 10, 0)], (0, 0), side="up")


def test_wire_diameter_zero_raises():
    with pytest.raises(ValueError, match="wire_diameter_mm"):
        emit_wire_edm_gcode([("line", 10, 0)], (0, 0), wire_diameter_mm=0)


def test_spark_gap_negative_raises():
    with pytest.raises(ValueError, match="spark_gap_mm"):
        emit_wire_edm_gcode([("line", 10, 0)], (0, 0), spark_gap_mm=-0.001)


def test_feedrate_zero_raises():
    with pytest.raises(ValueError, match="feedrate_mm_min"):
        emit_wire_edm_gcode([("line", 10, 0)], (0, 0), feedrate_mm_min=0)


def test_unknown_segment_kind_raises():
    with pytest.raises(ValueError, match="unknown kind"):
        emit_wire_edm_gcode([("helix", 10, 0)], (0, 0))


# ---------------------------------------------------------------------------
# LLM tool — cam_emit_wire_edm_gcode
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.cam_wire_edm_path import run_cam_emit_wire_edm_gcode
    _HAS_TOOL = True
except ImportError:
    _HAS_TOOL = False


@pytest.mark.skipif(not _HAS_TOOL, reason="LLM tool not registered (kerf_chat not installed)")
def test_llm_tool_square_happy_path():
    """cam_emit_wire_edm_gcode LLM tool returns gcode for a square."""
    ctx = _fake_ctx()
    payload = json.dumps({
        "profile_2d": [
            ["line", 25.0, -25.0],
            ["line", 25.0, 25.0],
            ["line", -25.0, 25.0],
            ["line", -25.0, -25.0],
        ],
        "start_xy": [-25.0, -25.0],
        "wire_diameter_mm": 0.25,
        "spark_gap_mm": 0.025,
        "side": "left",
    }).encode()
    result = _run(run_cam_emit_wire_edm_gcode(ctx, payload))
    assert "error" not in result
    data = json.loads(result)
    assert "gcode" in data
    assert "G41" in data["gcode"]
    assert math.isclose(data["compensation_radius"], 0.150, abs_tol=1e-4)


@pytest.mark.skipif(not _HAS_TOOL, reason="LLM tool not registered (kerf_chat not installed)")
def test_llm_tool_missing_profile():
    ctx = _fake_ctx()
    payload = json.dumps({"start_xy": [0, 0]}).encode()
    result = _run(run_cam_emit_wire_edm_gcode(ctx, payload))
    assert "error" in result
    data = json.loads(result)
    assert "profile_2d" in data["error"].lower()


@pytest.mark.skipif(not _HAS_TOOL, reason="LLM tool not registered (kerf_chat not installed)")
def test_llm_tool_missing_start_xy():
    ctx = _fake_ctx()
    payload = json.dumps({"profile_2d": [["line", 10, 0]]}).encode()
    result = _run(run_cam_emit_wire_edm_gcode(ctx, payload))
    assert "error" in result
    data = json.loads(result)
    assert "start_xy" in data["error"].lower()


@pytest.mark.skipif(not _HAS_TOOL, reason="LLM tool not registered (kerf_chat not installed)")
def test_llm_tool_bad_json():
    ctx = _fake_ctx()
    result = _run(run_cam_emit_wire_edm_gcode(ctx, b"not json at all"))
    assert "error" in result


@pytest.mark.skipif(not _HAS_TOOL, reason="LLM tool not registered (kerf_chat not installed)")
def test_llm_tool_bad_side():
    ctx = _fake_ctx()
    payload = json.dumps({
        "profile_2d": [["line", 10, 0]],
        "start_xy": [0, 0],
        "side": "diagonal",
    }).encode()
    result = _run(run_cam_emit_wire_edm_gcode(ctx, payload))
    assert "error" in result
