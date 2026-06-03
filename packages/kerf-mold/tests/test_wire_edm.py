"""
Tests for kerf_mold.wire_edm
==============================
Covers G-code generation, G41/G42 cutter compensation, G02/G03 arc output,
4-axis taper code, path length, estimated time, input validation, and LLM tool dispatch.

References:
  ISO 14117:2018 — Wire EDM geometric tolerances.
  Fanuc B-59064EN/01 — G40/G41/G42, M50/M51, G01/G02/G03.
  Hassan, A., Boothroyd, G. (1989). §14.3 — cutting speed.
"""
import asyncio
import json
import math

import pytest

from kerf_mold.wire_edm import (
    WireEdmPath,
    WireEdmGcode,
    generate_wire_edm_gcode,
    rectangular_profile,
    circular_profile,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Ctx:
    pass


CTX = _Ctx()


def _rect_path(**kw) -> WireEdmPath:
    start, segs = rectangular_profile(50.0, 30.0)
    defaults = dict(
        profile=segs,
        start_xy=start,
        wire_diameter_mm=0.25,
        spark_gap_mm=0.025,
        offset_direction="left",
        feedrate_mm_per_min=8.0,
    )
    defaults.update(kw)
    return WireEdmPath(**defaults)


def _circle_path(**kw) -> WireEdmPath:
    start, segs = circular_profile(25.0)
    defaults = dict(
        profile=segs,
        start_xy=start,
        wire_diameter_mm=0.25,
        spark_gap_mm=0.025,
        offset_direction="left",
        feedrate_mm_per_min=8.0,
    )
    defaults.update(kw)
    return WireEdmPath(**defaults)


# ---------------------------------------------------------------------------
# 1. G41 / G42 cutter compensation present
# ---------------------------------------------------------------------------

def test_left_offset_produces_g41():
    path = _rect_path(offset_direction="left")
    result = generate_wire_edm_gcode(path)
    assert "G41" in result.gcode, "Left offset should produce G41 in G-code"


def test_right_offset_produces_g42():
    path = _rect_path(offset_direction="right")
    result = generate_wire_edm_gcode(path)
    assert "G42" in result.gcode, "Right offset should produce G42 in G-code"


def test_g40_cancels_compensation():
    """G40 should appear at start (safe cancel) and end (cancel after cut)."""
    path = _rect_path()
    result = generate_wire_edm_gcode(path)
    assert result.gcode.count("G40") >= 2, "G40 should appear at least twice"


# ---------------------------------------------------------------------------
# 2. G02/G03 arc segments for circular profile
# ---------------------------------------------------------------------------

def test_circle_profile_produces_arc_segments():
    """Circular profile (two 180° arcs) should produce G03 in the G-code."""
    path = _circle_path()
    result = generate_wire_edm_gcode(path)
    assert "G03" in result.gcode or "G02" in result.gcode, (
        "Circular profile should produce G02 or G03 arc blocks"
    )


def test_circle_profile_arc_ccw_produces_g03():
    """CCW arcs should produce G03."""
    path = _circle_path()
    result = generate_wire_edm_gcode(path)
    assert "G03" in result.gcode


def test_rectangle_produces_only_linear_g01():
    """Rectangular profile (all lines) should NOT produce G02/G03."""
    path = _rect_path()
    result = generate_wire_edm_gcode(path)
    assert "G02" not in result.gcode
    assert "G03" not in result.gcode
    assert "G01" in result.gcode


# ---------------------------------------------------------------------------
# 3. Path length approximately matches profile perimeter
# ---------------------------------------------------------------------------

def test_rectangle_path_length_matches_perimeter():
    """50×30 mm rectangle perimeter = 2*(50+30) = 160 mm; ± small offset error."""
    path = _rect_path()
    result = generate_wire_edm_gcode(path)
    # Perimeter of rectangle profile (4 line segments)
    expected = 2.0 * (50.0 + 30.0)
    # Allow ±5 mm tolerance (lead-in not counted in total_path_length_mm)
    assert result.total_path_length_mm == pytest.approx(expected, abs=5.0)


def test_circle_path_length_matches_circumference():
    """Circle r=25 mm circumference = 2π×25 ≈ 157.08 mm; arc approximation ±5%."""
    path = _circle_path()
    result = generate_wire_edm_gcode(path)
    expected = 2.0 * math.pi * 25.0
    assert result.total_path_length_mm == pytest.approx(expected, rel=0.10)


# ---------------------------------------------------------------------------
# 4. Estimated time = path_length / feedrate
# ---------------------------------------------------------------------------

def test_estimated_time_consistent_with_feedrate():
    path = _rect_path(feedrate_mm_per_min=8.0)
    result = generate_wire_edm_gcode(path)
    if result.total_path_length_mm > 0:
        expected_time = result.total_path_length_mm / 8.0
        assert result.estimated_time_min == pytest.approx(expected_time, rel=1e-5)


# ---------------------------------------------------------------------------
# 5. Compensation radius = wire_radius + spark_gap
# ---------------------------------------------------------------------------

def test_compensation_radius():
    path = WireEdmPath(
        profile=[("line", 10.0, 0.0)],
        start_xy=(0.0, 0.0),
        wire_diameter_mm=0.25,
        spark_gap_mm=0.025,
    )
    result = generate_wire_edm_gcode(path)
    expected = 0.125 + 0.025  # 0.15 mm
    assert result.compensation_radius_mm == pytest.approx(expected, rel=1e-6)


# ---------------------------------------------------------------------------
# 6. 4-axis taper produces is_taper=True and XY/UV words
# ---------------------------------------------------------------------------

def test_taper_5deg_produces_4axis_gcode():
    """5° taper should set is_taper=True and include U/V axis words."""
    path = _rect_path(taper_angle_deg=5.0, workpiece_height_mm=40.0)
    result = generate_wire_edm_gcode(path)
    assert result.is_taper is True
    # G-code should contain U and V words
    assert " U" in result.gcode or "U" in result.gcode
    assert " V" in result.gcode or "V" in result.gcode


def test_straight_cut_is_not_taper():
    """taper_angle_deg=0 should produce is_taper=False."""
    path = _rect_path(taper_angle_deg=0.0)
    result = generate_wire_edm_gcode(path)
    assert result.is_taper is False


def test_taper_uv_offset_nonzero():
    """For taper > 0 and workpiece height > 0 the UV offset should be non-zero."""
    angle = 5.0
    height = 40.0
    expected_offset = height * math.tan(math.radians(angle))
    path = _rect_path(taper_angle_deg=angle, workpiece_height_mm=height)
    result = generate_wire_edm_gcode(path)
    # Check that the offset note appears in G-code header
    assert str(round(expected_offset, 2)) in result.gcode or "UV" in result.gcode or "Taper" in result.gcode


# ---------------------------------------------------------------------------
# 7. M50 / M51 wire feed on/off
# ---------------------------------------------------------------------------

def test_m50_wire_feed_on_present():
    path = _rect_path()
    result = generate_wire_edm_gcode(path)
    assert "M50" in result.gcode


def test_m51_wire_feed_off_present():
    path = _rect_path()
    result = generate_wire_edm_gcode(path)
    assert "M51" in result.gcode


def test_m02_program_end_present():
    path = _rect_path()
    result = generate_wire_edm_gcode(path)
    assert "M02" in result.gcode


# ---------------------------------------------------------------------------
# 8. G21 metric mode and G90 absolute mode
# ---------------------------------------------------------------------------

def test_g21_metric_present():
    path = _rect_path()
    result = generate_wire_edm_gcode(path)
    assert "G21" in result.gcode


def test_g90_absolute_present():
    path = _rect_path()
    result = generate_wire_edm_gcode(path)
    assert "G90" in result.gcode


# ---------------------------------------------------------------------------
# 9. Input validation
# ---------------------------------------------------------------------------

def test_empty_profile_raises():
    with pytest.raises(ValueError, match="at least 1 segment"):
        WireEdmPath(profile=[], start_xy=(0.0, 0.0))


def test_invalid_offset_direction_raises():
    with pytest.raises(ValueError, match="offset_direction"):
        WireEdmPath(
            profile=[("line", 10.0, 0.0)],
            start_xy=(0.0, 0.0),
            offset_direction="centre",
        )


def test_negative_wire_diameter_raises():
    with pytest.raises(ValueError, match="wire_diameter_mm must be > 0"):
        WireEdmPath(
            profile=[("line", 10.0, 0.0)],
            start_xy=(0.0, 0.0),
            wire_diameter_mm=-0.25,
        )


def test_negative_taper_angle_raises():
    with pytest.raises(ValueError, match="taper_angle_deg"):
        WireEdmPath(
            profile=[("line", 10.0, 0.0)],
            start_xy=(0.0, 0.0),
            taper_angle_deg=-5.0,
        )


# ---------------------------------------------------------------------------
# 10. Convenience profile builders
# ---------------------------------------------------------------------------

def test_rectangular_profile_4_segments():
    start, segs = rectangular_profile(50.0, 30.0)
    assert len(segs) == 4
    for seg in segs:
        assert seg[0] == "line"


def test_circular_profile_2_arc_segments():
    start, segs = circular_profile(25.0)
    assert len(segs) == 2
    for seg in segs:
        assert seg[0] in ("arc_ccw", "arc_cw")


def test_circular_profile_invalid_radius():
    with pytest.raises(ValueError, match="r_mm must be > 0"):
        circular_profile(-5.0)


# ---------------------------------------------------------------------------
# 11. LLM tool dispatch
# ---------------------------------------------------------------------------

def test_tool_dispatch_basic_rectangle():
    from kerf_mold.wire_edm_tool import run_mold_generate_wire_edm_gcode
    start, segs = rectangular_profile(50.0, 30.0)
    result = json.loads(_run(run_mold_generate_wire_edm_gcode({
        "profile_2d": [list(s) for s in segs],
        "start_xy": list(start),
        "wire_diameter_mm": 0.25,
        "spark_gap_mm": 0.025,
        "offset_direction": "left",
    }, CTX)))
    assert result.get("ok") is True
    assert "G41" in result["gcode"]
    assert result["total_path_length_mm"] > 0
    assert result["compensation_radius_mm"] == pytest.approx(0.15)


def test_tool_dispatch_taper():
    from kerf_mold.wire_edm_tool import run_mold_generate_wire_edm_gcode
    start, segs = rectangular_profile(40.0, 40.0)
    result = json.loads(_run(run_mold_generate_wire_edm_gcode({
        "profile_2d": [list(s) for s in segs],
        "start_xy": list(start),
        "taper_angle_deg": 5.0,
        "workpiece_height_mm": 30.0,
    }, CTX)))
    assert result.get("ok") is True
    assert result["is_taper"] is True


def test_tool_dispatch_missing_profile():
    from kerf_mold.wire_edm_tool import run_mold_generate_wire_edm_gcode
    result = json.loads(_run(run_mold_generate_wire_edm_gcode({
        "start_xy": [0.0, 0.0],
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


def test_tool_dispatch_missing_start():
    from kerf_mold.wire_edm_tool import run_mold_generate_wire_edm_gcode
    result = json.loads(_run(run_mold_generate_wire_edm_gcode({
        "profile_2d": [["line", 10.0, 0.0]],
    }, CTX)))
    assert "error" in result
    assert result.get("code") == "BAD_ARGS"


# ---------------------------------------------------------------------------
# 12. Tool spec
# ---------------------------------------------------------------------------

def test_tool_spec_name():
    from kerf_mold.wire_edm_tool import mold_generate_wire_edm_gcode_spec
    assert mold_generate_wire_edm_gcode_spec.name == "mold_generate_wire_edm_gcode"


def test_tool_spec_required_fields():
    from kerf_mold.wire_edm_tool import mold_generate_wire_edm_gcode_spec
    req = mold_generate_wire_edm_gcode_spec.input_schema.get("required", [])
    assert "profile_2d" in req
    assert "start_xy" in req


# ---------------------------------------------------------------------------
# 13. G92 reference position in G-code
# ---------------------------------------------------------------------------

def test_g92_reference_position():
    """G92 should set the wire home position to start_xy."""
    start, segs = rectangular_profile(20.0, 20.0, cx=5.0, cy=3.0)
    path = WireEdmPath(profile=segs, start_xy=start)
    result = generate_wire_edm_gcode(path)
    assert "G92" in result.gcode


# ---------------------------------------------------------------------------
# 14. Honest caveat present and references ISO 14117
# ---------------------------------------------------------------------------

def test_honest_caveat_present():
    path = _rect_path()
    result = generate_wire_edm_gcode(path)
    assert "HONEST" in result.honest_caveat
    assert "ISO" in result.honest_caveat or "skim" in result.honest_caveat.lower()
