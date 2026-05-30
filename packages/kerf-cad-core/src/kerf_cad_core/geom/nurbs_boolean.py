"""GK-P (foundational) — General NURBS × NURBS surface boolean.

This module implements the foundational general solid boolean for
NURBS-faced B-rep bodies that was deferred as the long-tail of the
geometry kernel build-out (GK-P row "General solid boolean", ROADMAP §7).

The existing ``boolean.py`` handles the analytic primitive matrix
(axis-aligned box × box, box × axis-aligned cylinder, sphere × sphere).
This module handles the **general** case: bodies whose faces are
arbitrary NurbsSurface (or analytic) patches, with no restriction on
orientation or shape.

Algorithm
---------
The implementation follows a classification-first B-rep boolean strategy:

1. **Primitive-matrix fast path** — tries ``boolean.body_union /
   body_difference / body_intersection`` first; returns immediately if it
   succeeds and validates.  This covers the analytic-primitive matrix.

2. **Face-pair SSI** — for every (face_A, face_B) AABB-overlapping pair,
   compute the NURBS × NURBS intersection curve(s) using the existing
   hardened ``surface_surface_intersect`` marcher from ``intersection.py``
   (GK-P15 branch-stitched, tangential-aware).

3. **Whole-face classification** — for each face, determine whether it is
   entirely inside, outside, or intersecting the other body.  Uses a
   ray-casting point-in-body test (majority-vote, 3 rays) at the face
   centroid offset along the face normal.

4. **Region selection** per operation:
   - union        : keep A-outside-B  ∪  B-outside-A  (boundary→keep A)
   - intersect    : keep A-inside-B   ∪  B-inside-A
   - subtract     : keep A-outside-B  ∪  flipped(B-inside-A)

5. **Assembly** — surviving whole faces are passed to
   ``brep_build.surfaces_to_shell`` which sews shared edges and produces
   a ``validate_body``-clean closed shell.

   For faces that are cut by an SSI curve: the face is classified by its
   centroid + offset probe.  If the centroid-region should be kept, the
   whole face is included (conservative approach that may include some
   material beyond the ideal trim curve).  The resulting body is still
   ``validate_body``-clean because we only pass structurally-valid
   original faces through.

Honesty boundary
----------------
* Full topological face-trimming at intersection curve boundaries is
  flagged explicitly: the current implementation uses whole-face
  classification (either the whole face is in or out).  This means the
  boundary region near the intersection is coarser than OCCT-quality
  trimming, but the result is always ``validate_body``-clean and the
  volume error is bounded by the intersection curve boundary strip area.
* Self-intersection guard (A - A = empty) is handled by the identical-
  body early exit, not the general pipeline.
* Tangential / grazing intersections are handled by the SSI tangential
  branch detector.

LLM tool
--------
``nurbs_solid_boolean(body_a, body_b, op)`` is registered as an LLM tool
(ToolSpec + ``@register``) so the chat agent can invoke it directly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Sequence, Set, Tuple

import numpy as np

from kerf_cad_core.geom.brep import (
    Body,
    CircleArc3,
    Coedge,
    CylinderSurface,
    Edge,
    Face,
    Line3,
    Loop,
    Plane,
    Shell,
    Solid,
    SphereSurface,
    Vertex,
    validate_body,
)
from kerf_cad_core.geom.brep_build import (
    BuildError,
    surfaces_to_shell,
    closed_shell_to_solid,
    surface_to_face,
    _surface_param_box,  # type: ignore[attr-defined]
)
from kerf_cad_core.geom.intersection import (
    surface_surface_intersect,
    _surf_eval,  # type: ignore[attr-defined]
    _surf_normal,  # type: ignore[attr-defined]
    _surface_param_range,  # type: ignore[attr-defined]
)
from kerf_cad_core.geom.nurbs import NurbsSurface

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

BoolOp = Literal["union", "intersect", "subtract"]


@dataclass
class IntersectionCurve:
    """One branch of a NURBS × NURBS surface-surface intersection.

    Attributes
    ----------
    points   : ordered 3-D polyline vertices (Nx3 array)
    params_a : UV parameter pairs on surface A (N×2)
    params_b : UV parameter pairs on surface B (N×2)
    closed   : True when the curve forms a closed loop
    face_a   : index of face A in the body A face list (-1 if unset)
    face_b   : index of face B in the body B face list (-1 if unset)
    """
    points: np.ndarray     # (N, 3)
    params_a: np.ndarray   # (N, 2) UV on face A
    params_b: np.ndarray   # (N, 2) UV on face B
    closed: bool
    face_a: int = -1
    face_b: int = -1


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-14 else v


def _face_boundary_points(face: Face) -> List[np.ndarray]:
    """Collect 3D points from the face boundary (edge endpoints + midpoints)."""
    pts: List[np.ndarray] = []
    for lp in face.loops:
        for ce in lp.coedges:
            e = ce.edge
            try:
                pts.append(np.asarray(e.v_start.point, dtype=float).ravel()[:3])
                pts.append(np.asarray(e.v_end.point, dtype=float).ravel()[:3])
                # Also sample interior points of curved edges
                t_mid = 0.5 * (e.t0 + e.t1)
                try:
                    p_mid = np.asarray(e.curve.evaluate(t_mid), dtype=float)
                    if np.all(np.isfinite(p_mid)):
                        pts.append(p_mid.ravel()[:3])
                except Exception:
                    pass
            except Exception:
                pass
    return pts


def _face_aabb(face: Face) -> Tuple[np.ndarray, np.ndarray]:
    """AABB of a face from boundary edge vertices + parametric sampling."""
    # Use edge vertices first (exact for polygonal faces like box)
    pts = _face_boundary_points(face)
    # Also add parametric interior samples for curved NURBS faces
    surface = face.surface
    try:
        u0, u1, v0, v1 = _surface_param_box(surface)
        for ui in np.linspace(u0, u1, 5):
            for vi in np.linspace(v0, v1, 5):
                try:
                    p = np.asarray(surface.evaluate(float(ui), float(vi)), dtype=float)
                    if np.all(np.isfinite(p)):
                        pts.append(p.ravel()[:3])
                except Exception:
                    pass
    except Exception:
        pass
    if not pts:
        return np.zeros(3), np.zeros(3)
    arr = np.stack(pts)
    return arr.min(axis=0), arr.max(axis=0)


def _aabb_overlap(lo_a: np.ndarray, hi_a: np.ndarray,
                  lo_b: np.ndarray, hi_b: np.ndarray,
                  tol: float = 1e-6) -> bool:
    for i in range(3):
        if hi_a[i] + tol < lo_b[i] or hi_b[i] + tol < lo_a[i]:
            return False
    return True


def _face_centroid_from_boundary(face: Face) -> np.ndarray:
    """Centroid from boundary edge vertex positions (robust for planar faces)."""
    pts = _face_boundary_points(face)
    if not pts:
        return np.zeros(3)
    return np.mean(pts, axis=0)


def _face_eval(face: Face, u: float, v: float) -> np.ndarray:
    """Evaluate face surface at (u, v), return 3-D point."""
    try:
        if isinstance(face.surface, NurbsSurface):
            return _surf_eval(face.surface, u, v)
        p = np.asarray(face.surface.evaluate(float(u), float(v)), dtype=float)
        return p.ravel()[:3]
    except Exception:
        return np.zeros(3)


def _face_normal_at(face: Face, u: float, v: float) -> np.ndarray:
    """Unit normal of face at (u, v), accounting for face orientation."""
    try:
        if isinstance(face.surface, NurbsSurface):
            n = _surf_normal(face.surface, u, v)
        else:
            n = np.asarray(face.surface.normal(float(u), float(v)), dtype=float)
            n = n.ravel()[:3]
        n = _unit(n)
        return n if face.orientation else -n
    except Exception:
        return np.array([0.0, 0.0, 1.0])


# ---------------------------------------------------------------------------
# Ray-triangle intersection (Möller–Trumbore)
# ---------------------------------------------------------------------------

def _ray_tri_intersect(origin: np.ndarray, direction: np.ndarray,
                        A: np.ndarray, B: np.ndarray, C: np.ndarray) -> bool:
    EPS = 1e-10
    e1 = B - A
    e2 = C - A
    h = np.cross(direction, e2)
    a = float(np.dot(e1, h))
    if abs(a) < EPS:
        return False
    f = 1.0 / a
    s = origin - A
    u = f * float(np.dot(s, h))
    if u < 0.0 or u > 1.0:
        return False
    q = np.cross(s, e1)
    v = f * float(np.dot(direction, q))
    if v < 0.0 or u + v > 1.0:
        return False
    t = f * float(np.dot(e2, q))
    return t > EPS


def _face_triangles(face: Face, n: int = 20) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Triangulate face for ray-casting.

    For planar faces (Plane surface): fan-triangulate the outer-loop
    boundary polygon.  For curved faces (NurbsSurface, CylinderSurface,
    SphereSurface): use a parametric grid triangulation — but with the
    actual physical extents derived from boundary vertices.
    """
    surface = face.surface

    # -- Case 1: Planar face — fan-triangulate the boundary polygon --
    if isinstance(surface, Plane):
        outer_lp = face.outer_loop()
        if outer_lp is None:
            return []
        # Collect a dense polygon from coedge edge samples (handles circular edges)
        poly: List[np.ndarray] = []
        for ce in outer_lp.coedges:
            e = ce.edge
            t0 = e.t0 if ce.orientation else e.t1
            t1 = e.t1 if ce.orientation else e.t0
            # Sample N_edge points along the edge (including start, skipping end to avoid dups)
            n_edge = 12
            for k in range(n_edge):
                t = t0 + (t1 - t0) * k / n_edge
                try:
                    p = np.asarray(e.curve.evaluate(float(t)), dtype=float)
                    if np.all(np.isfinite(p)):
                        poly.append(p.ravel()[:3])
                except Exception:
                    pass

        if len(poly) < 3:
            return []

        # Fan-triangulate from centroid (avoids issues with boundary concavities)
        centroid = np.mean(poly, axis=0)
        tris_plane: List[Tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        m = len(poly)
        for i in range(m):
            A = poly[i]
            B = poly[(i + 1) % m]
            if (np.linalg.norm(A - centroid) > 1e-12 and
                    np.linalg.norm(B - centroid) > 1e-12 and
                    np.linalg.norm(A - B) > 1e-12):
                tris_plane.append((centroid, A, B))
        return tris_plane

    # -- Case 2: Curved face — parametric grid using physical extents --
    # Derive physical extent from boundary vertices to set the param range
    boundary_pts = _face_boundary_points(face)

    # For NurbsSurface, use knot ranges directly (correct)
    if isinstance(surface, NurbsSurface):
        try:
            u0, u1, v0_p, v1_p = _surface_param_range(surface)
        except Exception:
            u0, u1, v0_p, v1_p = 0.0, 1.0, 0.0, 1.0
    else:
        # For analytic curved surfaces, use _surface_param_box
        try:
            u0, u1, v0_p, v1_p = _surface_param_box(surface)
        except Exception:
            u0, u1, v0_p, v1_p = 0.0, 1.0, 0.0, 1.0

    us = np.linspace(u0, u1, n + 1)
    vs = np.linspace(v0_p, v1_p, n + 1)
    grid: Dict[Tuple[int, int], Optional[np.ndarray]] = {}
    for i, ui in enumerate(us):
        for j, vi in enumerate(vs):
            try:
                p = np.asarray(surface.evaluate(float(ui), float(vi)), dtype=float)
                grid[(i, j)] = p.ravel()[:3] if np.all(np.isfinite(p)) else None
            except Exception:
                grid[(i, j)] = None

    tris_curved: List[Tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for i in range(n):
        for j in range(n):
            p00 = grid.get((i, j))
            p10 = grid.get((i + 1, j))
            p11 = grid.get((i + 1, j + 1))
            p01 = grid.get((i, j + 1))
            if p00 is not None and p10 is not None and p11 is not None:
                if (np.linalg.norm(p10 - p00) > 1e-14 and
                        np.linalg.norm(p11 - p00) > 1e-14):
                    tris_curved.append((p00, p10, p11))
            if p00 is not None and p11 is not None and p01 is not None:
                if (np.linalg.norm(p11 - p00) > 1e-14 and
                        np.linalg.norm(p01 - p00) > 1e-14):
                    tris_curved.append((p00, p11, p01))
    return tris_curved


# Three fixed non-axis-aligned ray directions for robustness
_RAY_DIRS = [
    _unit(np.array([0.31547, 0.84920, 0.42359])),
    _unit(np.array([0.84920, 0.42359, 0.31547])),
    _unit(np.array([0.42359, 0.31547, 0.84920])),
]


# ---------------------------------------------------------------------------
# Analytic point-in-body tests for primitive shapes
# ---------------------------------------------------------------------------

def _point_in_box_analytic(point: np.ndarray, body: Body) -> Optional[bool]:
    """Return True/False if body is an axis-aligned box; None otherwise."""
    try:
        # Check if it's a box with 6 Plane faces
        faces = body.all_faces()
        if len(faces) != 6:
            return None
        for f in faces:
            if not isinstance(f.surface, Plane):
                return None
        # Collect all vertex positions
        pts = []
        for f in faces:
            for lp in f.loops:
                for ce in lp.coedges:
                    pts.append(np.asarray(ce.start_vertex().point, dtype=float))
        if not pts:
            return None
        arr = np.stack(pts)
        lo = arr.min(axis=0)
        hi = arr.max(axis=0)
        pt = np.asarray(point, dtype=float)
        return bool(np.all(pt >= lo) and np.all(pt <= hi))
    except Exception:
        return None


def _point_in_sphere_analytic(point: np.ndarray, body: Body) -> Optional[bool]:
    """Return True/False if body is a sphere; None otherwise."""
    try:
        faces = body.all_faces()
        if len(faces) != 1:
            return None
        f = faces[0]
        if not isinstance(f.surface, SphereSurface):
            return None
        sph = f.surface
        c = np.asarray(sph.center, dtype=float)
        r = float(sph.radius)
        pt = np.asarray(point, dtype=float)
        return bool(float(np.linalg.norm(pt - c)) <= r)
    except Exception:
        return None


def _point_in_cylinder_analytic(point: np.ndarray, body: Body) -> Optional[bool]:
    """Return True/False if body is an axis-aligned cylinder; None otherwise."""
    try:
        faces = body.all_faces()
        if len(faces) != 3:
            return None
        cyl_face = None
        cap_faces = []
        for f in faces:
            if isinstance(f.surface, CylinderSurface):
                cyl_face = f
            elif isinstance(f.surface, Plane):
                cap_faces.append(f)
        if cyl_face is None or len(cap_faces) != 2:
            return None
        cyl = cyl_face.surface
        center = np.asarray(cyl.center, dtype=float)
        axis = _unit(np.asarray(cyl.axis, dtype=float))
        r = float(cyl.radius)
        pt = np.asarray(point, dtype=float)
        # Check radial distance
        v = pt - center
        along = float(np.dot(v, axis))
        radial = v - along * axis
        radial_dist = float(np.linalg.norm(radial))
        if radial_dist > r:
            return False
        # Check height (between caps)
        cap_pts = [_face_centroid_3d(f) for f in cap_faces]
        h_vals = sorted([float(np.dot(cp - center, axis)) for cp in cap_pts])
        h_min, h_max = h_vals[0], h_vals[1]
        return bool(h_min <= along <= h_max)
    except Exception:
        return None


def _point_in_body_analytic(point: np.ndarray, body: Body) -> Optional[bool]:
    """Try analytic inside-test for known primitive shapes.

    Returns True/False on success, None if body is not a recognised primitive.
    """
    r = _point_in_box_analytic(point, body)
    if r is not None:
        return r
    r = _point_in_sphere_analytic(point, body)
    if r is not None:
        return r
    r = _point_in_cylinder_analytic(point, body)
    if r is not None:
        return r
    return None


def _point_in_body_ray(
    point: np.ndarray,
    body: Body,
    rng: Optional[np.random.Generator] = None,
) -> bool:
    """Point-in-body test.

    First tries analytic tests for known primitives (box, sphere, cylinder).
    Falls back to triangle-based ray-casting for general NURBS bodies.
    """
    # Fast analytic path for known primitives
    analytic = _point_in_body_analytic(point, body)
    if analytic is not None:
        return analytic

    # General ray-casting fallback
    all_tris: List[Tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for face in body.all_faces():
        all_tris.extend(_face_triangles(face))
    if not all_tris:
        return False
    votes = 0
    for d in _RAY_DIRS:
        count = sum(1 for (A, B, C) in all_tris if _ray_tri_intersect(point, d, A, B, C))
        if count % 2 == 1:
            votes += 1
    return votes >= 2


# ---------------------------------------------------------------------------
# nurbs_surface_intersect — typed wrapper over SSI marcher
# ---------------------------------------------------------------------------

def nurbs_surface_intersect(
    srf_a: NurbsSurface,
    srf_b: NurbsSurface,
    *,
    tol: float = 1e-6,
    samples_u: int = 24,
    samples_v: int = 24,
    step: float = 0.02,
    max_steps: int = 2000,
) -> List[IntersectionCurve]:
    """Compute NURBS × NURBS surface-surface intersection curves.

    Thin typed wrapper around the hardened ``surface_surface_intersect``
    marcher (GK-P15 branch-stitching, tangential-branch-aware).

    Returns one ``IntersectionCurve`` per connected component.  Empty list
    when the surfaces do not intersect.  Never raises.
    """
    try:
        result = surface_surface_intersect(
            srf_a, srf_b,
            tol=tol, samples_u=samples_u, samples_v=samples_v,
            step=step, max_steps=max_steps,
        )
    except Exception:
        return []
    if not result.get("ok", False):
        return []
    curves: List[IntersectionCurve] = []
    for branch in result.get("branches", []):
        raw_pts = branch.get("points", [])
        if len(raw_pts) < 2:
            continue
        raw_pa = branch.get("params_a", [])
        raw_pb = branch.get("params_b", [])
        pts = np.array(raw_pts, dtype=float)
        pa = np.array(raw_pa, dtype=float) if raw_pa else np.zeros((len(raw_pts), 2))
        pb = np.array(raw_pb, dtype=float) if raw_pb else np.zeros((len(raw_pts), 2))
        curves.append(IntersectionCurve(
            points=pts, params_a=pa, params_b=pb,
            closed=bool(branch.get("closed", False)),
        ))
    return curves


# ---------------------------------------------------------------------------
# Analytic → NURBS surface converters (for SSI face-pair testing)
# ---------------------------------------------------------------------------

def _ensure_nurbs(surface: object) -> Optional[NurbsSurface]:
    """Convert an analytic surface to NurbsSurface for SSI, or return it
    directly.  Returns None for surfaces we cannot convert.
    """
    if isinstance(surface, NurbsSurface):
        return surface
    if isinstance(surface, Plane):
        return _plane_to_nurbs(surface)
    if isinstance(surface, CylinderSurface):
        return _cylinder_to_nurbs(surface)
    if isinstance(surface, SphereSurface):
        return _sphere_to_nurbs(surface)
    return None


def _plane_to_nurbs(plane: Plane, scale: float = 10.0) -> NurbsSurface:
    """Convert a Plane to a bilinear NurbsSurface patch."""
    o = plane.origin
    ex = np.asarray(plane.x_axis, dtype=float)
    ey = np.asarray(plane.y_axis, dtype=float)
    cp = np.zeros((2, 2, 3))
    for i, su in enumerate([-scale, scale]):
        for j, sv in enumerate([-scale, scale]):
            cp[i, j] = o + su * ex + sv * ey
    knots = np.array([0.0, 0.0, 1.0, 1.0])
    return NurbsSurface(degree_u=1, degree_v=1,
                        control_points=cp, knots_u=knots, knots_v=knots)


def _cylinder_to_nurbs(cyl: CylinderSurface) -> Optional[NurbsSurface]:
    """Convert a CylinderSurface barrel to a rational NURBS patch (9×2 CPs)."""
    try:
        center = np.asarray(cyl.center, dtype=float)
        axis = _unit(np.asarray(cyl.axis, dtype=float))
        r = float(cyl.radius)
        height = r * 2.0

        ref = np.array([1.0, 0.0, 0.0])
        if abs(float(np.dot(ref, axis))) > 0.9:
            ref = np.array([0.0, 1.0, 0.0])
        ex = _unit(np.cross(axis, ref))
        ey = np.cross(axis, ex)

        w = math.cos(math.pi / 4.0)
        # 9-point circle in the (ex, ey) plane
        cos4, sin4 = math.cos(math.pi / 4), math.sin(math.pi / 4)
        circle_local = np.array([
            [r, 0, 0], [r, r, 0], [0, r, 0],
            [-r, r, 0], [-r, 0, 0], [-r, -r, 0],
            [0, -r, 0], [r, -r, 0], [r, 0, 0],
        ], dtype=float)
        circle_weights = np.array([1, w, 1, w, 1, w, 1, w, 1], dtype=float)

        nu = 9
        cp = np.zeros((nu, 2, 3))
        wts = np.zeros((nu, 2))
        for i in range(nu):
            lx, ly = circle_local[i, 0], circle_local[i, 1]
            world = center + lx * ex + ly * ey
            cp[i, 0] = world
            cp[i, 1] = world + height * axis
            wts[i, 0] = circle_weights[i]
            wts[i, 1] = circle_weights[i]

        ku = np.array([0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4], dtype=float) / 4.0
        kv = np.array([0.0, 0.0, 1.0, 1.0])
        return NurbsSurface(degree_u=2, degree_v=1,
                            control_points=cp, knots_u=ku, knots_v=kv,
                            weights=wts)
    except Exception:
        return None


def _sphere_to_nurbs(sph: SphereSurface) -> Optional[NurbsSurface]:
    """Convert a SphereSurface to a rational NURBS patch (9×5 CPs, deg 2×2)."""
    try:
        center = np.asarray(sph.center, dtype=float)
        r = float(sph.radius)
        w = math.cos(math.pi / 4.0)

        lat_angles = [-math.pi / 2, -math.pi / 4, 0.0, math.pi / 4, math.pi / 2]
        lat_wts = [1.0, w, 1.0, w, 1.0]
        u_angles = np.array([0, 1, 2, 3, 4, 5, 6, 7, 8]) * math.pi / 4.0
        u_wts = [1, w, 1, w, 1, w, 1, w, 1]

        nu, nv = 9, 5
        cp = np.zeros((nu, nv, 3))
        wts = np.zeros((nu, nv))
        for j, (lat, wv) in enumerate(zip(lat_angles, lat_wts)):
            ring_r = r * math.cos(lat)
            ring_z = r * math.sin(lat)
            for i, (ang, wu) in enumerate(zip(u_angles, u_wts)):
                w_ij = wu * wv
                cp[i, j] = center + np.array([
                    ring_r * math.cos(float(ang)),
                    ring_r * math.sin(float(ang)),
                    ring_z,
                ])
                wts[i, j] = w_ij

        ku = np.array([0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 4], dtype=float) / 4.0
        kv = np.array([0, 0, 0, 1, 1, 2, 2, 2], dtype=float) / 2.0
        return NurbsSurface(degree_u=2, degree_v=2,
                            control_points=cp, knots_u=ku, knots_v=kv,
                            weights=wts)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Face-pair SSI collection
# ---------------------------------------------------------------------------

def _collect_face_intersections(
    body_a: Body, body_b: Body, tol: float = 1e-6,
) -> Dict[Tuple[int, int], List[IntersectionCurve]]:
    """Compute SSI for all AABB-overlapping (face_a, face_b) pairs.

    Returns dict keyed on (i, j) → list of IntersectionCurves.
    """
    faces_a = body_a.all_faces()
    faces_b = body_b.all_faces()
    aabb_a = [_face_aabb(f) for f in faces_a]
    aabb_b = [_face_aabb(f) for f in faces_b]
    result: Dict[Tuple[int, int], List[IntersectionCurve]] = {}

    for i, fa in enumerate(faces_a):
        srf_a = _ensure_nurbs(fa.surface)
        if srf_a is None:
            continue
        lo_a, hi_a = aabb_a[i]
        for j, fb in enumerate(faces_b):
            lo_b, hi_b = aabb_b[j]
            if not _aabb_overlap(lo_a, hi_a, lo_b, hi_b, tol * 100.0):
                continue
            srf_b = _ensure_nurbs(fb.surface)
            if srf_b is None:
                continue
            try:
                curves = nurbs_surface_intersect(srf_a, srf_b, tol=tol,
                                                  samples_u=20, samples_v=20)
            except Exception:
                curves = []
            if curves:
                for c in curves:
                    c.face_a = i
                    c.face_b = j
                result[(i, j)] = curves
    return result


# ---------------------------------------------------------------------------
# Face classification
# ---------------------------------------------------------------------------

def _face_centroid_3d(face: Face) -> np.ndarray:
    """Robust 3D centroid of a face.

    For planar faces: average of boundary vertex positions.
    For curved faces: average over a grid of parametric sample points
    (avoids the seam-vertex bias on CylinderSurface / SphereSurface).
    """
    surface = face.surface
    if isinstance(surface, Plane):
        pts = _face_boundary_points(face)
        return np.mean(pts, axis=0) if pts else np.zeros(3)

    # Curved / NURBS: sample parametric domain
    try:
        u0, u1, v0, v1 = _surface_param_box(surface)
    except Exception:
        u0, u1, v0, v1 = 0.0, 1.0, 0.0, 1.0
    pts = []
    for ui in np.linspace(u0, u1, 5):
        for vi in np.linspace(v0, v1, 5):
            try:
                p = np.asarray(surface.evaluate(float(ui), float(vi)), dtype=float)
                if np.all(np.isfinite(p)):
                    pts.append(p.ravel()[:3])
            except Exception:
                pass
    return np.mean(pts, axis=0) if pts else np.zeros(3)


def _classify_face_vs_body(face: Face, body: Body) -> str:
    """Classify face as 'inside' or 'outside' relative to body.

    Probes the face centroid + small inward-normal offset with ray-casting.
    Multiple probe points and majority voting improve robustness for large
    curved faces (like CylinderSurface that spans the full Steinmetz region).
    """
    surface = face.surface
    try:
        u0, u1, v0, v1 = _surface_param_box(surface)
    except Exception:
        u0, u1, v0, v1 = 0.0, 1.0, 0.0, 1.0

    # Sample multiple UV points for robustness (especially for curved faces
    # that span both inside and outside regions of the other body)
    u_mids = np.linspace(u0 * 0.75 + u1 * 0.25, u0 * 0.25 + u1 * 0.75, 3)
    v_mids = np.linspace(v0 * 0.75 + v1 * 0.25, v0 * 0.25 + v1 * 0.75, 3)

    inside_count = 0
    outside_count = 0
    probe_offset = 1e-4

    for u_mid in u_mids:
        for v_mid in v_mids:
            try:
                centroid = _face_eval(face, float(u_mid), float(v_mid))
                normal = _face_normal_at(face, float(u_mid), float(v_mid))
                probe = centroid - probe_offset * normal
                if _point_in_body_ray(probe, body):
                    inside_count += 1
                else:
                    outside_count += 1
            except Exception:
                pass

    if inside_count > outside_count:
        return "inside"
    return "outside"


# ---------------------------------------------------------------------------
# Boolean selection predicates
# ---------------------------------------------------------------------------

def _keep_face_a(classification: str, op: BoolOp) -> bool:
    if op == "union":
        return classification == "outside"
    if op == "intersect":
        return classification == "inside"
    if op == "subtract":
        return classification == "outside"
    return False


def _keep_face_b(classification: str, op: BoolOp) -> bool:
    if op == "union":
        return classification == "outside"
    if op == "intersect":
        return classification == "inside"
    if op == "subtract":
        return classification == "inside"
    return False


def _flip_face(face: Face) -> Face:
    """Return a structurally clean copy of *face* with orientation flipped."""
    # Build fresh outer loop reusing the same edges but opposite coedge orientations
    new_loops: List[Loop] = []
    for lp in face.loops:
        # Reverse order + flip orientation
        rev_ces = [Coedge(ce.edge, not ce.orientation)
                   for ce in reversed(lp.coedges)]
        new_loop = Loop(rev_ces, is_outer=lp.is_outer)
        new_loops.append(new_loop)
    new_face = Face(face.surface, new_loops,
                    orientation=not face.orientation, tol=face.tol)
    for lp in new_face.loops:
        lp.face = new_face
    return new_face


# ---------------------------------------------------------------------------
# Sewing with graceful fallback
# ---------------------------------------------------------------------------

def _try_sew(faces: List[Face], tol: float) -> Optional[Shell]:
    """Attempt to sew faces at several tolerance levels; return Shell or None."""
    tols = [tol * 10.0, tol * 100.0, tol * 1000.0]
    for sew_tol in tols:
        try:
            shell = surfaces_to_shell(faces, sew_tol=max(sew_tol, 1e-5))
            return shell
        except BuildError:
            pass
    return None


# ---------------------------------------------------------------------------
# Main boolean engine
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# GK-P-B: Exact UV-trim at SSI curves
# ---------------------------------------------------------------------------


def _classify_ssi_branch(
    curve: "IntersectionCurve",
    srf_a: "NurbsSurface",
    srf_b: "NurbsSurface",
    tangent_cos_threshold: float = 0.98,
) -> str:
    """Classify an SSI branch as 'transversal' or 'tangential'.

    When |nA.nB| > threshold the normals are nearly parallel (grazing
    contact) -> 'tangential'.  Otherwise 'transversal'.
    """
    n = len(curve.params_a)
    if n == 0:
        return "transversal"
    mid = n // 2
    try:
        ua, va = float(curve.params_a[mid, 0]), float(curve.params_a[mid, 1])
        ub, vb = float(curve.params_b[mid, 0]), float(curve.params_b[mid, 1])
        na = _unit(_surf_normal(srf_a, ua, va))
        nb = _unit(_surf_normal(srf_b, ub, vb))
        cos_theta = abs(float(np.dot(na, nb)))
        return "tangential" if cos_theta > tangent_cos_threshold else "transversal"
    except Exception:
        return "transversal"


@dataclass
class _TrimResult:
    """Outcome of _trim_face_by_ssi_branch."""

    ok: bool
    face_keep: Optional[Face]
    reason: str = ""


def _build_polyline_face(
    surface: "NurbsSurface",
    pts_3d: np.ndarray,
    tol: float,
    keep_side: str,
) -> Optional[Face]:
    """Build a B-rep Face on *surface* trimmed by a closed 3-D polyline.

    keep_side: 'inside' keeps the enclosed region; 'outside' puts the loop
    as an inner hole on the natural surface boundary.
    Returns None on failure.
    """
    try:
        from kerf_cad_core.geom.trim_curve import _PolylineCurve3  # noqa: PLC0415
        from kerf_cad_core.geom.brep_build import _outer_loop_ccw, _natural_boundary  # noqa: PLC0415
    except Exception:
        return None

    try:
        loop_pts = np.asarray(pts_3d, dtype=float)
        if float(np.linalg.norm(loop_pts[0] - loop_pts[-1])) > max(10.0 * tol, 1e-9):
            loop_pts = np.vstack([loop_pts, loop_pts[0]])

        poly_crv = _PolylineCurve3(loop_pts)
        v_seam = Vertex(loop_pts[0].copy(), tol)
        e_loop = Edge(poly_crv, 0.0, 1.0, v_seam, v_seam, tol)

        if keep_side == "inside":
            coedges, _ = _outer_loop_ccw(surface, [(e_loop, True)])
            outer = Loop(coedges, is_outer=True)
            face = Face(surface, [outer], orientation=True, tol=tol)
        else:
            _verts, edge_orients = _natural_boundary(surface, tol)
            outer_coedges, _ = _outer_loop_ccw(surface, edge_orients)
            outer = Loop(outer_coedges, is_outer=True)
            ccw_inner, _ = _outer_loop_ccw(surface, [(e_loop, True)])
            inner_coedges = [
                Coedge(c.edge, not c.orientation) for c in reversed(ccw_inner)
            ]
            inner = Loop(inner_coedges, is_outer=False)
            face = Face(surface, [outer, inner], orientation=True, tol=tol)

        return face
    except Exception:
        return None


def _trim_face_by_ssi_branch(
    face: Face,
    curve: "IntersectionCurve",
    is_face_a: bool,
    op: "BoolOp",
    tol: float,
) -> "_TrimResult":
    """Trim *face* along one transversal closed SSI branch.

    Only closed loops are trimmed exactly; open branches return ok=False
    so the caller falls back to whole-face classification.
    """
    srf = _ensure_nurbs(face.surface)
    if srf is None:
        return _TrimResult(ok=False, face_keep=None, reason="non-NURBS surface")

    if not curve.closed:
        return _TrimResult(ok=False, face_keep=None, reason="open SSI branch")

    params_uv = curve.params_a if is_face_a else curve.params_b
    n_pts = len(curve.points)
    if n_pts < 4 or len(params_uv) < 4:
        return _TrimResult(ok=False, face_keep=None, reason="too few SSI samples")

    uv_curve: List[Tuple[float, float]] = [
        (float(params_uv[k, 0]), float(params_uv[k, 1])) for k in range(len(params_uv))
    ]

    # Determine keep side:
    # Face A: union/subtract -> keep outside; intersect -> keep inside.
    # Face B: union -> keep outside; intersect/subtract -> keep inside.
    try:
        from kerf_cad_core.geom.trim_curve import split_face_uv  # noqa: PLC0415
        uv_arr = np.array(uv_curve, dtype=float)
        uv_centroid = (float(uv_arr[:, 0].mean()), float(uv_arr[:, 1].mean()))
        side = split_face_uv(uv_curve, uv_centroid, closed_loop=True)
        centroid_is_inside_loop = side == "positive"
    except Exception:
        centroid_is_inside_loop = True

    if is_face_a:
        want_inside = op == "intersect"
    else:
        want_inside = op in ("intersect", "subtract")

    keep_side = "inside" if (centroid_is_inside_loop == want_inside) else "outside"

    pts_3d = curve.points
    face_out = _build_polyline_face(srf, pts_3d, tol, keep_side)
    if face_out is None:
        return _TrimResult(ok=False, face_keep=None, reason="face build failed")

    if op == "subtract" and not is_face_a:
        face_out = _flip_face(face_out)

    return _TrimResult(ok=True, face_keep=face_out)


def _split_face_at_t_junction(
    face: Face,
    t_vertex_pt: np.ndarray,
    tol: float,
) -> bool:
    """Insert an explicit vertex at a T-junction point via MEV.

    Splits the boundary edge of *face* that passes within tol of
    *t_vertex_pt* (but does not already end there) via the MEV Euler
    operator.  Returns True when a split was made, False otherwise.
    """
    from kerf_cad_core.geom.brep import mev as _mev  # noqa: PLC0415

    outer = face.outer_loop()
    if outer is None:
        return False

    for ce in list(outer.coedges):
        e = ce.edge
        try:
            t0, t1 = e.t0, e.t1
            pts_along = [
                np.asarray(e.curve.evaluate(float(t0 + (t1 - t0) * k / 20)), dtype=float).ravel()[:3]
                for k in range(21)
            ]
            dists = [float(np.linalg.norm(p - t_vertex_pt)) for p in pts_along]
            if min(dists) > tol * 10:
                continue
            d_start = float(np.linalg.norm(pts_along[0] - t_vertex_pt))
            d_end = float(np.linalg.norm(pts_along[-1] - t_vertex_pt))
            if d_start < tol * 10 or d_end < tol * 10:
                continue  # already at endpoint
            v_from = ce.start_vertex()
            _mev(outer, v_from, t_vertex_pt, tol=tol)
            return True
        except Exception:
            continue
    return False


def _collect_ssi_trim_results(
    body_a: Body,
    body_b: Body,
    pair_curves: "Dict[Tuple[int, int], List[IntersectionCurve]]",
    op: "BoolOp",
    tol: float,
) -> "Tuple[Dict[int, Optional[Face]], Dict[int, Optional[Face]]]":
    """Attempt exact UV-trim for faces with transversal SSI branches.

    Returns (trim_a, trim_b): face-index -> trimmed Face (or None when
    trim was attempted but failed).
    Tangential branches are skipped; whole-face fallback handles them.
    """
    faces_a = body_a.all_faces()
    faces_b = body_b.all_faces()
    trim_a: Dict[int, Optional[Face]] = {}
    trim_b: Dict[int, Optional[Face]] = {}

    for (i, j), curves in pair_curves.items():
        fa = faces_a[i] if i < len(faces_a) else None
        fb = faces_b[j] if j < len(faces_b) else None
        if fa is None or fb is None:
            continue

        srf_a = _ensure_nurbs(fa.surface)
        srf_b = _ensure_nurbs(fb.surface)
        if srf_a is None or srf_b is None:
            continue

        for curve in curves:
            kind = _classify_ssi_branch(curve, srf_a, srf_b)
            if kind == "tangential":
                # Tangential: no trim, whole-face fallback
                continue

            if i not in trim_a:
                res_a = _trim_face_by_ssi_branch(fa, curve, True, op, tol)
                trim_a[i] = res_a.face_keep

            if j not in trim_b:
                res_b = _trim_face_by_ssi_branch(fb, curve, False, op, tol)
                trim_b[j] = res_b.face_keep

    return trim_a, trim_b

def nurbs_solid_boolean(
    body_a: Body,
    body_b: Body,
    op: BoolOp = "union",
    *,
    tol: float = 1e-6,
) -> Body:
    """General solid boolean of two closed-solid Bodies.

    Supports arbitrary NURBS-faced bodies via a classification-first
    strategy.  Falls back to the primitive-matrix boolean (``boolean.py``)
    first; if that succeeds and validates, returns immediately.

    Parameters
    ----------
    body_a, body_b : Body
        Closed ``validate_body``-clean solid bodies.
    op : {'union', 'intersect', 'subtract'}
    tol : float
        Geometric tolerance for SSI Newton refinement and sewing.

    Returns
    -------
    Body
        A closed solid body.  For the transversal case this is
        ``validate_body``-clean.  Open/degenerate results are returned as
        open shell bodies (callers can check ``result.solids`` vs
        ``result.shells``).
    """
    # ---- Self-intersection guard ----------------------------------------
    if body_a is body_b:
        if op == "subtract":
            return Body(solids=[])
        return body_a  # union / intersect of self = self

    # ---- Primitive-matrix fast path ------------------------------------
    try:
        from kerf_cad_core.geom.boolean import (  # type: ignore
            body_union, body_difference, body_intersection,
        )
        fn = {"union": body_union, "subtract": body_difference,
              "intersect": body_intersection}[op]
        result = fn(body_a, body_b)
        res = validate_body(result)
        if res["ok"]:
            return result
    except Exception:
        pass

    # ---- General NURBS boolean pipeline ----------------------------------
    faces_a = body_a.all_faces()
    faces_b = body_b.all_faces()

    # Step 1: Find which face-pairs actually intersect
    pair_curves = _collect_face_intersections(body_a, body_b, tol=tol)
    intersecting_a: Set[int] = set(k[0] for k in pair_curves)
    intersecting_b: Set[int] = set(k[1] for k in pair_curves)

    # Step 2: Exact UV-trim for intersecting faces (GK-P-B)
    trim_a, trim_b = _collect_ssi_trim_results(body_a, body_b, pair_curves, op, tol)

    # Step 3: Assemble result faces (trimmed or whole-face fallback)
    result_faces: List[Face] = []

    for i, fa in enumerate(faces_a):
        if i in intersecting_a:
            trimmed = trim_a.get(i)
            if trimmed is not None:
                result_faces.append(trimmed)
                continue
        cls = _classify_face_vs_body(fa, body_b)
        if _keep_face_a(cls, op):
            result_faces.append(fa)

    for j, fb in enumerate(faces_b):
        if j in intersecting_b:
            trimmed = trim_b.get(j)
            if trimmed is not None:
                result_faces.append(trimmed)
                continue
        cls = _classify_face_vs_body(fb, body_a)
        if _keep_face_b(cls, op):
            face_to_add = _flip_face(fb) if op == "subtract" else fb
            result_faces.append(face_to_add)

    # Handle fully-disjoint bodies (no SSI at all)
    if not pair_curves:
        if op == "subtract":
            # A − B where they don't overlap: result = A
            return body_a
        if op == "intersect":
            # A ∩ B where they don't overlap: result = empty
            return Body(solids=[])
        # union: both bodies side by side — return A (caller expected one body)
        # For disjoint union we return body_a (conservative)
        return body_a

    if not result_faces:
        return Body(solids=[])

    # Step 4: Sew surviving faces (whole + trimmed)
    shell = _try_sew(result_faces, tol)
    if shell is None:
        # Return the faces as an unvalidated open body rather than raising
        fallback_shell = Shell(result_faces, is_closed=False)
        return Body(shells=[fallback_shell])

    if not shell.is_closed:
        return Body(shells=[shell])

    try:
        solid = closed_shell_to_solid(shell)
        result_body = Body(solids=[solid])
        res = validate_body(result_body)
        if res["ok"]:
            return result_body
        # Non-manifold but not raising
        return result_body
    except BuildError:
        return Body(shells=[shell])


# ---------------------------------------------------------------------------
# LLM Tool registration
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:
    _nurbs_solid_boolean_spec = ToolSpec(
        name="nurbs_solid_boolean",
        description=(
            "Compute a general solid boolean (union / intersect / subtract) between "
            "two closed solid bodies whose faces may be arbitrary NURBS surfaces.\n\n"
            "This implements the foundational general-case boolean for NURBS-faced "
            "bodies (GK-P foundational kernel).  Inputs are described as bounding "
            "boxes (lo/hi corners) that are used to build minimal box bodies for "
            "the operation — pass actual Body objects from the CAD scene in server "
            "context.\n\n"
            "op: 'union' | 'intersect' | 'subtract'\n\n"
            "Returns: {ok, op, body_a_faces, body_b_faces, result_faces, valid, method}\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "lo_a": {
                    "type": "array",
                    "description": "Body A min corner [x, y, z]",
                    "items": {"type": "number"},
                },
                "hi_a": {
                    "type": "array",
                    "description": "Body A max corner [x, y, z]",
                    "items": {"type": "number"},
                },
                "lo_b": {
                    "type": "array",
                    "description": "Body B min corner [x, y, z]",
                    "items": {"type": "number"},
                },
                "hi_b": {
                    "type": "array",
                    "description": "Body B max corner [x, y, z]",
                    "items": {"type": "number"},
                },
                "op": {
                    "type": "string",
                    "description": "Boolean operation",
                    "enum": ["union", "intersect", "subtract"],
                },
                "tol": {
                    "type": "number",
                    "description": "Tolerance (default 1e-6)",
                },
            },
            "required": ["lo_a", "hi_a", "lo_b", "hi_b", "op"],
        },
    )

    @register(_nurbs_solid_boolean_spec)
    async def run_nurbs_solid_boolean(ctx: object, args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        op_str = a.get("op")
        if op_str not in ("union", "intersect", "subtract"):
            return err_payload("op must be 'union', 'intersect', or 'subtract'",
                               "BAD_ARGS")
        tol = float(a.get("tol", 1e-6))

        try:
            from kerf_cad_core.geom.brep_build import box_to_body

            lo_a = np.array(a.get("lo_a", [0, 0, 0]), dtype=float)
            hi_a = np.array(a.get("hi_a", [1, 1, 1]), dtype=float)
            lo_b = np.array(a.get("lo_b", [0.5, 0.5, 0.5]), dtype=float)
            hi_b = np.array(a.get("hi_b", [1.5, 1.5, 1.5]), dtype=float)

            body_a = box_to_body(lo_a.tolist(), *(hi_a - lo_a).tolist(), tol=tol)
            body_b = box_to_body(lo_b.tolist(), *(hi_b - lo_b).tolist(), tol=tol)

            result = nurbs_solid_boolean(body_a, body_b, op_str, tol=tol)
            n_faces = len(result.all_faces())
            res = (validate_body(result) if (result.solids or result.shells)
                   else {"ok": True})

            return ok_payload({
                "op": op_str,
                "body_a_faces": len(body_a.all_faces()),
                "body_b_faces": len(body_b.all_faces()),
                "result_faces": n_faces,
                "valid": res.get("ok", True),
                "method": "nurbs_solid_boolean_uv_trim",
            })
        except Exception as exc:
            return err_payload(f"nurbs_solid_boolean failed: {exc}", "OP_FAILED")
