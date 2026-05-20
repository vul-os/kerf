"""
test_feature_jewelry_cost_quote.py — T-13 hermetic pytest suite
===============================================================

Scope: kerf_cad_core.jewelry.metal_cost + tool_metal_cost (pure-Python path)
       quoting against piece volumes representative of pieces.py BOM.

Success criteria (from testing-breakdown.md T-13):
  - 25 SKUs × metal × spot prices
  - total = metal + casting + setting + finishing ±0.01
  - FX handling correct (multi-currency scale factor)
  - Boundary / malformed / idempotency cases covered

All tests are pure-Python — no OCC, no DB, no network.
"""

from __future__ import annotations

import math
import pytest

from kerf_cad_core.jewelry.metal_cost import (
    METAL_DENSITY_G_CM3,
    METAL_HALLMARK,
    METAL_LABELS,
    METAL_PRICE_PRESETS,
    GRAMS_PER_OZT,
    GRAMS_PER_DWT,
    MM3_PER_CM3,
    casting_cost,
    casting_weight,
    grams_to_dwt,
    grams_to_ozt,
    dwt_to_grams,
    ozt_to_grams,
    jewelry_quote,
    labour_cost,
    metal_weight,
    mm_to_carat,
    multi_metal_compare,
    resolve_density,
    stone_cost_line_items,
    DEFAULT_SETTING_FEE_PER_STONE,
    DEFAULT_FINISHING_COST,
)


# ---------------------------------------------------------------------------
# 25-SKU test matrix
# ---------------------------------------------------------------------------
# 5 piece types × 5 metals = 25 SKUs.
# Volumes are representative mm³ for real jewelry pieces:
#   ring shank ~700 mm³, pendant plate ~300 mm³, stud face ~80 mm³,
#   bangle ~3000 mm³, brooch plate ~500 mm³.

_PIECE_VOLUMES_MM3 = {
    "ring":    700.0,
    "pendant": 300.0,
    "stud":     80.0,
    "bangle": 3000.0,
    "brooch":  500.0,
}

_METALS_5 = [
    "18k_yellow",
    "14k_white",
    "sterling_925",
    "platinum_950",
    "titanium",
]

_SPOT_PRICES_USD_PER_G = {
    "18k_yellow":   48.0,
    "14k_white":    38.0,
    "sterling_925":  0.80,
    "platinum_950": 32.0,
    "titanium":      0.05,
}

# Build full 25-row matrix: (piece, metal, volume_mm3, price_per_g)
_SKU_MATRIX = [
    (piece, metal, vol, _SPOT_PRICES_USD_PER_G[metal])
    for piece, vol in _PIECE_VOLUMES_MM3.items()
    for metal in _METALS_5
]

assert len(_SKU_MATRIX) == 25, f"Expected 25 SKUs, got {len(_SKU_MATRIX)}"


# ---------------------------------------------------------------------------
# 25 SKUs — full casting_cost consistency
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("piece,metal,volume_mm3,price", _SKU_MATRIX)
def test_casting_cost_total_consistent(piece, metal, volume_mm3, price):
    """total_cost == metal_cost + labor + finishing within float epsilon."""
    labor = 45.0
    finishing = 35.0
    result = casting_cost(
        volume_mm3=volume_mm3,
        metal=metal,
        metal_price_per_gram=price,
        labor=labor,
        finishing=finishing,
    )
    expected_total = result["metal_cost"] + result["labor"] + result["finishing"]
    assert abs(result["total_cost"] - expected_total) < 1e-9, (
        f"{piece}/{metal}: total_cost mismatch: "
        f"{result['total_cost']} != {expected_total}"
    )


@pytest.mark.parametrize("piece,metal,volume_mm3,price", _SKU_MATRIX)
def test_gross_grams_gte_net_grams(piece, metal, volume_mm3, price):
    """gross_grams (with sprue allowance) must be >= net_grams."""
    result = casting_cost(volume_mm3=volume_mm3, metal=metal, metal_price_per_gram=price)
    assert result["gross_grams"] >= result["net_grams"], (
        f"{piece}/{metal}: gross_grams < net_grams"
    )


@pytest.mark.parametrize("piece,metal,volume_mm3,price", _SKU_MATRIX)
def test_metal_cost_equals_gross_times_price(piece, metal, volume_mm3, price):
    """metal_cost == gross_grams × metal_price_per_gram ±0.01."""
    result = casting_cost(volume_mm3=volume_mm3, metal=metal, metal_price_per_gram=price)
    expected = result["gross_grams"] * price
    assert abs(result["metal_cost"] - expected) < 0.01, (
        f"{piece}/{metal}: metal_cost {result['metal_cost']:.4f} != "
        f"gross_grams({result['gross_grams']:.4f}) × price({price}) = {expected:.4f}"
    )


@pytest.mark.parametrize("piece,metal,volume_mm3,price", _SKU_MATRIX)
def test_net_grams_matches_density_volume(piece, metal, volume_mm3, price):
    """net_grams == density × volume_cm3 ±0.0001."""
    density = METAL_DENSITY_G_CM3[metal]
    volume_cm3 = volume_mm3 / MM3_PER_CM3
    expected_grams = density * volume_cm3
    result = casting_cost(volume_mm3=volume_mm3, metal=metal, metal_price_per_gram=price)
    assert abs(result["net_grams"] - expected_grams) < 1e-4, (
        f"{piece}/{metal}: net_grams {result['net_grams']:.6f} != "
        f"density×vol {expected_grams:.6f}"
    )


# ---------------------------------------------------------------------------
# 25 SKUs — full jewelry_quote consistency (metal + stones + labour)
# ---------------------------------------------------------------------------

# Stone specs used for the full quote tests (1 round brilliant + 2 pave)
_STONES_SPEC = [
    {"cut": "round_brilliant", "carat": 0.50, "price_per_carat": 800.0, "count": 1, "note": "VS1 G"},
    {"cut": "pave",           "carat": 0.03, "price_per_carat": 200.0, "count": 8, "note": "side pave"},
]
_EXPECTED_STONE_COST = 0.50 * 800.0 + 0.03 * 200.0 * 8  # 400 + 48 = 448.0


@pytest.mark.parametrize("piece,metal,volume_mm3,price", _SKU_MATRIX)
def test_full_quote_total_equals_subtotal_plus_markup(piece, metal, volume_mm3, price):
    """total == subtotal + markup_amount ±0.01 (spec: ±0.01)."""
    markup_pct = 20.0
    q = jewelry_quote(
        volume_mm3=volume_mm3,
        metal=metal,
        metal_price_per_gram=price,
        stones=_STONES_SPEC,
        bench_hours=2.0,
        hourly_rate=60.0,
        setting_type="prong",
        finishing_type="rhodium",
        markup_pct=markup_pct,
    )
    expected_total = round(q["subtotal"] + q["markup_amount"], 4)
    assert abs(q["total"] - expected_total) < 0.01, (
        f"{piece}/{metal}: total {q['total']} != subtotal({q['subtotal']}) + "
        f"markup({q['markup_amount']}) = {expected_total}"
    )


@pytest.mark.parametrize("piece,metal,volume_mm3,price", _SKU_MATRIX)
def test_full_quote_subtotal_decomposition(piece, metal, volume_mm3, price):
    """subtotal == metal_cost + stone_cost + labour_total ±0.01."""
    q = jewelry_quote(
        volume_mm3=volume_mm3,
        metal=metal,
        metal_price_per_gram=price,
        stones=_STONES_SPEC,
        bench_hours=1.5,
        hourly_rate=75.0,
        setting_type="bezel",
        finishing_type="polish",
        markup_pct=0.0,
    )
    expected = round(q["metal_cost"] + q["stone_cost"] + q["labour_total"], 4)
    assert abs(q["subtotal"] - expected) < 0.01, (
        f"{piece}/{metal}: subtotal {q['subtotal']} != "
        f"metal({q['metal_cost']}) + stone({q['stone_cost']}) + "
        f"labour({q['labour_total']}) = {expected}"
    )


@pytest.mark.parametrize("piece,metal,volume_mm3,price", _SKU_MATRIX)
def test_full_quote_stone_cost_correct(piece, metal, volume_mm3, price):
    """stone_cost matches manually computed sum ±0.01."""
    q = jewelry_quote(
        volume_mm3=volume_mm3,
        metal=metal,
        metal_price_per_gram=price,
        stones=_STONES_SPEC,
    )
    assert abs(q["stone_cost"] - _EXPECTED_STONE_COST) < 0.01, (
        f"{piece}/{metal}: stone_cost {q['stone_cost']} != {_EXPECTED_STONE_COST}"
    )


# ---------------------------------------------------------------------------
# FX handling — currency scale factor
# ---------------------------------------------------------------------------
# "FX handling correct" from the spec means the module is currency-agnostic:
# scaling all monetary inputs by a constant FX factor must scale all monetary
# outputs by the same factor (linearity). No live rates are used.

_FX_FACTOR = 18.5  # e.g. approximate USD→ZAR

@pytest.mark.parametrize("piece,metal,volume_mm3,price", _SKU_MATRIX)
def test_fx_linearity_metal_cost(piece, metal, volume_mm3, price):
    """Scaling metal price by FX factor scales metal_cost by the same factor ±0.01."""
    base = casting_cost(volume_mm3=volume_mm3, metal=metal, metal_price_per_gram=price)
    scaled = casting_cost(
        volume_mm3=volume_mm3,
        metal=metal,
        metal_price_per_gram=price * _FX_FACTOR,
    )
    ratio = scaled["metal_cost"] / base["metal_cost"] if base["metal_cost"] > 0 else 1.0
    assert abs(ratio - _FX_FACTOR) < 0.01, (
        f"{piece}/{metal}: FX scale ratio {ratio:.4f} != {_FX_FACTOR}"
    )


@pytest.mark.parametrize("piece,metal,volume_mm3,price", _SKU_MATRIX)
def test_fx_linearity_full_quote(piece, metal, volume_mm3, price):
    """Full quote sub-components scale linearly with all monetary inputs ×FX_FACTOR.

    The module is currency-agnostic: no built-in conversion rates are applied,
    so scaling every monetary input by a constant factor must scale every
    monetary output by the same factor.

    Setting fees use DEFAULT_SETTING_FEE_PER_STONE which is denominated in USD.
    To test pure FX linearity we pass an explicit setting_fee_per_stone that
    is also scaled, so all monetary inputs are consistently in the same currency.
    """
    bench_hours = 2.0
    hourly_rate = 55.0
    stone_ppc = 600.0
    setting_fee_base = 12.0   # explicit, USD-equivalent; will be scaled
    finishing_val = 30.0
    stones_base = [{"cut": "round_brilliant", "carat": 0.3, "price_per_carat": stone_ppc, "count": 1}]

    q_base = jewelry_quote(
        volume_mm3=volume_mm3,
        metal=metal,
        metal_price_per_gram=price,
        stones=stones_base,
        bench_hours=bench_hours,
        hourly_rate=hourly_rate,
        setting_fee_per_stone=setting_fee_base,
        finishing_cost=finishing_val,
        markup_pct=0.0,
    )
    q_scaled = jewelry_quote(
        volume_mm3=volume_mm3,
        metal=metal,
        metal_price_per_gram=price * _FX_FACTOR,
        stones=[{"cut": "round_brilliant", "carat": 0.3,
                 "price_per_carat": stone_ppc * _FX_FACTOR, "count": 1}],
        bench_hours=bench_hours,
        hourly_rate=hourly_rate * _FX_FACTOR,
        setting_fee_per_stone=setting_fee_base * _FX_FACTOR,
        finishing_cost=finishing_val * _FX_FACTOR,
        markup_pct=0.0,
    )
    # Verify each monetary sub-component scales by FX_FACTOR (within float epsilon)
    for field in ("metal_cost", "stone_cost", "labour_total"):
        base_val = q_base[field]
        scaled_val = q_scaled[field]
        expected = base_val * _FX_FACTOR
        assert abs(scaled_val - expected) < 1e-6, (
            f"{piece}/{metal}: {field} FX scaling error: "
            f"scaled={scaled_val:.6f} expected={expected:.6f}"
        )


# ---------------------------------------------------------------------------
# Price preset path
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metal", _METALS_5)
def test_price_preset_usd_2024(metal):
    """price_preset='usd_2024_approx' fills metal_price_per_gram from the table."""
    volume = 500.0
    preset_price = METAL_PRICE_PRESETS["usd_2024_approx"][metal]
    q = jewelry_quote(
        volume_mm3=volume,
        metal=metal,
        price_preset="usd_2024_approx",
    )
    assert q["metal_price_per_gram"] == pytest.approx(preset_price), (
        f"{metal}: preset price {q['metal_price_per_gram']} != {preset_price}"
    )


def test_explicit_price_overrides_preset():
    """Explicit metal_price_per_gram > 0 takes precedence over price_preset."""
    explicit = 999.0
    q = jewelry_quote(
        volume_mm3=500.0,
        metal="18k_yellow",
        metal_price_per_gram=explicit,
        price_preset="usd_2024_approx",
    )
    assert q["metal_price_per_gram"] == pytest.approx(explicit)


def test_unknown_preset_raises():
    """Unknown price_preset should raise ValueError."""
    with pytest.raises(ValueError, match="Unknown price_preset"):
        jewelry_quote(
            volume_mm3=500.0,
            metal="18k_yellow",
            price_preset="does_not_exist",
        )


# ---------------------------------------------------------------------------
# Casting allowance
# ---------------------------------------------------------------------------

def test_casting_allowance_zero():
    """With casting_allowance_pct=0, gross_grams == net_grams."""
    result = casting_weight(net_grams=10.0, casting_allowance_pct=0.0)
    assert result["gross_grams"] == pytest.approx(10.0)
    assert result["allowance_grams"] == pytest.approx(0.0)


def test_casting_allowance_15_pct():
    """Default 15% allowance: gross = net * 1.15."""
    result = casting_weight(net_grams=10.0, casting_allowance_pct=15.0)
    assert result["gross_grams"] == pytest.approx(11.5)
    assert result["allowance_grams"] == pytest.approx(1.5)


def test_casting_allowance_custom():
    """Custom 25% allowance: gross = net * 1.25."""
    result = casting_weight(net_grams=8.0, casting_allowance_pct=25.0)
    assert result["gross_grams"] == pytest.approx(10.0)


def test_casting_allowance_negative_raises():
    """Negative casting allowance is rejected."""
    with pytest.raises(ValueError):
        casting_weight(net_grams=10.0, casting_allowance_pct=-1.0)


# ---------------------------------------------------------------------------
# Unit conversion round-trips
# ---------------------------------------------------------------------------

def test_grams_ozt_round_trip():
    """grams → ozt → grams is lossless ±1e-9."""
    for g in [0.5, 1.0, 5.0, 31.1034768, 100.0]:
        assert abs(ozt_to_grams(grams_to_ozt(g)) - g) < 1e-9, f"ozt round-trip failed for {g}g"


def test_grams_dwt_round_trip():
    """grams → dwt → grams is lossless ±1e-9."""
    for g in [0.1, 1.0, 5.0, 15.55, 100.0]:
        assert abs(dwt_to_grams(grams_to_dwt(g)) - g) < 1e-9, f"dwt round-trip failed for {g}g"


def test_grams_per_ozt_constant():
    """GRAMS_PER_OZT == 31.1034768 (NIST)."""
    assert GRAMS_PER_OZT == pytest.approx(31.1034768)


def test_grams_per_dwt_constant():
    """GRAMS_PER_DWT == GRAMS_PER_OZT / 20."""
    assert GRAMS_PER_DWT == pytest.approx(GRAMS_PER_OZT / 20.0)


# ---------------------------------------------------------------------------
# mm → carat estimation
# ---------------------------------------------------------------------------

def test_mm_to_carat_round_brilliant_6mm():
    """6.5 mm round brilliant ~ 1 ct (trade rule of thumb ≈ 0.00370 × 6.5³)."""
    ct = mm_to_carat(6.5, cut="round_brilliant")
    # 6.5³ × 0.0037 ≈ 1.015 ct
    assert 0.9 < ct < 1.2, f"6.5mm round brilliant out of expected range: {ct}"


@pytest.mark.parametrize("cut", [
    "round_brilliant", "princess", "oval", "cushion", "pear",
    "marquise", "emerald", "asscher", "radiant", "heart",
])
def test_mm_to_carat_all_cuts_positive(cut):
    """mm_to_carat returns a positive value for all supported cuts."""
    ct = mm_to_carat(5.0, cut=cut)
    assert ct > 0, f"{cut}: carat must be positive"


def test_mm_to_carat_unknown_cut_falls_back():
    """Unknown cut falls back to round_brilliant factor without raising."""
    ct_unknown = mm_to_carat(5.0, cut="fantasy_cut")
    ct_round = mm_to_carat(5.0, cut="round_brilliant")
    assert ct_unknown == pytest.approx(ct_round)


def test_mm_to_carat_zero_diameter_raises():
    """diameter_mm <= 0 raises ValueError."""
    with pytest.raises(ValueError):
        mm_to_carat(0.0)
    with pytest.raises(ValueError):
        mm_to_carat(-1.0)


def test_mm_to_carat_scales_cubically():
    """Doubling diameter increases carat by ~8× (cubic scaling)."""
    ct1 = mm_to_carat(4.0, cut="round_brilliant")
    ct2 = mm_to_carat(8.0, cut="round_brilliant")
    ratio = ct2 / ct1
    assert abs(ratio - 8.0) < 0.01, f"Expected cubic scaling 8×, got {ratio}"


# ---------------------------------------------------------------------------
# stone_cost_line_items
# ---------------------------------------------------------------------------

def test_stone_cost_single_stone():
    """Single stone: total_cost == carat × price_per_carat."""
    result = stone_cost_line_items([
        {"cut": "round_brilliant", "carat": 0.50, "price_per_carat": 800.0, "count": 1}
    ])
    assert abs(result["total_cost"] - 400.0) < 0.001
    assert result["total_stones"] == 1
    assert abs(result["total_carats"] - 0.50) < 0.001


def test_stone_cost_multi_count():
    """count multiplies the line total."""
    result = stone_cost_line_items([
        {"cut": "pave", "carat": 0.03, "price_per_carat": 200.0, "count": 10}
    ])
    assert abs(result["total_cost"] - 60.0) < 0.001
    assert result["total_stones"] == 10


def test_stone_cost_multi_line():
    """Multi-line stone list totals correctly."""
    result = stone_cost_line_items(_STONES_SPEC)
    assert abs(result["total_cost"] - _EXPECTED_STONE_COST) < 0.001


def test_stone_cost_mm_fallback():
    """Stone spec using mm instead of carat is accepted."""
    result = stone_cost_line_items([
        {"cut": "round_brilliant", "mm": 6.5, "price_per_carat": 500.0, "count": 1}
    ])
    # mm path uses mm_to_carat; result must be > 0
    assert result["total_cost"] > 0


def test_stone_cost_empty_list():
    """Empty stones list returns zero cost."""
    result = stone_cost_line_items([])
    assert result["total_cost"] == 0.0
    assert result["total_stones"] == 0
    assert result["total_carats"] == 0.0


def test_stone_cost_missing_price_raises():
    """Missing price_per_carat raises ValueError."""
    with pytest.raises(ValueError, match="price_per_carat"):
        stone_cost_line_items([{"carat": 0.5}])


def test_stone_cost_missing_carat_and_mm_raises():
    """Missing both carat and mm raises ValueError."""
    with pytest.raises(ValueError):
        stone_cost_line_items([{"price_per_carat": 500.0}])


def test_stone_cost_negative_carat_raises():
    """Negative carat raises ValueError."""
    with pytest.raises(ValueError):
        stone_cost_line_items([{"carat": -0.1, "price_per_carat": 500.0}])


def test_stone_cost_zero_count_raises():
    """count=0 raises ValueError."""
    with pytest.raises(ValueError):
        stone_cost_line_items([{"carat": 0.5, "price_per_carat": 500.0, "count": 0}])


# ---------------------------------------------------------------------------
# labour_cost
# ---------------------------------------------------------------------------

def test_labour_bench_only():
    """Bench labour = bench_hours × hourly_rate (no stones or finishing)."""
    result = labour_cost(bench_hours=3.0, hourly_rate=80.0)
    assert result["bench_labour_cost"] == pytest.approx(240.0)
    assert result["setting_cost"] == pytest.approx(0.0)
    assert result["finishing_cost"] == pytest.approx(0.0)
    assert result["total_labour"] == pytest.approx(240.0)


def test_labour_setting_default_prong():
    """Default prong setting fee applied per stone."""
    stones = [{"count": 3, "carat": 0.1, "price_per_carat": 100.0}]
    result = labour_cost(stones=stones, setting_type="prong")
    expected_setting = DEFAULT_SETTING_FEE_PER_STONE["prong"] * 3
    assert result["setting_cost"] == pytest.approx(expected_setting)
    assert result["stone_count"] == 3


@pytest.mark.parametrize("setting_type", list(DEFAULT_SETTING_FEE_PER_STONE.keys()))
def test_labour_all_setting_types(setting_type):
    """All setting types return non-negative setting_cost."""
    stones = [{"count": 2, "carat": 0.1, "price_per_carat": 100.0}]
    result = labour_cost(stones=stones, setting_type=setting_type)
    assert result["setting_cost"] >= 0
    assert result["total_labour"] >= 0


@pytest.mark.parametrize("finishing_type", list(DEFAULT_FINISHING_COST.keys()))
def test_labour_all_finishing_types(finishing_type):
    """All finishing types return non-negative finishing_cost."""
    result = labour_cost(finishing_type=finishing_type)
    assert result["finishing_cost"] >= 0
    expected = DEFAULT_FINISHING_COST[finishing_type]
    assert result["finishing_cost"] == pytest.approx(expected)


def test_labour_finishing_cost_override():
    """Explicit finishing_cost overrides the named type default."""
    result = labour_cost(finishing_type="rhodium", finishing_cost=99.0)
    assert result["finishing_cost"] == pytest.approx(99.0)


def test_labour_unknown_setting_raises():
    """Unknown setting type raises ValueError."""
    with pytest.raises(ValueError, match="setting_type"):
        labour_cost(
            stones=[{"count": 1, "carat": 0.1, "price_per_carat": 100.0}],
            setting_type="unknown_magic_setting",
        )


def test_labour_unknown_finishing_raises():
    """Unknown finishing type raises ValueError."""
    with pytest.raises(ValueError, match="finishing_type"):
        labour_cost(finishing_type="diamond_polished_by_unicorn")


def test_labour_negative_bench_hours_raises():
    """Negative bench_hours raises ValueError."""
    with pytest.raises(ValueError):
        labour_cost(bench_hours=-1.0)


# ---------------------------------------------------------------------------
# jewelry_quote — idempotency
# ---------------------------------------------------------------------------

def test_jewelry_quote_idempotent():
    """Calling jewelry_quote twice with identical args returns identical totals."""
    kwargs = dict(
        volume_mm3=700.0,
        metal="18k_yellow",
        metal_price_per_gram=48.0,
        stones=_STONES_SPEC,
        bench_hours=2.0,
        hourly_rate=60.0,
        setting_type="prong",
        finishing_type="rhodium",
        markup_pct=15.0,
    )
    q1 = jewelry_quote(**kwargs)
    q2 = jewelry_quote(**kwargs)
    assert q1["total"] == q2["total"]
    assert q1["subtotal"] == q2["subtotal"]
    assert q1["stone_cost"] == q2["stone_cost"]


def test_jewelry_quote_no_stones_no_labour():
    """Quote with no stones and no labour reduces to pure casting cost + markup."""
    volume = 500.0
    price = 40.0
    markup = 20.0
    q = jewelry_quote(
        volume_mm3=volume,
        metal="14k_yellow",
        metal_price_per_gram=price,
        markup_pct=markup,
    )
    # metal_cost is gross_grams × price
    density = METAL_DENSITY_G_CM3["14k_yellow"]
    net_grams = density * (volume / 1000.0)
    gross_grams = net_grams * 1.15  # default 15% allowance
    expected_metal_cost = gross_grams * price
    expected_subtotal = expected_metal_cost  # no stones, no labour
    expected_total = expected_subtotal * (1 + markup / 100.0)
    assert abs(q["metal_cost"] - expected_metal_cost) < 0.001
    assert abs(q["total"] - expected_total) < 0.01


def test_jewelry_quote_zero_markup():
    """With markup_pct=0, total == subtotal."""
    q = jewelry_quote(
        volume_mm3=300.0,
        metal="sterling_925",
        metal_price_per_gram=0.80,
        markup_pct=0.0,
    )
    assert q["total"] == pytest.approx(q["subtotal"])
    assert q["markup_amount"] == pytest.approx(0.0)


def test_jewelry_quote_negative_markup_raises():
    """Negative markup raises ValueError."""
    with pytest.raises(ValueError):
        jewelry_quote(
            volume_mm3=500.0,
            metal="18k_yellow",
            metal_price_per_gram=48.0,
            markup_pct=-5.0,
        )


# ---------------------------------------------------------------------------
# metal_weight boundary cases
# ---------------------------------------------------------------------------

def test_metal_weight_explicit_density():
    """density_g_cm3 override produces correct gram weight."""
    density = 15.58  # 18k yellow
    volume = 1000.0  # 1 cm³ = 1000 mm³
    result = metal_weight(volume, density_g_cm3=density)
    assert abs(result["grams"] - density) < 1e-6
    assert result["metal"] is None  # no metal key when density override used


def test_metal_weight_zero_volume_raises():
    """volume_mm3 <= 0 raises ValueError."""
    with pytest.raises(ValueError):
        metal_weight(0.0, metal="18k_yellow")
    with pytest.raises(ValueError):
        metal_weight(-100.0, metal="18k_yellow")


def test_metal_weight_unknown_metal_raises():
    """Unknown metal key raises ValueError."""
    with pytest.raises(ValueError, match="Unknown metal"):
        metal_weight(500.0, metal="unobtainium")


def test_metal_weight_neither_metal_nor_density_raises():
    """Providing neither metal nor density_g_cm3 raises ValueError."""
    with pytest.raises(ValueError):
        metal_weight(500.0)


def test_metal_weight_negative_density_raises():
    """Negative density_g_cm3 raises ValueError."""
    with pytest.raises(ValueError):
        metal_weight(500.0, density_g_cm3=-1.0)


def test_metal_weight_case_insensitive():
    """Metal key lookup is case-insensitive."""
    result_lower = metal_weight(500.0, metal="18k_yellow")
    result_upper = metal_weight(500.0, metal="18K_YELLOW")
    assert abs(result_lower["grams"] - result_upper["grams"]) < 1e-9


# ---------------------------------------------------------------------------
# resolve_density
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metal", list(METAL_DENSITY_G_CM3.keys()))
def test_resolve_density_all_metals(metal):
    """resolve_density succeeds for every entry in METAL_DENSITY_G_CM3."""
    d = resolve_density(metal=metal)
    assert d == pytest.approx(METAL_DENSITY_G_CM3[metal])
    assert d > 0


def test_resolve_density_explicit_wins():
    """Explicit density_g_cm3 overrides the metal key."""
    d = resolve_density(metal="18k_yellow", density_g_cm3=20.0)
    assert d == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# multi_metal_compare
# ---------------------------------------------------------------------------

def test_multi_metal_compare_sorted_by_cost():
    """Results are sorted ascending by total_cost."""
    prices = {
        "14k_yellow": 37.5,
        "18k_yellow": 48.0,
        "sterling_925": 0.80,
    }
    results = multi_metal_compare(
        volume_mm3=500.0,
        metals=["14k_yellow", "18k_yellow", "sterling_925"],
        metal_prices=prices,
    )
    costs = [r["total_cost"] for r in results]
    assert costs == sorted(costs), "multi_metal_compare results are not sorted by total_cost"


def test_multi_metal_compare_default_metals():
    """Default metals list produces 8 rows."""
    results = multi_metal_compare(volume_mm3=500.0)
    assert len(results) == 8


def test_multi_metal_compare_label_present():
    """Each row has a 'label' key from METAL_LABELS."""
    results = multi_metal_compare(
        volume_mm3=500.0,
        metals=["18k_yellow", "sterling_925"],
    )
    for r in results:
        assert "label" in r
        assert r["label"]  # non-empty


# ---------------------------------------------------------------------------
# Hallmark / fineness table coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("metal", list(METAL_HALLMARK.keys()))
def test_hallmark_in_range_or_none(metal):
    """Every hallmark is either None or an integer in 1–999."""
    h = METAL_HALLMARK[metal]
    if h is not None:
        assert isinstance(h, int)
        assert 1 <= h <= 999, f"{metal}: hallmark {h} out of range"


def test_jewelry_quote_hallmark_field():
    """Full quote returns correct hallmark for the metal."""
    for metal in _METALS_5:
        q = jewelry_quote(
            volume_mm3=300.0,
            metal=metal,
            metal_price_per_gram=_SPOT_PRICES_USD_PER_G[metal],
        )
        assert q["hallmark"] == METAL_HALLMARK[metal], (
            f"{metal}: quote hallmark {q['hallmark']} != {METAL_HALLMARK[metal]}"
        )


# ---------------------------------------------------------------------------
# casting_cost — edge and boundary
# ---------------------------------------------------------------------------

def test_casting_cost_zero_price():
    """With metal_price_per_gram=0, metal_cost=0 and total=labor+finishing."""
    result = casting_cost(
        volume_mm3=500.0,
        metal="18k_yellow",
        metal_price_per_gram=0.0,
        labor=100.0,
        finishing=50.0,
    )
    assert result["metal_cost"] == pytest.approx(0.0)
    assert result["total_cost"] == pytest.approx(150.0)


def test_casting_cost_negative_price_raises():
    """Negative metal_price_per_gram raises ValueError."""
    with pytest.raises(ValueError):
        casting_cost(volume_mm3=500.0, metal="18k_yellow", metal_price_per_gram=-1.0)


def test_casting_cost_negative_labor_raises():
    """Negative labor raises ValueError."""
    with pytest.raises(ValueError):
        casting_cost(volume_mm3=500.0, metal="sterling_925", metal_price_per_gram=0.8, labor=-5.0)


def test_casting_cost_density_override():
    """density_g_cm3 override accepted; metal field returns None."""
    result = casting_cost(volume_mm3=500.0, density_g_cm3=10.0, metal_price_per_gram=1.0)
    assert result["metal"] is None
    assert result["density_g_cm3"] == pytest.approx(10.0)
