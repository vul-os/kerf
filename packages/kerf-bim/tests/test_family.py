"""
test_family.py — Tests for the GDL-replacement Family Editor.

Covers:
- All 10 starter families load without error
- Door 800 mm wide instantiates with two swung halves (double swing)
- Single swing door formula evaluation (panel_width = width - 2*frame_thickness)
- validate_family catches bad formula references
- validate_family catches bad formula syntax
- validate_family passes for all 10 starter families
- FamilyParameter type / min / max / choices validation
- Boolean parameter toggle (toilet ADA compliance)
- Window pane formula (choice parameter driving division)
"""
from __future__ import annotations

import pytest

from kerf_bim.family_editor import (
    FamilyDef,
    FamilyEditorError,
    FamilyFormula,
    FamilyFormulaError,
    FamilyParameter,
    instantiate_family,
    validate_family,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def door_single():
    from kerf_bim.families.door_single_swing import family_def
    return family_def


@pytest.fixture
def door_double():
    from kerf_bim.families.door_double_swing import family_def
    return family_def


@pytest.fixture
def all_starter_families():
    from kerf_bim.families import ALL_STARTER_FAMILIES
    return ALL_STARTER_FAMILIES


# ── Test 1: all 10 starter families load without error ────────────────────────

def test_all_10_starter_families_import():
    """All 10 starter family modules must be importable."""
    from kerf_bim.families import (
        cabinet_base,
        chair_dining,
        desk_office,
        door_double_swing,
        door_single_swing,
        kitchen_sink_single,
        light_pendant,
        toilet_standard,
        window_casement,
        window_sliding,
    )
    families = [
        door_single_swing,
        door_double_swing,
        window_casement,
        window_sliding,
        cabinet_base,
        chair_dining,
        desk_office,
        light_pendant,
        toilet_standard,
        kitchen_sink_single,
    ]
    assert len(families) == 10
    for fdef in families:
        assert isinstance(fdef, FamilyDef)
        assert fdef.name
        assert fdef.category in FamilyDef.VALID_CATEGORIES


def test_all_starter_families_are_10(all_starter_families):
    assert len(all_starter_families) == 10


def test_all_starter_families_have_unique_names(all_starter_families):
    names = [f.name for f in all_starter_families]
    assert len(names) == len(set(names)), "duplicate family names"


# ── Test 2: single swing door 800 mm wide ─────────────────────────────────────

def test_door_single_swing_800mm(door_single):
    """Single swing door 800 mm wide — panel_width = 800 - 2*70 = 660 mm."""
    result = instantiate_family(door_single, {"width": 800.0})
    assert result["panel"]["width_mm"] == pytest.approx(660.0)


def test_door_single_swing_default_params(door_single):
    result = instantiate_family(door_single)
    assert result["family"] == "Single Swing Door"
    assert result["category"] == "door"
    assert result["panel"]["width_mm"] == pytest.approx(900.0 - 2 * 70.0)


def test_door_single_swing_swing_angle(door_single):
    """swing_angle = 90 → tip_y ≈ panel_width (sin 90° = 1)."""
    import math
    result = instantiate_family(door_single, {"width": 900.0, "swing_angle": 90.0})
    panel_w = 900.0 - 2 * 70.0
    assert result["panel"]["tip_offset_y_mm"] == pytest.approx(panel_w, rel=1e-4)


# ── Test 3: double swing door 800 mm wide → two swung halves ─────────────────

def test_door_double_swing_800mm_two_halves(door_double):
    """800 mm wide double door → each leaf is (800 - 2*70 - 4)/2 = 328 mm."""
    result = instantiate_family(door_double, {"width": 800.0})
    expected_leaf = (800.0 - 2 * 70.0 - 4.0) / 2
    assert result["left_leaf"]["width_mm"] == pytest.approx(expected_leaf)
    assert result["right_leaf"]["width_mm"] == pytest.approx(expected_leaf)


def test_door_double_swing_has_both_leaves(door_double):
    result = instantiate_family(door_double, {"width": 1800.0})
    assert "left_leaf" in result
    assert "right_leaf" in result
    assert result["left_leaf"]["width_mm"] > 0
    assert result["right_leaf"]["width_mm"] > 0


# ── Test 4: validate_family catches bad formula reference ─────────────────────

def test_validate_catches_unknown_name_in_formula():
    fdef = FamilyDef(
        name="Bad",
        category="door",
        parameters=[FamilyParameter(name="width", type="number", default=900.0)],
        formulas=[FamilyFormula(name="derived", expression="width + unknown_var")],
    )
    errors = validate_family(fdef)
    assert len(errors) > 0
    assert any("unknown_var" in e for e in errors)


def test_validate_catches_bad_formula_syntax():
    """Formula with invalid Python syntax must be flagged at FamilyFormula construction."""
    with pytest.raises(FamilyFormulaError):
        FamilyFormula(name="bad", expression="width ==== 3 %%% 2")


def test_validate_passes_for_valid_family(door_single):
    errors = validate_family(door_single)
    assert errors == [], f"unexpected validation errors: {errors}"


def test_validate_all_starter_families_are_valid(all_starter_families):
    """All 10 starter families must pass validation."""
    for fdef in all_starter_families:
        errors = validate_family(fdef)
        assert errors == [], f"{fdef.name} has validation errors: {errors}"


# ── Test 5: FamilyParameter validation ───────────────────────────────────────

def test_family_parameter_invalid_type():
    with pytest.raises(FamilyEditorError, match="type must be one of"):
        FamilyParameter(name="x", type="blob", default=0.0)


def test_family_parameter_min_gt_max():
    with pytest.raises(FamilyEditorError, match="min.*max"):
        FamilyParameter(name="x", type="number", default=500.0, min=1000.0, max=500.0)


def test_family_parameter_choice_no_choices():
    with pytest.raises(FamilyEditorError):
        FamilyParameter(name="x", type="choice", default="a", choices=[])


def test_family_parameter_choice_default_not_in_choices():
    with pytest.raises(FamilyEditorError, match="not in choices"):
        FamilyParameter(name="x", type="choice", default="z", choices=["a", "b"])


def test_family_parameter_invalid_name():
    with pytest.raises(FamilyEditorError, match="valid identifier"):
        FamilyParameter(name="not a valid name!", type="number", default=0.0)


# ── Test 6: boolean parameter toggle (toilet ADA) ────────────────────────────

def test_toilet_ada_compliant_seat_height():
    from kerf_bim.families.toilet_standard import family_def
    non_ada = instantiate_family(family_def, {"ada_compliant": False})
    ada = instantiate_family(family_def, {"ada_compliant": True})
    assert non_ada["bowl"]["seat_height_mm"] == pytest.approx(400.0)
    assert ada["bowl"]["seat_height_mm"] == pytest.approx(480.0)


# ── Test 7: window pane formula driven by choice parameter ────────────────────

def test_casement_window_pane_width_3():
    from kerf_bim.families.window_casement import family_def
    result = instantiate_family(family_def, {"width": 1500.0, "num_panes": "3"})
    assert result["pane_width_mm"] == pytest.approx(500.0)


def test_casement_window_pane_width_1():
    from kerf_bim.families.window_casement import family_def
    result = instantiate_family(family_def, {"width": 900.0, "num_panes": "1"})
    assert result["pane_width_mm"] == pytest.approx(900.0)


# ── Test 8: duplicate parameter name in FamilyDef ────────────────────────────

def test_family_def_duplicate_param_names():
    with pytest.raises(FamilyEditorError, match="duplicate parameter"):
        FamilyDef(
            name="Dup",
            category="generic",
            parameters=[
                FamilyParameter(name="width", type="number", default=100.0),
                FamilyParameter(name="width", type="number", default=200.0),
            ],
        )


# ── Test 9: instantiate_family returns dict when no geometry script ────────────

def test_instantiate_no_script_returns_dict():
    fdef = FamilyDef(
        name="Simple",
        category="generic",
        parameters=[FamilyParameter(name="width", type="number", default=500.0)],
        formulas=[FamilyFormula(name="half", expression="width / 2")],
        geometry_script="",
    )
    result = instantiate_family(fdef, {"width": 1000.0})
    assert isinstance(result, dict)
    assert result["resolved_params"]["width"] == pytest.approx(1000.0)
    assert result["resolved_params"]["half"] == pytest.approx(500.0)


# ── Test 10: FamilyDef invalid category ───────────────────────────────────────

def test_family_def_invalid_category():
    with pytest.raises(FamilyEditorError, match="category must be one of"):
        FamilyDef(name="X", category="spaceship")
