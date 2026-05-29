"""
FirmwareFlashWorker — drains ``firmware_flash_jobs`` rows on behalf of BYO workers.

When running inside the cloud API process this worker *dispatches* jobs by
claiming queued rows and marking them ``running``.  The actual flash execution
happens on the enrolled BYO worker machine (the user's workshop PC with USB-
attached hardware) via the kerf-worker CLI claim-poll loop.

In LOCAL_CLI mode (``KERF_LOCAL_CLI=1``) the worker performs the flash itself
by shelling out to the appropriate tool (esptool / avrdude / openocd) after
downloading the artifact from storage.

Job lifecycle
-------------
  queued  → claimed by a worker (status = 'running')
  running → flash succeeds    → status = 'done',   log_key = <storage key>
          → flash fails       → status = 'error',  error   = <message>

Billing
-------
``billing_bucket = 'byo'`` on every row — no credits are consumed.

Board-target → tool mapping (mirrors firmware_flash_via_worker.py)
--------------------------------------------------------------------
  esp32 / esp8266       → esptool
  avr_*                 → avrdude
  stm32* / openocd      → openocd
  rp2040                → picotool
  * (default)           → avrdude
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import subprocess
import tempfile
import time
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

# ── flash tool selection ───────────────────────────────────────────────────────

_BOARD_TO_TOOL: dict[str, str] = {
    "esp32":    "esptool",
    "esp8266":  "esptool",
    "avr_uno":  "avrdude",
    "avr_mega": "avrdude",
    "avr":      "avrdude",
    "stm32f4":  "openocd",
    "stm32f1":  "openocd",
    "stm32":    "openocd",
    "rp2040":   "picotool",
}


def _flash_tool_for(board_target: str) -> str:
    bt = board_target.lower().strip()
    if bt in _BOARD_TO_TOOL:
        return _BOARD_TO_TOOL[bt]
    for prefix, tool in _BOARD_TO_TOOL.items():
        if bt.startswith(prefix):
            return tool
    return "avrdude"


# ── flash command builders ────────────────────────────────────────────────────

def _build_flash_cmd(tool: str, firmware_path: str, board_target: str) -> list[str]:
    """Return the subprocess argv for the given flash tool."""
    if tool == "esptool":
        return [
            "esptool.py",
            "--chip", "auto",
            "write_flash", "--flash_mode", "dio",
            "0x0", firmware_path,
        ]
    if tool == "openocd":
        cfg = _openocd_cfg_for(board_target)
        return [
            "openocd",
            "-f", cfg,
            "-c", f"program {firmware_path} verify reset exit",
        ]
    if tool == "picotool":
        return ["picotool", "load", "-f", firmware_path]
    # Default: avrdude
    part = _avr_part_for(board_target)
    return [
        "avrdude",
        "-c", "arduino",
        "-p", part,
        "-U", f"flash:w:{firmware_path}:i",
    ]


def _openocd_cfg_for(board_target: str) -> str:
    bt = board_target.lower()
    if "f4" in bt:
        return "target/stm32f4x.cfg"
    if "f1" in bt:
        return "target/stm32f1x.cfg"
    return "target/stm32f4x.cfg"


def _avr_part_for(board_target: str) -> str:
    bt = board_target.lower()
    if "mega" in bt:
        return "atmega2560"
    return "atmega328p"


# ── async worker ─────────────────────────────────────────────────────────────

class FirmwareFlashWorker:
    """Poll ``firmware_flash_jobs`` and execute or relay flash operations.

    In cloud mode (``KERF_LOCAL_CLI`` not set) only BYO workers (enrolled
    kerf-worker agents) should run actual flashes; the server-side instance
    merely keeps the status current.  In local-CLI mode the worker shells
    out to the flash tool directly.
    """

    POLL_INTERVAL = float(os.getenv("FIRMWARE_FLASH_POLL_INTERVAL", "5"))

    def __init__(self, pool: asyncpg.Pool, storage_getter=None):
        self._pool = pool
        self._storage_getter = storage_getter
        self._stop = False
        self._local_cli = os.getenv("KERF_LOCAL_CLI", "") == "1"

    def stop(self) -> None:
        self._stop = True

    async def run(self, _tg=None) -> None:
        logger.info("FirmwareFlashWorker: started (local_cli=%s)", self._local_cli)
        while not self._stop:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("FirmwareFlashWorker: error in tick")
            await asyncio.sleep(self.POLL_INTERVAL)
        logger.info("FirmwareFlashWorker: stopped")

    async def _tick(self) -> None:
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT id, artifact_key, board_target
                    FROM firmware_flash_jobs
                    WHERE status = 'queued'
                    ORDER BY created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                    """
                )
                if row is None:
                    return

                job_id = str(row["id"])
                artifact_key = row["artifact_key"]
                board_target = row["board_target"]

                await conn.execute(
                    """
                    UPDATE firmware_flash_jobs
                    SET status = 'running', started_at = now(), updated_at = now()
                    WHERE id = $1
                    """,
                    row["id"],
                )

        if self._local_cli:
            await self._execute_flash(job_id, artifact_key, board_target)
        else:
            # Cloud relay: job is now 'running'; the BYO worker CLI will pick it
            # up via GET /api/firmware/flash-jobs/claim and complete it.
            logger.info(
                "FirmwareFlashWorker: job %s queued for BYO worker "
                "(artifact=%s board=%s)", job_id, artifact_key, board_target
            )

    async def _execute_flash(
        self,
        job_id: str,
        artifact_key: str,
        board_target: str,
    ) -> None:
        """Download the artifact and run the flash tool (local-CLI path)."""
        loop = asyncio.get_event_loop()
        try:
            result_log, error = await loop.run_in_executor(
                None,
                _run_flash_sync,
                job_id,
                artifact_key,
                board_target,
                self._storage_getter,
            )
        except Exception as exc:
            error = str(exc)
            result_log = ""

        if error:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE firmware_flash_jobs
                    SET status = 'error', error = $2,
                        finished_at = now(), updated_at = now()
                    WHERE id = $1
                    """,
                    job_id,
                    error[:2000],
                )
        else:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE firmware_flash_jobs
                    SET status = 'done', finished_at = now(), updated_at = now()
                    WHERE id = $1
                    """,
                    job_id,
                )


# ── sync flash runner (run in executor) ───────────────────────────────────────

def _run_flash_sync(
    job_id: str,
    artifact_key: str,
    board_target: str,
    storage_getter,
) -> tuple[str, Optional[str]]:
    """Download artifact, run flash tool.  Returns (log, error_or_None)."""
    tool = _flash_tool_for(board_target)
    import shutil
    if shutil.which(tool) is None and tool != "esptool":
        # esptool may be installed as esptool.py — tolerate both
        if tool == "esptool" and shutil.which("esptool.py") is not None:
            tool_bin = "esptool.py"
        else:
            return "", f"Flash tool '{tool}' not found on PATH. Install it to enable local flash."
    else:
        tool_bin = tool

    # Download artifact from storage.
    storage = storage_getter() if storage_getter else None
    if storage is None:
        return "", "Storage not configured — cannot download firmware artifact."

    try:
        firmware_bytes: bytes = _download_artifact_sync(storage, artifact_key)
    except Exception as exc:
        return "", f"Failed to download artifact '{artifact_key}': {exc}"

    with tempfile.TemporaryDirectory() as tmpdir:
        fw_path = os.path.join(tmpdir, "firmware.bin")
        with open(fw_path, "wb") as fh:
            fh.write(firmware_bytes)

        cmd = _build_flash_cmd(tool, fw_path, board_target)
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError:
            return "", f"Flash tool binary not found: {cmd[0]}"
        except subprocess.TimeoutExpired:
            return "", "Flash timed out after 120 seconds."
        except Exception as exc:
            return "", f"Flash subprocess error: {exc}"

        log = f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        if result.returncode != 0:
            return log, f"Flash tool exited {result.returncode}: {result.stderr[-500:]}"
        return log, None


def _download_artifact_sync(storage, key: str) -> bytes:
    """Synchronous download via async storage (runs in thread executor)."""
    import asyncio

    async def _dl():
        # storage.get() may return bytes or a file-like.
        data = await storage.get(key)
        if isinstance(data, (bytes, bytearray)):
            return bytes(data)
        if hasattr(data, "read"):
            return data.read()
        return bytes(data)

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    return loop.run_until_complete(_dl())


__all__ = ["FirmwareFlashWorker"]
