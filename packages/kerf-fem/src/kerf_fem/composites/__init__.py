"""
kerf_fem.composites — Classical Laminate Theory + failure criteria.

Wave 12E: thermal-structural coupled + composite laminate + Tsai-Wu.

Modules
-------
laminate_classical   : CLT ABD matrix, ply-by-ply stress analysis
failure_criteria     : Tsai-Wu, Tsai-Hill, max-stress, max-strain, Puck, Hashin
composite_tools      : LLM tool wrappers

Honest limitation
-----------------
This module implements Classical Laminate Theory (CLT / CLPT) based on
Kirchhoff-Love plate assumptions.  CLT is valid for thin laminates
(span/thickness > ~20).  For thick laminates use First-order Shear Deformation
Theory (FSDT) or Higher-order SDT (HSDT) to capture through-thickness shear.

References
----------
Jones R.M. (1999). "Mechanics of Composite Materials." 2nd ed. Taylor & Francis.
Reddy J.N. (2003). "Mechanics of Laminated Composite Plates and Shells."
  2nd ed. CRC Press.
"""

from kerf_fem.composites.laminate_classical import (
    LaminaPly,
    Laminate,
    LaminateResponse,
    analyze_laminate,
)
from kerf_fem.composites.failure_criteria import (
    FailureResult,
    tsai_wu,
    tsai_hill,
    maximum_stress,
    maximum_strain,
    puck,
    hashin,
    first_ply_failure_analysis,
)

__all__ = [
    "LaminaPly",
    "Laminate",
    "LaminateResponse",
    "analyze_laminate",
    "FailureResult",
    "tsai_wu",
    "tsai_hill",
    "maximum_stress",
    "maximum_strain",
    "puck",
    "hashin",
    "first_ply_failure_analysis",
]
