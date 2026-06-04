"""
kerf_woodworking.woodworking_advanced_tools — LLM tool wrappers for cabinet
cut-list, advanced joinery selection, and grain direction guidance.

Tools:
    woodworking_generate_cut_list       — cut-list from cabinet placements
    woodworking_select_joinery          — heuristic joint selector
    woodworking_joinery_machining_ops   — CAM operations for a joint
    woodworking_select_grain_direction  — grain direction for a part kind
    woodworking_grain_match_panels      — grain matching pairs for glued panels

References:
    KCMA (2021). Cabinet Standards.
    Stanley, J. (2010). Furniture Design & Construction for the Wood Worker.
    Hoadley, R.B. (2000). Understanding Wood, 2nd ed.

HONEST: All tools carry simplified-model caveats.
"""

from __future__ import annotations

import json
from typing import Any

from kerf_woodworking._compat import ToolSpec, err_payload, ok_payload

from kerf_woodworking.cabinet_cut_list import (
    CabinetPlacement,
    generate_cut_list,
)
from kerf_woodworking.joinery_advanced import (
    JoineryConnection,
    select_joinery,
    joinery_machining_operations,
)
from kerf_woodworking.grain_direction import (
    select_grain_direction,
    grain_match_panels,
    figure_type_properties,
    SPECIES_PROPERTIES,
    FigureType,
)
from kerf_woodworking.cabinet_cut_list import CutListItem


# ---------------------------------------------------------------------------
# Tool: woodworking_generate_cut_list
# ---------------------------------------------------------------------------

_cut_list_spec = ToolSpec(
    name="woodworking_generate_cut_list",
    description=(
        "Generate an optimised cabinet cut-list from cabinet placements. "
        "Decomposes each cabinet (base/wall/tall) into panels (sides, top, bottom, "
        "back, shelves, doors), packs onto 4×8 ft sheets using 2D bin-packing, "
        "and returns sheet counts, edge banding, waste %, and cost estimate. "
        "HONEST: simplified 2D bin-packing. "
        "Ref: KCMA 2021 Cabinet Standards; Stanley (2010)."
    ),
    input_schema={
        "type": "object",
        "required": ["cabinets"],
        "properties": {
            "cabinets": {
                "type": "array",
                "description": "List of cabinet placement specs.",
                "items": {
                    "type": "object",
                    "required": ["cabinet_id", "cabinet_type", "width_mm", "height_mm", "depth_mm"],
                    "properties": {
                        "cabinet_id":       {"type": "string"},
                        "cabinet_type":     {"type": "string", "enum": ["base", "wall", "tall"]},
                        "width_mm":         {"type": "number"},
                        "height_mm":        {"type": "number"},
                        "depth_mm":         {"type": "number"},
                        "material":         {"type": "string"},
                        "back_material":    {"type": "string"},
                        "door_count":       {"type": "integer", "minimum": 0},
                        "shelf_count":      {"type": "integer", "minimum": 0},
                        "edge_banding":     {"type": "string"},
                        "include_face_frame": {"type": "boolean"},
                    },
                },
                "minItems": 1,
            },
            "sheet_width_mm":  {"type": "number", "description": "Sheet width mm. Default 1220."},
            "sheet_height_mm": {"type": "number", "description": "Sheet height mm. Default 2440."},
        },
    },
)


async def run_woodworking_generate_cut_list(params: dict[str, Any], ctx: Any) -> str:
    """Execute cut-list generation."""
    try:
        cabs_raw = params["cabinets"]
        sheet_w = float(params.get("sheet_width_mm", 1220.0))
        sheet_h = float(params.get("sheet_height_mm", 2440.0))

        placements = []
        for c in cabs_raw:
            placements.append(CabinetPlacement(
                cabinet_id=c["cabinet_id"],
                cabinet_type=c["cabinet_type"],
                width_mm=float(c["width_mm"]),
                height_mm=float(c["height_mm"]),
                depth_mm=float(c["depth_mm"]),
                material=c.get("material", 'birch_ply_3/4"'),
                back_material=c.get("back_material", 'birch_ply_1/4"'),
                door_count=int(c.get("door_count", 1)),
                shelf_count=int(c.get("shelf_count", 1)),
                edge_banding=c.get("edge_banding", "pvc_white"),
                include_face_frame=bool(c.get("include_face_frame", False)),
            ))

        report = generate_cut_list(placements, sheet_size_mm=(sheet_w, sheet_h))

        result = {
            "item_count": len(report.items),
            "items": [
                {
                    "part_id": item.part_id,
                    "material": item.material,
                    "length_mm": round(item.length_mm, 1),
                    "width_mm": round(item.width_mm, 1),
                    "thickness_mm": item.thickness_mm,
                    "grain_direction": item.grain_direction,
                    "count": item.count,
                    "edge_banding": item.edge_banding,
                }
                for item in report.items
            ],
            "total_sheets_required": report.total_sheets_required,
            "total_lineal_meters_edge_banding": report.total_lineal_meters_edge_banding,
            "estimated_cost_usd": report.estimated_cost_usd,
            "waste_pct": report.waste_pct,
            "honest_caveat": report.honest_caveat,
        }
        return ok_payload(result)

    except Exception as exc:
        return err_payload(str(exc), "CUT_LIST_ERROR")


# ---------------------------------------------------------------------------
# Tool: woodworking_select_joinery
# ---------------------------------------------------------------------------

_select_joinery_spec = ToolSpec(
    name="woodworking_select_joinery",
    description=(
        "Heuristic joinery selector based on structural load and visibility. "
        "Returns recommended joint type: dovetail_half_blind, mortise_tenon, "
        "pocket_screw, biscuit_size_20, dowel, or loose_tenon. "
        "HONEST: heuristics only — not a structural calculation. "
        "Ref: Stanley (2010); Hoadley (2000); KCMA 2021."
    ),
    input_schema={
        "type": "object",
        "required": ["part_a", "part_b", "load_n"],
        "properties": {
            "part_a":   {"type": "string", "description": "Identifier of part A."},
            "part_b":   {"type": "string", "description": "Identifier of part B."},
            "load_n":   {"type": "number", "description": "Anticipated structural load (N)."},
            "location": {
                "type": "string",
                "enum": ["concealed", "visible", "structural"],
                "description": "Joint visibility context. Default: concealed.",
            },
        },
    },
)


async def run_woodworking_select_joinery(params: dict[str, Any], ctx: Any) -> str:
    try:
        jt = select_joinery(
            part_a=params["part_a"],
            part_b=params["part_b"],
            load_n=float(params["load_n"]),
            location=params.get("location", "concealed"),
        )
        return ok_payload({
            "joint_type": jt,
            "honest_caveat": (
                "Heuristic selection only. Structural connections require "
                "mechanical analysis. Ref: Stanley (2010); KCMA 2021."
            ),
        })
    except Exception as exc:
        return err_payload(str(exc), "JOINERY_SELECT_ERROR")


# ---------------------------------------------------------------------------
# Tool: woodworking_joinery_machining_ops
# ---------------------------------------------------------------------------

_machining_ops_spec = ToolSpec(
    name="woodworking_joinery_machining_ops",
    description=(
        "Return a list of machining / CAM operations for a specified joinery connection. "
        "Covers dovetail, mortise-tenon, biscuit, pocket-screw, dowel, and loose-tenon. "
        "HONEST: reference procedures only — actual CNC programs require full fixture analysis."
    ),
    input_schema={
        "type": "object",
        "required": ["joint_type", "part_a", "part_b"],
        "properties": {
            "joint_type": {
                "type": "string",
                "description": "One of: dovetail_half_blind, dovetail_through, mortise_tenon, "
                               "biscuit_size_0, biscuit_size_10, biscuit_size_20, "
                               "pocket_screw, dowel, loose_tenon.",
            },
            "part_a":     {"type": "string"},
            "part_b":     {"type": "string"},
            "location_3d": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Joint location [x, y, z] mm.",
            },
            "parameters": {
                "type": "object",
                "description": "Joint-specific parameters dict.",
            },
        },
    },
)


async def run_woodworking_joinery_machining_ops(params: dict[str, Any], ctx: Any) -> str:
    try:
        loc = tuple(params.get("location_3d", [0.0, 0.0, 0.0]))
        conn = JoineryConnection(
            joint_type=params["joint_type"],
            part_a=params["part_a"],
            part_b=params["part_b"],
            location_3d=loc,
            parameters=params.get("parameters", {}),
        )
        ops = joinery_machining_operations(conn)
        return ok_payload({
            "joint_type": conn.joint_type,
            "operation_count": len(ops),
            "operations": ops,
        })
    except Exception as exc:
        return err_payload(str(exc), "MACHINING_OPS_ERROR")


# ---------------------------------------------------------------------------
# Tool: woodworking_select_grain_direction
# ---------------------------------------------------------------------------

_grain_dir_spec = ToolSpec(
    name="woodworking_select_grain_direction",
    description=(
        "Return best-practice grain direction for a named part kind. "
        "Returns 'length' | 'width' | 'none'. "
        "Ref: Hoadley (2000); Stanley (2010); KCMA 2021. "
        "HONEST: guidelines only — inspect actual stock."
    ),
    input_schema={
        "type": "object",
        "required": ["part_kind"],
        "properties": {
            "part_kind": {
                "type": "string",
                "description": "Part kind, e.g. 'door_stile', 'table_top', 'shelf'.",
            },
        },
    },
)


async def run_woodworking_select_grain_direction(params: dict[str, Any], ctx: Any) -> str:
    try:
        direction = select_grain_direction(params["part_kind"])
        return ok_payload({
            "part_kind": params["part_kind"],
            "grain_direction": direction,
            "honest_caveat": (
                "Best-practice guideline per Hoadley (2000) and KCMA (2021). "
                "Always inspect actual lumber."
            ),
        })
    except Exception as exc:
        return err_payload(str(exc), "GRAIN_DIR_ERROR")


# ---------------------------------------------------------------------------
# Tool: woodworking_grain_match_panels
# ---------------------------------------------------------------------------

_grain_match_spec = ToolSpec(
    name="woodworking_grain_match_panels",
    description=(
        "Return recommended grain-matching pairs for glued-up panels. "
        "Supports book_match, slip_match, random. "
        "Ref: Hoadley (2000) p. 83; Stanley (2010). "
        "HONEST: pairs by list order only; real matching requires visual inspection."
    ),
    input_schema={
        "type": "object",
        "required": ["panels"],
        "properties": {
            "panels": {
                "type": "array",
                "description": "List of panel descriptors: [{part_id, grain_direction, length_mm, width_mm}].",
                "items": {
                    "type": "object",
                    "required": ["part_id"],
                    "properties": {
                        "part_id":         {"type": "string"},
                        "grain_direction": {"type": "string", "default": "length"},
                        "length_mm":       {"type": "number"},
                        "width_mm":        {"type": "number"},
                    },
                },
            },
            "match_kind": {
                "type": "string",
                "enum": ["book_match", "slip_match", "random"],
                "description": "Matching method. Default: book_match.",
            },
        },
    },
)


async def run_woodworking_grain_match_panels(params: dict[str, Any], ctx: Any) -> str:
    try:
        panels_raw = params["panels"]
        match_kind = params.get("match_kind", "book_match")

        # Build minimal CutListItem proxies
        panels = []
        for p in panels_raw:
            panels.append(CutListItem(
                part_id=p["part_id"],
                material="unknown",
                length_mm=float(p.get("length_mm", 100.0)),
                width_mm=float(p.get("width_mm", 100.0)),
                thickness_mm=19.0,
                grain_direction=p.get("grain_direction", "length"),
                count=1,
                edge_banding="none",
            ))

        pairs = grain_match_panels(panels, match_kind=match_kind)

        return ok_payload({
            "match_kind": match_kind,
            "pair_count": len(pairs),
            "pairs": [{"panel_a": a, "panel_b": b} for a, b in pairs],
            "honest_caveat": (
                "Pairs are by list order only. Real grain matching requires "
                "visual inspection of boards at the bench. "
                "Ref: Hoadley (2000); Stanley (2010)."
            ),
        })
    except Exception as exc:
        return err_payload(str(exc), "GRAIN_MATCH_ERROR")


# ---------------------------------------------------------------------------
# TOOLS registry
# ---------------------------------------------------------------------------

TOOLS = [
    ("woodworking_generate_cut_list",       _cut_list_spec,       run_woodworking_generate_cut_list),
    ("woodworking_select_joinery",          _select_joinery_spec, run_woodworking_select_joinery),
    ("woodworking_joinery_machining_ops",   _machining_ops_spec,  run_woodworking_joinery_machining_ops),
    ("woodworking_select_grain_direction",  _grain_dir_spec,      run_woodworking_select_grain_direction),
    ("woodworking_grain_match_panels",      _grain_match_spec,    run_woodworking_grain_match_panels),
]
