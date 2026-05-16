"""
kerf-electronics DSP sub-package — digital signal processing & digital filter design.

Distinct from:
  afilter/  — analog filter design (Butterworth/Chebyshev/Bessel prototypes, S-domain)
  si/       — signal integrity (impedance, propagation delay, crosstalk)
  emc/      — EMC/EMI pre-compliance estimation

Public API re-exported from filters.py.
"""
from kerf_electronics.dsp.filters import (
    fft,
    ifft,
    dft_spectrum,
    bin_frequency,
    windowed_sinc_lp,
    windowed_sinc_hp,
    windowed_sinc_bp,
    fir_order_estimate,
    bilinear_butterworth_lp,
    bilinear_butterworth_hp,
    biquad_lp,
    biquad_hp,
    biquad_bp,
    biquad_notch,
    biquad_peaking,
    freq_response,
    group_delay,
    nyquist_check,
    adc_snr,
)

__all__ = [
    "fft",
    "ifft",
    "dft_spectrum",
    "bin_frequency",
    "windowed_sinc_lp",
    "windowed_sinc_hp",
    "windowed_sinc_bp",
    "fir_order_estimate",
    "bilinear_butterworth_lp",
    "bilinear_butterworth_hp",
    "biquad_lp",
    "biquad_hp",
    "biquad_bp",
    "biquad_notch",
    "biquad_peaking",
    "freq_response",
    "group_delay",
    "nyquist_check",
    "adc_snr",
]
