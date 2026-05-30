"""Tests for kerf_firmware.clock_tree_verify + clock_tree_specs.

Clock-tree arithmetic reference (RM0383 §6.3.2):
    f_PLL_in = f_HSE / PLLM
    f_VCO    = f_PLL_in × PLLN
    f_SYSCLK = f_VCO / PLLP
    f_USB    = f_VCO / PLLQ
    f_AHB    = f_SYSCLK / HPRE
    f_APB1   = f_AHB / PPRE1
    f_APB2   = f_AHB / PPRE2

Covers
------
- Valid STM32F411 config at 96 MHz (USB-safe with 48 MHz on PLLQ)
- Valid STM32F407 config at 168 MHz
- Over-spec SYSCLK (F411 > 100 MHz) → SYSCLK_EXCEEDED
- Over-spec APB1 (> 42 MHz) → APB1_EXCEEDED
- Over-spec APB2 (> 84 MHz) → APB2_EXCEEDED
- Over-spec VCO (> 432 MHz) → VCO_OUT_OF_RANGE
- USB requires exactly 48 MHz → PERIPHERAL_CLOCK_EXACT_MISMATCH when wrong
- USB exactly 48 MHz → passes
- ADC ≤ 36 MHz via explicit peripheral_clocks
- ADC over 36 MHz → PERIPHERAL_CLOCK_EXCEEDED
- PLL input out of range → PLL_INPUT_OUT_OF_RANGE
- Invalid PLLP → INVALID_PLLP
- HSE out of range → HSE_OUT_OF_RANGE
- Unknown chip → KeyError
- LLM tool smoke tests (valid, invalid args, unknown chip)
- STM32F411: HSE=8, PLLM=8, PLLN=336, PLLP=2 → SYSCLK=168 MHz (over F411 max)
- STM32F411: HSE=8, PLLM=8, PLLN=192, PLLP=4 → SYSCLK=48 MHz, USB=48 MHz (pass)
"""
from __future__ import annotations

import json

import pytest

from kerf_firmware.clock_tree_specs import (
    STM32F411,
    STM32F407,
    get_clock_spec,
    list_clock_chip_ids,
)
from kerf_firmware.clock_tree_verify import (
    ClockConfig,
    ClockTreeReport,
    ClockViolation,
    verify_clock_tree,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def violation_kinds(report: ClockTreeReport) -> list[str]:
    return [v.kind for v in report.violations]


def make_f411_base() -> ClockConfig:
    """STM32F411, HSE=8 MHz, PLLM=8, PLLN=192, PLLP=4, PLLQ=8
    → PLL_in=1 MHz, VCO=192 MHz, SYSCLK=48 MHz.
    PPRE1=4 → APB1=12 MHz; PPRE2=2 → APB2=24 MHz.  All within spec.
    """
    return ClockConfig(
        source="HSE",
        hse_hz=8_000_000,
        pll_m=8,
        pll_n=192,
        pll_p=4,
        pll_q=8,
        hpre=1,
        ppre1=4,
        ppre2=2,
    )


# ─────────────────────────────────────────────────────────────────────────────
# clock_tree_specs tests
# ─────────────────────────────────────────────────────────────────────────────

class TestClockTreeSpecs:
    def test_registry_contains_f411(self):
        assert "STM32F411" in list_clock_chip_ids()

    def test_registry_contains_f407(self):
        assert "STM32F407" in list_clock_chip_ids()

    def test_get_clock_spec_canonical(self):
        spec = get_clock_spec("STM32F411")
        assert spec.chip_family == "STM32F411"

    def test_get_clock_spec_alias_lowercase(self):
        spec = get_clock_spec("stm32f411")
        assert spec.chip_family == "STM32F411"

    def test_get_clock_spec_alias_f411ce(self):
        spec = get_clock_spec("stm32f411ce")
        assert spec.chip_family == "STM32F411"

    def test_get_clock_spec_f407_alias(self):
        spec = get_clock_spec("stm32f407vg")
        assert spec.chip_family == "STM32F407"

    def test_unknown_chip_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown clock-tree chip"):
            get_clock_spec("nonexistent_xyz")

    def test_f411_sysclk_max(self):
        assert STM32F411.sysclk_max_hz == 100_000_000

    def test_f407_sysclk_max(self):
        assert STM32F407.sysclk_max_hz == 168_000_000

    def test_f411_apb1_max(self):
        assert STM32F411.apb1_max_hz == 42_000_000

    def test_f411_apb2_max(self):
        assert STM32F411.apb2_max_hz == 84_000_000

    def test_f411_vco_range(self):
        assert STM32F411.pll_vco_min_hz == 100_000_000
        assert STM32F411.pll_vco_max_hz == 432_000_000

    def test_f411_usb_constraint_exact(self):
        usb = STM32F411.peripheral_constraints["USB_OTG_FS"]
        assert usb.exact_hz == 48_000_000

    def test_f411_adc_constraint_max(self):
        adc = STM32F411.peripheral_constraints["ADC"]
        assert adc.max_hz == 36_000_000

    def test_f411_pll_input_range(self):
        assert STM32F411.pll_input_min_hz == 1_000_000
        assert STM32F411.pll_input_max_hz == 2_000_000


# ─────────────────────────────────────────────────────────────────────────────
# DEPTH BAR — exact arithmetic from the spec brief
# ─────────────────────────────────────────────────────────────────────────────

class TestDepthBarArithmetic:
    """Reproduce the exact examples in the FIRMWARE-CLOCK-TREE-VERIFY spec."""

    def test_hse8_pllm8_plln336_pllp2_is_over_f411_sysclk(self):
        """HSE=8, PLLM=8, PLLN=336, PLLP=2
        → VCO_in=1 MHz, VCO=336 MHz, SYSCLK=168 MHz > 100 MHz (F411 max).
        Must raise SYSCLK_EXCEEDED.
        """
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=336,
            pll_p=2,
            pll_q=7,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )
        report = verify_clock_tree("STM32F411", cfg)
        assert report.vco_hz == 336_000_000
        assert report.sysclk_hz == 168_000_000
        assert report.ok is False
        assert "SYSCLK_EXCEEDED" in violation_kinds(report)

    def test_hse8_pllm8_plln192_pllp4_sysclk_48mhz_usb_48mhz(self):
        """HSE=8, PLLM=8, PLLN=192, PLLP=4, PLLQ=4
        → VCO_in=1 MHz, VCO=192 MHz, SYSCLK=48 MHz, USB=48 MHz.
        All within spec for F411 — should pass.
        """
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=4,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )
        report = verify_clock_tree("STM32F411", cfg)
        assert report.pll_input_hz == 1_000_000
        assert report.vco_hz == 192_000_000
        assert report.sysclk_hz == 48_000_000
        assert report.usb_clk_hz == 48_000_000
        assert report.ok is True, report.as_dict()


# ─────────────────────────────────────────────────────────────────────────────
# Valid STM32F411 configuration (96 MHz SYSCLK with USB at 48 MHz)
# ─────────────────────────────────────────────────────────────────────────────

class TestF411ValidConfig96MHz:
    """HSE=8 MHz, PLLM=8, PLLN=192, PLLP=2 → SYSCLK=96 MHz; PLLQ=4 → USB=48 MHz.
    APB1 = 96/4 = 24 MHz; APB2 = 96/2 = 48 MHz.  All within F411 spec.
    """

    def make_cfg(self) -> ClockConfig:
        return ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )

    def test_arithmetic_vco(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.pll_input_hz == 1_000_000
        assert r.vco_hz == 192_000_000

    def test_arithmetic_sysclk(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.sysclk_hz == 96_000_000

    def test_arithmetic_usb(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.usb_clk_hz == 48_000_000

    def test_arithmetic_apb1(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.apb1_hz == 24_000_000

    def test_arithmetic_apb2(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.apb2_hz == 48_000_000

    def test_ok_true(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.ok is True, r.as_dict()

    def test_no_violations(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.violations == []

    def test_chip_name_in_report(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.chip == "STM32F411"

    def test_caveats_mention_jitter(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        combined = " ".join(r.caveats).lower()
        assert "jitter" in combined or "phase" in combined

    def test_as_dict_schema(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        d = r.as_dict()
        assert "ok" in d
        assert "clocks" in d
        assert "violations" in d
        assert "caveats" in d
        assert "peripheral_results" in d

    def test_alias_accepted(self):
        r = verify_clock_tree("stm32f411", self.make_cfg())
        assert r.ok is True


# ─────────────────────────────────────────────────────────────────────────────
# Valid STM32F407 at 168 MHz
# ─────────────────────────────────────────────────────────────────────────────

class TestF407Valid168MHz:
    """HSE=8 MHz, PLLM=8, PLLN=336, PLLP=2 → SYSCLK=168 MHz (F407 max).
    PLLQ=7 → USB = 336/7 = 48 MHz.
    APB1 = 168/4 = 42 MHz; APB2 = 168/2 = 84 MHz.  All within F407 spec.
    """

    def make_cfg(self) -> ClockConfig:
        return ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=336,
            pll_p=2,
            pll_q=7,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )

    def test_sysclk_168mhz(self):
        r = verify_clock_tree("STM32F407", self.make_cfg())
        assert r.sysclk_hz == 168_000_000

    def test_ok_true(self):
        r = verify_clock_tree("STM32F407", self.make_cfg())
        assert r.ok is True, r.as_dict()

    def test_apb1_42mhz(self):
        r = verify_clock_tree("STM32F407", self.make_cfg())
        assert r.apb1_hz == 42_000_000

    def test_apb2_84mhz(self):
        r = verify_clock_tree("STM32F407", self.make_cfg())
        assert r.apb2_hz == 84_000_000


# ─────────────────────────────────────────────────────────────────────────────
# SYSCLK_EXCEEDED — STM32F411 driven at 168 MHz (over 100 MHz limit)
# ─────────────────────────────────────────────────────────────────────────────

class TestF411SysclkExceeded:
    """HSE=8, PLLM=8, PLLN=336, PLLP=2 → SYSCLK=168 MHz > 100 MHz (F411 max)."""

    def make_cfg(self) -> ClockConfig:
        return ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=336,
            pll_p=2,
            pll_q=7,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )

    def test_ok_false(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.ok is False

    def test_sysclk_exceeded_violation(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert "SYSCLK_EXCEEDED" in violation_kinds(r)

    def test_violation_actual_hz_correct(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        v = next(x for x in r.violations if x.kind == "SYSCLK_EXCEEDED")
        assert v.actual_hz == 168_000_000

    def test_violation_limit_hz_is_100mhz(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        v = next(x for x in r.violations if x.kind == "SYSCLK_EXCEEDED")
        assert v.limit_hz == 100_000_000

    def test_sysclk_computed_correctly(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.sysclk_hz == 168_000_000

    def test_vco_correct(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.vco_hz == 336_000_000


# ─────────────────────────────────────────────────────────────────────────────
# APB1_EXCEEDED
# ─────────────────────────────────────────────────────────────────────────────

class TestF411Apb1Exceeded:
    """SYSCLK=96 MHz, PPRE1=1 → APB1=96 MHz > 42 MHz."""

    def make_cfg(self) -> ClockConfig:
        return ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=1,   # APB1 = SYSCLK = 96 MHz → over 42 MHz
            ppre2=2,
        )

    def test_ok_false(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.ok is False

    def test_apb1_exceeded_detected(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert "APB1_EXCEEDED" in violation_kinds(r)

    def test_violation_actual_hz(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        v = next(x for x in r.violations if x.kind == "APB1_EXCEEDED")
        assert v.actual_hz == 96_000_000

    def test_violation_limit_hz_42mhz(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        v = next(x for x in r.violations if x.kind == "APB1_EXCEEDED")
        assert v.limit_hz == 42_000_000


# ─────────────────────────────────────────────────────────────────────────────
# APB2_EXCEEDED
# ─────────────────────────────────────────────────────────────────────────────

class TestF411Apb2Exceeded:
    """SYSCLK=96 MHz, PPRE2=1 → APB2=96 MHz > 84 MHz."""

    def make_cfg(self) -> ClockConfig:
        return ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=1,   # APB2 = SYSCLK = 96 MHz → over 84 MHz
        )

    def test_ok_false(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.ok is False

    def test_apb2_exceeded_detected(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert "APB2_EXCEEDED" in violation_kinds(r)

    def test_violation_limit_hz_84mhz(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        v = next(x for x in r.violations if x.kind == "APB2_EXCEEDED")
        assert v.limit_hz == 84_000_000


# ─────────────────────────────────────────────────────────────────────────────
# VCO_OUT_OF_RANGE
# ─────────────────────────────────────────────────────────────────────────────

class TestVcoOutOfRange:
    """VCO > 432 MHz: HSE=8, PLLM=2, PLLN=432, PLL_in=4 MHz → VCO=1728 MHz."""

    def make_cfg(self) -> ClockConfig:
        return ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=2,
            pll_n=432,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )

    def test_vco_out_of_range_detected(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert "VCO_OUT_OF_RANGE" in violation_kinds(r)

    def test_pll_input_also_out_of_range(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert "PLL_INPUT_OUT_OF_RANGE" in violation_kinds(r)

    def test_ok_false(self):
        r = verify_clock_tree("STM32F411", self.make_cfg())
        assert r.ok is False


# ─────────────────────────────────────────────────────────────────────────────
# USB requires exactly 48 MHz
# ─────────────────────────────────────────────────────────────────────────────

class TestUsbExact48MHz:
    def test_usb_wrong_frequency_flagged(self):
        """VCO=192 MHz, PLLQ=6 → USB=32 MHz ≠ 48 MHz."""
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=2,
            pll_q=6,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )
        r = verify_clock_tree("STM32F411", cfg)
        assert r.usb_clk_hz == 32_000_000
        assert r.ok is False
        assert "PERIPHERAL_CLOCK_EXACT_MISMATCH" in violation_kinds(r)

    def test_usb_exact_48mhz_passes(self):
        """VCO=192 MHz, PLLQ=4 → USB=48 MHz — must pass."""
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )
        r = verify_clock_tree("STM32F411", cfg)
        assert r.usb_clk_hz == 48_000_000
        usb_violations = [v for v in r.violations if v.parameter == "USB_OTG_FS"]
        assert usb_violations == []

    def test_usb_skip_when_pllq_zero(self):
        """PLLQ=0 → skip USB check."""
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=2,
            pll_q=0,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )
        r = verify_clock_tree("STM32F411", cfg)
        assert r.usb_clk_hz is None
        usb_violations = [v for v in r.violations if v.parameter == "USB_OTG_FS"]
        assert usb_violations == []


# ─────────────────────────────────────────────────────────────────────────────
# ADC ≤ 36 MHz
# ─────────────────────────────────────────────────────────────────────────────

class TestAdcClock:
    def test_adc_within_spec(self):
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
            peripheral_clocks={"ADC": 18_000_000},
        )
        r = verify_clock_tree("STM32F411", cfg)
        adc_violations = [v for v in r.violations if v.parameter == "ADC"]
        assert adc_violations == []

    def test_adc_over_spec(self):
        """Explicit ADC=48 MHz > 36 MHz → PERIPHERAL_CLOCK_EXCEEDED."""
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
            peripheral_clocks={"ADC": 48_000_000},
        )
        r = verify_clock_tree("STM32F411", cfg)
        assert r.ok is False
        assert "PERIPHERAL_CLOCK_EXCEEDED" in violation_kinds(r)
        adc_v = next(v for v in r.violations if v.parameter == "ADC")
        assert adc_v.actual_hz == 48_000_000
        assert adc_v.limit_hz == 36_000_000

    def test_adc_at_limit_passes(self):
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
            peripheral_clocks={"ADC": 36_000_000},
        )
        r = verify_clock_tree("STM32F411", cfg)
        adc_violations = [v for v in r.violations if v.parameter == "ADC"]
        assert adc_violations == []


# ─────────────────────────────────────────────────────────────────────────────
# PLL input out of range
# ─────────────────────────────────────────────────────────────────────────────

class TestPllInputOutOfRange:
    def test_pll_input_over_2mhz(self):
        """PLLM=1 → PLL_in = 8 MHz > 2 MHz → PLL_INPUT_OUT_OF_RANGE."""
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=1,
            pll_n=100,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )
        r = verify_clock_tree("STM32F411", cfg)
        assert "PLL_INPUT_OUT_OF_RANGE" in violation_kinds(r)
        v = next(x for x in r.violations if x.kind == "PLL_INPUT_OUT_OF_RANGE")
        assert v.actual_hz == 8_000_000

    def test_pll_input_exact_1mhz_ok(self):
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=4,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )
        r = verify_clock_tree("STM32F411", cfg)
        assert "PLL_INPUT_OUT_OF_RANGE" not in violation_kinds(r)


# ─────────────────────────────────────────────────────────────────────────────
# Invalid PLLP
# ─────────────────────────────────────────────────────────────────────────────

class TestInvalidPllp:
    def test_pllp_3_invalid(self):
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=3,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )
        r = verify_clock_tree("STM32F411", cfg)
        assert "INVALID_PLLP" in violation_kinds(r)

    def test_pllp_2_valid(self):
        cfg = ClockConfig(
            source="HSE",
            hse_hz=8_000_000,
            pll_m=8,
            pll_n=192,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )
        r = verify_clock_tree("STM32F411", cfg)
        assert "INVALID_PLLP" not in violation_kinds(r)


# ─────────────────────────────────────────────────────────────────────────────
# HSE out of range
# ─────────────────────────────────────────────────────────────────────────────

class TestHseOutOfRange:
    def test_hse_too_high(self):
        cfg = ClockConfig(
            source="HSE",
            hse_hz=50_000_000,
            pll_m=25,
            pll_n=200,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )
        r = verify_clock_tree("STM32F411", cfg)
        assert "HSE_OUT_OF_RANGE" in violation_kinds(r)

    def test_hse_8mhz_valid(self):
        r = verify_clock_tree("STM32F411", make_f411_base())
        assert "HSE_OUT_OF_RANGE" not in violation_kinds(r)


# ─────────────────────────────────────────────────────────────────────────────
# Unknown chip
# ─────────────────────────────────────────────────────────────────────────────

class TestUnknownChip:
    def test_unknown_chip_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown clock-tree chip"):
            verify_clock_tree("nonexistent_chip_xyz", make_f411_base())


# ─────────────────────────────────────────────────────────────────────────────
# HSI source
# ─────────────────────────────────────────────────────────────────────────────

class TestHsiSource:
    def test_hsi_source_no_pll(self):
        cfg = ClockConfig(source="HSI", use_pll=False, ppre1=1, ppre2=1)
        r = verify_clock_tree("STM32F411", cfg)
        assert r.sysclk_hz == 16_000_000
        assert r.source_hz == 16_000_000
        assert r.ok is True

    def test_hsi_with_pll(self):
        """HSI=16 MHz, PLLM=16, PLLN=192, PLLP=2 → SYSCLK=96 MHz."""
        cfg = ClockConfig(
            source="HSI",
            pll_m=16,
            pll_n=192,
            pll_p=2,
            pll_q=4,
            hpre=1,
            ppre1=4,
            ppre2=2,
        )
        r = verify_clock_tree("STM32F411", cfg)
        assert r.pll_input_hz == 1_000_000
        assert r.vco_hz == 192_000_000
        assert r.sysclk_hz == 96_000_000


# ─────────────────────────────────────────────────────────────────────────────
# LLM tool smoke tests
# ─────────────────────────────────────────────────────────────────────────────

class TestFirmwareVerifyClockTreeTool:
    def _call(self, args: dict) -> dict:
        from kerf_firmware.tools.firmware_verify_clock_tree import (
            run_firmware_verify_clock_tree,
        )
        return json.loads(run_firmware_verify_clock_tree(args))

    def test_valid_f411_96mhz(self):
        result = self._call({
            "chip": "STM32F411",
            "config": {
                "source": "HSE",
                "hse_hz": 8_000_000,
                "pll_m": 8,
                "pll_n": 192,
                "pll_p": 2,
                "pll_q": 4,
                "hpre": 1,
                "ppre1": 4,
                "ppre2": 2,
            },
        })
        assert result.get("ok") is True, result

    def test_f411_sysclk_exceeded(self):
        result = self._call({
            "chip": "STM32F411",
            "config": {
                "source": "HSE",
                "hse_hz": 8_000_000,
                "pll_m": 8,
                "pll_n": 336,
                "pll_p": 2,
                "pll_q": 7,
                "hpre": 1,
                "ppre1": 4,
                "ppre2": 2,
            },
        })
        assert result.get("ok") is False
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "SYSCLK_EXCEEDED" in kinds

    def test_missing_chip(self):
        result = self._call({"config": {"source": "HSE"}})
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_missing_config(self):
        result = self._call({"chip": "STM32F411"})
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_unknown_chip(self):
        result = self._call({
            "chip": "nonexistent_xyz",
            "config": {"source": "HSE"},
        })
        assert "error" in result
        assert result.get("code") == "UNKNOWN_CHIP"

    def test_result_has_clocks_dict(self):
        result = self._call({
            "chip": "STM32F411",
            "config": {
                "source": "HSE", "hse_hz": 8_000_000,
                "pll_m": 8, "pll_n": 192, "pll_p": 2, "pll_q": 4,
                "hpre": 1, "ppre1": 4, "ppre2": 2,
            },
        })
        assert "clocks" in result
        clocks = result["clocks"]
        assert "sysclk_hz" in clocks
        assert "vco_hz" in clocks
        assert "apb1_hz" in clocks
        assert "apb2_hz" in clocks

    def test_result_has_caveats(self):
        result = self._call({
            "chip": "STM32F411",
            "config": {
                "source": "HSE", "hse_hz": 8_000_000,
                "pll_m": 8, "pll_n": 192, "pll_p": 2, "pll_q": 4,
                "hpre": 1, "ppre1": 4, "ppre2": 2,
            },
        })
        assert "caveats" in result
        assert len(result["caveats"]) > 0

    def test_f411_alias(self):
        result = self._call({
            "chip": "stm32f411",
            "config": {
                "source": "HSE", "hse_hz": 8_000_000,
                "pll_m": 8, "pll_n": 192, "pll_p": 2, "pll_q": 4,
                "hpre": 1, "ppre1": 4, "ppre2": 2,
            },
        })
        assert result.get("ok") is True, result
