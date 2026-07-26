# Sketch Tools (`sketch.py`)

2-D parametric sketcher: add/delete geometric entities and constraints to
`.sketch` files, update dimensional values, and copy reference geometry
between sketches (carbon-copy).

---

## When to use

Reach for these tools when the user asks to:

- add a point, line, circle, arc, ellipse, or B-spline to a sketch
- add a geometric or dimensional constraint (coincident, parallel, tangent,
  distance, angle, radius/diameter, etc.)
- change the value of a dimensional constraint
- delete an entity (cascades to dependent edges and constraints)
- copy reference geometry from one sketch into another for alignment

---

## Tools

### `sketch_add_entity`

Add a geometric entity to a `.sketch` file.

**Required:** `file_path` (str), `entity` (obj with `type`)
**Optional:** `construction` (bool, default false)

Supported `entity.type` values: `point`, `line`, `circle`, `arc`, `ellipse`, `bspline`

Entity shape depends on type (examples):
```json
{"type": "point", "x": 10.0, "y": 5.0}
{"type": "line",  "p1": "pt-1", "p2": "pt-2"}
{"type": "circle","center": "pt-1", "radius": 5.0}
{"type": "arc",   "center": "pt-1", "start": "pt-2", "end": "pt-3", "radius": 5.0}
{"type": "bspline","controls": ["pt-1","pt-2","pt-3"]}
```

**Returns:** `{ok: true, id: "<generated-id>"}`

---

### `sketch_add_constraint`

Add a geometric or dimensional constraint.

**Required:** `file_path` (str), `constraint` (obj with `type`)

Common constraint types: `coincident`, `parallel`, `perpendicular`,
`tangent`, `horizontal`, `vertical`, `fixed`, `distance`, `distance_x`,
`distance_y`, `angle`, `radius`, `diameter`, `equal`, `symmetric`.

**Returns:** `{ok: true, id: "<generated-id>"}`

---

### `sketch_set_constraint_value`

Update the numeric value of a dimensional constraint.

**Required:** `file_path`, `constraint_id`, `value` (number)
**Returns:** `{ok: true}`
**Errors:** `NOT_FOUND` if constraint id does not exist.

---

### `sketch_delete_entity`

Delete an entity by id with full cascade:
- Deleting a **point** also deletes any line/arc/circle/ellipse/bspline
  that references that point.
- Any constraint referencing a deleted id is also removed.

**Required:** `file_path`, `entity_id`
**Returns:** `{ok: true, deleted: ["<id>", ...]}`  — list of all removed ids.
**Errors:** `NOT_FOUND` if entity id does not exist.

---

### `sketch_carbon_copy`

Copy entities from a source sketch into a target sketch as driven
reference geometry (`is_reference: true`).  Reference entities
participate in constraints but are not extruded.

**Required:** `source_file_path`, `target_file_path`
**Optional:**
- `entity_ids` (array of str) — subset to copy; default copies all edges
- `translation` (`{x, y}`) — offset applied to copied coordinates
- `rotation_deg` — rotation applied before translation

**Returns:** `{ok: true, copied: <count>}`

---

## Supported input contract

- Sketch files are JSON documents stored in the project file table;
  `file_path` must be the project-relative path to a `.sketch` file.
- Entity ids are auto-generated (8-char hex) if not provided.
- Constraints reference entity ids by string; ids must already exist in the
  sketch unless the constraint only needs node names (e.g. `fixed`).
- `sketch_set_constraint_value` only updates dimensional constraints
  (those with a `value` field); geometric constraints have no numeric value.

---

## Usage examples

**Add a circle and constrain its diameter:**

```
sketch_add_entity
  file_path: "/proj/profile.sketch"
  entity: {type:"circle", center:"pt-1", radius:5.0}
→ {ok:true, id:"a3f1b2c4"}

sketch_add_constraint
  file_path: "/proj/profile.sketch"
  constraint: {type:"diameter", entity:"a3f1b2c4", value:10.0}
→ {ok:true, id:"d9e4f5a6"}
```

**Update a dimensional constraint value:**

```
sketch_set_constraint_value
  file_path: "/proj/profile.sketch"
  constraint_id: "d9e4f5a6"
  value: 12.0
→ {ok:true}
```

**Delete a point (cascade removes attached line):**

```
sketch_delete_entity
  file_path: "/proj/profile.sketch"
  entity_id: "pt-1"
→ {ok:true, deleted:["pt-1","line-2"]}
```

**Carbon-copy reference circle into another sketch:**

```
sketch_carbon_copy
  source_file_path: "/proj/profile.sketch"
  target_file_path: "/proj/path.sketch"
  entity_ids: ["a3f1b2c4"]
  translation: {x:0, y:50}
→ {ok:true, copied:1}
```
