"""Tests for kerf_firmware.memory_map_verify + firmware_verify_memory_map LLM tool.

Coverage
--------
- memory_map_verify module: registry, aliases, unknown chip, ChipMemorySpec properties
- Valid STM32F411 layout (.text 70 KB, .data 8 KB, .bss 4 KB, _stack 4 KB) → ok=True
- FLASH_OVERFLOW — .text 600 KB on STM32F411 (512 KB Flash)
- SRAM_OVERFLOW — combined SRAM sections exceed 128 KB
- STACK_OVERFLOW_INTO_BSS — stack + data + bss > SRAM size
- VECTOR_TABLE_MISPLACED — vector table at arbitrary address
- Vector table at SRAM address (VTOR remap) — note, no violation
- Vector table at Flash start — clean, note only
- ISR_COUNT_MISMATCH — too few entries for STM32F411 (expect 78)
- ISR_COUNT_MISMATCH — too many entries
- ISR count correct for STM32F411 → no violation
- ISR count correct for STM32F407 → no violation
- STM32F407 valid layout (1 MB Flash)
- STM32F407 Flash overflow (> 1 MB)
- Multiple violations in one call
- LLM tool: valid layout, bad args, unknown chip, overflow
- LLM tool: async wrapper smoke test
"""
from __future__ import annotations

import json

import pytest

from kerf_firmware.memory_map_verify import (
    ChipMemorySpec,
    LinkerSection,
    MemoryMapReport,
    MemoryViolation,
    STM32F411_MEM,
    STM32F407_MEM,
    get_memory_spec,
    list_memory_chip_ids,
    verify_memory_layout,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def violation_kinds(report: MemoryMapReport) -> list[str]:
    return [v.kind for v in report.violations]


def stm32f411_valid_sections() -> list[LinkerSection]:
    """STM32F411 valid layout: .text 70 KB, .data 8 KB, .bss 4 KB, _stack 4 KB.

    Total Flash LMA = 70 + 8 = 78 KB (< 512 KB).
    Total SRAM      = 8 + 4 + 4 = 16 KB (< 128 KB); free = 87.5%.
    """
    return [
        LinkerSection(".text",  70 * 1024, "flash"),
        LinkerSection(".data",   8 * 1024, "sram", lma_size=8 * 1024),
        LinkerSection(".bss",    4 * 1024, "sram", lma_size=0, is_bss=True),
        LinkerSection("_stack",  4 * 1024, "sram", lma_size=0, is_stack=True),
    ]


# ─────────────────────────────────────────────────────────────────────────────
# memory_map_verify: registry + ChipMemorySpec properties
# ─────────────────────────────────────────────────────────────────────────────

class TestRegistry:
    def test_stm32f411_in_registry(self):
        spec = get_memory_spec("STM32F411")
        assert spec.chip_id == "STM32F411"

    def test_stm32f407_in_registry(self):
        spec = get_memory_spec("STM32F407")
        assert spec.chip_id == "STM32F407"

    def test_aliases_resolve(self):
        for alias in ("stm32f411ce", "stm32f411re", "stm32f411ve"):
            spec = get_memory_spec(alias)
            assert spec.chip_id == "STM32F411"
        for alias in ("stm32f407vg", "stm32f407ig"):
            spec = get_memory_spec(alias)
            assert spec.chip_id == "STM32F407"

    def test_unknown_chip_raises_key_error(self):
        with pytest.raises(KeyError, match="Unknown chip"):
            get_memory_spec("STM32F999")

    def test_list_chip_ids_returns_canonical(self):
        ids = list_memory_chip_ids()
        assert "STM32F411" in ids
        assert "STM32F407" in ids

    def test_stm32f411_flash_512kb(self):
        assert STM32F411_MEM.flash_size == 512 * 1024

    def test_stm32f411_sram_128kb(self):
        assert STM32F411_MEM.sram_size == 128 * 1024

    def test_stm32f411_flash_start(self):
        assert STM32F411_MEM.flash_start == 0x08000000

    def test_stm32f411_sram_start(self):
        assert STM32F411_MEM.sram_start == 0x20000000

    def test_stm32f411_nvic_62_irqs(self):
        # RM0383 §10: STM32F411 has 62 maskable IRQs
        assert STM32F411_MEM.nvic_irq_count == 62

    def test_stm32f411_total_vectors_78(self):
        # 16 Cortex-M system exceptions + 62 peripheral IRQs
        assert STM32F411_MEM.total_vector_entries == 78

    def test_stm32f407_flash_1mb(self):
        assert STM32F407_MEM.flash_size == 1024 * 1024

    def test_stm32f407_nvic_82_irqs(self):
        # RM0090 §10: STM32F407 has 82 maskable IRQs
        assert STM32F407_MEM.nvic_irq_count == 82

    def test_stm32f407_total_vectors_98(self):
        assert STM32F407_MEM.total_vector_entries == 98

    def test_flash_end_property(self):
        assert STM32F411_MEM.flash_end == 0x08000000 + 512 * 1024

    def test_sram_end_property(self):
        assert STM32F411_MEM.sram_end == 0x20000000 + 128 * 1024


# ─────────────────────────────────────────────────────────────────────────────
# LinkerSection validation
# ─────────────────────────────────────────────────────────────────────────────

class TestLinkerSection:
    def test_valid_flash_section(self):
        s = LinkerSection(".text", 70 * 1024, "flash")
        assert s.lma_size == 70 * 1024   # defaults to size for flash

    def test_bss_lma_defaults_zero(self):
        s = LinkerSection(".bss", 4 * 1024, "sram", is_bss=True)
        assert s.lma_size == 0

    def test_stack_lma_defaults_zero(self):
        s = LinkerSection("_stack", 4 * 1024, "sram", is_stack=True)
        assert s.lma_size == 0

    def test_invalid_region_raises(self):
        with pytest.raises(ValueError, match="region"):
            LinkerSection(".text", 1024, "invalid_region")


# ─────────────────────────────────────────────────────────────────────────────
# verify_memory_layout: valid layout (depth-bar scenario)
# ─────────────────────────────────────────────────────────────────────────────

class TestValidLayout:
    def test_stm32f411_valid_ok(self):
        report = verify_memory_layout("STM32F411", stm32f411_valid_sections())
        assert report.ok is True
        assert len(report.violations) == 0

    def test_stm32f411_flash_used_78kb(self):
        report = verify_memory_layout("STM32F411", stm32f411_valid_sections())
        assert report.flash_used == 78 * 1024

    def test_stm32f411_sram_used_16kb(self):
        report = verify_memory_layout("STM32F411", stm32f411_valid_sections())
        assert report.sram_used == 16 * 1024

    def test_stm32f411_sram_free_87_5_pct(self):
        report = verify_memory_layout("STM32F411", stm32f411_valid_sections())
        assert abs(report.sram_free_pct - 87.5) < 0.1

    def test_stm32f411_chip_id(self):
        report = verify_memory_layout("STM32F411", stm32f411_valid_sections())
        assert report.chip == "STM32F411"

    def test_report_has_notes(self):
        report = verify_memory_layout("STM32F411", stm32f411_valid_sections())
        assert len(report.notes) > 0

    def test_accepts_chip_spec_object(self):
        report = verify_memory_layout(STM32F411_MEM, stm32f411_valid_sections())
        assert report.ok is True


# ─────────────────────────────────────────────────────────────────────────────
# FLASH_OVERFLOW
# ─────────────────────────────────────────────────────────────────────────────

class TestFlashOverflow:
    def test_600kb_text_overflows_stm32f411(self):
        sections = [
            LinkerSection(".text", 600 * 1024, "flash"),
            LinkerSection(".data",   8 * 1024, "sram", lma_size=8 * 1024),
            LinkerSection(".bss",    4 * 1024, "sram", lma_size=0, is_bss=True),
        ]
        report = verify_memory_layout("STM32F411", sections)
        assert report.ok is False
        assert "FLASH_OVERFLOW" in violation_kinds(report)

    def test_overflow_used_bytes_correct(self):
        sections = [LinkerSection(".text", 600 * 1024, "flash")]
        report = verify_memory_layout("STM32F411", sections)
        v = next(v for v in report.violations if v.kind == "FLASH_OVERFLOW")
        assert v.used_bytes == 600 * 1024

    def test_overflow_available_bytes_512kb(self):
        sections = [LinkerSection(".text", 600 * 1024, "flash")]
        report = verify_memory_layout("STM32F411", sections)
        v = next(v for v in report.violations if v.kind == "FLASH_OVERFLOW")
        assert v.available_bytes == 512 * 1024

    def test_exactly_at_limit_no_overflow(self):
        sections = [LinkerSection(".text", 512 * 1024, "flash")]
        report = verify_memory_layout("STM32F411", sections)
        assert "FLASH_OVERFLOW" not in violation_kinds(report)

    def test_one_byte_over_limit(self):
        sections = [LinkerSection(".text", 512 * 1024 + 1, "flash")]
        report = verify_memory_layout("STM32F411", sections)
        assert "FLASH_OVERFLOW" in violation_kinds(report)

    def test_stm32f407_1mb_ok(self):
        sections = [LinkerSection(".text", 512 * 1024, "flash")]
        report = verify_memory_layout("STM32F407", sections)
        assert "FLASH_OVERFLOW" not in violation_kinds(report)

    def test_stm32f407_overflow_above_1mb(self):
        sections = [LinkerSection(".text", 1025 * 1024, "flash")]
        report = verify_memory_layout("STM32F407", sections)
        assert "FLASH_OVERFLOW" in violation_kinds(report)


# ─────────────────────────────────────────────────────────────────────────────
# SRAM_OVERFLOW
# ─────────────────────────────────────────────────────────────────────────────

class TestSramOverflow:
    def test_overflow_sram_128kb_plus_1(self):
        sections = [
            LinkerSection(".data",   64 * 1024, "sram", lma_size=64 * 1024),
            LinkerSection(".bss",    64 * 1024, "sram", lma_size=0, is_bss=True),
            LinkerSection("_stack",  1024,      "sram", lma_size=0, is_stack=True),
        ]
        report = verify_memory_layout("STM32F411", sections)
        assert "SRAM_OVERFLOW" in violation_kinds(report)

    def test_exactly_at_limit_no_sram_overflow(self):
        sections = [
            LinkerSection(".data", 128 * 1024, "sram", lma_size=128 * 1024),
        ]
        report = verify_memory_layout("STM32F411", sections)
        assert "SRAM_OVERFLOW" not in violation_kinds(report)


# ─────────────────────────────────────────────────────────────────────────────
# STACK_OVERFLOW_INTO_BSS
# ─────────────────────────────────────────────────────────────────────────────

class TestStackOverflowIntoBss:
    def test_stack_overflows_into_bss(self):
        # data=4KB, bss=60KB, stack=70KB → total=134KB > 128KB SRAM
        # remaining_for_stack = 128 - 4 - 60 = 64 KB; stack 70 KB > 64 KB
        sections = [
            LinkerSection(".data",   4 * 1024, "sram", lma_size=4 * 1024),
            LinkerSection(".bss",   60 * 1024, "sram", lma_size=0, is_bss=True),
            LinkerSection("_stack", 70 * 1024, "sram", lma_size=0, is_stack=True),
        ]
        report = verify_memory_layout("STM32F411", sections)
        assert "STACK_OVERFLOW_INTO_BSS" in violation_kinds(report)

    def test_valid_stack_no_overflow_into_bss(self):
        # data=4KB, bss=4KB, stack=4KB → total=12KB, SRAM=128KB
        sections = stm32f411_valid_sections()
        report = verify_memory_layout("STM32F411", sections)
        assert "STACK_OVERFLOW_INTO_BSS" not in violation_kinds(report)

    def test_no_bss_no_stack_overflow_check(self):
        # No bss section → check skipped even if stack is large
        sections = [
            LinkerSection(".data",   4 * 1024, "sram", lma_size=4 * 1024),
            LinkerSection("_stack", 120 * 1024, "sram", lma_size=0, is_stack=True),
        ]
        report = verify_memory_layout("STM32F411", sections)
        assert "STACK_OVERFLOW_INTO_BSS" not in violation_kinds(report)


# ─────────────────────────────────────────────────────────────────────────────
# VECTOR_TABLE_MISPLACED
# ─────────────────────────────────────────────────────────────────────────────

class TestVectorTableMisplaced:
    def test_arbitrary_address_flagged(self):
        report = verify_memory_layout(
            "STM32F411", stm32f411_valid_sections(),
            vector_table_addr=0x10000000,  # neither Flash nor SRAM
        )
        assert "VECTOR_TABLE_MISPLACED" in violation_kinds(report)

    def test_flash_start_no_violation(self):
        report = verify_memory_layout(
            "STM32F411", stm32f411_valid_sections(),
            vector_table_addr=0x08000000,
        )
        assert "VECTOR_TABLE_MISPLACED" not in violation_kinds(report)

    def test_sram_vtor_remap_no_violation(self):
        # VTOR remap to SRAM is valid (note generated, not violation)
        report = verify_memory_layout(
            "STM32F411", stm32f411_valid_sections(),
            vector_table_addr=0x20000000,
        )
        assert "VECTOR_TABLE_MISPLACED" not in violation_kinds(report)

    def test_sram_vtor_note_generated(self):
        report = verify_memory_layout(
            "STM32F411", stm32f411_valid_sections(),
            vector_table_addr=0x20001000,
        )
        assert any("VTOR" in n for n in report.notes)

    def test_no_vector_addr_no_violation(self):
        report = verify_memory_layout(
            "STM32F411", stm32f411_valid_sections(),
        )
        assert "VECTOR_TABLE_MISPLACED" not in violation_kinds(report)


# ─────────────────────────────────────────────────────────────────────────────
# ISR_COUNT_MISMATCH
# ─────────────────────────────────────────────────────────────────────────────

class TestIsrCountMismatch:
    def test_correct_count_stm32f411_78(self):
        report = verify_memory_layout(
            "STM32F411", stm32f411_valid_sections(),
            isr_vector_count=78,
        )
        assert "ISR_COUNT_MISMATCH" not in violation_kinds(report)

    def test_too_few_entries_flagged(self):
        report = verify_memory_layout(
            "STM32F411", stm32f411_valid_sections(),
            isr_vector_count=50,
        )
        assert "ISR_COUNT_MISMATCH" in violation_kinds(report)

    def test_too_many_entries_flagged(self):
        report = verify_memory_layout(
            "STM32F411", stm32f411_valid_sections(),
            isr_vector_count=100,
        )
        assert "ISR_COUNT_MISMATCH" in violation_kinds(report)

    def test_correct_count_stm32f407_98(self):
        sections = [
            LinkerSection(".text", 70 * 1024, "flash"),
            LinkerSection(".data",  8 * 1024, "sram", lma_size=8 * 1024),
            LinkerSection(".bss",   4 * 1024, "sram", lma_size=0, is_bss=True),
        ]
        report = verify_memory_layout(
            "STM32F407", sections,
            isr_vector_count=98,
        )
        assert "ISR_COUNT_MISMATCH" not in violation_kinds(report)

    def test_mismatch_detail_mentions_expected(self):
        report = verify_memory_layout(
            "STM32F411", stm32f411_valid_sections(),
            isr_vector_count=50,
        )
        v = next(v for v in report.violations if v.kind == "ISR_COUNT_MISMATCH")
        assert "78" in v.detail  # STM32F411 expects 78 entries


# ─────────────────────────────────────────────────────────────────────────────
# as_dict serialisation
# ─────────────────────────────────────────────────────────────────────────────

class TestAsDictSerialisation:
    def test_valid_report_serialisable(self):
        report = verify_memory_layout("STM32F411", stm32f411_valid_sections())
        d = report.as_dict()
        assert d["ok"] is True
        assert d["chip"] == "STM32F411"
        assert d["flash_free_pct"] > 0
        assert d["sram_free_pct"] > 0
        assert d["violations"] == []

    def test_violation_serialisable(self):
        sections = [LinkerSection(".text", 600 * 1024, "flash")]
        report = verify_memory_layout("STM32F411", sections)
        d = report.as_dict()
        assert d["ok"] is False
        assert len(d["violations"]) > 0
        v = d["violations"][0]
        assert "kind" in v
        assert "detail" in v
        assert "suggestion" in v


# ─────────────────────────────────────────────────────────────────────────────
# LLM tool
# ─────────────────────────────────────────────────────────────────────────────

class TestLlmTool:
    def _invoke(self, payload: dict) -> dict:
        from kerf_firmware.tools.firmware_verify_memory_map import run_firmware_verify_memory_map
        result = run_firmware_verify_memory_map(payload)
        return json.loads(result)

    def test_valid_layout_ok(self):
        result = self._invoke({
            "chip": "STM32F411",
            "sections": [
                {"name": ".text",  "size": 70 * 1024, "region": "flash"},
                {"name": ".data",  "size": 8 * 1024,  "region": "sram", "lma_size": 8 * 1024},
                {"name": ".bss",   "size": 4 * 1024,  "region": "sram", "lma_size": 0, "is_bss": True},
                {"name": "_stack", "size": 4 * 1024,  "region": "sram", "lma_size": 0, "is_stack": True},
            ],
        })
        assert result.get("ok") is True
        assert result.get("violations") == []

    def test_flash_overflow_detected(self):
        result = self._invoke({
            "chip": "STM32F411",
            "sections": [
                {"name": ".text", "size": 600 * 1024, "region": "flash"},
            ],
        })
        assert result.get("ok") is False
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "FLASH_OVERFLOW" in kinds

    def test_isr_count_mismatch_via_tool(self):
        result = self._invoke({
            "chip": "STM32F411",
            "sections": [
                {"name": ".text", "size": 70 * 1024, "region": "flash"},
            ],
            "isr_vector_count": 50,
        })
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "ISR_COUNT_MISMATCH" in kinds

    def test_missing_chip_returns_error(self):
        result = self._invoke({
            "sections": [
                {"name": ".text", "size": 1024, "region": "flash"},
            ],
        })
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_missing_sections_returns_error(self):
        result = self._invoke({"chip": "STM32F411"})
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_unknown_chip_returns_error(self):
        result = self._invoke({
            "chip": "STM32F999",
            "sections": [{"name": ".text", "size": 1024, "region": "flash"}],
        })
        assert "error" in result
        assert result.get("code") == "UNKNOWN_CHIP"

    def test_invalid_region_returns_error(self):
        result = self._invoke({
            "chip": "STM32F411",
            "sections": [{"name": ".text", "size": 1024, "region": "bad_region"}],
        })
        assert "error" in result

    def test_sections_not_array_returns_error(self):
        result = self._invoke({
            "chip": "STM32F411",
            "sections": "not-an-array",
        })
        assert "error" in result
        assert result.get("code") == "BAD_ARGS"

    def test_vector_table_misplaced_via_tool(self):
        result = self._invoke({
            "chip": "STM32F411",
            "sections": [{"name": ".text", "size": 70 * 1024, "region": "flash"}],
            "vector_table_addr": 0x10000000,
        })
        kinds = [v["kind"] for v in result.get("violations", [])]
        assert "VECTOR_TABLE_MISPLACED" in kinds

    def test_stm32f407_valid(self):
        result = self._invoke({
            "chip": "STM32F407",
            "sections": [
                {"name": ".text", "size": 512 * 1024, "region": "flash"},
                {"name": ".data", "size": 8 * 1024,   "region": "sram", "lma_size": 8 * 1024},
            ],
        })
        assert result.get("ok") is True


class TestLlmToolAsync:
    def test_async_wrapper_smoke(self):
        import asyncio
        from kerf_firmware.tools.firmware_verify_memory_map import run_firmware_verify_memory_map_async

        payload = json.dumps({
            "chip": "STM32F411",
            "sections": [
                {"name": ".text",  "size": 70 * 1024, "region": "flash"},
                {"name": ".data",  "size": 8 * 1024,  "region": "sram", "lma_size": 8 * 1024},
                {"name": ".bss",   "size": 4 * 1024,  "region": "sram", "lma_size": 0, "is_bss": True},
                {"name": "_stack", "size": 4 * 1024,  "region": "sram", "lma_size": 0, "is_stack": True},
            ],
        }).encode()

        result = asyncio.run(
            run_firmware_verify_memory_map_async(None, payload)
        )
        d = json.loads(result)
        assert d.get("ok") is True

    def test_async_invalid_json(self):
        import asyncio
        from kerf_firmware.tools.firmware_verify_memory_map import run_firmware_verify_memory_map_async

        result = asyncio.run(
            run_firmware_verify_memory_map_async(None, b"not-json")
        )
        d = json.loads(result)
        assert "error" in d
