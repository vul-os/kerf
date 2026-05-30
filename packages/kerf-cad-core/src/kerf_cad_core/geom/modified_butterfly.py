"""
modified_butterfly.py
=====================
Modified Butterfly (Zorin-Schroder-Sweldens 1996) interpolating subdivision.

Modified Butterfly is an interpolating scheme for triangle meshes: every
original vertex is preserved exactly across subdivision levels.  It produces
C¹-continuous limit surfaces with C² away from irregular vertices.

References
----------
- Zorin, D., Schroder, P., & Sweldens, W. (1996). Interpolating subdivision
  for meshes with arbitrary topology. SIGGRAPH 96, pp. 189-192.
- Butterfly: Dyn, N., Levin, D., & Gregory, J. A. (1990). A butterfly
  subdivision scheme for surface interpolation with tension control.
  ACM Transactions on Graphics, 9(2), 160-169.

Stencil summary
---------------
Even vertices (original): preserved exactly (interpolating).

Odd vertex (edge midpoint) stencil for edge (A, B):
  - Regular case (both endpoints have valence 6):
      4-2-2-1 stencil (see below) with tension w = 1/16
  - Irregular case (valence != 6 at A or B):
      Per-endpoint stencil averaged at midpoint (Zorin 1996, §3.2)

Regular 4-2-2-1 stencil (Butterfly, w=1/16):
    The two edge endpoints and their one-ring define the stencil.
    For regular valence-6 mesh the stencil is:
        1/2  * (A + B)
       +1/8  * (c0 + c1)   [two common face verts, i.e., the "wing" verts]
       -1/16 * (d0 + d1 + d2 + d3)  [the "tail" verts of the two one-rings]
    This is the classic "butterfly" stencil.
    With w = 1/16:
        e = 1/2*(A+B) + (2w)*(c0+c1) + (-w)*(d0+d1+d2+d3)
    (Note: 2w = 1/8 and w = 1/16 as in Dyn-Levin-Gregory; Zorin 1996 §3.1.)

Irregular stencil (Zorin 1996, Appendix A):
    For valence n endpoint, compute the limit-tangent-weighted stencil over
    the n neighbours, using the weights:
        s_j = (1/n) * (1/4 + cos(2πj/n) + 1/2 * cos(4πj/n))
    for j = 0..n-1, where j indexes the one-ring neighbours in order.
    The endpoint weight sums to 3/4; the n-ring sum sums to 1/4.

Boundary:
    Boundary edge midpoints use the midpoint rule.

All public functions never raise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from kerf_cad_core.geom.loop_subdivide import (
    TriMesh,
    _build_tri_adjacency,
    _add3,
    _scale3,
    trimesh_from_arrays,
)


# ---------------------------------------------------------------------------
# Butterfly stencil helpers
# ---------------------------------------------------------------------------

def _butterfly_irregular_weights(n: int) -> List[float]:
    """Zorin 1996 irregular stencil weights for an endpoint of valence n.

    Returns list of n weights for the n one-ring neighbours, ordered by
    the fan around the endpoint.

    s_j = (1/n) * (1/4 + cos(2πj/n) + (1/2) * cos(4πj/n))

    The endpoint itself has weight 3/4; the n weights sum to 1/4.
    """
    weights = []
    for j in range(n):
        angle = 2.0 * math.pi * j / n
        w = (1.0 / n) * (0.25 + math.cos(angle) + 0.5 * math.cos(2.0 * angle))
        weights.append(w)
    return weights


def _ordered_one_ring(
    vi: int,
    mesh: TriMesh,
    edge_faces: Dict,
    vert_faces: Dict,
) -> List[int]:
    """Return the one-ring of vertex vi in CCW fan order.

    For interior vertices, walks the fan.  Returns neighbours in order.
    Falls back to unordered if fan walk fails.
    """
    nbrs_raw = set()
    for fi in vert_faces.get(vi, []):
        face = mesh.faces[fi]
        if vi in face:
            for u in face:
                if u != vi:
                    nbrs_raw.add(u)

    nbrs = list(nbrs_raw)
    if len(nbrs) <= 1:
        return nbrs

    # Try to order them by walking the face fan
    # Build face adjacency per neighbour pair
    ordered = []
    remaining = set(nbrs)

    # Pick the first face containing vi
    adj_faces_of_vi = vert_faces.get(vi, [])
    if not adj_faces_of_vi:
        return nbrs

    # Start from the first face
    current_face_idx = adj_faces_of_vi[0]
    face = mesh.faces[current_face_idx]
    # Get the two non-vi vertices of this face in order
    idx = face.index(vi)
    ordered.append(face[(idx + 1) % 3])
    ordered.append(face[(idx + 2) % 3])
    remaining.discard(ordered[0])
    remaining.discard(ordered[1])

    # Walk to adjacent faces
    max_iter = len(nbrs) * 2
    iter_count = 0
    while remaining and iter_count < max_iter:
        iter_count += 1
        last = ordered[-1]
        found_next = False
        for fi in vert_faces.get(vi, []):
            f = mesh.faces[fi]
            if vi in f and last in f:
                for u in f:
                    if u != vi and u != last and u in remaining:
                        ordered.append(u)
                        remaining.discard(u)
                        found_next = True
                        break
            if found_next:
                break
        if not found_next:
            break

    # Append any stragglers (shouldn't happen for well-formed mesh)
    ordered.extend(remaining)
    return ordered


# ---------------------------------------------------------------------------
# One level of Modified Butterfly subdivision
# ---------------------------------------------------------------------------

def _modified_butterfly_once(mesh: TriMesh, w: float = 1.0 / 16.0) -> TriMesh:
    """Apply one level of Modified Butterfly subdivision.

    Parameters
    ----------
    mesh : TriMesh
    w : float
        Tension parameter (default 1/16).  Dyn 1990 / Zorin 1996 default.
    """
    try:
        verts = mesh.vertices
        faces = mesh.faces
        nv = len(verts)

        edge_faces, vert_faces, vert_nbrs, edge_opp = _build_tri_adjacency(mesh)

        # Collect all unique edges
        all_edges: List[Tuple[int, int]] = []
        seen_edges: Set[Tuple[int, int]] = set()
        for face in faces:
            if len(face) != 3:
                continue
            a, b, c = face
            for u, v in ((a, b), (b, c), (c, a)):
                key = mesh.edge_key(u, v)
                if key not in seen_edges:
                    seen_edges.add(key)
                    all_edges.append(key)

        edge_idx: Dict[Tuple[int, int], int] = {}
        odd_verts: List[List[float]] = []

        # ------------------------------------------------------------------
        # Even vertices: interpolating — positions are PRESERVED EXACTLY
        # ------------------------------------------------------------------
        new_even = [list(v) for v in verts]

        # ------------------------------------------------------------------
        # Compute odd (edge midpoint) vertices
        # ------------------------------------------------------------------
        REGULAR_VALENCE = 6  # regular valence for triangular meshes

        for ei, key in enumerate(all_edges):
            edge_idx[key] = nv + ei
            a, b = key
            va, vb = verts[a], verts[b]
            adj = edge_faces.get(key, [])
            crease = mesh.get_crease(a, b)

            if len(adj) < 2 or crease >= 1.0:
                # Boundary or fully-creased: midpoint
                odd_verts.append(_scale3(_add3(va, vb), 0.5))
                continue

            if crease > 0.0:
                # Fractional crease: blend smooth ↔ midpoint
                mid = _scale3(_add3(va, vb), 0.5)
                # Compute smooth odd vertex (regular formula)
                opp_verts = edge_opp.get(key, [])
                if len(opp_verts) >= 2:
                    c0, c1 = verts[opp_verts[0]], verts[opp_verts[1]]
                    smooth = _add3(
                        _scale3(_add3(va, vb), 0.5),
                        _add3(
                            _scale3(_add3(c0, c1), 2.0 * w),
                            _scale3([0.0, 0.0, 0.0], 0.0),
                        ),
                    )
                else:
                    smooth = mid
                ep = _add3(
                    _scale3(smooth, 1.0 - crease),
                    _scale3(mid, crease),
                )
                odd_verts.append(ep)
                continue

            # Smooth interior edge
            va_nbrs = vert_nbrs.get(a, [])
            vb_nbrs = vert_nbrs.get(b, [])
            na = len(va_nbrs)
            nb_val = len(vb_nbrs)

            # Boundary detection
            a_is_interior = len(vert_faces.get(a, [])) >= na
            b_is_interior = len(vert_faces.get(b, [])) >= nb_val

            a_regular = a_is_interior and na == REGULAR_VALENCE
            b_regular = b_is_interior and nb_val == REGULAR_VALENCE

            if a_regular and b_regular:
                # Regular butterfly stencil:
                # e = 1/2*(A+B) + 2w*(c0+c1) - w*(d0+d1+d2+d3)
                # c0, c1: the two shared face vertices (wing vertices)
                # d0..d3: the "far" vertices (A's other neighbours opposite c0,c1
                #          and B's other neighbours opposite c0,c1)
                opp_verts = edge_opp.get(key, [])
                if len(opp_verts) < 2:
                    odd_verts.append(_scale3(_add3(va, vb), 0.5))
                    continue
                c0_idx, c1_idx = opp_verts[0], opp_verts[1]
                c0, c1 = verts[c0_idx], verts[c1_idx]

                # Find d-vertices: for vertex A, the two neighbours other than
                # B, c0, c1 (i.e. the "opposite" verts in A's one-ring).
                # For the regular case these are the two non-c0/c1 neighbours
                # of A and B that are NOT b and NOT a respectively.
                excluded_a = {b, c0_idx, c1_idx}
                d_from_a = [verts[u] for u in va_nbrs if u not in excluded_a]
                excluded_b = {a, c0_idx, c1_idx}
                d_from_b = [verts[u] for u in vb_nbrs if u not in excluded_b]

                # Standard Butterfly: uses exactly 2 from A and 2 from B
                # (valence 6 means 5 neighbours + the edge partner = 6 total)
                # d from A = 2 verts, d from B = 2 verts
                ep = _scale3(_add3(va, vb), 0.5)
                ep = _add3(ep, _scale3(_add3(c0, c1), 2.0 * w))
                for dv in d_from_a[:2]:
                    ep = _add3(ep, _scale3(dv, -w))
                for dv in d_from_b[:2]:
                    ep = _add3(ep, _scale3(dv, -w))

                odd_verts.append(ep)

            else:
                # Irregular endpoint(s): Zorin 1996 §3.2
                # Compute stencil for each endpoint independently then average.
                def _endpoint_stencil(
                    ep_vi: int,
                    ep_v: List[float],
                    ep_nbrs: List[int],
                    ep_is_interior: bool,
                ) -> List[float]:
                    n_val = len(ep_nbrs)
                    if n_val == 0:
                        return list(ep_v)

                    if not ep_is_interior:
                        # Boundary endpoint: 3/4 * ep + 1/4 * edge_partner
                        # (degenerate; midpoint fallback)
                        return list(ep_v)

                    if n_val == 3:
                        # Valence 3: special case weights from Zorin 1996
                        # s = {5/12, -1/12, -1/12}
                        ordered = _ordered_one_ring(ep_vi, mesh, edge_faces, vert_faces)
                        if len(ordered) >= 3:
                            ep_result = _scale3(ep_v, 3.0 / 4.0)
                            sp_weights = [5.0 / 12.0, -1.0 / 12.0, -1.0 / 12.0]
                            for j, w_j in enumerate(sp_weights):
                                ep_result = _add3(ep_result, _scale3(verts[ordered[j % len(ordered)]], w_j))
                        else:
                            ep_result = list(ep_v)
                        return ep_result
                    elif n_val == 4:
                        # Valence 4: weights {3/8, 0, -1/8, 0}
                        ordered = _ordered_one_ring(ep_vi, mesh, edge_faces, vert_faces)
                        if len(ordered) >= 4:
                            sp_weights = [3.0 / 8.0, 0.0, -1.0 / 8.0, 0.0]
                            ep_result = _scale3(ep_v, 3.0 / 4.0)
                            for j, w_j in enumerate(sp_weights):
                                ep_result = _add3(ep_result, _scale3(verts[ordered[j % len(ordered)]], w_j))
                        else:
                            ep_result = list(ep_v)
                        return ep_result
                    else:
                        # General irregular: Zorin 1996 weights
                        ordered = _ordered_one_ring(ep_vi, mesh, edge_faces, vert_faces)
                        irr_weights = _butterfly_irregular_weights(n_val)
                        ep_result = _scale3(ep_v, 3.0 / 4.0)
                        for j, w_j in enumerate(irr_weights):
                            if j < len(ordered):
                                ep_result = _add3(ep_result, _scale3(verts[ordered[j]], w_j))
                        return ep_result

                contrib_a = _endpoint_stencil(a, va, va_nbrs, a_is_interior)
                contrib_b = _endpoint_stencil(b, vb, vb_nbrs, b_is_interior)

                if a_regular and not b_regular:
                    # Only B is irregular: use B's stencil
                    ep = contrib_b
                elif b_regular and not a_regular:
                    # Only A is irregular: use A's stencil
                    ep = contrib_a
                else:
                    # Both irregular: average
                    ep = _scale3(_add3(contrib_a, contrib_b), 0.5)

                odd_verts.append(ep)

        # ------------------------------------------------------------------
        # Assemble mesh
        # ------------------------------------------------------------------
        new_verts = new_even + odd_verts

        new_faces: List[List[int]] = []
        for face in faces:
            if len(face) != 3:
                continue
            a, b, c = face
            e_ab = edge_idx[mesh.edge_key(a, b)]
            e_bc = edge_idx[mesh.edge_key(b, c)]
            e_ca = edge_idx[mesh.edge_key(c, a)]
            new_faces.append([a,    e_ab, e_ca])
            new_faces.append([e_ab, b,    e_bc])
            new_faces.append([e_bc, c,    e_ca])
            new_faces.append([e_ab, e_bc, e_ca])

        # Propagate creases
        new_creases: Dict[Tuple[int, int], float] = {}
        for key in all_edges:
            c_val = mesh.get_crease(key[0], key[1])
            if c_val <= 0.0:
                continue
            a2, b2 = key
            ep_idx_val = edge_idx[key]
            new_c = max(0.0, c_val - 1.0)
            if new_c > 0.0:
                new_creases[(min(a2, ep_idx_val), max(a2, ep_idx_val))] = new_c
                new_creases[(min(b2, ep_idx_val), max(b2, ep_idx_val))] = new_c

        return TriMesh(vertices=new_verts, faces=new_faces, creases=new_creases)

    except Exception:
        return TriMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
            creases=dict(mesh.creases),
        )


# ---------------------------------------------------------------------------
# Public: modified_butterfly_subdivide
# ---------------------------------------------------------------------------

def modified_butterfly_subdivide(
    mesh: TriMesh,
    levels: int = 1,
    w: float = 1.0 / 16.0,
) -> TriMesh:
    """Apply N levels of Modified Butterfly subdivision.

    Parameters
    ----------
    mesh : TriMesh
        Input triangle mesh.
    levels : int
        Number of subdivision levels (>= 0).  0 returns a copy.
    w : float
        Tension parameter (default 1/16).

    Returns
    -------
    TriMesh — never raises.
    """
    try:
        levels = max(0, int(levels))
        result = TriMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
            creases=dict(mesh.creases),
        )
        for _ in range(levels):
            result = _modified_butterfly_once(result, w=w)
        return result
    except Exception:
        return TriMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
            creases=dict(mesh.creases),
        )


# ---------------------------------------------------------------------------
# LLM tool registration
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

    _subd_modified_butterfly_spec = ToolSpec(
        name="subd_modified_butterfly",
        description=(
            "Apply Modified Butterfly (Zorin-Schroder-Sweldens 1996) interpolating "
            "subdivision to a triangle mesh.  Every original vertex is preserved "
            "exactly across levels (interpolating scheme).  Produces C¹ limit "
            "surfaces with C² away from irregular vertices.\n"
            "\n"
            "Parameters:\n"
            "  vertices : [[x,y,z], ...]\n"
            "  faces    : [[i,j,k], ...] — triangle faces\n"
            "  levels   : int (1..4, default 1)\n"
            "  w        : float — tension parameter (default 0.0625 = 1/16)\n"
            "\n"
            "Returns:\n"
            "  ok           : bool\n"
            "  vertices     : [[x,y,z], ...]\n"
            "  faces        : [[i,j,k], ...]\n"
            "  num_vertices : int\n"
            "  num_faces    : int\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "levels": {
                    "type": "integer",
                    "description": "Subdivision levels (1..4, default 1).",
                },
                "w": {
                    "type": "number",
                    "description": "Tension parameter (default 1/16 = 0.0625).",
                },
                "creases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "v1": {"type": "integer"},
                            "v2": {"type": "integer"},
                            "sharpness": {"type": "number"},
                        },
                        "required": ["v1", "v2", "sharpness"],
                    },
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_modified_butterfly_spec)
    async def run_subd_modified_butterfly(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        levels = int(a.get("levels", 1))
        tension_w = float(a.get("w", 1.0 / 16.0))
        raw_creases = a.get("creases", [])

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if levels < 0 or levels > 6:
            return err_payload("levels must be 0..6", "BAD_ARGS")

        try:
            mesh = TriMesh(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid mesh: {exc}", "BAD_ARGS")

        for ce in raw_creases:
            try:
                mesh.set_crease(int(ce["v1"]), int(ce["v2"]), float(ce["sharpness"]))
            except Exception:
                pass

        result = modified_butterfly_subdivide(mesh, levels=levels, w=tension_w)
        return ok_payload({
            "ok": True,
            "vertices": result.vertices,
            "faces": result.faces,
            "num_vertices": result.num_vertices,
            "num_faces": result.num_faces,
        })
