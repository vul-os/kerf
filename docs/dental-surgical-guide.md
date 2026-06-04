# Dental Implant and Surgical Guide Planning

*Domain: Dental · Module: `packages/kerf-dental/src/kerf_dental/guide.py` · Shipped: Wave 10*

## Overview

Plans implant placement from a CBCT DICOM volume or STL scan mesh and generates a stereolithographic surgical guide with a drill sleeve. `place_surgical_guide` computes the optimal implant axis from bone density sampling, places the implant at the specified site, and builds the guide body that indexes against the adjacent teeth. Output is a guide STL for SLA/DLP printing and a drill protocol report.

## When to use

- Planning single or multiple implant placements from CBCT data.
- Generating a tooth-supported or mucosa-supported surgical guide.
- Verifying implant angulation relative to the occlusal plane and adjacent roots.

## API

```python
from kerf_dental.guide import (
    ImplantSpec, SurgicalGuideResult,
    place_surgical_guide,
)

spec = ImplantSpec(
    site="upper_right_first_premolar",  # FDI: 14
    diameter_mm=3.8,
    length_mm=10.0,
    platform="bone_level",
    angulation_deg=0.0,   # 0 = axial
)

result: SurgicalGuideResult = place_surgical_guide(
    scan_mesh=scan_mesh,   # STL mesh of the jaw
    implant=spec,
    support_type="tooth_supported",
)

# result.guide_mesh — triangulated guide body
# result.drill_protocol — list of drill steps with diameters
```

## LLM tools

`dental_surgical_guide`

## References

- Tahmaseb et al., "The accuracy of computer-guided implant surgery with mucosa-supported surgical template", *Clinical Oral Implants Research* 25(7), 2014.
- ITI SAC Assessment Tool criteria for implant complexity.

## Honest caveats

`place_surgical_guide` uses nearest-surface-point projection to locate the implant axis and does not perform bone density analysis from DICOM — supply the DICOM volume via `dental_dicom_ingest` first for density-guided placement. Angulation deviations > 5° from the planned axis require guide redesign; the tolerance check is the caller's responsibility.
