"""LLM tool: firmware_estimate_stack_depth — static worst-case stack analyser.

Estimates worst-case stack depth for a Cortex-M / ATmega firmware function
call tree given per-function stack frame sizes and call relationships.

Algorithm: DFS through the call graph, accumulating frame sizes.  Back-edges
(recursion) are detected and flagged.  ISR preemption overhead is added once
to the deepest path total.

References
----------
  ARM IHI 0042F AAPCS §5.2, §6.1 — stack frame layout.
  ARM Cortex-M Generic UG §B1.5.6 — 8-register exception frame (32 bytes).
  Greenwood (2011), "Static Stack Analysis for Embedded Systems", §3 — DFS.
  Brylow et al. (2001), LCTES/OM — empirical validation of DFS stack analysis.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.stack_depth_estimate import (
    FunctionFrame,
    estimate_stack_depth,
)


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_estimate_stack_depth",
    description=(
        "Estimate worst-case stack depth in bytes for a Cortex-M or ATmega firmware "
        "function call tree.  Given per-function stack frame sizes and call "
        "relationships, performs a DFS to find the deepest call chain and adds an "
        "ISR preemption overhead.\n\n"
        "Algorithm: DFS through the call graph from the entry function, accumulating "
        "frame sizes.  Cyclic call chains (recursion) are detected and flagged.  "
        "ISR overhead is added once (default 32 B = Cortex-M3/M4/M7 hardware exception "
        "frame: 8 registers × 4 bytes, ARM Generic UG §B1.5.6).\n\n"
        "Depth-bar oracle — 3-function chain main(100) → A(200) → B(50):\n"
        "  max_stack_depth_bytes = 100 + 200 + 50 + 32 (ISR) = 382 B.\n\n"
        "Frame sizes should come from arm-none-eabi-gcc / avr-gcc -fstack-usage "
        "(*.su files), not manual estimates.\n\n"
        "HONEST LIMITATIONS: static estimate only — does not account for VLA "
        "(variable-length arrays), alloca(), longjmp/setjmp, inline asm SP "
        "manipulation, or indirect calls (function pointers, callbacks).  "
        "Recursive cycles are flagged; the reported depth is a per-iteration lower "
        "bound only.  Refs: ARM IHI 0042F AAPCS §5.2/§6.1; Greenwood (2011) "
        "'Static Stack Analysis for Embedded Systems' §3."
    ),
    input_schema={
        "type": "object",
        "required": ["functions", "entry_function_name"],
        "properties": {
            "functions": {
                "type": "array",
                "description": (
                    "List of function descriptors.  Each entry requires: "
                    "function_name (str), frame_size_bytes (int ≥ 0), "
                    "callees (array of function name strings, may be empty). "
                    "Functions referenced as callees but absent from this list "
                    "are treated as leaf nodes with frame_size_bytes = 0 "
                    "(external / library functions — their frame cost is ignored)."
                ),
                "items": {
                    "type": "object",
                    "required": ["function_name", "frame_size_bytes"],
                    "properties": {
                        "function_name": {
                            "type": "string",
                            "description": "Unique function name as it appears in the symbol table.",
                        },
                        "frame_size_bytes": {
                            "type": "integer",
                            "description": (
                                "Stack bytes consumed by this function's activation record "
                                "(local variables + saved registers + alignment padding).  "
                                "Obtain from arm-none-eabi-gcc -fstack-usage *.su files."
                            ),
                            "minimum": 0,
                        },
                        "callees": {
                            "type": "array",
                            "description": (
                                "Names of functions directly called by this function.  "
                                "Indirect calls (function pointers, callbacks) must be "
                                "enumerated manually as synthetic entries."
                            ),
                            "items": {"type": "string"},
                            "default": [],
                        },
                    },
                },
                "minItems": 1,
            },
            "entry_function_name": {
                "type": "string",
                "description": (
                    "Name of the call-tree root, e.g. 'main' or an ISR handler name "
                    "('SysTick_Handler', 'USART1_IRQHandler').  Must appear in the "
                    "functions list."
                ),
            },
            "isr_overhead_bytes": {
                "type": "integer",
                "description": (
                    "Extra bytes added to model hardware ISR entry push.  "
                    "Default 32 = Cortex-M3/M4/M7 exception frame (8 regs × 4 B, "
                    "ARM Cortex-M Generic UG §B1.5.6).  "
                    "Pass 3 for ATmega (PC save only).  "
                    "Pass 0 to get the bare call-tree maximum without ISR overhead."
                ),
                "minimum": 0,
                "default": 32,
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_estimate_stack_depth(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute stack-depth estimation and return a JSON payload."""
    raw_functions = args.get("functions")
    entry_name = args.get("entry_function_name")
    isr_overhead = args.get("isr_overhead_bytes", 32)

    # ── Validate top-level required fields ────────────────────────────────────
    if not raw_functions:
        return err_payload("'functions' is required and must be non-empty", "BAD_ARGS")
    if not isinstance(raw_functions, list):
        return err_payload("'functions' must be a JSON array", "BAD_ARGS")
    if not entry_name:
        return err_payload("'entry_function_name' is required", "BAD_ARGS")
    if not isinstance(entry_name, str):
        return err_payload("'entry_function_name' must be a string", "BAD_ARGS")

    # ── Validate / parse isr_overhead_bytes ───────────────────────────────────
    try:
        isr_overhead = int(isr_overhead)
    except (TypeError, ValueError) as exc:
        return err_payload(f"'isr_overhead_bytes' must be an integer: {exc}", "BAD_ARGS")
    if isr_overhead < 0:
        return err_payload("'isr_overhead_bytes' must be >= 0", "BAD_ARGS")

    # ── Parse function descriptors ─────────────────────────────────────────────
    frames: list[FunctionFrame] = []
    for i, item in enumerate(raw_functions):
        if not isinstance(item, dict):
            return err_payload(f"functions[{i}] must be a JSON object", "BAD_ARGS")
        try:
            fn_name = str(item["function_name"])
            frame_size = int(item["frame_size_bytes"])
        except KeyError as exc:
            return err_payload(f"functions[{i}] missing required field {exc}", "BAD_ARGS")
        except (TypeError, ValueError) as exc:
            return err_payload(f"functions[{i}] invalid value: {exc}", "BAD_ARGS")

        callees_raw = item.get("callees", [])
        if not isinstance(callees_raw, list):
            return err_payload(
                f"functions[{i}].callees must be an array of strings, got "
                f"{type(callees_raw).__name__}",
                "BAD_ARGS",
            )
        callees = []
        for j, c in enumerate(callees_raw):
            if not isinstance(c, str):
                return err_payload(
                    f"functions[{i}].callees[{j}] must be a string, got "
                    f"{type(c).__name__}",
                    "BAD_ARGS",
                )
            callees.append(c)

        try:
            frames.append(FunctionFrame(
                function_name=fn_name,
                frame_size_bytes=frame_size,
                callees=callees,
            ))
        except ValueError as exc:
            return err_payload(f"functions[{i}] invalid: {exc}", "BAD_ARGS")

    # ── Run estimation ─────────────────────────────────────────────────────────
    try:
        report = estimate_stack_depth(frames, entry_name, isr_overhead_bytes=isr_overhead)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Computation error: {exc}", "COMPUTE_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_estimate_stack_depth_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_estimate_stack_depth(a, ctx)
