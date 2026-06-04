# RANS Turbulence Modelling (k-ε and k-ω SST)

> Solve Reynolds-Averaged Navier-Stokes with k-ε or k-ω SST turbulence closure — from flat-plate boundary layers to channel flows.

**Module**: `packages/kerf-cfd/src/kerf_cfd/rans/k_epsilon.py`, `packages/kerf-cfd/src/kerf_cfd/k_omega_sst.py`
**Shipped**: Wave 9
**LLM tools**: `cfd_rans_solve`

---

## What it is

Reynolds-Averaged Navier-Stokes (RANS) models replace the turbulent fluctuations with an eddy viscosity νt that is computed from a turbulence transport model. The k-ε model (Jones & Launder 1972) solves transport equations for turbulent kinetic energy k and its dissipation rate ε. The k-ω SST model (Menter 1994) blends k-ω near walls (more accurate in adverse pressure gradients) with k-ε in the freestream — making it the default for external aerodynamics.

Kerf implements both models in pure Python for 1D channel and boundary-layer problems, and exposes them as initial-field generators for OpenFOAM 3D cases. The 1D channel solver `solve_channel_keps` is validated against the Re=10,000 DNS dataset of Moser et al. (1999).

## How to use it

### From chat (natural language)

> "Compute the k-ε eddy viscosity profile for a channel flow at Re=10,000"

The LLM calls `cfd_rans_solve` with the channel geometry and Reynolds number.

### From Python

```python
from kerf_cfd.rans.k_epsilon import (
    step_k_epsilon, compute_eddy_viscosity_ke,
    KEpsilonConstants, KEpsilonState,
)
from kerf_cfd.rans_keps import solve_channel_keps, ChannelKepsConfig

cfg = ChannelKepsConfig(Re=10000, n_cells=128, L=1.0, growth_ratio=1.05)
state = solve_channel_keps(cfg)
print(f"Wall y+: {state.y_plus_wall:.2f}")
print(f"Centreline velocity: {state.u_centreline:.4f}")
```

### From an LLM tool spec

```json
{"tool": "cfd_rans_solve", "model": "kEpsilon", "Re": 10000,
 "geometry": "channel", "n_cells": 128}
```

## How it works

The k-ε model transport equations (in steady 1D form) are:
- ∂(ρUk)/∂x = Pk - ε + ∂/∂y[(μ + μt/σk) ∂k/∂y]
- ∂(ρUε)/∂x = Cε1 Pk ε/k - Cε2 ρε²/k + ∂/∂y[(μ + μt/σε) ∂ε/∂y]

where Pk is the turbulence production, μt = ρ Cμ k²/ε is the eddy viscosity. Constants: Cμ=0.09, Cε1=1.44, Cε2=1.92, σk=1.0, σε=1.3. The TDMA (tridiagonal matrix algorithm) solves each equation on a geometric grid stretched toward the wall.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `compute_eddy_viscosity_ke(k, eps)` | `float` | νt from k and ε |
| `step_k_epsilon(state, dt, constants)` | `KEpsilonState` | Single time step |
| `solve_channel_keps(cfg)` | `ChannelKepsState` | Full 1D channel solver |
| `validate_channel_re10000(state)` | `dict` | Comparison to Moser DNS |

## Example

```python
cfg = ChannelKepsConfig(Re=10000, n_cells=64, L=1.0)
state = solve_channel_keps(cfg)
validation = validate_channel_re10000(state)
print(f"u_cl error vs DNS: {validation['u_cl_error']:.1%}")
```

## Honest caveats

RANS models are time-averaged and cannot capture unsteady turbulent structures (vortex shedding, buffeting). The k-ε model over-predicts turbulent viscosity in adverse pressure gradients; use k-ω SST for flows with separation. Wall functions are required unless the mesh is fine enough to resolve the viscous sublayer (y+ < 1). The 1D implementation is for validation and initial-field generation only; production 3D RANS runs require OpenFOAM.

## References

- Jones & Launder (1972). "The prediction of laminarization with a two-equation model of turbulence." *IJHMT* 15(2).
- Menter (1994). "Two-equation eddy-viscosity turbulence models for engineering applications." *AIAA J* 32(8).
- Moser, Kim & Mansour (1999). "Direct numerical simulation of turbulent channel flow up to Re=590." *Physics of Fluids* 11(4).
