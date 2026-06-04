# CFD SIMPLE Incompressible Solver

*Domain: CFD · Module: `packages/kerf-cfd/src/kerf_cfd/simple_solver.py` · Shipped: Wave 9*

## Overview

A finite-volume 2-D incompressible Navier-Stokes solver using the SIMPLE (Semi-Implicit Method for Pressure-Linked Equations) algorithm on a staggered MAC grid with first-order upwind convection. Validated against Ghia et al. (1982) lid-driven cavity reference data at Re = 100, 400, and 1000. Used as the embedded fast-solve path before dispatching to OpenFOAM for production runs.

## When to use

- Quick convergence check for 2-D cavity or channel flows during pre-processing.
- Generating velocity/pressure field summaries without external solver infrastructure.
- Teaching and verification of SIMPLE algorithm behaviour.

## API

```python
from kerf_cfd.simple_solver import (
    SolverConfig, SolverState,
    solve_simple,
    u_on_vertical_centreline,
    v_on_horizontal_centreline,
    compare_ghia_re100,
)

cfg = SolverConfig(
    Re=100,
    ni=32, nj=32,      # grid cells
    max_iter=2000,
    tol=1e-4,
    case="lid_driven_cavity",
)
state: SolverState = solve_simple(cfg)

u_profile = u_on_vertical_centreline(state)
```

## LLM tools

`cfd_run` (analysis_type `"cfd"`), `cfd_rans_solve`

## References

- Patankar & Spalding, "A calculation procedure for heat, mass and momentum transfer in three-dimensional parabolic flows", *IJHMT* 15(10), 1972.
- Ghia, Ghia & Shin, "High-Re solutions for incompressible flow using the Navier-Stokes equations and a multigrid method", *JCP* 48(3), 1982.

## Honest caveats

First-order upwind introduces numerical diffusion at Re > 400 on the default 32×32 grid. Published studies document that u-velocity profiles at the vertical centreline deviate from Ghia reference by up to 8% at Re=1000 on coarse grids. Use at least 64×64 for Re > 400 or switch to the OpenFOAM path. The solver is 2-D only; 3-D cases are routed to OpenFOAM.
