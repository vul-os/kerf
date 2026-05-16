"""
Tests for kerf_cad_core.jewelry.production

Pure-Python: no OCC, no database, no project context required.
All tests run hermetically with no external dependencies.

Covers (≥30 tests):
  - shrink_compensate: exact scale factor per alloy, boundary, monotonicity
  - sprue_diameter_mm: monotonic in volume, clamp limits
  - casting_tree: tree weight = Σ part + sprue volumes × density; structure
  - hallmark_spec: fineness mapping correct for 750/585/950/925; non-precious
  - production_weights: wax vs resin density, batch scaling
  - batch_cost: full decomposition, markup, batch = n × each
  - ring_resize: circumference = π·d; scale factor; metal_change_note
  - polish_stock: rough volume > finished; stock_pct computation
  - LLM tool runners: happy-path ok, missing args err, bad args err
"""

from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_cad_core.jewelry.production import (
    WAX_DENSITY_G_CM3,
    RESIN_DENSITY_G_CM3,
    _POLISH_STOCK_DEFAULT_MM,
    _SPRUE_DIA_MIN_MM,
    _SPRUE_DIA_MAX_MM,
    shrink_compensate,
    sprue_diameter_mm,
    casting_tree,
    hallmark_spec,
    production_weights,
    batch_cost,
    ring_resize,
    polish_stock,
)
from kerf_cad_core.jewelry.casting_export import SHRINKAGE_PCT
from kerf_cad_core.jewelry.metal_cost import METAL_DENSITY_G_CM3, METAL_HALLMARK


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _run_tool(tool_fn, **kwargs) -> dict:
    raw = asyncio.new_event_loop().run_until_complete(
        tool_fn(None, json.dumps(kwargs).encode())
    )
    return json.loads(raw)


def approx(v, rel=1e-4):
    return pytest.approx(v, rel=rel)


# ============================================================================
# 1. shrink_compensate — mold-shrinkage compensation
# ============================================================================

class TestShrinkCompensate:
    def test_18k_yellow_scale_factor(self):
        """Scale = 1 / (1 - 0.0125) for 18k_yellow."""
        result = shrink_compensate(10.0, "18k_yellow")
        expected_scale = 1.0 / (1.0 - 1.25 / 100.0)
        assert result["scale_factor"] == approx(expected_scale)

    def test_platinum_950_scale_factor(self):
        """Scale = 1 / (1 - 0.018) for platinum_950."""
        result = shrink_compensate(20.0, "platinum_950")
        expected_scale = 1.0 / (1.0 - 1.80 / 100.0)
        assert result["scale_factor"] == approx(expected_scale)

    def test_sterling_925_scale_factor(self):
        """Scale = 1 / (1 - 0.014) for sterling_925."""
        result = shrink_compensate(15.0, "sterling_925")
        expected_scale = 1.0 / (1.0 - 1.40 / 100.0)
        assert result["scale_factor"] == approx(expected_scale)

    def test_compensated_mm_correct(self):
        """compensated_mm = dimension_mm × scale_factor."""
        dim = 12.5
        result = shrink_compensate(dim, "18k_yellow")
        assert result["compensated_mm"] == approx(dim * result["scale_factor"])

    def test_compensated_larger_than_input(self):
        """Wax pattern must always be larger than finished dimension."""
        result = shrink_compensate(10.0, "sterling_925")
        assert result["compensated_mm"] > 10.0

    def test_all_alloys_have_valid_scale_factor(self):
        """Every alloy in SHRINKAGE_PCT produces a scale > 1."""
        for key in SHRINKAGE_PCT:
            r = shrink_compensate(5.0, key)
            assert r["scale_factor"] > 1.0, f"scale_factor <= 1 for {key}"

    def test_platinum_scale_greater_than_gold(self):
        """Platinum shrinks more → larger scale factor than 18k yellow."""
        pt = shrink_compensate(10.0, "platinum_950")["scale_factor"]
        gold = shrink_compensate(10.0, "18k_yellow")["scale_factor"]
        assert pt > gold

    def test_non_positive_dimension_raises(self):
        with pytest.raises(ValueError):
            shrink_compensate(0.0, "18k_yellow")

    def test_negative_dimension_raises(self):
        with pytest.raises(ValueError):
            shrink_compensate(-5.0, "18k_yellow")


# ============================================================================
# 2. sprue_diameter_mm — monotonic in volume, clamped
# ============================================================================

class TestSprueeDiameter:
    def test_minimum_clamp(self):
        """Very small pieces clamp to minimum sprue diameter."""
        assert sprue_diameter_mm(1.0) == approx(_SPRUE_DIA_MIN_MM)

    def test_maximum_clamp(self):
        """Very large pieces clamp to maximum sprue diameter."""
        assert sprue_diameter_mm(1e8) == approx(_SPRUE_DIA_MAX_MM)

    def test_monotonic_in_volume(self):
        """Larger volume → larger or equal sprue diameter."""
        vols = [100.0, 500.0, 1000.0, 3000.0, 8000.0, 50000.0]
        dias = [sprue_diameter_mm(v) for v in vols]
        for i in range(len(dias) - 1):
            assert dias[i] <= dias[i + 1], (
                f"sprue_dia not monotonic: {vols[i]}→{dias[i]}, {vols[i+1]}→{dias[i+1]}"
            )

    def test_result_within_bounds(self):
        for v in [50.0, 200.0, 1000.0, 5000.0, 20000.0]:
            d = sprue_diameter_mm(v)
            assert _SPRUE_DIA_MIN_MM <= d <= _SPRUE_DIA_MAX_MM

    def test_zero_volume_raises(self):
        with pytest.raises(ValueError):
            sprue_diameter_mm(0.0)

    def test_negative_volume_raises(self):
        with pytest.raises(ValueError):
            sprue_diameter_mm(-100.0)


# ============================================================================
# 3. casting_tree — tree weight, structure
# ============================================================================

class TestCastingTree:
    def test_tree_weight_equals_parts_plus_trunk(self):
        """tree_metal_weight_g = pieces_weight_g + trunk_weight_g."""
        vol = 1000.0
        result = casting_tree(vol, "18k_yellow", n_pieces=4)
        # pieces weight
        density = METAL_DENSITY_G_CM3["18k_yellow"]
        piece_g = density * (vol / 1000.0)
        pieces_g = piece_g * 4
        # trunk weight
        trunk_vol = result["sprue_trunk_volume_mm3"]
        trunk_g = (trunk_vol / 1000.0) * density
        expected_tree_g = pieces_g + trunk_g
        assert result["tree_metal_weight_g"] == approx(expected_tree_g)

    def test_tree_weight_gt_pieces_weight(self):
        """Tree weight must exceed pieces-only weight (trunk adds overhead)."""
        result = casting_tree(800.0, "sterling_925", n_pieces=6)
        assert result["tree_metal_weight_g"] > result["pieces_weight_g"]

    def test_n_pieces_scales_pieces_weight(self):
        """Doubling n_pieces doubles pieces_weight_g."""
        r6 = casting_tree(500.0, "18k_yellow", n_pieces=6)
        r12 = casting_tree(500.0, "18k_yellow", n_pieces=12)
        assert r12["pieces_weight_g"] == approx(r6["pieces_weight_g"] * 2)

    def test_sprue_dia_monotonic(self):
        """Larger piece volume → larger piece_sprue_dia_mm."""
        small = casting_tree(200.0, "18k_yellow")["piece_sprue_dia_mm"]
        large = casting_tree(4000.0, "18k_yellow")["piece_sprue_dia_mm"]
        assert large >= small

    def test_flask_yield_between_0_and_100(self):
        result = casting_tree(1000.0, "18k_yellow", n_pieces=6)
        assert 0.0 < result["flask_yield_pct"] <= 100.0

    def test_wax_weight_uses_wax_density(self):
        """wax_weight_g = volume_cm3 × WAX_DENSITY_G_CM3."""
        vol = 1200.0
        result = casting_tree(vol, "18k_yellow", n_pieces=1)
        expected = (vol / 1000.0) * WAX_DENSITY_G_CM3
        assert result["wax_weight_g"] == approx(expected)

    def test_tree_wax_weight_scales_with_n_pieces(self):
        r = casting_tree(600.0, "sterling_925", n_pieces=5)
        assert r["tree_wax_weight_g"] == approx(r["wax_weight_g"] * 5)

    def test_required_keys_present(self):
        result = casting_tree(1000.0, "18k_yellow")
        for key in (
            "piece_sprue_dia_mm", "trunk_dia_mm", "pieces_weight_g",
            "tree_metal_weight_g", "flask_yield_pct", "wax_weight_g",
        ):
            assert key in result, f"Missing key: {key}"

    def test_unknown_alloy_raises(self):
        with pytest.raises(ValueError):
            casting_tree(1000.0, "unobtanium_999")

    def test_zero_n_pieces_raises(self):
        with pytest.raises(ValueError):
            casting_tree(1000.0, "18k_yellow", n_pieces=0)


# ============================================================================
# 4. hallmark_spec — fineness mapping
# ============================================================================

class TestHallmarkSpec:
    def test_18k_yellow_fineness_750(self):
        result = hallmark_spec("18k_yellow")
        assert result["fineness_stamp"] == "750"

    def test_14k_yellow_fineness_583(self):
        result = hallmark_spec("14k_yellow")
        assert result["fineness_stamp"] == "583"

    def test_platinum_950_fineness_950(self):
        result = hallmark_spec("platinum_950")
        assert result["fineness_stamp"] == "950"

    def test_sterling_925_fineness_925(self):
        result = hallmark_spec("sterling_925")
        assert result["fineness_stamp"] == "925"

    def test_non_precious_no_fineness_stamp(self):
        """Brass, bronze, titanium carry only maker mark — fineness = '—'."""
        for key in ("titanium", "brass", "bronze"):
            r = hallmark_spec(key)
            assert r["fineness_stamp"] == "—", f"Expected '—' for {key}"

    def test_full_stamp_contains_fineness_and_maker(self):
        result = hallmark_spec("18k_yellow", maker_mark="TEST")
        assert "750" in result["full_stamp"]
        assert "TEST" in result["full_stamp"]

    def test_maker_mark_truncated_to_8_chars(self):
        result = hallmark_spec("18k_yellow", maker_mark="VERYLONGMARK")
        assert len(result["maker_mark"]) <= 8

    def test_all_alloys_return_fineness_consistent_with_hallmark_table(self):
        """fineness_stamp must match METAL_HALLMARK for every alloy."""
        for key in METAL_DENSITY_G_CM3:
            r = hallmark_spec(key)
            expected = METAL_HALLMARK.get(key)
            if expected is not None:
                assert r["fineness_stamp"] == str(expected), (
                    f"Mismatch for {key}: got {r['fineness_stamp']!r}, "
                    f"expected {str(expected)!r}"
                )

    def test_unknown_alloy_raises(self):
        with pytest.raises(ValueError):
            hallmark_spec("unobtanium_999")


# ============================================================================
# 5. production_weights — wax/resin and metal weight
# ============================================================================

class TestProductionWeights:
    def test_wax_weight_uses_wax_density(self):
        vol = 500.0
        r = production_weights(vol, "18k_yellow", material="wax")
        expected = (vol / 1000.0) * WAX_DENSITY_G_CM3
        assert r["wax_weight_g"] == approx(expected)

    def test_resin_weight_uses_resin_density(self):
        vol = 500.0
        r = production_weights(vol, "18k_yellow", material="resin")
        expected = (vol / 1000.0) * RESIN_DENSITY_G_CM3
        assert r["wax_weight_g"] == approx(expected)

    def test_resin_heavier_than_wax(self):
        """Resin density > wax density → heavier pattern."""
        wax = production_weights(1000.0, "18k_yellow", material="wax")["wax_weight_g"]
        resin = production_weights(1000.0, "18k_yellow", material="resin")["wax_weight_g"]
        assert resin > wax

    def test_batch_scales_linearly(self):
        r1 = production_weights(800.0, "sterling_925", n_pieces=1)
        r5 = production_weights(800.0, "sterling_925", n_pieces=5)
        assert r5["batch_wax_weight_g"] == approx(r1["wax_weight_g"] * 5)
        assert r5["batch_metal_weight_g"] == approx(r1["metal_weight_g"] * 5)

    def test_metal_heavier_than_wax_for_gold(self):
        """Gold density >> wax density → metal_weight_g > wax_weight_g."""
        r = production_weights(1000.0, "18k_yellow")
        assert r["metal_weight_g"] > r["wax_weight_g"]

    def test_invalid_material_raises(self):
        with pytest.raises(ValueError):
            production_weights(500.0, "18k_yellow", material="clay")


# ============================================================================
# 6. batch_cost — cost rollup decomposition
# ============================================================================

class TestBatchCost:
    def test_subtotal_equals_sum_of_components(self):
        """subtotal_each = metal + casting_fee + labour + stones."""
        r = batch_cost(
            1000.0, "18k_yellow",
            metal_price_per_gram=48.0,
            casting_fee_per_piece=15.0,
            labour_per_piece=25.0,
            stone_cost_per_piece=100.0,
        )
        expected = (
            r["metal_cost_each"] +
            r["casting_fee_each"] +
            r["labour_each"] +
            r["stone_cost_each"]
        )
        assert r["subtotal_each"] == approx(expected)

    def test_batch_total_equals_n_times_each(self):
        """batch_total = n_pieces × total_each (via markup symmetry)."""
        r = batch_cost(800.0, "sterling_925", n_pieces=5, metal_price_per_gram=0.80)
        assert r["batch_total"] == approx(r["total_each"] * 5)

    def test_markup_applied_correctly(self):
        """total_each = subtotal_each × (1 + markup_pct/100)."""
        r = batch_cost(1000.0, "18k_yellow", metal_price_per_gram=48.0, markup_pct=20.0)
        expected = r["subtotal_each"] * 1.20
        assert r["total_each"] == approx(expected)

    def test_zero_price_gives_zero_metal_cost(self):
        r = batch_cost(500.0, "18k_yellow", metal_price_per_gram=0.0)
        assert r["metal_cost_each"] == approx(0.0)

    def test_batch_metal_cost_equals_n_times_each(self):
        r = batch_cost(600.0, "14k_yellow", n_pieces=10, metal_price_per_gram=37.5)
        assert r["batch_metal_cost"] == approx(r["metal_cost_each"] * 10)

    def test_negative_price_raises(self):
        with pytest.raises(ValueError):
            batch_cost(500.0, "18k_yellow", metal_price_per_gram=-1.0)

    def test_unknown_alloy_raises(self):
        with pytest.raises(ValueError):
            batch_cost(500.0, "unobtanium_999")

    def test_zero_n_pieces_raises(self):
        with pytest.raises(ValueError):
            batch_cost(500.0, "18k_yellow", n_pieces=0)


# ============================================================================
# 7. ring_resize — circumference = π·d; scale factor
# ============================================================================

class TestRingResize:
    def test_circumference_equals_pi_times_diameter(self):
        """C = π·d for both from and to sizes."""
        r = ring_resize(6.0, 8.0, "US")
        assert r["from_circumference_mm"] == approx(math.pi * r["from_diameter_mm"])
        assert r["to_circumference_mm"] == approx(math.pi * r["to_diameter_mm"])

    def test_scale_factor_is_diameter_ratio(self):
        """scale_factor = to_diameter / from_diameter."""
        r = ring_resize(5.0, 7.0, "US")
        expected = r["to_diameter_mm"] / r["from_diameter_mm"]
        assert r["scale_factor"] == approx(expected)

    def test_same_size_gives_scale_1(self):
        r = ring_resize(7.0, 7.0, "US")
        assert r["scale_factor"] == approx(1.0)
        assert r["metal_change_note"] == "no_change"

    def test_sizing_up_adds_metal(self):
        r = ring_resize(5.0, 8.0, "US")
        assert r["metal_change_note"] == "add_metal"
        assert r["scale_factor"] > 1.0

    def test_sizing_down_removes_metal(self):
        r = ring_resize(8.0, 5.0, "US")
        assert r["metal_change_note"] == "remove_metal"
        assert r["scale_factor"] < 1.0

    def test_us_ring_5_diameter(self):
        """US size 5 → inner diameter = 11.63 + 0.8128×5 = 15.694 mm."""
        r = ring_resize(5.0, 5.0, "US")
        assert r["from_diameter_mm"] == approx(11.63 + 0.8128 * 5, rel=1e-3)

    def test_us_ring_7_diameter(self):
        """US size 7 → inner diameter = 11.63 + 0.8128×7 = 17.3196 mm."""
        r = ring_resize(7.0, 7.0, "US")
        assert r["from_diameter_mm"] == approx(11.63 + 0.8128 * 7, rel=1e-3)


# ============================================================================
# 8. polish_stock — rough volume > finished; stock_pct
# ============================================================================

class TestPolishStock:
    def test_rough_volume_gt_finished(self):
        r = polish_stock(1000.0, 5.0)
        assert r["rough_volume_mm3"] > 1000.0

    def test_stock_pct_correct(self):
        """stock_pct = stock_volume / finished_volume × 100."""
        r = polish_stock(1000.0, 5.0, stock_mm=0.15, sides=3)
        expected_pct = (r["stock_volume_mm3"] / 1000.0) * 100.0
        assert r["stock_pct"] == approx(expected_pct)

    def test_zero_stock_returns_unchanged_volume(self):
        r = polish_stock(800.0, 4.0, stock_mm=0.0)
        assert r["rough_volume_mm3"] == approx(800.0)
        assert r["stock_pct"] == approx(0.0)

    def test_more_sides_increases_stock(self):
        r3 = polish_stock(1000.0, 5.0, sides=3)
        r5 = polish_stock(1000.0, 5.0, sides=5)
        assert r5["stock_volume_mm3"] > r3["stock_volume_mm3"]

    def test_thicker_stock_increases_overhead(self):
        r1 = polish_stock(1000.0, 5.0, stock_mm=0.10)
        r2 = polish_stock(1000.0, 5.0, stock_mm=0.30)
        assert r2["stock_volume_mm3"] > r1["stock_volume_mm3"]

    def test_negative_volume_raises(self):
        with pytest.raises(ValueError):
            polish_stock(0.0, 5.0)

    def test_negative_stock_mm_raises(self):
        with pytest.raises(ValueError):
            polish_stock(1000.0, 5.0, stock_mm=-0.1)


# ============================================================================
# 9. LLM tool runners — happy path and error paths
# ============================================================================

class TestLLMTools:
    # jewelry_shrink_compensate
    def test_shrink_tool_happy_path(self):
        from kerf_cad_core.jewelry.production import run_jewelry_shrink_compensate as fn
        r = _run_tool(fn, dimension_mm=10.0, alloy_key="18k_yellow")
        assert "scale_factor" in r
        assert r["scale_factor"] == approx(1.0 / (1.0 - 0.0125))

    def test_shrink_tool_missing_dimension(self):
        from kerf_cad_core.jewelry.production import run_jewelry_shrink_compensate as fn
        r = _run_tool(fn, alloy_key="18k_yellow")
        assert "error" in r

    def test_shrink_tool_unknown_alloy(self):
        from kerf_cad_core.jewelry.production import run_jewelry_shrink_compensate as fn
        r = _run_tool(fn, dimension_mm=10.0, alloy_key="unobtanium_x")
        assert "error" in r

    # jewelry_casting_tree
    def test_casting_tree_tool_happy_path(self):
        from kerf_cad_core.jewelry.production import run_jewelry_casting_tree as fn
        r = _run_tool(fn, piece_volume_mm3=1000.0, alloy_key="18k_yellow", n_pieces=4)
        assert "tree_metal_weight_g" in r
        assert r["n_pieces"] == 4

    def test_casting_tree_tool_missing_volume(self):
        from kerf_cad_core.jewelry.production import run_jewelry_casting_tree as fn
        r = _run_tool(fn, alloy_key="18k_yellow")
        assert "error" in r

    # jewelry_hallmark_spec
    def test_hallmark_tool_18k_yellow(self):
        from kerf_cad_core.jewelry.production import run_jewelry_hallmark_spec as fn
        r = _run_tool(fn, alloy_key="18k_yellow", maker_mark="MRKR")
        assert r["fineness_stamp"] == "750"
        assert "MRKR" in r["full_stamp"]

    def test_hallmark_tool_missing_alloy(self):
        from kerf_cad_core.jewelry.production import run_jewelry_hallmark_spec as fn
        r = _run_tool(fn)
        assert "error" in r

    # jewelry_production_weights
    def test_weights_tool_happy_path(self):
        from kerf_cad_core.jewelry.production import run_jewelry_production_weights as fn
        r = _run_tool(fn, piece_volume_mm3=800.0, alloy_key="sterling_925", n_pieces=3)
        assert "batch_metal_weight_g" in r
        assert r["n_pieces"] == 3

    # jewelry_batch_cost
    def test_batch_cost_tool_happy_path(self):
        from kerf_cad_core.jewelry.production import run_jewelry_batch_cost as fn
        r = _run_tool(
            fn,
            piece_volume_mm3=1000.0,
            alloy_key="18k_yellow",
            n_pieces=5,
            metal_price_per_gram=48.0,
            casting_fee_per_piece=10.0,
            labour_per_piece=20.0,
        )
        assert "batch_total" in r
        assert r["batch_total"] == approx(r["total_each"] * 5)

    def test_batch_cost_tool_missing_alloy(self):
        from kerf_cad_core.jewelry.production import run_jewelry_batch_cost as fn
        r = _run_tool(fn, piece_volume_mm3=1000.0)
        assert "error" in r

    # jewelry_ring_resize
    def test_ring_resize_tool_happy_path(self):
        from kerf_cad_core.jewelry.production import run_jewelry_ring_resize as fn
        r = _run_tool(fn, from_size=6.0, to_size=8.0, system="US")
        assert "scale_factor" in r
        assert r["scale_factor"] > 1.0

    def test_ring_resize_tool_missing_to_size(self):
        from kerf_cad_core.jewelry.production import run_jewelry_ring_resize as fn
        r = _run_tool(fn, from_size=6.0)
        assert "error" in r

    # jewelry_polish_stock
    def test_polish_stock_tool_happy_path(self):
        from kerf_cad_core.jewelry.production import run_jewelry_polish_stock as fn
        r = _run_tool(fn, volume_mm3=1000.0, avg_dimension_mm=5.0)
        assert "rough_volume_mm3" in r
        assert r["rough_volume_mm3"] > 1000.0

    def test_polish_stock_tool_missing_avg_dimension(self):
        from kerf_cad_core.jewelry.production import run_jewelry_polish_stock as fn
        r = _run_tool(fn, volume_mm3=1000.0)
        assert "error" in r
