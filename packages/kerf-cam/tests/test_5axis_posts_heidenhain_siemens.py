"""
pytest tests for Heidenhain iTNC 530 and Siemens 840D 5-axis post-processors.

Tests:
  - Heidenhain simultaneous 5-axis (emit): header/footer/moves
  - Heidenhain 3+2 indexed (emit_indexed_3_2): PLANE SPATIAL present
  - Siemens 840D simultaneous (emit): TRAORI present when TCP
  - Siemens 840D 3+2 indexed (emit_indexed_3_2): CYCLE800 present
  - emit_gcode_constant_tilt dispatches to heidenhain/siemens correctly
  - emit_gcode_indexed_3_2 dispatches to heidenhain/siemens correctly
  - Table-table and head-head kinematics produce G-code without errors
"""

from __future__ import annotations

import math
import re
import pytest

from kerf_cam.five_axis.gcode_constant_tilt import emit_gcode_constant_tilt, PostOpts
from kerf_cam.five_axis.gcode_indexed_3_2 import emit_gcode_indexed_3_2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row(n: int = 5, tilt_deg: float = 15.0) -> list[dict]:
    r = math.radians(tilt_deg)
    return [
        {"x": float(i) * 5.0, "y": 0.0, "z": 0.0,
         "i": math.sin(r), "j": 0.0, "k": math.cos(r)}
        for i in range(n)
    ]


def _vertical_row(n: int = 4) -> list[dict]:
    return [{"x": float(i) * 5.0, "y": 0.0, "z": 0.0, "i": 0.0, "j": 0.0, "k": 1.0}
            for i in range(n)]


def _tilted_y(n: int = 4, tilt_deg: float = 30.0) -> list[dict]:
    r = math.radians(tilt_deg)
    return [{"x": float(i), "y": 0.0, "z": 0.0, "i": 0.0, "j": math.sin(r), "k": math.cos(r)}
            for i in range(n)]


# ===========================================================================
# Heidenhain post — simultaneous 5-axis
# ===========================================================================

class TestHeidenhainSimultaneous:
    def _gcode(self, pts=None, opts=None):
        if pts is None:
            pts = _row(5, 15.0)
        if opts is None:
            opts = PostOpts()
        return emit_gcode_constant_tilt(pts, "heidenhain", opts)

    def test_begin_end_pgm(self):
        gcode = self._gcode()
        assert "BEGIN PGM" in gcode
        assert "END PGM" in gcode

    def test_tool_call_present(self):
        opts = PostOpts(tool_number=3)
        gcode = self._gcode(opts=opts)
        assert "TOOL CALL 3" in gcode

    def test_spindle_in_tool_call(self):
        opts = PostOpts(spindle_rpm=15000)
        gcode = self._gcode(opts=opts)
        assert "S15000" in gcode

    def test_m3_spindle_on(self):
        assert "M3" in self._gcode()

    def test_m8_flood_coolant(self):
        opts = PostOpts(coolant="flood")
        assert "M8" in self._gcode(opts=opts)

    def test_m7_mist_coolant(self):
        opts = PostOpts(coolant="mist")
        gcode = self._gcode(opts=opts)
        assert "M7" in gcode

    def test_m30_end(self):
        assert "M30" in self._gcode()

    def test_m5_spindle_off_in_footer(self):
        assert "M5" in self._gcode()

    def test_m9_coolant_off_in_footer(self):
        assert "M9" in self._gcode()

    def test_l_blocks_present(self):
        """Heidenhain uses 'L' for linear interpolation."""
        gcode = self._gcode()
        l_lines = [ln for ln in gcode.splitlines() if ln.strip().startswith("L ") or
                   ln.strip().startswith("N") and " L " in ln]
        assert len(l_lines) > 0, "No L-block lines found"

    def test_ab_angles_in_cutting_moves(self):
        """L cutting moves must contain A and B."""
        gcode = self._gcode(_row(5, 15.0))
        lines = [ln for ln in gcode.splitlines()
                 if ("L " in ln) and "A" in ln and "B" in ln and "FMAX" not in ln]
        assert len(lines) > 0, "No cutting L moves with A/B found"

    def test_tcp_mode_emits_m128(self):
        opts = PostOpts(use_tcp=True)
        gcode = self._gcode(opts=opts)
        assert "M128" in gcode, "M128 (TCPM) not found for use_tcp=True"

    def test_tcp_mode_emits_m129_in_footer(self):
        opts = PostOpts(use_tcp=True)
        gcode = self._gcode(opts=opts)
        assert "M129" in gcode, "M129 (TCPM off) not in footer"

    def test_no_tcp_no_m128(self):
        opts = PostOpts(use_tcp=False)
        gcode = self._gcode(opts=opts)
        assert "M128" not in gcode

    def test_b_angle_15_degrees(self):
        """15° tilt in +X → B≈15.000 in L blocks."""
        pts = [{"x": 0.0, "y": 0.0, "z": 0.0,
                "i": math.sin(math.radians(15.0)), "j": 0.0,
                "k": math.cos(math.radians(15.0))}]
        gcode = self._gcode(pts)
        # Look for B+15.xxx or B-15.xxx in L blocks
        b_matches = re.findall(r"\bB([+-]\d+\.\d+)", gcode)
        assert len(b_matches) > 0, "No B value found in L blocks"
        b_val = float(b_matches[0])
        assert abs(b_val - 15.0) < 0.1, f"Expected B≈15°, got B={b_val}"

    def test_hh_coordinates_heidenhain_style(self):
        """Heidenhain uses +/- prefixes for coordinate values."""
        gcode = self._gcode()
        # At least some coordinates must have explicit + prefix
        assert "+" in gcode, "Heidenhain-style '+' prefix missing from coordinates"

    def test_empty_cl_points_graceful(self):
        gcode = self._gcode([])
        assert "M30" in gcode
        assert "BEGIN PGM" in gcode

    def test_n_numbers_present_by_default(self):
        opts = PostOpts(no_n_numbers=False)
        gcode = self._gcode(opts=opts)
        assert "N10 " in gcode

    def test_no_n_numbers_suppressed(self):
        opts = PostOpts(no_n_numbers=True)
        gcode = self._gcode(opts=opts)
        assert "N10 " not in gcode

    def test_feed_rate_in_cutting_move(self):
        opts = PostOpts(feed_cut_mm_min=650.0)
        gcode = self._gcode(_row(3), opts=opts)
        assert "F650" in gcode


# ===========================================================================
# Heidenhain post — 3+2 indexed
# ===========================================================================

class TestHeidenhain3Plus2:
    def _gcode(self, pts=None, a=30.0, b=0.0, opts=None):
        if pts is None:
            r = math.radians(a)
            pts = [{"x": float(i), "y": 0.0, "z": 0.0,
                    "i": 0.0, "j": math.sin(r), "k": math.cos(r)}
                   for i in range(5)]
        if opts is None:
            opts = PostOpts(no_n_numbers=True)
        return emit_gcode_indexed_3_2(pts, "heidenhain", opts)

    def test_plane_spatial_present_when_tilted(self):
        """Non-axis-aligned → PLANE SPATIAL block must appear."""
        gcode = self._gcode(_tilted_y(5, 30.0), a=30.0)
        assert "PLANE SPATIAL" in gcode

    def test_plane_reset_in_footer(self):
        gcode = self._gcode(_tilted_y(5, 30.0), a=30.0)
        assert "PLANE RESET" in gcode

    def test_no_plane_spatial_for_axis_aligned(self):
        """Axis-aligned (A=B=0) → NO active PLANE SPATIAL line (non-comment lines)."""
        pts = [{"x": float(i), "y": 0.0, "z": 0.0, "i": 0.0, "j": 0.0, "k": 1.0}
               for i in range(5)]
        opts = PostOpts(no_n_numbers=True)
        gcode = emit_gcode_indexed_3_2(pts, "heidenhain", opts)
        # Must not appear in non-comment lines
        active_lines = [ln for ln in gcode.splitlines()
                        if "PLANE SPATIAL" in ln and not ln.strip().startswith(";")]
        assert len(active_lines) == 0, (
            f"Axis-aligned output should have no active PLANE SPATIAL, found: {active_lines}"
        )

    def test_body_l_lines_no_ab(self):
        """3+2 body L moves must NOT contain A or B axis words."""
        gcode = self._gcode(_tilted_y(5, 30.0), a=30.0)
        lines = gcode.splitlines()
        # Find body L lines (not rapid/orient/footer)
        body_l = []
        in_body = False
        for ln in lines:
            if "PLANE SPATIAL" in ln:
                in_body = True
                continue
            if "PLANE RESET" in ln or "L Z+50" in ln:
                in_body = False
                continue
            if in_body and ln.startswith("L ") and "FMAX" not in ln:
                body_l.append(ln)
        for ln in body_l:
            assert not re.search(r"\bA[+-]\d", ln), f"Body L has A: {ln!r}"
            assert not re.search(r"\bB[+-]\d", ln), f"Body L has B: {ln!r}"

    def test_begin_end_pgm(self):
        gcode = self._gcode(_tilted_y(3, 30.0))
        assert "BEGIN PGM" in gcode
        assert "END PGM" in gcode

    def test_m30(self):
        assert "M30" in self._gcode()

    def test_home_rotaries_in_footer(self):
        """Footer must home rotaries: L A+0 B+0."""
        gcode = self._gcode(_tilted_y(3, 30.0))
        assert "A+0 B+0" in gcode or "A+0.000 B+0.000" in gcode


# ===========================================================================
# Siemens 840D post — simultaneous 5-axis
# ===========================================================================

class TestSiemensSimultaneous:
    def _gcode(self, pts=None, opts=None):
        if pts is None:
            pts = _row(5, 15.0)
        if opts is None:
            opts = PostOpts()
        return emit_gcode_constant_tilt(pts, "siemens", opts)

    def test_header_modals(self):
        gcode = self._gcode()
        assert "G17" in gcode
        assert "G90" in gcode
        assert "G94" in gcode
        assert "G71" in gcode

    def test_tool_number_present(self):
        opts = PostOpts(tool_number=5)
        gcode = self._gcode(opts=opts)
        assert "T5" in gcode
        assert "M6" in gcode

    def test_m3_spindle(self):
        assert "M3" in self._gcode()

    def test_m8_flood(self):
        opts = PostOpts(coolant="flood")
        assert "M8" in self._gcode(opts=opts)

    def test_m7_mist(self):
        opts = PostOpts(coolant="mist")
        assert "M7" in self._gcode(opts=opts)

    def test_m5_m9_m30_in_footer(self):
        gcode = self._gcode()
        assert "M5" in gcode
        assert "M9" in gcode
        assert "M30" in gcode

    def test_traori_present_when_tcp(self):
        opts = PostOpts(use_tcp=True)
        gcode = self._gcode(opts=opts)
        assert "TRAORI" in gcode

    def test_trafoof_in_footer_when_tcp(self):
        opts = PostOpts(use_tcp=True)
        gcode = self._gcode(opts=opts)
        assert "TRAFOOF" in gcode

    def test_no_traori_without_tcp(self):
        opts = PostOpts(use_tcp=False)
        gcode = self._gcode(opts=opts)
        assert "TRAORI" not in gcode

    def test_g1_ab_present(self):
        gcode = self._gcode(_row(5, 15.0))
        g1_lines = [ln for ln in gcode.splitlines()
                    if ln.strip().startswith("G1 ") and "A" in ln and "B" in ln]
        assert len(g1_lines) > 0, "No G1 lines with A/B found in Siemens output"

    def test_b_angle_15(self):
        """B angle for 15° tilt in +X should be ≈15° in G1 lines."""
        pts = [{"x": 0.0, "y": 0.0, "z": 0.0,
                "i": math.sin(math.radians(15.0)), "j": 0.0,
                "k": math.cos(math.radians(15.0))}]
        gcode = self._gcode(pts)
        for ln in gcode.splitlines():
            if ln.strip().startswith("G1 ") and "B" in ln:
                m = re.search(r"\bB(-?\d+\.\d+)", ln)
                if m:
                    assert abs(float(m.group(1)) - 15.0) < 0.1
                break

    def test_empty_cl_graceful(self):
        gcode = self._gcode([])
        assert "M30" in gcode

    def test_feed_rate_in_g1(self):
        opts = PostOpts(feed_cut_mm_min=900.0)
        gcode = self._gcode(_row(3), opts)
        assert "F900" in gcode

    def test_semicolon_comments(self):
        """Siemens 840D uses ; for comments."""
        gcode = self._gcode()
        comment_lines = [ln for ln in gcode.splitlines() if ln.strip().startswith(";")]
        assert len(comment_lines) > 0


# ===========================================================================
# Siemens 840D post — 3+2 indexed (CYCLE800)
# ===========================================================================

class TestSiemens3Plus2:
    def _gcode(self, pts=None, opts=None):
        if pts is None:
            pts = _tilted_y(5, 30.0)
        if opts is None:
            opts = PostOpts(no_n_numbers=True)
        return emit_gcode_indexed_3_2(pts, "siemens", opts)

    def test_cycle800_present_for_tilted(self):
        """Non-axis-aligned → CYCLE800 must appear."""
        gcode = self._gcode()
        assert "CYCLE800" in gcode

    def test_cycle800_reset_in_footer(self):
        """CYCLE800() (reset) must appear in the footer."""
        gcode = self._gcode()
        lines = gcode.splitlines()
        # CYCLE800() reset has no parameters
        resets = [ln for ln in lines if ln.strip() == "CYCLE800()"]
        assert len(resets) >= 1, "CYCLE800() reset not found in footer"

    def test_cycle800_angles(self):
        """CYCLE800 must contain the A and B angle values."""
        pts = _tilted_y(3, 30.0)
        gcode = emit_gcode_indexed_3_2(pts, "siemens", PostOpts(no_n_numbers=True))
        cycle_line = next((ln for ln in gcode.splitlines() if "CYCLE800(" in ln and "30." in ln), None)
        assert cycle_line is not None, (
            "CYCLE800 line with 30° not found:\n" + gcode
        )

    def test_no_cycle800_for_axis_aligned(self):
        """Axis-aligned → no active CYCLE800 call (only appears in header comment)."""
        pts = [{"x": float(i), "y": 0.0, "z": 0.0, "i": 0.0, "j": 0.0, "k": 1.0}
               for i in range(4)]
        gcode = emit_gcode_indexed_3_2(pts, "siemens", PostOpts(no_n_numbers=True))
        # CYCLE800 must not appear in non-comment lines
        active_lines = [ln for ln in gcode.splitlines()
                        if "CYCLE800" in ln and not ln.strip().startswith(";")]
        assert len(active_lines) == 0, (
            f"Axis-aligned output should have no active CYCLE800 call, found: {active_lines}"
        )

    def test_body_g1_no_ab(self):
        """3+2 body G1 lines must NOT have A/B."""
        gcode = self._gcode()
        lines = gcode.splitlines()
        # Find G1 lines that come after CYCLE800 and before CYCLE800()
        in_body = False
        for ln in lines:
            if "CYCLE800(" in ln and ")" in ln and ln.strip() != "CYCLE800()":
                in_body = True
                continue
            if ln.strip() == "CYCLE800()":
                in_body = False
                continue
            if in_body and "G1 " in ln:
                assert not re.search(r"\bA-?\d", ln), f"Body G1 has A: {ln!r}"
                assert not re.search(r"\bB-?\d", ln), f"Body G1 has B: {ln!r}"

    def test_m30(self):
        assert "M30" in self._gcode()

    def test_home_rotaries_in_footer(self):
        gcode = self._gcode()
        assert "G0 A0 B0" in gcode


# ===========================================================================
# Dispatch: emit_gcode_constant_tilt supports heidenhain/siemens aliases
# ===========================================================================

class TestDispatchAliases:
    def test_heidenhain_alias(self):
        gcode = emit_gcode_constant_tilt(_row(3), "heidenhain_tnc")
        assert "BEGIN PGM" in gcode

    def test_tnc530_alias(self):
        gcode = emit_gcode_constant_tilt(_row(3), "tnc530")
        assert "BEGIN PGM" in gcode

    def test_tnc640_alias(self):
        gcode = emit_gcode_constant_tilt(_row(3), "tnc640")
        assert "BEGIN PGM" in gcode

    def test_siemens_alias(self):
        gcode = emit_gcode_constant_tilt(_row(3), "siemens_840d")
        assert "TRAORI" not in gcode   # use_tcp=False by default

    def test_840d_alias(self):
        gcode = emit_gcode_constant_tilt(_row(3), "840d")
        assert "G17" in gcode

    def test_sinumerik_alias(self):
        gcode = emit_gcode_constant_tilt(_row(3), "sinumerik")
        assert "G17" in gcode

    def test_unknown_post_still_raises(self):
        with pytest.raises(ValueError, match="Unknown post-processor"):
            emit_gcode_constant_tilt(_row(3), "mazak_nx")


# ===========================================================================
# Multi-kinematic: table_table and head_head emit without error
# ===========================================================================

class TestMultiKinematics:
    @pytest.mark.parametrize("kinematic", ["table_table", "head_head"])
    def test_emit_table_table_head_head(self, kinematic):
        """Both table_table and head_head should produce G-code for fanuc post."""
        opts = PostOpts(machine_kinematic=kinematic, no_n_numbers=True)
        gcode = emit_gcode_constant_tilt(_row(4, 20.0), "fanuc", opts)
        assert "G1 " in gcode or "G1\n" in gcode or "G90" in gcode
        assert "M30" in gcode

    @pytest.mark.parametrize("kinematic", ["table_table", "head_head"])
    def test_emit_linuxcnc_all_kinematics(self, kinematic):
        opts = PostOpts(machine_kinematic=kinematic, no_n_numbers=True)
        gcode = emit_gcode_constant_tilt(_row(4, 20.0), "linuxcnc", opts)
        assert "M30" in gcode
        assert "G90" in gcode

    def test_unsupported_kinematic_raises(self):
        opts = PostOpts(machine_kinematic="unknown_kin")
        with pytest.raises(NotImplementedError):
            emit_gcode_constant_tilt(_row(3), "linuxcnc", opts)
