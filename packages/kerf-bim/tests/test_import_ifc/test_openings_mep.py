"""
test_openings_mep.py — pytest suite for kerf_bim.import_ifc openings + MEP.

All tests use in-process mock IFC objects; ifcopenshell is never required.

Test inventory:
  1.  translate_opening – IfcWindow with OverallWidth/Height
  2.  translate_opening – IfcDoor with OverallWidth/Height
  3.  translate_opening – no OverallWidth/Height falls back to defaults + warning
  4.  translate_opening – host_wall resolved via FillsVoids chain
  5.  translate_opening – level resolved via ContainedInStructure
  6.  translate_opening – non-opening entity returns {} + warning
  7.  translate_mep_element – IfcFlowSegment basic node
  8.  translate_mep_element – IfcFlowTerminal with system name
  9.  translate_mep_element – IfcFlowFitting kind mapping
  10. translate_mep_element – unknown subtype falls back to "distribution"
  11. translate_mep_element – level resolved via ContainedInStructure
  12. parser emits openings[] and mep[] keys in bim_payload (mock ifc_file)
  13. parser stats includes openings + mep counts
  14. parser handles IfcWindow / IfcDoor query failure gracefully
  15. parser handles MEP query failure gracefully
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Ensure kerf-bim src is importable ─────────────────────────────────────────
_HERE = Path(__file__).parent
_TESTS_ROOT = _HERE.parent
_PLUGIN_ROOT = _TESTS_ROOT.parent
_PACKAGES = _PLUGIN_ROOT.parent

for entry in _PACKAGES.iterdir():
    if not entry.name.startswith("kerf-"):
        continue
    src = entry / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

# ── Imports under test ─────────────────────────────────────────────────────────
from kerf_bim.import_ifc.openings import translate_opening
from kerf_bim.import_ifc.mep import translate_mep_element, MEP_QUERY_TYPES
from kerf_bim.import_ifc.types import IFCImportResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_entity(ifc_type: str, **attrs) -> MagicMock:
    e = MagicMock()
    e.is_a.return_value = ifc_type
    e.GlobalId = attrs.get("GlobalId", "DEADBEEF00000000000000")
    for k, v in attrs.items():
        setattr(e, k, v)
    return e


def _mock_storey(name: str, guid: str) -> MagicMock:
    s = _mock_entity("IfcBuildingStorey", Name=name, GlobalId=guid)
    return s


def _mock_rel_contained(storey: MagicMock) -> MagicMock:
    rel = MagicMock()
    rel.RelatingStructure = storey
    return rel


# ---------------------------------------------------------------------------
# Tests: translate_opening
# ---------------------------------------------------------------------------

class TestTranslateOpening(unittest.TestCase):

    def _make_window(self, width=900.0, height=1200.0, guid="WIN0000000000000001"):
        w = _mock_entity(
            "IfcWindow",
            Name="W01",
            GlobalId=guid,
            OverallWidth=width,
            OverallHeight=height,
            Representation=None,
            ContainedInStructure=[],
            FillsVoids=[],
            ObjectPlacement=None,
        )
        return w

    def _make_door(self, width=900.0, height=2100.0, guid="DOOR000000000000001"):
        d = _mock_entity(
            "IfcDoor",
            Name="D01",
            GlobalId=guid,
            OverallWidth=width,
            OverallHeight=height,
            Representation=None,
            ContainedInStructure=[],
            FillsVoids=[],
            ObjectPlacement=None,
        )
        return d

    def test_window_kind_and_dimensions(self):
        win = self._make_window(width=1200.0, height=1500.0)
        warnings: list = []
        with patch("kerf_bim.import_ifc.openings._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_opening(win, {}, warnings)
        self.assertEqual(result["kind"], "window")
        self.assertEqual(result["width"], 1200.0)
        self.assertEqual(result["height"], 1500.0)
        self.assertEqual(result["name"], "W01")
        self.assertEqual(result["ifc_guid"], "WIN0000000000000001")

    def test_door_kind_and_dimensions(self):
        door = self._make_door(width=800.0, height=2100.0)
        warnings: list = []
        with patch("kerf_bim.import_ifc.openings._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_opening(door, {}, warnings)
        self.assertEqual(result["kind"], "door")
        self.assertEqual(result["width"], 800.0)
        self.assertEqual(result["height"], 2100.0)

    def test_missing_dimensions_fallback(self):
        """When OverallWidth/Height are absent, defaults are used and a warning is emitted."""
        win = _mock_entity(
            "IfcWindow",
            Name="W-NoSize",
            GlobalId="WIN_NOSIZE00000000",
            OverallWidth=None,
            OverallHeight=None,
            Representation=None,
            ContainedInStructure=[],
            FillsVoids=[],
            ObjectPlacement=None,
        )
        warnings: list = []
        with patch("kerf_bim.import_ifc.openings._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_opening(win, {}, warnings)
        self.assertIn("kind", result)
        self.assertGreater(len(warnings), 0)

    def test_host_wall_resolved_via_fills_voids(self):
        """host_wall is populated by walking FillsVoids → opening → host wall."""
        wall = _mock_entity("IfcWall", Name="Wall-01", GlobalId="WALL0000000001")

        voids_rel = MagicMock()
        voids_rel.RelatingBuildingElement = wall

        opening_elem = MagicMock()
        opening_elem.VoidsElements = [voids_rel]

        fills_rel = MagicMock()
        fills_rel.RelatingOpeningElement = opening_elem

        door = self._make_door()
        door.FillsVoids = [fills_rel]

        warnings: list = []
        with patch("kerf_bim.import_ifc.openings._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_opening(door, {}, warnings)

        self.assertEqual(result["host_wall"], "Wall-01")

    def test_level_resolved_via_contained_in_structure(self):
        storey = _mock_storey("L1", "STOREY0000000000001A")
        storey.is_a.return_value = "IfcBuildingStorey"
        rel = _mock_rel_contained(storey)

        win = self._make_window()
        win.ContainedInStructure = [rel]

        level_map = {"STOREY0000000000001A": "L1"}
        warnings: list = []
        with patch("kerf_bim.import_ifc.openings._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_opening(win, level_map, warnings)

        self.assertEqual(result["level"], "L1")

    def test_non_opening_entity_returns_empty(self):
        wall = _mock_entity("IfcWall", Name="NotAnOpening", GlobalId="WALL_NOTOPEN")
        warnings: list = []
        result = translate_opening(wall, {}, warnings)
        self.assertEqual(result, {})
        self.assertGreater(len(warnings), 0)

    def test_position_populated(self):
        win = self._make_window()
        warnings: list = []
        with patch("kerf_bim.import_ifc.openings._placement_origin", return_value=(100.0, 200.0, 900.0)):
            result = translate_opening(win, {}, warnings)
        self.assertEqual(result["position"], [100.0, 200.0, 900.0])


# ---------------------------------------------------------------------------
# Tests: translate_mep_element
# ---------------------------------------------------------------------------

class TestTranslateMepElement(unittest.TestCase):

    def _make_segment(self, guid="SEG0000000000000001"):
        s = _mock_entity(
            "IfcFlowSegment",
            Name="Pipe-01",
            GlobalId=guid,
            PredefinedType="RIGIDSEGMENT",
            ContainedInStructure=[],
            HasAssignments=[],
            ObjectPlacement=None,
        )
        return s

    def _make_terminal(self, guid="TERM000000000000001"):
        t = _mock_entity(
            "IfcFlowTerminal",
            Name="Diffuser-01",
            GlobalId=guid,
            PredefinedType=None,
            ContainedInStructure=[],
            HasAssignments=[],
            ObjectPlacement=None,
        )
        return t

    def _make_fitting(self, guid="FITT000000000000001"):
        f = _mock_entity(
            "IfcFlowFitting",
            Name="Elbow-01",
            GlobalId=guid,
            PredefinedType=None,
            ContainedInStructure=[],
            HasAssignments=[],
            ObjectPlacement=None,
        )
        return f

    def test_flow_segment_kind(self):
        seg = self._make_segment()
        warnings: list = []
        with patch("kerf_bim.import_ifc.mep._placement_origin", return_value=(0.0, 0.0, 3000.0)):
            result = translate_mep_element(seg, {}, warnings)
        self.assertEqual(result["kind"], "segment")
        self.assertEqual(result["ifc_class"], "IfcFlowSegment")
        self.assertEqual(result["name"], "Pipe-01")
        self.assertEqual(result["predefined_type"], "RIGIDSEGMENT")

    def test_flow_terminal_kind(self):
        term = self._make_terminal()
        warnings: list = []
        with patch("kerf_bim.import_ifc.mep._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_mep_element(term, {}, warnings)
        self.assertEqual(result["kind"], "terminal")

    def test_flow_fitting_kind(self):
        fitting = self._make_fitting()
        warnings: list = []
        with patch("kerf_bim.import_ifc.mep._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_mep_element(fitting, {}, warnings)
        self.assertEqual(result["kind"], "fitting")

    def test_unknown_subtype_fallback_kind(self):
        elem = _mock_entity(
            "IfcDistributionElement",
            Name="Unknown-01",
            GlobalId="DIST000000000000001",
            PredefinedType=None,
            ContainedInStructure=[],
            HasAssignments=[],
            ObjectPlacement=None,
        )
        warnings: list = []
        with patch("kerf_bim.import_ifc.mep._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_mep_element(elem, {}, warnings)
        self.assertEqual(result["kind"], "distribution")

    def test_level_resolved_via_contained_in_structure(self):
        storey = _mock_storey("L2", "STOREY0000000000002B")
        storey.is_a.return_value = "IfcBuildingStorey"
        rel = MagicMock()
        rel.RelatingStructure = storey

        seg = self._make_segment()
        seg.ContainedInStructure = [rel]

        level_map = {"STOREY0000000000002B": "L2"}
        warnings: list = []
        with patch("kerf_bim.import_ifc.mep._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_mep_element(seg, level_map, warnings)
        self.assertEqual(result["level"], "L2")

    def test_system_name_from_has_assignments(self):
        """system_name is resolved via HasAssignments → IfcRelAssignsToGroup → IfcSystem."""
        system_group = MagicMock()
        system_group.is_a.return_value = "IfcDistributionSystem"
        system_group.Name = "Supply Air"

        group_rel = MagicMock()
        group_rel.is_a.return_value = "IfcRelAssignsToGroup"
        group_rel.RelatingGroup = system_group

        term = self._make_terminal()
        term.HasAssignments = [group_rel]

        warnings: list = []
        with patch("kerf_bim.import_ifc.mep._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_mep_element(term, {}, warnings)
        self.assertEqual(result["system_name"], "Supply Air")

    def test_position_populated(self):
        seg = self._make_segment()
        warnings: list = []
        with patch("kerf_bim.import_ifc.mep._placement_origin", return_value=(500.0, 1000.0, 2700.0)):
            result = translate_mep_element(seg, {}, warnings)
        self.assertEqual(result["position"], [500.0, 1000.0, 2700.0])


# ---------------------------------------------------------------------------
# Tests: parser integration (mocked ifc_file)
# ---------------------------------------------------------------------------

class TestParserOpeningsMep(unittest.TestCase):

    def _build_mock_ifc_file(
        self,
        windows=None,
        doors=None,
        mep_segments=None,
    ):
        """Build a minimal mock ifc_file that parser.parse_ifc_file can call."""
        mock_ifc = MagicMock()

        def by_type(entity_type):
            if entity_type == "IfcProject":
                proj = MagicMock()
                proj.Name = "TestProject"
                return [proj]
            if entity_type == "IfcSite":
                return []
            if entity_type in ("IfcBuildingStorey",):
                return []
            if entity_type in ("IfcWall", "IfcWallStandardCase"):
                return []
            if entity_type == "IfcSlab":
                return []
            if entity_type == "IfcSpace":
                return []
            if entity_type == "IfcWindow":
                return windows or []
            if entity_type == "IfcDoor":
                return doors or []
            if entity_type == "IfcFlowSegment":
                return mep_segments or []
            # all other MEP types and skipped structural types return empty
            return []

        mock_ifc.by_type.side_effect = by_type
        return mock_ifc

    def _call_parser_with_mock(self, mock_ifc):
        """Call parse_ifc_file with ifcopenshell mocked to return our fake file."""
        mock_ifcos = MagicMock()
        mock_ifcos.open.return_value = mock_ifc

        with patch.dict(sys.modules, {"ifcopenshell": mock_ifcos}):
            import importlib
            from kerf_bim.import_ifc import parser as _parser
            importlib.reload(_parser)

            import tempfile, os
            with tempfile.NamedTemporaryFile(suffix=".ifc", delete=False) as f:
                f.write(b"ISO-10303-21;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
                tmp_path = Path(f.name)
            try:
                result = _parser.parse_ifc_file(tmp_path)
            finally:
                os.unlink(tmp_path)

        return result

    def _make_window_node(self, guid="WIN_PARSER_0000001"):
        w = _mock_entity(
            "IfcWindow",
            Name="W-P01",
            GlobalId=guid,
            OverallWidth=1000.0,
            OverallHeight=1200.0,
            Representation=None,
            ContainedInStructure=[],
            FillsVoids=[],
            ObjectPlacement=None,
        )
        return w

    def _make_segment_node(self, guid="SEG_PARSER_0000001"):
        s = _mock_entity(
            "IfcFlowSegment",
            Name="Pipe-P01",
            GlobalId=guid,
            PredefinedType=None,
            ContainedInStructure=[],
            HasAssignments=[],
            ObjectPlacement=None,
        )
        return s

    def test_parser_bim_payload_has_openings_key(self):
        mock_ifc = self._build_mock_ifc_file()
        result = self._call_parser_with_mock(mock_ifc)
        self.assertIn("openings", result.bim_payload)

    def test_parser_bim_payload_has_mep_key(self):
        mock_ifc = self._build_mock_ifc_file()
        result = self._call_parser_with_mock(mock_ifc)
        self.assertIn("mep", result.bim_payload)

    def test_parser_translates_windows(self):
        win = self._make_window_node()
        mock_ifc = self._build_mock_ifc_file(windows=[win])
        with patch("kerf_bim.import_ifc.openings._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = self._call_parser_with_mock(mock_ifc)
        self.assertEqual(len(result.bim_payload["openings"]), 1)
        self.assertEqual(result.bim_payload["openings"][0]["kind"], "window")

    def test_parser_translates_mep_segments(self):
        seg = self._make_segment_node()
        mock_ifc = self._build_mock_ifc_file(mep_segments=[seg])
        with patch("kerf_bim.import_ifc.mep._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = self._call_parser_with_mock(mock_ifc)
        self.assertEqual(len(result.bim_payload["mep"]), 1)
        self.assertEqual(result.bim_payload["mep"][0]["kind"], "segment")

    def test_parser_stats_includes_openings_and_mep(self):
        win = self._make_window_node()
        seg = self._make_segment_node()
        mock_ifc = self._build_mock_ifc_file(windows=[win], mep_segments=[seg])
        with patch("kerf_bim.import_ifc.openings._placement_origin", return_value=(0.0, 0.0, 0.0)), \
             patch("kerf_bim.import_ifc.mep._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = self._call_parser_with_mock(mock_ifc)
        self.assertIn("openings", result.stats)
        self.assertIn("mep", result.stats)
        self.assertEqual(result.stats["openings"], 1)
        self.assertEqual(result.stats["mep"], 1)

    def test_parser_handles_window_query_failure_gracefully(self):
        """A by_type exception for IfcWindow should not crash the parser."""
        mock_ifc = self._build_mock_ifc_file()

        original_side_effect = mock_ifc.by_type.side_effect

        def patched_by_type(entity_type):
            if entity_type == "IfcWindow":
                raise RuntimeError("simulated query failure")
            return original_side_effect(entity_type)

        mock_ifc.by_type.side_effect = patched_by_type
        result = self._call_parser_with_mock(mock_ifc)
        # Should not raise; warnings should contain the failure message
        self.assertTrue(any("IfcWindow" in w for w in result.warnings))

    def test_parser_handles_mep_query_failure_gracefully(self):
        """A by_type exception for IfcFlowSegment should not crash the parser."""
        mock_ifc = self._build_mock_ifc_file()

        original_side_effect = mock_ifc.by_type.side_effect

        def patched_by_type(entity_type):
            if entity_type == "IfcFlowSegment":
                raise RuntimeError("simulated mep query failure")
            return original_side_effect(entity_type)

        mock_ifc.by_type.side_effect = patched_by_type
        result = self._call_parser_with_mock(mock_ifc)
        self.assertTrue(any("IfcFlowSegment" in w for w in result.warnings))


if __name__ == "__main__":
    unittest.main()
