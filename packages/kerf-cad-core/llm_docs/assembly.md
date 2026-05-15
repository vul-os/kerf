# Assembly Constraint Layer — LLM Reference

Units: **mm**. Coordinate system: **right-handed** (X right, Y forward, Z up).  
Transforms: **4×4 row-major homogeneous matrix**, flat `list[float]` of 16 elements.  
Identity: `[1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]`

---

## Workflow

```
assembly_create → assembly_add_component (repeat) → assembly_add_mate (repeat) → assembly_solve
                                                                               → assembly_bom
```

The assembly and mates dicts are passed verbatim between calls (stateless).

---

## Tools

### `assembly_create`
Create an empty assembly. Returns `{assembly, assembly_id}`.

### `assembly_add_component`
Add a part instance. `part_ref` is a name / file-id. First component added is the **ground** (fixed, 0 DOF). Returns `{assembly, instance_id}`.

### `assembly_add_mate`
Append a constraint between two instances. Returns `{mates, mate_id}`.

| `mate_type`   | DOF removed | Geometry needed |
|---------------|-------------|-----------------|
| `coincident`  | 3           | `point_a`, `normal_a`, `point_b`, `normal_b` (optional `offset` mm) |
| `concentric`  | 4           | `point_a`, `normal_a` (axis), `point_b`, `normal_b` (axis) |
| `parallel`    | 2           | `normal_a`, `normal_b` |
| `perpendicular` | 1         | `normal_a`, `normal_b` |
| `distance`    | 1           | `point_a`, `normal_a`, `point_b`, `offset` mm |
| `angle`       | 1           | `normal_a`, `normal_b`, `angle_deg` |
| `tangent`     | 1           | `point_a`, `normal_a`, `point_b`, `offset` = cylinder radius |
| `lock`        | all remaining | — |

All geometry in **local component frame**.

### `assembly_solve`
Solve the constraint system. Returns:
```json
{
  "ok": true,
  "components": [{"instance_id": "…", "part_ref": "…", "transform": […], "dof_remaining": 0}],
  "dof_remaining": 0,
  "status": "fully_constrained",
  "errors": []
}
```
`status` is `"fully_constrained"` / `"under_constrained"` / `"over_constrained"`.

### `assembly_bom`
Generate BOM. Returns:
- `flat`: `[{part_ref, qty, instances: [instance_id, …]}]` — duplicates rolled up.
- `tree`: nested indented structure mirroring sub-assembly hierarchy.
- `total_components`, `unique_parts`.

---

## Example — bolt + nut (concentric + coincident)

```
create → add bolt (ground) → add nut →
add_mate concentric (bolt axis, nut axis) →
add_mate coincident (bolt face, nut face) →
solve  →  bom
```

## DOF counting

A free rigid body has **6 DOF**. The ground component has 0. Each mate reduces the free component's DOF by the amount shown in the table above. Over-constrained = a mate tries to remove a DOF already consumed; under-constrained = DOF > 0 remain after all mates.
