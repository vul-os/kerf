# GD&T — Geometric Dimensioning and Tolerancing

Pure-Python ASME Y14.5 / ISO 1101 datum + tolerance framework. No 3D rendering
required; this is the data model, validation, and callout report layer. Drawing
view rendering is downstream.

---

## Tools

### `gdt_apply_datum`

Define or update a datum (letter + type + optional feature reference).

**Input:**
- `label` (required) — datum letter, e.g. `"A"`, `"B"`, `"C"`, or compound `"A-B"`
- `datum_type` — one of `PLANE` | `AXIS` | `CENTRE_PLANE` | `POINT` | `LINE`  
  Default: `PLANE`
- `feature_ref` (optional) — face name / surface id / feature-tree node id
- `description` (optional) — human note
- `is_compound` (optional, bool) — `true` for co-datum references

**Output:** `{datum: {...}, message: "..."}`

**Use AXIS for:** cylinder/cone centrelines (needed for POSITION, RUNOUT,
TOTAL_RUNOUT, CONCENTRICITY).  
**Use CENTRE_PLANE for:** slot / tab centreplanes (needed for SYMMETRY).

---

### `gdt_apply_tolerance`

Attach a geometric tolerance (feature control frame) to a named feature.

**Input:**
- `feature_name` (required) — name / id of the toleranced feature
- `symbol` (required) — one of the 14 GD&T characteristics (see below)
- `tolerance_value` (required) — zone width/diameter in mm (> 0)
- `diameter_zone` (bool) — `true` for cylindrical zone (⌀ prefix)
- `datum_ref` — `{primary, secondary, tertiary}` datum labels
- `modifiers` — list from: `MMC`, `LMC`, `RFS`, `PROJECTED`, `TANGENT`,
  `FREE_STATE`, `STATISTICAL`, `CONTINUOUS_FEATURE`, `INDEPENDENCY`,
  `UNEQUAL_BILATERAL`
- `is_feature_of_size` (bool) — required `true` when using MMC or LMC
- `projected_zone_height` — required when `PROJECTED` modifier is set (mm)
- `note` (optional) — annotation

**Output:** `{tolerance: {...}, message: "..."}`

**Symbol reference:**

| Category    | Symbols |
|-------------|---------|
| Form        | `FLATNESS`, `STRAIGHTNESS`, `CIRCULARITY`, `CYLINDRICITY` |
| Profile     | `PROFILE_LINE`, `PROFILE_SURFACE` |
| Orientation | `PARALLELISM`, `PERPENDICULARITY`, `ANGULARITY` |
| Location    | `POSITION`, `CONCENTRICITY`, `SYMMETRY` |
| Runout      | `RUNOUT`, `TOTAL_RUNOUT` |

---

### `gdt_validate_scheme`

Validate a complete datum + tolerance set against Y14.5 rules.

**Input:**
- `datums` — list of datum dicts (from `gdt_apply_datum` output)
- `tolerances` (required) — list of tolerance dicts

**Output:** `{ok: bool, errors: [string...]}`  
Never raises on bad input.

**Rules enforced:**
- `POSITION` requires ≥ 1 datum reference
- `CONCENTRICITY` / `SYMMETRY` require an `AXIS` or `CENTRE_PLANE` datum
- `MMC` / `LMC` modifiers require `is_feature_of_size == true`
- `RUNOUT` / `TOTAL_RUNOUT` require exactly 1 datum of type `AXIS`
- `PROJECTED` modifier requires `projected_zone_height > 0`
- Datum reference frame: tertiary requires secondary; secondary requires primary

---

### `gdt_callout_report`

Render a formatted GD&T callout report from a list of tolerance dicts.

**Input:**
- `features` (required) — list of tolerance dicts

**Output:**
```json
{
  "callouts":    ["[⊕ | ⌀0.05 (M) | A | B | C]  ← bore-top", ...],
  "summary":     [{...tolerance dict...}, ...],
  "count":       3,
  "by_category": {"form": 1, "location": 1, "orientation": 1},
  "text":        "GD&T Callout Report\n...",
  "parse_errors": []
}
```

---

## Typical workflow

```
1. gdt_apply_datum   label:"A"  datum_type:"PLANE"   feature_ref:"bottom-face"
2. gdt_apply_datum   label:"B"  datum_type:"AXIS"    feature_ref:"bore-primary"
3. gdt_apply_datum   label:"C"  datum_type:"PLANE"   feature_ref:"back-face"

4. gdt_apply_tolerance  feature_name:"bottom-face"
                        symbol:"FLATNESS"  tolerance_value:0.025

5. gdt_apply_tolerance  feature_name:"bore-top"
                        symbol:"POSITION"  tolerance_value:0.05
                        diameter_zone:true
                        datum_ref:{primary:"A", secondary:"B", tertiary:"C"}
                        modifiers:["MMC"]  is_feature_of_size:true

6. gdt_validate_scheme  datums:[...A, B, C...]  tolerances:[...flatness, position...]
   → {ok: true, errors: []}

7. gdt_callout_report  features:[...flatness, position...]
   → formatted callout list for drawing or inspection report
```

---

## Notes

- All tools are **pure-Python**; no OCC dependency.
- `gdt_apply_datum` / `gdt_apply_tolerance` are **stateless** — they validate
  and return the dict; storage is the caller's responsibility (accumulate in
  session, pass to validate/report).
- Form tolerances (`FLATNESS`, `STRAIGHTNESS`, `CIRCULARITY`, `CYLINDRICITY`)
  do not require datum references.
- Orientation tolerances (`PARALLELISM`, `PERPENDICULARITY`, `ANGULARITY`)
  and Profile tolerances can optionally reference datums.
- Drawing view rendering of feature control frames is downstream (not in this
  module).
