# FEM Linear Static Analysis

*Domain: Structural FEM · Module: `packages/kerf-fem/src/kerf_fem/linear_static.py` · Shipped: Wave 8*

## Overview

Hermite-cubic Euler-Bernoulli beam elements and axial bar elements assembled into exact linear-static solvers. The element formulations are analytic-exact for the polynomial fields that arise in canonical Roark/Timoshenko cases (tip-load cantilever, UDL simply-supported, fixed-fixed). For 3-D solid and shell FEA, the `fem_run` tool dispatches to CalculiX.

## When to use

- Deflection, slope, and reaction calculations for beams under concentrated or distributed loads.
- Axial bar stress and thermal stress calculations.
- Rapid sizing before running a full 3-D CalculiX job.

## API

```python
from kerf_fem.linear_static import (
    solve_axial_bar,
    solve_beam,
    solve_thermal_stress_bar,
)

# Cantilever beam, tip load
result = solve_beam(
    E=200e9, I=8.3e-6, L=1.0,
    supports={"0": "clamped"},
    loads={"1.0": {"P": -5000}},
    n_elem=10,
)
print(result["tip_deflection"])   # m

# Axial bar with thermal mismatch
result = solve_thermal_stress_bar(E=70e9, alpha=23e-6, dT=50)
```

## LLM tools

`fem_run`, `fem_nonlinear_bar`

## References

- Roark & Young, *Formulas for Stress and Strain*, 9th ed., Table 8.1.
- Hughes, *The Finite Element Method*, ch. 1–2.

## Honest caveats

The pure-Python solvers handle 1-D bar and Euler-Bernoulli beam problems only. They do not cover shear deformation (Timoshenko beam), torsion, or 2-D/3-D elements. For these, use `fem_run` which dispatches to CalculiX. The beam solver requires nodes at all load and support points; intermediate nodes are used only for convergence verification.
