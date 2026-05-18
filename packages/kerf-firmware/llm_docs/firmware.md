# Firmware — embedded build + flash + monitor (kerf-firmware)

## Overview

`kerf-firmware` gives embedded/firmware engineers a PlatformIO-reference build
loop inside Kerf. The tool compiles Arduino, ESP-IDF, Zephyr, and Mbed
sketches via the **PlatformIO Core CLI** (`pio`) invoked as a subprocess.

## LLM tool

```
build_firmware(
  sketch_dir: str,         -- absolute project path to the sketch directory
  board?:     str = "uno", -- PlatformIO board ID
  framework?: str = "arduino",
  environment?: str        -- named platformio.ini environment (optional)
)
→ {
    elf_path, hex_path, bin_path,
    build_log_preview,       -- first 80 lines of build stdout
    build_log_lines,         -- total lines
    artefact_bytes,          -- size of primary artefact
    environment,
    warnings
  }
```

### When to use

Use `build_firmware` when the user asks to compile, build, or verify an
embedded firmware sketch. Always supply the correct `board` and `framework`
for the user's hardware — wrong combinations fail with a clear PlatformIO error.

### Supported boards (Kerf manifest)

| `board` ID          | Name                          | Framework     |
|---------------------|-------------------------------|---------------|
| `uno`               | Arduino Uno (ATmega328P)      | arduino       |
| `nano`              | Arduino Nano (ATmega328P)     | arduino       |
| `mega2560`          | Arduino Mega 2560             | arduino       |
| `esp32dev`          | ESP32 Dev Module              | arduino/espidf|
| `esp32-s3`          | ESP32-S3 Dev Module           | arduino/espidf|
| `nodemcuv2`         | NodeMCU v2 (ESP8266)          | arduino       |
| `d1_mini`           | Wemos D1 mini (ESP8266)       | arduino       |
| `bluepill_f103c8`   | STM32 Blue Pill               | arduino       |
| `nucleo_f401re`     | ST Nucleo F401RE              | arduino       |
| `teensylc`          | Teensy LC                     | arduino       |
| `teensy40`          | Teensy 4.0                    | arduino       |
| `pico`              | Raspberry Pi Pico (RP2040)    | arduino       |

Any PlatformIO-supported board ID can be passed — the Kerf manifest above is a
convenience subset. Use `GET /firmware/boards` to retrieve the full Kerf list.

### Supported frameworks

| `framework`  | Description                                    |
|--------------|------------------------------------------------|
| `arduino`    | Arduino framework (default, widest board support) |
| `espidf`     | Espressif IDF (ESP32/ESP32-S2/S3 only)        |
| `zephyr`     | Zephyr RTOS (ARM/RISC-V targets)               |
| `mbed`       | Mbed OS (ARM targets)                          |
| `cmsis`      | CMSIS-core, bare-metal ARM                     |

## Sketch directory layout

A minimal sketch directory for `board=uno`, `framework=arduino`:

```
blink/
  main.ino          ← Arduino entry point
  platformio.ini    ← optional; generated if absent
```

When `platformio.ini` is absent kerf-firmware generates a minimal one:

```ini
[env:uno]
platform  = atmelavr
board     = uno
framework = arduino
```

## Artefacts

| File           | Targets                    |
|----------------|---------------------------|
| `firmware.elf` | All targets (always built) |
| `firmware.hex` | AVR (Arduino Uno, Mega…)   |
| `firmware.bin` | ARM (STM32, ESP32, RP2040) |

## Error: PlatformIO not installed

When PlatformIO Core CLI is not on the server PATH the tool returns:

```json
{
  "error": "PIO_NOT_INSTALLED",
  "message": "PlatformIO Core CLI not found. Install: pip install platformio"
}
```

Prompt the user to install PlatformIO and retry. The tool does not fall back
silently — compilation requires the external binary.

## Serial monitor

The serial monitor (`POST /firmware/monitor`) is for **local / self-hosted**
installs where the device is physically connected to the host machine.  It is
not available in the hosted cloud service (the device is on the user's desk,
not the server).

```
POST /firmware/monitor
{ "port": "/dev/ttyUSB0", "baud": 9600, "duration_s": 10 }
```

## Deferred (Tier 2)

The following are not implemented in this Tier 1 release:

- Over-the-air (OTA) flash support
- Remote serial monitor via WebSocket relay
- Debug adapter (DAP / OpenOCD) integration
- JTAG/SWD flash via `pio run -t upload`
- Multi-environment batch builds
