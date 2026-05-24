"""
Power Distribution Network (PDN) analysis for kerf-electronics.

DC IR-drop solver (resistive plane/trace mesh), target-impedance estimator,
decoupling-capacitor count estimator, and AC impedance sweep (frequency-domain
Z(ω) analysis from DC to GHz).

Author: imranparuk
"""
from kerf_electronics.pdn.analyzer import (
    PDNNode,
    PDNSegment,
    PDNResult,
    sheet_resistance_ohms_per_sq,
    trace_resistance,
    solve_ir_drop,
    target_impedance,
    decap_count_estimate,
)
from kerf_electronics.pdn.ac_impedance import (
    PDNComponent,
    TargetZResult,
    vrm_impedance,
    bulk_cap_impedance,
    mlcc_impedance,
    plane_impedance,
    via_inductance_h,
    spreading_inductance_h,
    pdn_impedance_sweep,
    target_z_check,
    recommend_decap_bank,
    validate_single_mlcc,
    TOOLS as AC_TOOLS,
)

__all__ = [
    # DC IR-drop
    "PDNNode",
    "PDNSegment",
    "PDNResult",
    "sheet_resistance_ohms_per_sq",
    "trace_resistance",
    "solve_ir_drop",
    "target_impedance",
    "decap_count_estimate",
    # AC impedance
    "PDNComponent",
    "TargetZResult",
    "vrm_impedance",
    "bulk_cap_impedance",
    "mlcc_impedance",
    "plane_impedance",
    "via_inductance_h",
    "spreading_inductance_h",
    "pdn_impedance_sweep",
    "target_z_check",
    "recommend_decap_bank",
    "validate_single_mlcc",
    "AC_TOOLS",
]
