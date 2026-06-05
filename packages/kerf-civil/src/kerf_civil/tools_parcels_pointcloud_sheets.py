"""
tools_parcels_pointcloud_sheets.py — LLM tools for three Civil 3D greenfield
gap engines:

  civil_parcel_subdivide    — parcel subdivision: split boundary into lots by
                              frontage/area targets, setback offsets, ROW
                              dedication, area/perimeter report.

  civil_pointcloud_process  — LAS/LAZ-lite ingest (XYZ/PLY ASCII), voxel
                              downsample, PMF ground classification, and
                              surface-from-points TIN handoff.

  civil_plan_profile_sheets — automated plan+profile sheet generator for an
                              alignment: station grid, profile band, match
                              lines, sheet framing → JSON sheet set.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_civil._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


# ===========================================================================
# Tool: civil_parcel_subdivide
# ===========================================================================

civil_parcel_subdivide_spec = ToolSpec(
    name="civil_parcel_subdivide",
    description=(
        "Subdivide a parcel boundary polygon into development lots.\n"
        "\n"
        "Two strategies:\n"
        "  'equal_width'  — divide into N equal-width lots from the frontage edge.\n"
        "  'target_area'  — greedy binary-search slice to meet a target lot area.\n"
        "\n"
        "Optionally dedicates a ROW strip along the frontage edge.\n"
        "Returns lot polygons, buildable (post-setback) polygons, and summary\n"
        "statistics (area, perimeter, frontage per lot).\n"
        "\n"
        "Method: Sutherland-Hodgman polygon clipping + signed-area shoelace\n"
        "formula (ISO 19152 LADM parcel concept; ASCE Surveying Engineering\n"
        "subdivision design practice).\n"
        "\n"
        "Parameters\n"
        "----------\n"
        "boundary      : list of [x, y] vertices of the outer parcel (m)\n"
        "strategy      : 'equal_width' or 'target_area'\n"
        "n_lots        : int — number of lots (required for equal_width)\n"
        "target_area_m2: float — target lot area m² (required for target_area)\n"
        "frontage_edge : int — index of the frontage edge (default 0)\n"
        "min_frontage_m: float — minimum lot frontage (m); for validation\n"
        "setback_m     : float — building setback from all lot edges (m)\n"
        "row_width_m   : float — ROW dedication strip width (m)\n"
        "\n"
        "Returns\n"
        "-------\n"
        "ok, n_lots, parent_area_m2, net_developable_area_m2,\n"
        "min/max/mean lot areas, total_buildable_area_m2,\n"
        "row (polygon + area_m2), lots[] (polygon, buildable polygon,\n"
        "area_m2, perimeter_m, frontage_m, buildable_area_m2)\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "boundary": {
                "type": "array",
                "description": "Outer parcel boundary as [[x, y], …] in metres.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 3,
            },
            "strategy": {
                "type": "string",
                "enum": ["equal_width", "target_area"],
                "description": "Subdivision strategy.",
                "default": "equal_width",
            },
            "n_lots": {
                "type": "integer",
                "description": "Number of lots (equal_width strategy).",
                "minimum": 1,
            },
            "target_area_m2": {
                "type": "number",
                "description": "Target lot area in m² (target_area strategy).",
            },
            "frontage_edge": {
                "type": "integer",
                "description": "Index of frontage edge in boundary (default 0).",
                "default": 0,
            },
            "min_frontage_m": {
                "type": "number",
                "description": "Minimum lot frontage width (m).",
                "default": 10.0,
            },
            "setback_m": {
                "type": "number",
                "description": "Building setback from all lot edges (m).",
                "default": 3.0,
            },
            "row_width_m": {
                "type": "number",
                "description": "ROW dedication strip width along frontage edge (m).",
                "default": 0.0,
            },
        },
        "required": ["boundary"],
    },
)


async def run_civil_parcel_subdivide(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.parcels import subdivide_parcel

        boundary = params.get("boundary")
        if not boundary or len(boundary) < 3:
            return err_payload("boundary must have >= 3 [x,y] vertices", "BAD_ARGS")

        strategy = params.get("strategy", "equal_width")
        n_lots = params.get("n_lots")
        target_area = params.get("target_area_m2")
        frontage_edge = int(params.get("frontage_edge", 0))
        min_frontage = float(params.get("min_frontage_m", 10.0))
        setback = float(params.get("setback_m", 3.0))
        row_width = float(params.get("row_width_m", 0.0))

        result = subdivide_parcel(
            boundary,
            n_lots=n_lots,
            target_area_m2=target_area,
            frontage_edge=frontage_edge,
            min_frontage_m=min_frontage,
            setback_m=setback,
            row_width_m=row_width,
            strategy=strategy,
        )

        row_dict = None
        if result.row:
            row_dict = {
                "polygon": result.row.polygon,
                "area_m2": result.row.area_m2,
                "width_m": result.row.width_m,
            }

        lots_out = []
        for lot in result.lots:
            lots_out.append({
                "lot_number": lot.lot_number,
                "polygon": lot.polygon,
                "buildable_polygon": lot.buildable_polygon,
                "area_m2": lot.area_m2,
                "perimeter_m": lot.perimeter_m,
                "frontage_m": lot.frontage_m,
                "buildable_area_m2": lot.buildable_area_m2,
            })

        return ok_payload({
            "ok": True,
            "strategy": result.strategy,
            "n_lots": result.n_lots,
            "parent_area_m2": result.parent_area_m2,
            "net_developable_area_m2": result.net_developable_area_m2,
            "min_lot_area_m2": result.min_lot_area_m2,
            "max_lot_area_m2": result.max_lot_area_m2,
            "mean_lot_area_m2": result.mean_lot_area_m2,
            "total_buildable_area_m2": result.total_buildable_area_m2,
            "row": row_dict,
            "lots": lots_out,
        })
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_PARCEL_ERROR")


# ===========================================================================
# Tool: civil_pointcloud_process
# ===========================================================================

civil_pointcloud_process_spec = ToolSpec(
    name="civil_pointcloud_process",
    description=(
        "Process a point cloud through the civil engineering pipeline:\n"
        "ingest → voxel downsample → PMF ground classification → TIN surface.\n"
        "\n"
        "Input formats:\n"
        "  'xyz'  — space/tab/comma XYZ text (inline or file path)\n"
        "  'ply'  — ASCII PLY with x y z vertex properties\n"
        "  'las'  — LAS/LAZ file path (requires laspy >= 2.0)\n"
        "\n"
        "Operations (op):\n"
        "  'stats'       — return point-count / extents / density statistics\n"
        "  'downsample'  — voxel-grid downsample, return reduced point count\n"
        "  'classify'    — run PMF ground filter, return ground point count\n"
        "  'surface'     — full pipeline → build TIN, return n_triangles\n"
        "\n"
        "Method: Zhang et al. (2003) Progressive Morphological Filter (PMF),\n"
        "IEEE TGRS 41(4):872-882; ASPRS LAS Spec 1.4-R15.\n"
        "\n"
        "Parameters\n"
        "----------\n"
        "format        : 'xyz', 'ply', or 'las'\n"
        "data          : inline text (xyz/ply) or file path (las)\n"
        "op            : 'stats', 'downsample', 'classify', or 'surface'\n"
        "cell_size     : voxel cell size (m) for downsample + PMF\n"
        "max_window    : PMF max morphological window (m)\n"
        "slope_thresh  : PMF slope threshold (m/m)\n"
        "classify_ground : bool — run PMF for 'surface' op (default true)\n"
        "\n"
        "Returns\n"
        "-------\n"
        "ok, n_points_in, n_points_out, stats dict;\n"
        "For 'surface': also n_triangles, tin_extents.\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "format": {
                "type": "string",
                "enum": ["xyz", "ply", "las"],
                "description": "Input format.",
            },
            "data": {
                "type": "string",
                "description": "Inline XYZ/PLY text, or LAS/LAZ file path.",
            },
            "op": {
                "type": "string",
                "enum": ["stats", "downsample", "classify", "surface"],
                "description": "Operation to perform.",
            },
            "cell_size": {
                "type": "number",
                "description": "Voxel cell size (m) for downsample and PMF.",
                "default": 1.0,
            },
            "max_window": {
                "type": "number",
                "description": "PMF maximum morphological window half-size (m).",
                "default": 33.0,
            },
            "slope_thresh": {
                "type": "number",
                "description": "PMF slope threshold (m/m), typically 0.3.",
                "default": 0.3,
            },
            "classify_ground": {
                "type": "boolean",
                "description": "Run PMF ground classification for 'surface' op.",
                "default": True,
            },
        },
        "required": ["format", "data", "op"],
    },
)


async def run_civil_pointcloud_process(params: dict, ctx: "ProjectCtx") -> str:
    try:
        import numpy as np
        from kerf_civil.pointcloud import (
            read_xyz,
            read_ply_ascii,
            voxel_downsample,
            pmf_ground_classify,
            surface_from_points,
            point_cloud_stats,
        )

        fmt = params.get("format", "xyz")
        data = params.get("data", "")
        op = params.get("op", "stats")
        cell_size = float(params.get("cell_size", 1.0))
        max_window = float(params.get("max_window", 33.0))
        slope_thresh = float(params.get("slope_thresh", 0.3))
        classify_ground = bool(params.get("classify_ground", True))

        # Ingest
        if fmt == "xyz":
            pts = read_xyz(data)
        elif fmt == "ply":
            pts = read_ply_ascii(data)
        elif fmt == "las":
            from kerf_civil.pointcloud import read_las
            pts = read_las(data)
        else:
            return err_payload(f"unknown format {fmt!r}", "BAD_ARGS")

        n_in = int(len(pts))

        if op == "stats":
            stats = point_cloud_stats(pts)
            return ok_payload({"ok": True, "n_points": n_in, "stats": stats})

        elif op == "downsample":
            ds = voxel_downsample(pts, cell_size)
            stats = point_cloud_stats(ds)
            return ok_payload({
                "ok": True,
                "n_points_in": n_in,
                "n_points_out": int(len(ds)),
                "reduction_pct": round((1.0 - len(ds) / max(n_in, 1)) * 100, 2),
                "stats": stats,
            })

        elif op == "classify":
            pmf_kw = {
                "cell_size": cell_size,
                "max_window_size": max_window,
                "slope_threshold": slope_thresh,
            }
            gnd = pmf_ground_classify(pts, **pmf_kw)
            stats = point_cloud_stats(gnd)
            return ok_payload({
                "ok": True,
                "n_points_in": n_in,
                "n_ground_points": int(len(gnd)),
                "ground_fraction_pct": round(len(gnd) / max(n_in, 1) * 100, 2),
                "stats": stats,
            })

        elif op == "surface":
            pmf_kw = {
                "cell_size": cell_size,
                "max_window_size": max_window,
                "slope_threshold": slope_thresh,
            }
            tin = surface_from_points(
                pts,
                downsample_cell_size=cell_size,
                classify_ground=classify_ground,
                pmf_kwargs=pmf_kw,
            )
            n_tri = int(tin.triangles.shape[0])
            xyz = tin.points[:, :3]
            return ok_payload({
                "ok": True,
                "n_points_in": n_in,
                "n_tin_points": int(len(tin.points)),
                "n_triangles": n_tri,
                "tin_extents": {
                    "x_min": round(float(xyz[:, 0].min()), 4),
                    "x_max": round(float(xyz[:, 0].max()), 4),
                    "y_min": round(float(xyz[:, 1].min()), 4),
                    "y_max": round(float(xyz[:, 1].max()), 4),
                    "z_min": round(float(xyz[:, 2].min()), 4),
                    "z_max": round(float(xyz[:, 2].max()), 4),
                },
            })

        else:
            return err_payload(f"unknown op {op!r}", "BAD_ARGS")

    except Exception as exc:
        return err_payload(str(exc), "CIVIL_POINTCLOUD_ERROR")


# ===========================================================================
# Tool: civil_plan_profile_sheets
# ===========================================================================

civil_plan_profile_sheets_spec = ToolSpec(
    name="civil_plan_profile_sheets",
    description=(
        "Generate an automated plan-and-profile sheet set for a horizontal and\n"
        "vertical alignment.\n"
        "\n"
        "Each sheet contains:\n"
        "  • Plan view: station grid ticks, north orientation, alignment centreline\n"
        "    polyline, sheet framing at plan_scale.\n"
        "  • Profile band: existing ground + proposed grade elevations at each\n"
        "    station tick; vertical grid; grade labels.\n"
        "  • Match lines: station-aligned cut lines for continuation sheets with\n"
        "    directional labels ('Sheet N →').\n"
        "  • Title block metadata: project name, sheet N of M, scales, date.\n"
        "\n"
        "Method: AASHTO Green Book (2011) Ch.2; FHWA Plans Preparation Manual\n"
        "(2012); ODOT Plans Preparation Manual (2023) Ch.300;\n"
        "CALTRANS PPM (2023) Ch.3.\n"
        "\n"
        "Parameters\n"
        "----------\n"
        "total_length       : float — alignment length (m or ft)\n"
        "alignment_elements : list of {type, length, radius, delta_deg, turn_right}\n"
        "vertical_elements  : list of {type, length, grade_out_pct}\n"
        "datum_elev         : starting elevation (m)\n"
        "initial_grade_pct  : starting grade (%)\n"
        "existing_ground    : [[station, elev], …] for existing ground profile\n"
        "plan_scale         : plan-view scale denominator (default 1000)\n"
        "profile_scale_h    : profile horizontal scale denominator (default 1000)\n"
        "profile_scale_v    : profile vertical scale denominator (default 200)\n"
        "sheet_length       : alignment coverage per sheet (m; default = plan_scale×0.25)\n"
        "station_interval   : grid tick interval (m; default 20)\n"
        "units              : 'm' or 'ft'\n"
        "project_name       : title block text\n"
        "alignment_name     : alignment name for title block\n"
        "date               : date string\n"
        "designer           : designer initials\n"
        "overlap            : match-line overlap (m; default 0)\n"
        "\n"
        "Returns\n"
        "-------\n"
        "ok, n_sheets, total_length_m,\n"
        "sheets[] — each with sheet_number, total_sheets, sta_start/end,\n"
        "station_ticks[], alignment_polyline[], match_lines[], profile_band[],\n"
        "profile_datum_elev, profile_top_elev, title block fields.\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "total_length": {
                "type": "number",
                "description": "Alignment total length (m).",
            },
            "alignment_elements": {
                "type": "array",
                "description": "Horizontal alignment elements.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["tangent", "arc", "spiral"]},
                        "length": {"type": "number"},
                        "radius": {"type": "number"},
                        "delta_deg": {"type": "number"},
                        "turn_right": {"type": "boolean"},
                    },
                    "required": ["type", "length"],
                },
            },
            "vertical_elements": {
                "type": "array",
                "description": "Vertical alignment elements.",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["tangent", "curve"]},
                        "length": {"type": "number"},
                        "grade_out_pct": {"type": "number"},
                    },
                    "required": ["type", "length"],
                },
            },
            "datum_elev": {
                "type": "number",
                "description": "Starting elevation (m).",
                "default": 0.0,
            },
            "initial_grade_pct": {
                "type": "number",
                "description": "Starting grade (%).",
                "default": 0.0,
            },
            "existing_ground": {
                "type": "array",
                "description": "Existing ground profile [[station, elev], …].",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
            },
            "plan_scale": {
                "type": "integer",
                "description": "Plan-view scale denominator (e.g. 1000 for 1:1000).",
                "default": 1000,
            },
            "profile_scale_h": {
                "type": "integer",
                "description": "Profile horizontal scale denominator.",
                "default": 1000,
            },
            "profile_scale_v": {
                "type": "integer",
                "description": "Profile vertical scale denominator.",
                "default": 200,
            },
            "sheet_length": {
                "type": "number",
                "description": "Alignment coverage per sheet (m).",
            },
            "station_interval": {
                "type": "number",
                "description": "Station tick/grid interval (m).",
                "default": 20.0,
            },
            "units": {
                "type": "string",
                "enum": ["m", "ft"],
                "description": "Units system.",
                "default": "m",
            },
            "project_name": {
                "type": "string",
                "description": "Title block project name.",
                "default": "Kerf Civil Project",
            },
            "alignment_name": {
                "type": "string",
                "description": "Alignment name.",
                "default": "Alignment 1",
            },
            "date": {
                "type": "string",
                "description": "Date string for title block.",
                "default": "",
            },
            "designer": {
                "type": "string",
                "description": "Designer initials.",
                "default": "",
            },
            "overlap": {
                "type": "number",
                "description": "Match-line overlap between sheets (m).",
                "default": 0.0,
            },
        },
        "required": ["total_length"],
    },
)


async def run_civil_plan_profile_sheets(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.sheets import produce_sheets, sheet_set_to_dict

        total_length = float(params["total_length"])
        ha_elems = params.get("alignment_elements") or None
        va_elems = params.get("vertical_elements") or None
        datum_elev = float(params.get("datum_elev", 0.0))
        init_grade = float(params.get("initial_grade_pct", 0.0))
        existing_ground_raw = params.get("existing_ground")
        existing_ground = [tuple(eg) for eg in existing_ground_raw] if existing_ground_raw else None  # type: ignore[misc]

        plan_scale = int(params.get("plan_scale", 1000))
        profile_scale_h = int(params.get("profile_scale_h", 1000))
        profile_scale_v = int(params.get("profile_scale_v", 200))
        sheet_length = params.get("sheet_length")
        if sheet_length is not None:
            sheet_length = float(sheet_length)
        station_interval = float(params.get("station_interval", 20.0))
        units = params.get("units", "m")
        project_name = params.get("project_name", "Kerf Civil Project")
        alignment_name = params.get("alignment_name", "Alignment 1")
        date = params.get("date", "")
        designer = params.get("designer", "")
        overlap = float(params.get("overlap", 0.0))

        ss = produce_sheets(
            total_length=total_length,
            alignment_elements=ha_elems,
            vertical_elements=va_elems,
            datum_elev=datum_elev,
            initial_grade_pct=init_grade,
            existing_ground=existing_ground,
            plan_scale=plan_scale,
            profile_scale_h=profile_scale_h,
            profile_scale_v=profile_scale_v,
            sheet_length=sheet_length,
            station_interval=station_interval,
            units=units,
            project_name=project_name,
            alignment_name=alignment_name,
            date=date,
            designer=designer,
            overlap=overlap,
        )

        payload = sheet_set_to_dict(ss)
        payload["ok"] = True
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "CIVIL_SHEETS_ERROR")


# ===========================================================================
# TOOLS list consumed by plugin
# ===========================================================================

TOOLS = [
    (
        "civil_parcel_subdivide",
        civil_parcel_subdivide_spec,
        run_civil_parcel_subdivide,
    ),
    (
        "civil_pointcloud_process",
        civil_pointcloud_process_spec,
        run_civil_pointcloud_process,
    ),
    (
        "civil_plan_profile_sheets",
        civil_plan_profile_sheets_spec,
        run_civil_plan_profile_sheets,
    ),
]
