"""
kerf_mold.wire_edm_tool — LLM tool wrapper for wire EDM G-code generation.

Tool: mold_generate_wire_edm_gcode
  Generate Fanuc-dialect wire EDM G-code for a 2-D profile with G41/G42
  cutter compensation, and optional 4-axis taper (XY + UV).

References:
  ISO 14117:2018 — Wire EDM geometric tolerances and process conventions.
  Fanuc Wire-Cut EDM manual B-59064EN/01.
  Hassan, A., Boothroyd, G. (1989). §14.3.

Wave 9C: Cimatron mold base + EDM electrode + wire EDM
"""
from __future__ import annotations

from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_mold._compat import ToolSpec, err_payload, ok_payload, ProjectCtx

from kerf_mold.wire_edm import (
    WireEdmPath,
    WireEdmGcode,
    generate_wire_edm_gcode,
    rectangular_profile,
    circular_profile,
)


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

mold_generate_wire_edm_gcode_spec = ToolSpec(
    name="mold_generate_wire_edm_gcode",
    description=(
        "Generate Fanuc-dialect wire EDM G-code for a 2-D profile.\n\n"
        "Emits G41/G42 cutter compensation (D-register = wire_radius + spark_gap), "
        "G01 linear and G02/G03 arc interpolation, M50/M51 wire feed, "
        "and a straight lead-in to activate compensation safely.\n\n"
        "Profile segments (profile_2d): list of segment tuples:\n"
        "  [\"line\",    x, y]           — linear cut to (x, y)\n"
        "  [\"arc_cw\",  x, y, cx, cy]   — CW arc to (x,y), centre (cx,cy)\n"
        "  [\"arc_ccw\", x, y, cx, cy]   — CCW arc to (x,y), centre (cx,cy)\n"
        "Coordinates in mm.\n\n"
        "Taper cutting (taper_angle_deg > 0):\n"
        "  Emits 4-axis G-code (XY + UV simultaneous moves).\n"
        "  UV = lower guide offset = workpiece_height × tan(taper_angle).\n"
        "  ISO 14117:2018 §7.3.\n\n"
        "Returns: {ok, gcode, total_path_length_mm, estimated_time_min, "
        "cutting_speed_mm_per_min, compensation_radius_mm, is_taper, honest_caveat}.\n\n"
        "D-register value must be set in the controller's D01 offset register "
        "before running.\n\n"
        "HONEST: One-pass program; no skim cuts. Taper is radial approximation. "
        "Verify on machine before production cutting.\n\n"
        "Refs: ISO 14117:2018; Fanuc B-59064EN/01; Hassan-Boothroyd 1989 §14."
    ),
    input_schema={
        "type": "object",
        "required": ["profile_2d", "start_xy"],
        "properties": {
            "profile_2d": {
                "type": "array",
                "description": (
                    "Profile segments. Each segment is a list:\n"
                    "  [\"line\", x, y]\n"
                    "  [\"arc_cw\",  x, y, cx, cy]\n"
                    "  [\"arc_ccw\", x, y, cx, cy]\n"
                    "Coordinates in mm. Minimum 1 segment."
                ),
                "items": {"type": "array"},
                "minItems": 1,
            },
            "start_xy": {
                "type": "array",
                "description": "Starting [x, y] position (mm).",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
            "wire_diameter_mm": {
                "type": "number",
                "description": "Wire diameter (mm). Default 0.25 mm.",
                "default": 0.25,
                "exclusiveMinimum": 0,
            },
            "spark_gap_mm": {
                "type": "number",
                "description": "One-sided spark gap (mm). Default 0.025 mm.",
                "default": 0.025,
                "minimum": 0,
            },
            "offset_direction": {
                "type": "string",
                "enum": ["left", "right"],
                "description": "Compensation side: 'left'→G41, 'right'→G42. Default 'left'.",
                "default": "left",
            },
            "taper_angle_deg": {
                "type": "number",
                "description": (
                    "Taper half-angle in degrees. 0 = straight 2-axis cut. "
                    "> 0 = 4-axis taper (XY + UV). ISO 14117:2018 §7.3. Default 0."
                ),
                "default": 0.0,
                "minimum": 0,
            },
            "workpiece_height_mm": {
                "type": "number",
                "description": (
                    "Workpiece thickness (mm) — used for UV taper offset calculation "
                    "when taper_angle_deg > 0. Default 50 mm."
                ),
                "default": 50.0,
                "exclusiveMinimum": 0,
            },
            "feedrate_mm_per_min": {
                "type": "number",
                "description": (
                    "Wire traverse speed (mm/min). Default 8.0 mm/min. "
                    "Hassan-Boothroyd 1989 §14.3: typical 5–15 mm/min (25 mm steel, 0.25 mm wire)."
                ),
                "default": 8.0,
                "exclusiveMinimum": 0,
            },
            "lead_in_mm": {
                "type": "number",
                "description": "Lead-in straight length (mm). Default 2.0 mm.",
                "default": 2.0,
                "exclusiveMinimum": 0,
            },
        },
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

async def run_mold_generate_wire_edm_gcode(
    args: dict[str, Any], ctx: "ProjectCtx"
) -> str:
    """Execute wire EDM G-code generation and return a JSON string."""
    try:
        raw_profile = args.get("profile_2d")
        if raw_profile is None:
            return err_payload("profile_2d is required", "BAD_ARGS")
        if not isinstance(raw_profile, list) or len(raw_profile) < 1:
            return err_payload("profile_2d must be a non-empty list of segments", "BAD_ARGS")

        raw_start = args.get("start_xy")
        if raw_start is None:
            return err_payload("start_xy is required", "BAD_ARGS")
        try:
            start_xy = (float(raw_start[0]), float(raw_start[1]))
        except Exception as exc:
            return err_payload(f"start_xy invalid: {exc}", "BAD_ARGS")

        try:
            profile = [tuple(s) for s in raw_profile]
        except Exception as exc:
            return err_payload(f"profile_2d parsing failed: {exc}", "BAD_ARGS")

        path = WireEdmPath(
            profile=profile,
            start_xy=start_xy,
            wire_diameter_mm=float(args.get("wire_diameter_mm", 0.25)),
            spark_gap_mm=float(args.get("spark_gap_mm", 0.025)),
            offset_direction=str(args.get("offset_direction", "left")),
            taper_angle_deg=float(args.get("taper_angle_deg", 0.0)),
            workpiece_height_mm=float(args.get("workpiece_height_mm", 50.0)),
            feedrate_mm_per_min=float(args.get("feedrate_mm_per_min", 8.0)),
            lead_in_mm=float(args.get("lead_in_mm", 2.0)),
        )

        result: WireEdmGcode = generate_wire_edm_gcode(path)

        return ok_payload({
            "ok": True,
            "gcode": result.gcode,
            "total_path_length_mm": result.total_path_length_mm,
            "estimated_time_min": result.estimated_time_min,
            "cutting_speed_mm_per_min": result.cutting_speed_mm_per_min,
            "compensation_radius_mm": result.compensation_radius_mm,
            "is_taper": result.is_taper,
            "honest_caveat": result.honest_caveat,
            "reference": (
                "ISO 14117:2018 — Wire EDM geometric tolerances. "
                "Fanuc Wire-Cut EDM manual B-59064EN/01. "
                "Hassan, A., Boothroyd, G. (1989). Fundamentals of Machining, §14."
            ),
        })

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "WIRE_EDM_ERROR")
