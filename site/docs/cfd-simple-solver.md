# CFD SIMPLE Incompressible Solver

> 2D incompressible Navier-Stokes on a staggered MAC grid via the SIMPLE algorithm — fast convergence checks before dispatching to OpenFOAM.

**Module**: `packages/kerf-cfd/src/kerf_cfd/cfd_navier_stokes.py`
**Shipped**: Wave 9
**LLM tools**: `cfd_run`, `cfd_rans_solve`

---

## What it is

The SIMPLE (Semi-Implicit Method for Pressure-Linked Equations) algorithm is the workhorse of incompressible CFD. It decouples the velocity-pressure coupling in the Navier-Stokes equations via a predictor-corrector scheme: predict the velocity field ignoring the pressure gradient, solve a pressure-correction equation (the discrete Poisson equation), then correct velocities to satisfy continuity.

Kerf's SIMPLE solver runs on a 2D staggered MAC grid with first-order upwind convection. It is validated against the Ghia et al. (1982) lid-driven cavity benchmark at Re = 100, 400, and 1000. Engineers use it as a fast pre-screening step: a 32×32 grid at Re=100 converges in under 2000 iterations (seconds), giving velocity profiles before committing to an OpenFOAM run.

## How to use it

### From chat (natural language)

> "Run a lid-driven cavity simulation at Re=400 on a 64×64 grid and return the velocity profile"

The LLM calls `cfd_run` with `analysis_type='cfd'` and Re=400.

### From Python

```python
from kerf_cfd.cfd_navier_stokes import (
    NavierStokesSolver, SolverConfig,
)

cfg = SolverConfig(
    Re=100, ni=32, nj=32,
    max_iter=2000, tol=1e-4,
    case="lid_driven_cavity",
)
solver = NavierStokesSolver(cfg)
state = solver.solve()
print(f"Converged: {state.converged} in {state.iterations} iterations")
u_centre = state.u_on_vertical_centreline()
```

### From an LLM tool spec

```json
{"tool": "cfd_run", "analysis_type": "cfd", "Re": 400, "grid": 64,
 "case": "lid_driven_cavity"}
```

## How it works

On a staggered MAC grid, u-velocity components are stored at face centres on vertical faces, and v-velocities on horizontal faces; pressure is stored at cell centres. The SIMPLE loop: (1) assemble the momentum equations with the current pressure field using first-order upwind for convection; (2) solve for predicted velocities; (3) assemble the pressure-correction equation from velocity divergence; (4) correct velocities and pressures; (5) check L∞ residual against tolerance. The pressure-correction equation is solved with TDMA (TriDiagonal Matrix Algorithm) in alternating sweeps.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `SolverConfig(Re, ni, nj, max_iter, tol, case)` | Config | Solver parameters |
| `NavierStokesSolver(cfg).solve()` | `SolverState` | Run SIMPLE iterations |
| `state.u_on_vertical_centreline()` | `np.ndarray` | u-velocity profile |
| `state.compare_ghia_re100()` | `dict` | Validation against Ghia (1982) |

## Example

```python
cfg = SolverConfig(Re=100, ni=32, nj=32, max_iter=2000, tol=1e-4,
                   case="lid_driven_cavity")
state = NavierStokesSolver(cfg).solve()
err = state.compare_ghia_re100()
print(f"Max u-error vs Ghia: {err['max_u_error']:.4f}")  # should be < 0.08
```

## Honest caveats

First-order upwind introduces numerical diffusion proportional to cell size — at Re=1000 on a 32×32 grid, u-velocity profiles deviate from Ghia reference by up to 8%. Use 64×64 or higher for Re > 400. The solver is 2D only; 3D cases, turbulent flows (Re > 10,000), and complex geometries are routed to OpenFOAM.

## References

- Patankar & Spalding (1972). "A calculation procedure for heat, mass and momentum transfer in three-dimensional parabolic flows." *IJHMT* 15(10).
- Ghia, Ghia & Shin (1982). "High-Re solutions for incompressible flow using the Navier-Stokes equations and a multigrid method." *JCP* 48(3).
