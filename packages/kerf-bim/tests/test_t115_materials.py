"""
Tests for T-115: BIM material catalogue with IFC IfcMaterial round-trip.

DoD: a wall with a catalogued material renders via the PBR hero path +
IFC round-trips its IfcMaterial; pytest.
"""
from __future__ import annotations

import math
import pytest

from kerf_bim.materials import (
    CATALOGUE,
    BIMMaterial,
    PBRAppearance,
    StructuralProps,
    ThermalProps,
    FireProps,
    find_material,
    list_by_category,
    get_material,
    MaterialError,
    material_to_ifc_dict,
    material_from_ifc_dict,
    layer_set_to_ifc_dict,
    MaterialLayer,
    pbr_appearance_dict,
    wall_material_layer_set,
    MPa,
    GPa,
)
from kerf_bim.walls import make_compound_wall, make_wall_instance, wall_to_ifc_dict


# =============================================================================
# T-115.1: Re-export completeness
# =============================================================================

class TestReExports:
    def test_catalogue_accessible(self):
        assert len(CATALOGUE) >= 40

    def test_find_material_works(self):
        r = find_material("concrete_m30")
        assert r["ok"]

    def test_list_by_category_works(self):
        metals = list_by_category("metal")
        assert len(metals) >= 4

    def test_get_material_found(self):
        m = get_material("steel_a36")
        assert isinstance(m, BIMMaterial)

    def test_get_material_missing_raises(self):
        with pytest.raises(MaterialError):
            get_material("nonexistent_material_xyz_t115")


# =============================================================================
# T-115.2: IFC material dict round-trip
# =============================================================================

class TestMaterialIFCRoundTrip:
    def _mat(self, name: str = "concrete_m30") -> BIMMaterial:
        return get_material(name)

    def test_material_to_ifc_dict_keys(self):
        d = material_to_ifc_dict(self._mat())
        for key in ("ifc_entity", "name", "category", "density_kg_m3",
                    "source", "structural", "thermal", "fire",
                    "render_appearance"):
            assert key in d, f"Missing key '{key}'"

    def test_ifc_entity_is_ifcmaterial(self):
        d = material_to_ifc_dict(self._mat())
        assert d["ifc_entity"] == "IfcMaterial"

    def test_structural_keys_concrete(self):
        d = material_to_ifc_dict(self._mat("concrete_m30"))
        s = d["structural"]
        assert s is not None
        for key in ("elastic_modulus_pa", "yield_strength_pa",
                    "tensile_strength_pa", "poisson_ratio", "shear_modulus_pa"):
            assert key in s

    def test_thermal_keys_present(self):
        d = material_to_ifc_dict(self._mat("concrete_m30"))
        t = d["thermal"]
        assert t is not None
        for key in ("thermal_conductivity_w_mk", "specific_heat_j_kgk",
                    "thermal_expansion_1_k", "emissivity"):
            assert key in t

    def test_fire_keys_present(self):
        d = material_to_ifc_dict(self._mat("concrete_m30"))
        f = d["fire"]
        assert f is not None
        assert "rating_class" in f
        assert "fire_resistance_hours" in f

    def test_render_appearance_keys(self):
        d = material_to_ifc_dict(self._mat("steel_a36"))
        r = d["render_appearance"]
        for key in ("base_color", "metallic", "roughness", "ior", "opacity"):
            assert key in r

    def test_insulation_no_structural(self):
        d = material_to_ifc_dict(self._mat("insulation_rockwool"))
        assert d["structural"] is None

    def test_round_trip_concrete(self):
        """material_from_ifc_dict(material_to_ifc_dict(m)) reproduces m."""
        orig = self._mat("concrete_m30")
        d = material_to_ifc_dict(orig)
        reconstructed = material_from_ifc_dict(d)
        assert reconstructed.name == orig.name
        assert reconstructed.category == orig.category
        assert abs(reconstructed.density - orig.density) < 0.1
        assert reconstructed.structural is not None
        assert abs(
            reconstructed.structural.elastic_modulus - orig.structural.elastic_modulus
        ) < 1e3

    def test_round_trip_render_appearance(self):
        orig = self._mat("steel_a36")
        d = material_to_ifc_dict(orig)
        reconstructed = material_from_ifc_dict(d)
        r = reconstructed.render_appearance
        assert r.metallic == pytest.approx(orig.render_appearance.metallic)
        assert r.roughness == pytest.approx(orig.render_appearance.roughness)
        assert r.ior == pytest.approx(orig.render_appearance.ior)

    def test_round_trip_steel_source(self):
        orig = self._mat("steel_a36")
        d = material_to_ifc_dict(orig)
        reconstructed = material_from_ifc_dict(d)
        assert reconstructed.source == orig.source


# =============================================================================
# T-115.3: Material layer set (IfcMaterialLayerSet)
# =============================================================================

class TestMaterialLayerSet:
    def test_layer_set_keys(self):
        layers = [
            MaterialLayer("concrete_reinforced", 200.0),
            MaterialLayer("insulation_rockwool", 80.0),
        ]
        d = layer_set_to_ifc_dict("Test Wall Layers", layers)
        assert d["ifc_entity"] == "IfcMaterialLayerSet"
        assert d["name"] == "Test Wall Layers"
        assert abs(d["total_thickness_mm"] - 280.0) < 1e-6
        assert len(d["layers"]) == 2

    def test_layer_material_embedded(self):
        layers = [MaterialLayer("concrete_m30", 200.0)]
        d = layer_set_to_ifc_dict("RC", layers)
        mat = d["layers"][0]["material"]
        assert mat["ifc_entity"] == "IfcMaterial"
        assert mat["name"] == "concrete_m30"

    def test_unknown_material_placeholder(self):
        """Unknown materials get a minimal placeholder dict."""
        layers = [MaterialLayer("nonexistent_mat_t115_test", 50.0)]
        d = layer_set_to_ifc_dict("Test", layers)
        mat = d["layers"][0]["material"]
        assert mat["name"] == "nonexistent_mat_t115_test"

    def test_ventilated_flag(self):
        layers = [
            MaterialLayer("brick_clay", 110.0, is_ventilated=False),
            MaterialLayer("air_gap", 50.0, is_ventilated=True),
        ]
        d = layer_set_to_ifc_dict("Cavity Wall", layers)
        assert d["layers"][0]["is_ventilated"] is False
        assert d["layers"][1]["is_ventilated"] is True


# =============================================================================
# T-115.4: PBR appearance bridge
# =============================================================================

class TestPBRAppearanceBridge:
    def test_concrete_pbr(self):
        pbr = pbr_appearance_dict("concrete_m30")
        assert pbr is not None
        assert "color" in pbr
        assert "metallic" in pbr
        assert "roughness" in pbr
        assert "ior" in pbr
        assert "opacity" in pbr

    def test_steel_metallic_1(self):
        pbr = pbr_appearance_dict("steel_a36")
        assert pbr is not None
        assert pbr["metallic"] == pytest.approx(1.0)

    def test_glass_opacity_less_than_1(self):
        pbr = pbr_appearance_dict("glass_annealed_float")
        assert pbr is not None
        assert pbr["opacity"] < 1.0

    def test_missing_material_returns_none(self):
        pbr = pbr_appearance_dict("nonexistent_mat_t115_pbr_test")
        assert pbr is None

    def test_all_pbr_values_in_range(self):
        for name in ("concrete_m30", "steel_a36", "timber_spf", "brick_clay"):
            pbr = pbr_appearance_dict(name)
            assert pbr is not None
            r, g, b = pbr["color"]
            assert 0.0 <= r <= 1.0
            assert 0.0 <= g <= 1.0
            assert 0.0 <= b <= 1.0
            assert 0.0 <= pbr["metallic"] <= 1.0
            assert 0.0 <= pbr["roughness"] <= 1.0
            assert 1.0 <= pbr["ior"] <= 3.0
            assert 0.0 < pbr["opacity"] <= 1.0


# =============================================================================
# T-115.5: Wall with catalogued material — IFC round-trip DoD
# =============================================================================

class TestWallMaterialRoundTrip:
    def test_wall_material_layer_set(self):
        """A CompoundWall exports an IfcMaterialLayerSet via wall_material_layer_set."""
        wt = make_compound_wall(
            "Brick Cavity 350",
            [
                ("brick_clay",         110.0, "finish1"),
                ("air_gap",             50.0, "air_gap"),
                ("insulation_rockwool", 90.0, "thermal"),
                ("concrete_reinforced", 100.0, "structure"),
            ],
        )
        d = wall_material_layer_set(wt)
        assert d["ifc_entity"] == "IfcMaterialLayerSet"
        assert abs(d["total_thickness_mm"] - 350.0) < 1e-6
        assert len(d["layers"]) == 4

    def test_wall_ifc_dict_with_material_layer_set(self):
        """Full DoD: wall IFC dict + material layer set produced cleanly."""
        wt = make_compound_wall(
            "RC Slab 200",
            [("concrete_reinforced", 200.0, "structure")],
        )
        wi = make_wall_instance(wt, [0, 0], [5000, 0], height=3000.0)
        wall_d = wall_to_ifc_dict(wi)
        mat_d = wall_material_layer_set(wt)

        # Wall dict is IFC-exporter compatible
        assert wall_d["thickness"] == pytest.approx(200.0)
        assert len(wall_d["layers"]) == 1

        # Material layer set is IfcMaterial compatible
        layer = mat_d["layers"][0]
        mat = layer["material"]
        assert mat["ifc_entity"] == "IfcMaterial"
        assert mat["name"] == "concrete_reinforced"

        # Round-trip the material
        reconstructed = material_from_ifc_dict(mat)
        assert reconstructed.name == "concrete_reinforced"
        assert reconstructed.structural is not None

    def test_wall_pbr_hero_path(self):
        """DoD: wall material renders via PBR hero path."""
        wt = make_compound_wall(
            "Brick Single",
            [("brick_clay", 230.0, "structure")],
        )
        # Get primary structural layer material
        primary_mat_name = wt.layers[0].material
        pbr = pbr_appearance_dict(primary_mat_name)
        assert pbr is not None
        # Brick should be non-metallic, rough, opaque
        assert pbr["metallic"] == pytest.approx(0.0)
        assert pbr["roughness"] > 0.5
        assert pbr["opacity"] == pytest.approx(1.0)

    def test_ifc_material_round_trip_all_presets(self):
        """All catalogue materials round-trip through IFC dict without loss."""
        for name, mat in CATALOGUE.items():
            d = material_to_ifc_dict(mat)
            r = material_from_ifc_dict(d)
            assert r.name == mat.name
            assert r.category == mat.category
            assert abs(r.density - mat.density) < 0.1
