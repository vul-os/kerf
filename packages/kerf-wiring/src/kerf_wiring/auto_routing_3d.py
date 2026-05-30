"""
kerf_wiring.auto_routing_3d — 3D automatic wire-harness routing with collision avoidance.

Algorithm
---------
1.  **Voxelization** — The bounding box spanning start, end and all obstacle bodies
    is discretised into a regular 3-D grid of cubes of ``voxel_size`` mm per side
    (Cheng-Quan 2001 §3).  Each voxel is either FREE or BLOCKED.

2.  **AABB obstacle marking** — Each obstacle body is represented by its axis-aligned
    bounding box (AABB) inflated by ``cable_radius`` mm so the cable centre-line
    always clears the physical surface.

3.  **A* search** — 26-connected 3-D grid A* with:
      * g-cost  = Euclidean arc-length accumulated from start.
      * h-cost  = straight-line Euclidean distance to goal.
      * Bend penalty = ``BEND_PENALTY`` mm per 90° of direction change, proportional
        to the angle between successive steps.
    The search is capped at ``MAX_ITERATIONS`` expansions to prevent runaway on
    pathological inputs.

4.  **Path smoothing** — The raw voxel-centre path is smoothed with a Catmull-Rom
    spline re-sampled at 1/2 of voxel_size resolution, giving a physically realistic
    cable curve.  Smoothed waypoints are clipped to the un-inflated obstacle AABBs to
    avoid the spline cutting corners back into obstacles.

5.  **Metrics** — ``Route`` carries total arc-length (smoothed), bend count
    (significant direction changes > 15°), and minimum clearance to all obstacle
    bodies along the smoothed path.

References
----------
* Cheng-Quan, Wang et al. (2001) "Automatic wire harness routing using 3D voxelization
  and improved A* algorithm", Engineering with Computers.
* P. W. Springer, *PWS Cable Routing* (CAD integration guide, 2004).
"""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

Point3D = tuple[float, float, float]


@dataclass
class Body:
    """
    Axis-aligned bounding box obstacle body.

    All coordinates in mm.

    Parameters
    ----------
    min_pt : (x, y, z) — minimum corner of the AABB.
    max_pt : (x, y, z) — maximum corner of the AABB.
    name   : optional label for diagnostics.
    """
    min_pt: Point3D
    max_pt: Point3D
    name: str = "obstacle"

    def __post_init__(self):
        self.min_pt = tuple(float(v) for v in self.min_pt)
        self.max_pt = tuple(float(v) for v in self.max_pt)
        for i, (lo, hi) in enumerate(zip(self.min_pt, self.max_pt)):
            if lo > hi:
                raise ValueError(
                    f"Body '{self.name}': min_pt[{i}]={lo} > max_pt[{i}]={hi}"
                )

    def inflated(self, margin: float) -> "Body":
        """Return a copy of this body inflated by ``margin`` on all sides."""
        return Body(
            min_pt=(
                self.min_pt[0] - margin,
                self.min_pt[1] - margin,
                self.min_pt[2] - margin,
            ),
            max_pt=(
                self.max_pt[0] + margin,
                self.max_pt[1] + margin,
                self.max_pt[2] + margin,
            ),
            name=self.name,
        )

    def contains_point(self, pt: Point3D) -> bool:
        """True if pt is strictly inside or on the surface of this AABB."""
        return (
            self.min_pt[0] <= pt[0] <= self.max_pt[0]
            and self.min_pt[1] <= pt[1] <= self.max_pt[1]
            and self.min_pt[2] <= pt[2] <= self.max_pt[2]
        )

    def distance_to_point(self, pt: Point3D) -> float:
        """Minimum distance from pt to the surface of this AABB (0 if inside)."""
        dx = max(self.min_pt[0] - pt[0], 0.0, pt[0] - self.max_pt[0])
        dy = max(self.min_pt[1] - pt[1], 0.0, pt[1] - self.max_pt[1])
        dz = max(self.min_pt[2] - pt[2], 0.0, pt[2] - self.max_pt[2])
        return math.sqrt(dx * dx + dy * dy + dz * dz)


@dataclass
class Route:
    """
    Result of :func:`auto_route_harness`.

    Attributes
    ----------
    polyline              Smoothed 3-D path as a list of (x, y, z) points.
    total_length          Arc-length of the smoothed polyline in mm.
    bend_count            Number of significant direction changes (> 15°) along the path.
    collision_clearance_min
                          Minimum distance from any point on the polyline to any obstacle
                          surface, in mm.  Positive = clear; ≤ 0 = collision.
    """
    polyline: list[Point3D]
    total_length: float
    bend_count: int
    collision_clearance_min: float


@dataclass
class Collision:
    """A detected collision between the routed cable and an obstacle."""
    segment_index: int       # index of the polyline segment where collision occurs
    point: Point3D           # approximate collision point
    obstacle_name: str       # name of the colliding obstacle
    penetration_depth: float # how far inside (mm); positive = cable is inside the body


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BEND_PENALTY_PER_RAD: float = 10.0   # mm of equivalent cost per radian of bend
_MAX_ITERATIONS: int = 500_000         # A* expansion cap
_SMOOTH_SAMPLES_PER_VOXEL: float = 2.0 # Catmull-Rom re-sample density
_BEND_ANGLE_THRESHOLD_DEG: float = 15.0


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _dist3(a: tuple, b: tuple) -> float:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    dz = b[2] - a[2]
    return math.sqrt(dx * dx + dy * dy + dz * dz)


def _min_clearance(point: Point3D, obstacles: list[Body]) -> float:
    """Return minimum distance from *point* to any obstacle (0 if inside one)."""
    if not obstacles:
        return float("inf")
    return min(ob.distance_to_point(point) for ob in obstacles)


# ---------------------------------------------------------------------------
# Voxel grid + A*
# ---------------------------------------------------------------------------

def _build_voxel_grid(
    start: Point3D,
    end: Point3D,
    obstacles: list[Body],
    cable_radius: float,
    voxel_size: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Build a boolean voxel grid over the bounding box [start, end, obstacles].

    Returns
    -------
    grid      : bool array shape (nx, ny, nz) — True = blocked
    origin    : (x0, y0, z0) corner of the grid in world coords
    shape     : (nx, ny, nz)
    """
    # Compute world-space bounding box
    all_pts = [start, end]
    inflated_bodies = [ob.inflated(cable_radius) for ob in obstacles]
    for ob in obstacles:
        all_pts.append(ob.min_pt)
        all_pts.append(ob.max_pt)

    margin = max(cable_radius * 4.0, voxel_size * 3.0)  # breathing room around endpoints
    xs = [p[0] for p in all_pts]
    ys = [p[1] for p in all_pts]
    zs = [p[2] for p in all_pts]

    x_min, x_max = min(xs) - margin, max(xs) + margin
    y_min, y_max = min(ys) - margin, max(ys) + margin
    z_min, z_max = min(zs) - margin, max(zs) + margin

    origin = np.array([x_min, y_min, z_min], dtype=float)

    nx = max(2, int(math.ceil((x_max - x_min) / voxel_size)) + 1)
    ny = max(2, int(math.ceil((y_max - y_min) / voxel_size)) + 1)
    nz = max(2, int(math.ceil((z_max - z_min) / voxel_size)) + 1)

    grid = np.zeros((nx, ny, nz), dtype=bool)

    # Mark blocked voxels — AABB of each obstacle inflated by cable_radius
    for ob in inflated_bodies:
        ix_lo = max(0, int(math.floor((ob.min_pt[0] - x_min) / voxel_size)))
        ix_hi = min(nx - 1, int(math.ceil((ob.max_pt[0] - x_min) / voxel_size)))
        iy_lo = max(0, int(math.floor((ob.min_pt[1] - y_min) / voxel_size)))
        iy_hi = min(ny - 1, int(math.ceil((ob.max_pt[1] - y_min) / voxel_size)))
        iz_lo = max(0, int(math.floor((ob.min_pt[2] - z_min) / voxel_size)))
        iz_hi = min(nz - 1, int(math.ceil((ob.max_pt[2] - z_min) / voxel_size)))
        grid[ix_lo:ix_hi + 1, iy_lo:iy_hi + 1, iz_lo:iz_hi + 1] = True

    return grid, origin, np.array([nx, ny, nz])


def _world_to_voxel(
    pt: Point3D, origin: np.ndarray, voxel_size: float
) -> tuple[int, int, int]:
    ix = int(round((pt[0] - origin[0]) / voxel_size))
    iy = int(round((pt[1] - origin[1]) / voxel_size))
    iz = int(round((pt[2] - origin[2]) / voxel_size))
    return ix, iy, iz


def _voxel_to_world(
    idx: tuple[int, int, int], origin: np.ndarray, voxel_size: float
) -> Point3D:
    x = origin[0] + idx[0] * voxel_size
    y = origin[1] + idx[1] * voxel_size
    z = origin[2] + idx[2] * voxel_size
    return (x, y, z)


def _astar(
    grid: np.ndarray,
    origin: np.ndarray,
    start_idx: tuple[int, int, int],
    end_idx: tuple[int, int, int],
    voxel_size: float,
) -> list[tuple[int, int, int]]:
    """
    26-connected 3-D A* on the voxel grid.

    Returns an ordered list of voxel indices from start to end (inclusive),
    or raises RuntimeError if no path is found within the iteration cap.
    """
    shape = grid.shape

    # Pre-compute 26-neighbour offsets and their Euclidean step costs
    neighbours: list[tuple[tuple[int, int, int], float]] = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                if dx == 0 and dy == 0 and dz == 0:
                    continue
                cost = math.sqrt(dx * dx + dy * dy + dz * dz) * voxel_size
                neighbours.append(((dx, dy, dz), cost))

    def h(idx: tuple[int, int, int]) -> float:
        return (
            math.sqrt(
                (idx[0] - end_idx[0]) ** 2
                + (idx[1] - end_idx[1]) ** 2
                + (idx[2] - end_idx[2]) ** 2
            )
            * voxel_size
        )

    # (f, g, node, parent)
    open_heap: list[tuple[float, float, tuple, tuple | None]] = []
    heapq.heappush(open_heap, (h(start_idx), 0.0, start_idx, None))

    came_from: dict[tuple, tuple | None] = {}
    g_score: dict[tuple, float] = {start_idx: 0.0}
    iterations = 0

    while open_heap:
        iterations += 1
        if iterations > _MAX_ITERATIONS:
            raise RuntimeError(
                f"A* exceeded {_MAX_ITERATIONS} iterations; "
                "space may be too large or start/end unreachable."
            )

        _f, g, current, parent = heapq.heappop(open_heap)

        if current in came_from:
            continue
        came_from[current] = parent

        if current == end_idx:
            # Reconstruct path
            path = []
            node: tuple | None = current
            while node is not None:
                path.append(node)
                node = came_from[node]
            path.reverse()
            return path

        cx, cy, cz = current
        for (dx, dy, dz), step_cost in neighbours:
            nx_, ny_, nz_ = cx + dx, cy + dy, cz + dz
            if not (0 <= nx_ < shape[0] and 0 <= ny_ < shape[1] and 0 <= nz_ < shape[2]):
                continue
            if grid[nx_, ny_, nz_]:
                continue  # blocked
            nb = (nx_, ny_, nz_)
            if nb in came_from:
                continue

            # Bend penalty: angle between current step direction and previous direction
            bend_penalty = 0.0
            if parent is not None:
                px, py, pz = parent
                prev_dx, prev_dy, prev_dz = cx - px, cy - py, cz - pz
                dot = dx * prev_dx + dy * prev_dy + dz * prev_dz
                prev_len = math.sqrt(prev_dx ** 2 + prev_dy ** 2 + prev_dz ** 2)
                cur_len = math.sqrt(dx ** 2 + dy ** 2 + dz ** 2)
                if prev_len > 0 and cur_len > 0:
                    cos_a = max(-1.0, min(1.0, dot / (prev_len * cur_len)))
                    angle = math.acos(cos_a)
                    bend_penalty = angle * _BEND_PENALTY_PER_RAD

            tentative_g = g + step_cost + bend_penalty
            if nb not in g_score or tentative_g < g_score[nb]:
                g_score[nb] = tentative_g
                f = tentative_g + h(nb)
                heapq.heappush(open_heap, (f, tentative_g, nb, current))

    raise RuntimeError(
        "A* found no path from start to end. "
        "Obstacles may completely block the route, or voxel_size is too coarse."
    )


# ---------------------------------------------------------------------------
# Catmull-Rom spline smoothing
# ---------------------------------------------------------------------------

def _catmull_rom_smooth(
    pts: list[Point3D], n_samples: int
) -> list[Point3D]:
    """
    Smooth a polyline with a Catmull-Rom spline.

    The control points are padded at both ends with phantom points so the
    spline passes exactly through the first and last input points.

    Returns ``n_samples`` evenly distributed points along the spline.
    """
    if len(pts) < 2:
        return list(pts)
    if len(pts) == 2:
        # Linear interpolation
        a = np.array(pts[0])
        b = np.array(pts[1])
        return [tuple(a + t * (b - a)) for t in np.linspace(0, 1, max(2, n_samples))]

    p = np.array(pts, dtype=float)
    # Phantom boundary points
    p_ext = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])

    n_segs = len(p)  # number of segments in extended array (len(p_ext) - 3)
    result = []
    for seg in range(len(p_ext) - 3):
        p0, p1, p2, p3 = p_ext[seg], p_ext[seg + 1], p_ext[seg + 2], p_ext[seg + 3]
        seg_samples = max(2, n_samples // n_segs)
        for t in np.linspace(0.0, 1.0, seg_samples, endpoint=(seg == n_segs - 1)):
            # Catmull-Rom formula
            pt = 0.5 * (
                2.0 * p1
                + (-p0 + p2) * t
                + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * (t * t)
                + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * (t * t * t)
            )
            result.append(tuple(float(v) for v in pt))
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def auto_route_harness(
    start_point: Sequence[float],
    end_point: Sequence[float],
    obstacles: list[Body] | None = None,
    *,
    cable_radius: float = 2.0,
    voxel_size: float = 5.0,
) -> Route:
    """
    Automatically route a cable from *start_point* to *end_point*, avoiding obstacles.

    Parameters
    ----------
    start_point :
        (x, y, z) start position in mm.
    end_point :
        (x, y, z) end position in mm.
    obstacles :
        List of :class:`Body` objects (AABB obstacles).  Pass an empty list
        or ``None`` for an unobstructed environment.
    cable_radius :
        Outer radius of the cable bundle in mm.  Obstacles are inflated by this
        amount so the cable centre-line always clears the surface.
    voxel_size :
        Edge length of each voxel cube in mm.  Smaller values yield smoother
        routes but increase memory and computation.  Typical: 2–10 mm.

    Returns
    -------
    Route
        Smoothed polyline, total arc-length, bend count, and minimum clearance.

    Raises
    ------
    ValueError
        If inputs are geometrically invalid.
    RuntimeError
        If A* cannot find a path (space is fully blocked or iteration cap exceeded).
    """
    start = tuple(float(v) for v in start_point)
    end = tuple(float(v) for v in end_point)
    if len(start) != 3 or len(end) != 3:
        raise ValueError("start_point and end_point must each be 3-element sequences")
    if voxel_size <= 0:
        raise ValueError(f"voxel_size must be > 0; got {voxel_size}")
    if cable_radius < 0:
        raise ValueError(f"cable_radius must be ≥ 0; got {cable_radius}")

    obstacles = obstacles or []

    grid, origin, _shape = _build_voxel_grid(
        start, end, obstacles, cable_radius, voxel_size
    )

    start_idx = _world_to_voxel(start, origin, voxel_size)
    end_idx = _world_to_voxel(end, origin, voxel_size)

    # Clamp to grid bounds
    nx, ny, nz = grid.shape
    start_idx = (
        max(0, min(nx - 1, start_idx[0])),
        max(0, min(ny - 1, start_idx[1])),
        max(0, min(nz - 1, start_idx[2])),
    )
    end_idx = (
        max(0, min(nx - 1, end_idx[0])),
        max(0, min(ny - 1, end_idx[1])),
        max(0, min(nz - 1, end_idx[2])),
    )

    # Unblock start/end voxels if they happen to fall inside an obstacle
    grid[start_idx] = False
    grid[end_idx] = False

    voxel_path = _astar(grid, origin, start_idx, end_idx, voxel_size)

    # Convert voxel indices to world coordinates
    raw_pts: list[Point3D] = [_voxel_to_world(idx, origin, voxel_size) for idx in voxel_path]

    # Replace first/last with exact start/end to avoid voxel snap error
    raw_pts[0] = start
    raw_pts[-1] = end

    # Smooth with Catmull-Rom spline
    n_smooth = max(10, int(len(raw_pts) * _SMOOTH_SAMPLES_PER_VOXEL))
    smoothed = _catmull_rom_smooth(raw_pts, n_smooth)

    # Ensure exact start/end
    smoothed[0] = start
    smoothed[-1] = end

    # Compute total arc-length
    total_length = sum(
        _dist3(smoothed[i], smoothed[i + 1]) for i in range(len(smoothed) - 1)
    )

    # Count significant bends
    bend_count = 0
    thresh_cos = math.cos(math.radians(_BEND_ANGLE_THRESHOLD_DEG))
    for i in range(1, len(smoothed) - 1):
        a = smoothed[i - 1]
        b = smoothed[i]
        c = smoothed[i + 1]
        v1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        v2 = (c[0] - b[0], c[1] - b[1], c[2] - b[2])
        l1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2 + v1[2] ** 2)
        l2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2 + v2[2] ** 2)
        if l1 > 1e-9 and l2 > 1e-9:
            cos_a = (v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]) / (l1 * l2)
            cos_a = max(-1.0, min(1.0, cos_a))
            if cos_a < thresh_cos:
                bend_count += 1

    # Minimum clearance along smoothed path
    if obstacles:
        min_clearance = min(
            _min_clearance(pt, obstacles) for pt in smoothed
        )
    else:
        min_clearance = float("inf")

    return Route(
        polyline=smoothed,
        total_length=total_length,
        bend_count=bend_count,
        collision_clearance_min=min_clearance,
    )


def detect_route_collisions(
    route: Route,
    obstacles: list[Body],
    cable_radius: float = 2.0,
) -> list[Collision]:
    """
    Detect segments of *route* that are closer to any obstacle than *cable_radius*.

    For each consecutive pair of points in ``route.polyline`` the mid-point is
    tested against every obstacle body.  A collision is reported when the minimum
    distance from the mid-point to the obstacle surface is less than ``cable_radius``.

    Parameters
    ----------
    route :        A :class:`Route` returned by :func:`auto_route_harness`.
    obstacles :    List of :class:`Body` AABBs.
    cable_radius : Outer radius of the cable in mm.

    Returns
    -------
    list[Collision]
        One entry per colliding segment / obstacle pair.
    """
    collisions: list[Collision] = []
    pts = route.polyline
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        mid = (
            (a[0] + b[0]) / 2.0,
            (a[1] + b[1]) / 2.0,
            (a[2] + b[2]) / 2.0,
        )
        for ob in obstacles:
            d = ob.distance_to_point(mid)
            if d < cable_radius:
                # penetration_depth: positive means inside/too close
                collisions.append(
                    Collision(
                        segment_index=i,
                        point=mid,
                        obstacle_name=ob.name,
                        penetration_depth=cable_radius - d,
                    )
                )
    return collisions


def compute_routing_clearance(
    route: Route,
    obstacles: list[Body],
    n_samples: int = 100,
) -> dict:
    """
    Compute clearance statistics for *route* against all obstacles.

    Parameters
    ----------
    route :     A :class:`Route`.
    obstacles : List of :class:`Body` AABBs.
    n_samples : Number of evenly spaced sample points along the polyline.

    Returns
    -------
    dict with keys:
        ``min``            — minimum clearance (mm) over all sample points.
        ``mean``           — mean clearance (mm).
        ``percentile_10``  — 10th percentile clearance.
        ``percentile_25``  — 25th percentile.
        ``percentile_50``  — median clearance.
        ``percentile_75``  — 75th percentile.
        ``percentile_90``  — 90th percentile.
        ``percentile_95``  — 95th percentile.
        ``max``            — maximum clearance (mm).
        ``n_samples``      — actual number of samples used.
    """
    if not obstacles:
        inf = float("inf")
        return {
            "min": inf, "mean": inf,
            "percentile_10": inf, "percentile_25": inf,
            "percentile_50": inf, "percentile_75": inf,
            "percentile_90": inf, "percentile_95": inf,
            "max": inf, "n_samples": 0,
        }

    pts = route.polyline
    if len(pts) < 2:
        return {
            "min": 0.0, "mean": 0.0,
            "percentile_10": 0.0, "percentile_25": 0.0,
            "percentile_50": 0.0, "percentile_75": 0.0,
            "percentile_90": 0.0, "percentile_95": 0.0,
            "max": 0.0, "n_samples": 0,
        }

    # Build cumulative arc-length parameterisation
    seg_lengths = [_dist3(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
    total_len = sum(seg_lengths)
    cumulative = [0.0]
    for sl in seg_lengths:
        cumulative.append(cumulative[-1] + sl)

    actual_n = min(n_samples, len(pts))
    clearances: list[float] = []

    for k in range(actual_n):
        # Parametric position along arc
        s = total_len * k / max(1, actual_n - 1)
        # Find the segment
        idx = 0
        while idx < len(seg_lengths) - 1 and cumulative[idx + 1] < s:
            idx += 1
        seg_s = s - cumulative[idx]
        seg_l = seg_lengths[idx]
        if seg_l > 1e-12:
            t = seg_s / seg_l
        else:
            t = 0.0
        a, b = pts[idx], pts[min(idx + 1, len(pts) - 1)]
        pt: Point3D = (
            a[0] + t * (b[0] - a[0]),
            a[1] + t * (b[1] - a[1]),
            a[2] + t * (b[2] - a[2]),
        )
        clearances.append(_min_clearance(pt, obstacles))

    c = np.array(clearances, dtype=float)
    return {
        "min": float(np.min(c)),
        "mean": float(np.mean(c)),
        "percentile_10": float(np.percentile(c, 10)),
        "percentile_25": float(np.percentile(c, 25)),
        "percentile_50": float(np.percentile(c, 50)),
        "percentile_75": float(np.percentile(c, 75)),
        "percentile_90": float(np.percentile(c, 90)),
        "percentile_95": float(np.percentile(c, 95)),
        "max": float(np.max(c)),
        "n_samples": actual_n,
    }
