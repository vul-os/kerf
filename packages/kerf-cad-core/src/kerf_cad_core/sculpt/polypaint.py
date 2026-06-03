"""sculpt/polypaint.py — ZBrush PolyPaint equivalent: per-vertex colour + UV texture bake.

PolyPaint (Pixologic ZBrush 2025)
----------------------------------
PolyPaint stores an RGB colour value at each mesh vertex, independent of UV
coordinates.  Colour strokes use a radial falloff identical to the sculpt brush
falloff so the same pen metaphor applies.  When texture export is needed, the
per-vertex colours are *baked* into a texture image by rasterising each
triangle's vertex colours onto the UV-parameterised pixel grid.

Bake algorithm
--------------
1. If no UV coordinates are provided, compute LSCM UV unwrap (Lévy et al. 2002)
   via :func:`kerf_cad_core.geom.uv_unwrap.lscm_unwrap`.
2. For each triangle, project its UV-space corners into pixel coordinates.
3. Rasterise the triangle onto the texture using barycentric interpolation of
   the three vertex colours — equivalent to a GPU fragment shader.

References
----------
- Pixologic ZBrush 2025 PolyPaint documentation.
  https://docs.pixologic.com/reference-guide/tool/subtool/polypaint/
- Lévy, B., Petitjean, S., Ray, N. & Maillot, J. (2002). "Least Squares
  Conformal Maps for Automatic Texture Atlas Generation." SIGGRAPH, pp. 362-371.
- Sederberg, T.W. & Parry, S.R. (1986). "Free-form deformation of solid
  geometric models." SIGGRAPH, pp. 151-160. (Falloff / soft-selection concept.)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from kerf_cad_core.sculpt.brush import falloff_weight


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PolyPaintLayer:
    """A single PolyPaint colour layer.

    Attributes
    ----------
    vertex_colors : np.ndarray, shape (V, 3), float32
        Per-vertex RGB colours in [0, 1].
    opacity : float
        Layer opacity in [0, 1].  Colour strokes are blended with this factor.
    """

    vertex_colors: np.ndarray    # (V, 3) RGB float 0..1
    opacity: float = 1.0         # layer opacity 0..1


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def polypaint_stroke(
    mesh,
    layer: PolyPaintLayer,
    center: np.ndarray,
    radius: float,
    color: np.ndarray,
    falloff: str = "smooth",
) -> PolyPaintLayer:
    """Apply a single PolyPaint colour stroke to *layer*.

    Each vertex within *radius* of *center* has its colour blended toward
    *color* by a weight determined by the radial falloff function and the layer
    opacity.  Vertices outside *radius* are unchanged.

    The blend formula is:
        new_color[v] = lerp(old_color[v], color, weight * layer.opacity)
    where *weight* = falloff_weight(dist(v, center), radius, falloff).

    Parameters
    ----------
    mesh : any object with ``.positions`` attribute (np.ndarray (V,3)) OR
           a dict with key ``"vertices"`` (list[list[float]]).
    layer : PolyPaintLayer
        The colour layer to update.
    center : np.ndarray, shape (3,)
        World-space brush centre.
    radius : float
        Influence radius in world units (> 0).
    color : np.ndarray, shape (3,)
        Target RGB colour in [0, 1].
    falloff : str
        Falloff shape passed to :func:`~kerf_cad_core.sculpt.brush.falloff_weight`:
        ``"smooth"`` (cubic Hermite), ``"linear"``, or ``"constant"``.

    Returns
    -------
    PolyPaintLayer
        New layer with updated vertex colours (copy — original is not mutated).
    """
    # Resolve positions
    if hasattr(mesh, "positions"):
        positions = np.asarray(mesh.positions, dtype=np.float64)
    elif isinstance(mesh, dict):
        positions = np.asarray(mesh["vertices"], dtype=np.float64)
    else:
        positions = np.asarray(mesh, dtype=np.float64)

    center = np.asarray(center, dtype=np.float64)
    color  = np.clip(np.asarray(color, dtype=np.float32), 0.0, 1.0)

    dists = np.linalg.norm(positions - center[None, :], axis=1)  # (V,)

    new_colors = layer.vertex_colors.copy().astype(np.float32)

    for v_idx, dist in enumerate(dists):
        w = falloff_weight(float(dist), radius, falloff)
        if w <= 0.0:
            continue
        blend = w * float(layer.opacity)
        new_colors[v_idx] = (
            (1.0 - blend) * new_colors[v_idx] + blend * color
        )

    return PolyPaintLayer(vertex_colors=np.clip(new_colors, 0.0, 1.0), opacity=layer.opacity)


def bake_polypaint_to_uv_texture(
    mesh,
    polypaint: PolyPaintLayer,
    uv_coords: np.ndarray | None,
    texture_size: int = 512,
) -> np.ndarray:
    """Rasterise per-vertex PolyPaint colours into a UV texture image.

    For each triangle in *mesh*, the three vertex colours are interpolated
    across the triangle's UV-space footprint using barycentric coordinates,
    writing into a floating-point RGB texture.

    If *uv_coords* is None, LSCM UV unwrapping is computed automatically via
    :func:`~kerf_cad_core.geom.uv_unwrap.lscm_unwrap`.

    Parameters
    ----------
    mesh : SculptMesh / dict
        Triangle mesh.  Must have ``.positions`` and ``.triangles`` or dict
        keys ``"vertices"`` / ``"faces"``.
    polypaint : PolyPaintLayer
        Source vertex colours.
    uv_coords : np.ndarray, shape (V, 2) or None
        Explicit UV coordinates (one per vertex, in [0,1]²).  Pass None to
        trigger automatic LSCM unwrap.
    texture_size : int
        Output texture resolution (square).  Default 512.

    Returns
    -------
    np.ndarray, shape (texture_size, texture_size, 3), dtype float32
        RGB texture in [0, 1].
    """
    from kerf_cad_core.geom.uv_unwrap import lscm_unwrap

    # Resolve positions and triangles
    if hasattr(mesh, "positions"):
        positions = np.asarray(mesh.positions, dtype=np.float64)
        triangles = np.asarray(mesh.triangles, dtype=np.int32)
    elif isinstance(mesh, dict):
        positions = np.asarray(mesh["vertices"], dtype=np.float64)
        triangles = np.asarray(mesh["faces"], dtype=np.int32)
    else:
        raise TypeError("mesh must have .positions/.triangles or be a dict with 'vertices'/'faces'")

    V = len(positions)

    # UV coords
    if uv_coords is None:
        mesh_dict = {
            "vertices": positions.tolist(),
            "faces": triangles.tolist(),
        }
        result = lscm_unwrap(mesh_dict)
        uv = np.asarray(result["uv"], dtype=np.float64)
    else:
        uv = np.asarray(uv_coords, dtype=np.float64)

    # Validate
    if len(uv) != V:
        raise ValueError(f"uv_coords length {len(uv)} != vertex count {V}")

    colors = polypaint.vertex_colors.astype(np.float32)  # (V, 3)

    # Output texture (H, W, 3) — y axis = v (0 = bottom), stored top-to-bottom
    texture = np.zeros((texture_size, texture_size, 3), dtype=np.float32)
    # Coverage mask to avoid overwriting pixels that were already written
    coverage = np.zeros((texture_size, texture_size), dtype=bool)

    S = float(texture_size)

    for tri in triangles:
        i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])

        # UV positions in pixel space (column, row)
        u0, v0 = uv[i0]
        u1, v1 = uv[i1]
        u2, v2 = uv[i2]

        c0 = colors[i0]
        c1 = colors[i1]
        c2 = colors[i2]

        # Pixel-space (col, row) — flip v so v=0 → row = texture_size-1
        px = np.array([u0 * S, u1 * S, u2 * S])
        py = np.array([(1.0 - v0) * S, (1.0 - v1) * S, (1.0 - v2) * S])

        # Bounding box in pixel space
        x_min = max(0,             int(np.floor(px.min())))
        x_max = min(texture_size-1, int(np.ceil(px.max())))
        y_min = max(0,             int(np.floor(py.min())))
        y_max = min(texture_size-1, int(np.ceil(py.max())))

        if x_min > x_max or y_min > y_max:
            continue

        # Rasterise via barycentric test
        cols = np.arange(x_min, x_max + 1)
        rows = np.arange(y_min, y_max + 1)
        cc, rr = np.meshgrid(cols, rows)      # (R, C)
        px_c = cc.ravel().astype(np.float64) + 0.5
        py_c = rr.ravel().astype(np.float64) + 0.5

        # Barycentric weights (2D cross-product method)
        denom = (py[1] - py[2]) * (px[0] - px[2]) + (px[2] - px[1]) * (py[0] - py[2])
        if abs(denom) < 1e-10:
            continue

        w0 = ((py[1] - py[2]) * (px_c - px[2]) + (px[2] - px[1]) * (py_c - py[2])) / denom
        w1 = ((py[2] - py[0]) * (px_c - px[2]) + (px[0] - px[2]) * (py_c - py[2])) / denom
        w2 = 1.0 - w0 - w1

        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        idx_in = np.where(inside)[0]

        for k in idx_in:
            col_k = int(px_c[k])
            row_k = int(py_c[k])
            if col_k < 0 or col_k >= texture_size or row_k < 0 or row_k >= texture_size:
                continue
            ww0, ww1, ww2 = float(w0[k]), float(w1[k]), float(w2[k])
            interp = ww0 * c0 + ww1 * c1 + ww2 * c2
            texture[row_k, col_k] = np.clip(interp, 0.0, 1.0)
            coverage[row_k, col_k] = True

    return texture
