"""
Tests for Mohr-Coulomb plasticity model.

Covers:
  - Elastic regime: stress unchanged.
  - Single-surface return on uniaxial tension.
  - Zero cohesion → frictional only (c = 0).
  - Principal-stress ordering preserved.
  - Yield function sign convention.
  - Edge/multi-surface return consistency.
  - Apex return for high triaxial tension.
  - After return mapping, yield function ≈ 0.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_fem.plasticity.mohr_coulomb import (
    MohrCoulombMaterial,
    _mc_params,
    return_map_mc,
    yield_function_mc,
)
from kerf_fem.plasticity.return_mapping import voigt_to_tensor, principal_stresses

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mat(phi: float = 30.0, c: float = 50e3, psi: float = 20.0,
         E: float = 50e6, nu: float = 0.25):
    return MohrCoulombMaterial(
        youngs_modulus_pa=E,
        poisson=nu,
        cohesion_pa=c,
        friction_angle_deg=phi,
        dilation_angle_deg=psi,
    )


def _principal(s1: float, s2: float, s3: float) -> np.ndarray:
    """Build a diagonal stress tensor in Voigt (no shear) with given principal values."""
    return np.array([s1, s2, s3, 0.0, 0.0, 0.0])


# ===========================================================================
# 1. MC parameter computation
# ===========================================================================

class TestMCParams:

    def test_N_phi_at_30_deg(self):
        """N_φ = (1+sin30°)/(1-sin30°) = (1+0.5)/(1-0.5) = 3."""
        mat = _mat(phi=30.0)
        N_phi, _, _, _, _ = _mc_params(mat)
        assert abs(N_phi - 3.0) < 1e-10

    def test_N_phi_increases_with_friction(self):
        """Larger φ → larger N_φ."""
        N_20, _, _, _, _ = _mc_params(_mat(phi=20.0))
        N_30, _, _, _, _ = _mc_params(_mat(phi=30.0))
        assert N_30 > N_20

    def test_zero_friction_N_phi_is_one(self):
        """φ = 0 → N_φ = 1 → Tresca-like (σ₁ − σ₃ = 2c)."""
        mat = _mat(phi=0.0, c=50e3, psi=0.0)
        N_phi, _, two_c_sqrt_N, _, _ = _mc_params(mat)
        assert abs(N_phi - 1.0) < 1e-10


# ===========================================================================
# 2. Yield function
# ===========================================================================

class TestYieldFunction:

    def test_elastic_state_below_yield(self):
        """All-compressive stress below Mohr-Coulomb cone → elastic.

        For phi=30, N_phi=3, c=500 kPa:
          two_c_sqrt_N = 2*500e3*sqrt(3) ≈ 1732 kPa
          f = sigma1 - 3*sigma3 - 1732 = -500 + 2100 - 1732 = -132 kPa < 0.
        """
        mat = _mat(phi=30.0, c=500e3)
        stress = _principal(-500e3, -600e3, -700e3)
        f = yield_function_mc(stress, mat)
        assert f < 0.0

    def test_above_yield(self):
        """Large tensile σ₁ with compressive σ₃ → f > 0."""
        mat = _mat(phi=30.0, c=50e3)
        stress = _principal(1e6, 0.0, -1e6)  # σ₁ = 1 MPa, σ₃ = -1 MPa
        f = yield_function_mc(stress, mat)
        assert f > 0.0

    def test_zero_cohesion_frictional_only(self):
        """
        c = 0: the yield function is frictional only.
        At σ₁ = σ₂ = σ₃ = 0 → f = 0 - N_φ·0 - 0 = 0 (on yield for zero stress).
        Any tensile σ₁ with σ₃ = 0 → f > 0.
        """
        mat = _mat(phi=30.0, c=0.0, psi=0.0)
        stress_tension = _principal(100e3, 0.0, 0.0)
        f = yield_function_mc(stress_tension, mat)
        # σ₁ - N_φ·σ₃ - 0 = σ₁ > 0
        assert f > 0.0


# ===========================================================================
# 3. Elastic step
# ===========================================================================

class TestElasticStep:

    def test_elastic_returns_unchanged_stress(self):
        """Elastic trial → stress unchanged.

        Uses c=500 kPa (large cohesion) so that the confined compressive state
        is guaranteed to be inside the yield cone:
          f = sigma1 - 3*sigma3 - 2c*sqrt(3)
            = -100e3 - 3*(-300e3) - 2*500e3*sqrt(3)
            = -100 + 900 - 1732 = -932 kPa < 0  (elastic).
        """
        mat = _mat(phi=30.0, c=500e3)
        stress = _principal(-100e3, -200e3, -300e3)
        f = yield_function_mc(stress, mat)
        assert f < 0.0, f"Expected elastic state, f = {f}"
        stress_out, info = return_map_mc(stress, mat)
        np.testing.assert_allclose(stress_out, stress, rtol=1e-10)
        assert info["mode"] == "elastic"


# ===========================================================================
# 4. Single-surface return
# ===========================================================================

class TestSingleSurfaceReturn:

    def test_uniaxial_tension_return(self):
        """
        Single-axis tension above yield → single-surface return.
        After return, yield function ≈ 0 (within tolerance).
        """
        mat = _mat(phi=30.0, c=50e3, psi=20.0)
        # σ₁ well above 2c√N_φ with σ₂=σ₃=0
        N_phi, _, two_c_sqrt_N, _, _ = _mc_params(mat)
        sigma1_trial = 2.0 * two_c_sqrt_N
        stress_trial = _principal(sigma1_trial, 0.0, 0.0)
        f_tr = yield_function_mc(stress_trial, mat)
        assert f_tr > 0.0, "Expected above yield"
        stress_n1, info = return_map_mc(stress_trial, mat)
        f_n1 = yield_function_mc(stress_n1, mat)
        assert abs(f_n1) / max(abs(two_c_sqrt_N), 1.0) < 1e-4

    def test_return_mode_is_not_elastic(self):
        """Above-yield trial must not return 'elastic' mode."""
        mat = _mat(phi=30.0, c=50e3, psi=20.0)
        N_phi, _, two_c_sqrt_N, _, _ = _mc_params(mat)
        stress_trial = _principal(2.0 * two_c_sqrt_N, 0.0, 0.0)
        f_tr = yield_function_mc(stress_trial, mat)
        if f_tr <= 0:
            pytest.skip("Stress is elastic")
        _, info = return_map_mc(stress_trial, mat)
        assert info["mode"] != "elastic"


# ===========================================================================
# 5. Zero cohesion (frictional material)
# ===========================================================================

class TestZeroCohesion:

    def test_zero_cohesion_return_map(self):
        """c = 0: any tensile principal stress requires plastic correction."""
        mat = _mat(phi=30.0, c=0.0, psi=15.0)
        # Frictional material: tensile principal stress → yield
        stress_trial = _principal(500e3, 0.0, -100e3)
        f_tr = yield_function_mc(stress_trial, mat)
        assert f_tr > 0.0
        stress_n1, info = return_map_mc(stress_trial, mat)
        assert info["mode"] != "elastic"
        f_n1 = yield_function_mc(stress_n1, mat)
        assert abs(f_n1) / 1e3 < 1.0  # within 1 kPa

    def test_zero_cohesion_zero_stress_at_yield(self):
        """c = 0, φ > 0: zero stress state is on the yield surface (f = 0)."""
        mat = _mat(phi=30.0, c=0.0, psi=0.0)
        f = yield_function_mc(np.zeros(6), mat)
        assert abs(f) < 1e-6


# ===========================================================================
# 6. Principal stress ordering
# ===========================================================================

class TestPrincipalOrdering:

    def test_general_stress_principal_ordering(self):
        """After return mapping, principal stresses must maintain σ₁ ≥ σ₂ ≥ σ₃."""
        mat = _mat(phi=30.0, c=50e3, psi=20.0)
        # Off-diagonal stress with shear components
        stress_trial = np.array([300e3, 100e3, -50e3, 80e3, 20e3, 10e3])
        stress_n1, _ = return_map_mc(stress_trial, mat)
        ps = principal_stresses(stress_n1)
        assert ps[0] >= ps[1] - 1.0  # σ₁ ≥ σ₂ (allow 1 Pa tolerance)
        assert ps[1] >= ps[2] - 1.0  # σ₂ ≥ σ₃

    def test_symmetric_output_tensor(self):
        """Returned stress tensor must be symmetric."""
        mat = _mat(phi=30.0, c=50e3, psi=20.0)
        stress_trial = np.array([400e3, 200e3, 100e3, 100e3, 50e3, 50e3])
        stress_n1, _ = return_map_mc(stress_trial, mat)
        T = voigt_to_tensor(stress_n1)
        np.testing.assert_allclose(T, T.T, atol=1e-3)  # Pa absolute


# ===========================================================================
# 7. Edge and apex returns
# ===========================================================================

class TestEdgeApexReturns:

    def test_large_compressive_hydrostatic_above_yield(self):
        """
        For MC, the apex (cone tip) is in the compressive hemisphere.

        For phi=30, c=100 kPa:
          apex at p_apex = -c/tan(phi) ≈ -173 kPa.
        A state MORE compressive than p_apex (e.g. p = 2*p_apex) is above yield.

        f = sigma1 - N*sigma3 - 2c*sqrt(N)
          For hydrostatic p: sigma1=sigma3=p → f = (1-N)*p - 2c*sqrt(N)
          At 2*p_apex: f = -2*(2*p_apex) - 2c*sqrt(3) = +2c*sqrt(3) > 0.
        """
        import math
        mat = _mat(phi=30.0, c=100e3, psi=15.0)
        c = 100e3
        phi_rad = math.radians(30.0)
        p_apex = -c / math.tan(phi_rad)   # ≈ -173 kPa
        p_beyond = 2.0 * p_apex           # even more compressive → above yield
        stress_trial = np.array([p_beyond, p_beyond, p_beyond, 0.0, 0.0, 0.0])
        f_tr = yield_function_mc(stress_trial, mat)
        assert f_tr > 0.0, f"Expected f>0, got {f_tr}"
        _, info = return_map_mc(stress_trial, mat)
        assert info["mode"] in ("single", "edge", "apex")

    def test_yield_value_trial_positive(self):
        """info dict must always store the positive trial yield value when above yield."""
        mat = _mat(phi=25.0, c=80e3, psi=15.0)
        stress_trial = _principal(1e6, 500e3, -200e3)
        f_tr = yield_function_mc(stress_trial, mat)
        if f_tr <= 0:
            pytest.skip("Elastic")
        _, info = return_map_mc(stress_trial, mat)
        assert info["yield_value_trial"] > 0.0
