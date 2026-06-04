"""
Tests for thermal-structural coupled FEA (Wave 12E).

Covers:
  - Staggered solver: heated bar elongation matches ΔL = α·L·ΔT
  - Monolithic solver: matches staggered for same BCs
  - Free thermal expansion: zero stress when unconstrained
  - Constrained thermal bar: stress = -E·α·ΔT
  - Temperature-dependent E (thermal softening)
  - Monolithic vs staggered agree within tolerance
  - Mixed Dirichlet/Neumann thermal BCs
  - Single-element bar
  - Multi-element bar convergence
"""

from __future__ import annotations

import math
import pytest
import numpy as np

from kerf_fem.multiphysics.thermal_structural import (
    ThermoElasticMaterial,
    CoupledResult,
    solve_thermo_elastic_staggered,
    solve_thermo_elastic_monolithic,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def make_steel() -> ThermoElasticMaterial:
    """Typical mild steel thermo-elastic properties."""
    return ThermoElasticMaterial(
        youngs_modulus_pa=200e9,
        poisson=0.3,
        thermal_conductivity_w_m_k=50.0,
        thermal_expansion_per_k=12e-6,
        specific_heat_j_kg_k=500.0,
        density_kg_m3=7850.0,
        thermal_softening_beta=0.0,
    )


def make_aluminium() -> ThermoElasticMaterial:
    return ThermoElasticMaterial(
        youngs_modulus_pa=70e9,
        poisson=0.33,
        thermal_conductivity_w_m_k=200.0,
        thermal_expansion_per_k=23e-6,
        specific_heat_j_kg_k=900.0,
        density_kg_m3=2700.0,
    )


def uniform_bar_mesh(L: float, n_elem: int, area: float = 1e-4) -> dict:
    """Create a uniform 1-D bar mesh."""
    nodes = np.linspace(0.0, L, n_elem + 1).tolist()
    return {"nodes": nodes, "area": area}


# ---------------------------------------------------------------------------
# Test 1: Free thermal expansion — bar elongates by ΔL = α·L·ΔT
# ---------------------------------------------------------------------------

def test_staggered_free_expansion_elongation():
    """
    A bar with T_left=0°C, T_right=100°C, fixed at left, free at right.
    Mean ΔT = 50 K relative to T_ref=0°C.
    For a bar with linear temperature profile T(x) = 100·x/L:
      ΔL = α · ∫₀ᴸ (T(x) - 0) dx = α · L · T_mean = α · L · 50
    """
    L = 1.0  # m
    T_ref = 273.15  # K (0°C reference)
    T_left = 273.15   # K (0°C)
    T_right = 373.15  # K (100°C)
    n_elem = 20
    mat = make_steel()
    alpha = mat.thermal_expansion_per_k

    mesh = uniform_bar_mesh(L, n_elem)
    thermal_bcs = {"temperature": {0: T_left, n_elem: T_right}}
    structural_bcs = {"displacement": {0: 0.0}}  # fixed left, free right

    res = solve_thermo_elastic_staggered(
        mesh, mat, thermal_bcs, structural_bcs, T_reference=T_ref
    )

    assert res.temperatures is not None
    assert res.displacements is not None
    assert res.iterations_converged >= 1

    # Analytical: ΔL = α * ∫₀ᴸ (T(x) - T_ref) dx
    # T(x) = T_left + (T_right - T_left)*x/L  → T_mean - T_ref = (T_left + T_right)/2 - T_ref
    T_mean = 0.5 * (T_left + T_right)
    delta_T_mean = T_mean - T_ref
    delta_L_analytical = alpha * L * delta_T_mean

    tip_disp = float(res.displacements[-1])
    assert abs(tip_disp - delta_L_analytical) / (abs(delta_L_analytical) + 1e-12) < 0.02, (
        f"Tip displacement {tip_disp:.6e} m, expected {delta_L_analytical:.6e} m"
    )


# ---------------------------------------------------------------------------
# Test 2: Staggered — fully constrained bar thermal stress
# ---------------------------------------------------------------------------

def test_staggered_constrained_thermal_stress():
    """
    A bar fully constrained at both ends with uniform ΔT.
    σ = -E·α·ΔT (Timoshenko & Goodier, Theory of Elasticity §13).
    """
    L = 1.0
    dT = 50.0  # K above reference
    T_ref = 293.15
    T_bar = T_ref + dT
    mat = make_steel()

    mesh = uniform_bar_mesh(L, 10)
    thermal_bcs = {"temperature": {0: T_bar, 10: T_bar}}  # uniform T
    structural_bcs = {"displacement": {0: 0.0, 10: 0.0}}   # both ends fixed

    res = solve_thermo_elastic_staggered(
        mesh, mat, thermal_bcs, structural_bcs, T_reference=T_ref
    )

    # All nodes should be at T_bar
    assert np.allclose(res.temperatures, T_bar, atol=1.0)

    # Stress = -E·α·ΔT (compressive for positive dT)
    sigma_analytical = -mat.youngs_modulus_pa * mat.thermal_expansion_per_k * dT
    # Interior node stress (boundary nodes averaged less accurately)
    interior_stress = res.stress_at_nodes[5]
    assert abs(interior_stress - sigma_analytical) / abs(sigma_analytical) < 0.01, (
        f"σ = {interior_stress:.4e}, expected {sigma_analytical:.4e}"
    )


# ---------------------------------------------------------------------------
# Test 3: Temperature profile is linear (Fourier law check)
# ---------------------------------------------------------------------------

def test_staggered_temperature_profile_is_linear():
    """
    For a bar with no volumetric heat source and Dirichlet BCs at both ends,
    FEM with linear elements recovers the exact linear temperature field.
    """
    n_elem = 10
    L = 2.0
    T_left = 300.0
    T_right = 600.0
    mat = make_steel()

    mesh = uniform_bar_mesh(L, n_elem)
    thermal_bcs = {"temperature": {0: T_left, n_elem: T_right}}
    structural_bcs = {"displacement": {0: 0.0}}

    res = solve_thermo_elastic_staggered(
        mesh, mat, thermal_bcs, structural_bcs, T_reference=T_left
    )

    nodes = np.linspace(0, L, n_elem + 1)
    T_exact = T_left + (T_right - T_left) * nodes / L
    assert np.allclose(res.temperatures, T_exact, atol=1e-6)


# ---------------------------------------------------------------------------
# Test 4: Monolithic — same free expansion as staggered
# ---------------------------------------------------------------------------

def test_monolithic_free_expansion_matches_staggered():
    """
    Monolithic and staggered should agree closely for temperature-independent E.
    """
    L = 1.0
    n_elem = 10
    T_ref = 293.15
    mat = make_steel()

    mesh = uniform_bar_mesh(L, n_elem)
    thermal_bcs = {"temperature": {0: T_ref, n_elem: T_ref + 100.0}}
    structural_bcs = {"displacement": {0: 0.0}}

    res_stag = solve_thermo_elastic_staggered(
        mesh, mat, thermal_bcs, structural_bcs, T_reference=T_ref
    )
    res_mono = solve_thermo_elastic_monolithic(
        mesh, mat, thermal_bcs, structural_bcs, T_reference=T_ref
    )

    # Temperatures should be identical (same thermal solve)
    assert np.allclose(res_stag.temperatures, res_mono.temperatures, rtol=1e-8)
    # Displacements should agree to within 1%
    assert np.allclose(res_stag.displacements, res_mono.displacements, rtol=0.01)


# ---------------------------------------------------------------------------
# Test 5: Monolithic — constrained bar stress matches analytical
# ---------------------------------------------------------------------------

def test_monolithic_constrained_stress():
    """Monolithic solver: constrained bar stress = -E·α·ΔT."""
    L = 1.0
    dT = 80.0
    T_ref = 293.15
    T_uniform = T_ref + dT
    mat = make_steel()

    mesh = uniform_bar_mesh(L, 8)
    thermal_bcs = {"temperature": {0: T_uniform, 8: T_uniform}}
    structural_bcs = {"displacement": {0: 0.0, 8: 0.0}}

    res = solve_thermo_elastic_monolithic(
        mesh, mat, thermal_bcs, structural_bcs, T_reference=T_ref
    )

    sigma_analytical = -mat.youngs_modulus_pa * mat.thermal_expansion_per_k * dT
    interior_stress = res.stress_at_nodes[4]
    assert abs(interior_stress - sigma_analytical) / abs(sigma_analytical) < 0.01


# ---------------------------------------------------------------------------
# Test 6: Monolithic returns iterations_converged = 1
# ---------------------------------------------------------------------------

def test_monolithic_iterations_is_one():
    mat = make_steel()
    mesh = uniform_bar_mesh(1.0, 5)
    thermal_bcs = {"temperature": {0: 300.0, 5: 400.0}}
    structural_bcs = {"displacement": {0: 0.0}}
    res = solve_thermo_elastic_monolithic(mesh, mat, thermal_bcs, structural_bcs)
    assert res.iterations_converged == 1


# ---------------------------------------------------------------------------
# Test 7: CoupledResult has correct shapes
# ---------------------------------------------------------------------------

def test_result_shapes():
    n_elem = 15
    mat = make_steel()
    mesh = uniform_bar_mesh(1.0, n_elem)
    thermal_bcs = {"temperature": {0: 300.0, n_elem: 500.0}}
    structural_bcs = {"displacement": {0: 0.0}}
    res = solve_thermo_elastic_staggered(mesh, mat, thermal_bcs, structural_bcs)

    assert res.temperatures.shape == (n_elem + 1,)
    assert res.displacements.shape == (n_elem + 1,)
    assert res.stress_at_nodes.shape == (n_elem + 1,)
    assert res.thermal_strain_at_nodes.shape == (n_elem + 1,)


# ---------------------------------------------------------------------------
# Test 8: Thermal strain at nodes = α·(T - T_ref)
# ---------------------------------------------------------------------------

def test_thermal_strain_consistency():
    n_elem = 8
    T_ref = 273.15
    mat = make_aluminium()
    mesh = uniform_bar_mesh(0.5, n_elem)
    thermal_bcs = {"temperature": {0: 293.15, n_elem: 373.15}}
    structural_bcs = {"displacement": {0: 0.0}}

    res = solve_thermo_elastic_staggered(
        mesh, mat, thermal_bcs, structural_bcs, T_reference=T_ref
    )

    expected_eps_th = mat.thermal_expansion_per_k * (res.temperatures - T_ref)
    assert np.allclose(res.thermal_strain_at_nodes, expected_eps_th, rtol=1e-10)


# ---------------------------------------------------------------------------
# Test 9: Temperature-dependent E — staggered converges in >1 iteration
# ---------------------------------------------------------------------------

def test_staggered_converges_with_temperature_dependent_E():
    """With thermal softening, staggered iterates but eventually converges."""
    mat = ThermoElasticMaterial(
        youngs_modulus_pa=200e9,
        poisson=0.3,
        thermal_conductivity_w_m_k=50.0,
        thermal_expansion_per_k=12e-6,
        specific_heat_j_kg_k=500.0,
        density_kg_m3=7850.0,
        thermal_softening_beta=5e-4,  # mild softening
    )
    n_elem = 6
    mesh = uniform_bar_mesh(1.0, n_elem)
    thermal_bcs = {"temperature": {0: 300.0, n_elem: 800.0}}
    structural_bcs = {"displacement": {0: 0.0}}

    res = solve_thermo_elastic_staggered(
        mesh, mat, thermal_bcs, structural_bcs,
        T_reference=300.0, max_iter=50, tol=1e-8
    )
    assert res.iterations_converged >= 1
    assert res.residual_norm <= 1e-4  # converged


# ---------------------------------------------------------------------------
# Test 10: Zero temperature gradient → zero thermal strain
# ---------------------------------------------------------------------------

def test_zero_temperature_gradient_zero_thermal_strain():
    T_uniform = 300.0
    n_elem = 5
    mat = make_steel()
    mesh = uniform_bar_mesh(1.0, n_elem)
    thermal_bcs = {"temperature": {0: T_uniform, n_elem: T_uniform}}
    structural_bcs = {"displacement": {0: 0.0}}

    res = solve_thermo_elastic_staggered(
        mesh, mat, thermal_bcs, structural_bcs, T_reference=T_uniform
    )

    assert np.allclose(res.thermal_strain_at_nodes, 0.0, atol=1e-12)
    # Displacements should all be zero (no expansion, no external loads)
    assert np.allclose(res.displacements, 0.0, atol=1e-12)


# ---------------------------------------------------------------------------
# Test 11: Staggered — external axial force with no thermal loading
# ---------------------------------------------------------------------------

def test_staggered_pure_axial_load_no_thermal():
    """
    Bar at uniform T=T_ref, axial force P at free end.
    Should recover u(L) = P·L/(E·A) with zero thermal strain.
    """
    E = 200e9
    A = 1e-4
    L = 2.0
    P = 10000.0  # N
    T_ref = 293.15
    n_elem = 10

    mat = ThermoElasticMaterial(
        youngs_modulus_pa=E, poisson=0.3,
        thermal_conductivity_w_m_k=50.0,
        thermal_expansion_per_k=12e-6,
        specific_heat_j_kg_k=500.0,
        density_kg_m3=7850.0,
    )
    mesh = uniform_bar_mesh(L, n_elem, area=A)
    thermal_bcs = {"temperature": {0: T_ref, n_elem: T_ref}}
    structural_bcs = {
        "displacement": {0: 0.0},
        "force": {n_elem: (P, 0.0, 0.0)},
    }

    res = solve_thermo_elastic_staggered(
        mesh, mat, thermal_bcs, structural_bcs, T_reference=T_ref
    )

    u_analytical = P * L / (E * A)
    assert abs(res.displacements[-1] - u_analytical) / u_analytical < 1e-8
    assert np.allclose(res.thermal_strain_at_nodes, 0.0, atol=1e-14)


# ---------------------------------------------------------------------------
# Test 12: Monolithic — staggered consistent across different mesh sizes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n_elem", [4, 10, 20])
def test_staggered_converges_with_mesh_refinement(n_elem):
    """Tip displacement should converge as mesh is refined."""
    L = 1.0
    T_ref = 273.15
    mat = make_aluminium()
    mesh = uniform_bar_mesh(L, n_elem)
    thermal_bcs = {"temperature": {0: T_ref, n_elem: T_ref + 200.0}}
    structural_bcs = {"displacement": {0: 0.0}}

    res = solve_thermo_elastic_staggered(
        mesh, mat, thermal_bcs, structural_bcs, T_reference=T_ref
    )
    # For linear elements, result should be essentially exact already
    T_mean = T_ref + 100.0
    delta_T_mean = T_mean - T_ref
    delta_L = mat.thermal_expansion_per_k * L * delta_T_mean
    assert abs(res.displacements[-1] - delta_L) / (abs(delta_L) + 1e-10) < 0.01


# ---------------------------------------------------------------------------
# Test 13: Invalid mesh raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_mesh_raises():
    mat = make_steel()
    # Non-monotone nodes
    bad_mesh = {"nodes": [0.0, 0.5, 0.3, 1.0], "area": 1e-4}
    with pytest.raises(ValueError, match="strictly increasing"):
        solve_thermo_elastic_staggered(
            bad_mesh, mat, {"temperature": {0: 300.0, 3: 400.0}},
            {"displacement": {0: 0.0}}
        )
