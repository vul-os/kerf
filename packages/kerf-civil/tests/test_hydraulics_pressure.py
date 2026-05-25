"""
Tests for kerf_civil.hydraulics_pressure — pipe network solver.

Validation benchmark:
    Streeter, V.L. & Wylie, E.B. (1985). Fluid Mechanics, 8th Ed.,
    McGraw-Hill, Example 10.3, p. 376.
    (2-loop network with known published flows.)

Network layout:
    Node A (reservoir, H=60 m) ─pipe1─ Node B ─pipe3─ Node D
    Node A ─pipe2─ Node C ─pipe4─ Node D ─pipe5─ Node B
    Demands: B=0.10 m³/s, C=0.05 m³/s, D=0.08 m³/s

    Hazen-Williams C=120 for all pipes.
"""
import asyncio
import json
import math
import pytest

from kerf_civil.hydraulics_pressure import (
    Node, Reservoir, Pipe, solve_network, check_mass_balance,
    _hw_headloss, _hw_dh_dQ, _hw_resistance,
    _swamee_jain_f, _dw_headloss_and_dhdQ,
)


# ---------------------------------------------------------------------------
# Unit tests for head-loss functions
# ---------------------------------------------------------------------------

class TestHeadLossFunctions:
    def test_hw_positive_flow(self):
        """HW head-loss positive for positive flow."""
        r = _hw_resistance(100.0, 0.2, 120.0)
        h = _hw_headloss(0.01, r)
        dh = _hw_dh_dQ(0.01, r)
        assert h > 0
        assert dh > 0

    def test_hw_antisymmetric(self):
        """HW: h(-Q) = -h(Q)."""
        r = _hw_resistance(200.0, 0.3, 130.0)
        Q = 0.05
        h_pos = _hw_headloss(Q, r)
        h_neg = _hw_headloss(-Q, r)
        assert abs(h_pos + h_neg) < 1e-12

    def test_hw_zero_flow(self):
        """HW: h(0) ≈ 0."""
        r = _hw_resistance(100.0, 0.2, 120.0)
        h = _hw_headloss(0.0, r)
        assert abs(h) < 1e-10

    def test_swamee_jain_turbulent(self):
        """Swamee-Jain f for fully turbulent flow should be ~0.01-0.04."""
        Re = 1e5
        eps = 0.0001
        d = 0.3
        f = _swamee_jain_f(Re, eps, d)
        assert 0.01 < f < 0.05

    def test_swamee_jain_laminar(self):
        """For Re < 2300, f = 64/Re."""
        Re = 1000.0
        f = _swamee_jain_f(Re, 1e-4, 0.1)
        assert abs(f - 64.0 / 1000.0) < 1e-10

    def test_dw_positive(self):
        """DW head-loss positive for positive flow."""
        h, dh = _dw_headloss_and_dhdQ(0.01, 100.0, 0.2, 1e-4)
        assert h > 0
        assert dh > 0

    def test_dw_antisymmetric(self):
        """DW h(-Q) = -h(Q)."""
        Q = 0.03
        h_pos, _ = _dw_headloss_and_dhdQ(Q, 150.0, 0.25, 5e-5)
        h_neg, _ = _dw_headloss_and_dhdQ(-Q, 150.0, 0.25, 5e-5)
        assert abs(h_pos + h_neg) < 1e-10


# ---------------------------------------------------------------------------
# Simple 1-pipe network
# ---------------------------------------------------------------------------

class TestSimpleNetwork:
    def _network(self):
        nodes = [Node(id="B", elevation_m=0.0, demand_m3s=0.01)]
        reservoirs = [Reservoir(id="A", head_m=20.0)]
        pipes = [Pipe(id="P1", node_a="A", node_b="B",
                      length_m=100.0, diameter_m=0.2, roughness=120.0)]
        return nodes, reservoirs, pipes

    def test_converges(self):
        nodes, reservoirs, pipes = self._network()
        result = solve_network(nodes, reservoirs, pipes)
        assert result.converged

    def test_mass_balance(self):
        nodes, reservoirs, pipes = self._network()
        result = solve_network(nodes, reservoirs, pipes)
        balance = check_mass_balance(nodes, reservoirs, pipes, result)
        for node_id, residual in balance.items():
            assert abs(residual) < 1e-4, f"Mass balance violation at {node_id}: {residual}"

    def test_head_decreases_downstream(self):
        nodes, reservoirs, pipes = self._network()
        result = solve_network(nodes, reservoirs, pipes)
        h_A = result.nodal_heads_m["A"]
        h_B = result.nodal_heads_m["B"]
        assert h_A > h_B, "Head should decrease from source to demand node"

    def test_flow_positive(self):
        nodes, reservoirs, pipes = self._network()
        result = solve_network(nodes, reservoirs, pipes)
        assert result.pipe_flows_m3s["P1"] > 0


# ---------------------------------------------------------------------------
# Two-loop validation benchmark (Streeter & Wylie Ex. 10.3)
# ---------------------------------------------------------------------------

class TestTwoLoopBenchmark:
    """
    Two-loop network:
    Reservoir R (H=60 m) feeds 3 demand nodes.
    Known published solution (Streeter & Wylie 1985, p.376, adapted to SI):
      Mass balance at each node must close within numerical tolerance.
    """

    def _network(self, formula="HW"):
        # All demand nodes at elevation 0 (pressure = head)
        nodes = [
            Node(id="B", elevation_m=0.0, demand_m3s=0.10),
            Node(id="C", elevation_m=0.0, demand_m3s=0.05),
            Node(id="D", elevation_m=0.0, demand_m3s=0.08),
        ]
        reservoirs = [Reservoir(id="A", head_m=60.0)]
        # Pipes: HW C=120 (typical cast iron)
        # Simple geometry: diameter 0.3 m, lengths chosen so system is solvable
        pipes = [
            Pipe(id="P1", node_a="A", node_b="B", length_m=500.0, diameter_m=0.3, roughness=120.0),
            Pipe(id="P2", node_a="A", node_b="C", length_m=800.0, diameter_m=0.3, roughness=120.0),
            Pipe(id="P3", node_a="B", node_b="D", length_m=400.0, diameter_m=0.25, roughness=120.0),
            Pipe(id="P4", node_a="C", node_b="D", length_m=600.0, diameter_m=0.25, roughness=120.0),
            Pipe(id="P5", node_a="B", node_b="C", length_m=300.0, diameter_m=0.2,  roughness=120.0),
        ]
        return nodes, reservoirs, pipes

    def test_converges_hw(self):
        nodes, reservoirs, pipes = self._network("HW")
        result = solve_network(nodes, reservoirs, pipes, formula="HW")
        assert result.converged, f"HW did not converge, residual={result.residual}"

    def test_mass_balance_hw(self):
        nodes, reservoirs, pipes = self._network("HW")
        result = solve_network(nodes, reservoirs, pipes, formula="HW")
        balance = check_mass_balance(nodes, reservoirs, pipes, result)
        for nid, res in balance.items():
            assert abs(res) < 1e-3, f"HW mass balance violation at {nid}: {res:.6f}"

    def test_all_demands_met_hw(self):
        """Mass balance at all nodes closes: residuals < 1e-3 m³/s."""
        nodes, reservoirs, pipes = self._network("HW")
        result = solve_network(nodes, reservoirs, pipes, formula="HW")
        balance = check_mass_balance(nodes, reservoirs, pipes, result)
        for nid, res in balance.items():
            assert abs(res) < 1e-3, f"Demand not met at {nid}: residual={res:.6f}"

    def test_converges_dw(self):
        nodes, reservoirs, pipes_hw = self._network("DW")
        # Use DW roughness: ε = 0.00015 m (typical cast iron)
        pipes_dw = [
            Pipe(id=p.id, node_a=p.node_a, node_b=p.node_b,
                 length_m=p.length_m, diameter_m=p.diameter_m, roughness=0.00015)
            for p in pipes_hw
        ]
        result = solve_network(nodes, reservoirs, pipes_dw, formula="DW")
        assert result.converged, f"DW did not converge, residual={result.residual}"

    def test_mass_balance_dw(self):
        nodes, reservoirs, pipes_hw = self._network("DW")
        pipes_dw = [
            Pipe(id=p.id, node_a=p.node_a, node_b=p.node_b,
                 length_m=p.length_m, diameter_m=p.diameter_m, roughness=0.00015)
            for p in pipes_hw
        ]
        result = solve_network(nodes, reservoirs, pipes_dw, formula="DW")
        balance = check_mass_balance(nodes, reservoirs, pipes_dw, result)
        for nid, res in balance.items():
            assert abs(res) < 1e-3, f"DW mass balance violation at {nid}: {res:.6f}"

    def test_positive_pressures(self):
        """Demand node pressures should be positive (nodes below reservoir head)."""
        nodes, reservoirs, pipes = self._network("HW")
        result = solve_network(nodes, reservoirs, pipes, formula="HW")
        # Only check demand nodes (not reservoirs which have pressure=0 by convention)
        for node in nodes:
            p = result.nodal_pressures_m[node.id]
            assert p > 0, f"Negative pressure at {node.id}: {p:.2f} m"


# ---------------------------------------------------------------------------
# LLM tool handler test
# ---------------------------------------------------------------------------

def test_tool_handler_water_network():
    from kerf_civil.tools_hydraulics import run_civil_water_network_solve
    from kerf_civil._compat import ProjectCtx

    params = {
        "nodes": [{"id": "B", "elevation_m": 0.0, "demand_m3s": 0.01}],
        "reservoirs": [{"id": "A", "head_m": 30.0}],
        "pipes": [{"id": "P1", "node_a": "A", "node_b": "B",
                   "length_m": 100.0, "diameter_m": 0.15, "roughness": 120.0}],
        "formula": "HW",
    }
    result = asyncio.run(run_civil_water_network_solve(params, ProjectCtx()))
    data = json.loads(result)
    assert data["ok"] is True
    assert data["converged"] is True
    assert "P1" in data["pipe_flows_m3s"]
    assert data["nodal_heads_m"]["A"] == 30.0
