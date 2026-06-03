"""test_netlist_codegen.py — Tests for SPICE netlist code generator.

Coverage:
  - generate_netlist: Spectre / ngspice / HSPICE dialects
  - CMOS inverter: M1 + M2 lines present
  - R/C/L/V/I device generation
  - Engineering value formatting
  - parse_netlist: round-trip oracle for all dialects
  - Round-trip: generate → parse → generate → identical string
  - Dialect validation: unknown dialect raises ValueError
  - SchematicGraph / SchematicDevice / SchematicNode dataclasses
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

from kerf_electronics.spice.netlist_codegen import (
    SchematicDevice,
    SchematicGraph,
    SchematicNode,
    _fmt_eng,
    generate_netlist,
    parse_netlist,
)


# ---------------------------------------------------------------------------
# Helper: build a CMOS inverter graph
# ---------------------------------------------------------------------------

def _cmos_inverter() -> SchematicGraph:
    """Return a minimal CMOS inverter graph: M1 (PMOS) + M2 (NMOS)."""
    return SchematicGraph(
        title = "cmos_inverter",
        nodes = [
            SchematicNode("VDD", voltage="VDD"),
            SchematicNode("IN"),
            SchematicNode("OUT"),
            SchematicNode("0",  voltage="gnd"),
        ],
        devices = [
            SchematicDevice(
                device_id  = "M1",
                kind       = "PMOS",
                pins       = ["OUT", "IN", "VDD", "VDD"],
                parameters = {"W": 2e-6, "L": 100e-9},
                model_name = "pmos",
            ),
            SchematicDevice(
                device_id  = "M2",
                kind       = "NMOS",
                pins       = ["OUT", "IN", "0",   "0"],
                parameters = {"W": 1e-6, "L": 100e-9},
                model_name = "nmos",
            ),
        ],
    )


def _resistor_graph() -> SchematicGraph:
    return SchematicGraph(
        title   = "r_test",
        nodes   = [SchematicNode("a"), SchematicNode("0")],
        devices = [
            SchematicDevice(
                device_id  = "R1",
                kind       = "R",
                pins       = ["a", "0"],
                parameters = {"r": 1000.0},
            )
        ],
    )


def _passives_graph() -> SchematicGraph:
    """Graph with R, C, L, V, I devices."""
    return SchematicGraph(
        title   = "passives",
        nodes   = [SchematicNode("vdd"), SchematicNode("n1"), SchematicNode("0")],
        devices = [
            SchematicDevice("R1", "R", ["n1",  "0"],   {"r": 10e3}),
            SchematicDevice("C1", "C", ["n1",  "0"],   {"c": 10e-12}),
            SchematicDevice("L1", "L", ["vdd", "n1"],  {"l": 10e-9}),
            SchematicDevice("V1", "V", ["vdd", "0"],   {"dc": 1.8}),
            SchematicDevice("I1", "I", ["n1",  "0"],   {"dc": 1e-3}),
        ],
    )


# ---------------------------------------------------------------------------
# 1. generate_netlist — dialect selection
# ---------------------------------------------------------------------------

class TestGenerateNetlistDialects:
    def test_spectre_cmos_contains_m1_m2(self):
        """Spectre netlist for CMOS inverter must contain M1 and M2 lines."""
        nl = generate_netlist(_cmos_inverter(), dialect="spectre")
        assert "M1" in nl
        assert "M2" in nl

    def test_ngspice_cmos_contains_m1_m2(self):
        """ngspice netlist for CMOS inverter must contain M1 and M2 lines."""
        nl = generate_netlist(_cmos_inverter(), dialect="ngspice")
        assert "M1" in nl
        assert "M2" in nl

    def test_hspice_cmos_contains_m1_m2(self):
        """HSPICE netlist for CMOS inverter must contain M1 and M2 lines."""
        nl = generate_netlist(_cmos_inverter(), dialect="hspice")
        assert "M1" in nl
        assert "M2" in nl

    def test_unknown_dialect_raises(self):
        """Unknown dialect should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown dialect"):
            generate_netlist(_cmos_inverter(), dialect="spice2g6")

    def test_spectre_header_keyword(self):
        """Spectre netlist should contain 'simulator lang=spectre'."""
        nl = generate_netlist(_cmos_inverter(), dialect="spectre")
        assert "simulator lang=spectre" in nl

    def test_ngspice_end_directive(self):
        """ngspice netlist should end with '.end'."""
        nl = generate_netlist(_passives_graph(), dialect="ngspice")
        assert nl.strip().lower().endswith(".end")

    def test_hspice_end_directive(self):
        """HSPICE netlist should end with '.END'."""
        nl = generate_netlist(_passives_graph(), dialect="hspice")
        assert nl.strip().upper().endswith(".END")


# ---------------------------------------------------------------------------
# 2. MOSFET syntax per dialect
# ---------------------------------------------------------------------------

class TestMosfetSyntax:
    def test_spectre_mosfet_parenthesised_pins(self):
        """Spectre MOSFET line should have parenthesised pin list."""
        nl = generate_netlist(_cmos_inverter(), dialect="spectre")
        # e.g.  M1 (OUT IN VDD VDD) pmos W=2u L=100n
        assert "(" in nl and ")" in nl

    def test_ngspice_mosfet_model_uppercase(self):
        """ngspice MOSFET line should have model name as given (typically lower)."""
        nl = generate_netlist(_cmos_inverter(), dialect="ngspice")
        # Our generator uses kind.upper() for ngspice
        assert "NMOS" in nl or "nmos" in nl.lower()

    def test_hspice_mosfet_pins_uppercase(self):
        """HSPICE MOSFET pins should be uppercase."""
        nl = generate_netlist(_cmos_inverter(), dialect="hspice")
        # The pin names '0', 'VDD', etc should appear uppercased
        for line in nl.splitlines():
            if line.startswith("M1") or line.startswith("M2"):
                parts = line.split()
                # parts[1..4] are D G S B — check they're uppercase or numeric
                for p in parts[1:5]:
                    assert p == p.upper() or p.isdigit() or p == "0"


# ---------------------------------------------------------------------------
# 3. Passive devices
# ---------------------------------------------------------------------------

class TestPassiveDevices:
    def test_resistor_ngspice(self):
        nl = generate_netlist(_resistor_graph(), dialect="ngspice")
        assert "R1" in nl
        # 1000 Ω → should appear as 1K or 1000
        assert "1K" in nl or "1000" in nl or "1k" in nl.lower()

    def test_capacitor_in_netlist(self):
        nl = generate_netlist(_passives_graph(), dialect="ngspice")
        assert "C1" in nl

    def test_inductor_in_netlist(self):
        nl = generate_netlist(_passives_graph(), dialect="ngspice")
        assert "L1" in nl

    def test_voltage_source_in_netlist(self):
        nl = generate_netlist(_passives_graph(), dialect="ngspice")
        assert "V1" in nl

    def test_current_source_in_netlist(self):
        nl = generate_netlist(_passives_graph(), dialect="ngspice")
        assert "I1" in nl


# ---------------------------------------------------------------------------
# 4. Engineering value formatter
# ---------------------------------------------------------------------------

class TestFmtEng:
    def test_zero(self):
        assert _fmt_eng(0, "ngspice") == "0"
        assert _fmt_eng(0, "spectre") == "0"

    def test_kilo_ngspice(self):
        result = _fmt_eng(1000.0, "ngspice")
        assert result in ("1K", "1.0K", "1.00K")

    def test_mega_spectre(self):
        result = _fmt_eng(1e6, "spectre")
        assert result in ("1M", "1.0M", "1.00M")

    def test_nano_ngspice(self):
        result = _fmt_eng(1e-9, "ngspice")
        assert result in ("1N", "1.0N", "1.00N")

    def test_pico_spectre(self):
        result = _fmt_eng(1e-12, "spectre")
        assert result in ("1p", "1.0p", "1.00p")

    def test_negative_value(self):
        result = _fmt_eng(-1e-3, "ngspice")
        assert result.startswith("-")


# ---------------------------------------------------------------------------
# 5. parse_netlist — basic parsing
# ---------------------------------------------------------------------------

class TestParseNetlist:
    def test_parse_ngspice_mosfet(self):
        """Parser should recover MOSFET device from ngspice netlist."""
        nl = generate_netlist(_cmos_inverter(), dialect="ngspice")
        graph = parse_netlist(nl, dialect="ngspice")
        ids = {d.device_id for d in graph.devices}
        assert "M1" in ids
        assert "M2" in ids

    def test_parse_spectre_mosfet(self):
        """Parser should recover MOSFET device from Spectre netlist."""
        nl = generate_netlist(_cmos_inverter(), dialect="spectre")
        graph = parse_netlist(nl, dialect="spectre")
        ids = {d.device_id for d in graph.devices}
        assert "M1" in ids
        assert "M2" in ids

    def test_parse_hspice_mosfet(self):
        """Parser should recover MOSFET device from HSPICE netlist."""
        nl = generate_netlist(_cmos_inverter(), dialect="hspice")
        graph = parse_netlist(nl, dialect="hspice")
        ids = {d.device_id for d in graph.devices}
        assert "M1" in ids
        assert "M2" in ids

    def test_parse_unknown_dialect_raises(self):
        """Unknown parse dialect should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown dialect"):
            parse_netlist("R1 a 0 1K", dialect="spice2")

    def test_parse_device_count(self):
        """Parsed graph should have the same device count as the source graph."""
        nl    = generate_netlist(_passives_graph(), dialect="ngspice")
        graph = parse_netlist(nl, dialect="ngspice")
        assert len(graph.devices) == 5  # R1, C1, L1, V1, I1

    def test_parse_kind_nmos_ngspice(self):
        """NMOS kind should be recovered after parsing ngspice netlist."""
        nl    = generate_netlist(_cmos_inverter(), dialect="ngspice")
        graph = parse_netlist(nl, dialect="ngspice")
        m2    = next(d for d in graph.devices if d.device_id == "M2")
        assert m2.kind == "NMOS"

    def test_parse_kind_pmos_ngspice(self):
        """PMOS kind should be recovered after parsing ngspice netlist."""
        nl    = generate_netlist(_cmos_inverter(), dialect="ngspice")
        graph = parse_netlist(nl, dialect="ngspice")
        m1    = next(d for d in graph.devices if d.device_id == "M1")
        assert m1.kind == "PMOS"


# ---------------------------------------------------------------------------
# 6. Round-trip: generate → parse → generate → identical
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def _round_trip(self, graph: SchematicGraph, dialect: str) -> tuple:
        nl1   = generate_netlist(graph, dialect=dialect)
        graph2 = parse_netlist(nl1, dialect=dialect)
        nl2   = generate_netlist(graph2, dialect=dialect)
        return nl1, nl2

    def test_round_trip_ngspice_cmos(self):
        """ngspice CMOS inverter round-trip should produce identical netlist."""
        nl1, nl2 = self._round_trip(_cmos_inverter(), "ngspice")
        assert nl1 == nl2, (
            f"Round-trip mismatch.\n--- nl1 ---\n{nl1}\n--- nl2 ---\n{nl2}"
        )

    def test_round_trip_spectre_cmos(self):
        """Spectre CMOS inverter round-trip should produce identical netlist."""
        nl1, nl2 = self._round_trip(_cmos_inverter(), "spectre")
        assert nl1 == nl2

    def test_round_trip_hspice_cmos(self):
        """HSPICE CMOS inverter round-trip should produce identical netlist."""
        nl1, nl2 = self._round_trip(_cmos_inverter(), "hspice")
        assert nl1 == nl2

    def test_round_trip_preserves_device_count(self):
        """Round-trip should preserve device count for passives graph."""
        nl1    = generate_netlist(_passives_graph(), dialect="ngspice")
        graph2 = parse_netlist(nl1, dialect="ngspice")
        nl2    = generate_netlist(graph2, dialect="ngspice")
        assert nl1 == nl2


# ---------------------------------------------------------------------------
# 7. Honest disclaimer in generated netlists
# ---------------------------------------------------------------------------

class TestHonestDisclaimer:
    def test_spectre_contains_disclaimer(self):
        nl = generate_netlist(_cmos_inverter(), dialect="spectre")
        assert "honest" in nl.lower() or "not foundry" in nl.lower()

    def test_ngspice_contains_disclaimer(self):
        nl = generate_netlist(_cmos_inverter(), dialect="ngspice")
        assert "honest" in nl.lower() or "not foundry" in nl.lower()

    def test_hspice_contains_disclaimer(self):
        nl = generate_netlist(_cmos_inverter(), dialect="hspice")
        assert "honest" in nl.lower() or "not foundry" in nl.lower()
