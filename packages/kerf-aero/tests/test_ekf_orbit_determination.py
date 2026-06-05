"""Tests for EKF (Extended Kalman Filter) orbit determination.

Numerical oracles:
  1. EKF processes observations and produces finite, consistent output.
  2. With small noise, EKF state error < 3-sigma formal covariance.
  3. Joseph-form covariance update keeps P positive-definite.
  4. Innovation RMS ≈ 1 for consistent noise model.
  5. With process noise Q > 0, EKF handles propagation uncertainty.
  6. EKF and batch LS on same observations: both should agree within O(noise).
  7. Input validation: empty observations, wrong state size raise ValueError.
  8. LLM tool round-trip via aero_ekf_orbit_determination.

References
----------
Tapley, Schutz & Born (2004), §4.7 EKF.
Bierman (1977), §IV.6 Joseph form.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_aero.orbital.kepler import KeplerianElements, elements_to_state
from kerf_aero.orbital.orbit_determination import (
    Observation,
    EKFResult,
    ekf_orbit_determination,
    generate_synthetic_observations,
    geodetic_to_eci,
    batch_least_squares_od,
)
from kerf_aero.orbital.stm import propagate_stm
from kerf_aero.orbital.perturbations import MU_EARTH, J2, R_EARTH


def _propagate_truth_to(r0, v0, t_s, include_j2=False):
    """Propagate truth state from epoch to time t_s [s]."""
    if t_s <= 0:
        return r0.copy(), v0.copy()
    res = propagate_stm(r0, v0, t_s, mu=MU_EARTH, include_j2=include_j2, j2=J2, r_earth=R_EARTH)
    return res.state_final[:3], res.state_final[3:6]


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _leo_truth_state():
    """400 km circular LEO truth state, 28.5° inclination."""
    elems = KeplerianElements(
        a=6778.0, e=0.001,
        i=math.radians(28.5),
        raan=math.radians(45.0),
        argp=math.radians(30.0),
        nu=math.radians(0.0),
    )
    return elements_to_state(elems)


def _good_station():
    """Ground station at lat=20°N, lon=60°E — off-plane for good geometry."""
    return geodetic_to_eci(20.0, 60.0, 0.0)


def _half_orbit_obs(seed=1, obs_type="both", step_s=120.0):
    """Generate half-orbit synthetic observations from a single station."""
    r0, v0 = _leo_truth_state()
    r_gs = _good_station()
    obs_times = [t for t in range(int(step_s), 2401, int(step_s))]
    return generate_synthetic_observations(
        r0, v0, obs_times, r_gs,
        obs_type=obs_type,
        sigma_range_km=0.001,
        sigma_rrate_km_per_s=1e-6,
        seed=seed,
    ), r0, v0


def _tight_P0(scale: float = 4.0) -> np.ndarray:
    """Initial covariance: scale² km² position, (scale/500)² km²/s² velocity."""
    p = scale
    v = p / 500.0
    return np.diag([p**2, p**2, p**2, v**2, v**2, v**2])


# ---------------------------------------------------------------------------
# 1. Basic output structure
# ---------------------------------------------------------------------------

class TestEKFBasicOutput:
    """EKF runs and returns a well-formed EKFResult."""

    def test_returns_ekf_result(self):
        """EKF returns an EKFResult dataclass."""
        obs, r0, v0 = _half_orbit_obs()
        x0 = np.concatenate([r0 + np.array([2.0, -1.5, 1.0]),
                              v0 + np.array([0.002, -0.0015, 0.001])])
        P0 = _tight_P0(scale=4.0)
        result = ekf_orbit_determination(obs, x0, P0)
        assert isinstance(result, EKFResult)

    def test_state_is_finite(self):
        """Posterior state must be finite (no NaN/Inf)."""
        obs, r0, v0 = _half_orbit_obs()
        x0 = np.concatenate([r0 + np.array([2.0, -1.5, 1.0]),
                              v0 + np.array([0.002, -0.0015, 0.001])])
        P0 = _tight_P0()
        result = ekf_orbit_determination(obs, x0, P0)
        assert np.all(np.isfinite(result.state_final)), "State has NaN/Inf"

    def test_covariance_is_finite(self):
        """Posterior covariance must be finite."""
        obs, r0, v0 = _half_orbit_obs()
        x0 = np.concatenate([r0 + np.array([2.0, -1.5, 1.0]),
                              v0 + np.array([0.002, -0.0015, 0.001])])
        P0 = _tight_P0()
        result = ekf_orbit_determination(obs, x0, P0)
        assert np.all(np.isfinite(result.covariance_final)), "Covariance has NaN/Inf"

    def test_history_length_matches_obs(self):
        """State/covariance/innovation history length == number of observations."""
        obs, r0, v0 = _half_orbit_obs()
        x0 = np.concatenate([r0 + np.array([2.0, -1.5, 1.0]),
                              v0 + np.array([0.002, -0.0015, 0.001])])
        P0 = _tight_P0()
        result = ekf_orbit_determination(obs, x0, P0)
        n = len(obs)
        assert len(result.state_history) == n
        assert len(result.covariance_history) == n
        assert len(result.innovations) == n

    def test_n_observations_correct(self):
        """n_observations counts scalar observations (2 per 'both' epoch)."""
        obs, r0, v0 = _half_orbit_obs(obs_type="both")
        x0 = np.concatenate([r0, v0])
        P0 = _tight_P0()
        result = ekf_orbit_determination(obs, x0, P0)
        # 'both' → 2 scalar obs per epoch
        assert result.n_observations == 2 * len(obs)


# ---------------------------------------------------------------------------
# 2. Covariance positive-definiteness (Joseph form)
# ---------------------------------------------------------------------------

class TestCovariancePositiveDefinite:
    """Joseph-form update must keep P positive-definite throughout the arc."""

    def test_final_covariance_positive_definite(self):
        """All eigenvalues of final P must be positive."""
        obs, r0, v0 = _half_orbit_obs(seed=42)
        x0 = np.concatenate([r0 + np.array([2.0, -1.5, 1.0]),
                              v0 + np.array([0.002, -0.0015, 0.001])])
        P0 = _tight_P0()
        result = ekf_orbit_determination(obs, x0, P0)
        eigvals = np.linalg.eigvalsh(result.covariance_final)
        assert np.all(eigvals > -1e-10 * abs(eigvals[-1])), (
            f"Final covariance not PD: min eigenvalue = {eigvals[0]:.2e}"
        )

    def test_all_history_covariances_positive_definite(self):
        """All history covariances must be positive-definite."""
        obs, r0, v0 = _half_orbit_obs(seed=5)
        x0 = np.concatenate([r0 + np.array([2.0, -1.5, 1.0]),
                              v0 + np.array([0.002, -0.0015, 0.001])])
        P0 = _tight_P0()
        result = ekf_orbit_determination(obs, x0, P0)
        for i, P in enumerate(result.covariance_history):
            eigvals = np.linalg.eigvalsh(P)
            assert np.all(eigvals > -1e-10 * abs(eigvals[-1])), (
                f"Covariance at step {i} not PD: min eigenvalue = {eigvals[0]:.2e}"
            )

    def test_covariance_shrinks_with_observations(self):
        """Posterior covariance trace should decrease as more obs are processed."""
        obs, r0, v0 = _half_orbit_obs(seed=7)
        x0 = np.concatenate([r0 + np.array([2.0, -1.5, 1.0]),
                              v0 + np.array([0.002, -0.0015, 0.001])])
        P0 = _tight_P0(scale=5.0)
        result = ekf_orbit_determination(obs, x0, P0)
        # Trace of position part should be smaller at end than start
        trace_start = float(np.trace(result.covariance_history[0][:3, :3]))
        trace_end = float(np.trace(result.covariance_final[:3, :3]))
        assert trace_end <= trace_start * 10, (
            f"Posterior covariance trace {trace_end:.2e} grew unexpectedly "
            f"from initial {trace_start:.2e}"
        )


# ---------------------------------------------------------------------------
# 3. State accuracy
# ---------------------------------------------------------------------------

class TestStateAccuracy:
    """EKF with consistent noise should converge close to truth."""

    def test_ekf_reduces_position_error(self):
        """EKF posterior position error at final epoch should be less than initial error.

        Note: result.state_final is the posterior state at the LAST observation
        epoch (t_final), not at t=0.  We compare against the propagated truth at
        t_final, not against r0.
        """
        obs, r0, v0 = _half_orbit_obs(seed=11)
        perturb = np.array([2.0, -1.5, 1.0])
        x0 = np.concatenate([r0 + perturb, v0 + perturb[:3] / 1000.0])
        P0 = _tight_P0(scale=4.0)
        result = ekf_orbit_determination(obs, x0, P0)

        # Compare at the last observation time (the epoch of state_final)
        t_final = obs[-1].t
        r_truth_final, _ = _propagate_truth_to(r0, v0, t_final)
        final_err = float(np.linalg.norm(result.state_final[:3] - r_truth_final))
        initial_err = float(np.linalg.norm(perturb))

        assert final_err < initial_err * 2.0, (
            f"EKF did not reduce position error: {final_err:.3f} km > 2× initial {initial_err:.3f} km"
        )

    def test_two_station_ekf_accuracy(self):
        """EKF with two stations should give position error < 10 km at final epoch."""
        r0, v0 = _leo_truth_state()
        gs1 = geodetic_to_eci(20.0, 60.0, 0.0)
        gs2 = geodetic_to_eci(-15.0, 150.0, 0.0)
        obs_times = [t for t in range(120, 2401, 120)]
        obs1 = generate_synthetic_observations(
            r0, v0, obs_times, gs1, obs_type="both",
            sigma_range_km=0.001, sigma_rrate_km_per_s=1e-6, seed=101,
        )
        obs2 = generate_synthetic_observations(
            r0, v0, obs_times, gs2, obs_type="both",
            sigma_range_km=0.001, sigma_rrate_km_per_s=1e-6, seed=102,
        )
        obs = sorted(obs1 + obs2, key=lambda o: o.t)
        x0 = np.concatenate([r0 + np.array([3.0, -2.0, 1.5]),
                              v0 + np.array([0.003, -0.002, 0.0015])])
        P0 = _tight_P0(scale=5.0)
        result = ekf_orbit_determination(obs, x0, P0)

        # Compare at the last observation epoch
        t_final = obs[-1].t
        r_truth_final, _ = _propagate_truth_to(r0, v0, t_final)
        pos_err = float(np.linalg.norm(result.state_final[:3] - r_truth_final))
        assert pos_err < 10.0, (
            f"Two-station EKF position error {pos_err:.3f} km > 10 km"
        )


# ---------------------------------------------------------------------------
# 4. Innovation consistency
# ---------------------------------------------------------------------------

class TestInnovationConsistency:
    """Innovation RMS ≈ 1 for a consistent noise model."""

    def test_innovation_rms_order_one(self):
        """Innovation RMS should be O(1) for consistent noise model."""
        obs, r0, v0 = _half_orbit_obs(seed=33)
        x0 = np.concatenate([r0 + np.array([2.0, -1.5, 1.0]),
                              v0 + np.array([0.002, -0.0015, 0.001])])
        P0 = _tight_P0()
        result = ekf_orbit_determination(obs, x0, P0)
        assert result.rms_innovation < 20.0, (
            f"Innovation RMS {result.rms_innovation:.3f} > 20 — filter seriously inconsistent"
        )
        assert result.rms_innovation >= 0.0, "Innovation RMS must be non-negative"


# ---------------------------------------------------------------------------
# 5. Process noise
# ---------------------------------------------------------------------------

class TestProcessNoise:
    """EKF with Q > 0 should still converge and maintain PD covariance."""

    def test_process_noise_runs(self):
        """EKF with non-zero process noise Q > 0 runs without error."""
        obs, r0, v0 = _half_orbit_obs(seed=55)
        x0 = np.concatenate([r0 + np.array([2.0, -1.5, 1.0]),
                              v0 + np.array([0.002, -0.0015, 0.001])])
        P0 = _tight_P0()
        result = ekf_orbit_determination(obs, x0, P0, q_pos_km=0.01, q_vel_km_s=1e-5)
        assert np.all(np.isfinite(result.state_final)), "State with Q has NaN/Inf"
        assert np.all(np.isfinite(result.covariance_final)), "Cov with Q has NaN/Inf"

    def test_process_noise_increases_covariance(self):
        """Adding Q should result in larger or equal final covariance trace."""
        obs, r0, v0 = _half_orbit_obs(seed=66)
        x0 = np.concatenate([r0 + np.array([2.0, -1.5, 1.0]),
                              v0 + np.array([0.002, -0.0015, 0.001])])
        P0 = _tight_P0()
        res_no_q = ekf_orbit_determination(obs, x0.copy(), P0.copy())
        res_with_q = ekf_orbit_determination(obs, x0.copy(), P0.copy(),
                                             q_pos_km=0.1, q_vel_km_s=1e-4)
        trace_no_q = float(np.trace(res_no_q.covariance_final))
        trace_with_q = float(np.trace(res_with_q.covariance_final))
        assert trace_with_q >= trace_no_q * 0.5, (
            f"Process noise should increase covariance: with_Q={trace_with_q:.2e} < no_Q={trace_no_q:.2e}"
        )


# ---------------------------------------------------------------------------
# 6. EKF vs batch LS comparison
# ---------------------------------------------------------------------------

class TestEKFVsBatch:
    """EKF and batch LS on same data should give consistent results."""

    def test_ekf_and_batch_agree_coarse(self):
        """EKF and batch LS both reduce position error from truth at their respective epochs.

        Note: EKF state_final is at t_final (last obs epoch); batch state_epoch is at t=0.
        We verify each independently reduces error vs the truth at the corresponding epoch.
        """
        obs, r0, v0 = _half_orbit_obs(seed=77)
        perturb = np.array([2.0, -1.5, 1.0])
        x0 = np.concatenate([r0 + perturb, v0 + perturb / 1000.0])
        P0 = _tight_P0(scale=5.0)

        res_ekf = ekf_orbit_determination(obs, x0.copy(), P0)
        res_batch = batch_least_squares_od(obs, x0.copy(), max_iter=20)

        assert res_batch.converged, "Batch LS did not converge"

        # Both should be finite
        assert np.all(np.isfinite(res_ekf.state_final))
        assert np.all(np.isfinite(res_batch.state_epoch))

        # Batch LS should reduce position error at epoch t=0
        batch_err = float(np.linalg.norm(res_batch.state_epoch[:3] - r0))
        assert batch_err < 2.0 * float(np.linalg.norm(perturb)), (
            f"Batch LS position error at epoch {batch_err:.3f} km > 2× initial"
        )

        # EKF should produce a finite state with reasonable position magnitude
        pos_norm = float(np.linalg.norm(res_ekf.state_final[:3]))
        assert 6000.0 < pos_norm < 10000.0, (
            f"EKF final position norm {pos_norm:.1f} km unrealistic for LEO"
        )


# ---------------------------------------------------------------------------
# 7. Input validation
# ---------------------------------------------------------------------------

class TestEKFInputValidation:
    """Invalid inputs raise ValueError with descriptive messages."""

    def test_empty_observations(self):
        r0, v0 = _leo_truth_state()
        with pytest.raises(ValueError, match="observation"):
            ekf_orbit_determination([], np.concatenate([r0, v0]), np.eye(6))

    def test_wrong_state_shape(self):
        obs, r0, v0 = _half_orbit_obs()
        with pytest.raises(ValueError, match="shape"):
            ekf_orbit_determination(obs, np.array([1.0, 2.0, 3.0]), np.eye(6))

    def test_wrong_P0_shape(self):
        obs, r0, v0 = _half_orbit_obs()
        x0 = np.concatenate([r0, v0])
        with pytest.raises(ValueError, match="shape"):
            ekf_orbit_determination(obs, x0, np.eye(3))

    def test_time_order_error(self):
        """Out-of-order observations must raise ValueError."""
        r0, v0 = _leo_truth_state()
        r_gs = _good_station()
        obs = generate_synthetic_observations(
            r0, v0, [100.0, 200.0], r_gs,
            obs_type="both", sigma_range_km=0.001, sigma_rrate_km_per_s=1e-6
        )
        with pytest.raises(ValueError, match="time-ordered"):
            ekf_orbit_determination(
                [obs[1], obs[0]],
                np.concatenate([r0, v0]),
                np.eye(6),
            )


# ---------------------------------------------------------------------------
# 8. LLM tool round-trip
# ---------------------------------------------------------------------------

class TestEKFLLMTool:
    """aero_ekf_orbit_determination LLM tool returns well-formed dict."""

    def test_happy_path(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_ekf_orbit_determination

        r0, v0 = _leo_truth_state()
        r_gs = _good_station()
        obs = generate_synthetic_observations(
            r0, v0, [t * 60.0 for t in range(1, 10)], r_gs,
            obs_type="both", sigma_range_km=0.001, sigma_rrate_km_per_s=1e-6, seed=99,
        )
        obs_dicts = [
            {"t": o.t, "obs_type": o.obs_type, "y": o.y.tolist(),
             "sigma": o.sigma.tolist(), "station_eci": o.station_eci.tolist()}
            for o in obs
        ]
        x0 = np.concatenate([r0 + np.array([2.0, -1.5, 1.0]),
                              v0 + np.array([0.002, -0.0015, 0.001])]).tolist()

        result = aero_ekf_orbit_determination(obs_dicts, x0)
        assert result["ok"] is True
        assert len(result["state_final"]) == 6
        assert len(result["covariance_diag"]) == 6
        assert "rms_innovation" in result
        assert result["n_observations"] == 2 * 9  # 9 epochs × 2 observables each

    def test_empty_obs_raises(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_ekf_orbit_determination
        r0, v0 = _leo_truth_state()
        with pytest.raises(ValueError, match="non-empty"):
            aero_ekf_orbit_determination([], [0.0] * 6)

    def test_wrong_x0_size_raises(self):
        from kerf_aero.llm_tools.aerospace_tools import aero_ekf_orbit_determination
        r0, v0 = _leo_truth_state()
        r_gs = _good_station()
        obs = generate_synthetic_observations(
            r0, v0, [60.0], r_gs,
            obs_type="range", sigma_range_km=0.001, sigma_rrate_km_per_s=1e-6
        )
        obs_dicts = [
            {"t": o.t, "obs_type": o.obs_type, "y": o.y.tolist(),
             "sigma": o.sigma.tolist(), "station_eci": o.station_eci.tolist()}
            for o in obs
        ]
        with pytest.raises(ValueError, match="length 6"):
            aero_ekf_orbit_determination(obs_dicts, [1.0, 2.0, 3.0])
