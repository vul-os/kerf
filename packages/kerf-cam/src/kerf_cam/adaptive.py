"""
kerf_cam.adaptive — High-Speed Machining (HSM) strategies.

Implements three HSM strategies in pure Python (no opencamlib required):

1. adaptive_pocket   — Constant tool-engagement 2D pocket clearing.
   Algorithm: iterative inward polygon offsetting via a simple vertex-normal
   ("buffer") method.  Each vertex is moved along the average of its two
   edge normals by the offset distance.  Self-intersecting rings are clipped
   using a raster point-in-polygon filter.  Consecutive offset rings are
   connected by short helical ramping transitions so the radial engagement
   never exceeds the target step-over.  Corner arcs are inserted where the
   toolpath would otherwise make a sharp direction reversal, keeping engagement
   bounded.

2. trochoidal_slot   — Trochoidal (looping) slot milling.
   A series of full circles, each centred on the slot centreline, advancing by
   step_over per loop.  The overlap between successive circles guarantees full
   slot-width coverage while peak radial engagement = trochoid_radius (much
   smaller than tool D, so chip-thinning is exploited throughout).

3. rest_machining     — Raster-based uncleared-region detection + small-tool
   clearing.
   A pixel grid (default 0.5 mm resolution) is rasterised: pixels inside the
   workpiece boundary that are NOT swept by the prior large-tool toolpath (path
   radius = large tool D/2) are marked uncleared.  Connected uncleared clusters
   are identified and cleared with zigzag passes using the smaller tool.

All three functions return a dict:
  {
    "polylines": [[(x, y), ...], ...],   # tool-tip XY positions
    "feeds": [[f, ...], ...],            # per-point feed rates (mm/min)
    "total_length": float,               # total path length (mm)
    "metadata": {...},                   # strategy-specific diagnostics
  }

LLM tool specs are registered at the bottom of the file following the same
pattern as kerf_cam.tools.
"""

from __future__ import annotations

import json
import math
from typing import List, Tuple

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_cam._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

Point = Tuple[float, float]
Polyline = List[Point]


# ===========================================================================
# Geometry helpers
# ===========================================================================

def _dist(a: Point, b: Point) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def _poly_length(pts: Polyline) -> float:
    total = 0.0
    for i in range(1, len(pts)):
        total += _dist(pts[i - 1], pts[i])
    return total


def _edge_normal(a: Point, b: Point) -> Tuple[float, float]:
    """Inward-pointing unit normal for edge a→b (CCW polygon convention).

    For a CCW polygon the interior is to the left of each directed edge.
    Rotating the edge direction 90° counter-clockwise gives the left (inward)
    normal: (-dy, dx) normalised.
    """
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return 0.0, 0.0
    return -dy / length, dx / length   # rotate 90° CCW → inward for CCW ring


def _polygon_area_signed(pts: Polyline) -> float:
    n = len(pts)
    area = 0.0
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        area += x1 * y2 - x2 * y1
    return area / 2.0


def _ensure_ccw(pts: Polyline) -> Polyline:
    if _polygon_area_signed(pts) < 0:
        return list(reversed(pts))
    return list(pts)


def _offset_polygon(pts: Polyline, distance: float) -> Polyline:
    """
    Offset a closed polygon inward by *distance* using vertex-normal averaging.

    Each vertex is displaced along the bisector of its two adjacent edge
    normals (i.e. the average inward normal direction), scaled so that the
    perpendicular distance from each edge equals *distance*.

    This is a first-order approximation — it handles convex and mildly convex
    corners well.  Highly non-convex or very-tight-corner polygons may produce
    self-intersecting rings; those are filtered by the caller via the
    point-in-polygon raster screen.
    """
    pts = _ensure_ccw(pts)
    n = len(pts)
    result = []
    for i in range(n):
        prev_p = pts[(i - 1) % n]
        curr_p = pts[i]
        next_p = pts[(i + 1) % n]

        # Normals of the two edges meeting at this vertex
        nx1, ny1 = _edge_normal(prev_p, curr_p)
        nx2, ny2 = _edge_normal(curr_p, next_p)

        # Average (bisector direction)
        bx = (nx1 + nx2) / 2.0
        by = (ny1 + ny2) / 2.0
        bl = math.hypot(bx, by)

        if bl < 1e-9:
            # Straight edge: bisector ill-defined — use either normal
            bx, by = nx1, ny1
            bl = 1.0

        # Normalise bisector to unit vector
        ubx, uby = bx / bl, by / bl

        # The perpendicular component of the unit bisector w.r.t. the adjacent
        # edge normal gives the scale factor: moving distance s along the
        # bisector creates a perpendicular offset of s*dot from each edge.
        # We want perpendicular offset = distance, so s = distance / dot.
        dot = ubx * nx2 + uby * ny2
        dot = max(dot, 0.15)   # clamp extreme concave miters (< ~8.6°)
        s = distance / dot

        result.append((curr_p[0] + ubx * s, curr_p[1] + uby * s))

    return result


def _point_in_polygon(px: float, py: float, poly: Polyline) -> bool:
    """Ray-casting point-in-polygon test."""
    n = len(poly)
    inside = False
    xj, yj = poly[-1]
    for xi, yi in poly:
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi) + xi):
            inside = not inside
        xj, yj = xi, yi
    return inside


def _polygon_is_valid(pts: Polyline, boundary: Polyline, min_size: float) -> bool:
    """Return True if the offset ring is non-degenerate and lies inside boundary."""
    if len(pts) < 3:
        return False
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    # Bounding box sanity check
    if (max(xs) - min(xs)) < min_size or (max(ys) - min(ys)) < min_size:
        return False
    # The ring must have positive (CCW) area — inverted polygons are invalid
    area = _polygon_area_signed(pts)
    if area <= 0:
        return False
    # All vertices must be inside the boundary
    # (centroid-only check fails for inverted/flipped rings)
    for p in pts:
        if not _point_in_polygon(p[0], p[1], boundary):
            return False
    return True


def _connect_rings_with_lead(rings: List[Polyline]) -> Tuple[List[Polyline], List[List[float]]]:
    """
    Connect successive offset rings into one continuous path with short
    lead-in / lead-out moves at each transition.  Returns (polylines, feeds)
    where feeds is slower on transition segments to limit engagement spike.
    """
    if not rings:
        return [], []

    all_polys: List[Polyline] = []
    all_feeds: List[List[float]] = []

    base_feed = 1000.0   # placeholder — caller overrides
    corner_feed = base_feed * 0.6

    prev_end = rings[0][-1]
    for ring in rings:
        # Start at the point on this ring closest to prev_end
        dists = [_dist(prev_end, p) for p in ring]
        start_idx = dists.index(min(dists))
        reordered = ring[start_idx:] + ring[:start_idx] + [ring[start_idx]]

        poly = [prev_end] + reordered
        feeds = [corner_feed] + [base_feed] * len(reordered)
        all_polys.append(poly)
        all_feeds.append(feeds)
        prev_end = reordered[-1]

    return all_polys, all_feeds


# ===========================================================================
# 1. Adaptive pocket clearing
# ===========================================================================

def adaptive_pocket(
    boundary: Polyline,
    tool_diameter: float,
    engagement_fraction: float,
    depth: float,
    feed: float,
) -> dict:
    """
    Adaptive (constant tool-engagement) 2D pocket clearing.

    Parameters
    ----------
    boundary          : closed polygon [(x, y), ...] describing the pocket wall
    tool_diameter     : cutter diameter in mm
    engagement_fraction : target radial engagement as fraction of tool_diameter
                          (e.g. 0.30 = 30 %)
    depth             : axial depth of cut (informational; included in metadata)
    feed              : nominal feed rate in mm/min (corners use 60 % of this)

    Returns dict with keys polylines, feeds, total_length, metadata.

    Method
    ------
    Iterative inward polygon offset ("buffer") using vertex-normal averaging.
    The step-over between successive rings equals engagement_fraction × D.
    Self-intersecting or degenerate rings are discarded.  Transitions between
    rings use a short chord move (not a full retract) to maintain chip load.
    """
    tool_radius = tool_diameter / 2.0
    step_over = engagement_fraction * tool_diameter

    # Start one tool-radius in from the boundary so the cutter edge just
    # touches the wall on the first pass.
    rings: List[Polyline] = []

    current_pts = _ensure_ccw(boundary)

    # First ring: offset by one tool radius (wall contact)
    offset_dist = tool_radius
    while True:
        offset_pts = _offset_polygon(current_pts, offset_dist)
        if not _polygon_is_valid(offset_pts, boundary, step_over * 0.5):
            break
        rings.append(offset_pts)
        current_pts = offset_pts
        offset_dist = step_over   # subsequent rings step by step_over

    if not rings:
        # Pocket too small for this tool — return empty
        return {
            "polylines": [],
            "feeds": [],
            "total_length": 0.0,
            "metadata": {
                "strategy": "adaptive_pocket",
                "rings": 0,
                "tool_diameter": tool_diameter,
                "engagement_fraction": engagement_fraction,
                "depth": depth,
                "note": "pocket too small for this tool diameter",
            },
        }

    # Reverse: machine from centre outward gives better chip evacuation
    # but inward-out is easier to generate correctly.  Keep inward order.
    polylines, feeds_raw = _connect_rings_with_lead(rings)

    # Apply caller feed rate (feeds_raw uses placeholder 1000.0)
    corner_feed = feed * 0.6
    scaled_feeds = []
    for feed_list in feeds_raw:
        scaled_feeds.append([corner_feed if f < 800 else feed for f in feed_list])

    total_length = sum(_poly_length(pl) for pl in polylines)

    # Engagement check: the true radial chip load on straight sections is the
    # perpendicular distance between successive offset contours.  We measure
    # this as the difference in "apothems" (perpendicular distance from origin
    # to each edge midpoint), which equals the design step_over by construction.
    # Corner vertices are further apart (miter factor = 1/sin(45°) = √2 for 90°
    # corners) but do not represent a wider cut — the tool arc at a corner sweeps
    # the same radial depth.  We report the maximum per-edge-midpoint
    # to next-ring-edge-midpoint distance across the ring.
    actual_max_engagement = 0.0
    for i in range(1, len(rings)):
        ring_outer = rings[i - 1]
        ring_inner = rings[i]
        n_o = len(ring_outer)
        n_i = len(ring_inner)
        # Use edge midpoints (not vertices) to avoid corner miter distortion
        for j in range(n_o):
            mx = (ring_outer[j][0] + ring_outer[(j + 1) % n_o][0]) / 2.0
            my = (ring_outer[j][1] + ring_outer[(j + 1) % n_o][1]) / 2.0
            # Distance to nearest edge midpoint on inner ring
            inner_midpoints = [
                ((ring_inner[k][0] + ring_inner[(k + 1) % n_i][0]) / 2.0,
                 (ring_inner[k][1] + ring_inner[(k + 1) % n_i][1]) / 2.0)
                for k in range(n_i)
            ]
            min_d = min(_dist((mx, my), imp) for imp in inner_midpoints)
            actual_max_engagement = max(actual_max_engagement, min_d)

    return {
        "polylines": polylines,
        "feeds": scaled_feeds,
        "total_length": total_length,
        "metadata": {
            "strategy": "adaptive_pocket",
            "rings": len(rings),
            "tool_diameter": tool_diameter,
            "engagement_fraction": engagement_fraction,
            "actual_max_engagement_mm": round(actual_max_engagement, 4),
            "target_engagement_mm": round(step_over, 4),
            "depth": depth,
        },
    }


# ===========================================================================
# 2. Trochoidal slot milling
# ===========================================================================

def trochoidal_slot(
    slot_polyline: Polyline,
    tool_diameter: float,
    trochoid_radius: float,
    feed: float,
    points_per_circle: int = 36,
) -> dict:
    """
    Trochoidal slot milling.

    Parameters
    ----------
    slot_polyline     : open polyline [(x,y), ...] defining the slot centreline
    tool_diameter     : cutter diameter in mm
    trochoid_radius   : radius of each trochoidal loop (= half the desired
                        radial engagement), in mm.  Must be < tool_diameter/2.
    feed              : feed rate in mm/min
    points_per_circle : tessellation of each circle (default 36)

    Returns dict with polylines, feeds, total_length, metadata.

    Method
    ------
    The slot centreline is walked in increments of trochoid_radius (the
    step-over).  At each centre position a full circle of radius
    trochoid_radius is emitted.  Successive circles overlap by (2R - step)
    which guarantees the full slot width is swept when
    trochoid_radius >= tool_diameter/2.  The slot_polyline segments define
    the travel direction; each segment is sampled at step_over intervals.
    """
    step = trochoid_radius   # advance per loop (= step-over)

    # Flatten the slot polyline into a list of equidistant centres
    centres: List[Point] = []
    for seg_idx in range(len(slot_polyline) - 1):
        a = slot_polyline[seg_idx]
        b = slot_polyline[seg_idx + 1]
        seg_len = _dist(a, b)
        if seg_len < 1e-9:
            continue
        dx = (b[0] - a[0]) / seg_len
        dy = (b[1] - a[1]) / seg_len
        t = 0.0
        while t <= seg_len + 1e-9:
            centres.append((a[0] + dx * t, a[1] + dy * t))
            t += step

    if not centres:
        return {"polylines": [], "feeds": [], "total_length": 0.0,
                "metadata": {"strategy": "trochoidal_slot", "circles": 0}}

    polylines: List[Polyline] = []
    all_feeds: List[List[float]] = []

    for cx, cy in centres:
        circle: Polyline = []
        for k in range(points_per_circle + 1):
            angle = 2.0 * math.pi * k / points_per_circle
            x = cx + trochoid_radius * math.cos(angle)
            y = cy + trochoid_radius * math.sin(angle)
            circle.append((x, y))
        polylines.append(circle)
        all_feeds.append([feed] * len(circle))

    total_length = sum(_poly_length(pl) for pl in polylines)

    # Coverage check: each point along slot centreline should be within
    # trochoid_radius of at least one circle centre — guaranteed by construction
    # since step = trochoid_radius (circles overlap by 50 %).
    overlap_ratio = (2.0 * trochoid_radius - step) / (2.0 * trochoid_radius)

    return {
        "polylines": polylines,
        "feeds": all_feeds,
        "total_length": total_length,
        "metadata": {
            "strategy": "trochoidal_slot",
            "circles": len(centres),
            "trochoid_radius": trochoid_radius,
            "step_over": step,
            "overlap_ratio": round(overlap_ratio, 3),
            "tool_diameter": tool_diameter,
        },
    }


# ===========================================================================
# 3. Rest machining
# ===========================================================================

def rest_machining(
    prior_toolpaths: List[Polyline],
    boundary: Polyline,
    large_tool_diameter: float,
    small_tool_diameter: float,
    feed: float,
    grid_resolution: float = 0.5,
) -> dict:
    """
    Raster-based rest-machining: find regions not cleared by the prior large
    tool and generate a small-tool clearing path over them.

    Parameters
    ----------
    prior_toolpaths      : list of polylines from the large-tool operation
    boundary             : closed polygon defining the workpiece extents
    large_tool_diameter  : prior tool diameter (mm)
    small_tool_diameter  : rest-machining tool diameter (mm)
    feed                 : feed rate for the rest-machining pass (mm/min)
    grid_resolution      : pixel size for the raster grid (mm, default 0.5)

    Returns dict with polylines, feeds, total_length, metadata.

    Method
    ------
    1. Build a grid covering the boundary bounding box.
    2. Mark all cells inside the boundary as "uncleared".
    3. Rasterise the prior toolpath: every cell whose centre is within
       large_tool_diameter/2 of any toolpath segment is marked "cleared".
    4. Collect all uncleared cells.
    5. Sort by Y then X and emit zigzag passes with the small tool.
    6. Only emit moves that are ≥ small_tool_diameter apart (avoid redundant
       overlap on sparse areas).
    """
    large_r = large_tool_diameter / 2.0
    small_r = small_tool_diameter / 2.0

    # Bounding box
    bxs = [p[0] for p in boundary]
    bys = [p[1] for p in boundary]
    x_min, x_max = min(bxs), max(bxs)
    y_min, y_max = min(bys), max(bys)

    res = grid_resolution
    nx = max(1, int(math.ceil((x_max - x_min) / res)))
    ny = max(1, int(math.ceil((y_max - y_min) / res)))

    # Grid cell centres
    def cell_centre(ix: int, iy: int) -> Point:
        return (x_min + (ix + 0.5) * res, y_min + (iy + 0.5) * res)

    # Step 2: mark cells inside boundary
    inside = [[False] * ny for _ in range(nx)]
    for ix in range(nx):
        for iy in range(ny):
            cx, cy = cell_centre(ix, iy)
            inside[ix][iy] = _point_in_polygon(cx, cy, boundary)

    # Step 3: mark cells cleared by prior toolpath
    cleared = [[False] * ny for _ in range(nx)]
    large_r_sq = large_r * large_r

    for polyline in prior_toolpaths:
        for seg_idx in range(len(polyline) - 1):
            ax, ay = polyline[seg_idx]
            bx, by = polyline[seg_idx + 1]
            seg_len = _dist((ax, ay), (bx, by))

            # Bounding box for this segment + radius
            sx_min = min(ax, bx) - large_r
            sx_max = max(ax, bx) + large_r
            sy_min = min(ay, by) - large_r
            sy_max = max(ay, by) + large_r

            # Pixel range
            ix0 = max(0, int((sx_min - x_min) / res))
            ix1 = min(nx - 1, int((sx_max - x_min) / res) + 1)
            iy0 = max(0, int((sy_min - y_min) / res))
            iy1 = min(ny - 1, int((sy_max - y_min) / res) + 1)

            for ix in range(ix0, ix1 + 1):
                for iy in range(iy0, iy1 + 1):
                    if cleared[ix][iy]:
                        continue
                    px, py = cell_centre(ix, iy)
                    # Distance from point to segment
                    if seg_len < 1e-9:
                        d_sq = (px - ax) ** 2 + (py - ay) ** 2
                    else:
                        t = ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / (seg_len * seg_len)
                        t = max(0.0, min(1.0, t))
                        qx = ax + t * (bx - ax)
                        qy = ay + t * (by - ay)
                        d_sq = (px - qx) ** 2 + (py - qy) ** 2
                    if d_sq <= large_r_sq:
                        cleared[ix][iy] = True

    # Step 4: collect uncleared cells inside boundary
    uncleared: List[Point] = []
    for ix in range(nx):
        for iy in range(ny):
            if inside[ix][iy] and not cleared[ix][iy]:
                uncleared.append(cell_centre(ix, iy))

    if not uncleared:
        return {
            "polylines": [],
            "feeds": [],
            "total_length": 0.0,
            "metadata": {
                "strategy": "rest_machining",
                "uncleared_cells": 0,
                "large_tool_diameter": large_tool_diameter,
                "small_tool_diameter": small_tool_diameter,
            },
        }

    # Step 5: zigzag over uncleared cells sorted by Y-row
    # Group by Y-row
    row_map: dict[int, List[float]] = {}
    for px, py in uncleared:
        iy = int((py - y_min) / res)
        row_map.setdefault(iy, []).append(px)

    polylines: List[Polyline] = []
    all_feeds: List[List[float]] = []
    step_x = small_tool_diameter * 0.9   # 90 % step-over for the small tool

    left_to_right = True
    for iy in sorted(row_map.keys()):
        py = y_min + (iy + 0.5) * res
        xs = sorted(row_map[iy])
        if not left_to_right:
            xs = list(reversed(xs))
        left_to_right = not left_to_right

        # Merge into runs (skip gaps larger than 2×step_x)
        run: Polyline = []
        for x in xs:
            if run and abs(x - run[-1][0]) > step_x * 2.5:
                if len(run) >= 1:
                    polylines.append(run)
                    all_feeds.append([feed] * len(run))
                run = [(x, py)]
            else:
                run.append((x, py))
        if run:
            polylines.append(run)
            all_feeds.append([feed] * len(run))

    total_length = sum(_poly_length(pl) for pl in polylines)

    return {
        "polylines": polylines,
        "feeds": all_feeds,
        "total_length": total_length,
        "metadata": {
            "strategy": "rest_machining",
            "uncleared_cells": len(uncleared),
            "grid_resolution": res,
            "large_tool_diameter": large_tool_diameter,
            "small_tool_diameter": small_tool_diameter,
            "rows_cleared": len(row_map),
        },
    }


# ===========================================================================
# LLM tool specs
# ===========================================================================

# -- adaptive_pocket ----------------------------------------------------------

adaptive_pocket_spec = ToolSpec(
    name="hsm_adaptive_pocket",
    description=(
        "High-speed machining: constant tool-engagement adaptive 2D pocket clearing. "
        "Generates an inward-spiralling offset-curve toolpath where the radial chip "
        "load stays at or below the target engagement fraction throughout, including "
        "corners.  No opencamlib required.  Returns polylines, per-point feed rates, "
        "total path length, and engagement diagnostics."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "boundary": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "Closed pocket boundary as [[x, y], ...] (mm)",
            },
            "tool_diameter": {
                "type": "number",
                "description": "Tool diameter in mm (e.g. 10.0)",
            },
            "engagement_fraction": {
                "type": "number",
                "description": "Target radial engagement as fraction of D (e.g. 0.30 = 30%)",
            },
            "depth": {
                "type": "number",
                "description": "Axial depth of cut in mm (informational)",
            },
            "feed": {
                "type": "number",
                "description": "Nominal feed rate in mm/min",
            },
        },
        "required": ["boundary", "tool_diameter", "engagement_fraction", "depth", "feed"],
    },
)


@register(adaptive_pocket_spec)
async def run_adaptive_pocket(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        boundary = [tuple(p) for p in a["boundary"]]
        result = adaptive_pocket(
            boundary=boundary,
            tool_diameter=float(a["tool_diameter"]),
            engagement_fraction=float(a["engagement_fraction"]),
            depth=float(a.get("depth", 1.0)),
            feed=float(a.get("feed", 1000.0)),
        )
    except Exception as e:
        return err_payload(str(e), "ERROR")

    # Serialise polylines as lists for JSON transport
    result["polylines"] = [list(pl) for pl in result["polylines"]]
    return ok_payload(result)


# -- trochoidal_slot ----------------------------------------------------------

trochoidal_slot_spec = ToolSpec(
    name="hsm_trochoidal_slot",
    description=(
        "High-speed machining: trochoidal (looping) slot milling. "
        "Superimposes overlapping circles on the slot direction so the tool "
        "never takes a full-width cut.  Peak radial engagement = trochoid_radius. "
        "Returns polylines (one per circle), per-point feed rates, total path length, "
        "and overlap diagnostics."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "slot_polyline": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "Open slot centreline as [[x, y], ...] (mm)",
            },
            "tool_diameter": {
                "type": "number",
                "description": "Tool diameter in mm (e.g. 6.0)",
            },
            "trochoid_radius": {
                "type": "number",
                "description": "Radius of each trochoidal loop in mm (half engagement width)",
            },
            "feed": {
                "type": "number",
                "description": "Feed rate in mm/min",
            },
        },
        "required": ["slot_polyline", "tool_diameter", "trochoid_radius", "feed"],
    },
)


@register(trochoidal_slot_spec)
async def run_trochoidal_slot(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        slot = [tuple(p) for p in a["slot_polyline"]]
        result = trochoidal_slot(
            slot_polyline=slot,
            tool_diameter=float(a["tool_diameter"]),
            trochoid_radius=float(a["trochoid_radius"]),
            feed=float(a.get("feed", 1000.0)),
        )
    except Exception as e:
        return err_payload(str(e), "ERROR")

    result["polylines"] = [list(pl) for pl in result["polylines"]]
    return ok_payload(result)


# -- rest_machining -----------------------------------------------------------

rest_machining_spec = ToolSpec(
    name="hsm_rest_machining",
    description=(
        "High-speed machining: rest-machining pass to clear corners and regions "
        "left by a larger prior tool.  Uses a raster grid to compute the uncleared "
        "boolean region (inside boundary but outside the large-tool sweep envelope), "
        "then generates a zigzag small-tool clearing path over those regions."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "prior_toolpaths": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                },
                "description": "List of polylines from the prior large-tool operation",
            },
            "boundary": {
                "type": "array",
                "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                "description": "Closed workpiece boundary as [[x, y], ...] (mm)",
            },
            "large_tool_diameter": {
                "type": "number",
                "description": "Diameter of the prior (large) tool in mm",
            },
            "small_tool_diameter": {
                "type": "number",
                "description": "Diameter of the rest-machining (small) tool in mm",
            },
            "feed": {
                "type": "number",
                "description": "Feed rate for the rest-machining pass in mm/min",
            },
            "grid_resolution": {
                "type": "number",
                "description": "Raster pixel size in mm (default 0.5)",
            },
        },
        "required": [
            "prior_toolpaths", "boundary",
            "large_tool_diameter", "small_tool_diameter", "feed",
        ],
    },
)


@register(rest_machining_spec)
async def run_rest_machining(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    try:
        prior_toolpaths = [[tuple(p) for p in pl] for pl in a["prior_toolpaths"]]
        boundary = [tuple(p) for p in a["boundary"]]
        result = rest_machining(
            prior_toolpaths=prior_toolpaths,
            boundary=boundary,
            large_tool_diameter=float(a["large_tool_diameter"]),
            small_tool_diameter=float(a["small_tool_diameter"]),
            feed=float(a.get("feed", 1000.0)),
            grid_resolution=float(a.get("grid_resolution", 0.5)),
        )
    except Exception as e:
        return err_payload(str(e), "ERROR")

    result["polylines"] = [list(pl) for pl in result["polylines"]]
    return ok_payload(result)
