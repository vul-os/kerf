"""
kerf_cad_core.arch.spaces
==========================

Rooms / spaces layer — compute area, perimeter, occupancy load, egress width,
and produce building area schedules from a set of boundary polygons.

All linear dimensions are in **millimetres** throughout; areas are mm².
Area schedule totals may optionally be converted to m² for display but the
internal representation stays mm².

Occupancy load factors
-----------------------
Nominal values from IBC Table 1004.5 (International Building Code, 2021
edition).  These are the *gross floor area per occupant* figures used for
determining minimum occupant load.  Source: "nominal IBC Table 1004.5 values".

Selected factors (m² per occupant — converted to mm²/person internally):

  assembly_standing   :   0.28  m²/person  (standing space)
  assembly_concentrated:  0.65  m²/person  (fixed seats / concentrated)
  assembly_unconcentrated: 1.39 m²/person  (tables and chairs)
  business             :  9.30  m²/person  (general office/business)
  educational_classroom:  1.86  m²/person  (classroom)
  factory_industrial   :  9.30  m²/person  (industrial / manufacturing)
  mercantile           :  2.79  m²/person  (retail / sales floor)
  residential          : 18.58  m²/person  (residential)
  storage              : 11.15  m²/person  (storage)
  healthcare_inpatient : 22.30  m²/person  (inpatient treatment areas)
  kitchen_commercial   :  4.65  m²/person  (kitchen / food prep)
  library_reading_room :  4.65  m²/person  (library reading area)
  locker_room          :  4.65  m²/person  (locker / shower rooms)
  mall_covered         :  2.79  m²/person  (covered mall buildings)
  parking              : 18.58  m²/person  (parking garages)

Egress minimum width
---------------------
Nominal IBC § 1005.1 values:

  stairways : 0.3 mm per occupant
  other means (corridors, ramps, doors) : 0.2 mm per occupant

Public API
----------
  shoelace_area(polygon)     -> float  (mm²)
  polygon_perimeter(polygon) -> float  (mm)
  is_self_intersecting(polygon) -> bool
  compute_room(polygon, name, occupancy, wall_thickness=0, level="") -> dict
  compute_area_schedule(rooms)                                        -> dict
  compute_occupancy_load(area_m2, occupancy)                         -> dict

  OCCUPANCY_LOAD_FACTORS  — public constant dict {occupancy: m²/person}

Builder functions used by tools:
  room_from_polygon(...)     -> dict  (same as compute_room)
  area_schedule(rooms)       -> dict  (same as compute_area_schedule)

All builders return {ok: bool, ...} — never raise.
"""

from __future__ import annotations

import math
from typing import Optional

# ---------------------------------------------------------------------------
# Occupancy load factors — nominal IBC Table 1004.5 values
# (gross floor area in m² per occupant)
# ---------------------------------------------------------------------------

OCCUPANCY_LOAD_FACTORS: dict[str, float] = {
    "assembly_standing":         0.28,
    "assembly_concentrated":     0.65,
    "assembly_unconcentrated":   1.39,
    "business":                  9.30,
    "educational_classroom":     1.86,
    "factory_industrial":        9.30,
    "mercantile":                2.79,
    "residential":              18.58,
    "storage":                  11.15,
    "healthcare_inpatient":     22.30,
    "kitchen_commercial":        4.65,
    "library_reading_room":      4.65,
    "locker_room":               4.65,
    "mall_covered":              2.79,
    "parking":                  18.58,
}

# Nominal IBC § 1005.1 egress width factors (mm per occupant)
_EGRESS_WIDTH_STAIR_MM_PER_OCC: float = 0.3
_EGRESS_WIDTH_OTHER_MM_PER_OCC: float = 0.2

# Conversion factor
_MM2_PER_M2: float = 1_000_000.0


# ---------------------------------------------------------------------------
# Internal geometry helpers
# ---------------------------------------------------------------------------

def _shoelace_signed(vertices: list[tuple[float, float]]) -> float:
    """Return the signed shoelace area (positive = CCW, negative = CW)."""
    n = len(vertices)
    total = 0.0
    for i in range(n):
        x0, y0 = vertices[i]
        x1, y1 = vertices[(i + 1) % n]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def shoelace_area(polygon: list) -> float:
    """Compute polygon area (mm²) using the shoelace formula.

    Returns the absolute area so both CW and CCW orderings are accepted.
    Polygon is automatically closed (first==last vertex is not required).
    """
    verts = [(float(p[0]), float(p[1])) for p in polygon]
    return abs(_shoelace_signed(verts))


def polygon_perimeter(polygon: list) -> float:
    """Compute the perimeter of a closed polygon in mm."""
    verts = [(float(p[0]), float(p[1])) for p in polygon]
    n = len(verts)
    total = 0.0
    for i in range(n):
        x0, y0 = verts[i]
        x1, y1 = verts[(i + 1) % n]
        total += math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
    return total


def _segments_intersect(
    ax: float, ay: float, bx: float, by: float,
    cx: float, cy: float, dx: float, dy: float,
) -> bool:
    """Return True if segment AB *properly* crosses segment CD (not at endpoints)."""
    def _cross2(ox, oy, px, py, qx, qy) -> float:
        return (px - ox) * (qy - oy) - (py - oy) * (qx - ox)

    d1 = _cross2(cx, cy, dx, dy, ax, ay)
    d2 = _cross2(cx, cy, dx, dy, bx, by)
    d3 = _cross2(ax, ay, bx, by, cx, cy)
    d4 = _cross2(ax, ay, bx, by, dx, dy)

    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and \
       ((d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)):
        return True
    return False


def is_self_intersecting(polygon: list) -> bool:
    """Return True if any two non-adjacent edges of the polygon properly cross."""
    verts = [(float(p[0]), float(p[1])) for p in polygon]
    n = len(verts)
    edges = [(verts[i], verts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        ax, ay = edges[i][0]
        bx, by = edges[i][1]
        for j in range(i + 2, n):
            # Skip edges that share a vertex
            if j == n - 1 and i == 0:
                continue
            cx, cy = edges[j][0]
            dx, dy = edges[j][1]
            if _segments_intersect(ax, ay, bx, by, cx, cy, dx, dy):
                return True
    return False


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_polygon(polygon, label: str = "polygon") -> list[str]:
    """Return a list of error strings; empty list means the polygon is valid."""
    errors: list[str] = []
    if not isinstance(polygon, (list, tuple)) or len(polygon) < 3:
        errors.append(f"{label} must be a list of at least 3 [x, y] vertices")
        return errors
    for i, pt in enumerate(polygon):
        if not (isinstance(pt, (list, tuple)) and len(pt) == 2):
            errors.append(f"{label}[{i}] must be a 2-element [x, y] pair")
    if errors:
        return errors
    # Self-intersection check first (catches bow-tie shapes before area check)
    if is_self_intersecting(polygon):
        errors.append(f"{label} is self-intersecting")
        return errors
    # Degenerate check: zero area (collinear vertices)
    area = shoelace_area(polygon)
    if area == 0.0:
        errors.append(f"{label} is degenerate (zero area — all vertices may be collinear)")
    return errors


# ---------------------------------------------------------------------------
# Net area helpers
# ---------------------------------------------------------------------------

def _net_area_mm2(gross_area_mm2: float, perimeter_mm: float, wall_thickness_mm: float) -> float:
    """Approximate net room area by subtracting a wall-thickness band.

    The band area approximation is:  perimeter × (wall_thickness / 2)
    (half-thickness inset on each side of the boundary).
    This is a standard architectural approximation.
    """
    if wall_thickness_mm <= 0.0:
        return gross_area_mm2
    band = perimeter_mm * (wall_thickness_mm / 2.0)
    return max(0.0, gross_area_mm2 - band)


# ---------------------------------------------------------------------------
# Occupancy load computation
# ---------------------------------------------------------------------------

def _occupant_load(area_mm2: float, occupancy: str) -> int:
    """Compute occupant load (persons) = ceil(area_m2 / factor).

    Uses nominal IBC Table 1004.5 values.
    """
    factor_m2 = OCCUPANCY_LOAD_FACTORS[occupancy]
    area_m2 = area_mm2 / _MM2_PER_M2
    return math.ceil(area_m2 / factor_m2)


def _egress_width_mm(occupant_load: int) -> dict[str, float]:
    """Return the minimum egress clear width (mm) per IBC § 1005.1."""
    return {
        "stairways_mm": occupant_load * _EGRESS_WIDTH_STAIR_MM_PER_OCC,
        "other_means_mm": occupant_load * _EGRESS_WIDTH_OTHER_MM_PER_OCC,
    }


# ---------------------------------------------------------------------------
# Public builders
# ---------------------------------------------------------------------------

def compute_room(
    polygon: list,
    name: str,
    occupancy: str,
    wall_thickness: float = 0.0,
    level: str = "",
) -> dict:
    """Compute area, perimeter, occupancy load, and egress width for a room.

    Parameters
    ----------
    polygon        : list of [x, y] in mm — closed room boundary polygon
    name           : str — human-readable room name
    occupancy      : str — one of OCCUPANCY_LOAD_FACTORS keys
    wall_thickness : float — wall thickness in mm; if > 0, net area is
                             derived by subtracting the wall-thickness band
                             (gross_area − perimeter × thickness/2)
    level          : str — floor/level label (e.g. "L1", "Ground Floor")

    Returns
    -------
    dict with keys:
      ok                  : bool
      errors              : list[str]   (empty on success)
      name                : str
      occupancy           : str
      level               : str
      polygon             : list[[x, y]]
      gross_area_mm2      : float
      perimeter_mm        : float
      net_area_mm2        : float   (== gross if wall_thickness == 0)
      wall_thickness_mm   : float
      occupant_load       : int     (based on net area)
      egress_width        : {stairways_mm, other_means_mm}
      gross_area_m2       : float   (convenience)
      net_area_m2         : float   (convenience)
      load_factor_m2_per_person: float
      load_factor_source  : str
    """
    errors: list[str] = []

    poly_errors = _validate_polygon(polygon, "polygon")
    errors.extend(poly_errors)

    if not isinstance(name, str) or not name.strip():
        errors.append("name must be a non-empty string")

    if occupancy not in OCCUPANCY_LOAD_FACTORS:
        errors.append(
            f"occupancy '{occupancy}' is not recognised. "
            f"Valid values: {sorted(OCCUPANCY_LOAD_FACTORS)}"
        )

    if not isinstance(wall_thickness, (int, float)) or wall_thickness < 0:
        errors.append(f"wall_thickness must be >= 0; got {wall_thickness}")

    if errors:
        return {"ok": False, "errors": errors}

    verts = [[float(p[0]), float(p[1])] for p in polygon]
    gross_area = shoelace_area(verts)
    perimeter = polygon_perimeter(verts)
    net_area = _net_area_mm2(gross_area, perimeter, float(wall_thickness))
    load = _occupant_load(net_area, occupancy)
    egress = _egress_width_mm(load)
    factor = OCCUPANCY_LOAD_FACTORS[occupancy]

    return {
        "ok": True,
        "errors": [],
        "name": name.strip(),
        "occupancy": occupancy,
        "level": str(level),
        "polygon": verts,
        "gross_area_mm2": gross_area,
        "perimeter_mm": perimeter,
        "net_area_mm2": net_area,
        "wall_thickness_mm": float(wall_thickness),
        "occupant_load": load,
        "egress_width": egress,
        "gross_area_m2": gross_area / _MM2_PER_M2,
        "net_area_m2": net_area / _MM2_PER_M2,
        "load_factor_m2_per_person": factor,
        "load_factor_source": "nominal IBC Table 1004.5 values",
    }


# Alias for the tool layer
room_from_polygon = compute_room


def compute_area_schedule(rooms: list[dict]) -> dict:
    """Produce a building area schedule rollup from a list of room dicts.

    Parameters
    ----------
    rooms : list of dicts — each must be a successful output of compute_room
            (ok=True).  Invalid room dicts are collected as errors.

    Returns
    -------
    dict with keys:
      ok                  : bool
      errors              : list[str]
      rooms               : list[dict]  (only valid rooms)
      total_gross_area_mm2: float
      total_net_area_mm2  : float
      total_occupant_load : int
      total_gross_area_m2 : float
      total_net_area_m2   : float
      by_level            : {level_label: {gross_area_mm2, net_area_mm2,
                                           occupant_load, room_count}}
      by_occupancy        : {occupancy_type: {gross_area_mm2, net_area_mm2,
                                              occupant_load, room_count}}
    """
    errors: list[str] = []
    valid_rooms: list[dict] = []

    if not isinstance(rooms, (list, tuple)):
        return {"ok": False, "errors": ["rooms must be a list"], "rooms": []}

    for i, room in enumerate(rooms):
        if not isinstance(room, dict):
            errors.append(f"rooms[{i}] is not a dict")
            continue
        if not room.get("ok"):
            for e in room.get("errors", [f"rooms[{i}] has ok=false"]):
                errors.append(f"rooms[{i}]: {e}")
            continue
        valid_rooms.append(room)

    if errors:
        return {
            "ok": False,
            "errors": errors,
            "rooms": valid_rooms,
        }

    total_gross = sum(r["gross_area_mm2"] for r in valid_rooms)
    total_net = sum(r["net_area_mm2"] for r in valid_rooms)
    total_load = sum(r["occupant_load"] for r in valid_rooms)

    # Rollup by level
    by_level: dict[str, dict] = {}
    for r in valid_rooms:
        lvl = r.get("level", "")
        if lvl not in by_level:
            by_level[lvl] = {
                "gross_area_mm2": 0.0,
                "net_area_mm2": 0.0,
                "occupant_load": 0,
                "room_count": 0,
            }
        by_level[lvl]["gross_area_mm2"] += r["gross_area_mm2"]
        by_level[lvl]["net_area_mm2"] += r["net_area_mm2"]
        by_level[lvl]["occupant_load"] += r["occupant_load"]
        by_level[lvl]["room_count"] += 1

    # Rollup by occupancy
    by_occ: dict[str, dict] = {}
    for r in valid_rooms:
        occ = r.get("occupancy", "")
        if occ not in by_occ:
            by_occ[occ] = {
                "gross_area_mm2": 0.0,
                "net_area_mm2": 0.0,
                "occupant_load": 0,
                "room_count": 0,
            }
        by_occ[occ]["gross_area_mm2"] += r["gross_area_mm2"]
        by_occ[occ]["net_area_mm2"] += r["net_area_mm2"]
        by_occ[occ]["occupant_load"] += r["occupant_load"]
        by_occ[occ]["room_count"] += 1

    return {
        "ok": True,
        "errors": [],
        "rooms": valid_rooms,
        "total_gross_area_mm2": total_gross,
        "total_net_area_mm2": total_net,
        "total_occupant_load": total_load,
        "total_gross_area_m2": total_gross / _MM2_PER_M2,
        "total_net_area_m2": total_net / _MM2_PER_M2,
        "by_level": by_level,
        "by_occupancy": by_occ,
    }


# Alias for the tool layer
area_schedule = compute_area_schedule


def compute_occupancy_load(
    area_m2: float,
    occupancy: str,
    use_net: bool = True,
) -> dict:
    """Compute occupancy load for a given area and occupancy type.

    Parameters
    ----------
    area_m2   : float — gross or net floor area in square metres
    occupancy : str   — one of OCCUPANCY_LOAD_FACTORS keys
    use_net   : bool  — labelling only; does not affect the calculation

    Returns
    -------
    dict with keys:
      ok                 : bool
      errors             : list[str]
      occupancy          : str
      area_m2            : float
      area_type          : "net" or "gross"
      load_factor_m2_per_person: float
      load_factor_source : str
      occupant_load      : int
      egress_width       : {stairways_mm, other_means_mm}
    """
    errors: list[str] = []

    if not isinstance(area_m2, (int, float)) or area_m2 < 0:
        errors.append(f"area_m2 must be >= 0; got {area_m2}")

    if occupancy not in OCCUPANCY_LOAD_FACTORS:
        errors.append(
            f"occupancy '{occupancy}' is not recognised. "
            f"Valid values: {sorted(OCCUPANCY_LOAD_FACTORS)}"
        )

    if errors:
        return {"ok": False, "errors": errors}

    factor = OCCUPANCY_LOAD_FACTORS[occupancy]
    load = math.ceil(float(area_m2) / factor)
    egress = _egress_width_mm(load)

    return {
        "ok": True,
        "errors": [],
        "occupancy": occupancy,
        "area_m2": float(area_m2),
        "area_type": "net" if use_net else "gross",
        "load_factor_m2_per_person": factor,
        "load_factor_source": "nominal IBC Table 1004.5 values",
        "occupant_load": load,
        "egress_width": egress,
    }
