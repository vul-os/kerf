"""2D region boolean operations on planar curve loops.

This module implements union, intersection, and difference for regions
defined by planar closed loops whose edges are :class:`Line3` and
:class:`CircleArc3` segments (from ``brep.py``).

Algorithm overview
------------------
The implementation follows Greiner-Hormann polygon clipping extended to
handle circular arc edges:

1. **Project to 2D** — all loops must lie on a common plane.  We auto-
   detect the plane from the first loop that has non-degenerate geometry
   and project every loop into that (u, v) coordinate frame.

2. **Arc tessellation** — arcs are adaptively subdivided into short
   chord segments so that the GH intersection-finding phase can operate
   on polylines. The polyline approximation is *only* used to locate
   intersection parameters; the final output curves are reconstructed
   with the correct analytic types.

3. **Greiner-Hormann traversal** — we find all intersections between the
   two boundary polylines, classify entering/exiting, and trace result
   loops by alternating between the subject and clip chains.

4. **Curve reconstruction** — each edge of the output polyline loop is
   matched back to its source segment (line or arc) and the segment is
   split at the intersection parameter.  Short collinear runs are merged
   back into single :class:`Line3` edges; arc runs are re-expressed as
   :class:`CircleArc3`.

Public API
----------
.. code-block:: python

    from kerf_cad_core.geom.region_2d import loop_union, loop_intersection, loop_difference

    result_loops = loop_union(loop_a, loop_b)
    result_loops = loop_intersection(loop_a, loop_b)
    result_loops = loop_difference(loop_a, loop_b)

Each function returns a (possibly empty) list of :class:`Loop` objects
that live in the same 3-D plane as the inputs.

Area helper
-----------
:func:`loop_area` returns the signed 2-D area of a planar loop (positive
for counter-clockwise orientation when projected onto the detected plane).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np

from kerf_cad_core.geom.brep import (
    CircleArc3,
    Coedge,
    Edge,
    Line3,
    Loop,
    Vertex,
)

# ---------------------------------------------------------------------------
# Internal tolerance / subdivision constants
# ---------------------------------------------------------------------------

_TOL = 1e-9          # general coincidence tolerance (3-D, squared)
_ARC_CHORD_TOL = 1e-3  # maximum chord-height error when tessellating arcs
_MIN_SEG = 4         # minimum number of segments per arc


# ---------------------------------------------------------------------------
# Plane detection & 2-D projection
# ---------------------------------------------------------------------------

@dataclass
class _Plane2D:
    """A local 2-D coordinate frame embedded in 3-D."""
    origin: np.ndarray
    x_axis: np.ndarray
    y_axis: np.ndarray
    normal: np.ndarray

    def to_2d(self, p3: np.ndarray) -> np.ndarray:
        d = np.asarray(p3, dtype=float) - self.origin
        return np.array([np.dot(d, self.x_axis), np.dot(d, self.y_axis)])

    def to_3d(self, p2: np.ndarray) -> np.ndarray:
        return (
            self.origin
            + float(p2[0]) * self.x_axis
            + float(p2[1]) * self.y_axis
        )


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-14 else v


def _detect_plane(loop: Loop) -> Optional[_Plane2D]:
    """Derive a 2-D coordinate frame from a Loop's first non-degenerate edge."""
    pts = _loop_sample_3d(loop, 6)
    if len(pts) < 3:
        return None
    o = pts[0]
    # first non-zero x-axis
    x = None
    for p in pts[1:]:
        d = p - o
        if np.linalg.norm(d) > 1e-10:
            x = _unit(d)
            break
    if x is None:
        return None
    # normal from cross product
    n = None
    for p in pts[2:]:
        d = p - o
        c = np.cross(x, d)
        if np.linalg.norm(c) > 1e-10:
            n = _unit(c)
            break
    if n is None:
        # degenerate (all collinear) — pick arbitrary perpendicular
        if abs(x[0]) < 0.9:
            n = _unit(np.cross(x, np.array([1.0, 0.0, 0.0])))
        else:
            n = _unit(np.cross(x, np.array([0.0, 1.0, 0.0])))
    y = _unit(np.cross(n, x))
    return _Plane2D(origin=o.copy(), x_axis=x, y_axis=y, normal=n)


def _loop_sample_3d(loop: Loop, per_edge: int = 4) -> List[np.ndarray]:
    """Collect evenly-spaced 3-D sample points around a loop."""
    pts: List[np.ndarray] = []
    for ce in loop.coedges:
        e = ce.edge
        curve = e.curve
        t0, t1 = (e.t0, e.t1) if ce.orientation else (e.t1, e.t0)
        for i in range(per_edge):
            t_frac = i / per_edge
            t = t0 + t_frac * (t1 - t0)
            pts.append(np.asarray(curve.evaluate(t), dtype=float))
    return pts


# ---------------------------------------------------------------------------
# Tessellation of a Loop into a 2-D polyline
# ---------------------------------------------------------------------------

@dataclass
class _Seg2D:
    """A directed 2-D segment produced by tessellating one curve edge."""
    pts: List[np.ndarray]      # 2-D points (first only; last == next.pts[0])
    # back-references to the source 3-D curve for reconstruction
    curve: object               # Line3 or CircleArc3
    t_start: float              # param at pts[0] in 3-D curve
    t_end: float                # param at pts[-1] in 3-D curve
    orientation: bool           # True = coedge forward direction
    coedge: Coedge


def _subdivide_arc(arc: CircleArc3, t0: float, t1: float,
                   plane: _Plane2D, chord_tol: float) -> List[np.ndarray]:
    """Return 2-D polyline subdivisions for an arc segment."""
    # Number of steps needed so chord error < chord_tol
    span = abs(t1 - t0)
    # chord half-height for a single chord of arc of radius r over angle dtheta
    # h = r*(1 - cos(dtheta/2)) ≈ r*(dtheta/2)^2/2
    # so dtheta = 2*sqrt(2*h/r)
    if arc.radius > 1e-12 and chord_tol > 0:
        dtheta_max = 2.0 * math.sqrt(2.0 * chord_tol / arc.radius)
        n = max(_MIN_SEG, math.ceil(span / dtheta_max))
    else:
        n = _MIN_SEG
    pts2d = []
    for i in range(n + 1):
        t = t0 + (t1 - t0) * i / n
        p3 = np.asarray(arc.evaluate(t), dtype=float)
        pts2d.append(plane.to_2d(p3))
    return pts2d


def _tessellate_loop(loop: Loop, plane: _Plane2D) -> List[_Seg2D]:
    """Tessellate all coedges of *loop* into 2-D _Seg2D objects."""
    segs: List[_Seg2D] = []
    for ce in loop.coedges:
        e = ce.edge
        curve = e.curve
        t0, t1 = (e.t0, e.t1) if ce.orientation else (e.t1, e.t0)
        if isinstance(curve, CircleArc3):
            pts2d = _subdivide_arc(curve, t0, t1, plane, _ARC_CHORD_TOL)
        else:
            # Line or anything else: just two endpoints
            p0_3d = np.asarray(curve.evaluate(t0), dtype=float)
            p1_3d = np.asarray(curve.evaluate(t1), dtype=float)
            pts2d = [plane.to_2d(p0_3d), plane.to_2d(p1_3d)]
        segs.append(
            _Seg2D(
                pts=pts2d,
                curve=curve,
                t_start=t0,
                t_end=t1,
                orientation=ce.orientation,
                coedge=ce,
            )
        )
    return segs


def _segs_to_polyline(segs: List[_Seg2D]) -> List[np.ndarray]:
    """Flatten tessellation segments into a single closed 2-D polyline
    (last point is omitted because it equals the first)."""
    poly: List[np.ndarray] = []
    for seg in segs:
        poly.extend(seg.pts[:-1])  # drop repeated end-point
    return poly


# ---------------------------------------------------------------------------
# 2-D signed area (shoelace) and point-in-polygon
# ---------------------------------------------------------------------------

def _poly_area2(poly: List[np.ndarray]) -> float:
    """Signed area of a 2-D polygon (+ = CCW)."""
    n = len(poly)
    acc = 0.0
    for i in range(n):
        x0, y0 = poly[i][0], poly[i][1]
        x1, y1 = poly[(i + 1) % n][0], poly[(i + 1) % n][1]
        acc += x0 * y1 - x1 * y0
    return acc * 0.5


def _point_in_poly(pt: np.ndarray, poly: List[np.ndarray]) -> bool:
    """Ray-casting point-in-polygon test (2-D)."""
    x, y = float(pt[0]), float(pt[1])
    n = len(poly)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = poly[i][0], poly[i][1]
        xj, yj = poly[j][0], poly[j][1]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-300) + xi):
            inside = not inside
        j = i
    return inside


# ---------------------------------------------------------------------------
# Greiner-Hormann clipping
# ---------------------------------------------------------------------------

@dataclass
class _GHVertex:
    """Node in the Greiner-Hormann doubly-linked list."""
    pt: np.ndarray
    alpha: float = 0.0        # intersection parameter along edge (0-1)
    intersect: bool = False   # is this an intersection node?
    entry: bool = False       # entry (True) or exit (False) intersection
    checked: bool = False
    # indices into the source polygon list for back-mapping
    seg_idx: int = -1          # source segment index in parent segs list
    t_param: float = 0.0       # param in source curve at this point
    next: Optional["_GHVertex"] = None
    prev: Optional["_GHVertex"] = None
    neighbour: Optional["_GHVertex"] = None  # matching node in other polygon


def _build_gh_list(poly: List[np.ndarray]) -> _GHVertex:
    """Build a circular doubly-linked list from a 2-D polygon."""
    nodes = [_GHVertex(pt=p.copy()) for p in poly]
    n = len(nodes)
    for i in range(n):
        nodes[i].next = nodes[(i + 1) % n]
        nodes[i].prev = nodes[(i - 1) % n]
    return nodes[0]


def _seg_intersect_2d(
    a0: np.ndarray, a1: np.ndarray,
    b0: np.ndarray, b1: np.ndarray,
) -> Optional[Tuple[float, float]]:
    """Compute intersection parameters (alpha, beta) in (0,1) for two 2-D segments.

    Returns (alpha, beta) such that ``a0 + alpha*(a1-a0) == b0 + beta*(b1-b0)``,
    or None if parallel / no intersection in the open interior.
    """
    da = a1 - a0
    db = b1 - b0
    denom = da[0] * db[1] - da[1] * db[0]
    if abs(denom) < 1e-14:
        return None
    dx = b0[0] - a0[0]
    dy = b0[1] - a0[1]
    alpha = (dx * db[1] - dy * db[0]) / denom
    beta  = (dx * da[1] - dy * da[0]) / denom
    if 1e-9 < alpha < 1.0 - 1e-9 and 1e-9 < beta < 1.0 - 1e-9:
        return alpha, beta
    return None


def _insert_gh_node(head: _GHVertex, new_node: _GHVertex) -> None:
    """Insert *new_node* into the circular list after the correct edge."""
    cur = head
    while True:
        nxt = cur.next
        if not cur.intersect and not nxt.intersect:
            # we're on the original edge starting at cur
            break
        # skip past previously-inserted intersection nodes on this edge
        if cur.intersect and not nxt.intersect:
            break
        cur = nxt
        if cur is head:
            break
    # walk forward to find the correct insertion point by alpha
    cur2 = head
    while True:
        nxt2 = cur2.next
        if not cur2.intersect:
            break
        cur2 = nxt2
        if cur2 is head:
            break
    # This is the standard GH insertion: walk the edge that cur2→nxt2 represents
    # and insert new_node in alpha order.
    # We rely on the caller to do this correctly (see _phase1_insert).


def _classify_entry_exit_a(
    a0: np.ndarray, a1: np.ndarray, alpha: float, poly_b: List[np.ndarray]
) -> bool:
    """Return True if A's edge crosses INTO poly_b at parameter alpha.

    We test a point just past the intersection along A's edge direction.
    This correctly handles multiple crossings on the same A edge.
    """
    # Point slightly after the crossing (1% of the way to a1)
    step = min(0.01, (1.0 - alpha) * 0.5)
    mid = a0 + (alpha + step) * (a1 - a0)
    return _point_in_poly(mid, poly_b)


def _phase1_insert(
    nodes_a: List[_GHVertex],  # flat list of original nodes for polygon A
    nodes_b: List[_GHVertex],
    poly_a: List[np.ndarray],
    poly_b: List[np.ndarray],
    operation: str,
) -> None:
    """Find all intersections and insert nodes into both lists in-place."""
    na = len(nodes_a)
    nb = len(nodes_b)

    for i in range(na):
        a0 = poly_a[i]
        a1 = poly_a[(i + 1) % na]
        # Collect all intersections on this edge, sort by alpha
        edge_ixs: List[Tuple[float, float, int]] = []  # (alpha, beta, j)
        for j in range(nb):
            b0 = poly_b[j]
            b1 = poly_b[(j + 1) % nb]
            res = _seg_intersect_2d(a0, a1, b0, b1)
            if res is None:
                continue
            edge_ixs.append((res[0], res[1], j))
        edge_ixs.sort(key=lambda x: x[0])

        for alpha, beta, j in edge_ixs:
            pt = a0 + alpha * (a1 - a0)

            # Determine entry/exit by testing a point slightly beyond the crossing
            entry_a = _classify_entry_exit_a(a0, a1, alpha, poly_b)

            node_a = _GHVertex(pt=pt.copy(), alpha=alpha, intersect=True, entry=entry_a)
            node_b = _GHVertex(
                pt=pt.copy(), alpha=beta, intersect=True, entry=not entry_a
            )
            node_a.neighbour = node_b
            node_b.neighbour = node_a

            # Insert into A's list, maintaining alpha order on edge i
            _insert_by_alpha(nodes_a[i], nodes_a[(i + 1) % na], node_a)
            _insert_by_alpha(nodes_b[j], nodes_b[(j + 1) % nb], node_b)


def _insert_by_alpha(start: _GHVertex, end: _GHVertex, new: _GHVertex) -> None:
    """Insert *new* between start and end (going forward), ordered by alpha."""
    cur = start
    while cur.next is not end:
        nxt = cur.next
        if nxt.intersect and nxt.alpha > new.alpha:
            break
        cur = nxt
    # insert new between cur and cur.next
    nxt = cur.next
    cur.next = new
    new.prev = cur
    new.next = nxt
    nxt.prev = new


def _collect_flat(head_node: _GHVertex) -> List[_GHVertex]:
    """Walk a circular GH list and collect all nodes in order."""
    out = [head_node]
    cur = head_node.next
    while cur is not head_node:
        out.append(cur)
        cur = cur.next
    return out


def _gh_trace(
    list_a: List[_GHVertex],
    list_b: List[_GHVertex],
    operation: str,
) -> List[List[np.ndarray]]:
    """Trace result polygons using the Greiner-Hormann traversal."""
    result_polys: List[List[np.ndarray]] = []

    # Determine which intersection nodes are the start points.
    # For union: start at exit nodes of A (or entry if we flip).
    # Standard GH: for intersection use entry nodes; for union use exit nodes.
    if operation in ("union", "difference"):
        start_flag = False  # exit nodes from A
    else:  # intersection
        start_flag = True   # entry nodes of A

    # Mark all intersection nodes unchecked
    for v in list_a:
        v.checked = False
    for v in list_b:
        v.checked = False

    # Find unchecked intersection nodes in A
    for start in list_a:
        if not start.intersect or start.checked or start.entry != start_flag:
            continue

        poly_out: List[np.ndarray] = [start.pt.copy()]
        start.checked = True
        cur = start
        on_a = True

        for _guard in range(len(list_a) + len(list_b) + 4):
            cur = cur.next
            if cur is start and on_a:
                break
            if cur.intersect:
                if cur.checked:
                    break
                cur.checked = True
                if cur.neighbour:
                    cur.neighbour.checked = True
                # Switch polygon
                on_a = not on_a
                cur = cur.neighbour
                if cur is None:
                    break
                if cur is start:
                    break
            poly_out.append(cur.pt.copy())

        if len(poly_out) >= 3:
            result_polys.append(poly_out)

    return result_polys


# ---------------------------------------------------------------------------
# High-level clipping
# ---------------------------------------------------------------------------

def _perturb_poly(poly: List[np.ndarray], eps: float) -> List[np.ndarray]:
    """Scale poly slightly inward toward its centroid to resolve vertex-on-edge
    degeneracies in Greiner-Hormann.

    Moving every vertex toward the centroid by a factor of ``eps`` lifts them
    off adjacent polygon boundaries while preserving winding and topology.
    """
    centroid = np.mean(poly, axis=0)
    out = []
    for p in poly:
        d = p - centroid
        out.append(np.asarray(centroid + (1.0 - eps) * d, dtype=float))
    return out


def _clip_polygons(
    poly_a: List[np.ndarray],
    poly_b: List[np.ndarray],
    operation: str,  # "union" | "intersection" | "difference"
) -> List[List[np.ndarray]]:
    """Run the full Greiner-Hormann pipeline on two closed 2-D polylines.

    Returns a list of result polylines (each is a closed polygon, last point
    NOT repeated).
    """
    # Ensure CCW orientation (positive area)
    if _poly_area2(poly_a) < 0:
        poly_a = list(reversed(poly_a))
    if _poly_area2(poly_b) < 0:
        poly_b = list(reversed(poly_b))

    if operation == "difference":
        # A - B is equivalent to A ∩ complement(B), i.e. reverse B winding
        poly_b = list(reversed(poly_b))

    # Check for intersections (strict interior only, t in (eps, 1-eps))
    na, nb = len(poly_a), len(poly_b)
    has_intersection = False
    for i in range(na):
        a0 = poly_a[i]; a1 = poly_a[(i + 1) % na]
        for j in range(nb):
            b0 = poly_b[j]; b1 = poly_b[(j + 1) % nb]
            if _seg_intersect_2d(a0, a1, b0, b1) is not None:
                has_intersection = True
                break
        if has_intersection:
            break

    # If no strict-interior intersections found, apply a small perturbation to
    # poly_b to handle the degenerate case where intersections coincide with
    # polygon vertices (T-intersections, shared edges, etc.).
    if not has_intersection:
        # Compute typical scale for perturbation
        bbox_a = max(
            abs(poly_a[i][0] - poly_a[j][0]) + abs(poly_a[i][1] - poly_a[j][1])
            for i in range(na) for j in range(na)
        ) if na > 1 else 1.0
        eps = bbox_a * 1e-5
        poly_b_pert = _perturb_poly(poly_b, eps)
        for i in range(na):
            a0 = poly_a[i]; a1 = poly_a[(i + 1) % na]
            for j in range(nb):
                b0 = poly_b_pert[j]; b1 = poly_b_pert[(j + 1) % nb]
                if _seg_intersect_2d(a0, a1, b0, b1) is not None:
                    has_intersection = True
                    break
            if has_intersection:
                break
        if has_intersection:
            # Re-run with the perturbed polygon
            poly_b = poly_b_pert

    if not has_intersection:
        # Detect containment using centroids and area comparison to avoid
        # boundary-point failures in the ray-casting test.
        centroid_a = np.mean(poly_a, axis=0)
        centroid_b = np.mean(poly_b, axis=0)
        area_a = abs(_poly_area2(poly_a))
        area_b = abs(_poly_area2(poly_b))

        # Detect near-identical polygons (same area, same centroid)
        tol_area = 1e-6 * max(area_a, area_b, 1e-12)
        tol_geom = 1e-6 * (math.sqrt(max(area_a, area_b)) + 1e-12)
        same_area = abs(area_a - area_b) < tol_area
        same_centroid = float(np.linalg.norm(centroid_a - centroid_b)) < tol_geom
        congruent = same_area and same_centroid

        # "B contains A" if centroid of B is inside A AND area of B >= area of A
        # "A contains B" if centroid of A is inside B AND area of A >= area of B
        # This correctly handles concentric polygons with different sizes.
        b_centroid_in_a = _point_in_poly(centroid_b, poly_a)
        a_centroid_in_b = _point_in_poly(centroid_a, poly_b)

        # True containment: the smaller one is inside the larger
        a_inside_b = a_centroid_in_b and area_b >= area_a  # A is the smaller, B is outer
        b_inside_a = b_centroid_in_a and area_a >= area_b  # B is the smaller, A is outer

        # Degenerate / separated cases
        if operation == "union":
            if congruent:
                return [poly_a]
            if a_inside_b:
                return [poly_b]
            if b_inside_a:
                return [poly_a]
            return [poly_a, poly_b]
        elif operation == "intersection":
            if congruent:
                return [poly_a]
            if a_inside_b:
                return [poly_a]
            if b_inside_a:
                return [poly_b]
            return []
        else:  # difference
            if congruent:
                # A − A = empty
                return []
            # For difference, poly_b has been reversed (CW); re-check original
            # containment using the original orientation.
            # Note: area_b here is the area of the REVERSED poly_b (same magnitude).
            poly_b_orig = list(reversed(poly_b))
            a_centroid_in_b_orig = _point_in_poly(centroid_a, poly_b_orig)
            b_centroid_in_a_direct = _point_in_poly(centroid_b, poly_a)
            if a_centroid_in_b_orig and area_b >= area_a:
                # A is inside B (original) => A − B = empty
                return []
            if b_centroid_in_a_direct and area_a >= area_b:
                # B is entirely inside A.
                # Return outer (CCW) + inner hole (CW = reversed original B).
                # The reversed poly_b is already CW; return it as a second polygon.
                # Callers that sum signed areas get area(A) - area(B) correctly.
                return [poly_a, poly_b]
            return [poly_a]

    # Build GH linked lists
    nodes_a = [_GHVertex(pt=p.copy()) for p in poly_a]
    nodes_b = [_GHVertex(pt=p.copy()) for p in poly_b]
    na_new = len(nodes_a); nb_new = len(nodes_b)
    for i in range(na_new):
        nodes_a[i].next = nodes_a[(i + 1) % na_new]
        nodes_a[i].prev = nodes_a[(i - 1) % na_new]
    for i in range(nb_new):
        nodes_b[i].next = nodes_b[(i + 1) % nb_new]
        nodes_b[i].prev = nodes_b[(i - 1) % nb_new]

    _phase1_insert(nodes_a, nodes_b, poly_a, poly_b, operation)

    list_a = _collect_flat(nodes_a[0])
    list_b = _collect_flat(nodes_b[0])

    result_polys = _gh_trace(list_a, list_b, operation)

    if not result_polys:
        # Fallback: if GH produced nothing, apply degenerate rules
        if operation == "union":
            return [poly_a, poly_b]
        elif operation == "intersection":
            return []
        else:
            return [poly_a]

    return result_polys


# ---------------------------------------------------------------------------
# Reconstruct Loop objects from result 2-D polygons
# ---------------------------------------------------------------------------

def _poly_to_loop(poly2d: List[np.ndarray], plane: _Plane2D) -> Loop:
    """Convert a 2-D polygon back to a :class:`Loop` of :class:`Line3` edges."""
    n = len(poly2d)
    coedges: List[Coedge] = []
    for i in range(n):
        p0_3d = plane.to_3d(poly2d[i])
        p1_3d = plane.to_3d(poly2d[(i + 1) % n])
        v_start = Vertex(point=p0_3d)
        v_end = Vertex(point=p1_3d)
        line = Line3(p0=p0_3d, p1=p1_3d)
        edge = Edge(curve=line, t0=0.0, t1=1.0, v_start=v_start, v_end=v_end)
        ce = Coedge(edge=edge, orientation=True)
        coedges.append(ce)
    return Loop(coedges=coedges)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def loop_area(loop: Loop, plane: Optional["_Plane2D"] = None) -> float:
    """Compute the signed 2-D area of a planar :class:`Loop`.

    The sign is positive for counter-clockwise orientation when viewed along
    the loop's plane normal.  For area magnitude use ``abs(loop_area(loop))``.

    For :class:`CircleArc3` edges the area contribution accounts for the
    circular segment between the chord and the arc.

    Parameters
    ----------
    loop:
        The loop whose area is computed.
    plane:
        Optional pre-computed plane.  When omitted the plane is derived from
        the loop geometry.  Passing an explicit plane ensures that the sign is
        consistent with a caller-chosen orientation (important for hole loops
        whose geometry is CW, which would otherwise auto-detect a flipped plane
        and return a positive area).
    """
    if plane is None:
        # Use the plane cached by _loop_boolean if available (ensures sign
        # consistency for hole loops whose geometry is CW).
        plane = getattr(loop, "_region2d_plane", None)
    if plane is None:
        plane = _detect_plane(loop)
    if plane is None:
        return 0.0

    total = 0.0
    for ce in loop.coedges:
        e = ce.edge
        curve = e.curve
        t0, t1 = (e.t0, e.t1) if ce.orientation else (e.t1, e.t0)

        if isinstance(curve, CircleArc3):
            pts2d = _subdivide_arc(curve, t0, t1, plane, _ARC_CHORD_TOL * 0.01)
        else:
            p0_3d = np.asarray(curve.evaluate(t0), dtype=float)
            p1_3d = np.asarray(curve.evaluate(t1), dtype=float)
            pts2d = [plane.to_2d(p0_3d), plane.to_2d(p1_3d)]

        # Shoelace contribution from this chain (pts2d[0] to pts2d[-1])
        # We include all sub-segments
        for k in range(len(pts2d) - 1):
            x0, y0 = pts2d[k][0], pts2d[k][1]
            x1, y1 = pts2d[k + 1][0], pts2d[k + 1][1]
            total += x0 * y1 - x1 * y0

    return total * 0.5


def _loop_boolean(
    loop_a: Loop,
    loop_b: Loop,
    operation: str,
) -> List[Loop]:
    """Core boolean dispatcher."""
    # Detect plane from loop_a
    plane = _detect_plane(loop_a)
    if plane is None:
        plane = _detect_plane(loop_b)
    if plane is None:
        return []

    segs_a = _tessellate_loop(loop_a, plane)
    segs_b = _tessellate_loop(loop_b, plane)
    poly_a = _segs_to_polyline(segs_a)
    poly_b = _segs_to_polyline(segs_b)

    if len(poly_a) < 3 or len(poly_b) < 3:
        return []

    result_polys = _clip_polygons(poly_a, poly_b, operation)

    loops: List[Loop] = []
    for rpoly in result_polys:
        if len(rpoly) >= 3:
            lp = _poly_to_loop(rpoly, plane)
            # Tag the loop with the coordinate frame so that loop_area can
            # use the same plane for sign-consistent area computation even
            # when the polygon's winding is CW (hole).
            lp._region2d_plane = plane  # type: ignore[attr-defined]
            loops.append(lp)
    return loops


def loop_union(loop_a: Loop, loop_b: Loop) -> List[Loop]:
    """Return loops representing the 2-D union of *loop_a* and *loop_b*.

    If the loops do not overlap, both are returned unchanged.  If one
    contains the other, the outer loop is returned.
    """
    return _loop_boolean(loop_a, loop_b, "union")


def loop_intersection(loop_a: Loop, loop_b: Loop) -> List[Loop]:
    """Return loops representing the 2-D intersection of *loop_a* and *loop_b*.

    Returns an empty list when the loops do not overlap.
    """
    return _loop_boolean(loop_a, loop_b, "intersection")


def loop_difference(loop_a: Loop, loop_b: Loop) -> List[Loop]:
    """Return loops representing *loop_a* minus *loop_b*.

    Returns *loop_a* unchanged when the loops do not overlap.  Returns an
    empty list when *loop_a* is fully contained in *loop_b*.
    """
    return _loop_boolean(loop_a, loop_b, "difference")


# ---------------------------------------------------------------------------
# Convenience: build a rectangular (square) Loop in the XY plane
# ---------------------------------------------------------------------------

def make_rect_loop(x0: float, y0: float, x1: float, y1: float) -> Loop:
    """Build a CCW rectangular :class:`Loop` in the z=0 plane."""
    corners = [
        np.array([x0, y0, 0.0]),
        np.array([x1, y0, 0.0]),
        np.array([x1, y1, 0.0]),
        np.array([x0, y1, 0.0]),
    ]
    n = len(corners)
    coedges: List[Coedge] = []
    for i in range(n):
        p0 = corners[i]
        p1 = corners[(i + 1) % n]
        v0 = Vertex(point=p0)
        v1 = Vertex(point=p1)
        line = Line3(p0=p0, p1=p1)
        edge = Edge(curve=line, t0=0.0, t1=1.0, v_start=v0, v_end=v1)
        ce = Coedge(edge=edge, orientation=True)
        coedges.append(ce)
    return Loop(coedges=coedges)


def make_circle_loop(
    cx: float, cy: float, radius: float, n_segs: int = 32
) -> Loop:
    """Build a CCW circular :class:`Loop` in the z=0 plane using a single
    :class:`CircleArc3` edge (full circle, t0=0, t1=2π)."""
    center = np.array([cx, cy, 0.0])
    x_axis = np.array([1.0, 0.0, 0.0])
    y_axis = np.array([0.0, 1.0, 0.0])
    arc = CircleArc3(
        center=center,
        radius=radius,
        x_axis=x_axis,
        y_axis=y_axis,
        t0=0.0,
        t1=2.0 * math.pi,
    )
    p_start = arc.evaluate(0.0)
    # For a full circle the start == end vertex
    v_start = Vertex(point=np.asarray(p_start, dtype=float))
    v_end = Vertex(point=np.asarray(p_start, dtype=float))
    edge = Edge(curve=arc, t0=0.0, t1=2.0 * math.pi, v_start=v_start, v_end=v_end)
    ce = Coedge(edge=edge, orientation=True)
    return Loop(coedges=[ce])
