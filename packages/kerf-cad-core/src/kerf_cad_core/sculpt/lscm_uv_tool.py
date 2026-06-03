"""lscm_uv_tool.py — LLM tool registration for LSCM UV unwrap.

PLUGIN REGISTRATION
-------------------
Add the following line to `packages/kerf-cad-core/src/kerf_cad_core/plugin.py`
in the _TOOL_MODULES list (do NOT add it there yourself — the parent agent does
this after reviewing this file):

    "kerf_cad_core.sculpt.lscm_uv_tool",

Place it alongside other sculpt/mesh tools, e.g. after:
    "kerf_cad_core.geom.subd_decimate_to_cage_tool",

TOOL SHAPE
----------
The tool follows the standard kerf pattern:
    TOOLS = [("lscm_uv_unwrap", spec_dict, handler_fn)]

Inputs:  body_id (str), seam_edge_ids (list[list[int]])
Outputs: uv_coords (list[list[float]]), stretch_metric (float),
         boundary_length_2d (float)

BACKEND
-------
Delegates to :func:`kerf_cad_core.geom.uv_unwrap.lscm_unwrap` which implements
Lévy et al. 2002 "Least Squares Conformal Maps for Automatic Texture Atlas
Generation" (§3 complex Cauchy-Riemann linear system, 2 boundary pins).

Because the LLM tool layer operates on body IDs (not raw mesh dicts), this
module provides both:
  1. A standalone mesh-level function ``lscm_uv_unwrap_mesh`` for direct use in
     tests and other Python callers.
  2. An LLM tool handler ``run_lscm_uv_unwrap`` registered via @register.

References
----------
Lévy, B., Petitjean, S., Ray, N. & Maillot, J. (2002) "Least Squares Conformal
Maps for Automatic Texture Atlas Generation", SIGGRAPH 2002, pp. 362-371.
"""
from __future__ import annotations

import json
import math
from typing import Any

import numpy as np

from kerf_cad_core._compat import ToolSpec, err_payload, ok_payload, register
from kerf_cad_core.geom.uv_unwrap import lscm_unwrap

try:
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
except ImportError:
    from kerf_cad_core._compat import ProjectCtx  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Stretch metric helpers
# ---------------------------------------------------------------------------


def _conformal_stretch_metric(
    verts: list[list[float]],
    faces: list[list[int]],
    uv: list[list[float]],
) -> float:
    """Compute the mean conformal stretch metric over all triangles.

    For each triangle we compute the ratio of 3-D edge lengths to 2-D UV edge
    lengths (the "stretch" in Sander et al. 2001 sense).  A perfectly conformal
    flat map has stretch ≈ 1.0 (within scale).  We return the area-weighted mean.

    Parameters
    ----------
    verts : list of [x, y, z]
    faces : list of [i0, i1, i2]
    uv    : list of [u, v] (one per vertex)

    Returns
    -------
    float
        Normalised stretch metric.  Returns 1.0 for degenerate inputs.
    """
    if not faces:
        return 1.0

    V = np.asarray(verts, dtype=float)
    UV = np.asarray(uv, dtype=float)
    F = np.asarray(faces, dtype=int)

    total_weight = 0.0
    total_stretch = 0.0

    for f in F:
        i0, i1, i2 = int(f[0]), int(f[1]), int(f[2])
        # 3-D edges
        e3_01 = V[i1] - V[i0]
        e3_02 = V[i2] - V[i0]
        area3 = 0.5 * np.linalg.norm(np.cross(e3_01, e3_02))
        if area3 < 1e-14:
            continue

        # 2-D edges
        e2_01 = UV[i1] - UV[i0]
        e2_02 = UV[i2] - UV[i0]
        area2 = 0.5 * abs(e2_01[0] * e2_02[1] - e2_01[1] * e2_02[0])
        if area2 < 1e-14:
            continue

        # Stretch = (3-D area) / (2-D area) normalised so that flat identity → 1.
        # We normalise by the ratio of total 3-D to 2-D area globally.
        total_weight += area3
        total_stretch += area3 * (area3 / area2)

    if total_weight < 1e-14:
        return 1.0

    raw_ratio = total_stretch / total_weight  # units: area3/area2 per tri

    # Normalise so that a flat plane with UV == XY gives 1.0
    total_3d = sum(
        0.5 * np.linalg.norm(
            np.cross(V[int(f[1])] - V[int(f[0])], V[int(f[2])] - V[int(f[0])])
        )
        for f in F
    )
    total_2d = sum(
        abs(
            (UV[int(f[1])][0] - UV[int(f[0])][0]) * (UV[int(f[2])][1] - UV[int(f[0])][1])
            - (UV[int(f[2])][0] - UV[int(f[0])][0]) * (UV[int(f[1])][1] - UV[int(f[0])][1])
        ) * 0.5
        for f in F
    )
    if total_2d < 1e-14:
        return 1.0

    normaliser = total_3d / total_2d
    return float(raw_ratio / normaliser)


def _boundary_length_2d(
    faces: list[list[int]],
    uv: list[list[float]],
) -> float:
    """Return the total 2-D perimeter of the UV boundary loop."""
    # Find boundary edges (appear exactly once)
    edge_count: dict[tuple[int, int], int] = {}
    for f in faces:
        for k in range(3):
            a, b = int(f[k]), int(f[(k + 1) % 3])
            key = (min(a, b), max(a, b))
            edge_count[key] = edge_count.get(key, 0) + 1

    UV = np.asarray(uv, dtype=float)
    length = 0.0
    for (a, b), count in edge_count.items():
        if count == 1:
            length += float(np.linalg.norm(UV[b] - UV[a]))
    return length


# ---------------------------------------------------------------------------
# Mesh-level public API (used by tests + downstream callers)
# ---------------------------------------------------------------------------


def lscm_uv_unwrap_mesh(
    mesh: dict,
    seam_edge_ids: list[list[int]] | None = None,
) -> dict:
    """Run LSCM UV unwrap on a raw mesh dict and return the full result.

    Parameters
    ----------
    mesh : dict
        ``"vertices"`` (list[list[float]]) + ``"faces"`` (list[list[int]],
        triangles only).
    seam_edge_ids : list of [vi0, vi1] pairs, optional
        Seam edges that define cuts in the mesh surface.  Currently used to
        select boundary pins: the first two distinct vertices encountered along
        the seam edges are used as fixed pins at UV (0, 0) and (1, 0).
        If omitted or empty, the two farthest boundary vertices are chosen
        automatically (same as ``lscm_unwrap`` default).

    Returns
    -------
    dict with keys:
        ``uv_coords``        — list[list[float]], one [u, v] per vertex
        ``stretch_metric``   — float, conformal stretch ≈ 1.0 for flat input
        ``boundary_length_2d`` — float, total 2-D UV boundary perimeter

    Raises
    ------
    ValueError
        If the mesh has no vertices or faces, or if seam_edge_ids are provided
        but contain no valid vertex indices.
    """
    verts = mesh.get("vertices", [])
    faces = mesh.get("faces", [])

    if not verts:
        raise ValueError("mesh has no vertices")
    if not faces:
        raise ValueError("mesh has no faces")

    n_verts = len(verts)

    # Build fixed_pins from seam edges if provided
    fixed_pins: list[tuple[int, float, float]] | None = None
    if seam_edge_ids:
        seam_verts: list[int] = []
        for edge in seam_edge_ids:
            if len(edge) >= 2:
                for vi in edge[:2]:
                    v = int(vi)
                    if 0 <= v < n_verts and v not in seam_verts:
                        seam_verts.append(v)
            if len(seam_verts) >= 2:
                break
        if len(seam_verts) < 2:
            raise ValueError(
                f"seam_edge_ids produced fewer than 2 valid vertex indices "
                f"(got {seam_verts}); need at least 2 to pin boundary"
            )
        fixed_pins = [(seam_verts[0], 0.0, 0.0), (seam_verts[1], 1.0, 0.0)]

    result = lscm_unwrap(mesh, fixed_pins=fixed_pins)
    uv_coords: list[list[float]] = result["uv"]

    stretch = _conformal_stretch_metric(verts, faces, uv_coords)
    bdry_len = _boundary_length_2d(faces, uv_coords)

    return {
        "uv_coords": uv_coords,
        "stretch_metric": float(stretch),
        "boundary_length_2d": float(bdry_len),
    }


# ---------------------------------------------------------------------------
# LLM tool
# ---------------------------------------------------------------------------

_lscm_spec = ToolSpec(
    name="lscm_uv_unwrap",
    description=(
        "Compute a Least-Squares Conformal Map (LSCM) UV unwrap for a body "
        "mesh.  Minimises angle distortion (Lévy et al. 2002 §3).\n\n"
        "Inputs:\n"
        "  body_id         — identifier for the body to unwrap (resolved to\n"
        "                    mesh by the session context; pass raw mesh via\n"
        "                    'mesh' override for testing).\n"
        "  seam_edge_ids   — list of [vi0, vi1] edge pairs defining seam cuts\n"
        "                    used to select boundary pins.\n\n"
        "Outputs:\n"
        "  uv_coords           — list[list[float]] one [u,v] per vertex\n"
        "  stretch_metric      — conformal stretch (≈1.0 for flat/isometric)\n"
        "  boundary_length_2d  — total perimeter of the UV boundary (2-D)\n\n"
        "Never raises; invalid inputs return {error: ..., code: BAD_ARGS}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "body_id": {
                "type": "string",
                "description": "Body identifier (project context resolves to mesh).",
            },
            "seam_edge_ids": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": "List of [vi0, vi1] seam edge vertex-index pairs.",
                "default": [],
            },
            "mesh": {
                "type": "object",
                "description": (
                    "Raw mesh override for testing: "
                    "{vertices: [[x,y,z],...], faces: [[i,j,k],...]}. "
                    "If supplied, body_id is ignored."
                ),
            },
        },
        "required": ["body_id"],
    },
)


@register(_lscm_spec, write=False)
async def run_lscm_uv_unwrap(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    seam_edge_ids: list[list[int]] = a.get("seam_edge_ids", [])

    # Allow a raw mesh override (for testing / standalone use)
    raw_mesh = a.get("mesh")
    if raw_mesh is not None:
        if not isinstance(raw_mesh, dict):
            return err_payload("'mesh' must be an object", "BAD_ARGS")
        try:
            out = lscm_uv_unwrap_mesh(raw_mesh, seam_edge_ids or None)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"LSCM failed: {exc}", "COMPUTE_ERROR")
        return ok_payload(out)

    body_id = a.get("body_id")
    if not body_id:
        return err_payload("body_id is required", "BAD_ARGS")

    # Production path: resolve body from context.
    # When context has a mesh resolver, use it.  Otherwise return a stub.
    try:
        resolver = getattr(ctx, "resolve_body_mesh", None)
        if resolver is not None:
            mesh = await resolver(body_id)
        else:
            return err_payload(
                f"body_id '{body_id}' cannot be resolved: no mesh resolver on context. "
                "Pass 'mesh' key directly for standalone use.",
                "NOT_IMPLEMENTED",
            )
    except Exception as exc:
        return err_payload(f"could not resolve body '{body_id}': {exc}", "BAD_ARGS")

    try:
        out = lscm_uv_unwrap_mesh(mesh, seam_edge_ids or None)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"LSCM failed: {exc}", "COMPUTE_ERROR")

    return ok_payload(out)


# ---------------------------------------------------------------------------
# TOOLS export (kerf plugin introspection pattern)
# ---------------------------------------------------------------------------

TOOLS: list[tuple[str, dict, Any]] = [
    (
        "lscm_uv_unwrap",
        {
            "name": "lscm_uv_unwrap",
            "description": _lscm_spec.description,
            "input_schema": _lscm_spec.input_schema,
        },
        run_lscm_uv_unwrap,
    )
]

__all__ = [
    "lscm_uv_unwrap_mesh",
    "run_lscm_uv_unwrap",
    "TOOLS",
    "_conformal_stretch_metric",
    "_boundary_length_2d",
]
