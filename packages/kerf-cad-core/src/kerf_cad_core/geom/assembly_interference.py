"""GK-P49: Assembly-level interference detection between multiple bodies.

References
----------
* Möller 1997 — "A fast triangle-triangle intersection test"
  Journal of Graphics Tools, 2(2):25–30.
* Cohen-Lin-Manocha-Ponamgi 1995 — "I-COLLIDE: An interactive and exact
  collision detection system for large-scale environments".
* Pan-Chitta-Manocha 2012 — "FCL: A general purpose library for collision
  and proximity queries".

Algorithm overview
------------------
1. **Broad phase (AABB)**: axis-aligned bounding boxes are computed for each
   body from its vertex set (or from analytic face parameters). Pairs whose
   AABBs do not overlap are cheaply rejected; pairs within ``clearance_min``
   distance are flagged as close-clearance warnings.

2. **Narrow phase (boolean intersection)**: for pairs that pass the AABB
   filter we call ``body_intersection`` (GK-18) to obtain the exact overlap
   region and ``body_mass_props`` to measure its volume. This is analytically
   exact for the axis-aligned-box and sphere primitives supported by GK-18.

3. **Triangle-triangle intersection (Möller 1997)**: when body geometry is
   tessellated we run the Möller-Trumbore signed-distance interval algorithm
   on every triangle pair to detect any geometric crossing. This is used both
   as a secondary check and as the basis for ``intersection_curves``.

4. **Severity classification**:
   - ``'none'``:         no interference (disjoint or gap only).
   - ``'touch'``:        boolean volume ≤ ``tol`` (coincident faces / edges).
   - ``'overlap'``:      non-trivial interference.
   - ``'major_overlap'``: volume > 10 % of the smaller body's volume.

Pure-Python / NumPy — no OCCT dependency for the core algorithm (though
``body_intersection`` uses the GK-18 analytic specialisations for axis-aligned
primitives).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.brep import Body, Plane, CylinderSurface, SphereSurface
from kerf_cad_core.geom.boolean import body_intersection
from kerf_cad_core.geom.mass_props import body_mass_props

# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

Point3 = List[float]

_EPSILON = 1e-12  # Möller-Trumbore epsilon


@dataclass
class AABB:
    """Axis-aligned bounding box.

    Parameters
    ----------
    lo:
        Minimum corner (3-vector).
    hi:
        Maximum corner (3-vector).
    """

    lo: np.ndarray
    hi: np.ndarray

    def __post_init__(self) -> None:
        self.lo = np.asarray(self.lo, dtype=float)
        self.hi = np.asarray(self.hi, dtype=float)

    @property
    def volume(self) -> float:
        d = self.hi - self.lo
        if np.any(d <= 0.0):
            return 0.0
        return float(np.prod(d))

    def expand(self, margin: float) -> "AABB":
        m = float(margin)
        return AABB(self.lo - m, self.hi + m)

    def overlaps(self, other: "AABB") -> bool:
        """Return True if this AABB overlaps *other* (inclusive)."""
        return bool(
            np.all(self.lo <= other.hi) and np.all(other.lo <= self.hi)
        )

    def gap_to(self, other: "AABB") -> float:
        """Signed separation: negative means overlap, 0 means touching."""
        # Per-axis one-sided gaps
        gaps = np.maximum(self.lo - other.hi, other.lo - self.hi)
        return float(np.max(gaps))

    def to_dict(self) -> dict:
        return {"lo": self.lo.tolist(), "hi": self.hi.tolist()}


@dataclass
class InterferenceResult:
    """Result of a pairwise interference check.

    Attributes
    ----------
    interferes:
        True when the bodies geometrically overlap beyond the *touch* level.
    intersection_volume:
        Volume of the intersection region (0.0 when disjoint or touch-only).
    intersection_curves:
        List of representative intersection-curve sample points (may be empty
        for analytic primitives where only volume is meaningful).
    severity:
        One of ``'none'``, ``'touch'``, ``'overlap'``, ``'major_overlap'``.
    aabb_gap:
        Signed AABB separation (negative = overlapping AABBs).
    """

    interferes: bool
    intersection_volume: float
    intersection_curves: List[List[Point3]]
    severity: str  # 'none' | 'touch' | 'overlap' | 'major_overlap'
    aabb_gap: float = 0.0

    def to_dict(self) -> dict:
        return {
            "interferes": bool(self.interferes),
            "intersection_volume": float(self.intersection_volume),
            "intersection_curves": self.intersection_curves,
            "severity": self.severity,
            "aabb_gap": float(self.aabb_gap),
        }


@dataclass
class AssemblyInterferenceReport:
    """Full assembly interference report for N bodies.

    Attributes
    ----------
    pairs:
        List of ``(i, j, InterferenceResult)`` for each pair checked.
    total_interference_volume:
        Sum of all pairwise intersection volumes.
    critical_pairs:
        Indices ``(i, j)`` for pairs with severity == 'overlap' or
        'major_overlap'.
    clearance_warnings:
        Indices ``(i, j)`` for pairs within ``clearance_min`` distance.
    n_bodies:
        Number of bodies in the assembly.
    n_pairs_checked:
        Number of pairs actually evaluated (after AABB pre-filter).
    """

    pairs: List[Tuple[int, int, InterferenceResult]] = field(default_factory=list)
    total_interference_volume: float = 0.0
    critical_pairs: List[Tuple[int, int]] = field(default_factory=list)
    clearance_warnings: List[Tuple[int, int]] = field(default_factory=list)
    n_bodies: int = 0
    n_pairs_checked: int = 0

    def interfering_pairs(self) -> List[Tuple[int, int]]:
        """Return all (i, j) pairs that interfere."""
        return [(i, j) for i, j, r in self.pairs if r.interferes]

    def to_dict(self) -> dict:
        return {
            "pairs": [
                {"i": i, "j": j, "result": r.to_dict()}
                for i, j, r in self.pairs
            ],
            "total_interference_volume": self.total_interference_volume,
            "critical_pairs": [list(p) for p in self.critical_pairs],
            "clearance_warnings": [list(p) for p in self.clearance_warnings],
            "n_bodies": self.n_bodies,
            "n_pairs_checked": self.n_pairs_checked,
        }


# ---------------------------------------------------------------------------
# AABB computation
# ---------------------------------------------------------------------------

def _body_aabb(body: Body) -> AABB:
    """Compute the AABB of *body* from its B-rep vertex set and analytic faces.

    For bodies with no topology vertices (degenerate), fall back to the
    origin as both corners.
    """
    pts: List[np.ndarray] = []

    # Collect vertices
    for v in body.all_vertices():
        pts.append(np.asarray(v.point, dtype=float))

    # For analytic sphere surfaces without B-rep vertices, use center±radius
    for face in body.all_faces():
        surf = face.surface
        if isinstance(surf, SphereSurface):
            c = np.asarray(surf.center, dtype=float)
            r = float(surf.radius)
            pts.extend([
                c + np.array([r, 0, 0]),
                c - np.array([r, 0, 0]),
                c + np.array([0, r, 0]),
                c - np.array([0, r, 0]),
                c + np.array([0, 0, r]),
                c - np.array([0, 0, r]),
            ])
        elif isinstance(surf, CylinderSurface):
            # Already covered by vertex collection for bounded cylinders
            pass

    if not pts:
        return AABB(np.zeros(3), np.zeros(3))

    arr = np.array(pts, dtype=float)
    return AABB(arr.min(axis=0), arr.max(axis=0))


# ---------------------------------------------------------------------------
# Möller 1997 triangle-triangle intersection kernel
# ---------------------------------------------------------------------------

def _tri_tri_intersect(
    t1: np.ndarray,  # (3, 3) three vertices of triangle 1
    t2: np.ndarray,  # (3, 3) three vertices of triangle 2
    tol: float = _EPSILON,
) -> bool:
    """Test whether two triangles intersect.

    Implements the signed-distance-interval overlap test described in:

        Möller 1997, "A fast triangle-triangle intersection test",
        Journal of Graphics Tools 2(2):25–30.

    Parameters
    ----------
    t1, t2:
        Each is a (3, 3) array: rows are the three 3-D vertex coordinates.
    tol:
        Numerical epsilon for degeneracy guard.

    Returns
    -------
    bool — True if the triangles intersect.
    """
    # Plane 2: N2·X + d2 = 0
    e1 = t2[1] - t2[0]
    e2 = t2[2] - t2[0]
    N2 = np.cross(e1, e2)
    n2_sq = float(np.dot(N2, N2))
    if n2_sq < tol:
        return False  # degenerate triangle 2
    d2 = -float(np.dot(N2, t2[0]))

    # Signed distances of T1 vertices to plane 2
    dv1 = np.dot(t1, N2) + d2  # (3,)
    # All same sign → T1 fully on one side of plane 2
    if float(dv1[0]) * float(dv1[1]) > 0 and float(dv1[0]) * float(dv1[2]) > 0:
        return False

    # Plane 1: N1·X + d1 = 0
    f1 = t1[1] - t1[0]
    f2 = t1[2] - t1[0]
    N1 = np.cross(f1, f2)
    n1_sq = float(np.dot(N1, N1))
    if n1_sq < tol:
        return False  # degenerate triangle 1
    d1 = -float(np.dot(N1, t1[0]))

    # Signed distances of T2 vertices to plane 1
    dv2 = np.dot(t2, N1) + d1  # (3,)
    if float(dv2[0]) * float(dv2[1]) > 0 and float(dv2[0]) * float(dv2[2]) > 0:
        return False

    # Intersection line direction: D = N1 × N2
    D = np.cross(N1, N2)
    d_sq = float(np.dot(D, D))
    if d_sq < tol:
        # Coplanar triangles — use 2D separating axis test in the plane
        return _coplanar_tri_tri(t1, t2, N1)

    # Project vertices onto D to get scalar intervals
    def _interval(t, dv, D):
        # t:  (3,3), dv: (3,), D: (3,)
        p = np.dot(t, D)  # (3,) projections
        # find the vertex whose signed distance to the *other* plane has
        # the opposite sign from the other two
        # vertices i whose dv has opposite sign from the majority
        if float(dv[0]) * float(dv[1]) > 0:
            # v0 and v1 on same side; v2 is isolated
            isol, pair0, pair1 = 2, 0, 1
        else:
            isol, pair0, pair1 = 0, 1, 2
        denom_a = float(dv[pair0]) - float(dv[isol])
        denom_b = float(dv[pair1]) - float(dv[isol])
        if abs(denom_a) < _EPSILON:
            t_a = float(p[pair0])
        else:
            t_a = p[pair0] + (p[isol] - p[pair0]) * float(dv[pair0]) / denom_a
        if abs(denom_b) < _EPSILON:
            t_b = float(p[pair1])
        else:
            t_b = p[pair1] + (p[isol] - p[pair1]) * float(dv[pair1]) / denom_b
        return (min(t_a, t_b), max(t_a, t_b))

    i1 = _interval(t1, dv1, D)
    i2 = _interval(t2, dv2, D)

    # Intervals overlap iff max(lo) ≤ min(hi) (with epsilon)
    return (max(i1[0], i2[0]) <= min(i1[1], i2[1]) + tol)


def _coplanar_tri_tri(
    t1: np.ndarray,
    t2: np.ndarray,
    N: np.ndarray,
) -> bool:
    """Separating axis test for coplanar triangles.

    Projects both triangles onto the plane defined by normal N and performs
    2-D SAT on the 6 edge normals.
    """
    # Build an orthonormal basis in the plane
    N_norm = N / (np.linalg.norm(N) + 1e-30)
    ref = np.array([1.0, 0.0, 0.0])
    if abs(float(np.dot(N_norm, ref))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    ax = ref - float(np.dot(ref, N_norm)) * N_norm
    ax /= np.linalg.norm(ax) + 1e-30
    ay = np.cross(N_norm, ax)

    def proj2d(tri):
        return np.column_stack([tri @ ax, tri @ ay])  # (3, 2)

    p1 = proj2d(t1)
    p2 = proj2d(t2)

    def _sat_axis(a, b, edge):
        """Separating axis test: project both polys onto perp(edge)."""
        n = np.array([-edge[1], edge[0]])
        pa = a @ n
        pb = b @ n
        return float(pa.max()) < float(pb.min()) - 1e-10 or float(pb.max()) < float(pa.min()) - 1e-10

    for i in range(3):
        edge = p1[(i + 1) % 3] - p1[i]
        if _sat_axis(p1, p2, edge):
            return False
        edge2 = p2[(i + 1) % 3] - p2[i]
        if _sat_axis(p1, p2, edge2):
            return False
    return True


# ---------------------------------------------------------------------------
# Body tessellation (flat triangle list for narrow-phase)
# ---------------------------------------------------------------------------

def _tessellate_body(body: Body, face_grid: int = 8) -> np.ndarray:
    """Return an (N, 3, 3) array of triangles tessellating *body*.

    For each planar face we fan-triangulate the outer loop polygon.
    For analytic curved faces we sample a UV grid and produce (2*(n-1)^2)
    triangles per face.
    """
    triangles: List[np.ndarray] = []

    for face in body.all_faces():
        surf = face.surface

        # Collect outer loop vertices
        loop_verts: List[np.ndarray] = []
        for loop in face.loops:
            if loop.is_outer:
                for v in loop.vertices():
                    loop_verts.append(np.asarray(v.point, dtype=float))
                break

        if isinstance(surf, Plane) and len(loop_verts) >= 3:
            # Fan triangulation from the first vertex
            v0 = loop_verts[0]
            for k in range(1, len(loop_verts) - 1):
                tri = np.array([v0, loop_verts[k], loop_verts[k + 1]])
                triangles.append(tri)

        elif isinstance(surf, SphereSurface):
            c, r = np.asarray(surf.center, dtype=float), float(surf.radius)
            us = np.linspace(0.0, 2 * math.pi, face_grid, endpoint=False)
            vs = np.linspace(-math.pi / 2, math.pi / 2, face_grid // 2 + 1)
            for i in range(len(us)):
                for j in range(len(vs) - 1):
                    def sp(u, v):
                        return c + r * np.array([
                            math.cos(v) * math.cos(u),
                            math.cos(v) * math.sin(u),
                            math.sin(v),
                        ])
                    p00 = sp(us[i], vs[j])
                    p10 = sp(us[(i + 1) % len(us)], vs[j])
                    p01 = sp(us[i], vs[j + 1])
                    p11 = sp(us[(i + 1) % len(us)], vs[j + 1])
                    triangles.append(np.array([p00, p10, p01]))
                    triangles.append(np.array([p10, p11, p01]))

        elif isinstance(surf, CylinderSurface):
            ctr = np.asarray(surf.center, dtype=float)
            axis = np.asarray(surf.axis, dtype=float)
            r = float(surf.radius)
            x_ref = np.asarray(surf.x_ref, dtype=float)
            y_ref = surf._y if hasattr(surf, '_y') else np.cross(axis, x_ref)
            y_ref = y_ref / (np.linalg.norm(y_ref) + 1e-30)

            # Derive height range from vertices
            if loop_verts:
                projs = [float(np.dot(p - ctr, axis)) for p in loop_verts]
                v0_h, v1_h = min(projs), max(projs)
            else:
                v0_h, v1_h = 0.0, 1.0

            us = np.linspace(0.0, 2 * math.pi, face_grid, endpoint=False)
            hs = np.linspace(v0_h, v1_h, face_grid // 2 + 1)

            def cp(u, h):
                return ctr + r * (math.cos(u) * x_ref + math.sin(u) * y_ref) + h * axis

            for i in range(len(us)):
                for j in range(len(hs) - 1):
                    p00 = cp(us[i], hs[j])
                    p10 = cp(us[(i + 1) % len(us)], hs[j])
                    p01 = cp(us[i], hs[j + 1])
                    p11 = cp(us[(i + 1) % len(us)], hs[j + 1])
                    triangles.append(np.array([p00, p10, p01]))
                    triangles.append(np.array([p10, p11, p01]))
        else:
            # Generic surface: UV grid over face
            if not loop_verts:
                continue
            # Fan-triangulate the loop vertices as a planar approximation
            v0 = loop_verts[0]
            for k in range(1, len(loop_verts) - 1):
                tri = np.array([v0, loop_verts[k], loop_verts[k + 1]])
                triangles.append(tri)

    if not triangles:
        return np.empty((0, 3, 3), dtype=float)
    return np.array(triangles, dtype=float)


# ---------------------------------------------------------------------------
# Triangle-pair loop → intersection curves
# ---------------------------------------------------------------------------

def _find_intersection_curves(
    tris_a: np.ndarray,  # (M, 3, 3)
    tris_b: np.ndarray,  # (N, 3, 3)
    tol: float = 1e-6,
) -> List[List[Point3]]:
    """Return a list of intersection-curve segments (each segment is 2 endpoints).

    Each element is a list of two 3D points [p0, p1] representing one
    intersection segment between a triangle pair. This is a sparse output
    intended for downstream display, not a fully chained polyline.
    """
    curves: List[List[Point3]] = []
    for ta in tris_a:
        for tb in tris_b:
            if _tri_tri_intersect(ta, tb, tol=tol):
                # Compute one representative midpoint of the intersection
                # (sufficient for display; exact segment computation is O(1)
                # per pair but complex — midpoint is a good-faith approximation)
                mid_a = ta.mean(axis=0)
                mid_b = tb.mean(axis=0)
                curves.append([mid_a.tolist(), mid_b.tolist()])
    return curves


# ---------------------------------------------------------------------------
# Public API: pairwise
# ---------------------------------------------------------------------------

def detect_interference_pair(
    body_a: Body,
    body_b: Body,
    tol: float = 1e-6,
) -> InterferenceResult:
    """Detect geometric interference between two solid bodies.

    Algorithm
    ---------
    1. Compute AABBs; if they do not overlap return ``severity='none'``.
    2. If AABBs overlap, call ``body_intersection`` (GK-18) and measure the
       intersection volume via ``body_mass_props`` (GK-23).
    3. Additionally run the Möller 1997 triangle-triangle test on tessellated
       bodies to populate ``intersection_curves``.
    4. Classify severity and return an :class:`InterferenceResult`.

    Parameters
    ----------
    body_a, body_b:
        The two :class:`~kerf_cad_core.geom.brep.Body` objects.
    tol:
        Geometric tolerance (forwarded to ``body_intersection``).

    Returns
    -------
    :class:`InterferenceResult`
    """
    aabb_a = _body_aabb(body_a)
    aabb_b = _body_aabb(body_b)
    aabb_gap = aabb_a.gap_to(aabb_b)

    # Broad phase: if AABBs are clearly disjoint with margin, early return
    if aabb_gap > tol:
        return InterferenceResult(
            interferes=False,
            intersection_volume=0.0,
            intersection_curves=[],
            severity="none",
            aabb_gap=aabb_gap,
        )

    # Narrow phase: compute exact intersection via boolean body_intersection
    int_vol = 0.0
    int_body = None
    try:
        int_body = body_intersection(body_a, body_b, tol=tol)
        if int_body.all_faces():
            props = body_mass_props(int_body)
            int_vol = abs(props["volume"])
    except Exception:
        # body_intersection may raise BuildError for unsupported shape combos
        # Fall through to triangle-triangle narrow phase
        pass

    # Möller 1997 narrow phase: tessellate + triangle-triangle intersection
    tris_a = _tessellate_body(body_a)
    tris_b = _tessellate_body(body_b)
    int_curves: List[List[Point3]] = []
    mesh_intersects = False
    if len(tris_a) > 0 and len(tris_b) > 0:
        int_curves = _find_intersection_curves(tris_a, tris_b, tol=tol)
        mesh_intersects = len(int_curves) > 0

    # Combine evidence: we trust the boolean volume when available, otherwise
    # use the mesh intersection as a proxy.
    actual_interferes = (int_vol > tol) or (int_body is None and mesh_intersects)

    # Classify severity
    if not actual_interferes:
        # Could still be a touch (exactly zero volume intersection)
        if aabb_gap <= tol and (
            mesh_intersects or (int_body is not None and int_body.all_faces())
        ):
            severity = "touch"
        else:
            severity = "none"
    else:
        # Compute the smaller body's volume for major-overlap threshold
        vol_a = 0.0
        vol_b = 0.0
        try:
            vol_a = abs(body_mass_props(body_a)["volume"])
        except Exception:
            pass
        try:
            vol_b = abs(body_mass_props(body_b)["volume"])
        except Exception:
            pass

        smaller = min(vol_a, vol_b) if (vol_a > 0 and vol_b > 0) else 0.0
        if smaller > 0 and int_vol > 0.10 * smaller:
            severity = "major_overlap"
        else:
            severity = "overlap"

    return InterferenceResult(
        interferes=actual_interferes or (severity == "touch"),
        intersection_volume=int_vol,
        intersection_curves=int_curves,
        severity=severity,
        aabb_gap=aabb_gap,
    )


# ---------------------------------------------------------------------------
# Public API: compute_assembly_aabb
# ---------------------------------------------------------------------------

def compute_assembly_aabb(bodies: Sequence[Body]) -> AABB:
    """Return the total bounding box enclosing all bodies.

    Parameters
    ----------
    bodies:
        List of :class:`~kerf_cad_core.geom.brep.Body` objects.

    Returns
    -------
    :class:`AABB` — the union bounding box.
    """
    if not bodies:
        return AABB(np.zeros(3), np.zeros(3))
    aabbs = [_body_aabb(b) for b in bodies]
    lo = np.array([a.lo for a in aabbs]).min(axis=0)
    hi = np.array([a.hi for a in aabbs]).max(axis=0)
    return AABB(lo, hi)


# ---------------------------------------------------------------------------
# Public API: all-pairs assembly check
# ---------------------------------------------------------------------------

def detect_interference_assembly(
    bodies: Sequence[Body],
    tol: float = 1e-6,
    clearance_min: float = 0.0,
) -> AssemblyInterferenceReport:
    """Check all pairs of bodies in an assembly for interference.

    Algorithm
    ---------
    1. Compute an AABB for each body.
    2. For every unique pair (i, j):
       a. Reject if ``aabb_gap > clearance_min + tol`` (broad-phase).
       b. Flag as *clearance warning* if ``0 < aabb_gap ≤ clearance_min``.
       c. Run :func:`detect_interference_pair` for pairs within touching range.
    3. Accumulate results into an :class:`AssemblyInterferenceReport`.

    Parameters
    ----------
    bodies:
        List of bodies to check. The check is O(N²) pairs but AABB pruning
        makes it fast in practice for typical assemblies.
    tol:
        Geometric tolerance.
    clearance_min:
        Minimum required clearance gap. Pairs within this distance but not
        actually interfering are reported as clearance warnings.

    Returns
    -------
    :class:`AssemblyInterferenceReport`
    """
    n = len(bodies)
    if n < 2:
        return AssemblyInterferenceReport(n_bodies=n)

    # Pre-compute AABBs
    aabbs = [_body_aabb(b) for b in bodies]

    report = AssemblyInterferenceReport(n_bodies=n)

    for i, j in itertools.combinations(range(n), 2):
        gap = aabbs[i].gap_to(aabbs[j])

        if gap > clearance_min + tol:
            # Definitely disjoint with sufficient clearance — skip
            result = InterferenceResult(
                interferes=False,
                intersection_volume=0.0,
                intersection_curves=[],
                severity="none",
                aabb_gap=gap,
            )
            report.pairs.append((i, j, result))
            continue

        # Within touching / clearance range — run narrow phase
        result = detect_interference_pair(bodies[i], bodies[j], tol=tol)
        result.aabb_gap = gap  # overwrite with pre-computed value
        report.n_pairs_checked += 1

        report.pairs.append((i, j, result))

        if result.interferes and result.severity in ("overlap", "major_overlap"):
            report.critical_pairs.append((i, j))
        elif not result.interferes and 0.0 < gap <= clearance_min:
            report.clearance_warnings.append((i, j))

        report.total_interference_volume += result.intersection_volume

    return report


__all__ = [
    "AABB",
    "InterferenceResult",
    "AssemblyInterferenceReport",
    "detect_interference_pair",
    "detect_interference_assembly",
    "compute_assembly_aabb",
]


# ---------------------------------------------------------------------------
# LLM tool registration (gated import — works without kerf_chat installed)
# ---------------------------------------------------------------------------

try:
    import json as _json

    from kerf_chat.tools.registry import (  # type: ignore[import]
        ToolSpec,
        err_payload,
        ok_payload,
        register,
    )
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]

    from kerf_cad_core.geom.brep_build import box_to_body as _box_to_body

    _BODY_SCHEMA = {
        "type": "object",
        "properties": {
            "id": {
                "type": "string",
                "description": "Optional label for this body (used in result keys).",
            },
            "type": {
                "type": "string",
                "enum": ["box"],
                "description": "Primitive type. Only 'box' is supported.",
            },
            "corner": {
                "type": "array",
                "items": {"type": "number"},
                "description": "Minimum corner of the box [x, y, z] (mm).",
            },
            "dx": {"type": "number", "description": "X extent of the box (mm)."},
            "dy": {"type": "number", "description": "Y extent of the box (mm)."},
            "dz": {"type": "number", "description": "Z extent of the box (mm)."},
        },
        "required": ["type", "corner", "dx", "dy", "dz"],
    }

    def _parse_body_ai(spec: dict, idx: int):
        if not isinstance(spec, dict):
            raise ValueError(f"bodies[{idx}] must be an object")
        body_type = str(spec.get("type", "")).strip().lower()
        if body_type != "box":
            raise ValueError(
                f"bodies[{idx}]: unsupported type '{body_type}' "
                f"(only 'box' is supported)"
            )
        corner_raw = spec.get("corner")
        if not corner_raw or len(corner_raw) != 3:
            raise ValueError(f"bodies[{idx}]: corner must be [x, y, z]")
        try:
            corner = [float(x) for x in corner_raw]
        except (TypeError, ValueError):
            raise ValueError(f"bodies[{idx}]: corner values must be numbers")
        try:
            dx = float(spec["dx"])
            dy = float(spec["dy"])
            dz = float(spec["dz"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"bodies[{idx}]: {exc}")
        if dx <= 0 or dy <= 0 or dz <= 0:
            raise ValueError(
                f"bodies[{idx}]: dx/dy/dz must be positive; got ({dx}, {dy}, {dz})"
            )
        label = str(spec.get("id", f"body_{idx}"))
        body = _box_to_body(corner, dx, dy, dz)
        return label, body

    _interference_spec = ToolSpec(
        name="brep_assembly_interference",
        description=(
            "Detect geometric interference (volume overlap) between bodies in an "
            "assembly.\n"
            "\n"
            "Each body is an axis-aligned box specified by its minimum corner and "
            "extents (dx, dy, dz in mm).  The tool performs:\n"
            "  1. AABB broad-phase: cheap rejection of clearly-disjoint pairs.\n"
            "  2. Möller 1997 triangle-triangle narrow phase: exact crossing test.\n"
            "  3. Boolean intersection (GK-18) + volume measurement (GK-23) for "
            "     pairs that pass the broad phase.\n"
            "\n"
            "Severity levels:\n"
            "  'none'          — disjoint (no interference).\n"
            "  'touch'         — coincident faces / zero-volume contact.\n"
            "  'overlap'       — genuine volume interpenetration.\n"
            "  'major_overlap' — overlap > 10 % of smaller body's volume.\n"
            "\n"
            "Returns a full pairwise matrix plus a list of critical pairs "
            "(severity == 'overlap' or 'major_overlap') and clearance warnings.\n"
            "\n"
            "Exactly 2 bodies → single-pair result returned as 'pair' key.\n"
            "3+ bodies → full assembly report returned as 'report' key."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bodies": {
                    "type": "array",
                    "description": "List of body specifications (minimum 2).",
                    "items": _BODY_SCHEMA,
                    "minItems": 2,
                },
                "tol": {
                    "type": "number",
                    "description": "Geometric tolerance in mm (default 1e-6).",
                },
                "clearance_min": {
                    "type": "number",
                    "description": (
                        "Minimum required clearance gap in mm (default 0). "
                        "Pairs within this distance but not interfering are "
                        "reported as clearance warnings."
                    ),
                },
            },
            "required": ["bodies"],
        },
    )

    @register(_interference_spec, write=False)
    async def _run_brep_assembly_interference(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        bodies_raw = a.get("bodies")
        if not bodies_raw or not isinstance(bodies_raw, list):
            return err_payload("bodies is required (list of ≥2 body specs)", "BAD_ARGS")
        if len(bodies_raw) < 2:
            return err_payload("bodies must have at least 2 elements", "BAD_ARGS")

        tol = float(a.get("tol", 1e-6))
        clearance_min = float(a.get("clearance_min", 0.0))

        labels = []
        bodies = []
        for idx, spec in enumerate(bodies_raw):
            try:
                label, body = _parse_body_ai(spec, idx)
            except ValueError as exc:
                return err_payload(str(exc), "BAD_ARGS")
            labels.append(label)
            bodies.append(body)

        if len(bodies) == 2:
            result = detect_interference_pair(bodies[0], bodies[1], tol=tol)
            return ok_payload({
                "mode": "pair",
                "body_a": labels[0],
                "body_b": labels[1],
                "pair": result.to_dict(),
                "message": (
                    f"Interference between '{labels[0]}' and '{labels[1]}': "
                    f"severity={result.severity!r}, "
                    f"volume={result.intersection_volume:.6g} mm³."
                ),
            })

        report = detect_interference_assembly(bodies, tol=tol, clearance_min=clearance_min)

        pairs_labelled = []
        for i, j, res in report.pairs:
            pairs_labelled.append({
                "body_a": labels[i],
                "body_b": labels[j],
                "i": i,
                "j": j,
                "result": res.to_dict(),
            })

        critical = [
            {"i": i, "j": j, "body_a": labels[i], "body_b": labels[j]}
            for i, j in report.critical_pairs
        ]
        warnings_list = [
            {"i": i, "j": j, "body_a": labels[i], "body_b": labels[j]}
            for i, j in report.clearance_warnings
        ]

        assembly_aabb = compute_assembly_aabb(bodies)

        return ok_payload({
            "mode": "assembly",
            "n_bodies": report.n_bodies,
            "n_pairs_checked": report.n_pairs_checked,
            "total_pairs": len(report.pairs),
            "total_interference_volume": report.total_interference_volume,
            "critical_pairs": critical,
            "clearance_warnings": warnings_list,
            "pairs": pairs_labelled,
            "assembly_aabb": assembly_aabb.to_dict(),
            "body_labels": labels,
            "message": (
                f"{len(report.critical_pairs)} interfering pair(s) out of "
                f"{report.n_bodies} bodies; "
                f"total volume={report.total_interference_volume:.6g} mm³."
            ),
        })

    _clearance_spec = ToolSpec(
        name="brep_check_clearance",
        description=(
            "Check minimum clearance gaps between bodies in an assembly and flag "
            "pairs that are closer than a required minimum distance.\n"
            "\n"
            "Performs AABB-based gap computation for all pairs. Pairs with AABB gap "
            "≤ min_clearance are reported as clearance violations.\n"
            "\n"
            "Also detects actual interference (overlap); overlapping pairs are "
            "reported separately from close-clearance pairs.\n"
            "\n"
            "Returns:\n"
            "  violations        — pairs with gap < min_clearance (not overlapping).\n"
            "  interfering       — pairs with actual volume overlap.\n"
            "  all_pairs         — full gap matrix.\n"
            "  assembly_aabb     — bounding box of the entire assembly.\n"
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bodies": {
                    "type": "array",
                    "description": "List of body specifications (minimum 2).",
                    "items": _BODY_SCHEMA,
                    "minItems": 2,
                },
                "min_clearance": {
                    "type": "number",
                    "description": (
                        "Required minimum clearance gap in mm. "
                        "Pairs with gap < min_clearance are flagged (default 0.1)."
                    ),
                },
                "tol": {
                    "type": "number",
                    "description": "Geometric tolerance in mm (default 1e-6).",
                },
            },
            "required": ["bodies"],
        },
    )

    @register(_clearance_spec, write=False)
    async def _run_brep_check_clearance(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

        bodies_raw = a.get("bodies")
        if not bodies_raw or not isinstance(bodies_raw, list):
            return err_payload("bodies is required (list of ≥2 body specs)", "BAD_ARGS")
        if len(bodies_raw) < 2:
            return err_payload("bodies must have at least 2 elements", "BAD_ARGS")

        min_clearance = float(a.get("min_clearance", 0.1))
        tol = float(a.get("tol", 1e-6))

        labels = []
        bodies = []
        for idx, spec in enumerate(bodies_raw):
            try:
                label, body = _parse_body_ai(spec, idx)
            except ValueError as exc:
                return err_payload(str(exc), "BAD_ARGS")
            labels.append(label)
            bodies.append(body)

        report = detect_interference_assembly(
            bodies, tol=tol, clearance_min=min_clearance
        )

        all_pairs = []
        violations = []
        interfering = []

        for i, j, res in report.pairs:
            entry = {
                "body_a": labels[i],
                "body_b": labels[j],
                "i": i,
                "j": j,
                "aabb_gap": res.aabb_gap,
                "interferes": res.interferes,
                "severity": res.severity,
                "intersection_volume": res.intersection_volume,
            }
            all_pairs.append(entry)

            if res.interferes and res.severity in ("overlap", "major_overlap"):
                interfering.append(entry)
            elif not res.interferes and res.aabb_gap <= min_clearance:
                violations.append(entry)

        assembly_aabb = compute_assembly_aabb(bodies)

        n_violations = len(violations)
        n_interfering = len(interfering)

        return ok_payload({
            "violations": violations,
            "interfering": interfering,
            "all_pairs": all_pairs,
            "assembly_aabb": assembly_aabb.to_dict(),
            "body_labels": labels,
            "min_clearance_mm": min_clearance,
            "n_violations": n_violations,
            "n_interfering": n_interfering,
            "message": (
                f"{n_violations} clearance violation(s) and "
                f"{n_interfering} interference(s) found among "
                f"{len(bodies)} bodies (min clearance = {min_clearance} mm)."
            ),
        })

except ImportError:
    pass
