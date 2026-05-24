"""
space.py — LLM tools for BIM space / zone / room objects.

Tools
-----
bim_create_space   — create a named space with boundary polygon, level, height
bim_space_schedule — generate an area/occupancy schedule from a BIM model
"""
from __future__ import annotations

import json
import uuid

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:  # compat shim for test environments
    from kerf_bim.tools._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # type: ignore


# ---------------------------------------------------------------------------
# bim_create_space
# ---------------------------------------------------------------------------

_create_space_spec = ToolSpec(
    name="bim_create_space",
    description=(
        "Create a BIM space / zone / room object (IfcSpace) "
        "with a plan-view boundary polygon, level assignment, ceiling height, "
        "and optional occupancy program. "
        "Returns computed area (m²), volume (m³), and occupancy. "
        "Spaces are automatically included in IFC export and area schedules."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Room / space name, e.g. 'Living Room', 'Office 1'.",
            },
            "level": {
                "type": "string",
                "description": "Storey name, e.g. 'L1', 'Ground Floor'.",
                "default": "L1",
            },
            "boundary": {
                "type": "array",
                "description": (
                    "Plan-view boundary polygon as [[x, y], ...] in metres. "
                    "Minimum 3 points; no closing duplicate needed."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 3,
            },
            "height_m": {
                "type": "number",
                "description": "Floor-to-ceiling height in metres (default 2.7).",
                "default": 2.7,
            },
            "program": {
                "type": "string",
                "description": "Occupancy program category, e.g. 'residential', 'office', 'retail', 'circulation'.",
                "default": "residential",
            },
            "occupancy_per_m2": {
                "type": "number",
                "description": "Occupancy density in persons/m² for code compliance (optional).",
            },
        },
        "required": ["name", "boundary"],
    },
)


@register(_create_space_spec, write=False)
async def run_bim_create_space(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    name = (a.get("name") or "").strip()
    if not name:
        return err_payload("name is required", "BAD_ARGS")

    boundary_raw = a.get("boundary")
    if not isinstance(boundary_raw, list) or len(boundary_raw) < 3:
        return err_payload("boundary must be an array of at least 3 [x, y] points", "BAD_ARGS")

    try:
        boundary = [[float(p[0]), float(p[1])] for p in boundary_raw]
    except (TypeError, ValueError, IndexError) as exc:
        return err_payload(f"boundary points must be [x, y] numbers: {exc}", "BAD_ARGS")

    height_m = float(a.get("height_m") or 2.7)
    if height_m <= 0:
        return err_payload("height_m must be positive", "BAD_ARGS")

    program = str(a.get("program") or "residential")
    level = str(a.get("level") or "L1")
    occ_density = a.get("occupancy_per_m2")
    if occ_density is not None:
        try:
            occ_density = float(occ_density)
        except (TypeError, ValueError):
            return err_payload("occupancy_per_m2 must be a number", "BAD_ARGS")

    try:
        from kerf_bim.spaces import Space, SpaceValidationError
        sp = Space(
            name=name,
            boundary=boundary,
            level=level,
            height_m=height_m,
            program=program,
            occupancy_per_m2=occ_density,
        )
        return ok_payload(sp.to_dict())
    except Exception as exc:
        return err_payload(str(exc), "ERROR")


# ---------------------------------------------------------------------------
# bim_space_schedule
# ---------------------------------------------------------------------------

_space_schedule_spec = ToolSpec(
    name="bim_space_schedule",
    description=(
        "Generate a BIM area / occupancy schedule from a list of space definitions. "
        "Returns per-space rows (name, level, area, volume, occupancy) plus "
        "totals and per-level subtotals. "
        "Conforms to IfcElementQuantity / IfcAreaMeasure conventions from ISO 16739-1:2018."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "spaces": {
                "type": "array",
                "description": "Array of space objects, each with name, boundary, level, height_m, program.",
                "items": {
                    "type": "object",
                    "properties": {
                        "name":    {"type": "string"},
                        "level":   {"type": "string"},
                        "boundary": {
                            "type": "array",
                            "items": {"type": "array", "items": {"type": "number"}},
                        },
                        "height_m": {"type": "number"},
                        "program":  {"type": "string"},
                        "occupancy_per_m2": {"type": "number"},
                    },
                    "required": ["name", "boundary"],
                },
                "minItems": 1,
            },
        },
        "required": ["spaces"],
    },
)


@register(_space_schedule_spec, write=False)
async def run_bim_space_schedule(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    spaces_raw = a.get("spaces")
    if not isinstance(spaces_raw, list) or len(spaces_raw) == 0:
        return err_payload("spaces must be a non-empty array", "BAD_ARGS")

    try:
        from kerf_bim.spaces import Space, SpaceValidationError, space_schedule
        space_objs = []
        for i, s in enumerate(spaces_raw):
            try:
                sp = Space(
                    name=str(s.get("name") or f"Space {i+1}"),
                    boundary=[[float(p[0]), float(p[1])] for p in (s.get("boundary") or [])],
                    level=str(s.get("level") or "L1"),
                    height_m=float(s.get("height_m") or 2.7),
                    program=str(s.get("program") or "residential"),
                    occupancy_per_m2=(
                        float(s["occupancy_per_m2"])
                        if s.get("occupancy_per_m2") is not None
                        else None
                    ),
                )
                space_objs.append(sp)
            except (SpaceValidationError, ValueError, TypeError, IndexError) as exc:
                return err_payload(f"space[{i}] invalid: {exc}", "BAD_ARGS")

        result = space_schedule(space_objs)
        return ok_payload(result)
    except Exception as exc:
        return err_payload(str(exc), "ERROR")
