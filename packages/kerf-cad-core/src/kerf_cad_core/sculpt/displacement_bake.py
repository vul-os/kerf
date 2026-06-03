"""sculpt/displacement_bake.py — ZBrush HD Geometry displacement map baking.

ZBrush HD Geometry (Pixologic 2025)
-------------------------------------
When a ZBrush mesh is sculpted at very high subdivisions (HD mode), the fine
detail is stored as a *displacement map* relative to a lower-resolution cage.
On export, each UV-space pixel on the low-poly base mesh is assigned a signed
scalar representing how far the high-poly surface deviates from the low-poly
surface along the low-poly surface normal.  Renderers (RenderMan, Arnold, V-Ray)
use this map to reconstruct the full-detail silhouette at render time.

Algorithm
---------
For each pixel (u, v) in the displacement map:
1. Determine which low-poly triangle contains that UV sample.
2. Compute the world-space position ``p_low`` and surface normal ``n_low``
   at that UV sample via barycentric interpolation.
3. Cast a ray ``r(t) = p_low + t * n_low`` and find the *closest intersection*
   with the high-poly mesh within ``max_distance_mm``.
4. Record the signed displacement ``d = t`` (positive = above, negative = below).

This implements the standard *cage-projection* baking used by xNormal, Substance
Painter, and ZBrush HD.

Ray–triangle intersection
--------------------------
Uses the Möller–Trumbore (1997) algorithm for each high-poly triangle.

References
----------
- Pixologic ZBrush 2025 HD Geometry / Displacement Map documentation.
  https://docs.pixologic.com/reference-guide/zplugin/multi-displacement-3/
- Möller, T., & Trumbore, B. (1997). "Fast, minimum storage ray/triangle
  intersection." Journal of Graphics Tools 2(1):21-28.
- Bourke, P. (1994). "Polygonising a scalar field."
  http://paulbourke.net/geometry/polygonise/
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class DisplacementMap:
    """Output of :func:`bake_displacement`.

    Attributes
    ----------
    resolution : int
        Square texture size (pixels per side).
    scalar_field : np.ndarray, shape (resolution, resolution)
        Signed displacement in world units (mm).  Positive = surface above
        low-poly normal; negative = below.  Background (no coverage) = 0.
    udim_tile : int
        UDIM tile number (default 1001 = first tile, UV [0,1]²).
    """

    resolution: int
    scalar_field: np.ndarray      # (resolution, resolution) signed displacement
    udim_tile: int = 1001


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _triangle_normals(positions: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Compute unit face normals for each triangle, shape (F, 3)."""
    v0 = positions[triangles[:, 0]]
    v1 = positions[triangles[:, 1]]
    v2 = positions[triangles[:, 2]]
    n = np.cross(v1 - v0, v2 - v0)
    norms = np.linalg.norm(n, axis=1, keepdims=True)
    norms = np.where(norms < 1e-15, 1.0, norms)
    return n / norms


def _vertex_normals(positions: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Compute area-weighted per-vertex normals, shape (V, 3)."""
    V = len(positions)
    vn = np.zeros((V, 3), dtype=np.float64)
    v0 = positions[triangles[:, 0]]
    v1 = positions[triangles[:, 1]]
    v2 = positions[triangles[:, 2]]
    fn = np.cross(v1 - v0, v2 - v0)   # area-weighted (F, 3)
    np.add.at(vn, triangles[:, 0], fn)
    np.add.at(vn, triangles[:, 1], fn)
    np.add.at(vn, triangles[:, 2], fn)
    norms = np.linalg.norm(vn, axis=1, keepdims=True)
    norms = np.where(norms < 1e-15, 1.0, norms)
    return vn / norms


def _ray_triangle_intersect_batch(
    ray_origins: np.ndarray,   # (N, 3)
    ray_dirs: np.ndarray,      # (N, 3)
    v0: np.ndarray,            # (F, 3)
    v1: np.ndarray,
    v2: np.ndarray,
    max_t: float,
) -> np.ndarray:
    """Möller–Trumbore ray-triangle intersection for N rays against F triangles.

    Returns t_hit (N,) — the smallest positive t found, or np.inf if no hit.

    For large meshes the outer loop is over ray batches to avoid O(N*F) memory.

    References
    ----------
    Möller, T., & Trumbore, B. (1997). "Fast, minimum storage ray/triangle
    intersection." JGT 2(1):21-28.
    """
    N = len(ray_origins)
    t_min = np.full(N, np.inf, dtype=np.float64)

    EPS = 1e-8
    F = len(v0)

    batch = 256  # rays per batch
    for rs in range(0, N, batch):
        re = min(rs + batch, N)
        ro = ray_origins[rs:re]  # (B, 3)
        rd = ray_dirs[rs:re]     # (B, 3)
        B = re - rs

        # Broadcast: (B, F, 3) vs (1, F, 3)
        e1 = (v1 - v0)[None, :, :]   # (1, F, 3)
        e2 = (v2 - v0)[None, :, :]
        h  = np.cross(rd[:, None, :], e2)       # (B, F, 3)
        a  = np.einsum("bfi,fi->bf", h, v1-v0)  # (B, F)

        # Parallel rays
        valid = np.abs(a) > EPS   # (B, F)

        f = np.where(valid, 1.0 / np.where(valid, a, 1.0), 0.0)
        s = ro[:, None, :] - v0[None, :, :]     # (B, F, 3)
        u = f * np.einsum("bfi,bfi->bf", s, h)
        valid &= (u >= 0.0) & (u <= 1.0)

        q = np.cross(s, e1.repeat(B, axis=0) if B > 1 else e1)
        # Use einsum for (B,F,3) dot (B,1,3)
        v_param = f * np.einsum("bfi,bi->bf", q, rd)
        valid &= (v_param >= 0.0) & (u + v_param <= 1.0)

        t = f * np.einsum("bfi,fi->bf", q, v2 - v0)   # (B, F)
        valid &= (t > EPS) & (t < max_t)

        t_clamped = np.where(valid, t, np.inf)
        t_best = np.min(t_clamped, axis=1)   # (B,)
        t_min[rs:re] = np.minimum(t_min[rs:re], t_best)

    return t_min


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def bake_displacement(
    low_poly_positions: np.ndarray,
    low_poly_triangles: np.ndarray,
    low_poly_uv: np.ndarray | None,
    high_poly_positions: np.ndarray,
    high_poly_triangles: np.ndarray,
    map_resolution: int = 2048,
    max_distance_mm: float = 5.0,
) -> DisplacementMap:
    """Bake a displacement map from high-poly detail onto the low-poly UV space.

    For each UV-space pixel on the low-poly mesh a ray is shot along the
    surface normal.  The first intersection with the high-poly mesh gives the
    signed displacement scalar.

    This is the ZBrush HD Geometry baking workflow (cage projection method).

    Parameters
    ----------
    low_poly_positions : np.ndarray, shape (V_low, 3)
        Low-poly base mesh vertex positions (world units / mm).
    low_poly_triangles : np.ndarray, shape (F_low, 3)
        Low-poly triangle indices.
    low_poly_uv : np.ndarray, shape (V_low, 2) or None
        UV coordinates for the low-poly mesh (one per vertex, [0,1]²).
        If None, LSCM unwrap is computed automatically.
    high_poly_positions : np.ndarray, shape (V_high, 3)
        High-poly (sculpted) mesh vertex positions.
    high_poly_triangles : np.ndarray, shape (F_high, 3)
        High-poly triangle indices.
    map_resolution : int
        Output displacement map size (square).  Default 2048.
    max_distance_mm : float
        Maximum ray-casting distance; pixels with no hit within this range
        receive displacement = 0.

    Returns
    -------
    DisplacementMap
        ``scalar_field`` has shape (map_resolution, map_resolution); signed
        displacement in the same world units as the input positions.
    """
    from kerf_cad_core.geom.uv_unwrap import lscm_unwrap

    low_pos  = np.asarray(low_poly_positions,  dtype=np.float64)
    low_tri  = np.asarray(low_poly_triangles,  dtype=np.int32)
    high_pos = np.asarray(high_poly_positions, dtype=np.float64)
    high_tri = np.asarray(high_poly_triangles, dtype=np.int32)

    # UV for low-poly
    if low_poly_uv is None:
        mesh_dict = {"vertices": low_pos.tolist(), "faces": low_tri.tolist()}
        result = lscm_unwrap(mesh_dict)
        uv = np.asarray(result["uv"], dtype=np.float64)
    else:
        uv = np.asarray(low_poly_uv, dtype=np.float64)

    # Per-vertex normals for low-poly
    vert_normals = _vertex_normals(low_pos, low_tri)  # (V_low, 3)

    # High-poly triangle vertices (precomputed for ray-intersection)
    hp_v0 = high_pos[high_tri[:, 0]]
    hp_v1 = high_pos[high_tri[:, 1]]
    hp_v2 = high_pos[high_tri[:, 2]]

    S = float(map_resolution)
    disp_map = np.zeros((map_resolution, map_resolution), dtype=np.float32)

    # Collect all pixel sample positions and normals in UV space
    # For each low-poly triangle, rasterise UV-space and bake
    ray_origins_list = []
    ray_dirs_list    = []
    pixel_indices_list = []  # (row, col)

    for tri in low_tri:
        i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])

        # UV coords
        u0, v0_ = uv[i0]
        u1, v1_ = uv[i1]
        u2, v2_ = uv[i2]

        # Pixel coords (flip v)
        px = np.array([u0 * S, u1 * S, u2 * S])
        py = np.array([(1.0 - v0_) * S, (1.0 - v1_) * S, (1.0 - v2_) * S])

        x_min = max(0,                int(np.floor(px.min())))
        x_max = min(map_resolution-1, int(np.ceil(px.max())))
        y_min = max(0,                int(np.floor(py.min())))
        y_max = min(map_resolution-1, int(np.ceil(py.max())))

        if x_min > x_max or y_min > y_max:
            continue

        denom = (py[1] - py[2]) * (px[0] - px[2]) + (px[2] - px[1]) * (py[0] - py[2])
        if abs(denom) < 1e-10:
            continue

        cols = np.arange(x_min, x_max + 1)
        rows = np.arange(y_min, y_max + 1)
        cc, rr = np.meshgrid(cols, rows)
        px_c = cc.ravel().astype(np.float64) + 0.5
        py_c = rr.ravel().astype(np.float64) + 0.5

        w0 = ((py[1] - py[2]) * (px_c - px[2]) + (px[2] - px[1]) * (py_c - py[2])) / denom
        w1 = ((py[2] - py[0]) * (px_c - px[2]) + (px[0] - px[2]) * (py_c - py[2])) / denom
        w2 = 1.0 - w0 - w1

        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        idx_in = np.where(inside)[0]

        for k in idx_in:
            col_k = int(px_c[k])
            row_k = int(py_c[k])
            if col_k < 0 or col_k >= map_resolution or row_k < 0 or row_k >= map_resolution:
                continue

            ww0, ww1, ww2 = float(w0[k]), float(w1[k]), float(w2[k])

            # World-space position via barycentric interp
            world_p = ww0 * low_pos[i0] + ww1 * low_pos[i1] + ww2 * low_pos[i2]

            # Normal via barycentric interp (unnormalised)
            world_n = ww0 * vert_normals[i0] + ww1 * vert_normals[i1] + ww2 * vert_normals[i2]
            nlen = np.linalg.norm(world_n)
            if nlen < 1e-12:
                continue
            world_n = world_n / nlen

            ray_origins_list.append(world_p)
            ray_dirs_list.append(world_n)
            pixel_indices_list.append((row_k, col_k))

    if not ray_origins_list:
        return DisplacementMap(resolution=map_resolution, scalar_field=disp_map)

    ray_origins = np.stack(ray_origins_list)   # (N, 3)
    ray_dirs    = np.stack(ray_dirs_list)       # (N, 3)

    # Shoot rays both forward (+n) and backward (-n); take closest hit with sign
    t_fwd = _ray_triangle_intersect_batch(ray_origins, ray_dirs, hp_v0, hp_v1, hp_v2, max_distance_mm)
    t_bwd = _ray_triangle_intersect_batch(ray_origins, -ray_dirs, hp_v0, hp_v1, hp_v2, max_distance_mm)

    for k, (row_k, col_k) in enumerate(pixel_indices_list):
        tf = t_fwd[k]
        tb = t_bwd[k]

        if tf < np.inf and tb < np.inf:
            # Pick the one with smaller absolute t (closer surface)
            disp = float(tf) if tf <= tb else -float(tb)
        elif tf < np.inf:
            disp = float(tf)
        elif tb < np.inf:
            disp = -float(tb)
        else:
            disp = 0.0

        disp_map[row_k, col_k] = disp

    return DisplacementMap(resolution=map_resolution, scalar_field=disp_map)
