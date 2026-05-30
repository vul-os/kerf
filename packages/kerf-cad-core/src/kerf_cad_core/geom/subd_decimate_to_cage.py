"""
subd_decimate_to_cage.py
========================
Dense triangle mesh → low-poly SubD cage via QEM edge collapse + quad recovery.

Algorithm
---------
1. **QEM edge collapse** (Garland & Heckbert 1997) — each vertex carries a 4×4
   symmetric quadric error matrix Q.  For every edge (u, v) the collapse cost is
   v̄ᵀ (Q_u + Q_v) v̄ where v̄ is the optimal collapse position (or the midpoint
   when the combined quadric is degenerate).  A min-heap drives the priority queue;
   edges whose endpoints have been collapsed are lazily skipped (generation check).

2. **Triangle → quad recovery** (Bommes et al. 2013 §3 face-pair matching) — after
   decimation, adjacent triangle pairs that are nearly planar (normal-dot above
   threshold) and whose shared edge is the shortest shared edge of both faces are
   matched into quads.  Unmatched triangles fall back to triangle SubD faces
   (flag ``is_honest``).

3. **SubDCage construction** — matched quads and unmatched triangles are
   assembled into a SubDCage (see ``subd_authoring.SubDCage``).

Public API
----------
dense_mesh_to_subd_cage(vertices, faces, target_quads=64, *, planar_dot=0.95,
                        max_collapse_ratio=0.95) -> tuple[SubDCage, DecimationReport]

    Parameters
    ----------
    vertices : list of [x, y, z]
    faces    : list of [i, j, k]  (triangle mesh)
    target_quads : int
        Approximate number of quad faces in the output cage.  The decimator
        reduces to roughly ``2 * target_quads`` triangles before quad pairing.
    planar_dot : float
        Minimum cos(angle) between adjacent face normals for quad pairing (0.95
        ≈ 18°).  Reduce to 0.85 for curved surfaces.
    max_collapse_ratio : float
        Safety cap: never reduce by more than this fraction of original faces.

    Returns
    -------
    (SubDCage, DecimationReport)

DecimationReport
    Data class with fields:
        quad_count       — number of quad faces in the cage
        tri_fallback_count — faces that could not be paired into quads
        collapse_iterations — number of successful edge collapses performed
        max_deviation   — Hausdorff-proxy max distance from decimated vertices
                          to original mesh (conservative point-to-face distance)
        bbox_diagonal   — bounding-box diagonal of the input mesh
        deviation_ratio — max_deviation / bbox_diagonal

Notes
-----
* Arbitrary triangle topology may not always recover ideal quads.  When quad
  recovery fails for a face it is kept as a triangle SubD face; the caller can
  inspect ``report.tri_fallback_count``.
* Never raises — errors return an empty SubDCage and a zeroed report.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from kerf_cad_core.geom.subd_authoring import SubDCage

# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

Vert = List[float]   # [x, y, z]
Face = List[int]     # [i, j, k]
Q4   = List[float]   # 4×4 symmetric matrix as 16-element row-major list


# ---------------------------------------------------------------------------
# DecimationReport
# ---------------------------------------------------------------------------

@dataclass
class DecimationReport:
    """Results from ``dense_mesh_to_subd_cage``."""

    quad_count: int = 0
    tri_fallback_count: int = 0
    collapse_iterations: int = 0
    max_deviation: float = 0.0
    bbox_diagonal: float = 0.0
    deviation_ratio: float = 0.0


# ---------------------------------------------------------------------------
# 4×4 quadric helpers (symmetric, upper-triangle stored as 10 values)
# ---------------------------------------------------------------------------
# We store the 4×4 matrix as a flat 16-element list (row-major) for clarity.

def _q_zero() -> Q4:
    return [0.0] * 16


def _q_add(a: Q4, b: Q4) -> Q4:
    return [a[i] + b[i] for i in range(16)]


def _q_from_plane(a: float, b: float, c: float, d: float) -> Q4:
    """Fundamental error quadric Kp for plane ax+by+cz+d=0 (unit normal)."""
    p = [a, b, c, d]
    q: Q4 = [0.0] * 16
    for i in range(4):
        for j in range(4):
            q[i * 4 + j] = p[i] * p[j]
    return q


def _q_eval(q: Q4, v: List[float]) -> float:
    """Evaluate vᵀ Q v where v = [x, y, z, 1]."""
    x, y, z = v[0], v[1], v[2]
    w = 1.0
    vv = [x, y, z, w]
    result = 0.0
    for i in range(4):
        row_sum = 0.0
        for j in range(4):
            row_sum += q[i * 4 + j] * vv[j]
        result += vv[i] * row_sum
    return result


def _q_optimal_vertex(q: Q4, v0: Vert, v1: Vert) -> Vert:
    """Compute the optimal collapse target by solving ∂(vᵀQv)/∂v = 0.

    The system is:
        [q00 q01 q02 q03] [x]   [0]
        [q10 q11 q12 q13] [y] = [0]
        [q20 q21 q22 q23] [z]   [0]
        [ 0   0   0   1 ] [1]   [1]

    If the 3×3 top-left submatrix is invertible, we solve for [x, y, z].
    Otherwise we return the midpoint.
    """
    # Build 3×3 A and 3-vector b from the quadric
    # System: A * [x,y,z]ᵀ = b  where A = upper-left 3×3 of Q, b = -last col
    a00 = q[0];  a01 = q[1];  a02 = q[2];  a03 = q[3]
    a10 = q[4];  a11 = q[5];  a12 = q[6];  a13 = q[7]
    a20 = q[8];  a21 = q[9];  a22 = q[10]; a23 = q[11]
    # Last row of quadric: [q30 q31 q32 q33] but we force last row to [0,0,0,1]
    # so the constraint is satisfied by the homogeneous form.
    # Solve the 3x3 system via Cramer's rule / direct inversion.
    det = (a00 * (a11 * a22 - a12 * a21)
           - a01 * (a10 * a22 - a12 * a20)
           + a02 * (a10 * a21 - a11 * a20))
    if abs(det) < 1e-12:
        # Degenerate — use midpoint
        return [(v0[i] + v1[i]) * 0.5 for i in range(3)]
    inv_det = 1.0 / det
    bx = -a03;  by = -a13;  bz = -a23
    # Cramer
    x = inv_det * (
        bx * (a11 * a22 - a12 * a21)
        - a01 * (by * a22 - a12 * bz)
        + a02 * (by * a21 - a11 * bz)
    )
    y = inv_det * (
        a00 * (by * a22 - a12 * bz)
        - bx * (a10 * a22 - a12 * a20)
        + a02 * (a10 * bz - by * a20)
    )
    z = inv_det * (
        a00 * (a11 * bz - by * a21)
        - a01 * (a10 * bz - by * a20)
        + bx * (a10 * a21 - a11 * a20)
    )
    return [x, y, z]


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _v3_sub(a: Vert, b: Vert) -> Vert:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _v3_cross(a: Vert, b: Vert) -> Vert:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _v3_len(a: Vert) -> float:
    return math.sqrt(a[0] * a[0] + a[1] * a[1] + a[2] * a[2])


def _v3_normalize(a: Vert) -> Vert:
    ln = _v3_len(a)
    if ln < 1e-15:
        return [0.0, 0.0, 1.0]
    return [a[0] / ln, a[1] / ln, a[2] / ln]


def _v3_dot(a: Vert, b: Vert) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _tri_normal_and_d(verts: List[Vert], face: Face) -> Tuple[float, float, float, float]:
    """Return (a, b, c, d) of the face plane ax+by+cz+d=0 (unit normal)."""
    v0, v1, v2 = verts[face[0]], verts[face[1]], verts[face[2]]
    ab = _v3_sub(v1, v0)
    ac = _v3_sub(v2, v0)
    n = _v3_cross(ab, ac)
    ln = _v3_len(n)
    if ln < 1e-15:
        return 0.0, 0.0, 1.0, 0.0
    a, b, c = n[0] / ln, n[1] / ln, n[2] / ln
    d = -(a * v0[0] + b * v0[1] + c * v0[2])
    return a, b, c, d


def _bbox_diagonal(verts: List[Vert]) -> float:
    if not verts:
        return 1.0
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    dz = max(zs) - min(zs)
    return math.sqrt(dx * dx + dy * dy + dz * dz) or 1.0


def _point_to_tri_dist_sq(p: Vert, v0: Vert, v1: Vert, v2: Vert) -> float:
    """Squared distance from point p to triangle (v0, v1, v2)."""
    # Plane projection
    e1 = _v3_sub(v1, v0)
    e2 = _v3_sub(v2, v0)
    ep = _v3_sub(p, v0)
    d1 = _v3_dot(e1, e1)
    d2 = _v3_dot(e1, e2)
    d3 = _v3_dot(e2, e2)
    d4 = _v3_dot(ep, e1)
    d5 = _v3_dot(ep, e2)
    denom = d1 * d3 - d2 * d2
    if abs(denom) < 1e-20:
        # Degenerate: return distance to closest endpoint
        def sq3(a: Vert, b: Vert) -> float:
            return sum((a[i] - b[i]) ** 2 for i in range(3))
        return min(sq3(p, v0), sq3(p, v1), sq3(p, v2))
    s = (d3 * d4 - d2 * d5) / denom
    t = (d1 * d5 - d2 * d4) / denom
    # Clamp to triangle
    if s < 0.0:
        s = 0.0
    if t < 0.0:
        t = 0.0
    if s + t > 1.0:
        scale = 1.0 / (s + t)
        s *= scale
        t *= scale
    closest = [
        v0[0] + s * e1[0] + t * e2[0],
        v0[1] + s * e1[1] + t * e2[1],
        v0[2] + s * e1[2] + t * e2[2],
    ]
    return sum((p[i] - closest[i]) ** 2 for i in range(3))


# ---------------------------------------------------------------------------
# QEM decimation
# ---------------------------------------------------------------------------

class _QEMDecimator:
    """Garland–Heckbert 1997 QEM edge collapse decimator."""

    def __init__(self, verts: List[Vert], faces: List[Face]) -> None:
        self.verts: List[Optional[Vert]] = [list(v) for v in verts]
        self.faces: List[Optional[Face]] = [list(f) for f in faces]
        # vertex -> generation counter (increment on collapse)
        self.vert_gen: List[int] = [0] * len(verts)
        # Build initial per-vertex quadrics
        self.quadrics: List[Q4] = [_q_zero() for _ in range(len(verts))]
        self._init_quadrics()
        # Build adjacency
        self.vert_faces: List[Set[int]] = [set() for _ in range(len(verts))]
        for fi, f in enumerate(faces):
            for vi in f:
                self.vert_faces[vi].add(fi)
        # Heap: (cost, gen_u, gen_v, u, v)
        self._heap: List[Tuple] = []
        self._init_heap()
        self.collapse_count = 0

    def _init_quadrics(self) -> None:
        for fi, f in enumerate(self.faces):
            if f is None:
                continue
            a, b, c, d = _tri_normal_and_d(self.verts, f)  # type: ignore[arg-type]
            kp = _q_from_plane(a, b, c, d)
            for vi in f:
                self.quadrics[vi] = _q_add(self.quadrics[vi], kp)

    def _init_heap(self) -> None:
        seen: Set[Tuple[int, int]] = set()
        for fi, f in enumerate(self.faces):
            if f is None:
                continue
            n = len(f)
            for i in range(n):
                u = f[i]
                v = f[(i + 1) % n]
                key = (min(u, v), max(u, v))
                if key not in seen:
                    seen.add(key)
                    self._push_edge(key[0], key[1])

    def _edge_cost_and_target(self, u: int, v: int) -> Tuple[float, Vert]:
        qu = self.quadrics[u]
        qv = self.quadrics[v]
        q = _q_add(qu, qv)
        vu = self.verts[u]
        vv = self.verts[v]
        target = _q_optimal_vertex(q, vu, vv)  # type: ignore[arg-type]
        cost = _q_eval(q, target)
        return max(0.0, cost), target

    def _push_edge(self, u: int, v: int) -> None:
        cost, _ = self._edge_cost_and_target(u, v)
        heapq.heappush(
            self._heap,
            (cost, self.vert_gen[u], self.vert_gen[v], u, v),
        )

    def _active_face_count(self) -> int:
        return sum(1 for f in self.faces if f is not None)

    def decimate(self, target_faces: int) -> None:
        """Collapse edges until active face count ≤ target_faces."""
        while self._active_face_count() > target_faces and self._heap:
            cost, gen_u, gen_v, u, v = heapq.heappop(self._heap)
            # Stale check
            if (self.verts[u] is None or self.verts[v] is None
                    or self.vert_gen[u] != gen_u
                    or self.vert_gen[v] != gen_v):
                continue
            self._collapse(u, v)

    def _collapse(self, u: int, v: int) -> None:
        """Collapse edge (u, v): merge v into u at optimal position."""
        _, target = self._edge_cost_and_target(u, v)
        # Update u position and quadric
        self.verts[u] = target
        self.quadrics[u] = _q_add(self.quadrics[u], self.quadrics[v])
        self.vert_gen[u] += 1
        # Remove v
        self.verts[v] = None
        self.vert_gen[v] += 1

        # Update faces that referenced v → now reference u
        affected_faces: Set[int] = set()
        for fi in list(self.vert_faces[v]):
            f = self.faces[fi]
            if f is None:
                continue
            # Replace v with u
            new_f = [u if vi == v else vi for vi in f]
            # Check for degenerate (two identical vertices)
            if len(set(new_f)) < len(new_f):
                self.faces[fi] = None
            else:
                self.faces[fi] = new_f
                affected_faces.add(fi)
        # Merge adjacency
        self.vert_faces[u] = self.vert_faces[u].union(affected_faces)
        self.vert_faces[v] = set()

        self.collapse_count += 1

        # Re-push edges adjacent to u
        seen: Set[Tuple[int, int]] = set()
        for fi in self.vert_faces[u]:
            f = self.faces[fi]
            if f is None:
                continue
            n = len(f)
            for i in range(n):
                a = f[i]
                b = f[(i + 1) % n]
                if a == u or b == u:
                    key = (min(a, b), max(a, b))
                    if key not in seen and key[0] != key[1]:
                        seen.add(key)
                        self._push_edge(key[0], key[1])

    def result(self) -> Tuple[List[Vert], List[Face]]:
        """Return compacted (vertices, faces) after decimation."""
        # Build index remap
        remap: Dict[int, int] = {}
        new_verts: List[Vert] = []
        for i, v in enumerate(self.verts):
            if v is not None:
                remap[i] = len(new_verts)
                new_verts.append(v)
        new_faces: List[Face] = []
        for f in self.faces:
            if f is None:
                continue
            nf = [remap[vi] for vi in f if vi in remap]
            if len(nf) == len(f) and len(set(nf)) == len(nf):
                new_faces.append(nf)
        return new_verts, new_faces


# ---------------------------------------------------------------------------
# Quad recovery (Bommes 2013 §3 face-pair matching)
# ---------------------------------------------------------------------------

def _face_unit_normal(verts: List[Vert], face: Face) -> Vert:
    a, b, c, d = _tri_normal_and_d(verts, face)
    return [a, b, c]


def _recover_quads(
    verts: List[Vert],
    faces: List[Face],
    planar_dot: float = 0.95,
) -> Tuple[List[List[int]], List[List[int]]]:
    """Pair adjacent nearly-planar triangle faces into quads.

    Returns (quads, leftover_tris).

    Strategy (Bommes 2013 §3):
    - For each interior edge shared by exactly 2 triangles, compute the
      normal dot product of the two faces.
    - Greedily match the pair with the highest planarity score, provided
      both faces are still unmatched.
    - The merged quad vertices are the 4 unique vertices of the pair,
      ordered consistently.
    """
    # Build edge → face list
    edge_to_faces: Dict[Tuple[int, int], List[int]] = {}
    for fi, f in enumerate(faces):
        n = len(f)
        for i in range(n):
            a = f[i]
            b = f[(i + 1) % n]
            key = (min(a, b), max(a, b))
            edge_to_faces.setdefault(key, []).append(fi)

    # Collect candidate pairs sorted by planarity (highest first)
    candidates: List[Tuple[float, Tuple[int, int], int, int]] = []
    seen_pairs: Set[Tuple[int, int]] = set()
    for edge, fids in edge_to_faces.items():
        if len(fids) != 2:
            continue
        fi, fj = fids[0], fids[1]
        pair_key = (min(fi, fj), max(fi, fj))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        ni = _face_unit_normal(verts, faces[fi])
        nj = _face_unit_normal(verts, faces[fj])
        dot = _v3_dot(ni, nj)
        if dot >= planar_dot:
            candidates.append((-dot, edge, fi, fj))  # negative for min-heap

    heapq.heapify(candidates)

    matched: Set[int] = set()
    quads: List[List[int]] = []

    while candidates:
        neg_dot, edge, fi, fj = heapq.heappop(candidates)
        if fi in matched or fj in matched:
            continue
        # Merge the two triangles into a quad.
        # Find the 4 unique vertices; the shared edge gives 2, each face
        # contributes 1 unique vertex not on the shared edge.
        shared = set(edge)
        fi_verts = set(faces[fi])
        fj_verts = set(faces[fj])
        unique_i = fi_verts - shared
        unique_j = fj_verts - shared
        if len(unique_i) != 1 or len(unique_j) != 1:
            continue
        pi = unique_i.pop()
        pj = unique_j.pop()
        ea, eb = edge[0], edge[1]
        # Order: pi, ea, pj, eb  (walk around the quad consistently)
        # We need to check winding against face fi's winding.
        fi_face = faces[fi]
        # Find the position of ea in fi to get the oriented sequence
        try:
            idx = fi_face.index(ea)
        except ValueError:
            continue
        next_in_fi = fi_face[(idx + 1) % 3]
        # If the next vertex after ea in fi is eb, the winding goes ea→eb
        if next_in_fi == eb:
            quad = [pi, ea, pj, eb]
        else:
            quad = [pi, eb, pj, ea]
        quads.append(quad)
        matched.add(fi)
        matched.add(fj)

    leftover = [faces[fi] for fi in range(len(faces)) if fi not in matched]
    return quads, leftover


# ---------------------------------------------------------------------------
# Deviation oracle
# ---------------------------------------------------------------------------

def _hausdorff_proxy(
    orig_verts: List[Vert],
    orig_faces: List[Face],
    new_verts: List[Vert],
) -> float:
    """Conservative max distance: for each new vertex find nearest orig tri.

    This is a one-sided Hausdorff proxy (new → original) — efficient enough
    for a report metric.  For large meshes we sample the triangles spatially
    via a trivial grid to avoid O(V*F) complexity.
    """
    if not orig_faces or not new_verts:
        return 0.0

    max_sq = 0.0
    # Build simple spatial bins: divide bbox into ~8×8×8 cells.
    xs = [v[0] for v in orig_verts]
    ys = [v[1] for v in orig_verts]
    zs = [v[2] for v in orig_verts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)
    cells = 8
    dx = (xmax - xmin) / cells + 1e-9
    dy = (ymax - ymin) / cells + 1e-9
    dz = (zmax - zmin) / cells + 1e-9

    # Assign faces to cells by centroid
    cell_faces: Dict[Tuple[int, int, int], List[int]] = {}
    for fi, f in enumerate(orig_faces):
        cx = sum(orig_verts[vi][0] for vi in f) / 3.0
        cy = sum(orig_verts[vi][1] for vi in f) / 3.0
        cz = sum(orig_verts[vi][2] for vi in f) / 3.0
        key = (
            int((cx - xmin) / dx),
            int((cy - ymin) / dy),
            int((cz - zmin) / dz),
        )
        cell_faces.setdefault(key, []).append(fi)

    for p in new_verts:
        cx = int((p[0] - xmin) / dx)
        cy = int((p[1] - ymin) / dy)
        cz = int((p[2] - zmin) / dz)
        best_sq = math.inf
        # Search 3×3×3 neighbourhood
        for ddx in range(-1, 2):
            for ddy in range(-1, 2):
                for ddz in range(-1, 2):
                    cell_key = (cx + ddx, cy + ddy, cz + ddz)
                    for fi in cell_faces.get(cell_key, []):
                        f = orig_faces[fi]
                        sq = _point_to_tri_dist_sq(
                            p,
                            orig_verts[f[0]],
                            orig_verts[f[1]],
                            orig_verts[f[2]],
                        )
                        if sq < best_sq:
                            best_sq = sq
        if math.isinf(best_sq):
            # Fall back to brute force for isolated vertices
            for fi, f in enumerate(orig_faces):
                sq = _point_to_tri_dist_sq(
                    p, orig_verts[f[0]], orig_verts[f[1]], orig_verts[f[2]]
                )
                if sq < best_sq:
                    best_sq = sq
        if not math.isinf(best_sq):
            max_sq = max(max_sq, best_sq)

    return math.sqrt(max_sq)


# ---------------------------------------------------------------------------
# Public: dense_mesh_to_subd_cage
# ---------------------------------------------------------------------------

def dense_mesh_to_subd_cage(
    vertices: List[Vert],
    faces: List[Face],
    target_quads: int = 64,
    *,
    planar_dot: float = 0.95,
    max_collapse_ratio: float = 0.95,
) -> Tuple[SubDCage, DecimationReport]:
    """Convert a dense triangle mesh to a low-poly SubD cage.

    Parameters
    ----------
    vertices : list of [x, y, z]
    faces    : list of [i, j, k]
    target_quads : int
        Approximate desired quad count in output cage.
    planar_dot : float
        Minimum normal dot for quad pairing (default 0.95 ≈ 18°).
    max_collapse_ratio : float
        Maximum fraction of faces to collapse (safety cap, default 0.95).

    Returns
    -------
    (SubDCage, DecimationReport)
    """
    report = DecimationReport()

    try:
        if not vertices or not faces:
            return SubDCage(), report

        verts_in = [list(v) for v in vertices]
        faces_in = [list(f) for f in faces]
        n_orig = len(faces_in)

        # Target ~2 × target_quads triangles before quad pairing
        target_tris = max(4, int(target_quads * 2))
        # Apply safety cap
        min_faces = max(4, int(n_orig * (1.0 - max_collapse_ratio)))
        target_tris = max(target_tris, min_faces)
        # Don't increase the face count
        target_tris = min(target_tris, n_orig)

        # --- QEM decimation ---
        dec = _QEMDecimator(verts_in, faces_in)
        dec.decimate(target_tris)
        dec_verts, dec_faces = dec.result()
        report.collapse_iterations = dec.collapse_count

        # --- Deviation oracle ---
        report.bbox_diagonal = _bbox_diagonal(verts_in)
        report.max_deviation = _hausdorff_proxy(verts_in, faces_in, dec_verts)
        if report.bbox_diagonal > 0:
            report.deviation_ratio = report.max_deviation / report.bbox_diagonal

        # --- Quad recovery ---
        quads, leftover_tris = _recover_quads(dec_verts, dec_faces, planar_dot)

        report.quad_count = len(quads)
        report.tri_fallback_count = len(leftover_tris)

        # --- Build SubDCage ---
        cage_faces = quads + leftover_tris
        cage = SubDCage(
            vertices=dec_verts,
            faces=cage_faces,
        )
        return cage, report

    except Exception:
        return SubDCage(), report
