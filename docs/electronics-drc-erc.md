# PCB DRC and ERC

*Domain: Electronics · Module: `packages/kerf-electronics/src/kerf_electronics/drc.py` · Shipped: Wave 9*

## Overview

Design Rule Check (DRC) for PCB layouts and Electrical Rule Check (ERC) for schematics against CircuitJSON. DRC checks trace-to-trace clearance, trace-to-pad clearance, minimum annular ring, drill-to-drill spacing, board-edge clearance, silk-to-copper violations, and copper-pour isolation. ERC checks for floating nets, missing power symbols, unconnected pins, and duplicate refdes.

## When to use

- Verifying a PCB layout before sending Gerbers to a fabrication house.
- Checking a schematic for net connectivity errors before running simulation.
- Automating board quality checks in a design review pipeline.

## API

```python
from kerf_electronics.drc import (
    DRCRuleSet, run_drc, run_erc,
    DRCViolation, ERCViolation,
)

rules = DRCRuleSet(
    min_trace_clearance_mm=0.15,
    min_trace_width_mm=0.10,
    min_drill_mm=0.25,
    min_annular_ring_mm=0.125,
    board_edge_clearance_mm=0.5,
)

drc_results = run_drc(circuit_json=board, rules=rules)
erc_results = run_erc(circuit_json=schematic)

for v in drc_results.violations:
    print(v.rule, v.location, v.measured, v.required)
```

## LLM tools

`pcb_drc`, `pcb_erc`

## References

- IPC-2221B, *Generic Standard on Printed Board Design* (clearances, annular ring).
- IPC-7351C, *Land Pattern Standard for SMT Components*.

## Honest caveats

DRC clearance checks use the component footprint bounding boxes as an approximation when exact pad geometry is not available in CircuitJSON. Complex polygon copper pours require exact polygon-boolean clearance checks which are computed at reduced resolution for large boards. ERC does not perform netlist-level gate-swap equivalence checking.
