# State-Space Models and LQR Design

*Domain: Controls · Module: `packages/kerf-cad-core/src/kerf_cad_core/controls/statespace.py` · Shipped: Wave 9*

## Overview

State-space model analysis and optimal control design: controllability/observability Gramians, Ackermann pole placement, discrete LQR via the algebraic Riccati equation (ARE), Luenberger observer gain design, continuous-to-discrete conversion (ZOH), discrete stability, and a digital PID step-response simulator. All algorithms are pure Python; no scipy required.

## When to use

- Designing a full-state feedback controller (pole placement or LQR).
- Checking controllability and observability before designing a state estimator.
- Converting a continuous-time model to discrete time for embedded implementation.
- Designing a Luenberger observer for state estimation.

## API

```python
from kerf_cad_core.controls.statespace import (
    ss_model, controllability_matrix, observability_matrix,
    pole_placement_ackermann, lqr, luenberger_gains, c2d,
)

# Define A, B, C, D matrices for a double integrator
model = ss_model(
    A=[[0,1],[0,0]], B=[[0],[1]],
    C=[[1,0]], D=[[0]],
)

# Controllability check
Wc = controllability_matrix(model)

# LQR gain design
result = lqr(model, Q=[[1,0],[0,1]], R=[[0.1]])
K = result["K"]   # feedback gain matrix

# Luenberger observer poles
L = luenberger_gains(model, desired_poles=[-5, -6])

# Discretise at Ts = 0.01 s
disc = c2d(model, Ts=0.01)
```

## LQR tools

`feature_control_lqr`, `feature_control_pole_placement`, `feature_control_observer`

## References

- Ogata, *Modern Control Engineering*, 5th ed.
- Anderson & Moore, *Optimal Control: Linear Quadratic Methods* (1990).

## Honest caveats

The LQR solver uses a finite-horizon iterative Riccati solver (backwards recursion) which may not converge for unstabilisable systems. Verify controllability before calling `lqr`. The `c2d` conversion uses the matrix exponential series method; for very small Ts relative to the fastest pole, increase the series truncation order or use exact expm.
