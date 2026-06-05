"""woodworking_pricing_tools.py — LLM tool wrappers for pricing, 2D nesting, and shop drawings.

Tools:
    woodworking_estimate_project_cost  — material + hardware + labour cost rollup
    woodworking_nest_panels            — 2D guillotine panel nesting on sheet stock
    woodworking_panel_shop_drawing     — generate shop drawing data for a flat panel
    woodworking_cabinet_shop_drawing   — generate shop drawing data for a cabinet assembly

References:
    KCMA (2021). Cabinet Standards §8.
    AWI (2014). Architectural Woodwork Quality Standards 9th ed. §11.
    RS Means (2024). Architectural Woodwork cost data.
    Bourque (2003). Guillotine rectangle packing.
"""

from __future__ import annotations

import json
from typing import Any

from kerf_woodworking._compat import ToolSpec, err_payload, ok_payload
from kerf_woodworking.pricing import (
    estimate_project_cost,
    cost_estimate_to_dict,
    SHEET_COST_USD,
    HARDWARE_UNIT_COST_USD,
)
from kerf_woodworking.panel_optimizer import (
    PanelPart,
    optimise_panel_layout,
    nesting_result_to_dict,
)
from kerf_woodworking.shop_drawings import (
    panel_shop_drawing,
    cabinet_shop_drawing,
    shop_drawing_to_dict,
)


# ---------------------------------------------------------------------------
# Tool: woodworking_estimate_project_cost
# ---------------------------------------------------------------------------

_cost_spec = ToolSpec(
    name="woodworking_estimate_project_cost",
    description=(
        "Full material + hardware + labour cost rollup for a woodworking project. "
        "Covers sheet goods, edge banding, solid lumber, hardware items, and "
        "cabinet labour at a configurable shop rate. "
        "HONEST: Approximate 2024 US pricing ±30%. Validate against local quotes. "
        "Ref: KCMA 2021 §8; RS Means (2024)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sheet_items": {
                "type": "array",
                "description": "Sheet goods: [{material: str, sheets: float}]. "
                               "Material keys: oak_3/4\", birch_ply_3/4\", mdf_3/4\", etc.",
                "items": {
                    "type": "object",
                    "required": ["material", "sheets"],
                    "properties": {
                        "material": {"type": "string"},
                        "sheets": {"type": "number"},
                    },
                },
            },
            "edge_banding_items": {
                "type": "array",
                "description": "Edge banding: [{banding_type: str, lineal_m: float}]. "
                               "Types: pvc_white, oak_veneer, maple_veneer, etc.",
                "items": {
                    "type": "object",
                    "required": ["banding_type", "lineal_m"],
                    "properties": {
                        "banding_type": {"type": "string"},
                        "lineal_m": {"type": "number"},
                    },
                },
            },
            "solid_lumber_items": {
                "type": "array",
                "description": "Solid lumber: [{species: str, board_feet: float}].",
                "items": {
                    "type": "object",
                    "required": ["species", "board_feet"],
                    "properties": {
                        "species": {"type": "string"},
                        "board_feet": {"type": "number"},
                    },
                },
            },
            "hardware_items": {
                "type": "array",
                "description": "Hardware: [{hardware_key: str, quantity: int, description?: str}]. "
                               "Keys: hinge_blum_clip_top, drawer_slide_blum_movento, "
                               "pull_bar_128mm, shelf_pins_5mm_x4, pocket_screws_32mm_x100, etc.",
                "items": {
                    "type": "object",
                    "required": ["hardware_key", "quantity"],
                    "properties": {
                        "hardware_key": {"type": "string"},
                        "quantity": {"type": "integer"},
                        "description": {"type": "string"},
                    },
                },
            },
            "cabinet_counts": {
                "type": "object",
                "description": "Cabinet type counts for labour estimate: {base: N, wall: N, tall: N}.",
                "additionalProperties": {"type": "integer"},
            },
            "labour_rate_usd_per_hr": {
                "type": "number",
                "description": "Shop hourly rate (USD, default $75/hr).",
            },
            "overhead_pct": {
                "type": "number",
                "description": "Overhead + profit as % of direct costs (default 15%).",
            },
        },
    },
)


async def run_woodworking_estimate_project_cost(params: dict[str, Any], ctx: Any) -> str:
    try:
        estimate = estimate_project_cost(
            sheet_items=params.get("sheet_items"),
            edge_banding_items=params.get("edge_banding_items"),
            solid_lumber_items=params.get("solid_lumber_items"),
            hardware_items=params.get("hardware_items"),
            cabinet_counts=params.get("cabinet_counts"),
            labour_rate_usd_per_hr=float(params.get("labour_rate_usd_per_hr", 75.0)),
            overhead_pct=float(params.get("overhead_pct", 15.0)),
        )
        return ok_payload(cost_estimate_to_dict(estimate))
    except Exception as exc:
        return err_payload(str(exc), "COST_ESTIMATE_ERROR")


# ---------------------------------------------------------------------------
# Tool: woodworking_nest_panels
# ---------------------------------------------------------------------------

_nest_spec = ToolSpec(
    name="woodworking_nest_panels",
    description=(
        "Optimise 2D guillotine nesting of panel parts onto standard sheet stock "
        "(default 2440×1220 mm, 4×8 ft). Grain-direction aware: 'none' parts may "
        "rotate 90° for better yield. Returns placements, sheets used, yield %, "
        "and waste per sheet. "
        "Algorithm: Guillotine Best Short Side (BSS), FFD order. "
        "HONEST: Simplified heuristic — professional nesting adds 5–15% yield. "
        "Ref: Bourque (2003); Scheithauer (2018)."
    ),
    input_schema={
        "type": "object",
        "required": ["parts"],
        "properties": {
            "parts": {
                "type": "array",
                "description": "Panel parts to nest.",
                "items": {
                    "type": "object",
                    "required": ["part_id", "length_mm", "width_mm"],
                    "properties": {
                        "part_id":         {"type": "string"},
                        "length_mm":       {"type": "number"},
                        "width_mm":        {"type": "number"},
                        "quantity":        {"type": "integer", "minimum": 1},
                        "grain_direction": {
                            "type": "string",
                            "enum": ["length", "width", "none"],
                            "description": "Grain constraint. 'none' allows rotation.",
                        },
                        "material":    {"type": "string"},
                        "description": {"type": "string"},
                    },
                },
            },
            "sheet_length_mm": {"type": "number", "description": "Sheet long side (default 2440 mm)."},
            "sheet_width_mm":  {"type": "number", "description": "Sheet short side (default 1220 mm)."},
            "kerf_mm":         {"type": "number", "description": "Saw kerf (default 3.175 mm)."},
            "allow_rotation":  {"type": "boolean", "description": "Allow 90° rotation for 'none' grain parts (default true)."},
        },
    },
)


async def run_woodworking_nest_panels(params: dict[str, Any], ctx: Any) -> str:
    try:
        parts_raw = params.get("parts", [])
        parts = [
            PanelPart(
                part_id=p["part_id"],
                length_mm=float(p["length_mm"]),
                width_mm=float(p["width_mm"]),
                quantity=int(p.get("quantity", 1)),
                grain_direction=p.get("grain_direction", "none"),
                material=p.get("material", ""),
                description=p.get("description", ""),
            )
            for p in parts_raw
        ]
        result = optimise_panel_layout(
            parts,
            sheet_length_mm=float(params.get("sheet_length_mm", 2440.0)),
            sheet_width_mm=float(params.get("sheet_width_mm", 1220.0)),
            kerf_mm=float(params.get("kerf_mm", 3.175)),
            allow_rotation=bool(params.get("allow_rotation", True)),
        )
        return ok_payload(nesting_result_to_dict(result))
    except Exception as exc:
        return err_payload(str(exc), "NEST_PANELS_ERROR")


# ---------------------------------------------------------------------------
# Tool: woodworking_panel_shop_drawing
# ---------------------------------------------------------------------------

_panel_drawing_spec = ToolSpec(
    name="woodworking_panel_shop_drawing",
    description=(
        "Generate shop drawing data for a flat panel. "
        "Returns orthographic views (front, side) with dimensions, bore holes, "
        "edge banding indicators, grain arrow, and BOM. "
        "Output is JSON-serialisable for SVG rendering or DXF export. "
        "Ref: AWI (2014) §11; KCMA (2021) §5."
    ),
    input_schema={
        "type": "object",
        "required": ["part_id", "length_mm", "width_mm"],
        "properties": {
            "part_id":        {"type": "string"},
            "length_mm":      {"type": "number"},
            "width_mm":       {"type": "number"},
            "thickness_mm":   {"type": "number", "description": "Panel thickness (default 19 mm = 3/4\")."},
            "description":    {"type": "string"},
            "grain_direction": {
                "type": "string", "enum": ["length", "width", "none"],
                "description": "Grain direction shown as arrow (default 'length').",
            },
            "holes": {
                "type": "array",
                "description": "Bore holes from bore_pattern_to_dict: [{x, y, diameter_mm, depth_mm, kind, label}].",
                "items": {"type": "object"},
            },
            "edge_banding": {
                "type": "object",
                "description": "Edge banding per side: {top, bottom, left, right} → banding type string.",
                "additionalProperties": {"type": "string"},
            },
            "include_section": {"type": "boolean", "description": "Include cross-section view (default false)."},
        },
    },
)


async def run_woodworking_panel_shop_drawing(params: dict[str, Any], ctx: Any) -> str:
    try:
        drawing = panel_shop_drawing(
            part_id=params["part_id"],
            length_mm=float(params["length_mm"]),
            width_mm=float(params["width_mm"]),
            thickness_mm=float(params.get("thickness_mm", 19.0)),
            description=params.get("description", ""),
            holes=params.get("holes"),
            edge_banding=params.get("edge_banding"),
            grain_direction=params.get("grain_direction", "length"),
            include_section=bool(params.get("include_section", False)),
        )
        return ok_payload(shop_drawing_to_dict(drawing))
    except Exception as exc:
        return err_payload(str(exc), "PANEL_DRAWING_ERROR")


# ---------------------------------------------------------------------------
# Tool: woodworking_cabinet_shop_drawing
# ---------------------------------------------------------------------------

_cabinet_drawing_spec = ToolSpec(
    name="woodworking_cabinet_shop_drawing",
    description=(
        "Generate shop drawing data for a complete cabinet assembly. "
        "Returns front elevation, side elevation, plan view, and full BOM. "
        "Shows door, shelf, and toe-kick outlines per KCMA conventions. "
        "Output is JSON-serialisable for SVG rendering or DXF export. "
        "Ref: AWI (2014) §11; KCMA (2021) §5."
    ),
    input_schema={
        "type": "object",
        "required": ["cabinet_id", "cabinet_type", "width_mm", "height_mm", "depth_mm"],
        "properties": {
            "cabinet_id":    {"type": "string"},
            "cabinet_type":  {"type": "string", "enum": ["base", "wall", "tall"]},
            "width_mm":      {"type": "number"},
            "height_mm":     {"type": "number"},
            "depth_mm":      {"type": "number"},
            "material":      {"type": "string", "description": "Sheet material key (default birch_ply_3/4\")."},
            "door_count":    {"type": "integer", "minimum": 0, "description": "Number of doors (default 1)."},
            "shelf_count":   {"type": "integer", "minimum": 0, "description": "Number of shelves (default 1)."},
            "description":   {"type": "string"},
        },
    },
)


async def run_woodworking_cabinet_shop_drawing(params: dict[str, Any], ctx: Any) -> str:
    try:
        drawing = cabinet_shop_drawing(
            cabinet_id=params["cabinet_id"],
            cabinet_type=params["cabinet_type"],
            width_mm=float(params["width_mm"]),
            height_mm=float(params["height_mm"]),
            depth_mm=float(params["depth_mm"]),
            material=params.get("material", 'birch_ply_3/4"'),
            door_count=int(params.get("door_count", 1)),
            shelf_count=int(params.get("shelf_count", 1)),
            description=params.get("description", ""),
        )
        return ok_payload(shop_drawing_to_dict(drawing))
    except Exception as exc:
        return err_payload(str(exc), "CABINET_DRAWING_ERROR")


# ---------------------------------------------------------------------------
# TOOLS registry
# ---------------------------------------------------------------------------

TOOLS = [
    ("woodworking_estimate_project_cost", _cost_spec,          run_woodworking_estimate_project_cost),
    ("woodworking_nest_panels",           _nest_spec,           run_woodworking_nest_panels),
    ("woodworking_panel_shop_drawing",    _panel_drawing_spec,  run_woodworking_panel_shop_drawing),
    ("woodworking_cabinet_shop_drawing",  _cabinet_drawing_spec, run_woodworking_cabinet_shop_drawing),
]
