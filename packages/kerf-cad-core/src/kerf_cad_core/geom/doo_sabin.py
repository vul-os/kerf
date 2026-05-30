"""
doo_sabin.py
============
Doo-Sabin (1978) subdivision for arbitrary polygon meshes.

Doo-Sabin is a face-based generalization of bi-quadratic B-spline subdivision.
It handles arbitrary polygons (triangles, quads, n-gons) and converges to a
bi-quadratic limit surface (versus Catmull-Clark's bi-cubic).

Widely used in engineering CAD for organic surfaces and for subdivision
starting from arbitrary polygon meshes.

References
----------
- Doo, D., & Sabin, M. (1978). Behaviour of recursive division surfaces near
  extraordinary points. Computer-Aided Design, 10(6), 356-360.
- Catmull, E., & Clark, J. (1978). Recursively generated B-spline surfaces on
  arbitrary topological meshes. Computer-Aided Design, 10(6), 350-355.

Algorithm
---------
Each subdivision step:
  1. For every face F of n vertices, create n new "face-vertex" points:
       FV_{F,i} = (1/n) * P_i  +  ((n+5)/(4n)) * avg(P_j, j!=i)  [approx]
     The exact Doo-Sabin formula for face F with vertices P_0..P_{n-1}:
       FV_{F,i} = c_{0,n} * P_i + sum_{j!=i} c_{j-i mod n, n} * P_j
     where the coefficients are:
       c_{0,n} = (n+5) / (4n)
       c_{k,n} = (3 + 2*cos(2πk/n)) / (4n)  for k = 1..n-1
     This is the uniform Doo-Sabin formula (§3 of the 1978 paper).

  2. New face topology:
     a. **Face faces**: Each original n-face spawns a new n-gon from its
        n new face-vertex points (F-face).
     b. **Edge faces**: Each shared edge (a, b) between faces F1 and F2
        spawns a new quad from the 4 relevant face-vertex points:
          FV_{F1,a}, FV_{F1,b}, FV_{F2,b}, FV_{F2,a}
        (one new vertex per endpoint per adjacent face).
        Boundary edges are not quad-extended (the edge is on the boundary).
     c. **Vertex faces**: At each original vertex v, shared by faces
        F_0, F_1, ..., F_{k-1} (in CCW order), a new k-gon is formed
        from FV_{F_0,v}, FV_{F_1,v}, ..., FV_{F_{k-1},v}.

All public functions never raise.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# PolyMesh dataclass (shared with Doo-Sabin; works for arbitrary n-gons)
# ---------------------------------------------------------------------------

@dataclass
class PolyMesh:
    """Polygon mesh for Doo-Sabin subdivision.

    Attributes
    ----------
    vertices : list of [x, y, z]
    faces : list of vertex-index lists (arbitrary polygon lengths)
    """
    vertices: List[List[float]] = field(default_factory=list)
    faces: List[List[int]] = field(default_factory=list)

    @property
    def num_vertices(self) -> int:
        return len(self.vertices)

    @property
    def num_faces(self) -> int:
        return len(self.faces)

    def edge_key(self, a: int, b: int) -> Tuple[int, int]:
        return (min(a, b), max(a, b))


# ---------------------------------------------------------------------------
# Doo-Sabin coefficient c_{k, n}
# ---------------------------------------------------------------------------

def _ds_coefficient(k: int, n: int) -> float:
    """Doo-Sabin face-vertex coefficient.

    c_{0, n} = (n + 5) / (4n)
    c_{k, n} = (3 + 2*cos(2πk/n)) / (4n)  for k != 0
    """
    if n <= 0:
        return 0.0
    if k % n == 0:
        return (n + 5.0) / (4.0 * n)
    return (3.0 + 2.0 * math.cos(2.0 * math.pi * k / n)) / (4.0 * n)


# ---------------------------------------------------------------------------
# One level of Doo-Sabin subdivision
# ---------------------------------------------------------------------------

def _doo_sabin_once(mesh: PolyMesh) -> PolyMesh:
    """Apply one level of Doo-Sabin subdivision.

    Returns a new PolyMesh with:
    - Face faces (one per original face)
    - Edge faces (one per interior edge)
    - Vertex faces (one per original vertex)
    """
    try:
        verts = mesh.vertices
        faces = mesh.faces

        # ------------------------------------------------------------------
        # Step 1: Compute face-vertex points
        # FV_{fi, i} = sum_j  c_{|i-j|, n} * P_{face[j]}
        # where n = len(face), indices are mod n.
        # ------------------------------------------------------------------
        # fv_indices[fi][local_i] = global index in new_verts
        fv_indices: List[List[int]] = []
        new_verts: List[List[float]] = []

        for fi, face in enumerate(faces):
            n = len(face)
            row: List[int] = []
            for i in range(n):
                # Compute new face-vertex point
                pt = [0.0, 0.0, 0.0]
                for j in range(n):
                    k = (i - j) % n
                    coeff = _ds_coefficient(k, n)
                    pj = verts[face[j]]
                    pt[0] += coeff * pj[0]
                    pt[1] += coeff * pj[1]
                    pt[2] += coeff * pj[2]
                idx = len(new_verts)
                new_verts.append(pt)
                row.append(idx)
            fv_indices.append(row)

        # ------------------------------------------------------------------
        # Step 2: Build edge -> [(face_idx, local_vertex_idx_for_endpoint)]
        # We need to know for each edge (a, b): which faces share it, and
        # in which local position each endpoint appears in that face.
        # ------------------------------------------------------------------
        # edge_key -> list of (face_idx, local_idx_of_a, local_idx_of_b)
        edge_face_map: Dict[Tuple[int, int], List[Tuple[int, int, int]]] = {}
        for fi, face in enumerate(faces):
            n = len(face)
            for li in range(n):
                a = face[li]
                b = face[(li + 1) % n]
                key = mesh.edge_key(a, b)
                # local index in face for a and b
                li_a = li
                li_b = (li + 1) % n
                edge_face_map.setdefault(key, []).append((fi, li_a, li_b))

        # vertex -> ordered list of (face_idx, local_idx_of_vertex_in_face)
        vert_face_map: Dict[int, List[Tuple[int, int]]] = {}
        for fi, face in enumerate(faces):
            for li, vi in enumerate(face):
                vert_face_map.setdefault(vi, []).append((fi, li))

        # ------------------------------------------------------------------
        # Step 3: Assemble new faces
        # ------------------------------------------------------------------
        new_faces: List[List[int]] = []

        # 3a. Face faces — one new n-gon per original face
        for fi, face in enumerate(faces):
            new_faces.append(list(fv_indices[fi]))

        # 3b. Edge faces — one new quad per interior edge
        for key, face_entries in edge_face_map.items():
            if len(face_entries) < 2:
                # Boundary edge: skip (no edge face)
                continue
            # Take first two face entries for this edge
            fi1, li_a1, li_b1 = face_entries[0]
            fi2, li_a2, li_b2 = face_entries[1]
            # Edge quad:
            # FV_{F1, a}, FV_{F1, b}, FV_{F2, b}, FV_{F2, a}
            p0 = fv_indices[fi1][li_a1]
            p1 = fv_indices[fi1][li_b1]
            p2 = fv_indices[fi2][li_b2]
            p3 = fv_indices[fi2][li_a2]
            new_faces.append([p0, p1, p2, p3])

        # 3c. Vertex faces — one new k-gon per original vertex
        # The vertex face is formed by collecting the face-vertex points
        # for this vertex from all adjacent faces, in CCW order.
        # We need to order the adjacent faces around each vertex.
        for vi in range(len(verts)):
            entries = vert_face_map.get(vi, [])
            if len(entries) == 0:
                continue
            if len(entries) == 1:
                # Isolated vertex in a single face: just a point, skip
                continue

            # Try to order the adjacent faces in CCW order around this vertex.
            # We do this by walking the edge-face map.
            ordered = _order_faces_around_vertex(vi, entries, mesh, edge_face_map)
            if len(ordered) >= 3:
                v_face_pts = [fv_indices[fi][li] for fi, li in ordered]
                new_faces.append(v_face_pts)

        return PolyMesh(vertices=new_verts, faces=new_faces)

    except Exception:
        return PolyMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
        )


def _order_faces_around_vertex(
    vi: int,
    entries: List[Tuple[int, int]],
    mesh: PolyMesh,
    edge_face_map: Dict[Tuple[int, int], List[Tuple[int, int, int]]],
) -> List[Tuple[int, int]]:
    """Return (face_idx, local_idx) entries ordered CCW around vertex vi.

    Uses edge-face adjacency to walk the fan.  Falls back to unordered if
    walking fails (e.g., at a boundary vertex).
    """
    if len(entries) <= 2:
        return entries

    # Build a map: face_idx -> (local_idx, prev_vert, next_vert) for vertex vi
    # prev_vert = face[(li-1) % n],  next_vert = face[(li+1) % n]
    face_info: Dict[int, Tuple[int, int, int]] = {}
    for fi, li in entries:
        face = mesh.faces[fi]
        n = len(face)
        prev_v = face[(li - 1) % n]
        next_v = face[(li + 1) % n]
        face_info[fi] = (li, prev_v, next_v)

    # Walk: start from entries[0], then follow the fan
    ordered = [entries[0]]
    visited = {entries[0][0]}

    max_iter = len(entries) * 2
    for _ in range(max_iter):
        current_fi, current_li = ordered[-1]
        li, prev_v, next_v = face_info[current_fi]

        # The "next" face in CCW order shares the edge (vi, next_v)
        key = mesh.edge_key(vi, next_v)
        adj = edge_face_map.get(key, [])
        found_next = False
        for adj_fi, adj_li_a, adj_li_b in adj:
            if adj_fi != current_fi and adj_fi not in visited:
                # Check that vi is in this face
                if adj_fi in face_info:
                    ordered.append((adj_fi, face_info[adj_fi][0]))
                    visited.add(adj_fi)
                    found_next = True
                    break

        if not found_next:
            break

    # Append any unordered entries (boundary or valence mismatch)
    for fi, li in entries:
        if fi not in visited:
            ordered.append((fi, li))

    return ordered


# ---------------------------------------------------------------------------
# Public: doo_sabin_subdivide
# ---------------------------------------------------------------------------

def doo_sabin_subdivide(mesh: PolyMesh, levels: int = 1) -> PolyMesh:
    """Apply N levels of Doo-Sabin subdivision.

    Parameters
    ----------
    mesh : PolyMesh
        Input polygon mesh (any polygon type).
    levels : int
        Number of subdivision levels (>= 0).  0 returns a copy.

    Returns
    -------
    PolyMesh — never raises.
    """
    try:
        levels = max(0, int(levels))
        result = PolyMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
        )
        for _ in range(levels):
            result = _doo_sabin_once(result)
        return result
    except Exception:
        return PolyMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
        )


def polymesh_from_arrays(
    vertices: List[List[float]],
    faces: List[List[int]],
) -> PolyMesh:
    """Construct a PolyMesh from raw arrays.

    Returns PolyMesh — never raises.
    """
    try:
        return PolyMesh(
            vertices=[[float(x) for x in v] for v in vertices],
            faces=[[int(i) for i in f] for f in faces],
        )
    except Exception:
        return PolyMesh()


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

    _subd_doo_sabin_spec = ToolSpec(
        name="subd_doo_sabin",
        description=(
            "Apply Doo-Sabin (1978) subdivision to an arbitrary polygon mesh.  "
            "Doo-Sabin is face-based and converges to bi-quadratic B-spline limit "
            "surfaces.  It handles triangles, quads, and n-gons seamlessly — useful "
            "for engineering CAD surfaces starting from imported polygon meshes.\n"
            "\n"
            "Parameters:\n"
            "  vertices : [[x,y,z], ...]\n"
            "  faces    : [[i,j,...], ...] — any polygon size\n"
            "  levels   : int (1..4, default 1)\n"
            "\n"
            "Returns:\n"
            "  ok           : bool\n"
            "  vertices     : [[x,y,z], ...]\n"
            "  faces        : [[i,j,...], ...]\n"
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
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subd_doo_sabin_spec)
    async def run_subd_doo_sabin(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        levels = int(a.get("levels", 1))

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if levels < 0 or levels > 6:
            return err_payload("levels must be 0..6", "BAD_ARGS")

        try:
            mesh = PolyMesh(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid mesh: {exc}", "BAD_ARGS")

        result = doo_sabin_subdivide(mesh, levels=levels)
        return ok_payload({
            "ok": True,
            "vertices": result.vertices,
            "faces": result.faces,
            "num_vertices": result.num_vertices,
            "num_faces": result.num_faces,
        })
