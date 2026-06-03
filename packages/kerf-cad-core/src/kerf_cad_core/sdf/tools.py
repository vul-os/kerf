"""
kerf_cad_core.sdf.tools — Wave 8 LLM tool for SDF polygonization.

Wave 8 modules
--------------
  kerf_cad_core.sdf.csg           — SDF primitives + CSG boolean operations
  kerf_cad_core.sdf.marching_cubes — Lorensen-Cline Marching Cubes polygonizer

Tool registered
---------------
  sdf_polygonize — Build a CSG SDF from primitive shapes and polygonize via
    Marching Cubes, returning vertices and triangle indices.

References
----------
Quilez, I. (2008). "smooth min." https://iquilezles.org/articles/smin/
Lorensen, W.E. & Cline, H.E. (1987). "Marching Cubes: A high resolution 3D
    surface construction algorithm." SIGGRAPH '87.
Bourke, P. (1994). "Polygonising a scalar field." http://paulbourke.net/geometry/polygonise/
"""
from __future__ import annotations

import json
from typing import Any

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

from kerf_cad_core.sdf.csg import (
    sdf_sphere,
    sdf_box,
    sdf_cylinder_z,
    sdf_plane,
    sdf_union,
    sdf_intersection,
    sdf_subtraction,
)
from kerf_cad_core.sdf.marching_cubes import polygonize_sdf

import numpy as np


# ---------------------------------------------------------------------------
# Helper: build SDF from declarative description
# ---------------------------------------------------------------------------

def _build_sdf(desc: dict):
    """Recursively build an SDF callable from a declarative dict.

    Supported types:
      {"type": "sphere",    "radius": r,    "center": [cx,cy,cz]}
      {"type": "box",       "half_extents": [hx,hy,hz], "center": [cx,cy,cz]}
      {"type": "cylinder_z","radius": r,    "half_height": h, "center": [cx,cy,cz]}
      {"type": "plane",     "normal": [nx,ny,nz], "offset": d}
      {"type": "union",       "a": {...}, "b": {...}}
      {"type": "intersection","a": {...}, "b": {...}}
      {"type": "subtraction", "a": {...}, "b": {...}}
    """
    kind = str(desc.get("type", "")).lower()
    center = np.array(desc.get("center", [0.0, 0.0, 0.0]), dtype=np.float64)

    if kind == "sphere":
        r = float(desc.get("radius", 1.0))
        base = sdf_sphere(r)
        if any(center != 0):
            def _translated(pts, c=center, f=base):
                return f(pts - c)
            return _translated
        return base

    if kind == "box":
        he = np.array(desc.get("half_extents", [1.0, 1.0, 1.0]), dtype=np.float64)
        base = sdf_box(he)
        if any(center != 0):
            def _translated(pts, c=center, f=base):
                return f(pts - c)
            return _translated
        return base

    if kind == "cylinder_z":
        r = float(desc.get("radius", 1.0))
        h = float(desc.get("half_height", 1.0))
        base = sdf_cylinder_z(r, h)
        if any(center != 0):
            def _translated(pts, c=center, f=base):
                return f(pts - c)
            return _translated
        return base

    if kind == "plane":
        n = np.array(desc.get("normal", [0.0, 0.0, 1.0]), dtype=np.float64)
        d = float(desc.get("offset", 0.0))
        return sdf_plane(n, d)

    if kind == "union":
        fa = _build_sdf(desc["a"])
        fb = _build_sdf(desc["b"])
        return sdf_union(fa, fb)

    if kind == "intersection":
        fa = _build_sdf(desc["a"])
        fb = _build_sdf(desc["b"])
        return sdf_intersection(fa, fb)

    if kind in ("subtraction", "difference"):
        fa = _build_sdf(desc["a"])
        fb = _build_sdf(desc["b"])
        return sdf_subtraction(fa, fb)

    raise ValueError(f"Unknown SDF type: {kind!r}")


# ---------------------------------------------------------------------------
# Tool: sdf_polygonize
# ---------------------------------------------------------------------------

_sdf_polygonize_spec = ToolSpec(
    name="sdf_polygonize",
    description=(
        "Build a CSG SDF from primitive shapes and extract an isosurface mesh\n"
        "via Marching Cubes (Lorensen & Cline 1987).\n"
        "\n"
        "Supported SDF primitives:\n"
        "  sphere:       {type:'sphere',    radius:r,          center:[cx,cy,cz]}\n"
        "  box:          {type:'box',       half_extents:[hx,hy,hz], center:[...]}\n"
        "  cylinder_z:   {type:'cylinder_z',radius:r,half_height:h, center:[...]}\n"
        "  plane:        {type:'plane',     normal:[nx,ny,nz], offset:d}\n"
        "  union:        {type:'union',       a:{...}, b:{...}}\n"
        "  intersection: {type:'intersection',a:{...}, b:{...}}\n"
        "  subtraction:  {type:'subtraction', a:{...}, b:{...}}\n"
        "\n"
        "Polygonization: uniform grid over [bounds_min, bounds_max] at resolution.\n"
        "Isovalue = 0 (SDF zero-crossing = surface boundary).\n"
        "\n"
        "Returns:\n"
        "  vertices      — list of [x,y,z] mesh vertices\n"
        "  triangles     — list of [i0,i1,i2] index triples\n"
        "  vertex_count  — int\n"
        "  triangle_count— int\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sdf": {
                "type": "object",
                "description": "Root SDF primitive or CSG tree (see tool description).",
            },
            "bounds_min": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Grid lower corner [xmin, ymin, zmin]. Default [-2,-2,-2].",
            },
            "bounds_max": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Grid upper corner [xmax, ymax, zmax]. Default [2, 2, 2].",
            },
            "resolution": {
                "type": "integer",
                "description": "Grid samples per axis (default 32). Max 128.",
            },
        },
        "required": ["sdf"],
    },
)


@register(_sdf_polygonize_spec, write=False)
async def run_sdf_polygonize(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    sdf_desc = a.get("sdf")
    if not sdf_desc or not isinstance(sdf_desc, dict):
        return err_payload("sdf is required (object)", "BAD_ARGS")

    bounds_min = np.array(a.get("bounds_min", [-2.0, -2.0, -2.0]), dtype=np.float64)
    bounds_max = np.array(a.get("bounds_max", [2.0, 2.0, 2.0]), dtype=np.float64)
    resolution = min(int(a.get("resolution", 32)), 128)

    try:
        sdf_fn = _build_sdf(sdf_desc)
    except Exception as exc:
        return err_payload(f"invalid SDF description: {exc}", "BAD_ARGS")

    try:
        mesh = polygonize_sdf(
            sdf=sdf_fn,
            bounds_min=tuple(bounds_min.tolist()),
            bounds_max=tuple(bounds_max.tolist()),
            resolution=resolution,
            isovalue=0.0,
        )
    except Exception as exc:
        return err_payload(f"polygonization error: {exc}", "EVAL_ERROR")

    return ok_payload({
        "vertices": mesh.vertices.tolist(),
        "triangles": mesh.triangles.tolist(),
        "vertex_count": len(mesh.vertices),
        "triangle_count": len(mesh.triangles),
        "resolution": resolution,
    })


__all__ = ["run_sdf_polygonize"]
