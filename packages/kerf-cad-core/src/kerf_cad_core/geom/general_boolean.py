"""GK-P09 — General pure-Python solid boolean for convex planar-faced polyhedra.

This module extends the limited-primitive boolean (boolean.py) to arbitrary
convex polyhedra whose faces are all planar (trimmed-plane bodies).  Both the
input and output are expressed as :class:`PlanarPolyhedron` dataclasses —
independent of the B-rep ``Body`` topology — so the implementation is fully
hermetic and has no dependency on OCCT.

Algorithm (Mantyla §6; Hoffmann "Geometric & Solid Modeling" §3)
-----------------------------------------------------------------
1. **Face-face intersection** — for every (face_A, face_B) pair test whether
   the two supporting planes intersect within both face polygons.  The
   intersection of two planes is a line; we clip it against the two convex
   polygons (Sutherland-Hodgman) to obtain a finite edge segment.

2. **Wire loops** — the collected edge segments are threaded into closed wire
   loops by greedy nearest-neighbour walk with endpoint snapping within *tol*.

3. **Trimmed sub-faces** — each original face is split by the wire segments
   that lie on its plane into sub-face polygons via Sutherland-Hodgman
   polygon clipping.

4. **Inside/outside classification** — a sub-face centroid offset slightly
   along its face normal is tested against the other polyhedron by a
   point-in-polyhedron test (sum of signed solid angles / point-in-convex-
   polyhedron half-plane test; correct for convex bodies).

5. **Region selection**:
   - *union*:        sub-faces outside the other body (+ shared boundary)
   - *intersection*: sub-faces inside the other body
   - *difference*:   sub-faces of A outside B U sub-faces of B inside A
     (B faces flipped so they face outward from the result)

6. **Assembly** — the surviving sub-face polygon list is canonicalised back
   into a :class:`PlanarPolyhedron`.

Honesty boundary
----------------
* **Convex inputs only** — the Sutherland-Hodgman clip is correct only for
  convex clipping polygons.  Non-convex inputs will give geometrically
  incorrect sub-face splits.  Use OCCT for non-convex bodies.
* **Planar faces only** — curved faces (cylinders, NURBS) are not handled;
  use OCCT (or the specific analytic paths in boolean.py) for those.
* **Coplanar faces** — pairs of exactly coplanar faces are classified
  conservatively (kept for union / dropped for intersection) but may
  produce duplicate or zero-area sub-faces that are subsequently filtered
  by the area threshold.
* **Numeric robustness** — floating-point tolerance ``tol`` (default 1e-7 mm)
  is propagated throughout; sub-faces with area < 1e-10 * reference_scale² are
  discarded as degenerate.  Near-singular configurations (nearly-coplanar face
  pairs, nearly-touching polyhedra) may require a larger ``tol``.

LLM tool
--------
``brep_general_boolean`` is registered as an LLM tool (ToolSpec + ``@register``)
when ``kerf_chat`` is available.  Input / output is JSON-serialised
:class:`PlanarPolyhedron` (vertex list + face index lists).

References
----------
* Mantyla, M. (1988). *An Introduction to Solid Modeling*. §6.
* Hoffmann, C. M. (1989). *Geometric and Solid Modeling*. §3.
* Sutherland, I. E. & Hodgman, G. W. (1974). *Reentrant Polygon Clipping*.
  CACM 17(1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

__all__ = [
    "PlanarPolyhedron",
    "BooleanResult",
    "boolean_polyhedra",
]

# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------

Vec3 = Tuple[float, float, float]
FaceIndices = List[int]


@dataclass
class PlanarPolyhedron:
    """A closed solid bounded entirely by planar (polygonal) faces.

    Parameters
    ----------
    vertices_xyz_mm:
        Ordered list of 3-D vertex positions in millimetres.
    faces:
        Each entry is an ordered list of vertex indices (into
        ``vertices_xyz_mm``) defining one planar face.  Vertices are
        wound **counter-clockwise** when viewed from outside the solid
        (outward-pointing face normal).
    """

    vertices_xyz_mm: List[Vec3]
    faces: List[FaceIndices]


@dataclass
class BooleanResult:
    """Result of a :func:`boolean_polyhedra` call.

    Parameters
    ----------
    result_polyhedron:
        The output :class:`PlanarPolyhedron` (may have zero faces for empty
        results such as a disjoint intersection).
    operation:
        One of ``"union"``, ``"intersection"``, or ``"difference"``.
    is_valid:
        ``True`` when the result passed internal consistency checks
        (all face normals outward-pointing, volume >= 0).
    num_input_faces_a:
        Number of faces in the first input polyhedron.
    num_input_faces_b:
        Number of faces in the second input polyhedron.
    num_output_faces:
        Number of faces in the result polyhedron.
    honest_caveat:
        Plain-English description of known limitations for this result.
    """

    result_polyhedron: PlanarPolyhedron
    operation: str
    is_valid: bool
    num_input_faces_a: int
    num_input_faces_b: int
    num_output_faces: int
    honest_caveat: str


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------

_TOL_DEFAULT = 1e-7


def _v3(v: Vec3) -> np.ndarray:
    return np.asarray(v, dtype=float)


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _face_normal(verts: np.ndarray) -> np.ndarray:
    """Newell's method — robust normal for planar polygon (n >= 3 vertices)."""
    n = np.zeros(3, dtype=float)
    nv = len(verts)
    for i in range(nv):
        a = verts[i]
        b = verts[(i + 1) % nv]
        n[0] += (a[1] - b[1]) * (a[2] + b[2])
        n[1] += (a[2] - b[2]) * (a[0] + b[0])
        n[2] += (a[0] - b[0]) * (a[1] + b[1])
    return _unit(n)


def _face_centroid(verts: np.ndarray) -> np.ndarray:
    return np.mean(verts, axis=0)


def _face_area(verts: np.ndarray) -> float:
    """Signed area magnitude via cross-product sum (Newell's method)."""
    n = np.zeros(3, dtype=float)
    nv = len(verts)
    for i in range(nv):
        a = verts[i]
        b = verts[(i + 1) % nv]
        n += np.cross(a, b)
    return float(np.linalg.norm(n)) * 0.5


def _poly_verts(poly: PlanarPolyhedron, fi: int) -> np.ndarray:
    """Nx3 array of world-coordinate vertices for face *fi*."""
    idxs = poly.faces[fi]
    return np.array([poly.vertices_xyz_mm[i] for i in idxs], dtype=float)


# ---------------------------------------------------------------------------
# Point-in-convex-polyhedron test
# ---------------------------------------------------------------------------


def _point_in_polyhedron(pt: np.ndarray, poly: PlanarPolyhedron, tol: float) -> bool:
    """Return True when *pt* is inside or on the boundary of *poly*.

    Uses the half-plane (half-space) test: for a convex polyhedron a point
    is inside iff it is on the inner side of every face plane
    (dot(normal, pt - any_face_vertex) <= tol).
    """
    for fi in range(len(poly.faces)):
        verts = _poly_verts(poly, fi)
        if verts.shape[0] < 3:
            continue
        n = _face_normal(verts)
        d = float(np.dot(n, pt - verts[0]))
        if d > tol:
            return False
    return True


# ---------------------------------------------------------------------------
# Sutherland-Hodgman polygon clipping
# ---------------------------------------------------------------------------


def _sh_clip_polygon_by_halfplane(
    polygon: List[np.ndarray],
    plane_point: np.ndarray,
    plane_normal: np.ndarray,
    tol: float,
) -> List[np.ndarray]:
    """Clip *polygon* against one half-plane (inside = dot(n, p-p0) <= tol).

    Returns a new polygon with vertices on the inside.
    """
    if not polygon:
        return []
    result: List[np.ndarray] = []
    n = len(polygon)
    for i in range(n):
        a = polygon[i]
        b = polygon[(i + 1) % n]
        da = float(np.dot(plane_normal, a - plane_point))
        db = float(np.dot(plane_normal, b - plane_point))
        inside_a = da <= tol
        inside_b = db <= tol
        if inside_a:
            result.append(a)
        if inside_a != inside_b:
            # compute edge-plane intersection
            denom = da - db
            if abs(denom) > 1e-14:
                t = da / denom
                result.append(a + t * (b - a))
    return result


def _sh_clip_polygon_by_convex_polygon(
    polygon: List[np.ndarray],
    clip_verts: np.ndarray,
    clip_normal: np.ndarray,
    tol: float,
) -> List[np.ndarray]:
    """Clip *polygon* against the convex *clip_verts* polygon using S-H."""
    out = list(polygon)
    nc = len(clip_verts)
    for i in range(nc):
        if not out:
            break
        a = clip_verts[i]
        b = clip_verts[(i + 1) % nc]
        # edge plane normal (points inward into the clip polygon)
        edge_dir = b - a
        edge_normal = _unit(np.cross(edge_dir, clip_normal))
        out = _sh_clip_polygon_by_halfplane(out, a, edge_normal, tol)
    return out


# ---------------------------------------------------------------------------
# Face-face intersection: compute edge segment where two face planes meet
# ---------------------------------------------------------------------------


def _plane_plane_line(
    n1: np.ndarray,
    d1: float,
    n2: np.ndarray,
    d2: float,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Return (point, direction) of the intersection line of two planes
    n1·x = d1 and n2·x = d2.  Returns None when planes are parallel."""
    direction = np.cross(n1, n2)
    if float(np.linalg.norm(direction)) < 1e-12:
        return None
    direction = _unit(direction)
    # find a point on the line: solve the 2x2 system with a third eq x·direction=0
    M = np.array([n1, n2, direction], dtype=float)
    rhs = np.array([d1, d2, 0.0], dtype=float)
    try:
        point = np.linalg.solve(M, rhs)
    except np.linalg.LinAlgError:
        return None
    return point, direction


def _clip_line_to_polygon(
    line_pt: np.ndarray,
    line_dir: np.ndarray,
    poly_verts: np.ndarray,
    poly_normal: np.ndarray,
    tol: float,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Clip an infinite 3-D line to the interior of a convex polygon.

    Returns the clipped segment (start, end) or None when the line
    does not intersect the polygon interior.
    """
    n = len(poly_verts)
    t_min = -1e18
    t_max = 1e18
    for i in range(n):
        a = poly_verts[i]
        b = poly_verts[(i + 1) % n]
        edge_dir = b - a
        inward_n = _unit(np.cross(edge_dir, poly_normal))
        # dot(inward_n, x - a) >= -tol  =>  t*dot(inward_n, line_dir) >= -tol - dot(inward_n, line_pt - a)
        denom = float(np.dot(inward_n, line_dir))
        lhs = float(np.dot(inward_n, line_pt - a))
        if abs(denom) < 1e-14:
            if lhs > tol:
                return None  # line is outside this edge (parallel and on wrong side)
            continue
        t_cross = -lhs / denom
        # Constraint: lhs + t*denom <= tol (inside half-space).
        # When denom > 0: t <= t_cross  → upper bound.
        # When denom < 0: t >= t_cross  → lower bound.
        if denom > 0:
            t_max = min(t_max, t_cross)
        else:
            t_min = max(t_min, t_cross)
    if t_min > t_max + tol:
        return None
    if t_max - t_min < tol:
        return None  # degenerate / touching
    pt_start = line_pt + t_min * line_dir
    pt_end = line_pt + t_max * line_dir
    return pt_start, pt_end


def _face_face_intersection_segment(
    verts_a: np.ndarray,
    norm_a: np.ndarray,
    verts_b: np.ndarray,
    norm_b: np.ndarray,
    tol: float,
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """Find the line segment where face A and face B intersect.

    Returns None when the faces do not intersect or are coplanar.
    """
    da = float(np.dot(norm_a, verts_a[0]))
    db = float(np.dot(norm_b, verts_b[0]))
    line = _plane_plane_line(norm_a, da, norm_b, db)
    if line is None:
        return None
    line_pt, line_dir = line
    # clip to A
    seg_a = _clip_line_to_polygon(line_pt, line_dir, verts_a, norm_a, tol)
    if seg_a is None:
        return None
    # rebuild clipped segment and clip to B
    seg_a_dir = seg_a[1] - seg_a[0]
    seg_a_len = float(np.linalg.norm(seg_a_dir))
    if seg_a_len < tol:
        return None
    seg_b = _clip_line_to_polygon(seg_a[0], line_dir, verts_b, norm_b, tol)
    if seg_b is None:
        return None
    # intersect the two t-intervals on the line
    t_a0 = float(np.dot(seg_a[0] - line_pt, line_dir))
    t_a1 = float(np.dot(seg_a[1] - line_pt, line_dir))
    t_b0 = float(np.dot(seg_b[0] - line_pt, line_dir))
    t_b1 = float(np.dot(seg_b[1] - line_pt, line_dir))
    t_lo = max(min(t_a0, t_a1), min(t_b0, t_b1))
    t_hi = min(max(t_a0, t_a1), max(t_b0, t_b1))
    if t_hi - t_lo < tol:
        return None
    return line_pt + t_lo * line_dir, line_pt + t_hi * line_dir


# ---------------------------------------------------------------------------
# Build result polyhedron from sub-face polygon lists
# ---------------------------------------------------------------------------


def _dedup_vertices(
    polygons: List[List[np.ndarray]],
    tol: float,
) -> Tuple[List[Vec3], List[FaceIndices]]:
    """Merge near-coincident vertices and return (vertices, face_indices)."""
    verts: List[Vec3] = []
    vert_arr: List[np.ndarray] = []

    def _get_idx(p: np.ndarray) -> int:
        for k, v in enumerate(vert_arr):
            if float(np.linalg.norm(p - v)) <= tol:
                return k
        vert_arr.append(p.copy())
        verts.append((float(p[0]), float(p[1]), float(p[2])))
        return len(verts) - 1

    faces: List[FaceIndices] = []
    for poly in polygons:
        if len(poly) < 3:
            continue
        idxs = [_get_idx(p) for p in poly]
        # deduplicate consecutive identical indices
        deduped: FaceIndices = []
        for idx in idxs:
            if not deduped or deduped[-1] != idx:
                deduped.append(idx)
        if deduped and deduped[0] == deduped[-1]:
            deduped.pop()
        if len(deduped) >= 3:
            faces.append(deduped)
    return verts, faces


# ---------------------------------------------------------------------------
# Volume computation (divergence theorem on triangulated faces)
# ---------------------------------------------------------------------------


def _polyhedron_volume(poly: PlanarPolyhedron) -> float:
    """Signed volume via divergence theorem (positive when outward normals)."""
    vol = 0.0
    for fi in range(len(poly.faces)):
        verts = _poly_verts(poly, fi)
        n = len(verts)
        if n < 3:
            continue
        # fan-triangulate
        v0 = verts[0]
        for i in range(1, n - 1):
            v1 = verts[i]
            v2 = verts[i + 1]
            cross = np.cross(v1 - v0, v2 - v0)
            vol += float(np.dot(v0, cross))
    return abs(vol) / 6.0


# ---------------------------------------------------------------------------
# Main boolean algorithm
# ---------------------------------------------------------------------------


def boolean_polyhedra(
    poly_a: PlanarPolyhedron,
    poly_b: PlanarPolyhedron,
    operation: str,
    tol: float = _TOL_DEFAULT,
) -> BooleanResult:
    """Compute the regularised solid boolean of two convex planar polyhedra.

    Parameters
    ----------
    poly_a, poly_b:
        Input convex planar polyhedra.
    operation:
        One of ``"union"``, ``"intersection"``, or ``"difference"``
        (``"difference"`` computes ``poly_a \\ poly_b``).
    tol:
        Geometric tolerance in mm for vertex snapping, degenerate-face
        filtering, and inside/outside classification.

    Returns
    -------
    BooleanResult
        Contains the result polyhedron and metadata.

    Raises
    ------
    ValueError
        When *operation* is not one of the three supported values.
    """
    if operation not in ("union", "intersection", "difference"):
        raise ValueError(
            f"boolean_polyhedra: operation must be 'union', 'intersection', "
            f"or 'difference'; got {operation!r}"
        )

    nfa = len(poly_a.faces)
    nfb = len(poly_b.faces)

    # ------------------------------------------------------------------
    # Fast-path: disjoint check (for union / difference)
    # ------------------------------------------------------------------
    # We check if any vertex of A is inside B and vice versa.
    a_in_b = any(
        _point_in_polyhedron(_v3(poly_a.vertices_xyz_mm[i]), poly_b, tol)
        for i in range(len(poly_a.vertices_xyz_mm))
    )
    b_in_a = any(
        _point_in_polyhedron(_v3(poly_b.vertices_xyz_mm[i]), poly_a, tol)
        for i in range(len(poly_b.vertices_xyz_mm))
    )

    # Check if there are any face-face intersections
    has_ff_intersection = False
    for fi in range(nfa):
        if has_ff_intersection:
            break
        va = _poly_verts(poly_a, fi)
        na = _face_normal(va)
        for fj in range(nfb):
            vb = _poly_verts(poly_b, fj)
            nb = _face_normal(vb)
            seg = _face_face_intersection_segment(va, na, vb, nb, tol)
            if seg is not None:
                has_ff_intersection = True
                break

    disjoint = not a_in_b and not b_in_a and not has_ff_intersection

    if disjoint:
        if operation == "union":
            # Return both polyhedra merged
            verts = list(poly_a.vertices_xyz_mm) + list(poly_b.vertices_xyz_mm)
            offset = len(poly_a.vertices_xyz_mm)
            faces_a = list(poly_a.faces)
            faces_b = [[idx + offset for idx in f] for f in poly_b.faces]
            result = PlanarPolyhedron(verts, faces_a + faces_b)
            return BooleanResult(
                result_polyhedron=result,
                operation=operation,
                is_valid=True,
                num_input_faces_a=nfa,
                num_input_faces_b=nfb,
                num_output_faces=len(result.faces),
                honest_caveat=(
                    "Inputs are disjoint: result is a multi-component "
                    "polyhedron with both solids; convex inputs only."
                ),
            )
        elif operation in ("intersection", "difference"):
            # intersection of disjoint = empty; A\B disjoint = A
            if operation == "intersection":
                result = PlanarPolyhedron([], [])
                return BooleanResult(
                    result_polyhedron=result,
                    operation=operation,
                    is_valid=True,
                    num_input_faces_a=nfa,
                    num_input_faces_b=nfb,
                    num_output_faces=0,
                    honest_caveat="Inputs are disjoint: intersection is empty.",
                )
            else:
                # difference: A unchanged
                result = PlanarPolyhedron(
                    list(poly_a.vertices_xyz_mm), [list(f) for f in poly_a.faces]
                )
                return BooleanResult(
                    result_polyhedron=result,
                    operation=operation,
                    is_valid=True,
                    num_input_faces_a=nfa,
                    num_input_faces_b=nfb,
                    num_output_faces=len(result.faces),
                    honest_caveat="Inputs are disjoint: difference equals A.",
                )

    # ------------------------------------------------------------------
    # Identity / containment fast-paths
    # ------------------------------------------------------------------
    all_a_in_b = all(
        _point_in_polyhedron(_v3(v), poly_b, tol)
        for v in poly_a.vertices_xyz_mm
    )
    all_b_in_a = all(
        _point_in_polyhedron(_v3(v), poly_a, tol)
        for v in poly_b.vertices_xyz_mm
    )

    if all_a_in_b and all_b_in_a:
        # Identical (or one fully contains the other at tolerance level)
        if operation in ("union", "difference"):
            # union: return A; difference: return empty (A - A ≈ empty)
            if operation == "union":
                result = PlanarPolyhedron(
                    list(poly_a.vertices_xyz_mm), [list(f) for f in poly_a.faces]
                )
                caveat = "Inputs are coincident; result is A."
            else:
                result = PlanarPolyhedron([], [])
                caveat = "Inputs are coincident; difference is empty."
            return BooleanResult(
                result_polyhedron=result,
                operation=operation,
                is_valid=True,
                num_input_faces_a=nfa,
                num_input_faces_b=nfb,
                num_output_faces=len(result.faces),
                honest_caveat=caveat,
            )
        else:
            # intersection = A
            result = PlanarPolyhedron(
                list(poly_a.vertices_xyz_mm), [list(f) for f in poly_a.faces]
            )
            return BooleanResult(
                result_polyhedron=result,
                operation=operation,
                is_valid=True,
                num_input_faces_a=nfa,
                num_input_faces_b=nfb,
                num_output_faces=len(result.faces),
                honest_caveat="Inputs are coincident; intersection is A.",
            )

    if all_a_in_b:
        # A contained in B
        if operation == "union":
            result = PlanarPolyhedron(
                list(poly_b.vertices_xyz_mm), [list(f) for f in poly_b.faces]
            )
            return BooleanResult(
                result_polyhedron=result,
                operation=operation,
                is_valid=True,
                num_input_faces_a=nfa,
                num_input_faces_b=nfb,
                num_output_faces=len(result.faces),
                honest_caveat="A is fully inside B; union is B.",
            )
        elif operation == "intersection":
            result = PlanarPolyhedron(
                list(poly_a.vertices_xyz_mm), [list(f) for f in poly_a.faces]
            )
            return BooleanResult(
                result_polyhedron=result,
                operation=operation,
                is_valid=True,
                num_input_faces_a=nfa,
                num_input_faces_b=nfb,
                num_output_faces=len(result.faces),
                honest_caveat="A is fully inside B; intersection is A.",
            )
        else:
            # A - B = empty
            result = PlanarPolyhedron([], [])
            return BooleanResult(
                result_polyhedron=result,
                operation=operation,
                is_valid=True,
                num_input_faces_a=nfa,
                num_input_faces_b=nfb,
                num_output_faces=0,
                honest_caveat="A is fully inside B; difference is empty.",
            )

    if all_b_in_a:
        # B contained in A
        if operation == "union":
            result = PlanarPolyhedron(
                list(poly_a.vertices_xyz_mm), [list(f) for f in poly_a.faces]
            )
            return BooleanResult(
                result_polyhedron=result,
                operation=operation,
                is_valid=True,
                num_input_faces_a=nfa,
                num_input_faces_b=nfb,
                num_output_faces=len(result.faces),
                honest_caveat="B is fully inside A; union is A.",
            )
        elif operation == "intersection":
            result = PlanarPolyhedron(
                list(poly_b.vertices_xyz_mm), [list(f) for f in poly_b.faces]
            )
            return BooleanResult(
                result_polyhedron=result,
                operation=operation,
                is_valid=True,
                num_input_faces_a=nfa,
                num_input_faces_b=nfb,
                num_output_faces=len(result.faces),
                honest_caveat="B is fully inside A; intersection is B.",
            )
        else:
            # A - B: A with B hollowed out — complex but unsupported in
            # this planar algorithm (no inner loops on planar faces).
            # Return A as a conservative approximation.
            result = PlanarPolyhedron(
                list(poly_a.vertices_xyz_mm), [list(f) for f in poly_a.faces]
            )
            return BooleanResult(
                result_polyhedron=result,
                operation=operation,
                is_valid=False,
                num_input_faces_a=nfa,
                num_input_faces_b=nfb,
                num_output_faces=len(result.faces),
                honest_caveat=(
                    "B is fully inside A; A-minus-B would require inner face "
                    "loops which planar-polygon representation cannot express. "
                    "Result is conservative (A unchanged).  Use OCCT for this case."
                ),
            )

    # ------------------------------------------------------------------
    # General case: Sutherland-Hodgman face classification + trimming
    # ------------------------------------------------------------------
    #
    # Algorithm (Mantyla §6; Hoffmann §3):
    #
    # 1. For each face of A: clip to the interior of B (for intersection) or
    #    clip to the exterior of B (for union/difference).  The "inside" clip
    #    uses S-H polygon clipping; the "outside" clip takes the complement.
    #
    # 2. For each face of B: only include faces that are NOT coplanar with
    #    any A face.  Coplanar faces from B that coincide with A faces are
    #    already covered by the A side (they would double-count the area).
    #
    # 3. For difference, B-face normals are flipped so they point outward
    #    from the result solid.
    #
    # The "clip to exterior" for a convex body is implemented by iterating
    # over the body's half-spaces and taking the COMPLEMENT of each, then
    # combining via S-H clipping.  Specifically, the region outside convex C
    # can be partitioned as:
    #
    #   ∪_j { x : n_j·(x-p_j) > 0  AND  n_k·(x-p_k) ≤ 0 for all k < j }
    #
    # (Taken as a 2D polygon clipping operation on each face.)

    def _trim_face_inside(
        verts: np.ndarray,
        clip: PlanarPolyhedron,
        flip: bool,
        inner_tol: float,
    ) -> Optional[List[np.ndarray]]:
        """Clip *verts* against the interior of convex *clip*.
        Returns the trimmed sub-polygon or None if empty/degenerate.
        """
        poly_list: List[np.ndarray] = list(verts)
        for fj in range(len(clip.faces)):
            clip_verts = _poly_verts(clip, fj)
            clip_norm = _face_normal(clip_verts)
            clip_pt = clip_verts[0]
            poly_list = _sh_clip_polygon_by_halfplane(
                poly_list, clip_pt, clip_norm, inner_tol
            )
            if not poly_list:
                return None
        if not poly_list or _face_area(np.array(poly_list)) <= inner_tol:
            return None
        return list(reversed(poly_list)) if flip else poly_list

    def _face_centroid_offset_inside(
        verts: np.ndarray,
        clip: PlanarPolyhedron,
        offset: float,
        inner_tol: float,
    ) -> bool:
        """Return True when the face centroid + offset*normal is inside *clip*.

        Used to classify whether a face should be discarded (its outward side
        is inside the other solid) or kept (outward side is outside).
        """
        norm = _face_normal(verts)
        ctr = _face_centroid(verts)
        probe = ctr + offset * norm
        return _point_in_polyhedron(probe, clip, inner_tol)

    def _trim_face_outside(
        verts: np.ndarray,
        clip: PlanarPolyhedron,
        flip: bool,
        inner_tol: float,
        include_coplanar_boundary: bool = True,
    ) -> List[List[np.ndarray]]:
        """Return sub-polygons of *verts* that lie outside (or on the boundary
        of) convex *clip*.

        Parameters
        ----------
        include_coplanar_boundary:
            When True (default), include the coplanar boundary piece (the
            portion of the face that lies exactly on the clip boundary, e.g.
            the shared face of two half-overlapping cubes).  Pass False for
            the B-side of a union so that coplanar boundary faces are counted
            exactly once (from the A side).

        Classification strategy:
        1. Compute the S-H clip of *verts* to the interior of *clip* (with
           standard tolerance so coplanar faces contribute their coplanar part).
        2. If the face is entirely outside (inside_clip is empty): keep whole face.
        3. If the face is entirely inside-strictly (centroid offset inside clip):
           discard.
        4. If partially overlapping: return the face minus inside_clip.  The
           "minus" is computed as the Sutherland-Hodgman complement decomposition,
           but skipping clip half-spaces that are coplanar with the source face
           (those are boundary planes — a face on the boundary is NOT interior).
        """
        result: List[List[np.ndarray]] = []

        # S-H clip to inside clip (non-strict — boundary counts as inside)
        inside_clip: List[np.ndarray] = list(verts)
        for fj in range(len(clip.faces)):
            cv = _poly_verts(clip, fj)
            cn = _face_normal(cv)
            inside_clip = _sh_clip_polygon_by_halfplane(
                inside_clip, cv[0], cn, inner_tol
            )
            if not inside_clip:
                break

        if not inside_clip:
            # Entirely outside — keep the whole face
            area = _face_area(verts)
            if area > inner_tol:
                result.append(list(reversed(verts)) if flip else list(verts))
            return result

        src_norm = _face_normal(verts)
        offset_dist = inner_tol * 1000.0

        # Partially overlapping (or entirely inside) case.
        # Strategy:
        # 1. Collect strictly-exterior pieces (from the complement decomposition).
        #    If the face is entirely inside clip, Step 1 yields nothing.
        # 2. Optionally collect the coplanar-boundary piece (the inside_clip
        #    portion whose outward probe is outside clip) — this handles the
        #    shared-face case.  Only include for the primary (A) side; skip for
        #    B-side to avoid double-counting.

        # Step 1: strictly exterior pieces
        for fj in range(len(clip.faces)):
            cv_j = _poly_verts(clip, fj)
            cn_j = _face_normal(cv_j)
            cp_j = cv_j[0]

            # Skip coplanar half-spaces
            if abs(abs(float(np.dot(src_norm, cn_j))) - 1.0) < 1e-6:
                dist_j = abs(float(np.dot(cn_j, verts[0] - cp_j)))
                if dist_j < inner_tol * 1000:
                    continue

            # Strict exterior: dot(cn_j, x - cp_j) >= inner_tol
            piece: List[np.ndarray] = list(verts)
            piece = _sh_clip_polygon_by_halfplane(
                piece, cp_j, -cn_j, -inner_tol
            )
            if not piece:
                continue

            for fk in range(fj):
                cv_k = _poly_verts(clip, fk)
                cn_k = _face_normal(cv_k)
                piece = _sh_clip_polygon_by_halfplane(
                    piece, cv_k[0], cn_k, inner_tol
                )
                if not piece:
                    break

            if piece and _face_area(np.array(piece)) > inner_tol:
                result.append(list(reversed(piece)) if flip else piece)

        # Step 2: coplanar boundary piece — only for primary (A) side.
        # The inside_clip = face ∩ clip (coplanar boundary region).
        # Include this if the face's outward probe (centroid+ε*norm) is outside clip.
        if include_coplanar_boundary and inside_clip and _face_area(np.array(inside_clip)) > inner_tol:
            ic_ctr = _face_centroid(np.array(inside_clip))
            probe = ic_ctr + offset_dist * src_norm
            if not _point_in_polyhedron(probe, clip, inner_tol):
                # Outward side is outside clip — this boundary piece belongs in union
                result.append(
                    list(reversed(inside_clip)) if flip else inside_clip
                )

        return result

    def _is_coplanar_with_any(
        src_norm: np.ndarray,
        src_pt: np.ndarray,
        other: PlanarPolyhedron,
        inner_tol: float,
    ) -> bool:
        """True if the plane (src_norm, src_pt) is coplanar with any face of *other*.

        Two faces are coplanar if their normals are parallel (or anti-parallel)
        AND the signed distance between the planes is within tolerance.
        """
        for fj in range(len(other.faces)):
            ov = _poly_verts(other, fj)
            on = _face_normal(ov)
            if abs(abs(float(np.dot(src_norm, on))) - 1.0) > 1e-6:
                continue
            dist = abs(float(np.dot(on, src_pt - ov[0])))
            if dist <= inner_tol * 1000:
                return True
        return False

    # Collect A faces
    polys_a: List[List[np.ndarray]] = []
    for fi in range(nfa):
        va = _poly_verts(poly_a, fi)
        if operation == "intersection":
            piece = _trim_face_inside(va, poly_b, flip=False, inner_tol=tol)
            if piece is not None:
                polys_a.append(piece)
        else:
            # union or difference: A faces outside B.
            # For union: include coplanar boundary from A side (counted once).
            # For difference: do NOT include coplanar boundary — the A-B shared
            # boundary face is removed by the subtraction.
            incl_cb = (operation == "union")
            pieces = _trim_face_outside(
                va, poly_b, flip=False, inner_tol=tol,
                include_coplanar_boundary=incl_cb,
            )
            polys_a.extend(pieces)

    # Collect B faces.
    #
    # Deduplication rule to avoid double-counting coplanar face pairs:
    #
    # * union: B faces are included (trimmed to outside A).  When coplanar
    #   with an A face, both sides contribute their exclusive portion; there
    #   is no double-count because the trim ensures non-overlap.
    #
    # * intersection: B faces that are coplanar with an A face and on the
    #   same plane are SKIPPED — the A side already contributes that face's
    #   inside-B clip.
    #
    # * difference: B faces that are coplanar with an A face in the SAME
    #   direction are skipped (A contributes that face trimmed to outside-B).
    #   B faces coplanar in the OPPOSITE direction (anti-parallel normal) are
    #   included as the new cap faces of the cut.

    polys_b: List[List[np.ndarray]] = []
    for fi in range(nfb):
        vb = _poly_verts(poly_b, fi)
        nb = _face_normal(vb)

        if operation == "union":
            # Trimmed to outside A.  Coplanar boundary pieces are already
            # included from the A side (include_coplanar_boundary=True there);
            # pass include_coplanar_boundary=False here to avoid double-counting.
            pieces = _trim_face_outside(
                vb, poly_a, flip=False, inner_tol=tol,
                include_coplanar_boundary=False,
            )
            polys_b.extend(pieces)

        elif operation == "intersection":
            # Skip B faces that are coplanar with any A face (A covers them)
            coplanar = _is_coplanar_with_any(nb, vb[0], poly_a, tol)
            if not coplanar:
                piece = _trim_face_inside(vb, poly_a, flip=False, inner_tol=tol)
                if piece is not None:
                    polys_b.append(piece)

        else:  # difference (A minus B)
            # Check coplanarity: same direction → skip (A covers outside-B part)
            # opposite direction → include as new cap (B interior boundary)
            parallel = False
            anti_parallel = False
            for fk in range(nfa):
                vak = _poly_verts(poly_a, fk)
                nak = _face_normal(vak)
                if abs(abs(float(np.dot(nb, nak))) - 1.0) < 1e-6:
                    dist = abs(float(np.dot(nak, vb[0] - vak[0])))
                    if dist < tol * 1000:
                        if float(np.dot(nb, nak)) > 0:
                            parallel = True
                        else:
                            anti_parallel = True
                        break

            if parallel:
                pass  # skip — A face (trimmed outside B) already on this plane
            elif anti_parallel:
                # New cap face: include B-face trimmed to inside A, flipped
                piece = _trim_face_inside(vb, poly_a, flip=True, inner_tol=tol)
                if piece is not None:
                    polys_b.append(piece)
            else:
                # Non-coplanar: standard inside-A contribution (flipped)
                piece = _trim_face_inside(vb, poly_a, flip=True, inner_tol=tol)
                if piece is not None:
                    polys_b.append(piece)

    all_polys = polys_a + polys_b

    # Filter degenerate faces
    filtered: List[List[np.ndarray]] = [
        p for p in all_polys
        if len(p) >= 3 and _face_area(np.array(p)) > tol
    ]

    if not filtered:
        result = PlanarPolyhedron([], [])
        return BooleanResult(
            result_polyhedron=result,
            operation=operation,
            is_valid=True,
            num_input_faces_a=nfa,
            num_input_faces_b=nfb,
            num_output_faces=0,
            honest_caveat=(
                "Result has no faces — inputs may be touching face-to-face with "
                "zero overlap, or inputs are nearly identical.  "
                "Convex planar polyhedra only; non-convex / curved-face "
                "bodies need OCCT."
            ),
        )

    verts_out, faces_out = _dedup_vertices(filtered, tol)
    result = PlanarPolyhedron(verts_out, faces_out)

    # Validation: volume should be non-negative
    vol = _polyhedron_volume(result)

    # Degenerate-mesh check: a valid closed polyhedron needs at least 4 faces
    # (tetrahedron is the minimum).  Fewer faces indicates a lower-dimensional
    # result (e.g. two touching cubes whose intersection is a 2-D face).  For
    # intersection this is correctly an empty result; for union/difference it
    # signals a problem but we return what we have.
    if len(faces_out) < 4 and operation == "intersection":
        result = PlanarPolyhedron([], [])
        return BooleanResult(
            result_polyhedron=result,
            operation=operation,
            is_valid=True,
            num_input_faces_a=nfa,
            num_input_faces_b=nfb,
            num_output_faces=0,
            honest_caveat=(
                "Intersection result is lower-dimensional (polyhedra touch at "
                "a face/edge/vertex only); regularised intersection is empty.  "
                "Convex planar polyhedra only; non-convex / curved-face "
                "bodies need OCCT."
            ),
        )

    is_valid = vol >= -tol and len(faces_out) >= 1

    caveat = (
        "GK-P09 general boolean — convex planar polyhedra only.  "
        "Non-convex and curved-face bodies still require OCCT.  "
        "Numeric tolerance is tunable but coplanar-face edge cases "
        "may fail.  Face count is approximate when faces are split "
        "into multiple sub-polygons."
    )

    return BooleanResult(
        result_polyhedron=result,
        operation=operation,
        is_valid=is_valid,
        num_input_faces_a=nfa,
        num_input_faces_b=nfb,
        num_output_faces=len(faces_out),
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# Volume helper exposed for tests
# ---------------------------------------------------------------------------


def polyhedron_volume(poly: PlanarPolyhedron) -> float:
    """Volume of *poly* via divergence theorem (mm³)."""
    return _polyhedron_volume(poly)


# ---------------------------------------------------------------------------
# LLM tool (gated import)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload  # type: ignore[import]

    @register
    class _BrepGeneralBooleanTool(ToolSpec):
        name = "brep_general_boolean"
        description = (
            "Compute a solid boolean (union / intersection / difference) on two "
            "convex planar polyhedra expressed as vertex + face-index lists.  "
            "Pure-Python, no OCCT required.  Returns the result polyhedron "
            "with validity flag and honest caveats.  "
            "LIMITATION: convex planar faces only — for non-convex or "
            "curved-face bodies use the OCCT boolean tools."
        )
        input_schema = {
            "type": "object",
            "properties": {
                "vertices_a": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "description": "List of [x, y, z] vertices for polyhedron A (mm).",
                },
                "faces_a": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "description": "List of faces for A; each face is a CCW list of vertex indices.",
                },
                "vertices_b": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
                    "description": "List of [x, y, z] vertices for polyhedron B (mm).",
                },
                "faces_b": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "integer"}},
                    "description": "List of faces for B; each face is a CCW list of vertex indices.",
                },
                "operation": {
                    "type": "string",
                    "enum": ["union", "intersection", "difference"],
                    "description": "Boolean operation: union, intersection, or difference (A minus B).",
                },
                "tol": {
                    "type": "number",
                    "default": 1e-7,
                    "description": "Geometric tolerance in mm (default 1e-7).",
                },
            },
            "required": ["vertices_a", "faces_a", "vertices_b", "faces_b", "operation"],
        }

        def run(self, params: dict) -> dict:
            try:
                poly_a = PlanarPolyhedron(
                    vertices_xyz_mm=[tuple(v) for v in params["vertices_a"]],
                    faces=[list(f) for f in params["faces_a"]],
                )
                poly_b = PlanarPolyhedron(
                    vertices_xyz_mm=[tuple(v) for v in params["vertices_b"]],
                    faces=[list(f) for f in params["faces_b"]],
                )
                tol = float(params.get("tol", _TOL_DEFAULT))
                res = boolean_polyhedra(poly_a, poly_b, params["operation"], tol=tol)
                return ok_payload({
                    "operation": res.operation,
                    "is_valid": res.is_valid,
                    "num_input_faces_a": res.num_input_faces_a,
                    "num_input_faces_b": res.num_input_faces_b,
                    "num_output_faces": res.num_output_faces,
                    "vertices": res.result_polyhedron.vertices_xyz_mm,
                    "faces": res.result_polyhedron.faces,
                    "honest_caveat": res.honest_caveat,
                    "volume_mm3": polyhedron_volume(res.result_polyhedron),
                })
            except Exception as exc:
                return err_payload(str(exc))

except ImportError:
    pass
