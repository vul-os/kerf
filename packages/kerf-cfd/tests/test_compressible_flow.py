"""
Tests for compressible flow module (Wave 12B).

Reference values from:
  Anderson, J.D. (2003). "Modern Compressible Flow." 3rd ed., McGraw-Hill.
  Normal shock tables for γ=1.4, M₁=2: p₂/p₁=4.5, T₂/T₁=1.687, ρ₂/ρ₁=2.667, M₂=0.577.
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_cfd.compressible.compressible_flow import (
    CompressibleState,
    normal_shock_relations,
    roe_flux,
    step_compressible,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uniform_state(ncells: int = 4, ndim: int = 2, rho: float = 1.225,
                   u: float = 100.0, p: float = 101325.0, gamma: float = 1.4):
    """Build a uniform-flow CompressibleState with given scalars."""
    rho_arr = np.full(ncells, rho)
    rho_u = np.zeros((ncells, ndim))
    rho_u[:, 0] = rho * u   # x-momentum only
    # rho_E = p/(gamma-1) + 0.5*rho*u^2
    rho_E = p / (gamma - 1.0) + 0.5 * rho * u ** 2
    rho_E_arr = np.full(ncells, rho_E)
    return CompressibleState(rho=rho_arr, rho_u=rho_u, rho_E=rho_E_arr, gamma=gamma)


def _rest_state(ncells: int = 1, ndim: int = 2, rho: float = 1.225,
                p: float = 101325.0, gamma: float = 1.4):
    """Build a zero-velocity state."""
    rho_arr = np.full(ncells, rho)
    rho_u = np.zeros((ncells, ndim))
    rho_E = p / (gamma - 1.0)
    rho_E_arr = np.full(ncells, rho_E)
    return CompressibleState(rho=rho_arr, rho_u=rho_u, rho_E=rho_E_arr, gamma=gamma)


# ---------------------------------------------------------------------------
# CompressibleState derived quantities
# ---------------------------------------------------------------------------

def test_mach_number_at_rest_is_zero():
    """Mach number at zero velocity must be 0 (|u|=0)."""
    state = _rest_state(ncells=3)
    M = state.mach_number()
    np.testing.assert_array_less(M, 1e-10)


def test_mach_number_subsonic():
    """u=100 m/s in air at 101325 Pa should give M < 1."""
    state = _uniform_state(ncells=2, u=100.0)
    M = state.mach_number()
    assert np.all(M < 1.0), f"Expected subsonic, got M={M}"


def test_pressure_roundtrip():
    """Pressure from rho_E recovers the input pressure."""
    p_ref = 101325.0
    rho = 1.225
    state = _rest_state(ncells=5, rho=rho, p=p_ref)
    p_calc = state.pressure()
    np.testing.assert_allclose(p_calc, p_ref, rtol=1e-10)


def test_temperature_positive():
    """Temperature must be positive for physical state."""
    state = _uniform_state(ncells=4, rho=1.225, u=200.0, p=101325.0)
    T = state.temperature()
    assert np.all(T > 0), "Temperature must be positive"


def test_sound_speed_air():
    """Speed of sound in air at 288 K ≈ 340 m/s."""
    p = 101325.0
    rho = p / (287.058 * 288.15)  # ρ = p/(R·T)
    state = _rest_state(ncells=1, rho=rho, p=p)
    c = state.sound_speed()
    # c = sqrt(1.4 * 101325 / rho_at_288K) ≈ 340 m/s
    assert abs(float(c[0]) - 340.0) < 10.0, f"Sound speed c={c[0]:.1f} m/s outside ±10 of 340"


def test_total_enthalpy_positive():
    """Total enthalpy must be positive for physical state."""
    state = _uniform_state(ncells=3, u=300.0, p=50000.0)
    H = state.total_enthalpy()
    assert np.all(H > 0)


# ---------------------------------------------------------------------------
# Normal shock relations
# ---------------------------------------------------------------------------

def test_normal_shock_m2_air():
    """M₁=2, γ=1.4 → p₂/p₁ ≈ 4.5, T₂/T₁ ≈ 1.687 (Anderson Table A.2)."""
    result = normal_shock_relations(2.0, gamma=1.4)
    assert abs(result["p2_p1"] - 4.5) < 0.01, f"p2/p1={result['p2_p1']}"
    assert abs(result["T2_T1"] - 1.687) < 0.005, f"T2/T1={result['T2_T1']}"


def test_normal_shock_density_ratio():
    """M₁=2, γ=1.4 → ρ₂/ρ₁ ≈ 2.667."""
    result = normal_shock_relations(2.0, gamma=1.4)
    assert abs(result["rho2_rho1"] - 2.667) < 0.01, f"rho2/rho1={result['rho2_rho1']}"


def test_normal_shock_downstream_mach():
    """M₁=2 → M₂ ≈ 0.5774 (subsonic downstream)."""
    result = normal_shock_relations(2.0, gamma=1.4)
    assert abs(result["M2"] - 0.5774) < 0.002, f"M2={result['M2']}"


def test_normal_shock_m3_pressure():
    """M₁=3, γ=1.4 → p₂/p₁ ≈ 10.333 (Anderson Table A.2)."""
    result = normal_shock_relations(3.0, gamma=1.4)
    assert abs(result["p2_p1"] - 10.333) < 0.05, f"p2/p1={result['p2_p1']}"


def test_normal_shock_requires_supersonic():
    """Should raise ValueError for M₁ < 1."""
    with pytest.raises(ValueError):
        normal_shock_relations(0.8)


def test_normal_shock_m1_limit():
    """At M₁=1 all ratios → 1 (no shock)."""
    result = normal_shock_relations(1.0)
    assert abs(result["p2_p1"] - 1.0) < 0.01
    assert abs(result["rho2_rho1"] - 1.0) < 0.01
    assert abs(result["T2_T1"] - 1.0) < 0.01


# ---------------------------------------------------------------------------
# Roe flux
# ---------------------------------------------------------------------------

def test_roe_flux_uniform_is_zero():
    """Roe flux on identical L/R states (uniform flow) should give zero dissipation."""
    rho = 1.225
    u = 100.0
    p = 101325.0
    gamma = 1.4
    ndim = 2

    def _single(r, ux, pp):
        rho_u = np.array([[r * ux, 0.0]])
        rho_E = np.array([pp / (gamma - 1.0) + 0.5 * r * ux ** 2])
        return CompressibleState(rho=np.array([r]), rho_u=rho_u, rho_E=rho_E, gamma=gamma)

    s_L = _single(rho, u, p)
    s_R = _single(rho, u, p)
    n_hat = np.array([1.0, 0.0])

    flux = roe_flux(s_L, s_R, n_hat)
    # Dissipation part should vanish; net flux = f_L = f_R (non-zero physical flux)
    # Check that flux is consistent: F_rho = rho*u (for normal component)
    expected_f_rho = rho * u   # x-face
    assert abs(flux[0] - expected_f_rho) < 1.0, f"F_rho={flux[0]:.3f} vs expected {expected_f_rho:.3f}"


def test_roe_flux_zero_velocity():
    """Roe flux with zero velocity: only pressure contributes to momentum flux."""
    p = 101325.0
    rho = 1.225
    gamma = 1.4
    rho_E = p / (gamma - 1.0)
    s_L = CompressibleState(
        rho=np.array([rho]), rho_u=np.zeros((1, 2)), rho_E=np.array([rho_E]), gamma=gamma
    )
    s_R = CompressibleState(
        rho=np.array([rho]), rho_u=np.zeros((1, 2)), rho_E=np.array([rho_E]), gamma=gamma
    )
    n_hat = np.array([1.0, 0.0])
    flux = roe_flux(s_L, s_R, n_hat)
    # F_rho = 0, F_rho_u_x = p, F_rho_E = 0
    assert abs(flux[0]) < 1e-6, "Mass flux must be zero at rest"
    assert abs(flux[1] - p) < 1.0, f"Momentum flux should be pressure {p:.0f}, got {flux[1]:.0f}"


def test_roe_flux_returns_correct_size():
    """Roe flux should return vector of length ndim+2."""
    ndim = 3
    rho = 1.0
    p = 1e5
    gamma = 1.4
    rho_E = p / (gamma - 1.0)
    s = CompressibleState(
        rho=np.array([rho]),
        rho_u=np.zeros((1, ndim)),
        rho_E=np.array([rho_E]),
        gamma=gamma,
    )
    n = np.array([0.0, 0.0, 1.0])
    flux = roe_flux(s, s, n)
    assert flux.shape == (ndim + 2,), f"Expected shape ({ndim+2},), got {flux.shape}"


# ---------------------------------------------------------------------------
# step_compressible
# ---------------------------------------------------------------------------

def test_step_compressible_mass_conserved():
    """Total mass (sum ρ·V) must be conserved under periodic-like boundary conditions."""
    ncells = 4
    ndim = 2
    state = _uniform_state(ncells=ncells, ndim=ndim, rho=1.225, u=10.0, p=101325.0)
    cell_volumes = np.ones(ncells)
    # 1-D periodic chain: 0-1, 1-2, 2-3, 3-0
    neighbours = [(0, 1), (1, 2), (2, 3), (3, 0)]
    nfaces = len(neighbours)
    face_areas = np.ones(nfaces)
    face_normals = np.tile([1.0, 0.0], (nfaces, 1))

    mass_before = np.sum(state.rho * cell_volumes)
    new_state = step_compressible(state, cell_volumes, face_areas, face_normals, neighbours, dt=1e-5)
    mass_after = np.sum(new_state.rho * cell_volumes)
    np.testing.assert_allclose(mass_after, mass_before, rtol=1e-6)


def test_step_compressible_returns_compressible_state():
    """step_compressible must return a CompressibleState."""
    state = _uniform_state(ncells=2, ndim=2, rho=1.0, u=50.0, p=1e5)
    neighbours = [(0, 1)]
    face_areas = np.array([1.0])
    face_normals = np.array([[1.0, 0.0]])
    cell_volumes = np.array([1.0, 1.0])
    result = step_compressible(state, cell_volumes, face_areas, face_normals, neighbours, dt=1e-6)
    assert isinstance(result, CompressibleState)
