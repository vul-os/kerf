# Mohr-Coulomb Plasticity

> Model shear-failure yielding in soils and rock using the six-sided Mohr-Coulomb pyramid.

**Module**: `packages/kerf-fem/src/kerf_fem/plasticity/mohr_coulomb.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

The Mohr-Coulomb (MC) criterion is the classical soil and rock failure model: failure occurs when `τ = c + σ_n tan(φ)` on any plane. In principal stress space the yield surface is a six-sided pyramid. The FEM implementation uses a return-mapping algorithm that handles the facets, edges, and apex of the pyramid as separate return zones.

## How to use it

### From chat

> "Compute the Mohr-Coulomb yield function for a clay element at principal stresses (−150, −60, −20) kPa."

### From Python

```python
from kerf_fem.plasticity.mohr_coulomb import (
    MohrCoulombMaterial, yield_function_mc, return_map_mc,
)

mat = MohrCoulombMaterial(
    E=50e6, nu=0.35,
    cohesion=20e3,       # c = 20 kPa
    friction_angle=28.0, # φ = 28°
    dilatancy_angle=0.0, # associated flow if equal to φ
)
sigma = [-150e3, -60e3, -20e3, 0, 0, 0]
f = yield_function_mc(mat, sigma)
print(f"f = {f:.1f} Pa")
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "mohr_coulomb", "cohesion": 20e3, "friction_angle": 28}}
```

## How it works

The six yield planes of the MC pyramid are written in terms of principal stresses `σ₁ ≥ σ₂ ≥ σ₃`. The active return zone is determined by checking which side of the yield surface the elastic predictor lies on. Apex returns are handled separately. The return-mapping equations are solved analytically in the principal stress space using the formulas of de Souza Neto et al. (§8.3) and then rotated back to the Voigt frame.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `yield_function_mc(mat, sigma)` | `float` | Maximum of 6 MC planes (> 0 = yielded) |
| `return_map_mc(mat, state, d_eps)` | `MCState` | Stress update with MC return |
| `MohrCoulombMaterial(E, nu, cohesion, friction_angle, dilatancy_angle)` | instance | Material parameters |

## Example

```python
f = yield_function_mc(mat, [-150e3, -60e3, -20e3, 0, 0, 0])
# −4320 Pa — not yielded; increase σ₁ slightly to trigger failure
```

## Honest caveats

The non-smooth corners and apex of the MC surface cause numerical difficulties; this implementation uses the smoothed (Drucker-Prager circumscribed) return at edges and apex. Softening (post-peak cohesion degradation) is not modelled. The small-strain implementation is adequate for slope stability and foundation checks but not for large-deformation landslide analysis.

## References

- de Souza Neto, Peric & Owen, *Computational Methods for Plasticity*, Wiley (2008), §8.3.
- Abbo & Sloan, "A smooth hyperbolic approximation to the Mohr-Coulomb yield criterion," *Comput. Struct.* 54(3), 1995.
