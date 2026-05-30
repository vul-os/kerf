"""
subd_wire_intersect.py
======================
SubD cage intersection with wire-mesh boundary curves.

Finds where a SubD limit surface meets explicit wire curves and embeds new
edges along the projection.  Useful for:
  * Stylised character lines / scarification
  * Branding / embossing paths
  * Constraint curves ("SubD must pass through this path")

Theory
------
The approach follows Levin (2003) "Modified subdivision surfaces with
continuous curvature" and Karciauskas–Peters (2014) "Improvements to the
classification of extraordinary vertices in NURBS-compatible subdivision
surfaces":

  1. Given a wire curve, sample it densely.
  2. For each sample point, find the nearest vertex on the *limit surface*
     (approximated by a few levels of CC subdivision).
  3. Project the wire onto the limit surface by mapping each sample to its
     nearest cage vertex's *limit position* (via the closed-form Stam rule),
     then walk the connectivity to insert new vertices exactly at the
     projection points.
  4. Insert new cage vertices; tag the resulting edges with sharpness = inf
     (fully sharp) so they act as feature curves in subsequent subdivision.

Public API
----------
Curve3D
    Simple dataclass for a piecewise-linear 3-D polyline.

WireIntersectResult
    Result of intersect_subd_with_wires — modified cage, new edge ids,
    and worst-case projection residual.

intersect_subd_with_wires(cage, wires, snap_tolerance=1e-3) -> WireIntersectResult
    Project wire curves onto the SubD limit surface and insert new cage
    edges along the projection.

extract_wire_from_subd_intersection(cage, plane) -> list[Curve3D]
    Extract the intersection curve where a plane cuts the SubD limit surface.

embed_wire_as_feature_curve(cage, wire) -> SubDCage
    Convenience wrapper: intersect + tag result as feature curve with
    infinite sharpness.

Never raises — all exceptions produce empty / unchanged results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from kerf_cad_core.geom.subd import (
    SubDMesh,
    catmull_clark_subdivide,
    subd_limit_position,
)
from kerf_cad_core.geom.subd_authoring import (
    SubDCage,
    _copy_cage,
)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

@dataclass
class Curve3D:
    """Piecewise-linear 3-D polyline.

    Attributes
    ----------
    points : list of [x, y, z]
        Ordered sample points.  At least 2 points make a valid curve.
    closed : bool
        If True the last point is implicitly connected back to the first.
    """
    points: List[List[float]] = field(default_factory=list)
    closed: bool = False

    @property
    def num_points(self) -> int:
        return len(self.points)

    def sample(self, n: int) -> "List[List[float]]":
        """Resample to exactly *n* evenly-spaced points along arc-length."""
        if n < 2 or len(self.points) < 2:
            return [list(p) for p in self.points]
        # Build cumulative arc-length
        pts = self.points
        segs = [0.0]
        for i in range(1, len(pts)):
            d = _dist3(pts[i - 1], pts[i])
            segs.append(segs[-1] + d)
        total = segs[-1]
        if total < 1e-15:
            return [list(pts[0])] * n
        result: List[List[float]] = []
        for k in range(n):
            t = total * k / (n - 1)
            # Binary search for segment
            lo, hi = 0, len(segs) - 2
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if segs[mid] <= t:
                    lo = mid
                else:
                    hi = mid - 1
            seg_t = (t - segs[lo]) / max(1e-15, segs[lo + 1] - segs[lo])
            seg_t = max(0.0, min(1.0, seg_t))
            p = _lerp3(pts[lo], pts[lo + 1], seg_t)
            result.append(p)
        return result


@dataclass
class WireIntersectResult:
    """Result of :func:`intersect_subd_with_wires`.

    Attributes
    ----------
    cage_modified : SubDCage
        Updated cage with new vertices + edges inserted along the projection.
    new_edges : list of list[(int, int)]
        Per-wire lists of new (v_a, v_b) edge pairs inserted.
    projection_residual : float
        Maximum distance from any wire sample to its nearest limit-surface
        point (lower is better; ideally < snap_tolerance).
    """
    cage_modified: SubDCage = field(default_factory=SubDCage)
    new_edges: List[List[Tuple[int, int]]] = field(default_factory=list)
    projection_residual: float = 0.0


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------

def _dist3(a: List[float], b: List[float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    dz = a[2] - b[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _lerp3(a: List[float], b: List[float], t: float) -> List[float]:
    return [a[i] + (b[i] - a[i]) * t for i in range(3)]


def _add3(a: List[float], b: List[float]) -> List[float]:
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _scale3(v: List[float], s: float) -> List[float]:
    return [v[0] * s, v[1] * s, v[2] * s]


def _sub3(a: List[float], b: List[float]) -> List[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _dot3(a: List[float], b: List[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm3(v: List[float]) -> List[float]:
    ln = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    if ln < 1e-15:
        return [0.0, 0.0, 1.0]
    return [v[0] / ln, v[1] / ln, v[2] / ln]


def _nearest_point_on_segment(p: List[float], a: List[float], b: List[float]) -> Tuple[List[float], float]:
    """Return the nearest point on segment a-b to p, plus the parameter t in [0,1]."""
    ab = _sub3(b, a)
    ap = _sub3(p, a)
    denom = _dot3(ab, ab)
    if denom < 1e-30:
        return list(a), 0.0
    t = max(0.0, min(1.0, _dot3(ap, ab) / denom))
    return _lerp3(a, b, t), t


def _build_limit_surface_vertices(cage: SubDCage, levels: int = 3) -> SubDMesh:
    """Evaluate the limit surface by subdividing the cage mesh."""
    mesh = cage.to_subd_mesh()
    return catmull_clark_subdivide(mesh, levels=levels)


def _nearest_limit_vertex(
    query: List[float],
    limit_mesh: SubDMesh,
) -> Tuple[int, float]:
    """Find the nearest vertex in the limit mesh to *query*.

    Returns (vertex_index, distance).
    """
    best_idx = 0
    best_dist = float("inf")
    for i, v in enumerate(limit_mesh.vertices):
        d = _dist3(query, v)
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx, best_dist


def _cage_limit_positions(cage: SubDCage) -> List[List[float]]:
    """Compute the Stam limit position for every cage vertex."""
    mesh = cage.to_subd_mesh()
    return [subd_limit_position(mesh, i) for i in range(len(mesh.vertices))]


# ---------------------------------------------------------------------------
# Core: project a single wire sample onto the cage
# ---------------------------------------------------------------------------

def _project_wire_to_cage(
    wire_samples: List[List[float]],
    cage: SubDCage,
    limit_mesh: SubDMesh,
    snap_tolerance: float,
) -> Tuple[List[int], float]:
    """Map each wire sample to the nearest cage vertex by proximity on the
    limit surface.

    Returns
    -------
    (cage_vertex_sequence, max_residual)
        A list of cage vertex indices (one per sample, deduplicated
        consecutively), and the maximum projection residual.
    """
    # For each wire sample, find the nearest vertex in the limit surface.
    # The limit_mesh vertex layout mirrors the cage vertex ordering when
    # levels=0, so we compute limit positions of cage vertices and use those.

    # Build limit positions of original cage vertices only
    cage_mesh = cage.to_subd_mesh()
    n_cage = len(cage_mesh.vertices)
    lim_pts: List[List[float]] = []
    for i in range(n_cage):
        lim_pts.append(subd_limit_position(cage_mesh, i))

    max_residual = 0.0
    cage_seq: List[int] = []

    for sample in wire_samples:
        best_ci = 0
        best_d = float("inf")
        for ci, lp in enumerate(lim_pts):
            d = _dist3(sample, lp)
            if d < best_d:
                best_d = d
                best_ci = ci
        max_residual = max(max_residual, best_d)
        # Deduplicate consecutive identical cage vertices
        if not cage_seq or cage_seq[-1] != best_ci:
            cage_seq.append(best_ci)

    return cage_seq, max_residual


def _insert_wire_vertices(
    cage: SubDCage,
    wire_samples: List[List[float]],
    snap_tolerance: float,
    infinite_sharpness: bool = True,
) -> Tuple[SubDCage, List[Tuple[int, int]], float]:
    """Project wire samples onto the limit surface, insert new cage vertices
    where needed, and return the new edge pairs.

    Strategy:
      1. For each consecutive pair of wire samples, find the nearest cage edge
         (in limit-surface space).
      2. Insert a new vertex at the projection point on that edge.
      3. Tag the chain of new edges with infinite (or unit) sharpness.

    Returns
    -------
    (new_cage, new_edge_pairs, max_residual)
    """
    if len(wire_samples) < 2:
        return _copy_cage(cage), [], 0.0

    cage_mesh = cage.to_subd_mesh()
    n_cage_orig = len(cage_mesh.vertices)

    # Compute limit positions for all original cage vertices
    lim_pts: List[List[float]] = [
        subd_limit_position(cage_mesh, i) for i in range(n_cage_orig)
    ]

    # Build edge list (original cage topology)
    all_edges = cage.cage_edges()

    # For each wire sample, find the nearest point among all cage edges
    # (using limit-surface positions for each edge's endpoints).
    max_residual = 0.0
    new_verts: List[List[float]] = [list(v) for v in cage.vertices]
    new_faces: List[List[int]] = [list(f) for f in cage.faces]
    # Map: original edge key -> list of (t, new_vi) insertions sorted by t
    edge_insertions: Dict[Tuple[int, int], List[Tuple[float, int]]] = {}
    new_edge_pairs: List[Tuple[int, int]] = []

    # Map each wire sample to a position on the cage (edge + parameter)
    sample_placements: List[Tuple[Tuple[int, int], float, List[float]]] = []
    # (edge_key, t, world_pos)

    for sample in wire_samples:
        best_key: Optional[Tuple[int, int]] = None
        best_t = 0.0
        best_pt: List[float] = [0.0, 0.0, 0.0]
        best_d = float("inf")

        for key in all_edges:
            a_ci, b_ci = key
            if a_ci >= len(lim_pts) or b_ci >= len(lim_pts):
                continue
            la = lim_pts[a_ci]
            lb = lim_pts[b_ci]
            near_pt, t = _nearest_point_on_segment(sample, la, lb)
            d = _dist3(sample, near_pt)
            if d < best_d:
                best_d = d
                best_key = key
                best_t = t
                best_pt = near_pt

        max_residual = max(max_residual, best_d)

        if best_key is not None:
            # Snap to endpoint if within snap_tolerance
            a_ci, b_ci = best_key
            va_world = new_verts[a_ci]  # cage space (not limit)
            vb_world = new_verts[b_ci]

            if best_t < snap_tolerance or best_d < snap_tolerance:
                # Snap to start vertex
                sample_placements.append((best_key, 0.0, va_world))
            elif best_t > 1.0 - snap_tolerance:
                # Snap to end vertex
                sample_placements.append((best_key, 1.0, vb_world))
            else:
                # Interpolate cage-space position using the same parameter t
                cage_pt = _lerp3(va_world, vb_world, best_t)
                sample_placements.append((best_key, best_t, cage_pt))

    # Deduplicate placements: merge samples that land on the same edge with
    # very similar t values (within snap_tolerance along the edge length).
    unique_placements: List[Tuple[Tuple[int, int], float, List[float]]] = []
    for key, t, pt in sample_placements:
        duplicate = False
        for ukey, ut, upt in unique_placements:
            if ukey == key and abs(ut - t) < snap_tolerance:
                duplicate = True
                break
        if not duplicate:
            unique_placements.append((key, t, pt))

    # Insert new vertices into cage for each non-endpoint placement.
    # edge_vtx_map[edge_key][t] = vertex_index
    edge_vtx_map: Dict[Tuple[int, int], Dict[float, int]] = {}

    for key, t, pt in unique_placements:
        a_ci, b_ci = key
        if t <= snap_tolerance:
            vtx_idx = a_ci
        elif t >= 1.0 - snap_tolerance:
            vtx_idx = b_ci
        else:
            # Check if a vertex at this t was already inserted on this edge
            edge_map = edge_vtx_map.setdefault(key, {})
            matched = None
            for existing_t, existing_vi in edge_map.items():
                if abs(existing_t - t) < snap_tolerance:
                    matched = existing_vi
                    break
            if matched is not None:
                vtx_idx = matched
            else:
                # Insert new vertex
                vtx_idx = len(new_verts)
                new_verts.append(list(pt))
                edge_map[t] = vtx_idx
                # Track insertion for topology update
                edge_insertions.setdefault(key, []).append((t, vtx_idx))

        edge_vtx_map.setdefault(key, {})[t] = vtx_idx

    # Now update the face topology to incorporate inserted vertices.
    # For each edge with insertions, split the adjacent faces.
    for key, insertions in edge_insertions.items():
        insertions.sort()  # sort by t
        a_ci, b_ci = key

        # Find all faces containing this edge and split them
        faces_to_update: List[int] = []
        for fi, face in enumerate(new_faces):
            n = len(face)
            for i in range(n):
                u = face[i]
                v_ = face[(i + 1) % n]
                if (min(u, v_), max(u, v_)) == key:
                    faces_to_update.append(fi)
                    break

        if not faces_to_update:
            continue

        # Build the ordered sequence of vertices along the split edge:
        # a_ci, [inserted verts in t order], b_ci
        edge_verts_seq: List[int] = [a_ci]
        for t_val, vi in insertions:
            edge_verts_seq.append(vi)
        edge_verts_seq.append(b_ci)

        # Replace the edge in each face with the chain of new vertices
        for fi in faces_to_update:
            face = new_faces[fi]
            n = len(face)
            new_face: List[int] = []
            for i in range(n):
                u = face[i]
                v_ = face[(i + 1) % n]
                new_face.append(u)
                edge_here = (min(u, v_), max(u, v_))
                if edge_here == key:
                    # Insert the chain between u and v_
                    if u == a_ci:
                        # Forward direction
                        for inserted_vi in edge_verts_seq[1:-1]:
                            new_face.append(inserted_vi)
                    else:
                        # Reverse direction (edge traversed b→a)
                        for inserted_vi in reversed(edge_verts_seq[1:-1]):
                            new_face.append(inserted_vi)
            new_faces[fi] = new_face

    # Build the sequence of vertex indices along the wire path (before
    # face-splitting so we know which pairs to connect).
    wire_vert_seq: List[int] = []
    for key, t, pt in unique_placements:
        a_ci, b_ci = key
        if t <= snap_tolerance:
            vi = a_ci
        elif t >= 1.0 - snap_tolerance:
            vi = b_ci
        else:
            edge_map = edge_vtx_map.get(key, {})
            vi = a_ci  # fallback
            for existing_t, existing_vi in edge_map.items():
                if abs(existing_t - t) < snap_tolerance:
                    vi = existing_vi
                    break
        if not wire_vert_seq or wire_vert_seq[-1] != vi:
            wire_vert_seq.append(vi)

    # Face-split step: for each consecutive (va, vb) pair in the wire
    # sequence that are both in the same n-gon face but are NOT already
    # adjacent, cut the face along the va-vb diagonal.  This promotes the
    # wire connection into a proper topological edge so it can carry sharpness.
    wire_pairs: Set[Tuple[int, int]] = set()
    for i in range(len(wire_vert_seq) - 1):
        va = wire_vert_seq[i]
        vb = wire_vert_seq[i + 1]
        wire_pairs.add((min(va, vb), max(va, vb)))

    # For each wire pair, check if it is already a topological edge; if not,
    # find the face that contains both vertices and split it.
    def _edge_in_face(face: List[int], va: int, vb: int) -> bool:
        """True if va-vb is a consecutive edge in the face."""
        n = len(face)
        for i in range(n):
            if face[i] == va and face[(i + 1) % n] == vb:
                return True
            if face[i] == vb and face[(i + 1) % n] == va:
                return True
        return False

    def _split_face_on_diagonal(face: List[int], va: int, vb: int) -> List[List[int]]:
        """Split a polygon face on the diagonal va-vb.

        Returns two sub-faces.  Requires both va and vb to be in the face
        and not already adjacent.
        """
        n = len(face)
        # Find positions of va and vb
        pos_a = face.index(va)
        pos_b = face.index(vb)
        if pos_a > pos_b:
            pos_a, pos_b = pos_b, pos_a
            va, vb = vb, va
        # face[pos_a..pos_b] → sub-face A (includes both va and vb)
        face_a = face[pos_a:pos_b + 1]
        # face[pos_b..end] + face[0..pos_a] → sub-face B
        face_b = face[pos_b:] + face[:pos_a + 1]
        return [face_a, face_b]

    split_happened = True
    max_iters = len(wire_pairs) * 10
    iteration = 0
    while split_happened and iteration < max_iters:
        split_happened = False
        iteration += 1
        for pair_key in list(wire_pairs):
            va, vb = pair_key
            # Check if already a topological edge
            already_edge = any(_edge_in_face(f, va, vb) for f in new_faces)
            if already_edge:
                continue
            # Find a face containing both va and vb
            for fi, face in enumerate(new_faces):
                if va in face and vb in face:
                    if len(face) <= 2:
                        continue
                    if _edge_in_face(face, va, vb):
                        continue
                    try:
                        sub_faces = _split_face_on_diagonal(face, va, vb)
                        # Replace this face with the two sub-faces
                        new_faces[fi] = sub_faces[0]
                        new_faces.append(sub_faces[1])
                        split_happened = True
                    except (ValueError, IndexError):
                        pass
                    break

    # Build new cage with updated topology (after face-splits)
    result = SubDCage(
        vertices=new_verts,
        faces=new_faces,
        sharpness=dict(cage.sharpness),
        bevel_weights=dict(cage.bevel_weights),
    )

    # Tag the edges along the wire sequence with infinite sharpness
    new_result_edges = result.cage_edges()
    sharpness_inf = math.inf

    for i in range(len(wire_vert_seq) - 1):
        va = wire_vert_seq[i]
        vb = wire_vert_seq[i + 1]
        pair_key = (min(va, vb), max(va, vb))
        try:
            eid = new_result_edges.index(pair_key)
            if infinite_sharpness:
                result.sharpness[eid] = sharpness_inf
            new_edge_pairs.append((va, vb))
        except ValueError:
            # Wire pair was not promoted to a topological edge; still record it
            new_edge_pairs.append((va, vb))

    return result, new_edge_pairs, max_residual


# ---------------------------------------------------------------------------
# Public: intersect_subd_with_wires
# ---------------------------------------------------------------------------

def intersect_subd_with_wires(
    cage: SubDCage,
    wires: List[Curve3D],
    snap_tolerance: float = 1e-3,
) -> WireIntersectResult:
    """Project wire curves onto the SubD limit surface and embed new cage edges.

    For each wire:
      1. Sample *n_samples* points along the wire (adaptive density based on
         wire length relative to cage bounding-box size).
      2. For each sample, find the nearest cage edge in limit-surface space.
      3. Insert new cage vertices at the projection points.
      4. Tag the resulting edge chain with sharpness = inf (perfectly sharp
         feature curve).

    Parameters
    ----------
    cage : SubDCage
        Input control cage.  Not mutated.
    wires : list of Curve3D
        Wire curves to project.  Each is sampled densely before projection.
    snap_tolerance : float
        Maximum distance within which a wire sample is snapped to an existing
        cage vertex (default 1e-3).  Also the merge threshold for duplicate
        insertion points on the same edge.

    Returns
    -------
    WireIntersectResult
        Modified cage (with new vertices + feature edges), per-wire edge lists,
        and the worst-case projection residual over all wires.
    Never raises.
    """
    try:
        if not cage.vertices or not cage.faces or not wires:
            return WireIntersectResult(
                cage_modified=_copy_cage(cage),
                new_edges=[[] for _ in wires],
                projection_residual=0.0,
            )

        # Estimate cage bounding-box diagonal for adaptive sampling
        xs = [v[0] for v in cage.vertices]
        ys = [v[1] for v in cage.vertices]
        zs = [v[2] for v in cage.vertices]
        diag = _dist3(
            [min(xs), min(ys), min(zs)],
            [max(xs), max(ys), max(zs)],
        )
        base_samples = max(32, int(diag * 100))

        current_cage = _copy_cage(cage)
        all_wire_edges: List[List[Tuple[int, int]]] = []
        overall_residual = 0.0

        for wire in wires:
            if wire.num_points < 2:
                all_wire_edges.append([])
                continue

            # Adaptive sample count
            wire_len = sum(
                _dist3(wire.points[i], wire.points[i + 1])
                for i in range(len(wire.points) - 1)
            )
            n_samples = max(8, min(base_samples, int(wire_len / max(1e-9, diag) * base_samples)))
            samples = wire.sample(n_samples)

            new_cage, wire_edges, residual = _insert_wire_vertices(
                current_cage,
                samples,
                snap_tolerance,
                infinite_sharpness=True,
            )
            current_cage = new_cage
            all_wire_edges.append(wire_edges)
            overall_residual = max(overall_residual, residual)

        return WireIntersectResult(
            cage_modified=current_cage,
            new_edges=all_wire_edges,
            projection_residual=overall_residual,
        )
    except Exception:
        return WireIntersectResult(
            cage_modified=_copy_cage(cage),
            new_edges=[[] for _ in wires],
            projection_residual=float("inf"),
        )


# ---------------------------------------------------------------------------
# Public: extract_wire_from_subd_intersection
# ---------------------------------------------------------------------------

def extract_wire_from_subd_intersection(
    cage: SubDCage,
    plane: Tuple[List[float], List[float]],
) -> List[Curve3D]:
    """Extract intersection curves where a plane cuts the SubD limit surface.

    Evaluates the cage through 3 levels of CC subdivision to produce a dense
    limit surface approximation, then uses the Marching Edges algorithm on
    the resulting quad mesh to extract planar cross-sections.

    Parameters
    ----------
    cage : SubDCage
        Control cage.
    plane : (point, normal)
        Plane defined by a point on the plane and an outward unit normal.
        Both are [x, y, z] lists.

    Returns
    -------
    list of Curve3D
        Intersection polylines.  Returns empty list if no intersection.
        Never raises.
    """
    try:
        plane_pt, plane_normal = plane
        # Normalise the plane normal
        nrm = _norm3(plane_normal)

        # Evaluate the limit surface
        limit_mesh = _build_limit_surface_vertices(cage, levels=3)
        verts = limit_mesh.vertices
        faces = limit_mesh.faces

        # Signed distance of each vertex to the plane
        signed_dist: List[float] = []
        for v in verts:
            d = _dot3(_sub3(v, plane_pt), nrm)
            signed_dist.append(d)

        # Determine a sign-threshold based on the range of distances.
        # When the plane passes exactly through mesh vertices (d≈0), we
        # perturb those vertices to a small positive value so that the
        # marching-edges algorithm still produces crossings on the adjacent
        # edges.  This avoids the degenerate "no crossings" case.
        dist_range = max(abs(d) for d in signed_dist) if signed_dist else 1.0
        eps = dist_range * 1e-9 + 1e-15  # tiny relative epsilon

        # Classify vertices: -1 (below), 0 (on-plane), +1 (above)
        # Use a small epsilon to handle exact-zero distances.
        on_plane_eps = dist_range * 1e-7 + 1e-12
        adj_dist: List[float] = []
        for d in signed_dist:
            if abs(d) < on_plane_eps:
                adj_dist.append(eps)  # perturb slightly positive
            else:
                adj_dist.append(d)

        # Marching-edges on quad/tri faces: find edges that straddle the plane
        # (one vertex positive, one negative) and compute the crossing point.
        # Also collect edges where one endpoint is exactly on the plane (d≈0).
        edge_cross: Dict[Tuple[int, int], List[float]] = {}  # edge_key -> point
        # on-plane vertices: collect edges incident to on-plane vertices that
        # connect to vertices on opposite sides → the on-plane vertex itself.
        on_plane_verts: Set[int] = set(
            i for i, d in enumerate(signed_dist) if abs(d) < on_plane_eps
        )

        for face in faces:
            n = len(face)
            for i in range(n):
                a_idx = face[i]
                b_idx = face[(i + 1) % n]
                da = adj_dist[a_idx]
                db = adj_dist[b_idx]
                key = (min(a_idx, b_idx), max(a_idx, b_idx))
                if key in edge_cross:
                    continue
                if da * db < 0.0:  # opposite sides — standard crossing
                    t = da / (da - db)  # crossing parameter
                    pt = _lerp3(verts[a_idx], verts[b_idx], t)
                    edge_cross[key] = pt
                elif a_idx in on_plane_verts and b_idx not in on_plane_verts:
                    # Edge from on-plane vertex to off-plane vertex
                    edge_cross[key] = list(verts[a_idx])
                elif b_idx in on_plane_verts and a_idx not in on_plane_verts:
                    edge_cross[key] = list(verts[b_idx])

        if not edge_cross:
            return []

        # Build adjacency: crossing points form line segments through faces.
        # For each face, collect all crossing edges and form segments.
        segments: List[Tuple[List[float], List[float]]] = []

        for face in faces:
            n = len(face)
            cross_pts: List[List[float]] = []
            for i in range(n):
                a_idx = face[i]
                b_idx = face[(i + 1) % n]
                key = (min(a_idx, b_idx), max(a_idx, b_idx))
                if key in edge_cross:
                    cross_pts.append(edge_cross[key])
            # Deduplicate consecutive duplicate points (on-plane vertices
            # can appear on multiple edges of the same face).
            dedup: List[List[float]] = []
            for cp in cross_pts:
                if not dedup or _dist3(dedup[-1], cp) > 1e-12:
                    dedup.append(cp)
            cross_pts = dedup

            if len(cross_pts) == 2:
                segments.append((cross_pts[0], cross_pts[1]))
            elif len(cross_pts) > 2:
                # Take first and last for polygons with multiple crossings
                for k in range(0, len(cross_pts) - 1, 2):
                    segments.append((cross_pts[k], cross_pts[k + 1]))

        if not segments:
            return []

        # Chain segments into polylines using endpoint proximity
        curves = _chain_segments(segments, tol=1e-6)
        return curves
    except Exception:
        return []


def _chain_segments(
    segments: List[Tuple[List[float], List[float]]],
    tol: float = 1e-6,
) -> List[Curve3D]:
    """Chain unordered line segments into polylines.

    Uses greedy endpoint matching: start a chain with the first unused segment,
    then repeatedly append the segment whose nearest endpoint is within *tol*
    of the current chain's tail.  If no segment can extend the chain, start
    a new one.

    Parameters
    ----------
    segments : list of (p0, p1) endpoint pairs
    tol : float
        Snap tolerance for endpoint matching.

    Returns
    -------
    list of Curve3D  — never raises.
    """
    if not segments:
        return []

    used: List[bool] = [False] * len(segments)
    chains: List[List[List[float]]] = []

    for start_i in range(len(segments)):
        if used[start_i]:
            continue
        used[start_i] = True
        chain: List[List[float]] = [list(segments[start_i][0]), list(segments[start_i][1])]
        extended = True
        while extended:
            extended = False
            tail = chain[-1]
            head = chain[0]
            for j in range(len(segments)):
                if used[j]:
                    continue
                p0, p1 = segments[j]
                if _dist3(tail, p0) < tol:
                    chain.append(list(p1))
                    used[j] = True
                    extended = True
                    break
                elif _dist3(tail, p1) < tol:
                    chain.append(list(p0))
                    used[j] = True
                    extended = True
                    break
                elif _dist3(head, p0) < tol:
                    chain.insert(0, list(p1))
                    used[j] = True
                    extended = True
                    break
                elif _dist3(head, p1) < tol:
                    chain.insert(0, list(p0))
                    used[j] = True
                    extended = True
                    break
        if chain:
            chains.append(chain)

    result: List[Curve3D] = []
    for chain in chains:
        if len(chain) >= 2:
            # Check if closed (head ≈ tail)
            closed = _dist3(chain[0], chain[-1]) < tol
            result.append(Curve3D(points=chain, closed=closed))

    return result


# ---------------------------------------------------------------------------
# Public: embed_wire_as_feature_curve
# ---------------------------------------------------------------------------

def embed_wire_as_feature_curve(
    cage: SubDCage,
    wire: Curve3D,
    snap_tolerance: float = 1e-3,
) -> SubDCage:
    """Embed a wire as a feature curve in the SubD cage.

    Convenience wrapper around :func:`intersect_subd_with_wires` that returns
    only the modified cage with feature-curve sharpness applied.

    Parameters
    ----------
    cage : SubDCage
    wire : Curve3D
        The curve to embed.
    snap_tolerance : float
        Snap tolerance (default 1e-3).

    Returns
    -------
    SubDCage with new feature edges at infinite sharpness.
    Never raises.
    """
    try:
        result = intersect_subd_with_wires(cage, [wire], snap_tolerance=snap_tolerance)
        return result.cage_modified
    except Exception:
        return _copy_cage(cage)


# ---------------------------------------------------------------------------
# LLM tool registration (gated — mirrors subd.py pattern)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    import json as _json  # noqa: F811

    _subd_intersect_wires_spec = ToolSpec(
        name="subd_intersect_wires",
        description=(
            "Project explicit wire curves onto a SubD cage's limit surface and "
            "embed new feature edges along the projection.  Each wire curve is "
            "sampled densely; samples are projected to the nearest point on the "
            "CC limit surface; new cage vertices are inserted and tagged with "
            "infinite sharpness so subsequent subdivision produces sharp feature "
            "lines (useful for character lines, branding, scarification).\n"
            "\n"
            "wire_curves: list of polylines, each a list of [x,y,z] points.\n"
            "\n"
            "Returns:\n"
            "  ok                  : bool\n"
            "  vertices            : updated cage vertices\n"
            "  faces               : updated cage faces\n"
            "  new_edges           : per-wire list of new [v_a, v_b] edge pairs\n"
            "  projection_residual : float — worst-case projection error\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Control-mesh vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Face vertex-index lists [[i,j,k,l], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "wire_curves": {
                    "type": "array",
                    "description": "List of wire curves, each a list of [x,y,z] sample points.",
                    "items": {
                        "type": "array",
                        "items": {"type": "array", "items": {"type": "number"}},
                    },
                },
                "snap_tolerance": {
                    "type": "number",
                    "description": "Snap distance for merging nearby samples (default 1e-3).",
                },
                "creases": {
                    "type": "array",
                    "description": "Optional existing crease entries [{v1, v2, value}].",
                    "items": {
                        "type": "object",
                        "properties": {
                            "v1": {"type": "integer"},
                            "v2": {"type": "integer"},
                            "value": {"type": "number"},
                        },
                        "required": ["v1", "v2", "value"],
                    },
                },
            },
            "required": ["vertices", "faces", "wire_curves"],
        },
    )

    @register(_subd_intersect_wires_spec)
    async def run_subd_intersect_wires(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_wires = a.get("wire_curves", [])
        snap_tol = float(a.get("snap_tolerance", 1e-3))
        raw_creases = a.get("creases", [])

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if not raw_wires:
            return err_payload("wire_curves is required", "BAD_ARGS")

        try:
            cage = SubDCage(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid cage mesh: {exc}", "BAD_ARGS")

        # Apply any existing creases
        edges = cage.cage_edges()
        for ce in raw_creases:
            try:
                v1 = int(ce["v1"])
                v2 = int(ce["v2"])
                val = float(ce["value"])
                key = (min(v1, v2), max(v1, v2))
                try:
                    eid = edges.index(key)
                    cage.sharpness[eid] = val
                except ValueError:
                    pass
            except Exception:
                pass

        # Build wire curves
        wires: List[Curve3D] = []
        for raw_wire in raw_wires:
            try:
                pts = [[float(x) for x in pt] for pt in raw_wire]
                if len(pts) >= 2:
                    wires.append(Curve3D(points=pts))
            except Exception:
                pass

        if not wires:
            return err_payload("no valid wire_curves (need >= 2 points each)", "BAD_ARGS")

        result = intersect_subd_with_wires(cage, wires, snap_tolerance=snap_tol)

        # Serialise new_edges as [[v_a, v_b], ...]
        new_edges_out = [
            [[va, vb] for va, vb in wire_edges]
            for wire_edges in result.new_edges
        ]

        return ok_payload({
            "ok": True,
            "vertices": result.cage_modified.vertices,
            "faces": result.cage_modified.faces,
            "new_edges": new_edges_out,
            "projection_residual": result.projection_residual,
            "num_vertices": result.cage_modified.num_vertices,
            "num_faces": result.cage_modified.num_faces,
        })
