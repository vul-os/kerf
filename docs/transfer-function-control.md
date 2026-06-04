# Transfer Function and PID Analysis

*Domain: Controls · Module: `packages/kerf-cad-core/src/kerf_cad_core/controls/system.py` · Shipped: Wave 9*

## Overview

Classical linear control analysis: second-order step/impulse response, Routh-Hurwitz stability, Bode gain/phase margins, steady-state error coefficients, root-locus breakaway points, and PID tuning via Ziegler-Nichols (open/closed), Cohen-Coon, and IMC methods. All computations are pure Python; no scipy required.

## When to use

- Checking closed-loop stability of a control system design.
- Tuning PID gains from process model parameters.
- Generating Bode plots and gain/phase margin reports.
- Teaching control theory with numerically exact canonical examples.

## API

```python
from kerf_cad_core.controls.system import (
    second_order_spec, second_order_step,
    routh_hurwitz, bode_point, gain_phase_margins,
    pid_zn_open, pid_zn_closed,
    pid_cohen_coon, pid_imc,
)

# 2nd-order system specs from ωn and ζ
spec = second_order_spec(wn=10.0, zeta=0.7)

# Step response
resp = second_order_step(wn=10.0, zeta=0.7,
                          t_samples=[i*0.01 for i in range(100)])

# PID tuning via IMC
gains = pid_imc(K=2.0, tau=5.0, theta=0.5, lambda_c=1.0)
print(gains["Kp"], gains["Ti"], gains["Td"])

# Stability check
rh = routh_hurwitz(coeffs=[1, 3, 3, 1])
print(rh["stable"])
```

## LLM tools

`feature_control_pid_tune`, `feature_control_bode`, `feature_control_stability`

## References

- Franklin, Powell & Emami-Naeini, *Feedback Control of Dynamic Systems*, 8th ed.
- Ziegler & Nichols, "Optimum settings for automatic controllers", *Trans. ASME* 64, 1942.
- Rivera, Morari & Skogestad, "Internal model control: PID controller design", *I&EC Proc. Des. Dev.* 25, 1986.

## Honest caveats

All transfer-function analysis is for linear, time-invariant (LTI) systems. Nonlinear plants, time-varying parameters, and discrete-time systems have separate handling in `statespace.py`. Root-locus breakaway uses a real-axis sweep — complex-plane breakaway points away from the real axis require the full derivative equation.
