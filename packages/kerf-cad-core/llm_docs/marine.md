# Marine Hull Design and Hydrostatics

Pure-Python marine hull module: build a parametric NURBS-loft recipe from a
half-breadth offset table, check hull fairing quality, and compute basic
hydrostatic properties. No OCC dependency — the recipe drives a downstream
NURBS worker. Units: **metres** (m) and **m²/m³** throughout.

---

## When to use

Reach for this module when the user asks about:

- building a hull surface from a table of offsets (traditional lines plan)
- checking hull fairness, curvature monotonicity, or batten bending energy
- computing waterplane area, displaced volume, or LCB for a hull
- naval architecture preliminary design: LOA, max beam, depth, draft
- evaluating whether a hull form is fair (smooth, free of kinks)
- hydrostatic analysis at a given design waterline / draft
- converting a traditional offsets table into a parametric hull model

---

## Tools

### `marine_hull_from_offsets`

Build a parametric NURBS-loft hull recipe from a half-breadth offset table. Input
is a list of `{station, waterline, half_breadth}` rows (metres). Returns the loft
recipe (`op:"marine_loft_hull"`), principal dimensions (LOA, max half-beam, depth,
station count, waterline count), and knot parameters. Pass the recipe to a
downstream NURBS worker to produce the actual surface.

### `marine_fairing_report`

Compute hull fairing quality metrics from the same offset table. Reports three
metrics: (1) curvature monotonicity per station (flags kinks / inflection points),
(2) batten bending energy per station (natural cubic spline approximation — lower
= fairer), and (3) longitudinal roughness per waterline (RMS of second finite
differences). Also reports `overall_roughness` (mean of per-WL RMS values).

### `marine_hydrostatics`

Compute basic hydrostatic properties from the offset table using composite
Simpson's 1/3 rule. Returns `waterplane_area_m2` (Awp), `displaced_volume_m3`
(∇), and `lcb_from_bow_m` (LCB measured from the first station). Accepts an
optional `design_waterline` (draft in metres); defaults to the maximum waterline
in the table.

---

## Example

**User ask:** "I have a small powerboat offset table with 5 stations and 4
waterlines. What is the displaced volume at 0.6 m draft, and is the hull fair?"

```
1. marine_hull_from_offsets
     offsets:[{station:0,waterline:0,half_breadth:0},
              {station:0,waterline:0.3,half_breadth:0.4},
              …]
   → {loa:5.0, max_half_beam:1.2, depth:0.9, op:"marine_loft_hull", …}

2. marine_fairing_report
     offsets:[same table]
   → {curvature_monotonicity:[…], batten_energy:[…],
      roughness_per_waterline:[…], overall_roughness:0.003}

3. marine_hydrostatics
     offsets:[same table]  design_waterline:0.6
   → {waterplane_area_m2:4.8, displaced_volume_m3:1.44, lcb_from_bow_m:2.1}
```

---

## Notes

- All tools are **pure-Python**; no OCC dependency.
- Minimum 3 offset rows; at least 2 distinct stations and 2 distinct waterlines.
- Duplicate `(station, waterline)` pairs are rejected.
- Hydrostatics uses Simpson's 1/3 rule — exact for polynomials up to degree 3.
- Fairing metrics are diagnostic; interpretation requires naval architect judgement.
- Invalid inputs return `{ok: false, errors: [...]}` — never raise.
