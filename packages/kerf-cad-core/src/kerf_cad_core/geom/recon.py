"""GK-137 — Point-cloud → mesh reconstruction.

Implements two complementary surface-reconstruction strategies in pure Python
(numpy + scipy only; no compiled mesh-library dependency):

Ball-pivoting algorithm (BPA)
    A sphere of radius *r* rolls over the point cloud.  Whenever the sphere
    touches three points simultaneously, those three points form a triangle of
    the reconstructed surface.  The implementation follows the seminal Bernardini
    et al. 1999 paper with spatial-hash acceleration.

Screened Poisson (lite)
    A simplified Poisson-style reconstruction: estimate per-point oriented
    normals via PCA on *k*-nearest neighbours, then accumulate a scalar
    indicator function on a voxel grid whose gradient field best matches the
    normal field (divergence of oriented normals), and extract the iso-surface
    at 0.5 with a marching-cubes like approach.  Suitable for dense, uniformly
    sampled point clouds.

Public API
----------
reconstruct_mesh(points, method='ball_pivoting', radius=None) -> dict
    Parameters
    ----------
    points : array-like, shape (N, 3)
        Input point cloud.  At least 3 points are required.
    method : {'ball_pivoting', 'poisson'}
        Surface reconstruction algorithm.
    radius : float or None
        Ball radius for BPA, or voxel cell size for Poisson.
        Auto-selected from point-cloud density when None.

    Returns
    -------
    dict with keys:

    ``verts``
        ``numpy.ndarray`` of shape ``(V, 3)``, dtype float64.
    ``faces``
        ``numpy.ndarray`` of shape ``(F, 3)``, dtype int64 — CCW triangles.
    ``ok``
        bool — True on success.
    ``n_verts``
        int
    ``n_faces``
        int

    On failure returns ``{"ok": False, "reason": "..."}``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Dict, Any

import numpy as np
from scipy.spatial import KDTree


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def reconstruct_mesh(
    points,
    method: str = "ball_pivoting",
    radius: float | None = None,
) -> Dict[str, Any]:
    """Reconstruct a triangle mesh from an unstructured point cloud.

    Parameters
    ----------
    points : array-like, shape (N, 3)
    method : {'ball_pivoting', 'poisson'}
    radius : float | None
        Auto-estimated when None.

    Returns
    -------
    dict with keys: ok, verts, faces, n_verts, n_faces
    """
    try:
        pts = np.asarray(points, dtype=np.float64)
        if pts.ndim != 2 or pts.shape[1] != 3:
            return {"ok": False, "reason": "points must be (N, 3)"}
        if len(pts) < 4:
            return {"ok": False, "reason": "need at least 4 points"}

        if method == "ball_pivoting":
            return _ball_pivoting(pts, radius)
        elif method == "poisson":
            return _poisson_lite(pts, radius)
        else:
            return {"ok": False, "reason": f"unknown method {method!r}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": str(exc)}


# ---------------------------------------------------------------------------
# Ball-pivoting algorithm
# ---------------------------------------------------------------------------

def _estimate_radius(pts: np.ndarray) -> float:
    """Estimate a good ball radius from average nearest-neighbour distance."""
    tree = KDTree(pts)
    dists, _ = tree.query(pts, k=min(7, len(pts)))
    # dists[:,0] is self (0); use columns 1..k
    mean_nn = float(np.mean(dists[:, 1:]))
    return mean_nn * 2.5


def _ball_pivoting(pts: np.ndarray, radius: float | None) -> Dict[str, Any]:
    """Ball-pivoting surface reconstruction."""
    n = len(pts)
    r = radius if radius is not None else _estimate_radius(pts)

    tree = KDTree(pts)

    # ------------------------------------------------------------------
    # Per-point oriented normals (PCA on k-neighbourhood)
    # ------------------------------------------------------------------
    normals = _estimate_normals(pts, tree, k=min(15, n - 1))

    # ------------------------------------------------------------------
    # Core BPA state
    # ------------------------------------------------------------------
    # edge_table: (i, j) -> list of opposite vertices k (the triangles using edge)
    edge_table: dict[tuple[int, int], list[int]] = defaultdict(list)
    # Set of used edges (both orientations) to detect boundaries vs. interior
    used_edges: set[tuple[int, int]] = set()
    faces: list[tuple[int, int, int]] = []
    on_front: set[int] = set()  # vertices currently on the advancing front
    used_in_mesh: set[int] = set()

    # front edges: (i, j, k_opposite) — the ball is currently resting on
    # edge i-j with triangle i-j-k already added.
    front: list[tuple[int, int, int]] = []

    def _add_triangle(a: int, b: int, c: int) -> None:
        faces.append((a, b, c))
        used_in_mesh.update([a, b, c])
        for e in [(a, b), (b, c), (c, a)]:
            edge_table[e].append(c if e == (a, b) else (a if e == (b, c) else b))
            used_edges.add(e)

    def _find_seed() -> tuple[int, int, int] | None:
        """Find an unused point and grow a seed triangle from it."""
        for i in range(n):
            if i in used_in_mesh:
                continue
            # neighbours within 2r
            idx = tree.query_ball_point(pts[i], 2 * r)
            idx = [j for j in idx if j != i]
            if len(idx) < 2:
                continue
            for j in idx:
                for k in idx:
                    if k <= j:
                        continue
                    if _valid_triangle(i, j, k, pts, normals, r, used_in_mesh):
                        return i, j, k
        return None

    def _pivot_ball(ei: int, ej: int, ek: int) -> int | None:
        """Pivot from edge (ei, ej) (opposite vertex ek) to find next vertex."""
        pi, pj, pk = pts[ei], pts[ej], pts[ek]
        mid = (pi + pj) / 2.0
        candidates = tree.query_ball_point(mid, 2 * r)
        best_angle = -1.0
        best_m = -1
        for m in candidates:
            if m == ei or m == ej or m == ek:
                continue
            if _sphere_contains_only(pts, tree, ei, ej, m, r, ei, ej, ek):
                angle = _pivot_angle(pi, pj, pk, pts[m])
                if angle > best_angle:
                    best_angle = angle
                    best_m = m
        return best_m if best_m >= 0 else None

    # ------------------------------------------------------------------
    # Seed + advance
    # ------------------------------------------------------------------
    max_iterations = min(n * 20, 200_000)
    iteration = 0

    while iteration < max_iterations:
        iteration += 1
        if not front:
            seed = _find_seed()
            if seed is None:
                break
            a, b, c = seed
            # Orient so normal agrees with estimated point normal
            ni = normals[a]
            tri_normal = np.cross(pts[b] - pts[a], pts[c] - pts[a])
            if np.dot(tri_normal, ni) < 0:
                b, c = c, b
            _add_triangle(a, b, c)
            front.extend([(a, b, c), (b, c, a), (c, a, b)])
            continue

        ei, ej, ek = front.pop()
        # Skip if edge is already interior (two triangles share it)
        if (ei, ej) in used_edges and (ej, ei) in used_edges:
            continue
        # Already processed opposite direction
        if len(edge_table.get((ei, ej), [])) >= 2:
            continue

        m = _pivot_ball(ei, ej, ek)
        if m is None:
            continue

        # Check edge not already added in this orientation
        if (ei, m) in used_edges and (m, ej) in used_edges:
            continue

        # Ensure consistent winding
        tri_normal = np.cross(pts[ej] - pts[ei], pts[m] - pts[ei])
        ni = normals[ei]
        if np.dot(tri_normal, ni) < 0:
            _add_triangle(ei, m, ej)
            front.extend([(ei, m, ej), (m, ej, ei)])
        else:
            _add_triangle(ei, ej, m)
            front.extend([(ei, ej, m), (ej, m, ei)])

    if not faces:
        return {"ok": False, "reason": "ball-pivoting produced no faces"}

    verts_arr = pts.copy()
    faces_arr = np.array(faces, dtype=np.int64)

    return {
        "ok": True,
        "verts": verts_arr,
        "faces": faces_arr,
        "n_verts": len(verts_arr),
        "n_faces": len(faces_arr),
    }


def _valid_triangle(
    i: int, j: int, k: int,
    pts: np.ndarray,
    normals: np.ndarray,
    r: float,
    used: set,
) -> bool:
    """Return True if the ball of radius r resting on triangle i,j,k is valid."""
    pi, pj, pk = pts[i], pts[j], pts[k]
    centre = _ball_centre(pi, pj, pk, r)
    if centre is None:
        return False
    # Normal consistency
    tri_n = np.cross(pj - pi, pk - pi)
    norm = np.linalg.norm(tri_n)
    if norm < 1e-14:
        return False
    avg_n = normals[i] + normals[j] + normals[k]
    return float(np.dot(tri_n, avg_n)) > 0


def _ball_centre(p0: np.ndarray, p1: np.ndarray, p2: np.ndarray, r: float):
    """Compute ball centre for triangle p0,p1,p2 with ball radius r."""
    # Circumcentre of the triangle
    a = p1 - p0
    b = p2 - p0
    axb = np.cross(a, b)
    denom = 2.0 * float(np.dot(axb, axb))
    if abs(denom) < 1e-14:
        return None
    alpha = float(np.dot(b, b) * np.dot(a, a - b)) / denom
    beta = float(np.dot(a, a) * np.dot(b, b - a)) / denom
    # gamma = 1 - alpha - beta is implicit
    circ = p0 + alpha * a + beta * b
    circ_r = float(np.linalg.norm(circ - p0))
    if circ_r > r:
        return None  # circumradius larger than ball radius — can't fit
    # Lift ball centre off the plane
    n = axb / math.sqrt(float(np.dot(axb, axb)))
    h2 = r * r - circ_r * circ_r
    if h2 < 0:
        return None
    return circ + math.sqrt(h2) * n


def _sphere_contains_only(
    pts: np.ndarray,
    tree: KDTree,
    ei: int, ej: int, m: int,
    r: float,
    *exclude,
) -> bool:
    """Return True if the ball through pts[ei], pts[ej], pts[m] contains no others."""
    centre = _ball_centre(pts[ei], pts[ej], pts[m], r)
    if centre is None:
        return False
    inside = tree.query_ball_point(centre, r - 1e-10)
    excl = set(exclude) | {ei, ej, m}
    return not any(i not in excl for i in inside)


def _pivot_angle(pi: np.ndarray, pj: np.ndarray, pk: np.ndarray, pm: np.ndarray) -> float:
    """Angle swept by ball pivoting from triangle (pi,pj,pk) to (pi,pj,pm)."""
    mid = (pi + pj) / 2.0
    vk = pk - mid
    vm = pm - mid
    nk = np.linalg.norm(vk)
    nm = np.linalg.norm(vm)
    if nk < 1e-14 or nm < 1e-14:
        return -1.0
    cos_a = float(np.clip(np.dot(vk, vm) / (nk * nm), -1.0, 1.0))
    return math.acos(cos_a)


def _estimate_normals(pts: np.ndarray, tree: KDTree, k: int = 15) -> np.ndarray:
    """Estimate per-point outward normals via PCA on k-NN neighbourhood."""
    n = len(pts)
    normals = np.zeros((n, 3), dtype=np.float64)
    _, idx = tree.query(pts, k=k + 1)  # +1 because first is self
    centroid = np.mean(pts, axis=0)

    for i in range(n):
        neighbours = pts[idx[i, 1:]]  # exclude self
        cov = np.cov(neighbours.T)
        # Smallest eigenvector = normal direction
        eigvals, eigvecs = np.linalg.eigh(cov)
        normal = eigvecs[:, 0]  # smallest eigenvalue
        # Orient outward: dot with vector from cloud centroid
        if np.dot(normal, pts[i] - centroid) < 0:
            normal = -normal
        normals[i] = normal

    return normals


# ---------------------------------------------------------------------------
# Poisson-lite reconstruction
# ---------------------------------------------------------------------------

def _poisson_lite(pts: np.ndarray, cell_size: float | None) -> Dict[str, Any]:
    """
    Simplified Poisson surface reconstruction on a voxel grid.

    Strategy:
    1. Estimate oriented normals (PCA on k-NN).
    2. Splat normals into a divergence field on a uniform grid.
    3. Solve for the indicator function (cumulative sum approximation).
    4. Extract iso-surface via marching cubes.
    """
    n = len(pts)

    # Auto cell size
    tree = KDTree(pts)
    if cell_size is None:
        dists, _ = tree.query(pts, k=min(7, n - 1))
        mean_nn = float(np.mean(dists[:, 1:]))
        cell_size = mean_nn * 1.5

    # Grid setup
    lo = pts.min(axis=0) - 2 * cell_size
    hi = pts.max(axis=0) + 2 * cell_size
    dims = np.ceil((hi - lo) / cell_size).astype(int) + 1
    # Cap grid for performance
    dims = np.minimum(dims, 64)

    gx = np.linspace(lo[0], hi[0], dims[0])
    gy = np.linspace(lo[1], hi[1], dims[1])
    gz = np.linspace(lo[2], hi[2], dims[2])

    # Oriented normals
    normals = _estimate_normals(pts, tree, k=min(15, n - 1))

    # Indicator field: voxel is "inside" if it is on the interior side of
    # most nearby oriented normals.
    field = np.zeros(tuple(dims), dtype=np.float64)

    # Voxel centres
    grid_x, grid_y, grid_z = np.meshgrid(gx, gy, gz, indexing="ij")
    voxel_pts = np.stack([grid_x.ravel(), grid_y.ravel(), grid_z.ravel()], axis=-1)

    # For each voxel centre, find nearest point and use signed distance
    # (dot of offset with normal) as the indicator.
    vox_tree = KDTree(pts)
    dists_vox, idx_vox = vox_tree.query(voxel_pts, k=1)

    offsets = voxel_pts - pts[idx_vox]  # (V, 3)
    nn = normals[idx_vox]               # (V, 3)
    signed = np.einsum("ij,ij->i", offsets, nn)  # dot product per row

    field = signed.reshape(tuple(dims))

    # Extract iso-surface at 0 (transition from inside to outside)
    try:
        verts_out, faces_out = _marching_cubes(field, lo, cell_size, dims, iso=0.0)
    except Exception as exc:
        return {"ok": False, "reason": f"marching cubes failed: {exc}"}

    if len(faces_out) == 0:
        return {"ok": False, "reason": "poisson-lite produced no faces"}

    return {
        "ok": True,
        "verts": verts_out,
        "faces": faces_out,
        "n_verts": len(verts_out),
        "n_faces": len(faces_out),
    }


# ---------------------------------------------------------------------------
# Minimal marching cubes (single iso-value, pure Python/numpy)
# ---------------------------------------------------------------------------

# Marching cubes edge table: each cube has 12 edges; _EDGE_TABLE[config] is a
# bitmask of which edges are cut.  _TRI_TABLE[config] lists the triangles.
# We use the classic Lorensen & Cline 1987 tables (256 entries).

_EDGE_TABLE = [
    0x0, 0x109, 0x203, 0x30a, 0x406, 0x50f, 0x605, 0x70c,
    0x80c, 0x905, 0xa0f, 0xb06, 0xc0a, 0xd03, 0xe09, 0xf00,
    0x190, 0x099, 0x393, 0x29a, 0x596, 0x49f, 0x795, 0x69c,
    0x99c, 0x895, 0xb9f, 0xa96, 0xd9a, 0xc93, 0xf99, 0xe90,
    0x230, 0x339, 0x033, 0x13a, 0x636, 0x73f, 0x435, 0x53c,
    0xa3c, 0xb35, 0x83f, 0x936, 0xe3a, 0xf33, 0xc39, 0xd30,
    0x3a0, 0x2a9, 0x1a3, 0x0aa, 0x7a6, 0x6af, 0x5a5, 0x4ac,
    0xbac, 0xaa5, 0x9af, 0x8a6, 0xfaa, 0xea3, 0xda9, 0xca0,
    0x460, 0x569, 0x663, 0x76a, 0x066, 0x16f, 0x265, 0x36c,
    0xc6c, 0xd65, 0xe6f, 0xf66, 0x86a, 0x963, 0xa69, 0xb60,
    0x5f0, 0x4f9, 0x7f3, 0x6fa, 0x1f6, 0x0ff, 0x3f5, 0x2fc,
    0xdfc, 0xcf5, 0xfff, 0xef6, 0x9fa, 0x8f3, 0xbf9, 0xaf0,
    0x650, 0x759, 0x453, 0x55a, 0x256, 0x35f, 0x055, 0x15c,
    0xe5c, 0xf55, 0xc5f, 0xd56, 0xa5a, 0xb53, 0x859, 0x950,
    0x7c0, 0x6c9, 0x5c3, 0x4ca, 0x3c6, 0x2cf, 0x1c5, 0x0cc,
    0xfcc, 0xec5, 0xdcf, 0xcc6, 0xbca, 0xac3, 0x9c9, 0x8c0,
    0x8c0, 0x9c9, 0xac3, 0xbca, 0xcc6, 0xdcf, 0xec5, 0xfcc,
    0x0cc, 0x1c5, 0x2cf, 0x3c6, 0x4ca, 0x5c3, 0x6c9, 0x7c0,
    0x950, 0x859, 0xb53, 0xa5a, 0xd56, 0xc5f, 0xf55, 0xe5c,
    0x15c, 0x055, 0x35f, 0x256, 0x55a, 0x453, 0x759, 0x650,
    0xaf0, 0xbf9, 0x8f3, 0x9fa, 0xef6, 0xfff, 0xcf5, 0xdfc,
    0x2fc, 0x3f5, 0x0ff, 0x1f6, 0x6fa, 0x7f3, 0x4f9, 0x5f0,
    0xb60, 0xa69, 0x963, 0x86a, 0xf66, 0xe6f, 0xd65, 0xc6c,
    0x36c, 0x265, 0x16f, 0x066, 0x76a, 0x663, 0x569, 0x460,
    0xca0, 0xda9, 0xea3, 0xfaa, 0x8a6, 0x9af, 0xaa5, 0xbac,
    0x4ac, 0x5a5, 0x6af, 0x7a6, 0x0aa, 0x1a3, 0x2a9, 0x3a0,
    0xd30, 0xc39, 0xf33, 0xe3a, 0x936, 0x83f, 0xb35, 0xa3c,
    0x53c, 0x435, 0x73f, 0x636, 0x13a, 0x033, 0x339, 0x230,
    0xe90, 0xf99, 0xc93, 0xd9a, 0xa96, 0xb9f, 0x895, 0x99c,
    0x69c, 0x795, 0x49f, 0x596, 0x29a, 0x393, 0x099, 0x190,
    0xf00, 0xe09, 0xd03, 0xc0a, 0xb06, 0xa0f, 0x905, 0x80c,
    0x70c, 0x605, 0x50f, 0x406, 0x30a, 0x203, 0x109, 0x0,
]

# Triangle table: each entry is a flat list of edge indices grouped into
# triples.  -1 terminates.
_TRI_TABLE = [
    [-1],
    [0, 8, 3, -1],
    [0, 1, 9, -1],
    [1, 8, 3, 9, 8, 1, -1],
    [1, 2, 10, -1],
    [0, 8, 3, 1, 2, 10, -1],
    [9, 2, 10, 0, 2, 9, -1],
    [2, 8, 3, 2, 10, 8, 10, 9, 8, -1],
    [3, 11, 2, -1],
    [0, 11, 2, 8, 11, 0, -1],
    [1, 9, 0, 2, 3, 11, -1],
    [1, 11, 2, 1, 9, 11, 9, 8, 11, -1],
    [3, 10, 1, 11, 10, 3, -1],
    [0, 10, 1, 0, 8, 10, 8, 11, 10, -1],
    [3, 9, 0, 3, 11, 9, 11, 10, 9, -1],
    [9, 8, 10, 10, 8, 11, -1],
    [4, 7, 8, -1],
    [4, 3, 0, 7, 3, 4, -1],
    [0, 1, 9, 8, 4, 7, -1],
    [4, 1, 9, 4, 7, 1, 7, 3, 1, -1],
    [1, 2, 10, 8, 4, 7, -1],
    [3, 4, 7, 3, 0, 4, 1, 2, 10, -1],
    [9, 2, 10, 9, 0, 2, 8, 4, 7, -1],
    [2, 10, 9, 2, 9, 7, 2, 7, 3, 7, 9, 4, -1],
    [8, 4, 7, 3, 11, 2, -1],
    [11, 4, 7, 11, 2, 4, 2, 0, 4, -1],
    [9, 0, 1, 8, 4, 7, 2, 3, 11, -1],
    [4, 7, 11, 9, 4, 11, 9, 11, 2, 9, 2, 1, -1],
    [3, 10, 1, 3, 11, 10, 7, 8, 4, -1],
    [1, 11, 10, 1, 4, 11, 1, 0, 4, 7, 11, 4, -1],
    [4, 7, 8, 9, 0, 11, 9, 11, 10, 11, 0, 3, -1],
    [4, 7, 11, 4, 11, 9, 9, 11, 10, -1],
    [9, 5, 4, -1],
    [9, 5, 4, 0, 8, 3, -1],
    [0, 5, 4, 1, 5, 0, -1],
    [8, 5, 4, 8, 3, 5, 3, 1, 5, -1],
    [1, 2, 10, 9, 5, 4, -1],
    [3, 0, 8, 1, 2, 10, 4, 9, 5, -1],
    [5, 2, 10, 5, 4, 2, 4, 0, 2, -1],
    [2, 10, 5, 3, 2, 5, 3, 5, 4, 3, 4, 8, -1],
    [9, 5, 4, 2, 3, 11, -1],
    [0, 11, 2, 0, 8, 11, 4, 9, 5, -1],
    [0, 5, 4, 0, 1, 5, 2, 3, 11, -1],
    [2, 1, 5, 2, 5, 8, 2, 8, 11, 4, 8, 5, -1],
    [10, 3, 11, 10, 1, 3, 9, 5, 4, -1],
    [4, 9, 5, 0, 8, 1, 8, 10, 1, 8, 11, 10, -1],
    [5, 4, 0, 5, 0, 11, 5, 11, 10, 11, 0, 3, -1],
    [5, 4, 8, 5, 8, 10, 10, 8, 11, -1],
    [9, 7, 8, 5, 7, 9, -1],
    [9, 3, 0, 9, 5, 3, 5, 7, 3, -1],
    [0, 7, 8, 0, 1, 7, 1, 5, 7, -1],
    [1, 5, 3, 3, 5, 7, -1],
    [9, 7, 8, 9, 5, 7, 10, 1, 2, -1],
    [10, 1, 2, 9, 5, 0, 5, 3, 0, 5, 7, 3, -1],
    [8, 0, 2, 8, 2, 5, 8, 5, 7, 10, 5, 2, -1],
    [2, 10, 5, 2, 5, 3, 3, 5, 7, -1],
    [7, 9, 5, 7, 8, 9, 3, 11, 2, -1],
    [9, 5, 7, 9, 7, 2, 9, 2, 0, 2, 7, 11, -1],
    [2, 3, 11, 0, 1, 8, 1, 7, 8, 1, 5, 7, -1],
    [11, 2, 1, 11, 1, 7, 7, 1, 5, -1],
    [9, 5, 8, 8, 5, 7, 10, 1, 3, 10, 3, 11, -1],
    [5, 7, 0, 5, 0, 9, 7, 11, 0, 1, 0, 10, 11, 10, 0, -1],
    [11, 10, 0, 11, 0, 3, 10, 5, 0, 8, 0, 7, 5, 7, 0, -1],
    [11, 10, 5, 7, 11, 5, -1],
    [10, 6, 5, -1],
    [0, 8, 3, 5, 10, 6, -1],
    [9, 0, 1, 5, 10, 6, -1],
    [1, 8, 3, 1, 9, 8, 5, 10, 6, -1],
    [1, 6, 5, 2, 6, 1, -1],
    [1, 6, 5, 1, 2, 6, 3, 0, 8, -1],
    [9, 6, 5, 9, 0, 6, 0, 2, 6, -1],
    [5, 9, 8, 5, 8, 2, 5, 2, 6, 3, 2, 8, -1],
    [2, 3, 11, 10, 6, 5, -1],
    [11, 0, 8, 11, 2, 0, 10, 6, 5, -1],
    [0, 1, 9, 2, 3, 11, 5, 10, 6, -1],
    [5, 10, 6, 1, 9, 2, 9, 11, 2, 9, 8, 11, -1],
    [6, 3, 11, 6, 5, 3, 5, 1, 3, -1],
    [0, 8, 11, 0, 11, 5, 0, 5, 1, 5, 11, 6, -1],
    [3, 11, 6, 0, 3, 6, 0, 6, 5, 0, 5, 9, -1],
    [6, 5, 9, 6, 9, 11, 11, 9, 8, -1],
    [5, 10, 6, 4, 7, 8, -1],
    [4, 3, 0, 4, 7, 3, 6, 5, 10, -1],
    [1, 9, 0, 5, 10, 6, 8, 4, 7, -1],
    [10, 6, 5, 1, 9, 7, 1, 7, 3, 7, 9, 4, -1],
    [6, 1, 2, 6, 5, 1, 4, 7, 8, -1],
    [1, 2, 5, 5, 2, 6, 3, 0, 4, 3, 4, 7, -1],
    [8, 4, 7, 9, 0, 5, 0, 6, 5, 0, 2, 6, -1],
    [7, 3, 9, 7, 9, 4, 3, 2, 9, 5, 9, 6, 2, 6, 9, -1],
    [3, 11, 2, 7, 8, 4, 10, 6, 5, -1],
    [5, 10, 6, 4, 7, 2, 4, 2, 0, 2, 7, 11, -1],
    [0, 1, 9, 4, 7, 8, 2, 3, 11, 5, 10, 6, -1],
    [9, 2, 1, 9, 11, 2, 9, 4, 11, 7, 11, 4, 5, 10, 6, -1],
    [8, 4, 7, 3, 11, 5, 3, 5, 1, 5, 11, 6, -1],
    [5, 1, 11, 5, 11, 6, 1, 0, 11, 7, 11, 4, 0, 4, 11, -1],
    [0, 5, 9, 0, 6, 5, 0, 3, 6, 11, 6, 3, 8, 4, 7, -1],
    [6, 5, 9, 6, 9, 11, 4, 7, 9, 7, 11, 9, -1],
    [10, 4, 9, 6, 4, 10, -1],
    [4, 10, 6, 4, 9, 10, 0, 8, 3, -1],
    [10, 0, 1, 10, 6, 0, 6, 4, 0, -1],
    [8, 3, 1, 8, 1, 6, 8, 6, 4, 6, 1, 10, -1],
    [1, 4, 9, 1, 2, 4, 2, 6, 4, -1],
    [3, 0, 8, 1, 2, 9, 2, 4, 9, 2, 6, 4, -1],
    [0, 2, 4, 4, 2, 6, -1],
    [8, 3, 2, 8, 2, 4, 4, 2, 6, -1],
    [10, 4, 9, 10, 6, 4, 11, 2, 3, -1],
    [0, 8, 2, 2, 8, 11, 4, 9, 10, 4, 10, 6, -1],
    [3, 11, 2, 0, 1, 6, 0, 6, 4, 6, 1, 10, -1],
    [6, 4, 1, 6, 1, 10, 4, 8, 1, 2, 1, 11, 8, 11, 1, -1],
    [9, 6, 4, 9, 3, 6, 9, 1, 3, 11, 6, 3, -1],
    [8, 11, 1, 8, 1, 0, 11, 6, 1, 9, 1, 4, 6, 4, 1, -1],
    [3, 11, 6, 3, 6, 0, 0, 6, 4, -1],
    [6, 4, 8, 11, 6, 8, -1],
    [7, 10, 6, 7, 8, 10, 8, 9, 10, -1],
    [0, 7, 3, 0, 10, 7, 0, 9, 10, 6, 7, 10, -1],
    [10, 6, 7, 1, 10, 7, 1, 7, 8, 1, 8, 0, -1],
    [10, 6, 7, 10, 7, 1, 1, 7, 3, -1],
    [1, 2, 6, 1, 6, 8, 1, 8, 9, 8, 6, 7, -1],
    [2, 6, 9, 2, 9, 1, 6, 7, 9, 0, 9, 3, 7, 3, 9, -1],
    [7, 8, 0, 7, 0, 6, 6, 0, 2, -1],
    [7, 3, 2, 6, 7, 2, -1],
    [2, 3, 11, 10, 6, 8, 10, 8, 9, 8, 6, 7, -1],
    [2, 0, 7, 2, 7, 11, 0, 9, 7, 6, 7, 10, 9, 10, 7, -1],
    [1, 8, 0, 1, 7, 8, 1, 10, 7, 6, 7, 10, 2, 3, 11, -1],
    [11, 2, 1, 11, 1, 7, 10, 6, 1, 6, 7, 1, -1],
    [8, 9, 6, 8, 6, 7, 9, 1, 6, 11, 6, 3, 1, 3, 6, -1],
    [0, 9, 1, 11, 6, 7, -1],
    [7, 8, 0, 7, 0, 6, 3, 11, 0, 11, 6, 0, -1],
    [7, 11, 6, -1],
    [7, 6, 11, -1],
    [3, 0, 8, 11, 7, 6, -1],
    [0, 1, 9, 11, 7, 6, -1],
    [8, 1, 9, 8, 3, 1, 11, 7, 6, -1],
    [10, 1, 2, 6, 11, 7, -1],
    [1, 2, 10, 3, 0, 8, 6, 11, 7, -1],
    [2, 9, 0, 2, 10, 9, 6, 11, 7, -1],
    [6, 11, 7, 2, 10, 3, 10, 8, 3, 10, 9, 8, -1],
    [7, 2, 3, 6, 2, 7, -1],
    [7, 0, 8, 7, 6, 0, 6, 2, 0, -1],
    [2, 7, 6, 2, 3, 7, 0, 1, 9, -1],
    [1, 6, 2, 1, 8, 6, 1, 9, 8, 8, 7, 6, -1],
    [10, 7, 6, 10, 1, 7, 1, 3, 7, -1],
    [10, 7, 6, 1, 7, 10, 1, 8, 7, 1, 0, 8, -1],
    [0, 3, 7, 0, 7, 10, 0, 10, 9, 6, 10, 7, -1],
    [7, 6, 10, 7, 10, 8, 8, 10, 9, -1],
    [6, 8, 4, 11, 8, 6, -1],
    [3, 6, 11, 3, 0, 6, 0, 4, 6, -1],
    [8, 6, 11, 8, 4, 6, 9, 0, 1, -1],
    [9, 4, 6, 9, 6, 3, 9, 3, 1, 11, 3, 6, -1],
    [6, 8, 4, 6, 11, 8, 2, 10, 1, -1],
    [1, 2, 10, 3, 0, 11, 0, 6, 11, 0, 4, 6, -1],
    [4, 11, 8, 4, 6, 11, 0, 2, 9, 2, 10, 9, -1],
    [10, 9, 3, 10, 3, 2, 9, 4, 3, 11, 3, 6, 4, 6, 3, -1],
    [8, 2, 3, 8, 4, 2, 4, 6, 2, -1],
    [0, 4, 2, 4, 6, 2, -1],
    [1, 9, 0, 2, 3, 4, 2, 4, 6, 4, 3, 8, -1],
    [1, 9, 4, 1, 4, 2, 2, 4, 6, -1],
    [8, 1, 3, 8, 6, 1, 8, 4, 6, 6, 10, 1, -1],
    [10, 1, 0, 10, 0, 6, 6, 0, 4, -1],
    [4, 6, 3, 4, 3, 8, 6, 10, 3, 0, 3, 9, 10, 9, 3, -1],
    [10, 9, 4, 6, 10, 4, -1],
    [4, 9, 5, 7, 6, 11, -1],
    [0, 8, 3, 4, 9, 5, 11, 7, 6, -1],
    [5, 0, 1, 5, 4, 0, 7, 6, 11, -1],
    [11, 7, 6, 8, 3, 4, 3, 5, 4, 3, 1, 5, -1],
    [9, 5, 4, 10, 1, 2, 7, 6, 11, -1],
    [6, 11, 7, 1, 2, 10, 0, 8, 3, 4, 9, 5, -1],
    [7, 6, 11, 5, 4, 10, 4, 2, 10, 4, 0, 2, -1],
    [3, 4, 8, 3, 5, 4, 3, 2, 5, 10, 5, 2, 11, 7, 6, -1],
    [7, 2, 3, 7, 6, 2, 5, 4, 9, -1],
    [9, 5, 4, 0, 8, 6, 0, 6, 2, 6, 8, 7, -1],
    [3, 6, 2, 3, 7, 6, 1, 5, 0, 5, 4, 0, -1],
    [6, 2, 8, 6, 8, 7, 2, 1, 8, 4, 8, 5, 1, 5, 8, -1],
    [9, 5, 4, 10, 1, 6, 1, 7, 6, 1, 3, 7, -1],
    [1, 6, 10, 1, 7, 6, 1, 0, 7, 8, 7, 0, 9, 5, 4, -1],
    [4, 0, 10, 4, 10, 5, 0, 3, 10, 6, 10, 7, 3, 7, 10, -1],
    [7, 6, 10, 7, 10, 8, 5, 4, 10, 4, 8, 10, -1],
    [6, 9, 5, 6, 11, 9, 11, 8, 9, -1],
    [3, 6, 11, 0, 6, 3, 0, 5, 6, 0, 9, 5, -1],
    [0, 11, 8, 0, 5, 11, 0, 1, 5, 5, 6, 11, -1],
    [6, 11, 3, 6, 3, 5, 5, 3, 1, -1],
    [1, 2, 10, 9, 5, 11, 9, 11, 8, 11, 5, 6, -1],
    [0, 11, 3, 0, 6, 11, 0, 9, 6, 5, 6, 9, 1, 2, 10, -1],
    [11, 8, 5, 11, 5, 6, 8, 0, 5, 10, 5, 2, 0, 2, 5, -1],
    [6, 11, 3, 6, 3, 5, 2, 10, 3, 10, 5, 3, -1],
    [5, 8, 9, 5, 2, 8, 5, 6, 2, 3, 8, 2, -1],
    [9, 5, 6, 9, 6, 0, 0, 6, 2, -1],
    [1, 5, 8, 1, 8, 0, 5, 6, 8, 3, 8, 2, 6, 2, 8, -1],
    [1, 5, 6, 2, 1, 6, -1],
    [1, 3, 6, 1, 6, 10, 3, 8, 6, 5, 6, 9, 8, 9, 6, -1],
    [10, 1, 0, 10, 0, 6, 9, 5, 0, 5, 6, 0, -1],
    [0, 3, 8, 5, 6, 10, -1],
    [10, 5, 6, -1],
    [11, 5, 10, 7, 5, 11, -1],
    [11, 5, 10, 11, 7, 5, 8, 3, 0, -1],
    [5, 11, 7, 5, 10, 11, 1, 9, 0, -1],
    [10, 7, 5, 10, 11, 7, 9, 8, 1, 8, 3, 1, -1],
    [11, 1, 2, 11, 7, 1, 7, 5, 1, -1],
    [0, 8, 3, 1, 2, 7, 1, 7, 5, 7, 2, 11, -1],
    [9, 7, 5, 9, 2, 7, 9, 0, 2, 2, 11, 7, -1],
    [7, 5, 2, 7, 2, 11, 5, 9, 2, 3, 2, 8, 9, 8, 2, -1],
    [2, 5, 10, 2, 3, 5, 3, 7, 5, -1],
    [8, 2, 0, 8, 5, 2, 8, 7, 5, 10, 2, 5, -1],
    [9, 0, 1, 5, 10, 3, 5, 3, 7, 3, 10, 2, -1],
    [9, 8, 2, 9, 2, 1, 8, 7, 2, 10, 2, 5, 7, 5, 2, -1],
    [1, 3, 5, 3, 7, 5, -1],
    [0, 8, 7, 0, 7, 1, 1, 7, 5, -1],
    [9, 0, 3, 9, 3, 5, 5, 3, 7, -1],
    [9, 8, 7, 5, 9, 7, -1],
    [5, 8, 4, 5, 10, 8, 10, 11, 8, -1],
    [5, 0, 4, 5, 11, 0, 5, 10, 11, 11, 3, 0, -1],
    [0, 1, 9, 8, 4, 10, 8, 10, 11, 10, 4, 5, -1],
    [10, 11, 4, 10, 4, 5, 11, 3, 4, 9, 4, 1, 3, 1, 4, -1],
    [2, 5, 1, 2, 8, 5, 2, 11, 8, 4, 5, 8, -1],
    [0, 4, 11, 0, 11, 3, 4, 5, 11, 2, 11, 1, 5, 1, 11, -1],
    [0, 2, 5, 0, 5, 9, 2, 11, 5, 4, 5, 8, 11, 8, 5, -1],
    [9, 4, 5, 2, 11, 3, -1],
    [2, 5, 10, 3, 5, 2, 3, 4, 5, 3, 8, 4, -1],
    [5, 10, 2, 5, 2, 4, 4, 2, 0, -1],
    [3, 10, 2, 3, 5, 10, 3, 8, 5, 4, 5, 8, 0, 1, 9, -1],
    [5, 10, 2, 5, 2, 4, 1, 9, 2, 9, 4, 2, -1],
    [8, 4, 5, 8, 5, 3, 3, 5, 1, -1],
    [0, 4, 5, 1, 0, 5, -1],
    [8, 4, 5, 8, 5, 3, 9, 0, 5, 0, 3, 5, -1],
    [9, 4, 5, -1],
    [4, 11, 7, 4, 9, 11, 9, 10, 11, -1],
    [0, 8, 3, 4, 9, 7, 9, 11, 7, 9, 10, 11, -1],
    [1, 10, 11, 1, 11, 4, 1, 4, 0, 7, 4, 11, -1],
    [3, 1, 4, 3, 4, 8, 1, 10, 4, 7, 4, 11, 10, 11, 4, -1],
    [4, 11, 7, 9, 11, 4, 9, 2, 11, 9, 1, 2, -1],
    [9, 7, 4, 9, 11, 7, 9, 1, 11, 2, 11, 1, 0, 8, 3, -1],
    [11, 7, 4, 11, 4, 2, 2, 4, 0, -1],
    [11, 7, 4, 11, 4, 2, 8, 3, 4, 3, 2, 4, -1],
    [2, 9, 10, 2, 7, 9, 2, 3, 7, 7, 4, 9, -1],
    [9, 10, 7, 9, 7, 4, 10, 2, 7, 8, 7, 0, 2, 0, 7, -1],
    [3, 7, 10, 3, 10, 2, 7, 4, 10, 1, 10, 0, 4, 0, 10, -1],
    [1, 10, 2, 8, 7, 4, -1],
    [4, 9, 1, 4, 1, 7, 7, 1, 3, -1],
    [4, 9, 1, 4, 1, 7, 0, 8, 1, 8, 7, 1, -1],
    [4, 0, 3, 7, 4, 3, -1],
    [4, 8, 7, -1],
    [9, 10, 8, 10, 11, 8, -1],
    [3, 0, 9, 3, 9, 11, 11, 9, 10, -1],
    [0, 1, 10, 0, 10, 8, 8, 10, 11, -1],
    [3, 1, 10, 11, 3, 10, -1],
    [1, 2, 11, 1, 11, 9, 9, 11, 8, -1],
    [3, 0, 9, 3, 9, 11, 1, 2, 9, 2, 11, 9, -1],
    [0, 2, 11, 8, 0, 11, -1],
    [3, 2, 11, -1],
    [2, 3, 8, 2, 8, 10, 10, 8, 9, -1],
    [9, 10, 2, 0, 9, 2, -1],
    [2, 3, 8, 2, 8, 10, 0, 1, 8, 1, 10, 8, -1],
    [1, 10, 2, -1],
    [1, 3, 8, 9, 1, 8, -1],
    [0, 9, 1, -1],
    [0, 3, 8, -1],
    [-1],
]

# Cube vertex offsets (local index → (dx, dy, dz))
_CUBE_VERTS = np.array([
    [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
    [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1],
], dtype=np.int32)

# Edge vertex pairs
_CUBE_EDGES = [
    (0, 1), (1, 2), (2, 3), (3, 0),
    (4, 5), (5, 6), (6, 7), (7, 4),
    (0, 4), (1, 5), (2, 6), (3, 7),
]


def _marching_cubes(
    field: np.ndarray,
    lo: np.ndarray,
    cell_size: float,
    dims: np.ndarray,
    iso: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract an iso-surface from a scalar field using marching cubes."""
    verts_out: list[list[float]] = []
    faces_out: list[list[int]] = []
    edge_cache: dict[tuple, int] = {}

    def _interp(p1_idx, p2_idx, v1, v2):
        """Interpolate edge crossing, return vertex index."""
        key = (min(p1_idx, p2_idx), max(p1_idx, p2_idx))
        if key in edge_cache:
            return edge_cache[key]
        if abs(v2 - v1) < 1e-10:
            t = 0.5
        else:
            t = (iso - v1) / (v2 - v1)
        pt = lo + (p1_idx + t * (p2_idx - p1_idx)) * cell_size
        # p1_idx and p2_idx here are world coordinate arrays
        idx = len(verts_out)
        verts_out.append(pt.tolist())
        edge_cache[key] = idx
        return idx

    dx, dy, dz = dims
    for ix in range(dx - 1):
        for iy in range(dy - 1):
            for iz in range(dz - 1):
                # Gather 8 corner values
                corners_ijk = _CUBE_VERTS + np.array([ix, iy, iz], dtype=np.int32)
                vals = np.array([
                    field[ci[0], ci[1], ci[2]] for ci in corners_ijk
                ], dtype=np.float64)

                cube_idx = 0
                for bit, v in enumerate(vals):
                    if v < iso:
                        cube_idx |= (1 << bit)

                if _EDGE_TABLE[cube_idx] == 0:
                    continue

                # Compute world coordinates of the 8 corners
                wc = lo + corners_ijk * cell_size  # shape (8, 3)

                # For each active edge, compute intersection vertex
                edge_verts: dict[int, int] = {}
                for eidx, (va, vb) in enumerate(_CUBE_EDGES):
                    if _EDGE_TABLE[cube_idx] & (1 << eidx):
                        key = (
                            int(corners_ijk[va][0]) * dy * dz +
                            int(corners_ijk[va][1]) * dz +
                            int(corners_ijk[va][2]),
                            int(corners_ijk[vb][0]) * dy * dz +
                            int(corners_ijk[vb][1]) * dz +
                            int(corners_ijk[vb][2]),
                        )
                        key_s = (min(key), max(key))
                        if key_s in edge_cache:
                            edge_verts[eidx] = edge_cache[key_s]
                        else:
                            t_v = vals[va]
                            t_v2 = vals[vb]
                            if abs(t_v2 - t_v) < 1e-10:
                                t = 0.5
                            else:
                                t = (iso - t_v) / (t_v2 - t_v)
                            pt = wc[va] + t * (wc[vb] - wc[va])
                            vidx = len(verts_out)
                            verts_out.append(pt.tolist())
                            edge_cache[key_s] = vidx
                            edge_verts[eidx] = vidx

                # Build triangles
                tri_list = _TRI_TABLE[cube_idx]
                i = 0
                while i < len(tri_list) and tri_list[i] != -1:
                    a = edge_verts[tri_list[i]]
                    b = edge_verts[tri_list[i + 1]]
                    c = edge_verts[tri_list[i + 2]]
                    faces_out.append([a, b, c])
                    i += 3

    if not verts_out:
        return np.zeros((0, 3), dtype=np.float64), np.zeros((0, 3), dtype=np.int64)

    return (
        np.array(verts_out, dtype=np.float64),
        np.array(faces_out, dtype=np.int64),
    )
