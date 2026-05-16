# kerf-electronics oscillator sub-package.
# Crystal oscillator & PLL design — pure Python, math only.
from kerf_electronics.oscillator.design import (
    crystal_load_caps,
    pierce_negative_resistance,
    drive_level_estimate,
    frequency_pulling,
    ppm_error_budget,
    rc_oscillator_frequency,
    lc_oscillator_frequency,
    ring_oscillator_frequency,
    pll_divider_n,
    pll_type2_loop_filter,
    pll_lock_time,
    phase_noise_to_jitter,
)

__all__ = [
    "crystal_load_caps",
    "pierce_negative_resistance",
    "drive_level_estimate",
    "frequency_pulling",
    "ppm_error_budget",
    "rc_oscillator_frequency",
    "lc_oscillator_frequency",
    "ring_oscillator_frequency",
    "pll_divider_n",
    "pll_type2_loop_filter",
    "pll_lock_time",
    "phase_noise_to_jitter",
]
