# Jewelry CAD QC — `jewelry/cad_qc.py`

Pre-production quality checks for jewelry CAD models before casting, DMLS, or resin printing.

---

## Process targets

| Process | Key checks |
|---------|-----------|
| `cast` | Wall thickness ≥ min, undercut draft, sharp inside corners, spruing clearance |
| `dmls` | Overhang angle, support-land geometry, min feature size, powder trap cavities |
| `resin_print` | Minimum wall for resin cure, hollow with drain holes, support geometry |

---

## Public API

### `qc_check(body_dict, process, *, min_wall_mm=None, min_feature_mm=None, draft_deg=None) → dict`

`body_dict` must contain `"volume_mm3"`, `"surface_area_mm2"`, `"bounding_box"` (as `{x,y,z}` mm), and optionally `"wall_samples"` (list of local thickness values in mm).

Process defaults for `min_wall_mm`: cast → 0.8 mm, dmls → 0.4 mm, resin_print → 0.5 mm.

Returns:
```json
{
  "process": "cast",
  "pass": false,
  "checks": [
    {"check": "min_wall_thickness", "ok": false,
     "min_found_mm": 0.62, "required_mm": 0.8,
     "locations": ["near_prong_base"]},
    {"check": "undercut_draft",    "ok": true},
    {"check": "sharp_inside_corners", "ok": true},
    {"check": "water_tight",       "ok": true}
  ],
  "critical_failures": ["min_wall_thickness"],
  "warnings": [],
  "summary": "FAIL — 1 critical issue"
}
```

### `qc_report_text(qc_result) → str`

Human-readable plain-text report from a `qc_check` result dict.

---

## Usage

```python
from kerf_cad_core.jewelry.cad_qc import qc_check, qc_report_text

body = {
    "volume_mm3": 1200,
    "surface_area_mm2": 840,
    "bounding_box": {"x": 22, "y": 18, "z": 8},
    "wall_samples": [0.62, 0.85, 1.1, 0.9, 0.78],
}
result = qc_check(body, process="cast", min_wall_mm=0.8)
print(qc_report_text(result))
```

---

## Notes

- Wall samples are user-supplied or can be derived from a solid model thickness analysis.
- `dmls` checks for powder trap cavities require a `"hollow": bool` field in `body_dict`.
- Resin print checks assume a full-cure SLA/DLP process; FDM has different minimum-feature constraints.
