"""
Acoustic analysis — Sabine reverberation time and STC rating helper.

References:
  Sabine, W. C. (1900). Reverberation. The American Architect.
  ASHRAE Fundamentals 2021, Ch. 8 — Sound and Vibration.
  ASTM E413-16 — Classification for Rating Sound Insulation (STC).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence


# ---------------------------------------------------------------------------
# Sabine RT60
# ---------------------------------------------------------------------------

SABINE_CONSTANT = 0.161  # m·s⁻¹  (metric)  = 4·ln10 / c₀  where c₀ ≈ 343 m/s


def rt60_sabine(volume_m3: float, total_absorption_sabines: float) -> float:
    """Return Sabine reverberation time RT60 in seconds.

    Parameters
    ----------
    volume_m3:
        Room volume in cubic metres.
    total_absorption_sabines:
        Total room absorption in metric Sabines (m²).
        A = Σ(surface_area_i × absorption_coeff_i).

    Returns
    -------
    float
        RT60 in seconds.  RT60 = 0.161 · V / A.

    Raises
    ------
    ValueError
        If volume or absorption are non-positive.
    """
    if volume_m3 <= 0:
        raise ValueError(f"volume_m3 must be positive, got {volume_m3}")
    if total_absorption_sabines <= 0:
        raise ValueError(
            f"total_absorption_sabines must be positive, got {total_absorption_sabines}"
        )
    return SABINE_CONSTANT * volume_m3 / total_absorption_sabines


# ---------------------------------------------------------------------------
# Surface / absorption helpers
# ---------------------------------------------------------------------------

@dataclass
class Surface:
    """A room surface with an area and absorption coefficient."""

    area_m2: float
    absorption_coeff: float  # dimensionless, 0–1

    def sabines(self) -> float:
        """Return the metric Sabines contributed by this surface."""
        return self.area_m2 * self.absorption_coeff


def total_absorption(surfaces: Sequence[Surface]) -> float:
    """Sum absorption across all surfaces, returning total metric Sabines."""
    return sum(s.sabines() for s in surfaces)


# ---------------------------------------------------------------------------
# STC rating helper
# ---------------------------------------------------------------------------

# Reference STC contour values at standard 1/3-octave centre frequencies (Hz).
# Values are the STC contour offsets relative to the STC rating value.
# Source: ASTM E413.
_STC_FREQS_HZ = [125, 160, 200, 250, 315, 400, 500, 630, 800, 1000,
                 1250, 1600, 2000, 2500, 3150, 4000]

# Contour shape: amount (dB) by which STC contour at each frequency exceeds
# the STC rating value.  Positive = contour is above the rating number.
_STC_CONTOUR_OFFSETS = [
    -16, -13, -10, -7, -4, -1, 0, 1, 2, 3,
    3, 3, 3, 3, 3, 3,
]


def stc_rating(tl_values: Sequence[float], freqs_hz: Sequence[float] | None = None) -> int:
    """Estimate the Sound Transmission Class (STC) rating.

    Parameters
    ----------
    tl_values:
        Measured or computed transmission-loss values (dB) at each frequency.
        Must have the same length as ``freqs_hz``.
    freqs_hz:
        Centre frequencies (Hz) corresponding to ``tl_values``.
        Defaults to the standard ASTM E413 1/3-octave set (16 values).

    Returns
    -------
    int
        Estimated STC rating (rounded down to nearest integer).

    Algorithm
    ---------
    Slide the STC reference contour upward from a low STC until the two
    ASTM E413 deficiency constraints are met:
      1. No single deficiency (contour − TL) exceeds 8 dB.
      2. Sum of all deficiencies ≤ 32 dB.
    """
    if freqs_hz is None:
        freqs_hz = _STC_FREQS_HZ

    freqs_hz = list(freqs_hz)
    tl_values = list(tl_values)

    if len(freqs_hz) != len(tl_values):
        raise ValueError(
            f"freqs_hz length ({len(freqs_hz)}) must match tl_values length ({len(tl_values)})"
        )

    # Build interpolated contour offsets for the provided frequencies.
    # For simplicity, use the nearest standard frequency offset.
    def _nearest_offset(f: float) -> float:
        idx = min(range(len(_STC_FREQS_HZ)), key=lambda i: abs(_STC_FREQS_HZ[i] - f))
        return _STC_CONTOUR_OFFSETS[idx]

    offsets = [_nearest_offset(f) for f in freqs_hz]

    # Search for the highest STC rating satisfying ASTM E413 constraints.
    # Try STC values from 0 up to 100.
    best_stc = 0
    for stc_candidate in range(0, 101):
        contour = [stc_candidate + off for off in offsets]
        deficiencies = [max(0.0, contour[i] - tl_values[i]) for i in range(len(freqs_hz))]
        max_def = max(deficiencies)
        sum_def = sum(deficiencies)
        if max_def <= 8 and sum_def <= 32:
            best_stc = stc_candidate
        else:
            # Once constraints are violated the search should continue upwards
            # looking for a fit, but standard ASTM practice stops at the
            # highest passing value.  We continue scanning to be safe.
            pass

    return best_stc
