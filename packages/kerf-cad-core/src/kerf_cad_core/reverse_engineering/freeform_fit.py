"""
freeform_fit.py — Freeform NURBS surface fit from segmented point clouds.
=========================================================================

Integrates the existing ``kerf_cad_core.geom.nurbs_surface_fit`` routines into
the reverse-engineering pipeline, consuming the "freeform" clusters that remain
after planes / spheres / cylinders / cones / tori have been extracted by the
RANSAC segmentation step.

Algorithm overview
------------------
For each freeform cluster:

1. **Grid-detection heuristic**: project the cluster onto its PCA plane and
   check whether the projected parameters form a near-regular grid (variance of
   inter-point spacings < 20% of mean spacing in both U and V after sorting).
   If so, reshape to (Nu, Nv, 3) and run the ordered-grid interpolation path
   (P&T §9.4 — "Global Surface Interpolation").

2. **Unordered-cloud path**: centripetal PCA parameterisation + knot-vector
   averaging (P&T §9.2.2) + damped least-squares + adaptive Boehm knot
   insertion (P&T §9.2 / Hoschek-Lasser §8) to converge below target_rms.

3. **Hausdorff validation** (P&T §9.2 / ICP convention from Wave 8B oracle):
   ``max_hausdorff_mm = max_{p in cluster} min_{q in dense grid} ||p - q||``
   where the dense grid is sampled on a 50×50 evaluation lattice over the
   fitted surface.  ``converged`` is True when both:
     - rms_error_mm ≤ target_rms_mm
     - max_hausdorff_mm ≤ 2 × target_rms_mm

References
----------
- Piegl & Tiller, "The NURBS Book", 2nd ed. (P&T)
  §9.2 — Global Surface Approximation (unordered cloud)
  §9.4 — Global Surface Interpolation (ordered grid)
- Hoschek & Lasser, "Fundamentals of Computer Aided Geometric Design"
  §8 — Approximation of point sets by surfaces
- Boehm, W. (1980) "Inserting new knots into B-spline curves"
  Computer-Aided Design 12(4), pp. 199–201.

Public API
----------
fit_freeform_to_cluster(req: FreeformFitRequest) -> FreeformFitResult
fit_freeform_from_segmentation(point_cloud, segmentation_labels,
                               target_rms_mm) -> list[FreeformFitResult]

Author: imranparuk
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface
from kerf_cad_core.geom.nurbs_surface_fit import FitError, nurbs_surface_fit

# ------------------------------------------------------------------
# Public data types
# ------------------------------------------------------------------

_GRID_CV_THRESHOLD = 0.20  # coefficient of variation below which spacings are
                             # considered "regular" enough for the ordered path


@dataclass
class FreeformFitRequest:
    """Parameters for fitting a single freeform cluster.

    Attributes
    ----------
    cluster_points : np.ndarray, shape (N, 3)
        Points labelled as "freeform" by the segmentation step (i.e. the
        residual that no primitive model accepted as inliers).
    target_rms_mm : float
        Convergence target in millimetres.  The fitter will attempt adaptive
        knot insertion until rms_error_mm ≤ target_rms_mm or
        max_knot_insertions is exhausted.  Default 0.05 mm.
    initial_grid : tuple[int, int]
        (n_u_ctrl, n_v_ctrl) initial control-point grid for the unordered
        path.  Ignored on the ordered-grid path.  Default (8, 8).
    max_knot_insertions : int
        Maximum number of adaptive Boehm knot-insertion iterations.
        Default 5.
    underdetermined_flag : bool
        Set internally when the cluster has too few points for the requested
        initial_grid; the fitter falls back to a minimal-degree surface.
        Callers should not set this.
    """

    cluster_points: np.ndarray
    target_rms_mm: float = 0.05
    initial_grid: tuple = (8, 8)
    max_knot_insertions: int = 5
    underdetermined_flag: bool = field(default=False, repr=False)


@dataclass
class FreeformFitResult:
    """Diagnostics and output surface for a single freeform cluster.

    Attributes
    ----------
    nurbs_surface : NurbsSurface
        The fitted B-spline surface (non-rational).
    rms_error_mm : float
        RMS point-to-surface distance over all cluster points.
    max_hausdorff_mm : float
        One-sided Hausdorff distance: max over cluster points of the
        nearest distance to the fitted surface (sampled on a 50×50 grid).
    n_control_points : int
        Total control-point count = n_u × n_v.
    converged : bool
        True when rms_error_mm ≤ target_rms_mm AND
        max_hausdorff_mm ≤ 2 × target_rms_mm.
        Also False when the cluster was underdetermined (< 16 points) —
        the fit still proceeds at a reduced resolution but this flag signals
        the caller to treat the result as approximate.
    iterations : int
        Solver iterations (1 for the ordered-grid path; 1 + adaptive
        refinement steps for the unordered path).
    """

    nurbs_surface: NurbsSurface
    rms_error_mm: float
    max_hausdorff_mm: float
    n_control_points: int
    converged: bool
    iterations: int


# ------------------------------------------------------------------
# Grid-detection heuristic  (P&T §9.4 ordered-grid trigger)
# ------------------------------------------------------------------

def _detect_grid(pts: np.ndarray) -> Optional[tuple[int, int]]:
    """Try to detect whether pts lie on an approximately regular grid.

    Projects onto the PCA plane, bins the projected coordinates in U and V,
    and checks whether the inter-bin spacings are sufficiently uniform
    (coefficient of variation < _GRID_CV_THRESHOLD).

    Returns
    -------
    (Nu, Nv) if the cloud looks like a (Nu × Nv) grid, else None.

    P&T §9.4 ordered-grid path is used when this returns a valid shape.
    """
    N = len(pts)
    if N < 9:
        return None

    # PCA to find 2 dominant directions (same as nurbs_surface_fit._centripetal_params_2d)
    centroid = pts.mean(axis=0)
    X = pts - centroid
    _, sv, Vt = np.linalg.svd(X, full_matrices=False)

    # If the third singular value is large relative to the first two,
    # the cloud is truly 3-D and we cannot sensibly reshape it to a grid.
    if sv[0] < 1e-12:
        return None
    if sv[2] > 0.1 * sv[0]:
        # Not planar enough to guess a grid
        return None

    d1, d2 = Vt[0], Vt[1]
    u_coords = X @ d1
    v_coords = X @ d2

    # Try all factorisations of N into (Nu, Nv) with Nu, Nv >= 3
    candidates: list[tuple[float, int, int]] = []
    for nu in range(3, N // 3 + 1):
        if N % nu != 0:
            continue
        nv = N // nu
        if nv < 3:
            continue

        # Sort by u, then by v within each u-row
        order = np.argsort(u_coords)
        u_sorted = u_coords[order]
        v_sorted = v_coords[order]

        # u-spacings between row-group centroids
        u_rows = u_sorted.reshape(nu, nv).mean(axis=1)
        u_gaps = np.diff(u_rows)
        # v-spacings within one row
        v_cols = v_sorted.reshape(nu, nv)[0]
        v_order = np.argsort(v_cols)
        v_sorted_row = v_cols[v_order]
        v_gaps = np.diff(v_sorted_row)

        if len(u_gaps) == 0 or len(v_gaps) == 0:
            continue
        u_mean = np.abs(u_gaps).mean()
        v_mean = np.abs(v_gaps).mean()
        if u_mean < 1e-12 or v_mean < 1e-12:
            continue

        u_cv = np.std(np.abs(u_gaps)) / u_mean
        v_cv = np.std(np.abs(v_gaps)) / v_mean

        score = u_cv + v_cv
        if u_cv < _GRID_CV_THRESHOLD and v_cv < _GRID_CV_THRESHOLD:
            candidates.append((score, nu, nv))

    if not candidates:
        return None

    candidates.sort()
    _, best_nu, best_nv = candidates[0]
    return (best_nu, best_nv)


def _reshape_to_grid(pts: np.ndarray, nu: int, nv: int) -> np.ndarray:
    """Reshape a flat (N, 3) cloud to (nu, nv, 3) ordered grid.

    Projects onto PCA plane, sorts by u then v, and fills the grid.
    (P&T §9.4 input form)
    """
    centroid = pts.mean(axis=0)
    X = pts - centroid
    _, _, Vt = np.linalg.svd(X, full_matrices=False)
    d1, d2 = Vt[0], Vt[1]
    u_coords = X @ d1
    v_coords = X @ d2

    # Sort by u-coordinate, then by v within each row
    u_order = np.argsort(u_coords)
    pts_u = pts[u_order]
    v_coords_u = v_coords[u_order]

    grid = np.zeros((nu, nv, 3))
    for i in range(nu):
        row_pts = pts_u[i * nv: (i + 1) * nv]
        row_v = v_coords_u[i * nv: (i + 1) * nv]
        v_order = np.argsort(row_v)
        grid[i] = row_pts[v_order]

    return grid


# ------------------------------------------------------------------
# Hausdorff oracle  (ICP / Wave 8B convention)
# ------------------------------------------------------------------

def _hausdorff_one_sided(
    query_pts: np.ndarray,
    srf: NurbsSurface,
    n_grid: int = 50,
) -> float:
    """One-sided Hausdorff: max over query_pts of nearest distance to srf.

    Samples srf on an (n_grid × n_grid) uniform UV lattice to approximate
    the continuous surface, then for each query point finds the nearest
    sample point.

    This matches the Wave 8B oracle convention:
        H(query → surface) = max_p min_q ||p - q||

    P&T §9.2 residual evaluation; ICP analogy.
    """
    # Build a dense sample grid on the surface
    us = np.linspace(0.0, 1.0, n_grid)
    vs = np.linspace(0.0, 1.0, n_grid)
    # Build flat param arrays
    uu, vv = np.meshgrid(us, vs, indexing="ij")
    us_flat = uu.ravel()
    vs_flat = vv.ravel()

    # Evaluate surface at all sample points using the surface's internal evaluator
    from kerf_cad_core.geom.nurbs_surface_fit import _evaluate_surface_at
    surface_samples = _evaluate_surface_at(srf, us_flat, vs_flat)  # (n_grid², 3)

    # For each query point, find the nearest surface sample
    # Use a simple vectorised distance to avoid scipy dependency
    # (n_query × n_samples)
    max_dist = 0.0
    for p in query_pts:
        diffs = surface_samples - p[np.newaxis, :]           # (M, 3)
        dists = np.sqrt(np.sum(diffs * diffs, axis=1))       # (M,)
        max_dist = max(max_dist, float(dists.min()))

    return max_dist


# ------------------------------------------------------------------
# Core fitter
# ------------------------------------------------------------------

def fit_freeform_to_cluster(req: FreeformFitRequest) -> FreeformFitResult:
    """Fit a NURBS surface to a single freeform cluster.

    Wraps the existing nurbs_surface_fit ordered/unordered routines:
      1. If cluster lies on an approximate grid → use ordered-grid fit
         (P&T §9.4 "Global Surface Interpolation").
      2. Else → unordered cloud with adaptive knot insertion
         (P&T §9.2 + Boehm 1980).
      3. Validate Hausdorff < 2 × target_rms; return result with
         converged flag.

    Parameters
    ----------
    req : FreeformFitRequest
        Fit parameters including the point cloud, target RMS, and grid hint.

    Returns
    -------
    FreeformFitResult

    Raises
    ------
    ValueError
        If cluster_points is empty (N == 0).
    """
    pts = np.asarray(req.cluster_points, dtype=float)

    # ── Empty cluster guard ───────────────────────────────────────────────────
    if pts.ndim == 1 or pts.shape[0] == 0:
        raise ValueError("cluster_points is empty — cannot fit a NURBS surface.")
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(
            f"cluster_points must have shape (N, 3); got {pts.shape}"
        )

    N = pts.shape[0]

    if N == 0:
        raise ValueError("cluster_points is empty — cannot fit a NURBS surface.")

    target_rms = float(req.target_rms_mm)
    n_u_ctrl, n_v_ctrl = int(req.initial_grid[0]), int(req.initial_grid[1])
    max_iter = int(req.max_knot_insertions)

    # ── Underdetermined check  (< 16 points OR fewer pts than grid) ──────────
    # P&T §9.2: need at least (degree+1)² control points; for cubic that is 16.
    # For small clusters we fall back to degree-2, 4×4 = 16 CP minimum.
    # Also treat as underdetermined if N < initial_grid product (auto-shrink).
    underdetermined = (N < 16) or req.underdetermined_flag or (N < n_u_ctrl * n_v_ctrl)
    if underdetermined:
        # Fit the best we can: reduce degree and grid to match available data
        u_degree = min(2, N - 1)
        v_degree = min(2, N - 1)
        # Minimal valid grid: (degree+1) × (degree+1) but also ≤ sqrt(N)
        side = max(u_degree + 1, min(4, int(N ** 0.5)))
        # Ensure enough data points for the grid
        while side * side > N and side > u_degree + 1:
            side -= 1
        n_u_ctrl = side
        n_v_ctrl = side
        n_u_ctrl = max(u_degree + 1, n_u_ctrl)
        n_v_ctrl = max(v_degree + 1, n_v_ctrl)
    else:
        u_degree = 3
        v_degree = 3

    # ── Try ordered-grid path first  (P&T §9.4) ──────────────────────────────
    use_grid = False
    grid_pts = None

    if not underdetermined:
        grid_shape = _detect_grid(pts)
        if grid_shape is not None:
            nu, nv = grid_shape
            if nu >= u_degree + 1 and nv >= v_degree + 1:
                try:
                    grid_pts = _reshape_to_grid(pts, nu, nv)
                    use_grid = True
                except Exception:
                    use_grid = False

    # ── Fit ──────────────────────────────────────────────────────────────────
    try:
        if use_grid and grid_pts is not None:
            # P&T §9.4 ordered-grid interpolation
            srf, report = nurbs_surface_fit(
                grid_pts,
                u_degree=u_degree,
                v_degree=v_degree,
            )
        else:
            # P&T §9.2 unordered-cloud + adaptive refinement (Boehm 1980)
            srf, report = nurbs_surface_fit(
                pts,
                u_degree=u_degree,
                v_degree=v_degree,
                n_u_ctrl=n_u_ctrl,
                n_v_ctrl=n_v_ctrl,
                lambda_smooth=1e-3,
                target_rms=target_rms,
                max_iter=max_iter,
            )
    except FitError as exc:
        raise ValueError(f"NURBS freeform fit failed: {exc}") from exc

    # ── Hausdorff validation (ICP / Wave 8B convention) ──────────────────────
    hausdorff = _hausdorff_one_sided(pts, srf)

    rms = report.rms_residual
    converged = (
        rms <= target_rms
        and hausdorff <= 2.0 * target_rms
        and not underdetermined
    )

    return FreeformFitResult(
        nurbs_surface=srf,
        rms_error_mm=rms,
        max_hausdorff_mm=hausdorff,
        n_control_points=srf.num_control_points_u * srf.num_control_points_v,
        converged=converged,
        iterations=report.n_iterations,
    )


# ------------------------------------------------------------------
# Pipeline integrator
# ------------------------------------------------------------------

def fit_freeform_from_segmentation(
    point_cloud: np.ndarray,
    segmentation_labels: np.ndarray,
    target_rms_mm: float = 0.05,
) -> list[FreeformFitResult]:
    """Fit NURBS surfaces to all freeform clusters in a segmented point cloud.

    Selects all clusters labelled ``'freeform'`` (residual after primitive
    fits) and runs :func:`fit_freeform_to_cluster` on each.

    Parameters
    ----------
    point_cloud : np.ndarray, shape (N, 3)
        Full point cloud.
    segmentation_labels : array-like of str or int, length N
        Per-point labels.  Any label that is the string ``'freeform'`` (or
        integer ``-1`` by RANSAC convention) identifies freeform residual
        points.
    target_rms_mm : float
        Convergence target, passed to each :class:`FreeformFitRequest`.

    Returns
    -------
    list[FreeformFitResult]
        One result per freeform cluster.  Empty if no freeform labels exist.
    """
    pts = np.asarray(point_cloud, dtype=float)
    labels = np.asarray(segmentation_labels)

    if len(pts) != len(labels):
        raise ValueError(
            f"point_cloud length ({len(pts)}) != "
            f"segmentation_labels length ({len(labels)})"
        )

    # Identify freeform indices
    if labels.dtype.kind in ("U", "S", "O"):
        # String labels — match 'freeform'
        mask = labels == "freeform"
    else:
        # Integer labels — RANSAC convention: -1 = unassigned / freeform
        mask = labels == -1

    freeform_pts = pts[mask]

    if len(freeform_pts) == 0:
        return []

    # Fit one surface to the entire freeform residual
    # (a more sophisticated pipeline would cluster by spatial proximity first)
    req = FreeformFitRequest(
        cluster_points=freeform_pts,
        target_rms_mm=target_rms_mm,
    )
    result = fit_freeform_to_cluster(req)
    return [result]
