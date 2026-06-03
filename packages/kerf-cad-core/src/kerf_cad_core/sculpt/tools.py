"""
kerf_cad_core.sculpt.tools — Wave 8 LLM tool for sculpt brush operations.

Wave 8 module
-------------
  kerf_cad_core.sculpt.brush

Tool registered
---------------
  sculpt_apply_brush — Apply a sculpt brush stroke to a triangle mesh.
    Distinct from mesh_sculpt_brush (mesh_sculpt_brushes.py which uses a
    different dataclass API); this wrapper uses the sculpt.brush module
    BrushStroke / SculptMesh types.

References
----------
Sederberg & Parry (1986). "Free-form deformation of solid geometric models."
    SIGGRAPH Proc. pp. 151-160. (Soft-selection / falloff concept.)
Botsch & Sorkine (2008). "On linear variational surface deformation methods."
    IEEE TVCG 14(1):213-230. (Laplacian smoothing context.)
Meyer et al. (2003). "Discrete Differential-Geometry Operators for Triangulated
    2-Manifolds." VisMath. (Area-weighted vertex normal accumulation, §3.1.)
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.sculpt.brush import (
    BrushKind,
    BrushStroke,
    MeshDelta,
    SculptMesh,
    apply_brush,
    revert_delta,
)

import numpy as np


# ---------------------------------------------------------------------------
# Tool: sculpt_apply_brush
# ---------------------------------------------------------------------------

_BRUSH_KINDS = [k.value for k in BrushKind]

_sculpt_apply_brush_spec = ToolSpec(
    name="sculpt_apply_brush",
    description=(
        "Apply a sculpt brush stroke to a triangle mesh and return the updated\n"
        "vertex positions plus a delta record for undo.\n"
        "\n"
        "Brush kinds:\n"
        "  grab    — translate vertices inside radius along stroke direction\n"
        "  smooth  — Laplacian smoothing toward neighbour centroid\n"
        "  inflate — push vertices along per-vertex normal\n"
        "  crease  — pinch vertices toward stroke axis (sharpens edges)\n"
        "  pinch   — pull vertices toward brush center\n"
        "\n"
        "Falloff shapes: 'smooth' (cubic Hermite), 'linear', 'constant'.\n"
        "\n"
        "Returns:\n"
        "  positions       — updated vertex positions [[x,y,z], ...]\n"
        "  delta_indices   — affected vertex indices (for undo)\n"
        "  delta_vectors   — per-vertex displacement vectors applied\n"
        "  n_affected      — number of vertices affected\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "positions": {
                "type": "array",
                "description": "Vertex positions [[x,y,z], ...].",
                "items": {"type": "array", "items": {"type": "number"}},
            },
            "triangles": {
                "type": "array",
                "description": "Triangle faces [[i0,i1,i2], ...].",
                "items": {"type": "array", "items": {"type": "integer"}},
            },
            "kind": {
                "type": "string",
                "enum": _BRUSH_KINDS,
                "description": "Brush operation kind.",
            },
            "center": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Brush center world position [x, y, z].",
            },
            "direction": {
                "type": "array",
                "items": {"type": "number"},
                "description": (
                    "Stroke direction [x, y, z] (required for 'grab'; "
                    "used for 'crease'; ignored for smooth/inflate/pinch)."
                ),
            },
            "radius": {
                "type": "number",
                "description": "Influence radius in world units (> 0).",
            },
            "strength": {
                "type": "number",
                "description": "Scalar in [0, 1] controlling displacement magnitude.",
            },
            "falloff": {
                "type": "string",
                "enum": ["smooth", "linear", "constant"],
                "description": "Falloff shape (default 'smooth').",
            },
        },
        "required": ["positions", "triangles", "kind", "center", "radius"],
    },
)


@register(_sculpt_apply_brush_spec, write=False)
async def run_sculpt_apply_brush(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        positions = np.array(a["positions"], dtype=np.float64)
        triangles = np.array(a["triangles"], dtype=np.int32)
    except Exception as exc:
        return err_payload(f"invalid mesh data: {exc}", "BAD_ARGS")

    kind_str = str(a.get("kind", "")).lower()
    try:
        brush_kind = BrushKind(kind_str)
    except ValueError:
        return err_payload(
            f"Invalid kind '{kind_str}'. Valid: {_BRUSH_KINDS}", "BAD_ARGS"
        )

    center_raw = a.get("center")
    if center_raw is None:
        return err_payload("center is required", "BAD_ARGS")

    radius = float(a.get("radius", 1.0))
    if radius <= 0:
        return err_payload("radius must be > 0", "BAD_ARGS")

    strength = float(a.get("strength", 0.5))
    falloff = str(a.get("falloff", "smooth"))

    direction_raw = a.get("direction")
    direction = np.array(direction_raw, dtype=np.float64) if direction_raw is not None else None

    try:
        stroke = BrushStroke(
            kind=brush_kind,
            center=np.array(center_raw, dtype=np.float64),
            direction=direction,
            radius=radius,
            strength=strength,
            falloff=falloff,
        )
        mesh = SculptMesh(positions=positions.copy(), triangles=triangles)
        delta = apply_brush(mesh, stroke)
    except Exception as exc:
        return err_payload(f"brush application error: {exc}", "EVAL_ERROR")

    return ok_payload({
        "positions": mesh.positions.tolist(),
        "delta_indices": delta.vertex_indices.tolist(),
        "delta_vectors": delta.deltas.tolist(),
        "n_affected": len(delta.vertex_indices),
        "kind": kind_str,
        "center": list(center_raw),
        "radius": radius,
        "strength": strength,
    })


__all__ = ["run_sculpt_apply_brush"]
