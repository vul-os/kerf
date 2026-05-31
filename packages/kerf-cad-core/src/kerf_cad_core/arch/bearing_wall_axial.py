"""
kerf_cad_core.arch.bearing_wall_axial — Plain/RC bearing wall axial-load capacity check.

Implements:
  - ACI 318-19 §11.5 (Empirical method for plain walls):
      ACI Eq 11.5.3.1: φ·Pn = 0.55·φ·f'c·Ag·[1 − (k·lc / (32·t))²]
      Valid when eccentricity e ≤ t/6 (small eccentricity bound, ACI §11.5.3.1).
      k from end conditions: fixed_fixed → 0.8; pin_pin → 1.0; cantilever → 2.0.

  - TMS 402-22 §8.3 (masonry bearing walls, clay_masonry and concrete_masonry):
      φ·Pn = φ · 0.80 · f'm · Ag × [1 − (h_eff / (140·r))²]
      where r = t / √12 (radius of gyration for rectangular cross-section).
      Valid for h_eff/r ≤ 99 (TMS Eq 8-22).

  - For reinforced_concrete material the ACI §11.5.3.1 empirical formula is used with
    a composite gross-section; the formula does NOT credit reinforcement in the axial term.
    If As_per_m > 0 the module flags this via the governing_check caveat (ACI §11.5.3.1
    applies to plain walls; reinforced walls should use ACI §11.4 or §22.4).

  Per-metre-width strip throughout: dimensions in mm, stresses in MPa, forces in kN/m.

References:
  ACI 318-19, "Building Code Requirements for Structural Concrete":
    §11.5   (Empirical design method for walls)
    §11.5.3 (Walls subjected to axial loads — Eq 11.5.3.1)
    Table 21.2.2 (φ = 0.65 compression-controlled)
  TMS 402-22, "Building Code Requirements and Specification for Masonry Structures":
    §8.3 (Axial load-bearing masonry piers/walls, Eq 8-22 slenderness factor)
  Wight J.K. (2019) *Reinforced Concrete: Mechanics and Design* 8e §13.13.

SCOPE LIMITATIONS (honest caveats):
  - ACI §11.5.3.1 empirical method ONLY for plain concrete and RC walls.
    Large eccentricity (e > t/6) is outside the scope of the empirical formula —
    a full PM interaction surface analysis (ACI §11.4 or §22.4.2 with moment) is required.
  - TMS 402-22 §8.3 slenderness: h_eff/r ≤ 99 required; beyond this limit φ·Pn = 0.
  - Reinforcement (As_per_m) does NOT increase φ·Pn in the ACI §11.5.3 empirical formula.
    For reinforced concrete walls where As contributes, use the full ACI §22.4.2.2 approach.
  - In-plane shear wall behaviour (ACI §11.6) is NOT checked here.
  - Load combinations per ACI §5.3 are the caller's responsibility.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "BearingWallSpec",
    "BearingWallReport",
    "check_bearing_wall",
]

# ---------------------------------------------------------------------------
# Valid options
# ---------------------------------------------------------------------------

_VALID_MATERIALS = frozenset(
    {"concrete", "clay_masonry", "concrete_masonry", "reinforced_concrete"}
)
_VALID_END_CONDITIONS = frozenset({"fixed_fixed", "pin_pin", "cantilever"})

# k-factors per ACI Commentary R11.5.3.1 and Wight §13.13
_K_FACTOR: dict[str, float] = {
    "fixed_fixed": 0.8,
    "pin_pin": 1.0,
    "cantilever": 2.0,
}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class BearingWallSpec:
    """
    Bearing wall geometry and material properties for axial-load capacity check.

    Parameters
    ----------
    wall_thickness_t_mm : float
        Wall thickness t (mm).  Must be > 0.
    wall_height_h_mm : float
        Clear storey height h between supports (mm).  Must be > 0.
    wall_length_lw_m : float
        Horizontal plan length of the wall lw (m).  Informational only; used
        in description.  Must be > 0.
    material : str
        One of: "concrete", "reinforced_concrete", "clay_masonry", "concrete_masonry".
        Governs which code formula is applied.
    f_prime_MPa : float
        Specified compressive strength (MPa): f'c for concrete/RC, f'm for masonry.
        Must be > 0.
    As_per_m : float
        Vertical reinforcement area (mm²/m of wall width).  Default 0.0.
        NOTE: ignored in ACI §11.5.3.1 empirical formula (plain-wall formula);
        present for informational reporting.  Must be ≥ 0.
    fy_MPa : float
        Reinforcing steel yield strength (MPa).  Default 420 MPa.  Used only
        for caveat reporting when As_per_m > 0.  Must be > 0.
    end_conditions : str
        One of "fixed_fixed" (k=0.8), "pin_pin" (k=1.0), "cantilever" (k=2.0).
    eccentricity_e_mm : float
        Load eccentricity e measured from wall centroid (mm).  Default 0.0.
        ACI §11.5.3.1 requires e ≤ t/6 for the empirical formula to apply.
        If e > t/6, the governing_check is set to "large_eccentricity_method_required"
        and the formula result is flagged as not applicable.  Must be ≥ 0.
    """

    wall_thickness_t_mm: float
    wall_height_h_mm: float
    wall_length_lw_m: float
    material: str
    f_prime_MPa: float
    As_per_m: float = field(default=0.0)
    fy_MPa: float = field(default=420.0)
    end_conditions: str = field(default="pin_pin")
    eccentricity_e_mm: float = field(default=0.0)


@dataclass
class BearingWallReport:
    """
    Result of ACI 318-19 §11.5 / TMS 402-22 §8.3 bearing wall axial capacity check.

    Parameters
    ----------
    phi_Pn_kN_per_m : float
        Design axial compressive strength per unit wall width (kN/m).
        For large-eccentricity or slenderness-limit-exceeded cases this is 0.0.
    slenderness_factor : float
        Dimensionless buckling reduction factor.
        ACI: 1 − (k·lc / (32·t))²; TMS: 1 − (h_eff / (140·r))².
        Zero if the slenderness term exceeds 1.0 (very slender wall).
    dcr : float
        Demand-Capacity Ratio = P_factored / φ·Pn.  Inf if φ·Pn = 0.
    adequate : bool
        True if dcr ≤ 1.0 AND e ≤ t/6 (eccentricity bound) AND slenderness
        limit is not exceeded.
    governing_check : str
        Short tag describing the governing condition:
        "OK" | "dcr_exceeded" | "large_eccentricity_method_required" |
        "slenderness_limit_exceeded" | "large_eccentricity_and_dcr_exceeded".
    honest_caveat : str
        Full narrative of code references, formula parameters, scope limitations,
        and advisory notes.
    """

    phi_Pn_kN_per_m: float
    slenderness_factor: float
    dcr: float
    adequate: bool
    governing_check: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(spec: BearingWallSpec, P_factored_kN_per_m: float) -> None:
    """Raise ValueError on invalid inputs."""
    if spec.wall_thickness_t_mm <= 0:
        raise ValueError(
            f"wall_thickness_t_mm must be > 0, got {spec.wall_thickness_t_mm}"
        )
    if spec.wall_height_h_mm <= 0:
        raise ValueError(
            f"wall_height_h_mm must be > 0, got {spec.wall_height_h_mm}"
        )
    if spec.wall_length_lw_m <= 0:
        raise ValueError(
            f"wall_length_lw_m must be > 0, got {spec.wall_length_lw_m}"
        )
    if spec.material not in _VALID_MATERIALS:
        raise ValueError(
            f"material must be one of {sorted(_VALID_MATERIALS)}, got {spec.material!r}"
        )
    if spec.f_prime_MPa <= 0:
        raise ValueError(f"f_prime_MPa must be > 0, got {spec.f_prime_MPa}")
    if spec.As_per_m < 0:
        raise ValueError(f"As_per_m must be >= 0, got {spec.As_per_m}")
    if spec.fy_MPa <= 0:
        raise ValueError(f"fy_MPa must be > 0, got {spec.fy_MPa}")
    if spec.end_conditions not in _VALID_END_CONDITIONS:
        raise ValueError(
            f"end_conditions must be one of {sorted(_VALID_END_CONDITIONS)}, "
            f"got {spec.end_conditions!r}"
        )
    if spec.eccentricity_e_mm < 0:
        raise ValueError(
            f"eccentricity_e_mm must be >= 0, got {spec.eccentricity_e_mm}"
        )
    if P_factored_kN_per_m < 0:
        raise ValueError(
            f"P_factored_kN_per_m must be >= 0, got {P_factored_kN_per_m}"
        )


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------


def check_bearing_wall(
    spec: BearingWallSpec,
    P_factored_kN_per_m: float,
    phi: float = 0.65,
) -> BearingWallReport:
    """
    Check axial-load capacity of a plain or masonry bearing wall.

    Method
    ------
    For concrete / reinforced_concrete (ACI 318-19 §11.5.3.1):
      - Eccentricity limit: e ≤ t/6 (required for empirical formula applicability).
      - Effective length: lc = h, k from end_conditions (ACI Commentary R11.5.3.1).
      - Slenderness term: [1 − (k·lc / (32·t))²]
      - φ·Pn = 0.55·φ·f'c·(t × 1000)·slenderness_factor  (per metre width, kN/m)

    For clay_masonry / concrete_masonry (TMS 402-22 §8.3 / Eq 8-22):
      - r = t / √12 (radius of gyration, rectangular cross-section).
      - h_eff = k·h (k from end_conditions; TMS uses same k as ACI commentary).
      - Slenderness factor: [1 − (h_eff / (140·r))²]; valid only for h_eff/r ≤ 99.
      - φ·Pn = φ · 0.80 · f'm · (t × 1000) · slenderness_factor  (kN/m)

    Parameters
    ----------
    spec : BearingWallSpec
        Wall geometry, materials, and parameters.
    P_factored_kN_per_m : float
        Factored axial compressive demand per unit wall width (kN/m).  Must be ≥ 0.
    phi : float
        ACI/TMS strength-reduction factor φ.  Default 0.65 (compression-controlled,
        ACI 318-19 Table 21.2.2).

    Returns
    -------
    BearingWallReport

    Raises
    ------
    ValueError
        On invalid input parameters.
    """
    _validate(spec, P_factored_kN_per_m)
    if phi <= 0 or phi > 1.0:
        raise ValueError(f"phi must be in (0, 1], got {phi}")

    t = spec.wall_thickness_t_mm
    h = spec.wall_height_h_mm
    fc = spec.f_prime_MPa
    k = _K_FACTOR[spec.end_conditions]
    e = spec.eccentricity_e_mm

    # Per-metre width: b = 1000 mm
    Ag_per_m = t * 1_000.0  # mm²/m

    # -----------------------------------------------------------------------
    # Eccentricity check (ACI §11.5.3.1 bound: e ≤ t/6)
    # -----------------------------------------------------------------------
    t_over_6 = t / 6.0
    large_eccentricity = e > t_over_6

    # -----------------------------------------------------------------------
    # Capacity calculation: branched by material
    # -----------------------------------------------------------------------
    is_masonry = spec.material in ("clay_masonry", "concrete_masonry")
    slenderness_limit_exceeded = False

    if is_masonry:
        # TMS 402-22 §8.3 / Eq 8-22
        # r = t / √12 for rectangular cross-section (weak-axis governs unit strip)
        r = t / math.sqrt(12.0)
        h_eff = k * h
        h_over_r = h_eff / r

        if h_over_r > 99.0:
            slenderness_limit_exceeded = True
            slenderness_factor = 0.0
            phi_Pn_kN_per_m = 0.0
        else:
            slenderness_factor = max(0.0, 1.0 - (h_eff / (140.0 * r)) ** 2)
            # TMS §8.3: Pn = 0.80 · f'm · Ag
            Pn_kN_per_m = 0.80 * fc * Ag_per_m * slenderness_factor / 1_000.0
            phi_Pn_kN_per_m = phi * Pn_kN_per_m

        code_ref = "TMS 402-22 §8.3 Eq 8-22"
        formula_str = (
            f"φ·Pn = φ·0.80·f'm·Ag·[1−(h_eff/(140·r))²] = "
            f"φ·0.80·f'm·(t×1000)·C_s"
        )
        slenderness_str = (
            f"r = t/√12 = {r:.3f} mm; h_eff = k·h = {k}×{h:.0f} = {k*h:.0f} mm; "
            f"h_eff/r = {k*h/r:.3f}"
        )
    else:
        # ACI 318-19 §11.5.3.1 — concrete and reinforced_concrete
        lc = h  # clear height between supports
        klc_over_32t = (k * lc) / (32.0 * t)
        slenderness_factor = max(0.0, 1.0 - klc_over_32t ** 2)

        # ACI Eq 11.5.3.1:  Pn = 0.55 · f'c · A_g · [1 − (k·lc/(32·t))²]
        Pn_kN_per_m = 0.55 * fc * Ag_per_m * slenderness_factor / 1_000.0
        phi_Pn_kN_per_m = phi * Pn_kN_per_m

        code_ref = "ACI 318-19 §11.5.3.1"
        formula_str = (
            f"φ·Pn = 0.55·φ·f'c·Ag·[1−(k·lc/(32·t))²]"
        )
        slenderness_str = (
            f"k = {k} (end_conditions={spec.end_conditions}); "
            f"k·lc/(32·t) = {k}×{lc:.0f}/(32×{t:.0f}) = {klc_over_32t:.5f}; "
            f"slenderness_factor = 1 − {klc_over_32t:.5f}² = {slenderness_factor:.6f}"
        )

        # TMS slenderness limit does not apply, but ACI formula goes to zero
        # naturally when k·lc/(32·t) ≥ 1 (extremely slender)
        if slenderness_factor <= 0.0:
            slenderness_limit_exceeded = True

    # -----------------------------------------------------------------------
    # Large-eccentricity override: empirical formula not applicable
    # -----------------------------------------------------------------------
    if large_eccentricity:
        phi_Pn_kN_per_m = 0.0  # mark capacity as undefined (not applicable)

    # -----------------------------------------------------------------------
    # DCR
    # -----------------------------------------------------------------------
    if phi_Pn_kN_per_m > 0.0:
        dcr = P_factored_kN_per_m / phi_Pn_kN_per_m
    else:
        dcr = float("inf") if P_factored_kN_per_m > 0.0 else 0.0

    # -----------------------------------------------------------------------
    # Adequacy and governing check
    # -----------------------------------------------------------------------
    dcr_ok = dcr <= 1.0
    capacity_available = not large_eccentricity and not slenderness_limit_exceeded

    if large_eccentricity and not dcr_ok:
        governing_check = "large_eccentricity_and_dcr_exceeded"
    elif large_eccentricity:
        governing_check = "large_eccentricity_method_required"
    elif slenderness_limit_exceeded:
        governing_check = "slenderness_limit_exceeded"
    elif not dcr_ok:
        governing_check = "dcr_exceeded"
    else:
        governing_check = "OK"

    adequate = capacity_available and dcr_ok

    # -----------------------------------------------------------------------
    # Reinforcement advisory (for RC material only; ignored in formula)
    # -----------------------------------------------------------------------
    rebar_note = ""
    if spec.As_per_m > 0.0 and not is_masonry:
        rebar_note = (
            f" NOTE: As_per_m = {spec.As_per_m:.1f} mm²/m supplied but is NOT credited in "
            f"ACI §11.5.3.1 empirical formula (plain-wall method). "
            f"For reinforced walls where steel contribution is needed use ACI §22.4.2.2 "
            f"(φ·Pn = φ·0.80·[0.85·f'c·(Ag-As)+fy·As]) or ACI §11.4 (alternate method)."
        )

    # TMS h/r advisory
    masonry_hr_note = ""
    if is_masonry and not slenderness_limit_exceeded:
        r_val = t / math.sqrt(12.0)
        h_eff_val = k * h
        masonry_hr_note = (
            f" h_eff/r = {h_eff_val/r_val:.3f} (≤99 OK — within TMS Eq 8-22 range)."
        )
    elif is_masonry and slenderness_limit_exceeded:
        r_val = t / math.sqrt(12.0)
        h_eff_val = k * h
        masonry_hr_note = (
            f" h_eff/r = {h_eff_val/r_val:.3f} EXCEEDS TMS §8.3 limit of 99 — "
            f"slender-wall analysis required; φ·Pn set to 0."
        )

    # Eccentricity advisory
    ecc_note = ""
    if large_eccentricity:
        ecc_note = (
            f" ECCENTRICITY EXCEEDS LIMIT: e = {e:.1f} mm > t/6 = {t_over_6:.1f} mm. "
            f"ACI §11.5.3.1 empirical formula applies only for e ≤ t/6 (concentric or "
            f"small eccentric load). For large eccentricity use full PM interaction "
            f"analysis (ACI §11.4 combined axial + flexure) or a P-M interaction surface."
        )
    else:
        ecc_note = (
            f" e = {e:.1f} mm ≤ t/6 = {t_over_6:.1f} mm (eccentricity bound satisfied)."
        )

    caveat = (
        f"{code_ref}: {formula_str}. "
        f"t = {t:.0f} mm, h = {h:.0f} mm, lw = {spec.wall_length_lw_m:.3f} m, "
        f"material = {spec.material}, f' = {fc:.1f} MPa, "
        f"end_conditions = {spec.end_conditions} (k={k}). "
        f"{slenderness_str}. "
        f"Slenderness factor = {slenderness_factor:.6f}. "
        f"Ag = {Ag_per_m:.0f} mm²/m (unit-strip b=1000mm). "
        f"φ·Pn = {phi_Pn_kN_per_m:.3f} kN/m (φ={phi}). "
        f"P_factored = {P_factored_kN_per_m:.3f} kN/m. "
        f"DCR = {P_factored_kN_per_m:.3f}/{phi_Pn_kN_per_m:.3f} = "
        f"{'inf' if phi_Pn_kN_per_m == 0 else f'{dcr:.6f}'} "
        f"({'≤ 1.0 ADEQUATE' if dcr_ok and not large_eccentricity and not slenderness_limit_exceeded else '> 1.0 or N/A INADEQUATE'}). "
        f"{ecc_note}"
        f"{masonry_hr_note}"
        f"{rebar_note} "
        "SCOPE LIMITATIONS: "
        "(1) ACI §11.5.3.1 EMPIRICAL METHOD only — valid ONLY for e ≤ t/6. "
        "Large eccentricity requires full PM interaction analysis "
        "(ACI §11.4 axial+flexure or ACI §22.4.2.2 method). "
        "(2) Reinforcement is NOT credited in ACI §11.5.3.1 formula — "
        "call the ACI §22.4.2.2 pier/column method for RC capacity with rebar. "
        "(3) TMS Eq 8-22 valid for h_eff/r ≤ 99 only. "
        "(4) In-plane shear wall behaviour (ACI §11.6 / TMS §8.2) is NOT checked here. "
        "(5) Factored loads must reflect governing ACI §5.3 / TMS §9.3 load combinations. "
        "(6) For unreinforced masonry ACI §12 (masonry in ACI 530) may impose additional "
        "limits on f'm and inspection class — not automatically enforced here. "
        "Always verify with a licensed structural engineer. "
        "Refs: ACI 318-19 §11.5.3.1; TMS 402-22 §8.3 Eq 8-22; Wight §13.13."
    )

    return BearingWallReport(
        phi_Pn_kN_per_m=phi_Pn_kN_per_m,
        slenderness_factor=slenderness_factor,
        dcr=dcr,
        adequate=adequate,
        governing_check=governing_check,
        honest_caveat=caveat,
    )
