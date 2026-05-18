"""
Tests for kerf_cad_core.materials.aerospace — certified aerospace alloys and
composites database.

Run with:
    PYTHONPATH=packages/kerf-core/src:packages/kerf-cad-core/src \
        python3 -m pytest packages/kerf-cad-core/tests/test_aerospace_materials.py -x
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.materials.aerospace import (
    aerospace_catalogue,
    all_specs,
    by_category,
    lookup,
)
from kerf_cad_core.materials.aerospace_data import AEROSPACE_DB

# ---------------------------------------------------------------------------
# Positive-only numeric fields that must never be NaN or negative
# ---------------------------------------------------------------------------

_POSITIVE_FIELDS = [
    "density_kg_m3",
    "elastic_modulus_GPa",
    "shear_modulus_GPa",
    "yield_strength_MPa",
    "ultimate_strength_MPa",
    "elongation_pct",
    "thermal_conductivity_W_mK",
    "specific_heat_J_kgK",
    "max_service_temp_C",
    "fatigue_limit_MPa",
    "fracture_toughness_K1c_MPa_sqrt_m",
]

# poisson_ratio and cte_per_K may legitimately be slightly negative
# (e.g. Kevlar longitudinal CTE), so they are excluded.

_REQUIRED_FIELDS = _POSITIVE_FIELDS + [
    "poisson_ratio",
    "cte_per_K",
    "specification",
    "description",
    "category",
    "name",
]

_EXPECTED_CATEGORIES = {
    "aluminium",
    "titanium",
    "steel",
    "nickel_superalloy",
    "composite",
    "copper_alloy",
    "magnesium",
}


# ===========================================================================
# 1. Catalogue size and category coverage
# ===========================================================================


class TestCatalogueSize:
    def test_at_least_30_entries(self):
        catalogue = aerospace_catalogue()
        assert len(catalogue) >= 30, (
            f"Expected ≥30 entries, got {len(catalogue)}"
        )

    def test_all_categories_present(self):
        catalogue = aerospace_catalogue()
        found = {e["category"] for e in catalogue}
        missing = _EXPECTED_CATEGORIES - found
        assert not missing, f"Missing categories: {missing}"

    def test_raw_db_and_catalogue_same_length(self):
        assert len(aerospace_catalogue()) == len(AEROSPACE_DB)


# ===========================================================================
# 2. Schema validation — every entry has all required fields
# ===========================================================================


class TestSchemaValidation:
    @pytest.mark.parametrize("entry", AEROSPACE_DB, ids=lambda e: e.get("name", "?"))
    def test_required_fields_present(self, entry):
        for field in _REQUIRED_FIELDS:
            assert field in entry, (
                f"{entry.get('name')!r}: missing field {field!r}"
            )

    @pytest.mark.parametrize("entry", AEROSPACE_DB, ids=lambda e: e.get("name", "?"))
    def test_no_nan_in_numeric_fields(self, entry):
        for field in _POSITIVE_FIELDS:
            val = entry.get(field)
            assert val is not None, (
                f"{entry['name']!r}: {field!r} is None"
            )
            assert math.isfinite(val), (
                f"{entry['name']!r}: {field!r} = {val!r} is not finite"
            )

    @pytest.mark.parametrize("entry", AEROSPACE_DB, ids=lambda e: e.get("name", "?"))
    def test_positive_only_fields_non_negative(self, entry):
        for field in _POSITIVE_FIELDS:
            val = entry.get(field, 0.0)
            assert val >= 0.0, (
                f"{entry['name']!r}: {field!r} = {val!r} is negative"
            )

    @pytest.mark.parametrize("entry", AEROSPACE_DB, ids=lambda e: e.get("name", "?"))
    def test_specification_non_empty(self, entry):
        spec = entry.get("specification", "")
        assert isinstance(spec, str) and spec.strip(), (
            f"{entry['name']!r}: specification is empty or not a string"
        )


# ===========================================================================
# 3. Property oracle values
# ===========================================================================


class TestPropertyOracles:
    def test_ti64_annealed_density(self):
        """Ti-6Al-4V density ≈ 4430 kg/m³ (within 1%)."""
        entry = lookup("Ti-6Al-4V annealed")
        assert entry is not None, "Ti-6Al-4V annealed not found"
        rho = entry["density_kg_m3"]
        assert abs(rho - 4430.0) / 4430.0 < 0.01, (
            f"Ti-6Al-4V density {rho} differs from 4430 by more than 1%"
        )

    def test_7075_t6_yield_strength(self):
        """7075-T6 yield ≈ 503 MPa (within 5%)."""
        entry = lookup("7075-T6")
        assert entry is not None, "7075-T6 not found"
        sy = entry["yield_strength_MPa"]
        assert abs(sy - 503.0) / 503.0 < 0.05, (
            f"7075-T6 yield {sy} differs from 503 MPa by more than 5%"
        )

    def test_inconel_718_max_service_temp(self):
        """Inconel 718 max service temperature ≈ 700 °C (within 10%)."""
        entry = lookup("Inconel 718")
        assert entry is not None, "Inconel 718 not found"
        t = entry["max_service_temp_C"]
        assert abs(t - 700.0) / 700.0 < 0.10, (
            f"Inconel 718 max_service_temp_C {t} differs from 700 by more than 10%"
        )

    def test_t300_5208_longitudinal_modulus(self):
        """T300/5208 longitudinal modulus ≈ 138 GPa (within 5%)."""
        entry = lookup("T300/5208 UD CFRP")
        assert entry is not None, "T300/5208 UD CFRP not found"
        E = entry["elastic_modulus_GPa"]
        assert abs(E - 138.0) / 138.0 < 0.05, (
            f"T300/5208 E {E} differs from 138 GPa by more than 5%"
        )

    def test_ti64_sta_higher_strength_than_annealed(self):
        """STA variant must be stronger than annealed."""
        ann = lookup("Ti-6Al-4V annealed")
        sta = lookup("Ti-6Al-4V STA")
        assert ann is not None and sta is not None
        assert sta["yield_strength_MPa"] > ann["yield_strength_MPa"]

    def test_aermet100_fracture_toughness(self):
        """AerMet 100 K1c should be notably higher than 4340."""
        aermet = lookup("AerMet 100")
        s4340 = lookup("AISI 4340 Q&T")
        assert aermet is not None and s4340 is not None
        assert aermet["fracture_toughness_K1c_MPa_sqrt_m"] > s4340["fracture_toughness_K1c_MPa_sqrt_m"]

    def test_im7_8552_higher_modulus_than_t300(self):
        """IM7/8552 intermediate modulus fibre should give higher E than T300."""
        im7 = lookup("IM7/8552 UD CFRP")
        t300 = lookup("T300/5208 UD CFRP")
        assert im7 is not None and t300 is not None
        assert im7["elastic_modulus_GPa"] > t300["elastic_modulus_GPa"]


# ===========================================================================
# 4. lookup() API
# ===========================================================================


class TestLookup:
    def test_lookup_case_insensitive(self):
        assert lookup("INCONEL 718") is not None
        assert lookup("inconel 718") is not None
        assert lookup("Inconel 718") is not None

    def test_lookup_unknown_returns_none(self):
        assert lookup("Unobtanium-X") is None

    def test_lookup_non_string_returns_none(self):
        assert lookup(None) is None  # type: ignore[arg-type]
        assert lookup(42) is None    # type: ignore[arg-type]

    def test_lookup_returns_deep_copy(self):
        a = lookup("7075-T6")
        b = lookup("7075-T6")
        assert a is not b
        a["yield_strength_MPa"] = 0.0
        c = lookup("7075-T6")
        assert c["yield_strength_MPa"] != 0.0, "lookup() must return a deep copy"


# ===========================================================================
# 5. by_category() API
# ===========================================================================


class TestByCategory:
    def test_aluminium_returns_multiple(self):
        results = by_category("aluminium")
        assert len(results) >= 5

    def test_titanium_returns_entries(self):
        results = by_category("titanium")
        assert len(results) >= 4

    def test_nickel_superalloy_returns_entries(self):
        results = by_category("nickel_superalloy")
        assert len(results) >= 5

    def test_composite_returns_entries(self):
        results = by_category("composite")
        assert len(results) >= 4

    def test_steel_returns_entries(self):
        results = by_category("steel")
        assert len(results) >= 4

    def test_unknown_category_returns_empty_list(self):
        assert by_category("unobtanium") == []

    def test_non_string_returns_empty_list(self):
        assert by_category(None) == []  # type: ignore[arg-type]

    def test_category_case_insensitive(self):
        assert by_category("ALUMINIUM") == by_category("aluminium")

    def test_all_returned_entries_have_correct_category(self):
        for cat in _EXPECTED_CATEGORIES:
            for entry in by_category(cat):
                assert entry["category"].lower() == cat.lower()


# ===========================================================================
# 6. all_specs() API
# ===========================================================================


class TestAllSpecs:
    def test_returns_list_of_strings(self):
        specs = all_specs()
        assert isinstance(specs, list)
        assert all(isinstance(s, str) for s in specs)

    def test_no_empty_strings(self):
        specs = all_specs()
        assert all(s.strip() for s in specs)

    def test_sorted(self):
        specs = all_specs()
        assert specs == sorted(specs)

    def test_unique(self):
        specs = all_specs()
        assert len(specs) == len(set(specs))

    def test_ams_specs_present_for_metals(self):
        """All metal entries (non-composite) must carry at least one AMS spec."""
        non_composite = [
            e for e in AEROSPACE_DB if e["category"] != "composite"
        ]
        for entry in non_composite:
            spec = entry.get("specification", "")
            assert "AMS" in spec, (
                f"{entry['name']!r}: non-composite entry has no AMS spec "
                f"(got {spec!r})"
            )


# ===========================================================================
# 7. aerospace_catalogue() API
# ===========================================================================


class TestAerospaceCatalogue:
    def test_returns_list(self):
        assert isinstance(aerospace_catalogue(), list)

    def test_returns_deep_copies(self):
        cat_a = aerospace_catalogue()
        cat_b = aerospace_catalogue()
        # Mutate one; the other must be unaffected
        cat_a[0]["density_kg_m3"] = 0.0
        assert cat_b[0]["density_kg_m3"] != 0.0

    def test_all_entries_have_name_and_category(self):
        for entry in aerospace_catalogue():
            assert "name" in entry and entry["name"]
            assert "category" in entry and entry["category"]
