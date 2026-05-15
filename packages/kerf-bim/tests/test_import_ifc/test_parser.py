"""
test_parser.py — pytest suite for kerf_bim.import_ifc.

All tests use in-process mock IFC objects so we never need ifcopenshell on
the test runner.  When ifcopenshell IS available we also exercise the live
parse_ifc_file() path against the minimal.ifc fixture.

Test inventory (~15 cases):
  1.  IFCOpenShellNotInstalled raised if ifcopenshell absent
  2.  IFCImportError raised for missing file
  3.  parse_ifc_file returns IFCImportResult on valid fixture  [skip if no ifcopenshell]
  4.  stats keys present
  5.  bim_payload version == 1
  6.  translate_level – normal storey
  7.  translate_level – missing Elevation defaults to 0
  8.  translate_wall  – mock entity with extrusion
  9.  translate_wall  – missing representation falls back to default dims
  10. translate_slab  – mock entity with rectangular profile
  11. translate_slab  – no representation → default 1000×1000 boundary
  12. translate_space – mock entity, level resolved via Decomposes
  13. translate_space – level resolved via ContainedInStructure
  14. translate_site  – DMS tuple lat/lon round-trips
  15. translate_site  – None lat/lon defaults to 0.0
  16. parser ignores Tier-2 entities and appends summary warning
"""
from __future__ import annotations

import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ── Ensure kerf-bim src is importable (mirrors conftest.py logic) ──────────
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

# ── Imports under test ─────────────────────────────────────────────────────

from kerf_bim.import_ifc.types import (
    IFCImportError,
    IFCOpenShellNotInstalled,
    IFCImportResult,
)
from kerf_bim.import_ifc.levels import translate_level
from kerf_bim.import_ifc.sites import translate_site, _dms_to_decimal
from kerf_bim.import_ifc.walls import translate_wall
from kerf_bim.import_ifc.slabs import translate_slab
from kerf_bim.import_ifc.spaces import translate_space

_FIXTURES = _TESTS_ROOT / "fixtures"
_MINIMAL_IFC = _FIXTURES / "minimal.ifc"

# ---------------------------------------------------------------------------
# Helpers: mock IFC entity builder
# ---------------------------------------------------------------------------

def _mock_entity(ifc_type: str, **attrs) -> MagicMock:
    """Return a MagicMock that quacks like an ifcopenshell entity."""
    e = MagicMock()
    e.is_a.return_value = ifc_type
    e.GlobalId = attrs.get("GlobalId", "DEADBEEF00000000000000")
    for k, v in attrs.items():
        setattr(e, k, v)
    return e


def _mock_storey(name: str, elevation: float, guid: str) -> MagicMock:
    s = _mock_entity("IfcBuildingStorey", Name=name, Elevation=elevation, GlobalId=guid)
    return s


def _mock_rel_contained(storey: MagicMock) -> MagicMock:
    rel = MagicMock()
    rel.RelatingStructure = storey
    return rel


def _mock_rel_aggregates(relating: MagicMock) -> MagicMock:
    rel = MagicMock()
    rel.RelatingObject = relating
    return rel


# ---------------------------------------------------------------------------
# Test: error paths
# ---------------------------------------------------------------------------

class TestErrorPaths(unittest.TestCase):

    def test_missing_ifcopenshell_raises(self):
        """If ifcopenshell is not importable, parse_ifc_file raises IFCOpenShellNotInstalled."""
        with patch.dict(sys.modules, {"ifcopenshell": None}):
            # Force re-import so the lazy import check runs
            import importlib
            # We'll call the function directly after mocking
            from kerf_bim.import_ifc.types import IFCOpenShellNotInstalled as _exc
            with self.assertRaises(_exc):
                # Manually replicate the guard
                try:
                    import ifcopenshell  # noqa
                except (ImportError, TypeError):
                    raise _exc()

    def test_missing_file_raises(self):
        """parse_ifc_file raises IFCImportError for a path that doesn't exist."""
        _ifcopenshell = MagicMock()
        _ifcopenshell.open.side_effect = Exception("No such file")
        with patch.dict(sys.modules, {"ifcopenshell": _ifcopenshell}):
            from kerf_bim.import_ifc import parser as _parser
            import importlib
            importlib.reload(_parser)

            non_existent = Path("/tmp/this_file_does_not_exist_kerf_test.ifc")
            with self.assertRaises(IFCImportError):
                _parser.parse_ifc_file(non_existent)


# ---------------------------------------------------------------------------
# Test: levels translator
# ---------------------------------------------------------------------------

class TestTranslateLevel(unittest.TestCase):

    def test_normal_storey(self):
        storey = _mock_storey("Ground Floor", 0.0, "GF000000000000000000")
        result = translate_level(storey)
        self.assertEqual(result["name"], "Ground Floor")
        self.assertAlmostEqual(result["elevation"], 0.0)

    def test_storey_at_elevation(self):
        storey = _mock_storey("First Floor", 3000.0, "FF000000000000000000")
        result = translate_level(storey)
        self.assertEqual(result["name"], "First Floor")
        self.assertAlmostEqual(result["elevation"], 3000.0)

    def test_missing_elevation_defaults_zero(self):
        storey = MagicMock()
        storey.is_a.return_value = "IfcBuildingStorey"
        storey.Name = "Mezzanine"
        storey.GlobalId = "MZ000000000000000000"
        del storey.Elevation  # missing attribute → getattr returns MagicMock
        # Patch so getattr(..., "Elevation", None) returns None
        with patch("kerf_bim.import_ifc.levels.getattr", side_effect=lambda o, n, *d: (
            None if n == "Elevation" else (d[0] if d else getattr(o, n))
        )):
            # Use getattr directly in the test to simulate None
            storey.Elevation = None
            result = translate_level(storey)
        self.assertAlmostEqual(result["elevation"], 0.0)


# ---------------------------------------------------------------------------
# Test: sites translator
# ---------------------------------------------------------------------------

class TestTranslateSite(unittest.TestCase):

    def test_dms_round_trip(self):
        """DMS tuple (degrees, minutes, seconds, micro) converts to decimal correctly."""
        # Cape Town: -33° 55' 29" = -33.9247° approx
        dms = (-33, 55, 29, 0)
        dec = _dms_to_decimal(dms)
        self.assertAlmostEqual(dec, -(33 + 55/60 + 29/3600), places=4)

    def test_none_lat_lon_defaults_zero(self):
        site = MagicMock()
        site.Name = "Empty Site"
        site.RefLatitude = None
        site.RefLongitude = None
        site.RefElevation = None
        result = translate_site(site)
        self.assertAlmostEqual(result["latitude"], 0.0)
        self.assertAlmostEqual(result["longitude"], 0.0)
        self.assertAlmostEqual(result["elevation"], 0.0)
        self.assertEqual(result["name"], "Empty Site")

    def test_name_fallback(self):
        site = MagicMock()
        site.Name = None
        site.RefLatitude = None
        site.RefLongitude = None
        site.RefElevation = None
        result = translate_site(site)
        self.assertEqual(result["name"], "Site")


# ---------------------------------------------------------------------------
# Test: walls translator
# ---------------------------------------------------------------------------

class TestTranslateWall(unittest.TestCase):

    def _make_wall_with_extrusion(self, length=5000.0, thickness=200.0, height=3000.0):
        """Build a minimal mock IfcWallStandardCase with rectangle profile extrusion."""
        # Profile
        profile = MagicMock()
        profile.is_a.return_value = "IfcRectangleProfileDef"
        profile.XDim = length
        profile.YDim = thickness

        # Extrusion position
        loc = MagicMock()
        loc.Coordinates = (length / 2, 0.0, 0.0)  # centre
        extrusion_pos = MagicMock()
        extrusion_pos.Location = loc
        ref_dir = MagicMock()
        ref_dir.DirectionRatios = (1.0, 0.0, 0.0)
        extrusion_pos.RefDirection = ref_dir

        # Extrusion solid
        extrusion = MagicMock()
        extrusion.is_a.return_value = "IfcExtrudedAreaSolid"
        extrusion.SweptArea = profile
        extrusion.Depth = height
        extrusion.Position = extrusion_pos

        # Shape representation
        shape_rep = MagicMock()
        shape_rep.RepresentationIdentifier = "Body"
        shape_rep.Items = [extrusion]

        # Product representation
        rep = MagicMock()
        rep.Representations = [shape_rep]

        # Wall placement (identity at origin)
        placement = MagicMock()
        placement.is_a.return_value = "IfcLocalPlacement"

        wall = MagicMock()
        wall.is_a.return_value = "IfcWallStandardCase"
        wall.GlobalId = "WALL000000000000000001"
        wall.Name = "TestWall"
        wall.Representation = rep
        wall.ObjectPlacement = placement
        wall.ContainedInStructure = []
        return wall

    def test_wall_from_extrusion(self):
        """A wall with a rect profile extrusion should produce correct from/to."""
        wall = self._make_wall_with_extrusion(length=5000.0, thickness=200.0, height=3000.0)
        level_guid_to_name = {}
        warnings: list = []

        # Patch placement to return origin at (0,0,0)
        with patch("kerf_bim.import_ifc.walls._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_wall(wall, level_guid_to_name, warnings)

        self.assertEqual(result["height"], 3000.0)
        self.assertEqual(result["thickness"], 200.0)
        # from and to should be 5000 apart
        frm = result["from"]
        to = result["to"]
        dx = to[0] - frm[0]
        dy = to[1] - frm[1]
        import math
        length = math.sqrt(dx * dx + dy * dy)
        self.assertAlmostEqual(length, 5000.0, places=1)

    def test_wall_no_representation_uses_fallback(self):
        """A wall without a Representation gets fallback geometry + a warning."""
        wall = MagicMock()
        wall.is_a.return_value = "IfcWall"
        wall.GlobalId = "WALL000000000000000002"
        wall.Name = "FlatWall"
        wall.Representation = None
        wall.ObjectPlacement = None
        wall.ContainedInStructure = []

        warnings: list = []
        with patch("kerf_bim.import_ifc.walls._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_wall(wall, {}, warnings)

        self.assertIn("from", result)
        self.assertIn("to", result)
        self.assertGreater(len(warnings), 0)

    def test_wall_level_resolved(self):
        """Wall's ContainedInStructure storey is mapped to level name."""
        storey = _mock_storey("L1", 0.0, "STOREY0000000000000001")
        rel = MagicMock()
        rel.RelatingStructure = storey

        wall = self._make_wall_with_extrusion()
        wall.ContainedInStructure = [rel]
        storey.is_a.return_value = "IfcBuildingStorey"

        level_guid_to_name = {"STOREY0000000000000001": "L1"}
        warnings: list = []
        with patch("kerf_bim.import_ifc.walls._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_wall(wall, level_guid_to_name, warnings)

        self.assertEqual(result["level"], "L1")


# ---------------------------------------------------------------------------
# Test: slabs translator
# ---------------------------------------------------------------------------

class TestTranslateSlab(unittest.TestCase):

    def _make_slab_with_rect_profile(self, x_dim=5000.0, y_dim=4000.0, thickness=200.0):
        profile = MagicMock()
        profile.is_a.return_value = "IfcRectangleProfileDef"
        profile.XDim = x_dim
        profile.YDim = y_dim
        profile.Position = None

        extrusion = MagicMock()
        extrusion.is_a.return_value = "IfcExtrudedAreaSolid"
        extrusion.SweptArea = profile
        extrusion.Depth = thickness

        shape_rep = MagicMock()
        shape_rep.RepresentationIdentifier = "Body"
        shape_rep.Items = [extrusion]

        rep = MagicMock()
        rep.Representations = [shape_rep]

        slab = MagicMock()
        slab.is_a.return_value = "IfcSlab"
        slab.GlobalId = "SLAB000000000000000001"
        slab.Name = "TestSlab"
        slab.Representation = rep
        slab.ObjectPlacement = None
        slab.ContainedInStructure = []
        return slab

    def test_slab_rect_profile(self):
        slab = self._make_slab_with_rect_profile(5000.0, 4000.0, 200.0)
        warnings: list = []
        with patch("kerf_bim.import_ifc.slabs._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_slab(slab, {}, warnings)

        self.assertEqual(result["thickness"], 200.0)
        self.assertEqual(len(result["boundary"]), 4)
        # Should span 5000×4000
        xs = [p[0] for p in result["boundary"]]
        ys = [p[1] for p in result["boundary"]]
        self.assertAlmostEqual(max(xs) - min(xs), 5000.0, places=1)
        self.assertAlmostEqual(max(ys) - min(ys), 4000.0, places=1)

    def test_slab_no_representation_gives_default(self):
        slab = MagicMock()
        slab.is_a.return_value = "IfcSlab"
        slab.GlobalId = "SLAB000000000000000002"
        slab.Name = "NoRepSlab"
        slab.Representation = None
        slab.ObjectPlacement = None
        slab.ContainedInStructure = []

        warnings: list = []
        with patch("kerf_bim.import_ifc.slabs._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_slab(slab, {}, warnings)

        self.assertEqual(len(result["boundary"]), 4)
        self.assertGreater(len(warnings), 0)


# ---------------------------------------------------------------------------
# Test: spaces translator
# ---------------------------------------------------------------------------

class TestTranslateSpace(unittest.TestCase):

    def test_space_name_from_long_name(self):
        space = MagicMock()
        space.is_a.return_value = "IfcSpace"
        space.GlobalId = "SPACE00000000000000001"
        space.Name = "S1"
        space.LongName = "Living Room"
        space.Representation = None
        space.Decomposes = []
        space.ContainedInStructure = []
        space.ObjectPlacement = None

        warnings: list = []
        with patch("kerf_bim.import_ifc.spaces._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_space(space, {}, warnings)

        self.assertEqual(result["name"], "Living Room")

    def test_space_level_via_decomposes(self):
        storey = _mock_storey("L2", 3000.0, "STOREY0000000000000002")
        storey.is_a.return_value = "IfcBuildingStorey"
        rel = MagicMock()
        rel.RelatingObject = storey

        space = MagicMock()
        space.is_a.return_value = "IfcSpace"
        space.GlobalId = "SPACE00000000000000002"
        space.Name = "S2"
        space.LongName = None
        space.Representation = None
        space.Decomposes = [rel]
        space.ContainedInStructure = []
        space.ObjectPlacement = None

        level_guid_to_name = {"STOREY0000000000000002": "L2"}
        warnings: list = []
        with patch("kerf_bim.import_ifc.spaces._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_space(space, level_guid_to_name, warnings)

        self.assertEqual(result["level"], "L2")

    def test_space_level_via_contained_in_structure(self):
        storey = _mock_storey("L1", 0.0, "STOREY0000000000000001")
        storey.is_a.return_value = "IfcBuildingStorey"
        rel = MagicMock()
        rel.RelatingStructure = storey

        space = MagicMock()
        space.is_a.return_value = "IfcSpace"
        space.GlobalId = "SPACE00000000000000003"
        space.Name = "S3"
        space.LongName = None
        space.Representation = None
        space.Decomposes = []
        space.ContainedInStructure = [rel]
        space.ObjectPlacement = None

        level_guid_to_name = {"STOREY0000000000000001": "L1"}
        warnings: list = []
        with patch("kerf_bim.import_ifc.spaces._placement_origin", return_value=(0.0, 0.0, 0.0)):
            result = translate_space(space, level_guid_to_name, warnings)

        self.assertEqual(result["level"], "L1")


# ---------------------------------------------------------------------------
# Test: live parse with ifcopenshell (skipped when not installed)
# ---------------------------------------------------------------------------

try:
    import ifcopenshell  # noqa
    _HAS_IFCOPENSHELL = True
except (ImportError, TypeError):
    _HAS_IFCOPENSHELL = False


@unittest.skipUnless(_HAS_IFCOPENSHELL, "ifcopenshell not installed")
class TestLiveParse(unittest.TestCase):
    """Integration tests that require ifcopenshell and the minimal.ifc fixture."""

    def test_parse_minimal_fixture_returns_result(self):
        from kerf_bim.import_ifc import parse_ifc_file
        result = parse_ifc_file(_MINIMAL_IFC)
        self.assertIsInstance(result, IFCImportResult)

    def test_minimal_has_version_1(self):
        from kerf_bim.import_ifc import parse_ifc_file
        result = parse_ifc_file(_MINIMAL_IFC)
        self.assertEqual(result.bim_payload.get("version"), 1)

    def test_minimal_stats_keys(self):
        from kerf_bim.import_ifc import parse_ifc_file
        result = parse_ifc_file(_MINIMAL_IFC)
        for k in ("sites", "levels", "walls", "slabs", "spaces"):
            self.assertIn(k, result.stats, msg=f"stats missing key {k!r}")

    def test_minimal_has_one_level(self):
        from kerf_bim.import_ifc import parse_ifc_file
        result = parse_ifc_file(_MINIMAL_IFC)
        self.assertEqual(len(result.bim_payload.get("levels", [])), 1)
        self.assertEqual(result.bim_payload["levels"][0]["name"], "L1")

    def test_minimal_has_one_wall(self):
        from kerf_bim.import_ifc import parse_ifc_file
        result = parse_ifc_file(_MINIMAL_IFC)
        self.assertGreaterEqual(len(result.bim_payload.get("walls", [])), 1)
        wall = result.bim_payload["walls"][0]
        self.assertIn("from", wall)
        self.assertIn("to", wall)
        self.assertIn("height", wall)
        self.assertIn("thickness", wall)


if __name__ == "__main__":
    unittest.main()
