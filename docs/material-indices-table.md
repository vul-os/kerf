# Material Performance Indices

> Apply Ashby performance indices to rank materials for common structural, thermal, and acoustic applications.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/matsel/db.py`
**Shipped**: Wave 9
**LLM tools**: `matsel_filter`, `matsel_select`

---

## What it is

Material performance indices are dimensionless or dimensioned merit figures that rank materials for a specific design function and objective. For example, for a stiffness-limited panel of minimum mass the index is `E^(1/3)/ρ`. The `ashby_rank` function evaluates a named index against all materials in the database and returns a ranked shortlist.

## How to use it

### From chat

> "Rank all materials by specific stiffness for a beam in bending, top 10."

### From Python

```python
from kerf_cad_core.matsel.db import ashby_rank, filter_materials

all_mats = filter_materials()  # no constraints = all materials

# Stiffness-limited beam, minimum mass: index = E^(1/2) / rho
ranked = ashby_rank(all_mats, index="E_half_over_rho", top_n=10)
for m in ranked:
    print(f"{m['name']}: {m['score']:.4f}")
```

### From an LLM tool spec

```json
{"tool": "matsel_filter", "input": {"min_yield_strength_mpa": 100, "max_density": 3000}}
```

## How it works

`ashby_rank` evaluates the named index formula against each material's property values and sorts descending (higher = better, unless the index is a cost or weight-to-minimise). Index formulas are stored as lambda expressions in the index registry: `E_over_rho` = `E / density`, `E_half_over_rho` = `sqrt(E) / density`, `sigma_y_over_rho` = `yield_strength / density`, `thermal_conductivity` = `lambda_k` directly.

## API reference

| Index Name | Formula | Application |
|---|---|---|
| `E_over_rho` | E / ρ | Stiffness-limited tie rod, min mass |
| `E_half_over_rho` | √E / ρ | Stiffness-limited beam, min mass |
| `E_third_over_rho` | E^(1/3) / ρ | Stiffness-limited panel, min mass |
| `sigma_y_over_rho` | σ_y / ρ | Strength-limited tie rod, min mass |
| `sigma_y_23_over_rho` | σ_y^(2/3) / ρ | Strength-limited beam, min mass |
| `thermal_conductivity` | λ | Maximum heat flux |
| `E_over_cost` | E / (ρ × cost/kg) | Stiffness per unit cost |

## Example

```python
ranked = ashby_rank(filter_materials(), "E_half_over_rho", top_n=5)
# 1. CFRP (UD):  score=47.3
# 2. Beryllium:  score=43.8
# 3. GFRP (UD):  score=28.1
# 4. Al 7075-T6: score=25.7
# 5. Mg AZ31:    score=25.2
```

## Honest caveats

Performance indices assume the dominant failure mode matches the design case (e.g., stiffness-limited vs. strength-limited). Using the wrong index can give misleading rankings. Index values are computed from mean database properties; real material selection must account for property scatter, manufacturing constraints, and cost volatility. Custom indices can be computed by calling `filter_materials` and sorting the result manually.

## References

- Ashby, *Materials Selection in Mechanical Design*, 5th ed. (2017), Ch. 4.
- Ashby & Jones, *Engineering Materials 1*, 5th ed. (2019), Appendix A (property charts).
