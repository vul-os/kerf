# Dental Surgical Guide Design

> Generate a stereolithographic surgical guide with drill sleeve from a jaw scan and implant plan.

**Module**: `packages/kerf-dental/src/kerf_dental/surgical_guide.py`
**Shipped**: Wave 10
**LLM tools**: `dental_surgical_guide`

---

## What it is

The surgical guide module builds a tooth-supported or mucosa-supported drill guide body that positions a cylindrical drill sleeve precisely over the planned implant axis. Input is a jaw scan mesh and an implant specification (site, diameter, length, angulation). Output is a guide STL for SLA/DLP printing and a drill protocol (ordered sequence of drill diameters and depths).

## How to use it

### From chat

> "Generate a tooth-supported surgical guide for a 3.8 mm implant at site 14, axial angulation."

### From Python

```python
from kerf_dental.surgical_guide import (
    DrillSleeve, SurgicalGuide, design_surgical_guide,
)

guide = design_surgical_guide(
    scan_mesh=jaw_mesh,
    tooth_site="14",         # FDI notation
    implant_diameter_mm=3.8,
    implant_length_mm=10.0,
    angulation_deg=0.0,
    support_type="tooth_supported",
)
print(guide.drill_protocol)
# guide.guide_mesh.vertices, guide.guide_mesh.faces — printable guide
```

### From an LLM tool spec

```json
{"tool": "dental_surgical_guide", "input": {"tooth_site": "14", "implant_diameter_mm": 3.8, "implant_length_mm": 10.0, "support_type": "tooth_supported"}}
```

## How it works

`_build_arch_shell_mesh` creates a thin shell offset 1 mm from the arch scan surface that will index against adjacent tooth anatomy. `_build_sleeve_mesh` generates a cylindrical drill sleeve aligned with the implant axis, with an inner diameter matching the drill size (implant diameter − 0.2 mm) and a collar flange that registers the guide depth. The two meshes are Booleanunioned to form the final guide body.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `design_surgical_guide(scan_mesh, tooth_site, implant_diameter_mm, implant_length_mm, angulation_deg, support_type)` | `SurgicalGuide` | Complete guide mesh and drill protocol |
| `DrillSleeve(inner_mm, outer_mm, height_mm, axis)` | instance | Drill sleeve geometry |

## Example

```python
guide = design_surgical_guide(jaw_mesh, "14", 3.8, 10.0, 0.0, "tooth_supported")
# SurgicalGuide(guide_mesh=<Mesh>, drill_protocol=[
#   {'step': 1, 'drill_mm': 2.0, 'depth_mm': 10.0},
#   {'step': 2, 'drill_mm': 3.5, 'depth_mm': 10.0},
# ])
```

## Honest caveats

The guide indexing uses nearest-surface-point projection; it does not verify that the adjacent teeth are sufficiently stable to support the guide during drilling. Angulation deviations > 5° from the planned axis require guide redesign. DICOM bone density analysis (for density-guided axis selection) is handled separately by `dental_implant_metrics`.

## References

- Tahmaseb et al., "Accuracy of computer-guided implant surgery with mucosa-supported surgical template," *Clin. Oral Implants Res.* 25(7), 2014.
- ITI SAC Assessment Tool, implant site complexity classification.
