"""
kerf_fem.fracture — Fracture mechanics sub-package.

Wave 12E: contact mechanics + fracture (J-integral / cohesive zone)
Wave FEM-gaps: Paris-law crack growth + Erdogan-Sih kink angle
Wave FEM-crack-sim: Incremental crack-propagation simulation on 2-D FEM mesh

Modules
-------
j_integral              — J-integral (Rice 1968) path-independent contour integral
stress_intensity        — K_I, K_II, K_III from displacement field; ASTM E399
cohesive_zone           — Cohesive zone models (bilinear, exponential, PPR)
crack_growth            — Paris-law da/dN integrator; Erdogan-Sih mixed-mode kink angle
crack_growth_sim        — Incremental crack-propagation on 2-D FEM mesh (CST + DCT)
fracture_tools          — LLM tool wrappers (auto-registers on import)
crack_growth_tools      — LLM tool wrapper for fem_crack_growth
crack_growth_sim_tools  — LLM tool wrapper for fem_crack_growth_simulate

SIMPLIFICATION NOTICE
---------------------
This package implements 2-D (plane stress/strain) fracture mechanics.
Incremental simulation uses CST elements + displacement-correlation DCT.
Paris-law crack growth uses geometry-factor SIF (not XFEM enrichment).
Full XFEM (Moës-Dolbow-Belytschko 1999) is deferred to T-100-C.
"""

from kerf_fem.fracture.j_integral import (
    JIntegralContour,
    compute_j_integral,
    domain_integral_j,
    j_to_k,
)
from kerf_fem.fracture.stress_intensity import (
    stress_intensity_from_displacement,
    fracture_toughness_from_load,
    k_to_j,
)
from kerf_fem.fracture.cohesive_zone import (
    CohesiveZoneMaterial,
    traction_separation_bilinear,
    traction_separation_exponential,
    park_paulino_roesler,
    cohesive_fracture_energy,
)
from kerf_fem.fracture.crack_growth import (
    ParisLawParams,
    CrackGrowthResult,
    integrate_paris_law,
    paris_analytic_flat,
    paris_analytic_sent,
    sif_range_sent,
    sif_range_central_crack,
    kink_angle_erdogan_sih,
    effective_sif_mixed_mode,
)

__all__ = [
    "JIntegralContour",
    "compute_j_integral",
    "domain_integral_j",
    "j_to_k",
    "stress_intensity_from_displacement",
    "fracture_toughness_from_load",
    "k_to_j",
    "CohesiveZoneMaterial",
    "traction_separation_bilinear",
    "traction_separation_exponential",
    "park_paulino_roesler",
    "cohesive_fracture_energy",
    "ParisLawParams",
    "CrackGrowthResult",
    "integrate_paris_law",
    "paris_analytic_flat",
    "paris_analytic_sent",
    "sif_range_sent",
    "sif_range_central_crack",
    "kink_angle_erdogan_sih",
    "effective_sif_mixed_mode",
]
