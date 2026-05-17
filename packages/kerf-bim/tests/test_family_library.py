"""Verification suite for the cold-start BIM family library (T-110).

Asserts catalog completeness, registry lookup semantics, parameter
integrity, and that every built-in FamilyType resolves cleanly through
the frozen family resolution layer.
"""
from __future__ import annotations

import pytest

from kerf_bim.family.family import FamilyDefinition, FamilyType, resolve_type
from kerf_bim.family.library import (
    ALL_DOOR_FAMILIES,
    ALL_FURNITURE_FAMILIES,
    ALL_LIBRARY_FAMILIES,
    ALL_LIGHTING_FAMILIES,
    ALL_PLUMBING_FAMILIES,
    ALL_STRUCTURAL_FAMILIES,
    ALL_WINDOW_FAMILIES,
    DEFAULT_LIBRARY,
    DOMAIN_CATALOGS,
    FamilyLibrary,
    FamilyLibraryError,
)


# ---------------------------------------------------------------------------
# Catalog completeness
# ---------------------------------------------------------------------------


def test_every_domain_catalog_present():
    assert set(DOMAIN_CATALOGS) == {
        "doors", "windows", "furniture", "plumbing", "lighting", "structural",
    }
    for catalog in DOMAIN_CATALOGS.values():
        assert len(catalog) >= 6
        assert all(isinstance(f, FamilyDefinition) for f in catalog)


def test_aggregate_is_sum_of_domains():
    total = sum(len(c) for c in DOMAIN_CATALOGS.values())
    assert len(ALL_LIBRARY_FAMILIES) == total
    assert len(DEFAULT_LIBRARY) == total


def test_new_domains_landed():
    # The four domains added in the T-110 completion pass.
    for catalog in (
        ALL_FURNITURE_FAMILIES,
        ALL_PLUMBING_FAMILIES,
        ALL_LIGHTING_FAMILIES,
        ALL_STRUCTURAL_FAMILIES,
    ):
        assert len(catalog) >= 6
    # Pre-existing domains untouched.
    assert len(ALL_DOOR_FAMILIES) == 6
    assert len(ALL_WINDOW_FAMILIES) == 9


# ---------------------------------------------------------------------------
# Registry semantics
# ---------------------------------------------------------------------------


def test_family_names_unique():
    names = [f.name for f in ALL_LIBRARY_FAMILIES]
    assert len(names) == len(set(names)), "family names must be unique"


def test_get_family_roundtrip():
    fam = DEFAULT_LIBRARY.get_family("Single Swing Door")
    assert fam.category == "Door"
    assert DEFAULT_LIBRARY.get_family(fam.name) is fam


def test_get_family_missing_raises():
    with pytest.raises(FamilyLibraryError):
        DEFAULT_LIBRARY.get_family("No Such Family")


def test_categories_and_filter_consistent():
    for cat in DEFAULT_LIBRARY.categories():
        fams = DEFAULT_LIBRARY.families_in_category(cat)
        assert fams
        assert all(f.category == cat for f in fams)


def test_duplicate_family_name_rejected():
    dup = ALL_DOOR_FAMILIES[0]
    with pytest.raises(FamilyLibraryError):
        FamilyLibrary([dup, dup])


def test_get_type_lookup():
    t = DEFAULT_LIBRARY.get_type("Single Swing Door", "3-0 × 6-8")
    assert isinstance(t, FamilyType)
    with pytest.raises(FamilyLibraryError):
        DEFAULT_LIBRARY.get_type("Single Swing Door", "nonexistent")


# ---------------------------------------------------------------------------
# Parameter / type integrity
# ---------------------------------------------------------------------------


def test_every_family_has_parameters_and_types():
    for fam in ALL_LIBRARY_FAMILIES:
        assert fam.type_parameters, f"{fam.name} has no type parameters"
        lib_types = getattr(fam, "_library_types", [])
        assert lib_types, f"{fam.name} has no type presets"
        for t in lib_types:
            assert isinstance(t, FamilyType)
            assert t.definition is fam


def test_all_library_types_resolve():
    """Every preset must resolve through the frozen resolution layer."""
    pairs = DEFAULT_LIBRARY.all_types()
    assert len(pairs) >= 100
    for fam, t in pairs:
        resolved = resolve_type(t)
        # Every declared type parameter must have a resolved value.
        for pname in fam.type_parameters:
            assert pname in resolved


def test_type_preset_values_reference_declared_params():
    for fam in ALL_LIBRARY_FAMILIES:
        for t in getattr(fam, "_library_types", []):
            for pname in t.type_param_values:
                assert pname in fam.type_parameters, (
                    f"{fam.name}/{t.name}: preset sets unknown param {pname!r}"
                )
