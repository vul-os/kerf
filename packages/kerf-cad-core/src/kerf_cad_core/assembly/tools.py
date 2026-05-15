"""
kerf_cad_core.assembly.tools — LLM tool wrappers for the assembly constraint layer.

Tools
-----
assembly_create          — create a new empty Assembly and return its id.
assembly_add_component   — add a Component (part instance) to an Assembly.
assembly_add_mate        — add a Mate (constraint) between two components.
assembly_solve           — solve the assembly; returns resolved transforms + DOF status.
assembly_bom             — generate flat and indented BOM with quantity roll-up.

Session model
-------------
Because the LLM tools are stateless HTTP calls, the assembly and its mates are
serialised in the response payload and expected to be passed back verbatim in
subsequent calls.  The caller (LLM) maintains the assembly + mates state between
tool calls.

No DB write, no file mutation — all operations are pure in-memory and returned
as JSON in the payload.

Design matches the GDT tools pattern:  dict-in / dict-out, never raises,
uses ok_payload / err_payload from kerf_chat.
"""

from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.assembly.model import Assembly, Component
from kerf_cad_core.assembly.mates import Mate, MateType, solve_assembly


# ---------------------------------------------------------------------------
# assembly_create
# ---------------------------------------------------------------------------

_create_spec = ToolSpec(
    name="assembly_create",
    description=(
        "Create a new empty assembly and return its serialised state. "
        "The returned ``assembly`` dict must be passed to subsequent assembly "
        "tool calls (assembly_add_component, assembly_add_mate, assembly_solve, "
        "assembly_bom). "
        "Units: mm. Right-handed coordinate system (X right, Y forward, Z up). "
        "Transforms are 4×4 row-major homogeneous matrices as flat list[float] "
        "of length 16.  Identity = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Human-readable assembly name. Default 'assembly'.",
            },
        },
        "required": [],
    },
)


@register(_create_spec, write=False)
async def run_assembly_create(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    name = str(a.get("name", "assembly")).strip() or "assembly"
    asm = Assembly(name=name)
    return ok_payload({
        "assembly": asm.to_dict(),
        "assembly_id": asm.assembly_id,
        "message": f"Assembly '{name}' created.",
    })


# ---------------------------------------------------------------------------
# assembly_add_component
# ---------------------------------------------------------------------------

_add_component_spec = ToolSpec(
    name="assembly_add_component",
    description=(
        "Add a part instance (Component) to an assembly. "
        "The first component added is fixed (ground, 0 DOF). "
        "Subsequent components start with 6 DOF and are constrained by mates. "
        "\n"
        "``transform`` is an optional 4×4 row-major homogeneous matrix as a "
        "flat list of 16 floats that places the component in world space. "
        "If omitted the identity transform is used (origin, no rotation). "
        "\n"
        "Pass the updated ``assembly`` dict from the returned payload to the "
        "next assembly tool call."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly": {
                "type": "object",
                "description": "Assembly dict returned by assembly_create or previous call.",
            },
            "part_ref": {
                "type": "string",
                "description": (
                    "Reference to the part definition — file id, part number, "
                    "or part name. Used for BOM roll-up and display only; does "
                    "not need to resolve to a DB record."
                ),
            },
            "transform": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Optional 4×4 row-major transform as flat list of 16 floats. "
                    "Identity if omitted."
                ),
            },
            "name": {
                "type": "string",
                "description": "Optional human-readable instance name.",
            },
            "instance_id": {
                "type": "string",
                "description": (
                    "Optional explicit instance id. Auto-generated (UUID4) if omitted. "
                    "Use to make instance ids predictable in tests."
                ),
            },
        },
        "required": ["assembly", "part_ref"],
    },
)


@register(_add_component_spec, write=False)
async def run_assembly_add_component(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    asm_raw = a.get("assembly")
    if not asm_raw or not isinstance(asm_raw, dict):
        return err_payload("assembly is required", "BAD_ARGS")

    part_ref = str(a.get("part_ref", "")).strip()
    if not part_ref:
        return err_payload("part_ref is required", "BAD_ARGS")

    try:
        asm = Assembly.from_dict(asm_raw)
    except Exception as exc:
        return err_payload(f"invalid assembly: {exc}", "BAD_ARGS")

    try:
        comp = Component(
            part_ref=part_ref,
            transform=a.get("transform"),
            name=a.get("name"),
            instance_id=a.get("instance_id"),
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    try:
        asm.add_component(comp)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    return ok_payload({
        "assembly": asm.to_dict(),
        "instance_id": comp.instance_id,
        "part_ref": comp.part_ref,
        "message": f"Component '{part_ref}' added as instance '{comp.instance_id}'.",
    })


# ---------------------------------------------------------------------------
# assembly_add_mate
# ---------------------------------------------------------------------------

_MATE_TYPE_VALUES = [mt.value for mt in MateType]

_add_mate_spec = ToolSpec(
    name="assembly_add_mate",
    description=(
        "Add a geometric mate (constraint) between two component instances. "
        "Mates are accumulated in a list and consumed by assembly_solve. "
        "\n"
        "Mate types and DOF removed:\n"
        "  coincident    — face/face, 3 DOF (1 translation + 2 rotations)\n"
        "  concentric    — axis/axis colinear, 4 DOF (2 translations + 2 rotations)\n"
        "  parallel      — axes/faces parallel, 2 DOF (2 rotations)\n"
        "  perpendicular — axes/faces perpendicular, 1 DOF (1 rotation)\n"
        "  distance      — face-to-face offset, 1 DOF (1 translation)\n"
        "  angle         — angle between axes/faces, 1 DOF (1 rotation)\n"
        "  tangent       — cylinder tangent to plane, 1 DOF (1 translation)\n"
        "  lock          — fully constrain remaining DOF\n"
        "\n"
        "Geometry hints (optional):\n"
        "  point_a / point_b   — 3-D point [x, y, z] on the feature in local frame (mm)\n"
        "  normal_a / normal_b — unit axis/normal direction [x, y, z] in local frame\n"
        "  offset              — signed distance (mm) for distance / tangent mates\n"
        "  angle_deg           — target angle (degrees) for angle mates\n"
        "\n"
        "Returns the updated ``mates`` list to pass to assembly_solve."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "mates": {
                "type": "array",
                "description": "Current mate list (from previous assembly_add_mate call, or []).",
                "items": {"type": "object"},
            },
            "mate_type": {
                "type": "string",
                "enum": _MATE_TYPE_VALUES,
                "description": "Constraint type.",
            },
            "instance_id_a": {
                "type": "string",
                "description": "Instance id of the first component.",
            },
            "instance_id_b": {
                "type": "string",
                "description": "Instance id of the second component.",
            },
            "point_a": {
                "type": "array",
                "items": {"type": "number"},
                "description": "3-D point [x, y, z] on component A's feature (local frame, mm).",
            },
            "normal_a": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Normal/axis direction [x, y, z] for component A (local frame).",
            },
            "point_b": {
                "type": "array",
                "items": {"type": "number"},
                "description": "3-D point [x, y, z] on component B's feature (local frame, mm).",
            },
            "normal_b": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Normal/axis direction [x, y, z] for component B (local frame).",
            },
            "offset": {
                "type": "number",
                "description": (
                    "Signed distance offset (mm) for distance / tangent mates. "
                    "0 = flush / touching."
                ),
            },
            "angle_deg": {
                "type": "number",
                "description": "Target angle (degrees) for angle mates.",
            },
            "mate_id": {
                "type": "string",
                "description": "Optional explicit mate id (auto-generated if omitted).",
            },
        },
        "required": ["mates", "mate_type", "instance_id_a", "instance_id_b"],
    },
)


@register(_add_mate_spec, write=False)
async def run_assembly_add_mate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    mates_raw = a.get("mates")
    if mates_raw is None:
        return err_payload("mates is required (pass [] for first mate)", "BAD_ARGS")
    if not isinstance(mates_raw, list):
        return err_payload("mates must be an array", "BAD_ARGS")

    mate_type_str = str(a.get("mate_type", "")).strip().lower()
    if not mate_type_str:
        return err_payload("mate_type is required", "BAD_ARGS")
    try:
        MateType(mate_type_str)
    except ValueError:
        return err_payload(
            f"Invalid mate_type '{mate_type_str}'. Valid: {_MATE_TYPE_VALUES}",
            "BAD_ARGS",
        )

    iid_a = str(a.get("instance_id_a", "")).strip()
    iid_b = str(a.get("instance_id_b", "")).strip()
    if not iid_a:
        return err_payload("instance_id_a is required", "BAD_ARGS")
    if not iid_b:
        return err_payload("instance_id_b is required", "BAD_ARGS")

    try:
        mate = Mate(
            mate_type=mate_type_str,
            instance_id_a=iid_a,
            instance_id_b=iid_b,
            point_a=a.get("point_a"),
            normal_a=a.get("normal_a"),
            point_b=a.get("point_b"),
            normal_b=a.get("normal_b"),
            offset=a.get("offset", 0.0),
            angle_deg=a.get("angle_deg", 0.0),
            mate_id=a.get("mate_id"),
        )
    except (ValueError, TypeError) as exc:
        return err_payload(f"invalid mate geometry: {exc}", "BAD_ARGS")

    # Re-parse existing mates (validation only; errors accumulate gracefully)
    existing_mates: list[dict] = []
    for i, mr in enumerate(mates_raw):
        if not isinstance(mr, dict):
            return err_payload(f"mates[{i}] is not an object", "BAD_ARGS")
        existing_mates.append(mr)

    existing_mates.append(mate.to_dict())

    return ok_payload({
        "mates": existing_mates,
        "mate_id": mate.mate_id,
        "message": (
            f"Mate '{mate_type_str}' added between "
            f"'{iid_a}' and '{iid_b}'."
        ),
    })


# ---------------------------------------------------------------------------
# assembly_solve
# ---------------------------------------------------------------------------

_solve_spec = ToolSpec(
    name="assembly_solve",
    description=(
        "Solve the assembly constraint system and return each component's "
        "resolved 4×4 transform plus DOF / status information. "
        "\n"
        "The first component in the assembly is the ground (fixed, 0 DOF). "
        "Subsequent components are placed by the solver using the accumulated mates. "
        "\n"
        "Returns:\n"
        "  ok               — bool, true if no errors\n"
        "  components       — list of {instance_id, part_ref, transform, dof_remaining}\n"
        "  dof_remaining    — total remaining DOF across all non-ground components\n"
        "  status           — 'fully_constrained' | 'under_constrained' | 'over_constrained'\n"
        "  errors           — list of error strings (empty on clean solve)\n"
        "\n"
        "Never raises; invalid mates are reported in errors."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly": {
                "type": "object",
                "description": "Assembly dict from assembly_create / assembly_add_component.",
            },
            "mates": {
                "type": "array",
                "description": "Mate list from assembly_add_mate (pass [] for unconstrained).",
                "items": {"type": "object"},
            },
        },
        "required": ["assembly", "mates"],
    },
)


@register(_solve_spec, write=False)
async def run_assembly_solve(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    asm_raw = a.get("assembly")
    if not asm_raw or not isinstance(asm_raw, dict):
        return err_payload("assembly is required", "BAD_ARGS")

    mates_raw = a.get("mates")
    if mates_raw is None:
        return err_payload("mates is required (pass [] for unconstrained solve)", "BAD_ARGS")
    if not isinstance(mates_raw, list):
        return err_payload("mates must be an array", "BAD_ARGS")

    try:
        asm = Assembly.from_dict(asm_raw)
    except Exception as exc:
        return err_payload(f"invalid assembly: {exc}", "BAD_ARGS")

    # Parse mates; collect parse errors without raising
    mates: list[Mate] = []
    parse_errors: list[str] = []
    for i, mr in enumerate(mates_raw):
        if not isinstance(mr, dict):
            parse_errors.append(f"mates[{i}]: not an object")
            continue
        try:
            mates.append(Mate.from_dict(mr))
        except Exception as exc:
            parse_errors.append(f"mates[{i}]: {exc}")

    result = solve_assembly(asm, mates)
    result["errors"] = parse_errors + result.get("errors", [])
    if parse_errors:
        result["ok"] = False

    return ok_payload(result)


# ---------------------------------------------------------------------------
# assembly_bom
# ---------------------------------------------------------------------------

_bom_spec = ToolSpec(
    name="assembly_bom",
    description=(
        "Generate a Bill of Materials (BOM) for an assembly. "
        "Returns a flat list (quantity-rolled-up by part_ref) and an indented "
        "tree representation. "
        "\n"
        "Flat BOM: list of {part_ref, qty, instances: [instance_id, ...]}\n"
        "  Duplicate part_refs are rolled up into a single row with qty > 1.\n"
        "\n"
        "Indented BOM: nested tree mirroring the Assembly / sub-assembly structure,\n"
        "  with items as [{level, part_ref, instance_id, name}].\n"
        "\n"
        "Returns:\n"
        "  flat  — [{part_ref, qty, instances: [instance_id, ...]}]\n"
        "  tree  — [{level, part_ref, instance_id, name, sub_items: [...]}]\n"
        "  total_components — int (all leaf components, counting duplicates)\n"
        "  unique_parts     — int (number of distinct part_refs)\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "assembly": {
                "type": "object",
                "description": "Assembly dict.",
            },
        },
        "required": ["assembly"],
    },
)


@register(_bom_spec, write=False)
async def run_assembly_bom(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    asm_raw = a.get("assembly")
    if not asm_raw or not isinstance(asm_raw, dict):
        return err_payload("assembly is required", "BAD_ARGS")

    try:
        asm = Assembly.from_dict(asm_raw)
    except Exception as exc:
        return err_payload(f"invalid assembly: {exc}", "BAD_ARGS")

    flat = _build_flat_bom(asm)
    tree = _build_tree_bom(asm, level=0)

    all_comps = asm.all_components()
    unique_parts = len({c.part_ref for c in all_comps})

    return ok_payload({
        "flat": flat,
        "tree": tree,
        "total_components": len(all_comps),
        "unique_parts": unique_parts,
    })


# ---------------------------------------------------------------------------
# BOM helpers
# ---------------------------------------------------------------------------

def _build_flat_bom(asm: Assembly) -> list[dict]:
    """
    Build a flat BOM with quantity roll-up across all components
    (direct + sub-assembly), keyed by part_ref.
    """
    from collections import OrderedDict
    buckets: dict[str, list[str]] = OrderedDict()
    for comp in asm.all_components():
        buckets.setdefault(comp.part_ref, []).append(comp.instance_id)
    return [
        {"part_ref": ref, "qty": len(iids), "instances": iids}
        for ref, iids in buckets.items()
    ]


def _build_tree_bom(asm: Assembly, level: int) -> list[dict]:
    """
    Build an indented tree BOM.  Each entry carries a ``level`` integer
    for indentation rendering (0 = top-level assembly, 1 = direct child, …).
    """
    items: list[dict] = []
    for comp in asm.components:
        items.append({
            "level": level,
            "part_ref": comp.part_ref,
            "instance_id": comp.instance_id,
            "name": comp.name,
            "sub_items": [],
        })
    for sub in asm.sub_assemblies:
        sub_items = _build_tree_bom(sub, level + 1)
        items.append({
            "level": level,
            "part_ref": None,
            "instance_id": None,
            "name": sub.name,
            "sub_items": sub_items,
        })
    return items


__all__ = [
    "run_assembly_create",
    "run_assembly_add_component",
    "run_assembly_add_mate",
    "run_assembly_solve",
    "run_assembly_bom",
]
