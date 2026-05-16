"""
Tests for kerf_cad_core.jewelry.family_ring

All tests are pure-Python (no OCCT, no network).
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.jewelry.family_ring import (
    VALID_ARRANGEMENTS,
    VALID_SETTINGS,
    _MONTH_TO_GEM,
    _MAX_STONES,
    _MIN_METAL_GAP_MM,
    _compute_spacing,
    _layout_linear,
    _layout_cluster,
    _layout_wave,
    _layout_split_shank,
    _shank_top_arc_mm_ex,
    _shank_volume_mm3,
    _head_volume_mm3,
    build_family_ring,
    resolve_stone,
)
from kerf_cad_core.jewelry.gemstones import GEM_CATALOG, carat_from_mm
from kerf_cad_core.jewelry.ring import ring_size_to_diameter
from kerf_cad_core.jewelry.metal_cost import METAL_DENSITY_G_CM3, metal_weight

_PI = math.pi


# ---------------------------------------------------------------------------
# 1. Month → birthstone mapping
# ---------------------------------------------------------------------------

class TestMonthBirthstone:
    def test_april_is_diamond(self):
        assert _MONTH_TO_GEM[4] == "diamond"

    def test_july_is_ruby(self):
        assert _MONTH_TO_GEM[7] == "ruby"

    def test_september_is_sapphire(self):
        assert _MONTH_TO_GEM[9] == "sapphire"

    def test_may_is_emerald(self):
        assert _MONTH_TO_GEM[5] == "emerald"

    def test_january_is_garnet(self):
        assert _MONTH_TO_GEM[1] == "garnet"

    def test_all_months_covered(self):
        for m in range(1, 13):
            assert m in _MONTH_TO_GEM, f"Month {m} has no birthstone"

    def test_birthstone_in_catalog(self):
        for m, gem in _MONTH_TO_GEM.items():
            assert gem in GEM_CATALOG, f"Month {m} gem {gem!r} not in GEM_CATALOG"

    def test_month_in_catalog_entry(self):
        for m, gem in _MONTH_TO_GEM.items():
            assert m in GEM_CATALOG[gem]["months"], (
                f"Month {m} not listed in GEM_CATALOG[{gem!r}]['months']"
            )


# ---------------------------------------------------------------------------
# 2. resolve_stone
# ---------------------------------------------------------------------------

class TestResolveStone:
    def test_resolve_by_month(self):
        r = resolve_stone(month=4)
        assert r["ok"]
        assert r["gem"] == "diamond"

    def test_resolve_by_gem_name(self):
        r = resolve_stone(gem_name="ruby")
        assert r["ok"]
        assert r["gem"] == "ruby"

    def test_gem_name_overrides_month(self):
        r = resolve_stone(month=4, gem_name="sapphire")
        assert r["ok"]
        assert r["gem"] == "sapphire"

    def test_unknown_gem_returns_error(self):
        r = resolve_stone(gem_name="unobtanium")
        assert not r["ok"]

    def test_invalid_month_returns_error(self):
        r = resolve_stone(month=13)
        assert not r["ok"]

    def test_carat_from_diameter(self):
        r = resolve_stone(month=4, diameter_mm=6.5)
        assert r["ok"]
        assert r["diameter_mm"] == pytest.approx(6.5, abs=1e-3)
        # 6.5 mm diamond ≈ 1.0 ct
        assert r["carat_weight"] == pytest.approx(1.0, abs=0.05)

    def test_diameter_from_carat(self):
        r = resolve_stone(month=4, carat=1.0)
        assert r["ok"]
        assert r["diameter_mm"] == pytest.approx(6.5, abs=0.1)

    def test_default_diameter_used_when_neither(self):
        r = resolve_stone(month=7)
        assert r["ok"]
        # default is 3.0 mm
        assert r["diameter_mm"] == pytest.approx(3.0, abs=0.01)


# ---------------------------------------------------------------------------
# 3. _compute_spacing — no-overlap / auto-shrink
# ---------------------------------------------------------------------------

class TestComputeSpacing:
    def test_three_stones_fit(self):
        # 3 × 3 mm stones, 0.3 mm gap → total = 3×3 + 2×0.3 = 9.6 mm
        # arc for US-7 (id=17.32 mm, thickness=1.5): r=8.66+1.5=10.16; arc=10.16×π/2≈15.96
        id_mm = ring_size_to_diameter("us", 7)
        arc   = _shank_top_arc_mm_ex(id_mm, 1.5)
        fit   = _compute_spacing(3, 3.0, arc, 0.3)
        assert fit["fits"]
        assert not fit["auto_shrunk"]
        assert fit["spacing_mm"] == pytest.approx(3.3, abs=1e-3)
        assert fit["total_span_mm"] == pytest.approx(9.6, abs=1e-3)

    def test_spacing_equals_girdle_plus_gap(self):
        id_mm = ring_size_to_diameter("us", 7)
        arc   = _shank_top_arc_mm_ex(id_mm, 1.5)
        fit   = _compute_spacing(3, 3.0, arc, _MIN_METAL_GAP_MM)
        assert fit["spacing_mm"] == pytest.approx(
            fit["final_girdle_mm"] + _MIN_METAL_GAP_MM, abs=1e-3
        )

    def test_auto_shrink_fires_when_too_many_large_stones(self):
        # 10 × 5 mm stones clearly overflow a US-7 arc (~16 mm)
        id_mm = ring_size_to_diameter("us", 7)
        arc   = _shank_top_arc_mm_ex(id_mm, 1.5)
        fit   = _compute_spacing(10, 5.0, arc, 0.3)
        assert fit["fits"]
        assert fit["auto_shrunk"]
        assert fit["final_girdle_mm"] < 5.0

    def test_total_span_le_available_after_shrink(self):
        id_mm = ring_size_to_diameter("us", 7)
        arc   = _shank_top_arc_mm_ex(id_mm, 1.5)
        fit   = _compute_spacing(10, 5.0, arc, 0.3)
        # Allow 1e-3 mm tolerance for floating-point rounding in 4-dp rounded output
        assert fit["total_span_mm"] <= arc + 1e-3

    def test_zero_stones(self):
        fit = _compute_spacing(0, 3.0, 20.0, 0.3)
        assert fit["fits"]
        assert fit["spacing_mm"] == 0.0

    def test_single_stone_always_fits_reasonable_arc(self):
        fit = _compute_spacing(1, 3.0, 10.0, 0.3)
        assert fit["fits"]


# ---------------------------------------------------------------------------
# 4. build_family_ring — 3 stones, linear
# ---------------------------------------------------------------------------

class TestLinearThreeStones:
    def setup_method(self):
        stones = [
            {"month": 4},   # diamond
            {"month": 7},   # ruby
            {"month": 9},   # sapphire
        ]
        self.r = build_family_ring(7, stones, arrangement="linear_across_top")

    def test_ok(self):
        assert self.r["ok"]

    def test_three_seats(self):
        assert len(self.r["layout"]) == 3

    def test_stone_count_matches(self):
        assert len(self.r["stones"]) == 3

    def test_correct_gems(self):
        gems = [s["gem"] for s in self.r["stones"]]
        assert gems == ["diamond", "ruby", "sapphire"]

    def test_non_overlapping_x_coords(self):
        xs = [c["x_mm"] for c in self.r["layout"]]
        xs.sort()
        girdle = self.r["final_girdle_mm"]
        gap    = self.r["stones"][0]["diameter_mm"] * 0 + _MIN_METAL_GAP_MM
        for i in range(len(xs) - 1):
            dist = xs[i + 1] - xs[i]
            assert dist >= girdle + gap - 1e-6, (
                f"Adjacent stones overlap: gap={dist:.4f} < girdle+min_gap={girdle + gap:.4f}"
            )

    def test_spacing_ge_girdle_plus_gap(self):
        sp  = self.r["spacing_mm"]
        gd  = self.r["final_girdle_mm"]
        assert sp >= gd + _MIN_METAL_GAP_MM - 1e-6

    def test_total_span_le_available_arc(self):
        assert self.r["total_span_mm"] <= self.r["available_arc_mm"] + 1e-6

    def test_total_carat_equals_sum_of_per_stone(self):
        expected = sum(s["carat_weight"] for s in self.r["stones"])
        assert self.r["total_carat"] == pytest.approx(expected, abs=1e-5)

    def test_ring_id_matches_size_table(self):
        expected_id = ring_size_to_diameter("us", 7)
        assert self.r["inner_diameter_mm"] == pytest.approx(expected_id, abs=1e-4)


# ---------------------------------------------------------------------------
# 5. Metal weight = shank + Σ heads
# ---------------------------------------------------------------------------

class TestMetalWeight:
    def test_metal_weight_is_shank_plus_heads(self):
        stones = [{"month": 4}, {"month": 7}]
        r = build_family_ring(7, stones, metal="14k_yellow",
                              band_width=4.0, thickness=1.5)
        assert r["ok"]

        id_mm = ring_size_to_diameter("us", 7)
        sv = _shank_volume_mm3(id_mm, 1.5, 4.0)
        hv = sum(_head_volume_mm3(s["diameter_mm"]) for s in r["stones"])
        total_vol = sv + hv

        wt = metal_weight(total_vol, metal="14k_yellow")
        assert r["metal_weight_g"] == pytest.approx(wt["grams"], abs=1e-3)
        assert r["shank_volume_mm3"] == pytest.approx(sv, abs=1e-3)
        assert r["heads_volume_mm3"] == pytest.approx(hv, abs=1e-3)

    def test_heavier_metal_increases_weight(self):
        stones = [{"month": 4}]
        r_gold  = build_family_ring(7, stones, metal="18k_yellow")
        r_silv  = build_family_ring(7, stones, metal="sterling_925")
        assert r_gold["ok"] and r_silv["ok"]
        assert r_gold["metal_weight_g"] > r_silv["metal_weight_g"]


# ---------------------------------------------------------------------------
# 6. Auto-shrink flag fires when stones are too large
# ---------------------------------------------------------------------------

class TestAutoShrink:
    def test_auto_shrink_flag(self):
        # 12 large stones on a US-7 ring should trigger auto-shrink
        stones = [{"month": i + 1, "diameter_mm": 5.0} for i in range(12)]
        r = build_family_ring(7, stones, arrangement="channel")
        assert r["ok"]
        assert r["auto_shrunk"]
        assert r["final_girdle_mm"] < 5.0

    def test_no_shrink_when_stones_fit_naturally(self):
        stones = [{"month": i + 1, "diameter_mm": 2.0} for i in range(3)]
        r = build_family_ring(7, stones, arrangement="linear_across_top")
        assert r["ok"]
        assert not r["auto_shrunk"]


# ---------------------------------------------------------------------------
# 7. Cluster vs linear give different coordinates
# ---------------------------------------------------------------------------

class TestArrangementCoordsDiffer:
    def test_cluster_vs_linear_differ(self):
        stones = [{"month": i + 1} for i in range(4)]
        r_lin = build_family_ring(7, stones, arrangement="linear_across_top")
        r_clu = build_family_ring(7, stones, arrangement="cluster")
        assert r_lin["ok"] and r_clu["ok"]

        lin_ys = {c["y_mm"] for c in r_lin["layout"]}
        clu_ys = {c["y_mm"] for c in r_clu["layout"]}
        # Linear is always y=0; cluster has at least one nonzero y (ring of 3)
        assert lin_ys == {0.0}
        assert clu_ys != {0.0}, "Cluster should have nonzero y coords"

    def test_wave_alternates_y(self):
        stones = [{"month": i + 1} for i in range(4)]
        r = build_family_ring(7, stones, arrangement="wave")
        assert r["ok"]
        ys = [c["y_mm"] for c in r["layout"]]
        # Not all zero
        assert any(abs(y) > 1e-6 for y in ys)

    def test_split_shank_has_two_arms(self):
        stones = [{"month": i + 1} for i in range(4)]
        r = build_family_ring(7, stones, arrangement="split_shank")
        assert r["ok"]
        arms = {c.get("arm") for c in r["layout"]}
        assert "A" in arms and "B" in arms


# ---------------------------------------------------------------------------
# 8. Too many stones → graceful reason
# ---------------------------------------------------------------------------

class TestMaxStones:
    def test_too_many_linear(self):
        n = _MAX_STONES["linear_across_top"] + 1
        stones = [{"month": (i % 12) + 1} for i in range(n)]
        r = build_family_ring(7, stones, arrangement="linear_across_top")
        assert not r["ok"]
        assert "Too many stones" in r["reason"]

    def test_too_many_cluster(self):
        n = _MAX_STONES["cluster"] + 1
        stones = [{"month": (i % 12) + 1} for i in range(n)]
        r = build_family_ring(7, stones, arrangement="cluster")
        assert not r["ok"]
        assert "Too many stones" in r["reason"]

    def test_at_max_count_ok(self):
        n = _MAX_STONES["channel"]
        stones = [{"month": (i % 12) + 1} for i in range(n)]
        r = build_family_ring(7, stones, arrangement="channel")
        assert r["ok"]

    def test_too_many_wave(self):
        n = _MAX_STONES["wave"] + 1
        stones = [{"month": (i % 12) + 1} for i in range(n)]
        r = build_family_ring(7, stones, arrangement="wave")
        assert not r["ok"]


# ---------------------------------------------------------------------------
# 9. Duplicate months allowed
# ---------------------------------------------------------------------------

class TestDuplicateMonths:
    def test_duplicate_months_allowed(self):
        stones = [{"month": 7}, {"month": 7}, {"month": 7}]
        r = build_family_ring(7, stones, arrangement="linear_across_top")
        assert r["ok"]
        gems = [s["gem"] for s in r["stones"]]
        assert all(g == "ruby" for g in gems)
        assert len(r["layout"]) == 3


# ---------------------------------------------------------------------------
# 10. Invalid inputs return ok=False
# ---------------------------------------------------------------------------

class TestInvalidInputs:
    def test_unknown_arrangement(self):
        r = build_family_ring(7, [{"month": 4}], arrangement="spiral")
        assert not r["ok"]
        assert "Unknown arrangement" in r["reason"]

    def test_unknown_metal(self):
        r = build_family_ring(7, [{"month": 4}], metal="unobtanium_gold")
        assert not r["ok"]
        assert "Unknown metal" in r["reason"]

    def test_empty_stones(self):
        r = build_family_ring(7, [])
        assert not r["ok"]

    def test_invalid_ring_size(self):
        r = build_family_ring(99, [{"month": 4}])  # US 99 is out of range
        assert not r["ok"]


# ---------------------------------------------------------------------------
# 11. Per-stone seat geometry (seats are non-overlapping)
# ---------------------------------------------------------------------------

class TestSeatGeometry:
    def test_seats_non_overlapping_linear(self):
        stones = [{"month": i + 1, "diameter_mm": 3.0} for i in range(5)]
        r = build_family_ring(7, stones, arrangement="linear_across_top")
        assert r["ok"]
        xs = sorted(c["x_mm"] for c in r["layout"])
        gd = r["final_girdle_mm"]
        for i in range(len(xs) - 1):
            assert xs[i + 1] - xs[i] >= gd + _MIN_METAL_GAP_MM - 1e-6

    def test_channel_seats_non_overlapping(self):
        stones = [{"month": (i % 12) + 1, "diameter_mm": 3.0} for i in range(6)]
        r = build_family_ring(7, stones, arrangement="channel")
        assert r["ok"]
        xs = sorted(c["x_mm"] for c in r["layout"])
        gd = r["final_girdle_mm"]
        for i in range(len(xs) - 1):
            assert xs[i + 1] - xs[i] >= gd + _MIN_METAL_GAP_MM - 1e-6


# ---------------------------------------------------------------------------
# 12. Layout metadata attached correctly
# ---------------------------------------------------------------------------

class TestLayoutMetadata:
    def test_layout_has_gem_info(self):
        stones = [{"month": 4}, {"month": 7}]
        r = build_family_ring(7, stones)
        assert r["ok"]
        for entry in r["layout"]:
            assert "gem" in entry
            assert "cut" in entry
            assert "diameter_mm" in entry
            assert "carat_weight" in entry
            assert "setting" in entry


# ---------------------------------------------------------------------------
# 13. Shank arc grows with ring size
# ---------------------------------------------------------------------------

class TestShankArcBySize:
    def test_larger_ring_has_more_arc(self):
        arc_5  = _shank_top_arc_mm_ex(ring_size_to_diameter("us", 5), 1.5)
        arc_10 = _shank_top_arc_mm_ex(ring_size_to_diameter("us", 10), 1.5)
        assert arc_10 > arc_5

    def test_more_stones_fit_on_larger_ring(self):
        stones_small = [{"month": (i % 12) + 1} for i in range(8)]
        stones_large = [{"month": (i % 12) + 1} for i in range(8)]
        r5  = build_family_ring(5,  stones_small, arrangement="linear_across_top")
        r12 = build_family_ring(12, stones_large, arrangement="linear_across_top")
        # US-12 ring has more arc; auto_shrunk should be less or final_girdle >=
        assert r12["ok"] and r5["ok"]
        assert r12["final_girdle_mm"] >= r5["final_girdle_mm"] - 1e-9


# ---------------------------------------------------------------------------
# 14. Explicit stone spec overrides default
# ---------------------------------------------------------------------------

class TestExplicitStoneSpec:
    def test_explicit_diameter_respected(self):
        r = build_family_ring(7, [{"month": 4, "diameter_mm": 5.0}])
        assert r["ok"]
        # if fits, diameter preserved; if not, shrunk
        assert r["stones"][0]["diameter_mm"] <= 5.0 + 1e-6

    def test_explicit_gem_name(self):
        r = build_family_ring(7, [{"gem": "amethyst"}])
        assert r["ok"]
        assert r["stones"][0]["gem"] == "amethyst"

    def test_default_cut_round_brilliant(self):
        r = build_family_ring(7, [{"month": 4}])
        assert r["ok"]
        assert r["stones"][0]["cut"] == "round_brilliant"
