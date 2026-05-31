"""
kerf_cad_core.arch.footing_bearing — Meyerhof (1963) general bearing capacity.

Implements the Meyerhof (1963) general bearing capacity equation for shallow
rectangular, square, circular, and strip footings on cohesive/cohesionless soil:

    q_ult = c·N_c·s_c·d_c + γ·Df·N_q·s_q·d_q + 0.5·γ·B·N_γ·s_γ·d_γ

N-factors (Meyerhof 1963):
    N_q   = e^(π·tanφ) · tan²(45 + φ/2)
    N_c   = (N_q − 1) · cotφ          (φ > 0)
    N_c   = 5.14                        (φ = 0, limit as φ→0)
    N_γ   = (N_q − 1) · tan(1.4φ)

Shape factors s_c, s_q, s_γ and depth factors d_c, d_q, d_γ follow
Meyerhof (1963) / Bowles (1996) Table 4-4 conventions.

All inputs in SI: kPa, kN/m³, metres.  Output in kPa.

References:
  Bowles J.E. (1996) *Foundation Analysis and Design* 5e, §4.
  Das B.M. (2011) *Principles of Foundation Engineering* 8e, §3.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

__all__ = [
    "SoilProperties",
    "FootingSpec",
    "BearingCapacityReport",
    "compute_bearing_capacity",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class SoilProperties:
    """
    Soil characterisation for Meyerhof bearing-capacity computation.

    Parameters
    ----------
    cohesion_c_kPa : float
        Undrained (or drained) cohesion c in kPa.  Use 0 for purely frictional
        soils (sand/gravel).  Must be ≥ 0.
    friction_angle_phi_deg : float
        Angle of internal friction φ in degrees.  Range [0, 50].
        For saturated clay in undrained analysis (φ_u = 0) set to 0.
    unit_weight_kN_m3 : float
        Moist (or submerged) unit weight γ in kN/m³.  Must be > 0.
    depth_factor_kf : float
        Reserved scale factor applied to the depth term γ·Df.  Defaults to 1.0.
        Useful for layered soils or effective-stress corrections.
    """
    cohesion_c_kPa: float
    friction_angle_phi_deg: float
    unit_weight_kN_m3: float
    depth_factor_kf: float = 1.0


@dataclass
class FootingSpec:
    """
    Geometry of a shallow footing.

    Parameters
    ----------
    length_B_m : float
        Shorter plan dimension (B) in metres.  Must be > 0.
        For circular footings this is the diameter.
    width_L_m : float
        Longer plan dimension (L) in metres.  Must be ≥ B.
        Ignored for circular footings (only B is used).
    depth_Df_m : float
        Depth of footing base below ground surface (Df) in metres.  Must be > 0.
    shape : str
        One of ``"strip"``, ``"square"``, ``"circular"``, ``"rectangular"``.
        Shape factors are applied accordingly.
    """
    length_B_m: float
    width_L_m: float
    depth_Df_m: float
    shape: str


@dataclass
class BearingCapacityReport:
    """
    Output of Meyerhof (1963) bearing-capacity calculation.

    Parameters
    ----------
    q_ult_kPa : float
        Ultimate bearing capacity in kPa.
    q_allow_kPa : float
        Allowable bearing capacity = q_ult / FS in kPa.
    factor_of_safety : float
        Factor of safety applied.  Default 3.0 (Bowles §4-8, Das §3.9).
    N_c : float
        Meyerhof bearing-capacity factor N_c.
    N_q : float
        Meyerhof bearing-capacity factor N_q.
    N_gamma : float
        Meyerhof bearing-capacity factor N_γ.
    shape_factor_s_c : float
        Shape factor applied to the cohesion term.
    depth_factor_d_c : float
        Depth factor applied to the cohesion term.
    honest_caveat : str
        Scope caveat: limitations and applicable references.
    """
    q_ult_kPa: float
    q_allow_kPa: float
    factor_of_safety: float
    N_c: float
    N_q: float
    N_gamma: float
    shape_factor_s_c: float
    depth_factor_d_c: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

_VALID_SHAPES = frozenset({"strip", "square", "circular", "rectangular"})


def _meyerhof_N_factors(phi_deg: float) -> tuple[float, float, float]:
    """
    Return (N_c, N_q, N_γ) using Meyerhof (1963) expressions.

    For φ = 0 (pure cohesion / undrained) the special limiting case
    N_c = 5.14 (= π + 2, Prandtl) is used and N_γ = 0.

    Reference: Bowles (1996) Table 4-2; Das (2011) Table 3.2.
    """
    if phi_deg < 0 or phi_deg > 50:
        raise ValueError(
            f"friction_angle_phi_deg must be in [0, 50], got {phi_deg}"
        )

    if phi_deg == 0.0:
        # Limiting case: N_c = π + 2 = 5.14 (Prandtl solution for φ=0)
        N_q = 1.0
        N_c = 5.14
        N_gamma = 0.0
        return N_c, N_q, N_gamma

    phi_rad = math.radians(phi_deg)

    # Meyerhof (1963):
    #   N_q = e^(π·tanφ) · tan²(45 + φ/2)
    N_q = math.exp(math.pi * math.tan(phi_rad)) * (math.tan(math.radians(45.0 + phi_deg / 2.0)) ** 2)

    #   N_c = (N_q − 1) · cot(φ)
    N_c = (N_q - 1.0) / math.tan(phi_rad)

    #   N_γ = (N_q − 1) · tan(1.4·φ)
    #   Note: Bowles (1996) Table 4-2; Das (2011) Eq 3.26c; Meyerhof 1963 §3.
    N_gamma = (N_q - 1.0) * math.tan(math.radians(1.4 * phi_deg))

    return N_c, N_q, N_gamma


def _shape_factors(shape: str, phi_deg: float, B: float, L: float) -> tuple[float, float, float]:
    """
    Return (s_c, s_q, s_γ) per Meyerhof (1963) / Bowles (1996) Table 4-4.

    Strip:       s_c = s_q = s_γ = 1.0
    Square:      s_c = 1 + 0.2·(B/L)·(N_phi/N_phi_45)  →  simplified as per Bowles
    Circular:    same as square with B/L = 1
    Rectangular: interpolation between strip and square

    In practice Meyerhof (1963) gave (Bowles Table 4-4 / Das Table 3.4):
      s_c = 1 + 0.2·(B/L)·K_phi   where K_phi = tan²(45+φ/2)
      s_q = s_γ = 1 + 0.1·(B/L)·K_phi  for φ ≥ 10°
      s_q = s_γ = 1.0  for φ = 0
    """
    phi_rad = math.radians(phi_deg)
    K_phi = math.tan(math.radians(45.0 + phi_deg / 2.0)) ** 2  # tan²(45+φ/2)

    if shape == "strip":
        return 1.0, 1.0, 1.0

    # ratio B/L (always ≤ 1 because B ≤ L in the spec)
    if shape in ("square", "circular"):
        ratio = 1.0
    else:
        # rectangular: B/L
        ratio = B / L if L > 0 else 1.0

    s_c = 1.0 + 0.2 * ratio * K_phi

    if phi_deg == 0.0:
        s_q = 1.0
        s_gamma = 1.0
    else:
        s_q = 1.0 + 0.1 * ratio * K_phi
        s_gamma = 1.0 + 0.1 * ratio * K_phi

    return s_c, s_q, s_gamma


def _depth_factors(phi_deg: float, Df: float, B: float) -> tuple[float, float, float]:
    """
    Return (d_c, d_q, d_γ) per Meyerhof (1963) / Bowles (1996) Table 4-4.

    Meyerhof (1963) depth factors (Bowles Table 4-4 / Das Table 3.5):
      d_c = 1 + 0.2·(Df/B)·sqrt(K_phi)
      d_q = d_γ = 1 + 0.1·(Df/B)·sqrt(K_phi)  for φ ≥ 10°
      d_q = d_γ = 1.0  for φ = 0
    """
    K_phi = math.tan(math.radians(45.0 + phi_deg / 2.0)) ** 2
    sqrt_K = math.sqrt(K_phi)
    Df_over_B = Df / B if B > 0 else 0.0

    d_c = 1.0 + 0.2 * Df_over_B * sqrt_K

    if phi_deg == 0.0:
        d_q = 1.0
        d_gamma = 1.0
    else:
        d_q = 1.0 + 0.1 * Df_over_B * sqrt_K
        d_gamma = 1.0 + 0.1 * Df_over_B * sqrt_K

    return d_c, d_q, d_gamma


def compute_bearing_capacity(
    footing: FootingSpec,
    soil: SoilProperties,
    FS: float = 3.0,
) -> BearingCapacityReport:
    """
    Compute ultimate and allowable bearing capacity of a shallow footing using
    the Meyerhof (1963) general bearing capacity equation.

    Formula (Meyerhof 1963, Bowles 1996 Eq 4-4 / Das 2011 Eq 3.25):
        q_ult = c·N_c·s_c·d_c
              + γ·Df·N_q·s_q·d_q
              + 0.5·γ·B·N_γ·s_γ·d_γ

    Parameters
    ----------
    footing : FootingSpec
        Plan dimensions (B, L in m), embedment depth Df, and shape.
    soil : SoilProperties
        Cohesion c (kPa), friction angle φ (°), unit weight γ (kN/m³).
    FS : float
        Factor of safety.  Bowles §4-8 recommends FS = 2.5–3.0 for
        ordinary static loads; default 3.0.

    Returns
    -------
    BearingCapacityReport

    Raises
    ------
    ValueError
        On invalid geometry or soil parameters.
    """
    # ---- Input validation --------------------------------------------------
    if footing.shape not in _VALID_SHAPES:
        raise ValueError(
            f"shape must be one of {sorted(_VALID_SHAPES)}, got '{footing.shape}'"
        )
    if footing.length_B_m <= 0:
        raise ValueError(f"length_B_m must be > 0, got {footing.length_B_m}")
    if footing.width_L_m < footing.length_B_m and footing.shape == "rectangular":
        raise ValueError(
            f"width_L_m ({footing.width_L_m}) must be ≥ length_B_m ({footing.length_B_m})"
        )
    if footing.depth_Df_m <= 0:
        raise ValueError(f"depth_Df_m must be > 0, got {footing.depth_Df_m}")
    if soil.cohesion_c_kPa < 0:
        raise ValueError(f"cohesion_c_kPa must be ≥ 0, got {soil.cohesion_c_kPa}")
    if soil.friction_angle_phi_deg < 0 or soil.friction_angle_phi_deg > 50:
        raise ValueError(
            f"friction_angle_phi_deg must be in [0, 50], got {soil.friction_angle_phi_deg}"
        )
    if soil.unit_weight_kN_m3 <= 0:
        raise ValueError(
            f"unit_weight_kN_m3 must be > 0, got {soil.unit_weight_kN_m3}"
        )
    if FS <= 0:
        raise ValueError(f"FS must be > 0, got {FS}")

    # ---- Convenience aliases -----------------------------------------------
    c = soil.cohesion_c_kPa
    phi_deg = soil.friction_angle_phi_deg
    gamma = soil.unit_weight_kN_m3
    Df = footing.depth_Df_m
    B = footing.length_B_m
    L = footing.width_L_m

    # ---- Meyerhof N-factors ------------------------------------------------
    N_c, N_q, N_gamma = _meyerhof_N_factors(phi_deg)

    # ---- Shape factors --------------------------------------------------------
    s_c, s_q, s_gamma = _shape_factors(footing.shape, phi_deg, B, L)

    # ---- Depth factors --------------------------------------------------------
    d_c, d_q, d_gamma = _depth_factors(phi_deg, Df, B)

    # ---- Bearing capacity equation -----------------------------------------
    # Term 1: cohesion
    q_cohesion = c * N_c * s_c * d_c
    # Term 2: surcharge
    q_surcharge = gamma * Df * soil.depth_factor_kf * N_q * s_q * d_q
    # Term 3: self-weight (use B = shorter dimension always)
    q_weight = 0.5 * gamma * B * N_gamma * s_gamma * d_gamma

    q_ult = q_cohesion + q_surcharge + q_weight
    q_allow = q_ult / FS

    # ---- Honest scope caveat -----------------------------------------------
    caveat = (
        "Meyerhof (1963) general bearing capacity equation — "
        "Bowles 'Foundation Analysis and Design' 5e §4, Das 'Principles of Foundation Engineering' 8e §3. "
        f"q_ult = {q_ult:.2f} kPa; q_allow = {q_allow:.2f} kPa (FS = {FS}). "
        f"N_c = {N_c:.2f}, N_q = {N_q:.2f}, N_γ = {N_gamma:.2f}. "
        "SCOPE LIMITATIONS: "
        "(1) Meyerhof (1963) shape/depth/inclination factors only — Brinch Hansen (1970) rigidity index "
        "(I_r) correction and vesic punching shear not applied. "
        "(2) No inclined load, eccentric load, or ground-slope corrections (Meyerhof 1963 §4). "
        "(3) No seismic (ASCE 7-22 §13.2) or liquefaction correction. "
        "(4) Assumes homogeneous half-space — layered soils or weak-layer punching not modelled. "
        "(5) q_allow = q_ult / FS; net bearing capacity correction for existing overburden pressure "
        "not applied. "
        "(6) For saturated clay (φ=0): undrained bearing capacity via N_c=5.14 (Prandtl); "
        "long-term drained stability requires effective-stress parameters. "
        "Always verify against site investigation data and local building code."
    )

    return BearingCapacityReport(
        q_ult_kPa=q_ult,
        q_allow_kPa=q_allow,
        factor_of_safety=FS,
        N_c=N_c,
        N_q=N_q,
        N_gamma=N_gamma,
        shape_factor_s_c=s_c,
        depth_factor_d_c=d_c,
        honest_caveat=caveat,
    )
