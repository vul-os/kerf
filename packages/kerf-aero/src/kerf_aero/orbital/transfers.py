"""Orbital transfer manoeuvres.

Implements:
  - Hohmann transfer (two-impulse, coplanar, circular orbits)
  - Bi-elliptic transfer (three-impulse, coplanar, circular orbits)
  - Phasing manoeuvre (catch-up to a target in the same circular orbit)

Units: km, km/s, seconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

from .kepler import MU_EARTH, orbital_period


@dataclass
class HohmannResult:
    """Results of a Hohmann transfer calculation.

    Attributes:
        dv1        : First impulse (perigee of transfer ellipse) [km/s]
        dv2        : Second impulse (apogee of transfer ellipse) [km/s]
        dv_total   : Total ΔV magnitude [km/s]
        tof        : Transfer time (half the transfer ellipse period) [s]
        a_transfer : Semi-major axis of the transfer ellipse [km]
    """

    dv1: float
    dv2: float
    dv_total: float
    tof: float
    a_transfer: float


@dataclass
class BiEllipticResult:
    """Results of a bi-elliptic transfer calculation.

    Attributes:
        dv1, dv2, dv3 : Three impulse magnitudes [km/s]
        dv_total       : Total ΔV magnitude [km/s]
        tof            : Total transfer time [s]
    """

    dv1: float
    dv2: float
    dv3: float
    dv_total: float
    tof: float


@dataclass
class PhasingResult:
    """Results of a phasing manoeuvre.

    Attributes:
        dv_total     : Total ΔV (two burns of equal magnitude) [km/s]
        dv_single    : Magnitude of each individual burn [km/s]
        tof          : Time for one phasing orbit [s]
        n_orbits     : Number of phasing orbits before rendezvous
        a_phasing    : Semi-major axis of phasing orbit [km]
    """

    dv_total: float
    dv_single: float
    tof: float
    n_orbits: int
    a_phasing: float


def hohmann_delta_v(
    r1: float,
    r2: float,
    mu: float = MU_EARTH,
) -> HohmannResult:
    """Calculate ΔV for a Hohmann transfer between two circular orbits.

    The spacecraft starts in a circular orbit of radius *r1* and transfers to
    a circular orbit of radius *r2* via an elliptic Hohmann arc.

    Parameters
    ----------
    r1 : float
        Initial circular orbit radius [km]
    r2 : float
        Final circular orbit radius [km]
    mu : float
        Gravitational parameter [km^3/s^2]

    Returns
    -------
    HohmannResult
    """
    if r1 <= 0.0 or r2 <= 0.0:
        raise ValueError("Orbit radii must be positive")
    if r1 == r2:
        return HohmannResult(dv1=0.0, dv2=0.0, dv_total=0.0, tof=0.0, a_transfer=r1)

    # Circular velocities
    v_c1 = math.sqrt(mu / r1)
    v_c2 = math.sqrt(mu / r2)

    # Transfer ellipse semi-major axis
    a_t = (r1 + r2) / 2.0

    # Velocities on the transfer ellipse at periapsis (r1) and apoapsis (r2)
    v_t1 = math.sqrt(mu * (2.0 / r1 - 1.0 / a_t))
    v_t2 = math.sqrt(mu * (2.0 / r2 - 1.0 / a_t))

    dv1 = abs(v_t1 - v_c1)
    dv2 = abs(v_c2 - v_t2)
    dv_total = dv1 + dv2

    tof = math.pi * math.sqrt(a_t**3 / mu)  # half period of transfer ellipse

    return HohmannResult(
        dv1=dv1,
        dv2=dv2,
        dv_total=dv_total,
        tof=tof,
        a_transfer=a_t,
    )


def bielliptic_delta_v(
    r1: float,
    r2: float,
    r_b: float,
    mu: float = MU_EARTH,
) -> BiEllipticResult:
    """Calculate ΔV for a bi-elliptic transfer between two circular orbits.

    A bi-elliptic transfer uses a high intermediate apoapsis *r_b* (the
    "boost point") to increase efficiency for large orbit ratio transfers
    (r2 / r1 > ~12).

    Parameters
    ----------
    r1 : float
        Initial circular orbit radius [km]
    r2 : float
        Final circular orbit radius [km]
    r_b : float
        Intermediate boost orbit apoapsis radius [km] (must be > max(r1, r2))
    mu : float
        Gravitational parameter [km^3/s^2]

    Returns
    -------
    BiEllipticResult
    """
    if r_b <= max(r1, r2):
        raise ValueError(
            f"Boost radius r_b={r_b} must be larger than both r1={r1} and r2={r2}"
        )

    # Circular velocities
    v_c1 = math.sqrt(mu / r1)
    v_c2 = math.sqrt(mu / r2)

    # First transfer ellipse: r1 → r_b
    a_t1 = (r1 + r_b) / 2.0
    v_t1_peri = math.sqrt(mu * (2.0 / r1 - 1.0 / a_t1))
    v_t1_apo = math.sqrt(mu * (2.0 / r_b - 1.0 / a_t1))

    # Second transfer ellipse: r_b → r2
    a_t2 = (r_b + r2) / 2.0
    v_t2_apo = math.sqrt(mu * (2.0 / r_b - 1.0 / a_t2))
    v_t2_peri = math.sqrt(mu * (2.0 / r2 - 1.0 / a_t2))

    dv1 = abs(v_t1_peri - v_c1)           # burn at r1
    dv2 = abs(v_t2_apo - v_t1_apo)        # burn at r_b
    dv3 = abs(v_c2 - v_t2_peri)           # circularise at r2

    dv_total = dv1 + dv2 + dv3
    tof = math.pi * (math.sqrt(a_t1**3 / mu) + math.sqrt(a_t2**3 / mu))

    return BiEllipticResult(
        dv1=dv1,
        dv2=dv2,
        dv3=dv3,
        dv_total=dv_total,
        tof=tof,
    )


def phasing_delta_v(
    r: float,
    phase_error: float,
    n_orbits: int = 1,
    mu: float = MU_EARTH,
) -> PhasingResult:
    """Calculate ΔV for a phasing manoeuvre in a circular orbit.

    The spacecraft needs to catch up (or let a target wait) by *phase_error*
    radians over *n_orbits* phasing orbits.  Two equal-magnitude impulses are
    used: one to enter the phasing orbit, one to return.

    Parameters
    ----------
    r : float
        Circular orbit radius [km]
    phase_error : float
        Angular catch-up required [rad] (positive = need to speed up/catch up)
    n_orbits : int
        Number of phasing orbits to complete the rendezvous
    mu : float
        Gravitational parameter [km^3/s^2]

    Returns
    -------
    PhasingResult
    """
    if r <= 0.0:
        raise ValueError("Orbit radius must be positive")
    if n_orbits < 1:
        raise ValueError("n_orbits must be >= 1")

    T_ref = orbital_period(r, mu)  # reference orbit period [s]

    # Phasing orbit period: T_phase such that the spacecraft covers the
    # extra phase_error over n_orbits
    T_phase = T_ref - phase_error / (2.0 * math.pi) * T_ref / n_orbits

    # Semi-major axis of phasing orbit from T = 2π sqrt(a³/μ)
    a_phase = (mu * (T_phase / (2.0 * math.pi)) ** 2) ** (1.0 / 3.0)

    # Circular velocity on reference orbit
    v_circ = math.sqrt(mu / r)

    # Velocity on phasing ellipse at the shared radius r
    # The phasing orbit touches the reference orbit at r.
    # If a_phase < r the periapsis is r; if a_phase > r apoapsis is r.
    # In both cases vis-viva applies:
    v_phase_at_r = math.sqrt(mu * (2.0 / r - 1.0 / a_phase))

    dv_single = abs(v_phase_at_r - v_circ)
    dv_total = 2.0 * dv_single  # entry + exit burns

    return PhasingResult(
        dv_total=dv_total,
        dv_single=dv_single,
        tof=n_orbits * T_phase,
        n_orbits=n_orbits,
        a_phasing=a_phase,
    )
