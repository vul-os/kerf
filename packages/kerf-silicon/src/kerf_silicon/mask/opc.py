"""opc.py — Optical Proximity Correction (OPC) stub.

This module provides a stub-level OPC engine that applies two classical
correction techniques:

1. **Hammerhead extensions** — rectangular tabs added at the two ends of a
   narrow line to counteract line-end shortening (the tendency for resist
   lines to print shorter than drawn due to diffraction).

2. **Serif features** — small square additions at concave (inside) corners of
   a polygon to counteract corner rounding (diffraction causes inside corners
   to print rounded inward, making the feature smaller than intended).

This is explicitly a stub: it implements the geometric operations required to
demonstrate correctness but does not iterate, does not model the aerial image,
and does not use a resist model.  It is suitable for unit-testing and
algorithm-development purposes.

Design-rule keys
----------------
The *design_rules* dict may contain any of the following keys (all values in
nm; defaults are chosen to be physically reasonable at 65–130 nm nodes):

    "min_width_nm" (float)
        Features narrower than this are candidates for line-end hammerheads.
        Default: 200.

    "hammerhead_extension_nm" (float)
        How far a hammerhead protrudes beyond the drawn line-end.
        Default: 25.

    "hammerhead_width_nm" (float)
        Width of the hammerhead tab (usually slightly wider than the line).
        Default: calculated as line_width + 2 * serif_size_nm if not given.

    "serif_size_nm" (float)
        Side length of the square serif added at inside corners.
        Default: 30.

Public API
----------
apply_opc(shapes, design_rules) -> list[Shape]
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Sequence

# ---------------------------------------------------------------------------
# Shape dataclass
# ---------------------------------------------------------------------------


@dataclass
class Shape:
    """An axis-aligned rectangular shape on the mask layer.

    Attributes
    ----------
    x, y : float
        Bottom-left corner (nm).
    width, height : float
        Dimensions in nm.
    tag : str
        Descriptive tag for provenance (e.g. "original", "hammerhead", "serif").
    """

    x: float
    y: float
    width: float
    height: float
    tag: str = "original"

    # ------------------------------------------------------------------
    # Geometric helpers
    # ------------------------------------------------------------------

    @property
    def x2(self) -> float:
        return self.x + self.width

    @property
    def y2(self) -> float:
        return self.y + self.height

    @property
    def area(self) -> float:
        return self.width * self.height

    def corners(self) -> list[tuple[float, float]]:
        """Return the four corners [BL, BR, TR, TL]."""
        return [
            (self.x, self.y),
            (self.x2, self.y),
            (self.x2, self.y2),
            (self.x, self.y2),
        ]


# ---------------------------------------------------------------------------
# OPC helper: detect line-ends on narrow rectangles
# ---------------------------------------------------------------------------

_EPS = 1e-9


def _is_narrow_wire(shape: Shape, min_width_nm: float) -> bool:
    """Return True if *shape* qualifies as a narrow wire needing hammerheads.

    A wire is narrow when its smaller dimension <= min_width_nm AND its
    aspect ratio (longer / shorter) >= 2.0 so we don't confuse squares.
    """
    w, h = shape.width, shape.height
    small = min(w, h)
    large = max(w, h)
    if small < _EPS:
        return False
    return small <= min_width_nm and (large / small) >= 2.0


def _hammerheads_for_wire(
    shape: Shape,
    extension_nm: float,
    hh_width_nm: float,
) -> list[Shape]:
    """Build two hammerhead rectangles — one per line-end of *shape*.

    The hammerhead is centred on the line-end face and protrudes by
    *extension_nm* beyond it.  Its width is *hh_width_nm* (> wire width so
    it covers the corner rounding at the end).

    For a horizontal wire (width > height):
        - left end:  hammerhead extends to the left  (x direction)
        - right end: hammerhead extends to the right

    For a vertical wire (height > width):
        - bottom end: extends downward
        - top end:    extends upward
    """
    hh_shapes: list[Shape] = []

    if shape.width >= shape.height:
        # Horizontal wire; line-ends are at the left and right faces
        wire_h = shape.height
        hh_h = hh_width_nm  # hh extends in y
        hh_w = extension_nm  # hh extends in x

        centre_y = shape.y + 0.5 * wire_h
        hh_y = centre_y - 0.5 * hh_h

        # Left end
        hh_shapes.append(Shape(
            x=shape.x - hh_w,
            y=hh_y,
            width=hh_w,
            height=hh_h,
            tag="hammerhead",
        ))
        # Right end
        hh_shapes.append(Shape(
            x=shape.x2,
            y=hh_y,
            width=hh_w,
            height=hh_h,
            tag="hammerhead",
        ))
    else:
        # Vertical wire; line-ends are at the bottom and top faces
        wire_w = shape.width
        hh_w = hh_width_nm  # hh extends in x
        hh_h = extension_nm  # hh extends in y

        centre_x = shape.x + 0.5 * wire_w
        hh_x = centre_x - 0.5 * hh_w

        # Bottom end
        hh_shapes.append(Shape(
            x=hh_x,
            y=shape.y - hh_h,
            width=hh_w,
            height=hh_h,
            tag="hammerhead",
        ))
        # Top end
        hh_shapes.append(Shape(
            x=hh_x,
            y=shape.y2,
            width=hh_w,
            height=hh_h,
            tag="hammerhead",
        ))

    return hh_shapes


# ---------------------------------------------------------------------------
# OPC helper: detect inside corners of a compound shape (list of rectangles)
# ---------------------------------------------------------------------------


def _find_inside_corners(
    shapes: list[Shape],
) -> list[tuple[float, float]]:
    """Identify concave (inside) corners in the union of all *shapes*.

    An inside corner is a vertex of the bounding union that is concave — i.e.
    the interior angle at that vertex (measured inside the shape) is 270°.

    This implementation uses a simple rasterisation-free approach:
    for each vertex (x, y) in the set of all shape corners, test whether the
    two interior quadrants (the ones "inside" the corner for a 270° vertex)
    are both covered by some shape in the list, while the exterior quadrant
    (the 90° cutout) is not covered.

    Returns a list of (x, y) coordinates of inside corners.
    """
    # Collect all corner coordinates
    all_x = sorted({s.x for s in shapes} | {s.x2 for s in shapes})
    all_y = sorted({s.y for s in shapes} | {s.y2 for s in shapes})

    def covered(px: float, py: float) -> bool:
        """Return True if point (px, py) — tested as an open interior point —
        falls strictly inside at least one shape."""
        for s in shapes:
            if s.x < px < s.x2 and s.y < py < s.y2:
                return True
        return False

    inside_corners: list[tuple[float, float]] = []
    delta = 1.0  # 1 nm probe offset — safe for nm-unit coordinates

    for vx in all_x:
        for vy in all_y:
            # A vertex is on the boundary; probe the four quadrants
            q_ll = covered(vx - delta, vy - delta)  # lower-left
            q_lr = covered(vx + delta, vy - delta)  # lower-right
            q_ul = covered(vx - delta, vy + delta)  # upper-left
            q_ur = covered(vx + delta, vy + delta)  # upper-right

            covered_count = sum([q_ll, q_lr, q_ul, q_ur])
            # Inside corner: exactly 3 quadrants covered (270° interior angle)
            if covered_count == 3:
                inside_corners.append((vx, vy))

    return inside_corners


def _serif_at_corner(
    vx: float,
    vy: float,
    shapes: list[Shape],
    serif_size: float,
    delta: float = 1.0,
) -> Shape | None:
    """Return a serif square placed in the uncovered quadrant at (vx, vy).

    The uncovered quadrant is the one that is *not* filled — the serif fills
    it to counteract corner rounding.
    """

    def covered(px: float, py: float) -> bool:
        for s in shapes:
            if s.x < px < s.x2 and s.y < py < s.y2:
                return True
        return False

    q_ll = covered(vx - delta, vy - delta)
    q_lr = covered(vx + delta, vy - delta)
    q_ul = covered(vx - delta, vy + delta)
    q_ur = covered(vx + delta, vy + delta)

    # Find the empty quadrant
    if not q_ll:
        return Shape(x=vx - serif_size, y=vy - serif_size,
                     width=serif_size, height=serif_size, tag="serif")
    if not q_lr:
        return Shape(x=vx, y=vy - serif_size,
                     width=serif_size, height=serif_size, tag="serif")
    if not q_ul:
        return Shape(x=vx - serif_size, y=vy,
                     width=serif_size, height=serif_size, tag="serif")
    if not q_ur:
        return Shape(x=vx, y=vy,
                     width=serif_size, height=serif_size, tag="serif")
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_opc(
    shapes: Sequence[Shape],
    design_rules: dict[str, Any] | None = None,
) -> list[Shape]:
    """Apply stub-level Optical Proximity Correction to *shapes*.

    Adds hammerhead extensions at the ends of narrow wires and serif squares
    at concave inside corners.

    Parameters
    ----------
    shapes : sequence of Shape
        The as-drawn mask shapes (all axis-aligned rectangles).
    design_rules : dict, optional
        Override default OPC parameters.  Recognised keys:

        - ``"min_width_nm"`` (default 200): maximum wire width eligible for
          hammerhead treatment.
        - ``"hammerhead_extension_nm"`` (default 25): protrusion length.
        - ``"hammerhead_width_nm"`` (default min_width_nm + 2*serif_size_nm):
          tab width.
        - ``"serif_size_nm"`` (default 30): serif square side length.

    Returns
    -------
    list[Shape]
        Original shapes followed by all added OPC features.  The list is
        ordered: originals first, then hammerheads, then serifs.
    """
    dr = design_rules or {}
    min_width_nm: float = float(dr.get("min_width_nm", 200.0))
    hh_ext_nm: float = float(dr.get("hammerhead_extension_nm", 25.0))
    serif_size_nm: float = float(dr.get("serif_size_nm", 30.0))
    hh_width_nm: float = float(
        dr.get("hammerhead_width_nm", min_width_nm + 2.0 * serif_size_nm)
    )

    original = list(shapes)
    hammerheads: list[Shape] = []
    serifs: list[Shape] = []

    # --- Pass 1: hammerheads on narrow wires ---
    for shape in original:
        if _is_narrow_wire(shape, min_width_nm):
            hh = _hammerheads_for_wire(shape, hh_ext_nm, hh_width_nm)
            hammerheads.extend(hh)

    # --- Pass 2: serifs at inside corners of the combined shape set ---
    all_shapes = original + hammerheads  # include hh shapes in corner detection
    inside_corners = _find_inside_corners(all_shapes)
    for vx, vy in inside_corners:
        serif = _serif_at_corner(vx, vy, all_shapes, serif_size_nm)
        if serif is not None:
            serifs.append(serif)

    return original + hammerheads + serifs
