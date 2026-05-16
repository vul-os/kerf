"""
kerf_cad_core.combustion — combustion & fuels engineering calculators.

Distinct from thermocycle/ (power cycles) and heatxfer/.

Public API (re-exported for convenience):

    from kerf_cad_core.combustion import (
        stoich_afr,
        equivalence_ratio,
        product_composition,
        adiabatic_flame_temp,
        hhv_to_lhv,
        combustion_efficiency,
        flue_gas_dew_point,
        co2_max,
        fuel_power,
        FUELS,
    )

References
----------
Turns, S.R., "An Introduction to Combustion", 3rd ed.
Baukal, C.E. (ed.), "The John Zink Hamworthy Combustion Handbook", 2nd ed.
Siegert, F., VDI-Wärmeatlas — Abgasverluste
Borman, G.L. & Ragland, K.W., "Combustion Engineering"

Author: imranparuk
"""

from kerf_cad_core.combustion.burn import (
    stoich_afr,
    equivalence_ratio,
    product_composition,
    adiabatic_flame_temp,
    hhv_to_lhv,
    combustion_efficiency,
    flue_gas_dew_point,
    co2_max,
    fuel_power,
    FUELS,
)

__all__ = [
    "stoich_afr",
    "equivalence_ratio",
    "product_composition",
    "adiabatic_flame_temp",
    "hhv_to_lhv",
    "combustion_efficiency",
    "flue_gas_dew_point",
    "co2_max",
    "fuel_power",
    "FUELS",
]
