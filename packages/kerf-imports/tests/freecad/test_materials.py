"""
test_materials.py — App::MaterialObject → .material translator tests.

Exercises translate_material() with:
  - density in g/cm³ (→ kg/m³ conversion)
  - YoungsModulus in GPa (→ MPa)
  - PoissonRatio (dimensionless)
  - YieldStrength / UltimateTensileStrength in MPa
  - ThermalConductivity
  - KdColor / AppearanceColor → hex
  - missing properties (graceful partial output)
  - unknown unit suffixes (warn + pass-through)
"""
from __future__ import annotations

import pytest

from kerf_imports.freecad.types import FCStdObject
from kerf_imports.freecad.materials import (
    translate_material,
    _parse_quantity_str,
    _parse_color,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_material(
    name: str = "TestMat",
    label: str = "TestMat",
    mat_map: dict | None = None,
) -> FCStdObject:
    return FCStdObject(
        name=name,
        type="App::MaterialObject",
        label=label,
        properties={"Material": mat_map or {}},
    )


# ---------------------------------------------------------------------------
# Basic output shape
# ---------------------------------------------------------------------------

class TestTranslateMaterialBasic:
    def test_returns_dict_with_required_keys(self):
        obj = _make_material()
        result = translate_material(obj)
        assert isinstance(result, dict)
        assert "version" in result
        assert "name" in result
        assert "freecad_ref" in result
        assert "warnings" in result

    def test_version_is_1(self):
        result = translate_material(_make_material())
        assert result["version"] == 1

    def test_freecad_ref_populated(self):
        obj = _make_material(name="Steel001", label="Steel-Generic")
        result = translate_material(obj)
        assert result["freecad_ref"]["name"] == "Steel001"
        assert result["freecad_ref"]["label"] == "Steel-Generic"
        assert result["freecad_ref"]["type"] == "App::MaterialObject"

    def test_name_from_mat_map(self):
        obj = _make_material(mat_map={"Name": "Aluminum-6061"})
        assert translate_material(obj)["name"] == "Aluminum-6061"

    def test_name_fallback_to_label(self):
        obj = _make_material(label="MyMaterial", mat_map={})
        assert translate_material(obj)["name"] == "MyMaterial"


# ---------------------------------------------------------------------------
# Density conversion
# ---------------------------------------------------------------------------

class TestDensityConversion:
    def test_density_g_per_cm3(self):
        obj = _make_material(mat_map={"Density": "7.90 g/cm^3"})
        result = translate_material(obj)
        assert "density" in result
        assert abs(result["density"] - 7900.0) < 1.0

    def test_density_kg_per_m3(self):
        obj = _make_material(mat_map={"Density": "7900 kg/m^3"})
        result = translate_material(obj)
        assert abs(result["density"] - 7900.0) < 1.0

    def test_density_2700_aluminum(self):
        obj = _make_material(mat_map={"Density": "2.70 g/cm^3"})
        result = translate_material(obj)
        assert abs(result["density"] - 2700.0) < 1.0


# ---------------------------------------------------------------------------
# Youngs modulus conversion
# ---------------------------------------------------------------------------

class TestYoungsModulusConversion:
    def test_gpa_to_mpa(self):
        obj = _make_material(mat_map={"YoungsModulus": "210 GPa"})
        result = translate_material(obj)
        assert abs(result["youngs_modulus"] - 210000.0) < 1.0

    def test_mpa_passthrough(self):
        obj = _make_material(mat_map={"YoungsModulus": "210000 MPa"})
        result = translate_material(obj)
        assert abs(result["youngs_modulus"] - 210000.0) < 1.0

    def test_pa_to_mpa(self):
        obj = _make_material(mat_map={"YoungsModulus": "210000000000 Pa"})
        result = translate_material(obj)
        assert abs(result["youngs_modulus"] - 210000.0) < 10.0  # float precision


# ---------------------------------------------------------------------------
# Poisson ratio (dimensionless)
# ---------------------------------------------------------------------------

class TestPoissonRatio:
    def test_poisson_ratio_stored(self):
        obj = _make_material(mat_map={"PoissonRatio": "0.30"})
        result = translate_material(obj)
        assert abs(result["poisson_ratio"] - 0.30) < 1e-6

    def test_poisson_ratio_no_unit(self):
        obj = _make_material(mat_map={"PoissonRatio": "0.33"})
        result = translate_material(obj)
        assert "poisson_ratio" in result


# ---------------------------------------------------------------------------
# Strength fields
# ---------------------------------------------------------------------------

class TestStrengthFields:
    def test_yield_strength_mpa(self):
        obj = _make_material(mat_map={"YieldStrength": "250 MPa"})
        result = translate_material(obj)
        assert abs(result["yield_strength"] - 250.0) < 1.0

    def test_ultimate_strength_gpa(self):
        obj = _make_material(mat_map={"UltimateTensileStrength": "0.400 GPa"})
        result = translate_material(obj)
        assert abs(result["ultimate_strength"] - 400.0) < 1.0


# ---------------------------------------------------------------------------
# Thermal conductivity
# ---------------------------------------------------------------------------

class TestThermalConductivity:
    def test_w_per_m_k(self):
        obj = _make_material(mat_map={"ThermalConductivity": "50 W/m/K"})
        result = translate_material(obj)
        assert abs(result["thermal_conductivity"] - 50.0) < 1.0


# ---------------------------------------------------------------------------
# Color extraction
# ---------------------------------------------------------------------------

class TestColorExtraction:
    def test_float_rgb_tuple(self):
        obj = _make_material(mat_map={"KdColor": "(0.50, 0.50, 0.50)"})
        result = translate_material(obj)
        # 0.50 * 255 = 127.5 → int(127.5) = 127 = 0x7f
        assert result.get("color") == "#7f7f7f"

    def test_float_rgb_aluminum(self):
        obj = _make_material(mat_map={"KdColor": "(0.80, 0.80, 0.85)"})
        result = translate_material(obj)
        assert "color" in result
        assert result["color"].startswith("#")

    def test_already_hex(self):
        obj = _make_material(mat_map={"KdColor": "#aabbcc"})
        result = translate_material(obj)
        assert result["color"] == "#aabbcc"

    def test_appearance_color_fallback(self):
        obj = _make_material(mat_map={"AppearanceColor": "(1.0, 0.0, 0.0)"})
        result = translate_material(obj)
        assert result.get("color") == "#ff0000"

    def test_no_color_key_not_in_output(self):
        obj = _make_material(mat_map={"Density": "7900 kg/m^3"})
        result = translate_material(obj)
        assert "color" not in result


# ---------------------------------------------------------------------------
# Missing properties
# ---------------------------------------------------------------------------

class TestMissingProperties:
    def test_absent_property_not_in_output(self):
        obj = _make_material(mat_map={"Density": "7900 kg/m^3"})
        result = translate_material(obj)
        assert "youngs_modulus" not in result
        assert "yield_strength" not in result

    def test_empty_mat_map_no_error(self):
        obj = _make_material(mat_map={})
        result = translate_material(obj)
        assert result["version"] == 1
        assert result["warnings"] == []

    def test_missing_material_property_warns(self):
        obj = FCStdObject(
            name="Mat",
            type="App::MaterialObject",
            label="Mat",
            properties={},  # no "Material" key at all
        )
        result = translate_material(obj)
        assert any("Material" in w or "material" in w.lower() for w in result["warnings"])


# ---------------------------------------------------------------------------
# Unit parsing helpers
# ---------------------------------------------------------------------------

class TestParseQuantityStr:
    def test_gpa(self):
        val, unit, warn = _parse_quantity_str("210 GPa", "youngs_modulus")
        assert abs(val - 210000.0) < 1.0
        assert warn == ""

    def test_g_cm3(self):
        val, unit, warn = _parse_quantity_str("7.90 g/cm^3", "density")
        assert abs(val - 7900.0) < 1.0
        assert warn == ""

    def test_empty_string(self):
        val, unit, warn = _parse_quantity_str("", "density")
        assert val is None

    def test_non_numeric(self):
        val, unit, warn = _parse_quantity_str("unknown", "density")
        assert val is None
        assert warn != ""  # some warning issued

    def test_unknown_unit_warns(self):
        val, unit, warn = _parse_quantity_str("100 furlong", "youngs_modulus")
        assert val == 100.0  # passed through unchanged
        assert "unrecognised unit" in warn


# ---------------------------------------------------------------------------
# Color helper
# ---------------------------------------------------------------------------

class TestParseColor:
    def test_float_tuple_grey(self):
        # 0.50 * 255 = 127.5 → int = 127 = 0x7f
        assert _parse_color("(0.50, 0.50, 0.50)") == "#7f7f7f"

    def test_float_tuple_red(self):
        assert _parse_color("(1.0, 0.0, 0.0)") == "#ff0000"

    def test_hex_passthrough(self):
        assert _parse_color("#aabbcc") == "#aabbcc"

    def test_empty_string_returns_none(self):
        assert _parse_color("") is None

    def test_named_color_returns_none(self):
        # Named colors (e.g. "gray") are not supported — return None
        assert _parse_color("gray") is None


# ---------------------------------------------------------------------------
# Integration with fixture
# ---------------------------------------------------------------------------

class TestMaterialsFixture:
    @pytest.fixture
    def fixture_path(self):
        import pathlib
        path = pathlib.Path(__file__).parent / "fixtures" / "materials_basic.FCStd"
        if not path.exists():
            pytest.skip("materials_basic.FCStd fixture not found")
        return path

    def test_fixture_has_two_materials(self, fixture_path):
        from kerf_imports.freecad.parser import parse_fcstd
        doc = parse_fcstd(fixture_path.read_bytes())
        mats = doc.objects_by_type("App::MaterialObject")
        assert len(mats) == 2

    def test_fixture_steel_density(self, fixture_path):
        from kerf_imports.freecad.parser import parse_fcstd
        doc = parse_fcstd(fixture_path.read_bytes())
        mats = doc.objects_by_type("App::MaterialObject")
        steel = next(m for m in mats if "Steel" in m.label)
        result = translate_material(steel)
        assert abs(result.get("density", 0) - 7900.0) < 1.0

    def test_fixture_steel_youngs_modulus(self, fixture_path):
        from kerf_imports.freecad.parser import parse_fcstd
        doc = parse_fcstd(fixture_path.read_bytes())
        mats = doc.objects_by_type("App::MaterialObject")
        steel = next(m for m in mats if "Steel" in m.label)
        result = translate_material(steel)
        # 210 GPa → 210000 MPa
        assert abs(result.get("youngs_modulus", 0) - 210000.0) < 1.0

    def test_fixture_aluminum_density(self, fixture_path):
        from kerf_imports.freecad.parser import parse_fcstd
        doc = parse_fcstd(fixture_path.read_bytes())
        mats = doc.objects_by_type("App::MaterialObject")
        alu = next(m for m in mats if "Aluminum" in m.label or "Alumin" in m.label)
        result = translate_material(alu)
        # 2.70 g/cm³ → 2700 kg/m³
        assert abs(result.get("density", 0) - 2700.0) < 1.0

    def test_fixture_steel_color(self, fixture_path):
        from kerf_imports.freecad.parser import parse_fcstd
        doc = parse_fcstd(fixture_path.read_bytes())
        mats = doc.objects_by_type("App::MaterialObject")
        steel = next(m for m in mats if "Steel" in m.label)
        result = translate_material(steel)
        assert "color" in result
        # (0.50, 0.50, 0.50) → int(0.5*255)=127=0x7f
        assert result["color"] == "#7f7f7f"
