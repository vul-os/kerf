"""Main worker loop.

Responsibilities:
- Heartbeat every 30 s.
- Long-poll claim-job every 30 s.
- On claim: download scene from signed URL, dispatch subprocess, upload result.
- Handle SIGTERM / SIGINT for clean shutdown.

Job kinds
---------
cycles_render
    ``blender -b scene.blend -o out -F PNG -f 1``
    Requires: Blender in PATH (``blender`` or BLENDER_PATH env).

fem_solve
    ``ccx <input-stem>``
    Requires: CalculiX ``ccx`` in PATH (or CCX_PATH env).

firmware_flash
    Flash a firmware artifact to a locally-attached board.  Requires one of:
      - esptool / esptool.py  (ESP32 / ESP8266)
      - avrdude               (Arduino AVR / ATmega)
      - openocd               (STM32 / ARM Cortex-M)
      - picotool              (RP2040)
    Tool selection is automatic based on ``board_target`` from the job payload.
    The flash log is uploaded via ``signed_upload_url`` (Wave 4D path).
    ``billing_bucket='byo'`` → zero credit consumption.

Other kinds are logged as unsupported and the job is completed with an error
so the server can re-queue it on a different worker.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from kerf_worker import config

logger = logging.getLogger("kerf_worker")

HEARTBEAT_INTERVAL = 30  # seconds
CLAIM_POLL_INTERVAL = 2   # seconds between poll attempts within a 30 s window


# ---------------------------------------------------------------------------
# HTTP client helpers
# ---------------------------------------------------------------------------

def _headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _heartbeat_once(
    client: httpx.AsyncClient, base: str, worker_id: str, token: str, status: str = "online"
) -> None:
    url = f"{base}/api/workers/{worker_id}/heartbeat"
    try:
        resp = await client.post(url, json={"status": status}, headers=_headers(token), timeout=15)
        resp.raise_for_status()
        # Update last_heartbeat in local config.
        cfg = config.load()
        if cfg:
            cfg.last_heartbeat = datetime.now(tz=timezone.utc).isoformat()
            config.save(cfg)
        logger.debug("heartbeat ok")
    except Exception as exc:
        logger.warning("heartbeat failed: %s", exc)


async def _claim_job(
    client: httpx.AsyncClient, base: str, worker_id: str, token: str
) -> Optional[Dict[str, Any]]:
    """Long-poll claim-job.  Returns job dict or None (204 / network error)."""
    url = f"{base}/api/workers/{worker_id}/claim-job"
    try:
        resp = await client.post(url, headers=_headers(token), timeout=35)
        if resp.status_code == 204:
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        logger.warning("claim-job error: %s", exc)
        return None


async def _complete_job(
    client: httpx.AsyncClient,
    base: str,
    worker_id: str,
    job_id: str,
    token: str,
    signed_url: str,
    gpu_seconds: float = 0.0,
    error: Optional[str] = None,
) -> None:
    url = f"{base}/api/workers/{worker_id}/jobs/{job_id}/complete"
    payload: Dict[str, Any] = {"signed_url": signed_url, "gpu_seconds": gpu_seconds}
    if error:
        payload["error"] = error
    try:
        resp = await client.post(url, json=payload, headers=_headers(token), timeout=30)
        resp.raise_for_status()
        logger.info("job %s completed (error=%s)", job_id, error)
    except Exception as exc:
        logger.warning("complete-job error for %s: %s", job_id, exc)


# ---------------------------------------------------------------------------
# Scene download
# ---------------------------------------------------------------------------

async def _download_scene(signed_url: str, dest: Path) -> None:
    """Download the scene blob from a signed URL to *dest*."""
    async with httpx.AsyncClient() as dl:
        async with dl.stream("GET", signed_url, timeout=120) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                async for chunk in resp.aiter_bytes(65536):
                    fh.write(chunk)


# ---------------------------------------------------------------------------
# Job dispatchers
# ---------------------------------------------------------------------------

async def _run_cycles(job: Dict[str, Any], workdir: Path) -> tuple[str, float, Optional[str]]:
    """Run Blender Cycles on the downloaded scene file.

    Returns (result_url_or_path, gpu_seconds, error_or_None).
    The result_url_or_path here is the local output path; the caller is
    responsible for uploading to blob storage if needed.  For BYO workers
    the server accepts a file:// or pre-signed upload URL.
    """
    import time

    scene_blob_hash = job.get("scene_blob_hash", "")
    signed_input_url = job.get("signed_input_url") or job.get("scene_blob_hash")
    # The claim-job response may embed a signed download URL under "signed_input_url".
    # Fall back to the blob hash as a path prefix if not present (server should provide it).

    scene_path = workdir / "scene.blend"
    output_path = workdir / "out"
    output_path.mkdir(exist_ok=True)

    # Download scene if a real signed URL is present.
    if signed_input_url and signed_input_url.startswith("http"):
        try:
            await _download_scene(signed_input_url, scene_path)
        except Exception as exc:
            return ("", 0.0, f"scene download failed: {exc}")
    else:
        # In test / offline scenarios the file is already at scene_path.
        if not scene_path.exists():
            return ("", 0.0, "scene.blend not found and no download URL provided")

    blender_bin = os.environ.get("BLENDER_PATH", "blender")
    cmd = [
        blender_bin,
        "-b", str(scene_path),
        "-o", str(output_path / "frame_"),
        "-F", "PNG",
        "-f", "1",
    ]

    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workdir),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1800)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return ("", time.monotonic() - t0, "blender render timed out after 30 min")
    except FileNotFoundError:
        return ("", 0.0, f"Blender not found at '{blender_bin}'; add to PATH or set BLENDER_PATH")
    except Exception as exc:
        return ("", time.monotonic() - t0, f"blender error: {exc}")

    gpu_secs = time.monotonic() - t0

    if proc.returncode != 0:
        err_text = (stderr or b"").decode(errors="replace")[-500:]
        return ("", gpu_secs, f"blender exited {proc.returncode}: {err_text}")

    # Find the rendered frame.
    rendered_files = list(output_path.glob("frame_*.png"))
    if not rendered_files:
        rendered_files = list(output_path.glob("*.png"))
    if not rendered_files:
        return ("", gpu_secs, "blender completed but no PNG output found")

    result_path = str(rendered_files[0])
    # In a real deployment the caller uploads this to blob storage and returns
    # the signed URL.  We return the local path; the run loop handles upload.
    return (result_path, gpu_secs, None)


async def _run_fem(job: Dict[str, Any], workdir: Path) -> tuple[str, float, Optional[str]]:
    """Run CalculiX on a downloaded .inp file."""
    import time

    signed_input_url = job.get("signed_input_url")
    inp_path = workdir / "input.inp"

    if signed_input_url and signed_input_url.startswith("http"):
        try:
            await _download_scene(signed_input_url, inp_path)
        except Exception as exc:
            return ("", 0.0, f"input download failed: {exc}")
    else:
        if not inp_path.exists():
            return ("", 0.0, "input.inp not found and no download URL provided")

    ccx_bin = os.environ.get("CCX_PATH", "ccx")
    stem = inp_path.stem  # "input"
    cmd = [ccx_bin, stem]

    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workdir),
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=3600)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return ("", time.monotonic() - t0, "ccx timed out after 60 min")
    except FileNotFoundError:
        return ("", 0.0, f"CalculiX not found at '{ccx_bin}'; add to PATH or set CCX_PATH")
    except Exception as exc:
        return ("", time.monotonic() - t0, f"ccx error: {exc}")

    gpu_secs = time.monotonic() - t0

    if proc.returncode != 0:
        err_text = (stderr or b"").decode(errors="replace")[-500:]
        return ("", gpu_secs, f"ccx exited {proc.returncode}: {err_text}")

    # CalculiX writes <stem>.frd — find it.
    frd_files = list(workdir.glob("*.frd"))
    if not frd_files:
        return ("", gpu_secs, "ccx completed but no .frd output found")

    return (str(frd_files[0]), gpu_secs, None)


async def _run_firmware_flash(
    job: Dict[str, Any], workdir: Path
) -> tuple[str, float, Optional[str]]:
    """Download a firmware artifact and flash it to a locally-attached board.

    Returns (log_path, elapsed_seconds, error_or_None).

    The flash log is written to ``workdir/flash.log`` and then uploaded via
    ``signed_upload_url`` by the caller.  ``billing_bucket='byo'`` is implicit
    — no credits are ever consumed for firmware_flash jobs.

    Parameters
    ----------
    job:
        Claim-job response dict.  Expected keys:
          ``signed_input_url``  — presigned GET URL for the firmware artifact.
          ``board_target``      — board identifier, e.g. ``"esp32"``, ``"stm32f4"``.
          ``signed_upload_url`` — presigned PUT URL for the flash log.
    workdir:
        Temporary working directory managed by the caller.
    """
    import time
    from kerf_worker.flash import tool_for_board

    board_target: str = job.get("board_target", "").strip()
    if not board_target:
        return ("", 0.0, "firmware_flash job missing 'board_target' in payload")

    # Select the appropriate flash tool (checks PATH).
    tool_name = tool_for_board(board_target)
    if tool_name is None:
        return (
            "", 0.0,
            f"No flash tool available for board_target={board_target!r}. "
            "Install esptool, avrdude, openocd, or picotool and re-enroll."
        )

    # Download the firmware artifact.
    signed_input_url: Optional[str] = job.get("signed_input_url")
    fw_ext = ".bin"
    if board_target.lower().startswith("avr"):
        fw_ext = ".hex"

    fw_path = workdir / f"firmware{fw_ext}"

    if signed_input_url and signed_input_url.startswith("http"):
        try:
            await _download_scene(signed_input_url, fw_path)
        except Exception as exc:
            return ("", 0.0, f"firmware artifact download failed: {exc}")
    else:
        if not fw_path.exists():
            return ("", 0.0, "firmware artifact not found and no download URL provided")

    # Build the flash command.
    cmd = _build_flash_cmd(tool_name, str(fw_path), board_target)
    log_path = workdir / "flash.log"

    t0 = time.monotonic()
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workdir),
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - t0
        return ("", elapsed, f"flash tool timed out after 120 s (board={board_target})")
    except FileNotFoundError:
        return (
            "", 0.0,
            f"Flash tool binary '{cmd[0]}' not found. "
            "Ensure it is installed and on PATH."
        )
    except Exception as exc:
        elapsed = time.monotonic() - t0
        return ("", elapsed, f"flash subprocess error: {exc}")

    elapsed = time.monotonic() - t0

    stdout_text = (stdout_bytes or b"").decode(errors="replace")
    stderr_text = (stderr_bytes or b"").decode(errors="replace")
    log_content = (
        f"board_target: {board_target}\n"
        f"tool: {tool_name}\n"
        f"command: {' '.join(cmd)}\n"
        f"elapsed: {elapsed:.1f}s\n"
        f"exit_code: {proc.returncode}\n"
        f"\n--- STDOUT ---\n{stdout_text}"
        f"\n--- STDERR ---\n{stderr_text}"
    )
    log_path.write_text(log_content)

    if proc.returncode != 0:
        return (
            str(log_path),
            elapsed,
            f"flash tool exited {proc.returncode}: {stderr_text[-500:]}",
        )

    return (str(log_path), elapsed, None)


def _build_flash_cmd(tool: str, firmware_path: str, board_target: str) -> list[str]:
    """Return the subprocess argv for the given flash tool + board."""
    bt = board_target.lower()

    if tool == "esptool":
        # Prefer 'esptool' over 'esptool.py' if both exist.
        binary = shutil.which("esptool") or shutil.which("esptool.py") or "esptool"
        chip = "auto"
        if "esp8266" in bt:
            chip = "esp8266"
        elif "esp32s2" in bt:
            chip = "esp32s2"
        elif "esp32s3" in bt:
            chip = "esp32s3"
        elif "esp32c3" in bt:
            chip = "esp32c3"
        elif "esp32" in bt:
            chip = "esp32"
        return [
            binary,
            "--chip", chip,
            "write_flash", "--flash_mode", "dio",
            "0x0", firmware_path,
        ]

    if tool == "openocd":
        cfg_file = "target/stm32f4x.cfg"
        if "f1" in bt:
            cfg_file = "target/stm32f1x.cfg"
        elif "f7" in bt:
            cfg_file = "target/stm32f7x.cfg"
        elif "h7" in bt:
            cfg_file = "target/stm32h7x.cfg"
        return [
            "openocd",
            "-f", cfg_file,
            "-c", f"program {firmware_path} verify reset exit",
        ]

    if tool == "picotool":
        return ["picotool", "load", "-f", firmware_path]

    # Default: avrdude
    part = "atmega328p"
    if "mega" in bt or "2560" in bt:
        part = "atmega2560"
    elif "32u4" in bt:
        part = "atmega32u4"
    elif "tiny85" in bt or "attiny85" in bt:
        part = "attiny85"
    return [
        "avrdude",
        "-c", "arduino",
        "-p", part,
        "-U", f"flash:w:{firmware_path}:{'i' if firmware_path.endswith('.hex') else 'r'}",
    ]


# ---------------------------------------------------------------------------
# Upload helper (stub — in real use would PUT to a signed upload URL)
# ---------------------------------------------------------------------------

async def _upload_result(
    client: httpx.AsyncClient, local_path: str, upload_url: Optional[str]
) -> str:
    """Upload a local result file to a signed URL and return the public URL.

    If no upload URL is provided (BYO scenario without cloud storage), returns
    the ``file://`` URI so the server at least records *something*.
    """
    if not upload_url or not upload_url.startswith("http"):
        return f"file://{local_path}"

    with open(local_path, "rb") as fh:
        data = fh.read()
    resp = await client.put(upload_url, content=data, timeout=120)
    resp.raise_for_status()
    # Return the upload URL minus query string as the result URL.
    return upload_url.split("?")[0]


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

async def run_loop(stop_event: Optional[asyncio.Event] = None) -> None:
    """Heartbeat + claim-job main loop.

    Runs until *stop_event* is set (or SIGTERM / SIGINT on the main thread).
    """
    cfg = config.load()
    if cfg is None:
        raise RuntimeError(
            "Not enrolled. Run `kerf-worker enroll <TOKEN>` first."
        )

    base = os.environ.get("KERF_API_URL", cfg.api_base).rstrip("/")
    worker_id = cfg.worker_id
    token = cfg.token

    if stop_event is None:
        stop_event = asyncio.Event()

    # Wire OS signals when running in the main thread.
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, ValueError):
            # Windows / non-main-thread — skip.
            pass

    logger.info("kerf-worker started: worker_id=%s api=%s", worker_id, base)
    last_heartbeat_time = 0.0

    async with httpx.AsyncClient() as client:
        while not stop_event.is_set():
            import time
            now = time.monotonic()

            # Heartbeat every 30 s.
            if now - last_heartbeat_time >= HEARTBEAT_INTERVAL:
                await _heartbeat_once(client, base, worker_id, token)
                last_heartbeat_time = time.monotonic()

            # Try to claim a job (server holds poll up to 30 s).
            job = await _claim_job(client, base, worker_id, token)

            if job is None:
                # No job in the polling window — loop again.
                if stop_event.is_set():
                    break
                continue

            job_id = job["job_id"]
            # firmware_flash jobs use "kind"; render jobs use "preset".
            job_kind = job.get("kind") or job.get("preset") or "cycles_render"

            # Mark worker busy.
            cfg2 = config.load()
            if cfg2:
                cfg2.current_job = job_id
                config.save(cfg2)

            logger.info("claimed job=%s kind=%s", job_id, job_kind)

            with tempfile.TemporaryDirectory(prefix="kerf_worker_") as tmpdir:
                workdir = Path(tmpdir)

                if job_kind in ("cycles_render", "render"):
                    result_path, gpu_secs, err = await _run_cycles(job, workdir)
                elif job_kind in ("fem_solve", "fem"):
                    result_path, gpu_secs, err = await _run_fem(job, workdir)
                elif job_kind in ("firmware_flash", "flash"):
                    result_path, gpu_secs, err = await _run_firmware_flash(job, workdir)
                else:
                    logger.warning("unsupported job kind: %r — skipping", job_kind)
                    await _complete_job(
                        client, base, worker_id, job_id, token,
                        signed_url="",
                        error=f"unsupported job kind: {job_kind!r}",
                    )
                    continue

                # Upload result.
                upload_url = job.get("signed_upload_url")
                if err:
                    await _complete_job(
                        client, base, worker_id, job_id, token,
                        signed_url="",
                        gpu_seconds=gpu_secs,
                        error=err,
                    )
                else:
                    result_url = await _upload_result(client, result_path, upload_url)
                    await _complete_job(
                        client, base, worker_id, job_id, token,
                        signed_url=result_url,
                        gpu_seconds=gpu_secs,
                    )

            # Clear current job.
            cfg3 = config.load()
            if cfg3:
                cfg3.current_job = None
                config.save(cfg3)

    logger.info("kerf-worker stopped")
