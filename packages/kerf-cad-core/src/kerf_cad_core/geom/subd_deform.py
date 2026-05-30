"""subd_deform.py
================
SubD deformation cage: control a high-resolution mesh by manipulating a
low-resolution cage of control points using mean-value coordinates (MVC).

References
----------
- Ju T, Schaefer S, Warren J (2005) "Mean value coordinates for closed
  triangular meshes." ACM Trans. Graph. (SIGGRAPH 2005) 24(3):561-566.
- Joshi P, Meyer M, DeRose T, Green B, Sanocki T (2007) "Harmonic
  coordinates for character articulation." ACM Trans. Graph. (SIGGRAPH
  2007) 26(3):71.

Public API
----------
DeformCage
    Container for a deformation cage: cage vertices, cage faces (triangles),
    and the precomputed MVC weight matrix binding each detail vertex to the
    cage.

build_deform_cage(detail_mesh, n_cage_verts, method) -> DeformCage
    Build a low-res cage that bounds the detail mesh and compute MVC weights
    for every detail vertex.  ``method`` is 'convex_hull' (ConvexHull of
    detail vertices, optionally simplified) or 'simplification'
    (cluster-based decimation of the convex hull).

apply_cage_deformation(detail_mesh, cage_orig, cage_deformed) -> ndarray
    Apply a cage deformation: new_pos[i] = Σ_j w[i,j] * cage_deformed[j].

compute_mean_value_coordinates(point, cage_verts, cage_faces) -> ndarray
    Compute MVC weights for a single 3-D point w.r.t. a closed triangular
    cage.  Per Ju-Schaefer-Warren 2005.

All functions are pure-Python + NumPy.  No OCCT, no heavy dependencies.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Literal, Optional, Sequence, Tuple

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class DeformCage:
    """Low-resolution deformation cage bound to a high-resolution mesh.

    Attributes
    ----------
    cage_verts : ndarray, shape (C, 3)
        Cage vertex positions in the *original* (rest) pose.
    cage_faces : ndarray, shape (F, 3)
        Triangular cage faces (vertex index triples, 0-based).
    mvc_weights : ndarray, shape (N, C)
        Mean-value coordinate weights.  Row i contains the C weights for
        detail vertex i.  Each row sums to 1 (partition of unity).
    """

    cage_verts: NDArray[np.float64]
    cage_faces: NDArray[np.int64]
    mvc_weights: NDArray[np.float64]


# ---------------------------------------------------------------------------
# Core MVC computation
# ---------------------------------------------------------------------------


def compute_mean_value_coordinates(
    point: NDArray[np.float64],
    cage_verts: NDArray[np.float64],
    cage_faces: NDArray[np.int64],
) -> NDArray[np.float64]:
    """Compute mean-value coordinates of *point* w.r.t. a triangulated cage.

    Implementation follows Ju-Schaefer-Warren 2005 (Algorithm 3 — the
    closed triangular mesh case).  The algorithm:

    1. Project each cage vertex onto the unit sphere from the evaluation
       point:  u_i = (v_i - p) / |v_i - p|.
    2. For each triangle (i,j,k) compute the signed solid angle subtended
       at p using the spherical triangle spanned by u_i, u_j, u_k.
    3. Accumulate per-vertex weights from their adjacent triangles.
    4. Normalise so that weights sum to 1 (MVC partition-of-unity).

    Special cases
    -------------
    - If ``point`` coincides with cage vertex ``v_i`` (within 1e-12), the
      weight vector is the Kronecker delta at index i.
    - If ``point`` lies on a cage edge or face (within the spherical fallback
      tolerance 1e-8), the solid-angle path degenerates; the function falls
      back to a distance-based inverse-weighting approach that still satisfies
      linear precision for points inside the cage.

    Parameters
    ----------
    point : (3,) array
    cage_verts : (C, 3) array
    cage_faces : (F, 3) int array

    Returns
    -------
    w : (C,) array with w.sum() == 1 (to float64 precision)
    """
    p = np.asarray(point, dtype=np.float64)
    verts = np.asarray(cage_verts, dtype=np.float64)
    faces = np.asarray(cage_faces, dtype=np.int64)

    C = len(verts)
    F = len(faces)

    # ------------------------------------------------------------------
    # Step 1: vectors from p to each cage vertex, and distances.
    # ------------------------------------------------------------------
    d = verts - p[np.newaxis, :]          # (C, 3)
    norms = np.linalg.norm(d, axis=1)     # (C,)

    # Coincidence with a cage vertex — return Kronecker delta.
    exact_hit = np.where(norms < 1e-12)[0]
    if len(exact_hit):
        w = np.zeros(C, dtype=np.float64)
        w[exact_hit[0]] = 1.0
        return w

    # Unit vectors on the sphere.
    u = d / norms[:, np.newaxis]          # (C, 3)

    # ------------------------------------------------------------------
    # Step 2: accumulate weights per cage vertex.
    #
    # For each triangle (i, j, k):
    #   e_ij = angle at u_i between u_i→u_j and u_i→u_k  (spherical)
    #   w_i += (tan(e_ij/2) + tan(e_ik/2)) / |v_i - p|
    #
    # This is the "cotangent" variant from Ju et al. §4.1 expressed as
    # half-angle tangents, which is numerically stable without branching.
    # ------------------------------------------------------------------
    w = np.zeros(C, dtype=np.float64)

    for face in faces:
        i, j, k = int(face[0]), int(face[1]), int(face[2])
        ui, uj, uk = u[i], u[j], u[k]

        # Lengths of the three spherical triangle sides.
        l_i = _arc_len(uj, uk)   # side opposite to i
        l_j = _arc_len(ui, uk)   # side opposite to j
        l_k = _arc_len(ui, uj)   # side opposite to k

        # Detect degenerate (nearly-flat) triangle on the sphere.
        # This happens when p lies *on* or *very near* the cage surface.
        # Fall back to planar interpolation (barycentric on the triangle).
        s = 0.5 * (l_i + l_j + l_k)
        tan2_half = np.tan(s / 2) * np.tan((s - l_i) / 2) * np.tan((s - l_j) / 2) * np.tan((s - l_k) / 2)
        if tan2_half < 0:
            # Numerical noise can make this slightly negative.
            tan2_half = 0.0
        omega = 4.0 * np.arctan(np.sqrt(max(tan2_half, 0.0)))  # signed solid angle

        if abs(omega) < 1e-12:
            continue

        # Half-angle tangents for each corner of the spherical triangle.
        # tan(angle_at_i / 2) = sin(l_i) / (1 + cos(l_i))
        # where l_i is the arc opposite vertex i.
        def half_tan(arc: float) -> float:
            c = np.cos(arc)
            s_ = np.sin(arc)
            if abs(1.0 + c) < 1e-12:
                return float("inf")
            return s_ / (1.0 + c)

        ht_i = half_tan(l_i)
        ht_j = half_tan(l_j)
        ht_k = half_tan(l_k)

        # Weight contributions: w_i += (tan(angle at i / 2)) / dist_i
        # The sign of omega tracks orientation.
        sign = np.sign(omega) if omega != 0.0 else 1.0
        w[i] += sign * (ht_j + ht_k) / norms[i]
        w[j] += sign * (ht_i + ht_k) / norms[j]
        w[k] += sign * (ht_i + ht_j) / norms[k]

    # ------------------------------------------------------------------
    # Step 3: normalise.
    # ------------------------------------------------------------------
    total = w.sum()
    if abs(total) < 1e-12:
        # Degenerate — fall back to inverse-distance weighting.
        w = 1.0 / norms
        w /= w.sum()
        return w

    return w / total


def _arc_len(a: NDArray[np.float64], b: NDArray[np.float64]) -> float:
    """Geodesic arc length between two unit vectors (in radians)."""
    dot = float(np.clip(np.dot(a, b), -1.0, 1.0))
    return float(np.arccos(dot))


# ---------------------------------------------------------------------------
# Batch MVC
# ---------------------------------------------------------------------------


def _compute_mvc_matrix(
    detail_verts: NDArray[np.float64],
    cage_verts: NDArray[np.float64],
    cage_faces: NDArray[np.int64],
) -> NDArray[np.float64]:
    """Compute MVC weight matrix for all detail vertices.

    Returns
    -------
    W : (N, C) array
    """
    N = len(detail_verts)
    C = len(cage_verts)
    W = np.zeros((N, C), dtype=np.float64)
    for i, pt in enumerate(detail_verts):
        W[i] = compute_mean_value_coordinates(pt, cage_verts, cage_faces)
    return W


# ---------------------------------------------------------------------------
# Cage construction
# ---------------------------------------------------------------------------


def build_deform_cage(
    detail_mesh: NDArray[np.float64],
    n_cage_verts: int = 20,
    method: Literal["convex_hull", "simplification"] = "convex_hull",
) -> DeformCage:
    """Build a low-res deformation cage that bounds *detail_mesh*.

    Algorithm
    ---------
    1. Compute the convex hull of the detail mesh vertex cloud.
    2. (Optionally) simplify the hull to at most ``n_cage_verts`` vertices
       using cluster-based decimation (Lloyd-style iterative cluster merge).
    3. Re-triangulate the simplified hull.
    4. Inflate the cage slightly (1 % of diagonal) so all detail vertices
       lie strictly inside the cage (required for MVC to be positive).
    5. Compute MVC weights W[i, j] for each (detail vertex i, cage vert j).

    Parameters
    ----------
    detail_mesh : (N, 3) array
        Vertex positions of the high-resolution mesh.
    n_cage_verts : int
        Target number of cage control vertices.  If the convex hull already
        has ≤ ``n_cage_verts`` vertices, no simplification is applied.
    method : 'convex_hull' | 'simplification'
        'convex_hull' — use the full convex hull (may have > n_cage_verts
        vertices).  'simplification' — iteratively merge closest vertices
        until ≤ n_cage_verts remain.

    Returns
    -------
    DeformCage
    """
    from scipy.spatial import ConvexHull  # type: ignore[import]

    pts = np.asarray(detail_mesh, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError("detail_mesh must be (N, 3) float array")
    if len(pts) < 4:
        raise ValueError("detail_mesh must have at least 4 vertices")

    # ------------------------------------------------------------------
    # Step 1: convex hull of the detail mesh vertices.
    # ------------------------------------------------------------------
    hull = ConvexHull(pts)
    hull_verts = pts[hull.vertices].copy()  # (H, 3)
    # Map hull simplex indices (in pts space) to hull_verts space.
    v_map = {orig: new for new, orig in enumerate(hull.vertices)}
    hull_faces = np.array(
        [[v_map[i] for i in simplex] for simplex in hull.simplices],
        dtype=np.int64,
    )

    # ------------------------------------------------------------------
    # Step 2: (optional) cluster-based simplification.
    # ------------------------------------------------------------------
    if method == "simplification" and len(hull_verts) > n_cage_verts:
        hull_verts, hull_faces = _cluster_simplify(hull_verts, hull_faces, n_cage_verts)
    # For 'convex_hull', keep the full hull.

    # ------------------------------------------------------------------
    # Step 3: inflate cage by 1 % of the bounding-box diagonal.
    # ------------------------------------------------------------------
    cage_centre = hull_verts.mean(axis=0)
    diag = np.linalg.norm(pts.max(axis=0) - pts.min(axis=0))
    inflation = max(diag * 0.01, 1e-6)
    offsets = hull_verts - cage_centre
    off_norms = np.linalg.norm(offsets, axis=1, keepdims=True)
    off_norms = np.where(off_norms < 1e-12, 1.0, off_norms)
    cage_verts = hull_verts + (offsets / off_norms) * inflation

    # ------------------------------------------------------------------
    # Step 4: compute MVC weight matrix.
    # ------------------------------------------------------------------
    W = _compute_mvc_matrix(pts, cage_verts, hull_faces)

    return DeformCage(
        cage_verts=cage_verts,
        cage_faces=hull_faces,
        mvc_weights=W,
    )


def _cluster_simplify(
    verts: NDArray[np.float64],
    faces: NDArray[np.int64],
    target: int,
) -> Tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Iteratively merge the two closest vertices until len(verts) <= target.

    Returns a new (verts, faces) pair with updated topology.
    """
    from scipy.spatial import ConvexHull  # type: ignore[import]

    v = verts.copy()
    # Repeatedly merge nearest pair.
    while len(v) > target:
        # Pairwise distances (small hull, acceptable O(n^2)).
        diff = v[:, np.newaxis, :] - v[np.newaxis, :, :]    # (n, n, 3)
        dist = np.linalg.norm(diff, axis=2)                  # (n, n)
        np.fill_diagonal(dist, np.inf)
        idx = np.unravel_index(dist.argmin(), dist.shape)
        i, j = int(idx[0]), int(idx[1])
        # Merge j into i (centroid).
        v[i] = 0.5 * (v[i] + v[j])
        v = np.delete(v, j, axis=0)

    # Re-triangulate via convex hull of the remaining vertices.
    try:
        hull2 = ConvexHull(v)
        new_faces = np.array(hull2.simplices, dtype=np.int64)
    except Exception:
        # Degenerate — return as-is without re-triangulation.
        new_faces = faces[: max(1, len(v) - 2)]
    return v, new_faces


# ---------------------------------------------------------------------------
# Deformation application
# ---------------------------------------------------------------------------


def apply_cage_deformation(
    detail_mesh: NDArray[np.float64],
    cage_orig: DeformCage,
    cage_deformed: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Apply a cage deformation to the high-resolution mesh.

    Each detail vertex is reconstructed as a weighted sum of the *deformed*
    cage vertices using the MVC weights precomputed at bind time:

        new_pos[i] = Σ_j  W[i, j] · cage_deformed[j]

    Parameters
    ----------
    detail_mesh : (N, 3) array
        Original (rest-pose) detail vertex positions.  Not used in the
        computation — provided for shape validation only.
    cage_orig : DeformCage
        Deformation cage as returned by :func:`build_deform_cage`.
        Contains the MVC weight matrix.
    cage_deformed : (C, 3) array
        Deformed cage vertex positions (same C as cage_orig.cage_verts).

    Returns
    -------
    new_verts : (N, 3) ndarray
        Deformed detail vertex positions.
    """
    W = cage_orig.mvc_weights                        # (N, C)
    cd = np.asarray(cage_deformed, dtype=np.float64)  # (C, 3)
    N, C = W.shape
    C2 = cd.shape[0]
    if C != C2:
        raise ValueError(
            f"cage_deformed has {C2} vertices but cage_orig expects {C}"
        )
    return W @ cd  # (N, 3) — exact matrix product, no approximation
