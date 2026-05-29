"""
nurbs_surface_fit.py
====================
NURBS freeform-surface fitting from segmented point clouds.

Implements two complementary code paths:

**Ordered-grid path** (P&T §9.4 — "Global Surface Interpolation")
  Triggered when ``points`` is shape ``(Nu, Nv, 3)``.  Parameterises each row
  and each column independently with centripetal chord-length, then fits
  row-by-row interpolating curves and skins them column-wise.  This gives
  near-exact interpolation for smooth surfaces (e.g. sinusoidal patches,
  torus patches) without needing a global LS solve.

**Unordered cloud path** (P&T §9.2 — "Global Surface Approximation")
  Triggered when ``points`` is shape ``(N, 3)``.  Uses centripetal PCA-based
  parameterisation, knot-vector averaging (§9.2.2), damped least-squares, and
  optional adaptive knot refinement to converge toward a target RMS.

Algorithm summary (unordered path)
-----------------------------------
  1. Centripetal parameterisation (robust for noisy, irregular clouds).
  2. Knot-vector placement via the averaging method (P&T §9.2.2).
  3. Damped least-squares solve:
       min ||N · P - Q||_F^2 + λ ||D · P||_F^2
     where N is the tensor-product basis matrix, D is a finite-difference
     second-derivative (smoothness) operator on the control-point grid, and
     λ (lambda_smooth) is the damping weight.
  4. Adaptive refinement: if ``target_rms`` is set and ``rms > target_rms``,
     locate the parametric region with maximum local residual, insert a knot
     via Boehm insertion in U and/or V, and re-solve.  Repeat up to
     ``max_iter`` times.

Public API
----------
nurbs_surface_fit(points, *, u_degree, v_degree, n_u_ctrl, n_v_ctrl,
                  lambda_smooth, target_rms, max_iter, seed)
    -> tuple[NurbsSurface, FitReport]

    points : (N, 3) or (Nu, Nv, 3) ndarray
        Point cloud.  If 3-D (Nu, Nv, 3) the ordered-grid path is used.

    u_degree, v_degree : int   B-spline degree in U and V (default 3).
    n_u_ctrl, n_v_ctrl : int   Number of control points (default 8).
    lambda_smooth : float      Smoothness damping weight (default 1e-3).
    target_rms : float | None  If set, adaptive refinement attempts to reduce
                               rms_residual below this value.  Default None.
    max_iter : int             Maximum adaptive refinement iterations (default 5).
    seed : int                 RNG seed (reserved).

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
from typing import Optional, Tuple

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
    n_iterations   : int     Number of solver iterations (1 for ordered-grid
                             path; 1 + adaptive refinement steps for cloud).
    condition_number : float Estimated condition number of the normal matrix
                             N^T N (before regularisation).  Large values
                             (>1e10) indicate near-singular problems; increase
                             lambda_smooth to stabilise.  Set to 0.0 for the
                             ordered-grid (interpolation) path.
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

def _centripetal_params_1d(pts: np.ndarray) -> Optional[np.ndarray]:
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


def _centripetal_params_2d(pts: np.ndarray) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
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
        N = len(params)
        for j in range(1, n_inner + 1):
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
# Boehm knot insertion (P&T Algorithm A5.1)
# ---------------------------------------------------------------------------

def _knot_insert_surface_u(srf: NurbsSurface, u_new: float) -> NurbsSurface:
    """Insert a single knot u_new into the U knot vector using Boehm's algorithm.

    Updates control points and knot vector; returns a new NurbsSurface.
    P&T Algorithm A5.1 applied to each V-isoparametric strip independently.
    """
    p = srf.degree_u
    U = srf.knots_u
    n_u = srf.num_control_points_u
    n_v = srf.num_control_points_v
    P = srf.control_points  # (n_u, n_v, 3)

    # Find knot span
    k = _find_span(n_u - 1, p, u_new, U)

    # New knot vector
    U_new = np.insert(U, k + 1, u_new)

    # New control points (n_u + 1, n_v, 3)
    P_new = np.zeros((n_u + 1, n_v, 3))
    for v_idx in range(n_v):
        pts = P[:, v_idx, :]  # (n_u, 3)
        new_pts = np.zeros((n_u + 1, 3))
        # Below the span: copy unchanged
        for i in range(k - p + 1):
            new_pts[i] = pts[i]
        # Above the span: copy unchanged
        for i in range(k, n_u):
            new_pts[i + 1] = pts[i]
        # Blend within span
        for i in range(k - p + 1, k + 1):
            denom = U[i + p] - U[i]
            if abs(denom) < 1e-15:
                alpha = 1.0
            else:
                alpha = (u_new - U[i]) / denom
            new_pts[i] = alpha * pts[i] + (1.0 - alpha) * pts[i - 1]
        P_new[:, v_idx, :] = new_pts

    return NurbsSurface(
        degree_u=srf.degree_u,
        degree_v=srf.degree_v,
        control_points=P_new,
        knots_u=U_new,
        knots_v=srf.knots_v.copy(),
    )


def _knot_insert_surface_v(srf: NurbsSurface, v_new: float) -> NurbsSurface:
    """Insert a single knot v_new into the V knot vector using Boehm's algorithm."""
    q = srf.degree_v
    V = srf.knots_v
    n_u = srf.num_control_points_u
    n_v = srf.num_control_points_v
    P = srf.control_points  # (n_u, n_v, 3)

    k = _find_span(n_v - 1, q, v_new, V)

    V_new = np.insert(V, k + 1, v_new)

    P_new = np.zeros((n_u, n_v + 1, 3))
    for u_idx in range(n_u):
        pts = P[u_idx, :, :]  # (n_v, 3)
        new_pts = np.zeros((n_v + 1, 3))
        for j in range(k - q + 1):
            new_pts[j] = pts[j]
        for j in range(k, n_v):
            new_pts[j + 1] = pts[j]
        for j in range(k - q + 1, k + 1):
            denom = V[j + q] - V[j]
            if abs(denom) < 1e-15:
                alpha = 1.0
            else:
                alpha = (v_new - V[j]) / denom
            new_pts[j] = alpha * pts[j] + (1.0 - alpha) * pts[j - 1]
        P_new[u_idx, :, :] = new_pts

    return NurbsSurface(
        degree_u=srf.degree_u,
        degree_v=srf.degree_v,
        control_points=P_new,
        knots_u=srf.knots_u.copy(),
        knots_v=V_new,
    )


# ---------------------------------------------------------------------------
# Ordered-grid path: P&T §9.4 — row-by-row interpolation + skinning
# ---------------------------------------------------------------------------

def _fit_curve_interpolate(pts_1d: np.ndarray, degree: int, params: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Interpolate a 1-D sequence of 3-D points with a B-spline curve.

    Uses the parameter values ``params`` (already computed centripetal), builds
    a Greville / averaging knot vector, then solves the interpolation system
    N * P = Q exactly via numpy.

    Returns (control_points, knot_vector).
    """
    n_pts = len(pts_1d)
    n_ctrl = n_pts  # interpolation: n_ctrl == n_pts

    # Build knot vector by averaging (P&T §9.2.2)
    knots = _knot_vector_average(params, n_ctrl, degree)

    # Build collocation matrix N  (n_pts, n_ctrl)
    N_mat = np.zeros((n_pts, n_ctrl))
    for k in range(n_pts):
        u = float(np.clip(params[k], 0.0, 1.0))
        span = _find_span(n_ctrl - 1, degree, u, knots)
        basis = _basis_fns(span, u, degree, knots)
        for di in range(degree + 1):
            ii = span - degree + di
            if 0 <= ii < n_ctrl:
                N_mat[k, ii] = basis[di]

    # Solve N * P = Q
    try:
        ctrl_pts, _, _, _ = np.linalg.lstsq(N_mat, pts_1d, rcond=None)
    except np.linalg.LinAlgError as exc:
        raise FitError(f"Curve interpolation solve failed: {exc}") from exc

    return ctrl_pts, knots


def _fit_ordered_grid(
    pts: np.ndarray,
    u_degree: int,
    v_degree: int,
    n_u_ctrl: int,
    n_v_ctrl: int,
) -> Tuple[NurbsSurface, FitReport]:
    """P&T §9.4 ordered-grid surface fitting.

    Algorithm:
    1. Parameterise each row (along V) with centripetal rule.
    2. Average row parameters over all rows → single V-parameter set.
    3. For each row, interpolate a B-spline curve → row control points.
    4. Average column parameters over all rows → single U-parameter set.
    5. For each column of the row-curve control points, interpolate a B-spline
       curve along U → final surface control points.

    This separates the 2-D fit into two passes of 1-D curve interpolation,
    giving near-exact fit for smooth surfaces.
    """
    Nu, Nv = pts.shape[0], pts.shape[1]

    # ── Step 1: centripetal V-parameters for each row ─────────────────────
    v_params_per_row = []
    for i in range(Nu):
        t = _centripetal_params_1d(pts[i, :, :])
        if t is None:
            raise FitError(f"Grid row {i} has all-coincident points.")
        v_params_per_row.append(t)

    # ── Step 2: average V-parameters ──────────────────────────────────────
    v_params = np.mean(np.array(v_params_per_row), axis=0)  # (Nv,)
    v_params[0] = 0.0
    v_params[-1] = 1.0

    # ── Step 3: fit each row → row curve control points ───────────────────
    # Each row gives n_v_ctrl_row control points; we use Nv (interpolating)
    # control points per row for maximal accuracy.
    row_ctrl_count = Nv  # interpolation: same count as points
    row_knots = None  # all rows share the same V params so same knots
    row_ctrl_pts = np.zeros((Nu, row_ctrl_count, 3))

    for i in range(Nu):
        ctrl, knots_v = _fit_curve_interpolate(pts[i, :, :], v_degree, v_params)
        row_ctrl_pts[i] = ctrl
        if row_knots is None:
            row_knots = knots_v

    # ── Step 4: centripetal U-parameters for each column (of ctrl pts) ────
    u_params_per_col = []
    for j in range(row_ctrl_count):
        t = _centripetal_params_1d(row_ctrl_pts[:, j, :])
        if t is None:
            # Degenerate column: use uniform spacing
            t = np.linspace(0.0, 1.0, Nu)
        u_params_per_col.append(t)
    u_params = np.mean(np.array(u_params_per_col), axis=0)  # (Nu,)
    u_params[0] = 0.0
    u_params[-1] = 1.0

    # ── Step 5: fit each column of row ctrl pts → surface control points ──
    col_ctrl_count = Nu  # interpolating along U
    col_knots = None
    surf_ctrl = np.zeros((col_ctrl_count, row_ctrl_count, 3))

    for j in range(row_ctrl_count):
        col_pts = row_ctrl_pts[:, j, :]  # (Nu, 3)
        ctrl, knots_u = _fit_curve_interpolate(col_pts, u_degree, u_params)
        surf_ctrl[:, j, :] = ctrl
        if col_knots is None:
            col_knots = knots_u

    # ── Build surface ──────────────────────────────────────────────────────
    srf = NurbsSurface(
        degree_u=u_degree,
        degree_v=v_degree,
        control_points=surf_ctrl,
        knots_u=col_knots,
        knots_v=row_knots,
    )

    # ── Residuals: evaluate at grid (u_i, v_j) params ────────────────────
    # Build flat param lists
    us_flat = np.repeat(u_params, Nv)   # (Nu*Nv,)
    vs_flat = np.tile(v_params, Nu)     # (Nu*Nv,)
    pts_flat = pts.reshape(-1, 3)
    fitted = _evaluate_surface_at(srf, us_flat, vs_flat)
    diffs = np.linalg.norm(pts_flat - fitted, axis=1)
    rms = float(np.sqrt(np.mean(diffs ** 2)))
    max_res = float(np.max(diffs))

    report = FitReport(
        rms_residual=rms,
        max_residual=max_res,
        n_iterations=1,
        condition_number=0.0,  # interpolation path: no condition number
    )
    return srf, report


# ---------------------------------------------------------------------------
# Unordered-cloud LS solve (shared by initial fit + adaptive refinement)
# ---------------------------------------------------------------------------

def _ls_solve(
    pts_flat: np.ndarray,
    us: np.ndarray,
    vs: np.ndarray,
    U: np.ndarray,
    V: np.ndarray,
    u_degree: int,
    v_degree: int,
    n_u_ctrl: int,
    n_v_ctrl: int,
    lambda_smooth: float,
) -> Tuple[NurbsSurface, float, float, float]:
    """Solve the damped LS system and return (surface, rms, max_res, cond).

    Internal helper used by both the initial fit and adaptive iterations.
    """
    N = len(pts_flat)
    n_ctrl_total = n_u_ctrl * n_v_ctrl

    # Build basis matrix
    N_mat = np.zeros((N, n_ctrl_total))
    for k in range(N):
        u = float(np.clip(us[k], 0.0, 1.0))
        v = float(np.clip(vs[k], 0.0, 1.0))
        N_mat[k] = _basis_row(u, v, U, V, u_degree, v_degree, n_u_ctrl, n_v_ctrl)

    # Condition number of N^T N (before regularisation)
    NtN = N_mat.T @ N_mat
    try:
        sv_NtN = np.linalg.svd(NtN, compute_uv=False)
        cond = float(sv_NtN[0] / sv_NtN[-1]) if sv_NtN[-1] > 1e-30 else float("inf")
    except np.linalg.LinAlgError:
        cond = float("inf")

    # Smoothness regularisation
    D = _smoothness_matrix(n_u_ctrl, n_v_ctrl)
    sqrt_lam = np.sqrt(max(lambda_smooth, 0.0))
    A = np.vstack([N_mat, sqrt_lam * D])
    b = np.vstack([pts_flat[:, :3], np.zeros((n_ctrl_total, 3))])

    try:
        if _SCIPY_AVAILABLE:
            ctrl_flat, _, _, _ = _scipy_lstsq(A, b, cond=None, check_finite=True)
        else:
            ctrl_flat, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
    except Exception as exc:
        raise FitError(f"Least-squares solve failed: {exc}") from exc

    ctrl_flat = ctrl_flat[:n_ctrl_total]
    ctrl_grid = ctrl_flat.reshape(n_u_ctrl, n_v_ctrl, 3)

    srf = NurbsSurface(
        degree_u=u_degree,
        degree_v=v_degree,
        control_points=ctrl_grid,
        knots_u=U.copy(),
        knots_v=V.copy(),
    )

    fitted = _evaluate_surface_at(srf, us, vs)
    diffs = np.linalg.norm(pts_flat[:, :3] - fitted, axis=1)
    rms = float(np.sqrt(np.mean(diffs ** 2)))
    max_res = float(np.max(diffs))

    return srf, rms, max_res, cond


# ---------------------------------------------------------------------------
# Adaptive knot refinement for unordered clouds
# ---------------------------------------------------------------------------

def _adaptive_refine(
    srf: NurbsSurface,
    pts_flat: np.ndarray,
    us: np.ndarray,
    vs: np.ndarray,
    u_degree: int,
    v_degree: int,
    lambda_smooth: float,
    target_rms: float,
    max_iter: int,
    current_rms: float,
    current_max: float,
    current_cond: float,
) -> Tuple[NurbsSurface, float, float, int, float]:
    """Iterative adaptive knot refinement.

    Finds the parametric region with maximum local residual, inserts a knot
    at the centroid of that region in U and/or V (Boehm), then re-solves.
    Stops when rms <= target_rms or max_iter exhausted.

    Returns (surface, rms, max_res, n_iterations_done, cond).
    """
    best_srf = srf
    best_rms = current_rms
    best_max = current_max
    best_cond = current_cond
    n_iters = 0

    U = srf.knots_u.copy()
    V = srf.knots_v.copy()
    n_u_ctrl = srf.num_control_points_u
    n_v_ctrl = srf.num_control_points_v

    for _ in range(max_iter):
        if best_rms <= target_rms:
            break

        # Evaluate residuals at each point
        fitted = _evaluate_surface_at(best_srf, us, vs)
        diffs = np.linalg.norm(pts_flat[:, :3] - fitted, axis=1)

        # Find parametric location of worst residual
        worst_idx = int(np.argmax(diffs))
        u_worst = float(np.clip(us[worst_idx], 0.0, 1.0))
        v_worst = float(np.clip(vs[worst_idx], 0.0, 1.0))

        # Measure local residual anisotropy: compare variance in U vs V bands
        # Points within a band around u_worst vs v_worst
        u_band = np.abs(us - u_worst) < 0.15
        v_band = np.abs(vs - v_worst) < 0.15
        u_rms = float(np.sqrt(np.mean(diffs[u_band] ** 2))) if np.any(u_band) else 0.0
        v_rms = float(np.sqrt(np.mean(diffs[v_band] ** 2))) if np.any(v_band) else 0.0

        # Insert knot in the direction with higher residual (or both if similar)
        new_srf = best_srf
        inserted = False

        U_cur = new_srf.knots_u
        V_cur = new_srf.knots_v
        u_deg = new_srf.degree_u
        v_deg = new_srf.degree_v

        # Only insert if u_worst is not already a knot (avoid multiplicity > degree)
        def _knot_already_present(knots: np.ndarray, val: float, tol: float = 1e-6) -> bool:
            return bool(np.any(np.abs(knots - val) < tol))

        if u_rms >= v_rms * 0.8 and not _knot_already_present(U_cur, u_worst):
            new_srf = _knot_insert_surface_u(new_srf, u_worst)
            inserted = True

        if v_rms >= u_rms * 0.8 and not _knot_already_present(V_cur, v_worst):
            new_srf = _knot_insert_surface_v(new_srf, v_worst)
            inserted = True

        if not inserted:
            # Knots already present at worst location — try midpoint of largest gap
            U_inner = U_cur[u_deg + 1:-u_deg - 1]
            if len(U_inner) > 0:
                gaps = np.diff(U_inner)
                if len(gaps) > 0 and gaps.max() > 1e-6:
                    worst_gap = int(np.argmax(gaps))
                    u_mid = float((U_inner[worst_gap] + U_inner[worst_gap + 1]) / 2)
                    new_srf = _knot_insert_surface_u(new_srf, u_mid)
                    inserted = True

        if not inserted:
            break  # No more useful insertions

        # Re-solve with refined knot vectors
        U_new = new_srf.knots_u
        V_new = new_srf.knots_v
        n_u_new = new_srf.num_control_points_u
        n_v_new = new_srf.num_control_points_v

        # Need at least as many data points as unknowns
        if len(pts_flat) < n_u_new * n_v_new:
            break  # Refinement would over-fit; stop

        try:
            refined_srf, rms_new, max_new, cond_new = _ls_solve(
                pts_flat, us, vs,
                U_new, V_new,
                u_deg, v_deg,
                n_u_new, n_v_new,
                lambda_smooth,
            )
        except FitError:
            break  # Solve failed; keep previous result

        n_iters += 1

        if rms_new < best_rms:
            best_srf = refined_srf
            best_rms = rms_new
            best_max = max_new
            best_cond = cond_new
        else:
            # Refinement didn't help; restore and stop
            break

    return best_srf, best_rms, best_max, n_iters, best_cond


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
    target_rms: Optional[float] = None,
    max_iter: int = 5,
    seed: int = 42,
) -> Tuple["NurbsSurface", FitReport]:
    """Fit a B-spline surface to a point cloud or ordered grid.

    Parameters
    ----------
    points : np.ndarray, shape (N, 3) or (Nu, Nv, 3)
        Input point cloud or ordered grid.

        * **(Nu, Nv, 3)** — ordered grid: the fast P&T §9.4 row-by-row
          interpolation path is used.  ``n_u_ctrl`` and ``n_v_ctrl`` are
          ignored (the interpolation uses one control point per input point);
          ``lambda_smooth``, ``target_rms``, ``max_iter`` are ignored.

        * **(N, 3)** — unordered cloud: centripetal PCA parameterisation +
          damped LS + optional adaptive knot refinement.

    u_degree, v_degree : int
        B-spline degree in U and V directions (1 ≤ degree ≤ 7).
    n_u_ctrl, n_v_ctrl : int
        Number of control points (unordered path only).
        Must satisfy n ≥ degree + 1.
    lambda_smooth : float
        Smoothness regularisation weight (≥ 0, unordered path only).
    target_rms : float | None
        If set, adaptive knot refinement will attempt to reduce
        ``rms_residual`` below this value (unordered path only).
    max_iter : int
        Maximum number of adaptive refinement iterations (default 5).
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

    # ── Degeneracy check ──────────────────────────────────────────────────
    centroid = pts_flat.mean(axis=0)
    X = pts_flat - centroid
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

    # ── Ordered-grid path (P&T §9.4) ──────────────────────────────────────
    if is_grid:
        # Validate grid dimensions
        if grid_nu < u_degree + 1:
            raise FitError(
                f"Grid has {grid_nu} rows but needs at least u_degree+1 = "
                f"{u_degree + 1} rows for a degree-{u_degree} surface."
            )
        if grid_nv < v_degree + 1:
            raise FitError(
                f"Grid has {grid_nv} columns but needs at least v_degree+1 = "
                f"{v_degree + 1} columns for a degree-{v_degree} surface."
            )
        return _fit_ordered_grid(pts, u_degree, v_degree, n_u_ctrl, n_v_ctrl)

    # ── Unordered cloud path ───────────────────────────────────────────────
    # Clamp control point counts
    n_u_ctrl = max(u_degree + 1, int(n_u_ctrl))
    n_v_ctrl = max(v_degree + 1, int(n_v_ctrl))

    # Need at least as many data points as unknowns (approx)
    n_ctrl_total = n_u_ctrl * n_v_ctrl
    if N < n_ctrl_total:
        raise FitError(
            f"Need at least n_u_ctrl * n_v_ctrl = {n_ctrl_total} points for the "
            f"requested control grid ({n_u_ctrl} x {n_v_ctrl}); got {N}."
        )

    if lambda_smooth < 0.0:
        raise FitError(f"lambda_smooth must be >= 0; got {lambda_smooth}")

    # Parameterise
    us, vs = _centripetal_params_2d(pts_flat)
    if us is None:
        raise FitError(
            "Input points are collinear or all-coincident; "
            "cannot build 2-D parameterisation."
        )

    # Knot vectors
    us_sorted = np.sort(us)
    vs_sorted = np.sort(vs)
    U = _knot_vector_average(us_sorted, n_u_ctrl, u_degree)
    V = _knot_vector_average(vs_sorted, n_v_ctrl, v_degree)

    # Initial LS solve
    srf, rms, max_res, cond = _ls_solve(
        pts_flat, us, vs, U, V,
        u_degree, v_degree, n_u_ctrl, n_v_ctrl, lambda_smooth,
    )

    n_iterations = 1

    # Adaptive refinement
    if target_rms is not None and rms > target_rms and max_iter > 0:
        srf, rms, max_res, extra_iters, cond = _adaptive_refine(
            srf, pts_flat, us, vs,
            u_degree, v_degree, lambda_smooth,
            float(target_rms), int(max_iter),
            rms, max_res, cond,
        )
        n_iterations += extra_iters

    report = FitReport(
        rms_residual=rms,
        max_residual=max_res,
        n_iterations=n_iterations,
        condition_number=cond,
    )
    return srf, report
