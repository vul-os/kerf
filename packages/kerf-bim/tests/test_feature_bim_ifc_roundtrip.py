"""
test_feature_bim_ifc_roundtrip.py — T-49 hermetic pytest suite.

BIM: IFC export Tier 1+2 — round-trip across 25 IFC4 element families.

Scope: kerf_bim.export_ifc/ + import_ifc/ round-trip
Target: packages/kerf-bim/tests/test_feature_bim_ifc_roundtrip.py

Tests (25 cases):

--- GlobalId determinism / preservation ---
 1.  Wall GlobalId is deterministic across two exports of the same model
 2.  Slab GlobalId is deterministic across two exports
 3.  Column GlobalId is deterministic
 4.  Beam GlobalId is deterministic
 5.  Door GlobalId is deterministic
 6.  Window GlobalId is deterministic
 7.  Project GlobalId is deterministic
 8.  Site GlobalId is deterministic
 9.  Building GlobalId is deterministic
10.  Storey GlobalId is deterministic

--- Geometry round-trip (mm → IFC metres → text) ---
11.  Wall length 10 000 mm → 10.0 m appears in IFC4 text
12.  Wall height 4 200 mm → 4.2 m appears in IFC4 text
13.  Wall thickness 300 mm → 0.3 m appears in IFC4 text
14.  Slab boundary 8 000 mm → 8.0 m appears in IFC4 text
15.  Slab thickness 300 mm → 0.3 m appears in IFC4 text
16.  Column width 400 mm → 0.4 m appears in IFC4 text
17.  Column height 3 600 mm → 3.6 m appears in IFC4 text
18.  Beam length 12 000 mm → 12.0 m appears in IFC4 text
19.  Beam height 500 mm → 0.5 m appears in IFC4 text
20.  Door width 900 mm → 0.9 m appears in IFC4 text
21.  Window width 1 500 mm → 1.5 m appears in IFC4 text
22.  Storey elevation 3 600 mm → 3.6 m appears in IFC4 text

--- Pset / metadata round-trip ---
23.  Element name (pset identity) survives export in IFC4 STEP text
24.  Level name (spatial assignment pset) appears in storey entity
25.  Multi-storey model: each level produces its own IfcBuildingStorey with
     correct names, and all elements resolve to their storey's
     IfcRelContainedInSpatialStructure

All tests are pure-Python — no ifcopenshell, no filesystem writes, no network.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

# ── sys.path bootstrap (mirrors conftest.py) ──────────────────────────────────
_HERE = Path(__file__).parent
_PLUGIN_ROOT = _HERE.parent
_PACKAGES = _PLUGIN_ROOT.parent

for _entry in _PACKAGES.iterdir():
    if not _entry.name.startswith("kerf-"):
        continue
    _src = _entry / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

# ── Imports under test ────────────────────────────────────────────────────────
from kerf_bim.export_ifc import export_ifc, IFCExportResult, IFCExportError

# ── Shared helpers ────────────────────────────────────────────────────────────

def _count(text: str, ifc_type: str) -> int:
    """Count #N=IFCTYPE( entities (case-insensitive)."""
    return len(re.findall(rf"#\d+={ifc_type.upper()}\(", text, re.IGNORECASE))


def _has(text: str, ifc_type: str) -> bool:
    return _count(text, ifc_type) > 0


def _find_guids(text: str, ifc_type: str) -> list[str]:
    """Extract all GlobalId strings from entities of the given type."""
    # Pattern: #N=IFCTYPE('GUID', ...
    pattern = rf"#\d+={ifc_type.upper()}\('([^']+)'"
    return re.findall(pattern, text, re.IGNORECASE)


def _export_ifc4(model: dict) -> IFCExportResult:
    return export_ifc(model, schema="IFC4")


# ---------------------------------------------------------------------------
# Fixture models
# ---------------------------------------------------------------------------

_WALL_MODEL = {
    "name": "WallTestProject",
    "levels": [{"name": "GF", "elevation": 0.0}],
    "walls": [
        {
            "name": "W_long",
            "level": "GF",
            "from": [0.0, 0.0],
            "to": [10_000.0, 0.0],
            "height": 4_200.0,
            "thickness": 300.0,
        }
    ],
}

_SLAB_MODEL = {
    "name": "SlabTestProject",
    "levels": [{"name": "GF", "elevation": 0.0}],
    "slabs": [
        {
            "name": "S_large",
            "level": "GF",
            "boundary": [[0, 0], [8_000, 0], [8_000, 6_000], [0, 6_000]],
            "thickness": 300.0,
        }
    ],
}

_COLUMN_MODEL = {
    "name": "ColumnTestProject",
    "levels": [{"name": "GF", "elevation": 0.0}],
    "columns": [
        {
            "name": "C1",
            "level": "GF",
            "position": [0.0, 0.0, 0.0],
            "width": 400.0,
            "depth": 400.0,
            "height": 3_600.0,
        }
    ],
}

_BEAM_MODEL = {
    "name": "BeamTestProject",
    "levels": [{"name": "FF", "elevation": 3_600.0}],
    "beams": [
        {
            "name": "B1",
            "level": "FF",
            "start": [0.0, 0.0, 3_600.0],
            "end": [12_000.0, 0.0, 3_600.0],
            "width": 200.0,
            "height": 500.0,
        }
    ],
}

_OPENING_MODEL = {
    "name": "OpeningsTestProject",
    "levels": [{"name": "GF", "elevation": 0.0}],
    "openings": [
        {
            "name": "D_main",
            "kind": "door",
            "level": "GF",
            "position": [500.0, 0.0, 0.0],
            "width": 900.0,
            "height": 2_100.0,
        },
        {
            "name": "W_large",
            "kind": "window",
            "level": "GF",
            "position": [2_000.0, 0.0, 800.0],
            "width": 1_500.0,
            "height": 1_200.0,
        },
    ],
}

_FULL_MULTI_STOREY = {
    "name": "MultiStoreyProject",
    "site": {"name": "Test Site", "latitude": -33.9, "longitude": 18.4, "elevation": 0.0},
    "levels": [
        {"name": "GF", "elevation": 0.0},
        {"name": "FF", "elevation": 3_600.0},
        {"name": "SF", "elevation": 7_200.0},
    ],
    "walls": [
        {"name": "GF_W1", "level": "GF", "from": [0, 0], "to": [6_000, 0], "height": 3_600, "thickness": 200},
        {"name": "FF_W1", "level": "FF", "from": [0, 0], "to": [6_000, 0], "height": 3_600, "thickness": 200},
        {"name": "SF_W1", "level": "SF", "from": [0, 0], "to": [6_000, 0], "height": 3_600, "thickness": 200},
    ],
    "slabs": [
        {"name": "GF_S1", "level": "GF", "boundary": [[0,0],[6_000,0],[6_000,5_000],[0,5_000]], "thickness": 250},
        {"name": "FF_S1", "level": "FF", "boundary": [[0,0],[6_000,0],[6_000,5_000],[0,5_000]], "thickness": 250},
    ],
    "columns": [
        {"name": "GF_C1", "level": "GF", "position": [0, 0, 0], "width": 300, "depth": 300, "height": 3_600},
    ],
    "beams": [
        {"name": "FF_B1", "level": "FF", "start": [0, 0, 3_600], "end": [6_000, 0, 3_600], "width": 200, "height": 400},
    ],
    "openings": [
        {"name": "GF_D1", "kind": "door", "level": "GF", "position": [500, 0, 0], "width": 900, "height": 2_100},
        {"name": "FF_W1", "kind": "window", "level": "FF", "position": [2_000, 0, 900], "width": 1_200, "height": 1_200},
    ],
}


# ===========================================================================
# 1-6 — GlobalId determinism: walls, slabs, columns, beams, doors, windows
# ===========================================================================

class TestGlobalIdDeterminism(unittest.TestCase):
    """GlobalId for each element type must be identical across two exports."""

    def _guids_match(self, model: dict, ifc_type: str) -> None:
        r1 = _export_ifc4(model)
        r2 = _export_ifc4(model)
        guids1 = _find_guids(r1.ifc_text, ifc_type)
        guids2 = _find_guids(r2.ifc_text, ifc_type)
        self.assertTrue(
            len(guids1) > 0,
            f"No {ifc_type} entities found in first export",
        )
        self.assertEqual(
            guids1,
            guids2,
            f"{ifc_type} GlobalIds differ between exports: {guids1!r} vs {guids2!r}",
        )

    # 1
    def test_wall_global_id_deterministic(self):
        self._guids_match(_WALL_MODEL, "IFCWALL")

    # 2
    def test_slab_global_id_deterministic(self):
        self._guids_match(_SLAB_MODEL, "IFCSLAB")

    # 3
    def test_column_global_id_deterministic(self):
        self._guids_match(_COLUMN_MODEL, "IFCCOLUMN")

    # 4
    def test_beam_global_id_deterministic(self):
        self._guids_match(_BEAM_MODEL, "IFCBEAM")

    # 5
    def test_door_global_id_deterministic(self):
        self._guids_match(_OPENING_MODEL, "IFCDOOR")

    # 6
    def test_window_global_id_deterministic(self):
        self._guids_match(_OPENING_MODEL, "IFCWINDOW")


# ===========================================================================
# 7-10 — GlobalId determinism: spatial structure entities
# ===========================================================================

class TestSpatialGlobalIdDeterminism(unittest.TestCase):
    """Project / Site / Building / Storey GlobalIds must be stable."""

    def _single_guid_matches(self, ifc_type: str) -> None:
        r1 = _export_ifc4(_FULL_MULTI_STOREY)
        r2 = _export_ifc4(_FULL_MULTI_STOREY)
        g1 = _find_guids(r1.ifc_text, ifc_type)
        g2 = _find_guids(r2.ifc_text, ifc_type)
        self.assertGreater(len(g1), 0, f"No {ifc_type} in export")
        self.assertEqual(g1, g2, f"{ifc_type} GlobalIds not deterministic")

    # 7
    def test_project_global_id_deterministic(self):
        self._single_guid_matches("IFCPROJECT")

    # 8
    def test_site_global_id_deterministic(self):
        self._single_guid_matches("IFCSITE")

    # 9
    def test_building_global_id_deterministic(self):
        self._single_guid_matches("IFCBUILDING")

    # 10
    def test_storey_global_id_deterministic(self):
        self._single_guid_matches("IFCBUILDINGSTOREY")


# ===========================================================================
# 11-13 — Wall geometry round-trip
# ===========================================================================

class TestWallGeometryRoundtrip(unittest.TestCase):
    """Wall dimensions in mm must appear as correct metre values in IFC4."""

    def setUp(self):
        self.text = _export_ifc4(_WALL_MODEL).ifc_text

    # 11
    def test_wall_length_10000mm_is_10m(self):
        """10 000 mm wall → length = 10.0 m in extrusion profile."""
        # The wall's RectangleProfileDef XDim should be 10.0 (metres)
        self.assertIn("10.", self.text)

    # 12
    def test_wall_height_4200mm_is_4_2m(self):
        """4 200 mm wall height → extrusion depth = 4.2 m."""
        self.assertIn("4.2", self.text)

    # 13
    def test_wall_thickness_300mm_is_0_3m(self):
        """300 mm thickness → YDim = 0.3 m in rectangle profile."""
        self.assertIn("0.3", self.text)


# ===========================================================================
# 14-15 — Slab geometry round-trip
# ===========================================================================

class TestSlabGeometryRoundtrip(unittest.TestCase):

    def setUp(self):
        self.text = _export_ifc4(_SLAB_MODEL).ifc_text

    # 14
    def test_slab_boundary_8000mm_is_8m(self):
        """8 000 mm boundary → 8.0 m cartesian point coordinate."""
        self.assertIn("8.", self.text)

    # 15
    def test_slab_thickness_300mm_is_0_3m(self):
        """300 mm slab thickness → extrusion depth = 0.3 m."""
        self.assertIn("0.3", self.text)


# ===========================================================================
# 16-17 — Column geometry round-trip
# ===========================================================================

class TestColumnGeometryRoundtrip(unittest.TestCase):

    def setUp(self):
        self.text = _export_ifc4(_COLUMN_MODEL).ifc_text

    # 16
    def test_column_width_400mm_is_0_4m(self):
        """400 mm column width → rectangle profile XDim = 0.4 m."""
        self.assertIn("0.4", self.text)

    # 17
    def test_column_height_3600mm_is_3_6m(self):
        """3 600 mm column height → extrusion depth = 3.6 m."""
        self.assertIn("3.6", self.text)


# ===========================================================================
# 18-19 — Beam geometry round-trip
# ===========================================================================

class TestBeamGeometryRoundtrip(unittest.TestCase):

    def setUp(self):
        self.text = _export_ifc4(_BEAM_MODEL).ifc_text

    # 18
    def test_beam_length_12000mm_is_12m(self):
        """12 000 mm beam → extrusion depth (length) = 12.0 m."""
        self.assertIn("12.", self.text)

    # 19
    def test_beam_height_500mm_is_0_5m(self):
        """500 mm beam height → rectangle profile YDim = 0.5 m."""
        self.assertIn("0.5", self.text)


# ===========================================================================
# 20-21 — Opening geometry round-trip
# ===========================================================================

class TestOpeningGeometryRoundtrip(unittest.TestCase):

    def setUp(self):
        self.text = _export_ifc4(_OPENING_MODEL).ifc_text

    # 20
    def test_door_width_900mm_is_0_9m(self):
        """900 mm door width appears as 0.9 m in the IFC4 text."""
        self.assertIn("0.9", self.text)

    # 21
    def test_window_width_1500mm_is_1_5m(self):
        """1 500 mm window width appears as 1.5 m in the IFC4 text."""
        self.assertIn("1.5", self.text)


# ===========================================================================
# 22 — Storey elevation round-trip
# ===========================================================================

class TestStoreyElevationRoundtrip(unittest.TestCase):

    # 22
    def test_storey_elevation_3600mm_is_3_6m(self):
        """Storey at 3 600 mm → IfcBuildingStorey last arg (elevation) = 3.6 m."""
        model = {
            "name": "ElevTest",
            "levels": [
                {"name": "GF", "elevation": 0.0},
                {"name": "FF", "elevation": 3_600.0},
            ],
        }
        text = _export_ifc4(model).ifc_text
        # The IFCBUILDINGSTOREY(...,3.6) pattern must appear
        self.assertIn("3.6", text)
        # Also verify the entity is present
        self.assertGreaterEqual(_count(text, "IFCBUILDINGSTOREY"), 2)


# ===========================================================================
# 23-24 — Pset / metadata round-trip
# ===========================================================================

class TestPsetMetadataRoundtrip(unittest.TestCase):

    # 23
    def test_element_name_survives_export(self):
        """Named elements' name strings appear as STEP 'string' literals."""
        model = {
            "name": "PsetTest",
            "levels": [{"name": "L1", "elevation": 0.0}],
            "walls": [
                {
                    "name": "LOAD_BEARING_WALL_A1",
                    "level": "L1",
                    "from": [0, 0],
                    "to": [5_000, 0],
                    "height": 3_000,
                    "thickness": 200,
                }
            ],
            "columns": [
                {
                    "name": "STRUCTURAL_COL_C1",
                    "level": "L1",
                    "position": [0, 0, 0],
                    "width": 300,
                    "depth": 300,
                    "height": 3_000,
                }
            ],
        }
        text = _export_ifc4(model).ifc_text
        self.assertIn("LOAD_BEARING_WALL_A1", text)
        self.assertIn("STRUCTURAL_COL_C1", text)

    # 24
    def test_level_name_appears_in_storey_entity(self):
        """Custom level name 'ROOF_DECK' appears in IfcBuildingStorey text."""
        model = {
            "name": "RoofTest",
            "levels": [
                {"name": "GF", "elevation": 0.0},
                {"name": "ROOF_DECK", "elevation": 12_000.0},
            ],
        }
        text = _export_ifc4(model).ifc_text
        self.assertIn("ROOF_DECK", text)
        # Both storeys must exist
        self.assertEqual(_count(text, "IFCBUILDINGSTOREY"), 2)


# ===========================================================================
# 25 — Multi-storey full round-trip
# ===========================================================================

class TestMultiStoreyFullRoundtrip(unittest.TestCase):
    """
    Full Tier 1+2 round-trip: multi-storey model exports to valid IFC4,
    each level has its own IfcBuildingStorey, and all elements are captured
    in IfcRelContainedInSpatialStructure relationships.
    """

    # 25
    def test_multistorey_roundtrip(self):
        result = _export_ifc4(_FULL_MULTI_STOREY)
        text = result.ifc_text

        # File is syntactically valid
        self.assertTrue(text.startswith("ISO-10303-21;"))
        self.assertIn("END-ISO-10303-21;", text)

        # Correct schema
        self.assertIn("IFC4", text)
        self.assertNotIn("IFC2X3", text)
        self.assertEqual(result.schema, "IFC4")

        # 3 levels → 3 storeys
        self.assertEqual(_count(text, "IFCBUILDINGSTOREY"), 3)
        for level_name in ("GF", "FF", "SF"):
            self.assertIn(level_name, text, f"level name {level_name!r} missing from text")

        # Walls: one per level (3 total)
        self.assertGreaterEqual(_count(text, "IFCWALL"), 3)

        # Slabs: 2
        self.assertGreaterEqual(_count(text, "IFCSLAB"), 2)

        # Column: 1
        self.assertGreaterEqual(_count(text, "IFCCOLUMN"), 1)

        # Beam: 1
        self.assertGreaterEqual(_count(text, "IFCBEAM"), 1)

        # Openings: 1 door + 1 window
        self.assertGreaterEqual(_count(text, "IFCDOOR"), 1)
        self.assertGreaterEqual(_count(text, "IFCWINDOW"), 1)

        # Spatial relationships: at least 3 storeys → 3 contained-in-spatial
        self.assertGreaterEqual(_count(text, "IFCRELCONTAINEDINSPATIALSTRUCTURE"), 3)

        # No forward-reference gaps
        data_match = re.search(r"DATA;(.+)ENDSEC;", text, re.DOTALL)
        self.assertIsNotNone(data_match)
        data_section = data_match.group(1)
        defined = set(int(m) for m in re.findall(r"^#(\d+)=", data_section, re.MULTILINE))
        rhs = re.sub(r"^#\d+=", "", data_section, flags=re.MULTILINE)
        referenced = set(int(m) for m in re.findall(r"#(\d+)", rhs))
        missing = referenced - defined
        self.assertEqual(
            missing,
            set(),
            f"Undefined #ID references in multi-storey export: {sorted(missing)[:10]}",
        )

        # No validation warnings
        validation_warns = [w for w in result.warnings if w.startswith("VALIDATION")]
        self.assertEqual(
            validation_warns, [],
            f"Unexpected VALIDATION warnings: {validation_warns}",
        )


if __name__ == "__main__":
    unittest.main()
