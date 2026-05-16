# Clash Detection

Pure-Python cross-discipline clash detection for assembly components. Detects
hard interference (volume interpenetration), clearance violations (gap below a
minimum), and coincident/duplicate placements from placed bounding boxes and
optional triangle meshes. All dimensions in **millimetres**.

---

## When to use

Reach for this module when the user asks about:

- checking whether components in an assembly intersect or overlap
- finding interference between structural members, pipes, ducts, or equipment
- verifying minimum clearance gaps between components (e.g. 5 mm clearance rule)
- detecting duplicate or coincident component placements
- cross-discipline clash checking (structure vs MEP, structure vs architecture)
- validating a placed assembly before fabrication or export

---

## Tools

### `clash_detect`

Detect spatial clashes between a list of component instances. Each component is
described by a unique `instance_id`, local-frame axis-aligned bounding box
(`bbox_min`, `bbox_max` in mm), an optional 4×4 row-major transform matrix (16
floats; identity if omitted), and an optional triangle mesh for narrow-phase
mesh-level intersection testing. The `min_clearance` parameter (mm, default 0)
triggers clearance violations when components are closer than this gap. Returns
`clashes` list with type (`hard`, `clearance`, or `coincident`), penetration
depth, and `clash_count`.

---

## Example

**User ask:** "I have a steel column and a duct that might be clashing. The column
is 300×300 mm and the duct is 400 mm wide. Do they clash?"

```
clash_detect
  components:[
    {instance_id:"column-1",
     bbox_min:[0,0,0], bbox_max:[300,300,4000]},
    {instance_id:"duct-hvac-1",
     bbox_min:[200,150,1500], bbox_max:[600,350,2000]}
  ]
  min_clearance:50
→ {clashes:[{a:"column-1",b:"duct-hvac-1",type:"hard",depth:100.0}],
   clash_count:1}
```

---

## Notes

- All tools are **pure-Python**; no OCC dependency.
- Broad-phase: AABB overlap test in world frame (transform applied to bbox corners).
- Narrow-phase: triangle mesh intersection when `triangles` are provided.
- Clash types:
  - `hard` — bounding boxes (or meshes) overlap (volume interpenetration)
  - `clearance` — gap between boxes is less than `min_clearance`
  - `coincident` — identical bbox min/max (duplicate placement)
- Invalid inputs return `{ok:true, clashes:[], errors:[...]}` — never raise.
- `ok` in the response reflects whether the detection ran without errors, not
  whether clashes were found.
