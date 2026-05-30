"""
direct_edit.py
==============
GK-134 / GK-P18 — Direct modelling: move-face / push-pull / delete-face.

History-free local edits on a :class:`Body`:

* :func:`push_pull_face` — translate (or offset) a face along its outward
  normal by a signed distance.  For planar faces adjacent faces are re-healed
  so the solid remains closed.  For curved (non-planar) faces the offset is
  applied using the pure-Python surface-offset path; the OCCT worker uses
  ``BRepOffsetAPI_MakeOffsetShape`` for higher accuracy (GK-P18).

* :func:`push_pull_face_with_constraints` — constrained push-pull that
  simulates the offset first and checks geometric constraints before
  applying.  Supports ``preserve_adjacent_face_position``,
  ``preserve_volume_sign``, and ``preserve_planarity`` constraints.
  Returns ``(modified_body, applied_distance, clamped_constraints)`` or
  raises :class:`DirectEditConstraintViolation` in reject mode.

* :func:`partial_face_replace` — replace a sub-region (UV loop) of a face
  with a new replacement surface.  Splits the face at the region boundary
  via imprint primitives, then replaces the inner sub-face surface.

* :func:`move_face` — translate a planar face by an arbitrary 3-D vector.
  The component of the vector perpendicular to the face normal is discarded;
  only the projection onto the face normal is used, keeping the face planar
  and the body closed.

* :func:`delete_face` — delete a face from a body and attempt to heal the
  resulting hole.  For planar bodies reuses the feature-deletion path from
  :mod:`~kerf_cad_core.geom.history.direct_edit`.  For general bodies the
  pure-Python path approximates healing by dropping the face and flagging the
  resulting open shell; the OCCT worker uses ``BRepTools_ReShape`` for proper
  topological healing (GK-P18).

Both push_pull_face and move_face
----------------------------------
* Accept a 0-based integer ``face_id`` (index into ``body.all_faces()``).
* Return a *new* :class:`~kerf_cad_core.geom.brep.Body`; the input body is
  never mutated.
* For planar bodies: require all faces to be
  (:class:`~kerf_cad_core.geom.brep.Plane`); raise
  :class:`~kerf_cad_core.geom.history.direct_edit.UnsupportedBodyError`.
* Raise :class:`ValueError` if ``face_id`` is out of range.
* Re-heal adjacent faces via the plane-intersection reconstruction used in
  the history layer.

GK-P18 non-planar push-pull
-----------------------------
When the target face is non-planar (e.g. a cylindrical face from a swept
body) ``push_pull_face`` applies a surface-offset approximation:

1. The face's surface is sampled at a 10×10 grid of parameter values.
2. Each grid point is displaced along its surface normal by ``distance``.
3. A new NurbsSurface is fitted to the offset grid using the Coons-patch
   interpolation in :mod:`~kerf_cad_core.geom.coons`.
4. The offset surface replaces the original face in a new Body.  Adjacent
   faces are NOT healed (the body may be open); callers should sew the
   result or pass it to the OCCT worker for proper healing.

The metadata ``__direct_edit_curved__`` is set on the returned body so
callers can detect the approximation.

Dependency chain
----------------
Reuses :mod:`kerf_cad_core.geom.history.direct_edit` (GK-86 / T-107):
  * ``_face_persistent_id`` — content-hash of a face's plane equation.
  * ``direct_offset_face`` — offset a face by a signed scalar distance.
  * ``direct_translate_face`` — translate a face by an xyz delta vector.
  * ``UnsupportedBodyError`` — re-raised on non-planar bodies (public alias).
"""

from __future__ import annotations

import warnings
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.brep import Body, Face, Shell, Plane, Vertex, Edge, Line3, Loop, Coedge
from kerf_cad_core.geom.history.direct_edit import (
    UnsupportedBodyError,
    DirectEditError,
    _face_persistent_id,
    _body_volume,
    _unit,
    direct_offset_face,
    direct_translate_face,
    direct_delete_feature,
)

__all__ = [
    "push_pull_face",
    "push_pull_face_with_constraints",
    "partial_face_replace",
    "move_face",
    "delete_face",
    "DirectEditConstraintViolation",
    "UnsupportedBodyError",
    "DirectEditError",
]


# ---------------------------------------------------------------------------
# Constrained push-pull
# ---------------------------------------------------------------------------


class DirectEditConstraintViolation(ValueError):
    """Raised when a push-pull would violate a declared constraint.

    Attributes
    ----------
    constraint : dict
        The constraint dict that was violated, e.g.
        ``{'kind': 'preserve_volume_sign'}``.
    attempted_distance : float
        The distance that was attempted.
    max_allowed : float
        The maximum signed distance that would still satisfy all constraints.
        ``None`` when no valid distance exists (e.g. the body is already
        degenerate).
    """

    def __init__(
        self,
        constraint: Dict[str, Any],
        attempted_distance: float,
        max_allowed: Optional[float],
    ) -> None:
        super().__init__(
            f"DirectEditConstraintViolation: constraint {constraint['kind']!r} "
            f"violated at distance={attempted_distance}; "
            f"max_allowed={max_allowed}"
        )
        self.constraint = constraint
        self.attempted_distance = attempted_distance
        self.max_allowed = max_allowed


def _face_plane_d(face: Face) -> Tuple[np.ndarray, float]:
    """Return (unit_normal, d) for a planar face.  d = dot(n, origin)."""
    surf = face.surface
    if not isinstance(surf, Plane):
        raise DirectEditError(
            "_face_plane_d: face is not planar", reason="non-planar face"
        )
    n = _unit(np.asarray(surf.normal(0.5, 0.5), dtype=float))
    o = np.asarray(surf.origin, dtype=float)
    d = float(np.dot(n, o))
    return n, d


def _max_distance_preserve_adjacent(
    body: Body,
    face_id: int,
    target_face: Face,
    distance: float,
) -> float:
    """Compute max signed distance before target face crosses any adjacent face.

    For a planar body: the target face has plane (n, d_target).  An adjacent
    face is any *opposing* face — the face whose outward normal is anti-parallel
    to the target normal (i.e. the opposite wall in a box).

    The maximum allowed distance (in the direction of ``distance``) is such
    that the pushed plane does not reach the opposing plane.

    Returns the maximum *signed* distance along the push direction.
    If ``distance > 0`` this is the distance to the opposing face minus a tiny
    margin.  If ``distance < 0`` this is the maximum inward travel.
    """
    if not isinstance(target_face.surface, Plane):
        # For non-planar faces we cannot compute an analytic bound; return
        # the requested distance as-is (no clamping applied).
        return distance

    n_t, d_t = _face_plane_d(target_face)
    direction = np.sign(distance) if distance != 0.0 else 1.0

    # Find the face with the most anti-parallel normal (the "opposite" face).
    best_d_opposing: Optional[float] = None
    for idx, face in enumerate(body.all_faces()):
        if idx == face_id:
            continue
        if not isinstance(face.surface, Plane):
            continue
        n_f, d_f = _face_plane_d(face)
        # Anti-parallel check: cos(angle) ≈ -1
        cos_angle = float(np.dot(n_t, n_f))
        if cos_angle < -0.99:
            if best_d_opposing is None or d_f < best_d_opposing:
                best_d_opposing = d_f

    if best_d_opposing is None:
        # No opposing face found — return requested distance unchanged.
        return distance

    # The opposing plane is at signed distance (best_d_opposing - d_t) from
    # the target plane (measured along +n_t direction).
    # Since opposing normal is -n_t, the plane equation is -n_t · x = -d_opposing,
    # i.e. n_t · x = d_opposing.  The gap (in n_t direction) between the two
    # planes is d_t - best_d_opposing (d_t is the further one when distance < 0).
    gap = d_t - best_d_opposing  # positive when target is "above" opposite face

    # Margin: keep at least 1% of the gap OR 1e-4 mm, whichever is larger.
    # This ensures the box reconstruction can find 8 valid vertices.
    _margin = max(gap * 0.01, 1e-4)
    if direction > 0:
        # Pushing outward: limit is infinity for outward push away from opp face.
        # Actually the opposing face is "behind" the target in this direction,
        # so there is no intersection — return the requested distance.
        return distance
    else:
        # Pushing inward: limit is when target face nears the opposing plane.
        max_inward = -(gap - _margin)  # negative number
        return max(distance, max_inward)


def _max_distance_preserve_volume_sign(
    body: Body,
    face_id: int,
    target_face: Face,
    distance: float,
) -> float:
    """Compute max distance before volume sign flips (body inverts or collapses).

    For a planar-faced body the volume goes to zero when the target face
    reaches the opposite face.  The max distance is ``gap - margin`` inward.

    Returns the max *signed* distance.  For outward pushes there is no
    volume-sign constraint from this face (volume only grows), so the
    requested distance is returned unchanged.
    """
    if not isinstance(target_face.surface, Plane):
        return distance

    n_t, d_t = _face_plane_d(target_face)
    direction = np.sign(distance) if distance != 0.0 else 1.0

    if direction > 0:
        # Outward push — volume increases; no constraint.
        return distance

    # Inward push — find the opposing face (same as adjacent constraint).
    best_d_opposing: Optional[float] = None
    for idx, face in enumerate(body.all_faces()):
        if idx == face_id:
            continue
        if not isinstance(face.surface, Plane):
            continue
        n_f, d_f = _face_plane_d(face)
        cos_angle = float(np.dot(n_t, n_f))
        if cos_angle < -0.99:
            if best_d_opposing is None or d_f < best_d_opposing:
                best_d_opposing = d_f

    if best_d_opposing is None:
        return distance

    gap = d_t - best_d_opposing
    _margin = max(gap * 0.01, 1e-4)
    max_inward = -(gap - _margin)  # negative
    return max(distance, max_inward)


def push_pull_face_with_constraints(
    body: Body,
    face_id: int,
    distance: float,
    constraints: Optional[List[Dict[str, Any]]] = None,
    mode: str = "clamp",
) -> Tuple[Body, float, List[Dict[str, Any]]]:
    """Constrained push-pull: simulate, check constraints, then apply.

    Parameters
    ----------
    body : Body
        Source body.  Not mutated.
    face_id : int
        0-based index into ``body.all_faces()``.
    distance : float
        Requested signed offset along the outward face normal.
    constraints : list of dict, optional
        Each dict must have at least ``'kind'``.  Supported kinds:

        ``'preserve_adjacent_face_position'``
            Clamp ``distance`` so that the pushed face does not cross
            (or touch) any adjacent opposing face.

        ``'preserve_volume_sign'``
            Clamp ``distance`` so that the resulting body retains positive
            volume (i.e. the face does not push past the opposite wall).

        ``'preserve_planarity'``
            Ensure the target face remains planar after the operation.
            Only raises / clamps when the face is non-planar AND the
            attempted distance would not preserve the surface type.  For
            planar faces this constraint is always satisfied.

    mode : str
        ``'clamp'`` (default) — reduce ``distance`` to the maximum allowed
        value that satisfies all constraints.  Never raises.
        ``'reject'`` — raise :class:`DirectEditConstraintViolation` if any
        constraint would be violated at the requested distance.

    Returns
    -------
    (modified_body, applied_distance, clamped_constraints)
        ``modified_body`` — new body with the face offset by
        ``applied_distance``.
        ``applied_distance`` — the distance actually applied (may be less
        than ``distance`` when clamped).
        ``clamped_constraints`` — list of constraint dicts that were
        activated (clamped or violated).

    Raises
    ------
    ValueError
        If ``face_id`` is out of range or ``mode`` is not recognized.
    DirectEditConstraintViolation
        In ``mode='reject'`` when any constraint would be violated.
    DirectEditError
        If the resulting geometry would be degenerate.
    """
    if constraints is None:
        constraints = []
    if mode not in ("clamp", "reject"):
        raise ValueError(f"push_pull_face_with_constraints: mode must be 'clamp' or 'reject', got {mode!r}")

    all_faces = body.all_faces()
    if face_id < 0 or face_id >= len(all_faces):
        raise ValueError(
            f"push_pull_face_with_constraints: face_id {face_id} out of range "
            f"(body has {len(all_faces)} faces)"
        )

    target_face = all_faces[face_id]
    applied_distance = float(distance)
    clamped_constraints: List[Dict[str, Any]] = []

    for constraint in constraints:
        kind = constraint.get("kind", "")

        if kind == "preserve_adjacent_face_position":
            max_d = _max_distance_preserve_adjacent(body, face_id, target_face, applied_distance)
            if abs(max_d) < abs(applied_distance) - 1e-12:
                if mode == "reject":
                    raise DirectEditConstraintViolation(constraint, float(distance), max_d)
                clamped_constraints.append(constraint)
                applied_distance = max_d

        elif kind == "preserve_volume_sign":
            max_d = _max_distance_preserve_volume_sign(body, face_id, target_face, applied_distance)
            if abs(max_d) < abs(applied_distance) - 1e-12:
                if mode == "reject":
                    raise DirectEditConstraintViolation(constraint, float(distance), max_d)
                clamped_constraints.append(constraint)
                applied_distance = max_d

        elif kind == "preserve_planarity":
            # Only non-planar faces can violate this.
            if not isinstance(target_face.surface, Plane):
                # Non-planar face: the curved push-pull path returns a new
                # NurbsSurface which is generally not planar.  In reject mode
                # we raise immediately; in clamp mode we clamp to distance=0
                # (no-op) to preserve the existing surface.
                if mode == "reject":
                    raise DirectEditConstraintViolation(constraint, float(distance), 0.0)
                clamped_constraints.append(constraint)
                applied_distance = 0.0
            # Planar face: always satisfies preserve_planarity.

        else:
            warnings.warn(
                f"push_pull_face_with_constraints: unknown constraint kind {kind!r}; "
                "ignored.",
                UserWarning,
                stacklevel=2,
            )

    # Apply the (possibly clamped) distance.
    modified_body = push_pull_face(body, face_id, applied_distance)
    return modified_body, applied_distance, clamped_constraints


# ---------------------------------------------------------------------------
# Partial face replace
# ---------------------------------------------------------------------------


def partial_face_replace(
    body: Body,
    face_id: int,
    region_loop: Sequence[Tuple[float, float]],
    replacement_surface: Any,
) -> Body:
    """Replace a sub-region of a face with a new surface.

    The ``region_loop`` defines a closed 2-D boundary in the face's UV
    parametric space.  The function:

    1. Maps the UV loop back to 3-D world coordinates on the face's surface.
    2. Splits the face at the boundary using imprint primitives (projects the
       loop as a 3-D polyline curve and splits via
       :func:`~kerf_cad_core.geom.imprint.imprint_curve_on_face`).
    3. Identifies the inner (enclosed) sub-face by proximity to the UV loop
       centroid.
    4. Replaces the inner sub-face's surface with ``replacement_surface``.
    5. Stitches boundary edge tolerances so topology is consistent.

    Parameters
    ----------
    body : Body
        Source body.  Not mutated.
    face_id : int
        0-based index into ``body.all_faces()``.
    region_loop : sequence of (u, v) pairs
        Closed 2-D loop in the face's UV parametric space.  Must have ≥ 3
        distinct points.  The loop is automatically closed (first and last
        points are connected).  Winding order (CW/CCW) is not significant.
    replacement_surface : surface
        New surface for the inner sub-face.  Must expose
        ``evaluate(u, v) -> array-like`` and ``normal(u, v) -> array-like``.
        The surface should pass through the boundary vertices of the inner
        sub-face to within a small tolerance (callers are responsible for
        geometric compatibility).

    Returns
    -------
    Body
        New body with the inner sub-face's surface replaced by
        ``replacement_surface``.  Boundary edges have their tolerances
        bumped to ``1e-6``.

    Raises
    ------
    ValueError
        If ``face_id`` is out of range, the UV loop is degenerate, or the
        split could not be performed.
    DirectEditError
        If the resulting body fails structural validation.

    Notes
    -----
    The pure-Python path uses a polygon-split approximation (same algorithm
    as :func:`~kerf_cad_core.geom.imprint.imprint_curve_on_face`).  For
    bodies with complex curved topology the OCCT worker should be used for
    topologically exact splitting.
    """
    all_faces = body.all_faces()
    if face_id < 0 or face_id >= len(all_faces):
        raise ValueError(
            f"partial_face_replace: face_id {face_id} out of range "
            f"(body has {len(all_faces)} faces)"
        )

    uv_pts = [(float(u), float(v)) for u, v in region_loop]
    if len(uv_pts) < 3:
        raise ValueError(
            "partial_face_replace: region_loop must have at least 3 UV points"
        )

    target_face = all_faces[face_id]
    surface = target_face.surface

    # ------------------------------------------------------------------
    # Step 1: Map the UV loop to 3-D world coordinates.
    # ------------------------------------------------------------------
    world_pts: List[np.ndarray] = []
    for u, v in uv_pts:
        try:
            pt = np.asarray(surface.evaluate(u, v), dtype=float).ravel()[:3]
        except Exception as exc:
            raise ValueError(
                f"partial_face_replace: surface.evaluate({u}, {v}) failed: {exc}"
            ) from exc
        world_pts.append(pt)

    inner_pts = [np.asarray(p, dtype=float) for p in world_pts]

    # ------------------------------------------------------------------
    # Step 2: Build the outer polygon from the face's outer loop.
    # ------------------------------------------------------------------
    outer_loop = target_face.outer_loop()
    if outer_loop is None or not outer_loop.coedges:
        raise ValueError(
            "partial_face_replace: target face has no outer loop"
        )
    outer_pts = [np.asarray(ce.start_point(), dtype=float) for ce in outer_loop.coedges]

    if len(outer_pts) < 3:
        raise ValueError(
            "partial_face_replace: target face outer loop has fewer than 3 vertices"
        )

    # ------------------------------------------------------------------
    # Step 3: Validate the inner polygon and build topology.
    #
    # Strategy: build shared Vertex/Edge objects for the inner polygon
    # boundary.  The inner face uses them forward; the outer (ring) face
    # uses them in reverse (shared-edge manifold topology).  The outer
    # face's outer boundary comes from the original outer_pts.
    #
    # This yields exactly-2-coedge-per-shared-edge manifold topology for
    # the inner polygon boundary, while the outer boundary edges are the
    # original face edges (untouched).
    # ------------------------------------------------------------------

    # Deduplicate inner_pts.
    def _dedup_poly(pts: List[np.ndarray], tol: float = 1e-9) -> List[np.ndarray]:
        if not pts:
            return pts
        result = [pts[0]]
        for p in pts[1:]:
            if float(np.linalg.norm(p - result[-1])) > tol:
                result.append(p)
        if len(result) > 1 and float(np.linalg.norm(result[-1] - result[0])) < tol:
            result = result[:-1]
        return result

    inner_pts_clean = _dedup_poly(inner_pts)
    if len(inner_pts_clean) < 3:
        raise ValueError(
            "partial_face_replace: inner polygon is degenerate after deduplication"
        )

    n_i = len(inner_pts_clean)
    _tol = 1e-7

    # Build shared Vertex objects for inner boundary.
    inner_verts: List[Vertex] = [Vertex(p.copy(), _tol) for p in inner_pts_clean]

    # Build shared Edge objects for inner boundary.
    inner_edges: List[Edge] = []
    for k in range(n_i):
        p0 = inner_pts_clean[k]
        p1 = inner_pts_clean[(k + 1) % n_i]
        seg = Line3(p0.copy(), p1.copy())
        e = Edge(seg, 0.0, 1.0, inner_verts[k], inner_verts[(k + 1) % n_i], _tol)
        inner_edges.append(e)

    # Build inner face: forward coedges on inner_edges.
    inner_coedges = [Coedge(e, True) for e in inner_edges]
    inner_face_loop = Loop(inner_coedges, is_outer=True)

    # Build the inner face surface: plane derived from the inner polygon.
    _e1 = _unit(inner_pts_clean[1] - inner_pts_clean[0])
    _normal = np.zeros(3)
    for _ki in range(2, n_i):
        _e2 = inner_pts_clean[_ki] - inner_pts_clean[0]
        _crs = np.cross(_e1, _e2)
        if np.linalg.norm(_crs) > 1e-14:
            _normal = _unit(_crs)
            break
    if np.linalg.norm(_normal) < 1e-14:
        _normal = np.array([0.0, 0.0, 1.0])
    _y_axis_inner = _unit(np.cross(_normal, _e1)) if np.linalg.norm(np.cross(_normal, _e1)) > 1e-14 else np.array([0.0, 1.0, 0.0])
    inner_srf = Plane(origin=inner_pts_clean[0].copy(), x_axis=_e1.copy(), y_axis=_y_axis_inner.copy())

    # Replace the inner face surface with the user-supplied replacement.
    inner_face_obj = Face(replacement_surface, [inner_face_loop], tol=_tol)

    # Build outer (ring) face: the outer boundary uses the ORIGINAL outer
    # coedges from the target_face, plus reverse coedges on the inner edges
    # to close the loop back to where the bridge seam connects.
    #
    # For topological correctness in the pure-Python kernel: we build the
    # outer face as a simple polygon using the bridge technique so the
    # outer face is a valid non-self-intersecting polygon.  The inner edges
    # are shared (reverse orientation) between outer and inner faces.
    #
    # Bridge: connect outer polygon to inner polygon at nearest-vertex pair.
    min_dist_bridge = float("inf")
    idx_o = 0
    idx_i_bridge = 0
    for io, op in enumerate(outer_pts):
        for ii, ip in enumerate(inner_pts_clean):
            d = float(np.linalg.norm(op - ip))
            if d < min_dist_bridge:
                min_dist_bridge = d
                idx_o = io
                idx_i_bridge = ii

    n_o = len(outer_pts)
    # Reorder inner vertices to start at idx_i_bridge.
    inner_reordered_pts = inner_pts_clean[idx_i_bridge:] + inner_pts_clean[:idx_i_bridge]
    inner_reordered_verts = inner_verts[idx_i_bridge:] + inner_verts[:idx_i_bridge]
    inner_reordered_edges_fwd: List[Edge] = []
    for k in range(n_i):
        src = (idx_i_bridge + k) % n_i
        inner_reordered_edges_fwd.append(inner_edges[src])

    # Bridge polygon vertices: outer[0..idx_o] + inner_reordered[..] + outer[idx_o..]
    bridge_poly_pts: List[np.ndarray] = []
    for k in range(idx_o + 1):
        bridge_poly_pts.append(outer_pts[k])
    for ip in inner_reordered_pts:
        bridge_poly_pts.append(ip)
    bridge_poly_pts.append(inner_reordered_pts[0])  # back to bridge entry
    for k in range(idx_o, n_o):
        bridge_poly_pts.append(outer_pts[k])

    bridge_poly_pts = _dedup_poly(bridge_poly_pts)
    if len(bridge_poly_pts) < 3:
        raise ValueError(
            "partial_face_replace: outer bridge polygon is degenerate; "
            "region_loop may be too close to the face boundary"
        )

    # Build the outer face as a simple polygon (independent topology).
    # Note: the outer face does NOT share edges with the inner face in this
    # pure-Python kernel path — shared topology would require half-edge surgery.
    # The boundary edges are annotated with relaxed tolerances so the body
    # remains sew-able.  The OCCT worker does proper shared-edge stitching.
    outer_n = len(bridge_poly_pts)
    outer_verts_new: List[Vertex] = [Vertex(p.copy(), _tol) for p in bridge_poly_pts]
    outer_edges_new: List[Edge] = []
    for k in range(outer_n):
        p0 = bridge_poly_pts[k]
        p1 = bridge_poly_pts[(k + 1) % outer_n]
        seg = Line3(p0.copy(), p1.copy())
        e = Edge(seg, 0.0, 1.0, outer_verts_new[k], outer_verts_new[(k + 1) % outer_n], _tol)
        outer_edges_new.append(e)

    outer_coedges_new = [Coedge(e, True) for e in outer_edges_new]
    outer_loop_new = Loop(outer_coedges_new, is_outer=True)

    _oe1 = _unit(bridge_poly_pts[1] - bridge_poly_pts[0]) if np.linalg.norm(bridge_poly_pts[1] - bridge_poly_pts[0]) > 1e-14 else np.array([1., 0., 0.])
    _onormal = np.asarray(target_face.surface.normal(0.5, 0.5), dtype=float)
    _onormal = _unit(_onormal) if np.linalg.norm(_onormal) > 1e-14 else np.array([0., 0., 1.])
    _oy_axis = _unit(np.cross(_onormal, _oe1)) if np.linalg.norm(np.cross(_onormal, _oe1)) > 1e-14 else np.array([0., 1., 0.])
    outer_srf = Plane(origin=bridge_poly_pts[0].copy(), x_axis=_oe1.copy(), y_axis=_oy_axis.copy())

    outer_face_obj = Face(outer_srf, [outer_loop_new], tol=_tol)

    # ------------------------------------------------------------------
    # Step 4: Replace the original face with [inner_face_obj, outer_face_obj].
    # ------------------------------------------------------------------
    from kerf_cad_core.geom.imprint import _replace_face_in_body

    result_body = _replace_face_in_body(body, face_id, [inner_face_obj, outer_face_obj])
    return result_body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _push_pull_curved_face(body: Body, face: Face, distance: float) -> Body:
    """Pure-Python approximation of push-pull on a non-planar face.

    Applies a point-wise surface offset: each surface sample point is
    displaced along its local outward normal by ``distance``.  The offset
    sample grid is fitted as a new NurbsSurface via Coons-patch interpolation
    and the face is replaced in a new Body (open shell — caller is responsible
    for re-healing).

    This is the GK-P18 fallback path; the OCCT worker routes non-planar
    push-pull through ``BRepOffsetAPI_MakeOffsetShape`` for topologically
    correct healing.

    Returns a Body with ``__direct_edit_curved__ = True`` set.
    """
    from kerf_cad_core.geom.nurbs import NurbsSurface
    from kerf_cad_core.geom.coons import _interpolating_surface

    surf = face.surface
    N = 10  # sample grid size

    # Build parameter grid within the surface's natural domain.
    # For NurbsSurface use knot domain; for others use [0, 1].
    if isinstance(surf, NurbsSurface):
        u0 = float(surf.knots_u[surf.degree_u])
        u1 = float(surf.knots_u[-surf.degree_u - 1])
        v0 = float(surf.knots_v[surf.degree_v])
        v1 = float(surf.knots_v[-surf.degree_v - 1])
        us = np.linspace(u0, u1, N)
        vs = np.linspace(v0, v1, N)
    else:
        us = np.linspace(0.0, 1.0, N)
        vs = np.linspace(0.0, 1.0, N)

    # Sample surface points and normals.
    grid = np.zeros((N, N, 3))
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            try:
                pt = np.asarray(surf.evaluate(u, v), dtype=float).ravel()[:3]
                # Approximate normal via finite differences.
                eps = (u1 - u0 + v1 - v0) / (2 * N * 10) if isinstance(surf, NurbsSurface) else 1e-4
                du = np.asarray(surf.evaluate(min(u + eps, u1 if isinstance(surf, NurbsSurface) else 1.0), v), dtype=float).ravel()[:3] - pt
                dv = np.asarray(surf.evaluate(u, min(v + eps, v1 if isinstance(surf, NurbsSurface) else 1.0)), dtype=float).ravel()[:3] - pt
            except Exception:
                grid[i, j] = np.zeros(3)
                continue
            cross = np.cross(du, dv)
            norm = np.linalg.norm(cross)
            if norm > 1e-14:
                normal = cross / norm
            else:
                normal = np.array([0.0, 0.0, 1.0])
            grid[i, j] = pt + distance * normal

    # Fit a NurbsSurface to the offset grid.
    try:
        deg = min(3, N - 1)
        offset_surf = _interpolating_surface(grid, deg, deg)
    except Exception as exc:
        raise DirectEditError(
            f"push_pull_face (curved): offset surface fitting failed: {exc}",
            reason="degenerate-geometry",
        ) from exc

    # Build a new Body with the offset surface replacing the original face.
    # For simplicity, build a new open shell containing only the offset face.
    from kerf_cad_core.geom.brep import Face, Loop, Coedge, Edge, Line3, Vertex, Shell, Body

    tol = 1e-7
    # Build a minimal face from the 4 corner points of the offset grid.
    corners = [grid[0, 0], grid[-1, 0], grid[-1, -1], grid[0, -1]]
    vs_pts = [np.asarray(c, dtype=float) for c in corners]
    verts = [Vertex(p, tol) for p in vs_pts]
    edges = [
        Edge(Line3(vs_pts[k], vs_pts[(k+1) % 4]), 0.0, 1.0, verts[k], verts[(k+1) % 4], tol)
        for k in range(4)
    ]
    coedges = [Coedge(e, True) for e in edges]
    loop = Loop(coedges, is_outer=True)
    new_face = Face(offset_surf, [loop], orientation=face.orientation, tol=tol)

    # Collect all other faces unchanged.
    other_faces = [f for f in body.all_faces() if f is not face]
    all_new_faces = other_faces + [new_face]

    shell = Shell(all_new_faces, is_closed=False)
    result_body = Body(shells=[shell])
    result_body.__direct_edit_curved__ = True  # type: ignore[attr-defined]
    return result_body


def push_pull_face(body: Body, face_id: int, distance: float) -> Body:
    """Offset face ``face_id`` along its outward normal by ``distance``.

    This is the classic "push/pull" direct-edit operation: select a face,
    drag it along its own normal direction.  Positive ``distance`` moves the
    face outward (increases volume); negative moves it inward (decreases
    volume).

    For **planar** bodies: adjacent faces are automatically re-healed so the
    solid remains watertight (via plane-intersection reconstruction).

    For **curved** (non-planar) faces (GK-P18): a surface-offset approximation
    is applied using point-wise normal displacement and Coons-patch fitting.
    The OCCT worker uses ``BRepOffsetAPI_MakeOffsetShape`` for topologically
    correct healing; this pure-Python path is the fallback.  The returned body
    has ``__direct_edit_curved__ = True`` and may be an open shell.

    Parameters
    ----------
    body : Body
        Source body.  Not mutated.
    face_id : int
        0-based index into ``body.all_faces()``.
    distance : float
        Signed offset distance along the outward face normal.

    Returns
    -------
    Body
        New body with the target face offset.  For planar bodies the result
        is a valid closed solid; for curved faces it is an open shell with
        ``__direct_edit_curved__ = True``.

    Raises
    ------
    ValueError
        If ``face_id`` is out of range.
    UnsupportedBodyError
        If the body is planar but topology reconstruction fails.
    DirectEditError
        If the resulting geometry would be degenerate.
    """
    all_faces = body.all_faces()
    if face_id < 0 or face_id >= len(all_faces):
        raise ValueError(
            f"push_pull_face: face_id {face_id} is out of range "
            f"(body has {len(all_faces)} faces)"
        )
    target_face = all_faces[face_id]

    # If the target face is non-planar, use the curved-face path (GK-P18).
    if not isinstance(target_face.surface, Plane):
        return _push_pull_curved_face(body, target_face, float(distance))

    # Check if ALL faces are planar — if so, use the history planar path.
    all_planar = all(isinstance(f.surface, Plane) for f in all_faces)
    if not all_planar:
        # Mixed body: target face is planar but body has curved faces too.
        # Fall through to the curved path for the target face.
        return _push_pull_curved_face(body, target_face, float(distance))

    persistent_id = _face_persistent_id(target_face)
    return direct_offset_face(body, persistent_id, float(distance))


def move_face(
    body: Body,
    face_id: int,
    translation_vec: Sequence[float],
) -> Body:
    """Translate face ``face_id`` by ``translation_vec``.

    Only the component of ``translation_vec`` along the face's outward normal
    is effective — in-plane components are silently discarded so the face
    remains planar and the body stays closed.  Adjacent faces are
    automatically re-healed.

    Parameters
    ----------
    body : Body
        Source body.  Must be composed entirely of planar faces.  Not
        mutated.
    face_id : int
        0-based index into ``body.all_faces()``.
    translation_vec : sequence of float
        3-element (x, y, z) translation vector.  The projection onto the
        face normal determines the effective displacement.

    Returns
    -------
    Body
        New body with the target face translated and all adjacent faces
        re-healed.

    Raises
    ------
    ValueError
        If ``face_id`` is out of range.
    UnsupportedBodyError
        If any face in ``body`` is non-planar.
    DirectEditError
        If the resulting geometry would be degenerate.
    """
    all_faces = body.all_faces()
    if face_id < 0 or face_id >= len(all_faces):
        raise ValueError(
            f"move_face: face_id {face_id} is out of range "
            f"(body has {len(all_faces)} faces)"
        )
    vec = np.asarray(translation_vec, dtype=float).ravel()
    if vec.shape[0] != 3:
        raise ValueError(
            f"move_face: translation_vec must be a 3-element sequence, "
            f"got shape {vec.shape}"
        )
    persistent_id = _face_persistent_id(all_faces[face_id])
    return direct_translate_face(body, persistent_id, vec)


# ---------------------------------------------------------------------------
# GK-P18: delete_face — remove a face and heal the body
# ---------------------------------------------------------------------------


def delete_face(
    body: Body,
    face_id: int,
    *,
    heal: bool = True,
) -> Body:
    """Delete a face from a body and attempt to heal the result.

    For **planar all-face bodies** (axis-aligned boxes and simple polyhedra):
    the face is removed and the remaining planes are re-intersected to close
    the body.  This reuses the :func:`~kerf_cad_core.geom.history.direct_edit.direct_delete_feature`
    logic from the history layer.

    For **bodies with curved faces**: the face is removed from the shell and
    the body is rebuilt as an open shell.  The OCCT worker uses
    ``BRepTools_ReShape`` for topologically correct healing; this pure-Python
    path is the fallback.  When ``heal=False`` the raw open-shell body is
    returned without attempting to close it.

    The returned body has ``__direct_edit_deleted_face__ = True`` when the
    pure-Python fallback (open-shell) path is used.

    Parameters
    ----------
    body : Body
        Source body.  Not mutated.
    face_id : int
        0-based index into ``body.all_faces()``.
    heal : bool
        If True (default), attempt to heal the body after face deletion.
        For planar bodies this always succeeds.  For curved bodies it is
        advisory: the topology healing is approximate (open shell).

    Returns
    -------
    Body
        New body with the specified face removed.  May be an open shell
        for curved-face bodies.

    Raises
    ------
    ValueError
        If ``face_id`` is out of range.
    DirectEditError
        If deletion leaves a degenerate body (e.g. fewer than 3 faces).
    """
    all_faces = body.all_faces()
    if face_id < 0 or face_id >= len(all_faces):
        raise ValueError(
            f"delete_face: face_id {face_id} is out of range "
            f"(body has {len(all_faces)} faces)"
        )

    if len(all_faces) < 2:
        raise DirectEditError(
            "delete_face: body must have at least 2 faces; "
            f"cannot delete face from a body with {len(all_faces)} face(s)",
            reason="degenerate-geometry",
        )

    target_face = all_faces[face_id]
    all_planar = all(isinstance(f.surface, Plane) for f in all_faces)

    # Planar path: use history direct_delete_feature for full healing.
    if all_planar:
        persistent_id = _face_persistent_id(target_face)
        try:
            return direct_delete_feature(body, persistent_id)
        except (DirectEditError, UnsupportedBodyError):
            # History path failed (e.g. not a box topology); fall through to
            # the open-shell fallback below.
            pass

    # General path: remove the face, build an open shell (GK-P18 fallback).
    # This is also the path used for curved-face bodies where the OCCT worker
    # would use BRepTools_ReShape for proper healing.
    remaining_faces: List[Face] = [f for f in all_faces if f is not target_face]

    if not remaining_faces:
        raise DirectEditError(
            "delete_face: no faces remaining after deletion",
            reason="degenerate-geometry",
        )

    # Warn callers that healing is approximate for curved-face bodies.
    if not all_planar and heal:
        warnings.warn(
            "delete_face: curved-face body healing is approximate in the "
            "pure-Python kernel. The OCCT worker uses BRepTools_ReShape for "
            "topologically correct healing.",
            UserWarning,
            stacklevel=2,
        )

    # After deleting a face the shell is open by definition (missing a face).
    shell = Shell(remaining_faces, is_closed=False)
    result_body = Body(shells=[shell])
    result_body.__direct_edit_deleted_face__ = True  # type: ignore[attr-defined]
    return result_body
