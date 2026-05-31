"""
kerf_mold.vent_depth_check
==========================
Verify that a mold parting-line vent depth (air-escape gap) is within the
polymer-specific recommended range from Beaumont 2007 §8.3 (Vent Design
Guidelines) + Menges 2001 §6.4 Table 6.7.

Background
----------
During injection, air trapped in the cavity must escape through vents at the
parting line.  If the vent is too shallow the air cannot escape fast enough:
the trapped gas compresses, heats adiabatically, and causes either a short shot
(incomplete fill) or burn marks (diesel effect).  If the vent is too deep the
molten polymer flows into the gap and produces flash — thin fins of plastic at
the parting line that require trimming and may damage the mold sealing surface.

The acceptable vent depth is polymer-specific because it is controlled by the
viscosity of the melt at injection temperature (low viscosity → easy to flash →
tight tolerance on the upper end) and the compressibility / surface tension of
the escaping air/vapour (sets the lower end).

Recommended vent depths — Beaumont 2007 Table 8.2 + Menges 2001 §6.4 Table 6.7
--------------------------------------------------------------------------------
  ABS   — 0.025–0.038 mm  (amorphous; moderate viscosity)
  PC    — 0.013–0.025 mm  (amorphous; low viscosity at processing temp)
  PP    — 0.025–0.050 mm  (semi-crystalline; moderate–high viscosity)
  PA66  — 0.013–0.025 mm  (semi-crystalline; low viscosity when molten)
  POM   — 0.013–0.025 mm  (semi-crystalline; low melt viscosity; reactive)
  PMMA  — 0.025–0.038 mm  (amorphous; moderate viscosity)
  PE    — 0.038–0.075 mm  (semi-crystalline; high melt viscosity; high PE-HD end)

Land length (the flat section behind the vent gap, before the relief slot)
should typically be 0.8–3.0 mm (Beaumont 2007 §8.3.2 recommends 0.8 mm minimum;
wider land improves flash resistance but increases gas backpressure).  Default
1.5 mm.

Honest caveats
--------------
1. These are empirical handbook ranges derived from production practice.
   The actual safe vent depth for a given tool depends on melt temperature,
   injection speed, mold steel surface finish, land length, and part geometry.
2. Flash onset depends on the viscosity of the specific resin batch and its
   additives (fillers, flame retardants, plasticisers).  Two grades of the
   same polymer can have significantly different flash limits.
3. Vent depth alone does not ensure adequate venting: vent width, number of
   vents, and vent location all affect whether the cavity fills correctly.
4. The only definitive test is a mold trial with visual inspection for flash
   and short shots, combined if necessary with gas-trap simulation
   (Moldflow / Moldex3D / SigmaSoft).
5. Do NOT use this tool as a substitute for mold-trial flash inspection and
   process optimisation.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §8.3 Vent Design Guidelines + Table 8.2 Recommended vent depths.
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §6.4 Vent design + Table 6.7 Polymer-specific vent depths (mm).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple


# ---------------------------------------------------------------------------
# Polymer-specific vent depth database
# Beaumont 2007 Table 8.2 + Menges 2001 §6.4 Table 6.7
# Values in mm.
# ---------------------------------------------------------------------------

#: Recommended vent depth range (min_mm, max_mm) per polymer.
#: Source: Beaumont 2007 Table 8.2 + Menges 2001 §6.4 Table 6.7.
VENT_DEPTH_DB: Dict[str, Tuple[float, float]] = {
    "ABS":  (0.025, 0.038),   # amorphous; moderate viscosity
    "PC":   (0.013, 0.025),   # amorphous; low viscosity at processing temp
    "PP":   (0.025, 0.050),   # semi-crystalline; moderate–high viscosity
    "PA66": (0.013, 0.025),   # semi-crystalline; low melt viscosity
    "POM":  (0.013, 0.025),   # semi-crystalline; low melt viscosity; reactive
    "PMMA": (0.025, 0.038),   # amorphous; moderate viscosity
    "PE":   (0.038, 0.075),   # semi-crystalline; high melt viscosity (HD end)
}

#: Polymer-specific notes explaining the recommended range.
_POLYMER_NOTES: Dict[str, str] = {
    "ABS": (
        "ABS is amorphous with moderate melt viscosity. "
        "Beaumont 2007 Table 8.2 + Menges 2001 Table 6.7 recommend 0.025–0.038 mm. "
        "Filled / flame-retarded grades should be biased toward the lower end "
        "(additives can reduce viscosity and increase flash risk)."
    ),
    "PC": (
        "PC (polycarbonate) has very low melt viscosity at typical processing "
        "temperatures (280–320 °C). "
        "Beaumont 2007 Table 8.2 + Menges 2001 Table 6.7 recommend 0.013–0.025 mm. "
        "Err toward the lower end (0.013–0.018 mm) for thin-wall or high-speed "
        "injection; higher end only for thick-wall / slow-fill applications."
    ),
    "PP": (
        "PP is semi-crystalline with moderate to high melt viscosity. "
        "Beaumont 2007 Table 8.2 + Menges 2001 Table 6.7 recommend 0.025–0.050 mm. "
        "Rubber-toughened (impact PP) or talc-filled grades: stay below 0.038 mm."
    ),
    "PA66": (
        "PA66 (nylon 6,6) has low melt viscosity when fully molten. "
        "Beaumont 2007 Table 8.2 + Menges 2001 Table 6.7 recommend 0.013–0.025 mm. "
        "Glass-filled grades (e.g. PA66-GF30) may tolerate up to 0.025 mm; "
        "unfilled PA66 should be at the lower end."
    ),
    "POM": (
        "POM (acetal / polyoxymethylene) has low melt viscosity and releases "
        "formaldehyde under excess heat. "
        "Beaumont 2007 Table 8.2 + Menges 2001 Table 6.7 recommend 0.013–0.025 mm. "
        "Because flash on POM is brittle and can jam slides, use 0.013–0.018 mm "
        "for tight tolerances."
    ),
    "PMMA": (
        "PMMA (acrylic) is amorphous with moderate melt viscosity. "
        "Beaumont 2007 Table 8.2 + Menges 2001 Table 6.7 recommend 0.025–0.038 mm. "
        "Optical-grade PMMA: mold trial mandatory to confirm no cosmetic burn marks."
    ),
    "PE": (
        "PE (polyethylene, both LDPE and HDPE) is semi-crystalline with "
        "relatively high melt viscosity. "
        "Beaumont 2007 Table 8.2 + Menges 2001 Table 6.7 recommend 0.038–0.075 mm. "
        "LDPE (softer, lower viscosity) should be at the lower end 0.038–0.050 mm; "
        "HDPE at 0.050–0.075 mm. "
        "Flash on PE is ductile and can be trimmed but spoils cosmetics."
    ),
}

#: Fallback note for unknown polymers.
_UNKNOWN_POLYMER_NOTE = (
    "Polymer not found in the Beaumont 2007 / Menges 2001 vent-depth database. "
    "A general-purpose fallback range of 0.013–0.038 mm is returned. "
    "Consult the resin supplier's processing guide or a material-specific "
    "reference for the correct range before cutting the vent."
)

#: Fallback range used when polymer is not in the database.
_FALLBACK_RANGE: Tuple[float, float] = (0.013, 0.038)

#: Honest caveat appended to every report.
_HONEST_CAVEAT = (
    "Empirical handbook ranges from Beaumont 2007 §8.3 Table 8.2 + "
    "Menges 2001 §6.4 Table 6.7. "
    "Actual safe vent depth depends on resin batch viscosity, melt temperature, "
    "injection speed, mold steel surface finish, land length, and part geometry. "
    "Filled / flame-retarded / rubber-toughened grades may flash at depths "
    "within the 'correct' band for the base resin. "
    "Do NOT rely on this check alone — confirm by mold trial with visual "
    "flash inspection and, if needed, gas-trap simulation "
    "(Moldflow / Moldex3D / SigmaSoft). "
    "Vent width and vent count also affect whether the cavity fills correctly; "
    "this tool checks depth only."
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class VentSpec:
    """Specification for a mold parting-line vent to be checked.

    Attributes
    ----------
    polymer_grade : str
        Polymer material.  Case-insensitive.  Supported: ABS, PC, PP, PA66,
        POM, PMMA, PE.  Unknown grades receive a fallback range with a caveat.
    proposed_depth_mm : float
        Proposed vent depth (parting-line air-escape gap) [mm].  Must be > 0.
    land_length_mm : float
        Length of the vent land (flat sealing surface behind the gap) [mm].
        Default 1.5 mm.  Beaumont 2007 §8.3.2 recommends ≥ 0.8 mm.
    vent_width_mm : float
        Width of the vent slot [mm].  Default 6.0 mm.  Used for context only;
        this check does not validate width.
    """

    polymer_grade: str
    proposed_depth_mm: float
    land_length_mm: float = 1.5
    vent_width_mm: float = 6.0

    def __post_init__(self) -> None:
        normalised = self.polymer_grade.strip().upper()
        object.__setattr__(self, "polymer_grade", normalised)
        if self.proposed_depth_mm <= 0.0:
            raise ValueError(
                f"proposed_depth_mm must be > 0, got {self.proposed_depth_mm}"
            )
        if self.land_length_mm < 0.0:
            raise ValueError(
                f"land_length_mm must be >= 0, got {self.land_length_mm}"
            )
        if self.vent_width_mm <= 0.0:
            raise ValueError(
                f"vent_width_mm must be > 0, got {self.vent_width_mm}"
            )


@dataclass
class VentDepthReport:
    """Report produced by check_vent_depth.

    Attributes
    ----------
    recommended_depth_min_mm : float
        Lower bound of the recommended vent depth range [mm].
    recommended_depth_max_mm : float
        Upper bound of the recommended vent depth range [mm].
    compliant : bool
        True if proposed_depth_mm is within [min, max] inclusive.
    depth_class : str
        One of "too_shallow" | "correct" | "too_deep" | "flash_risk".
        "flash_risk" is used when the depth exceeds the maximum by more than
        25 % (significant flash probability regardless of process tuning).
        "too_deep" is used when the depth exceeds the maximum by 0–25 %.
    polymer_notes : str
        Polymer-specific processing notes from the reference tables.
    honest_caveat : str
        Plain-language statement of model limitations.
    """

    recommended_depth_min_mm: float
    recommended_depth_max_mm: float
    compliant: bool
    depth_class: str          # "too_shallow" | "correct" | "too_deep" | "flash_risk"
    polymer_notes: str
    honest_caveat: str = field(default="")


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

#: Fraction above the max depth beyond which we escalate to "flash_risk".
_FLASH_RISK_FRACTION = 0.25


def check_vent_depth(vent: VentSpec) -> VentDepthReport:
    """Verify a mold vent depth against polymer-specific recommended ranges.

    Uses empirical ranges from Beaumont 2007 §8.3 Table 8.2 +
    Menges 2001 §6.4 Table 6.7.

    Classification rules
    --------------------
    - proposed_depth ≥ min and ≤ max  →  ``correct`` (compliant=True)
    - proposed_depth < min             →  ``too_shallow`` (compliant=False)
      (trapped air → short shot / burn marks)
    - proposed_depth > max and ≤ max × (1 + 0.25)  →  ``too_deep`` (compliant=False)
      (probable flash at parting line)
    - proposed_depth > max × (1 + 0.25)  →  ``flash_risk`` (compliant=False)
      (significant flash risk; 25 % beyond upper limit)

    For unknown polymers a fallback range of 0.013–0.038 mm is used with an
    explanatory note; no ValueError is raised.

    Parameters
    ----------
    vent : VentSpec
        Vent specification to check.

    Returns
    -------
    VentDepthReport
    """
    grade = vent.polymer_grade
    unknown = grade not in VENT_DEPTH_DB
    depth_min, depth_max = VENT_DEPTH_DB.get(grade, _FALLBACK_RANGE)

    d = vent.proposed_depth_mm

    # Classify
    if d < depth_min:
        depth_class = "too_shallow"
        compliant = False
    elif d <= depth_max:
        depth_class = "correct"
        compliant = True
    elif d <= depth_max * (1.0 + _FLASH_RISK_FRACTION):
        depth_class = "too_deep"
        compliant = False
    else:
        depth_class = "flash_risk"
        compliant = False

    # Polymer notes
    if unknown:
        polymer_notes = _UNKNOWN_POLYMER_NOTE
    else:
        polymer_notes = _POLYMER_NOTES[grade]

    return VentDepthReport(
        recommended_depth_min_mm=depth_min,
        recommended_depth_max_mm=depth_max,
        compliant=compliant,
        depth_class=depth_class,
        polymer_notes=polymer_notes,
        honest_caveat=_HONEST_CAVEAT,
    )
