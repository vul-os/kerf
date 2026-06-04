# Compressible Flow (Roe FVM and Normal Shocks)

> Solve compressible Euler equations with the Roe approximate Riemann solver — for transonic, supersonic, and shock-capturing problems.

**Module**: `packages/kerf-cfd/src/kerf_cfd/compressible/compressible_flow.py`
**Shipped**: Wave 10
**LLM tools**: `cfd_compressible_run`

---

## What it is

Compressible flow becomes important when the Mach number exceeds ~0.3, where density variations are significant and shock waves can form. The Euler equations (inviscid compressible Navier-Stokes) describe compressible flow; their non-linear hyperbolic character requires specialised numerical schemes that correctly capture shock waves and contact discontinuities without spurious oscillations.

This module implements the Roe approximate Riemann solver on an unstructured finite-volume mesh for 1D and 2D compressible flow, plus the classical normal-shock relations for quick engineering calculations (Mach number, pressure ratio, temperature ratio, density ratio). The Sutherland viscosity law extends the solver to viscous compressible (Navier-Stokes) problems. Engineers use it for supersonic nozzle design, shock tube analysis, and pre-screening before OpenFOAM `rhoCentralFoam` runs.

## How to use it

### From chat (natural language)

> "Compute the pressure ratio across a normal shock at Mach 2.5"

The LLM calls `cfd_compressible_run` with shock analysis type.

### From Python

```python
from kerf_cfd.compressible.compressible_flow import (
    CompressibleState, step_compressible, normal_shock_relations,
    roe_flux,
)

# Normal shock relations at M=2.5
shock = normal_shock_relations(M_1=2.5, gamma=1.4)
print(f"Pressure ratio p2/p1: {shock['p_ratio']:.3f}")
print(f"Mach 2: {shock['M_2']:.4f}")
print(f"Temperature ratio: {shock['T_ratio']:.3f}")
```

### From an LLM tool spec

```json
{"tool": "cfd_compressible_run", "analysis": "normal_shock",
 "M_1": 2.5, "gamma": 1.4}
```

## How it works

The Roe flux computes the numerical flux at a cell interface by solving an approximate Riemann problem using the Roe-averaged state: density √(ρ_L ρ_R), velocity and enthalpy averaged by √ρ weights. The flux is Roe's matrix-based upwind split: F = ½(F_L + F_R) - ½|Ā|(U_R - U_L), where |Ā| is the absolute-value Roe matrix (eigenvalue-based entropy fix applied). This captures shocks and contacts sharply (1-2 cells wide).

Normal shock relations are the Rankine-Hugoniot jump conditions for an ideal gas: p₂/p₁ = (2γM₁² - (γ-1))/(γ+1).

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `roe_flux(U_L, U_R, gamma)` | `np.ndarray[5]` | Roe numerical flux |
| `step_compressible(state, dt)` | `CompressibleState` | One time step |
| `normal_shock_relations(M_1, gamma)` | `dict` | Rankine-Hugoniot relations |

`normal_shock_relations` returns: `M_2`, `p_ratio`, `T_ratio`, `rho_ratio`, `p0_ratio`, `T0_ratio`.

## Example

```python
for M in [1.5, 2.0, 2.5, 3.0]:
    s = normal_shock_relations(M, 1.4)
    print(f"M={M}: p2/p1={s['p_ratio']:.2f}, T2/T1={s['T_ratio']:.2f}")
```

## Honest caveats

The Roe solver is first-order in space by default — extend with MUSCL reconstruction for second-order accuracy. The Roe flux requires an entropy fix near sonic points (M≈1) to avoid entropy-violating expansion shocks; a Harten-Hyman fix is applied. This module solves the Euler equations — viscous effects (boundary layers, viscous shock structure) require the Navier-Stokes extension with Sutherland viscosity. For 3D compressible RANS, use OpenFOAM `rhoCentralFoam`.

## References

- Roe (1981). "Approximate Riemann solvers, parameter vectors, and difference schemes." *JCP* 43(2).
- Anderson (2003). *Modern Compressible Flow*, 3rd ed. McGraw-Hill.
