"""
bossac upload wrapper.

Shells out to the `bossac` CLI to flash a binary to a SAM/SAMD board
(Arduino Due, Zero, MKR family, Adafruit Feather M0, etc.) and to
Raspberry Pi RP2040 boards via the BOSSA bootloader.

bossac CLI shape (bossac >=1.9):

    bossac \\
        --port=<port>        # serial port name (without /dev/ on Linux/macOS)
        --info               # print device info
        --erase              # erase flash before writing
        --write <file>       # firmware BIN file
        --verify             # verify after write
        --reset              # reset board after upload
        --offset=<offset>    # flash offset (default: 0x2000 for most SAM boards)

If `bossac` is not on PATH, returns UploadResult(status="pending").
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any

from kerf_firmware.upload.types import UploadResult

_BINARY = "bossac"

# Default flash offset per MCU family.
# SAM boards with a bootloader typically start at 0x2000 (8 KB bootloader).
# RP2040 uses 0x0 when flashed directly but bossac is rarely used for RP2040;
# included here for completeness.
_MCU_OFFSET: dict[str, str] = {
    "SAMD21":   "0x2000",
    "SAMD51":   "0x4000",
    "SAM3X8E":  "0x0",      # Arduino Due — no bootloader offset
    "RP2040":   "0x0",
}
_DEFAULT_OFFSET = "0x2000"


def _port_basename(port: str) -> str:
    """Strip /dev/ prefix for bossac (it expects just the device name)."""
    if port.startswith("/dev/"):
        return port[len("/dev/"):]
    return port


def upload(
    hex_or_bin_path: str,
    port: str,
    board_meta: dict[str, Any],
) -> UploadResult:
    """Flash a BIN file to a SAM/RP2040 board via bossac.

    Parameters
    ----------
    hex_or_bin_path:
        Absolute path to the compiled firmware (.bin).
    port:
        Serial port the board is connected to (e.g. '/dev/ttyACM0', 'COM3').
    board_meta:
        BoardEntry dict with optional:
          - ``mcu``            — MCU string for offset lookup (e.g. 'SAMD21')
          - ``flash_offset``   — explicit flash offset override (e.g. '0x2000')

    Returns
    -------
    UploadResult
        status="pending" when bossac is absent;
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
                "bossac not found on PATH. "
                "Install it via: sudo apt install bossac  "
                "| brew install bossac  "
                "| https://github.com/shumatech/BOSSA"
            ),
        )

    mcu_raw = board_meta.get("mcu", "")
    offset = board_meta.get("flash_offset") or _MCU_OFFSET.get(mcu_raw, _DEFAULT_OFFSET)
    port_name = _port_basename(port)

    cmd = [
        binary,
        f"--port={port_name}",
        "--erase",
        f"--write={hex_or_bin_path}",
        "--verify",
        "--reset",
        f"--offset={offset}",
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
            reason="bossac timed out after 60 s",
        )

    ok = proc.returncode == 0
    return UploadResult(
        ok=ok,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        status="ok" if ok else "error",
        reason="" if ok else f"bossac exited {proc.returncode}",
    )
