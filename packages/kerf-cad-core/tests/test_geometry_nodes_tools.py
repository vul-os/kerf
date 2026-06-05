"""
Tests for kerf_cad_core.geometry_nodes_tools — geometry_nodes_evaluate_graph.

Coverage:
  1. Empty graph → ok, 0 nodes.
  2. Single number node → output = value.
  3. add chain: number(3) + number(5) = 8.
  4. Mesh sphere node → output has type/vertex_count/face_count keys.
  5. Mesh cylinder node → geometry dict.
  6. Mesh torus node → geometry dict.
  7. Disabled node is skipped.
  8. Cycle detection → CYCLE_ERROR.
  9. Bad JSON → BAD_ARGS.
  10. Bad args type → BAD_ARGS.
  11. Topological order respected (upstream evaluated first).
  12. Unknown node type → graceful result (not a crash).
"""
from __future__ import annotations

import asyncio
import json

import pytest

from kerf_cad_core.geometry_nodes_tools import run_geometry_nodes_evaluate_graph
from kerf_cad_core._compat import ProjectCtx

_CTX = ProjectCtx()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def call(**kwargs) -> dict:
    raw = run(run_geometry_nodes_evaluate_graph(_CTX, json.dumps(kwargs).encode()))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# 1. Empty graph
# ---------------------------------------------------------------------------

def test_empty_graph():
    result = call(nodes={}, connections={})
    assert result["ok"] is True
    assert result["n_nodes"] == 0
    assert result["node_order"] == []


# ---------------------------------------------------------------------------
# 2. Single number node
# ---------------------------------------------------------------------------

def test_single_number_node():
    result = call(
        nodes={"n1": {"defId": "number", "params": {"value": 42.0}}},
        connections={},
    )
    assert result["ok"] is True
    assert "n1" in result["node_results"]
    assert result["node_results"]["n1"]["ok"] is True
    assert result["node_results"]["n1"]["output"] == pytest.approx(42.0)


# ---------------------------------------------------------------------------
# 3. Add chain: number(3) → add.a, number(5) → add.b → result = 8
# ---------------------------------------------------------------------------

def test_add_chain():
    result = call(
        nodes={
            "n_a": {"defId": "number", "params": {"value": 3.0}},
            "n_b": {"defId": "number", "params": {"value": 5.0}},
            "n_add": {"defId": "add", "params": {"a": 0.0, "b": 0.0}},
        },
        connections={
            "c1": {"fromNodeId": "n_a", "fromPin": "value", "toNodeId": "n_add", "toPin": "a"},
            "c2": {"fromNodeId": "n_b", "fromPin": "value", "toNodeId": "n_add", "toPin": "b"},
        },
    )
    assert result["ok"] is True
    add_res = result["node_results"]["n_add"]
    assert add_res["ok"] is True
    assert add_res["output"] == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# 4. Mesh sphere
# ---------------------------------------------------------------------------

def test_mesh_sphere_node():
    result = call(
        nodes={"s": {"defId": "mesh_sphere", "params": {"radius": 2.0, "segments": 8, "rings": 4}}},
        connections={},
    )
    assert result["ok"] is True
    out = result["node_results"]["s"]["output"]
    assert out["type"] == "mesh_sphere"
    assert out["radius"] == pytest.approx(2.0)
    assert out["vertex_count"] > 0
    assert out["face_count"] > 0


# ---------------------------------------------------------------------------
# 5. Mesh cylinder
# ---------------------------------------------------------------------------

def test_mesh_cylinder_node():
    result = call(
        nodes={"c": {"defId": "mesh_cylinder", "params": {"radius": 1.0, "height": 3.0, "segments": 6}}},
        connections={},
    )
    assert result["ok"] is True
    out = result["node_results"]["c"]["output"]
    assert out["type"] == "mesh_cylinder"
    assert out["height"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# 6. Mesh torus
# ---------------------------------------------------------------------------

def test_mesh_torus_node():
    result = call(
        nodes={"t": {"defId": "mesh_torus", "params": {"major_radius": 2.0, "minor_radius": 0.5,
                                                        "major_segments": 8, "minor_segments": 4}}},
        connections={},
    )
    assert result["ok"] is True
    out = result["node_results"]["t"]["output"]
    assert out["type"] == "mesh_torus"
    assert out["major_radius"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# 7. Disabled node is skipped
# ---------------------------------------------------------------------------

def test_disabled_node_skipped():
    result = call(
        nodes={
            "active": {"defId": "number", "params": {"value": 7.0}},
            "dead":   {"defId": "number", "params": {"value": 99.0}, "disabled": True},
        },
        connections={},
    )
    assert result["ok"] is True
    assert "active" in result["node_results"]
    assert "dead" not in result["node_results"]
    assert result["n_nodes"] == 1


# ---------------------------------------------------------------------------
# 8. Cycle detection
# ---------------------------------------------------------------------------

def test_cycle_detection():
    result = call(
        nodes={
            "n1": {"defId": "add", "params": {"a": 0, "b": 0}},
            "n2": {"defId": "add", "params": {"a": 0, "b": 0}},
        },
        connections={
            "c1": {"fromNodeId": "n1", "fromPin": "result", "toNodeId": "n2", "toPin": "a"},
            "c2": {"fromNodeId": "n2", "fromPin": "result", "toNodeId": "n1", "toPin": "b"},
        },
    )
    # err_payload returns {"error": ..., "code": ...}
    assert "cycle" in result.get("error", "").lower() or result.get("code", "") == "CYCLE_ERROR"


# ---------------------------------------------------------------------------
# 9. Bad JSON
# ---------------------------------------------------------------------------

def test_bad_json():
    raw = run(run_geometry_nodes_evaluate_graph(_CTX, b"NOT_JSON"))
    result = json.loads(raw)
    # err_payload returns {"error": ..., "code": ...}
    assert "error" in result


# ---------------------------------------------------------------------------
# 10. Wrong arg types
# ---------------------------------------------------------------------------

def test_wrong_types():
    raw = run(run_geometry_nodes_evaluate_graph(_CTX, json.dumps({"nodes": "bad", "connections": {}}).encode()))
    result = json.loads(raw)
    assert "error" in result


# ---------------------------------------------------------------------------
# 11. Topological order: add depends on two numbers
# ---------------------------------------------------------------------------

def test_topo_order():
    result = call(
        nodes={
            "n1": {"defId": "number", "params": {"value": 1.0}},
            "n2": {"defId": "number", "params": {"value": 2.0}},
            "n3": {"defId": "add", "params": {"a": 0.0, "b": 0.0}},
        },
        connections={
            "c1": {"fromNodeId": "n1", "fromPin": "value", "toNodeId": "n3", "toPin": "a"},
            "c2": {"fromNodeId": "n2", "fromPin": "value", "toNodeId": "n3", "toPin": "b"},
        },
    )
    assert result["ok"] is True
    order = result["node_order"]
    # n3 must come after n1 and n2
    assert order.index("n3") > order.index("n1")
    assert order.index("n3") > order.index("n2")
    assert result["node_results"]["n3"]["output"] == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# 12. Unknown node type — graceful (not a crash)
# ---------------------------------------------------------------------------

def test_unknown_node_type():
    result = call(
        nodes={"u": {"defId": "totally_unknown_xyz", "params": {}}},
        connections={},
    )
    assert result["ok"] is True
    nr = result["node_results"]["u"]
    # Either ok:true with partial output, or ok:false with reason — but no exception
    assert "ok" in nr


# ---------------------------------------------------------------------------
# 13. Multiply node
# ---------------------------------------------------------------------------

def test_multiply_chain():
    result = call(
        nodes={
            "n1": {"defId": "number", "params": {"value": 4.0}},
            "n2": {"defId": "number", "params": {"value": 3.0}},
            "mul": {"defId": "multiply", "params": {"a": 1.0, "b": 1.0}},
        },
        connections={
            "c1": {"fromNodeId": "n1", "fromPin": "value", "toNodeId": "mul", "toPin": "a"},
            "c2": {"fromNodeId": "n2", "fromPin": "value", "toNodeId": "mul", "toPin": "b"},
        },
    )
    assert result["ok"] is True
    assert result["node_results"]["mul"]["output"] == pytest.approx(12.0)
