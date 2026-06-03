"""
kerf_cad_core.woodworking.cabinet_room_layout_tools — LLM tool wrappers for
Mozaik-style cabinet room layout.

Registers two tools with the Kerf tool registry:

  woodworking_auto_layout_cabinets   — Pack standard-sized cabinets along selected
                                       room walls (NKBA Planning Guidelines 2021;
                                       ANSI A117.1-2017 §1003 accessibility;
                                       Mozaik cabinet line placement §3).

  woodworking_detect_collisions      — Report overlapping cabinet placements.

All tools are pure-Python; no OCC dependency.
Inputs validated; errors returned as {ok: false, reason: ...} — never raises.

References
----------
  NKBA Planning Guidelines 2021.  National Kitchen & Bath Association, Hackettstown NJ.
  ANSI A117.1-2017, "Accessible and Usable Buildings and Facilities", §1003.
  Mozaik Cabinet Software, "Cabinet Design Manual §3 — Wall-span placement."

Author: imranparuk
"""
from __future__ import annotations

import json
from dataclasses import asdict

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.woodworking.cabinet_room_layout import (
    CabinetUnit,
    CabinetPlacement,
    Room,
    auto_layout_cabinets,
    detect_cabinet_collisions,
)


# ---------------------------------------------------------------------------
# Tool: woodworking_auto_layout_cabinets
# ---------------------------------------------------------------------------

_layout_spec = ToolSpec(
    name="woodworking_auto_layout_cabinets",
    description=(
        "Pack standard cabinet units along selected room walls using first-fit-decreasing\n"
        "bin-packing (NKBA Planning Guidelines 2021; Mozaik Cabinet Software §3).\n"
        "\n"
        "For each selected wall:\n"
        "  1. Compute blocked intervals from door/window openings + clearance\n"
        "     (NKBA Guideline 5 — clearance to each side of every opening)\n"
        "  2. First-fit-decreasing pack the cabinet library into free spans\n"
        "  3. Report placements, lineal metres, waste corners, collision count\n"
        "\n"
        "Accessibility: ANSI A117.1-2017 §1003.12 requires 1524 mm (60″) turning\n"
        "radius in kitchens — user should verify clearance from placements.\n"
        "\n"
        "Input:\n"
        "  room.name                : string\n"
        "  room.outline             : [[x,y]...] metres (CCW polygon, ≥ 3 vertices)\n"
        "  room.ceiling_height_m    : number\n"
        "  room.openings            : [{type, wall_index, position_m, width_m, height_m}]\n"
        "  cabinet_library          : [{sku, width_m, depth_m, height_m, kind}]\n"
        "  along_walls              : [int] or null (default: all walls)\n"
        "  min_clearance_to_openings_m : number (default 0.15 m per NKBA Guideline 5)\n"
        "\n"
        "Returns {ok, n_units, total_lineal_meters, waste_corner_count,\n"
        "         collision_count, door_window_clearance_ok, placements[]}.\n"
        "Each placement: {sku, position:[x,y,z], rotation_deg, width_m, depth_m, height_m, kind}.\n"
        "\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "room": {
                "type": "object",
                "description": "Room definition.",
                "properties": {
                    "name": {"type": "string"},
                    "outline": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                        "minItems": 3,
                        "description": "Closed polygon [[x,y]...] in metres (CCW).",
                    },
                    "ceiling_height_m": {"type": "number"},
                    "openings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": ["door", "window"]},
                                "wall_index": {"type": "integer"},
                                "position_m": {"type": "number"},
                                "width_m": {"type": "number"},
                                "height_m": {"type": "number"},
                            },
                        },
                    },
                },
                "required": ["outline"],
            },
            "cabinet_library": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sku": {"type": "string"},
                        "width_m": {"type": "number"},
                        "depth_m": {"type": "number"},
                        "height_m": {"type": "number"},
                        "kind": {"type": "string"},
                    },
                    "required": ["sku", "width_m", "depth_m", "height_m"],
                },
                "minItems": 1,
            },
            "along_walls": {
                "type": ["array", "null"],
                "items": {"type": "integer"},
                "description": "Wall indices to fill (default: all walls).",
            },
            "min_clearance_to_openings_m": {
                "type": "number",
                "description": "Clearance to openings in metres (default 0.15 m, NKBA Guideline 5).",
            },
        },
        "required": ["room", "cabinet_library"],
    },
)


@register(_layout_spec, write=False)
async def run_woodworking_auto_layout_cabinets(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    # Parse room
    raw_room = a.get("room")
    if raw_room is None:
        return err_payload("room is required", "BAD_ARGS")

    try:
        raw_outline = raw_room.get("outline", [])
        outline = [(float(v[0]), float(v[1])) for v in raw_outline]
        if len(outline) < 3:
            return err_payload("room.outline must have ≥ 3 vertices", "BAD_ARGS")
    except (TypeError, IndexError, ValueError) as exc:
        return err_payload(f"room.outline parse error: {exc}", "BAD_ARGS")

    openings = raw_room.get("openings") or []
    room = Room(
        name=str(raw_room.get("name", "room")),
        outline=outline,
        ceiling_height_m=float(raw_room.get("ceiling_height_m", 2.4)),
        openings=openings,
    )

    # Parse cabinet library
    raw_lib = a.get("cabinet_library")
    if not raw_lib:
        return err_payload("cabinet_library must have ≥ 1 unit", "BAD_ARGS")

    try:
        library = [
            CabinetUnit(
                sku=str(u.get("sku", f"CAB-{i}")),
                width_m=float(u["width_m"]),
                depth_m=float(u["depth_m"]),
                height_m=float(u["height_m"]),
                kind=str(u.get("kind", "base")),
            )
            for i, u in enumerate(raw_lib)
        ]
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(f"cabinet_library parse error: {exc}", "BAD_ARGS")

    along_walls = a.get("along_walls")  # None or list[int]
    clearance = float(a.get("min_clearance_to_openings_m", 0.15))

    try:
        report = auto_layout_cabinets(room, library, along_walls, clearance)
    except Exception as exc:
        return err_payload(f"layout error: {exc}", "LAYOUT_ERROR")

    placements_out = [
        {
            "sku": pl.unit.sku,
            "position": list(pl.position),
            "rotation_deg": pl.rotation_deg,
            "width_m": pl.unit.width_m,
            "depth_m": pl.unit.depth_m,
            "height_m": pl.unit.height_m,
            "kind": pl.unit.kind,
        }
        for pl in report.placements
    ]

    return ok_payload({
        "ok": True,
        "n_units": report.n_units,
        "total_lineal_meters": report.total_lineal_meters,
        "waste_corner_count": report.waste_corner_count,
        "collision_count": report.collision_count,
        "door_window_clearance_ok": report.door_window_clearance_ok,
        "placements": placements_out,
        "note": (
            "FFD packing per NKBA Planning Guidelines 2021. "
            "Verify ANSI A117.1-2017 §1003 turning radius (1524 mm) manually."
        ),
    })


# ---------------------------------------------------------------------------
# Tool: woodworking_detect_collisions
# ---------------------------------------------------------------------------

_collision_spec = ToolSpec(
    name="woodworking_detect_collisions",
    description=(
        "Detect overlapping cabinet placements in plan view (XY axis-aligned bounding boxes).\n"
        "\n"
        "Input: placements array with {position:[x,y,z], rotation_deg, width_m, depth_m, height_m}.\n"
        "Returns {ok, collision_count, collision_pairs:[[i,j]...]}.\n"
        "collision_pairs contains 0-based indices of overlapping cabinet pairs.\n"
        "\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "placements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sku": {"type": "string"},
                        "position": {"type": "array", "items": {"type": "number"}, "minItems": 3},
                        "rotation_deg": {"type": "number"},
                        "width_m": {"type": "number"},
                        "depth_m": {"type": "number"},
                        "height_m": {"type": "number"},
                        "kind": {"type": "string"},
                    },
                    "required": ["position", "width_m", "depth_m", "height_m"],
                },
                "minItems": 2,
            },
        },
        "required": ["placements"],
    },
)


@register(_collision_spec, write=False)
async def run_woodworking_detect_collisions(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_placements = a.get("placements")
    if not raw_placements:
        return err_payload("placements is required and must have ≥ 2 items", "BAD_ARGS")

    try:
        placements = [
            CabinetPlacement(
                unit=CabinetUnit(
                    sku=str(p.get("sku", f"CAB-{i}")),
                    width_m=float(p["width_m"]),
                    depth_m=float(p["depth_m"]),
                    height_m=float(p["height_m"]),
                    kind=str(p.get("kind", "base")),
                ),
                position=(float(p["position"][0]), float(p["position"][1]), float(p["position"][2])),
                rotation_deg=float(p.get("rotation_deg", 0.0)),
            )
            for i, p in enumerate(raw_placements)
        ]
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        return err_payload(f"placements parse error: {exc}", "BAD_ARGS")

    pairs = detect_cabinet_collisions(placements)

    return ok_payload({
        "ok": True,
        "collision_count": len(pairs),
        "collision_pairs": [list(p) for p in pairs],
        "note": (
            "AABB overlap test in plan view. "
            "Zero collisions required for valid Mozaik-style cabinet layout (§3)."
        ),
    })
