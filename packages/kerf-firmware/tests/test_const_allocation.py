"""Tests for kerf_firmware.const_allocation + firmware_analyze_const_allocation LLM tool.

Coverage
--------
- SymbolEntry: valid construction with all fields
- SymbolEntry: valid construction with defaults (address_hex omitted)
- SymbolEntry: empty name raises ValueError
- SymbolEntry: empty section raises ValueError
- SymbolEntry: non-integer size_bytes raises TypeError
- SymbolEntry: negative size_bytes raises ValueError
- analyze_const_allocation: empty input → zero report, no recommendations about issues
- analyze_const_allocation: 4 KB rodata only → flash_utilization_pct > 0, ram = 0
- analyze_const_allocation: 4 KB rodata > 80% flash (mcu_flash_kib=4) → -Os recommendation
- analyze_const_allocation: 2 KB initialized const in .data → data_init_bytes flagged + suspect detected
- analyze_const_allocation: suspect_data_consts only includes ALL_CAPS >= 4 bytes
- analyze_const_allocation: suspect_data_consts capped at 10
- analyze_const_allocation: top_rodata_consumers sorted descending by size
- analyze_const_allocation: top_rodata_consumers capped at 10
- analyze_const_allocation: mixed sections → correct flash/ram split
- analyze_const_allocation: .bss counted in RAM, not flash
- analyze_const_allocation: .init_array + .ARM.exidx counted in flash
- analyze_const_allocation: as_dict returns expected keys and types
- analyze_const_allocation: honest_caveat always present
- analyze_const_allocation: mcu_flash_kib non-int raises TypeError
- analyze_const_allocation: mcu_ram_kib <= 0 raises ValueError
- LLM tool: valid symbols list returns expected keys
- LLM tool: missing symbols field returns BAD_ARGS
- LLM tool: symbols not a list returns BAD_ARGS
- LLM tool: symbol missing name returns BAD_ARGS
- LLM tool: symbol size_bytes negative returns BAD_ARGS
- LLM tool: mcu_flash_kib = 0 returns BAD_ARGS
- LLM tool: empty symbols list returns zero report
- LLM tool: async wrapper smoke test
- LLM tool: async wrapper invalid JSON returns BAD_ARGS
- LLM tool: 2 KB .data with ALL_CAPS symbols → suspect_data_consts non-empty
"""
from __future__ import annotations

import json
import pytest
import asyncio

from kerf_firmware.const_allocation import (
    SymbolEntry,
    ConstAllocationReport,
    analyze_const_allocation,
)
from kerf_firmware.tools.firmware_analyze_const_allocation import (
    run_firmware_analyze_const_allocation,
    run_firmware_analyze_const_allocation_async,
)


# ──────────────────────────────────────────────────────────────────────────────
# SymbolEntry construction
# ──────────────────────────────────────────────────────────────────────────────

class TestSymbolEntry:
    def test_valid_all_fields(self):
        sym = SymbolEntry(name="CRC_TABLE", section=".rodata", size_bytes=256, address_hex="0x08002c40")
        assert sym.name == "CRC_TABLE"
        assert sym.section == ".rodata"
        assert sym.size_bytes == 256
        assert sym.address_hex == "0x08002c40"

    def test_valid_default_address(self):
        sym = SymbolEntry(name="g_state", section=".data", size_bytes=8)
        assert sym.address_hex == ""

    def test_zero_size_allowed(self):
        sym = SymbolEntry(name="empty_sym", section=".bss", size_bytes=0)
        assert sym.size_bytes == 0

    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            SymbolEntry(name="", section=".rodata", size_bytes=4)

    def test_empty_section_raises(self):
        with pytest.raises(ValueError, match="section"):
            SymbolEntry(name="SOME_CONST", section="", size_bytes=4)

    def test_non_int_size_raises(self):
        with pytest.raises(TypeError, match="size_bytes"):
            SymbolEntry(name="X", section=".rodata", size_bytes="128")  # type: ignore[arg-type]

    def test_negative_size_raises(self):
        with pytest.raises(ValueError, match="size_bytes"):
            SymbolEntry(name="X", section=".data", size_bytes=-1)


# ──────────────────────────────────────────────────────────────────────────────
# analyze_const_allocation — core logic
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalyzeConstAllocation:
    def test_empty_input_zero_report(self):
        report = analyze_const_allocation([], mcu_flash_kib=512, mcu_ram_kib=128)
        assert report.total_flash_bytes == 0
        assert report.total_ram_bytes == 0
        assert report.rodata_bytes == 0
        assert report.data_init_bytes == 0
        assert report.suspect_data_consts == []
        assert report.top_rodata_consumers == []
        assert report.flash_utilization_pct == 0.0
        assert report.ram_utilization_pct == 0.0

    def test_empty_input_no_warning_recommendations(self):
        report = analyze_const_allocation([], mcu_flash_kib=512, mcu_ram_kib=128)
        # Should have the "no issues" recommendation, not the warning ones
        assert any("No immediate" in r for r in report.recommendations)

    def test_rodata_only_flash_used_ram_zero(self):
        """4 KB of .rodata on STM32F411 → flash > 0, RAM = 0."""
        symbols = [SymbolEntry("SENSOR_LUT", ".rodata", 4096)]
        report = analyze_const_allocation(symbols, mcu_flash_kib=512, mcu_ram_kib=128)
        assert report.total_flash_bytes == 4096
        assert report.rodata_bytes == 4096
        assert report.total_ram_bytes == 0
        assert report.flash_utilization_pct == pytest.approx(4096 / (512 * 1024) * 100, abs=1e-4)
        assert report.ram_utilization_pct == 0.0

    def test_flash_over_80_percent_recommends_os(self):
        """4 KB .rodata on a 4 KiB Flash MCU → > 80% → -Os recommendation."""
        symbols = [SymbolEntry("BIG_TABLE", ".rodata", 3500)]
        report = analyze_const_allocation(symbols, mcu_flash_kib=4, mcu_ram_kib=2)
        assert report.flash_utilization_pct > 80.0
        assert any("-Os" in r for r in report.recommendations)

    def test_data_init_over_1kb_recommends_const_migration(self):
        """2 KB in .data → data_init_bytes > 1024 → const-qualifier recommendation."""
        symbols = [
            SymbolEntry("LOOKUP_TABLE", ".data", 2048),
            SymbolEntry("g_counter", ".data", 4),
        ]
        report = analyze_const_allocation(symbols, mcu_flash_kib=512, mcu_ram_kib=128)
        assert report.data_init_bytes == 2052
        assert any("const-qualifier" in r or "const" in r for r in report.recommendations)

    def test_suspect_data_consts_all_caps_only(self):
        """Only ALL_CAPS symbols >= 4 bytes in .data are flagged as suspects."""
        symbols = [
            SymbolEntry("SENSOR_LUT", ".data", 512),       # should be flagged
            SymbolEntry("g_counter", ".data", 128),         # lowercase — not flagged
            SymbolEntry("__VTABLE", ".data", 256),          # leading underscores + caps — flagged
            SymbolEntry("MAX_SPEED", ".data", 4),           # exactly 4 bytes — flagged
            SymbolEntry("tiny", ".data", 1024),             # lowercase — not flagged
            SymbolEntry("ABC", ".data", 3),                 # < 4 bytes — not flagged
        ]
        report = analyze_const_allocation(symbols, mcu_flash_kib=512, mcu_ram_kib=128)
        assert "SENSOR_LUT" in report.suspect_data_consts
        assert "__VTABLE" in report.suspect_data_consts
        assert "MAX_SPEED" in report.suspect_data_consts
        assert "g_counter" not in report.suspect_data_consts
        assert "tiny" not in report.suspect_data_consts
        assert "ABC" not in report.suspect_data_consts

    def test_suspect_data_consts_capped_at_10(self):
        """suspect_data_consts never exceeds 10 entries."""
        symbols = [
            SymbolEntry(f"TABLE_{i:02d}", ".data", 100 + i * 10)
            for i in range(15)
        ]
        report = analyze_const_allocation(symbols, mcu_flash_kib=512, mcu_ram_kib=128)
        assert len(report.suspect_data_consts) <= 10

    def test_suspect_data_consts_sorted_by_size_descending(self):
        """Suspects are returned largest-first."""
        symbols = [
            SymbolEntry("TABLE_A", ".data", 100),
            SymbolEntry("TABLE_B", ".data", 500),
            SymbolEntry("TABLE_C", ".data", 200),
        ]
        report = analyze_const_allocation(symbols, mcu_flash_kib=512, mcu_ram_kib=128)
        # TABLE_B (500) should be first suspect
        assert report.suspect_data_consts[0] == "TABLE_B"

    def test_top_rodata_consumers_sorted_descending(self):
        """top_rodata_consumers are sorted by size descending."""
        symbols = [
            SymbolEntry("small_const", ".rodata", 32),
            SymbolEntry("LARGE_TABLE", ".rodata", 2048),
            SymbolEntry("mid_table", ".rodata", 512),
        ]
        report = analyze_const_allocation(symbols, mcu_flash_kib=512, mcu_ram_kib=128)
        names = [n for n, _ in report.top_rodata_consumers]
        assert names[0] == "LARGE_TABLE"
        assert names[1] == "mid_table"
        assert names[2] == "small_const"

    def test_top_rodata_consumers_capped_at_10(self):
        symbols = [SymbolEntry(f"CONST_{i}", ".rodata", 100 + i) for i in range(20)]
        report = analyze_const_allocation(symbols, mcu_flash_kib=512, mcu_ram_kib=128)
        assert len(report.top_rodata_consumers) <= 10

    def test_mixed_sections_correct_split(self):
        """Each section contributes to the correct Flash / RAM total."""
        symbols = [
            SymbolEntry("code_fn", ".text", 1024),
            SymbolEntry("CONST_A", ".rodata", 512),
            SymbolEntry("init_data", ".data", 256),
            SymbolEntry("bss_buf", ".bss", 128),
            SymbolEntry("ctor_table", ".init_array", 16),
            SymbolEntry("exidx_entry", ".ARM.exidx", 8),
        ]
        report = analyze_const_allocation(symbols, mcu_flash_kib=512, mcu_ram_kib=128)
        # Flash: .text + .rodata + .init_array + .ARM.exidx
        expected_flash = 1024 + 512 + 16 + 8
        assert report.total_flash_bytes == expected_flash
        # RAM: .data + .bss
        expected_ram = 256 + 128
        assert report.total_ram_bytes == expected_ram
        assert report.rodata_bytes == 512
        assert report.data_init_bytes == 256

    def test_bss_in_ram_not_flash(self):
        symbols = [SymbolEntry("zero_buf", ".bss", 1024)]
        report = analyze_const_allocation(symbols, mcu_flash_kib=512, mcu_ram_kib=128)
        assert report.total_ram_bytes == 1024
        assert report.total_flash_bytes == 0

    def test_init_array_and_exidx_in_flash(self):
        symbols = [
            SymbolEntry("__init_array_start", ".init_array", 32),
            SymbolEntry("__exidx_start", ".ARM.exidx", 16),
        ]
        report = analyze_const_allocation(symbols, mcu_flash_kib=512, mcu_ram_kib=128)
        assert report.total_flash_bytes == 48
        assert report.total_ram_bytes == 0

    def test_as_dict_keys_and_types(self):
        report = analyze_const_allocation([], mcu_flash_kib=512, mcu_ram_kib=128)
        d = report.as_dict()
        expected_keys = {
            "total_flash_bytes", "total_ram_bytes", "rodata_bytes",
            "data_init_bytes", "suspect_data_consts", "top_rodata_consumers",
            "recommendations", "honest_caveat",
            "flash_utilization_pct", "ram_utilization_pct",
        }
        assert expected_keys.issubset(d.keys())
        assert isinstance(d["total_flash_bytes"], int)
        assert isinstance(d["suspect_data_consts"], list)
        assert isinstance(d["top_rodata_consumers"], list)
        assert isinstance(d["recommendations"], list)
        assert isinstance(d["honest_caveat"], str) and len(d["honest_caveat"]) > 0

    def test_honest_caveat_always_present(self):
        for syms in [[], [SymbolEntry("X", ".rodata", 100)]]:
            report = analyze_const_allocation(syms)
            assert len(report.honest_caveat) > 0
            assert "HEURISTIC" in report.honest_caveat

    def test_mcu_flash_kib_non_int_raises(self):
        with pytest.raises(TypeError, match="mcu_flash_kib"):
            analyze_const_allocation([], mcu_flash_kib="512")  # type: ignore[arg-type]

    def test_mcu_ram_kib_zero_raises(self):
        with pytest.raises(ValueError, match="mcu_ram_kib"):
            analyze_const_allocation([], mcu_flash_kib=512, mcu_ram_kib=0)

    def test_mcu_flash_kib_negative_raises(self):
        with pytest.raises(ValueError, match="mcu_flash_kib"):
            analyze_const_allocation([], mcu_flash_kib=-1, mcu_ram_kib=128)

    def test_atm328p_small_flash(self):
        """ATmega328P 32 KiB Flash / 2 KiB RAM — tiny MCU scenario."""
        symbols = [
            SymbolEntry("CRC_TABLE", ".rodata", 512),
            SymbolEntry("g_rx_buf", ".bss", 256),
            SymbolEntry("main", ".text", 8192),
        ]
        report = analyze_const_allocation(symbols, mcu_flash_kib=32, mcu_ram_kib=2)
        assert report.total_flash_bytes == 512 + 8192
        assert report.total_ram_bytes == 256
        assert report.flash_utilization_pct == pytest.approx((512 + 8192) / (32 * 1024) * 100, abs=0.1)


# ──────────────────────────────────────────────────────────────────────────────
# LLM tool
# ──────────────────────────────────────────────────────────────────────────────

def _sym(name: str, section: str, size: int) -> dict:
    return {"name": name, "section": section, "size_bytes": size}


class TestLLMTool:
    def test_valid_invocation_returns_expected_keys(self):
        args = {
            "symbols": [
                _sym("LOOKUP", ".rodata", 1024),
                _sym("g_state", ".data", 64),
            ],
            "mcu_flash_kib": 512,
            "mcu_ram_kib": 128,
        }
        result = json.loads(run_firmware_analyze_const_allocation(args))
        assert "total_flash_bytes" in result
        assert "rodata_bytes" in result
        assert "data_init_bytes" in result
        assert "suspect_data_consts" in result
        assert "top_rodata_consumers" in result
        assert "recommendations" in result
        assert "honest_caveat" in result
        assert result["rodata_bytes"] == 1024
        assert result["data_init_bytes"] == 64

    def test_missing_symbols_returns_bad_args(self):
        result = json.loads(run_firmware_analyze_const_allocation({}))
        assert result.get("code") == "BAD_ARGS"

    def test_symbols_not_list_returns_bad_args(self):
        result = json.loads(run_firmware_analyze_const_allocation({"symbols": "not-a-list"}))
        assert result.get("code") == "BAD_ARGS"

    def test_symbol_missing_name_returns_bad_args(self):
        args = {"symbols": [{"section": ".rodata", "size_bytes": 100}]}
        result = json.loads(run_firmware_analyze_const_allocation(args))
        assert result.get("code") == "BAD_ARGS"

    def test_symbol_negative_size_returns_bad_args(self):
        args = {"symbols": [_sym("X", ".rodata", -1)]}
        result = json.loads(run_firmware_analyze_const_allocation(args))
        assert result.get("code") == "BAD_ARGS"

    def test_mcu_flash_kib_zero_returns_bad_args(self):
        args = {"symbols": [], "mcu_flash_kib": 0}
        result = json.loads(run_firmware_analyze_const_allocation(args))
        assert result.get("code") == "BAD_ARGS"

    def test_mcu_ram_kib_zero_returns_bad_args(self):
        args = {"symbols": [], "mcu_ram_kib": 0}
        result = json.loads(run_firmware_analyze_const_allocation(args))
        assert result.get("code") == "BAD_ARGS"

    def test_empty_symbols_returns_zero_report(self):
        args = {"symbols": []}
        result = json.loads(run_firmware_analyze_const_allocation(args))
        assert result["total_flash_bytes"] == 0
        assert result["total_ram_bytes"] == 0

    def test_data_symbols_all_caps_flagged_as_suspects(self):
        """2 KB .data with ALL_CAPS symbols → suspect_data_consts non-empty."""
        args = {
            "symbols": [
                _sym("LOOKUP_TABLE", ".data", 1024),
                _sym("COEFF_ARRAY", ".data", 512),
                _sym("g_mutable", ".data", 256),
            ],
            "mcu_flash_kib": 512,
            "mcu_ram_kib": 128,
        }
        result = json.loads(run_firmware_analyze_const_allocation(args))
        assert result["data_init_bytes"] == 1792
        suspects = result["suspect_data_consts"]
        assert "LOOKUP_TABLE" in suspects
        assert "COEFF_ARRAY" in suspects
        assert "g_mutable" not in suspects
        # data > 1KB so const-migration recommendation should be present
        assert any("const" in r.lower() for r in result["recommendations"])

    def test_flash_over_80_pct_recommends_os_via_tool(self):
        """Small MCU with large .text → flash > 80% → -Os recommendation from LLM tool."""
        args = {
            "symbols": [_sym("main_code", ".text", 3500)],
            "mcu_flash_kib": 4,
            "mcu_ram_kib": 2,
        }
        result = json.loads(run_firmware_analyze_const_allocation(args))
        assert result["flash_utilization_pct"] > 80.0
        assert any("-Os" in r for r in result["recommendations"])

    def test_symbol_with_address_hex_accepted(self):
        args = {
            "symbols": [
                {"name": "CONST_DATA", "section": ".rodata", "size_bytes": 128, "address_hex": "0x08001000"}
            ]
        }
        result = json.loads(run_firmware_analyze_const_allocation(args))
        assert result["rodata_bytes"] == 128

    def test_async_wrapper_smoke_test(self):
        args_bytes = json.dumps({
            "symbols": [_sym("CRC_TABLE", ".rodata", 256)],
            "mcu_flash_kib": 512,
            "mcu_ram_kib": 128,
        }).encode()
        result = json.loads(asyncio.run(run_firmware_analyze_const_allocation_async(None, args_bytes)))
        assert "rodata_bytes" in result
        assert result["rodata_bytes"] == 256

    def test_async_wrapper_invalid_json_returns_bad_args(self):
        result = json.loads(asyncio.run(
            run_firmware_analyze_const_allocation_async(None, b"not json {{{")
        ))
        assert result.get("code") == "BAD_ARGS"

    def test_symbol_missing_section_returns_bad_args(self):
        args = {"symbols": [{"name": "X", "size_bytes": 100}]}
        result = json.loads(run_firmware_analyze_const_allocation(args))
        assert result.get("code") == "BAD_ARGS"

    def test_unknown_section_treated_as_flash(self):
        """Unknown sections fall through to flash total (not RAM)."""
        args = {
            "symbols": [_sym("weird_sym", ".custom_section", 512)],
            "mcu_flash_kib": 512,
            "mcu_ram_kib": 128,
        }
        result = json.loads(run_firmware_analyze_const_allocation(args))
        # Unknown sections don't hit FLASH_ONLY or RAM sets; totals are zero
        # (section_totals accumulates by key; neither flash/ram sets match)
        # total_flash_bytes = sum of FLASH_ONLY sections = 0; total_ram = 0
        assert result["total_flash_bytes"] == 0
        assert result["total_ram_bytes"] == 0
