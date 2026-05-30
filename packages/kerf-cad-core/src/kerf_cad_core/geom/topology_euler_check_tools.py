"""LLM tool registration for B-rep Euler-Poincaré topology verification.

Exposes one tool to the Kerf chat agent:

  brep_verify_euler_topology
      Given a face-list (same schema as ``brep_inspect_connectivity``) plus
      optional genus/shells/inner-loops hints, verify the generalised
      Euler-Poincaré formula and return a structured report.

      The formula verified is (Mantyla 1988 §6; Hoffmann 1989 §5)::

          V - E + F  =  2*(S - G) + H

      where V = vertices, E = edges, F = faces, S = shells, G = genus,
      H = ring (inner) loops.

      For a valid manifold closed solid with no through-holes: V-E+F=2.
      For a torus: V-E+F=0.
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

__all__ = ["run_brep_verify_euler_topology"]

# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

_FACE_SCHEMA = {
    "type": "array",
    "description": (
        "List of faces. Each face has a 'face_id' (string or int) and an "
        "'edges' list. Each edge has 'edge_id', 'start' (vertex id), "
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
                    "required": ["edge_id"],
                },
            },
        },
        "required": ["face_id", "edges"],
    },
}

_euler_spec = ToolSpec(
    name="brep_verify_euler_topology",
    description=(
        "Verify the generalised Euler-Poincaré formula for a B-rep solid "
        "(Mantyla 1988 §6; Hoffmann 1989 §5):\n\n"
        "  V - E + F  =  2*(S - G) + H\n\n"
        "where V = vertices, E = edges, F = faces, S = shells (connected "
        "face-sets), G = genus (topological through-holes/handles; 0 for "
        "sphere/box, 1 for torus), H = ring/inner loops (inner loops on faces "
        "beyond the mandatory outer loop, e.g. counterbore holes).\n\n"
        "For a valid manifold closed solid with no through-holes: V-E+F=2.\n"
        "For a torus: V-E+F=0.\n\n"
        "CAVEATS: genus and inner-loop count cannot be inferred from the flat "
        "face-edge list — supply genus_hint and inner_loops_hint for non-trivial "
        "solids. Vertex deduplication issues after sew/heal may cause spurious "
        "failures (see degenerate_vertices_hint in the response)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "faces": _FACE_SCHEMA,
            "genus_hint": {
                "type": "integer",
                "description": (
                    "Genus G (number of topological through-holes/handles). "
                    "0 for a box/sphere/cylinder, 1 for a torus, etc. "
                    "Default 0."
                ),
                "default": 0,
            },
            "shells_hint": {
                "type": "integer",
                "description": (
                    "Number of shells S. If omitted, computed automatically "
                    "from edge adjacency via union-find."
                ),
            },
            "inner_loops_hint": {
                "type": "integer",
                "description": (
                    "Number of ring/inner loops H (inner loops on faces beyond "
                    "the mandatory outer loop). 0 for solids with no face holes. "
                    "Default 0."
                ),
                "default": 0,
            },
        },
        "required": ["faces"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register(_euler_spec, write=False)
async def run_brep_verify_euler_topology(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    faces = a.get("faces")
    if not isinstance(faces, list):
        return err_payload("'faces' must be a list", "BAD_ARGS")

    genus_hint = a.get("genus_hint", 0)
    if not isinstance(genus_hint, int) or genus_hint < 0:
        return err_payload("'genus_hint' must be a non-negative integer", "BAD_ARGS")

    shells_hint = a.get("shells_hint")
    if shells_hint is not None and (not isinstance(shells_hint, int) or shells_hint < 0):
        return err_payload("'shells_hint' must be a non-negative integer", "BAD_ARGS")

    inner_loops_hint = a.get("inner_loops_hint", 0)
    if not isinstance(inner_loops_hint, int) or inner_loops_hint < 0:
        return err_payload("'inner_loops_hint' must be a non-negative integer", "BAD_ARGS")

    try:
        from kerf_cad_core.geom.topology_euler_check import (
            verify_euler_topology_from_dict,
        )
        report = verify_euler_topology_from_dict(
            faces,
            genus_hint=genus_hint,
            shells_hint=shells_hint,
            inner_loops_hint=inner_loops_hint,
        )
    except Exception as e:
        return err_payload(f"Euler topology check failed: {e}", "ERROR")

    return ok_payload(report.as_dict())
