"""flat_pattern.py — Sheet-metal flat-pattern generator.

Generates the flat (developed) patterns for two common rectangular duct fittings:

1. Rectangular elbow (mitre or radius elbow)
2. Rectangular reducer (straight taper)

All coordinates are in millimetres.  The output is a list of 2-D polygon
vertices that can be scored / cut on a CNC plasma table, laser, or waterjet.

Design intent
-------------
- Pure-Python, no external geometry kernel required.
- Follows the same "unfold" conceptual semantics as T-2/T-3 (sheet-metal unfold
  in kerf-cam): panels are numbered, each returned as a closed list of (x, y)
  points starting at the bottom-left, proceeding counter-clockwise.
- Seam allowances, tab geometry, and notch positions are returned separately so
  the fabricator can configure them for their specific press-brake setup.

Rectangular elbow (mitre, single cheek)
----------------------------------------
A rectangular duct elbow has four panels:

  - Two *side cheeks* (trapezoids for angled cut, rectangles for mitres).
  - One *heel plate* (inside of the bend, shorter in the travel direction).
  - One *throat plate* (outside of the bend, longer in the travel direction).

For a 90° mitre elbow of width W × height H:

  Throat plate: rectangle W × (W + H)   (wrap around outside)
  Heel plate:   rectangle W × H         (inside)
  Cheeks: two identical parallelograms / isosceles trapezoids

Here we implement a *true-radius* elbow parameterised by:
  - W, H: duct cross-section (mm)
  - angle_deg: turn angle (default 90°)
  - throat_radius_mm: bend radius at the throat (default = H, i.e. 1× duct height)

The developed (unrolled) arc length of the centreline is:

    L_centre = (throat_radius_mm + W/2) × angle_rad

The heel arc length:

    L_heel = throat_radius_mm × angle_rad

The throat arc length:

    L_throat = (throat_radius_mm + W) × angle_rad

Cheek developed length = same for both:

    cheek_chord ~ sqrt(L_centre^2 + H^2)   (not used: full cheek is a sector)

For fabrication the cheek is a *sector annulus* developed flat.  We approximate
it as a trapezoidal strip with mean arc length and width H.

Rectangular reducer (straight concentric taper)
------------------------------------------------
A reducer transitions from section W1 × H1 (upstream) to W2 × H2 (downstream)
over a taper length L.

Four panels:

  - Top and bottom plates: trapezoids (W1 → W2 wide, length L on centreline)
  - Two side plates: trapezoids (H1 → H2 tall, length L on centreline)

The *developed length* of each panel (angled face) is:

  top/bottom: sqrt(L^2 + ((H1-H2)/2)^2)  [slant in height direction]
  sides:      sqrt(L^2 + ((W1-W2)/2)^2)  [slant in width direction]

(SMACNA Sheet Metal Manual, 4th ed., sections 4-3 and 4-5)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Tuple

Point2D = Tuple[float, float]
Polygon = List[Point2D]


# ---------------------------------------------------------------------------
# Elbow flat-pattern
# ---------------------------------------------------------------------------

@dataclass
class ElbowPattern:
    """Flat-pattern output for a rectangular duct elbow.

    All lengths in mm.  Polygons are closed (last point == first point NOT
    repeated — open contour convention).

    Attributes:
        throat_plate: Flat panel for the outer (long) face.
        heel_plate: Flat panel for the inner (short) face.
        cheek_left: Left side cheek panel (sector approximation).
        cheek_right: Right side cheek panel (same shape as cheek_left).
        throat_arc_length_mm: Developed arc length of throat plate.
        heel_arc_length_mm: Developed arc length of heel plate.
        centre_arc_length_mm: Developed arc length at duct centreline.
        angle_deg: Turn angle.
        width_mm: Duct width (across bend).
        height_mm: Duct height (in bend plane).
        throat_radius_mm: Bend radius at throat face.
    """

    throat_plate: Polygon
    heel_plate: Polygon
    cheek_left: Polygon
    cheek_right: Polygon
    throat_arc_length_mm: float
    heel_arc_length_mm: float
    centre_arc_length_mm: float
    angle_deg: float
    width_mm: float
    height_mm: float
    throat_radius_mm: float


def rect_elbow_pattern(
    width_mm: float,
    height_mm: float,
    angle_deg: float = 90.0,
    throat_radius_mm: float | None = None,
) -> ElbowPattern:
    """Generate flat-pattern polygons for a rectangular duct radius elbow.

    The *width* is the duct dimension perpendicular to the bend plane (i.e.
    the dimension that the throat/heel plates span across).
    The *height* is the dimension in the bend plane (top to bottom of duct as
    it turns).

    Args:
        width_mm: Duct width (mm).
        height_mm: Duct height in the bend plane (mm).
        angle_deg: Turn angle in degrees (default 90°).
        throat_radius_mm: Bend radius at the throat (inner face).  Defaults to
            1× duct height per SMACNA guidance.

    Returns:
        :class:`ElbowPattern` with all four flat panels.
    """
    if width_mm <= 0 or height_mm <= 0:
        raise ValueError("width_mm and height_mm must be positive")
    if not (0 < angle_deg <= 180):
        raise ValueError("angle_deg must be in (0, 180]")

    if throat_radius_mm is None:
        throat_radius_mm = height_mm  # 1× D per SMACNA

    if throat_radius_mm < 0:
        raise ValueError("throat_radius_mm must be non-negative")

    angle_rad = math.radians(angle_deg)

    # Arc lengths
    heel_arc = throat_radius_mm * angle_rad
    centre_arc = (throat_radius_mm + height_mm / 2) * angle_rad
    throat_arc = (throat_radius_mm + height_mm) * angle_rad

    # ------------------------------------------------------------------
    # Throat plate: rectangle width_mm × throat_arc_length
    # Bottom-left origin, counter-clockwise
    # ------------------------------------------------------------------
    W = width_mm
    throat_plate: Polygon = [
        (0.0, 0.0),
        (W, 0.0),
        (W, throat_arc),
        (0.0, throat_arc),
    ]

    # ------------------------------------------------------------------
    # Heel plate: rectangle width_mm × heel_arc_length
    # ------------------------------------------------------------------
    heel_plate: Polygon = [
        (0.0, 0.0),
        (W, 0.0),
        (W, heel_arc),
        (0.0, heel_arc),
    ]

    # ------------------------------------------------------------------
    # Cheek panels — sector annulus approximated as a flat trapezoidal
    # strip laid out by radial lines.
    #
    # The cheek is the plane that is normal to the bend axis. When unrolled:
    #   - Inner edge (heel side) has radius r_heel = throat_radius_mm
    #   - Outer edge (throat side) has radius r_throat = throat_radius_mm + height_mm
    #   - The sector spans angle_deg
    #
    # We lay the sector out as a flat strip:
    #   x goes from 0 → angle_deg (in mm, scaled by mean radius)
    #   y goes from 0 → height_mm (radial direction)
    #
    # The "developed" representation keeps both edges parallel by rotating
    # them to horizontal (this is the standard fabricator's cheek layout).
    #
    # For each radial station i we compute arc position along the inner
    # and outer arcs and use those as x coordinates, making the panel shape
    # a trapezoid whose parallel sides are heel_arc and throat_arc.
    # ------------------------------------------------------------------
    cheek_left: Polygon = [
        (0.0, 0.0),                   # inner-heel start
        (heel_arc, 0.0),              # inner-heel end  (heel arc = inner edge)
        (throat_arc, height_mm),      # outer-throat end
        (0.0, height_mm),             # outer-throat start
    ]
    cheek_right: Polygon = list(cheek_left)  # symmetric

    return ElbowPattern(
        throat_plate=throat_plate,
        heel_plate=heel_plate,
        cheek_left=cheek_left,
        cheek_right=cheek_right,
        throat_arc_length_mm=throat_arc,
        heel_arc_length_mm=heel_arc,
        centre_arc_length_mm=centre_arc,
        angle_deg=angle_deg,
        width_mm=width_mm,
        height_mm=height_mm,
        throat_radius_mm=throat_radius_mm,
    )


# ---------------------------------------------------------------------------
# Reducer flat-pattern
# ---------------------------------------------------------------------------

@dataclass
class ReducerPattern:
    """Flat-pattern output for a rectangular duct reducer (concentric taper).

    Attributes:
        top_plate: Top face trapezoidal panel.
        bottom_plate: Bottom face trapezoidal panel.
        left_plate: Left side trapezoidal panel.
        right_plate: Right side trapezoidal panel.
        top_slant_length_mm: Developed (slant) length of top/bottom panels.
        side_slant_length_mm: Developed (slant) length of side panels.
        axial_length_mm: Straight-line axial length of reducer.
        width_upstream_mm: Upstream duct width.
        height_upstream_mm: Upstream duct height.
        width_downstream_mm: Downstream duct width.
        height_downstream_mm: Downstream duct height.
    """

    top_plate: Polygon
    bottom_plate: Polygon
    left_plate: Polygon
    right_plate: Polygon
    top_slant_length_mm: float
    side_slant_length_mm: float
    axial_length_mm: float
    width_upstream_mm: float
    height_upstream_mm: float
    width_downstream_mm: float
    height_downstream_mm: float


def rect_reducer_pattern(
    width_upstream_mm: float,
    height_upstream_mm: float,
    width_downstream_mm: float,
    height_downstream_mm: float,
    axial_length_mm: float,
) -> ReducerPattern:
    """Generate flat-pattern polygons for a rectangular duct reducer.

    The reducer is concentric (centre-line aligned).  Each of the four faces
    is a trapezoid.  The *slant length* (developed panel height from upstream
    to downstream edge) is computed analytically.

    Args:
        width_upstream_mm: Upstream duct width W1 (mm).
        height_upstream_mm: Upstream duct height H1 (mm).
        width_downstream_mm: Downstream duct width W2 (mm).
        height_downstream_mm: Downstream duct height H2 (mm).
        axial_length_mm: Axial (run) length of the reducer (mm).

    Returns:
        :class:`ReducerPattern` with all four flat panels and slant lengths.
    """
    W1, H1 = width_upstream_mm, height_upstream_mm
    W2, H2 = width_downstream_mm, height_downstream_mm
    L = axial_length_mm

    for name, v in [
        ("width_upstream_mm", W1),
        ("height_upstream_mm", H1),
        ("width_downstream_mm", W2),
        ("height_downstream_mm", H2),
        ("axial_length_mm", L),
    ]:
        if v <= 0:
            raise ValueError(f"{name} must be positive, got {v}")

    # Slant lengths: hypotenuse in the plane of each panel
    #   top/bottom slant: the taper in the height direction
    delta_h = (H1 - H2) / 2  # offset on each side
    top_slant = math.hypot(L, delta_h)

    #   side slant: the taper in the width direction
    delta_w = (W1 - W2) / 2
    side_slant = math.hypot(L, delta_w)

    # ------------------------------------------------------------------
    # Top plate: trapezoid with parallel sides W1 (bottom) and W2 (top).
    # Panel height = top_slant (the slant length, not L).
    # Layout: origin bottom-left, upstream edge = W1 wide at y=0,
    #         downstream edge = W2 wide centred at y=top_slant.
    #
    # Offset of downstream edge from upstream edge (centred):
    #   x_offset = (W1 - W2) / 2
    # ------------------------------------------------------------------
    x_off_top = (W1 - W2) / 2
    top_plate: Polygon = [
        (0.0, 0.0),
        (W1, 0.0),
        (W1 - x_off_top, top_slant),
        (x_off_top, top_slant),
    ]
    bottom_plate: Polygon = list(top_plate)  # same shape

    # ------------------------------------------------------------------
    # Side plate: trapezoid with parallel sides H1 (bottom) and H2 (top).
    # Panel height = side_slant.
    # ------------------------------------------------------------------
    x_off_side = (H1 - H2) / 2
    left_plate: Polygon = [
        (0.0, 0.0),
        (H1, 0.0),
        (H1 - x_off_side, side_slant),
        (x_off_side, side_slant),
    ]
    right_plate: Polygon = list(left_plate)  # symmetric

    return ReducerPattern(
        top_plate=top_plate,
        bottom_plate=bottom_plate,
        left_plate=left_plate,
        right_plate=right_plate,
        top_slant_length_mm=top_slant,
        side_slant_length_mm=side_slant,
        axial_length_mm=L,
        width_upstream_mm=W1,
        height_upstream_mm=H1,
        width_downstream_mm=W2,
        height_downstream_mm=H2,
    )
