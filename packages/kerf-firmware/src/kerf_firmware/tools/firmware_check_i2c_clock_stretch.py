"""LLM tool: firmware_check_i2c_clock_stretch — I²C clock-stretch analyser.

Computes the worst-case effective I²C bus speed when one or more slave devices
exercise SCL clock stretching, and verifies that the master's SCL low-timeout
does not violate the I²C-bus specification.

References
----------
  NXP UM10204 Rev 7 §3.1.9 — Clock stretching.
  ARM Cortex-M Generic User Guide (ARM DUI 0553B) §I2C Timing.
  STM32F411 Reference Manual (RM0383 Rev 3) §26.6 — I2C TIMEOUTB register.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.i2c_clock_stretch_check import (
    I2CMasterConfig,
    I2CSlaveSpec,
    check_i2c_clock_stretch,
)


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_check_i2c_clock_stretch",
    description=(
        "Compute worst-case effective I²C bus speed when one or more slave devices "
        "exercise SCL clock stretching, and verify the MCU SCL low-timeout does not "
        "exceed the configured threshold.\n\n"
        "Algorithm (NXP UM10204 Rev 7 §3.1.9 — Clock stretching):\n"
        "  t_byte_nominal = 9 / nominal_clock_hz  (9 SCL pulses per byte: "
        "8 data bits + 1 ACK/NACK)\n"
        "  worst_stretch = max(slave.max_stretch_per_byte_us) across all slaves\n"
        "  t_byte_effective = t_byte_nominal + worst_stretch_us / 1e6\n"
        "  effective_clock_hz = 9 / t_byte_effective\n"
        "  timeout_compliant = (worst_stretch_us * bytes_per_txn) < "
        "scl_low_timeout_ms * 1000\n\n"
        "Depth-bar oracle — STM32F411 I2C1 at 400 kHz, SHT31 with 50 µs/byte "
        "stretch, timeout=25 ms:\n"
        "  t_nominal=22.5 µs; t_effective=72.5 µs; "
        "effective_clock≈124.1 kHz; cumulative for 8 bytes=400 µs < 25000 µs → "
        "timeout_compliant=True.\n\n"
        "NOTE: assumes synchronous single-master bus. Multi-master arbitration is "
        "NOT modelled. Stretch is assumed on every byte; rise/fall derating and "
        "inter-byte t_BUF overhead are not included."
    ),
    input_schema={
        "type": "object",
        "required": ["master", "slaves"],
        "properties": {
            "master": {
                "type": "object",
                "description": "I²C master (MCU) configuration.",
                "required": ["nominal_clock_hz", "scl_low_timeout_ms", "mcu_label"],
                "properties": {
                    "nominal_clock_hz": {
                        "type": "integer",
                        "description": (
                            "I²C SCL clock frequency in Hz. "
                            "Standard Mode: 100000; Fast Mode: 400000; "
                            "Fast-Mode Plus: 1000000."
                        ),
                        "minimum": 1,
                    },
                    "scl_low_timeout_ms": {
                        "type": "number",
                        "description": (
                            "SCL low-timeout threshold in milliseconds (RM0383 §26.6 "
                            "TIMEOUTB register or equivalent). Set 0.0 to disable "
                            "timeout compliance checking."
                        ),
                        "minimum": 0,
                    },
                    "mcu_label": {
                        "type": "string",
                        "description": (
                            "Human-readable MCU identifier, e.g. "
                            "'STM32F411CE I2C1 @ 400 kHz'."
                        ),
                    },
                },
            },
            "slaves": {
                "type": "array",
                "description": (
                    "List of I²C slave device specifications on this bus segment. "
                    "May be empty (no slaves → no stretching, effective = nominal)."
                ),
                "items": {
                    "type": "object",
                    "required": [
                        "device_label",
                        "address",
                        "max_stretch_per_byte_us",
                        "supports_stretching",
                    ],
                    "properties": {
                        "device_label": {
                            "type": "string",
                            "description": (
                                "Human-readable device identifier, e.g. "
                                "'SHT31 humidity sensor' or 'BNO055 IMU'."
                            ),
                        },
                        "address": {
                            "type": "integer",
                            "description": (
                                "7-bit I²C slave address (0x00–0x7F). "
                                "E.g. 0x44 for SHT31 default address."
                            ),
                            "minimum": 0,
                            "maximum": 127,
                        },
                        "max_stretch_per_byte_us": {
                            "type": "number",
                            "description": (
                                "Maximum clock-stretch duration the slave may assert "
                                "per byte, in microseconds. From device datasheet "
                                "SCL low-extension timing parameter. 0.0 for no stretch."
                            ),
                            "minimum": 0,
                        },
                        "supports_stretching": {
                            "type": "boolean",
                            "description": (
                                "True if this slave can hold SCL LOW (clock stretching). "
                                "False for slaves that never stretch."
                            ),
                        },
                    },
                },
            },
            "bytes_per_transaction": {
                "type": "integer",
                "description": (
                    "Number of data bytes per I²C transaction, used to compute "
                    "cumulative stretch for timeout compliance. Default: 8."
                ),
                "minimum": 1,
                "default": 8,
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_check_i2c_clock_stretch(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute I²C clock-stretch analysis and return a JSON payload."""
    raw_master = args.get("master")
    raw_slaves = args.get("slaves")

    if not isinstance(raw_master, dict):
        return err_payload("'master' is required and must be a JSON object", "BAD_ARGS")
    if not isinstance(raw_slaves, list):
        return err_payload("'slaves' is required and must be a JSON array", "BAD_ARGS")

    bytes_per_txn = args.get("bytes_per_transaction", 8)
    try:
        bytes_per_txn = int(bytes_per_txn)
        if bytes_per_txn < 1:
            raise ValueError("bytes_per_transaction must be >= 1")
    except (TypeError, ValueError) as exc:
        return err_payload(f"bytes_per_transaction invalid: {exc}", "BAD_ARGS")

    # ── Parse master ──────────────────────────────────────────────────────────
    try:
        master = I2CMasterConfig(
            nominal_clock_hz=int(raw_master["nominal_clock_hz"]),
            scl_low_timeout_ms=float(raw_master["scl_low_timeout_ms"]),
            mcu_label=str(raw_master["mcu_label"]),
        )
    except KeyError as exc:
        return err_payload(f"master missing required field {exc}", "BAD_ARGS")
    except (TypeError, ValueError) as exc:
        return err_payload(f"master invalid value: {exc}", "BAD_ARGS")

    # ── Parse slaves ──────────────────────────────────────────────────────────
    slaves = []
    for i, raw_slave in enumerate(raw_slaves):
        if not isinstance(raw_slave, dict):
            return err_payload(
                f"slaves[{i}] must be a JSON object, got {type(raw_slave).__name__}",
                "BAD_ARGS",
            )
        try:
            slave = I2CSlaveSpec(
                device_label=str(raw_slave["device_label"]),
                address=int(raw_slave["address"]),
                max_stretch_per_byte_us=float(raw_slave["max_stretch_per_byte_us"]),
                supports_stretching=bool(raw_slave["supports_stretching"]),
            )
        except KeyError as exc:
            return err_payload(f"slaves[{i}] missing required field {exc}", "BAD_ARGS")
        except (TypeError, ValueError) as exc:
            return err_payload(f"slaves[{i}] invalid value: {exc}", "BAD_ARGS")
        slaves.append(slave)

    try:
        report = check_i2c_clock_stretch(master, slaves, bytes_per_transaction=bytes_per_txn)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Analysis error: {exc}", "ANALYSIS_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_check_i2c_clock_stretch_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_check_i2c_clock_stretch(a, ctx)
