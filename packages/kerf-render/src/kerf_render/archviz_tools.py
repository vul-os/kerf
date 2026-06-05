"""
archviz_tools.py — LLM tools for archviz scatter/population + asset library.

Tools registered:
  archviz_scatter_populate  — distribute asset instances over a surface
  archviz_asset_library     — search/get assets from the built-in catalogue
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

from kerf_render import archviz_assets as _assets
from kerf_render import archviz_scatter as _scatter


# ── archviz_scatter_populate ──────────────────────────────────────────────

archviz_scatter_populate_spec = ToolSpec(
    name="archviz_scatter_populate",
    description=(
        "Procedurally scatter archviz asset instances (trees, shrubs, people, "
        "cars, furniture) over a rectangular area. "
        "Supports Poisson-disk (uniform but non-regular, respects min_spacing) "
        "and jittered-grid distributions. "
        "Returns a list of instance transforms {id, asset_id, position, rotation, "
        "scale} for use in instanced rendering. "
        "Controls: density (instances/m²), random seed (deterministic output), "
        "scale_jitter, rotation_jitter_deg, slope/altitude masks (with height "
        "field), exclusion_zones (axis-aligned rectangles), "
        "min_spacing for collision avoidance."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "area": {
                "type": "object",
                "description": (
                    "Bounding rectangle for the scatter surface. "
                    "{x_min, y_min, x_max, y_max, base_z}. "
                    "Units are metres. Default: 10×10 m."
                ),
                "properties": {
                    "x_min": {"type": "number"},
                    "y_min": {"type": "number"},
                    "x_max": {"type": "number"},
                    "y_max": {"type": "number"},
                    "base_z": {"type": "number", "description": "Ground Z offset."},
                },
            },
            "asset_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Asset IDs from the archviz catalogue to scatter. "
                    "Instances cycle through the list. "
                    "Use archviz_asset_library to discover valid IDs."
                ),
            },
            "density": {
                "type": "number",
                "description": "Instances per m². Default 1.0. Max 50.",
            },
            "seed": {
                "type": "integer",
                "description": "Random seed. Same seed + same params → same layout.",
            },
            "min_spacing": {
                "type": "number",
                "description": (
                    "Minimum centre-to-centre distance (metres). "
                    "Enforced for Poisson (hard radius) and as post-filter for grid. "
                    "Default 0.5."
                ),
            },
            "scale_jitter": {
                "type": "number",
                "description": "±fractional scale jitter (0=none, 0.2=±20%). Default 0.2.",
            },
            "rotation_jitter_deg": {
                "type": "number",
                "description": "Random Z-rotation range in degrees. Default 360.",
            },
            "method": {
                "type": "string",
                "enum": ["poisson", "grid"],
                "description": "'poisson' (Poisson-disk, default) or 'grid' (jittered grid).",
            },
            "exclusion_zones": {
                "type": "array",
                "description": "Rectangles inside which no instances are placed.",
                "items": {
                    "type": "object",
                    "properties": {
                        "x_min": {"type": "number"},
                        "y_min": {"type": "number"},
                        "x_max": {"type": "number"},
                        "y_max": {"type": "number"},
                    },
                },
            },
            "height_field": {
                "type": "object",
                "description": (
                    "2-D height grid for slope/altitude masking. "
                    "{grid:[[...]], rows, cols, x_min, y_min, x_max, y_max}."
                ),
            },
            "max_slope_deg": {
                "type": "number",
                "description": "Discard instances on slopes steeper than this (degrees).",
            },
            "altitude_min": {
                "type": "number",
                "description": "Discard instances below this Z altitude.",
            },
            "altitude_max": {
                "type": "number",
                "description": "Discard instances above this Z altitude.",
            },
        },
        "required": ["asset_ids"],
    },
)


@register(archviz_scatter_populate_spec, write=False)
async def archviz_scatter_populate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    asset_ids = a.get("asset_ids")
    if not isinstance(asset_ids, list) or not asset_ids:
        return err_payload("asset_ids must be a non-empty list of strings", "BAD_ARGS")

    # Validate all asset_ids against the catalogue
    unknown = [aid for aid in asset_ids if _assets.get_asset(aid) is None]
    if unknown:
        return err_payload(
            f"unknown asset_ids: {unknown}. Use archviz_asset_library to list valid IDs.",
            "BAD_ARGS",
        )

    area = a.get("area", {"x_min": 0, "y_min": 0, "x_max": 10, "y_max": 10, "base_z": 0})
    density = float(a.get("density", 1.0))
    seed = int(a.get("seed", 0))
    min_spacing = float(a.get("min_spacing", _scatter.DEFAULT_MIN_SPACING))
    scale_jitter = float(a.get("scale_jitter", 0.2))
    rotation_jitter_deg = float(a.get("rotation_jitter_deg", 360.0))
    method = str(a.get("method", "poisson"))
    exclusion_zones = a.get("exclusion_zones") or []
    height_field = a.get("height_field") or None
    max_slope_deg = a.get("max_slope_deg")
    altitude_min = a.get("altitude_min")
    altitude_max = a.get("altitude_max")

    if method not in ("poisson", "grid"):
        return err_payload(f"method must be 'poisson' or 'grid', got: {method!r}", "BAD_ARGS")

    try:
        instances = _scatter.scatter(
            area=area,
            asset_ids=asset_ids,
            density=density,
            seed=seed,
            min_spacing=min_spacing,
            scale_jitter=scale_jitter,
            rotation_jitter_deg=rotation_jitter_deg,
            method=method,
            exclusion_zones=exclusion_zones,
            height_field=height_field,
            max_slope_deg=float(max_slope_deg) if max_slope_deg is not None else None,
            altitude_min=float(altitude_min) if altitude_min is not None else None,
            altitude_max=float(altitude_max) if altitude_max is not None else None,
        )
    except Exception as e:
        return err_payload(f"scatter engine error: {e}", "SCATTER_ERROR")

    # Attach asset metadata for convenience
    asset_meta = {
        aid: _assets.get_asset(aid)
        for aid in asset_ids
    }

    return ok_payload({
        "status": "ok",
        "method": method,
        "seed": seed,
        "density": density,
        "min_spacing": min_spacing,
        "instance_count": len(instances),
        "instances": instances,
        "asset_meta": asset_meta,
    })


# ── archviz_asset_library ─────────────────────────────────────────────────

archviz_asset_library_spec = ToolSpec(
    name="archviz_asset_library",
    description=(
        "Search or retrieve assets from the Kerf built-in archviz proxy catalogue. "
        "Assets are parametric placeholder stubs (not photoreal meshes) covering "
        "trees, shrubs, ground-cover, people, cars, and furniture — "
        "sufficient for scale-figure population and spatial planning. "
        "Use 'action':'search' with optional category/query filters, "
        "or 'action':'get' with a specific asset_id. "
        "Returns asset metadata: id, category, label, bbox, default_scale, "
        "color_hint (for scatter preview dots), tags."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "get", "list_categories"],
                "description": (
                    "'search' (list matching assets), "
                    "'get' (single asset by id), "
                    "'list_categories' (return all category names)."
                ),
            },
            "asset_id": {
                "type": "string",
                "description": "Asset ID for action='get'.",
            },
            "category": {
                "type": "string",
                "enum": ["tree", "shrub", "ground_cover", "person", "car", "furniture"],
                "description": "Filter by category for action='search'.",
            },
            "query": {
                "type": "string",
                "description": "Free-text search in asset label/tags for action='search'.",
            },
            "limit": {
                "type": "integer",
                "description": "Max assets to return. Default 50.",
            },
        },
        "required": ["action"],
    },
)


@register(archviz_asset_library_spec, write=False)
async def archviz_asset_library(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args) if args else {}
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    action = str(a.get("action", "search")).strip()

    if action == "list_categories":
        return ok_payload({
            "categories": _assets.all_categories(),
            "category_colors": _assets.CATEGORY_COLORS,
        })

    if action == "get":
        asset_id = str(a.get("asset_id", "")).strip()
        if not asset_id:
            return err_payload("asset_id is required for action='get'", "BAD_ARGS")
        asset = _assets.get_asset(asset_id)
        if asset is None:
            return err_payload(f"asset not found: {asset_id!r}", "NOT_FOUND")
        return ok_payload({"asset": asset})

    if action == "search":
        category = a.get("category") or None
        query = a.get("query") or None
        limit = int(a.get("limit", 50))
        results = _assets.search_assets(query=query, category=category, limit=limit)
        return ok_payload({
            "total": len(results),
            "assets": results,
        })

    return err_payload(f"unknown action: {action!r}", "BAD_ARGS")


# ── TOOLS export ──────────────────────────────────────────────────────────

TOOLS = [
    (archviz_scatter_populate_spec.name, archviz_scatter_populate_spec, archviz_scatter_populate),
    (archviz_asset_library_spec.name, archviz_asset_library_spec, archviz_asset_library),
]
