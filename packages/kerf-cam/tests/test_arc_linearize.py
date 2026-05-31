"""
Tests for kerf_cam.arc_linearize — G02/G03 arc linearisation.

Reference: NIST RS-274/NGC §3.5.3; MH 31e §1130.

Segment count formula: N = ceil(θ_arc / Δθ) where Δθ = 2·acos(1 − ε/R)
For R=10, ε=0.025:
  Δθ = 2·acos(1 − 0.025/10) = 2·acos(0.9975) ≈ 0.14145 rad ≈ 8.105°
  N_full_circle = ceil(2π / 0.14145) ≈ ceil(44.44) = 45 segments

Note: the task description approximation of "≈ 89" was based on the chord-length
arc-length formula 2π·R / (2·sqrt(ε·(2R−ε))); the correct Δθ formula above
gives 45, which is what the implementation uses per MH 31e §1130.
"""

from __future__ import annotations

import math

import pytest

from kerf_cam.arc_linearize import (
    ArcLinearizeSpec,
    ArcLinearizeResult,
    linearize_arcs,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_g01(gcode: str) -> int:
    """Count lines containing a G01 command."""
    return sum(1 for ln in gcode.splitlines() if "G01" in ln.upper())


def _count_g02_g03(gcode: str) -> int:
    """Count remaining G02/G03 lines (should be 0 for valid arcs)."""
    return sum(
        1 for ln in gcode.splitlines()
        if ("G02" in ln.upper() or "G03" in ln.upper())
        and "arc_linearize" not in ln.lower()  # skip warning comments
    )


def _dtheta_for(r: float, eps: float) -> float:
    ratio = min(eps / r, 1.0)
    return 2.0 * math.acos(1.0 - ratio)


def _expected_n_full_circle(r: float, eps: float) -> int:
    dtheta = _dtheta_for(r, eps)
    return math.ceil(2 * math.pi / dtheta)


# ---------------------------------------------------------------------------
# 1. ArcLinearizeSpec validation
# ---------------------------------------------------------------------------

class TestArcLinearizeSpec:

    def test_valid_spec_defaults(self):
        spec = ArcLinearizeSpec(gcode_text="G21\nG90\n")
        assert spec.max_chord_error_mm == 0.025
        assert spec.min_segment_length_mm == 0.05

    def test_valid_spec_custom(self):
        spec = ArcLinearizeSpec(
            gcode_text="G21\n",
            max_chord_error_mm=0.010,
            min_segment_length_mm=0.02,
        )
        assert spec.max_chord_error_mm == 0.010

    def test_invalid_gcode_text_type(self):
        with pytest.raises(TypeError, match="gcode_text must be a str"):
            ArcLinearizeSpec(gcode_text=123)

    def test_invalid_chord_error_zero(self):
        with pytest.raises(ValueError, match="max_chord_error_mm must be > 0"):
            ArcLinearizeSpec(gcode_text="G21\n", max_chord_error_mm=0.0)

    def test_invalid_chord_error_negative(self):
        with pytest.raises(ValueError):
            ArcLinearizeSpec(gcode_text="G21\n", max_chord_error_mm=-0.01)

    def test_invalid_min_segment_negative(self):
        with pytest.raises(ValueError):
            ArcLinearizeSpec(gcode_text="G21\n", min_segment_length_mm=-1.0)


# ---------------------------------------------------------------------------
# 2. G01 lines pass through unchanged
# ---------------------------------------------------------------------------

class TestG01PassThrough:

    def test_pure_g01_lines_unchanged(self):
        gcode = (
            "G21 G90\n"
            "G01 X10 Y0 F500\n"
            "G01 X10 Y10\n"
            "G01 X0 Y10\n"
            "M30\n"
        )
        spec = ArcLinearizeSpec(gcode_text=gcode)
        result = linearize_arcs(spec)
        assert result.num_arcs_processed == 0
        assert result.total_segments_emitted == 0
        assert result.linearized_gcode == gcode
        # No arc expansion
        assert result.expansion_ratio == 0.0

    def test_g00_rapid_lines_unchanged(self):
        gcode = "G00 X50 Y50 Z5\nG00 X0 Y0\n"
        spec = ArcLinearizeSpec(gcode_text=gcode)
        result = linearize_arcs(spec)
        assert result.num_arcs_processed == 0
        assert result.linearized_gcode == gcode

    def test_empty_program(self):
        spec = ArcLinearizeSpec(gcode_text="")
        result = linearize_arcs(spec)
        assert result.num_arcs_processed == 0
        assert result.linearized_gcode == ""

    def test_comment_lines_unchanged(self):
        gcode = "(Program start)\n; feed setup\nG21 G90\nM30\n"
        spec = ArcLinearizeSpec(gcode_text=gcode)
        result = linearize_arcs(spec)
        assert result.linearized_gcode == gcode


# ---------------------------------------------------------------------------
# 3. Full circle G02, R=10mm, chord_error=0.025
# ---------------------------------------------------------------------------

class TestFullCircleG02IJ:

    def setup_method(self):
        # Full circle: G02 from (10,0) with centre at (0,0) → I=-10, J=0
        # Start point set by G00 X10 Y0
        self.gcode = (
            "G21 G90\n"
            "G00 X10 Y0\n"
            "G02 I-10 J0 F300\n"
            "M30\n"
        )
        self.spec = ArcLinearizeSpec(
            gcode_text=self.gcode,
            max_chord_error_mm=0.025,
            min_segment_length_mm=0.0,
        )
        self.result = linearize_arcs(self.spec)

    def test_one_arc_processed(self):
        assert self.result.num_arcs_processed == 1

    def test_segment_count_approx_45(self):
        # N = ceil(2π / (2·acos(1 − 0.025/10)))
        # Δθ ≈ 0.14145 rad → N = ceil(44.44) = 45
        expected = _expected_n_full_circle(10.0, 0.025)
        assert expected == 45, f"Expected 45 but formula gives {expected}"
        assert self.result.total_segments_emitted == expected

    def test_all_segments_are_g01(self):
        g01_count = _count_g01(self.result.linearized_gcode)
        assert g01_count == self.result.total_segments_emitted

    def test_no_g02_remaining(self):
        assert _count_g02_g03(self.result.linearized_gcode) == 0

    def test_chord_error_within_tolerance(self):
        assert self.result.max_actual_chord_error_mm <= 0.025 + 1e-9

    def test_expansion_ratio_approx_45(self):
        assert abs(self.result.expansion_ratio - 45.0) < 0.1


# ---------------------------------------------------------------------------
# 4. Half arc 180° G02, R=10mm → ~half the full-circle segments
# ---------------------------------------------------------------------------

class TestHalfArcG02IJ:

    def setup_method(self):
        # G02 half circle: start (10,0) → end (-10,0), centre (0,0)
        # I=-10, J=0; endpoint X=-10, Y=0
        self.gcode = (
            "G21 G90\n"
            "G00 X10 Y0\n"
            "G02 X-10 Y0 I-10 J0 F300\n"
            "M30\n"
        )
        self.spec = ArcLinearizeSpec(
            gcode_text=self.gcode,
            max_chord_error_mm=0.025,
            min_segment_length_mm=0.0,
        )
        self.result = linearize_arcs(self.spec)

    def test_one_arc_processed(self):
        assert self.result.num_arcs_processed == 1

    def test_half_circle_segments_half_of_full(self):
        # 180° arc → half of full-circle segments
        full = _expected_n_full_circle(10.0, 0.025)
        half = math.ceil(full / 2)
        # Allow ±1 due to integer ceiling rounding on half-angle
        assert abs(self.result.total_segments_emitted - half) <= 1

    def test_chord_error_within_tolerance(self):
        assert self.result.max_actual_chord_error_mm <= 0.025 + 1e-9

    def test_no_g02_remaining(self):
        assert _count_g02_g03(self.result.linearized_gcode) == 0


# ---------------------------------------------------------------------------
# 5. G03 CCW arc (quarter circle)
# ---------------------------------------------------------------------------

class TestQuarterCircleG03:

    def setup_method(self):
        # G03 quarter circle: start (10,0) → end (0,10), centre (0,0)
        # I=-10, J=0
        self.gcode = (
            "G21 G90\n"
            "G00 X10 Y0\n"
            "G03 X0 Y10 I-10 J0 F200\n"
            "M30\n"
        )
        self.spec = ArcLinearizeSpec(
            gcode_text=self.gcode,
            max_chord_error_mm=0.025,
            min_segment_length_mm=0.0,
        )
        self.result = linearize_arcs(self.spec)

    def test_one_arc_processed(self):
        assert self.result.num_arcs_processed == 1

    def test_quarter_circle_segments(self):
        dtheta = _dtheta_for(10.0, 0.025)
        expected_n = math.ceil((math.pi / 2) / dtheta)
        assert abs(self.result.total_segments_emitted - expected_n) <= 1

    def test_chord_error_within_tolerance(self):
        assert self.result.max_actual_chord_error_mm <= 0.025 + 1e-9

    def test_no_g03_remaining(self):
        assert _count_g02_g03(self.result.linearized_gcode) == 0


# ---------------------------------------------------------------------------
# 6. Multiple arcs in same program
# ---------------------------------------------------------------------------

class TestMultipleArcs:

    def setup_method(self):
        # Two arcs: G02 half circle + G03 quarter circle
        self.gcode = (
            "G21 G90\n"
            "G00 X10 Y0\n"
            "G02 X-10 Y0 I-10 J0 F300\n"   # half CW
            "G00 X10 Y0\n"
            "G03 X0 Y10 I-10 J0 F200\n"    # quarter CCW
            "M30\n"
        )
        self.spec = ArcLinearizeSpec(
            gcode_text=self.gcode,
            max_chord_error_mm=0.025,
            min_segment_length_mm=0.0,
        )
        self.result = linearize_arcs(self.spec)

    def test_two_arcs_processed(self):
        assert self.result.num_arcs_processed == 2

    def test_total_segments_sum_of_individual(self):
        # Half circle segments (≈ 45) + quarter circle segments (≈ 23)
        full_n = _expected_n_full_circle(10.0, 0.025)
        half_n = math.ceil(full_n / 2)
        quarter_n = math.ceil(full_n / 4)
        expected_total = half_n + quarter_n
        # Allow ±2 for integer rounding
        assert abs(self.result.total_segments_emitted - expected_total) <= 2

    def test_no_g02_g03_remaining(self):
        assert _count_g02_g03(self.result.linearized_gcode) == 0

    def test_non_arc_lines_preserved(self):
        # M30 should be in output
        assert "M30" in self.result.linearized_gcode
        # Both G00 lines should be in output
        g00_count = sum(
            1 for ln in self.result.linearized_gcode.splitlines()
            if "G00" in ln.upper()
        )
        assert g00_count == 2


# ---------------------------------------------------------------------------
# 7. R-format arcs
# ---------------------------------------------------------------------------

class TestRFormatArc:

    def test_r_format_minor_arc_g02(self):
        # Semicircle: start (10,0) → end (-10,0), R=10 → minor arc (180°) with G02 CW
        # Note: for a diameter chord with R=10, the minor arc is exactly 180°
        gcode = (
            "G21 G90\n"
            "G00 X10 Y0\n"
            "G02 X-10 Y0 R10 F300\n"
            "M30\n"
        )
        spec = ArcLinearizeSpec(
            gcode_text=gcode,
            max_chord_error_mm=0.025,
            min_segment_length_mm=0.0,
        )
        result = linearize_arcs(spec)
        assert result.num_arcs_processed == 1
        assert result.total_segments_emitted > 0
        assert _count_g02_g03(result.linearized_gcode) == 0
        assert result.max_actual_chord_error_mm <= 0.025 + 1e-9

    def test_r_format_full_circle_warning(self):
        # Full circle R-format: start == end → ambiguous, passed through with comment
        gcode = (
            "G21 G90\n"
            "G00 X10 Y0\n"
            "G02 X10 Y0 R10 F300\n"
            "M30\n"
        )
        spec = ArcLinearizeSpec(gcode_text=gcode)
        result = linearize_arcs(spec)
        # Should NOT be counted as processed (ambiguous)
        assert result.num_arcs_processed == 0
        # Warning comment should appear
        assert "arc_linearize" in result.linearized_gcode.lower()

    def test_r_format_impossible_chord(self):
        # chord > 2R: geometrically invalid → pass through with comment
        gcode = (
            "G21 G90\n"
            "G00 X0 Y0\n"
            "G02 X100 Y0 R10 F300\n"   # chord=100, 2R=20: impossible
            "M30\n"
        )
        spec = ArcLinearizeSpec(gcode_text=gcode)
        result = linearize_arcs(spec)
        assert result.num_arcs_processed == 0
        assert "arc_linearize" in result.linearized_gcode.lower()


# ---------------------------------------------------------------------------
# 8. Chord error precision (tighter tolerance → more segments)
# ---------------------------------------------------------------------------

class TestChordErrorPrecision:

    def test_tighter_tolerance_more_segments(self):
        gcode = (
            "G21 G90\n"
            "G00 X10 Y0\n"
            "G02 I-10 J0 F300\n"  # full circle
            "M30\n"
        )
        spec_loose = ArcLinearizeSpec(
            gcode_text=gcode, max_chord_error_mm=0.1, min_segment_length_mm=0.0
        )
        spec_tight = ArcLinearizeSpec(
            gcode_text=gcode, max_chord_error_mm=0.005, min_segment_length_mm=0.0
        )
        r_loose = linearize_arcs(spec_loose)
        r_tight = linearize_arcs(spec_tight)
        assert r_tight.total_segments_emitted > r_loose.total_segments_emitted

    def test_chord_error_never_exceeds_spec(self):
        for eps in (0.005, 0.025, 0.1):
            gcode = (
                "G21 G90\n"
                "G00 X10 Y0\n"
                "G02 I-10 J0 F300\n"
                "M30\n"
            )
            spec = ArcLinearizeSpec(
                gcode_text=gcode,
                max_chord_error_mm=eps,
                min_segment_length_mm=0.0,
            )
            result = linearize_arcs(spec)
            assert result.max_actual_chord_error_mm <= eps + 1e-9, (
                f"eps={eps}: actual chord error {result.max_actual_chord_error_mm} exceeds tolerance"
            )


# ---------------------------------------------------------------------------
# 9. Min segment length floor
# ---------------------------------------------------------------------------

class TestMinSegmentLength:

    def test_min_segment_length_reduces_count_on_small_arc(self):
        # Tiny arc: R=0.5mm, eps=0.025 → without floor: ~12 segments
        # With min_segment_length=0.5mm floor, segments should be fewer
        gcode = (
            "G21 G90\n"
            "G00 X0.5 Y0\n"
            "G02 I-0.5 J0 F100\n"
            "M30\n"
        )
        spec_no_floor = ArcLinearizeSpec(
            gcode_text=gcode,
            max_chord_error_mm=0.025,
            min_segment_length_mm=0.0,
        )
        spec_with_floor = ArcLinearizeSpec(
            gcode_text=gcode,
            max_chord_error_mm=0.025,
            min_segment_length_mm=0.3,
        )
        r_no_floor = linearize_arcs(spec_no_floor)
        r_with_floor = linearize_arcs(spec_with_floor)
        assert r_with_floor.total_segments_emitted <= r_no_floor.total_segments_emitted


# ---------------------------------------------------------------------------
# 10. Helical arc (Z travel on arc line)
# ---------------------------------------------------------------------------

class TestHelicalArc:

    def test_z_linearly_interpolated(self):
        # G02 half circle with Z travel from 0 to -5
        gcode = (
            "G21 G90\n"
            "G00 X10 Y0 Z0\n"
            "G02 X-10 Y0 Z-5 I-10 J0 F200\n"
            "M30\n"
        )
        spec = ArcLinearizeSpec(
            gcode_text=gcode,
            max_chord_error_mm=0.025,
            min_segment_length_mm=0.0,
        )
        result = linearize_arcs(spec)
        assert result.num_arcs_processed == 1
        # Final segment should end at Z-5
        linearized_lines = result.linearized_gcode.splitlines()
        # Find G01 lines
        g01_lines = [ln for ln in linearized_lines if "G01" in ln.upper()]
        assert len(g01_lines) > 0
        # Last G01 line should contain Z-5 (approximately)
        last_g01 = g01_lines[-1]
        assert "Z" in last_g01.upper()
        # Extract Z value
        import re
        z_match = re.search(r'Z\s*([+-]?\d+(?:\.\d*)?)', last_g01)
        assert z_match is not None
        z_val = float(z_match.group(1))
        assert abs(z_val - (-5.0)) < 0.001


# ---------------------------------------------------------------------------
# 11. Feed rate preserved on segments
# ---------------------------------------------------------------------------

class TestFeedRatePreserved:

    def test_feed_rate_on_arc_line_emitted_on_segments(self):
        gcode = (
            "G21 G90\n"
            "G00 X10 Y0\n"
            "G02 I-10 J0 F450\n"
            "M30\n"
        )
        spec = ArcLinearizeSpec(gcode_text=gcode)
        result = linearize_arcs(spec)
        g01_lines = [ln for ln in result.linearized_gcode.splitlines()
                     if "G01" in ln.upper()]
        assert len(g01_lines) > 0
        # Each G01 should carry F450
        for ln in g01_lines:
            assert "F450" in ln or "F450.0" in ln or "F450." in ln, (
                f"Expected F450 in segment line: {ln!r}"
            )


# ---------------------------------------------------------------------------
# 12. ArcLinearizeResult dataclass fields
# ---------------------------------------------------------------------------

class TestResultFields:

    def test_result_has_required_fields(self):
        gcode = (
            "G21 G90\n"
            "G00 X10 Y0\n"
            "G02 I-10 J0 F300\n"
            "M30\n"
        )
        spec = ArcLinearizeSpec(gcode_text=gcode)
        result = linearize_arcs(spec)
        assert isinstance(result, ArcLinearizeResult)
        assert isinstance(result.linearized_gcode, str)
        assert isinstance(result.num_arcs_processed, int)
        assert isinstance(result.total_segments_emitted, int)
        assert isinstance(result.max_actual_chord_error_mm, float)
        assert isinstance(result.expansion_ratio, float)
        assert isinstance(result.honest_caveat, str)
        assert len(result.honest_caveat) > 50  # substantive caveat

    def test_honest_caveat_mentions_modal(self):
        spec = ArcLinearizeSpec(gcode_text="G21\n")
        result = linearize_arcs(spec)
        assert "modal" in result.honest_caveat.lower()

    def test_honest_caveat_mentions_g17(self):
        spec = ArcLinearizeSpec(gcode_text="G21\n")
        result = linearize_arcs(spec)
        # G17 or XY-plane mentioned
        assert "G17" in result.honest_caveat or "XY" in result.honest_caveat


# ---------------------------------------------------------------------------
# 13. Mixed program: G01, G00, and multiple arc types
# ---------------------------------------------------------------------------

class TestMixedProgram:

    def test_mixed_program_only_arcs_replaced(self):
        gcode = (
            "G21 G90\n"
            "G00 X10 Y0 Z5\n"
            "G01 Z0 F100\n"
            "G02 I-10 J0 F300\n"           # arc 1 (full circle)
            "G01 X15 Y0 F200\n"
            "G03 X0 Y15 I-15 J0 F200\n"   # arc 2 (quarter CCW, R=15)
            "G01 X0 Y0 F200\n"
            "M30\n"
        )
        spec = ArcLinearizeSpec(
            gcode_text=gcode,
            max_chord_error_mm=0.025,
            min_segment_length_mm=0.0,
        )
        result = linearize_arcs(spec)

        assert result.num_arcs_processed == 2
        assert _count_g02_g03(result.linearized_gcode) == 0
        # Non-arc lines preserved
        assert "M30" in result.linearized_gcode
        assert "G00 X10 Y0 Z5" in result.linearized_gcode

    def test_expansion_ratio_positive_when_arcs_processed(self):
        gcode = (
            "G21 G90\n"
            "G00 X10 Y0\n"
            "G02 I-10 J0 F300\n"
            "M30\n"
        )
        spec = ArcLinearizeSpec(gcode_text=gcode)
        result = linearize_arcs(spec)
        assert result.expansion_ratio > 1.0  # Always many:1 for valid arcs


# ---------------------------------------------------------------------------
# 14. Small radius arc — verify segment count formula
# ---------------------------------------------------------------------------

class TestSmallRadiusArc:

    def test_small_radius_full_circle(self):
        # R=1mm, eps=0.025 → N = ceil(2π / (2·acos(1 - 0.025/1))) ≈ 25
        R = 1.0
        eps = 0.025
        expected_n = _expected_n_full_circle(R, eps)
        gcode = (
            f"G21 G90\n"
            f"G00 X{R} Y0\n"
            f"G02 I{-R} J0 F200\n"
            f"M30\n"
        )
        spec = ArcLinearizeSpec(
            gcode_text=gcode,
            max_chord_error_mm=eps,
            min_segment_length_mm=0.0,
        )
        result = linearize_arcs(spec)
        assert result.num_arcs_processed == 1
        assert result.total_segments_emitted == expected_n
        assert result.max_actual_chord_error_mm <= eps + 1e-9
