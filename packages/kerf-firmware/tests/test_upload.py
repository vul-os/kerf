"""
tests/test_upload.py — hermetic tests for kerf_firmware.upload wrappers.

Strategy:
  - Monkeypatch subprocess.run to verify the argv passed to each tool.
  - Monkeypatch shutil.which to simulate missing binaries (status="pending").
  - Router tests verify the correct wrapper is selected for each board.
  - All tests are fully offline — no real serial port or tool binary required.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_proc(returncode: int = 0, stdout: str = "OK", stderr: str = "") -> MagicMock:
    """Create a mock subprocess.CompletedProcess."""
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def _board(
    mcu: str = "ATmega328P",
    platform: str = "atmelavr",
    upload_protocol: str = "arduino",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "mcu": mcu,
        "platform": platform,
        "upload_protocol": upload_protocol,
        **extra,
    }


# ---------------------------------------------------------------------------
# T1 — avrdude wrapper
# ---------------------------------------------------------------------------


class TestAvrdude:
    def test_happy_path_argv(self, monkeypatch):
        """avrdude is called with the correct partno, programmer, port, and file."""
        captured: list[list[str]] = []

        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/avrdude" if name == "avrdude" else None)
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(0, "avrdude done", ""),
        )

        # Re-import to pick up monkeypatched shutil.which
        sys.modules.pop("kerf_firmware.upload.avrdude", None)
        from kerf_firmware.upload.avrdude import upload

        result = upload(
            "/tmp/firmware.hex",
            "/dev/ttyACM0",
            _board(mcu="ATmega328P", upload_protocol="arduino"),
        )

        assert result.ok
        assert result.status == "ok"
        assert len(captured) == 1
        argv = captured[0]
        assert argv[0] == "/usr/bin/avrdude"
        assert "-p" in argv
        assert "atmega328p" in argv
        assert "-c" in argv
        assert "arduino" in argv
        assert "-P" in argv
        assert "/dev/ttyACM0" in argv
        assert any("firmware.hex" in arg for arg in argv)

    def test_missing_binary_returns_pending(self, monkeypatch):
        """Returns status='pending' when avrdude is absent from PATH."""
        monkeypatch.setattr("shutil.which", lambda name: None)
        sys.modules.pop("kerf_firmware.upload.avrdude", None)
        from kerf_firmware.upload.avrdude import upload

        result = upload("/tmp/firmware.hex", "/dev/ttyACM0", _board())

        assert not result.ok
        assert result.status == "pending"
        assert "avrdude" in result.reason.lower()
        assert result.stdout == ""
        assert result.stderr == ""

    def test_nonzero_exit_returns_error(self, monkeypatch):
        """Returns status='error' when avrdude exits non-zero."""
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/avrdude" if name == "avrdude" else None)
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: _make_proc(1, "", "avrdude: error: programmer not responding"),
        )
        sys.modules.pop("kerf_firmware.upload.avrdude", None)
        from kerf_firmware.upload.avrdude import upload

        result = upload("/tmp/firmware.hex", "/dev/ttyACM0", _board())

        assert not result.ok
        assert result.status == "error"
        assert "1" in result.reason

    def test_wiring_protocol_uses_wiring_programmer(self, monkeypatch):
        """Mega 2560 upload_protocol='wiring' maps to programmer 'wiring'."""
        captured: list[list[str]] = []
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/avrdude" if name == "avrdude" else None)
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(),
        )
        sys.modules.pop("kerf_firmware.upload.avrdude", None)
        from kerf_firmware.upload.avrdude import upload

        upload(
            "/tmp/firmware.hex",
            "/dev/ttyUSB0",
            _board(mcu="ATmega2560", upload_protocol="wiring"),
        )

        argv = captured[0]
        assert "wiring" in argv

    def test_bin_file_uses_raw_format(self, monkeypatch):
        """A .bin firmware path uses ':r' (raw) format flag."""
        captured: list[list[str]] = []
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/avrdude" if name == "avrdude" else None)
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(),
        )
        sys.modules.pop("kerf_firmware.upload.avrdude", None)
        from kerf_firmware.upload.avrdude import upload

        upload("/tmp/firmware.bin", "/dev/ttyACM0", _board())

        argv = captured[0]
        flash_arg = next(a for a in argv if "flash:w:" in a)
        assert flash_arg.endswith(":r")

    def test_hex_file_uses_intel_format(self, monkeypatch):
        """A .hex firmware path uses ':i' (Intel HEX) format flag."""
        captured: list[list[str]] = []
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/avrdude" if name == "avrdude" else None)
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(),
        )
        sys.modules.pop("kerf_firmware.upload.avrdude", None)
        from kerf_firmware.upload.avrdude import upload

        upload("/tmp/firmware.hex", "/dev/ttyACM0", _board())

        argv = captured[0]
        flash_arg = next(a for a in argv if "flash:w:" in a)
        assert flash_arg.endswith(":i")

    def test_result_contains_stdout_stderr(self, monkeypatch):
        """UploadResult.stdout and .stderr reflect subprocess output."""
        monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/avrdude" if name == "avrdude" else None)
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: _make_proc(0, "flash written\n", "avrdude: 1234 bytes\n"),
        )
        sys.modules.pop("kerf_firmware.upload.avrdude", None)
        from kerf_firmware.upload.avrdude import upload

        result = upload("/tmp/firmware.hex", "/dev/ttyACM0", _board())

        assert "flash written" in result.stdout
        assert "1234" in result.stderr


# ---------------------------------------------------------------------------
# T2 — esptool wrapper
# ---------------------------------------------------------------------------


class TestEsptool:
    def test_happy_path_argv(self, monkeypatch):
        """esptool.py is called with chip, port, baud, and file."""
        captured: list[list[str]] = []

        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/local/bin/esptool.py" if name == "esptool.py" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(),
        )
        sys.modules.pop("kerf_firmware.upload.esptool", None)
        from kerf_firmware.upload.esptool import upload

        result = upload(
            "/tmp/firmware.bin",
            "/dev/ttyUSB0",
            _board(mcu="ESP32", platform="espressif32", upload_protocol="esptool"),
        )

        assert result.ok
        assert result.status == "ok"
        argv = captured[0]
        assert "--chip" in argv
        assert "esp32" in argv
        assert "--port" in argv
        assert "/dev/ttyUSB0" in argv
        assert "write_flash" in argv
        assert "/tmp/firmware.bin" in argv

    def test_missing_binary_returns_pending(self, monkeypatch):
        """Returns status='pending' when no esptool binary is on PATH."""
        monkeypatch.setattr("shutil.which", lambda name: None)
        sys.modules.pop("kerf_firmware.upload.esptool", None)
        from kerf_firmware.upload.esptool import upload

        result = upload("/tmp/firmware.bin", "/dev/ttyUSB0", _board(mcu="ESP32"))

        assert not result.ok
        assert result.status == "pending"
        assert "esptool" in result.reason.lower()

    def test_esp8266_chip_name(self, monkeypatch):
        """ESP8266 MCU maps to chip 'esp8266'."""
        captured: list[list[str]] = []
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/local/bin/esptool.py" if name == "esptool.py" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(),
        )
        sys.modules.pop("kerf_firmware.upload.esptool", None)
        from kerf_firmware.upload.esptool import upload

        upload("/tmp/fw.bin", "/dev/ttyUSB0", _board(mcu="ESP8266", platform="espressif8266"))

        argv = captured[0]
        assert "esp8266" in argv

    def test_fallback_binary_esptool(self, monkeypatch):
        """Falls back to 'esptool' when 'esptool.py' is not found."""
        captured: list[list[str]] = []

        def fake_which(name: str) -> str | None:
            if name == "esptool":
                return "/usr/local/bin/esptool"
            return None

        monkeypatch.setattr("shutil.which", fake_which)
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(),
        )
        sys.modules.pop("kerf_firmware.upload.esptool", None)
        from kerf_firmware.upload.esptool import upload

        result = upload("/tmp/fw.bin", "/dev/ttyUSB0", _board(mcu="ESP32"))

        assert result.ok
        assert captured[0][0] == "/usr/local/bin/esptool"

    def test_nonzero_exit_returns_error(self, monkeypatch):
        """Returns status='error' when esptool exits non-zero."""
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/local/bin/esptool.py" if name == "esptool.py" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: _make_proc(2, "", "FAILED to connect"),
        )
        sys.modules.pop("kerf_firmware.upload.esptool", None)
        from kerf_firmware.upload.esptool import upload

        result = upload("/tmp/fw.bin", "/dev/ttyUSB0", _board(mcu="ESP32"))

        assert not result.ok
        assert result.status == "error"


# ---------------------------------------------------------------------------
# T3 — stm32flash wrapper
# ---------------------------------------------------------------------------


class TestStm32flash:
    def test_happy_path_argv(self, monkeypatch):
        """stm32flash is called with baud, file, verify, and port."""
        captured: list[list[str]] = []

        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/bin/stm32flash" if name == "stm32flash" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(0, "stm32flash done", ""),
        )
        sys.modules.pop("kerf_firmware.upload.stm32flash", None)
        from kerf_firmware.upload.stm32flash import upload

        result = upload(
            "/tmp/firmware.bin",
            "/dev/ttyUSB0",
            _board(mcu="STM32F103C8", platform="ststm32", upload_protocol="serial"),
        )

        assert result.ok
        assert result.status == "ok"
        argv = captured[0]
        assert argv[0] == "/usr/bin/stm32flash"
        assert "-w" in argv
        assert "/tmp/firmware.bin" in argv
        assert "-v" in argv
        assert "/dev/ttyUSB0" in argv

    def test_missing_binary_returns_pending(self, monkeypatch):
        """Returns status='pending' when stm32flash is absent from PATH."""
        monkeypatch.setattr("shutil.which", lambda name: None)
        sys.modules.pop("kerf_firmware.upload.stm32flash", None)
        from kerf_firmware.upload.stm32flash import upload

        result = upload("/tmp/fw.bin", "/dev/ttyUSB0", _board(mcu="STM32F103C8"))

        assert not result.ok
        assert result.status == "pending"
        assert "stm32flash" in result.reason.lower()

    def test_baud_passed_correctly(self, monkeypatch):
        """upload_speed in board_meta is forwarded as -b <baud>."""
        captured: list[list[str]] = []
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/bin/stm32flash" if name == "stm32flash" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(),
        )
        sys.modules.pop("kerf_firmware.upload.stm32flash", None)
        from kerf_firmware.upload.stm32flash import upload

        upload(
            "/tmp/fw.bin",
            "/dev/ttyUSB0",
            _board(mcu="STM32F103C8", upload_speed=57600),
        )

        argv = captured[0]
        assert "-b" in argv
        baud_idx = argv.index("-b")
        assert argv[baud_idx + 1] == "57600"

    def test_nonzero_exit_returns_error(self, monkeypatch):
        """Returns status='error' when stm32flash exits non-zero."""
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/bin/stm32flash" if name == "stm32flash" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: _make_proc(1, "", "failed to init device"),
        )
        sys.modules.pop("kerf_firmware.upload.stm32flash", None)
        from kerf_firmware.upload.stm32flash import upload

        result = upload("/tmp/fw.bin", "/dev/ttyUSB0", _board(mcu="STM32F103C8"))

        assert not result.ok
        assert result.status == "error"


# ---------------------------------------------------------------------------
# T4 — bossac wrapper
# ---------------------------------------------------------------------------


class TestBossac:
    def test_happy_path_argv(self, monkeypatch):
        """bossac is called with port, erase, write, verify, reset flags."""
        captured: list[list[str]] = []

        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/local/bin/bossac" if name == "bossac" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(0, "Upload complete", ""),
        )
        sys.modules.pop("kerf_firmware.upload.bossac", None)
        from kerf_firmware.upload.bossac import upload

        result = upload(
            "/tmp/firmware.bin",
            "/dev/ttyACM0",
            _board(mcu="SAMD21", platform="atmelsam", upload_protocol="sam-ba"),
        )

        assert result.ok
        assert result.status == "ok"
        argv = captured[0]
        assert argv[0] == "/usr/local/bin/bossac"
        assert any("--port=" in a for a in argv)
        assert "--erase" in argv
        assert any("--write=" in a for a in argv)
        assert "--verify" in argv
        assert "--reset" in argv

    def test_missing_binary_returns_pending(self, monkeypatch):
        """Returns status='pending' when bossac is absent from PATH."""
        monkeypatch.setattr("shutil.which", lambda name: None)
        sys.modules.pop("kerf_firmware.upload.bossac", None)
        from kerf_firmware.upload.bossac import upload

        result = upload("/tmp/fw.bin", "/dev/ttyACM0", _board(mcu="SAMD21"))

        assert not result.ok
        assert result.status == "pending"
        assert "bossac" in result.reason.lower()

    def test_port_dev_prefix_stripped(self, monkeypatch):
        """bossac receives the port without the /dev/ prefix."""
        captured: list[list[str]] = []
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/local/bin/bossac" if name == "bossac" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(),
        )
        sys.modules.pop("kerf_firmware.upload.bossac", None)
        from kerf_firmware.upload.bossac import upload

        upload("/tmp/fw.bin", "/dev/ttyACM0", _board(mcu="SAMD21"))

        argv = captured[0]
        port_arg = next(a for a in argv if "--port=" in a)
        assert port_arg == "--port=ttyACM0"

    def test_windows_port_not_stripped(self, monkeypatch):
        """COM3 is passed as-is (no /dev/ prefix to strip)."""
        captured: list[list[str]] = []
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "C:\\tools\\bossac.exe" if name == "bossac" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(),
        )
        sys.modules.pop("kerf_firmware.upload.bossac", None)
        from kerf_firmware.upload.bossac import upload

        upload("/tmp/fw.bin", "COM3", _board(mcu="SAMD21"))

        argv = captured[0]
        port_arg = next(a for a in argv if "--port=" in a)
        assert port_arg == "--port=COM3"

    def test_mcu_offset_samd51(self, monkeypatch):
        """SAMD51 uses flash offset 0x4000."""
        captured: list[list[str]] = []
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/local/bin/bossac" if name == "bossac" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(),
        )
        sys.modules.pop("kerf_firmware.upload.bossac", None)
        from kerf_firmware.upload.bossac import upload

        upload("/tmp/fw.bin", "/dev/ttyACM0", _board(mcu="SAMD51"))

        argv = captured[0]
        offset_arg = next(a for a in argv if "--offset=" in a)
        assert offset_arg == "--offset=0x4000"

    def test_nonzero_exit_returns_error(self, monkeypatch):
        """Returns status='error' when bossac exits non-zero."""
        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/local/bin/bossac" if name == "bossac" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: _make_proc(1, "", "No device found"),
        )
        sys.modules.pop("kerf_firmware.upload.bossac", None)
        from kerf_firmware.upload.bossac import upload

        result = upload("/tmp/fw.bin", "/dev/ttyACM0", _board(mcu="SAMD21"))

        assert not result.ok
        assert result.status == "error"


# ---------------------------------------------------------------------------
# T5 — router
# ---------------------------------------------------------------------------


class TestRouter:
    """Router picks the correct wrapper based on board_meta."""

    def setup_method(self):
        # Ensure all upload modules are freshly imported each test.
        for mod in list(sys.modules):
            if "kerf_firmware.upload" in mod:
                sys.modules.pop(mod, None)

    def _patch_all_missing(self, monkeypatch):
        """Make all tool binaries absent so we get 'pending' results."""
        monkeypatch.setattr("shutil.which", lambda name: None)

    def test_avr_platform_routes_to_avrdude(self, monkeypatch):
        """atmelavr platform → avrdude (returns pending when absent)."""
        self._patch_all_missing(monkeypatch)
        from kerf_firmware.upload.router import route_upload

        result = route_upload(
            "/tmp/fw.hex",
            "/dev/ttyACM0",
            _board(mcu="ATmega328P", platform="atmelavr", upload_protocol="arduino"),
        )

        assert result.status == "pending"
        assert "avrdude" in result.reason.lower()

    def test_xtensa_platform_routes_to_esptool(self, monkeypatch):
        """espressif32 platform (Xtensa arch) → esptool."""
        self._patch_all_missing(monkeypatch)
        from kerf_firmware.upload.router import route_upload

        result = route_upload(
            "/tmp/fw.bin",
            "/dev/ttyUSB0",
            _board(mcu="ESP32", platform="espressif32", upload_protocol="esptool"),
        )

        assert result.status == "pending"
        assert "esptool" in result.reason.lower()

    def test_esp8266_platform_routes_to_esptool(self, monkeypatch):
        """espressif8266 platform → esptool."""
        self._patch_all_missing(monkeypatch)
        from kerf_firmware.upload.router import route_upload

        result = route_upload(
            "/tmp/fw.bin",
            "/dev/ttyUSB0",
            _board(mcu="ESP8266", platform="espressif8266", upload_protocol="esptool"),
        )

        assert result.status == "pending"
        assert "esptool" in result.reason.lower()

    def test_stm32_platform_routes_to_stm32flash(self, monkeypatch):
        """ststm32 platform → stm32flash."""
        self._patch_all_missing(monkeypatch)
        from kerf_firmware.upload.router import route_upload

        result = route_upload(
            "/tmp/fw.bin",
            "/dev/ttyUSB0",
            _board(mcu="STM32F103C8", platform="ststm32", upload_protocol="stlink"),
        )

        assert result.status == "pending"
        assert "stm32flash" in result.reason.lower()

    def test_raspberrypi_platform_routes_to_bossac(self, monkeypatch):
        """raspberrypi platform (RP2040) → bossac."""
        self._patch_all_missing(monkeypatch)
        from kerf_firmware.upload.router import route_upload

        result = route_upload(
            "/tmp/fw.bin",
            "/dev/ttyACM0",
            _board(mcu="RP2040", platform="raspberrypi", upload_protocol="picotool"),
        )

        assert result.status == "pending"
        assert "bossac" in result.reason.lower()

    def test_protocol_takes_precedence_over_platform(self, monkeypatch):
        """upload_protocol='esptool' beats platform='atmelavr' (unusual but possible)."""
        self._patch_all_missing(monkeypatch)
        from kerf_firmware.upload.router import route_upload

        result = route_upload(
            "/tmp/fw.bin",
            "/dev/ttyUSB0",
            # Contrived: AVR platform but esptool protocol.
            _board(mcu="ATmega328P", platform="atmelavr", upload_protocol="esptool"),
        )

        assert result.status == "pending"
        assert "esptool" in result.reason.lower()

    def test_unknown_protocol_falls_back_to_platform(self, monkeypatch):
        """Unknown upload_protocol routes by platform instead."""
        self._patch_all_missing(monkeypatch)
        from kerf_firmware.upload.router import route_upload

        result = route_upload(
            "/tmp/fw.hex",
            "/dev/ttyACM0",
            # Contrived protocol, known platform.
            _board(mcu="ATmega328P", platform="atmelavr", upload_protocol="unknown_proto"),
        )

        assert result.status == "pending"
        assert "avrdude" in result.reason.lower()

    def test_completely_unknown_defaults_to_avrdude(self, monkeypatch):
        """Unknown protocol + unknown platform falls back to avrdude."""
        self._patch_all_missing(monkeypatch)
        from kerf_firmware.upload.router import route_upload

        result = route_upload(
            "/tmp/fw.hex",
            "/dev/ttyACM0",
            _board(mcu="UnknownMCU", platform="unknown_platform", upload_protocol="unknown"),
        )

        assert result.status == "pending"
        assert "avrdude" in result.reason.lower()

    def test_router_delegates_success(self, monkeypatch):
        """When the tool is present and succeeds, router returns ok=True."""
        captured: list[list[str]] = []

        monkeypatch.setattr(
            "shutil.which",
            lambda name: "/usr/bin/avrdude" if name == "avrdude" else None,
        )
        monkeypatch.setattr(
            "subprocess.run",
            lambda cmd, **kw: captured.append(cmd) or _make_proc(0, "flash written", ""),
        )

        from kerf_firmware.upload.router import route_upload

        result = route_upload(
            "/tmp/firmware.hex",
            "/dev/ttyACM0",
            _board(mcu="ATmega328P", platform="atmelavr", upload_protocol="arduino"),
        )

        assert result.ok
        assert result.status == "ok"
        assert len(captured) == 1


# ---------------------------------------------------------------------------
# T6 — UploadResult type contract
# ---------------------------------------------------------------------------


class TestUploadResultType:
    def test_named_tuple_fields(self):
        """UploadResult has all required fields."""
        from kerf_firmware.upload.types import UploadResult

        r = UploadResult(ok=True, stdout="out", stderr="err", status="ok", reason="")
        assert r.ok is True
        assert r.stdout == "out"
        assert r.stderr == "err"
        assert r.status == "ok"
        assert r.reason == ""

    def test_pending_result_contract(self):
        """pending result has ok=False."""
        from kerf_firmware.upload.types import UploadResult

        r = UploadResult(ok=False, stdout="", stderr="", status="pending", reason="tool missing")
        assert not r.ok
        assert r.status == "pending"
        assert r.reason == "tool missing"

    def test_public_import_from_package(self):
        """All public names are importable from kerf_firmware.upload."""
        import kerf_firmware.upload as pkg

        assert hasattr(pkg, "UploadResult")
        assert hasattr(pkg, "upload_avrdude")
        assert hasattr(pkg, "upload_esptool")
        assert hasattr(pkg, "upload_stm32flash")
        assert hasattr(pkg, "upload_bossac")
        assert hasattr(pkg, "route_upload")
