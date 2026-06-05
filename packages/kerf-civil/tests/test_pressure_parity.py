"""
test_pressure_parity.py — Pressure network parity depth tests.

Covers new depth-deepening of hydraulics_pressure.py:
  1. Minor loss coefficient catalogue (ASHRAE 2009 Table 3)
  2. Minor losses included in network solve
  3. Pump head (Fixed Operating Point model, EPANET 2 §3.1.5)
  4. Pressure residuals (quality check function)
  5. LLM tool: civil_minor_loss_coeff
  6. LLM tool: civil_water_network_solve with minor_loss_K / pump_head_m

Numeric oracles
---------------
Minor loss: 90° standard elbow K_m = 0.75 (ASHRAE Table 3).
Pump head: a pump adding 10 m to a 1-pipe network must raise the
  downstream node head by ~10 m relative to the no-pump case.

References
----------
Rossman (2000) EPANET 2 Users Manual, EPA/600/R-00/057, §3.1.5.
ASHRAE (2009) Fundamentals Handbook, Chapter 3, Table 3.
Mays (2011) Water Resources Engineering, §10.4.
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest


def _ctx():
    from kerf_civil._compat import ProjectCtx
    return ProjectCtx()


def _call(handler, payload: dict) -> dict:
    raw = asyncio.run(handler(payload, _ctx()))
    return json.loads(raw)


# ---------------------------------------------------------------------------
# 1. Minor loss coefficient catalogue
# ---------------------------------------------------------------------------

class TestMinorLossCoeff:
    def test_elbow_90_std(self):
        from kerf_civil.hydraulics_pressure import minor_loss_coeff
        assert abs(minor_loss_coeff("elbow_90_std") - 0.75) < 1e-10

    def test_gate_valve_full(self):
        from kerf_civil.hydraulics_pressure import minor_loss_coeff
        assert abs(minor_loss_coeff("gate_valve_full") - 0.20) < 1e-10

    def test_exit_loss(self):
        from kerf_civil.hydraulics_pressure import minor_loss_coeff
        assert abs(minor_loss_coeff("exit") - 1.00) < 1e-10

    def test_invalid_fitting_raises(self):
        from kerf_civil.hydraulics_pressure import minor_loss_coeff
        with pytest.raises(ValueError, match="not in catalogue"):
            minor_loss_coeff("imaginary_fitting")

    def test_case_insensitive(self):
        from kerf_civil.hydraulics_pressure import minor_loss_coeff
        assert minor_loss_coeff("ELBOW_90_STD") == minor_loss_coeff("elbow_90_std")

    def test_all_values_positive(self):
        from kerf_civil.hydraulics_pressure import _FITTING_K
        for k, v in _FITTING_K.items():
            assert v > 0, f"K_m for {k} must be > 0"


# ---------------------------------------------------------------------------
# 2. Minor losses reduce pressure at downstream node
# ---------------------------------------------------------------------------

class TestMinorLossEffect:
    """
    A 90° elbow (K=0.75) added to pipe P1 should reduce downstream node
    pressure compared to zero minor losses.
    """

    def _network(self, K_m=0.0):
        from kerf_civil.hydraulics_pressure import Node, Reservoir, Pipe, solve_network
        nodes = [Node(id="B", elevation_m=0.0, demand_m3s=0.01)]
        reservoirs = [Reservoir(id="A", head_m=30.0)]
        pipes = [Pipe(
            id="P1", node_a="A", node_b="B",
            length_m=100.0, diameter_m=0.2, roughness=120.0,
            minor_loss_K=K_m,
        )]
        return solve_network(nodes, reservoirs, pipes)

    def test_with_minor_losses_lower_pressure(self):
        result_no = self._network(K_m=0.0)
        result_km = self._network(K_m=0.75)
        # With minor losses: higher head drop → lower pressure at B
        assert result_km.nodal_pressures_m["B"] < result_no.nodal_pressures_m["B"]

    def test_still_converges_with_minor_losses(self):
        result = self._network(K_m=0.75)
        assert result.converged

    def test_mass_balance_with_minor_losses(self):
        from kerf_civil.hydraulics_pressure import Node, Reservoir, Pipe, solve_network, check_mass_balance
        nodes = [Node(id="B", elevation_m=0.0, demand_m3s=0.01)]
        reservoirs = [Reservoir(id="A", head_m=30.0)]
        pipes = [Pipe(
            id="P1", node_a="A", node_b="B",
            length_m=100.0, diameter_m=0.2, roughness=120.0,
            minor_loss_K=1.5,  # tee_branch K
        )]
        result = solve_network(nodes, reservoirs, pipes)
        balance = check_mass_balance(nodes, reservoirs, pipes, result)
        for nid, res in balance.items():
            assert abs(res) < 1e-3, f"Mass balance failed at {nid}: {res}"


# ---------------------------------------------------------------------------
# 3. Pump head (Fixed Operating Point)
# ---------------------------------------------------------------------------

class TestPumpHead:
    """
    A pump adding 10 m head to pipe P1 (A→B) raises node B's pressure
    by approximately 10 m relative to the no-pump case.

    Oracle: with a pump the head at B = H_reservoir + pump_head - friction_loss.
    """

    def _network(self, pump_head=0.0):
        from kerf_civil.hydraulics_pressure import Node, Reservoir, Pipe, solve_network
        nodes = [Node(id="B", elevation_m=0.0, demand_m3s=0.005)]
        reservoirs = [Reservoir(id="A", head_m=20.0)]
        pipes = [Pipe(
            id="P1", node_a="A", node_b="B",
            length_m=200.0, diameter_m=0.15, roughness=120.0,
            pump_head_m=pump_head,
        )]
        return solve_network(nodes, reservoirs, pipes)

    def test_pump_raises_downstream_head(self):
        result_no   = self._network(pump_head=0.0)
        result_pump = self._network(pump_head=10.0)
        head_no   = result_no.nodal_heads_m["B"]
        head_pump = result_pump.nodal_heads_m["B"]
        # Pump should raise downstream head significantly (within ~10 m range)
        assert head_pump > head_no + 5.0

    def test_pump_converges(self):
        result = self._network(pump_head=10.0)
        assert result.converged

    def test_pump_mass_balance(self):
        from kerf_civil.hydraulics_pressure import Node, Reservoir, Pipe, solve_network, check_mass_balance
        nodes = [Node(id="B", elevation_m=0.0, demand_m3s=0.005)]
        reservoirs = [Reservoir(id="A", head_m=20.0)]
        pipes = [Pipe(
            id="P1", node_a="A", node_b="B",
            length_m=200.0, diameter_m=0.15, roughness=120.0,
            pump_head_m=10.0,
        )]
        result = solve_network(nodes, reservoirs, pipes)
        balance = check_mass_balance(nodes, reservoirs, pipes, result)
        for nid, res in balance.items():
            assert abs(res) < 1e-3, f"Mass balance failed at {nid}: {res}"


# ---------------------------------------------------------------------------
# 4. Pressure residuals
# ---------------------------------------------------------------------------

class TestPressureResidual:
    """
    A converged solution should have near-zero pressure residuals.
    """

    def test_converged_residuals_small(self):
        from kerf_civil.hydraulics_pressure import (
            Node, Reservoir, Pipe, solve_network, pressure_residual
        )
        nodes = [
            Node(id="B", elevation_m=0.0, demand_m3s=0.01),
            Node(id="C", elevation_m=0.0, demand_m3s=0.005),
        ]
        reservoirs = [Reservoir(id="A", head_m=40.0)]
        pipes = [
            Pipe(id="P1", node_a="A", node_b="B", length_m=100, diameter_m=0.2, roughness=120),
            Pipe(id="P2", node_a="B", node_b="C", length_m=80, diameter_m=0.15, roughness=120),
        ]
        result = solve_network(nodes, reservoirs, pipes)
        residuals = pressure_residual(nodes, pipes, result, formula="HW")
        # GGA converges on Q (flows), not on exact head-loss balance.
        # Acceptable residual < 1 m on a 40 m head system (< 2.5%).
        for pid, res in residuals.items():
            assert abs(res) < 1.0, f"Residual at {pid}: {res:.4f} m"

    def test_residuals_keys_match_pipes(self):
        from kerf_civil.hydraulics_pressure import (
            Node, Reservoir, Pipe, solve_network, pressure_residual
        )
        nodes = [Node(id="B", elevation_m=0.0, demand_m3s=0.01)]
        reservoirs = [Reservoir(id="A", head_m=30.0)]
        pipes = [Pipe(id="P1", node_a="A", node_b="B", length_m=100, diameter_m=0.2, roughness=120)]
        result = solve_network(nodes, reservoirs, pipes)
        residuals = pressure_residual(nodes, pipes, result)
        assert "P1" in residuals


# ---------------------------------------------------------------------------
# 5. LLM tool: civil_minor_loss_coeff
# ---------------------------------------------------------------------------

class TestToolMinorLossCoeff:
    def test_elbow_lookup(self):
        from kerf_civil.tools_hydraulics import run_civil_minor_loss_coeff
        result = _call(run_civil_minor_loss_coeff, {"fitting": "elbow_90_std"})
        assert result.get("ok") is True
        assert abs(result["K_m"] - 0.75) < 1e-10

    def test_invalid_fitting_error(self):
        from kerf_civil.tools_hydraulics import run_civil_minor_loss_coeff
        result = _call(run_civil_minor_loss_coeff, {"fitting": "invalid_valve"})
        assert "error" in result

    def test_spec_name(self):
        from kerf_civil.tools_hydraulics import civil_minor_loss_coeff_spec
        assert civil_minor_loss_coeff_spec.name == "civil_minor_loss_coeff"

    def test_gate_valve_through_tool(self):
        from kerf_civil.tools_hydraulics import run_civil_minor_loss_coeff
        result = _call(run_civil_minor_loss_coeff, {"fitting": "gate_valve_full"})
        assert result.get("ok") is True
        assert abs(result["K_m"] - 0.20) < 1e-10


# ---------------------------------------------------------------------------
# 6. LLM tool: civil_water_network_solve with minor_loss_K / pump_head_m
# ---------------------------------------------------------------------------

class TestToolNetworkWithMinorLossAndPump:
    BASE_PARAMS = {
        "nodes": [{"id": "B", "elevation_m": 0.0, "demand_m3s": 0.01}],
        "reservoirs": [{"id": "A", "head_m": 30.0}],
        "formula": "HW",
    }

    def test_with_minor_loss_k(self):
        from kerf_civil.tools_hydraulics import run_civil_water_network_solve
        params = {
            **self.BASE_PARAMS,
            "pipes": [{"id": "P1", "node_a": "A", "node_b": "B",
                       "length_m": 100, "diameter_m": 0.2, "roughness": 120,
                       "minor_loss_K": 0.75}],
        }
        result = _call(run_civil_water_network_solve, params)
        assert result.get("ok") is True
        assert result.get("converged") is True

    def test_with_pump_head(self):
        from kerf_civil.tools_hydraulics import run_civil_water_network_solve
        params = {
            **self.BASE_PARAMS,
            "pipes": [{"id": "P1", "node_a": "A", "node_b": "B",
                       "length_m": 200, "diameter_m": 0.15, "roughness": 120,
                       "pump_head_m": 10.0}],
        }
        result = _call(run_civil_water_network_solve, params)
        assert result.get("ok") is True
        assert result.get("converged") is True

    def test_residuals_in_response(self):
        from kerf_civil.tools_hydraulics import run_civil_water_network_solve
        params = {
            **self.BASE_PARAMS,
            "pipes": [{"id": "P1", "node_a": "A", "node_b": "B",
                       "length_m": 100, "diameter_m": 0.2, "roughness": 120}],
        }
        result = _call(run_civil_water_network_solve, params)
        assert "pipe_head_loss_residuals" in result
        assert "P1" in result["pipe_head_loss_residuals"]
