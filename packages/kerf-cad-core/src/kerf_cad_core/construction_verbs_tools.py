"""construction_verbs_tools.py — GK-P48: Wire construction verb ops as ToolSpecs.

Wires the following already-implemented functions into the tool/feature/LLM
surface:

Sheet-metal (GK-P17):
- ``hem_sheet``    — 180° hem fold on a bent sheet Body
- ``jog_sheet``    — Z-offset jog (two opposing bends)
- ``multi_flange`` — sequence of bends in one call

Direct-edit (GK-P18):
- ``delete_face``        — remove a face and heal the body
- ``push_pull_face``     — push/pull a face along its normal (planar + non-planar)

Weldment (GK-P19):
- ``gusset_plate``       — gusset-plate insert at a joint vertex
- ``apply_end_treatment``— cope / notch end-treatment on a member end

All ops append a node to a ``.feature`` file. The OCCT worker dispatches to
``BRepTools_ReShape`` / ``BRepOffsetAPI_MakeOffsetShape`` for curved-face ops;
pure-Python fallbacks are used when OCCT is unavailable.
"""
from __future__ import annotations

import json
import uuid

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

from kerf_cad_core.surfacing import (
    append_feature_node,
    next_node_id,
    read_feature_content,
)


# ── feature_hem_sheet ─────────────────────────────────────────────────────────
#
# GK-P17: add a 180° hem fold to a bent sheet Body.

feature_hem_sheet_spec = ToolSpec(
    name="feature_hem_sheet",
    description=(
        "Append a `hem_sheet` node to a `.feature` file. "
        "Adds a 180° hem fold to a bent sheet-metal body — folds the flange "
        "back onto itself to stiffen the edge and remove raw-cut burrs. "
        "\n\n"
        "Styles: `closed` (flat hem, gap=0), `open` (hem stopped before "
        "touching, gap>0), `teardrop` (full teardrop profile). "
        "The node carries `style`, `gap`, `radius` (default thickness/2), "
        "and `k_factor` (neutral-fibre fraction, default 0.44). "
        "\n\n"
        "Requires the target body to carry `__sheet_metal__` metadata "
        "with `type == 'bent'` (i.e. output of a `bend_sheet` node)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the bent sheet-metal body node (output of bend_sheet).",
            },
            "style": {
                "type": "string",
                "enum": ["closed", "open", "teardrop"],
                "description": "Hem style (default 'closed').",
                "default": "closed",
            },
            "gap": {
                "type": "number",
                "description": "Air gap between hem and base panel (mm, ≥0). Forced to 0 for 'closed'. Default 0.",
                "minimum": 0,
                "default": 0.0,
            },
            "radius": {
                "type": "number",
                "description": "Inner bend radius of the hem fold (mm). Defaults to thickness/2 when omitted.",
                "exclusiveMinimum": 0,
            },
            "k_factor": {
                "type": "number",
                "description": "Neutral-fibre fraction for bend allowance (default 0.44).",
                "exclusiveMinimum": 0,
                "exclusiveMaximum": 1,
                "default": 0.44,
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id"],
    },
)


@register(feature_hem_sheet_spec, write=True)
async def run_feature_hem_sheet(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    style = a.get("style", "closed")
    gap = a.get("gap", 0.0)
    radius = a.get("radius")
    k_factor = a.get("k_factor", 0.44)
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if style not in ("closed", "open", "teardrop"):
        return err_payload("style must be 'closed', 'open', or 'teardrop'", "BAD_ARGS")
    if not isinstance(gap, (int, float)) or float(gap) < 0:
        return err_payload("gap must be >= 0", "BAD_ARGS")
    if not isinstance(k_factor, (int, float)) or not (0 < float(k_factor) < 1):
        return err_payload("k_factor must be in (0, 1)", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "hem_sheet")

    node: dict = {
        "id": node_id,
        "op": "hem_sheet",
        "target_id": target_id,
        "style": style,
        "gap": float(gap),
        "k_factor": float(k_factor),
    }
    if radius is not None:
        node["radius"] = float(radius)

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "hem_sheet",
        "style": style,
    })


# ── feature_jog_sheet ─────────────────────────────────────────────────────────
#
# GK-P17: add a Z-offset jog (two opposing bends) to a sheet Body.

feature_jog_sheet_spec = ToolSpec(
    name="feature_jog_sheet",
    description=(
        "Append a `jog_sheet` node to a `.feature` file. "
        "Adds a jog (Z-offset step) to a sheet-metal body. "
        "A jog consists of two equal-and-opposite bends that shift one panel "
        "up or down by `offset` while keeping both panels parallel. "
        "\n\n"
        "`jog_angle_rad` is the interior angle of each jog bend (default π/2 "
        "= 90°, the sharpest possible step; smaller angles produce a ramp). "
        "`offset` is the signed Z-offset (positive = step up). "
        "\n\n"
        "Requires the target body to carry `__sheet_metal__` metadata."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the flat or bent sheet-metal body node.",
            },
            "offset": {
                "type": "number",
                "description": "Signed Z-offset of the output panel (mm). Non-zero.",
            },
            "jog_angle_rad": {
                "type": "number",
                "description": "Interior angle of each jog bend (rad, in (0, π/2]). Default π/2.",
                "exclusiveMinimum": 0,
                "default": 1.5707963267948966,
            },
            "radius": {
                "type": "number",
                "description": "Inner bend radius for each jog bend (mm, >0). Default 1.",
                "exclusiveMinimum": 0,
                "default": 1.0,
            },
            "k_factor": {
                "type": "number",
                "description": "Neutral-fibre fraction (default 0.44).",
                "exclusiveMinimum": 0,
                "exclusiveMaximum": 1,
                "default": 0.44,
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id", "offset"],
    },
)


@register(feature_jog_sheet_spec, write=True)
async def run_feature_jog_sheet(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    import math as _math

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    offset = a.get("offset")
    jog_angle_rad = a.get("jog_angle_rad", _math.pi / 2)
    radius = a.get("radius", 1.0)
    k_factor = a.get("k_factor", 0.44)
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if offset is None or not isinstance(offset, (int, float)) or float(offset) == 0:
        return err_payload("offset must be a non-zero number", "BAD_ARGS")
    if not isinstance(jog_angle_rad, (int, float)) or not (0 < float(jog_angle_rad) <= _math.pi / 2 + 1e-9):
        return err_payload("jog_angle_rad must be in (0, π/2]", "BAD_ARGS")
    if not isinstance(radius, (int, float)) or float(radius) <= 0:
        return err_payload("radius must be positive", "BAD_ARGS")
    if not isinstance(k_factor, (int, float)) or not (0 < float(k_factor) < 1):
        return err_payload("k_factor must be in (0, 1)", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "jog_sheet")

    node = {
        "id": node_id,
        "op": "jog_sheet",
        "target_id": target_id,
        "offset": float(offset),
        "jog_angle_rad": float(jog_angle_rad),
        "radius": float(radius),
        "k_factor": float(k_factor),
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "jog_sheet",
        "offset": float(offset),
    })


# ── feature_multi_flange ──────────────────────────────────────────────────────
#
# GK-P17: apply a sequence of bends in one call.

feature_multi_flange_spec = ToolSpec(
    name="feature_multi_flange",
    description=(
        "Append a `multi_flange` node to a `.feature` file. "
        "Applies a sequence of bends to a sheet-metal body in one call. "
        "Each bend spec in `bend_specs` must have: "
        "`bend_line` (mm, absolute X position of the bend on the flat extent), "
        "`angle_rad` (interior bend angle in radians), "
        "`radius` (inner bend radius in mm), "
        "and optionally `k_factor` (default 0.4). "
        "\n\n"
        "Returns the final body with `__sheet_metal__['type'] == 'multi_flange'` "
        "and an `operations` list recording each bend's metadata. "
        "\n\n"
        "Requires the target body to carry `__sheet_metal__` metadata or have "
        "at least one face with vertices (thickness + width are inferred from "
        "the bounding box when metadata is absent)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the starting sheet-metal body node.",
            },
            "bend_specs": {
                "type": "array",
                "description": (
                    "Ordered list of bend operations. Each must have: "
                    "bend_line (float), angle_rad (float), radius (float). "
                    "Optional: k_factor (float, default 0.4)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "bend_line": {"type": "number"},
                        "angle_rad": {"type": "number"},
                        "radius": {"type": "number", "exclusiveMinimum": 0},
                        "k_factor": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
                    },
                    "required": ["bend_line", "angle_rad", "radius"],
                },
                "minItems": 1,
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id", "bend_specs"],
    },
)


@register(feature_multi_flange_spec, write=True)
async def run_feature_multi_flange(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    bend_specs = a.get("bend_specs")
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if not isinstance(bend_specs, list) or len(bend_specs) == 0:
        return err_payload("bend_specs must be a non-empty list", "BAD_ARGS")
    for i, spec in enumerate(bend_specs):
        if not isinstance(spec, dict):
            return err_payload(f"bend_specs[{i}] must be an object", "BAD_ARGS")
        for key in ("bend_line", "angle_rad", "radius"):
            if key not in spec:
                return err_payload(f"bend_specs[{i}] missing required key '{key}'", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "multi_flange")

    node = {
        "id": node_id,
        "op": "multi_flange",
        "target_id": target_id,
        "bend_specs": bend_specs,
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "multi_flange",
        "num_bends": len(bend_specs),
    })


# ── feature_delete_face ───────────────────────────────────────────────────────
#
# GK-P18: remove a face from a body and heal the result.

feature_delete_face_spec = ToolSpec(
    name="feature_delete_face",
    description=(
        "Append a `delete_face` node to a `.feature` file. "
        "Removes a face from a body and attempts to heal the result. "
        "\n\n"
        "For **planar all-face bodies** (boxes, simple polyhedra): the face is "
        "removed and the remaining planes are re-intersected to close the body. "
        "For **bodies with curved faces**: the face is removed from the shell; "
        "the OCCT worker uses `BRepTools_ReShape` for topologically correct "
        "healing; the pure-Python path returns an open shell with "
        "`__direct_edit_deleted_face__ = True`. "
        "\n\n"
        "`heal=true` (default) attempts to close the body after deletion. "
        "`heal=false` returns the raw open-shell body."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the body node from which to delete a face.",
            },
            "face_id": {
                "type": "integer",
                "description": "0-based index of the face to delete.",
                "minimum": 0,
            },
            "heal": {
                "type": "boolean",
                "description": "If true (default), attempt to heal the body after deletion.",
                "default": True,
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id", "face_id"],
    },
)


@register(feature_delete_face_spec, write=True)
async def run_feature_delete_face(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    face_id = a.get("face_id")
    heal = a.get("heal", True)
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if face_id is None or not isinstance(face_id, int) or face_id < 0:
        return err_payload("face_id must be a non-negative integer", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "delete_face")

    node = {
        "id": node_id,
        "op": "delete_face",
        "target_id": target_id,
        "face_id": face_id,
        "heal": bool(heal),
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "delete_face",
        "face_id": face_id,
    })


# ── feature_push_pull ─────────────────────────────────────────────────────────
#
# GK-P18: push/pull a face along its normal (planar + non-planar).

feature_push_pull_spec = ToolSpec(
    name="feature_push_pull",
    description=(
        "Append a `push_pull` node to a `.feature` file. "
        "Offsets a face along its outward normal by `distance`. "
        "Positive distance moves the face outward (increases volume); "
        "negative moves it inward (decreases volume). "
        "\n\n"
        "For **planar** bodies: adjacent faces are automatically re-healed so "
        "the solid remains watertight. "
        "For **non-planar** (curved) faces (GK-P18): a surface-offset "
        "approximation is applied; the OCCT worker uses "
        "`BRepOffsetAPI_MakeOffsetShape` for correct healing. "
        "The pure-Python fallback returns an open shell with "
        "`__direct_edit_curved__ = True`."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the body node whose face to push/pull.",
            },
            "face_id": {
                "type": "integer",
                "description": "0-based index of the face to offset.",
                "minimum": 0,
            },
            "distance": {
                "type": "number",
                "description": "Signed offset distance along outward normal (mm). Non-zero.",
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id", "face_id", "distance"],
    },
)


@register(feature_push_pull_spec, write=True)
async def run_feature_push_pull(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    face_id = a.get("face_id")
    distance = a.get("distance")
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if face_id is None or not isinstance(face_id, int) or face_id < 0:
        return err_payload("face_id must be a non-negative integer", "BAD_ARGS")
    if distance is None or not isinstance(distance, (int, float)):
        return err_payload("distance is required and must be a number", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "push_pull")

    node = {
        "id": node_id,
        "op": "push_pull",
        "target_id": target_id,
        "face_id": face_id,
        "distance": float(distance),
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "push_pull",
        "face_id": face_id,
        "distance": float(distance),
    })


# ── feature_gusset_plate ──────────────────────────────────────────────────────
#
# GK-P19: gusset-plate insert at a weldment joint vertex.

feature_gusset_plate_spec = ToolSpec(
    name="feature_gusset_plate",
    description=(
        "Append a `gusset_plate` node to a `.feature` file. "
        "Computes and inserts a gusset-plate stiffener at a weldment joint "
        "vertex. The gusset plate sits at `vertex_pos` between the meeting "
        "members, stiffening the joint. "
        "\n\n"
        "Shapes: `triangle` (right-triangle), `rect` (full rectangle), "
        "`trapezoidal` (diagonal top edge). "
        "Optional fillet radius on corners. "
        "\n\n"
        "Returns a descriptor with area, mass, corner points, and member "
        "direction vectors. No OCCT required — pure-Python geometry."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the weldment frame node.",
            },
            "vertex_pos": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "[x, y, z] position of the joint vertex (mm).",
            },
            "thickness_mm": {
                "type": "number",
                "description": "Plate thickness (mm, >0). Default 6.",
                "exclusiveMinimum": 0,
                "default": 6.0,
            },
            "width_mm": {
                "type": "number",
                "description": "Plate width along first member direction (mm, >0). Default 100.",
                "exclusiveMinimum": 0,
                "default": 100.0,
            },
            "height_mm": {
                "type": "number",
                "description": "Plate height along second member direction (mm, >0). Default 100.",
                "exclusiveMinimum": 0,
                "default": 100.0,
            },
            "shape": {
                "type": "string",
                "enum": ["triangle", "rect", "trapezoidal"],
                "description": "Gusset plate outline shape (default 'triangle').",
                "default": "triangle",
            },
            "fillet_mm": {
                "type": "number",
                "description": "Corner fillet radius (mm, ≥0). 0 = sharp corners. Default 0.",
                "minimum": 0,
                "default": 0.0,
            },
            "material": {
                "type": "string",
                "description": "Material designation for mass calculation (default 'steel').",
                "default": "steel",
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id", "vertex_pos"],
    },
)


@register(feature_gusset_plate_spec, write=True)
async def run_feature_gusset_plate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    vertex_pos = a.get("vertex_pos")
    thickness_mm = a.get("thickness_mm", 6.0)
    width_mm = a.get("width_mm", 100.0)
    height_mm = a.get("height_mm", 100.0)
    shape = a.get("shape", "triangle")
    fillet_mm = a.get("fillet_mm", 0.0)
    material = a.get("material", "steel")
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if not isinstance(vertex_pos, list) or len(vertex_pos) < 3:
        return err_payload("vertex_pos must be [x, y, z]", "BAD_ARGS")
    if shape not in ("triangle", "rect", "trapezoidal"):
        return err_payload("shape must be 'triangle', 'rect', or 'trapezoidal'", "BAD_ARGS")
    if not isinstance(thickness_mm, (int, float)) or float(thickness_mm) <= 0:
        return err_payload("thickness_mm must be > 0", "BAD_ARGS")
    if not isinstance(width_mm, (int, float)) or float(width_mm) <= 0:
        return err_payload("width_mm must be > 0", "BAD_ARGS")
    if not isinstance(height_mm, (int, float)) or float(height_mm) <= 0:
        return err_payload("height_mm must be > 0", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "gusset_plate")

    node = {
        "id": node_id,
        "op": "gusset_plate",
        "target_id": target_id,
        "vertex_pos": [float(vertex_pos[0]), float(vertex_pos[1]), float(vertex_pos[2])],
        "thickness_mm": float(thickness_mm),
        "width_mm": float(width_mm),
        "height_mm": float(height_mm),
        "shape": shape,
        "fillet_mm": float(fillet_mm),
        "material": str(material),
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "gusset_plate",
        "shape": shape,
        "vertex_pos": node["vertex_pos"],
    })


# ── feature_cope_notch ────────────────────────────────────────────────────────
#
# GK-P19: cope / notch end-treatment on a weldment member end.

feature_cope_notch_spec = ToolSpec(
    name="feature_cope_notch",
    description=(
        "Append a `cope_notch` node to a `.feature` file. "
        "Computes cope or notch end-treatment metadata for a weldment member "
        "end, enabling fabrication-ready member end preparation. "
        "\n\n"
        "**Cope** — a curved or square cut-out at the member end to allow it "
        "to fit over a passing member's flange/web. "
        "Styles: `none`, `square`, `radius` (radiused re-entrant corner). "
        "\n\n"
        "**Notch** — a V-cut or square cut-out at the corner of a member end. "
        "Styles: `none`, `square`, `angle` (V-notch). "
        "\n\n"
        "Returns cope and notch geometry descriptors with area and mass of "
        "material removed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the weldment frame or member node.",
            },
            "member_index": {
                "type": "integer",
                "description": "0-based index of the member in the frame to treat.",
                "minimum": 0,
            },
            "end": {
                "type": "string",
                "enum": ["start", "end"],
                "description": "Which end of the member to treat.",
            },
            "cope_style": {
                "type": "string",
                "enum": ["none", "square", "radius"],
                "description": "Cope cut style (default 'none').",
                "default": "none",
            },
            "cope_depth_mm": {
                "type": "number",
                "description": "Cope cut depth (mm). Required when cope_style != 'none'.",
                "minimum": 0,
                "default": 0.0,
            },
            "cope_width_mm": {
                "type": "number",
                "description": "Cope cut width (mm). Required when cope_style != 'none'.",
                "minimum": 0,
                "default": 0.0,
            },
            "cope_radius_mm": {
                "type": "number",
                "description": "Re-entrant corner radius (mm). Only for 'radius' cope style.",
                "minimum": 0,
                "default": 0.0,
            },
            "notch_style": {
                "type": "string",
                "enum": ["none", "square", "angle"],
                "description": "Notch cut style (default 'none').",
                "default": "none",
            },
            "notch_depth_mm": {
                "type": "number",
                "description": "Notch depth (mm).",
                "minimum": 0,
                "default": 0.0,
            },
            "notch_width_mm": {
                "type": "number",
                "description": "Notch width (mm) at the outer face.",
                "minimum": 0,
                "default": 0.0,
            },
            "notch_angle_deg": {
                "type": "number",
                "description": "V-notch included angle (degrees). Only for 'angle' notch style. Default 45.",
                "default": 45.0,
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id", "member_index", "end"],
    },
)


@register(feature_cope_notch_spec, write=True)
async def run_feature_cope_notch(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    member_index = a.get("member_index")
    end = a.get("end", "")
    cope_style = a.get("cope_style", "none")
    cope_depth_mm = a.get("cope_depth_mm", 0.0)
    cope_width_mm = a.get("cope_width_mm", 0.0)
    cope_radius_mm = a.get("cope_radius_mm", 0.0)
    notch_style = a.get("notch_style", "none")
    notch_depth_mm = a.get("notch_depth_mm", 0.0)
    notch_width_mm = a.get("notch_width_mm", 0.0)
    notch_angle_deg = a.get("notch_angle_deg", 45.0)
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if member_index is None or not isinstance(member_index, int) or member_index < 0:
        return err_payload("member_index must be a non-negative integer", "BAD_ARGS")
    if end not in ("start", "end"):
        return err_payload("end must be 'start' or 'end'", "BAD_ARGS")
    if cope_style not in ("none", "square", "radius"):
        return err_payload("cope_style must be 'none', 'square', or 'radius'", "BAD_ARGS")
    if notch_style not in ("none", "square", "angle"):
        return err_payload("notch_style must be 'none', 'square', or 'angle'", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "cope_notch")

    node = {
        "id": node_id,
        "op": "cope_notch",
        "target_id": target_id,
        "member_index": member_index,
        "end": end,
        "cope_style": cope_style,
        "cope_depth_mm": float(cope_depth_mm),
        "cope_width_mm": float(cope_width_mm),
        "cope_radius_mm": float(cope_radius_mm),
        "notch_style": notch_style,
        "notch_depth_mm": float(notch_depth_mm),
        "notch_width_mm": float(notch_width_mm),
        "notch_angle_deg": float(notch_angle_deg),
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "cope_notch",
        "end": end,
        "cope_style": cope_style,
        "notch_style": notch_style,
    })


# ── brep_push_pull_constrained ────────────────────────────────────────────────
#
# GK-P18 extension: constrained push-pull (clamp / reject modes).

brep_push_pull_constrained_spec = ToolSpec(
    name="brep_push_pull_constrained",
    description=(
        "Append a `push_pull_constrained` node to a `.feature` file. "
        "Offsets a face along its outward normal by `distance`, checking "
        "geometric constraints before applying. "
        "\n\n"
        "**Constraint kinds** (each is a dict with `'kind'`):\n"
        "- `preserve_adjacent_face_position` — clamp distance so the pushed "
        "face does not cross any opposing adjacent face.\n"
        "- `preserve_volume_sign` — clamp distance so the body retains positive "
        "volume (face does not push past the opposite wall).\n"
        "- `preserve_planarity` — ensure the target face remains planar after "
        "the operation (relevant for non-planar faces).\n"
        "\n\n"
        "**mode** controls what happens when a constraint is violated:\n"
        "- `clamp` (default): reduce distance to the maximum allowed value.\n"
        "- `reject`: raise an error immediately.\n"
        "\n\n"
        "Returns `applied_distance` (possibly less than `distance` when "
        "clamped) and `clamped_constraints` (list of constraint kinds that "
        "were activated)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the body node whose face to push/pull.",
            },
            "face_id": {
                "type": "integer",
                "description": "0-based index of the face to offset.",
                "minimum": 0,
            },
            "distance": {
                "type": "number",
                "description": "Requested signed offset along outward normal (mm). Non-zero.",
            },
            "constraints": {
                "type": "array",
                "description": (
                    "List of constraint objects.  Each must have a `kind` field.  "
                    "Supported kinds: 'preserve_adjacent_face_position', "
                    "'preserve_volume_sign', 'preserve_planarity'."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": [
                                "preserve_adjacent_face_position",
                                "preserve_volume_sign",
                                "preserve_planarity",
                            ],
                        },
                    },
                    "required": ["kind"],
                },
                "default": [],
            },
            "mode": {
                "type": "string",
                "enum": ["clamp", "reject"],
                "description": "How to handle constraint violations: 'clamp' (default) or 'reject'.",
                "default": "clamp",
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id", "face_id", "distance"],
    },
)


@register(brep_push_pull_constrained_spec, write=True)
async def run_brep_push_pull_constrained(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    face_id = a.get("face_id")
    distance = a.get("distance")
    constraints = a.get("constraints", [])
    mode = a.get("mode", "clamp")
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if face_id is None or not isinstance(face_id, int) or face_id < 0:
        return err_payload("face_id must be a non-negative integer", "BAD_ARGS")
    if distance is None or not isinstance(distance, (int, float)):
        return err_payload("distance is required and must be a number", "BAD_ARGS")
    if not isinstance(constraints, list):
        return err_payload("constraints must be an array", "BAD_ARGS")
    if mode not in ("clamp", "reject"):
        return err_payload("mode must be 'clamp' or 'reject'", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "push_pull_constrained")

    node = {
        "id": node_id,
        "op": "push_pull_constrained",
        "target_id": target_id,
        "face_id": face_id,
        "distance": float(distance),
        "constraints": constraints,
        "mode": mode,
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "push_pull_constrained",
        "face_id": face_id,
        "distance": float(distance),
        "mode": mode,
    })


# ── brep_partial_face_replace ─────────────────────────────────────────────────
#
# GK-P18 extension: partial face replace (UV-region sub-face replacement).

brep_partial_face_replace_spec = ToolSpec(
    name="brep_partial_face_replace",
    description=(
        "Append a `partial_face_replace` node to a `.feature` file. "
        "Replaces a sub-region of a face (defined by a 2-D UV loop) with a "
        "new replacement surface. "
        "\n\n"
        "The operation: "
        "(1) maps the UV loop to 3-D world coordinates on the face's surface, "
        "(2) splits the face at the loop boundary using imprint primitives, "
        "(3) replaces the inner sub-face's surface with `replacement_surface_spec`. "
        "\n\n"
        "`region_loop` is a list of [u, v] pairs defining the closed 2-D "
        "boundary in parametric (UV) space.  Must have ≥ 3 points. "
        "\n\n"
        "`replacement_surface_spec` is a descriptor dict understood by the "
        "geometry kernel.  Supported types: "
        "`{'type': 'sphere', 'center': [cx, cy, cz], 'radius': r}`, "
        "`{'type': 'nurbs', 'control_points': [...], 'degree_u': int, 'degree_v': int}`. "
        "\n\n"
        "Returns the `face_id` of the inner (replaced) sub-face in the "
        "resulting body."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the body node whose face to partially replace.",
            },
            "face_id": {
                "type": "integer",
                "description": "0-based index of the face to partially replace.",
                "minimum": 0,
            },
            "region_loop": {
                "type": "array",
                "description": (
                    "Closed 2-D loop in UV parametric space.  "
                    "Each element is [u, v] (floats).  ≥ 3 points required."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 3,
            },
            "replacement_surface_spec": {
                "type": "object",
                "description": (
                    "Descriptor of the replacement surface.  "
                    "Must have a `type` field.  "
                    "Supported: 'sphere' (center, radius), "
                    "'nurbs' (control_points, degree_u, degree_v)."
                ),
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["sphere", "nurbs"],
                    },
                },
                "required": ["type"],
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id", "face_id", "region_loop", "replacement_surface_spec"],
    },
)


@register(brep_partial_face_replace_spec, write=True)
async def run_brep_partial_face_replace(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    face_id = a.get("face_id")
    region_loop = a.get("region_loop")
    replacement_surface_spec = a.get("replacement_surface_spec")
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if face_id is None or not isinstance(face_id, int) or face_id < 0:
        return err_payload("face_id must be a non-negative integer", "BAD_ARGS")
    if not isinstance(region_loop, list) or len(region_loop) < 3:
        return err_payload("region_loop must be a list of >= 3 [u, v] pairs", "BAD_ARGS")
    for i, pt in enumerate(region_loop):
        if not isinstance(pt, list) or len(pt) < 2:
            return err_payload(f"region_loop[{i}] must be [u, v]", "BAD_ARGS")
    if not isinstance(replacement_surface_spec, dict) or "type" not in replacement_surface_spec:
        return err_payload("replacement_surface_spec must have a 'type' field", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "partial_face_replace")

    node = {
        "id": node_id,
        "op": "partial_face_replace",
        "target_id": target_id,
        "face_id": face_id,
        "region_loop": region_loop,
        "replacement_surface_spec": replacement_surface_spec,
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "partial_face_replace",
        "face_id": face_id,
        "region_loop_points": len(region_loop),
    })
