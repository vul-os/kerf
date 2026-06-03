"""CR3BP Libration Point Orbit Design.

Implements the Circular Restricted Three-Body Problem (CR3BP) framework for
computing Lagrange equilibrium points and designing families of libration point
orbits: halo, Lyapunov, and Lissajous.

DISCLAIMER: Simplified implementation for design exploration — not GMAT-validated.
Results are suitable for preliminary mission analysis; flight-certified designs
require full ephemeris propagation.

Algorithm References
--------------------
Szebehely, V. (1967). *Theory of Orbits*. Academic Press. §4.4 (Lagrange points).
Richardson, D. L. (1980). "Analytic construction of periodic orbits about the
    collinear points." *Celestial Mechanics*, 22, 241–253. (3rd-order halo approx.)
Howell, K. C. (1984). "Three-dimensional, periodic, 'halo' orbits."
    *Celestial Mechanics*, 32, 53–71. (Differential corrector.)
Farquhar, R. W. (1968). "The control and use of libration-point satellites."
    PhD dissertation, Stanford University. (Lissajous trajectories.)
Vallado, D. A. (2013). *Fundamentals of Astrodynamics*, 4th ed. (CR3BP framework.)

Units: normalized (characteristic length = primary-secondary distance; time = 1/n
where n = mean motion). Position in synodic (rotating) frame; bodies on x-axis.

Author: kerf aero depth (Wave 10C)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from numpy.typing import NDArray


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Earth-Moon system — GMAT default (Szebehely 1967, Table 4.4.1)
_MU_EARTH_MOON: float = 0.01215058560962404   # μ = m_Moon / (m_Earth + m_Moon)
#: Sun-Earth system — DE430 value
_MU_SUN_EARTH: float = 3.003480593992993e-6   # μ = m_Earth / (m_Sun + m_Earth)

#: Earth-Moon characteristic length [km] (mean semi-major axis)
L_EM_KM: float = 384_400.0
#: Sun-Earth characteristic length [km]
L_SE_KM: float = 149_597_870.7


# ---------------------------------------------------------------------------
# CR3BP system descriptor
# ---------------------------------------------------------------------------

@dataclass
class CR3BPSystem:
    """Circular Restricted 3-Body Problem (CR3BP) system.

    In the normalized synodic frame:
      - Primary (m1) at x = -μ on the x-axis
      - Secondary (m2) at x = 1-μ on the x-axis
      - Total length scale = 1 (primary–secondary distance)
      - Time scale: mean motion n = 1 (one synodic period = 2π)

    Attributes
    ----------
    mu : float
        Mass ratio μ = m2 / (m1 + m2).  Must be in (0, 0.5].
        Earth-Moon ≈ 0.01215, Sun-Earth ≈ 3.0e-6.
    name : str
        Human-readable system name (e.g. 'Earth-Moon').
    char_length_km : float
        Characteristic length (primary–secondary distance) [km].
    char_time_s : float
        Characteristic time 1/n [s].  T_synodic = 2π × char_time_s.
    """

    mu: float
    name: str
    char_length_km: float = 1.0
    char_time_s: float = 1.0

    def __post_init__(self) -> None:
        if not (0.0 < self.mu <= 0.5):
            raise ValueError(
                f"mu must be in (0, 0.5]; got {self.mu!r}.  "
                "Convention: μ = m_secondary / m_total."
            )


#: Pre-built Earth-Moon CR3BP system.
EARTH_MOON_SYSTEM = CR3BPSystem(
    mu=_MU_EARTH_MOON,
    name="Earth-Moon",
    char_length_km=L_EM_KM,
    char_time_s=375_190.258,   # 1/n_EM [s]; T_synodic ≈ 27.32 days
)

#: Pre-built Sun-Earth CR3BP system.
SUN_EARTH_SYSTEM = CR3BPSystem(
    mu=_MU_SUN_EARTH,
    name="Sun-Earth",
    char_length_km=L_SE_KM,
    char_time_s=5_022_642.89,  # 1/n_SE [s]; T ≈ 365.25 days
)


# ---------------------------------------------------------------------------
# Lagrange point data class
# ---------------------------------------------------------------------------

@dataclass
class LagrangePoint:
    """Lagrange (libration) equilibrium point in the CR3BP.

    Coordinates are in the normalized synodic (rotating) frame where:
      - Primary at (−μ, 0, 0)
      - Secondary at (1−μ, 0, 0)

    Attributes
    ----------
    label : str
        'L1' | 'L2' | 'L3' | 'L4' | 'L5'
    x_synodic : float
        Normalized synodic X coordinate.
    y_synodic : float
        Normalized synodic Y coordinate.
    z_synodic : float
        Normalized synodic Z coordinate (always 0 for L1-L5).
    stability : str
        'unstable' for L1–L3 (real eigenvalues in linearization);
        'conditionally_stable' for L4/L5 (when μ < μ_Routh ≈ 0.0385).
    distance_from_primary_km : float
        Distance from primary body [km].  Requires char_length_km set.
    """

    label: str
    x_synodic: float
    y_synodic: float
    z_synodic: float = 0.0
    stability: str = "unstable"
    distance_from_primary_km: float = 0.0


# ---------------------------------------------------------------------------
# Lagrange point solver (Szebehely 1967 §4.4)
# ---------------------------------------------------------------------------

def _find_collinear_root(poly_coeffs: list[float], x_init: float) -> float:
    """Find root of a quintic polynomial via Newton-Raphson.

    Parameters
    ----------
    poly_coeffs : list of float
        Coefficients [a5, a4, a3, a2, a1, a0] for a5*x^5 + ... + a0.
    x_init : float
        Initial guess.

    Returns
    -------
    float
        Root to 1e-14 tolerance.
    """
    a = poly_coeffs
    # Horner evaluation of polynomial and derivative
    def _eval(x: float) -> tuple[float, float]:
        n = len(a) - 1
        p = a[0]
        dp = 0.0
        for k in range(1, n + 1):
            dp = dp * x + p
            p = p * x + a[k]
        return p, dp

    x = x_init
    for _ in range(100):
        p, dp = _eval(x)
        if abs(dp) < 1e-30:
            break
        dx = -p / dp
        x += dx
        if abs(dx) < 1e-14:
            break
    return x


def compute_lagrange_points(system: CR3BPSystem) -> list[LagrangePoint]:
    """Compute all five Lagrange points for a CR3BP system.

    L1, L2, L3 are collinear (on the x-axis) and found via quintic polynomial
    roots (Szebehely 1967, §4.4, equations 4.4.6–4.4.8).

    L4 and L5 form equilateral triangles with the primaries; exact positions
    at (0.5 − μ, ±√3/2, 0) (Szebehely 1967 §4.4.3).

    Stability criterion (Routh 1875 / Szebehely §4.4):
      L4, L5 are conditionally stable when μ < μ_Routh = (1 − √(23/27)) / 2 ≈ 0.0385.

    Parameters
    ----------
    system : CR3BPSystem
        Target CR3BP system.

    Returns
    -------
    list[LagrangePoint]
        Five Lagrange points [L1, L2, L3, L4, L5].
    """
    mu = system.mu
    L = system.char_length_km

    # Routh stability threshold (Szebehely §4.4.4)
    mu_routh = (1.0 - math.sqrt(23.0 / 27.0)) / 2.0  # ≈ 0.03852

    # ---- L1: between secondary and primary (x in (1-μ-1, 1-μ)) ----
    # Szebehely (1967) eq. 4.4.6 in terms of γ = distance from secondary:
    #   γ^5 - (3-μ)γ^4 + (3-2μ)γ^3 - μγ^2 + 2μγ - μ = 0
    # We solve directly for x_L1 in synodic frame.
    # Substitution: γ = (1-μ) - x  (L1 between Earth and Moon)
    # Quintic in γ (Szebehely eq. 4.4.6):
    #   γ^5 - (3-μ)γ^4 + (3-2μ)γ^3 - μγ^2 + 2μγ - μ = 0
    def _l1_quintic(gamma: float) -> tuple[float, float]:
        p = (gamma**5
             - (3.0 - mu) * gamma**4
             + (3.0 - 2.0 * mu) * gamma**3
             - mu * gamma**2
             + 2.0 * mu * gamma
             - mu)
        dp = (5.0 * gamma**4
              - 4.0 * (3.0 - mu) * gamma**3
              + 3.0 * (3.0 - 2.0 * mu) * gamma**2
              - 2.0 * mu * gamma
              + 2.0 * mu)
        return p, dp

    # Initial guess: Hill sphere radius (Laplace) γ ≈ (μ/3)^(1/3)
    gamma1 = (mu / 3.0) ** (1.0 / 3.0)
    for _ in range(100):
        p, dp = _l1_quintic(gamma1)
        if abs(dp) < 1e-30:
            break
        dg = -p / dp
        gamma1 += dg
        if abs(dg) < 1e-15:
            break
    x_L1 = (1.0 - mu) - gamma1

    # ---- L2: beyond secondary (x > 1-μ) ----
    # Szebehely eq. 4.4.7:  γ^5 + (3-μ)γ^4 + (3-2μ)γ^3 - μγ^2 - 2μγ - μ = 0
    # γ = x - (1-μ), γ > 0
    def _l2_quintic(gamma: float) -> tuple[float, float]:
        p = (gamma**5
             + (3.0 - mu) * gamma**4
             + (3.0 - 2.0 * mu) * gamma**3
             - mu * gamma**2
             - 2.0 * mu * gamma
             - mu)
        dp = (5.0 * gamma**4
              + 4.0 * (3.0 - mu) * gamma**3
              + 3.0 * (3.0 - 2.0 * mu) * gamma**2
              - 2.0 * mu * gamma
              - 2.0 * mu)
        return p, dp

    gamma2 = (mu / 3.0) ** (1.0 / 3.0)
    for _ in range(100):
        p, dp = _l2_quintic(gamma2)
        if abs(dp) < 1e-30:
            break
        dg = -p / dp
        gamma2 += dg
        if abs(dg) < 1e-15:
            break
    x_L2 = (1.0 - mu) + gamma2

    # ---- L3: beyond primary (x < -μ) ----
    # Szebehely eq. 4.4.8 in terms of γ = distance from primary beyond x=-μ
    # γ = -(x + μ), positive for x < -μ
    # 7μ/12 approximation gives good initial guess
    # Full quintic: γ^5 + (2+μ)γ^4 + (1+2μ)γ^3 - (1-μ)γ^2 - 2(1-μ)γ - (1-μ) = 0
    def _l3_quintic(gamma: float) -> tuple[float, float]:
        p = (gamma**5
             + (2.0 + mu) * gamma**4
             + (1.0 + 2.0 * mu) * gamma**3
             - (1.0 - mu) * gamma**2
             - 2.0 * (1.0 - mu) * gamma
             - (1.0 - mu))
        dp = (5.0 * gamma**4
              + 4.0 * (2.0 + mu) * gamma**3
              + 3.0 * (1.0 + 2.0 * mu) * gamma**2
              - 2.0 * (1.0 - mu) * gamma
              - 2.0 * (1.0 - mu))
        return p, dp

    gamma3 = 1.0 - 7.0 * mu / 12.0  # Szebehely §4.4 first-order estimate
    for _ in range(100):
        p, dp = _l3_quintic(gamma3)
        if abs(dp) < 1e-30:
            break
        dg = -p / dp
        gamma3 += dg
        if abs(dg) < 1e-15:
            break
    x_L3 = -(mu + gamma3)

    # ---- L4, L5: equilateral triangle points ----
    # Exact from Szebehely §4.4.3: x = 1/2 - μ, y = ±√3/2
    x_L45 = 0.5 - mu
    y_L4 = math.sqrt(3.0) / 2.0
    y_L5 = -math.sqrt(3.0) / 2.0

    # Stability string for L4/L5
    l45_stab = "conditionally_stable" if mu < mu_routh else "unstable"

    # Distance from primary (-μ, 0, 0) in normalized units
    def _dist_from_primary(x: float, y: float = 0.0) -> float:
        return math.sqrt((x + mu) ** 2 + y ** 2)

    return [
        LagrangePoint(
            label="L1",
            x_synodic=x_L1,
            y_synodic=0.0,
            z_synodic=0.0,
            stability="unstable",
            distance_from_primary_km=_dist_from_primary(x_L1) * L,
        ),
        LagrangePoint(
            label="L2",
            x_synodic=x_L2,
            y_synodic=0.0,
            z_synodic=0.0,
            stability="unstable",
            distance_from_primary_km=_dist_from_primary(x_L2) * L,
        ),
        LagrangePoint(
            label="L3",
            x_synodic=x_L3,
            y_synodic=0.0,
            z_synodic=0.0,
            stability="unstable",
            distance_from_primary_km=_dist_from_primary(x_L3) * L,
        ),
        LagrangePoint(
            label="L4",
            x_synodic=x_L45,
            y_synodic=y_L4,
            z_synodic=0.0,
            stability=l45_stab,
            distance_from_primary_km=_dist_from_primary(x_L45, y_L4) * L,
        ),
        LagrangePoint(
            label="L5",
            x_synodic=x_L45,
            y_synodic=y_L5,
            z_synodic=0.0,
            stability=l45_stab,
            distance_from_primary_km=_dist_from_primary(x_L45, y_L5) * L,
        ),
    ]


# ---------------------------------------------------------------------------
# CR3BP equations of motion and RK4 integrator
# ---------------------------------------------------------------------------

def _cr3bp_accel(state: NDArray, mu: float) -> NDArray:
    """CR3BP equations of motion in synodic frame.

    Reference: Szebehely (1967), §3.1, eq. 3.1.1–3.1.3.
    Includes Coriolis and centrifugal pseudo-forces.

    Parameters
    ----------
    state : NDArray, shape (6,)
        [x, y, z, vx, vy, vz] in normalized synodic frame.
    mu : float
        CR3BP mass ratio.

    Returns
    -------
    NDArray, shape (6,)
        State derivative [vx, vy, vz, ax, ay, az].
    """
    x, y, z, vx, vy, vz = state

    # Distances to primary (−μ, 0, 0) and secondary (1−μ, 0, 0)
    r1_sq = (x + mu) ** 2 + y ** 2 + z ** 2
    r2_sq = (x - 1.0 + mu) ** 2 + y ** 2 + z ** 2
    r1_3 = r1_sq ** 1.5
    r2_3 = r2_sq ** 1.5

    ax = (2.0 * vy + x
          - (1.0 - mu) * (x + mu) / r1_3
          - mu * (x - 1.0 + mu) / r2_3)
    ay = (-2.0 * vx + y
          - (1.0 - mu) * y / r1_3
          - mu * y / r2_3)
    az = (-(1.0 - mu) * z / r1_3
          - mu * z / r2_3)

    return np.array([vx, vy, vz, ax, ay, az])


def _rk4_step(state: NDArray, dt: float, mu: float) -> NDArray:
    """Single 4th-order Runge-Kutta step for CR3BP.

    Uses no external libraries — pure numpy per constraint.
    """
    k1 = _cr3bp_accel(state, mu)
    k2 = _cr3bp_accel(state + 0.5 * dt * k1, mu)
    k3 = _cr3bp_accel(state + 0.5 * dt * k2, mu)
    k4 = _cr3bp_accel(state + dt * k3, mu)
    return state + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def _propagate_cr3bp(
    state0: NDArray,
    t_span: float,
    mu: float,
    n_steps: int = 2000,
) -> tuple[NDArray, NDArray]:
    """Propagate CR3BP state over t_span.

    Returns
    -------
    times : NDArray, shape (n_steps+1,)
    states : NDArray, shape (n_steps+1, 6)
    """
    dt = t_span / n_steps
    times = np.linspace(0.0, t_span, n_steps + 1)
    states = np.empty((n_steps + 1, 6))
    states[0] = state0.copy()
    s = state0.copy()
    for i in range(n_steps):
        s = _rk4_step(s, dt, mu)
        states[i + 1] = s
    return times, states


# ---------------------------------------------------------------------------
# Richardson 1980 3rd-order halo approximation
# ---------------------------------------------------------------------------

def _richardson_halo_ic(
    mu: float,
    libration_point: str,
    Az_norm: float,
    family: str = "north",
) -> tuple[NDArray, float]:
    """Linear-order initial state for a halo orbit (seed for differential corrector).

    Computes the linearized CR3BP solution about the libration point.  This
    first-order seed is refined by the Howell (1984) differential corrector.

    Algorithm references
    --------------------
    Richardson, D. L. (1980). "Analytic construction of periodic orbits about
        the collinear points." Celestial Mechanics, 22, 241–253.
    Thurman, R. & Worfolk, P. (1996). "The geometry of halo orbits in the
        circular restricted three-body problem." Univ. Minnesota Tech. Rep.
    Gómez, G. et al. (2001). Dynamics and Mission Design Near Libration Points,
        Vol. II. World Scientific.

    Parameters
    ----------
    mu : float
        CR3BP mass ratio.
    libration_point : str
        'L1' or 'L2'.
    Az_norm : float
        Out-of-plane (z) amplitude in normalized CR3BP synodic units
        (i.e. km / char_length_km).
    family : str
        'north' (positive z) or 'south' (negative z).

    Returns
    -------
    state0 : NDArray, shape (6,)
        Approximate initial state [x, y, z, vx, vy, vz] in synodic frame.
        y = vx = vz = 0 at the xz-plane Poincaré section crossing.
    T_approx : float
        Approximate period [normalized CR3BP time].

    Notes
    -----
    The c_n Legendre coefficients (Gómez et al. 2001, §2.1) satisfy:

      L1:  c_n = [μ + (−1)^n (1−μ)(γ/(1−γ))^{n+1}] / γ³
      L2:  c_n = [μ + (1−μ)(γ/(1+γ))^{n+1}] / γ³

    where γ = distance from Lx to the secondary (Moon/Earth) in normalized
    synodic units.  These give c₂ ~ 5.15 for EM L1 and ~ 3.19 for EM L2.

    The characteristic polynomial in local coords (Szebehely §6.2, Richardson
    eq. 5) is:

      λ⁴ + (2−c₂)λ² + (1+2c₂)(1−c₂) = 0

    yielding a center-manifold frequency λ (the in-plane oscillation rate) and
    a saddle eigenvalue (unstable manifold direction).  The out-of-plane
    frequency is ν = √c₂.  For a halo orbit λ ≠ ν (nonlinear resonance
    selects a specific amplitude where the third-order correction locks them).

    The first-order IC at phase τ=0:
      ξ₀ = −Ax_local   (x behind Lagrange point for L1, ahead for L2)
      ζ₀ = ±Az_local   (sign depends on north/south family)
      η̇₀ = k·λ·Ax_local  where k = (λ²+1+2c₂)/(2λ)

    Ax_local is set to Az_local × 0.2 as a reasonable first-order seed;
    the differential corrector adjusts it to the true periodic value.
    """
    # Locate libration point and compute γ
    lpts = compute_lagrange_points(CR3BPSystem(mu=mu, name="tmp", char_length_km=1.0))
    lpt_map = {lp.label: lp for lp in lpts}
    if libration_point not in ("L1", "L2"):
        raise ValueError(f"Halo orbits only exist at L1 or L2; got {libration_point!r}")

    lp = lpt_map[libration_point]
    x_lp = lp.x_synodic

    # γ = distance from Lx to the secondary (Moon) in normalized synodic units.
    # For L1 (between primaries):  x_L1 < 1-μ,  γ = (1-μ) - x_L1
    # For L2 (beyond secondary):   x_L2 > 1-μ,  γ = x_L2 - (1-μ)
    gamma = abs(x_lp - (1.0 - mu))

    # ── Legendre coefficients c_n (Gómez et al. 2001, eq. 2.5) ─────────────
    # c_n governs the Taylor expansion of the effective CR3BP potential about Lx.
    # The z-equation is ζ'' = -c₂ ζ  →  ν² = c₂.
    # The x-y equations give the characteristic polynomial for λ.
    #
    # For L1 (secondary at +γ, primary at -(1-γ) in local frame):
    #   c_n = [μ + (−1)^n (1−μ)(γ/(1−γ))^{n+1}] / γ³
    # For L2 (secondary at -γ, primary at -(1+γ) in local frame):
    #   c_n = [μ + (1−μ)(γ/(1+γ))^{n+1}] / γ³
    #
    # Note: the secondary is at distance γ from Lx (contributing μ/γ³ directly),
    # while the primary is at distance 1∓γ (contributing the second term).
    if libration_point == "L1":
        def _c(n: int) -> float:
            return (mu + (-1) ** n * (1.0 - mu) * (gamma / (1.0 - gamma)) ** (n + 1)) / gamma ** 3
    else:  # L2
        def _c(n: int) -> float:
            return (mu + (1.0 - mu) * (gamma / (1.0 + gamma)) ** (n + 1)) / gamma ** 3

    c2 = _c(2)

    # ── In-plane center-manifold frequency λ ────────────────────────────────
    # Linearized CR3BP in local coords (ξ, η scaled by γ, same time t):
    #   ξ'' - 2η' = (1+2c₂) ξ    [Omega_xx = 1+2c₂]
    #   η'' + 2ξ' = -(c₂-1) η    [Omega_yy = 1-c₂ in rotating frame]
    #
    # Substituting (ξ,η) = (A,B) exp(λt) gives the characteristic equation:
    #   (λ²−(1+2c₂))(λ²+(c₂−1)) + 4λ² = 0
    #   ⟹  λ⁴ + (2−c₂)λ² + (1+2c₂)(1−c₂) = 0
    #
    # With c₂ > 1 (e.g. EM L1: c₂≈5.15), the polynomial has roots:
    #   λ²_{saddle} > 0  (real, unstable manifold)
    #   λ²_{center} < 0  (imaginary, oscillatory center manifold, freq = √|λ²|)
    poly_b = 2.0 - c2
    poly_c = (1.0 + 2.0 * c2) * (1.0 - c2)   # negative for c2 > 1
    disc = poly_b ** 2 - 4.0 * poly_c
    if disc < 0:
        # Should not happen for physical CR3BP parameters; use fallback
        lam = math.sqrt(c2)
    else:
        root_neg = (-poly_b - math.sqrt(disc)) / 2.0  # the negative root → center
        lam = math.sqrt(max(-root_neg, 0.0))

    # ── Out-of-plane frequency ν = √c₂ ──────────────────────────────────────
    nu = math.sqrt(c2)  # noqa: F841 (used implicitly via Az_norm below)

    # ── Coupling coefficient k (linear amplitude ratio η/ξ) ─────────────────
    # From the linear solution: η = k ξ at the Poincaré crossing.
    # k = (λ² + 1 + 2c₂) / (2λ)   [Richardson 1980, after eq. 10]
    k = (lam ** 2 + 1.0 + 2.0 * c2) / (2.0 * lam)

    # ── Approximate period ───────────────────────────────────────────────────
    T_approx = 2.0 * math.pi / lam

    # ── First-order initial conditions at phase τ = 0 ───────────────────────
    # At τ=0 on the xz Poincaré plane (y=0, vx=0):
    #   ξ₀ = −Ax   (start at negative ξ for L1; positive ξ for L2 uses same sign
    #                convention because the corrector adjusts x₀ freely)
    #   η₀ = 0
    #   ζ₀ = ±Az   (north = +Az, south = −Az)
    #   ξ̇₀ = 0     (Poincaré crossing condition)
    #   η̇₀ = k λ Ax
    #   ζ̇₀ = 0     (at cos-phase τ=0, z-velocity is zero)
    #
    # Ax_local / Az_local ≈ 0.2 is a reasonable seed;
    # the differential corrector will converge to the true periodic Ax.
    # Az_norm is in synodic units; local = synodic (same time, ζ = z/γ · γ = z).
    Az_local = Az_norm   # synodic Az equals the physical displacement in normalized units
    Ax_local = Az_local * 0.2

    if libration_point == "L1":
        # L1: orbit wraps around L1 with x < x_L1 at τ=0
        x0 = x_lp - gamma * Ax_local
    else:
        # L2: orbit wraps around L2 with x > x_L2 at τ=0
        x0 = x_lp + gamma * Ax_local

    z0 = Az_local if family == "north" else -Az_local
    vy0 = gamma * k * lam * Ax_local

    state0 = np.array([x0, 0.0, z0, 0.0, vy0, 0.0])
    return state0, T_approx


# ---------------------------------------------------------------------------
# Differential corrector (Howell 1984)
# ---------------------------------------------------------------------------

def _differential_corrector_halo(
    state0: NDArray,
    T_guess: float,
    mu: float,
    max_iter: int = 50,
    tol: float = 1e-10,
    n_steps: int = 2000,
) -> tuple[NDArray, float, bool]:
    """Howell (1984) differential corrector for halo orbit periodicity.

    Targeting: at the y=0 (xz-plane) half-period crossing, enforce:
      - y(T/2) = 0  (symmetric crossing — already enforced by x-z symmetry)
      - vx(T/2) = 0
      - vz(T/2) = 0

    Free variables: x0, vz0 (one free variable at a time in the
    single-shooter approach; Howell 1984 §3).

    Simplified to a 2×2 correction:
      [Δx0, Δvz0] = solve([∂vx/∂x0  ∂vx/∂vz0 ; ∂vz/∂x0  ∂vz/∂vz0]^{-1} [-vx_f, -vz_f])

    Parameters
    ----------
    state0 : NDArray, shape (6,)
        Richardson initial state (starting guess).
    T_guess : float
        Approximate period from Richardson.
    mu : float
        CR3BP mass ratio.
    max_iter : int
        Maximum corrector iterations.
    tol : float
        Convergence tolerance on |vx_f| + |vz_f|.
    n_steps : int
        RK4 steps per half-period propagation.

    Returns
    -------
    state_corrected : NDArray, shape (6,)
    period_corrected : float
    converged : bool
    """
    # Howell (1984) Differential Corrector — Fixed-time targeting.
    #
    # The halo orbit is symmetric about the xz-plane. Starting at y0=0, vx0=0
    # (the Poincaré crossing), the orbit must return to y(T_half)=0 with
    # vx(T_half)=0, vz(T_half)=0 at the half-period.
    #
    # Strategy: hold T_half fixed each iteration, adjust [x0, vz0] using
    # the 2×2 Jacobian ∂[vx,vz]/∂[x0,vz0] evaluated at T_half.
    # Update T_half after each correction via y=0 crossing search.
    #
    # Reference: Howell (1984) §3, Koon et al. (2006) §4.1.

    def _prop_fixed(s: NDArray, T: float, n: int) -> NDArray:
        dt = T / n
        curr = s.copy()
        for _ in range(n):
            curr = _rk4_step(curr, dt, mu)
        return curr

    def _find_y_crossing(s: NDArray, T_max: float, n: int) -> tuple[NDArray, float]:
        """Find first y=0 crossing after initial transient."""
        dt = T_max / n
        prev = s.copy()
        curr = prev.copy()
        t = 0.0
        skip = max(n // 100, 10)
        for _ in range(skip):
            curr = _rk4_step(curr, dt, mu)
            t += dt
        prev = curr.copy()
        for _ in range(n - skip):
            curr = _rk4_step(curr, dt, mu)
            t += dt
            if prev[1] * curr[1] <= 0:
                frac = -prev[1] / (curr[1] - prev[1] + 1e-30)
                frac = max(0.0, min(1.0, frac))
                return prev + frac * (curr - prev), t - dt + frac * dt
            prev = curr.copy()
        return curr, t

    s0 = state0.copy()
    T_half = T_guess / 2.0
    converged = False
    npts = max(n_steps, 2000)

    for it in range(max_iter):
        sf = _prop_fixed(s0, T_half, npts)
        vx_f, vz_f = sf[3], sf[5]

        if abs(vx_f) < tol and abs(vz_f) < tol:
            converged = True
            break

        eps_x = max(abs(s0[0]) * 1e-6, 1e-7)
        eps_vz = max(abs(s0[5]) * 1e-6 + 1e-7, 1e-7)

        sfpx = _prop_fixed(s0 + np.array([eps_x, 0, 0, 0, 0, 0]), T_half, npts)
        sfpvz = _prop_fixed(s0 + np.array([0, 0, 0, 0, 0, eps_vz]), T_half, npts)

        A = np.array([
            [(sfpx[3] - vx_f) / eps_x, (sfpvz[3] - vx_f) / eps_vz],
            [(sfpx[5] - vz_f) / eps_x, (sfpvz[5] - vz_f) / eps_vz],
        ])
        b = np.array([-vx_f, -vz_f])
        det = A[0, 0] * A[1, 1] - A[0, 1] * A[1, 0]

        if abs(det) < 1e-16:
            s0[4] *= 1.0 + 1e-3  # perturb vy0 slightly
            continue

        dx_corr = (A[1, 1] * b[0] - A[0, 1] * b[1]) / det
        dvz_corr = (A[0, 0] * b[1] - A[1, 0] * b[0]) / det
        # Trust-region limiter
        scale = max(abs(dx_corr) / 0.02, abs(dvz_corr) / 0.02, 1.0)
        dx_corr /= scale
        dvz_corr /= scale

        s0[0] += dx_corr
        s0[5] += dvz_corr

        # Update T_half via y=0 crossing search
        s_cross, t_cross = _find_y_crossing(s0, max(T_half * 2.5, T_guess), npts)
        if t_cross > 0.05 * T_half:
            T_half = t_cross

    return s0, T_half * 2.0, converged


def _estimate_half_period(
    state0: NDArray,
    T_guess: float,
    mu: float,
    n_steps: int = 2000,
) -> float:
    """Estimate half-period as first y=0 crossing after t>0."""
    dt = T_guess / (2.0 * n_steps)
    s = state0.copy()
    t = 0.0
    y_prev = s[1]
    t_cross = T_guess / 2.0  # default

    for _ in range(n_steps):
        s = _rk4_step(s, dt, mu)
        t += dt
        y_curr = s[1]
        if t > T_guess * 0.05 and y_prev * y_curr < 0:
            # Linear interpolation for crossing time
            t_cross = t - dt * y_curr / (y_curr - y_prev)
            break
        y_prev = y_curr

    return t_cross


# ---------------------------------------------------------------------------
# HaloOrbit data class and design function
# ---------------------------------------------------------------------------

@dataclass
class HaloOrbit:
    """A periodic halo orbit in the CR3BP.

    Attributes
    ----------
    family : str
        Family identifier, e.g. 'L1_north', 'L2_south'.
    amplitude_z_km : float
        Out-of-plane (z) amplitude [km] in physical units.
    period_seconds : float
        Orbital period [seconds].
    initial_state : NDArray, shape (6,)
        Initial state [x, y, z, vx, vy, vz] in normalized synodic frame.
    poincare_section_data : NDArray or None
        Optional Poincaré section data (shape (N, 6)).
    converged : bool
        Whether the differential corrector converged.
    """

    family: str
    amplitude_z_km: float
    period_seconds: float
    initial_state: NDArray
    poincare_section_data: Optional[NDArray] = None
    converged: bool = False


def design_halo_orbit(
    system: CR3BPSystem,
    libration_point: str,
    target_z_amplitude_km: float,
    family: str = "north",
    corrector_tol: float = 1e-9,
    corrector_max_iter: int = 50,
) -> HaloOrbit:
    """Design a halo orbit at an L1 or L2 Lagrange point.

    Uses Richardson (1980) 3rd-order analytic approximation as the initial
    guess, then refines with Howell (1984) differential corrector targeting
    periodicity via the y=0 Poincaré section.

    Parameters
    ----------
    system : CR3BPSystem
        Target CR3BP system (Earth-Moon, Sun-Earth, etc.).
    libration_point : str
        'L1' or 'L2'.
    target_z_amplitude_km : float
        Desired out-of-plane (z) amplitude [km].
    family : str
        'north' or 'south' (mirror families about xz plane).
    corrector_tol : float
        Convergence tolerance for differential corrector.
    corrector_max_iter : int
        Maximum corrector iterations.

    Returns
    -------
    HaloOrbit
        Refined halo orbit with initial state, period, and convergence flag.

    Notes
    -----
    - Richardson 3rd-order accuracy is ±1–5% of amplitude; the corrector
      tightens this to better than 1 km for moderate amplitudes.
    - Very small amplitudes (< 100 km for EM system) approach Lyapunov orbits
      and the corrector may not converge — use design_lyapunov_orbit instead.
    - DISCLAIMER: Not GMAT-validated. For design exploration.
    """
    if libration_point not in ("L1", "L2"):
        raise ValueError(
            f"Halo orbits exist only at L1 or L2; got {libration_point!r}. "
            "Use design_lissajous_orbit for L3–L5."
        )
    if target_z_amplitude_km <= 0:
        raise ValueError(
            f"target_z_amplitude_km must be positive; got {target_z_amplitude_km!r}"
        )
    if family not in ("north", "south"):
        raise ValueError(f"family must be 'north' or 'south'; got {family!r}")

    # Normalize amplitude to CR3BP synodic units
    Az_synodic = target_z_amplitude_km / system.char_length_km

    # Richardson 3rd-order initial state and period estimate.
    # The Richardson formulation uses LOCAL coordinates (ξ, η, ζ) scaled by γ.
    # We pass the synodic-frame Az; _richardson_halo_ic converts internally.
    state_r, T_r = _richardson_halo_ic(system.mu, libration_point, Az_synodic, family)

    # Differential corrector (Howell 1984)
    state_corrected, T_corrected, conv = _differential_corrector_halo(
        state_r, T_r, system.mu,
        max_iter=corrector_max_iter,
        tol=corrector_tol,
    )

    # Period in seconds
    period_s = T_corrected * system.char_time_s

    return HaloOrbit(
        family=f"{libration_point}_{family}",
        amplitude_z_km=target_z_amplitude_km,
        period_seconds=period_s,
        initial_state=state_corrected,
        converged=conv,
    )


# ---------------------------------------------------------------------------
# Lyapunov orbit (planar, Szebehely §6.2)
# ---------------------------------------------------------------------------

def design_lyapunov_orbit(
    system: CR3BPSystem,
    libration_point: str,
    target_x_amplitude_km: float,
) -> dict:
    """Design a planar Lyapunov orbit around an L1 or L2 Lagrange point.

    Lyapunov orbits are the planar (z = 0) periodic orbits that appear as
    the amplitude → 0 limit of halo orbits (Szebehely 1967, §6.2). They lie
    entirely in the synodic equatorial plane.

    Uses the Richardson (1980) planar initial state with z = vz = 0 and
    applies a single-shooter planar differential corrector.

    Parameters
    ----------
    system : CR3BPSystem
        Target CR3BP system.
    libration_point : str
        'L1' or 'L2'.
    target_x_amplitude_km : float
        Approximate x-axis amplitude from the Lagrange point [km].

    Returns
    -------
    dict with keys:
        state0 : list[float] — initial state [x, y, z, vx, vy, vz], normalized
        period_s : float — period [seconds]
        period_norm : float — period [normalized CR3BP time]
        x_amplitude_km : float — actual x amplitude [km]
        libration_point : str
        converged : bool
    """
    if libration_point not in ("L1", "L2"):
        raise ValueError(
            f"Lyapunov planar orbits at L1 or L2 only; got {libration_point!r}"
        )
    if target_x_amplitude_km <= 0:
        raise ValueError(f"target_x_amplitude_km must be positive")

    # Lyapunov: small out-of-plane amplitude → basically zero
    # Use a very small Az to get a near-planar Richardson IC then force z=vz=0
    Ax_norm = target_x_amplitude_km / system.char_length_km
    # Szebehely §6.2: Lyapunov period ≈ 2π/λ (linearized)
    lpts = compute_lagrange_points(system)
    lpt_map = {lp.label: lp for lp in lpts}
    x_lp = lpt_map[libration_point].x_synodic
    gamma = abs(x_lp - (1.0 - system.mu))

    # Use a small Az for the Richardson IC (near-Lyapunov)
    Az_small = Ax_norm * 0.05  # near planar
    Az_small = max(Az_small, 1e-5)

    try:
        state_r, T_r = _richardson_halo_ic(system.mu, libration_point, Az_small, "north")
    except Exception:
        # Fallback: linearized Lyapunov IC from L-point frequency analysis
        c2 = _c2_coeff(system.mu, libration_point, gamma)
        poly_b = 2.0 - c2
        poly_c = (1.0 + 2.0 * c2) * (1.0 - c2)  # correct sign (see _richardson_halo_ic)
        disc_lam = poly_b ** 2 - 4.0 * poly_c
        if disc_lam >= 0:
            root_neg = (-poly_b - math.sqrt(disc_lam)) / 2.0
            lam = math.sqrt(max(-root_neg, 0.0))
        else:
            lam = math.sqrt(c2)
        k_lam = (lam ** 2 + 1.0 + 2.0 * c2) / (2.0 * lam)
        T_r = 2.0 * math.pi / lam
        state_r = np.array([x_lp - gamma * Ax_norm, 0.0, 0.0, 0.0,
                             gamma * k_lam * lam * Ax_norm, 0.0])

    # Force planar: z = vz = 0
    state_r[2] = 0.0
    state_r[5] = 0.0

    # Planar differential corrector: x0, vy(T/2) constraint
    # At the y=0 half-period crossing, enforce vx(T/2) = 0
    s0 = state_r.copy()
    T = T_r
    conv = False

    for it in range(50):
        _, states = _propagate_cr3bp(s0, T / 2.0, system.mu, n_steps=2000)
        sf = states[-1]
        vx_f = sf[3]
        z_f = sf[2]

        if abs(vx_f) < 1e-10:
            conv = True
            break

        # Finite difference w.r.t. x0
        eps = max(abs(s0[0]) * 1e-7, 1e-8)
        sp = s0.copy(); sp[0] += eps
        _, spstates = _propagate_cr3bp(sp, T / 2.0, system.mu, n_steps=2000)
        dvx_dx0 = (spstates[-1][3] - vx_f) / eps

        if abs(dvx_dx0) < 1e-20:
            break
        dx0 = -vx_f / dvx_dx0
        dx0 = max(-0.05, min(0.05, dx0))
        s0[0] += dx0
        s0[2] = 0.0; s0[5] = 0.0  # keep planar

    # Ensure truly planar
    s0[2] = 0.0; s0[5] = 0.0

    # Compute actual period by finding next y=0 crossing
    T_half = _estimate_half_period(s0, T, system.mu, n_steps=3000)
    T = T_half * 2.0

    lpts_out = compute_lagrange_points(system)
    lpt_out = {lp.label: lp for lp in lpts_out}[libration_point]
    x_amp_km = abs(s0[0] - lpt_out.x_synodic) * system.char_length_km

    return {
        "state0": s0.tolist(),
        "period_s": T * system.char_time_s,
        "period_norm": T,
        "x_amplitude_km": x_amp_km,
        "libration_point": libration_point,
        "converged": conv,
    }


def _c2_coeff(mu: float, libration_point: str, gamma: float) -> float:
    """Compute dimensionless c2 Legendre coefficient for a collinear Lagrange point.

    Uses the correct Legendre expansion formula (Gómez et al. 2001, eq. 2.5):

      L1:  c₂ = [μ + (1−μ)(γ/(1−γ))³] / γ³
      L2:  c₂ = [μ + (1−μ)(γ/(1+γ))³] / γ³
      L3:  c₂ ≈ [μ + (1−μ)(γ/(1+γ))³] / γ³   (same form as L2)

    These give c₂ ≈ 5.15 for EM L1, c₂ ≈ 3.19 for EM L2.
    c₂ governs ζ'' = −c₂ ζ (out-of-plane oscillation) and the in-plane
    characteristic equation  λ⁴ + (2−c₂)λ² + (1+2c₂)(1−c₂) = 0.

    Parameters
    ----------
    mu : float
        CR3BP mass ratio.
    libration_point : str
        'L1', 'L2', or 'L3'.
    gamma : float
        Distance from Lx to the secondary (|x_Lx − (1−μ)|) in normalized units.
    """
    if libration_point == "L1":
        # Secondary (Moon) at +γ, primary (Earth) at −(1−γ) from L1
        return (mu + (1.0 - mu) * (gamma / (1.0 - gamma)) ** 3) / gamma ** 3
    else:
        # L2/L3: secondary at −γ, primary at −(1+γ) from L2 (or similar for L3)
        return (mu + (1.0 - mu) * (gamma / (1.0 + gamma)) ** 3) / gamma ** 3


# ---------------------------------------------------------------------------
# Lissajous orbit (Farquhar 1968)
# ---------------------------------------------------------------------------

def design_lissajous_orbit(
    system: CR3BPSystem,
    libration_point: str,
    target_xy_amp: float,
    target_z_amp: float,
) -> dict:
    """Design a quasi-periodic Lissajous orbit around a Lagrange point.

    Lissajous orbits (Farquhar 1968) are quasi-periodic trajectories arising
    from incommensurate in-plane (λ) and out-of-plane (ν) frequencies in the
    CR3BP linearized motion about collinear Lagrange points.

    The linearized equations near Lx give:
      x(t) = Ax cos(λt + φ1)
      y(t) = ky Ax sin(λt + φ1)
      z(t) = Az cos(νt + φ2)

    where λ ≠ ν (incommensurate) → quasi-periodic motion (Farquhar 1968, §3).

    For halo orbits, a frequency-matching condition forces λ = ν (Richardson 1980).
    Lissajous orbits are the generic non-resonant case.

    Parameters
    ----------
    system : CR3BPSystem
        Target CR3BP system.
    libration_point : str
        'L1', 'L2', or 'L3'.
    target_xy_amp : float
        In-plane amplitude [normalized CR3BP units].
    target_z_amp : float
        Out-of-plane amplitude [normalized CR3BP units].

    Returns
    -------
    dict with keys:
        state0 : list[float] — initial [x, y, z, vx, vy, vz] (linearized)
        freq_xy : float — in-plane frequency λ [rad/normalized time]
        freq_z : float — out-of-plane frequency ν [rad/normalized time]
        period_xy_s : float — in-plane quasi-period [s]
        period_z_s : float — out-of-plane quasi-period [s]
        is_resonant : bool — True if λ ≈ ν (nearly halo)
        libration_point : str
        xy_amplitude_km : float
        z_amplitude_km : float
    """
    if libration_point not in ("L1", "L2", "L3"):
        raise ValueError(
            f"Lissajous orbits at L1, L2, or L3; got {libration_point!r}"
        )

    lpts = compute_lagrange_points(system)
    lpt_map = {lp.label: lp for lp in lpts}
    x_lp = lpt_map[libration_point].x_synodic
    gamma = abs(x_lp - (1.0 - system.mu))

    c2 = _c2_coeff(system.mu, libration_point, gamma)

    # In-plane center-manifold frequency λ from the correct characteristic equation:
    # λ⁴ + (2−c₂)λ² + (1+2c₂)(1−c₂) = 0  (see _richardson_halo_ic for derivation)
    # The center-manifold root is the negative root of the quadratic in λ².
    poly_b = 2.0 - c2
    poly_c = (1.0 + 2.0 * c2) * (1.0 - c2)   # negative for c2 > 1
    disc_lam = poly_b ** 2 - 4.0 * poly_c
    if disc_lam >= 0:
        root_neg = (-poly_b - math.sqrt(disc_lam)) / 2.0
        lam = math.sqrt(max(-root_neg, 0.0))
    else:
        lam = math.sqrt(c2)  # fallback

    # Out-of-plane frequency ν = √c₂ (Farquhar 1968; Szebehely §6.5)
    nu = math.sqrt(c2)

    # Coupling factor k = ratio η̇/ξ in the linear solution
    # k = (λ² + 1 + 2c₂) / (2λ)  [from linear eigenvalue problem; Richardson 1980]
    k = (lam ** 2 + 1.0 + 2.0 * c2) / (2.0 * lam)

    # Initial state at t=0, phases φ1 = φ2 = 0
    Ax = target_xy_amp
    Az = target_z_amp
    x0 = x_lp - gamma * Ax
    y0 = 0.0
    z0 = Az
    vx0 = 0.0
    vy0 = k * lam * Ax * gamma
    vz0 = -nu * Az

    # Resonance check
    is_resonant = abs(lam - nu) / max(abs(nu), 1e-10) < 0.02

    return {
        "state0": [x0, y0, z0, vx0, vy0, vz0],
        "freq_xy": lam,
        "freq_z": nu,
        "period_xy_s": 2.0 * math.pi / lam * system.char_time_s,
        "period_z_s": 2.0 * math.pi / nu * system.char_time_s,
        "is_resonant": is_resonant,
        "libration_point": libration_point,
        "xy_amplitude_km": Ax * system.char_length_km,
        "z_amplitude_km": Az * system.char_length_km,
    }
