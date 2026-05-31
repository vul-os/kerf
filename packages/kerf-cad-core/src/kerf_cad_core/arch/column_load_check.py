"""
kerf_cad_core.arch.column_load_check — Architectural column axial-load capacity checks.

Implements:
  - AISC 360-22 §E3 steel column compression:
      Equation E3-2 (inelastic buckling, KL/r ≤ 4.71√(E/Fy))
      Equation E3-3 (elastic Euler buckling, KL/r > 4.71√(E/Fy))
      φ_c = 0.90 (LRFD, per AISC 360-22 §E1)
  - ACI 318-19 §22.4.2.2 short-column nominal strength:
      φ·Pn = φ · 0.80 · [0.85·f'c·(Ag − Ast) + fy·Ast]
      φ = 0.65 (tied, default) or 0.75 (spiral)

All dimensions in **millimetres** and **MPa**; results in **kN**.

References:
  AISC 360-22, "Specification for Structural Steel Buildings", Chapter E.
  ACI 318-19, "Building Code Requirements for Structural Concrete", §22.4.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "SteelColumnSpec",
    "ConcreteColumnSpec",
    "ColumnLoadReport",
    "check_steel_column",
    "check_concrete_column",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SteelColumnSpec:
    """
    Geometric and material properties of a steel column section.

    Parameters
    ----------
    section_label : str
        Human-readable section label, e.g. ``"W14x90"`` or ``"HSS 152x152x9.5"``.
    A_mm2 : float
        Gross cross-sectional area in mm².
    r_min_mm : float
        Minimum radius of gyration (weak-axis governs) in mm.
    Fy_MPa : float
        Specified minimum yield stress in MPa (e.g. 345 MPa for A572 Gr 50).
    K : float
        Effective-length factor (1.0 = pin-pin, 0.5 = fixed-fixed, 0.7 = fixed-pin).
    L_mm : float
        Unbraced column length in mm.
    E_MPa : float
        Elastic modulus in MPa. Default 200 000 MPa (200 GPa).
    """
    section_label: str
    A_mm2: float
    r_min_mm: float
    Fy_MPa: float
    K: float
    L_mm: float
    E_MPa: float = field(default=200_000.0)


@dataclass
class ConcreteColumnSpec:
    """
    Properties of a reinforced concrete column (short column, ACI 318-19 §22.4).

    Parameters
    ----------
    A_g_mm2 : float
        Gross cross-sectional area of the column in mm².
    A_st_mm2 : float
        Total area of longitudinal steel reinforcement in mm².
    fc_MPa : float
        Specified compressive strength of concrete (f'c) in MPa.
    fy_MPa : float
        Specified yield strength of reinforcing steel in MPa.
    phi : float
        Strength-reduction factor φ.  Default 0.65 (tied column per ACI 318-19 Table 21.2.2).
        Use 0.75 for spiral-reinforced columns.
    """
    A_g_mm2: float
    A_st_mm2: float
    fc_MPa: float
    fy_MPa: float
    phi: float = 0.65


@dataclass
class ColumnLoadReport:
    """
    Output of a column load-check calculation.

    Parameters
    ----------
    phi_Pn_kN : float
        Design axial compressive strength φ·Pn in kN.
    demand_capacity_ratio : float
        Demand / capacity ratio (DCR).  DCR > 1.0 → column fails (overstressed).
    governing_mode : str
        Buckling or strength mode that governed the calculation.
    controls : str
        ``"OK"`` if DCR ≤ 1.0, ``"FAIL"`` if DCR > 1.0.
    honest_caveat : str
        Code-compliance caveat: scope limitations, disclaimer, reference.
    """
    phi_Pn_kN: float
    demand_capacity_ratio: float
    governing_mode: str
    controls: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Steel column — AISC 360-22 §E3
# ---------------------------------------------------------------------------

def check_steel_column(spec: SteelColumnSpec, P_service_kN: float) -> ColumnLoadReport:
    """
    Check axial-load capacity of a steel column per AISC 360-22 §E3 (LRFD).

    Implements:
    - AISC E3-4: Fe = π² E / (KL/r)²
    - AISC E3-2: Fcr = [0.658^(Fy/Fe)] · Fy        when KL/r ≤ 4.71√(E/Fy)
    - AISC E3-3: Fcr = 0.877 · Fe                   when KL/r > 4.71√(E/Fy)
    - AISC E1:   φ_c = 0.90 (LRFD)
    - AISC E3-1: Pn = Fcr · Ag
    - φ_c · Pn = 0.90 · Fcr · Ag

    Parameters
    ----------
    spec : SteelColumnSpec
        Section properties and unbraced length.
    P_service_kN : float
        Required (demanded) axial compression in kN (factored load for LRFD).

    Returns
    -------
    ColumnLoadReport

    Raises
    ------
    ValueError
        If any geometric/material parameter is non-positive.
    """
    # --- Input validation ------------------------------------------------
    if spec.A_mm2 <= 0:
        raise ValueError(f"A_mm2 must be > 0, got {spec.A_mm2}")
    if spec.r_min_mm <= 0:
        raise ValueError(f"r_min_mm must be > 0, got {spec.r_min_mm}")
    if spec.Fy_MPa <= 0:
        raise ValueError(f"Fy_MPa must be > 0, got {spec.Fy_MPa}")
    if spec.E_MPa <= 0:
        raise ValueError(f"E_MPa must be > 0, got {spec.E_MPa}")
    if spec.K <= 0:
        raise ValueError(f"K must be > 0, got {spec.K}")
    if spec.L_mm <= 0:
        raise ValueError(f"L_mm must be > 0, got {spec.L_mm}")

    # --- AISC 360-22 §E3 ------------------------------------------------
    KLr = spec.K * spec.L_mm / spec.r_min_mm  # Eq. E3 slenderness ratio
    threshold = 4.71 * math.sqrt(spec.E_MPa / spec.Fy_MPa)   # AISC E3 limit

    # Elastic buckling stress (Euler), Eq. E3-4
    Fe = (math.pi ** 2 * spec.E_MPa) / (KLr ** 2)  # MPa

    # --- Slenderness flag -----------------------------------------------
    slender_flag = ""
    if KLr > 200:
        slender_flag = "; WARNING: KL/r > 200 — slender column (AISC User Note §E2)"

    if KLr <= threshold:
        # Inelastic buckling, Eq. E3-2
        Fcr = (0.658 ** (spec.Fy_MPa / Fe)) * spec.Fy_MPa  # MPa
        mode = f"inelastic flexural buckling (AISC E3-2, KL/r={KLr:.1f})"
    else:
        # Elastic (Euler) buckling, Eq. E3-3
        Fcr = 0.877 * Fe  # MPa
        mode = f"elastic flexural buckling (AISC E3-3, KL/r={KLr:.1f})"

    # Nominal and design strengths
    phi_c = 0.90
    Pn_kN = Fcr * spec.A_mm2 / 1_000.0      # N → kN
    phi_Pn_kN = phi_c * Pn_kN

    # Demand / capacity ratio
    dcr = P_service_kN / phi_Pn_kN if phi_Pn_kN > 0 else float("inf")
    controls = "OK" if dcr <= 1.0 else "FAIL"

    caveat = (
        f"AISC 360-22 §E3 LRFD; flexural buckling about weak axis assumed; "
        f"local buckling (§E7), torsional buckling (§E4), and combined loading not checked here. "
        f"Pu (factored demand) = {P_service_kN:.1f} kN, φPn = {phi_Pn_kN:.1f} kN, "
        f"DCR = {dcr:.3f}{slender_flag}."
    )
    return ColumnLoadReport(
        phi_Pn_kN=phi_Pn_kN,
        demand_capacity_ratio=dcr,
        governing_mode=mode,
        controls=controls,
        honest_caveat=caveat,
    )


# ---------------------------------------------------------------------------
# Concrete column — ACI 318-19 §22.4
# ---------------------------------------------------------------------------

def check_concrete_column(spec: ConcreteColumnSpec, P_service_kN: float) -> ColumnLoadReport:
    """
    Check axial-load capacity of a short reinforced concrete column per ACI 318-19 §22.4.2.2.

    Formula (ACI 22.4.2.2):
        φ·Pn = φ · 0.80 · [0.85·f'c·(Ag − Ast) + fy·Ast]

    The 0.80 factor accounts for minimum eccentricity (tied column).
    This formula applies to **short columns** (slenderness ratio does not govern).
    Slenderness amplification (ACI §6.6.4 / §6.7) is NOT applied here.

    Parameters
    ----------
    spec : ConcreteColumnSpec
        Section properties.
    P_service_kN : float
        Required (factored) axial compressive load Pu in kN.

    Returns
    -------
    ColumnLoadReport

    Raises
    ------
    ValueError
        If any geometric/material parameter is non-positive, or Ast ≥ Ag.
    """
    # --- Input validation ------------------------------------------------
    if spec.A_g_mm2 <= 0:
        raise ValueError(f"A_g_mm2 must be > 0, got {spec.A_g_mm2}")
    if spec.A_st_mm2 < 0:
        raise ValueError(f"A_st_mm2 must be ≥ 0, got {spec.A_st_mm2}")
    if spec.A_st_mm2 >= spec.A_g_mm2:
        raise ValueError("A_st_mm2 must be < A_g_mm2 (steel cannot exceed gross section)")
    if spec.fc_MPa <= 0:
        raise ValueError(f"fc_MPa must be > 0, got {spec.fc_MPa}")
    if spec.fy_MPa <= 0:
        raise ValueError(f"fy_MPa must be > 0, got {spec.fy_MPa}")
    if not (0.0 < spec.phi <= 1.0):
        raise ValueError(f"phi must be in (0, 1], got {spec.phi}")

    # Reinforcement ratio check (ACI §10.6.1.1: 0.01 ≤ ρg ≤ 0.08)
    rho_g = spec.A_st_mm2 / spec.A_g_mm2
    rho_warn = ""
    if rho_g < 0.01 or rho_g > 0.08:
        rho_warn = (
            f"; NOTE: ρg = {rho_g:.4f} is outside ACI 318-19 §10.6.1.1 limits [0.01, 0.08]"
        )

    # --- ACI 318-19 §22.4.2.2 -------------------------------------------
    Ac = spec.A_g_mm2 - spec.A_st_mm2   # net concrete area, mm²
    Pn_N = 0.80 * (0.85 * spec.fc_MPa * Ac + spec.fy_MPa * spec.A_st_mm2)  # N
    phi_Pn_kN = spec.phi * Pn_N / 1_000.0  # N → kN

    mode = "short-column axial compression (ACI 318-19 §22.4.2.2)"

    dcr = P_service_kN / phi_Pn_kN if phi_Pn_kN > 0 else float("inf")
    controls = "OK" if dcr <= 1.0 else "FAIL"

    caveat = (
        f"ACI 318-19 §22.4.2.2; valid for short columns only "
        f"(slenderness amplification per §6.6.4/§6.7 not applied). "
        f"Tied column φ=0.65 default (spiral: φ=0.75). "
        f"Pu = {P_service_kN:.1f} kN, φPn = {phi_Pn_kN:.1f} kN, "
        f"DCR = {dcr:.3f}, ρg = {rho_g:.4f}{rho_warn}."
    )
    return ColumnLoadReport(
        phi_Pn_kN=phi_Pn_kN,
        demand_capacity_ratio=dcr,
        governing_mode=mode,
        controls=controls,
        honest_caveat=caveat,
    )
