"""
avrdude upload wrapper.

Shells out to the `avrdude` CLI to flash a HEX file to an AVR-based board
(Arduino Uno, Nano, Mega 2560, etc.).

avrdude CLI shape (avrdude >=7.x):

    avrdude \\
        -p <partno>          # MCU part number, e.g. atmega328p
        -c <programmer>      # programmer/protocol, e.g. arduino, wiring, stk500v2
        -P <port>            # serial port, e.g. /dev/ttyACM0  COM3
        -b <baud>            # upload baud rate (optional, avrdude picks default)
        -U flash:w:<file>:i  # write <file> (Intel HEX) to flash memory

If `avrdude` is not on PATH, returns UploadResult(status="pending").
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any

from kerf_firmware.upload.types import UploadResult

# Default MCU → avrdude part string.
_MCU_PART: dict[str, str] = {
    "ATmega328P":  "atmega328p",
    "ATmega2560":  "atmega2560",
    "ATmega32U4":  "atmega32u4",
    "ATtiny85":    "attiny85",
    "ATtiny84":    "attiny84",
    "ATmega168":   "atmega168",
    "ATmega8":     "atmega8",
}

# upload_protocol → avrdude programmer id.
_PROTOCOL_PROGRAMMER: dict[str, str] = {
    "arduino":  "arduino",
    "wiring":   "wiring",
    "stk500v2": "stk500v2",
    "usbasp":   "usbasp",
    "usbtiny":  "usbtiny",
    "dragon_isp": "dragon_isp",
}

_DEFAULT_PROGRAMMER = "arduino"
_DEFAULT_BAUD = "115200"
_BINARY = "avrdude"


def upload(
    hex_or_bin_path: str,
    port: str,
    board_meta: dict[str, Any],
) -> UploadResult:
    """Flash a HEX file to an AVR board via avrdude.

    Parameters
    ----------
    hex_or_bin_path:
        Absolute path to the compiled firmware (Intel HEX preferred for AVR).
    port:
        Serial port the board is connected to (e.g. '/dev/ttyACM0', 'COM3').
    board_meta:
        BoardEntry dict (or compatible mapping) with at least:
          - ``mcu``             — MCU string, e.g. 'ATmega328P'
          - ``upload_protocol`` — e.g. 'arduino', 'wiring'

    Returns
    -------
    UploadResult
        status="pending" when avrdude is absent;
        status="ok"/"error" otherwise.
    """
    binary = shutil.which(_BINARY)
    if binary is None:
        return UploadResult(
            ok=False,
            stdout="",
            stderr="",
            status="pending",
            reason=(
                "avrdude not found on PATH. "
                "Install it via: sudo apt install avrdude  "
                "| brew install avrdude  "
                "| https://github.com/avrdudes/avrdude"
            ),
        )

    mcu_raw = board_meta.get("mcu", "ATmega328P")
    partno = _MCU_PART.get(mcu_raw, mcu_raw.lower())

    protocol = board_meta.get("upload_protocol", "arduino")
    programmer = _PROTOCOL_PROGRAMMER.get(protocol, _DEFAULT_PROGRAMMER)

    baud = str(board_meta.get("upload_speed", _DEFAULT_BAUD))

    # Detect file format: avrdude uses ':i' for Intel HEX, ':r' for raw binary.
    fmt = "i" if hex_or_bin_path.lower().endswith(".hex") else "r"

    cmd = [
        binary,
        "-p", partno,
        "-c", programmer,
        "-P", port,
        "-b", baud,
        f"-U", f"flash:w:{hex_or_bin_path}:{fmt}",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return UploadResult(
            ok=False,
            stdout="",
            stderr="",
            status="error",
            reason="avrdude timed out after 60 s",
        )

    ok = proc.returncode == 0
    return UploadResult(
        ok=ok,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        status="ok" if ok else "error",
        reason="" if ok else f"avrdude exited {proc.returncode}",
    )
