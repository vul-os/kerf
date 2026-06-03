"""
kerf_cfd.lagrangian — Lagrangian particle tracking with mass/momentum coupling.

Implements one-way and two-way coupled Lagrangian dispersed-phase tracking
using the Schiller-Naumann drag correlation for spherical particles.

HONEST FLAG: Design-exploration accuracy only.  Not validated against
OpenFOAM or experimental benchmarks.  Do not use for safety-critical design.

References:
  Crowe, C., Sommerfeld, M., Tsuji, Y. (1998). "Multiphase Flows with
  Droplets and Particles." CRC Press.
"""

from kerf_cfd.lagrangian.particle_tracking import (
    Particle,
    ParticleField,
    schiller_naumann_cd,
    step_particles_one_way,
    step_particles_two_way,
)

__all__ = [
    "Particle",
    "ParticleField",
    "schiller_naumann_cd",
    "step_particles_one_way",
    "step_particles_two_way",
]
