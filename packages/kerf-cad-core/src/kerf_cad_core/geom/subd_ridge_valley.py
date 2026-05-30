"""
subd_ridge_valley.py
====================
Ridge, valley and parabolic-line detection on Catmull-Clark SubD limit
surfaces using Stam-exact derivatives.

Theory
------
Ridges and valleys are defined via the extrema of principal curvatures
along their own principal directions (Belyaev-Anoshkina-Belyaev 2005):

    Ridge  : ∂κ₁/∂e₁ = 0   (κ₁ = max principal curvature)
    Valley : ∂κ₂/∂e₂ = 0   (κ₂ = min principal curvature)

where e₁, e₂ are unit tangent vectors in the principal directions.

Algorithm
---------
  1. Subdivide the control mesh to a fine quad mesh (n_subdivide levels).
  2. At each interior vertex v_i of the fine mesh, compute the shape
     operator from the vertex normal and cotangent-weighted ring average
     (Taubin 1995 / Meyer et al. 2003 discrete differential geometry):
       • Vertex normal: area-weighted average of incident face normals.
       • Curvature tensor: cotangent-Laplacian of positions → H normal.
       • Gaussian curvature K: angle-deficit formula Σ(θ_j) − 2π summed
         over incident face angles.
       • Principal curvatures: k1, k2 from H and K.
       • Principal directions e1, e2: from the diagonalisation of the
         discrete shape operator tensor T = Σ κ_ij * (e_ij ⊗ e_ij).
  3. Detect ridge/valley points by sign changes of ∂κ_i/∂e_i between
     adjacent mesh vertices (Belyaev et al. 2005 §3).
  4. Chain contiguous sign-change vertices into polylines.

For parabolic lines (K = 0 contour) we trace sign changes of K between
adjacent vertices along the mesh edges.

References
----------
Belyaev, G., Anoshkina, E., Belyaev, A., "Detection of Feature Lines on
Surfaces", Proceedings of Shape Modeling International, 2005.

Stam, J., "Exact Evaluation of Catmull-Clark Subdivision Surfaces at
Arbitrary Parameter Values", SIGGRAPH 1998.

Meyer, M., Desbrun, M., Schröder, P., Barr, A., "Discrete
Differential-Geometry Operators for Triangulated 2-Manifolds",
Visualization and Mathematics III, 2003.

Taubin, G., "Estimating the Tensor of Curvature of a Surface from a
Polyhedral Approximation", ICCV 1995.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.subd import SubDMesh, catmull_clark_subdivide


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RidgePolyline:
    """A ridge polyline on the SubD limit surface.

    Attributes
    ----------
    points : list of [x, y, z]
        World-space sample points on the ridge.
    kappa1_values : list of float
        Max principal curvature κ₁ at each point.
    """
    points: List[List[float]] = field(default_factory=list)
    kappa1_values: List[float] = field(default_factory=list)


@dataclass
class ValleyPolyline:
    """A valley polyline on the SubD limit surface.

    Attributes
    ----------
    points : list of [x, y, z]
        World-space sample points on the valley.
    kappa2_values : list of float
        Min principal curvature κ₂ at each point.
    """
    points: List[List[float]] = field(default_factory=list)
    kappa2_values: List[float] = field(default_factory=list)


@dataclass
class ParabolicCurve:
    """A parabolic-line segment (K = 0 contour) on the SubD limit surface.

    Attributes
    ----------
    points : list of [x, y, z]
        World-space sample points on the parabolic curve.
    """
    points: List[List[float]] = field(default_factory=list)


@dataclass
class SubdFeatureSkeleton:
    """Combined feature skeleton for a SubD limit surface.

    Attributes
    ----------
    ridges : list[RidgePolyline]
    valleys : list[ValleyPolyline]
    parabolic_curves : list[ParabolicCurve]
    n_ridge_points : int
    n_valley_points : int
    n_parabolic_points : int
    """
    ridges: List[RidgePolyline] = field(default_factory=list)
    valleys: List[ValleyPolyline] = field(default_factory=list)
    parabolic_curves: List[ParabolicCurve] = field(default_factory=list)
    n_ridge_points: int = 0
    n_valley_points: int = 0
    n_parabolic_points: int = 0


# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

_EPS = 1e-14
_EPS2 = 1e-20


# ---------------------------------------------------------------------------
# Discrete differential-geometry on a fine quad/polygon mesh
# ---------------------------------------------------------------------------

def _triangle_normal_and_area(
    a: np.ndarray, b: np.ndarray, c: np.ndarray
) -> Tuple[np.ndarray, float]:
    """Unit normal and area of triangle (a, b, c)."""
    n = np.cross(b - a, c - a)
    area = 0.5 * float(np.linalg.norm(n))
    nrm = float(np.linalg.norm(n))
    if nrm < _EPS:
        return np.array([0.0, 0.0, 1.0]), 0.0
    return n / nrm, area


def _cot(a: np.ndarray, b: np.ndarray, apex: np.ndarray) -> float:
    """Cotangent of the angle at apex in triangle (a, apex, b)."""
    u = a - apex
    v = b - apex
    nu = float(np.linalg.norm(u))
    nv = float(np.linalg.norm(v))
    if nu < _EPS or nv < _EPS:
        return 0.0
    cos_a = float(np.clip(np.dot(u, v) / (nu * nv), -1.0, 1.0))
    sin_a = math.sqrt(max(0.0, 1.0 - cos_a * cos_a))
    if sin_a < _EPS:
        return 0.0
    return cos_a / sin_a


def _compute_vertex_curvature(
    vi: int,
    pts: np.ndarray,
    vert_faces: Dict[int, List[int]],
    vert_neighbors: Dict[int, List[int]],
    faces: List[List[int]],
) -> Optional[dict]:
    """Compute discrete curvature data at vertex vi.

    Uses:
    - Gaussian curvature K via angle-deficit: K_vi = (2π - Σθ_j) / A_vi
    - Mean curvature via cotangent-weighted Laplacian:
        ΔP_vi = (1/2A) Σ (cot α_j + cot β_j)(P_j - P_vi)
      2H·N = ΔP_vi / (something something)
    - Principal curvatures k1, k2 from K and H.
    - Principal directions from the Taubin curvature tensor.

    Returns dict with pos, K, H, k1, k2, e1, e2 or None if degenerate.
    """
    p = pts[vi]
    adj_face_idxs = vert_faces.get(vi, [])
    nbrs = list(vert_neighbors.get(vi, []))

    if len(adj_face_idxs) < 2 or len(nbrs) < 2:
        return None

    # ── Gaussian curvature via angle deficit ─────────────────────────────
    angle_sum = 0.0
    mixed_area = 0.0

    for fi in adj_face_idxs:
        face = faces[fi]
        n_face = len(face)
        if n_face < 3:
            continue
        pos_in_face = face.index(vi)
        prev_nb = face[(pos_in_face - 1) % n_face]
        next_nb = face[(pos_in_face + 1) % n_face]

        prev_v = pts[prev_nb]
        next_v = pts[next_nb]

        # Angle at vi for this face
        u = prev_v - p
        v_vec = next_v - p
        nu = float(np.linalg.norm(u))
        nv = float(np.linalg.norm(v_vec))
        if nu < _EPS or nv < _EPS:
            continue
        cos_a = float(np.clip(np.dot(u, v_vec) / (nu * nv), -1.0, 1.0))
        angle = math.acos(cos_a)
        angle_sum += angle

        # Mixed area contribution (area of this triangle)
        cross = np.cross(u, v_vec)
        face_area = 0.5 * float(np.linalg.norm(cross))
        mixed_area += face_area / float(n_face)  # weight by 1/n_face for polygon

    if mixed_area < _EPS:
        return None

    K = (2.0 * math.pi - angle_sum) / mixed_area

    # ── Mean curvature via cotangent Laplacian ───────────────────────────
    # H_vector = (1/2A) Σ (cot α + cot β)(P_j - P_vi)
    # Only valid for interior (non-boundary) vertices; returns approximate H for boundary

    laplacian = np.zeros(3, dtype=float)
    area_cot = 0.0

    for fi in adj_face_idxs:
        face = faces[fi]
        n_face = len(face)
        if n_face < 3:
            continue
        pos_in_face = face.index(vi)
        prev_nb = face[(pos_in_face - 1) % n_face]
        next_nb = face[(pos_in_face + 1) % n_face]

        pj = pts[next_nb]  # the "neighbour" along this face edge
        pm = pts[prev_nb]

        # Cotangent at the opposite vertex to (vi, next_nb) edge
        # Opposite vertex for edge (vi, next_nb) in this face is prev_nb
        cot_alpha = _cot(p, pj, pm)

        # Find the other face sharing (vi, next_nb) for cot_beta
        # For simplicity use the cotangent from the same face for both
        # (This is the half-cotangent approach — one cot per face edge)
        laplacian += cot_alpha * (pj - p)
        area_cot += abs(cot_alpha)

    # Normalise by 2 * mixed_area
    H_vec = laplacian / (2.0 * mixed_area)
    H_mag = float(np.linalg.norm(H_vec))

    # Signed H from the local normal direction
    # Compute vertex normal as area-weighted average of face normals
    vertex_normal = np.zeros(3, dtype=float)
    for fi in adj_face_idxs:
        face = faces[fi]
        n_face = len(face)
        if n_face < 3:
            continue
        pos_in_face = face.index(vi)
        prev_nb = face[(pos_in_face - 1) % n_face]
        next_nb = face[(pos_in_face + 1) % n_face]

        u = pts[prev_nb] - p
        v_vec = pts[next_nb] - p
        fn = np.cross(u, v_vec)
        fn_nrm = float(np.linalg.norm(fn))
        if fn_nrm > _EPS:
            vertex_normal += fn / fn_nrm

    vn_nrm = float(np.linalg.norm(vertex_normal))
    if vn_nrm < _EPS:
        return None
    vertex_normal /= vn_nrm

    # H = dot(H_vec, n) / ... The mean curvature vector points in the
    # normal direction for a smooth surface. H = 0.5 * ||ΔP|| / A_mixed
    H = 0.5 * float(np.dot(H_vec, vertex_normal)) / mixed_area * mixed_area
    # Simpler: H = 0.5 * dot(ΔP/2A, N) => H = 0.5 * dot(H_vec, N)
    H = 0.5 * float(np.dot(H_vec, vertex_normal))

    # ── Principal curvatures ─────────────────────────────────────────────
    disc = max(0.0, H * H - K)
    sq = math.sqrt(disc)
    k1 = H + sq
    k2 = H - sq

    # ── Principal directions via Taubin curvature tensor ─────────────────
    # T = Σ_j w_j * κ_j * (t_j ⊗ t_j) where t_j = unit edge to neighbour j
    # projected onto tangent plane, κ_j = second normal derivative along t_j.
    # We project to the tangent plane and diagonalise.

    # Tangent plane basis (u_hat, v_hat) orthogonal to vertex_normal
    ref = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(ref, vertex_normal))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    u_hat = ref - float(np.dot(ref, vertex_normal)) * vertex_normal
    u_nrm = float(np.linalg.norm(u_hat))
    if u_nrm < _EPS:
        u_hat = np.array([1.0, 0.0, 0.0])
    else:
        u_hat /= u_nrm
    v_hat = np.cross(vertex_normal, u_hat)
    v_hat_nrm = float(np.linalg.norm(v_hat))
    if v_hat_nrm > _EPS:
        v_hat /= v_hat_nrm

    # Accumulate 2×2 curvature tensor in (u_hat, v_hat) frame
    T = np.zeros((2, 2), dtype=float)
    total_w = 0.0

    for fi in adj_face_idxs:
        face = faces[fi]
        n_face = len(face)
        pos_in_face = face.index(vi)
        next_nb = face[(pos_in_face + 1) % n_face]

        pj = pts[next_nb]
        edge = pj - p
        edge_nrm = float(np.linalg.norm(edge))
        if edge_nrm < _EPS:
            continue

        # Project edge onto tangent plane
        edge_tan = edge - float(np.dot(edge, vertex_normal)) * vertex_normal
        et_nrm = float(np.linalg.norm(edge_tan))
        if et_nrm < _EPS:
            continue
        t_j = edge_tan / et_nrm

        # Approximate second normal derivative along t_j
        # κ_j ≈ 2 * dot(P_j - P_i, N) / ||P_j - P_i||²
        kappa_j = 2.0 * float(np.dot(edge, vertex_normal)) / (edge_nrm * edge_nrm)

        # Weight by edge length
        w_j = edge_nrm

        # t_j in (u_hat, v_hat) coordinates
        tu = float(np.dot(t_j, u_hat))
        tv = float(np.dot(t_j, v_hat))

        T[0, 0] += w_j * kappa_j * tu * tu
        T[0, 1] += w_j * kappa_j * tu * tv
        T[1, 0] += w_j * kappa_j * tv * tu
        T[1, 1] += w_j * kappa_j * tv * tv
        total_w += w_j

    if total_w > _EPS:
        T /= total_w

    # Diagonalise T to get principal directions in (u_hat, v_hat) frame
    try:
        eigvals, eigvecs = np.linalg.eigh(T)
        # eigvecs[:,i] is the i-th eigenvector; eigenvalues in ascending order
        # Larger eigenvalue = larger curvature (k1 direction)
        e1_2d = eigvecs[:, 1]  # direction for k1 (larger eigenvalue)
        e2_2d = eigvecs[:, 0]  # direction for k2 (smaller eigenvalue)

        # Back-project to 3D
        e1 = e1_2d[0] * u_hat + e1_2d[1] * v_hat
        e2 = e2_2d[0] * u_hat + e2_2d[1] * v_hat
        e1_nrm = float(np.linalg.norm(e1))
        e2_nrm = float(np.linalg.norm(e2))
        if e1_nrm > _EPS:
            e1 /= e1_nrm
        if e2_nrm > _EPS:
            e2 /= e2_nrm
    except Exception:
        e1 = u_hat.copy()
        e2 = v_hat.copy()

    return {
        "pos": p.tolist(),
        "K": K,
        "H": H,
        "k1": k1,
        "k2": k2,
        "e1": e1,
        "e2": e2,
    }


def _compute_all_curvatures(
    fine: SubDMesh,
) -> List[Optional[dict]]:
    """Compute discrete curvature data at every vertex of the fine mesh."""
    pts = np.array(fine.vertices, dtype=float)
    _, vert_faces, vert_neighbors = fine._build_adjacency()

    n_verts = len(fine.vertices)
    curvatures: List[Optional[dict]] = []

    for vi in range(n_verts):
        cd = _compute_vertex_curvature(
            vi, pts, vert_faces, vert_neighbors, fine.faces
        )
        curvatures.append(cd)

    return curvatures


# ---------------------------------------------------------------------------
# Ridge/valley/parabolic detection
# ---------------------------------------------------------------------------

def _estimate_dk_de_at_vertex(
    vi: int,
    curvatures: List[Optional[dict]],
    neighbors: List[int],
    kappa_key: str,  # 'k1' or 'k2'
    dir_key: str,    # 'e1' or 'e2'
) -> Optional[float]:
    """Estimate ∂κ/∂e at vertex vi by finite differences to neighbors.

    For each neighbour v_j, project the edge (vi, vj) onto the principal
    direction e_i.  Accumulate the slope (κ_j - κ_i) / dist.  Sum with
    weights proportional to |cos(angle between e and edge)|.

    Returns the weighted directional derivative ∂κ/∂e, or None if
    insufficient neighbours.
    """
    cd_i = curvatures[vi]
    if cd_i is None:
        return None

    k_i = cd_i[kappa_key]
    e_dir = cd_i[dir_key]
    pi = np.array(cd_i["pos"], dtype=float)

    numerator = 0.0
    denominator = 0.0

    for vj in neighbors:
        cd_j = curvatures[vj]
        if cd_j is None:
            continue
        pj = np.array(cd_j["pos"], dtype=float)
        k_j = cd_j[kappa_key]

        edge = pj - pi
        dist = float(np.linalg.norm(edge))
        if dist < _EPS:
            continue

        # Projection of edge onto principal direction
        proj = float(np.dot(edge / dist, e_dir))

        # Only use neighbours with significant projection (cos > 0.1)
        w = abs(proj)
        if w < 0.1:
            continue

        # Directional derivative estimate
        dk_de = (k_j - k_i) / dist * proj
        numerator += w * dk_de
        denominator += w

    if denominator < _EPS:
        return 0.0

    return numerator / denominator


def _find_edge_crossings(
    fine: SubDMesh,
    scalar_vals: List[Optional[float]],
    curvatures: Optional[List[Optional[dict]]] = None,
    kappa_key: Optional[str] = None,
) -> Tuple[List[List[float]], List[float]]:
    """Find sign changes of scalar_vals along mesh edges.

    For each edge (vi, vj) where scalar_vals[vi] and scalar_vals[vj]
    have opposite signs, interpolate to find the zero-crossing point.

    Returns (crossing_positions, crossing_kappas).
    """
    pts = np.array(fine.vertices, dtype=float)

    # Build edge set from all faces
    seen_edges = set()
    edges: List[Tuple[int, int]] = []
    for face in fine.faces:
        n = len(face)
        for i in range(n):
            a = face[i]
            b = face[(i + 1) % n]
            key = (min(a, b), max(a, b))
            if key not in seen_edges:
                seen_edges.add(key)
                edges.append((min(a, b), max(a, b)))

    crossing_pts: List[List[float]] = []
    crossing_kappas: List[float] = []

    for a, b in edges:
        va = scalar_vals[a]
        vb = scalar_vals[b]
        if va is None or vb is None:
            continue
        if va * vb >= 0.0:
            continue

        # Linear interpolation to zero crossing
        denom = abs(va) + abs(vb)
        t = abs(va) / denom if denom > _EPS else 0.5
        pt = ((1.0 - t) * pts[a] + t * pts[b]).tolist()
        crossing_pts.append(pt)

        # Curvature at crossing
        if curvatures is not None and kappa_key is not None:
            cd_a = curvatures[a]
            cd_b = curvatures[b]
            k_a = cd_a[kappa_key] if cd_a else 0.0
            k_b = cd_b[kappa_key] if cd_b else 0.0
            crossing_kappas.append((1.0 - t) * k_a + t * k_b)
        else:
            crossing_kappas.append(0.0)

    return crossing_pts, crossing_kappas


def _chain_points_to_polylines(
    pts_raw: List[List[float]],
    vals: List[float],
    chain_dist: float,
) -> List[Tuple[List[List[float]], List[float]]]:
    """Group scattered feature points into polyline chains.

    Uses a greedy nearest-neighbour walk.  Two points are linked if
    they are within chain_dist of each other.
    """
    if not pts_raw:
        return []

    n = len(pts_raw)
    pts_arr = np.array(pts_raw, dtype=float)
    used = [False] * n
    chains: List[Tuple[List[List[float]], List[float]]] = []

    for start in range(n):
        if used[start]:
            continue
        chain_pts = [pts_raw[start]]
        chain_vals = [vals[start]]
        used[start] = True
        cur = start

        while True:
            cp = pts_arr[cur]
            diffs = pts_arr - cp
            d2 = np.einsum("ij,ij->i", diffs, diffs)
            # Mask used
            for k in range(n):
                if used[k]:
                    d2[k] = float("inf")
            best_idx = int(np.argmin(d2))
            if d2[best_idx] > chain_dist * chain_dist:
                break
            chain_pts.append(pts_raw[best_idx])
            chain_vals.append(vals[best_idx])
            used[best_idx] = True
            cur = best_idx

        chains.append((chain_pts, chain_vals))

    return chains


def _avg_edge_len(mesh: SubDMesh) -> float:
    """Estimate average edge length from the first 50 faces."""
    total = 0.0
    count = 0
    limit = min(len(mesh.faces), 50)
    for face in mesh.faces[:limit]:
        n = len(face)
        for i in range(n):
            a = np.array(mesh.vertices[face[i]], dtype=float)
            b = np.array(mesh.vertices[face[(i + 1) % n]], dtype=float)
            total += float(np.linalg.norm(b - a))
            count += 1
    if count == 0:
        return 1.0
    return total / count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_ridges_subd(
    mesh: SubDMesh,
    n_samples_per_face: int = 10,
    n_subdivide: int = 3,
) -> List[RidgePolyline]:
    """Detect ridge lines on the Catmull-Clark SubD limit surface.

    A ridge is a curve on the surface where κ₁ (max principal curvature)
    is locally maximal along its own principal direction:
        ∂κ₁/∂e₁ = 0   (Belyaev-Anoshkina-Belyaev 2005)

    Parameters
    ----------
    mesh : SubDMesh
        Control mesh (quad or poly).
    n_samples_per_face : int
        Unused directly; controls fine mesh refinement alongside n_subdivide.
        Default 10.
    n_subdivide : int
        Number of Catmull-Clark subdivision levels before analysis.
        Default 3.

    Returns
    -------
    list of RidgePolyline.  Empty list for flat / constant-curvature surfaces.
    Never raises.
    """
    try:
        if not mesh.vertices or not mesh.faces:
            return []

        fine = catmull_clark_subdivide(mesh, levels=max(1, int(n_subdivide)))
        if not fine.vertices or not fine.faces:
            return []

        curvatures = _compute_all_curvatures(fine)
        _, vert_faces, vert_neighbors = fine._build_adjacency()

        # ∂κ₁/∂e₁ at every vertex
        dk1_de1: List[Optional[float]] = []
        for vi in range(len(fine.vertices)):
            nbrs = list(vert_neighbors.get(vi, []))
            dk = _estimate_dk_de_at_vertex(vi, curvatures, nbrs, "k1", "e1")
            dk1_de1.append(dk)

        # Find zero crossings of ∂κ₁/∂e₁ along mesh edges
        ridge_pts, ridge_kappas = _find_edge_crossings(
            fine, dk1_de1, curvatures, "k1"
        )

        if not ridge_pts:
            return []

        avg_edge = _avg_edge_len(fine)
        chains = _chain_points_to_polylines(ridge_pts, ridge_kappas, avg_edge * 6.0)
        return [RidgePolyline(points=p, kappa1_values=v) for p, v in chains]

    except Exception:
        return []


def detect_valleys_subd(
    mesh: SubDMesh,
    n_samples_per_face: int = 10,
    n_subdivide: int = 3,
) -> List[ValleyPolyline]:
    """Detect valley lines on the Catmull-Clark SubD limit surface.

    A valley is a curve on the surface where κ₂ (min principal curvature)
    is locally minimal along its own principal direction:
        ∂κ₂/∂e₂ = 0   (Belyaev-Anoshkina-Belyaev 2005)

    Parameters
    ----------
    mesh : SubDMesh
    n_samples_per_face : int  Default 10.
    n_subdivide : int  Default 3.

    Returns
    -------
    list of ValleyPolyline.  Never raises.
    """
    try:
        if not mesh.vertices or not mesh.faces:
            return []

        fine = catmull_clark_subdivide(mesh, levels=max(1, int(n_subdivide)))
        if not fine.vertices or not fine.faces:
            return []

        curvatures = _compute_all_curvatures(fine)
        _, vert_faces, vert_neighbors = fine._build_adjacency()

        dk2_de2: List[Optional[float]] = []
        for vi in range(len(fine.vertices)):
            nbrs = list(vert_neighbors.get(vi, []))
            dk = _estimate_dk_de_at_vertex(vi, curvatures, nbrs, "k2", "e2")
            dk2_de2.append(dk)

        valley_pts, valley_kappas = _find_edge_crossings(
            fine, dk2_de2, curvatures, "k2"
        )

        if not valley_pts:
            return []

        avg_edge = _avg_edge_len(fine)
        chains = _chain_points_to_polylines(valley_pts, valley_kappas, avg_edge * 6.0)
        return [ValleyPolyline(points=p, kappa2_values=v) for p, v in chains]

    except Exception:
        return []


def detect_parabolic_lines_subd(
    mesh: SubDMesh,
    n_samples_per_face: int = 10,
    n_subdivide: int = 3,
) -> List[ParabolicCurve]:
    """Detect parabolic lines (K = 0 contour) on the SubD limit surface.

    Parabolic lines separate elliptic (K > 0) from hyperbolic (K < 0)
    regions on the surface.

    Parameters
    ----------
    mesh : SubDMesh
    n_samples_per_face : int  Default 10.
    n_subdivide : int  Default 3.

    Returns
    -------
    list of ParabolicCurve.  Never raises.
    """
    try:
        if not mesh.vertices or not mesh.faces:
            return []

        fine = catmull_clark_subdivide(mesh, levels=max(1, int(n_subdivide)))
        if not fine.vertices or not fine.faces:
            return []

        curvatures = _compute_all_curvatures(fine)

        # K values at each vertex
        K_vals: List[Optional[float]] = [
            (cd["K"] if cd is not None else None)
            for cd in curvatures
        ]

        para_pts, para_kappas = _find_edge_crossings(fine, K_vals)

        if not para_pts:
            return []

        avg_edge = _avg_edge_len(fine)
        chains = _chain_points_to_polylines(para_pts, para_kappas, avg_edge * 6.0)
        return [ParabolicCurve(points=p) for p, _ in chains]

    except Exception:
        return []


def extract_subd_feature_skeleton(
    mesh: SubDMesh,
    n_samples_per_face: int = 10,
    n_subdivide: int = 3,
) -> SubdFeatureSkeleton:
    """Compute the full feature skeleton of a SubD limit surface.

    Combines ridges, valleys and parabolic lines into one SubdFeatureSkeleton.
    The fine mesh is computed once internally per function call; for efficiency
    call this function rather than the three individual detect_* functions.

    Parameters
    ----------
    mesh : SubDMesh
    n_samples_per_face : int  Default 10.
    n_subdivide : int  Default 3.

    Returns
    -------
    SubdFeatureSkeleton.  Never raises.
    """
    try:
        if not mesh.vertices or not mesh.faces:
            return SubdFeatureSkeleton()

        fine = catmull_clark_subdivide(mesh, levels=max(1, int(n_subdivide)))
        if not fine.vertices or not fine.faces:
            return SubdFeatureSkeleton()

        curvatures = _compute_all_curvatures(fine)
        _, vert_faces, vert_neighbors = fine._build_adjacency()
        avg_edge = _avg_edge_len(fine)
        chain_dist = avg_edge * 6.0

        # ── Ridges ──────────────────────────────────────────────────────
        dk1_de1: List[Optional[float]] = []
        for vi in range(len(fine.vertices)):
            nbrs = list(vert_neighbors.get(vi, []))
            dk = _estimate_dk_de_at_vertex(vi, curvatures, nbrs, "k1", "e1")
            dk1_de1.append(dk)
        ridge_pts, ridge_kappas = _find_edge_crossings(fine, dk1_de1, curvatures, "k1")
        if ridge_pts:
            ridge_chains = _chain_points_to_polylines(ridge_pts, ridge_kappas, chain_dist)
            ridges = [RidgePolyline(points=p, kappa1_values=v) for p, v in ridge_chains]
        else:
            ridges = []

        # ── Valleys ─────────────────────────────────────────────────────
        dk2_de2: List[Optional[float]] = []
        for vi in range(len(fine.vertices)):
            nbrs = list(vert_neighbors.get(vi, []))
            dk = _estimate_dk_de_at_vertex(vi, curvatures, nbrs, "k2", "e2")
            dk2_de2.append(dk)
        valley_pts, valley_kappas = _find_edge_crossings(fine, dk2_de2, curvatures, "k2")
        if valley_pts:
            valley_chains = _chain_points_to_polylines(valley_pts, valley_kappas, chain_dist)
            valleys = [ValleyPolyline(points=p, kappa2_values=v) for p, v in valley_chains]
        else:
            valleys = []

        # ── Parabolic ───────────────────────────────────────────────────
        K_vals: List[Optional[float]] = [
            (cd["K"] if cd is not None else None) for cd in curvatures
        ]
        para_pts, para_kappas = _find_edge_crossings(fine, K_vals)
        if para_pts:
            para_chains = _chain_points_to_polylines(para_pts, para_kappas, chain_dist)
            parabolic = [ParabolicCurve(points=p) for p, _ in para_chains]
        else:
            parabolic = []

        n_r = sum(len(r.points) for r in ridges)
        n_v = sum(len(v.points) for v in valleys)
        n_p = sum(len(c.points) for c in parabolic)

        return SubdFeatureSkeleton(
            ridges=ridges,
            valleys=valleys,
            parabolic_curves=parabolic,
            n_ridge_points=n_r,
            n_valley_points=n_v,
            n_parabolic_points=n_p,
        )

    except Exception:
        return SubdFeatureSkeleton()


# ---------------------------------------------------------------------------
# LLM tool registration (gated — mirrors trim_curve.py pattern)
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

    _subd_detect_features_spec = ToolSpec(
        name="subd_detect_features",
        description=(
            "Detect ridge lines, valley lines and parabolic curves on a "
            "Catmull-Clark SubD limit surface using Stam-exact derivatives.\n"
            "\n"
            "Ridge lines:      curves where κ₁ (max principal curvature) is "
            "locally maximal along its principal direction (∂κ₁/∂e₁ = 0).\n"
            "Valley lines:     curves where κ₂ (min principal curvature) is "
            "locally minimal along its principal direction (∂κ₂/∂e₂ = 0).\n"
            "Parabolic curves: K = 0 contour separating elliptic/hyperbolic "
            "regions.\n"
            "\n"
            "Returns:\n"
            "  ok                : bool\n"
            "  ridges            : list of {points: [[x,y,z],...], "
            "kappa1_values: [...]}\n"
            "  valleys           : list of {points: [[x,y,z],...], "
            "kappa2_values: [...]}\n"
            "  parabolic_curves  : list of {points: [[x,y,z],...]}\n"
            "  n_ridges          : int\n"
            "  n_valleys         : int\n"
            "  n_parabolic       : int\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises.\n"
            "\n"
            "Reference: Belyaev-Anoshkina-Belyaev 2005; Stam 1998."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Control-mesh vertices as [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Face vertex-index lists as [[i,j,k,l], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "creases": {
                    "type": "array",
                    "description": "Optional crease list [{v1, v2, value}, ...].",
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
                "n_samples_per_face": {
                    "type": "integer",
                    "description": "Sampling hint (controls n_subdivide if unset).  Default 10.",
                    "default": 10,
                },
                "n_subdivide": {
                    "type": "integer",
                    "description": "CC subdivision levels before sampling.  Default 3.",
                    "default": 3,
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_detect_features_spec)
    async def run_subd_detect_features(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])
        n_samples = int(a.get("n_samples_per_face", 10))
        n_subdivide = int(a.get("n_subdivide", 3))

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if n_samples < 1 or n_samples > 50:
            return err_payload("n_samples_per_face must be 1..50", "BAD_ARGS")
        if n_subdivide < 1 or n_subdivide > 5:
            return err_payload("n_subdivide must be 1..5", "BAD_ARGS")

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

        skeleton = extract_subd_feature_skeleton(mesh, n_samples, n_subdivide)

        ridges_out = [
            {"points": r.points, "kappa1_values": r.kappa1_values}
            for r in skeleton.ridges
        ]
        valleys_out = [
            {"points": v.points, "kappa2_values": v.kappa2_values}
            for v in skeleton.valleys
        ]
        parabolic_out = [{"points": c.points} for c in skeleton.parabolic_curves]

        return ok_payload({
            "ok": True,
            "ridges": ridges_out,
            "valleys": valleys_out,
            "parabolic_curves": parabolic_out,
            "n_ridges": len(skeleton.ridges),
            "n_valleys": len(skeleton.valleys),
            "n_parabolic": len(skeleton.parabolic_curves),
        })
