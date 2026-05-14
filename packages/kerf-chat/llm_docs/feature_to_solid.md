# `feature_to_solid` — promote a surface body to a solid

Appends a `to_solid` node to a `.feature` file. Converts the output of a
surface-producing op (`sweep1`, `loft`, `network_srf`, `blend_srf`, …) into a
`TopoDS_Solid` by sewing its faces into a closed shell and capping into a solid
via `BRepBuilderAPI_Sewing` + `BRepBuilderAPI_MakeSolid`.

**Required before `feature_boolean`.** Both operands of a boolean must be
solids. If either is still a face or shell, call `feature_to_solid` on it first.

See the [NURBS booleans v1 design](../../docs/plans/nurbs-booleans-v1.md) for
the full rationale and fallback paths.

## Schema

```json
{
  "id": "to_solid-1",
  "op": "to_solid",
  "target_id": "sweep1-3",
  "tolerance": 1e-6
}
```

### Parameters

| Parameter    | Type          | Required | Default | Notes                                                              |
|--------------|---------------|----------|---------|--------------------------------------------------------------------|
| `file_id`    | string (uuid) | yes      | —       | Target `.feature` file id                                          |
| `target_id`  | string        | yes      | —       | Existing feature node id whose output to promote                   |
| `options.tolerance` | number | no     | `1e-6`  | Sewing tolerance in model units; raise to `1e-4` for noisy NURBS  |
| `options.id` | string        | no       | auto    | Explicit node id (`"to_solid-N"`)                                  |

## Worked example

A `blend_srf` node produces a free-form face. Before using it in a boolean,
promote it to a solid:

```json
[
  { "id": "pad-1",       "op": "pad",       "sketch_path": "/base.sketch", "height": 20 },
  { "id": "sweep1-1",    "op": "sweep1",    "profile_sketch_path": "/circle.sketch", "path_sketch_path": "/spine.sketch" },
  { "id": "to_solid-1",  "op": "to_solid",  "target_id": "sweep1-1", "tolerance": 1e-6 },
  { "id": "boolean-1",   "op": "boolean",   "target_a_id": "pad-1", "target_b_id": "to_solid-1", "kind": "cut" }
]
```

## Error messages

| Message | Cause |
|---|---|
| `to_solid: sewing produced no shell — input may be open/non-manifold` | The face collection has gaps or is not manifold |
| `to_solid: MakeSolid failed` | OCCT could not cap the shell; try raising `tolerance` |
| `to_solid: wasm binding missing — BRepBuilderAPI_MakeSolid_1 not present` | OCCT WASM build is missing the binding; requires a rebuild |
