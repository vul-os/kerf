# RANS Turbulence Solver (k-ω SST)

*Domain: CFD · Module: `packages/kerf-cfd/src/kerf_cfd/k_omega_sst.py` · Shipped: Wave 9*

## Overview

Implements the Menter (1994, 2003) two-equation k-ω SST turbulence closure for incompressible RANS flows. The SST model blends the Wilcox k-ω model near walls (where it is well-behaved) with the standard k-ε model in the freestream (where k-ω is overly sensitive to freestream BC). Blending is via the F1 function. The 1-D equilibrium solver targets fully-developed channel and boundary-layer flows and is used for reference-value generation and wall-function calibration.

## When to use

- Estimating turbulent viscosity and boundary-layer thickness for external aerodynamic flows.
- Generating log-layer reference states for OpenFOAM `turbulentInletBC` specification.
- Validating RANS mesh y+ requirements before running a 3-D case.
- Back-of-envelope flow separation estimation using the BFS reattachment correlator.

## API

```python
from kerf_cfd.k_omega_sst import (
    compute_F1, compute_F2, compute_nut,
    solve_equilibrium,
    channel_log_layer_state,
    estimate_bfs_reattachment,
    sst_constants,
)

consts = sst_constants()

# Equilibrium k, ω in a channel at Re_tau = 395
state = solve_equilibrium(Re_tau=395, nu=1.5e-5)

# Estimate step-height reattachment length
x_r = estimate_bfs_reattachment(h=0.01, U_ref=10.0, nu=1.5e-5)
```

## LLM tools

`cfd_select_turbulence_model`, `cfd_rans_solve`

## References

- Menter, "Two-equation eddy-viscosity turbulence models for engineering applications", *AIAA J.* 32(8), 1994.
- Menter, Kuntz & Langtry, "Ten years of industrial experience with the SST turbulence model", *Turbulence, Heat and Mass Transfer 4*, 2003.

## Honest caveats

The 1-D implementation covers fully-developed channel and equilibrium boundary-layer flows only. Strongly adverse pressure gradients, separation, and reattachment are estimated via correlations, not first-principles. 3-D RANS cases are dispatched to OpenFOAM via the `cfd_run` tool; the Python solver here provides reference values and model-constant verification.
