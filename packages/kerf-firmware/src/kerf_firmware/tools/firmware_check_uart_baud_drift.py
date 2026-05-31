"""LLM tool: firmware_check_uart_baud_drift — UART baud-rate drift analyser.

Computes the actual baud rate achieved by a UART peripheral given an MCU
clock frequency and a UBRR (USART Baud Rate Register) divisor value, reports
the percent drift vs the nominal target, flags unreliable links (>2 % drift,
per RS-232 / IEEE Std 488), and recommends the best standard baud + UBRR
combinations that achieve <0.5 % drift with the same clock.

References
----------
  ATmega328P Datasheet §19 (USART) — Integer divisor formula.
  STM32F411 Reference Manual RM0383 §19 (USART) — Fractional BRR generator.
  IEEE Std 488 — Baud-rate tolerance ±2 %.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.uart_baud_drift_check import (
    UartConfigSpec,
    check_uart_baud_drift,
)


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_check_uart_baud_drift",
    description=(
        "Compute UART baud-rate drift for an MCU UART peripheral and flag links "
        "that exceed RS-232 / IEEE Std 488 ±2 % tolerance.\n\n"
        "Algorithm (ATmega328P Datasheet §19):\n"
        "  Normal mode (U2X=0):  BAUD_actual = clock / (16 × (UBRR + 1))\n"
        "  Double-speed (U2X=1): BAUD_actual = clock / ( 8 × (UBRR + 1))\n"
        "  drift_pct = (BAUD_actual − BAUD_nominal) / BAUD_nominal × 100\n"
        "  reliable = |drift_pct| < 2.0  (RS-232 / IEEE Std 488 tolerance)\n\n"
        "Oracle examples:\n"
        "  ATmega328P 16 MHz, UBRR=103, target 9600: "
        "actual=9615.4, drift=+0.16% → reliable=True\n"
        "  ATmega328P 16 MHz, UBRR=8, target 115200: "
        "actual=111111, drift=−3.55% → reliable=False (flag!)\n"
        "  ATmega328P 16 MHz, UBRR=16, double_speed, target 115200: "
        "actual=117647, drift=+2.12% → reliable=False (flag!)\n\n"
        "Recommendations: for each standard baud in [9600, 19200, 38400, 57600, "
        "115200, 230400, 460800, 921600] × {normal, double_speed}, compute the "
        "optimal UBRR and include entries with |drift| < 0.5% in the output.\n\n"
        "HONEST CAVEAT: ATmega integer-divisor model is exact for AVR; for STM32 "
        "(fractional BRR) this model OVER-ESTIMATES drift by up to ~1% — the real "
        "STM32 fractional generator typically achieves < 0.1%. Always verify on "
        "target hardware with an oscilloscope or logic analyser."
    ),
    input_schema={
        "type": "object",
        "required": ["mcu_clock_hz", "ubrr_register_value", "target_baud"],
        "properties": {
            "mcu_clock_hz": {
                "type": "integer",
                "description": (
                    "MCU peripheral clock frequency in Hz. "
                    "E.g. 16000000 for ATmega328P @ 16 MHz, "
                    "80000000 for STM32F411 USART1 @ 80 MHz."
                ),
                "minimum": 1,
            },
            "ubrr_register_value": {
                "type": "integer",
                "description": (
                    "Value loaded into the UBRR (or BRR mantissa) register. "
                    "ATmega: UBRR = round(f_osc / (16 × BAUD) − 1) in normal mode. "
                    "Must be >= 0."
                ),
                "minimum": 0,
            },
            "target_baud": {
                "type": "integer",
                "description": (
                    "Nominal / desired baud rate in bps, e.g. 9600 or 115200."
                ),
                "minimum": 1,
            },
            "mode": {
                "type": "string",
                "description": (
                    "'normal' — ATmega normal mode: divisor = 16 × (UBRR + 1). "
                    "'double_speed' — ATmega U2X mode: divisor = 8 × (UBRR + 1). "
                    "Default: 'normal'."
                ),
                "enum": ["normal", "double_speed"],
                "default": "normal",
            },
            "mcu_label": {
                "type": "string",
                "description": (
                    "Human-readable MCU identifier, e.g. 'ATmega328P @ 16 MHz' "
                    "or 'STM32F411CE USART1 @ 80 MHz'."
                ),
                "default": "",
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_check_uart_baud_drift(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute UART baud-rate drift analysis and return a JSON payload."""
    mcu_clock_hz = args.get("mcu_clock_hz")
    ubrr_register_value = args.get("ubrr_register_value")
    target_baud = args.get("target_baud")

    if mcu_clock_hz is None:
        return err_payload("'mcu_clock_hz' is required", "BAD_ARGS")
    if ubrr_register_value is None:
        return err_payload("'ubrr_register_value' is required", "BAD_ARGS")
    if target_baud is None:
        return err_payload("'target_baud' is required", "BAD_ARGS")

    try:
        mcu_clock_hz = int(mcu_clock_hz)
        if mcu_clock_hz <= 0:
            raise ValueError("mcu_clock_hz must be > 0")
    except (TypeError, ValueError) as exc:
        return err_payload(f"mcu_clock_hz invalid: {exc}", "BAD_ARGS")

    try:
        ubrr_register_value = int(ubrr_register_value)
        if ubrr_register_value < 0:
            raise ValueError("ubrr_register_value must be >= 0")
    except (TypeError, ValueError) as exc:
        return err_payload(f"ubrr_register_value invalid: {exc}", "BAD_ARGS")

    try:
        target_baud = int(target_baud)
        if target_baud <= 0:
            raise ValueError("target_baud must be > 0")
    except (TypeError, ValueError) as exc:
        return err_payload(f"target_baud invalid: {exc}", "BAD_ARGS")

    mode = args.get("mode", "normal")
    if mode not in ("normal", "double_speed"):
        return err_payload(
            f"mode must be 'normal' or 'double_speed', got {mode!r}", "BAD_ARGS"
        )

    mcu_label = str(args.get("mcu_label", ""))

    try:
        config = UartConfigSpec(
            mcu_clock_hz=mcu_clock_hz,
            ubrr_register_value=ubrr_register_value,
            mode=mode,
            mcu_label=mcu_label,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    try:
        report = check_uart_baud_drift(config, target_baud)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Analysis error: {exc}", "ANALYSIS_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_check_uart_baud_drift_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_check_uart_baud_drift(a, ctx)
