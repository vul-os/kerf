"""
Tests for testpoint auto-placement and bed-of-nails fixture report.

Tests are fully hermetic (no network I/O).

Fixture board topology:
  VCC  — SMT top (R1-1) + PTH (U1-1)                   → 2 candidates, PTH wins
  GND  — SMT top (R1-2) + via                           → 2 candidates, via wins
  SIG  — SMT top (C1-1) + SMT bottom (C1-2)             → 2 candidates, top wins
  PWR  — PTH only (J1-1)                                → 1 candidate, PTH placed
  OPEN — single SMT pad far from others                  → placed (no conflict here)
  N/C  — pad with no net                                → excluded from probe list
  CONFLICT1 / CONFLICT2 — two nets sharing same grid cell → second flagged unreachable
"""

import csv
import io
import json
import math
import unittest

# Trigger @register decorators
import kerf_electronics.tools.testpoint  # noqa: F401

# ─── Fixture board ─────────────────────────────────────────────────────────────
# Coordinates chosen so most pads are well-separated (> 2.54 mm apart),
# but CONFLICT1 and CONFLICT2 snap to the same 2.54-mm grid cell.

FIXTURE_CIRCUIT_JSON = [
    {
        "type": "pcb_board",
        "width": 80.0,
        "height": 60.0,
        "center_x": 40.0,
        "center_y": 30.0,
    },
    # Source components
    {
        "type": "source_component",
        "source_component_id": "sc_r1",
        "name": "R1",
    },
    {
        "type": "source_component",
        "source_component_id": "sc_u1",
        "name": "U1",
    },
    {
        "type": "source_component",
        "source_component_id": "sc_c1",
        "name": "C1",
    },
    {
        "type": "source_component",
        "source_component_id": "sc_j1",
        "name": "J1",
    },
    # ── VCC net ──────────────────────────────────────────────────────────────
    # R1-1: SMT top
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_r1_1",
        "source_component_id": "sc_r1",
        "net_id": "VCC",
        "x": 5.0, "y": 5.0,
        "width": 1.5, "height": 0.8,
        "layer": "top_copper",
    },
    # U1-1: PTH (higher priority than SMT for probing)
    {
        "type": "pcb_plated_pad",
        "pcb_plated_pad_id": "pad_u1_1",
        "source_component_id": "sc_u1",
        "net_id": "VCC",
        "x": 10.0, "y": 5.0,
        "width": 1.8, "height": 1.8,
        "hole_diameter": 0.8,
        "layer": "top_copper",
    },
    # ── GND net ───────────────────────────────────────────────────────────────
    # R1-2: SMT top
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_r1_2",
        "source_component_id": "sc_r1",
        "net_id": "GND",
        "x": 5.0, "y": 10.0,
        "width": 1.5, "height": 0.8,
        "layer": "top_copper",
    },
    # Via on GND (highest priority — via beats SMT)
    {
        "type": "pcb_via",
        "pcb_via_id": "via_gnd_1",
        "net_id": "GND",
        "x": 20.0, "y": 10.0,
        "outer_diameter": 0.6,
        "hole_diameter": 0.3,
    },
    # ── SIG net ───────────────────────────────────────────────────────────────
    # C1-1: SMT top (access side wins over bottom)
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_c1_1",
        "source_component_id": "sc_c1",
        "net_id": "SIG",
        "x": 30.0, "y": 5.0,
        "width": 1.0, "height": 1.0,
        "layer": "top_copper",
    },
    # C1-2: SMT bottom (lower priority than top)
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_c1_2",
        "source_component_id": "sc_c1",
        "net_id": "SIG",
        "x": 30.0, "y": 8.0,
        "width": 1.0, "height": 1.0,
        "layer": "bottom_copper",
    },
    # ── PWR net ───────────────────────────────────────────────────────────────
    # J1-1: PTH only
    {
        "type": "pcb_plated_pad",
        "pcb_plated_pad_id": "pad_j1_1",
        "source_component_id": "sc_j1",
        "net_id": "PWR",
        "x": 40.0, "y": 20.0,
        "width": 2.0, "height": 2.0,
        "hole_diameter": 1.0,
        "layer": "top_copper",
    },
    # ── OPEN net (single pad, far from others — should still be placed) ───────
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_open_1",
        "net_id": "OPEN",
        "x": 60.0, "y": 50.0,
        "width": 1.0, "height": 1.0,
        "layer": "top_copper",
    },
    # ── Conflict pair: two nets whose pads snap to same 2.54-mm grid cell ─────
    # CONFLICT1 at (50.0, 30.0) snaps to (50.8, 30.48) on 2.54 grid
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_c1_x",
        "net_id": "CONFLICT1",
        "x": 50.0, "y": 30.0,
        "width": 1.0, "height": 1.0,
        "layer": "top_copper",
    },
    # CONFLICT2 at (50.1, 30.1) — snaps to same grid cell as CONFLICT1
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_c2_x",
        "net_id": "CONFLICT2",
        "x": 50.1, "y": 30.1,
        "width": 1.0, "height": 1.0,
        "layer": "top_copper",
    },
    # ── N/C pad (no net) ─────────────────────────────────────────────────────
    {
        "type": "pcb_smtpad",
        "pcb_smtpad_id": "pad_nc_1",
        "x": 70.0, "y": 55.0,
        "width": 1.0, "height": 1.0,
        "layer": "top_copper",
    },
]

# Nets with named connections in the fixture (excludes N/C)
NAMED_NETS = {"VCC", "GND", "SIG", "PWR", "OPEN", "CONFLICT1", "CONFLICT2"}


# ─── Unit tests: place_testpoints ────────────────────────────────────────────

class TestPlaceTestpoints(unittest.TestCase):

    def setUp(self):
        from kerf_electronics.tools.testpoint import place_testpoints
        self.place = place_testpoints
        self.result = place_testpoints(FIXTURE_CIRCUIT_JSON)

    def test_returns_dict_with_required_keys(self):
        for key in ("probes", "unreachable", "net_count", "placed_count", "coverage_pct"):
            self.assertIn(key, self.result, f"Missing key: {key}")

    def test_net_count_matches_fixture(self):
        """net_count must equal the number of named nets in the fixture."""
        self.assertEqual(self.result["net_count"], len(NAMED_NETS))

    def test_nc_pads_excluded(self):
        """N/C pads must not appear in probe list."""
        probe_nets = {p["net"] for p in self.result["probes"]}
        self.assertNotIn("N/C", probe_nets)

    def test_at_most_one_probe_per_net(self):
        """Each net must appear at most once in the probe list."""
        probe_nets = [p["net"] for p in self.result["probes"]]
        self.assertEqual(len(probe_nets), len(set(probe_nets)),
                         "Duplicate net in probe list")

    def test_placed_count_plus_unreachable_equals_net_count(self):
        placed = self.result["placed_count"]
        unreach = len(self.result["unreachable"])
        self.assertEqual(placed + unreach, self.result["net_count"])

    def test_coverage_pct_correct(self):
        expected = round(self.result["placed_count"] / self.result["net_count"] * 100.0, 1)
        self.assertAlmostEqual(self.result["coverage_pct"], expected, places=1)

    def test_all_reachable_nets_have_probe(self):
        """Every net except CONFLICT2 (spacing conflict) should have a probe."""
        probe_nets = {p["net"] for p in self.result["probes"]}
        # VCC, GND, SIG, PWR, OPEN, CONFLICT1 should all be placed
        for net in ("VCC", "GND", "SIG", "PWR", "OPEN", "CONFLICT1"):
            self.assertIn(net, probe_nets, f"Net {net} should have a probe")

    def test_conflict2_unreachable(self):
        """CONFLICT2 shares a grid cell with CONFLICT1 → must be flagged unreachable."""
        unreach_nets = {u["net"] for u in self.result["unreachable"]}
        self.assertIn("CONFLICT2", unreach_nets)

    def test_via_preferred_over_smt_for_gnd(self):
        """GND has a via — probe must be placed on the via (pad_type='via')."""
        gnd_probe = next((p for p in self.result["probes"] if p["net"] == "GND"), None)
        self.assertIsNotNone(gnd_probe, "GND should have a probe")
        self.assertEqual(gnd_probe["pad_type"], "via")

    def test_pth_preferred_over_smt_for_vcc(self):
        """VCC has PTH + SMT — probe must be on PTH (pad_type='pth')."""
        vcc_probe = next((p for p in self.result["probes"] if p["net"] == "VCC"), None)
        self.assertIsNotNone(vcc_probe, "VCC should have a probe")
        self.assertEqual(vcc_probe["pad_type"], "pth")

    def test_top_preferred_over_bottom_for_sig(self):
        """SIG has top + bottom SMT — probe must be on top side (access_side default='top')."""
        sig_probe = next((p for p in self.result["probes"] if p["net"] == "SIG"), None)
        self.assertIsNotNone(sig_probe, "SIG should have a probe")
        self.assertEqual(sig_probe["side"], "top")

    def test_probe_positions_respect_min_spacing(self):
        """No two placed probes may be closer than min_spacing_mm (2.54)."""
        from kerf_electronics.tools.testpoint import _dist
        probes = self.result["probes"]
        min_spacing = 2.54
        for i, a in enumerate(probes):
            for b in probes[i + 1:]:
                d = _dist(a["snapped_x_mm"], a["snapped_y_mm"],
                          b["snapped_x_mm"], b["snapped_y_mm"])
                self.assertGreaterEqual(
                    d, min_spacing * 0.999,
                    f"Probes for {a['net']} and {b['net']} too close: {d:.4f} mm"
                )

    def test_probe_dia_clamped(self):
        """All probe diameters must be in [0.5, 2.5] mm."""
        from kerf_electronics.tools.testpoint import _PROBE_DIA_MIN_MM, _PROBE_DIA_MAX_MM
        for p in self.result["probes"]:
            self.assertGreaterEqual(p["probe_dia_mm"], _PROBE_DIA_MIN_MM,
                                    f"probe_dia too small for {p['net']}")
            self.assertLessEqual(p["probe_dia_mm"], _PROBE_DIA_MAX_MM,
                                 f"probe_dia too large for {p['net']}")

    def test_probe_dict_has_required_fields(self):
        required = {"net", "x_mm", "y_mm", "snapped_x_mm", "snapped_y_mm",
                    "side", "pad_type", "probe_dia_mm", "refdes", "pin"}
        for p in self.result["probes"]:
            for field in required:
                self.assertIn(field, p, f"Probe for {p.get('net', '?')} missing field {field}")

    def test_unreachable_dict_has_required_fields(self):
        for u in self.result["unreachable"]:
            self.assertIn("net", u)
            self.assertIn("reason", u)

    def test_empty_circuit_returns_zeros(self):
        r = self.place([])
        self.assertEqual(r["net_count"], 0)
        self.assertEqual(r["placed_count"], 0)
        self.assertEqual(r["coverage_pct"], 0.0)
        self.assertEqual(r["probes"], [])
        self.assertEqual(r["unreachable"], [])

    def test_coverage_100_when_no_conflicts(self):
        """A board where all nets have well-separated pads should achieve 100% coverage."""
        clean = [
            {"type": "pcb_smtpad", "pcb_smtpad_id": "p1",
             "net_id": "A", "x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0, "layer": "top_copper"},
            {"type": "pcb_smtpad", "pcb_smtpad_id": "p2",
             "net_id": "B", "x": 10.0, "y": 0.0, "width": 1.0, "height": 1.0, "layer": "top_copper"},
            {"type": "pcb_smtpad", "pcb_smtpad_id": "p3",
             "net_id": "C", "x": 20.0, "y": 0.0, "width": 1.0, "height": 1.0, "layer": "top_copper"},
        ]
        r = self.place(clean, min_spacing_mm=2.54)
        self.assertEqual(r["placed_count"], 3)
        self.assertEqual(r["coverage_pct"], 100.0)
        self.assertEqual(r["unreachable"], [])

    def test_bottom_access_side_prefers_bottom_pads(self):
        """When access_side='bottom', bottom SMT pads rank higher than top SMT pads."""
        board = [
            {"type": "pcb_smtpad", "pcb_smtpad_id": "pt",
             "net_id": "NET1", "x": 5.0, "y": 5.0, "width": 1.0, "height": 1.0,
             "layer": "top_copper"},
            {"type": "pcb_smtpad", "pcb_smtpad_id": "pb",
             "net_id": "NET1", "x": 20.0, "y": 5.0, "width": 1.0, "height": 1.0,
             "layer": "bottom_copper"},
        ]
        r = self.place(board, access_side="bottom", min_spacing_mm=2.54)
        self.assertEqual(r["placed_count"], 1)
        probe = r["probes"][0]
        self.assertEqual(probe["side"], "bottom")

    def test_single_pad_net_still_placed(self):
        """A net with exactly one accessible pad should be placed (no conflict)."""
        board = [
            {"type": "pcb_smtpad", "pcb_smtpad_id": "lone",
             "net_id": "LONE", "x": 50.0, "y": 50.0,
             "width": 1.0, "height": 1.0, "layer": "top_copper"},
        ]
        r = self.place(board)
        self.assertEqual(r["placed_count"], 1)
        self.assertEqual(r["unreachable"], [])


# ─── Unit tests: build_fixture_report ────────────────────────────────────────

class TestFixtureReport(unittest.TestCase):

    def setUp(self):
        from kerf_electronics.tools.testpoint import build_fixture_report
        self.build = build_fixture_report
        self.report = build_fixture_report(FIXTURE_CIRCUIT_JSON, stem="test_board")

    def test_returns_required_keys(self):
        required = ("probes", "unreachable", "net_count", "placed_count",
                    "coverage_pct", "drill_csv", "summary", "stem",
                    "access_side", "min_spacing_mm")
        for k in required:
            self.assertIn(k, self.report, f"Missing key: {k}")

    def test_drill_csv_is_string(self):
        self.assertIsInstance(self.report["drill_csv"], str)

    def test_drill_csv_has_header_row(self):
        rows = list(csv.reader(io.StringIO(self.report["drill_csv"])))
        self.assertGreater(len(rows), 0)
        header = rows[0]
        self.assertIn("Net", header)
        self.assertIn("X_mm", header)
        self.assertIn("Y_mm", header)
        self.assertIn("Side", header)
        self.assertIn("Probe_dia_mm", header)

    def test_drill_csv_row_count_matches_placed(self):
        rows = list(csv.reader(io.StringIO(self.report["drill_csv"])))
        # rows[0] is header, remaining are probe rows
        data_rows = rows[1:]
        self.assertEqual(len(data_rows), self.report["placed_count"])

    def test_drill_csv_net_column_no_nc(self):
        rows = list(csv.reader(io.StringIO(self.report["drill_csv"])))
        net_col_idx = rows[0].index("Net")
        for row in rows[1:]:
            self.assertNotEqual(row[net_col_idx], "N/C",
                                "N/C nets must not appear in drill CSV")

    def test_summary_contains_coverage(self):
        self.assertIn("Coverage", self.report["summary"])
        # Coverage % should appear in summary
        self.assertIn("%", self.report["summary"])

    def test_summary_contains_stem(self):
        self.assertIn("test_board", self.report["summary"])

    def test_coverage_pct_in_range(self):
        self.assertGreaterEqual(self.report["coverage_pct"], 0.0)
        self.assertLessEqual(self.report["coverage_pct"], 100.0)

    def test_coverage_pct_value_correct(self):
        placed = self.report["placed_count"]
        total = self.report["net_count"]
        expected = round(placed / total * 100.0, 1) if total > 0 else 0.0
        self.assertAlmostEqual(self.report["coverage_pct"], expected, places=1)

    def test_drill_csv_x_y_are_numeric(self):
        rows = list(csv.reader(io.StringIO(self.report["drill_csv"])))
        hdr = rows[0]
        xi = hdr.index("X_mm")
        yi = hdr.index("Y_mm")
        for row in rows[1:]:
            float(row[xi])  # must not raise
            float(row[yi])

    def test_probe_dia_in_csv_is_valid(self):
        rows = list(csv.reader(io.StringIO(self.report["drill_csv"])))
        hdr = rows[0]
        di = hdr.index("Probe_dia_mm")
        for row in rows[1:]:
            dia = float(row[di])
            self.assertGreater(dia, 0.0, "probe_dia must be positive")


# ─── Internal helper tests ─────────────────────────────────────────────────────

class TestHelpers(unittest.TestCase):

    def test_grid_snap_on_grid(self):
        from kerf_electronics.tools.testpoint import _grid_snap
        self.assertAlmostEqual(_grid_snap(5.08, 2.54), 5.08, places=5)

    def test_grid_snap_rounds_to_nearest(self):
        from kerf_electronics.tools.testpoint import _grid_snap
        # 1.5 mm with 2.54 pitch: nearest is 2*2.54=5.08? No — 1.5/2.54≈0.59 rounds to 1 → 2.54
        result = _grid_snap(1.5, 2.54)
        self.assertAlmostEqual(result, 2.54, places=5)

    def test_grid_snap_zero_pitch_passthrough(self):
        from kerf_electronics.tools.testpoint import _grid_snap
        self.assertAlmostEqual(_grid_snap(3.7, 0), 3.7, places=5)

    def test_dist_zero(self):
        from kerf_electronics.tools.testpoint import _dist
        self.assertAlmostEqual(_dist(1.0, 2.0, 1.0, 2.0), 0.0, places=10)

    def test_dist_pythagorean(self):
        from kerf_electronics.tools.testpoint import _dist
        self.assertAlmostEqual(_dist(0.0, 0.0, 3.0, 4.0), 5.0, places=10)

    def test_probe_dia_clamp_min(self):
        from kerf_electronics.tools.testpoint import _probe_dia, _PROBE_DIA_MIN_MM
        from kerf_electronics.tools.ipc_netlist import _NetPoint
        tiny_pad = _NetPoint(
            net_name="NET", refdes="R1", pin="1",
            record_type="317", drilled=False, plated=False,
            x_mm=0, y_mm=0, w_mm=0.1, h_mm=0.1, drill_mm=0,
            layer_code="01",
        )
        self.assertGreaterEqual(_probe_dia(tiny_pad), _PROBE_DIA_MIN_MM)

    def test_probe_dia_clamp_max(self):
        from kerf_electronics.tools.testpoint import _probe_dia, _PROBE_DIA_MAX_MM
        from kerf_electronics.tools.ipc_netlist import _NetPoint
        large_pad = _NetPoint(
            net_name="NET", refdes="J1", pin="1",
            record_type="327", drilled=True, plated=True,
            x_mm=0, y_mm=0, w_mm=10.0, h_mm=10.0, drill_mm=2.0,
            layer_code="00",
        )
        self.assertLessEqual(_probe_dia(large_pad), _PROBE_DIA_MAX_MM)

    def test_side_of_top(self):
        from kerf_electronics.tools.testpoint import _side_of
        from kerf_electronics.tools.ipc_netlist import _NetPoint
        pt = _NetPoint(
            net_name="N", refdes="", pin="", record_type="317",
            drilled=False, plated=False,
            x_mm=0, y_mm=0, w_mm=1, h_mm=1, drill_mm=0, layer_code="01",
        )
        self.assertEqual(_side_of(pt), "top")

    def test_side_of_bottom(self):
        from kerf_electronics.tools.testpoint import _side_of
        from kerf_electronics.tools.ipc_netlist import _NetPoint
        pt = _NetPoint(
            net_name="N", refdes="", pin="", record_type="317",
            drilled=False, plated=False,
            x_mm=0, y_mm=0, w_mm=1, h_mm=1, drill_mm=0, layer_code="02",
        )
        self.assertEqual(_side_of(pt), "bottom")

    def test_side_of_via(self):
        from kerf_electronics.tools.testpoint import _side_of
        from kerf_electronics.tools.ipc_netlist import _NetPoint
        pt = _NetPoint(
            net_name="N", refdes="", pin="", record_type="327",
            drilled=True, plated=True,
            x_mm=0, y_mm=0, w_mm=0.6, h_mm=0.6, drill_mm=0.3, layer_code="00",
        )
        self.assertEqual(_side_of(pt), "both")

    def test_priority_via_top_access(self):
        from kerf_electronics.tools.testpoint import _priority
        from kerf_electronics.tools.ipc_netlist import _NetPoint
        via = _NetPoint(
            net_name="G", refdes="", pin="", record_type="327",
            drilled=True, plated=True,
            x_mm=0, y_mm=0, w_mm=0.6, h_mm=0.6, drill_mm=0.3, layer_code="00",
        )
        smt_top = _NetPoint(
            net_name="G", refdes="R1", pin="1", record_type="317",
            drilled=False, plated=False,
            x_mm=1, y_mm=0, w_mm=1.0, h_mm=0.8, drill_mm=0, layer_code="01",
        )
        self.assertLess(_priority(via, "top"), _priority(smt_top, "top"),
                        "Via should have lower (better) priority than SMT top")

    def test_priority_nc_is_highest_number(self):
        from kerf_electronics.tools.testpoint import _priority
        from kerf_electronics.tools.ipc_netlist import _NetPoint
        nc = _NetPoint(
            net_name="N/C", refdes="", pin="", record_type="317",
            drilled=False, plated=False,
            x_mm=0, y_mm=0, w_mm=1, h_mm=1, drill_mm=0, layer_code="01",
        )
        self.assertEqual(_priority(nc, "top"), 9)


# ─── LLM tool integration tests ───────────────────────────────────────────────

class TestToolRegistration(unittest.IsolatedAsyncioTestCase):

    async def test_generate_testpoints_registered(self):
        from kerf_chat.tools.registry import Registry
        names = {t.spec.name for t in Registry}
        self.assertIn("generate_testpoints", names)

    async def test_fixture_report_registered(self):
        from kerf_chat.tools.registry import Registry
        names = {t.spec.name for t in Registry}
        self.assertIn("fixture_report", names)

    async def test_generate_testpoints_runs(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "generate_testpoints")
        payload = json.dumps({"circuit_json": FIXTURE_CIRCUIT_JSON}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertNotIn("error", result, result)
        self.assertIn("probe_count", result)
        self.assertIn("coverage_pct", result)
        self.assertIn("probes", result)
        self.assertIn("unreachable_nets", result)

    async def test_generate_testpoints_coverage_in_range(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "generate_testpoints")
        payload = json.dumps({"circuit_json": FIXTURE_CIRCUIT_JSON}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertGreaterEqual(result["coverage_pct"], 0.0)
        self.assertLessEqual(result["coverage_pct"], 100.0)

    async def test_generate_testpoints_all_nets_covered_or_flagged(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "generate_testpoints")
        payload = json.dumps({"circuit_json": FIXTURE_CIRCUIT_JSON}).encode()
        result = json.loads(await tool.run(None, payload))
        placed = {p["net"] for p in result["probes"]}
        unreach = {u["net"] for u in result["unreachable_nets"]}
        for net in NAMED_NETS:
            self.assertTrue(
                net in placed or net in unreach,
                f"Net {net} neither placed nor flagged unreachable"
            )

    async def test_fixture_report_runs(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "fixture_report")
        payload = json.dumps({
            "circuit_json": FIXTURE_CIRCUIT_JSON,
            "stem": "integration_test",
        }).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertNotIn("error", result, result)
        self.assertIn("drill_csv", result)
        self.assertIn("coverage_pct", result)
        self.assertIn("summary", result)
        self.assertIn("csv_filename", result)

    async def test_fixture_report_csv_filename_uses_stem(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "fixture_report")
        payload = json.dumps({
            "circuit_json": FIXTURE_CIRCUIT_JSON,
            "stem": "my_board",
        }).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertIn("my_board", result["csv_filename"])

    async def test_generate_testpoints_bad_args(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "generate_testpoints")
        payload = json.dumps({"circuit_json": "not-an-array"}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertIn("error", result)

    async def test_fixture_report_bad_args(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "fixture_report")
        payload = json.dumps({"circuit_json": 42}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertIn("error", result)

    async def test_generate_testpoints_50mil_pitch(self):
        """At 1.27 mm pitch, a tighter board should still place probes."""
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "generate_testpoints")
        payload = json.dumps({
            "circuit_json": FIXTURE_CIRCUIT_JSON,
            "min_spacing_mm": 1.27,
        }).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertNotIn("error", result, result)
        self.assertGreater(result["probe_count"], 0)

    async def test_generate_testpoints_bottom_access(self):
        """Bottom access side should still return probes (via/PTH accessible from either side)."""
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "generate_testpoints")
        payload = json.dumps({
            "circuit_json": FIXTURE_CIRCUIT_JSON,
            "access_side": "bottom",
        }).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertNotIn("error", result, result)
        self.assertGreater(result["probe_count"], 0)


if __name__ == "__main__":
    unittest.main()
