/**
 * firmware.meta.js — SEO metadata + JSON-LD for the Firmware domain page.
 *
 * Exported constants are consumed by Firmware.jsx for <head> injection
 * and tested in landing.firmware.test.js.
 */

export const META_TITLE = 'Embedded firmware design with chat — Kerf'

export const META_DESCRIPTION =
  'Chat-driven embedded development: C/C++/Rust, static analysis, RTOS configuration, ' +
  'linker scripts, flash — .hex/.elf output, open toolchains.'

export const META_OG_IMAGE = 'https://kerf.sh/og/firmware.png'

export const META_URL = 'https://kerf.sh/domains/firmware'

export const TAGLINE = 'From bare metal to .hex in a conversation.'

// Feature list — one entry per capability card.
export const FEATURES = [
  {
    id: 'c-cpp-rust',
    name: 'C / C++ / Rust toolchain (ARM + RISC-V)',
    description:
      'arm-none-eabi-gcc, arm-none-eabi-g++, and cargo cross for ARM Cortex-M and RISC-V targets. Build configs for STM32, RP2040, ESP32, nRF52 and GD32 families. Cortex-A64 Linux targets supported.',
  },
  {
    id: 'rtos',
    name: 'RTOS configuration (FreeRTOS / Zephyr)',
    description:
      'FreeRTOS task, queue, semaphore, and timer scaffolding generated in chat. Zephyr devicetree (DTS) and Kconfig authoring with LLM awareness of the binding schema. West build wired end-to-end.',
  },
  {
    id: 'static-analysis',
    name: 'Static analysis (cppcheck + clang-tidy)',
    description:
      'cppcheck and clang-tidy run on every compile turn. MISRA-C 2012 advisory subset check via cppcheck addons. Findings surfaced inline with source context — fix-suggestions generated automatically.',
  },
  {
    id: 'linker-scripts',
    name: 'Linker script authoring',
    description:
      'Memory region tables (.text, .bss, .data, .stack, .heap) authored and validated in chat. GNU ld script syntax with size-budget callout after each link. Scatter files for armlink also supported.',
  },
  {
    id: 'flash-debug',
    name: 'Flash + debug (OpenOCD / pyOCD)',
    description:
      'OpenOCD and pyOCD flash programming and SWD/JTAG debug. GDB server wired through the chat loop: set breakpoints, inspect memory, read registers — all from a conversation.',
  },
  {
    id: 'hex-elf',
    name: '.hex / .elf / .bin output',
    description:
      'Produces Intel HEX, ELF (with full debug symbols) and raw .bin for bootloader consumption. objcopy, objdump, and nm cross-references embedded in the chat diff.',
  },
  {
    id: 'peripheral-hal',
    name: 'Peripheral HAL scaffolding',
    description:
      'Generate HAL init code for GPIO, UART, SPI, I2C, ADC, DAC, DMA and timers. Vendor cube/HAL wrappers or bare CMSIS depending on target. Register-level code where no HAL exists.',
  },
  {
    id: 'unit-tests',
    name: 'Unit testing (Unity / Ceedling)',
    description:
      'Unity test framework and Ceedling runner. Mock generation for peripheral HALs. Tests run on host x86 via cross-compile shim — no hardware required for logic-layer tests.',
  },
  {
    id: 'power-profiling',
    name: 'Power profiling + sleep scheduling',
    description:
      'Annotate tasks and peripherals with current draw. Scheduler suggests LP sleep modes, peripheral power gates and tick-less RTOS configurations to hit a μA target.',
  },
  {
    id: 'bootloader',
    name: 'Bootloader (MCUboot / U-Boot)',
    description:
      'MCUboot slot configuration for OTA on ARM Cortex-M. U-Boot config for embedded Linux targets (AM335x, i.MX8, Raspberry Pi CM). Signed image pipeline wired to kerf git.',
  },
  {
    id: 'kerf-sdk-firmware',
    name: 'Python SDK — kerf-sdk firmware surface',
    description:
      'pip install kerf-sdk. JSON-RPC calls: run_build, run_flash, run_static_analysis, get_map_report. CI integration: build matrix across toolchain versions and target families from a script.',
  },
]

export const JSON_LD = {
  '@context': 'https://schema.org',
  '@graph': [
    {
      '@type': 'WebPage',
      '@id': META_URL,
      url: META_URL,
      name: META_TITLE,
      description: META_DESCRIPTION,
      image: META_OG_IMAGE,
      publisher: {
        '@type': 'Organization',
        name: 'Kerf',
        url: 'https://kerf.sh',
      },
    },
    {
      '@type': 'ItemList',
      name: 'Kerf Embedded Firmware capabilities',
      description: 'Embedded development features in Kerf',
      numberOfItems: FEATURES.length,
      itemListElement: FEATURES.map((f, i) => ({
        '@type': 'ListItem',
        position: i + 1,
        name: f.name,
        description: f.description,
      })),
    },
  ],
}
