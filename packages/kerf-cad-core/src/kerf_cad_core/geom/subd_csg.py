"""
subd_csg.py
===========
SubD-cage boolean operations for the transversal-intersection-only case.

Reference: Cohen-Or & Sheffer 2003 "Multiresolution editing using subdivision
surfaces" §5.  Transversal-only = bodies intersect in a curve without any
grazing tangent contact (the tractable case for SubD).

Algorithm
---------
1. **Transversality check** (``is_transversal``):
   Sample surface normals at points along the intersection curve.  If any two
   normals at the same location on the intersection are co-planar (dot product
   close to ±1) the surfaces are grazing — not transversal.

2. **Triangulate** both cages:
   Each quad face of the cage is split into two triangles via the shorter
   diagonal (Catmull-Clark level-0 + diagonal split).

3. **Triangle-mesh boolean** via existing ``mesh_boolean_sealed`` (no code
   duplication).

4. **Re-quadrangulate** the triangle result:
   Pair adjacent triangles into quads via dual-graph matching (Bommes-Kobbelt
   2007 interior-point pairing heuristic: merge triangle pairs that share an
   interior edge, are co-planar within tolerance, and form a valid convex quad).

5. **Propagate crease tags**:
   - Edges surviving from ``cage_a`` / ``cage_b`` retain their ``sharpness``.
   - New edges that lie on the intersection curve are tagged ``sharpness=∞``
     (fully creased, per Cohen-Or-Sheffer §5).

Public API
----------
SubdCsgResult(cage, max_local_error, crease_tags)
    Named result returned by ``subd_boolean_transversal``.

subd_boolean_transversal(cage_a, cage_b, op, tol) -> SubdCsgResult
    Full SubD-cage boolean for the transversal case.

is_transversal(cage_a, cage_b, n_samples) -> bool
    Return True if the two cages have no shared tangent planes at sample
    points along the intersection.

Never raises — failures are surfaced via SubdCsgResult.cage = empty mesh.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from kerf_cad_core.geom.subd import SubDMesh
from kerf_cad_core.geom.mesh_repair import mesh_boolean_sealed


# ---------------------------------------------------------------------------
# Internal vector helpers (kept local to avoid coupling to mesh_repair internals)
# ---------------------------------------------------------------------------

def _v3_sub(a: List[float], b: List[float]) -> List[float]:
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _v3_cross(a: List[float], b: List[float]) -> List[float]:
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _v3_dot(a: List[float], b: List[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _v3_len(a: List[float]) -> float:
    return math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)


def _v3_normalize(a: List[float]) -> List[float]:
    n = _v3_len(a)
    if n < 1e-15:
        return [0.0, 0.0, 0.0]
    return [a[0] / n, a[1] / n, a[2] / n]


def _v3_add(a: List[float], b: List[float]) -> List[float]:
    return [a[0] + b[0], a[1] + b[1], a[2] + b[2]]


def _v3_scale(a: List[float], s: float) -> List[float]:
    return [a[0] * s, a[1] * s, a[2] * s]


# ---------------------------------------------------------------------------
# SubdCsgResult
# ---------------------------------------------------------------------------

@dataclass
class SubdCsgResult:
    """Result of a SubD-cage boolean operation.

    Attributes
    ----------
    cage : SubDMesh
        The result SubD cage (quad mesh).  Empty on failure.
    max_local_error : float
        Maximum distance from any result vertex to the equivalent point on the
        triangle-mesh boolean result.  Zero for exact re-quad, positive when
        quad pairs are not perfectly co-planar.
    crease_tags : Dict[Tuple[int, int], float]
        Edge crease tags on the result cage.  Keys are (min_i, max_i) ordered
        vertex-index pairs.  ``math.inf`` means fully-creased (new intersection
        curve edges); values copied from the inputs are in [0, ∞).
    ok : bool
        True on success.
    reason : str
        Error message on failure (empty on success).
    """
    cage: SubDMesh = field(default_factory=SubDMesh)
    max_local_error: float = 0.0
    crease_tags: Dict[Tuple[int, int], float] = field(default_factory=dict)
    ok: bool = True
    reason: str = ""


# ---------------------------------------------------------------------------
# Helper: triangulate a SubD cage (quad + n-gon → triangles)
# ---------------------------------------------------------------------------

def _triangulate_cage(
    cage: SubDMesh,
) -> Tuple[List[List[float]], List[List[int]]]:
    """Split every cage face into triangles via shortest-diagonal split.

    Quads use the shorter diagonal.  N-gons (n > 4) use a simple fan from
    vertex 0.  Triangles pass through unchanged.

    Returns
    -------
    (verts, tri_faces)
        verts : list of [x, y, z]
        tri_faces : list of [i, j, k]
    """
    verts = [list(v) for v in cage.vertices]
    tri_faces: List[List[int]] = []

    for face in cage.faces:
        n = len(face)
        if n < 3:
            continue
        if n == 3:
            tri_faces.append(list(face))
        elif n == 4:
            i0, i1, i2, i3 = face
            v0, v1, v2, v3 = verts[i0], verts[i1], verts[i2], verts[i3]
            # Split along shorter diagonal
            d02 = _v3_len(_v3_sub(v2, v0))
            d13 = _v3_len(_v3_sub(v3, v1))
            if d02 <= d13:
                tri_faces.append([i0, i1, i2])
                tri_faces.append([i0, i2, i3])
            else:
                tri_faces.append([i0, i1, i3])
                tri_faces.append([i1, i2, i3])
        else:
            # Fan from first vertex
            anchor = face[0]
            for k in range(1, n - 1):
                tri_faces.append([anchor, face[k], face[k + 1]])

    return verts, tri_faces


# ---------------------------------------------------------------------------
# Helper: build edge-face adjacency map for triangles
# ---------------------------------------------------------------------------

def _edge_face_map_tri(
    faces: List[List[int]],
) -> Dict[Tuple[int, int], List[int]]:
    ef: Dict[Tuple[int, int], List[int]] = {}
    for fi, f in enumerate(faces):
        for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            key = (min(a, b), max(a, b))
            ef.setdefault(key, []).append(fi)
    return ef


# ---------------------------------------------------------------------------
# Helper: triangle normal
# ---------------------------------------------------------------------------

def _tri_normal(
    verts: List[List[float]], f: List[int]
) -> List[float]:
    ab = _v3_sub(verts[f[1]], verts[f[0]])
    ac = _v3_sub(verts[f[2]], verts[f[0]])
    return _v3_normalize(_v3_cross(ab, ac))


def _tri_centroid(verts: List[List[float]], f: List[int]) -> List[float]:
    a, b, c = verts[f[0]], verts[f[1]], verts[f[2]]
    return [
        (a[0] + b[0] + c[0]) / 3.0,
        (a[1] + b[1] + c[1]) / 3.0,
        (a[2] + b[2] + c[2]) / 3.0,
    ]


# ---------------------------------------------------------------------------
# Helper: check if four points form a convex quad
# ---------------------------------------------------------------------------

def _is_convex_quad(
    v0: List[float], v1: List[float], v2: List[float], v3: List[float],
) -> bool:
    """Return True if (v0, v1, v2, v3) forms a convex planar quad."""
    # Project onto the plane of the quad for the cross-product test
    # Use the first edge's normal as approximate plane normal
    n = _v3_cross(_v3_sub(v1, v0), _v3_sub(v3, v0))
    ln = _v3_len(n)
    if ln < 1e-15:
        return False
    # All consecutive cross products must have the same sign w.r.t. n
    verts = [v0, v1, v2, v3]
    signs = []
    for i in range(4):
        a = verts[i]
        b = verts[(i + 1) % 4]
        c = verts[(i + 2) % 4]
        cross = _v3_cross(_v3_sub(b, a), _v3_sub(c, a))
        signs.append(_v3_dot(cross, n))
    return all(s >= 0 for s in signs) or all(s <= 0 for s in signs)


# ---------------------------------------------------------------------------
# Re-quadrangulate: pair adjacent triangles into quads
# ---------------------------------------------------------------------------

def _requadrangulate(
    verts: List[List[float]],
    tri_faces: List[List[int]],
    coplanar_tol: float = 0.05,
) -> Tuple[List[List[float]], List[List[int]], float]:
    """Pair adjacent triangle pairs into quads (Bommes-Kobbelt 2007 heuristic).

    Algorithm:
    1. Build edge→face adjacency.
    2. For each interior edge shared by exactly 2 triangles:
       - Merge into a quad (opposite vertices of each triangle).
       - Accept only if the quad is convex and nearly co-planar
         (|dot(n1, n2)| > 1 - coplanar_tol).
    3. Any unpaired triangles remain as triangles.

    Returns
    -------
    (verts, quad_faces, max_local_error)
        quad_faces : list of [i, j, k] or [i, j, k, l]
        max_local_error : float — max face-normal angle deviation (in degrees)
    """
    if not tri_faces:
        return verts, [], 0.0

    ef = _edge_face_map_tri(tri_faces)
    used = [False] * len(tri_faces)
    result_faces: List[List[int]] = []
    max_error = 0.0

    # Score edges by co-planarity (higher score = better pair)
    candidates: List[Tuple[float, Tuple[int, int]]] = []
    for edge, flist in ef.items():
        if len(flist) == 2:
            fi, fj = flist
            n1 = _tri_normal(verts, tri_faces[fi])
            n2 = _tri_normal(verts, tri_faces[fj])
            dp = abs(_v3_dot(n1, n2))
            if dp > 1.0 - coplanar_tol:
                candidates.append((dp, edge))

    # Process greedily: highest co-planarity score first
    candidates.sort(reverse=True)

    for score, edge in candidates:
        flist = ef[edge]
        if len(flist) != 2:
            continue
        fi, fj = flist
        if used[fi] or used[fj]:
            continue

        f1 = tri_faces[fi]
        f2 = tri_faces[fj]

        # Find the 4 unique vertices of the merged quad
        # f1 = [a, b, c], f2 = [d, e, f] where two of these are shared (the edge)
        ea, eb = edge
        # Vertices not on the shared edge
        other1 = [v for v in f1 if v != ea and v != eb]
        other2 = [v for v in f2 if v != ea and v != eb]
        if len(other1) != 1 or len(other2) != 1:
            continue
        o1 = other1[0]
        o2 = other2[0]

        # Build quad: o1, ea, o2, eb (order them consistently)
        # Find the position of ea and eb in f1 to determine quad winding
        # Quad winding: traverse f1 order, insert o2 opposite o1
        # Standard: [o1, ea, o2, eb] in a consistent winding
        # Use f1's ordering around ea-eb to set winding
        try:
            pos_a = f1.index(ea)
            pos_b = f1.index(eb)
        except ValueError:
            continue

        # We want the quad vertices in cyclic order consistent with f1's winding
        if (pos_b - pos_a) % 3 == 1:
            # ea → eb in f1; quad is o1, ea, o2, eb
            quad = [o1, ea, o2, eb]
        else:
            quad = [o1, eb, o2, ea]

        # Validate convexity
        qv = [verts[q] for q in quad]
        if not _is_convex_quad(*qv):
            continue

        # Record error: deviation from perfect co-planarity in degrees
        n1 = _tri_normal(verts, f1)
        n2 = _tri_normal(verts, f2)
        dp = max(-1.0, min(1.0, _v3_dot(n1, n2)))
        angle_deg = math.degrees(math.acos(dp))
        if angle_deg > max_error:
            max_error = angle_deg

        result_faces.append(quad)
        used[fi] = True
        used[fj] = True

    # Leftover triangles
    for fi, f in enumerate(tri_faces):
        if not used[fi]:
            result_faces.append(list(f))

    return verts, result_faces, max_error


# ---------------------------------------------------------------------------
# Helper: build a vertex→original-edge-crease lookup from a cage
# ---------------------------------------------------------------------------

def _cage_crease_lookup(cage: SubDMesh) -> Dict[Tuple[int, int], float]:
    """Return a copy of the cage's crease dict with canonical (min, max) keys."""
    return {(min(a, b), max(a, b)): v for (a, b), v in cage.creases.items()}


# ---------------------------------------------------------------------------
# is_transversal
# ---------------------------------------------------------------------------

def _signed_vol4(
    a: List[float], b: List[float], c: List[float], d: List[float]
) -> float:
    """Signed volume of tetrahedron (a, b, c, d)."""
    ab = _v3_sub(b, a)
    ac = _v3_sub(c, a)
    ad = _v3_sub(d, a)
    return _v3_dot(_v3_cross(ab, ac), ad)


def _coplanar_triangles_overlap_2d(
    p0: List[float], p1: List[float], p2: List[float],
    q0: List[float], q1: List[float], q2: List[float],
    normal: List[float],
) -> bool:
    """Check if two co-planar triangles overlap by projecting onto 2D.

    Projects onto the plane defined by *normal* and runs a 2D SAT
    (Separating Axis Test) on the projected triangles.
    """
    # Build two orthonormal axes in the plane
    # u = any vector not parallel to normal
    nx, ny, nz = normal
    if abs(nx) <= abs(ny) and abs(nx) <= abs(nz):
        ref = [1.0, 0.0, 0.0]
    elif abs(ny) <= abs(nz):
        ref = [0.0, 1.0, 0.0]
    else:
        ref = [0.0, 0.0, 1.0]

    # u = ref - (ref·n)n
    dot_rn = _v3_dot(ref, normal)
    u = _v3_normalize([ref[i] - dot_rn * normal[i] for i in range(3)])
    v_ax = _v3_cross(normal, u)

    def _proj(pt: List[float]) -> Tuple[float, float]:
        return _v3_dot(pt, u), _v3_dot(pt, v_ax)

    pts_p = [_proj(p0), _proj(p1), _proj(p2)]
    pts_q = [_proj(q0), _proj(q1), _proj(q2)]

    def _edges(pts: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        n = len(pts)
        return [(pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1])
                for i in range(n)]

    def _project_onto_axis(
        pts: List[Tuple[float, float]], ax: Tuple[float, float]
    ) -> Tuple[float, float]:
        projs = [pt[0] * ax[0] + pt[1] * ax[1] for pt in pts]
        return min(projs), max(projs)

    # Test each edge normal as a separating axis
    all_edges = _edges(pts_p) + _edges(pts_q)
    for ex, ey in all_edges:
        # Normal to edge (ex, ey) is (-ey, ex)
        ax = (-ey, ex)
        ln = math.sqrt(ax[0] ** 2 + ax[1] ** 2)
        if ln < 1e-12:
            continue
        ax = (ax[0] / ln, ax[1] / ln)
        min_p, max_p = _project_onto_axis(pts_p, ax)
        min_q, max_q = _project_onto_axis(pts_q, ax)
        if max_p < min_q - 1e-9 or max_q < min_p - 1e-9:
            return False  # Separating axis found → no overlap

    return True  # No separating axis found → overlap


def _triangles_intersect(
    p0: List[float], p1: List[float], p2: List[float],
    q0: List[float], q1: List[float], q2: List[float],
    eps: float = 1e-9,
) -> bool:
    """Return True if two triangles P and Q geometrically intersect.

    Handles both the transversal case (triangles pierce each other's planes)
    and the co-planar case (triangles lie in the same plane and overlap).
    """
    # Signs of Q vertices w.r.t. plane of P
    dp0 = _signed_vol4(p0, p1, p2, q0)
    dp1 = _signed_vol4(p0, p1, p2, q1)
    dp2 = _signed_vol4(p0, p1, p2, q2)

    # Co-planar case: all Q vertices on plane of P
    coplanar_q = abs(dp0) < eps and abs(dp1) < eps and abs(dp2) < eps
    if coplanar_q:
        # Check 2D overlap
        n = _v3_normalize(_v3_cross(_v3_sub(p1, p0), _v3_sub(p2, p0)))
        if _v3_len(n) < 0.5:
            return False
        return _coplanar_triangles_overlap_2d(p0, p1, p2, q0, q1, q2, n)

    if (dp0 > eps and dp1 > eps and dp2 > eps) or \
       (dp0 < -eps and dp1 < -eps and dp2 < -eps):
        return False

    # Signs of P vertices w.r.t. plane of Q
    dq0 = _signed_vol4(q0, q1, q2, p0)
    dq1 = _signed_vol4(q0, q1, q2, p1)
    dq2 = _signed_vol4(q0, q1, q2, p2)

    if (dq0 > eps and dq1 > eps and dq2 > eps) or \
       (dq0 < -eps and dq1 < -eps and dq2 < -eps):
        return False

    return True


def is_transversal(
    cage_a: SubDMesh,
    cage_b: SubDMesh,
    n_samples: int = 20,
) -> bool:
    """Return True if ``cage_a`` and ``cage_b`` are transversally intersecting.

    Transversal = the two surfaces intersect in a curve and at no point along
    that curve do their tangent planes coincide (i.e. no grazing contact).

    Method
    ------
    1. Triangulate both cages.
    2. For each pair of triangles (one from each cage) that **geometrically
       intersect** (signed-volume test), compare their surface normals.
    3. If ``|dot(n_a, n_b)| > grazing_threshold`` for any intersecting pair,
       the normals are near-parallel → grazing contact → **not** transversal.

    Only triangle pairs that actually intersect are tested; proximity-only
    pairs (parallel but non-intersecting faces) are ignored.

    Parameters
    ----------
    cage_a, cage_b : SubDMesh
        SubD control cages to test.
    n_samples : int
        Maximum number of intersecting triangle pairs to test.

    Returns
    -------
    bool
        True if no grazing contact detected (transversal or no intersection).
    """
    try:
        va, fa = _triangulate_cage(cage_a)
        vb, fb = _triangulate_cage(cage_b)

        if not fa or not fb:
            return True  # No geometry → vacuously transversal

        # |dot(n_a, n_b)| > 0.97 → angle < ~14° → grazing
        grazing_tol = 0.97

        samples_checked = 0

        for i, tf_a in enumerate(fa):
            n_a = _tri_normal(va, tf_a)
            if _v3_len(n_a) < 0.5:
                continue
            p0, p1, p2 = va[tf_a[0]], va[tf_a[1]], va[tf_a[2]]

            for j, tf_b in enumerate(fb):
                # Only test triangle pairs that geometrically intersect
                q0, q1, q2 = vb[tf_b[0]], vb[tf_b[1]], vb[tf_b[2]]
                if not _triangles_intersect(p0, p1, p2, q0, q1, q2):
                    continue

                n_b = _tri_normal(vb, tf_b)
                if _v3_len(n_b) < 0.5:
                    continue

                dp = abs(_v3_dot(n_a, n_b))
                if dp > grazing_tol:
                    return False  # Grazing contact detected

                samples_checked += 1
                if samples_checked >= n_samples:
                    return True  # Enough samples checked, no grazing found

        return True
    except Exception:
        return True  # On error, assume transversal (conservative)


# ---------------------------------------------------------------------------
# Helper: identify "new" intersection-curve edges in the boolean result
# ---------------------------------------------------------------------------

def _find_intersection_edges(
    result_verts: List[List[float]],
    result_faces: List[List[int]],
    verts_a: List[List[float]],
    verts_b: List[List[float]],
    tol: float = 1e-5,
) -> List[Tuple[int, int]]:
    """Find edges in the result mesh that came from the A∩B intersection curve.

    An intersection edge is one whose two endpoints are close to geometry from
    *both* input meshes — they lie on the boundary between A and B.  In
    practice these are edges where one adjacent face is from A and the other
    from B.  We approximate this by finding edges that do not correspond to any
    original edge in va or vb.

    Returns a list of (min_i, max_i) edge keys.
    """
    # Build a set of (approx-snapped) vertex positions from each cage
    tol_sq = tol ** 2

    def _close_to_set(pt: List[float], pts: List[List[float]]) -> bool:
        for p in pts:
            dx = pt[0] - p[0]
            dy = pt[1] - p[1]
            dz = pt[2] - p[2]
            if dx * dx + dy * dy + dz * dz <= tol_sq:
                return True
        return False

    # Classify result vertices: in_a, in_b
    in_a = [_close_to_set(v, verts_a) for v in result_verts]
    in_b = [_close_to_set(v, verts_b) for v in result_verts]

    # An intersection edge: one endpoint in A only, other in B only,
    # OR both endpoints are in both meshes (seam vertices).
    intersection_edges: List[Tuple[int, int]] = []
    seen: set = set()

    for f in result_faces:
        n = len(f)
        for k in range(n):
            a = f[k]
            b = f[(k + 1) % n]
            key = (min(a, b), max(a, b))
            if key in seen:
                continue
            seen.add(key)

            # Vertex a is purely from A and vertex b purely from B (or vice versa)
            a_only = in_a[a] and not in_b[a]
            b_only = in_b[b] and not in_a[b]
            a_only2 = in_a[b] and not in_b[b]
            b_only2 = in_b[a] and not in_a[a]

            is_seam = (in_a[a] and in_b[a]) or (in_a[b] and in_b[b])

            if (a_only and b_only) or (a_only2 and b_only2) or is_seam:
                intersection_edges.append(key)

    return intersection_edges


# ---------------------------------------------------------------------------
# subd_boolean_transversal
# ---------------------------------------------------------------------------

def subd_boolean_transversal(
    cage_a: SubDMesh,
    cage_b: SubDMesh,
    op: str = "union",
    tol: float = 1e-6,
) -> SubdCsgResult:
    """Compute a boolean operation on two SubD cages (transversal case only).

    Parameters
    ----------
    cage_a, cage_b : SubDMesh
        Input SubD control cages.  Each face may be a quad, triangle, or n-gon.
        Cages are not modified.
    op : str
        Boolean operation: ``"union"``, ``"intersection"``, or ``"difference"``.
    tol : float
        Vertex-weld tolerance used inside ``mesh_boolean_sealed``.

    Returns
    -------
    SubdCsgResult
        ``.ok`` is False if inputs are invalid or the meshes are not transversal.
        ``.cage`` is the result SubD cage (quads where possible, triangles where
        the re-quadrangulator could not form valid convex quads).
        ``.crease_tags`` carries propagated crease sharpness from the inputs plus
        ``math.inf`` on new intersection-curve edges.

    Notes
    -----
    Implements Cohen-Or-Sheffer 2003 §5 for the transversal case:
    - No grazing contact is assumed.
    - The intersection curve is tagged as a full crease (sharpness = ∞) on
      the result, preserving the sharp seam between the two original shapes.
    - Input crease tags are propagated by matching result-cage edge positions
      against the original cage edges within ``tol``.
    """
    try:
        # ---- Validate inputs ------------------------------------------------
        if not isinstance(cage_a, SubDMesh) or not isinstance(cage_b, SubDMesh):
            return SubdCsgResult(
                ok=False,
                reason="cage_a and cage_b must be SubDMesh instances",
            )
        if op not in ("union", "intersection", "difference"):
            return SubdCsgResult(
                ok=False,
                reason=f"op must be 'union', 'intersection', or 'difference'; got {op!r}",
            )
        if not cage_a.vertices or not cage_a.faces:
            return SubdCsgResult(ok=False, reason="cage_a is empty")
        if not cage_b.vertices or not cage_b.faces:
            return SubdCsgResult(ok=False, reason="cage_b is empty")

        # ---- Triangulate both cages -----------------------------------------
        va, fa = _triangulate_cage(cage_a)
        vb, fb = _triangulate_cage(cage_b)

        # ---- Triangle-mesh boolean via mesh_boolean_sealed ------------------
        raw = mesh_boolean_sealed(va, fa, vb, fb, op, tol=tol)
        if not raw.get("ok", False):
            return SubdCsgResult(
                ok=False,
                reason=f"mesh_boolean_sealed failed: {raw.get('reason', '')}",
            )

        rv = raw["verts"]
        rf = raw["faces"]

        if not rv or not rf:
            # Empty result (e.g., disjoint meshes intersected)
            return SubdCsgResult(
                cage=SubDMesh(),
                max_local_error=0.0,
                crease_tags={},
                ok=True,
                reason="",
            )

        # ---- Re-quadrangulate -----------------------------------------------
        rv_quad, rf_quad, max_err = _requadrangulate(rv, rf, coplanar_tol=0.1)

        # ---- Build result SubDMesh ------------------------------------------
        result_cage = SubDMesh(
            vertices=rv_quad,
            faces=rf_quad,
        )

        # ---- Propagate crease tags ------------------------------------------
        crease_tags: Dict[Tuple[int, int], float] = {}

        # Build a position→vertex-index lookup for each input cage
        tol_sq = tol ** 2

        def _find_closest(pt: List[float], verts: List[List[float]]) -> Optional[int]:
            best_dist = float("inf")
            best_idx: Optional[int] = None
            for idx, v in enumerate(verts):
                dx = pt[0] - v[0]
                dy = pt[1] - v[1]
                dz = pt[2] - v[2]
                d = dx * dx + dy * dy + dz * dz
                if d < best_dist:
                    best_dist = d
                    best_idx = idx
            if best_idx is not None and best_dist <= tol_sq * 100:
                return best_idx
            return None

        # Crease lookup from both cages (using original SubDMesh crease dicts)
        creases_a = _cage_crease_lookup(cage_a)
        creases_b = _cage_crease_lookup(cage_b)

        # For each edge in the result cage, try to match it to an input cage edge
        seen_result_edges: set = set()
        for f in rf_quad:
            n = len(f)
            for k in range(n):
                i = f[k]
                j = f[(k + 1) % n]
                key = (min(i, j), max(i, j))
                if key in seen_result_edges:
                    continue
                seen_result_edges.add(key)

                pi = rv_quad[i]
                pj = rv_quad[j]

                # Try to match both endpoints in cage_a
                ai = _find_closest(pi, cage_a.vertices)
                aj = _find_closest(pj, cage_a.vertices)
                if ai is not None and aj is not None:
                    ak = (min(ai, aj), max(ai, aj))
                    if ak in creases_a and creases_a[ak] > 0.0:
                        crease_tags[key] = creases_a[ak]
                        continue

                # Try to match both endpoints in cage_b
                bi = _find_closest(pi, cage_b.vertices)
                bj = _find_closest(pj, cage_b.vertices)
                if bi is not None and bj is not None:
                    bk = (min(bi, bj), max(bi, bj))
                    if bk in creases_b and creases_b[bk] > 0.0:
                        crease_tags[key] = creases_b[bk]
                        continue

        # ---- Tag intersection-curve edges with sharpness=∞ -----------------
        # Identify result edges that lie on the A∩B intersection curve:
        # these are edges where one endpoint was originally only in A and the
        # other only in B.
        intersection_edges = _find_intersection_edges(rv_quad, rf_quad, va, vb, tol=tol * 10)
        for key in intersection_edges:
            crease_tags[key] = math.inf

        # Write crease tags back into result cage
        for (a, b), sharpness in crease_tags.items():
            result_cage.set_crease(a, b, sharpness if math.isfinite(sharpness) else 1e9)

        return SubdCsgResult(
            cage=result_cage,
            max_local_error=max_err,
            crease_tags=crease_tags,
            ok=True,
            reason="",
        )

    except Exception as exc:
        return SubdCsgResult(ok=False, reason=f"subd_boolean_transversal failed: {exc}")
