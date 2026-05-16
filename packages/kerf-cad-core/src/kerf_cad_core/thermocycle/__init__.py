"""
kerf_cad_core.thermocycle — thermodynamic power/refrigeration cycle analysis.

Distinct from heatxfer/ (conduction/convection) and hvac/ (duct sizing).
Covers ideal-gas process relations, standard air cycles, Rankine, refrigeration,
and associated COP / efficiency metrics.

Public API (re-exported for convenience):

    from kerf_cad_core.thermocycle import (
        # Ideal-gas process relations
        isothermal_process,
        isobaric_process,
        isochoric_process,
        isentropic_process,
        polytropic_process,
        # Efficiency limits
        carnot_efficiency,
        carnot_cop_refrigeration,
        carnot_cop_heat_pump,
        # Air-standard power cycles
        otto_cycle,
        diesel_cycle,
        dual_cycle,
        brayton_cycle,
        # Rankine (steam) cycle
        rankine_cycle_ideal,
        # Refrigeration / heat-pump
        refrigeration_cop,
        # Isentropic relations helper
        isentropic_relations,
    )

References
----------
Cengel, Y.A. & Boles, M.A., "Thermodynamics: An Engineering Approach", 8th ed.
Moran, M.J. et al., "Fundamentals of Engineering Thermodynamics", 7th ed.

Author: imranparuk
"""

from kerf_cad_core.thermocycle.cycles import (
    isothermal_process,
    isobaric_process,
    isochoric_process,
    isentropic_process,
    polytropic_process,
    carnot_efficiency,
    carnot_cop_refrigeration,
    carnot_cop_heat_pump,
    otto_cycle,
    diesel_cycle,
    dual_cycle,
    brayton_cycle,
    rankine_cycle_ideal,
    refrigeration_cop,
    isentropic_relations,
)

__all__ = [
    "isothermal_process",
    "isobaric_process",
    "isochoric_process",
    "isentropic_process",
    "polytropic_process",
    "carnot_efficiency",
    "carnot_cop_refrigeration",
    "carnot_cop_heat_pump",
    "otto_cycle",
    "diesel_cycle",
    "dual_cycle",
    "brayton_cycle",
    "rankine_cycle_ideal",
    "refrigeration_cop",
    "isentropic_relations",
]
