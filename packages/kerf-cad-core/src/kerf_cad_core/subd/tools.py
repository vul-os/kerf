"""
kerf_cad_core.subd.tools — Wave 8 LLM tool wrappers for SubD modules.

Wave 8 modules covered
----------------------
  subd_limit_tangent   — kerf_cad_core.subd.limit_tangent
  subd_fractional_crease — kerf_cad_core.subd.fractional_crease
  subd_multires_eval   — kerf_cad_core.subd.multires

Tools registered
----------------
  subd_limit_tangent      — Stam 1998 exact limit position + tangents at a CC extraordinary vertex
  subd_fractional_crease  — Apply N levels of CC subdivision with fractional (semi-sharp) creases
  subd_multires_eval      — Evaluate a multires displacement patch at (u,v)

References
----------
Stam, J. (1998). "Exact Evaluation of Catmull-Clark Subdivision Surfaces at
    Arbitrary Parameter Values." SIGGRAPH '98, pp. 395-404.
DeRose, Kass & Truong (1998). "Subdivision Surfaces in Character Animation."
    SIGGRAPH '98, §4 — Semi-sharp creases.
Krishnamurthy & Levoy (1996). "Fitting Smooth Surfaces to Dense Polygon Meshes."
    SIGGRAPH '96, §3. (multires displacement encoding/evaluation).
"""
from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.subd.limit_tangent import (
    ExtraordinaryPatch,
    evaluate_at_extraordinary,
    evaluate_limit,
    g1_continuous_normals,
)
from kerf_cad_core.subd.fractional_crease import (
    CreaseEdge,
    CreaseSubdMesh,
    CreaseVertex,
    evaluate_limit_with_creases,
    subdivide_with_creases,
)
from kerf_cad_core.subd.multires import (
    DisplacementLevel,
    MultiresPatch,
    evaluate_multires,
)

import numpy as np


# ---------------------------------------------------------------------------
# Tool: subd_limit_tangent
# ---------------------------------------------------------------------------

_limit_tangent_spec = ToolSpec(
    name="subd_limit_tangent",
    description=(
        "Stam 1998 exact evaluation of Catmull-Clark limit position, tangents, and\n"
        "surface normal at an extraordinary vertex or arbitrary (u,v) parameter.\n"
        "\n"
        "Pass the 2N+1 control-point ring around the extraordinary vertex\n"
        "(valence N). Index 0 = central vertex; indices 1..N = N edge-adjacent\n"
        "vertices; indices N+1..2N = N face-adjacent vertices (all CCW).\n"
        "\n"
        "Returns:\n"
        "  position   — limit surface position [x, y, z]\n"
        "  tangent_u  — ∂S/∂u at the limit\n"
        "  tangent_v  — ∂S/∂v at the limit\n"
        "  normal     — unit normal T_u × T_v / |...|  ([0,0,0] if degenerate)\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "valence": {
                "type": "integer",
                "description": "Topological valence N of the central vertex (>= 3).",
            },
            "ring_positions": {
                "type": "array",
                "description": (
                    "2N+1 control-point positions in CCW 1-ring order: "
                    "[central_V, P_0..P_{N-1}, Q_0..Q_{N-1}]. "
                    "Each point is [x, y, z]."
                ),
                "items": {"type": "array", "items": {"type": "number"}},
            },
            "u": {
                "type": "number",
                "description": "Parameter u ∈ [0,1]. 0 = at the EV. Default 0.",
            },
            "v": {
                "type": "number",
                "description": "Parameter v ∈ [0,1]. 0 = at the EV. Default 0.",
            },
        },
        "required": ["valence", "ring_positions"],
    },
)


@register(_limit_tangent_spec, write=False)
async def run_subd_limit_tangent(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    valence = a.get("valence")
    ring_raw = a.get("ring_positions")
    if valence is None:
        return err_payload("valence is required", "BAD_ARGS")
    if ring_raw is None:
        return err_payload("ring_positions is required", "BAD_ARGS")

    try:
        valence = int(valence)
        ring = [tuple(float(x) for x in pt) for pt in ring_raw]
        patch = ExtraordinaryPatch(valence=valence, ring_positions=ring)
    except Exception as exc:
        return err_payload(f"invalid patch geometry: {exc}", "BAD_ARGS")

    u = float(a.get("u", 0.0))
    v = float(a.get("v", 0.0))

    try:
        result = evaluate_limit(patch, u, v)
    except Exception as exc:
        return err_payload(f"evaluation error: {exc}", "EVAL_ERROR")

    return ok_payload({
        "position": list(result.position),
        "tangent_u": list(result.tangent_u),
        "tangent_v": list(result.tangent_v),
        "normal": list(result.normal),
        "u": u,
        "v": v,
        "valence": valence,
    })


# ---------------------------------------------------------------------------
# Tool: subd_fractional_crease
# ---------------------------------------------------------------------------

_fractional_crease_spec = ToolSpec(
    name="subd_fractional_crease",
    description=(
        "Apply N levels of Catmull-Clark subdivision honouring fractional (semi-sharp)\n"
        "crease sharpness values.\n"
        "\n"
        "Crease sharpness decay rule (DeRose, Kass & Truong 1998 §4):\n"
        "  s′ = max(0, s − 1) per level\n"
        "  0    → smooth (no crease),  ∞ → infinitely sharp (hard crease).\n"
        "  0 < s < 1 → fractional blend: E = (1−s)·smooth_mask + s·sharp_mask.\n"
        "\n"
        "Returns the subdivided mesh: positions, faces, remaining crease edges.\n"
        "Optionally also computes the limit position of a tagged vertex (vertex_index)\n"
        "using the DeRose §4.2 crease limit formula.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "positions": {
                "type": "array",
                "description": "Control-mesh vertex positions [[x,y,z], ...].",
                "items": {"type": "array", "items": {"type": "number"}},
            },
            "faces": {
                "type": "array",
                "description": "Quad face index lists [[v0,v1,v2,v3], ...].",
                "items": {"type": "array", "items": {"type": "integer"}},
            },
            "crease_edges": {
                "type": "array",
                "description": (
                    "List of {v0, v1, sharpness} objects. "
                    "sharpness=0 → smooth; sharpness=1 → sharp for 1 level; "
                    "use 1e18 for ∞."
                ),
                "items": {"type": "object"},
            },
            "crease_vertices": {
                "type": "array",
                "description": "List of {vertex_index, sharpness} corner overrides.",
                "items": {"type": "object"},
            },
            "levels": {
                "type": "integer",
                "description": "Number of subdivision levels (default 1).",
            },
            "eval_limit_vertex": {
                "type": "integer",
                "description": "If set, also compute limit position at this vertex index.",
            },
        },
        "required": ["positions", "faces"],
    },
)


@register(_fractional_crease_spec, write=False)
async def run_subd_fractional_crease(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        positions = [tuple(float(x) for x in p) for p in a["positions"]]
        faces = [list(int(i) for i in f) for f in a["faces"]]
        crease_edges = []
        for ce in a.get("crease_edges", []):
            crease_edges.append(CreaseEdge(
                v0=int(ce["v0"]), v1=int(ce["v1"]),
                sharpness=float(ce.get("sharpness", 0.0)),
            ))
        crease_vertices = []
        for cv in a.get("crease_vertices", []):
            crease_vertices.append(CreaseVertex(
                vertex_index=int(cv["vertex_index"]),
                sharpness=float(cv.get("sharpness", 0.0)),
            ))
        levels = int(a.get("levels", 1))
    except Exception as exc:
        return err_payload(f"invalid mesh data: {exc}", "BAD_ARGS")

    mesh = CreaseSubdMesh(
        positions=positions,
        faces=faces,
        crease_edges=crease_edges,
        crease_vertices=crease_vertices,
    )

    try:
        result_mesh = subdivide_with_creases(mesh, levels=levels)
    except Exception as exc:
        return err_payload(f"subdivision error: {exc}", "EVAL_ERROR")

    payload: dict = {
        "positions": [list(p) for p in result_mesh.positions],
        "faces": result_mesh.faces,
        "crease_edges": [
            {"v0": ce.v0, "v1": ce.v1, "sharpness": ce.sharpness}
            for ce in result_mesh.crease_edges
        ],
        "vertex_count": len(result_mesh.positions),
        "face_count": len(result_mesh.faces),
        "levels_applied": levels,
    }

    eval_vi = a.get("eval_limit_vertex")
    if eval_vi is not None:
        try:
            lim = evaluate_limit_with_creases(result_mesh, int(eval_vi))
            payload["limit_position"] = list(lim)
            payload["eval_limit_vertex"] = int(eval_vi)
        except Exception as exc:
            payload["limit_position_error"] = str(exc)

    return ok_payload(payload)


# ---------------------------------------------------------------------------
# Tool: subd_multires_eval
# ---------------------------------------------------------------------------

_multires_eval_spec = ToolSpec(
    name="subd_multires_eval",
    description=(
        "Evaluate a multires displacement patch at (u,v) returning the displaced\n"
        "limit position, surface normal, base position, and total scalar displacement.\n"
        "\n"
        "Theory (Krishnamurthy & Levoy 1996 §3):\n"
        "  P(u,v) = S(u,v) + D(u,v) · n̂(u,v)\n"
        "where S(u,v) = bilinear interpolation of four base corners,\n"
        "n̂(u,v) = bilinear normal, and D(u,v) = sum of bilinear displacement grids.\n"
        "\n"
        "Each displacement level l has grid resolution 2^l+1 per side.\n"
        "Level 0 → 2×2, level 1 → 3×3, level 2 → 5×5.\n"
        "\n"
        "Returns:\n"
        "  position      — displaced 3D position\n"
        "  normal        — unit surface normal at (u,v)\n"
        "  base_position — un-displaced bilinear position\n"
        "  displacement  — total scalar offset\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "base_corners": {
                "type": "array",
                "description": (
                    "Four 3D positions [[x,y,z], ...] at corners "
                    "(u=0,v=0), (u=1,v=0), (u=0,v=1), (u=1,v=1)."
                ),
                "items": {"type": "array", "items": {"type": "number"}},
            },
            "base_normals": {
                "type": "array",
                "description": (
                    "Four unit normals at the base corners, same order as base_corners."
                ),
                "items": {"type": "array", "items": {"type": "number"}},
            },
            "displacements": {
                "type": "array",
                "description": (
                    "List of displacement levels. Each entry: "
                    "{level: int, scalars: [[float, ...], ...]}. "
                    "scalars shape must be (2^level+1) × (2^level+1). "
                    "Levels must be 0, 1, 2, ... in order."
                ),
                "items": {"type": "object"},
            },
            "u": {"type": "number", "description": "Parameter u ∈ [0,1]."},
            "v": {"type": "number", "description": "Parameter v ∈ [0,1]."},
            "max_level": {
                "type": "integer",
                "description": (
                    "Maximum displacement level to include (0-indexed). "
                    "Default: all levels."
                ),
            },
        },
        "required": ["base_corners", "base_normals", "displacements", "u", "v"],
    },
)


@register(_multires_eval_spec, write=False)
async def run_subd_multires_eval(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        base_corners = [tuple(float(x) for x in p) for p in a["base_corners"]]
        base_normals = [tuple(float(x) for x in n) for n in a["base_normals"]]
        u = float(a["u"])
        v = float(a["v"])

        disp_levels = []
        for dlev in a["displacements"]:
            lev = int(dlev["level"])
            scalars_raw = dlev["scalars"]
            scalars = np.array(scalars_raw, dtype=np.float32)
            expected_res = (1 << lev) + 1
            disp_levels.append(DisplacementLevel(
                level=lev,
                face_id=0,
                grid_resolution=expected_res,
                scalars=scalars,
            ))

        patch = MultiresPatch(
            base_face_id=0,
            base_corners=base_corners,
            base_normals=base_normals,
            displacements=disp_levels,
        )

        max_level = a.get("max_level", len(disp_levels) - 1)
    except Exception as exc:
        return err_payload(f"invalid patch data: {exc}", "BAD_ARGS")

    try:
        result = evaluate_multires(patch, u, v, level=int(max_level))
    except Exception as exc:
        return err_payload(f"evaluation error: {exc}", "EVAL_ERROR")

    return ok_payload({
        "position": list(result.position),
        "normal": list(result.normal),
        "base_position": list(result.base_position),
        "displacement": result.displacement,
        "u": u,
        "v": v,
        "levels_used": int(max_level) + 1,
    })


__all__ = [
    "run_subd_limit_tangent",
    "run_subd_fractional_crease",
    "run_subd_multires_eval",
]
