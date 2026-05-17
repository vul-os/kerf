"""
test_pads_reader.py — pytest suite for pads_reader.py.

All fixtures are synthetic PADS ASCII strings constructed in-test.
No real PADS files are used.  Tests cover:
  - *PART* section: part count parsed
  - *PART* section: ref/part_type extracted
  - *PART* section: x/y/rotation from layout form
  - *PART* section: top layer flag (0 → Top)
  - *PART* section: bottom layer flag (1 → Bottom)
  - *PART* section: T/B string layer flags
  - *NET* section: net count parsed
  - *NET* section: net name extracted
  - *NET* section: pin list populated
  - *NET* section: dash-separated pins normalised to dot form
  - *NET* section: header with pin count integer
  - *ROUTE* section: signal count
  - *ROUTE* section: signal name extracted
  - *ROUTE* section: wire coordinates parsed
  - *SIGNAL* alias for *NET* accepted
  - comment lines (! and ;) skipped
  - blank lines skipped
  - unknown section emits warning
  - empty string → {"ok": False}
  - no PADS markers → {"ok": False}
  - bytes (UTF-8) input accepted
  - footprints mirror parts
  - footprint count matches part count
  - part with no coordinates gives None for x/y
"""

from __future__ import annotations

import pytest

from kerf_imports.pads_reader import parse_pads


# ---------------------------------------------------------------------------
# Minimal PADS PCB netlist fixture
# ---------------------------------------------------------------------------

_MINIMAL_PADS = """\
*PADS2000*

! PADS PCB ASCII format test fixture

*PART*
R1   RES-0805    10.5   20.3   0.0   0
R2   RES-0805    15.0   20.3   90.0  0
C1   CAP-0402    5.0    30.0   0.0   1
U1   NE555       25.0   15.0   180.0 0

*NET*
VCC 3
U1.8 C1.1 R1.2
GND 2
R1.1 R2.1
OUT 2
U1.3 R1.2

*ROUTE*
VCC
10.5 20.3 5.0 30.0 1
5.0 30.0 25.0 15.0 1
GND
15.0 20.3 25.0 15.0 2

*END*
"""

# ---------------------------------------------------------------------------
# PADS Logic netlist fixture (simple, no coordinates)
# ---------------------------------------------------------------------------

_LOGIC_PADS = """\
*PADS2000*

*PART*
R1 RES-0805
R2 RES-0805
C1 CAP-0402
U1 NE555
U2 LM317

*NET*
PWR 2
U1.8 C1.1
AGND 3
R1.1 R2.1 U2.2

*END*
"""

# ---------------------------------------------------------------------------
# PADS with *SIGNAL* section alias and T/B layer flags
# ---------------------------------------------------------------------------

_SIGNAL_ALIAS_PADS = """\
*PADS2000*

*PART*
D1 LED-0805 1.0 2.0 45.0 T
D2 LED-0805 3.0 4.0 0.0 B

*SIGNAL*
ANODE 2
D1.A D2.A

*END*
"""

# ---------------------------------------------------------------------------
# PADS with comment lines and dash-separator in pin refs
# ---------------------------------------------------------------------------

_COMMENT_AND_DASH_PADS = """\
*PADS2000*
; semicolon comment
! exclamation comment

*PART*
Q1 2N3904

*NET*
BASE 1
! another comment
Q1-B

*END*
"""


# ===========================================================================
# Tests
# ===========================================================================

class TestPartSection:
    def test_part_count(self):
        r = parse_pads(_MINIMAL_PADS)
        assert r["ok"] is True
        assert len(r["parts"]) == 4

    def test_r1_ref(self):
        r = parse_pads(_MINIMAL_PADS)
        refs = {p["ref"] for p in r["parts"]}
        assert "R1" in refs

    def test_r1_part_type(self):
        r = parse_pads(_MINIMAL_PADS)
        r1 = next(p for p in r["parts"] if p["ref"] == "R1")
        assert r1["part_type"] == "RES-0805"

    def test_r1_x_coordinate(self):
        r = parse_pads(_MINIMAL_PADS)
        r1 = next(p for p in r["parts"] if p["ref"] == "R1")
        assert r1["x"] == pytest.approx(10.5)

    def test_r1_y_coordinate(self):
        r = parse_pads(_MINIMAL_PADS)
        r1 = next(p for p in r["parts"] if p["ref"] == "R1")
        assert r1["y"] == pytest.approx(20.3)

    def test_r2_rotation(self):
        r = parse_pads(_MINIMAL_PADS)
        r2 = next(p for p in r["parts"] if p["ref"] == "R2")
        assert r2["rot"] == pytest.approx(90.0)

    def test_r1_top_layer(self):
        r = parse_pads(_MINIMAL_PADS)
        r1 = next(p for p in r["parts"] if p["ref"] == "R1")
        assert r1["layer"] == "Top"

    def test_c1_bottom_layer(self):
        r = parse_pads(_MINIMAL_PADS)
        c1 = next(p for p in r["parts"] if p["ref"] == "C1")
        assert c1["layer"] == "Bottom"

    def test_t_flag_is_top(self):
        r = parse_pads(_SIGNAL_ALIAS_PADS)
        d1 = next(p for p in r["parts"] if p["ref"] == "D1")
        assert d1["layer"] == "Top"

    def test_b_flag_is_bottom(self):
        r = parse_pads(_SIGNAL_ALIAS_PADS)
        d2 = next(p for p in r["parts"] if p["ref"] == "D2")
        assert d2["layer"] == "Bottom"

    def test_no_coords_gives_none(self):
        r = parse_pads(_LOGIC_PADS)
        r1 = next(p for p in r["parts"] if p["ref"] == "R1")
        assert r1["x"] is None
        assert r1["y"] is None


class TestNetSection:
    def test_net_count(self):
        r = parse_pads(_MINIMAL_PADS)
        assert len(r["nets"]) == 3

    def test_net_names(self):
        r = parse_pads(_MINIMAL_PADS)
        names = {n["name"] for n in r["nets"]}
        assert {"VCC", "GND", "OUT"} == names

    def test_vcc_pins(self):
        r = parse_pads(_MINIMAL_PADS)
        vcc = next(n for n in r["nets"] if n["name"] == "VCC")
        assert "U1.8" in vcc["pins"]
        assert "C1.1" in vcc["pins"]

    def test_gnd_pin_count(self):
        r = parse_pads(_MINIMAL_PADS)
        gnd = next(n for n in r["nets"] if n["name"] == "GND")
        assert len(gnd["pins"]) == 2

    def test_net_with_header_int(self):
        r = parse_pads(_MINIMAL_PADS)
        assert r["ok"] is True

    def test_logic_net_count(self):
        r = parse_pads(_LOGIC_PADS)
        assert len(r["nets"]) == 2

    def test_logic_pwr_net(self):
        r = parse_pads(_LOGIC_PADS)
        pwr = next(n for n in r["nets"] if n["name"] == "PWR")
        assert "U1.8" in pwr["pins"]

    def test_signal_alias_accepted(self):
        r = parse_pads(_SIGNAL_ALIAS_PADS)
        assert r["ok"] is True
        assert len(r["nets"]) == 1

    def test_signal_alias_net_name(self):
        r = parse_pads(_SIGNAL_ALIAS_PADS)
        assert r["nets"][0]["name"] == "ANODE"

    def test_dash_separator_normalised(self):
        r = parse_pads(_COMMENT_AND_DASH_PADS)
        base = next(n for n in r["nets"] if n["name"] == "BASE")
        # Q1-B should be normalised to Q1.B
        assert "Q1.B" in base["pins"]


class TestRouteSection:
    def test_signal_count(self):
        r = parse_pads(_MINIMAL_PADS)
        assert len(r["signals"]) == 2

    def test_signal_names(self):
        r = parse_pads(_MINIMAL_PADS)
        names = {s["name"] for s in r["signals"]}
        assert {"VCC", "GND"} == names

    def test_vcc_wire_count(self):
        r = parse_pads(_MINIMAL_PADS)
        vcc = next(s for s in r["signals"] if s["name"] == "VCC")
        assert len(vcc["wires"]) == 2

    def test_vcc_first_wire_coords(self):
        r = parse_pads(_MINIMAL_PADS)
        vcc = next(s for s in r["signals"] if s["name"] == "VCC")
        w = vcc["wires"][0]
        assert w["x1"] == pytest.approx(10.5)
        assert w["y1"] == pytest.approx(20.3)
        assert w["x2"] == pytest.approx(5.0)
        assert w["y2"] == pytest.approx(30.0)

    def test_gnd_wire_layer(self):
        r = parse_pads(_MINIMAL_PADS)
        gnd = next(s for s in r["signals"] if s["name"] == "GND")
        assert gnd["wires"][0]["layer"] == "2"


class TestFootprints:
    def test_footprint_count_matches_parts(self):
        r = parse_pads(_MINIMAL_PADS)
        assert len(r["footprints"]) == len(r["parts"])

    def test_footprint_has_ref(self):
        r = parse_pads(_MINIMAL_PADS)
        for fp in r["footprints"]:
            assert "ref" in fp


class TestCommentHandling:
    def test_comments_skipped(self):
        r = parse_pads(_COMMENT_AND_DASH_PADS)
        assert r["ok"] is True
        assert len(r["parts"]) == 1

    def test_semicolon_comment_skipped(self):
        r = parse_pads(_COMMENT_AND_DASH_PADS)
        assert r["ok"] is True


class TestErrorHandling:
    def test_empty_string_not_ok(self):
        r = parse_pads("")
        assert r["ok"] is False

    def test_no_pads_markers_not_ok(self):
        r = parse_pads("just some random text with no markers")
        assert r["ok"] is False

    def test_not_ok_has_reason(self):
        r = parse_pads("")
        assert "reason" in r

    def test_bytes_utf8_accepted(self):
        r = parse_pads(_MINIMAL_PADS.encode("utf-8"))
        assert r["ok"] is True
        assert len(r["parts"]) == 4

    def test_unknown_section_warning(self):
        pads = "*PADS2000*\n*FUTURISTIC_SECTION*\nsome data\n*END*\n"
        r = parse_pads(pads)
        assert r["ok"] is True
        assert any("FUTURISTIC_SECTION" in w for w in r["warnings"])
