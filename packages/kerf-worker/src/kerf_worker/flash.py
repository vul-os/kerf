"""Firmware flash-tool capability detection.

``firmware_flash_capabilities()`` probes ``PATH`` for each of the four
supported flash tools and returns a dict advertising what is available.
This dict is merged into the worker's ``capabilities`` payload at enroll
time so the server only dispatches ``firmware_flash`` jobs to workers that
have the required toolchain.

Supported tools
---------------
esptool   — ESP32 / ESP8266 (Espressif)
avrdude   — Arduino AVR / ATmega
openocd   — STM32 / ARM Cortex-M
picotool  — RP2040 (Raspberry Pi)

Board-target → tool mapping
----------------------------
  board_target prefix     tool
  ─────────────────────── ────────
  esp32*                  esptool
  esp8266*                esptool
  avr*                    avrdude
  stm32*                  openocd
  arm*                    openocd
  rp2040*                 picotool
  * (default)             avrdude

None of the flash tools are *required* — they are external system binaries.
A missing tool merely means the worker will not be assigned jobs targeting
that board family.
"""
from __future__ import annotations

import shutil
from typing import Any, Dict, List, Optional

# ── Tool names ─────────────────────────────────────────────────────────────

# esptool may be installed as either "esptool" or "esptool.py"
_ESPTOOL_CANDIDATES = ("esptool", "esptool.py")
_AVRDUDE_BINARY     = "avrdude"
_OPENOCD_BINARY     = "openocd"
_PICOTOOL_BINARY    = "picotool"


# ── Board-target → tool ────────────────────────────────────────────────────

_BOARD_TO_TOOL: Dict[str, str] = {
    "esp32":    "esptool",
    "esp8266":  "esptool",
    "avr":      "avrdude",
    "avr_uno":  "avrdude",
    "avr_mega": "avrdude",
    "stm32":    "openocd",
    "stm32f1":  "openocd",
    "stm32f4":  "openocd",
    "arm":      "openocd",
    "rp2040":   "picotool",
}


def _which_esptool() -> Optional[str]:
    """Return the esptool binary path or None."""
    for name in _ESPTOOL_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def firmware_flash_capabilities() -> Dict[str, Any]:
    """Detect installed flash tools and return a capabilities sub-dict.

    Returns
    -------
    dict with the following keys:

    ``flash_tools`` : list[str]
        Names of tools found on PATH (e.g. ``["esptool", "avrdude"]``).

    ``flash_board_families`` : list[str]
        Inferred board families coverable by the installed tools
        (e.g. ``["esp32", "esp8266", "avr"]``).

    ``firmware_flash_enabled`` : bool
        True when at least one flash tool is available.
    """
    tools_found: List[str] = []
    board_families: List[str] = []

    if _which_esptool() is not None:
        tools_found.append("esptool")
        board_families.extend(["esp32", "esp8266"])

    if shutil.which(_AVRDUDE_BINARY) is not None:
        tools_found.append("avrdude")
        board_families.extend(["avr", "avr_uno", "avr_mega"])

    if shutil.which(_OPENOCD_BINARY) is not None:
        tools_found.append("openocd")
        board_families.extend(["stm32", "stm32f1", "stm32f4", "arm"])

    if shutil.which(_PICOTOOL_BINARY) is not None:
        tools_found.append("picotool")
        board_families.append("rp2040")

    return {
        "flash_tools": tools_found,
        "flash_board_families": board_families,
        "firmware_flash_enabled": len(tools_found) > 0,
    }


def tool_for_board(board_target: str) -> Optional[str]:
    """Return the flash tool name for a given board_target, or None.

    Returns None when no installed tool covers the requested board family.
    The caller should treat None as an unserviceable job.

    Parameters
    ----------
    board_target:
        Board identifier from the job payload, e.g. ``"esp32"``,
        ``"stm32f4"``, ``"avr_mega"``, ``"rp2040"``.
    """
    bt = board_target.lower().strip()

    # Exact match first.
    tool_name = _BOARD_TO_TOOL.get(bt)

    # Prefix match if no exact match.
    if tool_name is None:
        for prefix, t in _BOARD_TO_TOOL.items():
            if bt.startswith(prefix):
                tool_name = t
                break

    if tool_name is None:
        tool_name = "avrdude"  # safe default for unknown AVR boards

    # Check the tool is actually installed.
    if tool_name == "esptool":
        return "esptool" if _which_esptool() is not None else None
    if tool_name == "avrdude":
        return "avrdude" if shutil.which(_AVRDUDE_BINARY) is not None else None
    if tool_name == "openocd":
        return "openocd" if shutil.which(_OPENOCD_BINARY) is not None else None
    if tool_name == "picotool":
        return "picotool" if shutil.which(_PICOTOOL_BINARY) is not None else None

    return None


__all__ = ["firmware_flash_capabilities", "tool_for_board"]
