"""
kerf_cad_core.civil.plan_profile_sheet_tools — LLM tool wrapper for
plan-and-profile sheet generation.

Registers one tool with the Kerf tool registry:

  civil_plan_profile_sheet — Generate a plan-and-profile SVG sheet for a
                              road or utility alignment per ASCE Manual 21
                              and AASHTO Green Book (2018) §3.

Input: alignment geometry (station/x/y/elevation tuples) + sheet spec.
Output: {ok, sheet_id, svg, plan_view_bbox, profile_view_bbox, stations_labeled}.

The SVG is a full 24×36-inch (ANSI_D/ARCH_D) sheet in landscape orientation:
  • Top 60% : Plan view (X-Y, north up, alignment polyline + station ticks)
  • Bottom 40% : Profile view (station vs elevation, vertical exaggeration,
                 grid, grade line)
  • Bottom strip: Title block (ASCE Manual 21 §3.4 fields)

All tools are pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: ...} — never raises.
Units: caller's choice (ft or m; consistent with alignment_geometry).
Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.civil.plan_profile_sheet import (
    PlanProfileSpec,
    generate_plan_profile_sheet,
)


# ---------------------------------------------------------------------------
# Tool: civil_plan_profile_sheet
# ---------------------------------------------------------------------------

_sheet_spec = ToolSpec(
    name="civil_plan_profile_sheet",
    description=(
        "Generate a plan-and-profile SVG sheet for a road or utility alignment.\n"
        "\n"
        "Sheet layout (ASCE Manual 21 §3.4 / AASHTO Green Book 2018 §3):\n"
        "  Top 60%   — Plan view: X-Y bird's-eye, alignment polyline, "
        "station tick marks, north arrow.\n"
        "  Bottom 40% — Profile view: station (x-axis) vs elevation (y-axis) "
        "with vertical exaggeration, horizontal station grid, elevation grid, "
        "ground-line polyline.\n"
        "  Bottom strip — Title block: alignment ID, scale, sheet size, stations.\n"
        "\n"
        "Sheet sizes:\n"
        "  'ANSI_D'  — 24×36 inches (standard civil drawing, landscape)\n"
        "  'ARCH_D'  — 24×36 inches (same canvas; different border notation)\n"
        "\n"
        "Vertical exaggeration (AASHTO §3): profile_view_scale_v is the V:H "
        "ratio applied to the elevation axis.  Typical value = 10 (10× exag).\n"
        "\n"
        "Returns {ok, sheet_id, svg, plan_view_bbox, profile_view_bbox, "
        "stations_labeled}.\n"
        "  svg                  : Full SVG string (write to .svg file)\n"
        "  plan_view_bbox       : [x, y, width, height] in SVG pixels\n"
        "  profile_view_bbox    : [x, y, width, height] in SVG pixels\n"
        "  stations_labeled     : list of station values that received labels\n"
        "\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alignment_id": {
                "type": "string",
                "description": "Alignment identifier (e.g. 'Main St — Sta 0+00 to 10+00').",
            },
            "alignment_geometry": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                    "description": "[station, x, y, elevation] tuple.",
                },
                "description": (
                    "List of [station, x, y, elevation] tuples along the alignment. "
                    "station and coordinates should be in consistent units (ft or m). "
                    "Minimum 2 points required."
                ),
                "minItems": 2,
            },
            "station_start": {
                "type": "number",
                "description": "Starting station value (ft or m).",
            },
            "station_end": {
                "type": "number",
                "description": "Ending station value (ft or m).",
            },
            "plan_view_scale": {
                "type": "number",
                "description": "Plan view scale denominator (e.g. 50 → 1″=50′).",
                "default": 50,
            },
            "profile_view_scale_h": {
                "type": "number",
                "description": "Profile horizontal scale denominator (e.g. 50 → 1″=50′).",
                "default": 50,
            },
            "profile_view_scale_v": {
                "type": "number",
                "description": (
                    "Profile vertical exaggeration factor (V:H ratio). "
                    "AASHTO recommends 10 for typical road profiles."
                ),
                "default": 10,
            },
            "sheet_size": {
                "type": "string",
                "enum": ["ANSI_D", "ARCH_D"],
                "description": "Sheet size: 'ANSI_D' or 'ARCH_D' (both 24×36 inches).",
                "default": "ANSI_D",
            },
            "grid_interval": {
                "type": "number",
                "description": "Station grid interval in the same units as station values. Default 50.",
                "default": 50,
            },
        },
        "required": [
            "alignment_id",
            "alignment_geometry",
            "station_start",
            "station_end",
        ],
    },
)


@register(_sheet_spec, write=False)
async def run_civil_plan_profile_sheet(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    alignment_id = a.get("alignment_id")
    if not alignment_id:
        return json.dumps({"ok": False, "reason": "alignment_id is required"})

    raw_geom = a.get("alignment_geometry")
    if not raw_geom or len(raw_geom) < 2:
        return json.dumps({"ok": False, "reason": "alignment_geometry must have at least 2 points"})

    try:
        geom: list[tuple[float, float, float, float]] = [
            (float(pt[0]), float(pt[1]), float(pt[2]), float(pt[3]))
            for pt in raw_geom
        ]
    except (TypeError, IndexError, ValueError) as exc:
        return json.dumps({"ok": False, "reason": f"alignment_geometry parse error: {exc}"})

    try:
        station_start = float(a.get("station_start", geom[0][0]))
        station_end = float(a.get("station_end", geom[-1][0]))
        plan_scale = float(a.get("plan_view_scale", 50))
        prof_scale_h = float(a.get("profile_view_scale_h", 50))
        prof_scale_v = float(a.get("profile_view_scale_v", 10))
        grid_interval = float(a.get("grid_interval", 50))
    except (TypeError, ValueError) as exc:
        return json.dumps({"ok": False, "reason": f"numeric parse error: {exc}"})

    sheet_size = str(a.get("sheet_size", "ANSI_D"))

    spec = PlanProfileSpec(
        alignment_id=alignment_id,
        station_start=station_start,
        station_end=station_end,
        plan_view_scale=plan_scale,
        profile_view_scale_h=prof_scale_h,
        profile_view_scale_v=prof_scale_v,
        sheet_size=sheet_size,
        grid_interval_ft=grid_interval,
    )

    sheet = generate_plan_profile_sheet(geom, spec)

    return ok_payload({
        "ok": True,
        "sheet_id": sheet.sheet_id,
        "svg": sheet.svg,
        "plan_view_bbox": list(sheet.plan_view_bbox),
        "profile_view_bbox": list(sheet.profile_view_bbox),
        "stations_labeled": sheet.stations_labeled,
        "note": (
            "SVG sheet per ASCE Manual 21 §3.4 / AASHTO Green Book (2018) §3. "
            f"Sheet: {sheet_size} (24×36 in, landscape). "
            f"Plan scale 1″={plan_scale:.0f}, "
            f"Profile V.E. {prof_scale_v:.0f}×."
        ),
    })
