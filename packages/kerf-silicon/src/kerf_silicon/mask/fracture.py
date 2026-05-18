"""fracture.py — polygon fracturing for e-beam mask writers.

Converts arbitrary rectilinear or general polygons into a set of non-overlapping
trapezoids (and axis-aligned rectangles, which are a special case) that together
tile the interior of the input shape exactly.

Algorithm: greedy sweep-line trapezoidal decomposition.
  1. Collect all unique y-coordinates of the polygon vertices (scan lines).
  2. Sort the scan lines in ascending order.
  3. For each horizontal band between consecutive scan lines, compute the
     x-extent of the polygon interior using a standard even-odd fill rule.
  4. Merge adjacent intervals to form one trapezoid per monotone strip.
  5. If the resulting trapezoid width (max of top/bottom) exceeds *max_dim_nm*,
     subdivide it along x into pieces that each respect the limit.

Units: all coordinates are in nanometres (integers or floats).

Public API
----------
fracture_polygon(polygon, max_dim_nm=100_000) -> list[Trapezoid]
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence


@dataclass
class Trapezoid:
    """An axis-aligned trapezoid (two horizontal edges, two slanted/vertical sides).

    Attributes
    ----------
    x_lo_bot, x_hi_bot : float
        Left and right x-coordinates of the *bottom* edge (at y = y_bot).
    x_lo_top, x_hi_top : float
        Left and right x-coordinates of the *top* edge (at y = y_top).
    y_bot : float
        Y-coordinate of the bottom edge.
    y_top : float
        Y-coordinate of the top edge.

    For a rectangle: x_lo_bot == x_lo_top and x_hi_bot == x_hi_top.
    Area = 0.5 * (bottom_width + top_width) * height.
    """

    x_lo_bot: float
    x_hi_bot: float
    x_lo_top: float
    x_hi_top: float
    y_bot: float
    y_top: float

    @property
    def area(self) -> float:
        """Exact area of the trapezoid."""
        bot_w = self.x_hi_bot - self.x_lo_bot
        top_w = self.x_hi_top - self.x_lo_top
        h = self.y_top - self.y_bot
        return 0.5 * (bot_w + top_w) * h


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_EPS = 1e-9  # floating-point tolerance for edge intersection tests


def _polygon_area_shoelace(poly: list[tuple[float, float]]) -> float:
    """Signed area of a simple polygon via the shoelace formula."""
    n = len(poly)
    s = 0.0
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        s += x0 * y1 - x1 * y0
    return 0.5 * s


def _x_at_y(
    x0: float, y0: float, x1: float, y1: float, y: float
) -> float:
    """X-coordinate where edge (x0,y0)-(x1,y1) crosses horizontal line y.

    The edge is assumed to span y (caller must verify).
    """
    if abs(y1 - y0) < _EPS:
        # Horizontal edge — return midpoint (should be handled by caller)
        return 0.5 * (x0 + x1)
    t = (y - y0) / (y1 - y0)
    return x0 + t * (x1 - x0)


def _intersect_band(
    polygon: list[tuple[float, float]],
    y_bot: float,
    y_top: float,
) -> list[tuple[float, float]]:
    """Return sorted list of (x_at_bot, x_at_top) crossing pairs.

    Uses the even-odd (scan-line) rule: for each non-horizontal edge that
    straddles the band [y_bot, y_top], we record the x-values at y_bot and
    y_top.  The resulting list (sorted by x_at_bot, then x_at_top) is paired
    as intervals: [x0, x1], [x2, x3], ...
    """
    crossings: list[tuple[float, float]] = []
    n = len(polygon)
    y_mid = 0.5 * (y_bot + y_top)

    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]

        # Skip horizontal edges
        if abs(y1 - y0) < _EPS:
            continue

        # Check if edge crosses the midpoint scan line (avoids vertex issues)
        # We test against y_mid to decide whether the edge is active in the band.
        lo, hi = (y0, y1) if y0 < y1 else (y1, y0)
        if lo >= y_mid or hi <= y_mid:
            continue

        xb = _x_at_y(x0, y0, x1, y1, y_bot)
        xt = _x_at_y(x0, y0, x1, y1, y_top)
        crossings.append((xb, xt))

    # Sort by x at the bottom edge, then top
    crossings.sort(key=lambda c: (c[0], c[1]))
    return crossings


def _pairs_to_intervals(
    crossings: list[tuple[float, float]],
) -> list[tuple[float, float, float, float]]:
    """Convert a list of (x_bot, x_top) crossings to (x_lo_bot, x_lo_top, x_hi_bot, x_hi_top).

    Pairs consecutive crossings: index 0+1, 2+3, ...
    """
    intervals = []
    for i in range(0, len(crossings) - 1, 2):
        xb0, xt0 = crossings[i]
        xb1, xt1 = crossings[i + 1]
        intervals.append((xb0, xt0, xb1, xt1))  # (lo_bot, lo_top, hi_bot, hi_top)
    return intervals


def _subdivide_trapezoid(
    trap: Trapezoid, max_dim_nm: float
) -> list[Trapezoid]:
    """Subdivide a trapezoid along x if its width exceeds *max_dim_nm*.

    We subdivide the bottom and top edges uniformly into the same number of
    pieces so that each sub-trapezoid has width <= max_dim_nm.
    """
    bot_w = trap.x_hi_bot - trap.x_lo_bot
    top_w = trap.x_hi_top - trap.x_lo_top
    max_w = max(bot_w, top_w)

    if max_w <= max_dim_nm + _EPS:
        return [trap]

    n_pieces = math.ceil(max_w / max_dim_nm)
    result: list[Trapezoid] = []
    for k in range(n_pieces):
        t0 = k / n_pieces
        t1 = (k + 1) / n_pieces
        sub = Trapezoid(
            x_lo_bot=trap.x_lo_bot + t0 * bot_w,
            x_hi_bot=trap.x_lo_bot + t1 * bot_w,
            x_lo_top=trap.x_lo_top + t0 * top_w,
            x_hi_top=trap.x_lo_top + t1 * top_w,
            y_bot=trap.y_bot,
            y_top=trap.y_top,
        )
        result.append(sub)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fracture_polygon(
    polygon: Sequence[tuple[float, float]],
    max_dim_nm: float = 100_000,
) -> list[Trapezoid]:
    """Convert a simple polygon to e-beam-friendly trapezoids.

    Parameters
    ----------
    polygon : sequence of (x, y) tuples
        Vertices of the polygon in nm, given in either winding order.
        The polygon must be simple (no self-intersections).
    max_dim_nm : float
        Maximum width allowed per trapezoid, in nm (default 100 000 nm = 100 µm).
        Wider trapezoids are subdivided along x.

    Returns
    -------
    list[Trapezoid]
        Non-overlapping trapezoids whose union equals the polygon interior.
        A convex polygon with n vertices produces at most n-1 trapezoids.

    Notes
    -----
    The algorithm uses a horizontal sweep from y_min to y_max.  For each strip
    between consecutive vertex y-values, the active edges are scanned at the
    strip's midpoint and at both horizontal boundaries using linear
    interpolation.  This avoids numerical issues at shared vertices.
    """
    poly = list(polygon)
    if len(poly) < 3:
        return []

    # Ensure counter-clockwise winding (positive shoelace area)
    if _polygon_area_shoelace(poly) < 0:
        poly = poly[::-1]

    # Collect unique y-values and sort them
    ys = sorted({v[1] for v in poly})
    if len(ys) < 2:
        return []

    result: list[Trapezoid] = []

    for idx in range(len(ys) - 1):
        y_bot = ys[idx]
        y_top = ys[idx + 1]

        if y_top - y_bot < _EPS:
            continue

        crossings = _intersect_band(poly, y_bot, y_top)
        if len(crossings) < 2:
            continue

        intervals = _pairs_to_intervals(crossings)
        for x_lo_bot, x_lo_top, x_hi_bot, x_hi_top in intervals:
            if x_hi_bot - x_lo_bot < _EPS and x_hi_top - x_lo_top < _EPS:
                continue
            trap = Trapezoid(
                x_lo_bot=x_lo_bot,
                x_hi_bot=x_hi_bot,
                x_lo_top=x_lo_top,
                x_hi_top=x_hi_top,
                y_bot=y_bot,
                y_top=y_top,
            )
            result.extend(_subdivide_trapezoid(trap, max_dim_nm))

    return result
