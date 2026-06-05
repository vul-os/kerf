"""
kerf_cad_core.geometry_nodes_tools — LLM tool for Geometry Nodes DAG evaluation.

Provides a single tool:
  geometry_nodes_evaluate_graph  — evaluate a JSON graph description, running
                                   each node's built-in operation and collecting
                                   per-node results.

This is a lightweight pure-Python implementation (no OCC dependency) that
supports the fundamental geometry node types used by the frontend
GeometryNodesPanel: number, add, multiply, range, vec3, mesh_sphere,
mesh_cylinder, mesh_torus, and mesh_extrude (using the same IDs as
src/components/nodescript/node_library.js).

Graph JSON format (same as graph_engine.js Graph.toJSON())
----------------------------------------------------------
{
  "nodes": {
    "<nodeId>": {
      "defId": "<node type id>",
      "params": { "<param>": <value>, ... },
      "position": {"x": ..., "y": ...},
      "disabled": false
    },
    ...
  },
  "connections": {
    "<connId>": {
      "fromNodeId": "...",
      "fromPin": "...",
      "toNodeId": "...",
      "toPin": "..."
    },
    ...
  }
}

Returns:
  {
    "ok": true,
    "node_order": ["<nodeId>", ...],
    "node_results": { "<nodeId>": { "output": <value>, "ok": true } },
    "n_nodes": <int>,
    "n_connections": <int>
  }

References
----------
- Blender Geometry Nodes documentation, Blender 4.x.
  https://docs.blender.org/manual/en/latest/modeling/geometry_nodes/index.html
- Blender source: source/blender/nodes/geometry/ (NOD_geometry_nodes.hh)
"""
from __future__ import annotations

import json
import math
from typing import Any

from kerf_cad_core._compat import ToolSpec, err_payload, ok_payload, register

try:
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
except ImportError:
    from kerf_cad_core._compat import ProjectCtx  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Node evaluation functions — mirrors node_library.js node types
# ---------------------------------------------------------------------------

def _eval_node(def_id: str, params: dict, resolved_inputs: dict) -> Any:
    """Evaluate a single node given its type, params, and resolved input values.

    Returns the primary output value (or a dict for multi-output nodes).
    Returns None if the node type is unrecognised (graceful degradation).
    """
    # Merge: resolved inputs override params (connected value wins)
    effective = {**params, **resolved_inputs}

    def _num(key: str, default: float = 0.0) -> float:
        v = effective.get(key, default)
        return float(v) if v is not None else default

    def _int(key: str, default: int = 1) -> int:
        v = effective.get(key, default)
        return int(v) if v is not None else default

    if def_id == "number":
        return _num("value", 0.0)

    if def_id == "add":
        return _num("a") + _num("b")

    if def_id == "multiply":
        return _num("a", 1.0) * _num("b", 1.0)

    if def_id == "range":
        start = _num("start", 0.0)
        end   = _num("end", 1.0)
        steps = max(2, _int("steps", 10))
        step  = (end - start) / (steps - 1)
        return [start + i * step for i in range(steps)]

    if def_id == "vec3":
        return [_num("x"), _num("y"), _num("z")]

    if def_id == "vec3_add":
        a = effective.get("a", [0, 0, 0])
        b = effective.get("b", [0, 0, 0])
        if isinstance(a, list) and isinstance(b, list) and len(a) == 3 and len(b) == 3:
            return [a[i] + b[i] for i in range(3)]
        return [0, 0, 0]

    if def_id == "cross_product":
        a = effective.get("a", [1, 0, 0])
        b = effective.get("b", [0, 1, 0])
        if isinstance(a, list) and isinstance(b, list) and len(a) == 3 and len(b) == 3:
            return [
                a[1] * b[2] - a[2] * b[1],
                a[2] * b[0] - a[0] * b[2],
                a[0] * b[1] - a[1] * b[0],
            ]
        return [0, 0, 0]

    if def_id == "dot_product":
        a = effective.get("a", [1, 0, 0])
        b = effective.get("b", [1, 0, 0])
        if isinstance(a, list) and isinstance(b, list):
            return sum(ai * bi for ai, bi in zip(a, b))
        return 0.0

    if def_id == "mesh_sphere":
        r = max(1e-6, _num("radius", 1.0))
        segs = max(3, _int("segments", 16))
        rings = max(2, _int("rings", 8))
        n_verts = (rings - 1) * segs + 2
        n_faces = segs * (rings - 1) * 2
        return {"type": "mesh_sphere", "radius": r, "segments": segs, "rings": rings,
                "vertex_count": n_verts, "face_count": n_faces}

    if def_id == "mesh_cylinder":
        r = max(1e-6, _num("radius", 1.0))
        h = max(1e-6, _num("height", 2.0))
        segs = max(3, _int("segments", 16))
        n_verts = segs * 2 + 2
        n_faces = segs * 3
        return {"type": "mesh_cylinder", "radius": r, "height": h, "segments": segs,
                "vertex_count": n_verts, "face_count": n_faces}

    if def_id == "mesh_torus":
        R = max(1e-6, _num("major_radius", 1.0))
        r = max(1e-6, _num("minor_radius", 0.25))
        maj_segs = max(3, _int("major_segments", 24))
        min_segs = max(3, _int("minor_segments", 12))
        n_verts = maj_segs * min_segs
        n_faces = maj_segs * min_segs
        return {"type": "mesh_torus", "major_radius": R, "minor_radius": r,
                "major_segments": maj_segs, "minor_segments": min_segs,
                "vertex_count": n_verts, "face_count": n_faces}

    if def_id == "mesh_extrude":
        profile = effective.get("profile", None)
        depth = _num("depth", 1.0)
        return {"type": "mesh_extrude", "depth": depth, "has_profile": profile is not None}

    if def_id == "transform":
        geo = effective.get("geometry", None)
        translate = effective.get("translation", [0, 0, 0])
        scale = effective.get("scale", [1, 1, 1])
        if isinstance(geo, dict):
            return {**geo, "transform": {"translation": translate, "scale": scale}}
        return {"transform_applied": True}

    if def_id == "join_geometry":
        geo_a = effective.get("geometry_a", None)
        geo_b = effective.get("geometry_b", None)
        return {"type": "join_geometry", "a": geo_a, "b": geo_b}

    if def_id == "output":
        return {"type": "output", "value": effective.get("geometry", effective.get("value", None))}

    # Unknown node — pass through params
    return {"_unknown_node": def_id, "params": params}


# ---------------------------------------------------------------------------
# Topological sort
# ---------------------------------------------------------------------------

def _topo_sort(nodes: dict, connections: dict) -> list[str]:
    """Kahn's algorithm topological sort.

    Returns ordered list of node IDs (dependencies first).
    Raises ValueError on cycle.
    """
    in_edges: dict[str, set] = {nid: set() for nid in nodes}
    out_edges: dict[str, list] = {nid: [] for nid in nodes}
    pin_map: dict[str, list] = {}  # toNodeId+toPin -> (fromNodeId, fromPin)

    for conn in connections.values():
        fn = conn["fromNodeId"]
        tn = conn["toNodeId"]
        tp = conn["toPin"]
        fp = conn["fromPin"]
        if fn not in nodes or tn not in nodes:
            continue
        in_edges[tn].add(fn)
        out_edges[fn].append(tn)
        pin_map.setdefault(tn, []).append((fn, fp, tp))

    # Kahn's
    queue = [nid for nid, ins in in_edges.items() if not ins]
    order = []
    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for tn in out_edges[nid]:
            in_edges[tn].discard(nid)
            if not in_edges[tn]:
                queue.append(tn)

    if len(order) != len(nodes):
        raise ValueError("Graph contains a cycle")

    return order, pin_map


# ---------------------------------------------------------------------------
# Tool: geometry_nodes_evaluate_graph
# ---------------------------------------------------------------------------

_evaluate_graph_spec = ToolSpec(
    name="geometry_nodes_evaluate_graph",
    description=(
        "Evaluate a Geometry Nodes DAG.\n\n"
        "Each node has a defId (type string) and params dict.  Connections route\n"
        "output values from upstream nodes to input pins of downstream nodes.\n"
        "Nodes are evaluated in topological order.\n\n"
        "Supported node types (mirrors src/components/nodescript/node_library.js):\n"
        "  number, add, multiply, range, vec3, vec3_add, cross_product, dot_product,\n"
        "  mesh_sphere, mesh_cylinder, mesh_torus, mesh_extrude, transform,\n"
        "  join_geometry, output\n\n"
        "Input format: {nodes: {<id>: {defId, params, disabled?}}, "
        "connections: {<id>: {fromNodeId, fromPin, toNodeId, toPin}}}\n\n"
        "Returns {ok, node_order, node_results, n_nodes, n_connections}.\n"
        "Errors: {ok: false, reason}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "object",
                "description": "Node map: id → {defId, params, disabled?}",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "defId": {"type": "string"},
                        "params": {"type": "object"},
                        "disabled": {"type": "boolean"},
                    },
                    "required": ["defId"],
                },
            },
            "connections": {
                "type": "object",
                "description": "Connection map: id → {fromNodeId, fromPin, toNodeId, toPin}",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "fromNodeId": {"type": "string"},
                        "fromPin":    {"type": "string"},
                        "toNodeId":   {"type": "string"},
                        "toPin":      {"type": "string"},
                    },
                    "required": ["fromNodeId", "fromPin", "toNodeId", "toPin"],
                },
            },
        },
        "required": ["nodes", "connections"],
    },
)


@register(_evaluate_graph_spec, write=False)
async def run_geometry_nodes_evaluate_graph(ctx: ProjectCtx, args: bytes) -> str:
    try:
        payload = json.loads(args)
    except (json.JSONDecodeError, TypeError) as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    nodes_raw = payload.get("nodes", {})
    connections_raw = payload.get("connections", {})

    if not isinstance(nodes_raw, dict) or not isinstance(connections_raw, dict):
        return err_payload("nodes and connections must be objects", "BAD_ARGS")

    # Filter out disabled nodes
    active_nodes = {
        nid: nd for nid, nd in nodes_raw.items()
        if not nd.get("disabled", False) and nd.get("defId")
    }

    if not active_nodes:
        return ok_payload({
            "ok": True,
            "node_order": [],
            "node_results": {},
            "n_nodes": 0,
            "n_connections": len(connections_raw),
        })

    # Filter connections to only those between active nodes
    active_conns = {
        cid: c for cid, c in connections_raw.items()
        if c.get("fromNodeId") in active_nodes and c.get("toNodeId") in active_nodes
    }

    try:
        order, pin_map = _topo_sort(active_nodes, active_conns)
    except ValueError as exc:
        return err_payload(str(exc), "CYCLE_ERROR")

    # Evaluate in topo order
    node_results: dict[str, Any] = {}
    for nid in order:
        nd = active_nodes[nid]
        def_id = str(nd.get("defId", ""))
        params = dict(nd.get("params", {}) or {})

        # Resolve input connections
        resolved_inputs: dict[str, Any] = {}
        for dep_nid, dep_pin, to_pin in pin_map.get(nid, []):
            if dep_nid in node_results and node_results[dep_nid].get("ok"):
                resolved_inputs[to_pin] = node_results[dep_nid].get("output")

        try:
            output = _eval_node(def_id, params, resolved_inputs)
            node_results[nid] = {"ok": True, "defId": def_id, "output": output}
        except Exception as exc:
            node_results[nid] = {"ok": False, "defId": def_id, "reason": str(exc)}

    return ok_payload({
        "ok": True,
        "node_order": order,
        "node_results": node_results,
        "n_nodes": len(active_nodes),
        "n_connections": len(active_conns),
    })


__all__ = ["run_geometry_nodes_evaluate_graph"]
