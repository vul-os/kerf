"""B-rep face-adjacency traversal for routing applications.

BREP-FACE-NEIGHBOR-WALK
-----------------------
Builds a face-adjacency graph over a B-rep shell or solid and exposes
BFS-based traversal primitives used by:
  - CNC tool-path traversal (face-to-face transition planning)
  - Geodesic shortest-path between faces (coarse discrete approximation)
  - Paint-area planning (flood-fill from a seed face)

Honest-flag / topology contract
---------------------------------
*Adjacency is edge-sharing only.*  Two faces are adjacent if and only if
their edge-id sets share at least one common element.  Faces that share only
a vertex (point-touching) are NOT considered adjacent.  This matches the
standard B-rep radial-edge model (Weiler 1985 §3) where every edge is owned
by a directed half-edge and adjacency is defined on the manifold structure.

Input contract
--------------
``faces`` is a list of face dicts following the same schema used by
``brep_connect_inspector`` and ``brep_edge_metrics``::

    [
        {
            "face_id": <hashable>,           # required
            "edges":   [                     # list of edge dicts
                {"edge_id": <hashable>, ...},
                ...
            ],
        },
        ...
    ]

If "face_id" is absent the face index (0, 1, 2, …) is used as a fallback.
If "edges" is absent or empty the face contributes no adjacency edges.
Duplicate edge entries within a face are collapsed automatically.

Public API
----------
    face_adjacency_graph(faces) -> dict[face_id, set[face_id]]
    face_neighbors(face_id, faces) -> list[face_id]
    bfs_from_face(start_face_id, faces, depth_cap=10) -> dict[face_id, int]
    shortest_face_path(start_face_id, end_face_id, faces) -> list[face_id]
    FaceAdjacencyGraph  — dataclass wrapping the graph + helper methods

LLM tools ``brep_face_neighbors`` and ``brep_shortest_face_path`` are
registered when ``kerf_chat`` is available.
"""

from __future__ import annotations

import json as _json
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, Hashable, List, Optional, Set


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _face_id(face_dict: Dict[str, Any], index: int) -> Hashable:
    """Return the face identifier, falling back to the list index."""
    return face_dict.get("face_id", index)


def _edge_ids(face_dict: Dict[str, Any]) -> Set[Hashable]:
    """Return the set of edge ids for a face dict."""
    edges = face_dict.get("edges") or []
    return {e["edge_id"] for e in edges if "edge_id" in e}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def face_adjacency_graph(faces: List[Dict[str, Any]]) -> Dict[Hashable, Set[Hashable]]:
    """Build the face-adjacency graph.

    Returns a dict mapping each face_id to the set of its adjacent face_ids.
    Two faces are adjacent iff they share at least one edge_id.

    Complexity: O(F * E_avg) where F = number of faces, E_avg = average edges
    per face.  Uses an inverted edge→faces index to avoid O(F²) comparisons.

    Parameters
    ----------
    faces:
        List of face dicts (see module docstring for schema).

    Returns
    -------
    dict[face_id, set[face_id]]
        Every face_id in ``faces`` is a key.  Isolated faces map to the empty
        set.
    """
    if not faces:
        return {}

    # Index: edge_id -> list of face_ids that own this edge
    edge_to_faces: Dict[Hashable, List[Hashable]] = {}
    graph: Dict[Hashable, Set[Hashable]] = {}

    for i, face in enumerate(faces):
        fid = _face_id(face, i)
        graph[fid] = set()
        for eid in _edge_ids(face):
            edge_to_faces.setdefault(eid, []).append(fid)

    # For every edge shared by ≥ 2 faces, add symmetric adjacency links
    for eid, fids in edge_to_faces.items():
        for a_idx in range(len(fids)):
            for b_idx in range(a_idx + 1, len(fids)):
                fa, fb = fids[a_idx], fids[b_idx]
                graph[fa].add(fb)
                graph[fb].add(fa)

    return graph


def face_neighbors(
    face_id: Hashable,
    faces: List[Dict[str, Any]],
) -> List[Hashable]:
    """Return the list of faces adjacent to ``face_id`` (depth-1 neighbours).

    Adjacency is edge-sharing only (see module honest-flag).

    Parameters
    ----------
    face_id:
        The target face.  If not present in ``faces`` an empty list is
        returned (no error).
    faces:
        B-rep face list (same schema as ``face_adjacency_graph``).

    Returns
    -------
    list[face_id]  — order is arbitrary (dict-set iteration order).
    """
    graph = face_adjacency_graph(faces)
    return list(graph.get(face_id, set()))


def bfs_from_face(
    start_face_id: Hashable,
    faces: List[Dict[str, Any]],
    depth_cap: int = 10,
) -> Dict[Hashable, int]:
    """BFS traversal from a start face up to ``depth_cap`` hops.

    Parameters
    ----------
    start_face_id:
        Seed face for the traversal.
    faces:
        B-rep face list.
    depth_cap:
        Maximum traversal depth (inclusive).  Use ``depth_cap=0`` to return
        only ``{start_face_id: 0}``.  Defaults to 10.

    Returns
    -------
    dict[face_id, int]
        Maps each reachable face_id to its BFS depth from ``start_face_id``.
        Only includes faces reachable within ``depth_cap`` hops.
        If ``start_face_id`` is not in the graph, returns an empty dict.
    """
    graph = face_adjacency_graph(faces)
    if start_face_id not in graph:
        return {}

    visited: Dict[Hashable, int] = {start_face_id: 0}
    queue: deque[Hashable] = deque([start_face_id])

    while queue:
        current = queue.popleft()
        current_depth = visited[current]
        if current_depth >= depth_cap:
            continue
        for neighbor in graph[current]:
            if neighbor not in visited:
                visited[neighbor] = current_depth + 1
                queue.append(neighbor)

    return visited


def shortest_face_path(
    start_face_id: Hashable,
    end_face_id: Hashable,
    faces: List[Dict[str, Any]],
) -> List[Hashable]:
    """Find the shortest face path from ``start_face_id`` to ``end_face_id``.

    Uses BFS over the face-adjacency graph.  Each hop crosses one shared edge.
    This is a *discrete* geodesic approximation — it minimises hop count, not
    Euclidean distance.

    Parameters
    ----------
    start_face_id, end_face_id:
        Source and destination faces.
    faces:
        B-rep face list.

    Returns
    -------
    list[face_id]
        Ordered list from start to end inclusive.  Returns ``[]`` if no path
        exists or if either face is not in the graph.

    Examples
    --------
    Unit cube opposite faces: path length == 2 (one intermediate face).
    """
    if start_face_id == end_face_id:
        # Degenerate: start == end
        graph = face_adjacency_graph(faces)
        if start_face_id in graph:
            return [start_face_id]
        return []

    graph = face_adjacency_graph(faces)
    if start_face_id not in graph or end_face_id not in graph:
        return []

    # BFS with parent tracking
    parent: Dict[Hashable, Optional[Hashable]] = {start_face_id: None}
    queue: deque[Hashable] = deque([start_face_id])

    while queue:
        current = queue.popleft()
        if current == end_face_id:
            # Reconstruct path
            path: List[Hashable] = []
            node: Optional[Hashable] = end_face_id
            while node is not None:
                path.append(node)
                node = parent[node]
            path.reverse()
            return path
        for neighbor in graph[current]:
            if neighbor not in parent:
                parent[neighbor] = current
                queue.append(neighbor)

    return []  # no path


# ---------------------------------------------------------------------------
# FaceAdjacencyGraph dataclass
# ---------------------------------------------------------------------------

@dataclass
class FaceAdjacencyGraph:
    """Dataclass wrapping the face-adjacency graph for repeated queries.

    Build once with ``FaceAdjacencyGraph.from_faces(faces)`` and reuse the
    graph dict for multiple traversal calls without re-indexing edges.

    Attributes
    ----------
    graph:
        dict[face_id, set[face_id]] — the adjacency map.
    """

    graph: Dict[Hashable, Set[Hashable]] = field(default_factory=dict)

    @classmethod
    def from_faces(cls, faces: List[Dict[str, Any]]) -> "FaceAdjacencyGraph":
        """Construct from a list of face dicts (same schema as module API)."""
        return cls(graph=face_adjacency_graph(faces))

    def neighbors(self, face_id: Hashable) -> List[Hashable]:
        """Return depth-1 neighbours of ``face_id``."""
        return list(self.graph.get(face_id, set()))

    def bfs(
        self, start: Hashable, depth_cap: int = 10
    ) -> Dict[Hashable, int]:
        """BFS from ``start`` up to ``depth_cap`` hops.

        Uses the pre-built graph (does not re-index from faces).
        """
        if start not in self.graph:
            return {}
        visited: Dict[Hashable, int] = {start: 0}
        queue: deque[Hashable] = deque([start])
        while queue:
            current = queue.popleft()
            d = visited[current]
            if d >= depth_cap:
                continue
            for nb in self.graph[current]:
                if nb not in visited:
                    visited[nb] = d + 1
                    queue.append(nb)
        return visited

    def shortest_path(
        self, start: Hashable, end: Hashable
    ) -> List[Hashable]:
        """Shortest BFS path from ``start`` to ``end``.

        Returns ``[]`` if no path or either node missing.
        """
        if start == end:
            return [start] if start in self.graph else []
        if start not in self.graph or end not in self.graph:
            return []
        parent: Dict[Hashable, Optional[Hashable]] = {start: None}
        queue: deque[Hashable] = deque([start])
        while queue:
            cur = queue.popleft()
            if cur == end:
                path: List[Hashable] = []
                node: Optional[Hashable] = end
                while node is not None:
                    path.append(node)
                    node = parent[node]
                path.reverse()
                return path
            for nb in self.graph[cur]:
                if nb not in parent:
                    parent[nb] = cur
                    queue.append(nb)
        return []

    def connected_components(self) -> List[Set[Hashable]]:
        """Return list of connected-component face-id sets.

        Uses BFS (union-find equivalent for small graphs).
        """
        remaining = set(self.graph.keys())
        components: List[Set[Hashable]] = []
        while remaining:
            seed = next(iter(remaining))
            component = set(self.bfs(seed, depth_cap=len(self.graph)).keys())
            components.append(component)
            remaining -= component
        return components


# ---------------------------------------------------------------------------
# LLM tool registration (optional — requires kerf_chat)
# ---------------------------------------------------------------------------

_FACES_SCHEMA = {
    "type": "array",
    "description": (
        "List of B-rep face dicts.  Each dict must have:\n"
        "  face_id: <str|int|hashable>  (optional — falls back to list index)\n"
        "  edges:   list of {edge_id: <hashable>, ...}\n"
        "Adjacency is edge-sharing ONLY (not point-sharing)."
    ),
    "items": {
        "type": "object",
        "properties": {
            "face_id": {"description": "Unique face identifier"},
            "edges": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "edge_id": {"description": "Unique edge identifier"},
                    },
                    "required": ["edge_id"],
                },
            },
        },
    },
}

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]

    # ---- brep_face_neighbors ------------------------------------------------

    _neighbors_spec = ToolSpec(
        name="brep_face_neighbors",
        description=(
            "Return the direct (depth-1) face neighbours of a given face in a "
            "B-rep shell or solid.  Two faces are adjacent iff they share at "
            "least one edge (edge-sharing only; point-touching faces are NOT "
            "adjacent — Weiler 1985 §3 radial-edge model).\n\n"
            "Also returns the full face-adjacency graph so callers can inspect "
            "all face→face links in one call.\n\n"
            "Returns: {ok, face_id, neighbors: [face_id, ...], "
            "adjacency_graph: {face_id: [face_id, ...]}, face_count, "
            "neighbor_count}"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "face_id": {
                    "description": "The face whose neighbours to return.",
                },
                "faces": _FACES_SCHEMA,
            },
            "required": ["face_id", "faces"],
        },
    )

    @register(_neighbors_spec)
    async def run_brep_face_neighbors(ctx: "ProjectCtx", args: bytes) -> str:  # type: ignore[name-defined]
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        if "face_id" not in a:
            return err_payload("'face_id' is required", "BAD_ARGS")
        if "faces" not in a:
            return err_payload("'faces' is required", "BAD_ARGS")
        try:
            fag = FaceAdjacencyGraph.from_faces(a["faces"])
            fid = a["face_id"]
            neighbors = fag.neighbors(fid)
            # Serialise graph (sets → sorted lists for stable JSON)
            graph_serial = {
                str(k): sorted(str(v) for v in vs)
                for k, vs in fag.graph.items()
            }
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")
        return ok_payload({
            "face_id": fid,
            "neighbors": neighbors,
            "adjacency_graph": graph_serial,
            "face_count": len(fag.graph),
            "neighbor_count": len(neighbors),
        })

    # ---- brep_shortest_face_path --------------------------------------------

    _path_spec = ToolSpec(
        name="brep_shortest_face_path",
        description=(
            "Find the shortest face-to-face path in a B-rep shell or solid "
            "using BFS over the face-adjacency graph.  Each hop crosses one "
            "shared edge.  This is a discrete geodesic approximation — it "
            "minimises hop count, not Euclidean distance.\n\n"
            "Use-cases: CNC tool-path traversal order, geodesic routing between "
            "machining regions, paint-area planning.\n\n"
            "Returns: {ok, start_face_id, end_face_id, path: [face_id, ...], "
            "hop_count: int}  — path is empty if no route exists."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "start_face_id": {
                    "description": "Source face identifier.",
                },
                "end_face_id": {
                    "description": "Destination face identifier.",
                },
                "faces": _FACES_SCHEMA,
            },
            "required": ["start_face_id", "end_face_id", "faces"],
        },
    )

    @register(_path_spec)
    async def run_brep_shortest_face_path(ctx: "ProjectCtx", args: bytes) -> str:  # type: ignore[name-defined]
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid JSON: {exc}", "BAD_ARGS")
        for key in ("start_face_id", "end_face_id", "faces"):
            if key not in a:
                return err_payload(f"'{key}' is required", "BAD_ARGS")
        try:
            path = shortest_face_path(a["start_face_id"], a["end_face_id"], a["faces"])
        except Exception as exc:
            return err_payload(str(exc), "OP_FAILED")
        return ok_payload({
            "start_face_id": a["start_face_id"],
            "end_face_id": a["end_face_id"],
            "path": path,
            "hop_count": max(0, len(path) - 1),
        })

except ImportError:
    pass  # kerf_chat not installed — tools silently unavailable
