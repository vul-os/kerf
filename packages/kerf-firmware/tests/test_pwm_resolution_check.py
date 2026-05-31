"""Tests for kerf_firmware.pwm_resolution_check + LLM tool
firmware_check_pwm_resolution.

Coverage
--------
P01  16 MHz clock, 1 kHz PWM, 16-bit counter:
         prescaler=1, ARR=15999, resolution=13.97 bits, |freq_error| < 0.001%
P02  16 MHz, 20 kHz PWM, 16-bit counter:
         prescaler=1, ARR=799, resolution=9.64 bits
P03  High target_freq (500 kHz) → low resolution (<= 8 bits for 16 MHz 16-bit counter)
P04  8-bit counter limits ARR to <= 255, so resolution <= 8 bits always
P05  10-bit counter limits resolution to <= 10 bits
P06  PWMConfigSpec validation: mcu_clock_hz <= 0 raises ValueError
P07  PWMConfigSpec validation: target_pwm_freq_Hz <= 0 raises ValueError
P08  PWMConfigSpec validation: counter_bits not in {8,10,16,32} raises ValueError
P09  PWMConfigSpec validation: desired_resolution_bits < 1 raises ValueError
P10  meets_resolution_requirement=True when achievable >= desired
P11  meets_resolution_requirement=False when achievable < desired (high freq + 8-bit)
P12  PWMResolutionReport.as_dict() contains all required keys with correct types
P13  honest_caveat mentions STM32F411, ATmega328P, interrupt latency, dead-time
P14  freq_error_pct formula verified numerically: (actual − target) / target × 100
P15  32-bit counter: 100 MHz clock, 50 Hz servo PWM → very high resolution (>20 bits)
P16  LLM tool: valid round-trip 16 MHz / 1 kHz / 16-bit → JSON, prescaler=1, ARR=15999
P17  LLM tool: valid round-trip 16 MHz / 20 kHz / 16-bit → JSON, ARR=799
P18  LLM tool: missing mcu_clock_hz → BAD_ARGS
P19  LLM tool: missing target_pwm_freq_Hz → BAD_ARGS
P20  LLM tool: missing counter_bits → BAD_ARGS
P21  LLM tool: counter_bits=7 (invalid) → BAD_ARGS
P22  LLM tool: mcu_clock_hz=0 → BAD_ARGS
P23  LLM tool: target_pwm_freq_Hz=0 → BAD_ARGS
P24  LLM tool: async wrapper returns same result as sync handler
P25  STM32F411 @ 100 MHz, 20 kHz, 16-bit: prescaler=1, ARR=4999, resolution=12.29 bits
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_firmware.pwm_resolution_check import (
    PWMConfigSpec,
    PWMResolutionReport,
    check_pwm_resolution,
)
from kerf_firmware.tools.firmware_check_pwm_resolution import (
    run_firmware_check_pwm_resolution,
    run_firmware_check_pwm_resolution_async,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _spec(
    clock: int = 16_000_000,
    freq: float = 1000.0,
    bits: int = 16,
    desired: int = 10,
    label: str = "TestMCU",
) -> PWMConfigSpec:
    return PWMConfigSpec(
        mcu_clock_hz=clock,
        target_pwm_freq_Hz=freq,
        counter_bits=bits,
        desired_resolution_bits=desired,
        mcu_label=label,
    )


def _tool_args(
    clock: int = 16_000_000,
    freq: float = 1000.0,
    bits: int = 16,
    desired: int = 10,
    label: str = "TestMCU",
) -> dict:
    return {
        "mcu_clock_hz": clock,
        "target_pwm_freq_Hz": freq,
        "counter_bits": bits,
        "desired_resolution_bits": desired,
        "mcu_label": label,
    }


# ─────────────────────────────────────────────────────────────────────────────
# P01 — 16 MHz, 1 kHz, 16-bit: prescaler=1, ARR=15999, resolution=13.97 bits
# ─────────────────────────────────────────────────────────────────────────────

def test_p01_16mhz_1khz_16bit_baseline():
    """ATmega328P Timer1 @ 16 MHz, 1 kHz, 16-bit: prescaler=1, ARR=15999."""
    s = _spec(clock=16_000_000, freq=1000.0, bits=16)
    report = check_pwm_resolution(s)

    assert report.recommended_prescaler == 1, (
        f"Expected prescaler=1, got {report.recommended_prescaler}"
    )
    assert report.recommended_arr_top == 15999, (
        f"Expected ARR=15999, got {report.recommended_arr_top}"
    )
    # resolution = log2(15999 + 1) = log2(16000) ≈ 13.9657
    expected_res = math.log2(16000)
    assert abs(report.achievable_resolution_bits - expected_res) < 0.001, (
        f"resolution_bits {report.achievable_resolution_bits:.4f} != {expected_res:.4f}"
    )
    # freq error: f_actual = 16e6 / (1 × 16000) = 1000 Hz exactly
    assert abs(report.freq_error_pct) < 0.001, (
        f"freq_error_pct {report.freq_error_pct:.6f}% should be ≈ 0"
    )
    assert abs(report.actual_pwm_freq_Hz - 1000.0) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# P02 — 16 MHz, 20 kHz, 16-bit: prescaler=1, ARR=799, resolution=9.64 bits
# ─────────────────────────────────────────────────────────────────────────────

def test_p02_16mhz_20khz_16bit():
    """16 MHz, 20 kHz, 16-bit: prescaler=1, ARR=799, resolution≈9.64 bits."""
    s = _spec(clock=16_000_000, freq=20_000.0, bits=16)
    report = check_pwm_resolution(s)

    assert report.recommended_prescaler == 1
    assert report.recommended_arr_top == 799
    # resolution = log2(800) ≈ 9.6439
    expected_res = math.log2(800)
    assert abs(report.achievable_resolution_bits - expected_res) < 0.001, (
        f"resolution_bits {report.achievable_resolution_bits:.4f} != {expected_res:.4f}"
    )
    # freq exact: 16e6 / 800 = 20000 Hz
    assert abs(report.freq_error_pct) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# P03 — High target_freq (500 kHz) → very low resolution for 16 MHz clock
# ─────────────────────────────────────────────────────────────────────────────

def test_p03_high_freq_low_resolution():
    """16 MHz, 500 kHz PWM → ARR is very small, resolution <= 6 bits."""
    s = _spec(clock=16_000_000, freq=500_000.0, bits=16)
    report = check_pwm_resolution(s)

    # At 500 kHz from 16 MHz: clock/freq = 32, so ARR+1 = 32/P
    # With P=1: ARR = 31, resolution = log2(32) = 5 bits
    assert report.achievable_resolution_bits <= 6.0, (
        f"Expected low resolution for 500 kHz, got {report.achievable_resolution_bits:.2f} bits"
    )
    assert report.recommended_arr_top <= 31


# ─────────────────────────────────────────────────────────────────────────────
# P04 — 8-bit counter: resolution always <= 8 bits
# ─────────────────────────────────────────────────────────────────────────────

def test_p04_8bit_counter_caps_resolution():
    """8-bit counter: ARR <= 255, so resolution <= 8 bits always."""
    # Even with a slow PWM frequency and fast clock, 8-bit counter caps at 8 bits
    s = _spec(clock=16_000_000, freq=100.0, bits=8)
    report = check_pwm_resolution(s)

    assert report.recommended_arr_top <= 255, (
        f"ARR {report.recommended_arr_top} exceeds 8-bit limit of 255"
    )
    assert report.achievable_resolution_bits <= 8.0 + 1e-9, (
        f"resolution_bits {report.achievable_resolution_bits:.4f} exceeds 8-bit cap"
    )


# ─────────────────────────────────────────────────────────────────────────────
# P05 — 10-bit counter: resolution capped at 10 bits
# ─────────────────────────────────────────────────────────────────────────────

def test_p05_10bit_counter_caps_resolution():
    """10-bit counter: ARR <= 1023, so resolution <= 10 bits."""
    s = _spec(clock=16_000_000, freq=100.0, bits=10)
    report = check_pwm_resolution(s)

    assert report.recommended_arr_top <= 1023, (
        f"ARR {report.recommended_arr_top} exceeds 10-bit limit of 1023"
    )
    assert report.achievable_resolution_bits <= 10.0 + 1e-9, (
        f"resolution_bits {report.achievable_resolution_bits:.4f} exceeds 10-bit cap"
    )


# ─────────────────────────────────────────────────────────────────────────────
# P06 — PWMConfigSpec: invalid clock
# ─────────────────────────────────────────────────────────────────────────────

def test_p06_invalid_clock_raises():
    """PWMConfigSpec: mcu_clock_hz <= 0 raises ValueError."""
    with pytest.raises(ValueError, match="mcu_clock_hz"):
        PWMConfigSpec(mcu_clock_hz=0, target_pwm_freq_Hz=1000.0, counter_bits=16)

    with pytest.raises(ValueError, match="mcu_clock_hz"):
        PWMConfigSpec(mcu_clock_hz=-1, target_pwm_freq_Hz=1000.0, counter_bits=16)


# ─────────────────────────────────────────────────────────────────────────────
# P07 — PWMConfigSpec: invalid PWM frequency
# ─────────────────────────────────────────────────────────────────────────────

def test_p07_invalid_pwm_freq_raises():
    """PWMConfigSpec: target_pwm_freq_Hz <= 0 raises ValueError."""
    with pytest.raises(ValueError, match="target_pwm_freq_Hz"):
        PWMConfigSpec(mcu_clock_hz=16_000_000, target_pwm_freq_Hz=0.0, counter_bits=16)

    with pytest.raises(ValueError, match="target_pwm_freq_Hz"):
        PWMConfigSpec(mcu_clock_hz=16_000_000, target_pwm_freq_Hz=-100.0, counter_bits=16)


# ─────────────────────────────────────────────────────────────────────────────
# P08 — PWMConfigSpec: invalid counter_bits
# ─────────────────────────────────────────────────────────────────────────────

def test_p08_invalid_counter_bits_raises():
    """PWMConfigSpec: counter_bits not in {8,10,16,32} raises ValueError."""
    with pytest.raises(ValueError, match="counter_bits"):
        PWMConfigSpec(mcu_clock_hz=16_000_000, target_pwm_freq_Hz=1000.0, counter_bits=12)

    with pytest.raises(ValueError, match="counter_bits"):
        PWMConfigSpec(mcu_clock_hz=16_000_000, target_pwm_freq_Hz=1000.0, counter_bits=0)


# ─────────────────────────────────────────────────────────────────────────────
# P09 — PWMConfigSpec: invalid desired_resolution_bits
# ─────────────────────────────────────────────────────────────────────────────

def test_p09_invalid_desired_resolution_raises():
    """PWMConfigSpec: desired_resolution_bits < 1 raises ValueError."""
    with pytest.raises(ValueError, match="desired_resolution_bits"):
        PWMConfigSpec(
            mcu_clock_hz=16_000_000,
            target_pwm_freq_Hz=1000.0,
            counter_bits=16,
            desired_resolution_bits=0,
        )


# ─────────────────────────────────────────────────────────────────────────────
# P10 — meets_resolution_requirement=True
# ─────────────────────────────────────────────────────────────────────────────

def test_p10_meets_resolution_requirement_true():
    """16 MHz, 1 kHz, 16-bit: achievable ~13.97 bits >= 10 bits → meets=True."""
    s = _spec(clock=16_000_000, freq=1000.0, bits=16, desired=10)
    report = check_pwm_resolution(s)
    assert report.meets_resolution_requirement is True, (
        f"Expected meets=True, got False (achievable={report.achievable_resolution_bits:.2f})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# P11 — meets_resolution_requirement=False
# ─────────────────────────────────────────────────────────────────────────────

def test_p11_meets_resolution_requirement_false():
    """16 MHz, 500 kHz, 8-bit: low resolution fails desired=10 → meets=False."""
    s = _spec(clock=16_000_000, freq=500_000.0, bits=8, desired=10)
    report = check_pwm_resolution(s)
    # At 500 kHz from 16 MHz: ARR+1 <= 32, resolution <= log2(32)=5 bits < 10
    assert report.meets_resolution_requirement is False, (
        f"Expected meets=False for low resolution, got True "
        f"(achievable={report.achievable_resolution_bits:.2f})"
    )


# ─────────────────────────────────────────────────────────────────────────────
# P12 — as_dict() contains all required keys
# ─────────────────────────────────────────────────────────────────────────────

def test_p12_as_dict_required_keys():
    """PWMResolutionReport.as_dict() contains all required keys with correct types."""
    s = _spec()
    report = check_pwm_resolution(s)
    d = report.as_dict()

    required = {
        "actual_pwm_freq_Hz",
        "freq_error_pct",
        "achievable_resolution_bits",
        "recommended_prescaler",
        "recommended_arr_top",
        "meets_resolution_requirement",
        "honest_caveat",
    }
    assert required.issubset(d.keys()), f"Missing keys: {required - d.keys()}"
    assert isinstance(d["actual_pwm_freq_Hz"], float)
    assert isinstance(d["freq_error_pct"], float)
    assert isinstance(d["achievable_resolution_bits"], float)
    assert isinstance(d["recommended_prescaler"], int)
    assert isinstance(d["recommended_arr_top"], int)
    assert isinstance(d["meets_resolution_requirement"], bool)
    assert isinstance(d["honest_caveat"], str)


# ─────────────────────────────────────────────────────────────────────────────
# P13 — honest_caveat mentions expected content
# ─────────────────────────────────────────────────────────────────────────────

def test_p13_honest_caveat_content():
    """honest_caveat mentions STM32F411, ATmega328P, interrupt latency, dead-time."""
    s = _spec()
    report = check_pwm_resolution(s)
    caveat = report.honest_caveat.lower()
    assert "stm32f411" in caveat or "stm32" in caveat, (
        "honest_caveat should mention STM32F411"
    )
    assert "atmega328p" in caveat or "atmega" in caveat, (
        "honest_caveat should mention ATmega328P"
    )
    assert "interrupt" in caveat, "honest_caveat should mention interrupt latency"
    assert "dead" in caveat, "honest_caveat should mention dead-time"


# ─────────────────────────────────────────────────────────────────────────────
# P14 — freq_error_pct formula verified numerically
# ─────────────────────────────────────────────────────────────────────────────

def test_p14_freq_error_formula():
    """freq_error_pct = (actual − target) / target × 100 verified numerically."""
    clock = 16_000_000
    target = 1000.0
    s = _spec(clock=clock, freq=target, bits=16)
    report = check_pwm_resolution(s)

    p = report.recommended_prescaler
    arr = report.recommended_arr_top
    expected_actual = clock / (p * (arr + 1))
    expected_error = (expected_actual - target) / target * 100.0

    assert abs(report.actual_pwm_freq_Hz - expected_actual) < 1e-6
    assert abs(report.freq_error_pct - expected_error) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# P15 — 32-bit counter, 100 MHz clock, 50 Hz servo PWM → very high resolution
# ─────────────────────────────────────────────────────────────────────────────

def test_p15_32bit_high_resolution_servo():
    """STM32F411 TIM2 @ 100 MHz, 50 Hz servo: 32-bit counter → >20 bits resolution."""
    s = _spec(clock=100_000_000, freq=50.0, bits=32)
    report = check_pwm_resolution(s)

    # With P=1: ARR = 100e6/50 - 1 = 1999999, resolution = log2(2000000) ≈ 20.93 bits
    assert report.achievable_resolution_bits > 20.0, (
        f"Expected >20 bits resolution, got {report.achievable_resolution_bits:.2f}"
    )
    assert abs(report.freq_error_pct) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# P16 — LLM tool: valid round-trip 16 MHz / 1 kHz / 16-bit
# ─────────────────────────────────────────────────────────────────────────────

def test_p16_llm_tool_1khz_16bit():
    """LLM tool: 16 MHz / 1 kHz / 16-bit → JSON with prescaler=1, ARR=15999."""
    result = run_firmware_check_pwm_resolution(_tool_args(
        clock=16_000_000, freq=1000.0, bits=16
    ))
    data = json.loads(result)
    assert "error" not in data, f"Unexpected error: {data}"
    assert data["recommended_prescaler"] == 1
    assert data["recommended_arr_top"] == 15999
    assert abs(data["achievable_resolution_bits"] - math.log2(16000)) < 0.001
    assert abs(data["freq_error_pct"]) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# P17 — LLM tool: 16 MHz / 20 kHz / 16-bit → ARR=799
# ─────────────────────────────────────────────────────────────────────────────

def test_p17_llm_tool_20khz_16bit():
    """LLM tool: 16 MHz / 20 kHz / 16-bit → JSON with ARR=799, resolution≈9.64 bits."""
    result = run_firmware_check_pwm_resolution(_tool_args(
        clock=16_000_000, freq=20_000.0, bits=16
    ))
    data = json.loads(result)
    assert "error" not in data, f"Unexpected error: {data}"
    assert data["recommended_arr_top"] == 799
    assert abs(data["achievable_resolution_bits"] - math.log2(800)) < 0.001


# ─────────────────────────────────────────────────────────────────────────────
# P18-P23 — LLM tool: argument validation
# ─────────────────────────────────────────────────────────────────────────────

def test_p18_llm_tool_missing_clock():
    """LLM tool: missing mcu_clock_hz → BAD_ARGS."""
    result = run_firmware_check_pwm_resolution({
        "target_pwm_freq_Hz": 1000.0, "counter_bits": 16
    })
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS"


def test_p19_llm_tool_missing_freq():
    """LLM tool: missing target_pwm_freq_Hz → BAD_ARGS."""
    result = run_firmware_check_pwm_resolution({
        "mcu_clock_hz": 16_000_000, "counter_bits": 16
    })
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS"


def test_p20_llm_tool_missing_counter_bits():
    """LLM tool: missing counter_bits → BAD_ARGS."""
    result = run_firmware_check_pwm_resolution({
        "mcu_clock_hz": 16_000_000, "target_pwm_freq_Hz": 1000.0
    })
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS"


def test_p21_llm_tool_invalid_counter_bits():
    """LLM tool: counter_bits=7 → BAD_ARGS."""
    result = run_firmware_check_pwm_resolution(_tool_args() | {"counter_bits": 7})
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS"


def test_p22_llm_tool_zero_clock():
    """LLM tool: mcu_clock_hz=0 → BAD_ARGS."""
    result = run_firmware_check_pwm_resolution(_tool_args() | {"mcu_clock_hz": 0})
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS"


def test_p23_llm_tool_zero_freq():
    """LLM tool: target_pwm_freq_Hz=0 → BAD_ARGS."""
    result = run_firmware_check_pwm_resolution(_tool_args() | {"target_pwm_freq_Hz": 0})
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS"


# ─────────────────────────────────────────────────────────────────────────────
# P24 — async wrapper matches sync
# ─────────────────────────────────────────────────────────────────────────────

def test_p24_async_wrapper_matches_sync():
    """Async wrapper returns same result as sync handler."""
    sync_result = run_firmware_check_pwm_resolution(_tool_args(
        clock=16_000_000, freq=1000.0, bits=16
    ))
    async_result = asyncio.run(
        run_firmware_check_pwm_resolution_async(
            None,
            json.dumps(_tool_args(clock=16_000_000, freq=1000.0, bits=16)).encode(),
        )
    )
    assert json.loads(sync_result) == json.loads(async_result)


# ─────────────────────────────────────────────────────────────────────────────
# P25 — STM32F411 @ 100 MHz, 20 kHz, 16-bit: prescaler=1, ARR=4999
# ─────────────────────────────────────────────────────────────────────────────

def test_p25_stm32f411_100mhz_20khz_16bit():
    """STM32F411 TIM3 @ 100 MHz, 20 kHz, 16-bit: prescaler=1, ARR=4999, ~12.29 bits."""
    s = _spec(clock=100_000_000, freq=20_000.0, bits=16)
    report = check_pwm_resolution(s)

    assert report.recommended_prescaler == 1
    assert report.recommended_arr_top == 4999
    # resolution = log2(5000) ≈ 12.2877
    expected_res = math.log2(5000)
    assert abs(report.achievable_resolution_bits - expected_res) < 0.001, (
        f"resolution_bits {report.achievable_resolution_bits:.4f} != {expected_res:.4f}"
    )
    # freq exact: 100e6 / 5000 = 20000 Hz
    assert abs(report.freq_error_pct) < 0.001
