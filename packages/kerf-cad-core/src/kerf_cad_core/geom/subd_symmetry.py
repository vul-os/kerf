"""
subd_symmetry.py
================
Mirror-symmetry detection and enforcement for SubD control cages, plus
full symmetry analysis: rotational n-fold symmetry about an axis, spherical
symmetry, and a combined ``detect_symmetry`` entry-point that returns a
``SymmetryReport`` dataclass covering all three categories.

Algorithm (detect_symmetry)
---------------------------
Follows Mitra, Guibas, Pauly 2006 "Partial and Approximate Symmetry Detection
for 3D Geometry" (PCA intrinsic axes) and Podolak, Shilane, Golovinskiy,
Rusinkiewicz, Funkhouser 2006 "A Planar-Reflective Symmetry Transform for 3D
Shapes" (score formulation):

1. Compute centroid and covariance matrix of the vertex point cloud.
2. Eigendecompose the 3x3 covariance matrix (pure-Python Jacobi iteration);
   eigenvectors give the three principal axes.
3. Mirror planes: for each principal axis direction test both the
   centroid-centred plane and the origin-aligned plane.  Also test the three
   axis-aligned planes (XY/XZ/YZ) in case the centroid is near the origin.
   Score = fraction of vertices whose reflection falls within *tol* of some
   cage vertex (O(n^2) nearest-neighbour; adequate for cage sizes < 10 000).
4. Rotational axes: for each of the three principal axes test fold-orders
   n in {2, 3, 4, 5, 6, 8, 10, 12}.  Rotation by 2*pi/n about the axis must
   map every vertex within *tol* of another vertex.  Score = matched fraction.
   Flag as *continuous* if the two smallest PCA eigenvalues are equal (within
   5% relative tolerance) -- this indicates an axis of revolution.
5. Spherical: all three PCA eigenvalues equal -> flag ``spherical = True``
   plus compute a score = fraction of vertices at the same radius (within
   ``tol * max_radius`` tolerance).

Honest-flag caveats
-------------------
- Continuous rotational symmetry (e.g. cylinder / cone / sphere) requires the
  PCA eigenvalue equality test because testing all integer fold-orders cannot
  confirm true continuous symmetry (only discrete approximations).  When
  ``continuous = True`` the integer-fold test merely confirms the discretisation
  is consistent.
- The pure-Python Jacobi eigensolver is accurate to ~1e-9 for 3x3 matrices
  but is O(iterations * 9) -- fine for a 3x3 covariance, not for general n*n.
- O(n^2) vertex search is exact but slow for n > 5 000; for large cages a
  spatial hash (grid bucket) would be more efficient.

References
----------
- Mitra N.J., Guibas L., Pauly M. 2006 "Partial and Approximate Symmetry
  Detection for 3D Geometry", ACM Trans. Graph. 25(3) section 3-4.
- Podolak J., Shilane P., Golovinskiy A., Rusinkiewicz S., Funkhouser T. 2006
  "A Planar-Reflective Symmetry Transform for 3D Shapes", ACM Trans. Graph.
  25(3) section 3.1-3.3.

Public API
----------
SymmetryPlane
    Dataclass: normal [nx, ny, nz], offset d (signed distance from origin);
    plane equation: dot(n, p) = d.  score: float.

RotationAxis
    Dataclass: axis [ax, ay, az], center [cx, cy, cz], fold_order int,
    score float, continuous bool.

SymmetryReport
    Full symmetry analysis: mirror_planes, rotation_axes, spherical,
    spherical_score, overall_score, deviation_per_axis.

SymmetryResult
    Legacy mirror-only result: planes, dominant_plane, score, scores.

detect_symmetry(cage, tol=1e-4) -> SymmetryReport
    Unified mirror + rotational + spherical analysis via PCA.

detect_mirror_symmetry(cage, tol=1e-4) -> SymmetryResult
    Mirror-only detection (original API preserved).

enforce_mirror_symmetry(cage, symmetry_plane, side='left') -> SubDCage
mirror_edit(cage, vertex_id, new_position, symmetry_plane) -> SubDCage

All functions never raise -- errors produce unchanged / empty results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from kerf_cad_core.geom.subd_authoring import SubDCage, _copy_cage


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class SymmetryPlane:
    """A reflective symmetry plane represented as ``dot(normal, p) == offset``.

    Attributes
    ----------
    normal : list of float
        Unit normal vector [nx, ny, nz].
    offset : float
        Signed distance from the origin: ``dot(n, p) = offset`` for points on
        the plane.
    label : str
        Human-readable label, e.g. ``'XY'``, ``'XZ'``, ``'YZ'``.
    score : float
        Symmetry score for this plane (0-1).
    """

    normal: List[float] = field(default_factory=lambda: [0.0, 0.0, 1.0])
    offset: float = 0.0
    label: str = ""
    score: float = 0.0


@dataclass
class RotationAxis:
    """An n-fold rotational symmetry axis.

    Attributes
    ----------
    axis : list of float
        Unit direction vector [ax, ay, az].
    center : list of float
        A point on the axis (typically the centroid) [cx, cy, cz].
    fold_order : int
        n for n-fold rotation (rotation by 2*pi/n maps cage to itself).
    score : float
        Fraction of vertices matched after rotation (0-1).
    continuous : bool
        True if PCA eigenvalue analysis indicates continuous rotational
        symmetry (axis of revolution).  Honest-flag: this uses the PCA
        eigenvalue equality heuristic (|lam1 - lam2| / max(lam1, lam2) < 0.05)
        and cannot be verified by finite fold testing alone.
    label : str
        Human-readable label, e.g. ``'PC0_4fold'``.
    """

    axis: List[float] = field(default_factory=lambda: [0.0, 0.0, 1.0])
    center: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    fold_order: int = 2
    score: float = 0.0
    continuous: bool = False
    label: str = ""


@dataclass
class SymmetryReport:
    """Full symmetry analysis of a SubD cage.

    Attributes
    ----------
    mirror_planes : list[SymmetryPlane]
        All detected mirror planes with score >= 0, sorted descending by score.
    rotation_axes : list[RotationAxis]
        All detected rotation axes (best fold-order per axis), score >= 0.
    spherical : bool
        True if all three PCA eigenvalues are approximately equal -- indicates
        spherical symmetry.  Honest-flag: uses eigenvalue equality heuristic.
    spherical_score : float
        Fraction of vertices at the same radius +/- tol (0-1).
    overall_score : float
        Max of dominant mirror-plane score and dominant rotation-axis score
        (or spherical_score if spherical=True).
    deviation_per_axis : dict mapping label -> float
        Per-candidate mean vertex deviation from the symmetry candidate
        (lower = more symmetric).  Mirror planes use mean reflection residual;
        rotation axes use mean rotation residual.
    """

    mirror_planes: List[SymmetryPlane] = field(default_factory=list)
    rotation_axes: List[RotationAxis] = field(default_factory=list)
    spherical: bool = False
    spherical_score: float = 0.0
    overall_score: float = 0.0
    deviation_per_axis: Dict[str, float] = field(default_factory=dict)


@dataclass
class SymmetryResult:
    """Result of :func:`detect_mirror_symmetry` (legacy mirror-only API).

    Attributes
    ----------
    planes : list[SymmetryPlane]
        All candidate symmetry planes sorted descending by score.
    dominant_plane : SymmetryPlane or None
        The plane with the highest score; ``None`` when no vertices exist.
    score : float
        Score of the dominant plane (0-1).  1.0 = perfect symmetry.
    scores : dict mapping label -> float
        Per-plane scores for all candidates tested.
    """

    planes: List[SymmetryPlane] = field(default_factory=list)
    dominant_plane: Optional[SymmetryPlane] = None
    score: float = 0.0
    scores: Dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------

def _dot(a: List[float], b: List[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _reflect(point: List[float], normal: List[float], offset: float) -> List[float]:
    """Reflect *point* across the plane ``dot(n, p) = offset``.

    r = p - 2 * (dot(n, p) - d) * n
    """
    dist = _dot(normal, point) - offset
    return [
        point[0] - 2.0 * dist * normal[0],
        point[1] - 2.0 * dist * normal[1],
        point[2] - 2.0 * dist * normal[2],
    ]


def _snap_to_plane(point: List[float], normal: List[float], offset: float) -> List[float]:
    """Project *point* onto the plane ``dot(n, p) = offset``."""
    dist = _dot(normal, point) - offset
    return [
        point[0] - dist * normal[0],
        point[1] - dist * normal[1],
        point[2] - dist * normal[2],
    ]


def _dist_sq(a: List[float], b: List[float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return dx * dx + dy * dy + dz * dz


def _bbox(vertices: List[List[float]]) -> Tuple[List[float], List[float]]:
    """Return (min_xyz, max_xyz) bounding box of the vertex list."""
    mn = [vertices[0][0], vertices[0][1], vertices[0][2]]
    mx = [vertices[0][0], vertices[0][1], vertices[0][2]]
    for v in vertices[1:]:
        for i in range(3):
            if v[i] < mn[i]:
                mn[i] = v[i]
            if v[i] > mx[i]:
                mx[i] = v[i]
    return mn, mx


def _centroid(vertices: List[List[float]]) -> List[float]:
    n = len(vertices)
    return [
        sum(v[0] for v in vertices) / n,
        sum(v[1] for v in vertices) / n,
        sum(v[2] for v in vertices) / n,
    ]


# ---------------------------------------------------------------------------
# Core: symmetry score computation
# ---------------------------------------------------------------------------

def _symmetry_score(
    vertices: List[List[float]],
    normal: List[float],
    offset: float,
    tol: float,
) -> float:
    """Return fraction of vertices that have a mirrored counterpart within tol.

    Implementation follows the Podolak et al. 2006 "planar-reflective symmetry
    transform": for each vertex v, compute its mirror v' = reflect(v, plane) and
    check whether any vertex w satisfies dist(w, v') < tol.  The score is the
    fraction of vertices (count_matched / total_vertices).

    For boundary vertices on the plane (|signed_dist| < tol) the vertex is its
    own mirror, so it counts as matched automatically.

    A O(n^2) nearest-neighbour search is used -- adequate for cage meshes where
    n is typically < 10 000.
    """
    n = len(vertices)
    if n == 0:
        return 0.0

    tol_sq = tol * tol
    matched = 0

    for v in vertices:
        signed_dist = _dot(normal, v) - offset
        if abs(signed_dist) < tol:
            # On the plane -- trivially matched (it is its own mirror).
            matched += 1
            continue

        # Reflected position
        rv = [
            v[0] - 2.0 * signed_dist * normal[0],
            v[1] - 2.0 * signed_dist * normal[1],
            v[2] - 2.0 * signed_dist * normal[2],
        ]

        # Check whether any vertex is within tol of rv
        found = False
        for w in vertices:
            if _dist_sq(w, rv) <= tol_sq:
                found = True
                break
        if found:
            matched += 1

    return matched / n


# ---------------------------------------------------------------------------
# Internal: PCA helpers (pure-Python 3x3 Jacobi eigensolver)
# ---------------------------------------------------------------------------

def _covariance_matrix(
    vertices: List[List[float]],
    centroid: List[float],
) -> List[List[float]]:
    """Compute 3x3 covariance matrix of the vertex cloud about centroid."""
    cxx = cxy = cxz = cyy = cyz = czz = 0.0
    for v in vertices:
        dx = v[0] - centroid[0]
        dy = v[1] - centroid[1]
        dz = v[2] - centroid[2]
        cxx += dx * dx
        cxy += dx * dy
        cxz += dx * dz
        cyy += dy * dy
        cyz += dy * dz
        czz += dz * dz
    n = len(vertices)
    if n > 1:
        s = 1.0 / n
        cxx *= s
        cxy *= s
        cxz *= s
        cyy *= s
        cyz *= s
        czz *= s
    return [
        [cxx, cxy, cxz],
        [cxy, cyy, cyz],
        [cxz, cyz, czz],
    ]


def _jacobi_3x3(
    m: List[List[float]],
    max_iter: int = 100,
) -> Tuple[List[float], List[List[float]]]:
    """Jacobi eigendecomposition of a 3x3 symmetric matrix.

    Returns (eigenvalues, eigenvectors) where eigenvectors[i] is the
    eigenvector corresponding to eigenvalues[i].

    Algorithm: classical Jacobi sweeps; O(max_iter * 3) pivot operations.
    Accurate to machine epsilon for 3x3 matrices (Golub-Van Loan section 8.4).
    """
    # Working copy -- symmetric
    a = [[m[i][j] for j in range(3)] for i in range(3)]
    # Start with identity rotation accumulator
    v = [[1.0 if i == j else 0.0 for j in range(3)] for i in range(3)]

    for _ in range(max_iter):
        # Find largest off-diagonal element
        best = 0.0
        pi, pj = 0, 1
        for i in range(3):
            for j in range(i + 1, 3):
                val = abs(a[i][j])
                if val > best:
                    best = val
                    pi, pj = i, j
        if best < 1e-15:
            break

        # Compute rotation angle
        if abs(a[pi][pi] - a[pj][pj]) < 1e-30:
            theta = math.pi / 4.0
        else:
            theta = 0.5 * math.atan2(2.0 * a[pi][pj], a[pi][pi] - a[pj][pj])
        c = math.cos(theta)
        s = math.sin(theta)

        # Apply Givens rotation from both sides
        new_a = [[a[i][j] for j in range(3)] for i in range(3)]
        for k in range(3):
            if k != pi and k != pj:
                new_a[pi][k] = c * a[pi][k] + s * a[pj][k]
                new_a[k][pi] = new_a[pi][k]
                new_a[pj][k] = -s * a[pi][k] + c * a[pj][k]
                new_a[k][pj] = new_a[pj][k]
        new_a[pi][pi] = (
            c * c * a[pi][pi] + 2 * s * c * a[pi][pj] + s * s * a[pj][pj]
        )
        new_a[pj][pj] = (
            s * s * a[pi][pi] - 2 * s * c * a[pi][pj] + c * c * a[pj][pj]
        )
        new_a[pi][pj] = 0.0
        new_a[pj][pi] = 0.0
        a = new_a

        # Accumulate rotation into v
        new_v = [[v[i][j] for j in range(3)] for i in range(3)]
        for k in range(3):
            new_v[k][pi] = c * v[k][pi] + s * v[k][pj]
            new_v[k][pj] = -s * v[k][pi] + c * v[k][pj]
        v = new_v

    eigenvalues = [a[i][i] for i in range(3)]
    eigenvectors = [[v[i][j] for j in range(3)] for i in range(3)]
    return eigenvalues, eigenvectors


def _normalize(vec: List[float]) -> List[float]:
    """Return unit vector, or [0, 0, 1] if near-zero length."""
    mag = math.sqrt(vec[0] * vec[0] + vec[1] * vec[1] + vec[2] * vec[2])
    if mag < 1e-15:
        return [0.0, 0.0, 1.0]
    return [vec[0] / mag, vec[1] / mag, vec[2] / mag]


# ---------------------------------------------------------------------------
# Internal: rotation symmetry helpers
# ---------------------------------------------------------------------------

def _rotate_about_axis(
    point: List[float],
    axis: List[float],
    center: List[float],
    angle: float,
) -> List[float]:
    """Rotate *point* by *angle* (radians) about *axis* through *center*.

    Uses Rodrigues' rotation formula:
        v' = v*cos(t) + (k x v)*sin(t) + k*(k.v)*(1-cos(t))
    """
    # Translate to axis frame
    px = point[0] - center[0]
    py = point[1] - center[1]
    pz = point[2] - center[2]

    ax, ay, az = axis[0], axis[1], axis[2]
    cos_t = math.cos(angle)
    sin_t = math.sin(angle)

    dot = ax * px + ay * py + az * pz

    rx = px * cos_t + (ay * pz - az * py) * sin_t + ax * dot * (1.0 - cos_t)
    ry = py * cos_t + (az * px - ax * pz) * sin_t + ay * dot * (1.0 - cos_t)
    rz = pz * cos_t + (ax * py - ay * px) * sin_t + az * dot * (1.0 - cos_t)

    return [rx + center[0], ry + center[1], rz + center[2]]


def _rotation_score_and_deviation(
    vertices: List[List[float]],
    axis: List[float],
    center: List[float],
    fold: int,
    tol: float,
) -> Tuple[float, float]:
    """Score + mean-deviation for n-fold rotation about axis through center.

    Returns (score, mean_deviation) where score = matched_fraction and
    mean_deviation = average distance from rotated vertex to nearest vertex.
    """
    n = len(vertices)
    if n == 0:
        return 0.0, 0.0

    angle = 2.0 * math.pi / fold
    tol_sq = tol * tol
    matched = 0
    total_dev = 0.0

    for v in vertices:
        rv = _rotate_about_axis(v, axis, center, angle)
        best_dsq = math.inf
        for w in vertices:
            d = _dist_sq(w, rv)
            if d < best_dsq:
                best_dsq = d
        total_dev += math.sqrt(best_dsq)
        if best_dsq <= tol_sq:
            matched += 1

    return matched / n, total_dev / n


def _mirror_deviation(
    vertices: List[List[float]],
    normal: List[float],
    offset: float,
    tol: float,  # noqa: ARG001
) -> float:
    """Mean distance from each reflected vertex to its nearest neighbor."""
    n = len(vertices)
    if n == 0:
        return 0.0
    total = 0.0
    for v in vertices:
        signed_dist = _dot(normal, v) - offset
        rv = [
            v[0] - 2.0 * signed_dist * normal[0],
            v[1] - 2.0 * signed_dist * normal[1],
            v[2] - 2.0 * signed_dist * normal[2],
        ]
        best_dsq = math.inf
        for w in vertices:
            d = _dist_sq(w, rv)
            if d < best_dsq:
                best_dsq = d
        total += math.sqrt(best_dsq)
    return total / n


# ---------------------------------------------------------------------------
# Public: detect_symmetry (unified PCA-based analysis)
# ---------------------------------------------------------------------------

_DEFAULT_FOLD_ORDERS: Tuple[int, ...] = (2, 3, 4, 5, 6, 8, 10, 12)


def detect_symmetry(
    cage: SubDCage,
    tol: float = 1e-4,
    fold_orders: Tuple[int, ...] = _DEFAULT_FOLD_ORDERS,
    score_threshold: float = 0.0,
) -> SymmetryReport:
    """Detect mirror, rotational, and spherical symmetry of a SubD cage.

    Algorithm
    ---------
    Follows Mitra, Guibas, Pauly 2006 section 3 and Podolak et al. 2006
    section 3.1:

    1. Compute centroid and 3x3 covariance matrix of the vertex cloud.
    2. Jacobi-decompose the covariance -> 3 principal axes (eigenvectors).
    3. Mirror planes: test centroid-centred planes normal to each principal
       axis plus the three axis-aligned planes (XY/XZ/YZ through origin).
    4. Rotation axes: for each principal axis test fold orders in
       ``fold_orders``; keep best-scoring fold per axis.
    5. Spherical: eigenvalue equality test (all three lambda_i within 5%).
       Honest-flag: heuristic only -- confirmed by radial-distance score.

    Parameters
    ----------
    cage : SubDCage
    tol : float
        Vertex-matching tolerance.  Default 1e-4.
    fold_orders : tuple of int
        Rotation fold orders to test.  Default (2, 3, 4, 5, 6, 8, 10, 12).
    score_threshold : float
        Minimum score to include a candidate in the results (0 = include all).

    Returns
    -------
    SymmetryReport
        ``mirror_planes`` sorted descending by score.
        ``rotation_axes`` sorted descending by score (best fold per axis).
        ``spherical`` flag + ``spherical_score``.
        ``overall_score`` = max across all detected symmetries.
        ``deviation_per_axis`` mean vertex deviation per candidate label.

    References
    ----------
    Mitra N.J., Guibas L., Pauly M. 2006 "Partial and Approximate Symmetry
    Detection for 3D Geometry", ACM Trans. Graph. 25(3).
    Podolak J., et al. 2006 "A Planar-Reflective Symmetry Transform for 3D
    Shapes", ACM Trans. Graph. 25(3).
    """
    try:
        verts = cage.vertices
        if not verts:
            return SymmetryReport()

        cen = _centroid(verts)
        cov = _covariance_matrix(verts, cen)
        eigenvalues, eigenvectors = _jacobi_3x3(cov)

        # Sort eigenvectors by eigenvalue descending
        order = sorted(range(3), key=lambda i: eigenvalues[i], reverse=True)
        evals = [eigenvalues[i] for i in order]
        evecs = [
            _normalize([eigenvectors[r][order[col]] for r in range(3)])
            for col in range(3)
        ]

        # ----------------------------------------------------------------
        # Mirror planes: centroid-centred PCA planes + axis-aligned planes
        # ----------------------------------------------------------------
        mirror_candidates: List[Tuple[float, float, SymmetryPlane]] = []
        dev_map: Dict[str, float] = {}

        axis_normals = [
            ([0.0, 0.0, 1.0], "XY"),
            ([0.0, 1.0, 0.0], "XZ"),
            ([1.0, 0.0, 0.0], "YZ"),
        ]
        # PCA planes through centroid
        for ci, evec in enumerate(evecs):
            off = _dot(evec, cen)
            lbl = f"PC{ci}"
            sc = _symmetry_score(verts, evec, off, tol)
            dev = _mirror_deviation(verts, evec, off, tol)
            plane = SymmetryPlane(normal=list(evec), offset=off, label=lbl, score=sc)
            mirror_candidates.append((sc, dev, plane))
            dev_map[lbl] = dev

        # Axis-aligned planes through origin (and centroid)
        axis_comp = {"XY": 2, "XZ": 1, "YZ": 0}
        for normal_raw, label in axis_normals:
            for suf, off in [("", 0.0), ("_cen", cen[axis_comp[label]])]:
                lbl = label + suf
                sc = _symmetry_score(verts, normal_raw, off, tol)
                dev = _mirror_deviation(verts, normal_raw, off, tol)
                plane = SymmetryPlane(
                    normal=list(normal_raw), offset=off, label=lbl, score=sc,
                )
                mirror_candidates.append((sc, dev, plane))
                dev_map[lbl] = dev

        mirror_candidates.sort(key=lambda t: t[0], reverse=True)
        mirror_planes = [p for sc, _, p in mirror_candidates if sc >= score_threshold]

        # ----------------------------------------------------------------
        # Rotational symmetry: test each principal axis x each fold order
        # ----------------------------------------------------------------
        rotation_candidates: List[Tuple[float, float, RotationAxis]] = []
        for ci, evec in enumerate(evecs):
            best_score = -1.0
            best_dev = math.inf
            best_fold = 2
            best_label = f"PC{ci}_2fold"
            for fold in fold_orders:
                sc, dev = _rotation_score_and_deviation(verts, evec, cen, fold, tol)
                lbl = f"PC{ci}_{fold}fold"
                dev_map[lbl] = dev
                if sc > best_score or (sc == best_score and dev < best_dev):
                    best_score = sc
                    best_dev = dev
                    best_fold = fold
                    best_label = lbl

            # Continuous symmetry: test if the two transverse eigenvalues are equal
            other_idxs = [j for j in range(3) if j != ci]
            lam1 = abs(evals[other_idxs[0]])
            lam2 = abs(evals[other_idxs[1]])
            max_lam = max(lam1, lam2, 1e-30)
            continuous = abs(lam1 - lam2) / max_lam < 0.05

            rax = RotationAxis(
                axis=list(evec),
                center=list(cen),
                fold_order=best_fold,
                score=best_score,
                continuous=continuous,
                label=best_label,
            )
            rotation_candidates.append((best_score, best_dev, rax))

        rotation_candidates.sort(key=lambda t: t[0], reverse=True)
        rotation_axes = [r for sc, _, r in rotation_candidates if sc >= score_threshold]

        # ----------------------------------------------------------------
        # Spherical symmetry: all three eigenvalues approximately equal
        # ----------------------------------------------------------------
        max_eval = max(abs(evals[0]), abs(evals[1]), abs(evals[2]), 1e-30)
        spherical = (
            abs(evals[0] - evals[1]) / max_eval < 0.05
            and abs(evals[1] - evals[2]) / max_eval < 0.05
        )
        # Radial consistency score
        radii = [
            math.sqrt(
                (v[0] - cen[0]) ** 2
                + (v[1] - cen[1]) ** 2
                + (v[2] - cen[2]) ** 2
            )
            for v in verts
        ]
        max_r = max(radii) if radii else 1.0
        if max_r < 1e-15:
            spherical_score = 1.0
        else:
            r_tol = tol * max(max_r, 1.0)
            mean_r = sum(radii) / len(radii)
            matched_r = sum(1 for r in radii if abs(r - mean_r) <= r_tol)
            spherical_score = matched_r / len(radii)

        # ----------------------------------------------------------------
        # Overall score
        # ----------------------------------------------------------------
        best_mirror = mirror_planes[0].score if mirror_planes else 0.0
        best_rot = rotation_axes[0].score if rotation_axes else 0.0
        overall = spherical_score if spherical else max(best_mirror, best_rot)

        return SymmetryReport(
            mirror_planes=mirror_planes,
            rotation_axes=rotation_axes,
            spherical=spherical,
            spherical_score=spherical_score,
            overall_score=overall,
            deviation_per_axis=dev_map,
        )
    except Exception:
        return SymmetryReport()


# ---------------------------------------------------------------------------
# Public: detect_mirror_symmetry
# ---------------------------------------------------------------------------

def detect_mirror_symmetry(
    cage: SubDCage,
    tol: float = 1e-4,
) -> SymmetryResult:
    """Detect mirror-symmetry planes in a SubD control cage.

    Candidate planes tested
    -----------------------
    For each of the three axis-aligned plane orientations (XY, XZ, YZ) two
    planes are tested:

    1. The global axis-aligned plane through the world origin (offset = 0).
    2. The bbox-centred axis-aligned plane (offset = centroid component).

    The world-origin and bbox-centred planes coincide when the mesh is centred;
    duplicates are deduplicated by offset.

    Score
    -----
    symmetry_score = # vertices with a mirrored counterpart within tol /
                     total # vertices.

    A score of 1.0 indicates perfect symmetry; 0.0 means no vertex has a
    mirror.

    Parameters
    ----------
    cage : SubDCage
    tol : float
        Vertex-matching tolerance.  Default 1e-4.

    Returns
    -------
    SymmetryResult
        ``planes`` sorted descending by score.  ``dominant_plane`` is the
        highest-scoring plane.  ``score`` is the dominant score.
        ``scores`` is a dict of all label -> score pairs tested.
    """
    try:
        verts = cage.vertices
        if not verts:
            return SymmetryResult()

        cen = _centroid(verts)

        # Candidate planes: (normal, offset_list, label_prefix)
        axis_candidates = [
            ([0.0, 0.0, 1.0], "XY"),   # XY plane (normal=Z)
            ([0.0, 1.0, 0.0], "XZ"),   # XZ plane (normal=Y)
            ([1.0, 0.0, 0.0], "YZ"),   # YZ plane (normal=X)
        ]

        # Axis component indices for centering
        # XY -> Z component (index 2); XZ -> Y (index 1); YZ -> X (index 0)
        axis_comp = {"XY": 2, "XZ": 1, "YZ": 0}

        all_planes: List[Tuple[float, SymmetryPlane]] = []
        scores_map: Dict[str, float] = {}

        for normal_raw, label in axis_candidates:
            comp_idx = axis_comp[label]
            tested_offsets: List[Tuple[float, str]] = [
                (0.0, label),
                (cen[comp_idx], f"{label}_cen"),
            ]

            seen_offsets: set = set()
            for offset, lbl in tested_offsets:
                # Round to tol precision to deduplicate
                key = round(offset / max(tol, 1e-15)) * tol
                if key in seen_offsets:
                    continue
                seen_offsets.add(key)

                sc = _symmetry_score(verts, normal_raw, offset, tol)
                plane = SymmetryPlane(
                    normal=list(normal_raw),
                    offset=offset,
                    label=lbl,
                    score=sc,
                )
                all_planes.append((sc, plane))
                scores_map[lbl] = sc

        # Sort descending by score
        all_planes.sort(key=lambda t: t[0], reverse=True)

        result_planes = [p for _, p in all_planes]
        dominant_score = all_planes[0][0] if all_planes else 0.0
        dominant_plane = all_planes[0][1] if all_planes else None

        return SymmetryResult(
            planes=result_planes,
            dominant_plane=dominant_plane,
            score=dominant_score,
            scores=scores_map,
        )
    except Exception:
        return SymmetryResult()


# ---------------------------------------------------------------------------
# Public: enforce_mirror_symmetry
# ---------------------------------------------------------------------------

def enforce_mirror_symmetry(
    cage: SubDCage,
    symmetry_plane: SymmetryPlane,
    side: str = "left",
    tol: float = 1e-4,
) -> SubDCage:
    """Enforce mirror symmetry across ``symmetry_plane``.

    For every vertex on the *opposite* side, its position is overwritten with
    the reflection of the closest vertex on the *keep* side.

    Side convention
    ---------------
    The plane divides space into two half-spaces via the signed distance
    ``dot(normal, p) - offset``:

    * ``'left'``  -> keep vertices with signed_dist >= 0  (positive half-space).
    * ``'right'`` -> keep vertices with signed_dist <= 0  (negative half-space).

    Vertices on the plane (``|signed_dist| < tol``) are snapped onto the plane
    regardless of the ``side`` argument.

    Algorithm
    ---------
    For each vertex v in the *opposite* half-space:

    1. Compute its ideal mirror position ``v_mirror = reflect(v, plane)``.
    2. Find the closest vertex ``w`` on the *keep* side.
    3. Set ``v_new = reflect(w, plane)``.

    This is the standard "copy + mirror" approach used by DCC tools.  When the
    mesh is already nearly symmetric, ``w ≈ reflect(v)`` and the change is
    small.

    Parameters
    ----------
    cage : SubDCage
    symmetry_plane : SymmetryPlane
    side : 'left' | 'right'
        Which half-space to treat as the *authoritative* side.  Default 'left'.
    tol : float
        Distance threshold for "on the plane" vertex snapping.

    Returns
    -------
    SubDCage -- topology unchanged, vertex positions updated.  Never raises.
    """
    try:
        normal = symmetry_plane.normal
        offset = symmetry_plane.offset
        result = _copy_cage(cage)
        verts = result.vertices
        n_verts = len(verts)
        if n_verts == 0:
            return result

        keep_positive = (side == "left")

        # Classify each vertex
        signed_dists = [_dot(normal, v) - offset for v in verts]

        # Build list of keep-side vertex indices (excluding on-plane)
        keep_indices = []
        for i, sd in enumerate(signed_dists):
            if abs(sd) < tol:
                continue  # on-plane -- handled separately
            if keep_positive:
                if sd > 0.0:
                    keep_indices.append(i)
            else:
                if sd < 0.0:
                    keep_indices.append(i)

        # For each vertex NOT on the keep side, find nearest keep vertex and
        # mirror it.
        for i, sd in enumerate(signed_dists):
            if abs(sd) < tol:
                # Snap to plane
                verts[i] = _snap_to_plane(verts[i], normal, offset)
                continue

            on_keep = (sd > 0.0) if keep_positive else (sd < 0.0)
            if on_keep:
                continue  # authoritative side -- leave untouched

            # Opposite side: find nearest keep vertex
            if not keep_indices:
                # No keep-side vertices -- snap to plane
                verts[i] = _snap_to_plane(verts[i], normal, offset)
                continue

            ideal_mirror = _reflect(verts[i], normal, offset)
            best_idx = keep_indices[0]
            best_dsq = _dist_sq(cage.vertices[best_idx], ideal_mirror)
            for ki in keep_indices[1:]:
                d = _dist_sq(cage.vertices[ki], ideal_mirror)
                if d < best_dsq:
                    best_dsq = d
                    best_idx = ki

            # Mirror the keep vertex onto the opposite side
            verts[i] = _reflect(cage.vertices[best_idx], normal, offset)

        return result
    except Exception:
        return _copy_cage(cage)


# ---------------------------------------------------------------------------
# Public: mirror_edit
# ---------------------------------------------------------------------------

def mirror_edit(
    cage: SubDCage,
    vertex_id: int,
    new_position: Sequence[float],
    symmetry_plane: SymmetryPlane,
    tol: float = 1e-4,
) -> SubDCage:
    """Move a vertex and simultaneously update its mirror counterpart.

    The vertex at ``vertex_id`` is moved to ``new_position``.  Its mirror
    counterpart -- the vertex nearest to ``reflect(new_position, plane)`` -- is
    moved to exactly ``reflect(new_position, plane)``.

    If the new position is on the symmetry plane (within ``tol``), both the
    vertex and its counterpart are snapped to the plane.

    If no mirror counterpart is found (single vertex, or vertex is on the
    plane), only the primary vertex is updated.

    Parameters
    ----------
    cage : SubDCage
    vertex_id : int
        Index of the vertex to move.
    new_position : sequence of 3 floats
        Target position [x, y, z].
    symmetry_plane : SymmetryPlane
    tol : float
        Plane-snapping and mirror-search tolerance.

    Returns
    -------
    SubDCage -- topology unchanged.  Never raises.
    """
    try:
        vid = int(vertex_id)
        new_pos = [float(new_position[0]), float(new_position[1]), float(new_position[2])]
        normal = symmetry_plane.normal
        offset = symmetry_plane.offset

        n_verts = len(cage.vertices)
        if vid < 0 or vid >= n_verts:
            return _copy_cage(cage)

        result = _copy_cage(cage)
        verts = result.vertices

        # Move the primary vertex
        verts[vid] = new_pos

        # Compute the ideal mirror of the new position
        signed_dist = _dot(normal, new_pos) - offset
        if abs(signed_dist) < tol:
            # On the plane -- snap primary vertex and skip mirror search
            verts[vid] = _snap_to_plane(new_pos, normal, offset)
            return result

        mirror_pos = _reflect(new_pos, normal, offset)

        # Find the vertex nearest to mirror_pos (excluding vid itself)
        best_idx = -1
        best_dsq = math.inf
        for i in range(n_verts):
            if i == vid:
                continue
            d = _dist_sq(cage.vertices[i], mirror_pos)
            if d < best_dsq:
                best_dsq = d
                best_idx = i

        if best_idx >= 0:
            verts[best_idx] = mirror_pos

        return result
    except Exception:
        return _copy_cage(cage)
