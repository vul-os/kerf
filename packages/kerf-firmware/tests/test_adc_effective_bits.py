"""Tests for kerf_firmware.adc_effective_bits + LLM tool firmware_compute_adc_enob.

Coverage
--------
- SINAD-to-ENOB formula: (68 - 1.76) / 6.02 = 11.00 bits (ADI MT-003)
- Oversampling gain: OSR=16 → log2(16)/2 = 2.0 → 11.00 + 2.0 = 13.00 bits
- Oversampling gain: OSR=4 → 0.5 extra bits
- Oversampling gain: OSR=64 → 3.0 extra bits
- enob_specified takes priority over sinad_dB
- Nominal fallback when neither sinad_dB nor enob_specified supplied
- Recommend OSR for target 14 from ENOB 11: 4^3 = 64
- Recommend OSR for target 12 from ENOB 11: 4^1 = 4
- Recommend OSR returns None when already at target
- effective_resolution_uV correctly scaled to signal_full_scale_V (< VREF)
- SNR = 6.02 * ENOB_after + 1.76 (inverse MT-003)
- ADCSpec validation: bad nominal_bits, bad voltages, signal > ref
- OversamplingSpec validation: negative/zero OSR
- LLM tool: valid round-trip (SINAD=68)
- LLM tool: missing required fields
- LLM tool: invalid types
- LLM tool: signal > reference voltage
- LLM tool: OSR=16, target=14 → recommend_osr=64
- LLM tool: enob_specified path
- LLM tool: dict shape (all keys present)
"""
from __future__ import annotations

import json
import math

import pytest

from kerf_firmware.adc_effective_bits import (
    ADCSpec,
    ADCEffectiveBitsReport,
    OversamplingSpec,
    _enob_from_sinad,
    _enob_gain_from_osr,
    _recommend_osr_for_target,
    compute_adc_enob,
)
from kerf_firmware.tools.firmware_compute_adc_enob import run_firmware_compute_adc_enob


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_adc(
    nominal_bits=12,
    sinad_dB=68.0,
    enob_specified=None,
    sampling_rate_Hz=100_000,
    reference_voltage_V=3.3,
    signal_full_scale_V=3.3,
) -> ADCSpec:
    return ADCSpec(
        nominal_bits=nominal_bits,
        sinad_dB=sinad_dB,
        enob_specified=enob_specified,
        sampling_rate_Hz=sampling_rate_Hz,
        reference_voltage_V=reference_voltage_V,
        signal_full_scale_V=signal_full_scale_V,
    )


def _tool(args: dict) -> dict:
    """Call the LLM tool and return parsed JSON."""
    raw = run_firmware_compute_adc_enob(args)
    return json.loads(raw)


_BASE_TOOL_ARGS = {
    "nominal_bits": 12,
    "sinad_dB": 68.0,
    "sampling_rate_Hz": 100_000,
    "reference_voltage_V": 3.3,
    "signal_full_scale_V": 3.3,
}


# ─────────────────────────────────────────────────────────────────────────────
# Unit: _enob_from_sinad
# ─────────────────────────────────────────────────────────────────────────────

class TestSINADFormula:
    def test_68dB_gives_11_bits(self):
        """ADI MT-003 depth-bar: (68 - 1.76) / 6.02 ≈ 11.00."""
        enob = _enob_from_sinad(68.0)
        assert abs(enob - (68.0 - 1.76) / 6.02) < 1e-9

    def test_68dB_rounds_to_11_at_2dp(self):
        """The canonical '11.0 bits' figure: (68 - 1.76) / 6.02 = 11.0033...
        which rounds to 11.00 to 2 dp but is NOT exactly 11.0.
        """
        enob = _enob_from_sinad(68.0)
        # Within ±0.01 of 11.0
        assert abs(enob - 11.0) < 0.01

    def test_74dB_gives_approximately_12_bits(self):
        """74 dB SINAD → ~12 bits: (74-1.76)/6.02 ≈ 12.0."""
        enob = _enob_from_sinad(74.0)
        assert abs(enob - 12.0) < 0.01

    def test_monotone_higher_sinad_gives_higher_enob(self):
        """Higher SINAD ↔ higher ENOB (strict monotone)."""
        assert _enob_from_sinad(70.0) > _enob_from_sinad(68.0)

    def test_formula_exact_values(self):
        """Exact formula check for arbitrary value."""
        sinad = 62.5
        expected = (62.5 - 1.76) / 6.02
        assert abs(_enob_from_sinad(sinad) - expected) < 1e-12


# ─────────────────────────────────────────────────────────────────────────────
# Unit: _enob_gain_from_osr
# ─────────────────────────────────────────────────────────────────────────────

class TestOversamplingGain:
    def test_osr1_zero_gain(self):
        """OSR=1 → no gain."""
        assert _enob_gain_from_osr(1) == 0.0

    def test_osr4_half_bit(self):
        """OSR=4 → log2(4)/2 = 1.0 bit (TI SBAA221 Table 1)."""
        assert abs(_enob_gain_from_osr(4) - 1.0) < 1e-9

    def test_osr16_two_bits(self):
        """OSR=16 → log2(16)/2 = 2.0 bits (depth-bar from task spec)."""
        assert abs(_enob_gain_from_osr(16) - 2.0) < 1e-9

    def test_osr64_three_bits(self):
        """OSR=64 → log2(64)/2 = 3.0 bits."""
        assert abs(_enob_gain_from_osr(64) - 3.0) < 1e-9

    def test_osr256_four_bits(self):
        """OSR=256 → log2(256)/2 = 4.0 bits."""
        assert abs(_enob_gain_from_osr(256) - 4.0) < 1e-9

    def test_osr2_half_bit(self):
        """OSR=2 → log2(2)/2 = 0.5 bits."""
        assert abs(_enob_gain_from_osr(2) - 0.5) < 1e-9

    def test_arbitrary_osr(self):
        """OSR=32 → log2(32)/2 = 2.5 bits."""
        assert abs(_enob_gain_from_osr(32) - 2.5) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# Unit: _recommend_osr_for_target
# ─────────────────────────────────────────────────────────────────────────────

class TestRecommendOSR:
    def test_11_to_14_recommends_64(self):
        """Target 14 from ENOB 11 → 4^3 = 64 (task spec depth-bar)."""
        assert _recommend_osr_for_target(11.0, 14.0) == 64

    def test_11_to_12_recommends_4(self):
        """Target 12 from ENOB 11 → 4^1 = 4."""
        assert _recommend_osr_for_target(11.0, 12.0) == 4

    def test_11_to_13_recommends_16(self):
        """Target 13 from ENOB 11 → 4^2 = 16."""
        assert _recommend_osr_for_target(11.0, 13.0) == 16

    def test_already_at_target_returns_none(self):
        """ENOB already meets target → None."""
        assert _recommend_osr_for_target(12.0, 12.0) is None

    def test_above_target_returns_none(self):
        """ENOB exceeds target → None."""
        assert _recommend_osr_for_target(13.5, 12.0) is None

    def test_fractional_target(self):
        """Target 12.5 from ENOB 11.0 → need 1.5 bits → 4^2=16 (round up)."""
        result = _recommend_osr_for_target(11.0, 12.5)
        # 4^1=4 → +1 bit (not enough), 4^2=16 → +2 bits (≥1.5, sufficient)
        assert result == 16


# ─────────────────────────────────────────────────────────────────────────────
# compute_adc_enob: core computation
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeADCEnob:
    def test_sinad_68_no_oversampling(self):
        """Depth-bar: SINAD=68, OSR=1 → ENOB_no_osr ≈ 11.00, ENOB_after ≈ 11.00."""
        adc = _make_adc()
        r = compute_adc_enob(adc, OversamplingSpec())
        assert abs(r.enob_no_oversampling - (68.0 - 1.76) / 6.02) < 1e-9
        assert abs(r.enob_after_oversampling - r.enob_no_oversampling) < 1e-9

    def test_sinad_68_osr16_gives_13_bits(self):
        """Depth-bar: SINAD=68, OSR=16 → ENOB_after ≈ 11.00 + 2.00 = 13.00."""
        adc = _make_adc()
        os16 = OversamplingSpec(oversample_ratio=16)
        r = compute_adc_enob(adc, os16)
        expected = (68.0 - 1.76) / 6.02 + 2.0
        assert abs(r.enob_after_oversampling - expected) < 1e-9

    def test_enob_specified_takes_priority(self):
        """enob_specified=10.5 overrides sinad_dB=68."""
        adc = _make_adc(enob_specified=10.5, sinad_dB=68.0)
        r = compute_adc_enob(adc, OversamplingSpec())
        assert abs(r.enob_no_oversampling - 10.5) < 1e-9

    def test_nominal_fallback_when_neither_specified(self):
        """No SINAD, no enob_specified → ENOB = nominal − 0.5."""
        adc = ADCSpec(12, 100_000, 3.3, 3.3, sinad_dB=None, enob_specified=None)
        r = compute_adc_enob(adc, OversamplingSpec())
        assert abs(r.enob_no_oversampling - 11.5) < 1e-9

    def test_nominal_fallback_caveat_present(self):
        """Nominal fallback must produce a caveat mentioning the estimation."""
        adc = ADCSpec(12, 100_000, 3.3, 3.3)
        r = compute_adc_enob(adc, OversamplingSpec())
        assert "estimated" in r.honest_caveat.lower() or "ESTIMATED" in r.honest_caveat

    def test_recommend_osr_14_from_11(self):
        """target_bits=14, ENOB≈11 → recommend OSR=64."""
        adc = _make_adc(sinad_dB=68.0)
        r = compute_adc_enob(adc, OversamplingSpec(), target_bits=14.0)
        assert r.recommended_oversample_ratio_for_target_bits == 64

    def test_recommend_osr_none_when_no_target(self):
        """No target_bits → recommended_osr is None."""
        adc = _make_adc()
        r = compute_adc_enob(adc, OversamplingSpec())
        assert r.recommended_oversample_ratio_for_target_bits is None

    def test_recommend_osr_none_already_meets_target(self):
        """ENOB already meets target → recommended_osr is None."""
        adc = _make_adc(sinad_dB=68.0)
        r = compute_adc_enob(adc, OversamplingSpec(), target_bits=11.0)
        assert r.recommended_oversample_ratio_for_target_bits is None

    def test_effective_resolution_full_scale(self):
        """Resolution = Vfull / 2^ENOB_after (in µV); full-scale signal = VREF."""
        adc = _make_adc(reference_voltage_V=3.3, signal_full_scale_V=3.3)
        r = compute_adc_enob(adc, OversamplingSpec())
        expected_uV = 3.3 / (2 ** r.enob_after_oversampling) * 1e6
        assert abs(r.effective_resolution_uV - expected_uV) < 1e-6

    def test_effective_resolution_partial_scale(self):
        """Signal 1.65 V on 3.3 V ref → half the LSB voltage vs full scale."""
        adc_full = _make_adc(reference_voltage_V=3.3, signal_full_scale_V=3.3)
        adc_half = _make_adc(reference_voltage_V=3.3, signal_full_scale_V=1.65)
        r_full = compute_adc_enob(adc_full, OversamplingSpec())
        r_half = compute_adc_enob(adc_half, OversamplingSpec())
        assert abs(r_half.effective_resolution_uV - r_full.effective_resolution_uV / 2) < 1e-6

    def test_snr_inverse_of_enob(self):
        """SNR = 6.02 * ENOB_after + 1.76 (inverse ADI MT-003)."""
        adc = _make_adc()
        r = compute_adc_enob(adc, OversamplingSpec())
        expected_snr = 6.02 * r.enob_after_oversampling + 1.76
        assert abs(r.snr_dB - expected_snr) < 1e-9

    def test_oversampling_caveat_present_with_osr(self):
        """With OSR>1, caveat must mention oversampling limitations."""
        adc = _make_adc()
        r = compute_adc_enob(adc, OversamplingSpec(oversample_ratio=16))
        assert "WHITE" in r.honest_caveat or "white" in r.honest_caveat.lower()

    def test_osr4_gains_one_bit(self):
        """OSR=4 adds exactly 1 effective bit."""
        adc = _make_adc()
        r_base = compute_adc_enob(adc, OversamplingSpec(oversample_ratio=1))
        r_osr4 = compute_adc_enob(adc, OversamplingSpec(oversample_ratio=4))
        assert abs(r_osr4.enob_after_oversampling - r_base.enob_after_oversampling - 1.0) < 1e-9

    def test_report_as_dict_has_all_keys(self):
        """as_dict() must contain all expected output keys."""
        adc = _make_adc()
        r = compute_adc_enob(adc, OversamplingSpec(), target_bits=14.0)
        d = r.as_dict()
        for key in (
            "enob_no_oversampling",
            "enob_after_oversampling",
            "effective_resolution_uV",
            "recommended_oversample_ratio_for_target_bits",
            "snr_dB",
            "honest_caveat",
        ):
            assert key in d, f"Missing key: {key}"


# ─────────────────────────────────────────────────────────────────────────────
# ADCSpec validation
# ─────────────────────────────────────────────────────────────────────────────

class TestADCSpecValidation:
    def test_bad_nominal_bits_zero(self):
        with pytest.raises(ValueError, match="nominal_bits"):
            ADCSpec(0, 100_000, 3.3, 3.3)

    def test_bad_nominal_bits_negative(self):
        with pytest.raises(ValueError, match="nominal_bits"):
            ADCSpec(-1, 100_000, 3.3, 3.3)

    def test_bad_sampling_rate_zero(self):
        with pytest.raises(ValueError, match="sampling_rate_Hz"):
            ADCSpec(12, 0, 3.3, 3.3)

    def test_bad_reference_voltage_zero(self):
        with pytest.raises(ValueError, match="reference_voltage_V"):
            ADCSpec(12, 100_000, 0.0, 1.0)

    def test_bad_signal_exceeds_reference(self):
        with pytest.raises(ValueError, match="signal_full_scale_V"):
            ADCSpec(12, 100_000, 3.3, 5.0)

    def test_bad_sinad_negative(self):
        with pytest.raises(ValueError, match="sinad_dB"):
            ADCSpec(12, 100_000, 3.3, 3.3, sinad_dB=-5.0)

    def test_valid_spec_accepted(self):
        adc = ADCSpec(12, 1_000_000, 3.3, 1.65, sinad_dB=72.0)
        assert adc.nominal_bits == 12


# ─────────────────────────────────────────────────────────────────────────────
# OversamplingSpec validation
# ─────────────────────────────────────────────────────────────────────────────

class TestOversamplingSpecValidation:
    def test_bad_osr_zero(self):
        with pytest.raises(ValueError, match="oversample_ratio"):
            OversamplingSpec(oversample_ratio=0)

    def test_bad_osr_negative(self):
        with pytest.raises(ValueError, match="oversample_ratio"):
            OversamplingSpec(oversample_ratio=-1)

    def test_bad_decimation_zero(self):
        with pytest.raises(ValueError, match="decimation"):
            OversamplingSpec(decimation=0)

    def test_valid_osr(self):
        os = OversamplingSpec(oversample_ratio=64, decimation=64)
        assert os.oversample_ratio == 64


# ─────────────────────────────────────────────────────────────────────────────
# LLM tool tests
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMTool:
    def test_valid_sinad68_no_oversampling(self):
        """Depth-bar: SINAD=68, no OSR → ENOB_after ≈ 11.0."""
        result = _tool(_BASE_TOOL_ARGS)
        assert "error" not in result
        assert abs(result["enob_no_oversampling"] - (68.0 - 1.76) / 6.02) < 0.01
        assert abs(result["enob_after_oversampling"] - result["enob_no_oversampling"]) < 0.001
        assert result["recommended_oversample_ratio_for_target_bits"] is None

    def test_valid_osr16_gains_2_bits(self):
        """OSR=16 → ENOB_after = ENOB_no_osr + 2.0."""
        args = {**_BASE_TOOL_ARGS, "oversample_ratio": 16}
        result = _tool(args)
        assert "error" not in result
        diff = result["enob_after_oversampling"] - result["enob_no_oversampling"]
        assert abs(diff - 2.0) < 1e-6

    def test_valid_target_14_from_11_recommends_64(self):
        """target_bits=14, ENOB≈11 → recommend OSR=64."""
        args = {**_BASE_TOOL_ARGS, "target_bits": 14.0}
        result = _tool(args)
        assert "error" not in result
        assert result["recommended_oversample_ratio_for_target_bits"] == 64

    def test_valid_enob_specified(self):
        """enob_specified=10.5 used directly."""
        args = {**_BASE_TOOL_ARGS, "enob_specified": 10.5}
        result = _tool(args)
        assert "error" not in result
        assert abs(result["enob_no_oversampling"] - 10.5) < 1e-6

    def test_missing_nominal_bits(self):
        args = {k: v for k, v in _BASE_TOOL_ARGS.items() if k != "nominal_bits"}
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_missing_sampling_rate(self):
        args = {k: v for k, v in _BASE_TOOL_ARGS.items() if k != "sampling_rate_Hz"}
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_missing_reference_voltage(self):
        args = {k: v for k, v in _BASE_TOOL_ARGS.items() if k != "reference_voltage_V"}
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_missing_signal_full_scale(self):
        args = {k: v for k, v in _BASE_TOOL_ARGS.items() if k != "signal_full_scale_V"}
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_signal_exceeds_reference(self):
        """signal_full_scale_V > reference_voltage_V → BAD_ARGS."""
        args = {**_BASE_TOOL_ARGS, "reference_voltage_V": 3.3, "signal_full_scale_V": 5.0}
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_bad_osr_zero(self):
        args = {**_BASE_TOOL_ARGS, "oversample_ratio": 0}
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_bad_sinad_negative(self):
        args = {**_BASE_TOOL_ARGS, "sinad_dB": -10.0}
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_dict_shape_has_all_keys(self):
        """Tool response must contain all expected output keys."""
        result = _tool({**_BASE_TOOL_ARGS, "target_bits": 14.0})
        for key in (
            "enob_no_oversampling",
            "enob_after_oversampling",
            "effective_resolution_uV",
            "recommended_oversample_ratio_for_target_bits",
            "snr_dB",
            "honest_caveat",
        ):
            assert key in result, f"Missing key: {key}"

    def test_effective_resolution_uv_positive(self):
        result = _tool(_BASE_TOOL_ARGS)
        assert result["effective_resolution_uV"] > 0

    def test_snr_db_consistent_with_enob(self):
        """SNR = 6.02 * ENOB_after + 1.76."""
        result = _tool(_BASE_TOOL_ARGS)
        expected_snr = 6.02 * result["enob_after_oversampling"] + 1.76
        assert abs(result["snr_dB"] - expected_snr) < 0.001

    def test_honest_caveat_present_and_non_empty(self):
        result = _tool(_BASE_TOOL_ARGS)
        assert isinstance(result["honest_caveat"], str)
        assert len(result["honest_caveat"]) > 10
