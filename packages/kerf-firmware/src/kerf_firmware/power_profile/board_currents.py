"""
kerf_firmware.power_profile.board_currents
==========================================

Typical active and deep-sleep current draw for popular MCU boards.

All values in **milliamps (mA)** at nominal operating voltage.

Sources / methodology
---------------------
* Active current  — typical CPU-busy (all peripherals at idle unless noted).
* Deep-sleep current — deepest sleep mode the chip natively supports
  (ESP32 deep-sleep, STM32 Standby, AVR Power-down, RP2040 DORMANT, etc.).
* Values are midpoints from manufacturer datasheets; real draw varies with
  clock speed, peripheral load, and supply voltage.

The table is intentionally conservative (slightly high active, slightly low
sleep) so that battery-life estimates stay pessimistic / safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class BoardProfile:
    """Current draw profile for a single MCU board.

    Attributes
    ----------
    active_mA:
        Typical active (CPU running) current in mA.
    sleep_mA:
        Deep-sleep / lowest-power mode current in mA.
    voltage_V:
        Nominal operating voltage used when converting power to energy.
    notes:
        Free-text notes (datasheet refs, caveats).
    """

    active_mA: float
    sleep_mA: float
    voltage_V: float
    notes: str = ""


# ---------------------------------------------------------------------------
# Master board table
# Canonical key: the string a user passes to PowerModel(board=...).
# Aliases are resolved in board_lookup().
# ---------------------------------------------------------------------------

BOARD_TABLE: Dict[str, BoardProfile] = {
    # -----------------------------------------------------------------------
    # Microchip / Atmel AVR family
    # -----------------------------------------------------------------------
    "Arduino Uno": BoardProfile(
        active_mA=50.0,
        sleep_mA=0.001,  # ATmega328P Power-down with WDT disabled
        voltage_V=5.0,
        notes="ATmega328P @ 16 MHz. Includes on-board 5 V regulator & USB-serial chip (~20 mA idle).",
    ),
    "Arduino Nano": BoardProfile(
        active_mA=19.0,
        sleep_mA=0.001,
        voltage_V=5.0,
        notes="ATmega328P @ 16 MHz. Lighter than Uno; no CH340/FTDI powered from USB in battery use.",
    ),
    "Arduino Mega 2560": BoardProfile(
        active_mA=93.0,
        sleep_mA=0.001,
        voltage_V=5.0,
        notes="ATmega2560 @ 16 MHz. Includes USB-serial bridge.",
    ),
    "Arduino Nano Every": BoardProfile(
        active_mA=14.0,
        sleep_mA=0.00005,  # ATmega4809 Power-down ~50 nA
        voltage_V=5.0,
        notes="ATmega4809 @ 20 MHz. More efficient regulator than classic Nano.",
    ),
    # -----------------------------------------------------------------------
    # Espressif ESP8266 / ESP32 family
    # -----------------------------------------------------------------------
    "ESP8266": BoardProfile(
        active_mA=80.0,
        sleep_mA=0.02,  # deep-sleep ~20 µA
        voltage_V=3.3,
        notes="ESP8266EX @ 80 MHz. Wi-Fi TX peaks at ~400 mA; 80 mA is CPU-active, radio idle.",
    ),
    "ESP32": BoardProfile(
        active_mA=80.0,
        sleep_mA=0.01,  # deep-sleep ~10 µA
        voltage_V=3.3,
        notes="ESP32 dual-core Xtensa @ 240 MHz. Deep-sleep with RTC on ~10 µA.",
    ),
    "ESP32-S2": BoardProfile(
        active_mA=50.0,
        sleep_mA=0.022,  # deep-sleep ~22 µA (RTC mem retained)
        voltage_V=3.3,
        notes="ESP32-S2 single-core. Lower active draw than classic ESP32; USB-native.",
    ),
    "ESP32-S3": BoardProfile(
        active_mA=75.0,
        sleep_mA=0.015,  # deep-sleep ~15 µA
        voltage_V=3.3,
        notes="ESP32-S3 dual-core with AI accelerator. Deep-sleep with ULP on ~15 µA.",
    ),
    "ESP32-C3": BoardProfile(
        active_mA=22.0,
        sleep_mA=0.005,  # deep-sleep ~5 µA
        voltage_V=3.3,
        notes="ESP32-C3 single-core RISC-V. Very low active draw; good for battery IoT.",
    ),
    # -----------------------------------------------------------------------
    # Raspberry Pi RP2040 / RP2350
    # -----------------------------------------------------------------------
    "RP2040": BoardProfile(
        active_mA=25.0,
        sleep_mA=0.18,  # DORMANT mode ~180 µA (on-chip LDO stays on)
        voltage_V=3.3,
        notes="RP2040 dual-core ARM Cortex-M0+ @ 125 MHz. DORMANT keeps SRAM.",
    ),
    "RP2350": BoardProfile(
        active_mA=22.0,
        sleep_mA=0.010,  # deep-sleep ~10 µA
        voltage_V=3.3,
        notes="RP2350 dual ARM Cortex-M33 / RISC-V @ 150 MHz. Improved power modes vs RP2040.",
    ),
    # -----------------------------------------------------------------------
    # STMicroelectronics STM32 family
    # -----------------------------------------------------------------------
    "STM32F103": BoardProfile(
        active_mA=34.0,
        sleep_mA=0.002,  # Standby ~2 µA
        voltage_V=3.3,
        notes="STM32F103 (Blue Pill) @ 72 MHz. Standby with RTC ~2 µA.",
    ),
    "STM32L476": BoardProfile(
        active_mA=10.0,
        sleep_mA=0.00008,  # Shutdown ~80 nA
        voltage_V=3.3,
        notes="STM32L476 ultra-low-power @ 80 MHz. Shutdown mode ~80 nA (no RTC).",
    ),
    # -----------------------------------------------------------------------
    # Nordic Semiconductor nRF5x (BLE-focused)
    # -----------------------------------------------------------------------
    "nRF52840": BoardProfile(
        active_mA=5.0,
        sleep_mA=0.00150,  # System-off ~1.5 µA
        voltage_V=3.3,
        notes="nRF52840 ARM Cortex-M4F @ 64 MHz. System-off keeps GPREGRET; BLE TX ~7 mA.",
    ),
    # -----------------------------------------------------------------------
    # Teensy / NXP i.MX RT
    # -----------------------------------------------------------------------
    "Teensy 4.1": BoardProfile(
        active_mA=100.0,
        sleep_mA=0.001,
        voltage_V=3.3,
        notes="NXP IMXRT1062 ARM Cortex-M7 @ 600 MHz. High-performance; not optimised for battery.",
    ),
    # -----------------------------------------------------------------------
    # SAMD / Microchip (Adafruit, SparkFun variants)
    # -----------------------------------------------------------------------
    "SAMD21": BoardProfile(
        active_mA=6.0,
        sleep_mA=0.004,  # Standby ~4 µA
        voltage_V=3.3,
        notes="SAMD21 ARM Cortex-M0+ @ 48 MHz. Used on Arduino Zero, Adafruit M0 boards.",
    ),
    "SAMD51": BoardProfile(
        active_mA=22.0,
        sleep_mA=0.006,  # Standby ~6 µA
        voltage_V=3.3,
        notes="SAMD51 ARM Cortex-M4F @ 120 MHz. Used on Adafruit M4 boards.",
    ),
}

# ---------------------------------------------------------------------------
# Alias map — common alternative names → canonical key
# ---------------------------------------------------------------------------

_ALIASES: Dict[str, str] = {
    # ESP32 shorthand
    "esp32": "ESP32",
    "esp32-s2": "ESP32-S2",
    "esp32-s3": "ESP32-S3",
    "esp32-c3": "ESP32-C3",
    "esp8266": "ESP8266",
    # RP2040
    "rp2040": "RP2040",
    "rp2350": "RP2350",
    "pico": "RP2040",
    "raspberry pi pico": "RP2040",
    # Arduino
    "uno": "Arduino Uno",
    "nano": "Arduino Nano",
    "mega": "Arduino Mega 2560",
    "nano every": "Arduino Nano Every",
    # STM32
    "blue pill": "STM32F103",
    "stm32f103": "STM32F103",
    "stm32l476": "STM32L476",
    # Nordic
    "nrf52840": "nRF52840",
    "nrf52": "nRF52840",
    # Teensy
    "teensy41": "Teensy 4.1",
    "teensy 4.1": "Teensy 4.1",
    # SAMD
    "samd21": "SAMD21",
    "samd51": "SAMD51",
    "arduino zero": "SAMD21",
    "adafruit m0": "SAMD21",
    "adafruit m4": "SAMD51",
}


def board_lookup(name: str) -> BoardProfile:
    """Return the :class:`BoardProfile` for *name*.

    Lookup is case-insensitive and resolves common aliases.

    Raises
    ------
    KeyError
        If *name* is not found in the table or alias map.
    """
    # Exact match first (preserves user capitalisation)
    if name in BOARD_TABLE:
        return BOARD_TABLE[name]

    # Case-insensitive alias lookup
    canonical = _ALIASES.get(name.lower())
    if canonical and canonical in BOARD_TABLE:
        return BOARD_TABLE[canonical]

    # Case-insensitive direct match against table keys
    lower = name.lower()
    for key, profile in BOARD_TABLE.items():
        if key.lower() == lower:
            return profile

    available = ", ".join(sorted(BOARD_TABLE.keys()))
    raise KeyError(
        f"Board {name!r} not found. Available boards: {available}"
    )


def list_boards() -> list[str]:
    """Return a sorted list of canonical board names."""
    return sorted(BOARD_TABLE.keys())
