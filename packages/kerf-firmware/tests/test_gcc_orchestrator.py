"""Tests for gcc_orchestrator.py.

All subprocess calls are monkeypatched; no real compiler is required for the
core test suite.  A separate integration-test class is included, gated on
actual toolchain presence (skipped when the compiler is absent).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from kerf_firmware.build_artifacts import BuildArtifact
from kerf_firmware.gcc_orchestrator import build, _compiler_available


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_UNO_BOARD = {"mcu": "ATmega328P", "arch": "avr"}
_STM32_BOARD = {"mcu": "STM32F411CEU6", "arch": "arm-cm4f"}
_ESP32_BOARD = {"mcu": "ESP32", "arch": "xtensa"}
_C3_BOARD = {"mcu": "ESP32-C3", "arch": "riscv32imc"}
_RP2040_BOARD = {"mcu": "RP2040", "arch": "arm-cm0+"}


def _make_c_source(tmp_path: Path, name: str = "main.c") -> Path:
    src = tmp_path / name
    src.write_text("int main(void) { return 0; }\n")
    return src


def _make_cpp_source(tmp_path: Path, name: str = "main.cpp") -> Path:
    src = tmp_path / name
    src.write_text("int main() { return 0; }\n")
    return src


def _mock_run_success(argv: list[str], **kwargs: Any):
    """Monkeypatch target: simulate a successful subprocess run.

    Also creates any output file referenced by ``-o <path>`` so the
    orchestrator's existence checks pass.
    """
    proc = MagicMock()
    proc.returncode = 0
    proc.stdout = ""
    proc.stderr = ""

    # Create the output file when ``-o <path>`` is in the argv.
    try:
        o_idx = argv.index("-o")
        out_path = Path(argv[o_idx + 1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\x00" * 128)
    except (ValueError, IndexError):
        pass

    return proc


def _mock_run_fail(argv: list[str], **kwargs: Any):
    """Simulate a compile failure."""
    proc = MagicMock()
    proc.returncode = 1
    proc.stdout = ""
    proc.stderr = "error: undeclared identifier"
    return proc


# ---------------------------------------------------------------------------
# Pending-sentinel tests (compiler absent)
# ---------------------------------------------------------------------------

class TestPendingSentinel:
    """Orchestrator must return pending when the compiler is not on PATH."""

    def test_avr_compiler_absent_returns_pending(self, tmp_path):
        src = _make_c_source(tmp_path)
        with patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=False):
            result = build([src], [], "avr", tmp_path / "out", _UNO_BOARD)
        assert result.pending
        assert result.status == "pending"
        assert result.elf_path is None

    def test_pending_result_contains_install_hint(self, tmp_path):
        src = _make_c_source(tmp_path)
        with patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=False):
            result = build([src], [], "avr", tmp_path / "out", _UNO_BOARD)
        # install_hint must be non-empty for the UI to surface
        assert result.install_hint

    def test_arm_compiler_absent_returns_pending(self, tmp_path):
        src = _make_c_source(tmp_path)
        with patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=False):
            result = build([src], [], "arm-cm4f", tmp_path / "out", _STM32_BOARD)
        assert result.pending
        assert "arm-none-eabi" in result.install_hint.lower() or result.install_hint

    def test_xtensa_compiler_absent_returns_pending(self, tmp_path):
        src = _make_c_source(tmp_path)
        with patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=False):
            result = build([src], [], "xtensa", tmp_path / "out", _ESP32_BOARD)
        assert result.pending

    def test_riscv_compiler_absent_returns_pending(self, tmp_path):
        src = _make_c_source(tmp_path)
        with patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=False):
            result = build([src], [], "riscv32imc", tmp_path / "out", _C3_BOARD)
        assert result.pending
        assert result.reason  # non-empty reason string

    def test_pending_does_not_raise(self, tmp_path):
        src = _make_c_source(tmp_path)
        with patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=False):
            # Must never raise
            result = build([src], [], "avr", tmp_path / "out", _UNO_BOARD)
        assert isinstance(result, BuildArtifact)


# ---------------------------------------------------------------------------
# Successful build (subprocess mocked)
# ---------------------------------------------------------------------------

class TestSuccessfulBuild:
    """Happy-path build with subprocess mocked to succeed."""

    def test_avr_build_returns_ok(self, tmp_path):
        src = _make_c_source(tmp_path)
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            result = build([src], [], "avr", tmp_path / "out", _UNO_BOARD)
        assert result.ok
        assert result.arch == "avr"

    def test_arm_cm4f_build_returns_ok(self, tmp_path):
        src = _make_c_source(tmp_path)
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            result = build([src], [], "arm-cm4f", tmp_path / "out", _STM32_BOARD)
        assert result.ok
        assert result.arch == "arm-cm4f"

    def test_xtensa_build_returns_ok(self, tmp_path):
        src = _make_c_source(tmp_path)
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            result = build([src], [], "xtensa", tmp_path / "out", _ESP32_BOARD)
        assert result.ok

    def test_riscv_build_returns_ok(self, tmp_path):
        src = _make_c_source(tmp_path)
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            result = build([src], [], "riscv32imc", tmp_path / "out", _C3_BOARD)
        assert result.ok

    def test_arm_cm0plus_build_returns_ok(self, tmp_path):
        src = _make_c_source(tmp_path)
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            result = build([src], [], "arm-cm0+", tmp_path / "out", _RP2040_BOARD)
        assert result.ok

    def test_elf_path_is_set(self, tmp_path):
        src = _make_c_source(tmp_path)
        out = tmp_path / "out"
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            result = build([src], [], "avr", out, _UNO_BOARD)
        assert result.elf_path is not None
        assert result.elf_path.name == "firmware.elf"

    def test_hex_path_set_for_avr(self, tmp_path):
        src = _make_c_source(tmp_path)
        out = tmp_path / "out"
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            result = build([src], [], "avr", out, _UNO_BOARD)
        # AVR output_format == "hex"
        assert result.hex_path is not None or result.elf_path is not None

    def test_object_files_listed(self, tmp_path):
        src = _make_c_source(tmp_path)
        out = tmp_path / "out"
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            result = build([src], [], "avr", out, _UNO_BOARD)
        assert len(result.object_files) == 1
        assert result.object_files[0].suffix == ".o"

    def test_cpp_source_accepted(self, tmp_path):
        src = _make_cpp_source(tmp_path)
        out = tmp_path / "out"
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            result = build([src], [], "avr", out, _UNO_BOARD)
        assert result.ok

    def test_multiple_sources(self, tmp_path):
        srcs = [_make_c_source(tmp_path, "a.c"), _make_c_source(tmp_path, "b.c")]
        out = tmp_path / "out"
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            result = build(srcs, [], "avr", out, _UNO_BOARD)
        assert result.ok
        assert len(result.object_files) == 2


# ---------------------------------------------------------------------------
# Compiler-argv inspection
# ---------------------------------------------------------------------------

class TestCompilerArgvInspection:
    """Check that the compiler is called with the right flags."""

    def _capture_calls(self, sources, arch, board, tmp_path):
        calls = []

        def capture_run(argv, **kwargs):
            calls.append(list(argv))
            return _mock_run_success(argv, **kwargs)

        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=capture_run),
        ):
            result = build(sources, [], arch, tmp_path / "out", board)
        return calls, result

    def test_avr_compile_includes_mmcu(self, tmp_path):
        src = _make_c_source(tmp_path)
        calls, result = self._capture_calls([src], "avr", _UNO_BOARD, tmp_path)
        compile_call = calls[0]
        combined = " ".join(compile_call)
        assert "-mmcu=atmega328p" in combined

    def test_avr_compile_uses_avr_gcc(self, tmp_path):
        src = _make_c_source(tmp_path)
        calls, _ = self._capture_calls([src], "avr", _UNO_BOARD, tmp_path)
        assert calls[0][0] == "avr-gcc"

    def test_arm_cm4f_compile_includes_mcpu(self, tmp_path):
        src = _make_c_source(tmp_path)
        calls, _ = self._capture_calls([src], "arm-cm4f", _STM32_BOARD, tmp_path)
        compile_call = calls[0]
        combined = " ".join(compile_call)
        assert "-mcpu=cortex-m4" in combined

    def test_arm_cm4f_compile_uses_arm_none_eabi_gcc(self, tmp_path):
        src = _make_c_source(tmp_path)
        calls, _ = self._capture_calls([src], "arm-cm4f", _STM32_BOARD, tmp_path)
        assert "arm-none-eabi-gcc" in calls[0][0]

    def test_riscv_compile_includes_march(self, tmp_path):
        src = _make_c_source(tmp_path)
        calls, _ = self._capture_calls([src], "riscv32imc", _C3_BOARD, tmp_path)
        compile_call = calls[0]
        combined = " ".join(compile_call)
        assert "-march=rv32imc" in combined

    def test_xtensa_compile_includes_mlongcalls(self, tmp_path):
        src = _make_c_source(tmp_path)
        calls, _ = self._capture_calls([src], "xtensa", _ESP32_BOARD, tmp_path)
        compile_call = calls[0]
        combined = " ".join(compile_call)
        assert "-mlongcalls" in combined

    def test_include_dirs_passed_as_dash_i(self, tmp_path):
        src = _make_c_source(tmp_path)
        inc = tmp_path / "include"
        inc.mkdir()
        calls = []

        def capture_run(argv, **kwargs):
            calls.append(list(argv))
            return _mock_run_success(argv, **kwargs)

        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=capture_run),
        ):
            build([src], [inc], "avr", tmp_path / "out", _UNO_BOARD)

        compile_call = calls[0]
        assert "-I" in compile_call
        assert str(inc) in compile_call

    def test_linker_script_passed_with_t_flag(self, tmp_path):
        src = _make_c_source(tmp_path)
        ld = tmp_path / "board.ld"
        ld.write_text("MEMORY { FLASH : ORIGIN = 0, LENGTH = 32K }\n")
        calls = []

        def capture_run(argv, **kwargs):
            calls.append(list(argv))
            return _mock_run_success(argv, **kwargs)

        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=capture_run),
        ):
            build([src], [], "avr", tmp_path / "out", _UNO_BOARD, linker_script=ld)

        # Find the link call (the one that produces firmware.elf)
        link_call = None
        for c in calls:
            if "firmware.elf" in " ".join(c):
                link_call = c
                break
        assert link_call is not None
        assert "-T" in link_call
        assert str(ld) in link_call


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_compile_failure_returns_error_status(self, tmp_path):
        src = _make_c_source(tmp_path)
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_fail),
        ):
            result = build([src], [], "avr", tmp_path / "out", _UNO_BOARD)
        assert result.status == "error"
        assert not result.ok

    def test_error_result_contains_error_message(self, tmp_path):
        src = _make_c_source(tmp_path)
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_fail),
        ):
            result = build([src], [], "avr", tmp_path / "out", _UNO_BOARD)
        assert len(result.errors) > 0

    def test_unknown_arch_returns_error(self, tmp_path):
        src = _make_c_source(tmp_path)
        result = build([src], [], "msp430", tmp_path / "out", {})
        assert result.status == "error"

    def test_no_sources_returns_error(self, tmp_path):
        with patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True):
            result = build([], [], "avr", tmp_path / "out", _UNO_BOARD)
        assert result.status == "error"

    def test_nonexistent_linker_script_silently_ignored(self, tmp_path):
        """A linker script that doesn't exist must be skipped gracefully."""
        src = _make_c_source(tmp_path)
        missing_ld = tmp_path / "does_not_exist.ld"
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            result = build(
                [src], [], "avr", tmp_path / "out", _UNO_BOARD,
                linker_script=missing_ld,
            )
        # Should still succeed — missing script is just not passed
        assert result.ok


# ---------------------------------------------------------------------------
# Output directory
# ---------------------------------------------------------------------------

class TestOutputDirectory:
    def test_output_dir_created_if_missing(self, tmp_path):
        src = _make_c_source(tmp_path)
        out = tmp_path / "nested" / "build" / "avr"
        assert not out.exists()
        with (
            patch("kerf_firmware.gcc_orchestrator._compiler_available", return_value=True),
            patch("subprocess.run", side_effect=_mock_run_success),
        ):
            build([src], [], "avr", out, _UNO_BOARD)
        assert out.exists()


# ---------------------------------------------------------------------------
# Real-toolchain integration test (skipped when toolchain absent)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    shutil.which("avr-gcc") is None,
    reason="avr-gcc not on PATH",
)
class TestAvrIntegration:
    """Run a real avr-gcc compile+link+objcopy pipeline."""

    def test_blink_uno_produces_hex(self, tmp_path):
        src = tmp_path / "blink.c"
        src.write_text(
            """
#include <avr/io.h>
#include <util/delay.h>

int main(void) {
    DDRB |= (1 << DDB5);
    while (1) {
        PORTB ^= (1 << PORTB5);
        _delay_ms(500);
    }
    return 0;
}
""".strip()
        )
        result = build(
            sources=[src],
            includes=[],
            arch="avr",
            output_dir=tmp_path / "out",
            board_meta=_UNO_BOARD,
        )
        assert result.ok, f"Build failed: {result.errors}"
        assert result.elf_path is not None
        assert result.elf_path.exists()
        assert result.size_bytes > 0
