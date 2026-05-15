"""
Tests for ODB++ fab-archive export.

All tests are fully hermetic (no network I/O, no temp files on disk).
The writer returns tgz_bytes directly, so every test works purely in memory.

Coverage:
  - Directory/file structure inside the archive
  - Layer set and per-layer files (attrlist, components, features)
  - misc/info metadata (EDA product name, ODB++ version, units)
  - stephdr board dimensions and layer list
  - attrlist content (type, context, polarity per layer)
  - Feature-record encoding: lines, pads (P/L), surfaces (S/OB/OS/OE)
  - Symbol names: circle (r), rect, oval
  - Drill layer: via + PTH pad holes
  - Outline layer: board outline segments
  - Copper traces encoded as line records
  - Copper pour encoded as surface records
  - Silkscreen lines encoded as line records
  - Soldermask pads with expansion
  - Component placement records (CMP) on copper layers
  - Non-copper layers produce empty components file
  - Empty circuit_json → valid archive with expected structure
  - tgz produces a valid tar archive (gzip-compressed)
  - tarfile member list matches manifest
  - manifest is sorted
  - tgz_bytes is bytes
  - Stem name propagates through directory paths
  - Board dimensions in stephdr match fixture
  - Feature polarity field present in records
  - UNITS=MM declared in features and stephdr
  - LLM tool registered and returns ok payload
  - LLM tool bad-args path returns error
"""

import base64
import io
import json
import re
import tarfile
import unittest

# Fire @register decorators
import kerf_electronics.tools.odbpp_export  # noqa: F401

from kerf_electronics.fab.odbpp.writer import export_odbpp

# ─── shared fixture ────────────────────────────────────────────────────────────

FIXTURE = [
    # board
    {"type": "pcb_board", "width": 80.0, "height": 60.0,
     "center_x": 40.0, "center_y": 30.0},
    # source components
    {"type": "source_component", "source_component_id": "sc_r1",
     "name": "R1", "value": "10k", "footprint": "R_0402",
     "mpn": "RC0402", "manufacturer": "Yageo", "description": "Resistor"},
    {"type": "source_component", "source_component_id": "sc_u1",
     "name": "U1", "value": "ATmega328P", "footprint": "TQFP-32",
     "mpn": "ATMEGA328P-AU", "manufacturer": "Microchip", "description": "MCU"},
    # pcb components
    {"type": "pcb_component", "pcb_component_id": "pcb_r1",
     "source_component_id": "sc_r1",
     "x": 15.0, "y": 20.0, "rotation": 0.0, "layer": "top_copper"},
    {"type": "pcb_component", "pcb_component_id": "pcb_u1",
     "source_component_id": "sc_u1",
     "x": 50.0, "y": 30.0, "rotation": 90.0, "layer": "top_copper"},
    # SMT pad (top copper, rect)
    {"type": "pcb_smtpad", "x": 14.5, "y": 20.0,
     "width": 1.2, "height": 0.8, "shape": "rect", "layer": "top_copper"},
    # SMT pad (bottom copper, circle)
    {"type": "pcb_smtpad", "x": 65.0, "y": 45.0,
     "width": 1.0, "height": 1.0, "shape": "circle", "layer": "bottom_copper"},
    # SMT pad (top copper, oval)
    {"type": "pcb_smtpad", "x": 20.0, "y": 25.0,
     "width": 1.5, "height": 0.9, "shape": "oval", "layer": "top_copper"},
    # PTH pad
    {"type": "pcb_plated_pad", "x": 48.0, "y": 28.0,
     "width": 1.6, "height": 1.6, "hole_diameter": 0.8,
     "shape": "circle", "layer": "top_copper"},
    # via
    {"type": "pcb_via", "x": 30.0, "y": 25.0,
     "outer_diameter": 0.6, "hole_diameter": 0.3},
    # trace
    {"type": "pcb_trace", "net_id": "GND",
     "route": [
         {"x": 15.0, "y": 20.0, "width": 0.25, "layer": "top_copper"},
         {"x": 30.0, "y": 20.0, "width": 0.25, "layer": "top_copper"},
     ]},
    # copper pour (bottom)
    {"type": "copper_pour_fill", "layer": "bottom_copper",
     "polygon": [
         {"x": 0.0, "y": 0.0}, {"x": 80.0, "y": 0.0},
         {"x": 80.0, "y": 60.0}, {"x": 0.0, "y": 60.0},
     ]},
    # silkscreen line (top)
    {"type": "pcb_silkscreen_line",
     "route": [{"x": 5.0, "y": 5.0}, {"x": 10.0, "y": 5.0}],
     "stroke_width": 0.15, "layer": "top_silk"},
    # mounting hole
    {"type": "pcb_hole", "x": 5.0, "y": 5.0, "hole_diameter": 3.2},
]


def _open_tgz(tgz_bytes: bytes) -> tarfile.TarFile:
    return tarfile.open(fileobj=io.BytesIO(tgz_bytes), mode="r:gz")


def _member_text(tf: tarfile.TarFile, path: str) -> str:
    m = tf.getmember(path)
    return tf.extractfile(m).read().decode()


# ─── Directory structure ──────────────────────────────────────────────────────

class TestDirectoryStructure(unittest.TestCase):

    def setUp(self):
        self.result = export_odbpp(FIXTURE, stem="myboard")
        self.manifest = self.result["manifest"]

    def test_returns_dict_with_tgz_bytes(self):
        self.assertIn("tgz_bytes", self.result)
        self.assertIsInstance(self.result["tgz_bytes"], bytes)

    def test_returns_manifest_list(self):
        self.assertIn("manifest", self.result)
        self.assertIsInstance(self.manifest, list)
        self.assertGreater(len(self.manifest), 0)

    def test_manifest_is_sorted(self):
        self.assertEqual(self.manifest, sorted(self.manifest))

    def test_misc_info_in_manifest(self):
        self.assertIn("myboard/misc/info", self.manifest)

    def test_stephdr_in_manifest(self):
        self.assertIn("myboard/steps/pcb/stephdr", self.manifest)

    def test_all_layers_have_features(self):
        expected_layers = [
            "top_copper", "bottom_copper",
            "top_silk", "bottom_silk",
            "top_mask", "bottom_mask",
            "drill", "outline",
        ]
        for lyr in expected_layers:
            path = f"myboard/steps/pcb/layers/{lyr}/features"
            self.assertIn(path, self.manifest, f"Missing features for {lyr}")

    def test_all_layers_have_attrlist(self):
        expected_layers = [
            "top_copper", "bottom_copper",
            "top_silk", "bottom_silk",
            "top_mask", "bottom_mask",
            "drill", "outline",
        ]
        for lyr in expected_layers:
            path = f"myboard/steps/pcb/layers/{lyr}/attrlist"
            self.assertIn(path, self.manifest)

    def test_all_layers_have_components(self):
        expected_layers = [
            "top_copper", "bottom_copper",
            "top_silk", "bottom_silk",
            "top_mask", "bottom_mask",
            "drill", "outline",
        ]
        for lyr in expected_layers:
            path = f"myboard/steps/pcb/layers/{lyr}/components"
            self.assertIn(path, self.manifest)

    def test_stem_name_in_paths(self):
        for path in self.manifest:
            self.assertTrue(path.startswith("myboard/"),
                            f"Path {path!r} does not start with 'myboard/'")


# ─── tgz validity ────────────────────────────────────────────────────────────

class TestTgzValidity(unittest.TestCase):

    def setUp(self):
        self.result = export_odbpp(FIXTURE, stem="board")
        self.tgz_bytes = self.result["tgz_bytes"]

    def test_tgz_is_valid_tar(self):
        self.assertTrue(tarfile.is_tarfile(io.BytesIO(self.tgz_bytes)))

    def test_tgz_is_gzip_compressed(self):
        # gzip magic bytes: 0x1f 0x8b
        self.assertEqual(self.tgz_bytes[:2], b"\x1f\x8b")

    def test_tar_member_names_match_manifest(self):
        with _open_tgz(self.tgz_bytes) as tf:
            tar_names = sorted(tf.getnames())
        self.assertEqual(tar_names, sorted(self.result["manifest"]))

    def test_all_members_have_nonzero_size(self):
        with _open_tgz(self.tgz_bytes) as tf:
            for m in tf.getmembers():
                self.assertGreater(m.size, 0,
                                   f"Member {m.name!r} has zero size")


# ─── misc/info ────────────────────────────────────────────────────────────────

class TestMiscInfo(unittest.TestCase):

    def setUp(self):
        result = export_odbpp(FIXTURE, stem="board")
        with _open_tgz(result["tgz_bytes"]) as tf:
            self.info = _member_text(tf, "board/misc/info")

    def test_product_name_present(self):
        self.assertIn("Kerf Electronics", self.info)

    def test_odb_version_declared(self):
        self.assertIn("ODB_VERSION=7.0", self.info)

    def test_units_mm(self):
        self.assertIn("UNITS=MM", self.info)

    def test_creation_date_present(self):
        self.assertIn("CREATION_DATE=", self.info)

    def test_step_name_present(self):
        self.assertIn("STEP=board", self.info)


# ─── stephdr ─────────────────────────────────────────────────────────────────

class TestStephdr(unittest.TestCase):

    def setUp(self):
        result = export_odbpp(FIXTURE, stem="board")
        with _open_tgz(result["tgz_bytes"]) as tf:
            self.hdr = _member_text(tf, "board/steps/pcb/stephdr")

    def test_units_mm(self):
        self.assertIn("UNITS=MM", self.hdr)

    def test_board_width_correct(self):
        self.assertIn("BOARD_WIDTH=80.000000", self.hdr)

    def test_board_height_correct(self):
        self.assertIn("BOARD_HEIGHT=60.000000", self.hdr)

    def test_all_layers_listed(self):
        for lyr in ("top_copper", "bottom_copper", "top_silk", "bottom_silk",
                    "top_mask", "bottom_mask", "drill", "outline"):
            self.assertIn(f"LAYER={lyr}", self.hdr)


# ─── attrlist ─────────────────────────────────────────────────────────────────

class TestAttrlist(unittest.TestCase):

    def _get(self, layer: str) -> str:
        result = export_odbpp(FIXTURE, stem="board")
        with _open_tgz(result["tgz_bytes"]) as tf:
            return _member_text(tf, f"board/steps/pcb/layers/{layer}/attrlist")

    def test_top_copper_type_signal(self):
        self.assertIn("type signal", self._get("top_copper"))

    def test_top_mask_polarity_negative(self):
        self.assertIn("polarity negative", self._get("top_mask"))

    def test_bottom_mask_polarity_negative(self):
        self.assertIn("polarity negative", self._get("bottom_mask"))

    def test_drill_type_drill(self):
        self.assertIn("type drill", self._get("drill"))

    def test_outline_type_rout(self):
        self.assertIn("type rout", self._get("outline"))

    def test_silk_type_silk_screen(self):
        self.assertIn("type silk_screen", self._get("top_silk"))


# ─── features: copper layers ──────────────────────────────────────────────────

class TestTopCopperFeatures(unittest.TestCase):

    def setUp(self):
        result = export_odbpp(FIXTURE, stem="board")
        with _open_tgz(result["tgz_bytes"]) as tf:
            self.feat = _member_text(tf, "board/steps/pcb/layers/top_copper/features")

    def test_units_mm_declared(self):
        self.assertIn("UNITS=MM", self.feat)

    def test_pad_records_present(self):
        # P x y sym_idx polarity orient mirror;
        # e.g. "P 14.500000 20.000000 0 P 0 0;"
        pad_lines = [l for l in self.feat.splitlines() if l.startswith("P ")]
        self.assertGreater(len(pad_lines), 0)
        self.assertRegex(pad_lines[0], r"^P [\d.]+ [\d.]+ \d+ P \d+ \d+;$")

    def test_line_records_present_for_trace(self):
        line_lines = [l for l in self.feat.splitlines() if l.startswith("L ")]
        self.assertGreater(len(line_lines), 0)

    def test_rect_sym_present_for_rect_pad(self):
        self.assertIn("rect", self.feat)

    def test_oval_sym_present_for_oval_pad(self):
        self.assertIn("oval", self.feat)

    def test_via_pad_on_top_copper(self):
        # Via outer_diameter=0.6 → symbol r0.600000
        self.assertIn("r0.600000", self.feat)


class TestBottomCopperFeatures(unittest.TestCase):

    def setUp(self):
        result = export_odbpp(FIXTURE, stem="board")
        with _open_tgz(result["tgz_bytes"]) as tf:
            self.feat = _member_text(tf, "board/steps/pcb/layers/bottom_copper/features")

    def test_circle_pad_on_bottom_copper(self):
        # circle pad x=65, diam=1.0 → r1.000000
        self.assertIn("r1.000000", self.feat)

    def test_copper_pour_surface_record(self):
        self.assertIn("S P;", self.feat)
        self.assertIn("OB ", self.feat)
        self.assertIn("OS ", self.feat)
        self.assertIn("OE;", self.feat)

    def test_via_appears_on_bottom_copper(self):
        self.assertIn("r0.600000", self.feat)


# ─── features: drill layer ────────────────────────────────────────────────────

class TestDrillFeatures(unittest.TestCase):

    def setUp(self):
        result = export_odbpp(FIXTURE, stem="board")
        with _open_tgz(result["tgz_bytes"]) as tf:
            self.feat = _member_text(tf, "board/steps/pcb/layers/drill/features")

    def test_via_hole_present(self):
        # via hole_diameter=0.3 → r0.300000
        self.assertIn("r0.300000", self.feat)

    def test_pth_pad_hole_present(self):
        # PTH hole_diameter=0.8 → r0.800000
        self.assertIn("r0.800000", self.feat)

    def test_mounting_hole_present(self):
        # pcb_hole diameter=3.2 → r3.200000
        self.assertIn("r3.200000", self.feat)

    def test_at_least_three_drill_pads(self):
        pad_lines = [l for l in self.feat.splitlines() if l.startswith("P ")]
        self.assertGreaterEqual(len(pad_lines), 3)


# ─── features: outline layer ──────────────────────────────────────────────────

class TestOutlineFeatures(unittest.TestCase):

    def setUp(self):
        result = export_odbpp(FIXTURE, stem="board")
        with _open_tgz(result["tgz_bytes"]) as tf:
            self.feat = _member_text(tf, "board/steps/pcb/layers/outline/features")

    def test_line_records_present(self):
        line_lines = [l for l in self.feat.splitlines() if l.startswith("L ")]
        self.assertGreaterEqual(len(line_lines), 4)  # 4 sides of a rect

    def test_outline_sym_is_circle_aperture(self):
        # Outline uses a circle aperture for line width
        self.assertRegex(self.feat, r"r0\.\d+")


# ─── features: silkscreen layer ───────────────────────────────────────────────

class TestSilkFeatures(unittest.TestCase):

    def setUp(self):
        result = export_odbpp(FIXTURE, stem="board")
        with _open_tgz(result["tgz_bytes"]) as tf:
            self.top_silk = _member_text(
                tf, "board/steps/pcb/layers/top_silk/features")

    def test_silk_line_record_present(self):
        line_lines = [l for l in self.top_silk.splitlines() if l.startswith("L ")]
        self.assertGreater(len(line_lines), 0)

    def test_units_mm_in_silk(self):
        self.assertIn("UNITS=MM", self.top_silk)


# ─── features: soldermask layer ───────────────────────────────────────────────

class TestMaskFeatures(unittest.TestCase):

    def setUp(self):
        result = export_odbpp(FIXTURE, stem="board")
        with _open_tgz(result["tgz_bytes"]) as tf:
            self.top_mask = _member_text(
                tf, "board/steps/pcb/layers/top_mask/features")

    def test_pad_openings_present(self):
        pad_lines = [l for l in self.top_mask.splitlines() if l.startswith("P ")]
        self.assertGreater(len(pad_lines), 0)

    def test_expanded_circle_sym_for_via(self):
        # Via od=0.6, expansion 0.1 → r0.700000
        self.assertIn("r0.700000", self.top_mask)


# ─── components files ─────────────────────────────────────────────────────────

class TestComponentsFiles(unittest.TestCase):

    def setUp(self):
        result = export_odbpp(FIXTURE, stem="board")
        with _open_tgz(result["tgz_bytes"]) as tf:
            self.top_comp = _member_text(
                tf, "board/steps/pcb/layers/top_copper/components")
            self.silk_comp = _member_text(
                tf, "board/steps/pcb/layers/top_silk/components")
            self.drill_comp = _member_text(
                tf, "board/steps/pcb/layers/drill/components")

    def test_cmp_records_on_top_copper(self):
        cmp_lines = [l for l in self.top_comp.splitlines()
                     if l.startswith("CMP ")]
        self.assertGreaterEqual(len(cmp_lines), 2)

    def test_r1_refdes_in_top_components(self):
        self.assertIn("R1", self.top_comp)

    def test_u1_refdes_in_top_components(self):
        self.assertIn("U1", self.top_comp)

    def test_non_copper_layers_have_no_cmp_records(self):
        for comp_text in (self.silk_comp, self.drill_comp):
            cmp_lines = [l for l in comp_text.splitlines()
                         if l.startswith("CMP ")]
            self.assertEqual(len(cmp_lines), 0)

    def test_cmp_record_format(self):
        # CMP x y rot mirror refdes footprint value;
        self.assertRegex(self.top_comp, r"CMP [\d.]+\s+[\d.]+\s+[\d.]+\s+\d\s+\w+")


# ─── empty circuit ────────────────────────────────────────────────────────────

class TestEmptyCircuit(unittest.TestCase):

    def setUp(self):
        self.result = export_odbpp([], stem="empty")

    def test_valid_tgz(self):
        self.assertTrue(tarfile.is_tarfile(io.BytesIO(self.result["tgz_bytes"])))

    def test_manifest_has_expected_paths(self):
        m = self.result["manifest"]
        self.assertIn("empty/misc/info", m)
        self.assertIn("empty/steps/pcb/stephdr", m)
        for lyr in ("top_copper", "bottom_copper", "drill", "outline"):
            self.assertIn(f"empty/steps/pcb/layers/{lyr}/features", m)

    def test_default_board_dims_in_stephdr(self):
        with _open_tgz(self.result["tgz_bytes"]) as tf:
            hdr = _member_text(tf, "empty/steps/pcb/stephdr")
        self.assertIn("BOARD_WIDTH=100.000000", hdr)
        self.assertIn("BOARD_HEIGHT=100.000000", hdr)


# ─── LLM tool integration ─────────────────────────────────────────────────────

class TestOdbppTool(unittest.IsolatedAsyncioTestCase):

    async def test_tool_registered(self):
        from kerf_chat.tools.registry import Registry
        names = {t.spec.name for t in Registry}
        self.assertIn("export_odbpp", names)

    async def test_tool_returns_ok_payload(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_odbpp")
        payload = json.dumps({
            "circuit_json": FIXTURE,
            "stem": "tooltest",
        }).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertNotIn("error", result, result)
        self.assertIn("tgz_b64", result)
        self.assertIn("manifest", result)
        self.assertIn("tgz_filename", result)
        self.assertEqual(result["tgz_filename"], "tooltest-odbpp.tgz")

    async def test_tool_tgz_b64_decodes_to_valid_tar(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_odbpp")
        payload = json.dumps({"circuit_json": FIXTURE}).encode()
        result = json.loads(await tool.run(None, payload))
        tgz = base64.b64decode(result["tgz_b64"])
        self.assertTrue(tarfile.is_tarfile(io.BytesIO(tgz)))

    async def test_tool_bad_args_circuit_json_not_array(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_odbpp")
        payload = json.dumps({"circuit_json": "not-a-list"}).encode()
        result = json.loads(await tool.run(None, payload))
        self.assertIn("error", result)

    async def test_tool_bad_args_invalid_json(self):
        from kerf_chat.tools.registry import Registry
        tool = next(t for t in Registry if t.spec.name == "export_odbpp")
        result = json.loads(await tool.run(None, b"{not json"))
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
