"""vertex_merge.py
==================
SUBD-CAGE-VERTEX-MERGE — merge a list of cage vertices (by index) into their
centroid, updating all adjacent face indices and removing degenerate faces.

This is the N-vertex generalisation of edge collapse (Hoppe 1996 §3.2):
instead of collapsing exactly two endpoints of an edge, an arbitrary subset of
vertices is fused into a single new vertex at their centroid.

Theory
------
Given a set of vertex indices S = {i_0, i_1, ..., i_{k-1}} in a cage mesh:

  1. Compute centroid v_c = (1/|S|) * Σ_{i∈S} V[i].
  2. Replace ALL references to any vertex in S in every face with v_c.
  3. Remove degenerate faces (those containing a repeated vertex index after
     substitution; equivalently, faces where at least two of the original
     vertices were in S).
  4. Compact the vertex list: remove all vertices in S and insert v_c;
     renumber face indices accordingly.

Relationship to Garland-Heckbert (1997)
-----------------------------------------
Garland-Heckbert §3 defines QEM vertex pair contraction: the optimal
placement minimises Σ v^T Q_i v where Q_i are quadric error matrices
accumulated from incident face planes. This module implements centroid
placement only — it is correct for topology, but the centroid can deviate
from the optimal QEM location.  The honest_caveat field documents this.

Degenerate face detection
--------------------------
A face f containing indices {a, b} with a,b ∈ S becomes [v_c, v_c, ...]
after substitution — degenerate.  More generally, any face that originally
contained ≥ 2 vertices from S is degenerate after the merge and is removed.

Non-adjacent (disconnected) vertex merge
-----------------------------------------
When the vertices in S do not share any edge, no face contains two or more of
them.  No face becomes degenerate.  The vertex count drops by |S|-1 (|S|
vertices replaced by 1).  The resulting mesh is topologically valid but the
centroid placement introduces geometric distortion around each former vertex
location.

Edge cases
----------
* Empty S (len == 0) → no-op; returns original mesh unchanged.
* Single vertex S (len == 1) → no-op; returns original mesh unchanged.
  (No edge exists, nothing to merge.)
* Duplicate indices in S → deduplicated before processing; the effective
  set is the unique values.
* Out-of-range indices → ValueError.

References
----------
* Hoppe, H. (1996). "Progressive Meshes." ACM SIGGRAPH 1996, §3.2.
  https://hhoppe.com/pm.pdf
* Garland, M. & Heckbert, P. S. (1997). "Surface Simplification Using
  Quadric Error Metrics." ACM SIGGRAPH 1997.
  https://www.cs.cmu.edu/~quake-papers/quadrics.pdf
* Bommes, D., Lévy, B., Pietroni, N., Puppo, E., Silva, C., Tarini, M.,
  Zorin, D. (2013). "Quad-Mesh Generation and Processing: A Survey."
  Computer Graphics Forum 32(6):51–76.

Caveats (honest)
----------------
* Centroid placement only — NO quadric error metric (Garland-Heckbert 1997).
  Optimal QEM placement would minimise shape deviation; the centroid may lie
  well off the original surface.
* Only cage connectivity is modified; the CC limit surface changes shape
  after the merge.
* Crease annotations on edges incident to merged vertices are NOT preserved.
* After the merge, all vertex and face indices are invalidated for external
  callers.
* Non-manifold input (edge shared by > 2 faces) is handled conservatively:
  every face containing ≥ 2 merged vertices is removed.
* Isolated vertices not involved in the merge are NOT compacted separately.
* Triangle faces whose sole merged vertex is in S are valid (not degenerate
  in general) and are KEPT unless they contain ≥ 2 merged vertices.

Public API
----------
VertexMergeResult
    Dataclass holding the merge result.

merge_vertices(cage_mesh, vertex_indices) -> VertexMergeResult
    Main entry point.

LLM tool: ``subd_merge_vertices``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Set, Tuple


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class VertexMergeResult:
    """Result of a multi-vertex cage merge.

    Attributes
    ----------
    new_cage_vertices : list[tuple[float, float, float]]
        Updated vertex positions after the merge.  All vertices in
        ``vertex_indices`` have been replaced by their centroid; remaining
        vertices are preserved (positions unchanged, indices compacted).
    new_cage_faces : list[list[int]]
        Updated face index lists after the merge and degenerate-face removal.
        All indices reference ``new_cage_vertices``.
    num_faces_removed : int
        Number of faces removed because they became degenerate (contained ≥ 2
        of the merged vertices, producing a repeated vertex after substitution).
    num_verts_removed : int
        Net change: ``len(vertex_indices_unique) - 1``.  Zero if only 0 or 1
        distinct vertices were given (no-op case).
    merged_index : int
        Index of the newly inserted centroid vertex in ``new_cage_vertices``.
        ``-1`` if the operation was a no-op.
    honest_caveat : str
        Plain-language description of algorithmic limitations.
    """
    new_cage_vertices: List[Tuple[float, float, float]] = field(default_factory=list)
    new_cage_faces: List[List[int]] = field(default_factory=list)
    num_faces_removed: int = 0
    num_verts_removed: int = 0
    merged_index: int = -1
    honest_caveat: str = (
        "Centroid vertex merge (generalised edge collapse, Hoppe 1996 §3.2). "
        "v_c = mean of all merged vertices; NO quadric error metric "
        "(Garland-Heckbert 1997 §3). Degenerate faces (containing ≥ 2 merged "
        "vertices) are removed. Crease annotations on incident edges are NOT "
        "preserved. Shape quality not guaranteed — centroid placement can deviate "
        "from the original CC limit surface. Vertex/face indices are invalidated "
        "after merge. Non-manifold input handled conservatively: all incident "
        "degenerate faces removed. Use Garland-Heckbert QEM for quality-driven "
        "decimation."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_degenerate(face: List[int]) -> bool:
    """Return True if the face contains any repeated vertex index."""
    return len(set(face)) < len(face)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def merge_vertices(
    cage_mesh,
    vertex_indices: List[int],
) -> VertexMergeResult:
    """Merge a list of cage vertices to their centroid.

    All vertices identified by ``vertex_indices`` are fused into a single
    new vertex located at their centroid.  Face index references to any of
    the merged vertices are rewritten to the centroid vertex.  Faces that
    become degenerate (contained two or more of the merged vertices) are
    removed.  The vertex list is compacted.

    Parameters
    ----------
    cage_mesh : SubDMesh
        The Catmull-Clark control cage to modify.  Must expose ``.vertices``
        (list of [x, y, z]) and ``.faces`` (list of list[int]).
    vertex_indices : list[int]
        Indices into ``cage_mesh.vertices`` to merge.  Duplicates are
        ignored.  Order is irrelevant (centroid is order-independent).

    Returns
    -------
    VertexMergeResult
        See :class:`VertexMergeResult` for field documentation.

    Raises
    ------
    ValueError
        If any index in ``vertex_indices`` is out of range
        ``[0, len(vertices))``.
    """
    verts = cage_mesh.vertices   # list of [x, y, z] or (x, y, z)
    faces = cage_mesh.faces      # list of list[int]
    nv = len(verts)

    # ── Deduplicate indices ────────────────────────────────────────────────
    unique_set: Set[int] = set()
    for idx in vertex_indices:
        unique_set.add(int(idx))
    unique_indices = sorted(unique_set)   # sorted for deterministic removal order

    # ── Validate ───────────────────────────────────────────────────────────
    for idx in unique_indices:
        if not (0 <= idx < nv):
            raise ValueError(
                f"vertex index {idx} is out of range [0, {nv}). "
                f"Cage has {nv} vertices."
            )

    # ── No-op cases ────────────────────────────────────────────────────────
    result_noop = VertexMergeResult()
    if len(unique_indices) <= 1:
        # Build copies (not references) so callers can modify safely.
        result_noop.new_cage_vertices = [
            (float(v[0]), float(v[1]), float(v[2])) for v in verts
        ]
        result_noop.new_cage_faces = [list(f) for f in faces]
        result_noop.num_verts_removed = 0
        result_noop.merged_index = unique_indices[0] if unique_indices else -1
        return result_noop

    # ── Compute centroid ───────────────────────────────────────────────────
    k = len(unique_indices)
    cx = sum(float(verts[i][0]) for i in unique_indices) / k
    cy = sum(float(verts[i][1]) for i in unique_indices) / k
    cz = sum(float(verts[i][2]) for i in unique_indices) / k

    # ── Build remap table: old_idx → new_idx ─────────────────────────────
    # Strategy:
    #   - Keep the slot of the *first* (lowest) unique index for the centroid.
    #   - Remove the remaining unique_indices (higher ones).
    #   - Remaining vertices (not in unique_set) get shifted down by the
    #     number of unique_indices that fall below them.
    keep_slot = unique_indices[0]             # lowest merged idx → becomes centroid
    remove_set = set(unique_indices[1:])      # higher merged idxs → removed

    # Number of removed vertices with index < i (i.e. how much to shift down).
    # We need a prefix count for efficient lookup.
    # Since unique_indices is sorted, we can precompute a list of removed indices.
    removed_sorted = sorted(remove_set)       # ascending list of removed indices

    def _shift_for(i: int) -> int:
        """How many removed indices are strictly less than i."""
        lo, hi = 0, len(removed_sorted)
        while lo < hi:
            mid = (lo + hi) // 2
            if removed_sorted[mid] < i:
                lo = mid + 1
            else:
                hi = mid
        return lo

    remap: List[int] = []
    for i in range(nv):
        if i in unique_set:
            # All merged vertices map to keep_slot's NEW index.
            # After removing all vertices in remove_set, keep_slot's new index
            # is keep_slot minus the number of removed vertices before it.
            new_keep = keep_slot - _shift_for(keep_slot)
            remap.append(new_keep)
        else:
            # Shift down by how many removed vertices come before i.
            remap.append(i - _shift_for(i))

    # Pre-compute the new index for keep_slot (same for all merged vertices).
    new_centroid_idx = keep_slot - _shift_for(keep_slot)

    # ── Build new vertex list ─────────────────────────────────────────────
    new_verts: List[Tuple[float, float, float]] = []
    for i in range(nv):
        if i == keep_slot:
            new_verts.append((cx, cy, cz))
        elif i in remove_set:
            pass   # skip
        else:
            x = float(verts[i][0])
            y = float(verts[i][1])
            z = float(verts[i][2])
            new_verts.append((x, y, z))

    # ── Remap and filter degenerate faces ─────────────────────────────────
    new_faces: List[List[int]] = []
    num_removed_faces = 0

    for face in faces:
        remapped = [remap[vi] for vi in face]
        if _is_degenerate(remapped):
            num_removed_faces += 1
        else:
            new_faces.append(remapped)

    # ── Assemble result ───────────────────────────────────────────────────
    result = VertexMergeResult()
    result.new_cage_vertices = new_verts
    result.new_cage_faces = new_faces
    result.num_faces_removed = num_removed_faces
    result.num_verts_removed = k - 1          # |S| vertices merged → net -1*(|S|-1)
    result.merged_index = new_centroid_idx
    return result


# ---------------------------------------------------------------------------
# LLM tool: subd_merge_vertices
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

    _merge_spec = ToolSpec(
        name="subd_merge_vertices",
        description=(
            "Merge a list of cage vertices (by index) into their centroid, "
            "updating all adjacent face indices and removing degenerate faces.\n"
            "\n"
            "This is the N-vertex generalisation of edge collapse (Hoppe 1996 §3.2): "
            "instead of collapsing exactly two edge endpoints, an arbitrary subset of "
            "vertices is fused into v_c = centroid({V[i] for i in vertex_indices}).\n"
            "\n"
            "Algorithm:\n"
            "  1. Compute centroid v_c = mean of named vertices.\n"
            "  2. Replace all face references to any named vertex with v_c.\n"
            "  3. Remove degenerate faces (those that contained ≥ 2 named vertices "
            "and now have a repeated vertex index).\n"
            "  4. Compact vertex list; renumber face indices.\n"
            "\n"
            "Special cases:\n"
            "  - Empty or single-vertex list → no-op (mesh returned unchanged).\n"
            "  - Duplicate indices → deduplicated automatically.\n"
            "  - Non-adjacent vertices (share no edge) → no degenerate faces; "
            "vertex count drops by len(unique_indices)-1.\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  - Centroid placement only — NO quadric error metric "
            "(Garland-Heckbert 1997). The centroid can deviate substantially from "
            "the original limit surface.\n"
            "  - CC limit-surface shape changes after the merge.\n"
            "  - Crease annotations on incident edges are NOT preserved.\n"
            "  - Vertex/face indices are invalidated after the merge.\n"
            "\n"
            "Inputs:\n"
            "  vertices       : [[x,y,z], ...]  cage control vertices.\n"
            "  faces          : [[i,j,k,l], ...]  face vertex-index lists.\n"
            "  vertex_indices : [int, ...]  indices of vertices to merge.\n"
            "\n"
            "Returns:\n"
            "  ok                  : bool\n"
            "  new_cage_vertices   : [[x,y,z], ...]\n"
            "  new_cage_faces      : [[i,j,...], ...]\n"
            "  num_verts           : int  new vertex count\n"
            "  num_faces           : int  new face count\n"
            "  num_faces_removed   : int  degenerate faces removed\n"
            "  num_verts_removed   : int  len(unique_indices) - 1\n"
            "  merged_index        : int  index of centroid vertex in result\n"
            "  honest_caveat       : str\n"
            "\n"
            "Refs: Hoppe (1996) Progressive Meshes §3.2; "
            "Garland-Heckbert (1997) QEM §3."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Cage control vertices as [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "minItems": 1,
                },
                "faces": {
                    "type": "array",
                    "description": "Cage face vertex-index lists.",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "minItems": 1,
                },
                "vertex_indices": {
                    "type": "array",
                    "description": (
                        "List of vertex indices to merge into their centroid. "
                        "Duplicates are silently deduplicated. "
                        "Empty or single-element list is a no-op."
                    ),
                    "items": {"type": "integer"},
                },
            },
            "required": ["vertices", "faces", "vertex_indices"],
        },
    )

    @register(_merge_spec)
    async def run_subd_merge_vertices(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_indices = a.get("vertex_indices", [])

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if raw_indices is None:
            return err_payload("vertex_indices is required", "BAD_ARGS")

        try:
            verts = [[float(c) for c in row] for row in raw_verts]
            faces = [[int(i) for i in row] for row in raw_faces]
            idxs = [int(i) for i in raw_indices]
        except Exception as exc:
            return err_payload(f"invalid geometry data: {exc}", "BAD_ARGS")

        mesh = SubDMesh(vertices=verts, faces=faces)

        try:
            res = merge_vertices(mesh, idxs)
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
            "merged_index": res.merged_index,
            "honest_caveat": res.honest_caveat,
        })
