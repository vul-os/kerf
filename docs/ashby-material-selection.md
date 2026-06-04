# Ashby Material Selection

*Domain: Materials · Module: `packages/kerf-cad-core/src/kerf_cad_core/matsel/db.py` · Shipped: Wave 9*

## Overview

Multi-objective material selection using Ashby performance indices. The database contains 200+ engineering materials (metals, polymers, ceramics, composites, foams) with elastic modulus, density, yield strength, thermal conductivity, cost per kg, and other properties. `ashby_rank` evaluates performance indices such as E/ρ (stiffness-per-weight), σ_y/ρ (strength-per-weight), and λ (thermal conductivity) and returns a ranked shortlist. `filter_materials` applies hard constraints before ranking.

## When to use

- Finding the lightest material for a given stiffness or strength requirement.
- Comparing material candidates across multiple performance metrics.
- Generating material selection charts for design reports.

## API

```python
from kerf_cad_core.matsel.db import (
    get_material, list_materials, filter_materials,
    ashby_rank, select_material,
)

# Find all metals with yield strength > 300 MPa and density < 5000 kg/m³
candidates = filter_materials(
    material_class="metal",
    min_yield_strength_mpa=300,
    max_density=5000,
)

# Rank by specific stiffness (E/ρ)
ranked = ashby_rank(candidates, index="E_over_rho", top_n=10)

for mat in ranked:
    print(mat["name"], mat["score"])
```

## LLM tools

`material_select`, `material_ashby_rank`

## References

- Ashby, *Materials Selection in Mechanical Design*, 5th ed. (2017).
- CES EduPack material database (property ranges used as reference).

## Honest caveats

The embedded database uses typical (mid-range) property values, not guaranteed minimums. Actual material properties vary significantly between grades, suppliers, and processing conditions. The database does not include anisotropic properties for composites; use the CLT module for directional composite analysis. Cost data is order-of-magnitude only and not price-list accurate.
