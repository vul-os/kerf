"""Orbit Determination: Batch Least-Squares and Extended Kalman Filter.

Implements two classical orbit determination algorithms for estimating a
spacecraft's state (position + velocity) from ground-station observations
(range, range-rate, azimuth, elevation).

DISCLAIMER: Simplified implementation for design exploration — not GMAT-validated.
The dynamics model is Keplerian only (no J2, no drag, no SRP). Suitable for
preliminary mission analysis and educational use.

Algorithm References
--------------------
Tapley, B. D., Schutz, B. E., & Born, G. H. (2004). *Statistical Orbit
    Determination*. Elsevier. §4.3 (batch LS), §4.5 (covariance), §5.3 (EKF).
Vallado, D. A. (2013). *Fundamentals of Astrodynamics and Applications*,
    4th ed. Microcosm/Springer. Ch. 7 (OD methods).
Montenbruck, O., & Gill, E. (2000). *Satellite Orbits*. Springer. §5 (filter).
Gelb, A. (1974). *Applied Optimal Estimation*. MIT Press. (EKF derivation.)

Author: kerf aero depth (Wave 10C)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from numpy.typing import NDArray


# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

#: Earth gravitational parameter μ [km³/s²] (JGM-3)
MU_EARTH: float = 398_600.4418

#: Earth equatorial radius [km] (WGS-84)
R_EARTH_KM: float = 6_378.137


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GroundStationObservation:
    """Single ground-station observation of a spacecraft.

    Attributes
    ----------
    epoch_iso : str
        ISO-8601 epoch string, e.g. '2024-01-15T12:00:00Z'.
    range_km : float
        Two-way range ρ [km].
    range_rate_km_s : float
        Range-rate ρ̇ [km/s].  Positive = moving away.
    azimuth_deg : float
        Azimuth [degrees, 0=North, 90=East].
    elevation_deg : float
        Elevation above horizon [degrees].
    station_eci : NDArray, shape (3,)
        Ground station ECI position [km] at observation epoch.
    station_vel_eci : NDArray, shape (3,)
        Ground station ECI velocity [km/s].  Defaults to zero.
    sigma_range_km : float
        1-sigma range noise [km].  Default 0.001 km = 1 m.
    sigma_range_rate_km_s : float
        1-sigma range-rate noise [km/s].  Default 1e-6 km/s = 1 mm/s.
    """

    epoch_iso: str
    range_km: float
    range_rate_km_s: float
    azimuth_deg: float
    elevation_deg: float
    station_eci: NDArray
    station_vel_eci: NDArray = field(default_factory=lambda: np.zeros(3))
    sigma_range_km: float = 0.001
    sigma_range_rate_km_s: float = 1e-6

    def __post_init__(self) -> None:
        self.station_eci = np.asarray(self.station_eci, dtype=float)
        self.station_vel_eci = np.asarray(self.station_vel_eci, dtype=float)

    def epoch_seconds(self, ref_iso: str) -> float:
        """Compute seconds since reference epoch."""
        t_obs = _parse_iso(self.epoch_iso)
        t_ref = _parse_iso(ref_iso)
        return (t_obs - t_ref).total_seconds()


@dataclass
class InitialOrbitGuess:
    """Initial state estimate for orbit determination.

    Attributes
    ----------
    state_eci : NDArray, shape (6,)
        Best-guess state [x, y, z, vx, vy, vz] in ECI [km, km/s].
    epoch_iso : str
        ISO-8601 epoch of the state.
    """

    state_eci: NDArray
    epoch_iso: str

    def __post_init__(self) -> None:
        self.state_eci = np.asarray(self.state_eci, dtype=float)
        if self.state_eci.shape != (6,):
            raise ValueError(
                f"state_eci must have shape (6,); got {self.state_eci.shape}"
            )


@dataclass
class ODReport:
    """Orbit determination result.

    Attributes
    ----------
    refined_state : NDArray, shape (6,)
        Corrected state [x, y, z, vx, vy, vz] in ECI [km, km/s].
    covariance : NDArray, shape (6, 6)
        State covariance P [km², km·km/s, km²/s²].
    rms_residual : float
        RMS of weighted (normalised) post-fit residuals.  Near 1 → noise-consistent.
    iterations : int
        Number of iterations used.
    converged : bool
        Whether the solution converged within tolerance.
    """

    refined_state: NDArray
    covariance: NDArray
    rms_residual: float
    iterations: int
    converged: bool


# ---------------------------------------------------------------------------
# Time helper
# ---------------------------------------------------------------------------

def _parse_iso(epoch_iso: str) -> datetime:
    """Parse ISO-8601 epoch string to datetime (UTC)."""
    s = epoch_iso.strip()
    # Support trailing 'Z' and '+00:00'
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # Python 3.10 fallback: strip timezone manually
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                return datetime.strptime(s.replace("+00:00", ""), fmt).replace(
                    tzinfo=timezone.utc
                )
            except ValueError:
                continue
    raise ValueError(f"Cannot parse epoch_iso: {epoch_iso!r}")


# ---------------------------------------------------------------------------
# Keplerian propagator (two-body, pure Python + numpy, no scipy)
# ---------------------------------------------------------------------------

def _keplerian_rk4_step(state: NDArray, dt: float, mu: float = MU_EARTH) -> NDArray:
    """RK4 step for two-body Keplerian equation of motion.

    ẍ = -μ r / |r|³

    Parameters
    ----------
    state : NDArray, shape (6,)
        [x, y, z, vx, vy, vz] in ECI [km, km/s].
    dt : float
        Time step [s].
    mu : float
        Gravitational parameter [km³/s²].

    Returns
    -------
    NDArray, shape (6,)
    """
    def _accel(s: NDArray) -> NDArray:
        r = s[:3]
        v = s[3:6]
        r3 = float(np.dot(r, r)) ** 1.5
        if r3 < 1e-12:
            r3 = 1e-12
        a = -mu / r3 * r
        return np.concatenate([v, a])

    k1 = _accel(state)
    k2 = _accel(state + 0.5 * dt * k1)
    k3 = _accel(state + 0.5 * dt * k2)
    k4 = _accel(state + dt * k3)
    return state + (dt / 6.0) * (k1 + 2.0 * k2 + 2.0 * k3 + k4)


def _propagate_keplerian(
    state0: NDArray,
    dt: float,
    mu: float = MU_EARTH,
    n_steps: int = 100,
) -> NDArray:
    """Propagate two-body state over dt seconds using RK4.

    Parameters
    ----------
    state0 : NDArray, shape (6,)
    dt : float
        Total propagation time [s]. Can be negative.
    mu : float
    n_steps : int
        RK4 steps. More steps = higher accuracy but slower.

    Returns
    -------
    NDArray, shape (6,)
    """
    if abs(dt) < 1e-10:
        return state0.copy()
    step = dt / n_steps
    s = state0.copy()
    for _ in range(n_steps):
        s = _keplerian_rk4_step(s, step, mu)
    return s


# ---------------------------------------------------------------------------
# State transition matrix (STM) via numerical differentiation
# ---------------------------------------------------------------------------

def _compute_stm_numerical(
    state0: NDArray,
    dt: float,
    mu: float = MU_EARTH,
    eps: float = 0.1,  # km or km/s perturbation
) -> NDArray:
    """Numerically compute the 6×6 state transition matrix Φ(t+dt, t).

    Φ_ij ≈ [x_final(x0 + eps*e_j) - x_final(x0)] / eps

    This is a first-order finite-difference approximation.
    More accurate than analytic Keplerian STM for perturbed orbits
    but roughly equivalent for pure two-body.

    References: Tapley et al. (2004) §3.2, Vallado (2013) §7.4.
    """
    x_ref = _propagate_keplerian(state0, dt, mu)
    phi = np.zeros((6, 6))
    for j in range(6):
        eps_j = eps if j < 3 else eps * 1e-3  # smaller perturbation for velocity
        state_pert = state0.copy()
        state_pert[j] += eps_j
        x_pert = _propagate_keplerian(state_pert, dt, mu)
        phi[:, j] = (x_pert - x_ref) / eps_j
    return phi


# ---------------------------------------------------------------------------
# Observation model
# ---------------------------------------------------------------------------

def _predict_obs(state: NDArray, obs: GroundStationObservation) -> tuple[float, float]:
    """Compute predicted range and range-rate from spacecraft state.

    Parameters
    ----------
    state : NDArray, shape (6,)
        Spacecraft ECI state at observation epoch.
    obs : GroundStationObservation

    Returns
    -------
    rho : float — predicted range [km]
    rho_dot : float — predicted range-rate [km/s]
    """
    r_sc = state[:3]
    v_sc = state[3:6]
    r_gs = obs.station_eci
    v_gs = obs.station_vel_eci

    rho_vec = r_sc - r_gs
    rho = float(np.linalg.norm(rho_vec))
    if rho < 1e-8:
        rho = 1e-8
    rho_hat = rho_vec / rho
    rho_dot = float(np.dot(rho_hat, v_sc - v_gs))
    return rho, rho_dot


def _obs_jacobian(state: NDArray, obs: GroundStationObservation) -> NDArray:
    """Compute H = ∂[ρ, ρ̇]/∂[x, y, z, vx, vy, vz] (2×6 matrix).

    Analytic partials (Tapley et al. 2004, eq. 4.2.4–4.2.5):

    ∂ρ/∂r  = ρ̂            ∂ρ/∂v  = 0
    ∂ρ̇/∂r  = (v−v_gs)/ρ − (ρ̇/ρ) ρ̂
    ∂ρ̇/∂v  = ρ̂
    """
    r_sc = state[:3]
    v_sc = state[3:6]
    r_gs = obs.station_eci
    v_gs = obs.station_vel_eci

    rho_vec = r_sc - r_gs
    rho = float(np.linalg.norm(rho_vec))
    if rho < 1e-8:
        rho = 1e-8
    rho_hat = rho_vec / rho
    dv = v_sc - v_gs
    rho_dot = float(np.dot(rho_hat, dv))

    H = np.zeros((2, 6))
    # ∂ρ/∂x
    H[0, :3] = rho_hat
    # ∂ρ̇/∂x, ∂ρ̇/∂v
    H[1, :3] = dv / rho - (rho_dot / rho) * rho_hat
    H[1, 3:6] = rho_hat
    return H


# ---------------------------------------------------------------------------
# Batch Least-Squares OD (Tapley-Schutz-Born 2004)
# ---------------------------------------------------------------------------

def batch_least_squares_od(
    initial: InitialOrbitGuess,
    observations: list[GroundStationObservation],
    max_iter: int = 10,
    tol: float = 1e-6,
    mu: float = MU_EARTH,
) -> ODReport:
    """Batch least-squares orbit determination.

    Implements the differential-correction / weighted-least-squares OD
    algorithm (Tapley, Schutz & Born 2004, §4.3; Vallado 2013, §7.6):

    Each iteration:
      1. Propagate reference state X̄_0 to each observation epoch.
      2. Compute predicted observations ŷ_i = h(X̄(t_i)).
      3. Compute residuals: Δy_i = y_i − ŷ_i.
      4. Compute H_i (2×6 measurement Jacobian) at t_i.
      5. Map to epoch via STM: H̃_i = H_i Φ(t_i, t₀).
      6. Accumulate normal equations: Λ += H̃ᵀ W H̃, b += H̃ᵀ W Δy.
      7. Solve: δX₀ = Λ⁻¹ b.
      8. Update: X̄_0 ← X̄_0 + δX₀.
      9. Converge when ‖δX₀[0:3]‖ < tol [km].

    Covariance: P = Λ⁻¹ (information form, Tapley §4.5).

    Parameters
    ----------
    initial : InitialOrbitGuess
        A priori state and epoch.
    observations : list[GroundStationObservation]
        Observations sorted by epoch (ascending time).  Must have ≥ 6.
    max_iter : int
        Maximum iterations.
    tol : float
        Position convergence tolerance [km].
    mu : float
        Earth gravitational parameter [km³/s²].

    Returns
    -------
    ODReport

    Raises
    ------
    ValueError
        If fewer than 6 observations are provided (under-determined system)
        or if inputs are invalid.

    References
    ----------
    Tapley, Schutz & Born (2004). *Statistical Orbit Determination*. §4.3, §4.5.
    Vallado (2013). *Fundamentals of Astrodynamics*, 4th ed. §7.6.
    """
    if len(observations) < 6:
        raise ValueError(
            f"Batch OD requires at least 6 observations for a determined system "
            f"(6 state components); got {len(observations)}. "
            "Each observation provides 2 scalar measurements (range + range-rate)."
        )

    obs_sorted = sorted(observations, key=lambda o: _parse_iso(o.epoch_iso))
    ref_epoch = initial.epoch_iso

    x0 = initial.state_eci.copy()
    converged = False
    n_iter = 0
    Lambda_inv = np.eye(6)  # will be overwritten in first iteration

    for n_iter in range(1, max_iter + 1):
        Lambda = np.zeros((6, 6))
        b_vec = np.zeros(6)

        for obs in obs_sorted:
            t_i = obs.epoch_seconds(ref_epoch)
            # Propagate reference state to t_i
            x_ti = _propagate_keplerian(x0, t_i, mu)
            # STM from epoch to t_i
            phi_i = _compute_stm_numerical(x0, t_i, mu)

            # Predicted observations
            rho_pred, rdot_pred = _predict_obs(x_ti, obs)
            dy = np.array([obs.range_km - rho_pred,
                           obs.range_rate_km_s - rdot_pred])

            # Measurement Jacobian at t_i
            H_i = _obs_jacobian(x_ti, obs)

            # Map to epoch
            H_tilde = H_i @ phi_i  # (2, 6)

            # Weight matrix W = diag(1/σ²)
            w = np.array([
                1.0 / obs.sigma_range_km ** 2,
                1.0 / obs.sigma_range_rate_km_s ** 2,
            ])

            for k in range(2):
                h_k = H_tilde[k]
                Lambda += w[k] * np.outer(h_k, h_k)
                b_vec += w[k] * h_k * dy[k]

        # Symmetrize and solve via pseudo-inverse (Tapley §4.3.3)
        Lambda = 0.5 * (Lambda + Lambda.T)
        eigvals, eigvecs = np.linalg.eigh(Lambda)
        # Clip small/negative eigenvalues (unobservable subspace)
        inv_eigvals = np.where(eigvals > 1e-14 * eigvals.max(), 1.0 / eigvals, 0.0)
        Lambda_inv = eigvecs @ np.diag(inv_eigvals) @ eigvecs.T

        dx = Lambda_inv @ b_vec

        # Step limiter: cap at 5 km/iter for position, 0.005 km/s for velocity.
        # Tapley (2004) §4.3: differential-correction is a linearized iteration;
        # large steps leave the valid linear regime and cause divergence.
        # With small steps and sufficient iterations, the algorithm converges
        # from initial errors up to ~20–30 km (single-station geometry).
        pos_step_raw = float(np.linalg.norm(dx[:3]))
        vel_step_raw = float(np.linalg.norm(dx[3:6]))
        if pos_step_raw > 5.0:
            dx[:3] *= 5.0 / pos_step_raw
        if vel_step_raw > 0.005:
            dx[3:6] *= 0.005 / vel_step_raw

        x0 = x0 + dx

        # Converge when the *uncapped* Newton step is small (true convergence criterion)
        if pos_step_raw < tol:
            converged = True
            break

    # Post-fit residuals and RMS
    chi2 = 0.0
    n_obs_total = 0
    for obs in obs_sorted:
        t_i = obs.epoch_seconds(ref_epoch)
        x_ti = _propagate_keplerian(x0, t_i, mu)
        rho_p, rdot_p = _predict_obs(x_ti, obs)
        res_rho = (obs.range_km - rho_p) / obs.sigma_range_km
        res_rdot = (obs.range_rate_km_s - rdot_p) / obs.sigma_range_rate_km_s
        chi2 += res_rho ** 2 + res_rdot ** 2
        n_obs_total += 2

    rms = math.sqrt(chi2 / n_obs_total) if n_obs_total > 0 else 0.0

    # Formal covariance P = Λ⁻¹ (Tapley §4.5)
    cov = Lambda_inv.copy()
    cov = 0.5 * (cov + cov.T)

    return ODReport(
        refined_state=x0,
        covariance=cov,
        rms_residual=rms,
        iterations=n_iter,
        converged=converged,
    )


# ---------------------------------------------------------------------------
# Extended Kalman Filter OD (Tapley-Schutz-Born 2004, §5.3)
# ---------------------------------------------------------------------------

def extended_kalman_filter_od(
    initial: InitialOrbitGuess,
    observations: list[GroundStationObservation],
    process_noise: Optional[NDArray] = None,
    mu: float = MU_EARTH,
) -> list[ODReport]:
    """Extended Kalman Filter orbit determination (sequential).

    Implements the predict–update EKF for spacecraft OD:

    Predict step (Tapley et al. 2004, §5.3):
      X̄_k|k-1 = f(X̂_k-1, Δt)          [propagate mean state via RK4]
      P_k|k-1  = Φ P_k-1 Φᵀ + Q         [propagate covariance via STM]

    Update step:
      K_k = P_k|k-1 Hᵀ (H P_k|k-1 Hᵀ + R)⁻¹   [Kalman gain]
      X̂_k = X̄_k|k-1 + K_k (y_k − h(X̄_k|k-1))  [state update]
      P_k = (I − K_k H) P_k|k-1                  [covariance update]

    Parameters
    ----------
    initial : InitialOrbitGuess
        Initial state estimate and epoch.
    observations : list[GroundStationObservation]
        Observations in ascending time order.
    process_noise : NDArray, shape (6, 6) or None
        Process noise covariance Q.  None → Q = 0 (no process noise).
        Typical: small diagonal for position/velocity drift.
    mu : float
        Gravitational parameter.

    Returns
    -------
    list[ODReport]
        One ODReport per observation (state + covariance after each update).

    References
    ----------
    Tapley, Schutz & Born (2004). §5.3 *Extended Kalman Filter*.
    Gelb (1974). *Applied Optimal Estimation*. MIT Press.
    Montenbruck & Gill (2000). *Satellite Orbits*. §5.
    """
    obs_sorted = sorted(observations, key=lambda o: _parse_iso(o.epoch_iso))
    ref_epoch = initial.epoch_iso

    if process_noise is None:
        Q = np.zeros((6, 6))
    else:
        Q = np.asarray(process_noise, dtype=float)
        if Q.shape != (6, 6):
            raise ValueError(f"process_noise must be shape (6, 6); got {Q.shape}")

    # Initial state and covariance
    x = initial.state_eci.copy()
    # Initialize covariance from a reasonable prior
    P = np.diag([100.0, 100.0, 100.0, 1e-4, 1e-4, 1e-4])  # [km², km²/s²]

    reports: list[ODReport] = []
    t_prev = 0.0

    for obs_idx, obs in enumerate(obs_sorted):
        t_i = obs.epoch_seconds(ref_epoch)
        dt = t_i - t_prev

        # ── Predict ────────────────────────────────────────────────────────
        if abs(dt) > 1e-10:
            x_bar = _propagate_keplerian(x, dt, mu)
            phi = _compute_stm_numerical(x, dt, mu)
            P_bar = phi @ P @ phi.T + Q
        else:
            x_bar = x.copy()
            P_bar = P.copy()

        # ── Update ─────────────────────────────────────────────────────────
        rho_pred, rdot_pred = _predict_obs(x_bar, obs)
        y_obs = np.array([obs.range_km, obs.range_rate_km_s])
        y_pred = np.array([rho_pred, rdot_pred])
        innov = y_obs - y_pred

        H = _obs_jacobian(x_bar, obs)  # (2, 6)

        # Measurement noise covariance R (2×2)
        R = np.diag([obs.sigma_range_km ** 2, obs.sigma_range_rate_km_s ** 2])

        # Innovation covariance S = H P H^T + R
        S = H @ P_bar @ H.T + R

        # Kalman gain K = P H^T S^{-1}
        try:
            S_inv = _invert_2x2(S)
        except ValueError:
            # If S is singular, skip this observation (degenerate geometry)
            reports.append(ODReport(
                refined_state=x_bar.copy(),
                covariance=P_bar.copy(),
                rms_residual=float("inf"),
                iterations=obs_idx + 1,
                converged=False,
            ))
            x = x_bar
            P = P_bar
            t_prev = t_i
            continue

        K = P_bar @ H.T @ S_inv  # (6, 2)

        x_hat = x_bar + K @ innov
        # Joseph form covariance update (Tapley §5.3 — numerically stable)
        I_KH = np.eye(6) - K @ H
        P_hat = I_KH @ P_bar @ I_KH.T + K @ R @ K.T

        # Symmetrize to prevent drift
        P_hat = 0.5 * (P_hat + P_hat.T)

        # RMS of normalised innovation for this step
        innov_norm_sq = float(
            (innov[0] / obs.sigma_range_km) ** 2
            + (innov[1] / obs.sigma_range_rate_km_s) ** 2
        )
        rms_step = math.sqrt(innov_norm_sq / 2.0)

        reports.append(ODReport(
            refined_state=x_hat.copy(),
            covariance=P_hat.copy(),
            rms_residual=rms_step,
            iterations=obs_idx + 1,
            converged=True,
        ))

        x = x_hat
        P = P_hat
        t_prev = t_i

    return reports


def _invert_2x2(M: NDArray) -> NDArray:
    """Invert a 2×2 matrix analytically."""
    det = M[0, 0] * M[1, 1] - M[0, 1] * M[1, 0]
    if abs(det) < 1e-30:
        raise ValueError(f"2×2 matrix is singular (det={det:.3e})")
    return np.array([[M[1, 1], -M[0, 1]],
                     [-M[1, 0], M[0, 0]]]) / det


# ---------------------------------------------------------------------------
# Utility: generate synthetic observations from a truth orbit
# ---------------------------------------------------------------------------

def generate_synthetic_observations(
    r0_truth: NDArray,
    v0_truth: NDArray,
    obs_epochs_iso: list[str],
    station_eci: NDArray,
    ref_epoch_iso: str,
    sigma_range_km: float = 0.001,
    sigma_rrate_km_s: float = 1e-6,
    seed: Optional[int] = None,
    mu: float = MU_EARTH,
) -> list[GroundStationObservation]:
    """Generate synthetic ground-station observations from a truth orbit.

    Propagates the truth orbit and adds Gaussian noise.

    Parameters
    ----------
    r0_truth, v0_truth : NDArray
        True initial state at ref_epoch_iso.
    obs_epochs_iso : list of str
        Observation epoch strings (ISO-8601).
    station_eci : NDArray, shape (3,)
        Ground station ECI position [km].
    ref_epoch_iso : str
        Reference epoch (aligns with r0_truth, v0_truth).
    sigma_range_km : float
        Range noise 1-sigma [km].
    sigma_rrate_km_s : float
        Range-rate noise 1-sigma [km/s].
    seed : int or None
        RNG seed for reproducibility.
    mu : float
        Gravitational parameter.

    Returns
    -------
    list[GroundStationObservation]
        Sorted by epoch.
    """
    rng = np.random.default_rng(seed)
    r_gs = np.asarray(station_eci, dtype=float)
    x0 = np.concatenate([
        np.asarray(r0_truth, dtype=float),
        np.asarray(v0_truth, dtype=float),
    ])

    obs_list = []
    for epoch_iso in sorted(obs_epochs_iso, key=_parse_iso):
        dt_i = (_parse_iso(epoch_iso) - _parse_iso(ref_epoch_iso)).total_seconds()
        x_i = _propagate_keplerian(x0, dt_i, mu)

        # True range + range-rate
        rho_vec = x_i[:3] - r_gs
        rho_true = float(np.linalg.norm(rho_vec))
        if rho_true < 1e-8:
            rho_true = 1e-8
        rho_hat = rho_vec / rho_true
        rdot_true = float(np.dot(rho_hat, x_i[3:6]))

        # Noisy observations
        rho_obs = rho_true + rng.normal(0.0, sigma_range_km)
        rdot_obs = rdot_true + rng.normal(0.0, sigma_rrate_km_s)

        # Azimuth and elevation (simple topocentric, fixed frame)
        # r_topo = spacecraft position relative to station
        r_topo = x_i[:3] - r_gs
        # Simple approximation: azimuth from atan2 of Y/X components in topocentric
        az_rad = math.atan2(r_topo[1], r_topo[0])
        el_rad = math.asin(
            max(-1.0, min(1.0, r_topo[2] / max(float(np.linalg.norm(r_topo)), 1e-8)))
        )

        obs_list.append(GroundStationObservation(
            epoch_iso=epoch_iso,
            range_km=rho_obs,
            range_rate_km_s=rdot_obs,
            azimuth_deg=math.degrees(az_rad),
            elevation_deg=math.degrees(el_rad),
            station_eci=r_gs.copy(),
            station_vel_eci=np.zeros(3),
            sigma_range_km=sigma_range_km,
            sigma_range_rate_km_s=sigma_rrate_km_s,
        ))

    return obs_list
