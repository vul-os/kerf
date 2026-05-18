"""
kerf_civil.tin — Triangulated Irregular Network (TIN) terrain model.

Builds a Delaunay TIN from survey points (x, y, z), then extracts
contour poly-lines at arbitrary elevation intervals using linear
interpolation along triangle edges.

Public API
----------
build_tin(points) -> TIN
    Construct a TIN from a sequence of (x, y, z) survey points.
    Returns a TIN dataclass with attributes:
        points   : np.ndarray (N, 3)  — input survey points
        triangles: np.ndarray (M, 3)  — 0-based vertex indices (CCW)

contours(tin, interval, *, z_min=None, z_max=None) -> list[list[tuple]]
    Extract contour polylines at every *interval* metres between *z_min*
    and *z_max*.  Each polyline is a list of (x, y, z) tuples.  Open
    polylines are returned when contours cross the TIN boundary.

slope(tin, triangle_index) -> float
    Return the maximum slope angle (degrees) of a triangle face.

aspect(tin, triangle_index) -> float
    Return the aspect (compass bearing 0–360°, clockwise from North) of the
    steepest downslope direction for a triangle face.

area_2d(tin) -> float
    Total horizontal projected area of the TIN (m²).

volume_above(tin, datum_z) -> float
    Volume of material above the horizontal datum plane at *datum_z* (m³).

Notes
-----
- Requires numpy and scipy (both listed as hard dependencies of kerf-civil).
- All calculations are in the projected CRS of the input points (metres).
- Triangles are oriented counter-clockwise when viewed from above.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import math
import numpy as np
from scipy.spatial import Delaunay


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TIN:
    """Triangulated Irregular Network."""
    points: np.ndarray    # (N, 3) float64 — [x, y, z]
    triangles: np.ndarray # (M, 3) int32   — 0-based indices into points


# ---------------------------------------------------------------------------
# TIN construction
# ---------------------------------------------------------------------------

def build_tin(
    points: Sequence[tuple[float, float, float]] | np.ndarray,
) -> TIN:
    """
    Build a Delaunay TIN from survey points.

    Parameters
    ----------
    points : array-like of shape (N, 3) — (x, y, z) survey points.
             Minimum 3 non-collinear points required.

    Returns
    -------
    TIN dataclass.

    Raises
    ------
    ValueError if fewer than 3 points supplied or all points are collinear.
    """
    pts = np.asarray(points, dtype=float)
    if pts.ndim != 2 or pts.shape[1] != 3:
        raise ValueError(f"points must be shape (N, 3), got {pts.shape!r}")
    if len(pts) < 3:
        raise ValueError(f"Need at least 3 points, got {len(pts)}")

    xy = pts[:, :2]
    tri = Delaunay(xy)

    # Delaunay.simplices are already valid indices; ensure CCW orientation
    triangles = tri.simplices.astype(np.int32)
    # Make all triangles CCW w.r.t. the xy plane (positive z normal)
    triangles = _ensure_ccw(triangles, xy)

    return TIN(points=pts, triangles=triangles)


def _ensure_ccw(triangles: np.ndarray, xy: np.ndarray) -> np.ndarray:
    """Flip any CW triangles to CCW by swapping vertices 1 and 2."""
    out = triangles.copy()
    for i, (a, b, c) in enumerate(out):
        ax, ay = xy[a]
        bx, by = xy[b]
        cx, cy = xy[c]
        cross = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
        if cross < 0:
            out[i, 1], out[i, 2] = out[i, 2], out[i, 1]
    return out


# ---------------------------------------------------------------------------
# Contour extraction
# ---------------------------------------------------------------------------

def contours(
    tin: TIN,
    interval: float,
    *,
    z_min: float | None = None,
    z_max: float | None = None,
) -> list[list[tuple[float, float, float]]]:
    """
    Extract contour polylines from a TIN at a given elevation interval.

    Contours are computed by marching-triangle: for each target elevation
    *z_level* we collect all triangle edges that straddle that elevation,
    linearly interpolate the crossing point on each edge, then chain the
    edge-crossing segments into polylines.

    Parameters
    ----------
    tin      : TIN returned by build_tin()
    interval : float — contour interval in metres (> 0)
    z_min    : float | None — lowest contour elevation (default: ceil of min-z)
    z_max    : float | None — highest contour elevation (default: floor of max-z)

    Returns
    -------
    list of polylines; each polyline is a list of (x, y, z) tuples.
    """
    if interval <= 0:
        raise ValueError(f"interval must be > 0, got {interval!r}")

    zs = tin.points[:, 2]
    if z_min is None:
        z_min = math.ceil(zs.min() / interval) * interval
    if z_max is None:
        z_max = math.floor(zs.max() / interval) * interval

    result: list[list[tuple[float, float, float]]] = []
    level = z_min
    while level <= z_max + 1e-9:
        segs = _contour_at_level(tin, float(level))
        if segs:
            result.extend(_chain_segments(segs, z_val=float(level)))
        level = round(level + interval, 10)
    return result


def _lerp3(p0: np.ndarray, p1: np.ndarray, t: float) -> tuple[float, float, float]:
    """Linearly interpolate between two 3-D points."""
    x = p0[0] + t * (p1[0] - p0[0])
    y = p0[1] + t * (p1[1] - p0[1])
    z = p0[2] + t * (p1[2] - p0[2])
    return (x, y, z)


def _contour_at_level(
    tin: TIN,
    z_level: float,
) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
    """
    Return a list of line segments (pairs of 3-D points) for the contour at
    *z_level*.  Uses the marching-triangle algorithm.
    """
    pts = tin.points
    tris = tin.triangles
    segs: list[tuple[tuple, tuple]] = []

    for tri in tris:
        a, b, c = tri
        za, zb, zc = pts[a, 2], pts[b, 2], pts[c, 2]

        # Classify vertices as above (1) or below/on (0) the level
        above_a = za > z_level
        above_b = zb > z_level
        above_c = zc > z_level

        if above_a == above_b == above_c:
            continue  # all on same side — no contour crossing

        crossings: list[tuple[float, float, float]] = []
        edges = [(a, b, za, zb), (b, c, zb, zc), (c, a, zc, za)]
        for i0, i1, z0, z1 in edges:
            if (z0 - z_level) * (z1 - z_level) < 0:
                t = (z_level - z0) / (z1 - z0)
                crossings.append(_lerp3(pts[i0], pts[i1], t))
            elif z0 == z_level:
                crossings.append(tuple(pts[i0]))  # type: ignore[arg-type]

        # Deduplicate near-identical crossing points (on-vertex cases)
        unique: list[tuple[float, float, float]] = []
        for cp in crossings:
            if not any(
                abs(cp[0] - u[0]) < 1e-9 and abs(cp[1] - u[1]) < 1e-9
                for u in unique
            ):
                unique.append(cp)

        if len(unique) >= 2:
            segs.append((unique[0], unique[1]))

    return segs


def _chain_segments(
    segs: list[tuple[tuple, tuple]],
    z_val: float,
) -> list[list[tuple[float, float, float]]]:
    """
    Chain disconnected segments into polylines by matching endpoints.
    Returns a list of polylines (each a list of (x, y, z) tuples).
    """
    # Build adjacency by matching endpoints within tolerance
    tol = 1e-6
    remaining = list(segs)
    polylines: list[list[tuple[float, float, float]]] = []

    while remaining:
        seg = remaining.pop(0)
        line: list[tuple[float, float, float]] = list(seg)  # type: ignore[arg-type]

        # Try to extend forward
        changed = True
        while changed:
            changed = False
            end = line[-1]
            for i, s in enumerate(remaining):
                if abs(s[0][0] - end[0]) < tol and abs(s[0][1] - end[1]) < tol:
                    line.append(s[1])
                    remaining.pop(i)
                    changed = True
                    break
                if abs(s[1][0] - end[0]) < tol and abs(s[1][1] - end[1]) < tol:
                    line.append(s[0])
                    remaining.pop(i)
                    changed = True
                    break

        # Try to extend backward
        changed = True
        while changed:
            changed = False
            start = line[0]
            for i, s in enumerate(remaining):
                if abs(s[1][0] - start[0]) < tol and abs(s[1][1] - start[1]) < tol:
                    line.insert(0, s[0])
                    remaining.pop(i)
                    changed = True
                    break
                if abs(s[0][0] - start[0]) < tol and abs(s[0][1] - start[1]) < tol:
                    line.insert(0, s[1])
                    remaining.pop(i)
                    changed = True
                    break

        polylines.append(line)

    return polylines


# ---------------------------------------------------------------------------
# Terrain analysis helpers
# ---------------------------------------------------------------------------

def _triangle_normal(tin: TIN, idx: int) -> np.ndarray:
    """Return the unit normal vector of triangle *idx* (pointing upward)."""
    a, b, c = tin.triangles[idx]
    pa, pb, pc = tin.points[a], tin.points[b], tin.points[c]
    u = pb - pa
    v = pc - pa
    n = np.cross(u, v)
    mag = np.linalg.norm(n)
    if mag < 1e-15:
        return np.array([0.0, 0.0, 1.0])
    n = n / mag
    if n[2] < 0:
        n = -n
    return n


def slope(tin: TIN, triangle_index: int) -> float:
    """
    Maximum slope angle (degrees) of triangle *triangle_index*.

    0° = horizontal, 90° = vertical cliff.
    """
    n = _triangle_normal(tin, triangle_index)
    # Angle from vertical = arccos(n_z); slope from horizontal = 90 - that
    cos_z = float(np.clip(n[2], -1.0, 1.0))
    return math.degrees(math.acos(cos_z))


def aspect(tin: TIN, triangle_index: int) -> float:
    """
    Aspect (compass bearing 0–360°, clockwise from North) of the steepest
    downslope direction for triangle *triangle_index*.

    Returns 0.0 for a perfectly horizontal face.
    """
    n = _triangle_normal(tin, triangle_index)
    nx, ny = float(n[0]), float(n[1])
    if abs(nx) < 1e-12 and abs(ny) < 1e-12:
        return 0.0
    # Downslope direction projected to xy: (-nx, -ny)
    # Compass bearing (N = +y axis, clockwise)
    bearing = math.degrees(math.atan2(-nx, ny)) % 360
    return bearing


def area_2d(tin: TIN) -> float:
    """Total horizontal (xy) projected area of the TIN (m²)."""
    total = 0.0
    pts = tin.points
    for tri in tin.triangles:
        a, b, c = tri
        ax, ay = pts[a, 0], pts[a, 1]
        bx, by = pts[b, 0], pts[b, 1]
        cx, cy = pts[c, 0], pts[c, 1]
        total += abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) * 0.5
    return total


def volume_above(tin: TIN, datum_z: float) -> float:
    """
    Approximate volume of material above a horizontal datum plane at *datum_z*
    (m³), computed as the sum of truncated-prism volumes per triangle.

    Uses the average height formula: V_i = A_i × mean(max(z_j - datum, 0)).
    """
    total = 0.0
    pts = tin.points
    for tri in tin.triangles:
        a, b, c = tri
        ax, ay, az = pts[a]
        bx, by, bz = pts[b]
        cx, cy, cz = pts[c]
        # Projected area
        area_i = abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) * 0.5
        # Average excess height above datum (clipped at 0)
        h_avg = (max(az - datum_z, 0.0) + max(bz - datum_z, 0.0) + max(cz - datum_z, 0.0)) / 3.0
        total += area_i * h_avg
    return total
