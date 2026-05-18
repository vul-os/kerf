"""Secular orbital perturbation rates due to Earth's oblateness (J2, J3).

Provides the secular (orbit-averaged) drift rates for Ω (RAAN), ω (argument
of periapsis), and M (mean anomaly) caused by the J2 and J3 zonal harmonics
of Earth's gravitational potential.

Constants from JGM-3 / EGM-96 (Lemoine et al. 1998).

Units: km, radians, seconds (rates in rad/s unless noted).

References:
  Vallado, D. A. (2013). Fundamentals of Astrodynamics and Applications, 4th ed.
  Brouwer, D. (1959). Solution of the problem of artificial satellite theory
      without drag. AJ, 64, 378.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Earth constants (JGM-3 / EGM-96)
# ---------------------------------------------------------------------------

# Gravitational parameter [km^3/s^2]
MU_EARTH: float = 398600.4418

# Earth equatorial radius [km]
R_EARTH: float = 6378.1363

# J2 zonal harmonic (dimensionless) — JGM-3
J2: float = 1.08262668e-3

# J3 zonal harmonic (dimensionless) — JGM-3
J3: float = -2.53265649e-6


@dataclass
class SecularRates:
    """Secular drift rates for Ω, ω, and M due to a single harmonic.

    All rates are in rad/s.

    Attributes:
        d_raan : dΩ/dt  — RAAN drift rate [rad/s]
        d_argp : dω/dt  — argument-of-periapsis drift rate [rad/s]
        d_M    : dM/dt  — mean-anomaly drift rate correction [rad/s]
                         (added to the unperturbed mean motion n)
    """

    d_raan: float
    d_argp: float
    d_M: float


def j2_secular_rates(
    a: float,
    e: float,
    i: float,
    mu: float = MU_EARTH,
    R_eq: float = R_EARTH,
    j2: float = J2,
) -> SecularRates:
    """Compute J2 secular drift rates for Ω, ω, and M.

    First-order secular perturbations (Brouwer theory, mean elements):

        dΩ/dt = -3/2 * n * J2 * (Re/p)² * cos(i)

        dω/dt =  3/4 * n * J2 * (Re/p)² * (5cos²i - 1)

        δṀ   =  3/4 * n * J2 * (Re/p)² * sqrt(1-e²) * (3cos²i - 1)

    where p = a(1 - e²) is the semi-latus rectum, n = sqrt(μ/a³).

    Parameters
    ----------
    a : float
        Semi-major axis [km]
    e : float
        Eccentricity
    i : float
        Inclination [rad]
    mu : float
        Gravitational parameter [km^3/s^2]
    R_eq : float
        Earth equatorial radius [km]
    j2 : float
        J2 coefficient (dimensionless)

    Returns
    -------
    SecularRates
        Drift rates in rad/s.
    """
    n = math.sqrt(mu / a**3)          # mean motion [rad/s]
    p = a * (1.0 - e**2)              # semi-latus rectum [km]
    Re_over_p = R_eq / p
    eta = math.sqrt(1.0 - e**2)       # eccentricity factor
    cos_i = math.cos(i)
    cos2_i = cos_i**2

    factor = -1.5 * n * j2 * Re_over_p**2

    d_raan = factor * cos_i
    d_argp = -0.5 * factor * (5.0 * cos2_i - 1.0)  # factor is negative → flip sign
    d_M = -0.5 * factor * eta * (3.0 * cos2_i - 1.0)

    return SecularRates(d_raan=d_raan, d_argp=d_argp, d_M=d_M)


def j3_secular_rates(
    a: float,
    e: float,
    i: float,
    mu: float = MU_EARTH,
    R_eq: float = R_EARTH,
    j3: float = J3,
    j2: float = J2,
) -> SecularRates:
    """Compute J3 secular drift rates for Ω, ω, and M.

    The J3 contribution to the secular rates is of order J3/J2 relative to
    the J2 terms and affects ω and M (but not Ω to first order):

        dω/dt|J3 = -15/4 * n * J3 * (Re/p)³ * sin(i) *
                   (1 - (5/4) * sin²i) * e / eta²   [corrected form]

        dM/dt|J3 = -15/4 * n * J3 * (Re/p)³ * eta * sin(i) *
                   (1 - (5/4) * sin²i) * e / eta²

    Brouwer (1959), Vallado (2013) eq. 9-42.

    Parameters
    ----------
    a : float
        Semi-major axis [km]
    e : float
        Eccentricity (>0; J3 terms ∝ e become zero for circular orbits)
    i : float
        Inclination [rad]
    mu, R_eq, j3, j2 : floats
        Physical constants.

    Returns
    -------
    SecularRates
        Drift rates in rad/s.
    """
    n = math.sqrt(mu / a**3)
    p = a * (1.0 - e**2)
    Re_over_p = R_eq / p
    eta = math.sqrt(1.0 - e**2)
    sin_i = math.sin(i)
    sin2_i = sin_i**2

    # Brouwer secular J3 terms (leading)
    factor3 = (15.0 / 4.0) * n * j3 * Re_over_p**3

    d_argp = factor3 * (sin_i / eta**4) * (1.0 - (5.0 / 4.0) * sin2_i) * e
    d_M = factor3 * (sin_i / eta**3) * (1.0 - (5.0 / 4.0) * sin2_i) * e
    d_raan = 0.0  # J3 has no secular effect on Ω to first order

    # Note: J3 < 0 so these terms are negative for inclinations < ~63.43°
    return SecularRates(d_raan=d_raan, d_argp=d_argp, d_M=d_M)


def combined_secular_rates(
    a: float,
    e: float,
    i: float,
    mu: float = MU_EARTH,
    R_eq: float = R_EARTH,
    j2: float = J2,
    j3: float = J3,
) -> SecularRates:
    """Sum J2 + J3 secular rates.

    Parameters
    ----------
    a, e, i : float
        Orbital elements (SI units: km, dimensionless, rad)
    mu, R_eq, j2, j3 : float
        Physical constants.

    Returns
    -------
    SecularRates
        Combined J2 + J3 drift rates in rad/s.
    """
    r2 = j2_secular_rates(a, e, i, mu, R_eq, j2)
    r3 = j3_secular_rates(a, e, i, mu, R_eq, j3, j2)

    return SecularRates(
        d_raan=r2.d_raan + r3.d_raan,
        d_argp=r2.d_argp + r3.d_argp,
        d_M=r2.d_M + r3.d_M,
    )
