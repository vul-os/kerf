"""LLM tool registration for B-rep vertex edge-degree check.

Exposes one tool to the Kerf chat agent:

  brep_check_vertex_degrees
      For a face-list dict (same schema as ``brep_inspect_connectivity``),
      count the number of incident edges at each vertex and flag:

        * boundary vertices (degree < expected_degree) — open-mesh seams
          or unsealed B-rep junctions.
        * non-manifold vertices (degree > expected_degree + 2) — dense
          fans from T-junctions or bowtie geometry that may need repair.

      Returns a per-vertex degree histogram plus counts and identifiers of
      irregular vertices.

      References: Mantyla 1988 §3.4; Hoffmann 1989 §4.

HONEST CAVEATS (reported in tool output)
-----------------------------------------
* Edge-based degree only: does NOT analyse face-fan angular order or
  whether non-manifold edges exist at high-degree vertices.
* Vertex identity is by hashable id — duplicate Vertex objects for the
  same geometric point each count separately.
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

__all__ = ["run_brep_check_vertex_degrees"]


# ---------------------------------------------------------------------------
# Shared schema fragment (re-uses the same face-list schema)
# ---------------------------------------------------------------------------

_FACE_SCHEMA = {
    "type": "array",
    "description": (
        "List of faces. Each face has a 'face_id' (string or int) and an "
        "'edges' list. Each edge has 'edge_id', 'start' (vertex id), "
        "and 'end' (vertex id)."
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
                    },
                    "required": ["edge_id", "start", "end"],
                },
            },
        },
        "required": ["face_id", "edges"],
    },
}


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_vertex_degree_spec = ToolSpec(
    name="brep_check_vertex_degrees",
    description=(
        "Count the number of incident edges at each vertex of a B-rep "
        "shell/solid and flag topologically irregular vertices "
        "(Mantyla 1988 §3.4 + Hoffmann 1989 §4):\n\n"
        "  • boundary vertex — degree < expected_degree (open mesh seam or "
        "unsealed junction; needs topology repair before Boolean ops)\n"
        "  • non-manifold vertex — degree > expected_degree + 2 (dense fan "
        "from T-junction or bowtie; may need mesh surgery)\n\n"
        "Returns a degree histogram (degree → vertex count), the total "
        "boundary and non-manifold vertex counts, the maximum observed "
        "degree, and the identifiers of irregular vertices (capped at 500).\n\n"
        "CAVEATS: edge-based degree only — does NOT analyse face-fan "
        "angular order or whether high-degree vertices have non-manifold "
        "edges.  Combine with brep_inspect_connectivity for full diagnosis."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "faces": _FACE_SCHEMA,
            "expected_degree": {
                "type": "integer",
                "description": (
                    "Expected (typical) vertex valence. "
                    "3 for triangulated meshes / box corners, "
                    "4 for quad-dominant B-rep solids (default), "
                    "6 for interior vertices of a regular triangle mesh."
                ),
                "default": 4,
            },
        },
        "required": ["faces"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register(_vertex_degree_spec, write=False)
async def run_brep_check_vertex_degrees(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    faces = a.get("faces")
    if not isinstance(faces, list):
        return err_payload("'faces' must be a list", "BAD_ARGS")

    expected_degree = a.get("expected_degree", 4)
    if not isinstance(expected_degree, int) or expected_degree < 1:
        return err_payload(
            "'expected_degree' must be a positive integer", "BAD_ARGS"
        )

    try:
        from kerf_cad_core.geom.vertex_degree_check import check_vertex_degrees
        report = check_vertex_degrees(faces, expected_degree=expected_degree)
    except Exception as e:
        return err_payload(f"vertex degree check failed: {e}", "ERROR")

    return ok_payload(report.as_dict())
