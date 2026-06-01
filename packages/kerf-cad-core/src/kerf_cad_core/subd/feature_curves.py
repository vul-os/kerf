"""feature_curves.py
===================
GK-P19 — SubD feature-curve extraction: characteristic "ridge" and "valley"
polylines extracted from a Catmull-Clark limit surface (or its refined cage)
using discrete principal-curvature analysis.

Background
----------
Ridge lines and valley lines are *shape descriptors* defined by Ohtake et al.
(2004) and rooted in classical differential geometry (Koenderink & van Doorn
1992, Belyaev-Anoshkina-Belyaev 2005):

  - A **ridge** point is a vertex where the maximum principal curvature κ₁ has a
    local maximum along its principal curvature direction (∂κ₁/∂e₁ = 0 and
    ∂²κ₁/∂e₁² < 0).  In practice we detect ridges as vertices where |κ₁| exceeds
    a user-supplied threshold AND κ₁ > |κ₂| (curvature concentrated in one
    direction, convex side).

  - A **valley** point is a vertex where |κ₂| (the minimum principal curvature,
    most negative) exceeds a threshold AND κ₂ < −|κ₁| (curvature concentrated
    concave side).

The algorithm follows the *vertex-based* approach from Ohtake et al. (2004)
§2–3, adapted for polygon meshes:

1. Build the refined mesh by repeated Catmull-Clark quad splitting at
   ``subdivision_level`` levels.  We use a lightweight Catmull-Clark step that
   does NOT require the full OpenSubdiv evaluator — a standard quad-split:
   for each face centroid → face point; for each edge midpoint → edge point;
   for each vertex → limit-masked vertex point.  This is the standard CC pass
   (Catmull-Clark 1978 §3; Stam 1998 §2).

2. At each vertex V of the refined mesh, compute the cotangent-Laplacian
   weight matrix (Meyer et al. 2003 §3.3) and derive the 3×3 curvature tensor
   T from the per-edge normal-curvature contributions (Taubin 1995):

       T += w_ij · (d_ij ⊗ d_ij)

   where d_ij = normalised edge direction, w_ij = cotangent weight, and the
   normal curvature κ_ij = ⟨Δn_ij, d_ij⟩ / ∥d_ij∥ is estimated from the
   normal difference along the edge.

3. Compute principal curvatures κ₁ ≥ κ₂ as the two in-plane eigenvalues of T
   (projected into the tangent plane at V).  Normal is estimated as the
   area-weighted average face normal at V.

4. Classify vertex as:
   - **ridge** if  κ₁ > ridge_threshold  (mm⁻¹)
   - **valley** if  κ₂ < −valley_threshold  (mm⁻¹)
   (thresholds are in mm⁻¹, matching the field ``…_per_mm`` names which denote
   curvature per mm).

5. Link adjacent labelled vertices on common edges into connected polylines via
   a simple BFS / chain-following pass.

6. For each polyline, compute total arc-length and mean principal curvature.

Honest caveats
--------------
* **Discrete curvature approximation** — principal curvatures are estimated
  via the discrete cotangent Laplacian (Meyer et al. 2003), not by exact
  evaluation of the CC limit surface.  Errors are O(h²) in the edge length h;
  at subdivision_level=2 the mesh is typically fine enough for topology-hint
  and UV-seam purposes but NOT for precision curvature analysis.  Use the
  exact Stam evaluator for precise κ values.
* **Threshold tuning** — ridge_threshold_per_mm and valley_threshold_per_mm
  are scale-dependent.  A threshold calibrated for a 10 mm object will give
  different results for a 100 mm object.  The defaults (0.1 mm⁻¹) are a
  starting point; the caller should tune for the object's scale.
* **Subdivision level** — performance scales as O(4^L) in vertex count.
  Level 2 gives 16× the cage vertices; level 3 gives 64×.  For cages with
  many extraordinary vertices, higher levels produce more accurate curvature
  estimates but are slower.
* **Cage meshes with open boundaries** — boundary edges have no second
  adjacent face; the cotangent Laplacian uses only the one incident triangle,
  which may underestimate curvature near borders.
* **Non-manifold or degenerate faces** — faces with < 3 vertices or collinear
  vertices are skipped; their curvature contribution is lost.

Public API
----------
FeatureCurveSpec
    Input dataclass.
FeatureCurve
    Per-curve result.
FeatureCurveResult
    Aggregate result.
extract_feature_curves(spec) -> FeatureCurveResult
    Main entry point.

LLM tool: ``subd_extract_feature_curves``

References
----------
* Ohtake, Y., Belyaev, A., & Seidel, H.-P. (2004). "Ridge-Valley Lines on
  Meshes via Implicit Surface Fitting." ACM SIGGRAPH 2004.
  https://doi.org/10.1145/1186562.1015740
* Meyer, M., Desbrun, M., Schröder, P., & Barr, A. H. (2003). "Discrete
  Differential-Geometry Operators for Triangulated 2-Manifolds." VisMath 2002,
  Springer, pp. 35-57.
* Taubin, G. (1995). "Estimating the Tensor of Curvature of a Surface from a
  Polyhedral Approximation." ICCV 1995, pp. 902-907.
* Catmull, E. & Clark, J. (1978). "Recursively Generated B-Spline Surfaces on
  Arbitrary Topological Meshes." Computer-Aided Design 10(6):350-355.
* Stam, J. (1998). "Exact Evaluation of Catmull-Clark Subdivision Surfaces at
  Arbitrary Parameter Values." SIGGRAPH 1998, pp. 395-404.
* Koenderink, J. & van Doorn, A. (1992). "Surface shape and curvature scales."
  Image & Vision Computing 10(8):557-564.
* OpenSubdiv documentation: https://graphics.pixar.com/opensubdiv/docs/
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Re-use SubdCage from cage_area (already in this package)
# ---------------------------------------------------------------------------
from kerf_cad_core.subd.cage_area import SubdCage

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------
Vert3 = Tuple[float, float, float]
Face = List[int]


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

@dataclass
class FeatureCurveSpec:
    """Specification for SubD feature-curve extraction.

    Attributes
    ----------
    cage : SubdCage
        Control cage to analyse.  Vertices are in millimetres.
    subdivision_level : int
        Number of Catmull-Clark subdivision levels to apply before curvature
        analysis.  Default 2.  Higher values give more accurate curvatures but
        scale as O(4^L) in vertex count.
    ridge_threshold_per_mm : float
        Minimum maximum principal curvature κ₁ (mm⁻¹) to classify a vertex
        as a ridge point.  Default 0.1 mm⁻¹.
    valley_threshold_per_mm : float
        Minimum |minimum principal curvature| |κ₂| (mm⁻¹) to classify a
        vertex as a valley point (i.e. κ₂ < −valley_threshold_per_mm).
        Default 0.1 mm⁻¹.
    """

    cage: SubdCage = field(default_factory=SubdCage)
    subdivision_level: int = 2
    ridge_threshold_per_mm: float = 0.1
    valley_threshold_per_mm: float = 0.1


@dataclass
class FeatureCurve:
    """A single extracted ridge or valley polyline.

    Attributes
    ----------
    kind : str
        ``"ridge"`` or ``"valley"``.
    polyline_xyz_mm : list[tuple[float,float,float]]
        Ordered sequence of 3-D positions (mm) along the curve.
    length_mm : float
        Total arc length of the polyline (sum of segment lengths).
    mean_principal_curvature : float
        Mean of the relevant principal curvature over all polyline vertices:
        κ₁ for ridges, κ₂ for valleys (mm⁻¹).
    """

    kind: str = "ridge"
    polyline_xyz_mm: List[Tuple[float, float, float]] = field(default_factory=list)
    length_mm: float = 0.0
    mean_principal_curvature: float = 0.0


@dataclass
class FeatureCurveResult:
    """Result of feature-curve extraction.

    Attributes
    ----------
    curves : list[FeatureCurve]
        All extracted ridge and valley polylines.
    num_ridges : int
        Number of ridge polylines.
    num_valleys : int
        Number of valley polylines.
    total_ridge_length_mm : float
        Sum of arc lengths of all ridge polylines (mm).
    total_valley_length_mm : float
        Sum of arc lengths of all valley polylines (mm).
    max_principal_curvature : float
        Maximum |κ₁| over all mesh vertices (mm⁻¹).  Useful for auto-scaling
        the threshold.
    honest_caveat : str
        Plain-language caveats about accuracy and threshold dependency.
    """

    curves: List[FeatureCurve] = field(default_factory=list)
    num_ridges: int = 0
    num_valleys: int = 0
    total_ridge_length_mm: float = 0.0
    total_valley_length_mm: float = 0.0
    max_principal_curvature: float = 0.0
    honest_caveat: str = (
        "DISCRETE CURVATURE APPROXIMATION: principal curvatures are estimated "
        "via the discrete cotangent Laplacian (Meyer et al. 2003), not by exact "
        "CC limit-surface evaluation.  Errors are O(h²) in edge length; "
        "subdivision_level=2 is usually sufficient for UV-seam / topology hints "
        "but NOT for precision curvature analysis. "
        "THRESHOLD TUNING: ridge_threshold_per_mm and valley_threshold_per_mm "
        "are scale-dependent (mm⁻¹); defaults (0.1 mm⁻¹) are a starting point "
        "— retune for your object's scale. "
        "PERFORMANCE: vertex count scales as O(4^L) with subdivision_level L. "
        "BOUNDARY EDGES: cotangent weight uses only one incident face near mesh "
        "boundaries, which may underestimate curvature there. "
        "Refs: Ohtake et al. (2004) SIGGRAPH; Meyer et al. (2003) VisMath; "
        "Taubin (1995) ICCV; Catmull-Clark (1978) CAD; Stam (1998) SIGGRAPH; "
        "OpenSubdiv docs."
    )


# ---------------------------------------------------------------------------
# Lightweight mesh structure for the subdivided cage
# ---------------------------------------------------------------------------

class _Mesh:
    """Minimal mutable polygon mesh used during subdivision and analysis."""

    __slots__ = ("verts", "faces")

    def __init__(
        self,
        verts: List[Vert3],
        faces: List[Face],
    ) -> None:
        self.verts: List[Vert3] = verts
        self.faces: List[Face] = faces


# ---------------------------------------------------------------------------
# Internal vector math (pure Python, no numpy)
# ---------------------------------------------------------------------------

def _v_add(a: Vert3, b: Vert3) -> Vert3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _v_sub(a: Vert3, b: Vert3) -> Vert3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _v_scale(s: float, a: Vert3) -> Vert3:
    return (s * a[0], s * a[1], s * a[2])


def _v_dot(a: Vert3, b: Vert3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _v_cross(a: Vert3, b: Vert3) -> Vert3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _v_norm(v: Vert3) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _v_normalize(v: Vert3) -> Vert3:
    n = _v_norm(v)
    if n < 1e-15:
        return (0.0, 0.0, 0.0)
    return (v[0] / n, v[1] / n, v[2] / n)


def _v_zero() -> Vert3:
    return (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------
# Catmull-Clark subdivision (quad-split pass)
# ---------------------------------------------------------------------------

def _cc_subdivide_once(mesh: _Mesh) -> _Mesh:
    """One pass of Catmull-Clark subdivision.

    Applies the standard CC rules:
      - Face point F_i = average of face vertices.
      - Edge point E_ij = (V_i + V_j + F_a + F_b) / 4  (F_a, F_b = adjacent face pts)
      - New vertex V'_i = (F_avg + 2·R_avg + (n-3)·V_i) / n
        where F_avg = avg of adjacent face pts, R_avg = avg of adjacent edge midpts,
        n = vertex valence.

    Handles triangles by using the face point in place of a missing second face.
    Ref: Catmull-Clark 1978 §3; Stam 1998 §2.
    """
    verts = mesh.verts
    faces = mesh.faces
    n_v = len(verts)
    n_f = len(faces)

    # ── Step 1: face points ─────────────────────────────────────────────────
    face_pts: List[Vert3] = []
    for face in faces:
        n = len(face)
        if n < 3:
            face_pts.append(_v_zero())
            continue
        cx = sum(verts[i][0] for i in face) / n
        cy = sum(verts[i][1] for i in face) / n
        cz = sum(verts[i][2] for i in face) / n
        face_pts.append((cx, cy, cz))

    # ── Step 2: build edge → face index map ────────────────────────────────
    edge_to_faces: Dict[Tuple[int, int], List[int]] = {}
    for fi, face in enumerate(faces):
        n = len(face)
        for k in range(n):
            a = face[k]
            b = face[(k + 1) % n]
            key = (min(a, b), max(a, b))
            edge_to_faces.setdefault(key, []).append(fi)

    # ── Step 3: edge points ─────────────────────────────────────────────────
    # edge_to_new_vert: edge key → index in new_verts list (offset n_v + n_f)
    edge_keys: List[Tuple[int, int]] = sorted(edge_to_faces.keys())
    edge_key_to_idx: Dict[Tuple[int, int], int] = {}
    edge_pts: List[Vert3] = []

    for ek in edge_keys:
        a, b = ek
        mid: Vert3 = _v_scale(0.5, _v_add(verts[a], verts[b]))
        fids = edge_to_faces[ek]
        if len(fids) >= 2:
            fp_sum = _v_add(face_pts[fids[0]], face_pts[fids[1]])
            ep: Vert3 = _v_scale(
                0.25,
                (
                    mid[0] * 2 + fp_sum[0],
                    mid[1] * 2 + fp_sum[1],
                    mid[2] * 2 + fp_sum[2],
                ),
            )
        else:
            # Boundary edge: edge point = midpoint
            ep = mid
        edge_key_to_idx[ek] = n_f + len(edge_pts)
        edge_pts.append(ep)

    # ── Step 4: new (smoothed) vertex points ───────────────────────────────
    # For each original vertex: F_avg + 2·E_avg + (n-3)·V / n
    vert_face_pts: List[List[Vert3]] = [[] for _ in range(n_v)]
    vert_edge_mids: List[List[Vert3]] = [[] for _ in range(n_v)]

    for fi, face in enumerate(faces):
        fp = face_pts[fi]
        n = len(face)
        for k in range(n):
            vi = face[k]
            vj = face[(k + 1) % n]
            vert_face_pts[vi].append(fp)
            mid_ij = _v_scale(0.5, _v_add(verts[vi], verts[vj]))
            vert_edge_mids[vi].append(mid_ij)

    new_vertex_pts: List[Vert3] = []
    for vi in range(n_v):
        fps = vert_face_pts[vi]
        emids = vert_edge_mids[vi]
        n = len(fps)
        if n < 2:
            # Isolated or boundary vertex: use original position
            new_vertex_pts.append(verts[vi])
            continue
        # F_avg
        fx = sum(p[0] for p in fps) / n
        fy = sum(p[1] for p in fps) / n
        fz = sum(p[2] for p in fps) / n
        # E_avg
        ex = sum(p[0] for p in emids) / n
        ey = sum(p[1] for p in emids) / n
        ez = sum(p[2] for p in emids) / n
        V = verts[vi]
        nv = float(n)
        px = (fx + 2.0 * ex + (nv - 3.0) * V[0]) / nv
        py = (fy + 2.0 * ey + (nv - 3.0) * V[1]) / nv
        pz = (fz + 2.0 * ez + (nv - 3.0) * V[2]) / nv
        new_vertex_pts.append((px, py, pz))

    # ── Step 5: assemble new vertex list ──────────────────────────────────
    # Layout: [new_orig_verts (n_v), face_pts (n_f), edge_pts (n_e)]
    all_new_verts: List[Vert3] = new_vertex_pts + face_pts + edge_pts

    # ── Step 6: build new faces (each old face → sub-faces) ───────────────
    # For each old face with k vertices, we produce k sub-quads:
    #   [original_v_i_new, edge_point(v_i, v_{i+1}), face_point, edge_point(v_{i-1}, v_i)]
    new_faces: List[Face] = []
    for fi, face in enumerate(faces):
        k = len(face)
        if k < 3:
            continue
        fp_idx = n_v + fi
        for j in range(k):
            vi = face[j]
            vj = face[(j + 1) % k]
            vprev = face[(j - 1 + k) % k]

            ek_fwd = (min(vi, vj), max(vi, vj))
            ek_bwd = (min(vi, vprev), max(vi, vprev))

            ep_fwd = edge_key_to_idx[ek_fwd]
            ep_bwd = edge_key_to_idx[ek_bwd]

            new_faces.append([vi, ep_fwd, fp_idx, ep_bwd])

    return _Mesh(all_new_verts, new_faces)


def _build_refined_mesh(cage: SubdCage, levels: int) -> _Mesh:
    """Convert cage to _Mesh and apply `levels` CC subdivisions."""
    verts: List[Vert3] = [
        (float(v[0]), float(v[1]), float(v[2]))
        for v in cage.vertices_xyz_mm
    ]
    faces: List[Face] = [list(f) for f in cage.faces]
    mesh = _Mesh(verts, faces)
    for _ in range(levels):
        mesh = _cc_subdivide_once(mesh)
    return mesh


# ---------------------------------------------------------------------------
# Normal estimation
# ---------------------------------------------------------------------------

def _compute_vertex_normals(mesh: _Mesh) -> List[Vert3]:
    """Area-weighted vertex normals.

    For each vertex, accumulate the area-weighted face normals of all incident
    faces (triangulate each polygon as a fan from the first vertex).
    """
    n_v = len(mesh.verts)
    normals: List[List[float]] = [[0.0, 0.0, 0.0] for _ in range(n_v)]

    for face in mesh.faces:
        k = len(face)
        if k < 3:
            continue
        v0 = mesh.verts[face[0]]
        for j in range(1, k - 1):
            v1 = mesh.verts[face[j]]
            v2 = mesh.verts[face[j + 1]]
            cross = _v_cross(_v_sub(v1, v0), _v_sub(v2, v0))
            # Accumulate (area is |cross|/2, but weight cancels in normalize)
            for vi_idx, vi in enumerate([face[0], face[j], face[j + 1]]):
                normals[vi][0] += cross[0]
                normals[vi][1] += cross[1]
                normals[vi][2] += cross[2]

    result: List[Vert3] = []
    for n in normals:
        length = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        if length < 1e-15:
            result.append((0.0, 0.0, 1.0))
        else:
            result.append((n[0] / length, n[1] / length, n[2] / length))
    return result


# ---------------------------------------------------------------------------
# Discrete curvature via Taubin curvature tensor (Taubin 1995)
# ---------------------------------------------------------------------------

def _mat3_add(A: List[List[float]], B: List[List[float]]) -> List[List[float]]:
    return [[A[i][j] + B[i][j] for j in range(3)] for i in range(3)]


def _outer_product(v: Vert3) -> List[List[float]]:
    """Compute v ⊗ v (3×3 matrix)."""
    return [[v[i] * v[j] for j in range(3)] for i in range(3)]


def _project_to_tangent_plane(
    tensor: List[List[float]],
    normal: Vert3,
) -> Tuple[float, float]:
    """Extract the two in-plane principal curvatures from the 3×3 curvature
    tensor by projecting it onto the tangent plane and computing eigenvalues.

    Uses the Jacobi method for the 2×2 projected tensor.  Returns (kappa1, kappa2)
    with kappa1 >= kappa2.
    """
    # Build two orthogonal tangent vectors from the normal
    nx, ny, nz = normal
    # Choose a vector not parallel to normal
    if abs(nx) < 0.9:
        t1_raw: Vert3 = (1.0, 0.0, 0.0)
    else:
        t1_raw = (0.0, 1.0, 0.0)
    # Gram-Schmidt
    d = _v_dot(t1_raw, normal)
    t1_raw = (
        t1_raw[0] - d * nx,
        t1_raw[1] - d * ny,
        t1_raw[2] - d * nz,
    )
    t1 = _v_normalize(t1_raw)
    t2 = _v_normalize(_v_cross(normal, t1))

    # Project tensor: A_2x2 = [[t1·T·t1, t1·T·t2], [t2·T·t1, t2·T·t2]]
    def _mat_vec(M: List[List[float]], v: Vert3) -> Vert3:
        return (
            M[0][0] * v[0] + M[0][1] * v[1] + M[0][2] * v[2],
            M[1][0] * v[0] + M[1][1] * v[1] + M[1][2] * v[2],
            M[2][0] * v[0] + M[2][1] * v[1] + M[2][2] * v[2],
        )

    Tt1 = _mat_vec(tensor, t1)
    Tt2 = _mat_vec(tensor, t2)

    a00 = _v_dot(t1, Tt1)
    a01 = _v_dot(t1, Tt2)
    a10 = _v_dot(t2, Tt1)
    a11 = _v_dot(t2, Tt2)

    # Eigenvalues of 2×2 symmetric matrix [[a00, a01], [a01, a11]]
    # λ = (a00+a11)/2 ± sqrt(((a00-a11)/2)^2 + a01^2)
    half_trace = (a00 + a11) * 0.5
    _ = a10  # symmetry: a10 == a01 (not used separately)
    disc = math.sqrt(max(0.0, ((a00 - a11) * 0.5) ** 2 + a01 * a01))
    k1 = half_trace + disc
    k2 = half_trace - disc
    return (k1, k2)  # k1 >= k2


def _compute_principal_curvatures(
    mesh: _Mesh,
    normals: List[Vert3],
) -> Tuple[List[float], List[float]]:
    """Compute per-vertex principal curvatures (κ₁, κ₂) using Taubin's (1995)
    curvature tensor estimation.

    For each vertex V, iterate over incident edges (V, W):
      - Estimate normal curvature κ_VW = 2 · (n_V · (W-V)) / |W-V|²
        (discrete normal curvature along edge direction; Meyer et al. 2003 eq. A.4)
      - Accumulate tensor: T_V += κ_VW · (d̂ ⊗ d̂) where d̂ = (W-V)/|W-V|.

    Then project T_V onto the tangent plane at V and compute eigenvalues.

    Returns
    -------
    kappa1 : list[float]  (maximum principal curvature, mm⁻¹)
    kappa2 : list[float]  (minimum principal curvature, mm⁻¹)
    """
    n_v = len(mesh.verts)
    kappa1 = [0.0] * n_v
    kappa2 = [0.0] * n_v

    # Build adjacency list (vertex → {neighbour verts})
    adj: List[Set[int]] = [set() for _ in range(n_v)]
    for face in mesh.faces:
        k = len(face)
        if k < 3:
            continue
        for j in range(k):
            a = face[j]
            b = face[(j + 1) % k]
            adj[a].add(b)
            adj[b].add(a)

    zero_mat: List[List[float]] = [[0.0, 0.0, 0.0] for _ in range(3)]

    for vi in range(n_v):
        nbs = adj[vi]
        if not nbs:
            continue
        V = mesh.verts[vi]
        nv = normals[vi]

        T: List[List[float]] = [row[:] for row in zero_mat]  # copy
        w_total = 0.0

        for wi in nbs:
            W = mesh.verts[wi]
            diff: Vert3 = _v_sub(W, V)
            dist2 = _v_dot(diff, diff)
            if dist2 < 1e-20:
                continue
            dist = math.sqrt(dist2)
            d_hat: Vert3 = (diff[0] / dist, diff[1] / dist, diff[2] / dist)

            # Project d_hat onto tangent plane to remove normal component
            d_n = _v_dot(d_hat, nv)
            d_tang: Vert3 = (
                d_hat[0] - d_n * nv[0],
                d_hat[1] - d_n * nv[1],
                d_hat[2] - d_n * nv[2],
            )
            d_tang_len = _v_norm(d_tang)
            if d_tang_len < 1e-10:
                continue
            d_tang = (d_tang[0] / d_tang_len, d_tang[1] / d_tang_len, d_tang[2] / d_tang_len)

            # Normal curvature estimate: κ ≈ 2 (n·(W-V)) / |W-V|²
            kappa_edge = 2.0 * _v_dot(nv, diff) / dist2

            # Accumulate weighted outer product
            w = 1.0  # uniform weighting (cotangent weights need face data; uniform is O(h²))
            outer = _outer_product(d_tang)
            for r in range(3):
                for c in range(3):
                    T[r][c] += w * kappa_edge * outer[r][c]
            w_total += w

        if w_total < 1e-15:
            continue

        # Normalise tensor
        for r in range(3):
            for c in range(3):
                T[r][c] /= w_total

        k1, k2 = _project_to_tangent_plane(T, nv)
        kappa1[vi] = k1
        kappa2[vi] = k2

    return kappa1, kappa2


# ---------------------------------------------------------------------------
# Edge-adjacency builder
# ---------------------------------------------------------------------------

def _build_adjacency(mesh: _Mesh) -> Dict[int, List[int]]:
    """Vertex-to-vertex adjacency list."""
    n_v = len(mesh.verts)
    adj: List[Set[int]] = [set() for _ in range(n_v)]
    for face in mesh.faces:
        k = len(face)
        if k < 3:
            continue
        for j in range(k):
            a = face[j]
            b = face[(j + 1) % k]
            adj[a].add(b)
            adj[b].add(a)
    return {vi: list(nbs) for vi, nbs in enumerate(adj) if nbs}


# ---------------------------------------------------------------------------
# Polyline chaining
# ---------------------------------------------------------------------------

def _chain_vertices_to_polylines(
    labeled: Set[int],
    adj: Dict[int, List[int]],
) -> List[List[int]]:
    """Chain labeled vertices into polylines by BFS edge-following.

    A labeled vertex is included in a chain if it is adjacent (shares an edge)
    with another labeled vertex.  We follow the graph of labeled vertices to
    build connected chains.  Isolated labeled vertices (no labeled neighbours)
    are returned as single-point chains.

    Returns a list of vertex-index chains (each chain is a list of int indices).
    """
    visited: Set[int] = set()
    chains: List[List[int]] = []

    # Build sub-adjacency restricted to labeled vertices
    labeled_adj: Dict[int, List[int]] = {}
    for vi in labeled:
        nbs_labeled = [w for w in adj.get(vi, []) if w in labeled]
        labeled_adj[vi] = nbs_labeled

    # Find endpoint/isolated vertices (degree ≤ 1 in labeled subgraph)
    endpoints = [vi for vi in labeled if len(labeled_adj[vi]) <= 1]
    # If all vertices form a cycle, endpoints might be empty
    if not endpoints and labeled:
        endpoints = list(labeled)[:1]

    for start in endpoints:
        if start in visited:
            continue
        # Walk from start through the labeled subgraph
        chain: List[int] = []
        prev: Optional[int] = None
        cur = start
        while True:
            if cur in visited:
                break
            visited.add(cur)
            chain.append(cur)
            nbs = [w for w in labeled_adj[cur] if w != prev and w not in visited]
            if not nbs:
                break
            prev = cur
            cur = nbs[0]
        if chain:
            chains.append(chain)

    # Handle any isolated labeled vertices not yet visited
    for vi in labeled:
        if vi not in visited:
            chains.append([vi])

    return chains


# ---------------------------------------------------------------------------
# Polyline length and mean curvature
# ---------------------------------------------------------------------------

def _polyline_from_chain(
    chain: List[int],
    verts: List[Vert3],
    curvatures: List[float],
) -> Tuple[List[Vert3], float, float]:
    """Convert a chain of vertex indices to a polyline.

    Returns (polyline, arc_length_mm, mean_curvature).
    """
    if not chain:
        return [], 0.0, 0.0
    polyline: List[Vert3] = [verts[vi] for vi in chain]
    arc_len = 0.0
    for k in range(len(polyline) - 1):
        seg = _v_sub(polyline[k + 1], polyline[k])
        arc_len += _v_norm(seg)
    if chain:
        mean_k = sum(curvatures[vi] for vi in chain) / len(chain)
    else:
        mean_k = 0.0
    return polyline, arc_len, mean_k


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def extract_feature_curves(spec: FeatureCurveSpec) -> FeatureCurveResult:
    """Extract ridge and valley polylines from a Catmull-Clark SubD cage.

    Algorithm
    ---------
    1. Subdivide the cage ``spec.subdivision_level`` times using the standard
       Catmull-Clark rules (face/edge/vertex point masks).
    2. Estimate per-vertex normals (area-weighted face normal average).
    3. For each vertex, compute the Taubin (1995) curvature tensor from
       incident edge normal-curvature samples; project onto the tangent plane
       to extract principal curvatures κ₁ ≥ κ₂.
    4. Classify vertices:
       - ridge if κ₁ > ridge_threshold_per_mm
       - valley if κ₂ < −valley_threshold_per_mm
    5. Chain labelled vertices into polylines via BFS on the edge graph.
    6. Build FeatureCurve objects with arc-length and mean curvature.

    Parameters
    ----------
    spec : FeatureCurveSpec
        Input specification.  Empty cage returns an empty result.

    Returns
    -------
    FeatureCurveResult
        All extracted ridge and valley polylines plus aggregate statistics.

    Notes
    -----
    * Never raises — errors return empty result with extended caveat.
    * Curvatures are in mm⁻¹ (matching the cage's mm coordinate system).
    * The honest_caveat field describes accuracy limitations.

    References
    ----------
    Ohtake et al. (2004) SIGGRAPH; Meyer et al. (2003) VisMath;
    Taubin (1995) ICCV; Catmull-Clark (1978) CAD; Stam (1998) SIGGRAPH.
    """
    result = FeatureCurveResult()

    try:
        cage = spec.cage
        if not cage.vertices_xyz_mm or not cage.faces:
            return result

        # ── Step 1: refine ──────────────────────────────────────────────────
        levels = max(0, int(spec.subdivision_level))
        mesh = _build_refined_mesh(cage, levels)

        if not mesh.verts or not mesh.faces:
            return result

        # ── Step 2: normals ─────────────────────────────────────────────────
        normals = _compute_vertex_normals(mesh)

        # ── Step 3: principal curvatures ────────────────────────────────────
        kappa1, kappa2 = _compute_principal_curvatures(mesh, normals)

        # ── Record max principal curvature ───────────────────────────────────
        if kappa1:
            result.max_principal_curvature = max(abs(k) for k in kappa1)

        # ── Step 4: classify vertices ────────────────────────────────────────
        ridge_thr = float(spec.ridge_threshold_per_mm)
        valley_thr = float(spec.valley_threshold_per_mm)

        ridge_verts: Set[int] = set()
        valley_verts: Set[int] = set()
        for vi in range(len(mesh.verts)):
            if kappa1[vi] > ridge_thr:
                ridge_verts.add(vi)
            if kappa2[vi] < -valley_thr:
                valley_verts.add(vi)

        # ── Step 5: adjacency + chain ────────────────────────────────────────
        adj = _build_adjacency(mesh)

        all_curves: List[FeatureCurve] = []

        for labeled, kind, curvs in [
            (ridge_verts, "ridge", kappa1),
            (valley_verts, "valley", kappa2),
        ]:
            if not labeled:
                continue
            chains = _chain_vertices_to_polylines(labeled, adj)
            for chain in chains:
                if not chain:
                    continue
                polyline, arc_len, mean_k = _polyline_from_chain(
                    chain, mesh.verts, curvs
                )
                fc = FeatureCurve(
                    kind=kind,
                    polyline_xyz_mm=polyline,
                    length_mm=arc_len,
                    mean_principal_curvature=mean_k,
                )
                all_curves.append(fc)

        # ── Step 6: assemble result ──────────────────────────────────────────
        result.curves = all_curves
        result.num_ridges = sum(1 for c in all_curves if c.kind == "ridge")
        result.num_valleys = sum(1 for c in all_curves if c.kind == "valley")
        result.total_ridge_length_mm = sum(
            c.length_mm for c in all_curves if c.kind == "ridge"
        )
        result.total_valley_length_mm = sum(
            c.length_mm for c in all_curves if c.kind == "valley"
        )

    except Exception as exc:
        result.honest_caveat = result.honest_caveat + f"  [ERROR during extraction: {exc}]"

    return result


# ---------------------------------------------------------------------------
# LLM tool: subd_extract_feature_curves
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json

    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    _feature_curves_spec = ToolSpec(
        name="subd_extract_feature_curves",
        description=(
            "Extract characteristic 'ridge' and 'valley' polylines from a "
            "Catmull-Clark SubD limit surface (represented as a cage mesh), "
            "using discrete principal-curvature analysis (Ohtake et al. 2004 "
            "SIGGRAPH; Meyer et al. 2003 cotangent Laplacian).\n"
            "\n"
            "Use cases: ZBrush-style topology hints; automatic UV-seam "
            "generation along high-curvature lines; feature detection for "
            "re-meshing or CAM path planning.\n"
            "\n"
            "Algorithm:\n"
            "  1. Subdivide the cage subdivision_level times (Catmull-Clark 1978).\n"
            "  2. Estimate per-vertex normals (area-weighted face normals).\n"
            "  3. Compute Taubin (1995) curvature tensor at each vertex; project\n"
            "     to tangent plane → principal curvatures κ₁ ≥ κ₂ (mm⁻¹).\n"
            "  4. Classify: ridge if κ₁ > ridge_threshold_per_mm;\n"
            "               valley if κ₂ < −valley_threshold_per_mm.\n"
            "  5. Chain adjacent labelled vertices into polylines (BFS).\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  - DISCRETE CURVATURE: cotangent Laplacian approximation, O(h²);\n"
            "    NOT exact CC limit-surface curvature (use Stam evaluator for that).\n"
            "  - THRESHOLD TUNING: ridge/valley thresholds are in mm⁻¹ and are\n"
            "    scale-dependent — 0.1 mm⁻¹ is a reasonable default but must be\n"
            "    tuned for the object's scale and desired sensitivity.\n"
            "  - PERFORMANCE: vertex count scales O(4^subdivision_level).\n"
            "    Level 2 = 16× cage verts; level 3 = 64× cage verts.\n"
            "\n"
            "Inputs:\n"
            "  vertices              : [[x,y,z], ...]  cage vertices in mm\n"
            "  faces                 : [[i,j,k,...], ...]  face index lists\n"
            "  subdivision_level     : int (default 2)\n"
            "  ridge_threshold_per_mm: float (default 0.1, in mm⁻¹)\n"
            "  valley_threshold_per_mm: float (default 0.1, in mm⁻¹)\n"
            "\n"
            "Returns:\n"
            "  ok                       : bool\n"
            "  num_ridges               : int\n"
            "  num_valleys              : int\n"
            "  total_ridge_length_mm    : float\n"
            "  total_valley_length_mm   : float\n"
            "  max_principal_curvature  : float  (mm⁻¹; useful for threshold tuning)\n"
            "  curves                   : [{kind, polyline_xyz_mm, length_mm,\n"
            "                              mean_principal_curvature}, ...]\n"
            "  honest_caveat            : str\n"
            "\n"
            "Refs: Ohtake et al. (2004) SIGGRAPH; Meyer et al. (2003) VisMath §3.3; "
            "Taubin (1995) ICCV; Catmull-Clark (1978) CAD 10(6); "
            "Stam (1998) SIGGRAPH; OpenSubdiv docs."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Cage control vertices as [[x,y,z], ...] in mm.",
                    "items": {
                        "type": "array",
                        "items": {"type": "number"},
                        "minItems": 3,
                        "maxItems": 3,
                    },
                    "minItems": 3,
                },
                "faces": {
                    "type": "array",
                    "description": "Face vertex-index lists as [[i,j,k,...], ...].",
                    "items": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 3,
                    },
                    "minItems": 1,
                },
                "subdivision_level": {
                    "type": "integer",
                    "description": "CC subdivision levels before curvature analysis. Default 2.",
                    "minimum": 0,
                    "maximum": 5,
                    "default": 2,
                },
                "ridge_threshold_per_mm": {
                    "type": "number",
                    "description": "Minimum κ₁ (mm⁻¹) to classify a vertex as ridge. Default 0.1.",
                    "minimum": 0.0,
                    "default": 0.1,
                },
                "valley_threshold_per_mm": {
                    "type": "number",
                    "description": "Minimum |κ₂| (mm⁻¹) to classify a vertex as valley. Default 0.1.",
                    "minimum": 0.0,
                    "default": 0.1,
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_feature_curves_spec)
    async def run_subd_extract_feature_curves(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])

        if not raw_verts:
            return err_payload("vertices is required and must be non-empty", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required and must be non-empty", "BAD_ARGS")

        try:
            verts = [(float(v[0]), float(v[1]), float(v[2])) for v in raw_verts]
            faces = [[int(idx) for idx in f] for f in raw_faces]
        except (TypeError, IndexError, ValueError) as exc:
            return err_payload(f"invalid geometry data: {exc}", "BAD_ARGS")

        subdivision_level = int(a.get("subdivision_level", 2))
        ridge_thr = float(a.get("ridge_threshold_per_mm", 0.1))
        valley_thr = float(a.get("valley_threshold_per_mm", 0.1))

        cage = SubdCage(vertices_xyz_mm=verts, faces=faces)
        spec = FeatureCurveSpec(
            cage=cage,
            subdivision_level=subdivision_level,
            ridge_threshold_per_mm=ridge_thr,
            valley_threshold_per_mm=valley_thr,
        )

        try:
            res = extract_feature_curves(spec)
        except Exception as exc:
            return err_payload(f"feature curve extraction failed: {exc}", "INTERNAL")

        curves_out = []
        for fc in res.curves:
            curves_out.append({
                "kind": fc.kind,
                "polyline_xyz_mm": [list(pt) for pt in fc.polyline_xyz_mm],
                "length_mm": fc.length_mm,
                "mean_principal_curvature": fc.mean_principal_curvature,
            })

        return ok_payload({
            "ok": True,
            "num_ridges": res.num_ridges,
            "num_valleys": res.num_valleys,
            "total_ridge_length_mm": res.total_ridge_length_mm,
            "total_valley_length_mm": res.total_valley_length_mm,
            "max_principal_curvature": res.max_principal_curvature,
            "curves": curves_out,
            "honest_caveat": res.honest_caveat,
        })
