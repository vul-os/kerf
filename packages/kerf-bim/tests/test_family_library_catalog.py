"""
Tests for the curated BIM family template catalog (T-110).

Covers:
    - Catalog completeness (40+ entries, all required categories)
    - Name lookup and KeyError semantics
    - Category filter
    - Parameter integrity for specific families
    - Chair seat_height in the 16–18 in range (406.4–457.2 mm)
    - Door templates have width and height params with valid ranges
"""
from __future__ import annotations

import pytest

from kerf_bim.family_library import (
    LIBRARY,
    FamilyCatalogError,
    FamilyLibraryCatalog,
    FamilyTemplateEntry,
    ParameterSpec,
)
from kerf_bim.family_library_data import CATALOG, CATALOG_BY_CATEGORY, CATALOG_BY_NAME


# ---------------------------------------------------------------------------
# Catalog completeness
# ---------------------------------------------------------------------------


def test_catalog_has_at_least_40_entries():
    assert len(CATALOG) >= 40, f"expected ≥40 entries, got {len(CATALOG)}"


def test_library_size_matches_catalog():
    assert len(LIBRARY) == len(CATALOG)


def test_required_categories_present():
    required = {"Doors", "Windows", "Walls", "Stairs", "Furniture", "Plumbing", "HVAC", "Lighting"}
    assert required <= set(LIBRARY.categories()), (
        f"Missing categories: {required - set(LIBRARY.categories())}"
    )


def test_minimum_entries_per_category():
    minimums = {
        "Doors":     5,
        "Windows":   6,
        "Walls":     6,
        "Stairs":    4,
        "Furniture": 5,
        "Plumbing":  6,
        "HVAC":      4,
        "Lighting":  4,
    }
    counts = LIBRARY.category_counts()
    for cat, minimum in minimums.items():
        assert counts.get(cat, 0) >= minimum, (
            f"Category {cat!r}: expected ≥{minimum}, got {counts.get(cat, 0)}"
        )


def test_all_names_unique():
    names = [e.name for e in CATALOG]
    assert len(names) == len(set(names)), "Family names in catalog must be unique"


def test_all_entries_have_name_and_category():
    for entry in CATALOG:
        assert entry.name, "Every entry must have a non-empty name"
        assert entry.category, "Every entry must have a non-empty category"


def test_all_entries_have_at_least_one_parameter():
    for entry in CATALOG:
        assert entry.parameters, f"{entry.name!r} has no parameters"


def test_all_entries_have_generator_module():
    for entry in CATALOG:
        assert entry.generator_module, f"{entry.name!r} has no generator_module"
        # Must look like a dotted Python path
        assert "." in entry.generator_module, (
            f"{entry.name!r} generator_module {entry.generator_module!r} "
            f"must be a dotted module path"
        )


# ---------------------------------------------------------------------------
# Registry / lookup semantics
# ---------------------------------------------------------------------------


def test_lookup_by_name_single_leaf_door():
    entry = LIBRARY.get("Single-Leaf Door")
    assert isinstance(entry, FamilyTemplateEntry)
    assert entry.category == "Doors"


def test_lookup_by_name_missing_raises():
    with pytest.raises(FamilyCatalogError):
        LIBRARY.get("No Such Family XYZ")


def test_contains_existing():
    assert LIBRARY.contains("Single-Leaf Door")


def test_contains_missing():
    assert not LIBRARY.contains("Nonexistent Family")


def test_duplicate_name_rejected():
    dup = CATALOG[0]
    with pytest.raises(FamilyCatalogError):
        FamilyLibraryCatalog([dup, dup])


def test_catalog_by_name_dict():
    assert "Toilet" in CATALOG_BY_NAME
    assert CATALOG_BY_NAME["Toilet"].category == "Plumbing"


def test_catalog_by_category_dict():
    assert "Doors" in CATALOG_BY_CATEGORY
    door_names = {e.name for e in CATALOG_BY_CATEGORY["Doors"]}
    assert "Single-Leaf Door" in door_names


# ---------------------------------------------------------------------------
# Category filter
# ---------------------------------------------------------------------------


def test_by_category_doors():
    doors = LIBRARY.by_category("Doors")
    assert len(doors) >= 5
    assert all(e.category == "Doors" for e in doors)


def test_by_category_windows():
    windows = LIBRARY.by_category("Windows")
    assert len(windows) >= 6
    assert all(e.category == "Windows" for e in windows)


def test_by_category_walls():
    walls = LIBRARY.by_category("Walls")
    assert len(walls) >= 6
    assert all(e.category == "Walls" for e in walls)


def test_by_category_hvac():
    hvac = LIBRARY.by_category("HVAC")
    assert len(hvac) >= 4
    assert all(e.category == "HVAC" for e in hvac)


def test_by_category_empty_for_unknown():
    result = LIBRARY.by_category("NonexistentCategory")
    assert result == []


def test_categories_returns_sorted():
    cats = LIBRARY.categories()
    assert cats == sorted(cats)


# ---------------------------------------------------------------------------
# Door parameter integrity
# ---------------------------------------------------------------------------


def test_single_leaf_door_has_width_and_height():
    entry = LIBRARY.get("Single-Leaf Door")
    assert "width" in entry.parameters, "Single-Leaf Door must have a 'width' parameter"
    assert "height" in entry.parameters, "Single-Leaf Door must have a 'height' parameter"


def test_door_width_param_has_range():
    entry = LIBRARY.get("Single-Leaf Door")
    width = entry.parameters["width"]
    assert isinstance(width, ParameterSpec)
    assert width.range is not None, "Door width must have a [min, max] range"
    lo, hi = width.range
    assert lo < hi, "Width range min must be less than max"
    assert lo > 0, "Width range min must be positive"


def test_door_height_param_has_range():
    entry = LIBRARY.get("Single-Leaf Door")
    height = entry.parameters["height"]
    assert height.range is not None, "Door height must have a [min, max] range"
    lo, hi = height.range
    assert lo < hi
    assert lo > 0


def test_all_door_families_have_width_and_height():
    for entry in LIBRARY.by_category("Doors"):
        assert "width" in entry.parameters, (
            f"Door {entry.name!r} must have 'width'"
        )
        assert "height" in entry.parameters, (
            f"Door {entry.name!r} must have 'height'"
        )


def test_door_default_width_within_range():
    for entry in LIBRARY.by_category("Doors"):
        w = entry.parameters["width"]
        if w.range is not None:
            lo, hi = w.range
            assert lo <= w.default <= hi, (
                f"{entry.name} width default {w.default} outside range [{lo}, {hi}]"
            )


def test_door_default_height_within_range():
    for entry in LIBRARY.by_category("Doors"):
        h = entry.parameters["height"]
        if h.range is not None:
            lo, hi = h.range
            assert lo <= h.default <= hi, (
                f"{entry.name} height default {h.default} outside range [{lo}, {hi}]"
            )


# ---------------------------------------------------------------------------
# Chair seat_height: 16–18 inches (406.4–457.2 mm)
# ---------------------------------------------------------------------------

# 1 inch = 25.4 mm exactly
_IN_TO_MM = 25.4
_SEAT_HEIGHT_MIN_MM = 16 * _IN_TO_MM   # 406.4 mm
_SEAT_HEIGHT_MAX_MM = 18 * _IN_TO_MM   # 457.2 mm


def test_task_chair_has_seat_height_param():
    chair = LIBRARY.get("Task Chair")
    assert "seat_height" in chair.parameters, "Task Chair must have a 'seat_height' parameter"


def test_task_chair_seat_height_default_in_range():
    chair = LIBRARY.get("Task Chair")
    sh = chair.parameters["seat_height"]
    assert _SEAT_HEIGHT_MIN_MM <= sh.default <= _SEAT_HEIGHT_MAX_MM, (
        f"Task Chair seat_height default {sh.default} mm is outside "
        f"16–18 in ({_SEAT_HEIGHT_MIN_MM}–{_SEAT_HEIGHT_MAX_MM} mm)"
    )


def test_task_chair_seat_height_range_covers_16_to_18_inches():
    chair = LIBRARY.get("Task Chair")
    sh = chair.parameters["seat_height"]
    assert sh.range is not None, "Task Chair seat_height must declare a range"
    lo, hi = sh.range
    # The declared range must span 16–18 in
    assert lo <= _SEAT_HEIGHT_MIN_MM, (
        f"seat_height range lower bound {lo} is above 16 in ({_SEAT_HEIGHT_MIN_MM} mm)"
    )
    assert hi >= _SEAT_HEIGHT_MAX_MM, (
        f"seat_height range upper bound {hi} is below 18 in ({_SEAT_HEIGHT_MAX_MM} mm)"
    )


# ---------------------------------------------------------------------------
# ParameterSpec integrity
# ---------------------------------------------------------------------------


def test_all_numeric_params_with_range_have_valid_bounds():
    numeric_kinds = {"length", "float", "integer", "angle"}
    for entry in CATALOG:
        for pname, spec in entry.parameters.items():
            if spec.range is not None and spec.type in numeric_kinds:
                lo, hi = spec.range
                assert lo <= hi, (
                    f"{entry.name}/{pname}: range [{lo}, {hi}] has lo > hi"
                )


def test_all_numeric_params_have_numeric_default():
    numeric_kinds = {"length", "float", "integer", "angle"}
    for entry in CATALOG:
        for pname, spec in entry.parameters.items():
            if spec.type in numeric_kinds:
                assert isinstance(spec.default, (int, float)) and not isinstance(spec.default, bool), (
                    f"{entry.name}/{pname}: expected numeric default, got {spec.default!r}"
                )


def test_boolean_params_have_bool_default():
    for entry in CATALOG:
        for pname, spec in entry.parameters.items():
            if spec.type == "boolean":
                assert isinstance(spec.default, bool), (
                    f"{entry.name}/{pname}: boolean param default must be bool"
                )


def test_string_params_have_str_default():
    for entry in CATALOG:
        for pname, spec in entry.parameters.items():
            if spec.type == "string":
                assert isinstance(spec.default, str), (
                    f"{entry.name}/{pname}: string param default must be str"
                )


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_search_returns_matching_entries():
    results = LIBRARY.search("door")
    assert len(results) >= 5
    for e in results:
        assert "door" in e.name.lower() or "door" in e.description.lower()


def test_search_no_results():
    assert LIBRARY.search("xyzzy_no_match_12345") == []
