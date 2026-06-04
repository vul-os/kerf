"""
kerf_fem.multiphysics — bidirectional thermo-elastic coupled FEA.

Wave 12E: thermal-structural coupled + composite laminate + Tsai-Wu.

Modules
-------
thermal_structural   : staggered + monolithic thermo-elastic coupling
multiphysics_tools   : LLM tool wrappers
"""

from kerf_fem.multiphysics.thermal_structural import (
    ThermoElasticMaterial,
    CoupledResult,
    solve_thermo_elastic_staggered,
    solve_thermo_elastic_monolithic,
)

__all__ = [
    "ThermoElasticMaterial",
    "CoupledResult",
    "solve_thermo_elastic_staggered",
    "solve_thermo_elastic_monolithic",
]
