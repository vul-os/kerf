"""
site_terrain.py — LLM tools for Site Terrain / Mesh Modelling (ArchiCAD parity).

Registered tools
----------------
bim_terrain_from_points    — build a TIN terrain (Toposolid) from XYZ point cloud
bim_terrain_from_contours  — build a Toposolid from contour polylines (elevation sets)
bim_terrain_analyse        — compute surface area, slope, aspect for a terrain
bim_terrain_contours       — generate contour polylines from a Toposolid
bim_terrain_cut_fill       — earthwork cut/fill volume between two terrains

Reuses kerf_bim.site (Toposolid, Contour, cut_fill_volume, slope, aspect)
which is the civil TIN engine — no duplication.

References
----------
IFC4 ADD2 TC1 — IfcGeographicElement (IfcGeographicElementTypeEnum.TERRAIN).
ArchiCAD 27 Site Mesh tool — mesh-from-points / mesh-from-contours workflows.
ASCE 32-01 — Frost-protected shallow foundations.
Davis & Foote — Surveying Theory and Practice, 6th ed.
"""

from __future__ import annotations

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore


def _make_toposolid(pts_raw: list, material: str = "soil", thickness: float = 1.0):
    from kerf_bim.site import Toposolid
    if len(pts_raw) < 3:
        raise ValueError("At least 3 points are required for triangulation")
    points = [(float(p[0]), float(p[1]), float(p[2])) for p in pts_raw]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    boundary = [
        (min(xs), min(ys)), (max(xs), min(ys)),
        (max(xs), max(ys)), (min(xs), max(ys)),
    ]
    return Toposolid(boundary=boundary, points=points, material=material, thickness=thickness)


# ---------------------------------------------------------------------------
# bim_terrain_from_points
# ---------------------------------------------------------------------------

_from_points_spec = ToolSpec(
    name="bim_terrain_from_points",
    description=(
        "Site Terrain — Build TIN mesh from XYZ survey points.\n"
        "\n"
        "Constructs a Toposolid (Triangulated Irregular Network terrain element) "
        "from a point cloud.  Returns surface area, plan area, volume, and "
        "elevation range.\n"
        "\n"
        "IFC alignment: IfcGeographicElement.TERRAIN backed by IfcTriangulatedFaceSet.\n"
        "ArchiCAD parity: Site Mesh → Mesh from points workflow."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "description": "Survey points as [[x, y, z], ...] (min 3). Units: metres.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 3,
            },
            "material": {
                "type": "string",
                "description": "Terrain material (default 'soil').",
                "default": "soil",
            },
            "thickness": {
                "type": "number",
                "description": "Solid depth below lowest terrain point (m, default 1.0).",
                "default": 1.0,
            },
        },
        "required": ["points"],
    },
)


async def run_bim_terrain_from_points(params: dict, ctx) -> str:
    try:
        pts_raw = params.get("points", [])
        material = str(params.get("material", "soil"))
        thickness = float(params.get("thickness", 1.0))

        if len(pts_raw) < 3:
            return err_payload("At least 3 points are required", "BAD_ARGS")

        ts = _make_toposolid(pts_raw, material, thickness)
        pts = ts.vertices

        return ok_payload({
            "ok": True,
            "point_count":    len(pts),
            "triangle_count": len(ts.simplices),
            "surface_area":   round(ts.surface_area(), 4),
            "plan_area":      round(ts.plan_area(), 4),
            "volume":         round(ts.volume(), 4),
            "elevation": {
                "min": round(float(pts[:, 2].min()), 4),
                "max": round(float(pts[:, 2].max()), 4),
                "range": round(float(pts[:, 2].max() - pts[:, 2].min()), 4),
            },
            "material":  ts.material,
            "thickness": ts.thickness,
        })
    except Exception as exc:
        return err_payload(str(exc), "TERRAIN_FROM_POINTS_ERROR")


# ---------------------------------------------------------------------------
# bim_terrain_from_contours
# ---------------------------------------------------------------------------

_from_contours_spec = ToolSpec(
    name="bim_terrain_from_contours",
    description=(
        "Site Terrain — Build TIN mesh from contour polylines.\n"
        "\n"
        "Each contour_set is a {elevation: float, points: [[x,y], ...]} dict. "
        "Points from all contours are merged and Delaunay-triangulated. "
        "Returns the same statistics as bim_terrain_from_points.\n"
        "\n"
        "ArchiCAD parity: Site Mesh → Mesh from contours workflow."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "contour_sets": {
                "type": "array",
                "description": "List of contour dicts: [{elevation, points: [[x,y], ...]}]",
                "items": {
                    "type": "object",
                    "properties": {
                        "elevation": {"type": "number"},
                        "points": {
                            "type": "array",
                            "items": {
                                "type": "array",
                                "items": {"type": "number"},
                            },
                        },
                    },
                    "required": ["elevation", "points"],
                },
                "minItems": 2,
            },
            "material":  {"type": "string", "default": "soil"},
            "thickness": {"type": "number",  "default": 1.0},
        },
        "required": ["contour_sets"],
    },
)


async def run_bim_terrain_from_contours(params: dict, ctx) -> str:
    try:
        contour_sets = params.get("contour_sets", [])
        if len(contour_sets) < 2:
            return err_payload("At least 2 contour sets are required", "BAD_ARGS")

        # Flatten contour polylines into XYZ points
        all_pts = []
        for cs in contour_sets:
            elev = float(cs["elevation"])
            for xy in cs.get("points", []):
                all_pts.append([float(xy[0]), float(xy[1]), elev])

        if len(all_pts) < 3:
            return err_payload("Contour sets must contain at least 3 points total", "BAD_ARGS")

        material = str(params.get("material", "soil"))
        thickness = float(params.get("thickness", 1.0))

        ts = _make_toposolid(all_pts, material, thickness)
        pts = ts.vertices

        return ok_payload({
            "ok": True,
            "contour_count":  len(contour_sets),
            "point_count":    len(pts),
            "triangle_count": len(ts.simplices),
            "surface_area":   round(ts.surface_area(), 4),
            "plan_area":      round(ts.plan_area(), 4),
            "volume":         round(ts.volume(), 4),
            "elevation": {
                "min": round(float(pts[:, 2].min()), 4),
                "max": round(float(pts[:, 2].max()), 4),
                "range": round(float(pts[:, 2].max() - pts[:, 2].min()), 4),
            },
            "material":  ts.material,
            "thickness": ts.thickness,
        })
    except Exception as exc:
        return err_payload(str(exc), "TERRAIN_FROM_CONTOURS_ERROR")


# ---------------------------------------------------------------------------
# bim_terrain_analyse
# ---------------------------------------------------------------------------

_analyse_spec = ToolSpec(
    name="bim_terrain_analyse",
    description=(
        "Site Terrain — Analyse slope and aspect of a TIN terrain.\n"
        "\n"
        "Returns per-triangle slope (degrees from horizontal) and aspect "
        "(compass degrees, 0=North) statistics: min, max, mean, and "
        "histogram buckets for slope classification (flat/gentle/moderate/steep)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "description": "Survey points [[x,y,z], ...] (min 3).",
                "items": {"type": "array", "items": {"type": "number"}},
                "minItems": 3,
            },
        },
        "required": ["points"],
    },
)


async def run_bim_terrain_analyse(params: dict, ctx) -> str:
    try:
        import numpy as np
        from kerf_bim.site import slope as compute_slope, aspect as compute_aspect

        pts_raw = params.get("points", [])
        if len(pts_raw) < 3:
            return err_payload("At least 3 points are required", "BAD_ARGS")

        ts = _make_toposolid(pts_raw)
        slopes = compute_slope(ts)
        aspects = compute_aspect(ts)

        def _stats(arr: np.ndarray) -> dict:
            return {
                "min":  round(float(arr.min()), 2),
                "max":  round(float(arr.max()), 2),
                "mean": round(float(arr.mean()), 2),
            }

        # Slope classification (ASCE / standard GIS)
        slope_classes = {
            "flat (0-2°)":     int((slopes < 2).sum()),
            "gentle (2-10°)":  int(((slopes >= 2) & (slopes < 10)).sum()),
            "moderate (10-30°)": int(((slopes >= 10) & (slopes < 30)).sum()),
            "steep (>30°)":    int((slopes >= 30).sum()),
        }

        return ok_payload({
            "ok":           True,
            "triangle_count": len(slopes),
            "slope":        _stats(slopes),
            "slope_classes": slope_classes,
            "aspect":       _stats(aspects),
        })
    except Exception as exc:
        return err_payload(str(exc), "TERRAIN_ANALYSE_ERROR")


# ---------------------------------------------------------------------------
# bim_terrain_contours
# ---------------------------------------------------------------------------

_contours_spec = ToolSpec(
    name="bim_terrain_contours",
    description=(
        "Site Terrain — Generate contour polylines from a TIN terrain.\n"
        "\n"
        "Produces contour lines at regular elevation intervals. Each contour "
        "is a {elevation, point_count, length_m} summary. Set include_points=true "
        "to also return the full XYZ point arrays (larger payload)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "description": "Survey points [[x,y,z], ...] (min 3).",
                "items": {"type": "array", "items": {"type": "number"}},
                "minItems": 3,
            },
            "interval": {
                "type": "number",
                "description": "Elevation interval between contours (m, default 1.0).",
                "default": 1.0,
            },
            "include_points": {
                "type": "boolean",
                "description": "If true, include XYZ point arrays per contour (default false).",
                "default": False,
            },
        },
        "required": ["points"],
    },
)


async def run_bim_terrain_contours(params: dict, ctx) -> str:
    try:
        from kerf_bim.site import Contour

        pts_raw = params.get("points", [])
        if len(pts_raw) < 3:
            return err_payload("At least 3 points are required", "BAD_ARGS")

        interval = float(params.get("interval", 1.0))
        if interval <= 0:
            return err_payload("interval must be > 0", "BAD_ARGS")

        include_pts = bool(params.get("include_points", False))
        ts = _make_toposolid(pts_raw)
        curves = Contour(ts, interval=interval)

        result_contours = []
        for c in curves:
            entry: dict = {
                "elevation":   round(c.elevation, 4),
                "point_count": len(c.points),
                "length_m":    round(c.length(), 4),
            }
            if include_pts:
                entry["points"] = [[round(float(p[0]), 4), round(float(p[1]), 4), round(float(p[2]), 4)] for p in c.points]
            result_contours.append(entry)

        return ok_payload({
            "ok":             True,
            "contour_count":  len(curves),
            "interval_m":     interval,
            "contours":       result_contours,
        })
    except Exception as exc:
        return err_payload(str(exc), "TERRAIN_CONTOURS_ERROR")


# ---------------------------------------------------------------------------
# bim_terrain_cut_fill
# ---------------------------------------------------------------------------

_cut_fill_spec = ToolSpec(
    name="bim_terrain_cut_fill",
    description=(
        "Site Terrain — Compute earthwork cut/fill volumes between existing and "
        "proposed terrain surfaces using grid-difference integration.\n"
        "\n"
        "cut  = volume of material removed (proposed lower than existing)\n"
        "fill = volume of material added (proposed higher than existing)\n"
        "net  = fill - cut\n"
        "\n"
        "Reuses the kerf_bim.site civil TIN engine."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "existing_points": {
                "type": "array",
                "description": "Existing terrain XYZ points [[x,y,z], ...] (min 3).",
                "items": {"type": "array", "items": {"type": "number"}},
                "minItems": 3,
            },
            "proposed_points": {
                "type": "array",
                "description": "Proposed terrain XYZ points [[x,y,z], ...] (min 3).",
                "items": {"type": "array", "items": {"type": "number"}},
                "minItems": 3,
            },
            "grid_spacing": {
                "type": "number",
                "description": "Integration grid cell size (m, default 1.0).",
                "default": 1.0,
            },
        },
        "required": ["existing_points", "proposed_points"],
    },
)


async def run_bim_terrain_cut_fill(params: dict, ctx) -> str:
    try:
        from kerf_bim.site import cut_fill_volume

        existing_raw = params.get("existing_points", [])
        proposed_raw = params.get("proposed_points", [])
        grid_spacing = float(params.get("grid_spacing", 1.0))

        if len(existing_raw) < 3:
            return err_payload("existing_points must have at least 3 entries", "BAD_ARGS")
        if len(proposed_raw) < 3:
            return err_payload("proposed_points must have at least 3 entries", "BAD_ARGS")
        if grid_spacing <= 0:
            return err_payload("grid_spacing must be > 0", "BAD_ARGS")

        ts_existing = _make_toposolid(existing_raw)
        ts_proposed = _make_toposolid(proposed_raw)
        result = cut_fill_volume(ts_existing, ts_proposed, grid_spacing=grid_spacing)

        return ok_payload({
            "ok":          True,
            "cut_m3":      round(result["cut"], 4),
            "fill_m3":     round(result["fill"], 4),
            "net_m3":      round(result["net"], 4),
            "grid_spacing_m": grid_spacing,
        })
    except Exception as exc:
        return err_payload(str(exc), "TERRAIN_CUT_FILL_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list
# ---------------------------------------------------------------------------

TOOLS = [
    ("bim_terrain_from_points",    _from_points_spec,  run_bim_terrain_from_points),
    ("bim_terrain_from_contours",  _from_contours_spec, run_bim_terrain_from_contours),
    ("bim_terrain_analyse",        _analyse_spec,       run_bim_terrain_analyse),
    ("bim_terrain_contours",       _contours_spec,      run_bim_terrain_contours),
    ("bim_terrain_cut_fill",       _cut_fill_spec,      run_bim_terrain_cut_fill),
]
