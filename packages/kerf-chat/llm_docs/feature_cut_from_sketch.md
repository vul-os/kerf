# `feature_cut_from_sketch` — cut a face-anchored slot from a sketch

Appends a `cut_from_sketch` node to a `.feature` file.  Subtracts a
sketched region from a specific planar face of an existing body, extruding
the cutter **normal to that face** rather than normal to the sketch plane.

This is the key difference from `pocket`:

| Op | Cutter direction |
|----|-----------------|
| `pocket` | Normal to the sketch plane (always along the sketch's own Z-axis). |
| `cut_from_sketch` | Normal to the **target face** — works on any planar face including inclined and side faces. |

Use `cut_from_sketch` whenever you want to slot into a face that is not
parallel to any base plane, or when the sketch lives on a different plane
from the face you want to cut into.

## Schema

```json
{
  "id": "cut-1",
  "op": "cut_from_sketch",
  "target_id": "pad-1",
  "target_face_id": 7,
  "sketch_path": "/slot.sketch",
  "depth": 4,
  "reverse": false
}
```

### Parameters

| Parameter        | Type            | Required | Default | Notes                                                                 |
|------------------|-----------------|----------|---------|-----------------------------------------------------------------------|
| `file_id`        | string (uuid)   | yes      | —       | Target `.feature` file id                                             |
| `target_id`      | string          | yes      | —       | Feature node id of the body to cut into (e.g. `"pad-1"`)             |
| `target_face_id` | integer         | yes      | —       | Post-evaluation face index of the planar face to cut from (≥ 0)      |
| `sketch_path`    | string          | yes      | —       | Path to the `.sketch` file; must produce a closed loop                |
| `depth`          | number          | yes      | —       | Cut depth in mm (must be > 0)                                         |
| `reverse`        | boolean         | no       | `false` | When `true`, extrude along `+normal` instead of `-normal`             |
| `name`           | string          | no       | `""`    | Optional human-readable label for the node                            |

## OCCT evaluation pathway

1. `faceById(prev, target_face_id)` — retrieve the target face from the
   body produced by the preceding feature.
2. `faceFrame(face)` — compute the face's world-space frame: `origin`,
   `normal`, `uDir`, `vDir`.  The op errors if the face is non-planar.
3. `faceForSketchPath(sketch_path)` — build a profile face from the
   sketch's closed loop, initially in the sketch's own plane (XY by
   default).
4. `placeFaceOnPlane(profile, {type:'face', frame})` — re-orient the
   profile onto the target face's frame so the sketch's local X/Y map to
   the face's U/V directions and the sketch origin maps to the face's
   origin.
5. Extrusion vector = `-normal * depth` (or `+normal * depth` when
   `reverse: true`).
6. `BRepPrimAPI_MakePrism(oriented_profile, vec)` — build the cutter solid.
7. `BRepAlgoAPI_Cut_3(body, cutter)` — boolean subtraction.

## Face-id stability caveat

`target_face_id` is the post-evaluation index assigned by the worker's
TopExp explorer pass at the time you run the tool.  It is stable across
**parameter-only edits** (changing depth, sketch geometry, fillets on
downstream nodes) but **will change** if:

- A pad or revolve upstream changes shape (adds or removes faces),
- A new feature node is inserted before this node in the timeline,
- The target body is rebuilt from a different sketch profile.

After any such structural upstream change, re-pick the face in the
inspector and re-run `feature_cut_from_sketch` with the new id.  Phase 4's
persistent-naming layer will fix this automatically; v1 documents the
limitation.

This caveat mirrors `push_pull`'s documented face-id behaviour.

## Examples

### Slot on an inclined face

A mounting bracket (`pad-1`) has an angled top face at 30° (face 7).  You
want to cut a 3 × 10 mm rectangular slot into it.  The slot sketch
(`/slot.sketch`) is drawn in the XY plane; `cut_from_sketch` re-orients it
onto face 7 and cuts inward:

```text
feature_cut_from_sketch(
  file_id        = <bracket.feature id>,
  target_id      = "pad-1",
  target_face_id = 7,
  sketch_path    = "/slot.sketch",
  depth          = 3,
  name           = "angled_slot"
)
```

Resulting node:

```json
{
  "id": "cut-1",
  "op": "cut_from_sketch",
  "name": "angled_slot",
  "target_id": "pad-1",
  "target_face_id": 7,
  "sketch_path": "/slot.sketch",
  "depth": 3,
  "reverse": false
}
```

### Keyway on a side face

A shaft collar (`pad-2`) has a +X side face (face 3) into which you need a
3 × 3 mm keyway.  Draw the keyway profile in `/keyway.sketch` (XY plane),
then:

```text
feature_cut_from_sketch(
  file_id        = <collar.feature id>,
  target_id      = "pad-2",
  target_face_id = 3,
  sketch_path    = "/keyway.sketch",
  depth          = 3,
  name           = "keyway"
)
```

### Reverse direction

When the face normal points away from the body interior (e.g. a bottom face
where the normal points down), set `reverse: true` so the cutter travels
inward:

```text
feature_cut_from_sketch(
  file_id        = <part.feature id>,
  target_id      = "pad-1",
  target_face_id = 0,
  sketch_path    = "/pocket.sketch",
  depth          = 5,
  reverse        = true
)
```

## Validation rules

- `target_face_id` must be an integer ≥ 0.
- `sketch_path` must be a non-empty string.
- `depth` must be > 0.
- `reverse` must be a boolean (or omitted; defaults to `false`).
- The target face must be planar; non-planar faces produce `BAD_ARGS`.
- An out-of-range `target_face_id` produces `NOT_FOUND` at eval-time.
- `file_id` must be a valid UUID pointing to a `feature`-kind file.

## Comparison with related tools

| Need | Tool |
|------|------|
| Cut normal to sketch plane through the whole body | `pocket` |
| Cut normal to a specific face of the body | `feature_cut_from_sketch` |
| Push or pull a face outward / inward uniformly | `push_pull` |
| Drill a cylindrical hole through a body | `hole` |
