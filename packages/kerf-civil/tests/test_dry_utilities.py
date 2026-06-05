"""
Tests for kerf_civil.dry_utilities — dry-utility network model, separation
checks, gas pressure drop, and electrical duct-fill.

Validation oracles
------------------
1. Weymouth pressure drop (monotonic with length and flow)
   - Longer pipe → larger dP (all else equal).
   - Higher flow → larger dP (all else equal).

2. Darcy-Weisbach (incompressible) pressure drop
   - dP ∝ L (linear); dP ∝ Q² (turbulent regime).

3. Separation violation detected
   - Gas link at corridor_offset = 0.0, electrical link at 0.1 m:
     separation = 0.1 m < 0.3 m required → violation.
   - Same pair at 0.4 m separation → no violation.

4. Cover depth violation
   - Gas link with depth_of_cover = 0.4 m < 0.6 m minimum → violation.
   - Gas link with 0.65 m → no violation.

5. Wet-utility separation violation
   - wet_utility_offset_m = 0.2 m < 0.3 m → violation.

6. Duct fill PASS / FAIL
   - 3 cables of 10 mm OD in 50 mm ID conduit:
     area_per = π*(5)² = 78.54 mm²; 3 × 78.54 = 235.6 mm²
     conduit = π*(25)² = 1963.5 mm²
     fill = 235.6 / 1963.5 = 12.0 % < 40 % → PASS
   - 3 cables of 25 mm OD in 50 mm ID conduit:
     area_per = π*(12.5)² = 490.87 mm²; 3 × 490.87 = 1472.6 mm²
     fill = 1472.6 / 1963.5 = 75.0 % > 40 % → FAIL

7. build_network round-trip: correct counts.

References
----------
Weymouth, T.R. (1912). Trans. ASME 34, 185–234.
Menon, E.S. (2005) Gas Pipeline Hydraulics, CRC Press.
Swamee & Jain (1976) J. Hydraulics Div. ASCE 102(5) 657–664.
ASME B31.8 §841.1; NEC Table 300.5; NEC Chapter 9 Table 1.
NFPA 54 §5.5.1; IGEM PL2; AWWA M23 §7.5.
"""
from __future__ import annotations

import asyncio
import json
import math
import pytest

from kerf_civil.dry_utilities import (
    build_network,
    check_corridor_clearances,
    gas_pressure_drop_weymouth,
    gas_pressure_drop_darcy,
    electrical_duct_fill_check,
    SEP_GAS_ELEC_M,
    MIN_COVER_GAS_M,
    MIN_COVER_ELEC_LV_M,
    SEP_DRY_WET_M,
    DryUtilityKind,
    ViolationType,
)


# ---------------------------------------------------------------------------
# Helper: minimal network fixture
# ---------------------------------------------------------------------------

def _two_node_network():
    nodes = [
        {"id": "N1", "x": 0.0, "y": 0.0, "z_surface_m": 10.0},
        {"id": "N2", "x": 100.0, "y": 0.0, "z_surface_m": 10.0},
    ]
    return nodes


# ---------------------------------------------------------------------------
# 1.  build_network round-trip
# ---------------------------------------------------------------------------

class TestBuildNetwork:
    def test_counts_gas(self):
        nodes = _two_node_network()
        links = [
            {
                "id": "G1",
                "node_from": "N1",
                "node_to": "N2",
                "length_m": 100.0,
                "depth_of_cover_m": 0.7,
                "corridor_offset_m": 1.0,
                "asset": {
                    "kind": "gas",
                    "diameter_mm": 100.0,
                    "material": "PE",
                    "mop_kPa": 200.0,
                },
            }
        ]
        net = build_network(nodes, links)
        assert len(net.nodes) == 2
        assert len(net.links) == 1
        assert net.links[0].asset.kind == DryUtilityKind.GAS.value

    def test_counts_mixed(self):
        nodes = _two_node_network()
        links = [
            {
                "id": "G1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100.0, "depth_of_cover_m": 0.7, "corridor_offset_m": 0.0,
                "asset": {"kind": "gas", "diameter_mm": 100, "material": "PE", "mop_kPa": 200},
            },
            {
                "id": "E1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100.0, "depth_of_cover_m": 0.55, "corridor_offset_m": 0.6,
                "asset": {"kind": "electrical", "conduit_id_mm": 100, "voltage_class": "LV"},
            },
            {
                "id": "T1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100.0, "depth_of_cover_m": 0.55, "corridor_offset_m": 1.5,
                "asset": {"kind": "telecom", "conduit_id_mm": 75, "n_conduits": 4},
            },
        ]
        net = build_network(nodes, links)
        assert len(net.links) == 3
        kinds = {lk.asset.kind for lk in net.links}
        assert kinds == {"gas", "electrical", "telecom"}

    def test_unknown_kind_raises(self):
        nodes = _two_node_network()
        links = [
            {
                "id": "X1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 50, "depth_of_cover_m": 0.6, "corridor_offset_m": 0.0,
                "asset": {"kind": "water", "diameter_mm": 100},
            }
        ]
        with pytest.raises(ValueError, match="Unknown asset kind"):
            build_network(nodes, links)


# ---------------------------------------------------------------------------
# 2.  Separation violations
# ---------------------------------------------------------------------------

class TestClearanceCheck:

    def _net_gas_elec(self, gas_offset: float, elec_offset: float,
                      gas_cover: float = 0.7, elec_cover: float = 0.55):
        nodes = _two_node_network()
        links = [
            {
                "id": "G1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100, "depth_of_cover_m": gas_cover,
                "corridor_offset_m": gas_offset,
                "asset": {"kind": "gas", "diameter_mm": 100, "material": "PE", "mop_kPa": 200},
            },
            {
                "id": "E1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100, "depth_of_cover_m": elec_cover,
                "corridor_offset_m": elec_offset,
                "asset": {"kind": "electrical", "conduit_id_mm": 100, "voltage_class": "LV"},
            },
        ]
        return build_network(nodes, links)

    def test_gas_elec_violation_detected(self):
        """gas at 0.0 m, elec at 0.1 m → sep = 0.1 m < 0.3 m required."""
        net = self._net_gas_elec(gas_offset=0.0, elec_offset=0.1)
        viols = check_corridor_clearances(net)
        inter = [v for v in viols if v["violation_type"] == ViolationType.INTER_UTILITY_SEP.value]
        assert len(inter) >= 1
        v = inter[0]
        assert v["required_m"] == pytest.approx(SEP_GAS_ELEC_M)
        assert v["actual_m"] == pytest.approx(0.1)
        assert v["deficit_m"] > 0

    def test_gas_elec_no_violation(self):
        """gas at 0.0 m, elec at 0.4 m → sep = 0.4 m >= 0.3 m → clear."""
        net = self._net_gas_elec(gas_offset=0.0, elec_offset=0.4)
        viols = check_corridor_clearances(net)
        inter = [v for v in viols if v["violation_type"] == ViolationType.INTER_UTILITY_SEP.value]
        assert len(inter) == 0

    def test_cover_depth_gas_violation(self):
        """Gas link with 0.4 m cover < 0.6 m required → cover violation."""
        nodes = _two_node_network()
        links = [
            {
                "id": "G1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100, "depth_of_cover_m": 0.4,
                "corridor_offset_m": 0.0,
                "asset": {"kind": "gas", "diameter_mm": 100, "material": "PE", "mop_kPa": 200},
            }
        ]
        net = build_network(nodes, links)
        viols = check_corridor_clearances(net)
        cover_viols = [v for v in viols if v["violation_type"] == ViolationType.COVER_DEPTH.value]
        assert len(cover_viols) >= 1
        assert cover_viols[0]["required_m"] == pytest.approx(MIN_COVER_GAS_M)

    def test_cover_depth_gas_ok(self):
        """Gas link with 0.65 m cover → no cover violation."""
        nodes = _two_node_network()
        links = [
            {
                "id": "G1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100, "depth_of_cover_m": 0.65,
                "corridor_offset_m": 0.0,
                "asset": {"kind": "gas", "diameter_mm": 100, "material": "PE", "mop_kPa": 200},
            }
        ]
        net = build_network(nodes, links)
        viols = check_corridor_clearances(net)
        cover_viols = [v for v in viols if v["violation_type"] == ViolationType.COVER_DEPTH.value]
        assert len(cover_viols) == 0

    def test_wet_utility_sep_violation(self):
        """Wet sep = 0.2 m < 0.3 m required → violation."""
        nodes = _two_node_network()
        links = [
            {
                "id": "G1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100, "depth_of_cover_m": 0.7,
                "corridor_offset_m": 0.0,
                "wet_utility_offset_m": 0.2,
                "asset": {"kind": "gas", "diameter_mm": 100, "material": "PE", "mop_kPa": 200},
            }
        ]
        net = build_network(nodes, links)
        viols = check_corridor_clearances(net)
        wet_viols = [v for v in viols if v["violation_type"] == ViolationType.WET_UTILITY_SEP.value]
        assert len(wet_viols) >= 1
        assert wet_viols[0]["required_m"] == pytest.approx(SEP_DRY_WET_M)

    def test_wet_utility_global_override(self):
        """Global wet offset 0.25 m < 0.3 m → violation via global param."""
        nodes = _two_node_network()
        links = [
            {
                "id": "T1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100, "depth_of_cover_m": 0.5,
                "corridor_offset_m": 0.0,
                "asset": {"kind": "telecom", "conduit_id_mm": 75},
            }
        ]
        net = build_network(nodes, links)
        viols = check_corridor_clearances(net, wet_utility_offset_m=0.25)
        wet_viols = [v for v in viols if v["violation_type"] == ViolationType.WET_UTILITY_SEP.value]
        assert len(wet_viols) >= 1

    def test_elec_lv_cover_violation(self):
        """Electrical LV with 0.35 m cover < 0.45 m required → violation."""
        nodes = _two_node_network()
        links = [
            {
                "id": "E1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100, "depth_of_cover_m": 0.35,
                "corridor_offset_m": 0.0,
                "asset": {"kind": "electrical", "conduit_id_mm": 100, "voltage_class": "LV"},
            }
        ]
        net = build_network(nodes, links)
        viols = check_corridor_clearances(net)
        cover_viols = [v for v in viols if v["violation_type"] == ViolationType.COVER_DEPTH.value]
        assert len(cover_viols) >= 1
        assert cover_viols[0]["required_m"] == pytest.approx(MIN_COVER_ELEC_LV_M)

    def test_elec_hv_cover_violation(self):
        """Electrical HV with 0.5 m cover < 0.6 m required → violation."""
        nodes = _two_node_network()
        links = [
            {
                "id": "E1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100, "depth_of_cover_m": 0.5,
                "corridor_offset_m": 0.0,
                "asset": {"kind": "electrical", "conduit_id_mm": 150, "voltage_class": "HV"},
            }
        ]
        net = build_network(nodes, links)
        viols = check_corridor_clearances(net)
        cover_viols = [v for v in viols if v["violation_type"] == ViolationType.COVER_DEPTH.value]
        assert len(cover_viols) >= 1
        # HV min cover = 0.6 m
        assert cover_viols[0]["required_m"] == pytest.approx(0.6)

    def test_no_violations_all_ok(self):
        """Well-separated, adequately covered utilities → zero violations."""
        nodes = _two_node_network()
        links = [
            {
                "id": "G1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100, "depth_of_cover_m": 0.7,
                "corridor_offset_m": 0.0,
                "wet_utility_offset_m": 0.5,
                "asset": {"kind": "gas", "diameter_mm": 100, "material": "PE", "mop_kPa": 200},
            },
            {
                "id": "E1",
                "node_from": "N1", "node_to": "N2",
                "length_m": 100, "depth_of_cover_m": 0.55,
                "corridor_offset_m": 0.5,
                "wet_utility_offset_m": 0.5,
                "asset": {"kind": "electrical", "conduit_id_mm": 100, "voltage_class": "LV"},
            },
        ]
        net = build_network(nodes, links)
        viols = check_corridor_clearances(net)
        assert viols == []


# ---------------------------------------------------------------------------
# 3.  Gas pressure drop — Weymouth
# ---------------------------------------------------------------------------

class TestGasPressureDropWeymouth:
    """
    Test parameters chosen so P2² stays positive (no capacity exhaustion).

    With Cw = 8.8538e-3, D = 0.1 m, P1 = 500 kPa, SG = 0.6, T = 288.15 K:
      Q_max at L=2000 m ≈ 1.6e-5 m³/s std.
      Using Q = 2e-6 m³/s std ensures P2² > 0 for L up to several km.
    """

    _Q  = 2e-6   # safe flow for test geometry
    _D  = 0.1
    _P1 = 500.0

    def test_zero_flow_no_drop(self):
        result = gas_pressure_drop_weymouth(Q_m3s=0.0, D_m=self._D, L_m=1000.0, P1_kPa=self._P1)
        assert result["ok"] is True
        assert result["dP_kPa"] == pytest.approx(0.0)

    def test_monotonic_with_length(self):
        """Longer pipe → greater pressure drop (all else equal)."""
        r1 = gas_pressure_drop_weymouth(Q_m3s=self._Q, D_m=self._D, L_m=500.0,  P1_kPa=self._P1)
        r2 = gas_pressure_drop_weymouth(Q_m3s=self._Q, D_m=self._D, L_m=2000.0, P1_kPa=self._P1)
        assert r1["ok"] and r2["ok"]
        assert r2["dP_kPa"] > r1["dP_kPa"]

    def test_monotonic_with_flow(self):
        """Higher flow rate → greater pressure drop (all else equal)."""
        r1 = gas_pressure_drop_weymouth(Q_m3s=1e-6, D_m=self._D, L_m=1000.0, P1_kPa=self._P1)
        r2 = gas_pressure_drop_weymouth(Q_m3s=3e-6, D_m=self._D, L_m=1000.0, P1_kPa=self._P1)
        assert r1["ok"] and r2["ok"]
        assert r2["dP_kPa"] > r1["dP_kPa"]

    def test_P2_less_than_P1(self):
        """Downstream pressure must be less than upstream when flow > 0."""
        result = gas_pressure_drop_weymouth(Q_m3s=self._Q, D_m=self._D, L_m=1000.0, P1_kPa=self._P1)
        assert result["P2_kPa"] < self._P1

    def test_negative_D_raises(self):
        with pytest.raises(ValueError, match="D_m"):
            gas_pressure_drop_weymouth(Q_m3s=self._Q, D_m=-0.1, L_m=100.0, P1_kPa=200.0)

    def test_negative_L_raises(self):
        with pytest.raises(ValueError, match="L_m"):
            gas_pressure_drop_weymouth(Q_m3s=self._Q, D_m=self._D, L_m=-100.0, P1_kPa=200.0)

    def test_negative_P1_raises(self):
        with pytest.raises(ValueError, match="P1_kPa"):
            gas_pressure_drop_weymouth(Q_m3s=self._Q, D_m=self._D, L_m=100.0, P1_kPa=-10.0)

    def test_larger_pipe_lower_drop(self):
        """Larger diameter → lower pressure drop at same flow."""
        r1 = gas_pressure_drop_weymouth(Q_m3s=self._Q, D_m=0.05,  L_m=500.0, P1_kPa=self._P1)
        r2 = gas_pressure_drop_weymouth(Q_m3s=self._Q, D_m=0.15,  L_m=500.0, P1_kPa=self._P1)
        assert r2["dP_kPa"] < r1["dP_kPa"]

    def test_regime_returned(self):
        result = gas_pressure_drop_weymouth(Q_m3s=self._Q, D_m=self._D, L_m=1000.0, P1_kPa=self._P1)
        assert result["regime"] in ("laminar", "turbulent")


# ---------------------------------------------------------------------------
# 4.  Gas pressure drop — Darcy-Weisbach
# ---------------------------------------------------------------------------

class TestGasPressureDropDarcy:

    def test_zero_flow_no_drop(self):
        result = gas_pressure_drop_darcy(Q_m3s=0.0, D_m=0.1, L_m=1000.0, P_kPa=500.0)
        assert result["ok"] is True
        assert result["dP_Pa"] == pytest.approx(0.0)

    def test_monotonic_with_length(self):
        r1 = gas_pressure_drop_darcy(Q_m3s=0.01, D_m=0.1, L_m=500.0, P_kPa=500.0)
        r2 = gas_pressure_drop_darcy(Q_m3s=0.01, D_m=0.1, L_m=2000.0, P_kPa=500.0)
        assert r2["dP_Pa"] > r1["dP_Pa"]

    def test_monotonic_with_flow(self):
        r1 = gas_pressure_drop_darcy(Q_m3s=0.005, D_m=0.1, L_m=1000.0, P_kPa=500.0)
        r2 = gas_pressure_drop_darcy(Q_m3s=0.02, D_m=0.1, L_m=1000.0, P_kPa=500.0)
        assert r2["dP_Pa"] > r1["dP_Pa"]

    def test_turbulent_quadratic_length_scaling(self):
        """For turbulent flow, dP ∝ L (at fixed Q, D)."""
        r1 = gas_pressure_drop_darcy(Q_m3s=0.01, D_m=0.1, L_m=100.0, P_kPa=500.0)
        r2 = gas_pressure_drop_darcy(Q_m3s=0.01, D_m=0.1, L_m=200.0, P_kPa=500.0)
        # Should be approximately 2× for turbulent flow (Darcy is linear in L)
        ratio = r2["dP_Pa"] / r1["dP_Pa"]
        assert ratio == pytest.approx(2.0, rel=0.01)

    def test_friction_factor_positive(self):
        result = gas_pressure_drop_darcy(Q_m3s=0.01, D_m=0.1, L_m=100.0, P_kPa=500.0)
        assert result["friction_factor"] > 0


# ---------------------------------------------------------------------------
# 5.  Electrical duct fill
# ---------------------------------------------------------------------------

class TestElecDuctFill:

    def test_pass_low_fill(self):
        """3 cables of 10 mm OD in 50 mm ID → ~12 % fill → PASS."""
        result = electrical_duct_fill_check(
            conduit_id_mm=50.0,
            cables=[{"count": 3, "od_mm": 10.0}],
        )
        assert result["ok"] is True
        assert result["pass_fail"] == "PASS"
        assert result["n_cables"] == 3
        assert result["fill_pct"] < 40.0

    def test_fail_high_fill(self):
        """3 cables of 25 mm OD in 50 mm ID → ~75 % fill → FAIL."""
        result = electrical_duct_fill_check(
            conduit_id_mm=50.0,
            cables=[{"count": 3, "od_mm": 25.0}],
        )
        assert result["ok"] is True
        assert result["pass_fail"] == "FAIL"

    def test_single_cable_limit_53pct(self):
        """1 cable: NEC limit = 53 %."""
        result = electrical_duct_fill_check(
            conduit_id_mm=50.0,
            cables=[{"count": 1, "od_mm": 10.0}],
        )
        assert result["fill_limit_pct"] == pytest.approx(53.0)

    def test_two_cable_limit_31pct(self):
        """2 cables: NEC limit = 31 %."""
        result = electrical_duct_fill_check(
            conduit_id_mm=50.0,
            cables=[{"count": 2, "od_mm": 5.0}],
        )
        assert result["fill_limit_pct"] == pytest.approx(31.0)

    def test_three_plus_limit_40pct(self):
        """3+ cables: NEC limit = 40 %."""
        result = electrical_duct_fill_check(
            conduit_id_mm=100.0,
            cables=[{"count": 4, "od_mm": 5.0}],
        )
        assert result["fill_limit_pct"] == pytest.approx(40.0)

    def test_awg_lookup(self):
        """AWG-based cable spec should resolve OD and compute fill."""
        result = electrical_duct_fill_check(
            conduit_id_mm=50.0,
            cables=[{"count": 1, "awg": "12AWG"}],
        )
        assert result["ok"] is True
        assert result["cables"][0]["od_mm"] == pytest.approx(5.3)

    def test_empty_cables_pass(self):
        result = electrical_duct_fill_check(conduit_id_mm=50.0, cables=[])
        assert result["pass_fail"] == "PASS"
        assert result["fill_pct"] == pytest.approx(0.0)

    def test_fill_formula(self):
        """Verify fill formula: area_cable / area_conduit * 100 (within rounding)."""
        od = 15.0
        cid = 80.0
        result = electrical_duct_fill_check(
            conduit_id_mm=cid,
            cables=[{"count": 2, "od_mm": od}],
        )
        expected_fill = 2 * math.pi * (od / 2) ** 2 / (math.pi * (cid / 2) ** 2) * 100
        # result is rounded to 2 decimal places; allow 0.01 absolute tolerance
        assert result["fill_pct"] == pytest.approx(expected_fill, abs=0.01)


# ---------------------------------------------------------------------------
# 6.  LLM tool round-trip (async)
# ---------------------------------------------------------------------------

class TestToolRoundTrip:
    """Smoke-test the LLM tool handlers directly."""

    def _ctx(self):
        from kerf_civil._compat import ProjectCtx
        return ProjectCtx()

    def test_create_tool(self):
        from kerf_civil.tools_dry_utilities import run_civil_dry_utility_network_create
        params = {
            "nodes": [
                {"id": "A", "x": 0, "y": 0, "z_surface_m": 5},
                {"id": "B", "x": 50, "y": 0, "z_surface_m": 5},
            ],
            "links": [
                {
                    "id": "L1", "node_from": "A", "node_to": "B",
                    "length_m": 50, "depth_of_cover_m": 0.7, "corridor_offset_m": 0.0,
                    "asset": {"kind": "gas", "diameter_mm": 150, "material": "steel", "mop_kPa": 700},
                }
            ],
        }
        result = json.loads(asyncio.run(run_civil_dry_utility_network_create(params, self._ctx())))
        assert result["ok"] is True
        assert result["n_nodes"] == 2
        assert result["n_links"] == 1
        assert result["asset_kinds"]["gas"] == 1

    def test_clearance_tool_violation(self):
        from kerf_civil.tools_dry_utilities import run_civil_dry_utility_clearance_check
        params = {
            "nodes": [
                {"id": "A", "x": 0, "y": 0, "z_surface_m": 5},
                {"id": "B", "x": 50, "y": 0, "z_surface_m": 5},
            ],
            "links": [
                {
                    "id": "G1", "node_from": "A", "node_to": "B",
                    "length_m": 50, "depth_of_cover_m": 0.7, "corridor_offset_m": 0.0,
                    "asset": {"kind": "gas", "diameter_mm": 150, "material": "PE", "mop_kPa": 200},
                },
                {
                    "id": "E1", "node_from": "A", "node_to": "B",
                    "length_m": 50, "depth_of_cover_m": 0.55, "corridor_offset_m": 0.15,
                    "asset": {"kind": "electrical", "conduit_id_mm": 100, "voltage_class": "LV"},
                },
            ],
        }
        result = json.loads(asyncio.run(run_civil_dry_utility_clearance_check(params, self._ctx())))
        assert result["ok"] is True
        assert result["n_violations"] > 0
        assert result["clearance_ok"] is False

    def test_gas_pressure_drop_tool_weymouth(self):
        from kerf_civil.tools_dry_utilities import run_civil_gas_pressure_drop
        params = {
            "solver": "weymouth",
            "Q_m3s": 0.01,
            "D_m": 0.1,
            "L_m": 1000.0,
            "P1_kPa": 500.0,
        }
        result = json.loads(asyncio.run(run_civil_gas_pressure_drop(params, self._ctx())))
        assert result["ok"] is True
        assert result["dP_kPa"] > 0
        assert result["solver"] == "weymouth"

    def test_gas_pressure_drop_tool_darcy(self):
        from kerf_civil.tools_dry_utilities import run_civil_gas_pressure_drop
        params = {
            "solver": "darcy",
            "Q_m3s": 0.01,
            "D_m": 0.1,
            "L_m": 500.0,
            "P1_kPa": 100.0,
        }
        result = json.loads(asyncio.run(run_civil_gas_pressure_drop(params, self._ctx())))
        assert result["ok"] is True
        assert result["dP_Pa"] > 0
        assert result["solver"] == "darcy"

    def test_duct_fill_tool_pass(self):
        from kerf_civil.tools_dry_utilities import run_civil_elec_duct_fill
        params = {
            "conduit_id_mm": 100.0,
            "cables": [{"count": 3, "od_mm": 10.0}],
        }
        result = json.loads(asyncio.run(run_civil_elec_duct_fill(params, self._ctx())))
        assert result["ok"] is True
        assert result["pass_fail"] == "PASS"

    def test_duct_fill_tool_fail(self):
        from kerf_civil.tools_dry_utilities import run_civil_elec_duct_fill
        params = {
            "conduit_id_mm": 50.0,
            "cables": [{"count": 3, "od_mm": 25.0}],
        }
        result = json.loads(asyncio.run(run_civil_elec_duct_fill(params, self._ctx())))
        assert result["ok"] is True
        assert result["pass_fail"] == "FAIL"
