"""State Transition Matrix (STM) propagation for orbit covariance analysis.

The STM Φ(t, t₀) maps a small perturbation in initial conditions to the
perturbation at time t:

    δx(t) = Φ(t, t₀) * δx(t₀)

where x = [r; v]  (6-vector: position + velocity in ECI, km and km/s).

The STM is integrated simultaneously with the state by augmenting the system:

    ẋ = f(x)                    (equations of motion)
    Φ̇ = A(x) * Φ               (Φ̇ = A·Φ, with Φ(t₀, t₀) = I₆)

where A = ∂f/∂x is the Jacobian (A-matrix) of the dynamics.

For two-body gravity (Keplerian), A has the analytic form (Battin 1987):

    A = [ 0₃   I₃ ]
        [ G₃   0₃ ]

where G₃ = -μ/r³ * (I₃ - 3*r̂*r̂ᵀ)  is the gravity gradient tensor.

For J2-perturbed dynamics, A is augmented with the J2 gradient terms.

Applications:
  - Covariance propagation: P(t) = Φ P(t₀) Φᵀ
  - Differential correction / targeting (δv = Φ_rv⁻¹ (r_target - r_prop))
  - Sensitivity analysis

References
----------
Battin, R.H. (1987). "An Introduction to the Mathematics and Methods of
    Astrodynamics." AIAA, §9.3.
Broucke, R. (1970). "On the matrizant of the two-body problem." Astron. Astrophys.
    6, 173–182.
Montenbruck & Gill (2000), §7.1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import numpy as np
from numpy.typing import NDArray

from .perturbations import MU_EARTH, J2, R_EARTH


# ---------------------------------------------------------------------------
# A-matrix (Jacobian of equations of motion)
# ---------------------------------------------------------------------------

def keplerian_jacobian(
    r_vec: NDArray,
    mu: float = MU_EARTH,
) -> NDArray:
    """Compute the 6×6 A-matrix for Keplerian two-body dynamics.

    A = [ 0₃   I₃ ]
        [ G   0₃ ]

    where G = ∂²U/∂r² = -μ/r³ * (I₃ - 3*r̂*r̂ᵀ) is the gravity gradient tensor.

    Parameters
    ----------
    r_vec : array-like, shape (3,)
        Position vector [km].
    mu : float
        Gravitational parameter [km^3/s^2].

    Returns
    -------
    NDArray, shape (6, 6)
        State Jacobian matrix.
    """
    r = np.asarray(r_vec, dtype=float)
    r_mag = float(np.linalg.norm(r))

    if r_mag < 1.0:
        raise ValueError(f"Position magnitude {r_mag} km too small")

    # Gravity gradient tensor G (3×3)
    r_hat = r / r_mag
    G = (mu / r_mag ** 3) * (3.0 * np.outer(r_hat, r_hat) - np.eye(3))

    A = np.zeros((6, 6))
    A[0:3, 3:6] = np.eye(3)    # velocity partials
    A[3:6, 0:3] = G             # gravity gradient
    return A


def j2_jacobian(
    r_vec: NDArray,
    mu: float = MU_EARTH,
    j2: float = J2,
    r_earth: float = R_EARTH,
) -> NDArray:
    """Compute the 6×6 A-matrix for J2-perturbed dynamics.

    Augments the Keplerian A-matrix with the J2 gravitational gradient.
    The J2 perturbing acceleration is:

        a_J2 = (3/2) μ J2 Re² / r⁵ * [...] (position-dependent)

    The Jacobian ∂a_J2/∂r is computed analytically.

    Parameters
    ----------
    r_vec : array-like, shape (3,)
        Position vector [km].
    mu : float
        Gravitational parameter [km^3/s^2].
    j2 : float
        J2 coefficient.
    r_earth : float
        Earth equatorial radius [km].

    Returns
    -------
    NDArray, shape (6, 6)
    """
    r = np.asarray(r_vec, dtype=float)
    r_mag = float(np.linalg.norm(r))
    x, y, z = r[0], r[1], r[2]

    # Keplerian part
    A = keplerian_jacobian(r, mu)

    # J2 gradient ∂a_J2/∂r (3×3) — analytic
    factor = (3.0 / 2.0) * mu * j2 * r_earth ** 2 / r_mag ** 5
    c = j2 * r_earth ** 2   # convenience

    # The J2 acceleration components:
    # a_x = factor * x * (5z²/r² - 1)
    # a_y = factor * y * (5z²/r² - 1)
    # a_z = factor * z * (5z²/r² - 3)
    # The gradient ∂a_x/∂x, etc. is obtained by differentiating
    # using the quotient rule:

    r2 = r_mag ** 2
    zr2 = z ** 2 / r2
    pre = (3.0 / 2.0) * mu * j2 * r_earth ** 2 / r_mag ** 5

    def da_dr(i: int, j: int) -> float:
        """∂a_J2[i] / ∂r[j]  (i,j in 0,1,2 → x,y,z)"""
        ri = r[i]
        rj = r[j]
        z2 = z ** 2
        delta_ij = 1 if i == j else 0
        delta_iz = 1 if i == 2 else 0
        delta_jz = 1 if j == 2 else 0
        # a_i = pre * r_i * (5z²/r² - (1 if i<2 else 3))
        c_i = 5.0 * zr2 - (1.0 if i < 2 else 3.0)
        # ∂a_i/∂r_j = pre * [ delta_ij * c_i + r_i * ∂c_i/∂r_j ]
        # ∂c_i/∂r_j = 5 * ∂(z²/r²)/∂r_j
        #            = 5 * (2z*delta_jz*r² - z²*2*r_j) / r^4
        #            = 5 * (2z*delta_jz - 2*z²*r_j/r²) / r²
        dc_i_dr_j = 5.0 * (2.0 * z * delta_jz - 2.0 * z2 * rj / r2) / r2

        # Additional: pre itself depends on r → ∂pre/∂r_j = -5*pre*r_j/r²
        dpre_dr_j = -5.0 * pre * rj / r2

        return pre * (delta_ij * c_i + ri * dc_i_dr_j) + dpre_dr_j * ri * c_i

    J2_grad = np.array([
        [da_dr(i, j) for j in range(3)]
        for i in range(3)
    ])

    A[3:6, 0:3] += J2_grad
    return A


# ---------------------------------------------------------------------------
# STM propagation
# ---------------------------------------------------------------------------

@dataclass
class STMResult:
    """Result of state transition matrix propagation.

    Attributes
    ----------
    stm : NDArray, shape (6, 6)
        State transition matrix Φ(t, t₀) mapping δx(t₀) → δx(t).
    state_final : NDArray, shape (6,)
        Final state [r(3); v(3)] [km, km/s].
    t_elapsed : float
        Propagation time [s].
    """

    stm: NDArray
    state_final: NDArray
    t_elapsed: float


def propagate_stm(
    r0: NDArray,
    v0: NDArray,
    dt_total: float,
    *,
    mu: float = MU_EARTH,
    include_j2: bool = False,
    j2: float = J2,
    r_earth: float = R_EARTH,
    n_steps: int | None = None,
) -> STMResult:
    """Propagate the state and state transition matrix from t₀ to t₀ + dt_total.

    Simultaneously integrates:
        1. The equations of motion: ẋ = f(x)
        2. The STM equation: Φ̇ = A(x) · Φ,  Φ(0) = I₆

    Uses a 4th-order Runge-Kutta integrator.

    Parameters
    ----------
    r0 : array-like, shape (3,)
        Initial position [km].
    v0 : array-like, shape (3,)
        Initial velocity [km/s].
    dt_total : float
        Propagation duration [s].
    mu : float
        Gravitational parameter [km^3/s^2].
    include_j2 : bool
        If True, include J2 perturbation in the dynamics and Jacobian.
    j2, r_earth : float
        J2 coefficient and Earth radius for perturbation.
    n_steps : int | None
        Number of RK4 integration steps.  Defaults to ceil(dt_total / 60).

    Returns
    -------
    STMResult

    Examples
    --------
    >>> import numpy as np
    >>> r0 = np.array([6778.0, 0.0, 0.0])
    >>> v0 = np.array([0.0, 7.784, 0.0])
    >>> res = propagate_stm(r0, v0, 3600.0)
    >>> res.stm.shape
    (6, 6)
    >>> abs(np.linalg.det(res.stm) - 1.0) < 0.01  # symplectic: det ≈ 1
    True
    """
    r0 = np.asarray(r0, dtype=float)
    v0 = np.asarray(v0, dtype=float)

    if n_steps is None:
        n_steps = max(int(math.ceil(abs(dt_total) / 60.0)), 10)

    h = dt_total / n_steps   # step size [s]

    # Augmented state: [x(6), Phi_flat(36)] = 42-vector
    # Phi stored row-major, flattened to 36 elements

    def _dynamics(state42: NDArray) -> NDArray:
        """RHS of augmented state equation."""
        x = state42[:6]
        phi = state42[6:].reshape(6, 6)

        r_vec = x[:3]
        v_vec = x[3:6]
        r_mag = float(np.linalg.norm(r_vec))

        # Equations of motion
        grav_acc = -mu / r_mag ** 3 * r_vec

        if include_j2:
            z = r_vec[2]
            zr_sq = (z / r_mag) ** 2
            pre = (3.0 / 2.0) * mu * j2 * r_earth ** 2 / r_mag ** 5
            j2_acc = pre * np.array([
                r_vec[0] * (5.0 * zr_sq - 1.0),
                r_vec[1] * (5.0 * zr_sq - 1.0),
                r_vec[2] * (5.0 * zr_sq - 3.0),
            ])
            acc = grav_acc + j2_acc
        else:
            acc = grav_acc

        xdot = np.concatenate([v_vec, acc])

        # Jacobian
        if include_j2:
            A = j2_jacobian(r_vec, mu, j2, r_earth)
        else:
            A = keplerian_jacobian(r_vec, mu)

        phi_dot = A @ phi

        return np.concatenate([xdot, phi_dot.flatten()])

    # Initial augmented state
    phi0 = np.eye(6)
    state42 = np.concatenate([np.concatenate([r0, v0]), phi0.flatten()])

    # RK4 integration
    for _ in range(n_steps):
        k1 = _dynamics(state42)
        k2 = _dynamics(state42 + 0.5 * h * k1)
        k3 = _dynamics(state42 + 0.5 * h * k2)
        k4 = _dynamics(state42 + h * k3)
        state42 = state42 + (h / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)

    final_state = state42[:6]
    stm = state42[6:].reshape(6, 6)

    return STMResult(
        stm=stm,
        state_final=final_state,
        t_elapsed=dt_total,
    )


# ---------------------------------------------------------------------------
# Covariance propagation
# ---------------------------------------------------------------------------

def propagate_covariance(
    p0: NDArray,
    stm: NDArray,
) -> NDArray:
    """Propagate a 6×6 state covariance matrix using the STM.

    P(t) = Φ(t, t₀) · P(t₀) · Φ(t, t₀)ᵀ

    Parameters
    ----------
    p0 : array-like, shape (6, 6)
        Initial state covariance matrix [km², km²/s², km²/s⁴ mixed].
    stm : array-like, shape (6, 6)
        State transition matrix Φ(t, t₀).

    Returns
    -------
    NDArray, shape (6, 6)
        Propagated covariance P(t).
    """
    p0 = np.asarray(p0, dtype=float)
    phi = np.asarray(stm, dtype=float)
    return phi @ p0 @ phi.T


def differential_correction(
    r0: NDArray,
    v0: NDArray,
    r_target: NDArray,
    tof: float,
    *,
    mu: float = MU_EARTH,
    n_steps: int | None = None,
) -> NDArray:
    """Compute the velocity correction at t₀ to reach r_target at t₀ + tof.

    Uses the position-velocity partition of the STM:

        δr(t) = Φ_rr · δr₀ + Φ_rv · δv₀

    With δr₀ = 0 (fixed departure position):

        δv₀ = Φ_rv⁻¹ · (r_target - r_prop)

    Parameters
    ----------
    r0 : array-like, shape (3,)
        Departure position [km].
    v0 : array-like, shape (3,)
        Initial guess velocity [km/s].
    r_target : array-like, shape (3,)
        Target arrival position [km].
    tof : float
        Time of flight [s].
    mu : float
        Gravitational parameter [km^3/s^2].
    n_steps : int | None
        RK4 integration steps.

    Returns
    -------
    NDArray, shape (3,)
        Corrected initial velocity [km/s] (v0 + δv₀).

    Raises
    ------
    np.linalg.LinAlgError
        If Φ_rv is singular (degenerate geometry).
    """
    r0 = np.asarray(r0, dtype=float)
    v0 = np.asarray(v0, dtype=float)
    r_tgt = np.asarray(r_target, dtype=float)

    result = propagate_stm(r0, v0, tof, mu=mu, n_steps=n_steps)
    r_final = result.state_final[:3]

    phi = result.stm
    phi_rv = phi[0:3, 3:6]   # position-velocity block

    dr = r_tgt - r_final
    dv0 = np.linalg.solve(phi_rv, dr)

    return v0 + dv0
