"""
kerf_cad_core.costing — parametric manufacturing should-cost estimation.

Provides process-specific should-cost models (CNC machining, casting,
injection moulding, sheet metal, 3D printing, assembly) and a generic
direct-cost roll-up with batch-size breakpoints, Wright learning curve,
and make-vs-buy comparison.

Public API (re-exported from estimate.py):
    cnc_cost          — CNC machining should-cost
    casting_cost      — Sand/investment casting should-cost
    injection_cost    — Injection moulding should-cost
    sheet_metal_cost  — Sheet metal blank + bends + setup
    printing_cost     — FDM/SLA/SLS 3D printing should-cost
    assembly_cost     — Labour-time-based assembly cost
    rollup            — Generic direct-cost roll-up + margin
    batch_curve       — Cost-vs-batch breakpoints
    learning_curve    — Wright learning curve unit cost
    make_vs_buy       — Make vs. buy comparison

Author: imranparuk
"""

from kerf_cad_core.costing.estimate import (
    cnc_cost,
    casting_cost,
    injection_cost,
    sheet_metal_cost,
    printing_cost,
    assembly_cost,
    rollup,
    batch_curve,
    learning_curve,
    make_vs_buy,
)

__all__ = [
    "cnc_cost",
    "casting_cost",
    "injection_cost",
    "sheet_metal_cost",
    "printing_cost",
    "assembly_cost",
    "rollup",
    "batch_curve",
    "learning_curve",
    "make_vs_buy",
]
