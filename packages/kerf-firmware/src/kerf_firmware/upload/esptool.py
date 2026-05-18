"""
esptool upload wrapper.

Shells out to the `esptool.py` (or `esptool`) CLI to flash a binary to an
ESP32 / ESP8266 board.

esptool CLI shape (esptool >=4.x):

    esptool.py \\
        --chip <chip>        # auto | esp32 | esp32s2 | esp32s3 | esp8266 | ...
        --port <port>        # serial port, e.g. /dev/ttyUSB0  COM3
        --baud <baud>        # upload speed (default: 460800)
        write_flash \\
        --flash_mode dio \\
        0x0 <file>           # offset 0x0 for most ESP32 images; 0x0 for ESP8266

If `esptool.py` (or `esptool`) is not on PATH, returns
UploadResult(status="pending").
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any

from kerf_firmware.upload.types import UploadResult

_CANDIDATES = ("esptool.py", "esptool")
_DEFAULT_BAUD = "460800"
_DEFAULT_FLASH_MODE = "dio"
_DEFAULT_FLASH_OFFSET = "0x0"

# MCU string → esptool chip identifier.
_MCU_CHIP: dict[str, str] = {
    "ESP32":     "esp32",
    "ESP32-S2":  "esp32s2",
    "ESP32-S3":  "esp32s3",
    "ESP32-C3":  "esp32c3",
    "ESP32-H2":  "esp32h2",
    "ESP8266":   "esp8266",
}


def _esptool_binary() -> str | None:
    """Return the first esptool binary found on PATH, or None."""
    for name in _CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def upload(
    hex_or_bin_path: str,
    port: str,
    board_meta: dict[str, Any],
) -> UploadResult:
    """Flash a BIN file to an ESP32/ESP8266 board via esptool.

    Parameters
    ----------
    hex_or_bin_path:
        Absolute path to the compiled firmware binary (.bin preferred).
    port:
        Serial port the board is connected to (e.g. '/dev/ttyUSB0', 'COM3').
    board_meta:
        BoardEntry dict with at least:
          - ``mcu``           — MCU string, e.g. 'ESP32', 'ESP8266'
          - ``upload_speed``  — baud rate (optional, defaults to 460800)

    Returns
    -------
    UploadResult
        status="pending" when esptool is absent;
        status="ok"/"error" otherwise.
    """
    binary = _esptool_binary()
    if binary is None:
        return UploadResult(
            ok=False,
            stdout="",
            stderr="",
            status="pending",
            reason=(
                "esptool not found on PATH. "
                "Install it via: pip install esptool  "
                "| https://github.com/espressif/esptool"
            ),
        )

    mcu_raw = board_meta.get("mcu", "ESP32")
    chip = _MCU_CHIP.get(mcu_raw, "auto")

    baud = str(board_meta.get("upload_speed", _DEFAULT_BAUD))
    flash_mode = board_meta.get("flash_mode", _DEFAULT_FLASH_MODE)
    flash_offset = board_meta.get("flash_offset", _DEFAULT_FLASH_OFFSET)

    cmd = [
        binary,
        "--chip", chip,
        "--port", port,
        "--baud", baud,
        "write_flash",
        "--flash_mode", flash_mode,
        flash_offset,
        hex_or_bin_path,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return UploadResult(
            ok=False,
            stdout="",
            stderr="",
            status="error",
            reason="esptool timed out after 120 s",
        )

    ok = proc.returncode == 0
    return UploadResult(
        ok=ok,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        status="ok" if ok else "error",
        reason="" if ok else f"esptool exited {proc.returncode}",
    )
