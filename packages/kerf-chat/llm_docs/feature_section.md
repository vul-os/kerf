# `feature_section` — plane cross-section of a solid

Appends a `section` node to a `.feature` file.  Intersects a solid body with
a plane using OCCT's `BRepAlgoAPI_Section` and returns the resulting edge
compound (a 2D cross-section outline).

The result is **not** a solid — it is a `TopoDS_Compound` of intersection
edges.  It is rendered as a 2D wire outline and stored as a `.section` file
kind so it can be dimensioned, exported to DXF, or chained into `feature_pad`.

> **WASM binding gate**: `BRepAlgoAPI_Section` is probed in the NURBS Phase 4
> C1 binding probe at worker boot.  If the probe reports `MISSING` the worker
> will error with `section: wasm binding missing …`.  There is no fallback;
> the user must use a WASM rebuild that includes `BRepAlgoAPI_Section`.

## Schema

```json
{
  "id": "section-1",
  "op": "section",
  "target_solid_ref": "pad-1",
  "plane": {
    "point":  [0.0, 0.0, 10.0],
    "normal": [0.0, 0.0, 1.0]
  }
}
```

### Parameters

| Parameter          | Type          | Required | Default | Notes                                                                      |
|--------------------|---------------|----------|---------|----------------------------------------------------------------------------|
| `file_id`          | string (uuid) | yes      | —       | Target `.feature` file id                                                  |
| `target_solid_ref` | string        | yes      | —       | Node id of the solid to slice (must already exist in the feature tree)     |
| `plane.point`      | `[x, y, z]`  | yes      | —       | Any point on the cutting plane (mm)                                        |
| `plane.normal`     | `[x, y, z]`  | yes      | —       | Normal vector of the cutting plane (need not be unit-length)               |
| `name`             | string        | no       | `""`    | Optional human-readable label for the feature node                         |
| `id`               | string        | no       | auto    | Explicit node id (e.g. `"section-1"`). Auto-generated as `section-N` if omitted |

### Common plane shortcuts

| Plane   | `normal`     | Example `point`   |
|---------|--------------|-------------------|
| XY      | `[0, 0, 1]`  | `[0, 0, 5]` (Z=5) |
| XZ      | `[0, 1, 0]`  | `[0, 0, 0]`       |
| YZ      | `[1, 0, 0]`  | `[0, 0, 0]`       |
| Oblique | `[1, 1, 0]`  | `[0, 0, 0]`       |

## Worked examples

### 1. Mid-height cross-section of a pad

```json
[
  { "id": "pad-1", "op": "pad", "sketch_path": "/base.sketch", "height": 20 },
  {
    "id": "section-1",
    "op": "section",
    "target_solid_ref": "pad-1",
    "plane": { "point": [0, 0, 10], "normal": [0, 0, 1] }
  }
]
```

### 2. Vertical cross-section of a revolved body

```json
[
  { "id": "revolve-1", "op": "revolve", "sketch_path": "/profile.sketch", "axis": "z", "angle_deg": 360 },
  {
    "id": "section-1",
    "op": "section",
    "target_solid_ref": "revolve-1",
    "plane": { "point": [0, 0, 0], "normal": [1, 0, 0] }
  }
]
```

### 3. Oblique section of a lofted body

```json
[
  {
    "id": "loft-1",
    "op": "loft",
    "profile_sketch_paths": ["/bottom.sketch", "/top.sketch"]
  },
  {
    "id": "section-1",
    "op": "section",
    "target_solid_ref": "loft-1",
    "plane": { "point": [0, 0, 15], "normal": [0, 0.5, 1] }
  }
]
```

## Error messages

| Message | Cause |
|---|---|
| `section: wasm binding missing — BRepAlgoAPI_Section not present …` | C1 probe reported MISSING; WASM rebuild required |
| `section: target_solid_ref is required` | `target_solid_ref` was omitted or empty |
| `section: target_solid_ref 'X' not found in evaluated tree` | Referenced node hasn't been evaluated yet (wrong order) |
| `section: plane is required` | `plane` object was omitted |
| `section: plane.point must be [x,y,z]` | `plane.point` is not a 3-element number array |
| `section: plane.normal must be [x,y,z]` | `plane.normal` is not a 3-element number array |
| `section: plane.normal has zero magnitude` | Normal vector is `[0,0,0]` |
| `section: BRepAlgoAPI_Section.IsDone() returned false …` | Section is degenerate or the plane is parallel to all faces |

## Notes

- The output is a **1D compound of edges**, not a solid.  `breptToMesh`
  extracts edges natively so the cross-section appears as lines in the 3D
  renderer.
- The `.section` file kind is designed to be dimensioned in a Drawing view or
  exported to DXF.  `feature_pad` chaining (trace outline → extrude) is a
  planned v0.3 feature.
- Section-plane gumball (drag to reposition in the viewport) is deferred to
  v0.3.  Use the inspector's manual `point` / `normal` inputs for v0.2.
