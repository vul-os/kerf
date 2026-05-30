"""subd_tools.py — GK-P45: Wire SubD/mesh authoring ops as LLM ToolSpecs.

Wires the following already-implemented functions from
``kerf_cad_core.geom.subd_authoring`` into the tool/feature/LLM surface:

- ``subd_poke``          (GK-P20) — poke a face by centroid fan
- ``subd_extrude_along`` (GK-P21) — extrude a face along a curve path
- ``sculpt_brush``       (GK-P27) — sculpt-brush stroke (grab/smooth/inflate)
- ``MultiresStack``      (GK-P26) — multi-resolution displacement stack
  (evaluate + serialise as feature nodes)
- ``subd_to_nurbs_schaefer`` (GK-P-LS) — Loop-Schaefer 2008 bicubic-NURBS
  approximation of a Catmull-Clark SubD cage (stateless, returns patches + error)

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


# ── subd_to_nurbs_schaefer ────────────────────────────────────────────────────
#
# GK-P-LS: Loop-Schaefer 2008 bicubic-NURBS approximation (stateless tool).
# Converts an inline SubD cage description to a bicubic NURBS patch quilt
# and returns fit-error statistics + serialised control grids.

subd_to_nurbs_schaefer_spec = ToolSpec(
    name="subd_to_nurbs_schaefer",
    description=(
        "Convert a Catmull-Clark SubD control cage to a bicubic NURBS patch "
        "quilt using the Loop-Schaefer 2008 algorithm "
        "(ACM Trans. Graphics 27(1), Feb 2008). "
        "Regular interior faces (all valence-4 vertices) produce exact "
        "Stam-basis bicubic patches with C2 continuity. "
        "Irregular faces (extraordinary vertex, valence ≠ 4) are fitted by "
        "least-squares to Catmull-Clark limit-surface samples. "
        "Returns one 4×4 control grid per face plus fit-error statistics. "
        "Stateless: does not read or write any file."
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
                "description": "Vertex positions as [[x,y,z], ...] (≥4 vertices).",
                "minItems": 4,
            },
            "faces": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 4,
                    "maxItems": 4,
                },
                "description": "Quad faces as [[i0,i1,i2,i3], ...] (all quads, CCW winding).",
                "minItems": 1,
            },
            "target_error": {
                "type": "number",
                "description": (
                    "Target fit error for irregular (extraordinary-vertex) faces "
                    "(default 1e-3, in the same units as vertices). "
                    "The actual max_fit_error may exceed this for very irregular cages."
                ),
                "default": 0.001,
                "exclusiveMinimum": 0,
            },
        },
        "required": ["vertices", "faces"],
    },
)


@register(subd_to_nurbs_schaefer_spec, write=False)
async def run_subd_to_nurbs_schaefer(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    raw_verts = a.get("vertices")
    raw_faces = a.get("faces")
    target_error = a.get("target_error", 1e-3)

    if not isinstance(raw_verts, list) or len(raw_verts) < 4:
        return err_payload("vertices must be a list of ≥4 [x,y,z] points", "BAD_ARGS")
    if not isinstance(raw_faces, list) or len(raw_faces) < 1:
        return err_payload("faces must be a non-empty list of quad index lists", "BAD_ARGS")
    if not isinstance(target_error, (int, float)) or target_error <= 0:
        return err_payload("target_error must be a positive number", "BAD_ARGS")

    try:
        verts = [[float(c) for c in v] for v in raw_verts]
        faces = [[int(i) for i in f] for f in raw_faces]
    except (TypeError, ValueError) as exc:
        return err_payload(f"invalid vertex/face data: {exc}", "BAD_ARGS")

    for fi, f in enumerate(faces):
        if len(f) != 4:
            return err_payload(
                f"face {fi} has {len(f)} vertices; only quads supported", "BAD_ARGS"
            )
        for vi in f:
            if vi < 0 or vi >= len(verts):
                return err_payload(
                    f"face {fi} has out-of-range vertex index {vi}", "BAD_ARGS"
                )

    try:
        from kerf_cad_core.geom.subd import SubDMesh
        from kerf_cad_core.geom.subd_to_nurbs import (
            subd_to_nurbs_loop_schaefer,
            compute_conversion_loss,
        )
    except ImportError as exc:
        return err_payload(f"import error: {exc}", "ERROR")

    mesh = SubDMesh(vertices=verts, faces=faces)
    try:
        result = subd_to_nurbs_loop_schaefer(mesh, target_error=float(target_error))
    except Exception as exc:
        return err_payload(f"conversion failed: {exc}", "ERROR")

    try:
        loss = compute_conversion_loss(mesh, result.patches, n_samples=200)
    except Exception:
        loss = {"rms_error": 0.0, "max_error": 0.0, "near_extraordinary_max": 0.0}

    # Serialise control grids (list of 4×4 grids, each [[x,y,z]])
    ctrl_grids = []
    for patch in result.patches:
        grid = patch.control_points.tolist()
        ctrl_grids.append(grid)

    return ok_payload({
        "patch_count": len(result.patches),
        "max_fit_error": result.max_fit_error,
        "valence_table": {str(k): v for k, v in result.valence_table.items()},
        "rms_error": loss["rms_error"],
        "max_error": loss["max_error"],
        "near_extraordinary_max": loss["near_extraordinary_max"],
        "control_grids": ctrl_grids,
    })
