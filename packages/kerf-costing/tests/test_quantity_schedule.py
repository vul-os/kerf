"""
Hermetic tests for kerf_costing — BIM material quantity take-off.

Coverage
--------
quantity_schedule.compute_quantity_schedule:
  - empty elements → empty report + warning
  - single wall element → correct area/volume/count
  - multiple categories → aggregated by_category sorted by cost
  - category filter → only matching elements included
  - material cost rollup → correct mass + cost calculation
  - unknown material → flagged + zero cost + warning
  - waste_factor applied correctly
  - zero-volume element → no cost
  - mixed flagged/unflagged → total correct

tools.run_bim_quantity_schedule:
  - happy path → schedule without cost fields
  - missing elements → err_payload BAD_ARGS
  - empty list → err_payload BAD_ARGS

tools.run_bim_material_cost_rollup:
  - happy path → correct total_material_cost_usd
  - missing material_unit_costs → err_payload BAD_ARGS
  - invalid density → err_payload BAD_ARGS
  - category filter passed through

All tests are pure-Python and hermetic: no DB, no network, no OCC.

References
----------
BCIS SFCA: cost model validation
ISO 13370:2017: volume computation conventions
"""
from __future__ import annotations

import json
import math
import pytest

from kerf_costing.quantity_schedule import (
    MaterialCostSpec,
    compute_quantity_schedule,
    report_to_dict,
)
from kerf_costing.tools import (
    run_bim_quantity_schedule,
    run_bim_material_cost_rollup,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _wall(element_id="W1", name="Wall-01", material="Concrete",
          area=20.0, volume=6.0, length=10.0):
    return {
        "id": element_id, "name": name, "category": "Wall",
        "material": material, "area": area, "volume": volume, "length": length,
    }


def _slab(element_id="S1", name="Slab-01", material="Concrete",
          area=50.0, volume=12.5):
    return {
        "id": element_id, "name": name, "category": "Slab",
        "material": material, "area": area, "volume": volume,
    }


def _column(element_id="C1", name="Column-01", material="Steel",
            volume=0.1, length=3.0):
    return {
        "id": element_id, "name": name, "category": "Column",
        "material": material, "volume": volume, "length": length,
    }


def _door(element_id="D1", name="Door-01", material="Timber",
          area=2.1):
    return {
        "id": element_id, "name": name, "category": "Door",
        "material": material, "area": area,
    }


_CONCRETE_SPEC = MaterialCostSpec(
    material="Concrete",
    density_kg_m3=2400.0,
    price_usd_per_kg=0.065,
    waste_factor=0.05,
)

_STEEL_SPEC = MaterialCostSpec(
    material="Steel",
    density_kg_m3=7850.0,
    price_usd_per_kg=0.90,
    waste_factor=0.02,
)

_TIMBER_SPEC = MaterialCostSpec(
    material="Timber",
    density_kg_m3=550.0,
    price_usd_per_kg=0.50,
    waste_factor=0.10,
)


# ---------------------------------------------------------------------------
# MaterialCostSpec validation
# ---------------------------------------------------------------------------

class TestMaterialCostSpec:
    def test_valid_spec_created(self):
        spec = MaterialCostSpec(
            material="Concrete", density_kg_m3=2400, price_usd_per_kg=0.065,
        )
        assert spec.material == "Concrete"
        assert spec.waste_factor == 0.0

    def test_negative_density_raises(self):
        with pytest.raises(ValueError, match="density_kg_m3"):
            MaterialCostSpec(
                material="X", density_kg_m3=-1.0, price_usd_per_kg=1.0,
            )

    def test_negative_price_raises(self):
        with pytest.raises(ValueError, match="price_usd_per_kg"):
            MaterialCostSpec(
                material="X", density_kg_m3=1000.0, price_usd_per_kg=-0.01,
            )

    def test_waste_factor_out_of_range_raises(self):
        with pytest.raises(ValueError, match="waste_factor"):
            MaterialCostSpec(
                material="X", density_kg_m3=1000.0, price_usd_per_kg=1.0,
                waste_factor=1.5,
            )

    def test_zero_waste_factor_valid(self):
        spec = MaterialCostSpec("Y", 1000.0, 1.0, waste_factor=0.0)
        assert spec.waste_factor == 0.0

    def test_max_waste_factor_valid(self):
        spec = MaterialCostSpec("Z", 1000.0, 1.0, waste_factor=1.0)
        assert spec.waste_factor == 1.0


# ---------------------------------------------------------------------------
# compute_quantity_schedule — no-cost mode
# ---------------------------------------------------------------------------

class TestQuantityScheduleNoCost:
    def test_empty_elements_returns_empty_report_with_warning(self):
        report = compute_quantity_schedule([], [])
        assert report.ok is True
        assert report.element_lines == []
        assert any("empty" in w.lower() for w in report.warnings)

    def test_single_wall_element_count(self):
        report = compute_quantity_schedule([_wall()], [])
        assert len(report.element_lines) == 1
        line = report.element_lines[0]
        assert line.count == 1
        assert line.category == "Wall"
        assert line.material == "Concrete"

    def test_single_wall_area_volume(self):
        report = compute_quantity_schedule([_wall(area=20.0, volume=6.0)], [])
        line = report.element_lines[0]
        assert line.area_m2 == pytest.approx(20.0)
        assert line.volume_m3 == pytest.approx(6.0)

    def test_category_filter_excludes_non_matching(self):
        elements = [_wall(), _slab(), _column()]
        report = compute_quantity_schedule(elements, [], categories=["Wall"])
        cats = {l.category for l in report.element_lines}
        assert cats == {"Wall"}

    def test_category_filter_case_insensitive(self):
        report = compute_quantity_schedule([_wall(), _slab()], [], categories=["wall"])
        assert len(report.element_lines) == 1

    def test_by_category_groups_same_type(self):
        elements = [
            _wall(element_id="W1"), _wall(element_id="W2"),
        ]
        report = compute_quantity_schedule(elements, [])
        assert len(report.by_category) == 1
        cat = report.by_category[0]
        assert cat.category == "Wall"
        assert cat.element_count == 2
        assert cat.total_area_m2 == pytest.approx(40.0)

    def test_by_material_groups_same_material(self):
        elements = [_wall(), _slab()]  # both Concrete
        report = compute_quantity_schedule(elements, [])
        assert len(report.by_material) == 1
        mat = report.by_material[0]
        assert mat.material == "Concrete"
        assert mat.element_count == 2

    def test_multiple_categories_all_included(self):
        elements = [_wall(), _slab(), _column(), _door()]
        report = compute_quantity_schedule(elements, [])
        cats = {l.category for l in report.element_lines}
        assert cats == {"Wall", "Slab", "Column", "Door"}

    def test_door_no_volume_no_cost(self):
        report = compute_quantity_schedule([_door()], [])
        line = report.element_lines[0]
        assert line.volume_m3 is None
        assert line.material_cost_usd == 0.0

    def test_element_name_preserved(self):
        report = compute_quantity_schedule([_wall(name="My Wall")], [])
        assert report.element_lines[0].element_name == "My Wall"


# ---------------------------------------------------------------------------
# compute_quantity_schedule — cost mode
# ---------------------------------------------------------------------------

class TestQuantityScheduleWithCost:
    def test_wall_concrete_cost_calculation(self):
        # volume=6.0 m³, waste=5%, density=2400, price=0.065
        # gross_mass = 6.0 * 1.05 * 2400 = 15120 kg
        # cost = 15120 * 0.065 = 982.80 USD
        report = compute_quantity_schedule([_wall(volume=6.0)], [_CONCRETE_SPEC])
        line = report.element_lines[0]
        assert line.gross_mass_kg == pytest.approx(15120.0)
        assert line.material_cost_usd == pytest.approx(982.80)
        assert line.flagged is False

    def test_steel_column_cost_calculation(self):
        # volume=0.1 m³, waste=2%, density=7850, price=0.90
        # gross_mass = 0.1 * 1.02 * 7850 = 800.7 kg
        # cost = 800.7 * 0.90 = 720.63 USD
        report = compute_quantity_schedule([_column()], [_STEEL_SPEC])
        line = report.element_lines[0]
        assert line.gross_mass_kg == pytest.approx(800.7, rel=1e-4)
        assert line.material_cost_usd == pytest.approx(720.63, rel=1e-4)

    def test_total_cost_sum(self):
        elements = [_wall(volume=6.0), _slab(volume=12.5)]
        # Concrete waste=5%
        # Wall:  6.0 * 1.05 * 2400 * 0.065 = 982.80
        # Slab: 12.5 * 1.05 * 2400 * 0.065 = 2047.50
        # Total = 3030.30
        report = compute_quantity_schedule(elements, [_CONCRETE_SPEC])
        assert report.total_material_cost_usd == pytest.approx(3030.30, rel=1e-4)

    def test_unknown_material_flagged(self):
        elem = _wall(material="ExoticAlloy")
        report = compute_quantity_schedule([elem], [_CONCRETE_SPEC])
        line = report.element_lines[0]
        assert line.flagged is True
        assert line.material_cost_usd == 0.0
        assert any("ExoticAlloy" in w or "exotic" in w.lower() for w in report.warnings)

    def test_unknown_material_does_not_affect_total(self):
        elements = [_wall(volume=6.0), _wall(element_id="W2", material="Unknown")]
        report = compute_quantity_schedule(elements, [_CONCRETE_SPEC])
        # Only the first wall should contribute cost
        expected = 6.0 * 1.05 * 2400.0 * 0.065
        assert report.total_material_cost_usd == pytest.approx(expected, rel=1e-4)

    def test_zero_volume_element_no_cost(self):
        elem = {"id": "X1", "name": "Void", "category": "Wall",
                "material": "Concrete", "area": 10.0}  # no volume
        report = compute_quantity_schedule([elem], [_CONCRETE_SPEC])
        line = report.element_lines[0]
        assert line.volume_m3 is None
        assert line.material_cost_usd == 0.0
        assert line.flagged is False

    def test_waste_factor_zero_baseline(self):
        spec = MaterialCostSpec("Concrete", density_kg_m3=2400.0, price_usd_per_kg=0.065,
                                waste_factor=0.0)
        report = compute_quantity_schedule([_wall(volume=1.0)], [spec])
        line = report.element_lines[0]
        # gross_mass = 1.0 * 1.0 * 2400 = 2400 kg; cost = 2400 * 0.065 = 156 USD
        assert line.gross_mass_kg == pytest.approx(2400.0)
        assert line.material_cost_usd == pytest.approx(156.0)

    def test_by_category_sorted_by_cost_desc(self):
        # Slab has more volume → higher cost → should appear first
        elements = [_wall(volume=1.0), _slab(volume=50.0)]
        report = compute_quantity_schedule(elements, [_CONCRETE_SPEC])
        assert report.by_category[0].category == "Slab"

    def test_by_material_sums_across_categories(self):
        # Wall and Slab both use Concrete
        elements = [_wall(volume=6.0), _slab(volume=12.5)]
        report = compute_quantity_schedule(elements, [_CONCRETE_SPEC])
        assert len(report.by_material) == 1
        mat = report.by_material[0]
        assert mat.total_volume_m3 == pytest.approx(18.5)

    def test_multiple_materials_separate_summaries(self):
        elements = [_wall(volume=6.0), _column(volume=0.1)]  # Concrete + Steel
        report = compute_quantity_schedule(elements, [_CONCRETE_SPEC, _STEEL_SPEC])
        mats = {m.material for m in report.by_material}
        assert "Concrete" in mats
        assert "Steel" in mats


# ---------------------------------------------------------------------------
# report_to_dict
# ---------------------------------------------------------------------------

class TestReportToDict:
    def test_dict_is_json_serialisable(self):
        report = compute_quantity_schedule([_wall()], [_CONCRETE_SPEC])
        d = report_to_dict(report)
        s = json.dumps(d)
        assert len(s) > 10

    def test_dict_has_required_keys(self):
        report = compute_quantity_schedule([_wall()], [_CONCRETE_SPEC])
        d = report_to_dict(report)
        for key in ("ok", "total_material_cost_usd", "by_category",
                    "by_material", "element_lines", "warnings"):
            assert key in d

    def test_element_line_dict_fields(self):
        report = compute_quantity_schedule([_wall()], [_CONCRETE_SPEC])
        line = report_to_dict(report)["element_lines"][0]
        for field in ("element_id", "element_name", "category", "material",
                      "area_m2", "volume_m3", "count", "gross_mass_kg",
                      "material_cost_usd", "flagged", "flag_reason"):
            assert field in line


# ---------------------------------------------------------------------------
# LLM tool wrappers
# ---------------------------------------------------------------------------

class TestRunBimQuantitySchedule:
    def test_happy_path_returns_ok(self):
        params = {
            "elements": [_wall(), _slab()],
        }
        raw = run_bim_quantity_schedule(params, None)
        d = json.loads(raw)
        assert "error" not in d
        assert "by_category" in d
        assert "element_lines" in d

    def test_cost_fields_stripped_from_schedule_variant(self):
        params = {"elements": [_wall()]}
        raw = run_bim_quantity_schedule(params, None)
        d = json.loads(raw)
        # No cost-related fields in quantity-only mode
        for line in d.get("element_lines", []):
            assert "material_cost_usd" not in line
            assert "gross_mass_kg" not in line
        assert "total_material_cost_usd" not in d

    def test_missing_elements_returns_error(self):
        raw = run_bim_quantity_schedule({}, None)
        d = json.loads(raw)
        assert d.get("code") == "BAD_ARGS"

    def test_empty_elements_list_returns_error(self):
        raw = run_bim_quantity_schedule({"elements": []}, None)
        d = json.loads(raw)
        assert d.get("code") == "BAD_ARGS"

    def test_category_filter_applied(self):
        params = {
            "elements": [_wall(), _slab(), _column()],
            "categories": ["Wall"],
        }
        raw = run_bim_quantity_schedule(params, None)
        d = json.loads(raw)
        cats = {l["category"] for l in d["element_lines"]}
        assert cats == {"Wall"}

    def test_by_category_count_matches_elements(self):
        params = {"elements": [_wall(element_id="W1"), _wall(element_id="W2")]}
        raw = run_bim_quantity_schedule(params, None)
        d = json.loads(raw)
        assert d["by_category"][0]["element_count"] == 2


class TestRunBimMaterialCostRollup:
    def _make_params(self, elements=None, costs=None, categories=None):
        params = {
            "elements": elements or [_wall(volume=6.0)],
            "material_unit_costs": costs or [
                {"material": "Concrete", "density_kg_m3": 2400.0,
                 "price_usd_per_kg": 0.065, "waste_factor": 0.05}
            ],
        }
        if categories:
            params["categories"] = categories
        return params

    def test_happy_path_returns_total_cost(self):
        raw = run_bim_material_cost_rollup(self._make_params(), None)
        d = json.loads(raw)
        assert "total_material_cost_usd" in d
        # 6.0 * 1.05 * 2400 * 0.065 = 982.80
        assert abs(d["total_material_cost_usd"] - 982.80) < 0.01

    def test_missing_elements_returns_error(self):
        params = {"material_unit_costs": [
            {"material": "Concrete", "density_kg_m3": 2400, "price_usd_per_kg": 0.065}
        ]}
        raw = run_bim_material_cost_rollup(params, None)
        d = json.loads(raw)
        assert d.get("code") == "BAD_ARGS"

    def test_missing_material_costs_returns_error(self):
        raw = run_bim_material_cost_rollup({"elements": [_wall()]}, None)
        d = json.loads(raw)
        assert d.get("code") == "BAD_ARGS"

    def test_invalid_density_returns_error(self):
        params = self._make_params(
            costs=[{"material": "X", "density_kg_m3": -100, "price_usd_per_kg": 1.0}]
        )
        raw = run_bim_material_cost_rollup(params, None)
        d = json.loads(raw)
        assert d.get("code") == "BAD_ARGS"

    def test_category_filter_reduces_cost(self):
        elements = [_wall(volume=6.0), _slab(volume=12.5)]
        # Only include Walls → cost should be wall-only
        params = self._make_params(elements=elements, categories=["Wall"])
        raw = run_bim_material_cost_rollup(params, None)
        d = json.loads(raw)
        expected = 6.0 * 1.05 * 2400 * 0.065
        assert abs(d["total_material_cost_usd"] - expected) < 0.01

    def test_by_material_present_in_result(self):
        raw = run_bim_material_cost_rollup(self._make_params(), None)
        d = json.loads(raw)
        assert "by_material" in d
        assert len(d["by_material"]) == 1
        assert d["by_material"][0]["material"] == "Concrete"

    def test_element_lines_include_cost(self):
        raw = run_bim_material_cost_rollup(self._make_params(), None)
        d = json.loads(raw)
        line = d["element_lines"][0]
        assert "material_cost_usd" in line
        assert "gross_mass_kg" in line
        assert "flagged" in line

    def test_unknown_material_flagged(self):
        elements = [_wall(material="Unobtainium", volume=1.0)]
        params = self._make_params(elements=elements)
        raw = run_bim_material_cost_rollup(params, None)
        d = json.loads(raw)
        assert d["element_lines"][0]["flagged"] is True
        assert d["total_material_cost_usd"] == 0.0

    def test_multiple_materials_total_correct(self):
        elements = [_wall(volume=6.0), _column(volume=0.1)]
        costs = [
            {"material": "Concrete", "density_kg_m3": 2400.0,
             "price_usd_per_kg": 0.065, "waste_factor": 0.05},
            {"material": "Steel", "density_kg_m3": 7850.0,
             "price_usd_per_kg": 0.90, "waste_factor": 0.02},
        ]
        raw = run_bim_material_cost_rollup(
            {"elements": elements, "material_unit_costs": costs}, None
        )
        d = json.loads(raw)
        wall_cost = 6.0 * 1.05 * 2400.0 * 0.065    # 982.80
        col_cost  = 0.1 * 1.02 * 7850.0 * 0.90     # 720.63
        expected = round(wall_cost + col_cost, 4)
        assert abs(d["total_material_cost_usd"] - expected) < 0.01
