"""subd_edge_ring.py
==================
SUBD-CAGE-RING-FROM-EDGE — given a SubD cage and a starting edge, follow the
"edge ring" around the cage (the loop of edges parallel to the start edge, as
Maya/Blender Bridge traverses).

For Catmull-Clark quad meshes:
  - An edge ring crosses opposite edges of each face.  Starting from edge (a,b),
    find the two adjacent quad faces; for each face the "opposite edge" is the
    edge sharing neither vertex with (a,b).
  - The traversal alternates faces: given the current edge and the face just
    traversed, move to the other adjacent face, find that face's opposite edge,
    and repeat.
  - Traversal terminates when:
    - We return to the start edge → closed ring.
    - We reach a boundary edge (only one adjacent face) → open ring.
    - We reach a non-quad face (triangle, pentagon, …) → degenerate transition.

CAVEATS (honest-flag)
---------------------
- Only works on pure-quad cages.  At any non-quad face the algorithm sets
  ``is_degenerate = True`` and stops traversal.
- For an extraordinary vertex (valence ≠ 4) the ring still follows opposite
  edges correctly; the degenerate flag is NOT set for valence, only for
  non-quad faces.
- Mixed quad/tri meshes return a degenerate ring at the first triangular face.

Public API
----------
compute_edge_ring(cage, start_edge) -> EdgeRingResult
    Main entry point.  ``start_edge`` is an (int, int) pair of vertex indices
    OR a raw edge index into ``cage._all_edge_keys()``.

EdgeRingResult (dataclass)
    .edge_indices          : list[tuple[int,int]]  ordered edge (v0,v1) pairs
    .is_closed             : bool
    .is_degenerate         : bool
    .transition_face_indices : list[int]           faces traversed (in order)

LLM tool: ``subd_compute_edge_ring``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, Union

from kerf_cad_core.geom.subd import SubDMesh


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class EdgeRingResult:
    """Result of edge-ring traversal.

    Attributes
    ----------
    edge_indices : list of (v0, v1) tuples
        Ordered edge pairs in the ring (canonical min-first ordering).
    is_closed : bool
        True when the ring loops back to the start edge.
    is_degenerate : bool
        True when a non-quad face was encountered during traversal.
        The ring is open (truncated) at the degenerate face.
    transition_face_indices : list of int
        Indices into cage.faces for each face traversed to reach the next ring
        edge.  Length equals ``len(edge_indices) - 1`` for open rings,
        ``len(edge_indices)`` for closed rings.
    """
    edge_indices: List[Tuple[int, int]] = field(default_factory=list)
    is_closed: bool = False
    is_degenerate: bool = False
    transition_face_indices: List[int] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _opposite_edge_in_quad(face: List[int], edge_key: Tuple[int, int]) -> Optional[Tuple[int, int]]:
    """Return the opposite edge in a quad face relative to ``edge_key``.

    For a quad face [v0, v1, v2, v3], the edge (v0,v1) is opposite to (v2,v3).

    Returns None if the face is not a quad or the edge is not in the face.
    """
    if len(face) != 4:
        return None
    v0, v1, v2, v3 = face
    e_keys = [
        (min(v0, v1), max(v0, v1)),
        (min(v1, v2), max(v1, v2)),
        (min(v2, v3), max(v2, v3)),
        (min(v3, v0), max(v3, v0)),
    ]
    # Edges are indexed 0–3; opposite pairs are (0,2) and (1,3).
    for i, ek in enumerate(e_keys):
        if ek == edge_key:
            opp_idx = (i + 2) % 4
            return e_keys[opp_idx]
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_edge_ring(
    cage: SubDMesh,
    start_edge: Union[Tuple[int, int], int],
) -> EdgeRingResult:
    """Compute the edge ring starting from ``start_edge`` on ``cage``.

    Parameters
    ----------
    cage : SubDMesh
        The control cage.
    start_edge : (int, int) or int
        Either a pair of vertex indices (order doesn't matter) or an integer
        index into the ordered edge list returned by ``cage._all_edge_keys()``.

    Returns
    -------
    EdgeRingResult
        .edge_indices           : ring edges in traversal order.
        .is_closed              : True when ring loops back to start.
        .is_degenerate          : True when a non-quad face was encountered.
        .transition_face_indices: faces crossed to reach each next edge.

    Raises
    ------
    ValueError
        If the start_edge is invalid (out of range or vertices not adjacent).
    """
    nv = len(cage.vertices)
    all_edges = cage._all_edge_keys()
    ne = len(all_edges)

    # Resolve start_edge to a canonical (min, max) key.
    if isinstance(start_edge, int):
        if not (0 <= start_edge < ne):
            raise ValueError(
                f"start_edge index {start_edge} is out of range [0, {ne})"
            )
        start_key = all_edges[start_edge]
    else:
        try:
            a, b = int(start_edge[0]), int(start_edge[1])
        except (TypeError, IndexError) as exc:
            raise ValueError(f"start_edge must be (int, int) or int: {exc}") from exc
        if not (0 <= a < nv) or not (0 <= b < nv):
            raise ValueError(
                f"start_edge vertex indices ({a}, {b}) out of range [0, {nv})"
            )
        start_key = cage.edge_key(a, b)

    # Build edge-face adjacency.
    edge_faces: Dict[Tuple[int, int], List[int]]
    edge_faces, _, _ = cage._build_adjacency()

    if start_key not in edge_faces:
        raise ValueError(
            f"start_edge {start_key} is not a valid cage edge (no adjacent faces)"
        )

    # Traverse ring in both directions from start_key, then merge.
    def _traverse_one_direction(
        current_edge: Tuple[int, int],
        from_face: Optional[int],
    ) -> Tuple[List[Tuple[int, int]], List[int], bool, bool]:
        """Walk in one direction; return (edges, faces, reached_start, degenerate)."""
        edges: List[Tuple[int, int]] = []
        faces: List[int] = []
        degenerate = False

        seen_edges: Set[Tuple[int, int]] = {start_key}

        while True:
            adj = edge_faces.get(current_edge, [])

            # Filter out the face we just came from.
            candidates = [f for f in adj if f != from_face]

            if not candidates:
                # Boundary — open ring.
                break

            next_face_idx = candidates[0]
            face = cage.faces[next_face_idx]

            if len(face) != 4:
                # Non-quad face — degenerate.
                degenerate = True
                faces.append(next_face_idx)
                break

            opp = _opposite_edge_in_quad(face, current_edge)
            if opp is None:
                # Edge not found in face — shouldn't happen, but guard.
                degenerate = True
                faces.append(next_face_idx)
                break

            faces.append(next_face_idx)

            if opp == start_key:
                # Closed ring — we're back.
                return edges, faces, True, degenerate

            if opp in seen_edges:
                # Cycle detected that isn't start_key (degenerate topology).
                degenerate = True
                break

            seen_edges.add(opp)
            edges.append(opp)
            from_face = next_face_idx
            current_edge = opp

        return edges, faces, False, degenerate

    # Determine initial two adjacent faces for start_key.
    adj_faces_start = edge_faces.get(start_key, [])

    result_edges = [start_key]
    result_faces: List[int] = []
    is_closed = False
    is_degenerate = False

    if len(adj_faces_start) == 0:
        # Isolated edge — return single-edge open ring.
        return EdgeRingResult(
            edge_indices=[start_key],
            is_closed=False,
            is_degenerate=False,
            transition_face_indices=[],
        )

    # Traverse "forward" (through adj_faces_start[0]).
    fwd_edges, fwd_faces, fwd_closed, fwd_degen = _traverse_one_direction(
        start_key, from_face=None if len(adj_faces_start) < 2 else adj_faces_start[1]
    )
    # Traverse "backward" (through adj_faces_start[1] if it exists).
    if len(adj_faces_start) >= 2:
        bwd_edges, bwd_faces, bwd_closed, bwd_degen = _traverse_one_direction(
            start_key, from_face=adj_faces_start[0]
        )
    else:
        bwd_edges, bwd_faces, bwd_closed, bwd_degen = [], [], False, False

    if fwd_closed or bwd_closed:
        # Closed ring: fwd_closed means forward traversal looped back.
        # In that case the ring is: start + fwd_edges, with fwd_faces.
        is_closed = True
        is_degenerate = fwd_degen or bwd_degen
        result_edges = [start_key] + fwd_edges
        result_faces = fwd_faces
    else:
        # Open ring: stitch backward (reversed) + start + forward.
        is_degenerate = fwd_degen or bwd_degen
        result_edges = list(reversed(bwd_edges)) + [start_key] + fwd_edges
        result_faces = list(reversed(bwd_faces)) + fwd_faces

    return EdgeRingResult(
        edge_indices=result_edges,
        is_closed=is_closed,
        is_degenerate=is_degenerate,
        transition_face_indices=result_faces,
    )


# ---------------------------------------------------------------------------
# LLM tool: subd_compute_edge_ring
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

    _spec_ring = ToolSpec(
        name="subd_compute_edge_ring",
        description=(
            "Compute the edge ring for a SubD cage starting from a given edge.\n"
            "\n"
            "An edge ring on a Catmull-Clark quad cage follows the chain of edges\n"
            "that cross opposite sides of each quad face — like Maya/Blender Bridge.\n"
            "\n"
            "Algorithm: from start_edge, find adjacent quad faces; for each face\n"
            "find the opposite edge (sharing no vertex with start_edge); continue\n"
            "until the ring closes or hits a boundary/non-quad face.\n"
            "\n"
            "HONEST CAVEATS:\n"
            "  - Only pure-quad cages produce complete rings.\n"
            "  - Non-quad face → is_degenerate=true, ring truncated at transition.\n"
            "  - Boundary edge → is_closed=false (open ring).\n"
            "\n"
            "Inputs:\n"
            "  vertices   : [[x,y,z], ...]  control cage vertices.\n"
            "  faces      : [[i,j,k,l], ...]  face index lists (quads recommended).\n"
            "  start_edge : [v0, v1]  pair of vertex indices for the starting edge;\n"
            "               or an integer index into the cage edge list.\n"
            "  creases    : {\"a,b\": sharpness, ...}  optional crease map.\n"
            "\n"
            "Returns: {\n"
            "  ok: bool,\n"
            "  edge_indices: [[v0,v1], ...],\n"
            "  is_closed: bool,\n"
            "  is_degenerate: bool,\n"
            "  transition_face_indices: [int, ...],\n"
            "  ring_length: int\n"
            "}"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                    "minItems": 2,
                },
                "faces": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "minItems": 1,
                },
                "start_edge": {
                    "oneOf": [
                        {
                            "type": "array",
                            "items": {"type": "integer"},
                            "minItems": 2,
                            "maxItems": 2,
                            "description": "[v0, v1] vertex-index pair",
                        },
                        {
                            "type": "integer",
                            "minimum": 0,
                            "description": "Integer index into the cage edge list",
                        },
                    ],
                    "description": "Starting edge: [v0, v1] pair or integer edge index",
                },
                "creases": {
                    "type": "object",
                    "additionalProperties": {"type": "number"},
                    "description": "Optional edge creases as {\"a,b\": sharpness}",
                },
            },
            "required": ["vertices", "faces", "start_edge"],
        },
    )

    @register(_spec_ring)
    async def run_subd_compute_edge_ring(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        try:
            verts = [[float(c) for c in row] for row in a.get("vertices", [])]
            faces = [[int(i) for i in f] for f in a.get("faces", [])]
        except Exception as exc:
            return err_payload(f"invalid cage: {exc}", "BAD_ARGS")

        raw_se = a.get("start_edge")
        if raw_se is None:
            return err_payload("start_edge is required", "BAD_ARGS")
        if isinstance(raw_se, int):
            start_edge: Union[int, Tuple[int, int]] = int(raw_se)
        else:
            try:
                start_edge = (int(raw_se[0]), int(raw_se[1]))
            except Exception as exc:
                return err_payload(f"invalid start_edge: {exc}", "BAD_ARGS")

        cage = SubDMesh(vertices=verts, faces=faces)
        for key_str, sharpness in (a.get("creases") or {}).items():
            try:
                parts = key_str.split(",")
                av, bv = int(parts[0]), int(parts[1])
                cage.set_crease(av, bv, float(sharpness))
            except Exception:
                pass

        try:
            result = compute_edge_ring(cage, start_edge)
        except ValueError as exc:
            return err_payload(str(exc), "BAD_ARGS")
        except Exception as exc:
            return err_payload(f"ring computation failed: {exc}", "INTERNAL_ERROR")

        return ok_payload({
            "ok": True,
            "edge_indices": [list(e) for e in result.edge_indices],
            "is_closed": result.is_closed,
            "is_degenerate": result.is_degenerate,
            "transition_face_indices": result.transition_face_indices,
            "ring_length": len(result.edge_indices),
        })
