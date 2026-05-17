"""Geometry Kernel P1 — constant, asymmetric, and variable-width chamfer
on planar–planar B-rep edges.

Public API
----------
chamfer_edge(body, edge, width)
    Constant-width chamfer: both support faces set back by ``width``.

chamfer_edge_asymmetric(body, edge, width_a, width_b)
    Asymmetric chamfer: face A set back by ``width_a``, face B by
    ``width_b``.

chamfer_edge_variable(body, edge, width_start, width_end)
    Variable-width chamfer: linear ramp from ``width_start`` (at
    ``edge.v_start``) to ``width_end`` (at ``edge.v_end``).  The bevel
    surface is a ruled surface between the two trim curves; it is planar
    only when ``width_start == width_end``.

Supported-input contract
------------------------
These functions are restricted — by design — to **planar–planar** edges
emitted by :func:`kerf_cad_core.geom.brep_build.box_to_body` (i.e.
axis-aligned closed box bodies whose faces are all
:class:`~kerf_cad_core.geom.brep.Plane` instances).  Specifically:

* The ``edge`` must be shared by **exactly two** faces, both of which
  carry a :class:`~kerf_cad_core.geom.brep.Plane` surface (the analytic
  adapter, not a NURBS surface).
* The two planes must not be co-planar (the dihedral angle must be
  non-degenerate; ``|sin(theta)| > 1e-9``).
* ``width`` (or ``width_a`` / ``width_b``) must be positive and strictly
  smaller than the shortest distance from the edge to any parallel edge
  on the same support face; raises :class:`ChamferError` with a
  descriptive reason if violated.
* The underlying edge geometry must be a straight-line segment
  (:class:`~kerf_cad_core.geom.brep.Line3`).  Circular arcs and NURBS
  curves are P2/P3.
* Non-planar (cylindrical/spherical/NURBS) support faces are P2/P3;
  they raise :class:`ChamferError` with ``reason="non-planar face"``.

The resulting ``Body`` is guaranteed ``validate_body``-clean.

Topology change for one chamfered edge on a box
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Before: V=8  E=12  F=6
After:  V=10 E=15  F=7

Breakdown of the change:

* **−2 vertices**: the two original corner vertices of the chamfered edge
  are removed.
* **+4 vertices**: four new setback vertices, one per (support face, edge
  end) combination.
* **−1 edge**: the chamfered edge is removed.
* **+2 setback edges**: one new straight setback line on each support face
  (connecting the two new setback vertices on that face).
* **+2 bevel-boundary edges**: one per original corner vertex, connecting
  the setback vertex on face A to the setback vertex on face B at that
  corner.  These edges are also inserted into the respective corner faces
  to bridge the gap left by the removed corner vertex.
* **+1 bevel face**: bounded by setback-A, bevel-boundary-end, setback-B
  (reversed), bevel-boundary-start (reversed).
* **4 corner faces** updated: 2 support faces have their chamfered coedge
  replaced by the setback coedge; 2 corner faces each gain the bevel-
  boundary coedge to close the loop that was opened by removing the
  adjacent corner vertex.

Euler-Poincaré invariant: V−E+F−H−2(S−G) = 10−15+7−0−2(1−0) = 0 ✓

Notes
-----
The algorithm is pure-Python / NumPy — no OCCT dependency.  It operates
directly on the B-rep topology from :mod:`brep.py` and calls
:func:`kerf_cad_core.geom.sew.sew_into_solid` to rebuild the validated
body.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Coedge,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    Vertex,
    validate_body,
)
from kerf_cad_core.geom.brep_build import BuildError


__all__ = [
    "ChamferError",
    "chamfer_edge",
    "chamfer_edge_asymmetric",
    "chamfer_edge_variable",
    "_RuledSurface",  # exported for test inspection
]


# ---------------------------------------------------------------------------
# Public error type
# ---------------------------------------------------------------------------


class ChamferError(ValueError):
    """Raised when a chamfer input violates the supported-input contract.

    Attributes
    ----------
    reason : str
        Machine-readable short tag, e.g. ``"non-planar face"``,
        ``"width exceeds face"``, ``"non-linear edge"``,
        ``"non-manifold edge"``, ``"invalid-width"``.
    message : str
        Human-readable description.
    """

    def __init__(self, message: str, reason: str = "invalid-input") -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    if n < 1e-14:
        raise ChamferError(
            "degenerate zero-length vector during chamfer",
            reason="degenerate-geometry",
        )
    return v / n


def _find_edge_faces(body: Body, edge: Edge) -> Tuple[Face, Face]:
    """Return the exactly-two faces that share *edge* in *body*.

    Raises :class:`ChamferError` if the edge is not shared by exactly
    two faces (i.e. a boundary or non-manifold edge).
    """
    faces: List[Face] = []
    for face in body.all_faces():
        for lp in face.loops:
            for ce in lp.coedges:
                if ce.edge is edge:
                    faces.append(face)
                    break
            else:
                continue
            break
    if len(faces) != 2:
        raise ChamferError(
            f"chamfer requires an edge shared by exactly 2 faces; "
            f"found {len(faces)}",
            reason="non-manifold edge",
        )
    return faces[0], faces[1]


def _require_plane(face: Face) -> Plane:
    """Return the Plane surface of *face* or raise :class:`ChamferError`."""
    if not isinstance(face.surface, Plane):
        raise ChamferError(
            f"chamfer is restricted to Plane-surfaced faces (P1 contract); "
            f"face#{face.id} has surface type {type(face.surface).__name__}",
            reason="non-planar face",
        )
    return face.surface


def _require_line(edge: Edge) -> Line3:
    """Return the Line3 curve of *edge* or raise :class:`ChamferError`."""
    if not isinstance(edge.curve, Line3):
        raise ChamferError(
            f"chamfer is restricted to straight-line edges (P1 contract); "
            f"edge#{edge.id} has curve type {type(edge.curve).__name__}",
            reason="non-linear edge",
        )
    return edge.curve


def _face_inward_normal_at_edge(face: Face, edge: Edge) -> np.ndarray:
    """Return the unit inward direction on *face* perpendicular to *edge*.

    "Inward" means pointing away from the edge into the face interior
    (away from the shared edge boundary, towards the face's own interior).
    For a Plane surface the face normal is constant; the inward direction
    is ``face_normal × edge_direction`` (signed so it points into the face
    interior).
    """
    plane: Plane = face.surface
    face_n = _unit(np.cross(plane.x_axis, plane.y_axis))
    if not face.orientation:
        face_n = -face_n

    line: Line3 = edge.curve
    edge_dir = _unit(line.p1 - line.p0)

    inward = np.cross(face_n, edge_dir)
    nrm = float(np.linalg.norm(inward))
    if nrm < 1e-10:
        raise ChamferError(
            "edge direction is parallel to face normal; degenerate geometry",
            reason="degenerate-geometry",
        )
    inward = inward / nrm

    # Sign check: the face centroid should be on the inward side of the edge.
    outer = face.outer_loop()
    if outer and outer.coedges:
        pts = np.array([ce.start_point() for ce in outer.coedges], dtype=float)
        centroid = pts.mean(axis=0)
        edge_mid = 0.5 * (line.p0 + line.p1)
        if float(np.dot(centroid - edge_mid, inward)) < 0:
            inward = -inward

    return inward


def _max_setback_on_face(face: Face, edge: Edge, inward: np.ndarray) -> float:
    """Maximum setback allowed on *face* along *inward* before hitting another edge."""
    line: Line3 = edge.curve
    edge_mid = 0.5 * (line.p0 + line.p1)

    min_d = float("inf")
    for lp in face.loops:
        for ce in lp.coedges:
            if ce.edge is edge:
                continue
            other = ce.edge.curve
            if not isinstance(other, Line3):
                continue
            # sample midpoint distance along inward
            other_mid = 0.5 * (other.p0 + other.p1)
            d = float(np.dot(other_mid - edge_mid, inward))
            if d > 1e-12:
                min_d = min(min_d, d)
    return min_d if min_d < float("inf") else 1e9


def _validate_width(
    w: float,
    label: str,
    face: Face,
    edge: Edge,
    inward: np.ndarray,
) -> None:
    if w < 0.0:
        raise ChamferError(
            f"chamfer {label} must be non-negative; got {w}",
            reason="invalid-width",
        )
    if w == 0.0:
        return  # zero is allowed for variable end
    max_w = _max_setback_on_face(face, edge, inward)
    if w >= max_w - 1e-12:
        raise ChamferError(
            f"chamfer {label}={w:.6g} exceeds or reaches the face boundary "
            f"(max setback ≈ {max_w:.6g}); reduce width or choose a shorter edge",
            reason="width exceeds face",
        )


def _validate_nonzero_width(w: float, label: str) -> None:
    if w <= 0.0:
        raise ChamferError(
            f"chamfer {label} must be positive; got {w}",
            reason="invalid-width",
        )


# ---------------------------------------------------------------------------
# Ruled surface for bevel face
# ---------------------------------------------------------------------------


class _RuledSurface:
    """Ruled surface between two straight line segments.

    Parameterised as::

        P(u, v) = (1−v)·lineA(u) + v·lineB(u)

    where ``u ∈ [0, 1]`` runs along the edge direction, ``v ∈ [0, 1]``
    runs across the bevel.

    ``lineA(u) = a0 + u*(a1−a0)``  (face-A setback)
    ``lineB(u) = b0 + u*(b1−b0)``  (face-B setback)

    For a symmetric constant chamfer (both setback lines are parallel and
    equal-length) the ruled surface is planar.
    """

    def __init__(
        self,
        a0: np.ndarray,
        a1: np.ndarray,
        b0: np.ndarray,
        b1: np.ndarray,
    ) -> None:
        self.a0 = np.asarray(a0, dtype=float)
        self.a1 = np.asarray(a1, dtype=float)
        self.b0 = np.asarray(b0, dtype=float)
        self.b1 = np.asarray(b1, dtype=float)

    def evaluate(self, u: float, v: float) -> np.ndarray:
        la = self.a0 + float(u) * (self.a1 - self.a0)
        lb = self.b0 + float(u) * (self.b1 - self.b0)
        return (1.0 - float(v)) * la + float(v) * lb

    def normal(self, u: float, v: float) -> np.ndarray:
        h = 1e-5
        p = self.evaluate(u, v)
        du = self.evaluate(u + h, v) - p
        dv = self.evaluate(u, v + h) - p
        n = np.cross(du, dv)
        nrm = float(np.linalg.norm(n))
        if nrm < 1e-15:
            return np.array([0.0, 0.0, 1.0])
        return n / nrm


# ---------------------------------------------------------------------------
# Core chamfer surgery
# ---------------------------------------------------------------------------


def _signed_area_about_normal(pts: List[np.ndarray], normal: np.ndarray) -> float:
    """Signed polygon area of *pts* (list of 3D points, closed polygon)
    projected onto *normal*.  Positive = CCW, negative = CW.
    """
    centroid = np.mean(pts, axis=0)
    area_vec = np.zeros(3)
    n = len(pts)
    for i in range(n):
        a = pts[i] - centroid
        b = pts[(i + 1) % n] - centroid
        area_vec += np.cross(a, b)
    return float(np.dot(area_vec, normal) * 0.5)


def _make_loop(coedge_list: List[Coedge], is_outer: bool = True) -> Loop:
    lp = Loop(coedge_list, is_outer=is_outer)
    return lp


def _make_face_from_coedges(
    surface,
    coedge_list: List[Coedge],
    orientation: bool,
    tol: float,
    auto_orient: bool = True,
) -> Face:
    """Build a Face; if *auto_orient* is True, reverse coedges if CW wrt surface."""
    loop = _make_loop(coedge_list, is_outer=True)
    face = Face(surface, [loop], orientation=orientation, tol=tol)
    if auto_orient:
        pts = [np.asarray(ce.start_point(), dtype=float) for ce in coedge_list]
        if len(pts) >= 3:
            try:
                n = np.asarray(surface.normal(0.5, 0.5), dtype=float)
                nm = float(np.linalg.norm(n))
                if nm > 1e-14:
                    n = n / nm
                    signed = _signed_area_about_normal(pts, n)
                    if signed < 0:
                        # Reverse
                        rev = [Coedge(ce.edge, not ce.orientation)
                               for ce in reversed(coedge_list)]
                        loop = _make_loop(rev, is_outer=True)
                        face = Face(surface, [loop], orientation=orientation, tol=tol)
            except Exception:
                pass
    return face


def _chamfer_asymmetric_impl(
    body: Body,
    edge: Edge,
    width_a: float,
    width_b: float,
    width_a_end: Optional[float] = None,
    width_b_end: Optional[float] = None,
    tol: float = 1e-6,
) -> Body:
    """Core chamfer implementation shared by all three public entry points.

    Parameters
    ----------
    width_a, width_b
        Setback distances on face A / face B at the *v_start* end.
    width_a_end, width_b_end
        Setback distances at the *v_end* end.  ``None`` means same as
        start (constant chamfer).
    """
    if width_a_end is None:
        width_a_end = width_a
    if width_b_end is None:
        width_b_end = width_b

    # --- validate inputs -------------------------------------------------------
    _require_line(edge)
    face_a, face_b = _find_edge_faces(body, edge)
    _require_plane(face_a)
    _require_plane(face_b)

    inward_a = _face_inward_normal_at_edge(face_a, edge)
    inward_b = _face_inward_normal_at_edge(face_b, edge)

    _validate_width(width_a, "width_a (v_start end)", face_a, edge, inward_a)
    _validate_width(width_a_end, "width_a (v_end end)", face_a, edge, inward_a)
    _validate_width(width_b, "width_b (v_start end)", face_b, edge, inward_b)
    _validate_width(width_b_end, "width_b (v_end end)", face_b, edge, inward_b)

    # --- identify the original corner vertices ---------------------------------
    v_orig_start: Vertex = edge.v_start
    v_orig_end: Vertex = edge.v_end

    line: Line3 = edge.curve

    # --- compute new setback vertex positions ----------------------------------
    # At each end of the original edge there are two new setback vertices:
    #   one on face A, one on face B.
    p_a_start = line.p0 + width_a     * inward_a  # face-A setback at v_start end
    p_a_end   = line.p1 + width_a_end * inward_a  # face-A setback at v_end end
    p_b_start = line.p0 + width_b     * inward_b  # face-B setback at v_start end
    p_b_end   = line.p1 + width_b_end * inward_b  # face-B setback at v_end end

    v_a_start = Vertex(p_a_start, tol)
    v_a_end   = Vertex(p_a_end,   tol)
    v_b_start = Vertex(p_b_start, tol)
    v_b_end   = Vertex(p_b_end,   tol)

    # --- detect degenerate (zero-width) ends ----------------------------------
    # When one end of the chamfer has zero width, the two setback vertices at
    # that end coincide with the original corner vertex.  In this case:
    #  - No separate v_a_* / v_b_* vertices are created at that end.
    #  - No bevel_at_* edge is created at that end.
    #  - Corner faces at that end require no bevel bridge insertion.
    #  - The bevel face is a triangle (3 coedges) instead of a quad.

    degenerate_start = (width_a <= 0.0 and width_b <= 0.0)
    degenerate_end   = (width_a_end <= 0.0 and width_b_end <= 0.0)

    # For a degenerate start: reuse the original v_orig_start as the tip vertex
    # (so the setback edges still connect to it without changing corner faces).
    # Same logic for end.
    if degenerate_start:
        v_a_start = v_orig_start
        v_b_start = v_orig_start
        p_a_start = v_orig_start.point
        p_b_start = v_orig_start.point
        bevel_at_start = None  # type: ignore[assignment]
    if degenerate_end:
        v_a_end = v_orig_end
        v_b_end = v_orig_end
        p_a_end = v_orig_end.point
        p_b_end = v_orig_end.point
        bevel_at_end = None  # type: ignore[assignment]

    # Recreate setback / bevel-boundary edges now that degenerate vertex
    # references are resolved (no-op for non-degenerate cases).
    setback_a = Edge(Line3(p_a_start, p_a_end), 0.0, 1.0, v_a_start, v_a_end, tol)
    setback_b = Edge(Line3(p_b_start, p_b_end), 0.0, 1.0, v_b_start, v_b_end, tol)
    if not degenerate_start:
        bevel_at_start = Edge(
            Line3(p_a_start, p_b_start), 0.0, 1.0, v_a_start, v_b_start, tol
        )
    if not degenerate_end:
        bevel_at_end = Edge(
            Line3(p_a_end, p_b_end), 0.0, 1.0, v_a_end, v_b_end, tol
        )

    # --- edge substitution map (NON-MUTATING) ---------------------------------
    # Each edge adjacent to v_orig_start or v_orig_end (other than the
    # chamfered edge itself) must have its endpoint repointed to the correct
    # new vertex depending on which face context it belongs to.
    #
    # We create NEW Edge objects; the original body edges are never mutated,
    # so repeated calls on the same body (e.g. reversed asymmetric) work
    # correctly.

    def _faces_of_edge_including_support(e: Edge) -> List[Face]:
        result = []
        for f in body.all_faces():
            for lp in f.loops:
                for ce in lp.coedges:
                    if ce.edge is e:
                        result.append(f)
                        break
                else:
                    continue
                break
        return result

    # Build map: id(old_edge) -> new_Edge (with repointed vertices)
    edge_substitute: Dict[int, Edge] = {}

    for e in body.all_edges():
        if e is edge:
            continue
        old_vs = e.v_start
        old_ve = e.v_end
        touches_start = (old_vs is v_orig_start or old_ve is v_orig_start)
        touches_end   = (old_vs is v_orig_end   or old_ve is v_orig_end)
        if not touches_start and not touches_end:
            # Edge untouched — use it directly (no new object needed)
            continue

        # Determine which new vertex to use at the touched end.
        # Find whether this edge belongs to face_a or face_b.
        e_faces = _faces_of_edge_including_support(e)
        in_face_a = any(f is face_a for f in e_faces)
        in_face_b = any(f is face_b for f in e_faces)

        new_vs: Vertex = old_vs
        new_ve: Vertex = old_ve

        if touches_start:
            if degenerate_start:
                # v_a_start == v_b_start == v_orig_start; no repointing needed
                pass
            elif in_face_a and not in_face_b:
                replacement_s = v_a_start
                if old_vs is v_orig_start:
                    new_vs = replacement_s
                else:
                    new_ve = replacement_s
            elif in_face_b and not in_face_a:
                replacement_s = v_b_start
                if old_vs is v_orig_start:
                    new_vs = replacement_s
                else:
                    new_ve = replacement_s
            else:
                raise ChamferError(
                    "topology error: non-chamfered edge in both support faces",
                    reason="invalid-topology",
                )

        if touches_end:
            if degenerate_end:
                # v_a_end == v_b_end == v_orig_end; no repointing needed
                pass
            elif in_face_a and not in_face_b:
                replacement_e = v_a_end
                if old_vs is v_orig_end:
                    new_vs = replacement_e
                else:
                    new_ve = replacement_e
            elif in_face_b and not in_face_a:
                replacement_e = v_b_end
                if old_vs is v_orig_end:
                    new_vs = replacement_e
                else:
                    new_ve = replacement_e
            else:
                raise ChamferError(
                    "topology error: non-chamfered edge in both support faces",
                    reason="invalid-topology",
                )

        # Create a NEW edge with the repointed vertices (never mutate original)
        if new_vs is not old_vs or new_ve is not old_ve:
            new_edge = Edge(
                Line3(new_vs.point, new_ve.point),
                0.0, 1.0, new_vs, new_ve, tol,
            )
            edge_substitute[id(e)] = new_edge

    def _new_edge_for(old_e: Edge) -> Edge:
        """Return the substituted new Edge for *old_e*, or *old_e* if unchanged."""
        return edge_substitute.get(id(old_e), old_e)

    # --- rebuild all face loops ------------------------------------------------
    # We rebuild every face from scratch to ensure correct next/prev links.
    # Support faces (face_a, face_b) get their chamfered coedge replaced.
    # Corner faces get the bevel-boundary coedge inserted where needed.
    # Untouched faces are rebuilt using new edge objects.

    all_old_faces = body.all_faces()
    new_faces: List[Face] = []

    for f in all_old_faces:
        if f is face_a or f is face_b:
            continue  # handled specially below

        outer = f.outer_loop()
        if outer is None:
            continue

        new_ces: List[Coedge] = []
        for ce in outer.coedges:
            new_ces.append(Coedge(_new_edge_for(ce.edge), ce.orientation))

        # Check for and repair any gaps by inserting bevel-boundary coedges.
        # A gap occurs when coedge[i].end != coedge[i+1].start (in 3D).
        # This only happens at corner faces that share the two bevel-boundary
        # vertices at a non-degenerate end.
        n = len(new_ces)
        repaired: List[Coedge] = []
        for i in range(n):
            repaired.append(new_ces[i])
            end_pt = np.asarray(new_ces[i].end_point(), dtype=float)
            next_start_pt = np.asarray(new_ces[(i + 1) % n].start_point(), dtype=float)
            gap = float(np.linalg.norm(end_pt - next_start_pt))
            if gap > tol * 100:
                # We need a bevel-boundary edge here.
                # Only non-None bevel edges can bridge gaps.
                bev_candidates = [
                    b for b in (bevel_at_start, bevel_at_end)
                    if b is not None
                ]
                bev = _find_bevel_bridge(
                    end_pt, next_start_pt,
                    bev_candidates,
                    tol,
                )
                if bev is None:
                    raise ChamferError(
                        f"cannot find bevel bridge for gap in face#{f.id} "
                        f"(gap={gap:.3e} between {end_pt} and {next_start_pt})",
                        reason="internal",
                    )
                bev_ce, bev_edge = bev
                repaired.append(Coedge(bev_edge, bev_ce))

        new_loop = Loop(repaired, is_outer=True)
        new_face = Face(f.surface, [new_loop], orientation=f.orientation, tol=tol)
        new_faces.append(new_face)

    # --- rebuild support faces -------------------------------------------------
    # face_a: replace the chamfered-edge coedge with setback_a coedge,
    # also substituting any other repointed edges in the loop.
    new_face_a = _rebuild_support_face(
        face_a, edge, setback_a, tol, edge_substitute
    )
    # face_b: replace the chamfered-edge coedge with setback_b coedge
    new_face_b = _rebuild_support_face(
        face_b, edge, setback_b, tol, edge_substitute
    )
    new_faces.extend([new_face_a, new_face_b])

    # --- build bevel face ------------------------------------------------------
    # The bevel face shares edges with:
    #   - new_face_a (setback_a)
    #   - new_face_b (setback_b)
    #   - left corner face (bevel_at_start)   — None if degenerate_start
    #   - right corner face (bevel_at_end)    — None if degenerate_end
    #
    # For a closed 2-manifold, each shared edge must be used with OPPOSITE
    # orientation in the two faces.  We look up the orientation used by each
    # neighbouring face and flip it.

    def _orientation_of_edge_in_face(face_out: Face, target_edge: Edge) -> Optional[bool]:
        """Return the coedge orientation for *target_edge* in *face_out*, or None."""
        for lp in face_out.loops:
            for ce in lp.coedges:
                if ce.edge is target_edge:
                    return ce.orientation
        return None

    sa_in_a = _orientation_of_edge_in_face(new_face_a, setback_a)
    sb_in_b = _orientation_of_edge_in_face(new_face_b, setback_b)

    # Find bevel_at_start / bevel_at_end orientations from the corner faces.
    bas_in_corner: Optional[bool] = None
    bae_in_corner: Optional[bool] = None
    for f in new_faces:
        if f is new_face_a or f is new_face_b:
            continue
        if bevel_at_start is not None:
            o = _orientation_of_edge_in_face(f, bevel_at_start)
            if o is not None:
                bas_in_corner = o
        if bevel_at_end is not None:
            o = _orientation_of_edge_in_face(f, bevel_at_end)
            if o is not None:
                bae_in_corner = o

    # Bevel face uses OPPOSITE orientations.
    bevel_sa_ori = not sa_in_a if sa_in_a is not None else True
    bevel_sb_ori = not sb_in_b if sb_in_b is not None else True
    bevel_bas_ori = not bas_in_corner if bas_in_corner is not None else True
    bevel_bae_ori = not bae_in_corner if bae_in_corner is not None else True

    # Build the bevel loop; it may be a triangle (3 coedges) when one end is
    # degenerate, or a quad (4 coedges) for the general case.
    bevel_surface = _RuledSurface(p_a_start, p_a_end, p_b_start, p_b_end)

    bevel_coedges = _build_closed_bevel_loop(
        setback_a, bevel_sa_ori,
        setback_b, bevel_sb_ori,
        bevel_at_start if not degenerate_start else None, bevel_bas_ori,
        bevel_at_end   if not degenerate_end   else None, bevel_bae_ori,
        tol,
    )

    bevel_loop = Loop(bevel_coedges, is_outer=True)
    # Determine whether the bevel surface normal() points outward or inward.
    # The true outward bevel normal is -(inward_a + inward_b) normalised —
    # it points away from the solid toward the removed corner material.
    expected_outward = _unit(-(inward_a + inward_b))
    sn = np.asarray(bevel_surface.normal(0.5, 0.5), dtype=float)
    nm = float(np.linalg.norm(sn))
    if nm > 1e-14:
        sn = sn / nm
    # If surface normal agrees with expected outward direction, orientation=True;
    # if it points inward, orientation=False (which flips it for validate_body).
    bevel_orientation = bool(float(np.dot(sn, expected_outward)) > 0)
    bevel_face = Face(bevel_surface, [bevel_loop], orientation=bevel_orientation, tol=tol)
    new_faces.append(bevel_face)

    # --- sew and validate -------------------------------------------------------
    from kerf_cad_core.geom.sew import sew_into_solid
    result_body = sew_into_solid(new_faces, tol=tol)

    vr = validate_body(result_body)
    if not vr["ok"]:
        raise BuildError(
            f"chamfer produced invalid body: {vr['errors']}", vr
        )
    return result_body


def _build_closed_bevel_loop(
    sa: Edge, sa_ori: bool,
    sb: Edge, sb_ori: bool,
    bas: Optional[Edge], bas_ori: bool,
    bae: Optional[Edge], bae_ori: bool,
    tol: float,
) -> List[Coedge]:
    """Build a closed bevel loop (triangle or quad) from the bevel edges.

    When *bas* or *bae* is ``None`` the corresponding end is degenerate (zero
    width) and is omitted, producing a 3-coedge triangular loop instead of a
    4-coedge quad.

    The function assembles the non-None edges in an order that produces a
    closed chain (each coedge's end vertex = next coedge's start vertex) by
    trying the canonical orderings.

    Returns the coedge list in the correct traversal order.
    Raises :class:`ChamferError` if no closed ordering is found.
    """
    def _end(e: Edge, ori: bool) -> np.ndarray:
        return e.v_end.point if ori else e.v_start.point

    def _start(e: Edge, ori: bool) -> np.ndarray:
        return e.v_start.point if ori else e.v_end.point

    # Build the candidate list, omitting degenerate (None) boundary edges.
    # Full quad: [sa, bae, sb, bas]   (indices 0..3)
    # Triangle (degenerate_start): [sa, bae, sb]
    # Triangle (degenerate_end):   [sa, sb, bas]   — bas connects end of sa to start of sb

    if bas is None and bae is None:
        raise ChamferError(
            "both bevel boundary edges are degenerate; chamfer is zero everywhere",
            reason="invalid-width",
        )

    if bas is None:
        # Degenerate start: bevel is a triangle [sa, bae, sb]
        candidates = [
            (sa, sa_ori),
            (bae, bae_ori),
            (sb, sb_ori),
        ]
        orders = [[0, 1, 2], [0, 2, 1]]
    elif bae is None:
        # Degenerate end: bevel is a triangle [sa, sb, bas] or [sa, bas, sb]
        candidates = [
            (sa, sa_ori),
            (sb, sb_ori),
            (bas, bas_ori),
        ]
        orders = [[0, 1, 2], [0, 2, 1]]
    else:
        # Full quad
        candidates = [
            (sa, sa_ori),
            (bae, bae_ori),
            (sb, sb_ori),
            (bas, bas_ori),
        ]
        orders = [[0, 1, 2, 3], [0, 3, 2, 1]]

    n = len(candidates)
    for order in orders:
        seq = [candidates[i] for i in order]
        closed = True
        for i in range(n):
            e0, o0 = seq[i]
            e1, o1 = seq[(i + 1) % n]
            gap = float(np.linalg.norm(_end(e0, o0) - _start(e1, o1)))
            if gap > tol * 1000:
                closed = False
                break
        if closed:
            return [Coedge(e, o) for (e, o) in seq]

    # No ordering closed; raise an informative error.
    detail = "\n".join(
        f"  {e.v_start.point} -> {e.v_end.point} ori={o}"
        for e, o in candidates
    )
    raise ChamferError(
        f"cannot assemble closed bevel loop from:\n{detail}",
        reason="internal",
    )


def _find_bevel_bridge(
    end_pt: np.ndarray,
    next_start_pt: np.ndarray,
    bevel_candidates: List[Edge],
    tol: float,
) -> Optional[Tuple[bool, Edge]]:
    """Find which bevel-boundary edge connects *end_pt* to *next_start_pt*.

    *bevel_candidates* is a list of non-None bevel boundary edges to search.

    Returns ``(orientation, edge)`` where ``orientation=True`` means the
    edge runs naturally from ``end_pt`` to ``next_start_pt``.
    Returns ``None`` if no bevel edge bridges the gap.
    """
    for bev_edge in bevel_candidates:
        sp = bev_edge.v_start.point
        ep = bev_edge.v_end.point
        if (float(np.linalg.norm(sp - end_pt)) < tol * 1000 and
                float(np.linalg.norm(ep - next_start_pt)) < tol * 1000):
            return True, bev_edge
        if (float(np.linalg.norm(ep - end_pt)) < tol * 1000 and
                float(np.linalg.norm(sp - next_start_pt)) < tol * 1000):
            return False, bev_edge
    return None


def _rebuild_support_face(
    face: Face,
    chamfered_edge: Edge,
    setback_edge: Edge,
    tol: float,
    edge_substitute: Dict[int, Edge],
) -> Face:
    """Rebuild a support face replacing the chamfered coedge with the setback coedge.

    Other edges that were repointed (in *edge_substitute*) are substituted as
    well.  The setback edge has the same topological direction as the chamfered
    edge's coedge in this face.
    """
    outer = face.outer_loop()
    if outer is None:
        raise ChamferError(f"face#{face.id} has no outer loop", reason="internal")

    # Find the coedge for the chamfered edge and its orientation
    chamfer_orientation = None
    for ce in outer.coedges:
        if ce.edge is chamfered_edge:
            chamfer_orientation = ce.orientation
            break
    if chamfer_orientation is None:
        raise ChamferError(
            f"face#{face.id} does not contain chamfered edge#{chamfered_edge.id}",
            reason="internal",
        )

    # Rebuild coedges: replace chamfered coedge with setback coedge,
    # and substitute any other repointed edges.
    new_ces: List[Coedge] = []
    for ce in outer.coedges:
        if ce.edge is chamfered_edge:
            # The setback edge runs in the same relative direction.
            new_ces.append(Coedge(setback_edge, chamfer_orientation))
        else:
            new_e = edge_substitute.get(id(ce.edge), ce.edge)
            new_ces.append(Coedge(new_e, ce.orientation))

    new_loop = Loop(new_ces, is_outer=True)
    return Face(face.surface, [new_loop], orientation=face.orientation, tol=tol)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chamfer_edge(body: Body, edge: Edge, width: float, tol: float = 1e-6) -> Body:
    """Constant-width planar chamfer on *edge*.

    Both support faces are set back by *width* along their respective
    inward normals.  The resulting bevel face is planar (a 45° bevel when
    the dihedral angle is 90°, i.e. two orthogonal faces of a box).

    Parameters
    ----------
    body : Body
        A ``validate_body``-clean body produced by
        :func:`~kerf_cad_core.geom.brep_build.box_to_body` (or equivalent
        analytic construction).
    edge : Edge
        The edge to chamfer.  Must be a straight-line edge shared by
        exactly two planar faces (P1 contract).
    width : float
        Setback distance on each support face.  Must be positive and
        strictly less than the face extent beyond the edge.
    tol : float
        Sewing tolerance (default 1e-6).

    Returns
    -------
    Body
        A new ``validate_body``-clean body with the chamfer applied.
        Euler topology: V=+2, E=+3, F=+1 relative to input (for a
        manifold box edge: V=10, E=15, F=7).

    Raises
    ------
    ChamferError
        If the input violates the supported-input contract (non-planar
        face, non-linear edge, width too large, non-manifold edge, etc.).
    """
    _validate_nonzero_width(width, "width")
    return _chamfer_asymmetric_impl(body, edge, width, width, tol=tol)


def chamfer_edge_asymmetric(
    body: Body,
    edge: Edge,
    width_a: float,
    width_b: float,
    tol: float = 1e-6,
) -> Body:
    """Asymmetric planar chamfer on *edge*.

    Face A is set back by *width_a*, face B by *width_b*.  The bevel face
    is planar (it connects two parallel-in-space setback lines).

    Parameters
    ----------
    body : Body
        A ``validate_body``-clean body produced by
        :func:`~kerf_cad_core.geom.brep_build.box_to_body`.
    edge : Edge
        Straight-line edge shared by exactly two planar faces.
    width_a : float
        Setback distance on face A (the first face found sharing the edge).
    width_b : float
        Setback distance on face B.
    tol : float
        Sewing tolerance (default 1e-6).

    Returns
    -------
    Body
        New ``validate_body``-clean body with the asymmetric chamfer.

    Raises
    ------
    ChamferError
        If inputs violate the supported-input contract.
    """
    _validate_nonzero_width(width_a, "width_a")
    _validate_nonzero_width(width_b, "width_b")
    return _chamfer_asymmetric_impl(body, edge, width_a, width_b, tol=tol)


def chamfer_edge_variable(
    body: Body,
    edge: Edge,
    width_start: float,
    width_end: float,
    tol: float = 1e-6,
) -> Body:
    """Variable-width planar chamfer on *edge*.

    The chamfer width ramps linearly from *width_start* (at
    ``edge.v_start``) to *width_end* (at ``edge.v_end``).  Both support
    faces are trimmed by tapered lines.  The bevel face is a **ruled
    surface** between the two trim curves; it is planar when
    ``width_start == width_end``.

    Parameters
    ----------
    body : Body
        A ``validate_body``-clean body produced by
        :func:`~kerf_cad_core.geom.brep_build.box_to_body`.
    edge : Edge
        Straight-line edge shared by exactly two planar faces.
    width_start : float
        Setback distance at ``edge.v_start``.  May be zero (degenerate
        wedge end) or positive.
    width_end : float
        Setback distance at ``edge.v_end``.  May be zero or positive.
        At least one must be positive.
    tol : float
        Sewing tolerance (default 1e-6).

    Returns
    -------
    Body
        New ``validate_body``-clean body with the variable chamfer.

    Raises
    ------
    ChamferError
        If inputs violate the supported-input contract, or if both widths
        are zero or negative.
    """
    if width_start < 0.0 or width_end < 0.0:
        raise ChamferError(
            "variable chamfer widths must be non-negative",
            reason="invalid-width",
        )
    if width_start <= 0.0 and width_end <= 0.0:
        raise ChamferError(
            "variable chamfer: at least one of width_start / width_end "
            "must be positive",
            reason="invalid-width",
        )
    return _chamfer_asymmetric_impl(
        body, edge,
        width_a=width_start, width_b=width_start,
        width_a_end=width_end, width_b_end=width_end,
        tol=tol,
    )
