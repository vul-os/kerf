# kerf-mates · solver.py

Geometric constraint solver for parametric assembly mates. Iteratively resolves entity positions to satisfy coincident, distance, angle, parallel, perpendicular, concentric, and tangent constraints.

---

## When to use

- Resolve the final positions of components in a parametric assembly after mates are defined
- Check whether a set of geometric constraints has a valid solution (feasibility test)
- Compute worst-case and RSS tolerance contributions across all distance/angle mates in an assembly

---

## Data types

### `Entity` (dataclass)

```python
@dataclass
class Entity:
    id: str
    entity_type: str          # "face", "edge", "vertex", "axis", etc.
    component_id: str
    feature_id: str
    position: tuple[float, float, float]  # current 3-D position
    normal:   tuple[float, float, float]  # face/plane normal
    axis:     tuple[float, float, float]  # edge/cylinder axis
```

### `MateConstraint` (dataclass)

```python
@dataclass
class MateConstraint:
    id: str
    mate_type: str          # see "Supported constraint types" below
    entity_a_id: str
    entity_b_id: str
    value: float = 0.0      # target value (mm or radians)
    unit: str = "mm"        # "mm", "cm", "inch", "deg", "rad"
    tolerance_plus: float = 0.0
    tolerance_minus: float = 0.0
    flipped: bool = False
```

### `SolveResult` (dataclass)

```python
@dataclass
class SolveResult:
    solved: bool                    # True if converged within tolerance
    entities: dict[str, Entity]     # resolved entity positions
    residuals: list[float]          # per-constraint residual at exit
    iterations: int                 # number of gradient steps taken
    error: str = ""                 # non-empty if solved=False
```

---

## Supported constraint types

| `mate_type` | Residual | Notes |
|---|---|---|
| `coincident` | `|posA − posB|` | coincident point/face/edge |
| `distance` | `|dist − target|` | target in `value`/`unit` |
| `angle` | `|angle(normalA, normalB) − target|` | target in `value`/`unit` |
| `parallel` | `min(angle, π − angle)` | normals parallel |
| `perpendicular` | `|angle − π/2|` | normals perpendicular |
| `concentric` | `|posA − posB|` | axes coincident |
| `tangent` | `|posA − posB|` | point-to-point proxy |

---

## Solver algorithm

`GeometricConstraintSolver.solve()` — gradient-descent Newton-like loop:

1. Evaluate all constraint residuals `r_i`.
2. Compute numerical gradient by finite-difference perturbation (ε = 1e-7).
3. Update entity positions: `pos[eid] -= step_size × Σ(r_i × ∂r_i/∂pos)`.
4. Repeat up to `max_iterations = 100`.
5. Converged when `max(|r_i|) < 1e-6`.

**Note:** the solver adjusts entity `position` in 3-D; rotational DOFs (`normal`, `axis`) are not updated during the solve. For assemblies where mates constrain orientation (parallel, perpendicular) the orientation must be pre-set manually — the solver only moves positions.

---

## Public entrypoints

### `GeometricConstraintSolver(entities, constraints)`

```python
from kerf_mates.solver import GeometricConstraintSolver, Entity, MateConstraint

entities = [
    Entity(id="e1", entity_type="face", component_id="c1", feature_id="f1",
           position=(0, 0, 0), normal=(0, 0, 1), axis=(0, 0, 1)),
    Entity(id="e2", entity_type="face", component_id="c2", feature_id="f2",
           position=(5, 0, 0), normal=(0, 0, 1), axis=(0, 0, 1)),
]
constraints = [
    MateConstraint(id="m1", mate_type="coincident",
                   entity_a_id="e1", entity_b_id="e2"),
]

solver = GeometricConstraintSolver(entities, constraints)
result = solver.solve()

print(result.solved)       # True / False
print(result.iterations)   # number of gradient steps
print(result.residuals)    # per-constraint residual
for eid, entity in result.entities.items():
    print(eid, entity.position)
```

---

### `solve_assembly(assembly_doc) → SolveResult`

High-level entry point. Extracts entities and constraints from an assembly document dict, constructs the solver, and returns a `SolveResult`.

The `assembly_doc` is a Kerf internal assembly format dict (loaded by `kerf_mates.routes`); it is not a public schema. Use `GeometricConstraintSolver` directly for custom assemblies.

---

### `compute_tolerance_stackup(assembly_doc) → dict`

Worst-case and RSS tolerance contributions for all `distance` and `angle` mates in the assembly.

Returns `{mate_id: {"worst_case": float, "rss": float}}`. Delegates to `kerf_mates.tolerance` functions.

---

## Transform helpers

The module also provides standalone 3-D geometry helpers used internally:

- `vec3_sub`, `vec3_add`, `vec3_scale`, `vec3_dot`, `vec3_cross`
- `vec3_norm`, `vec3_normalize`, `vec3_angle`, `vec3_distance`
- `transform_point(p, m)` / `transform_normal(n, m)` — apply a 4×4 row-major matrix
- `extract_transform(component)` — extract the 16-float transform from a component dict

**Transform convention:** 4×4 row-major matrix stored as a 16-float tuple (indices 0–15, row-first). Column 3 is the translation; row 3 is `[0, 0, 0, 1]`.

---

## LLM tool

**`solve_assembly`** — registered in `kerf_mates.tools`. Accepts `assembly_file_id`, runs the solver, and returns:
```json
{
  "solved": true,
  "iterations": 23,
  "residual_max": 3.2e-8,
  "entity_count": 6
}
```

---

## Limitations

- Solver moves positions only; it does not update rotational degrees of freedom (normal, axis). Orientation constraints (parallel, perpendicular, angle) are residuals only — they guide step direction but do not rotate entities.
- The gradient step size is fixed at 0.1; for large initial constraint violations the solver may oscillate. Pre-position parts closer to the target before solving.
- Maximum 100 iterations; over-constrained or infeasible systems will exit with `solved=False`.
- No loop-closure detection; redundant constraints may cause instability.
