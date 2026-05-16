"""
kerf-electronics: analog filter design sub-package.

Distinct from:
  • kerf_electronics.si      — signal integrity (Z0, propagation, crosstalk)
  • kerf_electronics.emc     — EMC/EMI pre-compliance estimation
  • kerf_electronics.rfmatch — RF impedance-matching network synthesis

Provides pure-Python (math/cmath only) tools for:
  - Required filter order from passband/stopband ripple/frequency specs
  - Normalised LP prototype pole locations and ladder g-values
    (Butterworth, Chebyshev-I, Bessel)
  - LP→LP/HP/BP frequency and impedance denormalisation to RLC values
  - First/second-order op-amp topologies (Sallen-Key, Multiple-Feedback)
  - Magnitude (dB), phase, and group-delay at a frequency

Author: imranparuk
"""
from kerf_electronics.afilter.design import (
    butterworth_order,
    chebyshev_order,
    bessel_order,
    butterworth_poles,
    chebyshev_poles,
    bessel_poles,
    butterworth_g_values,
    chebyshev_g_values,
    lp_to_lp_rlc,
    lp_to_hp_rlc,
    lp_to_bp_rlc,
    sallen_key_components,
    multiple_feedback_components,
    filter_response,
)

__all__ = [
    "butterworth_order",
    "chebyshev_order",
    "bessel_order",
    "butterworth_poles",
    "chebyshev_poles",
    "bessel_poles",
    "butterworth_g_values",
    "chebyshev_g_values",
    "lp_to_lp_rlc",
    "lp_to_hp_rlc",
    "lp_to_bp_rlc",
    "sallen_key_components",
    "multiple_feedback_components",
    "filter_response",
]
