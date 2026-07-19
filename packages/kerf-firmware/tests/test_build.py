"""
tests/test_build.py — hermetic tests for kerf-firmware build + boards + monitor.

Strategy:
  - When PlatformIO is not on PATH (CI default): assert graceful degradation
    (PlatformIONotInstalledError / PIO_NOT_INSTALLED sentinel).
  - Happy path: a fake `pio` Python script writes a minimal ELF+HEX artefact
    to the expected .pio/build/<env>/ path, then build_firmware() is called.
  - Boards: list_boards(), get_board(), boards_as_json_manifest() are tested
    without any subprocess.
  - Monitor: absent-PIO degrade path is tested without a real serial device.
"""
from __future__ import annotations

import os
import stat
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixture: minimal Arduino Blink sketch (main.ino)
# ---------------------------------------------------------------------------

BLINK_INO = textwrap.dedent("""\
    // Blink — the canonical embedded hello-world
    void setup() {
        pinMode(LED_BUILTIN, OUTPUT);
    }

    void loop() {
        digitalWrite(LED_BUILTIN, HIGH);
        delay(1000);
        digitalWrite(LED_BUILTIN, LOW);
        delay(1000);
    }
""")

FAKE_BUILD_LOG = textwrap.dedent("""\
    Processing uno (platform: atmelavr; board: uno; framework: arduino)
    ----------------------------------------------------------------------
    Verbose mode can be enabled via `-v, --verbose` option
    CONFIGURATION: https://docs.platformio.org/page/boards/atmelavr/uno.html
    PLATFORM: Atmel AVR (4.2.0) > Arduino Uno
    Compiling .pio/build/uno/src/main.ino.cpp.o
    Linking .pio/build/uno/firmware.elf
    Checking size .pio/build/uno/firmware.elf
    Building .pio/build/uno/firmware.hex
    ================== [SUCCESS] Took 6.23 seconds ==================
""")


def _make_blink_sketch(tmp_path: Path) -> Path:
    """Create a minimal blink sketch directory in tmp_path."""
    sketch_dir = tmp_path / "blink"
    sketch_dir.mkdir()
    (sketch_dir / "main.ino").write_text(BLINK_INO, encoding="utf-8")
    return sketch_dir


# ---------------------------------------------------------------------------
# Fake `pio` subprocess helper
# ---------------------------------------------------------------------------

def _make_fake_pio(tmp_path: Path, exit_code: int = 0, produce_artefacts: bool = True) -> Path:
    """
    Write a small Python-based fake `pio` script.

    When called as `pio run --project-dir <dir> --environment <env> ...`
    it creates the expected artefact structure and exits with `exit_code`.
    """
    fake_bin = tmp_path / "pio"

    # Build the artefact-creation block as a separate indented string to avoid
    # f-string + textwrap.dedent indentation conflicts.
    if produce_artefacts:
        artefact_block = (
            "args = sys.argv[1:]\n"
            "project_dir = None\n"
            "environment = 'uno'\n"
            "for i, arg in enumerate(args):\n"
            "    if arg == '--project-dir' and i + 1 < len(args):\n"
            "        project_dir = args[i + 1]\n"
            "    if arg == '--environment' and i + 1 < len(args):\n"
            "        environment = args[i + 1]\n"
            "if project_dir:\n"
            "    import os as _os\n"
            "    build_dir = _os.path.join(project_dir, '.pio', 'build', environment)\n"
            "    _os.makedirs(build_dir, exist_ok=True)\n"
            "    open(_os.path.join(build_dir, 'firmware.elf'), 'w').write('ELF_STUB')\n"
            "    open(_os.path.join(build_dir, 'firmware.hex'), 'w').write(':00000001FF')\n"
        )
    else:
        artefact_block = ""

    build_log_repr = repr(FAKE_BUILD_LOG)
    script_lines = [
        "#!/usr/bin/env python3",
        "import sys",
        artefact_block,
        f"sys.stdout.write({build_log_repr})",
        f"sys.exit({exit_code})",
        "",
    ]
    script = "\n".join(script_lines)
    fake_bin.write_text(script, encoding="utf-8")
    fake_bin.chmod(fake_bin.stat().st_mode | stat.S_IEXEC)
    return fake_bin


# ---------------------------------------------------------------------------
# T1 — graceful degradation when PlatformIO is absent
# ---------------------------------------------------------------------------

class TestNoPlatformIO:
    def test_missing_binary_raises_not_installed(self, monkeypatch):
        """PlatformIONotInstalledError when neither pio nor platformio is on PATH."""
        monkeypatch.setattr("shutil.which", lambda name: None)
        sys.modules.pop("kerf_firmware.build", None)

        from kerf_firmware.build import PlatformIONotInstalledError, build_firmware

        with tempfile.TemporaryDirectory() as td:
            sketch_dir = Path(td) / "blink"
            sketch_dir.mkdir()
            (sketch_dir / "main.ino").write_text(BLINK_INO)

            with pytest.raises(PlatformIONotInstalledError) as exc_info:
                build_firmware(str(sketch_dir))

            assert "PlatformIO" in str(exc_info.value)
            assert "PATH" in str(exc_info.value)

    def test_missing_binary_includes_install_hint(self, monkeypatch):
        """The not-installed error message includes a pip install hint."""
        monkeypatch.setattr("shutil.which", lambda name: None)
        sys.modules.pop("kerf_firmware.build", None)

        from kerf_firmware.build import PlatformIONotInstalledError, build_firmware

        with tempfile.TemporaryDirectory() as td:
            sketch_dir = Path(td) / "blink"
            sketch_dir.mkdir()
            (sketch_dir / "main.ino").write_text(BLINK_INO)

            with pytest.raises(PlatformIONotInstalledError) as exc_info:
                build_firmware(str(sketch_dir))

            assert "pip install platformio" in str(exc_info.value).lower() or \
                   "pip install" in str(exc_info.value)

    def test_missing_sketch_dir_raises_file_not_found(self, monkeypatch, tmp_path):
        """FileNotFoundError before the binary check when the sketch dir is absent."""
        sys.modules.pop("kerf_firmware.build", None)
        from kerf_firmware.build import build_firmware

        with pytest.raises(FileNotFoundError):
            build_firmware(str(tmp_path / "nonexistent_sketch"))

    def test_monitor_degrade_when_pio_absent(self, monkeypatch):
        """open_serial_monitor() returns PIO_NOT_INSTALLED sentinel, not an exception."""
        monkeypatch.setattr("shutil.which", lambda name: None)
        sys.modules.pop("kerf_firmware.monitor", None)

        from kerf_firmware.monitor import open_serial_monitor

        result = open_serial_monitor(port="/dev/ttyUSB0", baud=115200, duration_s=1.0)

        assert result.error == "PIO_NOT_INSTALLED"
        assert len(result.warnings) > 0
        assert "platformio" in result.warnings[0].lower()
        assert result.lines == []


# ---------------------------------------------------------------------------
# T2 — happy path with fake `pio` subprocess
# ---------------------------------------------------------------------------

class TestFakePlatformIO:
    """
    Write a fake `pio` script that creates the expected .pio/build/<env>/
    artefact structure, verify build_firmware() processes the result correctly.
    """

    @pytest.fixture(autouse=True)
    def fake_pio(self, tmp_path, monkeypatch):
        """Create a fake `pio` binary and patch shutil.which to return it."""
        self._fake_bin = _make_fake_pio(tmp_path, exit_code=0, produce_artefacts=True)

        monkeypatch.setattr(
            "shutil.which",
            lambda name: str(self._fake_bin) if name in ("pio", "platformio") else None,
        )
        sys.modules.pop("kerf_firmware.build", None)

    def test_happy_path_blink_sketch(self, tmp_path):
        """Fixture Blink sketch compiles to an ELF + HEX artefact."""
        from kerf_firmware.build import build_firmware

        sketch_dir = _make_blink_sketch(tmp_path)
        result = build_firmware(str(sketch_dir), board="uno", framework="arduino")

        assert result.elf_path is not None, "Expected an ELF artefact path"
        assert result.hex_path is not None, "Expected a HEX artefact path"
        assert result.artefact_bytes > 0, "Expected non-zero artefact size"
        assert result.build_log_lines > 0

    def test_build_log_captured(self, tmp_path):
        """Build log is captured and non-empty."""
        from kerf_firmware.build import build_firmware

        sketch_dir = _make_blink_sketch(tmp_path)
        result = build_firmware(str(sketch_dir))

        assert isinstance(result.build_log, str)
        assert len(result.build_log) > 0

    def test_environment_reflects_board(self, tmp_path):
        """Environment in result matches the board ID used."""
        from kerf_firmware.build import build_firmware

        sketch_dir = _make_blink_sketch(tmp_path)
        result = build_firmware(str(sketch_dir), board="uno")

        assert result.environment == "uno"

    def test_warnings_list_present(self, tmp_path):
        """warnings is always a list (even when empty)."""
        from kerf_firmware.build import build_firmware

        sketch_dir = _make_blink_sketch(tmp_path)
        result = build_firmware(str(sketch_dir))

        assert isinstance(result.warnings, list)

    def test_existing_platformio_ini_respected(self, tmp_path):
        """When platformio.ini exists in sketch_dir it is not overwritten."""
        from kerf_firmware.build import build_firmware

        sketch_dir = _make_blink_sketch(tmp_path)
        # Write a custom platformio.ini with a non-default env name.
        ini_content = textwrap.dedent("""\
            [env:custom_env]
            platform  = atmelavr
            board     = uno
            framework = arduino
        """)
        (sketch_dir / "platformio.ini").write_text(ini_content, encoding="utf-8")

        # Build with environment=custom_env; if ini were regenerated the env
        # would be reset to 'uno' and the test env wouldn't exist.
        result = build_firmware(str(sketch_dir), board="uno", environment="custom_env")
        assert result.environment == "custom_env"


# ---------------------------------------------------------------------------
# T3 — non-zero exit raises FirmwareBuildError
# ---------------------------------------------------------------------------

class TestFirmwareBuildError:
    @pytest.fixture(autouse=True)
    def fake_pio_failing(self, tmp_path, monkeypatch):
        """Create a fake `pio` that exits non-zero."""
        self._fake_bin = _make_fake_pio(tmp_path, exit_code=1, produce_artefacts=False)

        monkeypatch.setattr(
            "shutil.which",
            lambda name: str(self._fake_bin) if name in ("pio", "platformio") else None,
        )
        sys.modules.pop("kerf_firmware.build", None)

    def test_nonzero_exit_raises_firmware_build_error(self, tmp_path):
        from kerf_firmware.build import FirmwareBuildError, build_firmware

        sketch_dir = _make_blink_sketch(tmp_path)
        with pytest.raises(FirmwareBuildError) as exc_info:
            build_firmware(str(sketch_dir))
        assert "exited 1" in str(exc_info.value)


# ---------------------------------------------------------------------------
# T4 — boards module
# ---------------------------------------------------------------------------

class TestBoards:
    def setup_method(self):
        sys.modules.pop("kerf_firmware.boards", None)

    def test_list_boards_returns_non_empty(self):
        from kerf_firmware.boards import list_boards
        boards = list_boards()
        assert len(boards) > 0

    def test_list_boards_have_required_fields(self):
        from kerf_firmware.boards import list_boards
        for board in list_boards():
            assert "id" in board
            assert "name" in board
            assert "platform" in board
            assert "board" in board
            assert "framework" in board
            assert "mcu" in board

    def test_get_board_known(self):
        from kerf_firmware.boards import get_board
        board = get_board("uno")
        assert board is not None
        assert board["id"] == "uno"
        assert board["mcu"] == "ATmega328P"

    def test_get_board_esp32(self):
        from kerf_firmware.boards import get_board
        board = get_board("esp32dev")
        assert board is not None
        assert board["platform"] == "espressif32"

    def test_get_board_unknown_returns_none(self):
        from kerf_firmware.boards import get_board
        assert get_board("totally_unknown_board_xyz") is None

    def test_boards_as_json_manifest_structure(self):
        from kerf_firmware.boards import boards_as_json_manifest
        manifest = boards_as_json_manifest()
        assert "boards" in manifest
        assert isinstance(manifest["boards"], list)
        assert len(manifest["boards"]) > 0

    def test_pico_rp2040_present(self):
        from kerf_firmware.boards import get_board
        pico = get_board("pico")
        assert pico is not None
        assert "RP2040" in pico["mcu"]

    def test_platform_inference(self):
        from kerf_firmware.build import _infer_platform
        sys.modules.pop("kerf_firmware.build", None)
        from kerf_firmware.build import _infer_platform

        assert _infer_platform("uno") == "atmelavr"
        assert _infer_platform("esp32dev") == "espressif32"
        assert _infer_platform("nodemcuv2") == "espressif8266"
        assert _infer_platform("pico") == "raspberrypi"
        # Unknown boards fall back to atmelavr
        assert _infer_platform("unknown_mcu") == "atmelavr"


# ---------------------------------------------------------------------------
# T5 — minimal platformio.ini generation
# ---------------------------------------------------------------------------

class TestIniGeneration:
    def setup_method(self):
        sys.modules.pop("kerf_firmware.build", None)

    def test_write_minimal_ini_creates_file(self, tmp_path):
        from kerf_firmware.build import _write_minimal_ini

        _write_minimal_ini(tmp_path, board="uno", framework="arduino")

        ini_path = tmp_path / "platformio.ini"
        assert ini_path.exists()
        content = ini_path.read_text()
        assert "platform" in content
        assert "atmelavr" in content
        assert "uno" in content
        assert "arduino" in content

    def test_write_minimal_ini_esp32(self, tmp_path):
        from kerf_firmware.build import _write_minimal_ini

        _write_minimal_ini(tmp_path, board="esp32dev", framework="arduino")

        content = (tmp_path / "platformio.ini").read_text()
        assert "espressif32" in content
        assert "esp32dev" in content

    def test_write_minimal_ini_section_header(self, tmp_path):
        from kerf_firmware.build import _write_minimal_ini

        _write_minimal_ini(tmp_path, board="nano", framework="arduino")
        content = (tmp_path / "platformio.ini").read_text()
        assert "[env:nano]" in content


# ---------------------------------------------------------------------------
# T6 — route layer (FastAPI routes using fake build_firmware)
# ---------------------------------------------------------------------------

class TestRoutes:
    """Smoke-test the FastAPI route layer with a mocked build_firmware()."""

    def setup_method(self):
        sys.modules.pop("kerf_firmware.routes", None)
        sys.modules.pop("kerf_firmware.build", None)
        sys.modules.pop("kerf_firmware.monitor", None)

    def test_build_route_bad_args_returns_error(self):
        """POST /firmware/build with missing sketch_dir → BAD_ARGS."""
        import asyncio
        from kerf_firmware.routes import firmware_build_route

        result = asyncio.run(
            firmware_build_route({})
        )
        assert result["error"] == "BAD_ARGS"
        assert not result["ok"]

    def test_boards_route_returns_manifest(self):
        """GET /firmware/boards returns a non-empty boards manifest."""
        import asyncio
        from kerf_firmware.routes import firmware_boards_route

        result = asyncio.run(
            firmware_boards_route()
        )
        assert "boards" in result
        assert len(result["boards"]) > 0

    def test_monitor_route_bad_args_returns_error(self):
        """POST /firmware/monitor with missing port → BAD_ARGS."""
        import asyncio
        from kerf_firmware.routes import firmware_monitor_route

        result = asyncio.run(
            firmware_monitor_route({})
        )
        assert result["error"] == "BAD_ARGS"
        assert not result["ok"]

    def test_build_route_pio_not_installed(self, monkeypatch):
        """Route returns PIO_NOT_INSTALLED when binary is absent."""
        import asyncio
        import tempfile

        monkeypatch.setattr("shutil.which", lambda name: None)
        sys.modules.pop("kerf_firmware.build", None)

        from kerf_firmware.routes import firmware_build_route
        import kerf_firmware.routes as _routes

        # Patch storage root so the sketch_dir inside tempdir passes confinement
        monkeypatch.setattr(_routes, "_get_storage_root", lambda: Path(tempfile.gettempdir()).resolve())

        with tempfile.TemporaryDirectory() as td:
            sketch_dir = Path(td) / "blink"
            sketch_dir.mkdir()
            (sketch_dir / "main.ino").write_text(BLINK_INO)

            result = asyncio.run(
                firmware_build_route({"sketch_dir": str(sketch_dir), "board": "uno"})
            )

        assert result["error"] == "PIO_NOT_INSTALLED"
        assert not result["ok"]
