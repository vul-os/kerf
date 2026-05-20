"""
replace_face.py
===============
GK-86 — Replace face / surface swap.

Swaps the underlying surface of one face in a :class:`Body` for a new,
compatible surface.  The topology (Vertex / Edge / Face / Loop counts)
is preserved; only ``face.surface`` is replaced.  Adjacent faces are
re-sewn so that shared-edge tolerances remain consistent.

Public API
----------
replace_face(body, face_id, new_surface) -> Body
    Return a *new* :class:`Body` in which the face at ``face_id``
    (index into ``body.all_faces()``) has its surface swapped for
    ``new_surface``.  The original ``body`` is **not** mutated.

    Compatible surface
        A surface is *compatible* when it passes within ``tol`` of every
        boundary vertex of the target face at some (u, v) -- i.e. the
        boundary wire can still be embedded on the new surface to within
        tolerance.  The function does **not** re-parameterise the
        boundary; it assumes the caller provides a geometrically
        equivalent surface (same shape, possibly different
        representation -- e.g. a Plane replaced by a degree-(1,1) NURBS
        plane).

    Post-swap actions
        1.  ``face.surface`` is set to ``new_surface``.
        2.  Shared edges that touch the swapped face have their
            ``edge.tol`` bumped to ``max(face.tol, sew_tol)`` to
            reflect that the abutting surfaces have been re-associated.
        3.  ``validate_body`` is called; a :class:`BuildError` is raised
            if the result fails validation.

Parameters
----------
body : Body
    Source body.  Not mutated.
face_id : int
    0-based index into ``body.all_faces()``.
new_surface : object
    Replacement surface (anything with ``evaluate(u, v) -> np.ndarray``
    and ``normal(u, v) -> np.ndarray``).
tol : float, optional
    Sewing tolerance applied when re-stitching edge tolerances.
    Default ``1e-6``.

Returns
-------
Body
    New body with the face's surface replaced.

Raises
------
ValueError
    If ``face_id`` is out of range.
BuildError
    If the resulting body fails :func:`validate_body`.
"""

from __future__ import annotations

import copy
from typing import List, Optional

from kerf_cad_core.geom.brep import (
    Body,
    Coedge,
    Edge,
    Face,
    Loop,
    Shell,
    Solid,
    Vertex,
    validate_body,
)
from kerf_cad_core.geom.brep_build import BuildError

__all__ = ["replace_face"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _clone_vertex(v: Vertex) -> Vertex:
    import numpy as np
    new_v = Vertex(np.array(v.point, dtype=float), v.tol)
    return new_v


def _clone_body(body: Body) -> tuple:
    """Deep-clone a Body, returning (new_body, face_map, vertex_map, edge_map).

    ``face_map``   : {id(old_face)   -> new_face}
    ``vertex_map`` : {id(old_vertex) -> new_vertex}
    ``edge_map``   : {id(old_edge)   -> new_edge}

    All topological linkages are replicated on the new objects.
    """
    import numpy as np

    vertex_map: dict = {}
    edge_map: dict = {}
    coedge_map: dict = {}
    loop_map: dict = {}
    face_map: dict = {}

    # --- pass 1: vertices ---
    def _get_vertex(v: Vertex) -> Vertex:
        key = id(v)
        if key not in vertex_map:
            vertex_map[key] = Vertex(np.array(v.point, dtype=float), v.tol)
        return vertex_map[key]

    # --- pass 2: edges (require vertices) ---
    def _get_edge(e: Edge) -> Edge:
        key = id(e)
        if key not in edge_map:
            vs = _get_vertex(e.v_start)
            ve = _get_vertex(e.v_end)
            new_e = Edge(e.curve, e.t0, e.t1, vs, ve, e.tol)
            # Edge.__post_init__ already initialises coedges=[]
            edge_map[key] = new_e
        return edge_map[key]

    # --- pass 3: coedges ---
    def _get_coedge(ce: Coedge) -> Coedge:
        key = id(ce)
        if key not in coedge_map:
            new_ce = Coedge(edge=_get_edge(ce.edge), orientation=ce.orientation)
            coedge_map[key] = new_ce
        return coedge_map[key]

    # --- pass 4: loops ---
    def _get_loop(lp: Loop) -> Loop:
        key = id(lp)
        if key not in loop_map:
            new_ces = [_get_coedge(ce) for ce in lp.coedges]
            new_lp = Loop(new_ces, is_outer=lp.is_outer)
            loop_map[key] = new_lp
        return loop_map[key]

    # --- pass 5: faces ---
    def _get_face(f: Face) -> Face:
        key = id(f)
        if key not in face_map:
            new_loops = [_get_loop(lp) for lp in f.loops]
            new_f = Face(f.surface, new_loops, orientation=f.orientation, tol=f.tol)
            face_map[key] = new_f
        return face_map[key]

    # --- build new Body hierarchy ---
    new_body = Body()
    for solid in body.solids:
        new_solid = Solid()
        for shell in solid.shells:
            new_shell = Shell(is_closed=shell.is_closed)
            for f in shell.faces:
                new_shell.add_face(_get_face(f))
            new_solid.shells.append(new_shell)
            new_shell.solid = new_solid
        new_body.solids.append(new_solid)

    for shell in body.shells:
        new_shell = Shell(is_closed=shell.is_closed)
        for f in shell.faces:
            new_shell.add_face(_get_face(f))
        new_body.shells.append(new_shell)

    return new_body, face_map, vertex_map, edge_map


def _collect_face_edges(face: Face) -> List[Edge]:
    """Return the unique Edge objects referenced by a face's coedges."""
    seen: set = set()
    out: List[Edge] = []
    for lp in face.loops:
        for ce in lp.coedges:
            if id(ce.edge) not in seen:
                seen.add(id(ce.edge))
                out.append(ce.edge)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def replace_face(
    body: Body,
    face_id: int,
    new_surface: object,
    tol: float = 1e-6,
) -> Body:
    """Swap the underlying surface of one face in *body*.

    Parameters
    ----------
    body : Body
        Source body.  Not mutated.
    face_id : int
        0-based index into ``body.all_faces()``.
    new_surface : object
        Replacement surface.  Must be compatible with the face boundary
        (same shape to within *tol*).
    tol : float
        Sewing / validation tolerance.  Default ``1e-6``.

    Returns
    -------
    Body
        New body with topology unchanged and the target face's surface
        replaced.

    Raises
    ------
    ValueError
        ``face_id`` out of range.
    BuildError
        Resulting body fails structural validation.
    """
    all_faces = body.all_faces()
    if face_id < 0 or face_id >= len(all_faces):
        raise ValueError(
            f"replace_face: face_id {face_id} is out of range "
            f"(body has {len(all_faces)} faces)"
        )

    old_target = all_faces[face_id]

    # --- deep-clone the body so the original is never mutated ---
    new_body, face_map, _vertex_map, _edge_map = _clone_body(body)

    # --- locate the cloned target face ---
    new_target: Face = face_map[id(old_target)]

    # --- swap the surface ---
    new_target.surface = new_surface

    # --- re-sew: bump edge.tol for edges shared by the swapped face so
    #     that the abutting face-pair tolerances are consistent. ----------
    for e in _collect_face_edges(new_target):
        # e here is from the cloned body (edge_map values)
        if e.tol < tol:
            e.tol = tol
        if e.tol < new_target.tol:
            e.tol = new_target.tol

    # Also propagate: vertex.tol >= incident edge.tol
    for e in _collect_face_edges(new_target):
        for v in (e.v_start, e.v_end):
            if v.tol < e.tol:
                v.tol = e.tol

    # --- validate ---
    # Only validate if the body has solids (closed shells).  Open shells
    # (sheet bodies) do not need to satisfy the Euler-Poincare relation.
    if new_body.solids:
        result = validate_body(new_body)
        if not result["ok"]:
            raise BuildError(
                f"replace_face: resulting body is invalid: {result['errors']}",
                result,
            )

    return new_body
