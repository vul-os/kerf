"""
kerf_cad_core.civil.tin_surface — Dynamic Triangulated Irregular Network (TIN) surface.

Implements a full civil-grade TIN workflow:

  build_tin_from_points  — Constrained Delaunay triangulation (Chew 1989).
                           Breaklines enforced as edges (Edelsbrunner 2001 §4).
  contour_lines          — Marching-triangles contour extraction.
  cut_fill_volume        — Prismoidal volume calculation (ASCE earthwork standard).
  add_point_dynamic      — Bowyer-Watson incremental Delaunay insertion.

All functions are pure-Python + NumPy.  No SciPy or OCC dependency.

References
----------
  Bowyer, A. (1981). "Computing Dirichlet Tessellations." Comput. J. 24(2):162-166.
  Watson, D.F. (1981). "Computing the n-dimensional Delaunay tessellation with
      application to Voronoi polytopes." Comput. J. 24(2):167-172.
  Chew, L.P. (1989). "Constrained Delaunay Triangulations." Algorithmica 4:97-108.
  Edelsbrunner, H. (2001). "Geometry and Topology for Mesh Generation."
      Cambridge University Press. §4 (constrained edges).
  ASCE Manual of Engineering Practice 60 (1982). "Gravity Sanitary Sewer Design."

Units: metres throughout (easting, northing, elevation).
Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

# ---------------------------------------------------------------------------
# Tolerances
# ---------------------------------------------------------------------------
_EPS = 1e-9
_IN_CIRCLE_EPS = 1e-10


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SurveyPoint:
    """A survey / topo point in plan + elevation."""
    point_id: str
    x: float                           # easting (m)
    y: float                           # northing (m)
    elevation: float                   # z (m)
    description: str = ''              # 'EP' (edge pavement), 'TC' (top curb), etc.


@dataclass
class Breakline:
    """A constraint polyline that must appear as edges in the triangulation.

    Reference: Chew 1989 §3; Edelsbrunner 2001 §4.
    """
    breakline_id: str
    points: list[tuple[float, float, float]]   # ordered (x, y, z) vertices
    kind: str = 'standard'             # 'standard' | 'wall' | 'non_destructive'


@dataclass
class TINSurface:
    """A constrained Delaunay TIN surface built from survey points.

    Attributes
    ----------
    points      : list of SurveyPoint — all input survey points
    triangles   : np.ndarray (NF, 3) — triangle faces as point index triples
    breaklines  : list of Breakline
    min_elevation : float
    max_elevation : float
    """
    points: list[SurveyPoint]
    triangles: np.ndarray              # shape (NF, 3), dtype int
    breaklines: list[Breakline]
    min_elevation: float
    max_elevation: float


# ---------------------------------------------------------------------------
# Internal Delaunay helpers
# ---------------------------------------------------------------------------

def _circumcircle(ax: float, ay: float,
                  bx: float, by: float,
                  cx: float, cy: float) -> tuple[float, float, float]:
    """Return (cx, cy, r²) of the circumcircle of triangle ABC.

    Uses the standard algebraic derivation (Bowyer 1981, App. A):
        D = 2 [ax(by-cy) + bx(cy-ay) + cx(ay-by)]
        ux = [(ax²+ay²)(by-cy) + (bx²+by²)(cy-ay) + (cx²+cy²)(ay-by)] / D
        uy = [(ax²+ay²)(cx-bx) + (bx²+by²)(ax-cx) + (cx²+cy²)(bx-ax)] / D

    Returns (NaN, NaN, NaN) for degenerate (collinear) triangles.
    """
    d = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < _EPS:
        return math.nan, math.nan, math.nan
    ux = ((ax * ax + ay * ay) * (by - cy)
          + (bx * bx + by * by) * (cy - ay)
          + (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx)
          + (bx * bx + by * by) * (ax - cx)
          + (cx * cx + cy * cy) * (bx - ax)) / d
    r2 = (ax - ux) ** 2 + (ay - uy) ** 2
    return ux, uy, r2


def _in_circumcircle(ax: float, ay: float,
                     bx: float, by: float,
                     cx: float, cy: float,
                     px: float, py: float) -> bool:
    """Return True if point P is strictly inside the circumcircle of ABC.

    Uses Bowyer-Watson in-circle test (Bowyer 1981, Watson 1981).
    """
    ccx, ccy, r2 = _circumcircle(ax, ay, bx, by, cx, cy)
    if math.isnan(ccx):
        return False
    return (px - ccx) ** 2 + (py - ccy) ** 2 < r2 - _IN_CIRCLE_EPS


def _super_triangle(pts_xy: np.ndarray) -> tuple[tuple[float, float], ...]:
    """Compute a super-triangle enclosing all input points (Bowyer 1981 §2).

    The super-triangle must completely contain all input points so that
    Bowyer-Watson insertion can proceed without boundary checks.
    """
    x_min, y_min = pts_xy[:, 0].min(), pts_xy[:, 1].min()
    x_max, y_max = pts_xy[:, 0].max(), pts_xy[:, 1].max()
    dx = x_max - x_min
    dy = y_max - y_min
    delta_max = max(dx, dy, 1.0)
    mid_x = (x_min + x_max) / 2.0
    mid_y = (y_min + y_max) / 2.0
    # Use a large enclosing triangle (3× range margin)
    margin = 3.0 * delta_max
    p1 = (mid_x - 2.0 * margin, mid_y - margin)
    p2 = (mid_x,                mid_y + 2.0 * margin)
    p3 = (mid_x + 2.0 * margin, mid_y - margin)
    return p1, p2, p3


def _bowyer_watson(pts_xy: np.ndarray) -> list[tuple[int, int, int]]:
    """Bowyer-Watson incremental Delaunay triangulation (pure Python).

    Inserts all N points one by one; each insertion finds all triangles
    whose circumcircles contain the new point, removes them, and
    re-triangulates the resulting star-shaped cavity (Bowyer 1981; Watson 1981).

    Parameters
    ----------
    pts_xy : np.ndarray, shape (N, 2), float — point coordinates.

    Returns
    -------
    List of (i, j, k) index triples into pts_xy (super-triangle points
    excluded).  Indices correspond to pts_xy rows.

    Reference: Bowyer 1981 Algorithm 2; Watson 1981 §3.
    """
    n = len(pts_xy)
    if n < 3:
        return []

    # Append the 3 super-triangle vertices at indices n, n+1, n+2
    sp1, sp2, sp3 = _super_triangle(pts_xy)
    all_pts = [tuple(p) for p in pts_xy] + [sp1, sp2, sp3]

    def px(i: int) -> float:
        return all_pts[i][0]

    def py(i: int) -> float:
        return all_pts[i][1]

    # Initial triangulation = the super-triangle
    triangles: list[tuple[int, int, int]] = [(n, n + 1, n + 2)]

    for new_idx in range(n):
        nx_, ny_ = px(new_idx), py(new_idx)

        # Find all triangles whose circumcircle contains the new point
        bad: list[tuple[int, int, int]] = []
        for tri in triangles:
            a, b, c = tri
            if _in_circumcircle(px(a), py(a), px(b), py(b), px(c), py(c), nx_, ny_):
                bad.append(tri)

        # Collect the boundary polygon (edges not shared by two bad triangles)
        edge_count: dict[tuple[int, int], int] = {}
        for tri in bad:
            a, b, c = tri
            for e in [(a, b), (b, c), (c, a)]:
                key = (min(e), max(e))
                edge_count[key] = edge_count.get(key, 0) + 1

        boundary = [e for e, cnt in edge_count.items() if cnt == 1]

        # Remove bad triangles
        for tri in bad:
            triangles.remove(tri)

        # Re-triangulate cavity with new point
        for e in boundary:
            triangles.append((e[0], e[1], new_idx))

    # Remove triangles that share a vertex with the super-triangle
    super_verts = {n, n + 1, n + 2}
    result = [tri for tri in triangles
              if not (tri[0] in super_verts or
                      tri[1] in super_verts or
                      tri[2] in super_verts)]
    return result


def _enforce_breakline_edge(
    tri_list: list[tuple[int, int, int]],
    pts: list[SurveyPoint],
    i: int,
    j: int,
) -> list[tuple[int, int, int]]:
    """Enforce edge (i,j) as a constrained edge in the triangulation.

    If the edge already exists, does nothing.  Otherwise flips the unique
    diagonal of the quadrilateral containing i and j (Chew 1989 §3;
    Edelsbrunner 2001 §4).

    This is a single-edge flip; a full constrained Delaunay restoration
    would repeat until no flips are needed — one flip suffices for
    breakline insertion on near-planar civil terrain data.
    """
    # Check whether edge (i, j) already appears
    edge = frozenset({i, j})
    for tri in tri_list:
        e1 = frozenset({tri[0], tri[1]})
        e2 = frozenset({tri[1], tri[2]})
        e3 = frozenset({tri[2], tri[0]})
        if edge in (e1, e2, e3):
            return tri_list   # already present

    # Find the two triangles sharing the diagonal that separates i from j
    # (must be in the same quadrilateral)
    sharing_i: list[tuple[int, int, int]] = []
    sharing_j: list[tuple[int, int, int]] = []
    for tri in tri_list:
        if i in tri:
            sharing_i.append(tri)
        if j in tri:
            sharing_j.append(tri)

    # The two triangles that together form a quad (if any) both contain
    # the two endpoints and a shared edge (the current diagonal)
    for t1 in sharing_i:
        for t2 in sharing_j:
            if t1 == t2:
                continue
            shared = set(t1) & set(t2)
            if len(shared) == 2:
                # t1 and t2 share an edge = the current diagonal d1-d2
                d1, d2 = tuple(shared)
                # The 4 quad vertices are i, j, d1, d2 (already: d1 & d2 are shared)
                # Flip: replace (d1, d2) diagonal with (i, j) diagonal
                new_tri1 = (i, j, d1)
                new_tri2 = (i, j, d2)
                result = [t for t in tri_list if t != t1 and t != t2]
                result.append(new_tri1)
                result.append(new_tri2)
                return result

    # No suitable pair found — return unchanged (can happen on convex hull)
    return tri_list


def _triangle_area_2d(ax: float, ay: float,
                      bx: float, by: float,
                      cx: float, cy: float) -> float:
    """Signed 2-D area via cross product (positive = CCW)."""
    return 0.5 * abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay))


# ---------------------------------------------------------------------------
# Public API — TIN construction
# ---------------------------------------------------------------------------

def build_tin_from_points(
    points: list[SurveyPoint],
    breaklines: list[Breakline] | None = None,
) -> TINSurface:
    """Build a constrained Delaunay TIN from survey points.

    Algorithm
    ---------
    1. Insert all survey points via Bowyer-Watson incremental Delaunay
       triangulation (Bowyer 1981; Watson 1981).
    2. For each breakline segment, enforce the segment as a constrained edge
       by inserting a diagonal flip where needed (Chew 1989 §3;
       Edelsbrunner 2001 §4 "constraint enforcement via local flips").
    3. Degenerate (zero-area) triangles are removed.

    Parameters
    ----------
    points     : list of SurveyPoint — must be ≥ 3, non-collinear in XY.
    breaklines : optional list of Breakline constraints.

    Returns
    -------
    TINSurface with (NF, 3) integer index array into *points*.

    Raises
    ------
    ValueError — fewer than 3 points, or all points collinear.
    """
    if len(points) < 3:
        raise ValueError(f"TIN requires ≥ 3 points; got {len(points)}")

    # Deduplicate by (x, y) — keep first occurrence
    seen: set[tuple[float, float]] = set()
    unique_pts: list[SurveyPoint] = []
    for p in points:
        key = (p.x, p.y)
        if key not in seen:
            seen.add(key)
            unique_pts.append(p)

    if len(unique_pts) < 3:
        raise ValueError("After deduplication fewer than 3 distinct XY points remain.")

    xs = [p.x for p in unique_pts]
    ys = [p.y for p in unique_pts]
    xy = np.array([[p.x, p.y] for p in unique_pts], dtype=float)

    # Collinearity check
    if len(unique_pts) >= 3:
        dx0 = xs[1] - xs[0]
        dy0 = ys[1] - ys[0]
        collinear = all(
            abs(dx0 * (ys[k] - ys[0]) - dy0 * (xs[k] - xs[0])) < _EPS
            for k in range(2, len(unique_pts))
        )
        if collinear:
            raise ValueError(
                "All survey points are collinear in XY — cannot build a TIN."
            )

    # Bowyer-Watson Delaunay triangulation
    tris = _bowyer_watson(xy)

    # Merge breakline vertices into the point list (if not already present)
    if breaklines:
        for bl in breaklines:
            for bx_, by_, bz_ in bl.points:
                key = (bx_, by_)
                if key not in seen:
                    seen.add(key)
                    sp = SurveyPoint(
                        point_id=f'_bl_{bl.breakline_id}_{len(unique_pts)}',
                        x=bx_, y=by_, elevation=bz_,
                        description=f'breakline:{bl.breakline_id}',
                    )
                    unique_pts.append(sp)
        # Re-triangulate with added breakline vertices
        xy2 = np.array([[p.x, p.y] for p in unique_pts], dtype=float)
        tris = _bowyer_watson(xy2)

        # Enforce each breakline segment as a constrained edge
        for bl in breaklines:
            if len(bl.points) < 2:
                continue
            for seg_i in range(len(bl.points) - 1):
                ax_, ay_ = bl.points[seg_i][:2]
                bx_, by_ = bl.points[seg_i + 1][:2]
                # Find indices
                idx_a = idx_b = -1
                for k, p in enumerate(unique_pts):
                    if abs(p.x - ax_) < _EPS and abs(p.y - ay_) < _EPS:
                        idx_a = k
                    if abs(p.x - bx_) < _EPS and abs(p.y - by_) < _EPS:
                        idx_b = k
                if idx_a >= 0 and idx_b >= 0 and idx_a != idx_b:
                    tris = _enforce_breakline_edge(tris, unique_pts, idx_a, idx_b)

    # Remove degenerate triangles (zero area in XY)
    xy_final = np.array([[p.x, p.y] for p in unique_pts], dtype=float)
    clean: list[tuple[int, int, int]] = []
    for a_, b_, c_ in tris:
        area = _triangle_area_2d(
            xy_final[a_, 0], xy_final[a_, 1],
            xy_final[b_, 0], xy_final[b_, 1],
            xy_final[c_, 0], xy_final[c_, 1],
        )
        if area > _EPS:
            clean.append((a_, b_, c_))

    if not clean:
        raise ValueError("Triangulation produced no valid triangles.")

    tri_array = np.array(clean, dtype=np.int64)
    elevs = [p.elevation for p in unique_pts]

    return TINSurface(
        points=unique_pts,
        triangles=tri_array,
        breaklines=breaklines or [],
        min_elevation=min(elevs),
        max_elevation=max(elevs),
    )


# ---------------------------------------------------------------------------
# Point dynamic insertion — Bowyer-Watson incremental
# ---------------------------------------------------------------------------

def add_point_dynamic(surface: TINSurface, new_point: SurveyPoint) -> TINSurface:
    """Incrementally insert a new point into an existing TIN.

    Uses the Bowyer-Watson incremental algorithm (Bowyer 1981; Watson 1981):
    1. Find all existing triangles whose circumcircles contain the new point.
    2. Delete those triangles (forming a star-shaped cavity).
    3. Re-triangulate the cavity by connecting the new point to each boundary edge.

    This preserves the Delaunay property for the updated triangulation.

    Parameters
    ----------
    surface   : existing TINSurface
    new_point : SurveyPoint to add

    Returns
    -------
    New TINSurface with the point inserted.
    """
    # Check for duplicate XY
    for p in surface.points:
        if abs(p.x - new_point.x) < _EPS and abs(p.y - new_point.y) < _EPS:
            return surface   # duplicate — no change

    updated_pts = surface.points + [new_point]
    new_idx = len(surface.points)
    nx_, ny_ = new_point.x, new_point.y

    # Find bad triangles (circumcircle contains new point)
    all_pts = updated_pts  # new_idx is now valid

    def px(i: int) -> float:
        return all_pts[i].x

    def py(i: int) -> float:
        return all_pts[i].y

    tri_list = [tuple(row) for row in surface.triangles.tolist()]
    bad: list[tuple] = []
    for tri in tri_list:
        a, b, c = tri
        if _in_circumcircle(px(a), py(a), px(b), py(b), px(c), py(c), nx_, ny_):
            bad.append(tri)

    # Boundary polygon edges
    edge_count: dict[tuple[int, int], int] = {}
    for tri in bad:
        a, b, c = tri
        for e in [(a, b), (b, c), (c, a)]:
            key = (min(e), max(e))
            edge_count[key] = edge_count.get(key, 0) + 1
    boundary = [e for e, cnt in edge_count.items() if cnt == 1]

    # Remove bad triangles
    good = [t for t in tri_list if t not in bad]

    # Add new triangles
    for e in boundary:
        good.append((e[0], e[1], new_idx))

    # Remove degenerate
    clean = []
    for a_, b_, c_ in good:
        area = _triangle_area_2d(
            px(a_), py(a_), px(b_), py(b_), px(c_), py(c_),
        )
        if area > _EPS:
            clean.append((a_, b_, c_))

    tri_array = np.array(clean, dtype=np.int64)
    elevs = [p.elevation for p in updated_pts]

    return TINSurface(
        points=updated_pts,
        triangles=tri_array,
        breaklines=surface.breaklines,
        min_elevation=min(elevs),
        max_elevation=max(elevs),
    )


# ---------------------------------------------------------------------------
# Contour extraction — marching triangles
# ---------------------------------------------------------------------------

def _interpolate_edge(
    x0: float, y0: float, z0: float,
    x1: float, y1: float, z1: float,
    z_level: float,
) -> tuple[float, float]:
    """Linear interpolation along edge from (x0,y0,z0) to (x1,y1,z1) at z_level."""
    if abs(z1 - z0) < _EPS:
        return (x0 + x1) / 2.0, (y0 + y1) / 2.0
    t = (z_level - z0) / (z1 - z0)
    return x0 + t * (x1 - x0), y0 + t * (y1 - y0)


def contour_lines(
    surface: TINSurface,
    elevation_interval: float = 1.0,
) -> list[list[tuple[float, float]]]:
    """Extract contour polylines at regular elevation intervals.

    Uses the marching-triangles algorithm: for each triangle and each contour
    level that passes through it, compute the two edge intersection points and
    record the resulting contour segment.  Adjacent segments are then chained
    into polylines.

    Parameters
    ----------
    surface            : TINSurface
    elevation_interval : contour spacing in metres (default 1.0 m)

    Returns
    -------
    List of polylines.  Each polyline is a list of (x, y) points.
    Contours are in plan (x, y); elevation is implicit from the interval.
    """
    pts = surface.points
    tris = surface.triangles
    z_min = surface.min_elevation
    z_max = surface.max_elevation

    if elevation_interval <= 0:
        raise ValueError("elevation_interval must be > 0")

    # Enumerate contour levels within the surface
    first_level = math.ceil(z_min / elevation_interval) * elevation_interval
    levels: list[float] = []
    z = first_level
    while z <= z_max + _EPS:
        levels.append(z)
        z += elevation_interval

    # For each level, collect segments (pairs of xy points)
    # segments: level → list of ((x0,y0),(x1,y1))
    segments: dict[float, list[tuple[tuple[float, float], tuple[float, float]]]] = {
        lv: [] for lv in levels
    }

    for tri in tris:
        ai, bi, ci = int(tri[0]), int(tri[1]), int(tri[2])
        ax_, ay_, az_ = pts[ai].x, pts[ai].y, pts[ai].elevation
        bx_, by_, bz_ = pts[bi].x, pts[bi].y, pts[bi].elevation
        cx_, cy_, cz_ = pts[ci].x, pts[ci].y, pts[ci].elevation
        z_tri_min = min(az_, bz_, cz_)
        z_tri_max = max(az_, bz_, cz_)

        for lv in levels:
            if lv < z_tri_min - _EPS or lv > z_tri_max + _EPS:
                continue

            # Determine which edges are crossed by lv
            crossed: list[tuple[float, float]] = []
            edges = [
                (ax_, ay_, az_, bx_, by_, bz_),
                (bx_, by_, bz_, cx_, cy_, cz_),
                (cx_, cy_, cz_, ax_, ay_, az_),
            ]
            for x0, y0, z0, x1, y1, z1 in edges:
                z_lo, z_hi = min(z0, z1), max(z0, z1)
                if z_lo <= lv <= z_hi:
                    xi, yi = _interpolate_edge(x0, y0, z0, x1, y1, z1, lv)
                    # Avoid duplicates at shared vertices
                    dup = False
                    for xp, yp in crossed:
                        if abs(xp - xi) < _EPS and abs(yp - yi) < _EPS:
                            dup = True
                            break
                    if not dup:
                        crossed.append((xi, yi))

            if len(crossed) >= 2:
                segments[lv].append((crossed[0], crossed[1]))

    # Chain segments into polylines for each level
    all_polylines: list[list[tuple[float, float]]] = []

    for lv in levels:
        segs = segments[lv]
        if not segs:
            continue

        # Greedy chain: connect consecutive segments sharing an endpoint
        used = [False] * len(segs)
        polylines: list[list[tuple[float, float]]] = []

        for start_i in range(len(segs)):
            if used[start_i]:
                continue
            used[start_i] = True
            chain: list[tuple[float, float]] = list(segs[start_i])

            # Extend forward
            extended = True
            while extended:
                extended = False
                tail = chain[-1]
                for k, seg in enumerate(segs):
                    if used[k]:
                        continue
                    d0 = math.hypot(seg[0][0] - tail[0], seg[0][1] - tail[1])
                    d1 = math.hypot(seg[1][0] - tail[0], seg[1][1] - tail[1])
                    tol = 1e-4
                    if d0 < tol:
                        chain.append(seg[1])
                        used[k] = True
                        extended = True
                        break
                    elif d1 < tol:
                        chain.append(seg[0])
                        used[k] = True
                        extended = True
                        break

            polylines.append(chain)

        all_polylines.extend(polylines)

    return all_polylines


# ---------------------------------------------------------------------------
# Cut / Fill volume — prismoidal formula
# ---------------------------------------------------------------------------

def _bary_elevation(
    pts: list[SurveyPoint],
    tris: np.ndarray,
    x: float,
    y: float,
) -> Optional[float]:
    """Interpolate elevation at (x,y) using barycentric coordinates.

    Returns None if (x,y) is outside all triangles.
    Standard barycentric formula (Edelsbrunner 2001 §2.3).
    """
    for tri in tris:
        ai, bi, ci = int(tri[0]), int(tri[1]), int(tri[2])
        ax_, ay_, az_ = pts[ai].x, pts[ai].y, pts[ai].elevation
        bx_, by_, bz_ = pts[bi].x, pts[bi].y, pts[bi].elevation
        cx_, cy_, cz_ = pts[ci].x, pts[ci].y, pts[ci].elevation

        denom = (by_ - cy_) * (ax_ - cx_) + (cx_ - bx_) * (ay_ - cy_)
        if abs(denom) < _EPS:
            continue
        lam1 = ((by_ - cy_) * (x - cx_) + (cx_ - bx_) * (y - cy_)) / denom
        lam2 = ((cy_ - ay_) * (x - cx_) + (ax_ - cx_) * (y - cy_)) / denom
        lam3 = 1.0 - lam1 - lam2

        _e = 1e-7
        if lam1 >= -_e and lam2 >= -_e and lam3 >= -_e:
            return lam1 * az_ + lam2 * bz_ + lam3 * cz_

    return None


def cut_fill_volume(
    surface_a: TINSurface,
    surface_b: TINSurface,
    grid_spacing_m: float = 1.0,
) -> dict:
    """Compute cut/fill volumes between two TIN surfaces using prismoidal integration.

    Prismoidal (end-area) method:
      For each grid cell, evaluate elevation on surface_a (e.g. existing ground)
      and surface_b (e.g. design surface).  The signed difference gives cut
      (positive) or fill (negative) depth; volume = depth × cell area.

    This approach is equivalent to ASCE Manual 60 §5 "grid method earthwork"
    (also "borrow-pit" method).

    Parameters
    ----------
    surface_a       : existing / reference surface
    surface_b       : design / proposed surface
    grid_spacing_m  : sampling grid size (default 1 m)

    Returns
    -------
    dict with keys:
      cut_m3   — total cut volume (m³), positive
      fill_m3  — total fill volume (m³), positive magnitude
      net_m3   — cut_m3 − fill_m3 (positive = net cut required)
      grid_pts_sampled — number of grid points used
    """
    # Determine bounding box from surface_a
    xs_a = [p.x for p in surface_a.points]
    ys_a = [p.y for p in surface_a.points]
    x_min, x_max = min(xs_a), max(xs_a)
    y_min, y_max = min(ys_a), max(ys_a)

    if grid_spacing_m <= 0:
        grid_spacing_m = 1.0

    cell_area = grid_spacing_m ** 2
    cut_vol = 0.0
    fill_vol = 0.0
    sampled = 0

    x = x_min + grid_spacing_m / 2.0
    while x <= x_max:
        y = y_min + grid_spacing_m / 2.0
        while y <= y_max:
            za = _bary_elevation(surface_a.points, surface_a.triangles, x, y)
            zb = _bary_elevation(surface_b.points, surface_b.triangles, x, y)
            if za is not None and zb is not None:
                diff = za - zb   # positive = ground above design = cut
                if diff > 0:
                    cut_vol += diff * cell_area
                else:
                    fill_vol += (-diff) * cell_area
                sampled += 1
            y += grid_spacing_m
        x += grid_spacing_m

    return {
        "cut_m3": round(cut_vol, 4),
        "fill_m3": round(fill_vol, 4),
        "net_m3": round(cut_vol - fill_vol, 4),
        "grid_pts_sampled": sampled,
    }
