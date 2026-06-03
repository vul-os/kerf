"""
kerf_cad_core.sdf — Signed Distance Field (SDF) primitives, CSG operations,
smooth blending (Quilez 2008), and Marching Cubes polygonization.

Sub-modules
-----------
csg             — SDF primitives, CSG ops (union/intersection/subtraction),
                  smooth-min blend variants, transforms (translate/scale/rotate).
marching_cubes  — Lorensen-Cline 1987 Marching Cubes polygonization with
                  linear edge interpolation and gradient-based vertex normals.
"""
from __future__ import annotations

from kerf_cad_core.sdf.csg import (
    SDF,
    sdf_sphere,
    sdf_box,
    sdf_cylinder_z,
    sdf_plane,
    sdf_union,
    sdf_intersection,
    sdf_subtraction,
    sdf_smooth_union,
    sdf_smooth_intersection,
    sdf_smooth_subtraction,
    sdf_translate,
    sdf_scale,
    sdf_rotate,
)
from kerf_cad_core.sdf.marching_cubes import (
    MarchingCubesResult,
    polygonize_sdf,
    polygonize_sdf_chernyaev,
)

__all__ = [
    "SDF",
    "sdf_sphere",
    "sdf_box",
    "sdf_cylinder_z",
    "sdf_plane",
    "sdf_union",
    "sdf_intersection",
    "sdf_subtraction",
    "sdf_smooth_union",
    "sdf_smooth_intersection",
    "sdf_smooth_subtraction",
    "sdf_translate",
    "sdf_scale",
    "sdf_rotate",
    "MarchingCubesResult",
    "polygonize_sdf",
    "polygonize_sdf_chernyaev",
]
