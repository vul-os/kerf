# Firmware — Embedded C/C++ and RTOS Projects

`kerf-firmware` adds embedded software authoring to Kerf. It manages `.c`,
`.cpp`, and linker-script files alongside your mechanical and electronics files
in the same project, and provides cross-compilation, flash-image generation,
and memory-map analysis through LLM tools.

---

## Overview

| Property | Value |
|---|---|
| Package | `kerf-firmware` |
| Plugin entry-point | `kerf_firmware.plugin:register` |
| Capability tag | `firmware.build` |
| Source | `packages/kerf-firmware/` |

---

## File types

| Extension | Kind | Description |
|---|---|---|
| `.c` | `c_source` | C source file — compiled with the project toolchain |
| `.cpp` / `.cc` | `cpp_source` | C++ source file |
| `.h` / `.hpp` | `c_header` | Header file — included in the Monaco editor but not compiled directly |
| `.ld` / `.lds` | `linker_script` | GNU ld linker script — defines memory regions and section placement |
| `.elf` | `elf_binary` | ELF binary produced by the cross-compiler — firmware artefact |
| `.hex` | `ihex_binary` | Intel HEX — commonly required by flash tools (avrdude, OpenOCD) |
| `.bin` | `raw_binary` | Flat binary — for bootloaders and DFU |
| `.map` | `linker_map` | Linker map file — symbol→section→address table |

---

## Supported toolchains

Toolchains are resolved from `$PATH` in preference order. Set
`KERF_FIRMWARE_TOOLCHAIN` to force a specific prefix.

| Target family | Toolchain prefix | Install |
|---|---|---|
| ARM Cortex-M | `arm-none-eabi-` | `apt install gcc-arm-none-eabi` |
| RISC-V | `riscv32-unknown-elf-` | `apt install gcc-riscv64-linux-gnu` |
| AVR | `avr-` | `apt install gcc-avr` |
| ESP32 (Xtensa) | `xtensa-esp32-elf-` | ESP-IDF toolchain |
| x86/x86-64 (hosted sim) | system `gcc` / `clang` | — |

---

## LLM tools

### `build_firmware`

Compile the firmware sources in the project and return build output.

```json
{
  "project_id": "<uuid>",
  "target": "stm32f4xx",
  "optimisation": "Os",
  "defines": ["HSE_VALUE=8000000", "USE_HAL_DRIVER"]
}
```

`target` is a short alias that selects the CPU flags, linker script, and
startup file. Built-in targets: `stm32f4xx`, `stm32h7xx`, `nrf52840`,
`rp2040`, `esp32`, `attiny85`, `atmega2560`, `rv32imac-sim`.

Returns:

```json
{
  "status": "ok",
  "elf_file_id": "<uuid>",
  "hex_file_id": "<uuid>",
  "map_file_id": "<uuid>",
  "warnings": [],
  "errors": [],
  "size": { "text": 14320, "data": 512, "bss": 2048 }
}
```

---

### `analyse_memory_map`

Parse the `.map` file and return a per-section, per-symbol breakdown of
flash and RAM usage.

```json
{
  "map_file_id": "<uuid>",
  "top_n": 20
}
```

Returns the top-N symbols by size in each memory region, sorted descending.
Useful for diagnosing flash overflow or finding large BSS buffers.

---

### `disassemble_function`

Disassemble a named function from an ELF binary.

```json
{
  "elf_file_id": "<uuid>",
  "function": "HAL_UART_Transmit",
  "flavour": "att"
}
```

`flavour`: `"att"` (AT&T syntax, default) or `"intel"`. Uses `objdump -d`
under the hood. Returns the disassembly as a plain-text string.

---

### `run_firmware_sim`

Run the firmware binary against the hosted QEMU machine emulator. Supported
machine types: `stm32f405`, `nrf52840`, `rv32-generic`.

```json
{
  "elf_file_id": "<uuid>",
  "machine": "stm32f405",
  "timeout_ms": 5000,
  "uart_input": ""
}
```

Returns UART output captured during the run, exit reason (`"timeout"`,
`"semihosting_exit"`, `"panic"`), and CPU cycle count if available.

---

## HTTP routes

| Method | Path | Description |
|---|---|---|
| `POST` | `/firmware/build` | Cross-compile sources and produce ELF/HEX/MAP artefacts |
| `POST` | `/firmware/analyse-map` | Parse a `.map` file; return section/symbol breakdown |
| `POST` | `/firmware/disassemble` | Disassemble a named function from an ELF |
| `POST` | `/firmware/sim` | Run firmware in QEMU; return UART output |

---

## Typical workflow

1. Create a new project or open an existing one. Add `.c` / `.h` / `.ld`
   files via the file tree.
2. Ask the LLM to call `build_firmware` with your target. Review warnings.
3. If flash is tight, call `analyse_memory_map` to find the largest symbols.
4. For logic bugs, call `run_firmware_sim` to capture UART output without
   hardware.
5. Download the `.hex` or `.bin` artefact and flash with your preferred tool
   (OpenOCD, `avrdude`, `esptool.py`).

---

## Related documentation

| Topic | Path |
|---|---|
| Electronics workflow | `docs/electronics.md` |
| PLC (IEC 61131-3) | `docs/plc.md` |
| Plugin development | `docs/plugins-development.md` |
| SDK scripting | `docs/sdk.md` |
