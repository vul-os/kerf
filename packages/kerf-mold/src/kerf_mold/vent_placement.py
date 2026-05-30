"""
kerf_mold.vent_placement
========================
Air-vent location optimiser for injection-mold cavities.

Vents allow trapped air (and combustion gases) to escape as the polymer melt
front fills the cavity.  Poor venting causes:
  - Diesel effect (adiabatic compression ignites gas -> burn marks, short shots).
  - High backpressure at last-fill zones -> incomplete fill.
  - Weld-line weakness where two melt fronts meet without venting.

This module provides:

  VentLocation    -- single vent position with depth/width/advisory.
  VentPlacementResult -- dataclass returned by optimize_vent_placement.
  optimize_vent_placement -- heuristic: last-fill zones, parting-line ribs,
                             sharp-corner pockets; material-specific vent depths.

Algorithm
---------
Based on Beaumont 2007 §8.4 heuristics:
  1. Last-fill zones -- bbox corners opposite the gate.  Air collects at the
     point(s) farthest from the gate along the melt-front path (Beaumont §8.4.1).
  2. Parting-line ribs -- vents are placed at the parting line; depth is
     material-dependent to prevent flash (Beaumont Table 8.4).
  3. Sharp-angle corners -- regions where the cavity geometry creates acute
     pockets that trap air (Beaumont §8.4.3).  Approximated here as corners
     whose interior angle is below a threshold (or explicit input list).

Candidate ranking uses Euclidean distance from gate to each candidate as a
proxy for flow-front arrival time: farthest = highest priority vent.

Vent Depth (Beaumont 2007 Table 8.4)
--------------------------------------
Material class       | Vent depth (mm)
---------------------|----------------
ABS, PS, HIPS, PPO   | 0.025 - 0.040
PP, PE (polyolefins) | 0.020 - 0.030
PC, PMMA             | 0.025 - 0.035
POM (acetal, Delrin) | 0.013 - 0.020
PA (Nylon 6, 66)     | 0.013 - 0.020
PBT, PET (polyester) | 0.013 - 0.020
LCP, PPS             | 0.010 - 0.015
TPE / TPU            | 0.020 - 0.030
Default (unknown)    | 0.025 - 0.040

The vent land length is 0.6-1.0 mm; the relief behind the land is >= 0.5 mm
(Beaumont §8.4.5).

Honest-flag
-----------
This is a **geometric heuristic** only.  It does NOT model:
  - Actual melt-front progression (Hele-Shaw / FEM fill simulation).
  - Viscosity, shear thinning, or temperature-dependent flow.
  - Cavity pressure or packing phase.
  - Flash risk as a function of clamp force and mold steel grade.
  - Runner / gate sequence for multi-cavity tools.
For production vent design use Moldflow / Moldex3D / SigmaSoft.

References
----------
Beaumont, J.P. (2007). *Runner and Gating Design Handbook*, 2nd ed.
  Hanser/Gardner.  §8.4 "Mold Venting" -- vent location rules, depth-per-
  material Table 8.4, land length, corner venting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Material vent-depth table  (Beaumont 2007 Table 8.4)
# ---------------------------------------------------------------------------

# (min_mm, max_mm) vent depth per material family
_VENT_DEPTH_TABLE: dict = {
    # Amorphous / semi-crystalline -- high-viscosity / non-crystalline group
    "ABS":    (0.025, 0.040),
    "PS":     (0.025, 0.040),
    "HIPS":   (0.025, 0.040),
    "PPO":    (0.025, 0.040),
    "PC":     (0.025, 0.035),
    "PMMA":   (0.025, 0.035),
    # Polyolefins
    "PP":     (0.020, 0.030),
    "PE":     (0.020, 0.030),
    "LDPE":   (0.020, 0.030),
    "HDPE":   (0.020, 0.030),
    # Crystalline / engineering
    "POM":    (0.013, 0.020),
    "PA":     (0.013, 0.020),
    "PA6":    (0.013, 0.020),
    "PA66":   (0.013, 0.020),
    "PBT":    (0.013, 0.020),
    "PET":    (0.013, 0.020),
    # High-performance
    "LCP":    (0.010, 0.015),
    "PPS":    (0.010, 0.015),
    # Elastomers / TPE
    "TPE":    (0.020, 0.030),
    "TPU":    (0.020, 0.030),
}

_DEFAULT_DEPTH_RANGE = (0.025, 0.040)  # ABS-class default

# Crystalline polymers that require tighter vent depths to prevent flash
_CRYSTALLINE_MATERIALS = frozenset({
    "POM", "PA", "PA6", "PA66", "PBT", "PET", "LCP", "PPS",
})


def _vent_depth_for_material(material: str):
    """Return (min_mm, max_mm) vent depth for *material*.

    Looks up the normalised upper-case material key in the Beaumont Table 8.4
    map.  Falls back to the ABS-class default (0.025-0.040 mm) for unknowns.

    Reference: Beaumont 2007 Table 8.4.
    """
    key = material.strip().upper()
    return _VENT_DEPTH_TABLE.get(key, _DEFAULT_DEPTH_RANGE)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CavityBbox:
    """Axis-aligned bounding box of the injection-mold cavity.

    Parameters
    ----------
    width_mm  : X dimension (mm).  Must be > 0.
    depth_mm  : Y dimension (mm).  Must be > 0.
    height_mm : Z dimension (mm).  Must be > 0.
    origin    : (x0, y0, z0) of the minimum-coordinate corner.  Default (0,0,0).
    """

    width_mm: float
    depth_mm: float
    height_mm: float
    origin: tuple = (0.0, 0.0, 0.0)

    def __post_init__(self) -> None:
        for name, val in [
            ("width_mm", self.width_mm),
            ("depth_mm", self.depth_mm),
            ("height_mm", self.height_mm),
        ]:
            if val <= 0.0:
                raise ValueError(f"{name} must be > 0, got {val}")

    @property
    def center(self):
        x0, y0, z0 = self.origin
        return (
            x0 + self.width_mm / 2.0,
            y0 + self.depth_mm / 2.0,
            z0 + self.height_mm / 2.0,
        )

    def parting_line_corners(self):
        """Return the 4 parting-line corners (bottom face, z = origin z).

        In a simple vertical-pull mold the parting surface is at the bottom of
        the cavity (z = z0).  Vents are most accessible at these corners
        (Beaumont §8.4.2).
        """
        x0, y0, z0 = self.origin
        x1 = x0 + self.width_mm
        y1 = y0 + self.depth_mm
        return [
            (x0, y0, z0),
            (x1, y0, z0),
            (x0, y1, z0),
            (x1, y1, z0),
        ]


@dataclass
class VentLocation:
    """A single recommended air-vent position.

    Parameters
    ----------
    position        : (x, y, z) in the cavity coordinate system.
    reason          : why this location was selected (e.g. 'last_fill', 'parting_rib',
                      'sharp_corner').
    depth_min_mm    : minimum vent channel depth (material-specific).
    depth_max_mm    : maximum vent channel depth (material-specific).
    recommended_depth_mm : midpoint of the depth range (use this for first-off).
    land_length_mm  : land length behind the vent (Beaumont §8.4.5).
    priority        : 1 = highest (last-fill corners), 2 = parting-line rib,
                      3 = supplementary corner.
    distance_from_gate_mm : Euclidean distance from gate to this vent (fill-front proxy).
    advisory        : human-readable note.
    """

    position: tuple
    reason: str
    depth_min_mm: float
    depth_max_mm: float
    recommended_depth_mm: float
    land_length_mm: float
    priority: int
    distance_from_gate_mm: float
    advisory: str


@dataclass
class VentPlacementResult:
    """Result of air-vent placement optimisation.

    Parameters
    ----------
    vent_positions      : list of (x, y, z) for each recommended vent.
    vent_locations      : full VentLocation objects with depth, reason, priority.
    depth_per_material  : dict with 'material', 'depth_min_mm', 'depth_max_mm',
                          'recommended_depth_mm', 'is_crystalline', 'reference'.
    count               : number of vents recommended.
    recommendations     : human-readable advisory strings.
    warnings            : honest-flag and scope caveats.
    """

    vent_positions: list
    vent_locations: list
    depth_per_material: dict
    count: int
    recommendations: list
    warnings: list


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _dist3(a, b) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


# ---------------------------------------------------------------------------
# Candidate generation
# ---------------------------------------------------------------------------

def _last_fill_candidates(bbox: CavityBbox, gate_position, n: int = 4):
    """Return (position, reason, priority) for the *n* corners farthest from the gate.

    Beaumont §8.4.1: "Vents should be placed at the last areas to fill.
    These are typically the areas farthest from the gate."

    For a bbox we use all 8 corners as candidates and take the farthest *n*.
    Priority 1 = last-fill (most critical).
    """
    corners = []
    x0, y0, z0 = bbox.origin
    x1 = x0 + bbox.width_mm
    y1 = y0 + bbox.depth_mm
    z1 = z0 + bbox.height_mm
    for x in (x0, x1):
        for y in (y0, y1):
            for z in (z0, z1):
                corners.append((x, y, z))

    ranked = sorted(corners, key=lambda c: _dist3(gate_position, c), reverse=True)
    return [
        (pos, "last_fill", 1)
        for pos in ranked[:n]
    ]


def _parting_line_rib_candidates(bbox: CavityBbox, gate_position):
    """Return parting-line rib vent candidates (Beaumont §8.4.2).

    Rib features at the parting line are a preferred vent location because:
      - The parting plane provides the natural seam for vent slots.
      - Ribs create localised high-pressure pockets as the melt enters.

    Approximated here as the mid-edge points on the bottom (parting) face.
    Priority 2.
    """
    x0, y0, z0 = bbox.origin
    x1 = x0 + bbox.width_mm
    y1 = y0 + bbox.depth_mm
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0

    candidates = [
        (cx, y0, z0),   # front mid
        (cx, y1, z0),   # back mid
        (x0, cy, z0),   # left mid
        (x1, cy, z0),   # right mid
    ]

    return [
        (pos, "parting_rib", 2)
        for pos in candidates
    ]


def _sharp_corner_candidates(bbox: CavityBbox, gate_position):
    """Return vent candidates at sharp-corner pockets (Beaumont §8.4.3).

    Sharp interior corners trap air because the melt front wraps around the
    outside and seals the corner before air can escape.  In a bbox model all
    four top corners are sharp (90 degrees) relative to the vertical pull direction.
    Priority 3.
    """
    x0, y0, z0 = bbox.origin
    x1 = x0 + bbox.width_mm
    y1 = y0 + bbox.depth_mm
    z1 = z0 + bbox.height_mm

    top_corners = [
        (x0, y0, z1),
        (x1, y0, z1),
        (x0, y1, z1),
        (x1, y1, z1),
    ]

    return [
        (pos, "sharp_corner", 3)
        for pos in top_corners
    ]


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def optimize_vent_placement(
    cavity_bbox: CavityBbox,
    gate_position,
    material: str = "ABS",
    max_vents: int = 8,
    include_parting_ribs: bool = True,
    include_corner_vents: bool = True,
    avoid_functional_zones=None,
) -> VentPlacementResult:
    """Recommend air-vent locations for an injection-mold cavity.

    Parameters
    ----------
    cavity_bbox     : CavityBbox -- the cavity bounding box (width x depth x height).
    gate_position   : (x, y, z) gate location in the cavity coordinate system.
    material        : material name string (e.g. 'ABS', 'PP', 'POM', 'PA66').
                      Controls vent depth per Beaumont Table 8.4.
    max_vents       : cap on total recommended vents.  Default 8.
    include_parting_ribs  : include parting-line rib candidates (default True).
    include_corner_vents  : include sharp-corner pocket candidates (default True).
    avoid_functional_zones : list of (cx, cy, cz, radius_mm) -- vent candidates within
                      these spheres are excluded (functional/cosmetic surfaces).

    Returns
    -------
    VentPlacementResult with vent locations, depths, advisory, and honest-flag warnings.

    Algorithm (Beaumont 2007 §8.4)
    --------------------------------
    1. Last-fill candidates: 4 bbox corners farthest from gate (priority 1).
    2. Parting-line rib candidates: 4 mid-edge points on the parting face (priority 2).
    3. Sharp-corner candidates: 4 top corners (priority 3).
    4. Filter candidates inside avoid_functional_zones.
    5. Deduplicate by position.
    6. Sort by (priority, distance_from_gate DESC).
    7. Cap at max_vents.
    8. Assign material-specific vent depth from Beaumont Table 8.4.

    Honest-flag
    -----------
    Geometric heuristic only -- does NOT model actual melt-front progression,
    viscosity, shear thinning, cavity pressure, packing phase, or flash risk.
    For production vent design use Moldflow / Moldex3D / SigmaSoft.

    References
    ----------
    Beaumont 2007 §8.4 "Mold Venting"; Table 8.4 vent depths per material.
    """
    if max_vents < 1:
        raise ValueError(f"max_vents must be >= 1, got {max_vents}")

    if avoid_functional_zones is None:
        avoid_functional_zones = []

    # -- Material depth lookup -----------------------------------------------
    depth_min, depth_max = _vent_depth_for_material(material)
    recommended_depth = round((depth_min + depth_max) / 2.0, 4)
    is_crystalline = material.strip().upper() in _CRYSTALLINE_MATERIALS

    depth_info = {
        "material": material,
        "depth_min_mm": depth_min,
        "depth_max_mm": depth_max,
        "recommended_depth_mm": recommended_depth,
        "is_crystalline": is_crystalline,
        "reference": "Beaumont 2007 Table 8.4",
        "note": (
            "Crystalline polymers (POM, PA, PBT, PET, LCP, PPS) require shallower "
            "vents (0.010-0.020 mm) to prevent flash due to low melt viscosity."
            if is_crystalline
            else
            "Amorphous/polyolefin materials allow 0.020-0.040 mm vent depth."
        ),
    }

    # -- Collect candidates --------------------------------------------------
    raw = []

    raw.extend(_last_fill_candidates(cavity_bbox, gate_position, n=4))
    if include_parting_ribs:
        raw.extend(_parting_line_rib_candidates(cavity_bbox, gate_position))
    if include_corner_vents:
        raw.extend(_sharp_corner_candidates(cavity_bbox, gate_position))

    # -- Filter avoid-zones --------------------------------------------------
    def _in_avoid(pos):
        for cx, cy, cz, r in avoid_functional_zones:
            if _dist3(pos, (cx, cy, cz)) <= r:
                return True
        return False

    filtered = [(pos, reason, pri) for pos, reason, pri in raw if not _in_avoid(pos)]

    # -- Deduplicate ---------------------------------------------------------
    seen = set()
    unique = []
    for pos, reason, pri in filtered:
        key = (round(pos[0], 5), round(pos[1], 5), round(pos[2], 5))
        if key not in seen:
            seen.add(key)
            unique.append((pos, reason, pri))

    # -- Sort: priority ASC, then distance from gate DESC --------------------
    unique.sort(key=lambda t: (t[2], -_dist3(gate_position, t[0])))

    # -- Cap at max_vents ----------------------------------------------------
    selected = unique[:max_vents]

    # -- Build VentLocation objects ------------------------------------------
    land_mm = 0.8  # Beaumont §8.4.5 default
    vent_locations = []

    _reason_desc = {
        "last_fill":    "Last-fill zone -- farthest corner from gate; highest trapped-air risk (Beaumont §8.4.1).",
        "parting_rib":  "Parting-line rib -- preferred vent site at mold parting surface (Beaumont §8.4.2).",
        "sharp_corner": "Sharp-corner pocket -- acute angle traps air ahead of melt front (Beaumont §8.4.3).",
    }

    for pos, reason, pri in selected:
        dist = _dist3(gate_position, pos)
        advisory = _reason_desc.get(reason, reason)
        if is_crystalline:
            advisory += (
                f"  Use depth {depth_min:.3f}-{depth_max:.3f} mm for {material} "
                "(crystalline; shallow vent prevents flash)."
            )
        else:
            advisory += (
                f"  Use depth {depth_min:.3f}-{depth_max:.3f} mm for {material}."
            )

        vent_locations.append(VentLocation(
            position=pos,
            reason=reason,
            depth_min_mm=depth_min,
            depth_max_mm=depth_max,
            recommended_depth_mm=recommended_depth,
            land_length_mm=land_mm,
            priority=pri,
            distance_from_gate_mm=round(dist, 3),
            advisory=advisory,
        ))

    vent_positions = [v.position for v in vent_locations]

    # -- Recommendations -----------------------------------------------------
    recs = []

    if vent_locations:
        top = vent_locations[0]
        recs.append(
            f"Primary vent at ({top.position[0]:.1f}, {top.position[1]:.1f}, "
            f"{top.position[2]:.1f}) mm -- {top.reason.replace('_', ' ')} "
            f"(dist from gate approx {top.distance_from_gate_mm:.1f} mm)."
        )

    last_fill_count = sum(1 for v in vent_locations if v.reason == "last_fill")
    if last_fill_count:
        recs.append(
            f"{last_fill_count} last-fill vent(s) at corners opposite the gate "
            f"(Beaumont 2007 §8.4.1). These are the highest-priority locations."
        )

    parting_count = sum(1 for v in vent_locations if v.reason == "parting_rib")
    if parting_count:
        recs.append(
            f"{parting_count} parting-line rib vent(s) at mid-edge positions on the "
            f"parting face (Beaumont §8.4.2). Machine vent slots into the parting steel."
        )

    corner_count = sum(1 for v in vent_locations if v.reason == "sharp_corner")
    if corner_count:
        recs.append(
            f"{corner_count} sharp-corner vent(s) at top face corners "
            f"(Beaumont §8.4.3). Use vent inserts or sintered steel if accessible."
        )

    recs.append(
        f"Vent depth for {material}: {depth_min:.3f}-{depth_max:.3f} mm "
        f"(recommended {recommended_depth:.4f} mm); land length 0.6-1.0 mm "
        f"(use 0.8 mm); relief behind land >= 0.5 mm (Beaumont Table 8.4, §8.4.5)."
    )

    if is_crystalline:
        recs.append(
            f"{material} is a crystalline polymer with low melt viscosity. "
            "Use the shallower end of the depth range to prevent flash. "
            "Verify with a short-shot study (Beaumont §8.4)."
        )

    if avoid_functional_zones:
        recs.append(
            f"Excluded {len(avoid_functional_zones)} avoid zone(s) from vent placement "
            "(functional/cosmetic surfaces). Verify final vent locations against part drawing."
        )

    # -- Warnings ------------------------------------------------------------
    warnings = [
        "HONEST-FLAG: geometric heuristic only -- does NOT model actual melt-front "
        "progression, viscosity, shear thinning, cavity pressure, packing phase, "
        "or flash risk as a function of clamp force. Vent locations are based on "
        "distance from gate (last-fill proxy) and bbox geometry only. "
        "For production vent design use Moldflow / Moldex3D / SigmaSoft "
        "(Beaumont 2007 §8.4)."
    ]

    if not vent_locations:
        warnings.append(
            "No vent candidates remain after applying avoid zones. "
            "Relax avoid-zone constraints or add vent inserts manually."
        )

    return VentPlacementResult(
        vent_positions=vent_positions,
        vent_locations=vent_locations,
        depth_per_material=depth_info,
        count=len(vent_locations),
        recommendations=recs,
        warnings=warnings,
    )
