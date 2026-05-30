"""LLM tool registration for non-manifold detection and repair.

Exposes two tools to the Kerf chat agent:

  brep_non_manifold_check
      Check a mesh file for non-manifold edges and vertices.
      Returns counts + edge/vertex lists.

  brep_non_manifold_repair
      Repair non-manifold conditions in a mesh file and write the result back.
      Supports mode='split' (default) and mode='delete_smaller'.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

__all__ = [
    "run_brep_non_manifold_check",
    "run_brep_non_manifold_repair",
]


# ---------------------------------------------------------------------------
# Shared helpers (same DB access pattern as heal.py)
# ---------------------------------------------------------------------------


def _read_mesh(ctx: ProjectCtx, file_id: uuid.UUID):
    row = ctx.pool.fetchone(
        "select content, kind from files where id = $1 and project_id = $2 and deleted_at is null",
        file_id, ctx.project_id,
    )
    if not row:
        return None, None, "file not found"
    content, kind = row
    if kind not in ("mesh", "step", "text"):
        return None, None, f"file is kind={kind!r}, expected mesh/step/text"
    try:
        if isinstance(content, (bytes, bytearray)):
            content = content.decode("utf-8")
        doc = json.loads(content)
    except Exception as e:
        return None, None, f"JSON parse error: {e}"
    # Normalise to verts/faces
    if "verts" in doc and "faces" in doc:
        return doc["verts"], doc["faces"], None
    if "vertices" in doc and "indices" in doc:
        flat = doc["indices"]
        faces = [[flat[i * 3], flat[i * 3 + 1], flat[i * 3 + 2]]
                 for i in range(len(flat) // 3)]
        return doc["vertices"], faces, None
    return None, None, "unrecognised mesh format (need verts+faces or vertices+indices)"


def _write_mesh(ctx: ProjectCtx, file_id: uuid.UUID, verts, faces) -> Optional[str]:
    body = json.dumps({"verts": verts, "faces": faces})
    try:
        ctx.pool.execute(
            "update files set content = $1, updated_at = now() where id = $2 and project_id = $3",
            body, file_id, ctx.project_id,
        )
        return None
    except Exception as e:
        return str(e)


def _parse_file_id(a: dict):
    raw = (a.get("file_id") or "").strip()
    if not raw:
        return None, "file_id is required"
    try:
        return uuid.UUID(raw), None
    except Exception:
        return None, "file_id must be a valid UUID"


# ---------------------------------------------------------------------------
# brep_non_manifold_check
# ---------------------------------------------------------------------------

_check_spec = ToolSpec(
    name="brep_non_manifold_check",
    description=(
        "Check a mesh file for non-manifold topology conditions: "
        "T-junction edges (shared by > 2 faces) and touching-cone vertices "
        "(edge fan not a single connected loop). "
        "Returns counts and the specific edge/vertex indices found."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the mesh file to check.",
            },
        },
        "required": ["file_id"],
    },
)


@register(_check_spec, write=False)
async def run_brep_non_manifold_check(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    fid, err = _parse_file_id(a)
    if err:
        return err_payload(err, "BAD_ARGS")

    verts, faces, err = _read_mesh(ctx, fid)
    if err:
        return err_payload(err, "NOT_FOUND")

    try:
        from kerf_cad_core.geom.non_manifold import detect_non_manifold_mesh
        mesh = {"verts": verts, "faces": faces}
        report = detect_non_manifold_mesh(mesh)
    except Exception as e:
        return err_payload(f"detection failed: {e}", "ERROR")

    return ok_payload({
        "file_id": str(fid),
        "is_manifold": report.is_manifold,
        "non_manifold_edge_count": len(report.non_manifold_edges),
        "non_manifold_vertex_count": len(report.non_manifold_vertices),
        "non_manifold_edges": [list(e) for e in report.non_manifold_edges[:50]],
        "non_manifold_vertices": report.non_manifold_vertices[:50],
    })


# ---------------------------------------------------------------------------
# brep_non_manifold_repair
# ---------------------------------------------------------------------------

_repair_spec = ToolSpec(
    name="brep_non_manifold_repair",
    description=(
        "Repair non-manifold edges and vertices in a mesh file and write the "
        "result back. "
        "mode='split' (default): insert midpoint vertices to give each extra "
        "face its own edge copy, and duplicate touching-cone vertices. "
        "mode='delete_smaller': keep the 2 largest-area faces per non-manifold "
        "edge; delete smaller faces and disconnected fan components. "
        "Returns a repair stats report."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the mesh file to repair.",
            },
            "mode": {
                "type": "string",
                "enum": ["split", "delete_smaller"],
                "description": (
                    "Repair strategy. 'split' preserves faces by inserting new "
                    "vertices (default). 'delete_smaller' removes surplus faces."
                ),
            },
        },
        "required": ["file_id"],
    },
)


@register(_repair_spec, write=True)
async def run_brep_non_manifold_repair(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    fid, err = _parse_file_id(a)
    if err:
        return err_payload(err, "BAD_ARGS")

    mode = a.get("mode", "split")
    if mode not in ("split", "delete_smaller"):
        return err_payload("mode must be 'split' or 'delete_smaller'", "BAD_ARGS")

    verts, faces, err = _read_mesh(ctx, fid)
    if err:
        return err_payload(err, "NOT_FOUND")

    try:
        from kerf_cad_core.geom.non_manifold import repair_non_manifold_mesh
        mesh = {"verts": verts, "faces": faces}
        result = repair_non_manifold_mesh(mesh, mode=mode)
    except Exception as e:
        return err_payload(f"repair failed: {e}", "ERROR")

    write_err = _write_mesh(ctx, fid, result.verts, result.faces)
    if write_err:
        return err_payload(write_err, "WRITE_ERR")

    s = result.stats
    return ok_payload({
        "file_id": str(fid),
        "mode": mode,
        "edges_split": s.edges_split,
        "faces_deleted": s.faces_deleted,
        "vertices_added": s.vertices_added,
        "vertices_split": s.vertices_split,
        "vertex_count_after": len(result.verts),
        "face_count_after": len(result.faces),
    })
