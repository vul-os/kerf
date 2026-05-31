"""edge_flip.py
==============
SUBD-CAGE-EDGE-FLIP — topological edge flip for two adjacent triangles sharing
an edge.  Given an edge (v_a, v_b) shared by exactly two triangles, the two
triangles are replaced by two new triangles formed by connecting the opposite
vertices (v_c, v_d) of the original pair.

Theory
------
Edge flip is the elementary topology-change operation used in Delaunay
triangulation, cage refinement, and isotropic remeshing to improve triangle
aspect ratio without adding or removing vertices.

Given two adjacent triangles sharing edge (v_a, v_b):

  Triangle T1: (v_a, v_b, v_c)   — v_c is the vertex of T1 opposite the
                                    shared edge.
  Triangle T2: (v_a, v_b, v_d)   — v_d is the vertex of T2 opposite the
                                    shared edge.

After flipping the shared edge the two new triangles are:

  T1' = (v_a, v_c, v_d)   (fan from v_a; winding: CCW if input was CCW)
  T2' = (v_b, v_d, v_c)   (fan from v_b; winding reversed to preserve orientation)

This preserves the four vertices v_a, v_b, v_c, v_d and the overall face count
(2 triangles in → 2 triangles out) while changing connectivity.

Winding-order convention
------------------------
The input triangles may be wound CW or CCW.  This implementation detects
the winding of T1 (the first triangle incident to the edge by index order)
and ensures both output triangles share the same orientation:

  * If T1 = [v_a, v_b, v_c] (v_a before v_b in face):
        T1' = [v_a, v_c, v_d]
        T2' = [v_b, v_d, v_c]
  * If T1 = [v_b, v_a, v_c] (v_b before v_a in face — reversed winding):
        T1' = [v_b, v_c, v_d]
        T2' = [v_a, v_d, v_c]

Algorithmic details
--------------------
1. Build ordered edge list from faces (same ordering as SubDMesh._all_edge_keys /
   edge_collapse / edge_loop_select).
2. Look up (v_a, v_b) = all_edges[edge_idx].
3. Scan face list: collect every face containing both v_a and v_b.
4. Validate: exactly 2 faces required; both must be triangles (len == 3).
5. Identify opposite vertices: for each tri-face, the vertex that is neither
   v_a nor v_b is the "opposite" vertex.  Call them v_c (from first face) and
   v_d (from second face).
6. Detect winding of first face; build T1' and T2' with matching winding.
7. Replace the two original faces in the face list with T1' and T2'.
8. All other faces (not incident to the shared edge) are kept unchanged.
9. Vertex list is unchanged — no vertices are added or removed.

What this does NOT do
----------------------
* No Delaunay criterion check: the flip is purely topological.  Whether the
  resulting triangulation is locally Delaunay (in-circle test) is NOT checked
  and NOT guaranteed.  If you need Delaunay flips, run the in-circle test
  externally and only call flip_edge when the test demands it.
* No quad-face support: quad faces containing the shared edge are rejected
  (raises ValueError) because the flip operation is only defined for
  triangles.
* No crease / attribute preservation: any per-edge crease weights, UV
  coordinates, or colour attributes are NOT transferred to the new edges.
* No non-manifold support: edges shared by more than 2 faces are rejected.
* Boundary edges (only 1 incident face) are rejected.

References
----------
* Bommes, D., Lévy, B., Pietroni, N. et al. (2013). "Quad-Mesh Generation
  and Processing: A Survey." Computer Graphics Forum 32(6):51–76, §3.
  https://doi.org/10.1111/cgf.12014
* Edelsbrunner, H. (2001). "Geometry and Topology for Mesh Generation."
  Cambridge University Press, §2 (Delaunay triangulation, edge flip).
* de Berg, M. et al. (2008). "Computational Geometry: Algorithms and
  Applications." 3rd ed., Springer, §9.3 (Delaunay flip graph).
* Shewchuk, J. R. (1996). "Triangle: Engineering a 2D Quality Mesh
  Generator and Delaunay Triangulator."  Workshop on Applied Computational
  Geometry, §3.2 (edge flip as Lawson's algorithm primitive).

Caveats (honest)
----------------
* TOPOLOGICAL FLIP ONLY — no Delaunay in-circle test.  Flipping an already-
  Delaunay edge degrades triangulation quality; callers are responsible for
  checking the Delaunay criterion if that property is required.
* TRIANGLES ONLY — quads and n-gons adjacent to the edge → ValueError.
* SHARED BY EXACTLY 2 TRIANGLES — boundary edges (1 face) and non-manifold
  edges (> 2 faces) → ValueError.
* Vertex positions unchanged; only face connectivity is modified.
* Crease, UV, normal, and colour attributes on the flipped edge and its new
  edges are NOT preserved.
* Vertex/face indices in the result still reference the original vertex list
  (no compaction needed since no vertices change).
* Degenerate input (v_a == v_b, or opposite vertex == v_a or v_b) will
  produce incorrect topology and is not detected.

Public API
----------
EdgeFlipResult
    Dataclass holding the flip result.

flip_edge(cage_mesh, edge_idx) -> EdgeFlipResult
    Main entry point.

LLM tool: ``subd_flip_edge``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EdgeFlipResult:
    """Result of a single edge flip on a triangulated cage.

    Attributes
    ----------
    new_cage_faces : list[list[int]]
        Updated face index lists after the flip.  Only the two faces that
        shared the flipped edge are replaced; all other faces are unchanged.
        All indices reference the original vertex list (vertices are
        unmodified).
    num_edges_flipped : int
        Always 1 for a successful flip.
    flipped_edge_indices : list[int]
        List of length 1 containing the edge index that was flipped.
    honest_caveat : str
        Plain-language description of algorithmic limitations.
    """
    new_cage_faces: List[List[int]] = field(default_factory=list)
    num_edges_flipped: int = 0
    flipped_edge_indices: List[int] = field(default_factory=list)
    honest_caveat: str = (
        "Topological edge flip only (Bommes-Lévy-Pietroni 2013 §3; "
        "Edelsbrunner 2001 §2). "
        "NO Delaunay in-circle test is performed — the flip is purely "
        "topological. Calling flip_edge on an already-Delaunay edge may "
        "degrade triangulation quality. "
        "Only triangular faces are supported; quad faces adjacent to the "
        "shared edge raise ValueError. "
        "Boundary edges (1 incident face) and non-manifold edges (> 2 "
        "incident faces) raise ValueError. "
        "Vertex positions are unchanged; only face connectivity is modified. "
        "Crease, UV, normal, and colour attributes on the flipped edge and "
        "its replacement edges are NOT preserved. "
        "Triangle only: this operation is not defined for quad-dominant or "
        "mixed tri/quad cages."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_ordered_edges(
    faces: List[List[int]],
) -> Tuple[List[Tuple[int, int]], Dict[Tuple[int, int], int]]:
    """Build the ordered edge list and edge→index map from a face list.

    Follows the same ordering logic as SubDMesh._all_edge_keys so that
    edge_idx matches the rest of the subd toolkit.
    """
    seen: Set[Tuple[int, int]] = set()
    all_edges: List[Tuple[int, int]] = []
    edge_index: Dict[Tuple[int, int], int] = {}

    for face in faces:
        n = len(face)
        for i in range(n):
            a = face[i]
            b = face[(i + 1) % n]
            key = (min(a, b), max(a, b))
            if key not in seen:
                seen.add(key)
                edge_index[key] = len(all_edges)
                all_edges.append(key)

    return all_edges, edge_index


def _faces_sharing_edge(
    faces: List[List[int]],
    v_a: int,
    v_b: int,
) -> List[int]:
    """Return indices of all faces containing both v_a and v_b."""
    result = []
    for i, face in enumerate(faces):
        face_set = set(face)
        if v_a in face_set and v_b in face_set:
            result.append(i)
    return result


def _opposite_vertex(face: List[int], v_a: int, v_b: int) -> int:
    """Return the vertex in *face* that is neither v_a nor v_b.

    Assumes face is a triangle (len == 3) and that v_a, v_b are present.
    """
    for v in face:
        if v != v_a and v != v_b:
            return v
    raise ValueError(
        f"Could not find opposite vertex in face {face} for edge ({v_a}, {v_b})"
    )


def _build_flipped_faces(
    face1: List[int],
    face2: List[int],
    v_a: int,
    v_b: int,
    v_c: int,
    v_d: int,
) -> Tuple[List[int], List[int]]:
    """Build the two replacement faces after flipping edge (v_a, v_b).

    Winding of face1 (the first-incident triangle) is preserved.

    In face1 the edge appears as (v_a→v_b) or (v_b→v_a).  We detect which
    and construct T1' and T2' so they share the same winding as face1.

    Convention (CCW example):
      face1 = [v_a, v_b, v_c]   →  T1' = [v_a, v_c, v_d],  T2' = [v_b, v_d, v_c]
      face1 = [v_b, v_a, v_c]   →  T1' = [v_b, v_c, v_d],  T2' = [v_a, v_d, v_c]
    """
    # Find where v_a appears in face1 and determine edge direction.
    n = len(face1)
    a_pos = face1.index(v_a)
    next_pos = (a_pos + 1) % n
    # Edge direction: v_a → v_b (a before b), or v_b → v_a (b before a)?
    a_before_b = (face1[next_pos] == v_b)

    if a_before_b:
        # face1 reads …, v_a, v_b, v_c, …  (v_a → v_b → v_c)
        t1_prime = [v_a, v_c, v_d]
        t2_prime = [v_b, v_d, v_c]
    else:
        # face1 reads …, v_b, v_a, v_c, …  (v_b → v_a → v_c)
        t1_prime = [v_b, v_c, v_d]
        t2_prime = [v_a, v_d, v_c]

    return t1_prime, t2_prime


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def flip_edge(
    cage_mesh,
    edge_idx: int,
) -> EdgeFlipResult:
    """Flip the cage edge at index ``edge_idx``.

    Finds the two triangles sharing the edge (v_a, v_b) and replaces them
    with two new triangles connecting the opposite vertices (v_c, v_d).

    The vertex list is unchanged — no vertices are added or removed.  The
    face list has exactly the same length; only the two incident triangles
    change.

    Parameters
    ----------
    cage_mesh : SubDMesh
        The triangulated (or mixed tri/poly) control cage.  The edge to flip
        must be shared by exactly two *triangle* faces.
    edge_idx : int
        Integer index into the ordered edge list (same ordering as
        SubDMesh._all_edge_keys / subd_compute_edge_ring, etc.).

    Returns
    -------
    EdgeFlipResult
        .new_cage_faces     : updated face lists; same length as input faces.
        .num_edges_flipped  : always 1 for a successful flip.
        .flipped_edge_indices : [edge_idx].
        .honest_caveat      : algorithmic limitations.

    Raises
    ------
    ValueError
        If edge_idx is out of range [0, num_edges).
        If the edge is not shared by exactly 2 faces (boundary or non-manifold).
        If either incident face is not a triangle (quad or n-gon).
    """
    faces = cage_mesh.faces  # list of list[int]

    all_edges, _edge_index = _build_ordered_edges(faces)
    ne = len(all_edges)

    if not (0 <= edge_idx < ne):
        raise ValueError(
            f"edge_idx {edge_idx} out of range [0, {ne}). "
            f"Cage has {ne} edges."
        )

    v_a, v_b = all_edges[edge_idx]  # canonical (min, max) ordering

    # Find all faces sharing this edge.
    incident_face_indices = _faces_sharing_edge(faces, v_a, v_b)
    n_inc = len(incident_face_indices)

    if n_inc == 0:
        raise ValueError(
            f"Edge ({v_a}, {v_b}) at index {edge_idx} is not incident to any face. "
            f"This should not happen for a valid cage."
        )

    if n_inc == 1:
        raise ValueError(
            f"Edge ({v_a}, {v_b}) at index {edge_idx} is a boundary edge "
            f"(only 1 incident face). Edge flip requires exactly 2 incident faces."
        )

    if n_inc > 2:
        raise ValueError(
            f"Edge ({v_a}, {v_b}) at index {edge_idx} is non-manifold "
            f"({n_inc} incident faces). Edge flip requires exactly 2 incident faces."
        )

    # Validate: both faces must be triangles.
    fi1, fi2 = incident_face_indices[0], incident_face_indices[1]
    face1, face2 = faces[fi1], faces[fi2]

    if len(face1) != 3:
        raise ValueError(
            f"Face {fi1} incident to edge ({v_a}, {v_b}) is a {len(face1)}-gon "
            f"(not a triangle). Edge flip only supports triangular faces."
        )

    if len(face2) != 3:
        raise ValueError(
            f"Face {fi2} incident to edge ({v_a}, {v_b}) is a {len(face2)}-gon "
            f"(not a triangle). Edge flip only supports triangular faces."
        )

    # Find the opposite vertices.
    v_c = _opposite_vertex(face1, v_a, v_b)
    v_d = _opposite_vertex(face2, v_a, v_b)

    # Build the two replacement faces preserving winding.
    t1_prime, t2_prime = _build_flipped_faces(face1, face2, v_a, v_b, v_c, v_d)

    # Build the new face list: replace face1 and face2; keep everything else.
    new_faces: List[List[int]] = []
    for i, face in enumerate(faces):
        if i == fi1:
            new_faces.append(t1_prime)
        elif i == fi2:
            new_faces.append(t2_prime)
        else:
            new_faces.append(list(face))

    result = EdgeFlipResult()
    result.new_cage_faces = new_faces
    result.num_edges_flipped = 1
    result.flipped_edge_indices = [edge_idx]
    return result


# ---------------------------------------------------------------------------
# LLM tool: subd_flip_edge
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

    from kerf_cad_core.geom.subd import SubDMesh  # type: ignore[import]

    _flip_spec = ToolSpec(
        name="subd_flip_edge",
        description=(
            "Flip a triangle-cage edge by connecting the opposite vertices of "
            "the two triangles that share it. Given edge (v_a, v_b) shared by "
            "triangles T1=(v_a, v_b, v_c) and T2=(v_a, v_b, v_d), produces "
            "T1'=(v_a, v_c, v_d) and T2'=(v_b, v_d, v_c).\n"
            "\n"
            "Used in cage refinement to improve triangle aspect ratio without "
            "adding or removing vertices.\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  - TOPOLOGICAL FLIP ONLY — no Delaunay in-circle test is applied.\n"
            "    The flip is unconditional; callers must run the in-circle test "
            "    themselves if Delaunay quality is required.\n"
            "  - TRIANGLES ONLY — raises ValueError if either incident face is a "
            "    quad or n-gon.\n"
            "  - SHARED BY EXACTLY 2 FACES — raises ValueError for boundary edges "
            "    (1 face) or non-manifold edges (> 2 faces).\n"
            "  - Vertex positions unchanged — no coordinates are modified.\n"
            "  - Crease, UV, normal, colour attributes on the flipped edge are NOT "
            "    preserved.\n"
            "\n"
            "Inputs:\n"
            "  vertices : [[x,y,z], ...]  cage control vertices (read-only; positions "
            "unchanged by the flip).\n"
            "  faces    : [[i,j,k], ...]  triangle face vertex-index lists.\n"
            "  edge_idx : int  index into the ordered cage edge list.\n"
            "\n"
            "Returns:\n"
            "  ok                  : bool\n"
            "  new_cage_faces      : [[i,j,k], ...]  updated face list (same length "
            "as input; only the 2 incident faces replaced).\n"
            "  num_edges_flipped   : int  always 1 on success.\n"
            "  flipped_edge_indices: [int]  the flipped edge index.\n"
            "  num_faces           : int  face count (unchanged).\n"
            "  honest_caveat       : str\n"
            "\n"
            "Refs: Bommes-Lévy-Pietroni (2013) CG&F §3; "
            "Edelsbrunner (2001) Geometry and Topology for Mesh Generation §2."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Cage control vertices as [[x,y,z], ...] (read-only).",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "minItems": 3,
                },
                "faces": {
                    "type": "array",
                    "description": "Triangle face vertex-index lists as [[i,j,k], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "minItems": 2,
                },
                "edge_idx": {
                    "type": "integer",
                    "description": "Integer index into the ordered cage edge list.",
                    "minimum": 0,
                },
            },
            "required": ["vertices", "faces", "edge_idx"],
        },
    )

    @register(_flip_spec)
    async def run_subd_flip_edge(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        edge_idx = a.get("edge_idx")

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if edge_idx is None:
            return err_payload("edge_idx is required", "BAD_ARGS")

        try:
            verts = [[float(c) for c in row] for row in raw_verts]
            faces = [[int(i) for i in row] for row in raw_faces]
            edge_idx = int(edge_idx)
        except Exception as exc:
            return err_payload(f"invalid geometry data: {exc}", "BAD_ARGS")

        mesh = SubDMesh(vertices=verts, faces=faces)

        try:
            res = flip_edge(mesh, edge_idx)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "ok": True,
            "new_cage_faces": [list(f) for f in res.new_cage_faces],
            "num_edges_flipped": res.num_edges_flipped,
            "flipped_edge_indices": res.flipped_edge_indices,
            "num_faces": len(res.new_cage_faces),
            "honest_caveat": res.honest_caveat,
        })
