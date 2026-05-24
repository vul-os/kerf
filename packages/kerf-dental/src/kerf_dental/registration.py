"""
kerf_dental.registration — ICP multi-scan mesh registration + deviation map.

Implements:
  - Point-to-point ICP  (Besl & McKay 1992, IEEE TPAMI 14(2):239–256)
  - Point-to-plane ICP  (Chen & Medioni 1991; linearised normal eqn.)
  - kd-tree nearest-neighbour  (scipy.spatial.KDTree)
  - Adaptive outlier rejection  (distance threshold = median + k*MAD)
  - Convergence on RMS change  (Rusinkiewicz & Levoy 2001, §4)
  - Deviation map  (per-vertex signed distance between two aligned meshes)

Public API
----------
  register_scans(source, target, …) -> RegistrationResult
  deviation_map(source_verts, target_verts, target_faces) -> DeviationResult

All coordinates in millimetres (dental convention).

References
----------
  Besl P, McKay N. "A method for registration of 3D shapes."
    IEEE Trans. Pattern Anal. Mach. Intell. 14(2):239–256, 1992.
  Chen Y, Medioni G. "Object modeling by registration of multiple range images."
    Image Vision Comput. 10(3):145–155, 1991.
  Rusinkiewicz S, Levoy M. "Efficient variants of the ICP algorithm."
    Proc. 3DIM 2001, pp. 145–152.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Sequence

import numpy as np
from numpy.typing import ArrayLike
from scipy.spatial import KDTree


# ---------------------------------------------------------------------------
# Public data models
# ---------------------------------------------------------------------------

@dataclass
class RegistrationResult:
    """Output of :func:`register_scans`."""

    #: 4×4 rigid-body transform (rotation + translation) mapping source → target frame.
    transform: np.ndarray          # shape (4, 4), float64

    #: 3×3 rotation matrix component of *transform*.
    rotation: np.ndarray           # shape (3, 3), float64

    #: Translation vector component of *transform* (mm).
    translation: np.ndarray        # shape (3,), float64

    #: RMS point-to-point residual after final iteration (mm).
    rms_mm: float

    #: Number of ICP iterations executed.
    iterations: int

    #: True if the algorithm converged before max_iterations.
    converged: bool

    #: Source vertices after applying *transform*.
    aligned_source: np.ndarray     # shape (N, 3), float64

    #: Fraction of source points retained after outlier rejection (last iter).
    inlier_fraction: float


@dataclass
class DeviationResult:
    """Per-vertex signed deviation of source from target surface."""

    #: Source vertices (transformed into target frame).
    source_vertices: np.ndarray    # (N, 3)

    #: Signed distance for each source vertex (mm).
    #  Positive → source is *outside* target (proud); negative → inside.
    signed_distances: np.ndarray   # (N,)

    #: Unsigned (absolute) deviation for each source vertex (mm).
    unsigned_distances: np.ndarray # (N,)

    #: RMS deviation (mm).
    rms_mm: float

    #: 95th-percentile absolute deviation (mm).
    p95_mm: float

    #: Mean signed deviation (mm).  Ideally ≈ 0 for identical meshes.
    mean_signed_mm: float


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_float64_pts(pts: ArrayLike) -> np.ndarray:
    """Coerce *pts* to a (N, 3) float64 array; validate shape."""
    arr = np.asarray(pts, dtype=np.float64)
    if arr.ndim == 1 and arr.shape[0] == 3:
        arr = arr[None, :]          # single point → (1, 3)
    if arr.ndim != 2 or arr.shape[1] != 3:
        raise ValueError(
            f"Expected (N, 3) point array; got shape {arr.shape}"
        )
    return arr


def _compute_vertex_normals(
    vertices: np.ndarray,
    faces: np.ndarray | None,
) -> np.ndarray:
    """Area-weighted per-vertex normals for point-to-plane ICP.

    If *faces* is None or empty, falls back to a zero-normal array
    (which causes point-to-plane to degenerate to point-to-point — safe).
    """
    normals = np.zeros_like(vertices)
    if faces is None or len(faces) == 0:
        return normals

    faces = np.asarray(faces, dtype=np.int64)
    v0 = vertices[faces[:, 0]]
    v1 = vertices[faces[:, 1]]
    v2 = vertices[faces[:, 2]]
    face_normals = np.cross(v1 - v0, v2 - v0)  # (F, 3), area-weighted
    np.add.at(normals, faces[:, 0], face_normals)
    np.add.at(normals, faces[:, 1], face_normals)
    np.add.at(normals, faces[:, 2], face_normals)

    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    safe = norms[:, 0] > 1e-12
    normals[safe] /= norms[safe]
    return normals


def _outlier_mask(
    distances: np.ndarray,
    k: float = 3.0,
) -> np.ndarray:
    """Boolean mask: True = inlier.

    Threshold = median(d) + k * MAD, where MAD is the median absolute
    deviation (a robust scale estimate; Hampel 1974).  k=3 keeps >99 % of
    Gaussian-distributed residuals while rejecting coarse outliers.
    """
    if len(distances) == 0:
        return np.ones(0, dtype=bool)
    med = float(np.median(distances))
    mad = float(np.median(np.abs(distances - med)))
    threshold = med + k * max(mad, 1e-9)
    return distances <= threshold


def _umeyama_rotation(
    src_c: np.ndarray,
    tgt_c: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """SVD-based optimal rotation (Umeyama 1991, point-to-point).

    Minimises sum ||R·p_i + t - q_i||².

    Parameters
    ----------
    src_c : (K, 3) centred source correspondences
    tgt_c : (K, 3) centred target correspondences

    Returns
    -------
    R : (3, 3) rotation matrix
    t : (3,)   translation (applied *before* rotation undoes centring)
    """
    H = src_c.T @ tgt_c          # (3, 3) cross-covariance
    U, _, Vt = np.linalg.svd(H)
    # Ensure proper rotation (det = +1) — handle reflections
    d = np.linalg.det(Vt.T @ U.T)
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T
    return R


def _point_to_plane_step(
    src: np.ndarray,
    tgt_pts: np.ndarray,
    tgt_nrm: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Linearised point-to-plane minimisation (Chen & Medioni 1991).

    Solves for 6-DOF twist [α, β, γ, tx, ty, tz] via the normal equations:

        A^T A x = A^T b

    where each row of A encodes the cross product source × normal and the
    normal itself, and b is the current point-to-plane residual.

    Returns
    -------
    R : (3, 3) approximate rotation
    t : (3,)   translation
    """
    # Build the 6-column design matrix
    n = src.shape[0]
    cross = np.cross(src, tgt_nrm)         # (N, 3):  s × n_i
    A = np.hstack([cross, tgt_nrm])        # (N, 6)
    diff = tgt_pts - src                   # (N, 3)
    b = np.einsum('ij,ij->i', diff, tgt_nrm)  # (N,): dot per row

    # Least-squares via pseudo-inverse (normal equations)
    AtA = A.T @ A
    Atb = A.T @ b
    try:
        x = np.linalg.solve(AtA, Atb)
    except np.linalg.LinAlgError:
        x = np.linalg.lstsq(A, b, rcond=None)[0]

    α, β, γ = x[:3]
    tx, ty, tz = x[3:]

    # Small-angle rotation matrix  (first-order Rodrigues)
    R = np.array([
        [ 1.0,  -γ,   β],
        [  γ,  1.0,  -α],
        [ -β,    α,  1.0],
    ], dtype=np.float64)
    # Re-orthogonalise via SVD to keep R ∈ SO(3)
    U, _, Vt = np.linalg.svd(R)
    d = np.linalg.det(Vt.T @ U.T)
    D = np.diag([1.0, 1.0, d])
    R = Vt.T @ D @ U.T

    t = np.array([tx, ty, tz], dtype=np.float64)
    return R, t


# ---------------------------------------------------------------------------
# Core ICP algorithm
# ---------------------------------------------------------------------------

def _icp(
    source: np.ndarray,        # (N, 3) — moved each iteration
    target: np.ndarray,        # (M, 3) — fixed reference cloud
    target_faces: np.ndarray | None,
    method: Literal["point_to_point", "point_to_plane"],
    max_iterations: int,
    convergence_tol: float,
    outlier_k: float,
    subsample: int | None,
) -> RegistrationResult:
    """Inner ICP loop; returns a RegistrationResult."""

    # Optionally subsample source for speed
    if subsample is not None and subsample < len(source):
        rng = np.random.default_rng(42)
        idx = rng.choice(len(source), subsample, replace=False)
        src_working = source[idx].copy()
    else:
        src_working = source.copy()
        idx = None

    # Precompute target normals for point-to-plane
    tgt_tree = KDTree(target)
    if method == "point_to_plane":
        tgt_normals = _compute_vertex_normals(target, target_faces)
    else:
        tgt_normals = None

    # Accumulate transform as 4×4 homogeneous matrix
    T_accum = np.eye(4, dtype=np.float64)

    prev_rms = float("inf")
    converged = False
    inlier_frac = 1.0

    for it in range(max_iterations):
        # --- 1. Nearest-neighbour query -----------------------------------
        dists, nn_idx = tgt_tree.query(src_working, workers=1)
        tgt_pts = target[nn_idx]

        # --- 2. Outlier rejection -----------------------------------------
        mask = _outlier_mask(dists, k=outlier_k)
        if mask.sum() < 6:
            # Too few inliers — keep all and hope for the best
            mask = np.ones(len(mask), dtype=bool)
        inlier_frac = float(mask.mean())

        src_in = src_working[mask]
        tgt_in = tgt_pts[mask]
        dists_in = dists[mask]

        # --- 3. RMS check -------------------------------------------------
        rms = float(np.sqrt(np.mean(dists_in ** 2)))
        delta_rms = abs(prev_rms - rms)
        prev_rms = rms

        # --- 4. Compute optimal R, t --------------------------------------
        if method == "point_to_plane" and tgt_normals is not None:
            nrm_in = tgt_normals[nn_idx[mask]]
            # Check if normals are non-trivial
            if np.any(np.linalg.norm(nrm_in, axis=1) > 1e-6):
                R, t = _point_to_plane_step(src_in, tgt_in, nrm_in)
            else:
                # Fallback to point-to-point when no valid normals
                mu_s = src_in.mean(axis=0)
                mu_t = tgt_in.mean(axis=0)
                R = _umeyama_rotation(src_in - mu_s, tgt_in - mu_t)
                t = mu_t - R @ mu_s
        else:
            # Point-to-point: Besl-McKay SVD step
            mu_s = src_in.mean(axis=0)
            mu_t = tgt_in.mean(axis=0)
            R = _umeyama_rotation(src_in - mu_s, tgt_in - mu_t)
            t = mu_t - R @ mu_s

        # --- 5. Apply incremental transform to working set ----------------
        src_working = (R @ src_working.T).T + t

        # --- 6. Accumulate into T_accum -----------------------------------
        T_inc = np.eye(4)
        T_inc[:3, :3] = R
        T_inc[:3, 3] = t
        T_accum = T_inc @ T_accum

        # --- 7. Convergence check -----------------------------------------
        if delta_rms < convergence_tol and it > 0:
            converged = True
            break

    # Apply accumulated transform to *full* source cloud (not just subsample)
    R_final = T_accum[:3, :3]
    t_final = T_accum[:3, 3]
    aligned_full = (R_final @ source.T).T + t_final

    # Final RMS on full set (no rejection) for reporting
    d_final, _ = tgt_tree.query(aligned_full, workers=1)
    rms_final = float(np.sqrt(np.mean(d_final ** 2)))

    return RegistrationResult(
        transform=T_accum,
        rotation=R_final,
        translation=t_final,
        rms_mm=rms_final,
        iterations=it + 1,
        converged=converged,
        aligned_source=aligned_full,
        inlier_fraction=inlier_frac,
    )


# ---------------------------------------------------------------------------
# Public API: register_scans
# ---------------------------------------------------------------------------

def register_scans(
    source: ArrayLike,
    target: ArrayLike,
    *,
    source_faces: ArrayLike | None = None,
    target_faces: ArrayLike | None = None,
    method: Literal["point_to_point", "point_to_plane"] = "point_to_plane",
    max_iterations: int = 100,
    convergence_tol: float = 1e-6,
    outlier_k: float = 3.0,
    subsample: int | None = None,
) -> RegistrationResult:
    """Register two intraoral-scan meshes/point-clouds via ICP.

    Aligns *source* onto *target* (target frame is fixed).

    Parameters
    ----------
    source : array-like (N, 3)
        Source vertices (mm).  May be a raw point cloud or mesh vertices.
    target : array-like (M, 3)
        Target vertices (mm).
    source_faces : array-like (Fs, 3), optional
        Triangle index array for the source mesh (unused in core ICP,
        reserved for future normal-driven initialisation).
    target_faces : array-like (Ft, 3), optional
        Triangle index array for the target mesh.  Used to compute
        per-vertex normals for point-to-plane ICP.  If omitted, the
        algorithm falls back to point-to-point.
    method : {"point_to_plane", "point_to_point"}
        "point_to_plane" uses the Chen–Medioni linearised normal equations
        (faster convergence on smooth surfaces, recommended for IOS scans).
        "point_to_point" uses the Besl–McKay SVD step.
    max_iterations : int
        Upper bound on ICP iterations (default 100).
    convergence_tol : float
        Stop when |ΔRMS| < convergence_tol (mm, default 1e-6).
    outlier_k : float
        Outlier threshold factor: keep d ≤ median + k·MAD (default 3.0).
    subsample : int or None
        If set, subsample the source to at most *subsample* points for the
        iterative step (full source is transformed at the end).

    Returns
    -------
    RegistrationResult
        Contains the 4×4 rigid transform, rotation/translation components,
        final RMS residual (mm), iteration count, convergence flag,
        aligned source vertices, and inlier fraction.

    Notes
    -----
    The algorithm follows Besl & McKay (1992) §IV with the outlier
    rejection heuristic from Rusinkiewicz & Levoy (2001) §2.2 and the
    point-to-plane step from Chen & Medioni (1991).  Registration is
    purely rigid (6 DOF); no scale.
    """
    src = _to_float64_pts(source)
    tgt = _to_float64_pts(target)

    if len(src) < 3:
        raise ValueError("source must contain at least 3 points")
    if len(tgt) < 3:
        raise ValueError("target must contain at least 3 points")

    tf = None if target_faces is None else np.asarray(target_faces, dtype=np.int64)
    # If no faces given, point_to_plane degrades to point_to_point inside _icp
    return _icp(
        src, tgt,
        target_faces=tf,
        method=method,
        max_iterations=max_iterations,
        convergence_tol=convergence_tol,
        outlier_k=outlier_k,
        subsample=subsample,
    )


# ---------------------------------------------------------------------------
# Public API: deviation_map
# ---------------------------------------------------------------------------

def deviation_map(
    source_vertices: ArrayLike,
    target_vertices: ArrayLike,
    target_faces: ArrayLike | None = None,
) -> DeviationResult:
    """Compute per-vertex signed deviation of *source_vertices* from target surface.

    The sign convention follows dental metrology practice:
      - **positive** = source vertex is *outside* (proud of) the target surface
      - **negative** = source vertex is *inside* (recessed into) the target surface

    Sign is determined by comparing the displacement vector with the target
    surface normal at the nearest point.  When *target_faces* is supplied and
    normals can be computed, the sign is the dot-product of the displacement
    with the normal.  Without faces, absolute distances are returned (unsigned
    set to 0 for sign).

    Parameters
    ----------
    source_vertices : array-like (N, 3)
        Source point cloud / mesh vertices, already in the target frame
        (i.e. *after* :func:`register_scans` has been applied).
    target_vertices : array-like (M, 3)
        Target mesh vertices (mm).
    target_faces : array-like (Ft, 3), optional
        Triangle index array for the target mesh (enables signed distance).

    Returns
    -------
    DeviationResult
    """
    src = _to_float64_pts(source_vertices)
    tgt = _to_float64_pts(target_vertices)

    tree = KDTree(tgt)
    unsigned, nn_idx = tree.query(src, workers=1)
    unsigned = unsigned.astype(np.float64)

    # Signed distance via normal dot product
    if target_faces is not None and len(target_faces) > 0:
        tgt_normals = _compute_vertex_normals(tgt, np.asarray(target_faces, dtype=np.int64))
        nn_normals = tgt_normals[nn_idx]           # (N, 3)
        disp = src - tgt[nn_idx]                   # (N, 3) displacement
        dot = np.einsum('ij,ij->i', disp, nn_normals)
        # Where normal is ~zero, fall back to unsigned (sign=+1)
        valid = np.linalg.norm(nn_normals, axis=1) > 1e-6
        sign = np.where(valid, np.sign(dot), 1.0)
        signed = sign * unsigned
    else:
        # No face data — return unsigned values; sign undefined
        signed = unsigned.copy()

    rms = float(np.sqrt(np.mean(unsigned ** 2)))
    p95 = float(np.percentile(unsigned, 95)) if len(unsigned) > 0 else 0.0
    mean_signed = float(signed.mean()) if len(signed) > 0 else 0.0

    return DeviationResult(
        source_vertices=src,
        signed_distances=signed,
        unsigned_distances=unsigned,
        rms_mm=rms,
        p95_mm=p95,
        mean_signed_mm=mean_signed,
    )


# ---------------------------------------------------------------------------
# Convenience: compose_transforms
# ---------------------------------------------------------------------------

def compose_transforms(T1: np.ndarray, T2: np.ndarray) -> np.ndarray:
    """Compose two 4×4 rigid transforms: apply T1 first, then T2."""
    return np.asarray(T2, dtype=np.float64) @ np.asarray(T1, dtype=np.float64)


def invert_transform(T: np.ndarray) -> np.ndarray:
    """Analytically invert a 4×4 rigid-body transform."""
    T = np.asarray(T, dtype=np.float64)
    R = T[:3, :3]
    t = T[:3, 3]
    T_inv = np.eye(4)
    T_inv[:3, :3] = R.T
    T_inv[:3, 3] = -(R.T @ t)
    return T_inv


def apply_transform(T: np.ndarray, pts: ArrayLike) -> np.ndarray:
    """Apply a 4×4 rigid transform to a (N, 3) point array."""
    pts = _to_float64_pts(pts)
    R = T[:3, :3]
    t = T[:3, 3]
    return (R @ pts.T).T + t
