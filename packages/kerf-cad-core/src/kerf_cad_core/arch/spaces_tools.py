"""
kerf_cad_core.arch.spaces_tools
=================================

LLM tool wrappers for room / space area analysis and building area schedules.

Registers three tools with the Kerf tool registry:

  arch_room            — compute area, perimeter, occupancy load and egress
                         width for a single room from its boundary polygon
  arch_area_schedule   — rollup building area schedule from a list of rooms
  arch_occupancy_load  — compute occupant load for a given area + occupancy type

All dimensions are in **millimetres** (areas in mm²).
Returns {ok: false, reason: ...} on bad input; never raises.
Load factors: nominal IBC Table 1004.5 values (cited in kerf_cad_core.arch.spaces).
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.arch.spaces import (
    OCCUPANCY_LOAD_FACTORS,
    compute_room,
    compute_area_schedule,
    compute_occupancy_load,
)

_OCCUPANCY_ENUM = sorted(OCCUPANCY_LOAD_FACTORS.keys())

# ---------------------------------------------------------------------------
# Tool: arch_room
# ---------------------------------------------------------------------------

_arch_room_spec = ToolSpec(
    name="arch_room",
    description=(
        "Compute the area, perimeter, occupancy load, and required egress "
        "width for a single room defined by its closed boundary polygon. "
        "All dimensions in millimetres; areas returned in both mm² and m². "
        "Occupancy load = ceil(net_area_m2 / IBC_factor). "
        "Egress width factors: nominal IBC § 1005.1 values "
        "(0.3 mm/person for stairways, 0.2 mm/person for other means). "
        "Load factors: nominal IBC Table 1004.5 values. "
        "Returns {ok: false, errors: [...]} for self-intersecting or "
        "degenerate polygons; never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "polygon": {
                "type": "array",
                "description": (
                    "Closed room boundary polygon as [[x1,y1],[x2,y2],...] in mm. "
                    "Minimum 3 vertices. CW or CCW — both accepted."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 3,
            },
            "name": {
                "type": "string",
                "description": "Human-readable room name, e.g. 'Office 101'.",
            },
            "occupancy": {
                "type": "string",
                "enum": _OCCUPANCY_ENUM,
                "description": (
                    "IBC occupancy classification for load-factor lookup. "
                    "Nominal IBC Table 1004.5 values. "
                    "Options include: business (9.3 m²/person), "
                    "mercantile (2.79 m²/person), "
                    "residential (18.58 m²/person), "
                    "assembly_concentrated (0.65 m²/person), etc."
                ),
            },
            "wall_thickness": {
                "type": "number",
                "description": (
                    "Wall thickness in mm used to compute net area from gross area "
                    "via the approximation: net = gross − perimeter × (thickness/2). "
                    "Default 0 (net == gross)."
                ),
            },
            "level": {
                "type": "string",
                "description": (
                    "Floor / level label for area schedule grouping, "
                    "e.g. 'L1', 'Ground Floor', 'Level 2'. Default ''."
                ),
            },
        },
        "required": ["polygon", "name", "occupancy"],
    },
)


@register(_arch_room_spec, write=False)
async def run_arch_room(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = compute_room(
        polygon=a.get("polygon"),
        name=a.get("name", ""),
        occupancy=a.get("occupancy", ""),
        wall_thickness=a.get("wall_thickness", 0.0),
        level=a.get("level", ""),
    )
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: arch_area_schedule
# ---------------------------------------------------------------------------

_arch_area_schedule_spec = ToolSpec(
    name="arch_area_schedule",
    description=(
        "Produce a building area schedule from a list of rooms. "
        "Rolls up total gross area, net area, and occupant load for the whole "
        "building and broken down by level and by occupancy type. "
        "Each room must be a successful output of arch_room (ok=true). "
        "Returns {ok: false, errors: [...]} if any room dict is invalid. "
        "Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "rooms": {
                "type": "array",
                "description": (
                    "List of room dicts — outputs of arch_room (each must have ok=true). "
                    "Pass an empty list to get an empty schedule."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["rooms"],
    },
)


@register(_arch_area_schedule_spec, write=False)
async def run_arch_area_schedule(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    rooms = a.get("rooms")
    if not isinstance(rooms, list):
        return err_payload("'rooms' must be a list", "BAD_ARGS")

    result = compute_area_schedule(rooms)
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: arch_occupancy_load
# ---------------------------------------------------------------------------

_arch_occupancy_load_spec = ToolSpec(
    name="arch_occupancy_load",
    description=(
        "Compute occupant load and required egress width for a given floor area "
        "and occupancy type, without needing a full polygon. "
        "Occupant load = ceil(area_m2 / IBC_factor). "
        "Egress width: nominal IBC § 1005.1 (0.3 mm/person for stairways, "
        "0.2 mm/person for other means). "
        "Load factors: nominal IBC Table 1004.5 values. "
        "Returns {ok: false, errors: [...]} on invalid input; never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "area_m2": {
                "type": "number",
                "description": "Floor area in square metres (m²). Must be >= 0.",
            },
            "occupancy": {
                "type": "string",
                "enum": _OCCUPANCY_ENUM,
                "description": (
                    "IBC occupancy classification. "
                    "Nominal IBC Table 1004.5 values. "
                    "E.g. 'business', 'mercantile', 'assembly_concentrated'."
                ),
            },
            "use_net": {
                "type": "boolean",
                "description": (
                    "Label the supplied area as 'net' (true, default) or 'gross' (false). "
                    "Does not affect the numeric calculation."
                ),
            },
        },
        "required": ["area_m2", "occupancy"],
    },
)


@register(_arch_occupancy_load_spec, write=False)
async def run_arch_occupancy_load(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = compute_occupancy_load(
        area_m2=a.get("area_m2"),
        occupancy=a.get("occupancy", ""),
        use_net=a.get("use_net", True),
    )
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)
