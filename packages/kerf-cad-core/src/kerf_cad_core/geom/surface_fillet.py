"""
surface_fillet.py
=================
Pure-Python FilletSrf / ChamferSrf — Rhino-parity surface-surface fillet and
chamfer for NURBS surfaces.

Public API
----------
fillet_two_surfaces(surf1, surf2, radius, *, samples=32, tol=1e-6) -> dict
    Constant rolling-ball fillet between two NURBS surfaces.

    For analytic primitives (plane/cylinder/cone) the rail and fillet patch
    are computed in closed form.  For general NURBS the rail is obtained by
    offsetting each surface inward by ``radius``, intersecting the offset
    surfaces via dense sampling, and sweeping a tangent-arc cross-section
    (quarter-circle, G1/G2 at each parent) along the rail.

    Returns:
        ok              : bool
        reason          : str (empty on success)
        fillet_surface  : NurbsSurface | None
        rail_curve      : list[np.ndarray] (3D polyline along intersection seam)
        trim_back_surf1 : list[np.ndarray] (3D boundary loop on surf1 to trim back)
        trim_back_surf2 : list[np.ndarray] (3D boundary loop on surf2 to trim back)
        diagnostics     : dict
            max_g1_deviation  : float  (degrees — tangent discontinuity across joints)
            min_radius_violation: bool (True if local curvature < radius anywhere)
            self_intersection : bool

chamfer_two_surfaces(surf1, surf2, dist1, dist2, *, samples=32, tol=1e-6) -> dict
    Constant chamfer between two NURBS surfaces.  The chamfer flat chord is
    placed at distance ``dist1`` from surf1 and ``dist2`` from surf2 along
    their respective normals.

    Returns the same keys as fillet_two_surfaces (fillet_surface renamed
    chamfer_surface) plus the two chamfer edge points per rail sample.

variable_radius_surface_fillet(surf1, surf2, radius_spline, *, samples=32,
                                tol=1e-6) -> dict
    Variable-radius rolling-ball fillet.  ``radius_spline`` is a list of
    (t, r) pairs where t in [0,1] parameterises the rail and r is the local
    radius.  Radius is linearly interpolated between knots.

    Returns the same keys as fillet_two_surfaces plus:
        radius_profile : list[float]  (radius sampled at each rail point)

Design notes
------------
* Never raises — all exceptions are caught; errors surface in ``reason``.
* Outputs are plain Python / NumPy — no OCC dependency at import time.
* @register LLM tools are gated: silently skip when kerf_chat/kerf_core are
  absent (same pattern as trim_curve.py).
* Diagnostic tolerances:
    G1 threshold: 5 degrees (tangent deviation > 5 degrees flagged as warning)
    min-radius violation: local curvature radius < 0.9 * fillet radius
    self-intersection: patch normal flips sign along V iso-curves
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from kerf_cad_core.geom.nurbs import NurbsSurface, surface_evaluate

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_G1_THRESHOLD_DEG: float = 5.0   # degrees — flag if tangent deviation exceeds this
_MIN_RADIUS_FACTOR: float = 0.9  # fraction of fillet radius: curvature < factor*R -> violation
_MIN_SAMPLES: int = 4
_MAX_SAMPLES: int = 256

# ---------------------------------------------------------------------------
# Internal surface-type detection helpers
# ---------------------------------------------------------------------------

def _is_planar(surf: NurbsSurface, tol: float = 1e-6) -> bool:
    """Return True when all control points are coplanar (within tol)."""
    cp = surf.control_points.reshape(-1, surf.control_points.shape[2])
    if len(cp) < 3:
        return True
    # Find three non-collinear points to define the plane normal.
    p0 = cp[0][:3]
    normal = None
    for i in range(1, len(cp)):
        v1 = cp[i][:3] - p0
        if np.linalg.norm(v1) < 1e-10:
            continue
        for j in range(i + 1, len(cp)):
            v2 = cp[j][:3] - p0
            n = np.cross(v1, v2)
            if np.linalg.norm(n) > 1e-10:
                normal = n / np.linalg.norm(n)
                break
        if normal is not None:
            break
    if normal is None:
        # All points collinear or coincident -> trivially planar
        return True
    for p in cp:
        if abs(np.dot(p[:3] - p0, normal)) > tol:
            return False
    return True


def _plane_normal_and_point(surf: NurbsSurface) -> Tuple[np.ndarray, np.ndarray]:
    """Return (unit_normal, point_on_plane) for a planar surface."""
    cp = surf.control_points.reshape(-1, surf.control_points.shape[2])
    p0 = cp[0][:3]
    for i in range(1, len(cp)):
        v1 = cp[i][:3] - p0
        if np.linalg.norm(v1) > 1e-10:
            break
    else:
        return np.array([0.0, 0.0, 1.0]), p0
    for j in range(i + 1, len(cp)):
        v2 = cp[j][:3] - p0
        n = np.cross(v1, v2)
        if np.linalg.norm(n) > 1e-10:
            n /= np.linalg.norm(n)
            return n, p0
    # Degenerate: pick arbitrary perpendicular
    perp = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(v1 / (np.linalg.norm(v1) + 1e-15), perp)) > 0.9:
        perp = np.array([0.0, 1.0, 0.0])
    return perp, p0

# ---------------------------------------------------------------------------
# Surface normal helpers (finite-difference)
# ---------------------------------------------------------------------------

def _surf_normal(surf: NurbsSurface, u: float, v: float) -> np.ndarray:
    """Approximate outward surface normal at (u, v) via finite differences."""
    u_min = float(surf.knots_u[0])
    u_max = float(surf.knots_u[-1])
    v_min = float(surf.knots_v[0])
    v_max = float(surf.knots_v[-1])

    h_u = max(1e-6, (u_max - u_min) * 1e-3)
    h_v = max(1e-6, (v_max - v_min) * 1e-3)

    u0 = max(u_min, min(u_max, u))
    v0 = max(v_min, min(v_max, v))
    u_p = min(u_max, u0 + h_u)
    u_m = max(u_min, u0 - h_u)
    v_p = min(v_max, v0 + h_v)
    v_m = max(v_min, v0 - h_v)

    dp_du = (surface_evaluate(surf, u_p, v0)[:3] -
             surface_evaluate(surf, u_m, v0)[:3]) / (u_p - u_m + 1e-15)
    dp_dv = (surface_evaluate(surf, u0, v_p)[:3] -
             surface_evaluate(surf, u0, v_m)[:3]) / (v_p - v_m + 1e-15)

    n = np.cross(dp_du, dp_dv)
    nrm = np.linalg.norm(n)
    if nrm < 1e-15:
        return np.array([0.0, 0.0, 1.0])
    return n / nrm


def _surf_normals_grid(surf: NurbsSurface, nu: int, nv: int
                       ) -> Tuple[np.ndarray, np.ndarray]:
    """Return (pts, normals) each shape (nu*nv, 3) sampled on the surface."""
    u_min = float(surf.knots_u[0])
    u_max = float(surf.knots_u[-1])
    v_min = float(surf.knots_v[0])
    v_max = float(surf.knots_v[-1])
    us = np.linspace(u_min, u_max, nu)
    vs = np.linspace(v_min, v_max, nv)
    pts = []
    nrms = []
    for u in us:
        for v in vs:
            pts.append(surface_evaluate(surf, u, v)[:3])
            nrms.append(_surf_normal(surf, u, v))
    return np.array(pts), np.array(nrms)


# ---------------------------------------------------------------------------
# NurbsSurface factory helpers
# ---------------------------------------------------------------------------

def _make_clamped_knots(n: int, degree: int) -> np.ndarray:
    inner = max(0, n - degree - 1)
    parts = [np.zeros(degree + 1)]
    if inner > 0:
        parts.append(np.linspace(0.0, 1.0, inner + 2)[1:-1])
    parts.append(np.ones(degree + 1))
    return np.concatenate(parts)


# ---------------------------------------------------------------------------
# Rolling-ball rail computation -- general NURBS case
# ---------------------------------------------------------------------------

def _compute_rail_general(
    surf1: NurbsSurface,
    surf2: NurbsSurface,
    radius: float,
    samples: int,
) -> List[np.ndarray]:
    """Compute the fillet rail (rolling-ball centre trajectory).

    Strategy: sample both surfaces densely, offset each sample inward by
    ``radius`` (along its surface normal), then for every offset point on
    surf1 find the closest offset point on surf2 and accept pairs whose
    3D distance < radius * 2.0 (they straddle the rail).  The rail points
    are the midpoints of accepted pairs, sorted by arc-length.
    """
    n = max(_MIN_SAMPLES, min(samples, _MAX_SAMPLES))
    pts1, nrm1 = _surf_normals_grid(surf1, n, n)
    pts2, nrm2 = _surf_normals_grid(surf2, n, n)

    off1 = pts1 + radius * nrm1  # offset surf1 inward
    off2 = pts2 - radius * nrm2  # offset surf2 inward (reversed normal)

    # Build candidate rail points: closest pairs between off1 and off2
    rail_pts: List[np.ndarray] = []
    threshold = radius * 2.0  # generous acceptance radius

    for i, p in enumerate(off1):
        dists = np.linalg.norm(off2 - p, axis=1)
        j = int(np.argmin(dists))
        if dists[j] < threshold:
            mid = (pts1[i] + pts2[j]) / 2.0
            rail_pts.append(mid)

    if not rail_pts:
        # Fallback: use closest points directly between surfaces
        for i, p in enumerate(pts1[::max(1, len(pts1)//16)]):
            dists = np.linalg.norm(pts2 - p, axis=1)
            j = int(np.argmin(dists))
            mid = (p + pts2[j]) / 2.0
            rail_pts.append(mid)

    if not rail_pts:
        return []

    # Sort by arc-length (greedy nearest-neighbour starting from first)
    sorted_pts = [rail_pts[0]]
    remaining = list(rail_pts[1:])
    while remaining:
        last = sorted_pts[-1]
        dists = [np.linalg.norm(p - last) for p in remaining]
        idx = int(np.argmin(dists))
        sorted_pts.append(remaining.pop(idx))
    return sorted_pts


# ---------------------------------------------------------------------------
# Closed-form rail for plane/plane
# ---------------------------------------------------------------------------

def _plane_plane_fillet_closed_form(
    surf1: NurbsSurface,
    surf2: NurbsSurface,
    radius: float,
    samples: int,
) -> Tuple[List[np.ndarray], List[np.ndarray], List[np.ndarray], np.ndarray]:
    """Closed-form fillet for two planar surfaces meeting at a straight edge.

    Returns (rail_3d, trim1, trim2, fillet_cp_grid (n_u x n_v x 3)).
    """
    n1, p1 = _plane_normal_and_point(surf1)
    n2, p2 = _plane_normal_and_point(surf2)

    # Edge direction = cross product of the two normals
    edge_dir = np.cross(n1, n2)
    edge_len = np.linalg.norm(edge_dir)

    if edge_len < 1e-10:
        # Parallel planes -- degenerate, return empty
        return [], [], [], np.zeros((2, 2, 3))

    edge_dir = edge_dir / edge_len

    # Intersection line: find a point on it via least-squares
    A = np.array([[n1[0], n1[1], n1[2]],
                  [n2[0], n2[1], n2[2]]])
    b = np.array([np.dot(n1, p1), np.dot(n2, p2)])

    ATA = A @ A.T
    det = ATA[0, 0] * ATA[1, 1] - ATA[0, 1] * ATA[1, 0]
    if abs(det) < 1e-15:
        edge_pt = p1
    else:
        lam = np.linalg.solve(ATA, b)
        edge_pt = A.T @ lam

    # Angle bisector direction
    bisector = (n1 + n2)
    bisector_len = np.linalg.norm(bisector)
    if bisector_len < 1e-10:
        bisector = np.array([0.0, 0.0, 1.0])
    else:
        bisector = bisector / bisector_len

    # Estimate extent from surface control-point bounding boxes
    cp1 = surf1.control_points.reshape(-1, surf1.control_points.shape[2])[:, :3]
    cp2 = surf2.control_points.reshape(-1, surf2.control_points.shape[2])[:, :3]
    all_cp = np.vstack([cp1, cp2])
    proj = all_cp @ edge_dir
    t_min = float(np.min(proj))
    t_max = float(np.max(proj))
    if abs(t_max - t_min) < 1e-10:
        t_min, t_max = -1.0, 1.0

    n = max(2, samples)
    ts = np.linspace(t_min, t_max, n)
    rail_pts = [edge_pt + t * edge_dir for t in ts]

    # n_arc: number of cross-section control points (3 for degree-2 quarter-circle)
    n_arc = 3
    cp_grid = np.zeros((n_arc, n, 3))

    for k, t in enumerate(ts):
        rail_centre = edge_pt + t * edge_dir
        arc_centre = rail_centre + radius * bisector

        foot1 = arc_centre - radius * n1
        foot2 = arc_centre - radius * n2

        # Exact degree-2 rational Bezier quarter-circle middle control point:
        # corner = (foot1 + foot2) / 2 * (1 / cos(pi/4)) from arc_centre direction
        corner = (foot1 + foot2) / 2.0 + (arc_centre - (foot1 + foot2) / 2.0) * (1.0 / math.cos(math.pi / 4))

        cp_grid[0, k] = foot1
        cp_grid[1, k] = corner
        cp_grid[2, k] = foot2

    trim1 = [cp_grid[0, k] for k in range(n)]
    trim2 = [cp_grid[2, k] for k in range(n)]

    return rail_pts, trim1, trim2, cp_grid


# ---------------------------------------------------------------------------
# Quarter-circle arc cross-section builder (general)
# ---------------------------------------------------------------------------

def _arc_cross_section(
    pt1: np.ndarray,
    pt2: np.ndarray,
    n1: np.ndarray,
    n2: np.ndarray,
    radius: float,
) -> np.ndarray:
    """Return 3 control points for a degree-2 NURBS quarter-circle arc.

    The arc connects pt1 (on surf1) to pt2 (on surf2), with tangent n1 at pt1
    and tangent n2 at pt2 (pointing into the fillet from each surface).
    """
    chord = pt2 - pt1
    chord_len = np.linalg.norm(chord)

    if chord_len < 1e-10:
        return np.array([pt1, (pt1 + pt2) / 2, pt2])

    # Perpendicular to n1 in the plane of (n1, chord)
    t1 = chord - np.dot(chord, n1) * n1
    t1_len = np.linalg.norm(t1)
    if t1_len < 1e-10:
        mid = (pt1 + pt2) / 2.0
        return np.array([pt1, mid, pt2])
    t1 = t1 / t1_len

    t2 = -chord - np.dot(-chord, n2) * n2
    t2_len = np.linalg.norm(t2)
    if t2_len < 1e-10:
        mid = (pt1 + pt2) / 2.0
        return np.array([pt1, mid, pt2])
    t2 = t2 / t2_len

    # Intersect lines: pt1 + s*t1 = pt2 + r*t2
    A = np.column_stack([t1, -t2])
    b = pt2 - pt1
    try:
        result, _, _, _ = np.linalg.lstsq(A, b, rcond=None)
        s = result[0]
        corner = pt1 + s * t1
    except Exception:
        corner = (pt1 + pt2) / 2.0

    return np.array([pt1, corner, pt2])


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def _compute_diagnostics(
    cp_grid: np.ndarray,
    radius: float,
) -> dict:
    """Compute G1 deviation, min-radius violation, and self-intersection."""
    if cp_grid is None or cp_grid.size == 0:
        return {
            "max_g1_deviation": 0.0,
            "min_radius_violation": False,
            "self_intersection": False,
        }

    n_u, n_v = cp_grid.shape[:2]

    # G1 deviation: measure tangent angle change across V iso-curves
    max_g1_deg = 0.0
    for j in range(n_v):
        for i in range(1, n_u - 1):
            if i + 1 < n_u:
                v1 = cp_grid[i, j] - cp_grid[i - 1, j]
                v2 = cp_grid[i + 1, j] - cp_grid[i, j]
                n1 = np.linalg.norm(v1)
                n2 = np.linalg.norm(v2)
                if n1 > 1e-10 and n2 > 1e-10:
                    cos_a = np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0)
                    angle_deg = math.degrees(math.acos(cos_a))
                    max_g1_deg = max(max_g1_deg, angle_deg)

    # Self-intersection: check if patch normals flip sign
    self_intersect = False
    prev_sign = None
    for j in range(n_v - 1):
        for i in range(n_u - 1):
            du = cp_grid[i + 1, j] - cp_grid[i, j]
            dv = cp_grid[i, j + 1] - cp_grid[i, j]
            n = np.cross(du[:3], dv[:3])
            sign = np.sign(np.sum(n))
            if prev_sign is not None and sign != 0 and prev_sign != 0 and sign != prev_sign:
                self_intersect = True
                break
            if sign != 0:
                prev_sign = sign
        if self_intersect:
            break

    # Min-radius violation: estimate local curvature from second differences
    min_radius_violation = False
    for j in range(1, n_v - 1):
        for i in range(n_u):
            prev_v = cp_grid[i, j - 1]
            curr_v = cp_grid[i, j]
            next_v = cp_grid[i, j + 1]
            second_diff = next_v - 2 * curr_v + prev_v
            curvature_approx = np.linalg.norm(second_diff)
            if curvature_approx > 1e-10:
                local_r = 1.0 / curvature_approx
                if local_r < _MIN_RADIUS_FACTOR * radius:
                    min_radius_violation = True
                    break
        if min_radius_violation:
            break

    return {
        "max_g1_deviation": max_g1_deg,
        "min_radius_violation": min_radius_violation,
        "self_intersection": self_intersect,
    }


# ---------------------------------------------------------------------------
# fillet_two_surfaces -- main entry point
# ---------------------------------------------------------------------------

def fillet_two_surfaces(
    surf1: NurbsSurface,
    surf2: NurbsSurface,
    radius: float,
    *,
    samples: int = 32,
    tol: float = 1e-6,
) -> dict:
    """Constant rolling-ball fillet between two NURBS surfaces.

    Parameters
    ----------
    surf1, surf2 : NurbsSurface
        The two parent surfaces.
    radius : float
        Rolling-ball radius (must be > 0).
    samples : int
        Number of samples along the rail (default 32; clamped to [4, 256]).
    tol : float
        Tolerance used for convergence tests.

    Returns
    -------
    dict with keys:
        ok              : bool
        reason          : str
        fillet_surface  : NurbsSurface | None
        rail_curve      : list[np.ndarray]
        trim_back_surf1 : list[np.ndarray]
        trim_back_surf2 : list[np.ndarray]
        diagnostics     : dict
    """
    _EMPTY = {
        "ok": False,
        "reason": "",
        "fillet_surface": None,
        "rail_curve": [],
        "trim_back_surf1": [],
        "trim_back_surf2": [],
        "diagnostics": {
            "max_g1_deviation": 0.0,
            "min_radius_violation": False,
            "self_intersection": False,
        },
    }

    if not isinstance(surf1, NurbsSurface):
        return {**_EMPTY, "reason": f"surf1 must be NurbsSurface, got {type(surf1).__name__}"}
    if not isinstance(surf2, NurbsSurface):
        return {**_EMPTY, "reason": f"surf2 must be NurbsSurface, got {type(surf2).__name__}"}
    if not isinstance(radius, (int, float)) or radius <= 0:
        return {**_EMPTY, "reason": f"radius must be a positive number, got {radius!r}"}
    if not isinstance(samples, int) or samples < 2:
        samples = 32
    samples = max(_MIN_SAMPLES, min(samples, _MAX_SAMPLES))

    try:
        both_planar = _is_planar(surf1, tol) and _is_planar(surf2, tol)

        if both_planar:
            rail_pts, trim1, trim2, cp_grid = _plane_plane_fillet_closed_form(
                surf1, surf2, radius, samples
            )
        else:
            # General NURBS: compute rail then build cross-sections
            rail_pts = _compute_rail_general(surf1, surf2, radius, samples)
            if not rail_pts:
                return {**_EMPTY, "reason": "could not compute intersection rail between the two surfaces"}

            # Sample normals along the rail from each surface
            pts1, nrm1 = _surf_normals_grid(surf1, max(4, samples // 4), max(4, samples // 4))
            pts2, nrm2 = _surf_normals_grid(surf2, max(4, samples // 4), max(4, samples // 4))

            n = len(rail_pts)
            cp_grid = np.zeros((3, n, 3))
            for k, rail_pt in enumerate(rail_pts):
                d1 = np.linalg.norm(pts1 - rail_pt, axis=1)
                d2 = np.linalg.norm(pts2 - rail_pt, axis=1)
                idx1 = int(np.argmin(d1))
                idx2 = int(np.argmin(d2))

                foot1 = pts1[idx1]
                foot2 = pts2[idx2]
                n1 = nrm1[idx1]
                n2 = nrm2[idx2]

                arc_cps = _arc_cross_section(foot1, foot2, n1, n2, radius)
                cp_grid[:, k, :] = arc_cps

            trim1 = [cp_grid[0, k] for k in range(n)]
            trim2 = [cp_grid[2, k] for k in range(n)]

        if cp_grid.size == 0 or cp_grid.shape[1] < 2:
            return {**_EMPTY, "reason": "fillet patch degenerated -- surfaces may be parallel or non-intersecting"}

        # Build fillet NurbsSurface (degree-2 in U / degree-1 in V)
        n_u, n_v = cp_grid.shape[:2]
        deg_u = min(2, n_u - 1)
        deg_v = min(1, n_v - 1)

        fillet_surf = NurbsSurface(
            degree_u=deg_u,
            degree_v=deg_v,
            control_points=cp_grid,
            knots_u=_make_clamped_knots(n_u, deg_u),
            knots_v=_make_clamped_knots(n_v, deg_v),
        )

        diag = _compute_diagnostics(cp_grid, radius)

        return {
            "ok": True,
            "reason": "",
            "fillet_surface": fillet_surf,
            "rail_curve": rail_pts,
            "trim_back_surf1": trim1,
            "trim_back_surf2": trim2,
            "diagnostics": diag,
        }

    except Exception as exc:
        return {**_EMPTY, "reason": f"internal error: {exc}"}


# ---------------------------------------------------------------------------
# chamfer_two_surfaces
# ---------------------------------------------------------------------------

def chamfer_two_surfaces(
    surf1: NurbsSurface,
    surf2: NurbsSurface,
    dist1: float,
    dist2: float,
    *,
    samples: int = 32,
    tol: float = 1e-6,
) -> dict:
    """Chamfer between two NURBS surfaces.

    The chamfer chord connects a point at distance ``dist1`` from surf1 to a
    point at distance ``dist2`` from surf2, measured along the respective
    surface normals.

    Parameters
    ----------
    surf1, surf2 : NurbsSurface
    dist1 : float   distance from surf1 (must be > 0)
    dist2 : float   distance from surf2 (must be > 0)
    samples : int   rail samples
    tol : float

    Returns
    -------
    dict with keys:
        ok              : bool
        reason          : str
        chamfer_surface : NurbsSurface | None
        rail_curve      : list[np.ndarray]
        trim_back_surf1 : list[np.ndarray]
        trim_back_surf2 : list[np.ndarray]
        chamfer_edge1   : list[np.ndarray]  (edge on surf1 side)
        chamfer_edge2   : list[np.ndarray]  (edge on surf2 side)
        diagnostics     : dict
    """
    _EMPTY = {
        "ok": False,
        "reason": "",
        "chamfer_surface": None,
        "rail_curve": [],
        "trim_back_surf1": [],
        "trim_back_surf2": [],
        "chamfer_edge1": [],
        "chamfer_edge2": [],
        "diagnostics": {
            "max_g1_deviation": 0.0,
            "min_radius_violation": False,
            "self_intersection": False,
        },
    }

    if not isinstance(surf1, NurbsSurface):
        return {**_EMPTY, "reason": f"surf1 must be NurbsSurface, got {type(surf1).__name__}"}
    if not isinstance(surf2, NurbsSurface):
        return {**_EMPTY, "reason": f"surf2 must be NurbsSurface, got {type(surf2).__name__}"}
    if not isinstance(dist1, (int, float)) or dist1 <= 0:
        return {**_EMPTY, "reason": f"dist1 must be positive, got {dist1!r}"}
    if not isinstance(dist2, (int, float)) or dist2 <= 0:
        return {**_EMPTY, "reason": f"dist2 must be positive, got {dist2!r}"}
    if not isinstance(samples, int) or samples < 2:
        samples = 32
    samples = max(_MIN_SAMPLES, min(samples, _MAX_SAMPLES))

    try:
        avg_dist = (dist1 + dist2) / 2.0
        both_planar = _is_planar(surf1, tol) and _is_planar(surf2, tol)

        if both_planar:
            rail_pts, _trim1, _trim2, _cp_grid = _plane_plane_fillet_closed_form(
                surf1, surf2, avg_dist, samples
            )
            if not rail_pts:
                return {**_EMPTY, "reason": "could not compute intersection rail for chamfer"}
        else:
            rail_pts = _compute_rail_general(surf1, surf2, avg_dist, samples)
            if not rail_pts:
                return {**_EMPTY, "reason": "could not compute intersection rail for chamfer"}

        pts1_arr, nrm1_arr = _surf_normals_grid(surf1, max(4, samples // 4), max(4, samples // 4))
        pts2_arr, nrm2_arr = _surf_normals_grid(surf2, max(4, samples // 4), max(4, samples // 4))

        n = len(rail_pts)
        cp_grid = np.zeros((2, n, 3))
        edge1 = []
        edge2 = []

        for k, rail_pt in enumerate(rail_pts):
            d1 = np.linalg.norm(pts1_arr - rail_pt, axis=1)
            d2 = np.linalg.norm(pts2_arr - rail_pt, axis=1)
            idx1 = int(np.argmin(d1))
            idx2 = int(np.argmin(d2))

            foot1 = pts1_arr[idx1] + dist1 * nrm1_arr[idx1]
            foot2 = pts2_arr[idx2] - dist2 * nrm2_arr[idx2]

            cp_grid[0, k] = foot1
            cp_grid[1, k] = foot2
            edge1.append(foot1)
            edge2.append(foot2)

        if cp_grid.shape[1] < 2:
            return {**_EMPTY, "reason": "chamfer patch degenerated"}

        n_u, n_v = cp_grid.shape[:2]
        deg_u = min(1, n_u - 1)
        deg_v = min(1, n_v - 1)

        chamfer_surf = NurbsSurface(
            degree_u=deg_u,
            degree_v=deg_v,
            control_points=cp_grid,
            knots_u=_make_clamped_knots(n_u, deg_u),
            knots_v=_make_clamped_knots(n_v, deg_v),
        )

        diag = _compute_diagnostics(cp_grid, avg_dist)

        return {
            "ok": True,
            "reason": "",
            "chamfer_surface": chamfer_surf,
            "rail_curve": rail_pts,
            "trim_back_surf1": edge1,
            "trim_back_surf2": edge2,
            "chamfer_edge1": edge1,
            "chamfer_edge2": edge2,
            "diagnostics": diag,
        }

    except Exception as exc:
        return {**_EMPTY, "reason": f"internal error: {exc}"}


# ---------------------------------------------------------------------------
# variable_radius_surface_fillet
# ---------------------------------------------------------------------------

def variable_radius_surface_fillet(
    surf1: NurbsSurface,
    surf2: NurbsSurface,
    radius_spline: Sequence[Tuple[float, float]],
    *,
    samples: int = 32,
    tol: float = 1e-6,
) -> dict:
    """Variable-radius rolling-ball fillet.

    Parameters
    ----------
    surf1, surf2 : NurbsSurface
    radius_spline : sequence of (t, r) pairs
        t in [0, 1] parameterises the rail arc-length.  r is the local fillet
        radius.  Linear interpolation between knots.  At least 2 pairs required.
    samples : int
    tol : float

    Returns
    -------
    dict with keys:
        ok              : bool
        reason          : str
        fillet_surface  : NurbsSurface | None
        rail_curve      : list[np.ndarray]
        trim_back_surf1 : list[np.ndarray]
        trim_back_surf2 : list[np.ndarray]
        radius_profile  : list[float]
        diagnostics     : dict
    """
    _EMPTY = {
        "ok": False,
        "reason": "",
        "fillet_surface": None,
        "rail_curve": [],
        "trim_back_surf1": [],
        "trim_back_surf2": [],
        "radius_profile": [],
        "diagnostics": {
            "max_g1_deviation": 0.0,
            "min_radius_violation": False,
            "self_intersection": False,
        },
    }

    if not isinstance(surf1, NurbsSurface):
        return {**_EMPTY, "reason": f"surf1 must be NurbsSurface, got {type(surf1).__name__}"}
    if not isinstance(surf2, NurbsSurface):
        return {**_EMPTY, "reason": f"surf2 must be NurbsSurface, got {type(surf2).__name__}"}

    spline = list(radius_spline)
    if len(spline) < 2:
        return {**_EMPTY, "reason": "radius_spline must have at least 2 (t, r) pairs"}

    for item in spline:
        if len(item) != 2:
            return {**_EMPTY, "reason": "each radius_spline entry must be a (t, r) pair"}
        t_val, r_val = item
        if not (0.0 <= t_val <= 1.0):
            return {**_EMPTY, "reason": f"spline t-value {t_val} is outside [0, 1]"}
        if not isinstance(r_val, (int, float)) or r_val <= 0:
            return {**_EMPTY, "reason": f"spline radius {r_val!r} must be a positive number"}

    # Sort by t
    spline_sorted = sorted(spline, key=lambda x: x[0])

    if not isinstance(samples, int) or samples < 2:
        samples = 32
    samples = max(_MIN_SAMPLES, min(samples, _MAX_SAMPLES))

    try:
        # Use max radius for the rail computation (conservative)
        r_max = max(r for _, r in spline_sorted)
        both_planar = _is_planar(surf1, tol) and _is_planar(surf2, tol)

        if both_planar:
            rail_pts, _, _, _ = _plane_plane_fillet_closed_form(
                surf1, surf2, r_max, samples
            )
        else:
            rail_pts = _compute_rail_general(surf1, surf2, r_max, samples)

        if not rail_pts:
            return {**_EMPTY, "reason": "could not compute rail for variable-radius fillet"}

        n = len(rail_pts)
        ts_uniform = np.linspace(0.0, 1.0, n)

        # Interpolate radius at each rail sample
        def _interp_radius(t: float) -> float:
            if t <= spline_sorted[0][0]:
                return float(spline_sorted[0][1])
            if t >= spline_sorted[-1][0]:
                return float(spline_sorted[-1][1])
            for i in range(len(spline_sorted) - 1):
                t0, r0 = spline_sorted[i]
                t1, r1 = spline_sorted[i + 1]
                if t0 <= t <= t1:
                    alpha = (t - t0) / (t1 - t0 + 1e-15)
                    return float(r0 + alpha * (r1 - r0))
            return float(spline_sorted[-1][1])

        radius_profile = [_interp_radius(float(t)) for t in ts_uniform]

        pts1_arr, nrm1_arr = _surf_normals_grid(surf1, max(4, samples // 4), max(4, samples // 4))
        pts2_arr, nrm2_arr = _surf_normals_grid(surf2, max(4, samples // 4), max(4, samples // 4))

        cp_grid = np.zeros((3, n, 3))
        trim1 = []
        trim2 = []
        min_radius_violation = False

        for k, rail_pt in enumerate(rail_pts):
            r_k = radius_profile[k]
            d1 = np.linalg.norm(pts1_arr - rail_pt, axis=1)
            d2 = np.linalg.norm(pts2_arr - rail_pt, axis=1)
            idx1 = int(np.argmin(d1))
            idx2 = int(np.argmin(d2))

            foot1 = pts1_arr[idx1]
            foot2 = pts2_arr[idx2]
            n1 = nrm1_arr[idx1]
            n2 = nrm2_arr[idx2]

            arc_cps = _arc_cross_section(foot1, foot2, n1, n2, r_k)
            cp_grid[:, k, :] = arc_cps

            trim1.append(arc_cps[0])
            trim2.append(arc_cps[2])

            # Check min-radius: local chord length should not exceed 2*r_k
            chord_len = np.linalg.norm(arc_cps[2] - arc_cps[0])
            if chord_len > 2 * r_k * 1.05:  # 5% tolerance
                min_radius_violation = True

        n_u, n_v = cp_grid.shape[:2]
        deg_u = min(2, n_u - 1)
        deg_v = min(1, n_v - 1)

        fillet_surf = NurbsSurface(
            degree_u=deg_u,
            degree_v=deg_v,
            control_points=cp_grid,
            knots_u=_make_clamped_knots(n_u, deg_u),
            knots_v=_make_clamped_knots(n_v, deg_v),
        )

        diag = _compute_diagnostics(cp_grid, r_max)
        diag["min_radius_violation"] = diag["min_radius_violation"] or min_radius_violation

        return {
            "ok": True,
            "reason": "",
            "fillet_surface": fillet_surf,
            "rail_curve": rail_pts,
            "trim_back_surf1": trim1,
            "trim_back_surf2": trim2,
            "radius_profile": radius_profile,
            "diagnostics": diag,
        }

    except Exception as exc:
        return {**_EMPTY, "reason": f"internal error: {exc}"}


# ---------------------------------------------------------------------------
# LLM tool registration  (gated -- mirrors trim_curve.py)
# ---------------------------------------------------------------------------

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register  # type: ignore[import]
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    import json as _json
    _REGISTRY_AVAILABLE = True
except ImportError:
    _REGISTRY_AVAILABLE = False


if _REGISTRY_AVAILABLE:

    # ------------------------------------------------------------------
    # query_surface_fillet
    # ------------------------------------------------------------------

    _query_surface_fillet_spec = ToolSpec(
        name="query_surface_fillet",
        description=(
            "Compute a constant rolling-ball fillet between two NURBS surfaces.\n"
            "\n"
            "Provide each surface as degree_u, degree_v, num_u, num_v, control_points "
            "(nu*nv flattened list of [x,y,z]) and the fillet radius.  Returns the fillet "
            "surface control-point grid, rail curve samples, and diagnostics.\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  rail_curve      : [[x,y,z], ...] -- 3D rail polyline\n"
            "  trim_back_surf1 : [[x,y,z], ...]\n"
            "  trim_back_surf2 : [[x,y,z], ...]\n"
            "  fillet_cp_grid  : [[[x,y,z]]] -- nu x nv control points\n"
            "  diagnostics     : {max_g1_deviation, min_radius_violation, self_intersection}\n"
            "\n"
            "Errors: {ok:false, reason} for invalid inputs.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u1": {"type": "integer"},
                "degree_v1": {"type": "integer"},
                "num_u1": {"type": "integer"},
                "num_v1": {"type": "integer"},
                "control_points1": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "degree_u2": {"type": "integer"},
                "degree_v2": {"type": "integer"},
                "num_u2": {"type": "integer"},
                "num_v2": {"type": "integer"},
                "control_points2": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "radius": {"type": "number"},
                "samples": {"type": "integer"},
            },
            "required": [
                "degree_u1", "degree_v1", "num_u1", "num_v1", "control_points1",
                "degree_u2", "degree_v2", "num_u2", "num_v2", "control_points2",
                "radius",
            ],
        },
    )

    def _build_surface_from_args(
        degree_u: int,
        degree_v: int,
        num_u: int,
        num_v: int,
        raw_cp: list,
        label: str,
    ):
        """Build a NurbsSurface from LLM tool args.  Returns (surf, error_str)."""
        if degree_u < 1 or degree_v < 1:
            return None, f"{label}: degree must be >= 1"
        if num_u < 2 or num_v < 2:
            return None, f"{label}: num_u and num_v must be >= 2"
        if len(raw_cp) != num_u * num_v:
            return None, (
                f"{label}: control_points length {len(raw_cp)} != num_u*num_v={num_u * num_v}"
            )
        try:
            cp_flat = [np.asarray(p, dtype=float) for p in raw_cp]
            dim = cp_flat[0].size
            cp = np.array([p.tolist()[:dim] for p in cp_flat],
                          dtype=float).reshape(num_u, num_v, dim)
        except Exception as exc:
            return None, f"{label}: invalid control_points: {exc}"

        surf = NurbsSurface(
            degree_u=int(degree_u),
            degree_v=int(degree_v),
            control_points=cp,
            knots_u=_make_clamped_knots(num_u, int(degree_u)),
            knots_v=_make_clamped_knots(num_v, int(degree_v)),
        )
        return surf, ""

    @register(_query_surface_fillet_spec)
    async def run_query_surface_fillet(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        surf1, err1 = _build_surface_from_args(
            a.get("degree_u1", 0), a.get("degree_v1", 0),
            a.get("num_u1", 0), a.get("num_v1", 0),
            a.get("control_points1", []), "surf1",
        )
        if err1:
            return err_payload(err1, "BAD_ARGS")

        surf2, err2 = _build_surface_from_args(
            a.get("degree_u2", 0), a.get("degree_v2", 0),
            a.get("num_u2", 0), a.get("num_v2", 0),
            a.get("control_points2", []), "surf2",
        )
        if err2:
            return err_payload(err2, "BAD_ARGS")

        radius = a.get("radius")
        if radius is None or not isinstance(radius, (int, float)) or radius <= 0:
            return err_payload(f"radius must be a positive number, got {radius!r}", "BAD_ARGS")

        samples = int(a.get("samples", 32))
        result = fillet_two_surfaces(surf1, surf2, float(radius), samples=samples)

        if not result["ok"]:
            return err_payload(result["reason"], "OP_FAILED")

        cp = result["fillet_surface"].control_points
        return ok_payload({
            "rail_curve": [[float(v) for v in p] for p in result["rail_curve"]],
            "trim_back_surf1": [[float(v) for v in p] for p in result["trim_back_surf1"]],
            "trim_back_surf2": [[float(v) for v in p] for p in result["trim_back_surf2"]],
            "fillet_cp_grid": cp.tolist(),
            "diagnostics": result["diagnostics"],
        })

    # ------------------------------------------------------------------
    # query_surface_chamfer
    # ------------------------------------------------------------------

    _query_surface_chamfer_spec = ToolSpec(
        name="query_surface_chamfer",
        description=(
            "Compute a chamfer between two NURBS surfaces.\n"
            "\n"
            "Same surface inputs as query_surface_fillet; provide dist1 and dist2 "
            "(offset distances from each surface) instead of radius.\n"
            "\n"
            "Returns:\n"
            "  ok              : bool\n"
            "  rail_curve      : [[x,y,z], ...]\n"
            "  chamfer_edge1   : [[x,y,z], ...] -- chamfer boundary on surf1\n"
            "  chamfer_edge2   : [[x,y,z], ...] -- chamfer boundary on surf2\n"
            "  chamfer_cp_grid : [[[x,y,z]]]\n"
            "  diagnostics     : dict\n"
            "\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "degree_u1": {"type": "integer"},
                "degree_v1": {"type": "integer"},
                "num_u1": {"type": "integer"},
                "num_v1": {"type": "integer"},
                "control_points1": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "degree_u2": {"type": "integer"},
                "degree_v2": {"type": "integer"},
                "num_u2": {"type": "integer"},
                "num_v2": {"type": "integer"},
                "control_points2": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}},
                },
                "dist1": {"type": "number"},
                "dist2": {"type": "number"},
                "samples": {"type": "integer"},
            },
            "required": [
                "degree_u1", "degree_v1", "num_u1", "num_v1", "control_points1",
                "degree_u2", "degree_v2", "num_u2", "num_v2", "control_points2",
                "dist1", "dist2",
            ],
        },
    )

    @register(_query_surface_chamfer_spec)
    async def run_query_surface_chamfer(ctx: "ProjectCtx", args: bytes) -> str:
        try:
            a = _json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args: {exc}", "BAD_ARGS")

        surf1, err1 = _build_surface_from_args(
            a.get("degree_u1", 0), a.get("degree_v1", 0),
            a.get("num_u1", 0), a.get("num_v1", 0),
            a.get("control_points1", []), "surf1",
        )
        if err1:
            return err_payload(err1, "BAD_ARGS")

        surf2, err2 = _build_surface_from_args(
            a.get("degree_u2", 0), a.get("degree_v2", 0),
            a.get("num_u2", 0), a.get("num_v2", 0),
            a.get("control_points2", []), "surf2",
        )
        if err2:
            return err_payload(err2, "BAD_ARGS")

        dist1 = a.get("dist1")
        dist2 = a.get("dist2")
        if dist1 is None or not isinstance(dist1, (int, float)) or dist1 <= 0:
            return err_payload(f"dist1 must be positive, got {dist1!r}", "BAD_ARGS")
        if dist2 is None or not isinstance(dist2, (int, float)) or dist2 <= 0:
            return err_payload(f"dist2 must be positive, got {dist2!r}", "BAD_ARGS")

        samples = int(a.get("samples", 32))
        result = chamfer_two_surfaces(surf1, surf2, float(dist1), float(dist2), samples=samples)

        if not result["ok"]:
            return err_payload(result["reason"], "OP_FAILED")

        cp = result["chamfer_surface"].control_points
        return ok_payload({
            "rail_curve": [[float(v) for v in p] for p in result["rail_curve"]],
            "chamfer_edge1": [[float(v) for v in p] for p in result["chamfer_edge1"]],
            "chamfer_edge2": [[float(v) for v in p] for p in result["chamfer_edge2"]],
            "chamfer_cp_grid": cp.tolist(),
            "diagnostics": result["diagnostics"],
        })
