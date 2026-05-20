"""
Tests for kerf_textiles.materials (T-286) and kerf_textiles.sustainability (T-286).

Oracles
-------
- Catalogue has 50+ entries
- Lookup by category works for every defined category
- by_id works and raises KeyError for unknown IDs
- Physical properties are positive-valued
- LCA sustainability score is in [0, 100]
- Weighted mass fractions produce correct absolute CO₂/water totals
- All-organic garment outscores all-synthetic garment
- Fraction validation raises ValueError
- Single-material garment score matches direct analytic calculation
"""

from __future__ import annotations

import math
import pytest

from kerf_textiles.materials import (
    CATALOGUE,
    CATEGORIES,
    TextileMaterial,
    by_category,
    by_id,
    by_subcategory,
    with_certification,
    biodegradable_materials,
)
from kerf_textiles.sustainability import (
    GarmentImpact,
    MaterialContribution,
    GHG_MAX_REFERENCE,
    WATER_MAX_REFERENCE,
    GHG_WEIGHT,
    WATER_WEIGHT,
    BIODEGRADABLE_BONUS,
    score_garment,
    compare_garments,
    _ghg_sub_score,
    _water_sub_score,
)


# ---------------------------------------------------------------------------
# Catalogue completeness
# ---------------------------------------------------------------------------

class TestCatalogueCompleteness:
    def test_at_least_50_entries(self):
        """DoD: catalogue must have 50+ entries."""
        assert len(CATALOGUE) >= 50, (
            f"Catalogue only has {len(CATALOGUE)} entries; need ≥ 50."
        )

    def test_all_ids_unique(self):
        ids = list(CATALOGUE.keys())
        assert len(ids) == len(set(ids)), "Duplicate material_id found in catalogue."

    def test_id_matches_dict_key(self):
        for key, mat in CATALOGUE.items():
            assert mat.material_id == key, (
                f"material_id {mat.material_id!r} does not match dict key {key!r}"
            )

    def test_every_category_populated(self):
        """Each CATEGORIES value must have at least one entry in the catalogue."""
        for cat in CATEGORIES:
            entries = by_category(cat)
            assert len(entries) >= 1, f"Category {cat!r} has no catalogue entries."

    def test_specific_materials_present(self):
        """Key materials named in the task spec must be present."""
        required_ids = [
            "cotton_conventional",
            "cotton_organic",
            "polyester_virgin",
            "polyester_recycled",
            "wool_merino_virgin",
            "silk_conventional",
            "linen",
            "viscose_conventional",
            "lyocell_tencel",
            "nylon_6_virgin",
            "hemp",
            "leather_full_grain",
            "leather_pu_synthetic",
        ]
        for mid in required_ids:
            assert mid in CATALOGUE, f"{mid!r} missing from catalogue."


# ---------------------------------------------------------------------------
# Physical properties sanity
# ---------------------------------------------------------------------------

class TestPhysicalProperties:
    def test_positive_density(self):
        for mat in CATALOGUE.values():
            assert mat.density_gsm > 0, f"{mat.material_id}: density_gsm <= 0"

    def test_positive_tensile_strength(self):
        for mat in CATALOGUE.values():
            assert mat.tensile_strength_mpa > 0, (
                f"{mat.material_id}: tensile_strength_mpa <= 0"
            )

    def test_positive_elongation(self):
        for mat in CATALOGUE.values():
            assert mat.elongation_pct > 0, (
                f"{mat.material_id}: elongation_pct <= 0"
            )

    def test_non_negative_water_consumption(self):
        for mat in CATALOGUE.values():
            assert mat.water_consumption_l_per_kg >= 0, (
                f"{mat.material_id}: water_consumption_l_per_kg < 0"
            )

    def test_non_negative_co2(self):
        for mat in CATALOGUE.values():
            assert mat.co2_footprint_kg_per_kg >= 0, (
                f"{mat.material_id}: co2_footprint_kg_per_kg < 0"
            )

    def test_certifications_are_tuples(self):
        for mat in CATALOGUE.values():
            assert isinstance(mat.certifications, tuple), (
                f"{mat.material_id}: certifications should be tuple"
            )


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

class TestLookupHelpers:
    def test_by_id_known(self):
        mat = by_id("cotton_organic")
        assert mat.material_id == "cotton_organic"
        assert mat.name == "Cotton (Organic)"
        assert mat.biodegradable is True
        assert "GOTS" in mat.certifications

    def test_by_id_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown material_id"):
            by_id("this_does_not_exist_xyz")

    def test_by_category_natural_cellulosic(self):
        results = by_category("natural_cellulosic")
        assert len(results) >= 4
        for mat in results:
            assert mat.category == "natural_cellulosic"

    def test_by_category_case_insensitive(self):
        upper = by_category("NATURAL_CELLULOSIC")
        lower = by_category("natural_cellulosic")
        assert len(upper) == len(lower)

    def test_by_category_empty_for_unknown(self):
        results = by_category("nonexistent_category_xyzzy")
        assert results == []

    def test_by_category_synthetic(self):
        results = by_category("synthetic")
        ids = [m.material_id for m in results]
        assert "polyester_virgin" in ids
        assert "polyester_recycled" in ids
        assert "nylon_6_virgin" in ids

    def test_by_category_leather(self):
        results = by_category("leather")
        assert len(results) >= 4
        for mat in results:
            assert mat.category == "leather"

    def test_by_subcategory_recycled(self):
        recycled = by_subcategory("recycled")
        assert len(recycled) >= 3
        for mat in recycled:
            assert mat.subcategory == "recycled"

    def test_with_certification_gots(self):
        gots = with_certification("GOTS")
        assert len(gots) >= 2
        for mat in gots:
            assert "GOTS" in mat.certifications

    def test_with_certification_bluesign(self):
        bs = with_certification("Bluesign")
        assert len(bs) >= 1

    def test_biodegradable_materials(self):
        bio = biodegradable_materials()
        assert len(bio) >= 20
        for mat in bio:
            assert mat.biodegradable is True

    def test_all_categories_lookup(self):
        """by_category works for every category constant."""
        for cat in CATEGORIES:
            results = by_category(cat)
            assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Specific known-value oracles
# ---------------------------------------------------------------------------

class TestKnownValues:
    """Check specific catalogue data against published literature values."""

    def test_cotton_conventional_water(self):
        """Conventional cotton ~10 000 L/kg — Hoekstra 2010."""
        mat = by_id("cotton_conventional")
        assert mat.water_consumption_l_per_kg == pytest.approx(10000.0, rel=0.01)

    def test_cotton_organic_lower_co2_than_conventional(self):
        conv = by_id("cotton_conventional")
        org = by_id("cotton_organic")
        assert org.co2_footprint_kg_per_kg < conv.co2_footprint_kg_per_kg

    def test_lyocell_very_low_water(self):
        """Lyocell closed-loop solvent → very low water (<50 L/kg)."""
        mat = by_id("lyocell_tencel")
        assert mat.water_consumption_l_per_kg < 50.0

    def test_hemp_low_water(self):
        mat = by_id("hemp")
        assert mat.water_consumption_l_per_kg < 400.0

    def test_polyester_recycled_lower_co2_than_virgin(self):
        virgin = by_id("polyester_virgin")
        recycled = by_id("polyester_recycled")
        assert recycled.co2_footprint_kg_per_kg < virgin.co2_footprint_kg_per_kg

    def test_pbo_highest_tensile(self):
        """PBO (Zylon) should have the highest tensile strength in catalogue."""
        pbo = by_id("pbo_zylon")
        max_other = max(
            m.tensile_strength_mpa
            for m in CATALOGUE.values()
            if m.material_id != "pbo_zylon"
        )
        assert pbo.tensile_strength_mpa > max_other

    def test_spandex_highest_elongation(self):
        spandex = by_id("spandex_elastane")
        max_other = max(
            m.elongation_pct
            for m in CATALOGUE.values()
            if m.material_id != "spandex_elastane"
        )
        assert spandex.elongation_pct > max_other

    def test_cashmere_high_co2(self):
        """Cashmere has very high CO₂ footprint (>100 kg CO₂e/kg)."""
        mat = by_id("cashmere_virgin")
        assert mat.co2_footprint_kg_per_kg > 100.0

    def test_leather_full_grain_biodegradable(self):
        mat = by_id("leather_full_grain")
        assert mat.biodegradable is True

    def test_polyester_not_biodegradable(self):
        mat = by_id("polyester_virgin")
        assert mat.biodegradable is False


# ---------------------------------------------------------------------------
# Sustainability scoring
# ---------------------------------------------------------------------------

class TestSubScoreHelpers:
    def test_ghg_subscore_zero_co2_is_100(self):
        assert _ghg_sub_score(0.0) == pytest.approx(100.0)

    def test_ghg_subscore_at_reference_is_0(self):
        assert _ghg_sub_score(GHG_MAX_REFERENCE) == pytest.approx(0.0)

    def test_ghg_subscore_above_reference_clamps_0(self):
        assert _ghg_sub_score(GHG_MAX_REFERENCE * 2) == pytest.approx(0.0)

    def test_water_subscore_zero_water_is_100(self):
        assert _water_sub_score(0.0) == pytest.approx(100.0)

    def test_water_subscore_at_reference_is_0(self):
        assert _water_sub_score(WATER_MAX_REFERENCE) == pytest.approx(0.0)

    def test_water_subscore_midpoint(self):
        score = _water_sub_score(WATER_MAX_REFERENCE / 2)
        assert score == pytest.approx(50.0, abs=1e-9)


class TestScoreGarment:
    def test_returns_garment_impact(self):
        impact = score_garment({"cotton_organic": 1.0})
        assert isinstance(impact, GarmentImpact)

    def test_score_in_range(self):
        impact = score_garment({"cotton_conventional": 1.0})
        assert 0.0 <= impact.sustainability_score <= 100.0

    def test_score_in_range_all_materials(self):
        """Every single-material garment score must be in [0, 100]."""
        for mid in CATALOGUE:
            impact = score_garment({mid: 1.0})
            assert 0.0 <= impact.sustainability_score <= 100.0, (
                f"{mid}: score={impact.sustainability_score}"
            )

    def test_co2_total_analytic(self):
        """CO₂ total = co2_per_kg × garment_mass_kg (single material)."""
        mat = by_id("lyocell_tencel")
        mass = 0.25
        impact = score_garment({"lyocell_tencel": 1.0}, garment_mass_kg=mass)
        expected = mat.co2_footprint_kg_per_kg * mass
        assert impact.co2_total_kg == pytest.approx(expected, rel=1e-9)

    def test_water_total_analytic(self):
        mat = by_id("hemp")
        mass = 0.4
        impact = score_garment({"hemp": 1.0}, garment_mass_kg=mass)
        expected = mat.water_consumption_l_per_kg * mass
        assert impact.water_total_l == pytest.approx(expected, rel=1e-9)

    def test_weighted_blend_co2(self):
        """50/50 blend: weighted CO₂ = average of the two."""
        mat_a = by_id("cotton_organic")
        mat_b = by_id("polyester_virgin")
        expected_co2 = 0.5 * mat_a.co2_footprint_kg_per_kg + 0.5 * mat_b.co2_footprint_kg_per_kg
        impact = score_garment({"cotton_organic": 0.5, "polyester_virgin": 0.5})
        assert impact.weighted_co2_kg_per_kg == pytest.approx(expected_co2, rel=1e-9)

    def test_weighted_blend_water(self):
        mat_a = by_id("linen")
        mat_b = by_id("nylon_6_virgin")
        expected_water = 0.6 * mat_a.water_consumption_l_per_kg + 0.4 * mat_b.water_consumption_l_per_kg
        impact = score_garment({"linen": 0.6, "nylon_6_virgin": 0.4})
        assert impact.weighted_water_l_per_kg == pytest.approx(expected_water, rel=1e-9)

    def test_biodegradable_bonus_all_natural(self):
        """All-natural garment should carry biodegradable bonus."""
        impact = score_garment({"cotton_organic": 0.7, "linen": 0.3})
        assert impact.fully_biodegradable is True
        assert impact.biodegradable_bonus == pytest.approx(BIODEGRADABLE_BONUS)

    def test_no_biodegradable_bonus_if_any_synthetic(self):
        """One non-biodegradable component disqualifies the bonus."""
        impact = score_garment({"cotton_organic": 0.95, "spandex_elastane": 0.05})
        assert impact.fully_biodegradable is False
        assert impact.biodegradable_bonus == pytest.approx(0.0)

    def test_cert_bonus_positive(self):
        """Organic cotton carries GOTS + OEKO-TEX → should get cert bonus."""
        impact = score_garment({"cotton_organic": 1.0})
        assert impact.cert_bonus > 0.0

    def test_organic_cotton_beats_conventional(self):
        """Organic cotton should score higher than conventional cotton."""
        score_org = score_garment({"cotton_organic": 1.0}).sustainability_score
        score_conv = score_garment({"cotton_conventional": 1.0}).sustainability_score
        assert score_org > score_conv

    def test_hemp_beats_cashmere(self):
        """Hemp (low water, low CO₂) should massively outscore cashmere."""
        score_hemp = score_garment({"hemp": 1.0}).sustainability_score
        score_cashmere = score_garment({"cashmere_virgin": 1.0}).sustainability_score
        assert score_hemp > score_cashmere

    def test_recycled_polyester_beats_virgin(self):
        score_rec = score_garment({"polyester_recycled": 1.0}).sustainability_score
        score_vir = score_garment({"polyester_virgin": 1.0}).sustainability_score
        assert score_rec > score_vir

    def test_breakdown_length_matches_mix(self):
        mix = {"cotton_organic": 0.6, "polyester_recycled": 0.3, "spandex_elastane": 0.1}
        impact = score_garment(mix)
        assert len(impact.breakdown) == 3

    def test_breakdown_fractions_sum(self):
        mix = {"cotton_organic": 0.6, "polyester_recycled": 0.35, "spandex_elastane": 0.05}
        impact = score_garment(mix)
        total = sum(c.mass_fraction for c in impact.breakdown)
        assert total == pytest.approx(1.0, abs=1e-9)

    def test_breakdown_co2_sum_matches_total(self):
        mix = {"cotton_organic": 0.5, "linen": 0.5}
        mass = 0.3
        impact = score_garment(mix, garment_mass_kg=mass)
        co2_from_breakdown = sum(c.co2_contribution_kg for c in impact.breakdown)
        assert co2_from_breakdown == pytest.approx(impact.co2_total_kg, rel=1e-9)

    def test_breakdown_water_sum_matches_total(self):
        mix = {"lyocell_tencel": 0.7, "spandex_elastane": 0.3}
        mass = 0.2
        impact = score_garment(mix, garment_mass_kg=mass)
        water_from_breakdown = sum(c.water_contribution_l for c in impact.breakdown)
        assert water_from_breakdown == pytest.approx(impact.water_total_l, rel=1e-9)

    def test_material_contribution_dataclass(self):
        impact = score_garment({"hemp_organic": 1.0})
        contrib = impact.breakdown[0]
        assert isinstance(contrib, MaterialContribution)
        assert contrib.material_id == "hemp_organic"
        assert contrib.mass_fraction == pytest.approx(1.0)
        assert 0.0 <= contrib.ghg_sub_score <= 100.0
        assert 0.0 <= contrib.water_sub_score <= 100.0


class TestScoreGarmentValidation:
    def test_empty_mix_raises(self):
        with pytest.raises(ValueError, match="empty"):
            score_garment({})

    def test_fractions_not_summing_raises(self):
        with pytest.raises(ValueError, match="sum to 1"):
            score_garment({"cotton_organic": 0.5, "linen": 0.3})

    def test_negative_fraction_raises(self):
        with pytest.raises(ValueError, match=r"\[0, 1\]"):
            score_garment({"cotton_organic": -0.1, "linen": 1.1})

    def test_unknown_material_raises(self):
        with pytest.raises(ValueError, match="Unknown material_id"):
            score_garment({"cotton_organic": 0.5, "zibblewomp_fibre": 0.5})

    def test_negative_mass_raises(self):
        with pytest.raises(ValueError, match="positive"):
            score_garment({"cotton_organic": 1.0}, garment_mass_kg=-0.1)

    def test_zero_mass_raises(self):
        with pytest.raises(ValueError, match="positive"):
            score_garment({"cotton_organic": 1.0}, garment_mass_kg=0.0)


class TestCompareGarments:
    def test_compare_returns_dict(self):
        garments = {
            "organic_tee": {"cotton_organic": 1.0},
            "poly_tee": {"polyester_virgin": 1.0},
        }
        results = compare_garments(garments)
        assert set(results.keys()) == {"organic_tee", "poly_tee"}
        for v in results.values():
            assert isinstance(v, GarmentImpact)

    def test_compare_ranking(self):
        """Low-impact garment should outscore high-impact garment."""
        garments = {
            "hemp": {"hemp_organic": 1.0},
            "cashmere": {"cashmere_virgin": 1.0},
            "leather": {"leather_full_grain": 1.0},
        }
        results = compare_garments(garments)
        assert results["hemp"].sustainability_score > results["cashmere"].sustainability_score
        assert results["hemp"].sustainability_score > results["leather"].sustainability_score

    def test_garment_mass_propagated(self):
        garments = {"g": {"linen": 1.0}}
        mass = 0.5
        results = compare_garments(garments, garment_mass_kg=mass)
        assert results["g"].garment_mass_kg == pytest.approx(mass)


class TestLCACompositeFormula:
    """White-box tests verifying the exact composite formula."""

    def test_single_material_composite_formula(self):
        """
        For a single material with no certifications and biodegradable=False:
        score = GHG_WEIGHT * ghg_sub + WATER_WEIGHT * water_sub (+ bonuses).
        """
        mid = "polyester_virgin"   # not biodegradable, certifications=("OEKO-TEX",)
        mat = by_id(mid)
        impact = score_garment({mid: 1.0})

        ghg_sub = _ghg_sub_score(mat.co2_footprint_kg_per_kg)
        water_sub = _water_sub_score(mat.water_consumption_l_per_kg)
        # OEKO-TEX is in POSITIVE_CERTS → cert_bonus = 2.0
        cert_bonus = 2.0
        expected = min(100.0, GHG_WEIGHT * ghg_sub + WATER_WEIGHT * water_sub + cert_bonus)

        assert impact.sustainability_score == pytest.approx(expected, abs=1e-9)

    def test_fully_biodegradable_adds_bonus(self):
        """Organic cotton (GOTS + OEKO-TEX, biodegradable) formula check."""
        mid = "cotton_organic"
        mat = by_id(mid)
        impact = score_garment({mid: 1.0})

        ghg_sub = _ghg_sub_score(mat.co2_footprint_kg_per_kg)
        water_sub = _water_sub_score(mat.water_consumption_l_per_kg)
        # GOTS + OEKO-TEX → 2 unique positive certs → cert_bonus = 4.0
        cert_bonus = 4.0
        expected = min(
            100.0,
            GHG_WEIGHT * ghg_sub + WATER_WEIGHT * water_sub + BIODEGRADABLE_BONUS + cert_bonus
        )
        assert impact.sustainability_score == pytest.approx(expected, abs=1e-9)
