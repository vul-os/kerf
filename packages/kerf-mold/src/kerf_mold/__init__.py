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
from kerf_mold.cooling_channel_conflict import (
    CavityWall,
    CoolingChannel3D,
    CoolingConflictReport,
    Conflict as CoolingConflict,
    EjectorPin3D,
    MoldBbox,
    verify_cooling_channels,
)
from kerf_mold.draft_validation import (
    DraftValidationReport,
    FaceInput,
    FaceResult,
    validate_draft,
)
from kerf_mold.runner_layout import (
    RunnerSegment,
    RunnerLayout,
    generate_runner_layout,
    beaumont_runner_diameter,
)
from kerf_mold.gate_placement import (
    CavityBbox,
    GateCandidate,
    GateConstraint,
    GatePlacementResult,
    optimize_gate_placement,
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
    # cooling_channel_conflict.py
    "CavityWall",
    "CoolingChannel3D",
    "CoolingConflictReport",
    "CoolingConflict",
    "EjectorPin3D",
    "MoldBbox",
    "verify_cooling_channels",
    # draft_validation.py
    "DraftValidationReport",
    "FaceInput",
    "FaceResult",
    "validate_draft",
    # runner_layout.py
    "RunnerSegment",
    "RunnerLayout",
    "generate_runner_layout",
    "beaumont_runner_diameter",
    # gate_placement.py
    "CavityBbox",
    "GateCandidate",
    "GateConstraint",
    "GatePlacementResult",
    "optimize_gate_placement",
]
