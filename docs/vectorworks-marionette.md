# Vectorworks Marionette Visual Scripting

> Build parametric geometry by connecting node graphs — a Vectorworks Marionette-compatible workflow.

**Module**: `packages/kerf-cad-core/src/kerf_cad_core/visualscript/marionette.py`
**Shipped**: Wave 9B3
**LLM tools**: `visualscript_evaluate_graph`, `visualscript_topological_order`, `visualscript_list_node_types`

---

## What it is

The Marionette module implements a node-graph evaluator for parametric CAD scripting. Each `MarionetteNode` has typed inputs and outputs; `MarionetteGraph` connects them into a DAG. Evaluation proceeds in topological order, propagating geometry values (walls, floors, windows, trusses) between nodes. The node library mirrors Vectorworks Marionette's built-in node palette.

## How to use it

### From chat

> "Create a Marionette graph that arrays 8 columns at 3 m spacing along a curve."

### From Python

```python
from kerf_cad_core.visualscript.marionette import (
    MarionetteGraph, MarionetteNode, evaluate_marionette_graph,
)

g = MarionetteGraph()
curve_node = g.add_node("input_curve", inputs={"curve": my_curve})
array_node = g.add_node("array_along_curve", inputs={"count": 8, "spacing_m": 3.0})
col_node   = g.add_node("create_column", inputs={"height_m": 4.0, "diameter_m": 0.3})
g.connect(curve_node, "curve", array_node, "curve")
g.connect(array_node, "points", col_node, "base_points")

result = evaluate_marionette_graph(g)
print(result["geometry"])  # list of column solid objects
```

### From an LLM tool spec

```json
{"tool": "visualscript_evaluate_graph", "input": {"graph_json": {...}}}
```

## How it works

`evaluate_marionette_graph` calls `visualscript_topological_order` (Kahn's algorithm on the adjacency list) to produce a linear evaluation order. Each node is dispatched to its handler function (`handler_create_wall`, `handler_array_along_curve`, etc.). Node outputs are stored in a value cache and forwarded to downstream input ports before their evaluation.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `evaluate_marionette_graph(graph)` | `dict` | Full geometry output of evaluated graph |
| `MarionetteGraph.add_node(type, inputs)` | `MarionetteNode` | Add a node to the graph |
| `MarionetteGraph.connect(src, out, dst, inp)` | None | Wire two node ports |

## Example

```python
result = evaluate_marionette_graph(g)
# {'geometry': [<Wall>, <Wall>, ...], 'node_outputs': {...}}
```

## Honest caveats

The node library covers the most common architectural and structural node types; custom Python node handlers can be registered but are not serialisable. Cyclic graphs raise a `ValueError` at evaluation time. Floating-point numerical stability for large-offset arrays (> 100 repetitions) may accumulate positional error.

## References

- Vectorworks, *Marionette Scripting Reference* (2023).
- Kahn, "Topological Sorting of Large Networks," *Commun. ACM* 5(11), 1962.
