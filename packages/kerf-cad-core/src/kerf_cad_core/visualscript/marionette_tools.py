"""
kerf_cad_core.visualscript.marionette_tools
=============================================
LLM tool wrappers for the Marionette / MatrixGold visual scripting engine.

Registers the following tools with the Kerf tool registry:

  visualscript_evaluate_graph   — evaluate a full Marionette DAG
  visualscript_topological_order — return topological order for a graph
  visualscript_list_node_types  — list all built-in node types

All tools are pure-Python; no OCC dependency.
Errors returned as {"ok": false, "reason": "..."} — tools never raise.

References
----------
Vectorworks Marionette — https://developer.vectorworks.net/marionette
MatrixGold Visual Scripting Guide, Gemvision 2022.

Author: imranparuk
"""
from __future__ import annotations

import json

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.visualscript.marionette import (
    MarionetteNode,
    MarionetteGraph,
    evaluate_marionette_graph,
    NODE_LIBRARY,
)


# ---------------------------------------------------------------------------
# Tool: visualscript_evaluate_graph
# ---------------------------------------------------------------------------

_evaluate_graph_spec = ToolSpec(
    name="visualscript_evaluate_graph",
    description=(
        "Evaluate a Vectorworks Marionette / MatrixGold visual-scripting DAG.\n"
        "\n"
        "Each node in the graph has a node_type (e.g. 'wall', 'window', "
        "'array', 'truss_span') and input port values.  Connections route "
        "output values from upstream nodes to input pins of downstream nodes.  "
        "Nodes are evaluated in topological (dependency) order.\n"
        "\n"
        "Built-in node types: wall, floor, window, door, column, array, move, "
        "rotate, scale, boolean_union, boolean_subtract, extrude, loft, "
        "material, truss_span.\n"
        "\n"
        "Returns {ok, node_results: {node_id: {inputs, outputs}}, "
        "node_order: [...]}.\n"
        "\n"
        "Cycle detection: returns {ok:false, reason} if the graph has a cycle.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "description": (
                    "List of node objects. Each has: "
                    "node_id (str), node_type (str), "
                    "inputs (dict of constant port values, optional)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string"},
                        "node_type": {"type": "string"},
                        "inputs": {"type": "object"},
                    },
                    "required": ["node_id", "node_type"],
                },
            },
            "connections": {
                "type": "array",
                "description": (
                    "List of wire connections as [src_node_id, src_pin, dst_node_id, dst_pin]. "
                    "Each connection routes src_node.outputs[src_pin] → "
                    "dst_node.inputs[dst_pin] before dst_node is evaluated."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 4,
                    "maxItems": 4,
                },
            },
        },
        "required": ["nodes"],
    },
)


@register(_evaluate_graph_spec, write=False)
async def run_visualscript_evaluate_graph(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if not a.get("nodes"):
        return json.dumps({"ok": False, "reason": "nodes is required and must be non-empty"})

    try:
        raw_nodes = a["nodes"]
        raw_connections = a.get("connections", [])

        nodes = [
            MarionetteNode(
                node_id=n["node_id"],
                node_type=n["node_type"],
                inputs=dict(n.get("inputs", {})),
            )
            for n in raw_nodes
        ]
        connections = [tuple(c) for c in raw_connections]

        graph = MarionetteGraph(nodes=nodes, connections=connections)
        results = evaluate_marionette_graph(graph)
        order = graph.topological_order()

        return ok_payload({
            "node_results": results,
            "node_order": order,
        })
    except ValueError as exc:
        # Cycle detection or bad graph structure.
        return err_payload(str(exc), "CYCLE_DETECTED")
    except Exception as exc:
        return err_payload(f"graph evaluation error: {exc}", "ERROR")


# ---------------------------------------------------------------------------
# Tool: visualscript_topological_order
# ---------------------------------------------------------------------------

_topo_order_spec = ToolSpec(
    name="visualscript_topological_order",
    description=(
        "Return the topological (dependency) evaluation order for a "
        "Marionette / MatrixGold visual-script graph.\n"
        "\n"
        "Uses Kahn's algorithm (BFS-based, O(V+E)).\n"
        "\n"
        "Returns {ok, node_order: [node_id, ...]}.\n"
        "Returns {ok:false, reason} if a cycle is detected.\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "node_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of all node IDs in the graph.",
            },
            "connections": {
                "type": "array",
                "description": "List of [src_node_id, src_pin, dst_node_id, dst_pin].",
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 4,
                    "maxItems": 4,
                },
            },
        },
        "required": ["node_ids"],
    },
)


@register(_topo_order_spec, write=False)
async def run_visualscript_topological_order(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    if not a.get("node_ids"):
        return json.dumps({"ok": False, "reason": "node_ids is required"})

    try:
        # Build a minimal graph with stub nodes (no handlers needed for topo sort).
        nodes = [
            MarionetteNode(node_id=nid, node_type="__stub__")
            for nid in a["node_ids"]
        ]
        connections = [tuple(c) for c in a.get("connections", [])]
        graph = MarionetteGraph(nodes=nodes, connections=connections)
        order = graph.topological_order()
        return ok_payload({"node_order": order})
    except ValueError as exc:
        return err_payload(str(exc), "CYCLE_DETECTED")
    except Exception as exc:
        return err_payload(f"topological order error: {exc}", "ERROR")


# ---------------------------------------------------------------------------
# Tool: visualscript_list_node_types
# ---------------------------------------------------------------------------

_list_node_types_spec = ToolSpec(
    name="visualscript_list_node_types",
    description=(
        "List all built-in Marionette / MatrixGold node types available in "
        "the Kerf visual scripting engine.\n"
        "\n"
        "Returns {ok, node_types: [str, ...], count: int}.\n"
        "\n"
        "Each node type corresponds to a Vectorworks Marionette or MatrixGold "
        "built-in node. Custom node_types are supported by passing a "
        "node_handlers dict to visualscript_evaluate_graph.\n"
        "\n"
        "Errors: {ok:false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {},
    },
)


@register(_list_node_types_spec, write=False)
async def run_visualscript_list_node_types(ctx: ProjectCtx, args: bytes) -> str:
    types = sorted(NODE_LIBRARY.keys())
    return ok_payload({
        "node_types": types,
        "count": len(types),
    })
