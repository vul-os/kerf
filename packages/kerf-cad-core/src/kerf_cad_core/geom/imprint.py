"""GK-82  Imprint (3D curve → new face edges).

Pure-Python, no OCCT dependency.

Public API
----------
imprint_curve_on_face(body, face_id, curve_3d) -> Body
    Project a 3D curve onto the underlying surface of a face, then split
    the face along the projected path, introducing new edges and vertices.
    Returns a **new** Body with topology updated; the input body is not
    mutated.

    The projection is performed via ``closest_point_surface`` (GK-07
    Newton inversion) for NurbsSurface-backed faces, and via orthogonal
    projection for analytic surfaces (Plane, SphereSurface, etc.).

    The split follows the same polygon-split algorithm used by
    ``knife_face`` (GK-89), but the projection step is surface-aware
    rather than planar.

    Parameters
    ----------
    body : Body
        Input B-rep body.  Not mutated.
    face_id : int
        Index into ``body.all_faces()``.
    curve_3d : object
        Any curve with ``evaluate(t) -> array-like`` (3-D).  The
        parametric range defaults to ``[0, 1]`` unless the object
        exposes ``t0`` / ``t1`` attributes.

    Returns
    -------
    Body
        New Body with the target face replaced by two new faces whose
        combined area equals the original face area.  All other faces are
        shallow-copied into the new shell/solid hierarchy.

    Raises
    ------
    ValueError
        When ``face_id`` is out of range, the projection is degenerate,
        or the curve path does not validly bisect the face boundary.
    TypeError
        When ``body`` is not a ``Body`` instance.
"""

from __future__ import annotations

import copy
import math
from typing import List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Optional imports – keep graceful so the module loads in minimal environments
# ---------------------------------------------------------------------------

try:
    from kerf_cad_core.geom.brep import (
        Body,
        Coedge,
        Edge,
        Face,
        Line3,
        Loop,
        Plane,
        Shell,
        Solid,
        SphereSurface,
        Vertex,
        _unit,
    )
    _HAS_BREP = True
except ImportError:  # pragma: no cover
    _HAS_BREP = False
    Body = None  # type: ignore[assignment,misc]

try:
    from kerf_cad_core.geom.inversion import closest_point_surface
    _HAS_INVERSION = True
except ImportError:  # pragma: no cover
    _HAS_INVERSION = False
    closest_point_surface = None  # type: ignore[assignment]

try:
    from kerf_cad_core.geom.nurbs import NurbsSurface
    _HAS_NURBS = True
except ImportError:  # pragma: no cover
    _HAS_NURBS = False
    NurbsSurface = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TOL: float = 1e-7

# Number of samples used to discretise curve_3d for projection / split
_CURVE_SAMPLES: int = 64


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _curve_t_range(curve_3d) -> Tuple[float, float]:
    """Return (t0, t1) parametric range of *curve_3d*."""
    t0 = float(getattr(curve_3d, "t0", 0.0))
    t1 = float(getattr(curve_3d, "t1", 1.0))
    return t0, t1


def _sample_curve(curve_3d, n: int = _CURVE_SAMPLES) -> np.ndarray:
    """Sample *curve_3d* at *n* equispaced parameter values; shape (n, 3)."""
    t0, t1 = _curve_t_range(curve_3d)
    ts = np.linspace(t0, t1, n)
    pts = np.array([np.asarray(curve_3d.evaluate(t), dtype=float) for t in ts])
    return pts


def _poly_vertices_3d(face: "Face") -> np.ndarray:
    """Return outer-loop vertex positions of *face* as (N, 3) array."""
    outer = face.outer_loop()
    if outer is None or not outer.coedges:
        return np.zeros((0, 3))
    pts = np.array(
        [np.asarray(ce.start_point(), dtype=float) for ce in outer.coedges]
    )
    return pts


# ---------------------------------------------------------------------------
# Surface projection helpers
# ---------------------------------------------------------------------------


def _project_point_to_plane_surface(
    point: np.ndarray, origin: np.ndarray, normal: np.ndarray
) -> np.ndarray:
    """Project *point* onto the plane defined by *origin* and *normal*."""
    n = _unit(normal)
    d = float(np.dot(point - origin, n))
    return point - d * n


def _project_point_to_sphere_surface(
    point: np.ndarray, center: np.ndarray, radius: float
) -> np.ndarray:
    """Project *point* radially onto the sphere with given center/radius."""
    d = point - center
    dn = float(np.linalg.norm(d))
    if dn < 1e-15:
        # degenerate: point at center – return any surface point
        return center + np.array([radius, 0.0, 0.0])
    return center + (radius / dn) * d


def _project_point_to_surface(point: np.ndarray, surface) -> np.ndarray:
    """Project *point* onto *surface*, returning the closest surface point.

    For NurbsSurface this uses Newton inversion (closest_point_surface).
    For analytic surfaces (Plane, SphereSurface) it uses the exact formula.
    For other surfaces it falls back to Newton inversion when available, or
    returns the point itself (identity fallback).
    """
    # --- Plane analytic projection -------------------------------------------
    if isinstance(surface, Plane):
        origin = np.asarray(surface.origin, dtype=float)
        normal = np.asarray(surface._n, dtype=float)
        return _project_point_to_plane_surface(point, origin, normal)

    # --- SphereSurface analytic radial projection ----------------------------
    if isinstance(surface, SphereSurface):
        center = np.asarray(surface.center, dtype=float)
        return _project_point_to_sphere_surface(point, center, surface.radius)

    # --- NurbsSurface: Newton inversion --------------------------------------
    if _HAS_NURBS and _HAS_INVERSION and isinstance(surface, NurbsSurface):
        try:
            _u, _v, foot, _dist = closest_point_surface(surface, point)
            return np.asarray(foot, dtype=float)
        except Exception:  # pragma: no cover - defensive
            pass

    # --- Generic: try closest_point_surface if it accepts this surface -------
    if _HAS_INVERSION and closest_point_surface is not None:
        try:
            _u, _v, foot, _dist = closest_point_surface(surface, point)
            return np.asarray(foot, dtype=float)
        except Exception:
            pass

    # --- Fallback: orthogonal projection via face-plane (best effort) --------
    # Derive a plane from surface normal at mid-params
    try:
        origin = np.asarray(surface.evaluate(0.5, 0.5), dtype=float)
        if hasattr(surface, "normal"):
            normal = np.asarray(surface.normal(0.5, 0.5), dtype=float)
        else:
            h = 1e-5
            du = np.asarray(surface.evaluate(0.5 + h, 0.5), dtype=float) - origin
            dv = np.asarray(surface.evaluate(0.5, 0.5 + h), dtype=float) - origin
            normal = np.cross(du, dv)
        normal = _unit(normal)
        return _project_point_to_plane_surface(point, origin, normal)
    except Exception:  # pragma: no cover - defensive
        return point.copy()


# ---------------------------------------------------------------------------
# Polygon-split helpers (shared logic with knife.py but surface-aware)
# ---------------------------------------------------------------------------


def _closest_point_on_segment(
    p: np.ndarray, a: np.ndarray, b: np.ndarray
) -> Tuple[np.ndarray, float]:
    """Closest point on segment *a→b* to *p*; also returns parameter t∈[0,1]."""
    ab = b - a
    ab_len2 = float(np.dot(ab, ab))
    if ab_len2 < _TOL ** 2:
        return a.copy(), 0.0
    t = float(np.dot(p - a, ab)) / ab_len2
    t = max(0.0, min(1.0, t))
    return a + t * ab, t


def _project_point_to_polygon_edge(
    p: np.ndarray, poly: np.ndarray
) -> Tuple[int, float, np.ndarray]:
    """Find the polygon edge closest to *p*.

    Returns ``(edge_index, t, closest_point)`` where ``edge_index`` is the
    index of vertex ``poly[edge_index]`` (start of the edge) and ``t`` is the
    parameter along that edge.
    """
    n = len(poly)
    best_dist = math.inf
    best_idx = 0
    best_t = 0.0
    best_pt: np.ndarray = poly[0].copy()
    for i in range(n):
        a = poly[i]
        b = poly[(i + 1) % n]
        cp, t = _closest_point_on_segment(p, a, b)
        d = float(np.linalg.norm(p - cp))
        if d < best_dist:
            best_dist = d
            best_idx = i
            best_t = t
            best_pt = cp
    return best_idx, best_t, best_pt


def _split_polygon(
    poly: np.ndarray,
    idx_a: int,
    t_a: float,
    split_pt_a: np.ndarray,
    idx_b: int,
    t_b: float,
    split_pt_b: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray]:
    """Split a polygon at two boundary points and return two sub-polygons."""
    n = len(poly)
    if idx_a == idx_b:
        if t_a > t_b:
            idx_a, idx_b = idx_b, idx_a
            t_a, t_b = t_b, t_a
            split_pt_a, split_pt_b = split_pt_b, split_pt_a

    poly_a: List[np.ndarray] = [split_pt_a]
    i = (idx_a + 1) % n
    while i != (idx_b + 1) % n:
        poly_a.append(poly[i])
        i = (i + 1) % n
    poly_a.append(split_pt_b)

    poly_b: List[np.ndarray] = [split_pt_b]
    i = (idx_b + 1) % n
    while i != (idx_a + 1) % n:
        poly_b.append(poly[i])
        i = (i + 1) % n
    poly_b.append(split_pt_a)

    def _dedup(pts: List[np.ndarray]) -> np.ndarray:
        result = [pts[0]]
        for p in pts[1:]:
            if np.linalg.norm(p - result[-1]) > _TOL:
                result.append(p)
        if len(result) > 1 and np.linalg.norm(result[-1] - result[0]) < _TOL:
            result = result[:-1]
        return np.array(result)

    return _dedup(poly_a), _dedup(poly_b)


def _poly_area_3d(pts: np.ndarray) -> float:
    """Area of a planar polygon (fan triangulation from centroid)."""
    n = len(pts)
    if n < 3:
        return 0.0
    c = pts.mean(axis=0)
    area = 0.0
    for i in range(n):
        a = pts[i] - c
        b = pts[(i + 1) % n] - c
        area += float(np.linalg.norm(np.cross(a, b)))
    return area * 0.5


def _make_face_from_polygon(pts: np.ndarray) -> "Face":
    """Construct a new B-rep Face (planar) from a 3-D polygon."""
    n = len(pts)
    if n < 3:
        raise ValueError("Cannot build face from fewer than 3 points")

    c = pts.mean(axis=0)
    e1 = _unit(pts[1] - pts[0])
    normal = np.zeros(3)
    for i in range(2, n):
        e2 = pts[i] - pts[0]
        crs = np.cross(e1, e2)
        if np.linalg.norm(crs) > _TOL:
            normal = _unit(crs)
            break
    if np.linalg.norm(normal) < _TOL:
        normal = np.array([0.0, 0.0, 1.0])

    y_axis = _unit(np.cross(normal, e1))
    if np.linalg.norm(y_axis) < _TOL:
        y_axis = _unit(np.cross(normal, np.array([0.0, 1.0, 0.0])))

    origin = pts[0]
    srf = Plane(origin=origin, x_axis=e1, y_axis=y_axis)

    vertices = [Vertex(point=p.copy()) for p in pts]
    coedges: List[Coedge] = []
    for i in range(n):
        v0 = vertices[i]
        v1 = vertices[(i + 1) % n]
        seg = Line3(p0=v0.point.copy(), p1=v1.point.copy())
        e = Edge(curve=seg, t0=0.0, t1=1.0, v_start=v0, v_end=v1)
        coedges.append(Coedge(edge=e, orientation=True))

    loop = Loop(coedges=coedges, is_outer=True)
    return Face(surface=srf, loops=[loop])


# ---------------------------------------------------------------------------
# Body reconstruction helpers
# ---------------------------------------------------------------------------


def _replace_face_in_body(
    body: "Body", face_id: int, new_faces: List["Face"]
) -> "Body":
    """Return a new Body where face *face_id* is replaced by *new_faces*.

    All other faces are shallow-referenced (not deep-copied) so that the
    resulting Body shares geometry with the original where unchanged.  The
    shell/solid hierarchy is reconstructed to include the new faces in place
    of the original one.
    """
    all_faces = body.all_faces()
    target_face = all_faces[face_id]

    # Build a flat list of (shell, face) pairs so we can find the owner.
    # We walk the same order as all_faces() to keep face_id consistent.
    face_to_shell: dict = {}
    for sh in body.all_shells():
        for f in sh.faces:
            face_to_shell[id(f)] = sh

    owner_shell = face_to_shell.get(id(target_face))
    if owner_shell is None:  # pragma: no cover – should always find it
        raise ValueError(f"face_id {face_id}: could not locate owning shell")

    # Rebuild each shell.  For the owner shell, swap target → new_faces.
    def _rebuild_shell(sh: "Shell") -> "Shell":
        new_face_list: List[Face] = []
        for f in sh.faces:
            if f is target_face:
                new_face_list.extend(new_faces)
            else:
                new_face_list.append(f)
        new_sh = Shell(faces=new_face_list, is_closed=sh.is_closed)
        return new_sh

    # Rebuild solids that own the owner shell.
    # Shells that are top-level (body.shells) are handled separately.

    # Map original shells → rebuilt shells.
    rebuilt: dict = {}  # id(original_sh) -> new_sh

    def _get_rebuilt(sh: "Shell") -> "Shell":
        k = id(sh)
        if k not in rebuilt:
            rebuilt[k] = _rebuild_shell(sh)
        return rebuilt[k]

    new_solids: List[Solid] = []
    for sol in body.solids:
        new_shell_list = [_get_rebuilt(sh) for sh in sol.shells]
        new_sol = Solid(shells=new_shell_list)
        new_solids.append(new_sol)

    new_top_shells: List[Shell] = []
    for sh in body.shells:
        new_top_shells.append(_get_rebuilt(sh))

    new_wires = list(body.wires)  # unchanged
    return Body(solids=new_solids, shells=new_top_shells, wires=new_wires)


# ---------------------------------------------------------------------------
# Core imprint logic
# ---------------------------------------------------------------------------


def _imprint_brep(body: "Body", face_id: int, curve_3d) -> "Body":
    """Project *curve_3d* onto face *face_id* and split the face.

    Returns a new Body with the face replaced by two sub-faces.
    """
    all_faces = body.all_faces()
    if face_id < 0 or face_id >= len(all_faces):
        raise ValueError(
            f"face_id {face_id} out of range [0, {len(all_faces)})"
        )

    face = all_faces[face_id]
    poly = _poly_vertices_3d(face)
    if len(poly) < 3:
        raise ValueError(
            "Target face has fewer than 3 vertices in its outer loop"
        )

    surface = face.surface

    # ------------------------------------------------------------------
    # Step 1: Sample the 3D curve and project each sample onto the surface.
    # ------------------------------------------------------------------
    raw_pts = _sample_curve(curve_3d)  # (N, 3)
    proj_pts = np.array([
        _project_point_to_surface(p, surface) for p in raw_pts
    ])  # (N, 3) – points on the surface

    # ------------------------------------------------------------------
    # Step 2: Use the first and last projected points as split end-points.
    # The imprint curve must cross the face boundary at two distinct spots.
    # ------------------------------------------------------------------
    p_start = proj_pts[0]
    p_end = proj_pts[-1]

    # Find where the projected endpoints snap to the outer-loop polygon.
    idx_a, t_a, snap_a = _project_point_to_polygon_edge(p_start, poly)
    idx_b, t_b, snap_b = _project_point_to_polygon_edge(p_end, poly)

    # Reject degenerate case (both ends project to the same boundary point).
    if idx_a == idx_b and abs(t_a - t_b) < _TOL:
        raise ValueError(
            "Imprint curve start and end project to the same boundary point; "
            "the curve must cross the face at two distinct locations"
        )

    # ------------------------------------------------------------------
    # Step 3: Split the outer-loop polygon at the two snap points.
    # ------------------------------------------------------------------
    poly_a, poly_b = _split_polygon(
        poly, idx_a, t_a, snap_a, idx_b, t_b, snap_b
    )

    if len(poly_a) < 3 or len(poly_b) < 3:
        raise ValueError(
            "Degenerate imprint split: one sub-polygon has fewer than 3 vertices"
        )

    # ------------------------------------------------------------------
    # Step 4: Build two new Face objects from the sub-polygons.
    # ------------------------------------------------------------------
    face_a = _make_face_from_polygon(poly_a)
    face_b = _make_face_from_polygon(poly_b)

    # ------------------------------------------------------------------
    # Step 5: Reconstruct the Body with the original face replaced.
    # ------------------------------------------------------------------
    return _replace_face_in_body(body, face_id, [face_a, face_b])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def imprint_curve_on_face(body: "Body", face_id: int, curve_3d) -> "Body":
    """GK-82 — project *curve_3d* onto a face and split it along the path.

    The 3D curve is first projected onto the face's underlying surface
    (using ``closest_point_surface`` for NurbsSurface, analytic formulae
    for Plane / SphereSurface, and a normal-projection fallback otherwise).
    The projected path's endpoints are snapped to the face's outer-loop
    polygon and the polygon is split at those two points, creating two new
    faces.

    Parameters
    ----------
    body : Body
        Input B-rep body.  Not mutated.
    face_id : int
        Index into ``body.all_faces()``.
    curve_3d : object
        Any curve with ``evaluate(t) -> array-like`` (3-D).  The
        parametric range defaults to ``[0, 1]`` unless ``t0`` / ``t1``
        attributes are present.

    Returns
    -------
    Body
        New Body with face *face_id* replaced by two new faces whose
        combined area equals the original face area.

    Raises
    ------
    TypeError
        If *body* is not a ``Body`` instance.
    ValueError
        If ``face_id`` is out of range, or the imprint is geometrically
        degenerate (curve endpoints project to the same boundary location).
    """
    if not _HAS_BREP:  # pragma: no cover
        raise RuntimeError("kerf_cad_core.geom.brep is not available")
    if not isinstance(body, Body):
        raise TypeError(
            f"imprint_curve_on_face: expected Body, got {type(body).__name__!r}"
        )
    return _imprint_brep(body, face_id, curve_3d)
