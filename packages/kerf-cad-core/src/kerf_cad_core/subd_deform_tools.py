"""subd_deform_tools.py — Wire SubD deformation cage as an LLM ToolSpec.

Wires the deformation-cage workflow from
``kerf_cad_core.geom.subd_deform`` into the tool/feature/LLM surface as a
single ``subd_deform_with_cage`` feature node.

The node stores:
  - the detail mesh (vertex + face arrays) in the rest pose
  - the cage (vertex + face arrays) in the deformed pose
  - the ``method`` used to build the cage ('convex_hull' | 'simplification')
  - the target cage vertex count (``n_cage_verts``)

On evaluation the worker calls ``build_deform_cage`` to compute the MVC
weights and then ``apply_cage_deformation`` with the stored deformed cage
vertices.  This is pure-Python; no OCCT is required.
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

from kerf_cad_core.surfacing import (
    append_feature_node,
    next_node_id,
    read_feature_content,
)

# ── subd_deform_with_cage ─────────────────────────────────────────────────────

subd_deform_with_cage_spec = ToolSpec(
    name="subd_deform_with_cage",
    description=(
        "Append a `subd_deform_with_cage` node to a `.feature` file. "
        "Controls a high-resolution detail mesh by manipulating a low-resolution "
        "cage of control points using mean-value coordinates (Ju-Schaefer-Warren "
        "2005, SIGGRAPH).  "
        "The cage is automatically built from the detail mesh's convex hull and "
        "simplified to `n_cage_verts` control points.  Each detail vertex is "
        "bound to the cage via MVC weights (partition of unity).  "
        "Deforming the cage vertices then propagates smoothly to the full detail "
        "mesh: new_pos[i] = Σ_j w[i,j] · cage_deformed[j].  "
        "Use for character-animation style rigging, fast organic model editing, "
        "and shape blending.  No OCCT required — pure-Python + NumPy."
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
                "description": "Id of an existing SubD cage node whose *evaluated* mesh is the detail mesh.",
            },
            "cage_deformed": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 4,
                "description": (
                    "Deformed cage vertex positions as [[x,y,z], ...] (≥4 points). "
                    "Must match the cage built from `n_cage_verts` and `method`. "
                    "To find the rest-pose cage first, call with the original "
                    "positions and inspect the returned `cage_verts`."
                ),
            },
            "n_cage_verts": {
                "type": "integer",
                "description": "Target number of cage control vertices (default 20, min 4).",
                "minimum": 4,
                "default": 20,
            },
            "method": {
                "type": "string",
                "enum": ["convex_hull", "simplification"],
                "description": (
                    "'convex_hull' — use the full convex hull of the detail mesh "
                    "(may have more than n_cage_verts vertices); "
                    "'simplification' — iteratively merge closest vertices until "
                    "≤ n_cage_verts remain.  Default 'convex_hull'."
                ),
                "default": "convex_hull",
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "target_id", "cage_deformed"],
    },
)


@register(subd_deform_with_cage_spec, write=True)
async def run_subd_deform_with_cage(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    cage_deformed = a.get("cage_deformed")
    n_cage_verts = a.get("n_cage_verts", 20)
    method = a.get("method", "convex_hull")
    node_id = a.get("id", "").strip()

    # --- validation ---
    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")

    if not isinstance(cage_deformed, list) or len(cage_deformed) < 4:
        return err_payload("cage_deformed must be a list of ≥4 [x,y,z] points", "BAD_ARGS")

    for i, pt in enumerate(cage_deformed):
        if not isinstance(pt, list) or len(pt) != 3:
            return err_payload(
                f"cage_deformed[{i}] must be [x, y, z] with exactly 3 values", "BAD_ARGS"
            )
        if not all(isinstance(v, (int, float)) for v in pt):
            return err_payload(
                f"cage_deformed[{i}] contains non-numeric values", "BAD_ARGS"
            )

    if not isinstance(n_cage_verts, int) or n_cage_verts < 4:
        return err_payload("n_cage_verts must be an integer ≥ 4", "BAD_ARGS")

    if method not in ("convex_hull", "simplification"):
        return err_payload("method must be 'convex_hull' or 'simplification'", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "subd_deform_with_cage")

    node = {
        "id": node_id,
        "op": "subd_deform_with_cage",
        "target_id": target_id,
        "cage_deformed": cage_deformed,
        "n_cage_verts": n_cage_verts,
        "method": method,
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "subd_deform_with_cage",
        "n_cage_verts": n_cage_verts,
        "method": method,
    })
