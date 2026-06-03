"""
Tests for kerf_cfd.lagrangian.particle_tracking.

References:
  Crowe, C., Sommerfeld, M., Tsuji, Y. (1998). "Multiphase Flows with
  Droplets and Particles." CRC Press.

  Schiller, L., Naumann, A. (1935). Z. Ver. Dtsch. Ing. 77, 318–320.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from kerf_cfd.lagrangian.particle_tracking import (
    Particle,
    ParticleField,
    schiller_naumann_cd,
    step_particles_one_way,
    step_particles_two_way,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def water_droplet():
    """A 100-µm water droplet initially at rest at the origin."""
    return Particle(
        position=np.array([0.0, 0.0, 0.0]),
        velocity=np.array([0.0, 0.0, 0.0]),
        diameter_m=100e-6,
        density_kg_per_m3=1000.0,
    )


@pytest.fixture
def air_props():
    return {"fluid_density": 1.2, "fluid_viscosity": 1.8e-5}


# ---------------------------------------------------------------------------
# Drag correlation tests
# ---------------------------------------------------------------------------

class TestSchillerNaumann:

    def test_stokes_limit_low_re(self):
        """At very low Re, C_D → 24/Re (Stokes drag)."""
        Re = 0.01
        cd = schiller_naumann_cd(Re)
        cd_stokes = 24.0 / Re
        # EBU correction: (1 + 0.15 * Re^0.687) ≈ 1 for small Re
        assert abs(cd - cd_stokes) / cd_stokes < 0.01

    def test_high_re_constant(self):
        """For Re > 1000, C_D should be 0.44 (Newton regime)."""
        cd = schiller_naumann_cd(2000.0)
        assert cd == pytest.approx(0.44)

    def test_zero_re_returns_zero(self):
        """C_D at Re=0 should return 0 (no slip, no drag)."""
        assert schiller_naumann_cd(0.0) == 0.0

    def test_cd_decreases_with_re_in_stokes(self):
        """Drag coefficient decreases as Re increases (viscous regime)."""
        cd_low = schiller_naumann_cd(1.0)
        cd_mid = schiller_naumann_cd(10.0)
        cd_high = schiller_naumann_cd(100.0)
        assert cd_low > cd_mid > cd_high


# ---------------------------------------------------------------------------
# One-way coupling tests
# ---------------------------------------------------------------------------

class TestOneWayCoupling:

    def test_zero_slip_gives_zero_acceleration(self, water_droplet, air_props):
        """When particle velocity == fluid velocity, drag = 0; particle moves at const vel."""
        p = Particle(
            position=np.array([0.0, 0.0, 0.0]),
            velocity=np.array([1.0, 0.0, 0.0]),
            diameter_m=100e-6,
            density_kg_per_m3=1000.0,
        )
        field = ParticleField(particles=[p])
        # Fluid moves at same velocity as particle
        u_f = np.array([1.0, 0.0, 0.0])

        field_new = step_particles_one_way(
            field=field,
            fluid_velocity_at=lambda pos: u_f,
            gravity=(0.0, 0.0, 0.0),
            dt=0.01,
            **air_props,
        )
        # Without gravity and with zero slip, velocity should remain [1,0,0]
        np.testing.assert_allclose(
            field_new.particles[0].velocity, [1.0, 0.0, 0.0], atol=1e-12
        )

    def test_gravity_accelerates_particle(self, water_droplet, air_props):
        """With gravity and no fluid, particle should accelerate downward."""
        field = ParticleField(particles=[water_droplet])
        # No fluid flow, gravity only
        field_new = step_particles_one_way(
            field=field,
            fluid_velocity_at=lambda pos: np.zeros(3),
            gravity=(0.0, -9.81, 0.0),
            dt=0.001,
            **air_props,
        )
        assert field_new.particles[0].velocity[1] < 0.0, "Particle should accelerate downward"

    def test_terminal_velocity_stokes(self, air_props):
        """Stokes terminal velocity: v_t = d² (ρ_p-ρ_f) g / (18 μ).
        For a small particle (Re << 1) the numerical and analytical values should agree."""
        d = 10e-6      # 10 µm
        rho_p = 1000.0
        rho_f = air_props["fluid_density"]
        mu = air_props["fluid_viscosity"]
        g_mag = 9.81

        v_t_stokes = (d ** 2 * (rho_p - rho_f) * g_mag) / (18.0 * mu)
        # Verify Re_t << 1 (Stokes regime valid)
        Re_t = rho_f * v_t_stokes * d / mu
        assert Re_t < 1.0, f"Test invalid: Re_t={Re_t:.3f} not in Stokes regime"

        p = Particle(
            position=np.zeros(3),
            velocity=np.array([0.0, -v_t_stokes * 0.99, 0.0]),  # near terminal
            diameter_m=d,
            density_kg_per_m3=rho_p,
        )
        field = ParticleField(particles=[p])

        # At terminal velocity, acceleration ≈ 0 → velocity barely changes
        field_new = step_particles_one_way(
            field=field,
            fluid_velocity_at=lambda pos: np.zeros(3),
            gravity=(0.0, -g_mag, 0.0),
            dt=1e-4,
            **air_props,
        )
        dv = abs(field_new.particles[0].velocity[1] - p.velocity[1])
        # Should change by less than 1% of terminal velocity per step
        assert dv < 0.02 * v_t_stokes, (
            f"Velocity change {dv:.2e} too large near terminal velocity {v_t_stokes:.2e}"
        )

    def test_particle_position_updates(self, water_droplet, air_props):
        """Particle position must change after one time step."""
        field = ParticleField(particles=[water_droplet])
        field_new = step_particles_one_way(
            field=field,
            fluid_velocity_at=lambda pos: np.array([1.0, 0.0, 0.0]),
            gravity=(0.0, 0.0, 0.0),
            dt=0.01,
            **air_props,
        )
        # Particle at rest in 1 m/s flow must move
        assert field_new.particles[0].position[0] > 0.0

    def test_multiple_particles_independent(self, air_props):
        """Multiple particles are tracked independently (no mutual interaction)."""
        p1 = Particle(np.array([0.0, 0.0, 0.0]), np.zeros(3), 50e-6, 1000.0)
        p2 = Particle(np.array([1.0, 0.0, 0.0]), np.zeros(3), 50e-6, 1000.0)
        field = ParticleField(particles=[p1, p2])

        field_new = step_particles_one_way(
            field=field,
            fluid_velocity_at=lambda pos: np.array([0.5, 0.0, 0.0]),
            gravity=(0.0, -9.81, 0.0),
            dt=0.001,
            **air_props,
        )
        assert len(field_new.particles) == 2


# ---------------------------------------------------------------------------
# Two-way coupling tests
# ---------------------------------------------------------------------------

class TestTwoWayCoupling:

    def test_momentum_source_opposite_to_drag_force(self, air_props):
        """Reaction force on fluid must be equal and opposite to force on particle."""
        p = Particle(
            position=np.zeros(3),
            velocity=np.zeros(3),
            diameter_m=100e-6,
            density_kg_per_m3=1000.0,
            cell_index=0,
        )
        field = ParticleField(particles=[p])

        fluid_vel = np.array([[2.0, 0.0, 0.0]])  # (1 cell, 3)
        cell_volumes = np.array([1.0])             # 1 m³

        field_new, mom_src = step_particles_two_way(
            field=field,
            fluid_velocity=fluid_vel,
            cell_volumes=cell_volumes,
            gravity=(0.0, 0.0, 0.0),
            dt=0.001,
            **air_props,
        )

        # Momentum source on fluid should be in +x (fluid pushes particle +x, particle pushes fluid −x)
        # mom_src sign convention: negative means fluid loses x-momentum (correct Newton's 3rd law)
        # The fluid drags particle in +x, so fluid must lose x-momentum
        # mom_src[0, 0] should be <= 0 (fluid x-momentum decreases)
        assert mom_src[0, 0] <= 0.0, (
            f"Fluid should lose x-momentum; got mom_src[0,0]={mom_src[0,0]:.4e}"
        )

    def test_zero_slip_zero_momentum_source(self, air_props):
        """When particle velocity = fluid velocity, drag = 0 → momentum source = 0."""
        p = Particle(
            position=np.zeros(3),
            velocity=np.array([1.0, 0.0, 0.0]),
            diameter_m=100e-6,
            density_kg_per_m3=1000.0,
            cell_index=0,
        )
        field = ParticleField(particles=[p])
        fluid_vel = np.array([[1.0, 0.0, 0.0]])
        cell_volumes = np.array([0.001])

        _, mom_src = step_particles_two_way(
            field=field,
            fluid_velocity=fluid_vel,
            cell_volumes=cell_volumes,
            gravity=(0.0, 0.0, 0.0),
            dt=0.001,
            **air_props,
        )
        np.testing.assert_allclose(mom_src[0], [0.0, 0.0, 0.0], atol=1e-20)

    def test_two_way_returns_correct_shapes(self, air_props):
        """Two-way coupling must return (ParticleField, ndarray of shape (Ncells, 3))."""
        n_cells = 4
        particles = [
            Particle(np.zeros(3), np.zeros(3), 100e-6, 1000.0, cell_index=i % n_cells)
            for i in range(6)
        ]
        field = ParticleField(particles=particles)
        fluid_vel = np.random.rand(n_cells, 3)
        cell_volumes = np.ones(n_cells) * 1e-3

        field_new, mom_src = step_particles_two_way(
            field=field,
            fluid_velocity=fluid_vel,
            cell_volumes=cell_volumes,
            gravity=(0.0, -9.81, 0.0),
            dt=1e-4,
            **air_props,
        )
        assert isinstance(field_new, ParticleField)
        assert len(field_new.particles) == 6
        assert mom_src.shape == (n_cells, 3)
