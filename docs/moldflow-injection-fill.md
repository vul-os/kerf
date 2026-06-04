# Moldflow Injection Fill Simulation

*Domain: Manufacturing · Module: `packages/kerf-manufacturing/src/kerf_manufacturing/moldflow/hele_shaw.py` · Shipped: Wave 10*

## Overview

Simulates injection moulding fill using the Hele-Shaw thin-shell flow model on a triangulated shell mesh. Computes pressure distribution, fill-time isochrones (melt-front arrival), and weld-line predictions. Uses a finite-element pressure solve followed by a front-tracking fill-time calculation. Suitable for early-stage gate placement and fill-balance studies.

## When to use

- Evaluating gate location options before cutting steel.
- Identifying likely weld-line positions for structural or cosmetic assessment.
- Estimating injection pressure for machine selection.

## API

```python
from kerf_manufacturing.moldflow.hele_shaw import (
    ShellMesh, GateLocation, InjectionConditions,
    MoldFlowResult, run_moldflow,
)

mesh = ShellMesh(
    nodes=[[x, y, z], ...],
    triangles=[[i, j, k], ...],
)
gate = GateLocation(node_index=42)
cond = InjectionConditions(
    fluidity=1.0,       # Pa·s⁻¹·m³ (viscosity reciprocal proxy)
    fill_time_s=2.0,
)

result: MoldFlowResult = run_moldflow(mesh, [gate], cond)

print(result.fill_time_per_node)    # list of arrival times (s)
print(result.pressure_per_node)     # list of pressures (Pa)
print(result.weld_line_segments)    # [[n1, n2], ...] edge list
```

## LLM tools

`manufacturing_moldflow`

## References

- Hele-Shaw, "The flow of water", *Nature* 58, 1898.
- Kennedy, *Practical and Scientific Aspects of Injection Molding Simulation* (2008).

## Honest caveats

The Hele-Shaw model assumes a thin shell (part thickness << planar dimensions) and Newtonian viscosity. Non-Newtonian shear-thinning, fibre orientation, cooling, and packing phases are not modelled. Weld-line detection is geometric (opposing fill fronts) rather than thermal, so actual weld-line strength is not predicted. Use Moldflow Insight or Sigmasoft for production-level analysis.
