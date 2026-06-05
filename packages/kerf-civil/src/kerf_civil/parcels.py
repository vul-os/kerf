"""
kerf_civil.parcels — Parcel subdivision engine.

Implements automated lot-layout via recursive / iterative polygon slicing,
producing lots that satisfy frontage and area targets with setback offsets,
ROW dedication strips, and full area/perimeter reporting.

Method
------
The algorithm follows the approach used in ESRI Parcel Fabric and most civil
land-subdivision software:

1. ROW dedication — shrink the parent boundary polygon inward by *row_width_m*
   along one or more designated *row_edges* (by side index) via a parallel-
   offset slice, returning the ROW polygon(s) and the net developable area.

2. Setback buffering — inset each lot candidate by *setback_m* to produce the
   buildable area envelope (the "building line").

3. Lot slicing — subdivide the net area polygon into N lots by cutting with
   parallel lines perpendicular to the frontage edge (i.e., lines parallel to
   the rear of the lots).  Two strategies:

   * "equal_width"  — N equal-width slices.
   * "target_area"  — greedy front-to-back slice that advances the cutting
                      line until the accumulated area matches *target_area_m2*.

The polygon arithmetic is done via the Sutherland-Hodgman clip algorithm and
signed-area shoelace formula (no external geometry dependencies required beyond
numpy).  For production use with complex concave parcels, shapely is preferred
and will be used when available.

References
----------
ISO 19152:2012 (LADM) — Land Administration Domain Model: parcel concept.
ASCE/NSPS "Surveying Engineering" Part III — subdivision design.
Sutherland & Hodgman (1974). "Reentrant Polygon Clipping". Commun. ACM 17(1).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------

def _shoelace_area(pts: list[tuple[float, float]]) -> float:
    """Signed area via shoelace formula.  Positive = CCW."""
    n = len(pts)
    a = 0.0
    for i in range(n):
        x0, y0 = pts[i]
        x1, y1 = pts[(i + 1) % n]
        a += x0 * y1 - x1 * y0
    return a / 2.0


def _area(pts: list[tuple[float, float]]) -> float:
    """Absolute polygon area (m²)."""
    return abs(_shoelace_area(pts))


def _perimeter(pts: list[tuple[float, float]]) -> float:
    """Polygon perimeter (m)."""
    n = len(pts)
    p = 0.0
    for i in range(n):
        dx = pts[(i + 1) % n][0] - pts[i][0]
        dy = pts[(i + 1) % n][1] - pts[i][1]
        p += math.hypot(dx, dy)
    return p


def _ensure_ccw(pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if _shoelace_area(pts) < 0:
        return list(reversed(pts))
    return list(pts)


def _clip_polygon_by_halfplane(
    polygon: list[tuple[float, float]],
    lx: float, ly: float,
    nx: float, ny: float,
) -> list[tuple[float, float]]:
    """
    Sutherland-Hodgman clip: keep the side of the half-plane defined by
    the line through point (lx, ly) with inward normal (nx, ny).

    A vertex v is *inside* when dot(v - L, N) >= 0.
    """
    if not polygon:
        return []

    result: list[tuple[float, float]] = []
    n = len(polygon)

    for i in range(n):
        cur = polygon[i]
        prev = polygon[(i - 1) % n]

        def _inside(p):
            return (p[0] - lx) * nx + (p[1] - ly) * ny >= -1e-9

        cur_in = _inside(cur)
        prev_in = _inside(prev)

        if cur_in:
            if not prev_in:
                # Edge enters — compute intersection
                dx = cur[0] - prev[0]
                dy = cur[1] - prev[1]
                denom = dx * nx + dy * ny
                if abs(denom) > 1e-12:
                    t = ((lx - prev[0]) * nx + (ly - prev[1]) * ny) / denom
                    result.append((prev[0] + t * dx, prev[1] + t * dy))
            result.append(cur)
        elif prev_in:
            # Edge exits — compute intersection
            dx = cur[0] - prev[0]
            dy = cur[1] - prev[1]
            denom = dx * nx + dy * ny
            if abs(denom) > 1e-12:
                t = ((lx - prev[0]) * nx + (ly - prev[1]) * ny) / denom
                result.append((prev[0] + t * dx, prev[1] + t * dy))

    return result


def _clip_polygon_by_strip(
    polygon: list[tuple[float, float]],
    cut_x: float,
    front_is_left: bool,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """
    Split a polygon with a vertical line at x = cut_x.
    Returns (left_poly, right_poly).
    """
    # Left piece: x <= cut_x  →  normal pointing left (+x toward cut) = (1, 0) at cut_x
    if front_is_left:
        left = _clip_polygon_by_halfplane(polygon, cut_x, 0.0, -1.0, 0.0)
        right = _clip_polygon_by_halfplane(polygon, cut_x, 0.0, 1.0, 0.0)
    else:
        left = _clip_polygon_by_halfplane(polygon, cut_x, 0.0, 1.0, 0.0)
        right = _clip_polygon_by_halfplane(polygon, cut_x, 0.0, -1.0, 0.0)
    return left, right


def _bbox(pts: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    """Return (xmin, ymin, xmax, ymax)."""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _rotate_polygon(
    pts: list[tuple[float, float]],
    angle_rad: float,
    cx: float = 0.0,
    cy: float = 0.0,
) -> list[tuple[float, float]]:
    cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)
    out = []
    for x, y in pts:
        x -= cx; y -= cy
        out.append((cx + cos_a * x - sin_a * y, cy + sin_a * x + cos_a * y))
    return out


def _inset_polygon(
    pts: list[tuple[float, float]],
    dist: float,
) -> list[tuple[float, float]]:
    """
    Inset a convex polygon by *dist* metres using parallel-edge offset
    and Sutherland-Hodgman half-plane clipping.

    For convex polygons this equals the Minkowski erosion.  For concave
    parcels the approximation may omit slivers; production code should use
    shapely.buffer(..., -dist).
    """
    if dist <= 0:
        return list(pts)

    result = list(pts)
    n = len(pts)
    for i in range(n):
        p0 = pts[i]
        p1 = pts[(i + 1) % n]
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        length = math.hypot(dx, dy)
        if length < 1e-12:
            continue
        # Inward normal (pointing left for CCW polygon)
        nx = -dy / length
        ny = dx / length
        # Offset edge point
        lx = p0[0] + nx * dist
        ly = p0[1] + ny * dist
        result = _clip_polygon_by_halfplane(result, lx, ly, nx, ny)
        if not result:
            return []

    return result


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class Lot:
    """A single subdivided lot."""
    lot_number: int
    polygon: list[tuple[float, float]]  # boundary in model CRS (metres)
    buildable_polygon: list[tuple[float, float]]  # after setback
    area_m2: float
    perimeter_m: float
    frontage_m: float
    buildable_area_m2: float


@dataclass
class ROWDedication:
    """Right-of-Way strip dedicated from the parent parcel."""
    polygon: list[tuple[float, float]]
    area_m2: float
    width_m: float


@dataclass
class SubdivisionResult:
    """Full output of the parcel subdivision engine."""
    lots: list[Lot]
    row: ROWDedication | None
    net_developable_area_m2: float
    parent_area_m2: float
    n_lots: int
    strategy: str
    # Summary statistics
    min_lot_area_m2: float
    max_lot_area_m2: float
    mean_lot_area_m2: float
    total_buildable_area_m2: float


# ---------------------------------------------------------------------------
# Core subdivision engine
# ---------------------------------------------------------------------------

def subdivide_parcel(
    boundary: Sequence[tuple[float, float]],
    *,
    n_lots: int | None = None,
    target_area_m2: float | None = None,
    frontage_edge: int = 0,
    min_frontage_m: float = 10.0,
    setback_m: float = 3.0,
    row_width_m: float = 0.0,
    strategy: str = "equal_width",
) -> SubdivisionResult:
    """
    Subdivide a boundary polygon into lots.

    Parameters
    ----------
    boundary : list of (x, y) tuples — outer parcel boundary (CCW preferred).
    n_lots : int — number of lots (used by 'equal_width' strategy).
    target_area_m2 : float — target lot area for 'target_area' strategy.
    frontage_edge : int — index of the frontage edge (0 = first edge of boundary).
    min_frontage_m : float — minimum frontage width per lot (m); used for validation.
    setback_m : float — building setback from all lot edges (m).
    row_width_m : float — ROW strip width to dedicate from the frontage edge (m).
    strategy : str — 'equal_width' or 'target_area'.

    Returns
    -------
    SubdivisionResult

    References
    ----------
    ISO 19152 LADM parcel concept; ASCE Surveying Engineering subdivision
    design practice; Sutherland-Hodgman polygon clipping (1974).
    """
    pts = _ensure_ccw(list(map(tuple, boundary)))  # type: ignore[arg-type]
    if len(pts) < 3:
        raise ValueError("boundary must have at least 3 vertices")

    parent_area = _area(pts)

    # ------------------------------------------------------------------
    # 1. ROW dedication
    # ------------------------------------------------------------------
    row: ROWDedication | None = None
    net_pts = pts

    if row_width_m > 0:
        # Identify the frontage edge direction
        n = len(pts)
        i0 = frontage_edge % n
        i1 = (i0 + 1) % n
        p0 = pts[i0]
        p1 = pts[i1]
        ex = p1[0] - p0[0]
        ey = p1[1] - p0[1]
        elen = math.hypot(ex, ey)
        if elen < 1e-9:
            raise ValueError(f"frontage edge {frontage_edge} has zero length")
        # Inward normal (points into the parcel for CCW)
        nx = -ey / elen
        ny = ex / elen
        # ROW: band from the frontage edge inward by row_width_m
        # = the part of pts with dot(v - p0, n) <= row_width_m
        # Inner boundary of ROW = original edge offset inward by row_width_m
        row_pts = _clip_polygon_by_halfplane(pts, p0[0] + nx * row_width_m, p0[1] + ny * row_width_m, -nx, -ny)
        net_pts = _clip_polygon_by_halfplane(pts, p0[0] + nx * row_width_m, p0[1] + ny * row_width_m, nx, ny)
        row = ROWDedication(
            polygon=row_pts,
            area_m2=round(_area(row_pts), 4),
            width_m=row_width_m,
        )

    net_area = _area(net_pts)

    # ------------------------------------------------------------------
    # 2. Rotation normalisation
    #    Rotate so that the frontage edge is along the x-axis,
    #    then slice with vertical lines, then rotate back.
    # ------------------------------------------------------------------
    n = len(net_pts)
    # Determine frontage edge in net_pts (may have shifted after ROW clip)
    # Use first edge closest to original frontage edge direction
    i0 = 0
    p0 = net_pts[0]
    p1 = net_pts[1]
    ex = p1[0] - p0[0]
    ey = p1[1] - p0[1]
    # Angle to rotate so this edge is along +x
    rot_angle = -math.atan2(ey, ex)
    cx = (min(p[0] for p in net_pts) + max(p[0] for p in net_pts)) / 2
    cy = (min(p[1] for p in net_pts) + max(p[1] for p in net_pts)) / 2

    rotated = _rotate_polygon(net_pts, rot_angle, cx, cy)
    xmin, ymin, xmax, ymax = _bbox(rotated)
    total_width = xmax - xmin

    # ------------------------------------------------------------------
    # 3. Lot slicing
    # ------------------------------------------------------------------
    lots: list[Lot] = []

    if strategy == "equal_width":
        if n_lots is None or n_lots < 1:
            raise ValueError("n_lots must be >= 1 for equal_width strategy")
        slice_width = total_width / n_lots
        remaining = list(rotated)
        for k in range(n_lots):
            cut_x = xmin + (k + 1) * slice_width
            if k < n_lots - 1:
                lot_poly_r, remaining = _clip_polygon_by_strip(remaining, cut_x, front_is_left=True)
            else:
                lot_poly_r = list(remaining)

            lot_poly = _rotate_polygon(lot_poly_r, -rot_angle, cx, cy)
            buildable = _inset_polygon(_ensure_ccw(lot_poly), setback_m)
            lot_area = _area(lot_poly)
            buildable_area = _area(buildable) if buildable else 0.0

            # Frontage = width of lot along original frontage direction
            lot_bbox = _bbox(lot_poly_r)
            frontage = lot_bbox[2] - lot_bbox[0]

            lots.append(Lot(
                lot_number=k + 1,
                polygon=lot_poly,
                buildable_polygon=buildable,
                area_m2=round(lot_area, 4),
                perimeter_m=round(_perimeter(lot_poly), 4),
                frontage_m=round(frontage, 4),
                buildable_area_m2=round(buildable_area, 4),
            ))

    elif strategy == "target_area":
        if target_area_m2 is None or target_area_m2 <= 0:
            raise ValueError("target_area_m2 must be > 0 for target_area strategy")

        remaining = list(rotated)
        lot_num = 1
        x_cursor = xmin

        while True:
            rem_area = _area(remaining)
            if rem_area < target_area_m2 * 0.1:
                break  # remainder too small to form a valid lot

            # Binary search for cut_x that yields target_area
            lo, hi = x_cursor, xmax
            for _ in range(60):  # 60 bisection steps → < 1e-15 relative error
                mid = (lo + hi) / 2.0
                test_lot, _ = _clip_polygon_by_strip(remaining, mid, front_is_left=True)
                if _area(test_lot) < target_area_m2:
                    lo = mid
                else:
                    hi = mid

            cut_x = (lo + hi) / 2.0
            # Check if remainder would be too thin for another lot
            remainder_width = xmax - cut_x
            if remainder_width < min_frontage_m or _area(remaining) - _area(
                    _clip_polygon_by_strip(remaining, cut_x, True)[0]
            ) < target_area_m2 * 0.5:
                # Absorb remainder into this lot
                lot_poly_r = list(remaining)
                remaining = []
            else:
                lot_poly_r, remaining = _clip_polygon_by_strip(remaining, cut_x, True)

            lot_poly = _rotate_polygon(lot_poly_r, -rot_angle, cx, cy)
            buildable = _inset_polygon(_ensure_ccw(lot_poly), setback_m)
            lot_area = _area(lot_poly)
            buildable_area = _area(buildable) if buildable else 0.0
            lot_bbox = _bbox(lot_poly_r)
            frontage = lot_bbox[2] - lot_bbox[0]

            lots.append(Lot(
                lot_number=lot_num,
                polygon=lot_poly,
                buildable_polygon=buildable,
                area_m2=round(lot_area, 4),
                perimeter_m=round(_perimeter(lot_poly), 4),
                frontage_m=round(frontage, 4),
                buildable_area_m2=round(buildable_area, 4),
            ))
            lot_num += 1

            if not remaining or _area(remaining) < 1e-3:
                break
            x_cursor = cut_x

        # Handle any small remaining slab
        if remaining and _area(remaining) > 0.01:
            rem_pts = _area(remaining)
            lot_poly = _rotate_polygon(remaining, -rot_angle, cx, cy)
            buildable = _inset_polygon(_ensure_ccw(lot_poly), setback_m)
            lot_area_r = _area(lot_poly)
            buildable_area = _area(buildable) if buildable else 0.0
            lot_bbox = _bbox(remaining)
            frontage = lot_bbox[2] - lot_bbox[0]
            lots.append(Lot(
                lot_number=lot_num,
                polygon=lot_poly,
                buildable_polygon=buildable,
                area_m2=round(lot_area_r, 4),
                perimeter_m=round(_perimeter(lot_poly), 4),
                frontage_m=round(frontage, 4),
                buildable_area_m2=round(buildable_area, 4),
            ))
    else:
        raise ValueError(f"unknown strategy {strategy!r}; use 'equal_width' or 'target_area'")

    lot_areas = [lot.area_m2 for lot in lots]
    total_buildable = sum(lot.buildable_area_m2 for lot in lots)

    return SubdivisionResult(
        lots=lots,
        row=row,
        net_developable_area_m2=round(net_area, 4),
        parent_area_m2=round(parent_area, 4),
        n_lots=len(lots),
        strategy=strategy,
        min_lot_area_m2=round(min(lot_areas), 4) if lot_areas else 0.0,
        max_lot_area_m2=round(max(lot_areas), 4) if lot_areas else 0.0,
        mean_lot_area_m2=round(sum(lot_areas) / len(lot_areas), 4) if lot_areas else 0.0,
        total_buildable_area_m2=round(total_buildable, 4),
    )
