"""LLM tool: firmware_verify_clock_tree — verify MCU clock-tree configuration.

Verifies an STM32 clock-tree configuration: HSE/HSI source, PLL multipliers +
dividers, SYSCLK, AHB/APB1/APB2 prescalers, and derived peripheral clocks.

HONEST DISCLAIMER
-----------------
This verifier is lookup-table-based (RM0383/RM0090 constraint tables embedded
in ``clock_tree_specs.py``).  It does NOT model PLL phase noise, cycle-to-cycle
jitter, or temperature/voltage derating.  Always confirm timing-sensitive
designs (USB HS, SDIO, camera IF) with STM32CubeMX RCC configurator.

Supported chips
---------------
  "STM32F411" / "stm32f411" / "stm32f411ce" / "stm32f411re" / "stm32f411ve"
  "STM32F407" / "stm32f407" / "stm32f407vg" / "stm32f407ig"

References
----------
  RM0383 Rev 3 §6 — STM32F411 Reset and clock control.
  RM0090 Rev 19 §6 — STM32F407 Reset and clock control.
"""
from __future__ import annotations

import json
from typing import Any

try:
    from kerf_chat.tools.registry import ToolSpec, register, ok_payload, err_payload
except ImportError:
    from kerf_firmware._compat import ToolSpec, register, ok_payload, err_payload  # type: ignore

from kerf_firmware.clock_tree_verify import ClockConfig, verify_clock_tree


# ── Tool specification ─────────────────────────────────────────────────────────

_spec = ToolSpec(
    name="firmware_verify_clock_tree",
    description=(
        "Verify an STM32 microcontroller clock-tree configuration. "
        "Checks: PLL VCO input frequency (1–2 MHz), VCO output range "
        "(100–432 MHz), SYSCLK maximum (100 MHz for STM32F411; "
        "168 MHz for STM32F407), APB1 ≤ 42 MHz, APB2 ≤ 84 MHz, "
        "USB_OTG_FS exactly 48 MHz (±500 ppm), ADC ≤ 36 MHz. "
        "Performs real PLL arithmetic: "
        "VCO = (HSE/PLLM) × PLLN; SYSCLK = VCO/PLLP; USB = VCO/PLLQ. "
        "Supported chips: STM32F411, STM32F407. "
        "NOTE: lookup-table-based; no jitter/phase-noise model."
    ),
    input_schema={
        "type": "object",
        "required": ["chip", "config"],
        "properties": {
            "chip": {
                "type": "string",
                "description": (
                    "Chip family. One of: 'STM32F411', 'STM32F407', "
                    "or aliases 'stm32f411', 'stm32f411ce', 'stm32f411re', "
                    "'stm32f407', 'stm32f407vg'."
                ),
            },
            "config": {
                "type": "object",
                "description": "Clock-tree configuration dict.",
                "required": [],
                "properties": {
                    "source": {
                        "type": "string",
                        "description": (
                            "Clock source: 'HSE' (crystal), 'HSE_BYPASS' "
                            "(external clock), or 'HSI' (internal 16 MHz RC). "
                            "Default: 'HSE'."
                        ),
                        "default": "HSE",
                    },
                    "hse_hz": {
                        "type": "integer",
                        "description": (
                            "HSE crystal/clock frequency in Hz. "
                            "Common values: 8000000 (8 MHz), 12000000, "
                            "16000000, 25000000. Only used when source='HSE'."
                        ),
                        "default": 8000000,
                    },
                    "pll_m": {
                        "type": "integer",
                        "description": (
                            "PLLM divider (2–63). Divides HSE/HSI before VCO. "
                            "Target fHSx/PLLM = 1–2 MHz. "
                            "For HSE=8 MHz, PLLM=8 → 1 MHz input."
                        ),
                        "default": 8,
                    },
                    "pll_n": {
                        "type": "integer",
                        "description": (
                            "PLLN multiplier (2–432). VCO = (fHSx/PLLM) × PLLN."
                        ),
                        "default": 192,
                    },
                    "pll_p": {
                        "type": "integer",
                        "description": (
                            "PLLP divider: 2, 4, 6, or 8. "
                            "SYSCLK = VCO / PLLP."
                        ),
                        "default": 4,
                    },
                    "pll_q": {
                        "type": "integer",
                        "description": (
                            "PLLQ divider (2–15). USB/SDIO clock = VCO / PLLQ. "
                            "Set to 0 to skip USB clock check."
                        ),
                        "default": 8,
                    },
                    "hpre": {
                        "type": "integer",
                        "description": (
                            "AHB prescaler. One of: 1, 2, 4, 8, 16, 64, 128, 256, 512."
                        ),
                        "default": 1,
                    },
                    "ppre1": {
                        "type": "integer",
                        "description": (
                            "APB1 prescaler. One of: 1, 2, 4, 8, 16. Max APB1 = 42 MHz."
                        ),
                        "default": 4,
                    },
                    "ppre2": {
                        "type": "integer",
                        "description": (
                            "APB2 prescaler. One of: 1, 2, 4, 8, 16. Max APB2 = 84 MHz."
                        ),
                        "default": 2,
                    },
                    "use_pll": {
                        "type": "boolean",
                        "description": "If false, SYSCLK driven by source directly. Default: true.",
                        "default": True,
                    },
                    "peripheral_clocks": {
                        "type": "object",
                        "description": (
                            "Optional {peripheral_name: frequency_hz} overrides. "
                            "Keys: 'ADC', 'SPI1', 'SPI2', 'I2C1', 'SDIO', etc."
                        ),
                        "additionalProperties": {"type": "integer"},
                        "default": {},
                    },
                },
            },
        },
    },
)


# ── Tool handler ───────────────────────────────────────────────────────────────

@register(_spec)
def run_firmware_verify_clock_tree(
    args: dict[str, Any], ctx: object | None = None
) -> str:
    """Execute clock-tree verification and return a JSON payload."""
    chip = args.get("chip", "")
    config_dict = args.get("config")

    if not chip:
        return err_payload("'chip' is required", "BAD_ARGS")
    if config_dict is None:
        return err_payload("'config' is required", "BAD_ARGS")
    if not isinstance(config_dict, dict):
        return err_payload("'config' must be a JSON object", "BAD_ARGS")

    try:
        clock_cfg = ClockConfig(
            source=config_dict.get("source", "HSE"),
            hse_hz=int(config_dict.get("hse_hz", 8_000_000)),
            pll_m=int(config_dict.get("pll_m", 8)),
            pll_n=int(config_dict.get("pll_n", 192)),
            pll_p=int(config_dict.get("pll_p", 4)),
            pll_q=int(config_dict.get("pll_q", 8)),
            hpre=int(config_dict.get("hpre", 1)),
            ppre1=int(config_dict.get("ppre1", 4)),
            ppre2=int(config_dict.get("ppre2", 2)),
            peripheral_clocks={
                k: int(v) for k, v in
                (config_dict.get("peripheral_clocks") or {}).items()
            },
            use_pll=bool(config_dict.get("use_pll", True)),
        )
    except (TypeError, ValueError) as exc:
        return err_payload(f"Invalid config value: {exc}", "BAD_ARGS")

    try:
        report = verify_clock_tree(chip, clock_cfg)
    except KeyError as exc:
        return err_payload(str(exc), "UNKNOWN_CHIP")
    except Exception as exc:  # noqa: BLE001
        return err_payload(f"Verification error: {exc}", "VERIFY_ERROR")

    return ok_payload(report.as_dict())


# ── Async wrapper for plugin registration ─────────────────────────────────────

async def run_firmware_verify_clock_tree_async(ctx: object, args: bytes) -> str:
    """Async wrapper used by plugin.py's ctx.tools.register()."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")
    return run_firmware_verify_clock_tree(a, ctx)
