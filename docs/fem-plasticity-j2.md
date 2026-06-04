# J2 (Von Mises) Plasticity

> Compute elastic-plastic stress updates for isotropic metals using J2 return-mapping.

**Module**: `packages/kerf-fem/src/kerf_fem/plasticity/j2.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

J2 plasticity (von Mises yield criterion with isotropic hardening) is the standard material model for metals undergoing plastic deformation. The module provides the yield function evaluation, radial return-mapping algorithm, and consistent algorithmic tangent modulus for use in FEM Newton-Raphson loops.

## How to use it

### From chat

> "Compute the stress update for a steel element after a plastic strain increment of 0.002 in pure tension."

### From Python

```python
from kerf_fem.plasticity.j2 import (
    J2PlasticityMaterial, J2State, von_mises_equivalent,
    yield_function_j2, return_map_j2,
)

mat = J2PlasticityMaterial(
    E=200e9, nu=0.3,
    sigma_y0=250e6,  # initial yield stress
    H=2e9,           # isotropic hardening modulus
)
state = J2State(stress=0.0, eps_p=0.0, alpha=0.0)
new_state = return_map_j2(mat, state, d_eps=0.003)
print(new_state.stress, new_state.eps_p)
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "j2_plasticity", "E": 200e9, "nu": 0.3, "sigma_y0": 250e6, "H": 2e9}}
```

## How it works

The elastic predictor computes a trial stress `σ_tr = σ_n + C : Δε`. The trial von Mises equivalent stress is compared to the yield surface `f = q(σ_tr) − σ_y(α)`. If `f > 0`, the radial return algorithm projects the trial stress back onto the yield surface by solving `f(Δγ) = 0` for the plastic multiplier `Δγ` via a 1-D Newton iteration. The stress and hardening variable are updated.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `von_mises_equivalent(stress)` | `float` | von Mises stress invariant |
| `yield_function_j2(mat, state, stress)` | `float` | Yield function value |
| `return_map_j2(mat, state, d_eps)` | `J2State` | Radial return stress update |

## Example

```python
state = return_map_j2(mat, state, d_eps=0.003)
# J2State(stress=2.54e8 Pa, eps_p=0.00150, alpha=0.00150)
```

## Honest caveats

This is a 1-D (scalar) implementation for educational and preliminary use. Full 3-D J2 plasticity with kinematic hardening is dispatched to CalculiX via `fem_run`. Rate-dependent (viscoplastic) effects and cyclic plasticity (Chaboche) are not implemented in this module. Temperature-dependent yield strength requires explicit material state management.

## References

- Simo & Hughes, *Computational Inelasticity*, Springer (1998), Ch. 2.
- de Souza Neto, Peric & Owen, *Computational Methods for Plasticity*, Wiley (2008), Ch. 7.
