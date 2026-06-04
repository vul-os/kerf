"""
kerf-fem plasticity package.

Wave 12E: material plasticity (J2 / Drucker-Prager / Mohr-Coulomb / Hill)

Exposes the four main material models and the shared return-mapping
infrastructure.  All models use pure Python + NumPy; no SciPy required.

Quick start
-----------
>>> from kerf_fem.plasticity.j2 import J2PlasticityMaterial, J2State, return_map_j2
>>> import numpy as np
>>> mat = J2PlasticityMaterial(200e9, 0.3, 250e6)
>>> stress_trial = np.array([300e6, 0, 0, 0, 0, 0])  # above yield
>>> state_n = J2State()
>>> stress_n1, state_n1, C_ep = return_map_j2(stress_trial, state_n, mat, np.zeros(6))

References
----------
Simo, J.C., Hughes, T.J.R. (1998). "Computational Inelasticity." Springer.
Hill, R. (1948). "A theory of the yielding and plastic flow of anisotropic metals."
Sloan, S.W., Booker, J.R. (1986). "Removal of singularities in Tresca and
    Mohr-Coulomb yield functions."
Lubliner, J. (1990). "Plasticity Theory." MacMillan.
Borja, R.I. (2013). "Plasticity: Modeling & Computation." Springer.
"""

from .j2 import (
    J2PlasticityMaterial,
    J2State,
    return_map_j2,
    von_mises_equivalent,
    yield_function_j2,
)
from .drucker_prager import (
    DruckerPragerMaterial,
    return_map_dp,
    yield_function_dp,
)
from .mohr_coulomb import (
    MohrCoulombMaterial,
    return_map_mc,
    yield_function_mc,
)
from .hill import (
    HillAnisotropicMaterial,
    return_map_hill,
    yield_function_hill,
)
from .return_mapping import (
    voigt_to_tensor,
    tensor_to_voigt,
    deviator,
    first_invariant,
    second_invariant_deviator,
    elastic_stiffness_6x6,
    newton_solve_consistency,
    dev_norm,
    voigt_inner,
)

__all__ = [
    # J2
    "J2PlasticityMaterial",
    "J2State",
    "return_map_j2",
    "von_mises_equivalent",
    "yield_function_j2",
    # Drucker-Prager
    "DruckerPragerMaterial",
    "return_map_dp",
    "yield_function_dp",
    # Mohr-Coulomb
    "MohrCoulombMaterial",
    "return_map_mc",
    "yield_function_mc",
    # Hill
    "HillAnisotropicMaterial",
    "return_map_hill",
    "yield_function_hill",
    # Utilities
    "voigt_to_tensor",
    "tensor_to_voigt",
    "deviator",
    "first_invariant",
    "second_invariant_deviator",
    "elastic_stiffness_6x6",
    "newton_solve_consistency",
    "dev_norm",
    "voigt_inner",
]
