# J-Integral Fracture Mechanics

> Compute the J-integral energy release rate from FEM displacement fields for fracture toughness assessment.

**Module**: `packages/kerf-fem/src/kerf_fem/fracture/j_integral.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

The J-integral (Rice, 1968) is a path-independent contour integral that gives the energy release rate at a crack tip, enabling fracture toughness assessment without knowing the stress intensity factor analytically. The module computes J from FEM displacement and stress fields using both contour integration and the domain integral (virtual crack extension) method.

## How to use it

### From chat

> "Compute the J-integral for a CT specimen with crack length 25 mm and applied load 5 kN."

### From Python

```python
from kerf_fem.fracture.j_integral import (
    JIntegralContour, compute_j_integral, j_to_k,
)

contour = JIntegralContour(
    crack_tip=(0.025, 0.0),
    contour_radius=0.003,   # m, contour around crack tip
    n_points=64,
)
J = compute_j_integral(
    contour=contour,
    displacement_field=u_field,  # (N, 2) displacements
    stress_field=sigma_field,    # (N, 3) stresses (σ_xx, σ_yy, τ_xy)
    strain_field=eps_field,      # (N, 3) strains
    mesh=fem_mesh,
)
K_I = j_to_k(J, E=200e9, nu=0.3, condition="plane_strain")
print(f"J = {J:.2f} kJ/m², K_I = {K_I/1e6:.2f} MPa√m")
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "j_integral", "crack_tip": [0.025, 0.0], "contour_radius": 0.003}}
```

## How it works

The contour J-integral is evaluated as `J = ∮_Γ (W n₁ − σ_ij n_j ∂u_i/∂x₁) dΓ` where W is the strain energy density, `n` is the outward contour normal, and summation is over i, j = 1, 2. The domain integral (equivalent domain integral, or virtual crack extension) method avoids the crack-tip stress singularity by converting the contour to a volume integral using a smooth weighting function. `j_to_k` converts J to mode-I SIF using plane-strain: `K_I = √(J E / (1 − ν²))`.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `compute_j_integral(contour, u, sigma, eps, mesh)` | `float` | J-integral energy release rate (J/m²) |
| `domain_integral_j(contour, u, sigma, eps, mesh)` | `float` | Domain form (more accurate) |
| `j_to_k(J, E, nu, condition)` | `float` | Convert J to K_I (plane_stress or plane_strain) |

## Example

```python
J = compute_j_integral(contour, u, sigma, eps, mesh)
# J = 42.7 kJ/m²  →  K_I = 92.4 MPa√m
```

## Honest caveats

J-integral accuracy depends on the mesh refinement near the crack tip; quarter-point elements are recommended for the crack-tip singularity. The path independence is valid only for linear elastic materials; elastic-plastic J (J_ep) requires a different formulation. Mixed-mode fracture (mode II, III contributions) requires the interaction integral decomposition, not implemented here.

## References

- Rice, J.R., "A path independent integral and the approximate analysis of strain concentration by notches and cracks," *J. Appl. Mech.* 35, 1968.
- Anderson, T.L., *Fracture Mechanics*, 4th ed. (2017), Ch. 3.
