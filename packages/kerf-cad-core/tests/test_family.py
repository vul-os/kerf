"""
Tests for kerf_cad_core.family — parametric family definition system.

All tests are pure-Python, hermetic: no OCC, no DB, no network, no fixtures
from disk. Tests run deterministically with fixed numeric inputs.

Coverage (≥25 cases):
  1.  family_define: valid definition succeeds
  2.  family_define: default param values resolved correctly
  3.  family_define: formula param resolves dependent params
  4.  family_define: formula with math function (sqrt)
  5.  family_define: cycle detected → error, ok=False
  6.  family_define: longer cycle (A→B→C→A) detected
  7.  family_define: duplicate param name rejected
  8.  family_define: unknown param_type rejected
  9.  family_define: min_value > max_value rejected
  10. family_define: empty name rejected
  11. family_define: duplicate family name rejected
  12. family_define: formula with unsafe AST node rejected
  13. family_add_type: type catalog entry added successfully
  14. family_add_type: unknown family → error
  15. family_add_type: unknown param in values → error
  16. family_add_type: out-of-range value rejected
  17. family_add_type: duplicate type name rejected
  18. family_instantiate: resolves defaults + type overrides
  19. family_instantiate: instance override merges on top of type values
  20. family_instantiate: formula params computed from resolved bases
  21. family_instantiate: out-of-range instance override rejected
  22. family_instantiate: unknown type → error
  23. family_instantiate: unknown override key → error
  24. family_instantiate: recipe template substituted with resolved params
  25. family_validate: valid values → ok, resolved_params returned
  26. family_validate: out-of-range value → error
  27. family_validate: unknown param in values → error
  28. family_validate: formula cycle error surface from validate
  29. LLM tool run_family_define: JSON round-trip ok
  30. LLM tool run_family_add_type: JSON round-trip ok
  31. LLM tool run_family_instantiate: JSON round-trip ok
  32. LLM tool run_family_validate: JSON round-trip ok
  33. LLM tool: malformed JSON → BAD_ARGS, not exception
  34. family_define: string param type accepted
  35. family_define: bool param type accepted
  36. family_instantiate: resolved recipe values are numbers not strings

Author: imranparuk
"""
from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from kerf_cad_core.family.model import (
    _clear_registry,
    _detect_cycle,
    _eval_formula,
    _resolve_params,
    _validate_ranges,
    _substitute_template,
    FamilyParam,
    family_define,
    family_add_type,
    family_instantiate,
    family_validate,
)
from kerf_cad_core.family.tools import (
    run_family_define,
    run_family_add_type,
    run_family_instantiate,
    run_family_validate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_ctx():
    from kerf_core.utils.context import ProjectCtx  # type: ignore[import]
    return ProjectCtx(
        pool=None, storage=None,
        project_id=uuid.uuid4(), user_id=uuid.uuid4(),
        role="owner", http_client=None,
    )


def _fresh_reg():
    """Return an isolated registry dict for test isolation."""
    return {}


def _door_params():
    return [
        {"name": "width", "param_type": "number", "default": 900.0,
         "min_value": 600.0, "max_value": 1200.0, "description": "Door width mm"},
        {"name": "height", "param_type": "number", "default": 2100.0,
         "min_value": 1800.0, "max_value": 2400.0, "description": "Door height mm"},
        {"name": "thickness", "param_type": "number", "default": 40.0,
         "min_value": 30.0, "max_value": 80.0},
    ]


def _door_family(reg):
    return family_define(
        name="Door",
        params=_door_params(),
        recipe_template={"kind": "door", "w": "{width}", "h": "{height}"},
        _registry_=reg,
    )


# ---------------------------------------------------------------------------
# 1. family_define: valid definition succeeds
# ---------------------------------------------------------------------------

def test_family_define_valid():
    reg = _fresh_reg()
    result = _door_family(reg)
    assert result["ok"] is True
    assert result["family_name"] == "Door"
    assert "Door" in reg


# ---------------------------------------------------------------------------
# 2. family_define: default param values resolved via family_validate
# ---------------------------------------------------------------------------

def test_family_define_defaults_resolved():
    reg = _fresh_reg()
    _door_family(reg)
    result = family_validate("Door", {}, _registry_=reg)
    assert result["ok"] is True
    rp = result["resolved_params"]
    assert rp["width"] == 900.0
    assert rp["height"] == 2100.0
    assert rp["thickness"] == 40.0


# ---------------------------------------------------------------------------
# 3. family_define: formula param resolves dependent params
# ---------------------------------------------------------------------------

def test_formula_resolves_dependent_params():
    reg = _fresh_reg()
    params = [
        {"name": "width", "default": 900.0},
        {"name": "height", "default": 2100.0},
        {"name": "area", "formula": "width * height"},
    ]
    r = family_define(name="Panel", params=params, _registry_=reg)
    assert r["ok"] is True

    vr = family_validate("Panel", {"width": 800.0, "height": 2000.0}, _registry_=reg)
    assert vr["ok"] is True
    assert vr["resolved_params"]["area"] == pytest.approx(1_600_000.0)


# ---------------------------------------------------------------------------
# 4. family_define: formula with math function (sqrt)
# ---------------------------------------------------------------------------

def test_formula_sqrt():
    reg = _fresh_reg()
    params = [
        {"name": "side", "default": 4.0},
        {"name": "diagonal", "formula": "sqrt(2) * side"},
    ]
    r = family_define(name="Square", params=params, _registry_=reg)
    assert r["ok"] is True

    vr = family_validate("Square", {"side": 9.0}, _registry_=reg)
    assert vr["ok"] is True
    import math
    assert vr["resolved_params"]["diagonal"] == pytest.approx(math.sqrt(2) * 9.0)


# ---------------------------------------------------------------------------
# 5. family_define: direct cycle (A→A) detected
# ---------------------------------------------------------------------------

def test_formula_self_cycle_detected():
    reg = _fresh_reg()
    params = [
        {"name": "x", "formula": "x + 1"},
    ]
    r = family_define(name="Bad", params=params, _registry_=reg)
    assert r["ok"] is False
    assert any("cycle" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# 6. family_define: longer cycle A→B→C→A detected
# ---------------------------------------------------------------------------

def test_formula_longer_cycle_detected():
    reg = _fresh_reg()
    params = [
        {"name": "a", "formula": "c + 1"},
        {"name": "b", "formula": "a + 1"},
        {"name": "c", "formula": "b + 1"},
    ]
    r = family_define(name="Cyclic", params=params, _registry_=reg)
    assert r["ok"] is False
    assert any("cycle" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# 7. family_define: duplicate param name rejected
# ---------------------------------------------------------------------------

def test_duplicate_param_name_rejected():
    reg = _fresh_reg()
    params = [
        {"name": "width", "default": 900.0},
        {"name": "width", "default": 800.0},  # duplicate
    ]
    r = family_define(name="Dup", params=params, _registry_=reg)
    assert r["ok"] is False
    assert any("duplicate" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# 8. family_define: unknown param_type rejected
# ---------------------------------------------------------------------------

def test_unknown_param_type_rejected():
    reg = _fresh_reg()
    params = [{"name": "x", "param_type": "float", "default": 1.0}]
    r = family_define(name="Bad2", params=params, _registry_=reg)
    assert r["ok"] is False
    assert any("invalid type" in e.lower() or "param_type" in e.lower() or "float" in e for e in r["errors"])


# ---------------------------------------------------------------------------
# 9. family_define: min_value > max_value rejected
# ---------------------------------------------------------------------------

def test_min_greater_than_max_rejected():
    reg = _fresh_reg()
    params = [{"name": "x", "default": 5.0, "min_value": 10.0, "max_value": 1.0}]
    r = family_define(name="BadRange", params=params, _registry_=reg)
    assert r["ok"] is False
    assert any("min_value" in e.lower() or "max" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# 10. family_define: empty name rejected
# ---------------------------------------------------------------------------

def test_empty_family_name_rejected():
    reg = _fresh_reg()
    r = family_define(name="", params=[], _registry_=reg)
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# 11. family_define: duplicate family name rejected
# ---------------------------------------------------------------------------

def test_duplicate_family_name_rejected():
    reg = _fresh_reg()
    _door_family(reg)
    r2 = _door_family(reg)
    assert r2["ok"] is False
    assert any("already exists" in e for e in r2["errors"])


# ---------------------------------------------------------------------------
# 12. family_define: formula with unsafe AST node rejected
# ---------------------------------------------------------------------------

def test_formula_unsafe_ast_rejected():
    reg = _fresh_reg()
    # import statement inside formula is unsafe
    params = [{"name": "x", "formula": "__import__('os').getenv('PATH')"}]
    r = family_define(name="Unsafe", params=params, _registry_=reg)
    assert r["ok"] is False
    assert any("unsafe" in e.lower() or "syntax" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# 13. family_add_type: type catalog entry added successfully
# ---------------------------------------------------------------------------

def test_add_type_success():
    reg = _fresh_reg()
    _door_family(reg)
    r = family_add_type(
        "Door", "Door 900x2100", {"width": 900.0, "height": 2100.0}, _registry_=reg
    )
    assert r["ok"] is True
    assert r["type_name"] == "Door 900x2100"
    assert "Door 900x2100" in reg["Door"].types


# ---------------------------------------------------------------------------
# 14. family_add_type: unknown family → error
# ---------------------------------------------------------------------------

def test_add_type_unknown_family():
    reg = _fresh_reg()
    r = family_add_type("Ghost", "T1", {"width": 900.0}, _registry_=reg)
    assert r["ok"] is False
    assert any("not found" in e for e in r["errors"])


# ---------------------------------------------------------------------------
# 15. family_add_type: unknown param in values → error
# ---------------------------------------------------------------------------

def test_add_type_unknown_param_rejected():
    reg = _fresh_reg()
    _door_family(reg)
    r = family_add_type("Door", "T1", {"depth": 500.0}, _registry_=reg)
    assert r["ok"] is False
    assert any("unknown param" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# 16. family_add_type: out-of-range value rejected
# ---------------------------------------------------------------------------

def test_add_type_out_of_range_rejected():
    reg = _fresh_reg()
    _door_family(reg)
    r = family_add_type("Door", "T2", {"width": 5000.0}, _registry_=reg)  # max 1200
    assert r["ok"] is False
    assert any("above maximum" in e or "maximum" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# 17. family_add_type: duplicate type name rejected
# ---------------------------------------------------------------------------

def test_add_type_duplicate_rejected():
    reg = _fresh_reg()
    _door_family(reg)
    family_add_type("Door", "Standard", {"width": 900.0}, _registry_=reg)
    r2 = family_add_type("Door", "Standard", {"width": 800.0}, _registry_=reg)
    assert r2["ok"] is False
    assert any("already exists" in e for e in r2["errors"])


# ---------------------------------------------------------------------------
# 18. family_instantiate: resolves defaults + type overrides
# ---------------------------------------------------------------------------

def test_instantiate_defaults_and_type():
    reg = _fresh_reg()
    _door_family(reg)
    family_add_type("Door", "Narrow", {"width": 700.0}, _registry_=reg)
    r = family_instantiate("Door", "Narrow", _registry_=reg)
    assert r["ok"] is True
    rp = r["resolved_params"]
    assert rp["width"] == 700.0
    assert rp["height"] == 2100.0  # default


# ---------------------------------------------------------------------------
# 19. family_instantiate: instance override merges on top of type values
# ---------------------------------------------------------------------------

def test_instantiate_override_merge():
    reg = _fresh_reg()
    _door_family(reg)
    family_add_type("Door", "Standard", {"width": 900.0, "height": 2100.0}, _registry_=reg)
    r = family_instantiate(
        "Door", "Standard",
        instance_name="Bathroom Door",
        overrides={"width": 750.0},
        _registry_=reg,
    )
    assert r["ok"] is True
    assert r["instance"]["name"] == "Bathroom Door"
    assert r["resolved_params"]["width"] == 750.0
    assert r["resolved_params"]["height"] == 2100.0


# ---------------------------------------------------------------------------
# 20. family_instantiate: formula params computed from resolved bases
# ---------------------------------------------------------------------------

def test_instantiate_formula_computed():
    reg = _fresh_reg()
    params = [
        {"name": "width", "default": 900.0},
        {"name": "height", "default": 2100.0},
        {"name": "area", "formula": "width * height"},
    ]
    family_define(
        "FPanel",
        params=params,
        recipe_template={"area_mm2": "{area}"},
        _registry_=reg,
    )
    family_add_type("FPanel", "Standard", {"width": 600.0, "height": 1800.0}, _registry_=reg)
    r = family_instantiate("FPanel", "Standard", _registry_=reg)
    assert r["ok"] is True
    assert r["resolved_params"]["area"] == pytest.approx(600.0 * 1800.0)


# ---------------------------------------------------------------------------
# 21. family_instantiate: out-of-range instance override rejected
# ---------------------------------------------------------------------------

def test_instantiate_override_out_of_range_rejected():
    reg = _fresh_reg()
    _door_family(reg)
    family_add_type("Door", "Base", {"width": 900.0}, _registry_=reg)
    r = family_instantiate("Door", "Base", overrides={"width": 100.0}, _registry_=reg)  # min 600
    assert r["ok"] is False
    assert any("below minimum" in e or "minimum" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# 22. family_instantiate: unknown type → error
# ---------------------------------------------------------------------------

def test_instantiate_unknown_type():
    reg = _fresh_reg()
    _door_family(reg)
    r = family_instantiate("Door", "NoSuchType", _registry_=reg)
    assert r["ok"] is False
    assert any("not found" in e for e in r["errors"])


# ---------------------------------------------------------------------------
# 23. family_instantiate: unknown override key → error
# ---------------------------------------------------------------------------

def test_instantiate_unknown_override_key():
    reg = _fresh_reg()
    _door_family(reg)
    family_add_type("Door", "Base2", {"width": 900.0}, _registry_=reg)
    r = family_instantiate("Door", "Base2", overrides={"color": "red"}, _registry_=reg)
    assert r["ok"] is False
    assert any("unknown param" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# 24. family_instantiate: recipe template substituted with resolved params
# ---------------------------------------------------------------------------

def test_instantiate_recipe_template_substituted():
    reg = _fresh_reg()
    _door_family(reg)
    family_add_type("Door", "Main", {"width": 900.0, "height": 2100.0}, _registry_=reg)
    r = family_instantiate("Door", "Main", _registry_=reg)
    assert r["ok"] is True
    recipe = r["recipe"]
    assert recipe["kind"] == "door"
    assert recipe["w"] == "900.0"
    assert recipe["h"] == "2100.0"


# ---------------------------------------------------------------------------
# 25. family_validate: valid values → ok, resolved_params returned
# ---------------------------------------------------------------------------

def test_validate_valid_values():
    reg = _fresh_reg()
    _door_family(reg)
    r = family_validate("Door", {"width": 800.0, "height": 2000.0}, _registry_=reg)
    assert r["ok"] is True
    assert r["resolved_params"]["width"] == 800.0


# ---------------------------------------------------------------------------
# 26. family_validate: out-of-range value → error
# ---------------------------------------------------------------------------

def test_validate_out_of_range():
    reg = _fresh_reg()
    _door_family(reg)
    r = family_validate("Door", {"width": 50.0}, _registry_=reg)  # min 600
    assert r["ok"] is False
    assert any("below minimum" in e or "minimum" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# 27. family_validate: unknown param in values → error
# ---------------------------------------------------------------------------

def test_validate_unknown_param():
    reg = _fresh_reg()
    _door_family(reg)
    r = family_validate("Door", {"bogus": 100.0}, _registry_=reg)
    assert r["ok"] is False
    assert any("unknown param" in e.lower() for e in r["errors"])


# ---------------------------------------------------------------------------
# 28. family_validate: unknown family → error
# ---------------------------------------------------------------------------

def test_validate_unknown_family():
    reg = _fresh_reg()
    r = family_validate("Ghost", {"width": 900.0}, _registry_=reg)
    assert r["ok"] is False
    assert any("not found" in e for e in r["errors"])


# ---------------------------------------------------------------------------
# 29. LLM tool run_family_define: JSON round-trip ok
# ---------------------------------------------------------------------------

def test_tool_run_family_define_json_roundtrip():
    ctx = _make_ctx()
    payload = json.dumps({
        "name": f"ToolDoor_{uuid.uuid4().hex[:8]}",
        "params": [
            {"name": "width", "default": 900.0, "min_value": 600.0, "max_value": 1200.0},
            {"name": "height", "default": 2100.0},
        ],
        "recipe_template": {"kind": "door"},
    }).encode()
    raw = _run(run_family_define(ctx, payload))
    result = json.loads(raw)
    assert result["ok"] is True
    assert "family_name" in result


# ---------------------------------------------------------------------------
# 30. LLM tool run_family_add_type: JSON round-trip ok
# ---------------------------------------------------------------------------

def test_tool_run_family_add_type_json_roundtrip():
    ctx = _make_ctx()
    fname = f"ToolColF_{uuid.uuid4().hex[:8]}"
    # Define first
    _run(run_family_define(ctx, json.dumps({
        "name": fname,
        "params": [
            {"name": "w", "default": 300.0},
            {"name": "h", "default": 300.0},
        ],
    }).encode()))
    raw = _run(run_family_add_type(ctx, json.dumps({
        "family_name": fname,
        "type_name": "300x300",
        "values": {"w": 300.0, "h": 300.0},
    }).encode()))
    result = json.loads(raw)
    assert result["ok"] is True
    assert result["type_name"] == "300x300"


# ---------------------------------------------------------------------------
# 31. LLM tool run_family_instantiate: JSON round-trip ok
# ---------------------------------------------------------------------------

def test_tool_run_family_instantiate_json_roundtrip():
    ctx = _make_ctx()
    fname = f"ToolInst_{uuid.uuid4().hex[:8]}"
    _run(run_family_define(ctx, json.dumps({
        "name": fname,
        "params": [{"name": "side", "default": 500.0}],
        "recipe_template": {"side_mm": "{side}"},
    }).encode()))
    _run(run_family_add_type(ctx, json.dumps({
        "family_name": fname,
        "type_name": "500mm",
        "values": {"side": 500.0},
    }).encode()))
    raw = _run(run_family_instantiate(ctx, json.dumps({
        "family_name": fname,
        "type_name": "500mm",
        "instance_name": "Pillar A",
    }).encode()))
    result = json.loads(raw)
    assert result["ok"] is True
    assert result["instance"]["name"] == "Pillar A"
    assert result["resolved_params"]["side"] == 500.0


# ---------------------------------------------------------------------------
# 32. LLM tool run_family_validate: JSON round-trip ok
# ---------------------------------------------------------------------------

def test_tool_run_family_validate_json_roundtrip():
    ctx = _make_ctx()
    fname = f"ToolVal_{uuid.uuid4().hex[:8]}"
    _run(run_family_define(ctx, json.dumps({
        "name": fname,
        "params": [{"name": "d", "default": 100.0, "min_value": 10.0, "max_value": 500.0}],
    }).encode()))
    raw = _run(run_family_validate(ctx, json.dumps({
        "family_name": fname,
        "values": {"d": 250.0},
    }).encode()))
    result = json.loads(raw)
    assert result["ok"] is True
    assert result["resolved_params"]["d"] == 250.0


# ---------------------------------------------------------------------------
# 33. LLM tool: malformed JSON → BAD_ARGS, not exception
# ---------------------------------------------------------------------------

def test_tool_malformed_json_no_exception():
    ctx = _make_ctx()
    for tool_fn in [run_family_define, run_family_add_type,
                    run_family_instantiate, run_family_validate]:
        raw = _run(tool_fn(ctx, b"not json at all {{{"))
        result = json.loads(raw)
        # err_payload returns {"error": ..., "code": ...} — never {"ok": true}
        assert result.get("ok") is not True
        assert "error" in result or "errors" in result or result.get("ok") is False


# ---------------------------------------------------------------------------
# 34. family_define: string param type accepted
# ---------------------------------------------------------------------------

def test_string_param_type_accepted():
    reg = _fresh_reg()
    params = [
        {"name": "material", "param_type": "string", "default": "oak",
         "description": "Door material"},
    ]
    r = family_define(name="WoodDoor", params=params, _registry_=reg)
    assert r["ok"] is True

    vr = family_validate("WoodDoor", {}, _registry_=reg)
    assert vr["ok"] is True
    assert vr["resolved_params"]["material"] == "oak"


# ---------------------------------------------------------------------------
# 35. family_define: bool param type accepted
# ---------------------------------------------------------------------------

def test_bool_param_type_accepted():
    reg = _fresh_reg()
    params = [
        {"name": "fire_rated", "param_type": "bool", "default": False},
    ]
    r = family_define(name="FireDoor", params=params, _registry_=reg)
    assert r["ok"] is True

    vr = family_validate("FireDoor", {}, _registry_=reg)
    assert vr["ok"] is True
    assert vr["resolved_params"]["fire_rated"] is False


# ---------------------------------------------------------------------------
# 36. family_instantiate: resolved recipe values are numbers not strings when
#     the template value is a bare number (not a placeholder string)
# ---------------------------------------------------------------------------

def test_instantiate_numeric_template_values_preserved():
    reg = _fresh_reg()
    params = [
        {"name": "width", "default": 900.0},
    ]
    # Template has a direct int — should pass through unchanged.
    family_define(
        "NumRecipe",
        params=params,
        recipe_template={"version": 1, "label": "w={width}"},
        _registry_=reg,
    )
    family_add_type("NumRecipe", "Standard", {"width": 900.0}, _registry_=reg)
    r = family_instantiate("NumRecipe", "Standard", _registry_=reg)
    assert r["ok"] is True
    assert r["recipe"]["version"] == 1  # integer preserved, not turned into string
    assert "900" in r["recipe"]["label"]
