"""edge_collapse.py
==================
SUBD-CAGE-EDGE-COLLAPSE — collapse a quad cage edge to a single vertex,
merging the two endpoints into their midpoint and updating all adjacent face
indices. Degenerate faces (those that contained both endpoints and become
triangles or lines after collapse) are removed from the cage.

Theory
------
Edge collapse is the fundamental decimation primitive in progressive meshes
(Hoppe 1996 §3.2): given an edge {v_a, v_b}, collapse it by:

  1. Compute midpoint v_m = (v_a + v_b) / 2.
  2. Replace ALL references to v_a and v_b in every face with v_m.
  3. Remove any face that now contains a duplicate vertex index (the face
     "collapsed" — it was adjacent to the collapsed edge and becomes
     degenerate: an n-gon with a repeated vertex is at most a triangle or
     line).
  4. Compact the vertex list: remove v_a and v_b, insert v_m; remap all
     face indices.

This is *midpoint* collapse only (no quadric error metric cost function).
It is suitable for:
  - Cage simplification / polygon-reduction preprocessing before CC subdivision.
  - Removing short sliver edges in a coarse control cage.
  - Reducing circumferential detail of cylinder/tube cages.

It is NOT suitable for:
  - High-quality mesh simplification (use Garland-Heckbert 1997 QEM for that).
  - Shape-preserving decimation — midpoint placement is often suboptimal.

Algorithm details
-----------------
Given cage vertices V and faces F and edge index i:
  - Build ordered edge list from F (same order as SubDMesh._all_edge_keys).
  - Look up (v_a, v_b) = all_edges[i].
  - v_m = midpoint(V[v_a], V[v_b]).
  - new_idx = len(V) — we will append v_m and then compact.
  - For every face f in F:
      Replace every occurrence of v_a and v_b with v_m_placeholder.
  - A face is degenerate if any vertex appears more than once.
  - Remove degenerate faces.
  - Compact: remove v_a and v_b; append v_m; renumber indices accordingly.

Degenerate face detection
--------------------------
A quad face [a, b, c, d] with v_a and v_b both present becomes
[v_m, v_m, c, d] after substitution — a degenerate quad with a repeated
vertex.  Such a face is removed.  A triangle face with one endpoint becomes
a valid triangle (not degenerate in general) and is KEPT unless it too has
a repeated vertex after substitution.

References
----------
* Hoppe, H. (1996). "Progressive Meshes." ACM SIGGRAPH 1996, §3.2.
  https://hhoppe.com/pm.pdf
* Bommes, D., Lévy, B., Pietroni, N., Puppo, E., Silva, C., Tarini, M.,
  Zorin, D. (2013). "Quad-Mesh Generation and Processing: A Survey."
  Computer Graphics Forum 32(6):51–76, §4.
* Garland, M. & Heckbert, P. S. (1997). "Surface Simplification Using
  Quadric Error Metrics." ACM SIGGRAPH 1997.
  (NOT implemented here — see honest_caveat.)

Caveats (honest)
----------------
* Midpoint collapse only — NO quadric error metric.  Shape quality of the
  simplified cage is not optimised; the midpoint may lie off the original
  surface.
* Only the cage connectivity is modified; the CC limit surface changes
  shape after collapse (it is not a shape-preserving operation).
* Non-manifold edges (shared by > 2 faces) are handled conservatively:
  ALL faces containing both endpoints are removed (may remove more faces
  than expected on non-manifold input).
* Crease data on the collapsed edge and edges incident to v_a or v_b is
  NOT preserved — the result has no crease annotations.
* After collapse the vertex indices shift; any external reference to specific
  vertex or face indices is invalidated.
* Triangle faces adjacent to a collapsed edge become a line (two unique
  vertices) and are also removed.
* Isolated vertices (unused after face removal) are NOT compacted — the
  returned vertex list may contain unreferenced entries from other collapse
  operations.  Callers should compact if needed.

Public API
----------
EdgeCollapseResult
    Dataclass holding the collapse result.

collapse_edge(cage_mesh, edge_idx) -> EdgeCollapseResult
    Main entry point.

LLM tool: ``subd_collapse_edge``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EdgeCollapseResult:
    """Result of a single edge collapse on a quad cage.

    Attributes
    ----------
    new_cage_vertices : list[tuple[float, float, float]]
        Updated vertex positions after collapse.  v_a and v_b have been
        replaced by their midpoint v_m; all remaining vertices are preserved.
    new_cage_faces : list[list[int]]
        Updated face index lists after collapse and degenerate-face removal.
        All indices reference new_cage_vertices.
    num_faces_removed : int
        Number of faces removed because they became degenerate (contained both
        endpoints of the collapsed edge).
    num_verts_removed : int
        Always 1 for a successful collapse (two endpoints merged to one
        midpoint, net -1 vertex).
    honest_caveat : str
        Plain-language description of algorithmic limitations.
    """
    new_cage_vertices: List[Tuple[float, float, float]] = field(default_factory=list)
    new_cage_faces: List[List[int]] = field(default_factory=list)
    num_faces_removed: int = 0
    num_verts_removed: int = 0
    honest_caveat: str = (
        "Midpoint edge collapse only (Hoppe 1996 §3.2). "
        "v_m = (v_a + v_b) / 2; no quadric error metric (Garland-Heckbert 1997). "
        "Degenerate faces (containing both endpoints of the collapsed edge) are "
        "removed. Crease annotations on incident edges are NOT preserved. "
        "Shape quality not guaranteed — midpoint placement can deviate from the "
        "original limit surface. Vertex/face indices are invalidated after collapse. "
        "Non-manifold edges handled conservatively: all incident degenerate faces "
        "removed. Use Garland-Heckbert QEM for quality-driven decimation."
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


def _is_degenerate(face: List[int]) -> bool:
    """Return True if the face contains any repeated vertex index."""
    return len(set(face)) < len(face)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collapse_edge(
    cage_mesh,
    edge_idx: int,
) -> EdgeCollapseResult:
    """Collapse cage edge at index ``edge_idx`` to the midpoint of its endpoints.

    The two endpoints v_a and v_b are merged into v_m = (v_a + v_b) / 2.
    All face index references to v_a or v_b are rewritten to v_m.  Faces
    that become degenerate (contained both endpoints) are removed.  The
    vertex list is compacted so that v_a and v_b are gone and v_m is present.

    Parameters
    ----------
    cage_mesh : SubDMesh
        The Catmull-Clark control cage to simplify.
    edge_idx : int
        Integer index into the ordered edge list (same ordering as
        SubDMesh._all_edge_keys / subd_compute_edge_ring, etc.).

    Returns
    -------
    EdgeCollapseResult
        .new_cage_vertices  : updated vertex list as list of 3-tuples.
        .new_cage_faces     : updated face lists referencing new vertex indices.
        .num_faces_removed  : number of degenerate faces removed.
        .num_verts_removed  : always 1 for a successful collapse.
        .honest_caveat      : method limitations.

    Raises
    ------
    ValueError
        If edge_idx is out of range [0, num_edges).
    """
    verts = cage_mesh.vertices  # list of [x, y, z] or (x, y, z)
    faces = cage_mesh.faces     # list of list[int]

    all_edges, _edge_index = _build_ordered_edges(faces)
    ne = len(all_edges)

    if not (0 <= edge_idx < ne):
        raise ValueError(
            f"edge_idx {edge_idx} out of range [0, {ne}). "
            f"Cage has {ne} edges."
        )

    v_a, v_b = all_edges[edge_idx]  # canonical (min, max) ordering

    # Compute midpoint.
    ax, ay, az = float(verts[v_a][0]), float(verts[v_a][1]), float(verts[v_a][2])
    bx, by, bz = float(verts[v_b][0]), float(verts[v_b][1]), float(verts[v_b][2])
    mx, my, mz = (ax + bx) / 2.0, (ay + by) / 2.0, (az + bz) / 2.0

    # We will insert v_m at position v_a (lower index) and remove v_b.
    # After insertion the index mapping is:
    #   old 0..v_a-1       -> new 0..v_a-1     (unchanged)
    #   old v_a            -> new v_a           (replaced by midpoint)
    #   old v_a+1..v_b-1   -> new v_a+1..v_b-2 (shifted down by 0, unchanged)
    #   old v_b            -> new v_a           (mapped to midpoint — v_a's slot)
    #   old v_b+1..end     -> new v_b           (shifted down by 1)
    #
    # Build the remap table: old_idx -> new_idx.
    nv = len(verts)
    remap: List[int] = []
    for i in range(nv):
        if i == v_a:
            remap.append(v_a)          # kept; becomes midpoint
        elif i == v_b:
            remap.append(v_a)          # collapsed to same slot as v_a
        elif i < v_b:
            remap.append(i)            # no shift (v_a < v_b always)
        else:
            remap.append(i - 1)        # shift down by 1 (v_b removed)

    # Build new vertex list.
    new_verts: List[Tuple[float, float, float]] = []
    for i in range(nv):
        if i == v_a:
            new_verts.append((mx, my, mz))
        elif i == v_b:
            pass   # skip — v_b is gone
        else:
            x, y, z = float(verts[i][0]), float(verts[i][1]), float(verts[i][2])
            new_verts.append((x, y, z))

    # Remap face indices and filter degenerate faces.
    new_faces: List[List[int]] = []
    num_removed = 0

    for face in faces:
        remapped = [remap[vi] for vi in face]
        if _is_degenerate(remapped):
            num_removed += 1
        else:
            new_faces.append(remapped)

    result = EdgeCollapseResult()
    result.new_cage_vertices = new_verts
    result.new_cage_faces = new_faces
    result.num_faces_removed = num_removed
    result.num_verts_removed = 1
    return result


# ---------------------------------------------------------------------------
# LLM tool: subd_collapse_edge
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

    _collapse_spec = ToolSpec(
        name="subd_collapse_edge",
        description=(
            "Collapse a quad cage edge to a single vertex (midpoint of its "
            "two endpoints). Updates all adjacent face indices; removes degenerate "
            "faces (those containing both endpoints, which become quads-with-repeat "
            "or triangles-with-repeat after substitution).\n"
            "\n"
            "Algorithm: v_m = (v_a + v_b) / 2. All face references to v_a or v_b "
            "are rewritten to v_m. Faces where both v_a and v_b appeared become "
            "degenerate and are removed. Vertex list is compacted.\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  - Midpoint collapse only — NO quadric error metric (Garland-Heckbert "
            "1997). Shape quality is not optimised; use QEM for quality decimation.\n"
            "  - CC limit surface shape changes after collapse.\n"
            "  - Crease annotations on incident edges are not preserved.\n"
            "  - Vertex/face indices are invalidated after collapse.\n"
            "\n"
            "Inputs:\n"
            "  vertices : [[x,y,z], ...]  cage control vertices.\n"
            "  faces    : [[i,j,k,l], ...]  face vertex-index lists.\n"
            "  edge_idx : int  index into the ordered cage edge list.\n"
            "\n"
            "Returns:\n"
            "  ok                  : bool\n"
            "  new_cage_vertices   : [[x,y,z], ...]\n"
            "  new_cage_faces      : [[i,j,...], ...]\n"
            "  num_verts           : int  new vertex count\n"
            "  num_faces           : int  new face count\n"
            "  num_faces_removed   : int  degenerate faces removed\n"
            "  num_verts_removed   : int  always 1\n"
            "  honest_caveat       : str\n"
            "\n"
            "Refs: Hoppe (1996) Progressive Meshes §3.2; "
            "Bommes-Lévy-Pietroni (2013) §4."
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
                    "description": "Cage face vertex-index lists.",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "minItems": 1,
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

    @register(_collapse_spec)
    async def run_subd_collapse_edge(ctx: "ProjectCtx", args: bytes) -> str:
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
            res = collapse_edge(mesh, edge_idx)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "ok": True,
            "new_cage_vertices": [list(v) for v in res.new_cage_vertices],
            "new_cage_faces": [list(f) for f in res.new_cage_faces],
            "num_verts": len(res.new_cage_vertices),
            "num_faces": len(res.new_cage_faces),
            "num_faces_removed": res.num_faces_removed,
            "num_verts_removed": res.num_verts_removed,
            "honest_caveat": res.honest_caveat,
        })
