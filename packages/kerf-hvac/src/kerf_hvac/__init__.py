"""kerf-hvac: HVAC duct fabrication + air-side system modelling plugin for Kerf.

Provides:
- DuctSystem data model (rectangular, round, oval ducts; elbow/reducer/tee/cap/flex fittings)
- ASHRAE velocity method duct sizing
- ASHRAE §35 equal-friction duct sizing optimizer
- Sheet-metal flat-pattern generation for rectangular elbow and reducer
- Darcy-Weisbach pressure drop + ASHRAE minor-loss coefficients
- Air-side AHU system model: psychrometrics, cooling/heating coils, economizer,
  VAV terminal boxes, supply/return fans, duct static pressure, plant coupling
- LLM tool surface
"""

from kerf_hvac.duct import (
    DuctShape,
    DuctSection,
    Fitting,
    FittingType,
    DuctSystem,
)
from kerf_hvac.sizing import size_duct
from kerf_hvac.flat_pattern import rect_elbow_pattern, rect_reducer_pattern
from kerf_hvac.pressure import (
    darcy_weisbach_loss,
    minor_loss,
    ELBOW_90_RECT_K,
    ELBOW_90_ROUND_K,
    TEE_MAIN_K,
    TEE_BRANCH_K,
)
from kerf_hvac.duct_sizing_optimizer import (
    equal_friction_size,
    size_duct_run,
    compute_duct_cost,
    SizedSegment,
)
from kerf_hvac.airside import (
    AirState,
    AHUConfig,
    VAVZone,
    PlantCoupling,
    simulate_ahu_system,
    cooling_coil,
    heating_coil,
    fan_power,
    economizer_control,
    vav_box,
    humidity_ratio_from_rh,
    enthalpy_kj_kg,
    saturation_pressure_pa,
)

__all__ = [
    # Duct system
    "DuctShape",
    "DuctSection",
    "Fitting",
    "FittingType",
    "DuctSystem",
    "size_duct",
    "rect_elbow_pattern",
    "rect_reducer_pattern",
    "darcy_weisbach_loss",
    "minor_loss",
    "ELBOW_90_RECT_K",
    "ELBOW_90_ROUND_K",
    "TEE_MAIN_K",
    "TEE_BRANCH_K",
    "equal_friction_size",
    "size_duct_run",
    "compute_duct_cost",
    "SizedSegment",
    # Air-side system
    "AirState",
    "AHUConfig",
    "VAVZone",
    "PlantCoupling",
    "simulate_ahu_system",
    "cooling_coil",
    "heating_coil",
    "fan_power",
    "economizer_control",
    "vav_box",
    "humidity_ratio_from_rh",
    "enthalpy_kj_kg",
    "saturation_pressure_pa",
]
