"""Tests for kerf_firmware.watchdog_interval_check + LLM tool
firmware_check_watchdog_interval.

Coverage
--------
W01  STM32F411 IWDG: LSI=32 kHz, prescaler=64, reload=4095
     → timeout = 64×4096/32000×1000 = 8192 ms exactly
W02  ATmega328P WDT: 128 kHz internal RC, prescaler=128, reload=0
     → timeout = 128×1/128000×1000 = 1.0 ms
W03  ATmega 128 kHz, prescaler=128, reload=1023 (max 10-bit)
     → timeout = 128×1024/128000×1000 = 1024.0 ms
W04  Worst-case 5000 ms loop vs 8192 ms STM32 timeout:
     adequate=True? 8192 > 2×5000=10000? No: adequate=False.
     (The 8192 ms timeout does NOT cover 2×5000 ms=10000 ms minimum.)
     Headroom = 8192-5000 = 3192 ms, margin ≈ 63.84%.
W05  Worst-case 4000 ms loop vs 8192 ms timeout: adequate=True (8192 > 8000)
     margin = (8192/4000 - 1)*100 = 104.8%
W06  Worst-case 8000 ms loop vs 8192 ms timeout: adequate=False (8192 < 16000)
     recommended_reload gives 2.5× margin
W07  Recommended reload gives exactly 2.5× worst-case margin or slightly above
W08  When adequate=True, recommended_reload is None
W09  safety_margin_pct formula: (actual/worst - 1)*100
W10  WatchdogConfig validation: clock_hz <= 0 raises ValueError
W11  WatchdogConfig validation: prescaler <= 0 raises ValueError
W12  WatchdogConfig validation: reload_value < 0 raises ValueError
W13  WorstCaseLoopLatency validation: worst_case_ms <= 0 raises ValueError
W14  WatchdogIntervalReport as_dict() has all required keys
W15  honest_caveat mentions LSI accuracy caveat
W16  LLM tool: valid round-trip STM32 8192 ms + 4000 ms worst-case → adequate=True
W17  LLM tool: invalid JSON bytes → BAD_ARGS
W18  LLM tool: missing config field → BAD_ARGS
W19  LLM tool: missing latency field → BAD_ARGS
W20  LLM tool: config missing clock_hz → BAD_ARGS
W21  LLM tool: latency missing worst_case_ms → BAD_ARGS
W22  LLM tool: async wrapper matches sync handler
W23  Timeout formula: prescaler × (reload+1) / clock_hz verified
W24  Inadequate case: 8 s loop vs 8192 ms timeout → recommended_reload
     recommendation satisfies 2.5× margin when used in a new config
W25  ATmega 1.024 s timeout vs 500 ms worst-case: adequate=True
"""
from __future__ import annotations

import asyncio
import json
import math

import pytest

from kerf_firmware.watchdog_interval_check import (
    WatchdogConfig,
    WorstCaseLoopLatency,
    WatchdogIntervalReport,
    check_watchdog_interval,
)
from kerf_firmware.tools.firmware_check_watchdog_interval import (
    run_firmware_check_watchdog_interval,
    run_firmware_check_watchdog_interval_async,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _stm32_config(
    clock_hz: int = 32_000,
    prescaler: int = 64,
    reload_value: int = 4095,
    mcu_label: str = "STM32F411 IWDG",
) -> WatchdogConfig:
    return WatchdogConfig(
        clock_hz=clock_hz,
        prescaler=prescaler,
        reload_value=reload_value,
        mcu_label=mcu_label,
    )


def _latency(worst_case_ms: float = 5000.0, source: str = "manual_spec") -> WorstCaseLoopLatency:
    return WorstCaseLoopLatency(worst_case_ms=worst_case_ms, source=source)


def _tool(args: dict) -> dict:
    raw = run_firmware_check_watchdog_interval(args)
    return json.loads(raw)


def _make_tool_args(
    clock_hz: int = 32_000,
    prescaler: int = 64,
    reload_value: int = 4095,
    mcu_label: str = "STM32F411 IWDG",
    worst_case_ms: float = 4000.0,
    source: str = "manual_spec",
) -> dict:
    return {
        "config": {
            "clock_hz": clock_hz,
            "prescaler": prescaler,
            "reload_value": reload_value,
            "mcu_label": mcu_label,
        },
        "latency": {
            "worst_case_ms": worst_case_ms,
            "source": source,
        },
    }


def _expected_timeout_ms(clock_hz: int, prescaler: int, reload_value: int) -> float:
    """Independent formula: prescaler × (reload+1) / clock_hz × 1000."""
    return prescaler * (reload_value + 1) / clock_hz * 1000.0


# ─────────────────────────────────────────────────────────────────────────────
# W01  STM32F411 IWDG: LSI=32 kHz, prescaler=64, reload=4095 → 8192 ms
# ─────────────────────────────────────────────────────────────────────────────

class TestSTM32MaxReload:
    """W01 — STM32F411 IWDG at full 12-bit reload: timeout = 8192 ms."""

    def test_w01_timeout_formula(self):
        """W01a: 64 × 4096 / 32000 × 1000 = 8192.0 ms exactly."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=1000.0)
        report = check_watchdog_interval(cfg, lat)
        assert report.actual_timeout_ms == pytest.approx(8192.0, rel=1e-9)

    def test_w01_timeout_equals_independent_formula(self):
        """W01b: result matches independent formula."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=1000.0)
        report = check_watchdog_interval(cfg, lat)
        expected = _expected_timeout_ms(32_000, 64, 4095)
        assert report.actual_timeout_ms == pytest.approx(expected, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# W02  ATmega 128 kHz, prescaler=128, reload=0 → 1.0 ms
# ─────────────────────────────────────────────────────────────────────────────

class TestATmegaMinReload:
    """W02 — ATmega 128 kHz internal RC, prescaler=128, reload=0 → 1.0 ms."""

    def test_w02_timeout_one_ms(self):
        """W02: 128 × 1 / 128000 × 1000 = 1.0 ms."""
        cfg = WatchdogConfig(
            clock_hz=128_000,
            prescaler=128,
            reload_value=0,
            mcu_label="ATmega328P WDT",
        )
        lat = _latency(worst_case_ms=0.1)
        report = check_watchdog_interval(cfg, lat)
        assert report.actual_timeout_ms == pytest.approx(1.0, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# W03  ATmega 128 kHz, prescaler=128, reload=1023 → 1024 ms
# ─────────────────────────────────────────────────────────────────────────────

class TestATmegaMaxReload:
    """W03 — ATmega 128 kHz, prescaler=128, reload=1023 → 1024.0 ms."""

    def test_w03_timeout_1024ms(self):
        """W03: 128 × 1024 / 128000 × 1000 = 1024.0 ms."""
        cfg = WatchdogConfig(
            clock_hz=128_000,
            prescaler=128,
            reload_value=1023,
            mcu_label="ATmega328P WDT max",
        )
        lat = _latency(worst_case_ms=100.0)
        report = check_watchdog_interval(cfg, lat)
        assert report.actual_timeout_ms == pytest.approx(1024.0, rel=1e-9)


# ─────────────────────────────────────────────────────────────────────────────
# W04  5 s worst-case vs 8192 ms timeout: adequate=False (8192 < 10000)
# ─────────────────────────────────────────────────────────────────────────────

class TestFiveSecondLoop:
    """W04 — 5000 ms worst-case vs 8192 ms timeout: 8192 < 2×5000=10000 → False."""

    def test_w04_inadequate_for_5s_loop(self):
        """W04a: 8192 ms timeout does NOT satisfy 2×5000 ms minimum."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=5000.0)
        report = check_watchdog_interval(cfg, lat)
        assert report.adequate is False

    def test_w04_headroom_positive(self):
        """W04b: headroom = 8192 - 5000 = 3192 ms (timeout > worst-case, but < 2×)."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=5000.0)
        report = check_watchdog_interval(cfg, lat)
        assert report.headroom_ms == pytest.approx(3192.0, rel=1e-6)

    def test_w04_safety_margin_approx_63pct(self):
        """W04c: margin = (8192/5000 - 1)*100 ≈ 63.84%."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=5000.0)
        report = check_watchdog_interval(cfg, lat)
        expected_pct = (8192.0 / 5000.0 - 1.0) * 100.0
        assert report.safety_margin_pct == pytest.approx(expected_pct, rel=1e-4)

    def test_w04_recommended_reload_not_none(self):
        """W04d: when inadequate, recommended_reload must be provided."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=5000.0)
        report = check_watchdog_interval(cfg, lat)
        assert report.recommended_reload is not None


# ─────────────────────────────────────────────────────────────────────────────
# W05  4 s worst-case vs 8192 ms: adequate=True (8192 > 8000)
# ─────────────────────────────────────────────────────────────────────────────

class TestFourSecondLoopAdequate:
    """W05 — 4000 ms worst-case vs 8192 ms timeout: 8192 > 2×4000=8000 → True."""

    def test_w05_adequate_for_4s_loop(self):
        """W05a: 8192 ms > 2×4000 ms = 8000 ms → adequate=True."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=4000.0)
        report = check_watchdog_interval(cfg, lat)
        assert report.adequate is True

    def test_w05_recommended_reload_is_none(self):
        """W05b: adequate=True → recommended_reload must be None."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=4000.0)
        report = check_watchdog_interval(cfg, lat)
        assert report.recommended_reload is None

    def test_w05_margin_formula(self):
        """W05c: margin = (8192/4000 - 1)*100 ≈ 104.8%."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=4000.0)
        report = check_watchdog_interval(cfg, lat)
        expected_pct = (8192.0 / 4000.0 - 1.0) * 100.0
        assert report.safety_margin_pct == pytest.approx(expected_pct, rel=1e-4)


# ─────────────────────────────────────────────────────────────────────────────
# W06  8 s worst-case vs 8192 ms: inadequate (8192 < 16000)
# ─────────────────────────────────────────────────────────────────────────────

class TestEightSecondLoopInadequate:
    """W06 — 8000 ms worst-case vs 8192 ms timeout: 8192 < 2×8000=16000 → False."""

    def test_w06_inadequate_for_8s_loop(self):
        """W06: 8192 ms < 2×8000 ms = 16000 ms → adequate=False."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=8000.0)
        report = check_watchdog_interval(cfg, lat)
        assert report.adequate is False

    def test_w06_recommended_reload_provided(self):
        """W06b: recommended_reload is not None when inadequate."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=8000.0)
        report = check_watchdog_interval(cfg, lat)
        assert report.recommended_reload is not None
        assert isinstance(report.recommended_reload, int)
        assert report.recommended_reload >= 0


# ─────────────────────────────────────────────────────────────────────────────
# W07  Recommended reload satisfies 2.5× margin
# ─────────────────────────────────────────────────────────────────────────────

class TestRecommendedReload:
    """W07 — recommended_reload produces ≥ 2.5× worst-case when applied."""

    def test_w07_recommended_reload_gives_2_5x_margin(self):
        """W07: applying recommended_reload produces timeout ≥ 2.5× worst-case."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=8000.0)
        report = check_watchdog_interval(cfg, lat)
        rec = report.recommended_reload
        assert rec is not None
        # Verify: timeout with recommended_reload ≥ 2.5 × worst_case
        rec_timeout_ms = _expected_timeout_ms(32_000, 64, rec)
        assert rec_timeout_ms >= 2.5 * lat.worst_case_ms

    def test_w07b_recommended_reload_is_minimal(self):
        """W07b: recommended_reload is the smallest value satisfying 2.5× margin."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=8000.0)
        report = check_watchdog_interval(cfg, lat)
        rec = report.recommended_reload
        assert rec is not None
        # rec-1 should NOT satisfy 2.5× margin
        if rec > 0:
            lower_timeout_ms = _expected_timeout_ms(32_000, 64, rec - 1)
            assert lower_timeout_ms < 2.5 * lat.worst_case_ms

    def test_w07c_5s_loop_recommended_reload(self):
        """W07c: 5 s inadequate case — recommended_reload gives ≥ 2.5× margin."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=5000.0)
        report = check_watchdog_interval(cfg, lat)
        rec = report.recommended_reload
        assert rec is not None
        rec_timeout_ms = _expected_timeout_ms(32_000, 64, rec)
        assert rec_timeout_ms >= 2.5 * lat.worst_case_ms


# ─────────────────────────────────────────────────────────────────────────────
# W08  Adequate → recommended_reload is None
# ─────────────────────────────────────────────────────────────────────────────

class TestAdequateNoRecommendation:
    """W08 — adequate=True → recommended_reload is None."""

    def test_w08_no_recommendation_when_adequate(self):
        """W08: when adequate, no recommended_reload is emitted."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=100.0)  # very short worst-case
        report = check_watchdog_interval(cfg, lat)
        assert report.adequate is True
        assert report.recommended_reload is None


# ─────────────────────────────────────────────────────────────────────────────
# W09  safety_margin_pct formula verification
# ─────────────────────────────────────────────────────────────────────────────

class TestSafetyMarginFormula:
    """W09 — safety_margin_pct = (actual_ms / worst_ms - 1) × 100."""

    def test_w09_margin_formula_verified(self):
        """W09: formula correct for multiple configurations."""
        for worst_ms in [100.0, 500.0, 1000.0, 4000.0, 5000.0]:
            cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
            lat = _latency(worst_case_ms=worst_ms)
            report = check_watchdog_interval(cfg, lat)
            expected = (report.actual_timeout_ms / worst_ms - 1.0) * 100.0
            assert report.safety_margin_pct == pytest.approx(expected, rel=1e-6), (
                f"Margin formula wrong for worst_ms={worst_ms}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# W10–W13  Dataclass validation
# ─────────────────────────────────────────────────────────────────────────────

class TestDataclassValidation:
    def test_w10_zero_clock_hz_raises(self):
        """W10: clock_hz=0 raises ValueError."""
        with pytest.raises(ValueError, match="clock_hz"):
            WatchdogConfig(clock_hz=0, prescaler=64, reload_value=4095, mcu_label="X")

    def test_w10b_negative_clock_hz_raises(self):
        """W10b: clock_hz < 0 raises ValueError."""
        with pytest.raises(ValueError, match="clock_hz"):
            WatchdogConfig(clock_hz=-1, prescaler=64, reload_value=4095, mcu_label="X")

    def test_w11_zero_prescaler_raises(self):
        """W11: prescaler=0 raises ValueError."""
        with pytest.raises(ValueError, match="prescaler"):
            WatchdogConfig(clock_hz=32_000, prescaler=0, reload_value=4095, mcu_label="X")

    def test_w11b_negative_prescaler_raises(self):
        """W11b: prescaler < 0 raises ValueError."""
        with pytest.raises(ValueError, match="prescaler"):
            WatchdogConfig(clock_hz=32_000, prescaler=-4, reload_value=4095, mcu_label="X")

    def test_w12_negative_reload_raises(self):
        """W12: reload_value < 0 raises ValueError."""
        with pytest.raises(ValueError, match="reload_value"):
            WatchdogConfig(clock_hz=32_000, prescaler=64, reload_value=-1, mcu_label="X")

    def test_w13_zero_worst_case_ms_raises(self):
        """W13: worst_case_ms=0 raises ValueError."""
        with pytest.raises(ValueError, match="worst_case_ms"):
            WorstCaseLoopLatency(worst_case_ms=0.0, source="manual_spec")

    def test_w13b_negative_worst_case_ms_raises(self):
        """W13b: worst_case_ms < 0 raises ValueError."""
        with pytest.raises(ValueError, match="worst_case_ms"):
            WorstCaseLoopLatency(worst_case_ms=-100.0, source="manual_spec")


# ─────────────────────────────────────────────────────────────────────────────
# W14  Report shape
# ─────────────────────────────────────────────────────────────────────────────

class TestReportShape:
    def test_w14_as_dict_has_all_required_keys(self):
        """W14: as_dict() contains all required keys."""
        cfg = _stm32_config()
        lat = _latency()
        report = check_watchdog_interval(cfg, lat)
        d = report.as_dict()
        for key in (
            "actual_timeout_ms",
            "headroom_ms",
            "safety_margin_pct",
            "adequate",
            "recommended_reload",
            "honest_caveat",
        ):
            assert key in d, f"Missing key: {key}"


# ─────────────────────────────────────────────────────────────────────────────
# W15  Caveat content
# ─────────────────────────────────────────────────────────────────────────────

class TestCaveatContent:
    def test_w15_caveat_mentions_lsi_accuracy(self):
        """W15: honest_caveat mentions LSI oscillator accuracy."""
        cfg = _stm32_config()
        lat = _latency()
        report = check_watchdog_interval(cfg, lat)
        caveat_lower = report.honest_caveat.lower()
        assert "lsi" in caveat_lower

    def test_w15b_caveat_mentions_oscillator_tolerance(self):
        """W15b: honest_caveat mentions oscillator tolerance."""
        cfg = _stm32_config()
        lat = _latency()
        report = check_watchdog_interval(cfg, lat)
        # Should mention real-world margin / oscillator tolerance
        assert "oscillator" in report.honest_caveat.lower()


# ─────────────────────────────────────────────────────────────────────────────
# W16  LLM tool valid round-trip
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMToolValid:
    def test_w16_adequate_case_round_trip(self):
        """W16: STM32 8192 ms + 4000 ms worst-case → adequate=True in JSON."""
        result = _tool(_make_tool_args(
            clock_hz=32_000, prescaler=64, reload_value=4095,
            worst_case_ms=4000.0,
        ))
        assert "actual_timeout_ms" in result
        assert "adequate" in result
        assert "recommended_reload" in result
        assert "honest_caveat" in result
        assert result["adequate"] is True
        assert result["actual_timeout_ms"] == pytest.approx(8192.0, rel=1e-6)
        assert result["recommended_reload"] is None

    def test_w16b_inadequate_case_round_trip(self):
        """W16b: 8 s worst-case → adequate=False, recommended_reload not None."""
        result = _tool(_make_tool_args(
            clock_hz=32_000, prescaler=64, reload_value=4095,
            worst_case_ms=8000.0,
        ))
        assert result["adequate"] is False
        assert result["recommended_reload"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# W17–W21  LLM tool error cases
# ─────────────────────────────────────────────────────────────────────────────

class TestLLMToolErrors:
    def test_w17_invalid_json_bytes(self):
        """W17: non-JSON bytes → BAD_ARGS via async wrapper."""
        result = json.loads(asyncio.run(
            run_firmware_check_watchdog_interval_async(None, b"not json {{")
        ))
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_w18_missing_config(self):
        """W18: missing 'config' key → BAD_ARGS."""
        result = _tool({
            "latency": {"worst_case_ms": 5000.0, "source": "manual_spec"}
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_w19_missing_latency(self):
        """W19: missing 'latency' key → BAD_ARGS."""
        result = _tool({
            "config": {
                "clock_hz": 32_000, "prescaler": 64,
                "reload_value": 4095, "mcu_label": "STM32F411 IWDG",
            }
        })
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_w20_config_missing_clock_hz(self):
        """W20: config missing clock_hz → BAD_ARGS."""
        args = _make_tool_args()
        del args["config"]["clock_hz"]
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"

    def test_w21_latency_missing_worst_case_ms(self):
        """W21: latency missing worst_case_ms → BAD_ARGS."""
        args = _make_tool_args()
        del args["latency"]["worst_case_ms"]
        result = _tool(args)
        assert "error" in result
        assert result["code"] == "BAD_ARGS"


# ─────────────────────────────────────────────────────────────────────────────
# W22  Async wrapper matches sync handler
# ─────────────────────────────────────────────────────────────────────────────

class TestAsyncWrapper:
    def test_w22_async_matches_sync(self):
        """W22: async wrapper returns same payload as sync handler."""
        args = _make_tool_args(worst_case_ms=4000.0)
        sync_result = json.loads(run_firmware_check_watchdog_interval(args))
        async_result = json.loads(asyncio.run(
            run_firmware_check_watchdog_interval_async(None, json.dumps(args).encode())
        ))
        assert sync_result["actual_timeout_ms"] == pytest.approx(
            async_result["actual_timeout_ms"], rel=1e-9
        )
        assert sync_result["adequate"] == async_result["adequate"]
        assert sync_result["recommended_reload"] == async_result["recommended_reload"]


# ─────────────────────────────────────────────────────────────────────────────
# W23  Timeout formula independent verification
# ─────────────────────────────────────────────────────────────────────────────

class TestTimeoutFormula:
    def test_w23_formula_matches_several_configs(self):
        """W23: timeout_ms = prescaler × (reload+1) / clock_hz × 1000 for many configs."""
        test_cases = [
            (32_000, 4, 0),       # STM32 min prescaler, min reload → 0.125 ms
            (32_000, 4, 4095),    # STM32 min prescaler, max reload → 512 ms
            (32_000, 256, 4095),  # STM32 max prescaler, max reload → 32768 ms
            (128_000, 128, 0),    # ATmega min reload → 1.0 ms
            (128_000, 128, 1023), # ATmega max reload → 1024.0 ms
        ]
        for clock_hz, prescaler, reload_value in test_cases:
            cfg = WatchdogConfig(
                clock_hz=clock_hz,
                prescaler=prescaler,
                reload_value=reload_value,
                mcu_label=f"test_{clock_hz}_{prescaler}_{reload_value}",
            )
            lat = _latency(worst_case_ms=0.001)  # tiny worst-case so adequate
            report = check_watchdog_interval(cfg, lat)
            expected = _expected_timeout_ms(clock_hz, prescaler, reload_value)
            assert report.actual_timeout_ms == pytest.approx(expected, rel=1e-9), (
                f"Formula wrong for clock={clock_hz}, prescaler={prescaler}, "
                f"reload={reload_value}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# W24  8 s inadequate → recommended_reload usable config
# ─────────────────────────────────────────────────────────────────────────────

class TestInadequateRecommendationUsable:
    def test_w24_recommended_reload_works_in_new_config(self):
        """W24: applying recommended_reload in new WatchdogConfig → adequate=True."""
        cfg = _stm32_config(clock_hz=32_000, prescaler=64, reload_value=4095)
        lat = _latency(worst_case_ms=8000.0)
        report = check_watchdog_interval(cfg, lat)
        rec = report.recommended_reload
        assert rec is not None
        # Build a new config with recommended reload
        new_cfg = WatchdogConfig(
            clock_hz=32_000,
            prescaler=64,
            reload_value=rec,
            mcu_label="STM32F411 IWDG (fixed)",
        )
        new_report = check_watchdog_interval(new_cfg, lat)
        assert new_report.adequate is True
        assert new_report.actual_timeout_ms >= 2.5 * lat.worst_case_ms


# ─────────────────────────────────────────────────────────────────────────────
# W25  ATmega 1.024 s timeout vs 500 ms worst-case: adequate
# ─────────────────────────────────────────────────────────────────────────────

class TestATmegaAdequate:
    def test_w25_atmega_1024ms_vs_500ms_adequate(self):
        """W25: ATmega 1024 ms timeout vs 500 ms worst-case → adequate=True."""
        cfg = WatchdogConfig(
            clock_hz=128_000,
            prescaler=128,
            reload_value=1023,
            mcu_label="ATmega328P WDT",
        )
        lat = _latency(worst_case_ms=500.0, source="manual_spec")
        report = check_watchdog_interval(cfg, lat)
        assert report.actual_timeout_ms == pytest.approx(1024.0, rel=1e-9)
        assert report.adequate is True
        assert report.recommended_reload is None

    def test_w25b_atmega_sources_handled(self):
        """W25b: all valid source values work without error."""
        for source in ("ISR_pile_up", "sd_write", "sensor_timeout", "manual_spec"):
            lat = WorstCaseLoopLatency(worst_case_ms=100.0, source=source)
            cfg = _stm32_config()
            report = check_watchdog_interval(cfg, lat)
            assert report.actual_timeout_ms > 0
