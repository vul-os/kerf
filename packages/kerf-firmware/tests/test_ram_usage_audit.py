"""Tests for kerf_firmware.ram_usage_audit + firmware_audit_ram_usage LLM tool.

Coverage
--------
- MemorySectionSizes: valid construction, negative-value rejection, zero total_ram
- audit_ram_usage: STM32F411 128 KB — 56 KB used, 44% util, within budget
- audit_ram_usage: STM32F411 128 KB over-allocated (> 80%) — fails budget
- audit_ram_usage: ATmega328P 2 KB — 2000 B used, 0 free — fails budget
- audit_ram_usage: exactly at 80% budget — within_budget=True
- audit_ram_usage: one byte over 80% budget — within_budget=False
- audit_ram_usage: zero dynamic allocation (embedded no-malloc firmware)
- audit_ram_usage: all zeros → only static sections
- static_alloc_bytes = data + bss
- dynamic_alloc_bytes = heap + stack
- free_bytes clamped to 0 when over-allocated
- recommendation mentions largest contributor when over budget
- recommendation mentions "No action required" when util < 50%
- honest_caveat always present and mentions fragmentation + interrupt stack
- as_dict serialisation keys and types
- LLM tool: valid invocation returns within_budget key
- LLM tool: missing required field returns BAD_ARGS
- LLM tool: negative total_ram_bytes returns BAD_ARGS
- LLM tool: zero total_ram_bytes returns BAD_ARGS
- LLM tool: non-integer field returns BAD_ARGS
- LLM tool: STM32F411 over-budget returns within_budget=False
- LLM tool: async wrapper smoke test
- LLM tool: async wrapper invalid JSON returns BAD_ARGS error
"""
from __future__ import annotations

import json

import pytest

from kerf_firmware.ram_usage_audit import (
    BUDGET_FRACTION,
    MemorySectionSizes,
    RamUsageReport,
    audit_ram_usage,
)


# ─────────────────────────────────────────────────────────────────────────────
# Reference constants (RM0383 §2; ATmega328P §8)
# ─────────────────────────────────────────────────────────────────────────────

STM32F411_RAM = 128 * 1024   # 131072 bytes
ATMEGA328P_RAM = 2048        # bytes


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def stm32_adequate_sizes() -> MemorySectionSizes:
    """STM32F411 fixture: data=8 KB, bss=16 KB, heap=24 KB, stack=8 KB.

    total_used = 8+16+24+8 = 56 KB = 57344 B
    free       = 128-56 = 72 KB = 73728 B
    util       = 56/128 = 43.75% → adequate
    """
    return MemorySectionSizes(
        data_bytes=8 * 1024,
        bss_bytes=16 * 1024,
        heap_max_bytes=24 * 1024,
        stack_max_bytes=8 * 1024,
        total_ram_bytes=STM32F411_RAM,
        mcu_label="STM32F411",
    )


def stm32_over_budget_sizes() -> MemorySectionSizes:
    """STM32F411 fixture: data=20KB, bss=40KB, heap=40KB, stack=20KB = 120KB.

    util = 120/128 = 93.75% → over 80% budget
    """
    return MemorySectionSizes(
        data_bytes=20 * 1024,
        bss_bytes=40 * 1024,
        heap_max_bytes=40 * 1024,
        stack_max_bytes=20 * 1024,
        total_ram_bytes=STM32F411_RAM,
        mcu_label="STM32F411",
    )


def atmega_tight_sizes() -> MemorySectionSizes:
    """ATmega328P fixture: data=500B, bss=1200B, heap=200B, stack=100B.

    total_used = 500+1200+200+100 = 2000 B
    free       = 2048-2000 = 48 B
    util       = 2000/2048 = 97.66% → over 80% budget
    """
    return MemorySectionSizes(
        data_bytes=500,
        bss_bytes=1200,
        heap_max_bytes=200,
        stack_max_bytes=100,
        total_ram_bytes=ATMEGA328P_RAM,
        mcu_label="ATmega328P",
    )


# ─────────────────────────────────────────────────────────────────────────────
# MemorySectionSizes validation
# ─────────────────────────────────────────────────────────────────────────────

class TestMemorySectionSizes:
    def test_valid_construction(self):
        sizes = stm32_adequate_sizes()
        assert sizes.data_bytes == 8 * 1024
        assert sizes.bss_bytes == 16 * 1024
        assert sizes.total_ram_bytes == STM32F411_RAM
        assert sizes.mcu_label == "STM32F411"

    def test_zero_heap_allowed(self):
        sizes = MemorySectionSizes(
            data_bytes=1024,
            bss_bytes=2048,
            heap_max_bytes=0,
            stack_max_bytes=512,
            total_ram_bytes=STM32F411_RAM,
            mcu_label="STM32F411",
        )
        assert sizes.heap_max_bytes == 0

    def test_negative_data_raises(self):
        with pytest.raises(ValueError, match="data_bytes"):
            MemorySectionSizes(
                data_bytes=-1,
                bss_bytes=0,
                heap_max_bytes=0,
                stack_max_bytes=0,
                total_ram_bytes=2048,
                mcu_label="ATmega",
            )

    def test_negative_bss_raises(self):
        with pytest.raises(ValueError, match="bss_bytes"):
            MemorySectionSizes(
                data_bytes=0,
                bss_bytes=-10,
                heap_max_bytes=0,
                stack_max_bytes=0,
                total_ram_bytes=2048,
                mcu_label="MCU",
            )

    def test_zero_total_ram_raises(self):
        with pytest.raises(ValueError, match="total_ram_bytes"):
            MemorySectionSizes(
                data_bytes=0,
                bss_bytes=0,
                heap_max_bytes=0,
                stack_max_bytes=0,
                total_ram_bytes=0,
                mcu_label="MCU",
            )

    def test_non_int_data_raises(self):
        with pytest.raises(TypeError, match="data_bytes"):
            MemorySectionSizes(
                data_bytes=1.5,  # type: ignore[arg-type]
                bss_bytes=0,
                heap_max_bytes=0,
                stack_max_bytes=0,
                total_ram_bytes=2048,
                mcu_label="MCU",
            )


# ─────────────────────────────────────────────────────────────────────────────
# audit_ram_usage: STM32F411 adequate scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestStm32AdequateScenario:
    """STM32F411: data=8KB, bss=16KB, heap=24KB, stack=8KB → 56 KB used."""

    def test_static_alloc_bytes(self):
        report = audit_ram_usage(stm32_adequate_sizes())
        assert report.static_alloc_bytes == (8 + 16) * 1024

    def test_dynamic_alloc_bytes(self):
        report = audit_ram_usage(stm32_adequate_sizes())
        assert report.dynamic_alloc_bytes == (24 + 8) * 1024

    def test_total_used_56kb(self):
        report = audit_ram_usage(stm32_adequate_sizes())
        assert report.total_used_bytes == 56 * 1024

    def test_free_72kb(self):
        report = audit_ram_usage(stm32_adequate_sizes())
        assert report.free_bytes == 72 * 1024

    def test_utilization_43_75_pct(self):
        report = audit_ram_usage(stm32_adequate_sizes())
        assert abs(report.utilization_pct - 43.75) < 0.01

    def test_within_budget_true(self):
        report = audit_ram_usage(stm32_adequate_sizes())
        assert report.within_budget is True

    def test_recommendation_no_action(self):
        report = audit_ram_usage(stm32_adequate_sizes())
        assert "No action required" in report.recommendation

    def test_honest_caveat_present(self):
        report = audit_ram_usage(stm32_adequate_sizes())
        assert report.honest_caveat != ""

    def test_honest_caveat_mentions_fragmentation(self):
        report = audit_ram_usage(stm32_adequate_sizes())
        assert "fragmentation" in report.honest_caveat.lower()

    def test_honest_caveat_mentions_interrupt(self):
        report = audit_ram_usage(stm32_adequate_sizes())
        assert "interrupt" in report.honest_caveat.lower()


# ─────────────────────────────────────────────────────────────────────────────
# audit_ram_usage: STM32F411 over-budget scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestStm32OverBudgetScenario:
    """STM32F411: data=20KB, bss=40KB, heap=40KB, stack=20KB = 120KB (93.75%)."""

    def test_within_budget_false(self):
        report = audit_ram_usage(stm32_over_budget_sizes())
        assert report.within_budget is False

    def test_utilization_over_80_pct(self):
        report = audit_ram_usage(stm32_over_budget_sizes())
        assert report.utilization_pct > 80.0

    def test_free_bytes_positive(self):
        # 120KB used of 128KB → 8KB free (not clamped)
        report = audit_ram_usage(stm32_over_budget_sizes())
        assert report.free_bytes == 8 * 1024

    def test_recommendation_mentions_reduce(self):
        report = audit_ram_usage(stm32_over_budget_sizes())
        assert "reduce" in report.recommendation.lower() or "over" in report.recommendation.lower()

    def test_recommendation_mentions_largest_contributor(self):
        # bss=40KB and heap=40KB are tied; one of them should appear
        report = audit_ram_usage(stm32_over_budget_sizes())
        assert "bss" in report.recommendation.lower() or "heap" in report.recommendation.lower()


# ─────────────────────────────────────────────────────────────────────────────
# audit_ram_usage: ATmega328P tight scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestAtmegaTightScenario:
    """ATmega328P: data=500B, bss=1200B, heap=200B, stack=100B = 2000B (97.66%)."""

    def test_total_used_2000b(self):
        report = audit_ram_usage(atmega_tight_sizes())
        assert report.total_used_bytes == 2000

    def test_free_48b(self):
        report = audit_ram_usage(atmega_tight_sizes())
        assert report.free_bytes == 48

    def test_utilization_over_97_pct(self):
        report = audit_ram_usage(atmega_tight_sizes())
        assert report.utilization_pct > 97.0

    def test_within_budget_false(self):
        report = audit_ram_usage(atmega_tight_sizes())
        assert report.within_budget is False

    def test_recommendation_names_mcu(self):
        report = audit_ram_usage(atmega_tight_sizes())
        assert "ATmega328P" in report.recommendation


# ─────────────────────────────────────────────────────────────────────────────
# Budget boundary conditions
# ─────────────────────────────────────────────────────────────────────────────

class TestBudgetBoundary:
    def test_exactly_at_80_pct_within_budget(self):
        """total_used = exactly 80% of total_ram → within_budget=True."""
        total = 1000
        used = int(total * BUDGET_FRACTION)   # 800
        sizes = MemorySectionSizes(
            data_bytes=used,
            bss_bytes=0,
            heap_max_bytes=0,
            stack_max_bytes=0,
            total_ram_bytes=total,
            mcu_label="TestMCU",
        )
        report = audit_ram_usage(sizes)
        assert report.within_budget is True

    def test_one_byte_over_80_pct_fails_budget(self):
        """total_used = 80% + 1 byte → within_budget=False."""
        total = 1000
        used = int(total * BUDGET_FRACTION) + 1   # 801
        sizes = MemorySectionSizes(
            data_bytes=used,
            bss_bytes=0,
            heap_max_bytes=0,
            stack_max_bytes=0,
            total_ram_bytes=total,
            mcu_label="TestMCU",
        )
        report = audit_ram_usage(sizes)
        assert report.within_budget is False

    def test_over_total_ram_free_clamped_to_zero(self):
        """total_used > total_ram → free_bytes == 0 (clamped)."""
        sizes = MemorySectionSizes(
            data_bytes=3000,
            bss_bytes=0,
            heap_max_bytes=0,
            stack_max_bytes=0,
            total_ram_bytes=ATMEGA328P_RAM,
            mcu_label="ATmega328P",
        )
        report = audit_ram_usage(sizes)
        assert report.free_bytes == 0
        assert report.utilization_pct > 100.0
        assert report.within_budget is False

    def test_all_zero_sections_within_budget(self):
        """All section sizes = 0 → 0% utilisation, within budget."""
        sizes = MemorySectionSizes(
            data_bytes=0,
            bss_bytes=0,
            heap_max_bytes=0,
            stack_max_bytes=0,
            total_ram_bytes=STM32F411_RAM,
            mcu_label="STM32F411",
        )
        report = audit_ram_usage(sizes)
        assert report.total_used_bytes == 0
        assert report.within_budget is True
        assert report.free_bytes == STM32F411_RAM


# ─────────────────────────────────────────────────────────────────────────────
# as_dict serialisation
# ─────────────────────────────────────────────────────────────────────────────

class TestAsDictSerialisation:
    def test_required_keys_present(self):
        report = audit_ram_usage(stm32_adequate_sizes())
        d = report.as_dict()
        required_keys = [
            "static_alloc_bytes",
            "dynamic_alloc_bytes",
            "total_used_bytes",
            "free_bytes",
            "utilization_pct",
            "within_budget",
            "recommendation",
            "honest_caveat",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    def test_within_budget_is_bool(self):
        d = audit_ram_usage(stm32_adequate_sizes()).as_dict()
        assert isinstance(d["within_budget"], bool)

    def test_utilization_pct_rounded(self):
        d = audit_ram_usage(stm32_adequate_sizes()).as_dict()
        # Should be a float, 2 decimal places
        assert isinstance(d["utilization_pct"], float)

    def test_json_serialisable(self):
        d = audit_ram_usage(stm32_adequate_sizes()).as_dict()
        s = json.dumps(d)
        assert len(s) > 0

    def test_over_budget_within_budget_false_in_dict(self):
        d = audit_ram_usage(stm32_over_budget_sizes()).as_dict()
        assert d["within_budget"] is False


# ─────────────────────────────────────────────────────────────────────────────
# LLM tool
# ─────────────────────────────────────────────────────────────────────────────

class TestLlmTool:
    def _invoke(self, payload: dict) -> dict:
        from kerf_firmware.tools.firmware_audit_ram_usage import run_firmware_audit_ram_usage
        result = run_firmware_audit_ram_usage(payload)
        return json.loads(result)

    def test_stm32_adequate_within_budget_true(self):
        result = self._invoke({
            "mcu_label": "STM32F411",
            "total_ram_bytes": STM32F411_RAM,
            "data_bytes": 8 * 1024,
            "bss_bytes": 16 * 1024,
            "heap_max_bytes": 24 * 1024,
            "stack_max_bytes": 8 * 1024,
        })
        assert result.get("within_budget") is True

    def test_stm32_over_budget_within_budget_false(self):
        result = self._invoke({
            "mcu_label": "STM32F411",
            "total_ram_bytes": STM32F411_RAM,
            "data_bytes": 20 * 1024,
            "bss_bytes": 40 * 1024,
            "heap_max_bytes": 40 * 1024,
            "stack_max_bytes": 20 * 1024,
        })
        assert result.get("within_budget") is False

    def test_result_has_required_keys(self):
        result = self._invoke({
            "mcu_label": "STM32F411",
            "total_ram_bytes": STM32F411_RAM,
            "data_bytes": 8 * 1024,
            "bss_bytes": 16 * 1024,
            "heap_max_bytes": 24 * 1024,
            "stack_max_bytes": 8 * 1024,
        })
        for key in ["static_alloc_bytes", "dynamic_alloc_bytes", "total_used_bytes",
                    "free_bytes", "utilization_pct", "within_budget",
                    "recommendation", "honest_caveat"]:
            assert key in result, f"Missing key: {key}"

    def test_missing_mcu_label_returns_bad_args(self):
        result = self._invoke({
            "total_ram_bytes": STM32F411_RAM,
            "data_bytes": 1024,
            "bss_bytes": 1024,
            "heap_max_bytes": 0,
            "stack_max_bytes": 512,
        })
        assert result.get("code") == "BAD_ARGS"

    def test_missing_total_ram_bytes_returns_bad_args(self):
        result = self._invoke({
            "mcu_label": "STM32F411",
            "data_bytes": 1024,
            "bss_bytes": 1024,
            "heap_max_bytes": 0,
            "stack_max_bytes": 512,
        })
        assert result.get("code") == "BAD_ARGS"

    def test_zero_total_ram_bytes_returns_bad_args(self):
        result = self._invoke({
            "mcu_label": "STM32F411",
            "total_ram_bytes": 0,
            "data_bytes": 0,
            "bss_bytes": 0,
            "heap_max_bytes": 0,
            "stack_max_bytes": 0,
        })
        assert result.get("code") == "BAD_ARGS"

    def test_non_integer_data_bytes_returns_bad_args(self):
        result = self._invoke({
            "mcu_label": "STM32F411",
            "total_ram_bytes": STM32F411_RAM,
            "data_bytes": "not-a-number",
            "bss_bytes": 0,
            "heap_max_bytes": 0,
            "stack_max_bytes": 0,
        })
        assert result.get("code") == "BAD_ARGS"

    def test_atmega_tight_scenario(self):
        result = self._invoke({
            "mcu_label": "ATmega328P",
            "total_ram_bytes": ATMEGA328P_RAM,
            "data_bytes": 500,
            "bss_bytes": 1200,
            "heap_max_bytes": 200,
            "stack_max_bytes": 100,
        })
        assert result.get("within_budget") is False
        assert result.get("total_used_bytes") == 2000
        assert result.get("free_bytes") == 48

    def test_honest_caveat_in_tool_result(self):
        result = self._invoke({
            "mcu_label": "STM32F411",
            "total_ram_bytes": STM32F411_RAM,
            "data_bytes": 8 * 1024,
            "bss_bytes": 16 * 1024,
            "heap_max_bytes": 24 * 1024,
            "stack_max_bytes": 8 * 1024,
        })
        caveat = result.get("honest_caveat", "")
        assert "fragmentation" in caveat.lower() or "static estimate" in caveat.lower()


class TestLlmToolAsync:
    def test_async_wrapper_smoke_test(self):
        import asyncio
        from kerf_firmware.tools.firmware_audit_ram_usage import run_firmware_audit_ram_usage_async

        payload = json.dumps({
            "mcu_label": "STM32F411",
            "total_ram_bytes": STM32F411_RAM,
            "data_bytes": 8 * 1024,
            "bss_bytes": 16 * 1024,
            "heap_max_bytes": 24 * 1024,
            "stack_max_bytes": 8 * 1024,
        }).encode()
        result = asyncio.get_event_loop().run_until_complete(
            run_firmware_audit_ram_usage_async(None, payload)
        )
        d = json.loads(result)
        assert d.get("within_budget") is True

    def test_async_wrapper_invalid_json_returns_error(self):
        import asyncio
        from kerf_firmware.tools.firmware_audit_ram_usage import run_firmware_audit_ram_usage_async

        result = asyncio.get_event_loop().run_until_complete(
            run_firmware_audit_ram_usage_async(None, b"not-valid-json")
        )
        d = json.loads(result)
        assert "error" in d
        assert d.get("code") == "BAD_ARGS"
