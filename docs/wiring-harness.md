# Wiring Harness Design

*Domain: Electronics · Module: `packages/kerf-cad-core/src/kerf_cad_core/harness/` · Shipped: Wave 9*

## Overview

Electrical wiring harness design: wire routing from a connection list (from-to table), bundle diameter estimation (IPC/SAE wire packing), connector pin assignment, voltage drop calculation, and automatic formboard flattening. Generates IPC-2612-compliant harness drawings and a wire BOM with lengths, gauges, and connector part numbers.

## When to use

- Routing and documenting the wiring harness for a vehicle, machine, or appliance.
- Computing bundle diameters for conduit sizing.
- Generating a formboard drawing for harness assembly.

## API

```python
from kerf_cad_core.harness.tools import (
    HarnessConnection, HarnessRoute,
    wire_bundle_diameter,
    voltage_drop,
    generate_formboard,
)

# Voltage drop check for a 12V circuit
drop = voltage_drop(
    gauge_awg=16,
    length_m=3.0,
    current_A=10.0,
    temp_C=40.0,
)
print(drop["V_drop"], drop["V_at_load"])
print(drop["percent_drop"])

# Bundle OD with IPC packing factor 0.65
bundle = wire_bundle_diameter(
    wire_gauges_awg=[16, 16, 18, 18, 20, 20],
    packing_factor=0.65,
)
```

## LLM tools

`harness_route`, `harness_bom`, `harness_formboard`

## References

- IPC-2612-3:2018, *Sectional Requirements for Electronic Data Interchange of Printed Board Assembly Data — Harness Data*.
- SAE EWIS Handbook (SAE AS50881) — aircraft wiring systems.

## Honest caveats

Wire routing is currently 2-D (formboard flattening). 3-D harness routing in a 3-D assembly uses a simplified minimum-spanning-tree path; smooth 3-D spline paths through a mechanical assembly require the `kerf-wiring` 3-D routing module. Ampacity de-rating for bundled wires per NEC Table 310.15(C)(1) must be applied manually.
