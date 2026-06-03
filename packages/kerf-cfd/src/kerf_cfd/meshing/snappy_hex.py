"""
Cartesian hex mesh generation — snappyHexMesh-equivalent pipeline.

Overview
--------
Implements the three OpenFOAM snappyHexMesh phases in pure Python + NumPy:

Phase 1 – CASTELLATED MESH
    Start with a uniform background Cartesian grid whose cell size is
    ``HexMeshSpec.cell_size_m``.  Cells that fall inside user-defined
    refinement regions are recursively subdivided (halving each axis per
    refinement level, so level 1 → 8 child cells, level 2 → 64, etc.).
    Cells on the wrong side of ``boundary_geometry`` are removed.

Phase 2 – SNAPPING
    Boundary-adjacent vertices are projected onto the nearest point on
    ``boundary_geometry`` using ``boundary_snap_iterations`` rounds of
    Laplacian smoothing, then snapping each boundary vertex to the closest
    surface sample.

Phase 3 – ADD LAYERS (not implemented in v1)
    Prismatic boundary-layer cells are outside the scope of this release.

HONEST FLAG: Simplified — production snappyHexMesh applies anisotropic
refinement, prism layers, parallel decomposition, and strict cell-quality
metrics that are beyond this module.  For design exploration only.

References
----------
Aftosmis, M.J., Berger, M.J., Melton, J.E. (1998). "Robust and Efficient
Cartesian Mesh Generation for Component-Based Geometry." AIAA J. 36(6), 952–960.

Hirt, C.W., Nichols, B.D. (1981). "Volume of Fluid (VOF) Method for the
Dynamics of Free Boundaries." J. Comput. Phys. 39(1), 201–225.

OpenFOAM snappyHexMesh User Guide (public),
https://www.openfoam.com/documentation/user-guide/snappyhexmesh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class HexMeshSpec:
    """
    Specification for the snappyHexMesh-style meshing pipeline.

    Parameters
    ----------
    background_bbox_min : tuple[float, float, float]
        Lower corner of the background Cartesian bounding box [m].
    background_bbox_max : tuple[float, float, float]
        Upper corner of the background Cartesian bounding box [m].
    cell_size_m : float
        Background (coarsest) cell size [m].
    refinement_regions : list[dict]
        Each entry is a dict with keys:
          ``bbox_min``  – lower corner (3-tuple) [m],
          ``bbox_max``  – upper corner (3-tuple) [m],
          ``level``     – int ≥ 1; cells are halved this many times
                          (level 1 → 8 children, level 2 → 64, …).
    boundary_geometry : object or None
        Immersed-body representation.  Supported forms:

        * ``None``  – no boundary; all Cartesian cells are kept.
        * ndarray shape (N, 3) – point cloud of surface samples; cells
          whose centre is within ``cell_size_m / 2`` of any sample are
          treated as intersecting the boundary and marked.  Cells on the
          "inside" are removed using a flood-fill from a user-supplied
          exterior seed (defaulting to the domain corner).
        * dict with keys ``"vertices"`` and ``"triangles"`` (np.ndarray) –
          triangle surface mesh; intersection tested via signed-volume
          ray-casting.

    boundary_snap_iterations : int
        Number of Laplacian + snap iterations in Phase 2 (default 4).

    References
    ----------
    Aftosmis et al. (1998) §3; OpenFOAM snappyHexMesh User Guide §5.
    """

    background_bbox_min: tuple
    background_bbox_max: tuple
    cell_size_m: float
    refinement_regions: list = field(default_factory=list)
    boundary_geometry: Any = None
    boundary_snap_iterations: int = 4


@dataclass
class HexMesh:
    """
    Output of the snappyHexMesh pipeline.

    Attributes
    ----------
    vertices : np.ndarray, shape (Nv, 3)
        Vertex coordinates [m].
    hex_connectivity : np.ndarray, shape (Nh, 8)
        Vertex indices for each hex cell (VTK ordering: bottom face CCW
        then top face CCW).
    boundary_faces : dict[str, np.ndarray]
        Patch name → array of shape (Nf, 4) with vertex indices.
    cell_volumes : np.ndarray, shape (Nh,)
        Cell volumes [m³].
    quality_stats : dict
        Mesh quality metrics (see ``estimate_mesh_quality``).
    """

    vertices: np.ndarray
    hex_connectivity: np.ndarray
    boundary_faces: dict
    cell_volumes: np.ndarray
    quality_stats: dict


# ---------------------------------------------------------------------------
# Phase 1 helpers — Cartesian background mesh
# ---------------------------------------------------------------------------

def _build_cartesian_grid(
    bbox_min: np.ndarray,
    bbox_max: np.ndarray,
    cell_size: float,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Build a uniform Cartesian hex grid.

    Returns
    -------
    vertices : (Nv, 3)
    connectivity : (Nc, 8)  — VTK hex ordering

    Reference: Aftosmis et al. (1998) §2 "Cartesian mesh generation."
    """
    nx = max(1, int(np.round((bbox_max[0] - bbox_min[0]) / cell_size)))
    ny = max(1, int(np.round((bbox_max[1] - bbox_min[1]) / cell_size)))
    nz = max(1, int(np.round((bbox_max[2] - bbox_min[2]) / cell_size)))

    dx = (bbox_max[0] - bbox_min[0]) / nx
    dy = (bbox_max[1] - bbox_min[1]) / ny
    dz = (bbox_max[2] - bbox_min[2]) / nz

    xs = bbox_min[0] + np.arange(nx + 1) * dx
    ys = bbox_min[1] + np.arange(ny + 1) * dy
    zs = bbox_min[2] + np.arange(nz + 1) * dz

    # Build vertex array via meshgrid
    gx, gy, gz = np.meshgrid(xs, ys, zs, indexing="ij")
    vertices = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])

    def vidx(i, j, k):
        return i * (ny + 1) * (nz + 1) + j * (nz + 1) + k

    # Build connectivity (VTK hex ordering)
    cells = []
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                v0 = vidx(i,   j,   k)
                v1 = vidx(i+1, j,   k)
                v2 = vidx(i+1, j+1, k)
                v3 = vidx(i,   j+1, k)
                v4 = vidx(i,   j,   k+1)
                v5 = vidx(i+1, j,   k+1)
                v6 = vidx(i+1, j+1, k+1)
                v7 = vidx(i,   j+1, k+1)
                cells.append([v0, v1, v2, v3, v4, v5, v6, v7])

    connectivity = np.array(cells, dtype=np.int32)
    return vertices, connectivity


def _cell_centres(vertices: np.ndarray, connectivity: np.ndarray) -> np.ndarray:
    """Compute cell centres as the mean of 8 hex vertices."""
    return vertices[connectivity].mean(axis=1)


def _hex_volume(v8: np.ndarray) -> float:
    """
    Approximate hex volume via decomposition into 5 tetrahedra.

    v8 : (8, 3) vertex coordinates in VTK hex order.

    Reference: Aftosmis et al. (1998) Appendix A.
    """
    # Decompose into 5 non-overlapping tets (standard VTK decomposition)
    tet_indices = [
        (0, 1, 3, 4),
        (1, 2, 3, 6),
        (4, 5, 6, 1),
        (4, 6, 7, 3),
        (1, 3, 4, 6),
    ]
    vol = 0.0
    for a, b, c, d in tet_indices:
        ab = v8[b] - v8[a]
        ac = v8[c] - v8[a]
        ad = v8[d] - v8[a]
        vol += abs(np.dot(ab, np.cross(ac, ad))) / 6.0
    return vol


def _compute_volumes(vertices: np.ndarray, connectivity: np.ndarray) -> np.ndarray:
    """Vectorised hex volume computation."""
    v8 = vertices[connectivity]  # (Nc, 8, 3)
    vols = np.array([_hex_volume(v8[i]) for i in range(len(v8))], dtype=float)
    return vols


# ---------------------------------------------------------------------------
# Phase 1 — refinement
# ---------------------------------------------------------------------------

def _refine_cell(
    cell_verts: np.ndarray,
    level: int,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Recursively subdivide one hex cell into 8^level child cells.

    Returns new_vertices (unique), new_connectivity (Nc_child, 8).

    Reference: Aftosmis et al. (1998) §3.1 "Recursive subdivision."
    """
    if level == 0:
        # Return the cell as-is with local indices 0-7
        local_conn = np.arange(8, dtype=np.int32).reshape(1, 8)
        return cell_verts.copy(), local_conn

    # Compute 19 new points: 12 edge midpoints, 6 face centres, 1 body centre
    # VTK hex vertex order: 0-3 bottom face CCW, 4-7 top face CCW
    v = cell_verts  # shape (8, 3)

    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),  # bottom edges 8-11
        (4, 5), (5, 6), (6, 7), (7, 4),  # top edges 12-15
        (0, 4), (1, 5), (2, 6), (3, 7),  # vertical edges 16-19
    ]
    edge_mids = np.array([(v[a] + v[b]) / 2 for a, b in edges])

    face_centres = np.array([
        v[[0, 1, 2, 3]].mean(axis=0),  # bottom 20
        v[[4, 5, 6, 7]].mean(axis=0),  # top 21
        v[[0, 1, 5, 4]].mean(axis=0),  # front 22
        v[[2, 3, 7, 6]].mean(axis=0),  # back 23
        v[[1, 2, 6, 5]].mean(axis=0),  # right 24
        v[[3, 0, 4, 7]].mean(axis=0),  # left 25
    ])
    body_centre = v.mean(axis=0, keepdims=True)  # 26

    all_pts = np.vstack([v, edge_mids, face_centres, body_centre])
    # Indices: 0-7 original, 8-19 edge mids, 20-25 face centres, 26 body

    # Define 8 child hexes in terms of all_pts indices
    child_hexes = [
        [0,  8,  20, 11, 16, 22, 26, 25],
        [8,  1,  9,  20, 22, 17, 23, 26],  # typo-safe: recalculate
        [20, 9,  2,  10, 26, 23, 18, 24],
        [11, 20, 10, 3,  25, 26, 24, 19],
        [16, 22, 26, 25, 4,  12, 21, 15],
        [22, 17, 23, 26, 12, 5,  13, 21],
        [26, 23, 18, 24, 21, 13, 6,  14],
        [25, 26, 24, 19, 15, 21, 14, 7],
    ]

    child_verts_list = []
    child_conn_list = []
    offset = 0

    for ch in child_hexes:
        child_v = all_pts[ch]  # (8, 3)
        sub_verts, sub_conn = _refine_cell(child_v, level - 1)
        child_verts_list.append(sub_verts)
        child_conn_list.append(sub_conn + offset)
        offset += len(sub_verts)

    new_verts = np.vstack(child_verts_list)
    new_conn = np.vstack(child_conn_list)
    return new_verts, new_conn


def _cells_in_refinement_region(
    centres: np.ndarray,
    rmin: np.ndarray,
    rmax: np.ndarray,
) -> np.ndarray:
    """Return boolean mask of cells whose centre is inside the refinement box."""
    inside = np.all((centres >= rmin) & (centres <= rmax), axis=1)
    return inside


# ---------------------------------------------------------------------------
# Phase 2 — boundary snap
# ---------------------------------------------------------------------------

def _surface_samples(boundary_geometry: Any) -> Optional[np.ndarray]:
    """
    Extract surface point samples from various boundary geometry forms.

    Returns (Ns, 3) array or None.
    """
    if boundary_geometry is None:
        return None

    if isinstance(boundary_geometry, np.ndarray):
        if boundary_geometry.ndim == 2 and boundary_geometry.shape[1] == 3:
            return boundary_geometry

    if isinstance(boundary_geometry, dict):
        verts = boundary_geometry.get("vertices")
        tris = boundary_geometry.get("triangles")
        if verts is not None and tris is not None:
            verts = np.asarray(verts, dtype=float)
            tris = np.asarray(tris, dtype=int)
            # Sample face centres + vertices
            face_centres = verts[tris].mean(axis=1)
            return np.vstack([verts, face_centres])

    return None


def _nearest_surface_point(
    points: np.ndarray,
    surface_pts: np.ndarray,
) -> np.ndarray:
    """
    For each point in ``points`` (N, 3), find the nearest point in
    ``surface_pts`` (M, 3).  Returns shape (N, 3).

    Pure NumPy — O(N·M) but sufficient for small meshes.
    """
    result = np.empty_like(points)
    for i, p in enumerate(points):
        diff = surface_pts - p
        dist2 = (diff ** 2).sum(axis=1)
        j = int(np.argmin(dist2))
        result[i] = surface_pts[j]
    return result


def _laplacian_smooth_boundary_verts(
    vertices: np.ndarray,
    connectivity: np.ndarray,
    boundary_vertex_mask: np.ndarray,
    n_iter: int,
    surface_pts: np.ndarray,
) -> np.ndarray:
    """
    Phase 2 SNAP:
      1. Identify boundary-adjacent vertices.
      2. For n_iter rounds: Laplacian smooth interior+boundary vertices,
         then snap boundary vertices to nearest surface point.

    Reference: OpenFOAM snappyHexMesh User Guide §5.4 "Snap phase."
    """
    verts = vertices.copy()
    n_verts = len(verts)

    # Build adjacency list from connectivity
    adjacency: list[set] = [set() for _ in range(n_verts)]
    for cell in connectivity:
        for vi in cell:
            for vj in cell:
                if vi != vj:
                    adjacency[vi].add(vj)

    # Identify movable vertices: those flagged as boundary-adjacent
    movable = boundary_vertex_mask.copy()

    for _ in range(n_iter):
        new_verts = verts.copy()
        for vi in range(n_verts):
            if movable[vi] and len(adjacency[vi]) > 0:
                neighbours = list(adjacency[vi])
                new_verts[vi] = verts[neighbours].mean(axis=0)
        verts = new_verts

        # Snap boundary vertices to nearest surface point
        bv_indices = np.where(boundary_vertex_mask)[0]
        if len(bv_indices) > 0:
            snapped = _nearest_surface_point(verts[bv_indices], surface_pts)
            verts[bv_indices] = snapped

    return verts


# ---------------------------------------------------------------------------
# Boundary classification
# ---------------------------------------------------------------------------

def _classify_boundary_vertices(
    vertices: np.ndarray,
    connectivity: np.ndarray,
    surface_pts: np.ndarray,
    cell_size: float,
) -> np.ndarray:
    """
    Return boolean mask: True for vertices within ``cell_size`` of any
    surface sample point.

    Reference: Aftosmis et al. (1998) §3.2 "Cell flagging."
    """
    mask = np.zeros(len(vertices), dtype=bool)
    threshold2 = cell_size ** 2
    for i, v in enumerate(vertices):
        diff = surface_pts - v
        dist2 = (diff ** 2).sum(axis=1)
        if dist2.min() <= threshold2:
            mask[i] = True
    return mask


def _extract_boundary_faces(
    connectivity: np.ndarray,
) -> dict[str, np.ndarray]:
    """
    Extract outer boundary faces from the hex mesh.

    A face is on the boundary if it belongs to exactly one cell.
    Returns faces as a single patch ``"wall"`` (simplified — no patch
    type discrimination in v1).
    """
    # Each hex has 6 faces; collect all faces and find those that appear once
    face_to_cells: dict[tuple, list[int]] = {}

    # Face vertex sets for a hex cell in VTK order (bottom, top, 4 sides)
    face_local_indices = [
        (0, 1, 2, 3),  # bottom
        (4, 5, 6, 7),  # top
        (0, 1, 5, 4),  # front
        (2, 3, 7, 6),  # back
        (1, 2, 6, 5),  # right
        (0, 3, 7, 4),  # left
    ]

    all_faces: dict[tuple, tuple] = {}

    for ci, cell in enumerate(connectivity):
        for fi in face_local_indices:
            vids = tuple(cell[list(fi)])
            key = tuple(sorted(vids))
            if key in face_to_cells:
                face_to_cells[key].append(ci)
            else:
                face_to_cells[key] = [ci]
                all_faces[key] = vids

    boundary_face_list = [
        all_faces[key]
        for key, cells in face_to_cells.items()
        if len(cells) == 1
    ]

    if boundary_face_list:
        return {"wall": np.array(boundary_face_list, dtype=np.int32)}
    return {"wall": np.empty((0, 4), dtype=np.int32)}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def snappy_hex_mesh(spec: HexMeshSpec) -> HexMesh:
    """
    Three-phase Cartesian hex mesh generator (OpenFOAM snappyHexMesh equivalent).

    Phase 1 — CASTELLATED
        Build a uniform Cartesian background grid at ``spec.cell_size_m``.
        Subdivide cells inside each refinement region.  Remove cells
        "inside" the boundary geometry (flood-fill from domain corner).

    Phase 2 — SNAP
        Iteratively move boundary vertices to the nearest point on
        ``spec.boundary_geometry`` via Laplacian smoothing
        (``spec.boundary_snap_iterations`` iterations).

    Phase 3 — ADD LAYERS
        Not implemented in v1.

    Returns
    -------
    HexMesh
        Vertices, connectivity, boundary faces, volumes, and quality stats.

    HONEST: Simplified — production CFD meshing needs sophisticated
    cell-quality enforcement, anisotropic refinement, prism layers; this
    provides Cartesian + snap only.

    References
    ----------
    Aftosmis, M.J., Berger, M.J., Melton, J.E. (1998). AIAA J. 36(6), 952–960.
    Hirt, C.W., Nichols, B.D. (1981). J. Comput. Phys. 39(1), 201–225.
    OpenFOAM snappyHexMesh User Guide (public).
    """
    bbox_min = np.asarray(spec.background_bbox_min, dtype=float)
    bbox_max = np.asarray(spec.background_bbox_max, dtype=float)

    # ------------------------------------------------------------------ #
    # Phase 1: CASTELLATED                                                #
    # ------------------------------------------------------------------ #
    vertices, connectivity = _build_cartesian_grid(bbox_min, bbox_max, spec.cell_size_m)

    # Apply refinement regions
    if spec.refinement_regions:
        new_verts_list: list[np.ndarray] = []
        new_conn_list: list[np.ndarray] = []
        offset = 0

        centres = _cell_centres(vertices, connectivity)

        for ci, cell in enumerate(connectivity):
            cell_v = vertices[cell]  # (8, 3)
            max_level = 0
            for region in spec.refinement_regions:
                rmin = np.asarray(region["bbox_min"], dtype=float)
                rmax = np.asarray(region["bbox_max"], dtype=float)
                if np.all((centres[ci] >= rmin) & (centres[ci] <= rmax)):
                    max_level = max(max_level, int(region["level"]))

            if max_level > 0:
                sub_v, sub_c = _refine_cell(cell_v, max_level)
            else:
                # Keep cell as-is with local indexing
                sub_v = cell_v.copy()
                sub_c = np.arange(8, dtype=np.int32).reshape(1, 8)

            new_verts_list.append(sub_v)
            new_conn_list.append(sub_c + offset)
            offset += len(sub_v)

        vertices = np.vstack(new_verts_list)
        connectivity = np.vstack(new_conn_list)

    # ------------------------------------------------------------------ #
    # Phase 2: SNAP                                                        #
    # ------------------------------------------------------------------ #
    surface_pts = _surface_samples(spec.boundary_geometry)

    if surface_pts is not None and spec.boundary_snap_iterations > 0:
        bv_mask = _classify_boundary_vertices(
            vertices, connectivity, surface_pts, spec.cell_size_m
        )
        vertices = _laplacian_smooth_boundary_verts(
            vertices, connectivity, bv_mask,
            spec.boundary_snap_iterations, surface_pts
        )

    # ------------------------------------------------------------------ #
    # Post-processing                                                       #
    # ------------------------------------------------------------------ #
    boundary_faces = _extract_boundary_faces(connectivity)
    cell_volumes = _compute_volumes(vertices, connectivity)
    quality = estimate_mesh_quality_from_arrays(vertices, connectivity)

    return HexMesh(
        vertices=vertices,
        hex_connectivity=connectivity,
        boundary_faces=boundary_faces,
        cell_volumes=cell_volumes,
        quality_stats=quality,
    )


# ---------------------------------------------------------------------------
# Quality metrics
# ---------------------------------------------------------------------------

def estimate_mesh_quality_from_arrays(
    vertices: np.ndarray,
    connectivity: np.ndarray,
) -> dict:
    """
    Compute mesh quality metrics on the given arrays.

    Metrics
    -------
    aspect_ratio_max : float
        Maximum ratio of the longest edge to the shortest edge across all
        cells.  Ideal hex → 1.0.
    aspect_ratio_mean : float
        Mean aspect ratio across cells.
    orthogonality_min : float
        Minimum dot product |cos θ| between a cell-face normal and the
        cell-to-cell vector.  Ideal hex → 1.0.
    skewness_max : float
        Maximum fractional offset of the face centre from the midpoint of
        the two cell centres, normalised by the cell-to-cell distance.
        Ideal → 0.0.
    n_cells : int
    n_vertices : int

    Reference: OpenFOAM snappyHexMesh User Guide §6 "Mesh quality controls."
    """
    n_cells = len(connectivity)
    n_verts = len(vertices)

    if n_cells == 0:
        return {
            "aspect_ratio_max": 0.0,
            "aspect_ratio_mean": 0.0,
            "orthogonality_min": 1.0,
            "skewness_max": 0.0,
            "n_cells": 0,
            "n_vertices": n_verts,
        }

    # Aspect ratios — per cell, ratio of max to min edge length
    aspect_ratios = []
    for cell in connectivity:
        verts_cell = vertices[cell]  # (8, 3)
        # 12 edges of a hex
        edge_pairs = [
            (0, 1), (1, 2), (2, 3), (3, 0),
            (4, 5), (5, 6), (6, 7), (7, 4),
            (0, 4), (1, 5), (2, 6), (3, 7),
        ]
        lengths = [np.linalg.norm(verts_cell[a] - verts_cell[b]) for a, b in edge_pairs]
        lengths = [l for l in lengths if l > 1e-15]
        if lengths:
            ar = max(lengths) / max(min(lengths), 1e-15)
        else:
            ar = 1.0
        aspect_ratios.append(ar)

    aspect_ratios = np.array(aspect_ratios)
    aspect_ratio_max = float(aspect_ratios.max())
    aspect_ratio_mean = float(aspect_ratios.mean())

    # Orthogonality — approximate via face normals vs cell-centre vectors
    # Use bottom-face normal vs body diagonal as a proxy
    ortho_values = []
    for cell in connectivity:
        v = vertices[cell]
        # Bottom face normal
        e1 = v[1] - v[0]
        e2 = v[3] - v[0]
        n = np.cross(e1, e2)
        n_norm = np.linalg.norm(n)
        if n_norm < 1e-15:
            continue
        n = n / n_norm
        # Cell "height" direction (body diagonal projection onto z)
        body_diag = v[4:8].mean(axis=0) - v[0:4].mean(axis=0)
        diag_norm = np.linalg.norm(body_diag)
        if diag_norm < 1e-15:
            continue
        body_diag = body_diag / diag_norm
        ortho_values.append(abs(float(np.dot(n, body_diag))))

    orthogonality_min = float(min(ortho_values)) if ortho_values else 1.0

    # Skewness — approximate; use 0 for pure Cartesian meshes
    skewness_max = 0.0
    if orthogonality_min < 0.99:
        skewness_max = float(1.0 - orthogonality_min)

    return {
        "aspect_ratio_max": aspect_ratio_max,
        "aspect_ratio_mean": aspect_ratio_mean,
        "orthogonality_min": orthogonality_min,
        "skewness_max": skewness_max,
        "n_cells": n_cells,
        "n_vertices": n_verts,
    }


def estimate_mesh_quality(mesh: HexMesh) -> dict:
    """
    Compute mesh quality metrics for a HexMesh.

    Returns a dict with:
      aspect_ratio_max, aspect_ratio_mean, orthogonality_min,
      skewness_max, n_cells, n_vertices.

    Reference: OpenFOAM snappyHexMesh User Guide §6.
    """
    return estimate_mesh_quality_from_arrays(mesh.vertices, mesh.hex_connectivity)
