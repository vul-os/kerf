# Authoring `.sketch` files

A Sketch is a parametric 2D profile: a set of geometric entities
(points, lines, arcs, …) plus geometric and dimensional constraints.
The frontend's planegcs solver reconciles the constraints. JSCAD code
imports the resulting profile as a Geom2 to extrude or revolve.

> **Tooling note:** Sketches are normally authored in the visual
> sketch UI. You can scaffold a blank one with `create_sketch`, then
> author the entities and constraints by editing JSON via `write_file` /
> `edit_file`. The sketch UI re-solves on next load.

## File shape

```json
{
  "version": 1,
  "plane": { "type": "base", "name": "XY" },
  "entities": [
    { "id": "origin", "type": "point", "x": 0, "y": 0 },
    { "id": "p1",     "type": "point", "x": 10, "y": 0 },
    { "id": "p2",     "type": "point", "x": 10, "y": 5 },
    { "id": "p3",     "type": "point", "x": 0,  "y": 5 },
    { "id": "l1",     "type": "line", "p1": "origin", "p2": "p1" },
    { "id": "l2",     "type": "line", "p1": "p1",     "p2": "p2" },
    { "id": "l3",     "type": "line", "p1": "p2",     "p2": "p3" },
    { "id": "l4",     "type": "line", "p1": "p3",     "p2": "origin" }
  ],
  "constraints": [
    { "id": "c1", "type": "coincident", "p1": "origin", "p2": "p1" },
    { "id": "c2", "type": "h",          "line": "l1" },
    { "id": "c3", "type": "v",          "line": "l2" },
    { "id": "c4", "type": "distance_x", "p1": "origin", "p2": "p1", "value": 10 },
    { "id": "c5", "type": "distance_y", "p1": "p1",     "p2": "p2", "value": 5 }
  ],
  "visible_3d": [],
  "solved": {},
  "metadata": { "name": "rect", "description": "10×5 rectangle" }
}
```

## Plane

```json
{ "type": "base", "name": "XY" }   // | "XZ" | "YZ"
```

Future-shape (face-anchored): `{ "type": "face", "file_id": "<uuid>",
"face_id": "..." }`.

## Entities

| `type`   | required keys                                                                    |
|----------|----------------------------------------------------------------------------------|
| `point`  | `id`, `x`, `y`                                                                   |
| `line`   | `id`, `p1`, `p2`                                                                 |
| `arc`    | `id`, `center`, `start`, `end`, `sweep_ccw` (bool), `radius`                     |
| `circle` | `id`, `center`, `radius`                                                         |
| `ellipse`| `id`, `center`, `radius_x`, `radius_y`, optional `rotation`                      |
| `bspline`| `id`, `controls` (array of point ids), `degree` (3)                              |
| `bezier` | `id`, `control_points` (array of point ids), `degree` (inferred: n+1 pts → n)   |

### Bezier curves

A polynomial Bezier curve is defined entirely by its control points. Unlike
B-splines, the first and last control points are exactly on the curve; the
inner points are "handles" that pull the curve toward them.

```json
{
  "id": "bz1",
  "type": "bezier",
  "degree": 3,
  "control_points": ["p0", "p1", "p2", "p3"]
}
```

Rules:
- **Degree 2 (quadratic)**: 3 control points. One handle.
- **Degree 3 (cubic)**: 4 control points. The most common case. Two handles.
- Degree is inferred from the `control_points` count (`n+1 points → degree n`).
- All control points must be `point` entities in the same sketch.
- Add `"construction": true` for reference-only curves excluded from extrude.

UI: select the **Bezier** tool (key `Z`), click control points in sequence,
then press **Enter** or **double-click** to commit. The ghost preview shows the
actual Bezier curve as soon as 3 points exist.

Control-point drag works like any other point — select a control-point entity
and drag. The curve updates live via the constraint solver.

Add `"construction": true` to mark an entity as construction-only — it
participates in constraints but isn't extruded.

## Constraints

Geometric:
- `coincident` — `{p1, p2}`
- `h` — `{line}` horizontal
- `v` — `{line}` vertical
- `parallel` — `{line1, line2}`
- `perpendicular` — `{line1, line2}`
- `tangent` — `{a, b}` (line ↔ arc/circle, or two arcs/circles)
- `equal_length` — `{line1, line2}`
- `equal_radius` — `{c1, c2}` (circles or arcs)
- `point_on_line` — `{point, line}` point lies on the line (free to slide along)
- `point_on_arc` — `{point, arc}`
- `midpoint` — `{point, line}` point pinned to the line's midpoint
- `symmetric` — `{p1, p2, axis}` axis is a line id (legacy: axis-aligned; uses any line)
- `symmetric_over_line` — `{entity_a_id, entity_b_id, construction_line_id}` mirror entity_a
  across an arbitrary construction line so it is the mirror image of entity_b. Works with
  points, lines, circles, arcs, bezier and bspline curves. Composite entities are decomposed
  into multiple `p2p_symmetric_ppl` point-pair primitives automatically.
- `block` — `{point}` lock the point at its current `(x, y)`; pair with `coordinate_x`/`coordinate_y` if you want a specific value
- `bezier_tangent` — `{p0, p1, p2}` direction-only tangent at a Bezier junction: p1 is the shared endpoint; p0 and p2 are the adjacent handles of each segment. Enforces p0–p1–p2 collinearity (G1 direction).
- `bezier_g1` — `{p0, p1, p2}` G0+G1 at a Bezier junction (use alongside a `coincident` for the shared endpoint). Same collinearity as `bezier_tangent`.

> **G2 note**: planegcs 1.1.x has no `CurvatureMatch` primitive in its
> push_primitive API, so G2 curvature-continuity constraints are not yet
> supported. Ship G0+G1 today; G2 will land when the upstream binding adds it.

Dimensional (carry `value`):
- `distance` — `{p1, p2, value}` Euclidean distance
- `distance_x` — `{p1, p2, value}` X projection
- `distance_y` — `{p1, p2, value}` Y projection
- `angle` — `{line1, line2, value}` degrees
- `radius` — `{circle, value}` (or `{arc, value}`)
- `diameter` — `{circle, value}`

## Symmetry constraints

Kerf supports two symmetry constraint types.

### Axis-aligned symmetry (`symmetric`)

The legacy form. Takes two *point* entity ids and a line id.

```json
{ "id": "c1", "type": "symmetric", "a": "p1", "b": "p2", "line": "axis_line" }
```

### Arbitrary-line symmetry (`symmetric_over_line`)

Mirror any entity (or pair of composite entities) across a user-drawn
construction line. The construction line must be a `line` entity with
`"construction": true` to distinguish it from profile geometry.

```json
{
  "id": "c2",
  "type": "symmetric_over_line",
  "entity_a_id": "p1",
  "entity_b_id": "p2",
  "construction_line_id": "axis"
}
```

**Before** adding the constraint — two free points and a diagonal construction line:

```json
{
  "entities": [
    { "id": "origin", "type": "point", "x": 0,  "y": 0 },
    { "id": "p1",     "type": "point", "x": -5, "y": 3 },
    { "id": "p2",     "type": "point", "x": 7,  "y": 8 },
    { "id": "lp1",    "type": "point", "x": 0,  "y": 0 },
    { "id": "lp2",    "type": "point", "x": 10, "y": 0 },
    { "id": "axis",   "type": "line",  "p1": "lp1", "p2": "lp2", "construction": true }
  ],
  "constraints": []
}
```

**After** adding `symmetric_over_line` (once solved, p2 will be the mirror image of p1
across the horizontal axis line):

```json
{
  "constraints": [
    {
      "id": "sym1",
      "type": "symmetric_over_line",
      "entity_a_id": "p1",
      "entity_b_id": "p2",
      "construction_line_id": "axis"
    }
  ]
}
```

Supported entity pairs:

| entity_a / entity_b | planegcs primitives emitted |
|---------------------|------------------------------|
| `point` / `point`   | 1 × `p2p_symmetric_ppl`     |
| `line` / `line`     | 2 × `p2p_symmetric_ppl`     |
| `circle` / `circle` | 1 × `p2p_symmetric_ppl` (centers) + `equal_radius_cc` |
| `arc` / `arc`       | 3 × `p2p_symmetric_ppl` (center, start↔end, end↔start) + `equal_radius_aa` |
| `bezier` / `bezier` | N × `p2p_symmetric_ppl` (control_points[i] ↔ control_points[N-1-i]) |
| `bspline` / `bspline` | N × `p2p_symmetric_ppl` (controls[i] ↔ controls[N-1-i]) |

The arc case intentionally swaps start/end to preserve the winding direction.

## Common authoring patterns

### A single closed loop (rectangle, polygon)

Pin one corner with `coincident` to `origin` (or a fixed point). Then
add `h`/`v` constraints to lock orientation, and `distance_x`/
`distance_y` for width and height.

### A circle of given diameter centered on origin

```json
{ "id": "c", "type": "circle", "center": "origin", "radius": 5 },
{ "id": "d", "type": "diameter", "circle": "c", "value": 10 }
```

The solver enforces `radius = value / 2`.

### A slot

Two parallel construction lines, two end arcs tangent to the lines,
plus `equal_radius` between the arcs.

## Tips

- Keep `id` short and descriptive (`p1`, `bot-right`, `arc-1`).
- The `solved` block is overwritten by planegcs on load; you can leave
  it `{}`.
- `visible_3d` is a list of entity ids the user wants to render in the
  3D backdrop alongside the sketch — usually leave empty when authoring.
- Sketches are imported into JSCAD as:
  `import profile from "/path.sketch"` → returns a Geom2.

---

## Carbon-copy reference geometry

Use `sketch_carbon_copy` to pull geometry from another sketch into the current
one as **driven reference** (read-only). Reference entities carry:

```json
{
  "id": "<cc_source>_<original_id>",
  "type": "line",
  "p1": "<cc_source>_<p1_id>",
  "p2": "<cc_source>_<p2_id>",
  "is_reference": true,
  "construction": true,
  "cc_source": "<source_sketch_id>",
  "source_id": "<original_entity_id>"
}
```

Key properties:
- `is_reference: true` — entity is driven; the UI renders it in a distinct
  colour and prevents direct editing.
- `construction: true` — excluded from extrude / shape output.
- `cc_source` — opaque string key identifying which source sketch this came
  from. Used by `refreshCarbonCopies` to re-sync geometry.
- `source_id` — the original entity id in the source sketch.
- `unresolved: true` — set by `refreshCarbonCopies` when the source sketch is
  no longer available; `sketch_validate` will flag this.

The sketch also gains a top-level `cc_sources` array listing all source ids:

```json
{ "cc_sources": ["profiles_rect_sketch"] }
```

### Tool: `sketch_carbon_copy`

```
sketch_carbon_copy({
  source_file_path,   // path to the source .sketch
  target_file_path,   // path to the target .sketch (modified in-place)
  entity_ids?,        // optional list of edge ids to copy (default: all)
  translation?,       // { x?, y? } applied to copied coordinates
  rotation_deg?       // rotation in degrees applied to copied coordinates
})
→ { ok, copied, cc_source }
```

Calling this multiple times for the same source replaces the previous copy
(ids are stable, so existing constraints survive the refresh).

---

## Sketch validation

Use `sketch_validate` before relying on a sketch in a feature operation.

### Tool: `sketch_validate`

```
sketch_validate({ file_path })
→ { errors: [...], warnings: [...] }
```

Each entry has `{ kind, severity, message, entity_id? }`.

| `kind`                    | `severity` | Trigger                                                     |
|---------------------------|------------|-------------------------------------------------------------|
| `open_contour`            | error      | Edge loop has an endpoint connected to only one edge        |
| `self_intersection`       | error      | Two non-adjacent edges cross each other                     |
| `redundant_constraint`    | error      | Estimated DOF < 0 (over-constrained)                        |
| `dangling_endpoint`       | warning    | Edge endpoint has no `coincident` or `fixed` constraint     |
| `unresolved_external_ref` | error      | Reference entity's source sketch is missing or deleted      |

A sketch with zero errors is safe to extrude. Warnings indicate incomplete
constraint coverage but won't block feature evaluation.
