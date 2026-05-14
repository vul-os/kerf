# `feature_cam_layered` — stacked plane-sections for layered milling

Generates a `.cam.layered` file from a solid by stacking `BRepAlgoAPI_Section`
calls at fixed Z (or X/Y) intervals.  Intended for layered milling, waterjet
cut-and-stack, and laser-cutter workflows where each layer is a separate 2-D
profile.

The result is **not** G-code — it is a structured list of 2-D contours.  Use
the "Generate G-code from layers" button in the `LayeredCAMView` (or call
`POST /api/projects/{pid}/files/{fid}/cam/layered/gcode`) to wrap each layer
in the existing `cam_contour` op with Z-step retracts between layers.

## Schema

```json
{
  "id": "cam-layered-1",
  "op": "cam_layered",
  "target_solid_ref": "pad-1",
  "z_step_mm": 5.0,
  "z_start_mm": 0.0,
  "z_end_mm": 50.0,
  "axis": "Z"
}
```

### Parameters

| Parameter          | Type          | Required | Default | Notes                                                                     |
|--------------------|---------------|----------|---------|---------------------------------------------------------------------------|
| `file_id`          | string (uuid) | yes      | —       | Target `.feature` file id                                                 |
| `target_solid_ref` | string        | yes      | —       | Node id of the solid to slice (must already exist in the feature tree)    |
| `z_step_mm`        | number        | yes      | —       | Distance between slice planes in mm (must be > 0)                        |
| `z_start_mm`       | number        | no       | auto    | Start position along the slicing axis; auto-detected from bbox if omitted |
| `z_end_mm`         | number        | no       | auto    | End position along the slicing axis; auto-detected from bbox if omitted   |
| `axis`             | `"Z"`,`"X"`,`"Y"` | no  | `"Z"`   | Slicing axis. `Z` = XY-plane stack (most common); `X` = YZ; `Y` = XZ    |
| `name`             | string        | no       | `""`    | Optional human-readable label for the feature node                        |
| `id`               | string        | no       | auto    | Explicit node id. Auto-generated as `cam-layered-N` if omitted            |

### Axis shortcuts

| Axis | Plane    | Use case                                                      |
|------|----------|---------------------------------------------------------------|
| `Z`  | XY plane | Standard layered milling (tool descends in Z between passes)  |
| `X`  | YZ plane | Side-profile stacking (e.g. lathe offcuts)                    |
| `Y`  | XZ plane | Front/back profile stacking                                   |

## Output — `.cam.layered` document

```json
{
  "version": 1,
  "axis": "Z",
  "z_step_mm": 5.0,
  "layers": [
    {
      "z_mm": 5.0,
      "edges": [
        [[0.0, 0.0], [50.0, 0.0]],
        [[50.0, 0.0], [50.0, 50.0]],
        ...
      ]
    },
    ...
  ]
}
```

Each `edges` entry is a list of segment pairs `[[x0, y0], [x1, y1]]` in the
2-D plane perpendicular to the slicing axis:

| Axis | 2-D coords |
|------|------------|
| `Z`  | `[x, y]`   |
| `X`  | `[y, z]`   |
| `Y`  | `[x, z]`   |

## Worked examples

### 1. Layer a 50 mm tall box in 5 mm steps

```json
[
  { "id": "pad-1", "op": "pad", "sketch_path": "/base.sketch", "height": 50 },
  {
    "id": "cam-layered-1",
    "op": "cam_layered",
    "target_solid_ref": "pad-1",
    "z_step_mm": 5.0
  }
]
```

`z_start_mm` and `z_end_mm` auto-detected from the solid's bounding box.

### 2. Explicit range — only the middle 30 mm of a 100 mm solid

```json
{
  "id": "cam-layered-2",
  "op": "cam_layered",
  "target_solid_ref": "revolve-1",
  "z_step_mm": 3.0,
  "z_start_mm": 35.0,
  "z_end_mm": 65.0,
  "axis": "Z"
}
```

### 3. X-axis stacking

```json
{
  "id": "cam-layered-3",
  "op": "cam_layered",
  "target_solid_ref": "loft-1",
  "z_step_mm": 10.0,
  "axis": "X"
}
```

## Error messages

| Message | Cause |
|---|---|
| `target_solid_ref must be a non-empty string …` | `target_solid_ref` was omitted or empty |
| `z_step_mm must be a positive number (mm)` | `z_step_mm` is 0 or negative |
| `z_start_mm must be less than z_end_mm` | Range is reversed |
| `axis must be one of ('Z', 'X', 'Y')` | Unknown axis value |
| `file_id must be a valid UUID` | Malformed UUID string |
| `file not found: NOT_FOUND` | The feature file does not exist or has the wrong kind |

## G-code generation

After generating a `.cam.layered` file, the user can produce G-code by:

1. Opening the file in the editor — the `LayeredCAMView` renders a Z-slider
   and a contour preview for each layer.
2. Clicking **Generate G-code from layers** — posts to
   `POST /api/projects/{pid}/files/{fid}/cam/layered/gcode`.
3. The backend wraps each layer in the existing `cam_contour` op and
   concatenates the results with Z-step retracts between layers:
   ```
   G0 Z<safe_z>
   ; layer N — Z=<z_mm>
   G1 Z<z_mm> F<plunge_feed>
   <contour moves>
   G0 Z<safe_z>
   ```
4. The standard LinuxCNC / GRBL / Mach3 / Fanuc post-processors emit the
   final `.nc` file.

## Notes

- Layers at exact face-boundary positions (e.g. Z=0 or Z=height for a
  `pad`) may be degenerate — `BRepAlgoAPI_Section` returns an empty
  compound there.  These layers are silently omitted from the output.
- When `z_start_mm` / `z_end_mm` are omitted the bounding box is read via
  `BRepBndLib.Add` + `Bnd_Box.Get()`.  For complex assemblies with many
  sub-shapes this is fast (single OCCT call).
- The Python tool appends the `cam_layered` feature node to the `.feature`
  file even when OCCT is unavailable (the node records intent for
  round-trip fidelity); the `layers` key is absent and a `warning` key
  explains that OCC is not installed.
- JS live-preview (worker-side `evaluateTree` / `evaluateToFinalShape`
  dispatch for `cam_layered`) is **not shipped in v0.2**.  The viewport
  scrubber in `LayeredCAMView` uses the Python-produced `layers` array
  stored in the file content.  A worker dispatch can be added in v0.3 if
  real-time parameter-driven preview proves necessary.
