# kerf_plc.llm — LLM-callable PLC analysis + simulation + synthesis tools.

# Each module loads independently; failure in one shouldn't block the others.
try:
    from .make_ladder import make_ladder_program
except ImportError:  # pragma: no cover
    make_ladder_program = None

try:
    from .transpile import convert_st_to_ladder, convert_ladder_to_st, TranspileError
except ImportError:  # pragma: no cover
    convert_st_to_ladder = None
    convert_ladder_to_st = None
    TranspileError = None

try:
    from .analyze import (
        find_double_coil_writes,
        find_self_latching,
        find_unused_variables,
        find_dangling_inputs,
        find_race_conditions,
        simulate_ladder,
        count_edges,
    )
except ImportError:  # pragma: no cover
    pass

__all__ = [
    "make_ladder_program",
    "convert_st_to_ladder",
    "convert_ladder_to_st",
    "TranspileError",
    "find_double_coil_writes",
    "find_self_latching",
    "find_unused_variables",
    "find_dangling_inputs",
    "find_race_conditions",
    "simulate_ladder",
    "count_edges",
]
