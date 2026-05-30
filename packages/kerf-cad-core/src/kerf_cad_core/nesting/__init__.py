"""
kerf_cad_core.nesting — 2D part nesting / cut-optimisation for sheet and laser work.

Public surface
--------------
pack.nest_parts(parts, sheet_w, sheet_h, kerf, margin, allow_rotate)
    -> NestResult

optimize_nest.optimize_nest(sheet, parts, options)
    -> OptimizeNestResult   (NFP + GA; Burke 2006 / Kovacs 2002)

tools.nest_parts_tool / tools.nest_report_tool
    -> LLM tool runners registered via @register

optimize_nest_tool.manufacturing_optimize_nest
    -> LLM tool runner registered via @register
"""
from kerf_cad_core.nesting.pack import NestResult, nest_parts
from kerf_cad_core.nesting.optimize_nest import OptimizeNestResult, optimize_nest

__all__ = ["NestResult", "nest_parts", "OptimizeNestResult", "optimize_nest"]
