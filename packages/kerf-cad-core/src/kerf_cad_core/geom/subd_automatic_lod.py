"""
subd_automatic_lod.py
=====================
SubD-specific automatic LOD (level-of-detail) chain generation.

Exploits the natural cage hierarchy of Catmull-Clark subdivision surfaces to
produce multi-resolution meshes for distance-based culling — faster than
re-tessellating from a B-rep because the cage itself IS the coarsest LOD.

References
----------
- Hoppe 1996 "Progressive Meshes", SIGGRAPH.
- Pajarola & Rossignac 2000 "Compressed Progressive Meshes", IEEE TVCG.
- DeRose, Kass & Truong 1998 "Subdivision Surfaces in Character Animation".
- OpenSubdiv documentation on level hierarchy.

Public API
----------
SubdLodChain
    Dataclass holding the generated LOD levels.

generate_subd_lod_chain(cage, n_levels=4) -> SubdLodChain
    LOD 0 = cage itself (lowest detail, fewest triangles).
    LOD i = subdivide(LOD i-1) one Catmull-Clark step.
    Returns SubdLodChain with per-level meshes, counts, and projected errors.

ProgressiveMesh
    Dataclass holding Hoppe-style edge-collapse / vertex-split records.

generate_progressive_mesh(cage, n_collapses=None) -> ProgressiveMesh
    Build a Hoppe progressive mesh from the finest LOD.
    Stores edge-collapse and vertex-split records for streaming/reconstruction.
    With all collapses applied → coarsest (LOD 0); with none → finest (LOD n).

pick_lod_for_view(chain, distance, viewport_pixels=1080, fov_y=60.0) -> int
    Returns the appropriate LOD index for a given viewing distance.
    Coarsest (index 0) at large distance; finest (last index) up close.

Screen-space pixel-error model
-------------------------------
For a mesh of characteristic edge length L at viewing distance d, the
projected pixel error in a viewport of height H pixels and vertical FOV α is:

    pixel_error(L, d) = H * L / (2 * d * tan(α/2))

We pre-compute a reference edge length at each LOD level as the RMS edge
length of the subdivided mesh, then solve for the distance at which that
error equals one pixel — giving the "switch-in" distance per level.

For the LOD picker we select the finest level whose pixel error at the given
distance is at least 1 pixel (i.e. adding detail is still visible).

Conventions
-----------
- ``distance`` is in world-space units (same as vertex coordinates).
- All operations are pure-Python and never raise.
- Quad faces from CC subdivision are triangulated (each quad → 2 triangles)
  for triangle_counts statistics, matching renderer expectations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from kerf_cad_core.geom.subd import (
    SubDMesh,
    catmull_clark_subdivide,
)


# ---------------------------------------------------------------------------
# Triangle count helper
# ---------------------------------------------------------------------------

def _triangle_count(mesh: SubDMesh) -> int:
    """Count triangles if all faces were split into tris (quad → 2, tri → 1, n → n-2)."""
    total = 0
    for face in mesh.faces:
        n = len(face)
        if n >= 3:
            total += n - 2
    return total


def _rms_edge_length(mesh: SubDMesh) -> float:
    """Compute RMS edge length of all unique edges in the mesh."""
    seen: set = set()
    sq_sum = 0.0
    count = 0
    verts = mesh.vertices
    for face in mesh.faces:
        n = len(face)
        for i in range(n):
            a = face[i]
            b = face[(i + 1) % n]
            key = (min(a, b), max(a, b))
            if key in seen:
                continue
            seen.add(key)
            va = verts[a]
            vb = verts[b]
            dx = vb[0] - va[0]
            dy = vb[1] - va[1]
            dz = vb[2] - va[2]
            sq_sum += dx * dx + dy * dy + dz * dz
            count += 1
    if count == 0:
        return 0.0
    return math.sqrt(sq_sum / count)


def _pixel_error(edge_length: float, distance: float, viewport_pixels: float, fov_y_rad: float) -> float:
    """Projected pixel size of an edge of *edge_length* at *distance*."""
    half_h = math.tan(fov_y_rad / 2.0) * distance
    if half_h <= 0.0 or distance <= 0.0:
        return float("inf")
    return viewport_pixels * edge_length / (2.0 * half_h)


# ---------------------------------------------------------------------------
# SubdLodChain
# ---------------------------------------------------------------------------

@dataclass
class SubdLodChain:
    """Multi-resolution LOD chain derived from a single SubD cage.

    Attributes
    ----------
    levels : list of SubDMesh
        LOD meshes from coarsest (index 0 = cage) to finest (index n_levels).
    vertex_counts : list of int
        Vertex count per LOD level.
    triangle_counts : list of int
        Triangle count per LOD level (quads split into 2 triangles each).
    level_pixel_errors : list of float
        RMS edge-length-based projected pixel error coefficient per level.
        Pixel error at distance d =  level_pixel_errors[i] / d  (for unit
        viewport / FOV).  Larger value means coarser.
    switch_distances : list of float
        Viewing distance at which pixel_error == 1 for each level, computed
        using the default viewport (1080px, 60° fov_y).  Switch-in range for
        level i is [0, switch_distances[i]].
    """
    levels: List[SubDMesh] = field(default_factory=list)
    vertex_counts: List[int] = field(default_factory=list)
    triangle_counts: List[int] = field(default_factory=list)
    level_pixel_errors: List[float] = field(default_factory=list)
    switch_distances: List[float] = field(default_factory=list)

    @property
    def n_levels(self) -> int:
        return len(self.levels)


# ---------------------------------------------------------------------------
# generate_subd_lod_chain
# ---------------------------------------------------------------------------

def generate_subd_lod_chain(
    cage: SubDMesh,
    n_levels: int = 4,
    viewport_pixels: float = 1080.0,
    fov_y: float = 60.0,
) -> SubdLodChain:
    """Build an automatic LOD chain from a SubD cage using CC subdivision.

    LOD 0 is the cage itself (lowest detail).  Each subsequent level is one
    additional Catmull-Clark subdivision step, so:

        LOD 0 → cage (V vertices, F faces)
        LOD 1 → subdivide(cage, 1 level)
        LOD k → subdivide(cage, k levels)

    Because CC is a refinement scheme, each level has approximately 4× the
    faces of the previous level for all-quad input (each quad → 4 quads).

    Parameters
    ----------
    cage : SubDMesh
        Input control cage.
    n_levels : int
        Number of refinement levels beyond the cage (1..8).  Total levels in
        the chain = n_levels + 1 (including LOD 0 = cage).
    viewport_pixels : float
        Viewport height in pixels for pixel-error computation (default 1080).
    fov_y : float
        Vertical field of view in degrees for pixel-error computation (default 60°).

    Returns
    -------
    SubdLodChain
        Never raises.
    """
    try:
        n_levels = max(1, min(8, int(n_levels)))
        fov_rad = math.radians(max(1.0, min(179.0, float(fov_y))))

        levels: List[SubDMesh] = []
        vertex_counts: List[int] = []
        triangle_counts: List[int] = []
        level_pixel_errors: List[float] = []
        switch_distances: List[float] = []

        # LOD 0 = cage copy
        current = SubDMesh(
            vertices=[list(v) for v in cage.vertices],
            faces=[list(f) for f in cage.faces],
            creases=dict(cage.creases),
        )

        for level_idx in range(n_levels + 1):
            if level_idx == 0:
                mesh = current
            else:
                # One additional CC step from the previous mesh
                mesh = catmull_clark_subdivide(current, levels=1)
                current = mesh

            levels.append(mesh)
            vertex_counts.append(mesh.num_vertices)
            triangle_counts.append(_triangle_count(mesh))

            # Pixel-error coefficient = RMS edge length * viewport_pixels / (2 * tan(fov/2))
            # pixel_error(d) = coeff / d
            rms_e = _rms_edge_length(mesh)
            half_tan = math.tan(fov_rad / 2.0)
            if half_tan > 0.0:
                coeff = viewport_pixels * rms_e / (2.0 * half_tan)
            else:
                coeff = 0.0
            level_pixel_errors.append(coeff)
            # Switch distance: coeff / 1 pixel = coeff
            switch_distances.append(coeff)

        return SubdLodChain(
            levels=levels,
            vertex_counts=vertex_counts,
            triangle_counts=triangle_counts,
            level_pixel_errors=level_pixel_errors,
            switch_distances=switch_distances,
        )
    except Exception:
        # Return a minimal chain with just the cage on failure.
        try:
            cage_copy = SubDMesh(
                vertices=[list(v) for v in cage.vertices],
                faces=[list(f) for f in cage.faces],
                creases=dict(cage.creases),
            )
            tc = _triangle_count(cage_copy)
            return SubdLodChain(
                levels=[cage_copy],
                vertex_counts=[cage_copy.num_vertices],
                triangle_counts=[tc],
                level_pixel_errors=[0.0],
                switch_distances=[0.0],
            )
        except Exception:
            return SubdLodChain()


# ---------------------------------------------------------------------------
# EdgeCollapseRecord / VertexSplitRecord / ProgressiveMesh
# ---------------------------------------------------------------------------

@dataclass
class EdgeCollapseRecord:
    """A single Hoppe-style edge-collapse operation.

    Collapses edge (v_a, v_b) → v_a (the "survivor" vertex).

    Attributes
    ----------
    v_a : int
        Survivor vertex index (position updated to the merged position).
    v_b : int
        Removed vertex index.
    merged_position : list of float
        [x, y, z] position of the merged vertex v_a.
    removed_faces : list of int
        Face indices that were removed (the two faces sharing edge (v_a, v_b)).
    updated_faces : list of int
        Face indices whose v_b references were remapped to v_a.
    qem_error : float
        Quadric error metric value at collapse time.
    """
    v_a: int = 0
    v_b: int = 0
    merged_position: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    removed_faces: List[int] = field(default_factory=list)
    updated_faces: List[int] = field(default_factory=list)
    qem_error: float = 0.0


@dataclass
class VertexSplitRecord:
    """Inverse of EdgeCollapseRecord — reconstructs a split vertex.

    Attributes
    ----------
    v_a : int
        Vertex to split (survivor from collapse).
    v_b_new : int
        New vertex index introduced by the split.
    v_b_position : list of float
        [x, y, z] position of the re-introduced vertex.
    restored_faces : list of int
        Faces restored by the split.
    """
    v_a: int = 0
    v_b_new: int = 0
    v_b_position: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    restored_faces: List[int] = field(default_factory=list)


@dataclass
class ProgressiveMesh:
    """Hoppe 1996 progressive mesh representation.

    The base mesh (M^0) is the coarsest representation; applying vertex-splits
    in order reconstructs progressively finer meshes up to M^n.

    Conversely: starting from M^n and applying edge-collapses yields M^0.

    Attributes
    ----------
    base_vertices : list of [x, y, z]
        Vertices of the coarsest (fully collapsed) mesh.
    base_faces : list of list[int]
        Faces of the coarsest mesh.
    collapses : list of EdgeCollapseRecord
        Ordered list of edge-collapse operations (finest → coarsest order).
        Apply all collapses starting from the fine mesh to get the base mesh.
    splits : list of VertexSplitRecord
        Ordered list of vertex-split operations (coarsest → finest order).
        Apply all splits starting from the base mesh to get the finest mesh.
    n_fine_vertices : int
        Vertex count of the original fine mesh (before any collapses).
    n_fine_faces : int
        Face count of the original fine mesh.
    n_base_vertices : int
        Vertex count of the base (fully collapsed) mesh.
    n_base_faces : int
        Face count of the base mesh.
    """
    base_vertices: List[List[float]] = field(default_factory=list)
    base_faces: List[List[int]] = field(default_factory=list)
    collapses: List[EdgeCollapseRecord] = field(default_factory=list)
    splits: List[VertexSplitRecord] = field(default_factory=list)
    n_fine_vertices: int = 0
    n_fine_faces: int = 0
    n_base_vertices: int = 0
    n_base_faces: int = 0


# ---------------------------------------------------------------------------
# QEM helper — per-vertex quadric accumulation
# ---------------------------------------------------------------------------

def _plane_quadric(a: float, b: float, c: float, d: float) -> List[float]:
    """Return the 10 unique entries of the 4×4 symmetric quadric Q = (v^T p)(p^T v).

    Plane equation: ax + by + cz + d = 0.
    Q = [a², ab, ac, ad, b², bc, bd, c², cd, d²]
    """
    return [
        a * a, a * b, a * c, a * d,
        b * b, b * c, b * d,
        c * c, c * d,
        d * d,
    ]


def _add_quadrics(q1: List[float], q2: List[float]) -> List[float]:
    return [q1[i] + q2[i] for i in range(10)]


def _eval_quadric(q: List[float], v: List[float]) -> float:
    """Evaluate v^T Q v for a 4-vector [x, y, z, 1]."""
    x, y, z = v[0], v[1], v[2]
    # Q = [[q0,q1,q2,q3],[q1,q4,q5,q6],[q2,q5,q7,q8],[q3,q6,q8,q9]]
    # vQv = sum over symmetric 4x4
    return (
        q[0] * x * x + 2 * q[1] * x * y + 2 * q[2] * x * z + 2 * q[3] * x
        + q[4] * y * y + 2 * q[5] * y * z + 2 * q[6] * y
        + q[7] * z * z + 2 * q[8] * z
        + q[9]
    )


def _face_plane(verts: List[List[float]], face: List[int]) -> Optional[Tuple[float, float, float, float]]:
    """Return (a, b, c, d) for the plane of face (first 3 vertices), or None."""
    if len(face) < 3:
        return None
    try:
        p0 = verts[face[0]]
        p1 = verts[face[1]]
        p2 = verts[face[2]]
        ux = p1[0] - p0[0]; uy = p1[1] - p0[1]; uz = p1[2] - p0[2]
        vx = p2[0] - p0[0]; vy = p2[1] - p0[1]; vz = p2[2] - p0[2]
        nx = uy * vz - uz * vy
        ny = uz * vx - ux * vz
        nz = ux * vy - uy * vx
        length = math.sqrt(nx * nx + ny * ny + nz * nz)
        if length < 1e-15:
            return None
        nx /= length; ny /= length; nz /= length
        d = -(nx * p0[0] + ny * p0[1] + nz * p0[2])
        return (nx, ny, nz, d)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# generate_progressive_mesh
# ---------------------------------------------------------------------------

def generate_progressive_mesh(
    cage: SubDMesh,
    n_collapses: Optional[int] = None,
) -> ProgressiveMesh:
    """Build a Hoppe-style progressive mesh from a SubD cage.

    Algorithm (Hoppe 1996 simplified, pure-Python):
    1. Triangulate the cage (quads → 2 triangles each).
    2. Build per-vertex quadric matrices Q_i as the sum of plane quadrics for
       all faces incident to vertex i.
    3. For each edge (v_a, v_b), compute the collapse cost:
       cost = min_{v} (v^T (Q_a + Q_b) v) evaluated at the midpoint.
    4. Greedily collapse the minimum-cost edge, updating adjacency.
    5. Record each collapse as an EdgeCollapseRecord; build the inverse
       VertexSplitRecord sequence.

    The resulting ProgressiveMesh stores:
    - base_vertices / base_faces: the fully-collapsed coarsest mesh.
    - collapses: ordered fine→coarse.
    - splits: ordered coarse→fine (inverse of collapses).

    Applying all vertex-splits to (base_vertices, base_faces) reconstructs the
    original fine mesh.  Applying k splits reconstructs an intermediate level.

    Parameters
    ----------
    cage : SubDMesh
        Input control cage.  For highest fidelity, pre-subdivide with
        ``catmull_clark_subdivide`` before calling this function.
    n_collapses : int or None
        Maximum number of edge collapses to perform.  None → collapse until
        no safe collapses remain (min 3 faces left).

    Returns
    -------
    ProgressiveMesh
        Never raises.
    """
    try:
        # --- 1. Triangulate cage ---
        verts: List[List[float]] = [list(v) for v in cage.vertices]
        tris: List[List[int]] = []
        for face in cage.faces:
            n = len(face)
            for i in range(1, n - 1):
                tris.append([face[0], face[i], face[i + 1]])

        n_fine_v = len(verts)
        n_fine_f = len(tris)

        if n_collapses is None:
            max_collapses = max(0, n_fine_f - 4)  # keep at least 4 triangles
        else:
            max_collapses = max(0, int(n_collapses))

        if not tris or n_fine_v < 3:
            return ProgressiveMesh(
                base_vertices=verts,
                base_faces=tris,
                collapses=[],
                splits=[],
                n_fine_vertices=n_fine_v,
                n_fine_faces=n_fine_f,
                n_base_vertices=n_fine_v,
                n_base_faces=n_fine_f,
            )

        # --- 2. Build vertex quadrics ---
        zero_q: List[float] = [0.0] * 10
        quadrics: List[List[float]] = [list(zero_q) for _ in range(len(verts))]

        # Active faces set (face index → list[int] or None if removed)
        active_faces: List[Optional[List[int]]] = [list(t) for t in tris]

        def _rebuild_quadrics() -> None:
            for i in range(len(quadrics)):
                quadrics[i] = list(zero_q)
            for fi, face in enumerate(active_faces):
                if face is None:
                    continue
                plane = _face_plane(verts, face)
                if plane is None:
                    continue
                q = _plane_quadric(*plane)
                for vi in face:
                    if 0 <= vi < len(quadrics):
                        quadrics[vi] = _add_quadrics(quadrics[vi], q)

        _rebuild_quadrics()

        # --- 3. Build edge set and collapse costs ---
        def _all_edges() -> Dict[Tuple[int, int], float]:
            edges: Dict[Tuple[int, int], float] = {}
            for face in active_faces:
                if face is None:
                    continue
                n = len(face)
                for i in range(n):
                    a = face[i]
                    b = face[(i + 1) % n]
                    key = (min(a, b), max(a, b))
                    if key not in edges:
                        q_combined = _add_quadrics(quadrics[a], quadrics[b])
                        mid = [
                            (verts[a][0] + verts[b][0]) / 2.0,
                            (verts[a][1] + verts[b][1]) / 2.0,
                            (verts[a][2] + verts[b][2]) / 2.0,
                        ]
                        cost = _eval_quadric(q_combined, mid)
                        edges[key] = max(0.0, cost)
            return edges

        collapses: List[EdgeCollapseRecord] = []
        splits: List[VertexSplitRecord] = []

        active_verts: set = set(range(len(verts)))

        def _do_collapse(n_collapses_max: int) -> None:
            for _ in range(n_collapses_max):
                if sum(1 for f in active_faces if f is not None) < 4:
                    break
                edges = _all_edges()
                if not edges:
                    break

                # Find minimum cost edge
                best_key = min(edges, key=lambda k: edges[k])
                v_a, v_b = best_key
                cost = edges[best_key]

                # Merged position = midpoint
                merged = [
                    (verts[v_a][0] + verts[v_b][0]) / 2.0,
                    (verts[v_a][1] + verts[v_b][1]) / 2.0,
                    (verts[v_a][2] + verts[v_b][2]) / 2.0,
                ]

                # Identify faces sharing the edge (to remove) and affected faces
                removed_faces: List[int] = []
                updated_faces: List[int] = []
                for fi, face in enumerate(active_faces):
                    if face is None:
                        continue
                    has_a = v_a in face
                    has_b = v_b in face
                    if has_a and has_b:
                        removed_faces.append(fi)
                    elif has_b:
                        updated_faces.append(fi)

                # Safety check: don't collapse if it would produce a degenerate mesh
                # (topological link condition — simplified: skip if > 2 shared faces)
                if len(removed_faces) > 2:
                    continue

                # Record the collapse
                old_pos_b = list(verts[v_b])
                old_pos_a = list(verts[v_a])

                collapses.append(EdgeCollapseRecord(
                    v_a=v_a,
                    v_b=v_b,
                    merged_position=list(merged),
                    removed_faces=list(removed_faces),
                    updated_faces=list(updated_faces),
                    qem_error=cost,
                ))

                # Corresponding vertex split record
                splits.insert(0, VertexSplitRecord(
                    v_a=v_a,
                    v_b_new=v_b,
                    v_b_position=old_pos_b,
                    restored_faces=list(removed_faces),
                ))

                # Apply: move v_a to merged, remove faces, remap v_b → v_a
                verts[v_a] = merged
                active_verts.discard(v_b)
                for fi in removed_faces:
                    active_faces[fi] = None
                for fi in updated_faces:
                    face = active_faces[fi]
                    if face is not None:
                        active_faces[fi] = [v_a if v == v_b else v for v in face]

                # Rebuild quadric for v_a
                quadrics[v_a] = _add_quadrics(quadrics[v_a], quadrics[v_b])

        _do_collapse(max_collapses)

        # Extract base mesh
        base_faces_out: List[List[int]] = [
            f for f in active_faces if f is not None
        ]
        # Remap vertex indices to compact form
        used_verts = sorted(set(v for f in base_faces_out for v in f))
        remap: Dict[int, int] = {old: new for new, old in enumerate(used_verts)}
        base_verts_out = [list(verts[v]) for v in used_verts]
        base_faces_remapped = [[remap[v] for v in f] for f in base_faces_out]

        return ProgressiveMesh(
            base_vertices=base_verts_out,
            base_faces=base_faces_remapped,
            collapses=collapses,
            splits=splits,
            n_fine_vertices=n_fine_v,
            n_fine_faces=n_fine_f,
            n_base_vertices=len(base_verts_out),
            n_base_faces=len(base_faces_remapped),
        )
    except Exception:
        try:
            verts_out = [list(v) for v in cage.vertices]
            tris_out: List[List[int]] = []
            for face in cage.faces:
                n = len(face)
                for i in range(1, n - 1):
                    tris_out.append([face[0], face[i], face[i + 1]])
            return ProgressiveMesh(
                base_vertices=verts_out,
                base_faces=tris_out,
                collapses=[],
                splits=[],
                n_fine_vertices=len(verts_out),
                n_fine_faces=len(tris_out),
                n_base_vertices=len(verts_out),
                n_base_faces=len(tris_out),
            )
        except Exception:
            return ProgressiveMesh()


# ---------------------------------------------------------------------------
# pick_lod_for_view
# ---------------------------------------------------------------------------

def pick_lod_for_view(
    chain: SubdLodChain,
    distance: float,
    viewport_pixels: float = 1080.0,
    fov_y: float = 60.0,
) -> int:
    """Select the most appropriate LOD level for the given viewing distance.

    Uses the screen-space projected pixel error model.  Returns the finest
    LOD whose projected RMS edge length covers at least 1 pixel at *distance*.
    When too far away for any detail to be visible (< 1 px), returns LOD 0.

    Parameters
    ----------
    chain : SubdLodChain
        LOD chain produced by :func:`generate_subd_lod_chain`.
    distance : float
        Viewing distance in world-space units (same as mesh vertex units).
        Must be > 0.
    viewport_pixels : float
        Viewport height in pixels (default 1080).
    fov_y : float
        Vertical field of view in degrees (default 60°).

    Returns
    -------
    int
        LOD index in [0, chain.n_levels - 1].  0 = coarsest, n-1 = finest.
        Returns 0 if chain is empty.  Never raises.
    """
    try:
        if not chain.levels:
            return 0
        n = chain.n_levels
        if n == 1:
            return 0

        distance = float(distance)
        if distance <= 0.0:
            return n - 1  # right on top of it → finest

        fov_rad = math.radians(max(1.0, min(179.0, float(fov_y))))
        half_tan = math.tan(fov_rad / 2.0)

        # Recompute pixel errors for each level using supplied viewport/fov.
        # This avoids storing the viewport params in SubdLodChain.
        best_lod = 0  # default: coarsest
        for i, mesh in enumerate(chain.levels):
            rms_e = _rms_edge_length(mesh)
            if half_tan <= 0.0 or distance <= 0.0:
                px_err = float("inf")
            else:
                px_err = viewport_pixels * rms_e / (2.0 * half_tan * distance)
            if px_err >= 1.0:
                best_lod = i  # this level is still visible; keep going finer

        return best_lod
    except Exception:
        if chain and chain.n_levels > 0:
            return 0
        return 0


# ---------------------------------------------------------------------------
# LLM tool registration (gated — mirrors subd.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    import json as _json  # noqa: F811

    _subd_generate_lod_chain_spec = ToolSpec(
        name="subd_generate_lod_chain",
        description=(
            "Generate an automatic LOD (level-of-detail) chain from a single "
            "SubD cage mesh using Catmull-Clark subdivision.\n"
            "\n"
            "LOD 0 = the cage itself (lowest detail, fastest rendering).\n"
            "LOD i = LOD i-1 subdivided one additional CC level.\n"
            "Each level has approximately 4× the triangles of the previous.\n"
            "\n"
            "Use this to produce multi-resolution meshes for distance-based "
            "culling in real-time rendering.  The returned chain includes per-"
            "level vertex/triangle counts and viewing-distance thresholds.\n"
            "\n"
            "Optionally call with 'pick_distance' to get the recommended LOD "
            "index for a specific viewing distance.\n"
            "\n"
            "Returns:\n"
            "  ok                : bool\n"
            "  n_levels          : int — total levels (n_levels+1 incl. cage)\n"
            "  vertex_counts     : [int, ...]  — per level\n"
            "  triangle_counts   : [int, ...]  — per level\n"
            "  switch_distances  : [float, ...] — 1-pixel switch-in distance per level\n"
            "  recommended_lod   : int | null — only if pick_distance supplied\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Control-cage vertices as [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Control-cage face vertex-index lists.",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "creases": {
                    "type": "array",
                    "description": "Optional crease list [{v1,v2,value}].",
                    "items": {
                        "type": "object",
                        "properties": {
                            "v1": {"type": "integer"},
                            "v2": {"type": "integer"},
                            "value": {"type": "number"},
                        },
                        "required": ["v1", "v2", "value"],
                    },
                },
                "n_levels": {
                    "type": "integer",
                    "description": "Number of CC refinement levels (1..8, default 4).",
                    "default": 4,
                },
                "pick_distance": {
                    "type": "number",
                    "description": (
                        "Optional viewing distance (world units). "
                        "If supplied, 'recommended_lod' is returned."
                    ),
                },
                "viewport_pixels": {
                    "type": "number",
                    "description": "Viewport height in pixels for LOD picking (default 1080).",
                    "default": 1080.0,
                },
                "fov_y": {
                    "type": "number",
                    "description": "Vertical field of view in degrees for LOD picking (default 60).",
                    "default": 60.0,
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_generate_lod_chain_spec)
    async def run_subd_generate_lod_chain(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])
        n_levels = int(a.get("n_levels", 4))
        pick_distance = a.get("pick_distance")
        viewport_pixels = float(a.get("viewport_pixels", 1080.0))
        fov_y = float(a.get("fov_y", 60.0))

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if n_levels < 1 or n_levels > 8:
            return err_payload("n_levels must be 1..8", "BAD_ARGS")

        try:
            mesh = SubDMesh(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid mesh: {exc}", "BAD_ARGS")

        for ce in raw_creases:
            try:
                mesh.set_crease(int(ce["v1"]), int(ce["v2"]), float(ce["value"]))
            except Exception:
                pass

        chain = generate_subd_lod_chain(
            mesh,
            n_levels=n_levels,
            viewport_pixels=viewport_pixels,
            fov_y=fov_y,
        )

        payload: dict = {
            "ok": True,
            "n_levels": chain.n_levels,
            "vertex_counts": chain.vertex_counts,
            "triangle_counts": chain.triangle_counts,
            "switch_distances": chain.switch_distances,
            "recommended_lod": None,
        }

        if pick_distance is not None:
            try:
                lod = pick_lod_for_view(
                    chain,
                    distance=float(pick_distance),
                    viewport_pixels=viewport_pixels,
                    fov_y=fov_y,
                )
                payload["recommended_lod"] = lod
            except Exception:
                pass

        return ok_payload(payload)
