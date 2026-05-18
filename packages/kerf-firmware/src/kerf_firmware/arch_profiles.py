"""
Architecture profiles for the gcc orchestrator.

Each profile describes:
- Which compiler executables to use (C and C++).
- Architecture-specific compilation flags.
- Link flags.
- How to derive MCU-specific flags from a board meta dict.
- The primary output format produced by ``objcopy``.

Profiles
--------
avr
    ``avr-gcc`` / ``avr-g++`` — classic 8-bit AVR (Uno, Mega, Leonardo …).
    Flags include ``-mmcu=<mcu>`` where the MCU slug is lowercased from the
    board's ``mcu`` field.

arm-cm0+
    ``arm-none-eabi-gcc`` — Cortex-M0+ (RP2040, SAMD21, STM32G0 …).
    Flags include ``-mcpu=cortex-m0plus``.

arm-cm4f
    ``arm-none-eabi-gcc`` — Cortex-M4F with hardware FPU (STM32F4, SAMD51,
    nRF52, RA4M1 …).  Flags include ``-mcpu=cortex-m4 -mfpu=fpv4-sp-d16
    -mfloat-abi=hard``.

arm-cm7
    ``arm-none-eabi-gcc`` — Cortex-M7 (STM32H7, IMXRT1062/Teensy 4 …).
    Flags include ``-mcpu=cortex-m7 -mfpu=fpv5-d16 -mfloat-abi=hard``.

xtensa-lx7
    ``xtensa-esp32-elf-gcc`` — Xtensa LX7 (ESP32, ESP32-S2, ESP32-S3 …).
    Flags include ``-mlongcalls``.

riscv32imc
    ``riscv-none-elf-gcc`` — RISC-V 32-bit IMC (ESP32-C3, ESP32-H2 …).
    Flags include ``-march=rv32imc -mabi=ilp32``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


# ---------------------------------------------------------------------------
# Profile dataclass
# ---------------------------------------------------------------------------

@dataclass
class ArchProfile:
    """Compile/link parameters for a single target architecture.

    Attributes
    ----------
    arch
        Architecture identifier — must match a ``board["arch"]`` value in the
        board catalogue (e.g. ``"avr"``, ``"arm-cm4f"``).
    compiler
        Name of the C compiler binary (searched on PATH with
        ``shutil.which``).
    cxx_compiler
        Name of the C++ compiler binary.
    objcopy
        Name of the ``objcopy`` binary used to produce hex/bin/uf2.
    size_tool
        Name of the ``size`` binary used to query section sizes.
    cxx_flags
        List of flags appended to every C++ compilation command.
    c_flags
        List of flags appended to every C compilation command.
    link_flags
        List of flags passed to the linker.
    output_format
        Primary post-processed output format: ``"hex"``, ``"bin"``, or
        ``"uf2"``.
    mcu_flags_fn
        Callable ``(board_meta: dict) -> list[str]`` that returns the
        architecture-specific ``-mmcu``/``-mcpu``/``-march`` flags for a
        specific board.
    install_hint
        Shell command (platform-appropriate) the user can run when the
        compiler is not found on PATH.
    """

    arch: str
    compiler: str
    cxx_compiler: str
    objcopy: str
    size_tool: str

    cxx_flags: list[str] = field(default_factory=list)
    c_flags: list[str] = field(default_factory=list)
    link_flags: list[str] = field(default_factory=list)

    output_format: str = "hex"  # "hex" | "bin" | "uf2"

    mcu_flags_fn: Callable[[dict], list[str]] = field(
        default_factory=lambda: (lambda _: [])
    )
    install_hint: str = ""

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def mcu_flags_for_board(self, board_meta: dict) -> list[str]:
        """Return MCU-specific flags for *board_meta*."""
        return self.mcu_flags_fn(board_meta)

    def all_c_flags(self, board_meta: dict) -> list[str]:
        """Full C flag list = c_flags + mcu_flags_for_board."""
        return list(self.c_flags) + self.mcu_flags_for_board(board_meta)

    def all_cxx_flags(self, board_meta: dict) -> list[str]:
        """Full C++ flag list = cxx_flags + mcu_flags_for_board."""
        return list(self.cxx_flags) + self.mcu_flags_for_board(board_meta)


# ---------------------------------------------------------------------------
# MCU-flag helpers
# ---------------------------------------------------------------------------

def _avr_mcu_flags(board_meta: dict) -> list[str]:
    """Return ``-mmcu=<mcu>`` flag for an AVR board.

    The MCU name is lower-cased from the board's ``mcu`` field and passed
    directly to ``avr-gcc`` (e.g. ``ATmega328P`` → ``atmega328p``).
    """
    mcu = board_meta.get("mcu", "")
    if not mcu:
        return []
    return [f"-mmcu={mcu.lower()}"]


def _arm_cm0plus_mcu_flags(board_meta: dict) -> list[str]:
    """Return ``-mcpu=cortex-m0plus`` plus optional ``-mthumb``."""
    return ["-mcpu=cortex-m0plus", "-mthumb"]


def _arm_cm4f_mcu_flags(board_meta: dict) -> list[str]:
    """Return Cortex-M4F flags with hardware FPU."""
    return [
        "-mcpu=cortex-m4",
        "-mthumb",
        "-mfpu=fpv4-sp-d16",
        "-mfloat-abi=hard",
    ]


def _arm_cm7_mcu_flags(board_meta: dict) -> list[str]:
    """Return Cortex-M7 flags with hardware FPU."""
    return [
        "-mcpu=cortex-m7",
        "-mthumb",
        "-mfpu=fpv5-d16",
        "-mfloat-abi=hard",
    ]


def _xtensa_lx7_mcu_flags(board_meta: dict) -> list[str]:
    """Return Xtensa LX7 flags for ESP32 family."""
    return ["-mlongcalls"]


def _riscv32imc_mcu_flags(board_meta: dict) -> list[str]:
    """Return RISC-V 32-bit IMC flags for ESP32-C3 / ESP32-H2."""
    return ["-march=rv32imc", "-mabi=ilp32"]


# ---------------------------------------------------------------------------
# Common flag sets
# ---------------------------------------------------------------------------

_COMMON_C_FLAGS = [
    "-Os",
    "-ffunction-sections",
    "-fdata-sections",
    "-Wall",
]

_COMMON_CXX_FLAGS = _COMMON_C_FLAGS + [
    "-fno-exceptions",
    "-fno-rtti",
]

_COMMON_LINK_FLAGS = [
    "-Wl,--gc-sections",
]

_AVR_LINK_FLAGS = _COMMON_LINK_FLAGS + [
    "-lm",
]

_ARM_LINK_FLAGS = _COMMON_LINK_FLAGS + [
    "--specs=nosys.specs",
    "-lm",
]


# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------

#: Map of ``arch`` → ``ArchProfile`` for all supported architectures.
PROFILES: dict[str, ArchProfile] = {
    "avr": ArchProfile(
        arch="avr",
        compiler="avr-gcc",
        cxx_compiler="avr-g++",
        objcopy="avr-objcopy",
        size_tool="avr-size",
        c_flags=_COMMON_C_FLAGS[:],
        cxx_flags=_COMMON_CXX_FLAGS[:],
        link_flags=_AVR_LINK_FLAGS[:],
        output_format="hex",
        mcu_flags_fn=_avr_mcu_flags,
        install_hint="brew install avr-gcc  # macOS; or: apt install gcc-avr binutils-avr",
    ),
    "arm-cm0+": ArchProfile(
        arch="arm-cm0+",
        compiler="arm-none-eabi-gcc",
        cxx_compiler="arm-none-eabi-g++",
        objcopy="arm-none-eabi-objcopy",
        size_tool="arm-none-eabi-size",
        c_flags=_COMMON_C_FLAGS[:],
        cxx_flags=_COMMON_CXX_FLAGS[:],
        link_flags=_ARM_LINK_FLAGS[:],
        output_format="uf2",
        mcu_flags_fn=_arm_cm0plus_mcu_flags,
        install_hint=(
            "brew install arm-none-eabi-gcc  # macOS; or: "
            "apt install gcc-arm-none-eabi binutils-arm-none-eabi"
        ),
    ),
    "arm-cm4f": ArchProfile(
        arch="arm-cm4f",
        compiler="arm-none-eabi-gcc",
        cxx_compiler="arm-none-eabi-g++",
        objcopy="arm-none-eabi-objcopy",
        size_tool="arm-none-eabi-size",
        c_flags=_COMMON_C_FLAGS[:],
        cxx_flags=_COMMON_CXX_FLAGS[:],
        link_flags=_ARM_LINK_FLAGS[:],
        output_format="bin",
        mcu_flags_fn=_arm_cm4f_mcu_flags,
        install_hint=(
            "brew install arm-none-eabi-gcc  # macOS; or: "
            "apt install gcc-arm-none-eabi binutils-arm-none-eabi"
        ),
    ),
    "arm-cm7": ArchProfile(
        arch="arm-cm7",
        compiler="arm-none-eabi-gcc",
        cxx_compiler="arm-none-eabi-g++",
        objcopy="arm-none-eabi-objcopy",
        size_tool="arm-none-eabi-size",
        c_flags=_COMMON_C_FLAGS[:],
        cxx_flags=_COMMON_CXX_FLAGS[:],
        link_flags=_ARM_LINK_FLAGS[:],
        output_format="hex",
        mcu_flags_fn=_arm_cm7_mcu_flags,
        install_hint=(
            "brew install arm-none-eabi-gcc  # macOS; or: "
            "apt install gcc-arm-none-eabi binutils-arm-none-eabi"
        ),
    ),
    "xtensa": ArchProfile(
        arch="xtensa",
        compiler="xtensa-esp32-elf-gcc",
        cxx_compiler="xtensa-esp32-elf-g++",
        objcopy="xtensa-esp32-elf-objcopy",
        size_tool="xtensa-esp32-elf-size",
        c_flags=_COMMON_C_FLAGS[:],
        cxx_flags=_COMMON_CXX_FLAGS[:],
        link_flags=_COMMON_LINK_FLAGS[:],
        output_format="bin",
        mcu_flags_fn=_xtensa_lx7_mcu_flags,
        install_hint=(
            "Install the Espressif toolchain: "
            "https://docs.espressif.com/projects/esp-idf/en/latest/esp32/get-started/"
        ),
    ),
    "riscv32imc": ArchProfile(
        arch="riscv32imc",
        compiler="riscv-none-elf-gcc",
        cxx_compiler="riscv-none-elf-g++",
        objcopy="riscv-none-elf-objcopy",
        size_tool="riscv-none-elf-size",
        c_flags=_COMMON_C_FLAGS[:],
        cxx_flags=_COMMON_CXX_FLAGS[:],
        link_flags=_COMMON_LINK_FLAGS[:],
        output_format="bin",
        mcu_flags_fn=_riscv32imc_mcu_flags,
        install_hint=(
            "Install the RISC-V toolchain: "
            "brew install riscv-gnu-toolchain  # macOS; or: "
            "apt install gcc-riscv64-unknown-elf"
        ),
    ),
}


def get_profile(arch: str) -> ArchProfile:
    """Return the ``ArchProfile`` for *arch*.

    Raises
    ------
    KeyError
        If *arch* has no registered profile.
    """
    try:
        return PROFILES[arch]
    except KeyError:
        available = ", ".join(sorted(PROFILES))
        raise KeyError(
            f"No architecture profile for {arch!r}. "
            f"Available: {available}"
        ) from None
