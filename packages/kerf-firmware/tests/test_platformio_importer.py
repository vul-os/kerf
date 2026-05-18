"""Tests for kerf_firmware.platformio_importer."""
from __future__ import annotations

import os
import tempfile

import pytest

from kerf_firmware.platformio_importer import import_platformio_ini

# Path to the fixture bundled with the test suite
FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
FIXTURE_PIO = os.path.join(FIXTURE_DIR, "platformio.ini")


# ── fixture round-trip ────────────────────────────────────────────────────────

def test_fixture_file_exists():
    assert os.path.isfile(FIXTURE_PIO), f"Fixture not found: {FIXTURE_PIO}"


def test_fixture_import_returns_dict():
    result = import_platformio_ini(FIXTURE_PIO)
    assert isinstance(result, dict)


def test_fixture_board_mapped_to_uno_r3():
    result = import_platformio_ini(FIXTURE_PIO)
    assert result["board"] == "arduino-uno-r3"


def test_fixture_two_libraries():
    result = import_platformio_ini(FIXTURE_PIO)
    assert len(result["libraries"]) == 2


def test_fixture_arduinojson_lib():
    result = import_platformio_ini(FIXTURE_PIO)
    lib_names = [lib["name"] for lib in result["libraries"]]
    assert any("ArduinoJson" in n for n in lib_names), f"ArduinoJson not in {lib_names}"


def test_fixture_arduinojson_version():
    result = import_platformio_ini(FIXTURE_PIO)
    for lib in result["libraries"]:
        if "ArduinoJson" in lib["name"]:
            assert lib["version"] == "6.21.3"
            break


def test_fixture_dht_lib():
    result = import_platformio_ini(FIXTURE_PIO)
    lib_names = [lib["name"] for lib in result["libraries"]]
    assert any("DHT" in n for n in lib_names), f"DHT lib not in {lib_names}"


def test_fixture_dht_version():
    result = import_platformio_ini(FIXTURE_PIO)
    for lib in result["libraries"]:
        if "DHT" in lib["name"]:
            assert lib["version"] == "1.4.4"
            break


def test_fixture_build_flags():
    result = import_platformio_ini(FIXTURE_PIO)
    flags = result["build_flags"]
    assert "-DDEBUG=1" in flags
    assert "-DLED_PIN=13" in flags


def test_fixture_monitor_speed():
    result = import_platformio_ini(FIXTURE_PIO)
    assert result["monitor_speed"] == 115200


def test_fixture_project_name():
    result = import_platformio_ini(FIXTURE_PIO)
    assert result["name"] == "uno_blink"


def test_fixture_sources_list():
    result = import_platformio_ini(FIXTURE_PIO)
    assert isinstance(result["sources"], list)
    assert len(result["sources"]) >= 1


# ── error handling ────────────────────────────────────────────────────────────

def test_missing_file_raises_file_not_found():
    with pytest.raises(FileNotFoundError):
        import_platformio_ini("/nonexistent/path/platformio.ini")


def test_no_env_section_raises_value_error():
    content = """\
[platformio]
default_envs = test
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ini", delete=False
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        with pytest.raises(ValueError, match="env"):
            import_platformio_ini(tmp_path)
    finally:
        os.unlink(tmp_path)


# ── inline INI variants ───────────────────────────────────────────────────────

def _write_ini(content: str) -> str:
    """Write content to a temp .ini file and return path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ini", delete=False
    ) as tmp:
        tmp.write(content)
        return tmp.name


def test_esp32_board_mapping():
    path = _write_ini("""\
[env:esp32]
platform = espressif32
board = esp32dev
framework = arduino
monitor_speed = 115200
""")
    try:
        result = import_platformio_ini(path)
        assert result["board"] == "esp32-wroom-32"
    finally:
        os.unlink(path)


def test_pico_board_mapping():
    path = _write_ini("""\
[env:mypico]
platform = raspberrypi
board = pico
framework = arduino
""")
    try:
        result = import_platformio_ini(path)
        assert result["board"] == "raspberry-pi-pico"
    finally:
        os.unlink(path)


def test_lib_at_version_syntax():
    path = _write_ini("""\
[env:myenv]
platform = atmelavr
board = uno
framework = arduino
lib_deps = MyLib @ 2.0.0
""")
    try:
        result = import_platformio_ini(path)
        assert result["libraries"][0]["name"] == "MyLib"
        assert result["libraries"][0]["version"] == "2.0.0"
    finally:
        os.unlink(path)


def test_lib_no_version():
    path = _write_ini("""\
[env:myenv]
platform = atmelavr
board = uno
framework = arduino
lib_deps = SomeLibWithNoVersion
""")
    try:
        result = import_platformio_ini(path)
        assert result["libraries"][0]["name"] == "SomeLibWithNoVersion"
        assert result["libraries"][0]["version"] == ""
    finally:
        os.unlink(path)


def test_no_monitor_speed_defaults_to_zero():
    path = _write_ini("""\
[env:myenv]
platform = atmelavr
board = uno
framework = arduino
""")
    try:
        result = import_platformio_ini(path)
        assert result["monitor_speed"] == 0
    finally:
        os.unlink(path)


def test_unknown_board_passes_through():
    path = _write_ini("""\
[env:myenv]
platform = atmelavr
board = custom_unknown_board_xyz
framework = arduino
""")
    try:
        result = import_platformio_ini(path)
        assert result["board"] == "custom_unknown_board_xyz"
    finally:
        os.unlink(path)
