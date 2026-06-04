# Lagrangian Particle Tracking

> Track discrete particles (droplets, sprays, coal, or sand) through a carrier flow using Newton's law with Schiller-Naumann drag — for spray drying, pneumatic conveying, and spray cooling.

**Module**: `packages/kerf-cfd/src/kerf_cfd/lagrangian/particle_tracking.py`
**Shipped**: Wave 10
**LLM tools**: `cfd_lagrangian_track`

---

## What it is

Lagrangian particle tracking models the motion of discrete particles (liquid droplets, solid grains, fibres) in a continuous carrier fluid. Unlike Eulerian approaches that model the dispersed phase as a continuum, the Lagrangian approach tracks individual particle trajectories by integrating Newton's second law with aerodynamic drag, gravity, and optionally Brownian motion and lift forces.

This module provides one-way coupling (particles follow the fluid without modifying it) and two-way coupling (particle drag feeds back into the fluid momentum equations). The Schiller-Naumann drag correlation covers the full range from Stokes flow (Re_p < 1) to inertial flow (Re_p up to 800). Engineers use it for spray drying (dairy, pharmaceuticals), pneumatic conveying of granular materials, and spray-cooled electronics.

## How to use it

### From chat (natural language)

> "Track 500 water droplets of 50µm diameter injected at 10 m/s into a 5 m/s crossflow"

The LLM calls `cfd_lagrangian_track` with the particle and flow specs.

### From Python

```python
from kerf_cfd.lagrangian.particle_tracking import (
    Particle, ParticleField, step_particles_one_way,
    step_particles_two_way, schiller_naumann_cd,
)

particles = ParticleField(
    positions=[(0,0,0)] * 100,
    velocities=[(10,0,0)] * 100,
    diameters=[50e-6] * 100,      # 50 µm
    densities=[1000.0] * 100,     # water
)
fluid_velocity = lambda pos: (5.0, 0.0, 0.0)  # uniform crossflow

for _ in range(100):
    particles = step_particles_one_way(particles, fluid_velocity, dt=1e-4)

print(f"Final positions: {particles.positions[:3]}")
```

### From an LLM tool spec

```json
{"tool": "cfd_lagrangian_track", "n_particles": 500,
 "diameter_m": 50e-6, "injection_velocity": [10,0,0],
 "fluid_velocity": [5,0,0], "n_steps": 1000}
```

## How it works

Each particle is a point mass with position x and velocity v. The equation of motion is: m dv/dt = F_drag + F_gravity + F_added_mass. The Schiller-Naumann drag: Cd = 24/Re_p (1 + 0.15 Re_p^0.687) for Re_p < 800, Cd = 0.44 for Re_p ≥ 800. The drag force is F_drag = ½ ρ_f Cd A_p |v_rel| v_rel, where A_p is the particle cross-section and v_rel = v_fluid - v_particle.

Two-way coupling adds the negative of the particle drag force to the fluid momentum source at the particle's cell.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `schiller_naumann_cd(Re_p)` | `float` | Drag coefficient |
| `step_particles_one_way(field, fluid_vel_fn, dt)` | `ParticleField` | One-way coupled step |
| `step_particles_two_way(field, fluid_state, dt)` | `(ParticleField, momentum_source)` | Two-way coupled step |

`Particle` fields: `position`, `velocity`, `diameter`, `density`, `Re_p`.

## Example

```python
cd = schiller_naumann_cd(Re_p=10.0)
print(f"Cd at Re_p=10: {cd:.4f}")  # ~3.7 (Stokes would give 2.4)
```

## Honest caveats

One-way coupling is valid for particle volume fractions below ~1%. Above that, two-way and four-way (particle-particle) coupling are needed. This module does not include evaporation, coalescence, or breakup — for spray combustion, use a coupled DPM solver in OpenFOAM. Brownian motion is not implemented (important for particles < 1 µm).

## References

- Schiller & Naumann (1933). "A drag coefficient correlation." *VDI Zeitung* 77.
- Crowe, Schwarzkopf, Sommerfeld & Tsuji (2011). *Multiphase Flows with Droplets and Particles*, 2nd ed.
