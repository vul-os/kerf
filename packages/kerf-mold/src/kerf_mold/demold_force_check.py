"""
kerf_mold.demold_force_check
============================
Estimate the demolding (ejection) force required to eject a molded part from
the cavity, and verify that the ejector pin system has adequate capacity.

Theory — Beaumont 2007 §9.3 + Menges 2001 §7.4
-----------------------------------------------
During ejection the part must overcome frictional grip between the shrunk
polymer and the mold steel.  The shrinkage stress σ_h acts as a contact
pressure pressing the part against the mold wall.  Combined with the friction
coefficient μ and the draft (relief) angle α the cavity-ejection force formula
(Beaumont 2007 §9.3 + Menges 2001 §7.4) gives:

    F = μ · σ_h · A_contact · cos α / (cos α + μ · sin α)

Equivalently:

    F = μ · σ_h · A_contact / (1 + μ · tan α)

where:
  μ         — kinetic friction coefficient (polymer on mold steel), finish-dependent
  σ_h       — polymer shrinkage stress [MPa] (Menges 2001 Table 7.6)
  A_contact — contact surface area between part and mold wall [mm²]
  α         — draft (relief) angle [radians] — the taper that aids cavity release

At α = 0 the formula reduces to F = μ · σ_h · A_contact (no taper relief).
As α increases, the taper provides progressive release and F decreases monotonically.
The formula is physically valid for all α ∈ [0°, 90°) — no self-locking condition.

Note on sign convention: some presentations of the Beaumont formula use
(cos α + μ sin α)/(cos α − μ sin α), which is the wedge-locking direction
(force INCREASES with α, applicable when draft works AGAINST ejection, e.g.,
a reverse taper or core-lock geometry).  This implementation uses the
cavity-ejection convention where positive draft angle = release taper.

Shrinkage stress per polymer (Menges 2001 Table 7.6)
-----------------------------------------------------
  ABS   — 4.0 MPa
  PC    — 3.0 MPa
  PP    — 5.0 MPa
  PA66  — 3.5 MPa
  POM   — 4.5 MPa

Friction coefficient per SPI finish class
------------------------------------------
  SPI_A1 — 0.15 (diamond-polished; very low friction)
  SPI_A2 — 0.18
  SPI_B1 — 0.25 (medium stone-polished; typical tooling)
  SPI_C1 — 0.30 (paper-finish)
  SPI_D1 — 0.40 (EDM / matte textured; high friction)

Honest caveats
--------------
1. Formula is empirical (Beaumont 2007 §9.3).  Real forces depend on melt
   temperature, mold temperature, cooling time, and resin batch variation.
2. Chemical adhesion (resin stick) is NOT modelled — highly relevant for PC
   on polished steel, POM on bare steel, or sticky elastomers.
3. Undercut geometry is NOT modelled — lifters/side-actions add significant
   force components outside this formula's scope.
4. Uniform contact pressure is assumed (σ_h constant over A_contact).
   In practice σ_h varies with wall thickness, cooling uniformity, and
   local geometry.
5. Static ejection only — no dynamic impact or pin-bounce effects.
6. For production tooling always verify by mold trial with a load cell on the
   ejector plate before specifying pin sizes and press tonnage.

References
----------
Beaumont J.P. "Runner and Gating Design Handbook", 2nd ed., Hanser 2007,
  §9.3 — Ejection force calculation.
Menges G., Michaeli W., Mohren P. "How to Make Injection Molds", 3rd ed.,
  Hanser 2001, §7.4 — Demolding forces, Table 7.6.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict


# ---------------------------------------------------------------------------
# Material shrinkage stress database — Menges 2001 Table 7.6
# ---------------------------------------------------------------------------

#: Polymer shrinkage contact stress (MPa) from Menges 2001 Table 7.6.
SHRINKAGE_STRESS_MPA: Dict[str, float] = {
    "ABS":  4.0,
    "PC":   3.0,
    "PP":   5.0,
    "PA66": 3.5,
    "POM":  4.5,
}

# ---------------------------------------------------------------------------
# Friction coefficient per SPI mold finish class
# ---------------------------------------------------------------------------

#: Kinetic friction coefficient (polymer on mold steel) per SPI finish class.
#: Values derived from Beaumont 2007 §9.3 surface-finish guidance and
#: Menges 2001 §7.4 friction data.
FRICTION_COEFF: Dict[str, float] = {
    "SPI_A1": 0.15,   # diamond-polished (Ra < 0.025 µm)
    "SPI_A2": 0.18,   # diamond-polished (Ra 0.025–0.05 µm)
    "SPI_B1": 0.25,   # stone-polished (Ra 0.05–0.4 µm)
    "SPI_C1": 0.30,   # paper-finish (Ra 0.4–1.6 µm)
    "SPI_D1": 0.40,   # EDM / bead-blast textured (Ra 1.6–12.5 µm)
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class MoldedPartSpec:
    """Specification of a molded part for demolding force estimation.

    Attributes
    ----------
    polymer_grade : str
        Polymer material.  Must be one of: ABS, PC, PP, PA66, POM.
    contact_area_cm2 : float
        Total contact surface area between the part and the mold steel [cm²].
        This is the projected area of all surfaces that grip the mold during
        ejection (typically all internal / core-side faces).  Must be > 0.
    draft_angle_deg : float
        Draft angle of the mold walls relative to the pull direction [degrees].
        Typically 0.5–5°.  Must be ≥ 0.
    mold_steel_finish_class : str
        SPI mold finish class.  Must be one of:
        "SPI_A1", "SPI_A2", "SPI_B1", "SPI_C1", "SPI_D1".
    """

    polymer_grade: str
    contact_area_cm2: float
    draft_angle_deg: float
    mold_steel_finish_class: str

    def __post_init__(self) -> None:
        _normalised = self.polymer_grade.strip().upper()
        if _normalised not in SHRINKAGE_STRESS_MPA:
            raise ValueError(
                f"Unknown polymer_grade '{self.polymer_grade}'. "
                f"Supported grades: {sorted(SHRINKAGE_STRESS_MPA.keys())}."
            )
        # Normalise so lookup always works
        object.__setattr__(self, "polymer_grade", _normalised)

        if self.contact_area_cm2 <= 0.0:
            raise ValueError(
                f"contact_area_cm2 must be > 0, got {self.contact_area_cm2}"
            )
        if self.draft_angle_deg < 0.0:
            raise ValueError(
                f"draft_angle_deg must be >= 0, got {self.draft_angle_deg}"
            )
        if self.mold_steel_finish_class not in FRICTION_COEFF:
            raise ValueError(
                f"Unknown mold_steel_finish_class '{self.mold_steel_finish_class}'. "
                f"Supported classes: {sorted(FRICTION_COEFF.keys())}."
            )


@dataclass
class DemoldForceReport:
    """Report produced by compute_demold_force.

    Attributes
    ----------
    demold_force_N : float
        Estimated total demolding (ejection) force [N] per the Beaumont 2007
        §9.3 formula.
    contact_pressure_MPa : float
        Effective contact pressure = σ_h (shrinkage stress) [MPa].
    ejector_pin_count_required : int
        Minimum number of ejector pins needed such that
        ejector_pin_count × single_pin_capacity_N ≥ demold_force_N.
    friction_coeff_used : float
        Friction coefficient μ applied (from finish class lookup).
    polymer_shrinkage_stress_MPa : float
        Shrinkage stress σ_h applied (from polymer grade lookup) [MPa].
    honest_caveat : str
        Plain-language statement of model limitations.
    """

    demold_force_N: float
    contact_pressure_MPa: float
    ejector_pin_count_required: int
    friction_coeff_used: float
    polymer_shrinkage_stress_MPa: float
    honest_caveat: str = field(default="")


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_CAVEAT_TMPL = (
    "Empirical cavity-ejection force from Beaumont 2007 §9.3 + Menges 2001 §7.4 "
    "formula (F = μ·σ_h·A·cosα / (cosα + μ·sinα)) using shrinkage stress "
    "{sigma_h} MPa for {polymer} (Menges 2001 Table 7.6). "
    "Formula assumes: uniform contact pressure over A_contact, no chemical "
    "adhesion (resin stick), no undercut geometry, static ejection only. "
    "Chemical adhesion (relevant for PC/POM on polished steel) is NOT modelled. "
    "Undercuts or side-action features add force components outside this scope. "
    "Confirm by mold-trial load-cell measurement before specifying pin capacity. "
    "{zero_draft_note}"
    "References: Beaumont 2007 §9.3; Menges 2001 §7.4 + Table 7.6."
)

_ZERO_DRAFT_NOTE = (
    "Draft angle = 0°: formula reduces to F = μ·σ_h·A (no taper relief). "
    "Force is at maximum; adding even 0.5° draft substantially reduces ejection force. "
)

_HIGH_DRAFT_NOTE = (
    "Draft angle is relatively large: taper relief effect is pronounced, "
    "force is well below the zero-draft baseline. "
)


def compute_demold_force(
    spec: MoldedPartSpec,
    single_pin_capacity_N: float = 2500.0,
) -> DemoldForceReport:
    """Estimate ejection (demolding) force and verify ejector pin capacity.

    Applies the Beaumont (2007) §9.3 ejection force formula:

        F = μ · σ_h · A_contact · (cosα + μ·sinα) / (cosα − μ·sinα)

    where σ_h is the polymer shrinkage contact stress from Menges 2001
    Table 7.6, μ is determined by mold finish class, and A_contact is
    converted from cm² to m² internally.

    The minimum ejector pin count is:

        n_pins = ceil(F / single_pin_capacity_N)

    Parameters
    ----------
    spec : MoldedPartSpec
        Part geometry and material specification.
    single_pin_capacity_N : float, optional
        Axial load capacity of a single ejector pin [N].
        Default 2500 N (typical 5 mm diameter H13 pin at 15% yield margin,
        Beaumont 2007 §9.4).

    Returns
    -------
    DemoldForceReport

    Raises
    ------
    ValueError
        If spec contains invalid values, or if the draft angle approaches
        self-locking (tanα ≥ 1/μ).
    """
    if single_pin_capacity_N <= 0.0:
        raise ValueError(
            f"single_pin_capacity_N must be > 0, got {single_pin_capacity_N}"
        )

    mu = FRICTION_COEFF[spec.mold_steel_finish_class]
    sigma_h = SHRINKAGE_STRESS_MPA[spec.polymer_grade]  # MPa

    # Convert contact area: cm² → m²  (1 cm² = 1e-4 m²)
    A_m2 = spec.contact_area_cm2 * 1e-4  # m²

    # Convert contact area for force in Newtons:
    # σ_h [MPa] = σ_h [N/mm²];  A [m²] = A × 1e6 [mm²]
    # F [N] = μ · σ_h [N/mm²] · A [mm²] · ratio
    A_mm2 = spec.contact_area_cm2 * 100.0  # 1 cm² = 100 mm²

    alpha_rad = math.radians(spec.draft_angle_deg)
    cos_a = math.cos(alpha_rad)
    sin_a = math.sin(alpha_rad)

    # Cavity-ejection formula (Beaumont 2007 §9.3 + Menges 2001 §7.4):
    #   F = μ · σ_h · A · cos(α) / (cos(α) + μ · sin(α))
    # Denominator is always positive for α ∈ [0°, 90°) — no self-locking.
    denominator = cos_a + mu * sin_a
    # denominator is always > 0 for valid alpha, but guard against degenerate input
    if denominator <= 0.0:
        raise ValueError(
            f"Degenerate draft_angle_deg={spec.draft_angle_deg}° — "
            f"cos(α) + μ·sin(α) ≤ 0. Use draft angle in range [0°, 89°]."
        )

    force_N = mu * sigma_h * A_mm2 * cos_a / denominator
    force_N = round(force_N, 3)

    # Ejector pin count
    n_pins = math.ceil(force_N / single_pin_capacity_N)
    n_pins = max(n_pins, 1)  # always at least 1 pin

    # Build caveat
    zero_draft_note = ""
    if spec.draft_angle_deg == 0.0:
        zero_draft_note = _ZERO_DRAFT_NOTE
    elif spec.draft_angle_deg >= 15.0:
        zero_draft_note = _HIGH_DRAFT_NOTE

    caveat = _CAVEAT_TMPL.format(
        sigma_h=sigma_h,
        polymer=spec.polymer_grade,
        zero_draft_note=zero_draft_note,
    )

    return DemoldForceReport(
        demold_force_N=force_N,
        contact_pressure_MPa=sigma_h,
        ejector_pin_count_required=n_pins,
        friction_coeff_used=mu,
        polymer_shrinkage_stress_MPa=sigma_h,
        honest_caveat=caveat,
    )
