"""
test_geda_reader.py — pytest suite for geda_reader.py.

All fixtures are synthetic gEDA text strings constructed in-test.
No real gEDA files are used.  Tests cover:
  - gschem source detected
  - PCB source detected
  - gschem: part count parsed
  - gschem: ref from refdes= attribute
  - gschem: value from value= attribute
  - gschem: footprint from footprint= attribute
  - gschem: basename from C line
  - gschem: x/y coordinates from C line
  - gschem: net connections via net= attribute reconstructed
  - gschem: net name extracted
  - gschem: multiple components in one schematic
  - PCB: footprint count from Element declarations
  - PCB: element ref extracted
  - PCB: element x/y parsed
  - PCB: nets from Net() declarations
  - PCB: net name extracted
  - PCB: net pin mapping
  - PCB: wire segments parsed
  - PCB: via coordinates and drill parsed
  - empty input → {"ok": False}
  - bytes (UTF-8) accepted
  - unknown source still returns ok with warning
"""

from __future__ import annotations

import pytest

from kerf_imports.geda_reader import parse_geda


# ---------------------------------------------------------------------------
# Synthetic gschem fixture
# ---------------------------------------------------------------------------

_GSCHEM = """\
v 20210605 2
C 1000 1000 1 0 0 resistor-1.sym
{
T 1050 1050 5 10 1 1 0 0 1
refdes=R1
T 1050 1100 5 10 1 1 0 0 1
value=10k
T 1050 1150 5 10 1 1 0 0 1
footprint=R_0805
T 1050 1200 5 10 1 1 0 0 1
net=VCC:1,GND:2
}
C 2000 1000 1 0 0 capacitor-1.sym
{
T 2050 1050 5 10 1 1 0 0 1
refdes=C1
T 2050 1100 5 10 1 1 0 0 1
value=100nF
T 2050 1150 5 10 1 1 0 0 1
footprint=C_0402
T 2050 1200 5 10 1 1 0 0 1
net=VCC:1,GND:2
}
C 3000 1000 1 0 0 ne555-1.sym
{
T 3050 1050 5 10 1 1 0 0 1
refdes=U1
T 3050 1100 5 10 1 1 0 0 1
value=NE555
T 3050 1150 5 10 1 1 0 0 1
footprint=DIP8
T 3050 1200 5 10 1 1 0 0 1
net=VCC:8,GND:1,OUT:3
}
"""

# ---------------------------------------------------------------------------
# Synthetic gEDA PCB fixture
# ---------------------------------------------------------------------------

_PCB = """\
PCBName("TestBoard")

Element["" "R_0805" "R1" "10k" 10500 20300 500 1000 0 100 ""]
(
  Pad[-1778 0 1778 0 1270 700 1600 "1" "1" "square,nopaste"]
  Pad[-1778 0 1778 0 1270 700 1600 "2" "2" "square,nopaste"]
)

Element["" "C_0402" "C1" "100nF" 5000 30000 500 1000 0 100 ""]
(
  Pad[-508 0 508 0 508 250 800 "1" "1" "square,nopaste"]
  Pad[-508 0 508 0 508 250 800 "2" "2" "square,nopaste"]
)

Element["" "DIP8" "U1" "NE555" 25000 15000 500 1000 0 100 ""]
(
  Pin[0 0 6000 2000 6600 3200 "" "1" ""]
  Pin[5000 0 6000 2000 6600 3200 "" "2" ""]
)

NetList()
(
  Net("VCC" "R1.1")
  Net("VCC" "C1.1")
  Net("VCC" "U1.8")
  Net("GND" "R1.2")
  Net("GND" "C1.2")
)

Line[10500 20300 5000 30000 2540 1270 ""]
Line[5000 30000 25000 15000 2540 1270 ""]
Via[12000 22000 5500 1270 6100 3200 "" ""]
"""


# ===========================================================================
# Tests
# ===========================================================================

class TestGschemSource:
    def test_source_is_sch(self):
        r = parse_geda(_GSCHEM)
        assert r["ok"] is True
        assert r["source"] == "sch"

    def test_pcb_source_is_pcb(self):
        r = parse_geda(_PCB)
        assert r["ok"] is True
        assert r["source"] == "pcb"


class TestGschemParts:
    def test_part_count(self):
        r = parse_geda(_GSCHEM)
        assert r["ok"] is True
        assert len(r["parts"]) == 3

    def test_r1_ref(self):
        r = parse_geda(_GSCHEM)
        refs = {p["ref"] for p in r["parts"]}
        assert "R1" in refs

    def test_r1_value(self):
        r = parse_geda(_GSCHEM)
        r1 = next(p for p in r["parts"] if p["ref"] == "R1")
        assert r1["value"] == "10k"

    def test_r1_footprint(self):
        r = parse_geda(_GSCHEM)
        r1 = next(p for p in r["parts"] if p["ref"] == "R1")
        assert r1["footprint"] == "R_0805"

    def test_r1_basename(self):
        r = parse_geda(_GSCHEM)
        r1 = next(p for p in r["parts"] if p["ref"] == "R1")
        assert r1["basename"] == "resistor-1.sym"

    def test_r1_x_coord(self):
        r = parse_geda(_GSCHEM)
        r1 = next(p for p in r["parts"] if p["ref"] == "R1")
        assert r1["x"] == pytest.approx(1000.0)

    def test_r1_y_coord(self):
        r = parse_geda(_GSCHEM)
        r1 = next(p for p in r["parts"] if p["ref"] == "R1")
        assert r1["y"] == pytest.approx(1000.0)

    def test_u1_ref_present(self):
        r = parse_geda(_GSCHEM)
        refs = {p["ref"] for p in r["parts"]}
        assert "U1" in refs


class TestGschemNets:
    def test_nets_extracted(self):
        r = parse_geda(_GSCHEM)
        assert len(r["nets"]) > 0

    def test_vcc_net_present(self):
        r = parse_geda(_GSCHEM)
        names = {n["name"] for n in r["nets"]}
        assert "VCC" in names

    def test_gnd_net_present(self):
        r = parse_geda(_GSCHEM)
        names = {n["name"] for n in r["nets"]}
        assert "GND" in names

    def test_vcc_has_r1_pin(self):
        r = parse_geda(_GSCHEM)
        vcc = next(n for n in r["nets"] if n["name"] == "VCC")
        assert "R1.1" in vcc["pins"]

    def test_out_net_has_u1_pin(self):
        r = parse_geda(_GSCHEM)
        out = next((n for n in r["nets"] if n["name"] == "OUT"), None)
        assert out is not None
        assert "U1.3" in out["pins"]


class TestPCBElements:
    def test_footprint_count(self):
        r = parse_geda(_PCB)
        assert len(r["footprints"]) == 3

    def test_r1_ref(self):
        r = parse_geda(_PCB)
        refs = {fp["ref"] for fp in r["footprints"]}
        assert "R1" in refs

    def test_r1_x_coord(self):
        r = parse_geda(_PCB)
        r1 = next(fp for fp in r["footprints"] if fp["ref"] == "R1")
        assert r1["x"] == pytest.approx(10500.0)

    def test_r1_y_coord(self):
        r = parse_geda(_PCB)
        r1 = next(fp for fp in r["footprints"] if fp["ref"] == "R1")
        assert r1["y"] == pytest.approx(20300.0)


class TestPCBNets:
    def test_net_count(self):
        r = parse_geda(_PCB)
        # VCC and GND groups
        assert len(r["nets"]) >= 2

    def test_vcc_net_present(self):
        r = parse_geda(_PCB)
        names = {n["name"] for n in r["nets"]}
        assert "VCC" in names

    def test_vcc_has_r1_pin(self):
        r = parse_geda(_PCB)
        vcc = next(n for n in r["nets"] if n["name"] == "VCC")
        assert "R1.1" in vcc["pins"]

    def test_gnd_net_present(self):
        r = parse_geda(_PCB)
        names = {n["name"] for n in r["nets"]}
        assert "GND" in names


class TestPCBRouting:
    def test_signals_present(self):
        r = parse_geda(_PCB)
        # Wire segments are grouped into a signal entry
        total_wires = sum(len(s["wires"]) for s in r["signals"])
        assert total_wires >= 2

    def test_via_present(self):
        r = parse_geda(_PCB)
        total_vias = sum(len(s["vias"]) for s in r["signals"])
        assert total_vias >= 1

    def test_wire_has_coords(self):
        r = parse_geda(_PCB)
        wire = r["signals"][0]["wires"][0]
        assert "x1" in wire
        assert "y1" in wire


class TestErrorHandling:
    def test_empty_string_not_ok(self):
        r = parse_geda("")
        assert r["ok"] is False

    def test_empty_bytes_not_ok(self):
        r = parse_geda(b"")
        assert r["ok"] is False

    def test_not_ok_has_reason(self):
        r = parse_geda("")
        assert "reason" in r

    def test_bytes_utf8_accepted(self):
        r = parse_geda(_GSCHEM.encode("utf-8"))
        assert r["ok"] is True

    def test_unknown_source_still_ok(self):
        # A file with no 'v ' prefix and no Element[ is "unknown"
        r = parse_geda("just text without eagle or geda markers\nC 1 2 3 4 5 dummy.sym\n")
        assert r["ok"] is True  # best-effort parse
