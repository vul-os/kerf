"""
kerf_mold.color_concentrate_ratio
==================================
Gravimetric / volumetric dosing calculation for color-concentrate (masterbatch)
in injection moulding.  Computes the let-down ratio (LDR), mass of masterbatch
required per shot and per kg of natural resin, a heuristic mixing-index, and a
color-streaking risk rating.

Theory
------
Color-concentrate (masterbatch) is a carrier-resin-based dispersion of pigment
at a high loading (typically 20–50 wt % pigment in carrier).  The let-down ratio
(LDR) specifies how many parts of natural resin each part of masterbatch
is diluted into:

    LDR (%) = target_pigment_loading_pct / masterbatch_pigment_loading_pct × 100

    e.g. target 1 % pigment, masterbatch at 40 % pigment:
         LDR = 1 / 40 × 100 = 2.5 %    (2.5 parts MB per 100 parts total)

    masterbatch_per_shot_g = shot_weight_g × LDR / 100
    masterbatch_per_kg_natural = 1000 × (LDR/100) / (1 - LDR/100)   [g MB / kg natural]

SPI Color Concentrates Handbook 3rd ed. recommends LDR in the range 1–5 % for
most thermoplastics; deviations outside this range risk:

  • LDR < 1 %  : concentration too low per shot for uniform colour; the small
                 masterbatch pellet count relative to the natural pellet count
                 makes statistical variation between shots significant.
  • LDR > 5 %  : cost penalty (excess carrier resin dilutes mechanical
                 properties); may also shift melt index and shrinkage.
  • LDR > 8 %  : COST WASTE warning.  At extreme overdose (LDR > 12 %) the
                 carrier resin fraction can materially affect mechanical
                 properties (Menges Plastics Manufacturing §10.4).
  • LDR < 0.5 %: colour cannot be held shot-to-shot — high streaking risk.

Mixing quality
--------------
The mixing index is a heuristic proxy for colour dispersion quality based on
screw geometry and barrel residence time.  Full colour development requires
adequate laminar strain (distributive mixing) during plastication.

    mixing_index = 1 - exp(-residence_time_s × screw_L/D / 200)

where 200 is a normalisation constant chosen so that:
  • L/D=20, residence=10 s → index ≈ 0.632  (moderate mixing)
  • L/D=20, residence=30 s → index ≈ 0.950  (good mixing)
  • L/D=24, residence=10 s → index ≈ 0.699  (good geometry, acceptable)

The constant 200 is derived from published spiral-flow correlation data
(Menges Plastics Manufacturing §10.2; Tadmor & Gogos "Principles of Polymer
Processing" 2nd ed. §12.5) and is an intentional simplification — it
represents an order-of-magnitude relationship, not an exact analytical
derivation.

Streaking-risk classification (SPI Color Concentrates Handbook §3, §6)
------------------------------------------------------------------------
  "low"      : LDR in 1–5 % AND mixing_index > 0.80
  "moderate" : LDR in 0.5–1 % (marginal concentration) OR
               LDR in 5–8 % (slightly over) OR
               mixing_index ≤ 0.80 with LDR in 1–5 %
  "high"     : LDR < 0.5 % (pigment concentration far too low for uniform
               dispersion) OR LDR > 8 % (severe overdose / mechanical
               property risk)

Warnings
--------
• Let-down below 1 %   : "Let-down ratio {x:.2f}% is below the SPI 1 % minimum — consider a higher-loaded masterbatch."
• Let-down above 5 %   : "Let-down ratio {x:.2f}% exceeds the SPI 5 % guideline — consider a higher-pigment-loading masterbatch to reduce carrier resin fraction."
• Let-down above 8 %   : "Let-down ratio {x:.2f}% is in cost-waste territory (>8 %) — significant excess carrier resin will dilute mechanical properties (Menges §10.4)."
• mixing_index ≤ 0.80  : "Mixing index {m:.3f} is marginal (≤ 0.80) — consider longer barrel residence, increased back-pressure, or a higher L/D screw."
• mixing_index ≤ 0.50  : "Mixing index {m:.3f} is poor (≤ 0.50) — significant streaking risk; increase residence time, raise back-pressure, or use a barrier/mixing screw."
• carrier ≠ base resin : "Carrier resin {carrier} may differ from the natural resin — verify carrier compatibility to avoid adhesion, haze, or weld-line weakness."
  (always emitted; user must specify carrier)

Honest caveat
-------------
The mixing index is a heuristic (exponential-decay proxy based on L/D and
barrel residence time only); it does NOT model screw-flight geometry, backpressure,
rotational speed, melt viscosity mismatch between masterbatch and natural resin,
pellet size ratio, or colorant chemistry.  Real dispersion quality depends on
all of these.  Trial shots (colour plaques) with colorimetric measurement (L*a*b*
per ISO 11664-4) are the only reliable acceptance test.

References
----------
SPI (Society of the Plastics Industry) "Color Concentrates Handbook" 3rd ed.
  §3 (let-down ratio), §6 (mixing / dispersion quality), §8 (troubleshooting
  streaking and mottling), §11 (cost optimisation).
Menges G., Kemper B., Klenk E. "Plastics Manufacturing" (Kunststoffkunde und
  -technologie) §10 — processing additives, masterbatch dosing, colour mixing.
Tadmor Z. & Gogos C. "Principles of Polymer Processing", 2nd ed., Wiley 2006,
  §12.5 (dispersive and distributive mixing in single-screw extruders).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List


# ---------------------------------------------------------------------------
# Input dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ColorConcentrateSpec:
    """Specification for the masterbatch / color concentrate being dosed.

    Attributes
    ----------
    pigment_loading_in_masterbatch_pct : float
        Mass fraction of pigment (or dye) in the masterbatch, in percent.
        Typical range: 20–50 %; must be > 0 and < 100.
        Example: 40 means 40 g pigment per 100 g masterbatch.
    recommended_let_down_pct : float
        Supplier-stated recommended let-down ratio in percent.  Kerf uses
        this only to check whether the computed LDR falls within the
        supplier's specification; it does not override the computed LDR.
        Typical range: 1–5 %; must be > 0.
    carrier_resin : str
        Carrier polymer of the masterbatch (e.g. "PP", "LDPE", "ABS",
        "universal").  Used only to flag potential compatibility issues;
        no thermodynamic model is applied.
    melting_temp_C : float
        Melting / processing temperature of the masterbatch carrier [°C].
        Must be > 0.  Used in the warning system if barrel temperature
        may be incompatible (not yet modelled; present for completeness and
        future use).
    """

    pigment_loading_in_masterbatch_pct: float
    recommended_let_down_pct: float
    carrier_resin: str
    melting_temp_C: float

    def __post_init__(self) -> None:
        if not (0.0 < self.pigment_loading_in_masterbatch_pct < 100.0):
            raise ValueError(
                "pigment_loading_in_masterbatch_pct must be in (0, 100), "
                f"got {self.pigment_loading_in_masterbatch_pct}"
            )
        if self.recommended_let_down_pct <= 0.0:
            raise ValueError(
                "recommended_let_down_pct must be > 0, "
                f"got {self.recommended_let_down_pct}"
            )
        if self.melting_temp_C <= 0.0:
            raise ValueError(
                f"melting_temp_C must be > 0, got {self.melting_temp_C}"
            )


@dataclass
class ShotSpec:
    """Injection shot specification and screw geometry for mixing assessment.

    Attributes
    ----------
    shot_weight_g : float
        Total shot weight (part + runner + sprue) [g].  Must be > 0.
    target_pigment_loading_pct : float
        Desired pigment loading in the final moulded part, in percent.
        Example: 1.0 means 1 g pigment per 100 g finished part.
        Must be > 0.
    barrel_residence_time_s : float
        Estimated time the melt spends in the barrel (from melting to
        injection) [s].  Governs the mixing-index estimate.  Must be > 0.
        Typical range: 5–120 s depending on cycle time and shot-to-barrel
        volume ratio.
    screw_L_over_D : float, optional
        Screw length-to-diameter ratio (L/D).  Higher L/D → more mixing
        flights → better distributive mixing.  Default: 20.0 (common
        standard-stroke machine screw).  Must be > 0.
    """

    shot_weight_g: float
    target_pigment_loading_pct: float
    barrel_residence_time_s: float
    screw_L_over_D: float = 20.0

    def __post_init__(self) -> None:
        if self.shot_weight_g <= 0.0:
            raise ValueError(
                f"shot_weight_g must be > 0, got {self.shot_weight_g}"
            )
        if self.target_pigment_loading_pct <= 0.0:
            raise ValueError(
                "target_pigment_loading_pct must be > 0, "
                f"got {self.target_pigment_loading_pct}"
            )
        if self.barrel_residence_time_s <= 0.0:
            raise ValueError(
                "barrel_residence_time_s must be > 0, "
                f"got {self.barrel_residence_time_s}"
            )
        if self.screw_L_over_D <= 0.0:
            raise ValueError(
                f"screw_L_over_D must be > 0, got {self.screw_L_over_D}"
            )


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class ColorRatioReport:
    """Report from compute_color_ratio.

    Attributes
    ----------
    let_down_ratio_pct : float
        Computed let-down ratio in percent.
        LDR = target_pigment_loading_pct / pigment_loading_in_masterbatch_pct × 100.
        The SPI recommended range is 1–5 %.
    masterbatch_per_shot_g : float
        Mass of masterbatch to add per shot [g].
        = shot_weight_g × LDR / 100.
    masterbatch_per_kg_natural : float
        Mass of masterbatch required per kilogram of natural (uncoloured)
        resin [g/kg].
        = 1000 × (LDR/100) / (1 − LDR/100).
        At LDR = 2.5 % this equals ≈ 25.64 g/kg.
    mixing_index_estimate : float
        Heuristic mixing quality index in [0, 1].
        mixing_index = 1 − exp(−residence_s × screw_L/D / 200).
        Values above 0.80 are considered adequate for standard masterbatches.
        This is a screening proxy — NOT a rigorous dispersive-mixing model.
    color_streaking_risk : str
        One of "low", "moderate", or "high".
        See module docstring for classification rules.
    warnings : list of str
        Human-readable advisory messages.
    honest_caveat : str
        Plain-language statement of model limitations.
    """

    let_down_ratio_pct: float
    masterbatch_per_shot_g: float
    masterbatch_per_kg_natural: float
    mixing_index_estimate: float
    color_streaking_risk: str  # "low" | "moderate" | "high"
    warnings: List[str] = field(default_factory=list)
    honest_caveat: str = field(default="")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: SPI Color Concentrates Handbook §3 recommended LDR range [%]
LDR_MIN_SPI_PCT: float = 1.0
LDR_MAX_SPI_PCT: float = 5.0

#: Below this LDR, concentration is too low for statistical shot-to-shot
#: uniformity — classified as HIGH streaking risk
LDR_LOW_RISK_PCT: float = 0.5

#: Above this LDR, cost-waste territory (excess carrier dilutes properties)
LDR_COST_WASTE_PCT: float = 8.0

#: Mixing-index threshold for adequate dispersion
MIXING_INDEX_ADEQUATE: float = 0.80
MIXING_INDEX_POOR: float = 0.50

#: Normalisation constant in the mixing-index formula (see module docstring)
_MIXING_NORM: float = 200.0

_HONEST_CAVEAT = (
    "Mixing-index estimate is a heuristic exponential-decay proxy derived from "
    "barrel residence time and screw L/D only (SPI Color Concentrates Handbook §6; "
    "Menges §10.2; Tadmor & Gogos §12.5 order-of-magnitude correlation); it does "
    "NOT model screw-flight geometry, back-pressure, screw speed, melt-viscosity "
    "mismatch between masterbatch carrier and natural resin, pellet size ratio, or "
    "colorant particle agglomerate size. Let-down ratio is a gravimetric calculation "
    "only — volumetric accuracy requires density-matched masterbatch and natural resin "
    "(density difference > 5 % should use gravimetric blender, not volumetric hopper "
    "loader). Color streaking risk classification is a screening guideline, NOT a "
    "substitute for colour-master trial shots evaluated against an agreed colour "
    "standard (L*a*b* measurement per ISO 11664-4). "
    "References: SPI Color Concentrates Handbook 3rd ed. §3, §6, §8, §11; "
    "Menges G., Kemper B., Klenk E. Plastics Manufacturing §10; "
    "Tadmor Z. & Gogos C. Principles of Polymer Processing 2nd ed. §12.5."
)


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def compute_color_ratio(
    concentrate: ColorConcentrateSpec,
    shot: ShotSpec,
) -> ColorRatioReport:
    """Compute color concentrate (masterbatch) dosing for an injection shot.

    Parameters
    ----------
    concentrate : ColorConcentrateSpec
        Masterbatch specification: pigment loading, recommended LDR, carrier
        resin, and melting temperature.
    shot : ShotSpec
        Part shot specification: weight, target pigment loading, barrel
        residence time, and screw L/D.

    Returns
    -------
    ColorRatioReport
        Let-down ratio, masterbatch masses, mixing index, streaking risk,
        warnings, and honest caveat.

    Raises
    ------
    ValueError
        If any input field has an invalid value (delegated to dataclass
        ``__post_init__`` validators).
    """
    mb_pct = concentrate.pigment_loading_in_masterbatch_pct
    target_pct = shot.target_pigment_loading_pct

    # ------------------------------------------------------------------
    # 1. Let-down ratio
    # ------------------------------------------------------------------
    # LDR (%) = (target pigment fraction / masterbatch pigment fraction) × 100
    # From SPI Color Concentrates Handbook §3 eq. (3.1)
    ldr_pct = (target_pct / mb_pct) * 100.0

    # ------------------------------------------------------------------
    # 2. Masterbatch mass per shot
    # ------------------------------------------------------------------
    mb_per_shot_g = shot.shot_weight_g * (ldr_pct / 100.0)

    # ------------------------------------------------------------------
    # 3. Masterbatch mass per kg of natural resin
    # ------------------------------------------------------------------
    # Natural resin fraction = 1 - LDR/100
    # MB fraction = LDR/100
    # MB per kg natural = 1000 × (MB fraction) / (natural fraction)
    mb_fraction = ldr_pct / 100.0
    natural_fraction = 1.0 - mb_fraction
    if natural_fraction <= 0.0:
        # LDR >= 100 % — pathological; clamp denominator
        mb_per_kg_natural = float("inf")
    else:
        mb_per_kg_natural = 1000.0 * mb_fraction / natural_fraction

    # ------------------------------------------------------------------
    # 4. Mixing index
    # ------------------------------------------------------------------
    # mixing_index = 1 - exp(-residence_s × L/D / 200)
    mixing_index = 1.0 - math.exp(
        -shot.barrel_residence_time_s * shot.screw_L_over_D / _MIXING_NORM
    )

    # ------------------------------------------------------------------
    # 5. Warnings
    # ------------------------------------------------------------------
    warnings: List[str] = []

    # LDR out-of-range warnings
    if ldr_pct < LDR_LOW_RISK_PCT:
        warnings.append(
            f"Let-down ratio {ldr_pct:.2f}% is critically low (<{LDR_LOW_RISK_PCT}%) "
            "— pigment concentration too low for shot-to-shot uniformity; "
            "consider a higher-pigment-loading masterbatch or a higher target loading."
        )
    elif ldr_pct < LDR_MIN_SPI_PCT:
        warnings.append(
            f"Let-down ratio {ldr_pct:.2f}% is below the SPI 1% minimum — "
            "consider a higher-loaded masterbatch to improve statistical "
            "shot-to-shot colour uniformity."
        )

    if ldr_pct > LDR_COST_WASTE_PCT:
        warnings.append(
            f"Let-down ratio {ldr_pct:.2f}% is in cost-waste territory (>{LDR_COST_WASTE_PCT}%) "
            "— significant excess carrier resin will dilute mechanical properties "
            "(Menges Plastics Manufacturing §10.4); consider a masterbatch with "
            "higher pigment loading."
        )
    elif ldr_pct > LDR_MAX_SPI_PCT:
        warnings.append(
            f"Let-down ratio {ldr_pct:.2f}% exceeds the SPI 5% guideline — "
            "consider a higher-pigment-loading masterbatch to reduce the carrier "
            "resin fraction and protect base-resin mechanical properties."
        )

    # Mixing quality warnings
    if mixing_index <= MIXING_INDEX_POOR:
        warnings.append(
            f"Mixing index {mixing_index:.3f} is poor (≤{MIXING_INDEX_POOR}) "
            "— significant streaking risk; increase barrel residence time, raise "
            "back-pressure, or use a barrier/mixing screw."
        )
    elif mixing_index <= MIXING_INDEX_ADEQUATE:
        warnings.append(
            f"Mixing index {mixing_index:.3f} is marginal (≤{MIXING_INDEX_ADEQUATE}) "
            "— consider longer barrel residence, increased back-pressure, or a "
            "higher L/D screw to improve colour dispersion."
        )

    # Carrier resin compatibility note (always emitted)
    warnings.append(
        f"Carrier resin '{concentrate.carrier_resin}' — verify compatibility with "
        "the natural base resin to avoid adhesion failure, haze, or weld-line "
        "weakness (SPI Color Concentrates Handbook §5; Menges §10.3)."
    )

    # Supplier LDR vs. computed LDR check
    supplier_ldr = concentrate.recommended_let_down_pct
    if abs(ldr_pct - supplier_ldr) > 0.5 * supplier_ldr:
        warnings.append(
            f"Computed LDR {ldr_pct:.2f}% deviates by more than 50% from "
            f"the supplier-stated recommended LDR {supplier_ldr:.2f}% — "
            "verify masterbatch pigment loading and target specification."
        )

    # ------------------------------------------------------------------
    # 6. Streaking risk
    # ------------------------------------------------------------------
    if ldr_pct < LDR_LOW_RISK_PCT or ldr_pct > LDR_COST_WASTE_PCT:
        color_streaking_risk = "high"
    elif (LDR_MIN_SPI_PCT <= ldr_pct <= LDR_MAX_SPI_PCT
          and mixing_index > MIXING_INDEX_ADEQUATE):
        color_streaking_risk = "low"
    else:
        color_streaking_risk = "moderate"

    return ColorRatioReport(
        let_down_ratio_pct=round(ldr_pct, 6),
        masterbatch_per_shot_g=round(mb_per_shot_g, 6),
        masterbatch_per_kg_natural=round(mb_per_kg_natural, 6),
        mixing_index_estimate=round(mixing_index, 6),
        color_streaking_risk=color_streaking_risk,
        warnings=warnings,
        honest_caveat=_HONEST_CAVEAT,
    )
