"""
Tests for kerf_electronics.power.ac_load_flow

Coverage:
  PowerBus / PowerLine / PowerSystem construction
  build_y_bus — Y-bus structure and values
  newton_raphson_load_flow — convergence, voltage profiles, power balance
  3-bus system (slack + PV + PQ)
  load_flow_tools — handler wrappers

References: Stevenson (1982); Grainger-Stevenson (1994).
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from kerf_electronics.power.ac_load_flow import (
    PowerBus,
    PowerLine,
    PowerSystem,
    build_y_bus,
)
from kerf_electronics.power.load_flow_tools import (
    _handle_power_build_y_bus,
    _handle_power_ac_load_flow,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _simple_2bus() -> PowerSystem:
    """2-bus system: slack (B1) feeding a PQ load (B2)."""
    buses = [
        PowerBus("B1", "slack", 0.0, 0.0, V_specified_pu=1.0, angle_deg=0.0),
        PowerBus("B2", "PQ", -50.0, -20.0, V_specified_pu=1.0, angle_deg=0.0),
    ]
    lines = [
        PowerLine("L1", "B1", "B2", R_pu=0.02, X_pu=0.10, B_pu=0.0),
    ]
    return PowerSystem(buses=buses, lines=lines, base_mva=100.0)


def _3bus_system() -> PowerSystem:
    """
    Standard 3-bus test system:
        B1: slack
        B2: PV (generator, 60 MW scheduled)
        B3: PQ (load, -80 MW, -30 Mvar)
    Two lines: B1-B2, B1-B3.
    """
    buses = [
        PowerBus("B1", "slack", 0.0, 0.0, V_specified_pu=1.05, angle_deg=0.0),
        PowerBus("B2", "PV", 60.0, 0.0, V_specified_pu=1.02, angle_deg=0.0),
        PowerBus("B3", "PQ", -80.0, -30.0, V_specified_pu=1.0, angle_deg=0.0),
    ]
    lines = [
        PowerLine("L12", "B1", "B2", R_pu=0.01, X_pu=0.05, B_pu=0.04),
        PowerLine("L13", "B1", "B3", R_pu=0.02, X_pu=0.08, B_pu=0.02),
        PowerLine("L23", "B2", "B3", R_pu=0.015, X_pu=0.06, B_pu=0.02),
    ]
    return PowerSystem(buses=buses, lines=lines, base_mva=100.0)


# ---------------------------------------------------------------------------
# 1. PowerBus / PowerLine / PowerSystem construction
# ---------------------------------------------------------------------------

class TestConstruction:
    def test_powerbus_valid(self):
        bus = PowerBus("B1", "slack", 0.0, 0.0)
        assert bus.bus_id == "B1"
        assert bus.bus_type == "slack"

    def test_powerbus_invalid_type(self):
        with pytest.raises(ValueError):
            PowerBus("B1", "generator", 0.0, 0.0)

    def test_powerline_basic(self):
        line = PowerLine("L1", "B1", "B2", R_pu=0.01, X_pu=0.05)
        assert line.B_pu == 0.0

    def test_powersystem_base_mva(self):
        system = _2bus_with_base()
        assert system.base_mva == 100.0

    def test_powersystem_bus_count(self):
        system = _3bus_system()
        assert len(system.buses) == 3
        assert len(system.lines) == 3


def _2bus_with_base() -> PowerSystem:
    buses = [
        PowerBus("B1", "slack", 0.0, 0.0),
        PowerBus("B2", "PQ", -50.0, -10.0),
    ]
    lines = [PowerLine("L1", "B1", "B2", 0.02, 0.10)]
    return PowerSystem(buses, lines, base_mva=100.0)


# ---------------------------------------------------------------------------
# 2. build_y_bus
# ---------------------------------------------------------------------------

class TestBuildYBus:
    def test_2bus_y_bus_shape(self):
        system = _simple_2bus()
        Y = build_y_bus(system)
        assert Y.shape == (2, 2)

    def test_y_bus_diagonal_positive_real(self):
        """Diagonal entries should have positive real parts (conductance)."""
        system = _simple_2bus()
        Y = build_y_bus(system)
        for i in range(2):
            assert Y[i, i].real > 0

    def test_y_bus_off_diagonal_negative(self):
        """Off-diagonal Y[i,j] = -y_series (negative of series admittance)."""
        system = _simple_2bus()
        Y = build_y_bus(system)
        # Y[0,1] = Y[1,0] and should be the negative of series admittance
        assert abs(Y[0, 1] - Y[1, 0]) < 1e-12  # symmetry
        assert Y[0, 1].real < 0  # negative real part

    def test_y_bus_symmetry(self):
        """Y-bus must be symmetric."""
        system = _3bus_system()
        Y = build_y_bus(system)
        assert np.allclose(Y, Y.T, atol=1e-10)

    def test_zero_impedance_raises(self):
        buses = [
            PowerBus("B1", "slack", 0.0, 0.0),
            PowerBus("B2", "PQ", -10.0, 0.0),
        ]
        lines = [PowerLine("L1", "B1", "B2", R_pu=0.0, X_pu=0.0)]
        system = PowerSystem(buses, lines)
        with pytest.raises(ValueError):
            build_y_bus(system)


# ---------------------------------------------------------------------------
# 3. Newton-Raphson load flow — 2-bus
# ---------------------------------------------------------------------------

class TestLoadFlow2Bus:
    def test_converges(self):
        result = _simple_2bus().newton_raphson_load_flow()
        assert result["converged"] is True

    def test_slack_voltage_fixed(self):
        """Slack bus voltage must remain at specified 1.0 pu."""
        result = _simple_2bus().newton_raphson_load_flow()
        V_slack, angle_slack = result["bus_voltages"]["B1"]
        assert abs(V_slack - 1.0) < 1e-6
        assert abs(angle_slack) < 1e-6

    def test_voltage_within_bounds(self):
        """Bus voltages should be in reasonable range [0.8, 1.2] pu."""
        result = _simple_2bus().newton_raphson_load_flow()
        for bid, (V, _) in result["bus_voltages"].items():
            assert 0.8 <= V <= 1.2, f"Bus {bid} V={V}"

    def test_line_flows_present(self):
        result = _simple_2bus().newton_raphson_load_flow()
        assert len(result["line_flows"]) == 1
        flow = result["line_flows"][0]
        assert "P_from_mw" in flow
        assert "Q_from_mvar" in flow


# ---------------------------------------------------------------------------
# 4. Newton-Raphson load flow — 3-bus
# ---------------------------------------------------------------------------

class TestLoadFlow3Bus:
    def test_converges(self):
        result = _3bus_system().newton_raphson_load_flow()
        assert result["converged"] is True, f"Did not converge: {result}"

    def test_iterations_reasonable(self):
        """N-R should converge within 10 iterations for well-conditioned system."""
        result = _3bus_system().newton_raphson_load_flow()
        assert result["iterations"] <= 10, f"Took {result['iterations']} iterations"

    def test_slack_voltage_held(self):
        """Slack bus B1 voltage = 1.05 pu (specified)."""
        result = _3bus_system().newton_raphson_load_flow()
        V_slack, _ = result["bus_voltages"]["B1"]
        assert abs(V_slack - 1.05) < 1e-4

    def test_power_balance_slack(self):
        """
        Active power balance: total generation (slack + PV) ≈ total load.
        Slack picks up the difference from losses.
        """
        result = _3bus_system().newton_raphson_load_flow()
        # PV generates 60 MW; PQ consumes 80 MW
        # Slack must supply ~20 MW + losses
        P_slack_mw = result["bus_powers"]["B1"]["P_mw"]
        P_pv_mw = result["bus_powers"]["B2"]["P_mw"]
        P_load_mw = result["bus_powers"]["B3"]["P_mw"]
        # Power balance: P_slack + P_pv + P_load ≈ 0 (net injections sum ~= losses)
        net = P_slack_mw + P_pv_mw + P_load_mw
        # Net should be small (system losses)
        assert abs(net) < 10.0, f"Power balance: {net:.2f} MW"

    def test_line_flows_3_lines(self):
        """3-bus system has 3 lines → 3 flow records."""
        result = _3bus_system().newton_raphson_load_flow()
        assert len(result["line_flows"]) == 3

    def test_pq_voltage_less_than_pv(self):
        """
        Under load, PQ bus voltage typically lower than PV bus voltage
        (PV bus holds voltage, PQ drops under load).
        """
        result = _3bus_system().newton_raphson_load_flow()
        V_pv, _ = result["bus_voltages"]["B2"]
        V_pq, _ = result["bus_voltages"]["B3"]
        assert V_pq < V_pv, f"V_PQ={V_pq:.4f} should be < V_PV={V_pv:.4f}"

    def test_no_slack_bus_returns_error(self):
        """System with no slack bus returns error dict."""
        buses = [
            PowerBus("B1", "PV", 50.0, 0.0),
            PowerBus("B2", "PQ", -50.0, -10.0),
        ]
        lines = [PowerLine("L1", "B1", "B2", 0.01, 0.05)]
        system = PowerSystem(buses, lines)
        result = system.newton_raphson_load_flow()
        assert result["converged"] is False


# ---------------------------------------------------------------------------
# 5. load_flow_tools handlers
# ---------------------------------------------------------------------------

class TestLoadFlowTools:
    def _3bus_payload(self) -> dict:
        return {
            "buses": [
                {"bus_id": "B1", "bus_type": "slack", "P_specified_mw": 0.0,
                 "Q_specified_mvar": 0.0, "V_specified_pu": 1.05, "angle_deg": 0.0},
                {"bus_id": "B2", "bus_type": "PV", "P_specified_mw": 60.0,
                 "Q_specified_mvar": 0.0, "V_specified_pu": 1.02, "angle_deg": 0.0},
                {"bus_id": "B3", "bus_type": "PQ", "P_specified_mw": -80.0,
                 "Q_specified_mvar": -30.0, "V_specified_pu": 1.0, "angle_deg": 0.0},
            ],
            "lines": [
                {"line_id": "L12", "from_bus": "B1", "to_bus": "B2",
                 "R_pu": 0.01, "X_pu": 0.05, "B_pu": 0.04},
                {"line_id": "L13", "from_bus": "B1", "to_bus": "B3",
                 "R_pu": 0.02, "X_pu": 0.08, "B_pu": 0.02},
                {"line_id": "L23", "from_bus": "B2", "to_bus": "B3",
                 "R_pu": 0.015, "X_pu": 0.06, "B_pu": 0.02},
            ],
            "base_mva": 100.0,
        }

    def test_y_bus_tool_ok(self):
        result = _handle_power_build_y_bus(self._3bus_payload())
        assert result["ok"] is True
        assert result["n_buses"] == 3

    def test_load_flow_tool_ok(self):
        result = _handle_power_ac_load_flow(self._3bus_payload())
        assert result["ok"] is True
        assert result["converged"] is True

    def test_load_flow_tool_missing_buses(self):
        result = _handle_power_ac_load_flow({"lines": []})
        # Should either fail gracefully or return empty system error
        assert "ok" in result

    def test_load_flow_tool_invalid_bus_type(self):
        payload = self._3bus_payload()
        payload["buses"][0]["bus_type"] = "generator"
        result = _handle_power_ac_load_flow(payload)
        assert result["ok"] is False
