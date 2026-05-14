"""
Tests for 5-axis G-code emission — T6: 3+2 indexed mode.

All tests are no-dep (no opencamlib / pythonOCC required) and run on every CI
run.  The tests validate:

  1. ONE rotation move at the top (A/B), never in body G1 lines.
  2. Body G1 lines carry X/Y/Z only (no A/B words).
  3. Footer: retract to Z50, G0 A0 B0 home, M30.
  4. Both LinuxCNC and Fanuc post-processors.
  5. Tool-comment line correct (from T7's Tool.to_comment()).
  6. Axis-aligned (A=B=0) detection — no rotation move emitted.
  7. Per-point feed override.
  8. Empty CL points: graceful short-circuit.
  9. Unknown post raises ValueError.
 10. TCP mode inserts G43.4 / G05.1.
"""

from __future__ import annotations

import math
import re
import pytest

from kerf_cam.five_axis.gcode_indexed_3_2 import (
    emit_gcode_indexed_3_2,
    _orientation_from_cl_points,
    _is_axis_aligned,
)
from kerf_cam.five_axis.gcode_constant_tilt import PostOpts
from kerf_cam.tool_db import parse_tool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_cl(
    x: float, y: float, z: float,
    i: float = 0.0, j: float = 0.0, k: float = 1.0,
    feed: float | None = None,
) -> dict:
    """Build a CL point dict with optional i/j/k and per-point feed."""
    pt: dict = {"x": x, "y": y, "z": z, "i": i, "j": j, "k": k}
    if feed is not None:
        pt["feed"] = feed
    return pt


def _row_xy(
    n: int = 5,
    a_deg: float = 30.0,
    b_deg: float = 45.0,
    z: float = 0.5,
) -> list[dict]:
    """Return n CL points with constant A=a_deg, B=b_deg, varying X."""
    # Convert (A, B) back to a tool-axis vector (i, j, k).
    # B is the polar angle off +Z: k = cos(B), sin(B) = sqrt(i^2+j^2)
    # A is the azimuth:            i = sin(B)*cos(A), j = sin(B)*sin(A)
    b_rad = math.radians(b_deg)
    a_rad = math.radians(a_deg)
    i = math.sin(b_rad) * math.cos(a_rad)
    j = math.sin(b_rad) * math.sin(a_rad)
    k = math.cos(b_rad)
    pts = []
    for idx in range(n):
        pts.append(_make_cl(float(idx) * 2.0, 0.0, z, i, j, k))
    return pts


def _row_upright(n: int = 5) -> list[dict]:
    """Return n upright (axis-aligned) CL points, tool along +Z."""
    return [_make_cl(float(idx) * 2.0, 0.0, 0.5) for idx in range(n)]


def _g1_lines(gcode: str) -> list[str]:
    """Return all G1 lines from the G-code."""
    return [ln.strip() for ln in gcode.splitlines() if re.match(r"(?:N\d+ )?G1 ", ln.strip())]


def _g0_lines(gcode: str) -> list[str]:
    """Return all G0 lines from the G-code."""
    return [ln.strip() for ln in gcode.splitlines() if re.match(r"(?:N\d+ )?G0 ", ln.strip())]


def _has_ab(line: str) -> bool:
    """Return True if the line contains A<number> or B<number> words."""
    return bool(re.search(r"\bA[-\d.]", line) or re.search(r"\bB[-\d.]", line))


# ---------------------------------------------------------------------------
# 1. Single rotation move at top; body G1 lines are pure X/Y/Z
# ---------------------------------------------------------------------------

def _nonzero_ab_g0_lines(gcode: str) -> list[str]:
    """Return G0 lines that have non-zero A or B values (the indexed orientation move).

    This excludes the header ``G0 Z50.000 A0.000 B0.000`` reset and the footer
    ``G0 A0.000 B0.000`` home-return, both of which have A=0 B=0.
    """
    result = []
    for ln in gcode.splitlines():
        stripped = ln.strip()
        if not re.search(r"\bG0\b", stripped):
            continue
        if not _has_ab(stripped):
            continue
        # Look for any A or B value that is not 0.000
        a_match = re.search(r"A([-\d.]+)", stripped)
        b_match = re.search(r"B([-\d.]+)", stripped)
        a_val = float(a_match.group(1)) if a_match else 0.0
        b_val = float(b_match.group(1)) if b_match else 0.0
        if abs(a_val) > 1e-6 or abs(b_val) > 1e-6:
            result.append(stripped)
    return result


class TestOneRotationMove:
    def test_linuxcnc_one_rotation_move(self):
        """Exactly ONE non-zero-AB G0 move (the indexed orientation move)."""
        pts = _row_xy(5, a_deg=30.0, b_deg=45.0)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")

        ab_moves = _nonzero_ab_g0_lines(gcode)
        assert len(ab_moves) == 1, (
            f"Expected exactly 1 non-zero orientation G0 A/B move; got {len(ab_moves)}: {ab_moves}"
        )

    def test_linuxcnc_body_g1_no_ab(self):
        """Body G1 lines must not contain A or B words."""
        pts = _row_xy(5, a_deg=30.0, b_deg=45.0)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")

        g1s = _g1_lines(gcode)
        assert g1s, "Expected some G1 lines in body"
        for ln in g1s:
            assert not _has_ab(ln), f"A/B found in body G1 line: {ln!r}"

    def test_fanuc_one_rotation_move(self):
        """Fanuc: exactly one non-zero-AB G0 move (the indexed orientation move)."""
        pts = _row_xy(5, a_deg=30.0, b_deg=45.0)
        gcode = emit_gcode_indexed_3_2(pts, post="fanuc")

        ab_moves = _nonzero_ab_g0_lines(gcode)
        assert len(ab_moves) == 1, (
            f"Expected exactly 1 non-zero orientation G0 A/B move; got {len(ab_moves)}: {ab_moves}"
        )

    def test_fanuc_body_g1_no_ab(self):
        """Fanuc: body G1 lines must not contain A or B words."""
        pts = _row_xy(5, a_deg=30.0, b_deg=45.0)
        gcode = emit_gcode_indexed_3_2(pts, post="fanuc")

        g1s = _g1_lines(gcode)
        assert g1s, "Expected some G1 lines in body"
        for ln in g1s:
            assert not _has_ab(ln), f"A/B found in Fanuc body G1 line: {ln!r}"


# ---------------------------------------------------------------------------
# 2. Rotation angles are correct (A=30°, B=45°)
# ---------------------------------------------------------------------------

class TestRotationAngles:
    def test_linuxcnc_a30_b45(self):
        pts = _row_xy(5, a_deg=30.0, b_deg=45.0)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")

        # Find orientation move line
        ab_lines = [ln for ln in gcode.splitlines()
                    if re.match(r"G0 A", ln.strip())]
        assert ab_lines, "No orientation move found"
        ln = ab_lines[0]

        a_match = re.search(r"A([-\d.]+)", ln)
        b_match = re.search(r"B([-\d.]+)", ln)
        assert a_match and b_match
        assert abs(float(a_match.group(1)) - 30.0) < 0.01
        assert abs(float(b_match.group(1)) - 45.0) < 0.01

    def test_fanuc_a30_b45(self):
        pts = _row_xy(5, a_deg=30.0, b_deg=45.0)
        gcode = emit_gcode_indexed_3_2(pts, post="fanuc")

        ab_lines = [ln for ln in gcode.splitlines()
                    if re.search(r"G0 A", ln)]
        assert ab_lines
        ln = ab_lines[0]
        a_match = re.search(r"A([-\d.]+)", ln)
        b_match = re.search(r"B([-\d.]+)", ln)
        assert a_match and b_match
        assert abs(float(a_match.group(1)) - 30.0) < 0.01
        assert abs(float(b_match.group(1)) - 45.0) < 0.01


# ---------------------------------------------------------------------------
# 3. Body contains the correct XYZ positions
# ---------------------------------------------------------------------------

class TestBodyXYZ:
    def test_linuxcnc_xyz_in_body(self):
        pts = _row_xy(5, a_deg=30.0, b_deg=45.0, z=1.25)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")

        g1s = _g1_lines(gcode)
        # 5 points → first becomes plunge, rest are body moves; total 5 G1 lines
        assert len(g1s) == 5

        # Check X values increase by 2.0 each step
        for idx, ln in enumerate(g1s):
            x_match = re.search(r"X([-\d.]+)", ln)
            assert x_match
            assert abs(float(x_match.group(1)) - idx * 2.0) < 0.001

    def test_linuxcnc_z_correct(self):
        pts = _row_xy(3, a_deg=30.0, b_deg=45.0, z=2.0)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")

        g1s = _g1_lines(gcode)
        for ln in g1s:
            z_match = re.search(r"Z([-\d.]+)", ln)
            assert z_match
            assert abs(float(z_match.group(1)) - 2.0) < 0.001


# ---------------------------------------------------------------------------
# 4. Footer: Z50, A0 B0 home, M30
# ---------------------------------------------------------------------------

class TestFooter:
    def test_linuxcnc_footer_has_home(self):
        pts = _row_xy(3)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")
        # Should find a G0 A0 B0 home line in the footer
        assert "G0 A0.000 B0.000" in gcode

    def test_linuxcnc_footer_has_m30(self):
        pts = _row_xy(3)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")
        assert "M30" in gcode

    def test_linuxcnc_footer_has_z50_retract(self):
        pts = _row_xy(3)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")
        # The retract line comes BEFORE A0 B0 in footer
        z50_idx = gcode.find("Z50.000")
        a0_idx = gcode.rfind("G0 A0.000 B0.000")  # last occurrence
        assert z50_idx < a0_idx

    def test_fanuc_footer_has_home(self):
        pts = _row_xy(3)
        gcode = emit_gcode_indexed_3_2(pts, post="fanuc")
        assert "A0.000 B0.000" in gcode

    def test_fanuc_footer_has_m30(self):
        pts = _row_xy(3)
        gcode = emit_gcode_indexed_3_2(pts, post="fanuc")
        assert "M30" in gcode


# ---------------------------------------------------------------------------
# 5. Axis-aligned (A=B=0) edge case — no rotation move
# ---------------------------------------------------------------------------

class TestAxisAligned:
    def test_linuxcnc_no_orientation_move_when_axis_aligned(self):
        """When drive face is +Z normal (k=1.0), no non-zero-AB orientation move emitted."""
        pts = _row_upright(5)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")

        # No G0 line should carry non-zero A or B (only the A0B0 header/footer is ok)
        nonzero_ab = _nonzero_ab_g0_lines(gcode)
        assert len(nonzero_ab) == 0, f"Unexpected non-zero orientation move: {nonzero_ab}"

    def test_linuxcnc_body_still_has_xyz_when_axis_aligned(self):
        pts = _row_upright(5)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")
        g1s = _g1_lines(gcode)
        assert len(g1s) == 5

    def test_fanuc_no_orientation_move_when_axis_aligned(self):
        pts = _row_upright(5)
        gcode = emit_gcode_indexed_3_2(pts, post="fanuc")
        nonzero_ab = _nonzero_ab_g0_lines(gcode)
        assert len(nonzero_ab) == 0, f"Unexpected non-zero orientation move: {nonzero_ab}"

    def test_axis_aligned_info_comment_linuxcnc(self):
        """Axis-aligned run should note the shortcut in a comment."""
        pts = _row_upright(3)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")
        assert "axis-aligned" in gcode.lower() or "A=0" in gcode or "no rotation" in gcode.lower()


# ---------------------------------------------------------------------------
# 6. Feed-rate handling
# ---------------------------------------------------------------------------

class TestFeedRate:
    def test_default_feed_in_body(self):
        pts = _row_xy(3)
        opts = PostOpts(feed_cut_mm_min=800.0)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc", opts=opts)
        # First G1 line should carry F800
        g1s = _g1_lines(gcode)
        assert "F800" in g1s[0]

    def test_per_point_feed_override(self):
        pts = _row_xy(3)
        pts[0]["feed"] = 500.0
        pts[1]["feed"] = 600.0
        pts[2]["feed"] = 600.0  # same as previous — no F word repeated
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc")
        g1s = _g1_lines(gcode)
        # First plunge: F500
        assert "F500" in g1s[0]
        # Second move: F600 (changed)
        assert "F600" in g1s[1]
        # Third move: same feed, no F word
        assert "F" not in g1s[2]


# ---------------------------------------------------------------------------
# 7. Tool comment (T7 integration)
# ---------------------------------------------------------------------------

class TestToolComment:
    def test_linuxcnc_tool_comment(self):
        tool = parse_tool({
            "id": "T3",
            "name": "6mm ball end",
            "type": "ball_end",
            "diameter_mm": 6.0,
            "ball_radius_mm": 3.0,
            "flute_count": 2,
            "material": "carbide",
        })
        opts = PostOpts(tool=tool)
        pts = _row_xy(3)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc", opts=opts)
        assert "; tool:" in gcode
        assert "6mm ball end" in gcode
        assert "ø6" in gcode

    def test_fanuc_tool_comment_uppercase(self):
        tool = parse_tool({
            "id": "T3",
            "name": "6mm flat end",
            "type": "flat_end",
            "diameter_mm": 6.0,
        })
        opts = PostOpts(tool=tool)
        pts = _row_xy(3)
        gcode = emit_gcode_indexed_3_2(pts, post="fanuc", opts=opts)
        # Fanuc uses UPPERCASE parenthetical comments
        assert "(TOOL:" in gcode.upper()


# ---------------------------------------------------------------------------
# 8. TCP mode
# ---------------------------------------------------------------------------

class TestTCPMode:
    def test_linuxcnc_tcp_inserts_g43_4(self):
        pts = _row_xy(3)
        opts = PostOpts(use_tcp=True)
        gcode = emit_gcode_indexed_3_2(pts, post="linuxcnc", opts=opts)
        assert "G43.4" in gcode

    def test_fanuc_tcp_inserts_g43_4_and_aicc(self):
        pts = _row_xy(3)
        opts = PostOpts(use_tcp=True)
        gcode = emit_gcode_indexed_3_2(pts, post="fanuc", opts=opts)
        assert "G43.4" in gcode
        assert "G05.1 Q1" in gcode   # AICC on
        assert "G05.1 Q0" in gcode   # AICC off in footer


# ---------------------------------------------------------------------------
# 9. Error handling
# ---------------------------------------------------------------------------

class TestErrors:
    def test_unknown_post_raises(self):
        pts = _row_xy(3)
        with pytest.raises(ValueError, match="Unknown post-processor"):
            emit_gcode_indexed_3_2(pts, post="mach3")

    def test_unsupported_kinematic_raises(self):
        pts = _row_xy(3)
        opts = PostOpts(machine_kinematic="table_table")
        with pytest.raises(NotImplementedError):
            emit_gcode_indexed_3_2(pts, post="linuxcnc", opts=opts)

    def test_empty_cl_points_linuxcnc(self):
        """Empty CL list: should return a valid (short) G-code program."""
        gcode = emit_gcode_indexed_3_2([], post="linuxcnc")
        assert "M30" in gcode
        assert "M5" in gcode

    def test_empty_cl_points_fanuc(self):
        gcode = emit_gcode_indexed_3_2([], post="fanuc")
        assert "M30" in gcode


# ---------------------------------------------------------------------------
# 10. Orientation math helpers
# ---------------------------------------------------------------------------

class TestOrientationHelpers:
    def test_orientation_from_cl_points_a30_b45(self):
        pts = _row_xy(3, a_deg=30.0, b_deg=45.0)
        a, b = _orientation_from_cl_points(pts)
        assert abs(a - 30.0) < 0.01
        assert abs(b - 45.0) < 0.01

    def test_orientation_fallback_no_ijk(self):
        """When CL points have no i/j/k, return (0, 0) = axis-aligned."""
        pts = [{"x": 0.0, "y": 0.0, "z": 0.5}]
        a, b = _orientation_from_cl_points(pts)
        assert a == 0.0
        assert b == 0.0

    def test_is_axis_aligned_zero(self):
        assert _is_axis_aligned(0.0, 0.0) is True

    def test_is_axis_aligned_nonzero(self):
        assert _is_axis_aligned(30.0, 45.0) is False

    def test_is_axis_aligned_threshold(self):
        assert _is_axis_aligned(1e-8, 0.0) is True
        assert _is_axis_aligned(0.001, 0.0) is False
