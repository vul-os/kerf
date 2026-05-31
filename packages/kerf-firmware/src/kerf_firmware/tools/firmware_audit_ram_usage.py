"""LLM tool: firmware_audit_ram_usage — MCU RAM utilisation audit.

Given MCU total SRAM bytes and the four section sizes (.data, .bss, heap
estimate, stack estimate), audits RAM utilisation, reports headroom, and flags
if the firmware exceeds the 80 % budget (10 % safety margin above 70 % soft
ceiling).

References
----------
  RM0383 Rev 3 §2  — STM32F411xC/E memory map (SRAM @ 0x2000_0000, 128 KB).
  ATmega328P §8    — SRAM organisation (internal SRAM 2 KB, 0x0100–0x08FF).
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.ram_usage_audit import MemorySectionSizes, audit_ram_usage


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_audit_ram_usage",
    description=(
        "Audit firmware RAM utilisation for an MCU given linker-reported section "
        "sizes and user-supplied heap/stack estimates. "
        "Computes: static_alloc (data+bss), dynamic_alloc (heap+stack), "
        "total_used, free_bytes, utilization_pct, and within_budget (True iff "
        "total_used ≤ 80% of total_ram_bytes — 10% safety guard). "
        "Flags over-budget firmware and identifies the largest RAM contributor. "
        "Supports any MCU: supply total_ram_bytes for the target "
        "(e.g. STM32F411 = 131072, ATmega328P = 2048). "
        "HONEST CAVEAT: static estimate only — does not account for malloc "
        "fragmentation or interrupt-driven stack growth beyond declared "
        "stack_max_bytes. "
        "References: RM0383 Rev 3 §2 (STM32F411 SRAM map); ATmega328P §8 "
        "(SRAM organisation)."
    ),
    input_schema={
        "type": "object",
        "required": [
            "mcu_label",
            "total_ram_bytes",
            "data_bytes",
            "bss_bytes",
            "heap_max_bytes",
            "stack_max_bytes",
        ],
        "properties": {
            "mcu_label": {
                "type": "string",
                "description": (
                    "Human-readable MCU identifier, e.g. 'STM32F411', 'ATmega328P'. "
                    "Used in report text; not validated against a registry."
                ),
            },
            "total_ram_bytes": {
                "type": "integer",
                "description": (
                    "Total SRAM in bytes for the target MCU. "
                    "Examples: STM32F411 → 131072 (128 KB, RM0383 §2); "
                    "STM32F407 → 131072 (128 KB, RM0090 §2); "
                    "ATmega328P → 2048 (2 KB, §8); "
                    "RP2040 → 262144 (256 KB)."
                ),
                "minimum": 1,
            },
            "data_bytes": {
                "type": "integer",
                "description": (
                    "Size of the .data section in bytes (initialised global/static "
                    "variables). Read from arm-none-eabi-size -A .data column or "
                    "avr-size output."
                ),
                "minimum": 0,
            },
            "bss_bytes": {
                "type": "integer",
                "description": (
                    "Size of the .bss section in bytes (zero-initialised global/static "
                    "variables + uninitialized statics). No Flash copy; zeroed at "
                    "startup."
                ),
                "minimum": 0,
            },
            "heap_max_bytes": {
                "type": "integer",
                "description": (
                    "Worst-case heap allocation estimate in bytes. "
                    "Pass 0 if no dynamic allocation is used. "
                    "For malloc-using firmware, estimate peak allocated bytes from "
                    "code review or heap-trace. "
                    "NOTE: malloc fragmentation metadata is NOT included — budget "
                    "20–30 % overhead for general-purpose allocators."
                ),
                "minimum": 0,
            },
            "stack_max_bytes": {
                "type": "integer",
                "description": (
                    "Worst-case stack depth estimate in bytes. "
                    "For Cortex-M: use the linker _stack section size or the "
                    "worst-case call-depth analysis result. "
                    "For FreeRTOS: sum all task stack sizes plus the MSP (main "
                    "stack pointer) size. "
                    "NOTE: interrupt frames (32 B each on Cortex-M) are NOT included — "
                    "add N_irq_nest × 32 B for nested-IRQ scenarios."
                ),
                "minimum": 0,
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_audit_ram_usage(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute the RAM usage audit and return a JSON payload."""
    mcu_label = args.get("mcu_label", "")
    if not mcu_label:
        return err_payload("'mcu_label' is required", "BAD_ARGS")

    total_ram_bytes = args.get("total_ram_bytes")
    if total_ram_bytes is None:
        return err_payload("'total_ram_bytes' is required", "BAD_ARGS")

    # Parse integer fields
    int_fields = [
        "total_ram_bytes",
        "data_bytes",
        "bss_bytes",
        "heap_max_bytes",
        "stack_max_bytes",
    ]
    parsed: dict[str, int] = {}
    for field in int_fields:
        val = args.get(field)
        if val is None:
            return err_payload(f"'{field}' is required", "BAD_ARGS")
        try:
            parsed[field] = int(val)
        except (TypeError, ValueError) as exc:
            return err_payload(f"'{field}' must be an integer: {exc}", "BAD_ARGS")
        if parsed[field] < 0:
            return err_payload(f"'{field}' must be >= 0", "BAD_ARGS")

    if parsed["total_ram_bytes"] == 0:
        return err_payload("'total_ram_bytes' must be > 0", "BAD_ARGS")

    try:
        sizes = MemorySectionSizes(
            data_bytes=parsed["data_bytes"],
            bss_bytes=parsed["bss_bytes"],
            heap_max_bytes=parsed["heap_max_bytes"],
            stack_max_bytes=parsed["stack_max_bytes"],
            total_ram_bytes=parsed["total_ram_bytes"],
            mcu_label=str(mcu_label),
        )
    except (TypeError, ValueError) as exc:
        return err_payload(f"Invalid section sizes: {exc}", "BAD_ARGS")

    try:
        report = audit_ram_usage(sizes)
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Audit error: {exc}", "AUDIT_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_audit_ram_usage_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_audit_ram_usage(a, ctx)
