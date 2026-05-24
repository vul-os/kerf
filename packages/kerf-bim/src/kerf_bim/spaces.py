"""
kerf_bim.spaces — BIM space / zone / room objects.

A BIM space corresponds to IfcSpace (ISO 16739-1:2018) and represents a
named, bounded region within a building storey.  Spaces carry:
  - Area (m²) — computed from the plan-view boundary polygon
  - Volume (m³) — area × ceiling height
  - Occupancy / program category
  - Level (storey) assignment
  - Name / description

These are the "Zone" objects in ArchiCAD and "Room" / "Space" objects in
Revit.

Public API
----------
Space(name, boundary, level, height, program, occupancy_per_m2) — dataclass
space_area(boundary) -> float          — compute polygon area (m²)
space_volume(boundary, height) -> float
space_schedule(spaces) -> dict         — generate area / occupancy schedule
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

__all__ = [
    "Space",
    "SpaceValidationError",
    "space_area",
    "space_volume",
    "space_schedule",
]


class SpaceValidationError(ValueError):
    """Raised when a space definition is invalid."""


# ---------------------------------------------------------------------------
# Shoelace formula for polygon area
# ---------------------------------------------------------------------------

def space_area(boundary: List[List[float]]) -> float:
    """Return area of a closed polygon (m²) via the shoelace formula.

    Parameters
    ----------
    boundary:
        List of ``[x, y]`` points in metres, no closing duplicate.

    Returns
    -------
    float
        Absolute area in m².  Returns 0 for fewer than 3 points.
    """
    n = len(boundary)
    if n < 3:
        return 0.0
    area = 0.0
    for i in range(n):
        x0, y0 = float(boundary[i][0]), float(boundary[i][1])
        x1, y1 = float(boundary[(i + 1) % n][0]), float(boundary[(i + 1) % n][1])
        area += x0 * y1 - x1 * y0
    return abs(area) / 2.0


def space_volume(boundary: List[List[float]], height_m: float) -> float:
    """Return volume (m³) = area × height."""
    return space_area(boundary) * max(0.0, float(height_m))


# ---------------------------------------------------------------------------
# Space dataclass
# ---------------------------------------------------------------------------

@dataclass
class Space:
    """A BIM space / zone / room.

    Parameters
    ----------
    name:
        Room / space name (e.g. "Living Room", "Office 1").
    boundary:
        Plan-view boundary polygon as ``[[x, y], ...]`` in **metres**.
        Minimum 3 points; no closing duplicate.
    level:
        Storey / level name (e.g. "L1", "Ground Floor").
    height_m:
        Floor-to-ceiling height in metres (default 2.7 m).
    program:
        Occupancy program category (e.g. "office", "residential", "retail").
    occupancy_per_m2:
        Density of occupancy in persons/m² (from building code, optional).
    global_id:
        Optional IFC GlobalId for round-trip fidelity.
    """
    name: str
    boundary: List[List[float]]
    level: str = "L1"
    height_m: float = 2.7
    program: str = "residential"
    occupancy_per_m2: Optional[float] = None
    global_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise SpaceValidationError("Space name must not be empty")
        if len(self.boundary) < 3:
            raise SpaceValidationError(
                f"Space '{self.name}': boundary must have at least 3 points"
            )
        if self.height_m <= 0:
            raise SpaceValidationError(
                f"Space '{self.name}': height_m must be positive"
            )

    @property
    def area_m2(self) -> float:
        """Net floor area in m²."""
        return space_area(self.boundary)

    @property
    def volume_m3(self) -> float:
        """Gross volume in m³."""
        return space_volume(self.boundary, self.height_m)

    @property
    def occupancy(self) -> Optional[int]:
        """Calculated occupancy (persons), or None if no density given."""
        if self.occupancy_per_m2 is None:
            return None
        return math.ceil(self.area_m2 * self.occupancy_per_m2)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to the .bim space dict schema."""
        d: Dict[str, Any] = {
            "name": self.name,
            "level": self.level,
            "boundary": [[round(p[0], 6), round(p[1], 6)] for p in self.boundary],
            "height_m": round(self.height_m, 4),
            "program": self.program,
            "area_m2": round(self.area_m2, 4),
            "volume_m3": round(self.volume_m3, 4),
        }
        if self.occupancy_per_m2 is not None:
            d["occupancy_per_m2"] = self.occupancy_per_m2
            d["occupancy"] = self.occupancy
        if self.global_id:
            d["global_id"] = self.global_id
        return d


# ---------------------------------------------------------------------------
# Schedule generator
# ---------------------------------------------------------------------------

def space_schedule(spaces: List[Space]) -> Dict[str, Any]:
    """Generate a BIM area / occupancy schedule from a list of spaces.

    Returns a dict with:
        - ``rows``:  one entry per space with name, level, area, volume, occupancy
        - ``totals``: sum area, sum volume, sum occupancy
        - ``by_level``: per-level subtotals

    Conforms to the IfcElementQuantity / IfcAreaMeasure conventions from
    ISO 16739-1:2018.

    Parameters
    ----------
    spaces:
        List of :class:`Space` objects.

    Returns
    -------
    dict
        ``{"rows": [...], "totals": {...}, "by_level": {...}}``
    """
    rows = []
    total_area = 0.0
    total_volume = 0.0
    total_occupancy = 0
    by_level: Dict[str, Dict[str, Any]] = {}

    for sp in spaces:
        row: Dict[str, Any] = {
            "name": sp.name,
            "level": sp.level,
            "program": sp.program,
            "area_m2": round(sp.area_m2, 2),
            "volume_m3": round(sp.volume_m3, 2),
            "height_m": round(sp.height_m, 2),
        }
        if sp.occupancy is not None:
            row["occupancy"] = sp.occupancy
            total_occupancy += sp.occupancy
        rows.append(row)
        total_area += sp.area_m2
        total_volume += sp.volume_m3

        lvl = sp.level or "Unknown"
        if lvl not in by_level:
            by_level[lvl] = {"area_m2": 0.0, "volume_m3": 0.0, "count": 0}
        by_level[lvl]["area_m2"] += sp.area_m2
        by_level[lvl]["volume_m3"] += sp.volume_m3
        by_level[lvl]["count"] += 1

    # Round by_level totals
    for lvl_data in by_level.values():
        lvl_data["area_m2"] = round(lvl_data["area_m2"], 2)
        lvl_data["volume_m3"] = round(lvl_data["volume_m3"], 2)

    totals: Dict[str, Any] = {
        "area_m2": round(total_area, 2),
        "volume_m3": round(total_volume, 2),
        "space_count": len(spaces),
    }
    if total_occupancy:
        totals["occupancy"] = total_occupancy

    return {
        "ok": True,
        "rows": rows,
        "totals": totals,
        "by_level": by_level,
    }
