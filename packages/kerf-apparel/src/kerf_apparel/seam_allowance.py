"""
Seam-allowance offset for pattern piece outlines.

A positive offset expands the outline outward (adds seam allowance).
A negative offset shrinks it inward (removes seam allowance to get
a finished size).

The implementation uses a pure-Python inward/outward polygon offset
(Minkowski sum style) based on per-edge normal offsetting with
miter-join corner blending, requiring no external geometry library.

API
---
    add_seam_allowance(piece, offset_cm)   -> PatternPiece
    remove_seam_allowance(piece, offset_cm)-> PatternPiece  (offset_cm > 0)
    offset_polyline(pts, offset)           -> list[Point]
"""

from __future__ import annotations

import math
from typing import Sequence

from kerf_apparel.blocks import PatternPiece, Point, Polyline, _close


# ------------------------------------------------------------------ #
# Low-level polyline offset                                            #
# ------------------------------------------------------------------ #

def _edge_normal(p1: Point, p2: Point) -> tuple[float, float]:
    """
    Outward unit normal for edge (p1 → p2) in a CCW polygon.

    For a CCW polygon (positive signed area), the outward normal points
    to the RIGHT of the edge direction:
        normal = (dy/len, -dx/len)
    """
    dx = p2[0] - p1[0]
    dy = p2[1] - p1[1]
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return (0.0, 0.0)
    # Right-hand normal (CCW winding → outward)
    return (dy / length, -dx / length)


def _signed_area(pts: Sequence[Point]) -> float:
    """Signed area (positive = CCW)."""
    n = len(pts)
    acc = 0.0
    for i in range(n - 1):
        acc += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return acc / 2.0


def offset_polyline(pts: list[Point], offset: float) -> list[Point]:
    """
    Offset a closed 2-D polyline by ``offset`` cm.

    Positive offset = outward (seam allowance added).
    Negative offset = inward.

    Uses a miter-join approach: each vertex is displaced along the
    bisector of the two adjacent edge normals.  Miter is clamped to
    4× the offset to avoid extreme spikes on very acute corners.

    Parameters
    ----------
    pts : list of (x, y)
        Closed polygon (last point == first point, or open — will be
        closed internally).
    offset : float
        Signed offset distance in the same units as ``pts``.

    Returns
    -------
    list of (x, y)
        New closed polygon with same vertex count.
    """
    if len(pts) < 3:
        return list(pts)

    # Work on an open list (drop repeated closing point)
    closed = list(pts)
    if closed[-1] == closed[0]:
        closed = closed[:-1]

    n = len(closed)

    # Ensure CCW winding so that our normals point outward for positive offset
    sa = _signed_area(closed + [closed[0]])
    if sa < 0:
        # CW → flip so that positive offset = expand
        closed = closed[::-1]
        offset_dir = offset
    else:
        offset_dir = offset

    edges: list[tuple[float, float]] = []
    for i in range(n):
        edges.append(_edge_normal(closed[i], closed[(i + 1) % n]))

    new_pts: list[Point] = []
    for i in range(n):
        n1 = edges[(i - 1) % n]  # normal of incoming edge
        n2 = edges[i]             # normal of outgoing edge

        # Bisector direction
        bx = n1[0] + n2[0]
        by = n1[1] + n2[1]
        blen = math.hypot(bx, by)

        if blen < 1e-9:
            # Anti-parallel edges (180° corner) → just use one normal
            bx, by = n2
            blen = 1.0

        bx /= blen
        by /= blen

        # Miter scale: the displacement along bisector needed to achieve
        # ``offset`` perpendicular distance.
        cos_half = (n1[0] * bx + n1[1] * by)
        if abs(cos_half) < 1e-9:
            miter = 1.0
        else:
            miter = 1.0 / cos_half

        # Clamp miter to avoid crazy spikes on sharp corners
        miter = max(-4.0, min(miter, 4.0))

        d = offset_dir * miter
        new_pts.append((closed[i][0] + bx * d, closed[i][1] + by * d))

    return _close(new_pts)


# ------------------------------------------------------------------ #
# Public API                                                           #
# ------------------------------------------------------------------ #

def add_seam_allowance(piece: PatternPiece, offset_cm: float) -> PatternPiece:
    """
    Return a new ``PatternPiece`` with ``offset_cm`` seam allowance added.

    The outline is expanded outward by ``offset_cm``.  A standard 1 cm or
    1.5 cm offset is typical.

    The original piece is unchanged.
    """
    if offset_cm <= 0:
        raise ValueError("offset_cm must be positive; use remove_seam_allowance for inward offset")

    new_outline = offset_polyline(piece.outline, offset_cm)
    return PatternPiece(
        name=piece.name,
        outline=new_outline,
        grain_line=piece.grain_line,
        notches=list(piece.notches),
        labels={**piece.labels, "seam_allowance_cm": offset_cm},
    )


def remove_seam_allowance(piece: PatternPiece, offset_cm: float) -> PatternPiece:
    """
    Return a new ``PatternPiece`` with ``offset_cm`` seam allowance removed
    (inward offset — finished / net size).

    ``offset_cm`` must be positive; the offset is applied inward.
    """
    if offset_cm <= 0:
        raise ValueError("offset_cm must be positive")

    new_outline = offset_polyline(piece.outline, -offset_cm)
    return PatternPiece(
        name=piece.name,
        outline=new_outline,
        grain_line=piece.grain_line,
        notches=list(piece.notches),
        labels={**piece.labels, "seam_allowance_removed_cm": offset_cm},
    )
