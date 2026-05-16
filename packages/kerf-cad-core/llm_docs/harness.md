# Wiring Harness Routing and BOM

Pure-Python 3-D wiring harness routing with bundle sizing and bill-of-materials
rollup. Routes a harness through connector endpoints and optional via-points,
checks bend-radius compliance, detects obstacle hits, and generates procurement
BOM by wire gauge. Units: **metres** (m). Wire gauges: mm² cross-section strings.

---

## When to use

Reach for this module when the user asks about:

- routing a wiring harness or cable run in 3D between two or more connectors
- computing harness bundle outer diameter from wire counts and gauges
- checking bend-radius constraints for a harness path
- detecting whether a harness path hits a structural obstacle
- modelling T-split or multi-branch harness topologies
- generating a wire-length bill of materials per gauge for procurement
- estimating total wire length for a harness assembly

---

## Tools

### `harness_route`

Route a harness trunk in 3D through two or more connector endpoints with optional
guide (via) points and optional T-split branches. Uses centripetal Catmull-Rom
spline smoothing. Checks bend-radius (flags if min bend < 10× bundle OD) and
obstacle AABB intersection. Returns total path length, bundle OD, per-segment
details, and branch breakdown. `ok:false` when bend or obstacle violations occur
(violations reported in `reason`, not raised).

### `harness_bundle_diameter`

Compute the outer diameter (mm and m) of a harness bundle from wire-spec list
`[{gauge, count}]`. Method: sum insulated cross-section areas, divide by
hexagonal fill factor (0.78), compute equivalent circular diameter. Returns
`bundle_od_mm`, total wire count, and parsed wire specs.

### `harness_bom`

Generate a wire-length bill of materials from a routed harness result (output of
`harness_route`). For each segment in each branch, lists gauge, count, segment
name, branch id, segment length, and total wire length (count × length). Returns
`totals_by_gauge` (total metres per gauge across all segments) and
`grand_total_wire_length_m` for procurement.

---

## Example

**User ask:** "Route a harness from connector A at (0,0,0) to connector B at
(2.5,1.0,0.3) via a guide at (1.2,0.5,0.1), carrying 4 × 1.0 mm² and
2 × 2.5 mm² wires. Check bend radius and give me the BOM."

```
1. harness_bundle_diameter
     wire_specs:[{gauge:"1.0",count:4},{gauge:"2.5",count:2}]
   → bundle_od_mm:12.4

2. harness_route
     endpoints:[{x:0,y:0,z:0},{x:2.5,y:1.0,z:0.3}]
     guides:[{x:1.2,y:0.5,z:0.1}]
     wire_specs:[{gauge:"1.0",count:4},{gauge:"2.5",count:2}]
   → {ok:true, total_length_m:2.91, bundle_od_mm:12.4, …}

3. harness_bom
     harness:{from step 2}
   → {totals_by_gauge:{"1.0":11.64,"2.5":5.82},
      grand_total_wire_length_m:17.46}
```

---

## Notes

- All tools are **pure-Python**; no OCC dependency.
- Bend-radius rule: minimum bend radius must be ≥ 10× bundle OD.
- Obstacle detection is AABB-based (axis-aligned bounding boxes in metres).
- `harness_route` returns `ok:false` for violations but still returns path data
  in the response — the violation is in `reason`.
- Gauges are mm² cross-section strings (e.g. `"0.5"`, `"1.0"`, `"2.5"`, `"4.0"`).
