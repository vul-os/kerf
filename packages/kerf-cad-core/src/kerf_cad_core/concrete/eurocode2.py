"""
kerf_cad_core.concrete.eurocode2 — EN 1992-1-1 (Eurocode 2) reinforced-concrete design.

Units: SI throughout.
  Lengths / dimensions : millimetres (mm)
  Areas               : square millimetres (mm²)
  Forces              : kilonewtons (kN)
  Moments             : kilonewton·metres (kN·m)
  Stresses            : megapascals (MPa = N/mm²)
  fck, fyk            : MPa

All functions return plain dicts.  Warnings are collected in result["warnings"]
(list of strings); the functions never raise.

References
----------
EN 1992-1-1:2004 "Eurocode 2: Design of Concrete Structures — Part 1-1"
Mosley, W.H., Bungey, J.H. & Hulse, R. "Reinforced Concrete Design to
  Eurocode 2", 7th ed. (MBH7).
Beeby, A.W. & Narayanan, R.S. "Designers' Guide to Eurocode 2" (B&N).

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# Material partial factors (EN 1992-1-1 §2.4.2.4 Table 2.1N, persistent/transient)
# ---------------------------------------------------------------------------

EC2_GAMMA_C: float = 1.5   # γC — partial factor for concrete
EC2_GAMMA_S: float = 1.15  # γS — partial factor for reinforcement steel
EC2_ALPHA_CC: float = 1.0  # α_cc — long-term strength reduction (recommended 1.0;
                            #        some NADs use 0.85)

# ---------------------------------------------------------------------------
# Concrete strength classes (EN 1992-1-1 Table 3.1)
# Keys: "C{fck}/{fckcube}" — values: (fck, fctm, Ecm) all in MPa
# fck  = characteristic cylinder strength (MPa)
# fctm = mean axial tensile strength (MPa)
# Ecm  = secant modulus of elasticity (GPa) — stored as MPa (×1000)
# ---------------------------------------------------------------------------

EC2_STRENGTH_CLASSES: dict[str, dict[str, float]] = {
    "C12/15": {"fck": 12,  "fctm": 1.6,  "Ecm": 27_000},
    "C16/20": {"fck": 16,  "fctm": 1.9,  "Ecm": 29_000},
    "C20/25": {"fck": 20,  "fctm": 2.2,  "Ecm": 30_000},
    "C25/30": {"fck": 25,  "fctm": 2.6,  "Ecm": 31_000},
    "C30/37": {"fck": 30,  "fctm": 2.9,  "Ecm": 32_000},
    "C35/45": {"fck": 35,  "fctm": 3.2,  "Ecm": 34_000},
    "C40/50": {"fck": 40,  "fctm": 3.5,  "Ecm": 35_000},
    "C45/55": {"fck": 45,  "fctm": 3.8,  "Ecm": 36_000},
    "C50/60": {"fck": 50,  "fctm": 4.1,  "Ecm": 37_000},
    "C55/67": {"fck": 55,  "fctm": 4.2,  "Ecm": 38_000},
    "C60/75": {"fck": 60,  "fctm": 4.4,  "Ecm": 39_000},
    "C70/85": {"fck": 70,  "fctm": 4.6,  "Ecm": 41_000},
    "C80/95": {"fck": 80,  "fctm": 4.8,  "Ecm": 42_000},
    "C90/105": {"fck": 90, "fctm": 5.0,  "Ecm": 44_000},
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fcd(fck: float, alpha_cc: float = EC2_ALPHA_CC) -> float:
    """Design compressive strength of concrete (EN 1992-1-1 §3.1.6 Eq. 3.15).

    fcd = α_cc · fck / γC  (MPa)
    """
    return alpha_cc * fck / EC2_GAMMA_C


def _fyd(fyk: float) -> float:
    """Design yield strength of reinforcement (EN 1992-1-1 §3.2.7).

    fyd = fyk / γS  (MPa)
    """
    return fyk / EC2_GAMMA_S


def _lambda_eta(fck: float) -> tuple[float, float]:
    """Rectangular stress-block factors λ and η per EN 1992-1-1 §3.1.7.

    For fck ≤ 50 MPa:  λ = 0.8, η = 1.0
    For 50 < fck ≤ 90: λ = 0.8 − (fck−50)/400,  η = 1.0 − (fck−50)/200
    """
    if fck <= 50:
        return 0.8, 1.0
    lam = 0.8 - (fck - 50) / 400.0
    eta = 1.0 - (fck - 50) / 200.0
    return lam, eta


def _xu_limit(fck: float) -> float:
    """EC2 ductility limit on neutral-axis depth ratio xu/d.

    EN 1992-1-1 §5.5(4): xu/d ≤ 0.45 for fck ≤ 50; ≤ 0.35 for fck > 50.
    """
    return 0.45 if fck <= 50 else 0.35


def _rho_min_beam_ec2(fck: float, fyk: float) -> float:
    """Minimum tension steel ratio for beams (EN 1992-1-1 §9.2.1.1 Eq. 9.1N).

    ρ_min = max(0.26 · fctm / fyk, 0.0013)
    Approximates fctm from fck using Table 3.1 fit.
    """
    # Approximate fctm: 0.3*fck^(2/3) for fck ≤ 50; see Table 3.1 trend
    fctm = 0.30 * fck ** (2.0 / 3.0)
    return max(0.26 * fctm / fyk, 0.0013)


def _rho_max_beam_ec2() -> float:
    """Maximum tension steel ratio — EN 1992-1-1 §9.2.1.1: ρ ≤ 0.04."""
    return 0.04


# ---------------------------------------------------------------------------
# 1. Design strengths (public API)
# ---------------------------------------------------------------------------

def ec2_design_strengths(
    fck: float,
    fyk: float,
    *,
    alpha_cc: float = EC2_ALPHA_CC,
) -> dict[str, Any]:
    """Compute EC2 design strengths for concrete and steel.

    Parameters (SI, MPa)
    ----------
    fck      : characteristic concrete cylinder strength (MPa)
    fyk      : characteristic yield strength of reinforcement (MPa)
    alpha_cc : long-term reduction factor for concrete (default 1.0)

    Returns
    -------
    dict with keys:
      fcd_MPa     — design compressive strength of concrete (MPa)
      fyd_MPa     — design yield strength of steel (MPa)
      gamma_C     — partial factor for concrete (1.5)
      gamma_S     — partial factor for steel (1.15)
      alpha_cc    — α_cc used
      lambda_     — rectangular stress-block λ factor
      eta         — rectangular stress-block η factor
      warnings    — list[str]
    """
    warnings: list[str] = []
    lam, eta = _lambda_eta(fck)
    return {
        "fcd_MPa": _fcd(fck, alpha_cc),
        "fyd_MPa": _fyd(fyk),
        "gamma_C": EC2_GAMMA_C,
        "gamma_S": EC2_GAMMA_S,
        "alpha_cc": alpha_cc,
        "lambda_": lam,
        "eta": eta,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 2. Flexure — rectangular section, singly-reinforced (or doubly if needed)
# ---------------------------------------------------------------------------

def ec2_flexure(
    b: float,
    d: float,
    fck: float,
    fyk: float,
    MEd: float,
    *,
    alpha_cc: float = EC2_ALPHA_CC,
    d2: float = 0.0,
) -> dict[str, Any]:
    """Required tension steel for a rectangular beam (EC2 rectangular stress block).

    Uses the approach of Mosley/Bungey/Hulse §4.5 and EN 1992-1-1 §6.1.

    Parameters (SI)
    ----------
    b    : beam width (mm)
    d    : effective depth to tension steel centroid (mm)
    fck  : characteristic concrete cylinder strength (MPa)
    fyk  : characteristic yield strength of steel (MPa)
    MEd  : design bending moment demand (kN·m)
    alpha_cc : long-term reduction factor for concrete (default 1.0)
    d2   : depth to compression steel centroid (mm); used only if doubly
            reinforced is required (default 0 — autocalculated as 50 mm if needed)

    Returns
    -------
    dict with keys:
      As_req_mm2        — required tension steel area (mm²)
      As2_req_mm2       — required compression steel area (mm²); 0 if singly reinf.
      xu_mm             — neutral-axis depth (mm)
      xu_d              — neutral-axis depth ratio xu/d
      xu_d_limit        — EC2 ductility limit (0.45 or 0.35)
      ductility_ok      — bool: xu/d ≤ limit
      MRd_kNm           — design moment resistance (kN·m); ≥ MEd
      K                 — moment coefficient M/(b·d²·fck)
      K_prime           — K' (limiting K for singly reinforced)
      doubly_reinforced — bool: True if compression steel required
      rho_req           — required tension steel ratio
      rho_min           — EC2 minimum steel ratio (§9.2.1.1)
      rho_max           — EC2 maximum steel ratio (0.04)
      warnings          — list[str]

    Notes
    -----
    Approach:
      K  = MEd·10⁶ / (b · d² · fcd)    [dimensionless; MEd in kN·m]
      z  = d · [0.5 + √(0.25 - K/1.134)]   (lever arm, λ=0.8,η=1→1.134=η·λ/(2·λ)×2)
      More precisely: z = d·(0.5 + √(0.25 - K/(η·λ/0.5·... )))
    We use the standard EC2 parabolic approach with lever arm:
      z = d · min(0.5 + √(0.25 - K/1.134), 0.95)
    K' (singly reinforced limit) based on xu_lim/d:
      K' = (xu_lim/d) · λ · (1 - (xu_lim/d) · λ / 2) · η
    """
    warnings: list[str] = []

    fcd_val = _fcd(fck, alpha_cc)
    fyd_val = _fyd(fyk)
    lam, eta = _lambda_eta(fck)
    xu_lim = _xu_limit(fck)
    rho_min = _rho_min_beam_ec2(fck, fyk)
    rho_max = _rho_max_beam_ec2()

    # Moment in N·mm
    MEd_Nmm = MEd * 1e6

    # Dimensionless moment coefficient K
    K = MEd_Nmm / (b * d**2 * fcd_val)

    # K' — limit for singly reinforced section (based on xu/d = xu_lim)
    xu_d_lim = xu_lim
    K_prime = eta * xu_d_lim * lam * (1.0 - xu_d_lim * lam / 2.0)

    doubly_reinforced = K > K_prime

    # Lever arm z for singly-reinforced case (or singly contribution for doubly)
    # From equilibrium: K = η·fcd·b·(λ·xu)·(d - λ·xu/2) / (b·d²·fcd)
    #                     = η·λ·(xu/d)·(1 - λ·(xu/d)/2)
    # → quadratic in (xu/d): η·λ² /2 · x² - η·λ·x + K = 0  where x = xu/d
    # Lever arm z/d = 1 - λ·(xu/d)/2

    def _lever_arm_ratio(K_use: float) -> float:
        """Return z/d for given K (singly-reinforced contribution)."""
        # Standard EC2 lever-arm formula (MBH7 eq 4.8):
        #   z/d = 0.5 + sqrt(0.25 - K_use / (eta * lambda_ / ... ))
        # Exact derivation from quadratic:
        #   η·λ·(xu/d) · (1 - λ·(xu/d)/2) = K_use
        # Let u = λ·(xu/d):  η·u·(1 - u/2) = K_use → u² - 2u + 2K_use/η = 0
        # u = 1 - sqrt(1 - 2K_use/η)
        inner = 1.0 - 2.0 * K_use / eta
        if inner < 0:
            return 0.82  # fallback — section too small
        u = 1.0 - math.sqrt(inner)          # u = λ·(xu/d)
        z_ratio = 1.0 - u / 2.0             # z/d = 1 - u/2
        return min(z_ratio, 0.95)

    if not doubly_reinforced:
        z_ratio = _lever_arm_ratio(K)
        z = z_ratio * d
        # Tension steel
        As_req = MEd_Nmm / (fyd_val * z)
        As2_req = 0.0
        # Neutral axis
        # xu = (d - z) * 2 / lambda
        xu = (d - z) * 2.0 / lam
    else:
        # Doubly reinforced — singly part carries K_prime moment
        if d2 <= 0.0:
            d2 = min(50.0, 0.1 * d)   # default cover estimate

        z_ratio = _lever_arm_ratio(K_prime)
        z = z_ratio * d

        M1_Nmm = K_prime * b * d**2 * fcd_val  # moment carried by singly part
        M2_Nmm = MEd_Nmm - M1_Nmm              # extra moment for compression steel

        # Compression steel stress: assume yielded (check strain)
        xu = xu_lim * d
        eps_cu = 0.0035
        eps_s2 = eps_cu * (xu - d2) / xu
        Es = 200_000.0  # MPa
        fs2 = min(eps_s2 * Es, fyd_val)

        As2_req = M2_Nmm / (fs2 * (d - d2))
        As_req = M1_Nmm / (fyd_val * z) + As2_req * fs2 / fyd_val
        warnings.append(
            f"doubly reinforced required: K={K:.4f} > K'={K_prime:.4f}; "
            f"As2={As2_req:.0f} mm² (compression steel at d2={d2:.0f} mm)"
        )

    # Ductility check
    xu_d = xu / d
    ductility_ok = xu_d <= xu_lim
    if not ductility_ok:
        warnings.append(
            f"ductility-check: xu/d={xu_d:.3f} > limit={xu_lim:.2f} "
            "(EN 1992-1-1 §5.5); increase section or add compression steel"
        )

    # Minimum steel check
    rho_req = As_req / (b * d)
    As_min = rho_min * b * d
    if As_req < As_min:
        warnings.append(
            f"As_req={As_req:.0f} mm² < As_min={As_min:.0f} mm² "
            "(EN 1992-1-1 §9.2.1.1); using As_min"
        )
        As_req = As_min
        rho_req = rho_min

    # Maximum steel check
    if rho_req > rho_max:
        warnings.append(
            f"ρ={rho_req:.4f} > ρ_max=0.04 (EN 1992-1-1 §9.2.1.1)"
        )

    # Verify MRd (for doubly: simplified using As_req)
    # MRd for singly part + doubly contribution already ≥ MEd by construction
    # Compute MRd from As_req for output
    if not doubly_reinforced:
        a = As_req * fyd_val / (eta * fcd_val * b)   # depth of stress block
        MRd_Nmm = As_req * fyd_val * (d - a / 2.0)
    else:
        # Singly part + compression part
        a1 = (M1_Nmm) / (eta * fcd_val * b * z) if z > 0 else 0.0
        MRd_Nmm = M1_Nmm + M2_Nmm   # by construction = MEd_Nmm
    MRd_kNm = MRd_Nmm / 1e6

    return {
        "As_req_mm2": As_req,
        "As2_req_mm2": As2_req,
        "xu_mm": xu,
        "xu_d": xu_d,
        "xu_d_limit": xu_lim,
        "ductility_ok": ductility_ok,
        "MRd_kNm": MRd_kNm,
        "K": K,
        "K_prime": K_prime,
        "doubly_reinforced": doubly_reinforced,
        "rho_req": rho_req,
        "rho_min": rho_min,
        "rho_max": rho_max,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 3. Shear design (EN 1992-1-1 §6.2)
# ---------------------------------------------------------------------------

def ec2_shear_design(
    bw: float,
    d: float,
    fck: float,
    fyk: float,
    VEd: float,
    As_l: float,
    *,
    Asw_s: float = 0.0,
    fywd: float = 0.0,
    theta_deg: float = 21.8,
    sigma_cp: float = 0.0,
    Ned: float = 0.0,
    Ac: float = 0.0,
    alpha_cc: float = EC2_ALPHA_CC,
) -> dict[str, Any]:
    """EC2 shear design for rectangular beam sections (EN 1992-1-1 §6.2).

    Computes VRd,c (no shear reinf.), VRd,s (with stirrups), VRd,max (web crushing).

    Parameters (SI: mm, MPa, kN)
    ----------
    bw       : web width (mm)
    d        : effective depth (mm)
    fck      : characteristic concrete cylinder strength (MPa)
    fyk      : characteristic yield strength of stirrups (MPa)
    VEd      : design shear force (kN)
    As_l     : area of longitudinal tension reinforcement (mm²)
    Asw_s    : Asw/s — stirrup area per unit length (mm²/mm); 0 = no stirrups
    fywd     : design yield strength of stirrups (MPa); if 0, computed as fyk/γS
    theta_deg: strut inclination angle θ (deg); 21.8° ≤ θ ≤ 45° per §6.2.3(2)
    sigma_cp : axial stress σcp = NEd/Ac (MPa, positive compression); default 0
    Ned      : design axial force (kN, positive compression); used if Ac > 0
    Ac       : cross-sectional area (mm²); used to compute σcp if Ned > 0
    alpha_cc : concrete partial factor modifier; default 1.0

    Returns
    -------
    dict with keys:
      VRd_c_kN        — design shear resistance without shear reinf. (kN)
      VRd_s_kN        — design shear resistance with stirrups (kN); 0 if Asw_s=0
      VRd_max_kN      — maximum shear resistance (web crushing limit) (kN)
      VRd_kN          — governing design resistance (kN)
      Asw_s_min       — minimum Asw/s per EN 1992-1-1 §9.2.2 (mm²/mm)
      VEd_kN          — shear demand (kN)
      adequate        — bool: VRd_kN >= VEd_kN
      CRd_c           — CRd,c = 0.18/γC
      k               — size effect factor k
      rho_l           — longitudinal reinforcement ratio ≤ 0.02
      warnings        — list[str]

    Notes
    -----
    VRd,c = [CRd,c · k · (100·ρl·fck)^(1/3) + k1·σcp] · bw · d  (§6.2.2 Eq.6.2a)
    with minimum VRd,c,min = (vmin + k1·σcp) · bw · d
      vmin = 0.035 · k^(3/2) · fck^(1/2)  (§6.2.2 Eq.6.3N)
    VRd,s = (Asw/s) · z · fywd · cot(θ)  (§6.2.3 Eq.6.8)
    VRd,max = α_cw · bw · z · ν1 · fcd / (cot(θ) + tan(θ))  (§6.2.3 Eq.6.9)
      α_cw = 1.0 (non-prestressed), ν1 = 0.6·(1 − fck/250)
    z = 0.9·d (lever arm, simplified per §6.2.3(1))
    """
    warnings: list[str] = []

    fcd_val = _fcd(fck, alpha_cc)
    if fywd <= 0.0:
        fywd = _fyd(fyk)

    # Size effect factor k (§6.2.2)
    k = min(1.0 + math.sqrt(200.0 / d), 2.0)

    # Longitudinal reinforcement ratio (§6.2.2)
    rho_l = min(As_l / (bw * d), 0.02)

    # Axial stress
    if Ac > 0 and Ned > 0:
        sigma_cp = (Ned * 1000.0) / Ac   # convert kN to N
    sigma_cp = min(sigma_cp, 0.2 * fcd_val)  # cap per §6.2.2(1)

    # CRd,c = 0.18/γC
    CRd_c = 0.18 / EC2_GAMMA_C
    k1 = 0.15  # per §6.2.2(1) recommended

    # VRd,c — Eq. 6.2a (N)
    VRd_c_term = CRd_c * k * (100.0 * rho_l * fck) ** (1.0 / 3.0) + k1 * sigma_cp
    VRd_c_N = VRd_c_term * bw * d

    # Minimum VRd,c — Eq. 6.3N
    v_min = 0.035 * k ** (3.0 / 2.0) * fck ** 0.5
    VRd_c_min_N = (v_min + k1 * sigma_cp) * bw * d

    VRd_c_N = max(VRd_c_N, VRd_c_min_N)
    VRd_c_kN = VRd_c_N / 1000.0

    # Lever arm z = 0.9d (simplified)
    z = 0.9 * d

    # Validate theta
    if theta_deg < 21.8 or theta_deg > 45.0:
        warnings.append(
            f"theta={theta_deg:.1f}° outside EN 1992-1-1 §6.2.3(2) range [21.8°, 45°]; "
            "clamping to range"
        )
        theta_deg = max(21.8, min(theta_deg, 45.0))

    theta_rad = math.radians(theta_deg)
    cot_theta = 1.0 / math.tan(theta_rad)
    tan_theta = math.tan(theta_rad)

    # VRd,max — web crushing limit — Eq. 6.9 (N)
    nu1 = 0.6 * (1.0 - fck / 250.0)  # strength reduction factor for cracked concrete
    alpha_cw = 1.0  # non-prestressed
    VRd_max_N = alpha_cw * bw * z * nu1 * fcd_val / (cot_theta + tan_theta)
    VRd_max_kN = VRd_max_N / 1000.0

    # VRd,s — Eq. 6.8 (N)
    if Asw_s > 0.0:
        VRd_s_N = Asw_s * z * fywd * cot_theta
        VRd_s_kN = VRd_s_N / 1000.0
        # Cap at VRd,max
        if VRd_s_kN > VRd_max_kN:
            warnings.append(
                f"VRd,s={VRd_s_kN:.1f} kN > VRd,max={VRd_max_kN:.1f} kN; "
                "web crushing governs — reduce spacing or increase section"
            )
            VRd_s_kN = VRd_max_kN
        VRd_kN = VRd_s_kN
    else:
        VRd_s_kN = 0.0
        VRd_kN = VRd_c_kN

    # Minimum Asw/s (EN 1992-1-1 §9.2.2 Eq. 9.4N)
    rho_w_min = 0.08 * math.sqrt(fck) / fyk
    Asw_s_min = rho_w_min * bw  # mm²/mm  (Eq. 9.4: ρw = Asw/(s·bw·sinα), α=90°)

    adequate = VRd_kN >= VEd

    if VEd > VRd_c_kN and Asw_s <= 0.0:
        warnings.append(
            f"VEd={VEd:.1f} kN > VRd,c={VRd_c_kN:.1f} kN: shear reinforcement required"
        )

    if VEd > VRd_max_kN:
        warnings.append(
            f"VEd={VEd:.1f} kN > VRd,max={VRd_max_kN:.1f} kN: "
            "section too small for shear — increase bw or d"
        )

    return {
        "VRd_c_kN": VRd_c_kN,
        "VRd_s_kN": VRd_s_kN,
        "VRd_max_kN": VRd_max_kN,
        "VRd_kN": VRd_kN,
        "Asw_s_min": Asw_s_min,
        "VEd_kN": VEd,
        "adequate": adequate,
        "CRd_c": CRd_c,
        "k": k,
        "rho_l": rho_l,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 4. Punching shear (EN 1992-1-1 §6.4)
# ---------------------------------------------------------------------------

def ec2_punching_shear(
    bw: float,
    bh: float,
    d: float,
    fck: float,
    fyk: float,
    VEd: float,
    As_avg: float,
    *,
    beta: float = 1.0,
    sigma_cp: float = 0.0,
    alpha_cc: float = EC2_ALPHA_CC,
) -> dict[str, Any]:
    """EC2 punching shear at critical perimeter u1 = 2d from column face.

    Parameters (SI: mm, MPa, kN)
    ----------
    bw      : column width in x-direction (mm)
    bh      : column width in y-direction (mm)
    d       : average effective depth of slab (mm)
    fck     : characteristic concrete cylinder strength (MPa)
    fyk     : characteristic yield strength (MPa)
    VEd     : design punching shear force (kN)
    As_avg  : average longitudinal reinforcement ratio ρ_avg = sqrt(ρlx·ρly);
              OR pass the total As (mm²) per unit area as mm²/mm² (dimensionless)
    beta    : eccentricity factor β (default 1.0 for symmetric loading; 1.15
              for edge columns, 1.5 for corner columns per §6.4.3)
    sigma_cp: average axial stress σcp = (σcx + σcy)/2 (MPa, compression +)
    alpha_cc: default 1.0

    Returns
    -------
    dict with keys:
      u1_mm           — critical perimeter (mm) = 2π·2d + 4·(bw+bh)? See formula.
                        u1 = 2·(bw + bh) + 2π·2d  for interior column
      A_crit_mm2      — area within critical perimeter
      vRd_c_MPa       — design punching shear stress (MPa)
      VRd_c_kN        — design punching shear resistance (kN)
      VEd_eff_kN      — effective punching shear (β·VEd) (kN)
      adequate        — bool: VRd_c_kN >= VEd_eff_kN
      warnings        — list[str]

    Notes
    -----
    Critical perimeter u1 = perimeter of rectangle 2d from column face (§6.4.2):
      u1 = 2·(bw + bh) + 4·π·d   for interior square/rectangular column
    Shear stress: vEd = β·VEd / (u1·d)
    VRd,c = vRd,c · u1 · d  where
      vRd,c = max(CRd,c·k·(100·ρl·fck)^(1/3) + k1·σcp, vmin + k1·σcp)
    ρl = min(sqrt(ρlx·ρly), 0.02)  (here As_avg is used as ρl directly)
    """
    warnings: list[str] = []

    _fcd(fck, alpha_cc)  # validate call (unused for punching formula itself)

    # Critical perimeter u1 — rectangular column interior (§6.4.2 Fig. 6.13)
    # u1 = 2*(bw + bh) + 2*pi*(2d)   (rounded corners at 2d radius)
    u1 = 2.0 * (bw + bh) + 2.0 * math.pi * 2.0 * d

    # Size effect k
    k = min(1.0 + math.sqrt(200.0 / d), 2.0)

    # Reinforcement ratio — cap at 0.02
    rho_l = min(As_avg, 0.02)
    if rho_l <= 0:
        rho_l = 0.001
        warnings.append("As_avg (ρl) ≤ 0; defaulted to 0.001 — check input")

    CRd_c = 0.18 / EC2_GAMMA_C
    k1 = 0.10  # k1 = 0.10 for punching per §6.4.4(1)
    sigma_cp = min(sigma_cp, 0.2 * _fcd(fck, alpha_cc))

    vRd_c = CRd_c * k * (100.0 * rho_l * fck) ** (1.0 / 3.0) + k1 * sigma_cp
    v_min = 0.035 * k ** (3.0 / 2.0) * fck ** 0.5
    vRd_c = max(vRd_c, v_min + k1 * sigma_cp)

    VRd_c_N = vRd_c * u1 * d
    VRd_c_kN = VRd_c_N / 1000.0

    VEd_eff_kN = beta * VEd
    vEd_MPa = VEd_eff_kN * 1000.0 / (u1 * d)

    adequate = VRd_c_kN >= VEd_eff_kN

    if not adequate:
        warnings.append(
            f"punching shear inadequate: VEd,eff={VEd_eff_kN:.1f} kN > "
            f"VRd,c={VRd_c_kN:.1f} kN; provide punching shear reinforcement (§6.4.5)"
        )

    return {
        "u1_mm": u1,
        "vRd_c_MPa": vRd_c,
        "vEd_MPa": vEd_MPa,
        "VRd_c_kN": VRd_c_kN,
        "VEd_eff_kN": VEd_eff_kN,
        "adequate": adequate,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# 5. LLM tool registrations (following concrete/tools.py pattern)
# ---------------------------------------------------------------------------

def _register_ec2_tools() -> None:
    """Register EC2 tools with the Kerf tool registry.

    Called at import time if the registry is available; silently skips in
    standalone/test usage where kerf_chat is not installed.
    """
    try:
        import json
        from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
        from kerf_core.utils.context import ProjectCtx  # noqa: F401
    except ImportError:
        return  # standalone mode — skip registration

    # -- ec2_design_strengths --------------------------------------------------

    _spec_strengths = ToolSpec(
        name="ec2_design_strengths",
        description=(
            "EN 1992-1-1 (Eurocode 2) design strengths for concrete and reinforcement.\n"
            "\n"
            "Returns fcd (design concrete strength), fyd (design steel strength), "
            "rectangular stress-block factors λ and η, and partial factors γC / γS.\n"
            "\n"
            "Units: MPa (N/mm²).  Reference: EN 1992-1-1 §3.1.6, §3.2.7.\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "fck": {"type": "number", "description": "Characteristic cylinder strength of concrete (MPa)."},
                "fyk": {"type": "number", "description": "Characteristic yield strength of reinforcement (MPa)."},
                "alpha_cc": {"type": "number", "description": "Long-term strength reduction factor (default 1.0; some NADs use 0.85)."},
            },
            "required": ["fck", "fyk"],
        },
    )

    @register(_spec_strengths, write=False)
    async def _run_ec2_strengths(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        for field in ("fck", "fyk"):
            if a.get(field) is None:
                return json.dumps({"ok": False, "reason": f"{field} is required"})
        kwargs: dict = {}
        if "alpha_cc" in a:
            kwargs["alpha_cc"] = a["alpha_cc"]
        return ok_payload(ec2_design_strengths(a["fck"], a["fyk"], **kwargs))

    # -- ec2_flexure -----------------------------------------------------------

    _spec_flexure = ToolSpec(
        name="ec2_flexure",
        description=(
            "EN 1992-1-1 §6.1 required tension steel for a rectangular beam.\n"
            "\n"
            "Computes K, K', lever arm z, required As (and As2 if doubly reinforced). "
            "Enforces EC2 ductility limit xu/d ≤ 0.45 (fck≤50) or 0.35 (fck>50), "
            "minimum and maximum steel ratios per §9.2.1.1.\n"
            "\n"
            "Units: dimensions in mm, stresses in MPa, moment in kN·m, areas in mm².\n"
            "Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "b": {"type": "number", "description": "Beam width (mm)."},
                "d": {"type": "number", "description": "Effective depth to tension steel (mm)."},
                "fck": {"type": "number", "description": "Characteristic concrete cylinder strength (MPa)."},
                "fyk": {"type": "number", "description": "Characteristic yield strength of steel (MPa)."},
                "MEd": {"type": "number", "description": "Design bending moment (kN·m)."},
                "alpha_cc": {"type": "number", "description": "Long-term reduction factor (default 1.0)."},
                "d2": {"type": "number", "description": "Depth to compression steel (mm); used only if doubly reinforced needed."},
            },
            "required": ["b", "d", "fck", "fyk", "MEd"],
        },
    )

    @register(_spec_flexure, write=False)
    async def _run_ec2_flexure(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        for field in ("b", "d", "fck", "fyk", "MEd"):
            if a.get(field) is None:
                return json.dumps({"ok": False, "reason": f"{field} is required"})
        kwargs: dict = {}
        for k in ("alpha_cc", "d2"):
            if k in a:
                kwargs[k] = a[k]
        return ok_payload(ec2_flexure(a["b"], a["d"], a["fck"], a["fyk"], a["MEd"], **kwargs))

    # -- ec2_shear_design ------------------------------------------------------

    _spec_shear = ToolSpec(
        name="ec2_shear_design",
        description=(
            "EN 1992-1-1 §6.2 shear design for rectangular beams.\n"
            "\n"
            "Returns VRd,c (no shear reinf.), VRd,s (with stirrups Asw/s provided), "
            "VRd,max (web crushing), minimum Asw/s, and adequacy flag.  "
            "θ (strut angle) between 21.8° and 45°.\n"
            "\n"
            "Units: mm, MPa, kN.  Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bw": {"type": "number", "description": "Web width (mm)."},
                "d": {"type": "number", "description": "Effective depth (mm)."},
                "fck": {"type": "number", "description": "Characteristic concrete strength (MPa)."},
                "fyk": {"type": "number", "description": "Characteristic yield strength of stirrups (MPa)."},
                "VEd": {"type": "number", "description": "Design shear force (kN)."},
                "As_l": {"type": "number", "description": "Area of longitudinal tension reinforcement (mm²)."},
                "Asw_s": {"type": "number", "description": "Asw/s — stirrup area per unit length (mm²/mm); 0 = no stirrups."},
                "fywd": {"type": "number", "description": "Design yield strength of stirrups (MPa); 0 = compute from fyk/γS."},
                "theta_deg": {"type": "number", "description": "Strut angle θ in degrees [21.8, 45] (default 21.8° = cot θ = 2.5)."},
                "sigma_cp": {"type": "number", "description": "Axial stress NEd/Ac (MPa, + compression); default 0."},
            },
            "required": ["bw", "d", "fck", "fyk", "VEd", "As_l"],
        },
    )

    @register(_spec_shear, write=False)
    async def _run_ec2_shear(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        for field in ("bw", "d", "fck", "fyk", "VEd", "As_l"):
            if a.get(field) is None:
                return json.dumps({"ok": False, "reason": f"{field} is required"})
        kwargs: dict = {}
        for k in ("Asw_s", "fywd", "theta_deg", "sigma_cp", "Ned", "Ac", "alpha_cc"):
            if k in a:
                kwargs[k] = a[k]
        return ok_payload(ec2_shear_design(
            a["bw"], a["d"], a["fck"], a["fyk"], a["VEd"], a["As_l"], **kwargs
        ))

    # -- ec2_punching_shear ----------------------------------------------------

    _spec_punching = ToolSpec(
        name="ec2_punching_shear",
        description=(
            "EN 1992-1-1 §6.4 punching shear at critical perimeter u1 = 2d from "
            "rectangular interior column face.\n"
            "\n"
            "Returns vRd,c (MPa), VRd,c (kN), effective punching shear β·VEd, "
            "critical perimeter u1, and adequacy flag.\n"
            "\n"
            "Units: mm, MPa, kN.  Errors: {ok:false, reason}.  Never raises."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bw": {"type": "number", "description": "Column width in x-direction (mm)."},
                "bh": {"type": "number", "description": "Column width in y-direction (mm)."},
                "d": {"type": "number", "description": "Average effective depth of slab (mm)."},
                "fck": {"type": "number", "description": "Characteristic concrete strength (MPa)."},
                "fyk": {"type": "number", "description": "Characteristic yield strength (MPa)."},
                "VEd": {"type": "number", "description": "Design punching shear force (kN)."},
                "As_avg": {"type": "number", "description": "ρl = √(ρlx·ρly) — average reinforcement ratio (dimensionless, e.g. 0.005)."},
                "beta": {"type": "number", "description": "Eccentricity factor β: 1.0 interior, 1.15 edge, 1.5 corner (default 1.0)."},
                "sigma_cp": {"type": "number", "description": "Average axial stress (MPa, + compression); default 0."},
            },
            "required": ["bw", "bh", "d", "fck", "fyk", "VEd", "As_avg"],
        },
    )

    @register(_spec_punching, write=False)
    async def _run_ec2_punching(ctx: ProjectCtx, args: bytes) -> str:
        try:
            a = json.loads(args)
        except Exception as exc:
            return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")
        for field in ("bw", "bh", "d", "fck", "fyk", "VEd", "As_avg"):
            if a.get(field) is None:
                return json.dumps({"ok": False, "reason": f"{field} is required"})
        kwargs: dict = {}
        for k in ("beta", "sigma_cp", "alpha_cc"):
            if k in a:
                kwargs[k] = a[k]
        return ok_payload(ec2_punching_shear(
            a["bw"], a["bh"], a["d"], a["fck"], a["fyk"], a["VEd"], a["As_avg"], **kwargs
        ))


# Register at import time (safe — silently skips if registry not present)
_register_ec2_tools()
