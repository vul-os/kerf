# Fasteners Library

*Domain: Mechanical · Module: `packages/kerf-cad-core/src/kerf_cad_core/fasteners/` · Shipped: Wave 6*

## Overview

Parametric fastener geometry generation and strength lookup for metric and imperial threaded fasteners: ISO 4762 socket head cap screws, ISO 4014 hex bolts, ISO 7089/7090 washers, DIN 934 hex nuts, ISO 10642 countersunk screws, and thread engagement calculations. Generates ISO-toleranced thread profiles and 3-D solid models ready for assembly insertion.

## When to use

- Inserting standard fasteners into a 3-D assembly with correct geometry.
- Checking bolt strength (proof load, tensile strength) for a joint design.
- Computing minimum thread engagement length for a tapped hole.

## API

```python
from kerf_cad_core.fasteners.tools import (
    iso_bolt, thread_engagement_length,
    bolt_proof_load, fastener_library_search,
)

# M8 × 25 socket head cap screw ISO 4762
bolt = iso_bolt(size="M8", length_mm=25, standard="iso_4762",
                material="12.9_alloy_steel")

# Minimum thread engagement
te = thread_engagement_length(
    size="M8", material_strength="aluminium_6061"
)
print(te["L_min_mm"])

# Proof load
pl = bolt_proof_load(size="M8", property_class="12.9")
print(pl["Fp_N"])
```

## LLM tools

`feature_insert_fastener`, `feature_fastener_search`

## References

- ISO 4762:2004, *Hexagon socket head cap screws*.
- ISO 898-1:2013, *Mechanical properties of fasteners — bolts, screws and studs*.
- VDI 2230:2015, *Systematic calculation of high duty bolted joints*.

## Honest caveats

Thread engagement calculations use the VDI 2230 simplified formula for uniform-strength engagement in through-holes. Blind-hole engagement (lacking nut backup) requires a stripping-strength calculation with the parent material shear strength. Fatigue-critical joints require the full VDI 2230 bolt fatigue analysis which is not implemented here.
