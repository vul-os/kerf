"""
Test suite for kerf_cfd.rans.k_omega_sst — Menter (1994) k-ω SST turbulence model.

Tests cover:
  1. Closure constants (Menter 1994 values)
  2. Eddy-viscosity SST formula and limiter behaviour
  3. F1 blending: → 1 near wall, → 0 freestream
  4. F2 blending: → 1 in boundary layer, → 0 freestream
  5. SST μ_t reduces to k-ε form (k/ω) far from walls
  6. Positivity preservation after a pseudo-time step
  7. Backward-facing step smoke test: k decays away from wall

References
----------
[Menter1994] Menter F. R., AIAA J. 32(8) (1994) 1598-1605.
[DS1985]     Driver D. M., Seegmiller H. L., AIAA J. 23(2) (1985) 163-171.
[Pope2000]   Pope S. B., Turbulent Flows, Cambridge 2000.
"""

from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC  = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import numpy as np
import pytest

from kerf_cfd.rans.k_omega_sst import (
    KOmegaSSTConstants,
    KOmegaSSTState,
    _K_MIN,
    _OMG_MIN,
    _compute_F1_scalar,
    _compute_F2_scalar,
    compute_eddy_viscosity_sst,
    step_k_omega_sst,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rel(a: float, b: float) -> float:
    return abs(a - b) / max(abs(b), 1.0e-30)


def _simple_mesh(n: int):
    """Build minimal 1-D chain mesh. Returns (vols, nbrs, wall_dist)."""
    vols  = np.ones(n)
    nbrs  = [[j for j in [i - 1, i + 1] if 0 <= j < n] for i in range(n)]
    # Wall distances: cell 0 is closest to wall
    wall_dist = np.linspace(0.001, 1.0, n)
    return vols, nbrs, wall_dist


def _default_state(n: int, k_val: float = 0.1, omega_val: float = 10.0, rho: float = 1.0):
    c = KOmegaSSTConstants()
    k     = np.full(n, k_val)
    omega = np.full(n, omega_val)
    S_mag = np.zeros(n)
    F2    = np.zeros(n)
    mu_t  = compute_eddy_viscosity_sst(k, omega, S_mag, F2, rho, c.a1)
    F1    = np.zeros(n)
    return KOmegaSSTState(k=k, omega=omega, mu_t=mu_t, F1=F1)


# ===========================================================================
# 1. Closure constants — Menter (1994) Table 1
# ===========================================================================

class TestKOmegaSSTConstants:
    """All constants must match Menter (1994) Table 1."""

    def test_sigma_k1(self):
        """σ_k1 = 0.85  [Menter1994 Table 1]"""
        c = KOmegaSSTConstants()
        assert c.sigma_k1 == pytest.approx(0.85, rel=1e-12)

    def test_sigma_w1(self):
        """σ_ω1 = 0.5  [Menter1994 Table 1]"""
        c = KOmegaSSTConstants()
        assert c.sigma_w1 == pytest.approx(0.5, rel=1e-12)

    def test_beta1(self):
        """β1 = 0.075  [Menter1994 Table 1]"""
        c = KOmegaSSTConstants()
        assert c.beta1 == pytest.approx(0.075, rel=1e-12)

    def test_sigma_k2(self):
        """σ_k2 = 1.0  [Menter1994 Table 1]"""
        c = KOmegaSSTConstants()
        assert c.sigma_k2 == pytest.approx(1.0, rel=1e-12)

    def test_sigma_w2(self):
        """σ_ω2 = 0.856  [Menter1994 Table 1]"""
        c = KOmegaSSTConstants()
        assert c.sigma_w2 == pytest.approx(0.856, rel=1e-12)

    def test_beta2(self):
        """β2 = 0.0828  [Menter1994 Table 1]"""
        c = KOmegaSSTConstants()
        assert c.beta2 == pytest.approx(0.0828, rel=1e-12)

    def test_beta_star(self):
        """β* = 0.09  [Menter1994 eq. 1]"""
        c = KOmegaSSTConstants()
        assert c.beta_star == pytest.approx(0.09, rel=1e-12)

    def test_a1(self):
        """a1 = 0.31  [Menter1994 eq. 2]"""
        c = KOmegaSSTConstants()
        assert c.a1 == pytest.approx(0.31, rel=1e-12)

    def test_kappa(self):
        """κ = 0.41  [Pope2000 §7.1]"""
        c = KOmegaSSTConstants()
        assert c.kappa == pytest.approx(0.41, rel=1e-12)


# ===========================================================================
# 2. Eddy-viscosity formula and SST limiter
# ===========================================================================

class TestComputeEddyViscositySST:
    """μ_t = ρ a1 k / max(a1 ω, S F2)  [Menter1994 eq. 2]"""

    def test_outer_layer_reduces_to_k_over_omega(self):
        """
        Far from wall (F2=0, S=0): μ_t = ρ a1 k / (a1 ω) = ρ k/ω.
        SST μ_t reduces to k-ε form (k/ω) far from walls.
        [Menter1994 eq. 2; Wilcox06 §4.3]
        """
        rho, k_val, omega_val = 1.2, 0.5, 20.0
        k     = np.array([k_val])
        omega = np.array([omega_val])
        S_mag = np.array([0.0])
        F2    = np.array([0.0])
        c     = KOmegaSSTConstants()
        mu_t  = compute_eddy_viscosity_sst(k, omega, S_mag, F2, rho, c.a1)
        expected = rho * k_val / omega_val
        assert mu_t[0] == pytest.approx(expected, rel=1e-8)

    def test_sst_limiter_active_high_strain(self):
        """
        High strain (S F2 >> a1 ω): SST limiter reduces μ_t below ρ k/ω.
        [Menter1994 eq. 2; Bradshaw 1967 assumption τ = ρ a1 k]
        """
        rho, k_val, omega_val = 1.0, 1.0, 1.0
        k     = np.array([k_val])
        omega = np.array([omega_val])
        S_mag = np.array([1000.0])   # very high strain
        F2    = np.array([1.0])      # in boundary layer
        c     = KOmegaSSTConstants()
        mu_t  = compute_eddy_viscosity_sst(k, omega, S_mag, F2, rho, c.a1)
        # Standard k/ω = 1.0; limited value < 1.0
        assert mu_t[0] < rho * k_val / omega_val
        assert mu_t[0] > 0.0

    def test_always_non_negative(self):
        """μ_t ≥ 0 for any valid input."""
        c = KOmegaSSTConstants()
        for k_val in [0.0, 0.001, 1.0]:
            for om_val in [0.0, 0.001, 10.0]:
                for S in [0.0, 1.0, 100.0]:
                    for F2_val in [0.0, 0.5, 1.0]:
                        k   = np.array([k_val])
                        om  = np.array([om_val])
                        Sv  = np.array([S])
                        F2v = np.array([F2_val])
                        mu_t = compute_eddy_viscosity_sst(k, om, Sv, F2v, 1.0, c.a1)
                        assert mu_t[0] >= 0.0


# ===========================================================================
# 3. F1 blending function
# ===========================================================================

class TestF1BlendingFunction:
    """F1 → 1 near wall, F1 → 0 in freestream.  [Menter1994 eq. 12-14]"""

    def test_F1_near_wall_equals_1(self):
        """
        Very close to wall (d → 0): arg1 → ∞, F1 → 1.
        [Menter1994 eq. 12-14]
        """
        c = KOmegaSSTConstants()
        F1 = _compute_F1_scalar(
            k=1e-3, omega=1e3, d=1e-6, nu=1e-5,
            grad_k_dot_grad_omega=0.0, c=c,
        )
        assert F1 > 0.99, f"Expected F1≈1 near wall, got {F1}"

    def test_F1_freestream_near_zero(self):
        """
        Far from wall (large d): arg1 → 0, F1 → 0.
        [Menter1994 eq. 12-14]
        """
        c = KOmegaSSTConstants()
        F1 = _compute_F1_scalar(
            k=1e-4, omega=1.0, d=1000.0, nu=1e-5,
            grad_k_dot_grad_omega=1e-8, c=c,
        )
        assert F1 < 0.05, f"Expected F1≈0 in freestream, got {F1}"

    def test_F1_range(self):
        """F1 ∈ [0, 1] for any physically valid input."""
        c = KOmegaSSTConstants()
        test_cases = [
            (1e-3, 100.0, 0.001, 1.5e-5, 0.0),
            (1e-3, 100.0, 1.0,   1.5e-5, 0.01),
            (1e-4, 0.5,   0.1,   1.0e-6, 0.0),
            (0.1,  500.0, 0.005, 1.5e-5, 1.0),
        ]
        for k, om, d, nu, cross in test_cases:
            F1 = _compute_F1_scalar(k, om, d, nu, cross, c)
            assert 0.0 <= F1 <= 1.0, f"F1={F1} out of [0,1] for inputs {k,om,d}"


# ===========================================================================
# 4. F2 blending function
# ===========================================================================

class TestF2BlendingFunction:
    """F2 → 1 in boundary layer, F2 → 0 freestream.  [Menter1994 eq. 15]"""

    def test_F2_near_wall_equals_1(self):
        """Close to wall: F2 → 1."""
        c = KOmegaSSTConstants()
        F2 = _compute_F2_scalar(k=1e-3, omega=1e4, d=1e-6, nu=1e-5, c=c)
        assert F2 > 0.99, f"Expected F2≈1 near wall, got {F2}"

    def test_F2_freestream_near_zero(self):
        """Far from wall: F2 → 0."""
        c = KOmegaSSTConstants()
        F2 = _compute_F2_scalar(k=1e-4, omega=0.5, d=1000.0, nu=1e-5, c=c)
        assert F2 < 0.05, f"Expected F2≈0 in freestream, got {F2}"

    def test_F2_range(self):
        """F2 ∈ [0, 1] for any valid input."""
        c = KOmegaSSTConstants()
        for d in [1e-6, 0.01, 0.1, 1.0, 100.0]:
            F2 = _compute_F2_scalar(k=1e-3, omega=100.0, d=d, nu=1.5e-5, c=c)
            assert 0.0 <= F2 <= 1.0, f"F2={F2} out of [0,1] at d={d}"

    def test_F2_monotone_decreasing_with_d(self):
        """F2 should decrease (or stay flat) as d increases."""
        c = KOmegaSSTConstants()
        d_vals = [1e-4, 1e-3, 0.01, 0.1, 1.0]
        F2_vals = [_compute_F2_scalar(k=1e-3, omega=50.0, d=d, nu=1.5e-5, c=c)
                   for d in d_vals]
        for i in range(len(F2_vals) - 1):
            assert F2_vals[i] >= F2_vals[i + 1] - 1.0e-10, (
                f"F2 not monotone: F2({d_vals[i]})={F2_vals[i]}, "
                f"F2({d_vals[i+1]})={F2_vals[i+1]}"
            )


# ===========================================================================
# 5. SST μ_t reduces to k-ε form far from walls
# ===========================================================================

class TestSSTOuterLayerKEpsForm:
    """
    In the freestream (F1=0, F2=0, low strain), the SST model should
    reduce to the standard k-ε eddy-viscosity form:

        μ_t = ρ k / ω   (since a1 ω dominates S F2 when F2→0)

    which is algebraically equivalent to k-ε with C_μ=β*:
        μ_t = ρ C_μ k² / ε,   ε = β* k ω  →  μ_t = ρ k / ω

    [Menter1994 §2; Wilcox06 §4.3]
    """

    def test_outer_layer_mut_equals_rho_k_over_omega(self):
        """μ_t → ρ k / ω in outer layer (F2=0, zero strain)."""
        rho = 1.25
        k_val, omega_val = 0.3, 15.0
        k   = np.array([k_val])
        om  = np.array([omega_val])
        S   = np.array([0.0])
        F2  = np.array([0.0])
        c   = KOmegaSSTConstants()
        mu_t = compute_eddy_viscosity_sst(k, om, S, F2, rho, c.a1)
        expected = rho * k_val / omega_val
        assert _rel(mu_t[0], expected) < 1.0e-8

    def test_outer_layer_multiple_cells(self):
        """ρ k/ω matches SST μ_t for all cells in a freestream patch."""
        n = 10
        rho = 1.0
        rng = np.random.default_rng(123)
        k   = rng.uniform(0.01, 1.0, n)
        om  = rng.uniform(1.0, 100.0, n)
        S   = np.zeros(n)
        F2  = np.zeros(n)
        c   = KOmegaSSTConstants()
        mu_t = compute_eddy_viscosity_sst(k, om, S, F2, rho, c.a1)
        expected = rho * k / om
        np.testing.assert_allclose(mu_t, expected, rtol=1e-8)


# ===========================================================================
# 6. Positivity preservation after pseudo-time step
# ===========================================================================

class TestStepKOmegaSSTPositivity:
    """k ≥ 0, ω > 0, μ_t ≥ 0 must hold after step_k_omega_sst."""

    def _build_input(self, n=8, shear_mag=2.0):
        vols, nbrs, wall_dist = _simple_mesh(n)
        state = _default_state(n)

        grad_u = np.zeros((n, 2, 2))
        grad_u[:, 0, 1] = shear_mag
        u = np.zeros((n, 2))
        return state, u, grad_u, vols, nbrs, wall_dist

    def test_k_non_negative_after_step(self):
        """k ≥ 0 after one step."""
        state, u, grad_u, vols, nbrs, wd = self._build_input()
        new = step_k_omega_sst(state, u, grad_u, wd, vols, nbrs,
                               rho=1.0, mu=1e-4, dt=1e-4)
        assert np.all(new.k >= 0.0)

    def test_omega_positive_after_step(self):
        """ω > 0 after one step."""
        state, u, grad_u, vols, nbrs, wd = self._build_input()
        new = step_k_omega_sst(state, u, grad_u, wd, vols, nbrs,
                               rho=1.0, mu=1e-4, dt=1e-4)
        assert np.all(new.omega > 0.0)

    def test_mu_t_non_negative_after_step(self):
        """μ_t ≥ 0 after one step."""
        state, u, grad_u, vols, nbrs, wd = self._build_input()
        new = step_k_omega_sst(state, u, grad_u, wd, vols, nbrs,
                               rho=1.0, mu=1e-4, dt=1e-4)
        assert np.all(new.mu_t >= 0.0)

    def test_F1_returned_in_state(self):
        """KOmegaSSTState.F1 field is populated by step."""
        state, u, grad_u, vols, nbrs, wd = self._build_input()
        new = step_k_omega_sst(state, u, grad_u, wd, vols, nbrs,
                               rho=1.0, mu=1e-4, dt=1e-4)
        assert hasattr(new, 'F1')
        assert len(new.F1) == len(state.k)

    def test_F1_range_after_step(self):
        """F1 ∈ [0, 1] after one step."""
        state, u, grad_u, vols, nbrs, wd = self._build_input()
        new = step_k_omega_sst(state, u, grad_u, wd, vols, nbrs,
                               rho=1.0, mu=1e-4, dt=1e-4)
        assert np.all(new.F1 >= 0.0)
        assert np.all(new.F1 <= 1.0)


# ===========================================================================
# 7. Backward-facing step smoke test: k decays away from wall
# ===========================================================================

class TestBFSSmokeTestSST:
    """
    Backward-facing step smoke test using a 1-D wall-normal k profile
    with the k-ω SST model.

    Physical expectation (Driver-Seegmiller 1985, [DS1985]):
      k is elevated near the wall / step height and decays in the freestream.
    """

    def test_k_profile_decays_away_from_wall(self):
        """
        k(cell_0) > k(cell_7) after several steps when production
        is concentrated near the wall.
        [DS1985; Menter1994]
        """
        n = 8
        rho = 1.0; mu = 1e-4; dt = 5e-4

        vols, nbrs, wall_dist = _simple_mesh(n)

        k_init   = np.array([1.0, 0.8, 0.3, 0.2, 0.1, 0.05, 0.03, 0.02])
        om_init  = np.array([50., 40., 20., 15., 10.,  8.,   5.,   3.])

        c = KOmegaSSTConstants()
        S_mag = np.zeros(n); F2 = np.zeros(n)
        mu_t0 = compute_eddy_viscosity_sst(k_init, om_init, S_mag, F2, rho, c.a1)
        F1_0  = np.zeros(n)
        state = KOmegaSSTState(k=k_init, omega=om_init, mu_t=mu_t0, F1=F1_0)

        # Shear only in cell 0 (near wall)
        grad_u = np.zeros((n, 2, 2))
        grad_u[0, 0, 1] = 10.0
        u = np.zeros((n, 2))

        for _ in range(200):
            state = step_k_omega_sst(
                state, u, grad_u, wall_dist, vols, nbrs, rho, mu, dt,
            )

        assert state.k[0] > state.k[7], (
            f"Expected k_wall={state.k[0]:.4f} > k_freestream={state.k[7]:.4f}; "
            "k should decay away from wall (Driver-Seegmiller 1985)"
        )

    def test_F1_higher_near_wall_after_steps(self):
        """
        F1 near wall (cell 0) should be higher than freestream (cell 7)
        after steps, since cell 0 is closest to the wall.
        [Menter1994 eq. 12-14]
        """
        n = 8
        rho = 1.0; mu = 1e-4; dt = 5e-4

        vols, nbrs, wall_dist = _simple_mesh(n)

        k_init  = np.full(n, 0.1)
        om_init = np.full(n, 10.0)
        c = KOmegaSSTConstants()
        S_mag = np.zeros(n); F2 = np.zeros(n)
        mu_t0 = compute_eddy_viscosity_sst(k_init, om_init, S_mag, F2, rho, c.a1)
        state = KOmegaSSTState(k=k_init, omega=om_init, mu_t=mu_t0,
                               F1=np.zeros(n))

        grad_u = np.zeros((n, 2, 2))
        grad_u[:, 0, 1] = 1.0
        u = np.zeros((n, 2))

        state = step_k_omega_sst(
            state, u, grad_u, wall_dist, vols, nbrs, rho, mu, dt,
        )

        # F1 should be higher near wall (cell 0) than in freestream (cell 7)
        # due to smaller wall distance
        assert state.F1[0] >= state.F1[7], (
            f"F1 near wall={state.F1[0]:.4f} should be ≥ freestream={state.F1[7]:.4f}; "
            "blending function should be larger near wall [Menter1994 eq. 12-14]"
        )
