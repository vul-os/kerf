"""
kerf_cad_core.refrigeration — vapor-compression refrigeration & heat-pump design.

Distinct from:
  thermocycle/  — idealized gas/Rankine cycles (air-standard, steam)
  hvac/         — duct sizing, airside systems
  psychro/      — moist-air properties
  heatxfer/     — conduction, convection, radiation

Public API:

    from kerf_cad_core.refrigeration import (
        saturation_pressure,
        single_stage_cycle,
        tons_of_refrigeration,
        compressor_sizing,
        superheat_subcool_effect,
        two_stage_cycle,
        cascade_cycle,
        defrost_energy,
        pressure_ratio_check,
        SUPPORTED_REFRIGERANTS,
        TR_TO_W,
        W_TO_TR,
    )

References
----------
ASHRAE Fundamentals Handbook, 2021 edition.
Stoecker, W.F. & Jones, J.W., "Refrigeration and Air Conditioning", 2nd ed.
Cengel, Y.A. & Boles, M.A., "Thermodynamics: An Engineering Approach", 8th ed.

Author: imranparuk
"""

from kerf_cad_core.refrigeration.cycle import (
    saturation_pressure,
    single_stage_cycle,
    tons_of_refrigeration,
    compressor_sizing,
    superheat_subcool_effect,
    two_stage_cycle,
    cascade_cycle,
    defrost_energy,
    pressure_ratio_check,
    SUPPORTED_REFRIGERANTS,
    TR_TO_W,
    W_TO_TR,
)

__all__ = [
    "saturation_pressure",
    "single_stage_cycle",
    "tons_of_refrigeration",
    "compressor_sizing",
    "superheat_subcool_effect",
    "two_stage_cycle",
    "cascade_cycle",
    "defrost_energy",
    "pressure_ratio_check",
    "SUPPORTED_REFRIGERANTS",
    "TR_TO_W",
    "W_TO_TR",
]
