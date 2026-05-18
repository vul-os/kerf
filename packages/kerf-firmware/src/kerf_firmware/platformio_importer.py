"""One-way PlatformIO → kerf.fw.json importer.

Usage:
    from kerf_firmware.platformio_importer import import_platformio_ini

    manifest = import_platformio_ini("path/to/platformio.ini")

The importer reads the first [env:...] section (or [env] fallback) and maps
PlatformIO keys to the kerf.fw.json schema.  It is deliberately one-way:
kerf.fw.json → platformio.ini conversion is out of scope.

Supported mappings
------------------
PlatformIO key          → kerf.fw.json field
board                   → board          (slug as-is; may need manual fix-up)
lib_deps               → libraries[]    (name + version parsed from "name@version"
                                          or "name @ version")
build_flags             → build_flags
monitor_speed           → monitor_speed
framework               → ignored (not in kerf.fw.json schema; available as extra)
"""
from __future__ import annotations

import configparser
import os
import re
from typing import Any


def _parse_lib_dep(raw: str) -> dict[str, str]:
    """Parse a single lib_deps entry into {name, version}.

    Handles the common forms:
      ArduinoJson@6.21.3
      ArduinoJson @ 6.21.3
      ArduinoJson
      https://github.com/...  (treated as name with no version)
    """
    raw = raw.strip()
    # "name @ version" or "name@version"
    m = re.match(r'^([^@\s][^@]*)@\s*(.+)$', raw)
    if m:
        return {"name": m.group(1).strip(), "version": m.group(2).strip()}
    return {"name": raw, "version": ""}


def _parse_lib_deps(raw: str) -> list[dict[str, str]]:
    """Split a multi-line lib_deps value and parse each entry."""
    libs: list[dict[str, str]] = []
    for line in raw.splitlines():
        line = line.strip()
        if line and not line.startswith(";") and not line.startswith("#"):
            libs.append(_parse_lib_dep(line))
    return libs


def _parse_build_flags(raw: str) -> list[str]:
    """Split build_flags (may span multiple lines, space-separated)."""
    flags: list[str] = []
    for line in raw.splitlines():
        for token in line.split():
            token = token.strip()
            if token and not token.startswith(";"):
                flags.append(token)
    return flags


def import_platformio_ini(path: str) -> dict[str, Any]:
    """Parse *path* (a ``platformio.ini``) and return a kerf.fw.json dict.

    Raises FileNotFoundError if the file does not exist.
    Raises ValueError if the file cannot be parsed or has no [env:*] section.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"platformio.ini not found: {path}")

    parser = configparser.ConfigParser(
        allow_no_value=True,
        inline_comment_prefixes=(";", "#"),
    )
    # Preserve case in keys (PlatformIO keys are lower-case already)
    parser.optionxform = str  # type: ignore[method-assign]

    with open(path, encoding="utf-8") as fh:
        content = fh.read()

    parser.read_string(content)

    # --- find the environment section ------------------------------------------
    env_section: str | None = None
    for section in parser.sections():
        if section.startswith("env:"):
            env_section = section
            break
    if env_section is None and parser.has_section("env"):
        env_section = "env"
    if env_section is None:
        raise ValueError(
            f"No [env:*] or [env] section found in {path}"
        )

    env = dict(parser[env_section])

    # Merge with [platformio] defaults if present
    pio_defaults: dict[str, str] = {}
    if parser.has_section("platformio"):
        pio_defaults = dict(parser["platformio"])

    def get(key: str) -> str | None:
        return env.get(key) or pio_defaults.get(key)

    # --- project name from section name ----------------------------------------
    project_name = env_section.replace("env:", "").replace("env", "") or "firmware"

    # --- board -----------------------------------------------------------------
    board_raw = get("board") or ""
    # PlatformIO board IDs often look like "uno"; normalise common ones
    _BOARD_MAP: dict[str, str] = {
        "uno": "arduino-uno-r3",
        "nano": "arduino-nano",
        "mega2560": "arduino-mega-2560",
        "esp32dev": "esp32-wroom-32",
        "esp32-s3-devkitc-1": "esp32-s3",
        "espressif32": "esp32-wroom-32",
        "nodemcuv2": "esp8266-nodemcu",
        "d1_mini": "wemos-d1-mini",
        "bluepill_f103c8": "stm32-bluepill-f103c8",
        "pico": "raspberry-pi-pico",
    }
    board = _BOARD_MAP.get(board_raw.lower(), board_raw)

    # --- libraries -------------------------------------------------------------
    lib_deps_raw = get("lib_deps") or ""
    libraries = _parse_lib_deps(lib_deps_raw)

    # --- build flags -----------------------------------------------------------
    build_flags_raw = get("build_flags") or ""
    build_flags = _parse_build_flags(build_flags_raw)

    # --- monitor speed ---------------------------------------------------------
    monitor_speed_raw = get("monitor_speed") or get("monitor_baud") or "0"
    try:
        monitor_speed = int(str(monitor_speed_raw).strip())
    except ValueError:
        monitor_speed = 0

    # --- sources (PlatformIO uses src_dir; we default to src/main.cpp) ---------
    src_dir = get("src_dir") or "src"
    sources: list[str] = [f"{src_dir}/main.cpp"]

    manifest: dict[str, Any] = {
        "name": project_name,
        "board": board,
        "libraries": libraries,
        "sources": sources,
        "build_flags": build_flags,
        "monitor_speed": monitor_speed,
    }
    return manifest
