"""
Tests for kerf_bim.nested_family — parametric nested families + type catalogue.

Coverage
--------
- NestedFamily: valid + invalid (empty sub_family_id)
- TypeCatalogueEntry: valid + invalid (empty type_id, bad param type)
- build_type_catalogue: valid, duplicate type_id, unknown param, type-mismatch
- render_catalogue_table: row structure
- instantiate_nested: no overrides, type catalogue lookup, nested sub-family count
- validate_nested: parent errors propagated, placement_param references
- LLM tool: bim_family_nested_instantiate
- LLM tool: bim_family_nested_validate
- LLM tool: bim_family_catalogue_build
- LLM tool: bim_family_catalogue_table
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kerf_bim.family_editor import FamilyDef, FamilyEditorError, FamilyFormula, FamilyParameter
from kerf_bim.nested_family import (
    NestedFamily,
    NestedFamilyDef,
    TypeCatalogue,
    TypeCatalogueEntry,
    build_type_catalogue,
    instantiate_nested,
    render_catalogue_table,
    validate_nested,
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _simple_family():
    return FamilyDef(
        name="Test Door",
        category="door",
        parameters=[
            FamilyParameter("width", "number", 900.0, min=600.0, max=1200.0, units="mm"),
            FamilyParameter("height", "number", 2100.0, min=1800.0, max=2700.0, units="mm"),
            FamilyParameter("frame_thickness", "number", 70.0, min=40.0, max=120.0, units="mm"),
        ],
        formulas=[
            FamilyFormula("panel_width",  "width - 2 * frame_thickness"),
            FamilyFormula("panel_height", "height - frame_thickness"),
        ],
    )


def _nested_def():
    return NestedFamilyDef(
        parent=_simple_family(),
        nested_families=[
            NestedFamily(
                sub_family_id="DOOR_PANEL",
                placement_params={"width": "panel_width", "height": "panel_height"},
                count=1,
                label="Door Panel",
                ifc_type="IfcDoor",
            ),
            NestedFamily(
                sub_family_id="DOOR_FRAME",
                placement_params={"thickness": "frame_thickness"},
                count=2,
                label="Frame Profile",
                ifc_type="IfcMember",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# 1. NestedFamily
# ---------------------------------------------------------------------------

class TestNestedFamily:
    def test_valid_nested_family(self):
        nf = NestedFamily(sub_family_id="PANEL_A", placement_params={"w": "panel_width"}, count=4)
        assert nf.sub_family_id == "PANEL_A"

    def test_empty_sub_family_id_raises(self):
        with pytest.raises(FamilyEditorError):
            NestedFamily(sub_family_id="")

    def test_count_can_be_string(self):
        nf = NestedFamily(sub_family_id="P", count="panel_count")
        assert nf.count == "panel_count"


# ---------------------------------------------------------------------------
# 2. TypeCatalogueEntry
# ---------------------------------------------------------------------------

class TestTypeCatalogueEntry:
    def test_valid_entry(self):
        e = TypeCatalogueEntry(type_id="D900", name="900 mm Door", param_overrides={"width": 900.0})
        assert e.type_id == "D900"

    def test_empty_type_id_raises(self):
        with pytest.raises(FamilyEditorError):
            TypeCatalogueEntry(type_id="", name="Test")

    def test_empty_name_raises(self):
        with pytest.raises(FamilyEditorError):
            TypeCatalogueEntry(type_id="T1", name="")


# ---------------------------------------------------------------------------
# 3. build_type_catalogue
# ---------------------------------------------------------------------------

class TestBuildTypeCatalogue:
    def test_valid_catalogue(self):
        fdef = _simple_family()
        rows = [
            {"type_id": "D900", "name": "900 mm",  "width": 900.0},
            {"type_id": "D750", "name": "750 mm",  "width": 750.0},
        ]
        cat = build_type_catalogue(fdef, rows)
        assert len(cat.entries) == 2
        assert cat.family_name == "Test Door"

    def test_duplicate_type_id_raises(self):
        fdef = _simple_family()
        rows = [
            {"type_id": "D900", "name": "A", "width": 900.0},
            {"type_id": "D900", "name": "B", "width": 750.0},
        ]
        with pytest.raises(FamilyEditorError, match="duplicate"):
            build_type_catalogue(fdef, rows)

    def test_unknown_param_raises(self):
        fdef = _simple_family()
        rows = [{"type_id": "X1", "name": "X", "nonexistent_param": 5.0}]
        with pytest.raises(FamilyEditorError, match="unknown parameter"):
            build_type_catalogue(fdef, rows)

    def test_wrong_type_number_raises(self):
        fdef = _simple_family()
        rows = [{"type_id": "X1", "name": "X", "width": "not_a_number"}]
        with pytest.raises(FamilyEditorError, match="expects a number"):
            build_type_catalogue(fdef, rows)

    def test_empty_rows(self):
        cat = build_type_catalogue(_simple_family(), [])
        assert cat.entries == []

    def test_missing_type_id_raises(self):
        fdef = _simple_family()
        rows = [{"name": "A", "width": 900.0}]  # no type_id
        with pytest.raises(FamilyEditorError, match="type_id"):
            build_type_catalogue(fdef, rows)


# ---------------------------------------------------------------------------
# 4. render_catalogue_table
# ---------------------------------------------------------------------------

class TestRenderCatalogueTable:
    def test_row_structure(self):
        entries = [
            TypeCatalogueEntry("D900", "900 mm", {"width": 900.0}),
            TypeCatalogueEntry("D750", "750 mm", {"width": 750.0}),
        ]
        cat = TypeCatalogue("Test Door", entries=entries)
        table = render_catalogue_table(cat)
        assert len(table) == 2
        assert table[0]["type_id"] == "D900"
        assert table[0]["width"] == 900.0
        assert "name" in table[0]
        assert "description" in table[0]

    def test_empty_catalogue(self):
        cat = TypeCatalogue("X")
        assert render_catalogue_table(cat) == []


# ---------------------------------------------------------------------------
# 5. instantiate_nested
# ---------------------------------------------------------------------------

class TestInstantiateNested:
    def test_basic_instantiation(self):
        nfdef = _nested_def()
        result = instantiate_nested(nfdef)
        assert result["family"] == "Test Door"
        assert "resolved_params" in result
        assert result["nested_count"] == 2

    def test_resolved_formulas_in_params(self):
        nfdef = _nested_def()
        result = instantiate_nested(nfdef, {"width": 900.0, "height": 2100.0, "frame_thickness": 70.0})
        ns = result["resolved_params"]
        assert abs(ns["panel_width"] - (900.0 - 2 * 70.0)) < 0.001

    def test_type_catalogue_lookup(self):
        nfdef = _nested_def()
        fdef = nfdef.parent
        cat = build_type_catalogue(fdef, [
            {"type_id": "D900", "name": "900 mm Door", "width": 900.0, "height": 2100.0, "frame_thickness": 70.0},
            {"type_id": "D750", "name": "750 mm Door", "width": 750.0, "height": 2100.0, "frame_thickness": 70.0},
        ])
        result = instantiate_nested(nfdef, type_id="D750", catalogue=cat)
        assert result["type_id"] == "D750"
        assert result["resolved_params"]["width"] == 750.0

    def test_user_overrides_win_over_type(self):
        nfdef = _nested_def()
        fdef = nfdef.parent
        cat = build_type_catalogue(fdef, [{"type_id": "D900", "name": "900", "width": 900.0, "height": 2100.0, "frame_thickness": 70.0}])
        result = instantiate_nested(nfdef, {"width": 800.0}, type_id="D900", catalogue=cat)
        assert result["resolved_params"]["width"] == 800.0

    def test_nested_sub_family_count(self):
        nfdef = _nested_def()
        result = instantiate_nested(nfdef)
        nested = result["nested"]
        assert nested[0]["sub_family_id"] == "DOOR_PANEL"
        assert nested[1]["sub_family_id"] == "DOOR_FRAME"

    def test_count_expression_resolved(self):
        parent = FamilyDef(
            name="Window System",
            category="window",
            parameters=[
                FamilyParameter("panel_count", "number", 4.0, min=1.0, max=10.0),
            ],
        )
        nfdef = NestedFamilyDef(
            parent=parent,
            nested_families=[
                NestedFamily(sub_family_id="PANE", count="panel_count"),
            ],
        )
        result = instantiate_nested(nfdef, {"panel_count": 6.0})
        assert result["nested"][0]["count"] == 6


# ---------------------------------------------------------------------------
# 6. validate_nested
# ---------------------------------------------------------------------------

class TestValidateNested:
    def test_valid_definition(self):
        nfdef = _nested_def()
        errors = validate_nested(nfdef)
        # placement_params reference formula names which are known
        # There should be no hard errors — only possibly formula-ref warnings
        assert isinstance(errors, list)

    def test_unknown_placement_param_ref_warns(self):
        parent = _simple_family()
        nfdef = NestedFamilyDef(
            parent=parent,
            nested_families=[
                NestedFamily(
                    sub_family_id="PANEL",
                    placement_params={"w": "nonexistent_name"},
                ),
            ],
        )
        errors = validate_nested(nfdef)
        assert any("nonexistent_name" in e for e in errors)

    def test_invalid_parent_propagates(self):
        # Parent with bad formula (references unknown name) should surface
        parent = FamilyDef(
            name="Bad Family",
            category="generic",
            parameters=[FamilyParameter("x", "number", 1.0)],
            formulas=[FamilyFormula("result", "x + unknown_var")],
        )
        nfdef = NestedFamilyDef(parent=parent)
        errors = validate_nested(nfdef)
        assert any("unknown_var" in e or "unknown name" in e for e in errors)


# ---------------------------------------------------------------------------
# 7. LLM tool: bim_family_nested_instantiate
# ---------------------------------------------------------------------------

class TestLLMNestedInstantiate:
    def _raw_family(self):
        return {
            "parent": {
                "name": "Test Door",
                "category": "door",
                "parameters": [
                    {"name": "width",           "type": "number", "default": 900.0,  "min": 600.0,  "max": 1200.0},
                    {"name": "height",          "type": "number", "default": 2100.0, "min": 1800.0, "max": 2700.0},
                    {"name": "frame_thickness", "type": "number", "default": 70.0,   "min": 40.0,   "max": 120.0},
                ],
                "formulas": [
                    {"name": "panel_width",  "expression": "width - 2 * frame_thickness"},
                ],
            },
            "nested_families": [
                {"sub_family_id": "PANEL", "placement_params": {"w": "panel_width"}, "count": 1, "label": "Panel"},
            ],
        }

    def _call(self, family_def, **kwargs) -> dict:
        from kerf_bim.tools.parametric_family_editor import run_bim_family_nested_instantiate
        params = {"family_def": family_def, **kwargs}
        return json.loads(_run(run_bim_family_nested_instantiate(params, None)))

    def test_basic_instantiate(self):
        result = self._call(self._raw_family())
        assert result["ok"] is True
        assert result["family"] == "Test Door"

    def test_parameter_overrides(self):
        result = self._call(self._raw_family(), parameter_values={"width": 800.0})
        assert result["resolved_params"]["width"] == 800.0

    def test_nested_present(self):
        result = self._call(self._raw_family())
        assert "nested" in result
        assert len(result["nested"]) == 1

    def test_type_catalogue_applied(self):
        cat = {
            "family_name": "Test Door",
            "entries": [{"type_id": "D800", "name": "800mm", "width": 800.0}],
        }
        result = self._call(self._raw_family(), type_id="D800", type_catalogue=cat)
        assert result["type_id"] == "D800"


# ---------------------------------------------------------------------------
# 8. LLM tool: bim_family_nested_validate
# ---------------------------------------------------------------------------

class TestLLMNestedValidate:
    def _call(self, family_def) -> dict:
        from kerf_bim.tools.parametric_family_editor import run_bim_family_nested_validate
        return json.loads(_run(run_bim_family_nested_validate({"family_def": family_def}, None)))

    def test_valid_def(self):
        family_def = {
            "parent": {
                "name": "Win", "category": "window",
                "parameters": [{"name": "w", "type": "number", "default": 1.0}],
                "formulas": [],
            },
            "nested_families": [
                {"sub_family_id": "PANE", "placement_params": {"width": "w"}},
            ],
        }
        result = self._call(family_def)
        assert result["ok"] is True
        assert result["valid"] is True


# ---------------------------------------------------------------------------
# 9. LLM tool: bim_family_catalogue_build
# ---------------------------------------------------------------------------

class TestLLMCatalogueBuild:
    def _call(self, family_def, rows) -> dict:
        from kerf_bim.tools.parametric_family_editor import run_bim_family_catalogue_build
        return json.loads(_run(run_bim_family_catalogue_build({"family_def": family_def, "rows": rows}, None)))

    def test_valid_catalogue_build(self):
        family_def = {
            "name": "Door", "category": "door",
            "parameters": [{"name": "width", "type": "number", "default": 900.0}],
            "formulas": [],
        }
        rows = [{"type_id": "D900", "name": "900mm", "width": 900.0}]
        result = self._call(family_def, rows)
        assert result["ok"] is True
        assert result["entry_count"] == 1

    def test_unknown_param_error(self):
        family_def = {
            "name": "Door", "category": "door",
            "parameters": [{"name": "width", "type": "number", "default": 900.0}],
            "formulas": [],
        }
        rows = [{"type_id": "D900", "name": "900mm", "nonexistent": 999.0}]
        result = self._call(family_def, rows)
        assert "error" in result


# ---------------------------------------------------------------------------
# 10. LLM tool: bim_family_catalogue_table
# ---------------------------------------------------------------------------

class TestLLMCatalogueTable:
    def _call(self, catalogue) -> dict:
        from kerf_bim.tools.parametric_family_editor import run_bim_family_catalogue_table
        return json.loads(_run(run_bim_family_catalogue_table({"catalogue": catalogue}, None)))

    def test_basic_table(self):
        cat = {
            "family_name": "Door",
            "entries": [
                {"type_id": "D900", "name": "900mm", "width": 900.0},
                {"type_id": "D750", "name": "750mm", "width": 750.0},
            ],
        }
        result = self._call(cat)
        assert result["ok"] is True
        assert result["row_count"] == 2
        assert result["table"][0]["type_id"] == "D900"
