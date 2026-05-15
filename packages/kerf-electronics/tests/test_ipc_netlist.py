"""
Tests for IPC-D-356A netlist export and connectivity report.

T-15: IPC-D-356A netlist writer and connectivity analyser.

Tests are fully hermetic (no network I/O).  The fixture board is deliberately
constructed with a mix of pads, vias, and a net with only one pad so the
open-net detection fires reliably.
"""

import base64
import json
import re
import unittest

# Trigger @register decorators
import kerf_electronics.tools.ipc_netlist  # noqa: F401

# ─── Fixture board ─────────────────────────────────────────────────────────────
# Board layout:
#   R1-1  pcb_smtpad   layer=top_copper  net=VCC
#   R1-2  pcb_smtpad   layer=top_copper  net=GND
#   U1-1  pcb_plated_pad (PTH) drill=0.8  net=VCC
#   VIA-1 pcb_via               net=GND
#   LONELY pcb_smtpad  net=SIG_OPEN  ← only one pad on this net → open
#   NONET  pcb_smtpad  no net_id     → unconnected (N/C)

FIXTURE_CIRCUIT_JSON = [
    {
        "type": "pcb_board",
        "width": 50.0,
        "height": 40.0,
        "center_x": 25.0,
        "center_y": 20.0,
    },
    # source_components
    {
        "type": "source_component",
        "source_component_id": "sc_r1",
        "name": "R1",
        "value": "10k",
        "footprint": "R_0402",
    },
    {
        "type": "source_component",
        "source_component_id": "sc_u1",
        "name": "U1",
        "value": "MCU",
        "footprint": "DIP-8",
    },
    # R1 pad 1 — SMT, VCC net
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_r1_1",
        "source_component_id": "sc_r1",
        "net_id": "VCC",
        "x": 10.0,
        "y": 10.0,
        "width": 1.5,
        "height": 0.8,
        "shape": "rect",
        "layer": "top_copper",
    },
    # R1 pad 2 — SMT, GND net
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_r1_2",
        "source_component_id": "sc_r1",
        "net_id": "GND",
        "x": 12.0,
        "y": 10.0,
        "width": 1.5,
        "height": 0.8,
        "shape": "rect",
        "layer": "top_copper",
    },
    # U1 pin 1 — PTH, VCC net (creates second VCC point → net is connected)
    {
        "type": "pcb_plated_pad",
        "pcb_plated_pad_id": "pad_u1_1",
        "source_component_id": "sc_u1",
        "net_id": "VCC",
        "x": 20.0,
        "y": 15.0,
        "width": 1.8,
        "height": 1.8,
        "hole_diameter": 0.8,
        "shape": "circle",
        "layer": "top_copper",
    },
    # Via — GND net (creates second GND point → net is connected)
    {
        "type": "pcb_via",
        "pcb_via_id": "via_1",
        "net_id": "GND",
        "x": 30.0,
        "y": 20.0,
        "outer_diameter": 0.6,
        "hole_diameter": 0.3,
    },
    # Lonely SMT pad — SIG_OPEN net, only 1 pad → open
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_lonely_1",
        "net_id": "SIG_OPEN",
        "x": 40.0,
        "y": 30.0,
        "width": 1.0,
        "height": 1.0,
        "shape": "rect",
        "layer": "bottom_copper",
    },
    # Unconnected pad — no net_id
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_nc_1",
        "x": 45.0,
        "y": 35.0,
        "width": 1.0,
        "height": 1.0,
        "shape": "rect",
        "layer": "top_copper",
    },
]


# ─── Unit tests: export_ipc_d356 (pure function) ──────────────────────────────

class TestExportIpcD356(unittest.TestCase):

    def setUp(self):
        from kerf_electronics.tools.ipc_netlist import export_ipc_d356
        self.export = export_ipc_d356
        self.netlist = export_ipc_d356(FIXTURE_CIRCUIT_JSON, stem="test_board")

    # Header tests (IPC-D-356A §4.1)

    def test_returns_string(self):
        self.assertIsInstance(self.netlist, str)

    def test_header_job_line_present(self):
        """P JOB record required (IPC-D-356A §4.1)."""
        self.assertRegex(self.netlist, r"P\s+JOB\s+test_board")

    def test_header_code_line_present(self):
        """P CODE IPC-D-356A record required (IPC-D-356A §4.1)."""
        self.assertIn("P  CODE    IPC-D-356A", self.netlist)

    def test_header_units_mm(self):
        """P UNITS MM required for metric mode (IPC-D-356A §4.1)."""
        self.assertIn("P  UNITS   MM", self.netlist)

    def test_header_date_present(self):
        """P DATE record must appear (IPC-D-356A §4.1)."""
        self.assertRegex(self.netlist, r"P\s+DATE")

    def test_comment_lines_start_with_c(self):
        """Comment records must start with 'C' (IPC-D-356A §4.1)."""
        lines = self.netlist.splitlines()
        comment_lines = [ln for ln in lines if ln.startswith("C")]
        self.assertGreater(len(comment_lines), 0)

    def test_end_record_999_present(self):
        """File must terminate with 999 end record (IPC-D-356A §4.4)."""
        lines = [ln for ln in self.netlist.splitlines() if ln.strip()]
        self.assertEqual(lines[-1], "999")

    # Net record tests (IPC-D-356A §4.2)

    def test_317_records_present(self):
        """SMT pads produce type-317 records (IPC-D-356A §4.2.1)."""
        records_317 = [ln for ln in self.netlist.splitlines() if ln.startswith("317")]
        self.assertGreater(len(records_317), 0)

    def test_327_records_present(self):
        """PTH pads and vias produce type-327 records (IPC-D-356A §4.2.2)."""
        records_327 = [ln for ln in self.netlist.splitlines() if ln.startswith("327")]
        self.assertGreater(len(records_327), 0)

    def test_vcc_net_has_two_records(self):
        """VCC net has R1-pad-1 (SMT) + U1-pin-1 (PTH) = 2 records."""
        vcc_lines = [
            ln for ln in self.netlist.splitlines()
            if ln.startswith(("317", "327")) and "VCC" in ln
        ]
        self.assertEqual(len(vcc_lines), 2)

    def test_gnd_net_has_two_records(self):
        """GND net has R1-pad-2 (SMT) + via (PTH) = 2 records."""
        gnd_lines = [
            ln for ln in self.netlist.splitlines()
            if ln.startswith(("317", "327")) and "GND" in ln
        ]
        self.assertEqual(len(gnd_lines), 2)

    def test_sig_open_net_has_one_record(self):
        """SIG_OPEN has only 1 pad → 1 record (will be flagged as open)."""
        open_lines = [
            ln for ln in self.netlist.splitlines()
            if ln.startswith(("317", "327")) and "SIG_OPEN" in ln
        ]
        self.assertEqual(len(open_lines), 1)

    def test_mid_net_flag_on_first_vcc_record(self):
        """First record in a multi-pad net must carry 'M' mid-net flag (§4.2.3)."""
        vcc_lines = [
            ln for ln in self.netlist.splitlines()
            if ln.startswith(("317", "327")) and "VCC" in ln
        ]
        self.assertEqual(len(vcc_lines), 2)
        # First VCC record should have 'M' somewhere in cols 34-35
        self.assertIn("M ", vcc_lines[0])

    def test_last_record_of_net_has_no_mid_flag(self):
        """Last record in a net must NOT carry 'M' flag."""
        vcc_lines = [
            ln for ln in self.netlist.splitlines()
            if ln.startswith(("317", "327")) and "VCC" in ln
        ]
        # Last VCC record should not have 'M' as mid-net indicator
        # Check that '  ' (two spaces) appears where mid-flag would be
        last_line = vcc_lines[-1]
        # The mid-net field follows the plated-flag; verify no 'M ' in positions 34-35
        # In our format: record_type(3) + space(1) + net(14) + space(1) + rp(11) + space(1) + drill + plated + mid(2)
        # Position 32-33 = drill+plated, position 34-35 = mid flag
        # Total prefix = 3+1+14+1+11+1 = 31, then col 32 = drill, 33 = plated, 34-35 = mid
        mid_field = last_line[33:35]  # 0-indexed: positions 33,34
        self.assertNotEqual(mid_field, "M ")

    def test_pth_record_has_d_flag(self):
        """PTH/via records must have 'D' drilled flag (IPC-D-356A §4.2.3)."""
        records_327 = [ln for ln in self.netlist.splitlines() if ln.startswith("327")]
        self.assertGreater(len(records_327), 0)
        for rec in records_327:
            # drill flag is at position 31 (0-indexed) = col 32
            self.assertEqual(rec[31], "D", f"Record missing 'D' drilled flag: {rec!r}")

    def test_smt_record_no_drill_flag(self):
        """SMT records (317) must NOT have 'D' drilled flag."""
        records_317 = [ln for ln in self.netlist.splitlines() if ln.startswith("317")]
        self.assertGreater(len(records_317), 0)
        for rec in records_317:
            self.assertNotEqual(rec[31], "D", f"SMT record should not have 'D': {rec!r}")

    def test_coordinate_format_sign_and_digits(self):
        """Coordinates must be sign + 7 digits (IPC-D-356A §4.2.3)."""
        records = [
            ln for ln in self.netlist.splitlines()
            if ln.startswith(("317", "327"))
        ]
        self.assertGreater(len(records), 0)
        # After the fixed-width prefix (31 chars for drill/plated/midnet) the
        # X coordinate immediately follows as ±DDDDDDD
        for rec in records:
            # Extract coordinate region — starts at col 35 (0-indexed)
            coord_region = rec[35:53] if len(rec) >= 53 else ""
            self.assertRegex(
                coord_region, r"[+-]\d{7}[+-]\d{7}",
                f"Coordinate region malformed: {coord_region!r} in {rec!r}"
            )

    def test_bottom_layer_pad_gets_layer02(self):
        """SMT pad on bottom_copper must have layer code '02' (IPC-D-356A §4.2.3)."""
        sig_open_lines = [
            ln for ln in self.netlist.splitlines()
            if ln.startswith(("317", "327")) and "SIG_OPEN" in ln
        ]
        self.assertEqual(len(sig_open_lines), 1)
        # Layer code is the last 2 characters of the record
        self.assertEqual(sig_open_lines[0][-2:], "02")

    def test_through_hole_gets_layer00(self):
        """PTH via must have layer code '00' (IPC-D-356A §4.2.3)."""
        gnd_327_lines = [
            ln for ln in self.netlist.splitlines()
            if ln.startswith("327") and "GND" in ln
        ]
        self.assertGreater(len(gnd_327_lines), 0)
        # The via is GND+327; layer code should be '00'
        self.assertEqual(gnd_327_lines[0][-2:], "00")

    def test_empty_circuit_produces_header_and_end(self):
        """Empty circuit must still produce header + 999."""
        text = self.export([], stem="empty")
        self.assertIn("P  CODE    IPC-D-356A", text)
        lines = [ln for ln in text.splitlines() if ln.strip()]
        self.assertEqual(lines[-1], "999")

    def test_net_records_sorted_alphabetically(self):
        """Net records must be emitted in alphabetical net name order."""
        records = [
            ln for ln in self.netlist.splitlines()
            if ln.startswith(("317", "327"))
        ]
        # Extract net name from each record (cols 5-18, 0-indexed 4-18)
        net_names = [rec[4:18].strip() for rec in records]
        self.assertEqual(net_names, sorted(net_names),
                         "Records must appear in alphabetical net-name order")


# ─── Unit tests: analyse_connectivity ────────────────────────────────────────

class TestAnalyseConnectivity(unittest.TestCase):

    def setUp(self):
        from kerf_electronics.tools.ipc_netlist import analyse_connectivity
        self.analyse = analyse_connectivity
        self.report = analyse_connectivity(FIXTURE_CIRCUIT_JSON)

    def test_returns_dict(self):
        self.assertIsInstance(self.report, dict)

    def test_required_keys_present(self):
        for key in (
            "nets_total", "connected_nets", "open_nets",
            "single_pad_nets", "unconnected_pads", "total_pads_vias",
        ):
            self.assertIn(key, self.report, f"Missing key: {key}")

    def test_sig_open_flagged_as_open_net(self):
        """SIG_OPEN has 1 pad — must appear in open_nets."""
        open_net_names = [e["net"] for e in self.report["open_nets"]]
        self.assertIn("SIG_OPEN", open_net_names)

    def test_sig_open_in_single_pad_nets(self):
        """SIG_OPEN has exactly 1 pad — must appear in single_pad_nets."""
        single_names = [e["net"] for e in self.report["single_pad_nets"]]
        self.assertIn("SIG_OPEN", single_names)

    def test_vcc_not_in_open_nets(self):
        """VCC has 2 pads — must NOT appear in open_nets."""
        open_net_names = [e["net"] for e in self.report["open_nets"]]
        self.assertNotIn("VCC", open_net_names)

    def test_gnd_not_in_open_nets(self):
        """GND has 2 pads — must NOT appear in open_nets."""
        open_net_names = [e["net"] for e in self.report["open_nets"]]
        self.assertNotIn("GND", open_net_names)

    def test_unconnected_pads_count(self):
        """One pad has no net_id — unconnected_pads must be >= 1."""
        self.assertGreaterEqual(self.report["unconnected_pads"], 1)

    def test_connected_nets_count(self):
        """VCC and GND both have 2 pads — at least 2 connected nets."""
        self.assertGreaterEqual(self.report["connected_nets"], 2)

    def test_total_pads_vias_matches_fixture(self):
        """Fixture has 3 SMT + 1 PTH + 1 via + 1 lonely SMT + 1 N/C SMT = 7 total."""
        self.assertEqual(self.report["total_pads_vias"], 7)

    def test_empty_circuit_no_issues(self):
        report = self.analyse([])
        self.assertEqual(report["nets_total"], 0)
        self.assertEqual(report["open_nets"], [])
        self.assertEqual(report["unconnected_pads"], 0)


# ─── Internal helper tests ────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_ipc_coord_positive(self):
        from kerf_electronics.tools.ipc_netlist import _ipc_coord
        self.assertEqual(_ipc_coord(20.0), "+0200000")

    def test_ipc_coord_negative(self):
        from kerf_electronics.tools.ipc_netlist import _ipc_coord
        self.assertEqual(_ipc_coord(-5.5), "-0055000")

    def test_ipc_coord_zero(self):
        from kerf_electronics.tools.ipc_netlist import _ipc_coord
        self.assertEqual(_ipc_coord(0.0), "+0000000")

    def test_ipc_size_normal(self):
        from kerf_electronics.tools.ipc_netlist import _ipc_size
        # 1.5 mm × 10000 = 15000 counts → 5-digit minimum, zero-padded to 4+
        result = _ipc_size(1.5)
        self.assertEqual(result, "15000")

    def test_layer_code_top(self):
        from kerf_electronics.tools.ipc_netlist import _layer_code
        self.assertEqual(_layer_code("top_copper"), "01")

    def test_layer_code_bottom(self):
        from kerf_electronics.tools.ipc_netlist import _layer_code
        self.assertEqual(_layer_code("bottom_copper"), "02")

    def test_layer_code_inner(self):
        from kerf_electronics.tools.ipc_netlist import _layer_code
        # inner_1 → code 03, inner_2 → 04
        self.assertEqual(_layer_code("inner_1"), "03")
        self.assertEqual(_layer_code("inner_2"), "04")

    def test_truncate_long(self):
        from kerf_electronics.tools.ipc_netlist import _truncate
        self.assertEqual(len(_truncate("ABCDEFGHIJKLMNOP", 14)), 14)

    def test_truncate_short_pads(self):
        from kerf_electronics.tools.ipc_netlist import _truncate
        result = _truncate("VCC", 14)
        self.assertEqual(len(result), 14)
        self.assertTrue(result.endswith(" "))


# ─── LLM tool integration tests ───────────────────────────────────────────────

class TestIpcNetlistTool(unittest.IsolatedAsyncioTestCase):

    async def test_tool_registered(self):
        from kerf_chat.tools.registry import Registry
        names = {t.spec.name for t in Registry}
        self.assertIn("export_ipc_netlist", names)

    async def test_netlist_report_tool_registered(self):
        from kerf_chat.tools.registry import Registry
        names = {t.spec.name for t in Registry}
        self.assertIn("netlist_report", names)

    async def test_export_ipc_netlist_runs(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_ipc_netlist")
        payload = json.dumps({
            "circuit_json": FIXTURE_CIRCUIT_JSON,
            "stem": "tool_test",
        }).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertNotIn("error", result, result)
        self.assertIn("content_b64", result)
        self.assertIn("record_count", result)
        # Decode and verify it's valid text
        text = base64.b64decode(result["content_b64"]).decode("ascii")
        self.assertIn("P  CODE    IPC-D-356A", text)
        self.assertIn("999", text)

    async def test_export_ipc_netlist_counts(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_ipc_netlist")
        payload = json.dumps({
            "circuit_json": FIXTURE_CIRCUIT_JSON,
            "stem": "tool_test",
        }).encode()
        result = json.loads(await tool.run(None, payload))
        # 4 pads (3 SMT + 1 pth) + 1 via = 5 records (N/C pad gets emitted too as N/C net)
        self.assertGreaterEqual(result["record_count"], 5)
        self.assertGreater(result["records_317_smt"], 0)
        self.assertGreater(result["records_327_pth"], 0)

    async def test_export_bad_args(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_ipc_netlist")
        payload = json.dumps({"circuit_json": "not-an-array"}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertIn("error", result)

    async def test_netlist_report_runs(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "netlist_report")
        payload = json.dumps({"circuit_json": FIXTURE_CIRCUIT_JSON}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertNotIn("error", result, result)
        self.assertIn("open_nets", result)
        self.assertIn("status", result)

    async def test_netlist_report_flags_open(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "netlist_report")
        payload = json.dumps({"circuit_json": FIXTURE_CIRCUIT_JSON}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertEqual(result["status"], "ISSUES_FOUND")
        open_names = [e["net"] for e in result["open_nets"]]
        self.assertIn("SIG_OPEN", open_names)

    async def test_netlist_report_ok_on_clean_circuit(self):
        """A circuit with every net having >= 2 pads reports OK status."""
        clean_circuit = [
            {
                "type": "pcb_smtpad",
                "pcb_smtpad_id": "p1",
                "net_id": "NETX",
                "x": 0.0, "y": 0.0,
                "width": 1.0, "height": 1.0,
                "layer": "top_copper",
            },
            {
                "type": "pcb_smtpad",
                "pcb_smtpad_id": "p2",
                "net_id": "NETX",
                "x": 5.0, "y": 0.0,
                "width": 1.0, "height": 1.0,
                "layer": "top_copper",
            },
        ]
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "netlist_report")
        payload = json.dumps({"circuit_json": clean_circuit}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertEqual(result["status"], "OK")
        self.assertEqual(result["open_nets"], [])


if __name__ == "__main__":
    unittest.main()
