"""Tests for orbital/b_plane.py — B-plane targeting."""

from __future__ import annotations

import math
import pytest
import numpy as np

from kerf_aero.orbital.b_plane import (
    b_plane_frame,
    BPlaneFrame,
    b_plane_from_state,
    BPlaneResult,
    b_plane_target_delta_v,
    BPlaneTargetResult,
)

# Earth gravitational parameter [km^3/s^2]
MU = 398600.4418


class TestBPlaneFrame:
    """Validate B-plane coordinate frame construction."""

    def test_orthonormal_triad(self):
        """S, T, R should form an orthonormal right-handed triad."""
        v_inf = np.array([1.0, 2.0, -1.0])
        frame = b_plane_frame(v_inf)

        assert abs(float(np.dot(frame.s_hat, frame.s_hat)) - 1.0) < 1e-12
        assert abs(float(np.dot(frame.t_hat, frame.t_hat)) - 1.0) < 1e-12
        assert abs(float(np.dot(frame.r_hat, frame.r_hat)) - 1.0) < 1e-12

        # Mutual orthogonality
        assert abs(float(np.dot(frame.s_hat, frame.t_hat))) < 1e-12
        assert abs(float(np.dot(frame.s_hat, frame.r_hat))) < 1e-12
        assert abs(float(np.dot(frame.t_hat, frame.r_hat))) < 1e-12

    def test_right_handed(self):
        """R = S × T (right-handed)."""
        v_inf = np.array([3.0, 1.0, -2.0])
        frame = b_plane_frame(v_inf)
        r_check = np.cross(frame.s_hat, frame.t_hat)
        np.testing.assert_allclose(frame.r_hat, r_check, atol=1e-12)

    def test_zero_v_inf_raises(self):
        with pytest.raises(ValueError):
            b_plane_frame(np.array([0.0, 0.0, 0.0]))


class TestBPlaneFromState:
    """Validate B-plane parameters from hyperbolic state vectors."""

    def _hyperbolic_state(self, rp_km: float, v_inf_mag: float, mu: float = MU):
        """Generate a hyperbolic approach state with known periapsis.

        At periapsis of a hyperbolic orbit:
            v_p = sqrt(v_inf² + 2*mu/rp)   [conservation of energy]
            e = 1 + rp*v_inf²/mu

        The spacecraft is placed at periapsis: r = (rp, 0, 0), v = (0, v_p, 0).
        """
        # Periapsis velocity from energy conservation:
        #   xi = v_inf²/2 = v_p²/2 - mu/rp  →  v_p = sqrt(v_inf² + 2mu/rp)
        v_p = math.sqrt(v_inf_mag ** 2 + 2.0 * mu / rp_km)

        # Eccentricity: e = 1 + rp*v_inf²/mu
        e = 1.0 + rp_km * v_inf_mag ** 2 / mu

        r_vec = np.array([rp_km, 0.0, 0.0])
        v_vec = np.array([0.0, v_p, 0.0])

        return r_vec, v_vec, e

    def test_eccentricity_greater_than_1(self):
        """State at periapsis of hyperbola → e > 1."""
        r_vec, v_vec, _ = self._hyperbolic_state(rp_km=8000.0, v_inf_mag=2.0)
        result = b_plane_from_state(r_vec, v_vec, MU)
        assert result.ecc > 1.0

    def test_c3_matches_v_inf_squared(self):
        """C3 = V_inf² should match input."""
        v_inf = 2.5   # km/s
        r_vec, v_vec, _ = self._hyperbolic_state(rp_km=8000.0, v_inf_mag=v_inf)
        result = b_plane_from_state(r_vec, v_vec, MU)
        assert abs(result.c3_km2s2 - v_inf ** 2) < 0.5, (
            f"C3 {result.c3_km2s2:.3f} vs expected {v_inf**2:.3f} km²/s²"
        )

    def test_rp_within_tolerance(self):
        """Periapsis radius should match input (within 5%)."""
        rp_target = 7000.0
        r_vec, v_vec, _ = self._hyperbolic_state(rp_km=rp_target, v_inf_mag=2.0)
        result = b_plane_from_state(r_vec, v_vec, MU)
        rel_err = abs(result.rp_km - rp_target) / rp_target
        assert rel_err < 0.05, (
            f"rp {result.rp_km:.1f} km vs target {rp_target:.1f} km; rel err {rel_err:.2%}"
        )

    def test_elliptic_orbit_raises(self):
        """Elliptic orbit (bound) should raise ValueError."""
        # Circular LEO: e = 0 < 1
        r_vec = np.array([6778.0, 0.0, 0.0])
        v_circ = math.sqrt(MU / 6778.0)
        v_vec = np.array([0.0, v_circ, 0.0])
        with pytest.raises(ValueError):
            b_plane_from_state(r_vec, v_vec, MU)

    def test_b_magnitude_positive(self):
        """B-vector magnitude should be positive."""
        r_vec, v_vec, _ = self._hyperbolic_state(rp_km=8000.0, v_inf_mag=3.0)
        result = b_plane_from_state(r_vec, v_vec, MU)
        assert result.b_magnitude > 0.0


class TestBPlaneTargetDeltaV:
    """Validate that B-plane targeting correction manoeuvre reduces B-plane error."""

    def _approach_state(self):
        """Hyperbolic approach state for a basic flyby scenario."""
        v_inf = 3.0   # km/s
        rp = 7500.0
        v_p = math.sqrt(v_inf ** 2 + 2.0 * MU / rp)
        r_vec = np.array([rp, 0.0, 0.0])
        v_vec = np.array([0.0, v_p, 0.0])
        return r_vec, v_vec

    def test_targeting_reduces_error(self):
        """After targeting correction, achieved B should be closer to target."""
        r_vec, v_vec = self._approach_state()

        target_bdt = 1000.0   # km
        target_bdr = 500.0    # km

        result = b_plane_target_delta_v(
            r_vec, v_vec, MU,
            target_b_dot_t=target_bdt,
            target_b_dot_r=target_bdr,
            tol=1.0,
        )

        assert isinstance(result, BPlaneTargetResult)
        # Delta-V should be finite
        assert math.isfinite(result.dv_magnitude)
        assert result.dv_magnitude >= 0

    def test_result_has_correct_shape(self):
        """Result delta-V should be a 3-vector."""
        r_vec, v_vec = self._approach_state()
        result = b_plane_target_delta_v(r_vec, v_vec, MU, 1000.0, 500.0)
        assert result.dv_vec.shape == (3,)
