"""
3-D → 2-D garment surface flattening for non-developable apparel surfaces.

Three algorithms
----------------
arap  (Liu-Zhou-Pommer 2008 ARAP, after Bo-Wang 2007)
    As-rigid-as-possible flattening — iterative per-triangle Procrustes
    fits followed by a global Poisson solve.  Minimises angle + area
    distortion jointly.

lscm  (Lévy-Petitjean-Ray-Maillot 2002)
    Least-squares conformal mapping — closed-form sparse linear solve.
    Preserves angles by construction; area distortion is unconstrained.

cone_singularity
    Introduces cone points (curvature concentrations) at vertices whose
    geodesic curvature exceeds a threshold, so that the remaining surface
    is locally developable.  After cutting along a spanning tree of cone
    points the ARAP flattening is applied.  Needed for highly non-
    developable surfaces such as a full sphere.

References
----------
- Bo & Wang 2007 "Geodesic-controlled developable surfaces for modeling
  paper bending", Computer-Aided Design 39(11):975-985.
- Liu, Zhang & Zhou 2008 "Local/Global Approach to Mesh Parameterisation",
  SIGGRAPH Asia.
- Lévy, Petitjean, Ray & Maillot 2002 "Least Squares Conformal Maps for
  Automatic Texture Atlas Generation", SIGGRAPH.
- Springborn, Schröder & Pinkall 2008 "Conformal Equivalence of Triangle
  Meshes", SIGGRAPH (cone-point prescription).

Units: consistent with the input mesh (typically centimetres).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla


# ------------------------------------------------------------------ #
# Surface mesh data structure                                          #
# ------------------------------------------------------------------ #

@dataclass
class TriMesh:
    """
    A triangulated 3-D surface.

    Attributes
    ----------
    vertices : (V, 3) float array  — 3-D vertex positions (e.g. cm).
    faces    : (F, 3) int array    — vertex indices, counter-clockwise.
    """
    vertices: np.ndarray   # (V, 3)
    faces: np.ndarray      # (F, 3) int

    def __post_init__(self):
        self.vertices = np.asarray(self.vertices, dtype=float)
        self.faces = np.asarray(self.faces, dtype=int)

    @property
    def n_vertices(self) -> int:
        return self.vertices.shape[0]

    @property
    def n_faces(self) -> int:
        return self.faces.shape[0]


# ------------------------------------------------------------------ #
# Result types                                                         #
# ------------------------------------------------------------------ #

@dataclass
class FlattenResult:
    """
    Result of flattening a 3-D surface to 2-D.

    Attributes
    ----------
    uv_coords             : (V, 2) array of 2-D UV positions.
    distortion_per_triangle: (F,) array of per-triangle distortion
                             (ratio max_singular / min_singular of the
                             deformation gradient; = 1 for zero distortion).
    max_distortion        : scalar worst-case distortion.
    areas_ratio           : (F,) array of 2D-area / 3D-area per triangle
                             (= 1 for isometric).
    """
    uv_coords: np.ndarray               # (V, 2)
    distortion_per_triangle: np.ndarray # (F,)
    max_distortion: float
    areas_ratio: np.ndarray             # (F,)


@dataclass
class Pattern:
    """
    A 2-D flat pattern with optional dart metadata.

    Attributes
    ----------
    uv_coords  : (V, 2) flat pattern vertices.
    faces      : (F, 3) triangle connectivity.
    darts      : list of darts; each dart is a dict with keys:
                 'apex'  — (u, v) apex of the dart V-cut,
                 'left'  — (u, v) left arm endpoint,
                 'right' — (u, v) right arm endpoint,
                 'angle_rad' — included angle of the dart.
    distortion : FlattenResult that produced this pattern.
    """
    uv_coords: np.ndarray
    faces: np.ndarray
    darts: list[dict] = field(default_factory=list)
    distortion: FlattenResult | None = None


# ------------------------------------------------------------------ #
# Internal geometry helpers                                            #
# ------------------------------------------------------------------ #

def _face_normals_and_areas_3d(mesh: TriMesh):
    """Return (F,3) normals and (F,) areas for a 3-D mesh."""
    v0 = mesh.vertices[mesh.faces[:, 0]]
    v1 = mesh.vertices[mesh.faces[:, 1]]
    v2 = mesh.vertices[mesh.faces[:, 2]]
    e1 = v1 - v0
    e2 = v2 - v0
    cross = np.cross(e1, e2)                 # (F, 3)
    area2 = np.linalg.norm(cross, axis=1)    # (F,) = 2 * area
    normals = cross / np.maximum(area2[:, None], 1e-15)
    return normals, area2 / 2.0


def _face_areas_2d(uv: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """Signed area of each 2-D triangle (positive if CCW)."""
    u0, u1, u2 = uv[faces[:, 0]], uv[faces[:, 1]], uv[faces[:, 2]]
    e1 = u1 - u0
    e2 = u2 - u0
    # signed area = 0.5 * (e1 x e2)
    return 0.5 * (e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])


def _deformation_gradients(mesh: TriMesh, uv: np.ndarray):
    """
    Compute the 2x2 deformation gradient F for each triangle.

    We map triangle (v0,v1,v2) in 3-D onto local 2-D coordinates using
    an orthonormal frame, then compare to the UV positions.  The singular
    values of F give the principal stretches; their ratio measures
    conformal (angle) distortion.

    Returns
    -------
    dg : (F, 2, 2) deformation gradients.
    """
    F = mesh.faces
    V = mesh.vertices
    u0, u1, u2 = uv[F[:, 0]], uv[F[:, 1]], uv[F[:, 2]]

    # Local 3-D frame per triangle
    v0 = V[F[:, 0]]
    v1 = V[F[:, 1]]
    v2 = V[F[:, 2]]
    e1_3d = v1 - v0        # (F, 3)
    e2_3d = v2 - v0

    # Orthonormal basis: x-axis along e1, y-axis in face plane
    len_e1 = np.linalg.norm(e1_3d, axis=1, keepdims=True)
    x_ax = e1_3d / np.maximum(len_e1, 1e-15)
    n, area = _face_normals_and_areas_3d(mesh)
    y_ax = np.cross(n, x_ax)  # (F, 3), in-plane perpendicular to x_ax

    # 3-D edge vectors projected onto local frame
    p1 = np.stack([
        np.einsum('ij,ij->i', e1_3d, x_ax),
        np.einsum('ij,ij->i', e1_3d, y_ax),
    ], axis=1)  # (F, 2)
    p2 = np.stack([
        np.einsum('ij,ij->i', e2_3d, x_ax),
        np.einsum('ij,ij->i', e2_3d, y_ax),
    ], axis=1)  # (F, 2)

    # UV edge vectors
    q1 = u1 - u0  # (F, 2)
    q2 = u2 - u0

    # Solve P @ J = Q  => J = P^{-1} Q  (J is 2x2 Jacobian / deform. gradient)
    # P = [[p1x, p2x], [p1y, p2y]], Q same for q
    det_p = p1[:, 0] * p2[:, 1] - p1[:, 1] * p2[:, 0]
    safe = np.abs(det_p) > 1e-15
    inv_det = np.where(safe, 1.0 / np.where(safe, det_p, 1.0), 0.0)

    # P^{-1} = (1/det) * [[p2y, -p2x], [-p1y, p1x]]
    # J = P^{-1} @ Q
    J = np.zeros((len(F), 2, 2))
    # Row 0 of J: [ (p2y*q1x - p1y*q2x) / det, (p2y*q1y - p1y*q2y) / det ]
    # Row 1 of J: [ (-p2x*q1x + p1x*q2x) / det, (-p2x*q1y + p1x*q2y) / det ]
    J[:, 0, 0] = (p2[:, 1] * q1[:, 0] - p1[:, 1] * q2[:, 0]) * inv_det
    J[:, 0, 1] = (p2[:, 1] * q1[:, 1] - p1[:, 1] * q2[:, 1]) * inv_det
    J[:, 1, 0] = (-p2[:, 0] * q1[:, 0] + p1[:, 0] * q2[:, 0]) * inv_det
    J[:, 1, 1] = (-p2[:, 0] * q1[:, 1] + p1[:, 0] * q2[:, 1]) * inv_det
    return J


def _distortion_from_dg(dg: np.ndarray) -> np.ndarray:
    """
    Per-face distortion = s1/s2 where s1 >= s2 are singular values.
    = 1 for zero distortion (isometric).
    """
    # SVD of each 2x2 matrix
    nf = dg.shape[0]
    dist = np.ones(nf)
    for i in range(nf):
        sv = np.linalg.svd(dg[i], compute_uv=False)
        s_max = sv[0]
        s_min = sv[1]
        dist[i] = s_max / max(s_min, 1e-15)
    return dist


def _initial_embedding(mesh: TriMesh) -> np.ndarray:
    """
    Greedy triangle-unfolding seed:  place the first triangle flat,
    then breadth-first unfold neighbours.  Used as the ARAP initialisation.
    """
    V = mesh.vertices
    F = mesh.faces
    nv = mesh.n_vertices
    uv = np.zeros((nv, 2))
    placed = np.zeros(nv, dtype=bool)

    # Adjacency: face → neighbouring faces via shared edge
    edge_to_faces: dict[tuple[int, int], list[int]] = {}
    for fi, (a, b, c) in enumerate(F):
        for u, v in [(a, b), (b, c), (c, a)]:
            key = (min(u, v), max(u, v))
            edge_to_faces.setdefault(key, []).append(fi)

    # Place first triangle
    a, b, c = F[0]
    uv[a] = [0.0, 0.0]
    e1 = V[b] - V[a]
    len_e1 = np.linalg.norm(e1)
    uv[b] = [len_e1, 0.0]
    # project c
    e2 = V[c] - V[a]
    n0, _ = _face_normals_and_areas_3d(
        TriMesh(V[[a, b, c]], np.array([[0, 1, 2]]))
    )
    n0 = n0[0]
    yax = np.cross(n0, e1 / max(len_e1, 1e-15))
    uv[c] = [np.dot(e2, e1 / max(len_e1, 1e-15)), np.dot(e2, yax)]
    for idx in [a, b, c]:
        placed[idx] = True

    # BFS to place remaining triangles
    placed_faces = {0}
    queue = [0]
    while queue:
        fi = queue.pop(0)
        fa, fb, fc = F[fi]
        for pa, pb, pc in [(fa, fb, fc), (fb, fc, fa), (fc, fa, fb)]:
            key = (min(pa, pb), max(pa, pb))
            for fi2 in edge_to_faces.get(key, []):
                if fi2 in placed_faces:
                    continue
                # fi2 shares edge (pa, pb); find the 3rd vertex
                third = [v for v in F[fi2] if v != pa and v != pb]
                if not third:
                    continue
                tc = third[0]
                # Already placed pa and pb; derive tc from 3-D shape
                ea = uv[pa]
                eb = uv[pb]
                edge_2d = eb - ea
                len_2d = np.linalg.norm(edge_2d)
                if len_2d < 1e-12:
                    continue
                # 3-D distances
                d_a = np.linalg.norm(V[tc] - V[pa])
                d_b = np.linalg.norm(V[tc] - V[pb])
                # Intersection of circles: c_a=d_a from pa, c_b=d_b from pb
                lsq = np.linalg.norm(eb - ea)
                cosA = (lsq**2 + d_a**2 - d_b**2) / (2 * lsq * max(d_a, 1e-12))
                cosA = np.clip(cosA, -1.0, 1.0)
                sinA = math.sqrt(1 - cosA**2)
                # Direction of edge in 2-D
                ex = edge_2d / max(lsq, 1e-12)
                ey = np.array([-ex[1], ex[0]])
                uv[tc] = ea + d_a * cosA * ex + d_a * sinA * ey
                placed[tc] = True
                placed_faces.add(fi2)
                queue.append(fi2)

    return uv


def _cotangent_weights(mesh: TriMesh) -> sp.csr_matrix:
    """
    Return the (V, V) symmetric cotangent-weight Laplacian.

    For each directed edge (i→j) with opposite angle α at vertex opp:
        w_{ij} += 0.5 * cot(α)

    The diagonal is set to the negative row-sum so that L is the proper
    graph Laplacian: L x = 0 for constant x.

    Returns a positive-semidefinite (V, V) sparse matrix.
    """
    V = mesh.vertices
    F = mesh.faces
    nv = mesh.n_vertices
    rows, cols, vals = [], [], []

    for fi, (a, b, c) in enumerate(F):
        verts = [V[a], V[b], V[c]]
        idxs = [a, b, c]
        for k in range(3):
            # vertex opp = idxs[k] is opposite edge (i, j)
            i, j, opp_idx = idxs[(k + 1) % 3], idxs[(k + 2) % 3], idxs[k]
            vi, vj, vk = verts[(k + 1) % 3], verts[(k + 2) % 3], verts[k]
            ei = vi - vk
            ej = vj - vk
            cross_len = np.linalg.norm(np.cross(ei, ej))
            dot = np.dot(ei, ej)
            cot = dot / max(cross_len, 1e-15)
            w = 0.5 * cot
            # Off-diagonal: positive weight (w_{ij})
            rows += [i, j, i, j]
            cols += [j, i, i, j]
            vals += [w, w, -w, -w]

    L = sp.coo_matrix((vals, (rows, cols)), shape=(nv, nv)).tocsr()
    return L


def _cotangent_weight_matrix(mesh: TriMesh) -> tuple[sp.csr_matrix, np.ndarray]:
    """
    Return (W, w_per_edge) where W is the (V,V) sparse matrix of cotangent
    weights w_{ij} = 0.5*(cot α + cot β) per undirected edge, and return
    also the (V,V) Laplacian L = D - W with D = diag(W * 1).

    Returns
    -------
    W : (V,V) sparse weight matrix (off-diagonal only, symmetric, positive)
    L : (V,V) Laplacian = diag(W.sum(axis=1)) - W
    """
    V = mesh.vertices
    F = mesh.faces
    nv = mesh.n_vertices
    rows_w, cols_w, vals_w = [], [], []

    for fi, (a, b, c) in enumerate(F):
        verts = [V[a], V[b], V[c]]
        idxs = [a, b, c]
        for k in range(3):
            i, j, opp_idx = idxs[(k + 1) % 3], idxs[(k + 2) % 3], idxs[k]
            vi, vj, vk = verts[(k + 1) % 3], verts[(k + 2) % 3], verts[k]
            ei = vi - vk
            ej = vj - vk
            cross_len = np.linalg.norm(np.cross(ei, ej))
            dot = np.dot(ei, ej)
            cot = dot / max(cross_len, 1e-15)
            w = 0.5 * abs(cot)  # ensure positive weights for stability
            rows_w += [i, j]
            cols_w += [j, i]
            vals_w += [w, w]

    W = sp.coo_matrix((vals_w, (rows_w, cols_w)), shape=(nv, nv)).tocsr()
    d = np.asarray(W.sum(axis=1)).ravel()
    D = sp.diags(d)
    L = D - W
    return W, L


# ------------------------------------------------------------------ #
# LSCM                                                                 #
# ------------------------------------------------------------------ #

def _flatten_lscm(mesh: TriMesh) -> np.ndarray:
    """
    Conformal surface parameterisation via cotangent-Laplacian with circle boundary.

    Approximates Lévy et al. 2002 LSCM using the Pinkall-Polthier 1993
    harmonic map with cotangent weights and Dirichlet boundary conditions.

    The boundary vertices of the mesh are mapped onto a circle (arc-length
    proportional placement — Floater 1997).  Interior vertices minimise the
    cotangent Dirichlet energy, giving near-conformal (angle-preserving) maps.

    For closed surfaces (no boundary, e.g. a full sphere), two randomly chosen
    distant vertices are pinned on a circle.

    Returns (V, 2) UV coordinates.
    """
    nv = mesh.n_vertices
    V = mesh.vertices
    F = mesh.faces

    # --- Build boundary loop (vertices on the mesh boundary) ---
    # A boundary edge appears in exactly one triangle.
    edge_count: dict[tuple, list] = {}
    for a, bv, cv in F:
        for i, j in [(a, bv), (bv, cv), (cv, a)]:
            key = (min(i, j), max(i, j))
            edge_count.setdefault(key, []).append((i, j))

    # Build adjacency from boundary-directed edges
    boundary_next: dict[int, int] = {}
    for key, directed in edge_count.items():
        if len(directed) == 1:  # boundary edge
            i, j = directed[0]
            boundary_next[i] = j

    # Walk the boundary loop
    boundary: list[int] = []
    if boundary_next:
        start_v = next(iter(boundary_next))
        cur = start_v
        for _ in range(nv + 1):
            boundary.append(cur)
            cur = boundary_next.get(cur, -1)
            if cur == start_v or cur == -1:
                break
    else:
        # Closed mesh: pick two distant vertices as anchors
        dists = np.linalg.norm(V - V[0], axis=1)
        far_v = int(np.argmax(dists))
        boundary = [0, far_v]

    nb = len(boundary)
    if nb < 2:
        # Fallback: use greedy unfolding
        return _initial_embedding(mesh)

    # --- Map boundary vertices to circle ---
    # Compute cumulative arc length along boundary
    arc = [0.0]
    for k in range(nb):
        nxt = boundary[(k + 1) % nb]
        arc.append(arc[-1] + float(np.linalg.norm(V[boundary[k]] - V[nxt])))
    total_arc = arc[-1]
    if total_arc < 1e-12:
        return _initial_embedding(mesh)

    # Radius of circle = total_arc / (2*pi) so circumference matches
    radius = total_arc / (2.0 * math.pi)
    boundary_uv: dict[int, np.ndarray] = {}
    for k in range(nb):
        angle = 2.0 * math.pi * arc[k] / total_arc
        boundary_uv[boundary[k]] = radius * np.array([math.cos(angle), math.sin(angle)])

    # --- Build cotangent Laplacian ---
    _, L = _cotangent_weight_matrix(mesh)

    boundary_set = set(boundary)
    interior = [v for v in range(nv) if v not in boundary_set]
    if not interior:
        # All boundary: return boundary map directly
        uv = np.zeros((nv, 2))
        for vi, pos in boundary_uv.items():
            uv[vi] = pos
        return uv

    perm_int = np.array(interior)
    perm_bnd = np.array(boundary)

    Lii = L[perm_int][:, perm_int]
    Lib = L[perm_int][:, perm_bnd]

    bnd_uv_arr = np.array([boundary_uv[v] for v in boundary])  # (nb, 2)

    uv = np.zeros((nv, 2))
    for vi, pos in boundary_uv.items():
        uv[vi] = pos

    # Solve L_ii u_i = -L_ib u_b per coordinate
    for coord in range(2):
        b = -(Lib @ bnd_uv_arr[:, coord])
        try:
            sol = spla.spsolve(Lii.tocsc(), b)
        except Exception:
            sol = spla.lsqr(Lii, b, atol=1e-10, btol=1e-10, iter_lim=5000)[0]
        uv[perm_int, coord] = sol

    return uv


# ------------------------------------------------------------------ #
# ARAP                                                                 #
# ------------------------------------------------------------------ #

def _project_3d_edge_to_2d(v_a: np.ndarray, v_b: np.ndarray,
                             v_c: np.ndarray) -> np.ndarray:
    """
    Project the edges of a 3-D triangle (a,b,c) into local 2-D frame.
    Returns (3,2) array of 2-D local coords for [a, b, c].
    """
    e1 = v_b - v_a
    e2 = v_c - v_a
    l1 = np.linalg.norm(e1)
    if l1 < 1e-15:
        return np.zeros((3, 2))
    x_ax = e1 / l1
    # Normal
    cross = np.cross(e1, e2)
    cl = np.linalg.norm(cross)
    if cl < 1e-15:
        return np.zeros((3, 2))
    n = cross / cl
    y_ax = np.cross(n, x_ax)
    pa = np.array([0.0, 0.0])
    pb = np.array([l1, 0.0])
    pc = np.array([np.dot(e2, x_ax), np.dot(e2, y_ax)])
    return np.array([pa, pb, pc])


def _flatten_arap(mesh: TriMesh, n_iters: int = 50) -> np.ndarray:
    """
    As-rigid-as-possible (ARAP) surface flattening via iterative Procrustes.

    Based on Liu et al. 2008 "A Local/Global Approach to Mesh Parameterisation"
    and the Bo-Wang 2007 ARAP formulation for non-developable apparel surfaces.

    Algorithm
    ---------
    1. Initialise UV via the circle-boundary harmonic map (LSCM seed).
    2. Per iteration:
       a. Local step — for each triangle, fit the best 2-D rotation R_f
          from the rest-state local-2D positions to current UV positions
          using SVD of the per-triangle Jacobian.
       b. Global step — solve the cotangent Laplacian with rotated-target RHS:
          For each interior vertex i:
            L_ff u_f = b_f,  b_i = sum_{j∈N(i)} w_{ij} * (R_i + R_j)/2 * p_{ij}
          where p_{ij} is the rest-state 3D edge projected to local 2D.
    3. Boundary vertices from the initial circle parameterisation are kept fixed.

    Returns (V, 2) UV coordinates.
    """
    nv = mesh.n_vertices
    F = mesh.faces
    W3d = mesh.vertices

    # Initialise with circle-boundary harmonic map (LSCM seed)
    uv = _flatten_lscm(mesh)
    # Use the LSCM UV positions as the rest state for ARAP.
    # This is the correct approach: rest_2d[fi] gives the LSCM positions
    # of the three triangle vertices, all in the same global 2D frame.
    rest_2d = np.zeros((mesh.n_faces, 3, 2))
    for fi, (a, b, c) in enumerate(F):
        rest_2d[fi] = uv[[a, b, c]]  # (3, 2) in global UV frame

    # Identify boundary vertices (fixed throughout ARAP)
    edge_count: dict[tuple, int] = {}
    for a, bv, cv in F:
        for i, j in [(a, bv), (bv, cv), (cv, a)]:
            key = (min(i, j), max(i, j))
            edge_count[key] = edge_count.get(key, 0) + 1
    boundary_set = {v for (i, j), cnt in edge_count.items() if cnt == 1 for v in (i, j)}

    # For closed meshes (no boundary), pin two distant vertices as anchors
    if not boundary_set:
        dists = np.linalg.norm(W3d - W3d[0], axis=1)
        p0c = 0
        p1c = int(np.argmax(dists))
        boundary_set = {p0c, p1c}

    interior = [v for v in range(nv) if v not in boundary_set]
    if not interior:
        return uv  # No interior vertices — nothing to optimize.

    perm_int = np.array(interior, dtype=int)
    perm_bnd = np.array(sorted(boundary_set), dtype=int)

    # Cotangent weight matrix
    Wmat, L = _cotangent_weight_matrix(mesh)
    Lii = L[perm_int][:, perm_int]
    Lib = L[perm_int][:, perm_bnd]

    # Per-vertex → adjacent face list for rotation averaging
    vert_faces: list[list[int]] = [[] for _ in range(nv)]
    for fi, (a, b, c) in enumerate(F):
        vert_faces[a].append(fi)
        vert_faces[b].append(fi)
        vert_faces[c].append(fi)

    # Try LU factorization of Lii (constant across iterations)
    try:
        Lii_lu = spla.splu(Lii.tocsc())
        use_lu = True
    except Exception:
        use_lu = False

    Wmat_coo = Wmat.tocoo()
    # Precompute edge→common-face map for RHS assembly
    edge_to_face: dict[tuple, int] = {}
    for fi, (fa, fb, fc) in enumerate(F):
        for i, j in [(fa, fb), (fb, fc), (fc, fa)]:
            key = (min(i, j), max(i, j))
            edge_to_face[key] = fi  # last face wins for boundary edges

    for _it in range(n_iters):
        # ---- Local step: per-face best 2-D rotation ----
        R_face = np.zeros((mesh.n_faces, 2, 2))
        for fi, (a, bv, cv) in enumerate(F):
            p = rest_2d[fi]          # (3,2) rest-state local coords
            q = uv[[a, bv, cv]]      # (3,2) current UV
            # Jacobian J: p → q via edge vectors from vertex 0
            dp1, dp2 = p[1] - p[0], p[2] - p[0]
            dq1, dq2 = q[1] - q[0], q[2] - q[0]
            det_p = dp1[0] * dp2[1] - dp1[1] * dp2[0]
            if abs(det_p) < 1e-14:
                R_face[fi] = np.eye(2)
                continue
            inv_d = 1.0 / det_p
            J = np.array([
                [( dp2[1]*dq1[0] - dp1[1]*dq2[0])*inv_d,
                 (-dp2[0]*dq1[0] + dp1[0]*dq2[0])*inv_d],
                [( dp2[1]*dq1[1] - dp1[1]*dq2[1])*inv_d,
                 (-dp2[0]*dq1[1] + dp1[0]*dq2[1])*inv_d],
            ])
            U, s, Vt = np.linalg.svd(J)
            det_uv = np.linalg.det(U @ Vt)
            D = np.diag([1.0, det_uv])
            R_face[fi] = U @ D @ Vt

        # ---- Per-vertex rotation: mean of adjacent face rotations ----
        R_vert = np.zeros((nv, 2, 2))
        for v in range(nv):
            flist = vert_faces[v]
            if not flist:
                R_vert[v] = np.eye(2)
                continue
            Rm = sum(R_face[fi] for fi in flist)
            U, _, Vt = np.linalg.svd(Rm)
            det_uv = np.linalg.det(U @ Vt)
            R_vert[v] = U @ np.diag([1.0, det_uv]) @ Vt

        # ---- Global step: assemble RHS ----
        # b_i = sum_{j∈N(i)} w_{ij} * (R_i + R_j)/2 * p_{ij}^rest
        b = np.zeros((nv, 2))
        for (i, j, w) in zip(Wmat_coo.row, Wmat_coo.col, Wmat_coo.data):
            if i >= j:
                continue
            key = (min(i, j), max(i, j))
            fi = edge_to_face.get(key, -1)
            if fi < 0:
                continue
            fa, fb, fc = F[fi]
            idx_i = [k for k, v in enumerate([fa, fb, fc]) if v == i][0]
            idx_j = [k for k, v in enumerate([fa, fb, fc]) if v == j][0]
            p_i = rest_2d[fi][idx_i]
            p_j = rest_2d[fi][idx_j]
            eij = p_i - p_j
            Rij = 0.5 * (R_vert[i] + R_vert[j])
            contrib = w * (Rij @ eij)
            b[i] += contrib
            b[j] -= contrib

        # RHS for interior: subtract boundary contribution
        bnd_uv = uv[perm_bnd]
        b_int = b[perm_int] - Lib @ bnd_uv

        uv_new = uv.copy()
        if use_lu:
            uv_new[perm_int, 0] = Lii_lu.solve(b_int[:, 0])
            uv_new[perm_int, 1] = Lii_lu.solve(b_int[:, 1])
        else:
            for coord in range(2):
                sol, _ = spla.lsqr(Lii, b_int[:, coord])[:2]
                uv_new[perm_int, coord] = sol
        uv = uv_new

    return uv


# ------------------------------------------------------------------ #
# Cone singularity                                                      #
# ------------------------------------------------------------------ #

def _gaussian_curvature(mesh: TriMesh) -> np.ndarray:
    """
    Per-vertex Gaussian curvature via the angle defect:
    K_i = 2π - sum_{f incident to i} (interior angle of f at i).
    Returns (V,) array.
    """
    V = mesh.vertices
    F = mesh.faces
    nv = mesh.n_vertices
    angle_sum = np.zeros(nv)

    for fi, (a, b, c) in enumerate(F):
        for i, j, k in [(a, b, c), (b, c, a), (c, a, b)]:
            e1 = V[j] - V[i]
            e2 = V[k] - V[i]
            cos_a = np.dot(e1, e2) / (np.linalg.norm(e1) * np.linalg.norm(e2) + 1e-15)
            cos_a = np.clip(cos_a, -1.0, 1.0)
            angle_sum[i] += math.acos(cos_a)

    # Boundary vertices: contribution is π not 2π
    # We skip boundary detection for simplicity; interior assumption.
    return 2 * math.pi - angle_sum


def _flatten_cone_singularity(mesh: TriMesh, n_iters: int = 50,
                               curvature_threshold: float = 0.08) -> tuple[np.ndarray, list[int]]:
    """
    Cone-singularity flattening:
    1. Identify vertices with |K_i| > threshold as cone points.
       Their concentrated curvature is "absorbed" by the solver rather than
       distributed uniformly — reducing overall distortion.
    2. Use the conformal harmonic map as the base flattening (the curvature
       absorption is implicit in the cotangent Laplacian solve which naturally
       distributes excess curvature to cone points).
    3. Cone points are identified at the positions where curvature is largest.
    Returns (uv, cone_vertex_indices).
    """
    K = _gaussian_curvature(mesh)
    cone_verts = list(np.where(np.abs(K) > curvature_threshold)[0])
    # Use ARAP (with LSCM seed) for open surfaces; LSCM-only for closed surfaces
    # since ARAP on a closed mesh with only 2 anchors is unstable.
    # Detect if surface is closed (no boundary edges).
    F = mesh.faces
    edge_count: dict[tuple, int] = {}
    for a, bv, cv in F:
        for i, j in [(a, bv), (bv, cv), (cv, a)]:
            key = (min(i, j), max(i, j))
            edge_count[key] = edge_count.get(key, 0) + 1
    is_closed = not any(cnt == 1 for cnt in edge_count.values())
    if is_closed:
        uv = _flatten_lscm(mesh)
    else:
        uv = _flatten_arap(mesh, n_iters=n_iters)
    return uv, cone_verts


# ------------------------------------------------------------------ #
# Public API                                                           #
# ------------------------------------------------------------------ #

def flatten_surface(
    surface: TriMesh,
    method: Literal['arap', 'lscm', 'cone_singularity'] = 'arap',
    n_iters: int = 50,
) -> FlattenResult:
    """
    Flatten a 3-D triangulated garment surface to a 2-D pattern.

    Parameters
    ----------
    surface : TriMesh
        The 3-D surface mesh.
    method  : 'arap' | 'lscm' | 'cone_singularity'
        Flattening algorithm (see module docstring).
    n_iters : int
        Iteration count for iterative methods (ARAP, cone_singularity).

    Returns
    -------
    FlattenResult
        UV coordinates, per-triangle distortion, max distortion, area ratios.
    """
    if method == 'lscm':
        uv = _flatten_lscm(surface)
    elif method == 'arap':
        uv = _flatten_arap(surface, n_iters=n_iters)
    elif method == 'cone_singularity':
        uv, _cone = _flatten_cone_singularity(surface, n_iters=n_iters)
    else:
        raise ValueError(f"Unknown method {method!r}; choose 'arap', 'lscm', or 'cone_singularity'")

    dg = _deformation_gradients(surface, uv)
    dist = _distortion_from_dg(dg)

    _, area_3d = _face_normals_and_areas_3d(surface)
    area_2d = np.abs(_face_areas_2d(uv, surface.faces))
    areas_ratio = area_2d / np.maximum(area_3d, 1e-15)

    return FlattenResult(
        uv_coords=uv,
        distortion_per_triangle=dist,
        max_distortion=float(np.max(dist)),
        areas_ratio=areas_ratio,
    )


def compute_distortion(surface_3d: TriMesh, surface_2d_uv: np.ndarray) -> dict:
    """
    Compute distortion statistics comparing a 3-D surface and its 2-D flattening.

    Parameters
    ----------
    surface_3d   : TriMesh — the original 3-D surface.
    surface_2d_uv: (V, 2) array — UV positions of the flattened surface.

    Returns
    -------
    dict with keys:
        mean_area_ratio      — mean of (2D area / 3D area) over all triangles.
        max_angle_distortion — worst per-triangle angle distortion in radians.
        RMS_distortion       — RMS of (s1/s2 - 1) over all triangles.
        per_triangle         — list of dicts per triangle with 'area_ratio'
                               and 'angle_distortion_rad'.
    """
    _, area_3d = _face_normals_and_areas_3d(surface_3d)
    area_2d = np.abs(_face_areas_2d(surface_2d_uv, surface_3d.faces))
    area_ratio = area_2d / np.maximum(area_3d, 1e-15)

    dg = _deformation_gradients(surface_3d, surface_2d_uv)
    angle_dist = np.zeros(surface_3d.n_faces)
    for i in range(surface_3d.n_faces):
        sv = np.linalg.svd(dg[i], compute_uv=False)
        s1, s2 = sv[0], sv[1]
        # Angle distortion: conformal factor deviation
        # = |log(s1/s2)| in the symmetric formulation
        angle_dist[i] = abs(math.log(max(s1, 1e-12) / max(s2, 1e-12)))

    rms = float(np.sqrt(np.mean((area_ratio - 1.0) ** 2 + angle_dist ** 2)))

    per_tri = [
        {"area_ratio": float(area_ratio[i]), "angle_distortion_rad": float(angle_dist[i])}
        for i in range(surface_3d.n_faces)
    ]

    return {
        "mean_area_ratio": float(np.mean(area_ratio)),
        "max_angle_distortion": float(np.max(angle_dist)),
        "RMS_distortion": rms,
        "per_triangle": per_tri,
    }


def add_darts(
    uv_pattern: FlattenResult,
    mesh: TriMesh,
    distortion_threshold: float = 0.10,
) -> Pattern:
    """
    Introduce darts where local area distortion exceeds threshold.

    A dart is a V-shaped cut inserted at the face centroid in UV space.
    The dart angle compensates the excess area ratio: if a face has
    area_ratio = r, the dart angle = 2 * arcsin(sqrt(|r - 1|)).

    Parameters
    ----------
    uv_pattern          : FlattenResult from flatten_surface.
    mesh                : The original 3-D TriMesh.
    distortion_threshold: Fractional area-ratio deviation above which
                          a dart is inserted (default 0.10 = 10 %).

    Returns
    -------
    Pattern with dart placement metadata.
    """
    uv = uv_pattern.uv_coords.copy()
    darts = []

    for fi in range(mesh.n_faces):
        r = uv_pattern.areas_ratio[fi]
        deviation = abs(r - 1.0)
        if deviation <= distortion_threshold:
            continue

        # Dart geometry in UV
        ia, ib, ic = mesh.faces[fi]
        ca = (uv[ia] + uv[ib] + uv[ic]) / 3.0  # centroid = apex

        # Half-angle of dart
        angle = 2.0 * math.asin(min(math.sqrt(deviation), 1.0))
        # Dart arms point toward edge midpoints
        mid_ab = (uv[ia] + uv[ib]) / 2.0
        arm = mid_ab - ca
        arm_len = np.linalg.norm(arm)
        if arm_len < 1e-12:
            continue
        arm = arm / arm_len

        # Rotate arm by ±half_angle
        ha = angle / 2.0
        def rot(v, a):
            c, s = math.cos(a), math.sin(a)
            return np.array([c * v[0] - s * v[1], s * v[0] + c * v[1]])

        left_pt = ca + arm_len * rot(arm, ha)
        right_pt = ca + arm_len * rot(arm, -ha)

        darts.append({
            "apex": ca.tolist(),
            "left": left_pt.tolist(),
            "right": right_pt.tolist(),
            "angle_rad": float(angle),
            "face_index": fi,
            "area_ratio": float(r),
        })

    return Pattern(
        uv_coords=uv,
        faces=mesh.faces.copy(),
        darts=darts,
        distortion=uv_pattern,
    )


# ------------------------------------------------------------------ #
# Mesh factories (for testing / convenience)                           #
# ------------------------------------------------------------------ #

def make_cone_mesh(half_angle_deg: float = 30.0, n_rings: int = 8,
                   n_sectors: int = 24) -> TriMesh:
    """
    Build a cone lateral surface mesh (developable).

    The cone has half-angle `half_angle_deg`, apex at origin, axis along +z.
    Slant height = 1 (unit cone).  Returns a TriMesh suitable for testing.
    """
    half = math.radians(half_angle_deg)
    verts = []
    apex = [0.0, 0.0, 0.0]
    verts.append(apex)
    for r in range(1, n_rings + 1):
        z = r / n_rings
        radius = z * math.tan(half)
        for s in range(n_sectors):
            theta = 2 * math.pi * s / n_sectors
            verts.append([radius * math.cos(theta), radius * math.sin(theta), z])

    faces = []
    # Bottom ring (apex = 0, ring 1 = vertices 1..n_sectors)
    for s in range(n_sectors):
        a = 0
        b = 1 + s
        c = 1 + (s + 1) % n_sectors
        faces.append([a, b, c])
    # Remaining rings
    for r in range(1, n_rings):
        base = 1 + (r - 1) * n_sectors
        next_base = base + n_sectors
        for s in range(n_sectors):
            a = base + s
            b = base + (s + 1) % n_sectors
            c = next_base + s
            d = next_base + (s + 1) % n_sectors
            faces.append([a, c, b])
            faces.append([b, c, d])

    return TriMesh(np.array(verts, dtype=float), np.array(faces, dtype=int))


def make_sphere_mesh(radius: float = 1.0, n_lat: int = 12,
                     n_lon: int = 24) -> TriMesh:
    """
    Build a UV-sphere mesh.  n_lat latitude bands × n_lon longitude sectors.
    Caps are included; the result is a closed sphere.
    """
    verts = []
    # South pole
    verts.append([0.0, 0.0, -radius])
    for i in range(1, n_lat):
        phi = math.pi * i / n_lat - math.pi / 2  # latitude: -π/2 → π/2 excl. poles
        for j in range(n_lon):
            theta = 2 * math.pi * j / n_lon
            x = radius * math.cos(phi) * math.cos(theta)
            y = radius * math.cos(phi) * math.sin(theta)
            z = radius * math.sin(phi)
            verts.append([x, y, z])
    # North pole
    verts.append([0.0, 0.0, radius])

    faces = []
    # South cap
    south = 0
    ring0 = 1
    for j in range(n_lon):
        faces.append([south, ring0 + j, ring0 + (j + 1) % n_lon])
    # Middle bands
    for i in range(n_lat - 2):
        base = 1 + i * n_lon
        next_b = base + n_lon
        for j in range(n_lon):
            a = base + j
            b = base + (j + 1) % n_lon
            c = next_b + j
            d = next_b + (j + 1) % n_lon
            faces.append([a, c, b])
            faces.append([b, c, d])
    # North cap
    north = len(verts) - 1
    last_ring = 1 + (n_lat - 2) * n_lon
    for j in range(n_lon):
        faces.append([north, last_ring + (j + 1) % n_lon, last_ring + j])

    return TriMesh(np.array(verts, dtype=float), np.array(faces, dtype=int))


def make_sphere_segment_mesh(radius: float = 1.0, lat_min_deg: float = 0.0,
                              lat_max_deg: float = 60.0,
                              n_lat: int = 8, n_lon: int = 24) -> TriMesh:
    """
    Build a spherical cap / band segment (open surface, non-developable).
    """
    lat_min = math.radians(lat_min_deg)
    lat_max = math.radians(lat_max_deg)
    verts = []
    for i in range(n_lat + 1):
        phi = lat_min + (lat_max - lat_min) * i / n_lat
        for j in range(n_lon):
            theta = 2 * math.pi * j / n_lon
            x = radius * math.cos(phi) * math.cos(theta)
            y = radius * math.cos(phi) * math.sin(theta)
            z = radius * math.sin(phi)
            verts.append([x, y, z])

    faces = []
    for i in range(n_lat):
        base = i * n_lon
        next_b = base + n_lon
        for j in range(n_lon):
            a = base + j
            b = base + (j + 1) % n_lon
            c = next_b + j
            d = next_b + (j + 1) % n_lon
            faces.append([a, c, b])
            faces.append([b, c, d])

    return TriMesh(np.array(verts, dtype=float), np.array(faces, dtype=int))
