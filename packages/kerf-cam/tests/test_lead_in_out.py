"""
Tests for kerf_cam.lead_in_out — G-code lead-in/lead-out segments.

References
----------
* Machinery's Handbook 31e §1131 — Cutter entry strategies (tangent arc entry)
* Fanuc Operator Manual §G41/G42 — Cutter compensation

Run:
    pytest packages/kerf-cam/tests/test_lead_in_out.py -v
"""

from __future__ import annotations

import asyncio
import json
import math
import re

import pytest

from kerf_cam.lead_in_out import (
    LeadSpec,
    LeadResult,
    _fmt,
    _normalise,
    _arc_ij,
    _arc_length,
    _rotate_90_ccw,
    _rotate_90_cw,
    _rotate_deg,
    _compute_arc_lead_in,
    generate_lead_in_out,
    cam_generate_lead_in_out_spec,
    run_cam_generate_lead_in_out,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spec(
    lead_type: str = "arc",
    lead_angle_deg: float = 90.0,
    lead_radius_mm: float = 5.0,
    contour_start_xy: tuple = (10.0, 20.0),
    contour_tangent_xy: tuple = (1.0, 0.0),  # +X direction
    cutter_diameter_mm: float = 10.0,
    feed_mm_per_min: float = 500.0,
) -> LeadSpec:
    return LeadSpec(
        contour_start_xy=contour_start_xy,
        contour_tangent_xy=contour_tangent_xy,
        cutter_diameter_mm=cutter_diameter_mm,
        lead_radius_mm=lead_radius_mm,
        lead_angle_deg=lead_angle_deg,
        feed_mm_per_min=feed_mm_per_min,
        lead_type=lead_type,
    )


def _ctx():
    from kerf_cam._compat import ProjectCtx
    return ProjectCtx()


def _run_async(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. Arc lead-in r=5 mm, 90°: check G02/G03, I/J correctness
# ---------------------------------------------------------------------------

class TestArcLeadIn90:
    """Arc lead-in with 90° sweep angle: classic perpendicular tangent entry."""

    def test_g41_emits_g03(self):
        """G41 (left) lead-in arc must use G03 (CCW)."""
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G41")
        assert "G03" in result.gcode_lead_in

    def test_g42_emits_g02(self):
        """G42 (right) lead-in arc must use G02 (CW)."""
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G42")
        assert "G02" in result.gcode_lead_in

    def test_arc_ends_at_contour_start(self):
        """The G03/G02 arc destination must be the contour start (X10 Y20)."""
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G41")
        # Arc line must contain X10 Y20 (the contour start)
        arc_line = [l for l in result.gcode_lead_in.splitlines()
                    if "G03" in l or "G02" in l][0]
        assert "X10.0" in arc_line
        assert "Y20.0" in arc_line

    def test_arc_90_i_j_correct_g41(self):
        """For G41, 90° arc, +X tangent: arc start = (10, 15), centre = (10, 20).
        I = 0, J = 5.0  (centre offset from arc start).
        """
        # Tangent = (1, 0), normal G41 = (0, 1) (CCW rotation)
        # Centre C = (10, 20) + 5*(0,1) = (10, 25)
        # Arc start Q: rotate (P-C) = (0,-5) by +90° CCW → (5, 0), then Q = (15, 25)
        # I = Cx - Qx = 10 - 15 = -5, J = Cy - Qy = 25 - 25 = 0
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G41")
        arc_line = [l for l in result.gcode_lead_in.splitlines()
                    if "G03" in l][0]
        assert "I-5.0" in arc_line
        assert "J0.0" in arc_line

    def test_arc_90_i_j_correct_g42(self):
        """For G42, 90° arc, +X tangent: similar geometry but mirrored.
        Normal G42 = (0,-1), Centre = (10, 15).
        Arc start Q: rotate (P-C)=(0,5) by -90° → (5,0), Q=(15, 15).
        I = 10-15 = -5, J = 15-15 = 0.
        """
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G42")
        arc_line = [l for l in result.gcode_lead_in.splitlines()
                    if "G02" in l][0]
        assert "I-5.0" in arc_line
        assert "J0.0" in arc_line

    def test_arc_lead_in_length_matches_formula(self):
        """Lead-in length must equal R * theta (arc length formula)."""
        R = 5.0
        alpha = 90.0
        expected = _arc_length(R, alpha)  # R * pi/2
        result = generate_lead_in_out(_spec("arc", alpha, R), cutter_comp="G41")
        assert abs(result.lead_in_length_mm - expected) < 1e-6

    def test_arc_lead_out_length_equals_lead_in_length(self):
        """Lead-out length must equal lead-in length (symmetric geometry)."""
        result = generate_lead_in_out(_spec("arc", 90.0, 5.0), cutter_comp="G41")
        assert abs(result.lead_in_length_mm - result.lead_out_length_mm) < 1e-9


# ---------------------------------------------------------------------------
# 2. Arc lead-in at 45° (non-orthogonal sweep)
# ---------------------------------------------------------------------------

class TestArcLeadIn45:
    def test_arc_45_lead_in_length(self):
        """45° arc: lead-in length = R * pi/4."""
        R = 8.0
        alpha = 45.0
        expected = _arc_length(R, alpha)
        result = generate_lead_in_out(_spec("arc", alpha, R), cutter_comp="G41")
        assert abs(result.lead_in_length_mm - expected) < 1e-6

    def test_arc_45_g03_present(self):
        result = generate_lead_in_out(_spec("arc", 45.0, 8.0), cutter_comp="G41")
        assert "G03" in result.gcode_lead_in

    def test_arc_45_arc_destination_is_contour_start(self):
        px, py = 0.0, 0.0
        s = _spec("arc", 45.0, 8.0,
                  contour_start_xy=(px, py),
                  contour_tangent_xy=(1.0, 0.0))
        result = generate_lead_in_out(s, cutter_comp="G41")
        arc_line = [l for l in result.gcode_lead_in.splitlines()
                    if "G03" in l][0]
        assert "X0.0" in arc_line
        assert "Y0.0" in arc_line


# ---------------------------------------------------------------------------
# 3. Line lead-in
# ---------------------------------------------------------------------------

class TestLineLead:
    def test_line_lead_in_emits_g01(self):
        result = generate_lead_in_out(_spec("line"), cutter_comp="G41")
        assert "G01" in result.gcode_lead_in

    def test_line_lead_in_ends_at_contour_start(self):
        result = generate_lead_in_out(_spec("line",
                                            contour_start_xy=(5.0, 7.0),
                                            contour_tangent_xy=(1.0, 0.0)),
                                      cutter_comp="G41")
        g01_line = [l for l in result.gcode_lead_in.splitlines()
                    if "G01" in l][0]
        assert "X5.0" in g01_line
        assert "Y7.0" in g01_line

    def test_line_lead_in_start_behind_tangent(self):
        """Line lead-in start must be P_c - R*t̂ (directly behind along tangent)."""
        R = 6.0
        px, py = 10.0, 20.0
        tx, ty = 1.0, 0.0  # +X tangent
        result = generate_lead_in_out(
            _spec("line", lead_radius_mm=R,
                  contour_start_xy=(px, py),
                  contour_tangent_xy=(tx, ty)),
            cutter_comp="G41"
        )
        # Start should be at (px - R, py) = (4.0, 20.0)
        g00_line = [l for l in result.gcode_lead_in.splitlines()
                    if "G00" in l][0]
        assert "X4.0" in g00_line
        assert "Y20.0" in g00_line

    def test_line_lead_in_length_equals_radius(self):
        R = 7.0
        result = generate_lead_in_out(_spec("line", lead_radius_mm=R), cutter_comp="G41")
        assert abs(result.lead_in_length_mm - R) < 1e-9

    def test_line_lead_out_length_equals_radius(self):
        R = 7.0
        result = generate_lead_in_out(_spec("line", lead_radius_mm=R), cutter_comp="G42")
        assert abs(result.lead_out_length_mm - R) < 1e-9

    def test_line_activates_cutter_comp(self):
        """G41 must appear in the lead-in block."""
        result = generate_lead_in_out(_spec("line"), cutter_comp="G41")
        assert "G41" in result.gcode_lead_in

    def test_line_lead_out_cancels_cutter_comp(self):
        """G40 must appear in the lead-out block."""
        result = generate_lead_in_out(_spec("line"), cutter_comp="G41")
        assert "G40" in result.gcode_lead_out


# ---------------------------------------------------------------------------
# 4. Perpendicular lead-in
# ---------------------------------------------------------------------------

class TestPerpendicularLead:
    def test_perp_lead_in_emits_g01(self):
        result = generate_lead_in_out(_spec("perpendicular"), cutter_comp="G41")
        assert "G01" in result.gcode_lead_in

    def test_perp_g41_approaches_from_left(self):
        """G41 perpendicular: approach from left of tangent (+Y side for +X tangent)."""
        R = 5.0
        px, py = 0.0, 0.0
        tx, ty = 1.0, 0.0  # +X tangent
        result = generate_lead_in_out(
            _spec("perpendicular", lead_radius_mm=R,
                  contour_start_xy=(px, py),
                  contour_tangent_xy=(tx, ty)),
            cutter_comp="G41"
        )
        # Normal for G41 (CCW rotate +X) = (0, 1), so start = (0, 5)
        g00_line = [l for l in result.gcode_lead_in.splitlines()
                    if "G00" in l][0]
        assert "X0.0" in g00_line
        assert "Y5.0" in g00_line

    def test_perp_g42_approaches_from_right(self):
        """G42 perpendicular: approach from right of tangent (-Y side for +X tangent)."""
        R = 5.0
        px, py = 0.0, 0.0
        tx, ty = 1.0, 0.0
        result = generate_lead_in_out(
            _spec("perpendicular", lead_radius_mm=R,
                  contour_start_xy=(px, py),
                  contour_tangent_xy=(tx, ty)),
            cutter_comp="G42"
        )
        g00_line = [l for l in result.gcode_lead_in.splitlines()
                    if "G00" in l][0]
        assert "X0.0" in g00_line
        assert "Y-5.0" in g00_line

    def test_perp_lead_in_length_equals_radius(self):
        R = 4.0
        result = generate_lead_in_out(_spec("perpendicular", lead_radius_mm=R), cutter_comp="G41")
        assert abs(result.lead_in_length_mm - R) < 1e-9

    def test_perp_lead_out_cancels_comp(self):
        result = generate_lead_in_out(_spec("perpendicular"), cutter_comp="G41")
        assert "G40" in result.gcode_lead_out


# ---------------------------------------------------------------------------
# 5. Cutter comp G41 vs G42
# ---------------------------------------------------------------------------

class TestCutterComp:
    def test_g41_in_lead_in_block(self):
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G41")
        assert "G41" in result.gcode_lead_in

    def test_g42_in_lead_in_block(self):
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G42")
        assert "G42" in result.gcode_lead_in

    def test_g40_in_lead_out_block_g41(self):
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G41")
        assert "G40" in result.gcode_lead_out

    def test_g40_in_lead_out_block_g42(self):
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G42")
        assert "G40" in result.gcode_lead_out

    def test_invalid_cutter_comp_raises(self):
        with pytest.raises(ValueError, match="G41.*G42"):
            generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G43")

    def test_lead_out_arc_direction_reversed_g41(self):
        """Lead-out arc must be G02 (opposite of G03 lead-in) for G41."""
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G41")
        assert "G02" in result.gcode_lead_out

    def test_lead_out_arc_direction_reversed_g42(self):
        """Lead-out arc must be G03 (opposite of G02 lead-in) for G42."""
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G42")
        assert "G03" in result.gcode_lead_out


# ---------------------------------------------------------------------------
# 6. Arc length matches R*theta within 1e-6
# ---------------------------------------------------------------------------

class TestArcLengthPrecision:
    @pytest.mark.parametrize("R,alpha", [
        (5.0, 90.0),
        (3.0, 45.0),
        (10.0, 60.0),
        (1.0, 15.0),
        (7.5, 80.0),
    ])
    def test_arc_length_formula(self, R, alpha):
        """lead_in_length_mm must equal R * radians(alpha) within 1e-6."""
        expected = R * math.radians(alpha)
        result = generate_lead_in_out(_spec("arc", alpha, R), cutter_comp="G41")
        assert abs(result.lead_in_length_mm - expected) < 1e-6, (
            f"R={R}, alpha={alpha}: expected {expected}, got {result.lead_in_length_mm}"
        )

    def test_arc_length_symmetric_lead_in_out(self):
        """lead_in_length_mm == lead_out_length_mm for all arc cases."""
        for R, alpha in [(5.0, 90.0), (8.0, 45.0), (3.0, 30.0)]:
            result = generate_lead_in_out(_spec("arc", alpha, R), cutter_comp="G41")
            assert abs(result.lead_in_length_mm - result.lead_out_length_mm) < 1e-9, (
                f"R={R}, alpha={alpha}: in={result.lead_in_length_mm}, "
                f"out={result.lead_out_length_mm}"
            )


# ---------------------------------------------------------------------------
# 7. Feed rate appears in arc/line blocks
# ---------------------------------------------------------------------------

class TestFeedRate:
    def test_feed_rate_in_arc_lead_in(self):
        result = generate_lead_in_out(_spec("arc", 90.0, feed_mm_per_min=800.0),
                                      cutter_comp="G41")
        assert "F800.0" in result.gcode_lead_in

    def test_feed_rate_in_line_lead_in(self):
        result = generate_lead_in_out(_spec("line", feed_mm_per_min=600.0),
                                      cutter_comp="G41")
        assert "F600.0" in result.gcode_lead_in

    def test_feed_rate_in_perp_lead_in(self):
        result = generate_lead_in_out(_spec("perpendicular", feed_mm_per_min=400.0),
                                      cutter_comp="G41")
        assert "F400.0" in result.gcode_lead_in


# ---------------------------------------------------------------------------
# 8. Validation errors
# ---------------------------------------------------------------------------

class TestValidation:
    def test_zero_lead_radius_raises(self):
        with pytest.raises(ValueError, match="lead_radius_mm"):
            LeadSpec((0, 0), (1, 0), 10.0, 0.0, 90.0, 500.0, "arc")

    def test_invalid_lead_type_raises(self):
        with pytest.raises(ValueError, match="lead_type"):
            LeadSpec((0, 0), (1, 0), 10.0, 5.0, 90.0, 500.0, "helix")

    def test_zero_feed_raises(self):
        with pytest.raises(ValueError, match="feed_mm_per_min"):
            LeadSpec((0, 0), (1, 0), 10.0, 5.0, 90.0, 0.0, "arc")

    def test_zero_tangent_raises(self):
        with pytest.raises(ValueError, match="contour_tangent_xy"):
            LeadSpec((0, 0), (0, 0), 10.0, 5.0, 90.0, 500.0, "arc")

    def test_arc_angle_zero_raises(self):
        with pytest.raises(ValueError, match="lead_angle_deg"):
            LeadSpec((0, 0), (1, 0), 10.0, 5.0, 0.0, 500.0, "arc")

    def test_arc_angle_over_90_raises(self):
        with pytest.raises(ValueError, match="lead_angle_deg"):
            LeadSpec((0, 0), (1, 0), 10.0, 5.0, 91.0, 500.0, "arc")


# ---------------------------------------------------------------------------
# 9. LLM tool (async round-trip)
# ---------------------------------------------------------------------------

class TestLLMTool:
    def test_llm_tool_arc_returns_ok(self):
        payload = json.dumps({
            "contour_start_xy": [10.0, 20.0],
            "contour_tangent_xy": [1.0, 0.0],
            "cutter_diameter_mm": 10.0,
            "lead_radius_mm": 5.0,
            "lead_angle_deg": 90.0,
            "feed_mm_per_min": 500.0,
            "lead_type": "arc",
            "cutter_comp": "G41",
        }).encode()
        result_str = _run_async(run_cam_generate_lead_in_out(_ctx(), payload))
        result = json.loads(result_str)
        assert "gcode_lead_in" in result
        assert "gcode_lead_out" in result
        assert "lead_in_length_mm" in result
        assert "honest_caveat" in result

    def test_llm_tool_bad_args_returns_error(self):
        payload = b"not json"
        result_str = _run_async(run_cam_generate_lead_in_out(_ctx(), payload))
        result = json.loads(result_str)
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_llm_tool_missing_field_returns_error(self):
        # Missing contour_start_xy
        payload = json.dumps({
            "contour_tangent_xy": [1.0, 0.0],
            "cutter_diameter_mm": 10.0,
            "lead_radius_mm": 5.0,
            "lead_angle_deg": 90.0,
            "feed_mm_per_min": 500.0,
            "lead_type": "arc",
        }).encode()
        result_str = _run_async(run_cam_generate_lead_in_out(_ctx(), payload))
        result = json.loads(result_str)
        assert "error" in result

    def test_llm_tool_arc_length_matches_formula(self):
        R = 6.0
        alpha = 90.0
        payload = json.dumps({
            "contour_start_xy": [0.0, 0.0],
            "contour_tangent_xy": [1.0, 0.0],
            "cutter_diameter_mm": 12.0,
            "lead_radius_mm": R,
            "lead_angle_deg": alpha,
            "feed_mm_per_min": 500.0,
            "lead_type": "arc",
        }).encode()
        result_str = _run_async(run_cam_generate_lead_in_out(_ctx(), payload))
        result = json.loads(result_str)
        expected = R * math.radians(alpha)
        assert abs(result["lead_in_length_mm"] - expected) < 1e-6

    def test_llm_tool_spec_has_required_fields(self):
        """ToolSpec must list all required input fields."""
        required = cam_generate_lead_in_out_spec.input_schema.get("required", [])
        for field_name in [
            "contour_start_xy", "contour_tangent_xy", "cutter_diameter_mm",
            "lead_radius_mm", "lead_angle_deg", "feed_mm_per_min", "lead_type",
        ]:
            assert field_name in required, f"Missing required field: {field_name}"


# ---------------------------------------------------------------------------
# 10. Arc geometry invariants (non-normalised tangent input)
# ---------------------------------------------------------------------------

class TestNonUnitTangent:
    def test_non_unit_tangent_normalised(self):
        """A tangent vector with magnitude != 1 must still produce the same geometry."""
        s1 = _spec("arc", 90.0, 5.0,
                   contour_tangent_xy=(1.0, 0.0))
        s2 = _spec("arc", 90.0, 5.0,
                   contour_tangent_xy=(10.0, 0.0))  # same direction, ×10
        r1 = generate_lead_in_out(s1, cutter_comp="G41")
        r2 = generate_lead_in_out(s2, cutter_comp="G41")
        assert abs(r1.lead_in_length_mm - r2.lead_in_length_mm) < 1e-9

    def test_diagonal_tangent_arc_length(self):
        """45°-diagonal tangent: arc length still = R * radians(alpha)."""
        R = 5.0
        alpha = 90.0
        s = _spec("arc", alpha, R, contour_tangent_xy=(1.0, 1.0))  # 45° diagonal
        result = generate_lead_in_out(s, cutter_comp="G41")
        expected = _arc_length(R, alpha)
        assert abs(result.lead_in_length_mm - expected) < 1e-6


# ---------------------------------------------------------------------------
# 11. Honest caveat always present
# ---------------------------------------------------------------------------

class TestHonestCaveat:
    def test_arc_caveat_mentions_2d(self):
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G41")
        assert "2D" in result.honest_caveat or "2d" in result.honest_caveat.lower()

    def test_arc_caveat_mentions_ij_convention(self):
        result = generate_lead_in_out(_spec("arc", 90.0), cutter_comp="G41")
        assert "I/J" in result.honest_caveat or "incremental" in result.honest_caveat.lower()

    def test_line_caveat_present(self):
        result = generate_lead_in_out(_spec("line"), cutter_comp="G41")
        assert len(result.honest_caveat) > 20
