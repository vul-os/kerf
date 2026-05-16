# kerf-electronics sensor signal-conditioning sub-package.
# Public API is re-exported from condition.py.
from kerf_electronics.sensorcond.condition import (
    wheatstone_bridge_output,
    bridge_excitation_power,
    strain_to_stress,
    rtd_resistance,
    rtd_temperature,
    rtd_lead_wire_error,
    thermocouple_temperature,
    instrumentation_amp_gain,
    adc_required_bits,
    enob_from_noise,
    antialias_filter_corner,
    loop_4_20ma_scaling,
    loop_burden_voltage,
    noise_budget_rss,
    filter_topology_select,
)

__all__ = [
    "wheatstone_bridge_output",
    "bridge_excitation_power",
    "strain_to_stress",
    "rtd_resistance",
    "rtd_temperature",
    "rtd_lead_wire_error",
    "thermocouple_temperature",
    "instrumentation_amp_gain",
    "adc_required_bits",
    "enob_from_noise",
    "antialias_filter_corner",
    "loop_4_20ma_scaling",
    "loop_burden_voltage",
    "noise_budget_rss",
    "filter_topology_select",
]
