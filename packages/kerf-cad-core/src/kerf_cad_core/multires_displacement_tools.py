"""multires_displacement_tools.py — GK-P-C: LLM tool wiring for multires displacement.

Registers two ToolSpecs:

- ``subd_apply_displacement``   — apply a scalar displacement map to a subdivided
  Catmull-Clark surface along Stam limit-surface normals.
- ``subd_extract_displacement`` — inverse: recover the per-vertex normal displacement
  from a sculpted fine mesh relative to the reference subdivision of a base cage.

Both ops are pure-Python (no OCCT).  They append nodes to ``.feature`` files so
the full sculpt/displacement workflow integrates with the existing feature DAG.
"""
from __future__ import annotations

import json
import uuid
from typing import List

import numpy as np

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

from kerf_cad_core.surfacing import (
    append_feature_node,
    next_node_id,
    read_feature_content,
)


# ---------------------------------------------------------------------------
# subd_apply_displacement
# ---------------------------------------------------------------------------

subd_apply_displacement_spec = ToolSpec(
    name="subd_apply_displacement",
    description=(
        "Apply a scalar displacement map to a Catmull-Clark subdivision surface. "
        "Subdivides the base mesh to the requested level, then displaces each "
        "fine vertex along its Stam limit-surface normal by the bilinearly "
        "interpolated displacement value at the vertex's parametric UV. "
        "Implements the Lee-Moreton-Hoppe 2000 displaced subdivision surface "
        "workflow (SIGGRAPH 2000). "
        "The result is serialised as a `subd_apply_displacement` node in the "
        "target `.feature` file. "
        "No OCCT required — pure-Python Catmull-Clark + Stam evaluator."
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
                "description": "Node id of an existing SubD cage node in the feature tree.",
            },
            "level": {
                "type": "integer",
                "description": "Number of Catmull-Clark subdivision levels (1–6).",
                "minimum": 1,
                "maximum": 6,
                "default": 2,
            },
            "displacement_samples": {
                "type": "array",
                "description": (
                    "2-D list of scalar displacement values (rows × cols). "
                    "Each value is the signed displacement along the surface normal "
                    "in scene units. Example: [[0.0, 0.1, 0.0], [0.1, 0.2, 0.1]]. "
                    "The grid is bilinearly interpolated over uv ∈ [0,1]²."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                },
            },
            "face_index": {
                "type": "integer",
                "description": "Base-mesh face the map applies to (-1 = whole mesh).",
                "default": -1,
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "target_id", "displacement_samples"],
    },
)


@register(subd_apply_displacement_spec, write=True)
async def run_subd_apply_displacement(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    level = a.get("level", 2)
    displacement_samples = a.get("displacement_samples")
    face_index = a.get("face_index", -1)
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if not isinstance(level, int) or not (1 <= level <= 6):
        return err_payload("level must be an integer 1–6", "BAD_ARGS")
    if not isinstance(displacement_samples, list) or len(displacement_samples) == 0:
        return err_payload("displacement_samples must be a non-empty 2-D list", "BAD_ARGS")

    # Validate 2-D shape
    try:
        arr = [[float(x) for x in row] for row in displacement_samples]
        row_lens = {len(r) for r in arr}
        if len(row_lens) != 1 or next(iter(row_lens)) == 0:
            return err_payload("displacement_samples rows must all be the same non-zero length", "BAD_ARGS")
    except (TypeError, ValueError) as exc:
        return err_payload(f"displacement_samples must contain numbers: {exc}", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "subd_apply_displacement")

    node = {
        "id": node_id,
        "op": "subd_apply_displacement",
        "target_id": target_id,
        "level": level,
        "displacement_samples": arr,
        "face_index": int(face_index),
    }

    try:
        content = append_feature_node(content, node)
    except Exception as exc:
        return err_payload(f"failed to append node: {exc}", "INTERNAL")

    n_rows = len(arr)
    n_cols = len(arr[0])
    return ok_payload({
        "id": node_id,
        "op": "subd_apply_displacement",
        "level": level,
        "grid_shape": [n_rows, n_cols],
        "face_index": int(face_index),
        "message": (
            f"Displacement map ({n_rows}×{n_cols}) will be applied at "
            f"subdivision level {level}."
        ),
    })


# ---------------------------------------------------------------------------
# subd_extract_displacement
# ---------------------------------------------------------------------------

subd_extract_displacement_spec = ToolSpec(
    name="subd_extract_displacement",
    description=(
        "Extract the displacement map from a sculpted fine mesh. "
        "Given a fine (sculpted) mesh that was produced by subdividing a base "
        "cage to a specific level and then free-form edited, recovers the "
        "per-vertex signed normal displacement and serialises it as a "
        "`subd_extract_displacement` node in the target `.feature` file. "
        "The output displacement_samples grid can be passed directly to "
        "`subd_apply_displacement` to re-apply the same sculpt to any cage "
        "that shares the same topology. "
        "No OCCT required — pure-Python Catmull-Clark + Stam evaluator."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "base_id": {
                "type": "string",
                "description": "Node id of the base SubD cage node.",
            },
            "fine_id": {
                "type": "string",
                "description": "Node id of the sculpted fine mesh node.",
            },
            "level": {
                "type": "integer",
                "description": (
                    "Subdivision level used to produce the fine mesh from the base cage."
                ),
                "minimum": 1,
                "maximum": 6,
                "default": 2,
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "base_id", "fine_id"],
    },
)


@register(subd_extract_displacement_spec, write=True)
async def run_subd_extract_displacement(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    base_id = a.get("base_id", "").strip()
    fine_id = a.get("fine_id", "").strip()
    level = a.get("level", 2)
    node_id = a.get("id", "").strip()

    if not file_id or not base_id or not fine_id:
        return err_payload("file_id, base_id and fine_id are required", "BAD_ARGS")
    if not isinstance(level, int) or not (1 <= level <= 6):
        return err_payload("level must be an integer 1–6", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "subd_extract_displacement")

    node = {
        "id": node_id,
        "op": "subd_extract_displacement",
        "base_id": base_id,
        "fine_id": fine_id,
        "level": level,
    }

    try:
        content = append_feature_node(content, node)
    except Exception as exc:
        return err_payload(f"failed to append node: {exc}", "INTERNAL")

    return ok_payload({
        "id": node_id,
        "op": "subd_extract_displacement",
        "level": level,
        "message": (
            f"Displacement extraction node appended (base={base_id}, "
            f"fine={fine_id}, level={level})."
        ),
    })
