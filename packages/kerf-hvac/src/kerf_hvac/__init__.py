"""kerf-hvac: HVAC duct fabrication plugin for Kerf.

Provides:
- DuctSystem data model (rectangular, round, oval ducts; elbow/reducer/tee/cap/flex fittings)
- ASHRAE velocity method duct sizing
- Sheet-metal flat-pattern generation for rectangular elbow and reducer
- Darcy-Weisbach pressure drop + ASHRAE minor-loss coefficients
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
from kerf_hvac.ahri_catalogue import (
    EquipmentModel,
    lookup_equipment,
    VALID_CATEGORIES,
)

__all__ = [
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
    "EquipmentModel",
    "lookup_equipment",
    "VALID_CATEGORIES",
]
