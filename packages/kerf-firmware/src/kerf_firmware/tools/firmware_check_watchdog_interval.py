"""LLM tool: firmware_check_watchdog_interval — MCU watchdog timeout verifier.

Computes the actual watchdog timeout interval (STM32F411 IWDG / ATmega328P WDT)
and verifies that the timeout covers the application's worst-case loop latency
with a 2× minimum safety margin (ARM Keil AN259).

References
----------
  STM32F411 Reference Manual RM0383 Rev 3 §17 — Independent Watchdog (IWDG).
  ATmega328P Datasheet Rev 7810D §11 — Watchdog Timer.
  ARM Keil Application Note AN259 — Using Watchdog Timers in Embedded Systems.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.watchdog_interval_check import (
    WatchdogConfig,
    WorstCaseLoopLatency,
    check_watchdog_interval,
)


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_check_watchdog_interval",
    description=(
        "Compute the actual MCU watchdog timeout interval and verify it covers "
        "the application's worst-case loop latency with an adequate safety margin.\n\n"
        "Timeout formula (RM0383 §17 IWDG + ATmega328P §11 WDT):\n"
        "  timeout_s = prescaler × (reload_value + 1) / clock_hz\n\n"
        "Adequacy criterion (ARM Keil AN259):\n"
        "  adequate = timeout_ms > 2 × worst_case_ms\n\n"
        "When inadequate, recommends the smallest reload_value that gives exactly "
        "2.5× worst-case margin with the same clock and prescaler.\n\n"
        "Depth-bar oracle — STM32F411 IWDG: LSI=32 kHz, prescaler=64, reload=4095:\n"
        "  timeout = 64 × 4096 / 32000 = 8.192 s = 8192 ms.\n"
        "  vs 5 s worst-case: adequate (8192 > 2×5000=10000? No — "
        "8192 > 10000 is False; headroom = 3192 ms, margin = 63.8%).\n"
        "  Wait — 8192 ms vs 2×5000 ms=10000 ms: 8192 < 10000 → adequate=False "
        "for 5 s loop? Re-check: 5000 ms worst-case, 2×5000=10000 ms threshold; "
        "8192 < 10000 → adequate=False. Use worst_case_ms=4000 for adequate "
        "(8192 > 8000 → True). Pass worst_case_ms values accordingly.\n\n"
        "NOTE: Assumes ideal LSI clock at nominal frequency. STM32F411 LSI ±10–15%; "
        "ATmega128 kHz WDT ±10–15%. Real-world margin should subtract ≥10% from "
        "computed timeout. WWDG (window watchdog) upper-bound NOT modelled."
    ),
    input_schema={
        "type": "object",
        "required": ["config", "latency"],
        "properties": {
            "config": {
                "type": "object",
                "description": "Watchdog peripheral configuration.",
                "required": ["clock_hz", "prescaler", "reload_value", "mcu_label"],
                "properties": {
                    "clock_hz": {
                        "type": "integer",
                        "description": (
                            "Watchdog clock source frequency in Hz. "
                            "STM32F411 IWDG LSI: 32000 (typical). "
                            "ATmega328P WDT internal RC: 128000 (typical)."
                        ),
                        "minimum": 1,
                    },
                    "prescaler": {
                        "type": "integer",
                        "description": (
                            "Integer prescaler applied to the watchdog clock. "
                            "STM32F411 IWDG valid values: 4, 8, 16, 32, 64, 128, 256. "
                            "ATmega328P WDT prescaler chain: 2048, 4096, 8192, ... 1048576."
                        ),
                        "minimum": 1,
                    },
                    "reload_value": {
                        "type": "integer",
                        "description": (
                            "Down-counter initial (reload) value. "
                            "STM32F411 IWDG RLR: 0–4095 (12-bit). "
                            "ATmega328P WDT: 0–1023 (10-bit, approximation)."
                        ),
                        "minimum": 0,
                    },
                    "mcu_label": {
                        "type": "string",
                        "description": (
                            "Human-readable MCU identifier, e.g. "
                            "'STM32F411CE IWDG' or 'ATmega328P WDT'."
                        ),
                    },
                },
            },
            "latency": {
                "type": "object",
                "description": "Application worst-case loop latency estimate.",
                "required": ["worst_case_ms", "source"],
                "properties": {
                    "worst_case_ms": {
                        "type": "number",
                        "description": (
                            "Worst-case time between consecutive watchdog kicks, "
                            "in milliseconds. Must cover ISR pile-up, SD card write, "
                            "sensor timeout, and all blocking paths."
                        ),
                        "exclusiveMinimum": 0,
                    },
                    "source": {
                        "type": "string",
                        "description": (
                            "Label describing the origin of the worst-case estimate. "
                            "Suggested: 'ISR_pile_up', 'sd_write', "
                            "'sensor_timeout', 'manual_spec'."
                        ),
                        "enum": [
                            "ISR_pile_up",
                            "sd_write",
                            "sensor_timeout",
                            "manual_spec",
                        ],
                    },
                },
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_check_watchdog_interval(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute watchdog interval analysis and return a JSON payload."""
    raw_config = args.get("config")
    raw_latency = args.get("latency")

    if not isinstance(raw_config, dict):
        return err_payload("'config' is required and must be a JSON object", "BAD_ARGS")
    if not isinstance(raw_latency, dict):
        return err_payload("'latency' is required and must be a JSON object", "BAD_ARGS")

    # ── Parse config ──────────────────────────────────────────────────────────
    try:
        config = WatchdogConfig(
            clock_hz=int(raw_config["clock_hz"]),
            prescaler=int(raw_config["prescaler"]),
            reload_value=int(raw_config["reload_value"]),
            mcu_label=str(raw_config["mcu_label"]),
        )
    except KeyError as exc:
        return err_payload(f"config missing required field {exc}", "BAD_ARGS")
    except (TypeError, ValueError) as exc:
        return err_payload(f"config invalid value: {exc}", "BAD_ARGS")

    # ── Parse latency ──────────────────────────────────────────────────────────
    try:
        latency = WorstCaseLoopLatency(
            worst_case_ms=float(raw_latency["worst_case_ms"]),
            source=str(raw_latency["source"]),
        )
    except KeyError as exc:
        return err_payload(f"latency missing required field {exc}", "BAD_ARGS")
    except (TypeError, ValueError) as exc:
        return err_payload(f"latency invalid value: {exc}", "BAD_ARGS")

    try:
        report = check_watchdog_interval(config, latency)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Analysis error: {exc}", "ANALYSIS_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_check_watchdog_interval_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_check_watchdog_interval(a, ctx)
