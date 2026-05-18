"""
tests/test_serial_monitor.py — tests for kerf_firmware.serial_monitor.

Strategy
────────
- pyserial is mocked throughout so tests run without hardware.
- T1: list_ports — with mocked comports returns expected PortInfo objects.
- T2: list_ports — when pyserial is absent returns empty list.
- T3: SerialReader — when pyserial is absent raises ImportError.
- T4: SerialReader — reads lines from a fake stream and emits via on_line.
- T5: SerialReader — stop() terminates the reader thread.
- T6: SerialReader — on_error callback is invoked on read failure.
- T7: SerialReader — context manager start/stop lifecycle.
"""
from __future__ import annotations

import sys
import threading
import types
import unittest.mock as mock
from io import BytesIO

import pytest


# ---------------------------------------------------------------------------
# Helpers to build a minimal fake pyserial module tree
# ---------------------------------------------------------------------------

def _make_fake_serial_module(fake_ports=None, fake_lines=None):
    """
    Build a minimal ``serial`` module stub that mimics the parts of pyserial
    used by serial_monitor.

    Parameters
    ----------
    fake_ports:
        List of objects with ``.device``, ``.description``, ``.hwid``.
    fake_lines:
        If given, the bytes that ``serial.Serial.readline()`` should return,
        one per call. After the list is exhausted subsequent calls block
        (return b"") so the reader thread exits cleanly when stop() is called.
    """
    fake_ports = fake_ports or []
    fake_lines = list(fake_lines) if fake_lines else []

    # Build serial.tools.list_ports sub-module
    list_ports_mod = types.ModuleType("serial.tools.list_ports")
    list_ports_mod.comports = mock.MagicMock(return_value=fake_ports)

    tools_mod = types.ModuleType("serial.tools")
    tools_mod.list_ports = list_ports_mod

    # Build serial.Serial context manager
    call_index = {"i": 0}

    class FakeSerial:
        def __init__(self, port, baud, timeout=1):
            self.port = port
            self.baud = baud

        def readline(self):
            idx = call_index["i"]
            call_index["i"] += 1
            if idx < len(fake_lines):
                return fake_lines[idx]
            # Block-then-return b"" so the thread sees empty reads and exits
            return b""

        def cancel_read(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    serial_mod = types.ModuleType("serial")
    serial_mod.Serial = FakeSerial
    serial_mod.tools = tools_mod

    return serial_mod, tools_mod, list_ports_mod


def _inject_fake_serial(monkeypatch, **kwargs):
    """Inject a fake serial module and reload serial_monitor."""
    serial_mod, tools_mod, list_ports_mod = _make_fake_serial_module(**kwargs)

    monkeypatch.setitem(sys.modules, "serial", serial_mod)
    monkeypatch.setitem(sys.modules, "serial.tools", tools_mod)
    monkeypatch.setitem(sys.modules, "serial.tools.list_ports", list_ports_mod)

    # Remove cached module so reload picks up the new mock
    monkeypatch.delitem(sys.modules, "kerf_firmware.serial_monitor", raising=False)

    from kerf_firmware import serial_monitor  # noqa: PLC0415
    # Patch module-level variables to reflect the injected mock
    monkeypatch.setattr(serial_monitor, "_PYSERIAL_AVAILABLE", True)
    monkeypatch.setattr(serial_monitor, "serial", serial_mod)
    monkeypatch.setattr(serial_monitor, "_list_ports_mod", list_ports_mod)

    return serial_monitor, list_ports_mod


# ---------------------------------------------------------------------------
# T1 — list_ports with mocked comports
# ---------------------------------------------------------------------------

class TestListPorts:
    def test_returns_port_info_objects(self, monkeypatch):
        """list_ports() converts pyserial ListPortInfo objects to PortInfo."""
        fake_port = mock.MagicMock()
        fake_port.device = "/dev/ttyUSB0"
        fake_port.description = "Arduino Uno"
        fake_port.hwid = "USB VID:PID=2341:0043"

        sm, _ = _inject_fake_serial(monkeypatch, fake_ports=[fake_port])

        result = sm.list_ports()
        assert len(result) == 1
        assert result[0].device == "/dev/ttyUSB0"
        assert result[0].description == "Arduino Uno"
        assert result[0].hwid == "USB VID:PID=2341:0043"

    def test_multiple_ports(self, monkeypatch):
        """list_ports() returns all enumerated ports."""
        ports = []
        for i in range(3):
            p = mock.MagicMock()
            p.device = f"/dev/ttyUSB{i}"
            p.description = f"Device {i}"
            p.hwid = ""
            ports.append(p)

        sm, _ = _inject_fake_serial(monkeypatch, fake_ports=ports)

        result = sm.list_ports()
        assert len(result) == 3
        assert [r.device for r in result] == ["/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyUSB2"]

    def test_empty_when_no_ports(self, monkeypatch):
        sm, _ = _inject_fake_serial(monkeypatch, fake_ports=[])
        assert sm.list_ports() == []

    def test_port_info_dataclass_fields(self, monkeypatch):
        """PortInfo exposes device, description, hwid."""
        p = mock.MagicMock()
        p.device = "COM3"
        p.description = "Silicon Labs CP210x"
        p.hwid = "PNP0501"

        sm, _ = _inject_fake_serial(monkeypatch, fake_ports=[p])
        info = sm.list_ports()[0]

        assert hasattr(info, "device")
        assert hasattr(info, "description")
        assert hasattr(info, "hwid")


# ---------------------------------------------------------------------------
# T2 — list_ports when pyserial is absent
# ---------------------------------------------------------------------------

class TestListPortsNoPyserial:
    def test_returns_empty_list_when_pyserial_absent(self, monkeypatch):
        """When pyserial is not installed list_ports() returns []."""
        # Remove pyserial from sys.modules to simulate absence
        monkeypatch.delitem(sys.modules, "serial", raising=False)
        monkeypatch.delitem(sys.modules, "serial.tools", raising=False)
        monkeypatch.delitem(sys.modules, "serial.tools.list_ports", raising=False)
        monkeypatch.delitem(sys.modules, "kerf_firmware.serial_monitor", raising=False)

        from kerf_firmware import serial_monitor  # noqa: PLC0415
        monkeypatch.setattr(serial_monitor, "_PYSERIAL_AVAILABLE", False)

        result = serial_monitor.list_ports()
        assert result == []


# ---------------------------------------------------------------------------
# T3 — SerialReader raises ImportError when pyserial absent
# ---------------------------------------------------------------------------

class TestSerialReaderNoPyserial:
    def test_raises_import_error_on_construction(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "kerf_firmware.serial_monitor", raising=False)
        from kerf_firmware import serial_monitor  # noqa: PLC0415
        monkeypatch.setattr(serial_monitor, "_PYSERIAL_AVAILABLE", False)

        with pytest.raises(ImportError, match="pyserial is not installed"):
            serial_monitor.SerialReader("/dev/ttyUSB0")

    def test_error_message_includes_install_hint(self, monkeypatch):
        monkeypatch.delitem(sys.modules, "kerf_firmware.serial_monitor", raising=False)
        from kerf_firmware import serial_monitor  # noqa: PLC0415
        monkeypatch.setattr(serial_monitor, "_PYSERIAL_AVAILABLE", False)

        with pytest.raises(ImportError, match="pip install pyserial"):
            serial_monitor.SerialReader("/dev/ttyUSB0")


# ---------------------------------------------------------------------------
# T4 — SerialReader yields decoded lines from a fake stream
# ---------------------------------------------------------------------------

class TestSerialReaderLines:
    def test_on_line_callback_receives_decoded_lines(self, monkeypatch):
        """Reader emits stripped, decoded UTF-8 lines via on_line callback."""
        fake_lines = [b"hello\r\n", b"world\n", b"foo\r\n"]
        sm, _ = _inject_fake_serial(monkeypatch, fake_lines=fake_lines)

        received: list[str] = []
        done = threading.Event()

        def _on_line(line: str) -> None:
            received.append(line)
            if len(received) >= len(fake_lines):
                done.set()

        reader = sm.SerialReader("/dev/ttyUSB0", baud=9600, on_line=_on_line)
        reader.start()
        done.wait(timeout=2)
        reader.stop()

        assert received == ["hello", "world", "foo"]

    def test_invalid_utf8_is_replaced_not_raised(self, monkeypatch):
        """Bytes that are not valid UTF-8 are decoded with errors='replace'."""
        fake_lines = [b"\xff\xfe bad bytes\r\n"]
        sm, _ = _inject_fake_serial(monkeypatch, fake_lines=fake_lines)

        received: list[str] = []
        done = threading.Event()

        def _on_line(line: str) -> None:
            received.append(line)
            done.set()

        reader = sm.SerialReader("/dev/ttyUSB0", on_line=_on_line)
        reader.start()
        done.wait(timeout=2)
        reader.stop()

        assert len(received) == 1
        # The replacement character U+FFFD should appear for invalid bytes
        assert "�" in received[0] or "bad bytes" in received[0]

    def test_custom_baud_rate_passed_to_serial(self, monkeypatch):
        """The baud rate supplied to SerialReader is forwarded to serial.Serial."""
        opened_with: dict = {}

        sm, _ = _inject_fake_serial(monkeypatch)

        original_serial = sm.serial.Serial

        class CapturingSerial(original_serial):
            def __init__(self, port, baud, **kw):
                opened_with["port"] = port
                opened_with["baud"] = baud
                super().__init__(port, baud, **kw)

        monkeypatch.setattr(sm.serial, "Serial", CapturingSerial)

        done = threading.Event()
        reader = sm.SerialReader("/dev/ttyACM0", baud=57600, on_line=lambda _: done.set())
        reader.start()
        done.wait(timeout=1)
        reader.stop()

        assert opened_with.get("baud") == 57600
        assert opened_with.get("port") == "/dev/ttyACM0"


# ---------------------------------------------------------------------------
# T5 — stop() terminates the reader thread
# ---------------------------------------------------------------------------

class TestSerialReaderStop:
    def test_stop_joins_thread(self, monkeypatch):
        """After stop() the reader thread is no longer alive."""
        sm, _ = _inject_fake_serial(monkeypatch)

        reader = sm.SerialReader("/dev/ttyUSB0", on_line=lambda _: None)
        reader.start()
        assert reader._thread is not None
        reader.stop()
        assert reader._thread is None or not reader._thread.is_alive()

    def test_double_start_is_safe(self, monkeypatch):
        """Calling start() twice does not create two threads."""
        sm, _ = _inject_fake_serial(monkeypatch)

        reader = sm.SerialReader("/dev/ttyUSB0", on_line=lambda _: None)
        reader.start()
        thread_id = id(reader._thread)
        reader.start()  # should be a no-op
        assert id(reader._thread) == thread_id
        reader.stop()


# ---------------------------------------------------------------------------
# T6 — on_error callback
# ---------------------------------------------------------------------------

class TestSerialReaderOnError:
    def test_on_error_called_on_read_failure(self, monkeypatch):
        """If readline() raises, on_error is invoked with the exception."""
        sm, _ = _inject_fake_serial(monkeypatch)

        # Patch Serial.readline to raise immediately
        class BustedSerial:
            def __init__(self, port, baud, timeout=1):
                pass

            def readline(self):
                raise OSError("device disconnected")

            def cancel_read(self):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        monkeypatch.setattr(sm.serial, "Serial", BustedSerial)

        errors: list[Exception] = []
        done = threading.Event()

        def _on_error(exc: Exception) -> None:
            errors.append(exc)
            done.set()

        reader = sm.SerialReader("/dev/ttyUSB0", on_line=lambda _: None, on_error=_on_error)
        reader.start()
        done.wait(timeout=2)
        reader.stop()

        assert len(errors) == 1
        assert "device disconnected" in str(errors[0])


# ---------------------------------------------------------------------------
# T7 — context manager
# ---------------------------------------------------------------------------

class TestSerialReaderContextManager:
    def test_context_manager_starts_and_stops(self, monkeypatch):
        """with SerialReader(...) as r: auto-starts; exit auto-stops."""
        fake_lines = [b"context-line\r\n"]
        sm, _ = _inject_fake_serial(monkeypatch, fake_lines=fake_lines)

        received: list[str] = []
        done = threading.Event()

        def _on_line(line: str) -> None:
            received.append(line)
            done.set()

        with sm.SerialReader("/dev/ttyUSB0", on_line=_on_line) as reader:
            done.wait(timeout=2)
            assert reader._thread is not None

        # Thread should be cleaned up on exit
        assert reader._thread is None or not reader._thread.is_alive()
        assert received == ["context-line"]
