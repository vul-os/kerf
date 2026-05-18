"""
MEMS cantilever beam: stiffness and resonance frequency.

Uses Euler-Bernoulli beam theory for a rectangular cross-section prismatic
cantilever fixed at one end.

Stiffness (end-loaded)
----------------------
    k = E t³ w / (4 L³)

where
  E  Young's modulus [Pa]
  t  thickness (out-of-plane bending direction) [m]
  w  width (in-plane) [m]
  L  length [m]

Resonance frequency (fundamental flexural mode)
------------------------------------------------
For a free-end cantilever the exact Euler-Bernoulli result is obtained by
solving the transcendental equation cos(βL)cosh(βL) = −1.  The first root
is β₁L ≈ 1.8751040631.  This gives:

    f₁ = (β₁L)² / (2π L²) · √(EI/ρA)

which for a rectangular section (I = wt³/12, A = wt) simplifies to:

    f₁ = (β₁L)² / (2π L²) · t/√12 · √(E/ρ)

The lumped-mass approximation f = 1/(2π)·√(k/m_eff) with m_eff = 0.2427·ρAL
(from the exact mode shape integral) reproduces the same result and is
exposed as a convenience.

References
----------
Senturia, S. D. (2001). *Microsystem Design*. Kluwer Academic Publishers.
  ch. 9 — cantilever beams, stiffness and resonance.
Blevins, R. D. (1979). *Formulas for Natural Frequency and Mode Shape*.
  Van Nostrand Reinhold. Table 8-1.
"""

from __future__ import annotations

import math


# First root of cos(βL)cosh(βL) = -1
_BETA1L: float = 1.8751040631351359


def cantilever_stiffness(
    E: float,
    t: float,
    w: float,
    L: float,
) -> float:
    """
    End-loaded stiffness of a rectangular cantilever beam.

        k = E t³ w / (4 L³)

    Parameters
    ----------
    E : float
        Young's modulus [Pa].
    t : float
        Beam thickness (bending direction) [m].
    w : float
        Beam width [m].
    L : float
        Beam length [m].

    Returns
    -------
    float
        Stiffness k [N/m].

    Raises
    ------
    ValueError
        If any parameter is non-positive.
    """
    for name, val in [("E", E), ("t", t), ("w", w), ("L", L)]:
        if val <= 0:
            raise ValueError(f"{name} must be positive; got {val}")

    return E * t**3 * w / (4.0 * L**3)


def cantilever_resonance(
    E: float,
    rho: float,
    t: float,
    w: float,
    L: float,
) -> float:
    """
    Fundamental flexural resonance frequency of a rectangular cantilever beam
    (free-end, fixed at base) using exact Euler-Bernoulli beam theory.

    The exact result for the first mode is:

        f₁ = (β₁L)² / (2π L²) · √(EI / ρA)

    For a rectangular cross-section (I = wt³/12, A = wt) this reduces to:

        f₁ = (β₁L)² · t / (2π L² √12) · √(E/ρ)

    where β₁L ≈ 1.8751040631 is the first root of cos(βL)cosh(βL) = −1.

    Parameters
    ----------
    E : float
        Young's modulus [Pa].
    rho : float
        Density [kg/m³].
    t : float
        Beam thickness (bending direction) [m].
    w : float
        Beam width (in-plane) [m].  Does not affect f for uniform beams.
    L : float
        Beam length [m].

    Returns
    -------
    float
        Fundamental resonance frequency f₁ [Hz].

    Raises
    ------
    ValueError
        If any parameter is non-positive.
    """
    for name, val in [("E", E), ("rho", rho), ("t", t), ("w", w), ("L", L)]:
        if val <= 0:
            raise ValueError(f"{name} must be positive; got {val}")

    # Second moment of area and cross-sectional area
    I = w * t**3 / 12.0
    A = w * t

    f1 = (_BETA1L**2 / (2.0 * math.pi * L**2)) * math.sqrt(E * I / (rho * A))
    return f1


def cantilever_resonance_lumped(
    E: float,
    rho: float,
    t: float,
    w: float,
    L: float,
) -> float:
    """
    Fundamental resonance frequency via the lumped-mass model.

        f = 1/(2π) · √(k / m_eff)

    where k = Et³w/(4L³) and m_eff = 0.2427 · ρ · w · t · L
    (effective mass from the first-mode shape integral).

    This matches ``cantilever_resonance`` to better than 0.01% and is
    provided as a cross-check.

    Parameters
    ----------
    E : float
        Young's modulus [Pa].
    rho : float
        Density [kg/m³].
    t : float
        Beam thickness [m].
    w : float
        Beam width [m].
    L : float
        Beam length [m].

    Returns
    -------
    float
        Fundamental resonance frequency f₁ [Hz].
    """
    for name, val in [("E", E), ("rho", rho), ("t", t), ("w", w), ("L", L)]:
        if val <= 0:
            raise ValueError(f"{name} must be positive; got {val}")

    k = cantilever_stiffness(E, t, w, L)
    m_total = rho * w * t * L
    # Effective mass factor for first Euler-Bernoulli mode
    m_eff = 0.24270167 * m_total
    return (1.0 / (2.0 * math.pi)) * math.sqrt(k / m_eff)
