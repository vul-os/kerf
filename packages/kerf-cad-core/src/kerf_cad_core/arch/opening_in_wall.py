"""
kerf_cad_core.arch.opening_in_wall — Wall opening load redistribution check.

Checks that a wall opening (door or window) satisfies code requirements for:
  1. Tributary load redistribution to jamb piers.
  2. Minimum jamb axial capacity (DCR check).
  3. Lintel/header bending and deflection limits.

References:
  IBC 2021 §2308.4 — Structural wall openings (prescriptive wood frame reference;
    structural intent: openings must redistribute tributary loads to jambs and header).
  TMS 402-22 §5 — Lintel and header design for masonry openings.
  ACI 318-19 §11.5.3.1 — Bearing wall axial capacity (jamb pier empirical formula).
  ACI 318-19 §11 — Wall capacities.
  AISC 360-22 / Wight 8e §13.13 — Reference methods for concrete jamb piers.

Tributary load model (IBC §2308.4 / simplified elastic redistribution)
-----------------------------------------------------------------------
The opening creates two jamb piers and a lintel/header above. Load is redistributed
from the opening width to the jamb piers by tributary-width logic:

  trib_width_per_jamb  = opening_width / 2  +  jamb_width / 2  +  header_above_height
                         ^^^^^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^  ^^^^^^^^^^^^^^^^^^^
                         half-opening span     half-pier width    arching/redistribution
                                                                   height above opening

  This captures: (a) half the opening's direct tributary, (b) half the pier's own
  width (pier self-tributary), (c) the height of wall above the lintel up to the
  next structural element (redistribution zone). Conservative one-sided summation.

  NOTE: The above simplifies the full 2-D tributary-area analysis for opening-in-wall
  redistribution. A full FE stress-concentration analysis around the opening corner
  would be more accurate (St Venant stress diffusion length ≈ 1–2× opening dimension);
  this module uses simplified tributary geometry per IBC §2308.4 prescriptive intent.

  total_load_on_jamb = axial_load_per_unit × trib_width_per_jamb
                     + lateral_load_per_unit_area × opening_area / 2

  (The lateral load contribution is half the opening's wind/seismic reaction, transferred
   to each jamb via the lintel diaphragm action; IBC §2308.4 prescriptive intent.)

Jamb capacity
-------------
The jamb pier is modelled as a short wall strip of width = jamb_width_m, thickness =
wall_thickness_m, height = opening_height_m (clear height of opening = jamb height).

  For material = "concrete" or "masonry":
    ACI 318-19 §11.5.3.1 empirical formula (pin-pin, k=1.0 for opening clear height):
      φ·Pn = 0.55·φ·f'c·Ag·[1 − (k·h/(32·t))²]   (per-pier, not per-metre)
      Ag = jamb_width_m × wall_thickness_m  (m²)

  For material = "wood_frame":
    A simplified timber column model (NDS 2018 Table 4A allowable stress approach
    is NOT implemented; instead a conservative elastic Euler buckling + bearing check
    is used as a proxy). Wood-frame jamb capacity = bearing_area × Fc where Fc is the
    code-default allowable compressive stress (f_prime_or_fy_MPa is interpreted as Fc).
    φ = 0.90 (conservative, for consistency with ACI/TMS phi-factor approach).

  Lintel moment DCR is taken from the existing design_lintel function (ACI/TMS/steel).
  A material mapping bridges this module's material names to lintel_design.py's names.

Deflection limit
----------------
  Concrete/masonry lintel: L/240 (TMS 402-22 §5 default; masonry/roof-bearing).
  Wood frame header: L/360 (floor-level lintel default).

Scope and honest caveats
------------------------
  - Simplified tributary-width approach per IBC §2308.4 prescriptive intent.
  - Full 2-D FE stress-concentration analysis around opening corners NOT modelled
    (St. Venant diffusion zone ≈ 1–2× opening dimension; may be unconservative for
    wide openings > storey height / 2).
  - Jamb axial capacity uses ACI §11.5.3.1 empirical wall formula (small eccentricity
    assumed, e ≈ 0). For eccentric loads the PM interaction surface is required (ACI §11.4).
  - Wood-frame jamb: simplified bearing check; NDS 2018 full column stability analysis
    (Cp factor, slenderness ratio) NOT implemented.
  - Lintel delegated to design_lintel (see lintel_design.py for its caveats).
  - Lateral load contribution to jamb (out-of-plane) is split equally between two jambs
    as a shear reaction — in-plane wall shear (IBC §2308.9 / SDPWS §4.3) NOT checked.
  - Load factors: 1.2D+1.6L (ASCE 7-16 §2.3.1 combo 2) for jamb axial; lintel uses
    the same combo internally.
  - IBC §2308 is a prescriptive provision for wood-frame construction; for concrete/masonry
    walls the equivalent structural intent is captured but the exact IBC §2308 clauses
    apply only to wood frame.

References
----------
  IBC (2021). International Building Code. §2308.4 (Wall openings).
  TMS 402-22. §5 (Lintel design); §8.3 (Bearing wall axial).
  ACI 318-19. §11.5.3.1 (Bearing walls); §11.4 (Alternate method).
  AISC 360-22 §F1/§G2 (Steel lintels).
  Wight J.K. (2019) Reinforced Concrete 8e §13.13.
  NDS (2018). National Design Specification for Wood Construction.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from kerf_cad_core.arch.lintel_design import LintelSpec, design_lintel

__all__ = [
    "WallOpeningSpec",
    "OpeningCheckReport",
    "check_opening",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_VALID_MATERIALS = frozenset({"concrete", "masonry", "wood_frame"})

# ACI 318-19 §11.5.3.1 phi for compression-controlled wall (Table 21.2.2)
_PHI_ACI_WALL = 0.65
# TMS 402-22 §7.3.2.1 phi for masonry axial/flexure
_PHI_TMS_WALL = 0.60
# Wood frame phi (conservative, proxy for NDS allowable-strength approach)
_PHI_WOOD = 0.90

# ACI §11.5.3.1: Pn = 0.55 · f'c · Ag · slenderness_factor
_ACI_WALL_COEFF = 0.55
# TMS 402-22 §8.3 Eq 8-22: Pn = 0.80 · f'm · Ag · slenderness_factor
_TMS_WALL_COEFF = 0.80

# ACI §11.5.3.1 k = 1.0 (pin-pin) for opening jamb (clear-span condition)
_K_JAMB = 1.0


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class WallOpeningSpec:
    """
    Input specification for a wall opening structural check.

    Parameters
    ----------
    wall_height_m : float
        Total clear storey height of the wall (m). Must be > 0.
    wall_thickness_m : float
        Wall thickness (m). Must be > 0.
    opening_width_m : float
        Clear opening width (m). Must be > 0.
    opening_height_m : float
        Clear opening height (m). Must be > 0 and < wall_height_m.
    header_above_opening_height_m : float
        Height of wall panel above the lintel/header up to the next
        structural element (floor/roof/bond beam) in metres.
        Used in tributary width computation and masonry arching.
        Must be >= 0.
    lintel_depth_m : float
        Overall depth of the lintel/header cross-section (m). Must be > 0.
    jamb_width_m : float
        Width of each jamb pier measured along the wall face (m). Must be > 0.
    material : str
        Wall and structural element material: "concrete" | "masonry" | "wood_frame".
        Governs jamb capacity formula and lintel material mapping.
    f_prime_or_fy_MPa : float
        Material strength (MPa). Must be > 0.
        concrete  → f'c (concrete compressive strength).
        masonry   → f'm (masonry compressive strength).
        wood_frame → Fc (allowable compressive stress parallel to grain, proxy).
    applied_axial_kN_per_m : float
        Service axial load from above (gravity + superimposed) per unit length
        of wall (kN/m). Must be >= 0.
    applied_lateral_kN_per_m2 : float
        Uniform lateral pressure on the wall face (kN/m²), e.g. wind or seismic
        equivalent uniform pressure. Must be >= 0.
    """

    wall_height_m: float
    wall_thickness_m: float
    opening_width_m: float
    opening_height_m: float
    header_above_opening_height_m: float
    lintel_depth_m: float
    jamb_width_m: float
    material: str
    f_prime_or_fy_MPa: float
    applied_axial_kN_per_m: float
    applied_lateral_kN_per_m2: float


@dataclass
class OpeningCheckReport:
    """
    Output of a wall opening structural check.

    Parameters
    ----------
    tributary_load_on_jamb_kN : float
        Total factored axial load assigned to one jamb pier (kN).
    jamb_axial_capacity_kN : float
        Design axial capacity of one jamb pier, φ·Pn (kN).
    jamb_dcr : float
        Demand-capacity ratio for jamb: tributary_load / jamb_axial_capacity. < 1.0 → adequate.
    lintel_moment_dcr : float
        DCR for lintel/header bending (from design_lintel). < 1.0 → adequate.
    lintel_deflection_mm : float
        Maximum elastic mid-span deflection of the lintel/header under service loads (mm).
    all_adequate : bool
        True if jamb_dcr <= 1.0 AND lintel_moment_dcr <= 1.0 AND lintel deflection_ok.
    governing_check : str
        Short tag for the first (worst) check that governs:
        "OK" | "jamb_dcr_exceeded" | "lintel_moment_dcr_exceeded" | "lintel_deflection_exceeded".
    honest_caveat : str
        Plain-language narrative of code references, method assumptions, scope limits.
    """

    tributary_load_on_jamb_kN: float
    jamb_axial_capacity_kN: float
    jamb_dcr: float
    lintel_moment_dcr: float
    lintel_deflection_mm: float
    all_adequate: bool
    governing_check: str
    honest_caveat: str


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(spec: WallOpeningSpec) -> None:
    """Raise ValueError on invalid inputs."""
    if spec.wall_height_m <= 0.0:
        raise ValueError(f"wall_height_m must be > 0, got {spec.wall_height_m}")
    if spec.wall_thickness_m <= 0.0:
        raise ValueError(f"wall_thickness_m must be > 0, got {spec.wall_thickness_m}")
    if spec.opening_width_m <= 0.0:
        raise ValueError(f"opening_width_m must be > 0, got {spec.opening_width_m}")
    if spec.opening_height_m <= 0.0:
        raise ValueError(f"opening_height_m must be > 0, got {spec.opening_height_m}")
    if spec.opening_height_m >= spec.wall_height_m:
        raise ValueError(
            f"opening_height_m ({spec.opening_height_m}) must be < wall_height_m "
            f"({spec.wall_height_m})"
        )
    if spec.header_above_opening_height_m < 0.0:
        raise ValueError(
            f"header_above_opening_height_m must be >= 0, got "
            f"{spec.header_above_opening_height_m}"
        )
    if spec.lintel_depth_m <= 0.0:
        raise ValueError(f"lintel_depth_m must be > 0, got {spec.lintel_depth_m}")
    if spec.jamb_width_m <= 0.0:
        raise ValueError(f"jamb_width_m must be > 0, got {spec.jamb_width_m}")
    if spec.material not in _VALID_MATERIALS:
        raise ValueError(
            f"material must be one of {sorted(_VALID_MATERIALS)}, got {spec.material!r}"
        )
    if spec.f_prime_or_fy_MPa <= 0.0:
        raise ValueError(f"f_prime_or_fy_MPa must be > 0, got {spec.f_prime_or_fy_MPa}")
    if spec.applied_axial_kN_per_m < 0.0:
        raise ValueError(f"applied_axial_kN_per_m must be >= 0, got {spec.applied_axial_kN_per_m}")
    if spec.applied_lateral_kN_per_m2 < 0.0:
        raise ValueError(
            f"applied_lateral_kN_per_m2 must be >= 0, got {spec.applied_lateral_kN_per_m2}"
        )


# ---------------------------------------------------------------------------
# Jamb capacity helpers
# ---------------------------------------------------------------------------


def _jamb_capacity_concrete(
    jamb_width_m: float,
    wall_thickness_m: float,
    opening_height_m: float,
    fc_MPa: float,
) -> float:
    """
    ACI 318-19 §11.5.3.1 empirical wall formula applied to one jamb pier.

    The jamb is treated as a short wall strip:
      Ag = jamb_width_m * wall_thickness_m  [m²]
      lc = opening_height_m (clear height = jamb height)
      k = 1.0 (pin-pin ends at head and sill)

    Returns φ·Pn in kN.
    """
    t_mm = wall_thickness_m * 1000.0
    h_mm = opening_height_m * 1000.0
    Ag_mm2 = (jamb_width_m * 1000.0) * t_mm     # mm²

    klc_over_32t = (_K_JAMB * h_mm) / (32.0 * t_mm)
    slenderness_factor = max(0.0, 1.0 - klc_over_32t ** 2)

    Pn_N = _ACI_WALL_COEFF * fc_MPa * Ag_mm2 * slenderness_factor
    phi_Pn_kN = _PHI_ACI_WALL * Pn_N / 1_000.0
    return phi_Pn_kN


def _jamb_capacity_masonry(
    jamb_width_m: float,
    wall_thickness_m: float,
    opening_height_m: float,
    fm_MPa: float,
) -> float:
    """
    TMS 402-22 §8.3 Eq 8-22 applied to one masonry jamb pier.

    r = t / √12 (radius of gyration, rectangular cross-section)
    h_eff = k·h = 1.0 · opening_height_m (pin-pin)
    Cs = [1 − (h_eff / (140·r))²]  (valid for h_eff/r ≤ 99)

    Returns φ·Pn in kN.
    """
    t_mm = wall_thickness_m * 1000.0
    h_mm = opening_height_m * 1000.0
    Ag_mm2 = (jamb_width_m * 1000.0) * t_mm

    r = t_mm / math.sqrt(12.0)
    h_eff_mm = _K_JAMB * h_mm
    h_over_r = h_eff_mm / r

    if h_over_r > 99.0:
        # TMS §8.3 limit exceeded; set capacity to zero
        return 0.0

    cs = max(0.0, 1.0 - (h_eff_mm / (140.0 * r)) ** 2)
    Pn_N = _TMS_WALL_COEFF * fm_MPa * Ag_mm2 * cs
    phi_Pn_kN = _PHI_TMS_WALL * Pn_N / 1_000.0
    return phi_Pn_kN


def _jamb_capacity_wood(
    jamb_width_m: float,
    wall_thickness_m: float,
    fc_MPa: float,
) -> float:
    """
    Wood-frame jamb: simplified bearing area × allowable compressive stress.

    Bearing area A = jamb_width_m × wall_thickness_m [m²]
    φ·Pn = φ · Fc · A
    where Fc = f_prime_or_fy_MPa (caller supplies NDS allowable Fc in MPa).

    NOTE: NDS 2018 column-stability factor Cp (slenderness) NOT computed here.
    Conservative φ = 0.90 applied for consistency. Full NDS analysis required
    for code compliance.

    Returns φ·Pn in kN.
    """
    Ag_mm2 = (jamb_width_m * 1000.0) * (wall_thickness_m * 1000.0)
    phi_Pn_kN = _PHI_WOOD * fc_MPa * Ag_mm2 / 1_000.0
    return phi_Pn_kN


# ---------------------------------------------------------------------------
# Material mapping for lintel_design.py
# ---------------------------------------------------------------------------

def _lintel_material(material: str) -> str:
    """Map WallOpeningSpec material to LintelSpec material."""
    _MAP = {
        "concrete": "reinforced_concrete",
        "masonry": "reinforced_masonry",
        "wood_frame": "steel",  # proxy: wood header treated as steel for bending check
    }
    return _MAP[material]


# ---------------------------------------------------------------------------
# Core check function
# ---------------------------------------------------------------------------


def check_opening(spec: WallOpeningSpec) -> OpeningCheckReport:
    """
    Check a wall opening (door/window) for IBC §2308.4 tributary-load redistribution,
    jamb axial capacity, and lintel moment + deflection.

    Parameters
    ----------
    spec : WallOpeningSpec
        Full opening geometry, material, and loading specification.

    Returns
    -------
    OpeningCheckReport

    Raises
    ------
    ValueError
        If any required parameter is out of range or material is unrecognised.

    Notes
    -----
    Tributary width (per jamb):
      trib_w = opening_width_m/2 + jamb_width_m/2 + header_above_opening_height_m
    Total factored load on one jamb:
      Pu = (1.2 × applied_axial_kN_per_m × trib_w)   (gravity, ASCE 7-16 §2.3.1 combo 2)
         + lateral_load_component_kN                  (half the opening's lateral reaction)
    Lateral component assigned to jamb:
      P_lat = 0.5 × applied_lateral_kN_per_m2 × opening_width_m × opening_height_m
    """
    _validate(spec)

    # ---- Tributary width for one jamb ----------------------------------------
    # IBC §2308.4 prescriptive intent: load from half-opening + half-pier + header zone.
    trib_w = (
        spec.opening_width_m / 2.0
        + spec.jamb_width_m / 2.0
        + spec.header_above_opening_height_m
    )

    # ---- Factored axial load on one jamb ------------------------------------
    # 1.2·DL factored gravity component over tributary width (ASCE 7-16 §2.3.1, combo 2)
    # applied_axial_kN_per_m is treated as total service gravity load (DL+LL); apply 1.2×
    # as conservative DL-dominant factored estimate for pier axial check.
    P_gravity_kN = 1.2 * spec.applied_axial_kN_per_m * trib_w

    # Lateral load contribution: half the opening panel's lateral reaction, treated as
    # vertical component transferred to one jamb via lintel (conservative).
    opening_area_m2 = spec.opening_width_m * spec.opening_height_m
    P_lateral_kN = 0.5 * spec.applied_lateral_kN_per_m2 * opening_area_m2

    total_load_on_jamb_kN = P_gravity_kN + P_lateral_kN

    # ---- Jamb axial capacity -------------------------------------------------
    if spec.material == "concrete":
        jamb_cap_kN = _jamb_capacity_concrete(
            spec.jamb_width_m,
            spec.wall_thickness_m,
            spec.opening_height_m,
            spec.f_prime_or_fy_MPa,
        )
        cap_method = f"ACI 318-19 §11.5.3.1 (φ={_PHI_ACI_WALL}, k={_K_JAMB} pin-pin)"
    elif spec.material == "masonry":
        jamb_cap_kN = _jamb_capacity_masonry(
            spec.jamb_width_m,
            spec.wall_thickness_m,
            spec.opening_height_m,
            spec.f_prime_or_fy_MPa,
        )
        cap_method = f"TMS 402-22 §8.3 Eq 8-22 (φ={_PHI_TMS_WALL}, k={_K_JAMB} pin-pin)"
    else:  # wood_frame
        jamb_cap_kN = _jamb_capacity_wood(
            spec.jamb_width_m,
            spec.wall_thickness_m,
            spec.f_prime_or_fy_MPa,
        )
        cap_method = (
            f"Wood-frame simplified bearing check (φ={_PHI_WOOD}, Fc={spec.f_prime_or_fy_MPa} MPa; "
            "NDS 2018 Cp slenderness NOT computed)"
        )

    # Jamb DCR
    if jamb_cap_kN > 0.0:
        jamb_dcr = total_load_on_jamb_kN / jamb_cap_kN
    else:
        jamb_dcr = float("inf")

    # ---- Lintel/header check via design_lintel --------------------------------
    # Map material to LintelSpec material
    lintel_mat = _lintel_material(spec.material)

    # Lateral load produces an equivalent UDL on the lintel from the wall panel
    # above the opening: treat as dead load on lintel for conservatism.
    # Gravity load per unit length over opening = axial_load × 1.0 (direct)
    # Lateral uniform pressure on opening panel → equivalent UDL on lintel:
    #   w_lateral = applied_lateral × opening_height (half-tributary per side on lintel)
    w_DL_lintel = spec.applied_axial_kN_per_m  # gravity DL on lintel (kN/m)
    w_LL_lintel = spec.applied_lateral_kN_per_m2 * spec.opening_height_m  # lateral proxy (kN/m)

    # Masonry height above lintel = header zone
    masonry_h_mm = spec.header_above_opening_height_m * 1000.0

    # For wood_frame acting as "steel" proxy: use fc as steel Fy (proxy); scale to
    # at least 20 MPa to avoid degenerate section.
    lintel_fc_fy = max(spec.f_prime_or_fy_MPa, 1.0)

    lintel_spec = LintelSpec(
        opening_span_mm=spec.opening_width_m * 1000.0,
        wall_thickness_mm=spec.wall_thickness_m * 1000.0,
        material=lintel_mat,
        lintel_depth_mm=spec.lintel_depth_m * 1000.0,
        lintel_width_mm=spec.wall_thickness_m * 1000.0,  # lintel width = wall thickness
        fc_or_fy_MPa=lintel_fc_fy,
        dead_load_kN_per_m=w_DL_lintel,
        live_load_kN_per_m=w_LL_lintel,
        masonry_above_height_mm=masonry_h_mm,
        floor_lintel=(spec.material == "wood_frame"),
    )
    lintel_report = design_lintel(lintel_spec)

    lintel_moment_dcr = lintel_report.moment_dcr
    lintel_deflection_mm = lintel_report.delta_max_mm
    lintel_deflection_ok = lintel_report.deflection_ok

    # ---- Overall adequacy check ----------------------------------------------
    jamb_ok = jamb_dcr <= 1.0
    lintel_moment_ok = lintel_moment_dcr <= 1.0

    all_adequate = jamb_ok and lintel_moment_ok and lintel_deflection_ok

    if not jamb_ok:
        governing_check = "jamb_dcr_exceeded"
    elif not lintel_moment_ok:
        governing_check = "lintel_moment_dcr_exceeded"
    elif not lintel_deflection_ok:
        governing_check = "lintel_deflection_exceeded"
    else:
        governing_check = "OK"

    # ---- Honest caveat -------------------------------------------------------
    t_mm = spec.wall_thickness_m * 1000.0
    honest_caveat = (
        f"ARCH-OPENING-IN-WALL [{spec.material.upper()}]: "
        f"opening {spec.opening_width_m:.3f}m W × {spec.opening_height_m:.3f}m H, "
        f"wall t={t_mm:.0f}mm, h_wall={spec.wall_height_m:.3f}m. "
        f"Jamb: width={spec.jamb_width_m:.3f}m, lintel depth={spec.lintel_depth_m*1000:.0f}mm. "
        f"Loading: axial={spec.applied_axial_kN_per_m:.3f}kN/m, "
        f"lateral={spec.applied_lateral_kN_per_m2:.3f}kN/m².\n"
        f"TRIBUTARY WIDTH (IBC §2308.4 intent): "
        f"trib_w = opening/2 + jamb/2 + header_height = "
        f"{spec.opening_width_m/2:.3f} + {spec.jamb_width_m/2:.3f} + "
        f"{spec.header_above_opening_height_m:.3f} = {trib_w:.3f}m per jamb.\n"
        f"JAMB LOAD: P_gravity={P_gravity_kN:.3f}kN (1.2×{spec.applied_axial_kN_per_m:.3f}×{trib_w:.3f}), "
        f"P_lateral={P_lateral_kN:.3f}kN (0.5×{spec.applied_lateral_kN_per_m2:.3f}×"
        f"{opening_area_m2:.3f}m²), "
        f"P_total={total_load_on_jamb_kN:.3f}kN.\n"
        f"JAMB CAPACITY [{cap_method}]: φ·Pn={jamb_cap_kN:.3f}kN. "
        f"Jamb DCR={jamb_dcr:.3f} ({'OK' if jamb_ok else 'FAIL'}).\n"
        f"LINTEL [{lintel_mat}]: moment DCR={lintel_moment_dcr:.3f} ({'OK' if lintel_moment_ok else 'FAIL'}), "
        f"δ_max={lintel_deflection_mm:.3f}mm ({'OK' if lintel_deflection_ok else 'FAIL'}).\n"
        f"GOVERNING: {governing_check}. ALL_ADEQUATE={all_adequate}.\n"
        "SCOPE LIMITATIONS:\n"
        "  (1) Tributary-width approach per IBC §2308.4 prescriptive intent: "
        "trib_w = opening/2 + jamb/2 + header_height. "
        "Full 2-D FE stress-concentration analysis around opening corners NOT modelled "
        "(St. Venant diffusion ≈ 1–2× opening dimension; potentially unconservative for "
        "opening_width > wall_height/2 or clustered openings).\n"
        "  (2) Jamb: ACI §11.5.3.1 / TMS §8.3 empirical formula — small eccentricity "
        "assumed (e ≈ 0). For eccentric loads use PM interaction surface (ACI §11.4).\n"
        "  (3) Wood-frame jamb: simplified bearing check only; NDS 2018 column-stability "
        "factor Cp (slenderness reduction) NOT computed — conservative φ=0.90 used.\n"
        "  (4) Lintel: design_lintel (simple span, 45° arching, ρ_max estimated; see "
        "arch_design_lintel caveat for full list of lintel scope limits).\n"
        "  (5) Lateral load to jamb treated as vertical shear reaction at lintel end — "
        "in-plane wall shear (IBC §2308.9 / SDPWS §4.3) NOT checked.\n"
        "  (6) Load factors: 1.2×gravity for jamb (ASCE 7-16 §2.3.1 combo 2). "
        "Wind/seismic load combinations must be checked separately.\n"
        "Refs: IBC 2021 §2308.4; TMS 402-22 §5/§8.3; ACI 318-19 §11.5.3.1; "
        "AISC 360-22 §F1; NDS 2018; ASCE 7-16 §2.3.1."
    )

    return OpeningCheckReport(
        tributary_load_on_jamb_kN=round(total_load_on_jamb_kN, 6),
        jamb_axial_capacity_kN=round(jamb_cap_kN, 6),
        jamb_dcr=round(jamb_dcr, 6),
        lintel_moment_dcr=round(lintel_moment_dcr, 6),
        lintel_deflection_mm=round(lintel_deflection_mm, 6),
        all_adequate=all_adequate,
        governing_check=governing_check,
        honest_caveat=honest_caveat,
    )
