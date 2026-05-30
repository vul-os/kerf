"""subd_tools.py — GK-P45 + GK-P: Wire SubD/mesh authoring ops as LLM ToolSpecs.

Wires the following already-implemented functions from
``kerf_cad_core.geom.subd_authoring`` into the tool/feature/LLM surface:

- ``subd_poke``                   (GK-P20) — poke a face by centroid fan
- ``subd_extrude_along``          (GK-P21) — extrude a face along a curve path
- ``sculpt_brush``                (GK-P27) — sculpt-brush stroke (grab/smooth/inflate)
- ``MultiresStack``               (GK-P26) — multi-resolution displacement stack
  (evaluate + serialise as feature nodes)
- ``subd_evaluate_limit_curvature`` (GK-P)  — Stam-exact limit-surface curvature
  (Gaussian K, mean H, principal κ₁/κ₂) at arbitrary (u,v), including
  extraordinary vertices.

These ops append a node to a ``.feature`` file. The OCCT worker has no
special dispatch for SubD nodes — evaluation is pure-Python.
"""
from __future__ import annotations

import json
import uuid
from typing import Optional

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx

from kerf_cad_core.surfacing import (
    append_feature_node,
    next_node_id,
    read_feature_content,
)


# ── feature_subd_poke ─────────────────────────────────────────────────────────
#
# GK-P20: poke a SubD cage face — inserts a centroid vertex and fans n
# triangles for an n-gon face.  Appends a ``subd_poke`` node.

feature_subd_poke_spec = ToolSpec(
    name="feature_subd_poke",
    description=(
        "Append a `subd_poke` node to a `.feature` file. "
        "Pokes a SubD cage face: inserts a centroid vertex and fans the "
        "n-gon into n triangles (one per edge).  For a quad face this "
        "produces 4 triangles; for a triangle 3 new triangles.  "
        "The op is applied by the pure-Python SubD evaluator; no OCCT required. "
        "Use to add local detail or to prepare a face for sculpt brushing."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of an existing SubD cage node in the feature tree.",
            },
            "face_id": {
                "type": "integer",
                "description": "0-based index of the face to poke.",
                "minimum": 0,
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "target_id", "face_id"],
    },
)


@register(feature_subd_poke_spec, write=True)
async def run_feature_subd_poke(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    face_id = a.get("face_id")
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if face_id is None or not isinstance(face_id, int) or face_id < 0:
        return err_payload("face_id must be a non-negative integer", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "subd_poke")

    node = {
        "id": node_id,
        "op": "subd_poke",
        "target_id": target_id,
        "face_id": face_id,
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({"file_id": file_id, "id": nid or node_id, "op": "subd_poke"})


# ── feature_subd_extrude_along ────────────────────────────────────────────────
#
# GK-P21: extrude a SubD cage face along a polyline curve path.

feature_subd_extrude_along_spec = ToolSpec(
    name="feature_subd_extrude_along",
    description=(
        "Append a `subd_extrude_along` node to a `.feature` file. "
        "Sweeps a SubD cage face along a polyline spine defined by "
        "`curve_pts` ([x,y,z] list, ≥2 points).  The first point is the "
        "current face location; subsequent points define the extrusion spine. "
        "Side walls are quad faces connecting consecutive profile copies. "
        "No OCCT required — pure-Python SubD evaluator."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of an existing SubD cage node.",
            },
            "face_id": {
                "type": "integer",
                "description": "0-based index of the face to extrude.",
                "minimum": 0,
            },
            "curve_pts": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 2,
                "description": (
                    "Polyline spine as [[x,y,z], ...] (≥2 points). "
                    "The first point should coincide with the face centroid."
                ),
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id", "face_id", "curve_pts"],
    },
)


@register(feature_subd_extrude_along_spec, write=True)
async def run_feature_subd_extrude_along(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    face_id = a.get("face_id")
    curve_pts = a.get("curve_pts")
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if face_id is None or not isinstance(face_id, int) or face_id < 0:
        return err_payload("face_id must be a non-negative integer", "BAD_ARGS")
    if not isinstance(curve_pts, list) or len(curve_pts) < 2:
        return err_payload("curve_pts must be a list of ≥2 [x,y,z] points", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "subd_extrude_along")

    node = {
        "id": node_id,
        "op": "subd_extrude_along",
        "target_id": target_id,
        "face_id": face_id,
        "curve_pts": [[float(c) for c in pt] for pt in curve_pts],
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "subd_extrude_along",
        "steps": len(curve_pts) - 1,
    })


# ── feature_sculpt_brush ──────────────────────────────────────────────────────
#
# GK-P27: apply a sculpt-brush stroke to a SubD cage.

feature_sculpt_brush_spec = ToolSpec(
    name="feature_sculpt_brush",
    description=(
        "Append a `sculpt_brush` node to a `.feature` file. "
        "Applies a sculpt-brush stroke to a SubD cage. "
        "Moves, smooths, or inflates cage vertices within `radius` of "
        "`center`, weighted by a smooth-step falloff function. "
        "Modes: `grab` — translate by `direction`; `smooth` — laplacian "
        "smooth toward ring-neighbour average; `inflate` — push along "
        "estimated vertex normal. "
        "No OCCT required — pure-Python SubD evaluator."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the SubD cage node to sculpt.",
            },
            "center": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "3D position of the brush centre [x, y, z].",
            },
            "radius": {
                "type": "number",
                "description": "Brush influence radius (> 0).",
                "exclusiveMinimum": 0,
            },
            "falloff": {
                "type": "number",
                "description": (
                    "Exponent of the smooth-step falloff (default 2.0). "
                    "1.0 = linear, 2.0 = squared, higher = harder edge. "
                    "Clamped to [0.5, 8.0]."
                ),
                "default": 2.0,
            },
            "strength": {
                "type": "number",
                "description": "Blend weight in [0, 1]. 0 = no effect, 1 = full. Default 0.5.",
                "default": 0.5,
            },
            "mode": {
                "type": "string",
                "enum": ["grab", "smooth", "inflate"],
                "description": "Brush mode. Default 'grab'.",
            },
            "direction": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": (
                    "3D displacement vector for 'grab' mode [dx, dy, dz]. "
                    "Ignored by smooth/inflate."
                ),
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id", "center", "radius", "mode"],
    },
)


@register(feature_sculpt_brush_spec, write=True)
async def run_feature_sculpt_brush(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    center = a.get("center")
    radius = a.get("radius")
    falloff = a.get("falloff", 2.0)
    strength = a.get("strength", 0.5)
    mode = a.get("mode", "grab")
    direction = a.get("direction")
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if not isinstance(center, list) or len(center) < 3:
        return err_payload("center must be [x, y, z]", "BAD_ARGS")
    if radius is None or not isinstance(radius, (int, float)) or float(radius) <= 0:
        return err_payload("radius must be a positive number", "BAD_ARGS")
    if mode not in ("grab", "smooth", "inflate"):
        return err_payload("mode must be 'grab', 'smooth', or 'inflate'", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "sculpt_brush")

    node: dict = {
        "id": node_id,
        "op": "sculpt_brush",
        "target_id": target_id,
        "center": [float(center[0]), float(center[1]), float(center[2])],
        "radius": float(radius),
        "falloff": float(falloff),
        "strength": float(strength),
        "mode": mode,
    }
    if direction is not None and isinstance(direction, list) and len(direction) >= 3:
        node["direction"] = [float(direction[0]), float(direction[1]), float(direction[2])]

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "sculpt_brush",
        "mode": mode,
    })


# ── feature_multires_evaluate ─────────────────────────────────────────────────
#
# GK-P26: evaluate / serialise a MultiresStack at a given level.

feature_multires_evaluate_spec = ToolSpec(
    name="feature_multires_evaluate",
    description=(
        "Append a `multires_evaluate` node to a `.feature` file. "
        "Evaluates a `MultiresStack` (multi-resolution displacement stack) at "
        "a specified subdivision level and serialises the resulting mesh into "
        "the feature tree. "
        "The node stores the base cage (`cage_data` dict) and the displacement "
        "map (`displacements` dict) so the evaluator can reconstruct the "
        "`MultiresStack`, call `.evaluate(level)`, and output the displaced "
        "`SubDMesh`. "
        "Use `max_levels` (1–6) to configure how many subdivision levels the "
        "stack supports. "
        "No OCCT required — pure-Python SubD evaluator."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the target .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the base SubD cage node whose mesh is stacked.",
            },
            "level": {
                "type": "integer",
                "description": "Subdivision level to evaluate (0 = base cage, max 6).",
                "minimum": 0,
                "maximum": 6,
                "default": 2,
            },
            "max_levels": {
                "type": "integer",
                "description": "Maximum levels in the stack (1–6, default 2).",
                "minimum": 1,
                "maximum": 6,
                "default": 2,
            },
            "displacements": {
                "type": "object",
                "description": (
                    "Displacement map keyed by level string: "
                    "{\"2\": [[dx,dy,dz], ...], ...}. "
                    "Absent levels have zero displacement. "
                    "Omit or pass {} for a plain subdivision without displacements."
                ),
                "default": {},
            },
            "id": {"type": "string", "description": "Optional explicit node id."},
        },
        "required": ["file_id", "target_id"],
    },
)


@register(feature_multires_evaluate_spec, write=True)
async def run_feature_multires_evaluate(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    level = a.get("level", 2)
    max_levels = a.get("max_levels", 2)
    displacements = a.get("displacements") or {}
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if not isinstance(level, int) or not (0 <= level <= 6):
        return err_payload("level must be an integer 0–6", "BAD_ARGS")
    if not isinstance(max_levels, int) or not (1 <= max_levels <= 6):
        return err_payload("max_levels must be an integer 1–6", "BAD_ARGS")
    if not isinstance(displacements, dict):
        return err_payload("displacements must be an object", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "multires_evaluate")

    node = {
        "id": node_id,
        "op": "multires_evaluate",
        "target_id": target_id,
        "level": level,
        "max_levels": max_levels,
        "displacements": displacements,
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "multires_evaluate",
        "level": level,
        "max_levels": max_levels,
    })


# ── subd_evaluate_limit_curvature ─────────────────────────────────────────────
#
# GK-P: Stam-exact limit-surface curvature at arbitrary (u,v), including
# extraordinary vertices.  Returns Gaussian K, mean H, principal κ₁/κ₂.

subd_evaluate_limit_curvature_spec = ToolSpec(
    name="subd_evaluate_limit_curvature",
    description=(
        "Evaluate the Stam-exact Catmull-Clark limit-surface curvature at "
        "an arbitrary parametric point (u, v) on a SubD cage face. "
        "Returns Gaussian curvature K, mean curvature H, and principal "
        "curvatures κ₁ and κ₂. "
        "Works at extraordinary vertices (valence ≠ 4) — the curvature "
        "converges to a well-defined finite limit as (u,v) approaches the "
        "extraordinary corner. "
        "Based on the second fundamental form of the bicubic CC limit patch: "
        "L, M, N from the Stam eigenvector-corrected NURBS second derivatives. "
        "Use face_id=0..N-1 to select the cage face. "
        "u, v ∈ [0, 1]; (0,0) = first vertex corner. "
        "Optionally request a grid (n_samples × n_samples) of curvature values "
        "over the face by setting n_samples > 1 (returns summary statistics). "
        "No OCCT required — pure-Python SubD + NURBS evaluator."
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
                "minItems": 1,
                "description": (
                    "SubD cage vertices as [[x,y,z], ...]. "
                    "All faces must be quads (4 vertex indices each)."
                ),
            },
            "faces": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "minItems": 4,
                    "maxItems": 4,
                },
                "minItems": 1,
                "description": (
                    "Quad faces as [[i,j,k,l], ...] (0-based vertex indices)."
                ),
            },
            "face_id": {
                "type": "integer",
                "minimum": 0,
                "description": "0-based index of the face to evaluate.",
            },
            "u": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.5,
                "description": "Parametric u coordinate in [0, 1] (default 0.5 = face centre).",
            },
            "v": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "default": 0.5,
                "description": "Parametric v coordinate in [0, 1] (default 0.5 = face centre).",
            },
            "n_samples": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "default": 1,
                "description": (
                    "If > 1, evaluate curvature on an n×n grid over the face "
                    "and return summary statistics (min/max/mean K and H). "
                    "If 1 (default), return the single-point evaluation at (u,v)."
                ),
            },
        },
        "required": ["vertices", "faces", "face_id"],
    },
)


@register(subd_evaluate_limit_curvature_spec, write=False)
async def run_subd_evaluate_limit_curvature(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    vertices = a.get("vertices")
    faces    = a.get("faces")
    face_id  = a.get("face_id")
    u        = float(a.get("u", 0.5))
    v        = float(a.get("v", 0.5))
    n_samples = int(a.get("n_samples", 1))

    if not isinstance(vertices, list) or len(vertices) < 1:
        return err_payload("vertices must be a list of [x,y,z] triples", "BAD_ARGS")
    if not isinstance(faces, list) or len(faces) < 1:
        return err_payload("faces must be a list of quad [i,j,k,l] index lists", "BAD_ARGS")
    if face_id is None or not isinstance(face_id, int) or face_id < 0:
        return err_payload("face_id must be a non-negative integer", "BAD_ARGS")
    if face_id >= len(faces):
        return err_payload(
            f"face_id={face_id} out of range; mesh has {len(faces)} faces", "BAD_ARGS"
        )
    if not (0.0 <= u <= 1.0) or not (0.0 <= v <= 1.0):
        return err_payload("u and v must be in [0, 1]", "BAD_ARGS")
    if not (1 <= n_samples <= 50):
        return err_payload("n_samples must be in [1, 50]", "BAD_ARGS")

    # Validate face vertex counts
    for fi, f in enumerate(faces):
        if not isinstance(f, list) or len(f) != 4:
            return err_payload(
                f"face {fi} must be a quad (4 vertex indices), got len={len(f) if isinstance(f, list) else '?'}",
                "BAD_ARGS",
            )

    try:
        from kerf_cad_core.geom.subd import SubDMesh
        from kerf_cad_core.geom.subd_limit_curvature import (
            evaluate_limit_curvature,
            evaluate_curvature_grid,
        )

        mesh = SubDMesh(
            vertices=[[float(c) for c in vert] for vert in vertices],
            faces=[[int(idx) for idx in face] for face in faces],
        )

        if n_samples <= 1:
            cv = evaluate_limit_curvature(mesh, face_id, u, v)
            return ok_payload({
                "face_id": face_id,
                "u": u,
                "v": v,
                "gaussian_K": cv.gaussian_K,
                "mean_H": cv.mean_H,
                "principal_kappa_1": cv.principal_kappa_1,
                "principal_kappa_2": cv.principal_kappa_2,
                "curvature_type": (
                    "elliptic" if cv.gaussian_K > 1e-10
                    else "hyperbolic" if cv.gaussian_K < -1e-10
                    else "parabolic_or_flat"
                ),
            })
        else:
            import numpy as np
            grid = evaluate_curvature_grid(mesh, face_id, n_samples=n_samples)
            K_grid = grid[:, :, 0]
            H_grid = grid[:, :, 1]
            return ok_payload({
                "face_id": face_id,
                "n_samples": n_samples,
                "gaussian_K_min": float(np.min(K_grid)),
                "gaussian_K_max": float(np.max(K_grid)),
                "gaussian_K_mean": float(np.mean(K_grid)),
                "mean_H_min": float(np.min(H_grid)),
                "mean_H_max": float(np.max(H_grid)),
                "mean_H_mean": float(np.mean(H_grid)),
                "principal_kappa_1_max": float(np.max(grid[:, :, 2])),
                "principal_kappa_2_min": float(np.min(grid[:, :, 3])),
            })

    except Exception as exc:
        return err_payload(f"curvature evaluation failed: {exc}", "ERROR")
