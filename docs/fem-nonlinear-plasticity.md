# FEM Nonlinear Material and Plasticity

> Newton-Raphson nonlinear FEA for bars and trusses with radial-return plasticity — compute plastic collapse loads, hinge sequences, and residual stresses.

**Module**: `packages/kerf-fem/src/kerf_fem/nonlinear_static.py`
**Shipped**: Wave 10
**LLM tools**: `fem_nonlinear_bar`, `fem_truss_plastic`

---

## What it is

Nonlinear FEA is needed when structures yield under extreme loads, when deflections are large, or when the load-displacement curve has a snap-through point. This module provides an incremental-iterative Newton-Raphson solver for 1D bars and 2D trusses with elastic-perfectly-plastic or bilinear-hardening material models.

The radial return (closest-point projection) algorithm integrates the constitutive equations exactly for J2 von Mises plasticity at each load step. Load stepping and convergence control make the solver robust for post-yield path tracing. Engineers use it to find the plastic collapse load of frames, check whether a detail will yield under service loads, and validate material models before CalculiX runs.

## How to use it

### From chat (natural language)

> "Compute the plastic strain and stress in a 0.5m steel bar under 30kN axial force, σy=250MPa, H=2GPa"

The LLM calls `fem_nonlinear_bar` with the bar parameters.

### From Python

```python
from kerf_fem.nonlinear_static import (
    _elastic_C, _return_map_3d, _von_mises_norm,
)
from kerf_fem.nonlinear_bar import ElasticPlasticBar, solve_nonlinear_bar

bar = ElasticPlasticBar(
    E=200e9, sigma_y=250e6, H=2e9,
    A=1e-4, L=0.5,
)
result = solve_nonlinear_bar(bar, axial_force=30000, n_steps=20)
print(f"Plastic strain: {result['plastic_strain']:.6f}")
print(f"Stress: {result['stress_pa']/1e6:.1f} MPa")
print(f"Converged: {result['converged']}")
```

### From an LLM tool spec

```json
{"tool": "fem_nonlinear_bar", "E": 200e9, "sigma_y": 250e6, "H": 2e9,
 "A": 1e-4, "L": 0.5, "F": 30000, "n_steps": 20}
```

## How it works

The incremental Newton-Raphson loop: (1) apply a load increment ΔF; (2) solve the linearised system K_tan δu = r (where r = F_ext - F_int is the residual); (3) update displacements; (4) at each integration point, compute trial stress σ_trial = σ_n + C:Δε; (5) check yield criterion f(σ_trial) = √(3J₂) - σ_y ≤ 0; (6) if violated, apply radial return: project σ_trial radially onto the yield surface, update plastic strain. Repeat until ‖r‖/‖F‖ < tolerance.

The tangent modulus matrix accounts for plastic flow: K_tan includes the elastoplastic consistent tangent (Simo & Hughes 1998), ensuring quadratic convergence of Newton-Raphson.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `solve_nonlinear_bar(bar, axial_force, n_steps)` | `dict` | Nonlinear bar solution |
| `_return_map_3d(sigma_trial, sigma_y, H, C)` | `(sigma, eps_p, converged)` | Radial-return plasticity |
| `_von_mises_norm(s)` | `float` | von Mises equivalent stress |

## Example

```python
bar = ElasticPlasticBar(E=200e9, sigma_y=350e6, H=0, A=5e-5, L=1.0)
r = solve_nonlinear_bar(bar, axial_force=20000, n_steps=10)
print(f"Plastic strain: {r['plastic_strain']:.4e}")
print(f"Residual: {r['final_residual']:.2e}")
```

## Honest caveats

The pure-Python solver covers 1D bars and 2D trusses only. Plane-stress/strain, shell, and 3D solid plasticity require CalculiX via `fem_run`. Kinematic hardening is not currently available — only isotropic hardening. Large-strain kinematics (Eulerian or total-Lagrangian) is not implemented; the solver assumes small-strain kinematics (ε ≈ ∇_sym u).

## References

- Simo & Hughes (1998). *Computational Inelasticity*. Springer.
- de Souza Neto, Peric & Owen (2008). *Computational Methods for Plasticity*. Wiley.
