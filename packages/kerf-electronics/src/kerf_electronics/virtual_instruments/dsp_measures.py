"""
dsp_measures.py — pure-Python DSP measurement functions for the virtual
instrument bench.  All functions operate on plain Python lists / tuples of
floats and have no external dependencies beyond ``math``.

Public API
----------
    measure_vpp(y)          -> float
    measure_frequency(t, y) -> float | None
    measure_rise_time(t, y, low_pct=0.10, high_pct=0.90) -> float | None
    measure_rms(y)          -> float
    measure_dc(y)           -> float
    measure_ac_rms(y)       -> float

All functions raise ``ValueError`` on empty / invalid inputs.

References
----------
- Vpp:       standard oscilloscope peak-to-peak definition
- RMS:       Parseval / discrete sqrt(mean(y²))
- Frequency: zero-crossing method (positive slope) — Tektronix AWG Guide §3.2
- Rise time: 10%–90% threshold crossing (IEEE 181-2011 §3.2.1)
- DC value:  arithmetic mean
- AC RMS:    sqrt(RMS² − DC²)  (IEC 60469 §4)
"""

from __future__ import annotations

import math
from typing import Sequence


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_non_empty(y: Sequence[float], name: str = "y") -> None:
    if not y:
        raise ValueError(f"{name} must be a non-empty sequence of floats")


def _to_floats(seq: Sequence) -> list[float]:
    return [float(v) for v in seq]


# ---------------------------------------------------------------------------
# Peak-to-peak voltage
# ---------------------------------------------------------------------------

def measure_vpp(y: Sequence[float]) -> float:
    """Return the peak-to-peak amplitude of *y*.

    Parameters
    ----------
    y:
        Sample array (V or A).

    Returns
    -------
    float
        ``max(y) - min(y)``, always non-negative.

    Raises
    ------
    ValueError
        If *y* is empty.
    """
    _check_non_empty(y)
    vals = _to_floats(y)
    return max(vals) - min(vals)


# ---------------------------------------------------------------------------
# Frequency via zero-crossing
# ---------------------------------------------------------------------------

def measure_frequency(
    t: Sequence[float],
    y: Sequence[float],
) -> float | None:
    """Estimate the dominant frequency of *y* using positive-slope zero crossings.

    Works on sinusoidal and periodic waveforms.  Returns ``None`` when fewer
    than 2 full cycles are detected (insufficient data for a reliable estimate).

    Algorithm
    ---------
    1. Compute mean(y) as a dynamic "zero" reference.
    2. Find all indices where y crosses the mean with a positive slope.
    3. Average the inter-crossing periods to estimate T.
    4. Return 1/T.

    Parameters
    ----------
    t:
        Time axis (seconds).
    y:
        Sample values (V or A).

    Returns
    -------
    float | None
        Frequency in Hz, or ``None`` if fewer than 2 crossings found.

    Raises
    ------
    ValueError
        If *t* or *y* is empty or their lengths differ.
    """
    _check_non_empty(t, "t")
    _check_non_empty(y, "y")
    tf = _to_floats(t)
    yf = _to_floats(y)
    if len(tf) != len(yf):
        raise ValueError(f"t and y must have equal length, got {len(tf)} vs {len(yf)}")
    if len(tf) < 2:
        return None

    mean_y = sum(yf) / len(yf)

    # Collect positive-slope zero-crossings (crossing mean_y upward)
    crossing_times: list[float] = []
    for i in range(1, len(yf)):
        y0, y1 = yf[i - 1] - mean_y, yf[i] - mean_y
        if y0 < 0 and y1 >= 0:
            # Linear interpolation of the crossing time
            frac = abs(y0) / (abs(y0) + abs(y1)) if (abs(y0) + abs(y1)) > 0 else 0.0
            t_cross = tf[i - 1] + frac * (tf[i] - tf[i - 1])
            crossing_times.append(t_cross)

    if len(crossing_times) < 2:
        return None

    # Average period from consecutive crossings
    periods = [
        crossing_times[i] - crossing_times[i - 1]
        for i in range(1, len(crossing_times))
    ]
    avg_period = sum(periods) / len(periods)
    if avg_period <= 0:
        return None
    return 1.0 / avg_period


# ---------------------------------------------------------------------------
# Rise time  (10 % → 90 % threshold)
# ---------------------------------------------------------------------------

def measure_rise_time(
    t: Sequence[float],
    y: Sequence[float],
    low_pct: float = 0.10,
    high_pct: float = 0.90,
) -> float | None:
    """Measure the rise time of the *first* rising edge in *y*.

    Uses the standard 10 %–90 % of the full swing (IEEE 181-2011 §3.2.1).

    The function finds the first upward transition that spans at least
    50 % of the full signal swing, then linearly interpolates the exact
    instants where the waveform crosses ``low_pct`` and ``high_pct`` of the
    full amplitude.

    Parameters
    ----------
    t:
        Time axis (seconds).
    y:
        Sample values (V or A).
    low_pct:
        Lower threshold fraction (default 0.10 = 10 %).
    high_pct:
        Upper threshold fraction (default 0.90 = 90 %).

    Returns
    -------
    float | None
        Rise time in seconds, or ``None`` if no clear rising edge is found.

    Raises
    ------
    ValueError
        If inputs are empty or lengths differ.
    """
    _check_non_empty(t, "t")
    _check_non_empty(y, "y")
    tf = _to_floats(t)
    yf = _to_floats(y)
    if len(tf) != len(yf):
        raise ValueError(f"t and y must have equal length, got {len(tf)} vs {len(yf)}")
    if len(tf) < 2:
        return None

    y_min = min(yf)
    y_max = max(yf)
    swing = y_max - y_min
    if swing <= 0:
        return None  # flat signal

    v_low = y_min + low_pct * swing
    v_high = y_min + high_pct * swing

    def _interp_crossing(idx: int, threshold: float) -> float:
        """Linear interpolation of crossing instant near index *idx*."""
        y0, y1 = yf[idx - 1], yf[idx]
        t0, t1 = tf[idx - 1], tf[idx]
        if y1 == y0:
            return t0
        frac = (threshold - y0) / (y1 - y0)
        return t0 + frac * (t1 - t0)

    # Find first crossing of v_low (upward)
    t_low = None
    low_idx = None
    for i in range(1, len(yf)):
        if yf[i - 1] <= v_low < yf[i]:
            t_low = _interp_crossing(i, v_low)
            low_idx = i
            break

    if t_low is None or low_idx is None:
        return None

    # Find the subsequent crossing of v_high (upward) after low crossing
    t_high = None
    for i in range(low_idx, len(yf)):
        if yf[i - 1] <= v_high < yf[i]:
            t_high = _interp_crossing(i, v_high)
            break

    if t_high is None or t_high <= t_low:
        return None

    return t_high - t_low


# ---------------------------------------------------------------------------
# RMS  (total)
# ---------------------------------------------------------------------------

def measure_rms(y: Sequence[float]) -> float:
    """Compute the root-mean-square of *y*.

    Parameters
    ----------
    y:
        Sample array.

    Returns
    -------
    float
        ``sqrt(mean(y²))``.

    Raises
    ------
    ValueError
        If *y* is empty.
    """
    _check_non_empty(y)
    vals = _to_floats(y)
    return math.sqrt(sum(v * v for v in vals) / len(vals))


# ---------------------------------------------------------------------------
# DC (mean)
# ---------------------------------------------------------------------------

def measure_dc(y: Sequence[float]) -> float:
    """Return the DC component (arithmetic mean) of *y*.

    Raises
    ------
    ValueError
        If *y* is empty.
    """
    _check_non_empty(y)
    vals = _to_floats(y)
    return sum(vals) / len(vals)


# ---------------------------------------------------------------------------
# AC RMS  (RMS of the AC component only)
# ---------------------------------------------------------------------------

def measure_ac_rms(y: Sequence[float]) -> float:
    """Return the AC RMS of *y* (IEC 60469 §4: sqrt(RMS² − DC²)).

    Equivalent to the RMS of the zero-mean signal.

    Raises
    ------
    ValueError
        If *y* is empty.
    """
    _check_non_empty(y)
    rms = measure_rms(y)
    dc = measure_dc(y)
    ac2 = rms * rms - dc * dc
    # Guard against tiny floating-point negatives from cancellation
    return math.sqrt(max(0.0, ac2))
