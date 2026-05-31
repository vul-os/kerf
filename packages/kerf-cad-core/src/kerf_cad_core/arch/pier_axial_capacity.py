"""
kerf_cad_core.arch.pier_axial_capacity — Masonry and RC pier axial-load capacity check.

Implements:
  - TMS 402-22 §8.3 masonry pier axial capacity (clay masonry, concrete masonry):
      φ·Pn = φ · 0.80 · f'm · Ag × (slenderness factor)
      Slenderness factor (TMS Eq 8-22): C_s = 1 − (h_eff / (140·r))²   for h_eff/r ≤ 99
      h_eff/r > 99 → exceeds slenderness limit (member too slender for this formula)

  - ACI 318-19 §22.4.2.2 reinforced concrete pier axial capacity (same as short column):
      φ·Pn = φ · 0.80 · [0.85·f'c·(Ag − As) + fy·As] × (slenderness factor)
      Slenderness factor applied per Drysdale-Hamid "Masonry Structures" §10 / ACI §6.2.5
      notation: 1 − (h_eff / (140·r))²   (same reduction form for slender RC pier checks)

  Radius of gyration:  r = √(I/A)
    For rectangular cross-section (width b, thickness t):
      I about weak axis = t · b³ / 12   (bending about weak axis, width=pier_width)
      A = b · t
      r = √(I/A) = b / √12 = 0.2887 · b

  Effective length kh per end conditions:
      fixed-fixed   → k = 0.5
      pin-pin       → k = 1.0
      fixed-pin     → k = 0.7
      cantilever    → k = 2.0

  Note on dimension orientation: pier_width_mm is the in-plane dimension (governs I about
  the weak axis for slenderness), pier_thickness_mm is the out-of-plane dimension.
  The governing slenderness uses the weaker (larger h/r) direction.  For a square pier both
  directions are equal; for a rectangular pier the calculation uses the dimension that gives
  the largest h/r (i.e. the smaller of width and thickness governs r).

All dimensions in **millimetres** and **MPa**; results in **kN**.

References:
  TMS 402-22, "Building Code Requirements and Specification for Masonry Structures",
    §8.3 (Axial load-bearing masonry piers), Eq 8-22 (slenderness).
  ACI 318-19, "Building Code Requirements for Structural Concrete",
    §22.4.2.2 (nominal axial compressive strength).
  Drysdale R.G. & Hamid A.A. (2005) *Masonry Structures: Behaviour and Design* 3e §10
    (pier slenderness, effective-height factor k).

SCOPE LIMITATIONS (honest caveats):
  - Pure concentric axial load ONLY.  Eccentric loads and combined axial + bending
    (moment interaction / PM interaction surface) are NOT modelled here.
  - TMS 402-22 §8.3 formula valid for h/r ≤ 99 only.  Beyond this limit the module
    sets governing_failure_mode = "slenderness_limit_exceeded" and returns φ·Pn = 0.
  - For reinforced_concrete, the slenderness factor is applied in the same form as TMS
    for consistency with the task scope; ACI §6.2.5 moment magnifier (full slender-column
    analysis) is NOT included.
  - Grout fill, mortar type, and inspection-level modifiers (TMS §4.6.3 Φ factors) are
    excluded — caller must supply a representative net f'm.
  - No lateral-load or shear capacity check.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "PierSpec",
    "PierAxialReport",
    "check_pier_axial",
]

# ---------------------------------------------------------------------------
# End-condition effective-length factors (k)
# ---------------------------------------------------------------------------

_K_FACTORS: dict[str, float] = {
    "fixed_fixed": 0.5,
    "pin_pin": 1.0,
    "fixed_pin": 0.7,
    "cantilever": 2.0,
}

# ---------------------------------------------------------------------------
# Supported material identifiers
# ---------------------------------------------------------------------------

_VALID_MATERIALS = {"clay_masonry", "concrete_masonry", "reinforced_concrete"}

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class PierSpec:
    """
    Geometric and material properties of a slender masonry or concrete pier.

    Parameters
    ----------
    pier_width_mm : float
        Width of the pier cross-section in mm (in-plane dimension).
    pier_thickness_mm : float
        Thickness of the pier cross-section in mm (out-of-plane dimension).
    height_h_mm : float
        Clear height of the pier (unsupported length) in mm.
    material : str
        Material type — one of:
          ``"clay_masonry"``       → TMS 402-22 §8.3 with f'm
          ``"concrete_masonry"``   → TMS 402-22 §8.3 with f'm
          ``"reinforced_concrete"`` → ACI 318-19 §22.4.2.2 with f'c + rebar
    f_prime_MPa : float
        Specified compressive strength in MPa.
        For masonry: net f'm (MPa).
        For RC: specified f'c (MPa).
    As_total_mm2 : float
        Total longitudinal reinforcement area in mm².
        Set to 0.0 for unreinforced masonry piers.
    fy_MPa : float
        Yield strength of reinforcing steel in MPa.
        Ignored for unreinforced masonry (As_total_mm2 = 0).
    end_conditions : str
        Boundary conditions at pier ends — one of:
          ``"fixed_fixed"``  → k = 0.5  (both ends restrained against rotation)
          ``"pin_pin"``      → k = 1.0  (both ends pinned, typical)
          ``"fixed_pin"``    → k = 0.7  (one end fixed, one pinned)
          ``"cantilever"``   → k = 2.0  (fixed base, free top)
    """
    pier_width_mm: float
    pier_thickness_mm: float
    height_h_mm: float
    material: str  # "clay_masonry" | "concrete_masonry" | "reinforced_concrete"
    f_prime_MPa: float
    As_total_mm2: float
    fy_MPa: float
    end_conditions: str  # "fixed_fixed" | "pin_pin" | "fixed_pin" | "cantilever"


@dataclass
class PierAxialReport:
    """
    Output of a pier axial-load capacity check.

    Parameters
    ----------
    phi_Pn_kN : float
        Design axial compressive strength φ·Pn in kN.
        Equals 0.0 when slenderness limit is exceeded (h/r > 99).
    slenderness_factor : float
        Dimensionless slenderness reduction factor C_s = 1 − (h_eff/(140·r))²
        (TMS Eq 8-22).  Equals 0.0 when h/r > 99.
    h_over_r : float
        Effective slenderness ratio h_eff / r (dimensionless).
    governing_failure_mode : str
        One of ``"yielding"`` (capacity governs, no slenderness issues),
        ``"slender_buckling"`` (slenderness factor < 1.0 but h/r ≤ 99),
        ``"slenderness_limit_exceeded"`` (h/r > 99, formula not applicable).
    honest_caveat : str
        Plain-text scope disclaimer with key computed values and references.
    """
    phi_Pn_kN: float
    slenderness_factor: float
    h_over_r: float
    governing_failure_mode: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Main check function
# ---------------------------------------------------------------------------


def check_pier_axial(
    pier: PierSpec,
    P_factored_kN: float,
    phi: float = 0.65,
) -> PierAxialReport:
    """
    Check axial-load capacity of a slender masonry or concrete pier.

    Implements TMS 402-22 §8.3 (clay/concrete masonry) and ACI 318-19 §22.4.2.2
    (reinforced concrete) with the TMS Eq 8-22 slenderness reduction factor:

        C_s = 1 − (h_eff / (140 · r))²    valid for h_eff / r ≤ 99

    where h_eff = k · h  (effective height from end-condition factor k)
    and   r = min(pier_width_mm, pier_thickness_mm) / √12  (radius of gyration,
          governing — smallest dimension gives largest h/r).

    Capacity:
        Masonry:    φ·Pn = φ · 0.80 · f'm · Ag · C_s
        RC:         φ·Pn = φ · 0.80 · [0.85·f'c·(Ag − As) + fy·As] · C_s

    Parameters
    ----------
    pier : PierSpec
        Pier geometry, material, and boundary conditions.
    P_factored_kN : float
        Factored axial compressive demand Pu in kN (must be ≥ 0).
    phi : float
        Strength-reduction factor φ (default 0.65 per TMS 402-22 §9.3 / ACI Table 21.2.2
        for compression-controlled members).

    Returns
    -------
    PierAxialReport

    Raises
    ------
    ValueError
        If any geometric/material parameter is non-positive or out of range,
        or if material / end_conditions strings are not recognised.
    """
    # --- Input validation ---------------------------------------------------
    if pier.pier_width_mm <= 0:
        raise ValueError(f"pier_width_mm must be > 0, got {pier.pier_width_mm}")
    if pier.pier_thickness_mm <= 0:
        raise ValueError(f"pier_thickness_mm must be > 0, got {pier.pier_thickness_mm}")
    if pier.height_h_mm <= 0:
        raise ValueError(f"height_h_mm must be > 0, got {pier.height_h_mm}")
    if pier.material not in _VALID_MATERIALS:
        raise ValueError(
            f"material must be one of {sorted(_VALID_MATERIALS)}, got {pier.material!r}"
        )
    if pier.f_prime_MPa <= 0:
        raise ValueError(f"f_prime_MPa must be > 0, got {pier.f_prime_MPa}")
    if pier.As_total_mm2 < 0:
        raise ValueError(f"As_total_mm2 must be ≥ 0, got {pier.As_total_mm2}")
    if pier.end_conditions not in _K_FACTORS:
        raise ValueError(
            f"end_conditions must be one of {sorted(_K_FACTORS)}, "
            f"got {pier.end_conditions!r}"
        )
    if not (0.0 < phi <= 1.0):
        raise ValueError(f"phi must be in (0, 1], got {phi}")
    if P_factored_kN < 0:
        raise ValueError(f"P_factored_kN must be ≥ 0, got {P_factored_kN}")

    # --- Geometry -----------------------------------------------------------
    b = pier.pier_width_mm       # in-plane width, mm
    t = pier.pier_thickness_mm   # out-of-plane thickness, mm
    h = pier.height_h_mm         # clear height, mm

    A_g = b * t                  # gross cross-sectional area, mm²

    # Radius of gyration — use the governing (smaller) cross-section dimension
    # to get the LARGEST h/r (most critical slenderness).
    # r = min(b, t) / √12
    # I = min_dim · max_dim³ / 12  if bending about the axis through max_dim ... but
    # for a rectangular section: r about axis through the width dimension = t/√12,
    # r about axis through the thickness dimension = b/√12.
    # The governing slenderness uses the smaller r (larger h/r).
    r_b = b / math.sqrt(12.0)    # radius of gyration for bending about b-dimension axis
    r_t = t / math.sqrt(12.0)    # radius of gyration for bending about t-dimension axis
    r = min(r_b, r_t)            # governing (smallest r → largest h/r)

    # --- Effective height ---------------------------------------------------
    k = _K_FACTORS[pier.end_conditions]
    h_eff = k * h                # effective height, mm

    # --- Slenderness ratio --------------------------------------------------
    h_over_r = h_eff / r

    # --- Slenderness factor (TMS Eq 8-22 / Drysdale §10) -------------------
    _TMS_LIMIT = 99.0
    if h_over_r > _TMS_LIMIT:
        # Section too slender — TMS formula does not apply
        return PierAxialReport(
            phi_Pn_kN=0.0,
            slenderness_factor=0.0,
            h_over_r=round(h_over_r, 3),
            governing_failure_mode="slenderness_limit_exceeded",
            honest_caveat=(
                f"h_eff/r = {h_over_r:.1f} > 99 — TMS 402-22 §8.3 Eq 8-22 slenderness "
                f"formula does NOT apply (limit = 99). Pier is too slender for this "
                f"simplified method. Perform a buckling analysis or redesign cross-section. "
                f"φ·Pn is returned as 0. "
                f"material={pier.material}, k={k}, h_eff={h_eff:.1f} mm, r={r:.2f} mm."
            ),
        )

    slenderness_factor = 1.0 - (h_eff / (140.0 * r)) ** 2

    # --- Nominal axial strength Pn ------------------------------------------
    if pier.material in ("clay_masonry", "concrete_masonry"):
        # TMS 402-22 §8.3: unreinforced masonry net area strength
        # (reinforcement in masonry piers contributes only when fully grouted;
        # caller should embed steel contribution in f'm or use RC path)
        Pn_N = 0.80 * pier.f_prime_MPa * A_g  # N (1 MPa × mm² = N)
        material_note = (
            f"TMS 402-22 §8.3 masonry pier: φ·Pn = φ·0.80·f'm·Ag·C_s; "
            f"f'm = {pier.f_prime_MPa} MPa, Ag = {A_g:.0f} mm²"
        )
    else:
        # ACI 318-19 §22.4.2.2 reinforced concrete
        A_s = pier.As_total_mm2
        A_c = A_g - A_s
        if A_s >= A_g:
            raise ValueError(
                f"As_total_mm2 ({A_s}) must be less than gross area Ag ({A_g}) mm²"
            )
        Pn_N = 0.80 * (0.85 * pier.f_prime_MPa * A_c + pier.fy_MPa * A_s)  # N
        material_note = (
            f"ACI 318-19 §22.4.2.2 RC pier: φ·Pn = φ·0.80·[0.85·f'c·(Ag-As)+fy·As]·C_s; "
            f"f'c = {pier.f_prime_MPa} MPa, As = {A_s:.1f} mm², fy = {pier.fy_MPa} MPa, "
            f"Ag = {A_g:.0f} mm²"
        )

    phi_Pn_kN = phi * Pn_N * slenderness_factor / 1_000.0  # N → kN

    # --- Governing failure mode ---------------------------------------------
    if slenderness_factor < 1.0:
        governing_failure_mode = "slender_buckling"
    else:
        governing_failure_mode = "yielding"

    # --- DCR for caveat text ------------------------------------------------
    dcr = P_factored_kN / phi_Pn_kN if phi_Pn_kN > 0 else float("inf")
    status = "OK" if dcr <= 1.0 else "FAIL"

    # --- Honest caveat ------------------------------------------------------
    caveat = (
        f"{material_note}. "
        f"End conditions: {pier.end_conditions!r} (k={k}); "
        f"h = {h:.0f} mm, h_eff = h_eff = k·h = {h_eff:.0f} mm; "
        f"governing dimension = {min(b, t):.0f} mm, r = {r:.3f} mm; "
        f"h_eff/r = {h_over_r:.2f} ≤ 99. "
        f"Slenderness factor C_s = 1-(h_eff/(140·r))² = {slenderness_factor:.4f}. "
        f"φ·Pn = {phi_Pn_kN:.2f} kN; Pu = {P_factored_kN:.2f} kN; "
        f"DCR = {dcr:.3f} → {status}. "
        f"SCOPE: Concentric axial load ONLY — no eccentricity, no moment interaction, "
        f"no PM curve. TMS Eq 8-22 valid for h_eff/r ≤ 99. "
        f"Grout fill and TMS inspection-level Φ modifiers not applied here. "
        f"Always verify with a licensed structural engineer. "
        f"Refs: TMS 402-22 §8.3 Eq 8-22; ACI 318-19 §22.4.2.2; "
        f"Drysdale-Hamid *Masonry Structures* §10."
    )

    return PierAxialReport(
        phi_Pn_kN=round(phi_Pn_kN, 3),
        slenderness_factor=round(slenderness_factor, 6),
        h_over_r=round(h_over_r, 4),
        governing_failure_mode=governing_failure_mode,
        honest_caveat=caveat,
    )
