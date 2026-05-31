"""LLM tool: firmware_verify_spi_timing — SPI master/slave timing verifier.

Given an MCU SPI master configuration and a slave device datasheet spec, checks
whether the master's clock rate, setup time, hold time, and clock mode (CPOL/CPHA)
are compatible with the slave's requirements.

References
----------
  Motorola SPI Bus Specification — canonical CPOL/CPHA definition.
  ARM Cortex-M Generic User Guide (ARM DUI 0553B) §SPI Timing.
  Microchip MCP3008 datasheet DS21295D §1.0 — AC electrical characteristics.
  STM32F411 Reference Manual (RM0383 Rev 3) §28.3 — SPI timing.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.spi_timing_verify import (
    SpiMasterConfig,
    SpiSlaveSpec,
    verify_spi_timing,
)


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_verify_spi_timing",
    description=(
        "Verify SPI bus timing compatibility between an MCU master and a slave "
        "device using the Motorola SPI specification (canonical CPOL/CPHA reference) "
        "and ARM Cortex-M Generic UG §SPI Timing.\n\n"
        "Checks performed:\n"
        "  1. Clock rate: master clock_hz <= slave max_clk_hz.\n"
        "  2. Setup time: master setup_ns >= slave min_setup_ns.\n"
        "  3. Hold time: master hold_ns >= slave min_hold_ns.\n"
        "  4. CPOL exact match: master cpol == slave cpol_required.\n"
        "  5. CPHA exact match: master cpha == slave cpha_required.\n\n"
        "CPOL/CPHA modes (Motorola SPI spec):\n"
        "  Mode 0: CPOL=0, CPHA=0 — idle LOW, sample on rising edge.\n"
        "  Mode 1: CPOL=0, CPHA=1 — idle LOW, sample on falling edge.\n"
        "  Mode 2: CPOL=1, CPHA=0 — idle HIGH, sample on falling edge.\n"
        "  Mode 3: CPOL=1, CPHA=1 — idle HIGH, sample on rising edge.\n\n"
        "Depth-bar oracle — MCP3008 ADC @ 1.35 MHz max, Mode 0 (CPOL=0, CPHA=0), "
        "min_setup=50 ns, min_hold=50 ns; STM32F411 SPI1 @ 1 MHz, "
        "setup=10 ns, hold=10 ns: compatible=True (clock OK, but setup/hold "
        "margins are tight — real-PCB trace delay will consume these margins fast).\n\n"
        "NOTE: assumes ideal square-wave signals; ignores PCB trace propagation "
        "delay and crosstalk. Always verify on target hardware with a logic analyser."
    ),
    input_schema={
        "type": "object",
        "required": ["master", "slave"],
        "properties": {
            "master": {
                "type": "object",
                "description": "SPI master (MCU) configuration.",
                "required": ["clock_hz", "cpol", "cpha", "setup_ns", "hold_ns", "mcu_label"],
                "properties": {
                    "clock_hz": {
                        "type": "integer",
                        "description": (
                            "SPI clock frequency programmed into the MCU peripheral, in Hz. "
                            "E.g. 1000000 for 1 MHz."
                        ),
                        "minimum": 1,
                    },
                    "cpol": {
                        "type": "integer",
                        "description": (
                            "Clock polarity. 0 = clock idles LOW; "
                            "1 = clock idles HIGH (Motorola SPI spec)."
                        ),
                        "enum": [0, 1],
                    },
                    "cpha": {
                        "type": "integer",
                        "description": (
                            "Clock phase. 0 = data sampled on leading edge; "
                            "1 = data sampled on trailing edge (Motorola SPI spec)."
                        ),
                        "enum": [0, 1],
                    },
                    "setup_ns": {
                        "type": "number",
                        "description": (
                            "Data setup time the master guarantees before the sampling "
                            "clock edge, in nanoseconds. From MCU SPI AC electrical "
                            "characteristics table (e.g. RM0383 §28.3 for STM32F411)."
                        ),
                        "minimum": 0,
                    },
                    "hold_ns": {
                        "type": "number",
                        "description": (
                            "Data hold time the master guarantees after the sampling "
                            "clock edge, in nanoseconds. From MCU SPI AC electrical "
                            "characteristics table."
                        ),
                        "minimum": 0,
                    },
                    "mcu_label": {
                        "type": "string",
                        "description": (
                            "Human-readable MCU identifier, e.g. "
                            "'STM32F411CE @ 1 MHz SPI1' or 'ATmega328P @ 4 MHz SPI'."
                        ),
                    },
                },
            },
            "slave": {
                "type": "object",
                "description": "SPI slave device timing requirements from the datasheet.",
                "required": [
                    "device_label",
                    "max_clk_hz",
                    "min_setup_ns",
                    "min_hold_ns",
                    "cpol_required",
                    "cpha_required",
                ],
                "properties": {
                    "device_label": {
                        "type": "string",
                        "description": (
                            "Human-readable device identifier, e.g. "
                            "'MCP3008 ADC' or 'MFRC522 RFID'."
                        ),
                    },
                    "max_clk_hz": {
                        "type": "integer",
                        "description": (
                            "Maximum SPI clock frequency accepted by the slave, in Hz. "
                            "From device datasheet AC electrical characteristics. "
                            "E.g. 1350000 (1.35 MHz) for MCP3008 at 2.7 V supply "
                            "(DS21295D §1.0 Table 1-1)."
                        ),
                        "minimum": 1,
                    },
                    "min_setup_ns": {
                        "type": "number",
                        "description": (
                            "Minimum data setup time required by the slave, in nanoseconds "
                            "(t_su in the datasheet timing diagram). "
                            "The master must present stable MOSI at least this many ns "
                            "before the sampling clock edge."
                        ),
                        "minimum": 0,
                    },
                    "min_hold_ns": {
                        "type": "number",
                        "description": (
                            "Minimum data hold time required by the slave, in nanoseconds "
                            "(t_h in the datasheet timing diagram). "
                            "MOSI must remain stable for at least this many ns after the "
                            "sampling clock edge."
                        ),
                        "minimum": 0,
                    },
                    "cpol_required": {
                        "type": "integer",
                        "description": (
                            "Required CPOL value for this slave (0 or 1). "
                            "From device datasheet SPI mode table."
                        ),
                        "enum": [0, 1],
                    },
                    "cpha_required": {
                        "type": "integer",
                        "description": (
                            "Required CPHA value for this slave (0 or 1). "
                            "From device datasheet SPI mode table."
                        ),
                        "enum": [0, 1],
                    },
                },
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_verify_spi_timing(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute SPI timing verification and return a JSON payload."""
    raw_master = args.get("master")
    raw_slave = args.get("slave")

    if not isinstance(raw_master, dict):
        return err_payload("'master' is required and must be a JSON object", "BAD_ARGS")
    if not isinstance(raw_slave, dict):
        return err_payload("'slave' is required and must be a JSON object", "BAD_ARGS")

    # ── Parse master ──────────────────────────────────────────────────────────
    try:
        master = SpiMasterConfig(
            clock_hz=int(raw_master["clock_hz"]),
            cpol=int(raw_master["cpol"]),
            cpha=int(raw_master["cpha"]),
            setup_ns=float(raw_master["setup_ns"]),
            hold_ns=float(raw_master["hold_ns"]),
            mcu_label=str(raw_master["mcu_label"]),
        )
    except KeyError as exc:
        return err_payload(f"master missing required field {exc}", "BAD_ARGS")
    except (TypeError, ValueError) as exc:
        return err_payload(f"master invalid value: {exc}", "BAD_ARGS")

    # ── Parse slave ───────────────────────────────────────────────────────────
    try:
        slave = SpiSlaveSpec(
            device_label=str(raw_slave["device_label"]),
            max_clk_hz=int(raw_slave["max_clk_hz"]),
            min_setup_ns=float(raw_slave["min_setup_ns"]),
            min_hold_ns=float(raw_slave["min_hold_ns"]),
            cpol_required=int(raw_slave["cpol_required"]),
            cpha_required=int(raw_slave["cpha_required"]),
        )
    except KeyError as exc:
        return err_payload(f"slave missing required field {exc}", "BAD_ARGS")
    except (TypeError, ValueError) as exc:
        return err_payload(f"slave invalid value: {exc}", "BAD_ARGS")

    try:
        report = verify_spi_timing(master, slave)
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Verification error: {exc}", "VERIFY_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_verify_spi_timing_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_verify_spi_timing(a, ctx)
