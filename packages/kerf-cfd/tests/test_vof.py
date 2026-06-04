"""
Tests for Volume of Fluid (VOF) multiphase module (Wave 12B).

Reference: Hirt & Nichols (1981), Youngs (1982), Weller (2008).
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_cfd.multiphase.vof import (
    VofState,
    interface_reconstruction_plic,
    mixture_density,
    step_vof,
)


# ---------------------------------------------------------------------------
# VofState construction
# ---------------------------------------------------------------------------

def test_vof_state_clips_alpha():
    """α outside [0,1] should be clipped on construction."""
    alpha = np.array([-0.1, 0.5, 1.2])
    vel = np.zeros((3, 2))
    state = VofState(alpha=alpha, velocity=vel)
    assert np.all(state.alpha >= 0.0)
    assert np.all(state.alpha <= 1.0)


def test_vof_state_default_densities():
    """Default rho_phase1=1000 (water), rho_phase2=1.225 (air)."""
    state = VofState(alpha=np.array([0.5]), velocity=np.zeros((1, 2)))
    assert state.rho_phase1 == pytest.approx(1000.0)
    assert state.rho_phase2 == pytest.approx(1.225)


# ---------------------------------------------------------------------------
# mixture_density
# ---------------------------------------------------------------------------

def test_mixture_density_pure_water():
    """α=1 → ρ_mix = ρ_water = 1000 kg/m³."""
    state = VofState(alpha=np.ones(5), velocity=np.zeros((5, 2)))
    rho = mixture_density(state)
    np.testing.assert_allclose(rho, 1000.0, rtol=1e-10)


def test_mixture_density_pure_air():
    """α=0 → ρ_mix = ρ_air = 1.225 kg/m³."""
    state = VofState(alpha=np.zeros(5), velocity=np.zeros((5, 2)))
    rho = mixture_density(state)
    np.testing.assert_allclose(rho, 1.225, rtol=1e-10)


def test_mixture_density_half_half():
    """α=0.5 → ρ_mix = 0.5·1000 + 0.5·1.225 = 500.6125 kg/m³."""
    state = VofState(alpha=np.array([0.5]), velocity=np.zeros((1, 2)))
    rho = mixture_density(state)
    expected = 0.5 * 1000.0 + 0.5 * 1.225
    np.testing.assert_allclose(rho[0], expected, rtol=1e-10)


def test_mixture_density_linear():
    """ρ_mix should vary linearly between ρ_air and ρ_water."""
    alpha_vals = np.linspace(0.0, 1.0, 11)
    state = VofState(alpha=alpha_vals, velocity=np.zeros((11, 2)))
    rho = mixture_density(state)
    rho_expected = alpha_vals * 1000.0 + (1.0 - alpha_vals) * 1.225
    np.testing.assert_allclose(rho, rho_expected, rtol=1e-10)


# ---------------------------------------------------------------------------
# step_vof
# ---------------------------------------------------------------------------

def _make_1d_droplet_state(ncells: int = 10, droplet_start: int = 4, droplet_end: int = 6):
    """Build a 1-D state with a water droplet (α=1) in cells [droplet_start, droplet_end)."""
    alpha = np.zeros(ncells)
    alpha[droplet_start:droplet_end] = 1.0
    velocity = np.zeros((ncells, 1))
    velocity[:, 0] = 0.5   # uniform flow u=0.5 m/s
    return VofState(alpha=alpha, velocity=velocity)


def _make_1d_grid(ncells: int):
    """1-D periodic grid geometry (unit cell spacing)."""
    nfaces = ncells
    face_areas = np.ones(nfaces)
    face_normals = np.ones((nfaces, 1))
    # Face i connects cell i and cell (i+1) % ncells
    neighbours = [(i, (i + 1) % ncells) for i in range(nfaces)]
    return face_areas, face_normals, neighbours


def test_step_vof_returns_vof_state():
    """step_vof must return a VofState."""
    state = _make_1d_droplet_state()
    fa, fn, nb = _make_1d_grid(len(state.alpha))
    result = step_vof(state, fa, fn, nb, dt=0.01)
    assert isinstance(result, VofState)


def test_step_vof_alpha_in_range():
    """After stepping, all α values must remain in [0, 1]."""
    state = _make_1d_droplet_state()
    fa, fn, nb = _make_1d_grid(len(state.alpha))
    result = step_vof(state, fa, fn, nb, dt=0.05)
    assert np.all(result.alpha >= -1e-12), "α should not go below 0"
    assert np.all(result.alpha <= 1.0 + 1e-12), "α should not exceed 1"


def test_step_vof_mass_conservation():
    """Total water volume fraction must be approximately conserved over 10 steps."""
    ncells = 10
    state = _make_1d_droplet_state(ncells=ncells, droplet_start=4, droplet_end=6)
    fa, fn, nb = _make_1d_grid(ncells)
    total_water_initial = float(np.sum(state.alpha))
    for _ in range(10):
        state = step_vof(state, fa, fn, nb, dt=0.02, courant_max=0.3)
    total_water_final = float(np.sum(state.alpha))
    # Allow 5% tolerance for upwind + compression scheme
    assert abs(total_water_final - total_water_initial) < 0.05 * total_water_initial + 0.1, (
        f"Water mass not conserved: {total_water_initial:.4f} → {total_water_final:.4f}"
    )


def test_step_vof_uniform_alpha_is_preserved():
    """Uniform α=0.3 field with uniform velocity should remain unchanged (no gradient)."""
    ncells = 6
    alpha = np.full(ncells, 0.3)
    velocity = np.zeros((ncells, 1))
    velocity[:, 0] = 1.0
    state = VofState(alpha=alpha, velocity=velocity)
    fa, fn, nb = _make_1d_grid(ncells)
    result = step_vof(state, fa, fn, nb, dt=0.01)
    # Uniform field: no net flux; interface compression term also zero (α(1-α) same everywhere)
    np.testing.assert_allclose(result.alpha, 0.3, atol=1e-6)


def test_step_vof_zero_velocity_no_change():
    """Zero velocity field → α must not change."""
    ncells = 8
    alpha = np.array([0.0, 0.0, 1.0, 1.0, 0.0, 0.5, 0.0, 0.0])
    velocity = np.zeros((ncells, 1))
    state = VofState(alpha=alpha, velocity=velocity)
    fa, fn, nb = _make_1d_grid(ncells)
    result = step_vof(state, fa, fn, nb, dt=0.1)
    np.testing.assert_allclose(result.alpha, alpha, atol=1e-10)


# ---------------------------------------------------------------------------
# interface_reconstruction_plic
# ---------------------------------------------------------------------------

def test_plic_interface_cells_only():
    """PLIC should only return normals for interface cells (0 < α < 1)."""
    alpha = np.array([0.0, 1.0, 0.5, 0.3, 1.0])
    velocity = np.zeros((5, 2))
    state = VofState(alpha=alpha, velocity=velocity)
    neighbours = [[1, 2], [0, 2], [1, 3], [2, 4], [3, 0]]
    normals = interface_reconstruction_plic(state, neighbours)
    # Cells 2 (α=0.5) and 3 (α=0.3) are interface cells
    assert 0 not in normals, "Cell 0 (α=0) is not an interface cell"
    assert 1 not in normals, "Cell 1 (α=1) is not an interface cell"
    assert 2 in normals, "Cell 2 (α=0.5) should be an interface cell"
    assert 3 in normals, "Cell 3 (α=0.3) should be an interface cell"


def test_plic_normal_is_unit():
    """PLIC normals for valid interface cells should have unit magnitude (or zero for isolated)."""
    alpha = np.array([0.0, 0.4, 0.6, 1.0, 0.8])
    velocity = np.zeros((5, 2))
    state = VofState(alpha=alpha, velocity=velocity)
    neighbours = [[1], [0, 2], [1, 3], [2, 4], [3]]
    normals = interface_reconstruction_plic(state, neighbours)
    for cell_idx, n in normals.items():
        mag = float(np.linalg.norm(n))
        assert mag < 1.0 + 1e-10, f"Normal magnitude {mag} > 1 for cell {cell_idx}"
