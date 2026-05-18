"""
Upload router — pick the right wrapper from board_meta.

Routing logic (in priority order):

1. ``board_meta["upload_protocol"]`` is checked first for explicit overrides
   (e.g. "esptool", "stlink", "picotool").
2. ``board_meta["platform"]`` is used as an arch hint when upload_protocol is
   ambiguous or absent.

Mapping:

  platform / upload_protocol → wrapper
  ─────────────────────────────────────
  atmelavr   / arduino|wiring|*     → avrdude    (AVR arch)
  espressif* / esptool              → esptool    (Xtensa / RISC-V arch)
  ststm32    / stlink|serial|*      → stm32flash (ARM Cortex-M arch)
  raspberrypi / picotool|uf2|*      → bossac     (RP2040)
  teensy     / teensy-cli|*         → NotImplemented (handled by Teensy Loader)
  *          / *                    → avrdude    (safe default)
"""
from __future__ import annotations

from typing import Any

from kerf_firmware.upload.avrdude import upload as _avrdude
from kerf_firmware.upload.bossac import upload as _bossac
from kerf_firmware.upload.esptool import upload as _esptool
from kerf_firmware.upload.stm32flash import upload as _stm32flash
from kerf_firmware.upload.types import UploadResult

# upload_protocol values that map to a specific tool regardless of platform.
_PROTOCOL_MAP: dict[str, Any] = {
    "esptool":    _esptool,
    "stlink":     _stm32flash,
    "serial":     _stm32flash,   # STM32 serial bootloader
    "picotool":   _bossac,
    "uf2":        _bossac,
    "arduino":    _avrdude,
    "wiring":     _avrdude,
    "usbasp":     _avrdude,
    "usbtiny":    _avrdude,
    "stk500v2":   _avrdude,
}

# PlatformIO platform prefix → wrapper.
_PLATFORM_MAP: dict[str, Any] = {
    "atmelavr":       _avrdude,
    "espressif32":    _esptool,
    "espressif8266":  _esptool,
    "ststm32":        _stm32flash,
    "raspberrypi":    _bossac,
}


def route_upload(
    hex_or_bin_path: str,
    port: str,
    board_meta: dict[str, Any],
) -> UploadResult:
    """Pick the right upload wrapper and invoke it.

    Parameters
    ----------
    hex_or_bin_path:
        Absolute path to the compiled firmware file.
    port:
        Serial port or device path (e.g. '/dev/ttyACM0', 'COM3').
    board_meta:
        BoardEntry dict (or compatible mapping).  The following keys are used
        for routing:
          - ``upload_protocol`` — e.g. 'esptool', 'arduino', 'stlink'
          - ``platform``        — e.g. 'atmelavr', 'espressif32', 'ststm32'

    Returns
    -------
    UploadResult
        Delegated to the chosen wrapper.  Returns status="pending" with a
        descriptive reason if the wrapper's tool binary is absent.
    """
    protocol = board_meta.get("upload_protocol", "")
    platform = board_meta.get("platform", "")

    # 1. Explicit protocol override takes precedence.
    wrapper = _PROTOCOL_MAP.get(protocol)

    # 2. Fall back to platform-based routing.
    if wrapper is None:
        for prefix, fn in _PLATFORM_MAP.items():
            if platform.startswith(prefix):
                wrapper = fn
                break

    # 3. Default to avrdude (broad AVR coverage, most common case).
    if wrapper is None:
        wrapper = _avrdude

    return wrapper(hex_or_bin_path, port, board_meta)
