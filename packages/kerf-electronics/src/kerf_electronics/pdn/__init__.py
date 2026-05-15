"""
Power Distribution Network (PDN) analysis for kerf-electronics.

DC IR-drop solver (resistive plane/trace mesh), target-impedance estimator,
and decoupling-capacitor count estimator.

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

__all__ = [
    "PDNNode",
    "PDNSegment",
    "PDNResult",
    "sheet_resistance_ohms_per_sq",
    "trace_resistance",
    "solve_ir_drop",
    "target_impedance",
    "decap_count_estimate",
]
