"""
kerf_cad_core.timber — NDS 2018 allowable-stress timber/wood structural design.

Distinct from:
  struct/    — general steel frame analysis (AISC)
  concrete/  — ACI 318 reinforced-concrete design
  steelconn/ — bolted/welded steel connections
  beam/      — generic elastic beam deflection/moment/shear solver

Modules
-------
design  — core calculation functions (pure math, no external deps)
tools   — LLM tool wrappers (@register)

Public re-exports for convenience::

    from kerf_cad_core.timber import (
        CD_load_duration,
        CM_wet,
        Ct_temp,
        CL_beam_stability,
        CF_size,
        Cfu_flat_use,
        Ci_incising,
        Cr_repetitive,
        CP_column_stability,
        FcE_critical,
        Cb_bearing_area,
        sawn_section,
        glulam_section,
        adjusted_Fb,
        adjusted_Fv,
        adjusted_Fc,
        adjusted_Fc_perp,
        adjusted_E_prime,
        bending_stress,
        shear_stress,
        check_bending,
        check_shear,
        check_deflection,
        check_compression_column,
        check_combined_bending_axial,
        check_bearing,
        lateral_yield_bolt,
        withdrawal_nail,
        reference_design_values,
    )

Units: US-customary throughout (lb, in, psi, ft) unless noted.

References
----------
NDS 2018 — National Design Specification for Wood Construction (AWC)
NDS Supplement 2018 — Design Values for Wood Construction
Breyer, D.E. et al. "Design of Wood Structures", 7th ed.

Author: imranparuk
"""

from kerf_cad_core.timber.design import (
    CD_load_duration,
    CM_wet,
    Ct_temp,
    CL_beam_stability,
    CF_size,
    Cfu_flat_use,
    Ci_incising,
    Cr_repetitive,
    CP_column_stability,
    FcE_critical,
    Cb_bearing_area,
    sawn_section,
    glulam_section,
    adjusted_Fb,
    adjusted_Fv,
    adjusted_Fc,
    adjusted_Fc_perp,
    adjusted_E_prime,
    bending_stress,
    shear_stress,
    check_bending,
    check_shear,
    check_deflection,
    check_compression_column,
    check_combined_bending_axial,
    check_bearing,
    lateral_yield_bolt,
    withdrawal_nail,
    reference_design_values,
)

__all__ = [
    "CD_load_duration",
    "CM_wet",
    "Ct_temp",
    "CL_beam_stability",
    "CF_size",
    "Cfu_flat_use",
    "Ci_incising",
    "Cr_repetitive",
    "CP_column_stability",
    "FcE_critical",
    "Cb_bearing_area",
    "sawn_section",
    "glulam_section",
    "adjusted_Fb",
    "adjusted_Fv",
    "adjusted_Fc",
    "adjusted_Fc_perp",
    "adjusted_E_prime",
    "bending_stress",
    "shear_stress",
    "check_bending",
    "check_shear",
    "check_deflection",
    "check_compression_column",
    "check_combined_bending_axial",
    "check_bearing",
    "lateral_yield_bolt",
    "withdrawal_nail",
    "reference_design_values",
]
