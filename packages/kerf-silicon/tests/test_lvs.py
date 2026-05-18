"""test_lvs.py — pytest suite for kerf_silicon.lvs (extractor + compare).

Synthetic layout: 2-cell inverter chain.

  INV1 (nmos+pmos pair, simplified as single-cell "inv"):
    ports: A (in), Z (out), VDD, VSS

  INV2 (same):
    ports: A (in), Z (out), VDD, VSS

  Nets:
    - VDD   : INV1/VDD, INV2/VDD          (power)
    - VSS   : INV1/VSS, INV2/VSS          (ground)
    - net_w : INV1/Z,   INV2/A            (internal wire: inv1-out → inv2-in)
"""
import pytest

from kerf_silicon.lvs.extractor import extract, Netlist, CellInstance, Net
from kerf_silicon.lvs.compare import lvs_match, LvsReport


# ---------------------------------------------------------------------------
# Synthetic layout fixture
# ---------------------------------------------------------------------------

def _make_inv_chain_layout() -> dict:
    """Return a minimal layout dict representing a 2-inverter chain."""
    return {
        "cells": [
            {
                "ref": "INV1",
                "type": "inv",
                "ports": [
                    {"name": "A",   "net": "net_in"},
                    {"name": "Z",   "net": "net_w"},
                    {"name": "VDD", "net": "VDD"},
                    {"name": "VSS", "net": "VSS"},
                ],
            },
            {
                "ref": "INV2",
                "type": "inv",
                "ports": [
                    {"name": "A",   "net": "net_w"},
                    {"name": "Z",   "net": "net_out"},
                    {"name": "VDD", "net": "VDD"},
                    {"name": "VSS", "net": "VSS"},
                ],
            },
        ],
        # Minimal polygon layer (touches propagate into three groups)
        "polygons": [
            {"id": "p1", "layer": "M1", "net": "VDD",    "touches": ["p2"]},
            {"id": "p2", "layer": "M1", "net": "VDD",    "touches": ["p1"]},
            {"id": "p3", "layer": "M1", "net": "VSS",    "touches": ["p4"]},
            {"id": "p4", "layer": "M1", "net": "VSS",    "touches": ["p3"]},
            {"id": "p5", "layer": "M1", "net": "net_w",  "touches": []},
        ],
        "vias": [],
    }


def _make_tech() -> dict:
    return {"connected_layers": [["M1", "M2"]]}


def _make_reference_netlist() -> Netlist:
    """Build the expected reference netlist for the inverter chain."""
    cells = [
        CellInstance(ref="INV1", cell_type="inv", ports=["A", "Z", "VDD", "VSS"]),
        CellInstance(ref="INV2", cell_type="inv", ports=["A", "Z", "VDD", "VSS"]),
    ]
    nets = [
        Net(name="net_in",  pin_refs=["INV1/A"]),
        Net(name="net_w",   pin_refs=["INV1/Z", "INV2/A"]),
        Net(name="VDD",     pin_refs=["INV1/VDD", "INV2/VDD"]),
        Net(name="VSS",     pin_refs=["INV1/VSS", "INV2/VSS"]),
        Net(name="net_out", pin_refs=["INV2/Z"]),
    ]
    return Netlist(cells=cells, nets=nets)


# ---------------------------------------------------------------------------
# Extractor tests
# ---------------------------------------------------------------------------

class TestExtractor:
    def test_extract_returns_two_cells(self):
        layout = _make_inv_chain_layout()
        netlist = extract(layout, _make_tech())
        assert len(netlist.cells) == 2

    def test_extract_cell_refs(self):
        layout = _make_inv_chain_layout()
        netlist = extract(layout, _make_tech())
        refs = {c.ref for c in netlist.cells}
        assert refs == {"INV1", "INV2"}

    def test_extract_cell_types(self):
        layout = _make_inv_chain_layout()
        netlist = extract(layout, _make_tech())
        for cell in netlist.cells:
            assert cell.cell_type == "inv"

    def test_extract_returns_correct_net_count(self):
        """net_in + net_w + VDD + VSS + net_out = 5 nets."""
        layout = _make_inv_chain_layout()
        netlist = extract(layout, _make_tech())
        assert len(netlist.nets) == 5

    def test_extract_net_names(self):
        layout = _make_inv_chain_layout()
        netlist = extract(layout, _make_tech())
        names = {n.name for n in netlist.nets}
        assert {"net_w", "VDD", "VSS"}.issubset(names)

    def test_extract_net_w_has_two_pins(self):
        """net_w connects INV1/Z and INV2/A."""
        layout = _make_inv_chain_layout()
        netlist = extract(layout, _make_tech())
        net_w = next(n for n in netlist.nets if n.name == "net_w")
        assert set(net_w.pin_refs) == {"INV1/Z", "INV2/A"}

    def test_extract_vdd_has_two_pins(self):
        layout = _make_inv_chain_layout()
        netlist = extract(layout, _make_tech())
        vdd = next(n for n in netlist.nets if n.name == "VDD")
        assert set(vdd.pin_refs) == {"INV1/VDD", "INV2/VDD"}

    def test_extract_cell_ports_preserved(self):
        layout = _make_inv_chain_layout()
        netlist = extract(layout, _make_tech())
        inv1 = next(c for c in netlist.cells if c.ref == "INV1")
        assert inv1.ports == ["A", "Z", "VDD", "VSS"]

    def test_extract_no_layout(self):
        """Empty layout yields empty netlist."""
        netlist = extract({}, None)
        assert netlist.cells == []
        assert netlist.nets == []

    def test_extract_polygon_touching_merges_nets(self):
        """Two polygons that touch and share the same net label produce one net."""
        layout = {
            "polygons": [
                {"id": "a", "layer": "M1", "net": "VDD", "touches": ["b"]},
                {"id": "b", "layer": "M1", "net": "VDD", "touches": ["a"]},
            ],
            "vias": [],
            "cells": [],
        }
        netlist = extract(layout, None)
        vdd_nets = [n for n in netlist.nets if n.name == "VDD"]
        assert len(vdd_nets) == 1

    def test_extract_via_merges_polygons(self):
        """A via between two polygons causes them to share a net."""
        layout = {
            "polygons": [
                {"id": "m1p", "layer": "M1", "net": "SIG", "touches": []},
                {"id": "m2p", "layer": "M2", "net": "SIG", "touches": []},
            ],
            "vias": [{"lower_poly": "m1p", "upper_poly": "m2p"}],
            "cells": [],
        }
        netlist = extract(layout, {"connected_layers": [["M1", "M2"]]})
        sig_nets = [n for n in netlist.nets if n.name == "SIG"]
        assert len(sig_nets) == 1


# ---------------------------------------------------------------------------
# LVS compare tests
# ---------------------------------------------------------------------------

class TestLvsMatch:
    def _extracted(self) -> Netlist:
        return extract(_make_inv_chain_layout(), _make_tech())

    def test_match_against_identical_reference(self):
        extracted = self._extracted()
        reference = _make_reference_netlist()
        report = lvs_match(extracted, reference)
        assert report.matched is True
        assert report.cell_diffs == []
        assert report.net_diffs == []

    def test_summary_clean(self):
        extracted = self._extracted()
        reference = _make_reference_netlist()
        report = lvs_match(extracted, reference)
        assert "CLEAN" in report.summary

    def test_extra_cell_in_reference_causes_failure(self):
        """Reference has an extra cell INV3 not in extracted."""
        extracted = self._extracted()
        reference = _make_reference_netlist()
        reference.cells.append(
            CellInstance(ref="INV3", cell_type="inv", ports=["A", "Z", "VDD", "VSS"])
        )
        # Also add the nets that INV3 would drive so the only diff is the cell
        reference.nets.append(Net(name="net_out2", pin_refs=["INV3/Z"]))
        report = lvs_match(extracted, reference)
        assert report.matched is False
        missing_refs = {d.ref for d in report.cell_diffs if d.kind == "missing_in_extracted"}
        assert "INV3" in missing_refs

    def test_extra_cell_in_reference_has_cell_diff(self):
        extracted = self._extracted()
        reference = _make_reference_netlist()
        reference.cells.append(
            CellInstance(ref="INV3", cell_type="inv", ports=["A", "Z", "VDD", "VSS"])
        )
        report = lvs_match(extracted, reference)
        assert any(d.kind == "missing_in_extracted" for d in report.cell_diffs)

    def test_missing_net_in_reference_causes_failure(self):
        """Reference is missing net_w compared to extracted."""
        extracted = self._extracted()
        reference = _make_reference_netlist()
        # Remove net_w from reference; extracted still has it → extra_in_extracted diff
        reference.nets = [n for n in reference.nets if n.name != "net_w"]
        # Also disconnect the ports from extracted side to isolate net diff:
        # Actually we just test the net diff path — extracted has net_w, reference does not.
        report = lvs_match(extracted, reference)
        assert report.matched is False
        extra_nets = {d.net_name for d in report.net_diffs if d.kind == "extra_in_extracted"}
        assert "net_w" in extra_nets

    def test_missing_net_has_net_diff(self):
        extracted = self._extracted()
        reference = _make_reference_netlist()
        reference.nets = [n for n in reference.nets if n.name != "net_w"]
        report = lvs_match(extracted, reference)
        assert any(d.kind == "extra_in_extracted" for d in report.net_diffs)

    def test_summary_fail_mentions_differences(self):
        extracted = self._extracted()
        reference = _make_reference_netlist()
        reference.cells.append(
            CellInstance(ref="EXTRA", cell_type="buf", ports=["A", "Z"])
        )
        report = lvs_match(extracted, reference)
        assert "FAIL" in report.summary
        assert "cell difference" in report.summary

    def test_cell_type_mismatch_causes_failure(self):
        extracted = self._extracted()
        reference = _make_reference_netlist()
        # Change INV2 type in reference to "buf"
        for c in reference.cells:
            if c.ref == "INV2":
                c.cell_type = "buf"
        report = lvs_match(extracted, reference)
        assert report.matched is False
        assert any(d.kind == "port_mismatch" and d.ref == "INV2" for d in report.cell_diffs)

    def test_net_pin_mismatch_causes_failure(self):
        extracted = self._extracted()
        reference = _make_reference_netlist()
        # Give VDD an extra pin in reference
        for n in reference.nets:
            if n.name == "VDD":
                n.pin_refs.append("INV3/VDD")
        report = lvs_match(extracted, reference)
        assert report.matched is False
        assert any(d.kind == "pin_mismatch" and d.net_name == "VDD" for d in report.net_diffs)

    def test_lvs_report_dataclass_fields(self):
        report = LvsReport(matched=True)
        assert hasattr(report, "cell_diffs")
        assert hasattr(report, "net_diffs")
        assert report.cell_diffs == []
        assert report.net_diffs == []
