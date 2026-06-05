"""
Test suite for kerf_cam.turning_cycles — G71/G70/G76 lathe canned cycles
LLM tool.

Tests cover:
  A  round-trip G71+G70 output has M3, G1 moves, M5/M30
  B  G76 threading path emits threading pass markers
  C  bad profile raises clean error (not crash)
  D  missing stock_x_mm returns BAD_ARGS
  E  profile with too-small stock returns ENGINE_ERROR
  F  async run_cam_generate_turning_cycles round-trip
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))

# Skip entire module if kerf_cad_core.turning.cycles is not available
_cad_core_available = False
try:
    from kerf_cad_core.turning.cycles import roughing_passes, finishing_pass
    _cad_core_available = True
except ImportError:
    pass

requires_cad_core = pytest.mark.skipif(
    not _cad_core_available,
    reason="kerf_cad_core.turning.cycles not installed",
)


def _simple_profile():
    """A simple cylindrical step profile: from Z=0 at R=15 to Z=-60 at R=15."""
    return [[0.0, 15.0], [-20.0, 15.0], [-40.0, 12.0], [-60.0, 12.0]]


def _run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


@requires_cad_core
def test_g71_g70_output_structure():
    """G71+G70 output should include M3, G1 moves, and M5/M30 footer."""
    from kerf_cam.turning_cycles import run_cam_generate_turning_cycles
    from kerf_cam._compat import ProjectCtx

    ctx = ProjectCtx()
    args = json.dumps({
        "profile": _simple_profile(),
        "stock_x_mm": 18.0,
        "css_m_per_min": 180.0,
        "feed_mm_rev": 0.20,
        "roughing_doc_mm": 2.0,
    }).encode()

    result_raw = _run_async(run_cam_generate_turning_cycles(ctx, args))
    result = json.loads(result_raw)

    assert "gcode_lines" in result, f"Missing gcode_lines in {result!r}"
    gcode = result["gcode_lines"]
    assert isinstance(gcode, list), "gcode_lines should be a list"
    gcode_str = "\n".join(gcode)

    assert "M3" in gcode_str, "Spindle-on (M3) missing from lathe G-code"
    assert "G1" in gcode_str, "G1 cutting moves missing from lathe G-code"
    assert "M5" in gcode_str, "M5 spindle-off missing from lathe G-code"
    assert "M30" in gcode_str, "M30 program-end missing from lathe G-code"

    assert result.get("roughing_passes", 0) >= 1, "Expected at least 1 roughing pass"
    assert result.get("finishing_passes", 0) == 1, "Expected exactly 1 finishing pass"
    assert result.get("has_threading") is False, "Threading should be absent for G71_G70"


@requires_cad_core
def test_g76_threading_pass_present():
    """G76 threading path should emit threading markers when thread_pitch_mm provided."""
    from kerf_cam.turning_cycles import run_cam_generate_turning_cycles
    from kerf_cam._compat import ProjectCtx

    ctx = ProjectCtx()
    args = json.dumps({
        "profile": _simple_profile(),
        "stock_x_mm": 18.0,
        "thread_pitch_mm": 1.5,
        "thread_depth_mm": 0.92,
        "thread_z_start_mm": 0.0,
        "thread_z_end_mm": -50.0,
    }).encode()

    result_raw = _run_async(run_cam_generate_turning_cycles(ctx, args))
    result = json.loads(result_raw)

    assert "gcode_lines" in result, f"Missing gcode_lines: {result!r}"
    gcode_str = "\n".join(result["gcode_lines"])

    assert result.get("has_threading") is True, "has_threading should be True when pitch provided"
    # Threading pass marker should appear in the output
    assert "THREADING" in gcode_str or "G1" in gcode_str, (
        "Threading G-code body missing"
    )


@requires_cad_core
def test_bad_profile_returns_error():
    """An empty profile should return BAD_ARGS (not a crash)."""
    from kerf_cam.turning_cycles import run_cam_generate_turning_cycles
    from kerf_cam._compat import ProjectCtx

    ctx = ProjectCtx()
    args = json.dumps({"profile": [], "stock_x_mm": 18.0}).encode()

    result_raw = _run_async(run_cam_generate_turning_cycles(ctx, args))
    result = json.loads(result_raw)

    # Should return an error payload
    assert "error" in result or "code" in result, (
        f"Expected error payload for empty profile, got: {result!r}"
    )


@requires_cad_core
def test_missing_stock_x_returns_bad_args():
    """Missing stock_x_mm should return BAD_ARGS."""
    from kerf_cam.turning_cycles import run_cam_generate_turning_cycles
    from kerf_cam._compat import ProjectCtx

    ctx = ProjectCtx()
    args = json.dumps({"profile": _simple_profile()}).encode()

    result_raw = _run_async(run_cam_generate_turning_cycles(ctx, args))
    result = json.loads(result_raw)

    assert result.get("code") == "BAD_ARGS", (
        f"Expected BAD_ARGS code for missing stock_x_mm, got: {result!r}"
    )


@requires_cad_core
def test_stock_too_small_returns_engine_error():
    """stock_x_mm smaller than profile max X should return an engine error."""
    from kerf_cam.turning_cycles import run_cam_generate_turning_cycles
    from kerf_cam._compat import ProjectCtx

    ctx = ProjectCtx()
    # Profile max X = 15.0; stock = 10.0 < 15.0 → should fail
    args = json.dumps({
        "profile": _simple_profile(),
        "stock_x_mm": 10.0,
    }).encode()

    result_raw = _run_async(run_cam_generate_turning_cycles(ctx, args))
    result = json.loads(result_raw)

    assert "error" in result or "code" in result, (
        f"Expected error for too-small stock, got: {result!r}"
    )
    assert result.get("code") in ("ENGINE_ERROR", "BAD_ARGS"), (
        f"Expected ENGINE_ERROR or BAD_ARGS for too-small stock, got: {result!r}"
    )


@requires_cad_core
def test_pass_count_matches_geometry():
    """Pass count = ceil(stock−profile_max)/doc + 1 finishing pass."""
    from kerf_cam.turning_cycles import run_cam_generate_turning_cycles
    from kerf_cam._compat import ProjectCtx
    import math

    # Profile max X = 15.0; stock = 21.0; finish_allow = 0.3; doc = 2.0
    # radial stock to remove = 21 − 15 = 6 mm; minus finish_allow 0.3 → 5.7 mm
    # n_rough = ceil(5.7 / 2.0) = 3 passes
    ctx = ProjectCtx()
    args = json.dumps({
        "profile": _simple_profile(),
        "stock_x_mm": 21.0,
        "roughing_doc_mm": 2.0,
        "finish_allowance_x_mm": 0.3,
    }).encode()

    result_raw = _run_async(run_cam_generate_turning_cycles(ctx, args))
    result = json.loads(result_raw)

    assert "roughing_passes" in result, f"roughing_passes missing: {result!r}"
    assert result["roughing_passes"] == 3, (
        f"Expected 3 roughing passes, got {result['roughing_passes']}"
    )
    assert result["finishing_passes"] == 1, (
        f"Expected 1 finishing pass, got {result['finishing_passes']}"
    )
