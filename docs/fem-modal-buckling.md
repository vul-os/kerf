# FEM Modal Analysis and Buckling

*Domain: Structural FEM · Module: `packages/kerf-fem/src/kerf_fem/modal.py` · Shipped: Wave 9*

## Overview

Computes natural frequencies and mode shapes for Euler-Bernoulli beam structures, and Euler buckling loads for columns, via a pure-Python generalised eigensolver (Cholesky + Jacobi). The `beam_natural_frequencies` function assembles consistent mass and stiffness matrices and returns angular frequencies, Hz values, and mode shapes. `euler_buckling_load` handles the four classical end-condition cases. For full 3-D modal/buckling, `fem_run` dispatches to CalculiX.

## When to use

- Checking natural frequencies of a beam or frame against excitation frequencies.
- Euler critical load estimation for slender column design per AISC / Eurocode.
- Modal verification before running a 3-D CalculiX eigensolution.

## API

```python
from kerf_fem.modal import (
    beam_natural_frequencies,
    euler_buckling_load,
    plate_first_mode_simply_supported,
)

# Simply-supported steel beam
modes = beam_natural_frequencies(
    E=200e9, I=8.3e-6, rho=7850, A=6.45e-3, L=2.0,
    supports="simply_supported", n_modes=5, n_elem=20,
)
for m in modes["modes"]:
    print(f"  f = {m['freq_hz']:.2f} Hz")

# Euler buckling (fixed-free column)
buck = euler_buckling_load(E=200e9, I=8.3e-6, L=3.0, K_factor=2.0)
print(buck["P_cr"])  # Newtons
```

## LLM tools

`fem_run`, `fem_buckling_linear`, `fem_harmonic_response`, `fem_random_vibration_psd`

## References

- Thomson, *Theory of Vibration with Applications*, 5th ed.
- Euler, "De curvis elasticis" (1744) — buckling of slender columns.
- Timoshenko & Gere, *Theory of Elastic Stability*, 2nd ed.

## Honest caveats

The pure-Python modal solver covers 1-D Euler-Bernoulli beams only. Gyroscopic effects, damping matrices, and geometric stiffness from pre-stress are not included. For 3-D shell/solid modal analysis use `fem_run`. The plate first mode is derived from the Navier series for simply-supported rectangular plates — other boundary conditions require numerical methods.
