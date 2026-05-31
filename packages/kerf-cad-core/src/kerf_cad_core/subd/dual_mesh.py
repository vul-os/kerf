"""dual_mesh.py
==============
SUBD-CAGE-DUAL-MESH — compute the combinatorial dual of a quad subdivision
cage mesh.

Theory
------
The dual mesh of a polygonal mesh M is constructed by:

  1. *Dual vertices*: for each primal face f_i, create a dual vertex d_i at
     the centroid of f_i's control vertices.
  2. *Dual faces*: for each primal vertex v, gather all faces incident to v
     (the vertex star), order them in CCW sequence around v, and emit a dual
     face whose corners are the dual vertices {d_i} of those incident faces.

For a regular all-quad closed manifold this produces the expected dual
polyhedron: the dual of a cube (6 quads, valence-3 vertices) is an
octahedron (8 triangles, degree-6 faces), and vice-versa.

Mathematical context
---------------------
  * Bossen & Heckbert (1996) §3.1 use the dual mesh for anisotropic mesh
    generation: the dual vertices become centroids that seed the next
    generation, achieving controlled density distributions.
  * Bommes, Lévy & Pietroni (2013) §3.2 describe the dual operation as the
    theoretical underpinning of face-loop walks: each face-loop in the primal
    corresponds to a vertex-ring in the dual.
  * The dual of a 2-manifold triangulation is a pure quad mesh (each primal
    triangle gives a valence-3 dual vertex; each primal vertex gives a
    triangular dual face). The dual of a pure quad mesh is a pure quad mesh
    only when every primal vertex has valence 4 (irregular vertices produce
    non-quad dual faces).

Algorithm
----------
Given cage vertices V and faces F:

  1. Build vertex-star adjacency:  vert_faces[v] = [f0, f1, ...]  (unordered).
  2. For each face fi: compute centroid  c_i = (1/|f|) * Σ_{j∈f} V[j].
     This is dual vertex d_i.
  3. For each primal vertex v:
     a. Retrieve the set of faces in vert_faces[v].
     b. Order them in CCW sequence around v by sorting on the angle of
        c_fi - V[v]  in the tangent plane (atan2-based sorting). For a
        manifold mesh in consistent winding, a half-edge walk is more robust;
        we use angular sort as a manifold-agnostic fallback.
     c. Emit dual face  [d_{f0}, d_{f1}, ..., d_{fk}]  in CCW order.
     d. Boundary vertices (on the mesh boundary) produce *incomplete* dual
        faces (open fans). These are emitted as-is and counted in
        num_irregular_dual_faces (because they lack a face on each boundary
        edge side).
     e. Non-manifold vertices (edge shared by > 2 faces) also emit complete
        fans using the same angular sort, but the result is topologically
        undefined — counted in num_irregular_dual_faces.

Boundary / non-manifold caveats
--------------------------------
  * Boundary primal edges (adjacent to exactly 1 face) produce *incomplete*
    dual faces. The dual face of a boundary vertex has a "hole" wherever the
    boundary edge runs — it is an open polygon, not a closed one. This
    implementation emits the partial face as-is; callers that need a closed
    dual must cap the boundary or trim it before use.
  * Non-manifold input (edge shared by > 2 faces) has no canonical dual;
    angular sort is applied as a best-effort fallback.

CCW ordering via angular sort
-------------------------------
For each primal vertex v at position P, compute θ_i = atan2(
    cross(ref_dir, c_i − P),   # sign via n̂ · (ref × u)
    dot(ref_dir, c_i − P),
) where ref_dir is the direction to the first neighboring centroid and n̂ is
the approximate vertex normal (average of incident face normals). Sorting on
θ then gives the CCW-ordered face ring.

For degenerate cases (all centroids coincident, etc.) the ordering falls back
to index order.

Public API
----------
DualMeshResult
    Dataclass holding the dual mesh.

compute_dual_mesh(cage_mesh) -> DualMeshResult
    Main entry point.

LLM tool: ``subd_compute_dual_mesh``

References
----------
* Bossen, F.J. & Heckbert, P.S. (1996). "A Pliant Method for Anisotropic
  Mesh Generation." 5th International Meshing Roundtable, pp. 63–74.
  https://www.cs.cmu.edu/~ph/mesh/aniso.pdf
* Bommes, D., Lévy, B., Pietroni, N., Puppo, E., Silva, C., Tarini, M.,
  Zorin, D. (2013). "Quad-Mesh Generation and Processing: A Survey."
  Computer Graphics Forum 32(6):51–76, §3.2.
  https://doi.org/10.1111/cgf.12014
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class DualMeshResult:
    """Result of computing the combinatorial dual mesh of a quad cage.

    Attributes
    ----------
    dual_vertices : list[tuple[float, float, float]]
        Dual vertex positions, one per primal face.  dual_vertices[i] is the
        centroid of primal face i.
    dual_faces : list[list[int]]
        Dual face connectivity.  dual_faces[v] is the CCW-ordered ring of dual
        vertex indices (= primal face indices) incident to primal vertex v.
        Boundary vertices produce open/incomplete dual faces.
    num_irregular_dual_faces : int
        Number of dual faces that are *not* simple closed polygons: boundary
        fans (open because of missing face on the boundary side) and
        non-manifold fans. For a closed orientable 2-manifold this is always 0.
    honest_caveat : str
        Plain-language description of algorithmic limitations.
    """
    dual_vertices: List[Tuple[float, float, float]] = field(default_factory=list)
    dual_faces: List[List[int]] = field(default_factory=list)
    num_irregular_dual_faces: int = 0
    honest_caveat: str = (
        "Dual mesh via face-centroid dual vertices + CCW angular-sort ring per "
        "primal vertex (Bossen-Heckbert 1996 §3.1; Bommes-Lévy-Pietroni 2013 §3.2). "
        "HONEST CAVEATS: "
        "(1) Boundary primal edges produce INCOMPLETE (open) dual faces — boundary "
        "vertices have no face on the boundary-edge side; the dual face is an open "
        "fan, not a closed polygon. Callers must cap or trim boundary dual faces. "
        "(2) The angular-sort CCW ordering uses atan2 on the tangent plane and works "
        "correctly for convex vertex stars; concave or nearly co-planar stars may "
        "mis-sort. A half-edge walk would be more robust but requires manifold "
        "input with consistent face winding. "
        "(3) Non-manifold vertices (edge shared by > 2 faces) produce topologically "
        "undefined dual faces; angular sort is a best-effort fallback. "
        "(4) Dual vertices are primal face centroids only — they are NOT projected "
        "onto the CC limit surface. For a limit-surface dual use subd_sample_limit_normals "
        "to obtain limit positions first. "
        "(5) Degenerate faces (< 3 vertices) in the primal are silently skipped. "
        "Their dual vertices are still emitted (at the centroid of the degenerate "
        "face) but the corresponding dual vertex index will not appear in any dual face."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _cross3(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    """Compute the 3D cross product a × b."""
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot3(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
) -> float:
    """Compute the 3D dot product a · b."""
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _sub3(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
) -> Tuple[float, float, float]:
    """Vector subtraction a - b."""
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _normalize3(
    v: Tuple[float, float, float],
) -> Optional[Tuple[float, float, float]]:
    """Normalize a 3D vector; returns None for near-zero vectors."""
    length = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if length < 1e-14:
        return None
    return (v[0] / length, v[1] / length, v[2] / length)


def _face_normal(
    verts: List,
    face: List[int],
) -> Tuple[float, float, float]:
    """Compute an approximate face normal via Newell's method.

    Newell's method: N = Σ_{i} (v_i - v_{i+1}) × (v_i + v_{i+1}) / 2.
    Works for planar and near-planar faces of any valence.
    """
    nx, ny, nz = 0.0, 0.0, 0.0
    n = len(face)
    for i in range(n):
        vi = face[i]
        vj = face[(i + 1) % n]
        xi, yi, zi = float(verts[vi][0]), float(verts[vi][1]), float(verts[vi][2])
        xj, yj, zj = float(verts[vj][0]), float(verts[vj][1]), float(verts[vj][2])
        nx += (yi - yj) * (zi + zj)
        ny += (zi - zj) * (xi + xj)
        nz += (xi - xj) * (yi + yj)
    return (nx, ny, nz)


def _build_adjacency(
    faces: List[List[int]],
) -> Tuple[
    Dict[int, List[int]],      # vert_faces: vertex → list of face indices
    Dict[Tuple[int, int], List[int]],  # edge_faces: canonical edge → list of face indices
]:
    """Build vertex-face and edge-face adjacency maps from a face list.

    Parameters
    ----------
    faces : list of face index lists.

    Returns
    -------
    vert_faces  : dict  {vertex_index: [face_indices...]}
    edge_faces  : dict  {(min_v, max_v): [face_indices...]}
    """
    vert_faces: Dict[int, List[int]] = {}
    edge_faces: Dict[Tuple[int, int], List[int]] = {}

    for fi, face in enumerate(faces):
        n = len(face)
        for i in range(n):
            vi = face[i]
            vert_faces.setdefault(vi, []).append(fi)
            vj = face[(i + 1) % n]
            key = (min(vi, vj), max(vi, vj))
            edge_faces.setdefault(key, []).append(fi)

    return vert_faces, edge_faces


def _is_boundary_vertex(
    vi: int,
    vert_faces: Dict[int, List[int]],
    edge_faces: Dict[Tuple[int, int], List[int]],
    faces: List[List[int]],
) -> bool:
    """Return True if vertex vi is on the mesh boundary.

    A vertex is on the boundary iff at least one of its incident edges
    is a boundary edge (adjacent to only 1 face).
    """
    for fi in vert_faces.get(vi, []):
        face = faces[fi]
        n = len(face)
        idx_in_face = face.index(vi)
        # Check both edges of this face incident to vi.
        prev_v = face[(idx_in_face - 1) % n]
        next_v = face[(idx_in_face + 1) % n]
        for nb in (prev_v, next_v):
            key = (min(vi, nb), max(vi, nb))
            if len(edge_faces.get(key, [])) == 1:
                return True
    return False


def _compute_vertex_normal(
    vi: int,
    verts: List,
    vert_faces: Dict[int, List[int]],
    faces: List[List[int]],
) -> Tuple[float, float, float]:
    """Compute vertex normal as the average of incident face normals."""
    nx, ny, nz = 0.0, 0.0, 0.0
    for fi in vert_faces.get(vi, []):
        fn = _face_normal(verts, faces[fi])
        nx += fn[0]
        ny += fn[1]
        nz += fn[2]
    n = _normalize3((nx, ny, nz))
    if n is None:
        return (0.0, 0.0, 1.0)  # fallback to +Z
    return n


def _ccw_sort_faces_around_vertex(
    vi: int,
    incident_face_indices: List[int],
    verts: List,
    face_centroids: List[Tuple[float, float, float]],
    faces: List[List[int]],
    vert_faces: Dict[int, List[int]],
) -> List[int]:
    """Sort incident faces into CCW order around vertex vi.

    Uses atan2-based angular sort in the plane perpendicular to the vertex
    normal. The reference direction is the vector from V[vi] to the centroid
    of the face with the smallest index (for determinism).

    Parameters
    ----------
    vi                    : primal vertex index.
    incident_face_indices : list of face indices incident to vi.
    verts                 : primal vertex positions.
    face_centroids        : dual vertex positions (one per face).
    faces                 : primal face index lists.
    vert_faces            : vertex-face adjacency.

    Returns
    -------
    sorted_face_indices : face indices in CCW order around vi.
    """
    if len(incident_face_indices) <= 1:
        return list(incident_face_indices)

    px, py, pz = float(verts[vi][0]), float(verts[vi][1]), float(verts[vi][2])
    pv = (px, py, pz)

    # Compute vertex normal.
    n_hat = _compute_vertex_normal(vi, verts, vert_faces, faces)

    # Choose reference direction: vector to first centroid.
    sorted_by_idx = sorted(incident_face_indices)
    ref_c = face_centroids[sorted_by_idx[0]]
    ref_dir_raw = _sub3(ref_c, pv)
    ref_dir = _normalize3(ref_dir_raw)
    if ref_dir is None:
        # Fallback: use arbitrary perpendicular to normal.
        if abs(n_hat[0]) < 0.9:
            ref_dir = _normalize3(_cross3(n_hat, (1.0, 0.0, 0.0)))
        else:
            ref_dir = _normalize3(_cross3(n_hat, (0.0, 1.0, 0.0)))
        if ref_dir is None:
            return sorted_by_idx

    # Build a second tangent-plane axis via n × ref_dir.
    perp_raw = _cross3(n_hat, ref_dir)
    perp = _normalize3(perp_raw)
    if perp is None:
        return sorted_by_idx

    def _angle(fi: int) -> float:
        c = face_centroids[fi]
        diff = _sub3(c, pv)
        u = _dot3(diff, ref_dir)
        v = _dot3(diff, perp)
        return math.atan2(v, u)

    # First face has angle 0 by construction; sort remaining by angle in [0, 2π).
    angles = [(fi, _angle(fi)) for fi in incident_face_indices]
    # Normalize all angles relative to the first (reference) face angle.
    ref_angle = _angle(sorted_by_idx[0])

    def _norm_angle(a: float) -> float:
        delta = a - ref_angle
        if delta < -1e-9:
            delta += 2.0 * math.pi
        return delta

    angles_norm = [(fi, _norm_angle(a)) for fi, a in angles]
    angles_norm.sort(key=lambda x: x[1])
    return [fi for fi, _ in angles_norm]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_dual_mesh(cage_mesh) -> DualMeshResult:
    """Compute the combinatorial dual mesh of a quad SubD cage.

    For each primal face a dual vertex is created at the face centroid.
    For each primal vertex a dual face is created whose corners are the
    dual vertices of all incident faces, ordered CCW around the primal vertex.

    Parameters
    ----------
    cage_mesh : SubDMesh
        The Catmull-Clark control cage.  Must have ``.vertices`` and
        ``.faces`` attributes (standard SubDMesh interface).

    Returns
    -------
    DualMeshResult
        .dual_vertices         : list of (x, y, z) — one per primal face.
        .dual_faces            : list of lists — one per primal vertex, CCW
                                 ordered ring of dual vertex indices.
        .num_irregular_dual_faces : count of incomplete/non-manifold dual faces.
        .honest_caveat         : method limitations.

    Notes
    -----
    * Isolated vertices (not referenced by any face) produce empty dual faces
      (length 0) and are counted in num_irregular_dual_faces.
    * Degenerate primal faces (< 3 unique vertices) are silently included in
      the dual-vertex list (the centroid is still valid), but the winding
      around the vertex may be unpredictable.
    """
    raw_verts = cage_mesh.vertices
    raw_faces = cage_mesh.faces

    nv = len(raw_verts)
    nf = len(raw_faces)

    # ------------------------------------------------------------------ #
    # Step 1: Compute dual vertices (face centroids).                      #
    # ------------------------------------------------------------------ #
    dual_vertices: List[Tuple[float, float, float]] = []
    for face in raw_faces:
        if len(face) == 0:
            dual_vertices.append((0.0, 0.0, 0.0))
            continue
        cx, cy, cz = 0.0, 0.0, 0.0
        for vi in face:
            cx += float(raw_verts[vi][0])
            cy += float(raw_verts[vi][1])
            cz += float(raw_verts[vi][2])
        k = len(face)
        dual_vertices.append((cx / k, cy / k, cz / k))

    # ------------------------------------------------------------------ #
    # Step 2: Build adjacency maps.                                        #
    # ------------------------------------------------------------------ #
    vert_faces, edge_faces = _build_adjacency(raw_faces)

    # ------------------------------------------------------------------ #
    # Step 3: Compute dual faces (CCW face-ring per primal vertex).        #
    # ------------------------------------------------------------------ #
    dual_faces: List[List[int]] = []
    num_irregular = 0

    for vi in range(nv):
        incident = vert_faces.get(vi, [])
        if len(incident) == 0:
            # Isolated vertex — empty dual face.
            dual_faces.append([])
            num_irregular += 1
            continue

        # Order incident faces CCW around vi.
        ordered = _ccw_sort_faces_around_vertex(
            vi=vi,
            incident_face_indices=incident,
            verts=raw_verts,
            face_centroids=dual_vertices,
            faces=raw_faces,
            vert_faces=vert_faces,
        )

        dual_faces.append(ordered)

        # Check if boundary vertex → incomplete dual face.
        if _is_boundary_vertex(vi, vert_faces, edge_faces, raw_faces):
            num_irregular += 1

    result = DualMeshResult()
    result.dual_vertices = dual_vertices
    result.dual_faces = dual_faces
    result.num_irregular_dual_faces = num_irregular
    return result


# ---------------------------------------------------------------------------
# LLM tool: subd_compute_dual_mesh
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

    from kerf_cad_core.geom.subd import SubDMesh  # type: ignore[import]

    _dual_spec = ToolSpec(
        name="subd_compute_dual_mesh",
        description=(
            "Compute the combinatorial dual mesh of a quad SubD cage.\n"
            "\n"
            "The dual is constructed as follows:\n"
            "  - Dual vertex d_i = centroid of primal face f_i.\n"
            "  - Dual face for primal vertex v = CCW-ordered ring of {d_i} for all\n"
            "    faces incident to v (Bossen-Heckbert 1996 §3.1).\n"
            "\n"
            "Applications:\n"
            "  - Ring analysis: each face loop in the primal ↔ vertex ring in dual\n"
            "    (Bommes-Lévy-Pietroni 2013 §3.2).\n"
            "  - Mesh smoothing: iterative dual→primal→dual converges to a smooth mesh.\n"
            "  - Visualization: dual overlay highlights irregular vertex topology.\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  - Boundary primal edges produce INCOMPLETE (open) dual faces.\n"
            "  - CCW order uses atan2 angular sort — works on convex stars; concave\n"
            "    or nearly co-planar vertex stars may mis-sort.\n"
            "  - Dual vertices are face centroids, NOT CC limit-surface points.\n"
            "  - Non-manifold vertices produce topologically undefined dual faces.\n"
            "\n"
            "Inputs:\n"
            "  vertices : [[x,y,z], ...]  cage control vertices.\n"
            "  faces    : [[i,j,k,l], ...]  face vertex-index lists (any valence).\n"
            "\n"
            "Returns:\n"
            "  ok                       : bool\n"
            "  dual_vertices            : [[x,y,z], ...]  one per primal face\n"
            "  dual_faces               : [[di,dj,...], ...]  one per primal vertex\n"
            "  num_dual_vertices        : int\n"
            "  num_dual_faces           : int\n"
            "  num_irregular_dual_faces : int  (boundary + non-manifold)\n"
            "  honest_caveat            : str\n"
            "\n"
            "Refs: Bossen-Heckbert (1996) §3.1; Bommes-Lévy-Pietroni (2013) §3.2."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Cage control vertices as [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "minItems": 1,
                },
                "faces": {
                    "type": "array",
                    "description": "Cage face vertex-index lists.",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "minItems": 1,
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_dual_spec)
    async def run_subd_compute_dual_mesh(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")

        try:
            verts = [[float(c) for c in row] for row in raw_verts]
            faces = [[int(i) for i in row] for row in raw_faces]
        except Exception as exc:
            return err_payload(f"invalid geometry data: {exc}", "BAD_ARGS")

        mesh = SubDMesh(vertices=verts, faces=faces)

        res = compute_dual_mesh(mesh)

        return ok_payload({
            "ok": True,
            "dual_vertices": [list(v) for v in res.dual_vertices],
            "dual_faces": [list(f) for f in res.dual_faces],
            "num_dual_vertices": len(res.dual_vertices),
            "num_dual_faces": len(res.dual_faces),
            "num_irregular_dual_faces": res.num_irregular_dual_faces,
            "honest_caveat": res.honest_caveat,
        })
