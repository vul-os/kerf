"""Lambert's problem solver using the BMW universal-variable method.

Given two position vectors r1, r2 and a time-of-flight, returns the initial
and final velocity vectors that connect the two positions on a conic arc.

Algorithm: universal-variable (Battin/Gooding/BMW) formulation via the
Lagrange f/g coefficient approach.  Robust for elliptic arcs of any
inclination, eccentricity, and transfer angle in (0°, 360°).

Reference:
  Bate, R. R., Mueller, D. D., & White, J. E. (1971).
  Fundamentals of Astrodynamics. Dover.  §6.3 (Lambert's problem).

Units: km, km/s, seconds.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from .kepler import MU_EARTH

# Newton-Raphson convergence parameters
_NR_TOL: float = 1e-9
_NR_MAX: int = 200


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def lambert_izzo(
    r1: np.ndarray,
    r2: np.ndarray,
    tof: float,
    mu: float = MU_EARTH,
    prograde: bool = True,
    revs: int = 0,
) -> Tuple[np.ndarray, np.ndarray]:
    """Solve Lambert's problem via the universal-variable (BMW) method.

    Parameters
    ----------
    r1 : np.ndarray shape (3,)
        Initial position vector [km]
    r2 : np.ndarray shape (3,)
        Final position vector [km]
    tof : float
        Time of flight [s] (must be positive)
    mu : float
        Gravitational parameter [km^3/s^2]
    prograde : bool
        If True, assume prograde transfer (Δν < π for short-way, determined
        by the sign of the z-component of r1×r2).
    revs : int
        Number of complete revolutions (currently only 0 supported).

    Returns
    -------
    v1 : np.ndarray shape (3,)
        Velocity at r1 [km/s]
    v2 : np.ndarray shape (3,)
        Velocity at r2 [km/s]

    Raises
    ------
    ValueError
        If tof <= 0, positions are collinear, or multi-rev not supported.
    RuntimeError
        If the Newton-Raphson iteration fails to converge.
    """
    r1 = np.asarray(r1, dtype=float)
    r2 = np.asarray(r2, dtype=float)

    if tof <= 0.0:
        raise ValueError(f"Time-of-flight must be positive, got {tof}")
    if revs != 0:
        raise NotImplementedError("Multi-revolution Lambert is not yet supported")

    r1_mag = np.linalg.norm(r1)
    r2_mag = np.linalg.norm(r2)

    if r1_mag < 1e-10 or r2_mag < 1e-10:
        raise ValueError("Position vector magnitude too small")

    # Transfer angle
    cos_dnu = np.clip(np.dot(r1, r2) / (r1_mag * r2_mag), -1.0, 1.0)
    cross = np.cross(r1, r2)

    if prograde:
        dnu = math.acos(cos_dnu) if cross[2] >= 0.0 else 2.0 * math.pi - math.acos(cos_dnu)
    else:
        dnu = 2.0 * math.pi - math.acos(cos_dnu) if cross[2] >= 0.0 else math.acos(cos_dnu)

    if abs(dnu) < 1e-10 or abs(dnu - 2.0 * math.pi) < 1e-10:
        raise ValueError("Transfer angle too small; positions nearly identical")

    if abs(math.sin(dnu)) < 1e-10:
        raise ValueError("r1 and r2 are collinear — Lambert problem is degenerate")

    # BMW 'A' parameter (eq. 6.3-25)
    A = math.sin(dnu) * math.sqrt(r1_mag * r2_mag / (1.0 - math.cos(dnu)))

    # Find z (universal variable squared) by Newton-Raphson
    z = _find_z(r1_mag, r2_mag, A, tof, mu)

    # Reconstruct velocities via Lagrange f and g coefficients
    y = _y_z(z, r1_mag, r2_mag, A)
    f = 1.0 - y / r1_mag
    g = A * math.sqrt(y / mu)
    g_dot = 1.0 - y / r2_mag

    v1 = (r2 - f * r1) / g
    v2 = (g_dot * r2 - r1) / g

    return v1, v2


# ---------------------------------------------------------------------------
# Universal-variable helper functions
# ---------------------------------------------------------------------------

def _C_z(z: float) -> float:
    """Stumpff C function: C(z) = (1 - cos√z)/z for z>0, series for z≈0."""
    if z > 1e-6:
        sq = math.sqrt(z)
        return (1.0 - math.cos(sq)) / z
    elif z < -1e-6:
        sq = math.sqrt(-z)
        return (math.cosh(sq) - 1.0) / (-z)
    else:
        # Taylor series: C(z) = 1/2 - z/24 + z²/720 - ...
        return 0.5 - z / 24.0 + z * z / 720.0


def _S_z(z: float) -> float:
    """Stumpff S function: S(z) = (√z - sin√z)/z^(3/2) for z>0, series for z≈0."""
    if z > 1e-6:
        sq = math.sqrt(z)
        return (sq - math.sin(sq)) / (sq * sq * sq)
    elif z < -1e-6:
        sq = math.sqrt(-z)
        return (math.sinh(sq) - sq) / (sq * sq * sq)
    else:
        # Taylor series: S(z) = 1/6 - z/120 + z²/5040 - ...
        return 1.0 / 6.0 - z / 120.0 + z * z / 5040.0


def _y_z(z: float, r1: float, r2: float, A: float) -> float:
    """Auxiliary y(z) = r1 + r2 + A*(z*S(z) - 1)/√C(z)  [BMW eq. 6.3-26]."""
    cz = _C_z(z)
    sz = _S_z(z)
    if cz < 1e-30:
        return r1 + r2
    return r1 + r2 + A * (z * sz - 1.0) / math.sqrt(cz)


def _tof_z(z: float, r1: float, r2: float, A: float, mu: float) -> float:
    """Time-of-flight as a function of z  [BMW eq. 6.3-27]."""
    y = _y_z(z, r1, r2, A)
    if y < 0.0:
        return -1e20
    cz = _C_z(z)
    sz = _S_z(z)
    if cz < 1e-30:
        return 0.0
    x = math.sqrt(y / cz)
    return (x * x * x * sz + A * math.sqrt(y)) / math.sqrt(mu)


def _find_z(
    r1: float,
    r2: float,
    A: float,
    tof: float,
    mu: float,
) -> float:
    """Newton-Raphson to find z such that tof_z(z) = tof."""
    z = 0.0

    for iteration in range(_NR_MAX):
        f_val = _tof_z(z, r1, r2, A, mu) - tof

        # Numerical derivative
        dz = max(abs(z) * 1e-7, 1e-7)
        df = (_tof_z(z + dz, r1, r2, A, mu) - _tof_z(z - dz, r1, r2, A, mu)) / (2.0 * dz)

        if abs(df) < 1e-30:
            z += 0.5
            continue

        step = -f_val / df

        # Limit step to avoid overshooting
        max_step = 4.0 * math.pi ** 2
        if step > max_step:
            step = max_step
        elif step < -max_step:
            step = -max_step

        z += step

        # Keep z above the hyperbolic lower bound
        z_min = -(2.0 * math.pi) ** 2 + 0.1
        if z < z_min:
            z = z_min

        if abs(f_val) < _NR_TOL:
            break

    else:
        # Last-resort convergence check
        residual = abs(_tof_z(z, r1, r2, A, mu) - tof)
        if residual > 1.0:
            raise RuntimeError(
                f"Lambert Newton-Raphson did not converge after {_NR_MAX} iterations "
                f"(residual = {residual:.3e} s)"
            )

    return z
