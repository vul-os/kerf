# AISC Steel Member Checks

*Domain: Structural · Module: `packages/kerf-structural/src/kerf_structural/aisc_member.py` · Shipped: Wave 10*

## Overview

AISC 360-22 LRFD/ASD member capacity checks for W-shapes, HSS, pipe, angles, and C-channels. Covers compression capacity (flexural, torsional, flexural-torsional buckling via AISC Chapter E), flexural capacity (yielding, lateral-torsional buckling, flange local buckling via Chapter F), and combined loading interaction equations (Chapter H). Section property lookups from an embedded AISC Steel Construction Manual database.

## When to use

- Checking if a wide-flange column or beam satisfies AISC demand/capacity ratios.
- Selecting the lightest W-shape or HSS for a given axial or flexural demand.
- Generating a capacity table across a section size range.

## API

```python
from kerf_structural.aisc_member import (
    w_shape, aisc_compression, aisc_flexure,
    CompressionResult, FlexureResult,
)

sec = w_shape("W10X49")

comp: CompressionResult = aisc_compression(
    section=sec,
    Fy=345e6,           # Pa (50 ksi)
    E=200e9,
    L_eff_cm=300,       # effective length cm
)
print(f"φPn = {comp.phi_Pn_N/1e3:.1f} kN")

flex: FlexureResult = aisc_flexure(
    section=sec,
    Fy=345e6,
    E=200e9,
    Lb_cm=300,          # unbraced length
    Cb=1.0,
)
print(f"φMn = {flex.phi_Mn_Nm/1e3:.1f} kNm")
```

## LLM tools

`struct_aisc_check`, `struct_member_select`

## References

- AISC 360-22, *Specification for Structural Steel Buildings*, Chapters E, F, G, H.
- AISC Steel Construction Manual, 16th ed. (section properties database).

## Honest caveats

Section property values are from the AISC 16th edition database for US shapes. Non-US sections (European IPE/HEA, Australian UB/UC) are not in the embedded database; supply properties manually via the `WShape` constructor. The interaction equations cover bending about the strong axis only; biaxial bending requires manual application of AISC H1-1.
