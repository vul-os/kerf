# Dental Crown and Bridge Design

> Generate anatomically correct crown and bridge meshes for zirconia, PFM, and composite restorations in one call.

**Module**: `packages/kerf-dental/src/kerf_dental/crown.py`
**Shipped**: Wave 10
**LLM tools**: `dental_crown_design`, `dental_crown_bridge_design`

---

## What it is

Parametric anatomic crown design for zirconia, PFM (porcelain-fused-to-metal), or composite restorations. Takes a tooth anatomy specification (arch position, cusp height, mesio-distal width, bucco-lingual width) and generates a triangulated crown mesh with anatomically correct cusp morphology. Output is a `.stl`-ready mesh for milling or 3D printing with die spacer, cement gap, and occlusal clearance built in.

## How to use it

### From chat

> "Design a zirconia crown for the upper first molar, mesio-distal 10.5 mm, buccal-lingual 11 mm."

### From Python

```python
from kerf_dental.crown import (
    ToothAnatomy, CrownDesignInput, CrownResult,
    design_crown_anatomic, design_crown,
)

tooth = ToothAnatomy(
    position="upper_first_molar",
    md_width_mm=10.5,
    bl_width_mm=11.0,
    cusp_height_mm=4.0,
)
inp = CrownDesignInput(
    anatomy=tooth,
    material="zirconia",
    die_spacer_mm=0.08,
    cement_gap_mm=0.05,
    occlusal_clearance_mm=1.5,
)
result: CrownResult = design_crown(inp)
# result.vertices, result.faces — triangulated mesh
```

### From an LLM tool spec

```json
{"tool": "dental_crown_design", "input": {"position": "upper_first_molar", "material": "zirconia", "md_width_mm": 10.5, "bl_width_mm": 11.0}}
```

## How it works

The crown generator constructs a cusp morphology from a parametric arch template, positioning cusps at anatomically validated heights and radii for each tooth position. The occlusal surface is a smoothed NURBS patch over the cusp tips. A uniform inward offset by `die_spacer_mm + cement_gap_mm` from the preparation margin gives the intaglio surface. Output vertices and faces form a closed manifold mesh.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `design_crown(inp)` | `CrownResult` | Full crown mesh from anatomy spec |
| `design_crown_anatomic(anatomy, material)` | `CrownResult` | Simplified single-call interface |
| `ToothAnatomy(position, md_width_mm, bl_width_mm, cusp_height_mm)` | instance | Tooth dimension spec |

## Example

```python
result = design_crown(inp)
# CrownResult(vertices=array(...), faces=array(...),
#             n_vertices=1842, n_faces=3680, material='zirconia')
```

## Honest caveats

The anatomic crown generator produces biologically plausible morphology but is not a replacement for a trained prosthodontist's crown design. Contact point geometry, occlusal curve of Spee, and Monson's sphere of occlusion are approximated. For implant superstructures, plan the implant first with `dental_implant_metrics` to ensure the implant axis is correctly accounted for.

## References

- Rosenstiel, Land & Fujimoto, *Contemporary Fixed Prosthodontics*, 5th ed. (2015).
- ISO 6872:2015, *Dentistry — Ceramic materials*.
