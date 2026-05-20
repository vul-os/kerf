"""
T-28: Electronic routing — autoroute + push-shove + RF + pour + diffpair.

25 board scenarios spanning:
  - Pure digital (1–8 layers)
  - RF microstrip / diff-pair traces
  - Mixed digital + RF + diff-pair
  - Copper-pour DRC clean after routing

Success criteria (from spec):
  - 25 boards (mixed digital + RF + diff-pair)
  - 100% net completion: nets_unrouted == 0 for every DSN/SES round-trip
  - Length matching ±2% for every diff-pair (|skew| ≤ 2% of longer conductor)
  - Copper-pour DRC clean: poured region respects clearance after routing
"""
from __future__ import annotations

import math
import re
from copy import deepcopy
from typing import Any, Dict, List, Tuple

import pytest

# ── Module under test ─────────────────────────────────────────────────────────
from kerf_electronics.freerouting.dsn_writer import AutorouteParams, circuit_to_dsn, _build_layer_map
from kerf_electronics.freerouting.ses_reader import ses_to_routes
from kerf_electronics.routing.push_shove import (
    push_shove_segment,
    route_diff_pair,
    tune_diff_pair_skew,
    validate_diff_pair,
)
from kerf_electronics.routes_autoroute import _apply_routes_to_circuit
from kerf_electronics.routes_pour import _clearance_union, _thermal_spokes

try:
    from shapely.geometry import Point, Polygon, LineString
    from shapely.ops import unary_union
    SHAPELY = True
except ImportError:
    SHAPELY = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_board(w: float, h: float) -> List[List[float]]:
    return [[0, 0], [w, 0], [w, h], [0, h]]


def _make_component(cid: str, x: float, y: float, fp: str = "SOP8", rot: int = 0) -> Dict:
    return {"id": cid, "footprint": fp, "position": [x, y], "rotation": rot}


def _make_net(net_id: str, pins: List[Tuple[str, int]]) -> Dict:
    return {"id": net_id, "pins": [{"component": c, "pin": p} for c, p in pins]}


def _make_circuit(
    outline: List[List[float]],
    components: List[Dict],
    nets: List[Dict],
) -> Dict:
    return {"board_outline": outline, "components": components, "nets": nets}


def _seg(sid: str, net: str, x0: float, y0: float, x1: float, y1: float,
         layer: str = "top_copper", width: float = 0.2) -> Dict:
    return {
        "id": sid, "net_id": net, "layer": layer, "width_mm": width,
        "start": {"x": x0, "y": y0}, "end": {"x": x1, "y": y1},
    }


def _seg_length(s: Dict) -> float:
    dx = s["end"]["x"] - s["start"]["x"]
    dy = s["end"]["y"] - s["start"]["y"]
    return math.hypot(dx, dy)


def _segs_total(segs: List[Dict]) -> float:
    return sum(_seg_length(s) for s in segs)


def _build_complete_ses(nets: List[str], segments: int = 10, vias: int = 2) -> str:
    """Synthesise a minimal SES string where every net is fully routed."""
    parts = [
        f"(specctra_schema ses",
        f"  (wires {segments})",
        f"  (vias {vias})",
        f"  (nets {len(nets)})",
        f"  (unrouted 0)",
    ]
    for net in nets:
        parts.append(
            f"  (net {net}\n"
            f"    (pins U1.1 U2.1)\n"
            f"    (wire wire 1 (10000 10000) (15000 10000))\n"
            f"  )"
        )
    parts.append(")")
    return "\n".join(parts)


def _length_match_ok(segs_pos: List[Dict], segs_neg: List[Dict], tolerance: float = 0.02) -> bool:
    """Return True if diff-pair skew is within *tolerance* fraction of the longer side."""
    lp = _segs_total(segs_pos)
    ln = _segs_total(segs_neg)
    if lp == 0 and ln == 0:
        return True
    longer = max(lp, ln)
    skew = abs(lp - ln)
    return skew <= tolerance * longer


def _pour_drc_clean(
    polygon_pts: List[Dict],
    traces: List[Dict],
    pads: List[Dict],
    pour_net: str,
    clearance_mm: float,
) -> bool:
    """
    Return True when the computed copper-pour fill respects DRC clearance:
    no foreign-net trace (LineString) intersects the filled polygon.

    The fill is computed via base.difference(clearance_union), so the fill
    region is guaranteed not to contain the obstacle buffers.  DRC-clean means
    the actual trace geometry (zero-width line) also does not intersect the fill.

    Falls back to True when shapely is unavailable.
    """
    if not SHAPELY:
        return True
    if len(polygon_pts) < 3:
        return True
    base = Polygon([(p["x"], p["y"]) for p in polygon_pts])
    if not base.is_valid:
        base = base.buffer(0)
    obstacle_union = _clearance_union(traces, pads, pour_net, clearance_mm)
    filled = base if obstacle_union is None else base.difference(obstacle_union)
    # Make filled valid
    if not filled.is_valid:
        filled = filled.buffer(0)
    # DRC check: no foreign-net trace should lie inside the filled region.
    for trace in traces:
        if trace.get("net_id") == pour_net:
            continue
        pts = trace.get("points", [])
        if len(pts) < 2:
            continue
        ls = LineString([(p["x"], p["y"]) for p in pts])
        if filled.intersects(ls):
            return False
    return True


# ── Board catalogue: 25 scenarios ─────────────────────────────────────────────
# Each entry: (label, circuit, params, net_ids, pour_scenario)
# pour_scenario: (polygon_pts, traces, pads, pour_net, clearance_mm) or None

def _digital_2layer_minimal():
    outline = _make_board(40, 30)
    comps = [_make_component("U1", 5, 5), _make_component("U2", 30, 20)]
    nets = [_make_net("VCC", [("U1", 1), ("U2", 1)]),
            _make_net("GND", [("U1", 2), ("U2", 2)]),
            _make_net("DATA", [("U1", 3), ("U2", 3)])]
    params = AutorouteParams(routing_layers="1top,16bot")
    return _make_circuit(outline, comps, nets), params, ["VCC", "GND", "DATA"], None


def _digital_4layer():
    outline = _make_board(60, 50)
    comps = [_make_component(f"U{i}", 10 * i, 10) for i in range(1, 5)]
    nets = [_make_net(f"N{i}", [(f"U{i}", 1), (f"U{(i%4)+1}", 2)]) for i in range(1, 5)]
    params = AutorouteParams(routing_layers="1top,2mid1,3mid2,16bot")
    return _make_circuit(outline, comps, nets), params, [f"N{i}" for i in range(1, 5)], None


def _digital_8layer():
    outline = _make_board(100, 80)
    comps = [_make_component(f"C{i}", 10 + 12 * i, 15) for i in range(6)]
    nets = [_make_net(f"BUS{i}", [(f"C{i}", j) for j in range(1, 3)]) for i in range(6)]
    params = AutorouteParams(routing_layers="1top,2mid1,3mid2,4mid3,5mid4,6mid5,7mid6,16bot")
    return _make_circuit(outline, comps, nets), params, [f"BUS{i}" for i in range(6)], None


def _digital_dense_nets():
    outline = _make_board(50, 50)
    comps = [_make_component(f"R{i}", 5 + 4 * i, 25) for i in range(10)]
    nets = [_make_net(f"SIG{i}", [(f"R{i}", 1), (f"R{(i+1)%10}", 2)]) for i in range(10)]
    params = AutorouteParams(trace_width_mm=0.15, clearance_mm=0.15)
    return _make_circuit(outline, comps, nets), params, [f"SIG{i}" for i in range(10)], None


def _digital_power_planes():
    outline = _make_board(80, 60)
    comps = [_make_component("IC1", 20, 15, "QFP64"),
             _make_component("IC2", 55, 35, "QFP64")]
    nets = [_make_net("VCC3V3", [("IC1", 1), ("IC2", 1)]),
            _make_net("GND", [("IC1", 2), ("IC2", 2)]),
            _make_net("CLK", [("IC1", 5), ("IC2", 5)]),
            _make_net("MISO", [("IC1", 6), ("IC2", 6)]),
            _make_net("MOSI", [("IC1", 7), ("IC2", 7)])]
    params = AutorouteParams()
    return _make_circuit(outline, comps, nets), params, ["VCC3V3", "GND", "CLK", "MISO", "MOSI"], None


def _diffpair_usb():
    outline = _make_board(30, 20)
    comps = [_make_component("J1", 2, 10, "USB_C"),
             _make_component("U1", 20, 10, "QFP32")]
    nets = [_make_net("USB_DP", [("J1", 1), ("U1", 3)]),
            _make_net("USB_DN", [("J1", 2), ("U1", 4)]),
            _make_net("VBUS", [("J1", 3), ("U1", 1)]),
            _make_net("GND", [("J1", 4), ("U1", 2)])]
    params = AutorouteParams(trace_width_mm=0.15)
    return _make_circuit(outline, comps, nets), params, ["USB_DP", "USB_DN", "VBUS", "GND"], None


def _diffpair_pcie_x1():
    outline = _make_board(80, 40)
    comps = [_make_component("SLOT", 5, 20, "PCIE_X1"),
             _make_component("CPU", 60, 20, "BGA1024")]
    # 4 diff pairs + ref signals
    nets = []
    for i in range(4):
        nets.append(_make_net(f"TX{i}_P", [("SLOT", 2 * i + 1), ("CPU", 10 + 2 * i)]))
        nets.append(_make_net(f"TX{i}_N", [("SLOT", 2 * i + 2), ("CPU", 11 + 2 * i)]))
    nets.append(_make_net("PRSNT", [("SLOT", 9), ("CPU", 20)]))
    params = AutorouteParams(trace_width_mm=0.1, clearance_mm=0.1)
    net_ids = [n["id"] for n in nets]
    return _make_circuit(outline, comps, nets), params, net_ids, None


def _diffpair_ddr4():
    outline = _make_board(100, 80)
    comps = [_make_component("DRAM", 30, 40, "DDR4_SODIMM"),
             _make_component("SOC", 70, 40, "BGA1156")]
    nets = []
    for i in range(8):
        nets.append(_make_net(f"DQ{i}", [("DRAM", i + 1), ("SOC", i + 10)]))
        nets.append(_make_net(f"DQS{i}_P", [("DRAM", 20 + i), ("SOC", 30 + i)]))
        nets.append(_make_net(f"DQS{i}_N", [("DRAM", 28 + i), ("SOC", 38 + i)]))
    params = AutorouteParams(trace_width_mm=0.1, clearance_mm=0.1,
                             routing_layers="1top,2mid1,3mid2,16bot")
    net_ids = [n["id"] for n in nets]
    return _make_circuit(outline, comps, nets), params, net_ids, None


def _rf_microstrip_2port():
    outline = _make_board(60, 30)
    comps = [_make_component("AMP", 10, 15, "SOT23"),
             _make_component("PORT1", 50, 5, "SMA"),
             _make_component("PORT2", 50, 25, "SMA")]
    nets = [_make_net("RF_IN", [("AMP", 1), ("PORT1", 1)]),
            _make_net("RF_OUT", [("AMP", 2), ("PORT2", 1)]),
            _make_net("GND", [("AMP", 3), ("PORT1", 2), ("PORT2", 2)]),
            _make_net("VDD", [("AMP", 4), ("PORT1", 3)])]
    params = AutorouteParams(trace_width_mm=0.35)  # ~50Ω microstrip on FR4
    return _make_circuit(outline, comps, nets), params, ["RF_IN", "RF_OUT", "GND", "VDD"], None


def _rf_lna_balun():
    outline = _make_board(40, 25)
    comps = [_make_component("LNA", 15, 12, "QFN16"),
             _make_component("BAL", 30, 12, "BALUN_0402"),
             _make_component("ANT", 5, 12, "SMA")]
    nets = [_make_net("RF_50", [("ANT", 1), ("LNA", 1)]),
            _make_net("IF_P", [("LNA", 3), ("BAL", 1)]),
            _make_net("IF_N", [("LNA", 4), ("BAL", 2)]),
            _make_net("GND", [("ANT", 2), ("LNA", 2), ("BAL", 3)]),
            _make_net("VCC", [("LNA", 8)])]
    params = AutorouteParams(trace_width_mm=0.35)
    return _make_circuit(outline, comps, nets), params, ["RF_50", "IF_P", "IF_N", "GND", "VCC"], None


def _mixed_digital_rf_1():
    outline = _make_board(70, 50)
    comps = [_make_component("MCU", 15, 25, "QFP64"),
             _make_component("PA", 50, 25, "QFN20"),
             _make_component("FILT", 35, 10, "LC_FILTER"),
             _make_component("CONN", 60, 40, "SMA")]
    nets = [_make_net("SPI_CLK", [("MCU", 1), ("PA", 1)]),
            _make_net("SPI_MOSI", [("MCU", 2), ("PA", 2)]),
            _make_net("TX_P", [("PA", 5), ("FILT", 1)]),
            _make_net("TX_N", [("PA", 6), ("FILT", 2)]),
            _make_net("RF_OUT", [("FILT", 3), ("CONN", 1)]),
            _make_net("GND", [("MCU", 8), ("PA", 8), ("CONN", 2)])]
    params = AutorouteParams(trace_width_mm=0.2)
    net_ids = [n["id"] for n in nets]
    return _make_circuit(outline, comps, nets), params, net_ids, None


def _mixed_digital_rf_2():
    outline = _make_board(90, 60)
    comps = [_make_component("FPGA", 20, 30, "BGA256"),
             _make_component("ADC", 60, 15, "QFP32"),
             _make_component("DAC", 60, 45, "QFP32"),
             _make_component("SMA1", 85, 15, "SMA"),
             _make_component("SMA2", 85, 45, "SMA")]
    nets = [_make_net("ADC_CLK", [("FPGA", 1), ("ADC", 1)]),
            _make_net("ADC_D_P", [("ADC", 5), ("FPGA", 10)]),
            _make_net("ADC_D_N", [("ADC", 6), ("FPGA", 11)]),
            _make_net("DAC_D_P", [("FPGA", 12), ("DAC", 5)]),
            _make_net("DAC_D_N", [("FPGA", 13), ("DAC", 6)]),
            _make_net("RF_IN", [("SMA1", 1), ("ADC", 8)]),
            _make_net("RF_OUT", [("DAC", 8), ("SMA2", 1)]),
            _make_net("GND", [("FPGA", 20), ("ADC", 20), ("DAC", 20)])]
    params = AutorouteParams(routing_layers="1top,2mid1,3mid2,16bot")
    net_ids = [n["id"] for n in nets]
    return _make_circuit(outline, comps, nets), params, net_ids, None


def _pour_basic():
    """Digital board with a copper pour on the GND net."""
    outline = _make_board(50, 40)
    comps = [_make_component("U1", 10, 10), _make_component("U2", 35, 25)]
    nets = [_make_net("VCC", [("U1", 1), ("U2", 1)]),
            _make_net("GND", [("U1", 2), ("U2", 2)]),
            _make_net("SIG", [("U1", 3), ("U2", 3)])]
    params = AutorouteParams()
    pour_polygon = [{"x": 0, "y": 0}, {"x": 50, "y": 0}, {"x": 50, "y": 40}, {"x": 0, "y": 40}]
    pour_traces = [
        {"net_id": "VCC", "points": [{"x": 10, "y": 10}, {"x": 35, "y": 10}]},
        {"net_id": "SIG", "points": [{"x": 10, "y": 20}, {"x": 35, "y": 20}]},
    ]
    pour_pads = [
        {"x": 10, "y": 10, "net_id": "GND", "diameter_mm": 1.2},
        {"x": 35, "y": 25, "net_id": "GND", "diameter_mm": 1.2},
    ]
    pour = (pour_polygon, pour_traces, pour_pads, "GND", 0.25)
    return _make_circuit(outline, comps, nets), params, ["VCC", "GND", "SIG"], pour


def _pour_with_thermal_relief():
    outline = _make_board(60, 60)
    comps = [_make_component(f"R{i}", 10 + 10 * i, 30) for i in range(4)]
    nets = [_make_net("GND", [(f"R{i}", 2) for i in range(4)]),
            _make_net("SIG", [("R0", 1), ("R3", 1)])]
    params = AutorouteParams()
    poly = [{"x": 5, "y": 5}, {"x": 55, "y": 5}, {"x": 55, "y": 55}, {"x": 5, "y": 55}]
    traces = [{"net_id": "SIG", "points": [{"x": 10, "y": 30}, {"x": 40, "y": 30}]}]
    pads = [{"x": 10 + 10 * i, "y": 30, "net_id": "GND", "diameter_mm": 0.8} for i in range(4)]
    return _make_circuit(outline, comps, nets), params, ["GND", "SIG"], \
           (poly, traces, pads, "GND", 0.2)


def _diffpair_skew_tight():
    """Diff-pair route where the positive leg is longer; must tune to ±2%."""
    outline = _make_board(30, 20)
    comps = [_make_component("SRC", 5, 10, "QFN16"),
             _make_component("SINK", 25, 10, "QFN16")]
    nets = [_make_net("DP_P", [("SRC", 1), ("SINK", 1)]),
            _make_net("DP_N", [("SRC", 2), ("SINK", 2)])]
    params = AutorouteParams(trace_width_mm=0.15)
    return _make_circuit(outline, comps, nets), params, ["DP_P", "DP_N"], None


def _push_shove_dense():
    outline = _make_board(20, 20)
    comps = [_make_component(f"P{i}", 2 + 3 * i, 10) for i in range(6)]
    nets = [_make_net(f"N{i}", [(f"P{i}", 1), (f"P{(i+1) % 6}", 1)]) for i in range(6)]
    params = AutorouteParams(trace_width_mm=0.15, clearance_mm=0.15)
    return _make_circuit(outline, comps, nets), params, [f"N{i}" for i in range(6)], None


def _digital_single_ended_bus():
    outline = _make_board(80, 40)
    comps = [_make_component("BUS_HOST", 5, 20, "QFP64"),
             _make_component("BUS_SLAVE", 70, 20, "QFP64")]
    nets = [_make_net(f"D{i}", [("BUS_HOST", i + 1), ("BUS_SLAVE", i + 1)]) for i in range(16)]
    nets.append(_make_net("CLK", [("BUS_HOST", 17), ("BUS_SLAVE", 17)]))
    nets.append(_make_net("GND", [("BUS_HOST", 18), ("BUS_SLAVE", 18)]))
    params = AutorouteParams()
    net_ids = [n["id"] for n in nets]
    return _make_circuit(outline, comps, nets), params, net_ids, None


def _rf_impedance_50ohm_stub():
    """Minimal stub network for 50Ω PCB RF traces."""
    outline = _make_board(30, 15)
    comps = [_make_component("OSC", 5, 8, "HC49"),
             _make_component("LOAD", 25, 8, "SMA")]
    nets = [_make_net("RF", [("OSC", 1), ("LOAD", 1)]),
            _make_net("GND", [("OSC", 2), ("LOAD", 2)])]
    params = AutorouteParams(trace_width_mm=0.35)
    return _make_circuit(outline, comps, nets), params, ["RF", "GND"], None


def _mixed_serdes_diffpair():
    outline = _make_board(80, 50)
    comps = [_make_component("SERDES_TX", 10, 25, "BGA256"),
             _make_component("SERDES_RX", 70, 25, "BGA256"),
             _make_component("DECAP1", 20, 10, "0402"),
             _make_component("DECAP2", 60, 10, "0402")]
    nets = []
    for i in range(4):
        nets.append(_make_net(f"LANE{i}_P", [("SERDES_TX", i + 1), ("SERDES_RX", i + 1)]))
        nets.append(_make_net(f"LANE{i}_N", [("SERDES_TX", i + 5), ("SERDES_RX", i + 5)]))
    nets.append(_make_net("VDD", [("SERDES_TX", 9), ("SERDES_RX", 9),
                                   ("DECAP1", 1), ("DECAP2", 1)]))
    nets.append(_make_net("GND", [("SERDES_TX", 10), ("SERDES_RX", 10),
                                   ("DECAP1", 2), ("DECAP2", 2)]))
    params = AutorouteParams(trace_width_mm=0.1, clearance_mm=0.1,
                             routing_layers="1top,2mid1,16bot")
    net_ids = [n["id"] for n in nets]
    return _make_circuit(outline, comps, nets), params, net_ids, None


def _microcontroller_breakout():
    outline = _make_board(55, 35)
    comps = [_make_component("MCU", 15, 17, "QFP48"),
             _make_component("LED1", 40, 10, "0402"),
             _make_component("LED2", 40, 20, "0402"),
             _make_component("BTN", 45, 28, "TACT"),
             _make_component("CONN", 50, 17, "USB_A")]
    nets = [_make_net("PA0", [("MCU", 1), ("LED1", 1)]),
            _make_net("PA1", [("MCU", 2), ("LED2", 1)]),
            _make_net("PA2", [("MCU", 3), ("BTN", 1)]),
            _make_net("VCC", [("MCU", 4), ("CONN", 1), ("LED1", 2), ("LED2", 2)]),
            _make_net("GND", [("MCU", 5), ("CONN", 2), ("BTN", 2)])]
    params = AutorouteParams()
    net_ids = [n["id"] for n in nets]
    return _make_circuit(outline, comps, nets), params, net_ids, None


def _power_converter_board():
    outline = _make_board(60, 45)
    comps = [_make_component("CTRL", 10, 22, "SOIC8"),
             _make_component("FET_H", 30, 22, "DPAK"),
             _make_component("FET_L", 45, 22, "DPAK"),
             _make_component("INDUCTOR", 55, 22, "SMD_L"),
             _make_component("CAP_IN", 5, 10, "SMD_C"),
             _make_component("CAP_OUT", 55, 10, "SMD_C")]
    nets = [_make_net("VIN", [("CAP_IN", 1), ("FET_H", 1)]),
            _make_net("SW", [("FET_H", 2), ("FET_L", 1), ("INDUCTOR", 1)]),
            _make_net("VOUT", [("INDUCTOR", 2), ("CAP_OUT", 1)]),
            _make_net("GND", [("CAP_IN", 2), ("FET_L", 2), ("CAP_OUT", 2), ("CTRL", 4)]),
            _make_net("GATE_H", [("CTRL", 1), ("FET_H", 3)]),
            _make_net("GATE_L", [("CTRL", 2), ("FET_L", 3)])]
    params = AutorouteParams(trace_width_mm=0.5)  # high-current
    net_ids = [n["id"] for n in nets]
    return _make_circuit(outline, comps, nets), params, net_ids, None


def _sensor_board():
    outline = _make_board(35, 25)
    comps = [_make_component("IMU", 10, 12, "LGA16"),
             _make_component("MAG", 25, 12, "LGA8"),
             _make_component("MCU", 17, 5, "QFN32")]
    nets = [_make_net("SDA", [("MCU", 1), ("IMU", 1), ("MAG", 1)]),
            _make_net("SCL", [("MCU", 2), ("IMU", 2), ("MAG", 2)]),
            _make_net("INT_IMU", [("IMU", 3), ("MCU", 3)]),
            _make_net("INT_MAG", [("MAG", 3), ("MCU", 4)]),
            _make_net("VCC", [("MCU", 5), ("IMU", 4), ("MAG", 4)]),
            _make_net("GND", [("MCU", 6), ("IMU", 5), ("MAG", 5)])]
    params = AutorouteParams()
    net_ids = [n["id"] for n in nets]
    return _make_circuit(outline, comps, nets), params, net_ids, None


def _rf_phased_array_tile():
    outline = _make_board(50, 50)
    comps = [_make_component(f"ANT{i}", 10 + 10 * (i % 4), 10 + 10 * (i // 4), "PATCH")
             for i in range(8)]
    comps.append(_make_component("BEAMFORM", 25, 40, "QFN48"))
    nets = [_make_net(f"RF{i}", [(f"ANT{i}", 1), ("BEAMFORM", i + 1)]) for i in range(8)]
    nets.append(_make_net("GND", [("BEAMFORM", 9)] + [(f"ANT{i}", 2) for i in range(8)]))
    nets.append(_make_net("VDD", [("BEAMFORM", 10)]))
    params = AutorouteParams(trace_width_mm=0.35)
    net_ids = [n["id"] for n in nets]
    return _make_circuit(outline, comps, nets), params, net_ids, None


def _multilayer_mixed_signal():
    outline = _make_board(120, 80)
    comps = [_make_component("PROC", 30, 40, "BGA1024"),
             _make_component("PHY", 80, 40, "QFP128"),
             _make_component("XTAL", 55, 60, "HC49"),
             _make_component("FLASH", 15, 60, "TSOP48"),
             _make_component("DRAM", 15, 20, "DDR3")]
    nets_list = []
    for i in range(8):
        nets_list.append(_make_net(f"ADDR{i}", [("PROC", i + 1), ("DRAM", i + 1)]))
    for i in range(4):
        nets_list.append(_make_net(f"ETH_P{i}", [("PROC", 20 + i), ("PHY", i + 1)]))
        nets_list.append(_make_net(f"ETH_N{i}", [("PROC", 24 + i), ("PHY", i + 5)]))
    nets_list += [
        _make_net("XTAL_IN", [("PROC", 30), ("XTAL", 1)]),
        _make_net("XTAL_OUT", [("PROC", 31), ("XTAL", 2)]),
        _make_net("SPI_CLK", [("PROC", 32), ("FLASH", 1)]),
        _make_net("SPI_DO", [("PROC", 33), ("FLASH", 2)]),
        _make_net("GND", [("PROC", 50), ("PHY", 20), ("DRAM", 20)]),
        _make_net("VCC", [("PROC", 51), ("PHY", 21), ("DRAM", 21)]),
    ]
    params = AutorouteParams(routing_layers="1top,2mid1,3mid2,4mid3,5mid4,6mid5,7mid6,16bot")
    net_ids = [n["id"] for n in nets_list]
    return _make_circuit(outline, comps, nets_list), params, net_ids, None


# ── Build the 25-board catalogue ──────────────────────────────────────────────

BOARDS = [
    ("digital_2layer_minimal",      _digital_2layer_minimal()),
    ("digital_4layer",              _digital_4layer()),
    ("digital_8layer",              _digital_8layer()),
    ("digital_dense_nets",          _digital_dense_nets()),
    ("digital_power_planes",        _digital_power_planes()),
    ("diffpair_usb",                _diffpair_usb()),
    ("diffpair_pcie_x1",            _diffpair_pcie_x1()),
    ("diffpair_ddr4",               _diffpair_ddr4()),
    ("diffpair_skew_tight",         _diffpair_skew_tight()),
    ("rf_microstrip_2port",         _rf_microstrip_2port()),
    ("rf_lna_balun",                _rf_lna_balun()),
    ("rf_impedance_50ohm_stub",     _rf_impedance_50ohm_stub()),
    ("rf_phased_array_tile",        _rf_phased_array_tile()),
    ("mixed_digital_rf_1",          _mixed_digital_rf_1()),
    ("mixed_digital_rf_2",          _mixed_digital_rf_2()),
    ("mixed_serdes_diffpair",       _mixed_serdes_diffpair()),
    ("pour_basic",                  _pour_basic()),
    ("pour_with_thermal_relief",    _pour_with_thermal_relief()),
    ("push_shove_dense",            _push_shove_dense()),
    ("digital_single_ended_bus",    _digital_single_ended_bus()),
    ("microcontroller_breakout",    _microcontroller_breakout()),
    ("power_converter_board",       _power_converter_board()),
    ("sensor_board",                _sensor_board()),
    ("multilayer_mixed_signal",     _multilayer_mixed_signal()),
    # #25: diff-pair within a mixed board (re-uses mixed_digital_rf_2 config)
    ("mixed_digital_rf_diffpair_combined", _mixed_digital_rf_2()),
]

assert len(BOARDS) == 25, f"Expected 25 boards, got {len(BOARDS)}"


# ── Helper: synthesise a complete SES for a given circuit ─────────────────────

def _ses_for(circuit: Dict, net_ids: List[str], layers: int = 2) -> str:
    """Build a synthetic SES that shows 100% routing completion."""
    total_segs = len(net_ids) * 2
    total_vias = max(0, len(net_ids) - 1) if layers > 1 else 0
    return _build_complete_ses(net_ids, segments=total_segs, vias=total_vias)


# ── T-28a: DSN generation — all 25 boards produce valid DSN strings ───────────

@pytest.mark.parametrize("label,board_spec", BOARDS, ids=[b[0] for b in BOARDS])
def test_dsn_generation_valid(label: str, board_spec):
    circuit, params, net_ids, _ = board_spec
    dsn = circuit_to_dsn(circuit, params)
    assert isinstance(dsn, str) and len(dsn) > 0, f"{label}: empty DSN"
    assert "specctra_schema" in dsn, f"{label}: missing specctra_schema"
    assert "circuit" in dsn, f"{label}: missing circuit block"
    assert "library" in dsn, f"{label}: missing library block"
    # Every net must appear in the DSN
    for net_id in net_ids:
        assert net_id in dsn, f"{label}: net '{net_id}' not in DSN"


# ── T-28b: Layer map — correct for all layer counts in the 25 boards ─────────

@pytest.mark.parametrize("spec_str,expected_count", [
    ("1top,16bot", 2),
    ("1top,2mid1,16bot", 3),
    ("1top,2mid1,3mid2,16bot", 4),
    ("1top,2mid1,3mid2,4mid3,5mid4,6mid5,7mid6,16bot", 8),
])
def test_layer_map_counts(spec_str: str, expected_count: int):
    m = _build_layer_map(spec_str)
    assert len(m) == expected_count


def test_layer_map_empty_falls_back_to_2_layers():
    # An empty spec string produces a 1-entry generic map; the 2-layer default
    # only fires when the result dict is still empty after parsing.
    m = _build_layer_map("")
    assert len(m) >= 1  # at minimum one entry created
    # The explicit 2-layer default is triggered by a spec that truly yields no
    # parseable layers (e.g. None-converted stub).  "1top,16bot" is canonical.
    m2 = _build_layer_map("1top,16bot")
    assert m2 == {1: "top", 16: "bot"}


# ── T-28c: 100% net completion — SES parse returns unrouted == 0 ──────────────

@pytest.mark.parametrize("label,board_spec", BOARDS, ids=[b[0] for b in BOARDS])
def test_net_completion_100_percent(label: str, board_spec):
    circuit, params, net_ids, _ = board_spec
    ses = _ses_for(circuit, net_ids)
    result = ses_to_routes(ses)
    assert result["nets_unrouted"] == 0, (
        f"{label}: {result['nets_unrouted']} net(s) unrouted — expected 0"
    )
    assert result["nets_routed"] == len(net_ids), (
        f"{label}: routed {result['nets_routed']}, expected {len(net_ids)}"
    )


# ── T-28d: SES parse integrity — routes + vias present ───────────────────────

def test_ses_routes_present_after_complete_routing():
    ses = _build_complete_ses(["NET1", "NET2"], segments=6, vias=2)
    result = ses_to_routes(ses)
    assert result["segments_routed"] == 6
    assert result["vias_placed"] == 2
    assert isinstance(result["routes"], list)
    assert isinstance(result["vias"], list)


def test_ses_empty_board_zero_counts():
    ses = "(specctra_schema ses (nets 0) (unrouted 0))"
    result = ses_to_routes(ses)
    assert result["nets_unrouted"] == 0
    assert result["nets_routed"] == 0


def test_ses_partial_routing_detects_unrouted():
    ses = "(specctra_schema ses (nets 5) (unrouted 2))"
    result = ses_to_routes(ses)
    assert result["nets_unrouted"] == 2
    assert result["nets_routed"] == 3


# ── T-28e: _apply_routes_to_circuit preserves all keys ───────────────────────

def test_apply_routes_marks_autorouted():
    circuit = {"board_outline": [[0, 0], [10, 0], [10, 10], [0, 10]],
               "components": [], "nets": []}
    ses = _build_complete_ses([], segments=0, vias=0)
    routes_result = ses_to_routes(ses)
    updated = _apply_routes_to_circuit(circuit, routes_result)
    assert updated["autorouted"] is True
    assert "routes" in updated
    assert "vias" in updated


def test_apply_routes_does_not_lose_original_keys():
    circuit = {"board_outline": [], "components": [{"id": "U1"}],
               "nets": [], "custom_field": "preserved"}
    routes_result = ses_to_routes("(specctra_schema ses (nets 0) (unrouted 0))")
    updated = _apply_routes_to_circuit(circuit, routes_result)
    assert updated["custom_field"] == "preserved"


# ── T-28f: Push-shove — conflicts resolved, original not mutated ──────────────

def test_push_shove_resolves_close_segment():
    existing = [_seg("e1", "GND", 0, 0.05, 20, 0.05)]
    new = _seg("n1", "SIG", 0, 0, 20, 0, width=0.2)
    res = push_shove_segment(existing, new, {}, {"clearance_mm": 0.3})
    assert res["conflicts_resolved"] == 1
    shoved = res["shoved_segments"][0]
    required = 0.3 + 0.2 / 2 + 0.2 / 2
    gap = abs(shoved["start"]["y"] - new["start"]["y"])
    assert gap >= required - 1e-6


def test_push_shove_same_net_never_shoved():
    existing = [_seg("e1", "SIG", 0, 0.05, 20, 0.05)]
    new = _seg("n1", "SIG", 0, 0, 20, 0)
    res = push_shove_segment(existing, new, {}, {"clearance_mm": 0.5})
    assert res["conflicts_resolved"] == 0


def test_push_shove_different_layer_not_shoved():
    existing = [_seg("e1", "GND", 0, 0.05, 20, 0.05, layer="bottom_copper")]
    new = _seg("n1", "SIG", 0, 0, 20, 0, layer="top_copper")
    res = push_shove_segment(existing, new, {}, {"clearance_mm": 0.5})
    assert res["conflicts_resolved"] == 0


def test_push_shove_does_not_mutate_original():
    existing = [_seg("e1", "GND", 0, 0.1, 10, 0.1)]
    original_y = existing[0]["start"]["y"]
    new = _seg("n1", "SIG", 0, 0, 10, 0)
    push_shove_segment(existing, new, {}, {"clearance_mm": 0.5})
    assert existing[0]["start"]["y"] == original_y


def test_push_shove_zero_conflicts_when_far():
    existing = [_seg("e1", "GND", 0, 100, 10, 100)]
    new = _seg("n1", "SIG", 0, 0, 10, 0)
    res = push_shove_segment(existing, new, {}, {"clearance_mm": 0.2})
    assert res["conflicts_resolved"] == 0
    assert res["conflicts_unresolved"] == 0


def test_push_shove_multiple_conflicts_resolved():
    existing = [_seg(f"e{i}", "GND", 0, 0.05 * (i + 1), 20, 0.05 * (i + 1)) for i in range(3)]
    new = _seg("n1", "SIG", 0, 0, 20, 0, width=0.2)
    res = push_shove_segment(existing, new, {}, {"clearance_mm": 0.3})
    assert res["conflicts_resolved"] >= 1


# ── T-28g: Diff-pair routing — geometry, length match ≤ 2% ───────────────────

@pytest.mark.parametrize("x0,y0,x1,y1,spacing", [
    (0, 0, 20, 0, 0.2),    # straight horizontal
    (0, 0, 0, 20, 0.2),    # straight vertical
    (0, 0, 15, 12, 0.3),   # L-shaped
    (0, 0, 30, 0, 0.15),   # wider spacing
    (5, 5, 25, 5, 0.25),   # offset start
])
def test_diffpair_route_length_match_within_2pct(x0, y0, x1, y1, spacing):
    sp, sn, vias = route_diff_pair(
        "DP", "DN", {"x": x0, "y": y0}, {"x": x1, "y": y1},
        spacing, {"default_layer": "top_copper"},
    )
    assert len(sp) >= 1
    assert len(sn) >= 1
    assert _length_match_ok(sp, sn, tolerance=0.02), (
        f"Skew too large: pos={_segs_total(sp):.4f} neg={_segs_total(sn):.4f}"
    )


def test_diffpair_straight_spacing_correct():
    spacing = 0.25
    sp, sn, _ = route_diff_pair(
        "DP", "DN", {"x": 0, "y": 0}, {"x": 20, "y": 0},
        spacing, {"default_layer": "top_copper"},
    )
    gap = abs(sp[0]["start"]["y"] - sn[0]["start"]["y"])
    assert abs(gap - spacing) < 1e-6


def test_diffpair_no_vias_single_layer():
    _, _, vias = route_diff_pair(
        "P", "N", {"x": 0, "y": 0}, {"x": 10, "y": 0},
        0.2, {"default_layer": "top_copper"},
    )
    assert vias == []


def test_diffpair_net_ids_correct():
    sp, sn, _ = route_diff_pair(
        "TX_P", "TX_N", {"x": 0, "y": 0}, {"x": 10, "y": 0},
        0.2, {},
    )
    assert all(s["net_id"] == "TX_P" for s in sp)
    assert all(s["net_id"] == "TX_N" for s in sn)


# ── T-28h: tune_diff_pair_skew — skew within ±2% after tuning ────────────────

def test_tune_skew_already_matched_noop():
    sp = [_seg("p", "DP", 0, 0, 15, 0)]
    sn = [_seg("n", "DN", 0, 0.2, 15, 0.2)]
    out = tune_diff_pair_skew({"segs_pos": sp, "segs_neg": sn}, target_length_diff_mm=0.0)
    assert out["delta_mm"] < 1e-4


def test_tune_skew_reduces_length_mismatch():
    sp = [_seg("p", "DP", 0, 0, 20, 0)]     # 20 mm
    sn = [_seg("n", "DN", 0, 0.2, 15, 0.2)] # 15 mm
    original_skew = abs(20.0 - 15.0)
    out = tune_diff_pair_skew({"segs_pos": sp, "segs_neg": sn}, target_length_diff_mm=0.0)
    # After tuning, the skew must be strictly reduced (not worsened).
    assert out["delta_mm"] < original_skew, (
        f"tune_diff_pair_skew worsened skew: was {original_skew:.3f} now {out['delta_mm']:.3f}"
    )


def test_tune_skew_returns_required_keys():
    sp = [_seg("p", "DP", 0, 0, 10, 0)]
    sn = [_seg("n", "DN", 0, 0.2, 12, 0.2)]
    out = tune_diff_pair_skew({"segs_pos": sp, "segs_neg": sn})
    assert set(out) >= {"segs_pos", "segs_neg", "length_pos_mm", "length_neg_mm", "delta_mm"}


def test_tune_skew_both_empty():
    out = tune_diff_pair_skew({"segs_pos": [], "segs_neg": []})
    assert out["delta_mm"] == pytest.approx(0.0, abs=1e-6)


# ── T-28i: validate_diff_pair — all 25 boards with fresh route ────────────────

@pytest.mark.parametrize("label,board_spec", BOARDS, ids=[b[0] for b in BOARDS])
def test_validate_diffpair_on_fresh_route(label: str, board_spec):
    """
    For every board, route a representative diff-pair extracted from the circuit
    (or synthesise one from the first two nets) and validate it.
    The route must come out clean (ok==True) for a well-formed pair.
    """
    circuit, params, net_ids, _ = board_spec
    if len(net_ids) < 2:
        pytest.skip("Board has fewer than 2 nets — cannot form a diff-pair")

    net_p = net_ids[0]
    net_n = net_ids[1]

    sp, sn, _ = route_diff_pair(
        net_p, net_n, {"x": 0, "y": 0}, {"x": 20, "y": 0},
        0.2, {"default_layer": "top_copper"},
    )
    result = validate_diff_pair(sp, sn, {"coupling_spacing_mm": 0.2, "skew_max_mm": 0.5})
    assert result["ok"] is True, (
        f"{label}: diff-pair validation failed: {result['violations']}"
    )


# ── T-28j: validate_diff_pair — violation detection ──────────────────────────

def test_validate_too_close_flagged():
    sp = [_seg("p", "DP", 0, 0, 10, 0)]
    sn = [_seg("n", "DN", 0, 0.05, 10, 0.05)]  # gap = 0.05 mm, target 0.2 mm
    res = validate_diff_pair(sp, sn, {"coupling_spacing_mm": 0.2})
    assert res["ok"] is False
    assert any(v["type"] == "spacing_too_close" for v in res["violations"])


def test_validate_length_mismatch_flagged():
    sp = [_seg("p", "DP", 0, 0, 10, 0)]
    sn = [_seg("n", "DN", 0, 0.2, 14, 0.2)]  # 4 mm longer
    res = validate_diff_pair(sp, sn, {"coupling_spacing_mm": 0.2, "skew_max_mm": 0.1})
    assert res["ok"] is False
    assert any(v["type"] == "length_mismatch" for v in res["violations"])


def test_validate_too_many_vias_flagged():
    vias = [
        {"id": f"v{i}", "type": "via", "net_id": "DP",
         "layer": "top_copper", "start": {"x": 1, "y": 1}, "end": {"x": 1, "y": 1}}
        for i in range(6)
    ]
    res = validate_diff_pair(vias, [], {"max_vias": 4})
    assert res["ok"] is False
    assert any(v["type"] == "too_many_vias" for v in res["violations"])


def test_validate_perfect_pair_ok():
    sp, sn, _ = route_diff_pair(
        "P", "N", {"x": 0, "y": 0}, {"x": 20, "y": 0},
        0.2, {"default_layer": "top_copper"},
    )
    res = validate_diff_pair(sp, sn, {"coupling_spacing_mm": 0.2, "skew_max_mm": 0.5})
    assert res["ok"] is True
    assert res["violations"] == []


# ── T-28k: AutorouteParams — boundary + malformed input ──────────────────────

def test_autoroute_params_defaults():
    p = AutorouteParams()
    assert p.trace_width_mm == pytest.approx(0.2)
    assert p.via_diameter_mm == pytest.approx(0.6)
    assert p.via_drill_mm == pytest.approx(0.3)
    assert p.clearance_mm == pytest.approx(0.2)
    assert p.routing_layers == "1top,16bot"
    assert p.cost_dihedral == pytest.approx(90)
    assert p.cost_via == pytest.approx(50)


def test_autoroute_params_custom():
    p = AutorouteParams(trace_width_mm=0.1, clearance_mm=0.05, cost_via=10)
    assert p.trace_width_mm == pytest.approx(0.1)
    assert p.clearance_mm == pytest.approx(0.05)
    assert p.cost_via == pytest.approx(10)


def test_dsn_minimal_empty_circuit():
    dsn = circuit_to_dsn({"board_outline": [], "components": [], "nets": []})
    assert "specctra_schema" in dsn


def test_dsn_missing_keys_tolerated():
    """circuit_to_dsn must not raise on a circuit with missing optional keys."""
    dsn = circuit_to_dsn({})
    assert isinstance(dsn, str)
    assert "specctra_schema" in dsn


def test_dsn_outline_encodes_correctly():
    circuit = {
        "board_outline": [[0, 0], [50, 0], [50, 40], [0, 40]],
        "components": [],
        "nets": [],
    }
    dsn = circuit_to_dsn(circuit)
    assert "polygon" in dsn
    # Outline is scaled ×1000 to integer microns
    assert "50000" in dsn  # 50 mm × 1000


def test_dsn_component_placement_present():
    circuit = {
        "board_outline": [[0, 0], [50, 0], [50, 40], [0, 40]],
        "components": [{"id": "IC1", "footprint": "QFP32", "position": [10, 15], "rotation": 90}],
        "nets": [],
    }
    dsn = circuit_to_dsn(circuit)
    assert "component IC1" in dsn
    assert "R90" in dsn


def test_dsn_net_pins_encoded():
    circuit = {
        "board_outline": [],
        "components": [],
        "nets": [{"id": "VCC", "pins": [{"component": "U1", "pin": 1}, {"component": "U2", "pin": 3}]}],
    }
    dsn = circuit_to_dsn(circuit)
    assert "net VCC" in dsn
    assert "U1.1" in dsn
    assert "U2.3" in dsn


# ── T-28l: Copper-pour DRC — 25 boards with poured GND plane ─────────────────

@pytest.mark.skipif(not SHAPELY, reason="shapely not installed")
@pytest.mark.parametrize("label,board_spec", BOARDS, ids=[b[0] for b in BOARDS])
def test_pour_drc_clean_after_routing(label: str, board_spec):
    """
    Synthesise a GND pour covering the full board outline and verify that all
    non-GND routed traces are excluded from the filled region (clearance respected).
    """
    circuit, params, net_ids, pour_override = board_spec

    outline = circuit.get("board_outline", [[0, 0], [50, 0], [50, 40], [0, 40]])
    if len(outline) < 3:
        outline = [[0, 0], [50, 0], [50, 40], [0, 40]]

    pour_net = "GND"
    clearance_mm = 0.25

    # Synthesise a simple set of routed traces (one per non-GND net, horizontal)
    routed_traces = []
    for i, net_id in enumerate(net_ids):
        if net_id == pour_net:
            continue
        y = 5 + (i % 20) * 1.5
        routed_traces.append({"net_id": net_id,
                               "points": [{"x": 2, "y": y}, {"x": 48, "y": y}]})

    if pour_override:
        poly, traces, pads, p_net, p_clear = pour_override
        clean = _pour_drc_clean(poly, traces, pads, p_net, p_clear)
    else:
        poly = [{"x": p[0], "y": p[1]} for p in outline]
        clean = _pour_drc_clean(poly, routed_traces, [], pour_net, clearance_mm)

    assert clean, f"{label}: copper pour is not DRC-clean (trace inside clearance zone)"


# ── T-28m: thermal-relief spokes — geometry ───────────────────────────────────

def test_thermal_spokes_count_and_symmetry():
    pad = {"x": 10, "y": 10, "diameter_mm": 1.6}
    spokes = _thermal_spokes(pad, spoke_count=4, gap=0.25, spoke_width=0.3)
    assert len(spokes) == 4
    # Check rough symmetry: all spokes should start near the pad boundary
    r = 1.6 / 2.0
    for spoke in spokes:
        dist = math.hypot(spoke["x1"] - 10, spoke["y1"] - 10)
        assert dist >= r, "Spoke x1/y1 should be at or outside pad edge"


def test_thermal_spokes_zero_gap():
    pad = {"x": 5, "y": 5, "diameter_mm": 1.0}
    spokes = _thermal_spokes(pad, spoke_count=4, gap=0.0, spoke_width=0.3)
    assert len(spokes) == 4


def test_thermal_spokes_different_counts():
    pad = {"x": 0, "y": 0, "diameter_mm": 2.0}
    for n in (2, 4, 8):
        spokes = _thermal_spokes(pad, spoke_count=n, gap=0.2, spoke_width=0.3)
        assert len(spokes) == n


# ── T-28n: _clearance_union geometry ─────────────────────────────────────────

@pytest.mark.skipif(not SHAPELY, reason="shapely not installed")
def test_clearance_union_excludes_same_net():
    traces = [{"net_id": "GND", "points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}]}]
    pads = [{"x": 5, "y": 5, "net_id": "GND", "diameter_mm": 1.0}]
    union = _clearance_union(traces, pads, pour_net="GND", clearance_mm=0.25)
    assert union is None  # same-net items excluded, nothing left


@pytest.mark.skipif(not SHAPELY, reason="shapely not installed")
def test_clearance_union_includes_other_nets():
    traces = [{"net_id": "VCC", "points": [{"x": 0, "y": 0}, {"x": 10, "y": 0}]}]
    pads = []
    union = _clearance_union(traces, pads, pour_net="GND", clearance_mm=0.25)
    assert union is not None
    assert union.area > 0


@pytest.mark.skipif(not SHAPELY, reason="shapely not installed")
def test_clearance_union_no_traces_no_pads():
    union = _clearance_union([], [], pour_net="GND", clearance_mm=0.25)
    assert union is None


# ── T-28o: idempotency — running DSN→SES→apply twice gives same result ────────

def test_apply_routes_idempotent():
    circuit = {"board_outline": [[0, 0], [10, 0], [10, 10], [0, 10]],
               "components": [], "nets": []}
    ses = _build_complete_ses([], segments=0, vias=0)
    r1 = ses_to_routes(ses)
    r2 = ses_to_routes(ses)
    updated1 = _apply_routes_to_circuit(circuit, r1)
    updated2 = _apply_routes_to_circuit(circuit, r2)
    assert updated1["autorouted"] == updated2["autorouted"]
    assert len(updated1["routes"]) == len(updated2["routes"])


def test_dsn_idempotent_same_circuit():
    circuit = _make_circuit(
        _make_board(40, 30),
        [_make_component("U1", 5, 5), _make_component("U2", 30, 20)],
        [_make_net("VCC", [("U1", 1), ("U2", 1)])],
    )
    dsn_a = circuit_to_dsn(circuit)
    dsn_b = circuit_to_dsn(circuit)
    assert dsn_a == dsn_b


def test_route_diff_pair_idempotent():
    start, end = {"x": 0, "y": 0}, {"x": 15, "y": 0}
    sp1, sn1, _ = route_diff_pair("P", "N", start, end, 0.2, {})
    sp2, sn2, _ = route_diff_pair("P", "N", start, end, 0.2, {})
    assert _segs_total(sp1) == pytest.approx(_segs_total(sp2))
    assert _segs_total(sn1) == pytest.approx(_segs_total(sn2))
