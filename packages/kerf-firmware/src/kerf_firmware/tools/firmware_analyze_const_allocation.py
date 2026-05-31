"""LLM tool: firmware_analyze_const_allocation — Flash vs RAM const-allocation analyser.

Given a parsed firmware symbol map (list of symbol entries with name, section,
and size), analyses how ``const``-qualified data is distributed across Flash
(.rodata, .text) and RAM (.data) sections.  Identifies wasteful placement of
constant arrays in .data (RAM) and recommends migration to .rodata (Flash) on
tight MCUs such as STM32F411 and ATmega328P.

HONEST CAVEAT: heuristic based on ELF section placement and symbol naming
convention (ALL_CAPS pattern) — not AST or source-level analysis.

References
----------
  GCC Internals §18 — Section Placement.
  ARM IHI 0044F AAPCS §5.4 — Data Layout.
  RM0383 Rev 3 §3 — STM32F411xC/E memory map (512 KB Flash / 128 KB SRAM).
  ATmega328P §8   — SRAM organisation; §28 — Flash self-programming.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.const_allocation import SymbolEntry, analyze_const_allocation


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_analyze_const_allocation",
    description=(
        "Analyse firmware symbol map to report Flash (.rodata, .text) vs RAM "
        "(.data initialised constants) allocation for `const`-qualified data. "
        "Helps optimise memory layout for tight MCUs (STM32F411, ATmega328P). "
        "Input: list of symbol entries (name, section, size_bytes) from GCC "
        "linker map or `arm-none-eabi-nm -S --size-sort` output. "
        "Output: total_flash_bytes, total_ram_bytes, rodata_bytes, "
        "data_init_bytes (RAM-stored constants — wasteful), "
        "suspect_data_consts (top 10 ALL_CAPS .data symbols by size — likely "
        "constants that should live in .rodata), "
        "top_rodata_consumers (top 10 .rodata symbols by size), "
        "flash_utilization_pct, ram_utilization_pct, recommendations, "
        "honest_caveat. "
        "Recommendation triggers: data_init_bytes > 1 KB → suggest "
        "`const-qualifier` / section migration; flash > 80% → suggest `-Os`. "
        "HONEST CAVEAT: heuristic based on section placement and ALL_CAPS "
        "naming convention — NOT AST or DWARF source-level analysis. "
        "References: GCC Internals §18; ARM IHI 0044F AAPCS §5.4; "
        "RM0383 Rev 3 §3 (STM32F411); ATmega328P §8."
    ),
    input_schema={
        "type": "object",
        "required": ["symbols"],
        "properties": {
            "symbols": {
                "type": "array",
                "description": (
                    "List of symbol entries from the firmware linker map. "
                    "Each entry must have: name (str), section (str), "
                    "size_bytes (int). Optionally: address_hex (str). "
                    "Recognised sections: .text, .rodata, .data, .bss, "
                    ".init_array, .ARM.exidx."
                ),
                "items": {
                    "type": "object",
                    "required": ["name", "section", "size_bytes"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Demangled symbol name, e.g. 'CRC_TABLE' or 'g_state'.",
                        },
                        "section": {
                            "type": "string",
                            "description": (
                                "ELF section: '.text', '.rodata', '.data', "
                                "'.bss', '.init_array', '.ARM.exidx'."
                            ),
                        },
                        "size_bytes": {
                            "type": "integer",
                            "description": "Symbol size in bytes (>= 0).",
                            "minimum": 0,
                        },
                        "address_hex": {
                            "type": "string",
                            "description": (
                                "Optional load address string, e.g. '0x08002c40'. "
                                "Used for diagnostics only."
                            ),
                        },
                    },
                },
                "minItems": 0,
            },
            "mcu_flash_kib": {
                "type": "integer",
                "description": (
                    "MCU Flash capacity in KiB. Default 512 (STM32F411CE, RM0383 §3). "
                    "Use 32 for ATmega328P, 1024 for STM32F407."
                ),
                "minimum": 1,
                "default": 512,
            },
            "mcu_ram_kib": {
                "type": "integer",
                "description": (
                    "MCU SRAM capacity in KiB. Default 128 (STM32F411, RM0383 §2). "
                    "Use 2 for ATmega328P."
                ),
                "minimum": 1,
                "default": 128,
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_analyze_const_allocation(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute the const-allocation analysis and return a JSON payload."""
    raw_symbols = args.get("symbols")
    if raw_symbols is None:
        return err_payload("'symbols' is required", "BAD_ARGS")
    if not isinstance(raw_symbols, list):
        return err_payload("'symbols' must be a JSON array", "BAD_ARGS")

    # Parse optional MCU params
    mcu_flash_kib = args.get("mcu_flash_kib", 512)
    mcu_ram_kib = args.get("mcu_ram_kib", 128)

    try:
        mcu_flash_kib = int(mcu_flash_kib)
        mcu_ram_kib = int(mcu_ram_kib)
    except (TypeError, ValueError) as exc:
        return err_payload(f"mcu_flash_kib / mcu_ram_kib must be integers: {exc}", "BAD_ARGS")

    if mcu_flash_kib <= 0:
        return err_payload("mcu_flash_kib must be > 0", "BAD_ARGS")
    if mcu_ram_kib <= 0:
        return err_payload("mcu_ram_kib must be > 0", "BAD_ARGS")

    # Parse symbol entries
    symbols: list[SymbolEntry] = []
    for i, entry in enumerate(raw_symbols):
        if not isinstance(entry, dict):
            return err_payload(
                f"symbols[{i}] must be an object, got {type(entry).__name__}",
                "BAD_ARGS",
            )
        name = entry.get("name")
        section = entry.get("section")
        size_bytes = entry.get("size_bytes")

        if not name or not isinstance(name, str):
            return err_payload(
                f"symbols[{i}].name must be a non-empty string", "BAD_ARGS"
            )
        if not section or not isinstance(section, str):
            return err_payload(
                f"symbols[{i}].section must be a non-empty string", "BAD_ARGS"
            )
        if size_bytes is None:
            return err_payload(
                f"symbols[{i}].size_bytes is required", "BAD_ARGS"
            )
        try:
            size_bytes = int(size_bytes)
        except (TypeError, ValueError) as exc:
            return err_payload(
                f"symbols[{i}].size_bytes must be an integer: {exc}", "BAD_ARGS"
            )
        if size_bytes < 0:
            return err_payload(
                f"symbols[{i}].size_bytes must be >= 0, got {size_bytes}", "BAD_ARGS"
            )

        address_hex = str(entry.get("address_hex", ""))
        try:
            sym = SymbolEntry(
                name=name,
                section=section,
                size_bytes=size_bytes,
                address_hex=address_hex,
            )
        except (TypeError, ValueError) as exc:
            return err_payload(f"symbols[{i}] invalid: {exc}", "BAD_ARGS")

        symbols.append(sym)

    try:
        report = analyze_const_allocation(
            symbols=symbols,
            mcu_flash_kib=mcu_flash_kib,
            mcu_ram_kib=mcu_ram_kib,
        )
    except (TypeError, ValueError) as exc:
        return err_payload(f"Analysis error: {exc}", "ANALYSIS_ERROR")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Unexpected error: {exc}", "ANALYSIS_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_analyze_const_allocation_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_analyze_const_allocation(a, ctx)
