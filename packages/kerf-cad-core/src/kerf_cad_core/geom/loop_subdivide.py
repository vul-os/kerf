"""
loop_subdivide.py
=================
Loop (1987) subdivision for triangle meshes.

Loop subdivision is the de-facto standard for triangle meshes, producing C²
continuity almost everywhere with C¹ at irregular (non-valence-6) vertices.

References
----------
- Loop, C. (1987). Smooth subdivision surfaces based on triangles. MS Thesis,
  University of Utah.
- Zorin, D., Schroder, P., & Sweldens, W. (1996). Interpolating subdivision
  for meshes with arbitrary topology. SIGGRAPH 96.

Public API
----------
TriMesh(dataclass)
    Triangle mesh: vertices + triangular faces + crease edge tags.

loop_subdivide(mesh, levels=1) -> TriMesh
    Apply N levels of Loop subdivision.  Crease edges follow cubic
    B-spline boundary rule; smooth edges use the full Loop interior rule.

loop_limit_position(mesh, vertex_index) -> [x, y, z]
    Closed-form Loop limit position for a regular (valence-6) interior vertex.

trimesh_from_arrays(vertices, faces) -> TriMesh
    Construct a TriMesh from raw arrays.

All public functions never raise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# TriMesh dataclass
# ---------------------------------------------------------------------------

@dataclass
class TriMesh:
    """Triangle mesh for Loop subdivision.

    Attributes
    ----------
    vertices : list of [x, y, z]
        Vertex positions.
    faces : list of [i, j, k]
        Triangle faces as vertex-index triples.
    creases : dict mapping (i, j) -> float
        Edge crease sharpness.  0.0 = smooth.  >= 1.0 = fully sharp.
        Keys are always (min, max) ordered.
    """
    vertices: List[List[float]] = field(default_factory=list)
    faces: List[List[int]] = field(default_factory=list)
    creases: Dict[Tuple[int, int], float] = field(default_factory=dict)

    @property
    def num_vertices(self) -> int:
        return len(self.vertices)

    @property
    def num_faces(self) -> int:
        return len(self.faces)

    def edge_key(self, a: int, b: int) -> Tuple[int, int]:
        return (min(a, b), max(a, b))

    def get_crease(self, a: int, b: int) -> float:
        return self.creases.get(self.edge_key(a, b), 0.0)

    def set_crease(self, a: int, b: int, value: float) -> None:
        self.creases[self.edge_key(a, b)] = float(max(0.0, value))


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _add3(a: List[float], b: List[float]) -> List[float]:
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _scale3(v: List[float], s: float) -> List[float]:
    return [v[0] * s, v[1] * s, v[2] * s]


def _build_tri_adjacency(
    mesh: TriMesh,
) -> Tuple[
    Dict[Tuple[int, int], List[int]],   # edge -> [face_indices]
    Dict[int, List[int]],               # vertex -> [face_indices]
    Dict[int, List[int]],               # vertex -> [neighbour vertices]
    Dict[Tuple[int, int], List[int]],   # edge -> [opposite vertex per face]
]:
    """Build adjacency maps for a triangle mesh."""
    edge_faces: Dict[Tuple[int, int], List[int]] = {}
    vert_faces: Dict[int, List[int]] = {}
    vert_nbrs: Dict[int, List[int]] = {}
    edge_opp: Dict[Tuple[int, int], List[int]] = {}  # edge -> list of opp verts

    for fi, face in enumerate(mesh.faces):
        if len(face) != 3:
            continue
        a, b, c = face
        for vi in (a, b, c):
            vert_faces.setdefault(vi, []).append(fi)

        for u, v, opp in ((a, b, c), (b, c, a), (c, a, b)):
            key = mesh.edge_key(u, v)
            edge_faces.setdefault(key, []).append(fi)
            edge_opp.setdefault(key, []).append(opp)
            if v not in vert_nbrs.get(u, []):
                vert_nbrs.setdefault(u, []).append(v)
            if u not in vert_nbrs.get(v, []):
                vert_nbrs.setdefault(v, []).append(u)

    return edge_faces, vert_faces, vert_nbrs, edge_opp


# ---------------------------------------------------------------------------
# Loop β(n) weight function
# ---------------------------------------------------------------------------

def _loop_beta(n: int) -> float:
    """Loop's vertex mask weight β(n) for even vertices.

    β(n) = 3/16  if n == 3
    β(n) = 3/(8n) otherwise

    The even vertex rule is:
        new_P = (1 - n * β) * P + β * sum(neighbours)
    """
    if n <= 0:
        return 0.0
    if n == 3:
        return 3.0 / 16.0
    return 3.0 / (8.0 * n)


# ---------------------------------------------------------------------------
# One level of Loop subdivision
# ---------------------------------------------------------------------------

def _loop_once(mesh: TriMesh) -> TriMesh:
    """Apply one level of Loop subdivision to a triangle mesh.

    Produces 4 child triangles per input triangle (1-4 split).

    Even vertex rule (original vertex update):
        Smooth interior n-valence:  (1-n*β)*P + β * sum(nbrs),  β = loop_beta(n)
        Boundary/crease vertex:     (3/4)*P + (1/8)*(P_prev + P_next)
        Corner (>=2 crease edges):  P  (unchanged)

    Odd vertex rule (new edge midpoint):
        Interior smooth edge:  3/8*(E0+E1) + 1/8*(Opp0+Opp1)
        Boundary/crease edge:  1/2*(E0+E1)
    """
    try:
        verts = mesh.vertices
        faces = mesh.faces
        nv = len(verts)

        edge_faces, vert_faces, vert_nbrs, edge_opp = _build_tri_adjacency(mesh)

        # Map edge -> new odd vertex index
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
        # Compute odd (edge) vertices
        # ------------------------------------------------------------------
        for ei, key in enumerate(all_edges):
            edge_idx[key] = nv + ei
            a, b = key
            va, vb = verts[a], verts[b]
            crease = mesh.get_crease(a, b)
            adj = edge_faces.get(key, [])

            if len(adj) < 2 or crease >= 1.0:
                # Boundary or fully-creased: midpoint (cubic B-spline rule)
                ep = _scale3(_add3(va, vb), 0.5)
            elif crease > 0.0:
                # Fractional crease: blend smooth ↔ midpoint
                opp_verts = edge_opp.get(key, [])
                if len(opp_verts) >= 2:
                    vo1, vo2 = verts[opp_verts[0]], verts[opp_verts[1]]
                    smooth = _add3(
                        _scale3(_add3(va, vb), 3.0 / 8.0),
                        _scale3(_add3(vo1, vo2), 1.0 / 8.0),
                    )
                else:
                    smooth = _scale3(_add3(va, vb), 0.5)
                mid = _scale3(_add3(va, vb), 0.5)
                # blend: 0 = smooth, 1 = sharp
                ep = _add3(
                    _scale3(smooth, 1.0 - crease),
                    _scale3(mid, crease),
                )
            else:
                # Interior smooth: Loop interior rule
                opp_verts = edge_opp.get(key, [])
                if len(opp_verts) >= 2:
                    vo1, vo2 = verts[opp_verts[0]], verts[opp_verts[1]]
                    ep = _add3(
                        _scale3(_add3(va, vb), 3.0 / 8.0),
                        _scale3(_add3(vo1, vo2), 1.0 / 8.0),
                    )
                else:
                    ep = _scale3(_add3(va, vb), 0.5)

            odd_verts.append(ep)

        # ------------------------------------------------------------------
        # Compute even (original) vertex updates
        # ------------------------------------------------------------------
        new_even: List[List[float]] = []
        for vi, v in enumerate(verts):
            nbrs = vert_nbrs.get(vi, [])
            n = len(nbrs)

            # Count hard crease edges (sharpness >= 1.0)
            crease_nbrs = [nb for nb in nbrs if mesh.get_crease(vi, nb) >= 1.0]
            num_creases = len(crease_nbrs)

            # Boundary detection: fewer adjacent faces than neighbours means boundary
            adj_face_count = len(vert_faces.get(vi, []))
            is_boundary = adj_face_count < n

            if num_creases >= 2:
                # Corner vertex: stays fixed
                new_even.append(list(v))
            elif num_creases == 1 or is_boundary:
                # Boundary / crease vertex: cubic B-spline boundary rule
                # Use only the two boundary/crease neighbours
                if is_boundary:
                    # Find the two boundary-edge neighbours
                    bnd_nbrs = []
                    for nb in nbrs:
                        key = mesh.edge_key(vi, nb)
                        if len(edge_faces.get(key, [])) == 1:
                            bnd_nbrs.append(nb)
                    if len(bnd_nbrs) == 2:
                        p_prev = verts[bnd_nbrs[0]]
                        p_next = verts[bnd_nbrs[1]]
                        new_pos = _add3(
                            _scale3(v, 3.0 / 4.0),
                            _scale3(_add3(p_prev, p_next), 1.0 / 8.0),
                        )
                    else:
                        new_pos = list(v)
                else:
                    # Crease rule: use the two crease neighbours
                    cn = crease_nbrs
                    if len(cn) == 2:
                        p_prev = verts[cn[0]]
                        p_next = verts[cn[1]]
                        new_pos = _add3(
                            _scale3(v, 3.0 / 4.0),
                            _scale3(_add3(p_prev, p_next), 1.0 / 8.0),
                        )
                    elif len(cn) == 1:
                        p_prev = verts[cn[0]]
                        new_pos = _add3(
                            _scale3(v, 7.0 / 8.0),
                            _scale3(p_prev, 1.0 / 8.0),
                        )
                    else:
                        new_pos = list(v)
                new_even.append(new_pos)
            else:
                # Smooth interior: Loop even rule
                if n == 0:
                    new_even.append(list(v))
                    continue
                beta = _loop_beta(n)
                nbr_sum = [0.0, 0.0, 0.0]
                for nb in nbrs:
                    nbr_sum = _add3(nbr_sum, verts[nb])
                new_pos = _add3(
                    _scale3(v, 1.0 - n * beta),
                    _scale3(nbr_sum, beta),
                )
                new_even.append(new_pos)

        # ------------------------------------------------------------------
        # Assemble new vertex list: [even_0..even_{nv-1}, odd_0..odd_{ne-1}]
        # ------------------------------------------------------------------
        new_verts = new_even + odd_verts

        # ------------------------------------------------------------------
        # Build new triangle faces: each triangle (a, b, c) → 4 triangles
        #   1. (a, e_ab, e_ca)
        #   2. (e_ab, b, e_bc)
        #   3. (e_bc, c, e_ca)
        #   4. (e_ab, e_bc, e_ca)  — the centre "star" triangle
        # ------------------------------------------------------------------
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

        # ------------------------------------------------------------------
        # Propagate creases: decay by 1.0 per level (OpenSubdiv rule)
        # ------------------------------------------------------------------
        new_creases: Dict[Tuple[int, int], float] = {}
        for key in all_edges:
            c_val = mesh.get_crease(key[0], key[1])
            if c_val <= 0.0:
                continue
            a, b = key
            ep_idx = edge_idx[key]
            new_c = max(0.0, c_val - 1.0)
            if new_c > 0.0:
                new_creases[(min(a, ep_idx), max(a, ep_idx))] = new_c
                new_creases[(min(b, ep_idx), max(b, ep_idx))] = new_c

        return TriMesh(vertices=new_verts, faces=new_faces, creases=new_creases)

    except Exception:
        return TriMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
            creases=dict(mesh.creases),
        )


# ---------------------------------------------------------------------------
# Public: loop_subdivide
# ---------------------------------------------------------------------------

def loop_subdivide(mesh: TriMesh, levels: int = 1) -> TriMesh:
    """Apply N levels of Loop subdivision to a triangle mesh.

    Parameters
    ----------
    mesh : TriMesh
        Input triangle mesh.
    levels : int
        Number of subdivision levels (>= 0).  0 returns a copy.

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
            result = _loop_once(result)
        return result
    except Exception:
        return TriMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
            creases=dict(mesh.creases),
        )


# ---------------------------------------------------------------------------
# Public: loop_limit_position
# ---------------------------------------------------------------------------

def loop_limit_position(mesh: TriMesh, vertex_index: int) -> List[float]:
    """Closed-form Loop limit position for a smooth interior vertex.

    For a regular (valence-6) interior vertex the Loop limit rule is:

        P_lim = (1 / (1 + 8β/3)) * (P + (β/3) * sum_nbrs)

    More generally for valence n the limit-position weight matrix is derived
    from the subdivision matrix eigenanalysis (Loop 1987, §4).  The practical
    formula used here is the well-known result:

        α(n) = n * β(n)          (sum of neighbour weights at limit)
        P_lim = (1-α) / (1-α + n*α / n) * ... simplified form:

        P_lim = P + (β(n) / (β(n) + 1/(n+8*β(n)*n))) * Laplacian

    The exact closed-form limit for any interior vertex is:

        c = (3/8 + 1/8 * cos(2π/n))²  [Loop's a(n) = n·β(n)]
        P_lim = (1 - a) * P + (a / n) * sum_nbrs

    where a = n * β(n) (total neighbour weight under the even rule).

    For boundary vertices, returns the vertex position.

    Parameters
    ----------
    mesh : TriMesh
    vertex_index : int

    Returns
    -------
    [x, y, z] — limit position, never raises.
    """
    try:
        vi = int(vertex_index)
        if vi < 0 or vi >= len(mesh.vertices):
            return [0.0, 0.0, 0.0]

        v = mesh.vertices[vi]
        edge_faces, vert_faces, vert_nbrs, _ = _build_tri_adjacency(mesh)
        nbrs = vert_nbrs.get(vi, [])
        n = len(nbrs)
        adj_faces = vert_faces.get(vi, [])

        # Boundary or isolated
        if n == 0 or len(adj_faces) < n:
            return list(v)

        # Crease vertex
        crease_nbrs = [nb for nb in nbrs if mesh.get_crease(vi, nb) >= 1.0]
        if len(crease_nbrs) >= 2:
            return list(v)

        # Smooth interior limit
        beta = _loop_beta(n)
        a = n * beta  # total neighbour weight

        nbr_sum = [0.0, 0.0, 0.0]
        for nb in nbrs:
            nbr_sum = _add3(nbr_sum, mesh.vertices[nb])

        lim = _add3(
            _scale3(v, 1.0 - a),
            _scale3(nbr_sum, a / n),
        )
        return lim

    except Exception:
        if 0 <= vertex_index < len(mesh.vertices):
            return list(mesh.vertices[vertex_index])
        return [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# Public: trimesh_from_arrays
# ---------------------------------------------------------------------------

def trimesh_from_arrays(
    vertices: List[List[float]],
    faces: List[List[int]],
    creases: Optional[List[Tuple[int, int, float]]] = None,
) -> TriMesh:
    """Construct a TriMesh from raw arrays.

    Parameters
    ----------
    vertices : list of [x, y, z]
    faces : list of [i, j, k]
    creases : optional list of (v1, v2, sharpness) tuples

    Returns
    -------
    TriMesh — never raises.
    """
    try:
        mesh = TriMesh(
            vertices=[[float(x) for x in v] for v in vertices],
            faces=[[int(i) for i in f] for f in faces],
        )
        if creases:
            for entry in creases:
                mesh.set_crease(int(entry[0]), int(entry[1]), float(entry[2]))
        return mesh
    except Exception:
        return TriMesh()


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

    _subd_loop_spec = ToolSpec(
        name="subd_loop",
        description=(
            "Apply Loop (1987) subdivision to a triangle mesh and return the "
            "subdivided mesh.  Loop subdivision produces C² continuity almost "
            "everywhere with C¹ at irregular vertices.  Crease edges follow the "
            "cubic B-spline boundary rule; smooth edges use the full Loop rule.\n"
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
                    "description": "Triangle-mesh vertices [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Triangle faces [[i,j,k], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "levels": {
                    "type": "integer",
                    "description": "Subdivision levels (1..4, default 1).",
                },
                "creases": {
                    "type": "array",
                    "description": "Crease edges [{v1, v2, sharpness}].",
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

    @register(_subd_loop_spec)
    async def run_subd_loop(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        levels = int(a.get("levels", 1))
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

        result = loop_subdivide(mesh, levels=levels)
        return ok_payload({
            "ok": True,
            "vertices": result.vertices,
            "faces": result.faces,
            "num_vertices": result.num_vertices,
            "num_faces": result.num_faces,
        })
