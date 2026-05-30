"""LLM tool registration for B-rep connectivity inspection.

Exposes two tools to the Kerf chat agent:

  brep_inspect_connectivity
      For a list of faces (each with edges + vertex endpoints), classify every
      edge by its radial valence (Weiler 1985 §3): dangling (0 faces), boundary
      (1 face), interior/manifold (2 faces), or non-manifold (≥3 faces).
      Also counts isolated vertices, degenerate (zero-length) edges, and shell
      connectivity components (union-find, Mantyla 1988 §6).

  brep_is_manifold
      Convenience boolean: returns True iff the shell is a closed 2-manifold
      (no boundary edges, no non-manifold edges, single connected component).
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

__all__ = [
    "run_brep_inspect_connectivity",
    "run_brep_is_manifold",
]

# ---------------------------------------------------------------------------
# Shared schema fragment
# ---------------------------------------------------------------------------

_FACE_SCHEMA = {
    "type": "array",
    "description": (
        "List of faces.  Each face has a 'face_id' (string or int) and an "
        "'edges' list.  Each edge has 'edge_id', 'start' (vertex id), "
        "'end' (vertex id), and optional 'length' (float, metres)."
    ),
    "items": {
        "type": "object",
        "properties": {
            "face_id": {"type": ["string", "integer"]},
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "edge_id": {"type": ["string", "integer"]},
                        "start":   {"type": ["string", "integer"]},
                        "end":     {"type": ["string", "integer"]},
                        "length":  {"type": "number"},
                    },
                    "required": ["edge_id", "start", "end"],
                },
            },
        },
        "required": ["face_id", "edges"],
    },
}


# ---------------------------------------------------------------------------
# brep_inspect_connectivity
# ---------------------------------------------------------------------------

_inspect_spec = ToolSpec(
    name="brep_inspect_connectivity",
    description=(
        "Classify every edge in a B-rep shell/solid by its radial valence "
        "(Weiler 1985 §3 + Mantyla 1988 §6 Euler operators):\n"
        "  • dangling (0 faces) — should be absent in a valid B-rep\n"
        "  • boundary (1 face) — open shell boundary\n"
        "  • manifold interior (2 faces) — watertight 2-manifold edge\n"
        "  • non-manifold (≥3 faces) — T-junction / fan defect\n"
        "Also returns isolated vertex count, degenerate (zero-length) edge "
        "count, shell connected-components (union-find), and the "
        "Euler–Poincaré residual V-E+F."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "faces": _FACE_SCHEMA,
        },
        "required": ["faces"],
    },
)


@register(_inspect_spec, write=False)
async def run_brep_inspect_connectivity(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    faces = a.get("faces")
    if not isinstance(faces, list):
        return err_payload("'faces' must be a list", "BAD_ARGS")

    try:
        from kerf_cad_core.geom.brep_connect_inspector import inspect_connectivity
        report = inspect_connectivity(faces)
    except Exception as e:
        return err_payload(f"connectivity inspection failed: {e}", "ERROR")

    return ok_payload({
        "face_count":              report.face_count,
        "edge_count":              report.edge_count,
        "vertex_count":            report.vertex_count,
        "manifold_edge_count":     report.manifold_edge_count,
        "boundary_edge_count":     report.boundary_edge_count,
        "nonmanifold_edge_count":  report.nonmanifold_edge_count,
        "dangling_edge_count":     report.dangling_edge_count,
        "isolated_vertex_count":   report.isolated_vertex_count,
        "degenerate_edge_count":   report.degenerate_edge_count,
        "components":              report.components,
        "is_manifold_closed":      report.is_manifold_closed,
        "euler_poincare_vef":      report.euler_poincare_vef,
        "free_edge_ids":           report.free_edges[:200],  # cap for large models
    })


# ---------------------------------------------------------------------------
# brep_is_manifold
# ---------------------------------------------------------------------------

_manifold_spec = ToolSpec(
    name="brep_is_manifold",
    description=(
        "Return whether a B-rep shell is a closed 2-manifold solid: "
        "no boundary edges, no non-manifold edges, single connected component."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "faces": _FACE_SCHEMA,
        },
        "required": ["faces"],
    },
)


@register(_manifold_spec, write=False)
async def run_brep_is_manifold(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    faces = a.get("faces")
    if not isinstance(faces, list):
        return err_payload("'faces' must be a list", "BAD_ARGS")

    try:
        from kerf_cad_core.geom.brep_connect_inspector import is_manifold_closed
        result = is_manifold_closed(faces)
    except Exception as e:
        return err_payload(f"manifold check failed: {e}", "ERROR")

    return ok_payload({"is_manifold_closed": result})
