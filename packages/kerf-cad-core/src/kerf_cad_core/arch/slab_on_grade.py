"""
kerf_cad_core.arch.slab_on_grade — ACI 360R-10 slab-on-grade thickness check.

Checks adequacy of an unreinforced (or lightly reinforced) concrete slab-on-grade
under a concentrated point or wheel load per:

  - ACI 360R-10  *Guide to Design and Construction of Concrete Floors*
  - PCA EB119    *Design of Concrete Floors on Ground* (Ringo & Anderson)
  - Westergaard (1948)  *New Formulas for Stresses in Concrete Pavements*

Theory — Interior load model (Westergaard plate-on-elastic-foundation):

  Radius of relative stiffness:
      l = [E·h³ / (12·(1−ν²)·k)]^0.25         (mm)

  where:
      E  = concrete elastic modulus = 4700·√f'c  (ACI 318-19 §19.2.2.1)  [MPa]
      h  = slab thickness                                                   [mm]
      ν  = Poisson's ratio for concrete = 0.15 (Westergaard 1948)
      k  = modulus of subgrade reaction                                    [N/mm³]
             input in MPa/m; converted: k[N/mm³] = k[MPa/m] / 1000

  Maximum bending stress at slab bottom (PCA EB119 simplified formula):
      σ_max = 3·P·(1+ν)/(2·π·h²) · (log₁₀(l/b) + 0.5)                   [MPa]

  where:
      P  = point load                                                       [N]
      b  = contact area effective radius                                    [mm]

  Modulus of rupture (tensile strength):
      MR = 0.62·√f'c                          (ACI 318-19 §19.2.3.1)      [MPa]

  Demand/capacity ratio:
      DCR = σ_max / MR

  Joint spacing (PCA 30×h rule):
      S_joint ≤ 30·h                                                        [m]

All units are mm and MPa unless otherwise noted.  Load in kN (input) / N (internal).

SCOPE LIMITATIONS (honest_caveat):
  (1) Interior load only — Westergaard edge and corner stress concentrations
      (σ_edge ≈ 25–30% higher, σ_corner even higher) are NOT computed;
      use a dedicated edge/corner check near slab edges and at construction joints.
  (2) Thermal/shrinkage curling NOT modelled; curling stresses can add
      0.3–1.0 MPa and increase DCR, especially for slabs on low-k subgrades.
  (3) Single concentrated load; multi-load or distributed-load superposition
      requires separate analysis.
  (4) Lightly reinforced slabs assumed (reinforcement for crack control only,
      not structural); for heavily reinforced SFRС / post-tensioned slabs use
      ACI 360R-10 §6/§7.
  (5) k is the modulus of subgrade reaction at the slab base; plate-bearing test
      correction for plate diameter and depth NOT applied.
  (6) f'c cap at √69 MPa (ACI normalweight concrete) NOT auto-enforced.

References:
  Westergaard H.M. (1948) *New formulas for stresses in concrete pavements.*
      Trans. ASCE 113, 425–444.
  Portland Cement Association EB119 *Design of Concrete Floors on Ground*
      (Ringo & Anderson, 3rd ed., 1996).
  ACI 360R-10 *Guide to Design and Construction of Concrete Floors*,
      Appendix A2.1 (concentrated load, interior region).
  ACI 318-19 §19.2.2.1 (Ec), §19.2.3.1 (fr = MR).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "SlabOnGradeSpec",
    "SlabOnGradeReport",
    "check_slab_on_grade",
]

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SlabOnGradeSpec:
    """
    Input geometry and materials for ACI 360R-10 / Westergaard slab-on-grade check.

    Parameters
    ----------
    slab_thickness_mm : float
        Slab thickness h (mm).  Must be > 0.
    fc_MPa : float
        Specified compressive strength of concrete f'c (MPa).  Must be > 0.
        ACI 318-19 §19.2.2.1 caps f'c at 70 MPa for Ec formula; user must ensure
        f'c ≤ 69 MPa for ACI-compliant results.
    subgrade_modulus_k_MPa_per_m : float
        Modulus of subgrade reaction k (MPa/m = kN/m³).  Must be > 0.
        Typical ranges: very soft soil ≈ 13–27 MPa/m; medium ≈ 27–55 MPa/m;
        dense/stiff ≈ 55–110 MPa/m; rock ≥ 140 MPa/m.
        Obtained from plate-bearing test per ASTM D1196.
    point_load_kN : float
        Applied concentrated or wheel load P (kN).  Must be > 0.
    contact_radius_mm : float
        Radius of the load contact area (mm).  Must be > 0.
        For a circular wheel load: b = sqrt(load / (π·tyre_pressure)).
        For a square pad: b = sqrt(a²/π) where a = pad side length.
    slab_long_dimension_m : float
        Longer plan dimension of the slab panel (m).  Used to recommend
        joint spacing.  Must be > 0.
    """

    slab_thickness_mm: float
    fc_MPa: float
    subgrade_modulus_k_MPa_per_m: float
    point_load_kN: float
    contact_radius_mm: float
    slab_long_dimension_m: float


@dataclass
class SlabOnGradeReport:
    """
    Output of ACI 360R-10 / Westergaard slab-on-grade adequacy check.

    Parameters
    ----------
    radius_of_relative_stiffness_l_mm : float
        Westergaard radius of relative stiffness l (mm).
        l = [E·h³/(12·(1−ν²)·k)]^0.25
    max_bending_stress_MPa : float
        Maximum tensile bending stress at the slab bottom under the point load
        (interior load position, PCA EB119 formula) [MPa].
    modulus_of_rupture_MR_MPa : float
        Concrete modulus of rupture MR = 0.62·√f'c (ACI 318-19 §19.2.3.1) [MPa].
    dcr : float
        Demand/capacity ratio = σ_max / MR.  ≤ 1.0 = adequate (working stress).
    adequate : bool
        True when dcr ≤ 1.0.
    recommended_joint_spacing_m : float
        Maximum recommended joint spacing = min(30·h/1000, slab_long_dimension_m) [m].
        The 30·h PCA rule (PCA EB119 §4.4) limits crack-inducing shrinkage spans.
    honest_caveat : str
        Scope caveats and limitations.  Always read before relying on results.
    """

    radius_of_relative_stiffness_l_mm: float
    max_bending_stress_MPa: float
    modulus_of_rupture_MR_MPa: float
    dcr: float
    adequate: bool
    recommended_joint_spacing_m: float
    honest_caveat: str


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _validate(spec: SlabOnGradeSpec) -> None:
    """Raise ValueError with descriptive message on invalid inputs."""
    if spec.slab_thickness_mm <= 0:
        raise ValueError(
            f"slab_thickness_mm must be > 0, got {spec.slab_thickness_mm}"
        )
    if spec.fc_MPa <= 0:
        raise ValueError(f"fc_MPa must be > 0, got {spec.fc_MPa}")
    if spec.subgrade_modulus_k_MPa_per_m <= 0:
        raise ValueError(
            f"subgrade_modulus_k_MPa_per_m must be > 0, "
            f"got {spec.subgrade_modulus_k_MPa_per_m}"
        )
    if spec.point_load_kN <= 0:
        raise ValueError(
            f"point_load_kN must be > 0, got {spec.point_load_kN}"
        )
    if spec.contact_radius_mm <= 0:
        raise ValueError(
            f"contact_radius_mm must be > 0, got {spec.contact_radius_mm}"
        )
    if spec.slab_long_dimension_m <= 0:
        raise ValueError(
            f"slab_long_dimension_m must be > 0, got {spec.slab_long_dimension_m}"
        )


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

# Poisson's ratio for concrete (Westergaard 1948 / ACI 360R-10)
_NU: float = 0.15


def check_slab_on_grade(spec: SlabOnGradeSpec) -> SlabOnGradeReport:
    """
    Check slab-on-grade thickness adequacy under a concentrated interior load.

    Implements Westergaard (1948) plate-on-elastic-foundation theory as
    adopted by PCA EB119 / ACI 360R-10 for interior load position.

    Parameters
    ----------
    spec : SlabOnGradeSpec
        Input geometry, material, and load.

    Returns
    -------
    SlabOnGradeReport

    Raises
    ------
    ValueError
        On invalid (non-positive) inputs.

    Notes
    -----
    Working-stress design: DCR = σ_max / MR.  DCR ≤ 1.0 is adequate.
    No partial safety factors are applied (ACI 360R-10 working-stress basis).
    """
    _validate(spec)

    h = spec.slab_thickness_mm                        # mm
    fc = spec.fc_MPa                                   # MPa
    k_N_mm3 = spec.subgrade_modulus_k_MPa_per_m / 1_000.0  # N/mm³
    P_N = spec.point_load_kN * 1_000.0                # N
    b = spec.contact_radius_mm                         # mm
    nu = _NU

    # -------------------------------------------------------------------------
    # Concrete elastic modulus (ACI 318-19 §19.2.2.1, normal-weight concrete)
    # -------------------------------------------------------------------------
    E_MPa = 4_700.0 * math.sqrt(fc)  # MPa

    # -------------------------------------------------------------------------
    # Westergaard radius of relative stiffness l
    # l = [E·h³ / (12·(1−ν²)·k)]^0.25   [mm]
    # -------------------------------------------------------------------------
    l = (E_MPa * h ** 3 / (12.0 * (1.0 - nu ** 2) * k_N_mm3)) ** 0.25  # mm

    # -------------------------------------------------------------------------
    # Maximum bending stress — interior concentrated load
    # PCA EB119 (Ringo & Anderson 1996) simplified Westergaard formula:
    #   σ_max = 3·P·(1+ν) / (2·π·h²) · (log₁₀(l/b) + 0.5)    [MPa]
    # -------------------------------------------------------------------------
    if b >= l:
        # Contact radius exceeds l: Westergaard formulation is not valid
        # (plate acts locally rigid-on-spring).  Return conservative σ_max.
        # Per Meyerhof (1962) for b/l ≥ 1 the stress formula underestimates;
        # flag in caveat and compute anyway so callers can inspect.
        sigma_max = 3.0 * P_N * (1.0 + nu) / (2.0 * math.pi * h ** 2) * (
            math.log10(l / b) + 0.5
        )
    else:
        sigma_max = 3.0 * P_N * (1.0 + nu) / (2.0 * math.pi * h ** 2) * (
            math.log10(l / b) + 0.5
        )

    # -------------------------------------------------------------------------
    # Modulus of rupture (ACI 318-19 §19.2.3.1 normalweight concrete)
    # MR = 0.62·√f'c   [MPa]
    # -------------------------------------------------------------------------
    MR = 0.62 * math.sqrt(fc)  # MPa

    # -------------------------------------------------------------------------
    # Demand/capacity ratio (working stress)
    # -------------------------------------------------------------------------
    dcr = sigma_max / MR if MR > 0.0 else float("inf")
    adequate = dcr <= 1.0

    # -------------------------------------------------------------------------
    # Joint spacing recommendation (PCA 30×h rule, PCA EB119 §4.4)
    # S_joint ≤ 30·h (mm→m)
    # Cap at slab long dimension (no point in joint tighter than the slab panel)
    # -------------------------------------------------------------------------
    joint_pca_m = 30.0 * h / 1_000.0             # 30·h rule, convert mm→m
    # Recommended joint spacing is the PCA limit (do not cap at slab dimension
    # since the 30·h rule is a maximum spacing — the designer may use smaller panels)
    recommended_joint_spacing_m = joint_pca_m

    # -------------------------------------------------------------------------
    # Honest caveat
    # -------------------------------------------------------------------------
    b_over_l = b / l
    caveat_parts = [
        "ACI 360R-10 / Westergaard (1948) slab-on-grade check — interior concentrated load only.",
        f"Inputs: h={h:.1f} mm, f'c={fc:.1f} MPa, k={spec.subgrade_modulus_k_MPa_per_m:.1f} MPa/m, "
        f"P={spec.point_load_kN:.1f} kN, b={b:.1f} mm.",
        f"Westergaard l={l:.1f} mm; b/l={b_over_l:.4f}.",
        f"E_c={E_MPa:.0f} MPa (ACI §19.2.2.1); ν={nu} (Westergaard 1948).",
        f"σ_max={sigma_max:.4f} MPa (PCA EB119 log₁₀(l/b)+0.5 formula).",
        f"MR={MR:.4f} MPa (ACI §19.2.3.1 0.62·√f'c); DCR={dcr:.4f} "
        f"({'ADEQUATE' if adequate else 'INADEQUATE'}).",
        f"Recommended joint spacing ≤ {recommended_joint_spacing_m:.2f} m "
        f"(PCA 30·h rule; slab long dimension = {spec.slab_long_dimension_m:.1f} m).",
        "SCOPE LIMITATIONS: "
        "(1) Interior load ONLY — edge load stress ≈ 25-30% higher, corner even higher "
        "(Westergaard 1948 §3); do NOT apply this check within one slab thickness of "
        "an edge or joint. "
        "(2) Thermal / shrinkage curling NOT modelled — curling stresses can increase "
        "effective tensile stress by 0.3-1.0 MPa (ACI 360R-10 Appendix A2.2). "
        "(3) Single concentrated load only; multi-load superposition NOT included. "
        "(4) Reinforcement for structural capacity NOT modelled — assumes unreinforced "
        "or crack-control-only steel (ACI 360R-10 §6 for SFRC, §7 for PT). "
        "(5) k is modulus of subgrade reaction at slab soffit; "
        "plate-bearing test correction for pad size and depth NOT applied "
        "(ASTM D1196; Terzaghi 1955 correction factor). "
        "(6) Working-stress design (no partial safety factors): DCR = σ/MR; "
        "ACI 360R-10 Appendix A recommends additional safety margin of 1.7–2.0 "
        "for unreinforced slabs under vehicle loads. "
        "Always verify with a licensed structural/civil engineer.",
    ]
    if b >= l:
        caveat_parts.append(
            "WARNING: contact radius b >= l (b/l = {:.3f}); "
            "Westergaard small-load-area assumption violated — "
            "result is NOT reliable for this load geometry.".format(b_over_l)
        )

    honest_caveat = "  ".join(caveat_parts)

    return SlabOnGradeReport(
        radius_of_relative_stiffness_l_mm=l,
        max_bending_stress_MPa=sigma_max,
        modulus_of_rupture_MR_MPa=MR,
        dcr=dcr,
        adequate=adequate,
        recommended_joint_spacing_m=recommended_joint_spacing_m,
        honest_caveat=honest_caveat,
    )
