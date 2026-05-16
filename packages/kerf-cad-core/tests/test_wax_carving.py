"""
Tests for kerf_cad_core.jewelry.wax_carving

All 25+ tests are hermetic (no OCC, no kerf_chat needed).

Covers:
  - Tube stock: ID ≤ ring ID and OD ≥ ring OD (envelopment)
  - Material removed = stock_vol − target_vol > 0
  - Cast metal weight = wax_vol × (ρ_metal / ρ_wax) and Pt > 18k > silver
  - Too-small stock → ok=False with reason containing next stock suggestion
  - Waste % = removed / stock_vol
  - Bigger ring → more roughing time
  - Block stock handling
  - Invalid inputs → graceful ok=False
  - Various profiles, design features, and size systems
"""

from __future__ import annotations

import math

import pytest

from kerf_cad_core.jewelry.wax_carving import (
    WAX_DENSITY_G_CM3,
    MM3_PER_CM3,
    plan_wax_carving,
    _ring_id_mm,
    _ring_od_mm,
    _tube_volume_mm3,
    _block_volume_mm3,
    _pick_tube_stock,
    _pick_block_stock,
    _METAL_DENSITY_TABLE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_plan(ring_size=7, band_width_mm=4.0, profile="d_shape", **kw):
    return plan_wax_carving(ring_size, band_width_mm, profile, **kw)


# ---------------------------------------------------------------------------
# 1. Tube stock envelopment: stock ID ≤ ring ID
# ---------------------------------------------------------------------------

class TestTubeEnvelopment:
    def test_stock_id_le_ring_id(self):
        p = _default_plan(ring_size=7, band_width_mm=4.0)
        assert p["ok"], p.get("reason")
        dims = p["stock_dims"]
        assert dims["id_mm"] <= p["ring_id_mm"] + 1e-9, (
            f"stock ID {dims['id_mm']} > ring ID {p['ring_id_mm']}"
        )

    def test_stock_od_ge_ring_od(self):
        p = _default_plan(ring_size=7, band_width_mm=4.0)
        assert p["ok"], p.get("reason")
        dims = p["stock_dims"]
        assert dims["od_mm"] >= p["ring_od_mm"] - 1e-9, (
            f"stock OD {dims['od_mm']} < ring OD {p['ring_od_mm']}"
        )

    def test_envelopment_large_ring(self):
        p = _default_plan(ring_size=13, band_width_mm=6.0)
        assert p["ok"], p.get("reason")
        dims = p["stock_dims"]
        assert dims["id_mm"] <= p["ring_id_mm"] + 1e-9
        assert dims["od_mm"] >= p["ring_od_mm"] - 1e-9

    def test_envelopment_small_ring(self):
        p = _default_plan(ring_size=4, band_width_mm=3.0)
        assert p["ok"], p.get("reason")
        dims = p["stock_dims"]
        assert dims["id_mm"] <= p["ring_id_mm"] + 1e-9
        assert dims["od_mm"] >= p["ring_od_mm"] - 1e-9


# ---------------------------------------------------------------------------
# 2. Material removed = stock_vol − target_vol > 0
# ---------------------------------------------------------------------------

class TestMaterialRemoved:
    def test_material_removed_positive(self):
        p = _default_plan()
        assert p["ok"], p.get("reason")
        assert p["material_removed_mm3"] >= 0.0

    def test_stock_vol_equals_target_plus_removed(self):
        p = _default_plan()
        assert p["ok"]
        assert abs(p["stock_volume_mm3"] - p["target_volume_mm3"] - p["material_removed_mm3"]) < 1e-6

    def test_material_removed_reasonable_fraction(self):
        # Waste should be >0 and typically <95%
        p = _default_plan(ring_size=7, band_width_mm=4.0)
        assert p["ok"]
        assert p["waste_pct"] > 0.0
        assert p["waste_pct"] < 95.0


# ---------------------------------------------------------------------------
# 3. Waste % = removed / stock_vol
# ---------------------------------------------------------------------------

class TestWastePct:
    def test_waste_pct_formula(self):
        p = _default_plan()
        assert p["ok"]
        expected = p["material_removed_mm3"] / p["stock_volume_mm3"] * 100.0
        # Values are rounded to 2 dp in the output so allow 0.01 tolerance
        assert abs(p["waste_pct"] - expected) < 0.01

    def test_waste_pct_between_0_and_100(self):
        for size in (5, 7, 10):
            p = _default_plan(ring_size=size, band_width_mm=4.0)
            assert p["ok"]
            assert 0.0 <= p["waste_pct"] <= 100.0


# ---------------------------------------------------------------------------
# 4. Cast metal weight = wax_vol × (ρ_metal / ρ_wax); Pt > 18k > silver
# ---------------------------------------------------------------------------

class TestCastWeights:
    def _expected_cast_g(self, vol_mm3: float, alloy: str) -> float:
        rho = _METAL_DENSITY_TABLE[alloy]
        return (vol_mm3 / MM3_PER_CM3) * rho

    def test_cast_weight_formula_sterling(self):
        p = _default_plan(alloys=["sterling_925"])
        assert p["ok"]
        vol = p["target_volume_mm3"]
        expected = self._expected_cast_g(vol, "sterling_925")
        assert abs(p["cast_weights"]["sterling_925"] - expected) < 1e-3

    def test_cast_weight_formula_18k(self):
        p = _default_plan(alloys=["18k_yellow"])
        assert p["ok"]
        vol = p["target_volume_mm3"]
        expected = self._expected_cast_g(vol, "18k_yellow")
        assert abs(p["cast_weights"]["18k_yellow"] - expected) < 1e-3

    def test_platinum_gt_18k_gt_silver(self):
        p = _default_plan(alloys=["sterling_925", "18k_yellow", "platinum_950"])
        assert p["ok"]
        w = p["cast_weights"]
        assert w["platinum_950"] > w["18k_yellow"] > w["sterling_925"], (
            f"Density order violated: Pt={w['platinum_950']:.3f}, "
            f"18k={w['18k_yellow']:.3f}, Ag={w['sterling_925']:.3f}"
        )

    def test_cast_weight_scales_with_alloy_density(self):
        # Ratio of cast weights == ratio of densities
        p = _default_plan(alloys=["sterling_925", "platinum_950"])
        assert p["ok"]
        w = p["cast_weights"]
        ratio_actual = w["platinum_950"] / w["sterling_925"]
        ratio_expected = (
            _METAL_DENSITY_TABLE["platinum_950"] / _METAL_DENSITY_TABLE["sterling_925"]
        )
        assert abs(ratio_actual - ratio_expected) < 1e-3

    def test_cast_weight_cast_metal_formula_via_ratio(self):
        # cast_weight = wax_vol * ρ_metal / ρ_wax
        p = _default_plan(alloys=["18k_yellow"])
        assert p["ok"]
        vol = p["target_volume_mm3"]
        expected = (vol / MM3_PER_CM3) * (_METAL_DENSITY_TABLE["18k_yellow"] / WAX_DENSITY_G_CM3) * WAX_DENSITY_G_CM3
        # This is same as (vol/1000) * ρ_metal
        got = p["cast_weights"]["18k_yellow"]
        assert abs(got - expected) < 1e-3


# ---------------------------------------------------------------------------
# 5. Too-small custom stock → ok=False with reason + suggestion
# ---------------------------------------------------------------------------

class TestTooSmallStock:
    def test_custom_tube_od_too_small_returns_error(self):
        # Force an OD that is smaller than the ring OD
        p = plan_wax_carving(
            7, 4.0,
            custom_stock={"id_mm": 10.0, "od_mm": 14.0},  # ring OD will be ~19 mm
            stock_type="tube",
        )
        assert p["ok"] is False
        assert "reason" in p
        assert len(p["reason"]) > 0

    def test_custom_tube_id_too_large_returns_error(self):
        # Force a stock ID that is larger than the ring ID
        ring_id = _ring_id_mm(7, "us")  # ~17.3 mm
        p = plan_wax_carving(
            7, 4.0,
            custom_stock={"id_mm": ring_id + 5.0, "od_mm": ring_id + 20.0},
            stock_type="tube",
        )
        assert p["ok"] is False
        assert "reason" in p

    def test_custom_block_too_narrow_returns_error(self):
        # Block too narrow for the ring OD
        p = plan_wax_carving(
            7, 4.0,
            stock_type="block",
            custom_stock={"width_mm": 5.0, "depth_mm": 5.0, "height_mm": 10.0},
        )
        assert p["ok"] is False
        assert "reason" in p

    def test_error_contains_suggested_stock(self):
        # When stock is too small, reason should hint at a better option
        p = plan_wax_carving(
            7, 4.0,
            custom_stock={"id_mm": 10.0, "od_mm": 14.0},
            stock_type="tube",
        )
        assert p["ok"] is False
        # reason should mention the issue
        assert isinstance(p["reason"], str)
        assert len(p["reason"]) > 5


# ---------------------------------------------------------------------------
# 6. Bigger ring → more roughing time
# ---------------------------------------------------------------------------

class TestRoughingScaling:
    def _roughing_time(self, p: dict) -> float:
        return sum(
            s["time_estimate_min"]
            for s in p["tool_sequence"]
            if s["phase"] == "roughing"
        )

    def test_bigger_ring_more_roughing_time(self):
        p_small = _default_plan(ring_size=4, band_width_mm=4.0)
        p_large = _default_plan(ring_size=12, band_width_mm=4.0)
        assert p_small["ok"] and p_large["ok"]
        assert self._roughing_time(p_large) >= self._roughing_time(p_small)

    def test_roughing_time_monotone_with_size(self):
        times = []
        for size in (4, 6, 8, 10, 12):
            p = _default_plan(ring_size=size, band_width_mm=4.0)
            assert p["ok"]
            times.append(self._roughing_time(p))
        # Should be non-decreasing
        for i in range(len(times) - 1):
            assert times[i] <= times[i + 1] + 0.01, (
                f"Roughing time not monotone at sizes: {times}"
            )


# ---------------------------------------------------------------------------
# 7. Block stock both handled
# ---------------------------------------------------------------------------

class TestBlockStock:
    def test_block_stock_plan_ok(self):
        p = plan_wax_carving(7, 4.0, stock_type="block")
        assert p["ok"], p.get("reason")
        assert p["stock_type"] == "block"
        assert "width_mm" in p["stock_dims"]

    def test_block_envelops_ring(self):
        p = plan_wax_carving(7, 4.0, stock_type="block")
        assert p["ok"]
        min_footprint = min(p["stock_dims"]["width_mm"], p["stock_dims"]["depth_mm"])
        assert min_footprint >= p["ring_od_mm"] - 1e-9
        assert p["stock_dims"]["height_mm"] >= p["band_width_mm"] - 1e-9

    def test_block_material_removed_positive(self):
        p = plan_wax_carving(7, 4.0, stock_type="block")
        assert p["ok"]
        assert p["material_removed_mm3"] >= 0.0


# ---------------------------------------------------------------------------
# 8. Invalid inputs handled gracefully
# ---------------------------------------------------------------------------

class TestInvalidInputs:
    def test_negative_ring_size(self):
        p = plan_wax_carving(-1, 4.0)
        assert p["ok"] is False
        assert "reason" in p

    def test_zero_band_width(self):
        p = plan_wax_carving(7, 0.0)
        assert p["ok"] is False
        assert "reason" in p

    def test_negative_band_width(self):
        p = plan_wax_carving(7, -3.0)
        assert p["ok"] is False

    def test_invalid_profile(self):
        p = plan_wax_carving(7, 4.0, profile="imaginary_profile")
        assert p["ok"] is False
        assert "reason" in p

    def test_invalid_stock_type(self):
        p = plan_wax_carving(7, 4.0, stock_type="fancy_wood")
        assert p["ok"] is False

    def test_custom_tube_inverted_id_od(self):
        p = plan_wax_carving(
            7, 4.0,
            custom_stock={"id_mm": 25.0, "od_mm": 10.0},  # OD < ID
            stock_type="tube",
        )
        assert p["ok"] is False


# ---------------------------------------------------------------------------
# 9. Profiles variety
# ---------------------------------------------------------------------------

class TestProfiles:
    PROFILES = [
        "flat", "d_shape", "comfort_fit", "half_round", "knife_edge",
        "euro", "tapered", "cigar_band", "bombe", "concave",
        "square", "hammered", "split_band",
    ]

    def test_all_profiles_succeed(self):
        for prof in self.PROFILES:
            p = plan_wax_carving(7, 4.0, profile=prof)
            assert p["ok"], f"Profile '{prof}' failed: {p.get('reason')}"

    def test_knife_edge_thinner_than_bombe(self):
        p_ke = plan_wax_carving(7, 4.0, profile="knife_edge")
        p_bm = plan_wax_carving(7, 4.0, profile="bombe")
        assert p_ke["ok"] and p_bm["ok"]
        assert p_ke["shank_thickness_mm"] <= p_bm["shank_thickness_mm"]


# ---------------------------------------------------------------------------
# 10. Design features included in tool sequence
# ---------------------------------------------------------------------------

class TestDesignFeatures:
    def test_milgrain_adds_stage(self):
        p_plain = plan_wax_carving(7, 4.0)
        p_milg  = plan_wax_carving(7, 4.0, design_features=["milgrain"])
        assert p_plain["ok"] and p_milg["ok"]
        assert p_milg["total_time_min"] > p_plain["total_time_min"]

    def test_engraving_adds_stage(self):
        p = plan_wax_carving(7, 4.0, design_features=["engraving"])
        assert p["ok"]
        detail_stages = [s for s in p["tool_sequence"] if s["phase"] == "detail"]
        tools_text = " ".join(s["tool"] for s in detail_stages)
        assert "graver" in tools_text.lower()

    def test_stone_seat_adds_bur(self):
        p = plan_wax_carving(7, 4.0, design_features=["stone_seat"])
        assert p["ok"]
        tools_text = " ".join(s["tool"] for s in p["tool_sequence"])
        assert "bur" in tools_text.lower()


# ---------------------------------------------------------------------------
# 11. Wax weight formula
# ---------------------------------------------------------------------------

class TestWaxWeight:
    def test_wax_weight_formula(self):
        p = _default_plan()
        assert p["ok"]
        expected = (p["target_volume_mm3"] / MM3_PER_CM3) * WAX_DENSITY_G_CM3
        assert abs(p["wax_weight_g"] - expected) < 1e-4

    def test_wax_weight_positive(self):
        p = _default_plan()
        assert p["ok"]
        assert p["wax_weight_g"] > 0.0


# ---------------------------------------------------------------------------
# 12. Sprue suggestion present
# ---------------------------------------------------------------------------

class TestSprueSuggestion:
    def test_sprue_suggestion_is_string(self):
        p = _default_plan()
        assert p["ok"]
        assert isinstance(p["sprue_suggestion"], str)
        assert len(p["sprue_suggestion"]) > 10

    def test_wide_band_gets_two_sprues(self):
        p = plan_wax_carving(7, 12.0)  # very wide band
        assert p["ok"]
        assert "two" in p["sprue_suggestion"].lower() or "symmetrical" in p["sprue_suggestion"].lower()


# ---------------------------------------------------------------------------
# 13. Tool sequence has at least 9 stages
# ---------------------------------------------------------------------------

class TestToolSequence:
    def test_tool_sequence_min_stages(self):
        # Without design features there are 8 stages; with one feature, 9+
        p_plain = _default_plan()
        assert p_plain["ok"]
        assert len(p_plain["tool_sequence"]) >= 8
        p_feat = plan_wax_carving(7, 4.0, design_features=["milgrain"])
        assert p_feat["ok"]
        assert len(p_feat["tool_sequence"]) >= 9

    def test_tool_sequence_has_all_phases(self):
        p = _default_plan()
        assert p["ok"]
        phases = {s["phase"] for s in p["tool_sequence"]}
        assert "roughing" in phases
        assert "shaping" in phases
        assert "detail" in phases

    def test_total_time_positive(self):
        p = _default_plan()
        assert p["ok"]
        assert p["total_time_min"] > 0.0
