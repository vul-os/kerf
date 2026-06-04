# Material Pareto Front

> Find the Pareto-optimal material set across two or more competing performance objectives.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/matsel/multi_objective.py`
**Shipped**: Wave 9
**LLM tools**: `matsel_filter`, `matsel_select`

---

## What it is

Multi-objective material selection computes the Pareto frontier of the material database across any combination of property metrics (e.g., maximise specific stiffness E/ρ while minimising cost/kg). A material is Pareto-optimal if no other material is simultaneously better on all objectives. The `pareto_frontier` function returns only the non-dominated materials.

## How to use it

### From chat

> "Find the Pareto front of all metals trading off specific stiffness against cost per kg."

### From Python

```python
from kerf_cad_core.matsel.multi_objective import pareto_frontier, weighted_score
from kerf_cad_core.matsel.db import filter_materials

metals = filter_materials(material_class="metal")

front = pareto_frontier(
    materials=metals,
    metrics=["E_over_rho", "cost_per_kg"],
    directions=["maximize", "minimize"],
)
for mat in front:
    print(mat["name"], mat["E_over_rho"], mat["cost_per_kg"])
```

### From an LLM tool spec

```json
{"tool": "matsel_filter", "input": {"material_class": "metal", "min_yield_strength_mpa": 200}}
```

## How it works

`_dominates(a, b)` returns True if material `a` is no worse than `b` on all objectives and strictly better on at least one. `pareto_frontier` iterates over all material pairs and removes dominated materials. The algorithm is O(n²) in the number of materials — acceptable for the embedded 200+ material database. `weighted_score` aggregates multiple normalised metrics into a single scalar for ranked shortlisting when a strict Pareto set is too large.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `pareto_frontier(materials, metrics, directions)` | `list[dict]` | Non-dominated material set |
| `weighted_score(materials, metrics, weights, directions)` | `list[dict]` | Weighted ranking across objectives |
| `tradeoff_envelope(materials, metric_x, metric_y)` | `list[dict]` | Sorted Pareto curve for charting |

## Example

```python
front = pareto_frontier(metals, ["E_over_rho", "cost_per_kg"], ["maximize", "minimize"])
# Returns 8–12 materials on the stiffness-cost Pareto front
# e.g. Ti-6Al-4V (high E/ρ, high cost), HSLA steel (moderate, low cost)
```

## Honest caveats

Pareto analysis uses the material database's typical mid-range values; scatter within a material class can be wider than the gap between adjacent Pareto points. Adding more objectives quickly expands the Pareto frontier (curse of dimensionality) — with 4+ objectives nearly every material is non-dominated. Use `weighted_score` for practical shortlisting when the Pareto set is too large.

## References

- Ashby, *Materials Selection in Mechanical Design*, 5th ed. (2017), Ch. 5.
- Deb, *Multi-Objective Optimization Using Evolutionary Algorithms*, Wiley (2001), Ch. 2.
