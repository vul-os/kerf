"""
kerf_cad_core.nesting — 2D part nesting / cut-optimisation for sheet and laser work.

Public surface
--------------
pack.nest_parts(parts, sheet_w, sheet_h, kerf, margin, allow_rotate)
    -> NestResult

tools.nest_parts_tool / tools.nest_report_tool
    -> LLM tool runners registered via @register
"""
from kerf_cad_core.nesting.pack import NestResult, nest_parts

__all__ = ["NestResult", "nest_parts"]
