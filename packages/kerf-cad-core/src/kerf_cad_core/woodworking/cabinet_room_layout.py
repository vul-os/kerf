"""
kerf_cad_core.woodworking.cabinet_room_layout — Room layout + cabinet placement + collision.

Implements a first-fit-decreasing (FFD) bin-packing algorithm to place standard-
sized cabinet units along selected walls of a room polygon, respecting door and
window clearances.

Design references
-----------------
  NKBA (National Kitchen and Bath Association) Planning Guidelines 2021:
    Guideline 5  — minimum 36″ (914 mm) clearance between countertop edges
    Guideline 13 — base cabinet standard depth 600 mm; wall cabinet 300 mm
    Guideline 14 — upper cabinet height 420–760 mm

  ANSI A117.1-2017 §1003 (Accessible Kitchen Design):
    §1003.12.1 — minimum 1524 mm (60″) turning radius in kitchen
    §1003.12.3 — work-surface knee clearance 660 mm × 280 mm × 685 mm

  Mozaik Cabinet Software (mozaikCabinet.com), Cabinet Design Manual §3:
    Cabinet line placement follows wall-span segments; corner logic uses a
    blind-corner unit or L-corner unit at each internal corner.

All coordinates are in metres.  Polygon winding: CCW positive area.

Author: imranparuk
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Room:
    """Room definition — a closed polygon with ceiling height and wall openings.

    outline: closed polygon vertices in metres (list of (x, y) tuples).
             The polygon is treated as CCW when area is positive.
    openings: list of dicts with keys:
        type         : 'door' | 'window'
        wall_index   : 0-based index of the wall segment (vertex[i] → vertex[i+1])
        position_m   : distance from the start vertex of that wall (in metres)
        width_m      : opening width (metres)
        height_m     : opening height from floor (metres)
    """
    name: str
    outline: list[tuple[float, float]]
    ceiling_height_m: float
    openings: list[dict] = field(default_factory=list)


@dataclass
class CabinetUnit:
    """Standard cabinet unit.

    NKBA Guideline 13: base cabinet depth 600 mm, wall cabinet depth 300 mm.
    kind: 'base' | 'wall' | 'tall' | 'corner'
    """
    sku: str
    width_m: float
    depth_m: float
    height_m: float
    kind: str = "base"   # 'base' | 'wall' | 'tall' | 'corner'


@dataclass
class CabinetPlacement:
    """A cabinet unit placed at a specific position in the room.

    position: (x, y, z) in metres.  z=0 for base/wall.
    rotation_deg: rotation around Z-axis (degrees).  0° = cabinet face toward +Y.
    """
    unit: CabinetUnit
    position: tuple[float, float, float]
    rotation_deg: float


@dataclass
class CabinetLayoutReport:
    """Summary of a cabinet auto-layout run.

    NKBA planning guidelines: total_lineal_meters should be ≥ 3 m for
    functional kitchen storage (Guideline 15 counter-space requirement).
    """
    room: Room
    placements: list[CabinetPlacement]
    n_units: int
    total_lineal_meters: float          # sum of all placed unit widths along walls
    waste_corner_count: int             # gaps too narrow for the smallest unit
    collision_count: int                # overlapping placements (should be 0)
    door_window_clearance_ok: bool


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------

def _polygon_area_signed(pts: list[tuple[float, float]]) -> float:
    """Signed shoelace area (positive = CCW)."""
    n = len(pts)
    a = 0.0
    for i in range(n):
        xi, yi = pts[i]
        xj, yj = pts[(i + 1) % n]
        a += xi * yj - xj * yi
    return a / 2.0


def _wall_segments(outline: list[tuple[float, float]]) -> list[tuple[
    tuple[float, float], tuple[float, float], float
]]:
    """Return list of (p0, p1, length) for each wall segment."""
    n = len(outline)
    segs = []
    for i in range(n):
        p0 = outline[i]
        p1 = outline[(i + 1) % n]
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        segs.append((p0, p1, math.hypot(dx, dy)))
    return segs


def _wall_unit_vector(p0: tuple[float, float], p1: tuple[float, float]) -> tuple[float, float]:
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    d = math.hypot(dx, dy)
    if d < 1e-12:
        return (1.0, 0.0)
    return (dx / d, dy / d)


def _wall_angle_deg(p0: tuple[float, float], p1: tuple[float, float]) -> float:
    """Angle (degrees) of the wall direction vector from +X axis."""
    ux, uy = _wall_unit_vector(p0, p1)
    return math.degrees(math.atan2(uy, ux))


def _blocked_spans(
    wall_idx: int,
    wall_len: float,
    openings: list[dict],
    clearance: float,
) -> list[tuple[float, float]]:
    """Return list of (start, end) blocked intervals on a wall, including clearance.

    NKBA Guideline 5 / Mozaik §3: cabinets must maintain clearance_m to each
    side of any door or window opening.
    """
    blocked = []
    for op in openings:
        if op.get("wall_index") != wall_idx:
            continue
        pos = float(op.get("position_m", 0.0))
        w = float(op.get("width_m", 0.0))
        # NKBA: clearance each side
        start = max(0.0, pos - clearance)
        end = min(wall_len, pos + w + clearance)
        if end > start:
            blocked.append((start, end))
    # merge overlapping
    blocked.sort()
    merged: list[tuple[float, float]] = []
    for s, e in blocked:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _free_spans(
    wall_len: float,
    blocked: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Return free (unblocked) spans on a wall of length wall_len."""
    free = []
    cursor = 0.0
    for bs, be in blocked:
        if bs > cursor:
            free.append((cursor, bs))
        cursor = max(cursor, be)
    if cursor < wall_len:
        free.append((cursor, wall_len))
    return [(s, e) for s, e in free if e - s > 1e-6]


def _pack_units_in_span(
    span_len: float,
    units: list[CabinetUnit],
    smallest_unit_width: float,
) -> tuple[list[CabinetUnit], int]:
    """First-fit-decreasing bin-packing along a 1-D span.

    Args:
        span_len: available wall length (metres)
        units: sorted list of cabinet units (decreasing width)
        smallest_unit_width: width of the smallest unit (for waste counting)

    Returns:
        (placed_units, waste_corners) where waste_corners counts remaining gaps
        too narrow for even the smallest unit.
    """
    placed: list[CabinetUnit] = []
    remaining = span_len
    # Sort units decreasing width (FFD)
    sorted_units = sorted(units, key=lambda u: -u.width_m)

    for unit in sorted_units:
        while remaining >= unit.width_m - 1e-9:
            placed.append(unit)
            remaining -= unit.width_m

    waste_corners = 1 if remaining > 1e-6 and remaining < smallest_unit_width else 0
    return placed, waste_corners


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def auto_layout_cabinets(
    room: Room,
    cabinet_library: list[CabinetUnit],
    along_walls: list[int] | None = None,
    min_clearance_to_openings_m: float = 0.15,
) -> CabinetLayoutReport:
    """Pack standard-sized cabinets along selected walls, leaving clearance to doors/windows.

    Algorithm: first-fit-decreasing (FFD) bin-packing along each wall span.
    For each selected wall:
      1. Compute blocked intervals from openings + clearance (NKBA Guideline 5)
      2. Derive free spans
      3. FFD-pack the cabinet library into each free span
      4. Place cabinets at their positions in world space

    NKBA Planning Guidelines 2021:
      Guideline 5   — clearance to door/window openings
      Guideline 13  — base cabinet depth 600 mm standard
      Guideline 15  — minimum 3.0 m lineal counter space recommended

    ANSI A117.1-2017 §1003.12 — accessible kitchen turning radius 1524 mm.
    Mozaik Cabinet Software §3 — wall-span placement with blind-corner logic.

    Args:
        room: Room definition with outline polygon and openings
        cabinet_library: list of available CabinetUnit types
        along_walls: list of wall indices to pack (default: all walls)
        min_clearance_to_openings_m: clearance each side of openings in metres

    Returns:
        CabinetLayoutReport with placement list and metrics
    """
    if not cabinet_library:
        return CabinetLayoutReport(
            room=room, placements=[], n_units=0,
            total_lineal_meters=0.0, waste_corner_count=0,
            collision_count=0, door_window_clearance_ok=True,
        )

    segments = _wall_segments(room.outline)
    n_walls = len(segments)
    if along_walls is None:
        along_walls = list(range(n_walls))

    smallest_w = min(u.width_m for u in cabinet_library)
    # Corner margin: reserve cabinet depth at each wall end to avoid overlap with
    # cabinets on adjacent walls (Mozaik Cabinet Software §3 blind-corner clearance).
    max_depth = max(u.depth_m for u in cabinet_library)
    corner_margin = max_depth

    placements: list[CabinetPlacement] = []
    total_lineal = 0.0
    total_waste = 0

    for wall_idx in along_walls:
        if wall_idx >= n_walls:
            continue
        p0, p1, wall_len = segments[wall_idx]
        ux, uy = _wall_unit_vector(p0, p1)
        angle = _wall_angle_deg(p0, p1)

        # Direction inward (normal pointing into room)
        # For CCW polygon, inward normal = rotate wall direction 90° CCW
        nx, ny = -uy, ux

        # Check whether adjacent walls are also being packed — if so, reserve corner margin.
        prev_wall = (wall_idx - 1) % n_walls
        next_wall = (wall_idx + 1) % n_walls
        start_margin = corner_margin if prev_wall in along_walls else 0.0
        end_margin = corner_margin if next_wall in along_walls else 0.0

        # Apply corner margins as additional blocked spans at wall ends
        corner_blocked: list[tuple[float, float]] = []
        if start_margin > 0.0:
            corner_blocked.append((0.0, start_margin))
        if end_margin > 0.0:
            corner_blocked.append((wall_len - end_margin, wall_len))

        # Merge opening-blocked spans with corner-blocked spans
        all_blocked = sorted(
            _blocked_spans(wall_idx, wall_len, room.openings, min_clearance_to_openings_m)
            + corner_blocked
        )
        merged_blocked: list[tuple[float, float]] = []
        for s, e in all_blocked:
            if merged_blocked and s <= merged_blocked[-1][1]:
                merged_blocked[-1] = (merged_blocked[-1][0], max(merged_blocked[-1][1], e))
            else:
                merged_blocked.append((s, e))

        free_spans = _free_spans(wall_len, merged_blocked)

        for span_start, span_end in free_spans:
            span_len = span_end - span_start
            if span_len < smallest_w - 1e-9:
                total_waste += 1
                continue

            # Filter units that fit the span at all
            fitting = [u for u in cabinet_library if u.width_m <= span_len + 1e-9]
            if not fitting:
                total_waste += 1
                continue

            packed, waste = _pack_units_in_span(span_len, fitting, smallest_w)
            total_waste += waste

            cursor = span_start
            for unit in packed:
                # Position: CENTRE of cabinet footprint (along-wall centre + half-depth inward)
                along = cursor + unit.width_m / 2.0
                px = p0[0] + ux * along + nx * (unit.depth_m / 2.0)
                py = p0[1] + uy * along + ny * (unit.depth_m / 2.0)
                placements.append(CabinetPlacement(
                    unit=unit,
                    position=(round(px, 6), round(py, 6), 0.0),
                    rotation_deg=round(angle, 3),
                ))
                cursor += unit.width_m
                total_lineal += unit.width_m

    # Check door/window clearance compliance
    clearance_ok = _check_door_window_clearances(placements, room, min_clearance_to_openings_m)

    # Detect collisions
    collision_pairs = detect_cabinet_collisions(placements)

    return CabinetLayoutReport(
        room=room,
        placements=placements,
        n_units=len(placements),
        total_lineal_meters=round(total_lineal, 4),
        waste_corner_count=total_waste,
        collision_count=len(collision_pairs),
        door_window_clearance_ok=clearance_ok,
    )


def detect_cabinet_collisions(
    placements: list[CabinetPlacement],
) -> list[tuple[int, int]]:
    """Return pairs of indices whose bounding boxes overlap in plan view (XY).

    Uses axis-aligned bounding box (AABB) intersection test in the cabinet's
    rotated frame.  For plan-view overlap check, rectangles are axis-aligned to
    the cabinet's local coordinate frame.

    Args:
        placements: list of CabinetPlacement objects

    Returns:
        list of (i, j) index pairs where placements[i] and placements[j] overlap.
    """
    if len(placements) < 2:
        return []

    def _cabinet_aabb(p: CabinetPlacement) -> tuple[float, float, float, float]:
        """Return (xmin, xmax, ymin, ymax) for a placement."""
        cx, cy, _ = p.position
        w = p.unit.width_m
        d = p.unit.depth_m
        ang = math.radians(p.rotation_deg)
        cos_a = math.cos(ang)
        sin_a = math.sin(ang)
        # Four corners relative to cabinet centre
        hw = w / 2.0
        hd = d / 2.0
        corners = [
            (-hw, -hd), (hw, -hd), (hw, hd), (-hw, hd),
        ]
        xs = [cx + lx * cos_a - ly * sin_a for lx, ly in corners]
        ys = [cy + lx * sin_a + ly * cos_a for lx, ly in corners]
        return (min(xs), max(xs), min(ys), max(ys))

    def _aabbs_overlap(a: tuple, b: tuple) -> bool:
        ax0, ax1, ay0, ay1 = a
        bx0, bx1, by0, by1 = b
        eps = 1e-6
        return (ax0 < bx1 - eps and ax1 > bx0 + eps and
                ay0 < by1 - eps and ay1 > by0 + eps)

    bboxes = [_cabinet_aabb(p) for p in placements]
    collisions = []
    for i in range(len(placements)):
        for j in range(i + 1, len(placements)):
            if _aabbs_overlap(bboxes[i], bboxes[j]):
                collisions.append((i, j))
    return collisions


def _check_door_window_clearances(
    placements: list[CabinetPlacement],
    room: Room,
    clearance_m: float,
) -> bool:
    """Verify all placements respect door/window clearances.

    NKBA Guideline 5: no cabinet within clearance_m of a door or window opening
    on the same wall.  Returns True if all placements comply.
    """
    if not room.openings:
        return True

    segments = _wall_segments(room.outline)

    for op in room.openings:
        wall_idx = op.get("wall_index", -1)
        if wall_idx < 0 or wall_idx >= len(segments):
            continue
        p0, p1, wall_len = segments[wall_idx]
        ux, uy = _wall_unit_vector(p0, p1)
        op_pos = float(op.get("position_m", 0.0))
        op_w = float(op.get("width_m", 0.0))

        for pl in placements:
            cx, cy, _ = pl.position
            # Project cabinet position onto wall
            dx = cx - p0[0]
            dy = cy - p0[1]
            proj = dx * ux + dy * uy   # along-wall coordinate of cabinet centre
            half_w = pl.unit.width_m / 2.0
            cab_start = proj - half_w
            cab_end = proj + half_w

            # Opening occupies [op_pos, op_pos + op_w]
            # Required gap: clearance_m each side
            blocked_start = op_pos - clearance_m
            blocked_end = op_pos + op_w + clearance_m

            # Overlap check
            if cab_start < blocked_end and cab_end > blocked_start:
                return False
    return True
