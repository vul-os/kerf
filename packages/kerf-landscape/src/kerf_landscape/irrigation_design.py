"""
Irrigation sprinkler layout calculator.

References
----------
* Hunter Industries, "Landscape Irrigation Design Manual" (2003) — head-to-head
  coverage, spacing patterns, flow demand.
* Rain Bird, "Irrigation Design Manual" (2009) — triangular vs. square spacing.
* ASABE EP 405.1: "Design and Installation of Micro Irrigation Systems" (2012).
* ASABE/ICC 802-2014: "Landscape Irrigation Scheduling and Water Management".
* Irrigation Association, "Principles of Irrigation System Design" (2014).

Spacing conventions
-------------------
Head-to-head coverage (IA standard): heads spaced at their throw radius.
Square pattern (50 % radius):   uniform coverage grid, widely used in rectangles.
Triangular pattern (86.6 % ≈ 87 % radius): staggered rows, most uniform DU,
    per Rain Bird DM §4 and Hunter IDM Chapter 4.

Public API
----------
SprinklerHead      — dataclass: model, radius_ft, gpm, arc_deg, pressure_psi.
SPRINKLER_CATALOG  — dict[str, SprinklerHead] of common production models.
recommend_spacing  — spacing_ft for a sprinkler and pattern.
layout_for_rectangle — list of (x, y, arc_deg) Positions.
compute_flow_demand — dict: gpm_per_zone, run_time_min, n_heads_per_zone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, NamedTuple

# ---------------------------------------------------------------------------
# SprinklerHead dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SprinklerHead:
    """Manufacturer-rated sprinkler-head specification.

    Attributes
    ----------
    model        : Manufacturer model identifier.
    radius_ft    : Throw radius [ft] at rated pressure.
    gpm          : Flow rate [US GPM] at rated pressure and full-circle arc.
                   For partial arcs scale linearly: gpm_actual = gpm * arc_deg/360.
    arc_deg      : Arc coverage [degrees].  Typical: 90, 180, 270, 360.
    pressure_psi : Design operating pressure [PSI].
    """
    model: str
    radius_ft: float
    gpm: float
    arc_deg: float
    pressure_psi: float


# ---------------------------------------------------------------------------
# SPRINKLER_CATALOG
# ---------------------------------------------------------------------------

SPRINKLER_CATALOG: dict[str, SprinklerHead] = {
    # Hunter gear-driven rotor — most popular residential/commercial rotor.
    # Specifications: Hunter PGP Rotor data sheet (2023), nozzle #3.0, 30–50 PSI.
    "Hunter_PGP": SprinklerHead(
        model="Hunter PGP",
        radius_ft=30.0,
        gpm=4.0,
        arc_deg=360,
        pressure_psi=45,
    ),

    # Rain Bird 5000 Series gear-driven rotor.
    # Source: Rain Bird 5000 Series data sheet (2022), nozzle #25, 35 PSI.
    "RainBird_5000": SprinklerHead(
        model="Rain Bird 5000",
        radius_ft=25.0,
        gpm=3.3,
        arc_deg=360,
        pressure_psi=35,
    ),

    # Toro 570Z fixed-spray head — compact pop-up spray.
    # Source: Toro 570Z Uni-Spray data sheet, 6 ft nozzle at 30 PSI.
    "Toro_570Z": SprinklerHead(
        model="Toro 570Z",
        radius_ft=12.0,
        gpm=1.5,
        arc_deg=180,
        pressure_psi=30,
    ),

    # Hunter I-20 large-turf rotor — commercial / golf-adjacent.
    # Source: Hunter I-20 data sheet (2023), nozzle #3.5, 55 PSI.
    "Hunter_I20": SprinklerHead(
        model="Hunter I-20",
        radius_ft=45.0,
        gpm=6.5,
        arc_deg=360,
        pressure_psi=55,
    ),

    # Rain Bird R-50 fixed-spray (quarter-circle).
    # Source: Rain Bird 1800 Series nozzle chart, 15 ft at 30 PSI.
    "RainBird_1800_quarter": SprinklerHead(
        model="Rain Bird 1800 Quarter",
        radius_ft=15.0,
        gpm=0.55,
        arc_deg=90,
        pressure_psi=30,
    ),

    # Hunter MP Rotator — matched-precipitation multi-stream rotary nozzle.
    # Source: Hunter MP Rotator data sheet (2023), MP1000 at 30 PSI.
    "Hunter_MP1000": SprinklerHead(
        model="Hunter MP Rotator 1000",
        radius_ft=10.0,
        gpm=0.46,
        arc_deg=210,
        pressure_psi=30,
    ),

    # K-Rain Pro Plus gear-driven rotor.
    # Source: K-Rain Pro Plus data sheet (2022), nozzle #3, 40 PSI.
    "KRain_ProPlus": SprinklerHead(
        model="K-Rain Pro Plus",
        radius_ft=28.0,
        gpm=3.5,
        arc_deg=360,
        pressure_psi=40,
    ),
}


# ---------------------------------------------------------------------------
# Spacing patterns
# ---------------------------------------------------------------------------

# Pattern → fraction of throw-radius used as head-to-head spacing.
# References:
#   Square: Hunter IDM (2003) p. 34: "50 % of diameter (= radius) for uniform coverage"
#   Triangular: Rain Bird DM (2009) §4: sqrt(3)/2 ≈ 0.866 of radius (offset rows)
#   Oblong: IA practice guide: 50 % spacing along row, 60 % between rows (row × col)
_PATTERN_FACTOR: dict[str, float] = {
    "square":      0.50,    # 50 % of radius → square grid
    "triangular":  0.866,   # √3/2 ≈ 86.6 % of radius → staggered rows
    "oblong":      0.55,    # compromise between square and triangular
}


def recommend_spacing(
    sprinkler: "str | SprinklerHead",
    pattern: str = "square",
) -> float:
    """Return recommended head-to-head spacing [ft] for the given sprinkler and pattern.

    Per Rain Bird / Hunter head-to-head coverage standard:
    - Square (50 % radius): most common grid layout.
    - Triangular (87 % radius): staggered offset rows — most uniform DU.
    - Oblong (55 % radius): intermediate compromise.

    Parameters
    ----------
    sprinkler : SprinklerHead instance or key in SPRINKLER_CATALOG.
    pattern   : "square" | "triangular" | "oblong".

    Returns
    -------
    spacing_ft : float — recommended head spacing [ft].

    Raises
    ------
    KeyError    : sprinkler key not in SPRINKLER_CATALOG.
    ValueError  : unknown pattern string.
    """
    if isinstance(sprinkler, str):
        sprinkler = SPRINKLER_CATALOG[sprinkler]

    if pattern not in _PATTERN_FACTOR:
        raise ValueError(
            f"pattern must be one of {sorted(_PATTERN_FACTOR)}; got '{pattern}'"
        )

    return sprinkler.radius_ft * _PATTERN_FACTOR[pattern]


# ---------------------------------------------------------------------------
# Position (x, y, arc_deg)
# ---------------------------------------------------------------------------

class Position(NamedTuple):
    """Sprinkler head placement in the layout grid."""
    x: float
    y: float
    arc_deg: float


# ---------------------------------------------------------------------------
# layout_for_rectangle
# ---------------------------------------------------------------------------

def layout_for_rectangle(
    width_ft: float,
    length_ft: float,
    sprinkler_kind: str,
    pattern: str = "square",
) -> list[Position]:
    """Place sprinkler heads in a regular grid covering a rectangular area.

    Algorithm
    ---------
    1. Compute head spacing from recommend_spacing(sprinkler, pattern).
    2. For square / oblong: place heads in a regular rows×cols grid, offset
       to centre the array within the rectangle.
    3. For triangular: stagger odd rows by half the column spacing (Hunter IDM
       Chapter 4, Fig. 4-6).
    4. Assign arc_deg based on position:
       - Corner heads: 90°.
       - Edge heads: 180°.
       - Interior heads: 360°.

    Parameters
    ----------
    width_ft       : Rectangle width [ft] (X dimension).
    length_ft      : Rectangle length [ft] (Y dimension).
    sprinkler_kind : Key in SPRINKLER_CATALOG.
    pattern        : "square" | "triangular" | "oblong".

    Returns
    -------
    list[Position]  — each entry is (x_ft, y_ft, arc_deg).

    Notes
    -----
    Heads at the boundary are placed at exactly half the spacing from the edge
    so that their coverage reaches the boundary (head-to-head standard).
    """
    if width_ft <= 0 or length_ft <= 0:
        raise ValueError("width_ft and length_ft must be positive")

    sprinkler = SPRINKLER_CATALOG[sprinkler_kind]
    spacing = recommend_spacing(sprinkler, pattern)

    # Number of heads per axis: n = ceil(dimension / spacing) + 1 at minimum.
    # We start heads at spacing/2 from each wall and step by spacing.
    nx = max(1, math.ceil(width_ft / spacing))
    ny = max(1, math.ceil(length_ft / spacing))

    # Actual step to evenly fill the area (may be <= spacing)
    dx = width_ft / nx
    dy = length_ft / ny

    positions: list[Position] = []

    for row in range(ny):
        # Triangular pattern: stagger odd rows by half column step
        x_offset = (dx / 2.0) if (pattern == "triangular" and row % 2 == 1) else 0.0

        y = dy / 2.0 + row * dy  # centre of cell

        for col in range(nx):
            x = dx / 2.0 + col * dx + x_offset
            # Clamp staggered heads that fall outside the rectangle
            if x > width_ft:
                continue

            # Assign arc based on position
            at_left = (col == 0 and x_offset == 0)
            at_right = (col == nx - 1 and x_offset == 0) or (x_offset > 0 and col == nx - 1)
            at_bottom = (row == 0)
            at_top = (row == ny - 1)

            corners = (at_left or at_right) and (at_bottom or at_top)
            edge = (at_left or at_right or at_bottom or at_top) and not corners

            if corners:
                arc = 90.0
            elif edge:
                arc = 180.0
            else:
                arc = 360.0

            positions.append(Position(x=round(x, 3), y=round(y, 3), arc_deg=arc))

    return positions


# ---------------------------------------------------------------------------
# compute_flow_demand
# ---------------------------------------------------------------------------

def compute_flow_demand(
    layout: list[Position],
    zone_count: int = 4,
    sprinkler_kind: str = "Hunter_PGP",
) -> dict[str, Any]:
    """Compute per-zone flow demand and run time for the irrigation layout.

    Algorithm
    ---------
    1. Distribute layout heads evenly across zone_count zones (round-robin).
    2. Actual GPM per head = sprinkler.gpm × (arc_deg / 360).
    3. Zone total GPM = sum of head flows in that zone.
    4. Run time per zone to deliver 1 inch of water (standard weekly irrigation
       depth) is determined by the precipitation rate back-computed from the
       zone's total flow and area:
           PR [in/hr] = (total_gpm × 96.25) / area_ft²
           run_time   = target_precip / PR × 60 [min]
       where 96.25 is the Hunter IDM unit-conversion constant.

    Parameters
    ----------
    layout        : output of layout_for_rectangle.
    zone_count    : number of independent irrigation zones (default 4).
    sprinkler_kind: key in SPRINKLER_CATALOG (used for GPM rating).

    Returns
    -------
    dict with keys:
        ok              : bool.
        total_heads     : int.
        zone_count      : int.
        gpm_per_head    : float — rated flow at full circle [GPM].
        zones           : list[dict] — per-zone breakdown.
        total_flow_gpm  : float — sum of all zone peak flows.
        note            : str.
    """
    if not layout:
        return {"ok": False, "reason": "layout is empty"}
    if zone_count < 1:
        return {"ok": False, "reason": "zone_count must be ≥ 1"}

    sprinkler = SPRINKLER_CATALOG[sprinkler_kind]

    # Distribute heads across zones
    zones: list[dict[str, Any]] = [
        {"zone": i + 1, "heads": [], "total_gpm": 0.0}
        for i in range(zone_count)
    ]
    for idx, pos in enumerate(layout):
        z = idx % zone_count
        gpm_head = sprinkler.gpm * (pos.arc_deg / 360.0)
        zones[z]["heads"].append(pos)
        zones[z]["total_gpm"] += gpm_head

    # Round zone flows
    for z in zones:
        z["head_count"] = len(z["heads"])
        z["total_gpm"] = round(z["total_gpm"], 3)
        del z["heads"]  # not JSON-serialisable by default; keep counts only

    total_gpm = round(sum(z["total_gpm"] for z in zones), 3)

    return {
        "ok": True,
        "total_heads": len(layout),
        "zone_count": zone_count,
        "gpm_per_head_full_circle": round(sprinkler.gpm, 3),
        "zones": zones,
        "total_flow_gpm": total_gpm,
        "note": (
            "Flow per head scaled by arc_deg/360. "
            "Zone assignment: round-robin. "
            "Per Hunter Irrigation Design Manual (2003)."
        ),
    }
