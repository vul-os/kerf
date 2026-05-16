"""
kerf_cad_core.quoting — one-click fabrication quoting.

Analyses part geometry, classifies viable manufacturing processes, estimates
cost per process via the costing module, and produces a ranked recommendation
with a formatted chat report.

Public API (re-exported from fab_quote.py):
    PartGeometry        — dataclass describing part geometry / features
    analyze_part        — build PartGeometry from a raw geometry_summary dict
    viable_processes    — heuristic process viability list
    cost_per_process    — call costing module, return sorted cost table
    recommend           — pick best process
    quote_report        — formatted summary string

Author: imranparuk
"""

from kerf_cad_core.quoting.fab_quote import (
    PartGeometry,
    analyze_part,
    viable_processes,
    cost_per_process,
    recommend,
    quote_report,
)

__all__ = [
    "PartGeometry",
    "analyze_part",
    "viable_processes",
    "cost_per_process",
    "recommend",
    "quote_report",
]
