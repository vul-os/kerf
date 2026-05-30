"""Embedded clock-tree constraint tables for STM32 microcontrollers.

Sources
-------
STM32F411  — Reference Manual RM0383 Rev 3, §6 "Reset and clock control (RCC)"
             Table 13 "PLL characteristics" and Table 15 "Clock tree constraints".
             Maximum frequencies from DS10086 Rev 7, §5.3.2 "Clock timing
             characteristics" and Table 10 "General operating conditions".

STM32F407  — Reference Manual RM0090 Rev 19, §6 "Reset and clock control".
             Maximum frequencies from DS8626 Rev 11, §5.3.2.

Limitation
----------
These are lookup-table-based constraints only.  No analytic PLL phase-noise
model or jitter estimation is included.  Phase noise / cycle-to-cycle jitter
calculations require silicon characterisation data (RM0383 Table 13 gives typical
figures but no statistical model); this verifier CANNOT compute jitter budgets.
Always cross-check timing-sensitive designs (e.g. USB HS, SDIO, camera interface)
against the vendor's clock-analysis tools (STM32CubeIDE / STM32CubeMX RCC
configurator).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PeripheralClockConstraint:
    """Operating-frequency constraint for one peripheral clock domain.

    Parameters
    ----------
    peripheral:
        Human-readable peripheral name, e.g. ``"USB_OTG_FS"``.
    min_hz:
        Minimum acceptable clock frequency in Hz (0 = no lower bound).
    max_hz:
        Maximum acceptable clock frequency in Hz.
    exact_hz:
        If not ``None``, the peripheral requires this *exact* frequency
        (tolerance ``±tolerance_ppm`` ppm).  Used for USB 48 MHz.
    tolerance_ppm:
        Acceptable deviation from ``exact_hz`` in parts-per-million.
        Default is 500 ppm (±0.05 %), per USB 2.0 spec §7.1.11.
    note:
        Free-text note citing the datasheet clause.
    """
    peripheral: str
    min_hz: int
    max_hz: int
    exact_hz: Optional[int] = None
    tolerance_ppm: int = 500
    note: str = ""


@dataclass(frozen=True)
class ClockTreeSpec:
    """Complete clock-tree constraints for one chip family.

    Parameters
    ----------
    chip_family:
        Short identifier, e.g. ``"STM32F411"``.
    hse_min_hz / hse_max_hz:
        HSE oscillator input range (RM0383 §6.3.1, Table 13).
    hsi_hz:
        HSI internal RC frequency (nominally 16 MHz on STM32F4, ±1 %).
    lse_hz:
        LSE crystal frequency (32.768 kHz standard).
    lsi_hz:
        LSI internal RC frequency (typically 32 kHz, not calibrated).
    pll_vco_min_hz / pll_vco_max_hz:
        Main PLL VCO output frequency range (RM0383 §6.3.2 Table 13:
        100 MHz ≤ fVCO ≤ 432 MHz per RM0383 Rev 3 Table 13 footnote 1).
    pll_input_min_hz / pll_input_max_hz:
        VCO *input* frequency constraints (fHSx / PLLM).
    sysclk_max_hz:
        Maximum SYSCLK (RM0383 §6.2, Table 10: 100 MHz for STM32F411,
        168 MHz for STM32F407).
    ahb_max_hz:
        Maximum AHB bus clock (= SYSCLK / HPRE).
    apb1_max_hz:
        Maximum APB1 peripheral clock (42 MHz for STM32F411, RM0383 §6.2).
    apb2_max_hz:
        Maximum APB2 peripheral clock (84 MHz for STM32F411, RM0383 §6.2).
    peripheral_constraints:
        Per-peripheral clock constraints, keyed by a canonical name.
    """
    chip_family: str
    hse_min_hz: int
    hse_max_hz: int
    hsi_hz: int
    lse_hz: int
    lsi_hz: int
    pll_vco_min_hz: int
    pll_vco_max_hz: int
    pll_input_min_hz: int
    pll_input_max_hz: int
    sysclk_max_hz: int
    ahb_max_hz: int
    apb1_max_hz: int
    apb2_max_hz: int
    peripheral_constraints: Dict[str, PeripheralClockConstraint] = field(
        default_factory=dict
    )


# ──────────────────────────────────────────────────────────────────────────────
# STM32F411 — RM0383 Rev 3 §6
# ──────────────────────────────────────────────────────────────────────────────
#
# Key values (all from RM0383 Rev 3, §6 and DS10086 Rev 7):
#   SYSCLK max          : 100 MHz   (DS10086 §5.3.2 Table 10)
#   AHB max             : 100 MHz   (= SYSCLK / HPRE; HPRE ≥ 1)
#   APB1 max            :  42 MHz   (RM0383 §6.2 note 1)
#   APB2 max            :  84 MHz   (RM0383 §6.2 note 1)
#   PLL VCO range       : 100–432 MHz (RM0383 Table 13, footnote 1)
#   PLL VCO input range :   1–2 MHz  (RM0383 Table 13)
#   HSE range           :   4–26 MHz (RM0383 §6.3.1, Table 13)
#   HSI                 :  16 MHz
#   USB_OTG_FS requires : exactly 48 MHz (USB 2.0 §7.1.11; PLLQ output)
#   ADC max             :  36 MHz   (RM0383 §13.3.1)

_F411_PERIPHERAL_CONSTRAINTS: Dict[str, PeripheralClockConstraint] = {
    "USB_OTG_FS": PeripheralClockConstraint(
        peripheral="USB_OTG_FS",
        min_hz=48_000_000,
        max_hz=48_000_000,
        exact_hz=48_000_000,
        tolerance_ppm=500,
        note=(
            "USB_OTG_FS requires exactly 48 MHz on the PLLQ output "
            "(USB 2.0 §7.1.11; RM0383 §6.3.3 RCC_PLLCFGR PLLQ field). "
            "Tolerance ±500 ppm per USB 2.0 spec."
        ),
    ),
    "ADC": PeripheralClockConstraint(
        peripheral="ADC",
        min_hz=0,
        max_hz=36_000_000,
        note=(
            "ADC clock (PCLK2 divided by ADC prescaler 2/4/6/8) must not "
            "exceed 36 MHz (RM0383 §13.3.1 ADC characteristics; "
            "DS10086 Table 68)."
        ),
    ),
    "SPI1": PeripheralClockConstraint(
        peripheral="SPI1",
        min_hz=0,
        max_hz=50_000_000,
        note="SPI1 on APB2; max SCK = fPCLK2/2; fPCLK2 ≤ 84 MHz → max 42 MHz.",
    ),
    "SPI2": PeripheralClockConstraint(
        peripheral="SPI2",
        min_hz=0,
        max_hz=25_000_000,
        note="SPI2/3 on APB1; max SCK = fPCLK1/2; fPCLK1 ≤ 42 MHz → max 21 MHz.",
    ),
    "SPI3": PeripheralClockConstraint(
        peripheral="SPI3",
        min_hz=0,
        max_hz=25_000_000,
        note="SPI3 on APB1 (same as SPI2).",
    ),
    "I2C1": PeripheralClockConstraint(
        peripheral="I2C1",
        min_hz=0,
        max_hz=42_000_000,
        note="I2C1/2/3 driven by APB1 clock; max = APB1 max = 42 MHz.",
    ),
    "TIM_APB1": PeripheralClockConstraint(
        peripheral="TIM_APB1",
        min_hz=0,
        max_hz=100_000_000,
        note=(
            "Timers on APB1 are clocked at 2×APB1 when APB1 prescaler ≠ 1 "
            "(RM0383 §6.3.3); max = 2×42 = 84 MHz (or SYSCLK if prescaler=1)."
        ),
    ),
    "TIM_APB2": PeripheralClockConstraint(
        peripheral="TIM_APB2",
        min_hz=0,
        max_hz=100_000_000,
        note=(
            "Timers on APB2 are clocked at 2×APB2 when APB2 prescaler ≠ 1; "
            "max = SYSCLK = 100 MHz."
        ),
    ),
    "SDIO": PeripheralClockConstraint(
        peripheral="SDIO",
        min_hz=0,
        max_hz=48_000_000,
        note="SDIO clock ≤ 48 MHz (SD Spec Part 1, §4.6.2).",
    ),
}

STM32F411: ClockTreeSpec = ClockTreeSpec(
    chip_family="STM32F411",
    hse_min_hz=4_000_000,
    hse_max_hz=26_000_000,
    hsi_hz=16_000_000,
    lse_hz=32_768,
    lsi_hz=32_000,
    pll_vco_min_hz=100_000_000,
    pll_vco_max_hz=432_000_000,
    pll_input_min_hz=1_000_000,
    pll_input_max_hz=2_000_000,
    sysclk_max_hz=100_000_000,
    ahb_max_hz=100_000_000,
    apb1_max_hz=42_000_000,
    apb2_max_hz=84_000_000,
    peripheral_constraints=_F411_PERIPHERAL_CONSTRAINTS,
)


# ──────────────────────────────────────────────────────────────────────────────
# STM32F407 — RM0090 Rev 19 §6
# ──────────────────────────────────────────────────────────────────────────────

_F407_PERIPHERAL_CONSTRAINTS: Dict[str, PeripheralClockConstraint] = {
    "USB_OTG_FS": PeripheralClockConstraint(
        peripheral="USB_OTG_FS",
        min_hz=48_000_000,
        max_hz=48_000_000,
        exact_hz=48_000_000,
        tolerance_ppm=500,
        note=(
            "USB_OTG_FS requires exactly 48 MHz on the PLLQ output "
            "(USB 2.0 §7.1.11; RM0090 §6.3.3)."
        ),
    ),
    "ADC": PeripheralClockConstraint(
        peripheral="ADC",
        min_hz=0,
        max_hz=36_000_000,
        note="ADC clock ≤ 36 MHz (RM0090 §13.3.1).",
    ),
    "SPI1": PeripheralClockConstraint(
        peripheral="SPI1",
        min_hz=0,
        max_hz=42_000_000,
        note="SPI1 on APB2; fPCLK2 ≤ 84 MHz, max SCK = fPCLK2/2 = 42 MHz.",
    ),
    "SPI2": PeripheralClockConstraint(
        peripheral="SPI2",
        min_hz=0,
        max_hz=21_000_000,
        note="SPI2/3 on APB1; max SCK = fPCLK1/2; fPCLK1 ≤ 42 MHz.",
    ),
    "SPI3": PeripheralClockConstraint(
        peripheral="SPI3",
        min_hz=0,
        max_hz=21_000_000,
        note="SPI3 on APB1 (same as SPI2).",
    ),
    "SDIO": PeripheralClockConstraint(
        peripheral="SDIO",
        min_hz=0,
        max_hz=48_000_000,
        note="SDIO clock ≤ 48 MHz.",
    ),
}

STM32F407: ClockTreeSpec = ClockTreeSpec(
    chip_family="STM32F407",
    hse_min_hz=4_000_000,
    hse_max_hz=26_000_000,
    hsi_hz=16_000_000,
    lse_hz=32_768,
    lsi_hz=32_000,
    pll_vco_min_hz=100_000_000,
    pll_vco_max_hz=432_000_000,
    pll_input_min_hz=1_000_000,
    pll_input_max_hz=2_000_000,
    sysclk_max_hz=168_000_000,
    ahb_max_hz=168_000_000,
    apb1_max_hz=42_000_000,
    apb2_max_hz=84_000_000,
    peripheral_constraints=_F407_PERIPHERAL_CONSTRAINTS,
)


# ──────────────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────────────

_REGISTRY: Dict[str, ClockTreeSpec] = {
    "STM32F411": STM32F411,
    "STM32F407": STM32F407,
}

_ALIASES: Dict[str, str] = {
    "stm32f411": "STM32F411",
    "stm32f411ce": "STM32F411",
    "stm32f411re": "STM32F411",
    "stm32f411ve": "STM32F411",
    "stm32f407": "STM32F407",
    "stm32f407vg": "STM32F407",
    "stm32f407ig": "STM32F407",
}


def get_clock_spec(chip: str) -> ClockTreeSpec:
    """Return the :class:`ClockTreeSpec` for *chip*.

    Parameters
    ----------
    chip:
        Chip family string, e.g. ``"STM32F411"``, ``"STM32F407"``, or any
        alias (case-insensitive, e.g. ``"stm32f411ce"``).

    Raises
    ------
    KeyError
        If *chip* is not recognised.
    """
    key = _ALIASES.get(chip.lower(), chip)
    if key in _REGISTRY:
        return _REGISTRY[key]
    for k, v in _REGISTRY.items():
        if k.lower() == chip.lower():
            return v
    raise KeyError(
        f"Unknown clock-tree chip: {chip!r}. "
        f"Known chips: {sorted(_REGISTRY)}.  "
        f"Aliases: {sorted(_ALIASES)}."
    )


def list_clock_chip_ids() -> list[str]:
    """Return the sorted list of canonical chip-family IDs."""
    return sorted(_REGISTRY)
