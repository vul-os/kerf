# CR3BP Libration Orbits (Halo, Lyapunov, Lissajous)

> Design Halo, Lyapunov, and Lissajous orbits around L1/L2 Lagrange points in the Circular Restricted Three-Body Problem.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/aerospace/libration_orbits.py`
**Shipped**: Wave 10C2
**LLM tools**: `aerospace_compute_lagrange_points`, `aerospace_design_halo_orbit`, `aerospace_design_lyapunov_orbit`, `aerospace_design_lissajous_orbit`

---

## What it is

The CR3BP module models spacecraft motion under the combined gravity of two massive bodies (e.g., Earth-Moon, Sun-Earth) in their co-rotating synodic frame. It computes the five Lagrange (libration) points, designs Halo orbits using Richardson's 3rd-order analytic initial conditions corrected by a differential corrector, and designs planar Lyapunov and 3-D Lissajous (quasi-periodic) orbits.

## How to use it

### From chat

> "Design an L2 Halo orbit for the Earth-Moon system with z-amplitude 8000 km."

### From Python

```python
from kerf_cad_core.aerospace.libration_orbits import (
    CR3BPSystem, compute_lagrange_points,
    design_halo_orbit, design_lyapunov_orbit,
)

system = CR3BPSystem(
    m1=5.974e24,  # Earth mass, kg
    m2=7.342e22,  # Moon mass, kg
    L=384400e3,   # distance, m
    name="Earth-Moon",
)
lagrange_pts = compute_lagrange_points(system)
L2 = next(p for p in lagrange_pts if p.name == "L2")

halo = design_halo_orbit(
    system=system,
    libration_point="L2",
    z_amplitude_km=8000,
    family="northern",
    n_periods=2,
)
print(halo.period_days, halo.initial_state)
```

### From an LLM tool spec

```json
{"tool": "aerospace_design_halo_orbit", "input": {"system": "Earth-Moon", "libration_point": "L2", "z_amplitude_km": 8000, "family": "northern"}}
```

## How it works

Lagrange points are found by solving the 5th-degree quintic polynomial for the collinear points (L1, L2, L3) and the equilateral triangle positions for L4, L5. Halo orbit initial conditions are seeded from Richardson's 3rd-order analytic approximation (1980) and corrected to machine precision by a half-period differential corrector: iterate the initial velocity `vy₀` until the perpendicular crossing condition `ẋ = ż = 0` is met. The trajectory is integrated by a fixed-step RK4 in the synodic frame.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `compute_lagrange_points(system)` | `list[LagrangePoint]` | L1–L5 positions in synodic frame |
| `design_halo_orbit(system, libration_point, z_amplitude_km, family)` | `HaloOrbit` | Corrected Halo orbit IC and period |
| `design_lyapunov_orbit(system, libration_point, amplitude_km)` | `dict` | Planar Lyapunov orbit |
| `design_lissajous_orbit(system, libration_point, Ax_km, Az_km, phase)` | `dict` | Quasi-periodic Lissajous orbit |

## Example

```python
halo = design_halo_orbit(system, "L2", z_amplitude_km=8000, family="northern")
# HaloOrbit(period_days=14.3, initial_state=[...], corrector_converged=True)
```

## Honest caveats

The RK4 integrator uses a fixed timestep; long-duration propagation (> 10 periods) may accumulate error. The differential corrector may not converge for large amplitudes near the forbidden region boundary. Practical orbit maintenance requires station-keeping manoeuvres not computed here. The CR3BP does not include solar radiation pressure, J2, or fourth-body effects.

## References

- Richardson, D.L., "Analytic Construction of Periodic Orbits about the Collinear Points," *Celestial Mechanics* 22(3), 1980.
- Szebehely, V., *Theory of Orbits: The Restricted Problem of Three Bodies*, Academic Press (1967).
