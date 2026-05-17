"""
Tests for the BIM parametric family system — T-109 foundation.

Hermetic: no DB, no async, no fixtures from the wider Kerf runtime.
Every test exercises `kerf_bim.family` in isolation.
"""
from __future__ import annotations

import math

import pytest

from kerf_bim.family import (
    SCHEMA,
    SCHEMA_VERSION,
    CycleError,
    DuplicateParameterError,
    FamilyDefinition,
    FamilyError,
    FamilyInstance,
    FamilyType,
    FormulaError,
    Parameter,
    SharedParameter,
    Transform,
    UnknownParameterError,
    VALID_PARAMETER_KINDS,
    VALID_SHARED_SCOPES,
    evaluate_formula,
    extract_referenced_names,
    family_from_dict,
    family_to_dict,
    identity_transform,
    instance_from_dict,
    instance_to_dict,
    make_family,
    make_instance,
    make_parameter,
    make_type,
    resolve_instance,
    resolve_parameters,
    resolve_type,
    topo_sort,
    type_from_dict,
    type_to_dict,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _door_family() -> FamilyDefinition:
    """A canonical 'Door' family for the contract tests."""
    return make_family(
        name="Door",
        category="Door",
        type_parameters=[
            Parameter("width",  "length", default=900.0),
            Parameter("height", "length", default=2100.0),
            Parameter("panel_thickness", "length", default=45.0),
        ],
        instance_parameters=[
            Parameter("frame_material", "material", default="oak"),
            Parameter("hardware",       "string",   default="standard"),
            Parameter("flipped",        "boolean",  default=False),
        ],
        description="Single-leaf door",
    )


# ---------------------------------------------------------------------------
# 1. Parameter kinds & validation
# ---------------------------------------------------------------------------


def test_valid_parameter_kinds_are_frozen():
    assert VALID_PARAMETER_KINDS == frozenset(
        {"integer", "float", "string", "length", "angle", "boolean", "material"}
    )


def test_unknown_parameter_kind_raises():
    with pytest.raises(FamilyError, match="unknown kind"):
        Parameter(name="bad", kind="vector", default=0.0)  # type: ignore[arg-type]


def test_parameter_kind_default_mismatch_integer():
    # bool is NOT a valid integer default — must be a real int.
    with pytest.raises(FamilyError, match="integer"):
        Parameter(name="n", kind="integer", default=True)


def test_parameter_kind_default_mismatch_string():
    with pytest.raises(FamilyError, match="string"):
        Parameter(name="s", kind="string", default=42)


def test_parameter_kind_default_mismatch_boolean():
    with pytest.raises(FamilyError, match="boolean"):
        Parameter(name="b", kind="boolean", default="yes")


def test_parameter_kind_default_mismatch_material():
    with pytest.raises(FamilyError, match="material"):
        Parameter(name="m", kind="material", default=12345)


def test_parameter_length_accepts_int_and_float():
    Parameter(name="a", kind="length", default=5)
    Parameter(name="b", kind="length", default=5.5)


def test_parameter_empty_name_rejected():
    with pytest.raises(FamilyError, match="non-empty"):
        Parameter(name="", kind="float", default=0.0)


def test_make_parameter_supplies_kind_default():
    p = make_parameter("w", kind="length")
    assert p.default == 0.0
    p2 = make_parameter("flag", kind="boolean")
    assert p2.default is False
    p3 = make_parameter("name", kind="string")
    assert p3.default == ""


# ---------------------------------------------------------------------------
# 2. Family construction
# ---------------------------------------------------------------------------


def test_family_basic_door():
    fam = _door_family()
    assert fam.name == "Door"
    assert fam.category == "Door"
    assert set(fam.type_parameters) == {"width", "height", "panel_thickness"}
    assert set(fam.instance_parameters) == {"frame_material", "hardware", "flipped"}
    assert fam.id  # uuid auto-assigned


def test_family_rejects_type_instance_name_collision():
    with pytest.raises(DuplicateParameterError):
        make_family(
            name="Bad",
            category="Generic",
            type_parameters=[Parameter("x", "float", 0.0)],
            instance_parameters=[Parameter("x", "float", 0.0)],
        )


def test_family_rejects_empty_name():
    with pytest.raises(FamilyError, match="family name"):
        FamilyDefinition(name="", category="Door")


def test_family_rejects_empty_category():
    with pytest.raises(FamilyError, match="category"):
        FamilyDefinition(name="X", category="")


def test_family_parameter_lookup():
    fam = _door_family()
    assert fam.parameter("width").kind == "length"
    assert fam.parameter("hardware").kind == "string"
    with pytest.raises(UnknownParameterError):
        fam.parameter("nope")


# ---------------------------------------------------------------------------
# 3. Types & instances
# ---------------------------------------------------------------------------


def test_type_uses_subset_of_type_params():
    fam = _door_family()
    t = make_type(fam, "36x80", {"width": 914.0, "height": 2032.0})
    assert t.type_param_values == {"width": 914.0, "height": 2032.0}


def test_type_rejects_unknown_param():
    fam = _door_family()
    with pytest.raises(UnknownParameterError, match="unknown type parameter"):
        make_type(fam, "bad", {"colour": "blue"})


def test_instance_default_resolution():
    fam = _door_family()
    t = make_type(fam, "default", {})
    i = make_instance(t)
    resolved = resolve_instance(i)
    assert resolved["width"] == 900.0
    assert resolved["height"] == 2100.0
    assert resolved["panel_thickness"] == 45.0
    assert resolved["frame_material"] == "oak"
    assert resolved["hardware"] == "standard"
    assert resolved["flipped"] is False


def test_instance_override_beats_type_default():
    fam = _door_family()
    t = make_type(fam, "wide", {"width": 1200.0})
    i = make_instance(t, instance_param_values={"frame_material": "walnut"})
    r = resolve_instance(i)
    assert r["width"] == 1200.0          # from type
    assert r["frame_material"] == "walnut"  # from instance
    assert r["height"] == 2100.0         # family default


def test_instance_override_beats_type_for_same_key():
    """Instance overrides may target type parameters (Revit semantics)."""
    fam = _door_family()
    t = make_type(fam, "wide", {"width": 1200.0})
    i = make_instance(t, instance_param_values={"width": 950.0})
    r = resolve_instance(i)
    assert r["width"] == 950.0


def test_family_default_when_neither_instance_nor_type_set():
    fam = _door_family()
    t = make_type(fam, "blank", {})
    i = make_instance(t)
    r = resolve_instance(i)
    assert r["height"] == 2100.0


def test_instance_rejects_unknown_parameter_override():
    fam = _door_family()
    t = make_type(fam, "x", {})
    with pytest.raises(UnknownParameterError):
        make_instance(t, instance_param_values={"colour": "red"})


# ---------------------------------------------------------------------------
# 4. Formula support
# ---------------------------------------------------------------------------


def test_formula_simple_product():
    fam = make_family(
        name="Box",
        category="Generic",
        type_parameters=[
            Parameter("width",  "length", default=1.0),
            Parameter("height", "length", default=2.0),
            Parameter("unit_price", "float", default=10.0),
            Parameter("cost", "float", default=0.0, formula="width * height * unit_price"),
        ],
    )
    t = make_type(fam, "default", {"width": 3.0, "height": 4.0, "unit_price": 5.0})
    i = make_instance(t)
    r = resolve_instance(i)
    assert r["cost"] == pytest.approx(3.0 * 4.0 * 5.0)


def test_formula_cycle_detected():
    with pytest.raises(CycleError):
        fam = make_family(
            name="Bad",
            category="Generic",
            type_parameters=[
                Parameter("a", "float", default=0.0, formula="b + 1"),
                Parameter("b", "float", default=0.0, formula="a + 1"),
            ],
        )
        t = make_type(fam, "x", {})
        resolve_instance(make_instance(t))


def test_formula_topo_sort_independent_of_declaration_order():
    """Define c=b+1, b=a+1, a=2 in mixed order; resolver still works."""
    fam = make_family(
        name="Chain",
        category="Generic",
        type_parameters=[
            Parameter("c", "float", default=0.0, formula="b + 1"),
            Parameter("a", "float", default=2.0),
            Parameter("b", "float", default=0.0, formula="a + 1"),
        ],
    )
    t = make_type(fam, "x", {})
    r = resolve_instance(make_instance(t))
    assert r["a"] == 2.0
    assert r["b"] == 3.0
    assert r["c"] == 4.0


def test_formula_overrides_explicit_value():
    """A param with a formula ignores any layer value supplied for it."""
    fam = make_family(
        name="X",
        category="Generic",
        type_parameters=[
            Parameter("base", "float", default=10.0),
            Parameter("derived", "float", default=0.0, formula="base * 2"),
        ],
    )
    # Instance tries to override 'derived' — but the formula must win.
    t = make_type(fam, "x", {"derived": 999.0})
    i = make_instance(t, instance_param_values={"derived": 777.0})
    r = resolve_instance(i)
    assert r["derived"] == 20.0


def test_formula_uses_math_function():
    fam = make_family(
        name="Trig",
        category="Generic",
        type_parameters=[
            Parameter("theta", "angle", default=0.0),
            Parameter("y", "float", default=0.0, formula="sin(theta)"),
        ],
    )
    t = make_type(fam, "x", {"theta": math.pi / 2})
    r = resolve_instance(make_instance(t))
    assert r["y"] == pytest.approx(1.0)


def test_formula_division_by_zero_at_resolve_time():
    fam = make_family(
        name="Div",
        category="Generic",
        type_parameters=[
            Parameter("a", "float", default=1.0),
            Parameter("b", "float", default=0.0, formula="1 / a"),
        ],
    )
    t = make_type(fam, "z", {"a": 0.0})
    with pytest.raises(FormulaError, match="evaluation error"):
        resolve_instance(make_instance(t))


# ---------------------------------------------------------------------------
# 5. AST safety
# ---------------------------------------------------------------------------


def test_formula_rejects_import():
    with pytest.raises(FamilyError):
        Parameter("x", "float", default=0.0, formula="__import__('os').system('id')")


def test_formula_rejects_eval_call():
    with pytest.raises(FamilyError):
        Parameter("x", "float", default=0.0, formula="eval('1+1')")


def test_formula_rejects_lambda():
    with pytest.raises(FamilyError):
        Parameter("x", "float", default=0.0, formula="(lambda y: y)(1)")


def test_formula_rejects_attribute_access():
    with pytest.raises(FamilyError):
        Parameter("x", "float", default=0.0, formula="(1).__class__")


def test_formula_rejects_subscript():
    with pytest.raises(FamilyError):
        Parameter("x", "float", default=0.0, formula="(1,2)[0]")


def test_formula_rejects_unknown_function():
    with pytest.raises(FamilyError):
        Parameter("x", "float", default=0.0, formula="open('/etc/passwd')")


def test_formula_rejects_syntax_error():
    with pytest.raises(FamilyError, match="syntax"):
        Parameter("x", "float", default=0.0, formula="1 + + + +")


def test_evaluate_formula_direct_safe_ok():
    assert evaluate_formula("1 + 2 * 3", {}) == 7
    assert evaluate_formula("sqrt(a)", {"a": 16}) == 4.0
    assert evaluate_formula("max(a, b)", {"a": 2, "b": 7}) == 7


def test_evaluate_formula_unknown_name_raises():
    with pytest.raises(FormulaError, match="unknown name"):
        evaluate_formula("a + b", {"a": 1})


def test_evaluate_formula_empty_raises():
    with pytest.raises(FormulaError, match="empty"):
        evaluate_formula("", {})


def test_evaluate_formula_keyword_arg_rejected():
    with pytest.raises(FormulaError):
        evaluate_formula("round(1.5, ndigits=1)", {})


def test_formula_ternary_supported():
    assert evaluate_formula("a if a > b else b", {"a": 5, "b": 3}) == 5
    assert evaluate_formula("a if a > b else b", {"a": 1, "b": 3}) == 3


# ---------------------------------------------------------------------------
# 6. Topo sort + extract refs
# ---------------------------------------------------------------------------


def test_topo_sort_simple():
    order = topo_sort({"a": [], "b": ["a"], "c": ["b"]})
    assert order.index("a") < order.index("b") < order.index("c")


def test_topo_sort_cycle_raises():
    with pytest.raises(CycleError):
        topo_sort({"a": ["b"], "b": ["a"]})


def test_extract_referenced_names_skips_safe_names():
    refs = extract_referenced_names("sin(pi * width) + height * 2")
    assert refs == {"width", "height"}


def test_extract_referenced_names_handles_syntax_error():
    # Returns empty set on parse failure — error surfaces later.
    assert extract_referenced_names("1 +") == set()


# ---------------------------------------------------------------------------
# 7. Shared parameters
# ---------------------------------------------------------------------------


def test_shared_parameter_validation():
    with pytest.raises(FamilyError, match="scope"):
        SharedParameter(name="region", kind="string", scope="weird", default="EU")  # type: ignore[arg-type]


def test_shared_parameter_scopes_frozen():
    assert VALID_SHARED_SCOPES == frozenset({"project", "global"})


def test_shared_parameter_resolves_in_formula():
    sp = SharedParameter(name="unit_price", kind="float", scope="project", default=1.0)
    fam = make_family(
        name="Priced",
        category="Generic",
        type_parameters=[
            Parameter("qty", "integer", default=2),
            Parameter("total", "float", default=0.0, formula="qty * unit_price"),
        ],
        shared_parameters=[sp],
    )
    t = make_type(fam, "x", {})
    r = resolve_instance(make_instance(t), shared_values={"unit_price": 17.5})
    assert r["total"] == pytest.approx(2 * 17.5)


def test_shared_parameter_resolves_identically_across_families():
    """Two distinct families with the same shared param + same shared
    value resolve to the same downstream effect."""
    sp = SharedParameter(name="floor_height", kind="length", scope="project", default=3000.0)
    fam_a = make_family(
        name="WallA", category="Wall",
        type_parameters=[Parameter("h", "length", default=0.0, formula="floor_height")],
        shared_parameters=[sp],
    )
    fam_b = make_family(
        name="WallB", category="Wall",
        type_parameters=[Parameter("h", "length", default=0.0, formula="floor_height")],
        shared_parameters=[sp],
    )
    ra = resolve_instance(make_instance(make_type(fam_a, "x", {})),
                          shared_values={"floor_height": 2700.0})
    rb = resolve_instance(make_instance(make_type(fam_b, "x", {})),
                          shared_values={"floor_height": 2700.0})
    assert ra["h"] == rb["h"] == 2700.0


def test_shared_parameter_default_used_when_value_absent():
    sp = SharedParameter(name="region", kind="string", scope="global", default="EU")
    fam = make_family(
        name="X",
        category="Generic",
        type_parameters=[Parameter("a", "integer", default=1)],
        shared_parameters=[sp],
    )
    # No shared_values supplied: formula references still bind to the default.
    r = resolve_instance(make_instance(make_type(fam, "t", {})))
    assert r == {"a": 1}


# ---------------------------------------------------------------------------
# 8. Serialization round-trip
# ---------------------------------------------------------------------------


def test_family_round_trip_serialize():
    fam = _door_family()
    d = family_to_dict(fam)
    assert d["schema"] == SCHEMA
    assert d["version"] == SCHEMA_VERSION
    fam2 = family_from_dict(d)
    assert fam2.id == fam.id
    assert fam2.name == fam.name
    assert fam2.category == fam.category
    assert set(fam2.type_parameters) == set(fam.type_parameters)
    assert set(fam2.instance_parameters) == set(fam.instance_parameters)
    for k, p in fam.type_parameters.items():
        p2 = fam2.type_parameters[k]
        assert p2.kind == p.kind
        assert p2.default == p.default


def test_family_round_trip_with_formula_and_shared():
    fam = make_family(
        name="Beam",
        category="Beam",
        type_parameters=[
            Parameter("length", "length", default=3000.0),
            Parameter("section", "string", default="IPE200"),
            Parameter("weight", "float", default=0.0, formula="length * 0.022"),
        ],
        instance_parameters=[
            Parameter("steel", "material", default="S355"),
        ],
        shared_parameters=[SharedParameter("design_load", "float", "project", 1.0)],
        description="Steel I-beam family",
    )
    d = family_to_dict(fam)
    fam2 = family_from_dict(d)
    # Resolve from the deserialized family and compare.
    t = make_type(fam2, "default", {})
    r = resolve_instance(make_instance(t))
    assert r["weight"] == pytest.approx(3000.0 * 0.022)
    assert r["steel"] == "S355"
    assert "design_load" in fam2.shared_parameters


def test_type_instance_round_trip():
    fam = _door_family()
    t = make_type(fam, "wide", {"width": 1200.0})
    i = make_instance(
        t,
        instance_param_values={"frame_material": "walnut"},
        transform=Transform.from_translation(1.0, 2.0, 3.0),
    )
    td = type_to_dict(t)
    id_ = instance_to_dict(i)
    t2 = type_from_dict(td, fam)
    i2 = instance_from_dict(id_, t2)
    assert t2.name == "wide"
    assert t2.type_param_values == {"width": 1200.0}
    assert i2.id == i.id
    assert i2.instance_param_values == {"frame_material": "walnut"}
    # Translation column survived.
    assert i2.transform.as_list()[0][3] == 1.0
    assert i2.transform.as_list()[1][3] == 2.0
    assert i2.transform.as_list()[2][3] == 3.0


def test_family_from_dict_rejects_bad_schema():
    bad = {"schema": "kerf.bim.wrong", "version": 1, "name": "X", "category": "Y"}
    with pytest.raises(FamilyError, match="schema"):
        family_from_dict(bad)


def test_family_from_dict_rejects_bad_version():
    bad = {"schema": SCHEMA, "version": 99, "name": "X", "category": "Y"}
    with pytest.raises(FamilyError, match="version"):
        family_from_dict(bad)


def test_family_from_dict_rejects_missing_fields():
    with pytest.raises(FamilyError, match="name"):
        family_from_dict({"schema": SCHEMA, "version": 1, "category": "x"})


def test_family_from_dict_ignores_unknown_keys():
    fam = _door_family()
    d = family_to_dict(fam)
    d["future_field"] = {"forward": "compat"}
    fam2 = family_from_dict(d)
    assert fam2.name == fam.name


# ---------------------------------------------------------------------------
# 9. Transform
# ---------------------------------------------------------------------------


def test_identity_transform():
    t = identity_transform()
    rows = t.as_list()
    assert rows[0] == [1.0, 0.0, 0.0, 0.0]
    assert rows[3] == [0.0, 0.0, 0.0, 1.0]


def test_transform_from_translation():
    t = Transform.from_translation(10.0, 20.0, 30.0)
    rows = t.as_list()
    assert rows[0][3] == 10.0
    assert rows[1][3] == 20.0
    assert rows[2][3] == 30.0


def test_transform_from_list_rejects_wrong_size():
    with pytest.raises(FamilyError, match="4x4"):
        Transform.from_list([[1, 0, 0], [0, 1, 0], [0, 0, 1]])


# ---------------------------------------------------------------------------
# 10. resolve_type & helpers
# ---------------------------------------------------------------------------


def test_resolve_type_returns_canonical_values():
    fam = _door_family()
    t = make_type(fam, "wide", {"width": 1200.0})
    r = resolve_type(t)
    assert r["width"] == 1200.0
    assert r["height"] == 2100.0
    # Instance params fall back to family defaults.
    assert r["frame_material"] == "oak"


def test_resolve_parameters_direct():
    """Lower-level entry point exposed for downstream BIM modules."""
    params = {
        "a": Parameter("a", "float", default=2.0),
        "b": Parameter("b", "float", default=0.0, formula="a * 3"),
    }
    out = resolve_parameters(params, {})
    assert out == {"a": 2.0, "b": 6.0}


def test_unknown_override_at_resolution_raises():
    fam = _door_family()
    t = make_type(fam, "x", {})
    # Bypass make_instance's check by mutating the dict directly:
    i = make_instance(t)
    i.instance_param_values["totally_unknown"] = 1
    with pytest.raises(UnknownParameterError):
        resolve_instance(i)


# ---------------------------------------------------------------------------
# 11. Contract sanity — exports
# ---------------------------------------------------------------------------


def test_public_surface_exports_required_names():
    """The CONTRACT guarantees these names are importable from the package."""
    from kerf_bim import family as fam_mod
    for name in [
        "FamilyDefinition", "FamilyType", "FamilyInstance",
        "Parameter", "SharedParameter", "Transform",
        "make_family", "make_type", "make_instance",
        "resolve_instance", "resolve_type",
        "family_to_dict", "family_from_dict",
        "evaluate_formula", "FormulaError", "CycleError",
        "FamilyError", "UnknownParameterError", "DuplicateParameterError",
        "VALID_PARAMETER_KINDS", "VALID_SHARED_SCOPES",
        "SCHEMA", "SCHEMA_VERSION",
    ]:
        assert hasattr(fam_mod, name), f"missing public export: {name}"
