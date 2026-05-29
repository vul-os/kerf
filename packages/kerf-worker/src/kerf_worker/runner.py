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
            job_kind = job.get("preset") or "cycles_render"

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
