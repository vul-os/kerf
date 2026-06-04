# Dental Crown and Bridge Design

*Domain: Dental · Module: `packages/kerf-dental/src/kerf_dental/crown.py` · Shipped: Wave 10*

## Overview

Parametric anatomic crown design for zirconia, PFM (porcelain-fused-to-metal), or composite restorations. Takes a tooth anatomy specification (arch position, cusp height, mesio-distal width, bucco-lingual width) and generates a triangulated crown mesh with anatomically correct cusp morphology. Output is a `.stl`-ready mesh for milling or 3D printing with die spacer, cement gap, and occlusal clearance built in.

## When to use

- Designing single-tooth zirconia crowns for CAD/CAM milling.
- Generating a crown mesh from intraoral scan data for DSD (Digital Smile Design).
- Batch-generating crown candidates for AI-assisted tooth morphology studies.

## API

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

## LLM tools

`dental_crown_design`

## References

- Rosenstiel, Land & Fujimoto, *Contemporary Fixed Prosthodontics*, 5th ed. (2015).
- ISO 6872:2015, *Dentistry — Ceramic materials*.

## Honest caveats

The anatomic crown generator produces biologically plausible morphology but is not a replacement for a trained prosthodontist's crown design. Contact point geometry, occlusal curve of Spee, and Monson's sphere of occlusion are approximated. For implant superstructures, use `dental_crown_design` after `dental_surgical_guide` to ensure the implant axis is correctly accounted for.
