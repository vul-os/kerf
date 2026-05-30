"""
subd_decimate_to_cage_tool.py
=============================
LLM tool: ``subd_decimate_dense_mesh_to_cage``

Converts a dense triangle mesh (e.g. limit-surface samples) to a low-poly
SubD cage using QEM edge collapse + quad-pair recovery.

See ``subd_decimate_to_cage.dense_mesh_to_subd_cage`` for the full algorithm.
"""

from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

# ---------------------------------------------------------------------------
# ToolSpec
# ---------------------------------------------------------------------------

subd_decimate_spec = ToolSpec(
    name="subd_decimate_dense_mesh_to_cage",
    description=(
        "Given a dense triangle mesh (assumed to be limit-surface samples from "
        "a SubD or scanned surface), produce a low-poly SubD control cage that "
        "when Catmull-Clark subdivided reproduces the original mesh within "
        "tolerance.\n\n"
        "**Algorithm**: Garland–Heckbert 1997 QEM edge collapse with 4×4 quadric "
        "per vertex and priority-queue collapse, followed by Bommes 2013 §3 "
        "triangle-pair → quad recovery, producing a Catmull-Clark valid quad cage.\n\n"
        "**Inputs**: raw vertex / face arrays (triangle mesh).\n\n"
        "**Outputs**: SubDCage (vertices + faces, mixed quad + tri fallback) "
        "plus a DecimationReport (deviation, quad_count, tri_fallback_count, "
        "collapse_iterations, deviation_ratio).\n\n"
        "**target_quads**: approximate desired quad count. For a dense torus "
        "(1000 triangles) use target_quads=64. Actual count may be ±15% due "
        "to triangle pairing constraints.\n\n"
        "**planar_dot**: minimum cos(angle) between adjacent face normals for "
        "quad pairing (default 0.95 ≈ 18°). Reduce to 0.85 for curved surfaces.\n\n"
        "**Honest flag**: arbitrary triangle topology may not always recover "
        "ideal quads. Unmatched triangles fall back to triangle SubD faces and "
        "are reported in ``tri_fallback_count``."
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
                    "maxItems": 3,
                },
                "description": "List of [i, j, k] triangle face index triples.",
            },
            "target_quads": {
                "type": "integer",
                "description": "Approximate desired quad count in output cage. Default 64.",
            },
            "planar_dot": {
                "type": "number",
                "description": (
                    "Minimum normal dot product for quad pairing (0.95 = 18°). "
                    "Default 0.95. Reduce to 0.85 for highly curved surfaces."
                ),
            },
        },
        "required": ["vertices", "faces"],
    },
)


@register(subd_decimate_spec, write=False)
async def run_subd_decimate_dense_mesh_to_cage(ctx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        vertices = a.get("vertices")
        faces = a.get("faces")
        if not vertices or not faces:
            return err_payload("vertices and faces are required", "BAD_ARGS")
        if not isinstance(vertices, list) or not isinstance(faces, list):
            return err_payload("vertices and faces must be arrays", "BAD_ARGS")

        target_quads = int(a.get("target_quads", 64))
        planar_dot = float(a.get("planar_dot", 0.95))

        from kerf_cad_core.geom.subd_decimate_to_cage import dense_mesh_to_subd_cage

        cage, report = dense_mesh_to_subd_cage(
            vertices=vertices,
            faces=faces,
            target_quads=target_quads,
            planar_dot=planar_dot,
        )

        return ok_payload({
            "cage": {
                "vertices": cage.vertices,
                "faces": cage.faces,
                "num_vertices": cage.num_vertices,
                "num_faces": cage.num_faces,
            },
            "report": {
                "quad_count": report.quad_count,
                "tri_fallback_count": report.tri_fallback_count,
                "collapse_iterations": report.collapse_iterations,
                "max_deviation": report.max_deviation,
                "bbox_diagonal": report.bbox_diagonal,
                "deviation_ratio": report.deviation_ratio,
            },
            "honest_flag": (
                report.tri_fallback_count > 0
            ),
            "honest_note": (
                f"{report.tri_fallback_count} triangle face(s) could not be "
                "paired into quads and remain as triangle SubD faces."
                if report.tri_fallback_count > 0
                else "All faces recovered as quads."
            ),
        })

    except Exception as e:
        return err_payload(f"decimation error: {e}", "DECIMATE_ERROR")
