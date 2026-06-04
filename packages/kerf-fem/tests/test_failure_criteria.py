"""
Tests for composite failure criteria — Wave 12E.

Covers:
  - tsai_wu: fails when σ_1 exceeds X_T
  - tsai_wu: safe for zero stress (FI near 0, SF = inf)
  - tsai_wu: F12 stability check
  - tsai_hill: fails at σ_1 = X_T
  - tsai_hill: bidirectional interaction reduces strength
  - maximum_stress: safe for zero stress (SF = inf)
  - maximum_stress: fails when σ_2 > Y_T
  - maximum_strain: fails when ε_1 > X_T/E1
  - puck: matrix failure mode for σ_2 > 0 loading
  - puck: fibre failure mode for σ_1 = X_T
  - hashin: fibre tension sub-criterion
  - hashin: matrix tension sub-criterion
  - hashin: matrix compression sub-criterion
  - first_ply_failure: [0/90/0] under N_x → 90° ply fails first
  - first_ply_failure: all criteria run without error
  - first_ply_failure: safety_factor < 1 when loads are very high
  - failure_index boundary: FI = 1.0 at exactly strength
"""

from __future__ import annotations

import math
import pytest
import numpy as np

from kerf_fem.composites.laminate_classical import (
    LaminaPly,
    Laminate,
    analyze_laminate,
)
from kerf_fem.composites.failure_criteria import (
    FailureResult,
    tsai_wu,
    tsai_hill,
    maximum_stress,
    maximum_strain,
    puck,
    hashin,
    first_ply_failure_analysis,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def carbon_ply(orientation_deg: float = 0.0, thickness_mm: float = 0.125) -> LaminaPly:
    """T300/5208 carbon-epoxy (Jones 1999, Table 2.1)."""
    return LaminaPly(
        material_name="T300/5208",
        E1_pa=181e9,
        E2_pa=10.3e9,
        G12_pa=7.17e9,
        nu12=0.28,
        thickness_mm=thickness_mm,
        orientation_deg=orientation_deg,
        sigma_1_T_pa=1500e6,
        sigma_1_C_pa=1500e6,
        sigma_2_T_pa=40e6,
        sigma_2_C_pa=246e6,
        tau_12_pa=68e6,
    )


def zero_stress():
    return np.array([0.0, 0.0, 0.0])


def stress_1T_only(ply: LaminaPly, factor: float = 1.0):
    """Pure σ_1 tension at factor × X_T."""
    return np.array([factor * ply.sigma_1_T_pa, 0.0, 0.0])


def stress_2T_only(ply: LaminaPly, factor: float = 1.0):
    """Pure σ_2 tension at factor × Y_T."""
    return np.array([0.0, factor * ply.sigma_2_T_pa, 0.0])


def stress_shear_only(ply: LaminaPly, factor: float = 1.0):
    """Pure τ_12 at factor × S."""
    return np.array([0.0, 0.0, factor * ply.tau_12_pa])


# ---------------------------------------------------------------------------
# Test 1: Tsai-Wu — fails when σ_1 = X_T (FI ≥ 1)
# ---------------------------------------------------------------------------

def test_tsai_wu_fails_at_fibre_tensile_strength():
    ply = carbon_ply()
    sigma = stress_1T_only(ply, factor=1.0)
    result = tsai_wu(sigma, ply)
    # At σ_1 = X_T, the Tsai-Wu criterion should indicate failure (FI ≥ 1)
    # FI = F1*X_T + F11*X_T² = (1/X_T - 1/X_C)*X_T + X_T²/(X_T*X_C)
    #    = (1 - X_T/X_C) + X_T/X_C = 1.0
    assert result.failure_index >= 0.99, f"Expected FI ≥ 1 at σ_1 = X_T, got {result.failure_index:.4f}"
    assert result.failed


# ---------------------------------------------------------------------------
# Test 2: Tsai-Wu — safe for zero stress
# ---------------------------------------------------------------------------

def test_tsai_wu_safe_for_zero_stress():
    ply = carbon_ply()
    result = tsai_wu(zero_stress(), ply)
    assert result.failure_index < 1e-10
    assert not result.failed
    assert math.isinf(result.safety_factor) or result.safety_factor > 1e6


# ---------------------------------------------------------------------------
# Test 3: Tsai-Wu — FI > 1 for σ_1 > X_T
# ---------------------------------------------------------------------------

def test_tsai_wu_fails_above_fibre_strength():
    ply = carbon_ply()
    sigma = stress_1T_only(ply, factor=2.0)
    result = tsai_wu(sigma, ply)
    assert result.failure_index > 1.0
    assert result.failed


# ---------------------------------------------------------------------------
# Test 4: Tsai-Wu — F12 stability check raises for out-of-range value
# ---------------------------------------------------------------------------

def test_tsai_wu_f12_stability_check():
    ply = carbon_ply()
    # Compute F11, F22 to derive a violation
    F11 = 1.0 / (ply.sigma_1_T_pa * ply.sigma_1_C_pa)
    F22 = 1.0 / (ply.sigma_2_T_pa * ply.sigma_2_C_pa)
    f12_bad = 2.0 * math.sqrt(F11 * F22)  # violates stability
    with pytest.raises(ValueError, match="stability"):
        tsai_wu(zero_stress(), ply, F12_interaction=f12_bad)


# ---------------------------------------------------------------------------
# Test 5: Tsai-Hill — fails when σ_1 = X_T
# ---------------------------------------------------------------------------

def test_tsai_hill_fails_at_fibre_tensile_strength():
    ply = carbon_ply()
    sigma = stress_1T_only(ply, factor=1.0)
    result = tsai_hill(sigma, ply)
    # At σ_1 = X_T, σ_2 = 0, τ_12 = 0:
    # FI = (X_T/X_T)² = 1.0
    assert abs(result.failure_index - 1.0) < 1e-6
    assert result.failed


# ---------------------------------------------------------------------------
# Test 6: Tsai-Hill — bidirectional interaction
# ---------------------------------------------------------------------------

def test_tsai_hill_interaction_term():
    """
    Under σ_1 = X_T/2 and σ_2 = Y_T:
    FI = (0.5)² - 0.5*σ_2/X_T + (σ_2/Y_T)² + 0
       = 0.25 - 0.5*(Y_T/X_T) + 1.0
    """
    ply = carbon_ply()
    s1 = 0.5 * ply.sigma_1_T_pa
    s2 = ply.sigma_2_T_pa
    sigma = np.array([s1, s2, 0.0])
    result = tsai_hill(sigma, ply)
    X = ply.sigma_1_T_pa  # s1 > 0
    Y = ply.sigma_2_T_pa  # s2 > 0
    expected = (s1/X)**2 - s1*s2/X**2 + (s2/Y)**2
    assert abs(result.failure_index - expected) < 1e-6


# ---------------------------------------------------------------------------
# Test 7: Maximum stress — safe for zero stress
# ---------------------------------------------------------------------------

def test_maximum_stress_safe_for_zero_stress():
    ply = carbon_ply()
    result = maximum_stress(zero_stress(), ply)
    assert result.failure_index < 1e-10
    assert not result.failed
    assert math.isinf(result.safety_factor) or result.safety_factor > 1e6


# ---------------------------------------------------------------------------
# Test 8: Maximum stress — fails when σ_2 > Y_T
# ---------------------------------------------------------------------------

def test_maximum_stress_fails_transverse_tension():
    ply = carbon_ply()
    sigma = stress_2T_only(ply, factor=1.5)
    result = maximum_stress(sigma, ply)
    assert result.failure_index > 1.0
    assert result.failed
    assert result.failed_mode == "matrix"


# ---------------------------------------------------------------------------
# Test 9: Maximum stress — shear failure mode
# ---------------------------------------------------------------------------

def test_maximum_stress_shear_failure():
    ply = carbon_ply()
    sigma = stress_shear_only(ply, factor=2.0)
    result = maximum_stress(sigma, ply)
    assert result.failed
    assert result.failed_mode == "shear"


# ---------------------------------------------------------------------------
# Test 10: Maximum strain — fails when ε_1 > X_T/E1
# ---------------------------------------------------------------------------

def test_maximum_strain_fails_at_fibre_failure_strain():
    ply = carbon_ply()
    eps_1_T = ply.sigma_1_T_pa / ply.E1_pa
    strain = np.array([1.5 * eps_1_T, 0.0, 0.0])
    result = maximum_strain(strain, ply)
    assert result.failure_index > 1.0
    assert result.failed
    assert result.failed_mode == "fibre"


# ---------------------------------------------------------------------------
# Test 11: Maximum strain — safe for zero strain
# ---------------------------------------------------------------------------

def test_maximum_strain_safe_for_zero_strain():
    ply = carbon_ply()
    result = maximum_strain(np.zeros(3), ply)
    assert result.failure_index < 1e-10
    assert not result.failed


# ---------------------------------------------------------------------------
# Test 12: Puck — matrix failure mode for tensile σ_2
# ---------------------------------------------------------------------------

def test_puck_matrix_mode_tensile_sigma2():
    ply = carbon_ply()
    sigma = stress_2T_only(ply, factor=1.5)
    result = puck(sigma, ply)
    assert result.failed
    assert result.failed_mode == "matrix"


# ---------------------------------------------------------------------------
# Test 13: Puck — fibre failure mode for large σ_1
# ---------------------------------------------------------------------------

def test_puck_fibre_mode_large_sigma1():
    ply = carbon_ply()
    sigma = stress_1T_only(ply, factor=1.5)
    result = puck(sigma, ply)
    assert result.failed
    assert result.failed_mode == "fibre"


# ---------------------------------------------------------------------------
# Test 14: Puck — safe for zero stress
# ---------------------------------------------------------------------------

def test_puck_safe_for_zero_stress():
    ply = carbon_ply()
    result = puck(zero_stress(), ply)
    assert not result.failed
    assert result.failure_index < 1.0


# ---------------------------------------------------------------------------
# Test 15: Hashin — fibre tension sub-criterion
# ---------------------------------------------------------------------------

def test_hashin_fibre_tension():
    ply = carbon_ply()
    # σ_1 = 1.2 X_T → fi_ft = 1.44 > 1
    sigma = stress_1T_only(ply, factor=1.2)
    result = hashin(sigma, ply)
    assert result.failed
    assert result.failed_mode == "fibre"


# ---------------------------------------------------------------------------
# Test 16: Hashin — matrix tension sub-criterion
# ---------------------------------------------------------------------------

def test_hashin_matrix_tension():
    ply = carbon_ply()
    # σ_2 = 1.5 Y_T (no σ_1 or τ)
    sigma = stress_2T_only(ply, factor=1.5)
    result = hashin(sigma, ply)
    assert result.failed
    assert result.failed_mode == "matrix"


# ---------------------------------------------------------------------------
# Test 17: Hashin — matrix compression sub-criterion
# ---------------------------------------------------------------------------

def test_hashin_matrix_compression():
    ply = carbon_ply()
    # σ_2 = -2·Y_C
    sigma = np.array([0.0, -2.0 * ply.sigma_2_C_pa, 0.0])
    result = hashin(sigma, ply)
    assert result.failure_index > 1.0
    assert result.failed


# ---------------------------------------------------------------------------
# Test 18: Hashin — safe for zero stress
# ---------------------------------------------------------------------------

def test_hashin_safe_for_zero_stress():
    ply = carbon_ply()
    result = hashin(zero_stress(), ply)
    assert not result.failed
    assert result.failure_index < 1e-10


# ---------------------------------------------------------------------------
# Test 19: All criteria produce a FailureResult with required fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("criterion_fn", [
    lambda s, p: tsai_wu(s, p),
    tsai_hill,
    maximum_stress,
    puck,
    hashin,
])
def test_all_criteria_return_failure_result(criterion_fn):
    ply = carbon_ply()
    sigma = np.array([100e6, 10e6, 5e6])
    result = criterion_fn(sigma, ply)
    assert isinstance(result, FailureResult)
    assert isinstance(result.failure_index, float)
    assert isinstance(result.failed, bool)
    assert isinstance(result.failed_mode, str)
    assert isinstance(result.safety_factor, float)
    assert result.safety_factor > 0


# ---------------------------------------------------------------------------
# Test 20: first_ply_failure — [0/90/0] under N_x → 90° ply fails first
# ---------------------------------------------------------------------------

def test_first_ply_failure_0_90_0_under_nx():
    """
    Under uniaxial N_x tension, the 90° ply (transverse direction) has
    σ_2 stress and fails first since Y_T << X_T.
    The first-failed ply index should correspond to the 90° ply (index 1).
    """
    plies = [
        carbon_ply(0.0),
        carbon_ply(90.0),
        carbon_ply(0.0),
    ]
    lam = Laminate(plies)

    # Apply moderate N_x: enough to fail 90° ply but not 0° plies
    # Y_T = 40 MPa for transverse; calibrate N_x accordingly
    # Use a large N_x that stresses the laminate significantly
    Nx = 20e3  # N/m — typical for this laminate

    response = analyze_laminate(lam, np.array([Nx, 0.0, 0.0]), np.zeros(3))
    fpf = first_ply_failure_analysis(lam, response, criterion="tsai_wu")

    # The 90° ply (index 1) should have the highest failure index
    # because σ_2 in the material frame is large for 90° ply under N_x
    fi_90 = fpf["ply_failure_indices"][1]
    fi_0_bot = fpf["ply_failure_indices"][0]
    fi_0_top = fpf["ply_failure_indices"][2]

    assert fi_90 > fi_0_bot, (
        f"90° ply FI ({fi_90:.4f}) should exceed 0° bottom ply FI ({fi_0_bot:.4f})"
    )
    assert fi_90 > fi_0_top, (
        f"90° ply FI ({fi_90:.4f}) should exceed 0° top ply FI ({fi_0_top:.4f})"
    )
    assert fpf["first_failed_ply_index"] == 1


# ---------------------------------------------------------------------------
# Test 21: first_ply_failure — all criteria run without error
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("criterion", [
    "tsai_wu", "tsai_hill", "maximum_stress", "hashin", "puck"
])
def test_first_ply_failure_all_criteria(criterion):
    plies = [carbon_ply(a) for a in [0, 45, -45, 90]]
    lam = Laminate(plies)
    response = analyze_laminate(lam, np.array([5000.0, 0.0, 0.0]), np.zeros(3))
    fpf = first_ply_failure_analysis(lam, response, criterion=criterion)
    assert "first_failed_ply_index" in fpf
    assert "safety_factor_to_first_ply_failure" in fpf
    assert len(fpf["ply_failure_indices"]) == 4


# ---------------------------------------------------------------------------
# Test 22: first_ply_failure — returns correct structure
# ---------------------------------------------------------------------------

def test_first_ply_failure_result_structure():
    plies = [carbon_ply(0.0), carbon_ply(90.0)]
    lam = Laminate(plies)
    response = analyze_laminate(lam, np.array([1000.0, 0.0, 0.0]), np.zeros(3))
    fpf = first_ply_failure_analysis(lam, response)
    assert fpf["criterion"] == "tsai_wu"
    assert 0 <= fpf["first_failed_ply_index"] < 2
    assert fpf["safety_factor_to_first_ply_failure"] > 0
    assert len(fpf["ply_results"]) == 2


# ---------------------------------------------------------------------------
# Test 23: Maximum stress — FI = 1 exactly at strength
# ---------------------------------------------------------------------------

def test_maximum_stress_fi_equals_one_at_strength():
    ply = carbon_ply()
    sigma = np.array([ply.sigma_1_T_pa, 0.0, 0.0])
    result = maximum_stress(sigma, ply)
    assert abs(result.failure_index - 1.0) < 1e-10
    assert result.failed


# ---------------------------------------------------------------------------
# Test 24: Safety factor = 1/FI
# ---------------------------------------------------------------------------

def test_safety_factor_is_inverse_fi():
    ply = carbon_ply()
    sigma = np.array([0.5 * ply.sigma_1_T_pa, 0.0, 0.0])
    result = maximum_stress(sigma, ply)
    assert abs(result.safety_factor - 1.0 / result.failure_index) < 1e-10


# ---------------------------------------------------------------------------
# Test 25: Tsai-Wu under pure shear — FI = (τ/S)²
# ---------------------------------------------------------------------------

def test_tsai_wu_pure_shear():
    """Under pure τ_12, Tsai-Wu reduces to FI = (τ_12/S)² (no linear shear term)."""
    ply = carbon_ply()
    t12 = 0.5 * ply.tau_12_pa
    sigma = np.array([0.0, 0.0, t12])
    result = tsai_wu(sigma, ply)
    expected_fi = (t12 / ply.tau_12_pa) ** 2
    assert abs(result.failure_index - expected_fi) < 1e-10


# ---------------------------------------------------------------------------
# Test 26: first_ply_failure — unknown criterion raises ValueError
# ---------------------------------------------------------------------------

def test_first_ply_failure_unknown_criterion():
    plies = [carbon_ply(0.0)]
    lam = Laminate(plies)
    response = analyze_laminate(lam, np.array([100.0, 0.0, 0.0]), np.zeros(3))
    with pytest.raises(ValueError, match="Unknown criterion"):
        first_ply_failure_analysis(lam, response, criterion="imaginary_criterion")
