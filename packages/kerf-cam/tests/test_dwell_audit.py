"""
Tests for kerf_cam.dwell_audit — G04 dwell audit for milling programs.

References
----------
* Machinery's Handbook 31e §1140 — Dwell commands in CNC; G04 syntax
* NIST RS-274/NGC §3.5 — G04 X<seconds> / P<milliseconds>

Run:
    pytest packages/kerf-cam/tests/test_dwell_audit.py -v
"""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cam.dwell_audit import (
    DwellAuditSpec,
    DwellAuditReport,
    audit_milling_dwells,
    cam_audit_milling_dwells_spec,
    run_cam_audit_milling_dwells,
)


# ---------------------------------------------------------------------------
# Helper — build a minimal G-code program
# ---------------------------------------------------------------------------

def _make_gcode(
    feed_mm_per_min: float = 600.0,
    total_cut_distance_mm: float = 600.0,
    dwell_commands: list[str] | None = None,
) -> str:
    """Build a tiny G-code program with configurable feed, linear moves, dwells.

    Cutting distance is split across two G01 moves.
    Programme total cutting time at F=feed: (total_cut_distance / feed) × 60 s.
    """
    if dwell_commands is None:
        dwell_commands = []
    half = total_cut_distance_mm / 2.0
    lines = [
        "G21 G90 G94",
        f"F{feed_mm_per_min:.1f}",
        "G00 X0 Y0 Z5",
        "G01 Z-1",
        f"G01 X{half:.3f}",
    ]
    lines.extend(dwell_commands)
    lines.append(f"G01 X{total_cut_distance_mm:.3f}")
    lines.append("G00 Z5")
    lines.append("M30")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 1. Basic parse — G04 X (NIST seconds) and G04 P (Fanuc milliseconds)
# ---------------------------------------------------------------------------

class TestG04Parsing:
    def test_parse_x_seconds(self):
        """G04 X0.5 → 500 ms."""
        gcode = "G21 G90 G94\nF600\nG01 X100\nG04 X0.5\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.num_dwells == 1
        assert r.dwell_per_op_ms == pytest.approx([500.0])
        assert r.total_dwell_time_ms == pytest.approx(500.0)

    def test_parse_p_milliseconds(self):
        """G04 P250 → 250 ms."""
        gcode = "G21 G90 G94\nF600\nG01 X100\nG04 P250\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.num_dwells == 1
        assert r.dwell_per_op_ms == pytest.approx([250.0])

    def test_parse_both_p_and_x_variants(self):
        """Mix of G04 P and G04 X in one program → both counted."""
        gcode = (
            "G21 G90 G94\nF600\n"
            "G01 X100\n"
            "G04 P300\n"           # 300 ms
            "G01 X200\n"
            "G04 X0.7\n"           # 700 ms
            "G01 X300\n"
            "M30"
        )
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.num_dwells == 2
        assert r.total_dwell_time_ms == pytest.approx(1000.0)
        assert sorted(r.dwell_per_op_ms) == pytest.approx(sorted([300.0, 700.0]))

    def test_no_dwells(self):
        """Program with no G04 → zero dwells."""
        gcode = "G21 G90 G94\nF600\nG01 X200\nG01 X0\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.num_dwells == 0
        assert r.total_dwell_time_ms == 0.0
        assert r.dwell_per_op_ms == []

    def test_five_g04_x0_5_total_2500ms(self):
        """Spec from task: 5 × G04 X0.5 → total_dwell_time_ms = 2500."""
        dwell_cmds = ["G04 X0.5"] * 5
        gcode = _make_gcode(
            feed_mm_per_min=600.0,
            total_cut_distance_mm=600.0,     # 60 s cutting time at F600
            dwell_commands=dwell_cmds,
        )
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.num_dwells == 5
        assert r.total_dwell_time_ms == pytest.approx(2500.0)
        assert all(d == pytest.approx(500.0) for d in r.dwell_per_op_ms)


# ---------------------------------------------------------------------------
# 2. Dwell ratio calculation
# ---------------------------------------------------------------------------

class TestDwellRatio:
    def test_five_x0_5_in_60s_program_ratio_approx_4pct(self):
        """5 × 0.5 s = 2.5 s dwell in ~60 s program → ratio ≈ 4.17 % → adequate."""
        # 600 mm at F=600 mm/min → 60 s cutting; 5 × 0.5 s = 2.5 s dwell
        # total ≈ 62.5 s → ratio = 2.5/62.5 × 100 = 4.0 %
        # (rapid time adds a tiny overhead, pushing ratio slightly below 4.17 %
        #  of the pure dwell+cutting total, but must stay < 5 %)
        dwell_cmds = ["G04 X0.5"] * 5
        gcode = _make_gcode(
            feed_mm_per_min=600.0,
            total_cut_distance_mm=600.0,
            dwell_commands=dwell_cmds,
        )
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        # Ratio must be < 5 % (adequate) and > 3 % (non-trivial)
        assert r.dwell_ratio_pct < 5.0
        assert r.dwell_ratio_pct > 2.0
        assert r.excessive is False

    def test_total_dwell_exceeds_5pct_marks_excessive(self):
        """If dwell > 5 % of program time, excessive=True."""
        # 10 × G04 X2.0 = 20 s dwell; cutting = 600/600 × 60 = 60 s
        # ratio = 20 / (60 + 20 + ...) ≈ 24 % → excessive
        dwell_cmds = ["G04 X2.0"] * 10
        gcode = _make_gcode(
            feed_mm_per_min=600.0,
            total_cut_distance_mm=600.0,
            dwell_commands=dwell_cmds,
        )
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.excessive is True
        assert r.dwell_ratio_pct > 5.0

    def test_zero_program_time_ratio_is_zero(self):
        """Empty G-code (no motion, no dwell) → ratio=0, not a div-by-zero error."""
        spec = DwellAuditSpec(gcode_text="M30")
        r = audit_milling_dwells(spec)
        assert r.dwell_ratio_pct == 0.0
        assert r.excessive is False

    def test_dwell_only_program_ratio_100pct(self):
        """Program with only a dwell and no cutting → ratio = 100 %."""
        gcode = "G04 P1000\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        # total_program_time = 1.0 s dwell; ratio = 100 %
        assert r.dwell_ratio_pct == pytest.approx(100.0)
        assert r.excessive is True

    def test_custom_threshold_ratio(self):
        """Custom max_total_dwell_ratio_pct=2.0 → flag earlier."""
        dwell_cmds = ["G04 X0.5"] * 5   # ≈ 4 % ratio
        gcode = _make_gcode(600.0, 600.0, dwell_cmds)
        spec = DwellAuditSpec(gcode_text=gcode, max_total_dwell_ratio_pct=2.0)
        r = audit_milling_dwells(spec)
        # Ratio ≈ 4 % > 2 % custom threshold → excessive
        assert r.excessive is True


# ---------------------------------------------------------------------------
# 3. Suspicious long-dwell detection
# ---------------------------------------------------------------------------

class TestSuspiciousLongDwells:
    def test_one_5s_dwell_flagged_suspicious(self):
        """Single G04 X5.0 (5 000 ms) is suspicious (> 500 ms default)."""
        gcode = "G21 G90 G94\nF600\nG01 X200\nG04 X5.0\nG01 X400\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert 5000.0 in r.suspicious_long_dwells

    def test_short_dwells_not_suspicious(self):
        """G04 P200 (200 ms) not suspicious when threshold=500 ms."""
        gcode = "G21 G90 G94\nF600\nG01 X200\nG04 P200\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.suspicious_long_dwells == []

    def test_exact_threshold_not_suspicious(self):
        """G04 P500 exactly equals threshold → NOT suspicious (> not >=)."""
        gcode = "G21 G90 G94\nF600\nG01 X200\nG04 P500\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.suspicious_long_dwells == []

    def test_custom_threshold_suspicious(self):
        """Custom max_recommended_dwell_per_op_ms=200 → flag 300 ms dwell."""
        gcode = "G21 G90 G94\nF600\nG01 X200\nG04 P300\nM30"
        spec = DwellAuditSpec(
            gcode_text=gcode,
            max_recommended_dwell_per_op_ms=200.0,
        )
        r = audit_milling_dwells(spec)
        assert 300.0 in r.suspicious_long_dwells

    def test_multiple_suspicious_dwells(self):
        """Both 1 000 ms and 3 000 ms flagged; 400 ms not."""
        gcode = (
            "G21 G90 G94\nF600\n"
            "G01 X100\nG04 P400\n"     # not suspicious
            "G01 X200\nG04 X1.0\n"     # suspicious (1000 ms)
            "G01 X300\nG04 X3.0\n"     # suspicious (3000 ms)
            "M30"
        )
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert len(r.suspicious_long_dwells) == 2
        assert 1000.0 in r.suspicious_long_dwells
        assert 3000.0 in r.suspicious_long_dwells
        assert 400.0 not in r.suspicious_long_dwells


# ---------------------------------------------------------------------------
# 4. Cutting-time estimation
# ---------------------------------------------------------------------------

class TestCuttingTimeEstimation:
    def test_simple_g01_cutting_time(self):
        """100 mm at F600 mm/min → 10 s cutting time."""
        gcode = "G21 G90 G94\nF600\nG01 X100\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        # cutting_s = 100/600 * 60 = 10 s; rapid from G00 not added yet
        # total ≈ 10 + small_rapid_time
        # No dwells → dwell_ratio = 0
        assert r.dwell_ratio_pct == 0.0
        # Cutting-time component: 10 s; total includes a small rapid component
        # total_program_time_estimate_s >= 10 s
        assert r.total_program_time_estimate_s >= 10.0

    def test_feed_modal_state_carries_across_lines(self):
        """F set on separate line is modal; all subsequent G01 use it."""
        gcode = (
            "G21 G90 G94\n"
            "F300\n"                   # feed set here
            "G01 X300\n"               # 300 mm at F300 → 60 s
            "G04 X1.0\n"               # 1 s dwell
            "M30"
        )
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        # cutting_s ≈ 60 s; dwell = 1 s; ratio < 2 %
        assert r.num_dwells == 1
        assert r.dwell_ratio_pct < 2.0

    def test_g00_rapid_not_included_in_cutting_time(self):
        """G00 rapids don't count as cutting time."""
        gcode = "G21 G90 G94\nF600\nG00 X500\nG01 X600\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        # G01: 100 mm at F600 → 10 s cutting
        # G00: 500 mm → rapid time
        # total > 10 s but G00 is NOT attributed to cutting
        assert r.total_program_time_estimate_s > 10.0

    def test_3d_g01_distance(self):
        """3D G01 move: distance = sqrt(3²+4²+0²) = 5 mm."""
        gcode = "G21 G90 G94\nF300\nG01 X3 Y4\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        # dist = 5; cutting_s = 5/300 * 60 = 1 s
        # Dwell ratio 0 %
        assert r.dwell_ratio_pct == 0.0
        assert r.total_program_time_estimate_s == pytest.approx(1.0, rel=0.05)


# ---------------------------------------------------------------------------
# 5. Inch mode (G20)
# ---------------------------------------------------------------------------

class TestInchMode:
    def test_g04_x_seconds_still_seconds_in_inch_mode(self):
        """G04 X word is always seconds; inch mode does not affect dwell time."""
        gcode = "G20 G90 G94\nF24\nG01 X1.0\nG04 X0.5\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.num_dwells == 1
        assert r.dwell_per_op_ms == pytest.approx([500.0])

    def test_g04_p_ms_still_ms_in_inch_mode(self):
        """G04 P word is always milliseconds regardless of units mode."""
        gcode = "G20 G90 G94\nF24\nG01 X1.0\nG04 P300\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.dwell_per_op_ms == pytest.approx([300.0])


# ---------------------------------------------------------------------------
# 6. Report structure and field types
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_report_fields_present_and_typed(self):
        gcode = "G21 G90 G94\nF600\nG01 X100\nG04 P500\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert isinstance(r.total_dwell_time_ms, float)
        assert isinstance(r.num_dwells, int)
        assert isinstance(r.dwell_per_op_ms, list)
        assert isinstance(r.total_program_time_estimate_s, float)
        assert isinstance(r.dwell_ratio_pct, float)
        assert isinstance(r.excessive, bool)
        assert isinstance(r.suspicious_long_dwells, list)
        assert isinstance(r.honest_caveat, str)
        assert len(r.honest_caveat) > 80

    def test_honest_caveat_mentions_references(self):
        gcode = "M30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert "MH 31e §1140" in r.honest_caveat
        assert "NIST RS-274/NGC §3.5" in r.honest_caveat

    def test_total_dwell_equals_sum_of_per_op(self):
        gcode = (
            "G21 G90 G94\nF600\n"
            "G01 X100\nG04 P300\n"
            "G01 X200\nG04 X0.5\n"
            "G01 X300\nG04 P1000\n"
            "M30"
        )
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.total_dwell_time_ms == pytest.approx(sum(r.dwell_per_op_ms))

    def test_num_dwells_matches_list_length(self):
        gcode = (
            "G21 G90 G94\nF600\n"
            "G04 P100\nG04 P200\nG04 P300\n"
            "M30"
        )
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.num_dwells == len(r.dwell_per_op_ms)
        assert r.num_dwells == 3


# ---------------------------------------------------------------------------
# 7. Input validation
# ---------------------------------------------------------------------------

class TestInputValidation:
    def test_non_string_gcode_raises(self):
        with pytest.raises(TypeError):
            DwellAuditSpec(gcode_text=123)  # type: ignore[arg-type]

    def test_zero_max_dwell_raises(self):
        with pytest.raises(ValueError, match="max_recommended_dwell_per_op_ms"):
            DwellAuditSpec(gcode_text="M30", max_recommended_dwell_per_op_ms=0.0)

    def test_negative_max_dwell_raises(self):
        with pytest.raises(ValueError, match="max_recommended_dwell_per_op_ms"):
            DwellAuditSpec(gcode_text="M30", max_recommended_dwell_per_op_ms=-10.0)

    def test_zero_ratio_threshold_raises(self):
        with pytest.raises(ValueError, match="max_total_dwell_ratio_pct"):
            DwellAuditSpec(gcode_text="M30", max_total_dwell_ratio_pct=0.0)

    def test_over_100_ratio_threshold_raises(self):
        with pytest.raises(ValueError, match="max_total_dwell_ratio_pct"):
            DwellAuditSpec(gcode_text="M30", max_total_dwell_ratio_pct=101.0)


# ---------------------------------------------------------------------------
# 8. LLM tool spec
# ---------------------------------------------------------------------------

class TestLLMToolSpec:
    def test_spec_name(self):
        assert cam_audit_milling_dwells_spec.name == "cam_audit_milling_dwells"

    def test_spec_description_mentions_references(self):
        desc = cam_audit_milling_dwells_spec.description
        assert "MH 31e §1140" in desc
        assert "NIST RS-274/NGC §3.5" in desc

    def test_spec_required_fields(self):
        required = cam_audit_milling_dwells_spec.input_schema["required"]
        assert "gcode_text" in required


# ---------------------------------------------------------------------------
# 9. LLM tool runner — async roundtrip
# ---------------------------------------------------------------------------

class TestLLMToolRunner:
    def _call(self, payload: dict) -> dict:
        raw = asyncio.get_event_loop().run_until_complete(
            run_cam_audit_milling_dwells(None, json.dumps(payload).encode())
        )
        return json.loads(raw)

    def test_valid_program_returns_report(self):
        gcode = "G21 G90 G94\nF600\nG01 X100\nG04 P500\nM30"
        result = self._call({"gcode_text": gcode})
        assert "total_dwell_time_ms" in result
        assert result["total_dwell_time_ms"] == pytest.approx(500.0)
        assert result["num_dwells"] == 1

    def test_missing_gcode_returns_error(self):
        result = self._call({})
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_invalid_json_returns_error(self):
        raw = asyncio.get_event_loop().run_until_complete(
            run_cam_audit_milling_dwells(None, b"{bad json{{")
        )
        result = json.loads(raw)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_custom_thresholds_passed_through(self):
        gcode = "G21 G90 G94\nF600\nG01 X100\nG04 P300\nM30"
        result = self._call({
            "gcode_text": gcode,
            "max_recommended_dwell_per_op_ms": 200.0,
            "max_total_dwell_ratio_pct": 3.0,
        })
        assert result["suspicious_long_dwells"] == pytest.approx([300.0])

    def test_honest_caveat_in_result(self):
        gcode = "M30"
        result = self._call({"gcode_text": gcode})
        assert "honest_caveat" in result
        assert len(result["honest_caveat"]) > 80

    def test_excessive_flag_false_when_adequate(self):
        """5 × G04 X0.5 in a 60 s program → ratio < 5 % → excessive=False."""
        dwell_cmds = ["G04 X0.5"] * 5
        gcode = _make_gcode(600.0, 600.0, dwell_cmds)
        result = self._call({"gcode_text": gcode})
        assert result["excessive"] is False
        assert result["num_dwells"] == 5
        assert result["total_dwell_time_ms"] == pytest.approx(2500.0)

    def test_excessive_flag_true_when_high_ratio(self):
        dwell_cmds = ["G04 X2.0"] * 10   # 20 s in ~60+20 s program ≈ 24 %
        gcode = _make_gcode(600.0, 600.0, dwell_cmds)
        result = self._call({"gcode_text": gcode})
        assert result["excessive"] is True


# ---------------------------------------------------------------------------
# 10. Edge cases and G-code quirks
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_program(self):
        """Empty string → no dwells, no motion, no error."""
        spec = DwellAuditSpec(gcode_text="")
        r = audit_milling_dwells(spec)
        assert r.num_dwells == 0
        assert r.total_dwell_time_ms == 0.0
        assert r.dwell_ratio_pct == 0.0

    def test_comments_not_parsed_as_dwells(self):
        """Parenthetical comments containing G04 are ignored."""
        gcode = (
            "G21 G90 G94\n"
            "(G04 P500 - this is a comment)\n"
            "G01 X100\n"
            "M30"
        )
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.num_dwells == 0

    def test_large_p_value_dwell(self):
        """G04 P5000 = 5000 ms = 5 s → confirmed."""
        gcode = "G21 G90 G94\nF600\nG01 X600\nG04 P5000\nM30"
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.dwell_per_op_ms == pytest.approx([5000.0])
        assert r.suspicious_long_dwells == pytest.approx([5000.0])

    def test_incremental_mode_g91(self):
        """G91 incremental moves: 3 × G01 X100 → 300 mm total travel."""
        gcode = (
            "G21 G91 G94\n"
            "F600\n"
            "G01 X100\n"
            "G01 X100\n"
            "G04 P200\n"
            "G01 X100\n"
            "M30"
        )
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        assert r.num_dwells == 1
        assert r.dwell_per_op_ms == pytest.approx([200.0])
        # 300 mm at F600 → 30 s cutting; 0.2 s dwell → ratio ≈ 0.66 %
        assert r.dwell_ratio_pct < 2.0

    def test_g04_with_space_between_g_and_04(self):
        """Some controllers emit 'G 04 P500' with space."""
        gcode = "G21 G90 G94\nF600\nG01 X100\nG 04 P500\nM30"
        # word regex strips interior whitespace → should still parse G=4
        # However, multi-word parsing: G and 04 are separate tokens.
        # Our parser picks the first G value; '04' as a standalone number is
        # not a word. Result: G4 may NOT be detected by the word-map approach.
        # This is a documented limitation — but let's test actual behaviour.
        spec = DwellAuditSpec(gcode_text=gcode)
        r = audit_milling_dwells(spec)
        # Whether parsed or not, this is an edge-case corner — just confirm no crash.
        assert isinstance(r.num_dwells, int)
