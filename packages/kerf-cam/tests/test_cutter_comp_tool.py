"""
Test suite for kerf_cam.cutter_comp — G41/G42 cutter-radius compensation.

Tests cover:
  A  G41 output: compensation activation + G40 cancel present
  B  G42 output: correct comp direction
  C  Software offset path has correct length and direction
  D  Missing path_xy returns BAD_ARGS
  E  Missing tool_radius_mm returns BAD_ARGS
  F  Zero-length path returns error
  G  Fanuc dialect produces N-line numbers
  H  LinuxCNC dialect produces % tape markers
  I  include_software_offset=True populates software_offset_path key
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import sys

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))


def _run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _square_path():
    """10mm square (CCW)."""
    return [[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0], [0.0, 0.0]]


def _call_tool(path_xy, tool_radius_mm, comp_side, **kwargs):
    from kerf_cam.cutter_comp import run_cam_apply_cutter_comp
    from kerf_cam._compat import ProjectCtx
    ctx = ProjectCtx()
    a = {
        "path_xy": path_xy,
        "tool_radius_mm": tool_radius_mm,
        "comp_side": comp_side,
        **kwargs,
    }
    raw = _run_async(run_cam_apply_cutter_comp(ctx, json.dumps(a).encode()))
    return json.loads(raw)


def test_g41_activation_and_cancel():
    """G41 output must include G41 activation and G40 cancel."""
    result = _call_tool(_square_path(), 1.5, "G41")
    assert "gcode_lines" in result, f"Missing gcode_lines: {result!r}"
    gcode = "\n".join(result["gcode_lines"])
    assert "G41" in gcode, "G41 cutter-comp activation missing"
    assert "G40" in gcode, "G40 cutter-comp cancel missing"
    assert "G1" in gcode, "G1 cutting moves missing"
    assert "M30" in gcode, "M30 end-of-program missing"


def test_g42_activation_and_cancel():
    """G42 output must include G42 activation and G40 cancel."""
    result = _call_tool(_square_path(), 1.5, "G42")
    gcode = "\n".join(result["gcode_lines"])
    assert "G42" in gcode, "G42 cutter-comp activation missing"
    assert "G40" in gcode, "G40 cutter-comp cancel missing"


def test_missing_path_xy_returns_bad_args():
    """Missing path_xy should return BAD_ARGS."""
    from kerf_cam.cutter_comp import run_cam_apply_cutter_comp
    from kerf_cam._compat import ProjectCtx
    ctx = ProjectCtx()
    raw = _run_async(run_cam_apply_cutter_comp(ctx, json.dumps({
        "tool_radius_mm": 1.5,
        "comp_side": "G41",
    }).encode()))
    result = json.loads(raw)
    assert result.get("code") == "BAD_ARGS", f"Expected BAD_ARGS, got: {result!r}"


def test_missing_tool_radius_returns_bad_args():
    """Missing tool_radius_mm should return BAD_ARGS."""
    from kerf_cam.cutter_comp import run_cam_apply_cutter_comp
    from kerf_cam._compat import ProjectCtx
    ctx = ProjectCtx()
    raw = _run_async(run_cam_apply_cutter_comp(ctx, json.dumps({
        "path_xy": _square_path(),
        "comp_side": "G41",
    }).encode()))
    result = json.loads(raw)
    assert result.get("code") == "BAD_ARGS", f"Expected BAD_ARGS, got: {result!r}"


def test_too_short_path_returns_error():
    """Single-point path should return an error."""
    result = _call_tool([[0.0, 0.0]], 1.5, "G41")
    assert "error" in result or result.get("code") == "BAD_ARGS", (
        f"Expected error for single-point path: {result!r}"
    )


def test_fanuc_dialect_has_n_numbers():
    """Fanuc dialect should emit N-line numbers."""
    result = _call_tool(_square_path(), 1.5, "G41", dialect="fanuc")
    gcode = "\n".join(result["gcode_lines"])
    assert "N10 " in gcode, f"Fanuc N10 line-number missing:\n{gcode}"
    assert "N20 " in gcode, f"Fanuc N20 line-number missing:\n{gcode}"


def test_linuxcnc_dialect_has_tape_markers():
    """LinuxCNC dialect should emit % tape markers."""
    result = _call_tool(_square_path(), 1.5, "G41", dialect="linuxcnc")
    gcode_lines = result["gcode_lines"]
    assert gcode_lines[0] == "%", "LinuxCNC tape-start '%' missing"
    assert gcode_lines[-1] == "%", "LinuxCNC tape-end '%' missing"


def test_software_offset_path_present_when_requested():
    """When include_software_offset=True, software_offset_path should be returned."""
    result = _call_tool(
        _square_path(), 2.0, "G41",
        include_software_offset=True,
    )
    assert "software_offset_path" in result, (
        f"software_offset_path missing when requested: {result!r}"
    )
    offset = result["software_offset_path"]
    assert isinstance(offset, list), "software_offset_path should be a list"
    assert len(offset) == len(_square_path()), (
        f"Offset path length {len(offset)} != input length {len(_square_path())}"
    )
    # Check that the first point is actually offset (not the same as input)
    inp = _square_path()[0]
    out = offset[0]
    dist = math.sqrt((out[0] - inp[0]) ** 2 + (out[1] - inp[1]) ** 2)
    assert dist > 0.1, (
        f"Software offset first point {out} should differ from input {inp} by ~tool_radius"
    )


def test_offset_path_not_present_when_not_requested():
    """By default, software_offset_path should NOT be in the result."""
    result = _call_tool(_square_path(), 2.0, "G41")
    assert "software_offset_path" not in result, (
        "software_offset_path should not be returned unless requested"
    )


def test_g41_offset_is_left_of_path():
    """G41 (left comp) offset should be to the LEFT of the travel direction.

    For a path travelling in +X direction (from [0,0] to [10,0]), the left
    side is +Y.  The first offset point should have y > 0 when R > 0.
    """
    path = [[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]]
    result = _call_tool(path, 2.0, "G41", include_software_offset=True)
    offset = result["software_offset_path"]
    # First interior point: travelling in +X, left = +Y
    assert offset[0][1] > 0, (
        f"G41 left offset: expected y > 0 for +X travel, got y={offset[0][1]}"
    )


def test_g42_offset_is_right_of_path():
    """G42 (right comp) offset should be to the RIGHT of the travel direction.

    For a path travelling in +X direction (from [0,0] to [10,0]), the right
    side is -Y.  The first offset point should have y < 0 when R > 0.
    """
    path = [[0.0, 0.0], [10.0, 0.0], [20.0, 0.0]]
    result = _call_tool(path, 2.0, "G42", include_software_offset=True)
    offset = result["software_offset_path"]
    assert offset[0][1] < 0, (
        f"G42 right offset: expected y < 0 for +X travel, got y={offset[0][1]}"
    )
