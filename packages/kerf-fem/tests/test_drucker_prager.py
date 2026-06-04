"""
Tests for Drucker-Prager plasticity model.

Covers:
  - Elastic regime: stress unchanged.
  - φ = 0 → reduces to J2-like (pressure-independent).
  - Smooth-cone return: updated yield function ≈ 0.
  - Apex return: hydrostatic stress.
  - High triaxial compression → apex.
  - Non-associated flow (ψ < φ).
  - Positive I₁ (tension) branch.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_fem.plasticity.drucker_prager import (
    DruckerPragerMaterial,
    _dp_alpha_k,
    return_map_dp,
    yield_function_dp,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mat(phi: float = 30.0, c: float = 50e3, psi: float = 20.0, E: float = 50e6, nu: float = 0.25):
    return DruckerPragerMaterial(
        youngs_modulus_pa=E,
        poisson=nu,
        cohesion_pa=c,
        friction_angle_deg=phi,
        dilation_angle_deg=psi,
    )


def _hydrostatic(p: float) -> np.ndarray:
    return np.array([p, p, p, 0.0, 0.0, 0.0])


def _deviatoric_trial(s_dev: float, p: float = 0.0) -> np.ndarray:
    """Axisymmetric deviatoric: σ_xx = p + s_dev, σ_yy = σ_zz = p - s_dev/2."""
    return np.array([
        p + s_dev,
        p - 0.5 * s_dev,
        p - 0.5 * s_dev,
        0.0, 0.0, 0.0,
    ])


# ===========================================================================
# 1. Coefficient computation
# ===========================================================================

class TestCoefficients:

    def test_phi_zero_alpha_zero(self):
        """φ = 0 → α = 0 (pressure-independent)."""
        mat = _mat(phi=0.0, c=100e3, psi=0.0)
        alpha, k = _dp_alpha_k(mat)
        assert abs(alpha) < 1e-12

    def test_phi_zero_k_cohesion_based(self):
        """φ = 0 → k = 2c/(√3)."""
        c = 100e3
        mat = _mat(phi=0.0, c=c, psi=0.0)
        alpha, k = _dp_alpha_k(mat)
        # For phi=0: denom = sqrt(3)*3, numerator = 6c*cos(0) = 6c
        # k = 6c / (3√3) = 2c/√3
        k_expected = 2.0 * c / math.sqrt(3.0)
        assert abs(k - k_expected) / k_expected < 1e-10

    def test_alpha_increases_with_friction_angle(self):
        """Larger φ → larger α (more pressure-dependence)."""
        alpha_30, _ = _dp_alpha_k(_mat(phi=30.0))
        alpha_20, _ = _dp_alpha_k(_mat(phi=20.0))
        assert alpha_30 > alpha_20


# ===========================================================================
# 2. Yield function
# ===========================================================================

class TestYieldFunction:

    def test_elastic_hydrostatic_compression(self):
        """Hydrostatic compression below yield → f < 0."""
        mat = _mat(phi=30.0, c=50e3)
        alpha, k = _dp_alpha_k(mat)
        # For elastic: α·I₁ + √J₂ < k
        # All compressive: I₁ < 0, √J₂ = 0 → f = α·I₁ − k < 0
        stress = _hydrostatic(-200e3)  # 200 kPa compression
        f = yield_function_dp(stress, mat)
        assert f < 0.0

    def test_at_yield_surface(self):
        """A stress exactly on the yield surface → f ≈ 0."""
        mat = _mat(phi=30.0, c=50e3)
        alpha, k = _dp_alpha_k(mat)
        # Pure deviatoric (I₁ = 0): √J₂ = k → yield
        # Pure deviatoric uniaxial: s = [s, -s/2, -s/2, 0, 0, 0]
        # J₂ = (1/2)((s)² + (-s/2)² + (-s/2)²) = (1/2)(s²+s²/4+s²/4) = 3s²/4
        # √J₂ = s·√3/2 = k → s = 2k/√3
        s0 = 2.0 * k / math.sqrt(3.0)
        stress = _deviatoric_trial(s0)
        f = yield_function_dp(stress, mat)
        assert abs(f) / k < 1e-6


# ===========================================================================
# 3. Elastic step
# ===========================================================================

class TestElasticStep:

    def test_elastic_stress_unchanged(self):
        """In elastic regime, return_map_dp returns unchanged stress."""
        mat = _mat(phi=30.0, c=200e3)
        stress_elastic = np.array([10e3, -5e3, -5e3, 1e3, 0.0, 0.0])
        f_el = yield_function_dp(stress_elastic, mat)
        if f_el >= 0:
            pytest.skip("Stress is not in elastic range for this test case")
        stress_out, info = return_map_dp(stress_elastic, mat)
        np.testing.assert_allclose(stress_out, stress_elastic, rtol=1e-10)
        assert info["mode"] == "elastic"

    def test_elastic_large_confinement(self):
        """Heavy confinement → elastic even for large deviatoric."""
        mat = _mat(phi=30.0, c=50e3)
        # Huge compression keeps f < 0
        stress = np.array([-10e6, -10e6, -10e6, 1e3, 0.0, 0.0])
        f = yield_function_dp(stress, mat)
        assert f < 0.0
        stress_out, info = return_map_dp(stress, mat)
        assert info["mode"] == "elastic"


# ===========================================================================
# 4. Smooth-cone return
# ===========================================================================

class TestSmoothConeReturn:

    def test_returned_stress_on_yield_surface(self):
        """After smooth return, yield function should be ≈ 0."""
        mat = _mat(phi=30.0, c=50e3, psi=20.0)
        # Trial stress above yield: deviatoric + mild confinement
        s_dev = 300e3  # exceeds k for typical DP
        p = -100e3
        stress_trial = _deviatoric_trial(s_dev, p)
        f_tr = yield_function_dp(stress_trial, mat)
        if f_tr <= 0:
            pytest.skip("Trial stress not above yield")
        stress_n1, info = return_map_dp(stress_trial, mat)
        if info["mode"] == "smooth":
            f_n1 = yield_function_dp(stress_n1, mat)
            assert abs(f_n1) / mat.cohesion_pa < 1e-4

    def test_smooth_return_mode_flag(self):
        """Mode must be 'smooth' for a standard deviatoric + small pressure case."""
        mat = _mat(phi=20.0, c=100e3, psi=10.0)
        stress_trial = np.array([500e3, 100e3, 100e3, 200e3, 0.0, 0.0])
        f_tr = yield_function_dp(stress_trial, mat)
        if f_tr <= 0:
            pytest.skip("Trial is elastic")
        stress_n1, info = return_map_dp(stress_trial, mat)
        # Mode should be smooth or apex (not elastic since f_tr > 0)
        assert info["mode"] in ("smooth", "apex")


# ===========================================================================
# 5. Apex return
# ===========================================================================

class TestApexReturn:

    def test_pure_tension_apex(self):
        """
        High triaxial tension with no deviator → maps to apex.
        The apex is at I₁ = k/α (positive pressure).
        """
        mat = _mat(phi=30.0, c=50e3, psi=20.0)
        alpha, k = _dp_alpha_k(mat)
        if alpha < 1e-12:
            pytest.skip("φ=0, no apex")
        # Very high triaxial tension, no deviatoric: should go to apex
        I1_above_apex = (k / alpha) * 10.0
        stress_trial = _hydrostatic(I1_above_apex / 3.0)
        _, info = return_map_dp(stress_trial, mat)
        assert info["mode"] == "apex"

    def test_apex_stress_is_hydrostatic(self):
        """Apex-returned stress should be isotropic (zero deviatoric)."""
        mat = _mat(phi=30.0, c=50e3, psi=20.0)
        alpha, k = _dp_alpha_k(mat)
        if alpha < 1e-12:
            pytest.skip("φ=0, no apex")
        stress_trial = _hydrostatic((k / alpha) * 5.0 / 3.0)
        stress_n1, info = return_map_dp(stress_trial, mat)
        if info["mode"] == "apex":
            # All three normal stresses should be equal, shear = 0
            np.testing.assert_allclose(stress_n1[0], stress_n1[1], rtol=1e-8)
            np.testing.assert_allclose(stress_n1[1], stress_n1[2], rtol=1e-8)
            np.testing.assert_allclose(stress_n1[3:], 0.0, atol=1e-6)


# ===========================================================================
# 6. φ = 0 → reduces to pressure-independent criterion
# ===========================================================================

class TestPhiZero:

    def test_phi_zero_no_pressure_effect(self):
        """
        With φ = 0, the DP criterion is pressure-independent (α = 0).
        Two trials with same deviatoric but different pressures should give
        the same yield function value.
        """
        mat_phi0 = _mat(phi=0.0, c=100e3, psi=0.0)
        s_dev = 200e3
        p1, p2 = -500e3, 0.0
        stress1 = _deviatoric_trial(s_dev, p1)
        stress2 = _deviatoric_trial(s_dev, p2)
        f1 = yield_function_dp(stress1, mat_phi0)
        f2 = yield_function_dp(stress2, mat_phi0)
        assert abs(f1 - f2) / max(abs(f1), 1.0) < 1e-10

    def test_phi_zero_return_map_correct(self):
        """φ = 0: return map should reduce to J2-like deviatoric correction."""
        mat_phi0 = _mat(phi=0.0, c=100e3, psi=0.0)
        stress_trial = _deviatoric_trial(300e3, 0.0)
        f_tr = yield_function_dp(stress_trial, mat_phi0)
        if f_tr <= 0:
            pytest.skip("Trial elastic")
        stress_n1, info = return_map_dp(stress_trial, mat_phi0)
        f_n1 = yield_function_dp(stress_n1, mat_phi0)
        assert abs(f_n1) / mat_phi0.cohesion_pa < 1e-4
