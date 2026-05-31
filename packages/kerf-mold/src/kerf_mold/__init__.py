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
from kerf_mold.vent_slot_layout import (
    MoldVolumeSpec,
    VentSlotLayoutReport,
    POLYMER_VENT_DEPTH_RANGE,
    generate_vent_slot_layout,
)
from kerf_mold.cooling_pressure_drop import (
    CoolingChannelSegment,
    CoolantSpec,
    CoolingPressureDropReport,
    compute_cooling_pressure_drop,
)
from kerf_mold.runner_diameter_optimize import (
    RunnerOptimizeSpec,
    RunnerOptimizeReport,
    optimize_runner_diameter,
)
from kerf_mold.warpage_index import (
    WarpageSpec,
    WarpageIndexReport,
    compute_warpage_index,
)
from kerf_mold.melt_flow_ratio_check import (
    MeltFlowSpec,
    MeltFlowRatioReport,
    check_melt_flow_ratio,
)
from kerf_mold.sprue_bushing_match import (
    SprueBushingSpec,
    MachineNozzleSpec,
    SprueMatchReport,
    check_sprue_bushing_match,
    R_EXCESS_MIN_MM,
    R_EXCESS_MAX_MM,
    O_EXCESS_MIN_MM,
    O_EXCESS_MAX_MM,
    TAPER_MIN_DEG,
    TAPER_MAX_DEG,
)
from kerf_mold.cooling_turbulent_re_check import (
    CoolingFlowSpec,
    TurbulentReCheckReport,
    check_turbulent_re,
)
from kerf_mold.ejector_pin_push import (
    EjectorPinPushSpec,
    EjectorPinPushReport,
    SPI_EJECTOR_PIN_DIAMETERS_MM as SPI_EJECTOR_PIN_DIAMETERS_MM_PUSH,
    compute_ejector_pin_push,
)
from kerf_mold.core_pin_cooling import (
    CorePinSpec,
    CorePinCoolingReport,
    design_core_pin_cooling,
)
from kerf_mold.tunnel_gate_design import (
    TunnelGateSpec,
    TunnelGateReport,
    design_tunnel_gate,
)
from kerf_mold.color_concentrate_ratio import (
    ColorConcentrateSpec,
    ShotSpec,
    ColorRatioReport,
    LDR_MIN_SPI_PCT,
    LDR_MAX_SPI_PCT,
    LDR_LOW_RISK_PCT,
    LDR_COST_WASTE_PCT,
    MIXING_INDEX_ADEQUATE,
    MIXING_INDEX_POOR,
    compute_color_ratio,
)
from kerf_mold.surface_finish_check import (
    SurfaceFinishSpec,
    MoldSpec,
    SurfaceFinishReport,
    check_surface_finish,
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
    # vent_slot_layout.py
    "MoldVolumeSpec",
    "VentSlotLayoutReport",
    "POLYMER_VENT_DEPTH_RANGE",
    "generate_vent_slot_layout",
    # cooling_pressure_drop.py
    "CoolingChannelSegment",
    "CoolantSpec",
    "CoolingPressureDropReport",
    "compute_cooling_pressure_drop",
    # runner_diameter_optimize.py
    "RunnerOptimizeSpec",
    "RunnerOptimizeReport",
    "optimize_runner_diameter",
    # warpage_index.py
    "WarpageSpec",
    "WarpageIndexReport",
    "compute_warpage_index",
    # melt_flow_ratio_check.py
    "MeltFlowSpec",
    "MeltFlowRatioReport",
    "check_melt_flow_ratio",
    # sprue_bushing_match.py
    "SprueBushingSpec",
    "MachineNozzleSpec",
    "SprueMatchReport",
    "check_sprue_bushing_match",
    "R_EXCESS_MIN_MM",
    "R_EXCESS_MAX_MM",
    "O_EXCESS_MIN_MM",
    "O_EXCESS_MAX_MM",
    "TAPER_MIN_DEG",
    "TAPER_MAX_DEG",
    # cooling_turbulent_re_check.py
    "CoolingFlowSpec",
    "TurbulentReCheckReport",
    "check_turbulent_re",
    # ejector_pin_push.py
    "EjectorPinPushSpec",
    "EjectorPinPushReport",
    "SPI_EJECTOR_PIN_DIAMETERS_MM_PUSH",
    "compute_ejector_pin_push",
    # core_pin_cooling.py
    "CorePinSpec",
    "CorePinCoolingReport",
    "design_core_pin_cooling",
    # tunnel_gate_design.py
    "TunnelGateSpec",
    "TunnelGateReport",
    "design_tunnel_gate",
    # color_concentrate_ratio.py
    "ColorConcentrateSpec",
    "ShotSpec",
    "ColorRatioReport",
    "LDR_MIN_SPI_PCT",
    "LDR_MAX_SPI_PCT",
    "LDR_LOW_RISK_PCT",
    "LDR_COST_WASTE_PCT",
    "MIXING_INDEX_ADEQUATE",
    "MIXING_INDEX_POOR",
    "compute_color_ratio",
    # surface_finish_check.py
    "SurfaceFinishSpec",
    "MoldSpec",
    "SurfaceFinishReport",
    "check_surface_finish",
]
