"""
kerf_cad_core.concrete — ACI 318 reinforced-concrete design calculators.

Distinct from:
  struct/   — steel frame analysis (AISC)
  steelconn/ — steel connection design
  geotech/  — soil / foundation

Modules
-------
design  — core calculation functions (pure math, no external deps)
tools   — LLM tool wrappers (@register)

Public re-exports for convenience::

    from kerf_cad_core.concrete import (
        beam_flexure,
        beam_required_As,
        beam_shear,
        tbeam_effective_flange,
        column_axial,
        column_pm_interaction,
        development_length,
        slab_one_way,
        immediate_deflection,
        crack_control,
    )

Units: US-customary throughout (lb, in, kip, psi, ksi, ft) unless noted.

References
----------
ACI 318-19 "Building Code Requirements for Structural Concrete"
McCormac, J.C. & Brown, R.H. "Design of Reinforced Concrete", 9th ed.
Wight, J.K. "Reinforced Concrete: Mechanics and Design", 8th ed.

Author: imranparuk
"""

from kerf_cad_core.concrete.design import (
    beam_flexure,
    beam_required_As,
    beam_shear,
    tbeam_effective_flange,
    column_axial,
    column_pm_interaction,
    development_length,
    slab_one_way,
    immediate_deflection,
    crack_control,
)

__all__ = [
    "beam_flexure",
    "beam_required_As",
    "beam_shear",
    "tbeam_effective_flange",
    "column_axial",
    "column_pm_interaction",
    "development_length",
    "slab_one_way",
    "immediate_deflection",
    "crack_control",
]
