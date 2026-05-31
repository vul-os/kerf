"""Tests for kerf_firmware.uart_baud_drift_check + LLM tool
firmware_check_uart_baud_drift.

Coverage
--------
U01  16 MHz clock, target 9600: UBRR=103 → actual≈9615.4, drift≈+0.16% → reliable
U02  16 MHz clock, target 115200: UBRR=8 → actual≈111111, drift≈−3.55% → NOT reliable
U03  16 MHz clock, target 115200, double_speed: UBRR=16 → actual≈117647, drift≈+2.12% → flag
U04  8 MHz clock, target 9600: UBRR=51 → actual≈9615.4, drift≈+0.16% → reliable
U05  80 MHz STM32-style clock, target 115200: UBRR=42 → drift≈0.94% (reliable), recommendations include
     double_speed entry with |drift| < 0.5%
U06  Recommendation engine finds at least one entry with |drift| < 0.5% for 80 MHz / 115200
U07  Recommendation engine: 16 MHz / 9600 has a normal-mode entry with |drift| < 0.5%
U08  Recommendation list is sorted by |drift| ascending
U09  UartConfigSpec validation: mcu_clock_hz <= 0 raises ValueError
U10  UartConfigSpec validation: ubrr_register_value < 0 raises ValueError
U11  UartConfigSpec validation: mode not in allowed set raises ValueError
U12  check_uart_baud_drift: target_baud <= 0 raises ValueError
U13  BaudDriftReport.as_dict() contains all required keys
U14  honest_caveat mentions ATmega and STM32
U15  LLM tool: valid round-trip (16 MHz, UBRR=103, target 9600) → JSON response, reliable=True
U16  LLM tool: 16 MHz UBRR=8 target 115200 → reliable=False in JSON response
U17  LLM tool: missing mcu_clock_hz → BAD_ARGS
U18  LLM tool: missing ubrr_register_value → BAD_ARGS
U19  LLM tool: missing target_baud → BAD_ARGS
U20  LLM tool: invalid mode → BAD_ARGS
U21  LLM tool: mcu_clock_hz=0 → BAD_ARGS
U22  LLM tool: async wrapper returns same result as sync handler
U23  drift_pct formula: (actual − nominal) / nominal × 100 verified numerically
U24  reliable boundary: drift exactly 2.0% → reliable=False (strictly less than)
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_firmware.uart_baud_drift_check import (
    UartConfigSpec,
    BaudDriftReport,
    check_uart_baud_drift,
)
from kerf_firmware.tools.firmware_check_uart_baud_drift import (
    run_firmware_check_uart_baud_drift,
    run_firmware_check_uart_baud_drift_async,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _cfg(
    clock: int = 16_000_000,
    ubrr: int = 103,
    mode: str = "normal",
    label: str = "TestMCU",
) -> UartConfigSpec:
    return UartConfigSpec(
        mcu_clock_hz=clock,
        ubrr_register_value=ubrr,
        mode=mode,
        mcu_label=label,
    )


def _tool_args(
    clock: int = 16_000_000,
    ubrr: int = 103,
    target: int = 9600,
    mode: str = "normal",
    label: str = "TestMCU",
) -> dict:
    return {
        "mcu_clock_hz": clock,
        "ubrr_register_value": ubrr,
        "target_baud": target,
        "mode": mode,
        "mcu_label": label,
    }


# ─────────────────────────────────────────────────────────────────────────────
# U01 — 16 MHz, 9600 baud, UBRR=103
# ─────────────────────────────────────────────────────────────────────────────

def test_u01_16mhz_9600_ubrr103_reliable():
    """ATmega328P @ 16 MHz, UBRR=103: actual≈9615.4, drift≈+0.16%, reliable."""
    cfg = _cfg(clock=16_000_000, ubrr=103, mode="normal")
    report = check_uart_baud_drift(cfg, 9600)

    assert report.nominal_baud == 9600
    assert abs(report.actual_baud - 9615.384615) < 0.1, (
        f"actual baud {report.actual_baud:.4f} not close to 9615.4"
    )
    assert abs(report.drift_pct - 0.16) < 0.01, (
        f"drift_pct {report.drift_pct:.4f} not close to 0.16%"
    )
    assert report.reliable is True, "Expected reliable=True for 0.16% drift"


# ─────────────────────────────────────────────────────────────────────────────
# U02 — 16 MHz, 115200 baud, UBRR=8 (normal) → NOT reliable
# ─────────────────────────────────────────────────────────────────────────────

def test_u02_16mhz_115200_ubrr8_not_reliable():
    """ATmega328P @ 16 MHz, UBRR=8, target 115200: drift≈−3.55%, NOT reliable."""
    cfg = _cfg(clock=16_000_000, ubrr=8, mode="normal")
    report = check_uart_baud_drift(cfg, 115200)

    # actual = 16e6 / (16 * 9) = 111111.111...
    assert abs(report.actual_baud - 111111.111) < 0.1, (
        f"actual baud {report.actual_baud:.4f} not close to 111111"
    )
    assert abs(report.drift_pct - (-3.55)) < 0.02, (
        f"drift_pct {report.drift_pct:.4f} not close to -3.55%"
    )
    assert report.reliable is False, (
        "Expected reliable=False for -3.55% drift (exceeds ±2% RS-232 threshold)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# U03 — 16 MHz, 115200 baud, double_speed, UBRR=16 → flag
# ─────────────────────────────────────────────────────────────────────────────

def test_u03_16mhz_115200_double_speed_ubrr16_flag():
    """ATmega328P @ 16 MHz, double_speed, UBRR=16: drift≈+2.12%, NOT reliable."""
    cfg = _cfg(clock=16_000_000, ubrr=16, mode="double_speed")
    report = check_uart_baud_drift(cfg, 115200)

    # actual = 16e6 / (8 * 17) = 117647.058...
    assert abs(report.actual_baud - 117647.058) < 0.1, (
        f"actual baud {report.actual_baud:.4f} not close to 117647"
    )
    assert abs(report.drift_pct - 2.12) < 0.02, (
        f"drift_pct {report.drift_pct:.4f} not close to +2.12%"
    )
    assert report.reliable is False, (
        "Expected reliable=False for +2.12% drift (exceeds ±2% RS-232 threshold)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# U04 — 8 MHz clock, target 9600, UBRR=51
# ─────────────────────────────────────────────────────────────────────────────

def test_u04_8mhz_9600_ubrr51_reliable():
    """ATmega328P @ 8 MHz, UBRR=51: actual≈9615.4, drift≈+0.16%, reliable."""
    cfg = _cfg(clock=8_000_000, ubrr=51, mode="normal", label="ATmega328P @ 8 MHz")
    report = check_uart_baud_drift(cfg, 9600)

    # actual = 8e6 / (16 * 52) = 9615.384...
    assert abs(report.actual_baud - 9615.384) < 0.1
    assert abs(report.drift_pct - 0.16) < 0.01
    assert report.reliable is True


# ─────────────────────────────────────────────────────────────────────────────
# U05 — 80 MHz STM32-style, target 115200, UBRR=42 → reliable, drift < 2%
# ─────────────────────────────────────────────────────────────────────────────

def test_u05_80mhz_115200_ubrr42_reliable_with_drift():
    """80 MHz clock (STM32 PCLK2), UBRR=42, target 115200: drift≈0.94%, reliable."""
    cfg = _cfg(clock=80_000_000, ubrr=42, mode="normal", label="STM32F411 @ 80 MHz")
    report = check_uart_baud_drift(cfg, 115200)

    # actual = 80e6 / (16 * 43) = 116279.07...
    assert abs(report.actual_baud - 116279.0) < 1.0
    # drift should be approximately 0.94%
    assert abs(report.drift_pct) < 2.0, (
        f"drift_pct {report.drift_pct:.4f} should be < 2% for reliable link"
    )
    assert report.reliable is True


# ─────────────────────────────────────────────────────────────────────────────
# U06 — 80 MHz recommendations include double_speed entry with |drift| < 0.5%
# ─────────────────────────────────────────────────────────────────────────────

def test_u06_80mhz_recommendations_include_sub_half_pct():
    """Recommendation engine for 80 MHz finds at least one entry with |drift| < 0.5%."""
    cfg = _cfg(clock=80_000_000, ubrr=42, mode="normal", label="STM32F411 @ 80 MHz")
    report = check_uart_baud_drift(cfg, 115200)

    assert len(report.recommended_baud_settings) > 0, (
        "Expected at least one recommended baud setting for 80 MHz clock"
    )
    best_drift = min(abs(r["drift_pct"]) for r in report.recommended_baud_settings)
    assert best_drift < 0.5, (
        f"Best recommendation drift {best_drift:.4f}% should be < 0.5%"
    )


# ─────────────────────────────────────────────────────────────────────────────
# U07 — 16 MHz / 9600 recommendation engine finds normal-mode entry < 0.5%
# ─────────────────────────────────────────────────────────────────────────────

def test_u07_16mhz_recommendations_include_9600():
    """16 MHz clock: recommendation list includes 9600 normal mode with |drift| < 0.5%."""
    cfg = _cfg(clock=16_000_000, ubrr=103, mode="normal")
    report = check_uart_baud_drift(cfg, 9600)

    recs_9600_normal = [
        r for r in report.recommended_baud_settings
        if r["baud"] == 9600 and r["mode"] == "normal"
    ]
    assert len(recs_9600_normal) >= 1, "Expected 9600/normal in recommendations for 16 MHz"
    entry = recs_9600_normal[0]
    assert abs(entry["drift_pct"]) < 0.5


# ─────────────────────────────────────────────────────────────────────────────
# U08 — Recommendation list sorted by |drift_pct| ascending
# ─────────────────────────────────────────────────────────────────────────────

def test_u08_recommendations_sorted_by_abs_drift():
    """Recommendation list is sorted by |drift_pct| ascending."""
    cfg = _cfg(clock=16_000_000, ubrr=103, mode="normal")
    report = check_uart_baud_drift(cfg, 9600)

    drifts = [abs(r["drift_pct"]) for r in report.recommended_baud_settings]
    assert drifts == sorted(drifts), (
        f"Recommendation list not sorted by |drift_pct|: {drifts}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# U09 — UartConfigSpec: invalid clock
# ─────────────────────────────────────────────────────────────────────────────

def test_u09_invalid_clock_raises():
    """UartConfigSpec: mcu_clock_hz <= 0 raises ValueError."""
    with pytest.raises(ValueError, match="mcu_clock_hz"):
        UartConfigSpec(mcu_clock_hz=0, ubrr_register_value=103)

    with pytest.raises(ValueError, match="mcu_clock_hz"):
        UartConfigSpec(mcu_clock_hz=-1, ubrr_register_value=103)


# ─────────────────────────────────────────────────────────────────────────────
# U10 — UartConfigSpec: negative UBRR
# ─────────────────────────────────────────────────────────────────────────────

def test_u10_negative_ubrr_raises():
    """UartConfigSpec: ubrr_register_value < 0 raises ValueError."""
    with pytest.raises(ValueError, match="ubrr_register_value"):
        UartConfigSpec(mcu_clock_hz=16_000_000, ubrr_register_value=-1)


# ─────────────────────────────────────────────────────────────────────────────
# U11 — UartConfigSpec: invalid mode
# ─────────────────────────────────────────────────────────────────────────────

def test_u11_invalid_mode_raises():
    """UartConfigSpec: mode not in {normal, double_speed} raises ValueError."""
    with pytest.raises(ValueError, match="mode"):
        UartConfigSpec(mcu_clock_hz=16_000_000, ubrr_register_value=103, mode="u4x")


# ─────────────────────────────────────────────────────────────────────────────
# U12 — check_uart_baud_drift: invalid target_baud
# ─────────────────────────────────────────────────────────────────────────────

def test_u12_zero_target_baud_raises():
    """check_uart_baud_drift: target_baud <= 0 raises ValueError."""
    cfg = _cfg()
    with pytest.raises(ValueError, match="target_baud"):
        check_uart_baud_drift(cfg, 0)

    with pytest.raises(ValueError, match="target_baud"):
        check_uart_baud_drift(cfg, -9600)


# ─────────────────────────────────────────────────────────────────────────────
# U13 — as_dict() has all required keys
# ─────────────────────────────────────────────────────────────────────────────

def test_u13_as_dict_keys():
    """BaudDriftReport.as_dict() contains all required keys."""
    cfg = _cfg()
    report = check_uart_baud_drift(cfg, 9600)
    d = report.as_dict()

    required_keys = {
        "nominal_baud",
        "actual_baud",
        "drift_pct",
        "reliable",
        "recommended_baud_settings",
        "honest_caveat",
    }
    assert required_keys.issubset(d.keys()), (
        f"Missing keys: {required_keys - d.keys()}"
    )

    # Check recommendation list item keys
    if d["recommended_baud_settings"]:
        rec_keys = {"baud", "ubrr", "mode", "actual_baud", "drift_pct"}
        first = d["recommended_baud_settings"][0]
        assert rec_keys.issubset(first.keys()), (
            f"Missing rec keys: {rec_keys - first.keys()}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# U14 — honest_caveat content
# ─────────────────────────────────────────────────────────────────────────────

def test_u14_honest_caveat_content():
    """honest_caveat mentions ATmega and STM32."""
    cfg = _cfg()
    report = check_uart_baud_drift(cfg, 9600)
    caveat = report.honest_caveat.lower()
    assert "atmega" in caveat or "avr" in caveat, (
        "honest_caveat should mention ATmega or AVR"
    )
    assert "stm32" in caveat, "honest_caveat should mention STM32"
    assert "2" in caveat, "honest_caveat should reference the 2% tolerance threshold"


# ─────────────────────────────────────────────────────────────────────────────
# U15 — LLM tool: valid round-trip, reliable=True
# ─────────────────────────────────────────────────────────────────────────────

def test_u15_llm_tool_valid_reliable():
    """LLM tool: 16 MHz / UBRR=103 / target 9600 → JSON with reliable=True."""
    result = run_firmware_check_uart_baud_drift(_tool_args(
        clock=16_000_000, ubrr=103, target=9600
    ))
    data = json.loads(result)
    assert "error" not in data, f"Unexpected error: {data}"
    assert data["reliable"] is True
    assert abs(data["actual_baud"] - 9615.0) < 1.0
    assert abs(data["drift_pct"] - 0.16) < 0.02


# ─────────────────────────────────────────────────────────────────────────────
# U16 — LLM tool: 115200 UBRR=8 → reliable=False
# ─────────────────────────────────────────────────────────────────────────────

def test_u16_llm_tool_unreliable_flag():
    """LLM tool: 16 MHz / UBRR=8 / target 115200 → JSON with reliable=False."""
    result = run_firmware_check_uart_baud_drift(_tool_args(
        clock=16_000_000, ubrr=8, target=115200
    ))
    data = json.loads(result)
    assert "error" not in data, f"Unexpected error: {data}"
    assert data["reliable"] is False


# ─────────────────────────────────────────────────────────────────────────────
# U17-U21 — LLM tool: argument validation
# ─────────────────────────────────────────────────────────────────────────────

def test_u17_llm_tool_missing_clock():
    """LLM tool: missing mcu_clock_hz → BAD_ARGS."""
    result = run_firmware_check_uart_baud_drift({"ubrr_register_value": 103, "target_baud": 9600})
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS"


def test_u18_llm_tool_missing_ubrr():
    """LLM tool: missing ubrr_register_value → BAD_ARGS."""
    result = run_firmware_check_uart_baud_drift({"mcu_clock_hz": 16_000_000, "target_baud": 9600})
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS"


def test_u19_llm_tool_missing_target_baud():
    """LLM tool: missing target_baud → BAD_ARGS."""
    result = run_firmware_check_uart_baud_drift({"mcu_clock_hz": 16_000_000, "ubrr_register_value": 103})
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS"


def test_u20_llm_tool_invalid_mode():
    """LLM tool: invalid mode string → BAD_ARGS."""
    result = run_firmware_check_uart_baud_drift(_tool_args() | {"mode": "u4x"})
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS"


def test_u21_llm_tool_zero_clock():
    """LLM tool: mcu_clock_hz=0 → BAD_ARGS."""
    result = run_firmware_check_uart_baud_drift(_tool_args() | {"mcu_clock_hz": 0})
    data = json.loads(result)
    assert data.get("code") == "BAD_ARGS"


# ─────────────────────────────────────────────────────────────────────────────
# U22 — async wrapper
# ─────────────────────────────────────────────────────────────────────────────

def test_u22_async_wrapper_matches_sync():
    """Async wrapper returns same result as sync handler."""
    sync_result = run_firmware_check_uart_baud_drift(_tool_args(
        clock=16_000_000, ubrr=103, target=9600
    ))
    async_result = asyncio.run(
        run_firmware_check_uart_baud_drift_async(
            None,
            json.dumps(_tool_args(clock=16_000_000, ubrr=103, target=9600)).encode(),
        )
    )
    assert json.loads(sync_result) == json.loads(async_result)


# ─────────────────────────────────────────────────────────────────────────────
# U23 — drift formula verification
# ─────────────────────────────────────────────────────────────────────────────

def test_u23_drift_formula_verified():
    """drift_pct = (actual − nominal) / nominal × 100 verified numerically."""
    clock = 16_000_000
    ubrr = 103
    nominal = 9600

    cfg = _cfg(clock=clock, ubrr=ubrr)
    report = check_uart_baud_drift(cfg, nominal)

    # ATmega normal formula: actual = clock / (16 × (ubrr + 1))
    expected_actual = clock / (16 * (ubrr + 1))
    expected_drift = (expected_actual - nominal) / nominal * 100

    assert abs(report.actual_baud - expected_actual) < 1e-6
    assert abs(report.drift_pct - expected_drift) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# U24 — reliable boundary: exactly 2.0% drift is NOT reliable
# ─────────────────────────────────────────────────────────────────────────────

def test_u24_reliable_boundary_at_exactly_two_pct():
    """reliable is based on strict < 2.0%; a link with exactly 2.0% drift is unreliable."""
    # Craft a UBRR that gives exactly 2% error: actual = nominal * 1.02
    # actual = clock / (16 * (ubrr + 1))  →  ubrr + 1 = clock / (16 * actual)
    # We search for a clock/ubrr pair where drift is just at or above 2%
    # Use the known U03 result: 16 MHz, double_speed, UBRR=16 → drift≈+2.12% → unreliable
    cfg = _cfg(clock=16_000_000, ubrr=16, mode="double_speed")
    report = check_uart_baud_drift(cfg, 115200)
    assert report.drift_pct > 2.0
    assert report.reliable is False, (
        "A link with >2% drift must have reliable=False"
    )

    # Also verify a link with drift just under 2% IS reliable
    cfg_ok = _cfg(clock=16_000_000, ubrr=103, mode="normal")
    report_ok = check_uart_baud_drift(cfg_ok, 9600)
    assert abs(report_ok.drift_pct) < 2.0
    assert report_ok.reliable is True
