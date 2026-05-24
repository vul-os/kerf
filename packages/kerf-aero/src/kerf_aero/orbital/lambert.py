"""Lambert's problem solver.

Implements two methods:
  1. Universal-variable (BMW/Bate-Mueller-White) for single-revolution (revs=0).
  2. Lancaster-Blanchard / Izzo (2015) for multi-revolution (revs>=1): both
     left/right branches, using Halley iteration on the x-variable.

Multi-revolution method (revs >= 1):
  x = cos(alpha/2) in (-1, 1) where alpha = 2*asin(sqrt(s/(2a))) is Lagrange's
  departure angle.  Using cos(alpha/2) = x gives alpha = 2*acos(x) ∈ (0, 2π).

  Non-dim time unit: T = (s/2)^(3/2) / sqrt(mu)   [s = semi-perimeter]

  Non-dim Lagrange TOF (Lancaster-Blanchard / Izzo 2015 eq. 9):
    p     = 1 - x^2  (= s/(2a), dimensionless)
    alpha = 2*acos(x)              [in (0, 2π) — note: NOT 2*asin(sqrt(p))]
    beta  = 2*asin(|λ|*sqrt(p))   [in (0, π), sign preserved via λ]
    A = alpha - sin(alpha)
    B = beta  - sin(beta)
    tau(x) = (A - B + 2πN) / p^(3/2)

  For N ≥ 1 the tau function has a minimum at x_min > 0.  The left branch covers
  x ∈ (-1, x_min) and the right branch x ∈ (x_min, 1).  Halley's method converges
  in 4–6 iterations from good starting points.

  Velocity reconstruction (Izzo 2015 eqs. 16-17):
    y   = sqrt(1 - λ² + λ²x²) = cos(β/2)
    γ   = sqrt(μs/2)
    ρ   = (r1 - r2) / c
    σ   = sqrt(1 - ρ²)
    Vr1 = (γ/r1) * ((λy - x) - ρ(λy + x))
    Vt1 = (γ/r1) * σ(y + λx)
    Vr2 = -(γ/r2) * ((λy - x) + ρ(λy + x))
    Vt2 = (γ/r2) * σ(y + λx)

References:
  Izzo, D. (2015). "Revisiting Lambert's problem."
  Celestial Mechanics and Dynamical Astronomy, 121(1), 1-15.
  DOI: 10.1007/s10569-014-9587-y

  Lancaster, E. R. & Blanchard, R. C. (1969). "A unified form of Lambert's
  theorem."  NASA TN D-5368.

  Bate, R. R., Mueller, D. D., & White, J. E. (1971).
  Fundamentals of Astrodynamics. Dover.  §6.3.

Units: km, km/s, seconds.
"""

from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np

from .kepler import MU_EARTH

# Newton-Raphson convergence parameters (single-rev BMW solver)
_NR_TOL: float = 1e-9
_NR_MAX: int = 200

# Multi-rev Halley iteration convergence parameters
_IZZO_TOL: float = 1e-12
_IZZO_MAX: int = 60


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
    branch: str = "left",
) -> Tuple[np.ndarray, np.ndarray]:
    """Solve Lambert's problem.

    For revs=0 (single-revolution): uses the BMW universal-variable method.
    For revs>=1 (multi-revolution): uses the Lancaster-Blanchard / Izzo (2015)
    algorithm with Halley iteration on the x-variable.  Two solutions exist
    (left/right branch); use the ``branch`` parameter to select.

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
        If True, assume prograde transfer.  Determines the transfer angle
        direction via the sign of (r1 x r2).z.
    revs : int
        Number of complete revolutions (0 = single-rev).
    branch : str
        For multi-rev only: "left" or "right".  Left branch gives the
        lower-x (lower-energy or higher-apoapsis) solution; right branch the
        higher-x solution.  Ignored for revs=0.

    Returns
    -------
    v1 : np.ndarray shape (3,)
        Velocity at r1 [km/s]
    v2 : np.ndarray shape (3,)
        Velocity at r2 [km/s]

    Raises
    ------
    ValueError
        If tof <= 0, positions are collinear, or branch invalid.
    RuntimeError
        If the iteration fails to converge or the TOF is below the
        minimum for the requested number of revolutions.
    """
    r1 = np.asarray(r1, dtype=float)
    r2 = np.asarray(r2, dtype=float)

    if tof <= 0.0:
        raise ValueError(f"Time-of-flight must be positive, got {tof}")

    r1_mag = np.linalg.norm(r1)
    r2_mag = np.linalg.norm(r2)

    if r1_mag < 1e-10 or r2_mag < 1e-10:
        raise ValueError("Position vector magnitude too small")

    if revs < 0:
        raise ValueError(f"revs must be >= 0, got {revs}")

    if revs == 0:
        return _lambert_single_rev(r1, r2, tof, mu, prograde)
    else:
        return _lambert_multi_rev(r1, r2, tof, mu, prograde, revs, branch)


def lambert_izzo_all_solutions(
    r1: np.ndarray,
    r2: np.ndarray,
    tof: float,
    mu: float = MU_EARTH,
    prograde: bool = True,
    max_revs: int = 3,
) -> List[Tuple[np.ndarray, np.ndarray, int, str]]:
    """Return all Lambert solutions up to max_revs revolutions.

    Parameters
    ----------
    r1, r2 : np.ndarray
        Position vectors [km]
    tof : float
        Time of flight [s]
    mu : float
        Gravitational parameter [km^3/s^2]
    prograde : bool
        Transfer direction flag
    max_revs : int
        Maximum number of complete revolutions to try

    Returns
    -------
    list of (v1, v2, revs, branch) tuples
        All valid solutions.  Single-rev always included (revs=0, branch="").
        Multi-rev solutions come in pairs ("left", "right") when the TOF
        is above the minimum for that revolution count.
    """
    r1 = np.asarray(r1, dtype=float)
    r2 = np.asarray(r2, dtype=float)
    solutions: List[Tuple[np.ndarray, np.ndarray, int, str]] = []

    try:
        v1, v2 = lambert_izzo(r1, r2, tof, mu, prograde, revs=0)
        solutions.append((v1, v2, 0, ""))
    except (ValueError, RuntimeError):
        pass

    for n in range(1, max_revs + 1):
        for b in ("left", "right"):
            try:
                v1, v2 = lambert_izzo(r1, r2, tof, mu, prograde, revs=n, branch=b)
                solutions.append((v1, v2, n, b))
            except (ValueError, RuntimeError):
                pass

    return solutions


# ---------------------------------------------------------------------------
# Single-revolution: BMW universal-variable
# ---------------------------------------------------------------------------

def _lambert_single_rev(
    r1: np.ndarray,
    r2: np.ndarray,
    tof: float,
    mu: float,
    prograde: bool,
) -> Tuple[np.ndarray, np.ndarray]:
    """BMW universal-variable Lambert solver for single revolution."""
    r1_mag = np.linalg.norm(r1)
    r2_mag = np.linalg.norm(r2)

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

    A = math.sin(dnu) * math.sqrt(r1_mag * r2_mag / (1.0 - math.cos(dnu)))
    z = _find_z(r1_mag, r2_mag, A, tof, mu)

    y = _y_z(z, r1_mag, r2_mag, A)
    f = 1.0 - y / r1_mag
    g = A * math.sqrt(y / mu)
    g_dot = 1.0 - y / r2_mag

    v1 = (r2 - f * r1) / g
    v2 = (g_dot * r2 - r1) / g

    return v1, v2


# ---------------------------------------------------------------------------
# Multi-revolution: Lancaster-Blanchard / Izzo 2015
# ---------------------------------------------------------------------------

def _lambert_multi_rev(
    r1: np.ndarray,
    r2: np.ndarray,
    tof: float,
    mu: float,
    prograde: bool,
    revs: int,
    branch: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """Lancaster-Blanchard multi-revolution Lambert solver.

    x-variable:  x = cos(alpha/2) in (-1, 1),
                 alpha = 2*acos(x) in (0, 2π) is Lagrange's departure angle.
    lambda:      λ = sqrt(1 - c/s), negative for long-way (dnu > π)

    Non-dim TOF (Lancaster-Blanchard):
      p     = 1 - x²
      alpha = 2*acos(x)
      beta  = 2*asin(|λ|*sqrt(p))   [with sign: negative if λ < 0]
      tau   = (alpha - sin(alpha) - (beta - sin(beta)) + 2πN) / p^(3/2)

    The minimum-energy x (x_min, where dtau/dx = 0) separates the two branches.
    Left branch: x < x_min;  Right branch: x > x_min.

    Velocity (Izzo 2015 eqs. 16-17, sign-checked vs BMW for single-rev):
      y   = sqrt(1 - λ² + λ²x²)
      γ   = sqrt(μs/2)
      Vr1 = (γ/r1) * ((λy - x) - ρ(λy + x))
      Vt1 = (γ/r1) * σ(y + λx)
      [similarly for Vr2, Vt2]
    """
    if branch not in ("left", "right"):
        raise ValueError(f"branch must be 'left' or 'right', got {branch!r}")

    r1_mag = float(np.linalg.norm(r1))
    r2_mag = float(np.linalg.norm(r2))

    cos_dnu = float(np.clip(np.dot(r1, r2) / (r1_mag * r2_mag), -1.0, 1.0))
    cross = np.cross(r1, r2)

    if prograde:
        dnu = math.acos(cos_dnu) if cross[2] >= 0.0 else 2.0 * math.pi - math.acos(cos_dnu)
    else:
        dnu = 2.0 * math.pi - math.acos(cos_dnu) if cross[2] >= 0.0 else math.acos(cos_dnu)

    if abs(math.sin(dnu)) < 1e-10:
        raise ValueError("r1 and r2 are collinear — Lambert problem is degenerate")

    c = math.sqrt(r1_mag**2 + r2_mag**2 - 2.0 * r1_mag * r2_mag * cos_dnu)
    s = 0.5 * (r1_mag + r2_mag + c)

    # Lambda (negative for long-way)
    lam2 = 1.0 - c / s
    lam = math.sqrt(max(0.0, lam2))
    if dnu > math.pi:
        lam = -lam

    # Non-dim time unit
    tof_unit = (s / 2.0) ** 1.5 / math.sqrt(mu)
    tof_nd = tof / tof_unit

    # Find x_min (minimum tau, i.e. dtau/dx = 0)
    x_min = _lb_find_xmin(lam, revs)
    tau_min = _lb_tau(x_min, lam, revs)
    tof_min = tau_min * tof_unit

    if tof_nd < tau_min - 1e-9:
        raise RuntimeError(
            f"TOF {tof:.3f} s is below the minimum {tof_min:.3f} s "
            f"for {revs}-revolution transfer (need longer flight time)"
        )

    # Initial guess and bracket for Halley
    if branch == "left":
        # Left branch: x in (-1, x_min)
        x0 = max(-0.9, x_min - 0.5 * (1.0 + x_min))
        x = _lb_halley(x0, lam, revs, tof_nd, x_lo=-1.0 + 1e-10, x_hi=x_min - 1e-10)
    else:
        # Right branch: x in (x_min, 1)
        x0 = min(0.9, x_min + 0.5 * (1.0 - x_min))
        x = _lb_halley(x0, lam, revs, tof_nd, x_lo=x_min + 1e-10, x_hi=1.0 - 1e-10)

    # Velocity reconstruction (Izzo 2015 eqs. 16-17)
    gamma = math.sqrt(mu * s / 2.0)
    rho = (r1_mag - r2_mag) / c
    sigma = math.sqrt(max(0.0, 1.0 - rho**2))
    y = math.sqrt(max(0.0, 1.0 - lam2 + lam2 * x**2))

    vr1 = gamma * ((lam * y - x) - rho * (lam * y + x)) / r1_mag
    vt1 = gamma * sigma * (y + lam * x) / r1_mag
    vr2 = -gamma * ((lam * y - x) + rho * (lam * y + x)) / r2_mag
    vt2 = gamma * sigma * (y + lam * x) / r2_mag

    r1_hat = r1 / r1_mag
    r2_hat = r2 / r2_mag

    h_vec = np.cross(r1, r2)
    h_mag = np.linalg.norm(h_vec)
    if h_mag < 1e-12:
        raise ValueError("r1 and r2 are collinear — Lambert problem is degenerate")
    h_hat = h_vec / h_mag

    t1_hat = np.cross(h_hat, r1_hat)
    t2_hat = np.cross(h_hat, r2_hat)

    v1_out = vr1 * r1_hat + vt1 * t1_hat
    v2_out = vr2 * r2_hat + vt2 * t2_hat

    return v1_out, v2_out


# ---------------------------------------------------------------------------
# Lancaster-Blanchard TOF and Halley derivatives
# ---------------------------------------------------------------------------

def _lb_tau(x: float, lam: float, revs: int) -> float:
    """Non-dim Lagrange TOF tau(x, λ, N).

    alpha = 2*acos(x)              ← the key distinction: acos(x) not asin(sqrt(p))
    beta  = 2*asin(|λ|*sqrt(p))   ← β ∈ (0, π) with sign from λ
    tau   = (A - B + 2πN) / p^(3/2)
    """
    p = 1.0 - x * x
    if p < 1e-20:
        return 0.0

    alpha = 2.0 * math.acos(max(-1.0, min(1.0, x)))
    sqrtp = math.sqrt(p)
    abslam = abs(lam)
    lam_sqrtp = min(1.0, abslam * sqrtp)
    beta = 2.0 * math.asin(lam_sqrtp)
    if lam < 0.0:
        beta = -beta

    A = alpha - math.sin(alpha)
    B = beta - math.sin(beta)

    return (A - B + 2.0 * math.pi * revs) / p ** 1.5


def _lb_dtau(x: float, lam: float, revs: int) -> Tuple[float, float, float]:
    """Compute (tau, dtau/dx, d²tau/dx²) analytically for Halley iteration.

    Key derivatives:
      alpha = 2*acos(x),  dalpha/dx = -2/sqrt(1-x²) = -2/sqrt(p)
      beta  = 2*asin(|λ|*sqrt(p)),  dbeta/dx = -2|λ|x/(sqrt(p)*y)
    where y = sqrt(1 - λ²p) = sqrt(1 - λ²(1-x²)).
    """
    x_c = max(-1.0 + 1e-12, min(1.0 - 1e-12, x))
    p = 1.0 - x_c * x_c
    if p < 1e-20:
        return 0.0, 1e30, 1e30

    sqrtp = math.sqrt(p)
    abslam = abs(lam)
    lam_sqrtp = min(1.0 - 1e-14, max(0.0, abslam * sqrtp))

    alpha = 2.0 * math.acos(max(-1.0, min(1.0, x_c)))
    beta_abs = 2.0 * math.asin(lam_sqrtp)
    beta = beta_abs if lam >= 0.0 else -beta_abs

    A = alpha - math.sin(alpha)
    B = beta - math.sin(beta)
    f = A - B + 2.0 * math.pi * revs
    tau = f / p ** 1.5

    # dalpha/dx = -2/sqrt(p)  [d(acos(x))/dx = -1/sqrt(1-x^2) = -1/sqrt(p)]
    da_dx = -2.0 / sqrtp

    # y = sqrt(1 - lam^2 * p)
    y2 = 1.0 - lam ** 2 * p
    y2 = max(0.0, y2)
    y = math.sqrt(y2)

    # dbeta_abs/dx = d(2*asin(|λ|*sqrt(p)))/dx
    #              = 2 * 1/sqrt(1-λ²p) * |λ| * (-x/sqrt(p))
    #              = -2*|λ|*x / (sqrt(p) * y)
    if y < 1e-14 or sqrtp < 1e-14:
        db_abs_dx = 0.0
    else:
        db_abs_dx = -2.0 * abslam * x_c / (sqrtp * y)
    db_dx = db_abs_dx if lam >= 0.0 else -db_abs_dx

    # dA/dx = (1 - cos(alpha)) * da_dx
    # dB/dx = (1 - cos(beta))  * db_dx
    dA_dx = (1.0 - math.cos(alpha)) * da_dx
    dB_dx = (1.0 - math.cos(beta)) * db_dx
    df_dx = dA_dx - dB_dx

    # dtau/dx = (df_dx + 3x*tau) / p
    dtau = (df_dx + 3.0 * x_c * tau) / p

    # Second derivative: d²tau/dx² = (d²f/dx² + 3*tau + 5x*dtau) / p
    # d²alpha/dx²: da_dx = -2*p^(-1/2), d/dx = -2*(-1/2)*p^(-3/2)*(-2x) = -2x/p^(3/2)
    d2a_dx2 = -2.0 * x_c / p ** 1.5

    # d²beta_abs/dx²: db_abs_dx = -2*|λ|*x / (sqrt(p)*y)
    # Let h = sqrt(p)*y = sqrt(p*(1-λ²p))
    # d(h)/dx = [p'*(1-λ²p) + p*(-λ²*p')] / (2h) = p'*(1-2λ²p)/(2h) = -2x*(1-2λ²p)/(2h)
    # d²beta_abs/dx² = -2|λ| * [h - x*dh/dx] / h²
    h2 = p * y2
    if h2 < 1e-30 or sqrtp < 1e-14:
        d2b_abs_dx2 = 0.0
    else:
        # dh/dx = -x*(1-2*lam^2*p) / h
        # d²beta_abs/dx² = -2*|λ| * [1 + x²*(1-2λ²p)/h²] / (sqrt(p)*y)
        d2b_abs_dx2 = -2.0 * abslam * (1.0 + x_c**2 * (1.0 - 2.0 * lam**2 * p) / h2) / (sqrtp * y)

    d2b_dx2 = d2b_abs_dx2 if lam >= 0.0 else -d2b_abs_dx2

    d2A_dx2 = math.sin(alpha) * da_dx**2 + (1.0 - math.cos(alpha)) * d2a_dx2
    d2B_dx2 = math.sin(beta) * db_dx**2 + (1.0 - math.cos(beta)) * d2b_dx2
    d2f_dx2 = d2A_dx2 - d2B_dx2

    d2tau = (d2f_dx2 + 3.0 * tau + 5.0 * x_c * dtau) / p

    return tau, dtau, d2tau


def _lb_find_xmin(lam: float, revs: int) -> float:
    """Find x_min where dtau/dx = 0 (minimum TOF, separates the two branches).

    For N ≥ 1, x_min is in (0, 1).  Uses Newton iteration.
    """
    # Initial guess: x_min ≈ 0.3 for N=1, slightly higher for N>1
    x = 0.3 + 0.1 * (revs - 1)
    x = max(0.01, min(0.95, x))

    for _ in range(60):
        _tau, dtau, d2tau = _lb_dtau(x, lam, revs)
        if abs(dtau) < 1e-12:
            break
        if abs(d2tau) < 1e-30:
            x -= dtau * 1e-4
        else:
            dx = -dtau / d2tau
            dx = max(-0.15, min(0.15, dx))
            x += dx
        x = max(0.001, min(0.999, x))

    return x


def _lb_halley(
    x0: float,
    lam: float,
    revs: int,
    tof_nd: float,
    x_lo: float,
    x_hi: float,
) -> float:
    """Halley iteration to solve tau(x) = tof_nd within [x_lo, x_hi]."""
    x = max(x_lo + 1e-10, min(x_hi - 1e-10, x0))

    for _iter in range(_IZZO_MAX):
        tau, dtau, d2tau = _lb_dtau(x, lam, revs)
        F = tau - tof_nd

        if abs(F) < _IZZO_TOL:
            break

        # Halley step: dx = -2*F*dtau / (2*dtau² - F*d²tau)
        denom = 2.0 * dtau**2 - F * d2tau
        if abs(denom) < 1e-30 or abs(dtau) < 1e-30:
            break

        dx = -2.0 * F * dtau / denom

        x_new = x + dx
        if x_new >= x_hi:
            x_new = x + 0.5 * (x_hi - x)
        if x_new <= x_lo:
            x_new = x + 0.5 * (x_lo - x)
        x = x_new

        if abs(dx) < _IZZO_TOL:
            break

    # Validate convergence
    tau_final, _, _ = _lb_dtau(x, lam, revs)
    if abs(tau_final - tof_nd) > 1e-6:
        raise RuntimeError(
            f"Lambert Halley iteration did not converge "
            f"(residual tau = {abs(tau_final - tof_nd):.3e}, x = {x:.6f})"
        )

    return x


# ---------------------------------------------------------------------------
# Universal-variable helper functions (single-rev BMW)
# ---------------------------------------------------------------------------

def _C_z(z: float) -> float:
    """Stumpff C function."""
    if z > 1e-6:
        sq = math.sqrt(z)
        return (1.0 - math.cos(sq)) / z
    elif z < -1e-6:
        sq = math.sqrt(-z)
        return (math.cosh(sq) - 1.0) / (-z)
    else:
        return 0.5 - z / 24.0 + z * z / 720.0


def _S_z(z: float) -> float:
    """Stumpff S function."""
    if z > 1e-6:
        sq = math.sqrt(z)
        return (sq - math.sin(sq)) / (sq * sq * sq)
    elif z < -1e-6:
        sq = math.sqrt(-z)
        return (math.sinh(sq) - sq) / (sq * sq * sq)
    else:
        return 1.0 / 6.0 - z / 120.0 + z * z / 5040.0


def _y_z(z: float, r1: float, r2: float, A: float) -> float:
    """BMW auxiliary y(z)."""
    cz = _C_z(z)
    sz = _S_z(z)
    if cz < 1e-30:
        return r1 + r2
    return r1 + r2 + A * (z * sz - 1.0) / math.sqrt(cz)


def _tof_z(z: float, r1: float, r2: float, A: float, mu: float) -> float:
    """BMW time-of-flight as function of z."""
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

        dz = max(abs(z) * 1e-7, 1e-7)
        df = (_tof_z(z + dz, r1, r2, A, mu) - _tof_z(z - dz, r1, r2, A, mu)) / (2.0 * dz)

        if abs(df) < 1e-30:
            z += 0.5
            continue

        step = -f_val / df
        max_step = 4.0 * math.pi**2
        step = max(-max_step, min(max_step, step))
        z += step

        z_min = -(2.0 * math.pi)**2 + 0.1
        if z < z_min:
            z = z_min

        if abs(f_val) < _NR_TOL:
            break

    else:
        residual = abs(_tof_z(z, r1, r2, A, mu) - tof)
        if residual > 1.0:
            raise RuntimeError(
                f"Lambert Newton-Raphson did not converge after {_NR_MAX} iterations "
                f"(residual = {residual:.3e} s)"
            )

    return z
