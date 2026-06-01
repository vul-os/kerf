"""
kerf_cad_core.civil.corridor_sheet_tools
=========================================
LLM tool wrapper for Civil 3D-style automated plan + profile + cross-section
sheet generation.

Registers one tool with the Kerf tool registry:

  civil_generate_corridor_sheets
      Generate a multi-sheet DXF from a corridor specification.  Produces:
        - Plan view: horizontal alignment centreline + edge strings + station ticks
        - Profile view: vertical alignment (FG) + existing ground + grade stubs
        - Cross-section views at each sampled station: carriageway + cut/fill slopes

Returns {ok, dxf_path, num_sheets, stations_drawn, total_length_m, honest_caveat}.

Units: metres.  DXF format: AutoCAD R12/R14 ASCII.
Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.civil.corridor_sheet_generator import (
    CorridorSheetSpec,
    CorridorSpec,
    HorizontalAlignmentSpec,
    VerticalAlignmentSpec,
    generate_corridor_sheets,
)

# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_SPEC = ToolSpec(
    name="civil_generate_corridor_sheets",
    description=(
        "Generate plan + profile + cross-section sheets for a road/rail corridor "
        "and export them as a multi-sheet DXF file (AutoCAD R12/R14 ASCII).\n"
        "\n"
        "Output sheet types\n"
        "------------------\n"
        "  Plan view        — horizontal alignment centreline (layer "
        "CIVIL-PLAN-ALIGN), edge strings at half_carriageway_m offset "
        "(CIVIL-PLAN-EDGE), station tick marks (CIVIL-PLAN-STATION).\n"
        "  Profile view     — finished-grade polyline (CIVIL-PROFILE-FG), "
        "existing-ground polyline (CIVIL-PROFILE-EG), grade stubs "
        "(CIVIL-PROFILE-GRADE).\n"
        "  Cross-sections   — one per station_interval_m: carriageway "
        "(CIVIL-XS-ROAD), cut/fill side-slopes (CIVIL-XS-SLOPE), existing "
        "ground stub (CIVIL-XS-GROUND).\n"
        "\n"
        "All DXF coordinates are in metres.  No BLOCKS or PAPER_SPACE section; "
        "everything is in MODEL space so any DXF reader (QCAD, LibreCAD, AutoCAD, "
        "BricsCAD) can open the file directly.\n"
        "\n"
        "Limitations\n"
        "-----------\n"
        "  - Existing-ground line is synthetic (sinusoidal).  Replace with "
        "    surveyed DTM points for production drawings.\n"
        "  - Vertical alignment uses linear PVI interpolation; parabolic vertical "
        "    curves are not applied inside the sheet generator (use "
        "    align_vertical to verify K-values separately).\n"
        "  - Text annotations / title blocks are not written (DXF MTEXT/TEXT "
        "    not yet implemented).\n"
        "\n"
        "Returns {ok, dxf_path, num_sheets, stations_drawn, total_length_m, "
        "honest_caveat}. Never raises; errors returned as {ok: false, errors: [...]}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "corridor_name": {
                "type": "string",
                "description": "Name of the corridor (used in DXF layer prefix).",
            },
            "start_station_m": {
                "type": "number",
                "description": "Start station of the corridor in metres.  Default: 0.0.",
            },
            "end_station_m": {
                "type": "number",
                "description": "End station of the corridor in metres (must be > start_station_m).",
            },
            "station_interval_m": {
                "type": "number",
                "description": (
                    "Interval between cross-section stations (metres).  "
                    "Default: 20.0.  Smaller = more cross-sections."
                ),
            },
            "scale_horizontal": {
                "type": "number",
                "description": (
                    "Nominal horizontal plot scale factor (e.g. 200 → 1:200).  "
                    "Controls sheet viewport size.  Default: 200."
                ),
            },
            "scale_vertical": {
                "type": "number",
                "description": (
                    "Nominal vertical scale factor for the profile view "
                    "(e.g. 50 → 1:50).  Informational only.  Default: 50."
                ),
            },
            "half_carriageway_m": {
                "type": "number",
                "description": (
                    "Half-width of the carriageway from centreline (metres).  "
                    "Default: 3.65 m (one AASHTO/TRH4 lane)."
                ),
            },
            "cut_slope_ratio": {
                "type": "number",
                "description": (
                    "Cut side-slope ratio H:V (horizontal run per 1 m vertical).  "
                    "Default: 1.5 (1.5H:1V)."
                ),
            },
            "fill_slope_ratio": {
                "type": "number",
                "description": (
                    "Fill side-slope ratio H:V.  Default: 2.0 (2H:1V)."
                ),
            },
            "design_elevation_at_start_m": {
                "type": "number",
                "description": (
                    "Design surface elevation at the start station (metres).  "
                    "Used when no PVI data is supplied.  Default: 100.0."
                ),
            },
            "horizontal_waypoints": {
                "type": "array",
                "description": (
                    "Horizontal alignment centreline as [[easting, northing], ...] "
                    "in metres.  Leave empty or omit for a straight alignment "
                    "along the +X axis."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                },
            },
            "pvi_stations": {
                "type": "array",
                "description": (
                    "Stations of vertical alignment PVI points (metres), in "
                    "ascending order."
                ),
                "items": {"type": "number"},
            },
            "pvi_elevations": {
                "type": "array",
                "description": (
                    "Elevations at each PVI point (metres).  Must have the same "
                    "length as pvi_stations."
                ),
                "items": {"type": "number"},
            },
            "output_path": {
                "type": "string",
                "description": (
                    "Full path for the output DXF file.  If empty or omitted, "
                    "a temporary file is created and its path is returned."
                ),
            },
        },
        "required": ["end_station_m"],
    },
)


# ---------------------------------------------------------------------------
# Tool runner
# ---------------------------------------------------------------------------

@register(_SPEC, write=True)
async def run_civil_generate_corridor_sheets(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    errors: list[str] = []

    # end_station_m is required
    end_station_raw = a.get("end_station_m")
    if end_station_raw is None:
        return json.dumps({"ok": False, "errors": ["end_station_m is required"]})

    try:
        end_station_m = float(end_station_raw)
    except (TypeError, ValueError) as exc:
        return json.dumps({"ok": False, "errors": [f"end_station_m must be a number: {exc}"]})

    start_station_m = float(a.get("start_station_m", 0.0))
    if end_station_m <= start_station_m:
        return json.dumps({"ok": False, "errors": [
            f"end_station_m ({end_station_m}) must be > start_station_m ({start_station_m})"
        ]})

    station_interval_m = float(a.get("station_interval_m", 20.0))
    if station_interval_m <= 0:
        return json.dumps({"ok": False, "errors": [
            f"station_interval_m must be > 0; got {station_interval_m}"
        ]})

    # Optional numeric fields
    scale_horizontal = float(a.get("scale_horizontal", 200.0))
    scale_vertical = float(a.get("scale_vertical", 50.0))
    half_carriageway_m = float(a.get("half_carriageway_m", 3.65))
    cut_slope_ratio = float(a.get("cut_slope_ratio", 1.5))
    fill_slope_ratio = float(a.get("fill_slope_ratio", 2.0))
    design_elevation_at_start_m = float(a.get("design_elevation_at_start_m", 100.0))
    corridor_name = str(a.get("corridor_name", "CORRIDOR"))
    output_path = str(a.get("output_path", ""))

    # Parse horizontal waypoints
    raw_wp = a.get("horizontal_waypoints", [])
    waypoints: list[tuple[float, float]] = []
    if isinstance(raw_wp, list):
        for pt in raw_wp:
            if isinstance(pt, (list, tuple)) and len(pt) >= 2:
                try:
                    waypoints.append((float(pt[0]), float(pt[1])))
                except (TypeError, ValueError) as exc:
                    errors.append(f"horizontal_waypoints parse error: {exc}")
                    break

    # Parse PVI data
    pvi_stations_raw = a.get("pvi_stations", [])
    pvi_elevations_raw = a.get("pvi_elevations", [])

    pvi_stations: list[float] = []
    pvi_elevations: list[float] = []

    if pvi_stations_raw:
        try:
            pvi_stations = [float(v) for v in pvi_stations_raw]
        except (TypeError, ValueError) as exc:
            errors.append(f"pvi_stations parse error: {exc}")

    if pvi_elevations_raw:
        try:
            pvi_elevations = [float(v) for v in pvi_elevations_raw]
        except (TypeError, ValueError) as exc:
            errors.append(f"pvi_elevations parse error: {exc}")

    if pvi_stations and pvi_elevations and len(pvi_stations) != len(pvi_elevations):
        errors.append(
            f"pvi_stations length ({len(pvi_stations)}) must match "
            f"pvi_elevations length ({len(pvi_elevations)})"
        )

    if errors:
        return json.dumps({"ok": False, "errors": errors})

    # Build spec
    horiz = HorizontalAlignmentSpec(waypoints=waypoints)
    vert = VerticalAlignmentSpec(pvi_stations=pvi_stations, pvi_elevations=pvi_elevations)
    corridor = CorridorSpec(
        name=corridor_name,
        start_station_m=start_station_m,
        end_station_m=end_station_m,
        horizontal=horiz,
        vertical=vert,
        half_carriageway_m=half_carriageway_m,
        cut_slope_ratio=cut_slope_ratio,
        fill_slope_ratio=fill_slope_ratio,
        design_elevation_at_start_m=design_elevation_at_start_m,
    )
    sheet_spec = CorridorSheetSpec(
        corridor=corridor,
        station_interval_m=station_interval_m,
        scale_horizontal=scale_horizontal,
        scale_vertical=scale_vertical,
        output_path=output_path,
    )

    try:
        result = generate_corridor_sheets(sheet_spec)
    except Exception as exc:
        return json.dumps({"ok": False, "errors": [f"sheet generation error: {exc}"]})

    return ok_payload({
        "ok": True,
        "dxf_path": result.dxf_path,
        "num_sheets": result.num_sheets,
        "stations_drawn": result.stations_drawn,
        "total_length_m": result.total_length_m,
        "honest_caveat": result.honest_caveat,
    })
