"""
LLM tool definitions for kerf-interior.

Each tool is registered via ``ToolSpec`` + an async handler.  The module is
importable standalone (uses ``_compat`` shims when ``kerf_chat`` is absent).
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_interior._compat import (  # type: ignore[assignment]
        ToolSpec, err_payload, ok_payload, register, ProjectCtx,
    )

from kerf_interior.clearance import (
    audit_clearances,
    check_corridor_clearance,
    check_knee_clearance,
    check_reach_range,
    check_turning_radius,
    turning_circle_diameter_mm,
    TURNING_CIRCLE_DIAMETER_MM,
    MIN_CORRIDOR_WIDTH_MM,
    MAX_REACH_HIGH_MM,
    MIN_REACH_LOW_MM,
)
from kerf_interior.furniture import make_chair, make_desk, make_sofa, make_table
from kerf_interior.space_planning import make_room


# ---------------------------------------------------------------------------
# interior_clearance_check
# ---------------------------------------------------------------------------

interior_clearance_check_spec = ToolSpec(
    name="interior_clearance_check",
    description=(
        "Check ADA / ANSI A117.1 dimensional clearances for an interior space. "
        "Pass any combination of turning_diameter_mm, corridor_widths_mm, "
        "knee_clearances, and reach_heights_mm.  Returns a list of violations "
        "(empty = compliant).  "
        f"Key limits: turning circle = {TURNING_CIRCLE_DIAMETER_MM:.0f} mm (60 in); "
        f"min corridor = {MIN_CORRIDOR_WIDTH_MM:.0f} mm (36 in); "
        f"max reach = {MAX_REACH_HIGH_MM:.0f} mm (48 in)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "turning_diameter_mm": {
                "type": "number",
                "description": (
                    "Diameter of the available wheelchair turning-circle in mm. "
                    "Must be >= 1524 mm to be compliant."
                ),
            },
            "corridor_widths_mm": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "List of corridor / aisle clear widths in mm. "
                    "Each must be >= 914 mm to be compliant."
                ),
            },
            "knee_clearances": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "height_mm": {"type": "number"},
                        "depth_mm": {"type": "number"},
                    },
                    "required": ["height_mm", "depth_mm"],
                },
                "description": (
                    "List of knee-clearance checks. Each requires height_mm >= 686 mm "
                    "and depth_mm >= 483 mm."
                ),
            },
            "reach_heights_mm": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Heights of controls / switches / outlets above finished floor in mm. "
                    "Each must be between 381 mm (15 in) and 1219 mm (48 in)."
                ),
            },
        },
    },
)


async def run_interior_clearance_check(ctx: ProjectCtx, params: dict) -> str:
    turning = params.get("turning_diameter_mm")
    corridors = params.get("corridor_widths_mm", [])
    knee_raw = params.get("knee_clearances", [])
    reaches = params.get("reach_heights_mm", [])

    knee_pairs = [(kc["height_mm"], kc["depth_mm"]) for kc in knee_raw]

    violations = audit_clearances(
        turning_diameter_mm=turning,
        corridor_widths_mm=corridors,
        knee_clearances=knee_pairs,
        reach_heights_mm=reaches,
    )

    result = {
        "compliant": len(violations) == 0,
        "violation_count": len(violations),
        "violations": [
            {
                "rule": v.rule,
                "actual_mm": round(v.actual_mm, 1),
                "limit_mm": round(v.limit_mm, 1),
                "message": v.message,
            }
            for v in violations
        ],
    }
    return ok_payload(result)


# ---------------------------------------------------------------------------
# interior_make_furniture
# ---------------------------------------------------------------------------

interior_make_furniture_spec = ToolSpec(
    name="interior_make_furniture",
    description=(
        "Generate a parametric FF&E item (chair, desk, sofa, or table). "
        "Returns a FurnitureItem JSON object with bounding-box dimensions and "
        "clearance zones.  Use with interior_room_layout to build a full space plan."
    ),
    input_schema={
        "type": "object",
        "required": ["kind"],
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["chair", "desk", "sofa", "table"],
                "description": "FF&E category.",
            },
            "name": {
                "type": "string",
                "description": "Label for this item (optional, defaults to category name).",
            },
            "width_mm": {"type": "number", "description": "Bounding-box width in mm."},
            "depth_mm": {"type": "number", "description": "Bounding-box depth in mm."},
            "height_mm": {"type": "number", "description": "Bounding-box height in mm."},
            "seats": {
                "type": "integer",
                "description": "Number of seats (sofa: 1-5; table: nominal capacity).",
            },
            "with_ada_clearance": {
                "type": "boolean",
                "description": "Apply ADA clear-floor zones (default true).",
            },
        },
    },
)


async def run_interior_make_furniture(ctx: ProjectCtx, params: dict) -> str:
    kind = params.get("kind")
    kw: dict[str, Any] = {}
    if "name" in params:
        kw["name"] = params["name"]
    if "width_mm" in params:
        kw["width_mm"] = float(params["width_mm"])
    if "depth_mm" in params:
        kw["depth_mm"] = float(params["depth_mm"])
    if "height_mm" in params:
        kw["height_mm"] = float(params["height_mm"])
    if "with_ada_clearance" in params:
        kw["with_ada_clearance"] = bool(params["with_ada_clearance"])
    if "seats" in params:
        kw["seats"] = int(params["seats"])

    try:
        if kind == "chair":
            item = make_chair(**kw)
        elif kind == "desk":
            item = make_desk(**kw)
        elif kind == "sofa":
            item = make_sofa(**kw)
        elif kind == "table":
            item = make_table(**kw)
        else:
            return err_payload(f"Unknown furniture kind: {kind!r}", "BAD_ARGS")
    except (ValueError, TypeError) as exc:
        return err_payload(str(exc), "BAD_ARGS")

    return ok_payload(item.to_dict())


# ---------------------------------------------------------------------------
# interior_room_layout
# ---------------------------------------------------------------------------

interior_room_layout_spec = ToolSpec(
    name="interior_room_layout",
    description=(
        "Create a room layout, place furniture, define circulation paths, and "
        "run a full ADA audit.  Returns a summary with all clearance violations."
    ),
    input_schema={
        "type": "object",
        "required": ["name", "width_mm", "depth_mm"],
        "properties": {
            "name": {"type": "string", "description": "Room name."},
            "width_mm": {"type": "number", "description": "Interior room width in mm."},
            "depth_mm": {"type": "number", "description": "Interior room depth in mm."},
            "ceiling_height_mm": {
                "type": "number",
                "description": "Interior ceiling height in mm (default 2700).",
            },
            "circulation_paths": {
                "type": "array",
                "description": "Named aisles / corridors to check.",
                "items": {
                    "type": "object",
                    "required": ["name", "start", "end", "clear_width_mm"],
                    "properties": {
                        "name": {"type": "string"},
                        "start": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "end": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 2,
                            "maxItems": 2,
                        },
                        "clear_width_mm": {"type": "number"},
                    },
                },
            },
            "turning_diameter_mm": {
                "type": "number",
                "description": "Turning-circle diameter to check (optional).",
            },
            "reach_heights_mm": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Control/outlet heights to check for reach range.",
            },
        },
    },
)


async def run_interior_room_layout(ctx: ProjectCtx, params: dict) -> str:
    try:
        room = make_room(
            params["name"],
            float(params["width_mm"]),
            float(params["depth_mm"]),
            ceiling_height_mm=float(params.get("ceiling_height_mm", 2700.0)),
        )
    except (ValueError, TypeError, KeyError) as exc:
        return err_payload(str(exc), "BAD_ARGS")

    for cp in params.get("circulation_paths", []):
        try:
            room.add_circulation_path(
                cp["name"],
                tuple(cp["start"]),
                tuple(cp["end"]),
                float(cp["clear_width_mm"]),
            )
        except (ValueError, TypeError, KeyError) as exc:
            return err_payload(f"Invalid circulation_path: {exc}", "BAD_ARGS")

    summary = room.audit_all(
        turning_diameter_mm=params.get("turning_diameter_mm"),
        reach_heights_mm=params.get("reach_heights_mm", []),
    )

    result = room.summary()
    return ok_payload(result)


# ---------------------------------------------------------------------------
# TOOLS registry list (for plugin loader)
# ---------------------------------------------------------------------------

TOOLS = [
    ("interior_clearance_check", interior_clearance_check_spec, run_interior_clearance_check),
    ("interior_make_furniture", interior_make_furniture_spec, run_interior_make_furniture),
    ("interior_room_layout", interior_room_layout_spec, run_interior_room_layout),
]
