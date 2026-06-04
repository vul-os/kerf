# Drucker-Prager Plasticity (Pressure-Dependent Yield)

> Compute plastic stress updates for geomaterials and concrete using the Drucker-Prager pressure-dependent yield criterion with associated or non-associated flow.

**Module**: `packages/kerf-fem/src/kerf_fem/plasticity/drucker_prager.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run` (material_model `"drucker_prager"`)

---

## What it is

The Drucker-Prager (DP) yield criterion extends von Mises plasticity to pressure-sensitive materials: concrete, rock, soil, and polymers. The yield surface is a cone in principal stress space: f(σ) = √(J₂) + α I₁ - k ≤ 0, where I₁ is the first stress invariant (hydrostatic pressure) and α, k are material parameters derived from cohesion and friction angle. Unlike J2, DP predicts different yield stresses in compression and tension, matching geomaterial behaviour.

This module implements the return-mapping algorithm for DP plasticity with both associated (flow direction = yield gradient) and non-associated (separate dilation angle) flow rules. Engineers use it to analyse concrete structural elements, soil bearing capacity, and polymer forming.

## How to use it

### From chat (natural language)

> "Compute the stress update for concrete (c=3MPa, φ=35°) after a compressive strain increment of 0.002"

The LLM calls the Drucker-Prager model through `fem_run`.

### From Python

```python
from kerf_fem.plasticity.drucker_prager import (
    DruckerPragerMaterial, yield_function_dp, return_map_dp,
    _dp_alpha_k,
)

mat = DruckerPragerMaterial(
    E=30e9, nu=0.2,
    cohesion=3e6,          # Pa
    friction_angle_deg=35.0,
    dilation_angle_deg=10.0,  # non-associated
)
alpha_dp, k_dp = _dp_alpha_k(mat)
print(f"DP params: alpha={alpha_dp:.4f}, k={k_dp/1e6:.2f} MPa")

import numpy as np
sigma0 = np.zeros(6)
deps = np.array([-0.002, -0.001, -0.001, 0, 0, 0])  # compressive
sigma_new, converged = return_map_dp(sigma0, deps, mat)
print(f"Axial stress: {sigma_new[0]/1e6:.2f} MPa")
```

### From an LLM tool spec

```json
{"tool": "fem_run", "type": "constitutive_test", "model": "drucker_prager",
 "E": 30e9, "nu": 0.2, "cohesion_MPa": 3, "friction_angle_deg": 35}
```

## How it works

DP parameters α and k are computed from Mohr-Coulomb friction angle φ and cohesion c via the inscribed-circle match: α = 2 sin φ / (√3 (3 - sin φ)), k = 6 c cos φ / (√3 (3 - sin φ)). The elastic predictor gives a trial stress; if the yield function f(σ_trial) > 0, the return mapping solves for the plastic multiplier Δγ by Newton iteration on f evaluated at the returned state. Non-associated flow uses a separate dilation potential g(σ) = √J₂ + α_ψ I₁ with dilation angle ψ.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `yield_function_dp(sigma, mat)` | `float` | f = √J₂ + αI₁ - k |
| `return_map_dp(sigma0, deps, mat)` | `(sigma, converged)` | DP stress update |
| `_dp_alpha_k(mat)` | `(float, float)` | DP parameters from Mohr-Coulomb |

`DruckerPragerMaterial` fields: `E`, `nu`, `cohesion`, `friction_angle_deg`, `dilation_angle_deg`.

## Example

```python
mat = DruckerPragerMaterial(E=20e9, nu=0.25, cohesion=1e6,
                              friction_angle_deg=30, dilation_angle_deg=5)
f_uniaxial = yield_function_dp(np.array([-5e6,0,0,0,0,0]), mat)
print(f"Yield function at 5 MPa compression: {f_uniaxial/1e6:.3f} MPa")
```

## Honest caveats

The DP criterion is a smooth cone — it does not reproduce the Mohr-Coulomb hexagonal pyramid exactly (use the inner- or outer-inscribed circle matching depending on the regime). Softening (post-peak cohesion degradation) is not implemented — the model is elastic-perfectly-plastic or with linear hardening only. For soil consolidation and rate-dependent creep, use a Cam-Clay or viscoplastic model.

## References

- Drucker & Prager (1952). "Soil mechanics and plastic analysis or limit design." *Quarterly of Applied Mathematics* 10(2).
- Chen & Han (1988). *Plasticity for Structural Engineers*. Springer.
