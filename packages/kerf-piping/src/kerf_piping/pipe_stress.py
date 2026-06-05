"""
kerf_piping.pipe_stress — ASME B31.1 / B31.3 pipe stress and flexibility analysis.

Implements the ASME B31 stress intensification / flexibility approach for:

  Sustained loads (dead weight + pressure):
      S_L ≤ S_h  (ASME B31.1 §104.8.1 / B31.3 §302.3.5)

  Thermal expansion loads:
      S_E = S_b + S_t  ≤ S_A = f(1.25·S_c + 0.25·S_h)  (B31.3 §319.4.4)
      S_A = allowable expansion stress range

  Sustained + occasional loads:
      S_L_occ ≤ 1.33·S_h  (ASME B31.1 §104.8.4)

  Thermal expansion (fully-restrained, single straight leg):
      F_th = E · α · ΔT · A_metal  [lbf or N]

DISCLAIMER
----------
These methods are simplified ASME B31 formulations suitable for preliminary
analysis of straight-pipe runs.  They do NOT replace a full piping flexibility
analysis (CAESAR II-class 3D elastic beam finite element).  NOT ASME stamp
certified.  Review by a licensed Professional Engineer is required before use
in any physical installation.

References
----------
ASME B31.1-2022 Power Piping:
  §104.8.1 — Sustained stress limits for straight pipe.
  §104.8.4 — Occasional load stress limits.
  §119.6.4 — Expansion stress (simplified for single-plane systems).
  Appendix D — Flexibility analysis guidance.

ASME B31.3-2022 Process Piping:
  §302.3.5 — Allowable stress bases.
  §319.4.4 — Displacement stress range equation.
  §319.4.2 — Flexibility characteristic and SIF.

Key functions
-------------
sustained_stress(dn, schedule, pressure_psi, weight_per_m, span_m, mat, code)
    S_L — sustained hoop + bending stress in straight pipe.

thermal_expansion_force(dn, schedule, delta_T_F, mat, anchored_length_m)
    Fully-restrained axial thermal force and approximate expansion stress.

expansion_stress_range(S_b, M_t, Z, S_c, S_h, f)
    ASME B31.3 §319.4.4 displacement stress range check.

allowable_expansion_stress(S_c, S_h, f)
    S_A = f(1.25·S_c + 0.25·S_h)  per B31.3 §319.4.4.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Material property tables for stress analysis
# ---------------------------------------------------------------------------

# Young's modulus E (psi) at temperature
# Source: ASME B31.1-2022 Appendix C / B31.3-2022 Appendix C
_MODULUS_PSI: dict[str, float] = {
    "A106-B":    29.0e6,   # carbon steel
    "A53-B":     29.0e6,
    "A312-304":  28.0e6,   # SS 304
    "A312-316":  28.0e6,   # SS 316
    "A333-6":    29.0e6,   # low-temp carbon steel
}

# Thermal expansion coefficient α (per °F)
# Source: ASME B31.1-2022 Appendix C
_ALPHA_PER_F: dict[str, float] = {
    "A106-B":    6.5e-6,   # carbon steel: 11.7e-6 /°C
    "A53-B":     6.5e-6,
    "A312-304":  9.6e-6,   # SS 304/316: 17.2e-6 /°C
    "A312-316":  9.6e-6,
    "A333-6":    6.5e-6,
}

# ASME B31.3 Table A-1 hot allowable stress S_h (psi) at service temperature
# Using same table as wall_thickness module (ambient/400°F)
# Simplified: use ambient allowable as conservative
_SH_PSI: dict[str, float] = {
    "A106-B":   17_500,
    "A53-B":    15_000,
    "A312-304": 20_000,
    "A312-316": 20_000,
    "A333-6":   17_500,
}

# Cold allowable stress S_c (psi) — typically same as S_h for most materials
_SC_PSI: dict[str, float] = _SH_PSI.copy()


# ---------------------------------------------------------------------------
# Pipe cross-section properties
# ---------------------------------------------------------------------------

def _pipe_section_modulus_in3(od_in: float, wall_in: float) -> float:
    """
    Elastic section modulus Z = π/32 · (OD⁴ - ID⁴) / OD  [in³].

    Used in bending stress = M / Z.
    """
    if wall_in <= 0.0:
        raise ValueError(
            f"Wall thickness must be > 0; got {wall_in:.4f}\". "
            "Check wall input."
        )
    id_in = od_in - 2.0 * wall_in
    if id_in <= 0.0:
        raise ValueError(
            f"Wall thickness {wall_in:.3f}\" ≥ OD/2 ({od_in/2:.3f}\"). "
            "Check OD and wall inputs."
        )
    Z = (math.pi / 32.0) * (od_in**4 - id_in**4) / od_in
    return Z


def _pipe_metal_area_in2(od_in: float, wall_in: float) -> float:
    """Cross-sectional metal area A = π/4·(OD² - ID²)  [in²]."""
    id_in = od_in - 2.0 * wall_in
    return math.pi / 4.0 * (od_in**2 - id_in**2)


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class StressResult:
    """Pipe stress analysis result."""
    code: str              # 'B31.1' or 'B31.3'
    load_case: str         # 'sustained', 'thermal', 'occasional'
    calculated_psi: float  # calculated stress (psi)
    allowable_psi: float   # allowable stress limit (psi)
    utilisation: float     # calculated / allowable
    compliant: bool        # True if utilisation ≤ 1.0
    details: dict          # intermediate values
    disclaimer: str

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            "load_case": self.load_case,
            "calculated_psi": round(self.calculated_psi, 1),
            "allowable_psi": round(self.allowable_psi, 1),
            "utilisation": round(self.utilisation, 4),
            "compliant": self.compliant,
            "details": self.details,
            "disclaimer": self.disclaimer,
        }


# ---------------------------------------------------------------------------
# Sustained stress — ASME B31.1 §104.8.1
# ---------------------------------------------------------------------------

def sustained_stress(
    od_in: float,
    wall_in: float,
    pressure_psi: float,
    weight_lbf_per_ft: float,
    span_ft: float,
    material: str = "A106-B",
    code: str = "B31.1",
    joint_efficiency: float = 1.0,
) -> StressResult:
    """
    Sustained stress in a simply-supported straight pipe span.

    ASME B31.1 §104.8.1 limit:
        S_L = S_L_hoop + S_L_bending ≤ S_h

    where:
        S_L_hoop    = pressure hoop stress (longitudinal component):
                      P·D / (4·t)  [lbf/in²]
                      (≈ half the hoop stress; used for sustained load check)
        S_L_bending = maximum bending stress due to self-weight:
                      M_max / Z
                      M_max = w·L² / 8  (simply supported beam, uniform load)

    Parameters
    ----------
    od_in           : Pipe outside diameter (inches).
    wall_in         : Nominal pipe wall thickness (inches).
    pressure_psi    : Internal design pressure (psi).
    weight_lbf_per_ft : Distributed weight of pipe + fluid + insulation (lbf/ft).
    span_ft         : Support span length (feet).
    material        : Material key string (e.g. 'A106-B').
    code            : 'B31.1' or 'B31.3' (affects allowable).
    joint_efficiency: Longitudinal weld joint efficiency E (default 1.0 seamless).

    Returns
    -------
    StressResult with load_case='sustained'.
    """
    if od_in <= 0:
        raise ValueError(f"od_in must be > 0, got {od_in!r}")
    if wall_in <= 0 or wall_in >= od_in / 2:
        raise ValueError(f"wall_in must be > 0 and < OD/2, got {wall_in!r}")

    # Section properties
    Z_in3 = _pipe_section_modulus_in3(od_in, wall_in)
    t = wall_in

    # Hoop stress longitudinal component P·D/(4·t)  (B31.1 §104.8.1 note)
    S_L_hoop = pressure_psi * od_in / (4.0 * t)

    # Bending moment: simply-supported uniform load  M = wL²/8
    w_lbf_in = weight_lbf_per_ft / 12.0   # convert to lbf/in
    L_in     = span_ft * 12.0             # span in inches
    M_max    = w_lbf_in * L_in ** 2 / 8.0   # in-lbf (max at mid-span)
    S_L_bend = M_max / Z_in3

    S_L = S_L_hoop + S_L_bend

    # Allowable
    S_h = _SH_PSI.get(material, 17_500)
    allowable = S_h * joint_efficiency

    util = S_L / allowable if allowable > 0 else float("inf")

    return StressResult(
        code=code,
        load_case="sustained",
        calculated_psi=S_L,
        allowable_psi=allowable,
        utilisation=util,
        compliant=util <= 1.0,
        details={
            "hoop_stress_psi": round(S_L_hoop, 1),
            "bending_stress_psi": round(S_L_bend, 1),
            "M_max_inlbf": round(M_max, 1),
            "Z_section_modulus_in3": round(Z_in3, 6),
            "span_ft": span_ft,
            "weight_lbf_per_ft": weight_lbf_per_ft,
            "od_in": od_in,
            "wall_in": wall_in,
            "S_h_psi": S_h,
        },
        disclaimer=(
            "ASME B31.1 §104.8.1 simplified sustained stress — "
            "simply-supported span model.  NOT ASME stamp certified.  "
            "Full piping flexibility analysis (CAESAR II-class) required "
            "for actual installation."
        ),
    )


# ---------------------------------------------------------------------------
# Thermal expansion load — fully-restrained
# ---------------------------------------------------------------------------

def thermal_expansion_force(
    od_in: float,
    wall_in: float,
    delta_T_F: float,
    material: str = "A106-B",
    code: str = "B31.1",
) -> dict:
    """
    Fully-restrained axial thermal force and stress.

    For a pipe segment anchored at both ends (fully restrained):
        F_th = E · α · ΔT · A_metal    [lbf]
        σ_th = E · α · ΔT              [psi]

    Parameters
    ----------
    od_in     : Pipe outside diameter (inches).
    wall_in   : Nominal pipe wall thickness (inches).
    delta_T_F : Temperature change ΔT (°F).  Positive = heat-up.
    material  : Material key (e.g. 'A106-B', 'A312-316').
    code      : 'B31.1' or 'B31.3'.

    Returns
    -------
    dict with:
        thermal_force_lbf    — fully-restrained axial thrust (lbf).
        thermal_stress_psi   — fully-restrained axial stress (psi).
        free_expansion_in    — free expansion per foot of pipe (in/ft).
        metal_area_in2       — pipe cross-section metal area (in²).
        compliant_note       — note on whether stress exceeds allowable S_h.
    """
    E   = _MODULUS_PSI.get(material, 29.0e6)
    alpha = _ALPHA_PER_F.get(material, 6.5e-6)
    A   = _pipe_metal_area_in2(od_in, wall_in)
    S_h = _SH_PSI.get(material, 17_500)

    sigma_th = E * alpha * delta_T_F        # psi (fully restrained)
    F_th     = sigma_th * A                  # lbf
    # Free expansion per foot of pipe (in/ft)
    free_exp_in_per_ft = alpha * delta_T_F * 12.0

    note = "Stress within S_h" if abs(sigma_th) <= S_h else (
        f"Fully-restrained stress ({abs(sigma_th):.0f} psi) exceeds S_h "
        f"({S_h} psi) — expansion loops, bends, or expansion joints required."
    )

    return {
        "thermal_force_lbf":    round(F_th, 1),
        "thermal_stress_psi":   round(sigma_th, 1),
        "free_expansion_in_per_ft": round(free_exp_in_per_ft, 5),
        "metal_area_in2":       round(A, 5),
        "modulus_psi":          E,
        "alpha_per_F":          alpha,
        "delta_T_F":            delta_T_F,
        "S_h_psi":              S_h,
        "compliant_note":       note,
        "disclaimer": (
            "Fully-restrained thermal force E·α·ΔT·A.  "
            "Actual piping system forces depend on boundary conditions "
            "and must be evaluated per ASME B31 Appendix D or equivalent "
            "flexibility analysis.  NOT ASME stamp certified."
        ),
    }


# ---------------------------------------------------------------------------
# Expansion stress range — ASME B31.3 §319.4.4
# ---------------------------------------------------------------------------

def allowable_expansion_stress(
    S_c_psi: float,
    S_h_psi: float,
    f: float = 1.0,
) -> float:
    """
    ASME B31.3 §319.4.4 allowable displacement stress range S_A.

        S_A = f · (1.25·S_c + 0.25·S_h)

    Parameters
    ----------
    S_c_psi : Cold (installation) allowable stress (psi).
    S_h_psi : Hot (operating) allowable stress (psi).
    f       : Stress range reduction factor for cyclic service.
              f = 1.0 for N ≤ 7000 cycles (full design life).
              Typically 0.9–1.0; see B31.3 Table 302.3.5.

    Returns
    -------
    S_A (psi).
    """
    return f * (1.25 * S_c_psi + 0.25 * S_h_psi)


def expansion_stress_range(
    M_i_inlbf: float,
    M_o_inlbf: float,
    M_t_inlbf: float,
    Z_in3: float,
    S_c_psi: float,
    S_h_psi: float,
    f: float = 1.0,
    i_SIF: float = 1.0,
) -> StressResult:
    """
    ASME B31.3 §319.4.4 displacement stress range check.

    Formula (Eq. 17):
        S_E = sqrt( S_b² + 4·S_t² ) ≤ S_A

    where:
        S_b = i · √(M_i² + M_o²) / Z   [in-plane + out-of-plane bending]
        S_t = M_t / (2·Z)               [torsional stress component]
        S_A = f·(1.25·S_c + 0.25·S_h)  [allowable expansion range]

    Parameters
    ----------
    M_i_inlbf  : In-plane bending moment (in-lbf).
    M_o_inlbf  : Out-of-plane bending moment (in-lbf).
    M_t_inlbf  : Torsional moment (in-lbf).
    Z_in3      : Section modulus (in³).  Use _pipe_section_modulus_in3().
    S_c_psi    : Cold allowable stress (psi).
    S_h_psi    : Hot allowable stress (psi).
    f          : Stress range reduction factor (default 1.0 for ≤7000 cycles).
    i_SIF      : Stress intensification factor (SIF) for fittings per
                 B31.3 Appendix D (1.0 for straight pipe, ≥1.3 for elbows).

    Returns
    -------
    StressResult with load_case='thermal_expansion'.
    """
    if Z_in3 <= 0:
        raise ValueError(f"Z_in3 must be > 0, got {Z_in3!r}")

    S_b = i_SIF * math.sqrt(M_i_inlbf**2 + M_o_inlbf**2) / Z_in3
    S_t = M_t_inlbf / (2.0 * Z_in3)
    S_E = math.sqrt(S_b**2 + 4.0 * S_t**2)

    S_A = allowable_expansion_stress(S_c_psi, S_h_psi, f)
    util = S_E / S_A if S_A > 0 else float("inf")

    return StressResult(
        code="B31.3",
        load_case="thermal_expansion",
        calculated_psi=S_E,
        allowable_psi=S_A,
        utilisation=util,
        compliant=util <= 1.0,
        details={
            "S_b_psi": round(S_b, 1),
            "S_t_psi": round(S_t, 1),
            "S_E_psi": round(S_E, 1),
            "S_A_psi": round(S_A, 1),
            "S_c_psi": S_c_psi,
            "S_h_psi": S_h_psi,
            "f_factor": f,
            "i_SIF": i_SIF,
            "Z_in3": round(Z_in3, 6),
            "M_i_inlbf": M_i_inlbf,
            "M_o_inlbf": M_o_inlbf,
            "M_t_inlbf": M_t_inlbf,
        },
        disclaimer=(
            "ASME B31.3 §319.4.4 expansion stress range (Eq. 17). "
            "Moments must come from a flexibility analysis (e.g. CAESAR II). "
            "This function evaluates the stress check only — it does NOT "
            "compute pipe system deflections or reactions.  "
            "NOT ASME stamp certified."
        ),
    )


# ---------------------------------------------------------------------------
# Occasional load check — ASME B31.1 §104.8.4
# ---------------------------------------------------------------------------

def occasional_stress_check(
    S_sustained_psi: float,
    M_occasional_inlbf: float,
    Z_in3: float,
    S_h_psi: float,
    occasional_factor: float = 1.33,
) -> StressResult:
    """
    Occasional load stress limit per ASME B31.1 §104.8.4.

    Occasionally-applied loads (wind, seismic, water hammer) may increase
    the allowable by a factor:
        S_L_occ = S_L_sustained + i·M_occ/Z ≤ occasional_factor · S_h

    Parameters
    ----------
    S_sustained_psi      : Already-calculated sustained stress (psi).
    M_occasional_inlbf   : Bending moment from occasional load (in-lbf).
    Z_in3                : Section modulus (in³).
    S_h_psi              : Hot allowable stress (psi).
    occasional_factor    : Allowable multiplier (1.33 per B31.1 §104.8.4;
                           1.20 for sustained + seismic per many codes).

    Returns
    -------
    StressResult with load_case='occasional'.
    """
    S_occ_bend = M_occasional_inlbf / Z_in3  if Z_in3 > 0 else float("inf")
    S_total    = S_sustained_psi + S_occ_bend
    allowable  = occasional_factor * S_h_psi
    util       = S_total / allowable if allowable > 0 else float("inf")

    return StressResult(
        code="B31.1",
        load_case="occasional",
        calculated_psi=S_total,
        allowable_psi=allowable,
        utilisation=util,
        compliant=util <= 1.0,
        details={
            "S_sustained_psi": round(S_sustained_psi, 1),
            "S_occ_bending_psi": round(S_occ_bend, 1),
            "M_occasional_inlbf": M_occasional_inlbf,
            "Z_in3": round(Z_in3, 6),
            "S_h_psi": S_h_psi,
            "occasional_factor": occasional_factor,
        },
        disclaimer=(
            "ASME B31.1 §104.8.4 occasional load check. "
            "Occasional load moment must be obtained from a separate "
            "seismic/dynamic analysis.  NOT ASME stamp certified."
        ),
    )
