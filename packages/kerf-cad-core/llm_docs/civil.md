# Civil Site Grading and Earthwork

Pure-Python site grading layer: build a TIN from survey points, define a design
platform, compute cut/fill earthwork volumes, and format a grading report.
No OCC required. Units: **metres** (m), **cubic metres** (m³).

---

## When to use

Reach for this module when the user asks about:

- building a terrain model from survey data (DTM, TIN, point cloud of elevations)
- defining a building pad, roadway platform, or graded area at a target elevation
- computing cut and fill volumes for site earthwork or grading
- checking whether earthwork is balanced (cut surplus vs fill deficit)
- generating a grading summary or earthwork report for a project
- evaluating side slopes for pad grading (e.g. 2H:1V benching)

---

## Tools

### `civil_terrain`

Build a Triangulated Irregular Network (TIN) from survey points `{x, y, z}` in
metres. Returns point count, triangle count, plan area (m²), and elevation
statistics. Use this first; pass the same points to `civil_earthwork`.

### `civil_pad`

Define a proposed design platform: a polygon boundary with a target pad elevation
and optional side-slope ratio (1V:nH) or tilt gradients (dz_dx, dz_dy). Returns
a `design_surface_json` ready to pass directly to `civil_earthwork`.

### `civil_earthwork`

Compute cut/fill volumes between an existing ground TIN and a design surface by
grid-sampling (default 1 m spacing). Returns cut_m3, fill_m3, net_m3,
balance_ratio (cut/fill ≈ 1 = balanced), and sample count. Grid spacing is
adjustable for accuracy vs speed.

### `civil_grading_report`

Format a human-readable earthwork balance report from `civil_earthwork` output.
Accepts optional project name and site description. Returns formatted report text
and a list of summary lines.

---

## Example

**User ask:** "I have survey data for a 50 × 50 m site. I want to cut it to a flat
pad at 102.5 m elevation. How much cut and fill will there be?"

```
1. civil_terrain  points:[{x:0,y:0,z:103.1}, {x:50,y:0,z:102.0}, …]
   → area_m2, elevation stats

2. civil_pad  polygon:[[0,0],[50,0],[50,50],[0,50]]
              pad_elevation:102.5  side_slope_ratio:2.0
   → design_surface_json

3. civil_earthwork  tin_points:[same survey points]
                    design_surface:{from step 2}  grid_spacing_m:1.0
   → {cut_m3:1250.0, fill_m3:380.0, net_m3:-870.0, balance_ratio:3.29}

4. civil_grading_report  earthwork:{from step 3}
                         project_name:"Site A"
   → formatted report text
```

---

## Notes

- All tools are **pure-Python**; no OCC dependency.
- Tools are **stateless** — pass outputs from one tool to the next.
- Invalid inputs return `{ok: false, errors: [...]}` — never raise.
- TIN uses a fan triangulation (deterministic, hub = lexicographically first point).
- Earthwork volumes use grid sampling; smaller `grid_spacing_m` increases accuracy.
- `balance_ratio` = cut / fill; ∞ when fill = 0 (all cut site).
