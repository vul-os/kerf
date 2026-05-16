# kerf-electronics thermoelectric sub-package (Peltier TEC / Seebeck TEG).
# Public API is re-exported from tec.py.
from kerf_electronics.thermoelectric.tec import (
    figure_of_merit,
    tec_operating_point,
    tec_optimal_current,
    tec_delta_t_max,
    tec_couples_required,
    tec_heatsink_coupled,
    tec_multistage,
    teg_output,
    teg_efficiency,
    teg_array,
    teg_fill_factor,
)

__all__ = [
    "figure_of_merit",
    "tec_operating_point",
    "tec_optimal_current",
    "tec_delta_t_max",
    "tec_couples_required",
    "tec_heatsink_coupled",
    "tec_multistage",
    "teg_output",
    "teg_efficiency",
    "teg_array",
    "teg_fill_factor",
]
