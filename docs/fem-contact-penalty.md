# Penalty and Augmented Lagrangian Contact

> Enforce no-penetration contact constraints between FEM bodies using the penalty or augmented Lagrangian method.

**Module**: `packages/kerf-fem/src/kerf_fem/contact/penalty.py`
**Shipped**: Wave 12E
**LLM tools**: `fem_run`

---

## What it is

Penalty contact enforces the non-penetration constraint `g ≥ 0` (gap function) by adding a normal contact force `F_n = k_pen × max(−g, 0)` to the residual when two surfaces interpenetrate. This avoids Lagrange multiplier DOFs at the cost of allowing a small amount of interpenetration proportional to `1/k_pen`. The augmented Lagrangian method iteratively updates a Lagrange multiplier estimate to reduce penetration without requiring a very large penalty stiffness.

## How to use it

### From chat

> "Check contact between two elastic plates with penalty stiffness 1e8 N/m."

### From Python

```python
from kerf_fem.contact.penalty import (
    ContactPair, compute_contact_force_penalty, contact_gap,
)

pair = ContactPair(
    master_nodes=master_v,   # (M, 3) positions
    slave_nodes=slave_v,     # (S, 3) positions
    penalty_stiffness=1e8,   # N/m
    friction_coeff=0.0,      # frictionless
)
gaps = contact_gap(pair)
forces = compute_contact_force_penalty(pair, gaps)
print(forces.normal_forces)    # N per slave node
print(forces.max_penetration_mm)
```

### From an LLM tool spec

```json
{"tool": "fem_run", "input": {"model": "contact_penalty", "penalty_stiffness": 1e8, "friction_coeff": 0.0}}
```

## How it works

`contact_gap` finds, for each slave node, the nearest point on the master surface by a nearest-segment search and computes the signed distance along the outward normal. A negative gap indicates penetration. `compute_contact_force_penalty` applies `F_n = k_pen × max(−g, 0)` as a nodal force on the slave node and an equal and opposite force distributed back onto the master surface via shape-function weighting.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `contact_gap(pair)` | `np.ndarray` | Signed gap per slave node (negative = penetration) |
| `compute_contact_force_penalty(pair, gaps)` | `ContactForces` | Normal (and friction) forces |
| `ContactPair(master_nodes, slave_nodes, penalty_stiffness, friction_coeff)` | instance | Contact pair definition |

## Example

```python
gaps = contact_gap(pair)
# array([-0.0002, 0.0005, ...]) — negative entries are interpenetrations
forces = compute_contact_force_penalty(pair, gaps)
# ContactForces(normal_forces=[20000, 0, ...], max_penetration_mm=0.20)
```

## Honest caveats

The penalty method is only an approximation to the constraint; choose `k_pen` large enough (typically 10–100× E) to limit penetration to an acceptable level but not so large as to ill-condition the stiffness matrix. The nearest-segment search is O(S × M) and becomes expensive for large meshes; a spatial index would improve performance. Friction (Coulomb) requires a consistent tangential stiffness and may reduce Newton-Raphson convergence.

## References

- Wriggers, *Computational Contact Mechanics*, 2nd ed. (2006), Ch. 3.
- Laursen, *Computational Contact and Impact Mechanics*, Springer (2002), Ch. 2.
