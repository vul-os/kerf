"""kerf-mold: injection-mold tooling design plugin for Kerf."""

from kerf_mold.mold import (
    Face,
    EjectorPin,
    GateLocation,
    PartingLine,
    MoldDesign,
    check_moldability,
    generate_parting_surface,
    draft_angle_per_face,
)
from kerf_mold.ejector_pin_planner import (
    BossFeature,
    Conflict,
    CoolingChannelXY,
    EjectorPin as EjectorPinXY,
    PartGeometry,
    RibFeature,
    plan_ejector_pins,
    compute_ejection_force_distribution,
    detect_pin_conflicts,
    compute_warpage_risk,
    SPI_STANDARD_DIAMETERS_MM,
)

__all__ = [
    # mold.py
    "Face",
    "EjectorPin",
    "GateLocation",
    "PartingLine",
    "MoldDesign",
    "check_moldability",
    "generate_parting_surface",
    "draft_angle_per_face",
    # ejector_pin_planner.py
    "BossFeature",
    "Conflict",
    "CoolingChannelXY",
    "EjectorPinXY",
    "PartGeometry",
    "RibFeature",
    "plan_ejector_pins",
    "compute_ejection_force_distribution",
    "detect_pin_conflicts",
    "compute_warpage_risk",
    "SPI_STANDARD_DIAMETERS_MM",
]
