# Dental Implant Planning

> Plan implant axis, bone density, and sleeve geometry from CBCT data in one step.

**Module**: `packages/kerf-dental/src/kerf_dental/implant_planning.py`
**Shipped**: Wave 10
**LLM tools**: `dental_implant_metrics`, `dental_recommend_implant`

---

## What it is

Implant planning takes a CBCT-derived scan, a proposed implant trajectory (tip position + direction vector), and outputs bone quality metrics, cortical thickness, and a go/no-go fit assessment. It also recommends optimal implant diameter and length based on bone density (Hounsfield Units classified into D1–D4 by Misch criteria) and the adjacent anatomy.

## How to use it

### From chat

> "Plan a 4.1 mm implant for tooth 36. My CBCT voxels are 0.3 mm and tip is at (12, −5, 0)."

### From Python

```python
from kerf_dental.implant_planning import (
    ImplantPlan, compute_implant_metrics, recommend_implant_dimensions,
)

plan = ImplantPlan(
    tooth_position="lower_first_molar",
    tip_xyz_mm=(12.0, -5.0, 0.0),
    axis_uvw=(0.0, 0.0, 1.0),
    implant_diameter_mm=4.1,
    implant_length_mm=10.0,
)
metrics = compute_implant_metrics(plan, hu_volume=hu_array, voxel_mm=0.3)
print(metrics.mean_hu, metrics.cortical_thickness_mm, metrics.fit_ok)

rec = recommend_implant_dimensions(plan, metrics)
print(rec["diameter_mm"], rec["length_mm"])
```

### From an LLM tool spec

```json
{"tool": "dental_implant_metrics", "input": {"tooth_position": "lower_first_molar", "tip_xyz_mm": [12.0, -5.0, 0.0], "axis_uvw": [0, 0, 1], "diameter_mm": 4.1, "length_mm": 10.0}}
```

## How it works

HU samples are taken along a cylindrical region collinear with the implant axis. The mean cortical HU and cortical thickness are estimated from the radial HU gradient at the outer 2 mm shell. Density class is assigned per Misch (1999): D1 > 1250 HU, D2 850–1250 HU, D3 350–850 HU, D4 < 350 HU. Clearance to the inferior alveolar canal (if segmented) is checked against a 2 mm safety margin.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `compute_implant_metrics(plan, hu_volume, voxel_mm)` | `ImplantMetrics` | HU stats, cortical thickness, fit flag |
| `recommend_implant_dimensions(plan, metrics)` | `dict` | Suggested diameter and length |
| `classify_bone_density(mean_hu)` | `str` | Misch D1–D4 class |
| `generate_surgical_guide_geometry(plan)` | `dict` | Sleeve mesh vertices and faces |

## Example

```python
metrics = compute_implant_metrics(plan, hu_volume=cbct, voxel_mm=0.3)
# ImplantMetrics(mean_hu=712.4, cortical_thickness_mm=1.8,
#                density_class='D3', fit_ok=True, canal_clearance_mm=4.1)
```

## Honest caveats

HU accuracy depends on CBCT calibration; cone-beam scanners have higher scatter than medical CT. The canal segmentation is estimated from intensity thresholding, not confirmed by a radiologist. Bone density classification uses Misch empirical ranges, which are population averages. Bone remodelling, healing potential, and patient systemic factors are not considered.

## References

- Misch, *Contemporary Implant Dentistry*, 3rd ed. (2008), Ch. 4.
- Lekholm & Zarb, "Patient selection and preparation," *Tissue-Integrated Prostheses* (1985).
