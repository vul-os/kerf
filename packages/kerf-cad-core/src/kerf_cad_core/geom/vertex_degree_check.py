"""B-rep vertex edge-degree checker.

Counts the number of edges incident at each vertex in a B-rep shell/solid
and flags vertices that are topologically irregular:

  * **boundary vertex** — degree < ``expected_degree``
    (e.g. degree 2 at a corner of an open mesh; not sealed into a solid)
  * **non-manifold vertex** — degree > ``expected_degree + 2``
    (radial fan so dense that the star neighbourhood cannot be embedded as
    a topological disc; indicates a T-junction, bowtie, or fan defect)

The threshold ``expected_degree + 2`` gives a one-ring of slack:
a cube corner has degree 3, an octahedron vertex has degree 4, a hex-mesh
interior vertex has degree 6.  For typical B-rep solids ``expected_degree=3``
(triangulated) or ``expected_degree=4`` (quad-dominant).  Mantyla 1988 §3.4
discusses valence requirements for a valid 2-manifold; Hoffmann 1989 §4
links vertex star validity to the Euler-Poincaré formula.

Input contract
--------------
``brep_or_mesh`` is accepted in two forms:

1. **Face-list dict** (same schema as ``brep_inspect_connectivity``)::

    [
        {
            "face_id": <hashable>,
            "edges": [
                {"edge_id": <hashable>, "start": <hashable>, "end": <hashable>},
                ...
            ]
        },
        ...
    ]

2. **Body object** from ``kerf_cad_core.geom.brep``  (``Body``, ``Shell``,
   ``Face``, or any object that exposes ``.all_edges()``).

HONEST CAVEATS
--------------
1. **Edge-based degree only**: the degree is counted as the number of *distinct
   edges* incident at a vertex.  This is exactly the topological vertex
   valence in the edge-graph.  We do NOT analyse the *angular* ordering of the
   face fan around a vertex (the "star neighbourhood" geometry); a vertex
   could have the correct degree but still be geometrically non-manifold due
   to degenerate face angles.  For full fan-order analysis use a half-edge /
   radial-edge traversal with geometric tests.
2. **Non-manifold edge detection**: we do not verify whether every edge
   incident at a high-degree vertex is itself a manifold edge (valence-2).
   Combining this with ``brep_inspect_connectivity`` gives a fuller picture.
3. **Vertex deduplication**: distinct *identifier* objects are treated as
   distinct vertices.  If the modelling kernel created duplicate Vertex objects
   for the same geometric point (e.g. after sew/heal without topological
   merging) each duplicate will appear as a low-degree (boundary) vertex.
4. **Expected degree**: the default ``expected_degree=4`` matches quad-mesh /
   typical extruded solid corners.  For triangulated meshes pass
   ``expected_degree=6`` (interior triangle-mesh vertex).  For box-corner
   analysis pass ``expected_degree=3``.

References
----------
* Mantyla, M. (1988). *An Introduction to Solid Modeling*, §3.4 "Vertex
  Stars and Euler Operators". Computer Science Press.
* Hoffmann, C.M. (1989). *Geometric and Solid Modeling: An Introduction*,
  §4 "Topology". Morgan Kaufmann.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# VertexDegreeReport
# ---------------------------------------------------------------------------

@dataclass
class VertexDegreeReport:
    """Per-vertex edge-degree audit result.

    Attributes
    ----------
    num_vertices : int
        Total number of distinct vertex identifiers found.
    degree_histogram : dict[int, int]
        Mapping from edge-degree → number of vertices with that degree.
        E.g. ``{3: 8}`` for a cube (all 8 corners have degree 3).
    num_boundary_vertices : int
        Vertices whose degree is strictly less than ``expected_degree``.
        These may indicate open-mesh boundaries or T-junctions at seams.
    num_non_manifold_vertices : int
        Vertices whose degree is strictly greater than
        ``expected_degree + 2``.  Dense fans; may need topology repair.
    max_degree : int
        Maximum observed vertex degree (0 if no vertices).
    irregular_vertex_indices : list[int | str]
        Identifiers of vertices that are either boundary or non-manifold.
        Capped to 500 entries for large models.
    honest_caveat : str
        Plain-language reminder of what this analysis does/doesn't cover.
    """

    num_vertices: int = 0
    degree_histogram: Dict[int, int] = field(default_factory=dict)
    num_boundary_vertices: int = 0
    num_non_manifold_vertices: int = 0
    max_degree: int = 0
    irregular_vertex_indices: List[Any] = field(default_factory=list)
    honest_caveat: str = (
        "Edge-based degree only: counts incident edges per vertex; does NOT "
        "analyse face-fan angular order or whether non-manifold edges exist "
        "at high-degree vertices. Vertex identity is by object id/hashable — "
        "duplicate Vertex objects for the same geometric point each count "
        "separately (see module docstring caveat 3)."
    )

    def as_dict(self) -> dict:
        return {
            "num_vertices":              self.num_vertices,
            "degree_histogram":          self.degree_histogram,
            "num_boundary_vertices":     self.num_boundary_vertices,
            "num_non_manifold_vertices": self.num_non_manifold_vertices,
            "max_degree":                self.max_degree,
            "irregular_vertex_indices":  self.irregular_vertex_indices,
            "honest_caveat":             self.honest_caveat,
        }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MAX_IRREGULAR_REPORT = 500  # cap list length returned to callers


def _degree_from_edge_list(
    edges: List[Dict],
) -> Dict[Any, int]:
    """Build vertex → degree map from a flat list of edge dicts.

    Each edge dict must have ``"start"`` and ``"end"`` keys (hashable vertex
    ids).  Edges without both keys are silently skipped.
    """
    degree: Dict[Any, int] = defaultdict(int)
    seen_edges: set = set()
    for edge in edges:
        eid = edge.get("edge_id")
        start = edge.get("start")
        end = edge.get("end")
        if start is None or end is None:
            continue
        # De-duplicate: same edge_id appearing in multiple faces' lists
        # should only count once per vertex.
        canonical_key = eid if eid is not None else (
            (min(str(start), str(end)), max(str(start), str(end)))
        )
        if canonical_key in seen_edges:
            continue
        seen_edges.add(canonical_key)
        degree[start] += 1
        degree[end] += 1
    return degree


def _degree_from_face_list(faces: List[Dict]) -> Dict[Any, int]:
    """Aggregate vertex degrees from a face-list dict.

    Handles the case where the same edge appears in multiple face entries
    by de-duplicating on ``edge_id``.
    """
    all_edges: List[Dict] = []
    for face in faces:
        all_edges.extend(face.get("edges", []))
    return _degree_from_edge_list(all_edges)


def _degree_from_body(body: Any) -> Dict[Any, int]:
    """Extract vertex degrees from a ``Body`` / ``Shell`` / ``Face`` object.

    Tries ``body.all_edges()`` first (returns ``Edge`` objects with
    ``v_start`` / ``v_end`` ``Vertex`` attributes).  Falls back to iterating
    ``body.all_faces()`` → face.loops → loop.coedges → coedge.edge.
    """
    degree: Dict[Any, int] = defaultdict(int)
    seen_edge_ids: set = set()

    def _register_edge(edge: Any) -> None:
        eid = id(edge)
        if eid in seen_edge_ids:
            return
        seen_edge_ids.add(eid)
        v_start = getattr(edge, "v_start", None)
        v_end = getattr(edge, "v_end", None)
        if v_start is not None:
            degree[id(v_start)] += 1
        if v_end is not None:
            degree[id(v_end)] += 1

    # Primary path: body.all_edges()
    if hasattr(body, "all_edges"):
        for edge in body.all_edges():
            _register_edge(edge)
        return degree

    # Fallback: traverse face → loop → coedge → edge
    faces_iter = None
    if hasattr(body, "all_faces"):
        faces_iter = body.all_faces()
    elif hasattr(body, "faces"):
        faces_iter = body.faces

    if faces_iter is not None:
        for face in faces_iter:
            for loop in getattr(face, "loops", []):
                for coedge in getattr(loop, "coedges", []):
                    edge = getattr(coedge, "edge", None)
                    if edge is not None:
                        _register_edge(edge)

    return degree


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_vertex_degrees(
    brep_or_mesh: Any,
    expected_degree: int = 4,
) -> VertexDegreeReport:
    """Count incident edges per vertex and flag irregular vertices.

    Parameters
    ----------
    brep_or_mesh :
        Either:

        * a ``list`` of face dicts (same schema as ``brep_inspect_connectivity``)
        * a ``Body`` / ``Shell`` / ``Face`` object from
          ``kerf_cad_core.geom.brep``

    expected_degree : int, optional
        Typical / expected valence for interior vertices.
        ``3`` for fully triangulated meshes (box corner),
        ``4`` for quad-dominant B-rep solids (default),
        ``6`` for interior vertices of a regular triangle mesh.

    Returns
    -------
    VertexDegreeReport
        ``num_boundary_vertices`` — degree < expected_degree.
        ``num_non_manifold_vertices`` — degree > expected_degree + 2.

    Notes
    -----
    The non-manifold threshold ``expected_degree + 2`` gives slack for
    models where some vertices legitimately have one or two extra incident
    edges (e.g. after a local Boolean operation adds an extra face without
    producing a fan defect).

    References
    ----------
    Mantyla 1988 §3.4; Hoffmann 1989 §4.
    """
    report = VertexDegreeReport()

    if expected_degree < 1:
        report.honest_caveat = (
            "expected_degree must be >= 1; received {}.  "
            "Results undefined.".format(expected_degree)
        )
        return report

    # -- Build degree map -----------------------------------------------
    if isinstance(brep_or_mesh, list):
        degree_map = _degree_from_face_list(brep_or_mesh)
    else:
        try:
            degree_map = _degree_from_body(brep_or_mesh)
        except Exception as exc:
            report.honest_caveat = (
                "Could not traverse B-rep object: {}.  "
                "Pass a face-list dict instead.".format(exc)
            )
            return report

    if not degree_map:
        # Empty input — return zeroed report (no vertices)
        return report

    # -- Aggregate ----------------------------------------------------------
    histogram: Dict[int, int] = defaultdict(int)
    boundary_ids: List[Any] = []
    nonmanifold_ids: List[Any] = []

    non_manifold_threshold = expected_degree + 2

    for vid, deg in degree_map.items():
        histogram[deg] += 1
        if deg < expected_degree:
            boundary_ids.append(vid)
        elif deg > non_manifold_threshold:
            nonmanifold_ids.append(vid)

    irregular = boundary_ids + nonmanifold_ids

    report.num_vertices = len(degree_map)
    report.degree_histogram = dict(histogram)
    report.num_boundary_vertices = len(boundary_ids)
    report.num_non_manifold_vertices = len(nonmanifold_ids)
    report.max_degree = max(histogram.keys()) if histogram else 0
    report.irregular_vertex_indices = irregular[:_MAX_IRREGULAR_REPORT]

    return report


# ---------------------------------------------------------------------------
# Convenience oracle helpers (used in tests and documentation)
# ---------------------------------------------------------------------------

def _make_cube_face_list() -> List[Dict]:
    """Return a cube face-list with 8 vertices each at degree 3.

    A closed cube has V=8, E=12, F=6.  Each vertex is incident on exactly
    3 edges (three face-meeting edges at each corner).
    """
    # Vertex ids: 000..111 (binary x,y,z)
    v = {(x, y, z): f"v{x}{y}{z}" for x in range(2) for y in range(2) for z in range(2)}
    e_count = [0]

    def _eid() -> str:
        e_count[0] += 1
        return f"e{e_count[0]}"

    # 12 edges of the cube  (each listed as start,end vertex tuple)
    edges_raw = [
        # bottom face ring
        ((0,0,0),(1,0,0)), ((1,0,0),(1,1,0)), ((1,1,0),(0,1,0)), ((0,1,0),(0,0,0)),
        # top face ring
        ((0,0,1),(1,0,1)), ((1,0,1),(1,1,1)), ((1,1,1),(0,1,1)), ((0,1,1),(0,0,1)),
        # vertical pillars
        ((0,0,0),(0,0,1)), ((1,0,0),(1,0,1)), ((1,1,0),(1,1,1)), ((0,1,0),(0,1,1)),
    ]
    edge_id_map = {}
    for (s, e) in edges_raw:
        eid = _eid()
        edge_id_map[(s, e)] = eid
        edge_id_map[(e, s)] = eid  # reverse lookup same id

    def _edge(s: tuple, e: tuple) -> Dict:
        return {"edge_id": edge_id_map[(s, e)], "start": v[s], "end": v[e]}

    faces = [
        # bottom z=0
        {"face_id": "f_bottom", "edges": [
            _edge((0,0,0),(1,0,0)), _edge((1,0,0),(1,1,0)),
            _edge((1,1,0),(0,1,0)), _edge((0,1,0),(0,0,0)),
        ]},
        # top z=1
        {"face_id": "f_top", "edges": [
            _edge((0,0,1),(1,0,1)), _edge((1,0,1),(1,1,1)),
            _edge((1,1,1),(0,1,1)), _edge((0,1,1),(0,0,1)),
        ]},
        # front y=0
        {"face_id": "f_front", "edges": [
            _edge((0,0,0),(1,0,0)), _edge((1,0,0),(1,0,1)),
            _edge((0,0,1),(1,0,1)), _edge((0,0,0),(0,0,1)),
        ]},
        # back y=1
        {"face_id": "f_back", "edges": [
            _edge((0,1,0),(1,1,0)), _edge((1,1,0),(1,1,1)),
            _edge((0,1,1),(1,1,1)), _edge((0,1,0),(0,1,1)),
        ]},
        # left x=0
        {"face_id": "f_left", "edges": [
            _edge((0,0,0),(0,1,0)), _edge((0,1,0),(0,1,1)),
            _edge((0,0,1),(0,1,1)), _edge((0,0,0),(0,0,1)),
        ]},
        # right x=1
        {"face_id": "f_right", "edges": [
            _edge((1,0,0),(1,1,0)), _edge((1,1,0),(1,1,1)),
            _edge((1,0,1),(1,1,1)), _edge((1,0,0),(1,0,1)),
        ]},
    ]
    return faces


def _make_tetrahedron_face_list() -> List[Dict]:
    """Return a tetrahedron face-list with 4 vertices each at degree 3.

    A tetrahedron has V=4, E=6, F=4.  Each vertex is incident on 3 edges.
    """
    # Vertex ids: v0..v3
    vs = ["v0", "v1", "v2", "v3"]
    # 6 edges
    edges = [
        ("e01", "v0", "v1"), ("e02", "v0", "v2"), ("e03", "v0", "v3"),
        ("e12", "v1", "v2"), ("e13", "v1", "v3"), ("e23", "v2", "v3"),
    ]
    edge_map = {(s, e): eid for eid, s, e in edges}
    edge_map.update({(e, s): eid for eid, s, e in edges})

    def _edge(s: str, e: str) -> Dict:
        return {"edge_id": edge_map[(s, e)], "start": s, "end": e}

    faces = [
        {"face_id": "f012", "edges": [_edge("v0","v1"), _edge("v1","v2"), _edge("v0","v2")]},
        {"face_id": "f013", "edges": [_edge("v0","v1"), _edge("v1","v3"), _edge("v0","v3")]},
        {"face_id": "f023", "edges": [_edge("v0","v2"), _edge("v2","v3"), _edge("v0","v3")]},
        {"face_id": "f123", "edges": [_edge("v1","v2"), _edge("v2","v3"), _edge("v1","v3")]},
    ]
    return faces
