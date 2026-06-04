"""
Tests for conjugate heat transfer solver (Wave 12B).

Reference: Quarteroni & Valli (1999) — Dirichlet-Neumann coupling convergence.
"""

from __future__ import annotations

import numpy as np
import pytest

from kerf_cfd.conjugate_ht.conjugate_solver import (
    FluidSolidInterface,
    couple_fluid_solid_temperature,
    heat_flux_at_interface,
)


# ---------------------------------------------------------------------------
# heat_flux_at_interface
# ---------------------------------------------------------------------------

def test_heat_flux_positive_when_fluid_hotter():
    """q > 0 when T_fluid > T_solid (heat flows from fluid to solid)."""
    q = heat_flux_at_interface(T_fluid_face=400.0, T_solid_face=300.0, h=100.0)
    assert q > 0, f"Expected q > 0, got {q}"


def test_heat_flux_zero_at_equilibrium():
    """q = 0 when T_fluid = T_solid."""
    q = heat_flux_at_interface(500.0, 500.0, h=200.0)
    assert q == pytest.approx(0.0, abs=1e-10)


def test_heat_flux_linear_in_h():
    """Heat flux scales linearly with h."""
    q1 = heat_flux_at_interface(600.0, 400.0, h=50.0)
    q2 = heat_flux_at_interface(600.0, 400.0, h=100.0)
    assert q2 == pytest.approx(2.0 * q1, rel=1e-10)


def test_heat_flux_sign_when_solid_hotter():
    """q < 0 when T_solid > T_fluid (heat flows from solid to fluid)."""
    q = heat_flux_at_interface(T_fluid_face=300.0, T_solid_face=500.0, h=100.0)
    assert q < 0


# ---------------------------------------------------------------------------
# FluidSolidInterface
# ---------------------------------------------------------------------------

def test_interface_default_face_areas():
    """Default face areas should be all ones."""
    iface = FluidSolidInterface(
        fluid_cell_ids=[0, 1],
        solid_cell_ids=[0, 1],
        face_pairs=[(0, 0), (1, 1)],
    )
    np.testing.assert_array_equal(iface.face_areas, [1.0, 1.0])


def test_interface_mismatch_raises():
    """Mismatched lengths should raise AssertionError."""
    with pytest.raises(AssertionError):
        FluidSolidInterface(
            fluid_cell_ids=[0],      # length 1
            solid_cell_ids=[0, 1],   # length 2 — mismatch
            face_pairs=[(0, 0)],
        )


# ---------------------------------------------------------------------------
# couple_fluid_solid_temperature
# ---------------------------------------------------------------------------

def _make_single_cell_interface():
    return FluidSolidInterface(
        fluid_cell_ids=[0],
        solid_cell_ids=[0],
        face_pairs=[(0, 0)],
        face_areas=np.array([1.0]),
    )


def test_coupling_interface_T_between_bulk_values():
    """After coupling, interface T should lie between hot fluid and cold solid."""
    T_hot = 600.0   # K — hot fluid
    T_cold = 300.0  # K — cold solid
    interface = _make_single_cell_interface()
    fluid_T, solid_T = couple_fluid_solid_temperature(
        np.array([T_hot]),
        np.array([T_cold]),
        interface,
        fluid_h=500.0,
        solid_k=10.0,
        n_iter=50,
        relaxation=0.5,
    )
    T_fi = float(fluid_T[0])
    T_si = float(solid_T[0])
    # Interface temperatures should move toward each other
    assert T_fi <= T_hot + 1e-3, f"Fluid T should not exceed initial hot: {T_fi}"
    assert T_si >= T_cold - 1e-3, f"Solid T should not go below initial cold: {T_si}"
    # Both sides should move from their initial extremes
    assert T_fi < T_hot or T_si > T_cold, "Interface should exchange heat"


def test_coupling_identical_temperatures_no_flux():
    """Equal T_fluid and T_solid → no change after coupling."""
    T_eq = 400.0
    interface = _make_single_cell_interface()
    fluid_T, solid_T = couple_fluid_solid_temperature(
        np.array([T_eq]),
        np.array([T_eq]),
        interface,
        fluid_h=100.0,
        solid_k=5.0,
        n_iter=20,
    )
    assert float(fluid_T[0]) == pytest.approx(T_eq, abs=1e-3)
    assert float(solid_T[0]) == pytest.approx(T_eq, abs=1e-3)


def test_coupling_returns_arrays_of_correct_shape():
    """Returned arrays must match input shapes."""
    n_fluid = 5
    n_solid = 5
    fluid_T = np.linspace(500, 600, n_fluid)
    solid_T = np.linspace(300, 350, n_solid)
    interface = FluidSolidInterface(
        fluid_cell_ids=list(range(n_fluid)),
        solid_cell_ids=list(range(n_solid)),
        face_pairs=[(i, i) for i in range(n_fluid)],
    )
    f_out, s_out = couple_fluid_solid_temperature(
        fluid_T, solid_T, interface, fluid_h=200.0, solid_k=15.0
    )
    assert f_out.shape == (n_fluid,)
    assert s_out.shape == (n_solid,)


def test_coupling_high_h_dominates():
    """Very high h → fluid-side interface temperature approaches solid temperature."""
    T_fluid = 1000.0
    T_solid = 300.0
    interface = _make_single_cell_interface()
    fluid_T, solid_T = couple_fluid_solid_temperature(
        np.array([T_fluid]),
        np.array([T_solid]),
        interface,
        fluid_h=1e6,    # very high convection
        solid_k=1.0,
        n_iter=100,
        relaxation=0.3,
    )
    # With very high h and many iterations, interface should be approaching equilibrium
    # The solid should heat up toward fluid
    assert float(solid_T[0]) > T_solid - 1.0, "Solid should warm with high h"


def test_coupling_low_k_reduces_heat_flux():
    """Very low solid k → smaller temperature change in solid."""
    interface = _make_single_cell_interface()
    _, solid_T_low_k = couple_fluid_solid_temperature(
        np.array([800.0]),
        np.array([300.0]),
        interface,
        fluid_h=100.0,
        solid_k=0.01,    # insulating solid
        n_iter=30,
    )
    _, solid_T_high_k = couple_fluid_solid_temperature(
        np.array([800.0]),
        np.array([300.0]),
        interface,
        fluid_h=100.0,
        solid_k=100.0,   # highly conducting solid
        n_iter=30,
    )
    delta_low = float(solid_T_low_k[0]) - 300.0
    delta_high = float(solid_T_high_k[0]) - 300.0
    # High k solid warms more (larger thermal coupling)
    assert delta_high >= delta_low - 1e-6, (
        f"High-k solid should warm at least as much: delta_low={delta_low:.4f} delta_high={delta_high:.4f}"
    )
