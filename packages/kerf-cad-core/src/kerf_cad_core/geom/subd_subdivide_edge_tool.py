"""
subd_subdivide_edge_tool.py
===========================
LLM tool: ``subd_subdivide_edge``

Wires :func:`kerf_cad_core.geom.subd_subdivide_edge.subdivide_edge` into the
tool registry.  SUBD-CAGE-SUBDIVIDE-EDGE: insert a midpoint vertex on a single
cage edge (localized refinement — not a full Catmull-Clark pass).

Ref: Catmull & Clark 1978; Stam 1998 §4; Maya polySplit API (Autodesk 2024).
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

subd_subdivide_edge_spec = ToolSpec(
    name="subd_subdivide_edge",
    description=(
        "Insert a midpoint vertex on a **single cage edge** (localized refinement — "
        "not a full Catmull-Clark subdivision pass).\n\n"
        "Analogous to Maya `polySplit` / Blender `subdivide_edges` on one edge. "
        "The two adjacent quad faces each split into a triangle + a quad (one new "
        "interior edge per adjacent face).  Vertex count increases by 1; the Euler "
        "characteristic is preserved.\n\n"
        "**Algorithm** (Catmull & Clark 1978 §3; Stam 1998 §4 local refinement):\n"
        "1. Locate endpoints v_a, v_b of the edge.\n"
        "2. Insert v_m = lerp(v_a, v_b, position_t).\n"
        "3. For each adjacent face: split into [v_a, v_m, last_vertex] (triangle) "
        "   + [v_m, v_b, ...rest] (polygon/quad).\n\n"
        "**Cube oracle** (12 edges, 1 interior edge split):\n"
        "  V: 8 → 9, F: 6 → 8, E: 12 → 15, Euler: 9-15+8 = 2 ✓\n\n"
        "**Inputs**: vertices [[x,y,z],...], faces [[i,j,k,l],...], edge_index (int), "
        "optional position_t (0.5 = midpoint), optional split_strategy ('quad'|'tri').\n\n"
        "**Outputs**: new cage vertices/faces, new_vertex_index, new_face_count, "
        "adjacent_face_count, has_non_quad_input flag.\n\n"
        "**Honest flag**: only pure quad-cage input is fully supported. Mixed-topology "
        "cages (any non-quad face) set ``has_non_quad_input=true``. Output always "
        "contains triangles (face_a per adjacent face) — a single edge split on a "
        "quad cannot produce two quads without also splitting the opposite edge "
        "(that would be a loop-cut, not an edge-split)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "vertices": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": "List of [x, y, z] vertex coordinates.",
            },
            "faces": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 3,
                },
                "description": "List of face vertex-index lists (quads recommended).",
            },
            "edge_index": {
                "type": "integer",
                "description": (
                    "Index of the edge to subdivide from cage_edges() order. "
                    "Use cage_edges() or subd_compute_edge_ring to find the right index."
                ),
                "minimum": 0,
            },
            "position_t": {
                "type": "number",
                "description": (
                    "Parametric position along the edge in (0, 1). "
                    "0.5 = midpoint (default). 0.25 = quarter-point toward v_a."
                ),
            },
            "split_strategy": {
                "type": "string",
                "enum": ["quad", "tri"],
                "description": (
                    "'quad' (default) or 'tri'. Both currently use the same "
                    "topology; reserved for future pure-quad split strategies."
                ),
            },
        },
        "required": ["vertices", "faces", "edge_index"],
    },
)


@register(subd_subdivide_edge_spec, write=False)
async def run_subd_subdivide_edge(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        vertices = a.get("vertices")
        faces = a.get("faces")
        edge_index = a.get("edge_index")

        if vertices is None or faces is None or edge_index is None:
            return err_payload("vertices, faces, and edge_index are required", "BAD_ARGS")
        if not isinstance(vertices, list) or not isinstance(faces, list):
            return err_payload("vertices and faces must be arrays", "BAD_ARGS")

        position_t = float(a.get("position_t", 0.5))
        split_strategy = str(a.get("split_strategy", "quad"))

        from kerf_cad_core.geom.subd_authoring import SubDCage
        from kerf_cad_core.geom.subd_subdivide_edge import subdivide_edge

        cage = SubDCage(
            vertices=[list(v) for v in vertices],
            faces=[list(f) for f in faces],
        )

        result = subdivide_edge(
            cage=cage,
            edge_index=int(edge_index),
            position_t=position_t,
            split_strategy=split_strategy,
        )

        nc = result.new_cage
        return ok_payload({
            "cage": {
                "vertices": nc.vertices,
                "faces": nc.faces,
                "num_vertices": nc.num_vertices,
                "num_faces": nc.num_faces,
                "num_edges": len(nc.cage_edges()),
            },
            "new_vertex_index": result.new_vertex_index,
            "new_face_count": result.new_face_count,
            "adjacent_face_count": result.adjacent_face_count,
            "has_non_quad_input": result.has_non_quad_input,
            "honest_note": (
                "Adjacent faces with valence != 4 detected; output is an approximation "
                "for mixed-topology input. Prefer pure quad-cage input."
                if result.has_non_quad_input
                else "Pure quad input; standard edge split applied."
            ),
        })

    except ValueError as ve:
        return err_payload(str(ve), "BAD_ARGS")
    except Exception as e:
        return err_payload(f"subdivide_edge error: {e}", "SUBDIVIDE_EDGE_ERROR")
