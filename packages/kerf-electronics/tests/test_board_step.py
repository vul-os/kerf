"""
Tests for T-13 — 3D STEP board export (MCAD-ECAD co-design).

Tests are fully hermetic (no network, no disk I/O beyond temp files).
Two execution paths are exercised:

1. OCC absent  — _OCC_AVAILABLE=False: export_board_step raises RuntimeError
   with the install message; the LLM tool returns an OCC_NOT_AVAILABLE error.

2. OCC present — _OCC_AVAILABLE=True: a fixture board produces a valid STEP
   file on disk; the result dict carries the expected keys; the file is
   non-empty.  This path is skipped automatically when pythonOCC is not
   installed in the test environment (``@unittest.skipUnless``).

The LLM tool registration is also checked (always, no OCC needed).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

# Import the tools module so @register decorators fire
import kerf_electronics.tools.fab  # noqa: F401

from kerf_electronics.fab.board_step import (
    _OCC_AVAILABLE,
    _board_outline_vertices,
    _collect_holes,
    _collect_placed_components,
    _estimate_body_size,
)

# ─── Shared fixture ────────────────────────────────────────────────────────────
# Matches the fixture used in test_fab.py (same board, reused).

FIXTURE_CIRCUIT_JSON = [
    {
        "type": "pcb_board",
        "width": 100.0,
        "height": 80.0,
        "center_x": 50.0,
        "center_y": 40.0,
    },
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
        "value": "ATmega328P",
        "footprint": "TQFP-32",
    },
    {
        "type": "pcb_component",
        "pcb_component_id": "pcb_r1",
        "source_component_id": "sc_r1",
        "x": 20.0,
        "y": 30.0,
        "rotation": 0.0,
        "layer": "top_copper",
    },
    {
        "type": "pcb_component",
        "pcb_component_id": "pcb_u1",
        "source_component_id": "sc_u1",
        "x": 60.0,
        "y": 40.0,
        "rotation": 90.0,
        "layer": "top_copper",
    },
    {
        "type": "pcb_via",
        "pcb_via_id": "via_1",
        "x": 40.0,
        "y": 35.0,
        "outer_diameter": 0.6,
        "hole_diameter": 0.3,
    },
    {
        "type": "pcb_plated_pad",
        "pcb_plated_pad_id": "pad_pth_1",
        "source_component_id": "sc_u1",
        "x": 58.0,
        "y": 38.0,
        "width": 1.6,
        "height": 1.6,
        "hole_diameter": 0.8,
        "shape": "circle",
        "layer": "top_copper",
    },
]


# ─── Pure-Python geometry extraction tests (no OCC needed) ────────────────────

class TestBoardOutlineExtraction(unittest.TestCase):

    def test_board_element_gives_rect(self):
        verts = _board_outline_vertices(FIXTURE_CIRCUIT_JSON)
        self.assertEqual(len(verts), 4)
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        self.assertAlmostEqual(max(xs) - min(xs), 100.0, places=3)
        self.assertAlmostEqual(max(ys) - min(ys), 80.0, places=3)

    def test_explicit_outline_path_takes_priority(self):
        circuit = [
            {"type": "pcb_board", "width": 100.0, "height": 80.0,
             "center_x": 50.0, "center_y": 40.0},
            {
                "type": "pcb_outline_path",
                "route": [
                    {"x": 0, "y": 0}, {"x": 50, "y": 0},
                    {"x": 50, "y": 50}, {"x": 0, "y": 50},
                ],
            },
        ]
        verts = _board_outline_vertices(circuit)
        # Must pick the 50×50 outline path, not the 100×80 board element
        xs = [v[0] for v in verts]
        self.assertAlmostEqual(max(xs), 50.0, places=3)

    def test_empty_circuit_gives_default_100x100(self):
        verts = _board_outline_vertices([])
        xs = [v[0] for v in verts]
        ys = [v[1] for v in verts]
        self.assertAlmostEqual(max(xs) - min(xs), 100.0, places=3)
        self.assertAlmostEqual(max(ys) - min(ys), 100.0, places=3)


class TestHoleExtraction(unittest.TestCase):

    def test_via_captured(self):
        holes = _collect_holes(FIXTURE_CIRCUIT_JSON)
        via_holes = [h for h in holes if abs(h[2] - 0.3) < 1e-6]
        self.assertEqual(len(via_holes), 1)
        self.assertAlmostEqual(via_holes[0][0], 40.0)
        self.assertAlmostEqual(via_holes[0][1], 35.0)

    def test_pth_pad_captured(self):
        holes = _collect_holes(FIXTURE_CIRCUIT_JSON)
        pth_holes = [h for h in holes if abs(h[2] - 0.8) < 1e-6]
        self.assertEqual(len(pth_holes), 1)

    def test_no_smt_holes(self):
        circuit = [
            {"type": "pcb_smtpad", "x": 5.0, "y": 5.0, "width": 1.0, "height": 0.5},
        ]
        holes = _collect_holes(circuit)
        self.assertEqual(len(holes), 0)

    def test_mounting_hole(self):
        circuit = [
            {"type": "pcb_mounting_hole", "x": 3.0, "y": 3.0, "hole_diameter": 3.2},
        ]
        holes = _collect_holes(circuit)
        self.assertEqual(len(holes), 1)
        self.assertAlmostEqual(holes[0][2], 3.2)

    def test_empty_circuit(self):
        self.assertEqual(_collect_holes([]), [])


class TestComponentExtraction(unittest.TestCase):

    def test_two_components_placed(self):
        comps = _collect_placed_components(FIXTURE_CIRCUIT_JSON)
        self.assertEqual(len(comps), 2)

    def test_refdes_and_footprint_resolved(self):
        comps = _collect_placed_components(FIXTURE_CIRCUIT_JSON)
        by_ref = {c["refdes"]: c for c in comps}
        self.assertIn("R1", by_ref)
        self.assertIn("U1", by_ref)
        self.assertEqual(by_ref["R1"]["footprint"], "R_0402")
        self.assertEqual(by_ref["U1"]["footprint"], "TQFP-32")

    def test_side_inferred_from_layer(self):
        comps = _collect_placed_components(FIXTURE_CIRCUIT_JSON)
        for c in comps:
            self.assertEqual(c["side"], "top")

    def test_rotation_preserved(self):
        comps = _collect_placed_components(FIXTURE_CIRCUIT_JSON)
        by_ref = {c["refdes"]: c for c in comps}
        self.assertAlmostEqual(by_ref["U1"]["rotation_deg"], 90.0)

    def test_bottom_side_detection(self):
        circuit = [
            {"type": "pcb_component", "pcb_component_id": "bot1",
             "source_component_id": "", "x": 0, "y": 0, "rotation": 0,
             "layer": "bottom_copper"},
        ]
        comps = _collect_placed_components(circuit)
        self.assertEqual(len(comps), 1)
        self.assertEqual(comps[0]["side"], "bottom")


class TestBodySizeEstimation(unittest.TestCase):

    def test_known_footprint_exact(self):
        w, h, z = _estimate_body_size("R_0402")
        self.assertAlmostEqual(w, 1.0)
        self.assertAlmostEqual(h, 0.5)
        self.assertAlmostEqual(z, 0.35)

    def test_known_footprint_prefix(self):
        # "SOIC-8_EIAJ" should match "SOIC-8" prefix
        w, h, z = _estimate_body_size("SOIC-8_EIAJ")
        self.assertAlmostEqual(w, 5.0)

    def test_unknown_footprint_fallback(self):
        w, h, z = _estimate_body_size("SOME_WEIRD_PART_XYZ")
        self.assertAlmostEqual(w, 2.5)
        self.assertAlmostEqual(h, 2.5)
        self.assertAlmostEqual(z, 1.5)

    def test_empty_footprint_fallback(self):
        w, h, z = _estimate_body_size("")
        self.assertAlmostEqual(w, 2.5)


# ─── OCC-absent path ──────────────────────────────────────────────────────────

class TestExportBoardStepOCCAbsent(unittest.TestCase):
    """Tests the no-OCC code path by temporarily patching _OCC_AVAILABLE."""

    def _patch_occ(self, available: bool):
        """Context manager: patch _OCC_AVAILABLE in board_step module."""
        import kerf_electronics.fab.board_step as bs
        return mock.patch.object(bs, "_OCC_AVAILABLE", available)

    def test_raises_runtime_error_when_occ_absent(self):
        with self._patch_occ(False):
            from kerf_electronics.fab.board_step import export_board_step
            with self.assertRaises(RuntimeError) as ctx:
                with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
                    tmp_path = tmp.name
                try:
                    export_board_step(FIXTURE_CIRCUIT_JSON, tmp_path)
                finally:
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
            self.assertIn("pythonOCC not installed", str(ctx.exception))
            self.assertIn("conda install", str(ctx.exception))

    def test_runtime_error_message_contains_install_hint(self):
        with self._patch_occ(False):
            from kerf_electronics.fab.board_step import export_board_step
            try:
                export_board_step(FIXTURE_CIRCUIT_JSON, "/tmp/should_not_exist.step")
            except RuntimeError as e:
                self.assertIn("pythonocc-core", str(e))
            else:
                self.fail("Expected RuntimeError not raised")


class TestExportBoardStepToolOCCAbsent(unittest.IsolatedAsyncioTestCase):
    """LLM tool returns OCC_NOT_AVAILABLE error when pythonOCC absent."""

    async def test_tool_returns_error_when_occ_absent(self):
        import kerf_electronics.tools.fab as fab_tools
        with mock.patch.object(fab_tools, "_STEP_OCC_AVAILABLE", False):
            from kerf_chat.tools.registry import Registry
            tool = next(t for t in Registry if t.spec.name == "export_board_step")
            payload = json.dumps({
                "circuit_json": FIXTURE_CIRCUIT_JSON,
            }).encode()
            result = json.loads(await tool.run(None, payload))
            self.assertIn("error", result)
            self.assertEqual(result.get("code"), "OCC_NOT_AVAILABLE")
            self.assertIn("pythonOCC", result["error"])

    async def test_tool_rejects_bad_args(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_board_step")
        payload = json.dumps({"circuit_json": "not-an-array"}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertIn("error", result)
        self.assertEqual(result.get("code"), "BAD_ARGS")


# ─── Tool registration (no OCC needed) ────────────────────────────────────────

class TestBoardStepToolRegistered(unittest.IsolatedAsyncioTestCase):

    async def test_export_board_step_registered(self):
        from kerf_chat.tools.registry import Registry
        names = {t.spec.name for t in Registry}
        self.assertIn("export_board_step", names)

    async def test_tool_spec_has_required_fields(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_board_step")
        self.assertIn("circuit_json", tool.spec.input_schema["properties"])
        self.assertIn("board_thickness_mm", tool.spec.input_schema["properties"])
        self.assertIn("circuit_json", tool.spec.input_schema["required"])


# ─── OCC-present path ─────────────────────────────────────────────────────────

@unittest.skipUnless(_OCC_AVAILABLE, "pythonOCC not installed — skipping OCC-present tests")
class TestExportBoardStepOCCPresent(unittest.TestCase):
    """Full integration tests: only run when pythonOCC is available."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.step_path = os.path.join(self.tmp_dir, "test_board.step")

    def tearDown(self):
        try:
            os.unlink(self.step_path)
            os.rmdir(self.tmp_dir)
        except OSError:
            pass

    def _export(self, circuit_json=None, **kwargs):
        from kerf_electronics.fab.board_step import export_board_step
        cj = circuit_json if circuit_json is not None else FIXTURE_CIRCUIT_JSON
        return export_board_step(cj, self.step_path, **kwargs)

    def test_step_file_produced(self):
        self._export()
        self.assertTrue(os.path.isfile(self.step_path),
                        "STEP file was not created")
        self.assertGreater(os.path.getsize(self.step_path), 0,
                           "STEP file is empty")

    def test_result_dict_keys(self):
        result = self._export()
        for key in ("output_path", "substrate_volume", "hole_count",
                    "component_count", "occ_available"):
            self.assertIn(key, result, f"result missing key: {key!r}")

    def test_output_path_matches(self):
        result = self._export()
        self.assertEqual(result["output_path"], self.step_path)

    def test_step_file_is_valid_ascii(self):
        self._export()
        with open(self.step_path, "r", encoding="ascii", errors="replace") as fh:
            content = fh.read(4096)
        # STEP AP214 files begin with "ISO-10303-21;" header
        self.assertIn("ISO-10303-21", content,
                      "STEP file does not start with expected AP214 header")

    def test_occ_available_true_in_result(self):
        result = self._export()
        self.assertTrue(result["occ_available"])

    def test_substrate_volume_positive(self):
        result = self._export()
        self.assertGreater(result["substrate_volume"], 0,
                           "Substrate volume should be positive")

    def test_hole_count_matches_fixture(self):
        # Fixture: 1 via + 1 PTH pad = 2 holes
        result = self._export()
        self.assertEqual(result["hole_count"], 2)

    def test_component_count_matches_fixture(self):
        # Fixture has 2 pcb_components (R1, U1)
        result = self._export()
        self.assertEqual(result["component_count"], 2)

    def test_board_only_no_components(self):
        result = self._export(place_components=False)
        self.assertEqual(result["component_count"], 0)
        self.assertTrue(os.path.isfile(self.step_path))

    def test_no_holes(self):
        result = self._export(drill_holes=False)
        self.assertEqual(result["hole_count"], 0)
        # File still produced
        self.assertGreater(os.path.getsize(self.step_path), 0)

    def test_custom_board_thickness(self):
        result = self._export(board_thickness_mm=0.8)
        # Approx volume: 100 * 80 * 0.8 = 6400 mm³
        self.assertAlmostEqual(result["substrate_volume"], 6400.0, delta=1.0)

    def test_empty_circuit_produces_default_board(self):
        """Empty CircuitJSON → 100×100 default outline, no holes, no components."""
        result = self._export(circuit_json=[])
        self.assertTrue(os.path.isfile(self.step_path))
        self.assertEqual(result["hole_count"], 0)
        self.assertEqual(result["component_count"], 0)

    def test_at_least_one_component_body_in_step(self):
        """The STEP file content should reference at least one solid body."""
        self._export()
        with open(self.step_path, "r", encoding="ascii", errors="replace") as fh:
            content = fh.read()
        # STEP AP214 solids/shells appear as MANIFOLD_SOLID_BREP or SHELL_BASED_SURFACE_MODEL
        has_solid = (
            "MANIFOLD_SOLID_BREP" in content
            or "SHELL_BASED_SURFACE_MODEL" in content
            or "BREP_WITH_VOIDS" in content
            or "CLOSED_SHELL" in content
        )
        self.assertTrue(has_solid,
                        "STEP file does not contain any recognisable solid geometry")


@unittest.skipUnless(_OCC_AVAILABLE, "pythonOCC not installed — skipping OCC tool test")
class TestBoardStepToolOCCPresent(unittest.IsolatedAsyncioTestCase):

    async def test_tool_returns_step_b64(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_board_step")
        payload = json.dumps({
            "circuit_json": FIXTURE_CIRCUIT_JSON,
            "stem": "tool_test",
            "board_thickness_mm": 1.6,
        }).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertNotIn("error", result, result)
        self.assertIn("step_b64", result)
        self.assertIn("step_filename", result)
        self.assertIn("component_count", result)
        step_bytes = base64.b64decode(result["step_b64"])
        self.assertGreater(len(step_bytes), 0)
        # Verify STEP header in decoded bytes
        self.assertIn(b"ISO-10303-21", step_bytes[:200])

    async def test_tool_component_count_correct(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_board_step")
        payload = json.dumps({
            "circuit_json": FIXTURE_CIRCUIT_JSON,
        }).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertEqual(result["component_count"], 2)

    async def test_tool_hole_count_correct(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_board_step")
        payload = json.dumps({
            "circuit_json": FIXTURE_CIRCUIT_JSON,
        }).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertEqual(result["hole_count"], 2)


if __name__ == "__main__":
    unittest.main()
