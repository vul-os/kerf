"""subd_tools.py — GK-P45: Wire SubD/mesh authoring ops as LLM ToolSpecs.

Wires the following already-implemented functions from
``kerf_cad_core.geom.subd_authoring`` into the tool/feature/LLM surface:

- ``subd_poke``          (GK-P20) — poke a face by centroid fan
- ``subd_extrude_along`` (GK-P21) — extrude a face along a curve path
- ``sculpt_brush``       (GK-P27) — sculpt-brush stroke (grab/smooth/inflate)
- ``MultiresStack``      (GK-P26) — multi-resolution displacement stack
  (evaluate + serialise as feature nodes)

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


# ── subd_detect_symmetry ──────────────────────────────────────────────────────
#
# GK-P: Detect mirror-symmetry planes in a SubD cage.

subd_detect_symmetry_spec = ToolSpec(
    name="subd_detect_symmetry",
    description=(
        "Detect mirror-symmetry planes in a SubD control cage. "
        "Tests axis-aligned candidate planes (XY, XZ, YZ plus bbox-centred "
        "variants) and returns each plane's symmetry score — the fraction of "
        "cage vertices that have a mirrored counterpart within `tol`. "
        "A score of 1.0 = perfect symmetry; 0.0 = no mirror relationship. "
        "Returns the dominant (highest-scoring) plane, all scored planes, and "
        "the dominant score. "
        "Use before enforce_symmetry or mirror_edit to discover which planes "
        "are already symmetric. "
        "Reference: Podolak et al. 2006 'Planar-Reflective Symmetry Transform'."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the .feature file containing the SubD cage.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the SubD cage node to analyse.",
            },
            "tol": {
                "type": "number",
                "description": (
                    "Vertex-matching tolerance for mirror detection. "
                    "Default 1e-4. Increase for noisy/scanned geometry."
                ),
                "default": 1e-4,
                "exclusiveMinimum": 0,
            },
        },
        "required": ["file_id", "target_id"],
    },
)


@register(subd_detect_symmetry_spec, write=False)
async def run_subd_detect_symmetry(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    tol = float(a.get("tol", 1e-4))

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if tol <= 0:
        return err_payload("tol must be > 0", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    # Locate the cage node in the feature tree and reconstruct the SubDCage.
    try:
        from kerf_cad_core.geom.subd_symmetry import detect_mirror_symmetry
        from kerf_cad_core.geom.subd_authoring import SubDCage
        from kerf_cad_core.surfacing import evaluate_feature_node  # type: ignore
    except ImportError as exc:
        return err_payload(f"import error: {exc}", "ERROR")

    try:
        cage = evaluate_feature_node(content, target_id)
        if not isinstance(cage, SubDCage):
            return err_payload(
                f"node '{target_id}' does not evaluate to a SubDCage", "BAD_ARGS"
            )
    except Exception as exc:
        return err_payload(f"failed to evaluate cage node: {exc}", "ERROR")

    result = detect_mirror_symmetry(cage, tol=tol)

    planes_out = []
    for plane in result.planes:
        planes_out.append({
            "label": plane.label,
            "normal": plane.normal,
            "offset": plane.offset,
            "score": result.scores.get(plane.label, 0.0),
        })

    dominant = None
    if result.dominant_plane:
        dominant = {
            "label": result.dominant_plane.label,
            "normal": result.dominant_plane.normal,
            "offset": result.dominant_plane.offset,
        }

    return ok_payload({
        "file_id": file_id,
        "target_id": target_id,
        "dominant_plane": dominant,
        "dominant_score": result.score,
        "planes": planes_out,
    })


# ── subd_enforce_symmetry ─────────────────────────────────────────────────────
#
# GK-P: Enforce mirror symmetry on a SubD cage by copying vertex positions
#       from the authoritative side to the opposite side.

subd_enforce_symmetry_spec = ToolSpec(
    name="subd_enforce_symmetry",
    description=(
        "Enforce mirror symmetry on a SubD cage across a specified plane. "
        "Copies vertex positions from the *keep* side to their mirror counterparts "
        "on the opposite side. Vertices on the plane are snapped to it. "
        "The plane is specified by `plane_normal` ([nx,ny,nz], will be "
        "normalised) and `plane_offset` (d in dot(n,p)=d). "
        "`side` is 'left' (keep positive half-space, dot(n,p)>=offset) or "
        "'right' (keep negative half-space). "
        "Appends a `subd_enforce_symmetry` node to the feature file. "
        "Topology is unchanged; only vertex positions are updated. "
        "Use after subd_detect_symmetry to get the plane parameters."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "file_id": {
                "type": "string",
                "description": "UUID of the .feature file.",
            },
            "target_id": {
                "type": "string",
                "description": "Id of the SubD cage node to enforce symmetry on.",
            },
            "plane_normal": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
                "description": "Plane normal vector [nx, ny, nz] (will be normalised).",
            },
            "plane_offset": {
                "type": "number",
                "description": (
                    "Plane offset d so that dot(normal, p) = d for points on the plane. "
                    "0.0 for a plane through the world origin."
                ),
                "default": 0.0,
            },
            "plane_label": {
                "type": "string",
                "description": "Human-readable label for the plane, e.g. 'XY'. Optional.",
                "default": "",
            },
            "side": {
                "type": "string",
                "enum": ["left", "right"],
                "description": (
                    "'left' = keep positive half-space (dot(n,p) >= offset); "
                    "'right' = keep negative half-space. Default 'left'."
                ),
                "default": "left",
            },
            "tol": {
                "type": "number",
                "description": "Plane-snapping tolerance. Default 1e-4.",
                "default": 1e-4,
                "exclusiveMinimum": 0,
            },
            "id": {
                "type": "string",
                "description": "Optional explicit node id.",
            },
        },
        "required": ["file_id", "target_id", "plane_normal"],
    },
)


@register(subd_enforce_symmetry_spec, write=True)
async def run_subd_enforce_symmetry(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    file_id = a.get("file_id", "").strip()
    target_id = a.get("target_id", "").strip()
    plane_normal = a.get("plane_normal")
    plane_offset = float(a.get("plane_offset", 0.0))
    plane_label = a.get("plane_label", "")
    side = a.get("side", "left")
    tol = float(a.get("tol", 1e-4))
    node_id = a.get("id", "").strip()

    if not file_id or not target_id:
        return err_payload("file_id and target_id are required", "BAD_ARGS")
    if not isinstance(plane_normal, list) or len(plane_normal) < 3:
        return err_payload("plane_normal must be [nx, ny, nz]", "BAD_ARGS")
    if side not in ("left", "right"):
        return err_payload("side must be 'left' or 'right'", "BAD_ARGS")
    if tol <= 0:
        return err_payload("tol must be > 0", "BAD_ARGS")

    try:
        fid = uuid.UUID(file_id)
    except Exception:
        return err_payload("file_id must be a uuid", "BAD_ARGS")

    content, err = read_feature_content(ctx, fid)
    if err:
        return err_payload(f"file not found: {err}", "NOT_FOUND")

    if not node_id:
        node_id = next_node_id(content, "subd_enforce_symmetry")

    node = {
        "id": node_id,
        "op": "subd_enforce_symmetry",
        "target_id": target_id,
        "plane_normal": [float(x) for x in plane_normal[:3]],
        "plane_offset": plane_offset,
        "plane_label": plane_label,
        "side": side,
        "tol": tol,
    }

    _, nid, err2 = append_feature_node(ctx, fid, node)
    if err2:
        return err_payload(err2, "ERROR")

    return ok_payload({
        "file_id": file_id,
        "id": nid or node_id,
        "op": "subd_enforce_symmetry",
        "side": side,
        "plane_normal": node["plane_normal"],
        "plane_offset": plane_offset,
    })
