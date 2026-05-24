"""
subd.py
=======
Pure-Python Subdivision Surface (SubD) geometry for Rhino 7+ parity.

This module implements Catmull-Clark subdivision surfaces with crease support,
limit-surface evaluation, authoring primitives, edit operations, and utilities
for converting between SubD and dense quad meshes.

Public API — Math layer
-----------------------
SubDMesh(dataclass)
    Vertices (list of [x,y,z]), quad/poly face index lists, edges with optional
    crease tags [0..1].

catmull_clark_subdivide(mesh, levels=1) -> SubDMesh
    One or N levels of Catmull-Clark subdivision with edge-crease handling and
    vertex classification (smooth / crease / corner).

subd_to_quadmesh(mesh, levels=3) -> SubDMesh
    Dense limit-surface approximation by subdividing N levels.

quad_mesh_to_subd(vertices, faces) -> SubDMesh
    Wrap a raw quad mesh, tagging all boundary edges as fully creased.

subd_limit_position(mesh, vertex_index) -> list[float]
    Closed-form limit position of a vertex using the Catmull-Clark quasi-uniform
    Stam rule (smooth interior valence-n vertex).

extract_isoparametric_polylines(mesh, direction='u', count=10) -> list[list[list[float]]]
    Sample isoparametric polylines from a subdivided mesh.

Public API — Authoring layer (T-105)
-------------------------------------
SubDDoc(dataclass)
    Author-time document: version, control_mesh (SubDMesh), subdivision_level,
    display_mesh (optional subdivided result).

create_subd_cube() -> SubDDoc
    Unit cube SubD primitive centred at origin.

create_subd_cylinder(segments=8) -> SubDDoc
    Cylinder SubD primitive with N side segments and capped ends.

subd_doc_move_vertex(doc, vertex_index, dx, dy, dz) -> SubDDoc
    Translate one control vertex by (dx, dy, dz).  Returns new doc (immutable).

subd_doc_extrude_face(doc, face_index, distance) -> SubDDoc
    Extrude a face along its normal by `distance`.  Returns new doc.

subd_doc_set_edge_crease(doc, v1, v2, value) -> SubDDoc
    Set the crease weight [0,1] on an edge.  Returns new doc.

subd_doc_evaluate(doc, levels=None) -> SubDDoc
    Subdivide the control mesh and store the result as display_mesh.

subd_doc_to_mesh(doc, levels=None) -> dict
    Return {"vertices": [[x,y,z],...], "faces": [[i,j,k,l],...]} of the
    subdivided display mesh.

mesh_to_subd_doc(vertices, faces) -> SubDDoc
    Wrap a raw vertex+face mesh as a SubDDoc (level-0), boundary edges creased.

Never raises — all exceptions are caught and returned as empty / identity results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# SubDMesh dataclass
# ---------------------------------------------------------------------------

@dataclass
class SubDMesh:
    """Subdivision surface control mesh.

    Attributes
    ----------
    vertices : list of [x, y, z]
        Control-point positions.
    faces : list of list[int]
        Each face is an ordered list of vertex indices (quads or n-gons).
    creases : dict mapping (i, j) -> float
        Edge crease values in [0, 1].  Keys are always (min, max) ordered.
        Missing edges have implicit crease 0.0.
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
        # GK-P14: allow fractional sharpness > 1.0 for multi-level decay.
        # Only hard-clamp negative values to 0.0; positive values pass through.
        self.creases[self.edge_key(a, b)] = float(max(0.0, value))

    def _build_adjacency(self) -> Tuple[
        Dict[Tuple[int, int], List[int]],   # edge -> [face_indices]
        Dict[int, List[int]],               # vertex -> [face_indices]
        Dict[int, List[int]],               # vertex -> [neighbor vertex ids]
    ]:
        """Build edge-face, vertex-face, vertex-neighbor adjacency maps."""
        edge_faces: Dict[Tuple[int, int], List[int]] = {}
        vert_faces: Dict[int, List[int]] = {}
        vert_neighbors: Dict[int, List[int]] = {}

        for fi, face in enumerate(self.faces):
            n = len(face)
            for vi in face:
                vert_faces.setdefault(vi, []).append(fi)
            for i in range(n):
                a = face[i]
                b = face[(i + 1) % n]
                key = self.edge_key(a, b)
                edge_faces.setdefault(key, []).append(fi)
                if b not in vert_neighbors.get(a, []):
                    vert_neighbors.setdefault(a, []).append(b)
                if a not in vert_neighbors.get(b, []):
                    vert_neighbors.setdefault(b, []).append(a)

        return edge_faces, vert_faces, vert_neighbors

    def _all_edge_keys(self) -> List[Tuple[int, int]]:
        seen = set()
        result = []
        for face in self.faces:
            n = len(face)
            for i in range(n):
                key = self.edge_key(face[i], face[(i + 1) % n])
                if key not in seen:
                    seen.add(key)
                    result.append(key)
        return result


# ---------------------------------------------------------------------------
# Helper: centroid of a list of 3D points
# ---------------------------------------------------------------------------

def _centroid(pts: List[List[float]]) -> List[float]:
    n = len(pts)
    if n == 0:
        return [0.0, 0.0, 0.0]
    x = sum(p[0] for p in pts) / n
    y = sum(p[1] for p in pts) / n
    z = sum(p[2] for p in pts) / n
    return [x, y, z]


def _midpoint(a: List[float], b: List[float]) -> List[float]:
    return [(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0]


def _lerp3(a: List[float], b: List[float], t: float) -> List[float]:
    return [
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
        a[2] + (b[2] - a[2]) * t,
    ]


def _add3(a: List[float], b: List[float]) -> List[float]:
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _scale3(v: List[float], s: float) -> List[float]:
    return [v[0] * s, v[1] * s, v[2] * s]


# ---------------------------------------------------------------------------
# One level of Catmull-Clark subdivision
# ---------------------------------------------------------------------------

def _catmull_clark_once(mesh: SubDMesh) -> SubDMesh:
    """Apply one level of Catmull-Clark subdivision.

    Algorithm:
      1. Face points: centroid of each face's control vertices.
      2. Edge points: for interior smooth edges, average of (two face-point
         centroids) and (two edge endpoints), optionally blended toward simple
         midpoint by the crease value.  Boundary / fully-creased edges use the
         midpoint.
      3. Vertex points: Catmull-Clark rule based on valence and vertex class
         (smooth interior, crease, corner).
      4. Assemble new quads: each original n-face produces n new quads.
    """
    try:
        verts = mesh.vertices
        faces = mesh.faces
        edge_faces, vert_faces, vert_neighbors = mesh._build_adjacency()
        all_edges = mesh._all_edge_keys()

        nv = len(verts)

        # ------------------------------------------------------------------
        # 1. Face points
        # ------------------------------------------------------------------
        face_pts: List[List[float]] = []
        for face in faces:
            fp = _centroid([verts[i] for i in face])
            face_pts.append(fp)

        # New vertex indices:
        #   0 .. nv-1            : updated original vertices (assigned last)
        #   nv .. nv+nf-1        : face points
        #   nv+nf .. nv+nf+ne-1  : edge points
        nf = len(faces)

        # Map edge key -> index in new vertex array
        edge_index: Dict[Tuple[int, int], int] = {}
        edge_pts: List[List[float]] = []

        # ------------------------------------------------------------------
        # 2. Edge points
        # ------------------------------------------------------------------
        for ei, key in enumerate(all_edges):
            edge_index[key] = nv + nf + ei
            a, b = key
            va, vb = verts[a], verts[b]
            mid = _midpoint(va, vb)
            crease = mesh.get_crease(a, b)
            adj_faces = edge_faces.get(key, [])

            if len(adj_faces) != 2:
                # Boundary edge: always use midpoint
                ep = mid
            elif crease >= 1.0:
                # GK-P14: fully-creased edge (sharpness >= 1.0): use midpoint;
                # sharpness for child edges will be crease - 1.0 (decay below).
                ep = mid
            elif crease > 0.0:
                # GK-P14: fractional crease 0 < s < 1: blend smooth ↔ crease
                # (OpenSubdiv: blend = s; s=0 → smooth, s→1 → crease midpoint)
                fp1 = face_pts[adj_faces[0]]
                fp2 = face_pts[adj_faces[1]]
                face_avg = _centroid([fp1, fp2])
                smooth = _scale3(
                    _add3(_add3(va, vb), _scale3(face_avg, 2.0)),
                    0.25,
                )
                ep = _lerp3(smooth, mid, crease)
            else:
                fp1 = face_pts[adj_faces[0]]
                fp2 = face_pts[adj_faces[1]]
                face_avg = _centroid([fp1, fp2])
                ep = _scale3(
                    _add3(_add3(va, vb), _scale3(face_avg, 2.0)),
                    0.25,
                )

            edge_pts.append(ep)

        # ------------------------------------------------------------------
        # 3. Updated (original) vertex positions
        # ------------------------------------------------------------------
        new_orig_verts: List[List[float]] = []
        for vi, v in enumerate(verts):
            adj_face_idxs = vert_faces.get(vi, [])
            adj_nbrs = vert_neighbors.get(vi, [])
            valence = len(adj_face_idxs)

            # Count crease edges incident to this vertex.
            # GK-P14: edges with sharpness >= 1.0 are "hard crease" for
            # vertex classification; fractional (0 < s < 1) edges are
            # partially creased — treated as smooth for corner counting but
            # their fractional influence is blended below.
            crease_nbrs = [nb for nb in adj_nbrs if mesh.get_crease(vi, nb) >= 1.0]
            num_creases = len(crease_nbrs)

            # For fractional (0 < s < 1) creased edges, compute per-vertex
            # blend weight: max fractional sharpness of incident edges in (0,1).
            frac_crease_s = max(
                (mesh.get_crease(vi, nb) for nb in adj_nbrs
                 if 0.0 < mesh.get_crease(vi, nb) < 1.0),
                default=0.0,
            )

            if num_creases >= 2 or valence == 0:
                # Corner vertex: stays put
                new_orig_verts.append(list(v))
            elif num_creases == 1 or len(adj_face_idxs) < len(adj_nbrs):
                # Crease / boundary vertex: use crease rule
                # Weighted average of vertex and midpoints to crease neighbours
                if adj_nbrs:
                    mids = [_midpoint(v, verts[nb]) for nb in adj_nbrs]
                    avg_mid = _centroid(mids)
                    new_pos = _add3(
                        _scale3(v, 6.0 / 8.0),
                        _scale3(avg_mid, 2.0 / 8.0),
                    )
                else:
                    new_pos = list(v)
                new_orig_verts.append(new_pos)
            else:
                # Smooth interior: standard Catmull-Clark
                n = valence
                if n < 1:
                    new_orig_verts.append(list(v))
                    continue
                F = _centroid([face_pts[fi] for fi in adj_face_idxs])
                mids = [_midpoint(v, verts[nb]) for nb in adj_nbrs]
                R = _centroid(mids)
                # (F + 2R + (n-3)P) / n
                smooth_pos = _scale3(
                    _add3(
                        _add3(F, _scale3(R, 2.0)),
                        _scale3(v, float(n - 3)),
                    ),
                    1.0 / n,
                )
                # GK-P14: if there are fractional-crease edges (0 < s < 1),
                # blend between smooth and crease-vertex rule.
                if frac_crease_s > 0.0:
                    avg_mid = _centroid(mids)
                    crease_pos = _add3(
                        _scale3(v, 6.0 / 8.0),
                        _scale3(avg_mid, 2.0 / 8.0),
                    )
                    new_pos = _lerp3(smooth_pos, crease_pos, frac_crease_s)
                else:
                    new_pos = smooth_pos
                new_orig_verts.append(new_pos)

        # ------------------------------------------------------------------
        # 4. Assemble new vertex list and faces
        # ------------------------------------------------------------------
        # Layout: [orig_0..orig_{nv-1}, face_0..face_{nf-1}, edge_0..edge_{ne-1}]
        new_verts = new_orig_verts + face_pts + edge_pts

        new_faces: List[List[int]] = []
        for fi, face in enumerate(faces):
            face_pt_idx = nv + fi
            n = len(face)
            for i in range(n):
                va_orig = face[i]
                vb_orig = face[(i + 1) % n]
                vc_orig = face[(i - 1) % n]
                ep_ab = edge_index[mesh.edge_key(va_orig, vb_orig)]
                ep_ca = edge_index[mesh.edge_key(vc_orig, va_orig)]
                new_faces.append([va_orig, ep_ab, face_pt_idx, ep_ca])

        # ------------------------------------------------------------------
        # 5. Propagate creases — GK-P14: OpenSubdiv fractional-decay rule.
        #
        #    sharpness s at level k decays to max(0, s - 1) at level k+1.
        #    Fractional residual frac = s - floor(s) in (0, 1) on the last
        #    "semi-sharp" level; the child edges get sharpness frac so the
        #    blend with the smooth rule carries the correct weight next level.
        #    Fully-sharp edges (s >= 1) produce child sharpness s - 1.
        #    Fully-smooth edges (s == 0) produce no crease entry.
        # ------------------------------------------------------------------
        new_creases: Dict[Tuple[int, int], float] = {}
        for key in all_edges:
            c = mesh.get_crease(key[0], key[1])
            if c <= 0.0:
                continue
            a, b = key
            ep_idx = edge_index[key]
            # OpenSubdiv decay: sharpness decreases by 1.0 per subdivision level
            new_c = max(0.0, c - 1.0)
            if new_c > 0.0:
                new_key_a = (min(a, ep_idx), max(a, ep_idx))
                new_key_b = (min(b, ep_idx), max(b, ep_idx))
                new_creases[new_key_a] = new_c
                new_creases[new_key_b] = new_c

        result = SubDMesh(
            vertices=new_verts,
            faces=new_faces,
            creases=new_creases,
        )
        return result
    except Exception:
        return SubDMesh(vertices=list(mesh.vertices), faces=list(mesh.faces), creases=dict(mesh.creases))


# ---------------------------------------------------------------------------
# Public: catmull_clark_subdivide
# ---------------------------------------------------------------------------

def catmull_clark_subdivide(mesh: SubDMesh, levels: int = 1) -> SubDMesh:
    """Apply N levels of Catmull-Clark subdivision.

    Parameters
    ----------
    mesh : SubDMesh
        Input control mesh.
    levels : int
        Number of subdivision levels (>= 0).  0 returns a copy.

    Returns
    -------
    SubDMesh
        Subdivided mesh.  Never raises.
    """
    try:
        levels = max(0, int(levels))
        result = SubDMesh(
            vertices=[list(v) for v in mesh.vertices],
            faces=[list(f) for f in mesh.faces],
            creases=dict(mesh.creases),
        )
        for _ in range(levels):
            result = _catmull_clark_once(result)
        return result
    except Exception:
        return SubDMesh(vertices=list(mesh.vertices), faces=list(mesh.faces), creases=dict(mesh.creases))


# ---------------------------------------------------------------------------
# Public: subd_to_quadmesh
# ---------------------------------------------------------------------------

def subd_to_quadmesh(mesh: SubDMesh, levels: int = 3) -> SubDMesh:
    """Dense limit-surface approximation via subdivision.

    Subdivides the mesh N levels to produce a dense quad mesh that
    approximates the smooth limit surface.

    Parameters
    ----------
    mesh : SubDMesh
    levels : int
        Number of subdivision levels (default 3).

    Returns
    -------
    SubDMesh
        Dense quad mesh (creases dictionary will be sparse / empty for
        fully converged internal edges).  Never raises.
    """
    return catmull_clark_subdivide(mesh, levels=max(1, levels))


# ---------------------------------------------------------------------------
# Public: quad_mesh_to_subd
# ---------------------------------------------------------------------------

def quad_mesh_to_subd(
    vertices: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
) -> SubDMesh:
    """Wrap a raw quad mesh as a SubDMesh, tagging boundary edges as creased.

    Boundary edges (those shared by only one face) are assigned crease=1.0.

    Parameters
    ----------
    vertices : sequence of [x, y, z]
    faces : sequence of vertex-index lists

    Returns
    -------
    SubDMesh
        Never raises.
    """
    try:
        verts = [list(map(float, v)) for v in vertices]
        face_list = [list(map(int, f)) for f in faces]
        mesh = SubDMesh(vertices=verts, faces=face_list)

        # Find boundary edges
        edge_face_count: Dict[Tuple[int, int], int] = {}
        for face in face_list:
            n = len(face)
            for i in range(n):
                key = mesh.edge_key(face[i], face[(i + 1) % n])
                edge_face_count[key] = edge_face_count.get(key, 0) + 1

        for key, cnt in edge_face_count.items():
            if cnt == 1:
                mesh.creases[key] = 1.0

        return mesh
    except Exception:
        return SubDMesh()


# ---------------------------------------------------------------------------
# Public: subd_limit_position
# ---------------------------------------------------------------------------

def subd_limit_position(mesh: SubDMesh, vertex_index: int) -> List[float]:
    """Closed-form limit position for a smooth interior vertex.

    Uses the Catmull-Clark quasi-uniform Stam limit rule:
        P_lim = (n^2 * P + 4 * sum(R_i) + sum(F_i)) / (n^2 + 5n)
    where n = valence (number of adjacent faces), R_i are edge midpoints,
    and F_i are face centroids of adjacent faces.

    For boundary / crease / corner vertices, returns the vertex position
    itself (limit == control point for corners under C-C).

    Parameters
    ----------
    mesh : SubDMesh
    vertex_index : int

    Returns
    -------
    [x, y, z]  — limit position, never raises.
    """
    try:
        vi = int(vertex_index)
        if vi < 0 or vi >= len(mesh.vertices):
            return [0.0, 0.0, 0.0]

        v = mesh.vertices[vi]
        edge_faces, vert_faces, vert_neighbors = mesh._build_adjacency()

        adj_face_idxs = vert_faces.get(vi, [])
        adj_nbrs = vert_neighbors.get(vi, [])
        n = len(adj_face_idxs)

        crease_nbrs = [nb for nb in adj_nbrs if mesh.get_crease(vi, nb) >= 1.0]
        num_creases = len(crease_nbrs)

        if n == 0 or num_creases >= 2:
            # Corner or isolated: limit == control position
            return list(v)

        if num_creases == 1 or len(adj_face_idxs) < len(adj_nbrs):
            # Crease vertex: limit is on the crease curve
            return list(v)

        # Smooth interior: Stam limit rule
        # P_lim = (n^2 * P + 4 * sum(midpoints) + sum(face_centroids)) / (n^2 + 5n)
        sum_R = _centroid([_midpoint(v, mesh.vertices[nb]) for nb in adj_nbrs])
        sum_F = _centroid([_centroid([mesh.vertices[i] for i in mesh.faces[fi]]) for fi in adj_face_idxs])

        denom = n * n + 5.0 * n
        if abs(denom) < 1e-15:
            return list(v)

        lim = _scale3(
            _add3(
                _add3(_scale3(v, float(n * n)), _scale3(sum_R, 4.0 * n)),
                _scale3(sum_F, float(n)),
            ),
            1.0 / denom,
        )
        return lim
    except Exception:
        if 0 <= vertex_index < len(mesh.vertices):
            return list(mesh.vertices[vertex_index])
        return [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# Public: extract_isoparametric_polylines
# ---------------------------------------------------------------------------

def extract_isoparametric_polylines(
    mesh: SubDMesh,
    direction: str = "u",
    count: int = 10,
) -> List[List[List[float]]]:
    """Sample isoparametric polylines from a quad mesh.

    Traces edge-connected paths across the mesh in either the U (horizontal)
    or V (vertical) direction for quad faces.  Polylines are extracted by
    walking adjacent quads sharing an edge in the given direction.

    Parameters
    ----------
    mesh : SubDMesh
        Should be a (subdivided) quad mesh.
    direction : 'u' or 'v'
        Direction of polylines.
    count : int
        Number of evenly-spaced polylines to sample along the orthogonal
        direction.  Actual count may be less for small meshes.

    Returns
    -------
    list of polylines, each polyline a list of [x, y, z] points.
    Never raises.
    """
    try:
        if not mesh.vertices or not mesh.faces:
            return []
        direction = direction.lower().strip()
        if direction not in ("u", "v"):
            direction = "u"

        count = max(1, int(count))

        # For each quad face extract the two midpoints along the chosen direction
        # direction 'u': connect midpoints of edges 0-1 and 2-3 (horizontal)
        # direction 'v': connect midpoints of edges 1-2 and 3-0 (vertical)
        polylines: List[List[List[float]]] = []

        # Walk connectivity: build face adjacency via shared edges
        edge_faces, vert_faces, vert_neighbors = mesh._build_adjacency()

        # For each quad face, produce a 2-point segment at its midline,
        # then group into chains via shared edge traversal.
        # Simplified: sample from face centroids and midpoints of edges.

        # Collect face midpoints along the direction, then cluster by
        # approximate position along the orthogonal axis.
        face_segments: List[Tuple[List[float], List[float]]] = []
        for face in mesh.faces:
            if len(face) != 4:
                continue
            v0, v1, v2, v3 = [mesh.vertices[i] for i in face]
            if direction == "u":
                p0 = _midpoint(v0, v3)  # midpoint of edge v0-v3
                p1 = _midpoint(v1, v2)  # midpoint of edge v1-v2
            else:
                p0 = _midpoint(v0, v1)  # midpoint of edge v0-v1
                p1 = _midpoint(v3, v2)  # midpoint of edge v3-v2
            face_segments.append((p0, p1))

        if not face_segments:
            return []

        # Evenly sample `count` polylines by partitioning segments into groups
        # based on their centroid coordinate along the orthogonal axis.
        ortho_idx = 1 if direction == "u" else 0  # orthogonal axis index

        def seg_ortho(seg: Tuple[List[float], List[float]]) -> float:
            return (seg[0][ortho_idx] + seg[1][ortho_idx]) / 2.0

        sorted_segs = sorted(face_segments, key=seg_ortho)
        n_segs = len(sorted_segs)
        if n_segs == 0:
            return []

        # Partition into `count` buckets
        bucket_size = max(1, n_segs // count)
        for bi in range(count):
            start = bi * bucket_size
            end = start + bucket_size if bi < count - 1 else n_segs
            bucket = sorted_segs[start:end]
            if not bucket:
                continue
            # Sort bucket by position along the direction axis
            dir_idx = 0 if direction == "u" else 1

            def seg_dir(seg: Tuple[List[float], List[float]]) -> float:
                return (seg[0][dir_idx] + seg[1][dir_idx]) / 2.0

            bucket.sort(key=seg_dir)
            pts: List[List[float]] = []
            for seg in bucket:
                pts.append(list(seg[0]))
                pts.append(list(seg[1]))
            if pts:
                polylines.append(pts)

        return polylines
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Authoring layer (T-105) — SubDDoc + edit operations
# ---------------------------------------------------------------------------

@dataclass
class SubDDoc:
    """Author-time SubD document.

    Attributes
    ----------
    version : int
        Document version (always 1).
    control_mesh : SubDMesh
        The editable control cage.
    subdivision_level : int
        Default number of CC levels used when evaluating.
    display_mesh : Optional[SubDMesh]
        Populated by :func:`subd_doc_evaluate`; None until evaluated.
    """
    version: int = 1
    control_mesh: SubDMesh = field(default_factory=SubDMesh)
    subdivision_level: int = 2
    display_mesh: Optional["SubDMesh"] = None

    def _copy(self) -> "SubDDoc":
        """Return a deep copy of this document."""
        import copy as _copy_mod
        return _copy_mod.deepcopy(self)


def create_subd_cube() -> SubDDoc:
    """Create a unit-cube SubD primitive centred at the origin.

    Returns a :class:`SubDDoc` with 8 control vertices and 6 quad faces.
    No creases are set (all edges smooth).
    """
    try:
        verts = [
            [-1.0, -1.0, -1.0],  # 0
            [ 1.0, -1.0, -1.0],  # 1
            [ 1.0,  1.0, -1.0],  # 2
            [-1.0,  1.0, -1.0],  # 3
            [-1.0, -1.0,  1.0],  # 4
            [ 1.0, -1.0,  1.0],  # 5
            [ 1.0,  1.0,  1.0],  # 6
            [-1.0,  1.0,  1.0],  # 7
        ]
        faces = [
            [0, 1, 2, 3],  # bottom z=-1
            [4, 5, 6, 7],  # top    z=+1
            [0, 1, 5, 4],  # front  y=-1
            [2, 3, 7, 6],  # back   y=+1
            [0, 3, 7, 4],  # left   x=-1
            [1, 2, 6, 5],  # right  x=+1
        ]
        mesh = SubDMesh(vertices=verts, faces=faces)
        return SubDDoc(control_mesh=mesh)
    except Exception:
        return SubDDoc()


def create_subd_cylinder(segments: int = 8) -> SubDDoc:
    """Create a cylinder SubD primitive.

    Parameters
    ----------
    segments : int
        Number of side segments around the circumference (default 8).
        At least 3 segments are used.

    Returns
    -------
    SubDDoc
        Control cage with 2×segments vertices, `segments` side quad faces,
        and 2 cap faces (n-gons).  Bottom/top rim edges are fully creased
        so the cylinder shape is preserved.
    """
    try:
        segments = max(3, int(segments))
        import math as _math

        verts: List[List[float]] = []
        bottom_ids: List[int] = []
        top_ids: List[int] = []

        for s in range(segments):
            theta = 2.0 * _math.pi * s / segments
            x = _math.cos(theta)
            y = _math.sin(theta)
            verts.append([x, y, -1.0])
            bottom_ids.append(len(verts) - 1)
            verts.append([x, y,  1.0])
            top_ids.append(len(verts) - 1)

        faces: List[List[int]] = []
        # Side quads
        for s in range(segments):
            ns = (s + 1) % segments
            a = bottom_ids[s]
            b = bottom_ids[ns]
            c = top_ids[ns]
            d = top_ids[s]
            faces.append([a, b, c, d])

        # Cap n-gons (bottom reversed for outward normal)
        faces.append(list(reversed(bottom_ids)))
        faces.append(list(top_ids))

        mesh = SubDMesh(vertices=verts, faces=faces)

        # Crease top and bottom rim edges so caps stay flat
        for s in range(segments):
            ns = (s + 1) % segments
            mesh.set_crease(bottom_ids[s], bottom_ids[ns], 1.0)
            mesh.set_crease(top_ids[s], top_ids[ns], 1.0)

        return SubDDoc(control_mesh=mesh)
    except Exception:
        return SubDDoc()


def subd_doc_move_vertex(
    doc: SubDDoc,
    vertex_index: int,
    dx: float,
    dy: float,
    dz: float,
) -> SubDDoc:
    """Translate a single control vertex and invalidate the display mesh.

    Parameters
    ----------
    doc : SubDDoc
    vertex_index : int
        0-based index of the vertex to move.
    dx, dy, dz : float
        Translation delta.

    Returns
    -------
    SubDDoc — new document (input is not mutated).  Never raises.
    """
    try:
        new_doc = doc._copy()
        new_doc.display_mesh = None  # invalidate
        vi = int(vertex_index)
        verts = new_doc.control_mesh.vertices
        if 0 <= vi < len(verts):
            verts[vi] = [
                verts[vi][0] + float(dx),
                verts[vi][1] + float(dy),
                verts[vi][2] + float(dz),
            ]
        return new_doc
    except Exception:
        return doc._copy()


def subd_doc_extrude_face(
    doc: SubDDoc,
    face_index: int,
    distance: float,
) -> SubDDoc:
    """Extrude a face along its normal by `distance`.

    Creates new vertices at the extruded position, replaces the original face
    with the new top face, and adds side quad faces.  Invalidates display_mesh.

    Parameters
    ----------
    doc : SubDDoc
    face_index : int
        0-based index of the face to extrude.
    distance : float
        Extrusion length (can be negative to extrude inward).

    Returns
    -------
    SubDDoc — new document.  Never raises.
    """
    try:
        new_doc = doc._copy()
        new_doc.display_mesh = None
        mesh = new_doc.control_mesh

        if face_index < 0 or face_index >= len(mesh.faces):
            return new_doc

        face = mesh.faces[face_index]
        verts = mesh.vertices

        # Newell normal for the face
        nx = ny = nz = 0.0
        n = len(face)
        for i in range(n):
            curr = verts[face[i]]
            nxt = verts[face[(i + 1) % n]]
            nx += (curr[1] - nxt[1]) * (curr[2] + nxt[2])
            ny += (curr[2] - nxt[2]) * (curr[0] + nxt[0])
            nz += (curr[0] - nxt[0]) * (curr[1] + nxt[1])
        length = (nx * nx + ny * ny + nz * nz) ** 0.5 or 1.0
        nx /= length
        ny /= length
        nz /= length

        dist = float(distance)
        # New top vertices
        new_top_ids: List[int] = []
        for vid in face:
            v = verts[vid]
            new_vid = len(verts)
            verts.append([v[0] + nx * dist, v[1] + ny * dist, v[2] + nz * dist])
            new_top_ids.append(new_vid)

        # Replace original face with top face
        mesh.faces[face_index] = list(new_top_ids)

        # Add side quads
        for i in range(n):
            ni = (i + 1) % n
            a = face[i]
            b = face[ni]
            ta = new_top_ids[i]
            tb = new_top_ids[ni]
            mesh.faces.append([a, b, tb, ta])

        return new_doc
    except Exception:
        return doc._copy()


def subd_doc_set_edge_crease(
    doc: SubDDoc,
    v1: int,
    v2: int,
    value: float,
) -> SubDDoc:
    """Set (or update) the crease weight on an edge.

    Parameters
    ----------
    doc : SubDDoc
    v1, v2 : int
        Vertex indices of the edge endpoints.
    value : float
        Crease weight in [0, 1].  0 = smooth, 1 = fully creased.

    Returns
    -------
    SubDDoc — new document with crease applied.  Never raises.
    """
    try:
        new_doc = doc._copy()
        new_doc.display_mesh = None
        new_doc.control_mesh.set_crease(int(v1), int(v2), float(value))
        return new_doc
    except Exception:
        return doc._copy()


def subd_doc_evaluate(doc: SubDDoc, levels: Optional[int] = None) -> SubDDoc:
    """Subdivide the control mesh and attach the result as display_mesh.

    Parameters
    ----------
    doc : SubDDoc
    levels : int or None
        Override subdivision level.  If None, uses doc.subdivision_level.

    Returns
    -------
    SubDDoc with display_mesh populated.  Never raises.
    """
    try:
        new_doc = doc._copy()
        n = int(levels) if levels is not None else int(new_doc.subdivision_level)
        n = max(0, n)
        new_doc.display_mesh = catmull_clark_subdivide(new_doc.control_mesh, levels=n)
        return new_doc
    except Exception:
        return doc._copy()


def subd_doc_to_mesh(
    doc: SubDDoc,
    levels: Optional[int] = None,
) -> Dict[str, object]:
    """Evaluate and return the display mesh as a plain dict.

    Returns
    -------
    dict with keys:
        "vertices" : list of [x, y, z]
        "faces"    : list of vertex-index lists
    Never raises.
    """
    try:
        evaluated = subd_doc_evaluate(doc, levels=levels)
        dm = evaluated.display_mesh
        if dm is None:
            return {"vertices": [], "faces": []}
        return {"vertices": dm.vertices, "faces": dm.faces}
    except Exception:
        return {"vertices": [], "faces": []}


def mesh_to_subd_doc(
    vertices: Sequence[Sequence[float]],
    faces: Sequence[Sequence[int]],
) -> SubDDoc:
    """Wrap a raw mesh as a level-0 SubDDoc, boundary edges fully creased.

    Parameters
    ----------
    vertices : sequence of [x, y, z]
    faces : sequence of vertex-index lists

    Returns
    -------
    SubDDoc — never raises.
    """
    try:
        mesh = quad_mesh_to_subd(vertices, faces)
        return SubDDoc(control_mesh=mesh, subdivision_level=0)
    except Exception:
        return SubDDoc()


# ---------------------------------------------------------------------------
# LLM tool registration (gated — mirrors trim_curve.py pattern)
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

    # ------------------------------------------------------------------
    # query_subd_limit
    # ------------------------------------------------------------------

    _query_subd_limit_spec = ToolSpec(
        name="query_subd_limit",
        description=(
            "Evaluate the Catmull-Clark limit position of one or more control "
            "vertices on a SubD mesh.  Pass the control-mesh vertices and faces, "
            "and a list of vertex indices to query.  Returns limit positions.\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  limit_positions : list of [x,y,z] (one per queried vertex)\n"
            "\n"
            "Errors: {ok:false, reason} for invalid inputs.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Control-mesh vertices as [[x,y,z], ...].",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Face vertex-index lists as [[i,j,k,l], ...].",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "vertex_indices": {
                    "type": "array",
                    "description": "Indices of vertices to query.",
                    "items": {"type": "integer"},
                },
                "creases": {
                    "type": "array",
                    "description": "Optional list of crease entries {v1, v2, value}.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "v1": {"type": "integer"},
                            "v2": {"type": "integer"},
                            "value": {"type": "number"},
                        },
                        "required": ["v1", "v2", "value"],
                    },
                },
            },
            "required": ["vertices", "faces", "vertex_indices"],
        },
    )

    @register(_query_subd_limit_spec)
    async def run_query_subd_limit(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        query_idxs = a.get("vertex_indices", [])
        raw_creases = a.get("creases", [])

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if not query_idxs:
            return err_payload("vertex_indices is required", "BAD_ARGS")

        try:
            mesh = SubDMesh(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid mesh: {exc}", "BAD_ARGS")

        for crease_entry in raw_creases:
            try:
                mesh.set_crease(
                    int(crease_entry["v1"]),
                    int(crease_entry["v2"]),
                    float(crease_entry["value"]),
                )
            except Exception:
                pass

        results = []
        for vi in query_idxs:
            try:
                results.append(subd_limit_position(mesh, int(vi)))
            except Exception:
                results.append([0.0, 0.0, 0.0])

        return ok_payload({"ok": True, "limit_positions": results})

    # ------------------------------------------------------------------
    # subdivide_subd_mesh
    # ------------------------------------------------------------------

    _subdivide_subd_mesh_spec = ToolSpec(
        name="subdivide_subd_mesh",
        description=(
            "Apply N levels of Catmull-Clark subdivision to a control mesh and "
            "return the resulting dense quad mesh (vertices + faces).  Crease "
            "edges are preserved.  Use this to preview the smooth limit surface "
            "before sending to the renderer.\n"
            "\n"
            "Returns:\n"
            "  ok       : bool\n"
            "  vertices : list of [x,y,z]\n"
            "  faces    : list of vertex-index lists\n"
            "  num_vertices : int\n"
            "  num_faces    : int\n"
            "\n"
            "Errors: {ok:false, reason} for invalid inputs.  Never raises."
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
                    "description": "Subdivision levels (1..4).  Default 2.",
                },
                "creases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "v1": {"type": "integer"},
                            "v2": {"type": "integer"},
                            "value": {"type": "number"},
                        },
                        "required": ["v1", "v2", "value"],
                    },
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_subdivide_subd_mesh_spec)
    async def run_subdivide_subd_mesh(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        levels = int(a.get("levels", 2))
        raw_creases = a.get("creases", [])

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if levels < 0 or levels > 6:
            return err_payload("levels must be 0..6", "BAD_ARGS")

        try:
            mesh = SubDMesh(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid mesh: {exc}", "BAD_ARGS")

        for crease_entry in raw_creases:
            try:
                mesh.set_crease(
                    int(crease_entry["v1"]),
                    int(crease_entry["v2"]),
                    float(crease_entry["value"]),
                )
            except Exception:
                pass

        result = catmull_clark_subdivide(mesh, levels=levels)
        return ok_payload({
            "ok": True,
            "vertices": result.vertices,
            "faces": result.faces,
            "num_vertices": result.num_vertices,
            "num_faces": result.num_faces,
        })

    # ------------------------------------------------------------------
    # create_subd_primitive  (T-105 authoring)
    # ------------------------------------------------------------------

    _create_subd_primitive_spec = ToolSpec(
        name="create_subd_primitive",
        description=(
            "Create a SubD control mesh from a named primitive and return it "
            "ready for editing.  Supported primitives: 'cube', 'cylinder'.\n"
            "\n"
            "Returns:\n"
            "  ok               : bool\n"
            "  vertices         : [[x,y,z], ...]\n"
            "  faces            : [[i,j,...], ...]\n"
            "  creases          : [{v1,v2,value}, ...]\n"
            "  subdivision_level: int\n"
            "  num_vertices     : int\n"
            "  num_faces        : int\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "primitive": {
                    "type": "string",
                    "description": "'cube' or 'cylinder'.",
                },
                "segments": {
                    "type": "integer",
                    "description": "Segments for cylinder (default 8, min 3).",
                },
                "subdivision_level": {
                    "type": "integer",
                    "description": "Default evaluation level (default 2).",
                },
            },
            "required": ["primitive"],
        },
    )

    @register(_create_subd_primitive_spec)
    async def run_create_subd_primitive(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        primitive = str(a.get("primitive", "")).strip().lower()
        segments = int(a.get("segments", 8))
        subdiv_level = int(a.get("subdivision_level", 2))

        if primitive == "cube":
            doc = create_subd_cube()
        elif primitive == "cylinder":
            doc = create_subd_cylinder(segments=segments)
        else:
            return err_payload(f"unknown primitive '{primitive}'; use 'cube' or 'cylinder'", "BAD_ARGS")

        doc.subdivision_level = max(0, subdiv_level)
        mesh = doc.control_mesh
        creases_out = [
            {"v1": k[0], "v2": k[1], "value": v}
            for k, v in mesh.creases.items()
        ]
        return ok_payload({
            "ok": True,
            "vertices": mesh.vertices,
            "faces": mesh.faces,
            "creases": creases_out,
            "subdivision_level": doc.subdivision_level,
            "num_vertices": mesh.num_vertices,
            "num_faces": mesh.num_faces,
        })

    # ------------------------------------------------------------------
    # edit_subd_doc  (T-105 authoring — move_vertex / extrude_face / set_crease)
    # ------------------------------------------------------------------

    _edit_subd_doc_spec = ToolSpec(
        name="edit_subd_doc",
        description=(
            "Apply one authoring edit operation to a SubD control mesh.\n"
            "\n"
            "ops:\n"
            "  move_vertex   : {vertex_index, dx, dy, dz}\n"
            "  extrude_face  : {face_index, distance}\n"
            "  set_crease    : {v1, v2, value}  — value in [0,1]\n"
            "\n"
            "Returns:\n"
            "  ok       : bool\n"
            "  vertices : updated control-mesh vertices\n"
            "  faces    : updated control-mesh faces\n"
            "  creases  : [{v1,v2,value}, ...]\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "vertices": {
                    "type": "array",
                    "description": "Current control-mesh vertices.",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "faces": {
                    "type": "array",
                    "description": "Current control-mesh faces.",
                    "items": {"type": "array", "items": {"type": "integer"}},
                },
                "creases": {
                    "type": "array",
                    "description": "Current crease list [{v1,v2,value}].",
                    "items": {
                        "type": "object",
                        "properties": {
                            "v1": {"type": "integer"},
                            "v2": {"type": "integer"},
                            "value": {"type": "number"},
                        },
                        "required": ["v1", "v2", "value"],
                    },
                },
                "op": {
                    "type": "string",
                    "description": "Operation: 'move_vertex', 'extrude_face', or 'set_crease'.",
                },
                "params": {
                    "type": "object",
                    "description": "Operation parameters (see op descriptions above).",
                },
            },
            "required": ["vertices", "faces", "op", "params"],
        },
    )

    @register(_edit_subd_doc_spec)
    async def run_edit_subd_doc(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])
        op = str(a.get("op", "")).strip()
        params = a.get("params", {})

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if op not in ("move_vertex", "extrude_face", "set_crease"):
            return err_payload(f"unknown op '{op}'", "BAD_ARGS")

        try:
            mesh = SubDMesh(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid mesh: {exc}", "BAD_ARGS")

        for ce in raw_creases:
            try:
                mesh.set_crease(int(ce["v1"]), int(ce["v2"]), float(ce["value"]))
            except Exception:
                pass

        doc = SubDDoc(control_mesh=mesh)

        try:
            if op == "move_vertex":
                doc = subd_doc_move_vertex(
                    doc,
                    int(params.get("vertex_index", 0)),
                    float(params.get("dx", 0)),
                    float(params.get("dy", 0)),
                    float(params.get("dz", 0)),
                )
            elif op == "extrude_face":
                doc = subd_doc_extrude_face(
                    doc,
                    int(params.get("face_index", 0)),
                    float(params.get("distance", 1.0)),
                )
            elif op == "set_crease":
                doc = subd_doc_set_edge_crease(
                    doc,
                    int(params.get("v1", 0)),
                    int(params.get("v2", 1)),
                    float(params.get("value", 1.0)),
                )
        except Exception as exc:
            return err_payload(f"op failed: {exc}", "OP_ERROR")

        out_mesh = doc.control_mesh
        creases_out = [
            {"v1": k[0], "v2": k[1], "value": v}
            for k, v in out_mesh.creases.items()
        ]
        return ok_payload({
            "ok": True,
            "vertices": out_mesh.vertices,
            "faces": out_mesh.faces,
            "creases": creases_out,
            "num_vertices": out_mesh.num_vertices,
            "num_faces": out_mesh.num_faces,
        })

    # ------------------------------------------------------------------
    # evaluate_subd_doc  (T-105 authoring — create-edit-evaluate dispatch)
    # ------------------------------------------------------------------

    _evaluate_subd_doc_spec = ToolSpec(
        name="evaluate_subd_doc",
        description=(
            "Subdivide a SubD control mesh and return the smooth display mesh.\n"
            "This completes the create→edit→evaluate round-trip.\n"
            "\n"
            "Returns:\n"
            "  ok           : bool\n"
            "  vertices     : [[x,y,z], ...] — subdivided mesh\n"
            "  faces        : [[i,j,k,l], ...]\n"
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
                "creases": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "v1": {"type": "integer"},
                            "v2": {"type": "integer"},
                            "value": {"type": "number"},
                        },
                        "required": ["v1", "v2", "value"],
                    },
                },
                "levels": {
                    "type": "integer",
                    "description": "Subdivision levels (0..6, default 2).",
                },
            },
            "required": ["vertices", "faces"],
        },
    )

    @register(_evaluate_subd_doc_spec)
    async def run_evaluate_subd_doc(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        raw_verts = a.get("vertices", [])
        raw_faces = a.get("faces", [])
        raw_creases = a.get("creases", [])
        levels = int(a.get("levels", 2))

        if not raw_verts:
            return err_payload("vertices is required", "BAD_ARGS")
        if not raw_faces:
            return err_payload("faces is required", "BAD_ARGS")
        if levels < 0 or levels > 6:
            return err_payload("levels must be 0..6", "BAD_ARGS")

        try:
            mesh = SubDMesh(
                vertices=[[float(x) for x in v] for v in raw_verts],
                faces=[[int(i) for i in f] for f in raw_faces],
            )
        except Exception as exc:
            return err_payload(f"invalid mesh: {exc}", "BAD_ARGS")

        for ce in raw_creases:
            try:
                mesh.set_crease(int(ce["v1"]), int(ce["v2"]), float(ce["value"]))
            except Exception:
                pass

        doc = SubDDoc(control_mesh=mesh, subdivision_level=levels)
        result_doc = subd_doc_evaluate(doc, levels=levels)
        dm = result_doc.display_mesh
        if dm is None:
            return err_payload("evaluation produced no display mesh", "EVAL_ERROR")

        return ok_payload({
            "ok": True,
            "vertices": dm.vertices,
            "faces": dm.faces,
            "num_vertices": dm.num_vertices,
            "num_faces": dm.num_faces,
        })
