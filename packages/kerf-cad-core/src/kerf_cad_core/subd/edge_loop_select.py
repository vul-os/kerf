"""edge_loop_select.py
====================
SUBD-CAGE-EDGE-LOOP-SELECT — given a quad cage mesh and a starting edge index,
walk the directional edge loop (opposite edge of adjacent quad) until hitting
an irregular vertex (valence != 4), a boundary, or returning to start.

Theory
------
On a pure-quad Catmull-Clark cage, an *edge loop* walks from edge to edge by
crossing each quad face to its **opposite** edge (the edge sharing no vertices
with the entry edge).  This is the "skip-2" rule from Bommes-Lévy-Pietroni
(2013) §3.2.

Algorithm
---------
Starting at undirected edge E = {a, b} in face F = [v0, v1, v2, v3]
(v0=a, v1=b, positions 0→1 in the face):

  1. The opposite edge in F is (v2, v3) — the edge at positions 2→3.
  2. Check valence of v2 and v3.  If either is irregular (valence ≠ 4),
     terminate: add the opposite edge to the loop and set
     terminated_at_irregular = True.
  3. Otherwise, step: move to the face F' adjacent to (v2, v3) other than F.
  4. In F', find the position of edge (v2, v3) and identify the opposite edge.
  5. Repeat until:
     (a) The current edge equals the start edge → closed = True.
     (b) An irregular vertex is reached → terminated_at_irregular = True.
     (c) A boundary edge (no adjacent face beyond current) → terminated.
     (d) A non-quad face → terminated.
     (e) max_steps exceeded → terminated.

Walk direction: the traversal proceeds in ONE direction only (forward through
face F, then through adjacent faces along the opposite-edge chain).  For a
torus with all regular (valence-4) vertices the loop always closes.  For a
cube (all vertices valence-3) it terminates at the very first step.

For a nu×nv torus, u-direction edges produce loops of length nu; v-direction
edges produce loops of length nv.

Vertex indices in the result represent the vertices of the entry edge at each
step, in traversal order.

References
----------
* Bommes, D., Lévy, B., Pietroni, N., Puppo, E., Silva, C., Tarini, M.,
  Zorin, D. (2013). "Quad-Mesh Generation and Processing: A Survey."
  Computer Graphics Forum 32(6):51–76, §3.2.
* Lévy, B. & Liu, Y. (2010). "Lp Centroidal Voronoi Tessellation and its
  Applications."  SIGGRAPH 2010, §4 (quad remeshing via edge loops).

Caveats (honest)
----------------
* Only works correctly on pure-quad manifold cages.  Any non-quad face causes
  immediate termination with terminated_at_irregular=True.
* Boundary edges terminate the loop; boundary vertices count as "irregular".
* Valence is the number of incident edges counted from the cage adjacency — NOT
  the subdivision-surface valence after refinement.
* Triangle or n-gon faces are not supported.  Mixed meshes terminate at the
  first non-quad face.
* For open (non-toroidal) meshes, loops starting near the boundary will
  terminate at boundary vertices (valence < 4).

Public API
----------
EdgeLoopResult
    Dataclass holding the loop result.

select_edge_loop(cage_mesh, start_edge_idx, max_steps=1000) -> EdgeLoopResult
    Main entry point.

LLM tool: ``subd_select_edge_loop``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from kerf_cad_core.geom.subd import SubDMesh


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EdgeLoopResult:
    """Result of a directional edge-loop walk on a quad cage.

    Attributes
    ----------
    edge_indices : list[int]
        Ordered integer indices into ``cage._all_edge_keys()`` for each edge
        in the loop, starting from ``start_edge_idx``.
    vertex_indices : list[int]
        Ordered list of (a, b) vertex-pair tuples for each edge, stored flat
        as [a0, b0, a1, b1, ...].  For a closed loop length n, contains
        2*n entries.
    closed : bool
        True when the loop returns to the start edge (forms a closed ring).
    terminated_at_irregular : bool
        True when the walk stopped because it hit a vertex with valence != 4,
        a boundary edge, or a non-quad face.
    irregular_vertex_valences : list[int]
        Valences (number of incident edges) of the irregular vertices that
        caused termination.  Empty for closed loops.
    honest_caveat : str
        Plain-language description of algorithmic limitations.
    """
    edge_indices: List[int] = field(default_factory=list)
    vertex_indices: List[int] = field(default_factory=list)
    closed: bool = False
    terminated_at_irregular: bool = False
    irregular_vertex_valences: List[int] = field(default_factory=list)
    honest_caveat: str = (
        "Quad-only directional edge-loop walk (Bommes-Lévy-Pietroni 2013 §3.2). "
        "Traverses opposite edges of each quad face. "
        "Terminates at irregular vertex (valence≠4), boundary edge, or non-quad "
        "face. Assumes manifold mesh: T-junctions and non-manifold edges not "
        "handled. Mixed tri/quad meshes terminate at first non-quad face. "
        "Boundary vertices are treated as irregular. "
        "max_steps safety valve prevents infinite loops on degenerate topology."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_full_adjacency(
    cage: SubDMesh,
) -> Tuple[
    "Dict[Tuple[int,int], List[int]]",   # edge_key → face indices
    "Dict[int, List[int]]",              # vertex → incident vertex neighbours
    "List[Tuple[int,int]]",              # all_edges ordered list
    "Dict[Tuple[int,int], int]",         # edge_key → integer index
]:
    """Build adjacency maps needed for edge-loop traversal."""
    edge_faces: Dict[Tuple[int, int], List[int]] = {}
    vert_neighbors: Dict[int, List[int]] = {}
    all_edges: List[Tuple[int, int]] = []
    edge_index: Dict[Tuple[int, int], int] = {}

    for fi, face in enumerate(cage.faces):
        n = len(face)
        for i in range(n):
            a = face[i]
            b = face[(i + 1) % n]
            key = cage.edge_key(a, b)
            if key not in edge_index:
                edge_index[key] = len(all_edges)
                all_edges.append(key)
            edge_faces.setdefault(key, []).append(fi)
            if b not in vert_neighbors.get(a, []):
                vert_neighbors.setdefault(a, []).append(b)
            if a not in vert_neighbors.get(b, []):
                vert_neighbors.setdefault(b, []).append(a)

    return edge_faces, vert_neighbors, all_edges, edge_index


def _vertex_valence(v: int, vert_neighbors: "Dict[int, List[int]]") -> int:
    """Return the edge-valence (number of incident edges) of vertex v."""
    return len(vert_neighbors.get(v, []))


def _opposite_edge_in_quad(
    face: List[int],
    entry_key: Tuple[int, int],
) -> Optional[Tuple[int, int]]:
    """Return the opposite (undirected) edge in a quad face relative to entry_key.

    For quad face [v0, v1, v2, v3], edges are indexed 0=(v0,v1), 1=(v1,v2),
    2=(v2,v3), 3=(v3,v0).  Opposite pairs: (0,2) and (1,3).

    Returns None if face is not a quad or entry_key is not one of its edges.
    """
    if len(face) != 4:
        return None
    v0, v1, v2, v3 = face
    edges = [
        (min(v0, v1), max(v0, v1)),
        (min(v1, v2), max(v1, v2)),
        (min(v2, v3), max(v2, v3)),
        (min(v3, v0), max(v3, v0)),
    ]
    for i, ek in enumerate(edges):
        if ek == entry_key:
            opp_idx = (i + 2) % 4
            return edges[opp_idx]
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def select_edge_loop(
    cage_mesh: SubDMesh,
    start_edge_idx: int,
    max_steps: int = 1000,
) -> EdgeLoopResult:
    """Walk a directional edge loop starting from a given edge index.

    The loop follows the *opposite-in-quad* pattern of Bommes-Lévy-Pietroni
    (2013) §3.2: at each step we cross the current face to its opposite edge,
    then continue into the face on the other side of that opposite edge.

    Terminates at:
      - Irregular vertex (valence ≠ 4): terminated_at_irregular=True.
      - Boundary edge (no more adjacent faces): terminated_at_irregular=True.
      - Non-quad face: terminated_at_irregular=True.
      - Loop closure (returns to start edge): closed=True.
      - max_steps exceeded: terminated_at_irregular=True.

    Parameters
    ----------
    cage_mesh : SubDMesh
        The Catmull-Clark control cage.  Pure-quad manifold meshes give the
        most meaningful results.
    start_edge_idx : int
        Integer index into ``cage_mesh._all_edge_keys()`` — the starting edge.
        The walk starts by entering the first adjacent face of this edge.
    max_steps : int
        Maximum number of steps before bailing out (default 1000).

    Returns
    -------
    EdgeLoopResult
        .edge_indices              : ordered edge integer indices in the loop.
        .vertex_indices            : flat list [a0, b0, a1, b1, ...] of edge vertices.
        .closed                    : True if loop returns to start.
        .terminated_at_irregular   : True if stopped at irregular vertex/boundary.
        .irregular_vertex_valences : valence(s) at termination point(s).
        .honest_caveat             : method limitations.

    Raises
    ------
    ValueError
        If start_edge_idx is out of range.
    """
    # Build adjacency.
    edge_faces, vert_neighbors, all_edges, edge_index = _build_full_adjacency(cage_mesh)
    ne = len(all_edges)

    if not (0 <= start_edge_idx < ne):
        raise ValueError(
            f"start_edge_idx {start_edge_idx} out of range [0, {ne})"
        )

    result = EdgeLoopResult()
    start_key = all_edges[start_edge_idx]

    start_adj = edge_faces.get(start_key, [])
    if not start_adj:
        # Isolated edge — no faces.
        result.edge_indices = [start_edge_idx]
        result.vertex_indices = list(start_key)
        result.closed = False
        result.terminated_at_irregular = True
        result.irregular_vertex_valences = [0, 0]
        return result

    # The walk traverses ONE direction: start from face start_adj[0].
    # In that face, find the opposite edge, check valence, cross to next face, repeat.

    visited_edge_indices: List[int] = [start_edge_idx]
    visited_vertices: List[int] = list(start_key)

    # Seen edges (to detect non-start cycles on degenerate topology).
    seen_edge_keys: Set[Tuple[int, int]] = {start_key}

    current_face_idx = start_adj[0]
    current_edge_key = start_key

    terminated = False
    closed = False
    irregular_valences: List[int] = []

    for _step in range(max_steps):
        face = cage_mesh.faces[current_face_idx]

        if len(face) != 4:
            # Non-quad face — terminate.
            terminated = True
            irregular_valences.append(len(face))
            break

        # Find opposite edge in this quad face.
        opp_key = _opposite_edge_in_quad(face, current_edge_key)
        if opp_key is None:
            # Edge not in face — shouldn't happen, guard.
            terminated = True
            break

        opp_idx = edge_index.get(opp_key)
        if opp_idx is None:
            terminated = True
            break

        # Check if we've closed the loop.
        if opp_key == start_key:
            closed = True
            break

        # Check valence of both vertices of the opposite edge.
        ov0, ov1 = opp_key  # canonical (min, max) ordering
        val0 = _vertex_valence(ov0, vert_neighbors)
        val1 = _vertex_valence(ov1, vert_neighbors)

        if val0 != 4 or val1 != 4:
            # Irregular vertex — add this edge and terminate.
            visited_edge_indices.append(opp_idx)
            visited_vertices.extend([ov0, ov1])
            terminated = True
            if val0 != 4:
                irregular_valences.append(val0)
            if val1 != 4:
                irregular_valences.append(val1)
            break

        # Cycle detection on non-start edges.
        if opp_key in seen_edge_keys:
            terminated = True
            break

        seen_edge_keys.add(opp_key)
        visited_edge_indices.append(opp_idx)
        visited_vertices.extend([ov0, ov1])

        # Move across opp_key to the next face.
        adj = edge_faces.get(opp_key, [])
        next_faces = [f for f in adj if f != current_face_idx]

        if not next_faces:
            # Boundary — no more faces.
            terminated = True
            bval0 = _vertex_valence(ov0, vert_neighbors)
            bval1 = _vertex_valence(ov1, vert_neighbors)
            if bval0 != 4:
                irregular_valences.append(bval0)
            if bval1 != 4:
                irregular_valences.append(bval1)
            break

        current_face_idx = next_faces[0]
        current_edge_key = opp_key

    else:
        # max_steps exhausted.
        terminated = True

    result.edge_indices = visited_edge_indices
    result.vertex_indices = visited_vertices
    result.closed = closed
    result.terminated_at_irregular = terminated
    result.irregular_vertex_valences = irregular_valences

    return result


# ---------------------------------------------------------------------------
# LLM tool: subd_select_edge_loop
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

    _loop_spec = ToolSpec(
        name="subd_select_edge_loop",
        description=(
            "Walk a directional edge loop on a Catmull-Clark quad cage mesh.\n"
            "\n"
            "Starting from an edge index, the loop crosses each quad face to its "
            "opposite edge (the edge sharing no vertices with the entry edge), "
            "per Bommes-Lévy-Pietroni (2013) §3.2 'skip-2' rule.  Terminates when:\n"
            "  - The loop returns to the start edge (closed=true).\n"
            "  - An irregular vertex (valence≠4) is reached (terminated_at_irregular=true).\n"
            "  - A boundary edge or non-quad face is encountered.\n"
            "  - max_steps is exceeded.\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  - Quads only: non-quad faces terminate the walk immediately.\n"
            "  - Assumes manifold mesh: non-manifold edges not supported.\n"
            "  - Boundary vertices are treated as irregular (loop terminates).\n"
            "  - Traversal direction fixed by first adjacent face of start edge.\n"
            "\n"
            "Inputs:\n"
            "  vertices       : [[x,y,z], ...]  cage control vertices.\n"
            "  faces          : [[i,j,k,l], ...]  quad face vertex-index lists.\n"
            "  start_edge_idx : int  index into the ordered cage edge list.\n"
            "  max_steps      : int  safety limit (default 1000).\n"
            "\n"
            "Returns:\n"
            "  ok                       : bool\n"
            "  edge_indices             : [int, ...]  ordered edge indices in the loop\n"
            "  vertex_indices           : [int, ...]  flat [a0,b0,a1,b1,...] edge vertices\n"
            "  closed                   : bool  true if loop closes back to start\n"
            "  terminated_at_irregular  : bool\n"
            "  irregular_vertex_valences: [int, ...]  valences at termination\n"
            "  loop_length              : int  number of edges in loop\n"
            "  honest_caveat            : str\n"
            "\n"
            "Refs: Bommes-Lévy-Pietroni (2013) CG&F §3.2; Lévy-Liu (2010) SIGGRAPH §4."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Cage control vertices as [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "minItems": 2,
                },
                "faces": {
                    "type": "array",
                    "description": "Cage face vertex-index lists (quads only).",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "minItems": 1,
                },
                "start_edge_idx": {
                    "type": "integer",
                    "description": "Integer index into the cage's ordered edge list.",
                    "minimum": 0,
                },
                "max_steps": {
                    "type": "integer",
                    "description": "Maximum walk steps before bailing out (default 1000).",
                    "default": 1000,
                    "minimum": 1,
                },
            },
            "required": ["vertices", "faces", "start_edge_idx"],
        },
    )

    @register(_loop_spec)
    async def run_subd_select_edge_loop(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        start_idx = a.get("start_edge_idx")
        max_steps = int(a.get("max_steps", 1000))

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if start_idx is None:
            return err_payload("start_edge_idx is required", "BAD_ARGS")

        try:
            verts = [[float(c) for c in row] for row in raw_verts]
            faces = [[int(i) for i in row] for row in raw_faces]
            start_idx = int(start_idx)
        except Exception as exc:
            return err_payload(f"invalid geometry data: {exc}", "BAD_ARGS")

        mesh = SubDMesh(vertices=verts, faces=faces)

        try:
            res = select_edge_loop(mesh, start_idx, max_steps=max_steps)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "ok": True,
            "edge_indices": res.edge_indices,
            "vertex_indices": res.vertex_indices,
            "closed": res.closed,
            "terminated_at_irregular": res.terminated_at_irregular,
            "irregular_vertex_valences": res.irregular_vertex_valences,
            "loop_length": len(res.edge_indices),
            "honest_caveat": res.honest_caveat,
        })
