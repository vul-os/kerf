# Hill Anisotropic Plasticity

> Model plastic yielding in anisotropic metals (rolled sheet, fibre-textured alloys) with Hill's 1948 criterion.

**Module**: `packages/kerf-fem/src/kerf_fem/plasticity/hill.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

Hill's 1948 anisotropic yield criterion generalises von Mises plasticity to orthotropic materials by introducing six independent anisotropy coefficients (F, G, H, L, M, N). It is widely used for sheet metal forming of aluminium and high-strength steel where the plastic flow is asymmetric with respect to the rolling, transverse, and through-thickness directions.

## How to use it

### From chat

> "Compute the Hill yield function for an AA2024-T3 sheet element with R-values R00=0.62, R45=0.80, R90=0.70."

### From Python

```python
from kerf_fem.plasticity.hill import (
    HillAnisotropicMaterial, yield_function_hill, return_map_hill,
)

mat = HillAnisotropicMaterial(
    E=73e9, nu=0.33,
    sigma_y0=345e6,
    R00=0.62, R45=0.80, R90=0.70,  # Lankford coefficients
)
sigma = [400e6, 50e6, 0, 30e6, 0, 0]  # Voigt: σ_xx, σ_yy, σ_zz, τ_xy, τ_xz, τ_yz
f = yield_function_hill(mat, sigma)
print(f"f = {f:.3e} Pa")
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "hill_anisotropic", "R00": 0.62, "R45": 0.80, "R90": 0.70, "sigma_y0": 345e6}}
```

## How it works

The six Hill coefficients (F, G, H, L, M, N) are derived from the Lankford r-values (R00, R45, R90) using the standard algebraic relations of Hill (1948). The anisotropic yield function is `f = √(F(σ_yy−σ_zz)² + G(σ_zz−σ_xx)² + H(σ_xx−σ_yy)² + 2Lτ_yz² + 2Mτ_xz² + 2Nτ_xy²) − σ_y`. Return mapping is performed via a closest-point projection using the anisotropic moduli.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `yield_function_hill(mat, sigma)` | `float` | Hill yield function value |
| `return_map_hill(mat, state, d_eps)` | `HillState` | Anisotropic stress update |
| `HillAnisotropicMaterial(E, nu, sigma_y0, R00, R45, R90)` | instance | Anisotropic material |

## Example

```python
f = yield_function_hill(mat, [400e6, 50e6, 0, 30e6, 0, 0])
# > 0 means yielded; adjust sigma_y0 or stress components accordingly
```

## Honest caveats

The Hill 1948 criterion assumes a quadratic yield surface — it cannot capture the "earring" defect in deep drawing where higher-order anisotropy is important. For those cases, Barlat Yld2000-2d or Cazacu-Barlat models are more appropriate but are not currently implemented. The r-value calibration assumes isotropic hardening; kinematic hardening is not included.

## References

- Hill, R., "A theory of the yielding and plastic flow of anisotropic metals," *Proc. R. Soc. London A* 193, 1948.
- Barlat et al., "Plane stress yield function for aluminium alloy sheets," *Int. J. Plasticity* 21(5), 2003.
