"""Non-manifold detection and auto-repair for B-rep bodies and triangle meshes.

Reference
---------
* Weiler (1985) "Edge-based data structures for solid modeling"
* Sheffer & Hart (2002) "Seamster" §3 — non-manifold detection by ring traversal

B-rep API
---------
detect_non_manifold(body)
    Returns NonManifoldReport with three sets:
      non_manifold_edges     — edge ids shared by > 2 faces (T-junctions).
      non_manifold_vertices  — vertex ids whose edge-fan is not a single cycle.
      non_manifold_faces     — face ids whose outer loop self-intersects.

repair_non_manifold(body, mode='split')
    Returns RepairResult(body, stats).
    mode='split'          — duplicate non-manifold edges; re-link face groups by
                            spatial proximity; insert mid-point vertices.
    mode='delete_smaller' — at each non-manifold edge keep the 2 largest faces;
                            drop the rest.

Mesh API
--------
detect_non_manifold_mesh(mesh)   mesh = {"verts": [...], "faces": [...]}
repair_non_manifold_mesh(mesh, mode='split')
    mesh-side equivalents using face-adjacency tables.

Integration
-----------
body_heal.heal_body() gains a ``repair_non_manifold=False`` kwarg that calls
repair_non_manifold() as a post-pass.
"""

from __future__ import annotations

import copy
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

import numpy as np

from kerf_cad_core.geom.brep import Body, Coedge, Edge, Face, Line3, Loop, Shell, Solid, Vertex

__all__ = [
    "NonManifoldReport",
    "RepairStats",
    "RepairResult",
    "detect_non_manifold",
    "repair_non_manifold",
    "detect_non_manifold_mesh",
    "repair_non_manifold_mesh",
]

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class NonManifoldReport:
    """Detection result for a B-rep body."""

    non_manifold_edges: Set[int] = field(default_factory=set)
    """Edge ids shared by more than 2 faces."""

    non_manifold_vertices: Set[int] = field(default_factory=set)
    """Vertex ids whose incident face-fan is not a single connected cycle."""

    non_manifold_faces: Set[int] = field(default_factory=set)
    """Face ids whose outer loop has any self-intersection (shared vertex)."""

    @property
    def is_manifold(self) -> bool:
        return (
            len(self.non_manifold_edges) == 0
            and len(self.non_manifold_vertices) == 0
            and len(self.non_manifold_faces) == 0
        )


@dataclass
class RepairStats:
    """Summary of what repair_non_manifold changed."""

    edges_split: int = 0
    """Number of non-manifold edges that were split (mode='split')."""

    faces_deleted: int = 0
    """Number of faces deleted (mode='delete_smaller')."""

    vertices_added: int = 0
    """New vertices inserted at edge midpoints (mode='split')."""


@dataclass
class RepairResult:
    """Return value of repair_non_manifold."""

    body: Body
    stats: RepairStats


# ---------------------------------------------------------------------------
# B-rep helpers
# ---------------------------------------------------------------------------


def _edge_to_faces(body: Body) -> Dict[int, List[Face]]:
    """Map edge.id → list of faces that own a coedge referencing it."""
    result: Dict[int, List[Face]] = defaultdict(list)
    for face in body.all_faces():
        for loop in face.loops:
            for ce in loop.coedges:
                result[ce.edge.id].append(face)
    return result


def _vertex_to_faces(body: Body) -> Dict[int, List[Face]]:
    """Map vertex.id → deduplicated list of faces incident to that vertex."""
    result: Dict[int, List[Face]] = defaultdict(list)
    seen: Dict[int, Set[int]] = defaultdict(set)  # vertex_id → set of face ids seen
    for face in body.all_faces():
        for loop in face.loops:
            for ce in loop.coedges:
                for v in (ce.edge.v_start, ce.edge.v_end):
                    if face.id not in seen[v.id]:
                        seen[v.id].add(face.id)
                        result[v.id].append(face)
    return result


def _face_area_brep(face: Face) -> float:
    """Estimate face area by sampling the bounding-loop centroid distances.

    Uses a simple polygon-area approximation by projecting loop vertices onto
    the face surface normal plane (no NURBS surface needed).
    """
    outer = face.outer_loop()
    if outer is None or len(outer.coedges) < 3:
        return 0.0
    pts = [ce.start_point() for ce in outer.coedges]
    # Shoelace on projected polygon
    try:
        n = len(pts)
        centroid = np.mean(pts, axis=0)
        total = 0.0
        for i in range(n):
            a = pts[i] - centroid
            b = pts[(i + 1) % n] - centroid
            total += float(np.linalg.norm(np.cross(a, b)))
        return total * 0.5
    except Exception:
        return 0.0


def _fan_is_single_cycle(faces: List[Face], vertex_id: int) -> bool:
    """Return True if the faces incident to *vertex_id* form a single connected fan.

    Two faces in the fan are adjacent if they share an edge that contains
    the target vertex.  A disconnected fan (touching cone) has ≥ 2 components.
    """
    if len(faces) <= 1:
        return True

    # Build adjacency restricted to these faces via shared edges
    face_ids = [id(f) for f in faces]
    face_set: Set[int] = set(face_ids)

    # Collect edges of each face that are incident to the target vertex
    def _incident_edges(face: Face) -> Set[int]:
        out: Set[int] = set()
        for loop in face.loops:
            for ce in loop.coedges:
                if ce.edge.v_start.id == vertex_id or ce.edge.v_end.id == vertex_id:
                    out.add(ce.edge.id)
        return out

    # Build adjacency: faces share an edge incident to the vertex
    adj: Dict[int, Set[int]] = {id(f): set() for f in faces}
    edge_to_faces_local: Dict[int, List[int]] = defaultdict(list)
    for f in faces:
        for eid in _incident_edges(f):
            edge_to_faces_local[eid].append(id(f))
    for eid, fids in edge_to_faces_local.items():
        for i in range(len(fids)):
            for j in range(i + 1, len(fids)):
                adj[fids[i]].add(fids[j])
                adj[fids[j]].add(fids[i])

    # BFS
    start = id(faces[0])
    visited: Set[int] = {start}
    queue = [start]
    while queue:
        cur = queue.pop()
        for nb in adj[cur]:
            if nb not in visited:
                visited.add(nb)
                queue.append(nb)

    return len(visited) == len(faces)


def _loop_has_self_intersection(loop: Loop) -> bool:
    """Detect self-intersecting outer loop by checking for repeated vertices."""
    vertex_ids: List[int] = []
    for ce in loop.coedges:
        vertex_ids.append(ce.start_vertex().id)
    return len(set(vertex_ids)) < len(vertex_ids)


# ---------------------------------------------------------------------------
# B-rep detection
# ---------------------------------------------------------------------------


def detect_non_manifold(body: Body) -> NonManifoldReport:
    """Detect non-manifold edges, vertices, and faces in *body*.

    Non-manifold edges
        Edges shared by more than 2 faces (T-junction topology).  Per Weiler
        1985: a 2-manifold solid requires every edge to be incident to exactly
        2 faces.

    Non-manifold vertices
        Vertices where the incident face-fan is not a single connected loop
        (touching-cone / pinch topology).  Per Sheffer-Hart 2002 §3: ring
        traversal from each vertex should yield a single orbit.

    Non-manifold faces
        Faces whose outer bounding loop contains the same vertex twice
        (self-intersecting boundary loop).

    Parameters
    ----------
    body : Body
        B-rep body to inspect.  Not mutated.

    Returns
    -------
    NonManifoldReport
    """
    report = NonManifoldReport()

    # --- edge manifold check ---
    e2f = _edge_to_faces(body)
    for edge_id, faces in e2f.items():
        if len(faces) > 2:
            report.non_manifold_edges.add(edge_id)

    # --- vertex manifold check ---
    v2f = _vertex_to_faces(body)
    for vertex_id, faces in v2f.items():
        if len(faces) >= 2 and not _fan_is_single_cycle(faces, vertex_id):
            report.non_manifold_vertices.add(vertex_id)

    # --- face self-intersection check ---
    for face in body.all_faces():
        outer = face.outer_loop()
        if outer is not None and _loop_has_self_intersection(outer):
            report.non_manifold_faces.add(face.id)

    return report


# ---------------------------------------------------------------------------
# B-rep repair
# ---------------------------------------------------------------------------


def repair_non_manifold(body: Body, mode: str = "split") -> RepairResult:
    """Repair non-manifold edges in *body*.

    Parameters
    ----------
    body : Body
        Input body.  Not mutated — a deep copy is made.
    mode : str
        ``'split'``
            At each non-manifold edge (N > 2 incident faces) duplicate the
            edge into N-1 copies and re-assign each copy to a distinct face
            group sorted by spatial proximity to the original edge midpoint.
            A new midpoint vertex is inserted per copy.
        ``'delete_smaller'``
            At each non-manifold edge keep the 2 faces with the largest area;
            remove all other face uses from their shells.

    Returns
    -------
    RepairResult
    """
    if mode not in ("split", "delete_smaller"):
        raise ValueError(f"mode must be 'split' or 'delete_smaller', got {mode!r}")

    report = detect_non_manifold(body)
    if report.is_manifold:
        return RepairResult(body=copy.deepcopy(body), stats=RepairStats())

    new_body = copy.deepcopy(body)
    stats = RepairStats()

    # Build edge-id → edge object map on the copy
    edge_map: Dict[int, Edge] = {}
    for e in new_body.all_edges():
        edge_map[e.id] = e

    # Build edge-id → coedges (and their parent faces) map on the copy
    e2ce_face: Dict[int, List[Tuple[Coedge, Face, Loop]]] = defaultdict(list)
    for face in new_body.all_faces():
        for loop in face.loops:
            for ce in loop.coedges:
                e2ce_face[ce.edge.id].append((ce, face, loop))

    if mode == "split":
        for bad_edge_id in report.non_manifold_edges:
            edge = edge_map.get(bad_edge_id)
            if edge is None:
                continue
            entries = e2ce_face.get(bad_edge_id, [])
            if len(entries) <= 2:
                continue

            # Group entries into pairs (each pair = one edge copy)
            # Sort by face area desc so the two largest faces keep the original edge
            def _area(entry: Tuple[Coedge, Face, Loop]) -> float:
                return _face_area_brep(entry[1])

            entries_sorted = sorted(entries, key=_area, reverse=True)
            # First 2 keep the original edge (no changes needed).
            # Each subsequent entry gets a fresh edge copy with a new midpoint vertex.
            mid = (edge.v_start.point + edge.v_end.point) * 0.5

            for ce, face, loop in entries_sorted[2:]:
                # Create new midpoint vertex
                new_v_mid = Vertex(mid.copy(), tol=edge.tol)
                # New edge: from v_start to mid (same curve shape; use Line3 proxy)
                new_edge = Edge(
                    Line3(edge.v_start.point.copy(), mid.copy()),
                    0.0,
                    1.0,
                    edge.v_start,
                    new_v_mid,
                    tol=edge.tol,
                )
                # Re-wire the coedge to point at new_edge
                # Remove ce from old edge's coedges list
                try:
                    ce.edge.coedges.remove(ce)
                except ValueError:
                    pass
                ce.edge = new_edge
                new_edge.coedges.append(ce)

                stats.edges_split += 1
                stats.vertices_added += 1

    elif mode == "delete_smaller":
        # Collect faces to delete: for each non-manifold edge, keep 2 largest
        face_ids_to_delete: Set[int] = set()
        for bad_edge_id in report.non_manifold_edges:
            entries = e2ce_face.get(bad_edge_id, [])
            if len(entries) <= 2:
                continue
            entries_sorted = sorted(entries, key=lambda x: _face_area_brep(x[1]), reverse=True)
            for ce, face, loop in entries_sorted[2:]:
                face_ids_to_delete.add(face.id)

        # Remove these faces from their parent shells
        for shell in new_body.all_shells():
            to_remove = [f for f in shell.faces if f.id in face_ids_to_delete]
            for f in to_remove:
                shell.faces.remove(f)
                stats.faces_deleted += 1

    return RepairResult(body=new_body, stats=stats)


# ---------------------------------------------------------------------------
# Mesh detection
# ---------------------------------------------------------------------------


def _mesh_validate_input(mesh: dict) -> Optional[str]:
    if not isinstance(mesh, dict):
        return "mesh must be a dict"
    if "verts" not in mesh or "faces" not in mesh:
        return "mesh must have 'verts' and 'faces' keys"
    return None


def _mesh_edge_map(faces: List[List[int]]) -> Dict[Tuple[int, int], List[int]]:
    """Undirected edge → list of face indices."""
    em: Dict[Tuple[int, int], List[int]] = defaultdict(list)
    for fi, f in enumerate(faces):
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            key = (min(a, b), max(a, b))
            em[key].append(fi)
    return em


def _mesh_non_manifold_vertices(
    verts: List[List[float]],
    faces: List[List[int]],
) -> List[int]:
    """Detect vertex-non-manifold conditions (touching cones).

    A vertex is non-manifold if the set of faces incident to it is not a
    single connected component when restricted to adjacency through edges
    incident to that vertex.
    """
    nv = len(verts)
    vert_faces: Dict[int, List[int]] = defaultdict(list)
    for fi, f in enumerate(faces):
        for vi in f:
            vert_faces[vi].append(fi)

    bad: List[int] = []
    for vi in range(nv):
        flist = vert_faces.get(vi, [])
        if len(flist) < 2:
            continue

        # Build adjacency for faces in this fan via shared edges incident to vi
        edge_fi_map: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        for fi in flist:
            f = faces[fi]
            fi_verts = set(f)
            for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
                if a == vi or b == vi:
                    key = (min(a, b), max(a, b))
                    edge_fi_map[key].append(fi)

        adj: Dict[int, Set[int]] = {fi: set() for fi in flist}
        for _key, fids in edge_fi_map.items():
            for i in range(len(fids)):
                for j in range(i + 1, len(fids)):
                    adj[fids[i]].add(fids[j])
                    adj[fids[j]].add(fids[i])

        # BFS
        visited: Set[int] = {flist[0]}
        queue = [flist[0]]
        while queue:
            cur = queue.pop()
            for nb in adj[cur]:
                if nb not in visited:
                    visited.add(nb)
                    queue.append(nb)

        if len(visited) < len(flist):
            bad.append(vi)

    return bad


@dataclass
class MeshNonManifoldReport:
    """Detection result for a triangle mesh."""

    non_manifold_edges: List[Tuple[int, int]] = field(default_factory=list)
    """Undirected edge tuples shared by > 2 faces."""

    non_manifold_vertices: List[int] = field(default_factory=list)
    """Vertex indices whose face-fan is disconnected (touching cone)."""

    @property
    def is_manifold(self) -> bool:
        return len(self.non_manifold_edges) == 0 and len(self.non_manifold_vertices) == 0


def detect_non_manifold_mesh(mesh: dict) -> MeshNonManifoldReport:
    """Detect non-manifold edges and vertices in a triangle mesh.

    Parameters
    ----------
    mesh : dict
        ``{"verts": [[x,y,z], ...], "faces": [[i,j,k], ...]}``

    Returns
    -------
    MeshNonManifoldReport
    """
    err = _mesh_validate_input(mesh)
    if err:
        raise ValueError(err)

    verts: List[List[float]] = [list(v) for v in mesh["verts"]]
    faces: List[List[int]] = [list(f) for f in mesh["faces"]]

    em = _mesh_edge_map(faces)
    nm_edges = [e for e, flist in em.items() if len(flist) > 2]
    nm_verts = _mesh_non_manifold_vertices(verts, faces)

    return MeshNonManifoldReport(
        non_manifold_edges=nm_edges,
        non_manifold_vertices=nm_verts,
    )


# ---------------------------------------------------------------------------
# Mesh repair
# ---------------------------------------------------------------------------


@dataclass
class MeshRepairStats:
    edges_split: int = 0
    faces_deleted: int = 0
    vertices_added: int = 0
    vertices_split: int = 0


@dataclass
class MeshRepairResult:
    verts: List[List[float]]
    faces: List[List[int]]
    stats: MeshRepairStats


def repair_non_manifold_mesh(
    mesh: dict,
    mode: str = "split",
) -> MeshRepairResult:
    """Repair non-manifold edges and vertices in a triangle mesh.

    Parameters
    ----------
    mesh : dict
        ``{"verts": [[x,y,z], ...], "faces": [[i,j,k], ...]}``
    mode : str
        ``'split'``
            Non-manifold edges: split by inserting a midpoint vertex; faces
            beyond the first 2 are re-linked to the new vertex.
            Non-manifold vertices: duplicate the vertex for each disconnected
            fan component beyond the first.
        ``'delete_smaller'``
            Non-manifold edges: keep the 2 largest-area faces; delete the rest.
            Non-manifold vertices: keep the largest fan component; delete faces
            in smaller components.

    Returns
    -------
    MeshRepairResult
    """
    if mode not in ("split", "delete_smaller"):
        raise ValueError(f"mode must be 'split' or 'delete_smaller', got {mode!r}")

    err = _mesh_validate_input(mesh)
    if err:
        raise ValueError(err)

    verts: List[List[float]] = [[float(v[0]), float(v[1]), float(v[2])] for v in mesh["verts"]]
    faces: List[List[int]] = [[int(f[0]), int(f[1]), int(f[2])] for f in mesh["faces"]]
    stats = MeshRepairStats()

    def _face_area(fi: int) -> float:
        f = faces[fi]
        a = verts[f[0]]; b = verts[f[1]]; c = verts[f[2]]
        ab = [b[0]-a[0], b[1]-a[1], b[2]-a[2]]
        ac = [c[0]-a[0], c[1]-a[1], c[2]-a[2]]
        cx = ab[1]*ac[2] - ab[2]*ac[1]
        cy = ab[2]*ac[0] - ab[0]*ac[2]
        cz = ab[0]*ac[1] - ab[1]*ac[0]
        return math.sqrt(cx*cx + cy*cy + cz*cz) * 0.5

    # --- repair non-manifold edges ---
    em = _mesh_edge_map(faces)
    nm_edges = [(e, flist) for e, flist in em.items() if len(flist) > 2]

    faces_to_delete: Set[int] = set()

    for (va, vb), flist in nm_edges:
        if mode == "split":
            # Sort faces by area descending; first 2 keep the original edge.
            # Remaining faces get a new midpoint vertex replacing va in their triangle.
            flist_sorted = sorted(flist, key=_face_area, reverse=True)
            mid = [
                (verts[va][0] + verts[vb][0]) * 0.5,
                (verts[va][1] + verts[vb][1]) * 0.5,
                (verts[va][2] + verts[vb][2]) * 0.5,
            ]
            new_v_idx = len(verts)
            verts.append(mid)
            stats.vertices_added += 1

            for fi in flist_sorted[2:]:
                f = faces[fi]
                # Replace one endpoint of the non-manifold edge in this face
                new_f = list(f)
                if va in new_f:
                    idx = new_f.index(va)
                    new_f[idx] = new_v_idx
                faces[fi] = new_f
                stats.edges_split += 1

        elif mode == "delete_smaller":
            flist_sorted = sorted(flist, key=_face_area, reverse=True)
            for fi in flist_sorted[2:]:
                faces_to_delete.add(fi)
                stats.faces_deleted += 1

    if faces_to_delete:
        faces = [f for i, f in enumerate(faces) if i not in faces_to_delete]

    # --- repair non-manifold vertices ---
    nm_verts = _mesh_non_manifold_vertices(verts, faces)

    for vi in nm_verts:
        # Find all faces incident to vi
        vert_fis = [fi for fi, f in enumerate(faces) if vi in f]
        if len(vert_fis) < 2:
            continue

        # Build fan adjacency via shared edges incident to vi
        edge_fi_map: Dict[Tuple[int, int], List[int]] = defaultdict(list)
        for fi in vert_fis:
            f = faces[fi]
            for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
                if a == vi or b == vi:
                    key = (min(a, b), max(a, b))
                    edge_fi_map[key].append(fi)

        adj: Dict[int, Set[int]] = {fi: set() for fi in vert_fis}
        for _key, fids in edge_fi_map.items():
            for i in range(len(fids)):
                for j in range(i + 1, len(fids)):
                    adj[fids[i]].add(fids[j])
                    adj[fids[j]].add(fids[i])

        # Find connected components by BFS
        visited: Set[int] = set()
        components: List[List[int]] = []
        for start in vert_fis:
            if start in visited:
                continue
            comp: List[int] = []
            queue = [start]
            while queue:
                cur = queue.pop()
                if cur in visited:
                    continue
                visited.add(cur)
                comp.append(cur)
                for nb in adj[cur]:
                    if nb not in visited:
                        queue.append(nb)
            components.append(comp)

        if len(components) <= 1:
            continue

        # Sort components by total area descending; largest keeps vi
        def _comp_area(comp: List[int]) -> float:
            return sum(_face_area(fi) for fi in comp)

        components.sort(key=_comp_area, reverse=True)

        if mode == "split":
            # Each extra component gets a fresh duplicate of vi
            for comp in components[1:]:
                new_vi = len(verts)
                verts.append(list(verts[vi]))
                stats.vertices_split += 1
                stats.vertices_added += 1
                for fi in comp:
                    f = faces[fi]
                    faces[fi] = [new_vi if x == vi else x for x in f]

        elif mode == "delete_smaller":
            # Delete all faces in smaller components
            for comp in components[1:]:
                for fi in comp:
                    faces_to_delete.add(fi)
                    stats.faces_deleted += 1

    if mode == "delete_smaller" and faces_to_delete:
        faces = [f for i, f in enumerate(faces) if i not in faces_to_delete]

    return MeshRepairResult(verts=verts, faces=faces, stats=stats)
