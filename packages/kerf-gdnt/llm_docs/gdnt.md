# kerf-gdnt · GD&T / PMI Model-Based Definition

Geometric Dimensioning & Tolerancing (GD&T) and Product & Manufacturing Information (PMI) tooling per **ISO 1101:2017** and **ASME Y14.5-2018**.  Pure Python — no heavy optional dependencies.

---

## When to use

- Annotate a CAD model with precise geometric tolerance callouts (Feature Control Frames)
- Check CMM or gauge measurements against tolerance specifications (pass/fail oracle)
- Generate a homologation-style First Article Inspection (FAI) report / quality dossier
- Look up symbol codes, Unicode characters, and ISO/ASME clause references

---

## Symbol codes

| Code | Unicode | Name | Category | ISO 1101 | ASME Y14.5 |
|------|---------|------|----------|----------|------------|
| `straightness` | ⎯ | Straightness | form | §17.2 | §12.4 |
| `flatness` | ▱ | Flatness | form | §17.3 | §12.5 |
| `circularity` | ○ | Circularity (Roundness) | form | §17.4 | §12.6 |
| `cylindricity` | ⌭ | Cylindricity | form | §17.5 | §12.7 |
| `profile_line` | ⌒ | Profile of a Line | profile | §17.6 | §11.5 |
| `profile_surface` | ⌓ | Profile of a Surface | profile | §17.7 | §11.6 |
| `angularity` | ∠ | Angularity | orientation | §17.8 | §10.4 |
| `perpendicularity` | ⟂ | Perpendicularity | orientation | §17.9 | §10.5 |
| `parallelism` | ⼏ | Parallelism | orientation | §17.10 | §10.6 |
| `position` | ⌖ | Position | location | §17.11 | §9.4 |
| `concentricity` | ◎ | Concentricity / Coaxiality | location | §17.13 | §9.9 |
| `symmetry` | ⌯ | Symmetry | location | §17.14 | §9.10 |
| `circular_runout` | ↗ | Circular Runout | runout | §17.15 | §13.4 |
| `total_runout` | ⇈ | Total Runout | runout | §17.16 | §13.5 |

### Modifier codes

| Code | Unicode | Meaning |
|------|---------|---------|
| `M` | Ⓜ | Maximum Material Condition (MMC) |
| `L` | Ⓛ | Least Material Condition (LMC) |
| `S` | Ⓢ | Regardless of Feature Size (RFS) |
| `F` | Ⓕ | Free State |
| `P` | Ⓟ | Projected Tolerance Zone |
| `T` | Ⓣ | Tangent Plane |
| `dia` | ⌀ | Diameter prefix for cylindrical zones |

---

## Public tools

### `gdnt_list_symbols`

List all supported GD&T symbol codes with Unicode characters, names, categories, and ISO/ASME references.

**Parameters** (all optional):
- `category` — filter by `"form"`, `"orientation"`, `"location"`, `"runout"`, `"profile"`, or `"all"` (default)

**Returns:** `{ symbols: [...], modifiers: [...] }`

---

### `gdnt_create_fcf`

Create a Feature Control Frame.

**Parameters:**
- `symbol_code` *(required)* — e.g. `"position"`, `"flatness"`
- `tolerance_value` *(required)* — numeric tolerance in drawing units
- `diameter_zone` — `true` for cylindrical tolerance zones (prefix ⌀)
- `tolerance_modifier` — `"M"`, `"L"`, `"S"`, `"F"`, `"P"`, or `"T"`
- `datum_refs` — list of `{ label, modifier? }` (max 3, primary → secondary → tertiary)
- `note` — optional annotation

**Returns:** FCF dict including `rendered` (the canonical Unicode form, e.g. `⏐⌖⏐∅0.5 Ⓜ ⏐A⏐B⏐C⏐`)

```json
{
  "symbol_code": "position",
  "tolerance_value": 0.5,
  "diameter_zone": true,
  "tolerance_modifier": "M",
  "datum_refs": [
    {"label": "A"},
    {"label": "B"},
    {"label": "C"}
  ]
}
```

---

### `gdnt_validate_fcf`

Validate an FCF dict.

**Parameters:**
- `fcf` *(required)* — FCF dict from `gdnt_create_fcf`

**Returns:** `{ valid: bool, issues: [string] }`

---

### `gdnt_inspect_feature`

Check a single CMM / gauge measurement against a tolerance specification.

**Parameters:**
- `feature_id` *(required)* — label, e.g. `"F1"`, `"bore_A"`
- `fcf` *(required)* — FCF dict
- `nominal` *(required)* — design (nominal) value
- `measured` *(required)* — actual measured value
- `unilateral` — `true` for unilateral zone `[nominal, nominal+tol]`; default bilateral `±tol/2`

**Returns:** `{ feature_id, status: "PASS"|"FAIL", deviation, tolerance_value, ... }`

Pass/fail rule:
- Bilateral (default): `|measured − nominal| ≤ tol/2` → PASS
- Unilateral: `0 ≤ measured − nominal ≤ tol` → PASS

---

### `gdnt_build_report`

Build a full homologation-style inspection report.

**Parameters:**
- `part_number` *(required)* — drawing part number
- `measurements` *(required)* — list of `{ feature_id, fcf, nominal, measured, unilateral? }`
- `revision` — drawing revision (default `"A"`)
- `inspector` — inspector name / ID
- `inspection_date` — ISO 8601 date string
- `units` — unit label for display (default `"mm"`)

**Returns:** `{ markdown: string, rows: [...], summary: { total, passed, failed, overall_pass } }`

The `markdown` field is a complete First Article Inspection (FAI) / homologation sheet ready for inclusion in a quality dossier.

---

## Python API

```python
from kerf_gdnt.symbols import get_symbol, POSITION, MODIFIER_MMC
from kerf_gdnt.feature_control_frame import DatumReference, FeatureControlFrame
from kerf_gdnt.datums import make_3_2_1_frame
from kerf_gdnt.inspection_report import build_report, render_report

# Build an FCF: ⏐⌖⏐∅0.5 Ⓜ ⏐A⏐B⏐C⏐
fcf = FeatureControlFrame(
    symbol_code="position",
    tolerance_value=0.5,
    diameter_zone=True,
    tolerance_modifier="M",
    datum_refs=[
        DatumReference("A"),
        DatumReference("B"),
        DatumReference("C"),
    ],
)
print(fcf.render())
# → ⏐⌖⏐⌀0.5 Ⓜ ⏐A⏐B⏐C⏐

# Inspect a measurement
from kerf_gdnt.inspection_report import InspectionRow
row = InspectionRow(feature_id="bore_1", fcf=fcf, nominal=0.0, measured=0.2)
print(row.status)    # PASS  (0.2 < 0.5/2 = 0.25)
print(row.deviation) # 0.2

# Build a full report
report = build_report(
    part_number="PN-1234",
    measurements=[
        {"feature_id": "F1", "fcf": fcf, "nominal": 0.0, "measured": 0.1},
        {"feature_id": "F2", "fcf": fcf, "nominal": 0.0, "measured": 0.3},  # FAIL
    ],
    revision="C",
    inspector="CMM-01",
)
print(render_report(report))
```

---

## Datum Reference Frames

A Datum Reference Frame (DRF) establishes the coordinate system for measurement per **ISO 5459:2011** and **ASME Y14.5-2018 §4**.

```python
from kerf_gdnt.datums import make_3_2_1_frame

drf = make_3_2_1_frame("A", "B", "C")
print(drf)
# → DRF [A | B | C] — fully constrained

print(drf.is_fully_constrained)  # True
print(drf.total_dof_constrained) # 6
```

Classic 3-2-1 setup:
- **Primary** (datum A) — surface plate contact → 3 DOF (tz, rx, ry)
- **Secondary** (datum B) — parallel stop → 2 DOF (ty, rz)
- **Tertiary** (datum C) — side stop → 1 DOF (tx)

---

## Tolerance zone geometry

| Symbol | Zone type | Note |
|--------|-----------|------|
| flatness | Two parallel planes | Bilateral by default |
| straightness | Two parallel lines / cylinder | Can be cylindrical with ⌀ prefix |
| circularity | Annular zone between two coaxial circles | |
| cylindricity | Annular zone between two coaxial cylinders | |
| position | Sphere / cylinder / two parallel planes | Use `diameter_zone=True` for cylindrical |
| perpendicularity | Two parallel planes / cylinder | Relative to datum |
| parallelism | Two parallel planes | Relative to datum |
| circular_runout | Circular band | Measured during one revolution |
| total_runout | Cylindrical band | Measured across entire surface |

---

## References

- ISO 1101:2017 — *Geometrical product specifications (GPS) — Geometrical tolerancing — Tolerances of form, orientation, location and run-out*
- ISO 5459:2011 — *GPS — Geometrical tolerancing — Datums and datum systems*
- ISO 2692:2014 — *GPS — Maximum material requirement (MMR), least material requirement (LMR) and reciprocity requirement (RPR)*
- ASME Y14.5-2018 — *Dimensioning and Tolerancing*
