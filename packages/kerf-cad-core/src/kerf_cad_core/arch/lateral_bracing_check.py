"""
kerf_cad_core.arch.lateral_bracing_check — Lateral-torsional buckling (LTB) check.

Implements AISC 360-22 §F2: Flexural Strength of Compact Doubly Symmetric
I-Shaped Members Bent About Their Major Axis.

Equations implemented
---------------------
F2-1  Mn = Mp = Fy · Zx                              (plastic moment)
F2-2  Mn = Cb · [Mp − (Mp − 0.7·Fy·Sx) · (Lb−Lp)/(Lr−Lp)] ≤ Mp   (inelastic LTB)
F2-3  Mn = Fcr · Sx ≤ Mp                             (elastic LTB)
F2-4  Fcr = Cb·π²·E / (Lb/rts)² · √(1 + 0.078·J·c/(Sx·ho)·(Lb/rts)²)
F2-5  Lp = 1.76 · ry · √(E/Fy)
F2-6  Lr = 1.95·rts·(E/(0.7·Fy))·√(J·c/(Sx·ho) + √((J·c/(Sx·ho))²+6.76·(0.7·Fy/E)²))
F2-7  rts² = √(Iy·Cw) / Sx   (alternative rts; user may supply rts directly instead)
F2-8a c = 1.0 (doubly symmetric I-shapes)

Scope / honest caveats
----------------------
* Doubly symmetric compact I-shaped members only (AISC 360-22 §F2).
* Non-compact / slender flanges or webs: not checked here (see §F3/F4/F5).
* Channels, tees, built-up, and other unsymmetric shapes: out of scope.
* phi_b = 0.90 (LRFD); ΩΩ_b = 1.67 (ASD) not implemented.
* Cb (moment gradient factor) must be supplied by the caller; the code does
  NOT compute Cb from moment diagrams.  Default Cb = 1.0 is conservative.
* This check produces Mn (nominal flexural strength).  Demand/capacity ratio
  and connection checks are not included.

All dimensions in **millimetres** and **MPa**; results in **kN·m**.

References
----------
AISC 360-22, "Specification for Structural Steel Buildings", Chapter F, §F2.
AISC Steel Construction Manual, 15th ed., Table 3-2 (W-shape LTB limits).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

__all__ = [
    "WSectionSpec",
    "LateralBracingReport",
    "check_lateral_bracing",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class WSectionSpec:
    """
    Properties of a doubly symmetric compact I-shaped (W-shape) section.

    Parameters
    ----------
    section_label : str
        Human-readable label, e.g. ``"W14x90"`` or ``"W360x134"``.
    S_x_mm3 : float
        Elastic section modulus about the strong axis (mm³).
    Z_x_mm3 : float
        Plastic section modulus about the strong axis (mm³).
    r_y_mm : float
        Radius of gyration about the weak axis (mm).
    J_mm4 : float
        Saint-Venant torsional constant (mm⁴).
    h_o_mm : float
        Distance between centroid of flanges (≈ d − t_f) in mm.
    Fy_MPa : float
        Specified minimum yield stress (MPa).  Default 345 MPa (A992/A572 Gr 50).
    E_MPa : float
        Elastic modulus (MPa).  Default 200 000 MPa (200 GPa).
    ry_TS_mm : float or None
        Effective radius of gyration rts used in the Lr/Fcr formulae (AISC
        F2-6/F2-4).  If ``None``, the caller must have the rts value computed
        externally OR rely on an approximation.  Because rts = √(√(Iy·Cw)/Sx)
        requires I_y and C_w which are not always known at call-time, the field
        is optional.  When ``None``, the code falls back to ``r_y_mm`` as a
        conservative approximation (rts ≥ ry for standard W-shapes, so using
        ry gives a lower Lr — conservative for Lr, non-conservative for Fcr).
        **Pass rts explicitly whenever possible.**
    """
    section_label: str
    S_x_mm3: float
    Z_x_mm3: float
    r_y_mm: float
    J_mm4: float
    h_o_mm: float
    Fy_MPa: float = field(default=345.0)
    E_MPa: float = field(default=200_000.0)
    ry_TS_mm: Optional[float] = field(default=None)


@dataclass
class LateralBracingReport:
    """
    Output of ``check_lateral_bracing``.

    Parameters
    ----------
    L_p_mm : float
        Limiting unbraced length for plastic moment (Eq. F2-5), mm.
    L_r_mm : float
        Limiting unbraced length for inelastic LTB / elastic LTB boundary
        (Eq. F2-6), mm.
    Mp_kNm : float
        Plastic moment capacity Mp = Fy·Zx (kN·m).
    Mr_kNm : float
        Moment at the inelastic/elastic LTB boundary: Mr = 0.7·Fy·Sx (kN·m).
    Mn_kNm : float
        Nominal flexural strength Mn for the supplied L_b (kN·m).
    phi_Mn_kNm : float
        Design flexural strength φ_b·Mn = 0.90·Mn (LRFD, kN·m).
    governing_mode : str
        One of ``"yielding"``, ``"inelastic_LTB"``, or ``"elastic_LTB"``.
    Lb_to_Lp_ratio : float
        L_b / L_p ratio (useful for quick checks; < 1 → fully braced).
    honest_caveat : str
        Code-compliance caveat referencing scope, equations, and limitations.
    """
    L_p_mm: float
    L_r_mm: float
    Mp_kNm: float
    Mr_kNm: float
    Mn_kNm: float
    phi_Mn_kNm: float
    governing_mode: str
    Lb_to_Lp_ratio: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def check_lateral_bracing(
    section: WSectionSpec,
    L_b_mm: float,
    Cb: float = 1.0,
) -> LateralBracingReport:
    """
    Compute the nominal flexural design moment capacity Mn for a compact
    doubly symmetric I-shaped member per AISC 360-22 §F2 (LRFD).

    Parameters
    ----------
    section : WSectionSpec
        Section properties (see :class:`WSectionSpec`).
    L_b_mm : float
        Unbraced length of the compression flange (mm).  Must be > 0.
    Cb : float
        Moment gradient amplification factor (AISC F1-1).  Default 1.0
        (conservative — uniform moment).  Must be ≥ 1.0.

    Returns
    -------
    LateralBracingReport

    Raises
    ------
    ValueError
        If any input is physically implausible (non-positive section property,
        L_b ≤ 0, or Cb < 1.0).

    Notes
    -----
    The Cb factor amplifies Mn in Eqs. F2-2 and F2-3 but is always capped at
    Mp, so it never pushes the section above plastic moment.

    rts fallback
    ~~~~~~~~~~~~
    When ``section.ry_TS_mm`` is ``None``, the function substitutes ``r_y_mm``
    for ``rts``.  For standard compact W-shapes rts > ry (typically 5–15 %
    larger), so this gives a slightly conservative Lr and Fcr.  The caveat
    string flags when the fallback is used.
    """
    # ------------------------------------------------------------------
    # Input validation
    # ------------------------------------------------------------------
    if section.S_x_mm3 <= 0:
        raise ValueError(f"S_x_mm3 must be > 0, got {section.S_x_mm3}")
    if section.Z_x_mm3 <= 0:
        raise ValueError(f"Z_x_mm3 must be > 0, got {section.Z_x_mm3}")
    if section.r_y_mm <= 0:
        raise ValueError(f"r_y_mm must be > 0, got {section.r_y_mm}")
    if section.J_mm4 <= 0:
        raise ValueError(f"J_mm4 must be > 0, got {section.J_mm4}")
    if section.h_o_mm <= 0:
        raise ValueError(f"h_o_mm must be > 0, got {section.h_o_mm}")
    if section.Fy_MPa <= 0:
        raise ValueError(f"Fy_MPa must be > 0, got {section.Fy_MPa}")
    if section.E_MPa <= 0:
        raise ValueError(f"E_MPa must be > 0, got {section.E_MPa}")
    if section.ry_TS_mm is not None and section.ry_TS_mm <= 0:
        raise ValueError(f"ry_TS_mm must be > 0 when provided, got {section.ry_TS_mm}")
    if L_b_mm <= 0:
        raise ValueError(f"L_b_mm must be > 0, got {L_b_mm}")
    if Cb < 1.0:
        raise ValueError(f"Cb must be >= 1.0 (AISC §F1-1 note), got {Cb}")

    # ------------------------------------------------------------------
    # Convenience aliases
    # ------------------------------------------------------------------
    E = section.E_MPa
    Fy = section.Fy_MPa
    Sx = section.S_x_mm3
    Zx = section.Z_x_mm3
    ry = section.r_y_mm
    J = section.J_mm4
    ho = section.h_o_mm

    # rts: use supplied value or fall back to ry (conservative)
    rts_fallback = section.ry_TS_mm is None
    rts = section.ry_TS_mm if section.ry_TS_mm is not None else ry

    # c = 1.0 for doubly symmetric I-shapes (AISC F2-8a)
    c = 1.0

    # ------------------------------------------------------------------
    # Limiting unbraced lengths
    # ------------------------------------------------------------------
    # AISC Eq. F2-5
    L_p = 1.76 * ry * math.sqrt(E / Fy)

    # AISC Eq. F2-6
    JcSxho = J * c / (Sx * ho)
    inner_sqrt = math.sqrt(JcSxho**2 + 6.76 * (0.7 * Fy / E) ** 2)
    L_r = 1.95 * rts * (E / (0.7 * Fy)) * math.sqrt(JcSxho + inner_sqrt)

    # ------------------------------------------------------------------
    # Plastic moment (AISC Eq. F2-1)
    # ------------------------------------------------------------------
    Mp_Nmm = Fy * Zx          # N·mm
    Mp_kNm = Mp_Nmm / 1.0e6   # kN·m

    # Moment at inelastic/elastic boundary
    Mr_Nmm = 0.7 * Fy * Sx
    Mr_kNm = Mr_Nmm / 1.0e6

    # ------------------------------------------------------------------
    # Governing mode and Mn
    # ------------------------------------------------------------------
    if L_b_mm <= L_p:
        # Zone 1 — plastic yielding governs (Eq. F2-1)
        governing_mode = "yielding"
        Mn_kNm = Mp_kNm

    elif L_b_mm <= L_r:
        # Zone 2 — inelastic LTB (Eq. F2-2)
        governing_mode = "inelastic_LTB"
        ramp_factor = (L_b_mm - L_p) / (L_r - L_p)
        Mn_raw_kNm = Cb * (Mp_kNm - (Mp_kNm - Mr_kNm) * ramp_factor)
        Mn_kNm = min(Mn_raw_kNm, Mp_kNm)

    else:
        # Zone 3 — elastic LTB (Eqs. F2-3, F2-4)
        governing_mode = "elastic_LTB"
        LbOrts = L_b_mm / rts
        Fcr = (
            Cb * math.pi**2 * E / LbOrts**2
            * math.sqrt(1.0 + 0.078 * J * c / (Sx * ho) * LbOrts**2)
        )  # MPa
        Mn_raw_kNm = Fcr * Sx / 1.0e6   # kN·m
        Mn_kNm = min(Mn_raw_kNm, Mp_kNm)

    # ------------------------------------------------------------------
    # LRFD design strength
    # ------------------------------------------------------------------
    phi_b = 0.90
    phi_Mn_kNm = phi_b * Mn_kNm

    # ------------------------------------------------------------------
    # Honest caveat
    # ------------------------------------------------------------------
    rts_note = (
        "ry_TS_mm not supplied — ry used as a conservative rts approximation "
        "(true rts ≥ ry gives a slightly larger Lr; Fcr/Lr may be under-estimated). "
        if rts_fallback
        else f"rts = {rts:.1f} mm supplied by caller. "
    )
    caveat = (
        f"AISC 360-22 §F2 LRFD; doubly symmetric compact I-shaped members bent about the "
        f"major axis only. "
        f"Lp = {L_p:.0f} mm (Eq. F2-5); Lr = {L_r:.0f} mm (Eq. F2-6); "
        f"Mp = {Mp_kNm:.1f} kN·m; Mr = {Mr_kNm:.1f} kN·m; "
        f"Lb = {L_b_mm:.0f} mm; Cb = {Cb:.3f}; "
        f"governing mode = {governing_mode}; Mn = {Mn_kNm:.2f} kN·m; "
        f"φ_b·Mn = {phi_Mn_kNm:.2f} kN·m. "
        f"{rts_note}"
        f"SCOPE: compact sections only (bf/(2·tf) and h/tw within compact limits per §B4); "
        f"channels, tees, and built-up sections are out of scope. "
        f"Cb is NOT computed by this function — caller must supply from AISC §C-F1-3 "
        f"(e.g. Cb=1.0 for uniform moment; Cb=1.14 for UDL simply-supported). "
        f"Demand/capacity ratio and connection checks not included. "
        f"Ref: AISC 360-22 §F2 (Eqs. F2-1..F2-8) + AISC Manual 15e Table 3-2."
    )

    return LateralBracingReport(
        L_p_mm=round(L_p, 3),
        L_r_mm=round(L_r, 3),
        Mp_kNm=round(Mp_kNm, 4),
        Mr_kNm=round(Mr_kNm, 4),
        Mn_kNm=round(Mn_kNm, 4),
        phi_Mn_kNm=round(phi_Mn_kNm, 4),
        governing_mode=governing_mode,
        Lb_to_Lp_ratio=round(L_b_mm / L_p, 6),
        honest_caveat=caveat,
    )
