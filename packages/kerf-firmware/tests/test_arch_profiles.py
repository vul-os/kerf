"""Tests for arch_profiles.py — ArchProfile registry and flag generation."""

import pytest

from kerf_firmware.arch_profiles import (
    PROFILES,
    ArchProfile,
    get_profile,
)


# ---------------------------------------------------------------------------
# Registry completeness
# ---------------------------------------------------------------------------

class TestProfileRegistry:
    EXPECTED_ARCHS = {"avr", "arm-cm0+", "arm-cm4f", "arm-cm7", "xtensa", "riscv32imc"}

    def test_all_expected_archs_registered(self):
        assert self.EXPECTED_ARCHS <= set(PROFILES)

    def test_get_profile_returns_arch_profile(self):
        for arch in self.EXPECTED_ARCHS:
            p = get_profile(arch)
            assert isinstance(p, ArchProfile)
            assert p.arch == arch

    def test_get_profile_unknown_raises_key_error(self):
        with pytest.raises(KeyError, match="No architecture profile"):
            get_profile("unknown-arch")

    def test_each_profile_has_compiler(self):
        for arch, profile in PROFILES.items():
            assert profile.compiler, f"{arch}: compiler is empty"

    def test_each_profile_has_objcopy(self):
        for arch, profile in PROFILES.items():
            assert profile.objcopy, f"{arch}: objcopy is empty"

    def test_each_profile_has_output_format(self):
        valid_formats = {"hex", "bin", "uf2"}
        for arch, profile in PROFILES.items():
            assert profile.output_format in valid_formats, (
                f"{arch}: output_format={profile.output_format!r} not in {valid_formats}"
            )

    def test_each_profile_has_install_hint(self):
        for arch, profile in PROFILES.items():
            assert profile.install_hint, f"{arch}: install_hint is empty"


# ---------------------------------------------------------------------------
# AVR profile
# ---------------------------------------------------------------------------

class TestAvrProfile:
    def setup_method(self):
        self.profile = get_profile("avr")

    def test_compiler_is_avr_gcc(self):
        assert self.profile.compiler == "avr-gcc"

    def test_cxx_compiler_is_avr_gpp(self):
        assert self.profile.cxx_compiler == "avr-g++"

    def test_objcopy_is_avr_objcopy(self):
        assert self.profile.objcopy == "avr-objcopy"

    def test_output_format_is_hex(self):
        assert self.profile.output_format == "hex"

    def test_mcu_flags_uno(self):
        board = {"mcu": "ATmega328P", "arch": "avr"}
        flags = self.profile.mcu_flags_for_board(board)
        assert any("-mmcu" in f for f in flags)
        assert any("atmega328p" in f for f in flags)

    def test_mcu_flags_mega(self):
        board = {"mcu": "ATmega2560", "arch": "avr"}
        flags = self.profile.mcu_flags_for_board(board)
        assert any("atmega2560" in f for f in flags)

    def test_mcu_flags_lowercased(self):
        board = {"mcu": "ATmega32U4", "arch": "avr"}
        flags = self.profile.mcu_flags_for_board(board)
        # Verify it's lower-cased in the flag
        combined = " ".join(flags)
        assert "atmega32u4" in combined

    def test_all_c_flags_include_mmcu(self):
        board = {"mcu": "ATmega328P", "arch": "avr"}
        flags = self.profile.all_c_flags(board)
        combined = " ".join(flags)
        assert "-mmcu=atmega328p" in combined

    def test_c_flags_include_os(self):
        board = {"mcu": "ATmega328P", "arch": "avr"}
        flags = self.profile.all_c_flags(board)
        assert "-Os" in flags

    def test_cxx_flags_include_no_exceptions(self):
        board = {"mcu": "ATmega328P", "arch": "avr"}
        flags = self.profile.all_cxx_flags(board)
        assert "-fno-exceptions" in flags


# ---------------------------------------------------------------------------
# ARM CM0+ profile
# ---------------------------------------------------------------------------

class TestArmCm0PlusProfile:
    def setup_method(self):
        self.profile = get_profile("arm-cm0+")

    def test_compiler_is_arm_none_eabi_gcc(self):
        assert self.profile.compiler == "arm-none-eabi-gcc"

    def test_output_format_is_uf2(self):
        assert self.profile.output_format == "uf2"

    def test_mcu_flags_contain_mcpu_cortex_m0plus(self):
        board = {"mcu": "RP2040", "arch": "arm-cm0+"}
        flags = self.profile.mcu_flags_for_board(board)
        combined = " ".join(flags)
        assert "-mcpu=cortex-m0plus" in combined

    def test_mcu_flags_contain_mthumb(self):
        board = {"mcu": "RP2040", "arch": "arm-cm0+"}
        flags = self.profile.mcu_flags_for_board(board)
        assert "-mthumb" in flags

    def test_all_c_flags_include_mcpu(self):
        board = {"mcu": "RP2040", "arch": "arm-cm0+"}
        flags = self.profile.all_c_flags(board)
        assert "-mcpu=cortex-m0plus" in flags


# ---------------------------------------------------------------------------
# ARM CM4F profile
# ---------------------------------------------------------------------------

class TestArmCm4fProfile:
    def setup_method(self):
        self.profile = get_profile("arm-cm4f")

    def test_compiler_is_arm_none_eabi_gcc(self):
        assert self.profile.compiler == "arm-none-eabi-gcc"

    def test_output_format_is_bin(self):
        assert self.profile.output_format == "bin"

    def test_mcu_flags_contain_mcpu_cortex_m4(self):
        board = {"mcu": "STM32F411CEU6", "arch": "arm-cm4f"}
        flags = self.profile.mcu_flags_for_board(board)
        combined = " ".join(flags)
        assert "-mcpu=cortex-m4" in combined

    def test_mcu_flags_contain_fpu(self):
        board = {"mcu": "STM32F411CEU6", "arch": "arm-cm4f"}
        flags = self.profile.mcu_flags_for_board(board)
        assert "-mfpu=fpv4-sp-d16" in flags

    def test_mcu_flags_contain_hard_float_abi(self):
        board = {"mcu": "STM32F411CEU6", "arch": "arm-cm4f"}
        flags = self.profile.mcu_flags_for_board(board)
        assert "-mfloat-abi=hard" in flags

    def test_mcu_flags_contain_mthumb(self):
        board = {"mcu": "STM32F411CEU6", "arch": "arm-cm4f"}
        flags = self.profile.mcu_flags_for_board(board)
        assert "-mthumb" in flags


# ---------------------------------------------------------------------------
# ARM CM7 profile
# ---------------------------------------------------------------------------

class TestArmCm7Profile:
    def setup_method(self):
        self.profile = get_profile("arm-cm7")

    def test_compiler_is_arm_none_eabi_gcc(self):
        assert self.profile.compiler == "arm-none-eabi-gcc"

    def test_output_format_is_hex(self):
        assert self.profile.output_format == "hex"

    def test_mcu_flags_contain_mcpu_cortex_m7(self):
        board = {"mcu": "IMXRT1062", "arch": "arm-cm7"}
        flags = self.profile.mcu_flags_for_board(board)
        combined = " ".join(flags)
        assert "-mcpu=cortex-m7" in combined

    def test_mcu_flags_contain_fpv5(self):
        board = {"mcu": "IMXRT1062", "arch": "arm-cm7"}
        flags = self.profile.mcu_flags_for_board(board)
        assert "-mfpu=fpv5-d16" in flags

    def test_mcu_flags_contain_mthumb(self):
        board = {"mcu": "IMXRT1062", "arch": "arm-cm7"}
        flags = self.profile.mcu_flags_for_board(board)
        assert "-mthumb" in flags


# ---------------------------------------------------------------------------
# Xtensa LX7 profile
# ---------------------------------------------------------------------------

class TestXtensaProfile:
    def setup_method(self):
        self.profile = get_profile("xtensa")

    def test_compiler_is_xtensa_esp32_elf_gcc(self):
        assert "xtensa" in self.profile.compiler

    def test_output_format_is_bin(self):
        assert self.profile.output_format == "bin"

    def test_mcu_flags_contain_mlongcalls(self):
        board = {"mcu": "ESP32", "arch": "xtensa"}
        flags = self.profile.mcu_flags_for_board(board)
        assert "-mlongcalls" in flags

    def test_all_c_flags_include_mlongcalls(self):
        board = {"mcu": "ESP32", "arch": "xtensa"}
        flags = self.profile.all_c_flags(board)
        assert "-mlongcalls" in flags


# ---------------------------------------------------------------------------
# RISC-V 32IMC profile
# ---------------------------------------------------------------------------

class TestRiscv32imcProfile:
    def setup_method(self):
        self.profile = get_profile("riscv32imc")

    def test_compiler_contains_riscv(self):
        assert "riscv" in self.profile.compiler

    def test_output_format_is_bin(self):
        assert self.profile.output_format == "bin"

    def test_mcu_flags_contain_march_rv32imc(self):
        board = {"mcu": "ESP32-C3", "arch": "riscv32imc"}
        flags = self.profile.mcu_flags_for_board(board)
        combined = " ".join(flags)
        assert "-march=rv32imc" in combined

    def test_mcu_flags_contain_mabi_ilp32(self):
        board = {"mcu": "ESP32-C3", "arch": "riscv32imc"}
        flags = self.profile.mcu_flags_for_board(board)
        assert "-mabi=ilp32" in flags

    def test_all_c_flags_include_march(self):
        board = {"mcu": "ESP32-C3", "arch": "riscv32imc"}
        flags = self.profile.all_c_flags(board)
        assert "-march=rv32imc" in flags


# ---------------------------------------------------------------------------
# Link flags
# ---------------------------------------------------------------------------

class TestLinkFlags:
    def test_avr_link_flags_include_gc_sections(self):
        profile = get_profile("avr")
        assert any("--gc-sections" in f for f in profile.link_flags)

    def test_arm_cm4f_link_flags_include_gc_sections(self):
        profile = get_profile("arm-cm4f")
        assert any("--gc-sections" in f for f in profile.link_flags)

    def test_arm_cm4f_link_flags_include_nosys_specs(self):
        profile = get_profile("arm-cm4f")
        assert any("nosys.specs" in f for f in profile.link_flags)


# ---------------------------------------------------------------------------
# mcu_flags_for_board with missing mcu field
# ---------------------------------------------------------------------------

class TestMissingMcuField:
    def test_avr_empty_mcu_returns_empty_list(self):
        profile = get_profile("avr")
        flags = profile.mcu_flags_for_board({})
        assert flags == []

    def test_arm_profile_ignores_mcu_field(self):
        profile = get_profile("arm-cm4f")
        # ARM profiles derive flags from the profile, not the board mcu
        flags = profile.mcu_flags_for_board({})
        assert "-mcpu=cortex-m4" in flags
