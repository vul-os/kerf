"""Keplerian orbital mechanics.

Provides conversions between orbital elements and Cartesian state vectors,
anomaly transformations via Newton-Raphson, and two-body propagation.

Units: km, km/s, radians, seconds unless noted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Tuple

import numpy as np

# Earth gravitational parameter [km^3/s^2] (JGM-3)
MU_EARTH: float = 398600.4418

# Tolerance for Newton-Raphson Kepler solver
_NR_TOL: float = 1e-12
_NR_MAX_ITER: int = 50


@dataclass
class KeplerianElements:
    """Classical Keplerian orbital elements.

    Attributes:
        a:    Semi-major axis [km]
        e:    Eccentricity (0 <= e < 1 for elliptical orbits)
        i:    Inclination [rad]
        raan: Right ascension of ascending node (Ω) [rad]
        argp: Argument of periapsis (ω) [rad]
        nu:   True anomaly (ν) [rad]
    """

    a: float
    e: float
    i: float
    raan: float
    argp: float
    nu: float


def mean_to_eccentric_anomaly(M: float, e: float) -> float:
    """Solve Kepler's equation M = E - e*sin(E) via Newton-Raphson.

    Parameters
    ----------
    M : float
        Mean anomaly [rad]
    e : float
        Eccentricity

    Returns
    -------
    float
        Eccentric anomaly E [rad]
    """
    # Normalise M to [-pi, pi] for robust initial guess
    M = M % (2 * math.pi)
    if M > math.pi:
        M -= 2 * math.pi

    # Initial guess (Danby 1988 starter)
    E = M + e * math.sin(M) / (1.0 - math.sin(M + e) + math.sin(M))
    if not math.isfinite(E):
        E = M

    for _ in range(_NR_MAX_ITER):
        f = E - e * math.sin(E) - M
        fp = 1.0 - e * math.cos(E)
        dE = -f / fp
        E += dE
        if abs(dE) < _NR_TOL:
            break

    return E


def eccentric_to_true_anomaly(E: float, e: float) -> float:
    """Convert eccentric anomaly to true anomaly.

    Parameters
    ----------
    E : float
        Eccentric anomaly [rad]
    e : float
        Eccentricity

    Returns
    -------
    float
        True anomaly ν [rad] in [0, 2π)
    """
    nu = 2.0 * math.atan2(
        math.sqrt(1.0 + e) * math.sin(E / 2.0),
        math.sqrt(1.0 - e) * math.cos(E / 2.0),
    )
    return nu % (2.0 * math.pi)


def true_to_eccentric_anomaly(nu: float, e: float) -> float:
    """Convert true anomaly to eccentric anomaly.

    Parameters
    ----------
    nu : float
        True anomaly [rad]
    e : float
        Eccentricity

    Returns
    -------
    float
        Eccentric anomaly E [rad]
    """
    E = 2.0 * math.atan2(
        math.sqrt(1.0 - e) * math.sin(nu / 2.0),
        math.sqrt(1.0 + e) * math.cos(nu / 2.0),
    )
    return E % (2.0 * math.pi)


def eccentric_to_mean_anomaly(E: float, e: float) -> float:
    """Convert eccentric anomaly to mean anomaly (Kepler's equation).

    Parameters
    ----------
    E : float
        Eccentric anomaly [rad]
    e : float
        Eccentricity

    Returns
    -------
    float
        Mean anomaly M [rad]
    """
    return (E - e * math.sin(E)) % (2.0 * math.pi)


def orbital_period(a: float, mu: float = MU_EARTH) -> float:
    """Compute the orbital period for a Keplerian ellipse.

    Parameters
    ----------
    a : float
        Semi-major axis [km]
    mu : float
        Gravitational parameter [km^3/s^2]

    Returns
    -------
    float
        Orbital period [s]
    """
    return 2.0 * math.pi * math.sqrt(a**3 / mu)


def elements_to_state(
    elems: KeplerianElements, mu: float = MU_EARTH
) -> Tuple[np.ndarray, np.ndarray]:
    """Convert Keplerian elements to Cartesian state vector (ECI frame).

    Uses the perifocal (PQW) frame then rotates via the 3-1-3 Euler sequence
    (RAAN, i, argp).

    Parameters
    ----------
    elems : KeplerianElements
        Orbital elements (a [km], e, i [rad], raan [rad], argp [rad], nu [rad])
    mu : float
        Gravitational parameter [km^3/s^2]

    Returns
    -------
    r : np.ndarray shape (3,)
        Position vector [km]
    v : np.ndarray shape (3,)
        Velocity vector [km/s]
    """
    a, e, i, raan, argp, nu = elems.a, elems.e, elems.i, elems.raan, elems.argp, elems.nu

    # Perifocal (PQW) frame
    p = a * (1.0 - e**2)  # semi-latus rectum [km]
    r_mag = p / (1.0 + e * math.cos(nu))

    r_pqw = np.array([r_mag * math.cos(nu), r_mag * math.sin(nu), 0.0])

    sqrt_mup = math.sqrt(mu / p)
    v_pqw = np.array([-sqrt_mup * math.sin(nu), sqrt_mup * (e + math.cos(nu)), 0.0])

    # Rotation matrix: PQW → ECI via R3(-raan) · R1(-i) · R3(-argp)
    R = _rot_pqw_to_eci(raan, i, argp)

    r_eci = R @ r_pqw
    v_eci = R @ v_pqw

    return r_eci, v_eci


def state_to_elements(
    r: np.ndarray, v: np.ndarray, mu: float = MU_EARTH
) -> KeplerianElements:
    """Convert Cartesian state vector (ECI) to Keplerian elements.

    Parameters
    ----------
    r : np.ndarray shape (3,)
        Position vector [km]
    v : np.ndarray shape (3,)
        Velocity vector [km/s]
    mu : float
        Gravitational parameter [km^3/s^2]

    Returns
    -------
    KeplerianElements
    """
    r = np.asarray(r, dtype=float)
    v = np.asarray(v, dtype=float)

    r_mag = np.linalg.norm(r)
    v_mag = np.linalg.norm(v)

    # Angular momentum
    h = np.cross(r, v)
    h_mag = np.linalg.norm(h)

    # Node vector
    k = np.array([0.0, 0.0, 1.0])
    n = np.cross(k, h)
    n_mag = np.linalg.norm(n)

    # Eccentricity vector
    e_vec = ((v_mag**2 - mu / r_mag) * r - np.dot(r, v) * v) / mu
    e = np.linalg.norm(e_vec)

    # Semi-major axis via vis-viva
    xi = v_mag**2 / 2.0 - mu / r_mag  # specific orbital energy
    a = -mu / (2.0 * xi)

    # Inclination
    i = math.acos(np.clip(h[2] / h_mag, -1.0, 1.0))

    # RAAN
    if n_mag < 1e-12:
        raan = 0.0
    else:
        raan = math.acos(np.clip(n[0] / n_mag, -1.0, 1.0))
        if n[1] < 0.0:
            raan = 2.0 * math.pi - raan

    # Argument of periapsis — use atan2 for quadrant accuracy
    if n_mag < 1e-12 or e < 1e-10:
        argp = 0.0
    else:
        n_hat = n / n_mag
        e_hat = e_vec / e
        h_hat = h / h_mag
        # t_hat is the direction 90° ahead of n_hat in the orbital plane
        t_hat_n = np.cross(h_hat, n_hat)
        argp = math.atan2(np.dot(e_hat, t_hat_n), np.dot(e_hat, n_hat)) % (2.0 * math.pi)

    # True anomaly — use atan2 for full-quadrant accuracy and better precision
    if e < 1e-10:
        # Circular orbit: use argument of latitude
        if n_mag < 1e-12:
            # Equatorial circular: angle from x-axis
            nu = math.atan2(r[1], r[0]) % (2.0 * math.pi)
        else:
            n_hat = n / n_mag
            # Component in orbital plane: decompose r into n_hat and
            # a direction 90° ahead in the plane
            t_hat = np.cross(h / h_mag, n_hat)
            nu = math.atan2(np.dot(r, t_hat), np.dot(r, n_hat)) % (2.0 * math.pi)
    else:
        # Eccentric orbit: use atan2(r×e_vec direction, r·e_vec)
        e_hat = e_vec / e
        # p_hat = e_hat, q_hat = h_hat × e_hat
        q_hat = np.cross(h / h_mag, e_hat)
        nu = math.atan2(np.dot(r, q_hat), np.dot(r, e_hat)) % (2.0 * math.pi)

    return KeplerianElements(a=a, e=e, i=i, raan=raan, argp=argp, nu=nu)


def propagate_kepler(
    r0: np.ndarray,
    v0: np.ndarray,
    dt: float,
    mu: float = MU_EARTH,
) -> Tuple[np.ndarray, np.ndarray]:
    """Propagate a Keplerian orbit forward by time dt.

    Uses element conversion and mean-anomaly advance (two-body, no
    perturbations).

    Parameters
    ----------
    r0 : np.ndarray
        Initial position [km]
    v0 : np.ndarray
        Initial velocity [km/s]
    dt : float
        Time step [s]
    mu : float
        Gravitational parameter [km^3/s^2]

    Returns
    -------
    r1 : np.ndarray
        Final position [km]
    v1 : np.ndarray
        Final velocity [km/s]
    """
    elems = state_to_elements(r0, v0, mu)
    n = math.sqrt(mu / elems.a**3)  # mean motion [rad/s]

    E0 = true_to_eccentric_anomaly(elems.nu, elems.e)
    M0 = eccentric_to_mean_anomaly(E0, elems.e)
    M1 = M0 + n * dt

    E1 = mean_to_eccentric_anomaly(M1, elems.e)
    nu1 = eccentric_to_true_anomaly(E1, elems.e)

    new_elems = KeplerianElements(
        a=elems.a,
        e=elems.e,
        i=elems.i,
        raan=elems.raan,
        argp=elems.argp,
        nu=nu1,
    )
    return elements_to_state(new_elems, mu)


# ---------------------------------------------------------------------------
# Internal helper: rotation matrix PQW → ECI
# ---------------------------------------------------------------------------

def _rot_pqw_to_eci(raan: float, i: float, argp: float) -> np.ndarray:
    """Build the 3×3 rotation matrix from perifocal to ECI frame.

    R = R3(-raan) · R1(-i) · R3(-argp)
    where R1, R3 are elementary rotations about X and Z axes.
    """
    cos_raan, sin_raan = math.cos(raan), math.sin(raan)
    cos_i, sin_i = math.cos(i), math.sin(i)
    cos_argp, sin_argp = math.cos(argp), math.sin(argp)

    # Combined 3-1-3 rotation (transposed — converting FROM perifocal TO ECI)
    R = np.array([
        [
            cos_raan * cos_argp - sin_raan * sin_argp * cos_i,
            -cos_raan * sin_argp - sin_raan * cos_argp * cos_i,
            sin_raan * sin_i,
        ],
        [
            sin_raan * cos_argp + cos_raan * sin_argp * cos_i,
            -sin_raan * sin_argp + cos_raan * cos_argp * cos_i,
            -cos_raan * sin_i,
        ],
        [
            sin_argp * sin_i,
            cos_argp * sin_i,
            cos_i,
        ],
    ])
    return R


# ---------------------------------------------------------------------------
# Public constants and compatibility aliases
# ---------------------------------------------------------------------------

#: Mean equatorial radius of the Earth [km] (WGS-84)
R_EARTH_KM: float = 6_378.137


@dataclass
class OrbitalElements:
    """Alias for :class:`KeplerianElements` using ``nu0`` instead of ``nu``.

    Provided for API compatibility.  Internally maps ``nu0`` → ``nu`` when
    converting to :class:`KeplerianElements`.
    """

    a: float
    e: float
    i: float
    raan: float
    argp: float
    nu0: float

    def to_keplerian(self) -> KeplerianElements:
        """Return the equivalent :class:`KeplerianElements` instance."""
        return KeplerianElements(
            a=self.a,
            e=self.e,
            i=self.i,
            raan=self.raan,
            argp=self.argp,
            nu=self.nu0,
        )


def propagate_orbit(
    elements: "OrbitalElements | KeplerianElements",
    duration_s: float,
    n_steps: int = 200,
    mu: float = MU_EARTH,
) -> list[tuple[float, float, float]]:
    """Propagate a Keplerian orbit and return an array of ECI position vectors.

    Parameters
    ----------
    elements:
        Orbital elements describing the initial state.  Both
        :class:`OrbitalElements` (``nu0`` field) and
        :class:`KeplerianElements` (``nu`` field) are accepted.
    duration_s:
        Total propagation duration in seconds.  Must be > 0.
    n_steps:
        Number of sample points to return (including start and end).
        Must be ≥ 2.
    mu:
        Gravitational parameter [km³/s²].  Defaults to Earth.

    Returns
    -------
    list of (x, y, z) tuples in kilometres (ECI frame).
    """
    if duration_s <= 0:
        raise ValueError(f"duration_s must be positive, got {duration_s!r}")
    if n_steps < 2:
        raise ValueError(f"n_steps must be ≥ 2, got {n_steps!r}")
    if isinstance(elements, OrbitalElements):
        kep = elements.to_keplerian()
    else:
        kep = elements
    if kep.e >= 1.0:
        raise ValueError(f"eccentricity must be < 1 for elliptic orbits, got {kep.e!r}")

    dt = duration_s / (n_steps - 1)
    r, v = elements_to_state(kep, mu)
    points: list[tuple[float, float, float]] = [(float(r[0]), float(r[1]), float(r[2]))]
    for _ in range(n_steps - 1):
        r, v = propagate_kepler(r, v, dt, mu)
        points.append((float(r[0]), float(r[1]), float(r[2])))
    return points
