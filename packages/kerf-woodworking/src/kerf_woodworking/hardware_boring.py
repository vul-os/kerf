"""
kerf_woodworking.hardware_boring — Cabinet hardware bore-pattern generator.

Produces bore-pattern layouts (hole positions and diameters) for common
cabinet hardware, following the 32 mm system (System 32) conventions used
in European flat-pack and CNC-machined cabinetry.

The 32 mm system places all functional holes on a 32 mm grid:
  - 5 mm diameter × 11 mm deep system holes on a 32 mm pitch along a vertical
    line 37 mm from the front edge (for hinges, drawer runners, shelf pins).
  - Hardware-specific pilot holes offset from the system holes.

References
----------
Blum Inc. (2024). MINIPRESS / DYNAPRO drilling specifications.
    https://www.blum.com/us/en/products/hingesystems/
Häfele (2024). System 32 boring pattern technical guide.
    https://www.hafele.com/
AWI (Architectural Woodwork Institute) Quality Standards 9th ed., §11
    Cabinet hardware boring tolerances.

Hardware modelled
-----------------
hinge_cup        — 35 mm cup hinge (Blum Clip-Top, Grass, Salice compatible)
drawer_runner    — undermount or side-mount drawer runner (Blum Movento / Tandem)
shelf_pin        — 5 mm shelf-pin socket holes (4-hole pattern per shelf)
euro_screw       — 7 mm Euro screw / confirmat pattern (RTA panel joints)
handles_rail     — Handle/rail drilling (96, 128, 160, 192, 224, 256 mm centres)

All coordinates are in mm.  Origin (0, 0) is at the bottom-left corner of
the panel face being bored.

Public API
----------
``hinge_cup_pattern(panel_height, overlay, count, ...)    -> BorePattern``
``drawer_runner_pattern(panel_height, drawer_height, ...) -> BorePattern``
``shelf_pin_pattern(panel_height, num_positions, ...)     -> BorePattern``
``euro_screw_pattern(panel_thickness, ...)                -> BorePattern``
``handle_pattern(centres_mm, ...)                         -> BorePattern``
``BoreHole``        — dataclass: x, y, diameter, depth, kind
``BorePattern``     — dataclass: holes list, panel context, warnings
``bore_pattern_to_dict(pattern)  -> dict``
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Constants — 32 mm System
# ---------------------------------------------------------------------------

# Standard system-hole pitch
SYSTEM_32_PITCH = 32.0        # mm

# Standard system-hole specifications (5 × 11 per System 32)
SYSTEM_HOLE_DIA   = 5.0       # mm
SYSTEM_HOLE_DEPTH = 11.0      # mm

# Distance from panel front edge to first system-hole row
FRONT_EDGE_OFFSET = 37.0      # mm (37 mm from front face)
# Distance from panel back edge to second system-hole row
BACK_EDGE_OFFSET  = 37.0      # mm

# Hinge cup: 35 mm Ø cup, 13 mm deep (standard concealed hinge)
HINGE_CUP_DIA   = 35.0        # mm
HINGE_CUP_DEPTH = 13.0        # mm

# Standard hinge arm pilot holes
HINGE_PILOT_DIA   = 3.5       # mm (screw pilot)
HINGE_PILOT_DEPTH = 13.0      # mm

# Confirmat / Euro screw: 7 mm Ø through-hole in edge, pilot in face
EURO_SCREW_DIA_EDGE  = 7.0    # mm
EURO_SCREW_DIA_FACE  = 5.0    # mm
EURO_SCREW_DEPTH     = 50.0   # mm


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class BoreHole:
    """
    A single bore hole.

    Attributes
    ----------
    x : float
        X position on the panel face (mm from left edge).
    y : float
        Y position on the panel face (mm from bottom edge).
    diameter_mm : float
        Drill bit diameter (mm).
    depth_mm : float
        Bore depth (mm).
    kind : str
        Semantic label: "system" | "hinge_cup" | "hinge_pilot" |
        "drawer_pilot" | "shelf_pin" | "euro_screw" | "handle_pilot".
    label : str
        Human-readable label (e.g. "Hinge cup 1 centre").
    """
    x: float
    y: float
    diameter_mm: float
    depth_mm: float
    kind: str
    label: str = ""


@dataclass
class BorePattern:
    """
    A complete bore-pattern layout for one panel face.

    Attributes
    ----------
    holes : list[BoreHole]
        All holes in the pattern.
    panel_width_mm : float
        Width of the panel (mm) — the horizontal dimension being bored.
    panel_height_mm : float
        Height / length of the panel (mm).
    panel_thickness_mm : float
        Thickness of the panel (mm).
    hardware_type : str
        Name of the hardware this pattern serves.
    warnings : list[str]
        Engineering warnings.
    """
    holes: list[BoreHole] = field(default_factory=list)
    panel_width_mm: float = 0.0
    panel_height_mm: float = 0.0
    panel_thickness_mm: float = 18.0
    hardware_type: str = ""
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snap_to_32(y: float, origin: float = 0.0) -> float:
    """Round y to the nearest 32 mm grid position relative to origin."""
    offset = y - origin
    snapped = round(offset / SYSTEM_32_PITCH) * SYSTEM_32_PITCH
    return origin + snapped


def _check_edge_clearance(hole: BoreHole, panel_w: float, panel_h: float, min_clearance: float = 3.0):
    """Return a warning string if the hole centre is too close to a panel edge, or '' if OK."""
    if hole.x < min_clearance or hole.x > panel_w - min_clearance:
        return f"Hole '{hole.label}' at x={hole.x:.1f} is within {min_clearance} mm of panel edge."
    if hole.y < min_clearance or hole.y > panel_h - min_clearance:
        return f"Hole '{hole.label}' at y={hole.y:.1f} is within {min_clearance} mm of panel edge."
    return ""


# ---------------------------------------------------------------------------
# Hinge cup pattern
# ---------------------------------------------------------------------------

def hinge_cup_pattern(
    panel_height_mm: float,
    panel_width_mm: float = 600.0,
    panel_thickness_mm: float = 18.0,
    *,
    overlay_mm: float = 0.0,
    count: int = 2,
    door_height_mm: Optional[float] = None,
    inset: bool = False,
) -> BorePattern:
    """
    Generate hinge-cup bore positions for a door panel.

    Follows Blum Clip-Top / INSERTA hinge cup positioning:
    - 35 mm cup, 13 mm deep, centred on the door stile.
    - Cup centre is 22.5 mm from the door edge (hinge stile).
    - Top hinge: 80–100 mm from door top edge (first grid position above 80 mm).
    - Bottom hinge: 80–100 mm from door bottom edge.
    - Middle hinges (if count > 2): evenly spaced between top and bottom.

    Parameters
    ----------
    panel_height_mm : float
        Height of the door panel (mm).
    panel_width_mm : float
        Width of the door panel (mm).  Default 600 mm.
    panel_thickness_mm : float
        Door thickness (mm).  Default 18 mm.
    overlay_mm : float
        Overlay of door over cabinet carcase (mm).  0 = full-inset.
        Typical: 9.5 mm (half overlay), 19 mm (full overlay).
    count : int
        Number of hinges.  Minimum 2.  Recommended: 2 for doors ≤ 1000 mm,
        3 for 1000–1500 mm, 4 for > 1500 mm.
    door_height_mm : float or None
        Deprecated alias for panel_height_mm (kept for backward compat).
    inset : bool
        True = full-inset hinge geometry (cup offset changes slightly).

    Returns
    -------
    BorePattern
    """
    if door_height_mm is not None:
        panel_height_mm = door_height_mm

    if panel_height_mm <= 0 or panel_width_mm <= 0:
        raise ValueError("Panel dimensions must be positive")
    if count < 1:
        raise ValueError("count must be >= 1")

    warnings_out: list[str] = []

    # Recommend minimum hinge count
    if panel_height_mm > 1500 and count < 4:
        warnings_out.append(
            f"Door height {panel_height_mm:.0f} mm > 1500 mm; recommend at least 4 hinges."
        )
    elif panel_height_mm > 1000 and count < 3:
        warnings_out.append(
            f"Door height {panel_height_mm:.0f} mm > 1000 mm; recommend at least 3 hinges."
        )

    # Cup centre X: 22.5 mm from hinge stile (left edge of door)
    # For overlay doors, cup centre is typically 22.5 mm from panel edge.
    # For inset doors, it shifts by the overlay amount.
    cup_x = 22.5

    # Hinge positions (Y from bottom of door)
    # Top hinge: first 32 mm position ≥ 80 mm from top → snap up from (H - 80)
    top_hinge_nominal = panel_height_mm - 80.0
    bottom_hinge_nominal = 80.0

    # Snap to nearest 32 mm grid above the minimum edge offset
    top_hinge_y    = max(top_hinge_nominal, 64.0)
    bottom_hinge_y = min(bottom_hinge_nominal, panel_height_mm - 64.0)

    if count == 1:
        hinge_ys = [panel_height_mm / 2.0]
    elif count == 2:
        hinge_ys = [bottom_hinge_y, top_hinge_y]
    else:
        # Evenly distribute middle hinges
        step = (top_hinge_y - bottom_hinge_y) / (count - 1)
        hinge_ys = [bottom_hinge_y + i * step for i in range(count)]

    holes: list[BoreHole] = []

    for i, hy in enumerate(hinge_ys):
        label_idx = i + 1
        # Cup hole
        holes.append(BoreHole(
            x=cup_x,
            y=hy,
            diameter_mm=HINGE_CUP_DIA,
            depth_mm=HINGE_CUP_DEPTH,
            kind="hinge_cup",
            label=f"Hinge cup {label_idx} centre",
        ))
        # Pilot holes — 45 mm apart (standard Blum two-screw arm)
        # Pilots are at cup_x ± 22.5 mm in Y from the cup centre,
        # using the system-hole size.
        for dy, plabel in [(-22.5, "pilot_lower"), (22.5, "pilot_upper")]:
            pilot_y = hy + dy
            if 0 <= pilot_y <= panel_height_mm:
                holes.append(BoreHole(
                    x=cup_x,
                    y=pilot_y,
                    diameter_mm=HINGE_PILOT_DIA,
                    depth_mm=HINGE_PILOT_DEPTH,
                    kind="hinge_pilot",
                    label=f"Hinge {label_idx} arm {plabel}",
                ))

    # Edge clearance checks
    for hole in holes:
        warn = _check_edge_clearance(hole, panel_width_mm, panel_height_mm, min_clearance=10.0)
        if warn:
            warnings_out.append(warn)

    return BorePattern(
        holes=holes,
        panel_width_mm=panel_width_mm,
        panel_height_mm=panel_height_mm,
        panel_thickness_mm=panel_thickness_mm,
        hardware_type="hinge_cup",
        warnings=warnings_out,
    )


# ---------------------------------------------------------------------------
# Drawer runner pattern
# ---------------------------------------------------------------------------

def drawer_runner_pattern(
    panel_height_mm: float,
    drawer_height_mm: float,
    panel_width_mm: float = 600.0,
    panel_thickness_mm: float = 18.0,
    *,
    runner_type: str = "undermount",
    num_drawers: int = 1,
    drawer_gap_mm: float = 4.0,
) -> BorePattern:
    """
    Generate drawer runner pilot-hole positions on the cabinet side panel.

    Supports:
    - ``undermount`` (Blum Movento / Tandem): two pilot holes per side,
      one at the front and one at the rear of the runner, 11 mm from the
      bottom of the drawer opening.
    - ``sidemount``: pilot holes at the middle height of the drawer opening,
      one at the front (87 mm from face) and one at the rear.

    Parameters
    ----------
    panel_height_mm : float
        Height of the cabinet side panel (mm).
    drawer_height_mm : float
        Height of a single drawer box (mm), not the face height.
    panel_width_mm : float
        Width (depth) of the cabinet (mm).
    panel_thickness_mm : float
        Panel thickness (mm).
    runner_type : str
        "undermount" or "sidemount".
    num_drawers : int
        Number of drawers (default 1).
    drawer_gap_mm : float
        Gap between adjacent drawer openings (mm, default 4 mm).

    Returns
    -------
    BorePattern
    """
    if panel_height_mm <= 0 or drawer_height_mm <= 0:
        raise ValueError("Panel and drawer heights must be positive")
    if runner_type not in ("undermount", "sidemount"):
        raise ValueError(f"runner_type must be 'undermount' or 'sidemount', got '{runner_type}'")

    warnings_out: list[str] = []
    holes: list[BoreHole] = []

    # Compute drawer bottom Y positions from the bottom of the panel up
    # The first drawer base starts at the bottom rail height (typically 96 mm
    # from the bottom for the first runner — snapped to 32 mm grid).
    first_runner_y = _snap_to_32(96.0, origin=0.0)  # 96 → nearest 32n = 96

    for d_idx in range(num_drawers):
        # Bottom of this drawer box opening
        box_bottom_y = first_runner_y + d_idx * (drawer_height_mm + drawer_gap_mm)
        box_top_y    = box_bottom_y + drawer_height_mm

        if box_top_y > panel_height_mm:
            warnings_out.append(
                f"Drawer {d_idx + 1}: drawer top {box_top_y:.0f} mm exceeds "
                f"panel height {panel_height_mm:.0f} mm."
            )

        if runner_type == "undermount":
            # Runner sits on the bottom of the drawer opening
            runner_y = box_bottom_y + 11.0  # 11 mm above the runner seating ledge
            # Front pilot: 87 mm from front face
            # Rear pilot:  panel_width - 87 mm from front face (or 37 mm from rear)
            front_x = 87.0
            rear_x  = panel_width_mm - 37.0
            for x, lbl in [(front_x, "front"), (rear_x, "rear")]:
                holes.append(BoreHole(
                    x=x,
                    y=runner_y,
                    diameter_mm=SYSTEM_HOLE_DIA,
                    depth_mm=SYSTEM_HOLE_DEPTH,
                    kind="drawer_pilot",
                    label=f"Drawer {d_idx + 1} {runner_type} runner {lbl}",
                ))
        else:
            # Sidemount: pilot holes at mid drawer height
            runner_y = box_bottom_y + drawer_height_mm / 2.0
            front_x = 87.0
            rear_x  = panel_width_mm - 37.0
            for x, lbl in [(front_x, "front"), (rear_x, "rear")]:
                holes.append(BoreHole(
                    x=x,
                    y=runner_y,
                    diameter_mm=SYSTEM_HOLE_DIA,
                    depth_mm=SYSTEM_HOLE_DEPTH,
                    kind="drawer_pilot",
                    label=f"Drawer {d_idx + 1} {runner_type} runner {lbl}",
                ))

    return BorePattern(
        holes=holes,
        panel_width_mm=panel_width_mm,
        panel_height_mm=panel_height_mm,
        panel_thickness_mm=panel_thickness_mm,
        hardware_type=f"drawer_runner_{runner_type}",
        warnings=warnings_out,
    )


# ---------------------------------------------------------------------------
# Shelf-pin pattern
# ---------------------------------------------------------------------------

def shelf_pin_pattern(
    panel_height_mm: float,
    panel_width_mm: float = 600.0,
    panel_thickness_mm: float = 18.0,
    *,
    num_positions: int = 10,
    start_y_mm: float = 96.0,
    end_y_mm: Optional[float] = None,
    front_offset_mm: float = FRONT_EDGE_OFFSET,
    back_offset_mm:  float = BACK_EDGE_OFFSET,
) -> BorePattern:
    """
    Generate 5 mm shelf-pin socket holes on 32 mm pitch.

    Two vertical rows of holes are placed:
    - Front row: ``front_offset_mm`` from the front edge of the panel.
    - Rear row:  ``panel_width_mm - back_offset_mm`` from the front edge.

    Each row has ``num_positions`` holes spaced 32 mm apart, starting at
    ``start_y_mm`` from the panel bottom and ending at ``end_y_mm``
    (default = panel_height - start_y_mm, symmetric).

    Parameters
    ----------
    panel_height_mm : float
        Height of the cabinet side panel (mm).
    panel_width_mm : float
        Depth of the cabinet (mm) — panel width when laid flat for boring.
    panel_thickness_mm : float
        Panel thickness (mm).
    num_positions : int
        Number of shelf-pin positions per row (default 10).
    start_y_mm : float
        Y position of the first shelf-pin hole from the bottom (mm).
    end_y_mm : float or None
        Y position of the last hole.  If None, computed from num_positions.
    front_offset_mm : float
        X position of the front hole row from the front edge (mm).
    back_offset_mm : float
        Distance from the rear edge for the rear hole row (mm).

    Returns
    -------
    BorePattern
    """
    if panel_height_mm <= 0 or panel_width_mm <= 0:
        raise ValueError("Panel dimensions must be positive")
    if num_positions < 1:
        raise ValueError("num_positions must be >= 1")

    warnings_out: list[str] = []
    holes: list[BoreHole] = []

    # Snap start to 32 mm grid
    start_y = _snap_to_32(start_y_mm)
    if end_y_mm is None:
        end_y = start_y + (num_positions - 1) * SYSTEM_32_PITCH
    else:
        end_y = end_y_mm

    if end_y > panel_height_mm - 32.0:
        warnings_out.append(
            f"Shelf-pin row end {end_y:.0f} mm may be too close to the top of "
            f"panel ({panel_height_mm:.0f} mm)."
        )

    front_x = front_offset_mm
    rear_x  = panel_width_mm - back_offset_mm

    y = start_y
    pos = 0
    while y <= end_y + 0.5 and pos < num_positions:
        for x, row_label in [(front_x, "front"), (rear_x, "rear")]:
            holes.append(BoreHole(
                x=x,
                y=y,
                diameter_mm=SYSTEM_HOLE_DIA,
                depth_mm=SYSTEM_HOLE_DEPTH,
                kind="shelf_pin",
                label=f"Shelf pin row={row_label} pos={pos + 1} y={y:.0f}",
            ))
        y += SYSTEM_32_PITCH
        pos += 1

    return BorePattern(
        holes=holes,
        panel_width_mm=panel_width_mm,
        panel_height_mm=panel_height_mm,
        panel_thickness_mm=panel_thickness_mm,
        hardware_type="shelf_pin",
        warnings=warnings_out,
    )


# ---------------------------------------------------------------------------
# Euro-screw (confirmat) pattern
# ---------------------------------------------------------------------------

def euro_screw_pattern(
    panel_width_mm: float,
    panel_height_mm: float,
    panel_thickness_mm: float = 18.0,
    *,
    edge: str = "bottom",
    spacing_mm: float = 128.0,
    count: int = 2,
) -> BorePattern:
    """
    Generate Confirmat / Euro-screw face-hole positions for RTA panel joints.

    A confirmat screw joins two panels at 90°. One panel gets a 7 mm through-
    hole in its edge; the mating panel gets a 5 mm pilot hole in its face.

    Parameters
    ----------
    panel_width_mm : float
        Width of the panel (mm) in the joining direction.
    panel_height_mm : float
        Height of the panel (mm).
    panel_thickness_mm : float
        Panel thickness (mm).
    edge : str
        Which edge is being joined: "bottom" | "top" | "left" | "right".
    spacing_mm : float
        Centre-to-centre spacing between screws (mm, default 128 mm).
    count : int
        Number of screws (default 2).

    Returns
    -------
    BorePattern
    """
    if panel_width_mm <= 0 or panel_height_mm <= 0:
        raise ValueError("Panel dimensions must be positive")
    if count < 1:
        raise ValueError("count must be >= 1")
    if edge not in ("bottom", "top", "left", "right"):
        raise ValueError(f"edge must be bottom/top/left/right, got '{edge}'")

    warnings_out: list[str] = []
    holes: list[BoreHole] = []

    # Hole depth in face = panel_thickness_mm (full thickness for pilot)
    pilot_depth = panel_thickness_mm

    # Determine hole row position along the panel
    if edge == "bottom":
        y_row = panel_thickness_mm / 2.0   # centre of the face at the bottom edge
        x_start = (panel_width_mm - (count - 1) * spacing_mm) / 2.0
        for i in range(count):
            x = x_start + i * spacing_mm
            holes.append(BoreHole(
                x=x, y=y_row,
                diameter_mm=EURO_SCREW_DIA_FACE,
                depth_mm=pilot_depth,
                kind="euro_screw",
                label=f"Confirmat face pilot {i + 1} (bottom edge)",
            ))
    elif edge == "top":
        y_row = panel_height_mm - panel_thickness_mm / 2.0
        x_start = (panel_width_mm - (count - 1) * spacing_mm) / 2.0
        for i in range(count):
            x = x_start + i * spacing_mm
            holes.append(BoreHole(
                x=x, y=y_row,
                diameter_mm=EURO_SCREW_DIA_FACE,
                depth_mm=pilot_depth,
                kind="euro_screw",
                label=f"Confirmat face pilot {i + 1} (top edge)",
            ))
    elif edge == "left":
        x_row = panel_thickness_mm / 2.0
        y_start = (panel_height_mm - (count - 1) * spacing_mm) / 2.0
        for i in range(count):
            y = y_start + i * spacing_mm
            holes.append(BoreHole(
                x=x_row, y=y,
                diameter_mm=EURO_SCREW_DIA_FACE,
                depth_mm=pilot_depth,
                kind="euro_screw",
                label=f"Confirmat face pilot {i + 1} (left edge)",
            ))
    else:  # right
        x_row = panel_width_mm - panel_thickness_mm / 2.0
        y_start = (panel_height_mm - (count - 1) * spacing_mm) / 2.0
        for i in range(count):
            y = y_start + i * spacing_mm
            holes.append(BoreHole(
                x=x_row, y=y,
                diameter_mm=EURO_SCREW_DIA_FACE,
                depth_mm=pilot_depth,
                kind="euro_screw",
                label=f"Confirmat face pilot {i + 1} (right edge)",
            ))

    # Edge clearance
    for hole in holes:
        warn = _check_edge_clearance(hole, panel_width_mm, panel_height_mm, min_clearance=8.0)
        if warn:
            warnings_out.append(warn)

    return BorePattern(
        holes=holes,
        panel_width_mm=panel_width_mm,
        panel_height_mm=panel_height_mm,
        panel_thickness_mm=panel_thickness_mm,
        hardware_type="euro_screw",
        warnings=warnings_out,
    )


# ---------------------------------------------------------------------------
# Handle / rail drilling
# ---------------------------------------------------------------------------

def handle_pattern(
    panel_width_mm: float,
    panel_height_mm: float,
    panel_thickness_mm: float = 18.0,
    *,
    centres_mm: float = 128.0,
    orientation: str = "horizontal",
    offset_from_edge_mm: float = 40.0,
    edge: str = "top",
    count: int = 1,
) -> BorePattern:
    """
    Generate handle / rail through-hole positions.

    Parameters
    ----------
    panel_width_mm : float
        Panel width (mm).
    panel_height_mm : float
        Panel height (mm).
    panel_thickness_mm : float
        Panel thickness (mm).
    centres_mm : float
        Centre-to-centre spacing of handle holes (mm).
        Common values: 32, 64, 96, 128, 160, 192, 224, 256, 320, 384, 448 mm.
    orientation : str
        "horizontal" = handle holes side by side;
        "vertical"   = handle holes stacked vertically.
    offset_from_edge_mm : float
        Distance from the chosen edge to the nearer handle hole (mm).
    edge : str
        "top" | "bottom" | "left" | "right" — edge the handle is near.
    count : int
        Number of handles (default 1).

    Returns
    -------
    BorePattern
    """
    if panel_width_mm <= 0 or panel_height_mm <= 0:
        raise ValueError("Panel dimensions must be positive")
    if centres_mm <= 0:
        raise ValueError("centres_mm must be positive")
    if edge not in ("top", "bottom", "left", "right"):
        raise ValueError(f"edge must be top/bottom/left/right, got '{edge}'")

    warnings_out: list[str] = []
    holes: list[BoreHole] = []

    # Handle through-holes: 5 mm Ø (M4 screw) — standard
    handle_dia   = 5.0
    handle_depth = panel_thickness_mm  # through the panel

    for h_idx in range(count):
        if orientation == "horizontal":
            if edge == "top":
                y_base = panel_height_mm - offset_from_edge_mm
            elif edge == "bottom":
                y_base = offset_from_edge_mm
            else:
                y_base = panel_height_mm / 2.0

            x_centre = panel_width_mm / 2.0
            x1 = x_centre - centres_mm / 2.0 + h_idx * (centres_mm + 10.0)
            x2 = x_centre + centres_mm / 2.0 + h_idx * (centres_mm + 10.0)

            for x, lbl in [(x1, "left"), (x2, "right")]:
                holes.append(BoreHole(
                    x=x, y=y_base,
                    diameter_mm=handle_dia,
                    depth_mm=handle_depth,
                    kind="handle_pilot",
                    label=f"Handle {h_idx + 1} {lbl} hole",
                ))
        else:  # vertical
            if edge == "right":
                x_base = panel_width_mm - offset_from_edge_mm
            elif edge == "left":
                x_base = offset_from_edge_mm
            else:
                x_base = panel_width_mm / 2.0

            y_centre = panel_height_mm / 2.0
            y1 = y_centre - centres_mm / 2.0 + h_idx * (centres_mm + 10.0)
            y2 = y_centre + centres_mm / 2.0 + h_idx * (centres_mm + 10.0)

            for y, lbl in [(y1, "lower"), (y2, "upper")]:
                holes.append(BoreHole(
                    x=x_base, y=y,
                    diameter_mm=handle_dia,
                    depth_mm=handle_depth,
                    kind="handle_pilot",
                    label=f"Handle {h_idx + 1} {lbl} hole",
                ))

    for hole in holes:
        warn = _check_edge_clearance(hole, panel_width_mm, panel_height_mm, min_clearance=5.0)
        if warn:
            warnings_out.append(warn)

    return BorePattern(
        holes=holes,
        panel_width_mm=panel_width_mm,
        panel_height_mm=panel_height_mm,
        panel_thickness_mm=panel_thickness_mm,
        hardware_type="handle",
        warnings=warnings_out,
    )


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def bore_pattern_to_dict(pattern: BorePattern) -> dict:
    """Serialise a BorePattern to a plain JSON-safe dict."""
    return {
        "hardware_type":       pattern.hardware_type,
        "panel_width_mm":      pattern.panel_width_mm,
        "panel_height_mm":     pattern.panel_height_mm,
        "panel_thickness_mm":  pattern.panel_thickness_mm,
        "hole_count":          len(pattern.holes),
        "holes": [
            {
                "x":           round(h.x, 3),
                "y":           round(h.y, 3),
                "diameter_mm": h.diameter_mm,
                "depth_mm":    h.depth_mm,
                "kind":        h.kind,
                "label":       h.label,
            }
            for h in pattern.holes
        ],
        "warnings": pattern.warnings,
    }
