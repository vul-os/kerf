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
from kerf_mold.vent_placement import (
    CavityBbox as VentCavityBbox,
    VentLocation,
    VentPlacementResult,
    optimize_vent_placement,
)
from kerf_mold.ejector_stroke_verify import (
    EjectorPinSpec,
    EjectorStrokeReport,
    PinDeflectionResult,
    verify_ejector_stroke,
    DEFAULT_ALLOWABLE_DEFLECTION_MM,
    STEEL_E_N_MM2,
)
from kerf_mold.flow_length_check import (
    FlowFeature,
    FlowLengthReport,
    MATERIAL_LT_LIMITS,
    compute_flow_length_check,
)
from kerf_mold.cooling_time_chen_chiang import (
    MaterialThermalProps,
    CoolingTimeReport,
    MATERIAL_THERMAL_DB,
    compute_cooling_time_chen_chiang,
)
from kerf_mold.runner_balance_check import (
    RunnerSegment as BalanceRunnerSegment,
    RunnerBalanceReport,
    check_runner_balance,
)
from kerf_mold.gate_vestige_check import (
    GateSpec,
    GateVestigeReport,
    COSMETIC_CLASS_LIMITS_MM,
    check_gate_vestige,
)
from kerf_mold.demold_force_check import (
    MoldedPartSpec,
    DemoldForceReport,
    SHRINKAGE_STRESS_MPA,
    FRICTION_COEFF,
    compute_demold_force,
)
from kerf_mold.vent_depth_check import (
    VentSpec,
    VentDepthReport,
    VENT_DEPTH_DB,
    check_vent_depth,
)
from kerf_mold.cold_slug_check import (
    RunnerJunctionSpec,
    ColdSlugReport,
    check_cold_slug_design,
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
    # vent_placement.py
    "VentCavityBbox",
    "VentLocation",
    "VentPlacementResult",
    "optimize_vent_placement",
    # ejector_stroke_verify.py
    "EjectorPinSpec",
    "EjectorStrokeReport",
    "PinDeflectionResult",
    "verify_ejector_stroke",
    "DEFAULT_ALLOWABLE_DEFLECTION_MM",
    "STEEL_E_N_MM2",
    # flow_length_check.py
    "FlowFeature",
    "FlowLengthReport",
    "MATERIAL_LT_LIMITS",
    "compute_flow_length_check",
    # cooling_time_chen_chiang.py
    "MaterialThermalProps",
    "CoolingTimeReport",
    "MATERIAL_THERMAL_DB",
    "compute_cooling_time_chen_chiang",
    # runner_balance_check.py
    "BalanceRunnerSegment",
    "RunnerBalanceReport",
    "check_runner_balance",
    # gate_vestige_check.py
    "GateSpec",
    "GateVestigeReport",
    "COSMETIC_CLASS_LIMITS_MM",
    "check_gate_vestige",
    # demold_force_check.py
    "MoldedPartSpec",
    "DemoldForceReport",
    "SHRINKAGE_STRESS_MPA",
    "FRICTION_COEFF",
    "compute_demold_force",
    # vent_depth_check.py
    "VentSpec",
    "VentDepthReport",
    "VENT_DEPTH_DB",
    "check_vent_depth",
    # cold_slug_check.py
    "RunnerJunctionSpec",
    "ColdSlugReport",
    "check_cold_slug_design",
]
