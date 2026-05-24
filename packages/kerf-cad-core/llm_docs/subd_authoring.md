# SubD / Mesh Authoring Tools (GK-P45)

SubD cage authoring ops: poke a face, extrude along a curve, sculpt-brush
strokes, and multi-resolution displacement stacks. All ops append a node to
a `.feature` file. Evaluation is pure-Python SubD (no OCCT required).

---

## When to use

Reach for these tools when the user asks about:

- Subdividing a specific face into triangles (centroid fan / poke)
- Extruding a face along a polyline spine (cable organiser, horn, tentacle)
- Sculpting a SubD cage — grab, smooth, or inflate vertices
- Multi-resolution displacement sculpting (ZBrush-style layered sculpt)
- Retopology: projecting a cage onto a reference scan or high-res mesh

---

## Tools

### `feature_subd_poke`

Poke a SubD cage face: insert a centroid vertex and fan the n-gon into n
triangles (one per edge). For a quad face → 4 triangles; for a triangle → 3
triangles.

**Required:** `file_id`, `target_id` (existing SubD cage node), `face_id` (0-based)
**Optional:** `id`
**Returns:** `{file_id, id, op:"subd_poke"}`

---

### `feature_subd_extrude_along`

Sweep a SubD cage face along a polyline spine. `curve_pts` is a list of
`[x,y,z]` points (≥2); the first point is the start (at the face location).
Side walls are quad faces connecting consecutive profile copies.

**Required:** `file_id`, `target_id`, `face_id`, `curve_pts` (≥2 points)
**Optional:** `id`
**Returns:** `{file_id, id, op:"subd_extrude_along", steps}`

---

### `feature_sculpt_brush`

Apply a sculpt-brush stroke to a SubD cage. Moves, smooths, or inflates
vertices within `radius` of `center`.

Modes:
- `grab` — translate vertices by `direction × weight × strength`
- `smooth` — laplacian smooth toward ring-neighbour average
- `inflate` — push vertices along their estimated normal

**Required:** `file_id`, `target_id`, `center` [x,y,z], `radius`, `mode`
**Optional:** `falloff` (default 2.0), `strength` (default 0.5), `direction` [dx,dy,dz] (grab only), `id`
**Returns:** `{file_id, id, op:"sculpt_brush", mode}`

---

### `feature_multires_evaluate`

Evaluate a `MultiresStack` at a subdivision level with per-vertex displacement
maps. Stores the displacement map (`displacements` dict keyed by level string)
in the feature node so the evaluator can reconstruct and call `.evaluate(level)`.

**Required:** `file_id`, `target_id`
**Optional:** `level` (0–6, default 2), `max_levels` (1–6, default 2), `displacements` ({level: [[dx,dy,dz],...]}), `id`
**Returns:** `{file_id, id, op:"multires_evaluate", level, max_levels}`

---

## Example

**User ask:** "Poke face 2 of my SubD cage, then sculpt-grab the area near the
centroid outward by 3mm."

```
1. feature_subd_poke
     file_id:"<uuid>"
     target_id:"cage-1"
     face_id:2
   → {id:"subd_poke-1", op:"subd_poke"}

2. feature_sculpt_brush
     file_id:"<uuid>"
     target_id:"subd_poke-1"
     center:[0,0,5]
     radius:8
     mode:"grab"
     direction:[0,0,3]
     strength:0.8
   → {id:"sculpt_brush-1", op:"sculpt_brush", mode:"grab"}
```

---

## Notes

- All ops are pure-Python SubD; no OCCT worker dispatch.
- `face_id` is a 0-based index into the cage's face list — use the inspector to see current face count.
- `sculpt_brush` never raises — out-of-range or empty results return an unmodified copy.
- `feature_multires_evaluate` `displacements` is a JSON object: keys are level strings ("0", "1", ...).
