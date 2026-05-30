"""LLM tool: firmware_verify_peripheral_map — check MCU pin assignments.

Verifies that a firmware peripheral pin-mapping (which physical pin is
assigned to which function: UART_TX, SPI_MISO, I2C_SDA, PWM, ADC, etc.)
is consistent with the chip's hardware capabilities.

IMPORTANT — HONEST DISCLAIMER
------------------------------
Kerf's built-in pin-map verifier is a *helpful sanity-checker*, NOT a
substitute for the vendor's official pin-assignment tools (ST CubeMX,
STM32CubeIDE, Microchip Atmel Start, or the relevant IDE's pin-config
wizard).  Always run your final pin assignment through the vendor tool
for your exact package and silicon revision before committing to a PCB
layout.

Supported chips (chip_id values)
---------------------------------
  "STM32F411_LQFP64"  — STM32F411xE LQFP64, 3.3 V (RM0383 §7.3).
  "ATmega328P_PDIP28" — ATmega328P PDIP-28, 5 V  (datasheet §13).
  Aliases: "stm32f411", "atmega328p", "atmega328", "arduino_uno".

References
----------
  RM0383 Rev 3 §7.3 Table 9 "STM32F411xC/E alternate function mapping".
  ATmega328P datasheet 7810D §13 Table 13-2 "Signal Description".
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.peripheral_map_verify import verify_pin_mapping


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_verify_peripheral_map",
    description=(
        "Verify a microcontroller peripheral pin-mapping against the chip's "
        "hardware alternate-function table. "
        "Detects: (1) a pin assigned to a function it cannot host "
        "(not in its AF list); (2) two signals sharing the same physical pin; "
        "(3) required peripherals with no pin assignment; "
        "(4) the same peripheral signal routed to multiple pins; "
        "(5) 5 V external signals wired to non-5V-tolerant pins. "
        "Supported chips: STM32F411_LQFP64 (RM0383 §7.3), "
        "ATmega328P_PDIP28 (datasheet §13). "
        "NOTE: this is a sanity-checker — NOT a substitute for ST CubeMX, "
        "STM32CubeIDE, or Microchip Atmel Start. "
        "Always confirm your final pin assignment with the vendor tool."
    ),
    input_schema={
        "type": "object",
        "required": ["chip_id", "mapping"],
        "properties": {
            "chip_id": {
                "type": "string",
                "description": (
                    "Chip identifier. One of: 'STM32F411_LQFP64', "
                    "'ATmega328P_PDIP28', or aliases 'stm32f411', "
                    "'atmega328p', 'arduino_uno'."
                ),
            },
            "mapping": {
                "type": "object",
                "description": (
                    "Object whose keys are peripheral signal names "
                    "(e.g. 'UART2_TX', 'SPI1_MOSI', 'I2C1_SDA', 'ADC_IN0') "
                    "and values are physical pin names "
                    "(e.g. 'PA2', 'PB5', 'PD0'). "
                    "Signal names are matched case-insensitively against the "
                    "chip's alternate-function list."
                ),
                "additionalProperties": {"type": "string"},
            },
            "required_peripherals": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of signal names that must appear in mapping. "
                    "Missing entries generate a MISSING_REQUIRED violation."
                ),
                "default": [],
            },
            "five_volt_signals": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional list of signal names whose external driver "
                    "operates at 5 V. Pins that are not 5V tolerant will "
                    "be flagged as VOLTAGE_INCOMPATIBLE."
                ),
                "default": [],
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_verify_peripheral_map(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute the pin-map verification and return a JSON payload."""
    chip_id = args.get("chip_id", "")
    mapping = args.get("mapping")
    required = args.get("required_peripherals") or []
    five_volt = args.get("five_volt_signals") or []

    if not chip_id:
        return err_payload("'chip_id' is required", "BAD_ARGS")
    if not mapping or not isinstance(mapping, dict):
        return err_payload("'mapping' must be a non-empty object", "BAD_ARGS")

    try:
        report = verify_pin_mapping(
            chip_id,
            mapping,
            required_peripherals=required,
            five_volt_signals=five_volt,
        )
    except KeyError as exc:
        return err_payload(str(exc), "UNKNOWN_CHIP")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Verification error: {exc}", "VERIFY_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_verify_peripheral_map_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_verify_peripheral_map(a, ctx)
