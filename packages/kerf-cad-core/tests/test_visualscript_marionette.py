"""
Hermetic tests for kerf_cad_core.visualscript.marionette
(Vectorworks Marionette / MatrixGold visual scripting engine).

Coverage (≥20 tests):
  MarionetteGraph.topological_order
    - Linear chain A→B→C returns correct order
    - Disconnected node has no ordering constraint (still in result)
    - Cycle detection raises ValueError with cyclic node IDs
    - Single-node graph returns that node
    - Diamond graph (shared predecessor) evaluates in valid order
  evaluate_marionette_graph
    - 3-node pipeline "wall → window → material" returns final geometry
    - Disconnected node has outputs from its default handler (empty inputs)
    - Custom node_handler overrides built-in
    - Node with unknown type receives pass-through warning in output
    - Connections correctly route upstream outputs to downstream inputs
    - Multiple connections into same node (fan-in) all resolve
  Built-in handlers
    - handler_create_wall produces geometry with correct volume
    - handler_create_floor produces geometry with correct area
    - handler_array_along_curve linear produces correct count and positions
    - handler_array_along_curve radial produces evenly-spaced positions
    - handler_move records transform_move offset
    - handler_rotate records transform_rotate
    - handler_boolean_union records both operands
    - handler_truss_span computes span_m correctly for a known geometry

All tests are pure-Python and hermetic: no OCC, no DB, no network.

References
----------
Vectorworks Marionette — https://developer.vectorworks.net/marionette
MatrixGold Visual Scripting Guide, Gemvision 2022.
Kahn, A.B. (1962). CACM 5(11):558-562 (topological sort).

Author: imranparuk
"""
from __future__ import annotations

import math
from typing import Any, Dict

import pytest

from kerf_cad_core.visualscript.marionette import (
    MarionetteNode,
    MarionetteGraph,
    evaluate_marionette_graph,
    NODE_LIBRARY,
    handler_create_wall,
    handler_create_floor,
    handler_array_along_curve,
    handler_move,
    handler_rotate,
    handler_boolean_union,
    handler_truss_span,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node(nid: str, ntype: str, inputs: Dict[str, Any] = None) -> MarionetteNode:
    return MarionetteNode(node_id=nid, node_type=ntype, inputs=inputs or {})


def _conn(src_id, src_pin, dst_id, dst_pin):
    return (src_id, src_pin, dst_id, dst_pin)


# ===========================================================================
# 1. MarionetteGraph.topological_order
# ===========================================================================

class TestTopologicalOrder:

    def test_linear_chain(self):
        """A → B → C: topological order must have A before B before C."""
        g = MarionetteGraph(
            nodes=[_node("A", "wall"), _node("B", "window"), _node("C", "material")],
            connections=[_conn("A", "geometry", "B", "host_wall"),
                         _conn("B", "geometry", "C", "geometry")],
        )
        order = g.topological_order()
        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("C")

    def test_all_nodes_present_in_order(self):
        """Every node must appear exactly once in the topological order."""
        g = MarionetteGraph(
            nodes=[_node("A", "wall"), _node("B", "window"), _node("C", "material")],
            connections=[_conn("A", "geometry", "B", "host_wall")],
        )
        order = g.topological_order()
        assert set(order) == {"A", "B", "C"}
        assert len(order) == 3

    def test_disconnected_node_in_result(self):
        """Disconnected node with no connections appears in order (no constraint)."""
        g = MarionetteGraph(
            nodes=[_node("A", "wall"), _node("B", "floor")],  # no connections
            connections=[],
        )
        order = g.topological_order()
        assert "A" in order
        assert "B" in order

    def test_single_node(self):
        """Single-node graph returns a list with that single node_id."""
        g = MarionetteGraph(nodes=[_node("Solo", "wall")], connections=[])
        assert g.topological_order() == ["Solo"]

    def test_diamond_graph_valid_order(self):
        """Diamond: A → B, A → C, B → D, C → D. A before B and C; D last."""
        g = MarionetteGraph(
            nodes=[_node("A", "wall"), _node("B", "move"), _node("C", "rotate"), _node("D", "material")],
            connections=[
                _conn("A", "geometry", "B", "geometry"),
                _conn("A", "geometry", "C", "geometry"),
                _conn("B", "geometry", "D", "geometry"),
                _conn("C", "geometry", "D", "geometry"),
            ],
        )
        order = g.topological_order()
        assert order.index("A") < order.index("B")
        assert order.index("A") < order.index("C")
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")

    def test_cycle_raises_value_error(self):
        """A → B → A cycle must raise ValueError with cyclic node IDs."""
        g = MarionetteGraph(
            nodes=[_node("A", "wall"), _node("B", "window")],
            connections=[
                _conn("A", "geometry", "B", "host_wall"),
                _conn("B", "geometry", "A", "geometry"),  # creates cycle
            ],
        )
        with pytest.raises(ValueError, match="[Cc]ycle"):
            g.topological_order()

    def test_cycle_error_mentions_cyclic_nodes(self):
        """Cycle error message should include the cyclic node IDs."""
        g = MarionetteGraph(
            nodes=[_node("X", "wall"), _node("Y", "floor"), _node("Z", "column")],
            connections=[
                _conn("X", "geometry", "Y", "geometry"),
                _conn("Y", "geometry", "Z", "geometry"),
                _conn("Z", "geometry", "X", "geometry"),  # cycle
            ],
        )
        with pytest.raises(ValueError) as exc_info:
            g.topological_order()
        msg = str(exc_info.value)
        # All three nodes are in the cycle — at least one should be mentioned.
        assert any(nid in msg for nid in ("X", "Y", "Z"))


# ===========================================================================
# 2. evaluate_marionette_graph — pipeline tests
# ===========================================================================

class TestEvaluateGraph:

    def test_3node_pipeline_returns_results_for_all_nodes(self):
        """wall → window → material pipeline: results dict has all 3 node IDs."""
        g = MarionetteGraph(
            nodes=[
                _node("W", "wall", {"length": 5.0, "height": 3.0}),
                _node("Win", "window", {"width": 1.2, "height": 1.0}),
                _node("Mat", "material", {"material": "brick"}),
            ],
            connections=[
                _conn("W", "geometry", "Win", "host_wall"),
                _conn("Win", "geometry", "Mat", "geometry"),
            ],
        )
        results = evaluate_marionette_graph(g)
        assert set(results.keys()) == {"W", "Win", "Mat"}

    def test_3node_pipeline_final_node_has_geometry(self):
        """The final material node should have geometry in its outputs."""
        g = MarionetteGraph(
            nodes=[
                _node("W", "wall", {"length": 5.0, "height": 3.0}),
                _node("Win", "window", {"width": 1.2, "height": 1.0}),
                _node("Mat", "material", {"material": "brick"}),
            ],
            connections=[
                _conn("W", "geometry", "Win", "host_wall"),
                _conn("Win", "geometry", "Mat", "geometry"),
            ],
        )
        results = evaluate_marionette_graph(g)
        assert "geometry" in results["Mat"]["outputs"], (
            "Material node output must contain 'geometry'"
        )

    def test_connection_routes_value_correctly(self):
        """Output of wall node is routed to input of move node."""
        wall_node = _node("W", "wall", {"length": 4.0, "height": 2.7})
        move_node = _node("M", "move", {"vector": [1.0, 0.0, 0.0]})
        g = MarionetteGraph(
            nodes=[wall_node, move_node],
            connections=[_conn("W", "geometry", "M", "geometry")],
        )
        results = evaluate_marionette_graph(g)
        # Move node input 'geometry' should be the wall's geometry output.
        m_inputs = results["M"]["inputs"]
        assert "geometry" in m_inputs
        assert m_inputs["geometry"].get("type") == "wall"

    def test_disconnected_node_has_outputs(self):
        """A node with no connections still evaluates using its constant inputs."""
        g = MarionetteGraph(
            nodes=[_node("Standalone", "floor", {"width": 3.0, "length": 4.0})],
            connections=[],
        )
        results = evaluate_marionette_graph(g)
        assert "Standalone" in results
        assert "area_m2" in results["Standalone"]["outputs"]

    def test_unknown_node_type_gets_passthrough_warning(self):
        """Node with node_type not in NODE_LIBRARY gets a _warning in outputs."""
        g = MarionetteGraph(
            nodes=[_node("X", "nonexistent_type_xyz", {"foo": 42})],
            connections=[],
        )
        results = evaluate_marionette_graph(g)
        out = results["X"]["outputs"]
        assert "_warning" in out, "Unknown node type should produce _warning key"

    def test_custom_handler_overrides_builtin(self):
        """Custom handler passed as node_handlers should override built-in 'wall'."""
        def my_wall_handler(inputs: dict) -> dict:
            return {"custom_output": True, "length": inputs.get("length", 0)}

        g = MarionetteGraph(
            nodes=[_node("W", "wall", {"length": 5.0})],
            connections=[],
        )
        results = evaluate_marionette_graph(g, node_handlers={"wall": my_wall_handler})
        assert results["W"]["outputs"].get("custom_output") is True

    def test_cycle_raises_in_evaluate(self):
        """evaluate_marionette_graph re-raises ValueError on cycle."""
        g = MarionetteGraph(
            nodes=[_node("A", "wall"), _node("B", "floor")],
            connections=[
                _conn("A", "geometry", "B", "geometry"),
                _conn("B", "area_m2", "A", "height"),  # cycle
            ],
        )
        with pytest.raises(ValueError, match="[Cc]ycle"):
            evaluate_marionette_graph(g)

    def test_fan_in_multiple_connections_to_same_node(self):
        """Two upstream nodes each feeding a different pin of the same downstream node."""
        wall = _node("W", "wall", {"length": 4.0, "height": 2.7})
        floor = _node("F", "floor", {"width": 4.0, "length": 5.0})
        boolean = _node("B", "boolean_union")
        g = MarionetteGraph(
            nodes=[wall, floor, boolean],
            connections=[
                _conn("W", "geometry", "B", "geometry_a"),
                _conn("F", "geometry", "B", "geometry_b"),
            ],
        )
        results = evaluate_marionette_graph(g)
        b_inputs = results["B"]["inputs"]
        assert "geometry_a" in b_inputs
        assert "geometry_b" in b_inputs


# ===========================================================================
# 3. Built-in handler unit tests
# ===========================================================================

class TestBuiltinHandlers:

    def test_wall_volume(self):
        """Volume = length × height × thickness = 4×2.7×0.2 = 2.16 m³."""
        out = handler_create_wall({"length": 4.0, "height": 2.7, "thickness": 0.2})
        assert abs(out["volume_m3"] - 2.16) < 0.001

    def test_wall_area(self):
        """Face area = length × height = 4 × 2.7 = 10.8 m²."""
        out = handler_create_wall({"length": 4.0, "height": 2.7, "thickness": 0.2})
        assert abs(out["area_m2"] - 10.8) < 0.001

    def test_wall_end_pt_overrides_length(self):
        """When end_pt is provided, length is computed from start_pt to end_pt."""
        out = handler_create_wall({
            "start_pt": [0.0, 0.0, 0.0],
            "end_pt": [3.0, 4.0, 0.0],  # length = 5m (3-4-5 triangle)
        })
        assert abs(out["length"] - 5.0) < 0.001

    def test_floor_area(self):
        """Floor area = width × length = 5 × 4 = 20 m²."""
        out = handler_create_floor({"width": 5.0, "length": 4.0, "thickness": 0.15})
        assert abs(out["area_m2"] - 20.0) < 0.001

    def test_floor_volume(self):
        """Volume = 5 × 4 × 0.15 = 3.0 m³."""
        out = handler_create_floor({"width": 5.0, "length": 4.0, "thickness": 0.15})
        assert abs(out["volume_m3"] - 3.0) < 0.001

    def test_array_linear_count(self):
        """Linear array with count=6 should produce 6 instances."""
        out = handler_array_along_curve({
            "item": {"type": "column"},
            "count": 6,
            "spacing": 1.5,
            "mode": "linear",
        })
        assert out["count"] == 6
        assert len(out["instances"]) == 6

    def test_array_linear_positions(self):
        """First instance at origin; last at (count-1)×spacing along x-axis."""
        out = handler_array_along_curve({
            "item": {"type": "column"},
            "count": 4,
            "spacing": 2.0,
            "mode": "linear",
            "direction": [1.0, 0.0, 0.0],
        })
        first_pos = out["instances"][0]["position"]
        last_pos = out["instances"][3]["position"]
        assert abs(first_pos[0]) < 1e-9
        assert abs(last_pos[0] - 6.0) < 1e-6  # 3 × 2.0 = 6.0

    def test_array_radial_count_and_angles(self):
        """Radial array count=4 → 4 instances at 0°, 90°, 180°, 270°."""
        out = handler_array_along_curve({
            "item": {"type": "column"},
            "count": 4,
            "mode": "radial",
            "radius": 3.0,
            "start_angle": 0.0,
        })
        assert out["count"] == 4
        angles = [inst["angle_deg"] for inst in out["instances"]]
        expected = [0.0, 90.0, 180.0, 270.0]
        for a, e in zip(angles, expected):
            assert abs(a - e) < 1e-6

    def test_move_records_transform(self):
        """Move handler stores _transform_move in geometry output."""
        out = handler_move({"geometry": {"type": "wall"}, "vector": [1.0, 2.0, 0.0]})
        assert out["geometry"]["_transform_move"] == [1.0, 2.0, 0.0]

    def test_rotate_records_transform(self):
        """Rotate handler stores _transform_rotate with angle and axis."""
        out = handler_rotate({
            "geometry": {"type": "wall"},
            "angle_deg": 45.0,
            "axis": [0.0, 0.0, 1.0],
        })
        tr = out["geometry"]["_transform_rotate"]
        assert tr["angle_deg"] == 45.0
        assert tr["axis"] == [0.0, 0.0, 1.0]

    def test_boolean_union_both_operands_recorded(self):
        """Boolean union output records both operand geometries."""
        a = {"type": "wall"}
        b = {"type": "floor"}
        out = handler_boolean_union({"geometry_a": a, "geometry_b": b})
        assert out["geometry"]["type"] == "boolean_union"
        assert out["geometry"]["operand_a"] == a
        assert out["geometry"]["operand_b"] == b

    def test_truss_span_span_length(self):
        """Truss from [0,0,3] to [6,0,3]: span = 6m exactly."""
        out = handler_truss_span({
            "start_pt": [0.0, 0.0, 3.0],
            "end_pt": [6.0, 0.0, 3.0],
        })
        assert abs(out["span_m"] - 6.0) < 0.001

    def test_truss_span_diagonal(self):
        """Truss with 3-4-5 triangle profile: span = 5m."""
        out = handler_truss_span({
            "start_pt": [0.0, 0.0, 0.0],
            "end_pt": [3.0, 4.0, 0.0],
        })
        assert abs(out["span_m"] - 5.0) < 0.001

    def test_node_library_has_minimum_10_types(self):
        """NODE_LIBRARY must contain at least 10 built-in node types."""
        assert len(NODE_LIBRARY) >= 10
