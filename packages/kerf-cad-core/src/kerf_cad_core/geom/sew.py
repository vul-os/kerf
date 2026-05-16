"""GK-17: tolerant face -> shell sewing.

This module is the **production** entry point for stitching an unordered
collection of independent :class:`Face` instances into a topologically
sound :class:`Shell` (and, when the result is closed, into a fully
``validate_body``-clean :class:`Body`).

Sewing semantics (BREP_CONTRACT-compliant)
------------------------------------------

* **Shared vertices**: two ``Vertex`` instances ``V1``, ``V2`` are
  merged when ``||V1.point - V2.point|| <= max(V1.tol, V2.tol, tol)``.
  All edges referencing the loser are repointed to the survivor; the
  survivor's tolerance is bumped to ``max(V1.tol, V2.tol)`` so a merge
  never *narrows* tolerance (BREP_CONTRACT §4.5).
* **Shared edges**: two ``Edge`` instances are merged when (a) their
  endpoint-representatives match (in either direction), and (b) the
  sample-based Hausdorff distance between the two parametric polylines
  (``samples=8``) is below ``tol``. Coedges are repointed; if the
  survivor runs in the opposite direction, the moved coedge's
  orientation is flipped. ``edge.tol`` is set to
  ``max(input edge tols, sew tol, incident face tol)``.
* **Coedge pairing**: after vertex+edge merging we scan every edge's
  ``coedges`` and verify exactly two coedges of *opposite* orientation
  (closed-manifold rule). ``Shell.is_closed`` is set ``True`` only when
  every edge satisfies this; otherwise the shell stays open.
* **Tolerance monotonicity**: post-sew we enforce
  ``vertex.tol >= edge.tol >= face.tol`` for every reachable triple by
  bumping the larger-numbered field upward (never inward).

Public API
~~~~~~~~~~

``sew_faces(faces, tol=1e-6) -> Shell``
    Sew an iterable of independent :class:`Face` into a :class:`Shell`.
    The shell's ``is_closed`` flag reflects whether the result is a
    closed 2-manifold. The shell is *not* placed inside a Solid/Body --
    callers wanting that can use :func:`sew_into_solid`.

``sew_into_solid(faces, tol=1e-6) -> Body``
    Sew + wrap a closed result in ``Solid(Shell)`` + ``Body``; calls
    :func:`validate_body` and raises :class:`BuildError` on any failure.

Both calls are deterministic: iteration order is the caller's input
order; cluster representatives are chosen by first-seen. Repeated
invocations on the same inputs produce identical topology counts.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    Coedge,
    Edge,
    Face,
    Shell,
    Solid,
    Vertex,
    validate_body,
)
from kerf_cad_core.geom.brep_build import BuildError, _validate_face_local


__all__ = ["sew_faces", "sew_into_solid"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collect_vertices(faces: Sequence[Face]) -> List[Vertex]:
    """Return the deterministic list of unique vertex *objects* reachable
    from the faces' coedges (deduplicated by ``id``, order preserved)."""
    seen = set()
    out: List[Vertex] = []
    for f in faces:
        for lp in f.loops:
            for ce in lp.coedges:
                for v in (ce.edge.v_start, ce.edge.v_end):
                    if id(v) not in seen:
                        seen.add(id(v))
                        out.append(v)
    return out


def _collect_edges(faces: Sequence[Face]) -> List[Edge]:
    """Return the deterministic list of unique edge *objects* reachable
    from the faces' coedges (deduplicated by ``id``)."""
    seen = set()
    out: List[Edge] = []
    for f in faces:
        for lp in f.loops:
            for ce in lp.coedges:
                if id(ce.edge) not in seen:
                    seen.add(id(ce.edge))
                    out.append(ce.edge)
    return out


def _vertex_cluster(
    vertices: Sequence[Vertex], tol: float
) -> dict:
    """Union-find by spatial coincidence.

    Two vertices ``A``, ``B`` are in the same cluster when
    ``||A.point - B.point|| <= max(A.tol, B.tol, tol)``. The first
    vertex of each cluster is the representative; later vertices in the
    same cluster point at it.

    Returns ``{id(vertex): representative_Vertex}``.
    """
    rep_of: dict = {}
    cluster_reps: List[Vertex] = []
    for v in vertices:
        found: Optional[Vertex] = None
        for rep in cluster_reps:
            thresh = max(rep.tol, v.tol, tol)
            if float(np.linalg.norm(v.point - rep.point)) <= thresh:
                found = rep
                break
        if found is None:
            cluster_reps.append(v)
            rep_of[id(v)] = v
        else:
            rep_of[id(v)] = found
            # tolerance monotonicity on merge: bump survivor's tol
            # upward but never inward (BREP_CONTRACT §4.5)
            if v.tol > found.tol:
                found.tol = v.tol
    return rep_of


def _edge_polyline(edge: Edge, n_samples: int = 8) -> np.ndarray:
    """Sample an edge's underlying curve at ``n_samples`` points."""
    n = max(2, int(n_samples))
    ts = np.linspace(edge.t0, edge.t1, n)
    return np.array([edge.point(float(t)) for t in ts])


def _hausdorff_samples(
    pl_a: np.ndarray, pl_b: np.ndarray
) -> float:
    """Symmetric sample-based Hausdorff distance between two polylines.

    Both inputs are ``(N, 3)`` and assumed *direction-aligned* (the
    caller has already aligned the endpoints). For our use case the
    sample count is small enough that the symmetric max-of-min over the
    full set is both robust and cheap.
    """
    # max over A of min over B
    ab = np.max(np.min(
        np.linalg.norm(
            pl_a[:, None, :] - pl_b[None, :, :], axis=2,
        ),
        axis=1,
    ))
    ba = np.max(np.min(
        np.linalg.norm(
            pl_b[:, None, :] - pl_a[None, :, :], axis=2,
        ),
        axis=1,
    ))
    return float(max(ab, ba))


def _curves_match(
    edge_a: Edge,
    edge_b: Edge,
    *,
    same_direction: bool,
    tol: float,
    n_samples: int = 8,
) -> bool:
    """Decide whether two edges trace the *same* curve geometry to ``tol``.

    The endpoint-rep check has already passed for the caller; here we
    inspect interior samples. ``same_direction`` is ``True`` when
    edge_a.v_start_rep == edge_b.v_start_rep (and v_end <-> v_end) --
    in that case we compare a-sample-i with b-sample-i; otherwise we
    reverse ``b`` so the parametric directions are aligned before
    comparing.
    """
    pl_a = _edge_polyline(edge_a, n_samples)
    pl_b = _edge_polyline(edge_b, n_samples)
    if not same_direction:
        pl_b = pl_b[::-1]
    return _hausdorff_samples(pl_a, pl_b) <= max(tol, 1e-12)


def _propagate_tolerance(
    faces: Sequence[Face], sew_tol: float
) -> None:
    """Enforce ``vertex.tol >= edge.tol >= face.tol`` monotonically.

    All bumps are *upward* on the larger-numbered field, never inward,
    so propagation can be applied repeatedly without narrowing any
    tolerance and without crossing the contract.
    """
    # First pass: edge.tol >= face.tol and >= sew_tol
    for f in faces:
        for lp in f.loops:
            for ce in lp.coedges:
                e = ce.edge
                if e.tol < f.tol:
                    e.tol = f.tol
                if e.tol < sew_tol:
                    e.tol = sew_tol
    # Second pass: vertex.tol >= incident edge.tol
    for f in faces:
        for lp in f.loops:
            for ce in lp.coedges:
                e = ce.edge
                for v in (e.v_start, e.v_end):
                    if v.tol < e.tol:
                        v.tol = e.tol


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def sew_faces(
    faces: Iterable[Face],
    tol: float = 1e-6,
) -> Shell:
    """Sew an iterable of :class:`Face` objects into a :class:`Shell`.

    Parameters
    ----------
    faces
        Independent faces (each with its own ``Edge``/``Vertex``
        objects) that should be stitched into a single shell.
    tol
        Linear tolerance used for vertex coincidence and edge curve
        equality. Default ``1e-6`` matches the BREP_CONTRACT
        recommendation for analytic builds.

    Returns
    -------
    Shell
        A :class:`Shell` whose ``is_closed`` flag is ``True`` iff every
        edge is used by exactly two coedges of opposite orientation
        (closed 2-manifold). The shell is **not** wrapped in a
        ``Solid``/``Body`` -- use :func:`sew_into_solid` for that.

    Notes
    -----
    The input ``Face`` objects are mutated in-place: their edges'
    ``v_start``/``v_end`` are repointed at cluster representatives, and
    duplicate edges are collapsed onto a chosen survivor. Tolerance
    fields are bumped upward to satisfy
    ``vertex.tol >= edge.tol >= face.tol``.
    """
    face_list = list(faces)
    if not face_list:
        raise BuildError("sew_faces requires at least one face")

    # 1. Cluster vertices -----------------------------------------------------
    vertices = _collect_vertices(face_list)
    rep_of_vertex = _vertex_cluster(vertices, tol)

    # 2. Repoint every edge's endpoints at the cluster reps ------------------
    edges = _collect_edges(face_list)
    for e in edges:
        e.v_start = rep_of_vertex[id(e.v_start)]
        e.v_end = rep_of_vertex[id(e.v_end)]

    # 3. Edge merge: same endpoint-rep pair (either direction) AND
    #    sample-Hausdorff equality.
    survivor_of: dict = {}  # id(edge) -> survivor Edge
    edge_buckets: List[Edge] = []
    for e in edges:
        survivor: Optional[Edge] = None
        same_direction = False
        key_fwd = (id(e.v_start), id(e.v_end))
        for cand in edge_buckets:
            ck = (id(cand.v_start), id(cand.v_end))
            if ck == key_fwd:
                if _curves_match(
                    e, cand, same_direction=True, tol=tol,
                ):
                    survivor = cand
                    same_direction = True
                    break
            elif ck == (key_fwd[1], key_fwd[0]):
                if _curves_match(
                    e, cand, same_direction=False, tol=tol,
                ):
                    survivor = cand
                    same_direction = False
                    break
        if survivor is None:
            edge_buckets.append(e)
            survivor_of[id(e)] = (e, True)
        else:
            survivor_of[id(e)] = (survivor, same_direction)
            # bump survivor.tol upward to envelope the merged edge's tol
            if e.tol > survivor.tol:
                survivor.tol = e.tol

    # 4. Repoint every coedge onto its edge's survivor; flip orientation
    #    when the survivor runs in the opposite direction.
    for f in face_list:
        for lp in f.loops:
            for ce in lp.coedges:
                old_edge = ce.edge
                survivor, same_dir = survivor_of[id(old_edge)]
                if survivor is old_edge:
                    continue
                if not same_dir:
                    ce.orientation = not ce.orientation
                ce.edge = survivor
                if ce not in survivor.coedges:
                    survivor.coedges.append(ce)
                # drop the stale coedge entry from old edge
                old_edge.coedges = [
                    c for c in old_edge.coedges if c is not ce
                ]

    # 5. Decide closedness exactly: every edge used by exactly two
    #    coedges of opposite orientation.
    edge_use: dict = {}
    for f in face_list:
        for lp in f.loops:
            for ce in lp.coedges:
                edge_use.setdefault(id(ce.edge), []).append(ce)
    is_closed = True
    for ces in edge_use.values():
        if len(ces) != 2:
            is_closed = False
            break
        if ces[0].orientation == ces[1].orientation:
            is_closed = False
            break

    # 6. Tolerance propagation (post-merge, with the now-final edge.tol).
    _propagate_tolerance(face_list, tol)

    # 7. Build the shell. We deliberately do NOT call validate_body here
    #    -- closedness depends on the input set and the caller may want
    #    an open shell back. Run the per-face local checks so any
    #    structural break (broken loop, bad orientation, dangling
    #    coedge) is surfaced eagerly.
    shell = Shell(list(face_list), is_closed=is_closed)
    errs: List[str] = []
    for f in face_list:
        errs.extend(_validate_face_local(f))
    if errs:
        raise BuildError(
            f"sew_faces produced invalid Shell: {errs}",
            {"ok": False, "errors": errs},
        )
    return shell


def sew_into_solid(
    faces: Iterable[Face],
    tol: float = 1e-6,
) -> Body:
    """Sew an iterable of :class:`Face` into a validated solid :class:`Body`.

    Calls :func:`sew_faces`; if the result is closed, wraps it in
    ``Solid([shell])`` + ``Body``; finally runs
    :func:`validate_body` and raises :class:`BuildError` on any error.
    """
    shell = sew_faces(faces, tol=tol)
    if not shell.is_closed:
        raise BuildError(
            "sew_into_solid: sewn shell is not closed; cannot form solid",
            {"ok": False, "errors": ["shell is open"]},
        )
    solid = Solid([shell])
    body = Body(solids=[solid])
    res = validate_body(body)
    if not res["ok"]:
        raise BuildError(
            f"sew_into_solid produced invalid Body: {res['errors']}",
            res,
        )
    return body
