"""
nurbs_surface_fit.py
====================
NURBS freeform-surface fitting from segmented point clouds.

Implements the least-squares NURBS surface approximation algorithm from
Piegl & Tiller "The NURBS Book" §9.2 (global approximation) with:

  - Centripetal parameterisation (robust for noisy, irregular clouds).
  - Knot-vector placement via the averaging method (P&T §9.2.2).
  - Damped linear least-squares solve:
      min ||N · P - Q||_F^2 + λ ||D · P||_F^2
    where N is the tensor-product basis matrix, D is a finite-difference
    second-derivative (smoothness) operator on the control-point grid, and
    λ (lambda_smooth) is the damping weight.
  - Returns a NurbsSurface + a FitReport with diagnostics.

Public API
----------
nurbs_surface_fit(points, *, u_degree, v_degree, n_u_ctrl, n_v_ctrl,
                  lambda_smooth, seed) -> tuple[NurbsSurface, FitReport]

    points : (N, 3) or (Nu, Nv, 3) ndarray
        Point cloud.  If 2-D (N, 3) the cloud is unordered and the function
        builds an interior UV parameterisation.  If 3-D (Nu, Nv, 3) the
        points already form an ordered grid.

    u_degree, v_degree : int   B-spline degree in U and V (default 3).
    n_u_ctrl, n_v_ctrl : int   Number of control points (default 8).
    lambda_smooth : float      Smoothness damping weight (default 1e-3).
    seed : int                 RNG seed used for reproducibility (unused
                               currently but reserved for future stochastic
                               parameterisation).

Errors
------
FitError — raised on degenerate or insufficient inputs.

Dependencies
------------
numpy, scipy.linalg.lstsq — both available in the kerf-cad-core virtualenv
(declared in the WORKSPACE-DRIFT-FIX wave; see commit message if not yet
present in pyproject.toml).

Author: imranparuk
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

import numpy as np

try:
    from scipy.linalg import lstsq as _scipy_lstsq  # type: ignore[import]
    _SCIPY_AVAILABLE = True
except ImportError:  # pragma: no cover
    _SCIPY_AVAILABLE = False

from kerf_cad_core.geom.nurbs import NurbsSurface


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

class FitError(ValueError):
    """Raised when nurbs_surface_fit cannot proceed (bad/degenerate input)."""


@dataclass
class FitReport:
    """Diagnostics returned alongside the fitted NurbsSurface.

    Attributes
    ----------
    rms_residual   : float   RMS distance from input points to the surface.
    max_residual   : float   Maximum point-to-surface distance.
    n_iterations   : int     Number of solver iterations (always 1 for the
                             current direct LS solve; reserved for future
                             iterative refinement).
    condition_number : float Estimated condition number of the normal matrix
                             N^T N (before regularisation).  Large values
                             (>1e10) indicate near-singular problems; increase
                             lambda_smooth to stabilise.
    """
    rms_residual: float
    max_residual: float
    n_iterations: int
    condition_number: float


# ---------------------------------------------------------------------------
# Internal knot-span + basis-function helpers (P&T Algorithm A2.1 / A2.2)
# ---------------------------------------------------------------------------

def _find_span(n: int, p: int, u: float, U: np.ndarray) -> int:
    """NURBS Book Algorithm A2.1 — knot span binary search."""
    if u >= U[n + 1]:
        return n
    if u <= U[p]:
        return p
    lo, hi = p, n + 1
    mid = (lo + hi) // 2
    while u < U[mid] or u >= U[mid + 1]:
        if u < U[mid]:
            hi = mid
        else:
            lo = mid
        mid = (lo + hi) // 2
    return mid


def _basis_fns(i: int, u: float, p: int, U: np.ndarray) -> np.ndarray:
    """NURBS Book Algorithm A2.2 — non-zero B-spline basis values."""
    N = np.zeros(p + 1)
    N[0] = 1.0
    left = np.zeros(p + 1)
    right = np.zeros(p + 1)
    for j in range(1, p + 1):
        left[j] = u - U[i + 1 - j]
        right[j] = U[i + j] - u
        saved = 0.0
        for r in range(j):
            denom = right[r + 1] + left[j - r]
            temp = N[r] / denom if abs(denom) > 1e-15 else 0.0
            N[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        N[j] = saved
    return N


# ---------------------------------------------------------------------------
# Centripetal parameterisation (P&T §9.2.1)
# ---------------------------------------------------------------------------

def _centripetal_params_1d(pts: np.ndarray) -> np.ndarray:
    """1-D centripetal parameterisation of a polyline (N,3) → (N,) in [0,1].

    Uses chord-lengths raised to the power 0.5 (centripetal rule).
    Robust against irregular spacing and near-duplicate points.
    """
    n = len(pts)
    t = np.zeros(n)
    chords = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    chords = np.sqrt(np.maximum(chords, 0.0))  # centripetal: sqrt of chord
    total = np.sum(chords)
    if total < 1e-14:
        # All points coincide — raise upstream
        return None
    t[1:] = np.cumsum(chords) / total
    t[-1] = 1.0
    return t


def _centripetal_params_2d(pts: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Centripetal parameterisation for an unordered (N,3) cloud.

    Projects points onto a 2-D plane spanned by the first two PCA directions,
    then normalises each axis to [0, 1] to get (u_i, v_i) parameters.

    Returns arrays (us, vs) both of length N.
    """
    # PCA to find 2 dominant directions
    centroid = pts.mean(axis=0)
    X = pts - centroid
    # Covariance
    _, _, Vt = np.linalg.svd(X, full_matrices=False)
    d1 = Vt[0]  # first principal direction
    d2 = Vt[1]  # second principal direction
    u_coords = X @ d1
    v_coords = X @ d2
    # Normalise to [0, 1]
    u_min, u_max = u_coords.min(), u_coords.max()
    v_min, v_max = v_coords.min(), v_coords.max()
    u_span = u_max - u_min
    v_span = v_max - v_min
    if u_span < 1e-14 and v_span < 1e-14:
        return None, None
    # If one span is degenerate (collinear), we detect this upstream
    if u_span < 1e-14:
        u_span = 1.0
    if v_span < 1e-14:
        v_span = 1.0
    us = (u_coords - u_min) / u_span
    vs = (v_coords - v_min) / v_span
    return us, vs


# ---------------------------------------------------------------------------
# Knot vector by averaging method (P&T §9.2.2)
# ---------------------------------------------------------------------------

def _knot_vector_average(params: np.ndarray, n_ctrl: int, degree: int) -> np.ndarray:
    """Build a clamped knot vector using the averaging method (P&T §9.2.2).

    Parameters
    ----------
    params   : sorted parameter values in [0,1] (N,)
    n_ctrl   : number of control points
    degree   : B-spline degree

    Returns
    -------
    knot vector of length n_ctrl + degree + 1
    """
    n_knots = n_ctrl + degree + 1
    n_inner = n_ctrl - degree - 1  # number of interior (non-clamped) knots
    U = np.zeros(n_knots)
    U[-degree - 1:] = 1.0

    if n_inner > 0:
        # Interpolation / averages: average consecutive params
        # Use d = len(params) / n_ctrl spacing
        N = len(params)
        # Grevillelike: interior knot j  = mean of params[j..j+degree-1]
        for j in range(1, n_inner + 1):
            # stride so we spread evenly over the parameter range
            i_start = int(round(j * N / n_ctrl))
            i_end = min(i_start + degree, N)
            i_start = max(0, i_start)
            seg = params[i_start:i_end]
            if len(seg) == 0:
                seg = params[[min(i_start, N - 1)]]
            U[degree + j] = np.mean(seg)

    return U


# ---------------------------------------------------------------------------
# Basis-function row for a single (u, v) parameter pair
# ---------------------------------------------------------------------------

def _basis_row(u: float, v: float,
               U: np.ndarray, V: np.ndarray,
               p: int, q: int,
               n_u: int, n_v: int) -> np.ndarray:
    """Compute the (n_u * n_v,) basis-function row N(u)⊗N(v).

    The control-point ordering is row-major: index = i * n_v + j.
    """
    span_u = _find_span(n_u - 1, p, u, U)
    span_v = _find_span(n_v - 1, q, v, V)
    Nu = _basis_fns(span_u, u, p, U)  # (p+1,)
    Nv = _basis_fns(span_v, v, q, V)  # (q+1,)

    row = np.zeros(n_u * n_v)
    for di in range(p + 1):
        for dj in range(q + 1):
            ii = span_u - p + di
            jj = span_v - q + dj
            if 0 <= ii < n_u and 0 <= jj < n_v:
                row[ii * n_v + jj] = Nu[di] * Nv[dj]
    return row


# ---------------------------------------------------------------------------
# Smoothness (second-difference) regularisation matrix
# ---------------------------------------------------------------------------

def _smoothness_matrix(n_u: int, n_v: int) -> np.ndarray:
    """Return a (n_u * n_v, n_u * n_v) second-difference Laplacian matrix.

    Penalises sum of squared second differences in both U and V directions.
    """
    n = n_u * n_v
    D = np.zeros((n, n))

    def idx(i: int, j: int) -> int:
        return i * n_v + j

    for i in range(n_u):
        for j in range(n_v):
            k = idx(i, j)
            # Second difference in U
            if 2 <= i <= n_u - 1:
                D[k, idx(i - 2, j)] += 1.0
                D[k, idx(i - 1, j)] -= 2.0
                D[k, k] += 1.0
            elif i == 1:
                D[k, idx(i - 1, j)] += 1.0
                D[k, k] -= 1.0
            # Second difference in V
            if 2 <= j <= n_v - 1:
                D[k, idx(i, j - 2)] += 1.0
                D[k, idx(i, j - 1)] -= 2.0
                D[k, k] += 1.0
            elif j == 1:
                D[k, idx(i, j - 1)] += 1.0
                D[k, k] -= 1.0

    return D


# ---------------------------------------------------------------------------
# Residual evaluation
# ---------------------------------------------------------------------------

def _evaluate_surface_at(srf: NurbsSurface, us: np.ndarray, vs: np.ndarray) -> np.ndarray:
    """Evaluate the surface at each (us[i], vs[i]) pair.  Returns (N, 3)."""
    U = srf.knots_u
    V = srf.knots_v
    p = srf.degree_u
    q = srf.degree_v
    n_u = srf.num_control_points_u
    n_v = srf.num_control_points_v
    out = np.zeros((len(us), 3))
    for k in range(len(us)):
        u = float(np.clip(us[k], 0.0, 1.0))
        v = float(np.clip(vs[k], 0.0, 1.0))
        row = _basis_row(u, v, U, V, p, q, n_u, n_v)
        # Reshape control points to (n_u*n_v, 3)
        cp_flat = srf.control_points.reshape(-1, 3)
        out[k] = row @ cp_flat
    return out


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def nurbs_surface_fit(
    points: np.ndarray,
    *,
    u_degree: int = 3,
    v_degree: int = 3,
    n_u_ctrl: int = 8,
    n_v_ctrl: int = 8,
    lambda_smooth: float = 1e-3,
    seed: int = 42,
) -> Tuple["NurbsSurface", FitReport]:
    """Fit a B-spline surface to a segmented point cloud.

    Parameters
    ----------
    points : np.ndarray, shape (N, 3) or (Nu, Nv, 3)
        Input point cloud.  If 3-D with shape (Nu, Nv, 3) the points are
        treated as an ordered grid; otherwise the cloud is unordered.
    u_degree, v_degree : int
        B-spline degree in U and V directions (1 ≤ degree ≤ 7).
    n_u_ctrl, n_v_ctrl : int
        Number of control points in U and V.  Must satisfy n ≥ degree + 1.
    lambda_smooth : float
        Smoothness regularisation weight (≥ 0).  Higher values produce a
        smoother but potentially less accurate surface.  Default 1e-3.
    seed : int
        RNG seed (reserved for future stochastic extensions).

    Returns
    -------
    (NurbsSurface, FitReport)
        The fitted surface and a report containing RMS residual, max
        residual, iteration count, and condition number.

    Raises
    ------
    FitError
        If the input is degenerate (collinear/coplanar in a single point),
        too few points, or the solver fails.
    """
    # ── Validate & normalise input ─────────────────────────────────────────
    try:
        pts = np.asarray(points, dtype=float)
    except Exception as exc:
        raise FitError(f"Cannot convert points to numpy array: {exc}") from exc

    is_grid = pts.ndim == 3
    if is_grid:
        if pts.shape[2] != 3:
            raise FitError(
                f"Grid points must have shape (Nu, Nv, 3); got {pts.shape}"
            )
        grid_nu, grid_nv = pts.shape[0], pts.shape[1]
        pts_flat = pts.reshape(-1, 3)
    elif pts.ndim == 2:
        if pts.shape[1] != 3:
            raise FitError(
                f"Point array must have shape (N, 3); got {pts.shape}"
            )
        pts_flat = pts
    else:
        raise FitError(
            f"points must be a 2-D (N, 3) or 3-D (Nu, Nv, 3) array; "
            f"got ndim={pts.ndim}"
        )

    N = len(pts_flat)

    # Minimum count guard
    min_pts = (u_degree + 1) * (v_degree + 1)
    if N < min_pts:
        raise FitError(
            f"Need at least (u_degree+1)*(v_degree+1) = {min_pts} points for a "
            f"degree-({u_degree},{v_degree}) surface; got {N}. "
            f"Provide more points or reduce the degree."
        )

    # Clamp control point counts
    n_u_ctrl = max(u_degree + 1, int(n_u_ctrl))
    n_v_ctrl = max(v_degree + 1, int(n_v_ctrl))

    # Also need at least as many data points as unknowns (approx)
    n_ctrl_total = n_u_ctrl * n_v_ctrl
    if N < n_ctrl_total:
        raise FitError(
            f"Need at least n_u_ctrl * n_v_ctrl = {n_ctrl_total} points for the "
            f"requested control grid ({n_u_ctrl} x {n_v_ctrl}); got {N}."
        )

    # ── Degeneracy check ──────────────────────────────────────────────────
    centroid = pts_flat.mean(axis=0)
    X = pts_flat - centroid
    # Use SVD to check rank
    try:
        sv = np.linalg.svd(X, compute_uv=False)
    except np.linalg.LinAlgError as exc:
        raise FitError(f"SVD failed on input points: {exc}") from exc

    if sv[1] < 1e-10 * sv[0]:
        raise FitError(
            "Input points appear to be collinear (all points lie on a single "
            "line). A surface cannot be fitted to collinear data."
        )
    if sv[0] < 1e-14:
        raise FitError(
            "Input points are all identical (degenerate cloud). "
            "Provide distinct points."
        )

    # ── Parameterise ──────────────────────────────────────────────────────
    if is_grid:
        # Ordered grid: build 1-D centripetal params per row/column, then average.
        # U params: average over columns; V params: average over rows.
        us_all = []
        for row_idx in range(grid_nu):
            row_pts = pts[row_idx, :, :]
            t = _centripetal_params_1d(row_pts)
            if t is None:
                raise FitError(
                    f"Grid row {row_idx} has all-coincident points (zero chord)."
                )
            us_all.append(t)
        us_grid = np.array(us_all)  # (grid_nu, grid_nv)

        vs_all = []
        for col_idx in range(grid_nv):
            col_pts = pts[:, col_idx, :]
            t = _centripetal_params_1d(col_pts)
            if t is None:
                raise FitError(
                    f"Grid column {col_idx} has all-coincident points."
                )
            vs_all.append(t)
        vs_grid = np.array(vs_all).T  # (grid_nu, grid_nv)

        us = us_grid.ravel()
        vs = vs_grid.ravel()
        pts_flat_for_fit = pts_flat
    else:
        # Unordered cloud: centripetal PCA-based parameterisation
        us, vs = _centripetal_params_2d(pts_flat)
        if us is None:
            raise FitError(
                "Input points are collinear or all-coincident; "
                "cannot build 2-D parameterisation."
            )
        pts_flat_for_fit = pts_flat

    # ── Knot vectors ──────────────────────────────────────────────────────
    us_sorted = np.sort(us)
    vs_sorted = np.sort(vs)
    U = _knot_vector_average(us_sorted, n_u_ctrl, u_degree)
    V = _knot_vector_average(vs_sorted, n_v_ctrl, v_degree)

    # ── Build basis matrix N (N_pts, n_u_ctrl * n_v_ctrl) ─────────────────
    N_mat = np.zeros((N, n_ctrl_total))
    for k in range(N):
        u = float(np.clip(us[k], 0.0, 1.0))
        v = float(np.clip(vs[k], 0.0, 1.0))
        N_mat[k] = _basis_row(u, v, U, V, u_degree, v_degree, n_u_ctrl, n_v_ctrl)

    # ── Condition number of N^T N (before regularisation) ─────────────────
    NtN = N_mat.T @ N_mat
    try:
        sv_NtN = np.linalg.svd(NtN, compute_uv=False)
        if sv_NtN[-1] > 1e-30:
            cond = float(sv_NtN[0] / sv_NtN[-1])
        else:
            cond = float("inf")
    except np.linalg.LinAlgError:
        cond = float("inf")

    # ── Smoothness regularisation matrix ──────────────────────────────────
    D = _smoothness_matrix(n_u_ctrl, n_v_ctrl)

    # ── Augmented system: [N ; sqrt(λ) * D] P = [Q ; 0] ──────────────────
    lam = float(lambda_smooth)
    if lam < 0.0:
        raise FitError(f"lambda_smooth must be >= 0; got {lam}")
    sqrt_lam = np.sqrt(max(lam, 0.0))
    A = np.vstack([N_mat, sqrt_lam * D])                      # (N + n_ctrl, n_ctrl)
    b = np.vstack([
        pts_flat_for_fit[:, :3],
        np.zeros((n_ctrl_total, 3)),
    ])                                                          # (N + n_ctrl, 3)

    # ── Solve ─────────────────────────────────────────────────────────────
    try:
        if _SCIPY_AVAILABLE:
            # scipy lstsq: more robust conditioning than np.linalg.lstsq
            ctrl_flat, _, _, _ = _scipy_lstsq(A, b, cond=None, check_finite=True)
        else:
            ctrl_flat, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    except Exception as exc:
        raise FitError(f"Least-squares solve failed: {exc}") from exc

    ctrl_flat = ctrl_flat[:n_ctrl_total]  # guard against over-augmented shape
    ctrl_grid = ctrl_flat.reshape(n_u_ctrl, n_v_ctrl, 3)

    # ── Construct NurbsSurface ─────────────────────────────────────────────
    srf = NurbsSurface(
        degree_u=u_degree,
        degree_v=v_degree,
        control_points=ctrl_grid,
        knots_u=U,
        knots_v=V,
    )

    # ── Compute residuals ─────────────────────────────────────────────────
    fitted = _evaluate_surface_at(srf, us, vs)
    diffs = np.linalg.norm(pts_flat_for_fit[:, :3] - fitted, axis=1)
    rms = float(np.sqrt(np.mean(diffs ** 2)))
    max_res = float(np.max(diffs))

    report = FitReport(
        rms_residual=rms,
        max_residual=max_res,
        n_iterations=1,
        condition_number=cond,
    )
    return srf, report
