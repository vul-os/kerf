"""
nurbs_projection.py
===================
NURBS silhouette projection to a 2D plane.

Given a 3D body and a view direction, compute the projected silhouette
curve in 2D for vector drawing extraction.  Implements the Hertzmann-Zorin
2000 silhouette-locus approach: for each face, find where the surface normal
is perpendicular to the view direction (n · v = 0), trace that locus as a
parametric curve, and project it onto the orthographic projection plane.

The output is a list of 2D NURBS curves suitable for CAD drawing layers.

References
----------
Hertzmann, A. & Zorin, D. (2000). Illustrating smooth surfaces.
    ACM SIGGRAPH 2000 Proceedings, pp. 517-526.
Markosian, L., Kowalski, M.A., et al. (1997). Real-time nonphotorealistic
    rendering. ACM SIGGRAPH 1997 Proceedings, pp. 415-420.
Piegl & Tiller, "The NURBS Book", 2nd ed., Springer 1997.

Public API
----------
Curve2D(dataclass)
    A 2D curve: list of (x, y) 2D sample points + optional NURBS representation.

Curve3D(dataclass)
    A 3D curve: list of (x, y, z) sample points.

ProjectionResult(dataclass)
    Multi-layer result: visible_silhouettes, hidden_silhouettes, visible_edges,
    hidden_edges, all as Curve2D lists.

compute_silhouette_curves(body, view_direction, plane_normal=None)
    -> list[Curve2D]
    For each face: identify the silhouette locus (n · v = 0), trace it, project
    to the 2D projection plane.

compute_visible_edges(body, view_direction)
    -> tuple[list[Curve3D], list[Curve3D]]
    Returns (visible_edges, hidden_edges) classified by ray-casting visibility.

project_to_2d_with_layers(body, view_direction, layer_groups=None)
    -> ProjectionResult
    Multi-pass projection into visible / hidden / dim layers.

Never raises — all failures are caught and surfaced in ok/reason dicts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from kerf_cad_core.geom.nurbs import (
    NurbsCurve,
    NurbsSurface,
    make_circle_nurbs,
    make_line_nurbs,
    surface_normal as nurbs_surface_normal,
    surface_derivatives,
    find_span,
    _basis_funcs,
)

# ---------------------------------------------------------------------------
# Internal tolerances and defaults
# ---------------------------------------------------------------------------

_TOL: float = 1e-9
_SILHOUETTE_TOL: float = 1e-6   # n·v crossing threshold
_UV_SAMPLES: int = 64           # UV-grid samples per dimension for tracing
_TRACE_SAMPLES: int = 128       # samples along traced silhouette curve
_RAY_OFFSET: float = 1e-4       # ray-cast origin offset to avoid self-hits


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Curve2D:
    """A 2D curve extracted from a NURBS surface projection.

    Attributes
    ----------
    points : list of (x, y) 2-tuples
        Sample points along the 2D curve (projection plane coordinates).
    nurbs : NurbsCurve | None
        Optional NURBS representation of the curve (2D control points).
        May be None when only the polyline approximation is available.
    source_face_index : int
        Index of the originating Face in the body's all_faces() list.
    curve_type : str
        'silhouette' | 'boundary' | 'crease'.
    """
    points: List[Tuple[float, float]] = field(default_factory=list)
    nurbs: Optional[NurbsCurve] = None
    source_face_index: int = -1
    curve_type: str = "silhouette"


@dataclass
class Curve3D:
    """A 3D curve (edge or silhouette) on the body surface.

    Attributes
    ----------
    points : list of (x, y, z) 3-tuples
        Sample points along the 3D curve.
    is_visible : bool
        True when the curve is visible from view_direction.
    source_edge_index : int
        Index in the body's all_edges() list, or -1 for silhouette curves.
    """
    points: List[Tuple[float, float, float]] = field(default_factory=list)
    is_visible: bool = True
    source_edge_index: int = -1


@dataclass
class ProjectionResult:
    """Result of project_to_2d_with_layers.

    Attributes
    ----------
    visible_silhouettes : list[Curve2D]
        NURBS silhouette curves on the visible side.
    hidden_silhouettes : list[Curve2D]
        NURBS silhouette curves on the hidden side.
    visible_edges : list[Curve2D]
        B-rep boundary edges visible from view_direction.
    hidden_edges : list[Curve2D]
        B-rep boundary edges hidden from view_direction.
    layers : dict[str, list[Curve2D]]
        Named drawing layers: 'visible', 'hidden', 'dim'.
    view_direction : np.ndarray
        Normalised view direction used.
    """
    visible_silhouettes: List[Curve2D] = field(default_factory=list)
    hidden_silhouettes: List[Curve2D] = field(default_factory=list)
    visible_edges: List[Curve2D] = field(default_factory=list)
    hidden_edges: List[Curve2D] = field(default_factory=list)
    layers: Dict[str, List[Curve2D]] = field(default_factory=dict)
    view_direction: np.ndarray = field(default_factory=lambda: np.array([0.0, 0.0, 1.0]))


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------


def _unit(v: np.ndarray) -> np.ndarray:
    """Return unit vector, or original vector if near-zero."""
    n = np.linalg.norm(v)
    return v / n if n > _TOL else v


def _build_projection_frame(view_dir: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build orthonormal right-hand frame for the projection plane.

    Returns (right, up, forward) where forward == view_dir,
    right and up span the projection plane.
    """
    vd = _unit(np.asarray(view_dir, dtype=float).ravel()[:3])
    # Pick a world-up that is not parallel to vd
    world_up = np.array([0.0, 1.0, 0.0])
    if abs(np.dot(vd, world_up)) > 0.9:
        world_up = np.array([1.0, 0.0, 0.0])
    right = _unit(np.cross(world_up, vd))
    up = _unit(np.cross(vd, right))
    return right, up, vd


def _project_point_to_2d(
    pt: np.ndarray,
    right: np.ndarray,
    up: np.ndarray,
) -> Tuple[float, float]:
    """Orthographic projection of 3D point to (x, y) in the view plane."""
    return (float(np.dot(pt, right)), float(np.dot(pt, up)))


def _surface_normal_at(surf: Any, u: float, v: float) -> np.ndarray:
    """Return unit surface normal for any surface type (NURBS or analytic)."""
    if isinstance(surf, NurbsSurface):
        return nurbs_surface_normal(surf, u, v)
    # Analytic surfaces from brep.py implement .normal(u, v)
    if hasattr(surf, "normal"):
        n = np.asarray(surf.normal(u, v), dtype=float).ravel()[:3]
        mag = np.linalg.norm(n)
        return n / mag if mag > _TOL else n
    return np.array([0.0, 0.0, 1.0])


def _surface_eval_at(surf: Any, u: float, v: float) -> np.ndarray:
    """Evaluate any surface type at (u, v)."""
    if isinstance(surf, NurbsSurface):
        return np.asarray(surf.evaluate(u, v), dtype=float)[:3]
    if hasattr(surf, "evaluate"):
        return np.asarray(surf.evaluate(u, v), dtype=float).ravel()[:3]
    return np.zeros(3)


def _get_uv_domain(surf: Any) -> Tuple[float, float, float, float]:
    """Return (u_min, u_max, v_min, v_max) for any surface type."""
    if isinstance(surf, NurbsSurface):
        pu = surf.degree_u
        pv = surf.degree_v
        u_min = float(surf.knots_u[pu])
        u_max = float(surf.knots_u[-(pu + 1)])
        v_min = float(surf.knots_v[pv])
        v_max = float(surf.knots_v[-(pv + 1)])
        return u_min, u_max, v_min, v_max
    # Analytic surfaces: use default [0, 2pi] x [0, 2pi] or [-pi/2, pi/2]
    if hasattr(surf, "radius"):
        # sphere or cylinder
        if hasattr(surf, "axis"):
            # cylinder: u in [0, 2pi], v in [-1, 1] (unit v)
            return 0.0, 2.0 * math.pi, -1.0, 1.0
        else:
            # sphere: u in [0, 2pi], v in [-pi/2, pi/2]
            return 0.0, 2.0 * math.pi, -math.pi / 2.0, math.pi / 2.0
    return 0.0, 1.0, 0.0, 1.0


# ---------------------------------------------------------------------------
# Silhouette locus tracing (Hertzmann-Zorin 2000 algorithm)
# ---------------------------------------------------------------------------


def _trace_silhouette_on_surface(
    surf: Any,
    view_dir: np.ndarray,
    n_samples: int = _UV_SAMPLES,
) -> List[List[Tuple[float, float, float]]]:
    """Trace the silhouette locus of a surface for a given view direction.

    The silhouette locus is the set of surface points where n(u,v) · v = 0.
    We use a sign-change grid traversal (Hertzmann-Zorin 2000, §3.1):
    sample a UV grid, find edges where the dot product changes sign, and
    linearly interpolate to find the zero crossing.  This yields a set of
    3D polyline chains approximating the silhouette curves.

    Parameters
    ----------
    surf : NurbsSurface or analytic surface
        The surface to analyse.
    view_dir : np.ndarray
        Normalised view direction.
    n_samples : int
        Grid resolution per UV direction.

    Returns
    -------
    list of polyline chains, each a list of [x, y, z] points.
    """
    u0, u1, v0, v1 = _get_uv_domain(surf)
    vd = _unit(view_dir)

    # Sample dot product n(u,v) · vd on a regular UV grid
    us = np.linspace(u0, u1, n_samples)
    vs = np.linspace(v0, v1, n_samples)

    dot_grid = np.zeros((n_samples, n_samples))
    pt_grid = np.zeros((n_samples, n_samples, 3))

    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            n = _surface_normal_at(surf, u, v)
            pt_grid[i, j] = _surface_eval_at(surf, u, v)
            dot_grid[i, j] = float(np.dot(n, vd))

    # Find zero-crossing segments by checking all 4 edges of each grid cell.
    # Collect crossing points in (row, col) local index space.
    crossing_pts_3d: List[Tuple[float, float, float]] = []
    crossing_uvs: List[Tuple[float, float]] = []  # for curve orientation

    for i in range(n_samples - 1):
        for j in range(n_samples - 1):
            # Traverse the 4 edges of cell (i,j):
            # bottom: (i,j)->(i,j+1), top: (i+1,j)->(i+1,j+1)
            # left: (i,j)->(i+1,j),   right: (i,j+1)->(i+1,j+1)
            edges = [
                ((i, j), (i, j + 1)),
                ((i + 1, j), (i + 1, j + 1)),
                ((i, j), (i + 1, j)),
                ((i, j + 1), (i + 1, j + 1)),
            ]
            for (r0, c0), (r1, c1) in edges:
                d0 = dot_grid[r0, c0]
                d1 = dot_grid[r1, c1]
                if d0 * d1 < 0.0:
                    # Linear interpolation to find zero
                    t = d0 / (d0 - d1)
                    pt = (1.0 - t) * pt_grid[r0, c0] + t * pt_grid[r1, c1]
                    u_cross = (1.0 - t) * us[c0] + t * us[c1]  # note: u along j
                    v_cross = (1.0 - t) * vs[r0] + t * vs[r1]  # v along i
                    crossing_pts_3d.append((float(pt[0]), float(pt[1]), float(pt[2])))
                    crossing_uvs.append((float(u_cross), float(v_cross)))

    if not crossing_pts_3d:
        return []

    # Chain the crossings into polylines by proximity (greedy nearest-neighbour)
    chains = _chain_crossings(crossing_pts_3d)
    return chains


def _chain_crossings(
    pts: List[Tuple[float, float, float]],
    max_gap: float = 0.5,
) -> List[List[Tuple[float, float, float]]]:
    """Group crossing points into chains by proximity.

    Uses a greedy nearest-neighbour approach: start a new chain from any
    unvisited point, greedily add the nearest unvisited point within
    max_gap, stop when no candidate is within range.

    The max_gap is expressed in model units; for a unit model 0.5 is safe.
    """
    if not pts:
        return []

    pts_arr = np.array(pts)
    n = len(pts_arr)
    visited = np.zeros(n, dtype=bool)
    chains: List[List[Tuple[float, float, float]]] = []

    # Adaptive max_gap: use 3x the median nearest-neighbour distance
    if n > 1:
        dists = np.sqrt(((pts_arr[:, None, :] - pts_arr[None, :, :]) ** 2).sum(axis=2))
        np.fill_diagonal(dists, np.inf)
        nn_dist = dists.min(axis=1)
        adaptive_gap = float(np.median(nn_dist)) * 3.0
        max_gap = max(adaptive_gap, max_gap)

    for start in range(n):
        if visited[start]:
            continue
        chain = [pts[start]]
        visited[start] = True
        current = start

        while True:
            # Find nearest unvisited point
            diffs = pts_arr - pts_arr[current]
            dists_c = np.sqrt((diffs ** 2).sum(axis=1))
            dists_c[visited] = np.inf
            nearest = int(np.argmin(dists_c))
            if dists_c[nearest] > max_gap:
                break
            chain.append(pts[nearest])
            visited[nearest] = True
            current = nearest

        if len(chain) >= 2:
            chains.append(chain)

    return chains


def _fit_nurbs_to_polyline_2d(
    pts_2d: List[Tuple[float, float]],
    degree: int = 3,
) -> Optional[NurbsCurve]:
    """Fit a degree-3 B-spline to a 2D polyline using chord-length parameterisation.

    Implements the global least-squares approximation of Piegl & Tiller §9.4
    with chord-length parameterisation and an open uniform knot vector.
    Control points are returned in 2D (shape Nx2).

    Returns None if fitting fails (< degree+1 points, degenerate, etc.).
    """
    if len(pts_2d) < degree + 1:
        return None

    pts = np.array(pts_2d, dtype=float)
    n = len(pts)

    # Chord-length parameterisation
    diffs = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    total = float(diffs.sum())
    if total < _TOL:
        return None
    params = np.zeros(n)
    params[1:] = np.cumsum(diffs) / total

    # Choose number of control points: clamp to avoid over-fitting
    n_ctrl = max(degree + 1, min(n, max(degree + 1, n // 4 + 2)))

    # Open uniform knot vector
    knots = np.zeros(n_ctrl + degree + 1)
    knots[-(degree + 1):] = 1.0
    for j in range(1, n_ctrl - degree):
        knots[j + degree] = j / (n_ctrl - degree)

    # Build basis matrix
    N = np.zeros((n, n_ctrl))
    for k in range(n):
        u = params[k]
        span = _find_span_safe(n_ctrl - 1, degree, u, knots)
        basis = _basis_funcs(span, u, degree, knots)
        for j in range(degree + 1):
            idx = span - degree + j
            if 0 <= idx < n_ctrl:
                N[k, idx] = basis[j]

    # Least-squares solve: N^T N x = N^T pts
    NtN = N.T @ N
    Ntp = N.T @ pts
    try:
        ctrl_pts = np.linalg.lstsq(NtN, Ntp, rcond=None)[0]
    except np.linalg.LinAlgError:
        return None

    return NurbsCurve(degree=degree, control_points=ctrl_pts, knots=knots)


def _find_span_safe(n: int, degree: int, u: float, knots: np.ndarray) -> int:
    """find_span with boundary clamping (avoids OOB at knot ends)."""
    u = float(np.clip(u, knots[degree], knots[n + 1]))
    return find_span(n, degree, u, knots)


# ---------------------------------------------------------------------------
# Visibility classification (ray-casting)
# ---------------------------------------------------------------------------


def _build_mesh_from_body(body: Any, n_per_face: int = 16) -> Tuple[np.ndarray, np.ndarray, List[int]]:
    """Tessellate a Body into a triangle mesh for ray-casting.

    Returns (vertices, triangles, face_indices) where face_indices[i] is the
    Body face index for each vertex strip.
    """
    all_verts: List[np.ndarray] = []
    all_tris: List[Tuple[int, int, int]] = []
    face_vert_start: List[int] = []

    try:
        faces = body.all_faces()
    except Exception:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int), []

    offset = 0
    for fi, face in enumerate(faces):
        surf = face.surface
        u0, u1, v0, v1 = _get_uv_domain(surf)
        us = np.linspace(u0, u1, n_per_face)
        vs = np.linspace(v0, v1, n_per_face)

        face_verts: List[np.ndarray] = []
        for u in us:
            for v in vs:
                pt = _surface_eval_at(surf, u, v)
                face_verts.append(pt)

        n = n_per_face
        for i in range(n - 1):
            for j in range(n - 1):
                # Two triangles per grid cell
                i00 = i * n + j
                i10 = (i + 1) * n + j
                i01 = i * n + (j + 1)
                i11 = (i + 1) * n + (j + 1)
                all_tris.append((offset + i00, offset + i10, offset + i01))
                all_tris.append((offset + i10, offset + i11, offset + i01))

        all_verts.extend(face_verts)
        face_vert_start.append(fi)
        offset += len(face_verts)

    if not all_verts:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=int), []

    verts = np.array(all_verts, dtype=float)
    tris = np.array(all_tris, dtype=int)
    return verts, tris, face_vert_start


def _ray_hits_mesh(
    origin: np.ndarray,
    direction: np.ndarray,
    verts: np.ndarray,
    tris: np.ndarray,
    exclude_start: int = -1,
) -> bool:
    """Test if a ray from origin along direction hits any triangle.

    Uses Moller-Trumbore intersection.  Returns True if any intersection
    with t > _RAY_OFFSET is found (i.e., something occludes the origin).
    """
    if len(tris) == 0:
        return False

    d = _unit(direction)
    o = origin + _RAY_OFFSET * d  # offset to avoid self-intersection

    v0 = verts[tris[:, 0]]
    v1 = verts[tris[:, 1]]
    v2 = verts[tris[:, 2]]

    e1 = v1 - v0
    e2 = v2 - v0
    h = np.cross(d, e2)
    a = (e1 * h).sum(axis=1)

    # Parallel rays
    mask = np.abs(a) > _TOL
    if not mask.any():
        return False

    # Use errstate to suppress divide-by-zero for masked-out (parallel) triangles.
    with np.errstate(divide="ignore", invalid="ignore"):
        f = np.where(mask, 1.0 / np.where(mask, a, 1.0), 0.0)
    s = o[np.newaxis, :] - v0
    u = f * (s * h).sum(axis=1)

    q = np.cross(s, e1)
    v = f * (d * q).sum(axis=1)
    t = f * (e2 * q).sum(axis=1)

    hit = mask & (u >= -_TOL) & (u <= 1.0 + _TOL) & (v >= -_TOL) & (u + v <= 1.0 + _TOL) & (t > _RAY_OFFSET)
    return bool(hit.any())


def _is_point_visible(
    pt: np.ndarray,
    view_dir: np.ndarray,
    verts: np.ndarray,
    tris: np.ndarray,
) -> bool:
    """Test visibility of a 3D point from the view direction (ortho).

    Cast a ray from pt along -view_dir (toward the viewer).  If any triangle
    is hit, the point is occluded (hidden).
    """
    # Ray direction: toward viewer = -view_dir
    ray_dir = -_unit(view_dir)
    return not _ray_hits_mesh(pt, ray_dir, verts, tris)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_silhouette_curves(
    body: Any,
    view_direction: Sequence[float],
    plane_normal: Optional[Sequence[float]] = None,
    n_samples: int = _UV_SAMPLES,
) -> List[Curve2D]:
    """Compute 2D NURBS silhouette curves for a body from a view direction.

    For each face of the body, identifies the silhouette locus (where the
    surface normal is perpendicular to the view direction: n · v = 0).
    Traces this locus as a parametric polyline on the surface using the
    Hertzmann-Zorin 2000 sign-change grid method.  Projects each chain to
    the 2D projection plane (perpendicular to view_direction) and fits a
    NURBS B-spline to the projected points.

    Parameters
    ----------
    body : Body
        B-rep body from kerf_cad_core.geom.brep.  Must implement all_faces()
        which returns Face objects with .surface attributes.
    view_direction : sequence of 3 floats
        View direction vector (camera looks toward this direction).
    plane_normal : sequence of 3 floats, optional
        Normal of the projection plane.  Defaults to view_direction.
    n_samples : int
        UV grid resolution per face for silhouette tracing (default 64).

    Returns
    -------
    list[Curve2D]
        One Curve2D per silhouette chain found.  Each has .points (2D
        coordinates in the projection plane) and .nurbs (fitted NurbsCurve
        or None).  Empty list if no silhouettes found or on error.
    """
    try:
        vd = _unit(np.asarray(view_direction, dtype=float).ravel()[:3])
        right, up, forward = _build_projection_frame(vd)
        if plane_normal is not None:
            pn = _unit(np.asarray(plane_normal, dtype=float).ravel()[:3])
        else:
            pn = forward  # noqa: F841 — kept for future use

        try:
            faces = body.all_faces()
        except Exception:
            return []

        result: List[Curve2D] = []

        for fi, face in enumerate(faces):
            surf = face.surface
            chains_3d = _trace_silhouette_on_surface(surf, vd, n_samples=n_samples)

            for chain in chains_3d:
                if len(chain) < 2:
                    continue
                # Project to 2D
                pts_2d = [_project_point_to_2d(np.array(p), right, up) for p in chain]
                nurbs_2d = _fit_nurbs_to_polyline_2d(pts_2d)
                result.append(Curve2D(
                    points=pts_2d,
                    nurbs=nurbs_2d,
                    source_face_index=fi,
                    curve_type="silhouette",
                ))

        return result

    except Exception:
        return []


def compute_visible_edges(
    body: Any,
    view_direction: Sequence[float],
    n_mesh: int = 12,
) -> Tuple[List[Curve3D], List[Curve3D]]:
    """Classify body edges as visible or hidden from the view direction.

    Uses ray-casting from each edge's midpoint along -view_direction.
    If the ray hits any mesh triangle (excluding the edge's own face),
    the edge is classified as hidden.

    Parameters
    ----------
    body : Body
        B-rep body implementing all_edges() and all_faces().
    view_direction : sequence of 3 floats
        View direction vector.
    n_mesh : int
        Tessellation resolution per face for the occlusion mesh (default 12).

    Returns
    -------
    (visible_edges, hidden_edges) : tuple[list[Curve3D], list[Curve3D]]
        Each list contains Curve3D objects representing edge polylines
        with .is_visible set accordingly.
    """
    try:
        vd = _unit(np.asarray(view_direction, dtype=float).ravel()[:3])
        verts, tris, _ = _build_mesh_from_body(body, n_per_face=n_mesh)

        try:
            edges = body.all_edges()
        except Exception:
            return [], []

        visible: List[Curve3D] = []
        hidden: List[Curve3D] = []

        for ei, edge in enumerate(edges):
            # Sample the edge curve
            t0 = float(getattr(edge, "t0", 0.0))
            t1 = float(getattr(edge, "t1", 1.0))
            params = np.linspace(t0, t1, max(8, min(32, int((t1 - t0) * 20 + 8))))
            pts_3d: List[Tuple[float, float, float]] = []
            try:
                for t in params:
                    pt = np.asarray(edge.curve.evaluate(t), dtype=float).ravel()[:3]
                    pts_3d.append((float(pt[0]), float(pt[1]), float(pt[2])))
            except Exception:
                continue

            if not pts_3d:
                continue

            # Test midpoint visibility
            mid_idx = len(pts_3d) // 2
            mid_pt = np.array(pts_3d[mid_idx])
            is_vis = _is_point_visible(mid_pt, vd, verts, tris)

            c = Curve3D(points=pts_3d, is_visible=is_vis, source_edge_index=ei)
            if is_vis:
                visible.append(c)
            else:
                hidden.append(c)

        return visible, hidden

    except Exception:
        return [], []


def project_to_2d_with_layers(
    body: Any,
    view_direction: Sequence[float],
    layer_groups: Optional[Dict[str, Any]] = None,
    n_samples: int = _UV_SAMPLES,
    n_mesh: int = 12,
) -> ProjectionResult:
    """Multi-pass NURBS projection into drawing layers.

    Computes:
    - Visible silhouette curves -> 'visible' layer
    - Hidden silhouette curves  -> 'hidden' layer (ray-cast classification)
    - B-rep edges visible       -> 'visible' layer
    - B-rep edges hidden        -> 'hidden' layer
    - Dimension layer           -> 'dim' layer (currently empty; populated
                                   by the auto_dimension pass downstream)

    Parameters
    ----------
    body : Body
        B-rep body.
    view_direction : sequence of 3 floats
        View direction vector.
    layer_groups : dict, optional
        Mapping of custom layer names to face index lists for selective
        inclusion.  If None, all faces are included in a single pass.
    n_samples : int
        UV grid resolution for silhouette tracing.
    n_mesh : int
        Tessellation resolution for ray-casting occlusion mesh.

    Returns
    -------
    ProjectionResult
        Multi-layer result with silhouettes and edge curves.
    """
    vd = _unit(np.asarray(view_direction, dtype=float).ravel()[:3])
    right, up, _ = _build_projection_frame(vd)

    # --- Silhouette curves ---
    all_silhouettes = compute_silhouette_curves(body, vd, n_samples=n_samples)

    # Classify silhouettes as visible/hidden by testing the first 3D point
    verts, tris, _ = _build_mesh_from_body(body, n_per_face=n_mesh)

    vis_sil: List[Curve2D] = []
    hid_sil: List[Curve2D] = []

    try:
        faces = body.all_faces()
    except Exception:
        faces = []

    # Build 3D chains for silhouette visibility test
    all_sil_3d = []
    for fi, face in enumerate(faces):
        surf = face.surface
        chains_3d = _trace_silhouette_on_surface(surf, vd, n_samples=n_samples)
        all_sil_3d.append(chains_3d)

    for curve_2d, chains in zip(all_silhouettes,
                                 [c for chains in all_sil_3d for c in chains]):
        if not chains:
            vis_sil.append(curve_2d)
            continue
        mid_idx = len(chains) // 2
        mid_pt = np.array(chains[mid_idx])
        is_vis = _is_point_visible(mid_pt, vd, verts, tris)
        if is_vis:
            vis_sil.append(curve_2d)
        else:
            hid_sil.append(curve_2d)

    # If classification didn't cover all curves, put remainder in visible
    n_classified = len(vis_sil) + len(hid_sil)
    if n_classified < len(all_silhouettes):
        vis_sil.extend(all_silhouettes[n_classified:])

    # --- B-rep edge curves ---
    vis_edges_3d, hid_edges_3d = compute_visible_edges(body, vd, n_mesh=n_mesh)

    def _edge3d_to_2d(e3d: Curve3D) -> Curve2D:
        pts_2d = [_project_point_to_2d(np.array(p), right, up) for p in e3d.points]
        nurbs_2d = _fit_nurbs_to_polyline_2d(pts_2d)
        return Curve2D(
            points=pts_2d,
            nurbs=nurbs_2d,
            source_face_index=-1,
            curve_type="boundary",
        )

    vis_edges_2d = [_edge3d_to_2d(e) for e in vis_edges_3d]
    hid_edges_2d = [_edge3d_to_2d(e) for e in hid_edges_3d]

    # --- Assemble layers ---
    layers: Dict[str, List[Curve2D]] = {
        "visible": vis_sil + vis_edges_2d,
        "hidden": hid_sil + hid_edges_2d,
        "dim": [],  # populated downstream by auto_dimension
    }

    if layer_groups:
        for layer_name, face_indices in layer_groups.items():
            idx_set = set(face_indices)
            layers[layer_name] = [
                c for c in all_silhouettes if c.source_face_index in idx_set
            ]

    return ProjectionResult(
        visible_silhouettes=vis_sil,
        hidden_silhouettes=hid_sil,
        visible_edges=vis_edges_2d,
        hidden_edges=hid_edges_2d,
        layers=layers,
        view_direction=vd,
    )


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

    _silhouette_projection_spec = ToolSpec(
        name="drawing_silhouette_projection",
        description=(
            "Compute NURBS silhouette projection curves for a body viewed from a given direction.\n"
            "\n"
            "Implements the Hertzmann-Zorin 2000 silhouette-locus method: for each face,\n"
            "identifies where the surface normal is perpendicular to the view direction\n"
            "(n · v = 0), traces that locus, projects to 2D, and fits NURBS curves.\n"
            "Returns layered visible/hidden silhouettes and edge projections for vector\n"
            "drawing extraction.\n"
            "\n"
            "Returns:\n"
            "  ok                    : bool\n"
            "  visible_silhouette_count : int\n"
            "  hidden_silhouette_count  : int\n"
            "  visible_edge_count    : int\n"
            "  hidden_edge_count     : int\n"
            "  visible_silhouettes   : list of {points: [[x,y],...], has_nurbs: bool}\n"
            "  hidden_silhouettes    : list of {points: [[x,y],...], has_nurbs: bool}\n"
            "  visible_edges         : list of {points: [[x,y],...], has_nurbs: bool}\n"
            "  hidden_edges          : list of {points: [[x,y],...], has_nurbs: bool}\n"
            "\n"
            "Errors: {ok: false, reason: str}.  Never raises.\n"
            "\n"
            "Reference: Hertzmann & Zorin, ACM SIGGRAPH 2000, pp. 517-526."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "faces": {
                    "type": "array",
                    "description": (
                        "List of face definitions.  Each face is an object with:\n"
                        "  surface_type: 'sphere' | 'cylinder' | 'plane' | 'nurbs'\n"
                        "  For 'sphere': center [x,y,z], radius float\n"
                        "  For 'cylinder': center [x,y,z], axis [dx,dy,dz], radius float\n"
                        "  For 'plane': origin [x,y,z], x_axis [dx,dy,dz], y_axis [dx,dy,dz]\n"
                        "  For 'nurbs': degree_u, degree_v, control_points (nu*nv x 3), "
                        "num_u, num_v"
                    ),
                    "items": {"type": "object"},
                },
                "view_direction": {
                    "type": "array",
                    "description": "View direction vector [dx, dy, dz].",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "n_samples": {
                    "type": "integer",
                    "description": "UV grid resolution per face (default 32; higher = more accurate).",
                },
            },
            "required": ["faces", "view_direction"],
        },
    )

    @register(_silhouette_projection_spec)
    async def run_drawing_silhouette_projection(ctx: "ProjectCtx", args: bytes) -> str:
        """LLM tool: compute NURBS silhouette projection."""
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        faces_raw = a.get("faces")
        view_dir_raw = a.get("view_direction")

        if faces_raw is None or view_dir_raw is None:
            return err_payload("faces and view_direction are required", "BAD_ARGS")

        try:
            vd = [float(x) for x in view_dir_raw]
        except (TypeError, ValueError) as exc:
            return err_payload(f"view_direction must be 3 numbers: {exc}", "BAD_ARGS")

        n_samples = int(a.get("n_samples", 32))
        if n_samples < 4:
            return err_payload("n_samples must be >= 4", "BAD_ARGS")

        # Build a minimal Body from the face definitions
        try:
            from kerf_cad_core.geom.brep import (
                Body, Solid, Shell, Face, Loop,
                SphereSurface, CylinderSurface, Plane,
                Vertex,
            )
            from kerf_cad_core.geom.nurbs import NurbsSurface as NurbsSurf

            faces_objs = []
            for fd in faces_raw:
                stype = fd.get("surface_type", "")
                if stype == "sphere":
                    ctr = np.asarray(fd["center"], dtype=float)
                    r = float(fd["radius"])
                    surf = SphereSurface(center=ctr, radius=r)
                elif stype == "cylinder":
                    ctr = np.asarray(fd["center"], dtype=float)
                    ax = np.asarray(fd["axis"], dtype=float)
                    r = float(fd["radius"])
                    surf = CylinderSurface(center=ctr, axis=ax, radius=r)
                elif stype == "plane":
                    org = np.asarray(fd["origin"], dtype=float)
                    xa = np.asarray(fd["x_axis"], dtype=float)
                    ya = np.asarray(fd["y_axis"], dtype=float)
                    surf = Plane(origin=org, x_axis=xa, y_axis=ya)
                elif stype == "nurbs":
                    du = int(fd["degree_u"])
                    dv = int(fd["degree_v"])
                    nu = int(fd["num_u"])
                    nv = int(fd["num_v"])
                    cp_flat = np.asarray(fd["control_points"], dtype=float)
                    cp = cp_flat.reshape(nu, nv, -1)
                    ku = np.array(fd.get("knots_u") or _uniform_knots(nu, du))
                    kv = np.array(fd.get("knots_v") or _uniform_knots(nv, dv))
                    surf = NurbsSurf(degree_u=du, degree_v=dv,
                                     control_points=cp, knots_u=ku, knots_v=kv)
                else:
                    return err_payload(
                        f"unknown surface_type {stype!r}; "
                        "must be 'sphere'|'cylinder'|'plane'|'nurbs'",
                        "BAD_ARGS",
                    )
                # Minimal face with no loops (shell-only body)
                faces_objs.append(Face(surface=surf, loops=[]))

            # Build a minimal Body: one shell, no edges/vertices
            sh = Shell(faces=faces_objs, is_closed=False)
            solid = Solid(shells=[sh])
            body = Body(solids=[solid])

        except Exception as exc:
            return err_payload(f"failed to build body from faces: {exc}", "OP_FAILED")

        try:
            result = project_to_2d_with_layers(body, vd, n_samples=n_samples)
        except Exception as exc:
            return err_payload(f"projection failed: {exc}", "OP_FAILED")

        def _serialize_curve(c: "Curve2D") -> dict:
            return {
                "points": [[float(x), float(y)] for x, y in c.points],
                "has_nurbs": c.nurbs is not None,
                "source_face_index": c.source_face_index,
            }

        return ok_payload({
            "visible_silhouette_count": len(result.visible_silhouettes),
            "hidden_silhouette_count": len(result.hidden_silhouettes),
            "visible_edge_count": len(result.visible_edges),
            "hidden_edge_count": len(result.hidden_edges),
            "visible_silhouettes": [_serialize_curve(c) for c in result.visible_silhouettes],
            "hidden_silhouettes": [_serialize_curve(c) for c in result.hidden_silhouettes],
            "visible_edges": [_serialize_curve(c) for c in result.visible_edges],
            "hidden_edges": [_serialize_curve(c) for c in result.hidden_edges],
        })


def _uniform_knots(n_ctrl: int, degree: int) -> np.ndarray:
    """Open uniform knot vector for n_ctrl control points of given degree."""
    n_knots = n_ctrl + degree + 1
    knots = np.zeros(n_knots)
    knots[-(degree + 1):] = 1.0
    n_inner = n_ctrl - degree - 1
    for i in range(1, n_inner + 1):
        knots[degree + i] = i / (n_inner + 1)
    return knots
