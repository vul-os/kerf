# FEM Nonlinear Material and Plasticity

*Domain: Structural FEM · Module: `packages/kerf-fem/src/kerf_fem/nonlinear.py` · Shipped: Wave 10*

## Overview

Nonlinear finite element analysis for 1-D bars and 2-D trusses with elastic-perfectly-plastic or bilinear-hardening material models. Implements incremental-iterative Newton-Raphson solver with load step control, return-mapping plasticity algorithm (radial return), and plastic strain tracking. Companion module `nonlinear_bar.py` provides the `fem_nonlinear_bar` LLM tool wrapper.

## When to use

- Computing the plastic collapse load of a truss or bar assembly.
- Checking plastic hinge formation sequence in a framed structure.
- Validating material models before running a full CalculiX nonlinear analysis.

## API

```python
from kerf_fem.nonlinear import (
    ElasticPlasticBar,
    solve_nonlinear_bar,
    TrussElement, PlasticTruss,
    solve_truss_plastic,
)

bar = ElasticPlasticBar(
    E=200e9, sigma_y=250e6, H=2e9,  # isotropic hardening modulus
    A=1e-4, L=0.5,
)
result = solve_nonlinear_bar(bar, axial_force=30000, n_steps=20)
print(result["plastic_strain"])
print(result["stress_pa"])
```

## LLM tools

`fem_nonlinear_bar`, `fem_truss_plastic`

## References

- Simo & Hughes, *Computational Inelasticity* (1998).
- de Souza Neto, Peric & Owen, *Computational Methods for Plasticity* (2008).

## Honest caveats

The pure-Python solver is 1-D (bars) and 2-D (trusses) only. Plane-stress/strain, shell, and 3-D solid plasticity are routed to CalculiX via `fem_run`. Geometric nonlinearity (large-strain plasticity) is not implemented; the solver assumes small-strain kinematics. Kinematic hardening is not currently available — only isotropic hardening.
