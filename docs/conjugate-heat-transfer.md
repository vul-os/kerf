# Conjugate Heat Transfer

*Domain: CFD · Module: `packages/kerf-cfd/src/kerf_cfd/heat_transfer.py` · Shipped: Wave 9*

## Overview

Two solvers for conjugate heat transfer (CHT) and buoyancy-driven convection. `CompositeWallCHT` gives the exact analytic series-resistance solution for a multi-layer wall with convective boundary conditions on both sides. `CavityNaturalConvection` solves 2-D Boussinesq natural convection in a differentially heated square cavity using a projection-method Navier-Stokes solver coupled to a convection-diffusion energy equation. Benchmarks against the de Vahl Davis (1983) reference at Ra = 10³–10⁶.

## When to use

- Steady-state heat flux and temperature profile through a composite wall (PCB, building envelope, pressure vessel insulation).
- Natural convection in electronics enclosures or building cavities.
- Nusselt number estimation for enclosure design without running a full 3-D CFD case.

## API

```python
from kerf_cfd.heat_transfer import (
    CompositeWallCHT,
    composite_wall_heat_flux,
    CavityNaturalConvection,
    cavity_nusselt,
)

# Multi-layer wall: aluminium + foam + aluminium
wall = CompositeWallCHT(
    layers=[
        {"thickness": 0.003, "k": 160.0},  # Al
        {"thickness": 0.050, "k": 0.04},   # foam
        {"thickness": 0.003, "k": 160.0},  # Al
    ],
    h_left=10.0,   T_fluid_left=20.0,
    h_right=25.0,  T_fluid_right=80.0,
)
q = composite_wall_heat_flux(wall)

# Natural convection in a 1m cavity
cav = CavityNaturalConvection(Ra=1e5, Pr=0.71, N=32)
Nu = cavity_nusselt(cav)
```

## LLM tools

`cfd_run` (analysis_type `"cfd_thermal"`)

## References

- de Vahl Davis, "Natural convection of air in a square cavity: a bench mark numerical solution", *IJNMF* 3(3), 1983.
- Incropera et al., *Fundamentals of Heat and Mass Transfer*, 7th ed.

## Honest caveats

`CompositeWallCHT` assumes 1-D steady-state heat flow and uniform material properties per layer. Radiation is not included. `CavityNaturalConvection` uses the Boussinesq approximation valid for small temperature differences (ΔT/T_ref << 1). At Ra > 10⁶ the solver may not converge on coarse grids; increase N to at least 64.
