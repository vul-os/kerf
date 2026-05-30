"""
subd_symmetry.py
================
Mirror-symmetry detection and enforcement for SubD control cages.

References
----------
- Mitra, Pauly, Wand, Ceylan 2013 "Symmetry in 3D Geometry: Extraction and
  Applications", §3 — planar reflective symmetry via point-cloud PCA + voting.
- Podolak, Shilane, Golovinskiy, Rusinkiewicz, Funkhouser 2006 "A Planar-
  Reflective Symmetry Transform for 3D Shapes" — symmetry-score formulation.

Public API
----------
SymmetryPlane
    Dataclass: normal [nx, ny, nz], offset d (signed distance from origin);
    plane equation: dot(n, p) = d.

SymmetryResult
    Dataclass: planes (list[SymmetryPlane]), dominant_plane, score (float 0-1).

detect_mirror_symmetry(cage, tol=1e-4) -> SymmetryResult
    Test 3 axis-aligned planes plus bbox-centred principal planes.  For each
    candidate plane compute the symmetry score = fraction of vertices that have
    a mirrored counterpart within ``tol``.  Returns a SymmetryResult with all
    detected planes sorted descending by score; dominant_plane is the highest.

enforce_mirror_symmetry(cage, symmetry_plane, side='left') -> SubDCage
    Copy vertex positions from the *keep* side to their mirror counterparts on
    the *other* side.  Vertices on the plane (distance < tol) are snapped to it.
    Returns a fully-symmetric cage; topology is unchanged.

mirror_edit(cage, vertex_id, new_position, symmetry_plane) -> SubDCage
    Move ``vertex_id`` to ``new_position`` and simultaneously move its mirror
    counterpart to the reflected position.  Used by interactive editing tools
    to preserve symmetry while modelling.

All functions never raise — errors produce an unchanged result.
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
    """
    normal: List[float] = field(default_factory=lambda: [0.0, 0.0, 1.0])
    offset: float = 0.0
    label: str = ""


@dataclass
class SymmetryResult:
    """Result of :func:`detect_mirror_symmetry`.

    Attributes
    ----------
    planes : list[SymmetryPlane]
        All candidate symmetry planes sorted descending by score.
    dominant_plane : SymmetryPlane or None
        The plane with the highest score; ``None`` when no vertices exist.
    score : float
        Score of the dominant plane (0–1).  1.0 = perfect symmetry.
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

    A O(n²) nearest-neighbour search is used — adequate for cage meshes where
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
            # On the plane — trivially matched (it is its own mirror).
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
        ``scores`` is a dict of all label → score pairs tested.
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
        # XY → Z component (index 2); XZ → Y (index 1); YZ → X (index 0)
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

    * ``'left'``  → keep vertices with signed_dist >= 0  (positive half-space).
    * ``'right'`` → keep vertices with signed_dist <= 0  (negative half-space).

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
    SubDCage — topology unchanged, vertex positions updated.  Never raises.
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
                continue  # on-plane — handled separately
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
                continue  # authoritative side — leave untouched

            # Opposite side: find nearest keep vertex
            if not keep_indices:
                # No keep-side vertices — snap to plane
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
    counterpart — the vertex nearest to ``reflect(new_position, plane)`` — is
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
    SubDCage — topology unchanged.  Never raises.
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
            # On the plane — snap primary vertex and skip mirror search
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
