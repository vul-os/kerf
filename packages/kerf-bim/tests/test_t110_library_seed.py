"""
Tests for the T-110 family library seed (kerf_bim.library).

Verifies the top-level kerf_bim.library re-export path and the
seed_summary provenance helper.
"""
from __future__ import annotations

import pytest
from kerf_bim.library import (
    DEFAULT_LIBRARY,
    ALL_LIBRARY_FAMILIES,
    DOMAIN_CATALOGS,
    FamilyLibrary,
    FamilyLibraryError,
    families_by_category,
    seed_summary,
)
from kerf_bim.family.family import FamilyDefinition, FamilyType, resolve_type


# ---------------------------------------------------------------------------
# T-110.1: Library re-export path resolves correctly
# ---------------------------------------------------------------------------

class TestLibraryReExport:
    def test_default_library_accessible(self):
        """DEFAULT_LIBRARY is importable from kerf_bim.library."""
        assert DEFAULT_LIBRARY is not None
        assert len(DEFAULT_LIBRARY) > 0

    def test_all_families_accessible(self):
        assert isinstance(ALL_LIBRARY_FAMILIES, list)
        assert len(ALL_LIBRARY_FAMILIES) >= 30

    def test_domain_catalogs_keys(self):
        assert "doors" in DOMAIN_CATALOGS
        assert "windows" in DOMAIN_CATALOGS
        assert "structural" in DOMAIN_CATALOGS

    def test_families_by_category(self):
        doors = families_by_category("Door")
        assert len(doors) >= 1
        assert all(f.category == "Door" for f in doors)

    def test_families_by_unknown_category(self):
        result = families_by_category("NonExistentCategory")
        assert isinstance(result, list)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# T-110.2: Seed summary provenance
# ---------------------------------------------------------------------------

class TestSeedSummary:
    def test_summary_returns_dict(self):
        s = seed_summary()
        assert isinstance(s, dict)
        assert "total_families" in s
        assert "total_types" in s
        assert "domains" in s

    def test_summary_total_matches(self):
        s = seed_summary()
        assert s["total_families"] == len(ALL_LIBRARY_FAMILIES)

    def test_summary_domains_complete(self):
        s = seed_summary()
        required = {"doors", "windows", "furniture", "plumbing", "lighting", "structural"}
        assert required.issubset(set(s["domains"]))

    def test_summary_each_domain_has_types(self):
        s = seed_summary()
        for domain, info in s["domains"].items():
            assert info["families"] >= 1, f"Domain '{domain}' has no families"
            assert info["types"] >= 1, f"Domain '{domain}' has no type presets"

    def test_every_category_has_one_valid_family(self):
        """DoD: ≥ 1 valid family per category with resolvable type."""
        for domain, catalog in DOMAIN_CATALOGS.items():
            assert len(catalog) >= 1, f"Domain '{domain}' empty"
            fam = catalog[0]
            types = getattr(fam, "_library_types", [])
            assert types, f"Family '{fam.name}' has no type presets"
            resolved = resolve_type(types[0])
            for pname in fam.type_parameters:
                assert pname in resolved

    def test_all_types_resolve(self):
        """Pytest-reproducible: every built-in type resolves cleanly."""
        for fam in ALL_LIBRARY_FAMILIES:
            for t in getattr(fam, "_library_types", []):
                resolved = resolve_type(t)
                assert isinstance(resolved, dict)
