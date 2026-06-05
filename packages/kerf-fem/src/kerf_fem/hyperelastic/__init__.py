"""
kerf_fem.hyperelastic — Hyperelastic constitutive models.

Implements Mooney-Rivlin (2-parameter), Neo-Hookean, and Ogden (N=1..3)
strain-energy density functions for finite-deformation elasticity.

References
----------
  Holzapfel, G. A. (2000). "Nonlinear Solid Mechanics." Wiley. Ch. 6.
  Ogden, R. W. (1972). "Large deformation isotropic elasticity." Proc. R. Soc.
      London A 326, 565-584.
  Rivlin, R. S. & Saunders, D. W. (1951). Philos. Trans. R. Soc. A 243, 251.
  Treloar, L. R. G. (1943). Trans. Faraday Soc. 39, 241-246 (neo-Hookean).
"""

from kerf_fem.hyperelastic.models import (
    HyperelasticModel,
    neo_hookean_strain_energy,
    neo_hookean_stress,
    neo_hookean_tangent,
    neo_hookean_uniaxial_cauchy,
    mooney_rivlin_strain_energy,
    mooney_rivlin_stress,
    mooney_rivlin_tangent,
    mooney_rivlin_uniaxial_cauchy,
    ogden_strain_energy,
    ogden_stress,
    ogden_tangent,
    ogden_uniaxial_cauchy,
    uniaxial_cauchy_stress,
    uniaxial_response,
    biaxial_response,
    planar_response,
)

__all__ = [
    "HyperelasticModel",
    "neo_hookean_strain_energy",
    "neo_hookean_stress",
    "neo_hookean_tangent",
    "neo_hookean_uniaxial_cauchy",
    "mooney_rivlin_strain_energy",
    "mooney_rivlin_stress",
    "mooney_rivlin_tangent",
    "mooney_rivlin_uniaxial_cauchy",
    "ogden_strain_energy",
    "ogden_stress",
    "ogden_tangent",
    "ogden_uniaxial_cauchy",
    "uniaxial_cauchy_stress",
    "uniaxial_response",
    "biaxial_response",
    "planar_response",
]
