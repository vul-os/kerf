"""
kerf_firmware/serial_monitor.py — pyserial-backed serial monitor.

Public API
──────────
  list_ports() -> list[PortInfo]
      Enumerate available serial ports. Returns [] when pyserial is absent.

  SerialReader(port: str, baud: int = 115200)
      Async-style line reader. Emits lines via an event callback or can be
      iterated synchronously in a thread. Falls back to ImportError when
      pyserial is not installed.

When pyserial is not installed the module remains importable; list_ports()
returns an empty list and SerialReader raises ImportError on construction so
callers can show a "install pyserial" hint rather than crashing.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

# ── optional pyserial import ──────────────────────────────────────────────────

try:
    import serial  # type: ignore[import-untyped]
    import serial.tools.list_ports as _list_ports_mod  # type: ignore[import-untyped]
    _PYSERIAL_AVAILABLE = True
except ImportError:
    serial = None  # type: ignore[assignment]
    _list_ports_mod = None  # type: ignore[assignment]
    _PYSERIAL_AVAILABLE = False


# ── data types ────────────────────────────────────────────────────────────────

@dataclass
class PortInfo:
    """Minimal description of an enumerated serial port."""
    device: str
    description: str = ""
    hwid: str = ""


# ── list_ports ────────────────────────────────────────────────────────────────

def list_ports() -> list[PortInfo]:
    """
    Return a list of available serial ports.

    Uses pyserial's ``serial.tools.list_ports.comports()``. When pyserial is
    not installed an empty list is returned (no exception raised).
    """
    if not _PYSERIAL_AVAILABLE:
        return []
    return [
        PortInfo(
            device=p.device,
            description=p.description or "",
            hwid=p.hwid or "",
        )
        for p in _list_ports_mod.comports()
    ]


# ── SerialReader ──────────────────────────────────────────────────────────────

class SerialReader:
    """
    Line-by-line serial reader backed by pyserial.

    Parameters
    ----------
    port:
        OS device path, e.g. ``/dev/ttyUSB0`` or ``COM3``.
    baud:
        Baud rate. Defaults to 115200.
    on_line:
        Optional callback ``(line: str) -> None`` invoked from the reader
        thread for each decoded line (newline stripped).
    on_error:
        Optional callback ``(exc: Exception) -> None`` invoked when a read
        error occurs. If not supplied, errors are silently swallowed after the
        reader thread exits.

    Raises
    ------
    ImportError
        When pyserial is not installed.

    Usage
    -----
    >>> reader = SerialReader("/dev/ttyUSB0", on_line=print)
    >>> reader.start()
    >>> # … do other work …
    >>> reader.stop()

    The reader can also be used as a context manager::

        with SerialReader("/dev/ttyUSB0") as r:
            r.on_line = handle_line
    """

    def __init__(
        self,
        port: str,
        baud: int = 115200,
        on_line: Callable[[str], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        if not _PYSERIAL_AVAILABLE:
            raise ImportError(
                "pyserial is not installed. "
                "Install it with: pip install pyserial"
            )
        self.port = port
        self.baud = baud
        self.on_line = on_line
        self.on_error = on_error

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._conn: "serial.Serial | None" = None  # type: ignore[name-defined]

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Open the port and begin reading in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name=f"serial-reader-{self.port}",
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the reader thread to stop and wait for it to finish."""
        self._stop_event.set()
        if self._conn is not None:
            try:
                self._conn.cancel_read()
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    # ── context manager ───────────────────────────────────────────────────────

    def __enter__(self) -> "SerialReader":
        self.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.stop()

    # ── internal ──────────────────────────────────────────────────────────────

    def _run(self) -> None:
        try:
            with serial.Serial(self.port, self.baud, timeout=1) as conn:
                self._conn = conn
                while not self._stop_event.is_set():
                    try:
                        raw = conn.readline()
                    except Exception as exc:
                        if self._stop_event.is_set():
                            break
                        if self.on_error is not None:
                            self.on_error(exc)
                        break
                    if raw:
                        line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
                        if self.on_line is not None:
                            self.on_line(line)
        except Exception as exc:
            if self.on_error is not None:
                self.on_error(exc)
        finally:
            self._conn = None
