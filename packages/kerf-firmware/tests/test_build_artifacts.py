"""Tests for build_artifacts.py — BuildArtifact dataclass."""

from pathlib import Path

import pytest

from kerf_firmware.build_artifacts import BuildArtifact


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestBuildArtifactConstruction:
    def test_ok_artifact_has_correct_status(self):
        art = BuildArtifact(
            status="ok",
            arch="avr",
            elf_path=Path("/tmp/firmware.elf"),
            hex_path=Path("/tmp/firmware.hex"),
            size_bytes=8192,
        )
        assert art.ok is True
        assert art.pending is False
        assert art.status == "ok"

    def test_pending_artifact(self):
        art = BuildArtifact(status="pending", arch="arm-cm4f")
        assert art.pending is True
        assert art.ok is False

    def test_error_artifact(self):
        art = BuildArtifact(status="error", arch="xtensa", reason="link failed")
        assert art.ok is False
        assert art.pending is False

    def test_default_lists_are_empty(self):
        art = BuildArtifact(status="ok", arch="avr")
        assert art.object_files == []
        assert art.warnings == []
        assert art.errors == []

    def test_size_bytes_default_is_zero(self):
        art = BuildArtifact(status="ok", arch="avr")
        assert art.size_bytes == 0


# ---------------------------------------------------------------------------
# Sentinel constructors
# ---------------------------------------------------------------------------

class TestSentinelConstructors:
    def test_pending_sentinel_sets_status(self):
        s = BuildArtifact.pending_sentinel(
            arch="riscv32imc",
            reason="riscv-none-elf-gcc not found",
            install_hint="brew install riscv-gnu-toolchain",
        )
        assert s.status == "pending"
        assert s.arch == "riscv32imc"
        assert "riscv-none-elf-gcc" in s.reason
        assert "brew" in s.install_hint
        assert s.elf_path is None
        assert s.hex_path is None

    def test_pending_sentinel_without_hint(self):
        s = BuildArtifact.pending_sentinel(arch="avr", reason="no compiler")
        assert s.install_hint == ""

    def test_error_sentinel_sets_status(self):
        s = BuildArtifact.error_sentinel(
            arch="arm-cm0+",
            reason="link failed",
            errors=["undefined reference to main"],
        )
        assert s.status == "error"
        assert s.arch == "arm-cm0+"
        assert len(s.errors) == 1
        assert "undefined reference" in s.errors[0]

    def test_error_sentinel_default_empty_errors(self):
        s = BuildArtifact.error_sentinel(arch="avr", reason="compile error")
        assert s.errors == []


# ---------------------------------------------------------------------------
# primary_path helper
# ---------------------------------------------------------------------------

class TestPrimaryPath:
    def test_prefers_hex_over_bin(self):
        art = BuildArtifact(
            status="ok",
            arch="avr",
            hex_path=Path("/tmp/firmware.hex"),
            bin_path=Path("/tmp/firmware.bin"),
        )
        assert art.primary_path() == Path("/tmp/firmware.hex")

    def test_falls_back_to_bin(self):
        art = BuildArtifact(
            status="ok",
            arch="arm-cm4f",
            bin_path=Path("/tmp/firmware.bin"),
            elf_path=Path("/tmp/firmware.elf"),
        )
        assert art.primary_path() == Path("/tmp/firmware.bin")

    def test_falls_back_to_uf2(self):
        art = BuildArtifact(
            status="ok",
            arch="arm-cm0+",
            uf2_path=Path("/tmp/firmware.uf2"),
            elf_path=Path("/tmp/firmware.elf"),
        )
        assert art.primary_path() == Path("/tmp/firmware.uf2")

    def test_falls_back_to_elf(self):
        art = BuildArtifact(
            status="ok",
            arch="avr",
            elf_path=Path("/tmp/firmware.elf"),
        )
        assert art.primary_path() == Path("/tmp/firmware.elf")

    def test_returns_none_when_all_paths_missing(self):
        art = BuildArtifact(status="pending", arch="avr")
        assert art.primary_path() is None


# ---------------------------------------------------------------------------
# Field mutation isolation (lists should not share references)
# ---------------------------------------------------------------------------

class TestListIsolation:
    def test_object_files_are_independent(self):
        a = BuildArtifact(status="ok", arch="avr")
        b = BuildArtifact(status="ok", arch="avr")
        a.object_files.append(Path("/tmp/foo.o"))
        assert b.object_files == []

    def test_errors_are_independent(self):
        a = BuildArtifact(status="error", arch="avr")
        b = BuildArtifact(status="error", arch="avr")
        a.errors.append("something went wrong")
        assert b.errors == []
