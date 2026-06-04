# Dental AI Template Matching

> Automatically design a crown from a scan by matching against a tooth-morphology template library.

**Module**: `packages/kerf-dental/src/kerf_dental/dental_ai_automation.py`
**Shipped**: Wave 10
**LLM tools**: `dental_crown_bridge_design`

---

## What it is

The AI template module compares a segmented tooth preparation mesh against a library of reference tooth templates using Hu moment descriptors projected onto the occlusal plane. The best-matching template is warped to fit the preparation margin and patient arch, producing a fully-designed crown mesh without manual morphology specification.

## How to use it

### From chat

> "Auto-design a crown for tooth 26 from my intraoral scan — use the template library."

### From Python

```python
from kerf_dental.dental_ai_automation import (
    match_tooth_template, auto_design_crown_from_scan,
)

# Match template for an upper first molar
match = match_tooth_template(
    scan_verts=prep_verts,
    scan_faces=prep_faces,
    tooth_number="26",
    top_k=3,
)
print(match.best_template.name, match.similarity_score)

# End-to-end auto design
crown = auto_design_crown_from_scan(
    scan_verts=prep_verts,
    scan_faces=prep_faces,
    tooth_number="26",
    material="zirconia",
)
```

### From an LLM tool spec

```json
{"tool": "dental_crown_bridge_design", "input": {"tooth_number": "26", "material": "zirconia", "scan_available": true}}
```

## How it works

Preparations are projected onto the occlusal plane and 2-D Hu invariant moments (7 values) are computed from the contour. These are compared against the same moments for each template in the library using Euclidean distance. The top-k templates are warped using thin-plate spline interpolation to align their margin curves to the preparation margin. The warped template with lowest RMS margin deviation is returned as the final design.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `match_tooth_template(scan_verts, scan_faces, tooth_number, top_k)` | `TemplateMatch` | Ranked template matches with scores |
| `auto_design_crown_from_scan(scan_verts, scan_faces, tooth_number, material)` | `CrownResult` | Full crown mesh from scan |

## Example

```python
match = match_tooth_template(prep_verts, prep_faces, "26", top_k=3)
# TemplateMatch(best_template='upper_first_molar_v3',
#               similarity_score=0.94, top_k=[...])
crown = auto_design_crown_from_scan(prep_verts, prep_faces, "26", "zirconia")
# CrownResult(vertices=..., faces=..., margin_rms_mm=0.08)
```

## Honest caveats

Template matching is based on morphological shape, not patient-specific anatomical landmark registration. The template library covers standard FDI tooth positions; unusual crown forms (taurodontism, peg laterals) may produce poor matches. Auto-designed crowns should always be reviewed by the clinician for occlusal contacts and margin fit before milling.

## References

- Hu, "Visual pattern recognition by moment invariants," *IRE Trans. Info. Theory* 8(2), 1962.
- Bookstein, *Morphometric Tools for Landmark Data*, Cambridge (1991).
