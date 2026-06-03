"""sculpt/sculpt_extended_tools.py — Wave 9B LLM tool registrations.

ZBrush-equivalent organic sculpting tool suite:
  - sculpt_dynamesh_remesh   — SDF-based uniform-density remeshing (DynaMesh)
  - sculpt_polypaint_stroke  — per-vertex colour stroke with radial falloff
  - sculpt_polypaint_bake    — bake per-vertex colours to a UV texture
  - sculpt_displacement_bake — high-poly→low-poly displacement map (HD Geometry)
  - sculpt_auto_weight       — automatic bone weight computation
  - sculpt_lbs_pose          — apply Linear Blend Skinning pose

All tools follow the standard kerf ``ToolSpec`` pattern used throughout
kerf_cad_core.

PLUGIN REGISTRATION
-------------------
Add to plugin.py _TOOL_MODULES (Wave 9B block):

    "kerf_cad_core.sculpt.sculpt_extended_tools",

References
----------
- Pixologic ZBrush 2025 DynaMesh / PolyPaint / HD Geometry documentation.
- Baran, I., & Popović, J. (2007). "Automatic Rigging and Animation of 3D
  Characters." SIGGRAPH 2007, TOG 26(3), Article 72.
- Lewis, J.P., Cordner, M., & Fong, N. (2000). "Pose Space Deformation:
  A Unified Approach to Shape Interpolation and Skeleton-Driven Deformation."
  SIGGRAPH 2000, pp. 165-172.
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np

from kerf_cad_core._compat import ToolSpec, err_payload, ok_payload, register

try:
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
except ImportError:
    from kerf_cad_core._compat import ProjectCtx  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Tool: sculpt_dynamesh_remesh
# ---------------------------------------------------------------------------

_dynamesh_spec = ToolSpec(
    name="sculpt_dynamesh_remesh",
    description=(
        "Re-mesh a triangle mesh via ZBrush DynaMesh SDF-based voxelisation.\n"
        "Rebuilds uniform-density topology while preserving enclosed volume\n"
        "to within 2 %. Equivalent to ZBrush DynaMesh.\n\n"
        "Inputs:\n"
        "  positions (list[[x,y,z]]): vertex positions\n"
        "  triangles (list[[i,j,k]]): face indices\n"
        "  target_resolution (int, default 128): MC grid resolution\n\n"
        "Outputs:\n"
        "  positions: remeshed vertices\n"
        "  triangles: remeshed faces\n"
        "  volume_before, volume_after: volume metrics"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "positions":         {"type": "array",   "items": {"type": "array"}, "description": "Vertex positions (V×3)"},
            "triangles":         {"type": "array",   "items": {"type": "array"}, "description": "Triangle indices (F×3)"},
            "target_resolution": {"type": "integer", "default": 128,            "description": "Marching Cubes resolution"},
        },
        "required": ["positions", "triangles"],
    },
)


@register(_dynamesh_spec, write=False)
async def run_sculpt_dynamesh_remesh(args: str, ctx: ProjectCtx) -> str:
    try:
        payload = json.loads(args)
    except json.JSONDecodeError as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        from kerf_cad_core.sculpt.dynamesh import dynamesh_remesh

        positions  = np.asarray(payload["positions"],  dtype=np.float64)
        triangles  = np.asarray(payload["triangles"],  dtype=np.int32)
        resolution = int(payload.get("target_resolution", 128))

        result = dynamesh_remesh(positions, triangles, target_resolution=resolution)
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"dynamesh failed: {exc}", "COMPUTE_ERROR")

    return ok_payload({
        "positions":      result.positions.tolist(),
        "triangles":      result.triangles.tolist(),
        "target_resolution": result.target_resolution,
        "volume_before":  result.volume_before,
        "volume_after":   result.volume_after,
    })


# ---------------------------------------------------------------------------
# Tool: sculpt_polypaint_stroke
# ---------------------------------------------------------------------------

_polypaint_stroke_spec = ToolSpec(
    name="sculpt_polypaint_stroke",
    description=(
        "Apply a ZBrush PolyPaint colour stroke to a per-vertex colour layer.\n"
        "Colours within *radius* of *center* are blended toward *color* using\n"
        "radial falloff weighting × layer opacity.\n\n"
        "Inputs:\n"
        "  positions (list[[x,y,z]]): mesh vertices\n"
        "  vertex_colors (list[[r,g,b]]): current per-vertex colours (0–1)\n"
        "  opacity (float, default 1.0): layer opacity\n"
        "  center ([x,y,z]): brush centre in world space\n"
        "  radius (float): brush influence radius\n"
        "  color ([r,g,b]): target stroke colour (0–1)\n"
        "  falloff (str, default 'smooth'): 'smooth', 'linear', or 'constant'\n\n"
        "Outputs:\n"
        "  vertex_colors: updated per-vertex colours"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "positions":     {"type": "array", "items": {"type": "array"}, "description": "Vertex positions"},
            "vertex_colors": {"type": "array", "items": {"type": "array"}, "description": "Per-vertex RGB colours"},
            "opacity":       {"type": "number", "default": 1.0},
            "center":        {"type": "array",  "items": {"type": "number"}, "description": "Brush centre [x,y,z]"},
            "radius":        {"type": "number", "description": "Brush radius"},
            "color":         {"type": "array",  "items": {"type": "number"}, "description": "Stroke colour [r,g,b]"},
            "falloff":       {"type": "string",  "default": "smooth"},
        },
        "required": ["positions", "vertex_colors", "center", "radius", "color"],
    },
)


@register(_polypaint_stroke_spec, write=False)
async def run_sculpt_polypaint_stroke(args: str, ctx: ProjectCtx) -> str:
    try:
        payload = json.loads(args)
    except json.JSONDecodeError as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        from kerf_cad_core.sculpt.polypaint import PolyPaintLayer, polypaint_stroke

        positions = np.asarray(payload["positions"], dtype=np.float64)
        vc        = np.asarray(payload["vertex_colors"], dtype=np.float32)
        opacity   = float(payload.get("opacity", 1.0))
        center    = np.asarray(payload["center"], dtype=np.float64)
        radius    = float(payload["radius"])
        color     = np.asarray(payload["color"], dtype=np.float32)
        falloff   = str(payload.get("falloff", "smooth"))

        layer = PolyPaintLayer(vertex_colors=vc, opacity=opacity)
        new_layer = polypaint_stroke(positions, layer, center, radius, color, falloff)
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"polypaint_stroke failed: {exc}", "COMPUTE_ERROR")

    return ok_payload({"vertex_colors": new_layer.vertex_colors.tolist()})


# ---------------------------------------------------------------------------
# Tool: sculpt_polypaint_bake
# ---------------------------------------------------------------------------

_polypaint_bake_spec = ToolSpec(
    name="sculpt_polypaint_bake",
    description=(
        "Bake per-vertex PolyPaint colours to a UV texture image.\n"
        "Rasterises triangle colours via barycentric UV interpolation.\n"
        "If uv_coords is omitted, LSCM unwrap is computed automatically.\n\n"
        "Inputs:\n"
        "  positions (list[[x,y,z]])\n"
        "  triangles (list[[i,j,k]])\n"
        "  vertex_colors (list[[r,g,b]])\n"
        "  uv_coords (list[[u,v]] or null)\n"
        "  texture_size (int, default 512)\n\n"
        "Outputs:\n"
        "  texture (texture_size × texture_size × 3 float list)"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "positions":     {"type": "array", "items": {"type": "array"}},
            "triangles":     {"type": "array", "items": {"type": "array"}},
            "vertex_colors": {"type": "array", "items": {"type": "array"}},
            "uv_coords":     {"type": ["array", "null"], "default": None},
            "texture_size":  {"type": "integer", "default": 512},
        },
        "required": ["positions", "triangles", "vertex_colors"],
    },
)


@register(_polypaint_bake_spec, write=False)
async def run_sculpt_polypaint_bake(args: str, ctx: ProjectCtx) -> str:
    try:
        payload = json.loads(args)
    except json.JSONDecodeError as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        from kerf_cad_core.sculpt.polypaint import PolyPaintLayer, bake_polypaint_to_uv_texture

        mesh_dict = {
            "vertices": payload["positions"],
            "faces":    payload["triangles"],
        }
        vc      = np.asarray(payload["vertex_colors"], dtype=np.float32)
        layer   = PolyPaintLayer(vertex_colors=vc)
        uv_raw  = payload.get("uv_coords", None)
        uv      = np.asarray(uv_raw, dtype=np.float64) if uv_raw is not None else None
        tx_size = int(payload.get("texture_size", 512))

        tex = bake_polypaint_to_uv_texture(mesh_dict, layer, uv, tx_size)
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"polypaint_bake failed: {exc}", "COMPUTE_ERROR")

    return ok_payload({"texture": tex.tolist()})


# ---------------------------------------------------------------------------
# Tool: sculpt_displacement_bake
# ---------------------------------------------------------------------------

_displacement_bake_spec = ToolSpec(
    name="sculpt_displacement_bake",
    description=(
        "Bake a displacement map from a high-poly sculpt onto a low-poly UV layout.\n"
        "Equivalent to ZBrush HD Geometry displacement export.\n\n"
        "For each UV-space pixel on the low-poly mesh, a ray is shot along the\n"
        "surface normal; the distance to the nearest high-poly intersection gives\n"
        "the signed displacement scalar.\n\n"
        "Inputs:\n"
        "  low_poly_positions, low_poly_triangles, low_poly_uv (null = auto LSCM)\n"
        "  high_poly_positions, high_poly_triangles\n"
        "  map_resolution (int, default 2048)\n"
        "  max_distance_mm (float, default 5.0)\n\n"
        "Outputs:\n"
        "  scalar_field (map_resolution × map_resolution float list)\n"
        "  resolution, udim_tile"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "low_poly_positions":  {"type": "array", "items": {"type": "array"}},
            "low_poly_triangles":  {"type": "array", "items": {"type": "array"}},
            "low_poly_uv":         {"type": ["array", "null"], "default": None},
            "high_poly_positions": {"type": "array", "items": {"type": "array"}},
            "high_poly_triangles": {"type": "array", "items": {"type": "array"}},
            "map_resolution":      {"type": "integer", "default": 2048},
            "max_distance_mm":     {"type": "number",  "default": 5.0},
        },
        "required": [
            "low_poly_positions", "low_poly_triangles",
            "high_poly_positions", "high_poly_triangles",
        ],
    },
)


@register(_displacement_bake_spec, write=False)
async def run_sculpt_displacement_bake(args: str, ctx: ProjectCtx) -> str:
    try:
        payload = json.loads(args)
    except json.JSONDecodeError as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        from kerf_cad_core.sculpt.displacement_bake import bake_displacement

        lp_pos  = np.asarray(payload["low_poly_positions"],  dtype=np.float64)
        lp_tri  = np.asarray(payload["low_poly_triangles"],  dtype=np.int32)
        lp_uv_raw = payload.get("low_poly_uv", None)
        lp_uv   = np.asarray(lp_uv_raw, dtype=np.float64) if lp_uv_raw is not None else None
        hp_pos  = np.asarray(payload["high_poly_positions"], dtype=np.float64)
        hp_tri  = np.asarray(payload["high_poly_triangles"], dtype=np.int32)
        res     = int(payload.get("map_resolution", 2048))
        maxd    = float(payload.get("max_distance_mm", 5.0))

        dm = bake_displacement(lp_pos, lp_tri, lp_uv, hp_pos, hp_tri, res, maxd)
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"displacement_bake failed: {exc}", "COMPUTE_ERROR")

    return ok_payload({
        "resolution":   dm.resolution,
        "scalar_field": dm.scalar_field.tolist(),
        "udim_tile":    dm.udim_tile,
    })


# ---------------------------------------------------------------------------
# Tool: sculpt_auto_weight
# ---------------------------------------------------------------------------

_auto_weight_spec = ToolSpec(
    name="sculpt_auto_weight",
    description=(
        "Compute automatic bone influence weights for a mesh skeleton.\n"
        "Uses bone-distance heuristic + Laplacian smoothing (Baran-Popović 2007).\n\n"
        "Inputs:\n"
        "  positions (list[[x,y,z]]): mesh vertices\n"
        "  triangles (list[[i,j,k]]): optional, enables Laplacian smoothing\n"
        "  bones (list of {name,parent,head,tail}): skeleton definition\n"
        "  max_bones_per_vert (int, default 4)\n\n"
        "Outputs:\n"
        "  bone_indices (V×4 int), bone_weights (V×4 float)"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "positions":          {"type": "array", "items": {"type": "array"}},
            "triangles":          {"type": ["array", "null"], "default": None},
            "bones": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name":   {"type": "string"},
                        "parent": {"type": ["string", "null"]},
                        "head":   {"type": "array", "items": {"type": "number"}},
                        "tail":   {"type": "array", "items": {"type": "number"}},
                    },
                    "required": ["name", "head", "tail"],
                },
            },
            "max_bones_per_vert": {"type": "integer", "default": 4},
        },
        "required": ["positions", "bones"],
    },
)


@register(_auto_weight_spec, write=False)
async def run_sculpt_auto_weight(args: str, ctx: ProjectCtx) -> str:
    try:
        payload = json.loads(args)
    except json.JSONDecodeError as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        from kerf_cad_core.sculpt.character_rigging import (
            Skeleton, make_bone, auto_weight_from_proximity
        )

        positions = np.asarray(payload["positions"], dtype=np.float64)
        tri_raw   = payload.get("triangles", None)
        triangles = np.asarray(tri_raw, dtype=np.int32) if tri_raw is not None else None
        max_b     = int(payload.get("max_bones_per_vert", 4))

        bones = []
        for bd in payload["bones"]:
            bones.append(make_bone(
                name=bd["name"],
                head=np.asarray(bd["head"], dtype=np.float64),
                tail=np.asarray(bd["tail"], dtype=np.float64),
                parent=bd.get("parent", None),
            ))

        skeleton = Skeleton(bones=bones)
        wm = auto_weight_from_proximity(positions, skeleton, max_bones_per_vert=max_b, triangles=triangles)
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"auto_weight failed: {exc}", "COMPUTE_ERROR")

    return ok_payload({
        "bone_indices": wm.bone_indices.tolist(),
        "bone_weights": wm.bone_weights.tolist(),
    })


# ---------------------------------------------------------------------------
# Tool: sculpt_lbs_pose
# ---------------------------------------------------------------------------

_lbs_pose_spec = ToolSpec(
    name="sculpt_lbs_pose",
    description=(
        "Apply Linear Blend Skinning to deform a character mesh into a pose.\n"
        "Implements the Lewis et al. (2000) LBS formula:\n"
        "  p_new = Σ w_i * M_pose_i * M_rest_i^{-1} * p_rest\n\n"
        "Inputs:\n"
        "  positions (list[[x,y,z]]): rest-pose vertex positions\n"
        "  bone_indices (V×4 int): from sculpt_auto_weight\n"
        "  bone_weights (V×4 float): from sculpt_auto_weight\n"
        "  bones (list of {name,parent,head,tail}): rest skeleton\n"
        "  pose_matrices (list of 4×4 lists): one world-space pose matrix per bone\n\n"
        "Outputs:\n"
        "  positions: deformed vertex positions"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "positions":     {"type": "array", "items": {"type": "array"}},
            "bone_indices":  {"type": "array", "items": {"type": "array"}},
            "bone_weights":  {"type": "array", "items": {"type": "array"}},
            "bones": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name":   {"type": "string"},
                        "parent": {"type": ["string", "null"]},
                        "head":   {"type": "array"},
                        "tail":   {"type": "array"},
                    },
                    "required": ["name", "head", "tail"],
                },
            },
            "pose_matrices": {"type": "array", "items": {"type": "array"}},
        },
        "required": ["positions", "bone_indices", "bone_weights", "bones", "pose_matrices"],
    },
)


@register(_lbs_pose_spec, write=False)
async def run_sculpt_lbs_pose(args: str, ctx: ProjectCtx) -> str:
    try:
        payload = json.loads(args)
    except json.JSONDecodeError as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        from kerf_cad_core.sculpt.character_rigging import (
            Skeleton, WeightMap, make_bone, linear_blend_skinning
        )

        positions = np.asarray(payload["positions"], dtype=np.float64)
        b_idx     = np.asarray(payload["bone_indices"], dtype=np.int32)
        b_wts     = np.asarray(payload["bone_weights"], dtype=np.float32)
        V = len(positions)

        bones = []
        for bd in payload["bones"]:
            bones.append(make_bone(
                name=bd["name"],
                head=np.asarray(bd["head"], dtype=np.float64),
                tail=np.asarray(bd["tail"], dtype=np.float64),
                parent=bd.get("parent", None),
            ))
        skeleton = Skeleton(bones=bones)

        pose_matrices = [np.asarray(m, dtype=np.float64) for m in payload["pose_matrices"]]

        wm = WeightMap(vertex_count=V, bone_indices=b_idx, bone_weights=b_wts)
        deformed = linear_blend_skinning(positions, wm, skeleton, pose_matrices)
    except (KeyError, TypeError, ValueError) as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(f"lbs_pose failed: {exc}", "COMPUTE_ERROR")

    return ok_payload({"positions": deformed.tolist()})
