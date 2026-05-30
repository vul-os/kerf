"""
subd_subdivide_edge.py
======================
SUBD-CAGE-SUBDIVIDE-EDGE — localized single-edge refinement on a SubD cage.

Given an edge index, inserts a midpoint vertex (or a weighted point along the
edge) and splits each adjacent face into two new faces.  This is a fundamental
cage-modeling primitive analogous to Maya ``polySplit`` and Blender
``subdivide_edges``, operating directly on the control cage without running a
full Catmull-Clark pass.

References
----------
* Catmull, E. & Clark, J. (1978). "Recursively generated B-spline surfaces on
  arbitrary topological meshes." *Computer-Aided Design*, 10(6), 350-355.
  DOI: 10.1016/0010-4485(78)90110-0
  — subdivision theory; face-split preserves the CC limit surface neighbourhood
  when the new vertex lies on the original limit position of the edge.

* Stam, J. (1998). "Exact evaluation of Catmull-Clark subdivision surfaces at
  arbitrary parameter values." *SIGGRAPH 98*, 395-404.
  — local refinement in §4: subdivision around an extraordinary vertex can be
  applied one ring at a time; single-edge split is the degenerate case of a
  one-ring local refinement.

* Autodesk Maya (2024). ``polySplit`` command reference.
  https://help.autodesk.com/view/MAYAUL/ENU/?guid=__CommandsPython_polySplit_html
  — interactive edge split at parametric position; face topology choices.

Algorithm
---------
1. Validate edge_index and locate endpoints v_a, v_b in cage.vertices.
2. Compute v_m = lerp(v_a, v_b, position_t).
3. Find the 1 or 2 faces adjacent to the edge.
4. Replace each adjacent face with 2 sub-faces:
   - ``split_strategy="quad"`` (default): each quad [p0, p1, p2, p3] with
     split edge p0–p1 becomes:
       face A: [p0, v_m, p3]              (triangle — honest flag)
       face B: [v_m, p1, p2, p3]          (quad)
     OR for the ``"tri"`` strategy:
       face A: [p0, v_m, p3]              (triangle)
       face B: [v_m, p1, p2, p3]          (triangle / polygon)
     Both strategies are topologically identical for a quad input; the name
     refers to the intent.  Non-quad input faces are split the same way.
5. Return SubdivideEdgeResult(new_cage, new_vertex_index, new_face_count).

Honest flags
------------
* Only quad-cage input is officially supported.  Non-quad faces are split using
  the same vertex-insertion rule, but the result is an approximation — the
  mixed-topology cage will not subdivide as cleanly under Catmull-Clark.
  ``SubdivideEdgeResult.has_non_quad_input`` is True when this occurs.
* Sharpness / bevel-weight indices are rebuilt from scratch on the new cage
  (old edge ids are invalid after topology change); the old values are silently
  dropped.  This matches the policy in ``subd_edge_split`` and ``subd_bevel``.

Topology counts for cube edge split (verification oracle)
----------------------------------------------------------
Cube cage: V=8, E=12, F=6.
After splitting one interior edge (shared by 2 quad faces):
    V' = 8 + 1 = 9
    F' = 6 - 2 + 4 = 8    (2 affected faces each become 2)
    E' = 12 - 1 + 2 + 2 = 15  (split edge → 2 halves; each adjacent face
                                gets 1 new interior edge)
    Euler:  V' - E' + F' = 9 - 15 + 8 = 2  ✓  (sphere topology χ=2)

For a boundary edge (only 1 adjacent face):
    V' = 9, F' = F + 1, E' = E + 2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from kerf_cad_core.geom.subd_authoring import SubDCage


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SubdivideEdgeResult:
    """Result of a single-edge cage subdivision.

    Attributes
    ----------
    new_cage : SubDCage
        Updated cage with the extra vertex and split faces.
    new_vertex_index : int
        Index of the inserted midpoint vertex in ``new_cage.vertices``.
    new_face_count : int
        Total number of faces in ``new_cage`` (``new_cage.num_faces``).
    adjacent_face_count : int
        Number of faces that were adjacent to the split edge (1 for boundary,
        2 for interior).
    has_non_quad_input : bool
        True if any adjacent face had valence != 4 (honest flag — see module
        docstring).
    """

    new_cage: SubDCage = field(default_factory=SubDCage)
    new_vertex_index: int = -1
    new_face_count: int = 0
    adjacent_face_count: int = 0
    has_non_quad_input: bool = False


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _copy_verts(cage: SubDCage) -> List[List[float]]:
    return [list(v) for v in cage.vertices]


def _lerp(va: List[float], vb: List[float], t: float) -> List[float]:
    return [
        va[0] + t * (vb[0] - va[0]),
        va[1] + t * (vb[1] - va[1]),
        va[2] + t * (vb[2] - va[2]),
    ]


def _find_adjacent_faces(
    cage: SubDCage,
    edge_key: Tuple[int, int],
) -> List[int]:
    """Return indices of faces in cage.faces that contain edge_key."""
    adj: List[int] = []
    a, b = edge_key
    for fi, face in enumerate(cage.faces):
        n = len(face)
        for i in range(n):
            u, w = face[i], face[(i + 1) % n]
            if (min(u, w), max(u, w)) == edge_key:
                adj.append(fi)
                break
    return adj


def _split_face(
    face: List[int],
    edge_key: Tuple[int, int],
    new_vi: int,
) -> List[List[int]]:
    """Split a single face at the given edge by inserting new_vi.

    The face is rotated so that the split edge is at position 0 → 1.
    Then the face [r0, r1, r2, ..., r_{n-1}] with edge r0–r1 is split into:
        face_a: [r0, new_vi, r_{n-1}]                   (triangle)
        face_b: [new_vi, r1, r2, ..., r_{n-1}]           (polygon)

    For a quad (n=4):
        face_a: [r0, new_vi, r3]       (triangle)
        face_b: [new_vi, r1, r2, r3]   (quad)

    Euler delta per incident face: ΔV=0 (v_m already added), ΔF=+1, ΔE=+2
    → V - E + F is preserved.

    Note: face_a is always a triangle.  For a pure-quad cage this means
    each split introduces one triangle.  Callers should document the
    has_non_quad_input honest flag accordingly when face inputs are quads
    (the *output* contains triangles, which is expected and documented).
    """
    n = len(face)
    # Rotate so the split edge is at index 0 → 1.
    edge_pos = -1
    for i in range(n):
        u, w = face[i], face[(i + 1) % n]
        if (min(u, w), max(u, w)) == edge_key:
            edge_pos = i
            break

    if edge_pos < 0:
        # Should not happen (caller already checked), but be safe.
        return [list(face)]

    r = [face[(edge_pos + k) % n] for k in range(n)]

    # Respect winding: if edge in face is (r0 → r1) order, keep orientation.
    # face_a: [r0, new_vi, r_{n-1}]
    # face_b: [new_vi, r1, r2, ..., r_{n-1}]
    face_a = [r[0], new_vi, r[n - 1]]
    face_b = [new_vi, r[1]] + [r[k] for k in range(2, n)]
    return [face_a, face_b]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def subdivide_edge(
    cage: SubDCage,
    edge_index: int,
    position_t: float = 0.5,
    split_strategy: str = "quad",
) -> SubdivideEdgeResult:
    """Insert a midpoint vertex on a single cage edge (localized refinement).

    Implements SUBD-CAGE-SUBDIVIDE-EDGE.  This is the cage-level analogue of
    Maya ``polySplit`` or Blender ``subdivide_edges`` for a single edge — it
    inserts one new vertex without running a full Catmull-Clark pass.

    References: Catmull & Clark 1978 §3; Stam 1998 §4 (local refinement);
    Maya polySplit API (Autodesk 2024).

    Parameters
    ----------
    cage : SubDCage
        Input control cage.  Must be a quad cage for topologically clean
        results; mixed-topology cages are accepted but trigger the
        ``has_non_quad_input`` honest flag.
    edge_index : int
        Index of the edge to subdivide, from ``cage.cage_edges()``.
    position_t : float
        Parametric position along the edge in (0, 1).  0.5 = midpoint.
        Clamped to [1e-9, 1-1e-9] to avoid degenerate zero-length edges.
    split_strategy : str
        ``"quad"`` (default) or ``"tri"``.  Currently both strategies use the
        same face-split topology (face_a=triangle, face_b=polygon).  The
        parameter is reserved for future strategies that connect the midpoint
        to the face centroid to produce pure-quad output.

    Returns
    -------
    SubdivideEdgeResult
        new_cage, new_vertex_index, new_face_count, adjacent_face_count,
        has_non_quad_input.

    Raises
    ------
    ValueError
        If edge_index is out of range.  All other errors produce a copy of the
        input cage wrapped in a SubdivideEdgeResult.

    Honest flags
    ------------
    * Only quad-cage input is fully supported.  Non-quad adjacent faces are
      split using the same rule; results are an approximation.
    * Output faces include triangles (face_a in each split).  This is correct
      and expected — a single edge split on a quad necessarily yields one
      triangle per adjacent face (two quads would require inserting a second
      vertex on the opposite edge, which is a loop-cut, not an edge-split).
    * Sharpness / bevel-weight metadata is not preserved across edge-index
      remapping (same policy as ``subd_bevel`` and ``subd_edge_split``).
    """
    try:
        t = max(1e-9, min(1.0 - 1e-9, float(position_t)))
        eid = int(edge_index)

        edges = cage.cage_edges()
        if eid < 0 or eid >= len(edges):
            raise ValueError(
                f"edge_index {eid} out of range [0, {len(edges) - 1}]"
            )

        a, b = edges[eid]
        va = cage.vertices[a]
        vb = cage.vertices[b]

        # Step 1: compute new midpoint vertex.
        v_m = _lerp(va, vb, t)
        new_vi = len(cage.vertices)

        # Step 2: find adjacent faces.
        edge_key: Tuple[int, int] = (min(a, b), max(a, b))
        adj_indices = _find_adjacent_faces(cage, edge_key)

        # Step 3: build new face list.
        adj_set = set(adj_indices)
        new_verts = _copy_verts(cage) + [v_m]
        new_faces: List[List[int]] = []
        has_non_quad = False

        for fi, face in enumerate(cage.faces):
            if fi not in adj_set:
                new_faces.append(list(face))
            else:
                if len(face) != 4:
                    has_non_quad = True
                sub = _split_face(face, edge_key, new_vi)
                new_faces.extend(sub)

        result_cage = SubDCage(vertices=new_verts, faces=new_faces)

        return SubdivideEdgeResult(
            new_cage=result_cage,
            new_vertex_index=new_vi,
            new_face_count=result_cage.num_faces,
            adjacent_face_count=len(adj_indices),
            has_non_quad_input=has_non_quad,
        )

    except ValueError:
        raise
    except Exception as exc:
        # Soft fallback: return a copy of the original cage.
        fallback = SubDCage(
            vertices=[list(v) for v in cage.vertices],
            faces=[list(f) for f in cage.faces],
        )
        return SubdivideEdgeResult(
            new_cage=fallback,
            new_vertex_index=-1,
            new_face_count=fallback.num_faces,
            adjacent_face_count=0,
            has_non_quad_input=False,
        )
