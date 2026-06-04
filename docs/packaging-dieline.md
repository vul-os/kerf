# Packaging Dieline Generator

*Domain: Packaging · Module: `packages/kerf-packaging/src/kerf_packaging/dieline.py` · Shipped: Wave 10*

## Overview

Generates parametric flat-pattern dielines for corrugated and folding-carton packaging in ECMA-compliant geometry. Produces cut/crease/perf line geometry as a `Dieline` object, validates closure and panel geometry, and exports to DXF or PDF for pre-press. Supports straight-tuck-end (ECMA B2), reverse-tuck-end (ECMA B3), and auto-bottom styles. The companion `ecma_generators.py` covers 30+ ECMA standard styles.

## When to use

- Generating a production-ready dieline for a product box to exact dimensions.
- Validating a received dieline for geometry errors before sending to a die cutter.
- Exporting an ECMA-standard carton for pre-press imposition.

## API

```python
from kerf_packaging.dieline import (
    Dieline, DieLine, validate_dieline,
)
from kerf_packaging.ecma_generators import straight_tuck_end

# Generate a straight-tuck-end (ECMA B2) for a 100×60×40mm product
dl: Dieline = straight_tuck_end(
    length_mm=100, width_mm=60, depth_mm=40,
    flap_mm=15, material="300gsm_sbs",
)

errors = validate_dieline(dl)
if not errors:
    dl.export_dxf("my_carton.dxf")
```

## LLM tools

`packaging_dieline_generate`, `packaging_dieline_to_dxf`, `packaging_fold_preview`

## References

- ECMA-132, *Recommendations for the Designation of Boxes* (12th ed., 2021).
- FEFCO/ESBO European Database of Packaging Styles.

## Honest caveats

Material allowance (board caliper compensation at fold lines) uses a default 0.3mm Cf for 300gsm SBS. For specific board grades, override with the supplier's measured crease allowance. The fold preview is a 2.5D flat-fold simulation; 3-D carton assembly for geometry verification is not currently rendered.
