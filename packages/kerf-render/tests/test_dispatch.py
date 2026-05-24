"""Tests for kerf_render.dispatch — GPU-SKU dispatch policy (T-409).

Verifies that:
- small / browser-preview scenes → rtx_a4000 or l4
- medium scenes → a6000 or l40s
- large / hero scenes → a100
- cinema scenes → h100
- uncertain / empty input → l4 (fallback)
- every returned SKU exists in GPU_RATES_USD_PER_SECOND
"""
from __future__ import annotations

import pytest

from kerf_render.dispatch import select_gpu_sku
from kerf_render.pricing_meter import GPU_RATES_USD_PER_SECOND

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_SKUS = set(GPU_RATES_USD_PER_SECOND.keys())
_MEDIUM_SKUS = {"a6000", "l40s"}
_LARGE_SKUS  = {"a100", "a100_sxm", "rtx_pro_6000", "h100", "h200"}


def _in_rate_table(sku: str) -> bool:
    """Assert helper: SKU must exist in the rate table."""
    return sku in _VALID_SKUS


# ---------------------------------------------------------------------------
# Fallback / empty input
# ---------------------------------------------------------------------------

class TestFallback:
    def test_empty_dict_returns_l4(self):
        sku = select_gpu_sku({})
        assert sku == "l4", f"expected l4, got {sku}"
        assert _in_rate_table(sku)

    def test_none_input_returns_fallback(self):
        sku = select_gpu_sku(None)  # type: ignore[arg-type]
        assert sku == "l4"
        assert _in_rate_table(sku)

    def test_no_preset_no_metrics_returns_l4(self):
        sku = select_gpu_sku({"job_id": "abc123"})
        assert sku == "l4"
        assert _in_rate_table(sku)


# ---------------------------------------------------------------------------
# Preset-only signals
# ---------------------------------------------------------------------------

class TestPresetSignal:
    def test_preview_preset_returns_rtx_a4000(self):
        sku = select_gpu_sku({"preset": "preview"})
        assert sku == "rtx_a4000"
        assert _in_rate_table(sku)

    def test_thumbnail_preset_returns_rtx_a4000(self):
        sku = select_gpu_sku({"preset": "thumbnail"})
        assert sku == "rtx_a4000"
        assert _in_rate_table(sku)

    def test_draft_preset_returns_l4(self):
        sku = select_gpu_sku({"preset": "draft"})
        assert sku == "l4"
        assert _in_rate_table(sku)

    def test_standard_preset_returns_medium_sku(self):
        sku = select_gpu_sku({"preset": "standard"})
        assert sku in _MEDIUM_SKUS, f"expected medium SKU, got {sku}"
        assert _in_rate_table(sku)

    def test_hero_preset_returns_a100(self):
        sku = select_gpu_sku({"preset": "hero"})
        assert sku == "a100"
        assert _in_rate_table(sku)

    def test_cinema_preset_returns_h100(self):
        sku = select_gpu_sku({"preset": "cinema"})
        assert sku == "h100"
        assert _in_rate_table(sku)

    def test_preset_case_insensitive(self):
        assert select_gpu_sku({"preset": "HERO"}) == "a100"
        assert select_gpu_sku({"preset": "Cinema"}) == "h100"
        assert select_gpu_sku({"preset": "DRAFT"}) == "l4"


# ---------------------------------------------------------------------------
# Sample-count signals
# ---------------------------------------------------------------------------

class TestSampleSignal:
    def test_tiny_samples_returns_rtx_a4000(self):
        sku = select_gpu_sku({"samples": 32})
        assert sku == "rtx_a4000"
        assert _in_rate_table(sku)

    def test_small_samples_returns_l4(self):
        sku = select_gpu_sku({"samples": 256})
        assert sku == "l4"
        assert _in_rate_table(sku)

    def test_medium_samples_returns_medium_sku(self):
        sku = select_gpu_sku({"samples": 1024})
        assert sku in _MEDIUM_SKUS
        assert _in_rate_table(sku)

    def test_large_samples_returns_large_sku(self):
        sku = select_gpu_sku({"samples": 4096})
        assert sku in _LARGE_SKUS
        assert _in_rate_table(sku)

    def test_cinema_samples_returns_large_or_cinema_sku(self):
        sku = select_gpu_sku({"samples": 16384})
        assert sku in _LARGE_SKUS
        assert _in_rate_table(sku)


# ---------------------------------------------------------------------------
# Resolution signals
# ---------------------------------------------------------------------------

class TestResolutionSignal:
    def test_4k_resolution_returns_large_sku(self):
        sku = select_gpu_sku({"resolution": [3840, 2160]})
        assert sku in _LARGE_SKUS
        assert _in_rate_table(sku)

    def test_fullhd_resolution_returns_medium_sku(self):
        sku = select_gpu_sku({"resolution": [1920, 1080]})
        assert sku in _MEDIUM_SKUS
        assert _in_rate_table(sku)

    def test_small_resolution_returns_small_sku(self):
        sku = select_gpu_sku({"resolution": [640, 480]})
        assert sku in {"rtx_a4000", "l4"}
        assert _in_rate_table(sku)


# ---------------------------------------------------------------------------
# Poly-count signals
# ---------------------------------------------------------------------------

class TestPolySignal:
    def test_very_large_poly_count_upgrades_to_large(self):
        sku = select_gpu_sku({"poly_count": 1_000_000})
        assert sku in _LARGE_SKUS
        assert _in_rate_table(sku)

    def test_medium_poly_count_returns_medium_sku(self):
        sku = select_gpu_sku({"poly_count": 200_000})
        assert sku in _MEDIUM_SKUS
        assert _in_rate_table(sku)


# ---------------------------------------------------------------------------
# Combined / override scenarios
# ---------------------------------------------------------------------------

class TestCombined:
    def test_draft_preset_with_high_poly_count_upgrades(self):
        """draft preset + huge poly count should pick large SKU."""
        sku = select_gpu_sku({"preset": "draft", "poly_count": 600_000})
        assert sku in _LARGE_SKUS
        assert _in_rate_table(sku)

    def test_hero_preset_with_4k_resolution(self):
        """hero + 4K → a100 (hero tier dominates; resolution confirms it)."""
        sku = select_gpu_sku({"preset": "hero", "resolution": [3840, 2160]})
        assert sku == "a100"
        assert _in_rate_table(sku)

    def test_preview_tier_not_downgraded_by_low_resolution(self):
        """Browser preview with a tiny resolution stays at rtx_a4000."""
        sku = select_gpu_sku({"preset": "preview", "resolution": [320, 240]})
        assert sku == "rtx_a4000"
        assert _in_rate_table(sku)

    def test_standard_with_many_lights_upgrades(self):
        """standard preset + many lights nudges up to large tier."""
        sku = select_gpu_sku({"preset": "standard", "light_count": 10})
        assert sku in _LARGE_SKUS
        assert _in_rate_table(sku)


# ---------------------------------------------------------------------------
# Rate-table membership: every possible return value must be a valid key
# ---------------------------------------------------------------------------

class TestRateTableMembership:
    """Exhaustive check: run all preset values through dispatch and verify
    every result is in GPU_RATES_USD_PER_SECOND."""

    @pytest.mark.parametrize("preset", [
        "preview", "thumbnail", "browser",
        "draft", "standard", "hero", "cinema", "",
    ])
    def test_preset_sku_in_rate_table(self, preset):
        sku = select_gpu_sku({"preset": preset})
        assert sku in GPU_RATES_USD_PER_SECOND, (
            f"select_gpu_sku returned {sku!r} which is NOT in GPU_RATES_USD_PER_SECOND"
        )

    @pytest.mark.parametrize("samples", [16, 64, 256, 512, 1024, 2048, 4096, 8192, 16384])
    def test_sample_sku_in_rate_table(self, samples):
        sku = select_gpu_sku({"samples": samples})
        assert sku in GPU_RATES_USD_PER_SECOND

    @pytest.mark.parametrize("res", [
        [320, 240], [640, 480], [1280, 720], [1920, 1080], [2560, 1440], [3840, 2160],
    ])
    def test_resolution_sku_in_rate_table(self, res):
        sku = select_gpu_sku({"resolution": res})
        assert sku in GPU_RATES_USD_PER_SECOND
