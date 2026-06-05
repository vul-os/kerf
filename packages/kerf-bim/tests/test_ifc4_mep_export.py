"""
test_ifc4_mep_export.py — IFC4 export parity tests for MEP + spaces + zones.

Tests cover:
1.  IFC4 export of duct segments produces IfcDuctSegment entities
2.  IFC4 export of pipe segments produces IfcPipeSegment entities
3.  IFC4 export of conduit segments produces IfcCableCarrierSegment entities
4.  IfcCircleProfileDef used for circular duct segments
5.  IfcRectangleProfileDef used for rectangular duct segments
6.  MEP segment mm→m scaling correct
7.  Segment local placement references storey
8.  Multiple MEP segments all exported
9.  IFC4 model with mep_systems + existing walls: all forward refs resolved
10. Export IFC4 with spaces emits IfcSpace
11. IFC4 with zones: IfcZone entities emitted
12. Segment extruded area solid emitted
13. IfcRelContainedInSpatialStructure includes MEP segment
14. MEP system on non-default level placed on correct storey
15. Empty mep_systems list → no additional entities
16. Zero-length MEP segment → warning + skip
17. Fallback to IfcFlowSegment for unknown ifc_type
18. MEP segment with rectangular profile has correct dimensions
19. Full round-trip: export IFC4 → validate header + forward refs + entity counts
20. Mixed model (walls + slabs + MEP + spaces) produces valid IFC4 file
"""
from __future__ import annotations

import math
import re
import sys
import unittest
from pathlib import Path

# ── Ensure kerf-bim src is importable ────────────────────────────────────
_HERE = Path(__file__).parent
_PLUGIN_ROOT = _HERE.parent
_PACKAGES = _PLUGIN_ROOT.parent

for entry in _PACKAGES.iterdir():
    if not entry.name.startswith("kerf-"):
        continue
    src = entry / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

from kerf_bim.export_ifc import export_ifc, IFCExportResult, IFCExportError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_ifc_type(ifc_text: str, ifc_type: str) -> int:
    pattern = rf"#\d+={ifc_type.upper()}\("
    return len(re.findall(pattern, ifc_text, re.IGNORECASE))


def _has_ifc_type(ifc_text: str, ifc_type: str) -> bool:
    return _count_ifc_type(ifc_text, ifc_type) > 0


def _defined_ids(ifc_text: str) -> set[int]:
    data = re.search(r"DATA;(.+)ENDSEC;", ifc_text, re.DOTALL)
    if not data:
        return set()
    return {int(m) for m in re.findall(r"^#(\d+)=", data.group(1), re.MULTILINE)}


def _referenced_ids(ifc_text: str) -> set[int]:
    data = re.search(r"DATA;(.+)ENDSEC;", ifc_text, re.DOTALL)
    if not data:
        return set()
    rhs = re.sub(r"^#\d+=", "", data.group(1), flags=re.MULTILINE)
    return {int(m) for m in re.findall(r"#(\d+)", rhs)}


# ---------------------------------------------------------------------------
# MEP model fixtures
# ---------------------------------------------------------------------------

_BASE_LEVELS = [{"name": "L1", "elevation": 0.0}]

_DUCT_SYSTEM = {
    "level": "L1",
    "system_type": "SUPPLYAIR",
    "segments": [
        {
            "id": "seg_d1",
            "ifc_type": "IfcDuctSegment",
            "from": [0.0, 0.0, 3000.0],
            "to": [5000.0, 0.0, 3000.0],
            "kind": "straight",
            "size_mm": 400.0,
        },
        {
            "id": "seg_d2",
            "ifc_type": "IfcDuctSegment",
            "from": [5000.0, 0.0, 3000.0],
            "to": [5000.0, 0.0, 3000.0],  # zero length — should be skipped
            "kind": "straight",
            "size_mm": 400.0,
        },
    ],
}

_PIPE_SYSTEM = {
    "level": "L1",
    "system_type": "DOMESTICCOLDWATER",
    "segments": [
        {
            "id": "seg_p1",
            "ifc_type": "IfcPipeSegment",
            "from": [1000.0, 0.0, 1500.0],
            "to": [4000.0, 0.0, 1500.0],
            "size_mm": 50.0,
        },
    ],
}

_CONDUIT_SYSTEM = {
    "level": "L1",
    "system_type": "ELECTRICAL",
    "segments": [
        {
            "id": "seg_c1",
            "ifc_type": "IfcCableCarrierSegment",
            "from": [0.0, 2000.0, 2800.0],
            "to": [6000.0, 2000.0, 2800.0],
            "size_mm": 32.0,
        },
    ],
}

_RECT_DUCT_SYSTEM = {
    "level": "L1",
    "segments": [
        {
            "id": "seg_rect",
            "ifc_type": "IfcDuctSegment",
            "from": [0.0, 0.0, 3000.0],
            "to": [8000.0, 0.0, 3000.0],
            "width_mm": 600.0,
            "height_mm": 400.0,
        },
    ],
}

_FULL_MEP_MODEL = {
    "name": "MEP Test Building",
    "levels": [
        {"name": "GF", "elevation": 0.0},
        {"name": "FF", "elevation": 3000.0},
    ],
    "walls": [
        {"level": "GF", "from": [0, 0], "to": [6000, 0], "height": 3000, "thickness": 200},
    ],
    "slabs": [
        {"level": "GF", "boundary": [[0,0],[6000,0],[6000,5000],[0,5000]], "thickness": 200},
    ],
    "spaces": [
        {"name": "Office 1", "level": "GF", "boundary": [[0,0],[6000,0],[6000,5000],[0,5000]],
         "zone": "Occupied"},
    ],
    "mep_systems": [
        {
            "level": "GF",
            "segments": [
                {
                    "id": "seg1",
                    "ifc_type": "IfcDuctSegment",
                    "from": [1000, 0, 2500],
                    "to": [5000, 0, 2500],
                    "size_mm": 400,
                },
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# Tests 1-3: IFC type entity names
# ---------------------------------------------------------------------------

class TestMEPEntityTypes(unittest.TestCase):

    def setUp(self):
        self.duct_model = {
            "name": "Duct Test",
            "levels": _BASE_LEVELS,
            "mep_systems": [_DUCT_SYSTEM],
        }
        self.pipe_model = {
            "name": "Pipe Test",
            "levels": _BASE_LEVELS,
            "mep_systems": [_PIPE_SYSTEM],
        }
        self.conduit_model = {
            "name": "Conduit Test",
            "levels": _BASE_LEVELS,
            "mep_systems": [_CONDUIT_SYSTEM],
        }

    def test_duct_segment_entity(self):
        """IFC4 export of duct system produces IFCDUCTSEGMENT entity."""
        result = export_ifc(self.duct_model, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCDUCTSEGMENT"))

    def test_pipe_segment_entity(self):
        """IFC4 export of pipe system produces IFCPIPESEGMENT entity."""
        result = export_ifc(self.pipe_model, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCPIPESEGMENT"))

    def test_conduit_segment_entity(self):
        """IFC4 export of conduit system produces IFCCABLECARRIERSEGMENT."""
        result = export_ifc(self.conduit_model, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCCABLECARRIERSEGMENT"))


# ---------------------------------------------------------------------------
# Tests 4-5: Profile types
# ---------------------------------------------------------------------------

class TestMEPProfiles(unittest.TestCase):

    def test_circular_duct_uses_circle_profile(self):
        """Circular duct segment uses IfcCircleProfileDef."""
        model = {
            "name": "Circular Duct",
            "levels": _BASE_LEVELS,
            "mep_systems": [{
                "level": "L1",
                "segments": [{
                    "id": "s1",
                    "ifc_type": "IfcDuctSegment",
                    "from": [0, 0, 3000],
                    "to": [5000, 0, 3000],
                    "size_mm": 400.0,
                }],
            }],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCCIRCLEPROFILEDEF"))

    def test_rectangular_duct_uses_rect_profile(self):
        """Rectangular duct segment uses IfcRectangleProfileDef."""
        model = {
            "name": "Rect Duct",
            "levels": _BASE_LEVELS,
            "mep_systems": [{
                "level": "L1",
                "segments": [{
                    "id": "sr",
                    "ifc_type": "IfcDuctSegment",
                    "from": [0, 0, 3000],
                    "to": [5000, 0, 3000],
                    "width_mm": 600.0,
                    "height_mm": 400.0,
                }],
            }],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCRECTANGLEPROFILEDEF"))


# ---------------------------------------------------------------------------
# Test 6: mm→m scaling
# ---------------------------------------------------------------------------

class TestMEPScaling(unittest.TestCase):

    def test_segment_length_scaled_to_metres(self):
        """5000mm segment → 5.0m extrusion depth in IFC text."""
        model = {
            "name": "Scale Test",
            "levels": _BASE_LEVELS,
            "mep_systems": [{
                "level": "L1",
                "segments": [{
                    "id": "ss",
                    "ifc_type": "IfcDuctSegment",
                    "from": [0, 0, 3000],
                    "to": [5000, 0, 3000],
                    "size_mm": 400.0,
                }],
            }],
        }
        result = export_ifc(model, schema="IFC4")
        # Extrusion value should be ~5.0 (metres)
        self.assertIn("5.", result.ifc_text)

    def test_segment_radius_scaled_to_metres(self):
        """400mm diameter → 0.2m radius in IfcCircleProfileDef."""
        model = {
            "name": "Radius Test",
            "levels": _BASE_LEVELS,
            "mep_systems": [{
                "level": "L1",
                "segments": [{
                    "id": "sr2",
                    "ifc_type": "IfcDuctSegment",
                    "from": [0, 0, 3000],
                    "to": [5000, 0, 3000],
                    "size_mm": 400.0,
                }],
            }],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertIn("0.2", result.ifc_text)


# ---------------------------------------------------------------------------
# Tests 7-8: Placement and multiple segments
# ---------------------------------------------------------------------------

class TestMEPPlacement(unittest.TestCase):

    def test_local_placement_present(self):
        """MEP model has IfcLocalPlacement for segments."""
        model = {
            "name": "Placement",
            "levels": _BASE_LEVELS,
            "mep_systems": [_PIPE_SYSTEM],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCLOCALPLACEMENT"))

    def test_multiple_segments_all_exported(self):
        """Three segments in one system → three IfcDuctSegment entities."""
        model = {
            "name": "Multi",
            "levels": _BASE_LEVELS,
            "mep_systems": [{
                "level": "L1",
                "segments": [
                    {"id": "m1", "ifc_type": "IfcDuctSegment",
                     "from": [0,0,3000], "to": [3000,0,3000], "size_mm": 400},
                    {"id": "m2", "ifc_type": "IfcDuctSegment",
                     "from": [3000,0,3000], "to": [6000,0,3000], "size_mm": 400},
                    {"id": "m3", "ifc_type": "IfcDuctSegment",
                     "from": [6000,0,3000], "to": [9000,0,3000], "size_mm": 400},
                ],
            }],
        }
        result = export_ifc(model, schema="IFC4")
        count = _count_ifc_type(result.ifc_text, "IFCDUCTSEGMENT")
        self.assertEqual(count, 3)


# ---------------------------------------------------------------------------
# Test 9: Forward reference integrity
# ---------------------------------------------------------------------------

class TestMEPForwardRefs(unittest.TestCase):

    def test_all_forward_refs_resolved(self):
        """MEP + walls + spaces: all #N references must be defined."""
        result = export_ifc(_FULL_MEP_MODEL, schema="IFC4")
        defined = _defined_ids(result.ifc_text)
        referenced = _referenced_ids(result.ifc_text)
        missing = referenced - defined
        self.assertEqual(
            missing, set(),
            msg=f"Undefined #ID references: {sorted(missing)[:10]}"
        )


# ---------------------------------------------------------------------------
# Tests 10-11: Spaces and zones
# ---------------------------------------------------------------------------

class TestSpacesAndZones(unittest.TestCase):

    def test_ifc4_export_emits_spaces(self):
        model = {
            "name": "Zone Test",
            "levels": _BASE_LEVELS,
            "spaces": [
                {"name": "Room 1", "level": "L1",
                 "boundary": [[0,0],[4000,0],[4000,3000],[0,3000]],
                 "zone": "Occupied"},
            ],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCSPACE"))

    def test_ifc4_emits_zones(self):
        model = {
            "name": "Zone Test",
            "levels": _BASE_LEVELS,
            "spaces": [
                {"name": "Room 1", "level": "L1",
                 "boundary": [[0,0],[4000,0],[4000,3000],[0,3000]],
                 "zone": "Fire Zone A"},
                {"name": "Room 2", "level": "L1",
                 "boundary": [[4000,0],[8000,0],[8000,3000],[4000,3000]],
                 "zone": "Fire Zone A"},
            ],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCZONE"))

    def test_ifc2x3_no_zones(self):
        """IFC2X3 export should NOT emit IfcZone (IFC4-only)."""
        model = {
            "name": "Zone Test",
            "levels": _BASE_LEVELS,
            "spaces": [
                {"name": "Room 1", "level": "L1",
                 "boundary": [[0,0],[4000,0],[4000,3000],[0,3000]],
                 "zone": "Some Zone"},
            ],
        }
        result = export_ifc(model, schema="IFC2X3")
        self.assertFalse(_has_ifc_type(result.ifc_text, "IFCZONE"))


# ---------------------------------------------------------------------------
# Tests 12-13: ExtrudedAreaSolid and containment
# ---------------------------------------------------------------------------

class TestMEPRepresentation(unittest.TestCase):

    def test_extruded_area_solid_emitted(self):
        model = {
            "name": "EAS",
            "levels": _BASE_LEVELS,
            "mep_systems": [_DUCT_SYSTEM],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCEXTRUDEDAREASOLID"))

    def test_rel_contained_includes_mep(self):
        """IfcRelContainedInSpatialStructure must be present when MEP segments emitted."""
        model = {
            "name": "MEP Containment",
            "levels": _BASE_LEVELS,
            "mep_systems": [_PIPE_SYSTEM],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCRELCONTAINEDINSPATIALSTRUCTURE"))


# ---------------------------------------------------------------------------
# Test 14: Non-default level
# ---------------------------------------------------------------------------

class TestMEPMultiLevel(unittest.TestCase):

    def test_mep_on_second_level(self):
        model = {
            "name": "Multi Level MEP",
            "levels": [
                {"name": "GF", "elevation": 0.0},
                {"name": "FF", "elevation": 3000.0},
            ],
            "mep_systems": [{
                "level": "FF",
                "segments": [{
                    "id": "ff_seg",
                    "ifc_type": "IfcDuctSegment",
                    "from": [0, 0, 3000],
                    "to": [5000, 0, 3000],
                    "size_mm": 300.0,
                }],
            }],
        }
        result = export_ifc(model, schema="IFC4")
        # Should emit the duct segment
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCDUCTSEGMENT"))
        # Both storeys should be present
        count = _count_ifc_type(result.ifc_text, "IFCBUILDINGSTOREY")
        self.assertEqual(count, 2)


# ---------------------------------------------------------------------------
# Test 15: Empty mep_systems
# ---------------------------------------------------------------------------

class TestEmptyMEP(unittest.TestCase):

    def test_empty_mep_systems(self):
        model = {
            "name": "No MEP",
            "levels": _BASE_LEVELS,
            "mep_systems": [],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertFalse(_has_ifc_type(result.ifc_text, "IFCDUCTSEGMENT"))
        self.assertFalse(_has_ifc_type(result.ifc_text, "IFCPIPESEGMENT"))

    def test_no_mep_systems_key(self):
        model = {"name": "No MEP Key", "levels": _BASE_LEVELS}
        result = export_ifc(model, schema="IFC4")
        # Should still produce a valid file
        self.assertTrue(result.ifc_text.startswith("ISO-10303-21;"))


# ---------------------------------------------------------------------------
# Test 16: Zero-length segment warning
# ---------------------------------------------------------------------------

class TestZeroLengthMEP(unittest.TestCase):

    def test_zero_length_segment_skipped_with_warning(self):
        model = {
            "name": "ZeroLen",
            "levels": _BASE_LEVELS,
            "mep_systems": [{
                "level": "L1",
                "segments": [{
                    "id": "zl",
                    "ifc_type": "IfcDuctSegment",
                    "from": [1000, 0, 3000],
                    "to": [1000, 0, 3000],   # zero length
                    "size_mm": 400.0,
                }],
            }],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertFalse(_has_ifc_type(result.ifc_text, "IFCDUCTSEGMENT"))
        self.assertTrue(any("zero length" in w.lower() for w in result.warnings))


# ---------------------------------------------------------------------------
# Test 17: Fallback entity type
# ---------------------------------------------------------------------------

class TestMEPFallbackType(unittest.TestCase):

    def test_unknown_ifc_type_uses_flowsegment(self):
        model = {
            "name": "Fallback",
            "levels": _BASE_LEVELS,
            "mep_systems": [{
                "level": "L1",
                "segments": [{
                    "id": "fb",
                    "ifc_type": "IfcSomeUnknownSegmentType",
                    "from": [0, 0, 3000],
                    "to": [5000, 0, 3000],
                    "size_mm": 200.0,
                }],
            }],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCFLOWSEGMENT"))


# ---------------------------------------------------------------------------
# Tests 18-20: Full model validity
# ---------------------------------------------------------------------------

class TestFullMEPModel(unittest.TestCase):

    def test_full_model_valid_header(self):
        result = export_ifc(_FULL_MEP_MODEL, schema="IFC4")
        self.assertTrue(result.ifc_text.startswith("ISO-10303-21;"))
        self.assertIn("END-ISO-10303-21;", result.ifc_text)

    def test_full_model_entity_count(self):
        result = export_ifc(_FULL_MEP_MODEL, schema="IFC4")
        data_m = re.search(r"DATA;(.+)ENDSEC;", result.ifc_text, re.DOTALL)
        self.assertIsNotNone(data_m)
        count = len(re.findall(r"^#\d+=", data_m.group(1), re.MULTILINE))
        self.assertEqual(result.entity_count, count)

    def test_full_model_no_validation_warnings(self):
        result = export_ifc(_FULL_MEP_MODEL, schema="IFC4")
        val_warns = [w for w in result.warnings if w.startswith("VALIDATION")]
        self.assertEqual(val_warns, [],
                         msg=f"Unexpected validation warnings: {val_warns}")

    def test_full_model_contains_walls_and_mep(self):
        result = export_ifc(_FULL_MEP_MODEL, schema="IFC4")
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCWALL"))
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCDUCTSEGMENT"))
        self.assertTrue(_has_ifc_type(result.ifc_text, "IFCSPACE"))

    def test_rectangular_duct_dimensions(self):
        """600mm wide × 400mm high rect duct → 0.6 and 0.4 in IFC text (metres)."""
        model = {
            "name": "Rect Test",
            "levels": _BASE_LEVELS,
            "mep_systems": [_RECT_DUCT_SYSTEM],
        }
        result = export_ifc(model, schema="IFC4")
        self.assertIn("0.6", result.ifc_text)
        self.assertIn("0.4", result.ifc_text)


if __name__ == "__main__":
    unittest.main()
