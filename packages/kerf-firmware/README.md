# kerf-firmware

Embedded/firmware build + flash + monitor plugin for Kerf.

## Overview

Provides a PlatformIO-reference build + flash + monitor loop for firmware
engineers. Supports Arduino, ESP-IDF, Zephyr, and Mbed frameworks via the
PlatformIO Core CLI (`pio`).

**PlatformIO Core CLI** is invoked as a **subprocess** so the hosted service
stays MIT-compatible regardless of what frameworks the user targets.

## File kinds

| Extension       | `files.kind` | Description                     |
|-----------------|-------------|----------------------------------|
| `.ino`          | `firmware`  | Arduino sketch (C++ dialect)     |
| `.cpp`, `.c`    | `firmware`  | C/C++ source (embedded context)  |
| `.h`, `.hpp`    | `firmware`  | C/C++ header                     |
| `platformio.ini`| `firmware`  | PlatformIO board manifest        |
| `boards.json`   | `firmware`  | Kerf board manifest              |

## LLM tools

| Tool            | Description                                    |
|-----------------|------------------------------------------------|
| `build_firmware`| Compile a sketch via PlatformIO Core CLI       |

## Graceful degradation

When PlatformIO Core CLI (`pio`) is not on PATH the tool and route both return a
descriptive sentinel — `PIO_NOT_INSTALLED` — with an install hint, mirroring the
CuraEngine pattern in `kerf-slicing`.

## Install PlatformIO Core

```
pip install platformio          # via pip (recommended)
brew install platformio         # macOS Homebrew
```

After install, `pio` must be on PATH (or `platformio` as a fallback).

## Board manifest

`boards.json` lists supported boards in a `platformio.ini`-compatible format:

```json
{
  "boards": [
    { "id": "uno",          "name": "Arduino Uno",        "platform": "atmelavr",   "board": "uno",         "framework": "arduino" },
    { "id": "esp32dev",     "name": "ESP32 Dev Module",   "platform": "espressif32","board": "esp32dev",    "framework": "arduino" },
    { "id": "esp8266",      "name": "ESP8266 NodeMCU",    "platform": "espressif8266","board": "nodemcuv2", "framework": "arduino" },
    { "id": "stm32f4",      "name": "STM32F4 Discovery",  "platform": "ststm32",    "board": "disco_f407vg","framework": "arduino" },
    { "id": "teensylc",     "name": "Teensy LC",          "platform": "teensy",     "board": "teensylc",   "framework": "arduino" }
  ]
}
```

## Licensing

MIT. PlatformIO Core is Apache-2.0 and invoked as a subprocess only.
