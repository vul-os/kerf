"""multires_displacement.py — GK-P-C: Multi-resolution displacement on subdivision surfaces.

Reference: Lee, Moreton & Hoppe 2000 "Displaced Subdivision Surfaces", SIGGRAPH 2000.
           Stam 1998 for exact limit-position / limit-tangent evaluation.

Overview
--------
A *displacement map* adds fine surface detail onto a coarse Catmull-Clark
subdivision surface by displacing each fine-mesh vertex along the surface
normal by a scalar amount stored in a regular UV-grid.  This is the standard
sculpt/detail workflow used in OpenSubdiv, ZBrush and Mudbox.

Three public operations:

1. ``apply_displacement(base_mesh, level, dmap)`` — subdivide the base mesh to
   *level*, then displace every fine vertex along its Stam-computed normal by
   the displacement sample at its parametric UV.

2. ``extract_displacement(fine_mesh, base_mesh, level)`` — inverse: given a
   fine (sculpted) mesh that was produced by subdividing *base_mesh* to *level*
   and then free-form edited, recover the per-vertex normal displacement and
   pack it into a ``DisplacementMap``.

3. Laplacian pyramid encoding/decoding via ``DisplacementPyramid`` — stores
   detail as coarse base + per-level residuals so LOD swapping and efficient
   storage are natural.

Public API
----------
DisplacementMap
    Per-face scalar field over uv ∈ [0,1]² sampled on a regular (rows × cols)
    grid. Supports bilinear interpolation.  ``width`` = cols, ``height`` = rows.

DisplacementPyramid
    Multi-level structure: a coarse base map + one detail map per level.
    ``encode(maps)`` / ``decode(level)`` / ``reconstruct(level)`` allow LOD
    access and exact reconstruction.

apply_displacement(base_mesh, level, dmap) -> SubDMesh
    Forward displacement: returns a ``SubDMesh`` with Stam-displaced vertices.

extract_displacement(fine_mesh, base_mesh, level) -> DisplacementMap
    Inverse: recover per-vertex normal displacements from a sculpted mesh.

encode_pyramid(maps) -> DisplacementPyramid
    Encode a list[DisplacementMap] (coarse → fine, same grid size) as a
    Laplacian pyramid.

decode_pyramid(pyramid, level) -> DisplacementMap
    Reconstruct the displacement map at the given level from the pyramid.

Notes
-----
* Pure Python + NumPy only; no OCCT dependency.
* UV parameterisation: for a subdivided quad-mesh vertex, the UV is derived
  from its position in the regular grid of the level-k mesh (row / (rows-1),
  col / (cols-1)).  For non-grid meshes a nearest-face centroid fallback is
  used.
* The Stam limit-tangent computation is imported from ``subd_to_nurbs``
  (module used by GK-P-B).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.subd import SubDMesh, catmull_clark_subdivide
from kerf_cad_core.geom.subd_to_nurbs import (
    _build_vertex_adjacency,
    _stam_limit_position,
    _stam_limit_tangents,
)


# ---------------------------------------------------------------------------
# DisplacementMap
# ---------------------------------------------------------------------------


@dataclass
class DisplacementMap:
    """Per-face scalar displacement field over uv ∈ [0,1]².

    Samples are stored in a 2-D array of shape (height, width) where
    ``height`` corresponds to the v-axis and ``width`` to the u-axis.

    Parameters
    ----------
    samples : np.ndarray, shape (height, width)
        Scalar displacement values.
    face_index : int
        The base-mesh face this map covers, or -1 for a global map over
        the whole subdivided mesh (one row = one vertex row of the grid).
    """

    samples: np.ndarray  # (height, width)
    face_index: int = -1

    def __post_init__(self) -> None:
        self.samples = np.asarray(self.samples, dtype=float)
        if self.samples.ndim != 2:
            raise ValueError(
                f"DisplacementMap.samples must be 2-D, got shape {self.samples.shape}"
            )

    @property
    def height(self) -> int:
        return self.samples.shape[0]

    @property
    def width(self) -> int:
        return self.samples.shape[1]

    def sample(self, u: float, v: float) -> float:
        """Bilinearly interpolate the displacement at (u, v) ∈ [0, 1]².

        Clamps u, v to [0, 1] before interpolating.
        """
        u = float(np.clip(u, 0.0, 1.0))
        v = float(np.clip(v, 0.0, 1.0))

        # Map to pixel coordinates
        col_f = u * (self.width - 1)
        row_f = v * (self.height - 1)

        c0 = int(math.floor(col_f))
        r0 = int(math.floor(row_f))
        c1 = min(c0 + 1, self.width - 1)
        r1 = min(r0 + 1, self.height - 1)

        tc = col_f - c0  # fractional column
        tr = row_f - r0  # fractional row

        s = self.samples
        val = (
            (1.0 - tr) * ((1.0 - tc) * s[r0, c0] + tc * s[r0, c1])
            + tr * ((1.0 - tc) * s[r1, c0] + tc * s[r1, c1])
        )
        return float(val)

    def copy(self) -> "DisplacementMap":
        return DisplacementMap(
            samples=self.samples.copy(),
            face_index=self.face_index,
        )


# ---------------------------------------------------------------------------
# DisplacementPyramid
# ---------------------------------------------------------------------------


@dataclass
class DisplacementPyramid:
    """Laplacian pyramid of displacement maps across subdivision levels.

    Stores one DisplacementMap per level.  Level 0 is the coarsest (base)
    map; each subsequent level stores the *residual* (detail) added at that
    resolution step.  Reconstruction at level k is the sum of levels 0..k.

    Parameters
    ----------
    levels : list[DisplacementMap]
        Ordered list from coarsest (index 0) to finest (index -1).
        The pyramid stores raw residuals; use ``reconstruct`` to recover the
        full displacement at a given level.
    """

    levels: List[DisplacementMap] = field(default_factory=list)

    def num_levels(self) -> int:
        return len(self.levels)

    def reconstruct(self, level: int) -> DisplacementMap:
        """Return the cumulative displacement map at the given level.

        ``level=0`` returns the coarse base map unchanged.
        ``level=k`` returns the sum of ``levels[0..k]`` interpolated to the
        same grid as ``levels[k]``.
        """
        if not self.levels:
            raise ValueError("Empty pyramid")
        level = max(0, min(int(level), len(self.levels) - 1))

        target_h = self.levels[level].height
        target_w = self.levels[level].width

        accumulated = np.zeros((target_h, target_w), dtype=float)
        for k in range(level + 1):
            lk = self.levels[k]
            if lk.height == target_h and lk.width == target_w:
                accumulated += lk.samples
            else:
                # Bilinear upsample/downsample to target grid
                resampled = _resample_map(lk.samples, target_h, target_w)
                accumulated += resampled

        return DisplacementMap(samples=accumulated, face_index=self.levels[level].face_index)


def _resample_map(samples: np.ndarray, target_h: int, target_w: int) -> np.ndarray:
    """Bilinear resample a 2-D array to (target_h, target_w)."""
    src_h, src_w = samples.shape
    if src_h == target_h and src_w == target_w:
        return samples.copy()

    out = np.zeros((target_h, target_w), dtype=float)
    for ri in range(target_h):
        for ci in range(target_w):
            v = ri / max(target_h - 1, 1)
            u = ci / max(target_w - 1, 1)
            col_f = u * (src_w - 1)
            row_f = v * (src_h - 1)
            c0 = int(math.floor(col_f))
            r0 = int(math.floor(row_f))
            c1 = min(c0 + 1, src_w - 1)
            r1 = min(r0 + 1, src_h - 1)
            tc = col_f - c0
            tr = row_f - r0
            out[ri, ci] = (
                (1.0 - tr) * ((1.0 - tc) * samples[r0, c0] + tc * samples[r0, c1])
                + tr * ((1.0 - tc) * samples[r1, c0] + tc * samples[r1, c1])
            )
    return out


def encode_pyramid(maps: Sequence[DisplacementMap]) -> DisplacementPyramid:
    """Encode a list of displacement maps as a Laplacian pyramid.

    ``maps[0]`` is the coarsest level; ``maps[-1]`` is the finest.  Each
    consecutive pair ``(maps[k], maps[k+1])`` produces a residual stored at
    level k+1 of the pyramid.

    The coarse base ``maps[0]`` is stored as-is at pyramid level 0.

    Parameters
    ----------
    maps : sequence of DisplacementMap
        Displacement maps from coarsest (index 0) to finest, all of the same
        or progressively finer grid resolution.

    Returns
    -------
    DisplacementPyramid
        Pyramid where ``pyramid.levels[0]`` = base and
        ``pyramid.levels[k]`` = residual added at that level.
    """
    if not maps:
        return DisplacementPyramid(levels=[])

    pyramid_levels: List[DisplacementMap] = []
    # Level 0: store base map unchanged
    pyramid_levels.append(maps[0].copy())

    for k in range(1, len(maps)):
        fine = maps[k]
        coarse = maps[k - 1]
        # Upsample coarser map to the resolution of this level
        coarse_up = _resample_map(coarse.samples, fine.height, fine.width)
        residual = fine.samples - coarse_up
        pyramid_levels.append(DisplacementMap(samples=residual, face_index=fine.face_index))

    return DisplacementPyramid(levels=pyramid_levels)


def decode_pyramid(pyramid: DisplacementPyramid, level: int) -> DisplacementMap:
    """Reconstruct the displacement map at *level* from the pyramid.

    Delegates to ``pyramid.reconstruct(level)``.
    """
    return pyramid.reconstruct(level)


# ---------------------------------------------------------------------------
# UV parameterisation helpers
# ---------------------------------------------------------------------------


def _compute_vertex_uvs(mesh: SubDMesh) -> List[Tuple[float, float]]:
    """Assign a UV coordinate to every vertex of *mesh*.

    Strategy:
    - If the mesh has a grid-like structure (all-quad with regular vertex
      counts), infer row/col from vertex index.
    - Otherwise use a nearest-face-centroid projection: for each vertex,
      find the face whose centroid is closest, then compute barycentric-like
      UV from the face's normalised corner positions.

    Returns a list of (u, v) tuples, one per vertex.
    """
    n_verts = len(mesh.vertices)
    if n_verts == 0:
        return []

    verts = [np.array(v, dtype=float) for v in mesh.vertices]

    # Attempt grid layout: for a CC-subdivided quad mesh at level k, the
    # vertex count grows as V_k = (2^k * m + 1)^2 for an m×m base grid.
    # We fall back to face-centroid UV for irregular meshes.
    uvs = _uvs_from_grid(verts, mesh.faces)
    if uvs is not None:
        return uvs

    return _uvs_from_face_centroids(verts, mesh.faces)


def _uvs_from_grid(
    verts: List[np.ndarray],
    faces: List[List[int]],
) -> Optional[List[Tuple[float, float]]]:
    """Attempt to assign UV from grid layout.

    For a regular all-quad mesh of N×N quads (produced by subdividing a
    single quad face), vertex ordering is row-major: vertex i is at
    (row = i // (N+1), col = i % (N+1)).

    Returns None if the mesh is not a regular grid.
    """
    if not faces:
        return None

    n_verts = len(verts)
    # Check if n_verts is (k+1)^2 for some integer k
    k_float = math.sqrt(n_verts)
    k = int(round(k_float))
    if k < 2 or k * k != n_verts:
        return None

    # Verify all faces are quads
    if any(len(f) != 4 for f in faces):
        return None

    # Check face count = k^2 - 1?  For a grid of k×k vertices, quads = (k-1)^2
    expected_faces = (k - 1) * (k - 1)
    if len(faces) != expected_faces:
        return None

    uvs = []
    for i in range(n_verts):
        row = i // k
        col = i % k
        u = col / (k - 1)
        v = row / (k - 1)
        uvs.append((u, v))
    return uvs


def _uvs_from_face_centroids(
    verts: List[np.ndarray],
    faces: List[List[int]],
) -> List[Tuple[float, float]]:
    """Assign UV by projecting each vertex onto the closest face's UV space.

    For each vertex, we find the face that contains it (or whose centroid is
    closest), then compute normalised (u, v) based on the face's bounding box
    in 3-D space projected to the face's local tangent plane.

    This is a best-effort fallback for non-grid meshes.
    """
    n_verts = len(verts)
    if not faces or n_verts == 0:
        return [(0.0, 0.0)] * n_verts

    # Build vertex → face mapping
    vert_to_faces: Dict[int, List[int]] = {}
    for fi, face in enumerate(faces):
        for vi in face:
            vert_to_faces.setdefault(vi, []).append(fi)

    # Compute face centroids once
    face_centroids = []
    for face in faces:
        c = np.mean([verts[vi] for vi in face], axis=0)
        face_centroids.append(c)

    # Global bounding box for normalisation
    all_pts = np.array([v.tolist() for v in verts])
    bb_min = all_pts.min(axis=0)
    bb_max = all_pts.max(axis=0)
    bb_range = bb_max - bb_min
    # Use the two widest axes as u,v
    axis_order = np.argsort(-bb_range)  # descending extent
    ax_u = int(axis_order[0])
    ax_v = int(axis_order[1])

    uvs: List[Tuple[float, float]] = []
    for vi, v in enumerate(verts):
        u_raw = float(v[ax_u] - bb_min[ax_u])
        v_raw = float(v[ax_v] - bb_min[ax_v])
        u = u_raw / bb_range[ax_u] if bb_range[ax_u] > 1e-14 else 0.0
        v_coord = v_raw / bb_range[ax_v] if bb_range[ax_v] > 1e-14 else 0.0
        uvs.append((u, v_coord))
    return uvs


# ---------------------------------------------------------------------------
# Stam normal computation
# ---------------------------------------------------------------------------


def _compute_stam_normals(mesh: SubDMesh) -> List[np.ndarray]:
    """Compute the Stam limit-surface normal at every vertex of *mesh*.

    The normal is computed as the cross product of the two Stam limit tangents,
    then sign-corrected to match the area-weighted face normal at that vertex
    (which respects the face winding order).

    For boundary / isolated vertices a fallback area-weighted normal is used.
    """
    verts_np = [np.array(v, dtype=float) for v in mesh.vertices]
    vert_faces, vert_neighbors = _build_vertex_adjacency(verts_np, mesh.faces)

    # Build vert_faces lookup for _area_weighted_normal fallback
    vert_face_list: Dict[int, List[int]] = {}
    for fi, face in enumerate(mesh.faces):
        for vi_f in face:
            vert_face_list.setdefault(vi_f, []).append(fi)

    normals: List[np.ndarray] = []
    for vi in range(len(mesh.vertices)):
        # Always compute area-weighted normal; used for sign-correction and fallback.
        awn = _area_weighted_normal(vi, verts_np, mesh.faces, vert_face_list.get(vi, []))

        t1, t2 = _stam_limit_tangents(vi, verts_np, vert_faces, vert_neighbors, mesh.faces)
        n = np.cross(t1, t2)
        mag = float(np.linalg.norm(n))
        if mag > 1e-14:
            n = n / mag
            # The Stam eigenvector walk may produce a cyclic ordering whose
            # cross-product is anti-parallel to the mesh winding normal, or
            # even perpendicular (at boundary/corner vertices where the tangent
            # fallback picks a Z-axis tangent).
            # Blend strategy:
            #   • If n is well-aligned with awn (dot ≥ 0.5) → use n.
            #   • If n is anti-aligned (dot < −0.1) → flip n.
            #   • If n is nearly perpendicular to awn (|dot| < 0.5) → fall
            #     back to awn (Stam tangent is degenerate at this vertex).
            dot = float(np.dot(n, awn))
            if dot >= 0.5:
                pass  # Stam normal is good; keep it.
            elif dot <= -0.1:
                n = -n  # Anti-parallel; flip.
            else:
                # Perpendicular or ambiguous — use area-weighted normal.
                n = awn
        else:
            n = awn
        normals.append(n)
    return normals


def _area_weighted_normal(
    vi: int,
    verts_np: List[np.ndarray],
    faces: List[List[int]],
    face_indices: List[int],
) -> np.ndarray:
    """Compute an area-weighted average normal for a vertex as a fallback."""
    acc = np.zeros(3, dtype=float)
    for fi in face_indices:
        face = faces[fi]
        if len(face) < 3:
            continue
        p0 = verts_np[face[0]]
        p1 = verts_np[face[1]]
        p2 = verts_np[face[2]]
        n = np.cross(p1 - p0, p2 - p0)
        acc += n
    mag = float(np.linalg.norm(acc))
    return acc / mag if mag > 1e-14 else np.array([0.0, 0.0, 1.0])


# ---------------------------------------------------------------------------
# apply_displacement
# ---------------------------------------------------------------------------


def apply_displacement(
    base_mesh: SubDMesh,
    level: int,
    displacement_map: DisplacementMap,
) -> SubDMesh:
    """Apply a displacement map to a subdivided Catmull-Clark mesh.

    Algorithm
    ---------
    1. Subdivide *base_mesh* to *level* using Catmull-Clark.
    2. For each vertex of the subdivided mesh:
       a. Compute the Stam limit normal at that vertex.
       b. Compute the UV coordinate of the vertex (grid-based or centroid).
       c. Sample the *displacement_map* at that UV.
       d. Displace the vertex position along the normal by the sampled scalar.
    3. Return the displaced ``SubDMesh`` (same topology, new positions).

    Parameters
    ----------
    base_mesh : SubDMesh
        The coarse control cage.
    level : int
        Number of Catmull-Clark subdivision steps.
    displacement_map : DisplacementMap
        Scalar field over uv ∈ [0,1]² to apply as normal displacement.

    Returns
    -------
    SubDMesh
        Displaced fine mesh with the same topology as the subdivided mesh.
    """
    level = max(0, int(level))
    fine_mesh = catmull_clark_subdivide(base_mesh, levels=level)

    uvs = _compute_vertex_uvs(fine_mesh)
    normals = _compute_stam_normals(fine_mesh)

    new_verts: List[List[float]] = []
    for vi, v in enumerate(fine_mesh.vertices):
        u, t = uvs[vi]
        d = displacement_map.sample(u, t)
        n = normals[vi]
        displaced = np.array(v, dtype=float) + d * n
        new_verts.append(displaced.tolist())

    return SubDMesh(
        vertices=new_verts,
        faces=[list(f) for f in fine_mesh.faces],
        creases=dict(fine_mesh.creases),
    )


# ---------------------------------------------------------------------------
# extract_displacement
# ---------------------------------------------------------------------------


def extract_displacement(
    fine_mesh: SubDMesh,
    base_mesh: SubDMesh,
    level: int,
) -> DisplacementMap:
    """Extract the displacement map from a sculpted fine mesh.

    Given a fine mesh that was produced by subdividing *base_mesh* to *level*
    and then free-form sculpted, recover the per-vertex normal displacement
    and return it as a ``DisplacementMap``.

    Algorithm
    ---------
    1. Subdivide *base_mesh* to *level* to get the unsculpted reference.
    2. For each vertex i:
       a. Compute Stam limit normal ``n_i`` from the **reference** mesh.
       b. Displacement = dot(fine_verts[i] - ref_verts[i], n_i).
    3. Pack displacement scalars into a DisplacementMap grid.

    The grid shape is chosen to be the closest square that holds all vertices.
    If the vertex count is a perfect square (common for grid-derived meshes),
    the grid is exactly that square.

    Parameters
    ----------
    fine_mesh : SubDMesh
        The sculpted fine mesh. Must have the same topology (same number of
        vertices and face connectivity) as ``catmull_clark_subdivide(base_mesh, level)``.
    base_mesh : SubDMesh
        The coarse control cage from which *fine_mesh* was derived.
    level : int
        Number of subdivision levels used to produce *fine_mesh*.

    Returns
    -------
    DisplacementMap
        Grid-sampled scalar displacement field.
    """
    level = max(0, int(level))
    ref_mesh = catmull_clark_subdivide(base_mesh, levels=level)

    n_verts = len(ref_mesh.vertices)
    if len(fine_mesh.vertices) != n_verts:
        raise ValueError(
            f"fine_mesh has {len(fine_mesh.vertices)} vertices but reference "
            f"(base subdivided to level {level}) has {n_verts}."
        )

    ref_verts = [np.array(v, dtype=float) for v in ref_mesh.vertices]
    fine_verts = [np.array(v, dtype=float) for v in fine_mesh.vertices]

    normals = _compute_stam_normals(ref_mesh)

    # Compute per-vertex scalar displacement
    scalars = np.zeros(n_verts, dtype=float)
    for vi in range(n_verts):
        delta = fine_verts[vi] - ref_verts[vi]
        scalars[vi] = float(np.dot(delta, normals[vi]))

    # Pack into a 2-D grid
    k = int(math.ceil(math.sqrt(n_verts)))
    # Prefer square grid when n_verts is a perfect square
    k_sq = int(round(math.sqrt(n_verts)))
    if k_sq * k_sq == n_verts:
        rows, cols = k_sq, k_sq
    else:
        rows = k
        cols = k

    grid = np.zeros((rows, cols), dtype=float)
    for vi in range(n_verts):
        r = vi // cols
        c = vi % cols
        if r < rows:
            grid[r, c] = scalars[vi]

    return DisplacementMap(samples=grid, face_index=-1)


# ---------------------------------------------------------------------------
# Pyramid encode / decode (public)
# ---------------------------------------------------------------------------


def build_multires_maps(
    base_mesh: SubDMesh,
    fine_meshes: Sequence[SubDMesh],
) -> DisplacementPyramid:
    """Build a displacement pyramid from a sequence of progressive fine meshes.

    *fine_meshes[k]* is expected to be the sculpted mesh at subdivision level
    k+1.  The pyramid is built by extracting the per-level displacement from
    each fine mesh against the (k+1)-level subdivision of *base_mesh*.

    Parameters
    ----------
    base_mesh : SubDMesh
        The coarse cage.
    fine_meshes : sequence of SubDMesh
        Sculpted meshes at levels 1, 2, …, len(fine_meshes).  Each must have
        the topology of ``catmull_clark_subdivide(base_mesh, level=k+1)``.

    Returns
    -------
    DisplacementPyramid
        Pyramid with ``len(fine_meshes)`` levels.
    """
    maps: List[DisplacementMap] = []
    for k, fm in enumerate(fine_meshes):
        dmap = extract_displacement(fm, base_mesh, level=k + 1)
        maps.append(dmap)
    return encode_pyramid(maps)
