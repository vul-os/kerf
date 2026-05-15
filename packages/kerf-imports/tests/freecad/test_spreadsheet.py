"""
test_spreadsheet.py — Spreadsheet → .equations translator tests.

Exercises translate_spreadsheet() with:
  - named alias cells (aliased B1, B2, B3 with value + formula)
  - literal values with unit suffixes
  - formula cells (content starts with ``=``)
  - cells without alias (should appear in raw_cells but NOT in params)
  - duplicate alias detection
  - name sanitisation (non-identifier chars in alias)
"""
from __future__ import annotations

import pytest

from kerf_imports.freecad.types import FCStdObject
from kerf_imports.freecad.spreadsheet import translate_spreadsheet, _parse_cell_content, _sanitise_name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sheet(cells: list[dict], name: str = "Spreadsheet", label: str = "Spreadsheet") -> FCStdObject:
    """Build a minimal FCStdObject representing a Spreadsheet::Sheet."""
    return FCStdObject(
        name=name,
        type="Spreadsheet::Sheet",
        label=label,
        properties={"_cell_list": cells},
    )


def _cell(address: str, content: str, alias: str = "") -> dict:
    c: dict = {"address": address, "content": content}
    if alias:
        c["alias"] = alias
    return c


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------

class TestTranslateSpreadsheetBasic:
    def test_returns_dict_with_required_keys(self):
        obj = _make_sheet([])
        result = translate_spreadsheet(obj)
        assert isinstance(result, dict)
        assert "version" in result
        assert "params" in result
        assert "raw_cells" in result
        assert "freecad_ref" in result
        assert "warnings" in result

    def test_version_is_1(self):
        obj = _make_sheet([])
        result = translate_spreadsheet(obj)
        assert result["version"] == 1

    def test_empty_sheet(self):
        obj = _make_sheet([])
        result = translate_spreadsheet(obj)
        assert result["params"] == []
        assert result["raw_cells"] == {}
        assert result["warnings"] == []

    def test_freecad_ref_populated(self):
        obj = _make_sheet([], name="Sheet001", label="Parameters")
        result = translate_spreadsheet(obj)
        assert result["freecad_ref"]["name"] == "Sheet001"
        assert result["freecad_ref"]["label"] == "Parameters"
        assert result["freecad_ref"]["type"] == "Spreadsheet::Sheet"


# ---------------------------------------------------------------------------
# Aliased cell → param extraction
# ---------------------------------------------------------------------------

class TestAliasedCells:
    def test_single_aliased_cell_numeric(self):
        obj = _make_sheet([_cell("B1", "2 mm", alias="wall_thickness")])
        result = translate_spreadsheet(obj)
        params = result["params"]
        assert len(params) == 1
        assert params[0]["name"] == "wall_thickness"
        assert params[0]["expr"] == "2"
        assert params[0]["unit"] == "mm"

    def test_formula_cell_strips_leading_equals(self):
        cells = [
            _cell("B1", "2 mm", alias="wall_thickness"),
            _cell("B2", "=wall_thickness / 4", alias="hole_radius"),
        ]
        obj = _make_sheet(cells)
        params = translate_spreadsheet(obj)["params"]
        assert len(params) == 2
        assert params[1]["name"] == "hole_radius"
        assert params[1]["expr"] == "wall_thickness / 4"
        assert "unit" not in params[1]

    def test_unitless_numeric_cell(self):
        obj = _make_sheet([_cell("B1", "45", alias="angle_deg")])
        params = translate_spreadsheet(obj)["params"]
        assert params[0]["expr"] == "45"
        assert "unit" not in params[0]

    def test_cell_order_preserved(self):
        cells = [
            _cell("B1", "10 mm", alias="width"),
            _cell("B2", "20 mm", alias="height"),
            _cell("B3", "5 mm",  alias="depth"),
        ]
        obj = _make_sheet(cells)
        names = [p["name"] for p in translate_spreadsheet(obj)["params"]]
        assert names == ["width", "height", "depth"]


# ---------------------------------------------------------------------------
# Unaliased cells — raw_cells only, not params
# ---------------------------------------------------------------------------

class TestUnaliasedCells:
    def test_unaliased_cell_not_in_params(self):
        obj = _make_sheet([_cell("A1", "header label")])
        result = translate_spreadsheet(obj)
        assert result["params"] == []

    def test_unaliased_cell_in_raw_cells(self):
        obj = _make_sheet([_cell("A1", "some text")])
        result = translate_spreadsheet(obj)
        assert "A1" in result["raw_cells"]
        assert result["raw_cells"]["A1"]["content"] == "some text"

    def test_aliased_cell_also_in_raw_cells(self):
        obj = _make_sheet([_cell("B1", "5 mm", alias="thickness")])
        result = translate_spreadsheet(obj)
        assert "B1" in result["raw_cells"]
        assert result["raw_cells"]["B1"]["alias"] == "thickness"

    def test_mixed_aliased_and_plain(self):
        cells = [
            _cell("A1", "Wall thickness"),
            _cell("B1", "3 mm", alias="wt"),
            _cell("A2", "Height"),
            _cell("B2", "100 mm", alias="h"),
        ]
        obj = _make_sheet(cells)
        result = translate_spreadsheet(obj)
        assert len(result["params"]) == 2
        assert len(result["raw_cells"]) == 4


# ---------------------------------------------------------------------------
# Duplicate alias handling
# ---------------------------------------------------------------------------

class TestDuplicateAlias:
    def test_duplicate_alias_warns_and_skips_second(self):
        cells = [
            _cell("B1", "2 mm", alias="wall"),
            _cell("C1", "3 mm", alias="wall"),
        ]
        obj = _make_sheet(cells)
        result = translate_spreadsheet(obj)
        assert len(result["params"]) == 1
        assert result["params"][0]["expr"] == "2"
        assert any("duplicate" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# Name sanitisation
# ---------------------------------------------------------------------------

class TestNameSanitisation:
    def test_alias_with_spaces_sanitised(self):
        obj = _make_sheet([_cell("B1", "5 mm", alias="wall thickness")])
        result = translate_spreadsheet(obj)
        assert result["params"][0]["name"] == "wall_thickness"
        assert any("sanitised" in w or "sanitized" in w for w in result["warnings"])

    def test_alias_starting_with_digit_prefixed(self):
        result_name = _sanitise_name("1wall")
        assert not result_name[0].isdigit()

    def test_alias_with_hyphens(self):
        result_name = _sanitise_name("wall-thickness")
        assert "-" not in result_name

    def test_valid_identifier_unchanged(self):
        assert _sanitise_name("wall_thickness") == "wall_thickness"
        assert _sanitise_name("WallThickness") == "WallThickness"
        assert _sanitise_name("x1") == "x1"


# ---------------------------------------------------------------------------
# Cell content parsing
# ---------------------------------------------------------------------------

class TestParseCellContent:
    def test_mm_unit(self):
        expr, unit = _parse_cell_content("2 mm")
        assert expr == "2"
        assert unit == "mm"

    def test_deg_unit(self):
        expr, unit = _parse_cell_content("45 deg")
        assert expr == "45"
        assert unit == "deg"

    def test_formula_strips_equals(self):
        expr, unit = _parse_cell_content("=width * 2")
        assert expr == "width * 2"
        assert unit == ""

    def test_unitless_integer(self):
        expr, unit = _parse_cell_content("10")
        assert expr == "10"
        assert unit == ""

    def test_unitless_float(self):
        expr, unit = _parse_cell_content("3.14")
        assert expr == "3.14"
        assert unit == ""

    def test_empty_content(self):
        expr, unit = _parse_cell_content("")
        assert expr == "0"
        assert unit == ""

    def test_leading_whitespace_stripped(self):
        expr, unit = _parse_cell_content("  5 mm  ")
        assert expr == "5"
        assert unit == "mm"


# ---------------------------------------------------------------------------
# Integration with fixture file
# ---------------------------------------------------------------------------

class TestSpreadsheetFixture:
    """Round-trip test using the spreadsheet_basic.FCStd fixture."""

    @pytest.fixture
    def fixture_path(self):
        import pathlib
        here = pathlib.Path(__file__).parent
        path = here / "fixtures" / "spreadsheet_basic.FCStd"
        if not path.exists():
            pytest.skip("spreadsheet_basic.FCStd fixture not found")
        return path

    def test_fixture_parses(self, fixture_path):
        from kerf_imports.freecad.parser import parse_fcstd
        doc = parse_fcstd(fixture_path.read_bytes())
        sheets = doc.objects_by_type("Spreadsheet::Sheet")
        assert len(sheets) == 1

    def test_fixture_translate_returns_params(self, fixture_path):
        from kerf_imports.freecad.parser import parse_fcstd
        doc = parse_fcstd(fixture_path.read_bytes())
        sheets = doc.objects_by_type("Spreadsheet::Sheet")
        result = translate_spreadsheet(sheets[0])
        # The fixture has 4 aliased cells
        assert len(result["params"]) == 4
        param_names = {p["name"] for p in result["params"]}
        assert "wall_thickness" in param_names
        assert "hole_radius" in param_names
        assert "height" in param_names
        assert "angle_deg" in param_names

    def test_fixture_formula_cell(self, fixture_path):
        from kerf_imports.freecad.parser import parse_fcstd
        doc = parse_fcstd(fixture_path.read_bytes())
        result = translate_spreadsheet(doc.objects_by_type("Spreadsheet::Sheet")[0])
        hole_param = next(p for p in result["params"] if p["name"] == "hole_radius")
        # Formula cells have no unit
        assert "unit" not in hole_param
        assert "wall_thickness" in hole_param["expr"]

    def test_fixture_no_errors(self, fixture_path):
        from kerf_imports.freecad.parser import parse_fcstd
        doc = parse_fcstd(fixture_path.read_bytes())
        result = translate_spreadsheet(doc.objects_by_type("Spreadsheet::Sheet")[0])
        assert result["warnings"] == []
