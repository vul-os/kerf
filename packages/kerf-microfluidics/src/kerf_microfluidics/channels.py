"""
Microchannel hydraulic resistance and pressure-flow relations.

References
----------
Bruus, H. (2008). *Theoretical Microfluidics*. Oxford University Press.
  - Rectangular channel: eq. 2.27 (approximation valid for h ≤ w)
  - Circular channel: Hagen-Poiseuille, eq. 2.10

All SI units throughout (Pa·s, m, m³/s, Pa).
"""

from __future__ import annotations

import math


# ---------------------------------------------------------------------------
# Rectangular microchannel
# ---------------------------------------------------------------------------

def rect_channel_resistance(
    mu: float,
    L: float,
    w: float,
    h: float,
) -> float:
    """
    Hydraulic resistance of a rectangular microchannel (h ≤ w assumed).

    Uses the Bruus approximation (exact to the leading Fourier-series correction):

        R = 12 μ L / (w h³ (1 − 0.63 h/w))

    Parameters
    ----------
    mu : float
        Dynamic viscosity [Pa·s].
    L : float
        Channel length [m].
    w : float
        Channel width (larger cross-sectional dimension) [m].
    h : float
        Channel height (smaller cross-sectional dimension) [m].
        Must satisfy h ≤ w.

    Returns
    -------
    float
        Hydraulic resistance R [Pa·s/m³].

    Raises
    ------
    ValueError
        If any dimension is non-positive, or h > w.
    """
    if mu <= 0:
        raise ValueError(f"Dynamic viscosity must be positive; got {mu}")
    if L <= 0:
        raise ValueError(f"Channel length must be positive; got {L}")
    if w <= 0:
        raise ValueError(f"Channel width must be positive; got {w}")
    if h <= 0:
        raise ValueError(f"Channel height must be positive; got {h}")
    if h > w:
        raise ValueError(
            f"h ({h}) must be ≤ w ({w}); swap dimensions so h is the smaller side."
        )

    numerator = 12.0 * mu * L
    denominator = w * h**3 * (1.0 - 0.63 * h / w)
    return numerator / denominator


def circ_channel_resistance(
    mu: float,
    L: float,
    r: float,
) -> float:
    """
    Hydraulic resistance of a circular (cylindrical) microchannel.

    Hagen-Poiseuille:

        R = 8 μ L / (π r⁴)

    Parameters
    ----------
    mu : float
        Dynamic viscosity [Pa·s].
    L : float
        Channel length [m].
    r : float
        Channel radius [m].

    Returns
    -------
    float
        Hydraulic resistance R [Pa·s/m³].
    """
    if mu <= 0:
        raise ValueError(f"Dynamic viscosity must be positive; got {mu}")
    if L <= 0:
        raise ValueError(f"Channel length must be positive; got {L}")
    if r <= 0:
        raise ValueError(f"Channel radius must be positive; got {r}")

    return 8.0 * mu * L / (math.pi * r**4)


# ---------------------------------------------------------------------------
# Pressure-flow
# ---------------------------------------------------------------------------

def pressure_drop(Q: float, R: float) -> float:
    """
    Pressure drop across a channel segment.

        ΔP = Q · R

    Parameters
    ----------
    Q : float
        Volumetric flow rate [m³/s].
    R : float
        Hydraulic resistance [Pa·s/m³].

    Returns
    -------
    float
        Pressure drop ΔP [Pa].
    """
    return Q * R


def flow_rate(delta_p: float, R: float) -> float:
    """
    Volumetric flow rate for a given pressure drop.

        Q = ΔP / R

    Parameters
    ----------
    delta_p : float
        Applied pressure difference [Pa].
    R : float
        Hydraulic resistance [Pa·s/m³].

    Returns
    -------
    float
        Flow rate Q [m³/s].
    """
    if R <= 0:
        raise ValueError(f"Resistance must be positive; got {R}")
    return delta_p / R
