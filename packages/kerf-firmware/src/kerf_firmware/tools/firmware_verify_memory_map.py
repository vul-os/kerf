"""LLM tool: firmware_verify_memory_map — verify Cortex-M firmware memory layout.

Checks that linker-script section sizes fit within the chip's Flash and SRAM,
that the stack cannot overflow into .bss at the declared sizes, that the vector
table is placed correctly, and that the ISR vector count matches the chip NVIC.

References
----------
  RM0383 Rev 3 §3              — STM32F411xC/E memory map (512 KB Flash / 128 KB SRAM).
  RM0090 Rev 19 §3             — STM32F407/417 memory map (1 MB Flash / 128 KB SRAM).
  ARM Cortex-M Generic User Guide (ARM DUI 0553B) §B3.2.4 — SCB->VTOR.
  ARM Cortex-M Generic User Guide §B1.3.2              — system exception table.
"""
from __future__ import annotations

import json
from typing import Any, Optional

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.memory_map_verify import LinkerSection, verify_memory_layout


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_verify_memory_map",
    description=(
        "Verify the memory layout of a Cortex-M firmware against the chip's physical "
        "Flash and SRAM regions and the linker-script section sizes. "
        "Detects: "
        "FLASH_OVERFLOW (sections exceed chip Flash capacity), "
        "SRAM_OVERFLOW (runtime sections exceed chip SRAM capacity), "
        "STACK_OVERFLOW_INTO_BSS (stack size > remaining SRAM after .data + .bss; "
        "conservative static check), "
        "VECTOR_TABLE_MISPLACED (vector table base not at Flash start and not in SRAM "
        "for VTOR remap — ARM Cortex-M Generic UG §B3.2.4), "
        "ISR_COUNT_MISMATCH (vector table entry count != chip NVIC count per RM0383 §10). "
        "Supported chips: STM32F411 (512 KB Flash / 128 KB SRAM, RM0383 §3), "
        "STM32F407 (1 MB Flash / 128 KB SRAM, RM0090 §3). "
        "NOTE: static section-size check only — does not run the actual linker; "
        "use arm-none-eabi-size + map file for production audits."
    ),
    input_schema={
        "type": "object",
        "required": ["chip", "sections"],
        "properties": {
            "chip": {
                "type": "string",
                "description": (
                    "Chip family. One of: 'STM32F411', 'STM32F407', or aliases "
                    "'stm32f411ce', 'stm32f411re', 'stm32f411ve', 'stm32f407vg', "
                    "'stm32f407ig'."
                ),
            },
            "sections": {
                "type": "array",
                "description": (
                    "Linker-script output sections to verify. "
                    "Each entry describes a section name, size, and memory region. "
                    "Flash usage = sum of lma_size for all sections (includes .data "
                    "init image stored in Flash). "
                    "SRAM usage = sum of size for all region='sram' sections."
                ),
                "items": {
                    "type": "object",
                    "required": ["name", "size", "region"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": (
                                "Section name, e.g. '.text', '.rodata', '.data', "
                                "'.bss', '_stack', '_heap'."
                            ),
                        },
                        "size": {
                            "type": "integer",
                            "description": "Section size in bytes (VMA size at runtime).",
                            "minimum": 0,
                        },
                        "region": {
                            "type": "string",
                            "enum": ["flash", "sram"],
                            "description": (
                                "Memory region. Use 'flash' for sections whose VMA is in "
                                "Flash (.text, .rodata, .ARM.extab, etc.). "
                                "Use 'sram' for sections resident in SRAM at runtime "
                                "(.data VMA, .bss, _stack, heap). "
                                "Note: .data has both an LMA (Flash) and VMA (SRAM); "
                                "use region='sram' and set lma_size=<data_size> to "
                                "account for the Flash copy."
                            ),
                        },
                        "lma_size": {
                            "type": "integer",
                            "description": (
                                "Bytes consumed in Flash at the load-memory address. "
                                "For .text, .rodata: omit (same as size). "
                                "For .data: set to the section size (init image in Flash). "
                                "For .bss, _stack: set to 0 (no Flash copy). "
                                "Default: inferred from is_bss / is_stack flags."
                            ),
                            "minimum": 0,
                        },
                        "is_stack": {
                            "type": "boolean",
                            "description": (
                                "True if this section is the initial stack allocation. "
                                "Used for stack-overflow-into-bss detection."
                            ),
                            "default": False,
                        },
                        "is_bss": {
                            "type": "boolean",
                            "description": (
                                "True if this section is zero-initialised (.bss). "
                                "lma_size defaults to 0 when is_bss=true."
                            ),
                            "default": False,
                        },
                        "is_heap": {
                            "type": "boolean",
                            "description": "True if this section is the heap.",
                            "default": False,
                        },
                    },
                },
                "minItems": 1,
            },
            "vector_table_addr": {
                "type": "integer",
                "description": (
                    "Optional base address of the vector table. "
                    "Default: chip Flash start (0x08000000 for STM32). "
                    "If set to a SRAM address (0x20000000+), treated as VTOR remap — "
                    "the tool will note that SCB->VTOR must be written. "
                    "If set to any other address, raises VECTOR_TABLE_MISPLACED. "
                    "(ARM Cortex-M Generic UG §B3.2.4)"
                ),
            },
            "isr_vector_count": {
                "type": "integer",
                "description": (
                    "Optional total number of entries in the application's vector "
                    "table (including initial SP, all 16 Cortex-M system exceptions, "
                    "and all peripheral IRQ handlers). "
                    "STM32F411: 16 + 62 = 78 entries. "
                    "STM32F407: 16 + 82 = 98 entries. "
                    "A mismatch raises ISR_COUNT_MISMATCH."
                ),
                "minimum": 1,
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_verify_memory_map(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute memory-map verification and return a JSON payload."""
    chip = args.get("chip", "")
    raw_sections = args.get("sections")

    if not chip:
        return err_payload("'chip' is required", "BAD_ARGS")
    if not raw_sections:
        return err_payload("'sections' is required and must be non-empty", "BAD_ARGS")
    if not isinstance(raw_sections, list):
        return err_payload("'sections' must be a JSON array", "BAD_ARGS")

    # Parse section dicts
    parsed: list[LinkerSection] = []
    for i, item in enumerate(raw_sections):
        if not isinstance(item, dict):
            return err_payload(f"sections[{i}] must be a JSON object", "BAD_ARGS")
        try:
            name = str(item["name"])
            size = int(item["size"])
            region = str(item["region"])
        except KeyError as exc:
            return err_payload(f"sections[{i}] missing required field {exc}", "BAD_ARGS")
        except (TypeError, ValueError) as exc:
            return err_payload(f"sections[{i}] invalid value: {exc}", "BAD_ARGS")

        lma_size: Optional[int] = None
        if "lma_size" in item and item["lma_size"] is not None:
            try:
                lma_size = int(item["lma_size"])
            except (TypeError, ValueError) as exc:
                return err_payload(f"sections[{i}].lma_size invalid: {exc}", "BAD_ARGS")

        is_stack = bool(item.get("is_stack", False))
        is_bss = bool(item.get("is_bss", False))
        is_heap = bool(item.get("is_heap", False))

        try:
            parsed.append(LinkerSection(
                name=name,
                size=size,
                region=region,
                lma_size=lma_size,
                is_stack=is_stack,
                is_bss=is_bss,
                is_heap=is_heap,
            ))
        except ValueError as exc:
            return err_payload(f"sections[{i}] invalid: {exc}", "BAD_ARGS")

    # Optional parameters
    vector_table_addr: Optional[int] = None
    if "vector_table_addr" in args and args["vector_table_addr"] is not None:
        try:
            vector_table_addr = int(args["vector_table_addr"])
        except (TypeError, ValueError) as exc:
            return err_payload(f"'vector_table_addr' invalid: {exc}", "BAD_ARGS")

    isr_vector_count: Optional[int] = None
    if "isr_vector_count" in args and args["isr_vector_count"] is not None:
        try:
            isr_vector_count = int(args["isr_vector_count"])
        except (TypeError, ValueError) as exc:
            return err_payload(f"'isr_vector_count' invalid: {exc}", "BAD_ARGS")

    try:
        report = verify_memory_layout(
            chip,
            parsed,
            vector_table_addr=vector_table_addr,
            isr_vector_count=isr_vector_count,
        )
    except KeyError as exc:
        return err_payload(str(exc), "UNKNOWN_CHIP")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Verification error: {exc}", "VERIFY_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_verify_memory_map_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_verify_memory_map(a, ctx)
