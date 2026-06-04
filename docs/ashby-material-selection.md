# Ashby Material Selection

> Filter 200+ engineering materials by property constraints then rank by Ashby performance index.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/matsel/db.py`
**Shipped**: Wave 9
**LLM tools**: `matsel_filter`, `matsel_select`

---

## What it is

Multi-objective material selection using Ashby performance indices. The database covers 200+ engineering materials (metals, polymers, ceramics, composites, foams) with elastic modulus, density, yield strength, thermal conductivity, cost per kg, and other properties. `ashby_rank` evaluates performance indices such as E/ρ (stiffness-per-weight), σ_y/ρ (strength-per-weight), and λ and returns a ranked shortlist. `filter_materials` applies hard constraints first.

## How to use it

### From chat

> "Find the top 5 metals for a stiffness-critical lightweight beam, yield strength > 300 MPa."

### From Python

```python
from kerf_cad_core.matsel.db import (
    get_material, list_materials, filter_materials,
    ashby_rank, select_material,
)

candidates = filter_materials(
    material_class="metal",
    min_yield_strength_mpa=300,
    max_density=5000,
)
ranked = ashby_rank(candidates, index="E_over_rho", top_n=5)
for mat in ranked:
    print(mat["name"], mat["score"])
```

### From an LLM tool spec

```json
{"tool": "matsel_filter", "input": {"material_class": "metal", "min_yield_strength_mpa": 300, "max_density": 5000}}
```

## How it works

`filter_materials` applies a series of optional bounds on scalar property fields (elastic modulus, yield strength, density, thermal conductivity, cost). The filtered list is passed to `ashby_rank`, which evaluates the named performance index formula (stored as a lambda in the index registry) for each material and sorts by descending score. `select_material` wraps filter + rank + top-1 selection in a single call.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `filter_materials(material_class, min/max props...)` | `list[dict]` | Constrained material list |
| `ashby_rank(materials, index, top_n)` | `list[dict]` | Ranked by performance index |
| `get_material(name)` | `dict` | Single material property record |
| `select_material(constraints, index)` | `dict` | Best material for a design case |

## Example

```python
ranked = ashby_rank(filter_materials(material_class="metal"), "E_over_rho", top_n=5)
# [{'name': 'Al 7075-T6', 'score': 25.7}, {'name': 'Ti-6Al-4V', 'score': 24.4}, ...]
```

## Honest caveats

The database uses typical mid-range property values, not guaranteed minimums. Properties vary significantly between grades, suppliers, and processing. The database does not include anisotropic properties for composites — use the CLT module for directional composite analysis. Cost data is order-of-magnitude only and is not current pricing.

## References

- Ashby, *Materials Selection in Mechanical Design*, 5th ed. (2017), Ch. 4–5.
- CES EduPack database (property ranges used as reference).
