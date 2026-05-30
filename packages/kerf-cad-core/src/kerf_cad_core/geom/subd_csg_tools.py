"""
subd_csg_tools.py
=================
LLM ToolSpec for SubD-cage boolean operations (transversal case).

Registers the ``subd_boolean`` tool into the kerf chat tool registry.

This tool wraps ``subd_boolean_transversal`` from ``geom.subd_csg`` and
surfaces it as a feature-tree node that the CAD agent can invoke.

Reference: Cohen-Or-Sheffer 2003 §5 (transversal SubD booleans).
"""

from __future__ import annotations

import json
import math
import uuid
from typing import Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

from kerf_cad_core.surfacing import (
    append_feature_node,
    next_node_id,
    read_feature_content,
)


# ---------------------------------------------------------------------------
# subd_boolean ToolSpec
# ---------------------------------------------------------------------------

subd_boolean_spec = ToolSpec(
    name="subd_boolean",
    description=(
        "Compute a boolean operation (union / intersection / difference) on two "
        "SubD control cages for the **transversal-intersection case** "
        "(Cohen-Or-Sheffer 2003 §5).  "
        "Transversal = the two SubD surfaces intersect in a curve with no grazing "
        "tangent contact.  "
        "\n\n"
        "Steps performed internally:\n"
        "1. Triangulate both cages (level-0, diagonal split).\n"
        "2. Apply triangle-mesh boolean via `mesh_boolean_sealed`.\n"
        "3. Re-quadrangulate result (Bommes-Kobbelt 2007 dual-graph pairing).\n"
        "4. Propagate crease tags from both inputs; new intersection-curve edges "
        "are tagged sharpness=∞.\n"
        "\n"
        "Returns the result cage node id, vertex/face counts, max re-quad error "
        "(degrees), and whether the cages were transversal.  "
        "Fails with `NOT_TRANSVERSAL` if grazing contact is detected."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "cage_a_id": {
                "type": "string",
                "description": "Node id of the first SubD cage (source A).",
            },
            "cage_b_id": {
                "type": "string",
                "description": "Node id of the second SubD cage (source B).",
            },
            "op": {
                "type": "string",
                "enum": ["union", "intersection", "difference"],
                "description": "Boolean operation to apply.",
                "default": "union",
            },
            "tol": {
                "type": "number",
                "description": "Vertex-weld tolerance (default 1e-6).",
                "default": 1e-6,
            },
            "check_transversal": {
                "type": "boolean",
                "description": (
                    "If true (default), verify transversality before proceeding. "
                    "Set false to skip the check and proceed regardless."
                ),
                "default": True,
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id for the result node.",
            },
        },
        "required": ["file_id", "cage_a_id", "cage_b_id"],
    },
)


@register(subd_boolean_spec, write=True)
async def run_subd_boolean(ctx: ProjectCtx, args: bytes) -> str:
    """Execute a SubD-cage boolean operation and append the result node."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    cage_a_id = a.get("cage_a_id", "").strip()
    cage_b_id = a.get("cage_b_id", "").strip()
    op = a.get("op", "union")
    tol = float(a.get("tol", 1e-6))
    check_transversal = bool(a.get("check_transversal", True))
    node_id = a.get("id", "").strip()

    if not file_id or not cage_a_id or not cage_b_id:
        return err_payload("file_id, cage_a_id, and cage_b_id are required", "BAD_ARGS")
    if op not in ("union", "intersection", "difference"):
        return err_payload(
            f"op must be 'union', 'intersection', or 'difference'; got {op!r}",
            "BAD_ARGS",
        )

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a UUID", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "subd_boolean")

    # Resolve cage nodes from the feature tree to get their geometry.
    # The feature tree stores cage vertices/faces as serialised geometry in
    # the node's ``cage`` field (set by earlier subd_* ops).
    def _find_node(content_: dict, nid: str) -> Optional[dict]:
        for node in content_.get("nodes", []):
            if node.get("id") == nid:
                return node
        return None

    node_a = _find_node(content, cage_a_id)
    node_b = _find_node(content, cage_b_id)

    if node_a is None:
        return err_payload(f"cage_a_id {cage_a_id!r} not found in feature tree", "NOT_FOUND")
    if node_b is None:
        return err_payload(f"cage_b_id {cage_b_id!r} not found in feature tree", "NOT_FOUND")

    # Extract cage geometry from node fields
    cage_a_data = node_a.get("cage") or node_a.get("result_cage")
    cage_b_data = node_b.get("cage") or node_b.get("result_cage")

    if not cage_a_data:
        return err_payload(f"node {cage_a_id!r} has no cage geometry", "BAD_ARGS")
    if not cage_b_data:
        return err_payload(f"node {cage_b_id!r} has no cage geometry", "BAD_ARGS")

    # Deserialise cages
    try:
        from kerf_cad_core.geom.subd import SubDMesh

        def _load_cage(data: dict) -> SubDMesh:
            cage = SubDMesh(
                vertices=data.get("vertices", []),
                faces=data.get("faces", []),
            )
            for k, v in data.get("creases", {}).items():
                a_idx, b_idx = map(int, k.split(","))
                cage.set_crease(a_idx, b_idx, float(v))
            return cage

        cage_a = _load_cage(cage_a_data)
        cage_b = _load_cage(cage_b_data)
    except Exception as exc:
        return err_payload(f"failed to deserialise cage geometry: {exc}", "ERROR")

    # Transversality check
    transversal = True
    if check_transversal:
        from kerf_cad_core.geom.subd_csg import is_transversal
        transversal = is_transversal(cage_a, cage_b)
        if not transversal:
            return err_payload(
                "cages are not transversally intersecting (grazing contact detected); "
                "set check_transversal=false to bypass",
                "NOT_TRANSVERSAL",
            )

    # Perform the boolean
    from kerf_cad_core.geom.subd_csg import subd_boolean_transversal

    result = subd_boolean_transversal(cage_a, cage_b, op=op, tol=tol)
    if not result.ok:
        return err_payload(f"subd_boolean_transversal failed: {result.reason}", "ERROR")

    # Serialise result cage
    crease_serial = {
        f"{k[0]},{k[1]}": (v if math.isfinite(v) else "inf")
        for k, v in result.crease_tags.items()
    }
    result_cage_data = {
        "vertices": result.cage.vertices,
        "faces": result.cage.faces,
        "creases": crease_serial,
    }

    node = {
        "id": node_id,
        "op": "subd_boolean",
        "cage_a_id": cage_a_id,
        "cage_b_id": cage_b_id,
        "boolean_op": op,
        "tol": tol,
        "transversal": transversal,
        "result_cage": result_cage_data,
        "max_local_error_deg": result.max_local_error,
        "vertex_count": len(result.cage.vertices),
        "face_count": len(result.cage.faces),
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "subd_boolean",
        "boolean_op": op,
        "vertex_count": len(result.cage.vertices),
        "face_count": len(result.cage.faces),
        "max_local_error_deg": result.max_local_error,
        "transversal": transversal,
        "crease_count": len(result.crease_tags),
    })
