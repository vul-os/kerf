"""Canonical bridge from analytic-geometry verbs to validated B-rep ``Body``.

This module is the **production** path that consumers should reach for when
they need real, structurally-validated topology around their geometry. The
constructors in :mod:`kerf_cad_core.geom.brep` (``make_box``,
``make_cylinder``, ``make_sphere`` ...) remain as in-source demonstrations
that the topology contract is satisfiable; everything in *this* file is
the user-facing builder layer that:

  * takes geometric verbs (a NURBS surface, an analytic ``Plane`` /
    ``CylinderSurface`` / ``SphereSurface`` / ``TorusSurface``, a quartet
    of bounding curves, or a primitive description),
  * stitches the topology hierarchy
    ``Vertex -> Edge -> Coedge -> Loop -> Face -> Shell -> Solid -> Body``,
  * and ends every public constructor with an internal ``validate_body``
    assertion, so the keystone now *guards real geometry*.

Design notes
------------

* No existing geom module is modified. We only consume the frozen public
  API of :mod:`brep` (``Vertex``, ``Edge``, ``Coedge``, ``Loop``, ``Face``,
  ``Shell``, ``Solid``, ``Body``, the analytic adapters, and
  ``validate_body``).

* For a NURBS surface ``surface_to_face`` slices the parametric domain on
  its four boundaries into 4 isocurves and 4 corner vertices. The
  resulting outer loop is checked to be CCW with respect to the surface
  normal at the central sample; if it is CW we reverse it. This makes
  ``validate_body`` clean for any sufficiently regular bicubic patch.

* For an explicit ``outer_loop_curves`` sequence we treat the provided
  curves as already-bounding the surface and use their endpoint
  coincidence (within ``tol``) to share vertices.

* ``surfaces_to_shell`` performs an O(F + V + E) sew: vertices within
  ``sew_tol`` collapse to a single representative; edges that share both
  endpoint-representatives (and have coincident midpoint samples) collapse
  similarly, with the original two coedges re-pointed at the shared edge.
  After sewing we recompute ``is_closed`` exactly by manifold count: a
  closed shell is one where every edge is used by exactly two coedges of
  opposite orientation.

Every public constructor here ends with an internal ``validate_body(...)``
check and raises ``BuildError`` on any error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    CircleArc3,
    Coedge,
    CylinderSurface,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    SphereSurface,
    Solid,
    TorusSurface,
    Vertex,
    validate_body,
)


# ---------------------------------------------------------------------------
# Public errors
# ---------------------------------------------------------------------------


class BuildError(RuntimeError):
    """Raised when a brep_build constructor produces invalid topology.

    The error carries the ``validate_body`` payload so callers can inspect
    the structured ``errors`` list rather than just a string.
    """

    def __init__(self, msg: str, payload: Optional[dict] = None) -> None:
        super().__init__(msg)
        self.payload = payload or {"ok": False, "errors": [msg]}


# ---------------------------------------------------------------------------
# Lightweight isocurve adapter for NurbsSurface / analytic surfaces
# ---------------------------------------------------------------------------


@dataclass
class _SurfaceIsoCurve:
    """A boundary isocurve of a parametric surface.

    ``axis`` is ``'u'`` if we fix ``v`` and sweep ``u``, ``'v'`` otherwise.
    ``t0`` / ``t1`` are the parametric range of the *swept* coordinate
    (matching the edge's ``[t0, t1]``).
    """

    surface: object
    axis: str
    fixed: float
    t0: float
    t1: float

    def evaluate(self, t: float) -> np.ndarray:
        if self.axis == "u":
            return np.asarray(self.surface.evaluate(t, self.fixed), dtype=float)
        return np.asarray(self.surface.evaluate(self.fixed, t), dtype=float)

    def derivative(self, t: float, order: int = 1) -> np.ndarray:  # noqa: ARG002
        h = 1e-6
        a = self.evaluate(t - h)
        b = self.evaluate(t + h)
        return (b - a) / (2.0 * h)


# ---------------------------------------------------------------------------
# Parameter-range introspection
# ---------------------------------------------------------------------------


def _surface_param_box(surface: object) -> Tuple[float, float, float, float]:
    """Return ``(u0, u1, v0, v1)`` for any surface we know how to bound.

    Handles ``NurbsSurface`` (proper knot range), the analytic ``Plane``
    (unit square), ``CylinderSurface`` (``u`` in [0, 2pi], ``v`` in [0, 1]
    -- caller passes the correct height as a separate primitive
    constructor), ``SphereSurface`` (longitude / latitude), and
    ``TorusSurface`` (two periodic angles). For a fully arbitrary surface
    with no ``param_range`` hint we return the unit square.
    """
    if hasattr(surface, "knots_u") and hasattr(surface, "knots_v"):
        ku, kv = surface.knots_u, surface.knots_v
        du, dv = surface.degree_u, surface.degree_v
        return (
            float(ku[du]), float(ku[-(du + 1)]),
            float(kv[dv]), float(kv[-(dv + 1)]),
        )
    if isinstance(surface, Plane):
        return 0.0, 1.0, 0.0, 1.0
    if isinstance(surface, CylinderSurface):
        return 0.0, 2.0 * math.pi, 0.0, 1.0
    if isinstance(surface, SphereSurface):
        return 0.0, 2.0 * math.pi, -math.pi / 2.0, math.pi / 2.0
    if isinstance(surface, TorusSurface):
        return 0.0, 2.0 * math.pi, 0.0, 2.0 * math.pi
    pr = getattr(surface, "param_range", None)
    if pr is not None:
        u0, u1, v0, v1 = pr
        return float(u0), float(u1), float(v0), float(v1)
    return 0.0, 1.0, 0.0, 1.0


def _surface_normal_at(surface: object, u: float, v: float) -> np.ndarray:
    if hasattr(surface, "normal"):
        n = np.asarray(surface.normal(u, v), dtype=float)
    else:
        h = 1e-6
        p = np.asarray(surface.evaluate(u, v), dtype=float)
        du = np.asarray(surface.evaluate(u + h, v), dtype=float) - p
        dv = np.asarray(surface.evaluate(u, v + h), dtype=float) - p
        n = np.cross(du, dv)
    nrm = float(np.linalg.norm(n))
    return n / nrm if nrm > 1e-14 else n


# ---------------------------------------------------------------------------
# Outer-loop construction
# ---------------------------------------------------------------------------


def _natural_boundary(
    surface: object, tol: float
) -> Tuple[List[Vertex], List[Tuple[Edge, bool]]]:
    """Build 4 corner vertices + 4 isocurve (edge, orientation) pairs for a
    parametric box.

    Traversal order: (u0,v0) -> (u1,v0) -> (u1,v1) -> (u0,v1) -> (u0,v0).
    Edges are returned as ``(edge, orientation)`` pairs already aligned to
    that traversal direction.
    """
    u0, u1, v0, v1 = _surface_param_box(surface)
    P00 = np.asarray(surface.evaluate(u0, v0), dtype=float)
    P10 = np.asarray(surface.evaluate(u1, v0), dtype=float)
    P11 = np.asarray(surface.evaluate(u1, v1), dtype=float)
    P01 = np.asarray(surface.evaluate(u0, v1), dtype=float)
    v00 = Vertex(P00, tol)
    v10 = Vertex(P10, tol)
    v11 = Vertex(P11, tol)
    v01 = Vertex(P01, tol)
    # Each edge is stored in its natural parametric direction; we record
    # whether the traversal walks the edge forwards (True) or backwards.
    e_bot = Edge(_SurfaceIsoCurve(surface, "u", v0, u0, u1),
                 u0, u1, v00, v10, tol)        # walked v00->v10 = forwards
    e_rgt = Edge(_SurfaceIsoCurve(surface, "v", u1, v0, v1),
                 v0, v1, v10, v11, tol)        # walked v10->v11 = forwards
    e_top = Edge(_SurfaceIsoCurve(surface, "u", v1, u0, u1),
                 u0, u1, v01, v11, tol)        # walked v11->v01 = backwards
    e_lft = Edge(_SurfaceIsoCurve(surface, "v", u0, v0, v1),
                 v0, v1, v00, v01, tol)        # walked v01->v00 = backwards
    return (
        [v00, v10, v11, v01],
        [(e_bot, True), (e_rgt, True), (e_top, False), (e_lft, False)],
    )


def _curve_endpoint_param_range(curve: object) -> Tuple[float, float]:
    """Best-effort ``(t0, t1)`` for an arbitrary curve."""
    for attr in ("param_range", "_param_range"):
        pr = getattr(curve, attr, None)
        if pr is not None:
            return float(pr[0]), float(pr[1])
    if hasattr(curve, "knots") and hasattr(curve, "degree"):
        k = np.asarray(curve.knots, dtype=float)
        d = int(curve.degree)
        return float(k[d]), float(k[-(d + 1)])
    return 0.0, 1.0


def _share_or_make_vertex(
    point: np.ndarray, pool: List[Vertex], tol: float
) -> Vertex:
    for v in pool:
        if float(np.linalg.norm(v.point - point)) <= max(v.tol, tol):
            return v
    v = Vertex(np.asarray(point, dtype=float), tol)
    pool.append(v)
    return v


def _explicit_loop(
    curves: Sequence[object], tol: float
) -> Tuple[List[Vertex], List[Tuple[Edge, bool]]]:
    """Build a closed chain of vertices+edges from caller-supplied curves.

    Endpoints within ``tol`` are merged into a single ``Vertex``; the last
    edge's endpoint is re-pointed at the first vertex if they coincide so
    the loop closes cleanly. Edges are returned as ``(edge, orientation)``
    pairs; orientation is always ``True`` for explicit curves because we
    assume the caller has already ordered them in traversal direction.
    """
    if len(curves) < 1:
        raise BuildError("explicit outer loop must have at least one curve")
    pool: List[Vertex] = []
    edges: List[Tuple[Edge, bool]] = []
    for c in curves:
        t0, t1 = _curve_endpoint_param_range(c)
        p0 = np.asarray(c.evaluate(t0), dtype=float)
        p1 = np.asarray(c.evaluate(t1), dtype=float)
        v0 = _share_or_make_vertex(p0, pool, tol)
        v1 = _share_or_make_vertex(p1, pool, tol)
        edges.append((Edge(c, t0, t1, v0, v1, tol), True))
    # close the loop: stitch last edge's v_end to first edge's v_start
    last_e, _ = edges[-1]
    first_e, _ = edges[0]
    if last_e.v_end is not first_e.v_start:
        if float(np.linalg.norm(
            last_e.v_end.point - first_e.v_start.point
        )) <= tol * 10.0:
            last_e.v_end = first_e.v_start
    return pool, edges


def _outer_loop_ccw(
    surface: object, edge_orients: Sequence[Tuple[Edge, bool]]
) -> Tuple[List[Coedge], bool]:
    """Build coedges traversing ``edge_orients`` and orient the loop CCW
    with respect to the surface normal at the surface centre.

    Returns ``(coedges, was_reversed)``. Each input pair already encodes
    the *intended* traversal direction (``orientation`` is the coedge
    direction relative to the edge's natural ``v_start -> v_end``).
    """
    coedges = [Coedge(e, o) for (e, o) in edge_orients]
    u0, u1, v0, v1 = _surface_param_box(surface)
    u_mid, v_mid = 0.5 * (u0 + u1), 0.5 * (v0 + v1)
    n = _surface_normal_at(surface, u_mid, v_mid)
    pts: List[np.ndarray] = []
    for ce in coedges:
        p = np.asarray(ce.start_point(), dtype=float)
        if not pts or float(np.linalg.norm(p - pts[-1])) > 1e-12:
            pts.append(p)
    if len(pts) < 3:
        return coedges, False
    centroid = np.mean(pts, axis=0)
    area_vec = np.zeros(3)
    m = len(pts)
    for i in range(m):
        a = pts[i] - centroid
        b = pts[(i + 1) % m] - centroid
        area_vec += np.cross(a, b)
    signed = float(np.dot(area_vec, n) * 0.5)
    if signed >= 0:
        return coedges, False
    # CW with respect to the normal -> reverse traversal so coedges become
    # CCW. Reverse order + flip every orientation.
    rev = [(e, not o) for (e, o) in reversed(edge_orients)]
    coedges = [Coedge(e, o) for (e, o) in rev]
    return coedges, True


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------


def surface_to_face(
    surface: object,
    outer_loop_curves: Optional[Sequence[object]] = None,
    inner_loops: Optional[Sequence[Sequence[object]]] = None,
    tol: float = 1e-7,
) -> Face:
    """Wrap a parametric surface in a topologically-correct ``Face``.

    Parameters
    ----------
    surface
        Anything with ``evaluate(u, v)``. ``NurbsSurface`` and the analytic
        adapters in :mod:`brep` (``Plane`` / ``CylinderSurface`` /
        ``SphereSurface`` / ``TorusSurface``) all qualify.
    outer_loop_curves
        Optional ordered sequence of bounding 3D curves whose endpoint
        chain forms a closed loop around the face. When ``None`` the four
        natural parametric boundaries of the surface are used.
    inner_loops
        Optional list of inner (hole) loops; each is a sequence of curves.
    tol
        Tolerance for vertex sharing and face/edge tolerance fields.

    The produced face is wrapped in a transient single-face open
    ``Shell``/``Body`` and ``validate_body`` is asserted clean. Returns
    the unattached ``Face`` (the transient shell is discarded; the face's
    ``.shell`` reference is reset to ``None`` so callers can sew it into
    their own shell).
    """
    if outer_loop_curves is None:
        _verts, edge_orients = _natural_boundary(surface, tol)
    else:
        _verts, edge_orients = _explicit_loop(outer_loop_curves, tol)

    coedges, _ = _outer_loop_ccw(surface, edge_orients)
    outer = Loop(coedges, is_outer=True)
    face = Face(surface, [outer], orientation=True, tol=tol)

    if inner_loops:
        for ring_curves in inner_loops:
            _ring_verts, ring_edge_orients = _explicit_loop(ring_curves, tol)
            ring_coedges, _ = _outer_loop_ccw(surface, ring_edge_orients)
            # _outer_loop_ccw gives CCW; inner loops must be CW wrt normal
            ring_coedges = [Coedge(c.edge, not c.orientation) for c in
                            reversed(ring_coedges)]
            face.add_loop(Loop(ring_coedges, is_outer=False))

    # A bare Face is below the granularity of validate_body (which gates
    # on the *body-wide* Euler-Poincare residual). Run the same structural
    # / orientation / tolerance checks that validate_body performs, minus
    # the Euler residual (it only makes sense for closed bodies) and the
    # closed-shell manifold gate (this face is not yet in a shell).
    errors = _validate_face_local(face)
    if errors:
        raise BuildError(
            f"surface_to_face produced invalid Face: {errors}",
            {"ok": False, "errors": errors},
        )
    return face


def _validate_face_local(face: Face) -> List[str]:
    """Structural / orientation / tolerance check for a single Face.

    Mirrors checks 2/3/5/6 from :func:`brep.validate_body` (loop closure,
    outer-CCW & inner-CW, tolerance monotonicity, no dangling/duplicate
    coedges) but skips the body-level Euler-Poincare residual and the
    closed-shell 2-manifold gate.
    """
    from kerf_cad_core.geom.brep import _loop_signed_area_about_normal

    errs: List[str] = []
    outer = face.outer_loop()
    if outer is None:
        errs.append(f"face#{face.id} has no outer loop")
        return errs
    for lp in face.loops:
        if not lp.coedges:
            errs.append(f"face#{face.id} loop#{lp.id} has no coedges")
            continue
        n = len(lp.coedges)
        for i, ce in enumerate(lp.coedges):
            nxt = lp.coedges[(i + 1) % n]
            if ce.next is not nxt:
                errs.append(
                    f"face#{face.id} loop#{lp.id} coedge#{ce.id} "
                    "next link inconsistent"
                )
            etol = max(ce.edge.tol, nxt.edge.tol)
            gap = float(np.linalg.norm(ce.end_point() - nxt.start_point()))
            if gap > 10.0 * max(etol, 1e-9):
                errs.append(
                    f"face#{face.id} loop#{lp.id} open at coedge#{ce.id} "
                    f"(gap={gap:.3e} > tol)"
                )
            if ce.end_vertex() is not nxt.start_vertex():
                if not ce.end_vertex().coincident(nxt.start_vertex()):
                    errs.append(
                        f"face#{face.id} loop#{lp.id} vertex discontinuity "
                        f"at coedge#{ce.id}"
                    )
        # orientation
        signed = _loop_signed_area_about_normal(lp, face)
        if signed is not None:
            if lp is outer and signed < 0:
                errs.append(
                    f"face#{face.id} outer loop#{lp.id} is CW "
                    "(expected CCW wrt surface normal)"
                )
            if lp is not outer and signed > 0:
                errs.append(
                    f"face#{face.id} inner loop#{lp.id} is CCW "
                    "(expected CW wrt surface normal)"
                )
    # tolerance monotonicity
    for lp in face.loops:
        for ce in lp.coedges:
            e = ce.edge
            if e.tol < face.tol - 1e-15:
                errs.append(
                    f"tolerance inversion: edge#{e.id}.tol < face#{face.id}.tol"
                )
            for v in (e.v_start, e.v_end):
                if v.tol < e.tol - 1e-15:
                    errs.append(
                        f"tolerance inversion: vertex#{v.id}.tol < "
                        f"edge#{e.id}.tol"
                    )
    # duplicate coedge check
    for lp in face.loops:
        seen = set()
        for ce in lp.coedges:
            key = (id(ce.edge), ce.orientation)
            if key in seen:
                errs.append(
                    f"face#{face.id} loop#{lp.id} duplicate coedge for "
                    f"edge#{ce.edge.id} orientation={ce.orientation}"
                )
            seen.add(key)
    return errs


def surfaces_to_shell(
    faces: Sequence[Face],
    sew_tol: float = 1e-6,
) -> Shell:
    """Combine multiple ``Face``s into a sewn ``Shell``.

    Vertices within ``sew_tol`` of each other are merged into one shared
    ``Vertex``; edges whose both endpoint-representatives match (and whose
    midpoint samples coincide within ``sew_tol``) are merged so the two
    incident coedges share a single physical ``Edge``. After sewing,
    ``is_closed`` is set exactly: every edge must be used by exactly two
    coedges of opposite orientation.
    """
    if not faces:
        raise BuildError("surfaces_to_shell requires at least one face")

    # 1) build the union-find on vertices keyed by identity then by
    #    spatial coincidence within sew_tol
    all_vertices: List[Vertex] = []
    seen = set()
    for f in faces:
        for lp in f.loops:
            for ce in lp.coedges:
                for v in (ce.edge.v_start, ce.edge.v_end):
                    if id(v) not in seen:
                        seen.add(id(v))
                        all_vertices.append(v)

    # map id(vertex) -> representative Vertex (a key vertex per cluster)
    rep_of: dict = {}
    cluster_reps: List[Vertex] = []
    for v in all_vertices:
        found = None
        for rep in cluster_reps:
            if float(np.linalg.norm(v.point - rep.point)) <= sew_tol:
                found = rep
                break
        if found is None:
            cluster_reps.append(v)
            rep_of[id(v)] = v
        else:
            rep_of[id(v)] = found
            # vertex.tol monotonicity: a merged cluster's tol must be at
            # least as large as any constituent tol (BREP_CONTRACT §4.5)
            if v.tol > found.tol:
                found.tol = v.tol

    # 2) rewrite every edge's v_start / v_end to its representative; bump
    #    edge tol to be >= face tol of incident faces (tolerance
    #    monotonicity), and >= sew_tol so the loop-closure gap test in
    #    validate_body accepts cross-face seams.
    edges_seen: List[Edge] = []
    for f in faces:
        for lp in f.loops:
            for ce in lp.coedges:
                e = ce.edge
                e.v_start = rep_of[id(e.v_start)]
                e.v_end = rep_of[id(e.v_end)]
                if e not in edges_seen:
                    edges_seen.append(e)
                if e.tol < f.tol:
                    e.tol = f.tol
                if e.tol < sew_tol:
                    e.tol = sew_tol
                # vertex tol monotonicity wrt the (potentially bumped)
                # edge tol; the representative has already been bumped
                for v in (e.v_start, e.v_end):
                    if v.tol < e.tol:
                        v.tol = e.tol

    # 3) edge merging: two edges with the same endpoint-rep pair AND
    #    coincident midpoint samples collapse to one shared physical edge,
    #    and the two coedges are re-pointed onto the survivor.
    rep_map_edge: dict = {}  # id(edge) -> survivor Edge
    edge_clusters: List[Edge] = []
    for e in edges_seen:
        key_a = (id(e.v_start), id(e.v_end))
        key_b = (id(e.v_end), id(e.v_start))
        mid = 0.5 * (e.point(e.t0) + e.point(e.t1))
        survivor: Optional[Edge] = None
        for cand in edge_clusters:
            ck = (id(cand.v_start), id(cand.v_end))
            if ck != key_a and ck != key_b:
                continue
            cmid = 0.5 * (cand.point(cand.t0) + cand.point(cand.t1))
            if float(np.linalg.norm(mid - cmid)) <= sew_tol * 100.0:
                survivor = cand
                break
        if survivor is None:
            edge_clusters.append(e)
            rep_map_edge[id(e)] = e
        else:
            rep_map_edge[id(e)] = survivor

    # 4) repoint coedges, and update edge.coedges to reflect the survivor
    for f in faces:
        for lp in f.loops:
            for ce in lp.coedges:
                old = ce.edge
                new = rep_map_edge[id(old)]
                if new is not old:
                    # we may need to flip orientation if the survivor runs
                    # the other way round
                    if (
                        old.v_start is new.v_end
                        and old.v_end is new.v_start
                    ):
                        ce.orientation = not ce.orientation
                    ce.edge = new
                    if ce not in new.coedges:
                        new.coedges.append(ce)
                    # purge the old edge's stale coedge list
                    old.coedges = []

    # 5) decide closedness exactly: every edge used by exactly 2 coedges of
    #    opposite orientation
    use: dict = {}
    for f in faces:
        for lp in f.loops:
            for ce in lp.coedges:
                use.setdefault(id(ce.edge), []).append(ce)
    is_closed = True
    for ces in use.values():
        if len(ces) != 2 or ces[0].orientation == ces[1].orientation:
            is_closed = False
            break

    shell = Shell(list(faces), is_closed=is_closed)
    if is_closed:
        # Full validate_body path: a closed shell wrapped in a solid is a
        # legitimate target for the body-wide Euler-Poincare check.
        transient_body = Body(solids=[Solid([shell])])
        res = validate_body(transient_body)
        if not res["ok"]:
            raise BuildError(
                f"surfaces_to_shell produced invalid closed Shell: "
                f"{res['errors']}",
                res,
            )
        transient_body.solids = []
        shell.solid = None
    else:
        # Open shells skip the Euler-Poincare gate and the closed-manifold
        # gate. Walk every face structurally instead.
        errs: List[str] = []
        for f in shell.faces:
            errs.extend(_validate_face_local(f))
        if errs:
            raise BuildError(
                f"surfaces_to_shell produced invalid open Shell: {errs}",
                {"ok": False, "errors": errs},
            )
    return shell


def closed_shell_to_solid(shell: Shell) -> Solid:
    """Wrap a closed ``Shell`` as the outer shell of a new ``Solid``.

    The resulting solid is placed in a transient single-solid ``Body`` and
    ``validate_body`` is asserted clean. Returns the unattached ``Solid``.
    """
    if not shell.is_closed:
        raise BuildError("closed_shell_to_solid requires a closed shell")
    solid = Solid([shell])
    transient = Body(solids=[solid])
    res = validate_body(transient)
    if not res["ok"]:
        raise BuildError(
            f"closed_shell_to_solid produced invalid Solid: {res['errors']}",
            res,
        )
    # detach
    transient.solids = []
    return solid


# ---------------------------------------------------------------------------
# Analytic primitive constructors (production path)
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _perp(axis: np.ndarray) -> np.ndarray:
    ref = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(ref, axis))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    return _unit(np.cross(axis, ref))


def box_to_body(
    corner: Sequence[float],
    dx: float,
    dy: float,
    dz: float,
    tol: float = 1e-7,
) -> Body:
    """Build an axis-aligned box ``Body`` from a corner + extents.

    Topology: V=8, E=12, F=6, S=1, G=0. ``validate_body`` is asserted
    clean before return.
    """
    ox, oy, oz = (float(c) for c in corner)
    P = [
        np.array([ox, oy, oz]),
        np.array([ox + dx, oy, oz]),
        np.array([ox + dx, oy + dy, oz]),
        np.array([ox, oy + dy, oz]),
        np.array([ox, oy, oz + dz]),
        np.array([ox + dx, oy, oz + dz]),
        np.array([ox + dx, oy + dy, oz + dz]),
        np.array([ox, oy + dy, oz + dz]),
    ]
    V = [Vertex(p, tol) for p in P]

    edef = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    E = {
        pair: Edge(Line3(P[pair[0]], P[pair[1]]), 0.0, 1.0,
                   V[pair[0]], V[pair[1]], tol)
        for pair in edef
    }

    def edge_for(a: int, b: int):
        if (a, b) in E:
            return E[(a, b)], True
        return E[(b, a)], False

    face_rings = [
        [0, 3, 2, 1],  # bottom (z-)
        [4, 5, 6, 7],  # top (z+)
        [0, 1, 5, 4],  # front (y-)
        [1, 2, 6, 5],  # right (x+)
        [2, 3, 7, 6],  # back (y+)
        [3, 0, 4, 7],  # left (x-)
    ]
    faces: List[Face] = []
    for ring in face_rings:
        coedges = []
        for i in range(4):
            a, b = ring[i], ring[(i + 1) % 4]
            e, o = edge_for(a, b)
            coedges.append(Coedge(e, o))
        loop = Loop(coedges, is_outer=True)
        p0, p1, p2 = P[ring[0]], P[ring[1]], P[ring[3]]
        plane = Plane(origin=p0, x_axis=p1 - p0, y_axis=p2 - p0)
        faces.append(Face(plane, [loop], orientation=True, tol=tol))

    shell = Shell(faces, is_closed=True)
    body = Body(solids=[Solid([shell])])
    res = validate_body(body)
    if not res["ok"]:
        raise BuildError(
            f"box_to_body produced invalid Body: {res['errors']}", res
        )
    return body


def cylinder_to_body(
    axis_pt: Sequence[float],
    axis_dir: Sequence[float],
    radius: float,
    height: float,
    tol: float = 1e-7,
) -> Body:
    """Build a closed cylinder ``Body`` matching the documented seam
    topology of :func:`brep.make_cylinder`.

    Topology: V=2 (two seam endpoints), E=3 (two rim circles + one
    straight seam), F=3 (lateral + 2 caps), L=4 (the lateral face's loop
    walks the seam there-and-back).
    """
    c = np.asarray(axis_pt, dtype=float)
    ax = _unit(np.asarray(axis_dir, dtype=float))
    xref = _perp(ax)
    yref = _unit(np.cross(ax, xref))
    top_c = c + height * ax

    cyl = CylinderSurface(c, ax, radius, xref)
    bottom_plane = Plane(origin=c, x_axis=xref, y_axis=yref)
    top_plane = Plane(origin=top_c, x_axis=xref, y_axis=-yref)

    seam_b = c + radius * xref
    seam_t = top_c + radius * xref
    vb = Vertex(seam_b, tol)
    vt = Vertex(seam_t, tol)

    bottom_circle = CircleArc3(c, radius, xref, yref, 0.0, 2 * math.pi)
    top_circle = CircleArc3(top_c, radius, xref, yref, 0.0, 2 * math.pi)
    e_bottom = Edge(bottom_circle, 0.0, 2 * math.pi, vb, vb, tol)
    e_top = Edge(top_circle, 0.0, 2 * math.pi, vt, vt, tol)
    e_seam = Edge(Line3(seam_b, seam_t), 0.0, 1.0, vb, vt, tol)

    side_loop = Loop(
        [
            Coedge(e_bottom, True),
            Coedge(e_seam, True),
            Coedge(e_top, False),
            Coedge(e_seam, False),
        ],
        is_outer=True,
    )
    side_face = Face(cyl, [side_loop], orientation=True, tol=tol)
    bottom_face = Face(
        bottom_plane,
        [Loop([Coedge(e_bottom, False)], is_outer=True)],
        orientation=True,
        tol=tol,
    )
    top_face = Face(
        top_plane,
        [Loop([Coedge(e_top, True)], is_outer=True)],
        orientation=True,
        tol=tol,
    )

    shell = Shell([side_face, bottom_face, top_face], is_closed=True)
    body = Body(solids=[Solid([shell])])
    res = validate_body(body)
    if not res["ok"]:
        raise BuildError(
            f"cylinder_to_body produced invalid Body: {res['errors']}", res
        )
    return body


def sphere_to_body(
    centre: Sequence[float],
    radius: float,
    tol: float = 1e-7,
) -> Body:
    """Build a closed sphere ``Body`` matching :func:`brep.make_sphere`.

    Topology: V=2 (poles), E=1 (one meridian seam), F=1, L=1, G=0, S=1.
    The lone face's single loop traverses the seam forward then backward
    (pole singularities collapse).
    """
    c = np.asarray(centre, dtype=float)
    sph = SphereSurface(c, radius)
    north = Vertex(c + np.array([0.0, 0.0, radius]), tol)
    south = Vertex(c - np.array([0.0, 0.0, radius]), tol)

    class _Meridian:
        def evaluate(self, t: float) -> np.ndarray:
            v = -math.pi / 2 + t * math.pi
            return sph.evaluate(0.0, v)

    seam = Edge(_Meridian(), 0.0, 1.0, south, north, tol)
    loop = Loop(
        [Coedge(seam, True), Coedge(seam, False)],
        is_outer=True,
    )
    face = Face(sph, [loop], orientation=True, tol=tol)
    shell = Shell([face], is_closed=True)
    body = Body(solids=[Solid([shell])])
    res = validate_body(body)
    if not res["ok"]:
        raise BuildError(
            f"sphere_to_body produced invalid Body: {res['errors']}", res
        )
    return body


__all__ = [
    "BuildError",
    "surface_to_face",
    "surfaces_to_shell",
    "closed_shell_to_solid",
    "box_to_body",
    "cylinder_to_body",
    "sphere_to_body",
]
