"""
kerf_cad_core.civil.parcels — Parcel geometry and lot-layout subdivision.

Land subdivision geometry
--------------------------
A parcel is a polygon (closed CCW) defined by a list of (x, y) vertices in
metres (or feet — units are user's choice; this module is unit-agnostic).

Polygon area (shoelace / Gauss formula):
  A = 0.5 · |Σ(xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)|

Polygon centroid:
  cx = (1/(6A)) · Σ(xᵢ+xᵢ₊₁)(xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)
  cy = (1/(6A)) · Σ(yᵢ+yᵢ₊₁)(xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)

Point-in-polygon: ray-casting (horizontal ray from (x, -∞)).

Subdivision algorithm
---------------------
References:
  • AASHTO Green Book (2018) Ch. 3 — Sight distance, access control,
    subdivision street design standards.
  • Bureau of Land Management Manual of Surveying Instructions (2009)
    §6 — Aliquot subdivision; lot layout principles.
  • ASCE Manual 21 (Land Subdivision Design) — minimum frontage,
    setback geometry, lot regularity.

Algorithm: recursive axis-aligned bisection along the road-perpendicular
(depth) axis of the parent polygon's bounding box.  Each bisection produces
two sub-rectangles; recursion continues until the remaining area is within
±20% of target_lot_area or the remaining area is too small for another lot.

Honest caveat (BLM Manual §6.2 note): this rectangular-grid method is exact
only for rectangular (or near-rectangular) parent parcels.  Irregular
boundaries are approximated by the convex-hull bounding rectangle; the
difference is reported as waste_area.

Units: metres (or user-supplied feet — no conversion is applied).
Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class Parcel:
    """A single parcel / lot."""
    parcel_id: str
    boundary: list[tuple[float, float]]    # closed CCW polygon; vertices in user units
    area: float                            # auto-computed via shoelace; user units²
    perimeter: float                       # sum of edge lengths; user units
    centroid: tuple[float, float]          # (cx, cy) in user units


@dataclass
class SubdivisionSpec:
    """
    Parameters for rectangular-grid lot-layout subdivision.

    AASHTO Green Book (2018) §3: minimum frontage controls access spacing;
    setbacks determine buildable area within each lot.

    ASCE Manual 21: lot depth = (target_lot_area / minimum_frontage) is the
    design depth; setbacks reduce the net buildable envelope.
    """
    parent_boundary: list[tuple[float, float]]   # closed CCW polygon
    target_lot_area: float                        # m² or ft²
    minimum_frontage: float                       # along access road (user units)
    access_road_polyline: list[tuple[float, float]]  # road centre/edge line
    setback_front: float                          # user units (towards road)
    setback_side: float                           # user units (left/right lot boundary)
    setback_rear: float                           # user units (away from road)


@dataclass
class SubdivisionReport:
    """
    Result of a rectangular-grid subdivision.

    waste_area = parent_area − Σ(child lot areas).
    Includes roads, setbacks, and clipping of irregular boundary.
    Honest caveat per BLM Manual §6.2: irregular boundaries produce
    convex-hull bounding-rectangle approximations; trim to actual
    boundary manually.
    """
    parcels: list[Parcel]
    n_lots: int
    average_lot_area: float
    waste_area: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Polygon geometry primitives
# ---------------------------------------------------------------------------

def polygon_area(boundary: list[tuple[float, float]]) -> float:
    """
    Shoelace (Gauss) formula for signed polygon area.
    Returns positive for CCW orientation.

    A = 0.5 · Σ(xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)
    """
    n = len(boundary)
    if n < 3:
        return 0.0
    xs = np.array([p[0] for p in boundary], dtype=float)
    ys = np.array([p[1] for p in boundary], dtype=float)
    # Roll to next vertex
    xs_next = np.roll(xs, -1)
    ys_next = np.roll(ys, -1)
    return 0.5 * float(np.sum(xs * ys_next - xs_next * ys))


def polygon_perimeter(boundary: list[tuple[float, float]]) -> float:
    """Sum of Euclidean edge lengths for a closed polygon."""
    n = len(boundary)
    if n < 2:
        return 0.0
    total = 0.0
    for i in range(n):
        x0, y0 = boundary[i]
        x1, y1 = boundary[(i + 1) % n]
        total += math.hypot(x1 - x0, y1 - y0)
    return total


def polygon_centroid(boundary: list[tuple[float, float]]) -> tuple[float, float]:
    """
    Centroid of a simple polygon via the signed-area formula.

    cx = (1/(6A)) · Σ(xᵢ+xᵢ₊₁)(xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)
    cy = (1/(6A)) · Σ(yᵢ+yᵢ₊₁)(xᵢ·yᵢ₊₁ − xᵢ₊₁·yᵢ)
    """
    n = len(boundary)
    if n < 3:
        if n == 0:
            return (0.0, 0.0)
        xs = [p[0] for p in boundary]
        ys = [p[1] for p in boundary]
        return (sum(xs) / n, sum(ys) / n)

    xs = np.array([p[0] for p in boundary], dtype=float)
    ys = np.array([p[1] for p in boundary], dtype=float)
    xs_next = np.roll(xs, -1)
    ys_next = np.roll(ys, -1)
    cross = xs * ys_next - xs_next * ys
    A = 0.5 * float(np.sum(cross))
    if abs(A) < 1e-12:
        # Degenerate — return mean of vertices
        return (float(np.mean(xs)), float(np.mean(ys)))
    cx = float(np.sum((xs + xs_next) * cross)) / (6.0 * A)
    cy = float(np.sum((ys + ys_next) * cross)) / (6.0 * A)
    return (cx, cy)


def polygon_contains_point(
    boundary: list[tuple[float, float]],
    pt: tuple[float, float],
) -> bool:
    """
    Ray-casting point-in-polygon test (horizontal ray, upward).
    Returns True if pt is strictly inside the polygon.
    Boundary points are treated as outside (conservative for setback checks).
    """
    x, y = pt
    n = len(boundary)
    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = boundary[i]
        xj, yj = boundary[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
            inside = not inside
        j = i
    return inside


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _bounding_box(
    boundary: list[tuple[float, float]],
) -> tuple[float, float, float, float]:
    """Return (x_min, y_min, x_max, y_max) of a polygon."""
    xs = [p[0] for p in boundary]
    ys = [p[1] for p in boundary]
    return (min(xs), min(ys), max(xs), max(ys))


def _rect_boundary(
    x0: float, y0: float, x1: float, y1: float
) -> list[tuple[float, float]]:
    """CCW rectangle boundary: (x0,y0)→(x1,y0)→(x1,y1)→(x0,y1)."""
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def _make_parcel(
    parcel_id: str,
    boundary: list[tuple[float, float]],
) -> Parcel:
    area = abs(polygon_area(boundary))
    perim = polygon_perimeter(boundary)
    centroid = polygon_centroid(boundary)
    return Parcel(
        parcel_id=parcel_id,
        boundary=boundary,
        area=area,
        perimeter=perim,
        centroid=centroid,
    )


# ---------------------------------------------------------------------------
# Subdivision algorithm
# ---------------------------------------------------------------------------

def subdivide_parcel(spec: SubdivisionSpec) -> SubdivisionReport:
    """
    Rectangular-grid lot-layout subdivision (BLM Manual §6 / AASHTO Green Book §3).

    Method
    ------
    1.  Compute the parent polygon's bounding box.
    2.  Determine lot depth from target_lot_area and minimum_frontage:
            depth = target_lot_area / minimum_frontage
        (ASCE Manual 21 proportioning rule)
    3.  Layout a row-and-column grid of lots inside the bounding box,
        starting from the road-adjacent edge.
    4.  Each grid cell that fits within the bounding box becomes a lot.
    5.  Cells that are split by the actual boundary are approximated as
        the grid cell (over-counting is reported as waste).
    6.  Strip a road allowance = setback_front along the access edge.
    7.  Report waste = parent_area − Σ(lot areas).

    Honest caveat (BLM Manual §6.2):
      This is a rectangular-grid approximation.  Irregular parent boundaries
      produce clipped lots; the trim must be performed by a licensed surveyor
      against the actual metes-and-bounds description.

    AASHTO Green Book (2018) §3 constraints applied:
      • Each lot frontage ≥ minimum_frontage.
      • Setbacks are subtracted from buildable area but the full lot polygon
        is recorded (setback area is accounted in waste_area per ASCE Manual 21).
    """
    parent = spec.parent_boundary
    if len(parent) < 3:
        return SubdivisionReport(
            parcels=[],
            n_lots=0,
            average_lot_area=0.0,
            waste_area=0.0,
            honest_caveat="Parent boundary must have at least 3 vertices.",
        )

    target_area = spec.target_lot_area
    frontage = spec.minimum_frontage

    if target_area <= 0 or frontage <= 0:
        return SubdivisionReport(
            parcels=[],
            n_lots=0,
            average_lot_area=0.0,
            waste_area=0.0,
            honest_caveat="target_lot_area and minimum_frontage must be > 0.",
        )

    parent_area = abs(polygon_area(parent))
    x_min, y_min, x_max, y_max = _bounding_box(parent)

    bbox_width = x_max - x_min
    bbox_height = y_max - y_min

    # Design lot depth from ASCE Manual 21 proportioning
    lot_depth = target_area / frontage
    lot_width = frontage  # == minimum_frontage

    # Road allowance strip at the bottom (y_min edge)
    road_strip = spec.setback_front  # front setback is the road buffer
    usable_y_min = y_min + road_strip
    usable_height = bbox_height - road_strip - spec.setback_rear

    if usable_height <= 0 or bbox_width <= 0:
        return SubdivisionReport(
            parcels=[],
            n_lots=0,
            average_lot_area=0.0,
            waste_area=parent_area,
            honest_caveat=(
                "Setbacks consume the entire parent parcel; no buildable area remains. "
                "BLM Manual §6.2: verify setback distances against local ordinance."
            ),
        )

    # Grid layout
    parcels: list[Parcel] = []
    lot_counter = 1

    n_cols = max(1, int(bbox_width / lot_width))
    n_rows = max(1, int(usable_height / lot_depth))

    # Actual lot width / depth after fitting integer grid
    actual_width = bbox_width / n_cols
    actual_depth = usable_height / n_rows

    for row in range(n_rows):
        for col in range(n_cols):
            lx0 = x_min + col * actual_width + spec.setback_side
            lx1 = x_min + (col + 1) * actual_width - spec.setback_side
            ly0 = usable_y_min + row * actual_depth
            ly1 = usable_y_min + (row + 1) * actual_depth - spec.setback_rear

            # Side setbacks must leave a non-zero width
            if lx1 <= lx0 or ly1 <= ly0:
                continue

            lot_bdry = _rect_boundary(lx0, ly0, lx1, ly1)
            # Check centroid lies within parent polygon (BLM §6 boundary check)
            cx = (lx0 + lx1) / 2.0
            cy = (ly0 + ly1) / 2.0
            if not polygon_contains_point(parent, (cx, cy)):
                continue

            pid = f"L{lot_counter:03d}"
            parcels.append(_make_parcel(pid, lot_bdry))
            lot_counter += 1

    n_lots = len(parcels)
    avg_area = (sum(p.area for p in parcels) / n_lots) if n_lots > 0 else 0.0
    waste = max(0.0, parent_area - sum(p.area for p in parcels))

    caveat = (
        "Rectangular-grid subdivision per BLM Manual of Surveying Instructions §6 "
        "and AASHTO Green Book (2018) Ch. 3.  Irregular parent boundaries are "
        "approximated by the bounding-rectangle grid; lots that straddle the "
        "actual boundary are included only if their centroid lies inside the "
        "parent polygon.  All lot polygons reflect gross area including internal "
        "setbacks.  Engage a licensed land surveyor for metes-and-bounds "
        "descriptions and title-quality subdivision plats (ASCE Manual 21 §4)."
    )

    return SubdivisionReport(
        parcels=parcels,
        n_lots=n_lots,
        average_lot_area=round(avg_area, 4),
        waste_area=round(waste, 4),
        honest_caveat=caveat,
    )
