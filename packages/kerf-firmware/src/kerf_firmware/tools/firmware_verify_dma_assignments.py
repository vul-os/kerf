"""LLM tool: firmware_verify_dma_assignments — verify STM32 DMA channel assignments.

Checks that each (peripheral, controller, stream, channel) DMA assignment is
valid according to the hardware request-mapping tables embedded from RM0383 and
RM0090.  Detects:

  * **INVALID_ASSIGNMENT** — peripheral not legal on this stream/channel; with
    suggestions for valid alternatives.
  * **STREAM_CONFLICT** — two peripherals mapped to the same DMA stream.
  * **UNKNOWN_CONTROLLER** — controller name not present on the chip.

HONEST DISCLAIMER
-----------------
Static conflict detection only.  This tool does NOT model DMA arbitration
priority, throughput starvation, FIFO depths, burst interactions, or double-
buffer mode.  Use STM32CubeMX DMA bandwidth estimator for timing/throughput
analysis.

Supported chips
---------------
  "STM32F411" (+ aliases stm32f411ce / stm32f411re / stm32f411ve)
  "STM32F407" (+ aliases stm32f407vg / stm32f407ig)

References
----------
  RM0383 Rev 3 §10.3.3 Tables 27–28 — STM32F411 DMA1/DMA2 request mapping.
  RM0090 Rev 19 §10.3.3 Tables 42–43 — STM32F407 DMA1/DMA2 request mapping.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.dma_channel_conflict import DMAAssignment, verify_dma_assignments


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_verify_dma_assignments",
    description=(
        "Verify STM32 DMA controller channel-assignment configuration. "
        "Checks each (peripheral, controller, stream, channel) assignment "
        "against the hardware request-mapping tables from RM0383/RM0090. "
        "Detects: INVALID_ASSIGNMENT (peripheral not valid on this stream/channel, "
        "with alternative suggestions), STREAM_CONFLICT (two peripherals sharing "
        "the same stream), UNKNOWN_CONTROLLER (DMA controller not present on chip). "
        "Supported chips: STM32F411, STM32F407. "
        "NOTE: static conflict detection only — no DMA throughput/priority model."
    ),
    input_schema={
        "type": "object",
        "required": ["chip", "assignments"],
        "properties": {
            "chip": {
                "type": "string",
                "description": (
                    "Chip family. One of: 'STM32F411', 'STM32F407', "
                    "or aliases 'stm32f411ce', 'stm32f411re', 'stm32f407vg', etc."
                ),
            },
            "assignments": {
                "type": "array",
                "description": (
                    "List of DMA channel assignments to verify. "
                    "Each entry is a {peripheral, controller, stream, channel} object."
                ),
                "items": {
                    "type": "object",
                    "required": ["peripheral", "controller", "stream", "channel"],
                    "properties": {
                        "peripheral": {
                            "type": "string",
                            "description": (
                                "Peripheral signal name, e.g. 'SPI1_TX', 'USART2_RX', "
                                "'ADC1', 'TIM2_CH1'. Case-insensitive."
                            ),
                        },
                        "controller": {
                            "type": "string",
                            "description": "DMA controller name: 'DMA1' or 'DMA2'. Case-insensitive.",
                        },
                        "stream": {
                            "type": "integer",
                            "description": "DMA stream number (0–7).",
                            "minimum": 0,
                            "maximum": 7,
                        },
                        "channel": {
                            "type": "integer",
                            "description": (
                                "Channel selection register value (0–7). "
                                "Selects the peripheral request line for this stream."
                            ),
                            "minimum": 0,
                            "maximum": 7,
                        },
                        "label": {
                            "type": "string",
                            "description": (
                                "Optional human-readable label for this assignment "
                                "(e.g. 'hdma_spi1_tx'). Used only in violation messages."
                            ),
                            "default": "",
                        },
                    },
                },
                "minItems": 1,
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_verify_dma_assignments(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute DMA assignment verification and return a JSON payload."""
    chip = args.get("chip", "")
    raw_assignments = args.get("assignments")

    if not chip:
        return err_payload("'chip' is required", "BAD_ARGS")
    if not raw_assignments:
        return err_payload("'assignments' is required and must be non-empty", "BAD_ARGS")
    if not isinstance(raw_assignments, list):
        return err_payload("'assignments' must be a JSON array", "BAD_ARGS")

    # Parse assignment dicts
    parsed: list[DMAAssignment] = []
    for i, item in enumerate(raw_assignments):
        if not isinstance(item, dict):
            return err_payload(
                f"assignments[{i}] must be a JSON object", "BAD_ARGS"
            )
        try:
            parsed.append(DMAAssignment(
                peripheral=str(item["peripheral"]),
                controller=str(item["controller"]),
                stream=int(item["stream"]),
                channel=int(item["channel"]),
                label=str(item.get("label", "")),
            ))
        except KeyError as exc:
            return err_payload(
                f"assignments[{i}] missing required field {exc}", "BAD_ARGS"
            )
        except (TypeError, ValueError) as exc:
            return err_payload(
                f"assignments[{i}] invalid value: {exc}", "BAD_ARGS"
            )

    try:
        report = verify_dma_assignments(chip, parsed)
    except KeyError as exc:
        return err_payload(str(exc), "UNKNOWN_CHIP")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Verification error: {exc}", "VERIFY_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_verify_dma_assignments_async(
    ctx: object, args: bytes
) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_verify_dma_assignments(a, ctx)
