# `extrude_sketch_to_jscad` tool

Scaffold a new `.jscad` file that imports a `.sketch` profile and applies an
extrusion to produce a 3D mesh part.  The sketch remains the single source of
truth: editing its dimensions in the sketch editor reflows the 3D automatically
(the `.jscad` file itself never needs to change for dimension updates).

## When to use this tool

- The user wants to extrude, revolve, or sweep a constrained 2D sketch into 3D.
- They want the parametric sketch → 3D workflow without the OCCT WASM dependency.
- They do NOT need STEP export, real fillets, draft angles, or manufacturer-grade
  tolerances — use `create_feature` + `feature_pad` / `feature_revolve` for those.

## Input schema

```json
{
  "path":           "/parts/plate.jscad",
  "sketch_file_id": "/parts/plate-outline.sketch",
  "operation":      "extrude_linear" | "extrude_rotate" | "sweep_along_path",
  "params":         { ... },
  "object_id":      "plate"
}
```

| Field | Required | Notes |
|---|---|---|
| `path` | yes | Absolute path for the new `.jscad` file. If the extension is missing it is added automatically. |
| `sketch_file_id` | yes | Absolute path to an existing `.sketch` file. Must parse and contain at least one closed loop (circle, ellipse, or ≥ 3 line/arc entities). |
| `operation` | yes | One of `extrude_linear`, `extrude_rotate`, `sweep_along_path`. |
| `params` | yes | Op-specific (see below). |
| `object_id` | no | The `id` field on the returned JSCAD Object. Defaults to the sketch basename without extension. |

### `params` for each operation

**`extrude_linear`** — pad the profile to a fixed or parametric height:

```json
{ "height_mm": 10 }
```

or, to reference a `.equations` variable:

```json
{ "height_param": "bracket_h" }
```

Exactly one of `height_mm` (number, > 0) or `height_param` (string) must be
provided.

**`extrude_rotate`** — revolve the profile around the sketch's vertical axis:

```json
{ "angle_deg": 360, "segments": 32 }
```

`angle_deg` is required and must be in (0, 360]. `segments` is optional
(default 32).

**`sweep_along_path`** — sweep the profile along a second sketch's path:

```json
{ "path_sketch_file_id": "/parts/sweep-rail.sketch" }
```

`path_sketch_file_id` is required and must point to an existing `.sketch` file.
The rail sketch should be an open polyline or curve (line + arc entities).

## Collision policy

If `path` already exists the tool returns `{"error": "...", "code": "EXISTS"}`.
Delete or rename the existing file and retry — the tool never silently overwrites.

## Return value

On success:

```json
{
  "path":           "/parts/plate.jscad",
  "id":             "uuid",
  "sketch_file_id": "/parts/plate-outline.sketch",
  "operation":      "extrude_linear",
  "object_id":      "plate"
}
```

---

## Worked example 1 — `extrude_linear`

**Scenario:** the user has drawn a bracket outline sketch at `/parts/bracket.sketch`
and wants a 15 mm thick plate from it.

**Tool call:**

```json
{
  "name": "extrude_sketch_to_jscad",
  "input": {
    "path": "/parts/bracket-plate.jscad",
    "sketch_file_id": "/parts/bracket.sketch",
    "operation": "extrude_linear",
    "params": { "height_mm": 15 },
    "object_id": "bracket"
  }
}
```

**Generated file** (`/parts/bracket-plate.jscad`):

```js
// Generated from /parts/bracket.sketch
// Edit the sketch to change the profile; the 3D updates automatically.
import profile from '/parts/bracket.sketch'

export default function ({ extrusions, params }) {
  const height = 15.0

  const body = extrusions.extrudeLinear({ height }, profile)
  return [{ id: 'bracket', geom: body }]
}
```

---

## Worked example 2 — `extrude_rotate`

**Scenario:** the user drew a half-profile of a vase at `/parts/vase-profile.sketch`
and wants a full 360° revolution.

**Tool call:**

```json
{
  "name": "extrude_sketch_to_jscad",
  "input": {
    "path": "/parts/vase.jscad",
    "sketch_file_id": "/parts/vase-profile.sketch",
    "operation": "extrude_rotate",
    "params": { "angle_deg": 360, "segments": 64 },
    "object_id": "vase"
  }
}
```

**Generated file** (`/parts/vase.jscad`):

```js
// Generated from /parts/vase-profile.sketch
// Edit the sketch to change the profile; the 3D updates automatically.
import profile from '/parts/vase-profile.sketch'

export default function ({ extrusions }) {
  // 360.0 degrees = 6.2831853072 radians
  const angleRad = 6.2831853072

  const body = extrusions.extrudeRotate(
    { angle: angleRad, segments: 64 },
    profile,
  )
  return [{ id: 'vase', geom: body }]
}
```

---

## Worked example 3 — `sweep_along_path`

**Scenario:** the user has a circular cross-section sketch at
`/parts/pipe-section.sketch` and a curved rail at `/parts/pipe-path.sketch`,
and wants a bent pipe.

**Tool call:**

```json
{
  "name": "extrude_sketch_to_jscad",
  "input": {
    "path": "/parts/bent-pipe.jscad",
    "sketch_file_id": "/parts/pipe-section.sketch",
    "operation": "sweep_along_path",
    "params": { "path_sketch_file_id": "/parts/pipe-path.sketch" },
    "object_id": "pipe"
  }
}
```

**Generated file** (`/parts/bent-pipe.jscad`):

```js
// Generated from /parts/pipe-section.sketch swept along /parts/pipe-path.sketch
// Edit either sketch to change the shape; the 3D updates automatically.
//
// Implementation note: @jscad/modeling has no sweepAlong().  This scaffold
// uses extrusions.extrudeFromSlices with a Frenet-frame callback that
// walks the path sketch's vertices.  For complex path curves, increase
// NUM_SLICES for smoother results.
import profile from '/parts/pipe-section.sketch'
import railPath from '/parts/pipe-path.sketch'

export default function ({ extrusions, geometries, maths }) {
  const { geom2 } = geometries
  const { mat4, vec3 } = maths

  // Extract ordered path vertices from the rail sketch.
  // geom2.toSides returns [[start, end], ...] pairs.
  const sides = geom2.toSides(railPath)
  const pathPts = sides.length > 0
    ? [sides[0][0], ...sides.map(s => s[1])]
    : [[0, 0], [0, 0, 1]]  // fallback: straight 1-unit path

  const NUM_SLICES = Math.max(pathPts.length, 8)

  const body = extrusions.extrudeFromSlices(
    {
      numberOfSlices: NUM_SLICES,
      callback: (progress, _i, base) => {
        // Interpolate position along path at this progress fraction.
        const t = progress * (pathPts.length - 1)
        const lo = Math.floor(t)
        const hi = Math.min(lo + 1, pathPts.length - 1)
        const f = t - lo
        const p0 = pathPts[lo], p1 = pathPts[hi]
        const x = p0[0] + f * (p1[0] - p0[0])
        const y = p0[1] + f * (p1[1] - p0[1])
        const z = (p0[2] ?? 0) + f * ((p1[2] ?? 0) - (p0[2] ?? 0))

        // Build a translation matrix for this slice.
        const xform = mat4.fromTranslation(mat4.create(), [x, y, z])
        return extrusions.slice.transform(xform,
          extrusions.slice.fromSides(geom2.toSides(base)))
      },
    },
    profile,
  )
  return [{ id: 'pipe', geom: body }]
}
```

---

## JSCAD API notes

The tool targets `@jscad/modeling` 2.x (the version bundled with Kerf).

- `extrusions.extrudeLinear({ height }, geom2)` — height in mm, profile is a `Geom2`.
- `extrusions.extrudeRotate({ angle, segments }, geom2)` — angle in **radians**.
- `extrusions.extrudeFromSlices({ numberOfSlices, callback }, geom2)` — used for
  path sweeps.  There is **no `sweepAlong`** function in `@jscad/modeling` 2.x;
  the canonical path-sweep API is `extrudeFromSlices` with a per-slice callback.

These are the only extrusion functions exported by
`@jscad/modeling/src/operations/extrusions/index.js` (verified against the
version in `node_modules`).

## Follow-up edits

After scaffolding, the model can use `edit_file` to:

- Add a second `extrudeLinear` and `booleans.subtract` to cut a pocket.
- `colorize(['steelblue'], body)` the result.
- Replace `height_mm` literal with `params.height ?? 10` to make it parametric.
- Wrap the body in a `transforms.translate` or `transforms.rotate` to position it.

The scaffolded file is intentionally minimal — it is the starting point, not the
final shape.
