"""
stm32flash upload wrapper.

Shells out to the `stm32flash` CLI to flash a binary to an STM32 board
over a serial/UART bootloader connection (BOOT0 pin pulled high).

stm32flash CLI shape:

    stm32flash \\
        -w <file>            # write firmware file
        -v                   # verify after write
        -g 0x0               # execute from address 0x0 after flash
        <port>               # serial port, e.g. /dev/ttyUSB0  COM3

Optional flags accepted via board_meta:
    upload_speed  — baud rate (default: 115200)
    start_address — execute address (default: "0x0")

If `stm32flash` is not on PATH, returns UploadResult(status="pending").

Note: for ST-Link (SWD/JTAG) uploads, OpenOCD or STM32CubeProgrammer is
typically used instead.  stm32flash targets the serial bootloader.
"""
from __future__ import annotations

import shutil
import subprocess
from typing import Any

from kerf_firmware.upload.types import UploadResult

_BINARY = "stm32flash"
_DEFAULT_BAUD = "115200"
_DEFAULT_START = "0x0"


def upload(
    hex_or_bin_path: str,
    port: str,
    board_meta: dict[str, Any],
) -> UploadResult:
    """Flash firmware to an STM32 board via stm32flash (serial bootloader).

    Parameters
    ----------
    hex_or_bin_path:
        Absolute path to the compiled firmware (.bin or .hex).
    port:
        Serial port the board is connected to (e.g. '/dev/ttyUSB0', 'COM3').
    board_meta:
        BoardEntry dict with optional:
          - ``upload_speed``   — baud rate (default: 115200)
          - ``start_address``  — execute start address (default: "0x0")

    Returns
    -------
    UploadResult
        status="pending" when stm32flash is absent;
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
                "stm32flash not found on PATH. "
                "Install it via: sudo apt install stm32flash  "
                "| brew install stm32flash  "
                "| https://sourceforge.net/p/stm32flash"
            ),
        )

    baud = str(board_meta.get("upload_speed", _DEFAULT_BAUD))
    start = board_meta.get("start_address", _DEFAULT_START)

    cmd = [
        binary,
        "-b", baud,
        "-w", hex_or_bin_path,
        "-v",
        "-g", start,
        port,
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
            reason="stm32flash timed out after 60 s",
        )

    ok = proc.returncode == 0
    return UploadResult(
        ok=ok,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        status="ok" if ok else "error",
        reason="" if ok else f"stm32flash exited {proc.returncode}",
    )
