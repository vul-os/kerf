# Sheet Metal Bend and Flat Pattern

*Domain: Manufacturing · Module: `packages/kerf-cad-core/src/kerf_cad_core/sheet_metal.py` · Shipped: Wave 6*

## Overview

Parametric sheet metal design: bend relief, flange, hem, joggle, and corner relief features; K-factor and bend deduction calculation per the Machinery's Handbook bend allowance table; flat pattern unfolding; and DXF export for laser or plasma cutting. Integrated bend table (`sheet_metal_bend_table.py`) covers common material/thickness/tooling combinations.

## When to use

- Designing a bent sheet metal bracket with accurate flat-pattern dimensions.
- Computing the blank size for a formed sheet metal part.
- Exporting a flat pattern for laser cutting or waterjet programming.

## API

```python
from kerf_cad_core.sheet_metal import (
    SheetMetalPart, BendFeature, FlangeFeature,
    compute_bend_allowance, compute_flat_pattern,
    export_flat_dxf,
)
from kerf_cad_core.sheet_metal_bend_table import lookup_k_factor

# K-factor from bend table (1.5mm aluminium, 1.5mm die radius)
K = lookup_k_factor(material="aluminium", thickness_mm=1.5, die_radius_mm=1.5)

# Flat pattern for a U-channel
part = SheetMetalPart(thickness_mm=1.5, K_factor=K)
part.add_base(width=50, length=100)
part.add_flange(BendFeature(angle=90, radius=1.5, length=30))
part.add_flange(BendFeature(angle=90, radius=1.5, length=30))

flat = compute_flat_pattern(part)
export_flat_dxf(flat, path="u_channel_flat.dxf")
```

## LLM tools

`feature_sheet_metal`, `feature_sheet_metal_flat_pattern`

## References

- Machinery's Handbook, 32nd ed., "Bending Sheet Metal" (K-factor and bend allowance).
- ASME Y14.5M-2018, *Dimensioning and Tolerancing* (bend radius callouts).

## Honest caveats

K-factor values in the bend table are typical mid-thickness values for common material/tooling combinations. Actual K-factors depend on punch angle, die opening, and material lot — measure from physical sample bends for production tooling setup. The flat-pattern algorithm unfolds in reverse-bend order; complex flanged parts with multiple bends at different axes may not unfold correctly and require manual sequence specification.
