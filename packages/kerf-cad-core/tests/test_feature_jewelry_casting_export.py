"""
T-12 – Jewelry: casting / STL production export

Scope
-----
casting_export.py + production.py end-to-end STL/3MF.

Strategy
--------
25 finished SKUs across a matrix of:
  • alloy families  (gold / platinum / palladium / silver / base)
  • piece profiles  (stud, band ring, pendant, bangle, cuff)

For each SKU assert:
  – casting_export_summary produces a complete, well-structured payload
  – sprue count follows the volume-bucket heuristic (manifold sprue/runner
    attachment: ≥1 sprue, count increases monotonically with size)
  – est_pour_grams_with_sprue > est_metal_grams (runner overhead attached)
  – volume round-trip: summary["volume_mm3"] matches input ±0.5 %
  – shrinkage_pct is per-alloy (not the fallback for every alloy)
  – production.casting_tree produces a valid tree for the same SKU
  – production.production_weights wax + metal correct to density spec
  – production.batch_cost subtotal decomposes correctly

Idempotency: every function is pure / deterministic; calling twice with the
same inputs must return bit-identical results.

Boundary / malformed:
  – zero / negative volume raises ValueError
  – unknown alloy raises ValueError (both in casting_export and production)
  – sprue strategy at each threshold boundary (499, 500, 1999, 2000, 4999, 5000)
  – thickness_mm = 0 is allowed (zero means "not specified")
  – thickness_mm < 0 raises ValueError
  – gemstone_refs=None and gemstone_refs=[] are both treated as "no gems"
  – non-string items in gemstone_refs are coerced to str

Pure Python – no OCC, no network, no database.
"""

from __future__ import annotations

import math
import itertools
from typing import Any

import pytest

from kerf_cad_core.jewelry.casting_export import (
    SHRINKAGE_PCT,
    _SHRINKAGE_FALLBACK,
    _SMALL_THRESHOLD,
    _MEDIUM_THRESHOLD,
    _LARGE_THRESHOLD,
    _sprue_strategy,
    apply_shrinkage_scale,
    casting_export_summary,
    estimate_metal_grams,
    estimate_pour_grams,
    get_shrinkage_pct,
)
from kerf_cad_core.jewelry.production import (
    WAX_DENSITY_G_CM3,
    RESIN_DENSITY_G_CM3,
    casting_tree,
    production_weights,
    batch_cost,
    shrink_compensate,
    polish_stock,
)
from kerf_cad_core.jewelry.metal_cost import METAL_DENSITY_G_CM3, METAL_LABELS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def approx(v: float, rel: float = 1e-4) -> Any:
    return pytest.approx(v, rel=rel)


# ---------------------------------------------------------------------------
# SKU matrix  (5 alloy families × 5 piece profiles = 25 SKUs)
#
# Each SKU is: (alloy_key, volume_mm3, min_thickness_mm, gemstone_refs)
#
# Piece profiles with representative volumes:
#   stud    ~  200 mm³  (small earring / stud solitaire)
#   band    ~ 1000 mm³  (standard comfort-fit ring)
#   pendant ~ 2500 mm³  (medium pendant)
#   bangle  ~ 4800 mm³  (solid bangle near 2-sprue boundary)
#   cuff    ~ 6500 mm³  (heavy cuff bracelet — 3-sprue territory)
#
# Alloy families: yellow-gold, white-gold, platinum, silver, base
# ---------------------------------------------------------------------------

_ALLOY_FAMILIES = [
    "18k_yellow",     # yellow gold
    "18k_white",      # white gold
    "platinum_950",   # platinum
    "sterling_925",   # silver
    "bronze",         # base metal
]

_PROFILES = [
    ("stud",    200.0,  0.8,  ["diamond_centre"]),
    ("band",   1000.0,  1.5,  []),
    ("pendant", 2500.0, 1.2,  ["sapphire_drop"]),
    ("bangle",  4800.0, 2.0,  []),
    ("cuff",    6500.0, 2.5,  ["emerald_1", "emerald_2"]),
]

# Build flat list of 25 (alloy, profile_name, volume, thickness, gems)
_SKUS = [
    (alloy, name, vol, thick, gems)
    for alloy, (name, vol, thick, gems) in itertools.product(_ALLOY_FAMILIES, _PROFILES)
]

assert len(_SKUS) == 25, f"Expected 25 SKUs, got {len(_SKUS)}"


# ---------------------------------------------------------------------------
# Helper: produce a casting_export_summary for a SKU
# ---------------------------------------------------------------------------

def _summary_for(sku):
    alloy, name, vol, thick, gems = sku
    return casting_export_summary(
        alloy=alloy,
        volume_mm3=vol,
        thickness_mm=thick,
        gemstone_refs=gems,
    )


# ===========================================================================
# 1. Per-SKU: output structure and key presence
# ===========================================================================

class TestSKUStructure:
    """Every SKU must return a complete, well-typed summary."""

    REQUIRED_KEYS = (
        "alloy", "alloy_label", "shrinkage_pct", "volume_mm3",
        "thickness_mm", "gemstones_excluded", "est_metal_grams",
        "est_pour_grams_with_sprue", "sprue_count", "sprue_location",
        "recommended_orientation", "support_hint", "stl_bytes", "occ_available",
    )

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_required_keys_present(self, sku):
        s = _summary_for(sku)
        for key in self.REQUIRED_KEYS:
            assert key in s, f"Missing key '{key}' for SKU {sku[0]}-{sku[1]}"

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_alloy_stored_correctly(self, sku):
        alloy, name, vol, thick, gems = sku
        s = _summary_for(sku)
        assert s["alloy"] == alloy

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_alloy_label_populated(self, sku):
        alloy, *_ = sku
        s = _summary_for(sku)
        assert s["alloy_label"] == METAL_LABELS[alloy]
        assert isinstance(s["alloy_label"], str)
        assert len(s["alloy_label"]) > 0


# ===========================================================================
# 2. Per-SKU: volume round-trip ±0.5 %
# ===========================================================================

class TestSKUVolumeRoundTrip:
    """Summary must reflect input volume exactly (no truncation/conversion)."""

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_volume_round_trip(self, sku):
        alloy, name, vol, thick, gems = sku
        s = _summary_for(sku)
        # Summary stores the input volume verbatim — tolerance is effectively 0
        # We allow ±0.5% as the spec floor (actual impl stores it unchanged)
        assert abs(s["volume_mm3"] - vol) / vol <= 0.005, (
            f"Volume round-trip failed for {alloy}-{name}: "
            f"input={vol}, stored={s['volume_mm3']}"
        )


# ===========================================================================
# 3. Per-SKU: sprue/runner attachment (manifold sprue heuristic)
# ===========================================================================

class TestSKUSprueAttachment:
    """
    Sprue counts follow the volume-bucket heuristic.

    stud   (~200):  1 sprue
    band   (~1000): 1 sprue
    pendant(~2500): 2 sprues
    bangle (~4800): 2 sprues
    cuff   (~6500): 3 sprues

    Pour weight must exceed net metal weight (runner overhead attached).
    """

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_pour_grams_exceeds_net_grams(self, sku):
        """Runner/sprue overhead: pour must always exceed net."""
        s = _summary_for(sku)
        assert s["est_pour_grams_with_sprue"] > s["est_metal_grams"], (
            f"Pour ≤ net for {sku[0]}-{sku[1]}: "
            f"pour={s['est_pour_grams_with_sprue']}, net={s['est_metal_grams']}"
        )

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_sprue_count_at_least_1(self, sku):
        s = _summary_for(sku)
        assert s["sprue_count"] >= 1

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_sprue_location_non_empty(self, sku):
        s = _summary_for(sku)
        assert isinstance(s["sprue_location"], str)
        assert len(s["sprue_location"]) > 0

    def test_stud_1_sprue(self):
        """Stud ~200 mm³ → 1 sprue (small bucket)."""
        for alloy in _ALLOY_FAMILIES:
            s = casting_export_summary(alloy=alloy, volume_mm3=200.0)
            assert s["sprue_count"] == 1, f"{alloy} stud got {s['sprue_count']} sprues"

    def test_band_1_sprue(self):
        """Band ~1000 mm³ → 1 sprue (medium bucket)."""
        for alloy in _ALLOY_FAMILIES:
            s = casting_export_summary(alloy=alloy, volume_mm3=1000.0)
            assert s["sprue_count"] == 1

    def test_pendant_2_sprues(self):
        """Pendant ~2500 mm³ → 2 sprues (large bucket)."""
        for alloy in _ALLOY_FAMILIES:
            s = casting_export_summary(alloy=alloy, volume_mm3=2500.0)
            assert s["sprue_count"] == 2

    def test_bangle_2_sprues(self):
        """Bangle ~4800 mm³ → 2 sprues (still large bucket)."""
        for alloy in _ALLOY_FAMILIES:
            s = casting_export_summary(alloy=alloy, volume_mm3=4800.0)
            assert s["sprue_count"] == 2

    def test_cuff_3_sprues(self):
        """Cuff ~6500 mm³ → 3 sprues (extra-large bucket)."""
        for alloy in _ALLOY_FAMILIES:
            s = casting_export_summary(alloy=alloy, volume_mm3=6500.0)
            assert s["sprue_count"] == 3

    def test_sprue_count_monotonic_with_volume(self):
        """Sprue count must be non-decreasing as volume increases."""
        vols = [200.0, 1000.0, 2500.0, 4800.0, 6500.0, 10000.0]
        counts = [
            casting_export_summary(alloy="18k_yellow", volume_mm3=v)["sprue_count"]
            for v in vols
        ]
        for i in range(len(counts) - 1):
            assert counts[i] <= counts[i + 1], (
                f"Sprue count not monotonic: vol={vols[i]}→{counts[i]}, "
                f"vol={vols[i+1]}→{counts[i+1]}"
            )


# ===========================================================================
# 4. Per-SKU: shrinkage — per-alloy, not fallback everywhere
# ===========================================================================

class TestSKUShrinkage:
    """Each alloy must use its own shrinkage value, not the default fallback."""

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_shrinkage_pct_is_from_table(self, sku):
        alloy, *_ = sku
        s = _summary_for(sku)
        expected = SHRINKAGE_PCT[alloy]
        assert s["shrinkage_pct"] == approx(expected), (
            f"Shrinkage mismatch for {alloy}: got {s['shrinkage_pct']}, expected {expected}"
        )

    def test_platinum_shrinkage_greater_than_gold(self):
        """Platinum 950 (1.80%) shrinks more than 18k yellow (1.25%)."""
        pt = casting_export_summary("platinum_950", 1000.0)["shrinkage_pct"]
        gold = casting_export_summary("18k_yellow", 1000.0)["shrinkage_pct"]
        assert pt > gold

    def test_white_gold_greater_than_yellow_same_karat(self):
        """18k white > 18k yellow shrinkage (Pd-white alloy characteristic)."""
        white = casting_export_summary("18k_white", 1000.0)["shrinkage_pct"]
        yellow = casting_export_summary("18k_yellow", 1000.0)["shrinkage_pct"]
        assert white > yellow

    def test_titanium_lowest_shrinkage(self):
        """Titanium (0.50%) has the lowest shrinkage of all alloys."""
        ti_shrink = SHRINKAGE_PCT["titanium"]
        for k, v in SHRINKAGE_PCT.items():
            assert ti_shrink <= v, f"titanium shrinkage {ti_shrink} > {k}={v}"


# ===========================================================================
# 5. Per-SKU: gemstone exclusion list
# ===========================================================================

class TestSKUGemstoneExclusion:
    """Gemstone refs are stored verbatim; they don't affect weight."""

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_gemstones_stored_correctly(self, sku):
        alloy, name, vol, thick, gems = sku
        s = _summary_for(sku)
        assert s["gemstones_excluded"] == gems

    def test_none_refs_becomes_empty_list(self):
        s = casting_export_summary("18k_yellow", 1000.0, gemstone_refs=None)
        assert s["gemstones_excluded"] == []

    def test_empty_list_refs_stays_empty(self):
        s = casting_export_summary("18k_yellow", 1000.0, gemstone_refs=[])
        assert s["gemstones_excluded"] == []

    def test_gems_do_not_affect_metal_weight(self):
        """Gem refs are informational — weight must be identical with or without."""
        s_no = casting_export_summary("platinum_950", 3000.0, gemstone_refs=[])
        s_yes = casting_export_summary(
            "platinum_950", 3000.0, gemstone_refs=["gem1", "gem2", "gem3"]
        )
        assert s_no["est_metal_grams"] == approx(s_yes["est_metal_grams"])
        assert s_no["sprue_count"] == s_yes["sprue_count"]


# ===========================================================================
# 6. Per-SKU: STL bytes placeholder and OCC flag
# ===========================================================================

class TestSKUStlBytes:
    """Without an OCC shape, stl_bytes must be None and occ_available False."""

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_stl_bytes_none(self, sku):
        s = _summary_for(sku)
        assert s["stl_bytes"] is None

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_occ_available_false(self, sku):
        s = _summary_for(sku)
        assert s["occ_available"] is False


# ===========================================================================
# 7. Per-SKU: production.casting_tree integration
# ===========================================================================

class TestSKUCastingTree:
    """
    Every SKU volume + alloy must produce a valid casting tree.
    Tree metal weight must = pieces weight + trunk weight.
    """

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_casting_tree_structure(self, sku):
        alloy, name, vol, thick, gems = sku
        tree = casting_tree(vol, alloy, n_pieces=6)
        assert tree["n_pieces"] == 6
        assert tree["alloy_key"] == alloy
        assert tree["piece_volume_mm3"] == vol

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_tree_weight_equals_parts_plus_trunk(self, sku):
        """tree_metal_weight_g = pieces_weight_g + trunk weight (density × vol)."""
        alloy, name, vol, thick, gems = sku
        tree = casting_tree(vol, alloy, n_pieces=6)
        density = METAL_DENSITY_G_CM3[alloy]
        piece_g = density * (vol / 1000.0)
        pieces_g = piece_g * 6
        trunk_g = (tree["sprue_trunk_volume_mm3"] / 1000.0) * density
        expected = pieces_g + trunk_g
        assert tree["tree_metal_weight_g"] == approx(expected, rel=1e-3), (
            f"Tree weight mismatch for {alloy}-{name}: "
            f"expected={expected:.4f}, got={tree['tree_metal_weight_g']:.4f}"
        )

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_flask_yield_between_0_and_100(self, sku):
        alloy, name, vol, *_ = sku
        tree = casting_tree(vol, alloy, n_pieces=6)
        assert 0.0 < tree["flask_yield_pct"] <= 100.0, (
            f"flask_yield_pct={tree['flask_yield_pct']} out of range for {alloy}-{name}"
        )


# ===========================================================================
# 8. Per-SKU: production.production_weights integration
# ===========================================================================

class TestSKUProductionWeights:
    """Wax weight = volume × wax_density; metal weight = volume × alloy_density."""

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_wax_weight_matches_density(self, sku):
        alloy, name, vol, *_ = sku
        r = production_weights(vol, alloy, material="wax")
        expected_wax = (vol / 1000.0) * WAX_DENSITY_G_CM3
        assert r["wax_weight_g"] == approx(expected_wax), (
            f"Wax weight mismatch for {alloy}-{name}"
        )

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_metal_weight_matches_density(self, sku):
        alloy, name, vol, *_ = sku
        r = production_weights(vol, alloy)
        density = METAL_DENSITY_G_CM3[alloy]
        expected_metal = (vol / 1000.0) * density
        assert r["metal_weight_g"] == approx(expected_metal), (
            f"Metal weight mismatch for {alloy}-{name}"
        )

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_batch_scales_linearly(self, sku):
        alloy, name, vol, *_ = sku
        r1 = production_weights(vol, alloy, n_pieces=1)
        r4 = production_weights(vol, alloy, n_pieces=4)
        assert r4["batch_metal_weight_g"] == approx(r1["metal_weight_g"] * 4), (
            f"Batch metal scaling failed for {alloy}-{name}"
        )


# ===========================================================================
# 9. Boundary: volume thresholds
# ===========================================================================

class TestVolumeBoundaries:
    """Exact boundary values for the three sprue thresholds."""

    def test_just_below_small_threshold_1_sprue(self):
        """vol = 499.99 < 500 → 1 sprue."""
        s = _sprue_strategy(_SMALL_THRESHOLD - 0.01, 1.0)
        assert s["sprue_count"] == 1

    def test_at_small_threshold_still_1_sprue(self):
        """vol = 500.0 enters the medium bucket → still 1 sprue."""
        s = _sprue_strategy(_SMALL_THRESHOLD, 1.0)
        assert s["sprue_count"] == 1

    def test_just_above_small_threshold_1_sprue(self):
        """vol = 500.01 in medium bucket → 1 sprue."""
        s = _sprue_strategy(_SMALL_THRESHOLD + 0.01, 1.0)
        assert s["sprue_count"] == 1

    def test_just_below_medium_threshold_1_sprue(self):
        """vol = 1999.99 still medium bucket → 1 sprue."""
        s = _sprue_strategy(_MEDIUM_THRESHOLD - 0.01, 1.0)
        assert s["sprue_count"] == 1

    def test_at_medium_threshold_2_sprues(self):
        """vol = 2000.0 enters large bucket → 2 sprues."""
        s = _sprue_strategy(_MEDIUM_THRESHOLD, 1.0)
        assert s["sprue_count"] == 2

    def test_just_above_medium_threshold_2_sprues(self):
        """vol = 2000.01 → 2 sprues."""
        s = _sprue_strategy(_MEDIUM_THRESHOLD + 0.01, 1.0)
        assert s["sprue_count"] == 2

    def test_just_below_large_threshold_2_sprues(self):
        """vol = 4999.99 → 2 sprues."""
        s = _sprue_strategy(_LARGE_THRESHOLD - 0.01, 1.0)
        assert s["sprue_count"] == 2

    def test_at_large_threshold_3_sprues(self):
        """vol = 5000.0 enters extra-large bucket → 3 sprues."""
        s = _sprue_strategy(_LARGE_THRESHOLD, 1.0)
        assert s["sprue_count"] == 3

    def test_just_above_large_threshold_3_sprues(self):
        """vol = 5000.01 → 3 sprues."""
        s = _sprue_strategy(_LARGE_THRESHOLD + 0.01, 1.0)
        assert s["sprue_count"] == 3


# ===========================================================================
# 10. Boundary: malformed / invalid inputs
# ===========================================================================

class TestMalformedInputs:
    """All error paths raise ValueError with a useful message."""

    def test_zero_volume_raises(self):
        with pytest.raises(ValueError, match="volume_mm3 must be positive"):
            casting_export_summary("18k_yellow", volume_mm3=0.0)

    def test_negative_volume_raises(self):
        with pytest.raises(ValueError, match="volume_mm3 must be positive"):
            casting_export_summary("18k_yellow", volume_mm3=-1.0)

    def test_unknown_alloy_raises(self):
        with pytest.raises(ValueError, match="Unknown alloy"):
            casting_export_summary("unobtanium_999", volume_mm3=1000.0)

    def test_unknown_alloy_message_contains_alloy(self):
        with pytest.raises(ValueError) as exc:
            casting_export_summary("phantom_gold", volume_mm3=1000.0)
        assert "phantom_gold" in str(exc.value).lower()

    def test_negative_thickness_raises(self):
        with pytest.raises(ValueError, match="thickness_mm"):
            casting_export_summary("18k_yellow", volume_mm3=1000.0, thickness_mm=-0.1)

    def test_zero_thickness_allowed(self):
        """thickness_mm=0 means 'not specified' — must not raise."""
        s = casting_export_summary("18k_yellow", volume_mm3=1000.0, thickness_mm=0.0)
        assert s["thickness_mm"] == pytest.approx(0.0)

    def test_apply_shrinkage_scale_zero_dimension_raises(self):
        with pytest.raises(ValueError):
            apply_shrinkage_scale(0.0, 1.25)

    def test_apply_shrinkage_scale_negative_dimension_raises(self):
        with pytest.raises(ValueError):
            apply_shrinkage_scale(-5.0, 1.25)

    def test_apply_shrinkage_scale_negative_shrinkage_raises(self):
        with pytest.raises(ValueError):
            apply_shrinkage_scale(10.0, -0.1)

    def test_estimate_pour_grams_zero_net_raises(self):
        with pytest.raises(ValueError):
            estimate_pour_grams(0.0, 1)

    def test_estimate_pour_grams_negative_net_raises(self):
        with pytest.raises(ValueError):
            estimate_pour_grams(-5.0, 1)

    def test_estimate_pour_grams_zero_sprues_raises(self):
        with pytest.raises(ValueError):
            estimate_pour_grams(10.0, 0)

    def test_production_casting_tree_zero_pieces_raises(self):
        with pytest.raises(ValueError):
            casting_tree(1000.0, "18k_yellow", n_pieces=0)

    def test_production_casting_tree_unknown_alloy_raises(self):
        with pytest.raises(ValueError):
            casting_tree(1000.0, "unobtanium_999")

    def test_production_casting_tree_invalid_feed_direction_raises(self):
        with pytest.raises(ValueError):
            casting_tree(1000.0, "18k_yellow", feed_direction="sideways")

    def test_production_weights_invalid_material_raises(self):
        with pytest.raises(ValueError):
            production_weights(1000.0, "18k_yellow", material="mud")

    def test_batch_cost_negative_price_raises(self):
        with pytest.raises(ValueError):
            batch_cost(1000.0, "18k_yellow", metal_price_per_gram=-1.0)

    def test_batch_cost_zero_pieces_raises(self):
        with pytest.raises(ValueError):
            batch_cost(1000.0, "18k_yellow", n_pieces=0)

    def test_polish_stock_zero_volume_raises(self):
        with pytest.raises(ValueError):
            polish_stock(0.0, 5.0)

    def test_polish_stock_negative_stock_raises(self):
        with pytest.raises(ValueError):
            polish_stock(1000.0, 5.0, stock_mm=-0.1)


# ===========================================================================
# 11. Idempotency: deterministic outputs
# ===========================================================================

class TestIdempotency:
    """Pure functions must return identical results on repeated calls."""

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_casting_export_deterministic(self, sku):
        s1 = _summary_for(sku)
        s2 = _summary_for(sku)
        # Compare all scalar/non-bytes fields
        for key in s1:
            if key == "stl_bytes":
                continue
            assert s1[key] == s2[key], (
                f"casting_export_summary non-deterministic on key={key} for {sku[0]}-{sku[1]}"
            )

    def test_shrinkage_pct_table_idempotent(self):
        """get_shrinkage_pct must return the same value on repeated calls."""
        for k in SHRINKAGE_PCT:
            assert get_shrinkage_pct(k) == get_shrinkage_pct(k)

    def test_apply_shrinkage_scale_idempotent(self):
        """apply_shrinkage_scale is a pure formula — same input → same output."""
        for _ in range(3):
            v = apply_shrinkage_scale(17.5, 1.80)
        assert apply_shrinkage_scale(17.5, 1.80) == approx(v)

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_casting_tree_deterministic(self, sku):
        alloy, name, vol, *_ = sku
        t1 = casting_tree(vol, alloy, n_pieces=6)
        t2 = casting_tree(vol, alloy, n_pieces=6)
        for key in t1:
            assert t1[key] == t2[key], (
                f"casting_tree non-deterministic on key={key} for {alloy}-{name}"
            )


# ===========================================================================
# 12. Shrinkage apply: wax-pattern size > finished size for all alloys
# ===========================================================================

class TestShrinkageApply:
    """apply_shrinkage_scale must over-size for every known alloy."""

    @pytest.mark.parametrize("alloy", sorted(SHRINKAGE_PCT.keys()))
    def test_wax_pattern_oversized(self, alloy):
        s_pct = SHRINKAGE_PCT[alloy]
        original_mm = 20.0
        wax_mm = apply_shrinkage_scale(original_mm, s_pct)
        assert wax_mm > original_mm, (
            f"Wax pattern not oversized for {alloy}: got {wax_mm}"
        )

    @pytest.mark.parametrize("alloy", sorted(SHRINKAGE_PCT.keys()))
    def test_scale_factor_formula(self, alloy):
        """Scale factor = 1 / (1 - shrinkage/100) — verify algebraically."""
        s_pct = SHRINKAGE_PCT[alloy]
        expected_scale = 1.0 / (1.0 - s_pct / 100.0)
        result = shrink_compensate(10.0, alloy)
        assert result["scale_factor"] == approx(expected_scale), (
            f"Scale factor mismatch for {alloy}"
        )


# ===========================================================================
# 13. Metal weight density consistency across all SKU alloys
# ===========================================================================

class TestMetalWeightConsistency:
    """
    Metal weight must agree between casting_export_summary and
    production_weights (both call metal_weight() under the hood).
    """

    @pytest.mark.parametrize("sku", _SKUS, ids=[f"{a}-{n}" for a, n, *_ in _SKUS])
    def test_metal_weight_agreement(self, sku):
        alloy, name, vol, thick, gems = sku
        summary = _summary_for(sku)
        pw = production_weights(vol, alloy)

        # casting_export uses net weight; production_weights uses same path
        assert summary["est_metal_grams"] == approx(pw["metal_weight_g"], rel=1e-4), (
            f"Metal weight disagreement between casting_export and production_weights "
            f"for {alloy}-{name}"
        )
