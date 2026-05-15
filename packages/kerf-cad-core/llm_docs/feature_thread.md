# Thread & Tapped-Hole Feature

Pure-Python ISO metric / UTS thread-spec catalog plus three LLM tools.
Thread dimensions are standard nominal constants from ISO 261/965-1 and
ASME B1.1-2003. No OCC required at tool-call time; nodes are evaluated by
the OCCT worker at render time.

---

## Thread dimension standards

| Standard | Scope |
|----------|-------|
| ISO 261:2013 | Metric thread series selection (M1.6 – M64 coarse + fine) |
| ISO 965-1:1998 | Metric thread tolerances; default class 6H/6g |
| ASME B1.1-2003 | Unified inch threads (UNC/UNF); default class 2B/2A |

`tap_drill = major_dia − pitch` (75% engagement approximation, ISO 228 / ASME B1.1 App.).

---

## Tools

### `feature_tapped_hole`

Append a `tapped_hole` node to a `.feature` file.

**Key inputs:**
- `file_id` (required) — UUID of the `.feature` file
- `designation` (required) — e.g. `"M6"`, `"M6x0.75"`, `"1/4-20 UNC"`, `"#10-24 UNC"`
- `depth` (required) — total hole depth in mm
- `hole_type` — `"through"` (default) or `"blind"`
- `thread_depth` — required for blind; must be ≤ depth
- `target_id` — optional body node id
- `counterbore_dia` / `counterbore_depth` — optional, both required together; counterbore_dia > major_dia
- `countersink_dia` / `countersink_angle_deg` — optional entry countersink (default 90°, range [30, 150])
- `cosmetic_thread` — bool, default `true`

**Output (ok):**
```json
{
  "file_id": "...",
  "id": "tapped_hole-1",
  "op": "tapped_hole",
  "designation": "M6",
  "tap_drill_dia": 5.0,
  "pitch_mm": 1.0,
  "major_dia_mm": 6.0,
  "minor_dia_mm": 4.773,
  "hole_type": "through"
}
```

Node emitted to the `.feature` file includes: `tap_drill_dia`, `pitch_mm`,
`major_dia_mm`, `minor_dia_mm`, `thread_class`, `cosmetic_thread`, and for
UTS threads the `_in` equivalents.

---

### `feature_thread_external`

Validate and return parameters for an external thread on a shaft.
**Does not** append a feature node — combine with `cut`/`revolve` as needed.

**Key inputs:**
- `shaft_dia` (required) — shaft nominal outer diameter in mm
- `designation` (required) — thread designation
- `length` (required) — thread length in mm
- `thread_class` — optional override (default `"6g"` metric / `"2A"` UTS)

**Constraints:**
- `shaft_dia` must match the designation's major diameter within ±0.3 mm.
  Returns `{error: "...", code: "MISMATCH"}` when out of range.

**Output (ok):**
```json
{
  "designation": "M6",
  "shaft_dia_mm": 6.0,
  "major_dia_mm": 6.0,
  "minor_dia_mm": 4.773,
  "pitch_mm": 1.0,
  "thread_class": "6g",
  "length_mm": 20.0,
  "cosmetic_thread": true,
  "system": "metric"
}
```

---

### `thread_lookup`

Pure catalog query. Returns the full thread spec dict or an error.

**Input:** `designation` string

**Output (found):**
```json
{
  "ok": true,
  "spec": {
    "designation": "M6",
    "standard": "ISO metric",
    "system": "metric",
    "major_dia_mm": 6.0,
    "pitch_mm": 1.0,
    "minor_dia_mm": 4.773,
    "tap_drill_mm": 5.0,
    "thread_class": "6H/6g",
    "series": "coarse"
  }
}
```

**Output (not found):**
```json
{"ok": false, "errors": ["Unknown or unsupported designation: 'M99'. ..."]}
```

---

## Accepted designation forms

| Form | Example | Notes |
|------|---------|-------|
| ISO metric coarse | `M6`, `M10`, `M24` | pitch is standard coarse for that size |
| ISO metric fine | `M6x0.75`, `M10x1.25` | explicit pitch after `x` |
| UTS numbered | `#10-24 UNC`, `#6-32 UNC` | `#N-TPI SERIES` |
| UTS fractional | `1/4-20 UNC`, `3/8-16 UNC` | `FRAC-TPI SERIES` |

Series suffix is case-insensitive (`unc` / `UNC`). Unknown designations
return `{ok: false, errors: [...]}` — never raise.

---

## Typical workflow

```
1. thread_lookup  designation:"M6"
   → confirm tap_drill_mm = 5.0, pitch_mm = 1.0

2. feature_tapped_hole
     file_id:"<uuid>"
     designation:"M6"
     depth:20
     hole_type:"blind"
     thread_depth:15
   → appends tapped_hole-1 node; OCCT cuts ⌀5 × 20 mm blind bore,
     cosmetic thread annotation to 15 mm depth

3. feature_thread_external
     shaft_dia:6.0  designation:"M6"  length:18
   → validates match, returns thread params for downstream annotation
```

---

## Notes

- All output lengths in mm; UTS tools also include `_in` fields.
- `tap_drill_mm` is the recommended drill size for ~75% thread engagement.
- `cosmetic_thread` is always `true` in v1; solid helical thread modelling
  is reserved for a future high-fidelity render path.
- No OCC import; pure Python.
