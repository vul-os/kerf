"""
Tests for kerf_cad_core.materials.material_db — engineering material catalog.

Coverage
--------
* Database size and structure
* Material dataclass fields
* by_name() lookup
* by_category() filtering
* filter() with min_/max_ constraints
* Sustainability and cost properties
* All required material families present
"""
from __future__ import annotations

import math
import pytest

from kerf_cad_core.materials.material_db import (
    Material,
    MaterialDatabase,
    default_engineering_materials_db,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db() -> MaterialDatabase:
    return default_engineering_materials_db()


# ---------------------------------------------------------------------------
# Database size
# ---------------------------------------------------------------------------

def test_db_has_at_least_40_materials(db: MaterialDatabase):
    """Default DB must contain ≥ 40 materials (task requirement)."""
    assert len(db) >= 40


def test_db_has_at_least_50_materials(db: MaterialDatabase):
    """We target ~55 entries; gate at 50 for a comfortable buffer."""
    assert len(db) >= 50


# ---------------------------------------------------------------------------
# Material structure
# ---------------------------------------------------------------------------

def test_material_fields_all_present(db: MaterialDatabase):
    """Every Material must have non-None mandatory fields."""
    import dataclasses
    required_fields = {
        "name", "category",
        "youngs_modulus_gpa", "yield_strength_mpa", "ultimate_strength_mpa",
        "density_kg_m3", "poisson",
        "thermal_conductivity_w_m_k", "thermal_expansion_per_k",
        "specific_heat_j_kg_k", "max_service_temp_c",
        "electrical_resistivity_ohm_m",
        "cost_per_kg_usd", "embodied_energy_mj_kg",
        "co2_footprint_kg_co2_per_kg", "recyclable_fraction_pct",
    }
    for mat in db.materials:
        for f in required_fields:
            val = getattr(mat, f)
            assert val is not None, f"{mat.name}: field {f!r} is None"


def test_material_youngs_modulus_positive(db: MaterialDatabase):
    for mat in db.materials:
        assert mat.youngs_modulus_gpa > 0, f"{mat.name}: E must be > 0"


def test_material_density_positive(db: MaterialDatabase):
    for mat in db.materials:
        assert mat.density_kg_m3 > 0, f"{mat.name}: density must be > 0"


def test_material_yield_strength_positive(db: MaterialDatabase):
    for mat in db.materials:
        assert mat.yield_strength_mpa > 0, f"{mat.name}: yield_strength_mpa must be > 0"


def test_material_poisson_in_range(db: MaterialDatabase):
    for mat in db.materials:
        assert 0.0 < mat.poisson < 0.5, f"{mat.name}: Poisson ratio {mat.poisson} out of (0, 0.5)"


def test_material_recyclable_fraction_range(db: MaterialDatabase):
    for mat in db.materials:
        assert 0.0 <= mat.recyclable_fraction_pct <= 100.0, (
            f"{mat.name}: recyclable_fraction_pct {mat.recyclable_fraction_pct} out of [0, 100]"
        )


def test_material_thermal_expansion_stored_as_per_k(db: MaterialDatabase):
    """CTE must be stored as 1/K (typically 1e-6 to 1e-4), not µm/(m·K)."""
    for mat in db.materials:
        assert mat.thermal_expansion_per_k < 1e-3, (
            f"{mat.name}: thermal_expansion_per_k {mat.thermal_expansion_per_k} looks like µm/(m·K) not 1/K"
        )


def test_material_cost_per_kg_positive(db: MaterialDatabase):
    for mat in db.materials:
        assert mat.cost_per_kg_usd > 0, f"{mat.name}: cost_per_kg_usd must be > 0"


def test_material_embodied_energy_positive(db: MaterialDatabase):
    for mat in db.materials:
        assert mat.embodied_energy_mj_kg > 0, f"{mat.name}: embodied_energy_mj_kg must be > 0"


# ---------------------------------------------------------------------------
# Category coverage
# ---------------------------------------------------------------------------

def test_metals_present(db: MaterialDatabase):
    metals = db.by_category("metal")
    assert len(metals) >= 10, f"Expected ≥ 10 metals, got {len(metals)}"


def test_polymers_present(db: MaterialDatabase):
    polymers = db.by_category("polymer")
    assert len(polymers) >= 5, f"Expected ≥ 5 polymers, got {len(polymers)}"


def test_ceramics_present(db: MaterialDatabase):
    ceramics = db.by_category("ceramic")
    assert len(ceramics) >= 3, f"Expected ≥ 3 ceramics, got {len(ceramics)}"


def test_composites_present(db: MaterialDatabase):
    composites = db.by_category("composite")
    assert len(composites) >= 3, f"Expected ≥ 3 composites, got {len(composites)}"


def test_natural_present(db: MaterialDatabase):
    natural = db.by_category("natural")
    assert len(natural) >= 2, f"Expected ≥ 2 natural materials, got {len(natural)}"


# ---------------------------------------------------------------------------
# by_name lookup
# ---------------------------------------------------------------------------

def test_by_name_steel(db: MaterialDatabase):
    mat = db.by_name("AISI_1018_steel")
    assert mat.name == "AISI_1018_steel"
    assert mat.category == "metal"
    assert mat.youngs_modulus_gpa == pytest.approx(200.0, abs=5.0)


def test_by_name_cfrp(db: MaterialDatabase):
    mat = db.by_name("CFRP_quasi_iso")
    assert mat.category == "composite"
    assert mat.youngs_modulus_gpa > 40.0


def test_by_name_missing_raises(db: MaterialDatabase):
    with pytest.raises(KeyError):
        db.by_name("NotAMaterial_XYZ")


# ---------------------------------------------------------------------------
# filter() with min_/max_ constraints
# ---------------------------------------------------------------------------

def test_filter_min_yield_strength_mpa_500(db: MaterialDatabase):
    """filter(min_yield_strength_mpa=500) must return ≥ 5 metals."""
    mats = db.filter(min_yield_strength_mpa=500)
    assert len(mats) >= 5, f"Expected ≥ 5 high-strength materials, got {len(mats)}"
    for m in mats:
        assert m.yield_strength_mpa >= 500


def test_filter_max_density_light_materials(db: MaterialDatabase):
    """filter(max_density_kg_m3=2000) should return only very light materials."""
    mats = db.filter(max_density_kg_m3=2000)
    for m in mats:
        assert m.density_kg_m3 <= 2000


def test_filter_combined_constraints(db: MaterialDatabase):
    """filter(min_yield_strength_mpa=200, max_density_kg_m3=4500) returns metals + composites."""
    mats = db.filter(min_yield_strength_mpa=200, max_density_kg_m3=4500)
    assert len(mats) >= 5
    for m in mats:
        assert m.yield_strength_mpa >= 200
        assert m.density_kg_m3 <= 4500


def test_filter_high_service_temp(db: MaterialDatabase):
    """filter(min_max_service_temp_c=800) should return ceramics and superalloys."""
    mats = db.filter(min_max_service_temp_c=800)
    assert len(mats) >= 2
    for m in mats:
        assert m.max_service_temp_c >= 800


def test_filter_bad_key_raises(db: MaterialDatabase):
    """Unknown property name should raise ValueError."""
    with pytest.raises(ValueError):
        db.filter(non_existent_property=100)


def test_filter_no_constraints_returns_all(db: MaterialDatabase):
    """filter() with no args returns all materials."""
    mats = db.filter()
    assert len(mats) == len(db)


# ---------------------------------------------------------------------------
# Specific known material values (spot-check against Ashby 2017 App A)
# ---------------------------------------------------------------------------

def test_aa6061_t6_properties(db: MaterialDatabase):
    mat = db.by_name("AA6061_T6")
    # Ashby (2017) App A: E ≈ 69 GPa, σy ≈ 276 MPa, ρ ≈ 2700 kg/m³
    assert mat.youngs_modulus_gpa == pytest.approx(69.0, abs=3.0)
    assert mat.yield_strength_mpa == pytest.approx(276.0, abs=20.0)
    assert mat.density_kg_m3 == pytest.approx(2700.0, abs=100.0)


def test_ti6al4v_properties(db: MaterialDatabase):
    mat = db.by_name("Ti-6Al-4V")
    # Ashby (2017): E ≈ 114 GPa, σy ≈ 880 MPa, ρ ≈ 4430 kg/m³
    assert mat.youngs_modulus_gpa == pytest.approx(113.8, abs=5.0)
    assert mat.yield_strength_mpa >= 800.0
    assert mat.density_kg_m3 == pytest.approx(4430.0, abs=100.0)


def test_cfrp_unidirectional_low_density_high_strength(db: MaterialDatabase):
    mat = db.by_name("CFRP_unidirectional")
    assert mat.density_kg_m3 < 1800
    assert mat.youngs_modulus_gpa > 100.0
    assert mat.yield_strength_mpa > 1000.0


def test_peek_high_service_temp_polymer(db: MaterialDatabase):
    mat = db.by_name("PEEK")
    assert mat.max_service_temp_c >= 230.0  # Ashby (2018): ~250°C


def test_bamboo_low_density_natural(db: MaterialDatabase):
    mat = db.by_name("Bamboo_structural")
    assert mat.density_kg_m3 < 800
    assert mat.youngs_modulus_gpa > 10.0


# ---------------------------------------------------------------------------
# Sustainability / cost spot checks
# ---------------------------------------------------------------------------

def test_titanium_high_embodied_energy(db: MaterialDatabase):
    """Ti-6Al-4V has much higher embodied energy than steel (Ashby 2018 §B)."""
    ti = db.by_name("Ti-6Al-4V")
    steel = db.by_name("AISI_1018_steel")
    assert ti.embodied_energy_mj_kg > steel.embodied_energy_mj_kg * 10


def test_bamboo_low_co2(db: MaterialDatabase):
    """Bamboo should have much lower CO₂ footprint than metals."""
    bamboo = db.by_name("Bamboo_structural")
    steel = db.by_name("AISI_1018_steel")
    assert bamboo.co2_footprint_kg_co2_per_kg < steel.co2_footprint_kg_co2_per_kg
