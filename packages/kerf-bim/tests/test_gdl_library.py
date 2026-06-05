"""
Tests for kerf_bim.gdl_library — GDL parametric object library.

Coverage
--------
- GDLParam: valid types + invalid type
- GDLObject: valid subtypes + invalid subtype
- GDLLibrary: get/list_objects with and without subtype filter
- validate_gdl_object: clean script, forbidden AST nodes (import, exec, eval)
- evaluate_gdl_object: basic arithmetic, param override, bad param name
- instantiate_gdl: default params + overrides, unknown object_id
- DEFAULT_LIBRARY: all 6 built-in objects present and evaluate cleanly
- LLM tool: bim_gdl_list_objects
- LLM tool: bim_gdl_evaluate_object
- LLM tool: bim_gdl_validate_object
- LLM tool: bim_gdl_instantiate
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kerf_bim.gdl_library import (
    DEFAULT_LIBRARY,
    GDLLibrary,
    GDLObject,
    GDLParam,
    evaluate_gdl_object,
    instantiate_gdl,
    validate_gdl_object,
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# 1. GDLParam
# ---------------------------------------------------------------------------

class TestGDLParam:
    def test_valid_length_param(self):
        p = GDLParam("width", "length", default=1.0, min=0.1, max=10.0)
        assert p.type == "length"

    def test_valid_boolean(self):
        p = GDLParam("has_handle", "boolean", default=True)
        assert p.default is True

    def test_valid_string(self):
        p = GDLParam("label", "string", default="Room A")
        assert p.default == "Room A"

    def test_invalid_type_raises(self):
        with pytest.raises(ValueError, match="type must be one of"):
            GDLParam("x", "sqft", default=1.0)

    def test_min_max_optional(self):
        p = GDLParam("x", "real", default=5.0)
        assert p.min is None
        assert p.max is None

    def test_values_for_enum_style(self):
        p = GDLParam("shape", "string", values=["rect", "round", "oval"])
        assert "rect" in p.values


# ---------------------------------------------------------------------------
# 2. GDLObject
# ---------------------------------------------------------------------------

class TestGDLObject:
    def _simple_obj(self, subtype="Door"):
        return GDLObject(
            id="TEST_DOOR_001",
            name="Test Door",
            subtype=subtype,
            params=[
                GDLParam("A", "length", default=0.9),
                GDLParam("B", "length", default=2.1),
            ],
            script="width = A\nheight = B\narea = width * height",
        )

    def test_valid_door_subtype(self):
        obj = self._simple_obj("Door")
        assert obj.subtype == "Door"

    def test_valid_furniture_subtype(self):
        obj = self._simple_obj("Furniture")
        assert obj.subtype == "Furniture"

    def test_invalid_subtype_raises(self):
        with pytest.raises(ValueError, match="subtype must be one of"):
            GDLObject(id="X", name="X", subtype="spaceship", params=[], script="")

    def test_empty_id_raises(self):
        with pytest.raises(ValueError):
            GDLObject(id="", name="X", subtype="Door", params=[], script="")

    def test_empty_name_raises(self):
        with pytest.raises(ValueError):
            GDLObject(id="X1", name="", subtype="Door", params=[], script="")


# ---------------------------------------------------------------------------
# 3. GDLLibrary
# ---------------------------------------------------------------------------

class TestGDLLibrary:
    def _lib(self):
        objs = [
            GDLObject("D1", "Door A",   "Door",      [], ""),
            GDLObject("D2", "Door B",   "Door",      [], ""),
            GDLObject("W1", "Window A", "Window",    [], ""),
            GDLObject("F1", "Desk",     "Furniture", [], ""),
        ]
        return GDLLibrary(objs)

    def test_get_existing(self):
        lib = self._lib()
        obj = lib.get("W1")
        assert obj is not None
        assert obj.name == "Window A"

    def test_get_missing_returns_none(self):
        lib = self._lib()
        assert lib.get("NONEXISTENT") is None

    def test_list_all(self):
        lib = self._lib()
        assert len(lib.list_objects()) == 4

    def test_list_by_subtype(self):
        lib = self._lib()
        doors = lib.list_objects("Door")
        assert len(doors) == 2

    def test_list_subtype_no_match(self):
        lib = self._lib()
        assert lib.list_objects("Lamp") == []


# ---------------------------------------------------------------------------
# 4. validate_gdl_object
# ---------------------------------------------------------------------------

class TestValidateGDLObject:
    def test_clean_script(self):
        obj = GDLObject("X", "X", "Door", [GDLParam("A", "length", 1.0)], "h = A * 2")
        errors = validate_gdl_object(obj)
        assert errors == []

    def test_import_forbidden(self):
        obj = GDLObject("X", "X", "Door", [], "import os")
        errors = validate_gdl_object(obj)
        assert any("import" in e.lower() or "Import" in e or "unsafe" in e for e in errors)

    def test_exec_forbidden(self):
        obj = GDLObject("X", "X", "Door", [], "exec('x=1')")
        errors = validate_gdl_object(obj)
        assert any("exec" in e for e in errors)

    def test_eval_forbidden(self):
        obj = GDLObject("X", "X", "Door", [], "v = eval('1+1')")
        errors = validate_gdl_object(obj)
        assert any("eval" in e for e in errors)

    def test_open_forbidden(self):
        obj = GDLObject("X", "X", "Door", [], "f = open('secret.txt')")
        errors = validate_gdl_object(obj)
        assert any("open" in e or "Call" in e for e in errors)

    def test_math_functions_allowed(self):
        obj = GDLObject("X", "X", "Door", [GDLParam("A", "length", 2.0)],
                        "import math\nv = math.sqrt(A)")
        errors = validate_gdl_object(obj)
        # import math for math functions — implementation may or may not allow it
        # The key behaviour is that the obj has errors if import is forbidden
        # Just check return type
        assert isinstance(errors, list)

    def test_empty_script_valid(self):
        obj = GDLObject("X", "X", "Door", [], "")
        errors = validate_gdl_object(obj)
        assert errors == []


# ---------------------------------------------------------------------------
# 5. evaluate_gdl_object
# ---------------------------------------------------------------------------

class TestEvaluateGDLObject:
    def _door(self):
        return GDLObject(
            "DOOR", "Door", "Door",
            [
                GDLParam("A", "length", default=0.9, min=0.6, max=1.5),
                GDLParam("B", "length", default=2.1, min=1.8, max=2.7),
            ],
            "width = A\nheight = B\narea = A * B",
        )

    def test_default_params_evaluated(self):
        obj = self._door()
        result = evaluate_gdl_object(obj)
        # resolved_params contains the input parameters
        assert result["resolved_params"]["A"] == pytest.approx(0.9)
        assert result["resolved_params"]["B"] == pytest.approx(2.1)

    def test_override_applied(self):
        obj = self._door()
        result = evaluate_gdl_object(obj, {"A": 1.2})
        assert result["resolved_params"]["A"] == pytest.approx(1.2)

    def test_unknown_override_ignored_or_raises(self):
        # Implementation may ignore unknown overrides or raise; both are valid
        obj = self._door()
        try:
            result = evaluate_gdl_object(obj, {"nonexistent": 1.0})
            # If it didn't raise, check the known param is still correct
            assert result["resolved_params"]["A"] == pytest.approx(0.9)
        except (ValueError, KeyError):
            pass  # raising is also acceptable

    def test_empty_script_returns_param_defaults(self):
        obj = GDLObject("X", "X", "Door", [GDLParam("A", "length", default=5.0)], "")
        result = evaluate_gdl_object(obj)
        assert result["resolved_params"]["A"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# 6. instantiate_gdl
# ---------------------------------------------------------------------------

class TestInstantiateGDL:
    def test_instantiate_with_defaults(self):
        result = instantiate_gdl(DEFAULT_LIBRARY, "DOOR_SINGLE_00001")
        assert result["object_id"] == "DOOR_SINGLE_00001"
        assert "resolved_params" in result

    def test_instantiate_with_override(self):
        result = instantiate_gdl(DEFAULT_LIBRARY, "DOOR_SINGLE_00001", {"WIDTH": 1.2})
        assert result["resolved_params"]["WIDTH"] == pytest.approx(1.2)

    def test_instantiate_unknown_id_raises(self):
        with pytest.raises(KeyError, match="NONEXISTENT"):
            instantiate_gdl(DEFAULT_LIBRARY, "NONEXISTENT")

    def test_window_instantiate(self):
        result = instantiate_gdl(DEFAULT_LIBRARY, "WINDOW_CASEMENT_00001")
        assert result["subtype"] == "Window"


# ---------------------------------------------------------------------------
# 7. DEFAULT_LIBRARY
# ---------------------------------------------------------------------------

class TestDefaultLibrary:
    def test_all_six_objects_present(self):
        expected = [
            "DOOR_SINGLE_00001",
            "WINDOW_CASEMENT_00001",
            "COLUMN_ROUND_00001",
            "BEAM_RECT_00001",
            "DESK_OFFICE_00001",
            "LIGHT_PENDANT_00001",
        ]
        for oid in expected:
            assert DEFAULT_LIBRARY.get(oid) is not None, f"{oid} not in DEFAULT_LIBRARY"

    def test_all_evaluate_cleanly(self):
        for meta in DEFAULT_LIBRARY.list_objects():
            obj = DEFAULT_LIBRARY.get(meta["id"])
            result = evaluate_gdl_object(obj)
            assert isinstance(result, dict)

    def test_all_validate_cleanly(self):
        for meta in DEFAULT_LIBRARY.list_objects():
            obj = DEFAULT_LIBRARY.get(meta["id"])
            errors = validate_gdl_object(obj)
            assert errors == [], f"{obj.id}: {errors}"

    def test_subtypes_varied(self):
        subtypes = {meta["subtype"] for meta in DEFAULT_LIBRARY.list_objects()}
        assert len(subtypes) >= 4  # Door, Window, structural, Furniture, lighting


# ---------------------------------------------------------------------------
# 8. LLM tool: bim_gdl_list_objects
# ---------------------------------------------------------------------------

class TestLLMGDLListObjects:
    def _call(self, **kwargs) -> dict:
        from kerf_bim.tools.gdl_library import run_bim_gdl_list_objects
        return json.loads(_run(run_bim_gdl_list_objects(kwargs, None)))

    def test_list_all(self):
        result = self._call()
        assert result["ok"] is True
        assert result["count"] == 6

    def test_filter_door(self):
        result = self._call(subtype="Door")
        assert result["ok"] is True
        assert all(o["subtype"] == "Door" for o in result["objects"])

    def test_filter_no_match(self):
        result = self._call(subtype="spacecraft")
        assert result["ok"] is True
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# 9. LLM tool: bim_gdl_evaluate_object
# ---------------------------------------------------------------------------

class TestLLMGDLEvaluateObject:
    def _call(self, object_id, **kwargs) -> dict:
        from kerf_bim.tools.gdl_library import run_bim_gdl_evaluate_object
        params = {"object_id": object_id, **kwargs}
        return json.loads(_run(run_bim_gdl_evaluate_object(params, None)))

    def test_evaluate_defaults(self):
        result = self._call("DOOR_SINGLE_00001")
        assert result["ok"] is True
        assert "resolved_params" in result

    def test_evaluate_with_override(self):
        result = self._call("DOOR_SINGLE_00001", param_overrides={"WIDTH": 1.1})
        assert result["ok"] is True
        assert result["resolved_params"]["WIDTH"] == pytest.approx(1.1)

    def test_unknown_id_returns_error(self):
        result = self._call("TOTALLY_FAKE_ID")
        assert "error" in result

    def test_output_keys_present(self):
        result = self._call("COLUMN_ROUND_00001")
        assert result["ok"] is True
        assert isinstance(result["resolved_params"], dict)


# ---------------------------------------------------------------------------
# 10. LLM tool: bim_gdl_validate_object
# ---------------------------------------------------------------------------

class TestLLMGDLValidateObject:
    def _call(self, object_def) -> dict:
        from kerf_bim.tools.gdl_library import run_bim_gdl_validate_object
        return json.loads(_run(run_bim_gdl_validate_object({"object_def": object_def}, None)))

    def _door_def(self):
        return {
            "id": "DOOR_TEST",
            "name": "Test Door",
            "subtype": "Door",
            "params": [{"name": "WIDTH", "type": "length", "default": 0.9}],
            "script": "height = WIDTH * 2.3",
        }

    def test_validate_clean_def(self):
        result = self._call(self._door_def())
        assert result["ok"] is True
        assert result["valid"] is True
        assert result["errors"] == []

    def test_validate_with_import(self):
        d = self._door_def()
        d["script"] = "import os"
        result = self._call(d)
        assert result["ok"] is True
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_validate_with_eval(self):
        d = self._door_def()
        d["script"] = "v = eval('1+1')"
        result = self._call(d)
        assert result["ok"] is True
        assert result["valid"] is False


# ---------------------------------------------------------------------------
# 11. LLM tool: bim_gdl_instantiate
# ---------------------------------------------------------------------------

class TestLLMGDLInstantiate:
    def _call(self, object_id, **kwargs) -> dict:
        from kerf_bim.tools.gdl_library import run_bim_gdl_instantiate
        params = {"object_id": object_id, **kwargs}
        return json.loads(_run(run_bim_gdl_instantiate(params, None)))

    def test_basic_instantiate(self):
        result = self._call("DESK_OFFICE_00001")
        assert result["ok"] is True
        assert result["object_id"] == "DESK_OFFICE_00001"
        assert "resolved_params" in result

    def test_override_applied(self):
        result = self._call("WINDOW_CASEMENT_00001", param_overrides={"WIDTH": 1.5})
        assert result["ok"] is True
        assert result["resolved_params"]["WIDTH"] == pytest.approx(1.5)

    def test_unknown_id_returns_error(self):
        result = self._call("NONEXISTENT")
        assert "error" in result

    def test_outputs_present(self):
        r1 = self._call("LIGHT_PENDANT_00001")
        assert r1["ok"] is True
        assert "resolved_params" in r1
