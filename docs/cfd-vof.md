# Volume of Fluid (VoF) Multiphase Solver

> Simulate free-surface flows (water-air interfaces, sloshing, filling) using PLIC interface reconstruction and surface-tension forces.

**Module**: `packages/kerf-cfd/src/kerf_cfd/multiphase/vof.py`
**Shipped**: Wave 10
**LLM tools**: `cfd_vof_run`

---

## What it is

The Volume of Fluid (VoF) method tracks a free surface between two immiscible fluids (typically water and air) by transporting a scalar field α (volume fraction: 0 = pure air, 1 = pure water, 0 < α < 1 = interface). VoF is the standard method for wave tanks, tank sloshing, pipe filling, coastal flooding, and die-casting simulation.

This module implements the PLIC (Piecewise Linear Interface Calculation) algorithm for sharp interface reconstruction, mixture density and viscosity as α-weighted averages, and a CFL-limited explicit time step for the α transport equation. It is validated for sloshing in rectangular tanks and can be coupled with the OpenFOAM bridge to set up `interFoam` cases.

## How to use it

### From chat (natural language)

> "Simulate 2D sloshing in a rectangular tank 1m × 0.5m, initial water height 0.3m, acceleration 0.1g"

The LLM calls `cfd_vof_run` with the tank geometry and excitation.

### From Python

```python
from kerf_cfd.multiphase.vof import (
    VofState, step_vof, mixture_density, mixture_viscosity,
    interface_reconstruction_plic,
)

state = VofState(
    alpha=alpha_field,     # n-cell float array
    rho_phase=(1000, 1.2), # water, air densities kg/m³
    mu_phase=(1e-3, 1.8e-5),
    velocity=u_field,      # n×2 array
)
for _ in range(100):
    state = step_vof(state, face_areas, cell_volumes, neighbours, dt=1e-4)

plic = interface_reconstruction_plic(state.alpha, cell_centres, cell_volumes)
print(f"Interface cells: {len(plic.interface_cells)}")
```

### From an LLM tool spec

```json
{"tool": "cfd_vof_run", "tank_width_m": 1.0, "tank_height_m": 0.5,
 "water_height_m": 0.3, "excitation_g": 0.1, "n_steps": 1000}
```

## How it works

The volume fraction α is transported: ∂α/∂t + ∇·(αu) = 0. PLIC reconstructs the interface in each cell as a planar segment with normal n̂ = -∇α/|∇α| and position determined by the volume constraint α = Volume(fluid side of plane) / Cell_volume. Fluxes across faces are computed from the PLIC geometry and the face velocity. Mixture properties are linearly interpolated: ρ = α ρ₁ + (1-α) ρ₂.

The CFL condition limits the time step: dt = CFL_max × min(V_cell / |u · A_face|) to prevent α overshoot.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `step_vof(state, face_areas, cell_vols, neighbours, dt)` | `VofState` | One VoF time step |
| `mixture_density(state)` | `np.ndarray` | Cell mixture densities |
| `mixture_viscosity(state)` | `np.ndarray` | Cell mixture viscosities |
| `interface_reconstruction_plic(alpha, ...)` | `PlicResult` | PLIC interface geometry |

## Example

```python
rho_mix = mixture_density(state)
print(f"Interface cell rho range: {rho_mix[(state.alpha > 0.01) & (state.alpha < 0.99)].mean():.1f}")
```

## Honest caveats

The PLIC reconstruction is second-order in space but can produce interface smearing over time due to numerical diffusion in the α advection. For sharp interfaces with high density ratios (e.g. water/air = 830:1), use geometric flux splitting (plicRDF) available in OpenFOAM `interFoam`. Surface tension is computed via the Continuum Surface Force (CSF) model (Brackbill 1992) — not yet implemented in this module; for problems where surface tension is significant (small capillary number), use OpenFOAM directly.

## References

- Hirt & Nichols (1981). "Volume of Fluid (VOF) method for the dynamics of free boundaries." *JCP* 39(1).
- Youngs (1982). "Time-dependent multi-material flow with large fluid distortion." *Numerical Methods for Fluid Dynamics*.
