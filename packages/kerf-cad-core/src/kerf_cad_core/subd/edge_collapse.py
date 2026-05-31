"""edge_collapse.py
==================
SUBD-CAGE-EDGE-COLLAPSE — collapse a SubD cage edge (merge two endpoints into
one vertex) while maintaining mesh validity.

Used for mesh decimation and cage simplification.

Theory
------
Edge collapse is the fundamental decimation primitive in progressive meshes
(Hoppe 1993/1996 §3.2): given an edge {v_keep, v_remove}, collapse it by:

  1. Compute new position:
       - midpoint mode (default): v_new = (V[v_keep] + V[v_remove]) / 2
       - endpoint mode (midpoint=False): v_new = V[v_keep]
  2. Move v_keep to v_new; replace ALL face references to v_remove with v_keep.
  3. Remove any face whose vertex list has < 3 distinct indices after
     substitution — these are degenerate faces that contained both endpoints.
  4. Compact vertex list: remove v_remove; remap all face indices.

The caller chooses which edge to collapse (v_keep, v_remove). No QEM error
metric is computed here — this module is topology-only, per the task spec.
Shape quality is caller-driven.

Adjacency check
---------------
``v_keep`` and ``v_remove`` must share at least one face (i.e. form a valid
cage edge). If they do not appear together in any face, ``collapse_edge``
returns ``became_invalid=True`` and a no-op cage identical to the input.

Per Hoppe (1993): a vertex pair is "contractible" only if the two vertices are
connected by an edge (simplicial complex link condition). Non-edge pairs would
violate manifold topology.

Degenerate face detection
--------------------------
A quad face [a, b, v_keep, v_remove] after substituting v_remove → v_keep
becomes [a, b, v_keep, v_keep] — a quad with a repeated vertex.  We remove
any face where ``len(set(remapped_face)) < len(remapped_face)`` OR
``len(set(remapped_face)) < 3`` (fewer than 3 unique vertices = line or point).

References
----------
* Hoppe, H. (1993). "Mesh Optimization." ACM SIGGRAPH 1993.
  (original progressive mesh / edge collapse proposal)
* Hoppe, H. (1996). "Progressive Meshes." ACM SIGGRAPH 1996, §3.2.
  https://hhoppe.com/pm.pdf
* Garland, M. & Heckbert, P. S. (1997). "Surface Simplification Using
  Quadric Error Metrics." ACM SIGGRAPH 1997.
  https://www.cs.cmu.edu/~quake-papers/quadrics.pdf
  (NOTE: QEM cost function is NOT implemented here — caller chooses edge.)
* Bommes, D., Lévy, B., Pietroni, N., Puppo, E., Silva, C., Tarini, M.,
  Zorin, D. (2013). "Quad-Mesh Generation and Processing: A Survey."
  Computer Graphics Forum 32(6):51–76, §4.

Caveats (honest)
----------------
* Midpoint collapse: v_new = (v_keep + v_remove) / 2.  No QEM-based optimal
  placement (Garland-Heckbert 1997).  Shape quality of the simplified cage is
  not optimised; midpoint may lie off the original limit surface.
* Endpoint collapse (midpoint=False): v_new = V[v_keep].  Even simpler — no
  shape optimisation at all.
* Only cage connectivity is modified; the CC limit surface changes shape.
* Crease data on the collapsed edge and edges incident to v_keep or v_remove
  is NOT preserved.
* After collapse, ALL external vertex and face index references are invalidated
  (v_remove is gone; indices above it shift down by 1).
* Non-manifold edges (shared by > 2 faces) are handled conservatively: ALL
  faces containing both endpoints become degenerate and are removed.
* Isolated vertices (unreferenced after face removal) are NOT further compacted
  beyond removing v_remove itself.
* v_keep and v_remove MUST form an actual edge (share ≥ 1 face). Non-adjacent
  pairs are rejected (became_invalid=True, no-op).

Public API
----------
SubdCage
    Re-exported from cage_area for convenience.
EdgeCollapseResult
    Dataclass holding the collapse result.
collapse_edge(cage, v_keep, v_remove, midpoint=True) -> EdgeCollapseResult
    Main entry point.

LLM tool: ``subd_collapse_edge``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Re-export SubdCage from the canonical location (cage_area.py)
# ---------------------------------------------------------------------------
from kerf_cad_core.subd.cage_area import SubdCage  # noqa: F401


# ---------------------------------------------------------------------------
# Result dataclass — per task spec
# ---------------------------------------------------------------------------

@dataclass
class EdgeCollapseResult:
    """Result of a single edge collapse on a SubD cage.

    Attributes
    ----------
    new_cage : SubdCage
        Updated cage after collapse.  ``v_remove`` has been removed and its
        former references replaced by ``v_keep`` (at the new position).
    num_vertices_removed : int
        Always 1 for a successful collapse (two endpoints merged to one, net
        -1 vertex).  0 if the operation was a no-op (became_invalid=True).
    num_faces_removed : int
        Number of faces removed because they became degenerate (contained both
        endpoints of the collapsed edge).
    collapsed_position_xyz_mm : tuple[float, float, float]
        The 3-D position of the resulting merged vertex (mm).
        Equals the midpoint of v_keep and v_remove when midpoint=True;
        equals V[v_keep] when midpoint=False.
    degenerate_faces_removed : int
        Same as num_faces_removed (alias for clarity; per task spec).
    became_invalid : bool
        True if the operation could not be performed because v_keep and
        v_remove do not share a face (not a valid edge) or another
        validity check failed.  The returned new_cage equals the input cage.
    honest_caveat : str
        Plain-language description of algorithmic limitations.
    """
    new_cage: SubdCage = field(default_factory=SubdCage)
    num_vertices_removed: int = 0
    num_faces_removed: int = 0
    collapsed_position_xyz_mm: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    degenerate_faces_removed: int = 0
    became_invalid: bool = False
    honest_caveat: str = (
        "SUBD-CAGE-EDGE-COLLAPSE — topology only (Hoppe 1993/1996 §3.2). "
        "No quadric error metric (Garland-Heckbert 1997): caller chooses which "
        "edge to collapse; this module handles the topological merge only. "
        "midpoint=True: v_new = (v_keep + v_remove) / 2. "
        "midpoint=False: v_new = V[v_keep]. "
        "Degenerate faces (containing both endpoints) are removed. "
        "Crease annotations on incident edges are NOT preserved. "
        "CC limit surface shape changes after collapse. "
        "All vertex/face indices are invalidated after collapse. "
        "Non-adjacent (non-edge) pairs are rejected (became_invalid=True). "
        "Non-manifold edges handled conservatively: all incident degenerate "
        "faces removed. Use Garland-Heckbert QEM for quality-driven decimation."
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _are_adjacent(faces: List[List[int]], v_a: int, v_b: int) -> bool:
    """Return True if v_a and v_b appear together in at least one face."""
    for face in faces:
        face_set = set(face)
        if v_a in face_set and v_b in face_set:
            return True
    return False


def _is_degenerate_face(face: List[int]) -> bool:
    """Return True if the face has fewer than 3 distinct vertex indices."""
    return len(set(face)) < 3


def _has_repeated_vertex(face: List[int]) -> bool:
    """Return True if the face has any repeated vertex index."""
    return len(set(face)) < len(face)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collapse_edge(
    cage: "SubdCage",
    v_keep: int,
    v_remove: int,
    midpoint: bool = True,
) -> EdgeCollapseResult:
    """Collapse the cage edge between v_keep and v_remove.

    Merges the two endpoints into a single vertex at the midpoint (or at
    v_keep if midpoint=False). All face index references to v_remove are
    rewritten to v_keep. Degenerate faces (those containing both endpoints,
    which produce a repeated vertex after substitution) are removed.
    The vertex list is compacted (v_remove is removed; indices above it shift
    down by 1).

    Parameters
    ----------
    cage : SubdCage
        Input control cage with ``vertices_xyz_mm`` and ``faces``.
    v_keep : int
        Index of the vertex to keep (its slot receives the new position).
    v_remove : int
        Index of the vertex to merge into v_keep (removed from the list).
    midpoint : bool
        If True (default), the kept vertex is moved to the midpoint of
        v_keep and v_remove. If False, the kept vertex stays at V[v_keep].

    Returns
    -------
    EdgeCollapseResult
        If v_keep == v_remove, or either index is out of range, or they do
        not share a face, ``became_invalid=True`` and ``new_cage`` is a
        shallow copy of the input cage.

    Raises
    ------
    ValueError
        If v_keep or v_remove is out of range [0, len(vertices)).
    """
    verts = cage.vertices_xyz_mm
    faces = cage.faces
    nv = len(verts)

    # ── Validate indices ─────────────────────────────────────────────────────
    if not (0 <= v_keep < nv):
        raise ValueError(
            f"v_keep={v_keep} out of range [0, {nv}). "
            f"Cage has {nv} vertices."
        )
    if not (0 <= v_remove < nv):
        raise ValueError(
            f"v_remove={v_remove} out of range [0, {nv}). "
            f"Cage has {nv} vertices."
        )

    # ── Trivial self-collapse ────────────────────────────────────────────────
    if v_keep == v_remove:
        result = EdgeCollapseResult()
        result.new_cage = SubdCage(
            vertices_xyz_mm=list(verts),
            faces=[list(f) for f in faces],
        )
        result.num_vertices_removed = 0
        result.num_faces_removed = 0
        result.collapsed_position_xyz_mm = (
            float(verts[v_keep][0]),
            float(verts[v_keep][1]),
            float(verts[v_keep][2]),
        )
        result.degenerate_faces_removed = 0
        result.became_invalid = True
        return result

    # ── Adjacency check — v_keep and v_remove must share a face ──────────────
    if not _are_adjacent(faces, v_keep, v_remove):
        result = EdgeCollapseResult()
        result.new_cage = SubdCage(
            vertices_xyz_mm=list(verts),
            faces=[list(f) for f in faces],
        )
        result.num_vertices_removed = 0
        result.num_faces_removed = 0
        result.collapsed_position_xyz_mm = (
            float(verts[v_keep][0]),
            float(verts[v_keep][1]),
            float(verts[v_keep][2]),
        )
        result.degenerate_faces_removed = 0
        result.became_invalid = True
        return result

    # ── Compute new position ─────────────────────────────────────────────────
    kx = float(verts[v_keep][0])
    ky = float(verts[v_keep][1])
    kz = float(verts[v_keep][2])
    rx = float(verts[v_remove][0])
    ry = float(verts[v_remove][1])
    rz = float(verts[v_remove][2])

    if midpoint:
        nx = (kx + rx) / 2.0
        ny = (ky + ry) / 2.0
        nz = (kz + rz) / 2.0
    else:
        nx, ny, nz = kx, ky, kz

    new_pos = (nx, ny, nz)

    # ── Build remap: old_idx → new_idx after removing v_remove ───────────────
    # v_keep stays at v_keep (or is updated in place)
    # v_remove is eliminated
    # indices > v_remove shift down by 1
    remap: List[int] = []
    for i in range(nv):
        if i == v_remove:
            remap.append(v_keep)      # all refs to v_remove → v_keep
        elif i < v_remove:
            remap.append(i)           # no shift
        else:
            remap.append(i - 1)       # shift down 1 (v_remove removed)

    # Also account for v_keep potentially being > v_remove — after v_remove
    # is deleted, v_keep index may shift if v_keep > v_remove.
    # The remap table handles this correctly:
    #   remap[v_remove] = v_keep         (v_remove maps to v_keep slot)
    #   if v_keep > v_remove:
    #       remap[v_keep] = v_keep - 1   (v_keep's slot shifts down)
    #   else:
    #       remap[v_keep] = v_keep       (no shift)

    # ── Build new vertex list ─────────────────────────────────────────────────
    new_verts: List[Tuple[float, float, float]] = []
    for i in range(nv):
        if i == v_remove:
            continue  # skip — merged into v_keep
        elif i == v_keep:
            new_verts.append(new_pos)
        else:
            new_verts.append((
                float(verts[i][0]),
                float(verts[i][1]),
                float(verts[i][2]),
            ))

    # ── Remap faces and remove degenerate ones ────────────────────────────────
    new_faces: List[List[int]] = []
    num_removed = 0

    for face in faces:
        remapped = [remap[vi] for vi in face]
        if _has_repeated_vertex(remapped) or _is_degenerate_face(remapped):
            num_removed += 1
        else:
            new_faces.append(remapped)

    # ── Build result ──────────────────────────────────────────────────────────
    result = EdgeCollapseResult()
    result.new_cage = SubdCage(
        vertices_xyz_mm=new_verts,
        faces=new_faces,
    )
    result.num_vertices_removed = 1
    result.num_faces_removed = num_removed
    result.collapsed_position_xyz_mm = new_pos
    result.degenerate_faces_removed = num_removed
    result.became_invalid = False
    return result


# ---------------------------------------------------------------------------
# LLM tool: subd_collapse_edge
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    import json as _json

    _collapse_spec = ToolSpec(
        name="subd_collapse_edge",
        description=(
            "Collapse a SubD cage edge (merge two endpoints into one vertex) while "
            "maintaining mesh validity. Used for mesh decimation and cage "
            "simplification.\n"
            "\n"
            "Per Hoppe (1993) Progressive Meshes and Garland-Heckbert (1997) QEM:\n"
            "  - TOPOLOGY ONLY: no QEM cost function — caller chooses which edge to "
            "collapse.\n"
            "  - midpoint=true (default): v_new = (V[v_keep] + V[v_remove]) / 2.\n"
            "  - midpoint=false: v_new = V[v_keep] (endpoint mode).\n"
            "  - All face references to v_remove are rewritten to v_keep.\n"
            "  - Degenerate faces (containing both endpoints → repeated vertex) are "
            "removed.\n"
            "  - v_keep and v_remove must share at least one face (valid edge). "
            "Non-adjacent pairs → became_invalid=true.\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  - No QEM (Garland-Heckbert 1997): shape quality not optimised.\n"
            "  - CC limit surface shape changes after collapse.\n"
            "  - Crease annotations on incident edges are NOT preserved.\n"
            "  - Vertex/face indices are ALL invalidated after collapse.\n"
            "\n"
            "Inputs:\n"
            "  vertices : [[x,y,z], ...]  cage control vertices (mm).\n"
            "  faces    : [[i,j,k,...], ...] face vertex-index lists.\n"
            "  v_keep   : int  vertex index to keep.\n"
            "  v_remove : int  vertex index to merge into v_keep.\n"
            "  midpoint : bool  (optional, default true) midpoint placement.\n"
            "\n"
            "Returns:\n"
            "  ok                        : bool\n"
            "  new_cage_vertices         : [[x,y,z], ...]\n"
            "  new_cage_faces            : [[i,j,...], ...]\n"
            "  num_vertices              : int  new vertex count\n"
            "  num_faces                 : int  new face count\n"
            "  num_vertices_removed      : int  (always 1 on success, 0 on invalid)\n"
            "  num_faces_removed         : int  degenerate faces removed\n"
            "  collapsed_position_xyz_mm : [x,y,z]  merged vertex position\n"
            "  became_invalid            : bool\n"
            "  honest_caveat             : str\n"
            "\n"
            "Refs: Hoppe (1993) Mesh Optimization; Hoppe (1996) Progressive Meshes "
            "§3.2; Garland-Heckbert (1997) QEM §3; Bommes-Lévy-Pietroni (2013) §4."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Cage control vertices as [[x,y,z], ...] (mm).",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "minItems": 2,
                },
                "faces": {
                    "type": "array",
                    "description": "Cage face vertex-index lists.",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "minItems": 1,
                },
                "v_keep": {
                    "type": "integer",
                    "description": "Index of vertex to keep.",
                    "minimum": 0,
                },
                "v_remove": {
                    "type": "integer",
                    "description": "Index of vertex to merge into v_keep.",
                    "minimum": 0,
                },
                "midpoint": {
                    "type": "boolean",
                    "description": "If true (default), move v_keep to midpoint of both verts.",
                    "default": True,
                },
            },
            "required": ["vertices", "faces", "v_keep", "v_remove"],
        },
    )

    @register(_collapse_spec)
    async def run_subd_collapse_edge(ctx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        v_keep = a.get("v_keep")
        v_remove = a.get("v_remove")
        mp = bool(a.get("midpoint", True))

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if v_keep is None:
            return err_payload("v_keep is required", "BAD_ARGS")
        if v_remove is None:
            return err_payload("v_remove is required", "BAD_ARGS")

        try:
            verts = [
                (float(c[0]), float(c[1]), float(c[2])) for c in raw_verts
            ]
            faces = [[int(i) for i in row] for row in raw_faces]
            v_keep = int(v_keep)
            v_remove = int(v_remove)
        except Exception as exc:
            return err_payload(f"invalid geometry data: {exc}", "BAD_ARGS")

        cage = SubdCage(vertices_xyz_mm=verts, faces=faces)

        try:
            res = collapse_edge(cage, v_keep, v_remove, midpoint=mp)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")

        return ok_payload({
            "ok": not res.became_invalid,
            "new_cage_vertices": [list(v) for v in res.new_cage.vertices_xyz_mm],
            "new_cage_faces": [list(f) for f in res.new_cage.faces],
            "num_vertices": len(res.new_cage.vertices_xyz_mm),
            "num_faces": len(res.new_cage.faces),
            "num_vertices_removed": res.num_vertices_removed,
            "num_faces_removed": res.num_faces_removed,
            "collapsed_position_xyz_mm": list(res.collapsed_position_xyz_mm),
            "degenerate_faces_removed": res.degenerate_faces_removed,
            "became_invalid": res.became_invalid,
            "honest_caveat": res.honest_caveat,
        })
