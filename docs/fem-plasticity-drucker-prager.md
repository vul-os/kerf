# Drucker-Prager Plasticity

> Model pressure-dependent yielding in concrete, rock, and granular soils with the Drucker-Prager criterion.

**Module**: `packages/kerf-fem/src/kerf_fem/plasticity/drucker_prager.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

The Drucker-Prager (DP) criterion extends von Mises plasticity to materials whose yield strength increases with hydrostatic pressure — concrete, rock, cemented sands, and filled polymers. The yield surface is a cone in principal stress space. The module provides yield function evaluation, associative and non-associative (dilatancy) return mapping, and consistent tangent.

## How to use it

### From chat

> "Check if a concrete element at stress state (−20, −5, −2) MPa with friction angle 37° has yielded."

### From Python

```python
from kerf_fem.plasticity.drucker_prager import (
    DruckerPragerMaterial, yield_function_dp, return_map_dp,
)

mat = DruckerPragerMaterial(
    E=30e9, nu=0.2,
    cohesion=3e6,       # c in Pa
    friction_angle=37.0,  # φ in degrees
    dilatancy_angle=10.0, # ψ in degrees (non-associative)
)
sigma = [-20e6, -5e6, -2e6, 0, 0, 0]  # Voigt notation
f = yield_function_dp(mat, sigma)
print(f"f = {f:.3e} Pa (> 0 means yielded)")
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "drucker_prager", "cohesion": 3e6, "friction_angle": 37.0}}
```

## How it works

The DP yield function in terms of first invariant `I₁` and second deviatoric invariant `J₂`: `f = α I₁ + √J₂ − k`, where `α` and `k` are functions of the Mohr-Coulomb cohesion and friction angle (circumscribed matching). Return mapping solves for the plastic multiplier `Δγ` such that the stress is on the apex cone or conical surface, depending on the stress triaxiality regime. The dilatancy angle `ψ` controls volume change during plastic flow.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `yield_function_dp(mat, sigma)` | `float` | DP yield function |
| `return_map_dp(mat, state, d_eps)` | `DPState` | DP stress update with return map |
| `DruckerPragerMaterial(E, nu, cohesion, friction_angle, dilatancy_angle)` | instance | Material parameters |

## Example

```python
f = yield_function_dp(mat, [-20e6, -5e6, -2e6, 0, 0, 0])
# -1.24e6 Pa — not yielded (f < 0)
```

## Honest caveats

This is a small-strain, infinitesimal-deformation implementation. Large-deformation (finite-strain) geomechanics requires a logarithmic strain formulation. The DP model does not cap the yield surface at high hydrostatic pressure (cap plasticity); for compaction-dominated problems use a Cam-Clay model. Softening and regularisation (non-local) are not implemented.

## References

- Drucker & Prager, "Soil mechanics and plastic analysis or limit design," *Q. Appl. Math.* 10(2), 1952.
- de Souza Neto et al., *Computational Methods for Plasticity*, Wiley (2008), Ch. 8.
