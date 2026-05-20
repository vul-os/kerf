"""
kerf_cad_core.reverse_engineering.noise — Scanner noise pre-filtering.

Functions
---------
statistical_outlier_removal(pts, k, n_sigma) -> (filtered_pts, outlier_indices)
    For each point compute the mean distance to its k nearest neighbours.
    Points whose mean-kNN distance exceeds  global_mean + n_sigma * global_std
    are classified as outliers and removed.

laplacian_smooth(pts, n_iter, weight) -> smoothed_pts
    Iterative Laplacian smoothing: each point moves toward the centroid of its
    k nearest neighbours.  A blending weight controls strength (0 = no move,
    1 = full replace with centroid).

Design notes
------------
- Pure Python + math.  No numpy or scipy required.
- O(n²) nearest-neighbour search — suitable for up to ~5 000 pts in tests.
  Production would want a k-d tree but that would require a 3rd-party dep.
- Deterministic (no randomness).

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sq_dist(a: list[float], b: list[float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return dx*dx + dy*dy + dz*dz


def _knn_mean_dist(pts: list[list[float]], k: int) -> list[float]:
    """Return the mean Euclidean distance to k nearest neighbours for each point.

    Uses a brute-force O(n²) search — fast enough for synthetic test clouds
    (few hundred to a few thousand points).
    """
    n = len(pts)
    k = min(k, n - 1)  # guard: k must be < n
    mean_dists: list[float] = []
    for i, p in enumerate(pts):
        # Compute squared distances to all other points
        dists = sorted(
            math.sqrt(_sq_dist(p, pts[j])) for j in range(n) if j != i
        )
        knn_dists = dists[:k]
        mean_dists.append(sum(knn_dists) / len(knn_dists) if knn_dists else 0.0)
    return mean_dists


# ---------------------------------------------------------------------------
# Public: statistical outlier removal
# ---------------------------------------------------------------------------

def statistical_outlier_removal(
    pts: list[list[float]],
    k: int = 8,
    n_sigma: float = 2.0,
) -> tuple[list[list[float]], list[int]]:
    """Remove statistical outliers from a point cloud.

    Algorithm
    ---------
    1. For each point compute the mean Euclidean distance to its *k* nearest
       neighbours.
    2. Compute the global mean (μ) and standard deviation (σ) of those
       per-point mean distances.
    3. Any point with mean-kNN distance > μ + n_sigma·σ is an outlier.

    Parameters
    ----------
    pts : list of [x, y, z]
        Input point cloud.
    k : int
        Number of nearest neighbours.  Default 8.
    n_sigma : float
        Outlier threshold in standard deviations above the mean.  Default 2.0.

    Returns
    -------
    filtered : list of [x, y, z]
        Points that are NOT outliers.
    outlier_indices : list of int
        Indices (into *pts*) of points that were removed.

    Notes
    -----
    If pts has fewer than k+1 points k is silently clamped to len(pts)-1.
    """
    n = len(pts)
    if n < 2:
        return [list(p) for p in pts], []

    mean_dists = _knn_mean_dist(pts, k)
    mu = sum(mean_dists) / n
    variance = sum((d - mu) ** 2 for d in mean_dists) / n
    sigma = math.sqrt(variance) if variance > 0.0 else 0.0
    threshold = mu + n_sigma * sigma

    filtered: list[list[float]] = []
    outlier_indices: list[int] = []
    for i, (p, d) in enumerate(zip(pts, mean_dists)):
        if d > threshold:
            outlier_indices.append(i)
        else:
            filtered.append(list(p))

    return filtered, outlier_indices


# ---------------------------------------------------------------------------
# Public: Laplacian smoothing
# ---------------------------------------------------------------------------

def laplacian_smooth(
    pts: list[list[float]],
    n_iter: int = 3,
    weight: float = 0.5,
    k: int = 8,
) -> list[list[float]]:
    """Iterative Laplacian smoothing of a point cloud.

    Each iteration replaces every point with a weighted average of itself and
    the centroid of its *k* nearest neighbours:

        p_new = (1 - w) * p + w * centroid(kNN(p))

    Parameters
    ----------
    pts : list of [x, y, z]
    n_iter : int
        Number of smoothing passes.  Default 3.
    weight : float
        Blending weight toward the neighbourhood centroid.
        0 = no smoothing, 1 = full Laplacian move.  Default 0.5.
    k : int
        Neighbourhood size.  Default 8.

    Returns
    -------
    list of [x, y, z]
        Smoothed point cloud (same length as input).
    """
    if len(pts) < 2 or n_iter < 1:
        return [list(p) for p in pts]

    current = [list(p) for p in pts]
    n = len(current)
    k_eff = min(k, n - 1)
    w = max(0.0, min(1.0, weight))

    for _ in range(n_iter):
        new_pts: list[list[float]] = []
        for i, p in enumerate(current):
            # k nearest neighbours (by index, sorted by sq-dist)
            dists = sorted(
                ((_sq_dist(p, current[j]), j) for j in range(n) if j != i),
                key=lambda x: x[0],
            )
            nbrs = [current[dists[k2][1]] for k2 in range(k_eff)]
            if not nbrs:
                new_pts.append(p[:])
                continue
            cx = sum(nb[0] for nb in nbrs) / len(nbrs)
            cy = sum(nb[1] for nb in nbrs) / len(nbrs)
            cz = sum(nb[2] for nb in nbrs) / len(nbrs)
            new_pts.append([
                (1.0 - w) * p[0] + w * cx,
                (1.0 - w) * p[1] + w * cy,
                (1.0 - w) * p[2] + w * cz,
            ])
        current = new_pts

    return current
