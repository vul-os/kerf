# Structural Grid + Levels + Framing

Pure-Python parametric layer for civil/structural building layout.
No OCC required. Units: **mm** (lengths, elevations), **kg** (mass), **t** (tonnes).

Session state (grid, levels, members) is passed in/out as plain dicts — no DB
writes. Accumulate state across tool calls in the session.

---

## Steel Section Catalog

Built-in catalog of 12 common structural steel sections with nominal
cross-section properties. Values are **factual nominal constants** from
publicly available engineering standards — not copied from any proprietary
software database or licensed table.

Sources cited: EN 10034 (IPE), EN 53-62 (HEA), BS 4-1 (UB), AISC Steel
Construction Manual (W). All values are the standard nominal/tabulated figures
reproduced in engineering references worldwide.

| Section           | Family | A (mm²) | Ix (mm⁴)  | Iy (mm⁴)  | kg/m  |
|-------------------|--------|---------|-----------|-----------|-------|
| IPE160            | IPE    | 2 009   | 8.69e6    | 0.683e6   | 12.7  |
| IPE200            | IPE    | 2 848   | 19.43e6   | 1.424e6   | 22.4  |
| IPE270            | IPE    | 4 594   | 57.9e6    | 4.20e6    | 36.1  |
| IPE360            | IPE    | 7 273   | 162.7e6   | 10.43e6   | 57.1  |
| HEA200            | HEA    | 5 383   | 36.92e6   | 13.36e6   | 42.3  |
| HEA300            | HEA    | 11 250  | 182.6e6   | 63.1e6    | 88.3  |
| HEA400            | HEA    | 15 900  | 450.1e6   | 155.8e6   | 124.8 |
| UB203x133x25      | UB     | 3 230   | 28.5e6    | 3.56e6    | 25.1  |
| UB356x171x51      | UB     | 6 490   | 141.1e6   | 12.06e6   | 51.0  |
| W8x31             | W      | 5 880   | 86.9e6    | 18.4e6    | 46.1  |
| W12x50            | W      | 9 480   | 286.6e6   | 52.5e6    | 74.3  |
| W14x68            | W      | 12 900  | 576.5e6   | 125.0e6   | 101.2 |

---

## Tools

### `struct_grid`

Define the structural grid. Returns a `grid` dict to pass to column/beam tools.

**Input:**
- `spacing_x` (required) — list of X bay widths in mm, e.g. `[6000, 8000, 6000]`
  → axes A, B, C, D at x = 0, 6000, 14000, 20000
- `spacing_y` (required) — list of Y bay depths in mm, e.g. `[5000, 5000]`
  → axes 1, 2, 3 at y = 0, 5000, 10000
- `name` (optional) — grid set name

**Output:** `{ok: true, grid: {...}, intersections: N, message: "..."}`

Grid intersections are addressed as `"X/Y"` where X is a letter (A, B, …)
and Y is a number (1, 2, …). Example: `"B/3"`.

---

### `struct_level`

Define a floor/storey level at a fixed elevation.

**Input:**
- `name` (required) — level name, e.g. `"Ground"`, `"L1"`, `"Roof"`
- `elevation_mm` (required) — elevation above project datum (mm); 0 = ground; negative = basement

**Output:** `{ok: true, level: {name, elevation_mm}, message: "..."}`

Accumulate levels into a `levels` dict: `{level_name: level_dict, …}`.

---

### `struct_column`

Place a column at a grid intersection spanning base level → top level.

**Input:**
- `id` (required) — unique identifier, e.g. `"C-B3-G-L1"`
- `grid_label` (required) — grid intersection, e.g. `"B/3"`
- `section` (required) — section name from catalog (see table above)
- `base_level` (required) — name of base level (key in `levels` dict)
- `top_level` (required) — name of top level (key in `levels` dict)
- `grid` (required) — dict from `struct_grid` output
- `levels` (required) — dict of level dicts accumulated from `struct_level`

**Output:** `{ok: true, column: {id, type, grid_label, x_mm, y_mm, section, base_level, top_level, base_elevation_mm, top_elevation_mm, length_mm, mass_kg}, message: "..."}`

Column length = |top_elevation − base_elevation| (mm).
Column mass = length_m × section kg/m.

**Error:** column at undefined grid label → `{ok: false, errors: [...]}`.
Base and top level at same elevation → error.

---

### `struct_beam`

Add a beam spanning between two grid intersections at a given level.

**Input:**
- `id` (required) — unique identifier, e.g. `"B-A2-C2-L1"`
- `start` (required) — start grid label, e.g. `"A/2"`
- `end` (required) — end grid label, e.g. `"C/2"`
- `section` (required) — section name from catalog
- `level` (required) — name of the level at which the beam sits
- `grid` (required) — dict from `struct_grid`
- `levels` (required) — dict of level dicts

**Output:** `{ok: true, beam: {id, type, start_label, end_label, start_x_mm, start_y_mm, end_x_mm, end_y_mm, section, level, elevation_mm, length_mm, mass_kg}, message: "..."}`

Beam length = Euclidean distance between start and end grid points (XY plane, mm).
Zero-length beam (same start and end) → `{ok: false, errors: [...]}`.

---

### `struct_framing_summary`

BOM-style summary of all framing members: count + total steel tonnage by section.

**Input:**
- `members` (required) — list of member dicts (column/beam dicts from the outputs above)

**Output:**
```json
{
  "ok": true,
  "total_members": 24,
  "total_mass_kg": 18450.3,
  "total_mass_t": 18.450,
  "by_section": [
    {"section": "HEA200", "family": "HEA", "count": 12, "total_length_mm": 48000, "total_mass_kg": 2030.4},
    ...
  ],
  "by_type": {
    "columns": {"count": 12, "mass_kg": 8200.0},
    "beams":   {"count": 12, "mass_kg": 10250.3}
  },
  "errors": []
}
```

Total steel mass = Σ(member length_m × section kg/m) for all members.

---

## Typical workflow

```
1. struct_grid  spacing_x:[6000,8000,6000]  spacing_y:[5000,5000]
   → grid dict

2. struct_level  name:"Ground"   elevation_mm:0
   struct_level  name:"L1"       elevation_mm:4000
   struct_level  name:"L2"       elevation_mm:8000
   struct_level  name:"Roof"     elevation_mm:12000
   → levels dict = {Ground:{…}, L1:{…}, L2:{…}, Roof:{…}}

3. struct_column  id:"C-B2-G-L1"  grid_label:"B/2"  section:"HEA200"
                  base_level:"Ground"  top_level:"L1"  grid:{…}  levels:{…}
   → column dict

4. struct_beam    id:"BM-A1-C1-L1"  start:"A/1"  end:"C/1"  section:"IPE270"
                  level:"L1"  grid:{…}  levels:{…}
   → beam dict

5. struct_framing_summary  members:[col.column, beam.beam, …]
   → {total_mass_t: 18.45, by_section: […], …}
```

---

## Notes

- All tools are **pure-Python**; no OCC dependency.
- Tools are **stateless** — they return dicts; accumulate state in the session.
- Invalid inputs return `{ok: false, errors: [...]}` — never raise.
- Section catalog values are **nominal published constants**, not proprietary data.
- Maximum 26 X-axes (A–Z) per grid.
- Beam length is measured in the XY plane (horizontal distance); elevation
  difference is not included (beams are defined as horizontal members).
