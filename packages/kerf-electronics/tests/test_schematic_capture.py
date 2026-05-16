"""
Hermetic tests for kerf_electronics.schematic.capture.

≥25 tests covering:
  - place 2 symbols + connect → netlist has 1 net with 2 pins
  - junction at 3-wire intersection
  - ERC flags unconnected pin
  - hierarchical port propagates label to parent
  - minimal .kicad_sch round-trip (2-resistor schematic)
  - bus expansion (DATA[3:0] → 4 net names)
  - designator uniqueness check
  - missing / invalid symbol error paths
  - auto_connect 1-bend routing
  - connect_wires straight line
  - add_label & net label in netlist
  - validate_erc: conflicting drivers, net name collision, dangling wire
  - save_kicad_sch contains required tokens
  - load_kicad_sch round-trip preserves symbols, wires, labels

Author: imranparuk
"""
from __future__ import annotations

import json
import os
import sys

# ── Make sure src/ is importable ─────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

import pytest

from kerf_electronics.schematic.capture import (
    Schematic,
    add_junction,
    add_label,
    auto_connect,
    build_netlist,
    connect_wires,
    expand_bus,
    hierarchical_port,
    load_kicad_sch,
    place_symbol,
    save_kicad_sch,
    validate_erc,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _sch_with_sheet() -> Schematic:
    """Return a fresh Schematic with one active sheet."""
    sch = Schematic()
    sch.new_sheet("Root")
    return sch


# ──────────────────────────────────────────────────────────────────────────────
# 1. place_symbol
# ──────────────────────────────────────────────────────────────────────────────

class TestPlaceSymbol:
    def test_place_returns_ok_and_uuid(self):
        sch = _sch_with_sheet()
        res = place_symbol(sch, "Device:R", "R1", "10k", (10.0, 20.0))
        assert res["ok"] is True
        assert "symbol_uuid" in res
        assert res["designator"] == "R1"

    def test_place_symbol_appears_on_sheet(self):
        sch = _sch_with_sheet()
        place_symbol(sch, "Device:R", "R1", "10k", (10.0, 20.0))
        sheet = sch._active()
        assert len(sheet.symbols) == 1
        assert sheet.symbols[0].lib_ref == "Device:R"

    def test_duplicate_designator_returns_error(self):
        sch = _sch_with_sheet()
        place_symbol(sch, "Device:R", "R1", "10k", (10.0, 20.0))
        res = place_symbol(sch, "Device:R", "R1", "22k", (30.0, 20.0))
        assert res["ok"] is False
        assert "R1" in res["reason"]

    def test_missing_lib_ref_returns_error(self):
        sch = _sch_with_sheet()
        res = place_symbol(sch, "", "R1", "10k", (0.0, 0.0))
        assert res["ok"] is False

    def test_bad_position_returns_error(self):
        sch = _sch_with_sheet()
        res = place_symbol(sch, "Device:R", "R2", "10k", "not_a_point")
        assert res["ok"] is False

    def test_no_active_sheet_returns_error(self):
        sch = Schematic()
        res = place_symbol(sch, "Device:R", "R1", "10k", (0.0, 0.0))
        assert res["ok"] is False


# ──────────────────────────────────────────────────────────────────────────────
# 2. connect_wires
# ──────────────────────────────────────────────────────────────────────────────

class TestConnectWires:
    def test_simple_wire_ok(self):
        sch = _sch_with_sheet()
        res = connect_wires(sch, [(0.0, 0.0), (10.0, 0.0)])
        assert res["ok"] is True
        assert "wire_uuid" in res
        assert res["segments"] == 1

    def test_single_point_returns_error(self):
        sch = _sch_with_sheet()
        res = connect_wires(sch, [(0.0, 0.0)])
        assert res["ok"] is False

    def test_wire_stored_on_sheet(self):
        sch = _sch_with_sheet()
        connect_wires(sch, [(0.0, 0.0), (10.0, 0.0)])
        assert len(sch._active().wires) == 1


# ──────────────────────────────────────────────────────────────────────────────
# 3. auto_connect
# ──────────────────────────────────────────────────────────────────────────────

class TestAutoConnect:
    def test_auto_connect_collinear_straight(self):
        sch = _sch_with_sheet()
        res = auto_connect(sch, (0.0, 0.0), (10.0, 0.0))
        assert res["ok"] is True
        assert res["bend"] is False

    def test_auto_connect_non_collinear_bent(self):
        sch = _sch_with_sheet()
        res = auto_connect(sch, (0.0, 0.0), (10.0, 5.0))
        assert res["ok"] is True
        assert res["bend"] is True
        # 3 points: start, corner, end
        assert len(res["points"]) == 3

    def test_auto_connect_bad_pin_a(self):
        sch = _sch_with_sheet()
        res = auto_connect(sch, "bad", (10.0, 5.0))
        assert res["ok"] is False


# ──────────────────────────────────────────────────────────────────────────────
# 4. add_junction
# ──────────────────────────────────────────────────────────────────────────────

class TestAddJunction:
    def test_junction_added_ok(self):
        sch = _sch_with_sheet()
        res = add_junction(sch, (5.0, 5.0))
        assert res["ok"] is True
        assert "junction_uuid" in res

    def test_three_wire_junction(self):
        """Three wires meeting at a point + junction → junction exists on sheet."""
        sch = _sch_with_sheet()
        connect_wires(sch, [(5.0, 0.0), (5.0, 5.0)])
        connect_wires(sch, [(0.0, 5.0), (5.0, 5.0)])
        connect_wires(sch, [(5.0, 5.0), (10.0, 5.0)])
        res = add_junction(sch, (5.0, 5.0))
        assert res["ok"] is True
        sheet = sch._active()
        assert len(sheet.junctions) == 1
        assert sheet.junctions[0].at == (5.0, 5.0)


# ──────────────────────────────────────────────────────────────────────────────
# 5. add_label
# ──────────────────────────────────────────────────────────────────────────────

class TestAddLabel:
    def test_label_ok(self):
        sch = _sch_with_sheet()
        res = add_label(sch, (0.0, 0.0), "VCC")
        assert res["ok"] is True
        assert res["net_name"] == "VCC"

    def test_empty_net_name_error(self):
        sch = _sch_with_sheet()
        res = add_label(sch, (0.0, 0.0), "")
        assert res["ok"] is False


# ──────────────────────────────────────────────────────────────────────────────
# 6. hierarchical_port
# ──────────────────────────────────────────────────────────────────────────────

class TestHierarchicalPort:
    def test_port_added_to_sheet(self):
        sch = _sch_with_sheet()
        sheet = sch._active()
        res = hierarchical_port(sch, sheet.sheet_id, "DATA_IN", "input")
        assert res["ok"] is True
        assert len(sheet.hier_ports) == 1
        assert sheet.hier_ports[0].net_name == "DATA_IN"

    def test_port_propagates_to_parent_via_netlist(self):
        """A hier port on a child sheet should show up in the netlist."""
        sch = Schematic()
        parent = sch.new_sheet("Parent")
        child = sch.new_sheet("Child")

        # On child sheet: wire + label "CLK" on it + hier port "CLK" (input)
        sch.active_sheet = child.sheet_id
        connect_wires(sch, [(0.0, 0.0), (10.0, 0.0)])
        add_label(sch, (0.0, 0.0), "CLK")
        hierarchical_port(sch, child.sheet_id, "CLK", "input")

        nl = build_netlist(sch)
        assert nl["ok"] is True
        net_names = [n["net_name"] for n in nl["nets"]]
        assert "CLK" in net_names

    def test_invalid_sheet_id_error(self):
        sch = _sch_with_sheet()
        res = hierarchical_port(sch, "nonexistent-id", "SIG", "output")
        assert res["ok"] is False

    def test_invalid_direction_error(self):
        sch = _sch_with_sheet()
        sheet = sch._active()
        res = hierarchical_port(sch, sheet.sheet_id, "SIG", "xyzzy")
        assert res["ok"] is False


# ──────────────────────────────────────────────────────────────────────────────
# 7. build_netlist
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildNetlist:
    def _make_two_resistors_connected(self) -> Schematic:
        """
        Canonical 2-resistor schematic:
          R1 pin2 — wire — R2 pin1

        Net labelled "NODE_A" ties both pins.
        """
        sch = _sch_with_sheet()
        # R1: pin1 at (0,0), pin2 at (10,0)
        place_symbol(sch, "Device:R", "R1", "10k", (5.0, 0.0),
                     pins={"1": (0.0, 0.0), "2": (10.0, 0.0)})
        # R2: pin1 at (10,0), pin2 at (20,0)
        place_symbol(sch, "Device:R", "R2", "22k", (15.0, 0.0),
                     pins={"1": (10.0, 0.0), "2": (20.0, 0.0)})
        # Wire from (0,0) to (20,0) — connects R1.pin1, R1.pin2/R2.pin1, R2.pin2
        connect_wires(sch, [(0.0, 0.0), (20.0, 0.0)])
        add_label(sch, (10.0, 0.0), "NODE_A")
        return sch

    def test_two_resistors_single_net_two_pins(self):
        """2 symbols + 1 wire + label → netlist has 'NODE_A' with ≥ 2 pins."""
        sch = self._make_two_resistors_connected()
        nl = build_netlist(sch)
        assert nl["ok"] is True
        node_nets = [n for n in nl["nets"] if n["net_name"] == "NODE_A"]
        assert len(node_nets) == 1
        node_a = node_nets[0]
        refs = {p["ref"] for p in node_a["pins"]}
        assert "R1" in refs
        assert "R2" in refs

    def test_netlist_json_is_valid_json(self):
        sch = self._make_two_resistors_connected()
        nl = build_netlist(sch)
        parsed = json.loads(nl["netlist_json"])
        assert "nets" in parsed

    def test_netlist_kicad_string_present(self):
        sch = self._make_two_resistors_connected()
        nl = build_netlist(sch)
        assert "(export" in nl["netlist_kicad"]
        assert "NODE_A" in nl["netlist_kicad"]

    def test_net_count_and_pin_count(self):
        sch = self._make_two_resistors_connected()
        nl = build_netlist(sch)
        assert nl["net_count"] >= 1
        assert nl["pin_count"] >= 2


# ──────────────────────────────────────────────────────────────────────────────
# 8. validate_erc
# ──────────────────────────────────────────────────────────────────────────────

class TestValidateErc:
    def test_clean_schematic_passes(self):
        sch = _sch_with_sheet()
        connect_wires(sch, [(0.0, 0.0), (10.0, 0.0)])
        add_label(sch, (0.0, 0.0), "VCC")
        add_label(sch, (10.0, 0.0), "GND")
        place_symbol(sch, "Device:R", "R1", "10k", (5.0, 0.0),
                     pins={"1": (0.0, 0.0), "2": (10.0, 0.0)})
        erc = validate_erc(sch)
        assert erc["ok"] is True
        # Pins connected → no unconnected-pin errors
        unconn = [v for v in erc["violations"] if v["code"] == "ERC_UNCONNECTED_PIN"]
        assert len(unconn) == 0

    def test_unconnected_pin_flagged(self):
        sch = _sch_with_sheet()
        # Symbol placed, no wire at pin positions
        place_symbol(sch, "Device:C", "C1", "100nF", (0.0, 0.0),
                     pins={"1": (1.0, 0.0), "2": (1.0, 5.0)})
        erc = validate_erc(sch)
        assert erc["ok"] is True
        codes = [v["code"] for v in erc["violations"]]
        assert "ERC_UNCONNECTED_PIN" in codes

    def test_conflicting_drivers_flagged(self):
        sch = _sch_with_sheet()
        connect_wires(sch, [(0.0, 0.0), (10.0, 0.0)])
        # Two output labels on the same wire
        add_label(sch, (0.0, 0.0), "SIG")
        add_label(sch, (5.0, 0.0), "SIG")
        # Patch both to 'output'
        for lbl in sch._active().labels:
            lbl.direction = "output"
        erc = validate_erc(sch)
        codes = [v["code"] for v in erc["violations"]]
        assert "ERC_CONFLICTING_DRIVER" in codes

    def test_net_name_collision_flagged(self):
        sch = _sch_with_sheet()
        sheet = sch._active()
        # Same name used as global label AND hierarchical port
        add_label(sch, (0.0, 0.0), "ENABLE")
        hierarchical_port(sch, sheet.sheet_id, "ENABLE", "input")
        erc = validate_erc(sch)
        codes = [v["code"] for v in erc["violations"]]
        assert "ERC_NET_NAME_COLLISION" in codes

    def test_duplicate_designator_across_sheets_flagged(self):
        sch = Schematic()
        s1 = sch.new_sheet("Sheet1")
        sch.active_sheet = s1.sheet_id
        place_symbol(sch, "Device:R", "R1", "10k", (0.0, 0.0))
        s2 = sch.new_sheet("Sheet2")
        sch.active_sheet = s2.sheet_id
        place_symbol(sch, "Device:R", "R1", "22k", (0.0, 0.0))
        erc = validate_erc(sch)
        codes = [v["code"] for v in erc["violations"]]
        assert "ERC_DUPLICATE_DESIGNATOR" in codes

    def test_missing_pins_flagged(self):
        sch = _sch_with_sheet()
        # Symbol with no pins dict
        place_symbol(sch, "Device:R", "R99", "1k", (0.0, 0.0), pins={})
        erc = validate_erc(sch)
        codes = [v["code"] for v in erc["violations"]]
        assert "ERC_MISSING_PINS" in codes


# ──────────────────────────────────────────────────────────────────────────────
# 9. KiCad .kicad_sch round-trip
# ──────────────────────────────────────────────────────────────────────────────

_MINIMAL_SCH = """
(kicad_sch (version 20230121) (generator pcbnew)
  (lib_symbols)
  (symbol (lib_id "Device:R") (at 10.0 10.0 0)
    (property "Reference" "R1")
    (property "Value" "10k")
    (uuid "aaaa-0001")
  )
  (symbol (lib_id "Device:R") (at 30.0 10.0 0)
    (property "Reference" "R2")
    (property "Value" "22k")
    (uuid "aaaa-0002")
  )
  (wire (pts (xy 10.0 10.0) (xy 30.0 10.0)) (uuid "bbbb-0001"))
  (junction (at 20.0 10.0) (uuid "cccc-0001"))
  (label "NODE_A" (at 20.0 10.0 0) (uuid "dddd-0001"))
)
"""


class TestKicadRoundTrip:
    def test_load_kicad_sch_ok(self):
        res = load_kicad_sch(_MINIMAL_SCH)
        assert res["ok"] is True
        assert "schematic" in res

    def test_load_preserves_two_symbols(self):
        res = load_kicad_sch(_MINIMAL_SCH)
        sheet = res["schematic"]._active()
        assert len(sheet.symbols) == 2
        refs = {s.designator for s in sheet.symbols}
        assert refs == {"R1", "R2"}

    def test_load_preserves_wire(self):
        res = load_kicad_sch(_MINIMAL_SCH)
        sheet = res["schematic"]._active()
        assert len(sheet.wires) == 1
        w = sheet.wires[0]
        assert len(w.points) == 2

    def test_load_preserves_junction(self):
        res = load_kicad_sch(_MINIMAL_SCH)
        sheet = res["schematic"]._active()
        assert len(sheet.junctions) == 1
        assert sheet.junctions[0].at == (20.0, 10.0)

    def test_load_preserves_label(self):
        res = load_kicad_sch(_MINIMAL_SCH)
        sheet = res["schematic"]._active()
        assert len(sheet.labels) == 1
        assert sheet.labels[0].net_name == "NODE_A"

    def test_save_kicad_sch_contains_lib_id(self):
        sch = _sch_with_sheet()
        place_symbol(sch, "Device:R", "R1", "10k", (10.0, 10.0))
        res = save_kicad_sch(sch)
        assert res["ok"] is True
        assert "Device:R" in res["kicad_sch"]

    def test_save_kicad_sch_contains_wire(self):
        sch = _sch_with_sheet()
        connect_wires(sch, [(0.0, 0.0), (10.0, 0.0)])
        res = save_kicad_sch(sch)
        assert "(wire" in res["kicad_sch"]

    def test_save_kicad_sch_contains_junction(self):
        sch = _sch_with_sheet()
        add_junction(sch, (5.0, 5.0))
        res = save_kicad_sch(sch)
        assert "(junction" in res["kicad_sch"]

    def test_save_kicad_sch_contains_label(self):
        sch = _sch_with_sheet()
        add_label(sch, (0.0, 0.0), "VCC")
        res = save_kicad_sch(sch)
        assert "VCC" in res["kicad_sch"]

    def test_load_then_save_contains_reference(self):
        """Load → save → output should contain 'R1'."""
        load_res = load_kicad_sch(_MINIMAL_SCH)
        sch2 = load_res["schematic"]
        save_res = save_kicad_sch(sch2)
        assert save_res["ok"] is True
        assert "R1" in save_res["kicad_sch"]

    def test_load_invalid_returns_error(self):
        res = load_kicad_sch("(not_a_kicad_sch)")
        assert res["ok"] is False

    def test_load_empty_returns_error(self):
        res = load_kicad_sch("")
        assert res["ok"] is False


# ──────────────────────────────────────────────────────────────────────────────
# 10. Bus expansion
# ──────────────────────────────────────────────────────────────────────────────

class TestBusExpansion:
    def test_bus_range_expansion(self):
        sch = _sch_with_sheet()
        res = expand_bus(sch, "DATA[3:0]")
        assert res["ok"] is True
        assert res["net_names"] == ["DATA3", "DATA2", "DATA1", "DATA0"]

    def test_bus_stored_on_sheet(self):
        sch = _sch_with_sheet()
        expand_bus(sch, "ADDR[1:0]")
        assert len(sch._active().buses) == 1
        assert sch._active().buses[0].name == "ADDR[1:0]"

    def test_single_net_bus(self):
        sch = _sch_with_sheet()
        res = expand_bus(sch, "CLK")
        assert res["ok"] is True
        assert res["net_names"] == ["CLK"]

    def test_empty_bus_name_error(self):
        sch = _sch_with_sheet()
        res = expand_bus(sch, "")
        assert res["ok"] is False
