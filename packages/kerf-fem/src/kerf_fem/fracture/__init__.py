"""
kerf_fem.fracture — Fracture mechanics sub-package.

Wave 12E: contact mechanics + fracture (J-integral / cohesive zone)

Modules
-------
j_integral         — J-integral (Rice 1968) path-independent contour integral
stress_intensity   — K_I, K_II, K_III from displacement field; ASTM E399
cohesive_zone      — Cohesive zone models (bilinear, exponential, PPR)
fracture_tools     — LLM tool wrappers (auto-registers on import)

SIMPLIFICATION NOTICE
---------------------
This package implements 2-D (plane stress/strain) fracture mechanics.
Production 3-D crack-front analysis (curved fronts, dynamic fracture,
XFEM enrichment) is beyond the scope of this pure-Python module.
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
]
