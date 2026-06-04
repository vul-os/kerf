# FEM Contact Mechanics

> Solve frictionless normal contact between deformable bodies using penalty and augmented Lagrangian methods — for press fits, Hertzian contact, and bolted joints.

**Module**: `packages/kerf-fem/src/kerf_fem/contact/penalty.py`, `packages/kerf-fem/src/kerf_fem/contact/augmented_lagrangian.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run` (analysis `"contact"`)

---

## What it is

Contact is one of the most common nonlinear FEA problems: gears meshing, bolted flange connections, bearing races, press-fit shafts. The challenge is that the contact area and contact pressure are unknowns — they depend on the deformation, which depends on the contact pressure.

This module provides two contact algorithms: (1) the penalty method, which allows small interpenetration and adds a stiffness proportional to the gap violation; (2) the augmented Lagrangian (Uzawa) method, which converges to the exact zero-penetration constraint. Hertzian contact solutions are provided for sphere-on-flat and cylinder-on-flat geometries for quick verification.

## How to use it

### From chat (natural language)

> "Compute the contact pressure between a 10mm radius steel sphere and a flat plate under 1000N normal load"

The LLM calls `fem_run` with Hertzian contact analysis.

### From Python

```python
from kerf_fem.contact.penalty import compute_contact_force_penalty, ContactPair
from kerf_fem.contact.augmented_lagrangian import run_uzawa_loop
from kerf_fem.contact.hertzian import hertz_sphere_flat

# Hertzian analytical solution
result = hertz_sphere_flat(
    R=0.010, F=1000.0,
    E1=200e9, nu1=0.3,   # steel sphere
    E2=200e9, nu2=0.3,   # steel flat
)
print(f"Contact radius: {result['a_m']*1000:.3f} mm")
print(f"Max pressure: {result['p0_Pa']/1e6:.1f} MPa")

# Penalty contact
pair = ContactPair(master_nodes=master, slave_nodes=slave, penalty=1e12)
F_contact = compute_contact_force_penalty(pair, u_master, u_slave)
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "hertz_contact", "R_m": 0.01,
 "F_N": 1000, "E1_Pa": 200e9, "nu1": 0.3}}
```

## How it works

The **penalty method** adds a contact stiffness k_p in the normal direction whenever the gap g < 0 (interpenetration): F_contact = k_p × |g| in the normal direction. The penalty stiffness must be large enough to limit penetration but not so large that the stiffness matrix becomes ill-conditioned.

The **augmented Lagrangian (Uzawa)** method iterates between: (1) solving the primal problem with current contact forces λ; (2) updating λ += k_p × g (only for active contact nodes). This converges to exact non-penetration without the ill-conditioning of the penalty method.

**Hertz contact** (sphere-flat): contact radius a = (3FR*/4E*)^(1/3), max pressure p₀ = 3F/(2πa²), where R* = R, E* = E/(2(1-ν²)) for identical materials.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `compute_contact_force_penalty(pair, u_master, u_slave)` | `np.ndarray` | Penalty contact forces |
| `run_uzawa_loop(K, f_ext, contact_pairs, n_iter)` | `dict` | Augmented Lagrangian solver |
| `augmented_lagrangian_converged(residual, tol)` | `bool` | Convergence check |

Hertzian functions (in `hertzian.py`): `hertz_sphere_flat(R, F, E1, nu1, E2, nu2)`, `hertz_cylinder_flat(...)`.

## Example

```python
from kerf_fem.contact.hertzian import hertz_sphere_flat
r = hertz_sphere_flat(R=0.005, F=500.0, E1=200e9, nu1=0.3, E2=70e9, nu2=0.33)
print(f"Contact radius: {r['a_m']*1e3:.3f} mm")
print(f"Peak pressure: {r['p0_Pa']/1e6:.1f} MPa")
```

## Honest caveats

The penalty method requires careful penalty parameter selection — too low allows visible penetration; too high causes ill-conditioning. The Uzawa loop converges linearly (not quadratically) — for tight tolerances use many iterations or switch to an active-set method. Friction contact (Coulomb) is not yet implemented in this module. Deformable-deformable contact requires careful mesh compatibility at the interface.

## References

- Wriggers (2006). *Computational Contact Mechanics*, 2nd ed. Springer.
- Johnson (1985). *Contact Mechanics*. Cambridge University Press.
