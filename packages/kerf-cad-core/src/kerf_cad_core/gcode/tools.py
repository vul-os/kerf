"""
kerf_cad_core.gcode.tools — LLM tool wrappers for G-code post-processing.

Registers tools with the Kerf tool registry:

  gcode_parse          — parse a G-code program to segment list
  gcode_stats          — toolpath length, air-move totals, segment counts
  gcode_cycle_time     — estimated cycle time (trapezoidal feed model)
  gcode_bounding_box   — axis-aligned bounding box of the toolpath
  gcode_clamp_feedrate — clamp all feed rates to [f_min, f_max]
  gcode_override_feedrate — scale all feed rates by a factor
  gcode_expand_drills  — expand G81/G82/G83 drill cycles to explicit moves
  gcode_transform      — translate/rotate/scale/mirror a program
  gcode_renumber       — strip and re-number all N-words
  gcode_backplot       — sample toolpath as (x,y,z) point list

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.gcode.post import (
    parse_gcode,
    toolpath_stats,
    cycle_time,
    bounding_box,
    clamp_feedrate,
    override_feedrate,
    expand_drill_cycles,
    transform_program,
    renumber_lines,
    backplot_points,
)


# ---------------------------------------------------------------------------
# Tool: gcode_parse
# ---------------------------------------------------------------------------

_gcode_parse_spec = ToolSpec(
    name="gcode_parse",
    description=(
        "Parse a G-code program string into a structured segment list.\n"
        "\n"
        "The parser tracks modal state (G0/1/2/3, G17-19, G20/21, G90/91, "
        "F/S/T/M) and returns each block as an absolute-endpoint segment.\n"
        "Arc segments (G2/G3) are chord-segmented into polylines within the "
        "given chord_tol.\n"
        "\n"
        "Returns: {ok, segments[], warnings[], units, final_pos, line_count}.\n"
        "Errors/unsupported codes go into warnings; never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode": {
                "type": "string",
                "description": "Raw G-code program text.",
            },
            "chord_tol": {
                "type": "number",
                "description": (
                    "Arc → polyline chord tolerance (same units as program, "
                    "default 0.01)."
                ),
            },
        },
        "required": ["gcode"],
    },
)


@register(_gcode_parse_spec, write=False)
async def run_gcode_parse(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    gcode = a.get("gcode")
    if not gcode or not isinstance(gcode, str):
        return json.dumps({"ok": False, "reason": "gcode is required (string)"})

    chord_tol = float(a.get("chord_tol", 0.01))
    try:
        result = parse_gcode(gcode, chord_tol=chord_tol)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: gcode_stats
# ---------------------------------------------------------------------------

_gcode_stats_spec = ToolSpec(
    name="gcode_stats",
    description=(
        "Compute toolpath statistics from a G-code program.\n"
        "\n"
        "Reports total toolpath length, feed-move length, rapid (air-move) "
        "length, arc length, segment counts and tool-change count.\n"
        "\n"
        "Returns: {ok, total_length, feed_length, rapid_length, arc_length, "
        "segment_count, feed_count, rapid_count, arc_count, tool_changes}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode": {
                "type": "string",
                "description": "Raw G-code program text.",
            },
            "chord_tol": {
                "type": "number",
                "description": "Arc chord tolerance (default 0.01).",
            },
        },
        "required": ["gcode"],
    },
)


@register(_gcode_stats_spec, write=False)
async def run_gcode_stats(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    gcode = a.get("gcode")
    if not gcode or not isinstance(gcode, str):
        return json.dumps({"ok": False, "reason": "gcode is required (string)"})

    chord_tol = float(a.get("chord_tol", 0.01))
    try:
        parsed = parse_gcode(gcode, chord_tol=chord_tol)
        result = toolpath_stats(parsed["segments"])
        result["warnings"] = parsed["warnings"]
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: gcode_cycle_time
# ---------------------------------------------------------------------------

_gcode_cycle_time_spec = ToolSpec(
    name="gcode_cycle_time",
    description=(
        "Estimate machining cycle time for a G-code program.\n"
        "\n"
        "Uses a trapezoidal accel/decel feed model: each move ramps up to the "
        "programmed feed rate, cruises, then decelerates.\n"
        "\n"
        "Parameters:\n"
        "  rapid_rate — machine rapid traverse rate (mm/min, default 10000)\n"
        "  accel      — axis acceleration (mm/s², default 500)\n"
        "\n"
        "Returns: {ok, total_s, feed_s, rapid_s, arc_s} (all in seconds)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode": {
                "type": "string",
                "description": "Raw G-code program text.",
            },
            "rapid_rate": {
                "type": "number",
                "description": "Rapid traverse rate (mm/min, default 10000).",
            },
            "accel": {
                "type": "number",
                "description": "Axis acceleration (mm/s², default 500).",
            },
        },
        "required": ["gcode"],
    },
)


@register(_gcode_cycle_time_spec, write=False)
async def run_gcode_cycle_time(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    gcode = a.get("gcode")
    if not gcode or not isinstance(gcode, str):
        return json.dumps({"ok": False, "reason": "gcode is required (string)"})

    rapid_rate = float(a.get("rapid_rate", 10000.0))
    accel = float(a.get("accel", 500.0))

    try:
        parsed = parse_gcode(gcode)
        result = cycle_time(parsed["segments"], rapid_rate=rapid_rate, accel=accel)
        result["warnings"] = parsed["warnings"]
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: gcode_bounding_box
# ---------------------------------------------------------------------------

_gcode_bbox_spec = ToolSpec(
    name="gcode_bounding_box",
    description=(
        "Compute the axis-aligned bounding box of a G-code toolpath.\n"
        "\n"
        "Returns: {ok, xmin, xmax, ymin, ymax, zmin, zmax, dx, dy, dz}.\n"
        "All values in program units (mm or inches)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode": {
                "type": "string",
                "description": "Raw G-code program text.",
            },
        },
        "required": ["gcode"],
    },
)


@register(_gcode_bbox_spec, write=False)
async def run_gcode_bounding_box(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    gcode = a.get("gcode")
    if not gcode or not isinstance(gcode, str):
        return json.dumps({"ok": False, "reason": "gcode is required (string)"})

    try:
        parsed = parse_gcode(gcode)
        result = bounding_box(parsed["segments"])
        result["warnings"] = parsed["warnings"]
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: gcode_clamp_feedrate
# ---------------------------------------------------------------------------

_gcode_clamp_spec = ToolSpec(
    name="gcode_clamp_feedrate",
    description=(
        "Clamp all feed rates in a G-code program to [f_min, f_max].\n"
        "\n"
        "Rapid segments are unaffected (they run at machine rapid rate).\n"
        "Returns the modified G-code segment list and statistics.\n"
        "\n"
        "Returns: {ok, segments[], stats{}}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode": {
                "type": "string",
                "description": "Raw G-code program text.",
            },
            "f_min": {
                "type": "number",
                "description": "Minimum feed rate (mm/min or in/min).",
            },
            "f_max": {
                "type": "number",
                "description": "Maximum feed rate (mm/min or in/min).",
            },
        },
        "required": ["gcode", "f_min", "f_max"],
    },
)


@register(_gcode_clamp_spec, write=False)
async def run_gcode_clamp_feedrate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    gcode = a.get("gcode")
    if not gcode or not isinstance(gcode, str):
        return json.dumps({"ok": False, "reason": "gcode is required (string)"})
    if a.get("f_min") is None:
        return json.dumps({"ok": False, "reason": "f_min is required"})
    if a.get("f_max") is None:
        return json.dumps({"ok": False, "reason": "f_max is required"})

    f_min = float(a["f_min"])
    f_max = float(a["f_max"])
    if f_min > f_max:
        return json.dumps({"ok": False, "reason": "f_min must be <= f_max"})

    try:
        parsed = parse_gcode(gcode)
        clamped = clamp_feedrate(parsed["segments"], f_min, f_max)
        stats = toolpath_stats(clamped)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload({"ok": True, "segments": clamped, "stats": stats})


# ---------------------------------------------------------------------------
# Tool: gcode_override_feedrate
# ---------------------------------------------------------------------------

_gcode_override_spec = ToolSpec(
    name="gcode_override_feedrate",
    description=(
        "Scale all feed rates in a G-code program by a factor.\n"
        "\n"
        "factor=0.8 applies 80% feed override.  Rapid moves are unaffected.\n"
        "\n"
        "Returns: {ok, segments[], stats{}}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode": {
                "type": "string",
                "description": "Raw G-code program text.",
            },
            "factor": {
                "type": "number",
                "description": "Feed rate scale factor (e.g. 0.8 for 80% override). Must be > 0.",
            },
        },
        "required": ["gcode", "factor"],
    },
)


@register(_gcode_override_spec, write=False)
async def run_gcode_override_feedrate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    gcode = a.get("gcode")
    if not gcode or not isinstance(gcode, str):
        return json.dumps({"ok": False, "reason": "gcode is required (string)"})
    if a.get("factor") is None:
        return json.dumps({"ok": False, "reason": "factor is required"})

    factor = float(a["factor"])
    if factor <= 0:
        return json.dumps({"ok": False, "reason": "factor must be > 0"})

    try:
        parsed = parse_gcode(gcode)
        overridden = override_feedrate(parsed["segments"], factor)
        stats = toolpath_stats(overridden)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload({"ok": True, "segments": overridden, "stats": stats})


# ---------------------------------------------------------------------------
# Tool: gcode_expand_drills
# ---------------------------------------------------------------------------

_gcode_expand_drills_spec = ToolSpec(
    name="gcode_expand_drills",
    description=(
        "Expand G81/G82/G83 canned drill cycles to explicit G0/G1 moves.\n"
        "\n"
        "G81: drill to depth, retract.\n"
        "G82: drill to depth, dwell, retract.\n"
        "G83: peck drilling with chip-clearing retracts (Q peck increment).\n"
        "\n"
        "Returns: {ok, segments[], stats{}}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode": {
                "type": "string",
                "description": "Raw G-code program text.",
            },
        },
        "required": ["gcode"],
    },
)


@register(_gcode_expand_drills_spec, write=False)
async def run_gcode_expand_drills(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    gcode = a.get("gcode")
    if not gcode or not isinstance(gcode, str):
        return json.dumps({"ok": False, "reason": "gcode is required (string)"})

    try:
        parsed = parse_gcode(gcode)
        expanded = expand_drill_cycles(parsed["segments"])
        stats = toolpath_stats(expanded)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload({"ok": True, "segments": expanded, "stats": stats, "warnings": parsed["warnings"]})


# ---------------------------------------------------------------------------
# Tool: gcode_transform
# ---------------------------------------------------------------------------

_gcode_transform_spec = ToolSpec(
    name="gcode_transform",
    description=(
        "Apply a coordinate transform to a G-code toolpath.\n"
        "\n"
        "Operations applied in order: scale → mirror → rotate (about Z) → translate.\n"
        "\n"
        "Parameters:\n"
        "  translate   — [dx, dy, dz] offset\n"
        "  rotate_deg  — rotation about Z-axis (degrees CCW, default 0)\n"
        "  scale       — uniform scale factor (default 1.0)\n"
        "  mirror_axis — 'X', 'Y', 'Z', or null\n"
        "\n"
        "Returns: {ok, segments[], stats{}}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode": {
                "type": "string",
                "description": "Raw G-code program text.",
            },
            "translate": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "[dx, dy, dz] translation (default [0,0,0]).",
            },
            "rotate_deg": {
                "type": "number",
                "description": "Rotation about Z-axis (degrees CCW, default 0).",
            },
            "scale": {
                "type": "number",
                "description": "Uniform scale factor (default 1.0). Must be > 0.",
            },
            "mirror_axis": {
                "type": "string",
                "enum": ["X", "Y", "Z"],
                "description": "Mirror about this axis (optional).",
            },
        },
        "required": ["gcode"],
    },
)


@register(_gcode_transform_spec, write=False)
async def run_gcode_transform(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    gcode = a.get("gcode")
    if not gcode or not isinstance(gcode, str):
        return json.dumps({"ok": False, "reason": "gcode is required (string)"})

    t = a.get("translate", [0.0, 0.0, 0.0])
    if not (isinstance(t, (list, tuple)) and len(t) == 3):
        return json.dumps({"ok": False, "reason": "translate must be [dx, dy, dz]"})

    rotate_deg = float(a.get("rotate_deg", 0.0))
    scale = float(a.get("scale", 1.0))
    if scale <= 0:
        return json.dumps({"ok": False, "reason": "scale must be > 0"})
    mirror_axis = a.get("mirror_axis", None)

    try:
        parsed = parse_gcode(gcode)
        transformed = transform_program(
            parsed["segments"],
            translate=(float(t[0]), float(t[1]), float(t[2])),
            rotate_deg=rotate_deg,
            scale=scale,
            mirror_axis=mirror_axis,
        )
        stats = toolpath_stats(transformed)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload({"ok": True, "segments": transformed, "stats": stats})


# ---------------------------------------------------------------------------
# Tool: gcode_renumber
# ---------------------------------------------------------------------------

_gcode_renumber_spec = ToolSpec(
    name="gcode_renumber",
    description=(
        "Strip existing N-words and re-number all non-blank G-code blocks.\n"
        "\n"
        "Parameters:\n"
        "  start — first line number (default 10)\n"
        "  step  — increment (default 10)\n"
        "\n"
        "Returns: {ok, gcode} where gcode is the renumbered program string."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode": {
                "type": "string",
                "description": "Raw G-code program text.",
            },
            "start": {
                "type": "integer",
                "description": "First line number (default 10).",
            },
            "step": {
                "type": "integer",
                "description": "Line number increment (default 10).",
            },
        },
        "required": ["gcode"],
    },
)


@register(_gcode_renumber_spec, write=False)
async def run_gcode_renumber(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    gcode = a.get("gcode")
    if not gcode or not isinstance(gcode, str):
        return json.dumps({"ok": False, "reason": "gcode is required (string)"})

    start = int(a.get("start", 10))
    step = int(a.get("step", 10))
    if step <= 0:
        return json.dumps({"ok": False, "reason": "step must be > 0"})

    try:
        result = renumber_lines(gcode, start=start, step=step)
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload({"ok": True, "gcode": result})


# ---------------------------------------------------------------------------
# Tool: gcode_backplot
# ---------------------------------------------------------------------------

_gcode_backplot_spec = ToolSpec(
    name="gcode_backplot",
    description=(
        "Sample a G-code toolpath as a flat list of (x, y, z) points for "
        "back-plotting.\n"
        "\n"
        "Arc segments are sampled via their chord-segmented polylines.\n"
        "Rapid moves are included in the path.\n"
        "\n"
        "Parameters:\n"
        "  max_points — maximum number of points (default 500, -1 for unlimited)\n"
        "\n"
        "Returns: {ok, points: [[x,y,z], ...]}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "gcode": {
                "type": "string",
                "description": "Raw G-code program text.",
            },
            "max_points": {
                "type": "integer",
                "description": "Max sample points (default 500, -1 = unlimited).",
            },
            "chord_tol": {
                "type": "number",
                "description": "Arc chord tolerance (default 0.01).",
            },
        },
        "required": ["gcode"],
    },
)


@register(_gcode_backplot_spec, write=False)
async def run_gcode_backplot(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    gcode = a.get("gcode")
    if not gcode or not isinstance(gcode, str):
        return json.dumps({"ok": False, "reason": "gcode is required (string)"})

    max_points = int(a.get("max_points", 500))
    chord_tol = float(a.get("chord_tol", 0.01))

    try:
        parsed = parse_gcode(gcode, chord_tol=chord_tol)
        pts = backplot_points(parsed["segments"], max_points=max_points if max_points > 0 else 0)
        # convert to list-of-list for JSON serialisation
        pts_list = [[p[0], p[1], p[2]] for p in pts]
    except Exception as exc:
        return json.dumps({"ok": False, "reason": str(exc)})

    return ok_payload({"ok": True, "points": pts_list, "count": len(pts_list)})
