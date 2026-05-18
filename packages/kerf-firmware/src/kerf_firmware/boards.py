"""
Board manifest for kerf-firmware.

Provides a `boards.json`-compatible registry of known PlatformIO boards and
a helper that returns a Kerf-flavoured board dict.

The manifest is intentionally small — it covers the most common boards.
PlatformIO Core knows about 1 000+ boards; users can always pass a custom
board ID to build_firmware() and PlatformIO will resolve it.
"""
from __future__ import annotations

from typing import TypedDict


class BoardEntry(TypedDict):
    id: str           # PlatformIO board ID (e.g. 'uno')
    name: str         # Human-readable name
    platform: str     # PlatformIO platform (e.g. 'atmelavr')
    board: str        # PlatformIO board field (often == id)
    framework: str    # Default framework (e.g. 'arduino')
    mcu: str          # MCU string (informational)
    f_cpu: str        # CPU frequency (informational)
    upload_protocol: str  # Upload protocol (informational)


# ── Manifest ──────────────────────────────────────────────────────────────────

BOARDS: list[BoardEntry] = [
    {
        "id": "uno",
        "name": "Arduino Uno",
        "platform": "atmelavr",
        "board": "uno",
        "framework": "arduino",
        "mcu": "ATmega328P",
        "f_cpu": "16000000L",
        "upload_protocol": "arduino",
    },
    {
        "id": "nano",
        "name": "Arduino Nano (ATmega328P)",
        "platform": "atmelavr",
        "board": "nano",
        "framework": "arduino",
        "mcu": "ATmega328P",
        "f_cpu": "16000000L",
        "upload_protocol": "arduino",
    },
    {
        "id": "mega2560",
        "name": "Arduino Mega 2560",
        "platform": "atmelavr",
        "board": "megaatmega2560",
        "framework": "arduino",
        "mcu": "ATmega2560",
        "f_cpu": "16000000L",
        "upload_protocol": "wiring",
    },
    {
        "id": "esp32dev",
        "name": "ESP32 Dev Module",
        "platform": "espressif32",
        "board": "esp32dev",
        "framework": "arduino",
        "mcu": "ESP32",
        "f_cpu": "240000000L",
        "upload_protocol": "esptool",
    },
    {
        "id": "esp32-s3",
        "name": "ESP32-S3 Dev Module",
        "platform": "espressif32",
        "board": "esp32-s3-devkitc-1",
        "framework": "arduino",
        "mcu": "ESP32-S3",
        "f_cpu": "240000000L",
        "upload_protocol": "esptool",
    },
    {
        "id": "nodemcuv2",
        "name": "NodeMCU v2 (ESP8266)",
        "platform": "espressif8266",
        "board": "nodemcuv2",
        "framework": "arduino",
        "mcu": "ESP8266",
        "f_cpu": "80000000L",
        "upload_protocol": "esptool",
    },
    {
        "id": "d1_mini",
        "name": "Wemos D1 mini (ESP8266)",
        "platform": "espressif8266",
        "board": "d1_mini",
        "framework": "arduino",
        "mcu": "ESP8266",
        "f_cpu": "80000000L",
        "upload_protocol": "esptool",
    },
    {
        "id": "bluepill_f103c8",
        "name": "STM32 Blue Pill (STM32F103C8)",
        "platform": "ststm32",
        "board": "bluepill_f103c8",
        "framework": "arduino",
        "mcu": "STM32F103C8",
        "f_cpu": "72000000L",
        "upload_protocol": "stlink",
    },
    {
        "id": "nucleo_f401re",
        "name": "ST Nucleo F401RE",
        "platform": "ststm32",
        "board": "nucleo_f401re",
        "framework": "arduino",
        "mcu": "STM32F401RE",
        "f_cpu": "84000000L",
        "upload_protocol": "stlink",
    },
    {
        "id": "teensylc",
        "name": "Teensy LC",
        "platform": "teensy",
        "board": "teensylc",
        "framework": "arduino",
        "mcu": "MKL26Z64",
        "f_cpu": "48000000L",
        "upload_protocol": "teensy-cli",
    },
    {
        "id": "teensy40",
        "name": "Teensy 4.0",
        "platform": "teensy",
        "board": "teensy40",
        "framework": "arduino",
        "mcu": "IMXRT1062",
        "f_cpu": "600000000L",
        "upload_protocol": "teensy-cli",
    },
    {
        "id": "pico",
        "name": "Raspberry Pi Pico (RP2040)",
        "platform": "raspberrypi",
        "board": "pico",
        "framework": "arduino",
        "mcu": "RP2040",
        "f_cpu": "133000000L",
        "upload_protocol": "picotool",
    },
]

# ── Index ──────────────────────────────────────────────────────────────────────

_BOARDS_BY_ID: dict[str, BoardEntry] = {b["id"]: b for b in BOARDS}


def get_board(board_id: str) -> BoardEntry | None:
    """Return the BoardEntry for a given board ID, or None if unknown."""
    return _BOARDS_BY_ID.get(board_id)


def list_boards() -> list[BoardEntry]:
    """Return all registered boards."""
    return BOARDS


def boards_as_json_manifest() -> dict:
    """Return the manifest in boards.json format (compatible with platformio.ini)."""
    return {"boards": BOARDS}
