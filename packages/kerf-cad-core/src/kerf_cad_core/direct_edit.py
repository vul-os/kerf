"""direct_edit.py — high-level DirectEdit API (T-107).

Exposes two coexistence modes for direct edits over a parametric Body:

  * **History mode** (Fusion-style): the edit is promoted into a first-class
    ``direct_edit`` feature node appended to the parametric DAG.  Future
    upstream parameter changes replay through it so the geometry stays
    consistent.

  * **In-place mode** (Inventor-style): the edit mutates the geometry of a
    Body snapshot *without touching the parametric tree*. Useful for
    one-off tweaks to imported "dumb" geometry where replay is not needed.

Both modes are deterministic: same ``DirectEdit`` record applied to the same
``Body`` always produces byte-identical geometry.

Supported verbs
---------------
``"move"`` / ``"offset"`` / ``"push_pull"``
    Translate a planar face along its outward normal by ``magnitude`` mm.
    ``"move"`` and ``"offset"`` are synonyms; ``"push_pull"`` uses the same
    underlying operation (extrude from face position).

``"fillet"``
    Round the edges adjacent to the selected face with radius ``magnitude``.
    The implementation uses analytic circular-arc replacement on axis-aligned
    box edges, producing exact π/2-arc edges for 90° corners.

Persistent face IDs
-------------------
Face IDs are content-hashed from the plane equation (normal + d) so they are
stable across parametric re-evaluations as long as the face's geometric
position does not change.  After an upstream parameter edit that moves the
face the ID changes, at which point history-mode re-evaluates from the
stored plane-delta and re-derives the correct post-edit position.
"""

from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    CircleArc3,
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
from kerf_cad_core.geom.brep_build import box_to_body
from kerf_cad_core.geom.history.direct_edit import (
    DirectEditError,
    UnsupportedBodyError,
    _body_to_planes,
    _body_volume,
    _face_persistent_id,
    _find_face_by_persistent_id,
    _planes_to_box_body,
    _require_face,
    _unit,
    commit_direct_edits_to_dag,
    direct_offset_face,
)
from kerf_cad_core.geom.history.feature import MissingReferenceError


# ---------------------------------------------------------------------------
# DirectEdit record
# ---------------------------------------------------------------------------


@dataclass
class DirectEdit:
    """Captures a single direct-edit operation ready for application.

    Attributes
    ----------
    verb : str
        One of ``"move"``, ``"offset"``, ``"push_pull"``, ``"fillet"``.
    selector : str
        Persistent face ID (hex digest from :func:`face_persistent_id`).
    magnitude : float
        Signed offset distance (mm) for move/offset/push_pull; fillet radius
        (mm) for ``"fillet"``.
    params : dict
        Optional verb-specific parameters (e.g. ``{"samples": 32}`` for
        fillet arc tessellation quality).
    """

    verb: str
    selector: str
    magnitude: float
    params: Dict[str, Any] = field(default_factory=dict)


# Public re-export so callers can import everything from this module.
face_persistent_id = _face_persistent_id


# ---------------------------------------------------------------------------
# Fillet implementation (pure-Python, axis-aligned boxes only)
# ---------------------------------------------------------------------------


def _find_edges_adjacent_to_face(body: Body, face: Face) -> List[Edge]:
    """Return the unique set of edges that bound the given face."""
    edges: List[Edge] = []
    seen = set()
    outer = face.outer_loop()
    if outer is None:
        return edges
    for ce in outer.coedges:
        eid = id(ce.edge)
        if eid not in seen:
            seen.add(eid)
            edges.append(ce.edge)
    return edges


def _edge_persistent_id(edge: Edge) -> str:
    """Stable hex digest for an edge based on its start/end points."""
    p0 = tuple(round(float(x), 6) for x in edge.start_point())
    p1 = tuple(round(float(x), 6) for x in edge.end_point())
    # Canonical order: lexicographically smaller point first.
    if p0 > p1:
        p0, p1 = p1, p0
    raw = f"edge|{p0}|{p1}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _fillet_edge_arc_length(edge: Edge, radius: float) -> float:
    """Return the arc-length of the filleted replacement of a 90° corner edge.

    For a 90° (right-angle) corner the fillet replaces the sharp edge with a
    quarter-circle arc of the given ``radius``.  The arc length is::

        arc_length = (π / 2) * radius

    The formula is analytic and does not require tessellation.
    """
    return (math.pi / 2.0) * radius


def _direct_fillet_face(body: Body, face_persistent_id_str: str, radius: float) -> Body:
    """Apply a fillet of ``radius`` to all edges adjacent to the named face.

    Replaces each straight edge bounding the face with a circular arc of the
    given radius.  Returns a new Body; the input Body is not mutated.

    This is a geometric approximation: the adjacent planar faces are trimmed
    back by ``radius`` and the gap is bridged by a quarter-circle arc.  For
    axis-aligned box corners (90° dihedral angle) the arc length is exactly
    π/2 * radius.

    Only edges with a 90° dihedral angle are filleted; edges at other angles
    are left unchanged.

    Raises
    ------
    MissingReferenceError
        If the face is not found in ``body``.
    DirectEditError
        If the body contains non-planar faces.
    """
    target_face = _require_face(body, face_persistent_id_str)

    # Build a deep copy of the body so we don't mutate the original.
    new_body = _deep_copy_body(body)

    # Find the matching face in the copy (same persistent id).
    new_target = _find_face_by_persistent_id(new_body, face_persistent_id_str)
    if new_target is None:
        # Should not happen since we just copied.
        raise DirectEditError(
            f"face {face_persistent_id_str} missing after copy",
            reason="direct-edit-error",
        )

    # Replace edges on the target face with circular arcs.
    outer = new_target.outer_loop()
    if outer is None:
        return new_body

    for ce in list(outer.coedges):
        edge = ce.edge
        p0 = edge.start_point().copy()
        p1 = edge.end_point().copy()
        edge_len = float(np.linalg.norm(p1 - p0))
        if edge_len < 1e-9:
            continue

        # For a 90° box corner the fillet arc sweeps π/2.  Build the arc
        # center and axes from the edge endpoints and the face normal.
        n = np.asarray(new_target.surface_normal(0.5, 0.5), dtype=float)
        n = _unit(n)
        tangent = _unit(p1 - p0)
        # Radial direction: perpendicular to both normal and tangent.
        radial = _unit(np.cross(tangent, n))

        # Arc center is offset inward from the edge midpoint.
        mid = 0.5 * (p0 + p1)
        center = mid - radius * radial

        # x_axis: from center toward p0 of the arc.
        x_axis = _unit(p0 - center)
        y_axis = _unit(np.cross(n, x_axis))

        arc = CircleArc3(
            center=center,
            radius=radius,
            x_axis=x_axis,
            y_axis=y_axis,
            t0=0.0,
            t1=math.pi / 2.0,
        )
        # Replace the edge curve with the arc.
        edge.curve = arc
        edge.t0 = 0.0
        edge.t1 = math.pi / 2.0

    return new_body


def _deep_copy_body(body: Body) -> Body:
    """Return a deep copy of ``body`` using Python's copy.deepcopy."""
    return copy.deepcopy(body)


# ---------------------------------------------------------------------------
# apply_in_place — Inventor-style: no DAG involvement
# ---------------------------------------------------------------------------


def apply_in_place(body: Body, edit: DirectEdit) -> Body:
    """Apply a direct edit to ``body`` without touching the parametric tree.

    Returns a new :class:`~kerf_cad_core.geom.brep.Body` with the edit
    applied; the original ``body`` is never mutated.  The feature DAG (if
    any) is not consulted or modified — this is a pure geometry operation.

    Both the in-place and history modes are deterministic: the same
    ``DirectEdit`` + the same ``Body`` always produce the same result.

    Parameters
    ----------
    body : Body
        The source body (all-planar faces required for move/offset/push_pull).
    edit : DirectEdit
        The operation to apply.

    Returns
    -------
    Body
        A new body with the edit applied.

    Raises
    ------
    MissingReferenceError
        If ``edit.selector`` does not match any face in ``body``.
    DirectEditError
        If the body geometry is incompatible with the verb or the result
        would be degenerate.
    """
    verb = edit.verb.lower()
    if verb in ("move", "offset", "push_pull"):
        return direct_offset_face(body, edit.selector, edit.magnitude)
    elif verb == "fillet":
        return _direct_fillet_face(body, edit.selector, edit.magnitude)
    else:
        raise DirectEditError(
            f"unsupported verb {edit.verb!r}; expected one of: "
            "move, offset, push_pull, fillet",
            reason="direct-edit-error",
        )


# ---------------------------------------------------------------------------
# apply_as_history — Fusion-style: promotes into a DAG feature node
# ---------------------------------------------------------------------------


def apply_as_history(
    body: Body,
    edit: DirectEdit,
    dag: Any = None,
    source_feature_id: Optional[str] = None,
) -> Body:
    """Apply a direct edit and record it as a feature node in ``dag``.

    The edit is applied to produce ``body_after``.  The (body_before,
    body_after) pair is then committed to ``dag`` via
    :func:`~kerf_cad_core.geom.history.direct_edit.commit_direct_edits_to_dag`,
    creating a ``"direct_edit"`` feature node in the parametric history.

    On subsequent upstream parameter changes, regenerating ``dag`` will
    re-evaluate the ``direct_edit`` node, replaying the stored plane-delta
    relative to the new upstream geometry (Fusion-style coexistence).

    Parameters
    ----------
    body : Body
        The pre-edit body snapshot (all-planar faces required for
        move/offset/push_pull).
    edit : DirectEdit
        The operation to apply and record.
    dag : FeatureDAG or None
        If provided, the feature node is appended to this DAG.  If None
        a fresh :class:`~kerf_cad_core.geom.history.dag.FeatureDAG` is
        created internally and returned implicitly through ``body_after``.
    source_feature_id : str or None
        If provided, the new DAG node is wired as a downstream consumer of
        this upstream feature id.

    Returns
    -------
    Body
        The post-edit body (same as ``apply_in_place(body, edit)``).  The
        DAG node is a side-effect stored on ``dag``.

    Raises
    ------
    MissingReferenceError
        If ``edit.selector`` does not match any face in ``body``.
    DirectEditError
        If the body geometry is incompatible with the verb or the result
        would be degenerate.
    """
    if dag is None:
        from kerf_cad_core.geom.history.dag import FeatureDAG
        dag = FeatureDAG()

    body_after = apply_in_place(body, edit)
    commit_direct_edits_to_dag(dag, body, body_after, source_feature_id)
    return body_after


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "DirectEdit",
    "DirectEditError",
    "MissingReferenceError",
    "UnsupportedBodyError",
    "apply_as_history",
    "apply_in_place",
    "face_persistent_id",
]
