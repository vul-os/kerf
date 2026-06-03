"""
Lagrangian particle tracking — one-way and two-way coupled dispersed phase.

Overview
--------
Tracks a cloud of spherical particles through a carrier fluid using Newton's
second law.  Drag is computed using the Schiller-Naumann (1935) correlation,
which extends Stokes drag to higher Reynolds numbers (Re_p up to ~1000):

    C_D = 24/Re_p · (1 + 0.15 · Re_p^0.687)    for Re_p <= 1000
    C_D = 0.44                                   for Re_p > 1000

Drag force on a particle:
    F_D = 0.5 · ρ_f · |u_rel|² · (π d²/4) · C_D · û_rel

where û_rel = (u_f - u_p) / |u_f - u_p|  is the unit slip vector.

Equation of motion (per particle):
    m_p · dv_p/dt = F_D + m_p · g

One-way coupling: particles feel the fluid but do not affect it.
Two-way coupling: particles feel the fluid AND impart a reaction force on the
    fluid cell they currently occupy (momentum source term).

Particle-to-cell assignment uses a simple nearest-cell scheme via the
`cell_index` optional attribute.  For production use this should be replaced
by an octree or background Eulerian mesh lookup.

HONEST FLAG: Design-exploration accuracy only.  Not validated against
OpenFOAM or experimental benchmarks.  Do not use for safety-critical design.

References
----------
Crowe, C., Sommerfeld, M., Tsuji, Y. (1998). "Multiphase Flows with
Droplets and Particles." CRC Press.

Schiller, L., Naumann, A. (1935). "Über die grundlegenden Berechnungen bei
der Schwerkraftaufbereitung." Z. Ver. Dtsch. Ing. 77, 318–320.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Particle:
    """A single spherical particle in the Lagrangian frame.

    Attributes
    ----------
    position:
        3-D position vector [m], shape (3,).
    velocity:
        3-D velocity vector [m/s], shape (3,).
    diameter_m:
        Particle diameter [m].
    density_kg_per_m3:
        Particle material density [kg/m³].
    cell_index:
        Index of the Eulerian cell that currently contains this particle.
        -1 indicates not yet assigned.
    """
    position: np.ndarray
    velocity: np.ndarray
    diameter_m: float
    density_kg_per_m3: float
    cell_index: int = -1

    def __post_init__(self):
        self.position = np.asarray(self.position, dtype=float)
        self.velocity = np.asarray(self.velocity, dtype=float)

    @property
    def mass(self) -> float:
        """Particle mass [kg] = ρ_p · (4/3) π r³."""
        r = self.diameter_m / 2.0
        return self.density_kg_per_m3 * (4.0 / 3.0) * math.pi * r ** 3

    @property
    def cross_section_area(self) -> float:
        """Frontal cross-section area [m²] = π (d/2)²."""
        return math.pi * (self.diameter_m / 2.0) ** 2


@dataclass
class ParticleField:
    """A collection of Lagrangian particles.

    Attributes
    ----------
    particles:
        List of :class:`Particle` objects.
    """
    particles: list  # list[Particle]


# ---------------------------------------------------------------------------
# Drag correlation
# ---------------------------------------------------------------------------

def schiller_naumann_cd(Re_p: float) -> float:
    """Schiller-Naumann (1935) drag coefficient for a sphere.

    Parameters
    ----------
    Re_p:
        Particle Reynolds number  Re_p = ρ_f · |u_rel| · d / μ_f.

    Returns
    -------
    float
        Drag coefficient C_D [-].

    References
    ----------
    Schiller, L., Naumann, A. (1935). Z. Ver. Dtsch. Ing. 77, 318–320.
    Crowe et al. (1998). CRC Press.
    """
    if Re_p <= 0.0:
        # Limit: no slip → no drag
        return 0.0
    if Re_p <= 1000.0:
        return (24.0 / Re_p) * (1.0 + 0.15 * Re_p ** 0.687)
    return 0.44


def _drag_acceleration(
    p: Particle,
    u_fluid: np.ndarray,
    rho_fluid: float,
    mu_fluid: float,
) -> np.ndarray:
    """Drag acceleration on particle p due to fluid velocity u_fluid [m/s²]."""
    u_rel = u_fluid - p.velocity          # fluid relative to particle
    speed = float(np.linalg.norm(u_rel))

    if speed < 1e-15:
        return np.zeros(3)

    Re_p = rho_fluid * speed * p.diameter_m / mu_fluid
    Cd = schiller_naumann_cd(Re_p)

    # Drag force magnitude: F_D = 0.5 · ρ_f · |u_rel|² · A · Cd
    F_drag = 0.5 * rho_fluid * speed ** 2 * p.cross_section_area * Cd
    # Direction: same as u_rel
    a_drag = F_drag / p.mass * (u_rel / speed)
    return a_drag


# ---------------------------------------------------------------------------
# One-way coupling
# ---------------------------------------------------------------------------

def step_particles_one_way(
    field: ParticleField,
    fluid_velocity_at: Callable[[np.ndarray], np.ndarray],
    fluid_density: float,
    fluid_viscosity: float,
    gravity: tuple,
    dt: float,
) -> ParticleField:
    """Advance all particles one time step — one-way coupled (no back-reaction).

    Each particle is accelerated by:
      - Drag from the local fluid velocity (Schiller-Naumann correlation)
      - Gravity

    The fluid is **not** modified.

    Parameters
    ----------
    field:
        Current particle field.
    fluid_velocity_at:
        Callable mapping a position array (3,) → fluid velocity (3,) [m/s].
        Typically a linear interpolant from the Eulerian solver.
    fluid_density:
        Carrier-fluid density [kg/m³] (assumed uniform).
    fluid_viscosity:
        Carrier-fluid dynamic viscosity [Pa·s] (assumed uniform).
    gravity:
        Gravitational acceleration vector (gx, gy, gz) [m/s²].
        E.g. (0, -9.81, 0) for downward.
    dt:
        Time step [s].

    Returns
    -------
    ParticleField
        New particle field with updated positions and velocities.

    References
    ----------
    Crowe, C., Sommerfeld, M., Tsuji, Y. (1998). CRC Press.
    """
    g = np.asarray(gravity, dtype=float)
    new_particles = []

    for p in field.particles:
        u_f = np.asarray(fluid_velocity_at(p.position), dtype=float)
        a = _drag_acceleration(p, u_f, fluid_density, fluid_viscosity) + g

        new_vel = p.velocity + a * dt
        new_pos = p.position + 0.5 * (p.velocity + new_vel) * dt  # trapezoidal

        new_particles.append(Particle(
            position=new_pos,
            velocity=new_vel,
            diameter_m=p.diameter_m,
            density_kg_per_m3=p.density_kg_per_m3,
            cell_index=p.cell_index,
        ))

    return ParticleField(particles=new_particles)


# ---------------------------------------------------------------------------
# Two-way coupling
# ---------------------------------------------------------------------------

def step_particles_two_way(
    field: ParticleField,
    fluid_velocity: np.ndarray,
    cell_volumes: np.ndarray,
    fluid_density: float,
    fluid_viscosity: float,
    gravity: tuple,
    dt: float,
) -> tuple:
    """Advance all particles — two-way coupled (particles react on fluid).

    Identical drag physics to :func:`step_particles_one_way`, but each
    particle's drag force is accumulated as a **negative momentum source**
    on the fluid cell that contains the particle (Newton's 3rd law).

    Momentum source [N/m³] on cell i:
        S_mom[i] = -Σ_p F_drag(p) / V_cell[i]

    The *sign convention* is: positive S_mom adds momentum to the fluid in
    the direction of the slip.

    Parameters
    ----------
    field:
        Current particle field.
    fluid_velocity:
        Eulerian fluid velocity at cell centres, shape (Ncells, 3) [m/s].
    cell_volumes:
        Volume of each Eulerian cell, shape (Ncells,) [m³].
    fluid_density:
        Carrier-fluid density [kg/m³] (assumed uniform).
    fluid_viscosity:
        Carrier-fluid dynamic viscosity [Pa·s].
    gravity:
        Gravitational acceleration vector (gx, gy, gz) [m/s²].
    dt:
        Time step [s].

    Returns
    -------
    (ParticleField, np.ndarray)
        Updated particle field and momentum source per cell (Ncells, 3) [N/m³].

    References
    ----------
    Crowe, C., Sommerfeld, M., Tsuji, Y. (1998). CRC Press.
    """
    fluid_velocity = np.asarray(fluid_velocity, dtype=float)
    cell_volumes = np.asarray(cell_volumes, dtype=float)
    n_cells = len(cell_volumes)
    g = np.asarray(gravity, dtype=float)

    momentum_source = np.zeros((n_cells, 3), dtype=float)
    new_particles = []

    for p in field.particles:
        # Determine which cell owns this particle
        ci = p.cell_index
        if ci < 0 or ci >= n_cells:
            # Particle outside mesh — use nearest-cell fallback (cell 0)
            ci = 0

        u_f = fluid_velocity[ci]
        a_drag = _drag_acceleration(p, u_f, fluid_density, fluid_viscosity)
        F_drag = a_drag * p.mass  # Force on particle [N]

        # Reaction on fluid: equal and opposite (Newton's 3rd law)
        # Distributed over cell volume → [N/m³]
        momentum_source[ci] += (-F_drag) / cell_volumes[ci]

        a_total = a_drag + g
        new_vel = p.velocity + a_total * dt
        new_pos = p.position + 0.5 * (p.velocity + new_vel) * dt

        new_particles.append(Particle(
            position=new_pos,
            velocity=new_vel,
            diameter_m=p.diameter_m,
            density_kg_per_m3=p.density_kg_per_m3,
            cell_index=ci,
        ))

    return ParticleField(particles=new_particles), momentum_source
