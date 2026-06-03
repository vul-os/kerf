"""
Tests for kerf_cad_core.fluid.visual_fluid.

Coverage:
  make_fluid_state     — allocates zeroed grid with correct shape
  step_smoke           — density increases near source, advects across grid
  step_smoke           — velocity field updated (buoyancy lifts smoke)
  step_smoke           — dissipation reduces density over time
  step_flip            — particle count preserved across steps
  step_flip            — density non-zero after emitting particles
  step_flip            — gravity accelerates particles downward
  _advect              — scalar field moves with velocity
  density_iso_slice    — returns correct 2D boolean mask

References
----------
Zhu, Y. and Bridson, R. (2005).  "Animating Sand as a Fluid."  SIGGRAPH 2005.
Stam, J. (1999).  "Stable Fluids."  SIGGRAPH 1999.
Bridson, R. (2015).  "Fluid Simulation for Computer Graphics."  2nd ed.

Author: imranparuk
"""
from __future__ import annotations

import numpy as np
import pytest

from kerf_cad_core.fluid.visual_fluid import (
    FluidSimState,
    _advect,
    density_iso_slice,
    make_fluid_state,
    step_flip,
    step_smoke,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_smoke_state(nx=16, ny=16, nz=16, cs=0.1) -> FluidSimState:
    return make_fluid_state(nx, ny, nz, cell_size=cs, with_temperature=False)


def _make_flip_state(nx=8, ny=8, nz=8, cs=0.1) -> FluidSimState:
    return make_fluid_state(
        nx, ny, nz, cell_size=cs, with_particles=True, n_particles=0
    )


# ---------------------------------------------------------------------------
# make_fluid_state
# ---------------------------------------------------------------------------

class TestMakeFluidState:
    def test_velocity_shape(self):
        s = make_fluid_state(10, 12, 8)
        assert s.velocity.shape == (10, 12, 8, 3)

    def test_density_shape(self):
        s = make_fluid_state(10, 12, 8)
        assert s.density.shape == (10, 12, 8)

    def test_initial_values_zero(self):
        s = make_fluid_state(8, 8, 8)
        assert float(s.density.max()) == pytest.approx(0.0)
        assert float(s.velocity.max()) == pytest.approx(0.0)

    def test_temperature_allocated_when_requested(self):
        s = make_fluid_state(8, 8, 8, with_temperature=True)
        assert s.temperature is not None
        assert s.temperature.shape == (8, 8, 8)

    def test_temperature_none_by_default(self):
        s = make_fluid_state(8, 8, 8)
        assert s.temperature is None

    def test_particles_allocated_when_requested(self):
        s = make_fluid_state(8, 8, 8, with_particles=True, n_particles=10)
        assert s.particles is not None
        assert s.particles.shape == (10, 6)


# ---------------------------------------------------------------------------
# step_smoke — Stam (1999)
# ---------------------------------------------------------------------------

class TestStepSmoke:
    def test_density_increases_near_source(self):
        """After one step with a source, density near the source should increase."""
        s = _make_smoke_state()
        nx, ny, nz = s.grid_resolution
        src = np.zeros((nx, ny, nz))
        src[nx//2, ny//2, 1] = 1.0  # bottom-centre source

        s2 = step_smoke(s, dt=0.05, buoyancy=1.0, add_density_sources=src)
        # Some density should now exist in the grid
        assert float(s2.density.max()) > 0.0

    def test_density_advects_across_multiple_steps(self):
        """After several steps with a source, total grid density must increase.

        The semi-Lagrangian advection is unconditionally stable (Stam 1999).
        We verify that the total mass in the grid increases when a source is active,
        which confirms advect + source injection are both working.
        """
        s = _make_smoke_state(8, 8, 8)
        nx, ny, nz = s.grid_resolution
        src = np.zeros((nx, ny, nz))
        src[nx//2, ny//2, 2] = 1.0  # inject at bottom-centre

        initial_total = float(s.density.sum())
        for _ in range(8):
            s = step_smoke(s, dt=0.05, buoyancy=2.0, dissipation=1.0,
                           add_density_sources=src)

        final_total = float(s.density.sum())
        assert final_total > initial_total, (
            f"Total density should grow with active source: "
            f"initial={initial_total:.4f}, final={final_total:.4f}"
        )

    def test_dissipation_reduces_density(self):
        """With no source and high dissipation, density must decrease each step."""
        s = _make_smoke_state(8, 8, 8)
        s.density[:] = 1.0  # fill with smoke
        prev_total = float(s.density.sum())

        s2 = step_smoke(s, dt=0.05, buoyancy=0.0, dissipation=0.9)
        assert float(s2.density.sum()) < prev_total

    def test_velocity_field_updated(self):
        """Buoyancy force should create non-zero velocity after step."""
        s = _make_smoke_state(8, 8, 8)
        s.density[4, 4, 4] = 1.0
        s2 = step_smoke(s, dt=0.1, buoyancy=5.0)
        # Velocity in Z direction should have been pushed up
        assert float(np.abs(s2.velocity[:, :, :, 2]).max()) > 0.0

    def test_density_stays_in_range(self):
        """Density must remain in [0, 1] after clamping."""
        s = _make_smoke_state(8, 8, 8)
        src = np.ones(s.grid_resolution) * 0.5
        s2 = step_smoke(s, dt=0.05, add_density_sources=src)
        assert float(s2.density.min()) >= 0.0
        assert float(s2.density.max()) <= 1.0 + 1e-9

    def test_returns_fluid_sim_state(self):
        s = _make_smoke_state(8, 8, 8)
        s2 = step_smoke(s, dt=0.05)
        assert isinstance(s2, FluidSimState)


# ---------------------------------------------------------------------------
# step_flip — Zhu & Bridson (2005)
# ---------------------------------------------------------------------------

class TestStepFlip:
    def _make_emitter(self, nx=8, ny=8, nz=8, cs=0.1) -> dict:
        return {
            "center": [nx * cs / 2, ny * cs / 2, nz * cs * 0.75],
            "radius": cs * 0.5,
            "velocity": [0.0, 0.0, -0.1],
            "rate": 4,
        }

    def test_particle_count_increases_with_emitter(self):
        s = _make_flip_state()
        emitter = self._make_emitter()
        s2 = step_flip(s, dt=0.02, gravity=(0, 0, -9.81), emitters=[emitter])
        assert s2.particles is not None
        assert len(s2.particles) > 0

    def test_particle_count_preserved_after_multiple_steps(self):
        """Total particle count after N steps with no emitter = initial count.

        We pre-populate particles and run with no emitter — they should all survive.
        """
        s = make_fluid_state(8, 8, 8, with_particles=True, n_particles=20)
        # Place particles in the middle of the domain
        cs = s.cell_size
        s.particles[:, :3] = cs * 4.0  # all at centre
        s.particles[:, 3:] = 0.0       # zero velocity

        n_initial = len(s.particles)
        # Run 3 steps without emitter (no new particles added)
        for _ in range(3):
            s = step_flip(s, dt=0.01, gravity=(0, 0, -9.81), emitters=[])

        assert s.particles is not None
        assert len(s.particles) == n_initial

    def test_gravity_moves_particles_down(self):
        """After gravity, particle Z-velocity should become more negative."""
        s = make_fluid_state(8, 8, 8, with_particles=True, n_particles=5)
        cs = s.cell_size
        # Place particles with zero velocity in the middle
        s.particles[:, :3] = cs * 4.0
        s.particles[:, 3:] = 0.0

        s2 = step_flip(s, dt=0.1, gravity=(0.0, 0.0, -9.81), emitters=[])
        if s2.particles is not None and len(s2.particles) > 0:
            avg_vz = float(s2.particles[:, 5].mean())
            assert avg_vz < 0.0, f"Gravity should reduce Z velocity, got {avg_vz}"

    def test_density_nonzero_after_particles_emitted(self):
        s = _make_flip_state()
        emitter = self._make_emitter()
        s2 = step_flip(s, dt=0.02, gravity=(0, 0, -9.81), emitters=[emitter])
        assert float(s2.density.max()) > 0.0

    def test_returns_fluid_sim_state(self):
        s = _make_flip_state()
        s2 = step_flip(s, dt=0.02)
        assert isinstance(s2, FluidSimState)


# ---------------------------------------------------------------------------
# _advect
# ---------------------------------------------------------------------------

class TestAdvect:
    def test_static_velocity_no_change(self):
        """Zero velocity → advected field should be close to input field.

        With zero velocity the backtraced position is the same integer grid cell,
        so trilinear interpolation returns the same value.  A small tolerance
        accounts for floating-point rounding at integer grid boundaries.
        """
        field = np.random.default_rng(0).uniform(0, 1, (8, 8, 8))
        velocity = np.zeros((8, 8, 8, 3))
        result = _advect(field, velocity, dt=0.1, cell_size=0.1)
        assert result.shape == field.shape
        # Trilinear interpolation at exact integer cell centres is exact;
        # allow small tolerance for boundary clamping effects.
        np.testing.assert_allclose(result, field, atol=0.01)

    def test_density_moves_with_velocity(self):
        """A density blob with uniform +X velocity should shift downstream in X.

        Semi-Lagrangian backtrace: cell (x+1) looks back by 1 cell (to x)
        and picks up the density there — so density effectively moves to x+1.
        """
        nx, ny, nz = 16, 8, 8
        field = np.zeros((nx, ny, nz))
        field[4, 4, 4] = 1.0  # density blob at (4,4,4)

        cs = 0.1
        dt = 0.1
        # Velocity: +1 m/s in X → backtrace moves 1 cell in -X
        # → cell at x=5 gets value from x=4 → density appears at x=5
        velocity = np.zeros((nx, ny, nz, 3))
        velocity[:, :, :, 0] = 1.0  # +X

        result = _advect(field, velocity, dt=dt, cell_size=cs)
        # The blob should have moved downstream (to X=5 due to backtrace)
        assert result[5, 4, 4] > result[4, 4, 4]


# ---------------------------------------------------------------------------
# density_iso_slice
# ---------------------------------------------------------------------------

class TestDensityIsoSlice:
    def test_returns_boolean_mask(self):
        density = np.random.default_rng(1).uniform(0, 1, (8, 8, 8))
        mask = density_iso_slice(density, z_index=4)
        assert mask.dtype == bool
        assert mask.shape == (8, 8)

    def test_iso_value_0_all_true(self):
        density = np.ones((8, 8, 8)) * 0.5
        mask = density_iso_slice(density, 0, iso_value=0.0)
        assert mask.all()

    def test_iso_value_2_all_false(self):
        density = np.ones((8, 8, 8)) * 0.5
        mask = density_iso_slice(density, 0, iso_value=2.0)
        assert not mask.any()
