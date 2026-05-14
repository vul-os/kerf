# `feature_sweep1` — sweep a profile along a single path

Appends a `sweep1` node to a `.feature` file. Sweep1 extrudes a closed
profile sketch along **one** open-curve path to produce a tube, shank, or
pipe body. The profile is repositioned at every point along the path using
the chosen frame mode.

Use `sweep1` when:
- You have one path curve and one cross-section (ring shank, tube, pipe coil,
  cable conduit, extrusion along a curved axis).
- You need `corrected_frenet` to avoid roll artefacts on coils or spirals.

Use `feature_sweep2` when you have **two** rail curves that should govern
both position and section orientation (e.g. oval ring shanks with separate
inner and outer rail).

## Schema

```json
{
  "id": "sweep1-1",
  "op": "sweep1",
  "profile_sketch_path": "/circle_profile.sketch",
  "path_sketch_path": "/helix_path.sketch",
  "scale": 1.0,
  "twist_deg": 0,
  "mode": "corrected_frenet"
}
```

### Parameters

| Parameter             | Type          | Required | Default            | Notes                                                    |
|-----------------------|---------------|----------|--------------------|----------------------------------------------------------|
| `file_id`             | string (uuid) | yes      | —                  | Target `.feature` file id                                |
| `profile_sketch_path` | string        | yes      | —                  | Absolute path of the closed-profile `.sketch` file       |
| `path_sketch_path`    | string        | yes      | —                  | Absolute path of the open-curve path `.sketch` file      |
| `scale`               | number        | no       | `1.0`              | Uniform scale factor applied to the profile              |
| `twist_deg`           | number        | no       | `0`                | Total twist (degrees) accumulated over the full path     |
| `mode`                | string (enum) | no       | `"auto"`           | Frame mode — see table below                             |
| `id`                  | string        | no       | auto-generated     | Explicit node id (`"sweep1-N"`)                          |

### `mode` values

| Value               | OCCT call         | When to use                                                                    |
|---------------------|-------------------|--------------------------------------------------------------------------------|
| `"auto"`            | default frame     | Everyday sweeps on smooth paths; matches today's existing behaviour.           |
| `"frenet"`          | `SetMode_2(true)` | Classic Frenet–Serret frame; marginally faster. Can exhibit roll near inflections. |
| `"corrected_frenet"`| `SetMode_5(true)` | **Tangent-locked** corrected Frenet frame. Eliminates roll on coils, spirals,  |
|                     |                   | jewellery shanks, or any path with high curvature variation. Recommended for   |
|                     |                   | helical paths and organic shapes where section orientation matters.             |

**Degraded mode caveat.** If the OpenCASCADE.js build in use lacks `SetMode_5`,
the worker silently falls back to the default frame and emits a console warning:
`sweep1: SetMode_5 (corrected Frenet) unavailable on this build; degraded:true`.
The geometry is still produced; only the frame correction is absent. This is
expected on older builds and will resolve when the WASM bundle is updated.

## Worked examples

### 1. Simple tube along a straight path — `"auto"` (default)

```json
{
  "id": "sweep1-1",
  "op": "sweep1",
  "profile_sketch_path": "/circle_8mm.sketch",
  "path_sketch_path": "/spine.sketch",
  "mode": "auto"
}
```

Use `"auto"` for straight or gently curved paths where frame orientation
is not critical.

### 2. Ring shank along a circular arc — `"frenet"`

```json
{
  "id": "sweep1-1",
  "op": "sweep1",
  "profile_sketch_path": "/oval_profile.sketch",
  "path_sketch_path": "/ring_arc.sketch",
  "mode": "frenet"
}
```

Frenet works well on circular arcs that have consistent curvature. If the
arc has near-inflection points, switch to `"corrected_frenet"`.

### 3. Coil spring / helix — `"corrected_frenet"` (recommended)

```json
{
  "id": "sweep1-1",
  "op": "sweep1",
  "profile_sketch_path": "/wire_section.sketch",
  "path_sketch_path": "/helix_5turns.sketch",
  "mode": "corrected_frenet"
}
```

On a helix path, plain Frenet causes the cross-section to rotate (roll)
as the path winds. `"corrected_frenet"` locks the section's local Y-axis
to the path tangent `T̂(s)` so there is no accumulated twist. This is the
right choice for coil springs, bracelet forms, hose routing, and cable
management shapes.

### 4. Tapered sweep with twist

```json
{
  "id": "sweep1-1",
  "op": "sweep1",
  "profile_sketch_path": "/ellipse_profile.sketch",
  "path_sketch_path": "/s_curve_path.sketch",
  "scale": 0.5,
  "twist_deg": 90,
  "mode": "corrected_frenet"
}
```

`scale` shrinks the profile uniformly at the end. `twist_deg` adds a
deliberate 90° twist over the full path length. Use `"corrected_frenet"`
so the intended twist is the **only** rotation — background frame roll
is suppressed.

## How it differs from `feature_sweep2`

`sweep1` takes one path; `sweep2` takes two rails. When you need a cross
section to track two boundary curves simultaneously (oval ring inner/outer
curves, a duct whose width varies independently of its height), use
`feature_sweep2`. When you have one spine and want precise control over
section roll, use `feature_sweep1` with `mode: "corrected_frenet"`.
