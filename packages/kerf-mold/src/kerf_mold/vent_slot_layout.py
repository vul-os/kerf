"""
kerf_mold.vent_slot_layout
==========================
Propose a vent slot layout (count, width, spacing) for an injection-mold
cavity given the parting-line perimeter and worst-case air-displacement volume.

Based on:
  Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
    §8.5 Vent Slot Count and Width.
  Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
    Hanser 2001, §6.4 Vent Slot Design.

Background
----------
During injection filling, the displaced air must escape through vent slots
machined at the parting line (and/or runner/gate system).  Insufficient
venting causes:
  • Short shot (incomplete fill) when backpressure exceeds fill pressure.
  • Burn marks / diesel effect (adiabatic compression raises air to ~300–600 °C).
  • Weld-line weakness at last-to-fill convergence zones.
  • Jetting and cosmetic surface defects.

Beaumont 2007 §8.5 Rule (total vent area)
------------------------------------------
  total_vent_area_mm2 ≥ 0.5 % × projected_cavity_area_mm2      (baseline)

  Projected cavity area is estimated from the cavity volume and a nominal
  part-wall-thickness assumption.  Since this tool takes cavity volume and
  perimeter (not projected area directly), we approximate:

      projected_area ≈ cavity_volume / wall_thickness_estimate

  where wall_thickness_estimate = 3.0 mm (typical mid-range injection-mold wall).

  For fast injection (injection_speed > 50 cm³/s), Beaumont §8.5 recommends
  increasing the total vent area by a scaling factor:

      vent_area_factor = max(1.0, injection_speed / 50.0)

  so that:

      required_total_vent_area = 0.005 × projected_area × vent_area_factor

Individual vent slot geometry
------------------------------
  slot_width = 6 mm  — Beaumont 2007 §8.5 + Menges 2001 §6.4: standard
    parting-line vent slot width; polymer-specific vent depth handles the
    flash/short-shot balance (see vent_depth_check.py); width of 6 mm is the
    recommended default for most engineering thermoplastics.

  slot_depth = polymer-specific (from VENT_DEPTH_DB in vent_depth_check.py,
    midpoint of the recommended range).  Used only to compute per-slot area.

  per_slot_area_mm2 = slot_width_mm × slot_depth_mm × slot_length_mm
    (slot_length defaulted to 6 mm land length per Beaumont §8.3.2).

Slot count calculation
----------------------
  num_vent_slots = ceil(required_total_vent_area / per_slot_area)

  Minimum enforced: 4 slots (Beaumont §8.5: at least one per quadrant of the
  parting line; Menges 2001 §6.4: minimum 4 vents for any non-trivial cavity).

  Maximum enforced: floor(parting_line_perimeter_mm / (slot_width_mm + 10.0))
    — slots must be separated by at least 10 mm of parting-line steel
      (Menges 2001 §6.4 mold-sealing surface requirement).

Spacing
-------
  spacing_mm = parting_line_perimeter_mm / num_vent_slots

Honest caveats
--------------
  1. The 0.5 % projected-area rule is a heuristic derived from production
     experience documented in Beaumont 2007 §8.5.  It is NOT a first-principles
     fluid-dynamic calculation.  The actual required vent area depends on:
     injection speed profile, melt viscosity, cavity geometry, and the number
     and location of last-to-fill zones.
  2. The wall-thickness assumption of 3 mm for area estimation is a placeholder.
     Thin-wall parts (<1 mm) require proportionally more venting; the formula
     underestimates the need in those cases.
  3. Last-to-fill regions should concentrate vent slots.  This tool proposes a
     uniformly spaced layout.  Use mold_optimize_vent_placement for geometric
     location optimisation.
  4. The only definitive check is a fill simulation (Moldflow / Moldex3D /
     SigmaSoft) followed by a mold-trial visual inspection.
  5. Vent depth (flash vs short-shot balance) is handled separately by
     mold_check_vent_depth.  This tool sizes count and width only.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §8.5 Vent Slot Count and Width.
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §6.4 Vent Slot Design.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Tuple


# ---------------------------------------------------------------------------
# Polymer vent depth database (midpoints used for slot-area sizing)
# Beaumont 2007 Table 8.2 + Menges 2001 §6.4 Table 6.7 — (min_mm, max_mm)
# ---------------------------------------------------------------------------

#: Polymer-specific vent depth range (min_mm, max_mm).
#: Source: Beaumont 2007 Table 8.2 + Menges 2001 §6.4 Table 6.7.
POLYMER_VENT_DEPTH_RANGE: Dict[str, Tuple[float, float]] = {
    "ABS":  (0.025, 0.038),
    "PC":   (0.013, 0.025),
    "PP":   (0.025, 0.050),
    "PA66": (0.013, 0.025),
    "POM":  (0.013, 0.025),
    "PMMA": (0.025, 0.038),
    "PE":   (0.038, 0.075),
}

#: Fallback vent depth range for unknown polymers.
_FALLBACK_DEPTH_RANGE: Tuple[float, float] = (0.013, 0.038)

# ---------------------------------------------------------------------------
# Physical / design constants
# ---------------------------------------------------------------------------

#: Standard vent slot width (mm) per Beaumont 2007 §8.5 + Menges 2001 §6.4.
VENT_SLOT_WIDTH_MM: float = 6.0

#: Standard vent land length (mm) used for slot-area calculation.
#: Beaumont 2007 §8.3.2 recommends ≥ 0.8 mm; 6 mm is the typical land length
#: before the relief slot.
VENT_LAND_LENGTH_MM: float = 6.0

#: Beaumont 2007 §8.5 required total vent area as a fraction of projected
#: cavity area (baseline, slow injection).
BEAUMONT_VENT_AREA_FRACTION: float = 0.005  # 0.5 %

#: Reference injection speed (cm³/s) for the baseline vent-area fraction.
#: Speeds above this require proportionally more venting (Beaumont §8.5).
REFERENCE_INJECTION_SPEED_CM3_S: float = 50.0

#: Minimum number of vent slots (Beaumont §8.5 + Menges §6.4: at least one
#: per quadrant of the parting line, minimum 4).
MIN_VENT_SLOTS: int = 4

#: Minimum steel bridge between adjacent vent slots (mm).
#: Menges 2001 §6.4: parting-line sealing surface must retain ≥ 10 mm of
#: uninterrupted steel between vents to prevent micro-flash and parting-line
#: crush damage.
MIN_STEEL_BRIDGE_MM: float = 10.0

#: Assumed nominal wall thickness (mm) for projecting cavity volume to area.
#: Used only when projected_area is not supplied directly.
NOMINAL_WALL_THICKNESS_MM: float = 3.0

#: Honest caveat text appended to every report.
_HONEST_CAVEAT = (
    "Heuristic rule from Beaumont 2007 §8.5 + Menges 2001 §6.4. "
    "The 0.5 % projected-area rule is derived from production experience, "
    "NOT a first-principles fluid-dynamic calculation. "
    "Actual required vent area depends on injection speed profile, melt viscosity, "
    "cavity geometry, and last-to-fill zone locations. "
    "Wall thickness is assumed 3 mm for area estimation; thin-wall parts (<1 mm) "
    "require proportionally more venting. "
    "This tool proposes a uniformly spaced layout — use mold_optimize_vent_placement "
    "to locate vents at last-to-fill regions. "
    "Vent depth (flash vs short-shot) is handled separately by mold_check_vent_depth. "
    "Confirm by fill simulation (Moldflow / Moldex3D / SigmaSoft) and "
    "mold-trial visual inspection for short shots and burn marks."
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MoldVolumeSpec:
    """Input specification for vent-slot layout sizing.

    Attributes
    ----------
    cavity_volume_cm3 : float
        Total injection cavity volume [cm³].  Must be > 0.
    parting_line_perimeter_mm : float
        Total length of the parting-line perimeter available for vent slots
        [mm].  Must be > 0.
    polymer_grade : str
        Polymer material grade.  Case-insensitive.  Supported: ABS, PC, PP,
        PA66, POM, PMMA, PE.  Unknown grades use a fallback vent depth range.
    injection_speed_cm3_s : float
        Volumetric injection speed [cm³/s].  Beaumont 2007 §8.5: speeds above
        50 cm³/s require proportionally larger total vent area.  Must be > 0.
    """

    cavity_volume_cm3: float
    parting_line_perimeter_mm: float
    polymer_grade: str
    injection_speed_cm3_s: float

    def __post_init__(self) -> None:
        # Normalise polymer grade to uppercase
        object.__setattr__(self, "polymer_grade", self.polymer_grade.strip().upper())
        if self.cavity_volume_cm3 <= 0.0:
            raise ValueError(
                f"cavity_volume_cm3 must be > 0, got {self.cavity_volume_cm3}"
            )
        if self.parting_line_perimeter_mm <= 0.0:
            raise ValueError(
                f"parting_line_perimeter_mm must be > 0, "
                f"got {self.parting_line_perimeter_mm}"
            )
        if self.injection_speed_cm3_s <= 0.0:
            raise ValueError(
                f"injection_speed_cm3_s must be > 0, "
                f"got {self.injection_speed_cm3_s}"
            )


@dataclass
class VentSlotLayoutReport:
    """Result of the vent slot layout calculation.

    Attributes
    ----------
    num_vent_slots : int
        Recommended number of vent slots around the parting line.
    vent_slot_width_mm : float
        Width of each vent slot [mm].
    vent_slot_spacing_mm : float
        Centre-to-centre spacing between adjacent vent slots [mm].
    total_vent_width_mm : float
        Sum of all slot widths (num_vent_slots × vent_slot_width_mm) [mm].
    air_displacement_rate_cm3_s : float
        Estimated air displacement rate = injection_speed_cm3_s (the cavity
        fills at the same volumetric rate as the melt injection) [cm³/s].
    adequate : bool
        True if the layout satisfies the Beaumont 0.5 %-area rule at the
        given injection speed AND the slots fit on the parting line with the
        minimum steel bridge constraint.
    honest_caveat : str
        Plain-language statement of model limitations.
    """

    num_vent_slots: int
    vent_slot_width_mm: float
    vent_slot_spacing_mm: float
    total_vent_width_mm: float
    air_displacement_rate_cm3_s: float
    adequate: bool
    honest_caveat: str = field(default="")


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def generate_vent_slot_layout(spec: MoldVolumeSpec) -> VentSlotLayoutReport:
    """Propose a vent slot layout per Beaumont 2007 §8.5 + Menges 2001 §6.4.

    Algorithm
    ---------
    1. Estimate projected cavity area:
         projected_area_mm2 = cavity_volume_cm3 × 1000 / NOMINAL_WALL_THICKNESS_MM
       (cm³ → mm³ via ×1000; divide by 3 mm nominal wall to get area in mm²).

    2. Apply Beaumont 0.5 %-area rule with speed scaling:
         vent_area_factor = max(1.0, injection_speed_cm3_s / REFERENCE_SPEED)
         required_total_vent_area_mm2 = BEAUMONT_FRACTION × projected_area × factor

    3. Determine per-slot area using polymer-specific vent depth midpoint:
         depth_mid_mm = (min + max) / 2  from POLYMER_VENT_DEPTH_RANGE
         per_slot_area_mm2 = VENT_SLOT_WIDTH_MM × depth_mid_mm × VENT_LAND_LENGTH_MM

    4. Number of slots:
         n = ceil(required_total_vent_area / per_slot_area)
         n = max(n, MIN_VENT_SLOTS)
         max_slots = floor(parting_line_perimeter / (VENT_SLOT_WIDTH + MIN_BRIDGE))
         n = min(n, max_slots)   [if perimeter is too short; adequacy flagged false]

    5. Spacing:
         spacing_mm = parting_line_perimeter_mm / n

    6. Adequacy check:
         actual_total_area = n × per_slot_area
         adequate = (actual_total_area >= required_total_vent_area)
                    AND (n >= MIN_VENT_SLOTS)
                    AND spacing_mm >= (VENT_SLOT_WIDTH + MIN_BRIDGE)

    Parameters
    ----------
    spec : MoldVolumeSpec
        Cavity specification.

    Returns
    -------
    VentSlotLayoutReport
    """
    grade = spec.polymer_grade
    depth_min, depth_max = POLYMER_VENT_DEPTH_RANGE.get(grade, _FALLBACK_DEPTH_RANGE)
    depth_mid_mm = (depth_min + depth_max) / 2.0

    # 1. Projected cavity area (mm²)
    cavity_volume_mm3 = spec.cavity_volume_cm3 * 1000.0  # cm³ → mm³
    projected_area_mm2 = cavity_volume_mm3 / NOMINAL_WALL_THICKNESS_MM

    # 2. Required total vent area with speed scaling
    vent_area_factor = max(1.0, spec.injection_speed_cm3_s / REFERENCE_INJECTION_SPEED_CM3_S)
    required_total_vent_area_mm2 = (
        BEAUMONT_VENT_AREA_FRACTION * projected_area_mm2 * vent_area_factor
    )

    # 3. Per-slot area: width × depth × land_length
    per_slot_area_mm2 = VENT_SLOT_WIDTH_MM * depth_mid_mm * VENT_LAND_LENGTH_MM

    # 4. Slot count
    n_required = math.ceil(required_total_vent_area_mm2 / per_slot_area_mm2)
    n_slots = max(n_required, MIN_VENT_SLOTS)

    # Maximum slots that fit on the perimeter with the steel-bridge constraint
    max_slots = int(
        spec.parting_line_perimeter_mm / (VENT_SLOT_WIDTH_MM + MIN_STEEL_BRIDGE_MM)
    )
    # Ensure at least 1 slot is always possible (degenerate very-small perimeters)
    max_slots = max(max_slots, 1)

    perimeter_constrained = n_slots > max_slots
    if perimeter_constrained:
        n_slots = max_slots

    # 5. Spacing
    spacing_mm = spec.parting_line_perimeter_mm / n_slots

    # 6. Adequacy
    actual_total_area_mm2 = n_slots * per_slot_area_mm2
    area_adequate = actual_total_area_mm2 >= required_total_vent_area_mm2
    count_adequate = n_slots >= MIN_VENT_SLOTS
    spacing_adequate = spacing_mm >= (VENT_SLOT_WIDTH_MM + MIN_STEEL_BRIDGE_MM)
    adequate = area_adequate and count_adequate and spacing_adequate

    # Air displacement rate = injection speed (cavity fills at melt injection rate)
    air_displacement_rate = spec.injection_speed_cm3_s

    return VentSlotLayoutReport(
        num_vent_slots=n_slots,
        vent_slot_width_mm=VENT_SLOT_WIDTH_MM,
        vent_slot_spacing_mm=round(spacing_mm, 3),
        total_vent_width_mm=round(n_slots * VENT_SLOT_WIDTH_MM, 3),
        air_displacement_rate_cm3_s=air_displacement_rate,
        adequate=adequate,
        honest_caveat=_HONEST_CAVEAT,
    )
