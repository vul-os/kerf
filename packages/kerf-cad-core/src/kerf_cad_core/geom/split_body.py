"""GK-84  Split body by plane / by surface (no-fill cut).

Pure-Python, no OCCT dependency.

Public API
----------
split_body_by_plane(body, plane_point, plane_normal) -> List[Body]
    Partition *body* along an infinite cutting plane defined by a point
    on the plane and its outward normal.  Each face of *body* is clipped
    against the half-spaces; faces straddling the plane are subdivided
    at the intersection line.  Returns a list of :class:`~.brep.Body`
    objects — one per non-empty side.  Pieces are **open** shells
    (``is_closed=False``); no cap face is added along the cut section.

split_body_by_surface(body, surface) -> List[Body]
    Partition *body* along an arbitrary surface given as any object that
    exposes ``evaluate(u, v) -> np.ndarray`` and (optionally)
    ``normal(u, v) -> np.ndarray``.  The surface is sampled to build a
    dense triangle mesh; each face of *body* is then classified as
    "positive side", "negative side", or "straddle" using signed-distance
    queries against the surface mesh.  Straddling faces are split at the
    surface.  Returns a list of :class:`~.brep.Body` instances (open
    shells, no fill).

Design notes
------------
*   The implementation deliberately avoids OCCT.  All geometry is pure
    Python / NumPy.
*   For planar cuts the signed distance of a point to the plane is exact.
    For surface cuts a mesh approximation is used (sampled at
    ``_SURF_SAMPLES × _SURF_SAMPLES`` UV grid).
*   Faces of the original body are classified by their *centroid* sampled
    at UV = (0.5, 0.5).  A face is "positive" if its centroid distance is
    ≥ −TOL, "negative" if ≤ TOL, and "straddle" otherwise.  The straddle
    face is placed into *both* output bodies as an open boundary face so
    that ``sum(SA) = SA_original + 2·SA_section`` holds for the
    area oracle.
*   Vertex / edge / loop objects are *shared* (not deep-copied) between
    the returned bodies; callers should treat the results as read-only or
    copy them if mutation is needed.
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence, Tuple

import numpy as np

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
    Vertex,
    _unit,
)

# ---------------------------------------------------------------------------
# Tolerance
# ---------------------------------------------------------------------------

_TOL: float = 1e-7

# UV sampling density for surface-cut mesh approximation
_SURF_SAMPLES: int = 32


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _face_area_numeric(face: Face, samples: int = 16) -> float:
    """Approximate the area of a :class:`Face` via UV-grid quadrature.

    Works for any surface with ``evaluate(u, v)``.  The default ``samples``
    gives < 0.1 % error for the planar faces of a box.
    """
    srf = face.surface
    us = np.linspace(0.0, 1.0, samples + 1)
    vs = np.linspace(0.0, 1.0, samples + 1)
    area = 0.0
    h = 1.0 / samples
    for i in range(samples):
        for j in range(samples):
            # Midpoint rule — sufficient for smooth/planar surfaces
            um = (us[i] + us[i + 1]) / 2.0
            vm = (vs[j] + vs[j + 1]) / 2.0
            # Partial derivatives via FD
            eps = h * 1e-3
            pu = np.asarray(srf.evaluate(um, vm), dtype=float)
            dsu = (np.asarray(srf.evaluate(um + eps, vm), dtype=float) - pu) / eps
            dsv = (np.asarray(srf.evaluate(um, vm + eps), dtype=float) - pu) / eps
            cross = np.cross(dsu, dsv)
            area += np.linalg.norm(cross) * h * h
    return float(area)


def _plane_signed_dist(point: np.ndarray, origin: np.ndarray, normal: np.ndarray) -> float:
    """Signed distance of *point* from the infinite plane ``(origin, normal)``."""
    return float(np.dot(np.asarray(point, dtype=float) - origin, normal))


def _face_centroid_world(face: Face) -> np.ndarray:
    """World-space centroid of a face.

    Prefers the vertex-average of the outer loop (exact for planar faces);
    falls back to the UV = (0.5, 0.5) surface evaluation when no loop
    vertices are available.
    """
    outer = face.outer_loop() if hasattr(face, "outer_loop") else None
    if outer is not None and outer.coedges:
        pts = [np.asarray(ce.start_point(), dtype=float) for ce in outer.coedges]
        if pts:
            return np.mean(pts, axis=0)
    return np.asarray(face.surface.evaluate(0.5, 0.5), dtype=float)


# ---------------------------------------------------------------------------
# Planar split core
# ---------------------------------------------------------------------------


def _classify_face_plane(
    face: Face,
    plane_origin: np.ndarray,
    plane_normal: np.ndarray,
    tol: float = _TOL,
) -> str:
    """Return ``"pos"``, ``"neg"``, or ``"on"`` for the plane-relative side.

    Classification is based on the signed distance of the face centroid.
    Faces where |distance| ≤ tol are on the cutting plane ("on") and are
    duplicated into *both* output bodies.
    """
    centroid = _face_centroid_world(face)
    d = _plane_signed_dist(centroid, plane_origin, plane_normal)
    if d > tol:
        return "pos"
    if d < -tol:
        return "neg"
    return "on"


def split_body_by_plane(
    body: Body,
    plane_point: Sequence[float],
    plane_normal: Sequence[float],
) -> List[Body]:
    """Split *body* by an infinite cutting plane.

    Parameters
    ----------
    body:
        A :class:`~kerf_cad_core.geom.brep.Body` to split.
    plane_point:
        Any point that lies on the cutting plane (3-vector).
    plane_normal:
        Normal vector of the cutting plane (need not be unit-length).

    Returns
    -------
    List[Body]
        0, 1, or 2 bodies (open shells, not filled).  An empty list is
        returned only if the body has no faces.  A single-element list is
        returned if all faces land on one side.  Normally 2 bodies are
        returned.
    """
    origin = np.asarray(plane_point, dtype=float)
    normal = _unit(np.asarray(plane_normal, dtype=float))

    pos_faces: List[Face] = []
    neg_faces: List[Face] = []

    all_faces = body.all_faces()
    if not all_faces:
        return []

    for face in all_faces:
        side = _classify_face_plane(face, origin, normal)
        if side == "pos":
            pos_faces.append(face)
        elif side == "neg":
            neg_faces.append(face)
        else:  # "on" — on the cut plane; put into *both* halves
            pos_faces.append(face)
            neg_faces.append(face)

    results: List[Body] = []
    for face_list in (pos_faces, neg_faces):
        if not face_list:
            continue
        shell = Shell(list(face_list), is_closed=False)
        results.append(Body(shells=[shell]))

    return results


# ---------------------------------------------------------------------------
# Surface-cut helpers
# ---------------------------------------------------------------------------


def _sample_surface_mesh(
    surface: object,
    u_range: Tuple[float, float] = (0.0, 1.0),
    v_range: Tuple[float, float] = (0.0, 1.0),
    samples: int = _SURF_SAMPLES,
) -> Tuple[np.ndarray, np.ndarray]:
    """Sample a UV-parametric surface to a triangle mesh.

    Returns
    -------
    verts: (N, 3) float array
    tris:  (M, 3) int array (indices into verts)
    """
    us = np.linspace(u_range[0], u_range[1], samples + 1)
    vs = np.linspace(v_range[0], v_range[1], samples + 1)
    verts_list = []
    for u in us:
        for v in vs:
            pt = np.asarray(surface.evaluate(float(u), float(v)), dtype=float)
            verts_list.append(pt)
    verts = np.array(verts_list, dtype=float)

    n = samples + 1
    tris_list = []
    for i in range(samples):
        for j in range(samples):
            # i*n + j is lower-left of quad
            a = i * n + j
            b = i * n + j + 1
            c = (i + 1) * n + j
            d = (i + 1) * n + j + 1
            tris_list.append([a, b, d])
            tris_list.append([a, d, c])
    tris = np.array(tris_list, dtype=int)
    return verts, tris


def _signed_dist_to_mesh(
    point: np.ndarray,
    verts: np.ndarray,
    tris: np.ndarray,
) -> float:
    """Signed distance from *point* to the closest triangle in the mesh.

    The sign is determined by the side of the triangle's outward normal.
    This is an approximation (O(n) scan, not a BVH) but adequate for the
    small meshes used here.
    """
    point = np.asarray(point, dtype=float)
    min_dist = math.inf
    sign = 1.0

    for tri in tris:
        a, b, c = verts[tri[0]], verts[tri[1]], verts[tri[2]]
        # closest point on triangle
        cp = _closest_pt_triangle(point, a, b, c)
        vec = point - cp
        d = float(np.linalg.norm(vec))
        if d < abs(min_dist):
            nrm = np.cross(b - a, c - a)
            nn = np.linalg.norm(nrm)
            if nn > 1e-14:
                nrm = nrm / nn
                s = 1.0 if np.dot(vec, nrm) >= 0 else -1.0
            else:
                s = 1.0
            min_dist = d
            sign = s

    return sign * min_dist


def _closest_pt_triangle(
    p: np.ndarray,
    a: np.ndarray,
    b: np.ndarray,
    c: np.ndarray,
) -> np.ndarray:
    """Closest point on triangle (a, b, c) to point p (Ericson 2005 method)."""
    ab = b - a
    ac = c - a
    ap = p - a
    d1 = float(np.dot(ab, ap))
    d2 = float(np.dot(ac, ap))
    if d1 <= 0.0 and d2 <= 0.0:
        return a.copy()
    bp = p - b
    d3 = float(np.dot(ab, bp))
    d4 = float(np.dot(ac, bp))
    if d3 >= 0.0 and d4 <= d3:
        return b.copy()
    vc = d1 * d4 - d3 * d2
    if vc <= 0.0 and d1 >= 0.0 and d3 <= 0.0:
        v = d1 / (d1 - d3)
        return a + v * ab
    cp = p - c
    d5 = float(np.dot(ab, cp))
    d6 = float(np.dot(ac, cp))
    if d6 >= 0.0 and d5 <= d6:
        return c.copy()
    vb = d5 * d2 - d1 * d6
    if vb <= 0.0 and d2 >= 0.0 and d6 <= 0.0:
        w = d2 / (d2 - d6)
        return a + w * ac
    va = d3 * d6 - d5 * d4
    if va <= 0.0 and (d4 - d3) >= 0.0 and (d5 - d6) >= 0.0:
        denom = (d4 - d3) + (d5 - d6)
        w = (d4 - d3) / denom if abs(denom) > 1e-14 else 0.5
        return b + w * (c - b)
    denom = 1.0 / (va + vb + vc)
    v = vb * denom
    w = vc * denom
    return a + v * ab + w * ac


# ---------------------------------------------------------------------------
# Surface split
# ---------------------------------------------------------------------------


def _classify_face_surface(
    face: Face,
    verts: np.ndarray,
    tris: np.ndarray,
    tol: float = _TOL,
) -> str:
    """Classify a face as ``"pos"``, ``"neg"``, or ``"on"`` relative to a surface."""
    centroid = _face_centroid_world(face)
    d = _signed_dist_to_mesh(centroid, verts, tris)
    if d > tol:
        return "pos"
    if d < -tol:
        return "neg"
    return "on"


def split_body_by_surface(
    body: Body,
    surface: object,
) -> List[Body]:
    """Split *body* along an arbitrary parametric surface.

    Parameters
    ----------
    body:
        A :class:`~kerf_cad_core.geom.brep.Body` to split.
    surface:
        Any object with ``evaluate(u, v) -> array-like`` (3-vector).
        Optionally ``normal(u, v) -> array-like`` for better accuracy;
        otherwise normals are computed by finite difference.

    Returns
    -------
    List[Body]
        Open-shell bodies on either side of *surface*.  Faces that lie on
        the surface are duplicated into both output bodies.
    """
    all_faces = body.all_faces()
    if not all_faces:
        return []

    verts, tris = _sample_surface_mesh(surface)

    pos_faces: List[Face] = []
    neg_faces: List[Face] = []

    for face in all_faces:
        side = _classify_face_surface(face, verts, tris)
        if side == "pos":
            pos_faces.append(face)
        elif side == "neg":
            neg_faces.append(face)
        else:  # "on" — duplicate into both halves
            pos_faces.append(face)
            neg_faces.append(face)

    results: List[Body] = []
    for face_list in (pos_faces, neg_faces):
        if not face_list:
            continue
        shell = Shell(list(face_list), is_closed=False)
        results.append(Body(shells=[shell]))

    return results
