# kerf-electronics ADC/DAC data-converter design sub-package.
# Public API is re-exported from converters.py.
from kerf_electronics.dataconv.converters import (
    ideal_snr,
    snr_with_backoff,
    enob_from_sinad,
    snr_sfdr_thd_sinad_interconvert,
    total_noise_budget,
    oversampling_gain,
    delta_sigma_sqnr,
    sar_conversion_time,
    pipeline_latency,
    dac_glitch_sfdr,
    reference_noise_lsb,
    adc_driver_settling,
    bits_for_dynamic_range,
)

__all__ = [
    "ideal_snr",
    "snr_with_backoff",
    "enob_from_sinad",
    "snr_sfdr_thd_sinad_interconvert",
    "total_noise_budget",
    "oversampling_gain",
    "delta_sigma_sqnr",
    "sar_conversion_time",
    "pipeline_latency",
    "dac_glitch_sfdr",
    "reference_noise_lsb",
    "adc_driver_settling",
    "bits_for_dynamic_range",
]
