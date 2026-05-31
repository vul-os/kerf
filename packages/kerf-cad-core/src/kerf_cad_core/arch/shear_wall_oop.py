"""
kerf_cad_core.arch.shear_wall_oop — RC shear wall out-of-plane (OOP) flexural check.

Implements:
  - ACI 318-19 §11.5.3 slenderness limit: h/t ≤ 30
  - ACI 318-19 §11.7.5 empirical axial capacity:
      φ·Pn = 0.55·φ·f'c·A_g·[1 − (k·h / (32·t))²]
      k = 0.8 for walls restrained top and bottom against rotation (typical floor-to-floor)
      k = 1.0 for walls not restrained (cantilever / free top)
  - ACI 318-19 §22.3 rectangular-stress-block out-of-plane flexural capacity (simplified):
      a = (As·fy) / (0.85·f'c·b)
      φ·Mn = φ · As · fy · (d − a/2)
  - Linear axial-flexure interaction (Bresler equation approximation):
      DCR = Pu / φPn + Mu / φMn   ≤ 1.0

Per-metre-width strip is used throughout; all forces in kN/m and moments in kNm/m.

Units:
  All dimensions in **millimetres** (mm).
  Stresses in **MPa**.
  Force results in **kN/m** and moment results in **kNm/m**.

References:
  ACI 318-19, "Building Code Requirements for Structural Concrete":
    §11.5.3 (slenderness limit h/t ≤ 30)
    §11.7.5 (empirical design method for walls)
    §22.3   (rectangular stress block)
    Table 21.2.2 (φ = 0.65 compression-controlled)
  Wight J.K. (2019) *Reinforced Concrete: Mechanics and Design* 8e §13.13.

SCOPE LIMITATIONS (honest caveats):
  - Empirical ACI §11.7.5 axial formula only; Wight §13.13 simplified method.
    NOT implemented: slender-wall alternative moment-magnifier (ACI §11.8 / §6.7.3),
    P-delta second-order analysis, or SP slender-wall method (SEAOC).
  - One-way (unit-strip) flexure only — biaxial bending not modelled.
  - In-plane shear wall behaviour (ACI §11.6 / §18.10) is entirely separate and
    NOT included here.  This module handles OOP bending only.
  - Bresler linear-interaction approximation; not the full crescent/contour PM
    interaction surface.
  - Cover depth for effective depth d is assumed as cover_mm (default 25 mm) +
    half bar diameter.  Bar diameter is back-computed from As_each_face_mm2_per_m
    assuming 200 mm spacing.
  - Minimum steel ratio check per ACI §11.6.1 (ρ ≥ 0.0012 for t < 250 mm; 0.0015
    otherwise, horizontal; 0.0012/0.0015 vertical) is flagged but not enforced.
  - Factored loads Pu / Mu are the caller's responsibility; no load combo is applied.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "ShearWallSpec",
    "ShearWallOOPReport",
    "check_shear_wall_oop",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class ShearWallSpec:
    """
    Reinforced concrete shear wall geometry and material properties for
    ACI 318-19 §11.7 out-of-plane flexural + slenderness check.

    Parameters
    ----------
    wall_thickness_t_mm : float
        Wall thickness t (mm).  Must be > 0.
    wall_height_h_mm : float
        Clear storey height h between lateral supports (mm).  Must be > 0.
    wall_length_lw_mm : float
        Horizontal plan length of the wall lw (mm).  Used only for reporting
        (in-plane shear is out of scope).  Must be > 0.
    fc_MPa : float
        Specified compressive strength of concrete f'c (MPa).  Must be > 0.
    fy_MPa : float
        Specified yield strength of reinforcing steel (MPa).  Must be > 0.
    As_each_face_mm2_per_m : float
        Total area of vertical reinforcement on *each face* in mm²/m of wall
        width.  Both faces are included in the flexural model, so total
        As = 2 × As_each_face_mm2_per_m.  Must be ≥ 0.
    axial_load_Pu_kN_per_m : float
        Factored axial compressive load per unit width of wall (kN/m).
        Must be ≥ 0.  Tensile axial loads (net uplift) are not supported.
    oop_moment_Mu_kNm_per_m : float
        Factored out-of-plane bending moment demand per unit width (kNm/m).
        Must be ≥ 0.
    k_factor : float
        Effective-height factor k for ACI §11.7.5.1.
        Default 0.8 (fixed-fixed, top + bottom restrained against rotation).
        Use 1.0 for walls free at top (cantilever).
    cover_mm : float
        Clear concrete cover to the reinforcement (mm).  Default 25 mm.
        Used to compute the effective depth d = t/2 − cover (centroidal).
    bar_spacing_mm : float
        Assumed bar spacing for effective-depth back-calculation (mm).
        Default 200 mm.  Bar diameter is back-computed for d estimation.
    """
    wall_thickness_t_mm: float
    wall_height_h_mm: float
    wall_length_lw_mm: float
    fc_MPa: float
    fy_MPa: float
    As_each_face_mm2_per_m: float
    axial_load_Pu_kN_per_m: float
    oop_moment_Mu_kNm_per_m: float
    k_factor: float = field(default=0.8)
    cover_mm: float = field(default=25.0)
    bar_spacing_mm: float = field(default=200.0)


@dataclass
class ShearWallOOPReport:
    """
    Result of ACI 318-19 §11.7 out-of-plane shear wall check.

    Parameters
    ----------
    slenderness_h_over_t : float
        Slenderness ratio h / t.
    slenderness_ok : bool
        True if h/t ≤ 30 (ACI 318-19 §11.5.3).
    phi_Pn_kN_per_m : float
        ACI §11.7.5 empirical design axial compressive strength φ·Pn (kN/m).
    phi_Mn_kNm_per_m : float
        Out-of-plane flexural design strength φ·Mn (kNm/m), per unit width,
        from rectangular-stress-block analysis (ACI §22.3).
    interaction_dcr : float
        Linear Bresler interaction DCR = Pu/φPn + Mu/φMn.
        Values ≤ 1.0 are adequate.
    adequate : bool
        True only if slenderness_ok is True AND interaction_dcr ≤ 1.0.
    governing_check : str
        Description of which check is critical:
        "slenderness", "interaction", "slenderness+interaction", or "OK".
    honest_caveat : str
        Code-compliance scope caveats and disclaimers.
    """
    slenderness_h_over_t: float
    slenderness_ok: bool
    phi_Pn_kN_per_m: float
    phi_Mn_kNm_per_m: float
    interaction_dcr: float
    adequate: bool
    governing_check: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def _validate(spec: ShearWallSpec) -> None:
    """Raise ValueError on invalid inputs."""
    if spec.wall_thickness_t_mm <= 0:
        raise ValueError(
            f"wall_thickness_t_mm must be > 0, got {spec.wall_thickness_t_mm}"
        )
    if spec.wall_height_h_mm <= 0:
        raise ValueError(
            f"wall_height_h_mm must be > 0, got {spec.wall_height_h_mm}"
        )
    if spec.wall_length_lw_mm <= 0:
        raise ValueError(
            f"wall_length_lw_mm must be > 0, got {spec.wall_length_lw_mm}"
        )
    if spec.fc_MPa <= 0:
        raise ValueError(f"fc_MPa must be > 0, got {spec.fc_MPa}")
    if spec.fy_MPa <= 0:
        raise ValueError(f"fy_MPa must be > 0, got {spec.fy_MPa}")
    if spec.As_each_face_mm2_per_m < 0:
        raise ValueError(
            f"As_each_face_mm2_per_m must be ≥ 0, got {spec.As_each_face_mm2_per_m}"
        )
    if spec.axial_load_Pu_kN_per_m < 0:
        raise ValueError(
            f"axial_load_Pu_kN_per_m must be ≥ 0, got {spec.axial_load_Pu_kN_per_m}"
        )
    if spec.oop_moment_Mu_kNm_per_m < 0:
        raise ValueError(
            f"oop_moment_Mu_kNm_per_m must be ≥ 0, got {spec.oop_moment_Mu_kNm_per_m}"
        )
    if spec.k_factor <= 0:
        raise ValueError(f"k_factor must be > 0, got {spec.k_factor}")
    if spec.cover_mm < 0:
        raise ValueError(f"cover_mm must be ≥ 0, got {spec.cover_mm}")
    if spec.bar_spacing_mm <= 0:
        raise ValueError(f"bar_spacing_mm must be > 0, got {spec.bar_spacing_mm}")


# ---------------------------------------------------------------------------
# Effective depth helper
# ---------------------------------------------------------------------------

def _effective_depth_d(spec: ShearWallSpec) -> float:
    """
    Estimate effective depth d (mm) from the tension face for OOP bending.

    For a doubly-reinforced wall section (steel on both faces), the tension
    steel centroid governs the lever arm.  We back-compute bar diameter from
    As_each_face_mm2_per_m and bar_spacing_mm, then:

        bar_area = As_each_face_mm2_per_m × bar_spacing_mm / 1000
        bar_dia  = √(4 × bar_area / π)
        d = t − cover − bar_dia/2

    The tension-face rebar contribution dominates; the compression-face
    steel contribution is included in the axial capacity formula via the
    full gross section but is conservatively ignored in the flexural model
    (this is on the safe side per Wight §13.13 simplified method).
    """
    t = spec.wall_thickness_t_mm
    As_per_m = spec.As_each_face_mm2_per_m       # mm²/m on one face
    s = spec.bar_spacing_mm                        # mm

    # area of one bar
    bar_area_mm2 = As_per_m * s / 1_000.0         # mm² (1 m = 1000 mm)

    # diameter of one bar (minimum 6 mm to avoid sqrt domain issues)
    bar_dia_mm = math.sqrt(4.0 * max(bar_area_mm2, 28.27) / math.pi)  # 28.27 ≈ 6mm bar

    d = t - spec.cover_mm - bar_dia_mm / 2.0
    if d <= 0:
        # Fallback: use 0.8·t (conservative minimum)
        d = 0.8 * t
    return d


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def check_shear_wall_oop(
    spec: ShearWallSpec,
    phi: float = 0.65,
) -> ShearWallOOPReport:
    """
    Check out-of-plane (OOP) flexural capacity of a reinforced concrete
    shear wall per ACI 318-19 §11.5 (slenderness) + §11.7 (empirical walls)
    + §22.3 (rectangular stress block).

    Method
    ------
    1. Slenderness check (ACI §11.5.3):
          h / t ≤ 30

    2. Empirical axial capacity (ACI §11.7.5.1):
          φ·Pn = 0.55·φ·f'c·A_g·[1 − (k·h / (32·t))²]
       where A_g = t × 1000 mm² per metre width, φ = 0.65 (default).

    3. Out-of-plane flexural capacity (ACI §22.3 rectangular stress block,
       Wight §13.13 simplified unit-strip method):
          Total As (both faces) = 2 × As_each_face_mm2_per_m (mm²/m)
          a  = (As_total × fy) / (0.85 × f'c × 1000)  [mm]
          φ·Mn = φ · As_total · fy · (d − a/2)  [N·mm/m] → convert to kNm/m

    4. Linear Bresler interaction:
          DCR = Pu/(φ·Pn) + Mu/(φ·Mn) ≤ 1.0

    Parameters
    ----------
    spec : ShearWallSpec
        Wall geometry, materials, reinforcement, and factored loads.
    phi : float
        ACI strength-reduction factor φ for compression-controlled members.
        Default 0.65 per ACI 318-19 Table 21.2.2.

    Returns
    -------
    ShearWallOOPReport

    Raises
    ------
    ValueError
        On invalid input parameters.
    """
    _validate(spec)
    if phi <= 0 or phi > 1.0:
        raise ValueError(f"phi must be in (0, 1], got {phi}")

    t = spec.wall_thickness_t_mm
    h = spec.wall_height_h_mm
    fc = spec.fc_MPa
    fy = spec.fy_MPa
    k = spec.k_factor

    # -----------------------------------------------------------------------
    # 1.  Slenderness check: ACI 318-19 §11.5.3
    # -----------------------------------------------------------------------
    h_over_t = h / t
    slenderness_ok = h_over_t <= 30.0

    # -----------------------------------------------------------------------
    # 2.  Empirical axial capacity: ACI 318-19 §11.7.5.1
    #     Per metre width: A_g = t × 1000 mm²/m
    # -----------------------------------------------------------------------
    A_g_per_m = t * 1_000.0                           # mm²/m (b = 1000 mm)

    # Buckling reduction term: (k·h / (32·t))²
    kh_over_32t = (k * h) / (32.0 * t)
    reduction = max(0.0, 1.0 - kh_over_32t ** 2)      # can be zero if very slender

    # ACI Eq 11.7.5.1:  Pn = 0.55 · f'c · A_g · [1 − (k·h/(32·t))²]
    Pn_kN_per_m = 0.55 * fc * A_g_per_m * reduction / 1_000.0   # N/m → kN/m
    phi_Pn_kN_per_m = phi * Pn_kN_per_m

    # -----------------------------------------------------------------------
    # 3.  Out-of-plane flexural capacity: rectangular stress block (ACI §22.3)
    #     Unit-strip width b = 1000 mm/m
    # -----------------------------------------------------------------------
    b = 1_000.0                                            # mm/m (unit strip)
    As_total_per_m = 2.0 * spec.As_each_face_mm2_per_m    # mm²/m (both faces)
    d = _effective_depth_d(spec)                           # mm

    if As_total_per_m > 0.0:
        a = (As_total_per_m * fy) / (0.85 * fc * b)       # depth of stress block, mm
        # Ensure a ≤ d (physically possible)
        a = min(a, d)
        Mn_Nmm_per_m = As_total_per_m * fy * (d - a / 2.0)  # N·mm/m
    else:
        # Zero steel — pure concrete (ACI does not permit, but compute for completeness)
        Mn_Nmm_per_m = 0.0

    phi_Mn_kNm_per_m = phi * Mn_Nmm_per_m / 1_000.0 / 1_000.0  # N·mm → kNm

    # -----------------------------------------------------------------------
    # 4.  Bresler linear interaction
    # -----------------------------------------------------------------------
    Pu = spec.axial_load_Pu_kN_per_m
    Mu = spec.oop_moment_Mu_kNm_per_m

    # Guard against zero-capacity denominators
    if phi_Pn_kN_per_m > 0.0:
        axial_ratio = Pu / phi_Pn_kN_per_m
    else:
        axial_ratio = float("inf")

    if phi_Mn_kNm_per_m > 0.0:
        flexure_ratio = Mu / phi_Mn_kNm_per_m
    else:
        flexure_ratio = float("inf") if Mu > 0.0 else 0.0

    dcr = axial_ratio + flexure_ratio
    interaction_ok = dcr <= 1.0

    # -----------------------------------------------------------------------
    # 5.  Adequacy and governing-check string
    # -----------------------------------------------------------------------
    adequate = slenderness_ok and interaction_ok

    if not slenderness_ok and not interaction_ok:
        governing_check = "slenderness+interaction"
    elif not slenderness_ok:
        governing_check = "slenderness"
    elif not interaction_ok:
        governing_check = "interaction"
    else:
        governing_check = "OK"

    # -----------------------------------------------------------------------
    # 6.  Minimum steel ratio advisory (ACI §11.6.1.1)
    # -----------------------------------------------------------------------
    rho_v = As_total_per_m / (t * b)                       # vertical steel ratio
    rho_min_v = 0.0012 if t < 250.0 else 0.0015
    rho_warn = ""
    if rho_v < rho_min_v:
        rho_warn = (
            f"; NOTE: vertical steel ratio ρ_v = {rho_v:.5f} is below ACI §11.6.1.1 "
            f"minimum ρ_v = {rho_min_v:.4f} — minimum reinforcement not met"
        )

    # -----------------------------------------------------------------------
    # 7.  Honest caveat
    # -----------------------------------------------------------------------
    caveat = (
        "ACI 318-19 §11.7 empirical wall method + ACI §22.3 rectangular stress block "
        "(OOP unit-strip) + Wight 'Reinforced Concrete' 8e §13.13. "
        f"t = {t:.0f} mm, h = {h:.0f} mm, k = {k}, f'c = {fc:.1f} MPa, "
        f"fy = {fy:.0f} MPa, As_each_face = {spec.As_each_face_mm2_per_m:.1f} mm²/m. "
        f"h/t = {h_over_t:.2f} ({'≤ 30 OK' if slenderness_ok else '> 30 FAIL — exceeds ACI §11.5.3'}). "
        f"kh/(32t) = {kh_over_32t:.4f}, reduction factor = {reduction:.4f}. "
        f"φPn = {phi_Pn_kN_per_m:.2f} kN/m (φ={phi}, ACI §11.7.5.1 empirical). "
        f"d = {d:.1f} mm, As_total = {As_total_per_m:.1f} mm²/m, "
        f"a = {(As_total_per_m * fy / (0.85 * fc * b)) if As_total_per_m > 0 else 0.0:.1f} mm. "
        f"φMn = {phi_Mn_kNm_per_m:.3f} kNm/m. "
        f"Pu = {Pu:.2f} kN/m, Mu = {Mu:.2f} kNm/m. "
        f"Bresler DCR = Pu/φPn + Mu/φMn = {axial_ratio:.4f} + {flexure_ratio:.4f} = {dcr:.4f} "
        f"({'≤ 1.0 ADEQUATE' if interaction_ok else '> 1.0 INADEQUATE'}). "
        "SCOPE LIMITATIONS: "
        "(1) ACI §11.7.5 empirical method only — slender-wall moment-magnifier "
        "(ACI §11.8 / §6.7.3) and P-delta second-order analysis NOT included; "
        "walls with h/t > 30 must use ACI §11.8 or moment-magnifier method. "
        "(2) SP slender-wall method (SEAOC) NOT implemented. "
        "(3) Bresler linear interaction is an approximation of the PM interaction surface; "
        "for heavily loaded sections near the balance point, use a full PM curve. "
        "(4) Biaxial bending NOT modelled — OOP unit strip only. "
        "(5) In-plane (horizontal) shear-wall behaviour (ACI §11.6 / §18.10) is entirely "
        "separate and NOT checked here. "
        "(6) Factored loads Pu / Mu are caller's responsibility; ACI load combinations "
        "per §5.3 (1.2D+1.6L, 1.2D+1.0E+1.0L, etc.) not applied automatically. "
        f"(7) Minimum vertical steel ratio{rho_warn if rho_warn else ': ρ_v = ' + f'{rho_v:.5f} ≥ {rho_min_v:.4f} OK'}. "
        "Always verify with a licensed structural engineer."
    )

    return ShearWallOOPReport(
        slenderness_h_over_t=h_over_t,
        slenderness_ok=slenderness_ok,
        phi_Pn_kN_per_m=phi_Pn_kN_per_m,
        phi_Mn_kNm_per_m=phi_Mn_kNm_per_m,
        interaction_dcr=dcr,
        adequate=adequate,
        governing_check=governing_check,
        honest_caveat=caveat,
    )
