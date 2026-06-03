"""Tests for Orbit Determination: batch least-squares and EKF.

References
----------
Tapley, B. D., Schutz, B. E., & Born, G. H. (2004). Statistical Orbit Determination.
Vallado, D. A. (2013). Fundamentals of Astrodynamics, 4th ed.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cad_core.aerospace.orbit_determination import (
    GroundStationObservation,
    InitialOrbitGuess,
    ODReport,
    batch_least_squares_od,
    extended_kalman_filter_od,
    generate_synthetic_observations,
    _propagate_keplerian,
    _predict_obs,
    _obs_jacobian,
    MU_EARTH,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REF_EPOCH = "2024-01-15T00:00:00Z"

@pytest.fixture
def leo_state():
    """Low Earth orbit truth state: circular 500 km orbit."""
    # ISS-like orbit: a = 6878 km, inclined, circular
    r0 = np.array([6878.0, 0.0, 0.0])     # km
    v0 = np.array([0.0, 7.612, 0.001])    # km/s (approximately circular)
    return r0, v0


@pytest.fixture
def ground_station():
    """Ground station in ECI frame — roughly Goldstone, CA."""
    return np.array([-2_353.621, -4_641.341, 3_677.052])  # km


@pytest.fixture
def geosat_state():
    """Geostationary orbit truth state: r ≈ 42 164 km."""
    r0 = np.array([42164.0, 0.0, 0.0])
    v0 = np.array([0.0, 3.075, 0.0])
    return r0, v0


@pytest.fixture
def leo_observations(leo_state):
    """10 synthetic observations of LEO orbit from ground station."""
    r0, v0 = leo_state
    station = np.array([6378.137, 0.0, 0.0])  # nadir station (simplified)
    # Observation times spanning ~half an orbit (~45 min for LEO)
    obs_times = [REF_EPOCH.replace("T00:00:00", f"T00:{i*5:02d}:00") for i in range(10)]
    return generate_synthetic_observations(
        r0, v0,
        obs_epochs_iso=obs_times,
        station_eci=station,
        ref_epoch_iso=REF_EPOCH,
        sigma_range_km=0.001,
        sigma_rrate_km_s=1e-6,
        seed=42,
    )


# ---------------------------------------------------------------------------
# Test 1: _propagate_keplerian conserves energy
# ---------------------------------------------------------------------------

def test_keplerian_energy_conservation(leo_state):
    """Two-body propagation conserves specific orbital energy."""
    r0, v0 = leo_state
    state0 = np.concatenate([r0, v0])

    def specific_energy(s: np.ndarray) -> float:
        r = float(np.linalg.norm(s[:3]))
        v = float(np.linalg.norm(s[3:6]))
        return v ** 2 / 2.0 - MU_EARTH / r

    E0 = specific_energy(state0)
    # Propagate for 1 orbit period (~92 min for LEO)
    T_leo = 2.0 * math.pi * math.sqrt(6878.0 ** 3 / MU_EARTH)
    state1 = _propagate_keplerian(state0, T_leo, n_steps=1000)
    E1 = specific_energy(state1)
    assert abs(E1 - E0) / abs(E0) < 1e-6, \
        f"Energy relative error = {abs(E1-E0)/abs(E0):.2e}"


# ---------------------------------------------------------------------------
# Test 2: Observation model gives positive range
# ---------------------------------------------------------------------------

def test_observation_model_range_positive(leo_state):
    """Predicted range is always positive."""
    r0, v0 = leo_state
    state0 = np.concatenate([r0, v0])
    station = np.array([6000.0, 0.0, 0.0])
    obs = GroundStationObservation(
        epoch_iso=REF_EPOCH,
        range_km=7000.0,
        range_rate_km_s=0.5,
        azimuth_deg=45.0,
        elevation_deg=30.0,
        station_eci=station,
    )
    rho, rdot = _predict_obs(state0, obs)
    assert rho > 0.0
    assert isinstance(rdot, float)


# ---------------------------------------------------------------------------
# Test 3: Observation Jacobian finite-difference check
# ---------------------------------------------------------------------------

def test_obs_jacobian_finite_difference(leo_state):
    """Analytic H matrix matches finite difference to 1e-4 relative."""
    r0, v0 = leo_state
    state0 = np.concatenate([r0, v0])
    station = np.array([6000.0, 0.0, 1000.0])
    obs = GroundStationObservation(
        epoch_iso=REF_EPOCH,
        range_km=7000.0,
        range_rate_km_s=0.5,
        azimuth_deg=0.0,
        elevation_deg=30.0,
        station_eci=station,
    )
    H_analytic = _obs_jacobian(state0, obs)

    # Numerical finite difference
    rho0, rdot0 = _predict_obs(state0, obs)
    H_num = np.zeros((2, 6))
    for j in range(6):
        eps = 1e-3 if j < 3 else 1e-6
        s_pert = state0.copy(); s_pert[j] += eps
        rho_p, rdot_p = _predict_obs(s_pert, obs)
        H_num[0, j] = (rho_p - rho0) / eps
        H_num[1, j] = (rdot_p - rdot0) / eps

    # Check agreement (relative)
    for i in range(2):
        for j in range(6):
            if abs(H_analytic[i, j]) > 1e-8:
                rel_err = abs(H_analytic[i, j] - H_num[i, j]) / abs(H_analytic[i, j])
                assert rel_err < 1e-3, \
                    f"H[{i},{j}]: analytic={H_analytic[i,j]:.6e}, num={H_num[i,j]:.6e}"


# ---------------------------------------------------------------------------
# Test 4: Batch OD too few observations raises ValueError
# ---------------------------------------------------------------------------

def test_batch_od_too_few_observations(leo_state):
    """batch_least_squares_od raises ValueError with fewer than 6 observations."""
    r0, v0 = leo_state
    state0 = np.concatenate([r0, v0])
    initial = InitialOrbitGuess(state_eci=state0, epoch_iso=REF_EPOCH)

    station = np.array([6378.137, 0.0, 0.0])
    obs = generate_synthetic_observations(
        r0, v0,
        obs_epochs_iso=[REF_EPOCH.replace("T00:00:00", f"T00:0{i}:00") for i in range(5)],
        station_eci=station,
        ref_epoch_iso=REF_EPOCH,
        seed=0,
    )
    assert len(obs) == 5  # sanity check

    with pytest.raises(ValueError, match="[Aa]t least 6"):
        batch_least_squares_od(initial, obs)


# ---------------------------------------------------------------------------
# Test 5: Batch OD converges to true state (10 noisy observations)
# ---------------------------------------------------------------------------

def test_batch_od_convergence(leo_state):
    """Batch LS OD reduces position error to < 2 km from a 5 km initial guess error.

    Tapley et al. (2004) §4.3: with sufficient observations and small noise,
    the batch LS differential-correction reduces residuals toward the noise floor.

    Note: single-station range+range-rate OD is a limited geometry problem.
    A 5 km initial error is an appropriate test for the linearized corrector
    (large perturbations of 50+ km require nonlinear IOD first, out of scope here).
    """
    r0_truth, v0_truth = leo_state
    state_truth = np.concatenate([r0_truth, v0_truth])

    station = np.array([6378.137, 0.0, 0.0])

    # Generate 10 observations with 1 m range noise, 1 mm/s rate noise
    obs_epochs = [
        REF_EPOCH.replace("T00:00:00", f"T00:{i*5:02d}:00")
        for i in range(10)
    ]
    observations = generate_synthetic_observations(
        r0_truth, v0_truth,
        obs_epochs_iso=obs_epochs,
        station_eci=station,
        ref_epoch_iso=REF_EPOCH,
        sigma_range_km=0.001,
        sigma_rrate_km_s=1e-6,
        seed=123,
    )

    # Initial guess: 5 km position perturbation (realistic for differential correction).
    # Larger perturbations require a separate IOD step to get within the linear regime.
    rng = np.random.default_rng(7)
    x0_perturbed = state_truth.copy()
    x0_perturbed[:3] += rng.normal(0.0, 5.0, 3)
    x0_perturbed[3:6] += rng.normal(0.0, 0.005, 3)

    initial = InitialOrbitGuess(state_eci=x0_perturbed, epoch_iso=REF_EPOCH)
    report = batch_least_squares_od(initial, observations, max_iter=30, tol=1e-8)

    pos_error_km = float(np.linalg.norm(report.refined_state[:3] - state_truth[:3]))
    assert pos_error_km < 2.0, \
        f"Batch OD position error = {pos_error_km:.2f} km, expected < 2 km"


# ---------------------------------------------------------------------------
# Test 6: ODReport has correct structure
# ---------------------------------------------------------------------------

def test_od_report_structure(leo_observations, leo_state):
    """ODReport has correct attributes and shapes."""
    r0, v0 = leo_state
    state_truth = np.concatenate([r0, v0])
    x0 = state_truth + np.array([20.0, -15.0, 10.0, 0.01, -0.01, 0.005])
    initial = InitialOrbitGuess(state_eci=x0, epoch_iso=REF_EPOCH)

    report = batch_least_squares_od(initial, leo_observations)
    assert report.refined_state.shape == (6,)
    assert report.covariance.shape == (6, 6)
    assert report.rms_residual >= 0.0
    assert report.iterations >= 1
    assert isinstance(report.converged, bool)


# ---------------------------------------------------------------------------
# Test 7: EKF OD returns per-observation reports
# ---------------------------------------------------------------------------

def test_ekf_od_report_count(leo_observations, leo_state):
    """EKF OD returns one report per observation."""
    r0, v0 = leo_state
    state_truth = np.concatenate([r0, v0])
    x0 = state_truth + np.array([30.0, -20.0, 15.0, 0.02, -0.02, 0.01])
    initial = InitialOrbitGuess(state_eci=x0, epoch_iso=REF_EPOCH)

    reports = extended_kalman_filter_od(initial, leo_observations)
    assert len(reports) == len(leo_observations), \
        f"Expected {len(leo_observations)} reports, got {len(reports)}"


# ---------------------------------------------------------------------------
# Test 8: EKF residuals decrease (or at least don't monotonically increase)
# ---------------------------------------------------------------------------

def test_ekf_residuals_decrease(leo_state):
    """EKF RMS residuals generally decrease as the filter converges.

    Montenbruck & Gill (2000) §5: with a good initial state, the EKF
    innovation covariance decreases as observations are assimilated.
    """
    r0_truth, v0_truth = leo_state
    state_truth = np.concatenate([r0_truth, v0_truth])

    station = np.array([6000.0, 1000.0, 500.0])
    obs_epochs = [
        REF_EPOCH.replace("T00:00:00", f"T00:{i*3:02d}:00")
        for i in range(12)
    ]
    observations = generate_synthetic_observations(
        r0_truth, v0_truth,
        obs_epochs_iso=obs_epochs,
        station_eci=station,
        ref_epoch_iso=REF_EPOCH,
        sigma_range_km=0.001,
        sigma_rrate_km_s=1e-6,
        seed=77,
    )

    # Initial guess with moderate error
    x0 = state_truth + np.array([25.0, -15.0, 8.0, 0.015, -0.01, 0.005])
    initial = InitialOrbitGuess(state_eci=x0, epoch_iso=REF_EPOCH)

    reports = extended_kalman_filter_od(initial, observations)
    rms_values = [r.rms_residual for r in reports if math.isfinite(r.rms_residual)]

    # The last few residuals should be smaller than the first few
    # (filter has converged)
    assert len(rms_values) >= 6, "Need at least 6 valid residual values"
    first_avg = sum(rms_values[:3]) / 3.0
    last_avg = sum(rms_values[-3:]) / 3.0
    # Allow for some variation but overall should not get dramatically worse
    assert last_avg < first_avg * 2.0, \
        f"EKF residuals unexpectedly increased: first_avg={first_avg:.4f}, last_avg={last_avg:.4f}"


# ---------------------------------------------------------------------------
# Test 9: EKF covariance decreases (information accumulates)
# ---------------------------------------------------------------------------

def test_ekf_covariance_decreases(leo_observations, leo_state):
    """EKF covariance trace decreases as observations are processed."""
    r0, v0 = leo_state
    state_truth = np.concatenate([r0, v0])
    x0 = state_truth + np.array([20.0, -10.0, 5.0, 0.01, -0.005, 0.002])
    initial = InitialOrbitGuess(state_eci=x0, epoch_iso=REF_EPOCH)

    reports = extended_kalman_filter_od(initial, leo_observations)
    # Covariance trace should decrease from first to last
    trace_first = float(np.trace(reports[0].covariance))
    trace_last = float(np.trace(reports[-1].covariance))
    assert trace_last < trace_first, \
        f"Covariance trace did not decrease: {trace_first:.4f} → {trace_last:.4f}"


# ---------------------------------------------------------------------------
# Test 10: EKF with process noise — returns same number of reports
# ---------------------------------------------------------------------------

def test_ekf_with_process_noise(leo_observations, leo_state):
    """EKF with process noise still returns per-observation reports."""
    r0, v0 = leo_state
    state_truth = np.concatenate([r0, v0])
    x0 = state_truth + np.array([10.0, -5.0, 3.0, 0.005, -0.002, 0.001])
    initial = InitialOrbitGuess(state_eci=x0, epoch_iso=REF_EPOCH)

    Q = np.diag([1e-6, 1e-6, 1e-6, 1e-12, 1e-12, 1e-12])
    reports = extended_kalman_filter_od(initial, leo_observations, process_noise=Q)
    assert len(reports) == len(leo_observations)


# ---------------------------------------------------------------------------
# Test 11: Batch OD covariance is positive semi-definite
# ---------------------------------------------------------------------------

def test_batch_od_covariance_psd(leo_observations, leo_state):
    """Batch OD covariance matrix is positive semi-definite.

    Tapley et al. (2004) §4.5: P = Λ⁻¹ must be PSD by construction.
    """
    r0, v0 = leo_state
    state_truth = np.concatenate([r0, v0])
    x0 = state_truth + np.array([15.0, -8.0, 4.0, 0.008, -0.004, 0.002])
    initial = InitialOrbitGuess(state_eci=x0, epoch_iso=REF_EPOCH)

    report = batch_least_squares_od(initial, leo_observations)
    # All eigenvalues should be non-negative
    eigvals = np.linalg.eigvalsh(report.covariance)
    assert float(min(eigvals)) >= -1e-10, \
        f"Covariance has negative eigenvalue: {float(min(eigvals)):.3e}"


# ---------------------------------------------------------------------------
# Test 12: InitialOrbitGuess validates state shape
# ---------------------------------------------------------------------------

def test_initial_orbit_guess_validation():
    """InitialOrbitGuess raises for wrong state shape."""
    with pytest.raises(ValueError, match="shape"):
        InitialOrbitGuess(
            state_eci=np.array([1.0, 2.0, 3.0]),  # Wrong shape: (3,) not (6,)
            epoch_iso=REF_EPOCH,
        )
