"""test_kicad_bridge.py — pytest suite for the KiCad round-trip bridge.

Tests are fully hermetic: no network, all disk I/O uses tempfile.TemporaryDirectory.

Coverage:
  1. export_to_kicad_project: writes three files, valid JSON .kicad_pro
  2. export_to_kicad_project: .kicad_sch contains expected symbols + nets
  3. export_to_kicad_project: .kicad_pcb balanced parens, layer table present
  4. export_to_kicad_project: correct component/net counts in KiCadExportResult
  5. import_from_kicad_pcb: extracts tracks, vias, footprint positions
  6. Round-trip: export → inject tracks → re-import preserves track count
  7. export empty board: no components, valid output
  8. import: no tracks/vias in unrouted file
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest

from kerf_electronics.kicad_bridge import (
    export_to_kicad_project,
    import_from_kicad_pcb,
    KiCadExportResult,
    KiCadImportResult,
    RouteTrack,
    RouteVia,
    FootprintPosition,
)
from kerf_electronics.kicad_io import _parse_sexpr

# ─── Fixture ──────────────────────────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
_FIXTURE_PATH = os.path.join(_HERE, "fixtures", "two_resistors_circuit.json")

with open(_FIXTURE_PATH, encoding="utf-8") as _f:
    FIXTURE: list = json.load(_f)

# Minimal 2-component schematic (no pcb_component entries) for schematic-only tests
SCHEMATIC_ONLY: list = [
    {"type": "source_component", "source_component_id": "sc_u1", "name": "U1", "value": "MCU", "footprint": "Package_QFP:LQFP-32"},
    {"type": "source_component", "source_component_id": "sc_c1", "name": "C1", "value": "100n", "footprint": "C_0402"},
    {"type": "source_net", "source_net_id": "sn_vcc", "name": "VCC"},
    {"type": "source_net", "source_net_id": "sn_gnd", "name": "GND"},
    {"type": "source_port", "source_port_id": "sp_u1_vcc", "source_component_id": "sc_u1", "name": "VCC", "pin_type": "power_in"},
    {"type": "source_port", "source_port_id": "sp_c1_1", "source_component_id": "sc_c1", "name": "1", "pin_type": "passive"},
    {"type": "source_trace", "source_trace_id": "st_vcc", "connected_source_port_ids": ["sp_u1_vcc", "sp_c1_1"], "connected_source_net_ids": ["sn_vcc"]},
]


# ─── Helper ───────────────────────────────────────────────────────────────────

def _make_routed_pcb_text(result: KiCadExportResult) -> str:
    """Read the exported .kicad_pcb and inject two track segments to simulate routing."""
    with open(result.pcb_path, encoding="utf-8") as fh:
        text = fh.read()

    # Append two segments and a via before the last closing paren
    extra = (
        "\n  (segment (start 10.0 15.0) (end 35.0 15.0) (width 0.25) (layer \"F.Cu\") (net 1))"
        "\n  (segment (start 35.0 15.0) (end 50.0 15.0) (width 0.25) (layer \"B.Cu\") (net 1))"
        "\n  (via (at 35.0 15.0) (size 0.8) (drill 0.4) (layers \"F.Cu\" \"B.Cu\") (net 1))"
    )
    # Insert before the final ")" of kicad_pcb
    idx = text.rfind(")")
    if idx == -1:
        return text + extra
    return text[:idx] + extra + "\n" + text[idx:]


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestExportToKicadProject(unittest.TestCase):
    """Tests for export_to_kicad_project()."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.outdir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_writes_three_files(self):
        """All three KiCad project files must be written."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir, stem="test_board")
        self.assertIsInstance(result, KiCadExportResult)
        self.assertTrue(os.path.isfile(result.pro_path), f"Missing: {result.pro_path}")
        self.assertTrue(os.path.isfile(result.sch_path), f"Missing: {result.sch_path}")
        self.assertTrue(os.path.isfile(result.pcb_path), f"Missing: {result.pcb_path}")

    def test_pro_file_is_valid_json(self):
        """*.kicad_pro must contain valid JSON with required keys."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)
        with open(result.pro_path, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIn("meta", data)
        self.assertIn("board", data)
        self.assertIn("schematic", data)
        self.assertIn("net_settings", data)

    def test_sch_contains_symbols(self):
        """*.kicad_sch must contain kicad_sch root and lib_symbols section."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)
        with open(result.sch_path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("kicad_sch", text, "Missing kicad_sch root tag")
        self.assertIn("lib_symbols", text, "Missing lib_symbols section")
        # Both R1 and R2 references should appear
        self.assertIn("R1", text)
        self.assertIn("R2", text)

    def test_sch_contains_nets(self):
        """*.kicad_sch must contain net label entries for VCC, MID, GND."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)
        with open(result.sch_path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("VCC", text)
        self.assertIn("GND", text)
        self.assertIn("MID", text)

    def test_pcb_balanced_parens(self):
        """*.kicad_pcb must have balanced parentheses (valid s-expression)."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)
        with open(result.pcb_path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(
            text.count("("),
            text.count(")"),
            "Unbalanced parentheses in .kicad_pcb",
        )

    def test_pcb_layer_table_present(self):
        """*.kicad_pcb must contain the standard layer table."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)
        with open(result.pcb_path, encoding="utf-8") as fh:
            text = fh.read()
        # Check a few canonical KiCad layer names
        for layer_name in ("F.Cu", "B.Cu", "F.SilkS", "Edge.Cuts"):
            self.assertIn(layer_name, text, f"Layer {layer_name!r} missing from layer table")

    def test_pcb_footprints_present(self):
        """*.kicad_pcb must contain footprint entries for R1 and R2."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)
        with open(result.pcb_path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("footprint", text)
        self.assertIn("R1", text)
        self.assertIn("R2", text)

    def test_result_counts(self):
        """KiCadExportResult must report correct component and net counts."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)
        self.assertEqual(result.num_components, 2, "Expected 2 pcb_components")
        self.assertGreaterEqual(result.num_nets, 3, "Expected at least 3 nets (VCC/MID/GND)")
        self.assertGreaterEqual(result.layer_count, 2, "Expected at least 2 copper layers")

    def test_caveat_present(self):
        """KiCadExportResult must include a non-empty caveat string."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)
        self.assertTrue(result.caveat, "Caveat should be non-empty")
        self.assertIn("KiCad", result.caveat)

    def test_schematic_only_export(self):
        """Export with schematic-only data (no pcb_component) must succeed."""
        result = export_to_kicad_project(SCHEMATIC_ONLY, [], self.outdir, stem="sch_only")
        self.assertTrue(os.path.isfile(result.sch_path))
        self.assertTrue(os.path.isfile(result.pcb_path))
        with open(result.sch_path, encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("U1", text)
        self.assertIn("C1", text)

    def test_empty_circuit_json(self):
        """Export with empty lists must write valid (minimal) files without error."""
        result = export_to_kicad_project([], [], self.outdir, stem="empty")
        self.assertTrue(os.path.isfile(result.pro_path))
        self.assertTrue(os.path.isfile(result.sch_path))
        self.assertTrue(os.path.isfile(result.pcb_path))
        self.assertEqual(result.num_components, 0)
        self.assertEqual(result.num_nets, 0)


class TestImportFromKicadPcb(unittest.TestCase):
    """Tests for import_from_kicad_pcb()."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.outdir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def _export(self, circuit_json=None):
        cj = circuit_json if circuit_json is not None else FIXTURE
        return export_to_kicad_project(cj, cj, self.outdir)

    def test_import_unrouted_has_no_tracks(self):
        """An unrouted export (no segments) should import with zero tracks."""
        result = self._export()
        imported = import_from_kicad_pcb(result.pcb_path)
        self.assertIsInstance(imported, KiCadImportResult)
        self.assertEqual(imported.num_unrouted, 0)
        # Unrouted export has no segment nodes
        self.assertEqual(len(imported.tracks), 0)

    def test_import_footprint_positions(self):
        """Import must recover footprint positions for R1 and R2."""
        result = self._export()
        imported = import_from_kicad_pcb(result.pcb_path)
        refs = {fp.ref for fp in imported.footprint_positions}
        self.assertIn("R1", refs)
        self.assertIn("R2", refs)

    def test_import_net_names(self):
        """Import must recover net names from the net table."""
        result = self._export()
        imported = import_from_kicad_pcb(result.pcb_path)
        self.assertIn("VCC", imported.net_names)
        self.assertIn("GND", imported.net_names)
        self.assertIn("MID", imported.net_names)

    def test_import_source_file_set(self):
        """Import result source_file must match the input path."""
        result = self._export()
        imported = import_from_kicad_pcb(result.pcb_path)
        self.assertEqual(os.path.abspath(result.pcb_path), imported.source_file)

    def test_import_caveat_present(self):
        """Import result must include a non-empty caveat string."""
        result = self._export()
        imported = import_from_kicad_pcb(result.pcb_path)
        self.assertTrue(imported.caveat)


class TestRoundTrip(unittest.TestCase):
    """Round-trip tests: export → inject routes → re-import."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.outdir = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_round_trip_preserves_tracks(self):
        """After injecting 2 tracks, import should recover exactly 2 tracks."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)

        # Simulate user routing in KiCad by injecting segments into the file
        routed_text = _make_routed_pcb_text(result)
        routed_path = os.path.join(self.outdir, "board_routed.kicad_pcb")
        with open(routed_path, "w", encoding="utf-8") as fh:
            fh.write(routed_text)

        imported = import_from_kicad_pcb(routed_path)
        self.assertEqual(len(imported.tracks), 2, f"Expected 2 tracks, got {len(imported.tracks)}")

    def test_round_trip_preserves_via(self):
        """After injecting 1 via, import should recover exactly 1 via."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)

        routed_text = _make_routed_pcb_text(result)
        routed_path = os.path.join(self.outdir, "board_via.kicad_pcb")
        with open(routed_path, "w", encoding="utf-8") as fh:
            fh.write(routed_text)

        imported = import_from_kicad_pcb(routed_path)
        self.assertEqual(len(imported.vias), 1, f"Expected 1 via, got {len(imported.vias)}")

    def test_round_trip_track_layer(self):
        """Injected track layers should map to correct Circuit-JSON layer names."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)
        routed_text = _make_routed_pcb_text(result)
        routed_path = os.path.join(self.outdir, "board_layer.kicad_pcb")
        with open(routed_path, "w", encoding="utf-8") as fh:
            fh.write(routed_text)

        imported = import_from_kicad_pcb(routed_path)
        layer_cj_values = {t.layer_cj for t in imported.tracks}
        # F.Cu → top_copper, B.Cu → bottom_copper
        self.assertIn("top_copper", layer_cj_values)
        self.assertIn("bottom_copper", layer_cj_values)

    def test_round_trip_footprint_positions_preserved(self):
        """After export→inject routes→import, footprint refs must match original."""
        result = export_to_kicad_project(FIXTURE, FIXTURE, self.outdir)
        routed_text = _make_routed_pcb_text(result)
        routed_path = os.path.join(self.outdir, "board_fp.kicad_pcb")
        with open(routed_path, "w", encoding="utf-8") as fh:
            fh.write(routed_text)

        imported = import_from_kicad_pcb(routed_path)
        refs = {fp.ref for fp in imported.footprint_positions}
        self.assertIn("R1", refs)
        self.assertIn("R2", refs)


if __name__ == "__main__":
    unittest.main()
