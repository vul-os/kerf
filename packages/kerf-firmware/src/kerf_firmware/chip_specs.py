"""Embedded alternate-function tables for concrete reference chips.

Sources
-------
STM32F411  — STM32F411xC/E Reference Manual RM0383, Table 9
             "STM32F411xC/E alternate function mapping" (Rev 3, §7.3)
             and STM32F411CE datasheet DS10086 Rev 7, Table 11.
             Package: LQFP64.  Pins PA0..PB15 + PC13..PC15.

ATmega328P — ATmega328P datasheet Rev 7810D, §14 "I/O Ports",
             Table 14-1..14-5, and §13 "Pin Configurations",
             Table 13-2 "Signal Description".
             Package: PDIP-28.  Pins PB0..PB7, PC0..PC6, PD0..PD7.

Voltage notes
-------------
  STM32F411  : 3.3 V device; no 5V-tolerant pins in standard mapping
               (some packages expose FT-marked pins but none on LQFP64
                PA0..PC15 subset — all VDD-tolerant only).
  ATmega328P : 5 V device when running at 5 V; all I/O pins 5 V tolerant.

Limitations
-----------
  * Only a subset of STM32 AF numbers is listed (AF0..AF9 that carry GPIO
    functions on LQFP64 PA0..PC15).  AF10..AF15 (unused / reserved on F411)
    are omitted for brevity.
  * The ATmega328P has no alternate-function mux register; each pin has fixed
    dual-function roles documented in the datasheet.  Functions listed here
    are the standard digital peripheral roles per §13.
  * Drive-strength ratings are indicative: STM32F411 max sink/source per I/O
    is 25 mA; ATmega328P is 40 mA per I/O (absolute max, not recommended).
  * NOT a substitute for ST CubeMX or Microchip Atmel Start.  Always verify
    against the official datasheet for your specific package + silicon revision.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


# ──────────────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PinCapability:
    """Describes one pin on a chip.

    Parameters
    ----------
    name:
        Canonical pin name, e.g. ``"PA0"`` or ``"PD1"``.
    alt_functions:
        Peripheral functions this pin can serve (upper-case, e.g.
        ``["GPIO", "UART2_TX", "TIM5_CH1", "ADC_IN0"]``).
    five_volt_tolerant:
        True if the pin accepts 5 V logic on its input.
    max_drive_ma:
        Peak sink/source current in milliamps (absolute-max rating).
    adc_channel:
        ADC channel number if the pin has an analogue input; ``None``
        otherwise.
    """
    name: str
    alt_functions: tuple[str, ...]
    five_volt_tolerant: bool = False
    max_drive_ma: int = 25
    adc_channel: int | None = None


@dataclass(frozen=True)
class ChipPinSpec:
    """Complete pin-capability map for one chip variant.

    Parameters
    ----------
    chip_id:
        Short identifier used in ``verify_pin_mapping`` calls,
        e.g. ``"STM32F411_LQFP64"`` or ``"ATmega328P_PDIP28"``.
    description:
        Human-readable chip description.
    pins:
        Mapping ``pin_name → PinCapability``.
    required_power_pins:
        Pin names that must be assigned (VCC, GND, …) — informational only;
        not checked by the verifier.
    """
    chip_id: str
    description: str
    pins: dict[str, PinCapability]
    required_power_pins: tuple[str, ...] = field(default_factory=tuple)


# ──────────────────────────────────────────────────────────────────────────────
# STM32F411 LQFP64 — alt-function table
# Source: RM0383 Rev 3 §7.3 Table 9; DS10086 Rev 7 Table 11
# ──────────────────────────────────────────────────────────────────────────────
#
# Format: PinCapability(name, (AF0_func, AF1_func, ...), 5V_tol, max_mA, adc_ch)
# AF order follows the datasheet table column order (AF0..AF9).
# Functions tagged with the peripheral that uses them, e.g. "TIM1_CH1" means
# timer 1 channel 1.  "SYS_*" = system functions (AF0).
#
# Only pins PA0..PA15, PB0..PB15, PC13..PC15 exist on LQFP64.
# STM32F411 is a 3.3 V device; no I/O pin on LQFP64 is 5 V tolerant.

def _p(name: str, fns: Sequence[str], adc: int | None = None) -> PinCapability:
    return PinCapability(
        name=name,
        alt_functions=tuple(fns),
        five_volt_tolerant=False,
        max_drive_ma=25,
        adc_channel=adc,
    )


_STM32F411_PINS: dict[str, PinCapability] = {
    # ── Port A ────────────────────────────────────────────────────────────────
    "PA0":  _p("PA0",  ["GPIO", "TIM2_CH1", "TIM5_CH1", "USART2_CTS", "ADC_IN0"], adc=0),
    "PA1":  _p("PA1",  ["GPIO", "TIM2_CH2", "TIM5_CH2", "USART2_RTS", "ADC_IN1"], adc=1),
    "PA2":  _p("PA2",  ["GPIO", "TIM2_CH3", "TIM5_CH3", "USART2_TX",  "ADC_IN2"], adc=2),
    "PA3":  _p("PA3",  ["GPIO", "TIM2_CH4", "TIM5_CH4", "USART2_RX",  "ADC_IN3"], adc=3),
    "PA4":  _p("PA4",  ["GPIO", "SPI1_NSS", "SPI3_NSS", "USART2_CK",  "ADC_IN4"], adc=4),
    "PA5":  _p("PA5",  ["GPIO", "TIM2_CH1", "SPI1_SCK",               "ADC_IN5"], adc=5),
    "PA6":  _p("PA6",  ["GPIO", "TIM1_BKIN","TIM3_CH1", "SPI1_MISO",  "ADC_IN6"], adc=6),
    "PA7":  _p("PA7",  ["GPIO", "TIM1_CH1N","TIM3_CH2", "SPI1_MOSI",  "ADC_IN7"], adc=7),
    "PA8":  _p("PA8",  ["GPIO", "MCO1",      "TIM1_CH1", "I2C3_SCL",  "USART1_CK"]),
    "PA9":  _p("PA9",  ["GPIO", "TIM1_CH2",  "I2C3_SMBA","USART1_TX"]),
    "PA10": _p("PA10", ["GPIO", "TIM1_CH3",  "USART1_RX"]),
    "PA11": _p("PA11", ["GPIO", "TIM1_CH4",  "USART1_CTS","USB_DM"]),
    "PA12": _p("PA12", ["GPIO", "TIM1_ETR",  "USART1_RTS","USB_DP"]),
    "PA13": _p("PA13", ["GPIO", "SYS_JTMS_SWDIO"]),
    "PA14": _p("PA14", ["GPIO", "SYS_JTCK_SWCLK"]),
    "PA15": _p("PA15", ["GPIO", "SYS_JTDI", "TIM2_CH1",  "SPI1_NSS",  "SPI3_NSS"]),

    # ── Port B ────────────────────────────────────────────────────────────────
    "PB0":  _p("PB0",  ["GPIO", "TIM1_CH2N","TIM3_CH3",  "ADC_IN8"], adc=8),
    "PB1":  _p("PB1",  ["GPIO", "TIM1_CH3N","TIM3_CH4",  "ADC_IN9"], adc=9),
    "PB2":  _p("PB2",  ["GPIO"]),                                          # BOOT1
    "PB3":  _p("PB3",  ["GPIO", "SYS_JTDO", "TIM2_CH2",  "SPI1_SCK",  "SPI3_SCK",  "I2C2_SDA"]),
    "PB4":  _p("PB4",  ["GPIO", "SYS_JTRST","TIM3_CH1",  "SPI1_MISO", "SPI3_MISO", "I2C3_SDA"]),
    "PB5":  _p("PB5",  ["GPIO", "TIM3_CH2", "I2C1_SMBA", "SPI1_MOSI", "SPI3_MOSI"]),
    "PB6":  _p("PB6",  ["GPIO", "TIM4_CH1", "I2C1_SCL",  "USART1_TX"]),
    "PB7":  _p("PB7",  ["GPIO", "TIM4_CH2", "I2C1_SDA",  "USART1_RX"]),
    "PB8":  _p("PB8",  ["GPIO", "TIM4_CH3", "TIM10_CH1", "I2C1_SCL",  "SDIO_D4"]),
    "PB9":  _p("PB9",  ["GPIO", "TIM4_CH4", "TIM11_CH1", "I2C1_SDA",  "SPI2_NSS",  "SDIO_D5"]),
    "PB10": _p("PB10", ["GPIO", "TIM2_CH3", "I2C2_SCL",  "SPI2_SCK",  "I2S2_CK"]),
    "PB12": _p("PB12", ["GPIO", "TIM1_BKIN","I2C2_SMBA", "SPI2_NSS",  "I2S2_WS"]),
    "PB13": _p("PB13", ["GPIO", "TIM1_CH1N","SPI2_SCK",  "I2S2_CK"]),
    "PB14": _p("PB14", ["GPIO", "TIM1_CH2N","SPI2_MISO", "I2S2ext_SD"]),
    "PB15": _p("PB15", ["GPIO", "TIM1_CH3N","SPI2_MOSI", "I2S2_SD",   "RTC_REFIN"]),

    # ── Port C (only PC13..PC15 exposed on LQFP64) ────────────────────────────
    "PC13": _p("PC13", ["GPIO", "RTC_AF1"]),
    "PC14": _p("PC14", ["GPIO", "RTC_OSC32_IN"]),
    "PC15": _p("PC15", ["GPIO", "RTC_OSC32_OUT"]),
}

STM32F411_LQFP64 = ChipPinSpec(
    chip_id="STM32F411_LQFP64",
    description=(
        "STM32F411xE LQFP64 — Cortex-M4 @ 100 MHz, 3.3 V VDD. "
        "Alt-function map from RM0383 Rev 3 §7.3 Table 9 + DS10086 Table 11. "
        "NOT ST-certified. No LQFP64 pin is 5V tolerant."
    ),
    pins=_STM32F411_PINS,
    required_power_pins=("VDD", "VSS", "VDDA", "VSSA"),
)


# ──────────────────────────────────────────────────────────────────────────────
# ATmega328P PDIP-28 — pin-function table
# Source: ATmega328P datasheet 7810D §13 Table 13-2 + §14 Tables 14-1..14-5
# ──────────────────────────────────────────────────────────────────────────────
#
# ATmega328P uses fixed dual-function pins, not a mux register.
# "ADC_IN<N>" = ADC channel, "PCINT<N>" = pin-change interrupt (informational).
# 5V tolerant: ALL I/O pins (device operates at 5 V / 3.3 V; input clamped to VCC).

def _avr(name: str, fns: Sequence[str], adc: int | None = None) -> PinCapability:
    return PinCapability(
        name=name,
        alt_functions=tuple(fns),
        five_volt_tolerant=True,   # ATmega I/O inputs are VCC-clamped
        max_drive_ma=40,
        adc_channel=adc,
    )


_ATMEGA328P_PINS: dict[str, PinCapability] = {
    # ── Port B (PB0..PB7, PDIP pins 14..19, 9, 10) ───────────────────────────
    # PB6/PB7 are XTAL1/XTAL2 in crystal mode; act as GPIO only when CKSEL fuses
    # select internal oscillator.  Listed here as GPIO-capable per §14.
    "PB0": _avr("PB0", ["GPIO", "ICP1", "CLKO", "PCINT0"]),
    "PB1": _avr("PB1", ["GPIO", "OC1A", "PCINT1"]),
    "PB2": _avr("PB2", ["GPIO", "SS",   "OC1B", "PCINT2"]),        # SPI SS
    "PB3": _avr("PB3", ["GPIO", "MOSI", "OC2A", "PCINT3"]),        # SPI MOSI
    "PB4": _avr("PB4", ["GPIO", "MISO", "PCINT4"]),                 # SPI MISO
    "PB5": _avr("PB5", ["GPIO", "SCK",  "PCINT5"]),                 # SPI SCK
    "PB6": _avr("PB6", ["GPIO", "XTAL1","TOSC1","PCINT6"]),
    "PB7": _avr("PB7", ["GPIO", "XTAL2","TOSC2","PCINT7"]),

    # ── Port C (PC0..PC6, PDIP pins 23..28 + RESET) ──────────────────────────
    # PC6 = RESET in default fuse config; acts as GPIO only when RSTDISBL=0.
    "PC0": _avr("PC0", ["GPIO", "ADC_IN0", "PCINT8"],  adc=0),
    "PC1": _avr("PC1", ["GPIO", "ADC_IN1", "PCINT9"],  adc=1),
    "PC2": _avr("PC2", ["GPIO", "ADC_IN2", "PCINT10"], adc=2),
    "PC3": _avr("PC3", ["GPIO", "ADC_IN3", "PCINT11"], adc=3),
    "PC4": _avr("PC4", ["GPIO", "ADC_IN4", "SDA",   "PCINT12"], adc=4),  # I2C SDA (TWI)
    "PC5": _avr("PC5", ["GPIO", "ADC_IN5", "SCL",   "PCINT13"], adc=5),  # I2C SCL (TWI)
    "PC6": _avr("PC6", ["GPIO", "RESET",   "PCINT14"]),

    # ── Port D (PD0..PD7, PDIP pins 2..6 + 11..13) ───────────────────────────
    "PD0": _avr("PD0", ["GPIO", "RXD",   "PCINT16"]),   # USART RX
    "PD1": _avr("PD1", ["GPIO", "TXD",   "PCINT17"]),   # USART TX
    "PD2": _avr("PD2", ["GPIO", "INT0",  "PCINT18"]),
    "PD3": _avr("PD3", ["GPIO", "INT1",  "OC2B", "PCINT19"]),
    "PD4": _avr("PD4", ["GPIO", "T0",    "XCK",  "PCINT20"]),
    "PD5": _avr("PD5", ["GPIO", "T1",    "OC0B", "PCINT21"]),
    "PD6": _avr("PD6", ["GPIO", "AIN0",  "OC0A", "PCINT22"]),
    "PD7": _avr("PD7", ["GPIO", "AIN1",  "PCINT23"]),
}

ATMEGA328P_PDIP28 = ChipPinSpec(
    chip_id="ATmega328P_PDIP28",
    description=(
        "ATmega328P PDIP-28 — AVR 8-bit @ up to 20 MHz (5 V) / 8 MHz (3.3 V). "
        "Pin functions from ATmega328P datasheet 7810D §13 Table 13-2 + §14. "
        "NOT Microchip-certified. All I/O pins 5V tolerant at VCC=5V."
    ),
    pins=_ATMEGA328P_PINS,
    required_power_pins=("VCC", "GND", "AVCC", "AREF"),
)


# ──────────────────────────────────────────────────────────────────────────────
# Registry
# ──────────────────────────────────────────────────────────────────────────────

_CHIP_REGISTRY: dict[str, ChipPinSpec] = {
    STM32F411_LQFP64.chip_id: STM32F411_LQFP64,
    ATMEGA328P_PDIP28.chip_id: ATMEGA328P_PDIP28,
    # convenience aliases
    "stm32f411":    STM32F411_LQFP64,
    "atmega328p":   ATMEGA328P_PDIP28,
    "atmega328":    ATMEGA328P_PDIP28,
    "arduino_uno":  ATMEGA328P_PDIP28,
}


def get_chip_spec(chip_id: str) -> ChipPinSpec:
    """Return a :class:`ChipPinSpec` by *chip_id* (case-insensitive).

    Raises :exc:`KeyError` for unknown chips.
    """
    key = chip_id.lower().replace("-", "_")
    for k, v in _CHIP_REGISTRY.items():
        if k.lower().replace("-", "_") == key:
            return v
    raise KeyError(
        f"Unknown chip: {chip_id!r}.  "
        f"Known IDs: {sorted({v.chip_id for v in _CHIP_REGISTRY.values()})}"
    )


def list_chip_ids() -> list[str]:
    """Return the canonical chip_ids available in the registry."""
    return sorted({v.chip_id for v in _CHIP_REGISTRY.values()})
