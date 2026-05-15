# kerf-electronics signal-integrity sub-package.
# Public API is re-exported from solver.py.
from kerf_electronics.si.solver import (
    microstrip_z0,
    stripline_z0,
    diff_z0,
    propagation_delay_ps_per_mm,
    flight_time_ps,
    crosstalk_next,
    crosstalk_fext,
    reflection_coefficient,
    termination_recommendation,
)

__all__ = [
    "microstrip_z0",
    "stripline_z0",
    "diff_z0",
    "propagation_delay_ps_per_mm",
    "flight_time_ps",
    "crosstalk_next",
    "crosstalk_fext",
    "reflection_coefficient",
    "termination_recommendation",
]
