"""LLM tool: firmware_check_pwm_resolution — MCU PWM resolution analyser.

Given an MCU timer clock frequency, a desired PWM frequency, and a counter
bit-width, computes the achievable PWM resolution (bits) and frequency error
using integer prescaler + ARR register arithmetic.

References
----------
  STM32F411 Reference Manual RM0383 §13 (General-purpose timers TIM2–TIM5).
  ATmega328P Datasheet §15 (Timer/Counter1 Fast PWM, ICR1 mode).
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.pwm_resolution_check import (
    PWMConfigSpec,
    check_pwm_resolution,
)


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_check_pwm_resolution",
    description=(
        "Compute the achievable PWM resolution (bits) and frequency error for an MCU "
        "timer peripheral, given a timer clock frequency, desired PWM frequency, and "
        "counter bit-width.\n\n"
        "Algorithm (STM32F411 RM0383 §13 + ATmega328P §15):\n"
        "  For each integer prescaler P in [1..65536]:\n"
        "    ARR = round(clock / (P × target_freq) − 1), clamped to [1, 2^bits−1]\n"
        "    f_actual = clock / (P × (ARR + 1))\n"
        "    freq_error_pct = (f_actual − target) / target × 100\n"
        "    resolution_bits = log2(ARR + 1)\n"
        "  Select (P, ARR) with maximum resolution_bits and |freq_error| < 1%.\n\n"
        "Oracle examples:\n"
        "  16 MHz clock, 1 kHz PWM, 16-bit: P=1, ARR=15999, resolution=13.97 bits\n"
        "  16 MHz clock, 20 kHz PWM, 16-bit: P=1, ARR=799, resolution=9.64 bits\n"
        "  16 MHz clock, 1 kHz PWM, 8-bit: ARR≤255, resolution≤8 bits\n\n"
        "HONEST CAVEAT: integer-prescaler model — exact for STM32F411 (PSC ∈ [0..65535]);\n"
        "ATmega328P Timer1 uses discrete prescalers {1,8,64,256,1024}; interrupt latency,\n"
        "dead-time insertion (TIM1/TIM8 BDTR), and complementary PWM are NOT modelled."
    ),
    input_schema={
        "type": "object",
        "required": ["mcu_clock_hz", "target_pwm_freq_Hz", "counter_bits"],
        "properties": {
            "mcu_clock_hz": {
                "type": "integer",
                "description": (
                    "MCU timer peripheral clock frequency in Hz. "
                    "E.g. 16000000 for ATmega328P @ 16 MHz; "
                    "100000000 for STM32F411 TIMx @ 100 MHz (APB1 timer clock doubled)."
                ),
                "minimum": 1,
            },
            "target_pwm_freq_Hz": {
                "type": "number",
                "description": (
                    "Desired PWM output frequency in Hz. "
                    "E.g. 1000 for 1 kHz servo/LED control, 20000 for inaudible motor drive."
                ),
                "exclusiveMinimum": 0,
            },
            "counter_bits": {
                "type": "integer",
                "description": (
                    "Timer counter width in bits. Must be one of {8, 10, 16, 32}. "
                    "Determines the maximum ARR value (2^bits − 1) and maximum resolution. "
                    "ATmega328P Timer0/Timer2 = 8-bit; Timer1 = 16-bit. "
                    "STM32F411 TIM3/TIM4 = 16-bit; TIM2/TIM5 = 32-bit."
                ),
                "enum": [8, 10, 16, 32],
            },
            "desired_resolution_bits": {
                "type": "integer",
                "description": (
                    "Minimum resolution requirement in bits. "
                    "meets_resolution_requirement is True iff achievable_resolution_bits >= "
                    "desired_resolution_bits. Default: 10 (1024 duty-cycle steps)."
                ),
                "minimum": 1,
                "default": 10,
            },
            "mcu_label": {
                "type": "string",
                "description": (
                    "Human-readable MCU + timer identifier, e.g. "
                    "'STM32F411 TIM3 @ 100 MHz' or 'ATmega328P Timer1 @ 16 MHz'."
                ),
                "default": "",
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_check_pwm_resolution(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute PWM resolution analysis and return a JSON payload."""
    mcu_clock_hz = args.get("mcu_clock_hz")
    target_pwm_freq_Hz = args.get("target_pwm_freq_Hz")
    counter_bits = args.get("counter_bits")

    if mcu_clock_hz is None:
        return err_payload("'mcu_clock_hz' is required", "BAD_ARGS")
    if target_pwm_freq_Hz is None:
        return err_payload("'target_pwm_freq_Hz' is required", "BAD_ARGS")
    if counter_bits is None:
        return err_payload("'counter_bits' is required", "BAD_ARGS")

    try:
        mcu_clock_hz = int(mcu_clock_hz)
        if mcu_clock_hz <= 0:
            raise ValueError("mcu_clock_hz must be > 0")
    except (TypeError, ValueError) as exc:
        return err_payload(f"mcu_clock_hz invalid: {exc}", "BAD_ARGS")

    try:
        target_pwm_freq_Hz = float(target_pwm_freq_Hz)
        if target_pwm_freq_Hz <= 0.0:
            raise ValueError("target_pwm_freq_Hz must be > 0")
    except (TypeError, ValueError) as exc:
        return err_payload(f"target_pwm_freq_Hz invalid: {exc}", "BAD_ARGS")

    try:
        counter_bits = int(counter_bits)
        if counter_bits not in (8, 10, 16, 32):
            raise ValueError("counter_bits must be one of {8, 10, 16, 32}")
    except (TypeError, ValueError) as exc:
        return err_payload(f"counter_bits invalid: {exc}", "BAD_ARGS")

    desired_resolution_bits = args.get("desired_resolution_bits", 10)
    try:
        desired_resolution_bits = int(desired_resolution_bits)
        if desired_resolution_bits < 1:
            raise ValueError("desired_resolution_bits must be >= 1")
    except (TypeError, ValueError) as exc:
        return err_payload(f"desired_resolution_bits invalid: {exc}", "BAD_ARGS")

    mcu_label = str(args.get("mcu_label", ""))

    try:
        spec = PWMConfigSpec(
            mcu_clock_hz=mcu_clock_hz,
            target_pwm_freq_Hz=target_pwm_freq_Hz,
            counter_bits=counter_bits,
            desired_resolution_bits=desired_resolution_bits,
            mcu_label=mcu_label,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    try:
        report = check_pwm_resolution(spec)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Analysis error: {exc}", "ANALYSIS_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_check_pwm_resolution_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_check_pwm_resolution(a, ctx)
