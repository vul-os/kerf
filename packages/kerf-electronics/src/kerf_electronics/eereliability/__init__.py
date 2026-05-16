# kerf-electronics electronics reliability prediction sub-package.
# Public API is re-exported from predict.py.
from kerf_electronics.eereliability.predict import (
    mil217f_parts_count,
    mil217f_part_stress,
    board_fit_and_mtbf,
    arrhenius_acceleration_factor,
    coffin_manson_nf,
    peck_humidity_acceleration,
    voltage_acceleration,
    derating_check,
    bathtub_hazard_rate,
    redundancy_mtbf,
    mtbf_confidence_bound,
    duty_cycle_adjusted_fit,
)

__all__ = [
    "mil217f_parts_count",
    "mil217f_part_stress",
    "board_fit_and_mtbf",
    "arrhenius_acceleration_factor",
    "coffin_manson_nf",
    "peck_humidity_acceleration",
    "voltage_acceleration",
    "derating_check",
    "bathtub_hazard_rate",
    "redundancy_mtbf",
    "mtbf_confidence_bound",
    "duty_cycle_adjusted_fit",
]
