# Thermo-Elastic Coupled Analysis

> Solve coupled temperature and displacement fields for thermally loaded structures.

**Module**: `packages/kerf-fem/src/kerf_fem/multiphysics/thermal_structural.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

The thermo-elastic module solves a 1-D bar (or rod assembly) with temperature-dependent elastic modulus and thermal expansion under a prescribed temperature field or convective boundary condition. It supports both staggered (sequential) and monolithic (simultaneous) coupling. Output includes temperature distribution, axial displacement, and thermal stress.

## How to use it

### From chat

> "Compute the thermal stress in a 1 m aluminium bar clamped at both ends, heated uniformly by 100°C."

### From Python

```python
from kerf_fem.multiphysics.thermal_structural import (
    ThermoElasticMaterial, solve_thermo_elastic_staggered,
)

mat = ThermoElasticMaterial(
    E0=70e9, alpha_E=-500e6,     # E = E0 + alpha_E * (T - T_ref)
    alpha_th=23e-6,               # thermal expansion coefficient
    k=200.0,                      # thermal conductivity W/(m·K)
    T_ref=20.0,                   # reference temperature °C
)
mesh = {"n_nodes": 11, "length_m": 1.0}
thermal_bcs = {"T_left": 20.0, "T_right": 120.0}
structural_bcs = {"u_left": 0.0, "u_right": 0.0}

result = solve_thermo_elastic_staggered(mat, mesh, thermal_bcs, structural_bcs, n_iter=5)
print(result.T_max, result.sigma_max)
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "thermo_elastic", "alpha_th": 23e-6, "T_uniform": 100, "boundary": "clamped"}}
```

## How it works

In the staggered scheme, the thermal problem is solved first (`_build_thermal_K`, `_thermal_force_vector`) using a 1-D heat conduction finite element. The resulting nodal temperatures are passed to the structural step, which builds the element stiffness with temperature-dependent E and adds the thermal strain force vector `_thermal_strain_force`. The two sub-problems are iterated to convergence. The monolithic scheme assembles the coupled system matrix in one step.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `solve_thermo_elastic_staggered(mat, mesh, thermal_bcs, structural_bcs, n_iter)` | `CoupledResult` | Staggered thermo-elastic solution |
| `solve_thermo_elastic_monolithic(mat, mesh, thermal_bcs, structural_bcs)` | `CoupledResult` | Monolithic coupled solution |
| `ThermoElasticMaterial(E0, alpha_E, alpha_th, k, T_ref)` | instance | Temperature-dependent material |

## Example

```python
result = solve_thermo_elastic_staggered(mat, mesh, thermal_bcs, structural_bcs, n_iter=5)
# CoupledResult(T_max=120°C, sigma_max=-161.0 MPa, u_tip_mm=0.0)
```

## Honest caveats

The module solves 1-D rod/bar problems only. 2-D/3-D thermo-elastic problems are handled by CalculiX via `fem_run`. The staggered scheme may not converge for strongly coupled problems (large α_E); use the monolithic scheme or reduce the thermal step. Radiation heat transfer and phase-change latent heat are not included.

## References

- Zienkiewicz & Taylor, *The Finite Element Method*, Vol. 2, 7th ed. (2013), Ch. 14.
- Lewis, Morgan & Thomas, *The Finite Element Method in Heat Transfer Analysis*, Wiley (1996).
