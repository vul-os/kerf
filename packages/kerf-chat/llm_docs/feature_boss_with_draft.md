# `feature_boss_with_draft` — pad + draft in one node

FreeCAD-parity shortcut. Extrudes a sketch profile (like `pad`) **and** applies
a draft taper to all side faces in a single step, eliminating the separate
pad → face-picking → `feature_draft` two-step workflow.

The neutral plane for the draft is always the sketch plane. The OCCT path is:

```
BRepPrimAPI_MakePrism → walkSideFaces → BRepOffsetAPI_DraftAngle
```

## Schema

```json
{
  "id": "boss_with_draft-1",
  "op": "boss_with_draft",
  "sketch_path": "/profile.sketch",
  "height": 25.0,
  "direction": "up",
  "draft_angle_deg": 3.0,
  "draft_direction": "outward"
}
```

### Parameters

| Parameter        | Type                            | Required | Default     | Notes |
|------------------|---------------------------------|----------|-------------|-------|
| `file_id`        | string (UUID)                   | yes      | —           | Target `.feature` file id |
| `sketch_path`    | string                          | yes      | —           | Absolute path to a closed-profile `.sketch` file |
| `height`         | number                          | yes      | —           | Extrusion height in mm. Must be > 0. |
| `draft_angle_deg`| number                          | yes      | —           | Taper angle in degrees. Clamped to `[-30, 30]`. `0` = no taper (plain pad). |
| `direction`      | `"up"` \| `"down"` \| `"symmetric"` | no  | `"up"`      | Extrusion direction. `"up"` = +Z, `"down"` = −Z, `"symmetric"` = centred on sketch plane. |
| `draft_direction`| `"outward"` \| `"inward"`      | no       | `"outward"` | `"outward"` = side faces widen away from the sketch plane. `"inward"` = narrow toward it. |
| `name`           | string                          | no       | `""`        | Human-readable label for the feature node. |
| `id`             | string                          | no       | auto        | Explicit node id (e.g. `"boss-1"`). Auto-generated if omitted. |

## Validation rules

- `sketch_path` must end in `.sketch` and be a non-empty string.
- `height` must be > 0.
- `draft_angle_deg` must be in the closed interval `[-30, 30]`.
  - `0` is allowed but emits a hint: the result is equivalent to a plain `pad`.
  - Values outside `[-30, 30]` are rejected with `BAD_ARGS`.
- `direction` must be one of `"up"`, `"down"`, `"symmetric"`.
- `draft_direction` must be `"outward"` or `"inward"`.

## Error codes

| Code               | Cause |
|--------------------|-------|
| `BAD_ARGS`         | Invalid parameter value (see validation rules above). |
| `NOT_FOUND`        | `file_id` does not resolve to a `feature`-kind file, OR the sketch produces no planar face. |
| `OCCT_BUILD_FAILED`| Draft angle too steep for the profile geometry (self-intersection). Try a smaller angle. |

## Behaviour notes

- **`draft_angle_deg = 0`** degenerates to a plain pad. The node is accepted
  and a `"hint"` field is added to the success payload, but no error is raised.
- **Inward vs outward**: for a `direction = "up"` boss, `"outward"` makes the
  base wider than the top; `"inward"` makes the top wider than the base.
- **Symmetric extrusion** centres the body on the sketch plane. The neutral
  plane for draft is still Z = 0 (the sketch plane). Both halves get the same
  taper applied from that plane.
- **Open profiles** fall through to the same behaviour as `pad` for open
  sketches — no new failure mode is introduced.
- **Draft self-intersection**: a very steep angle on a narrow, tall boss will
  cause the drafted side faces to intersect before reaching the top. OCCT
  returns `IsDone() = false`; the worker surfaces this as `OCCT_BUILD_FAILED`.
  Reduce `draft_angle_deg` or increase the profile width.

## Examples

### Injection-moulded boss (3° outward)

A 25 mm tall rectangular boss on a housing lid, extruded up from the sketch
plane with 3° outward taper so the boss releases cleanly from the mould:

```text
feature_boss_with_draft(
  file_id          = <housing.feature id>,
  sketch_path      = "/sketches/boss_profile.sketch",
  height           = 25.0,
  direction        = "up",
  draft_angle_deg  = 3.0,
  draft_direction  = "outward",
  name             = "lid_boss"
)
```

Resulting node:

```json
{
  "id": "boss_with_draft-1",
  "op": "boss_with_draft",
  "name": "lid_boss",
  "sketch_path": "/sketches/boss_profile.sketch",
  "height": 25.0,
  "direction": "up",
  "draft_angle_deg": 3.0,
  "draft_direction": "outward"
}
```

### Symmetric pin with inward taper

A 10 mm symmetric decorative pin centred on the sketch plane, tapered 5°
inward so it narrows away from the base on both sides:

```text
feature_boss_with_draft(
  file_id          = <pin.feature id>,
  sketch_path      = "/circle_4mm.sketch",
  height           = 10.0,
  direction        = "symmetric",
  draft_angle_deg  = 5.0,
  draft_direction  = "inward",
  name             = "centre_pin"
)
```

### When to prefer `pad` + `feature_draft` instead

Use separate `pad` + `feature_draft` nodes when:
- You need to draft only a **subset** of the side faces (not all of them).
- The neutral plane is a face **other than** the sketch plane.
- You want to add the draft taper to an existing body without re-extruding it.

`feature_boss_with_draft` always drafts **all** side faces from the sketch
plane. For selective drafting, use the two-step approach.
