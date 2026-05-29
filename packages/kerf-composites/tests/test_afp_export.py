"""Tests for kerf_composites.afp_export — G-code and APT/CL export.

Scenario: 4-course rectilinear AFP layup (0° angle, 6.35 mm tow width,
8 tows per band).  Verifies:
  - G-code has the correct number of GOTO lines + M-code fibre events
  - APT output is syntactically correct (required statements present)
  - Edge cases: empty courses list raises ValueError
  - Machine config overrides propagate correctly
"""
from __future__ import annotations

import math
import pytest

from kerf_composites.afp_export import afp_to_gcode, afp_to_apt


# ---------------------------------------------------------------------------
# Shared fixture — 4-course rectilinear layup (matches routes_composites_mfg
# analytical generator output at 0° over a 400×260 mm part)
# ---------------------------------------------------------------------------

FOUR_COURSES = [
    {
        "course_id": i,
        "angle_deg": 0.0,
        "start_x": 0.0,
        "start_y": float(i * 50),
        "end_x": 400.0,
        "end_y": float(i * 50),
        "tow_width_mm": 6.35,
        "length_mm": 400.0,
    }
    for i in range(4)
]


# ===========================================================================
# G-code tests
# ===========================================================================

class TestAfpToGcode:

    def test_returns_string(self):
        result = afp_to_gcode(FOUR_COURSES)
        assert isinstance(result, str)

    def test_contains_program_header(self):
        gcode = afp_to_gcode(FOUR_COURSES)
        # Must start with a program identifier
        assert "%" in gcode
        # Metric mode set
        assert "G21" in gcode

    def test_g01_count_matches_courses(self):
        """Every course produces exactly one G01 feed move."""
        gcode = afp_to_gcode(FOUR_COURSES)
        g01_lines = [l for l in gcode.splitlines() if l.strip().startswith("G01")]
        assert len(g01_lines) == len(FOUR_COURSES)

    def test_g00_rapid_count(self):
        """Each course needs at least 2 G00 lines (clearance + approach).
        Total G00 lines >= 2 * n_courses.
        """
        gcode = afp_to_gcode(FOUR_COURSES)
        g00_lines = [l for l in gcode.splitlines() if l.strip().startswith("G00")]
        assert len(g00_lines) >= 2 * len(FOUR_COURSES)

    def test_m200_fibre_start_count(self):
        """Each course emits exactly one M200 (fibre start)."""
        gcode = afp_to_gcode(FOUR_COURSES)
        m200 = [l for l in gcode.splitlines() if l.strip().startswith("M200")]
        assert len(m200) == len(FOUR_COURSES)

    def test_m201_fibre_stop_count(self):
        """Each course emits exactly one M201 (fibre stop)."""
        gcode = afp_to_gcode(FOUR_COURSES)
        m201 = [l for l in gcode.splitlines() if l.strip().startswith("M201")]
        assert len(m201) == len(FOUR_COURSES)

    def test_m202_tape_cut_count(self):
        """Each course emits exactly one M202 (tape cut)."""
        gcode = afp_to_gcode(FOUR_COURSES)
        m202 = [l for l in gcode.splitlines() if l.strip().startswith("M202")]
        assert len(m202) == len(FOUR_COURSES)

    def test_m203_roller_down_count(self):
        """Each course has compaction roller down (M203)."""
        gcode = afp_to_gcode(FOUR_COURSES)
        m203 = [l for l in gcode.splitlines() if l.strip().startswith("M203")]
        assert len(m203) == len(FOUR_COURSES)

    def test_m204_roller_up_count(self):
        """Each course has compaction roller up (M204)."""
        gcode = afp_to_gcode(FOUR_COURSES)
        m204 = [l for l in gcode.splitlines() if l.strip().startswith("M204")]
        assert len(m204) == len(FOUR_COURSES)

    def test_m205_force_command_present(self):
        """M205 compaction force command emitted per course."""
        gcode = afp_to_gcode(FOUR_COURSES)
        m205 = [l for l in gcode.splitlines() if l.strip().startswith("M205")]
        assert len(m205) == len(FOUR_COURSES)

    def test_default_compaction_force_in_output(self):
        """Default 150 N compaction force appears in G-code."""
        gcode = afp_to_gcode(FOUR_COURSES)
        assert "150" in gcode

    def test_m30_program_end(self):
        """M30 program end marker is present."""
        gcode = afp_to_gcode(FOUR_COURSES)
        assert "M30" in gcode

    def test_coordinate_precision_default(self):
        """Default 3-decimal precision: X0.000 form."""
        gcode = afp_to_gcode(FOUR_COURSES)
        # Should contain X with 3 decimal places
        import re
        assert re.search(r'X\d+\.\d{3}', gcode), "Expected X coordinate with 3 decimal places"

    def test_machine_config_feedrate_override(self):
        """machine_config feedrate_mmpm propagates to G01 lines."""
        cfg = {"feedrate_mmpm": 1500.0}
        gcode = afp_to_gcode(FOUR_COURSES, machine_config=cfg)
        assert "1500" in gcode

    def test_machine_config_force_override(self):
        """machine_config compaction_force_N propagates to M205."""
        cfg = {"compaction_force_N": 200.0}
        gcode = afp_to_gcode(FOUR_COURSES, machine_config=cfg)
        assert "200" in gcode

    def test_machine_name_in_header(self):
        """machine_config machine_name appears in the program header comment."""
        cfg = {"machine_name": "TEST_AFP_MACHINE"}
        gcode = afp_to_gcode(FOUR_COURSES, machine_config=cfg)
        assert "TEST_AFP_MACHINE" in gcode

    def test_program_number_in_output(self):
        """Program number O-code is present."""
        gcode = afp_to_gcode(FOUR_COURSES)
        assert "O0001" in gcode

    def test_empty_courses_raises(self):
        with pytest.raises(ValueError, match="empty"):
            afp_to_gcode([])

    def test_c_axis_at_zero_degrees(self):
        """0° angle → C0.000 or C0 in G00/G01 lines."""
        gcode = afp_to_gcode(FOUR_COURSES)
        # C-axis for 0° = 0.0
        assert "C0.000" in gcode or "C0.0" in gcode

    def test_single_course_still_valid(self):
        """Single-course export is syntactically complete."""
        gcode = afp_to_gcode([FOUR_COURSES[0]])
        assert gcode.count("M200") == 1
        assert gcode.count("M30") == 1


# ===========================================================================
# APT / CL tests
# ===========================================================================

class TestAfpToApt:

    def test_returns_string(self):
        result = afp_to_apt(FOUR_COURSES)
        assert isinstance(result, str)

    def test_partno_header(self):
        apt = afp_to_apt(FOUR_COURSES)
        assert "PARTNO" in apt

    def test_machin_statement(self):
        apt = afp_to_apt(FOUR_COURSES)
        assert "MACHIN" in apt

    def test_units_statement(self):
        apt = afp_to_apt(FOUR_COURSES)
        assert "UNITS/MM" in apt

    def test_end_statement(self):
        apt = afp_to_apt(FOUR_COURSES)
        assert apt.strip().endswith("END")

    def test_goto_count_per_course(self):
        """Each course needs at least 3 GOTO lines: clearance, start, end."""
        apt = afp_to_apt(FOUR_COURSES)
        goto_lines = [l for l in apt.splitlines() if l.strip().startswith("GOTO/")]
        # n_courses * 3 + initial (2) + final (1)
        assert len(goto_lines) >= len(FOUR_COURSES) * 3

    def test_fedrat_per_course(self):
        """FEDRAT statement emitted for each course."""
        apt = afp_to_apt(FOUR_COURSES)
        fedrat_lines = [l for l in apt.splitlines() if l.strip().startswith("FEDRAT/")]
        assert len(fedrat_lines) == len(FOUR_COURSES)

    def test_fedrat_in_ipm(self):
        """FEDRAT uses IPM units (legacy APT convention)."""
        apt = afp_to_apt(FOUR_COURSES)
        fedrat_lines = [l for l in apt.splitlines() if l.strip().startswith("FEDRAT/")]
        for line in fedrat_lines:
            assert "IPM" in line, f"FEDRAT missing IPM: {line}"

    def test_auxfun_200_per_course(self):
        """AUXFUN/200 (fibre start) present for each course."""
        apt = afp_to_apt(FOUR_COURSES)
        auxfun_200 = [l for l in apt.splitlines() if "AUXFUN/200" in l]
        assert len(auxfun_200) == len(FOUR_COURSES)

    def test_auxfun_201_per_course(self):
        """AUXFUN/201 (fibre stop) present for each course."""
        apt = afp_to_apt(FOUR_COURSES)
        auxfun_201 = [l for l in apt.splitlines() if "AUXFUN/201" in l]
        assert len(auxfun_201) == len(FOUR_COURSES)

    def test_auxfun_202_per_course(self):
        """AUXFUN/202 (tape cut) present for each course."""
        apt = afp_to_apt(FOUR_COURSES)
        auxfun_202 = [l for l in apt.splitlines() if "AUXFUN/202" in l]
        assert len(auxfun_202) == len(FOUR_COURSES)

    def test_tlaxis_per_course(self):
        """TLAXIS (tool axis) emitted for each course."""
        apt = afp_to_apt(FOUR_COURSES)
        tlaxis_lines = [l for l in apt.splitlines() if l.strip().startswith("TLAXIS/")]
        assert len(tlaxis_lines) == len(FOUR_COURSES)

    def test_rapid_present(self):
        """RAPID statements present for clearance-height moves."""
        apt = afp_to_apt(FOUR_COURSES)
        assert "RAPID" in apt

    def test_feedrate_override(self):
        """feedrate_mmpm parameter is converted and appears in FEDRAT lines."""
        apt = afp_to_apt(FOUR_COURSES, feedrate_mmpm=1524.0)
        # 1524 mm/min / 25.4 = 60.0 IPM
        assert "60.0000" in apt

    def test_empty_courses_raises(self):
        with pytest.raises(ValueError, match="empty"):
            afp_to_apt([])

    def test_comment_lines_with_course_ids(self):
        """$$ comment lines reference per-course IDs (format: $$ COURSE N ...)."""
        apt = afp_to_apt(FOUR_COURSES)
        # Match per-course comments: "$$ COURSE <N>  ..." (not the summary "$$ COURSES: N")
        course_comments = [
            l for l in apt.splitlines()
            if l.strip().startswith("$$ COURSE ") and not l.strip().startswith("$$ COURSES:")
        ]
        assert len(course_comments) == len(FOUR_COURSES)

    def test_single_course_still_valid(self):
        """Single-course APT export is complete."""
        apt = afp_to_apt([FOUR_COURSES[0]])
        assert apt.count("AUXFUN/200") == 1
        assert apt.strip().endswith("END")
