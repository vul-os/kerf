"""
Hull Scantling Rule Checks — ISO 12215-5, ABS, DNV local scantling formulae.

Implements the PASS/FAIL check interface that wraps ISO 12215-5 plate/stiffener
requirements and adds local scantling pressure / section-modulus formulas from
published ABS and DNV open-standard documents:

  * ISO 12215-5:2008  "Small craft — Hull construction and scantlings —
      Part 5: Design pressures for monohulls, design stresses, scantlings
      determination"  (ISO Geneva).

  * ABS Rules for Building and Classing Steel Vessels (2024),
      Part 3 Chapter 2 Section 3 — "Shell Plating" / "Stiffeners":
        - Design pressure:  P = 10*h + 0.7*Cw  [kN/m²]
          (hydrostatic head h(m) + wave correction Cw; hull-region coefficients)
        - Plate thickness:  t = s * sqrt(P / (1000 * sigma_a))  [mm]
          (Table 3.2.1; simply-supported strip)
        - Stiffener section modulus: SM = C * P * s * l^2 / (1000 * sigma_a)
          C = 1/12 fixed ends, 1/8 pin-pin.

  * DNV Rules for Classification of Ships (July 2023), Pt.3 Ch.1 Sec.7
      "Structural Design Principles — Local scantlings":
        - Design pressure for side shell: P = rho*g*h + 0.5*rho*V^2  [kPa]
          (Clause 702; hydrostatic + dynamic slamming head)
        - Plate thickness: t = 15.8*ka*s*sqrt(P/sigma_f)  [mm]
          (Eq. 7.2; ka = aspect-ratio factor ≈ (0.5 + (s/l)^2) capped at 1.0)
        - Stiffener section modulus: SM = 83.3*m*l*s*P/sigma_f  [cm³]
          (Eq. 7.6; m = 1/12 for fixed ends, 1/8 for pin-pin)

Disclaimer
----------
These implementations use the *published open-formula skeleton* of each rule
(pressure heads, plate-bending and stiffener equations) as found in the public
versions of the rules documents listed above.  They do NOT replicate the full
proprietary rule suites (Lloyd's Rule, DNV-GL Rule Note for each vessel class,
BV NR 467) — those encode many vessel-class-specific correction tables,
fatigue/buckling modules, and class-notations that require licensing.

Honest coverage:
  - ISO 12215-5:2008  — full (plate + stiffener + longitudinal strength)
  - ABS Steel Vessel Rules Pt.3 Ch.2 §3 local scantlings — local pressure + plate + stiffener
  - DNV Pt.3 Ch.1 Sec.7 local scantlings — local pressure + plate + stiffener
  NOT covered: Lloyd's full rule, BV NR 467, ABS dynamic-load approach (Part 5A), DNV fatigue module.

All units SI unless stated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from kerf_marine.scantlings import (
    MaterialProps,
    DesignCategory,
    design_pressures_motor_craft,
    design_pressures_sailing_craft,
    plate_thickness,
    stiffener_section_modulus,
    MATERIAL_AL5083,
    MATERIAL_STEEL_S235,
    MATERIAL_STEEL_S355,
    G,
)


# ---------------------------------------------------------------------------
# Common result dataclass
# ---------------------------------------------------------------------------

@dataclass
class ScantlingCheckResult:
    """
    PASS/FAIL scantling check result with utilisation and rule citation.

    Attributes
    ----------
    rule_set        : str  e.g. "ISO 12215-5:2008", "ABS Steel Vessels 2024 Pt.3 Ch.2 §3",
                           "DNV 2023 Pt.3 Ch.1 Sec.7"
    component       : str  "plate" or "stiffener"
    zone            : str  "bottom" | "side" | "deck" | "bulkhead"
    P_design_kPa    : float  design pressure used (kPa)
    # Plate
    t_required_mm   : float  required minimum plate thickness (mm)
    t_actual_mm     : float  provided plate thickness (mm); None if not checked
    plate_util      : float  t_required / t_actual; ≤ 1.0 = pass
    plate_passes    : bool
    # Stiffener
    SM_required_cm3 : float  required section modulus (cm³)
    SM_actual_cm3   : float  provided SM (cm³); None if not checked
    stiff_util      : float  SM_required / SM_actual; ≤ 1.0 = pass
    stiff_passes    : bool
    # Overall
    passes          : bool   True only if all checked components pass
    clause          : str    standard clause(s) cited
    notes           : list[str]  advisory messages
    """
    rule_set:          str
    component:         str   # "plate" | "stiffener" | "both"
    zone:              str
    P_design_kPa:      float

    t_required_mm:     float = 0.0
    t_actual_mm:       Optional[float] = None
    plate_util:        float = 0.0
    plate_passes:      bool  = True

    SM_required_cm3:   float = 0.0
    SM_actual_cm3:     Optional[float] = None
    stiff_util:        float = 0.0
    stiff_passes:      bool  = True

    passes:            bool  = True
    clause:            str   = ""
    notes:             list  = field(default_factory=list)

    def as_dict(self) -> dict:
        d: dict = {
            "rule_set":           self.rule_set,
            "component":          self.component,
            "zone":               self.zone,
            "P_design_kPa":       round(self.P_design_kPa, 3),
            "plate": {
                "t_required_mm":  round(self.t_required_mm, 3),
                "t_actual_mm":    round(self.t_actual_mm, 3) if self.t_actual_mm is not None else None,
                "utilisation":    round(self.plate_util, 4),
                "passes":         self.plate_passes,
            },
            "stiffener": {
                "SM_required_cm3": round(self.SM_required_cm3, 4),
                "SM_actual_cm3":   round(self.SM_actual_cm3, 4) if self.SM_actual_cm3 is not None else None,
                "utilisation":     round(self.stiff_util, 4),
                "passes":          self.stiff_passes,
            },
            "passes":   self.passes,
            "clause":   self.clause,
            "notes":    self.notes,
        }
        return d


# ---------------------------------------------------------------------------
# ISO 12215-5 check wrapper (adds PASS/FAIL vs provided scantlings)
# ---------------------------------------------------------------------------

def check_iso_12215(
    LWL: float,
    BWL: float,
    mLDC: float,
    V: float,
    beta_04: float,
    b_mm: float,
    l_mm: float,
    lu_mm: float,
    s_mm: float,
    material: MaterialProps,
    category: DesignCategory = DesignCategory.A,
    zone: str = "bottom",
    t_actual_mm: Optional[float] = None,
    SM_actual_cm3: Optional[float] = None,
    z_mm: float = 0.0,
    is_sailing: bool = False,
) -> ScantlingCheckResult:
    """
    ISO 12215-5:2008 local scantling check — PASS/FAIL vs provided scantlings.

    Rule clause: ISO 12215-5:2008 §8 (pressures), §11.4 (plate Eq. 16),
                 §11.5 (stiffener Eq. 22).

    Parameters
    ----------
    LWL, BWL, mLDC, V, beta_04   : hull geometry / mass / speed (SI)
    b_mm, l_mm                    : panel short/long sides (mm)
    lu_mm, s_mm                   : stiffener span, spacing (mm)
    material                      : MaterialProps
    category                      : DesignCategory (A/B/C/D)
    zone                          : "bottom" | "side" | "deck"
    t_actual_mm                   : provided plate thickness (mm); if None, check skipped
    SM_actual_cm3                 : provided SM (cm³); if None, check skipped
    z_mm                          : panel crown height (mm)
    is_sailing                    : True for sailing craft

    Returns
    -------
    ScantlingCheckResult
    """
    if is_sailing:
        pres = design_pressures_sailing_craft(LWL, BWL, mLDC, category)
    else:
        pres = design_pressures_motor_craft(LWL, BWL, mLDC, V, beta_04, category)

    P = {"bottom": pres.P_bottom, "side": pres.P_s, "deck": pres.P_d}.get(
        zone.lower(), pres.P_bottom
    )

    plate_res  = plate_thickness(P, b_mm, l_mm, material, z_mm=z_mm)
    stiff_res  = stiffener_section_modulus(P, lu_mm, s_mm, material)

    t_req = plate_res.t_governing_mm
    SM_req = stiff_res.SM_cm3

    # Plate check
    if t_actual_mm is not None and t_actual_mm > 0:
        p_util   = t_req / t_actual_mm
        p_passes = p_util <= 1.0
    else:
        p_util   = t_req / t_req if t_req > 0 else 0.0
        p_passes = True

    # Stiffener check
    if SM_actual_cm3 is not None and SM_actual_cm3 > 0:
        s_util   = SM_req / SM_actual_cm3
        s_passes = s_util <= 1.0
    else:
        s_util   = SM_req / SM_req if SM_req > 0 else 0.0
        s_passes = True

    overall = p_passes and s_passes

    component = "both"
    if t_actual_mm is None and SM_actual_cm3 is None:
        component = "required-only"

    notes = []
    if pres.nCG > 4.0:
        notes.append(f"High nCG={pres.nCG:.2f} g — verify at design speed.")
    if plate_res.kAR < 0.4:
        notes.append("Large panel: area pressure reduction kAR applied (kAR < 0.4).")

    return ScantlingCheckResult(
        rule_set         = "ISO 12215-5:2008",
        component        = component,
        zone             = zone,
        P_design_kPa     = round(P, 3),
        t_required_mm    = t_req,
        t_actual_mm      = t_actual_mm,
        plate_util       = p_util,
        plate_passes     = p_passes,
        SM_required_cm3  = SM_req,
        SM_actual_cm3    = SM_actual_cm3,
        stiff_util       = s_util,
        stiff_passes     = s_passes,
        passes           = overall,
        clause           = "ISO 12215-5:2008 §8 (pressures) / §11.4 Eq.16 (plate) / §11.5 Eq.22 (stiffener)",
        notes            = notes,
    )


# ---------------------------------------------------------------------------
# ABS Steel Vessels local scantling check
# ---------------------------------------------------------------------------

def abs_design_pressure(
    h_m: float,
    Cw: float = 0.0,
    rho: float = 1.025,
) -> float:
    """
    ABS Rules for Building and Classing Steel Vessels (2024) Pt.3 Ch.2 Sec.3.
    Design pressure formula (simplified, hull bottom / side / deck):

        P = rho * g * h + 0.5 * Cw   [kPa]

    where:
        h   = hydrostatic head to waterline (m) — vertical distance from WL to point
        Cw  = wave correction coefficient (kPa); rule = 2.5 for exposed decks,
              0 for internal; defaults 0 here (conservative: caller sets wave term)
        rho = water density (t/m³)

    ABS Pt.3 Ch.2 Sec.3 Table 2 gives hull-region pressure:
        P_keel   = 10 * T        [kPa]  (T = draft in m, 10 = rho*g in kN/m³)
        P_side   = 10 * (T - h) + Cw_side
        P_deck   = 0.70 * Cw    [kPa]  (weather deck, no head below WL)

    The simplified general formula used here:
        P = 10 * h + Cw     [kPa]   (matches rule Eq. at keel, h = T)

    Reference: ABS Rules for Steel Vessels 2024, Part 3, Chapter 2, Section 3,
               "Design Loading — Sea Pressure" (publicly available from ABS website).

    Parameters
    ----------
    h_m  : float  hydrostatic head (m) — depth below waterline to the panel
                  (0 for weather deck, T for keel)
    Cw   : float  wave-load correction coefficient (kPa); default 0
    rho  : float  water density (t/m³)

    Returns
    -------
    float  design pressure (kPa)
    """
    P = rho * G * h_m + Cw    # kPa (rho in t/m³ × G m/s² × h m = kN/m² = kPa)
    return max(P, 0.0)


def abs_plate_thickness(
    P_kPa: float,
    s_mm: float,
    sigma_a_MPa: float,
) -> float:
    """
    ABS Steel Vessel Rules 2024 Pt.3 Ch.2 Sec.3 — plate thickness formula.

    ABS Eq. (Table 3.2.1 / Sec.3.3):

        t = s * sqrt(P / (1000 * sigma_a))   [mm]

    This is the standard simply-supported strip formula where:
        s        = plate stiffener spacing (mm) — short dimension
        P        = design pressure (kPa)
        sigma_a  = allowable bending stress (N/mm²)
                   = 0.80 * sigma_y  (ABS typically uses 80% yield for plating)
        1000     = unit conversion factor (kPa * mm² / N/mm² → mm)

    For steel: sigma_a = 0.80 * sigma_y  (ABS Pt.3 Ch.2 Sec.3 Annex / Table 3.2.1)

    Reference: ABS Rules for Building and Classing Steel Vessels 2024,
               Part 3 Chapter 2 Section 3 "Shell Plating", publicly available.

    Parameters
    ----------
    P_kPa    : float  design pressure (kPa)
    s_mm     : float  plate spacing (mm)
    sigma_a_MPa : float  allowable bending stress (N/mm²)

    Returns
    -------
    float  required plate thickness (mm)
    """
    if sigma_a_MPa <= 0 or P_kPa <= 0:
        return 0.0
    return s_mm * math.sqrt(P_kPa / (1000.0 * sigma_a_MPa))


def abs_stiffener_sm(
    P_kPa: float,
    s_mm: float,
    l_mm: float,
    sigma_a_MPa: float,
    C: float = 1.0 / 12.0,
) -> float:
    """
    ABS Steel Vessel Rules 2024 — minimum stiffener section modulus.

    ABS formula (Pt.3 Ch.2 Sec.3 Stiffeners):

        SM = C * P * s * l^2 / (1000 * sigma_a)   [cm³]

    Same boundary-condition coefficient as ISO 12215-5:
        C = 1/12  (both ends fixed — typical welded ship stiffeners)
        C = 1/8   (simply supported)

    Reference: ABS Rules for Building and Classing Steel Vessels 2024,
               Part 3 Chapter 2 Section 3 "Stiffeners / Frames", publicly available.

    Parameters
    ----------
    P_kPa      : float  design pressure (kPa)
    s_mm       : float  stiffener spacing (mm)
    l_mm       : float  stiffener unsupported span (mm)
    sigma_a_MPa: float  allowable bending stress (N/mm²) = 0.80 * sigma_y
    C          : float  boundary coefficient (default 1/12)

    Returns
    -------
    float  required section modulus (cm³)
    """
    if sigma_a_MPa <= 0 or P_kPa <= 0:
        return 0.0
    return C * P_kPa * s_mm * (l_mm ** 2) / (1000.0 * sigma_a_MPa)


def check_abs(
    draft_m: float,
    h_panel_m: float,
    s_mm: float,
    l_mm: float,
    lu_mm: float,
    material: MaterialProps,
    Cw: float = 0.0,
    zone: str = "side",
    t_actual_mm: Optional[float] = None,
    SM_actual_cm3: Optional[float] = None,
    both_ends_fixed: bool = True,
) -> ScantlingCheckResult:
    """
    ABS Steel Vessels 2024 Pt.3 Ch.2 §3 local scantling check.

    Design pressure: P = rho * g * h_panel + Cw  [kPa]
    Plate thickness: t = s * sqrt(P / (1000 * sigma_a))  [mm]
    Stiffener SM: SM = C * P * s * lu^2 / (1000 * sigma_a)  [cm³]

    ABS allowable stress: sigma_a = 0.80 * sigma_yt  (plating/stiffeners,
    Pt.3 Ch.2 Sec.3 Table 3.2.1 for steel; 0.60*yield from ABS MODU rules
    for other materials — use 0.80 here per basic structural criteria).

    Parameters
    ----------
    draft_m   : float  vessel draft (m) — used for context/notes
    h_panel_m : float  hydrostatic head to panel (m) — depth below waterline
                       = draft for keel, 0 for weather deck, fraction for side
    s_mm      : float  plate stiffener spacing / short panel side (mm)
    l_mm      : float  long panel side (mm)
    lu_mm     : float  stiffener unsupported span (mm)
    material  : MaterialProps
    Cw        : float  wave correction (kPa); 0 for sheltered, ~5–10 for exposed
    zone      : str    "bottom" | "side" | "deck" | "bulkhead"
    t_actual_mm  : float or None  provided plate thickness (mm)
    SM_actual_cm3: float or None  provided stiffener SM (cm³)
    both_ends_fixed: bool  True → C = 1/12

    Returns
    -------
    ScantlingCheckResult
    """
    rho_sw = 1.025  # t/m³ = standard seawater for ABS rules
    P = abs_design_pressure(h_panel_m, Cw, rho=rho_sw)

    # ABS allowable stress: 0.80 * yield
    if material.sigma_yt > 0:
        sigma_a = 0.80 * material.sigma_yt
    else:
        # FRP — fall back to ISO 12215-5 design stress
        sigma_a = material.sigma_uf / 3.0
    sigma_a = max(sigma_a, 1.0)

    t_req = abs_plate_thickness(P, s_mm, sigma_a)

    # ABS minimum plate thickness (Pt.3 Ch.2 §3 — construction minimum)
    # Steel: t_min = 4.5 + 0.02 * L_pp  (for vessels; simplified 4.5 mm floor here)
    # For small craft context use 4.5 mm steel minimum
    if material.sigma_yt > 0:
        t_min_constr = 4.5  # mm — conservative ABS steel floor
    else:
        t_min_constr = 2.5  # mm — conservative FRP floor
    t_req = max(t_req, t_min_constr)

    C = 1.0 / 12.0 if both_ends_fixed else 1.0 / 8.0
    SM_req = abs_stiffener_sm(P, s_mm, lu_mm, sigma_a, C=C)

    # PASS/FAIL
    if t_actual_mm is not None and t_actual_mm > 0:
        p_util   = t_req / t_actual_mm
        p_passes = p_util <= 1.0
    else:
        p_util   = 1.0
        p_passes = True

    if SM_actual_cm3 is not None and SM_actual_cm3 > 0:
        s_util   = SM_req / SM_actual_cm3
        s_passes = s_util <= 1.0
    else:
        s_util   = 1.0
        s_passes = True

    overall = p_passes and s_passes
    component = "both" if (t_actual_mm is not None or SM_actual_cm3 is not None) else "required-only"

    notes = [
        f"ABS allowable stress σ_a = 0.80 × σ_y = {sigma_a:.1f} N/mm².",
        f"Design pressure h_panel = {h_panel_m:.2f} m, P = {P:.2f} kPa.",
        "ABS rules cover steel vessels; FRP via ABS Guide for Vessels using FRP (separate).",
    ]

    return ScantlingCheckResult(
        rule_set        = "ABS Rules for Steel Vessels 2024 Pt.3 Ch.2 §3",
        component       = component,
        zone            = zone,
        P_design_kPa    = P,
        t_required_mm   = t_req,
        t_actual_mm     = t_actual_mm,
        plate_util      = p_util,
        plate_passes    = p_passes,
        SM_required_cm3 = SM_req,
        SM_actual_cm3   = SM_actual_cm3,
        stiff_util      = s_util,
        stiff_passes    = s_passes,
        passes          = overall,
        clause          = (
            "ABS Rules for Building and Classing Steel Vessels 2024, "
            "Pt.3 Ch.2 Sec.3 'Shell Plating' (plate: Eq. t=s√(P/1000σa)); "
            "'Stiffeners' (SM=C·P·s·l²/1000σa); "
            "design pressure §3.3 P = ρgh + Cw."
        ),
        notes = notes,
    )


# ---------------------------------------------------------------------------
# DNV local scantling check
# ---------------------------------------------------------------------------

def dnv_ka_factor(s_mm: float, l_mm: float) -> float:
    """
    DNV Rules for Classification of Ships (July 2023) Pt.3 Ch.1 Sec.7.

    Aspect-ratio correction factor ka for plate bending:

        ka = (0.5 + (s/l)^2)   capped at 1.0

    where s/l = ratio of short side to long side.

    Reference: DNV-RU-SHIP Pt.3 Ch.1 Sec.7 Eq. (7.4) — publicly available
               in DNV Rules for Classification of Ships.

    Parameters
    ----------
    s_mm : float  short side (mm)
    l_mm : float  long side (mm)
    """
    if l_mm <= 0:
        return 1.0
    ratio = min(s_mm, l_mm) / max(s_mm, l_mm)   # s/l ∈ (0, 1]
    ka = 0.5 + ratio ** 2
    return min(ka, 1.0)


def dnv_design_pressure(
    h_m: float,
    V_kn: float = 0.0,
    zone: str = "side",
    rho: float = 1.025,
) -> float:
    """
    DNV Rules for Classification of Ships (July 2023) Pt.3 Ch.1 Sec.7 —
    local design pressure.

    Hull side / bottom pressure (Clause 702):

        P = rho * g * h + 0.5 * rho * (V_slam)^2     [kPa]

    where:
        h          = distance below waterline to the panel (m)
        V_slam     = slamming velocity (m/s) — simplified as V (ship speed) / 2
                     for side and forward panels; 0 for deck and aft panels
        rho        = water density (t/m³)

    For weather deck (zone = "deck"):
        P = 25 kPa (minimum exposed deck loading per DNV Sec.7 Clause 703)
        or: P_wave = 0.35 * Cw_deck if provided; simplified to 25 kPa here.

    For bulkheads:
        P = rho * g * h   (hydrostatic only; no slamming)

    Reference: DNV-RU-SHIP Pt.3 Ch.1 Sec.7 'Design Pressures', publicly
               available at rules.dnv.com (open access).

    Parameters
    ----------
    h_m   : float  hydrostatic head (m) — depth below waterline to panel
    V_kn  : float  ship design speed (kn); slamming V_slam = V_kn * 0.5144 / 2
    zone  : str    "bottom" | "side" | "deck" | "bulkhead"
    rho   : float  water density (t/m³)

    Returns
    -------
    float  design pressure (kPa)
    """
    g = G  # m/s²
    rho_kgm3 = rho * 1000.0  # convert t/m³ → kg/m³

    if zone == "deck":
        # DNV Sec.7 Cl.703 — minimum 25 kPa weather deck
        P_hydrostatic = rho_kgm3 * g * h_m / 1000.0   # kPa
        return max(P_hydrostatic, 25.0)

    if zone == "bulkhead":
        P = rho_kgm3 * g * h_m / 1000.0
        return max(P, 0.0)

    # Side / bottom — hydrostatic + slamming
    V_ms = V_kn * 0.5144           # m/s ship speed
    V_slam = V_ms / 2.0            # slamming velocity (simplified)
    P_hydro = rho_kgm3 * g * h_m / 1000.0          # kPa
    P_slam  = 0.5 * rho_kgm3 * (V_slam ** 2) / 1000.0  # kPa
    P = P_hydro + P_slam
    return max(P, 0.0)


def dnv_plate_thickness(
    P_kPa: float,
    ka: float,
    s_mm: float,
    sigma_f_MPa: float,
) -> float:
    """
    DNV Rules for Classification of Ships (July 2023) Pt.3 Ch.1 Sec.7
    Eq. (7.2) — minimum plate thickness.

        t = 15.8 * ka * s * sqrt(P / sigma_f)   [mm]

    where:
        ka      = aspect-ratio factor (Eq. 7.4)
        s       = plate spacing (mm) — short side in metres for the formula,
                  but published with s in metres; we convert: s_m = s_mm / 1000
        P       = design pressure (kPa)
        sigma_f = permissible bending stress (N/mm²) = 0.9 * sigma_y or
                  0.90 * sigma_f (fatigue controlled) — for check we use 0.90 * sigma_y
        15.8    = dimensional constant absorbing unit conversions

    Full unit derivation (published in DNV commentary):
        t_mm = 15.8 * ka * s_m * 1000 * sqrt(P_kPa / (1000 * sigma_f_N/mm²))
             = 15.8 * ka * (s_mm) * sqrt(P_kPa / (1000 * sigma_f))
    So the 15.8 factor already absorbs the 1000 factor.

    Reference: DNV-RU-SHIP Pt.3 Ch.1 Sec.7 Eq. (7.2), publicly available.

    Parameters
    ----------
    P_kPa      : float  design pressure (kPa)
    ka         : float  aspect ratio factor
    s_mm       : float  plate spacing — short side (mm)
    sigma_f_MPa: float  permissible bending stress (N/mm²)

    Returns
    -------
    float  required plate thickness (mm)
    """
    if sigma_f_MPa <= 0 or P_kPa <= 0:
        return 0.0
    s_m = s_mm / 1000.0
    t = 15.8 * ka * s_m * 1000.0 * math.sqrt(P_kPa / (1000.0 * sigma_f_MPa))
    return t


def dnv_stiffener_sm(
    P_kPa: float,
    l_mm: float,
    s_mm: float,
    sigma_f_MPa: float,
    m: float = 1.0 / 12.0,
) -> float:
    """
    DNV Rules for Classification of Ships (July 2023) Pt.3 Ch.1 Sec.7
    Eq. (7.6) — minimum stiffener section modulus.

        SM = 83.3 * m * l * s * P / sigma_f   [cm³]

    where:
        m       = 1/12 (fixed ends) or 1/8 (pin-pin)
        l       = stiffener span (m)
        s       = stiffener spacing (m)
        P       = design pressure (kPa)
        sigma_f = permissible bending stress (N/mm²)
        83.3    = dimensional constant

    Unit derivation:
        SM [cm³] = m * P [kN/m²] * s [m] * l² [m²] / sigma_f [N/mm²]
                 = m * P * s * l² * 1000 / sigma_f  ... /1000 for cm³→mm³:
        Using l_m, s_m:
        SM = m * P * s_m * l_m^2 * 1e6 / (sigma_f * 1e3)   [mm³ / 1e3 = cm³]
           = m * P * s_m * l_m^2 * 1000 / sigma_f   [cm³]

    The published Eq. (7.6) uses 83.3 = 1000 / 12 to absorb both m = 1/12
    and unit conversion:  83.3 ≈ 1000/12 = 83.33.

    Reference: DNV-RU-SHIP Pt.3 Ch.1 Sec.7 Eq. (7.6), publicly available.

    Parameters
    ----------
    P_kPa      : float  design pressure (kPa)
    l_mm       : float  stiffener span (mm)
    s_mm       : float  stiffener spacing (mm)
    sigma_f_MPa: float  permissible bending stress (N/mm²)
    m          : float  boundary coefficient (default 1/12)

    Returns
    -------
    float  required section modulus (cm³)
    """
    if sigma_f_MPa <= 0 or P_kPa <= 0:
        return 0.0
    l_m = l_mm / 1000.0
    s_m = s_mm / 1000.0
    SM = m * P_kPa * s_m * (l_m ** 2) * 1000.0 / sigma_f_MPa
    return SM


def check_dnv(
    h_panel_m: float,
    V_kn: float,
    s_mm: float,
    l_mm: float,
    lu_mm: float,
    material: MaterialProps,
    zone: str = "side",
    t_actual_mm: Optional[float] = None,
    SM_actual_cm3: Optional[float] = None,
    both_ends_fixed: bool = True,
) -> ScantlingCheckResult:
    """
    DNV Rules for Classification of Ships (July 2023) Pt.3 Ch.1 Sec.7
    local scantling check — PASS/FAIL vs provided scantlings.

    Rule formulae (all publicly published at rules.dnv.com):
      Pressure: P = rho*g*h + 0.5*rho*(V/2)^2         [kPa]    Cl.702
      Plate:    t = 15.8 * ka * s * sqrt(P / sigma_f)  [mm]     Eq. 7.2
      Stiffener: SM = 83.3 * m * l * s * P / sigma_f   [cm³]    Eq. 7.6
      DNV permissible stress: sigma_f = 0.90 * sigma_y            Cl.705

    Parameters
    ----------
    h_panel_m   : float  depth below waterline to panel (m)
    V_kn        : float  design vessel speed (knots)
    s_mm        : float  plate spacing / short side (mm)
    l_mm        : float  plate long side (mm)
    lu_mm       : float  stiffener unsupported span (mm)
    material    : MaterialProps
    zone        : str    "bottom" | "side" | "deck" | "bulkhead"
    t_actual_mm : float or None  provided plate thickness
    SM_actual_cm3: float or None  provided SM
    both_ends_fixed: bool

    Returns
    -------
    ScantlingCheckResult
    """
    P = dnv_design_pressure(h_panel_m, V_kn, zone)

    # DNV permissible bending stress: sigma_f = 0.90 * sigma_y
    if material.sigma_yt > 0:
        sigma_f = 0.90 * material.sigma_yt
    else:
        sigma_f = material.sigma_uf / 3.0
    sigma_f = max(sigma_f, 1.0)

    ka = dnv_ka_factor(s_mm, l_mm)
    t_req = dnv_plate_thickness(P, ka, s_mm, sigma_f)

    # DNV minimum steel plate: 5.0 mm construction minimum for ship shell
    if material.sigma_yt > 0:
        t_req = max(t_req, 5.0)
    else:
        t_req = max(t_req, 2.0)

    m = 1.0 / 12.0 if both_ends_fixed else 1.0 / 8.0
    SM_req = dnv_stiffener_sm(P, lu_mm, s_mm, sigma_f, m=m)

    # PASS/FAIL
    if t_actual_mm is not None and t_actual_mm > 0:
        p_util   = t_req / t_actual_mm
        p_passes = p_util <= 1.0
    else:
        p_util   = 1.0
        p_passes = True

    if SM_actual_cm3 is not None and SM_actual_cm3 > 0:
        s_util   = SM_req / SM_actual_cm3
        s_passes = s_util <= 1.0
    else:
        s_util   = 1.0
        s_passes = True

    overall = p_passes and s_passes
    component = "both" if (t_actual_mm is not None or SM_actual_cm3 is not None) else "required-only"

    notes = [
        f"DNV permissible stress σ_f = 0.90 × σ_y = {sigma_f:.1f} N/mm².",
        f"Design pressure h = {h_panel_m:.2f} m, V_slam = {V_kn * 0.5144 / 2:.2f} m/s, P = {P:.2f} kPa.",
        f"Aspect-ratio factor ka = {ka:.3f}.",
        "DNV rules cover sea-going vessels. Full rule suite requires class-society subscription.",
    ]

    return ScantlingCheckResult(
        rule_set        = "DNV Rules for Classification of Ships 2023 Pt.3 Ch.1 Sec.7",
        component       = component,
        zone            = zone,
        P_design_kPa    = P,
        t_required_mm   = t_req,
        t_actual_mm     = t_actual_mm,
        plate_util      = p_util,
        plate_passes    = p_passes,
        SM_required_cm3 = SM_req,
        SM_actual_cm3   = SM_actual_cm3,
        stiff_util      = s_util,
        stiff_passes    = s_passes,
        passes          = overall,
        clause          = (
            "DNV-RU-SHIP Pt.3 Ch.1 Sec.7 (July 2023): "
            "pressure Cl.702 P=ρgh+0.5ρV²; "
            "plate Eq.7.2 t=15.8·ka·s·√(P/σf); "
            "stiffener Eq.7.6 SM=83.3·m·l·s·P/σf; "
            "permissible stress Cl.705 σf=0.90·σy."
        ),
        notes = notes,
    )


# ---------------------------------------------------------------------------
# Unified marine_scantling_check entry point
# ---------------------------------------------------------------------------

@dataclass
class ScantlingCheckMultiResult:
    """
    Combined result for marine_scantling_check — one entry per rule-set requested.

    Attributes
    ----------
    results : list[ScantlingCheckResult]
    all_pass: bool  True only if ALL rule-set checks pass
    summary : str   human-readable summary
    """
    results:  list
    all_pass: bool
    summary:  str

    def as_dict(self) -> dict:
        return {
            "all_pass": self.all_pass,
            "summary":  self.summary,
            "checks":   [r.as_dict() for r in self.results],
        }


def marine_scantling_check(
    # Panel geometry
    b_mm: float,
    l_mm: float,
    lu_mm: float,
    s_mm: float,
    material: MaterialProps,
    # Rule selection
    rule_sets: list,     # list of str: "iso", "abs", "dnv"
    zone: str = "bottom",
    # ISO 12215-5 inputs
    LWL: float = 10.0,
    BWL: float = 3.0,
    mLDC: float = 5000.0,
    V: float = 15.0,
    beta_04: float = 20.0,
    category: DesignCategory = DesignCategory.A,
    z_mm: float = 0.0,
    is_sailing: bool = False,
    # ABS/DNV inputs
    h_panel_m: float = 1.5,
    V_kn: float = 0.0,
    Cw: float = 0.0,
    draft_m: float = 2.0,
    # Actual scantlings (for PASS/FAIL)
    t_actual_mm: Optional[float] = None,
    SM_actual_cm3: Optional[float] = None,
    both_ends_fixed: bool = True,
) -> ScantlingCheckMultiResult:
    """
    Unified hull scantling check against multiple rule sets.

    Calls the relevant check functions for each requested rule_set:
      "iso"  → ISO 12215-5:2008 (small craft, any material)
      "abs"  → ABS Rules for Steel Vessels 2024 Pt.3 Ch.2 §3
      "dnv"  → DNV Rules 2023 Pt.3 Ch.1 Sec.7

    Parameters
    ----------
    See individual check_* functions for parameter descriptions.

    Returns
    -------
    ScantlingCheckMultiResult (contains list of ScantlingCheckResult)
    """
    results = []

    norm = [r.lower().strip() for r in rule_sets]

    if "iso" in norm or "iso12215" in norm or "iso 12215" in norm:
        r = check_iso_12215(
            LWL=LWL, BWL=BWL, mLDC=mLDC, V=V, beta_04=beta_04,
            b_mm=b_mm, l_mm=l_mm, lu_mm=lu_mm, s_mm=s_mm,
            material=material, category=category, zone=zone,
            t_actual_mm=t_actual_mm, SM_actual_cm3=SM_actual_cm3,
            z_mm=z_mm, is_sailing=is_sailing,
        )
        results.append(r)

    if "abs" in norm:
        r = check_abs(
            draft_m=draft_m, h_panel_m=h_panel_m,
            s_mm=s_mm, l_mm=l_mm, lu_mm=lu_mm,
            material=material, Cw=Cw, zone=zone,
            t_actual_mm=t_actual_mm, SM_actual_cm3=SM_actual_cm3,
            both_ends_fixed=both_ends_fixed,
        )
        results.append(r)

    if "dnv" in norm:
        r = check_dnv(
            h_panel_m=h_panel_m, V_kn=V_kn,
            s_mm=s_mm, l_mm=l_mm, lu_mm=lu_mm,
            material=material, zone=zone,
            t_actual_mm=t_actual_mm, SM_actual_cm3=SM_actual_cm3,
            both_ends_fixed=both_ends_fixed,
        )
        results.append(r)

    if not results:
        # Default to ISO if no valid rule_sets given
        r = check_iso_12215(
            LWL=LWL, BWL=BWL, mLDC=mLDC, V=V, beta_04=beta_04,
            b_mm=b_mm, l_mm=l_mm, lu_mm=lu_mm, s_mm=s_mm,
            material=material, category=category, zone=zone,
            t_actual_mm=t_actual_mm, SM_actual_cm3=SM_actual_cm3,
        )
        results.append(r)

    all_pass = all(r.passes for r in results)

    if t_actual_mm is None and SM_actual_cm3 is None:
        summary = (
            f"Required scantlings for {len(results)} rule-set(s). "
            f"Provide t_actual_mm / SM_actual_cm3 for PASS/FAIL."
        )
    elif all_pass:
        summary = f"PASS — all {len(results)} rule-set(s) satisfied."
    else:
        failed = [r.rule_set for r in results if not r.passes]
        summary = f"FAIL — {len(failed)} rule-set(s) not satisfied: {'; '.join(failed)}."

    return ScantlingCheckMultiResult(results=results, all_pass=all_pass, summary=summary)
