"""
test_pricing.py — pytest suite for kerf_woodworking.pricing.

DoD oracles:
  1. material_cost: sheet count × unit price = correct total.
  2. hardware_cost: known hardware key returns correct unit price.
  3. labour_cost: base cabinet 5× at $75/hr → total > 0.
  4. estimate_project_cost: total = mat + hw + lab + overhead.
  5. Overhead is applied as correct % of direct costs.
  6. cost_estimate_to_dict is JSON-serialisable with all required keys.
  7. Unknown hardware key uses default fallback price.
  8. Edge banding cost computed correctly.
  9. Solid lumber cost at known species rate.
  10. Empty inputs return zero costs.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from kerf_woodworking.pricing import (
    estimate_project_cost,
    material_cost,
    hardware_cost,
    labour_cost,
    cost_estimate_to_dict,
    SHEET_COST_USD,
    HARDWARE_UNIT_COST_USD,
    EDGE_BANDING_COST_USD_PER_M,
    SOLID_LUMBER_COST_USD_PER_BF,
    CostEstimate,
)


# ---------------------------------------------------------------------------
# DoD oracle 1: material_cost sheet calculation
# ---------------------------------------------------------------------------

class TestMaterialCost:
    def test_single_sheet_known_material(self):
        """3 sheets of birch_ply_3/4" at $55 each = $165."""
        lines, total = material_cost([{"material": 'birch_ply_3/4"', "sheets": 3.0}])
        expected = 3.0 * SHEET_COST_USD['birch_ply_3/4"']
        assert abs(total - expected) < 0.01, f"Expected {expected:.2f}, got {total:.2f}"

    def test_multiple_materials(self):
        """Correct sum across multiple material types."""
        items = [
            {"material": 'oak_3/4"',    "sheets": 2.0},
            {"material": 'birch_ply_1/4"', "sheets": 1.5},
        ]
        lines, total = material_cost(items)
        expected = (2.0 * SHEET_COST_USD['oak_3/4"']
                    + 1.5 * SHEET_COST_USD['birch_ply_1/4"'])
        assert abs(total - expected) < 0.01

    def test_unknown_material_uses_default(self):
        """Unknown material key falls back to default price."""
        lines, total = material_cost([{"material": "exotic_unknown", "sheets": 1.0}])
        assert total > 0  # default price applied

    def test_empty_sheet_items_zero_total(self):
        lines, total = material_cost([])
        assert total == 0.0
        assert lines == []


# ---------------------------------------------------------------------------
# DoD oracle 2: hardware_cost known prices
# ---------------------------------------------------------------------------

class TestHardwareCost:
    def test_blum_hinge_price(self):
        """4 Blum Clip-Top hinges at known unit price."""
        qty = 4
        lines, total = hardware_cost([
            {"hardware_key": "hinge_blum_clip_top", "quantity": qty}
        ])
        expected = qty * HARDWARE_UNIT_COST_USD["hinge_blum_clip_top"]
        assert abs(total - expected) < 0.01

    def test_drawer_slide_price(self):
        """2 pairs of Blum Movento slides."""
        qty = 2
        lines, total = hardware_cost([
            {"hardware_key": "drawer_slide_blum_movento", "quantity": qty}
        ])
        expected = qty * HARDWARE_UNIT_COST_USD["drawer_slide_blum_movento"]
        assert abs(total - expected) < 0.01

    def test_multiple_hardware_items(self):
        items = [
            {"hardware_key": "hinge_blum_clip_top", "quantity": 6},
            {"hardware_key": "pull_bar_128mm",       "quantity": 4},
            {"hardware_key": "shelf_pins_5mm_x4",    "quantity": 10},
        ]
        _, total = hardware_cost(items)
        expected = (6 * HARDWARE_UNIT_COST_USD["hinge_blum_clip_top"]
                    + 4 * HARDWARE_UNIT_COST_USD["pull_bar_128mm"]
                    + 10 * HARDWARE_UNIT_COST_USD["shelf_pins_5mm_x4"])
        assert abs(total - expected) < 0.01

    def test_empty_hardware_zero(self):
        _, total = hardware_cost([])
        assert total == 0.0


# ---------------------------------------------------------------------------
# DoD oracle 7: unknown hardware key uses default
# ---------------------------------------------------------------------------

class TestHardwareFallback:
    def test_unknown_hardware_key_uses_default(self):
        """Unknown hardware key should not raise — uses fallback."""
        _, total = hardware_cost([{"hardware_key": "mystery_widget", "quantity": 2}])
        assert total > 0


# ---------------------------------------------------------------------------
# DoD oracle 3: labour_cost calculation
# ---------------------------------------------------------------------------

class TestLabourCost:
    def test_base_cabinet_labour_positive(self):
        """5 base cabinets at $75/hr → labour > 0."""
        lines, total = labour_cost({"base": 5}, rate_usd_per_hr=75.0)
        assert total > 0.0
        assert len(lines) > 0

    def test_wall_cabinet_labour(self):
        lines, total = labour_cost({"wall": 3}, rate_usd_per_hr=80.0)
        assert total > 0.0

    def test_mixed_cabinet_types(self):
        lines, total = labour_cost({"base": 4, "wall": 3, "tall": 1}, rate_usd_per_hr=75.0)
        assert total > 0.0
        # More cabinets = more labour
        _, total_less = labour_cost({"base": 1}, rate_usd_per_hr=75.0)
        assert total > total_less

    def test_rate_scales_linearly(self):
        """Doubling the rate doubles the labour total."""
        _, total_75 = labour_cost({"base": 3}, rate_usd_per_hr=75.0)
        _, total_150 = labour_cost({"base": 3}, rate_usd_per_hr=150.0)
        assert abs(total_150 - 2.0 * total_75) < 0.01

    def test_empty_counts_zero(self):
        lines, total = labour_cost({})
        assert total == 0.0

    def test_phase_labels_present(self):
        lines, total = labour_cost({"base": 2})
        phases = {l.phase for l in lines}
        assert "assembly" in phases
        assert "finishing" in phases


# ---------------------------------------------------------------------------
# DoD oracle 4: estimate_project_cost rollup
# ---------------------------------------------------------------------------

class TestEstimateProjectCost:
    def _full_estimate(self, overhead_pct: float = 15.0) -> CostEstimate:
        return estimate_project_cost(
            sheet_items=[{"material": 'birch_ply_3/4"', "sheets": 5.0}],
            edge_banding_items=[{"banding_type": "pvc_white", "lineal_m": 20.0}],
            hardware_items=[
                {"hardware_key": "hinge_blum_clip_top", "quantity": 8},
                {"hardware_key": "drawer_slide_blum_movento", "quantity": 2},
            ],
            cabinet_counts={"base": 4, "wall": 3},
            labour_rate_usd_per_hr=75.0,
            overhead_pct=overhead_pct,
        )

    def test_total_greater_than_zero(self):
        est = self._full_estimate()
        assert est.total_usd > 0.0

    def test_total_equals_parts_plus_overhead(self):
        """total = mat + hw + lab + overhead."""
        est = self._full_estimate(overhead_pct=20.0)
        direct = est.subtotal_material_usd + est.subtotal_hardware_usd + est.subtotal_labour_usd
        expected_total = direct + direct * 0.20
        assert abs(est.total_usd - expected_total) < 0.10, (
            f"total {est.total_usd:.2f} != direct+overhead {expected_total:.2f}"
        )

    def test_components_add_up(self):
        """Material subtotal matches sum of material lines."""
        est = self._full_estimate()
        mat_line_sum = sum(l.total_cost_usd for l in est.material_lines)
        assert abs(est.subtotal_material_usd - mat_line_sum) < 0.01

    def test_hardware_subtotal_correct(self):
        est = self._full_estimate()
        hw_line_sum = sum(l.total_cost_usd for l in est.hardware_lines)
        assert abs(est.subtotal_hardware_usd - hw_line_sum) < 0.01

    def test_labour_subtotal_correct(self):
        est = self._full_estimate()
        lab_line_sum = sum(l.total_cost_usd for l in est.labour_lines)
        assert abs(est.subtotal_labour_usd - lab_line_sum) < 0.01


# ---------------------------------------------------------------------------
# DoD oracle 5: overhead percentage
# ---------------------------------------------------------------------------

class TestOverhead:
    def test_overhead_applied_at_correct_pct(self):
        """With 10% overhead, overhead_usd = 10% of direct costs."""
        est = estimate_project_cost(
            sheet_items=[{"material": 'oak_3/4"', "sheets": 3.0}],
            overhead_pct=10.0,
        )
        direct = (est.subtotal_material_usd + est.subtotal_hardware_usd
                  + est.subtotal_labour_usd)
        expected_overhead = direct * 0.10
        assert abs(est.overhead_usd - expected_overhead) < 0.01

    def test_zero_overhead_no_markup(self):
        est = estimate_project_cost(
            sheet_items=[{"material": 'birch_ply_3/4"', "sheets": 2.0}],
            overhead_pct=0.0,
        )
        direct = (est.subtotal_material_usd + est.subtotal_hardware_usd
                  + est.subtotal_labour_usd)
        assert abs(est.total_usd - direct) < 0.01


# ---------------------------------------------------------------------------
# DoD oracle 6: JSON-serialisable
# ---------------------------------------------------------------------------

class TestCostEstimateDict:
    def test_json_serialisable(self):
        est = estimate_project_cost(
            sheet_items=[{"material": 'mdf_3/4"', "sheets": 2.0}],
            hardware_items=[{"hardware_key": "pocket_screws_32mm_x100", "quantity": 3}],
        )
        d = cost_estimate_to_dict(est)
        json.dumps(d)  # must not raise

    def test_dict_has_expected_keys(self):
        est = estimate_project_cost()
        d = cost_estimate_to_dict(est)
        for key in ("total_usd", "subtotal_material_usd", "subtotal_hardware_usd",
                    "subtotal_labour_usd", "overhead_usd", "overhead_pct",
                    "material_lines", "hardware_lines", "labour_lines", "honest_caveat"):
            assert key in d, f"Key '{key}' missing from cost_estimate dict"


# ---------------------------------------------------------------------------
# DoD oracle 8: edge banding cost
# ---------------------------------------------------------------------------

class TestEdgeBandingCost:
    def test_edge_banding_cost_correct(self):
        """20 m of pvc_white at known rate."""
        rate = EDGE_BANDING_COST_USD_PER_M["pvc_white"]
        lines, total = material_cost([], edge_banding_items=[
            {"banding_type": "pvc_white", "lineal_m": 20.0}
        ])
        assert abs(total - 20.0 * rate) < 0.01

    def test_none_banding_zero_cost(self):
        lines, total = material_cost([], edge_banding_items=[
            {"banding_type": "none", "lineal_m": 100.0}
        ])
        assert total == 0.0


# ---------------------------------------------------------------------------
# DoD oracle 9: solid lumber cost
# ---------------------------------------------------------------------------

class TestSolidLumberCost:
    def test_walnut_more_expensive_than_pine(self):
        """Walnut should cost more than pine per board-foot."""
        _, walnut_total = material_cost([], solid_lumber_items=[
            {"species": "walnut", "board_feet": 10.0}
        ])
        _, pine_total = material_cost([], solid_lumber_items=[
            {"species": "pine", "board_feet": 10.0}
        ])
        assert walnut_total > pine_total

    def test_oak_price_correct(self):
        bf = 5.0
        rate = SOLID_LUMBER_COST_USD_PER_BF["oak_red"]
        _, total = material_cost([], solid_lumber_items=[
            {"species": "oak_red", "board_feet": bf}
        ])
        assert abs(total - bf * rate) < 0.01


# ---------------------------------------------------------------------------
# DoD oracle 10: empty inputs
# ---------------------------------------------------------------------------

class TestEmptyInputs:
    def test_all_empty_returns_zero_total(self):
        est = estimate_project_cost()
        assert est.total_usd == 0.0

    def test_no_sheets_zero_material(self):
        est = estimate_project_cost(sheet_items=[])
        assert est.subtotal_material_usd == 0.0

    def test_no_hardware_zero_hw(self):
        est = estimate_project_cost(hardware_items=[])
        assert est.subtotal_hardware_usd == 0.0
