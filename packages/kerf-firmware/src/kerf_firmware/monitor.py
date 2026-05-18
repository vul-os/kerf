"""
Serial monitor abstraction for kerf-firmware.

Wraps the PlatformIO serial monitor (`pio device monitor`) as a subprocess and
streams its output line-by-line to a caller-supplied callback.

The monitor is intentionally simple: it connects, streams until the timeout
or until the caller cancels, and returns the captured lines.

For the hosted Kerf service the serial port is on the *user's local machine*,
not the server — so the monitor is invoked on the user's side via the Kerf SDK
or CLI, not inside the cloud worker.  This module is therefore primarily for
local/self-hosted installs and the kerf-cli flash+monitor workflow.

CLI shape (PlatformIO 6.x):

    pio device monitor \\
        --port <port>          \\   # e.g. /dev/ttyUSB0, COM3
        --baud <baud>          \\   # default 9600
        --filter time          \\   # prefix each line with a timestamp
        --eol LF

Graceful degrade: when PlatformIO is not installed the function returns a
sentinel MonitorResult with a NOT_INSTALLED warning.
"""
from __future__ import annotations

import shutil
import subprocess
import threading
from typing import Callable, NamedTuple


# ── result type ───────────────────────────────────────────────────────────────

class MonitorResult(NamedTuple):
    lines: list[str]         # captured output lines
    port: str                # the serial port used
    baud: int                # the baud rate used
    warnings: list[str]      # non-fatal warnings (e.g. PIO not installed)
    error: str | None        # fatal error message, or None on success


# ── binary probe ──────────────────────────────────────────────────────────────

def _pio_binary() -> str | None:
    for name in ("pio", "platformio"):
        found = shutil.which(name)
        if found:
            return found
    return None


# ── public entry point ────────────────────────────────────────────────────────

def open_serial_monitor(
    port: str,
    baud: int = 9600,
    duration_s: float = 10.0,
    line_callback: Callable[[str], None] | None = None,
) -> MonitorResult:
    """
    Open the PlatformIO serial monitor for `duration_s` seconds.

    Parameters
    ----------
    port:
        Serial port path (e.g. '/dev/ttyUSB0', 'COM3').
    baud:
        Baud rate.  Default 9600.
    duration_s:
        How long to capture output before closing the monitor.
    line_callback:
        Optional callable called with each captured line as it arrives.

    Returns
    -------
    MonitorResult
        Captured lines + metadata.  Never raises — errors are expressed as
        the ``error`` field so the FastAPI route can always return a response.
    """
    binary = _pio_binary()
    if binary is None:
        hint = (
            "PlatformIO Core CLI not found. "
            "Install: pip install platformio  |  brew install platformio"
        )
        return MonitorResult(
            lines=[],
            port=port,
            baud=baud,
            warnings=[hint],
            error="PIO_NOT_INSTALLED",
        )

    cmd = [
        binary, "device", "monitor",
        "--port", port,
        "--baud", str(baud),
        "--filter", "time",
        "--eol", "LF",
    ]

    captured: list[str] = []
    warnings: list[str] = []

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return MonitorResult(
            lines=[],
            port=port,
            baud=baud,
            warnings=[],
            error=f"Failed to start serial monitor: {exc}",
        )

    # Read lines in a thread so we can enforce the wall-clock timeout.
    def _reader():
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip("\n")
            captured.append(line)
            if line_callback:
                try:
                    line_callback(line)
                except Exception:  # noqa: BLE001
                    pass

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()
    reader_thread.join(timeout=duration_s)

    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()

    if not captured:
        warnings.append(f"No output received from {port} in {duration_s:.0f}s")

    return MonitorResult(
        lines=captured,
        port=port,
        baud=baud,
        warnings=warnings,
        error=None,
    )
