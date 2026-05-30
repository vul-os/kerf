"""
kerf_cfd.mesh_unstructured_tool — LLM tool wrapper for 3-D unstructured mesh generation.

Tool: cfd_mesh_unstructured
  Generate a 3-D unstructured tetrahedral mesh for CFD simulation.  Supports
  built-in geometries (unit_cube, spherical_shell, bent_pipe) and custom surface
  meshes.  Returns mesh statistics and quality metrics.
"""

from __future__ import annotations

import json
import math
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cfd._compat import ToolSpec, err_payload, ok_payload, ProjectCtx


# ---------------------------------------------------------------------------
# Tool spec
# ---------------------------------------------------------------------------

cfd_mesh_unstructured_spec = ToolSpec(
    name="cfd_mesh_unstructured",
    description=(
        "Generate a 3-D unstructured tetrahedral CFD mesh using Delaunay "
        "tetrahedralization (scipy.spatial.Delaunay core).  Supports built-in "
        "geometry primitives: 'unit_cube', 'spherical_shell', 'bent_pipe'.  "
        "Also accepts a custom surface mesh (vertices + triangles) for arbitrary "
        "boundary geometry.  Returns mesh statistics: vertex count, element count, "
        "total volume, Euler characteristic, Voronoi cell volumes, aspect ratio "
        "statistics, dihedral angle range, and quality flags."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "geometry": {
                "type": "string",
                "enum": ["unit_cube", "spherical_shell", "bent_pipe", "custom"],
                "description": (
                    "Geometry to mesh.  Built-in: 'unit_cube' (unit [0,1]³ cube), "
                    "'spherical_shell' (annular shell between two concentric spheres), "
                    "'bent_pipe' (curved cylindrical pipe).  Use 'custom' with "
                    "surface_vertices + surface_triangles for arbitrary geometry."
                ),
            },
            "resolution": {
                "type": "integer",
                "description": (
                    "Mesh resolution parameter.  For unit_cube: divisions per axis (default 4). "
                    "For spherical_shell: latitude/longitude subdivisions (default 8). "
                    "For bent_pipe: axial stations (default 12). "
                    "Higher values produce finer meshes."
                ),
            },
            "outer_radius": {
                "type": "number",
                "description": "Outer radius for spherical_shell geometry (default 1.0).",
            },
            "inner_radius": {
                "type": "number",
                "description": "Inner radius for spherical_shell geometry (default 0.3).",
            },
            "pipe_radius": {
                "type": "number",
                "description": "Cross-section radius for bent_pipe geometry (default 0.1).",
            },
            "bend_angle_deg": {
                "type": "number",
                "description": "Bend angle in degrees for bent_pipe geometry (default 90).",
            },
            "surface_vertices": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": (
                    "Vertex coordinates for custom geometry. "
                    "Each entry is [x, y, z].  Required when geometry='custom'."
                ),
            },
            "surface_triangles": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "description": (
                    "Triangle index triples for custom geometry. "
                    "Each entry is [i, j, k] (0-based vertex indices).  "
                    "Required when geometry='custom'."
                ),
            },
            "density_field": {
                "type": "object",
                "description": (
                    "Uniform target edge length for octree density refinement. "
                    "Pass {'uniform': <float>} to trigger one refinement pass."
                ),
                "properties": {
                    "uniform": {
                        "type": "number",
                        "description": "Uniform target edge length for refinement.",
                    },
                },
            },
            "compute_voronoi": {
                "type": "boolean",
                "description": "If true, compute Voronoi cell volumes (default true).",
            },
        },
        "required": ["geometry"],
    },
)


# ---------------------------------------------------------------------------
# Sync core
# ---------------------------------------------------------------------------

def run_cfd_mesh_unstructured_sync(
    geometry: str,
    *,
    resolution: int = 0,
    outer_radius: float = 1.0,
    inner_radius: float = 0.3,
    pipe_radius: float = 0.1,
    bend_angle_deg: float = 90.0,
    surface_vertices: list | None = None,
    surface_triangles: list | None = None,
    density_field: dict | None = None,
    compute_voronoi: bool = True,
) -> dict[str, Any]:
    """Generate a 3-D unstructured tet mesh and return quality statistics.

    Returns a JSON-serialisable dict with keys:
        ok (bool), geometry (str), n_vertices (int), n_elements (int),
        n_boundary_faces (int), total_volume (float), euler_characteristic (int),
        aspect_ratio_mean (float), aspect_ratio_p95 (float), aspect_ratio_max (float),
        min_dihedral_deg (float), max_dihedral_deg (float), n_bad_elements (int),
        quality_fraction_ar10 (float), voronoi_computed (bool),
        voronoi_total (float if computed), warnings (list[str])
    """
    import numpy as np
    from kerf_cfd.mesh_unstructured import (
        mesh_unit_cube_unstructured,
        mesh_spherical_shell,
        mesh_bent_pipe,
        mesh_from_surface,
        refine_with_density_field,
    )

    valid_geometries = {"unit_cube", "spherical_shell", "bent_pipe", "custom"}
    if geometry not in valid_geometries:
        return {
            "ok": False,
            "error": f"geometry must be one of {sorted(valid_geometries)}",
            "code": "BAD_ARGS",
        }

    warnings: list[str] = []

    try:
        if geometry == "unit_cube":
            n = resolution if resolution > 0 else 4
            n = min(n, 12)  # cap for speed
            mesh = mesh_unit_cube_unstructured(n=n, compute_voronoi=compute_voronoi)

        elif geometry == "spherical_shell":
            if not math.isfinite(outer_radius) or outer_radius <= 0:
                return {"ok": False, "error": "outer_radius must be positive", "code": "BAD_ARGS"}
            if not math.isfinite(inner_radius) or inner_radius <= 0:
                return {"ok": False, "error": "inner_radius must be positive", "code": "BAD_ARGS"}
            if inner_radius >= outer_radius:
                return {"ok": False, "error": "inner_radius must be less than outer_radius", "code": "BAD_ARGS"}
            n = resolution if resolution > 0 else 10
            n = min(n, 16)
            # n_radial scales with resolution for volume accuracy
            n_radial = max(5, n // 2)
            mesh = mesh_spherical_shell(
                outer_radius=outer_radius,
                inner_radius=inner_radius,
                n_lat=n, n_lon=n, n_radial=n_radial,
                compute_voronoi=compute_voronoi,
            )

        elif geometry == "bent_pipe":
            if not math.isfinite(pipe_radius) or pipe_radius <= 0:
                return {"ok": False, "error": "pipe_radius must be positive", "code": "BAD_ARGS"}
            n_cross = max(3, resolution if resolution > 0 else 4)
            n_cross = min(n_cross, 8)
            # n_axial = 10 × n_cross gives near-isotropic cells for good tet quality.
            n_axial = n_cross * 10
            mesh = mesh_bent_pipe(
                radius=pipe_radius,
                bend_angle_deg=bend_angle_deg,
                n_cross=n_cross, n_axial=n_axial,
                compute_voronoi=compute_voronoi,
            )

        else:  # custom
            if not surface_vertices or not surface_triangles:
                return {
                    "ok": False,
                    "error": "surface_vertices and surface_triangles are required for geometry='custom'",
                    "code": "BAD_ARGS",
                }
            if len(surface_vertices) < 4:
                return {
                    "ok": False,
                    "error": "Custom geometry needs at least 4 vertices",
                    "code": "BAD_ARGS",
                }
            verts = [tuple(v) for v in surface_vertices]  # type: ignore[misc]
            tris = [tuple(t) for t in surface_triangles]  # type: ignore[misc]
            mesh = mesh_from_surface(
                verts, tris, compute_voronoi=compute_voronoi  # type: ignore[arg-type]
            )

        # Optional refinement
        if density_field and "uniform" in density_field:
            target_size = float(density_field["uniform"])
            if target_size > 0:
                mesh = refine_with_density_field(mesh, target_size, max_iterations=3)
            else:
                warnings.append("density_field.uniform must be positive; refinement skipped.")

    except Exception as exc:
        return {"ok": False, "error": str(exc), "code": "MESH_ERROR"}

    if mesh.n_elements() == 0:
        return {"ok": False, "error": "Mesh generation produced zero elements", "code": "MESH_ERROR"}

    # Compute aspect ratio statistics
    ar = mesh.aspect_ratios()
    ar_finite = ar[np.isfinite(ar)]
    ar_mean = float(np.mean(ar_finite)) if len(ar_finite) > 0 else float("inf")
    ar_p95 = float(np.percentile(ar_finite, 95)) if len(ar_finite) > 0 else float("inf")
    ar_max = float(np.max(ar_finite)) if len(ar_finite) > 0 else float("inf")

    min_dih, max_dih = mesh.dihedral_angle_stats()
    qual_frac = mesh.quality_fraction_below_aspect(10.0)

    voronoi_total = float(mesh.voronoi_volumes.sum()) if mesh.voronoi_volumes.shape[0] > 0 else None

    result: dict[str, Any] = {
        "ok": True,
        "geometry": geometry,
        "n_vertices": mesh.n_vertices(),
        "n_elements": mesh.n_elements(),
        "n_boundary_faces": mesh.n_boundary_faces(),
        "total_volume": mesh.total_volume(),
        "euler_characteristic": mesh.euler_characteristic(),
        "aspect_ratio_mean": ar_mean,
        "aspect_ratio_p95": ar_p95,
        "aspect_ratio_max": ar_max,
        "min_dihedral_deg": min_dih,
        "max_dihedral_deg": max_dih,
        "n_bad_elements": len(mesh.quality_flags),
        "quality_fraction_ar10": qual_frac,
        "voronoi_computed": mesh.voronoi_volumes.shape[0] > 0,
        "voronoi_total": voronoi_total,
        "warnings": warnings,
    }
    return result


# ---------------------------------------------------------------------------
# Async LLM handler
# ---------------------------------------------------------------------------

async def run_cfd_mesh_unstructured(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    """Async entry-point for the cfd_mesh_unstructured LLM tool."""
    import asyncio

    try:
        geometry = str(args.get("geometry", "unit_cube"))
        resolution = int(args.get("resolution", 0))
        outer_radius = float(args.get("outer_radius", 1.0))
        inner_radius = float(args.get("inner_radius", 0.3))
        pipe_radius = float(args.get("pipe_radius", 0.1))
        bend_angle_deg = float(args.get("bend_angle_deg", 90.0))
        surface_vertices = args.get("surface_vertices")
        surface_triangles = args.get("surface_triangles")
        density_field = args.get("density_field")
        compute_voronoi = bool(args.get("compute_voronoi", True))
    except (TypeError, ValueError) as exc:
        return err_payload(f"invalid argument: {exc}", "BAD_ARGS")

    result = await asyncio.to_thread(
        run_cfd_mesh_unstructured_sync,
        geometry,
        resolution=resolution,
        outer_radius=outer_radius,
        inner_radius=inner_radius,
        pipe_radius=pipe_radius,
        bend_angle_deg=bend_angle_deg,
        surface_vertices=surface_vertices,
        surface_triangles=surface_triangles,
        density_field=density_field,
        compute_voronoi=compute_voronoi,
    )

    if not result.get("ok"):
        return err_payload(result.get("error", "mesh error"), result.get("code", "ERROR"))
    return ok_payload(result)
