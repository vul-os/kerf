"""
Contract tests for kerf-interior IFC 4 export.

All tests are hermetic — no DB, no network, no async.

Oracles
-------
- IFC 4 SPF files must start with ISO-10303-21; and end with END-ISO-10303-21;
- FILE_SCHEMA must declare IFC4
- Spatial hierarchy: IfcProject → IfcSite → IfcBuilding → IfcBuildingStorey
- A 4-wall room with 1 door + 2 windows must produce
  exactly 4 IFCWALL*/IFCWALLSTANDARDCASE + 1 IFCDOOR + 2 IFCWINDOW
- Furniture (desk + chair) must produce 2 IFCFURNITURE entries
- validate_ifc4_subset must return valid=True on a well-formed export
"""
from __future__ import annotations

import os
import re
import tempfile

import pytest

from kerf_interior.furniture import make_chair, make_desk
from kerf_interior.ifc_export import (
    InteriorDoor,
    InteriorLight,
    InteriorModel,
    InteriorWindow,
    ValidationResult,
    export_ifc4,
    list_supported_entity_types,
    validate_ifc4_subset,
)
from kerf_interior.space_planning import make_room


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity_count(text: str, entity_type: str) -> int:
    """Count occurrences of an IFC entity type in the DATA section."""
    pattern = re.compile(
        r"^#\d+=" + re.escape(entity_type.upper()) + r"\(",
        re.MULTILINE,
    )
    return len(pattern.findall(text))


def _export_to_temp(model: InteriorModel) -> str:
    """Write model to a temp file; return (path, ifc_text)."""
    fd, path = tempfile.mkstemp(suffix=".ifc")
    os.close(fd)
    export_ifc4(model, path)
    return path


# ---------------------------------------------------------------------------
# list_supported_entity_types
# ---------------------------------------------------------------------------

class TestListSupportedEntityTypes:
    def test_returns_list_of_strings(self):
        types = list_supported_entity_types()
        assert isinstance(types, list)
        assert all(isinstance(t, str) for t in types)

    def test_includes_required_types(self):
        types = list_supported_entity_types()
        for expected in [
            "IfcWall", "IfcWallStandardCase", "IfcSlab",
            "IfcDoor", "IfcWindow", "IfcFurniture",
            "IfcLightFixture", "IfcProject",
        ]:
            assert expected in types, f"Missing entity type: {expected}"


# ---------------------------------------------------------------------------
# Test 1: Simple room export (4 walls + 1 door + 2 windows)
# ---------------------------------------------------------------------------

class TestSimpleRoomExport:
    """Oracle: 4 IfcWall* + 1 IfcDoor + 2 IfcWindow; validate returns valid=True."""

    @pytest.fixture
    def ifc_path(self, tmp_path):
        room = make_room("Living Room", 5000.0, 4000.0, ceiling_height_mm=2700.0)
        door = InteriorDoor("Front Door", x_mm=500.0, y_mm=0.0,
                            width_mm=900.0, height_mm=2100.0)
        win1 = InteriorWindow("Window 1", x_mm=1500.0, y_mm=0.0,
                              width_mm=1200.0, height_mm=1200.0, sill_height_mm=900.0)
        win2 = InteriorWindow("Window 2", x_mm=3000.0, y_mm=0.0,
                              width_mm=1200.0, height_mm=1200.0, sill_height_mm=900.0)
        model = InteriorModel.from_room_layout(
            room,
            doors=[door],
            windows=[win1, win2],
        )
        path = str(tmp_path / "room.ifc")
        export_ifc4(model, path)
        return path

    def test_file_exists(self, ifc_path):
        assert os.path.isfile(ifc_path)
        assert os.path.getsize(ifc_path) > 0

    def test_file_starts_iso(self, ifc_path):
        with open(ifc_path) as fh:
            first_line = fh.readline().strip()
        assert first_line == "ISO-10303-21;"

    def test_file_ends_iso(self, ifc_path):
        with open(ifc_path) as fh:
            text = fh.read()
        assert text.rstrip().endswith("END-ISO-10303-21;")

    def test_schema_is_ifc4(self, ifc_path):
        with open(ifc_path) as fh:
            text = fh.read()
        assert "FILE_SCHEMA(('IFC4'))" in text

    def test_four_walls(self, ifc_path):
        with open(ifc_path) as fh:
            text = fh.read()
        wall_count = (
            _entity_count(text, "IFCWALL")
            + _entity_count(text, "IFCWALLSTANDARDCASE")
        )
        assert wall_count == 4, f"Expected 4 walls, got {wall_count}"

    def test_one_door(self, ifc_path):
        with open(ifc_path) as fh:
            text = fh.read()
        assert _entity_count(text, "IFCDOOR") == 1

    def test_two_windows(self, ifc_path):
        with open(ifc_path) as fh:
            text = fh.read()
        assert _entity_count(text, "IFCWINDOW") == 2

    def test_validate_returns_valid(self, ifc_path):
        result = validate_ifc4_subset(ifc_path)
        assert isinstance(result, ValidationResult)
        assert result.valid is True, f"Validation errors: {result.errors}"

    def test_validate_entity_counts_match_door_window(self, ifc_path):
        result = validate_ifc4_subset(ifc_path)
        tc = result.entity_type_counts
        door_count = tc.get("IFCDOOR", 0)
        win_count  = tc.get("IFCWINDOW", 0)
        assert door_count == 1, f"Expected 1 IFCDOOR, got {door_count}"
        assert win_count  == 2, f"Expected 2 IFCWINDOW, got {win_count}"


# ---------------------------------------------------------------------------
# Test 2: Hierarchy check
# ---------------------------------------------------------------------------

class TestHierarchy:
    """Oracle: IfcProject→IfcSite→IfcBuilding→IfcBuildingStorey present."""

    @pytest.fixture
    def ifc_text(self, tmp_path):
        room = make_room("Hierarchy Test Room", 4000.0, 3000.0)
        model = InteriorModel.from_room_layout(room)
        path = str(tmp_path / "hier.ifc")
        export_ifc4(model, path)
        with open(path) as fh:
            return fh.read()

    def test_has_ifcproject(self, ifc_text):
        assert _entity_count(ifc_text, "IFCPROJECT") == 1

    def test_has_ifcsite(self, ifc_text):
        assert _entity_count(ifc_text, "IFCSITE") >= 1

    def test_has_ifcbuilding(self, ifc_text):
        assert _entity_count(ifc_text, "IFCBUILDING") >= 1

    def test_has_ifcbuildingstorey(self, ifc_text):
        assert _entity_count(ifc_text, "IFCBUILDINGSTOREY") >= 1

    def test_has_rel_aggregates_for_hierarchy(self, ifc_text):
        # Must have at least 3 IFCRELAGGREGATES:
        # project→site, site→building, building→storey
        agg_count = _entity_count(ifc_text, "IFCRELAGGREGATES")
        assert agg_count >= 3, f"Expected >= 3 IFCRELAGGREGATES, got {agg_count}"

    def test_has_rel_contained(self, ifc_text):
        assert _entity_count(ifc_text, "IFCRELCONTAINEDINSPATIALSTRUCTURE") >= 1

    def test_has_floor_slab(self, ifc_text):
        assert _entity_count(ifc_text, "IFCSLAB") >= 1

    def test_hierarchy_valid(self, tmp_path, ifc_text):
        path = str(tmp_path / "hier.ifc")
        result = validate_ifc4_subset(path)
        assert result.valid is True, f"Hierarchy validation failed: {result.errors}"


# ---------------------------------------------------------------------------
# Test 3: Furniture export (desk + chair)
# ---------------------------------------------------------------------------

class TestFurnitureExport:
    """Oracle: desk + chair → 2 IfcFurniture entries; validate returns valid=True."""

    @pytest.fixture
    def ifc_data(self, tmp_path):
        room = make_room("Office", 6000.0, 5000.0)
        desk = make_desk(name="Work Desk")
        chair = make_chair(name="Task Chair")
        room.place(desk, 500.0, 500.0)
        room.place(chair, 2200.0, 500.0)
        model = InteriorModel.from_room_layout(room)
        path = str(tmp_path / "furniture.ifc")
        export_ifc4(model, path)
        with open(path) as fh:
            text = fh.read()
        return path, text

    def test_two_furniture_entities(self, ifc_data):
        _, text = ifc_data
        furn_count = _entity_count(text, "IFCFURNITURE")
        assert furn_count == 2, f"Expected 2 IFCFURNITURE, got {furn_count}"

    def test_furniture_names_in_file(self, ifc_data):
        _, text = ifc_data
        assert "Work Desk" in text
        assert "Task Chair" in text

    def test_validate_valid(self, ifc_data):
        path, _ = ifc_data
        result = validate_ifc4_subset(path)
        assert result.valid is True, f"Furniture validation errors: {result.errors}"

    def test_furniture_count_in_validation_result(self, ifc_data):
        path, _ = ifc_data
        result = validate_ifc4_subset(path)
        furn = result.entity_type_counts.get("IFCFURNITURE", 0)
        assert furn == 2, f"Validation sees {furn} IFCFURNITURE, expected 2"


# ---------------------------------------------------------------------------
# Test 4: Round-trip — export then re-parse, IDs + counts match
# ---------------------------------------------------------------------------

class TestRoundTrip:
    """Oracle: export → re-validate; entity type counts stable."""

    @pytest.fixture
    def export_result(self, tmp_path):
        room = make_room("Round-trip Room", 7000.0, 5000.0)
        door = InteriorDoor("Main Door", 1000.0, 0.0)
        win  = InteriorWindow("Side Window", 3000.0, 0.0)
        desk = make_desk()
        room.place(desk, 600.0, 600.0)
        model = InteriorModel.from_room_layout(room, doors=[door], windows=[win])
        path = str(tmp_path / "roundtrip.ifc")
        export_ifc4(model, path)
        return path

    def test_roundtrip_parse_counts_walls(self, export_result):
        result = validate_ifc4_subset(export_result)
        wall_count = (
            result.entity_type_counts.get("IFCWALL", 0)
            + result.entity_type_counts.get("IFCWALLSTANDARDCASE", 0)
        )
        assert wall_count == 4

    def test_roundtrip_parse_counts_door(self, export_result):
        result = validate_ifc4_subset(export_result)
        assert result.entity_type_counts.get("IFCDOOR", 0) == 1

    def test_roundtrip_parse_counts_window(self, export_result):
        result = validate_ifc4_subset(export_result)
        assert result.entity_type_counts.get("IFCWINDOW", 0) == 1

    def test_roundtrip_parse_counts_furniture(self, export_result):
        result = validate_ifc4_subset(export_result)
        assert result.entity_type_counts.get("IFCFURNITURE", 0) == 1

    def test_roundtrip_valid(self, export_result):
        result = validate_ifc4_subset(export_result)
        assert result.valid is True, f"Round-trip errors: {result.errors}"

    def test_roundtrip_entity_count_positive(self, export_result):
        result = validate_ifc4_subset(export_result)
        assert result.entity_count > 20

    def test_roundtrip_no_unresolved_refs(self, export_result):
        result = validate_ifc4_subset(export_result)
        # No unresolved-reference errors
        ref_errors = [e for e in result.errors if "Unresolved" in e]
        assert ref_errors == [], f"Unresolved references: {ref_errors}"

    def test_schema_recorded_as_ifc4(self, export_result):
        result = validate_ifc4_subset(export_result)
        assert result.schema == "IFC4"


# ---------------------------------------------------------------------------
# Test 5: Light fixtures
# ---------------------------------------------------------------------------

class TestLightFixtures:
    def test_light_fixture_entity_present(self, tmp_path):
        room = make_room("Lit Room", 4000.0, 3000.0)
        light = InteriorLight("Ceiling Light", x_mm=2000.0, y_mm=1500.0, z_mm=2600.0)
        model = InteriorModel.from_room_layout(room, lights=[light])
        path = str(tmp_path / "lights.ifc")
        export_ifc4(model, path)
        with open(path) as fh:
            text = fh.read()
        assert _entity_count(text, "IFCLIGHTFIXTURE") == 1

    def test_light_fixture_name_in_file(self, tmp_path):
        room = make_room("Lit Room", 4000.0, 3000.0)
        light = InteriorLight("Pendant Light", x_mm=2000.0, y_mm=1500.0)
        model = InteriorModel.from_room_layout(room, lights=[light])
        path = str(tmp_path / "lights2.ifc")
        export_ifc4(model, path)
        with open(path) as fh:
            text = fh.read()
        assert "Pendant Light" in text


# ---------------------------------------------------------------------------
# Test 6: Validate error cases
# ---------------------------------------------------------------------------

class TestValidateErrors:
    def test_missing_file_returns_invalid(self, tmp_path):
        result = validate_ifc4_subset(str(tmp_path / "nonexistent.ifc"))
        assert result.valid is False
        assert any("Cannot read" in e for e in result.errors)

    def test_empty_file_returns_invalid(self, tmp_path):
        path = str(tmp_path / "empty.ifc")
        with open(path, "w") as fh:
            fh.write("")
        result = validate_ifc4_subset(path)
        assert result.valid is False

    def test_wrong_schema_returns_invalid(self, tmp_path):
        path = str(tmp_path / "bad_schema.ifc")
        with open(path, "w") as fh:
            fh.write(
                "ISO-10303-21;\nHEADER;\n"
                "FILE_SCHEMA(('IFC2X3'));\n"
                "ENDSEC;\nDATA;\n"
                "#1=IFCPROJECT('x',#2,'P',$,$,$,$,(#3),#4);\n"
                "ENDSEC;\nEND-ISO-10303-21;\n"
            )
        result = validate_ifc4_subset(path)
        assert result.valid is False
        assert any("IFC4" in e for e in result.errors)
