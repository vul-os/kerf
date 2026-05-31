"""face_loop_select.py
====================
SUBD-CAGE-FACE-LOOP — walk a face loop on a quad cage mesh by hopping through
opposite-edge adjacent quads.  Analogous to a directional edge-loop walk but
tracks *faces* rather than edges — the dual traversal useful for ring-cut
planning and subdivision sweep selection.

Theory
------
On a pure-quad Catmull-Clark cage a *face loop* is the sequence of quad faces
reached by repeatedly crossing a face via its pair of *opposite* edges.  Given a
starting face F and a choice of which pair of opposite edges to traverse
(``walk_direction`` 0 or 1), the walk proceeds:

  1. Identify the two pairs of opposite edges in F:
       pair 0: edge (v0,v1) ↔ edge (v2,v3)  (the "u" direction)
       pair 1: edge (v1,v2) ↔ edge (v3,v0)  (the "v" direction)
  2. ``walk_direction`` selects which pair to cross.  At each step we enter the
     next face through one of the two edges in the chosen pair.
  3. In the new face find its two opposite-edge pairs and determine which pair is
     aligned with the incoming edge (the pair that *contains* the shared edge).
     The *other* pair's edges give the two exit directions.  We pick the exit
     edge that does **not** lead back to the face we came from (forward
     traversal).
  4. Stop when:
       (a) The current face equals ``start_face_idx`` → closed=True (closed ring).
       (b) The next face is not a quad → terminated_at_irregular=True.
       (c) There is no adjacent face (boundary edge) → terminated.
       (d) ``max_steps`` exceeded → terminated.

``walk_direction`` 0 vs 1 produce orthogonal face rings on a regular torus:
direction 0 follows the "v-strip" (nu faces); direction 1 follows the "u-strip"
(nv faces).

References
----------
* Bommes, D., Lévy, B., Pietroni, N., Puppo, E., Silva, C., Tarini, M.,
  Zorin, D. (2013). "Quad-Mesh Generation and Processing: A Survey."
  Computer Graphics Forum 32(6):51–76, §3.2.
* Hoppe, H. (1996). "Progressive Meshes." SIGGRAPH 1996, §3.2.

Caveats (honest)
----------------
* Quad faces only — any non-quad face terminates the walk immediately.
* Boundary edges (no adjacent face) terminate the walk.
* ``walk_direction`` is resolved relative to the *start* face winding.
  Winding inconsistencies in non-orientable or non-manifold meshes produce
  undefined results.
* The face loop is a *one-directional* walk; it does not back-propagate.
* Mixed tri/quad meshes terminate at the first non-quad face encountered.
* ``max_steps`` safety valve prevents infinite loops on degenerate topology.
* Irregular faces (non-quads) are recorded in ``irregular_face_indices``.

Public API
----------
FaceLoopResult
    Dataclass holding the face loop result.

select_face_loop(cage_mesh, start_face_idx, walk_direction=0, max_steps=1000) -> FaceLoopResult
    Main entry point.

LLM tool: ``subd_select_face_loop``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from kerf_cad_core.geom.subd import SubDMesh


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FaceLoopResult:
    """Result of a directional face-loop walk on a quad cage.

    Attributes
    ----------
    face_indices : list[int]
        Ordered integer indices of the faces in the loop, starting from
        ``start_face_idx``.
    closed : bool
        True when the loop returns to the start face (forms a closed ring).
    terminated_at_irregular : bool
        True when the walk stopped because it hit a non-quad face, a boundary
        edge, or ``max_steps`` was exceeded.
    irregular_face_indices : list[int]
        Indices of non-quad faces that caused (or were adjacent to) termination.
        Empty for closed loops.
    honest_caveat : str
        Plain-language description of algorithmic limitations.
    """
    face_indices: List[int] = field(default_factory=list)
    closed: bool = False
    terminated_at_irregular: bool = False
    irregular_face_indices: List[int] = field(default_factory=list)
    honest_caveat: str = (
        "Quad-only directional face-loop walk (Bommes-Lévy-Pietroni 2013 §3.2; "
        "Hoppe 1996). "
        "Traverses faces by hopping through opposite-edge adjacent quads. "
        "walk_direction 0/1 selects which pair of opposite edges to cross. "
        "Terminates at non-quad face, boundary edge, or max_steps exceeded. "
        "Assumes manifold mesh: T-junctions and non-manifold edges not handled. "
        "Mixed tri/quad meshes terminate at first non-quad face. "
        "Boundary edges are treated as loop terminators. "
        "max_steps safety valve prevents infinite loops on degenerate topology."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_edge_face_map(
    cage: SubDMesh,
) -> "Dict[Tuple[int, int], List[int]]":
    """Return a mapping from canonical edge key → list of adjacent face indices."""
    edge_faces: Dict[Tuple[int, int], List[int]] = {}
    for fi, face in enumerate(cage.faces):
        n = len(face)
        for i in range(n):
            a = face[i]
            b = face[(i + 1) % n]
            key = cage.edge_key(a, b)
            edge_faces.setdefault(key, []).append(fi)
    return edge_faces


def _opposite_edge_pairs_in_quad(
    face: List[int],
) -> Tuple[
    Tuple["Tuple[int,int]", "Tuple[int,int]"],  # pair 0: edge-u, opp-u
    Tuple["Tuple[int,int]", "Tuple[int,int]"],  # pair 1: edge-v, opp-v
]:
    """Return the two pairs of opposite edge keys for a quad face.

    For face [v0, v1, v2, v3] (winding order preserved):
      pair 0 (u-direction): edge(v0,v1) ↔ edge(v2,v3)
      pair 1 (v-direction): edge(v1,v2) ↔ edge(v3,v0)

    Each element is ``(min(a,b), max(a,b))``.
    """
    v0, v1, v2, v3 = face
    e01 = (min(v0, v1), max(v0, v1))
    e12 = (min(v1, v2), max(v1, v2))
    e23 = (min(v2, v3), max(v2, v3))
    e30 = (min(v3, v0), max(v3, v0))
    return (e01, e23), (e12, e30)


def _find_exit_edge(
    face: List[int],
    entry_edge_key: "Tuple[int, int]",
    edge_faces: "Dict[Tuple[int, int], List[int]]",
    current_face_idx: int,
    walk_direction: int,
) -> "Optional[Tuple[int, int]]":
    """Return the forward exit edge key for the next step, or None if boundary/invalid.

    Given that we entered ``face`` (index ``current_face_idx``) via
    ``entry_edge_key``, find the edge on the *opposite* side:

      1. Find which opposite-edge pair contains ``entry_edge_key``.
      2. The exit edge is the *other* edge in that pair.
      3. Verify that the exit edge has at least one adjacent face that is not
         ``current_face_idx``.  If not (boundary), return None.

    ``walk_direction`` is used only when determining the *initial* exit direction
    from ``start_face_idx`` (where there is no entry edge to use as reference).
    For subsequent steps the entry-edge pair lookup is used directly.
    """
    if len(face) != 4:
        return None

    (e01, e23), (e12, e30) = _opposite_edge_pairs_in_quad(face)

    # Find which pair contains the entry_edge_key and identify the exit edge.
    if entry_edge_key in (e01, e23):
        exit_key = e23 if entry_edge_key == e01 else e01
    elif entry_edge_key in (e12, e30):
        exit_key = e30 if entry_edge_key == e12 else e12
    else:
        # entry_edge_key is not an edge of this face — degenerate, bail.
        return None

    # Confirm exit edge has a neighbour other than current_face_idx.
    adj = edge_faces.get(exit_key, [])
    next_faces = [f for f in adj if f != current_face_idx]
    if not next_faces:
        return None  # boundary

    return exit_key


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_face_loop(
    cage_mesh: SubDMesh,
    start_face_idx: int,
    walk_direction: int = 0,
    max_steps: int = 1000,
) -> FaceLoopResult:
    """Walk a directional face loop starting from a given face index.

    The loop follows the *opposite-in-quad* face pattern: at each step we
    leave the current face through the exit edge that is opposite to the
    entry edge, then continue into the face on the other side.

    Terminates at:
      - Loop closure (returns to ``start_face_idx``): closed=True.
      - Non-quad face: terminated_at_irregular=True.
      - Boundary edge (no more adjacent faces): terminated_at_irregular=True.
      - ``max_steps`` exceeded: terminated_at_irregular=True.

    Parameters
    ----------
    cage_mesh : SubDMesh
        The Catmull-Clark control cage.  Pure-quad manifold meshes give the
        most meaningful results.
    start_face_idx : int
        Integer index into ``cage_mesh.faces`` — the starting face.
    walk_direction : int
        0 or 1 — selects which pair of opposite edges to traverse in the
        start face.  Direction 0 uses the (v0,v1)↔(v2,v3) pair; direction 1
        uses the (v1,v2)↔(v3,v0) pair.  On a regular torus, the two
        directions produce orthogonal face rings.  Default 0.
    max_steps : int
        Maximum number of steps before bailing out (default 1000).

    Returns
    -------
    FaceLoopResult
        .face_indices              : ordered face integer indices in the loop.
        .closed                    : True if loop returns to start face.
        .terminated_at_irregular   : True if stopped at non-quad/boundary.
        .irregular_face_indices    : non-quad face indices at termination.
        .honest_caveat             : method limitations.

    Raises
    ------
    ValueError
        If ``start_face_idx`` is out of range or ``walk_direction`` is not 0 or 1.
    """
    nf = len(cage_mesh.faces)
    if not (0 <= start_face_idx < nf):
        raise ValueError(
            f"start_face_idx {start_face_idx} out of range [0, {nf})"
        )
    if walk_direction not in (0, 1):
        raise ValueError(
            f"walk_direction must be 0 or 1, got {walk_direction}"
        )

    result = FaceLoopResult()

    # Validate start face is a quad.
    start_face = cage_mesh.faces[start_face_idx]
    if len(start_face) != 4:
        result.face_indices = [start_face_idx]
        result.closed = False
        result.terminated_at_irregular = True
        result.irregular_face_indices = [start_face_idx]
        return result

    edge_faces = _build_edge_face_map(cage_mesh)

    # Determine the initial exit edge from the start face using walk_direction.
    (e01, e23), (e12, e30) = _opposite_edge_pairs_in_quad(start_face)
    if walk_direction == 0:
        # Pick one edge of pair-0 to be the first exit; we use e23 (exit "forward")
        initial_exit_key: Tuple[int, int] = e23
        initial_entry_key: Tuple[int, int] = e01  # the entry side (conceptually)
    else:
        initial_exit_key = e30
        initial_entry_key = e12

    # Check that the initial exit edge has a neighbouring face.
    adj_start = edge_faces.get(initial_exit_key, [])
    next_start = [f for f in adj_start if f != start_face_idx]
    if not next_start:
        # The exit edge is a boundary from the very start.
        result.face_indices = [start_face_idx]
        result.closed = False
        result.terminated_at_irregular = True
        return result

    # Walk loop.
    visited: List[int] = [start_face_idx]
    seen_faces: Set[int] = {start_face_idx}

    current_face_idx = next_start[0]
    current_entry_key: Tuple[int, int] = initial_exit_key  # we entered through this edge

    terminated = False
    closed = False
    irregular_faces: List[int] = []

    for _step in range(max_steps):
        face = cage_mesh.faces[current_face_idx]

        if len(face) != 4:
            # Non-quad — terminate, record this face as irregular.
            irregular_faces.append(current_face_idx)
            terminated = True
            break

        # Find the exit edge (opposite to entry edge in this quad).
        exit_key = _find_exit_edge(
            face, current_entry_key, edge_faces, current_face_idx, walk_direction
        )

        if exit_key is None:
            # Boundary or degenerate — terminate.
            terminated = True
            break

        # Check if the next face is the start face (closure).
        adj = edge_faces.get(exit_key, [])
        next_faces = [f for f in adj if f != current_face_idx]

        if not next_faces:
            terminated = True
            break

        next_face_idx = next_faces[0]

        if next_face_idx == start_face_idx:
            # Closed loop — add the current face to visited and declare closed.
            visited.append(current_face_idx)
            closed = True
            break

        # Cycle detection (non-start faces).
        if current_face_idx in seen_faces:
            # We've re-visited a non-start face — topology is degenerate.
            terminated = True
            break

        seen_faces.add(current_face_idx)
        visited.append(current_face_idx)

        # Step forward.
        current_entry_key = exit_key
        current_face_idx = next_face_idx

    else:
        # max_steps exhausted.
        terminated = True

    result.face_indices = visited
    result.closed = closed
    result.terminated_at_irregular = terminated
    result.irregular_face_indices = irregular_faces

    return result


# ---------------------------------------------------------------------------
# LLM tool: subd_select_face_loop
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

    _face_loop_spec = ToolSpec(
        name="subd_select_face_loop",
        description=(
            "Walk a directional face loop on a Catmull-Clark quad cage mesh.\n"
            "\n"
            "Starting from a face index, the loop hops through adjacent quad faces by\n"
            "crossing each quad via its opposite-edge pair.  This is the face-dual of\n"
            "the directional edge-loop walk (Bommes-Lévy-Pietroni 2013 §3.2).  Useful\n"
            "for ring-cut planning and subdivision sweep selection.\n"
            "\n"
            "walk_direction 0 or 1 selects which pair of opposite edges to traverse:\n"
            "  direction 0: crosses the (v0,v1)↔(v2,v3) edge pair (u-strips)\n"
            "  direction 1: crosses the (v1,v2)↔(v3,v0) edge pair (v-strips)\n"
            "On a regular torus the two directions produce orthogonal face rings.\n"
            "\n"
            "Terminates when:\n"
            "  - The loop returns to the start face (closed=true).\n"
            "  - A non-quad face is encountered (terminated_at_irregular=true).\n"
            "  - A boundary edge is reached (no adjacent face).\n"
            "  - max_steps is exceeded.\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  - Quads only: non-quad faces terminate the walk immediately.\n"
            "  - Assumes manifold mesh: non-manifold edges not supported.\n"
            "  - Boundary edges are treated as loop terminators.\n"
            "  - walk_direction resolved relative to start face winding.\n"
            "  - One-directional walk only; does not back-propagate.\n"
            "\n"
            "Inputs:\n"
            "  vertices        : [[x,y,z], ...]  cage control vertices.\n"
            "  faces           : [[i,j,k,l], ...]  quad face vertex-index lists.\n"
            "  start_face_idx  : int  index into cage.faces.\n"
            "  walk_direction  : int  0 or 1 (default 0).\n"
            "  max_steps       : int  safety limit (default 1000).\n"
            "\n"
            "Returns:\n"
            "  ok                       : bool\n"
            "  face_indices             : [int, ...]  ordered face indices in the loop\n"
            "  closed                   : bool  true if loop closes back to start face\n"
            "  terminated_at_irregular  : bool\n"
            "  irregular_face_indices   : [int, ...]  non-quad faces at termination\n"
            "  loop_length              : int  number of faces in loop\n"
            "  honest_caveat            : str\n"
            "\n"
            "Refs: Bommes-Lévy-Pietroni (2013) CG&F §3.2; Hoppe (1996) §3.2."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Cage control vertices as [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "minItems": 3,
                },
                "faces": {
                    "type": "array",
                    "description": "Cage face vertex-index lists (quads only).",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "minItems": 1,
                },
                "start_face_idx": {
                    "type": "integer",
                    "description": "Integer index into cage.faces — the starting face.",
                    "minimum": 0,
                },
                "walk_direction": {
                    "type": "integer",
                    "description": (
                        "0 = cross (v0,v1)↔(v2,v3) pair; "
                        "1 = cross (v1,v2)↔(v3,v0) pair. Default 0."
                    ),
                    "default": 0,
                    "enum": [0, 1],
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Maximum walk steps before bailing out (default 1000).",
                    "default": 1000,
                    "minimum": 1,
                },
            },
            "required": ["vertices", "faces", "start_face_idx"],
        },
    )

    @register(_face_loop_spec)
    async def run_subd_select_face_loop(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        start_idx = a.get("start_face_idx")
        walk_dir = int(a.get("walk_direction", 0))
        max_steps = int(a.get("max_steps", 1000))

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if start_idx is None:
            return err_payload("start_face_idx is required", "BAD_ARGS")

        try:
            verts = [[float(c) for c in row] for row in raw_verts]
            faces = [[int(i) for i in row] for row in raw_faces]
            start_idx = int(start_idx)
        except Exception as exc:
            return err_payload(f"invalid geometry data: {exc}", "BAD_ARGS")

        mesh = SubDMesh(vertices=verts, faces=faces)

        try:
            res = select_face_loop(
                mesh, start_idx, walk_direction=walk_dir, max_steps=max_steps
            )
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "ok": True,
            "face_indices": res.face_indices,
            "closed": res.closed,
            "terminated_at_irregular": res.terminated_at_irregular,
            "irregular_face_indices": res.irregular_face_indices,
            "loop_length": len(res.face_indices),
            "honest_caveat": res.honest_caveat,
        })
