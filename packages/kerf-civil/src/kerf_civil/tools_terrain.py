"""
tools_terrain.py — LLM tools for TIN terrain modelling and CRS coordinate
transforms (coverage sweep 2026-05-25).

Exposes:
  civil_tin_terrain   — Build a Delaunay TIN and extract contours / slope /
                        aspect / volume from survey-point data.
  civil_crs_transform — Transform coordinates between any two CRS identifiers
                        (EPSG codes; WGS-84 ↔ UTM fallback when pyproj absent).
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_civil._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Tool: civil_tin_terrain
# ---------------------------------------------------------------------------

civil_tin_terrain_spec = ToolSpec(
    name="civil_tin_terrain",
    description=(
        "Build a Triangulated Irregular Network (TIN) from survey points and run "
        "terrain analysis.  Supports professional Civil 3D–level TIN operations "
        "including breaklines, boundary trimming, volume between surfaces, and "
        "elevation interpolation.\n"
        "\n"
        "Operations (op field):\n"
        "  'contours'        — extract iso-contour polylines at a given interval.\n"
        "  'stats'           — return area, slope and aspect for every triangle.\n"
        "  'volume'          — volume above a datum elevation.\n"
        "  'volume_between'  — cut/fill volume between two co-registered TINs.\n"
        "  'interpolate_z'   — interpolate surface elevation at a plan point.\n"
        "\n"
        "Parameters\n"
        "----------\n"
        "points        : list of [x, y, z] survey coordinates (min 3)\n"
        "op            : one of 'contours', 'stats', 'volume', 'volume_between', 'interpolate_z'\n"
        "breaklines    : list of [i, j] vertex-index pairs — constrained edges\n"
        "                (ridges, streams, road edges). Enforces edges in triangulation.\n"
        "boundary      : list of [x, y] polygon vertices — trims TIN to survey area.\n"
        "interval      : contour interval in metres (contours op)\n"
        "z_min, z_max  : restrict contour range (optional)\n"
        "datum_z       : datum elevation for volume op\n"
        "points_b      : second surface points [[x,y,z],…] for volume_between op\n"
        "x, y          : plan coordinates for interpolate_z op\n"
        "\n"
        "Returns:\n"
        "  ok              : bool\n"
        "  n_triangles     : int\n"
        "  For 'contours':      polylines (list of [[x,y,z], …])\n"
        "  For 'stats':         triangles list with slope_deg, aspect_deg\n"
        "  For 'volume':        volume_m3 above datum_z\n"
        "  For 'volume_between': cut_m3, fill_m3, net_m3\n"
        "  For 'interpolate_z': z_m (float) or null if outside TIN\n"
        "\n"
        "Reference: Civil 3D TIN surface methodology; Chaudhry (2008);\n"
        "AASHTO GDPS-4-M §2.2.3 earthwork volumes.\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "description": "Survey points as [[x, y, z], …] in metres.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 3,
            },
            "op": {
                "type": "string",
                "enum": ["contours", "stats", "volume", "volume_between", "interpolate_z"],
                "description": "Terrain operation to perform.",
            },
            "breaklines": {
                "type": "array",
                "description": "Constrained edges as [[i, j], …] vertex-index pairs.",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "boundary": {
                "type": "array",
                "description": "Outer boundary polygon as [[x, y], …] vertices.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "interval": {
                "type": "number",
                "description": "Contour interval in metres (required for 'contours' op).",
            },
            "z_min": {
                "type": "number",
                "description": "Minimum contour elevation (optional).",
            },
            "z_max": {
                "type": "number",
                "description": "Maximum contour elevation (optional).",
            },
            "datum_z": {
                "type": "number",
                "description": "Datum elevation for 'volume' op (default 0.0).",
                "default": 0.0,
            },
            "points_b": {
                "type": "array",
                "description": "Second surface points [[x,y,z],…] for 'volume_between' op.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "x": {
                "type": "number",
                "description": "X coordinate for 'interpolate_z' op.",
            },
            "y": {
                "type": "number",
                "description": "Y coordinate for 'interpolate_z' op.",
            },
        },
        "required": ["points", "op"],
    },
)


async def run_civil_tin_terrain(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.tin import (
            build_tin, contours, slope, aspect, area_2d, volume_above,
            volume_between, interpolate_z,
        )

        pts = params.get("points")
        op = params.get("op")
        if not pts or op is None:
            return err_payload("points and op are required", "BAD_ARGS")

        # Optional constraints
        breaklines = params.get("breaklines") or None
        boundary = params.get("boundary") or None

        tin = build_tin(pts, breaklines=breaklines, boundary=boundary)
        n_tri = int(tin.triangles.shape[0])

        if op == "contours":
            interval = float(params.get("interval", 1.0))
            if interval <= 0:
                return err_payload("interval must be > 0", "BAD_ARGS")
            kwargs: dict = {}
            if params.get("z_min") is not None:
                kwargs["z_min"] = float(params["z_min"])
            if params.get("z_max") is not None:
                kwargs["z_max"] = float(params["z_max"])
            polylines = contours(tin, interval, **kwargs)
            # Convert numpy tuples to plain lists for JSON serialisation
            serialisable = [
                [[round(x, 4), round(y, 4), round(z, 4)] for x, y, z in pl]
                for pl in polylines
            ]
            return ok_payload({
                "ok": True,
                "n_triangles": n_tri,
                "contour_count": len(serialisable),
                "polylines": serialisable,
            })

        elif op == "stats":
            tri_stats = []
            for i in range(n_tri):
                tri_stats.append({
                    "triangle_index": i,
                    "slope_deg": round(slope(tin, i), 4),
                    "aspect_deg": round(aspect(tin, i), 4),
                })
            return ok_payload({
                "ok": True,
                "n_triangles": n_tri,
                "area_2d_m2": round(area_2d(tin), 4),
                "triangles": tri_stats,
            })

        elif op == "volume":
            datum_z = float(params.get("datum_z", 0.0))
            vol = volume_above(tin, datum_z)
            return ok_payload({
                "ok": True,
                "n_triangles": n_tri,
                "datum_z": datum_z,
                "volume_m3": round(vol, 4),
            })

        elif op == "volume_between":
            pts_b = params.get("points_b")
            if not pts_b:
                return err_payload("points_b is required for volume_between op", "BAD_ARGS")
            tin_b = build_tin(pts_b)
            result = volume_between(tin, tin_b)
            return ok_payload({
                "ok": True,
                "n_triangles_a": n_tri,
                "n_triangles_b": int(tin_b.triangles.shape[0]),
                **result,
            })

        elif op == "interpolate_z":
            x = params.get("x")
            y = params.get("y")
            if x is None or y is None:
                return err_payload("x and y are required for interpolate_z op", "BAD_ARGS")
            z_val = interpolate_z(tin, float(x), float(y))
            return ok_payload({
                "ok": True,
                "n_triangles": n_tri,
                "x": float(x),
                "y": float(y),
                "z_m": round(z_val, 6) if z_val is not None else None,
                "inside_tin": z_val is not None,
            })

        else:
            return err_payload(f"unknown op {op!r}", "BAD_ARGS")

    except Exception as exc:
        return err_payload(str(exc), "CIVIL_TIN_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_crs_transform
# ---------------------------------------------------------------------------

civil_crs_transform_spec = ToolSpec(
    name="civil_crs_transform",
    description=(
        "Transform coordinates between two Coordinate Reference Systems.\n"
        "\n"
        "Supports EPSG integer codes (e.g. 4326, 32634) and 'EPSG:NNNN' strings.\n"
        "When pyproj is available, any EPSG / PROJ-string / WKT is accepted.\n"
        "Without pyproj, only WGS-84 (EPSG:4326) ↔ UTM (EPSG:326xx/327xx)\n"
        "conversions are supported.\n"
        "\n"
        "Single point mode:  supply x, y (scalars).\n"
        "Batch mode:         supply xs, ys (equal-length arrays).\n"
        "\n"
        "Returns:\n"
        "  ok  : bool\n"
        "  x   / xs : transformed easting(s)\n"
        "  y   / ys : transformed northing(s)\n"
        "  z   / zs : transformed elevation(s) if z/zs supplied\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "x": {"type": "number", "description": "Single input x / longitude (deg)."},
            "y": {"type": "number", "description": "Single input y / latitude (deg)."},
            "z": {"type": "number", "description": "Single input elevation (m), optional."},
            "xs": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Batch input x values.",
            },
            "ys": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Batch input y values (same length as xs).",
            },
            "zs": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Batch input z values (optional, same length as xs).",
            },
            "from_crs": {
                "type": ["string", "integer"],
                "description": "Source CRS — EPSG int/str e.g. 4326, 'EPSG:4326'.",
            },
            "to_crs": {
                "type": ["string", "integer"],
                "description": "Target CRS — EPSG int/str.",
            },
        },
        "required": ["from_crs", "to_crs"],
    },
)


async def run_civil_crs_transform(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.crs import transform

        from_crs = params["from_crs"]
        to_crs = params["to_crs"]

        # Determine scalar vs batch
        if params.get("xs") is not None:
            xs = list(params["xs"])
            ys = list(params["ys"])
            zs = list(params["zs"]) if params.get("zs") is not None else None
            result = transform(xs, ys, from_crs, to_crs, z=zs)
            if zs is not None:
                xo, yo, zo = result
                return ok_payload({"ok": True, "xs": list(xo), "ys": list(yo), "zs": list(zo)})
            xo, yo = result
            return ok_payload({"ok": True, "xs": list(xo), "ys": list(yo)})

        elif params.get("x") is not None:
            x = float(params["x"])
            y = float(params["y"])
            z = float(params["z"]) if params.get("z") is not None else None
            result = transform(x, y, from_crs, to_crs, z=z)
            if z is not None:
                xo, yo, zo = result
                return ok_payload({"ok": True, "x": xo, "y": yo, "z": zo})
            xo, yo = result
            return ok_payload({"ok": True, "x": xo, "y": yo})

        else:
            return err_payload("supply either (x, y) or (xs, ys)", "BAD_ARGS")

    except Exception as exc:
        return err_payload(str(exc), "CIVIL_CRS_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list consumed by plugin
# ---------------------------------------------------------------------------

TOOLS = [
    ("civil_tin_terrain",   civil_tin_terrain_spec,   run_civil_tin_terrain),
    ("civil_crs_transform", civil_crs_transform_spec, run_civil_crs_transform),
]
