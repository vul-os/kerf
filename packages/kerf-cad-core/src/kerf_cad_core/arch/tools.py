"""
kerf_cad_core.arch.tools — LLM tool wrappers for parametric BIM primitives.

Registers seven tools with the Kerf tool registry:

  arch_wall               — parametric wall (baseline + height + optional layers)
  arch_door               — door hosted in a wall
  arch_window             — window hosted in a wall (adds sill height)
  arch_slab               — horizontal slab from polygon outline + thickness
  arch_opening            — generic rectangular or arched void in a wall
  arch_wall_with_openings — compose a wall + hosted doors/windows; compute net volume
  arch_check_stair_codes  — IBC/ADA/ICC A117.1/OBC stair code-compliance check

All tools are **pure-Python**; no OCC dependency, no DB write required.
All dimensions are in **millimetres** throughout (except arch_check_stair_codes
which uses **inches** to match IBC/ADA source publications).
Returns {ok: bool, errors: [...]} on bad input; never raises.
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.arch.primitives import (
    build_wall,
    build_door,
    build_window,
    build_slab,
    build_opening,
    compose_wall_with_openings,
)
from kerf_cad_core.arch.stair_code_check import (  # noqa: E402
    StairCodeSpec,
    check_stair_codes,
)


# ---------------------------------------------------------------------------
# Tool: arch_wall
# ---------------------------------------------------------------------------

_arch_wall_spec = ToolSpec(
    name="arch_wall",
    description=(
        "Create a parametric architectural wall recipe. "
        "All dimensions in millimetres. "
        "Returns the wall's length, gross area, and gross volume. "
        "Optionally accepts a layers list for composite (e.g. brick/insulation/plaster) "
        "walls — layer thicknesses are summed to produce total_thickness. "
        "No OCC geometry is produced here; the recipe drives a downstream worker. "
        "Use arch_wall_with_openings to subtract doors/windows from the wall volume."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "start": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
                "description": "Baseline start point [x, y] in mm (plan view, Z=0 datum).",
            },
            "end": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
                "description": "Baseline end point [x, y] in mm.",
            },
            "height": {
                "type": "number",
                "description": "Wall height in mm. Must be > 0.",
            },
            "thickness": {
                "type": "number",
                "description": (
                    "Total wall thickness in mm. Required unless 'layers' is provided. "
                    "If layers are provided, thickness is derived as the sum of layer "
                    "thicknesses and this field is ignored."
                ),
            },
            "layers": {
                "type": "array",
                "description": (
                    "Optional ordered list of material layers (exterior → interior). "
                    "Each layer: {name: str, thickness: float (mm)}. "
                    "Example: [{name:'brick', thickness:110}, "
                    "{name:'insulation', thickness:75}, {name:'plaster', thickness:15}]. "
                    "If provided, total thickness = sum of layer thicknesses."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "thickness": {"type": "number"},
                    },
                    "required": ["name", "thickness"],
                },
            },
            "id": {
                "type": "string",
                "description": "Optional wall identifier for cross-referencing openings.",
            },
        },
        "required": ["start", "end", "height"],
    },
)


@register(_arch_wall_spec, write=False)
async def run_arch_wall(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = build_wall(
        start=a.get("start"),
        end=a.get("end"),
        height=a.get("height"),
        thickness=a.get("thickness"),
        layers=a.get("layers"),
        id=str(a.get("id", "")),
    )
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: arch_door
# ---------------------------------------------------------------------------

_arch_door_spec = ToolSpec(
    name="arch_door",
    description=(
        "Create a parametric door hosted in a wall. "
        "All dimensions in millimetres. "
        "Returns cut-box parameters (the rectangular void to subtract from the wall), "
        "the opening volume, and panel parameters. "
        "Validates that the door fits within the wall extents; "
        "returns {ok: false, errors: [...]} if it does not. "
        "swing options: 'hinged_left', 'hinged_right', 'double', 'sliding', "
        "'folding', 'pivot'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "width": {
                "type": "number",
                "description": "Door clear opening width in mm. Must be > 0.",
            },
            "height": {
                "type": "number",
                "description": "Door clear opening height in mm. Must be > 0.",
            },
            "wall_ref": {
                "type": "string",
                "description": "ID of the host wall (from arch_wall output).",
            },
            "position_along_wall": {
                "type": "number",
                "description": (
                    "Distance from the wall baseline start point to the near "
                    "edge of the door opening, measured along the wall in mm. "
                    "Must be >= 0."
                ),
            },
            "wall_length": {
                "type": "number",
                "description": "Total host wall baseline length in mm (from arch_wall output).",
            },
            "wall_height": {
                "type": "number",
                "description": "Host wall height in mm.",
            },
            "wall_thickness": {
                "type": "number",
                "description": "Host wall total thickness in mm.",
            },
            "swing": {
                "type": "string",
                "enum": ["hinged_left", "hinged_right", "double", "sliding", "folding", "pivot"],
                "description": "Door operation type. Default 'hinged_left'.",
            },
            "id": {
                "type": "string",
                "description": "Optional door identifier.",
            },
        },
        "required": ["width", "height", "wall_ref", "position_along_wall",
                     "wall_length", "wall_height", "wall_thickness"],
    },
)


@register(_arch_door_spec, write=False)
async def run_arch_door(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = build_door(
        width=a.get("width"),
        height=a.get("height"),
        wall_ref=a.get("wall_ref", ""),
        position_along_wall=a.get("position_along_wall"),
        wall_length=a.get("wall_length"),
        wall_height=a.get("wall_height"),
        wall_thickness=a.get("wall_thickness"),
        swing=a.get("swing", "hinged_left"),
        id=str(a.get("id", "")),
    )
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: arch_window
# ---------------------------------------------------------------------------

_arch_window_spec = ToolSpec(
    name="arch_window",
    description=(
        "Create a parametric window hosted in a wall. "
        "All dimensions in millimetres. "
        "Returns cut-box parameters, opening volume, and panel parameters. "
        "Validates that the window (sill height + height) fits within the wall height "
        "and that the horizontal extent fits within the wall length. "
        "Returns {ok: false, errors: [...]} if it does not. "
        "operation options: 'fixed', 'casement', 'sliding', 'awning', "
        "'hopper', 'tilt_turn', 'louvre'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "width": {
                "type": "number",
                "description": "Window clear opening width in mm. Must be > 0.",
            },
            "height": {
                "type": "number",
                "description": "Window clear opening height in mm. Must be > 0.",
            },
            "sill_height": {
                "type": "number",
                "description": (
                    "Height of the window sill above the floor level in mm. "
                    "Must be >= 0. Typical residential: 900 mm."
                ),
            },
            "wall_ref": {
                "type": "string",
                "description": "ID of the host wall (from arch_wall output).",
            },
            "position_along_wall": {
                "type": "number",
                "description": (
                    "Distance from the wall baseline start point to the near "
                    "edge of the window opening, measured along the wall in mm. "
                    "Must be >= 0."
                ),
            },
            "wall_length": {
                "type": "number",
                "description": "Total host wall baseline length in mm.",
            },
            "wall_height": {
                "type": "number",
                "description": "Host wall height in mm.",
            },
            "wall_thickness": {
                "type": "number",
                "description": "Host wall total thickness in mm.",
            },
            "operation": {
                "type": "string",
                "enum": ["fixed", "casement", "sliding", "awning", "hopper",
                         "tilt_turn", "louvre"],
                "description": "Window operation type. Default 'casement'.",
            },
            "id": {
                "type": "string",
                "description": "Optional window identifier.",
            },
        },
        "required": ["width", "height", "sill_height", "wall_ref",
                     "position_along_wall", "wall_length", "wall_height",
                     "wall_thickness"],
    },
)


@register(_arch_window_spec, write=False)
async def run_arch_window(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = build_window(
        width=a.get("width"),
        height=a.get("height"),
        sill_height=a.get("sill_height"),
        wall_ref=a.get("wall_ref", ""),
        position_along_wall=a.get("position_along_wall"),
        wall_length=a.get("wall_length"),
        wall_height=a.get("wall_height"),
        wall_thickness=a.get("wall_thickness"),
        operation=a.get("operation", "casement"),
        id=str(a.get("id", "")),
    )
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: arch_slab
# ---------------------------------------------------------------------------

_arch_slab_spec = ToolSpec(
    name="arch_slab",
    description=(
        "Create a parametric horizontal slab (floor/ceiling/roof deck) from a "
        "polygon outline and thickness. "
        "All dimensions in millimetres. "
        "Area is computed using the shoelace formula; volume = area × thickness. "
        "The polygon may be CW or CCW; both work correctly."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "outline": {
                "type": "array",
                "description": (
                    "Plan-view polygon vertices as [[x1,y1],[x2,y2],...] in mm. "
                    "Minimum 3 vertices. The polygon is automatically closed."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 3,
            },
            "thickness": {
                "type": "number",
                "description": "Slab thickness in mm. Must be > 0.",
            },
            "level": {
                "type": "number",
                "description": (
                    "Z-elevation of the slab top surface in mm. "
                    "Default 0. Use positive values for upper floors "
                    "(e.g. 3000 mm for a 3 m first floor)."
                ),
            },
            "id": {
                "type": "string",
                "description": "Optional slab identifier.",
            },
        },
        "required": ["outline", "thickness"],
    },
)


@register(_arch_slab_spec, write=False)
async def run_arch_slab(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = build_slab(
        outline=a.get("outline"),
        thickness=a.get("thickness"),
        level=a.get("level", 0.0),
        id=str(a.get("id", "")),
    )
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: arch_opening
# ---------------------------------------------------------------------------

_arch_opening_spec = ToolSpec(
    name="arch_opening",
    description=(
        "Create a generic parametric void (opening) cut into a wall. "
        "All dimensions in millimetres. "
        "Supports rectangular and arched (semicircular head) opening types. "
        "For arched openings: height is the rectangular portion height; "
        "the arch rise = width / 2 is added on top automatically. "
        "Returns cut parameters and opening volume. "
        "Validates that the opening fits within the wall extents."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "width": {
                "type": "number",
                "description": "Opening width in mm. Must be > 0.",
            },
            "height": {
                "type": "number",
                "description": (
                    "Opening height in mm (rectangular portion). Must be > 0. "
                    "For arched openings the arch rise (width/2) is added above this."
                ),
            },
            "wall_ref": {
                "type": "string",
                "description": "ID of the host wall.",
            },
            "position_along_wall": {
                "type": "number",
                "description": (
                    "Distance from the wall start to the near edge of the opening in mm. "
                    "Must be >= 0."
                ),
            },
            "wall_length": {
                "type": "number",
                "description": "Total host wall baseline length in mm.",
            },
            "wall_height": {
                "type": "number",
                "description": "Host wall height in mm.",
            },
            "wall_thickness": {
                "type": "number",
                "description": "Host wall total thickness in mm.",
            },
            "sill_height": {
                "type": "number",
                "description": "Height of the opening's bottom edge above floor in mm. Default 0.",
            },
            "arch_type": {
                "type": "string",
                "enum": ["rectangular", "arched"],
                "description": "Opening profile. 'arched' adds a semicircular head. Default 'rectangular'.",
            },
            "id": {
                "type": "string",
                "description": "Optional opening identifier.",
            },
        },
        "required": ["width", "height", "wall_ref", "position_along_wall",
                     "wall_length", "wall_height", "wall_thickness"],
    },
)


@register(_arch_opening_spec, write=False)
async def run_arch_opening(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    result = build_opening(
        width=a.get("width"),
        height=a.get("height"),
        wall_ref=a.get("wall_ref", ""),
        position_along_wall=a.get("position_along_wall"),
        wall_length=a.get("wall_length"),
        wall_height=a.get("wall_height"),
        wall_thickness=a.get("wall_thickness"),
        sill_height=a.get("sill_height", 0.0),
        arch_type=a.get("arch_type", "rectangular"),
        id=str(a.get("id", "")),
    )
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: arch_wall_with_openings
# ---------------------------------------------------------------------------

_arch_wall_with_openings_spec = ToolSpec(
    name="arch_wall_with_openings",
    description=(
        "Compose a wall with hosted doors, windows, or generic openings. "
        "Computes the net wall volume = gross volume − Σ opening volumes. "
        "All dimensions in millimetres. "
        "Accepts the output dicts from arch_wall, arch_door, arch_window, and "
        "arch_opening as inputs. "
        "Validates that all openings fit within the wall extents. "
        "Returns {ok: false, errors: [...]} if any opening is invalid; "
        "never raises. "
        "Typical workflow: "
        "1. arch_wall → wall_recipe "
        "2. arch_door / arch_window (pass wall_length, wall_height, wall_thickness) → opening_recipes "
        "3. arch_wall_with_openings(wall=wall_recipe, openings=[...opening_recipes...])"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "wall": {
                "type": "object",
                "description": "Wall recipe dict — output of arch_wall (must have ok=true).",
            },
            "openings": {
                "type": "array",
                "description": (
                    "List of opening recipe dicts — outputs of arch_door, arch_window, "
                    "or arch_opening (each must have ok=true). "
                    "Pass an empty list for a wall with no openings."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["wall", "openings"],
    },
)


@register(_arch_wall_with_openings_spec, write=False)
async def run_arch_wall_with_openings(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    wall = a.get("wall")
    openings = a.get("openings", [])

    if not isinstance(wall, dict):
        return err_payload("'wall' must be a dict (output of arch_wall)", "BAD_ARGS")
    if not isinstance(openings, list):
        return err_payload("'openings' must be a list", "BAD_ARGS")

    result = compose_wall_with_openings(wall=wall, openings=openings)
    if not result["ok"]:
        return err_payload("; ".join(result["errors"]), "BAD_ARGS")
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: arch_check_stair_codes
# ---------------------------------------------------------------------------

_arch_check_stair_codes_spec = ToolSpec(
    name="arch_check_stair_codes",
    description=(
        "Automated stair code-compliance check per IBC 2024 §1011, ADA §504, "
        "ICC A117.1 §504, or Ontario OBC Part 9. "
        "All dimensions must be supplied in **inches** (to match the code references). "
        "Checks: riser height, tread depth, stair width, handrail height, headroom "
        "clearance, landing depth, Blondel ergonomic formula (24 ≤ 2R+T ≤ 25 in), "
        "and max vertical rise between landings (IBC §1011.8). "
        "Returns per-category pass/fail booleans, a structured violations table "
        "(code_ref / requirement / actual), and an honest_caveat for inclusion in "
        "code-review packages. "
        "Never raises — bad inputs produce violation entries instead."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "tread_depth_in": {
                "type": "number",
                "description": (
                    "Horizontal tread depth, measured nose-to-nose in inches "
                    "(IBC §1011.5.3). Typical: 11\"."
                ),
            },
            "riser_height_in": {
                "type": "number",
                "description": (
                    "Vertical riser height in inches (IBC §1011.5.2). "
                    "IBC range: 4\"–7\"."
                ),
            },
            "stair_width_in": {
                "type": "number",
                "description": (
                    "Clear width between handrails (or wall faces) in inches. "
                    "IBC minimum: 44\" (occ. load ≥ 50) or 36\" (occ. load < 50)."
                ),
            },
            "handrail_height_in": {
                "type": "number",
                "description": (
                    "Height of handrail gripping surface above stair tread nosing "
                    "in inches (ADA §505.4 / IBC §1012.2). Range: 34\"–38\"."
                ),
            },
            "headroom_clearance_in": {
                "type": "number",
                "description": (
                    "Minimum vertical headroom measured from the tread nosing line "
                    "in inches (IBC §1011.3). Minimum: 80\" (6 ft 8 in)."
                ),
            },
            "num_risers": {
                "type": "integer",
                "description": (
                    "Number of risers in the flight. Used to compute total vertical "
                    "rise for the IBC §1011.8 max-rise-between-landings check."
                ),
                "minimum": 1,
            },
            "has_landing": {
                "type": "boolean",
                "description": (
                    "True if an intermediate landing is provided. When True, "
                    "landing_depth_in is checked against code minima."
                ),
            },
            "landing_depth_in": {
                "type": "number",
                "description": (
                    "Depth of the landing in the direction of travel in inches "
                    "(IBC §1011.7). Required when has_landing is True."
                ),
            },
            "jurisdiction": {
                "type": "string",
                "enum": ["ibc_2024", "ada_504", "icc_a117_1", "ontario_obc"],
                "description": (
                    "Code edition to enforce: "
                    "'ibc_2024' (IBC 2024 §1011), "
                    "'ada_504' (ADA Standards for Accessible Design §504), "
                    "'icc_a117_1' (ICC A117.1-2017 §504), "
                    "'ontario_obc' (Ontario Building Code Part 9 §9.8)."
                ),
            },
        },
        "required": [
            "tread_depth_in",
            "riser_height_in",
            "stair_width_in",
            "handrail_height_in",
            "headroom_clearance_in",
            "num_risers",
            "has_landing",
            "landing_depth_in",
            "jurisdiction",
        ],
    },
)


@register(_arch_check_stair_codes_spec, write=False)
async def run_arch_check_stair_codes(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    required = [
        "tread_depth_in", "riser_height_in", "stair_width_in",
        "handrail_height_in", "headroom_clearance_in",
        "num_risers", "has_landing", "landing_depth_in", "jurisdiction",
    ]
    missing = [k for k in required if k not in a]
    if missing:
        return err_payload(f"missing required fields: {missing}", "BAD_ARGS")

    try:
        spec = StairCodeSpec(
            tread_depth_in=float(a["tread_depth_in"]),
            riser_height_in=float(a["riser_height_in"]),
            stair_width_in=float(a["stair_width_in"]),
            handrail_height_in=float(a["handrail_height_in"]),
            headroom_clearance_in=float(a["headroom_clearance_in"]),
            num_risers=int(a["num_risers"]),
            has_landing=bool(a["has_landing"]),
            landing_depth_in=float(a["landing_depth_in"]),
            jurisdiction=str(a["jurisdiction"]),
        )
    except (TypeError, ValueError) as exc:
        return err_payload(f"invalid field value: {exc}", "BAD_ARGS")

    report = check_stair_codes(spec)

    payload = {
        "ok": True,
        "all_compliant": report.all_compliant,
        "riser_compliant": report.riser_compliant,
        "tread_compliant": report.tread_compliant,
        "width_compliant": report.width_compliant,
        "handrail_compliant": report.handrail_compliant,
        "headroom_compliant": report.headroom_compliant,
        "landing_compliant": report.landing_compliant,
        "ratio_2r_plus_t_compliant": report.ratio_2r_plus_t_compliant,
        "turning_compliant": report.turning_compliant,
        "violations": [
            {"code_ref": v[0], "requirement": v[1], "actual": v[2]}
            for v in report.violations
        ],
        "honest_caveat": report.honest_caveat,
    }
    return ok_payload(payload)
