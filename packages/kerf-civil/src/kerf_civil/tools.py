"""
kerf_civil LLM tools — CRS transform + TIN terrain.

Registered via plugin.py at startup.
"""

from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_civil._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# civil_crs_transform
# ---------------------------------------------------------------------------

civil_crs_transform_spec = ToolSpec(
    name="civil_crs_transform",
    description=(
        "Transform geographic or projected coordinates between two coordinate "
        "reference systems (CRS). Supports EPSG codes (e.g. 4326 for WGS-84, "
        "32634 for UTM zone 34N). Returns transformed (x, y) and round-trip error."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "x": {
                "oneOf": [
                    {"type": "number"},
                    {"type": "array", "items": {"type": "number"}},
                ],
                "description": "X coordinate(s) — longitude (degrees) for geographic CRS, easting (m) for projected.",
            },
            "y": {
                "oneOf": [
                    {"type": "number"},
                    {"type": "array", "items": {"type": "number"}},
                ],
                "description": "Y coordinate(s) — latitude (degrees) for geographic CRS, northing (m) for projected.",
            },
            "from_crs": {
                "type": ["integer", "string"],
                "description": "Source CRS — EPSG integer or 'EPSG:NNNN' string.",
            },
            "to_crs": {
                "type": ["integer", "string"],
                "description": "Target CRS — EPSG integer or 'EPSG:NNNN' string.",
            },
            "z": {
                "oneOf": [
                    {"type": "number"},
                    {"type": "array", "items": {"type": "number"}},
                    {"type": "null"},
                ],
                "description": "Optional elevation(s) in metres.",
            },
        },
        "required": ["x", "y", "from_crs", "to_crs"],
    },
)


async def run_civil_crs_transform(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.crs import transform, round_trip_error

        x = args["x"]
        y = args["y"]
        from_crs = args["from_crs"]
        to_crs = args["to_crs"]
        z = args.get("z")

        result = transform(x, y, from_crs, to_crs, z=z)
        err = round_trip_error(x, y, from_crs, to_crs, z=z)

        if z is not None:
            x_out, y_out, z_out = result
        else:
            x_out, y_out = result
            z_out = None

        payload: dict[str, Any] = {
            "x": x_out,
            "y": y_out,
            "round_trip_error_m": err,
        }
        if z_out is not None:
            payload["z"] = z_out

        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "CRS_ERROR")


# ---------------------------------------------------------------------------
# civil_tin_build
# ---------------------------------------------------------------------------

civil_tin_build_spec = ToolSpec(
    name="civil_tin_build",
    description=(
        "Build a Triangulated Irregular Network (TIN) terrain model from survey "
        "points, then extract contour lines at a given interval. Returns triangle "
        "count, area, and contour polylines."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "Array of [x, y, z] survey points (projected metres + elevation).",
                "minItems": 3,
            },
            "contour_interval": {
                "type": "number",
                "description": "Contour interval in metres. Default 1.0.",
            },
            "datum_z": {
                "type": "number",
                "description": "Datum elevation for volume_above calculation (m). Default 0.",
            },
        },
        "required": ["points"],
    },
)


async def run_civil_tin_build(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.tin import build_tin, contours, area_2d, volume_above

        raw_pts = args["points"]
        interval = float(args.get("contour_interval", 1.0))
        datum_z = float(args.get("datum_z", 0.0))

        tin = build_tin(raw_pts)
        cnt = contours(tin, interval)
        a2d = area_2d(tin)
        vol = volume_above(tin, datum_z)

        # Serialise contour polylines (cap at 500 points total for LLM context)
        serialised = []
        total_pts = 0
        for line in cnt:
            if total_pts >= 500:
                break
            sl = line[: max(1, 500 - total_pts)]
            serialised.append([[round(p[0], 4), round(p[1], 4), round(p[2], 4)] for p in sl])
            total_pts += len(sl)

        payload = {
            "triangle_count": len(tin.triangles),
            "point_count": len(tin.points),
            "area_m2": round(a2d, 4),
            "volume_above_datum_m3": round(vol, 4),
            "contour_count": len(cnt),
            "contours": serialised,
        }
        return ok_payload(payload)
    except Exception as exc:
        return err_payload(str(exc), "TIN_ERROR")
