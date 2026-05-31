"""
kerf_cad_core.arch.lintel_design — Steel, RC, and reinforced masonry lintel design.

Implements simple-span lintel design over wall openings for three material types:

  steel             — AISC Manual Table 3-23 (bending) + AISC 360-22 §G2 (shear);
                      elastic section modulus S_x for W/L/C shapes (user supplies section
                      properties as lintel_depth_mm, lintel_width_mm, fc_or_fy_MPa = Fy).
  reinforced_concrete — ACI 318-19 §9 LRFD flexure (φ=0.90) + shear (φ=0.75).
  reinforced_masonry  — TMS 402-22 §5 flexure (φ=0.90) + shear (φ=0.80).

Load model
----------
Superimposed loads:
  • UDL:        w_u = 1.2·DL + 1.6·LL  [kN/m]  (ASCE 7-16 §2.3.1 load combination 2)

Masonry triangular arching action (TMS 402-22 Commentary §5.3.1; BIA Technical Note 31B):
  When masonry height above lintel ≥ L/2 (45° arching triangle limit), only the
  triangular load within the 45° arching triangle needs to be supported.
  The triangular load has peak w_tri_peak = γ_masonry · L/2 [kN/m] at mid-span.
  Total arching resultant W_tri = 0.5 · w_tri_peak · L [kN]  (isoceles triangle).
  M_tri = W_tri · L / 6  (triangular load on SS beam — Roark 9e §8 Table 8.1 case 5).
  V_tri = W_tri / 2  (symmetric triangular load, max shear at supports).
  When masonry height < L/2 the full rectangular load from masonry_above_height_mm
  of masonry is used instead: w_masonry = γ_masonry · masonry_above_height_m [kN/m].

Combined factored loads (LRFD):
  Total M_max = M_udl + M_masonry  (superposition, simple span)
  Total V_max = V_udl + V_masonry

Capacity
--------
Steel (symmetric I/channel, elastic section properties approximated from depth × width):
  S_x = (lintel_width_mm · lintel_depth_mm²) / 6      [elastic modulus of rectangle]
  I_x = lintel_width_mm · lintel_depth_mm³ / 12
  NOTE: This is a solid rectangular cross-section model. For actual W/L-shapes the
        caller should use a dedicated AISC section lookup; see honest_caveat.
  φ_b = 0.90; φ_v = 1.00 (AISC 360-22 §F1 / §G2.1)
  φ·Mn = φ_b · Fy · S_x                               [kN·m]  (yielding governs, Lp check omitted)
  φ·Vn = φ_v · 0.6 · Fy · A_web  where A_web = 0.50 · lintel_depth_mm · lintel_width_mm
         (conservative 50% web area for rectangular approximation)
  E = 200 000 MPa; deflection: δ = 5·w_total·L⁴/(384·E·I) for UDL component
      + W_tri·L³/(60.75·E·I) for triangular component (Roark 9e case 5 δ_max≈0.01304·WL³/EI)

Reinforced concrete (ACI 318-19 §9):
  d = lintel_depth_mm − 65 mm  (cover + bar radius, assumed)
  ρ_max = 0.018 (≈ 0.375·ρ_bal at f'c=28 MPa, fy=420 MPa; conservative for rectangular beam)
  As = ρ_max · lintel_width_mm · d
  a  = As · fy / (0.85 · f'c · lintel_width_mm)
  φ·Mn = φ · As · fy · (d − a/2)  [N·mm] → kN·m
  V_c = 0.17 · √f'c · lintel_width_mm · d  (ACI §22.5.5.1, λ=1 normal-weight concrete)
  φ·Vn = φ_v · V_c  (stirrups not modelled; conservative)
  fc_or_fy_MPa = f'c (concrete compressive strength); fy assumed 420 MPa
  E_c = 4700 · √f'c  [MPa]

Reinforced masonry (TMS 402-22 §5):
  d = lintel_depth_mm − 65 mm
  ρ_max = 0.010 (conservative TMS §9.3.3.2 ρ ≤ ρ_max masonry)
  fy_s = 420 MPa  (Grade 60 rebar)
  As = ρ_max · lintel_width_mm · d
  a  = As · fy_s / (0.80 · f_m · lintel_width_mm)   (TMS §9.3.3.1 α_1 = 0.80)
  φ·Mn = φ · As · fy_s · (d − a/2)
  V_n = A_n · √(f_m) / 3  (TMS §9.3.4.1.2, no shear reinforcement; A_n = b·d)
  φ·Vn = φ_v · V_n
  fc_or_fy_MPa = f'm (masonry compressive strength)
  E_m = 900 · f_m  (TMS §4.2.2)

Deflection limit:
  Beams supporting masonry or roof → L/240  (plaster, stiff finish)
  floor_lintel parameter (default False) → L/360 for floor beams
  deflection_ok = (δ_max ≤ L/limit)

Scope and honest caveats
------------------------
  • Simple span only — continuous-beam moment redistribution NOT modelled.
  • Lateral-torsional buckling of steel lintel NOT checked (use arch_check_lateral_bracing).
  • Reinforcement area is ESTIMATED from ρ_max; actual detailing governs.
  • ACI shear model: minimum stirrups NOT added; φ·Vn is for plain concrete web.
  • Arching action: 45° triangle only; TMS Commentary §5.3.1 (BIA TN-31B).
    If course height or joint conditions prevent arching, use full triangular load manually.
  • LRFD load factors per ASCE 7-16 §2.3.1 combination 2 (1.2D + 1.6L).
    Other combinations (1.4D; wind; seismic) must be checked separately.
  • masonry γ assumed 20 kN/m³ (typical grouted concrete masonry, TMS §1.6.1).

References
----------
  AISC (2017). Steel Construction Manual, 15th ed. Table 3-23 "Shears, Moments,
    and Deflections"; AISC 360-22 §F1/§G2.
  ACI 318-19. "Building Code Requirements for Structural Concrete". §9.5 (flexure),
    §9.6 (shear), §22.5 (nominal shear).
  TMS 402-22. "Building Code Requirements and Specification for Masonry Structures".
    §5.2 (flexure), §5.3 (lintel design), §9.3.3 (RM flexure), §9.3.4 (RM shear).
  BIA Technical Note 31B (2009). "Structural Steel Lintels".
  Roark, R.J. et al. (2020). Roark's Formulas for Stress and Strain, 9th ed. §8 Table 8.1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "LintelSpec",
    "LintelDesignReport",
    "design_lintel",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_MATERIALS = frozenset({"steel", "reinforced_concrete", "reinforced_masonry"})

_GAMMA_MASONRY_kN_per_m3 = 20.0      # kN/m³ — grouted CMU (TMS §1.6.1 typical)
_E_STEEL_MPa = 200_000.0             # MPa
_PHI_B_STEEL = 0.90                  # AISC 360-22 §F1
_PHI_V_STEEL = 1.00                  # AISC 360-22 §G2.1 (web shear, h/tw ≤ 2.24√(E/Fy))
_PHI_B_RC = 0.90                     # ACI 318-19 Table 21.2.2 tension-controlled
_PHI_V_RC = 0.75                     # ACI 318-19 Table 21.2.1
_PHI_B_RM = 0.90                     # TMS 402-22 §7.3.2.2
_PHI_V_RM = 0.80                     # TMS 402-22 §7.3.2.3
_FY_REBAR_MPa = 420.0                # Grade 60 reinforcing steel
_COVER_PLUS_HALF_BAR_mm = 65.0       # d = depth − 65 mm (38 mm cover + ~28 mm for #8 bar)
_RHO_MAX_RC = 0.018                  # ≈ 0.375·ρ_bal (conservative net-tension limit)
_RHO_MAX_RM = 0.010                  # TMS §9.3.3.2 maximum reinforcement ratio


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class LintelSpec:
    """
    Input specification for a lintel design check.

    Parameters
    ----------
    opening_span_mm : float
        Clear span of the wall opening in mm. Must be > 0.
        Example: 1200 for a 1.2 m door opening.
    wall_thickness_mm : float
        Wall thickness (= lintel bearing width) in mm. Must be > 0.
        Used for masonry triangular load width context; lintel_width_mm governs section.
    material : str
        Lintel material: "steel" | "reinforced_concrete" | "reinforced_masonry".
    lintel_depth_mm : float
        Overall depth of lintel cross-section in mm. Must be > 0.
        Steel: total section depth (e.g. 101.6 mm for L4×4×1/4 angle leg).
        RC/RM: total beam depth including cover.
    lintel_width_mm : float
        Width of lintel cross-section in mm. Must be > 0.
        Steel: flange width (or combined leg width for back-to-back angles).
        RC/RM: beam width (= wall thickness typically).
    fc_or_fy_MPa : float
        Material strength in MPa. Must be > 0.
        Steel → Fy (yield stress). Example: 250 MPa (A36), 345 MPa (A992).
        Reinforced concrete → f'c (concrete compressive strength). Example: 28 MPa.
        Reinforced masonry → f'm (masonry compressive strength). Example: 14 MPa.
    dead_load_kN_per_m : float
        Service dead load (superimposed, excluding self-weight) in kN/m. Must be ≥ 0.
    live_load_kN_per_m : float
        Service live load in kN/m. Must be ≥ 0.
    masonry_above_height_mm : float
        Height of masonry course above the lintel (to the next floor/beam/slab) in mm.
        0 → no masonry self-weight included (non-masonry cladding or opening top).
        > 0 → masonry triangular arching action applied per TMS 402-22 Commentary §5.3.1.
        Must be ≥ 0.
    floor_lintel : bool
        True if supporting a floor (deflection limit L/360); False (default) if supporting
        roof or masonry wall only (deflection limit L/240).
    """
    opening_span_mm: float
    wall_thickness_mm: float
    material: str
    lintel_depth_mm: float
    lintel_width_mm: float
    fc_or_fy_MPa: float
    dead_load_kN_per_m: float
    live_load_kN_per_m: float
    masonry_above_height_mm: float
    floor_lintel: bool = False


@dataclass
class LintelDesignReport:
    """
    Output of a lintel design check.

    Parameters
    ----------
    M_max_kNm : float
        Maximum factored bending moment at mid-span (kN·m). Superposition of
        UDL (factored) + masonry arching or rectangular components.
    V_max_kN : float
        Maximum factored shear at supports (kN).
    delta_max_mm : float
        Maximum elastic mid-span deflection under *service* (unfactored) loads (mm).
    phi_Mn_kNm : float
        Design moment capacity φ·Mn (kN·m).
    phi_Vn_kN : float
        Design shear capacity φ·Vn (kN).
    moment_dcr : float
        Demand-capacity ratio for bending: M_max / φ·Mn. < 1.0 → adequate.
    shear_dcr : float
        Demand-capacity ratio for shear: V_max / φ·Vn. < 1.0 → adequate.
    deflection_ok : bool
        True if delta_max_mm ≤ L / deflection_limit (L/240 or L/360).
    adequate : bool
        True if moment_dcr ≤ 1.0 AND shear_dcr ≤ 1.0 AND deflection_ok.
    honest_caveat : str
        Plain-language scope statement: references, assumptions, what is NOT checked.
    """
    M_max_kNm: float
    V_max_kN: float
    delta_max_mm: float
    phi_Mn_kNm: float
    phi_Vn_kN: float
    moment_dcr: float
    shear_dcr: float
    deflection_ok: bool
    adequate: bool
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def design_lintel(spec: LintelSpec) -> LintelDesignReport:
    """
    Check a lintel over a wall opening for moment, shear, and deflection.

    Parameters
    ----------
    spec : LintelSpec
        Full lintel geometry, material, and loading specification.

    Returns
    -------
    LintelDesignReport

    Raises
    ------
    ValueError
        If any required parameter is out of range or material is unrecognised.

    Notes
    -----
    Simple span only.  Continuous-beam moment redistribution NOT modelled.
    Arching action: 45° isoceles triangle (TMS 402-22 Commentary §5.3.1).
    Load factors: ASCE 7-16 §2.3.1 combination 2 (1.2D + 1.6L).
    Deflection: elastic under service (unfactored) loads.
    """
    # ---- Input validation --------------------------------------------------
    if spec.opening_span_mm <= 0.0:
        raise ValueError(f"opening_span_mm must be > 0, got {spec.opening_span_mm}")
    if spec.wall_thickness_mm <= 0.0:
        raise ValueError(f"wall_thickness_mm must be > 0, got {spec.wall_thickness_mm}")
    if spec.material not in _VALID_MATERIALS:
        raise ValueError(
            f"material must be one of {sorted(_VALID_MATERIALS)}, got {spec.material!r}"
        )
    if spec.lintel_depth_mm <= 0.0:
        raise ValueError(f"lintel_depth_mm must be > 0, got {spec.lintel_depth_mm}")
    if spec.lintel_width_mm <= 0.0:
        raise ValueError(f"lintel_width_mm must be > 0, got {spec.lintel_width_mm}")
    if spec.fc_or_fy_MPa <= 0.0:
        raise ValueError(f"fc_or_fy_MPa must be > 0, got {spec.fc_or_fy_MPa}")
    if spec.dead_load_kN_per_m < 0.0:
        raise ValueError(f"dead_load_kN_per_m must be ≥ 0, got {spec.dead_load_kN_per_m}")
    if spec.live_load_kN_per_m < 0.0:
        raise ValueError(f"live_load_kN_per_m must be ≥ 0, got {spec.live_load_kN_per_m}")
    if spec.masonry_above_height_mm < 0.0:
        raise ValueError(
            f"masonry_above_height_mm must be ≥ 0, got {spec.masonry_above_height_mm}"
        )

    L_mm = spec.opening_span_mm
    L_m = L_mm / 1000.0
    b_mm = spec.lintel_width_mm
    h_mm = spec.lintel_depth_mm
    mat = spec.material

    # ---- Factored UDL (ASCE 7-16 §2.3.1 combination 2) --------------------
    DL = spec.dead_load_kN_per_m
    LL = spec.live_load_kN_per_m
    w_u = 1.2 * DL + 1.6 * LL                     # kN/m (factored)
    w_s = DL + LL                                  # kN/m (service, for deflection)

    # SS beam: M = wL²/8, V = wL/2
    M_udl_kNm = w_u * L_m**2 / 8.0
    V_udl_kN = w_u * L_m / 2.0

    # Service deflection — UDL component only (masonry added below)
    # E and I depend on material; compute after section properties below
    # placeholder; resolved after capacity section

    # ---- Masonry arching load (TMS 402-22 Commentary §5.3.1; BIA TN-31B) --
    h_masonry_mm = spec.masonry_above_height_mm
    h_masonry_m = h_masonry_mm / 1000.0
    arching_threshold_m = L_m / 2.0       # half-span = leg of 45° triangle

    M_masonry_kNm: float = 0.0
    V_masonry_kN: float = 0.0
    M_masonry_s_kNm: float = 0.0  # service version
    V_masonry_s_kN: float = 0.0
    masonry_load_desc: str = "no masonry above"

    if h_masonry_mm > 0.0:
        if h_masonry_m >= arching_threshold_m:
            # Full 45° arching triangle — TMS Commentary §5.3.1
            # Peak intensity at mid-span: γ · L/2
            w_tri_peak_kN_per_m = _GAMMA_MASONRY_kN_per_m3 * arching_threshold_m  # kN/m
            # Total triangular resultant (unfactored)
            W_tri_s_kN = 0.5 * w_tri_peak_kN_per_m * L_m           # kN (service)
            # Factored: masonry self-weight → DL factor = 1.2
            W_tri_u_kN = 1.2 * W_tri_s_kN
            # SS beam triangular load:
            #   M_max = W·L/6  (resultant W = 0.5·w_peak·L, apex at centre)
            #   [Roark 9e §8 Table 8.1 case 5: symmetrical triangle → M=WL/6]
            #   V_max = W/2  (symmetric, each reaction = W/2)
            M_masonry_kNm = W_tri_u_kN * L_m / 6.0
            V_masonry_kN = W_tri_u_kN / 2.0
            M_masonry_s_kNm = W_tri_s_kN * L_m / 6.0
            V_masonry_s_kN = W_tri_s_kN / 2.0
            masonry_load_desc = (
                f"45° arching triangle: h_masonry={h_masonry_m:.3f}m ≥ L/2={arching_threshold_m:.3f}m; "
                f"w_peak={w_tri_peak_kN_per_m:.3f} kN/m, W_tri(service)={W_tri_s_kN:.3f} kN"
            )
        else:
            # Masonry height < L/2: use full rectangular load from actual height
            w_masonry_s_kN_per_m = _GAMMA_MASONRY_kN_per_m3 * h_masonry_m
            w_masonry_u_kN_per_m = 1.2 * w_masonry_s_kN_per_m
            M_masonry_kNm = w_masonry_u_kN_per_m * L_m**2 / 8.0
            V_masonry_kN = w_masonry_u_kN_per_m * L_m / 2.0
            M_masonry_s_kNm = w_masonry_s_kN_per_m * L_m**2 / 8.0
            V_masonry_s_kN = w_masonry_s_kN_per_m * L_m / 2.0
            masonry_load_desc = (
                f"Rectangular masonry UDL: h_masonry={h_masonry_m:.3f}m < L/2={arching_threshold_m:.3f}m; "
                f"w_masonry={w_masonry_u_kN_per_m:.3f} kN/m (factored)"
            )

    # Total demand
    M_max_kNm = M_udl_kNm + M_masonry_kNm
    V_max_kN = V_udl_kN + V_masonry_kN

    # ---- Section properties + capacity ------------------------------------

    if mat == "steel":
        Fy = spec.fc_or_fy_MPa
        E_s = _E_STEEL_MPa
        # Rectangular section approximation (solid rectangle)
        I_x_mm4 = b_mm * h_mm**3 / 12.0
        S_x_mm3 = b_mm * h_mm**2 / 6.0
        A_web_mm2 = 0.50 * b_mm * h_mm  # conservative 50% web area
        phi_Mn_kNm = _PHI_B_STEEL * Fy * S_x_mm3 / 1e6   # N·mm → kN·m
        phi_Vn_kN = _PHI_V_STEEL * 0.6 * Fy * A_web_mm2 / 1e3  # N → kN
        # Deflection: elastic service UDL + masonry components
        # UDL: δ = 5wL⁴/(384EI)
        w_s_N_per_mm = w_s / 1000.0                        # kN/m → N/mm
        delta_udl = 5.0 * w_s_N_per_mm * L_mm**4 / (384.0 * E_s * I_x_mm4)
        # Masonry deflection component
        if h_masonry_mm > 0.0:
            if h_masonry_m >= arching_threshold_m:
                # Triangular (symmetric): Roark 9e §8 Table 8.1 case 5
                # δ_max = 0.01304 · W · L³ / (E·I)  where W = total resultant
                W_tri_s_N = V_masonry_s_kN * 2.0 * 1000.0  # kN → N (W = 2·R)
                delta_masonry = 0.01304 * W_tri_s_N * L_mm**3 / (E_s * I_x_mm4)
            else:
                # Low masonry: rectangular UDL — use actual masonry height
                w_ms_N_per_mm = (_GAMMA_MASONRY_kN_per_m3 * h_masonry_m) / 1000.0
                delta_masonry = 5.0 * w_ms_N_per_mm * L_mm**4 / (384.0 * E_s * I_x_mm4)
        else:
            delta_masonry = 0.0
        delta_max_mm = delta_udl + delta_masonry
        cap_desc = (
            f"Steel rectangle approx: Fy={Fy} MPa, b={b_mm} mm, h={h_mm} mm; "
            f"S_x={S_x_mm3:.4g} mm³, I_x={I_x_mm4:.4g} mm⁴; "
            f"φ·Mn={phi_Mn_kNm:.3f} kN·m, φ·Vn={phi_Vn_kN:.3f} kN. "
            "SCOPE: solid-rectangle approximation — actual W/L-shapes have higher S_x and I_x; "
            "LTB not checked; use arch_check_lateral_bracing separately."
        )

    elif mat == "reinforced_concrete":
        fc = spec.fc_or_fy_MPa       # f'c MPa
        fy = _FY_REBAR_MPa
        E_c = 4700.0 * math.sqrt(fc)  # ACI §19.2.2.1
        I_x_mm4 = b_mm * h_mm**3 / 12.0   # gross (uncracked; conservative for capacity)
        d_mm = h_mm - _COVER_PLUS_HALF_BAR_mm
        if d_mm <= 0.0:
            raise ValueError(
                f"lintel_depth_mm={h_mm} is too small; effective depth d = "
                f"{h_mm} − {_COVER_PLUS_HALF_BAR_mm} = {d_mm} mm ≤ 0."
            )
        As_mm2 = _RHO_MAX_RC * b_mm * d_mm
        a_mm = (As_mm2 * fy) / (0.85 * fc * b_mm)
        phi_Mn_Nmm = _PHI_B_RC * As_mm2 * fy * (d_mm - a_mm / 2.0)
        phi_Mn_kNm = phi_Mn_Nmm / 1e6
        # ACI §22.5.5.1 V_c = 0.17·λ·√f'c·b·d (λ=1 normal-weight)
        Vc_N = 0.17 * math.sqrt(fc) * b_mm * d_mm
        phi_Vn_kN = _PHI_V_RC * Vc_N / 1e3
        # Deflection: effective I ≈ 0.35·Ig (ACI §24.2.3.5 for beams with Mcr check omitted)
        I_eff_mm4 = 0.35 * I_x_mm4
        w_s_N_per_mm_rc = w_s / 1000.0
        delta_udl = 5.0 * w_s_N_per_mm_rc * L_mm**4 / (384.0 * E_c * I_eff_mm4)
        if h_masonry_mm > 0.0:
            if h_masonry_m >= arching_threshold_m:
                W_tri_s_N = V_masonry_s_kN * 2.0 * 1000.0
                delta_masonry = 0.01304 * W_tri_s_N * L_mm**3 / (E_c * I_eff_mm4)
            else:
                w_m_N_per_mm_rc = (_GAMMA_MASONRY_kN_per_m3 * h_masonry_m) / 1000.0
                delta_masonry = 5.0 * w_m_N_per_mm_rc * L_mm**4 / (384.0 * E_c * I_eff_mm4)
        else:
            delta_masonry = 0.0
        delta_max_mm = delta_udl + delta_masonry
        cap_desc = (
            f"RC ACI 318-19 §9: f'c={fc} MPa, fy={fy} MPa, b={b_mm} mm, d={d_mm:.1f} mm; "
            f"ρ_max={_RHO_MAX_RC}, As={As_mm2:.1f} mm², a={a_mm:.2f} mm; "
            f"φ·Mn={phi_Mn_kNm:.3f} kN·m; V_c={Vc_N/1e3:.3f} kN, φ·Vn={phi_Vn_kN:.3f} kN. "
            "SCOPE: ρ_max estimated (actual rebar layout governs); "
            "V_c = 0.17√f'c·b·d (no stirrups); deflection at 0.35·Ig."
        )

    else:  # reinforced_masonry
        fm = spec.fc_or_fy_MPa       # f'm MPa
        fy_s = _FY_REBAR_MPa
        E_m = 900.0 * fm             # TMS §4.2.2
        I_x_mm4 = b_mm * h_mm**3 / 12.0
        d_mm = h_mm - _COVER_PLUS_HALF_BAR_mm
        if d_mm <= 0.0:
            raise ValueError(
                f"lintel_depth_mm={h_mm} is too small; effective depth d = "
                f"{h_mm} − {_COVER_PLUS_HALF_BAR_mm} = {d_mm} mm ≤ 0."
            )
        As_mm2 = _RHO_MAX_RM * b_mm * d_mm
        # TMS §9.3.3.1: α_1 = 0.80 for f'm ≤ 28 MPa
        a_mm = (As_mm2 * fy_s) / (0.80 * fm * b_mm)
        phi_Mn_Nmm = _PHI_B_RM * As_mm2 * fy_s * (d_mm - a_mm / 2.0)
        phi_Mn_kNm = phi_Mn_Nmm / 1e6
        # TMS §9.3.4.1.2: V_n = A_n · √f'm / 3
        A_n_mm2 = b_mm * d_mm
        Vn_N = A_n_mm2 * math.sqrt(fm) / 3.0
        phi_Vn_kN = _PHI_V_RM * Vn_N / 1e3
        # Deflection: effective I ≈ 0.50·Ig (TMS §5.3.2.3 for RM lintels)
        I_eff_mm4 = 0.50 * I_x_mm4
        w_s_N_per_mm_rm = w_s / 1000.0
        delta_udl = 5.0 * w_s_N_per_mm_rm * L_mm**4 / (384.0 * E_m * I_eff_mm4)
        if h_masonry_mm > 0.0:
            if h_masonry_m >= arching_threshold_m:
                W_tri_s_N = V_masonry_s_kN * 2.0 * 1000.0
                delta_masonry = 0.01304 * W_tri_s_N * L_mm**3 / (E_m * I_eff_mm4)
            else:
                w_m_N_per_mm_rm = (_GAMMA_MASONRY_kN_per_m3 * h_masonry_m) / 1000.0
                delta_masonry = 5.0 * w_m_N_per_mm_rm * L_mm**4 / (384.0 * E_m * I_eff_mm4)
        else:
            delta_masonry = 0.0
        delta_max_mm = delta_udl + delta_masonry
        cap_desc = (
            f"RM TMS 402-22 §5: f'm={fm} MPa, fy={fy_s} MPa, b={b_mm} mm, d={d_mm:.1f} mm; "
            f"ρ_max={_RHO_MAX_RM}, As={As_mm2:.1f} mm², a={a_mm:.2f} mm; "
            f"φ·Mn={phi_Mn_kNm:.3f} kN·m; V_n={Vn_N/1e3:.3f} kN, φ·Vn={phi_Vn_kN:.3f} kN. "
            "SCOPE: ρ_max estimated; V_n = A_n·√f'm/3 (no shear reinforcement); "
            "deflection at 0.50·Ig."
        )

    # ---- Deflection limit --------------------------------------------------
    defl_limit = 360.0 if spec.floor_lintel else 240.0
    delta_allow_mm = L_mm / defl_limit
    deflection_ok = delta_max_mm <= delta_allow_mm

    # ---- DCR ---------------------------------------------------------------
    moment_dcr = M_max_kNm / phi_Mn_kNm if phi_Mn_kNm > 0.0 else float("inf")
    shear_dcr = V_max_kN / phi_Vn_kN if phi_Vn_kN > 0.0 else float("inf")
    adequate = (moment_dcr <= 1.0) and (shear_dcr <= 1.0) and deflection_ok

    # ---- Honest caveat -----------------------------------------------------
    honest_caveat = (
        f"ARCH-LINTEL-DESIGN [{mat.upper()}]: simple span L={L_m:.3f} m. "
        f"Loads (factored): w_u={w_u:.3f} kN/m (1.2·DL+1.6·LL); masonry: {masonry_load_desc}. "
        f"Demand: M_max={M_max_kNm:.3f} kN·m, V_max={V_max_kN:.3f} kN. "
        f"Capacity: {cap_desc} "
        f"Deflection (service): δ_max={delta_max_mm:.3f} mm ≤ L/{defl_limit:.0f}="
        f"{delta_allow_mm:.3f} mm → {'OK' if deflection_ok else 'FAIL'}. "
        f"DCR: M={moment_dcr:.3f}, V={shear_dcr:.3f}. Adequate={adequate}. "
        "SCOPE: Simple span ONLY — continuous-beam moment redistribution NOT modelled. "
        "Arching action: 45° triangle (TMS 402-22 Commentary §5.3.1; BIA TN-31B); "
        "no arching if course/mortar conditions preclude it. "
        "Steel: solid-rectangle section approximation; LTB not checked. "
        "RC: ρ_max=0.018 assumed; stirrups not modelled (V_c only). "
        "RM: ρ_max=0.010 assumed; shear rebar not modelled. "
        "Load factors: ASCE 7-16 §2.3.1 combo 2 (1.2D+1.6L) only — "
        "wind/seismic combinations must be checked separately. "
        "Refs: AISC Manual Table 3-23; AISC 360-22 §F1/§G2; "
        "ACI 318-19 §9.5/§9.6/§22.5; TMS 402-22 §5/§9.3; Roark 9e §8."
    )

    return LintelDesignReport(
        M_max_kNm=round(M_max_kNm, 6),
        V_max_kN=round(V_max_kN, 6),
        delta_max_mm=round(delta_max_mm, 6),
        phi_Mn_kNm=round(phi_Mn_kNm, 6),
        phi_Vn_kN=round(phi_Vn_kN, 6),
        moment_dcr=round(moment_dcr, 6),
        shear_dcr=round(shear_dcr, 6),
        deflection_ok=deflection_ok,
        adequate=adequate,
        honest_caveat=honest_caveat,
    )
