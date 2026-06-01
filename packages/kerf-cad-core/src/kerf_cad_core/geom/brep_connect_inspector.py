"""B-rep shell / solid connectivity inspector.

Implements radial-edge connectivity classification (Weiler 1985 §3) and
Mantyla 1988 §6 Euler-operator invariants at the pure-Python topology level.

Input contract
--------------
A *face* is a dict with at least::

    {
        "face_id": <hashable>,          # unique face identifier (int or str)
        "edges": [                       # ordered list of edges bounding the face
            {
                "edge_id": <hashable>,  # unique edge identifier
                "start": <hashable>,    # vertex identifier
                "end":   <hashable>,    # vertex identifier
                "length": <float|None>  # optional geometric length (m/mm)
            },
            ...
        ]
    }

``faces`` may be provided as any iterable of such dicts.

Output
------
``ConnectivityReport`` dataclass with:

  manifold_edge_count       int   edges shared by exactly 2 faces
  boundary_edge_count       int   edges shared by exactly 1 face
  nonmanifold_edge_count    int   edges shared by ≥ 3 faces
  dangling_edge_count       int   edges appearing in no face (should be 0
                                  given input; included for completeness)
  isolated_vertex_count     int   vertices referenced by no edge
  degenerate_edge_count     int   edges whose length == 0 (zero-length)
  components                int   connected components (union-find over vertices)
  face_count                int   total faces
  edge_count                int   total distinct edges
  vertex_count              int   total distinct vertices
  free_edges                list  edge_ids with boundary_edge_count == 1
  is_manifold_closed        bool  True iff manifold and boundary_edge_count == 0
                                  and components == 1

Methodology
-----------
Weiler 1985: an *interior* (manifold) edge is one whose radial cycle has
exactly two coedges, one per adjacent face.  A *boundary* edge has one
coedge; a *non-manifold* edge has three or more.

Mantyla 1988 §6: a valid closed 2-manifold solid satisfies
    V - E + F = 2 * (S - G)
  where S = shell count (components) and G = genus.  For a topological
  sphere (genus 0, one shell) we get V - E + F = 2.

This module is OCCT-free and depends only on the Python stdlib.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Internal union-find (path-compressed, union-by-rank)
# ---------------------------------------------------------------------------

class _UF:
    """Union-Find (path compression + union by rank)."""

    def __init__(self) -> None:
        self._parent: Dict[Any, Any] = {}
        self._rank: Dict[Any, int] = {}

    def find(self, x: Any) -> Any:
        if x not in self._parent:
            self._parent[x] = x
            self._rank[x] = 0
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: Any, b: Any) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def component_count(self, members: Iterable[Any]) -> int:
        roots = {self.find(m) for m in members}
        return len(roots)


# ---------------------------------------------------------------------------
# Public data class
# ---------------------------------------------------------------------------

@dataclass
class ConnectivityReport:
    """Result returned by ``inspect_connectivity``."""

    face_count: int
    edge_count: int
    vertex_count: int

    # Edge valence classification (Weiler 1985 §3)
    manifold_edge_count: int       # radial valence == 2
    boundary_edge_count: int       # radial valence == 1
    nonmanifold_edge_count: int    # radial valence >= 3
    dangling_edge_count: int       # radial valence == 0 (not used by any face)

    # Vertex / degenerate
    isolated_vertex_count: int     # vertices referenced by zero edges
    degenerate_edge_count: int     # zero-length edges (length == 0.0)

    # Topology
    components: int                # shell connectivity components (union-find)

    # Convenience
    free_edges: List[Any] = field(default_factory=list)   # edge_ids with valence 1
    is_manifold_closed: bool = False

    # Euler–Poincaré residual V - E + F (should be 2*components for closed genus-0)
    euler_poincare_vef: int = 0


# ---------------------------------------------------------------------------
# Core algorithm
# ---------------------------------------------------------------------------

def inspect_connectivity(faces: Iterable[Dict]) -> ConnectivityReport:
    """Classify the connectivity of a B-rep shell or solid.

    Parameters
    ----------
    faces:
        Iterable of face dicts as described in the module docstring.

    Returns
    -------
    ConnectivityReport
        Full connectivity report.

    Notes
    -----
    * Edge identity is determined solely by ``edge_id``.
    * Vertex identity is determined by the ``start``/``end`` keys.
    * Edge orientation is ignored for valence counting; both coedges of a
      manifold edge (forward + reverse) count as *one* underlying edge.
    * Degenerate edges (``length == 0``) are flagged but still counted in
      the normal edge/valence tallies.
    """
    faces_list = list(faces)
    n_faces = len(faces_list)

    # edge_id → number of face adjacencies (radial valence)
    edge_valence: Dict[Any, int] = defaultdict(int)
    # edge_id → (start_vertex, end_vertex) — first occurrence wins
    edge_endpoints: Dict[Any, Tuple[Any, Any]] = {}
    # edge_id → length (None if not provided)
    edge_length: Dict[Any, Optional[float]] = {}
    # vertex_id → set of edge_ids referencing it
    vertex_edges: Dict[Any, set] = defaultdict(set)
    # All vertex ids seen in any edge
    all_vertices: set = set()

    for face in faces_list:
        for edge in face.get("edges", []):
            eid = edge["edge_id"]
            sv = edge["start"]
            ev = edge["end"]
            edge_valence[eid] += 1
            if eid not in edge_endpoints:
                edge_endpoints[eid] = (sv, ev)
                edge_length[eid] = edge.get("length")
            all_vertices.add(sv)
            all_vertices.add(ev)
            vertex_edges[sv].add(eid)
            vertex_edges[ev].add(eid)

    n_edges = len(edge_valence)
    n_vertices = len(all_vertices)

    # Valence classification
    manifold_edges = [e for e, v in edge_valence.items() if v == 2]
    boundary_edges = [e for e, v in edge_valence.items() if v == 1]
    nonmanifold_edges = [e for e, v in edge_valence.items() if v >= 3]
    dangling_edges = []  # edges with valence == 0 cannot come from this input

    # Degenerate edges: length explicitly == 0 (not None)
    degenerate_edges = [
        e for e, l in edge_length.items()
        if l is not None and float(l) == 0.0
    ]

    # Isolated vertices: in all_vertices but not referenced by any edge
    # (This can happen if a face lists a vertex not connected to any edge;
    #  given the input contract they only arise from explicit vertex lists
    #  in edge.start/end.  If start==end that is a loop vertex for a
    #  degenerate edge — still referenced.)
    referenced_vertices: set = set(vertex_edges.keys())
    isolated_vertices = all_vertices - referenced_vertices

    # Union-find: connect vertices that share an edge
    uf = _UF()
    for v in all_vertices:
        uf.find(v)  # ensure every vertex is registered
    for sv, ev in edge_endpoints.values():
        uf.union(sv, ev)

    components = uf.component_count(all_vertices) if all_vertices else 0

    # Euler–Poincaré: V - E + F
    vef = n_vertices - n_edges + n_faces

    is_closed = (
        len(boundary_edges) == 0
        and len(nonmanifold_edges) == 0
        and components == 1
        and n_faces > 0
    )

    return ConnectivityReport(
        face_count=n_faces,
        edge_count=n_edges,
        vertex_count=n_vertices,
        manifold_edge_count=len(manifold_edges),
        boundary_edge_count=len(boundary_edges),
        nonmanifold_edge_count=len(nonmanifold_edges),
        dangling_edge_count=len(dangling_edges),
        isolated_vertex_count=len(isolated_vertices),
        degenerate_edge_count=len(degenerate_edges),
        components=components,
        free_edges=boundary_edges,
        is_manifold_closed=is_closed,
        euler_poincare_vef=vef,
    )


def is_manifold_closed(faces: Iterable[Dict]) -> bool:
    """Return True iff the shell is a closed 2-manifold with one component.

    Convenience wrapper around ``inspect_connectivity``.
    """
    return inspect_connectivity(faces).is_manifold_closed


# ---------------------------------------------------------------------------
# Cube / open-box builder helpers (used by tests and tools)
# ---------------------------------------------------------------------------

def _make_cube_faces(size: float = 1.0) -> List[Dict]:
    """Return the 6 faces of a closed-manifold axis-aligned cube.

    Each of the 12 edges is shared by exactly 2 faces.
    Vertices: 8 corners labelled (xi, yi, zi) ∈ {0,size}³.
    """
    s = size
    # 8 vertices
    V = {
        (0, 0, 0): "v000", (s, 0, 0): "v100",
        (0, s, 0): "v010", (s, s, 0): "v110",
        (0, 0, s): "v001", (s, 0, s): "v101",
        (0, s, s): "v011", (s, s, s): "v111",
    }
    # Helper: ensure canonical ordering so the same physical edge always
    # gets the same edge_id regardless of coedge direction.
    def eid(a: str, b: str) -> str:
        return "e_" + "_".join(sorted([a, b]))

    def face(fid: str, quads: List[Tuple[str, str]]) -> Dict:
        return {
            "face_id": fid,
            "edges": [
                {"edge_id": eid(a, b), "start": a, "end": b, "length": s}
                for a, b in quads
            ],
        }

    return [
        # bottom z=0
        face("f_bottom", [("v000","v100"),("v100","v110"),("v110","v010"),("v010","v000")]),
        # top z=s
        face("f_top",    [("v001","v101"),("v101","v111"),("v111","v011"),("v011","v001")]),
        # front y=0
        face("f_front",  [("v000","v100"),("v100","v101"),("v101","v001"),("v001","v000")]),
        # back y=s
        face("f_back",   [("v010","v110"),("v110","v111"),("v111","v011"),("v011","v010")]),
        # left x=0
        face("f_left",   [("v000","v010"),("v010","v011"),("v011","v001"),("v001","v000")]),
        # right x=s
        face("f_right",  [("v100","v110"),("v110","v111"),("v111","v101"),("v101","v100")]),
    ]


# ---------------------------------------------------------------------------
# LLM tool registration (gated import — works without kerf_chat installed)
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import (  # type: ignore[import]
        ToolSpec,
        err_payload,
        ok_payload,
        register,
    )
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

    _FACE_SCHEMA_CI = {
        "type": "array",
        "description": (
            "List of faces.  Each face has a 'face_id' (string or int) and an "
            "'edges' list.  Each edge has 'edge_id', 'start' (vertex id), "
            "'end' (vertex id), and optional 'length' (float, metres)."
        ),
        "items": {
            "type": "object",
            "properties": {
                "face_id": {"type": ["string", "integer"]},
                "edges": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "edge_id": {"type": ["string", "integer"]},
                            "start":   {"type": ["string", "integer"]},
                            "end":     {"type": ["string", "integer"]},
                            "length":  {"type": "number"},
                        },
                        "required": ["edge_id", "start", "end"],
                    },
                },
            },
            "required": ["face_id", "edges"],
        },
    }

    _inspect_spec = ToolSpec(
        name="brep_inspect_connectivity",
        description=(
            "Classify every edge in a B-rep shell/solid by its radial valence "
            "(Weiler 1985 §3 + Mantyla 1988 §6 Euler operators):\n"
            "  • dangling (0 faces) — should be absent in a valid B-rep\n"
            "  • boundary (1 face) — open shell boundary\n"
            "  • manifold interior (2 faces) — watertight 2-manifold edge\n"
            "  • non-manifold (≥3 faces) — T-junction / fan defect\n"
            "Also returns isolated vertex count, degenerate (zero-length) edge "
            "count, shell connected-components (union-find), and the "
            "Euler–Poincaré residual V-E+F."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "faces": _FACE_SCHEMA_CI,
            },
            "required": ["faces"],
        },
    )

    @register(_inspect_spec, write=False)
    async def _run_brep_inspect_connectivity(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as e:
            return err_payload(f"invalid args: {e}", "BAD_ARGS")

        faces = a.get("faces")
        if not isinstance(faces, list):
            return err_payload("'faces' must be a list", "BAD_ARGS")

        try:
            report = inspect_connectivity(faces)
        except Exception as e:
            return err_payload(f"connectivity inspection failed: {e}", "ERROR")

        return ok_payload({
            "face_count":              report.face_count,
            "edge_count":              report.edge_count,
            "vertex_count":            report.vertex_count,
            "manifold_edge_count":     report.manifold_edge_count,
            "boundary_edge_count":     report.boundary_edge_count,
            "nonmanifold_edge_count":  report.nonmanifold_edge_count,
            "dangling_edge_count":     report.dangling_edge_count,
            "isolated_vertex_count":   report.isolated_vertex_count,
            "degenerate_edge_count":   report.degenerate_edge_count,
            "components":              report.components,
            "is_manifold_closed":      report.is_manifold_closed,
            "euler_poincare_vef":      report.euler_poincare_vef,
            "free_edge_ids":           report.free_edges[:200],  # cap for large models
        })

    _manifold_spec = ToolSpec(
        name="brep_is_manifold",
        description=(
            "Return whether a B-rep shell is a closed 2-manifold solid: "
            "no boundary edges, no non-manifold edges, single connected component."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "faces": _FACE_SCHEMA_CI,
            },
            "required": ["faces"],
        },
    )

    @register(_manifold_spec, write=False)
    async def _run_brep_is_manifold(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as e:
            return err_payload(f"invalid args: {e}", "BAD_ARGS")

        faces = a.get("faces")
        if not isinstance(faces, list):
            return err_payload("'faces' must be a list", "BAD_ARGS")

        try:
            result = is_manifold_closed(faces)
        except Exception as e:
            return err_payload(f"manifold check failed: {e}", "ERROR")

        return ok_payload({"is_manifold_closed": result})

except ImportError:
    pass
