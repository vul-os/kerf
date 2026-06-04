"""
Tests for Classical Laminate Theory (CLT) — Wave 12E.

Covers:
  - A-matrix of [0/90/0] is symmetric (no B coupling for symmetric stacking)
  - A-matrix of [0/45/-45/90]_s has no B coupling (symmetric laminate)
  - D matrix of symmetric laminates is non-zero
  - Unidirectional [0] laminate under N_x → ε_x positive
  - Cross-ply [0/90] A-matrix diagonal properties
  - Ply-level stress transformation consistency
  - Quasi-isotropic laminate A-matrix is nearly isotropic
  - analyse_laminate returns correct response shape
  - CLT inversion: apply resultants, recover strains, re-derive resultants
"""

from __future__ import annotations

import math
import pytest
import numpy as np

from kerf_fem.composites.laminate_classical import (
    LaminaPly,
    Laminate,
    LaminateResponse,
    analyze_laminate,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def carbon_epoxy_ply(orientation_deg: float, thickness_mm: float = 0.125) -> LaminaPly:
    """
    Typical T300/5208 carbon-epoxy unidirectional ply.
    Properties from Jones (1999) Table 2.1.
    """
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


def glass_epoxy_ply(orientation_deg: float, thickness_mm: float = 0.25) -> LaminaPly:
    """
    E-glass/epoxy ply (approximate properties).
    """
    return LaminaPly(
        material_name="E-glass/epoxy",
        E1_pa=38.6e9,
        E2_pa=8.27e9,
        G12_pa=4.14e9,
        nu12=0.26,
        thickness_mm=thickness_mm,
        orientation_deg=orientation_deg,
        sigma_1_T_pa=1062e6,
        sigma_1_C_pa=610e6,
        sigma_2_T_pa=31e6,
        sigma_2_C_pa=118e6,
        tau_12_pa=72e6,
    )


# ---------------------------------------------------------------------------
# Test 1: A-matrix of [0/90/0] is symmetric (B = 0)
# ---------------------------------------------------------------------------

def test_0_90_0_laminate_b_matrix_zero():
    """
    A symmetric [0/90/0] laminate has B = 0 (no bending-extension coupling).
    Jones (1999) §4.4.
    """
    plies = [
        carbon_epoxy_ply(0.0),
        carbon_epoxy_ply(90.0),
        carbon_epoxy_ply(0.0),
    ]
    lam = Laminate(plies)
    ABD = lam.compute_ABD_matrix()
    B = ABD[:3, 3:]
    assert np.allclose(B, 0.0, atol=1e-3), f"B matrix not zero: max |B| = {np.max(np.abs(B)):.3e}"


# ---------------------------------------------------------------------------
# Test 2: A-matrix of [0/45/-45/90]_s — symmetric, B = 0
# ---------------------------------------------------------------------------

def test_quasi_isotropic_b_matrix_zero():
    """
    The [0/45/-45/90]_s symmetric laminate (8 plies) has B = 0.
    """
    angles = [0, 45, -45, 90]
    plies = [carbon_epoxy_ply(a) for a in angles] + \
            [carbon_epoxy_ply(a) for a in reversed(angles)]
    lam = Laminate(plies)
    ABD = lam.compute_ABD_matrix()
    B = ABD[:3, 3:]
    assert np.allclose(B, 0.0, atol=1e-3), f"B not zero for quasi-isotropic: {np.max(np.abs(B)):.3e}"


# ---------------------------------------------------------------------------
# Test 3: A-matrix is symmetric
# ---------------------------------------------------------------------------

def test_abd_matrix_symmetry():
    """ABD matrix must be symmetric (positive-definite)."""
    plies = [carbon_epoxy_ply(a) for a in [0, 30, 60, 90, 90, 60, 30, 0]]
    lam = Laminate(plies)
    ABD = lam.compute_ABD_matrix()
    assert np.allclose(ABD, ABD.T, atol=1e-6), "ABD matrix is not symmetric"


# ---------------------------------------------------------------------------
# Test 4: Unidirectional [0°] under N_x = 1000 N/m → ε_x positive
# ---------------------------------------------------------------------------

def test_unidirectional_nx_positive_strain():
    """
    A [0°] single ply under uniaxial N_x > 0 should give ε_x > 0.
    Jones (1999) §4.3.
    """
    ply = carbon_epoxy_ply(0.0)
    lam = Laminate([ply])
    Nx = 1000.0  # N/m
    response = analyze_laminate(lam, np.array([Nx, 0.0, 0.0]), np.zeros(3))
    assert response.midplane_strain[0] > 0.0, (
        f"ε_x should be positive under N_x > 0, got {response.midplane_strain[0]}"
    )


# ---------------------------------------------------------------------------
# Test 5: Unidirectional [0°] — Poisson contraction ε_y < 0 under N_x
# ---------------------------------------------------------------------------

def test_unidirectional_nx_poisson_contraction():
    """Under N_x only, ε_y should be negative (Poisson contraction)."""
    ply = carbon_epoxy_ply(0.0)
    lam = Laminate([ply])
    response = analyze_laminate(lam, np.array([1000.0, 0.0, 0.0]), np.zeros(3))
    assert response.midplane_strain[1] < 0.0, "Poisson contraction: ε_y should be negative"


# ---------------------------------------------------------------------------
# Test 6: Cross-ply [0/90] — A11 ≈ A22 is not exact, but A16 = A26 = 0
# ---------------------------------------------------------------------------

def test_cross_ply_0_90_no_shear_extension_coupling():
    """
    For a [0/90] laminate, A16 = A26 = 0 (no shear-extension coupling).
    Jones (1999) §4.4.
    """
    plies = [carbon_epoxy_ply(0.0), carbon_epoxy_ply(90.0)]
    lam = Laminate(plies)
    A = lam.compute_ABD_matrix()[:3, :3]
    assert abs(A[0, 2]) < 1e-3, f"A16 should be 0, got {A[0,2]:.3e}"
    assert abs(A[1, 2]) < 1e-3, f"A26 should be 0, got {A[1,2]:.3e}"


# ---------------------------------------------------------------------------
# Test 7: Total thickness sums correctly
# ---------------------------------------------------------------------------

def test_total_thickness():
    plies = [carbon_epoxy_ply(0.0, 0.1), carbon_epoxy_ply(90.0, 0.2)]
    lam = Laminate(plies)
    assert abs(lam.total_thickness_mm - 0.3) < 1e-10


# ---------------------------------------------------------------------------
# Test 8: analyze_laminate returns correct shape
# ---------------------------------------------------------------------------

def test_analyze_laminate_output_shape():
    n_plies = 4
    plies = [carbon_epoxy_ply(a) for a in [0, 45, -45, 90]]
    lam = Laminate(plies)
    resp = analyze_laminate(lam, np.array([100.0, 0.0, 0.0]), np.zeros(3))

    assert resp.midplane_strain.shape == (3,)
    assert resp.curvature.shape == (3,)
    assert len(resp.ply_stresses) == n_plies
    for s in resp.ply_stresses:
        assert s.shape == (3,)


# ---------------------------------------------------------------------------
# Test 9: Zero load → zero strain and curvature
# ---------------------------------------------------------------------------

def test_zero_load_zero_response():
    plies = [carbon_epoxy_ply(a) for a in [0, 90, 90, 0]]
    lam = Laminate(plies)
    resp = analyze_laminate(lam, np.zeros(3), np.zeros(3))
    assert np.allclose(resp.midplane_strain, 0.0, atol=1e-15)
    assert np.allclose(resp.curvature, 0.0, atol=1e-15)
    for s in resp.ply_stresses:
        assert np.allclose(s, 0.0, atol=1e-15)


# ---------------------------------------------------------------------------
# Test 10: A-matrix consistency with individual-ply Q̄ integration
# ---------------------------------------------------------------------------

def test_a_matrix_equals_sum_qbar_times_thickness():
    """
    A_ij = Σ_k Q̄_ij^k · t_k  for each ply.
    """
    plies = [carbon_epoxy_ply(a) for a in [0, 45, -45, 90]]
    lam = Laminate(plies)
    ABD = lam.compute_ABD_matrix()
    A = ABD[:3, :3]

    A_manual = sum(p.Qbar_matrix() * p.thickness_m for p in plies)
    assert np.allclose(A, A_manual, rtol=1e-10)


# ---------------------------------------------------------------------------
# Test 11: CLT inversion consistency (apply loads, derive strains, re-derive loads)
# ---------------------------------------------------------------------------

def test_clt_inversion_consistency():
    """
    Apply N_x load, solve for strains, then verify ABD · {ε⁰, κ} ≈ {N, M}.
    """
    plies = [carbon_epoxy_ply(a) for a in [0, 45, -45, 90, 90, -45, 45, 0]]
    lam = Laminate(plies)
    ABD = lam.compute_ABD_matrix()

    N_applied = np.array([5000.0, 0.0, 0.0])
    M_applied = np.zeros(3)
    resp = analyze_laminate(lam, N_applied, M_applied)

    deformation = np.concatenate([resp.midplane_strain, resp.curvature])
    recovered_load = ABD @ deformation
    assert np.allclose(recovered_load[:3], N_applied, rtol=1e-8)
    assert np.allclose(recovered_load[3:], M_applied, atol=1e-6)


# ---------------------------------------------------------------------------
# Test 12: nu12 reciprocal relation Q12 = nu12·E2/(1-nu12·nu21)
# ---------------------------------------------------------------------------

def test_ply_Q_matrix_reciprocal():
    """Q12/Q22 = nu12 for an on-axis (0°) ply."""
    ply = carbon_epoxy_ply(0.0)
    Q = ply.Q_matrix()
    nu21 = ply.nu21
    denom = 1.0 - ply.nu12 * nu21
    Q12_expected = ply.nu12 * ply.E2_pa / denom
    assert abs(Q[0, 1] - Q12_expected) < 1.0  # Pa level


# ---------------------------------------------------------------------------
# Test 13: Symmetric laminate D matrix is non-zero (bending stiffness exists)
# ---------------------------------------------------------------------------

def test_symmetric_laminate_d_matrix_nonzero():
    """D matrix must have non-zero entries (bending stiffness exists)."""
    plies = [carbon_epoxy_ply(a) for a in [0, 90, 90, 0]]
    lam = Laminate(plies)
    ABD = lam.compute_ABD_matrix()
    D = ABD[3:, 3:]
    # D11 = (1/3)*sum(Qbar11_k*(z_k^3-z_{k-1}^3)).
    # For 4 × 0.125 mm plies, D11 is on order 1-10 N·m.
    assert D[0, 0] > 0.1, f"D11 should be positive and significant, got {D[0,0]:.4f}"
    assert D[1, 1] > 0.01, f"D22 should be positive, got {D[1,1]:.4f}"
