# Braceworks Stage Truss and Entertainment Rigging

> Design and verify stage truss spans with load capacity checks — Vectorworks Braceworks-inspired.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/visualscript/marionette.py` (`handler_truss_span`)
**Shipped**: Wave 9B3
**LLM tools**: `visualscript_evaluate_graph`

---

## What it is

The `truss_span` Marionette node generates a parametric stage-truss span geometry (I-chord, box truss, or ladder truss) with configurable span, truss depth, chord diameter, and bay count. It computes the maximum UDL (uniformly distributed load) capacity using a simple beam model and flags spans that exceed safe working load, mirroring Vectorworks Braceworks behaviour.

## How to use it

### From chat

> "Design a 12 m box truss with 400 mm depth, 6 bays, supporting 800 kg UDL. Is it within capacity?"

### From Python

```python
from kerf_cad_core.visualscript.marionette import (
    MarionetteGraph, evaluate_marionette_graph,
)

g = MarionetteGraph()
node = g.add_node("truss_span", inputs={
    "span_m": 12.0,
    "depth_m": 0.4,
    "truss_type": "box",
    "n_bays": 6,
    "udl_kg_m": 66.7,  # 800 kg / 12 m
    "material": "aluminium_6082",
})
result = evaluate_marionette_graph(g)
truss_out = result["node_outputs"][node.id]
print(truss_out["max_udl_kg_m"], truss_out["capacity_ok"])
```

### From an LLM tool spec

```json
{"tool": "visualscript_evaluate_graph", "input": {"graph_json": {"nodes": [{"type": "truss_span", "inputs": {"span_m": 12, "depth_m": 0.4, "truss_type": "box", "n_bays": 6, "udl_kg_m": 66.7}}], "edges": []}}}
```

## How it works

The truss capacity check models the truss as a simply-supported beam with a uniformly distributed load. The maximum bending moment is `M = w L² / 8`. The chord cross-section moment of inertia (from the tube dimensions) gives the section modulus `S = I / (depth/2)`. Capacity is `w_max = σ_allow × S × 8 / L²` using the allowable stress for the chosen material. Geometry is rendered as a 3-D line set of chords and diagonals.

## API reference

| Node | Key Inputs | Key Outputs |
|---|---|---|
| `truss_span` | `span_m`, `depth_m`, `truss_type`, `n_bays`, `udl_kg_m`, `material` | `geometry`, `max_udl_kg_m`, `capacity_ok` |

## Example

```python
truss_out = result["node_outputs"][node.id]
# {'max_udl_kg_m': 84.2, 'capacity_ok': True,
#  'geometry': <TrussGeometry>, 'deflection_mm': 18.3}
```

## Honest caveats

The beam-model capacity check is a simplified analysis for preliminary sizing only. It does not account for dynamic loads, point loads, motor hoists, or lateral buckling of chord members. For final sign-off, the truss design must be verified by a structural engineer per EN 1993-1-1 or equivalent. No connection details (end-plate, sleeve coupler) are generated.

## References

- EN 1993-1-1:2005, *Eurocode 3: Design of steel structures*.
- PLASA, *Rigging — Guidelines for Entertainment Rigging*, BSR E1.6 (2012).
