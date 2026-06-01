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
    compute_helical_ramp_points,
    compute_ramp_on_points,
    compute_arc_tangent_points,
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


# ---------------------------------------------------------------------------
# 12. Helical-ramp lead-in
# ---------------------------------------------------------------------------

def _spec_helical(
    R: float = 5.0,
    ramp_angle_deg: float = 3.0,
    target_z_mm: float = -5.0,
    num_turns: int = 1,
    pts_per_turn: int = 36,
    contour_start_xy: tuple = (10.0, 0.0),
    contour_tangent_xy: tuple = (1.0, 0.0),
) -> LeadSpec:
    return LeadSpec(
        contour_start_xy=contour_start_xy,
        contour_tangent_xy=contour_tangent_xy,
        cutter_diameter_mm=10.0,
        lead_radius_mm=R,
        lead_angle_deg=90.0,  # not used for helical-ramp
        feed_mm_per_min=400.0,
        lead_type="helical-ramp",
        target_z_mm=target_z_mm,
        ramp_angle_deg=ramp_angle_deg,
        num_helix_turns=num_turns,
        helix_points_per_turn=pts_per_turn,
    )


class TestHelicalRamp:
    def test_helical_ramp_result_type(self):
        """generate_lead_in_out returns LeadResult for helical-ramp."""
        result = generate_lead_in_out(_spec_helical(), cutter_comp="G41")
        assert isinstance(result, LeadResult)

    def test_helical_ramp_has_toolpath_points(self):
        """lead_in_toolpath_points must be non-empty and contain 3-tuples."""
        result = generate_lead_in_out(_spec_helical(), cutter_comp="G41")
        pts = result.lead_in_toolpath_points
        assert len(pts) > 0
        assert len(pts[0]) == 3, f"Expected 3-tuple (x,y,z), got {pts[0]}"

    def test_helical_ramp_z_decreases_over_revolution(self):
        """Over one full revolution the Z coordinate must strictly decrease from
        z_start to target_z_mm (pitch_per_turn > 0)."""
        target_z = -4.0
        result = generate_lead_in_out(
            _spec_helical(R=5.0, ramp_angle_deg=3.0, target_z_mm=target_z, num_turns=1),
            cutter_comp="G41",
        )
        pts = result.lead_in_toolpath_points
        z_values = [p[2] for p in pts]
        # First Z > last Z (descent)
        assert z_values[0] > z_values[-1], (
            f"Expected z_start > z_end; got z_start={z_values[0]}, z_end={z_values[-1]}"
        )
        # Last Z must equal target_z_mm within tolerance
        assert abs(z_values[-1] - target_z) < 1e-6, (
            f"Last Z should be target_z={target_z}, got {z_values[-1]}"
        )

    def test_helical_ramp_z_descent_monotone(self):
        """Z must decrease monotonically (not increase) along the helix."""
        result = generate_lead_in_out(
            _spec_helical(R=4.0, ramp_angle_deg=5.0, target_z_mm=-3.0, num_turns=2),
            cutter_comp="G41",
        )
        pts = result.lead_in_toolpath_points
        z_vals = [p[2] for p in pts]
        for i in range(1, len(z_vals)):
            assert z_vals[i] <= z_vals[i - 1] + 1e-10, (
                f"Z not monotone at index {i}: z[{i}]={z_vals[i]} > z[{i-1}]={z_vals[i-1]}"
            )

    def test_helical_ramp_pitch_matches_formula(self):
        """pitch_per_turn = 2π × R × tan(angle); verify via Z span."""
        R = 6.0
        angle_deg = 4.0
        target_z = 0.0
        n_turns = 1
        spec = _spec_helical(R=R, ramp_angle_deg=angle_deg, target_z_mm=target_z, num_turns=n_turns)
        result = generate_lead_in_out(spec, cutter_comp="G41")
        pts = result.lead_in_toolpath_points
        z_start = pts[0][2]
        z_end = pts[-1][2]
        z_span = abs(z_start - z_end)
        expected_pitch = 2.0 * math.pi * R * math.tan(math.radians(angle_deg))
        assert abs(z_span - expected_pitch * n_turns) < 1e-6, (
            f"Z span {z_span} should equal pitch × turns = {expected_pitch * n_turns}"
        )

    def test_helical_ramp_xy_radius_constant(self):
        """All XY points must lie on a circle of radius R from the helix centre."""
        R = 5.0
        spec = _spec_helical(R=R, ramp_angle_deg=3.0, target_z_mm=0.0)
        result = generate_lead_in_out(spec, cutter_comp="G41")
        pts = result.lead_in_toolpath_points
        # Get centre from result
        cx, cy = result.arc_centre_xy
        for x, y, z in pts:
            dist = math.hypot(x - cx, y - cy)
            assert abs(dist - R) < 1e-6, (
                f"Point ({x},{y}) is {dist:.6f} mm from centre, expected R={R}"
            )

    def test_helical_ramp_lead_out_ascends(self):
        """Lead-out toolpath must go from target_z back up to z_start."""
        target_z = -3.0
        result = generate_lead_in_out(
            _spec_helical(R=5.0, ramp_angle_deg=3.0, target_z_mm=target_z),
            cutter_comp="G41",
        )
        out_pts = result.lead_out_toolpath_points
        assert out_pts[0][2] <= out_pts[-1][2], (
            f"Lead-out should ascend: z_start={out_pts[0][2]}, z_end={out_pts[-1][2]}"
        )

    def test_helical_ramp_gcode_mentions_pitch(self):
        """Lead-in G-code comment must mention pitch_angle."""
        result = generate_lead_in_out(_spec_helical(), cutter_comp="G41")
        assert "pitch_angle" in result.gcode_lead_in or "helical" in result.gcode_lead_in.lower()

    def test_helical_ramp_lead_in_length_positive(self):
        """lead_in_length_mm must be > 0."""
        result = generate_lead_in_out(_spec_helical(), cutter_comp="G41")
        assert result.lead_in_length_mm > 0.0

    def test_helical_ramp_multi_turn_more_points(self):
        """2-turn helix must have approximately 2× the points of 1-turn."""
        r1 = generate_lead_in_out(_spec_helical(num_turns=1, pts_per_turn=36), cutter_comp="G41")
        r2 = generate_lead_in_out(_spec_helical(num_turns=2, pts_per_turn=36), cutter_comp="G41")
        assert len(r2.lead_in_toolpath_points) > len(r1.lead_in_toolpath_points)

    def test_helical_ramp_validation_bad_ramp_angle(self):
        """ramp_angle_deg > 45 must raise ValueError."""
        with pytest.raises(ValueError, match="ramp_angle_deg"):
            LeadSpec(
                contour_start_xy=(0, 0), contour_tangent_xy=(1, 0),
                cutter_diameter_mm=10.0, lead_radius_mm=5.0,
                lead_angle_deg=90.0, feed_mm_per_min=500.0,
                lead_type="helical-ramp",
                ramp_angle_deg=50.0,
            )

    def test_helical_ramp_validation_zero_turns(self):
        """num_helix_turns < 1 must raise ValueError."""
        with pytest.raises(ValueError, match="num_helix_turns"):
            LeadSpec(
                contour_start_xy=(0, 0), contour_tangent_xy=(1, 0),
                cutter_diameter_mm=10.0, lead_radius_mm=5.0,
                lead_angle_deg=90.0, feed_mm_per_min=500.0,
                lead_type="helical-ramp",
                num_helix_turns=0,
            )


# ---------------------------------------------------------------------------
# 13. Ramp-on lead-in
# ---------------------------------------------------------------------------

def _spec_ramp_on(
    depth_mm: float = 5.0,
    ramp_angle_deg: float = 5.0,
    target_z_mm: float = -5.0,
    contour_start_xy: tuple = (10.0, 0.0),
    contour_tangent_xy: tuple = (1.0, 0.0),
) -> LeadSpec:
    return LeadSpec(
        contour_start_xy=contour_start_xy,
        contour_tangent_xy=contour_tangent_xy,
        cutter_diameter_mm=10.0,
        lead_radius_mm=depth_mm,
        lead_angle_deg=90.0,  # not used for ramp-on
        feed_mm_per_min=400.0,
        lead_type="ramp-on",
        target_z_mm=target_z_mm,
        ramp_angle_deg=ramp_angle_deg,
    )


class TestRampOn:
    def test_ramp_on_has_two_toolpath_points(self):
        """Ramp-on lead-in must have exactly 2 toolpath points (start, end)."""
        result = generate_lead_in_out(_spec_ramp_on(), cutter_comp="G41")
        assert len(result.lead_in_toolpath_points) == 2

    def test_ramp_on_end_at_contour_start(self):
        """Last toolpath point must be at contour_start_xy at target_z_mm."""
        px, py = 10.0, 0.0
        target_z = -5.0
        result = generate_lead_in_out(
            _spec_ramp_on(target_z_mm=target_z, contour_start_xy=(px, py)),
            cutter_comp="G41",
        )
        last = result.lead_in_toolpath_points[-1]
        assert abs(last[0] - px) < 1e-9
        assert abs(last[1] - py) < 1e-9
        assert abs(last[2] - target_z) < 1e-9

    def test_ramp_on_z_decreases(self):
        """Z must decrease from start to end of lead-in."""
        result = generate_lead_in_out(_spec_ramp_on(), cutter_comp="G41")
        pts = result.lead_in_toolpath_points
        assert pts[0][2] > pts[-1][2], (
            f"Expected z_start > z_end; got {pts[0][2]} vs {pts[-1][2]}"
        )

    def test_ramp_on_xy_length_matches_formula(self):
        """XY ramp length = depth / tan(angle)."""
        depth = 4.0
        angle_deg = 5.0
        px, py = 0.0, 0.0
        result = generate_lead_in_out(
            _spec_ramp_on(depth_mm=depth, ramp_angle_deg=angle_deg,
                          contour_start_xy=(px, py),
                          contour_tangent_xy=(1.0, 0.0)),
            cutter_comp="G41",
        )
        pts = result.lead_in_toolpath_points
        xy_dist = math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1])
        expected = depth / math.tan(math.radians(angle_deg))
        assert abs(xy_dist - expected) < 1e-6, (
            f"XY length {xy_dist} should equal depth/tan(angle) = {expected}"
        )

    def test_ramp_on_3d_path_length(self):
        """3D path length = ramp_xy / cos(angle)."""
        depth = 4.0
        angle_deg = 5.0
        result = generate_lead_in_out(
            _spec_ramp_on(depth_mm=depth, ramp_angle_deg=angle_deg),
            cutter_comp="G41",
        )
        ramp_xy = depth / math.tan(math.radians(angle_deg))
        expected_3d = ramp_xy / math.cos(math.radians(angle_deg))
        assert abs(result.lead_in_length_mm - expected_3d) < 1e-6

    def test_ramp_on_start_behind_contour_along_negative_tangent(self):
        """Ramp start must be behind P_c along -tangent direction."""
        px, py = 0.0, 0.0
        depth = 3.0
        angle_deg = 10.0
        result = generate_lead_in_out(
            _spec_ramp_on(depth_mm=depth, ramp_angle_deg=angle_deg,
                          contour_start_xy=(px, py),
                          contour_tangent_xy=(1.0, 0.0)),
            cutter_comp="G41",
        )
        start = result.lead_in_toolpath_points[0]
        # tangent is (1,0) so ramp start must be at negative x from P_c
        assert start[0] < px, f"Ramp start X {start[0]} should be < P_c X {px}"

    def test_ramp_on_lead_out_ascends(self):
        """Lead-out must ramp upward (last Z > first Z)."""
        result = generate_lead_in_out(_spec_ramp_on(), cutter_comp="G41")
        out_pts = result.lead_out_toolpath_points
        assert out_pts[-1][2] > out_pts[0][2], (
            f"Lead-out should ascend: z_start={out_pts[0][2]}, z_end={out_pts[-1][2]}"
        )

    def test_ramp_on_gcode_mentions_ramp(self):
        """Lead-in G-code comment must mention ramp."""
        result = generate_lead_in_out(_spec_ramp_on(), cutter_comp="G41")
        assert "ramp" in result.gcode_lead_in.lower()

    def test_ramp_on_validation_bad_angle(self):
        """ramp_angle_deg > 45 must raise ValueError."""
        with pytest.raises(ValueError, match="ramp_angle_deg"):
            LeadSpec(
                contour_start_xy=(0, 0), contour_tangent_xy=(1, 0),
                cutter_diameter_mm=10.0, lead_radius_mm=5.0,
                lead_angle_deg=90.0, feed_mm_per_min=500.0,
                lead_type="ramp-on",
                ramp_angle_deg=50.0,
            )

    def test_ramp_on_lead_in_lead_out_lengths_equal(self):
        """lead_in_length_mm == lead_out_length_mm (symmetric ramp)."""
        result = generate_lead_in_out(_spec_ramp_on(), cutter_comp="G41")
        assert abs(result.lead_in_length_mm - result.lead_out_length_mm) < 1e-9


# ---------------------------------------------------------------------------
# 14. Arc-tangent lead-in
# ---------------------------------------------------------------------------

def _spec_arc_tangent(
    R: float = 5.0,
    n_pts: int = 32,
    contour_start_xy: tuple = (10.0, 20.0),
    contour_tangent_xy: tuple = (1.0, 0.0),
) -> LeadSpec:
    return LeadSpec(
        contour_start_xy=contour_start_xy,
        contour_tangent_xy=contour_tangent_xy,
        cutter_diameter_mm=10.0,
        lead_radius_mm=R,
        lead_angle_deg=90.0,  # not used for arc-tangent (always 90°)
        feed_mm_per_min=500.0,
        lead_type="arc-tangent",
        arc_points=n_pts,
    )


class TestArcTangent:
    def test_arc_tangent_has_toolpath_points(self):
        """lead_in_toolpath_points must be non-empty 2-tuples."""
        result = generate_lead_in_out(_spec_arc_tangent(), cutter_comp="G41")
        pts = result.lead_in_toolpath_points
        assert len(pts) > 0
        assert len(pts[0]) == 2, f"Expected 2-tuple (x,y), got {pts[0]}"

    def test_arc_tangent_last_point_is_contour_start(self):
        """Last toolpath point must be contour_start_xy."""
        px, py = 10.0, 20.0
        result = generate_lead_in_out(
            _spec_arc_tangent(contour_start_xy=(px, py)),
            cutter_comp="G41",
        )
        last = result.lead_in_toolpath_points[-1]
        assert abs(last[0] - px) < 1e-6
        assert abs(last[1] - py) < 1e-6

    def test_arc_tangent_arc_centre_populated(self):
        """arc_centre_xy must be a 2-tuple for arc-tangent type."""
        result = generate_lead_in_out(_spec_arc_tangent(), cutter_comp="G41")
        assert result.arc_centre_xy is not None
        assert len(result.arc_centre_xy) == 2

    def test_arc_tangent_arc_radius_equals_spec_radius(self):
        """arc_radius_mm must equal lead_radius_mm."""
        R = 7.0
        result = generate_lead_in_out(_spec_arc_tangent(R=R), cutter_comp="G41")
        assert abs(result.arc_radius_mm - R) < 1e-9

    def test_arc_tangent_all_points_on_circle(self):
        """All toolpath points must lie on the arc circle within tolerance."""
        R = 5.0
        result = generate_lead_in_out(_spec_arc_tangent(R=R, n_pts=64), cutter_comp="G41")
        cx, cy = result.arc_centre_xy
        for x, y in result.lead_in_toolpath_points:
            dist = math.hypot(x - cx, y - cy)
            assert abs(dist - R) < 1e-6, (
                f"Point ({x},{y}) is {dist:.6f} mm from centre, expected R={R}"
            )

    def test_arc_tangent_centre_perpendicular_to_contour_start_g41(self):
        """For G41 +X tangent: arc centre must be directly above P_c (+Y direction)
        by exactly R, i.e. centre = (px, py + R)."""
        R = 5.0
        px, py = 10.0, 20.0
        result = generate_lead_in_out(
            _spec_arc_tangent(R=R, contour_start_xy=(px, py),
                               contour_tangent_xy=(1.0, 0.0)),
            cutter_comp="G41",
        )
        cx, cy = result.arc_centre_xy
        assert abs(cx - px) < 1e-6
        assert abs(cy - (py + R)) < 1e-6

    def test_arc_tangent_arc_length_is_pi_r_over_2(self):
        """90° arc length = R × π/2."""
        R = 6.0
        result = generate_lead_in_out(_spec_arc_tangent(R=R), cutter_comp="G41")
        expected = R * math.pi / 2.0
        assert abs(result.lead_in_length_mm - expected) < 1e-4, (
            f"Arc length {result.lead_in_length_mm} should be π×R/2 = {expected}"
        )

    def test_arc_tangent_lead_out_reversed(self):
        """Lead-out toolpath must be reverse of lead-in toolpath."""
        result = generate_lead_in_out(_spec_arc_tangent(n_pts=16), cutter_comp="G41")
        in_pts = result.lead_in_toolpath_points
        out_pts = result.lead_out_toolpath_points
        assert len(in_pts) == len(out_pts)
        # First point of lead-out == last point of lead-in
        assert abs(out_pts[0][0] - in_pts[-1][0]) < 1e-9
        assert abs(out_pts[0][1] - in_pts[-1][1]) < 1e-9

    def test_arc_tangent_gcode_mentions_centre(self):
        """Lead-in G-code comment must mention centre coordinates."""
        result = generate_lead_in_out(_spec_arc_tangent(), cutter_comp="G41")
        assert "centre" in result.gcode_lead_in.lower() or "center" in result.gcode_lead_in.lower()

    def test_arc_tangent_g40_in_lead_out(self):
        """G40 must appear in lead-out block."""
        result = generate_lead_in_out(_spec_arc_tangent(), cutter_comp="G41")
        assert "G40" in result.gcode_lead_out

    def test_arc_tangent_validation_too_few_arc_points(self):
        """arc_points < 4 must raise ValueError."""
        with pytest.raises(ValueError, match="arc_points"):
            LeadSpec(
                contour_start_xy=(0, 0), contour_tangent_xy=(1, 0),
                cutter_diameter_mm=10.0, lead_radius_mm=5.0,
                lead_angle_deg=90.0, feed_mm_per_min=500.0,
                lead_type="arc-tangent",
                arc_points=2,
            )

    def test_arc_tangent_g42_centre_below_contour_start(self):
        """For G42 +X tangent: arc centre must be directly below P_c (−Y direction)."""
        R = 5.0
        px, py = 10.0, 20.0
        result = generate_lead_in_out(
            _spec_arc_tangent(R=R, contour_start_xy=(px, py),
                               contour_tangent_xy=(1.0, 0.0)),
            cutter_comp="G42",
        )
        cx, cy = result.arc_centre_xy
        assert abs(cx - px) < 1e-6
        assert abs(cy - (py - R)) < 1e-6

    def test_arc_tangent_lead_in_lead_out_lengths_equal(self):
        """lead_in_length_mm == lead_out_length_mm (symmetric arc)."""
        result = generate_lead_in_out(_spec_arc_tangent(), cutter_comp="G41")
        assert abs(result.lead_in_length_mm - result.lead_out_length_mm) < 1e-9


# ---------------------------------------------------------------------------
# 15. LLM tool — new types round-trip
# ---------------------------------------------------------------------------

class TestLLMToolNewTypes:
    def test_llm_tool_helical_ramp_returns_ok(self):
        payload = json.dumps({
            "contour_start_xy": [10.0, 0.0],
            "contour_tangent_xy": [1.0, 0.0],
            "cutter_diameter_mm": 10.0,
            "lead_radius_mm": 5.0,
            "lead_angle_deg": 90.0,
            "feed_mm_per_min": 400.0,
            "lead_type": "helical-ramp",
            "target_z_mm": -5.0,
            "ramp_angle_deg": 3.0,
            "num_helix_turns": 1,
            "cutter_comp": "G41",
        }).encode()
        result_str = _run_async(run_cam_generate_lead_in_out(_ctx(), payload))
        result = json.loads(result_str)
        assert "gcode_lead_in" in result
        assert "lead_in_toolpath_points" in result
        assert len(result["lead_in_toolpath_points"]) > 0

    def test_llm_tool_ramp_on_returns_ok(self):
        payload = json.dumps({
            "contour_start_xy": [0.0, 0.0],
            "contour_tangent_xy": [1.0, 0.0],
            "cutter_diameter_mm": 10.0,
            "lead_radius_mm": 5.0,
            "lead_angle_deg": 90.0,
            "feed_mm_per_min": 400.0,
            "lead_type": "ramp-on",
            "target_z_mm": -5.0,
            "ramp_angle_deg": 5.0,
            "cutter_comp": "G41",
        }).encode()
        result_str = _run_async(run_cam_generate_lead_in_out(_ctx(), payload))
        result = json.loads(result_str)
        assert "gcode_lead_in" in result
        assert "lead_in_toolpath_points" in result
        assert len(result["lead_in_toolpath_points"]) == 2

    def test_llm_tool_arc_tangent_returns_ok(self):
        payload = json.dumps({
            "contour_start_xy": [10.0, 20.0],
            "contour_tangent_xy": [1.0, 0.0],
            "cutter_diameter_mm": 10.0,
            "lead_radius_mm": 5.0,
            "lead_angle_deg": 90.0,
            "feed_mm_per_min": 500.0,
            "lead_type": "arc-tangent",
            "cutter_comp": "G41",
        }).encode()
        result_str = _run_async(run_cam_generate_lead_in_out(_ctx(), payload))
        result = json.loads(result_str)
        assert "gcode_lead_in" in result
        assert "arc_centre_xy" in result
        assert result["arc_centre_xy"] is not None
        assert "arc_radius_mm" in result
        assert abs(result["arc_radius_mm"] - 5.0) < 1e-9

    def test_llm_tool_new_types_in_spec_enum(self):
        """ToolSpec enum for lead_type must include all 6 types."""
        enum_vals = (
            cam_generate_lead_in_out_spec.input_schema["properties"]["lead_type"]["enum"]
        )
        for t in ("arc", "line", "perpendicular", "helical-ramp", "ramp-on", "arc-tangent"):
            assert t in enum_vals, f"lead_type enum missing: {t}"

    def test_llm_tool_helical_ramp_arc_centre_populated(self):
        """helical-ramp result must include arc_centre_xy (helix centre)."""
        payload = json.dumps({
            "contour_start_xy": [10.0, 0.0],
            "contour_tangent_xy": [1.0, 0.0],
            "cutter_diameter_mm": 10.0,
            "lead_radius_mm": 5.0,
            "lead_angle_deg": 90.0,
            "feed_mm_per_min": 400.0,
            "lead_type": "helical-ramp",
            "target_z_mm": 0.0,
            "ramp_angle_deg": 3.0,
        }).encode()
        result_str = _run_async(run_cam_generate_lead_in_out(_ctx(), payload))
        result = json.loads(result_str)
        assert result.get("arc_centre_xy") is not None
