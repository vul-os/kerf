"""fractional_crease.py — Fractional (semi-sharp) creases for Catmull-Clark SubD.

Implements the semi-sharp crease scheme described in:

  DeRose, Kass, Truong (1998). "Subdivision Surfaces in Character Animation."
  SIGGRAPH 1998, §4 — Semi-sharp Creases.

  Bolz, Schröder (2002). "Rapid Evaluation of Catmull-Clark Subdivision Surfaces."

  Pixar OpenSubdiv "Edits" specification (open documentation).

Key insight (DeRose §4):
  A crease with integer sharpness k applies the sharp rule for k subdivision
  levels then switches to the smooth rule.  Fractional sharpness σ ∈ (0, 1)
  blends the smooth and sharp rules at the final semi-sharp level.  Sharpness
  decays by 1.0 per level: s′ = max(0, s − 1).

Public API
----------
CreaseEdge
CreaseVertex
CreaseSubdMesh

subdivide_with_creases(mesh, levels=1) -> CreaseSubdMesh
evaluate_limit_with_creases(mesh, vertex_index) -> Vec3

Vec3 = tuple[float, float, float]
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class CreaseEdge:
    """A directed/undirected edge with a fractional sharpness value.

    Attributes
    ----------
    v0, v1 : int
        Vertex indices in the mesh (order does not matter; edges are
        normalised to (min, max) internally).
    sharpness : float
        Crease sharpness s ∈ [0, ∞).
        0  → smooth (no crease effect at this level).
        1  → sharp for exactly one level, then smooth.
        n  → sharp for n levels; fractional part = blend at last level.
        ∞  → infinitely sharp (DeRose §4.3 "hard crease").
    """
    v0: int
    v1: int
    sharpness: float  # s ∈ [0, ∞); 0 = smooth, ∞ = infinitely sharp


@dataclass
class CreaseVertex:
    """A vertex with a corner-sharpness override.

    Attributes
    ----------
    vertex_index : int
    sharpness : float
        0 → smooth corner, ∞ → true corner (position unchanged).
    """
    vertex_index: int
    sharpness: float  # corner-vertex sharpness


@dataclass
class CreaseSubdMesh:
    """A Catmull-Clark control mesh with fractional crease data.

    Attributes
    ----------
    positions : list[Vec3]
        Control-point positions.
    faces : list[list[int]]
        Quad faces (each a list of 4 vertex indices).
    crease_edges : list[CreaseEdge]
        Edges with non-zero sharpness.
    crease_vertices : list[CreaseVertex]
        Vertices with explicit corner sharpness.
    """
    positions: List[Vec3] = field(default_factory=list)
    faces: List[List[int]] = field(default_factory=list)
    crease_edges: List[CreaseEdge] = field(default_factory=list)
    crease_vertices: List[CreaseVertex] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _edge_key(self, a: int, b: int) -> Tuple[int, int]:
        return (min(a, b), max(a, b))

    def _build_edge_sharpness_map(self) -> Dict[Tuple[int, int], float]:
        """Return {(min_v, max_v): sharpness} for all crease edges."""
        m: Dict[Tuple[int, int], float] = {}
        for ce in self.crease_edges:
            k = self._edge_key(ce.v0, ce.v1)
            m[k] = ce.sharpness
        return m

    def _build_vertex_sharpness_map(self) -> Dict[int, float]:
        """Return {vertex_index: sharpness} for all crease vertices."""
        return {cv.vertex_index: cv.sharpness for cv in self.crease_vertices}

    def _build_adjacency(self) -> Tuple[
        Dict[Tuple[int, int], List[int]],   # edge_key -> [face_indices]
        Dict[int, List[int]],               # vertex   -> [face_indices]
        Dict[int, List[int]],               # vertex   -> [neighbour vertex ids]
    ]:
        """Build edge-face, vertex-face, and vertex-neighbour adjacency maps."""
        edge_faces: Dict[Tuple[int, int], List[int]] = {}
        vert_faces: Dict[int, List[int]] = {}
        vert_nbrs: Dict[int, List[int]] = {}

        for fi, face in enumerate(self.faces):
            n = len(face)
            for vi in face:
                vert_faces.setdefault(vi, []).append(fi)
            for i in range(n):
                a = face[i]
                b = face[(i + 1) % n]
                key = self._edge_key(a, b)
                edge_faces.setdefault(key, []).append(fi)
                if b not in vert_nbrs.get(a, []):
                    vert_nbrs.setdefault(a, []).append(b)
                if a not in vert_nbrs.get(b, []):
                    vert_nbrs.setdefault(b, []).append(a)

        return edge_faces, vert_faces, vert_nbrs

    def _all_edge_keys(self) -> List[Tuple[int, int]]:
        seen: set = set()
        result = []
        for face in self.faces:
            n = len(face)
            for i in range(n):
                key = self._edge_key(face[i], face[(i + 1) % n])
                if key not in seen:
                    seen.add(key)
                    result.append(key)
        return result


# ---------------------------------------------------------------------------
# Vector helpers (numpy-free for inner loops, numpy used where convenient)
# ---------------------------------------------------------------------------

def _v3(x: float, y: float, z: float) -> Vec3:
    return (float(x), float(y), float(z))


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vec3, s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def _lerp(a: Vec3, b: Vec3, t: float) -> Vec3:
    """Linear interpolation: a*(1-t) + b*t."""
    mt = 1.0 - t
    return (a[0] * mt + b[0] * t, a[1] * mt + b[1] * t, a[2] * mt + b[2] * t)


def _centroid(pts: List[Vec3]) -> Vec3:
    n = len(pts)
    if n == 0:
        return (0.0, 0.0, 0.0)
    x = sum(p[0] for p in pts) / n
    y = sum(p[1] for p in pts) / n
    z = sum(p[2] for p in pts) / n
    return (x, y, z)


def _midpoint(a: Vec3, b: Vec3) -> Vec3:
    return ((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5, (a[2] + b[2]) * 0.5)


# ---------------------------------------------------------------------------
# Edge mask helpers
# ---------------------------------------------------------------------------

def _edge_point_smooth(
    va: Vec3,
    vb: Vec3,
    fp1: Vec3,
    fp2: Vec3,
) -> Vec3:
    """Standard Catmull-Clark smooth edge point (interior edge).

    Formula (CC §3.2): (va + vb + F1 + F2) / 4
    where F1, F2 are the face-points of the two adjacent faces.
    Equivalently: 0.25*(va + vb) + 0.25*(F1 + F2).
    """
    # (va + vb + fp1 + fp2) / 4
    x = (va[0] + vb[0] + fp1[0] + fp2[0]) * 0.25
    y = (va[1] + vb[1] + fp1[1] + fp2[1]) * 0.25
    z = (va[2] + vb[2] + fp1[2] + fp2[2]) * 0.25
    return (x, y, z)


def _edge_point_sharp(va: Vec3, vb: Vec3) -> Vec3:
    """Sharp (crease) edge point: simple midpoint.

    DeRose 1998 §4.1 — sharp-crease mask: M_sharp = (v0 + v1) / 2.
    """
    return _midpoint(va, vb)


def _blend_edge_point(
    va: Vec3,
    vb: Vec3,
    fp1: Vec3,
    fp2: Vec3,
    sharpness: float,
) -> Vec3:
    """Fractional crease blend for an edge point.

    DeRose 1998 §4 — semi-sharp blend:
        σ = min(1.0, sharpness)
        E = (1 − σ) * M_smooth + σ * M_sharp

    For sharpness >= 1.0 we use the pure sharp mask.
    For 0 < sharpness < 1.0 we linearly blend smooth ↔ sharp.
    """
    if sharpness >= 1.0 or math.isinf(sharpness):
        return _edge_point_sharp(va, vb)
    if sharpness <= 0.0:
        return _edge_point_smooth(va, vb, fp1, fp2)
    sigma = sharpness  # sigma = min(1, s); already 0 < s < 1
    smooth = _edge_point_smooth(va, vb, fp1, fp2)
    sharp = _edge_point_sharp(va, vb)
    return _lerp(smooth, sharp, sigma)


# ---------------------------------------------------------------------------
# Vertex mask helpers
# ---------------------------------------------------------------------------

def _vertex_point_smooth(
    v: Vec3,
    n: int,                   # valence (number of adjacent faces)
    F: Vec3,                  # average of adjacent face-points
    R: Vec3,                  # average of edge midpoints to neighbours
) -> Vec3:
    """Standard CC smooth vertex rule (DeRose eqn after Catmull-Clark 1978).

    P_new = (F + 2R + (n-3)*P) / n

    where:
      F = average of face-points of adjacent faces (1/n * sum_F)
      R = average of midpoints to each neighbouring vertex (1/n * sum_mid)
      n = valence
    """
    if n < 1:
        return v
    # (F + 2R + (n-3)*P) / n
    coeff_p = float(n - 3) / n
    coeff_f = 1.0 / n
    coeff_r = 2.0 / n
    x = coeff_f * F[0] + coeff_r * R[0] + coeff_p * v[0]
    y = coeff_f * F[1] + coeff_r * R[1] + coeff_p * v[1]
    z = coeff_f * F[2] + coeff_r * R[2] + coeff_p * v[2]
    return (x, y, z)


def _vertex_point_crease(
    v: Vec3,
    crease_nbr_a: Vec3,
    crease_nbr_b: Vec3,
) -> Vec3:
    """1D crease vertex rule (DeRose 1998 §4.2).

    When exactly 2 incident edges carry sharpness >= 1, the vertex moves
    along the crease polyline using the cubic B-spline mask:
        P_new = (1/8)*P_prev + (6/8)*P + (1/8)*P_next

    crease_nbr_a, crease_nbr_b are the two crease neighbours.
    """
    x = 0.125 * crease_nbr_a[0] + 0.75 * v[0] + 0.125 * crease_nbr_b[0]
    y = 0.125 * crease_nbr_a[1] + 0.75 * v[1] + 0.125 * crease_nbr_b[1]
    z = 0.125 * crease_nbr_a[2] + 0.75 * v[2] + 0.125 * crease_nbr_b[2]
    return (x, y, z)


def _compute_vertex_point(
    vi: int,
    positions: List[Vec3],
    vert_faces: Dict[int, List[int]],
    vert_nbrs: Dict[int, List[int]],
    face_pts: List[Vec3],
    edge_sharpness: Dict[Tuple[int, int], float],
    vertex_sharpness: Dict[int, float],
) -> Vec3:
    """Compute the new position for vertex vi.

    Implements the DeRose 1998 §4 fractional-crease vertex rule with
    blending between smooth, crease, and corner masks.

    Classification (per-level, using decayed sharpness):
      k = number of incident edges with sharpness >= 1.0 at this level
      k == 0: smooth CC rule
      k == 1: smooth CC rule (dart vertex — only 1 crease edge)
      k == 2: 1D crease rule along the crease polyline
      k >= 3: corner (vertex unchanged)

    Fractional sharpness (0 < s < 1) on incident edges linearly blends
    the smooth rule towards the crease/corner rule.
    """
    v = positions[vi]
    adj_faces = vert_faces.get(vi, [])
    adj_nbrs = vert_nbrs.get(vi, [])
    valence = len(adj_faces)

    # ------------------------------------------------------------------
    # Explicit corner-vertex sharpness override (CreaseVertex)
    # ------------------------------------------------------------------
    vsharp = vertex_sharpness.get(vi, 0.0)
    if math.isinf(vsharp) or vsharp >= 1.0:
        return v  # corner: unchanged

    def _edge_key(a: int, b: int) -> Tuple[int, int]:
        return (min(a, b), max(a, b))

    def _shar(nb: int) -> float:
        return edge_sharpness.get(_edge_key(vi, nb), 0.0)

    # Classify neighbours by sharpness
    sharp_nbrs = [nb for nb in adj_nbrs if _shar(nb) >= 1.0 or math.isinf(_shar(nb))]
    frac_nbrs  = [nb for nb in adj_nbrs if 0.0 < _shar(nb) < 1.0]
    k = len(sharp_nbrs)

    # ------------------------------------------------------------------
    # Smooth mask components
    # ------------------------------------------------------------------
    if valence == 0:
        smooth_pos = v
    else:
        n = valence
        F = _centroid([face_pts[fi] for fi in adj_faces])
        mids = [_midpoint(v, positions[nb]) for nb in adj_nbrs]
        R = _centroid(mids)
        smooth_pos = _vertex_point_smooth(v, n, F, R)

    # ------------------------------------------------------------------
    # Corner: k >= 3 → vertex unchanged (DeRose §4.2)
    # ------------------------------------------------------------------
    if k >= 3:
        corner_pos = v
        # Blend with vertex sharpness if fractional
        if 0.0 < vsharp < 1.0:
            return _lerp(smooth_pos, corner_pos, vsharp)
        return corner_pos

    # ------------------------------------------------------------------
    # Crease: k == 2 → 1D cubic B-spline mask along the crease
    # (DeRose 1998 §4.2, eq. for crease vertex)
    # ------------------------------------------------------------------
    if k == 2:
        na, nb_v = sharp_nbrs[0], sharp_nbrs[1]
        crease_pos = _vertex_point_crease(v, positions[na], positions[nb_v])

        # If there are additionally fractional crease edges, blend smooth→crease
        # using the maximum fractional sharpness of those edges.
        max_frac = max((_shar(nb) for nb in frac_nbrs), default=0.0)
        # Base blend: smooth ↔ crease via max fractional sharpness
        if max_frac > 0.0:
            crease_pos = _lerp(smooth_pos, crease_pos, max_frac)

        # Vertex-level sharpness blends smooth ↔ crease
        if 0.0 < vsharp < 1.0:
            return _lerp(smooth_pos, crease_pos, vsharp)

        return crease_pos

    # ------------------------------------------------------------------
    # Smooth (k <= 1): standard CC smooth vertex
    # Fractional incident edges blend smooth↔crease (Bolz-Schröder 2002)
    # ------------------------------------------------------------------
    if frac_nbrs:
        # Use maximum fractional sharpness as blend weight (OpenSubdiv convention)
        max_frac = max(_shar(nb) for nb in frac_nbrs)
        if len(frac_nbrs) >= 2:
            # Two fractional crease edges: blend smooth ↔ 1D crease
            fa, fb = frac_nbrs[0], frac_nbrs[1]
            crease_pos = _vertex_point_crease(v, positions[fa], positions[fb])
            return _lerp(smooth_pos, crease_pos, max_frac)
        else:
            # One fractional crease edge (dart): blend smooth ↔ crease-dart
            # Dart vertex blends toward crease rule proportionally
            fa = frac_nbrs[0]
            # For a dart, neighbour on the other side of the crease
            other_nbrs = [nb for nb in adj_nbrs if nb != fa]
            if other_nbrs:
                crease_pos = _vertex_point_crease(v, positions[fa], positions[other_nbrs[0]])
            else:
                crease_pos = v
            return _lerp(smooth_pos, crease_pos, max_frac)

    # Vertex-level sharpness (corner blend)
    if 0.0 < vsharp < 1.0:
        return _lerp(smooth_pos, v, vsharp)

    return smooth_pos


# ---------------------------------------------------------------------------
# One subdivision level
# ---------------------------------------------------------------------------

def _subdivide_once(mesh: CreaseSubdMesh) -> CreaseSubdMesh:
    """Apply one level of Catmull-Clark subdivision with fractional crease support.

    Algorithm (DeRose 1998 §4 + standard CC):
      1. Compute face-points (centroids of face vertices).
      2. Compute edge-points using the fractional crease blend mask.
      3. Compute updated original vertex positions using the vertex mask.
      4. Assemble new quads (each n-face → n quad children).
      5. Propagate crease sharpness: s′ = max(0, s − 1).

    References
    ----------
    DeRose et al. 1998 §4 — semi-sharp crease mask for edge and vertex points.
    Bolz, Schröder 2002 — efficient evaluation; confirms sharpness decay rule.
    OpenSubdiv spec §6.3 — propagation of sharpness to child edges.
    """
    positions = mesh.positions
    faces = mesh.faces
    nv = len(positions)
    nf = len(faces)

    edge_sharpness = mesh._build_edge_sharpness_map()
    vertex_sharpness = mesh._build_vertex_sharpness_map()
    edge_faces, vert_faces, vert_nbrs = mesh._build_adjacency()
    all_edges = mesh._all_edge_keys()

    # ------------------------------------------------------------------
    # 1. Face points — centroid of each face's control vertices
    # ------------------------------------------------------------------
    face_pts: List[Vec3] = []
    for face in faces:
        fp = _centroid([positions[i] for i in face])
        face_pts.append(fp)

    # New vertex layout:
    #   [0..nv-1]         : updated original vertices
    #   [nv..nv+nf-1]     : face points
    #   [nv+nf..nv+nf+ne-1]: edge points

    edge_index: Dict[Tuple[int, int], int] = {}
    edge_pts_list: List[Vec3] = []

    # ------------------------------------------------------------------
    # 2. Edge points with fractional crease mask
    # ------------------------------------------------------------------
    for ei, key in enumerate(all_edges):
        edge_index[key] = nv + nf + ei
        a, b = key
        va, vb = positions[a], positions[b]
        s = edge_sharpness.get(key, 0.0)
        adj_f = edge_faces.get(key, [])

        if len(adj_f) != 2:
            # Boundary edge: always midpoint (sharp by topology)
            ep = _edge_point_sharp(va, vb)
        elif math.isinf(s) or s >= 1.0:
            # DeRose §4.1: fully-sharp edge → pure midpoint
            ep = _edge_point_sharp(va, vb)
        elif s > 0.0:
            # DeRose §4: fractional semi-sharp blend
            # E = (1 − σ)*M_smooth + σ*M_sharp,  σ = s (already in (0,1))
            ep = _blend_edge_point(va, vb, face_pts[adj_f[0]], face_pts[adj_f[1]], s)
        else:
            # Fully smooth interior edge
            ep = _edge_point_smooth(va, vb, face_pts[adj_f[0]], face_pts[adj_f[1]])

        edge_pts_list.append(ep)

    # ------------------------------------------------------------------
    # 3. Updated original vertex positions
    # ------------------------------------------------------------------
    new_orig: List[Vec3] = []
    for vi in range(nv):
        new_pos = _compute_vertex_point(
            vi,
            positions,
            vert_faces,
            vert_nbrs,
            face_pts,
            edge_sharpness,
            vertex_sharpness,
        )
        new_orig.append(new_pos)

    # ------------------------------------------------------------------
    # 4. Assemble new vertex list and quad faces
    # ------------------------------------------------------------------
    new_positions: List[Vec3] = new_orig + face_pts + edge_pts_list

    new_faces: List[List[int]] = []
    for fi, face in enumerate(faces):
        face_pt_idx = nv + fi
        n = len(face)
        for i in range(n):
            va_orig = face[i]
            vb_orig = face[(i + 1) % n]
            vc_orig = face[(i - 1) % n]
            ep_ab = edge_index[mesh._edge_key(va_orig, vb_orig)]
            ep_ca = edge_index[mesh._edge_key(vc_orig, va_orig)]
            new_faces.append([va_orig, ep_ab, face_pt_idx, ep_ca])

    # ------------------------------------------------------------------
    # 5. Propagate crease sharpness — DeRose §4 decay rule:
    #    s′ = max(0, s − 1)   per level
    #    Each original edge (a, b) with edge_point ep splits into two
    #    child edges: (a, ep) and (b, ep), each inheriting s′.
    #    Infinitely sharp edges propagate ∞.
    # ------------------------------------------------------------------
    new_crease_edges: List[CreaseEdge] = []
    for key, s in edge_sharpness.items():
        if s <= 0.0:
            continue
        a, b = key
        ep_idx = edge_index.get(key)
        if ep_idx is None:
            continue
        if math.isinf(s):
            # Infinitely sharp: both children stay ∞
            new_crease_edges.append(CreaseEdge(v0=a, v1=ep_idx, sharpness=math.inf))
            new_crease_edges.append(CreaseEdge(v0=b, v1=ep_idx, sharpness=math.inf))
        else:
            # s′ = max(0, s − 1)
            s_new = max(0.0, s - 1.0)
            if s_new > 0.0:
                new_crease_edges.append(CreaseEdge(v0=a, v1=ep_idx, sharpness=s_new))
                new_crease_edges.append(CreaseEdge(v0=b, v1=ep_idx, sharpness=s_new))

    # Propagate vertex sharpness (corner vertices remain corners)
    new_crease_vertices: List[CreaseVertex] = []
    for cv in mesh.crease_vertices:
        if cv.sharpness > 0.0:
            new_crease_vertices.append(CreaseVertex(
                vertex_index=cv.vertex_index,
                sharpness=cv.sharpness,
            ))

    return CreaseSubdMesh(
        positions=new_positions,
        faces=new_faces,
        crease_edges=new_crease_edges,
        crease_vertices=new_crease_vertices,
    )


# ---------------------------------------------------------------------------
# Public: subdivide_with_creases
# ---------------------------------------------------------------------------

def subdivide_with_creases(mesh: CreaseSubdMesh, levels: int = 1) -> CreaseSubdMesh:
    """Apply N levels of Catmull-Clark subdivision honouring fractional creases.

    One CC subdivision pass per level that honours fractional creases per
    DeRose 1998 §4 + Bolz-Schroeder 2002.

    Rule:
      - If edge.sharpness >= 1.0: use sharp edge mask (linear average of
        v0+v1), and propagate sharpness s′ = max(0, s−1) to both child
        edges.
      - If 0 < edge.sharpness < 1.0: blend smooth and sharp masks with
        weight σ = sharpness.
      - Vertex rule: corner if all incident sharpness >= 1; crease if
        exactly 2; else smooth. Sharpness-blended for fractional cases.

    Parameters
    ----------
    mesh : CreaseSubdMesh
        Input control mesh with crease data.
    levels : int
        Number of subdivision levels (>= 0).  0 returns a copy.

    Returns
    -------
    CreaseSubdMesh
        Subdivided mesh with propagated crease sharpness.
    """
    levels = max(0, int(levels))
    result = CreaseSubdMesh(
        positions=list(mesh.positions),
        faces=[list(f) for f in mesh.faces],
        crease_edges=list(mesh.crease_edges),
        crease_vertices=list(mesh.crease_vertices),
    )
    for _ in range(levels):
        result = _subdivide_once(result)
    return result


# ---------------------------------------------------------------------------
# Public: evaluate_limit_with_creases
# ---------------------------------------------------------------------------

def evaluate_limit_with_creases(mesh: CreaseSubdMesh, vertex_index: int) -> Vec3:
    """Compute the limit position at a tagged vertex, accounting for crease incidence.

    Limit rules (DeRose 1998 §4 + CC limit formula):

      0 sharp incident edges:
        Standard Catmull-Clark smooth limit (Stam 1998 / CC 1978):
            P_lim = (n² * P + 4n * R + n * F) / (n² + 5n)
        where R = average of edge midpoints, F = average of face centroids,
        n = valence.

      2 sharp incident edges:
        1D cubic B-spline limit along the crease curve (DeRose §4.2):
            P_lim = (1/6)*P_prev + (2/3)*P + (1/6)*P_next
        where P_prev, P_next are the two crease neighbours.

      >= 3 sharp incident edges (corner):
        Limit == vertex itself (position unchanged).

    Parameters
    ----------
    mesh : CreaseSubdMesh
    vertex_index : int

    Returns
    -------
    Vec3  — limit position.
    """
    vi = int(vertex_index)
    if vi < 0 or vi >= len(mesh.positions):
        return (0.0, 0.0, 0.0)

    v = mesh.positions[vi]
    edge_sharpness = mesh._build_edge_sharpness_map()
    vertex_sharpness = mesh._build_vertex_sharpness_map()
    _, vert_faces, vert_nbrs = mesh._build_adjacency()

    adj_faces = vert_faces.get(vi, [])
    adj_nbrs = vert_nbrs.get(vi, [])
    n = len(adj_faces)

    def _ek(a: int, b: int) -> Tuple[int, int]:
        return (min(a, b), max(a, b))

    def _shar(nb: int) -> float:
        return edge_sharpness.get(_ek(vi, nb), 0.0)

    sharp_nbrs = [nb for nb in adj_nbrs
                  if _shar(nb) >= 1.0 or math.isinf(_shar(nb))]
    k = len(sharp_nbrs)

    # Vertex-level corner sharpness override
    vsharp = vertex_sharpness.get(vi, 0.0)
    if math.isinf(vsharp) or vsharp >= 1.0:
        return v  # corner limit == vertex itself

    # ------------------------------------------------------------------
    # Corner limit: >= 3 sharp incident edges → vertex unchanged
    # ------------------------------------------------------------------
    if k >= 3:
        return v

    # ------------------------------------------------------------------
    # 1D crease limit: exactly 2 sharp incident edges
    # DeRose §4.2: limit along crease = (1/6)*P_a + (2/3)*P + (1/6)*P_b
    # This is the cubic uniform B-spline limit point.
    # ------------------------------------------------------------------
    if k == 2:
        na, nb_v = sharp_nbrs[0], sharp_nbrs[1]
        pa = mesh.positions[na]
        pb = mesh.positions[nb_v]
        x = (1.0 / 6.0) * pa[0] + (2.0 / 3.0) * v[0] + (1.0 / 6.0) * pb[0]
        y = (1.0 / 6.0) * pa[1] + (2.0 / 3.0) * v[1] + (1.0 / 6.0) * pb[1]
        z = (1.0 / 6.0) * pa[2] + (2.0 / 3.0) * v[2] + (1.0 / 6.0) * pb[2]
        return (x, y, z)

    # ------------------------------------------------------------------
    # Smooth limit: standard CC quasi-uniform limit (Catmull-Clark 1978,
    # also see Stam 1998 for extraordinary vertices; here we use the
    # regular Stam rule valid for valence n):
    #
    #   P_lim = (n² * P + 4 * sum(R_i) + sum(F_i)) / (n² + 5n)
    #
    # where R_i = midpoint to neighbour i, F_i = centroid of face i.
    # (Equivalent form: (n² P + 4n R_avg + n F_avg) / (n² + 5n))
    # ------------------------------------------------------------------
    if n == 0:
        return v

    sum_R = [0.0, 0.0, 0.0]
    for nb in adj_nbrs:
        nb_pos = mesh.positions[nb]
        sum_R[0] += (v[0] + nb_pos[0]) * 0.5
        sum_R[1] += (v[1] + nb_pos[1]) * 0.5
        sum_R[2] += (v[2] + nb_pos[2]) * 0.5

    sum_F = [0.0, 0.0, 0.0]
    for fi in adj_faces:
        fp = _centroid([mesh.positions[i] for i in mesh.faces[fi]])
        sum_F[0] += fp[0]
        sum_F[1] += fp[1]
        sum_F[2] += fp[2]

    denom = float(n * n + 5 * n)
    if abs(denom) < 1e-15:
        return v

    n2 = float(n * n)
    x = (n2 * v[0] + 4.0 * sum_R[0] + sum_F[0]) / denom
    y = (n2 * v[1] + 4.0 * sum_R[1] + sum_F[1]) / denom
    z = (n2 * v[2] + 4.0 * sum_R[2] + sum_F[2]) / denom
    return (x, y, z)
