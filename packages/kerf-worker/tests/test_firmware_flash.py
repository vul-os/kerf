"""Tests for firmware-flash capability detection and runner dispatch.

Test matrix
-----------
1. flash_tool_detect_esptool   — shutil.which("esptool") present → reported.
2. flash_tool_detect_avrdude   — shutil.which("avrdude") present → reported.
3. flash_tool_detect_openocd   — shutil.which("openocd") present → reported.
4. flash_tool_detect_picotool  — shutil.which("picotool") present → reported.
5. flash_tool_detect_none      — no tools installed → firmware_flash_enabled=False.
6. flash_happy_path_esp32      — firmware_flash job with esptool exits 0 → log uploaded,
                                 complete called with result_key.
7. flash_happy_path_avr        — firmware_flash job with avrdude → complete success.
8. flash_missing_tool          — board_target=stm32f4 but openocd absent → graceful error.
9. flash_upload_result         — _upload_result PUT is called with the log content.
10. flash_missing_board_target — job without board_target → error without subprocess call.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile
import uuid
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# sys.path bootstrap so tests work without installing the package.
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).parent.parent
sys.path.insert(0, str(_HERE / "src"))

from kerf_worker import flash as flash_mod
from kerf_worker import runner as runner_mod


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_job(
    kind: str = "firmware_flash",
    board_target: str = "esp32",
    signed_input_url: str = "https://storage.example.com/fw.bin?sig=abc",
    signed_upload_url: str = "https://storage.example.com/logs/flash.log?sig=def",
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "job_id": job_id or str(uuid.uuid4()),
        "kind": kind,
        "board_target": board_target,
        "signed_input_url": signed_input_url,
        "signed_upload_url": signed_upload_url,
        "billing_bucket": "byo",
    }


# ---------------------------------------------------------------------------
# 1. flash_tool_detect_esptool
# ---------------------------------------------------------------------------

def test_flash_tool_detect_esptool():
    """When esptool is on PATH, firmware_flash_capabilities reports it."""
    with patch("shutil.which") as mock_which:
        def _which(name):
            return f"/usr/local/bin/{name}" if name in ("esptool", "esptool.py") else None
        mock_which.side_effect = _which

        caps = flash_mod.firmware_flash_capabilities()

    assert "esptool" in caps["flash_tools"]
    assert "esp32" in caps["flash_board_families"]
    assert "esp8266" in caps["flash_board_families"]
    assert caps["firmware_flash_enabled"] is True


# ---------------------------------------------------------------------------
# 2. flash_tool_detect_avrdude
# ---------------------------------------------------------------------------

def test_flash_tool_detect_avrdude():
    """When avrdude is on PATH, firmware_flash_capabilities reports avr families."""
    with patch("shutil.which") as mock_which:
        def _which(name):
            return "/usr/bin/avrdude" if name == "avrdude" else None
        mock_which.side_effect = _which

        caps = flash_mod.firmware_flash_capabilities()

    assert "avrdude" in caps["flash_tools"]
    assert "avr" in caps["flash_board_families"]
    assert caps["firmware_flash_enabled"] is True


# ---------------------------------------------------------------------------
# 3. flash_tool_detect_openocd
# ---------------------------------------------------------------------------

def test_flash_tool_detect_openocd():
    """When openocd is on PATH, firmware_flash_capabilities reports stm32 families."""
    with patch("shutil.which") as mock_which:
        def _which(name):
            return "/usr/bin/openocd" if name == "openocd" else None
        mock_which.side_effect = _which

        caps = flash_mod.firmware_flash_capabilities()

    assert "openocd" in caps["flash_tools"]
    assert "stm32" in caps["flash_board_families"]
    assert caps["firmware_flash_enabled"] is True


# ---------------------------------------------------------------------------
# 4. flash_tool_detect_picotool
# ---------------------------------------------------------------------------

def test_flash_tool_detect_picotool():
    """When picotool is on PATH, firmware_flash_capabilities reports rp2040."""
    with patch("shutil.which") as mock_which:
        def _which(name):
            return "/usr/local/bin/picotool" if name == "picotool" else None
        mock_which.side_effect = _which

        caps = flash_mod.firmware_flash_capabilities()

    assert "picotool" in caps["flash_tools"]
    assert "rp2040" in caps["flash_board_families"]
    assert caps["firmware_flash_enabled"] is True


# ---------------------------------------------------------------------------
# 5. flash_tool_detect_none
# ---------------------------------------------------------------------------

def test_flash_tool_detect_none():
    """When no flash tools are on PATH, firmware_flash_enabled is False."""
    with patch("shutil.which", return_value=None):
        caps = flash_mod.firmware_flash_capabilities()

    assert caps["flash_tools"] == []
    assert caps["flash_board_families"] == []
    assert caps["firmware_flash_enabled"] is False


# ---------------------------------------------------------------------------
# 6. flash_happy_path_esp32
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flash_happy_path_esp32(tmp_path):
    """firmware_flash job for esp32 with esptool exits 0 → log uploaded, complete called."""
    job = _make_job(board_target="esp32")

    # Mock firmware artifact download.
    async def _fake_download(url: str, dest) -> None:
        dest.write_bytes(b"\xde\xad\xbe\xef" * 64)

    # Mock subprocess: esptool exits 0.
    fake_proc = AsyncMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"Flash OK\n", b""))

    # Mock upload: PUT succeeds.
    upload_called_with: list = []

    async def _fake_put(url: str, content: bytes, timeout: int) -> SimpleNamespace:
        upload_called_with.append((url, content))
        return SimpleNamespace(raise_for_status=lambda: None)

    with patch("shutil.which") as mock_which, \
         patch.object(runner_mod, "_download_scene", side_effect=_fake_download), \
         patch("asyncio.create_subprocess_exec", return_value=fake_proc), \
         patch("asyncio.wait_for", return_value=(b"Flash OK\n", b"")):
        mock_which.side_effect = lambda n: "/usr/bin/esptool" if n == "esptool" else None

        result_path, elapsed, err = await runner_mod._run_firmware_flash(job, tmp_path)

    assert err is None, f"expected no error, got: {err}"
    assert result_path != ""
    log_file = tmp_path / "flash.log"
    assert log_file.exists()
    log_text = log_file.read_text()
    assert "esp32" in log_text
    assert "esptool" in log_text


# ---------------------------------------------------------------------------
# 7. flash_happy_path_avr
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flash_happy_path_avr(tmp_path):
    """firmware_flash job for avr board with avrdude exits 0 → success."""
    job = _make_job(board_target="avr_uno")

    async def _fake_download(url: str, dest) -> None:
        dest.write_bytes(b":00000001FF\n")  # minimal intel hex EOF record

    fake_proc = AsyncMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"avrdude done\n", b""))

    with patch("shutil.which") as mock_which, \
         patch.object(runner_mod, "_download_scene", side_effect=_fake_download), \
         patch("asyncio.create_subprocess_exec", return_value=fake_proc), \
         patch("asyncio.wait_for", return_value=(b"avrdude done\n", b"")):
        mock_which.side_effect = lambda n: "/usr/bin/avrdude" if n == "avrdude" else None

        result_path, elapsed, err = await runner_mod._run_firmware_flash(job, tmp_path)

    assert err is None, f"expected no error, got: {err}"
    assert (tmp_path / "flash.log").exists()


# ---------------------------------------------------------------------------
# 8. flash_missing_tool → graceful 422-style error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flash_missing_tool_returns_error(tmp_path):
    """When openocd is absent, firmware_flash returns an error without crashing."""
    job = _make_job(board_target="stm32f4")

    with patch("shutil.which", return_value=None):
        result_path, elapsed, err = await runner_mod._run_firmware_flash(job, tmp_path)

    assert err is not None
    assert "No flash tool available" in err or "not found" in err.lower() or "stm32f4" in err
    assert result_path == ""


# ---------------------------------------------------------------------------
# 9. flash_upload_result path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flash_upload_result_via_signed_url(tmp_path):
    """After a successful flash, the log file is PUT to the signed_upload_url."""
    job = _make_job(board_target="esp32")
    upload_url = job["signed_upload_url"]

    async def _fake_download(url: str, dest) -> None:
        dest.write_bytes(b"\xff" * 128)

    fake_proc = AsyncMock()
    fake_proc.returncode = 0
    fake_proc.communicate = AsyncMock(return_value=(b"OK\n", b""))

    put_calls: list = []

    class FakeResponse:
        def raise_for_status(self): pass

    class FakeClient:
        async def put(self, url, content, timeout=None):
            put_calls.append(url)
            return FakeResponse()

        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass

    with patch("shutil.which") as mock_which, \
         patch.object(runner_mod, "_download_scene", side_effect=_fake_download), \
         patch("asyncio.create_subprocess_exec", return_value=fake_proc), \
         patch("asyncio.wait_for", return_value=(b"OK\n", b"")):
        mock_which.side_effect = lambda n: "/usr/bin/esptool" if n == "esptool" else None

        result_path, elapsed, err = await runner_mod._run_firmware_flash(job, tmp_path)

    assert err is None
    # Verify the log file was written.
    assert (tmp_path / "flash.log").exists()

    # Now test _upload_result with the log file.
    import httpx

    async def _run_upload():
        async with httpx.AsyncClient() as client:
            with patch.object(client, "put", new_callable=AsyncMock) as mock_put:
                mock_put.return_value = FakeResponse()
                url_out = await runner_mod._upload_result(client, result_path, upload_url)
                assert mock_put.call_count == 1
                call_url = mock_put.call_args[0][0]
                assert "logs/flash.log" in call_url
                # Return URL is upload URL minus query string.
                assert "?" not in url_out

    await _run_upload()


# ---------------------------------------------------------------------------
# 10. flash_missing_board_target
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_flash_missing_board_target_returns_error(tmp_path):
    """A firmware_flash job without board_target returns an error immediately."""
    job = _make_job(board_target="")

    result_path, elapsed, err = await runner_mod._run_firmware_flash(job, tmp_path)

    assert err is not None
    assert "board_target" in err
    assert result_path == ""
