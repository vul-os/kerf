"""Tests for orbital/stm.py — State Transition Matrix propagation."""

from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_aero.orbital.stm import (
    keplerian_jacobian,
    j2_jacobian,
    propagate_stm,
    propagate_covariance,
    differential_correction,
    STMResult,
)
from kerf_aero.orbital.kepler import MU_EARTH, orbital_period, propagate_kepler, KeplerianElements


class TestKeplerianJacobian:
    """Validate the Keplerian A-matrix."""

    def test_shape(self):
        r = np.array([6778.0, 0.0, 0.0])
        A = keplerian_jacobian(r)
        assert A.shape == (6, 6)

    def test_top_right_is_identity(self):
        """Upper-right 3×3 block = I₃ (velocity derivatives)."""
        r = np.array([7000.0, 100.0, 200.0])
        A = keplerian_jacobian(r)
        np.testing.assert_allclose(A[0:3, 3:6], np.eye(3), atol=1e-12)

    def test_upper_left_is_zero(self):
        """Upper-left 3×3 block = 0."""
        r = np.array([7000.0, 0.0, 0.0])
        A = keplerian_jacobian(r)
        np.testing.assert_allclose(A[0:3, 0:3], np.zeros((3, 3)), atol=1e-12)

    def test_gravity_gradient_symmetric(self):
        """Gravity gradient G (lower-left) should be symmetric."""
        r = np.array([6778.0, 1000.0, 500.0])
        A = keplerian_jacobian(r)
        G = A[3:6, 0:3]
        np.testing.assert_allclose(G, G.T, atol=1e-10)

    def test_zero_position_raises(self):
        with pytest.raises(ValueError):
            keplerian_jacobian(np.array([0.0, 0.0, 0.0]))


class TestPropagateSTM:
    """Validate STM propagation properties."""

    # Circular LEO state
    R0 = np.array([6778.0, 0.0, 0.0])
    V0 = np.array([0.0, math.sqrt(MU_EARTH / 6778.0), 0.0])

    def test_stm_shape(self):
        result = propagate_stm(self.R0, self.V0, 3600.0)
        assert result.stm.shape == (6, 6)

    def test_stm_at_t0_is_identity(self):
        """At t=0, STM should be identity."""
        result = propagate_stm(self.R0, self.V0, 0.0, n_steps=1)
        np.testing.assert_allclose(result.stm, np.eye(6), atol=1e-10)

    def test_stm_determinant_near_unity(self):
        """Symplecticity: det(Φ) ≈ 1 for Hamiltonian dynamics."""
        result = propagate_stm(self.R0, self.V0, 3600.0)
        det = float(np.linalg.det(result.stm))
        assert abs(det - 1.0) < 0.05, (
            f"STM determinant {det:.6f} too far from 1"
        )

    def test_state_propagates_correctly(self):
        """Final position should be consistent with Kepler propagation."""
        T = orbital_period(6778.0, MU_EARTH)
        result = propagate_stm(self.R0, self.V0, T, n_steps=360)
        # After one full orbit, position should return near initial
        r_final = result.state_final[:3]
        rel_err = float(np.linalg.norm(r_final - self.R0)) / float(np.linalg.norm(self.R0))
        assert rel_err < 0.01, (
            f"Position after one orbit: rel err {rel_err:.4f} > 1%"
        )

    def test_j2_stm_differs_from_keplerian(self):
        """STM with J2 should differ from pure Keplerian."""
        res_kepler = propagate_stm(self.R0, self.V0, 3600.0, include_j2=False)
        res_j2 = propagate_stm(self.R0, self.V0, 3600.0, include_j2=True)
        diff = float(np.max(np.abs(res_kepler.stm - res_j2.stm)))
        assert diff > 0, "J2 STM should differ from Keplerian"

    def test_t_elapsed_correct(self):
        dt = 7200.0
        result = propagate_stm(self.R0, self.V0, dt)
        assert abs(result.t_elapsed - dt) < 1e-9


class TestPropagateCovariance:
    """Validate covariance propagation."""

    def test_output_shape(self):
        R0 = np.array([6778.0, 0.0, 0.0])
        V0 = np.array([0.0, math.sqrt(MU_EARTH / 6778.0), 0.0])
        result = propagate_stm(R0, V0, 1800.0)
        P0 = np.eye(6) * 1.0   # 1 km² / (km/s)² diagonal
        P1 = propagate_covariance(P0, result.stm)
        assert P1.shape == (6, 6)

    def test_identity_covariance_grows(self):
        """Unit initial covariance should grow during propagation (uncertainty increases)."""
        R0 = np.array([6778.0, 0.0, 0.0])
        V0 = np.array([0.0, math.sqrt(MU_EARTH / 6778.0), 0.0])
        result = propagate_stm(R0, V0, 3600.0)
        P0 = np.eye(6)
        P1 = propagate_covariance(P0, result.stm)
        # Position variance should grow
        assert P1[0, 0] != P0[0, 0] or P1[1, 1] != P0[1, 1]


class TestDifferentialCorrection:
    """Validate differential correction for rendezvous targeting."""

    def test_lambert_like_correction(self):
        """Correct an initial velocity to reach a target position after TOF."""
        r0 = np.array([6778.0, 0.0, 0.0])
        # Target: position after ~1/4 orbit
        T = orbital_period(6778.0, MU_EARTH)
        tof = T / 4.0

        # True velocity at departure (circular)
        v_circ = math.sqrt(MU_EARTH / 6778.0)
        v_true = np.array([0.0, v_circ, 0.0])

        # Propagate true state to get true target
        true_result = propagate_stm(r0, v_true, tof)
        r_target = true_result.state_final[:3]

        # Use slightly perturbed initial velocity as guess
        v_guess = v_true + np.array([0.05, 0.0, 0.0])

        v_corrected = differential_correction(r0, v_guess, r_target, tof)
        assert v_corrected.shape == (3,)
        # Corrected velocity should be closer to truth
        err_guess = float(np.linalg.norm(v_guess - v_true))
        err_corr = float(np.linalg.norm(v_corrected - v_true))
        assert err_corr < err_guess, (
            f"Corrected velocity error {err_corr:.6f} not less than guess {err_guess:.6f}"
        )
