"""
test_material_catalogue.py
==========================

Pytest suite for kerf_bim.material_catalogue (T-115).

Run with::

    PYTHONPATH=packages/kerf-core/src:packages/kerf-bim/src \\
        python3 -m pytest packages/kerf-bim/tests/test_material_catalogue.py -x
"""

from __future__ import annotations

import pytest

from kerf_bim.material_catalogue import (
    by_category,
    catalogue_size,
    lookup,
    to_pbr_dict,
)
from kerf_bim.material_catalogue_data import MaterialEntry


# ---------------------------------------------------------------------------
# 1. Catalogue completeness
# ---------------------------------------------------------------------------

class TestCatalogueCompleteness:
    def test_minimum_30_entries(self):
        """Catalogue must contain at least 30 entries (task T-115 requirement)."""
        size = catalogue_size()
        assert size >= 30, f"Only {size} entries; expected >= 30"

    def test_canonical_categories_present(self):
        """All canonical BIM categories must have at least one entry."""
        required = {
            "concrete", "brick", "masonry", "wood", "steel",
            "aluminum", "glass", "plaster", "ceramic_tile", "vinyl", "carpet",
        }
        found = set()
        for cat in required:
            if by_category(cat):
                found.add(cat)
        missing = required - found
        assert not missing, f"Categories with no entries: {missing}"

    def test_no_duplicate_names(self):
        """No two entries may share the same canonical name."""
        from kerf_bim.material_catalogue_data import _RAW
        names = [m.name.lower() for m in _RAW]
        assert len(names) == len(set(names)), "Duplicate material names detected"

    def test_all_entries_are_material_entry(self):
        """Every raw entry is a MaterialEntry dataclass instance."""
        from kerf_bim.material_catalogue_data import _RAW
        for m in _RAW:
            assert isinstance(m, MaterialEntry), f"{m!r} is not a MaterialEntry"


# ---------------------------------------------------------------------------
# 2. lookup() — case-insensitive
# ---------------------------------------------------------------------------

class TestLookup:
    def test_lookup_exact_case(self):
        mat = lookup("wood_oak")
        assert mat.name == "wood_oak"

    def test_lookup_uppercase(self):
        mat = lookup("WOOD_OAK")
        assert mat.name == "wood_oak"

    def test_lookup_mixed_case(self):
        mat = lookup("Steel_Raw_A36")
        assert mat.name == "steel_raw_a36"

    def test_lookup_with_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        mat = lookup("  glass_clear_float  ")
        assert mat.name == "glass_clear_float"

    def test_lookup_missing_raises_key_error(self):
        with pytest.raises(KeyError):
            lookup("material_that_does_not_exist_xyz")

    def test_lookup_returns_material_entry(self):
        mat = lookup("concrete_m30")
        assert isinstance(mat, MaterialEntry)


# ---------------------------------------------------------------------------
# 3. by_category()
# ---------------------------------------------------------------------------

class TestByCategory:
    def test_concrete_entries(self):
        entries = by_category("concrete")
        assert len(entries) >= 2
        for e in entries:
            assert e.category == "concrete"

    def test_glass_entries(self):
        entries = by_category("glass")
        assert len(entries) >= 3
        for e in entries:
            assert e.category == "glass"

    def test_wood_entries(self):
        entries = by_category("wood")
        assert len(entries) >= 4

    def test_sorted_by_name(self):
        entries = by_category("steel")
        names = [e.name for e in entries]
        assert names == sorted(names), "by_category result is not sorted by name"

    def test_unknown_category_returns_empty(self):
        result = by_category("completely_unknown_xyz")
        assert result == []

    def test_case_insensitive_category(self):
        """Category lookup is case-insensitive."""
        lower = by_category("brick")
        upper = by_category("BRICK")
        assert [m.name for m in lower] == [m.name for m in upper]


# ---------------------------------------------------------------------------
# 4. Physical property spot-checks
# ---------------------------------------------------------------------------

class TestPhysicalProperties:
    def test_oak_density_within_10_percent_of_750(self):
        """Published oak density ~750 kg/m³ (NDS 2018); tolerance ±10%."""
        mat = lookup("wood_oak")
        assert abs(mat.density_kg_m3 - 750.0) / 750.0 <= 0.10, (
            f"oak density {mat.density_kg_m3} kg/m³ outside ±10% of 750"
        )

    def test_steel_ior_approx_2_5(self):
        """Steel IOR ≈ 2.5 (Principled BSDF metal approximation)."""
        for name in ("steel_raw_a36", "steel_raw_s355", "steel_stainless_304"):
            mat = lookup(name)
            assert abs(mat.ior - 2.5) <= 0.2, (
                f"{name}: IOR={mat.ior}, expected ~2.5"
            )

    def test_glass_transmission_above_0_8(self):
        """Clear and tempered glass must have transmission > 0.8."""
        for name in ("glass_clear_float", "glass_tempered"):
            mat = lookup(name)
            assert mat.transmission > 0.8, (
                f"{name}: transmission={mat.transmission}, expected >0.8"
            )

    def test_glass_frosted_transmission_above_0_8(self):
        """Frosted glass still transmits (>0.8) light, just diffusely."""
        mat = lookup("glass_frosted")
        assert mat.transmission > 0.8

    def test_concrete_density_2400(self):
        """Normal-weight concrete grades M20/M30 density == 2400 kg/m³."""
        for name in ("concrete_m20", "concrete_m30"):
            mat = lookup(name)
            assert abs(mat.density_kg_m3 - 2400.0) < 1.0, (
                f"{name}: density={mat.density_kg_m3}"
            )

    def test_steel_density_7850(self):
        """Structural steel density == 7850 kg/m³ (NIST SP 1018)."""
        for name in ("steel_raw_a36", "steel_raw_s355"):
            mat = lookup(name)
            assert abs(mat.density_kg_m3 - 7850.0) < 1.0

    def test_aluminum_density_2700(self):
        """6061-T6 density == 2700 kg/m³ (ADM 2020)."""
        mat = lookup("aluminum_6061_t6")
        assert abs(mat.density_kg_m3 - 2700.0) < 10.0

    def test_carpet_low_thermal_conductivity(self):
        """Carpet thermal conductivity must be very low (< 0.1 W/(m·K))."""
        for name in ("carpet_loop_pile", "carpet_cut_pile"):
            mat = lookup(name)
            assert mat.thermal_conductivity_w_mk < 0.1, (
                f"{name}: λ={mat.thermal_conductivity_w_mk}"
            )


# ---------------------------------------------------------------------------
# 5. to_pbr_dict() — T-106a Cycles schema
# ---------------------------------------------------------------------------

class TestToPBRDict:
    _EXPECTED_KEYS = {"base_color", "metallic", "roughness", "ior", "transmission"}

    def test_schema_keys_present(self):
        """PBR dict must contain exactly the T-106a expected keys."""
        d = to_pbr_dict("steel_raw_a36")
        assert set(d.keys()) == self._EXPECTED_KEYS, (
            f"Keys mismatch: got {set(d.keys())}"
        )

    def test_base_color_is_4_tuple(self):
        """base_color must be a 4-tuple (R, G, B, alpha=1.0)."""
        d = to_pbr_dict("wood_oak")
        assert len(d["base_color"]) == 4
        assert d["base_color"][3] == 1.0

    def test_base_color_values_in_range(self):
        """All base_color components must be in [0, 1]."""
        from kerf_bim.material_catalogue_data import _RAW
        for mat in _RAW:
            d = to_pbr_dict(mat.name)
            r, g, b, a = d["base_color"]
            assert 0.0 <= r <= 1.0
            assert 0.0 <= g <= 1.0
            assert 0.0 <= b <= 1.0
            assert a == 1.0

    def test_metallic_float(self):
        d = to_pbr_dict("steel_raw_a36")
        assert isinstance(d["metallic"], float)
        assert d["metallic"] == 1.0

    def test_steel_metallic_1(self):
        """Structural steel must be fully metallic in the PBR dict."""
        d = to_pbr_dict("steel_raw_a36")
        assert d["metallic"] == 1.0

    def test_wood_metallic_0(self):
        """Wood must be non-metallic in the PBR dict."""
        d = to_pbr_dict("wood_oak")
        assert d["metallic"] == 0.0

    def test_glass_transmission_above_0_8(self):
        """Clear glass transmission > 0.8 in the PBR dict."""
        d = to_pbr_dict("glass_clear_float")
        assert d["transmission"] > 0.8

    def test_roughness_in_range(self):
        from kerf_bim.material_catalogue_data import _RAW
        for mat in _RAW:
            d = to_pbr_dict(mat.name)
            assert 0.0 <= d["roughness"] <= 1.0, (
                f"{mat.name}: roughness={d['roughness']}"
            )

    def test_ior_in_range(self):
        from kerf_bim.material_catalogue_data import _RAW
        for mat in _RAW:
            d = to_pbr_dict(mat.name)
            assert 1.0 <= d["ior"] <= 3.0, (
                f"{mat.name}: ior={d['ior']}"
            )

    def test_missing_material_raises(self):
        with pytest.raises(KeyError):
            to_pbr_dict("nonexistent_material_xyz")

    def test_case_insensitive_name(self):
        """to_pbr_dict delegates to lookup — must be case-insensitive."""
        d_lower = to_pbr_dict("wood_oak")
        d_upper = to_pbr_dict("WOOD_OAK")
        assert d_lower == d_upper


# ---------------------------------------------------------------------------
# 6. PBR sanity across the whole catalogue
# ---------------------------------------------------------------------------

class TestPBRSanityAll:
    def test_all_entries_have_valid_pbr(self):
        """Every entry must produce a valid PBR dict without error."""
        from kerf_bim.material_catalogue_data import _RAW
        for mat in _RAW:
            d = to_pbr_dict(mat.name)
            assert "base_color" in d
            assert "metallic" in d
            assert "roughness" in d
            assert "ior" in d
            assert "transmission" in d

    def test_non_metal_transmission_zero(self):
        """Non-glass, non-transmissive materials must have transmission == 0."""
        opaque_names = [
            "concrete_m30", "brick_clay_red", "wood_oak",
            "plaster_lime", "carpet_loop_pile", "vinyl_lvt",
        ]
        for name in opaque_names:
            d = to_pbr_dict(name)
            assert d["transmission"] == 0.0, (
                f"{name}: expected transmission=0, got {d['transmission']}"
            )
