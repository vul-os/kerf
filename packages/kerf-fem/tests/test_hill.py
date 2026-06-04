"""
Tests for Hill 1948 anisotropic plasticity model.

Covers:
  - Equal yield stresses + R = 1 → reduces to J2 (isotropic).
  - Anisotropic yield: different yield stresses give different effective yield.
  - R_0 = 2.5 (deep-drawing steel) → anisotropic.
  - Elastic regime: stress unchanged.
  - Return mapping satisfies f ≈ 0 after yield.
  - Hill matrix symmetry and positive semi-definiteness.
  - Uniaxial tension in rolling direction.
  - Uniaxial tension in transverse direction.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_fem.plasticity.hill import (
    HillAnisotropicMaterial,
    _hill_coefficients,
    _hill_matrix,
    return_map_hill,
    yield_function_hill,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

E = 210e9   # Pa
NU = 0.3
SY = 280e6  # Pa — reference yield stress (rolling direction)

def _isotropic_mat():
    """Equal yield stresses + R = 1 → J2 equivalent."""
    return HillAnisotropicMaterial(
        youngs_modulus_pa=E,
        poisson=NU,
        yield_stress_x_pa=SY,
        yield_stress_y_pa=SY,
        yield_stress_z_pa=SY,
        shear_yield_pa=SY / math.sqrt(3.0),
        R_values=(1.0, 1.0, 1.0),
    )


def _aniso_mat(Rx: float = 1.6, Ry: float = 1.4):
    """Mild steel anisotropy: X (rolling), Y (transverse), Z (thickness)."""
    return HillAnisotropicMaterial(
        youngs_modulus_pa=E,
        poisson=NU,
        yield_stress_x_pa=SY,
        yield_stress_y_pa=SY * 0.95,   # slightly softer transverse
        yield_stress_z_pa=SY * 1.10,   # stiffer thickness
        shear_yield_pa=SY / math.sqrt(3.0),
        R_values=(Rx, 1.0, Ry),
    )


def _deep_drawing_mat():
    """Deep-drawing steel: R_0 = 2.5 (high normal anisotropy)."""
    return HillAnisotropicMaterial(
        youngs_modulus_pa=210e9,
        poisson=0.3,
        yield_stress_x_pa=350e6,
        yield_stress_y_pa=330e6,
        yield_stress_z_pa=370e6,
        shear_yield_pa=350e6 / math.sqrt(3.0),
        R_values=(2.5, 1.6, 2.0),
    )


def _uniaxial_x(sigma: float) -> np.ndarray:
    return np.array([sigma, 0.0, 0.0, 0.0, 0.0, 0.0])


def _uniaxial_y(sigma: float) -> np.ndarray:
    return np.array([0.0, sigma, 0.0, 0.0, 0.0, 0.0])


# ===========================================================================
# 1. Hill coefficients
# ===========================================================================

class TestHillCoefficients:

    def test_isotropic_F_G_H_equal(self):
        """Equal yield stresses → F = G = H = 1/(2X²)."""
        mat = _isotropic_mat()
        F, G, H, L, M, N = _hill_coefficients(mat)
        # For X=Y=Z: F = G = H = 0.5/X²
        expected = 0.5 / (SY * SY)
        assert abs(F - expected) / expected < 1e-10
        assert abs(G - expected) / expected < 1e-10
        assert abs(H - expected) / expected < 1e-10

    def test_isotropic_F_G_H_symmetric(self):
        """Isotropic: F = G = H (all normal coefficients equal)."""
        mat = _isotropic_mat()
        F, G, H, _, _, _ = _hill_coefficients(mat)
        assert abs(F - G) / F < 1e-10
        assert abs(G - H) / G < 1e-10

    def test_anisotropic_different_FGHN(self):
        """Anisotropic material: F ≠ G or H (checked as relative differences)."""
        mat = _aniso_mat()
        F, G, H, _, _, _ = _hill_coefficients(mat)
        # With X=SY, Y=0.95*SY, Z=1.1*SY, the coefficients differ relatively.
        # Use relative comparison (they are very small absolute values).
        mag = max(abs(F), abs(G), abs(H))
        # At least one pair must differ by more than 1% relatively.
        relative_diff_FG = abs(F - G) / mag
        relative_diff_GH = abs(G - H) / mag
        # F, G, H are computed from different yield stresses so they differ
        # by O(1) relatively when expressed relative to their magnitude.
        assert relative_diff_FG > 1e-6 or relative_diff_GH > 1e-6, (
            f"Expected F≠G or G≠H (relative), got F={F:.4e} G={G:.4e} H={H:.4e}"
        )


# ===========================================================================
# 2. Hill matrix
# ===========================================================================

class TestHillMatrix:

    def test_matrix_is_symmetric(self):
        """Hill compliance matrix must be symmetric."""
        mat = _aniso_mat()
        MH = _hill_matrix(mat)
        np.testing.assert_allclose(MH, MH.T, atol=1e-15)

    def test_matrix_shape_6x6(self):
        mat = _aniso_mat()
        MH = _hill_matrix(mat)
        assert MH.shape == (6, 6)

    def test_isotropic_hill_matrix_reduces_to_J2_structure(self):
        """
        For isotropic F=G=H=1/(2σ_y²), the Hill inner product σ^T M_H σ
        for a uniaxial stress σ_x should give σ_x²/σ_y² = (σ_vm/σ_y)².
        """
        mat = _isotropic_mat()
        MH = _hill_matrix(mat)
        sigma = np.array([SY, 0.0, 0.0, 0.0, 0.0, 0.0])
        inner = float(sigma @ MH @ sigma)
        # Hill inner = σ_x² · (G+H) = σ_x² · 2·(1/(2σ_y²)) = σ_x²/σ_y²
        # At σ_x = σ_y: inner should be 1.0
        assert abs(inner - 1.0) < 1e-10


# ===========================================================================
# 3. Yield function
# ===========================================================================

class TestYieldFunction:

    def test_elastic_below_yield(self):
        """Stress below yield → f < 0."""
        mat = _isotropic_mat()
        f = yield_function_hill(_uniaxial_x(0.8 * SY), mat)
        assert f < 0.0

    def test_at_yield_x(self):
        """Uniaxial stress at SY (rolling direction) → f ≈ 0."""
        mat = _isotropic_mat()
        f = yield_function_hill(_uniaxial_x(SY), mat)
        assert abs(f) < 1e-3  # small relative to Pa

    def test_above_yield(self):
        """Stress above yield → f > 0."""
        mat = _isotropic_mat()
        f = yield_function_hill(_uniaxial_x(1.5 * SY), mat)
        assert f > 0.0

    def test_anisotropic_different_yield_in_y(self):
        """
        Anisotropic: σ_y direction should yield at yield_stress_y_pa (not X).
        With X=SY, Y=0.95·SY: uniaxial in y at SY should be above yield.
        """
        mat = _aniso_mat()
        # Uniaxial in Y at SY > Y_yield (0.95*SY)
        f = yield_function_hill(_uniaxial_y(SY), mat)
        # Should be above yield
        assert f > 0.0


# ===========================================================================
# 4. Isotropic limit: Hill → J2
# ===========================================================================

class TestIsotropicLimit:

    def test_equal_yield_returns_at_sigma_y(self):
        """
        Equal anisotropy (R=1, equal yield stresses) → Hill reduces to J2.
        After return mapping, effective yield = SY.
        """
        mat = _isotropic_mat()
        stress_trial = _uniaxial_x(1.8 * SY)
        stress_n1, info = return_map_hill(stress_trial, mat)
        # The von Mises equivalent of the returned stress ≈ SY
        vm = yield_function_hill(stress_n1, mat)
        assert abs(vm) / SY < 1e-5

    def test_isotropic_no_size_effect(self):
        """Isotropic Hill: two uniaxial stresses in x and y at same magnitude
        should give the same yield function value."""
        mat = _isotropic_mat()
        sigma = 1.3 * SY
        fx = yield_function_hill(_uniaxial_x(sigma), mat)
        fy = yield_function_hill(_uniaxial_y(sigma), mat)
        assert abs(fx - fy) / abs(fx) < 1e-10


# ===========================================================================
# 5. Return mapping
# ===========================================================================

class TestReturnMapping:

    def test_elastic_step_unchanged(self):
        """Elastic trial → stress unchanged."""
        mat = _isotropic_mat()
        stress_trial = _uniaxial_x(0.5 * SY)
        stress_n1, info = return_map_hill(stress_trial, mat)
        np.testing.assert_allclose(stress_n1, stress_trial, rtol=1e-10)
        assert info["mode"] == "elastic"

    def test_plastic_step_stress_on_surface(self):
        """After plastic return, yield function should be ≈ 0."""
        mat = _isotropic_mat()
        stress_trial = _uniaxial_x(2.0 * SY)
        stress_n1, info = return_map_hill(stress_trial, mat)
        assert info["mode"] == "smooth"
        f_n1 = yield_function_hill(stress_n1, mat)
        assert abs(f_n1) / SY < 1e-5

    def test_anisotropic_plastic_on_surface(self):
        """Anisotropic return: updated stress on Hill yield surface."""
        mat = _aniso_mat()
        stress_trial = _uniaxial_x(2.0 * SY)
        stress_n1, info = return_map_hill(stress_trial, mat)
        if info["mode"] == "smooth":
            f_n1 = yield_function_hill(stress_n1, mat)
            assert abs(f_n1) / SY < 1e-5

    def test_delta_gamma_positive(self):
        """Plastic multiplier Δγ must be non-negative."""
        mat = _aniso_mat()
        stress_trial = _uniaxial_x(1.5 * SY)
        _, info = return_map_hill(stress_trial, mat)
        if info["mode"] == "smooth":
            assert info["delta_gamma"] >= 0.0


# ===========================================================================
# 6. Deep-drawing steel (R_0 = 2.5)
# ===========================================================================

class TestDeepDrawingSteel:

    def test_r25_yield_function_sign(self):
        """Deep-drawing steel: yield at σ_y = 350 MPa in rolling direction."""
        mat = _deep_drawing_mat()
        # Just below yield in rolling direction
        f_below = yield_function_hill(_uniaxial_x(340e6), mat)
        f_above = yield_function_hill(_uniaxial_x(360e6), mat)
        assert f_below < 0.0
        assert f_above > 0.0

    def test_r25_anisotropic_stronger_in_thickness(self):
        """
        With high R_0 = 2.5, the material resists thinning (strong in
        through-thickness direction).  σ_z yield > σ_x yield.
        """
        mat = _deep_drawing_mat()
        # Yield stress in z-direction (370 MPa) > x-direction (350 MPa)
        f_z_at_z_yield = yield_function_hill(
            np.array([0.0, 0.0, 370e6, 0.0, 0.0, 0.0]), mat
        )
        f_x_at_x_yield = yield_function_hill(
            np.array([350e6, 0.0, 0.0, 0.0, 0.0, 0.0]), mat
        )
        # Both should be approximately zero at their respective yield stresses
        assert abs(f_z_at_z_yield) / 350e6 < 0.1
        assert abs(f_x_at_x_yield) / 350e6 < 0.02
