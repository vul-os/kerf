"""
Tests for 5-axis G-code emission — T5.

Tests use synthetic CL points (no OCC / opencamlib required).
All tests run without any optional dependencies.
"""

from __future__ import annotations

import math
import pytest

from kerf_cam.five_axis.gcode_constant_tilt import (
    emit_gcode_constant_tilt,
    PostOpts,
    _axis_to_ab,
    _unwrap_angle,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cl(x: float, y: float, z: float, i: float, j: float, k: float) -> dict:
    return {"x": x, "y": y, "z": z, "i": i, "j": j, "k": k}


def _upright() -> dict:
    """Tool pointing straight up (+Z): B=0, A=undefined/0."""
    return _make_cl(0.0, 0.0, 0.0, 0.0, 0.0, 1.0)


def _tilt_x(tilt_deg: float) -> dict:
    """Tool tilted by tilt_deg in the +X direction."""
    r = math.radians(tilt_deg)
    return _make_cl(0.0, 0.0, 0.0, math.sin(r), 0.0, math.cos(r))


def _tilt_y(tilt_deg: float) -> dict:
    """Tool tilted by tilt_deg in the +Y direction."""
    r = math.radians(tilt_deg)
    return _make_cl(0.0, 0.0, 0.0, 0.0, math.sin(r), math.cos(r))


def _row(n: int = 3, tilt_deg: float = 15.0) -> list[dict]:
    """A row of n CL points with constant tilt, linear X traverse."""
    r = math.radians(tilt_deg)
    pts = []
    for idx in range(n):
        pts.append({
            "x": float(idx) * 5.0,
            "y": 0.0,
            "z": 0.0,
            "i": math.sin(r),
            "j": 0.0,
            "k": math.cos(r),
        })
    return pts


# ---------------------------------------------------------------------------
# 1. Angle math unit tests
# ---------------------------------------------------------------------------

def test_axis_to_ab_upright():
    """Upright tool (0,0,1) → B=0, A=0."""
    a, b = _axis_to_ab(0.0, 0.0, 1.0)
    assert abs(b) < 1e-9
    assert abs(a) < 1e-9


def test_axis_to_ab_tilt_15_x():
    """Tool tilted 15° in +X direction: B=15°, A=0°."""
    r = math.radians(15.0)
    a, b = _axis_to_ab(math.sin(r), 0.0, math.cos(r))
    assert abs(b - 15.0) < 1e-6
    assert abs(a) < 1e-6


def test_axis_to_ab_tilt_15_y():
    """Tool tilted 15° in +Y direction: B=15°, A=90°."""
    r = math.radians(15.0)
    a, b = _axis_to_ab(0.0, math.sin(r), math.cos(r))
    assert abs(b - 15.0) < 1e-6
    assert abs(a - 90.0) < 1e-6


def test_unwrap_no_jump():
    """Small angle change — unwrap is identity."""
    assert abs(_unwrap_angle(10.0, 15.0) - 15.0) < 1e-9


def test_unwrap_avoids_positive_360_jump():
    """179° → -179° wrap: should produce 181°, not -179°."""
    result = _unwrap_angle(179.0, -179.0)
    assert abs(result - 181.0) < 1e-9


def test_unwrap_avoids_negative_360_jump():
    """-179° → 179° wrap: should produce -181°, not 179°."""
    result = _unwrap_angle(-179.0, 179.0)
    assert abs(result - (-181.0)) < 1e-9


# ---------------------------------------------------------------------------
# 2. Header / footer presence
# ---------------------------------------------------------------------------

def test_linuxcnc_header_present():
    pts = _row(3, 15.0)
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc")
    assert "%" in gcode                    # tape markers
    assert "G90" in gcode
    assert "G21" in gcode
    assert "M6" in gcode
    assert "M3" in gcode


def test_linuxcnc_footer_present():
    pts = _row(3, 15.0)
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc")
    assert "M30" in gcode
    assert "M5" in gcode
    assert "M9" in gcode


def test_fanuc_header_present():
    pts = _row(3, 15.0)
    gcode = emit_gcode_constant_tilt(pts, "fanuc")
    assert "G90" in gcode
    assert "G21" in gcode
    assert "M6" in gcode
    assert "M3" in gcode
    assert "M30" in gcode


def test_fanuc_n_numbers_present():
    pts = _row(3, 15.0)
    gcode = emit_gcode_constant_tilt(pts, "fanuc")
    assert "N10 " in gcode


def test_fanuc_no_n_numbers():
    pts = _row(3, 15.0)
    opts = PostOpts(no_n_numbers=True)
    gcode = emit_gcode_constant_tilt(pts, "fanuc", opts)
    assert "N10 " not in gcode
    assert "G90" in gcode


# ---------------------------------------------------------------------------
# 3. A/B angles in output
# ---------------------------------------------------------------------------

def test_linuxcnc_ab_angles_present():
    pts = _row(3, 15.0)
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc")
    assert " A" in gcode
    assert " B" in gcode


def test_fanuc_ab_angles_present():
    pts = _row(3, 15.0)
    gcode = emit_gcode_constant_tilt(pts, "fanuc")
    assert " A" in gcode
    assert " B" in gcode


def test_b_angle_value_linuxcnc():
    """B angle for 15° tilt in +X should be ~15.000 in G-code."""
    pts = [_tilt_x(15.0)]
    opts = PostOpts(feed_cut_mm_min=1000.0)
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc", opts)
    # Find the G1 line and extract B value.
    for line in gcode.splitlines():
        if line.startswith("G1 ") and " B" in line:
            parts = line.split()
            b_part = next(p for p in parts if p.startswith("B"))
            b_val = float(b_part[1:])
            assert abs(b_val - 15.0) < 0.01
            break
    else:
        pytest.fail("No G1 line with B found in output")


def test_a_angle_value_tilt_y():
    """A angle for 15° tilt in +Y should be ~90.000 in G-code."""
    pts = [_tilt_y(15.0)]
    opts = PostOpts(feed_cut_mm_min=1000.0)
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc", opts)
    for line in gcode.splitlines():
        if line.startswith("G1 ") and " A" in line:
            parts = line.split()
            a_part = next(p for p in parts if p.startswith("A"))
            a_val = float(a_part[1:])
            assert abs(a_val - 90.0) < 0.01
            break
    else:
        pytest.fail("No G1 line with A found in output")


# ---------------------------------------------------------------------------
# 4. Continuous-angle unwrap — no discontinuity
# ---------------------------------------------------------------------------

def test_no_angle_wrap_discontinuity():
    """A angles must not jump by more than 180° between adjacent points."""
    # Build a sequence of CL points where the azimuth goes from +170° to -170°
    # (a 340° sweep that, without unwrap, would have a 340° jump at the midpoint).
    angles_deg = list(range(-170, 171, 10))  # -170 to +170 in 10° steps
    pts = []
    tilt_r = math.radians(15.0)
    for az in angles_deg:
        az_r = math.radians(az)
        pts.append({
            "x": 0.0, "y": 0.0, "z": 0.0,
            "i": math.sin(tilt_r) * math.cos(az_r),
            "j": math.sin(tilt_r) * math.sin(az_r),
            "k": math.cos(tilt_r),
        })
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc")
    # Extract A values from G1 lines.
    a_vals = []
    for line in gcode.splitlines():
        if line.startswith("G1 ") and " A" in line:
            parts = line.split()
            a_part = next((p for p in parts if p.startswith("A")), None)
            if a_part:
                a_vals.append(float(a_part[1:]))
    # Check no consecutive jump > 180°.
    for prev_a, curr_a in zip(a_vals, a_vals[1:]):
        delta = abs(curr_a - prev_a)
        assert delta <= 180.0 + 1e-6, (
            f"A angle discontinuity of {delta:.1f}° detected: {prev_a:.1f}° → {curr_a:.1f}°"
        )


# ---------------------------------------------------------------------------
# 5. Feed-rate handling
# ---------------------------------------------------------------------------

def test_feed_rate_in_first_cut_move():
    pts = _row(3, 15.0)
    opts = PostOpts(feed_cut_mm_min=800.0)
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc", opts)
    # First G1 move should carry F800.
    for line in gcode.splitlines():
        if line.startswith("G1 "):
            assert "F800" in line
            break
    else:
        pytest.fail("No G1 line found")


def test_per_point_feed_override():
    """If a CL point carries a 'feed' key, it should override the default."""
    pts = [
        {**_tilt_x(15.0), "x": 0.0, "feed": 500.0},
        {**_tilt_x(15.0), "x": 5.0},
    ]
    opts = PostOpts(feed_cut_mm_min=1000.0)
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc", opts)
    lines = [l for l in gcode.splitlines() if l.startswith("G1 ")]
    # First G1 should carry F500.
    assert "F500" in lines[0]
    # Second G1 should carry F1000 (changed from 500).
    assert "F1000" in lines[1]


# ---------------------------------------------------------------------------
# 6. Edge case: zero-tilt (upright tool)
# ---------------------------------------------------------------------------

def test_zero_tilt_b_zero():
    """All upright CL points: B should be 0 in G-code."""
    pts = [_upright() for _ in range(3)]
    for p in pts:
        p["x"] = pts.index(p) * 5.0
    opts = PostOpts(feed_cut_mm_min=1000.0)
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc", opts)
    for line in gcode.splitlines():
        if line.startswith("G1 ") and " B" in line:
            parts = line.split()
            b_part = next(p for p in parts if p.startswith("B"))
            b_val = float(b_part[1:])
            assert abs(b_val) < 1e-6, f"B should be 0 for upright tool, got {b_val}"


def test_zero_tilt_a_held_at_zero():
    """All upright CL points: A should be held at 0 (singularity handling)."""
    pts = [_upright() for _ in range(3)]
    opts = PostOpts(feed_cut_mm_min=1000.0)
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc", opts)
    for line in gcode.splitlines():
        if line.startswith("G1 ") and " A" in line:
            parts = line.split()
            a_part = next(p for p in parts if p.startswith("A"))
            a_val = float(a_part[1:])
            assert abs(a_val) < 1e-6, f"A should be held at 0 for upright tool, got {a_val}"


def test_singularity_warning_emitted():
    """Upright CL points should trigger the singularity warning comment."""
    pts = [_upright()]
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc")
    assert "singularity" in gcode.lower() or "near-singularity" in gcode.lower()


# ---------------------------------------------------------------------------
# 7. TCP mode
# ---------------------------------------------------------------------------

def test_linuxcnc_tcp_mode_emits_g43_4():
    pts = _row(3, 15.0)
    opts = PostOpts(use_tcp=True)
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc", opts)
    assert "G43.4" in gcode


def test_fanuc_tcp_mode_emits_g43_4_and_aicc():
    pts = _row(3, 15.0)
    opts = PostOpts(use_tcp=True)
    gcode = emit_gcode_constant_tilt(pts, "fanuc", opts)
    assert "G43.4" in gcode
    assert "G05.1 Q1" in gcode    # AICC on
    assert "G05.1 Q0" in gcode    # AICC off in footer


def test_linuxcnc_no_tcp_g43_4_commented():
    pts = _row(3, 15.0)
    opts = PostOpts(use_tcp=False)
    gcode = emit_gcode_constant_tilt(pts, "linuxcnc", opts)
    # G43.4 should appear only as a comment (not as an active code word).
    active_lines = [l for l in gcode.splitlines()
                    if "G43.4" in l and not l.lstrip().startswith(";")]
    assert len(active_lines) == 0


# ---------------------------------------------------------------------------
# 8. Unknown post raises ValueError
# ---------------------------------------------------------------------------

def test_unknown_post_raises():
    with pytest.raises(ValueError, match="Unknown post-processor"):
        emit_gcode_constant_tilt([_tilt_x(15.0)], "mach3_5x")


# ---------------------------------------------------------------------------
# 9. Unsupported kinematic raises NotImplementedError
# ---------------------------------------------------------------------------

def test_unsupported_kinematic_raises():
    # table_table and head_head are now supported; use a truly unknown kinematic
    opts = PostOpts(machine_kinematic="parallel_arms")
    with pytest.raises(NotImplementedError):
        emit_gcode_constant_tilt([_tilt_x(15.0)], "linuxcnc", opts)


# ---------------------------------------------------------------------------
# 10. Empty CL points — both posts handle gracefully
# ---------------------------------------------------------------------------

def test_empty_cl_points_linuxcnc():
    gcode = emit_gcode_constant_tilt([], "linuxcnc")
    assert "M30" in gcode
    # No cutting moves — no line that starts with G1 (G17/G94 don't start a line with G1)
    assert not any(line.startswith("G1 ") for line in gcode.splitlines())


def test_empty_cl_points_fanuc():
    gcode = emit_gcode_constant_tilt([], "fanuc")
    assert "M30" in gcode
    # No cutting moves — no line that contains standalone G1 word
    cut_lines = [l for l in gcode.splitlines() if "G1 " in l or l.endswith("G1")]
    assert len(cut_lines) == 0
