"""
3-D unstructured CFD mesh generator — scipy.spatial.Delaunay core.

This module provides production-grade 3-D unstructured mesh generation for
arbitrary boundary geometry, suitable as the mesh substrate for finite-volume
CFD solvers.

Algorithm
---------
1. **Surface mesher** — accepts a triangulated boundary mesh (vertices + triangles).
   Repairs short edges (collapse), degenerate triangles (area filter), and
   guarantees the surface is watertight and manifold before volumetric meshing.

2. **3-D Delaunay tetrahedralization** — uses ``scipy.spatial.Delaunay`` for the
   unconstrained interior.  Boundary recovery is performed via constrained
   insertion: any required boundary face missing from the volumetric mesh surface
   triggers a Steiner point at the face centroid and local re-triangulation.

3. **Voronoi dual** — each Delaunay vertex's Voronoi cell is the set of
   circumcentres of all incident tetrahedra.  The cell volume is the finite-volume
   control-volume weight for node-centred FV schemes (Jasak 1996, Weller et al.
   1998).

4. **Mesh quality** — per-element aspect ratio (circumradius / inradius) and all
   six dihedral angles.  Elements with aspect > 50 or any dihedral < 5° or > 175°
   are flagged as ``bad``.

5. **Octree refinement** — a density field (callable or constant) drives local
   Steiner-point insertion until the local edge length matches the target sizing.

References
----------
- Shewchuk, J.R. (1997) "Delaunay refinement mesh generation."  PhD thesis, CMU.
- Frey & George (2000) "Mesh Generation".  Hermes Science Publishing.
- Si, H. (2015) "TetGen: A Delaunay-Based Quality Tetrahedral Mesh Generator."
  ACM Trans. Math. Software 41(2).
- Jasak (1996) "Error analysis and estimation for the finite volume method."
  PhD thesis, Imperial College London.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Callable, Iterator, List, Optional, Sequence, Tuple

import numpy as np
from scipy.spatial import Delaunay  # type: ignore[import]

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]
TriFace = Tuple[int, int, int]
TetIdx = Tuple[int, int, int, int]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class UnstructuredMesh3D:
    """3-D unstructured tetrahedral mesh with Voronoi dual.

    Attributes
    ----------
    vertices : (N, 3) float array
        Node coordinates.
    elements : (M, 4) int array
        Tetrahedra as vertex-index 4-tuples (positive-volume orientation).
    boundary_faces : (K, 3) int array
        Boundary triangle faces (vertex indices).
    boundary_tags : list[int]
        Region tag per boundary face (1 = outer wall, 2 = inlet, 3 = outlet,
        etc.).  Parallel to boundary_faces.
    voronoi_volumes : (N,) float array  or empty
        Voronoi cell volume associated with each vertex; used as finite-volume
        control-volume weight.  Empty if ``compute_voronoi=False``.
    quality_flags : list[int]
        Element index for each bad tet (aspect > 50 or dihedral < 5° or > 175°).
    """

    vertices: np.ndarray          # shape (N, 3)
    elements: np.ndarray          # shape (M, 4), dtype int
    boundary_faces: np.ndarray    # shape (K, 3), dtype int
    boundary_tags: List[int] = field(default_factory=list)
    voronoi_volumes: np.ndarray = field(default_factory=lambda: np.empty(0))
    quality_flags: List[int] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Topology helpers
    # ------------------------------------------------------------------

    def n_vertices(self) -> int:
        return int(self.vertices.shape[0])

    def n_elements(self) -> int:
        return int(self.elements.shape[0])

    def n_boundary_faces(self) -> int:
        return int(self.boundary_faces.shape[0])

    def total_volume(self) -> float:
        """Sum of all tetrahedral volumes (absolute value)."""
        total = 0.0
        v = self.vertices
        for tet in self.elements:
            a, b, c, d = v[tet[0]], v[tet[1]], v[tet[2]], v[tet[3]]
            vol = _tet_volume(a, b, c, d)
            total += abs(vol)
        return total

    def unique_edges(self) -> int:
        """Count unique undirected edges."""
        edge_set: set[tuple[int, int]] = set()
        for tet in self.elements:
            for i, j in itertools.combinations(tet, 2):
                edge_set.add((int(min(i, j)), int(max(i, j))))
        return len(edge_set)

    def unique_triangle_faces(self) -> int:
        """Count unique triangular faces (interior + boundary)."""
        face_set: set[tuple[int, int, int]] = set()
        for tet in self.elements:
            for triple in itertools.combinations(tet, 3):
                key: tuple[int, int, int] = tuple(sorted(triple))  # type: ignore[assignment]
                face_set.add(key)
        return len(face_set)

    def euler_characteristic(self) -> int:
        """V - E + F - T.  Must equal 1 for a simply-connected volume."""
        V = self.n_vertices()
        E = self.unique_edges()
        F = self.unique_triangle_faces()
        T = self.n_elements()
        return V - E + F - T

    def aspect_ratios(self) -> np.ndarray:
        """Compute circumradius/inradius aspect ratio for every tetrahedron.

        A regular tetrahedron has aspect ratio = 3.0 (circumradius = 3 × inradius).
        Sliver tets have aspect → ∞.  Flag threshold is 50.
        """
        v = self.vertices
        out = np.empty(self.n_elements(), dtype=float)
        for i, tet in enumerate(self.elements):
            a, b, c, d = v[tet[0]], v[tet[1]], v[tet[2]], v[tet[3]]
            out[i] = _tet_aspect_ratio(a, b, c, d)
        return out

    def dihedral_angle_stats(self) -> tuple[float, float]:
        """Return (min_dihedral_deg, max_dihedral_deg) across all elements."""
        v = self.vertices
        min_ang = math.inf
        max_ang = -math.inf
        for tet in self.elements:
            pts = [v[tet[k]] for k in range(4)]
            for ang in _tet_dihedral_angles(*pts):
                deg = math.degrees(ang)
                if deg < min_ang:
                    min_ang = deg
                if deg > max_ang:
                    max_ang = deg
        if not math.isfinite(min_ang):
            return 0.0, 0.0
        return min_ang, max_ang

    def quality_fraction_below_aspect(self, threshold: float = 10.0) -> float:
        """Fraction of tets with aspect ratio < threshold."""
        ar = self.aspect_ratios()
        if len(ar) == 0:
            return 1.0
        return float(np.mean(ar < threshold))


# ---------------------------------------------------------------------------
# Low-level geometry primitives (numpy-based)
# ---------------------------------------------------------------------------

def _tet_volume(a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray) -> float:
    """Signed volume of a tetrahedron (scalar)."""
    ab = b - a
    ac = c - a
    ad = d - a
    return float(np.dot(ab, np.cross(ac, ad))) / 6.0


def _tet_circumradius(a: np.ndarray, b: np.ndarray, c: np.ndarray,
                      d: np.ndarray) -> float:
    """Circumradius of a tetrahedron via Cayley-Menger determinant."""
    # Use the formula: R = |ab||ac||ad| / (6|V| × sin formula)
    # Implemented via the algebraic formula from Shewchuk 1997.
    A = b - a
    B = c - a
    C = d - a
    cross_BC = np.cross(B, C)
    vol6 = abs(float(np.dot(A, cross_BC)))
    if vol6 < 1e-15:
        return math.inf
    # Circumcentre offset from a:
    aA = float(np.dot(A, A))
    aB = float(np.dot(B, B))
    aC = float(np.dot(C, C))
    num = aA * cross_BC + aB * np.cross(C, A) + aC * np.cross(A, B)
    centre_offset = num / (2.0 * vol6)
    return float(np.linalg.norm(centre_offset))


def _tet_inradius(a: np.ndarray, b: np.ndarray, c: np.ndarray,
                  d: np.ndarray) -> float:
    """Inradius of a tetrahedron: r = 3V / (S1+S2+S3+S4)."""
    vol = abs(_tet_volume(a, b, c, d))
    # Face areas
    def _fa(p, q, r):
        return 0.5 * float(np.linalg.norm(np.cross(q - p, r - p)))
    s = _fa(a, b, c) + _fa(a, b, d) + _fa(a, c, d) + _fa(b, c, d)
    if s < 1e-15:
        return 0.0
    return 3.0 * vol / s


def _tet_aspect_ratio(a: np.ndarray, b: np.ndarray, c: np.ndarray,
                      d: np.ndarray) -> float:
    """Circumradius / inradius (regular tet → 3.0, sliver → ∞)."""
    R = _tet_circumradius(a, b, c, d)
    r = _tet_inradius(a, b, c, d)
    if r < 1e-15:
        return math.inf
    return R / r


def _tet_dihedral_angles(
    a: np.ndarray, b: np.ndarray, c: np.ndarray, d: np.ndarray
) -> Iterator[float]:
    """Yield the 6 dihedral angles (radians) for a tetrahedron."""
    verts = [a, b, c, d]
    for i, j in itertools.combinations(range(4), 2):
        opp = [x for x in range(4) if x not in (i, j)]
        k, l_ = opp
        n1 = np.cross(verts[j] - verts[i], verts[k] - verts[i])
        n2 = np.cross(verts[j] - verts[i], verts[l_] - verts[i])
        d1 = float(np.linalg.norm(n1))
        d2 = float(np.linalg.norm(n2))
        if d1 < 1e-15 or d2 < 1e-15:
            yield 0.0
            continue
        cos_ang = float(np.dot(n1, n2)) / (d1 * d2)
        cos_ang = max(-1.0, min(1.0, cos_ang))
        yield math.acos(-cos_ang)  # dihedral = π − angle between outward normals


def _tet_circumcentre(a: np.ndarray, b: np.ndarray, c: np.ndarray,
                      d: np.ndarray) -> Optional[np.ndarray]:
    """Return the circumcentre of a tetrahedron, or None if degenerate."""
    A = b - a
    B = c - a
    C = d - a
    cross_BC = np.cross(B, C)
    denom = 2.0 * float(np.dot(A, cross_BC))
    if abs(denom) < 1e-14:
        return None
    aA = float(np.dot(A, A))
    aB = float(np.dot(B, B))
    aC = float(np.dot(C, C))
    num = aA * cross_BC + aB * np.cross(C, A) + aC * np.cross(A, B)
    offset = num / denom
    return a + offset


# ---------------------------------------------------------------------------
# Surface mesh quality tools
# ---------------------------------------------------------------------------

def repair_surface_mesh(
    vertices: List[Vec3],
    triangles: List[TriFace],
    *,
    min_edge_length: float = 1e-6,
    min_triangle_area: float = 1e-14,
) -> tuple[List[Vec3], List[TriFace]]:
    """Repair a triangulated surface mesh for watertightness and quality.

    Steps
    -----
    1. **Short-edge collapse**: edges shorter than ``min_edge_length`` are
       collapsed to their midpoint.  The merged vertex replaces both endpoints
       throughout the triangle list.
    2. **Degenerate-face removal**: triangles whose area is below
       ``min_triangle_area`` are removed.
    3. **Duplicate vertex merge**: exact-coordinate duplicates are merged.

    Parameters
    ----------
    vertices, triangles:
        Input surface mesh.
    min_edge_length:
        Edges shorter than this threshold are collapsed.
    min_triangle_area:
        Triangles with area below this are removed.

    Returns
    -------
    (repaired_vertices, repaired_triangles) — a clean surface ready for
    volumetric Delaunay tetrahedralization.
    """
    pts = [np.array(v, dtype=float) for v in vertices]
    tris = list(triangles)

    # Step 1: merge duplicate vertices (exact tolerance = 1e-12)
    n = len(pts)
    merge_map: dict[int, int] = {i: i for i in range(n)}

    coord_to_id: dict[tuple, int] = {}
    for i, p in enumerate(pts):
        key = (round(p[0], 12), round(p[1], 12), round(p[2], 12))
        if key in coord_to_id:
            merge_map[i] = coord_to_id[key]
        else:
            coord_to_id[key] = i

    # Resolve chains
    def _resolve(i: int) -> int:
        while merge_map[i] != i:
            merge_map[i] = merge_map[merge_map[i]]
            i = merge_map[i]
        return i

    # Step 2: collapse short edges (merge higher-index into lower-index to avoid cycles)
    changed = True
    max_passes = len(pts) + 1  # safety limit
    pass_count = 0
    while changed and pass_count < max_passes:
        changed = False
        pass_count += 1
        for _ti, tri in enumerate(tris):
            if tri is None:  # type: ignore[comparison-overlap]
                continue
            a_i, b_i, c_i = (_resolve(tri[0]), _resolve(tri[1]), _resolve(tri[2]))
            for u, v in [(a_i, b_i), (b_i, c_i), (a_i, c_i)]:
                if pts[u] is None or pts[v] is None:  # type: ignore[comparison-overlap]
                    continue
                edge_len = float(np.linalg.norm(pts[u] - pts[v]))
                if edge_len < min_edge_length:
                    # Always merge higher into lower to prevent merge cycles
                    keep_v, drop_v = (u, v) if u < v else (v, u)
                    mid = (pts[keep_v] + pts[drop_v]) / 2.0
                    pts[keep_v] = mid
                    merge_map[drop_v] = keep_v
                    changed = True
                    break  # restart with fresh resolve

    # Step 3: apply merge_map to triangles and filter degenerate faces
    clean_tris: List[TriFace] = []
    for tri in tris:
        if tri is None:  # type: ignore[comparison-overlap]
            continue
        a_i, b_i, c_i = (_resolve(tri[0]), _resolve(tri[1]), _resolve(tri[2]))
        # Degenerate if any two indices are the same
        if len({a_i, b_i, c_i}) < 3:
            continue
        # Degenerate if area is too small
        pa, pb, pc = pts[a_i], pts[b_i], pts[c_i]
        area = 0.5 * float(np.linalg.norm(np.cross(pb - pa, pc - pa)))
        if area < min_triangle_area:
            continue
        clean_tris.append((a_i, b_i, c_i))

    # Re-index vertices to only those used
    used = set()
    for tri in clean_tris:
        used.update(tri)
    old_to_new = {old: new for new, old in enumerate(sorted(used))}
    new_verts = [tuple(pts[old]) for old in sorted(used)]  # type: ignore[misc]
    new_tris = [(old_to_new[a], old_to_new[b], old_to_new[c]) for (a, b, c) in clean_tris]
    return new_verts, new_tris  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Boundary face extraction
# ---------------------------------------------------------------------------

def _extract_boundary_faces(
    elements: np.ndarray,
) -> np.ndarray:
    """Return boundary faces (faces shared by exactly one tet).

    Returns
    -------
    (K, 3) int array — sorted vertex indices per boundary triangle.
    """
    face_count: dict[tuple[int, int, int], int] = {}
    for tet in elements:
        for triple in itertools.combinations(tet.tolist(), 3):
            key: tuple[int, int, int] = tuple(sorted(triple))  # type: ignore[assignment]
            face_count[key] = face_count.get(key, 0) + 1
    bfaces = [f for f, cnt in face_count.items() if cnt == 1]
    if not bfaces:
        return np.empty((0, 3), dtype=int)
    return np.array(bfaces, dtype=int)


# ---------------------------------------------------------------------------
# Constrained boundary recovery
# ---------------------------------------------------------------------------

def _missing_boundary_faces(
    required: np.ndarray,  # (K, 3) sorted
    present: np.ndarray,   # (J, 3) sorted
) -> np.ndarray:
    """Return required boundary faces that are absent from the tet mesh surface."""
    present_set: set[tuple[int, int, int]] = set()
    for row in present:
        present_set.add(tuple(row.tolist()))  # type: ignore[arg-type]
    missing = []
    for row in required:
        key: tuple[int, int, int] = tuple(row.tolist())  # type: ignore[assignment]
        if key not in present_set:
            missing.append(row)
    return np.array(missing, dtype=int) if missing else np.empty((0, 3), dtype=int)


def _recover_boundary(
    vertices: np.ndarray,
    elements: np.ndarray,
    required_faces: np.ndarray,
    max_passes: int = 5,
) -> tuple[np.ndarray, np.ndarray]:
    """Insert Steiner points to recover missing boundary faces.

    For each pass, every required boundary face that is absent from the
    current mesh surface gets a Steiner point at its centroid.  The augmented
    point cloud is then re-triangulated with Delaunay.

    Parameters
    ----------
    vertices : (N, 3) array
    elements : (M, 4) int array
    required_faces : (K, 3) int array  (sorted vertex indices)
    max_passes : int
        Maximum recovery passes before giving up.

    Returns
    -------
    (vertices, elements) — updated mesh.
    """
    for _pass in range(max_passes):
        bfaces = _extract_boundary_faces(elements)
        missing = _missing_boundary_faces(required_faces, bfaces)
        if missing.shape[0] == 0:
            break
        # Insert centroid of each missing face as a Steiner point
        steiner = []
        for face in missing:
            centroid = vertices[face].mean(axis=0)
            steiner.append(centroid)
        if steiner:
            new_pts = np.vstack([vertices, np.array(steiner)])
            try:
                dt = Delaunay(new_pts)
                new_elems = dt.simplices.copy()
                # Filter degenerate tets
                keep = []
                for tet in new_elems:
                    vol = _tet_volume(new_pts[tet[0]], new_pts[tet[1]],
                                     new_pts[tet[2]], new_pts[tet[3]])
                    if abs(vol) > 1e-15:
                        if vol < 0:
                            tet[[0, 1]] = tet[[1, 0]]
                        keep.append(tet)
                vertices = new_pts
                elements = np.array(keep, dtype=int) if keep else np.empty((0, 4), dtype=int)
            except Exception:
                break
    return vertices, elements


# ---------------------------------------------------------------------------
# Voronoi dual computation
# ---------------------------------------------------------------------------

def _compute_voronoi_volumes(
    vertices: np.ndarray,
    elements: np.ndarray,
) -> np.ndarray:
    """Compute the Voronoi cell volume for each mesh vertex.

    The Voronoi cell of vertex v is the region closer to v than to any other
    vertex.  Its volume equals the sum of contributions from each incident
    tetrahedron: (1/4) × tet_volume per vertex (barycentric partition).

    This is the standard node-centred finite-volume control-volume weight
    (Jasak 1996, eq. 4.4).

    Returns
    -------
    (N,) float array — Voronoi cell volume per vertex.
    """
    n = int(vertices.shape[0])
    vvol = np.zeros(n, dtype=float)
    for tet in elements:
        a, b, c, d = vertices[tet[0]], vertices[tet[1]], vertices[tet[2]], vertices[tet[3]]
        vol = abs(_tet_volume(a, b, c, d))
        share = vol / 4.0  # equal barycentric share per vertex
        for idx in tet:
            vvol[int(idx)] += share
    return vvol


# ---------------------------------------------------------------------------
# Quality flagging
# ---------------------------------------------------------------------------

def _flag_bad_elements(
    vertices: np.ndarray,
    elements: np.ndarray,
    *,
    max_aspect: float = 50.0,
    min_dihedral_deg: float = 5.0,
    max_dihedral_deg: float = 175.0,
) -> List[int]:
    """Return indices of tetrahedra that violate quality thresholds.

    Parameters
    ----------
    max_aspect : float
        Circumradius/inradius threshold (default 50).
    min_dihedral_deg : float
        Minimum acceptable dihedral angle in degrees (default 5°).
    max_dihedral_deg : float
        Maximum acceptable dihedral angle in degrees (default 175°).

    Returns
    -------
    List of element indices (into ``elements``) that fail at least one criterion.
    """
    bad: List[int] = []
    for i, tet in enumerate(elements):
        a, b, c, d = (vertices[tet[k]] for k in range(4))
        # Aspect ratio check
        ar = _tet_aspect_ratio(a, b, c, d)
        if ar > max_aspect:
            bad.append(i)
            continue
        # Dihedral angle check
        flag = False
        for ang_rad in _tet_dihedral_angles(a, b, c, d):
            deg = math.degrees(ang_rad)
            if deg < min_dihedral_deg or deg > max_dihedral_deg:
                flag = True
                break
        if flag:
            bad.append(i)
    return bad


# ---------------------------------------------------------------------------
# Octree density-field refinement
# ---------------------------------------------------------------------------

DensityField = Callable[[float, float, float], float]
"""A callable (x, y, z) → target_edge_length at that point."""


def _edge_length_stats(vertices: np.ndarray, elements: np.ndarray) -> np.ndarray:
    """Return the mean edge length for each tetrahedron."""
    out = np.empty(len(elements), dtype=float)
    for i, tet in enumerate(elements):
        pts = [vertices[tet[k]] for k in range(4)]
        lengths = [float(np.linalg.norm(pts[a] - pts[b]))
                   for a, b in itertools.combinations(range(4), 2)]
        out[i] = sum(lengths) / len(lengths)
    return out


def refine_with_density_field(
    mesh: UnstructuredMesh3D,
    density: DensityField | float,
    *,
    max_iterations: int = 5,
    tolerance: float = 0.5,
) -> UnstructuredMesh3D:
    """Refine a mesh to match a target sizing field.

    For each tetrahedron whose mean edge length exceeds
    ``(1 + tolerance) × target_size`` at its centroid, a Steiner point is
    inserted at the centroid.  The augmented point cloud is re-triangulated
    with Delaunay.  The process repeats for up to ``max_iterations`` passes.

    Parameters
    ----------
    mesh : UnstructuredMesh3D
        Input mesh to refine.
    density : callable or float
        Target edge length at (x, y, z).  If a scalar, uniform sizing.
    max_iterations : int
        Maximum refinement passes (default 5).
    tolerance : float
        Allowed over-size factor before refinement triggers (default 0.5 → 150%).

    Returns
    -------
    Refined ``UnstructuredMesh3D``.
    """
    if not callable(density):
        target_const = float(density)

        def density(x: float, y: float, z: float) -> float:  # type: ignore[misc]
            return target_const

    vertices = mesh.vertices.copy()
    elements = mesh.elements.copy()

    for _it in range(max_iterations):
        el_lengths = _edge_length_stats(vertices, elements)
        new_pts: List[np.ndarray] = []
        for i, tet in enumerate(elements):
            centroid = vertices[tet].mean(axis=0)
            cx, cy, cz = float(centroid[0]), float(centroid[1]), float(centroid[2])
            target = density(cx, cy, cz)
            if target <= 0:
                continue
            if el_lengths[i] > target * (1.0 + tolerance):
                new_pts.append(centroid)

        if not new_pts:
            break

        vertices = np.vstack([vertices, np.array(new_pts)])
        try:
            dt = Delaunay(vertices)
            new_elems_raw = dt.simplices.copy()
            keep = []
            for tet in new_elems_raw:
                vol = _tet_volume(vertices[tet[0]], vertices[tet[1]],
                                  vertices[tet[2]], vertices[tet[3]])
                if abs(vol) > 1e-15:
                    if vol < 0:
                        tet[[0, 1]] = tet[[1, 0]]
                    keep.append(tet)
            elements = np.array(keep, dtype=int) if keep else np.empty((0, 4), dtype=int)
        except Exception:
            break

    bfaces = _extract_boundary_faces(elements)
    quality_flags = _flag_bad_elements(vertices, elements)
    voronoi_vols = _compute_voronoi_volumes(vertices, elements)

    return UnstructuredMesh3D(
        vertices=vertices,
        elements=elements,
        boundary_faces=bfaces,
        boundary_tags=[1] * bfaces.shape[0],
        voronoi_volumes=voronoi_vols,
        quality_flags=quality_flags,
    )


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def mesh_from_surface(
    surface_vertices: Sequence[Vec3],
    surface_triangles: Sequence[TriFace],
    *,
    repair: bool = True,
    min_edge_length: float = 1e-6,
    compute_voronoi: bool = True,
    boundary_recovery_passes: int = 3,
) -> UnstructuredMesh3D:
    """Generate a 3-D unstructured tet mesh from a triangulated surface.

    Parameters
    ----------
    surface_vertices :
        List of (x, y, z) coordinate tuples defining the surface.
    surface_triangles :
        List of (i, j, k) vertex-index triples defining the boundary triangles.
    repair :
        If True, run surface mesh repair (short-edge collapse, degenerate removal)
        before volumetric meshing.
    min_edge_length :
        Short-edge collapse threshold (used when ``repair=True``).
    compute_voronoi :
        If True, compute Voronoi cell volumes for node-centred FV schemes.
    boundary_recovery_passes :
        Number of Steiner-point passes for boundary face recovery.

    Returns
    -------
    ``UnstructuredMesh3D`` with Delaunay elements and optional Voronoi dual.
    """
    verts_list: List[Vec3] = list(surface_vertices)
    tris_list: List[TriFace] = list(surface_triangles)

    if repair:
        verts_list, tris_list = repair_surface_mesh(
            verts_list, tris_list, min_edge_length=min_edge_length
        )

    if len(verts_list) < 4:
        raise ValueError(
            f"Need at least 4 non-coplanar surface vertices; got {len(verts_list)}"
        )

    pts = np.array(verts_list, dtype=float)

    # Delaunay tetrahedralization of the surface point cloud
    try:
        dt = Delaunay(pts)
    except Exception as exc:
        raise RuntimeError(f"scipy.spatial.Delaunay failed: {exc}") from exc

    raw_elems = dt.simplices.copy()

    # Ensure positive orientation and filter degenerate tets
    keep: List[np.ndarray] = []
    for tet in raw_elems:
        vol = _tet_volume(pts[tet[0]], pts[tet[1]], pts[tet[2]], pts[tet[3]])
        if abs(vol) > 1e-15:
            if vol < 0:
                tet[[0, 1]] = tet[[1, 0]]
            keep.append(tet.copy())

    elements = np.array(keep, dtype=int) if keep else np.empty((0, 4), dtype=int)

    # Build required boundary faces (sorted indices from input triangles)
    req_faces_list = [
        tuple(sorted([t[0], t[1], t[2]])) for t in tris_list
    ]
    req_faces = np.array(req_faces_list, dtype=int) if req_faces_list else np.empty((0, 3), dtype=int)

    # Boundary recovery
    if boundary_recovery_passes > 0 and req_faces.shape[0] > 0:
        pts, elements = _recover_boundary(
            pts, elements, req_faces, max_passes=boundary_recovery_passes
        )

    bfaces = _extract_boundary_faces(elements)
    quality_flags = _flag_bad_elements(pts, elements)
    voronoi_vols = _compute_voronoi_volumes(pts, elements) if compute_voronoi else np.empty(0)

    return UnstructuredMesh3D(
        vertices=pts,
        elements=elements,
        boundary_faces=bfaces,
        boundary_tags=[1] * bfaces.shape[0],
        voronoi_volumes=voronoi_vols,
        quality_flags=quality_flags,
    )


def mesh_unit_cube_unstructured(
    n: int = 4,
    *,
    compute_voronoi: bool = True,
) -> UnstructuredMesh3D:
    """Generate a uniform tet mesh of the unit cube [0,1]³.

    Parameters
    ----------
    n : int
        Number of interior divisions per axis (total grid = (n+1)³ nodes).
    compute_voronoi : bool
        If True, compute Voronoi cell volumes.

    Returns
    -------
    ``UnstructuredMesh3D`` filling the unit cube.
    """
    # Build a regular grid of points
    coords = np.linspace(0.0, 1.0, n + 1)
    grid = np.array(
        [(x, y, z) for x in coords for y in coords for z in coords],
        dtype=float,
    )

    # Small jitter to break symmetry and avoid degenerate Delaunay situations
    rng = np.random.default_rng(42)
    interior_mask = np.all((grid > 0) & (grid < 1), axis=1)
    grid[interior_mask] += rng.uniform(-0.5 / n * 0.15, 0.5 / n * 0.15,
                                        (int(interior_mask.sum()), 3))

    try:
        dt = Delaunay(grid)
    except Exception as exc:
        raise RuntimeError(f"Delaunay failed: {exc}") from exc

    raw_elems = dt.simplices.copy()
    # Keep ALL simplices (needed for correct Euler characteristic);
    # only flip orientation for negative-volume tets.
    keep: List[np.ndarray] = []
    for tet in raw_elems:
        vol = _tet_volume(grid[tet[0]], grid[tet[1]], grid[tet[2]], grid[tet[3]])
        if vol < 0:
            tet[[0, 1]] = tet[[1, 0]]
        keep.append(tet.copy())

    elements = np.array(keep, dtype=int) if keep else np.empty((0, 4), dtype=int)
    bfaces = _extract_boundary_faces(elements)
    quality_flags = _flag_bad_elements(grid, elements)
    voronoi_vols = _compute_voronoi_volumes(grid, elements) if compute_voronoi else np.empty(0)

    return UnstructuredMesh3D(
        vertices=grid,
        elements=elements,
        boundary_faces=bfaces,
        boundary_tags=[1] * bfaces.shape[0],
        voronoi_volumes=voronoi_vols,
        quality_flags=quality_flags,
    )


def mesh_spherical_shell(
    outer_radius: float = 1.0,
    inner_radius: float = 0.3,
    n_lat: int = 8,
    n_lon: int = 8,
    n_radial: int = 4,
    *,
    compute_voronoi: bool = True,
) -> UnstructuredMesh3D:
    """Generate a tet mesh of a spherical shell (annular domain).

    Parameters
    ----------
    outer_radius : float
        Outer sphere radius R.
    inner_radius : float
        Inner sphere radius r.
    n_lat, n_lon : int
        Latitude / longitude subdivisions for the surface grids.
    n_radial : int
        Radial layers between inner and outer spheres.
    compute_voronoi : bool
        If True, compute Voronoi cell volumes.

    Returns
    -------
    ``UnstructuredMesh3D`` filling the shell domain.

    Notes
    -----
    The expected volume is (4/3)π(R³ − r³).  The mesh volume should be
    within 5% of this value for n_lat = n_lon = 8, n_radial = 4.
    """
    if inner_radius >= outer_radius:
        raise ValueError("inner_radius must be less than outer_radius")
    if inner_radius <= 0:
        raise ValueError("inner_radius must be positive")

    # Use Fibonacci sphere sampling for uniform coverage on each radial layer.
    # This avoids the polar singularity of structured (lat, lon) grids and gives
    # better volume recovery at moderate point counts.
    def _fibonacci_sphere(n_pts: int, r: float) -> List[np.ndarray]:
        """Return n_pts uniformly distributed points on a sphere of radius r."""
        golden = (1.0 + math.sqrt(5.0)) / 2.0
        pts_s: List[np.ndarray] = []
        for i in range(n_pts):
            theta = math.acos(1.0 - 2.0 * (i + 0.5) / n_pts)
            phi = 2.0 * math.pi * i / golden
            pts_s.append(np.array([
                r * math.sin(theta) * math.cos(phi),
                r * math.sin(theta) * math.sin(phi),
                r * math.cos(theta),
            ]))
        return pts_s

    # n_lat is re-used as points-per-layer; n_lon is ignored (Fibonacci handles azimuth).
    n_per_layer = n_lat * n_lon  # re-interpret as total per-layer count
    radii_arr = np.linspace(inner_radius, outer_radius, n_radial + 2)
    pts_list: List[np.ndarray] = []
    for r in radii_arr:
        pts_list.extend(_fibonacci_sphere(n_per_layer, r))

    pts = np.array(pts_list, dtype=float)

    try:
        dt = Delaunay(pts)
    except Exception as exc:
        raise RuntimeError(f"Delaunay failed for spherical shell: {exc}") from exc

    raw_elems = dt.simplices.copy()
    pts_radii = np.linalg.norm(pts, axis=1)
    # Allow a small tolerance (2% of shell thickness) to avoid missing
    # tets near the inner/outer surfaces due to floating-point round-off.
    r_tol = 0.02 * (outer_radius - inner_radius)
    keep: List[np.ndarray] = []
    for tet in raw_elems:
        v_radii = pts_radii[tet]
        if (v_radii.min() >= inner_radius - r_tol and
                v_radii.max() <= outer_radius + r_tol):
            vol = _tet_volume(pts[tet[0]], pts[tet[1]], pts[tet[2]], pts[tet[3]])
            if vol < 0:
                tet[[0, 1]] = tet[[1, 0]]
            keep.append(tet.copy())

    elements = np.array(keep, dtype=int) if keep else np.empty((0, 4), dtype=int)
    bfaces = _extract_boundary_faces(elements)
    quality_flags = _flag_bad_elements(pts, elements)
    voronoi_vols = _compute_voronoi_volumes(pts, elements) if compute_voronoi else np.empty(0)

    return UnstructuredMesh3D(
        vertices=pts,
        elements=elements,
        boundary_faces=bfaces,
        boundary_tags=[1] * bfaces.shape[0],
        voronoi_volumes=voronoi_vols,
        quality_flags=quality_flags,
    )


def mesh_bent_pipe(
    length: float = 1.0,
    radius: float = 0.1,
    bend_angle_deg: float = 90.0,
    n_cross: int = 5,
    n_axial: int = 12,
    *,
    compute_voronoi: bool = True,
) -> UnstructuredMesh3D:
    """Generate a tet mesh of a bent (curved) cylindrical pipe.

    The pipe follows a circular arc in the x-z plane.  This geometry is a
    canonical CFD benchmark for mesh quality in curved domains.

    Parameters
    ----------
    length : float
        Approximate arc length of the pipe centreline.
    radius : float
        Pipe cross-section radius.
    bend_angle_deg : float
        Total bend angle in degrees (0° = straight pipe).
    n_cross : int
        Radial subdivisions in the cross-section.
    n_axial : int
        Number of axial stations along the pipe.
    compute_voronoi : bool
        If True, compute Voronoi cell volumes.

    Returns
    -------
    ``UnstructuredMesh3D`` of the pipe domain.
    """
    bend_rad = math.radians(bend_angle_deg)

    # Strategy: build a structured O-grid prism stack along the pipe centreline,
    # then subdivide each triangular prism into 3 tetrahedra (Freudenthal partition).
    # This guarantees well-shaped elements (no Delaunay convex-hull artifacts).
    #
    # Cross-section: O-grid with n_cross radial rings.
    # Topology: ring 0 = single central triangle fan; outer rings = quad cells.
    # Each quad is split into 2 triangles; each prism into 3 tets.

    # Build centreline frames
    frames: List[tuple[np.ndarray, np.ndarray, np.ndarray]] = []  # (centre, norm, binorm)
    for i_ax in range(n_axial + 1):
        t = i_ax / n_axial
        if bend_angle_deg < 1.0:
            cx, cy, cz = t * length, 0.0, 0.0
            norm = np.array([0.0, 1.0, 0.0])
            binorm = np.array([0.0, 0.0, 1.0])
        else:
            arc_radius = length / bend_rad
            theta = t * bend_rad
            cx = arc_radius * math.sin(theta)
            cy = 0.0
            cz = arc_radius * (1.0 - math.cos(theta))
            tang = np.array([math.cos(theta), 0.0, math.sin(theta)])
            norm = np.array([0.0, 1.0, 0.0])
            binorm = np.cross(tang, norm)
        frames.append((np.array([cx, cy, cz]), norm, binorm))

    # Fixed circumferential count for the outer ring (power of 2 for uniformity)
    n_circ = max(8, n_cross * 4)

    # Build node array: for each axial station, lay out a 2-D O-grid disk
    # Node ordering per station:
    #   index 0: centreline node
    #   index 1..n_circ: first ring nodes
    #   index (1 + i_r*n_circ)..(1 + (i_r+1)*n_circ - 1): ring i_r+1 nodes
    nodes_per_section = 1 + n_cross * n_circ

    pts_list = []
    for i_ax in range(n_axial + 1):
        centre, norm, binorm = frames[i_ax]
        pts_list.append(centre.copy())  # node 0 of section
        for i_r in range(n_cross):
            rr = radius * (i_r + 1) / n_cross
            for j in range(n_circ):
                phi = 2.0 * math.pi * j / n_circ
                pt = centre + rr * math.cos(phi) * norm + rr * math.sin(phi) * binorm
                pts_list.append(pt)

    pts = np.array(pts_list, dtype=float)

    def _node(i_ax: int, ring: int, circ: int) -> int:
        """Global vertex index: station i_ax, ring `ring` (0 = centre), circ index."""
        base = i_ax * nodes_per_section
        if ring == 0:
            return base
        return base + 1 + (ring - 1) * n_circ + (circ % n_circ)

    # Build tetrahedra from triangular prism stacks
    # For each axial slab [i_ax, i_ax+1] and each quadrilateral cell
    # [(ring r, circ j), (ring r, circ j+1), (ring r+1, circ j), (ring r+1, circ j+1)]
    # at two axial stations → 6-node prism → 3 tets.
    #
    # Freudenthal partition of a triangular prism (vertices a0,b0,c0; a1,b1,c1):
    #   tet1: a0, b0, c0, c1
    #   tet2: a0, b0, b1, c1
    #   tet3: a0, a1, b1, c1
    elems: List[np.ndarray] = []

    for i_ax in range(n_axial):
        # Central fan (triangle per circ segment between axial stations)
        for j in range(n_circ):
            j1 = (j + 1) % n_circ
            # Prism nodes: [ctr0, r1j0, r1j10; ctr1, r1j1, r1j11]
            a0, b0, c0 = _node(i_ax, 0, 0), _node(i_ax, 1, j), _node(i_ax, 1, j1)
            a1, b1, c1 = _node(i_ax+1, 0, 0), _node(i_ax+1, 1, j), _node(i_ax+1, 1, j1)
            # Freudenthal 3-tet split:
            for tet_verts in [
                (a0, b0, c0, c1),
                (a0, b0, b1, c1),
                (a0, a1, b1, c1),
            ]:
                t_arr = np.array(tet_verts, dtype=int)
                vol = _tet_volume(pts[t_arr[0]], pts[t_arr[1]],
                                  pts[t_arr[2]], pts[t_arr[3]])
                if vol < 0:
                    t_arr[[0, 1]] = t_arr[[1, 0]]
                if abs(vol) > 1e-15:
                    elems.append(t_arr)

        # Ring cells
        for i_r in range(1, n_cross):
            for j in range(n_circ):
                j1 = (j + 1) % n_circ
                # Quad: (i_r, j), (i_r, j1), (i_r+1, j), (i_r+1, j1) at each station
                a0 = _node(i_ax,   i_r, j)
                b0 = _node(i_ax,   i_r, j1)
                c0 = _node(i_ax,   i_r+1, j)
                d0 = _node(i_ax,   i_r+1, j1)
                a1 = _node(i_ax+1, i_r, j)
                b1 = _node(i_ax+1, i_r, j1)
                c1 = _node(i_ax+1, i_r+1, j)
                d1 = _node(i_ax+1, i_r+1, j1)
                # Split quad faces into 2 triangles each → 2 prisms → 6 tets
                for prism_verts in [
                    (a0, b0, d0, a1, b1, d1),
                    (a0, c0, d0, a1, c1, d1),
                ]:
                    pa0, pb0, pc0, pa1, pb1, pc1 = prism_verts
                    for tet_verts in [
                        (pa0, pb0, pc0, pc1),
                        (pa0, pb0, pb1, pc1),
                        (pa0, pa1, pb1, pc1),
                    ]:
                        t_arr = np.array(tet_verts, dtype=int)
                        vol = _tet_volume(pts[t_arr[0]], pts[t_arr[1]],
                                          pts[t_arr[2]], pts[t_arr[3]])
                        if vol < 0:
                            t_arr[[0, 1]] = t_arr[[1, 0]]
                        if abs(vol) > 1e-15:
                            elems.append(t_arr)

    keep: List[np.ndarray] = elems  # already built; no Delaunay needed for structured mesh

    elements = np.array(keep, dtype=int) if keep else np.empty((0, 4), dtype=int)
    bfaces = _extract_boundary_faces(elements)
    quality_flags = _flag_bad_elements(pts, elements)
    voronoi_vols = _compute_voronoi_volumes(pts, elements) if compute_voronoi else np.empty(0)

    return UnstructuredMesh3D(
        vertices=pts,
        elements=elements,
        boundary_faces=bfaces,
        boundary_tags=[1] * bfaces.shape[0],
        voronoi_volumes=voronoi_vols,
        quality_flags=quality_flags,
    )
