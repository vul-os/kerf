"""LLM tool: firmware_compute_flash_wear — MCU flash endurance / wear-level estimator.

Given an MCU flash sector layout, write rate, and EEPROM-like wear-leveling
parameters (N sectors), estimates flash endurance and time-to-failure for the
given write workload.

References
----------
  STM32F411 RM0383 Rev 4 §3 (Embedded Flash Memory): 10,000 erase cycle
    endurance per sector at Tj = −40 to +85 °C.
  AVR ATmega328P §11 (EEPROM): 100,000 erase/write cycles at 5 V, 25 °C.
  JEDEC JESD47 §9 — Flash memory endurance test standard.
  Micron AN-1015 — NAND Flash Wear-Leveling.
"""
from __future__ import annotations

import json
import math
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.flash_wear_level import (
    FlashSpec,
    WriteWorkload,
    compute_flash_wear,
)


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_compute_flash_wear",
    description=(
        "Estimate MCU flash / EEPROM endurance and time-to-failure for a given "
        "write workload and wear-leveling configuration.  Returns "
        "expected_cycles_per_sector, time_to_failure_years, adequate (bool), "
        "recommended_wear_level_sectors, write_amplification, and an honest caveat.\n\n"
        "Model: total_writes = writes_per_second × 31,557,600 (s/yr) × lifetime_years; "
        "sector_erase_events = ceil(total_writes / ceil(sector_size / bytes_per_write)); "
        "cycles_per_sector = sector_erase_events / num_sectors_for_wear_level; "
        "adequate = cycles_per_sector ≤ endurance_cycles.\n\n"
        "Depth-bar oracle examples:\n"
        "  STM32F411 (10k cycles, 128 KB sector), 1 sector, 1 write/s, 10 yr: "
        "cycles ≈ 3.15e8 → INADEQUATE (need ~31,558 sectors).\n"
        "  Same with 100 sectors: cycles ≈ 3.15e6 → still INADEQUATE.\n"
        "  ATmega328P EEPROM (100k cycles, 1-byte sector), 1 sector, 0.01 write/s, 10 yr: "
        "cycles ≈ 3,155 → ADEQUATE.\n\n"
        "HONEST CAVEATS: assumes perfect uniform wear distribution; real algorithms "
        "(NuttX MTD, Zephyr NVS) achieve ~80–90% of ideal.  "
        "STM32F411 RM0383 §3: 10,000 cycles at Tj = −40 to +85°C; "
        "ATmega328P §11: 100,000 cycles at 5 V, 25°C."
    ),
    input_schema={
        "type": "object",
        "required": [
            "mcu_label",
            "sector_size_bytes",
            "endurance_cycles",
            "num_sectors_for_wear_level",
            "bytes_per_write",
            "writes_per_second",
            "expected_lifetime_years",
        ],
        "properties": {
            "mcu_label": {
                "type": "string",
                "description": (
                    "Human-readable MCU or memory identifier, e.g. "
                    "'STM32F411CEU6' or 'ATmega328P-EEPROM'."
                ),
            },
            "sector_size_bytes": {
                "type": "integer",
                "description": (
                    "Size of one erasable sector or page in bytes.  "
                    "STM32F411 internal flash: 16384 (16 KB) for small sectors, "
                    "131072 (128 KB) for large sectors (RM0383 §3).  "
                    "ATmega328P EEPROM: 1 (byte-addressable, §11)."
                ),
                "minimum": 1,
                "examples": [1, 16384, 65536, 131072],
            },
            "endurance_cycles": {
                "type": "integer",
                "description": (
                    "Manufacturer-rated erase/write cycles per sector.  "
                    "STM32F411 internal flash: 10000 (RM0383 §3 Table 6).  "
                    "ATmega328P EEPROM: 100000 (§11).  "
                    "NOR flash typical: 10000–100000.  "
                    "NAND flash typical: 1000–100000."
                ),
                "minimum": 1,
                "examples": [10000, 100000],
            },
            "num_sectors_for_wear_level": {
                "type": "integer",
                "description": (
                    "Number of sectors used by the wear-leveling pool.  "
                    "1 = no leveling (all writes hit the same sector — worst case).  "
                    "2 = classic two-sector EEPROM emulation (ST AN2594).  "
                    "Larger values spread wear over more flash, extending life "
                    "proportionally under perfect uniform distribution."
                ),
                "minimum": 1,
                "examples": [1, 2, 4, 8, 16, 32, 100],
            },
            "bytes_per_write": {
                "type": "integer",
                "description": (
                    "Bytes written per logical write operation.  "
                    "For EEPROM byte writes: 1–4.  "
                    "For full-sector-erase flash writes: equal to sector_size_bytes.  "
                    "For small NVS records: 8–256.  "
                    "Affects write amplification: smaller writes relative to sector "
                    "size → more logical writes needed to fill a sector → lower WA."
                ),
                "minimum": 1,
            },
            "writes_per_second": {
                "type": "number",
                "description": (
                    "Average logical write operations per second.  "
                    "0.01 = one write every 100 s (e.g. periodic sensor calibration).  "
                    "1.0 = one write per second.  "
                    "10.0 = ten writes per second (e.g. data logger).  "
                    "Must be ≥ 0; a value of 0 means no writes and infinite lifetime."
                ),
                "minimum": 0,
                "examples": [0.01, 0.1, 1.0, 10.0, 100.0],
            },
            "expected_lifetime_years": {
                "type": "number",
                "description": (
                    "Target device lifetime in years over which flash wear is assessed.  "
                    "Consumer electronics: 3–5.  Industrial IoT: 10.  Infrastructure: 20–25."
                ),
                "exclusiveMinimum": 0,
                "examples": [3.0, 5.0, 10.0, 20.0],
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_compute_flash_wear(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute flash wear computation and return a JSON payload."""
    # Validate required fields
    required = [
        "mcu_label", "sector_size_bytes", "endurance_cycles",
        "num_sectors_for_wear_level", "bytes_per_write",
        "writes_per_second", "expected_lifetime_years",
    ]
    for field in required:
        if field not in args:
            return err_payload(f"'{field}' is required", "BAD_ARGS")

    # Parse and validate each field
    mcu_label = args.get("mcu_label")
    if not isinstance(mcu_label, str) or not mcu_label.strip():
        return err_payload("'mcu_label' must be a non-empty string", "BAD_ARGS")

    try:
        sector_size_bytes = int(args["sector_size_bytes"])
    except (TypeError, ValueError) as exc:
        return err_payload(f"'sector_size_bytes' must be an integer: {exc}", "BAD_ARGS")

    try:
        endurance_cycles = int(args["endurance_cycles"])
    except (TypeError, ValueError) as exc:
        return err_payload(f"'endurance_cycles' must be an integer: {exc}", "BAD_ARGS")

    try:
        num_sectors = int(args["num_sectors_for_wear_level"])
    except (TypeError, ValueError) as exc:
        return err_payload(
            f"'num_sectors_for_wear_level' must be an integer: {exc}", "BAD_ARGS"
        )

    try:
        bytes_per_write = int(args["bytes_per_write"])
    except (TypeError, ValueError) as exc:
        return err_payload(f"'bytes_per_write' must be an integer: {exc}", "BAD_ARGS")

    try:
        writes_per_second = float(args["writes_per_second"])
    except (TypeError, ValueError) as exc:
        return err_payload(f"'writes_per_second' must be a number: {exc}", "BAD_ARGS")

    try:
        lifetime_years = float(args["expected_lifetime_years"])
    except (TypeError, ValueError) as exc:
        return err_payload(f"'expected_lifetime_years' must be a number: {exc}", "BAD_ARGS")

    # Construct spec and workload (validation happens in __post_init__)
    try:
        spec = FlashSpec(
            mcu_label=mcu_label,
            sector_size_bytes=sector_size_bytes,
            endurance_cycles=endurance_cycles,
            num_sectors_for_wear_level=num_sectors,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    try:
        workload = WriteWorkload(
            bytes_per_write=bytes_per_write,
            writes_per_second=writes_per_second,
            expected_lifetime_years=lifetime_years,
        )
    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")

    try:
        report = compute_flash_wear(spec, workload)
    except (ValueError, ZeroDivisionError) as exc:
        return err_payload(f"Computation error: {exc}", "BAD_ARGS")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Unexpected error: {exc}", "COMPUTE_ERROR")

    # Serialise (handle inf for zero-write-rate case)
    ttf = report.time_to_failure_years
    ttf_serialised = None if math.isinf(ttf) else round(ttf, 4)

    return ok_payload({
        "mcu_label": mcu_label,
        "sector_size_bytes": sector_size_bytes,
        "endurance_cycles": endurance_cycles,
        "num_sectors_for_wear_level": num_sectors,
        "bytes_per_write": bytes_per_write,
        "writes_per_second": writes_per_second,
        "expected_lifetime_years": lifetime_years,
        "expected_cycles_per_sector": round(report.expected_cycles_per_sector, 2),
        "time_to_failure_years": ttf_serialised,
        "adequate": report.adequate,
        "recommended_wear_level_sectors": report.recommended_wear_level_sectors,
        "write_amplification": round(report.write_amplification, 2),
        "honest_caveat": report.honest_caveat,
    })


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_compute_flash_wear_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_compute_flash_wear(a, ctx)
