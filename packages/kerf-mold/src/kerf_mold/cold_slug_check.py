"""
kerf_mold.cold_slug_check
=========================
Verify cold-slug well dimensions at runner junctions in a multi-cavity
injection mold against the geometric rules from Beaumont 2007 §6.7
(Cold Slug Wells) and Menges 2001 §6.5.

Background
----------
During injection the leading edge of the polymer melt in the sprue and
primary runners cools rapidly on contact with the cold mold steel.  This
cold leading-edge slug — typically 1–3 °C below the bulk melt temperature —
reaches a junction before the runner system has fully equilibrated.  If it
enters the gate it can cause:

* Flow lines (visible surface streaks at the gate area)
* Cold weld lines / weak knit lines where the slug meets flowing material
  from adjacent cavities
* Incomplete fusion at the weld — tensile strength at the weld may be only
  40–60 % of the parent material strength for amorphous polymers

A cold-slug well is a short dead-end channel cut perpendicular to the runner
at each junction, sized to capture and hold the cold plug until the hot bulk
melt fills the cavity.

Beaumont 2007 §6.7 guidelines
-------------------------------
  Slug well diameter  = 1.5 × runner diameter  (minimum; 1.4–1.6 × acceptable)
  Slug well depth     = 2.0 × runner diameter  (minimum; 1.8–2.2 × acceptable)

The ±20 % tolerance applied here maps to the full 1.2×–1.8× and 1.6×–2.4×
ranges that Beaumont considers acceptable in practice.

Honest caveats
--------------
1. This is a geometric rule-of-thumb only.  Whether the cold slug is actually
   captured depends on melt temperature, injection speed, and the freeze-off
   time of the specific resin at the local steel temperature.
2. High-viscosity or fast-crystallising resins (POM, PA66, LCP) may require
   a larger well than the 1.5 × / 2 × rule suggests because the slug can be
   thicker or advance faster before the well fills with hot material.
3. Glass- or mineral-filled grades (e.g. PA66-GF30, PP-GF20) generate
   fibre-orientation defects at cold slug locations; the well alone does not
   eliminate the surface appearance defect — gating strategy matters.
4. The only definitive validation is a mold trial with visual inspection of
   the gate area and cross-section of a weld specimen.
5. Do NOT use this tool as a substitute for mold-trial cold-slug inspection or
   process simulation (Moldflow / Moldex3D / SigmaSoft).

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §6.7 Cold Slug Wells.
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §6.5 Runner junction design.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Constants — Beaumont 2007 §6.7 nominal ratios + ±20 % tolerance band
# ---------------------------------------------------------------------------

#: Nominal slug-well diameter = DIAMETER_RATIO × runner_diameter
DIAMETER_RATIO: float = 1.5

#: Nominal slug-well depth = DEPTH_RATIO × runner_diameter
DEPTH_RATIO: float = 2.0

#: Allowed fractional deviation from the nominal (±20 %)
TOLERANCE: float = 0.20

#: Honest caveat appended to every report.
_HONEST_CAVEAT = (
    "Geometric rule-of-thumb from Beaumont 2007 §6.7 + Menges 2001 §6.5: "
    "slug well diameter = 1.5 × runner diameter; "
    "slug well depth = 2.0 × runner diameter; ±20 % tolerance band applied. "
    "Actual cold-slug capture effectiveness depends on melt temperature, "
    "injection speed, and resin freeze-off time at the local steel temperature. "
    "Fast-crystallising resins (POM, PA66, LCP) and filled grades (GF/MF) may "
    "require a larger well or a dedicated reverse-taper sprue-puller arrangement. "
    "Confirm by mold trial with visual gate-area inspection and, if needed, "
    "cross-section weld-specimen tensile testing. "
    "Do NOT rely on this check alone — use Moldflow / Moldex3D / SigmaSoft "
    "for full melt-front thermal and weld-line simulation."
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class RunnerJunctionSpec:
    """Specification for one runner junction to be checked.

    Attributes
    ----------
    junction_id : str
        Human-readable label, e.g. ``"J1"`` or ``"primary-left"``.
    runner_diameter_mm : float
        Diameter of the runner leading into this junction [mm].
        Must be > 0.
    slug_well_diameter_mm : float
        Diameter of the cold-slug well cut at this junction [mm].
        Must be > 0.
    slug_well_depth_mm : float
        Depth of the cold-slug well [mm].
        Must be > 0.
    polymer_grade : str
        Informational polymer grade string (e.g. ``"ABS"``, ``"PP-GF30"``).
        Not used in the compliance calculation; surfaced in the report for
        context and to allow callers to add domain-specific notes.
    """

    junction_id: str
    runner_diameter_mm: float
    slug_well_diameter_mm: float
    slug_well_depth_mm: float
    polymer_grade: str

    def __post_init__(self) -> None:
        if self.runner_diameter_mm <= 0.0:
            raise ValueError(
                f"runner_diameter_mm must be > 0, got {self.runner_diameter_mm!r} "
                f"(junction '{self.junction_id}')"
            )
        if self.slug_well_diameter_mm <= 0.0:
            raise ValueError(
                f"slug_well_diameter_mm must be > 0, got "
                f"{self.slug_well_diameter_mm!r} (junction '{self.junction_id}')"
            )
        if self.slug_well_depth_mm <= 0.0:
            raise ValueError(
                f"slug_well_depth_mm must be > 0, got "
                f"{self.slug_well_depth_mm!r} (junction '{self.junction_id}')"
            )


@dataclass
class ColdSlugReport:
    """Report produced by check_cold_slug_design.

    Attributes
    ----------
    junction_results : list[dict]
        One entry per junction.  Each entry contains:

        * ``junction_id``          — str  : junction label
        * ``runner_diameter_mm``   — float: input runner diameter
        * ``slug_well_diameter_mm``— float: input well diameter
        * ``slug_well_depth_mm``   — float: input well depth
        * ``polymer_grade``        — str  : informational polymer grade
        * ``recommended_diameter_mm`` — float: nominal 1.5 × runner diameter
        * ``recommended_depth_mm``    — float: nominal 2.0 × runner diameter
        * ``diameter_min_mm``      — float: lower tolerance bound on diameter
        * ``diameter_max_mm``      — float: upper tolerance bound on diameter
        * ``depth_min_mm``         — float: lower tolerance bound on depth
        * ``depth_max_mm``         — float: upper tolerance bound on depth
        * ``diameter_compliant``   — bool : well diameter within ±20 %
        * ``depth_compliant``      — bool : well depth within ±20 %
        * ``slug_well_compliant``  — bool : both diameter and depth compliant
        * ``reason``               — str : plain-language compliance explanation
    total_junctions : int
        Total number of junctions evaluated.
    compliant_count : int
        Number of junctions where both diameter and depth are compliant.
    honest_caveat : str
        Plain-language statement of model limitations.
    """

    junction_results: List[dict]
    total_junctions: int
    compliant_count: int
    honest_caveat: str = field(default="")


# ---------------------------------------------------------------------------
# Core function
# ---------------------------------------------------------------------------

def check_cold_slug_design(
    junctions: List[RunnerJunctionSpec],
) -> ColdSlugReport:
    """Verify cold-slug well dimensions against Beaumont 2007 §6.7 guidelines.

    Beaumont rules applied
    ----------------------
    Recommended diameter = 1.5 × runner_diameter_mm
    Recommended depth    = 2.0 × runner_diameter_mm

    Compliance band: ±20 % of the recommended value (i.e. 1.2×–1.8× for
    diameter, 1.6×–2.4× for depth).

    Parameters
    ----------
    junctions : list[RunnerJunctionSpec]
        One spec per runner junction to be checked.  Must not be empty.

    Returns
    -------
    ColdSlugReport

    Raises
    ------
    ValueError
        If ``junctions`` is empty, or if any ``RunnerJunctionSpec`` contains
        non-positive dimension values (raised during dataclass ``__post_init__``).
    """
    if not junctions:
        raise ValueError("junctions must contain at least one RunnerJunctionSpec")

    results: List[dict] = []
    compliant_count = 0

    for spec in junctions:
        d_runner = spec.runner_diameter_mm

        # Nominal recommendations
        rec_diam = DIAMETER_RATIO * d_runner   # 1.5 ×
        rec_depth = DEPTH_RATIO * d_runner     # 2.0 ×

        # ±20 % tolerance band
        diam_min = rec_diam * (1.0 - TOLERANCE)
        diam_max = rec_diam * (1.0 + TOLERANCE)
        depth_min = rec_depth * (1.0 - TOLERANCE)
        depth_max = rec_depth * (1.0 + TOLERANCE)

        diam_ok = diam_min <= spec.slug_well_diameter_mm <= diam_max
        depth_ok = depth_min <= spec.slug_well_depth_mm <= depth_max
        compliant = diam_ok and depth_ok

        # Build reason string
        parts: List[str] = []
        if diam_ok:
            parts.append(
                f"diameter {spec.slug_well_diameter_mm:.2f} mm "
                f"within [{diam_min:.2f}, {diam_max:.2f}] mm (1.5×±20% of "
                f"{d_runner:.2f} mm runner)"
            )
        else:
            if spec.slug_well_diameter_mm < diam_min:
                parts.append(
                    f"diameter {spec.slug_well_diameter_mm:.2f} mm is too small "
                    f"(minimum {diam_min:.2f} mm = 1.5×{d_runner:.2f}×0.8)"
                )
            else:
                parts.append(
                    f"diameter {spec.slug_well_diameter_mm:.2f} mm is too large "
                    f"(maximum {diam_max:.2f} mm = 1.5×{d_runner:.2f}×1.2)"
                )

        if depth_ok:
            parts.append(
                f"depth {spec.slug_well_depth_mm:.2f} mm "
                f"within [{depth_min:.2f}, {depth_max:.2f}] mm (2.0×±20% of "
                f"{d_runner:.2f} mm runner)"
            )
        else:
            if spec.slug_well_depth_mm < depth_min:
                parts.append(
                    f"depth {spec.slug_well_depth_mm:.2f} mm is too shallow "
                    f"(minimum {depth_min:.2f} mm = 2.0×{d_runner:.2f}×0.8)"
                )
            else:
                parts.append(
                    f"depth {spec.slug_well_depth_mm:.2f} mm is too deep "
                    f"(maximum {depth_max:.2f} mm = 2.0×{d_runner:.2f}×1.2)"
                )

        reason = "; ".join(parts)

        entry: dict = {
            "junction_id": spec.junction_id,
            "runner_diameter_mm": d_runner,
            "slug_well_diameter_mm": spec.slug_well_diameter_mm,
            "slug_well_depth_mm": spec.slug_well_depth_mm,
            "polymer_grade": spec.polymer_grade,
            "recommended_diameter_mm": rec_diam,
            "recommended_depth_mm": rec_depth,
            "diameter_min_mm": diam_min,
            "diameter_max_mm": diam_max,
            "depth_min_mm": depth_min,
            "depth_max_mm": depth_max,
            "diameter_compliant": diam_ok,
            "depth_compliant": depth_ok,
            "slug_well_compliant": compliant,
            "reason": reason,
        }
        results.append(entry)

        if compliant:
            compliant_count += 1

    return ColdSlugReport(
        junction_results=results,
        total_junctions=len(junctions),
        compliant_count=compliant_count,
        honest_caveat=_HONEST_CAVEAT,
    )
