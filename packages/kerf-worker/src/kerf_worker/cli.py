"""kerf-worker CLI — BYO GPU worker companion for Kerf.

Commands
--------
enroll <TOKEN>   Enroll this machine as a BYO GPU worker.
run              Start the worker loop (heartbeat + job dispatch).
status           Print enrollment state, last heartbeat, GPU caps, current job.
revoke           Revoke worker token on the server and remove local config.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Optional

import httpx
import typer

from kerf_worker import config
from kerf_worker import gpu as gpu_probe
from kerf_worker import runner

app = typer.Typer(
    name="kerf-worker",
    help="BYO GPU worker companion CLI for Kerf.",
    no_args_is_help=True,
)

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format=_LOG_FORMAT)


# ---------------------------------------------------------------------------
# enroll
# ---------------------------------------------------------------------------

@app.command()
def enroll(
    token: str = typer.Argument(..., help="One-time enrollment token from kerf.sh Settings → Workers."),
    name: str = typer.Option("", "--name", "-n", help="Human-readable name for this worker (default: hostname)."),
    api_url: str = typer.Option("", "--api-url", help="Kerf API base URL (overrides KERF_API_URL env)."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Enroll this machine as a BYO GPU worker.

    Stores credentials in ~/.config/kerf/worker.json.
    Probes GPU capabilities via nvidia-smi and sends them to the server.
    """
    _setup_logging(verbose)

    base = (
        api_url.rstrip("/")
        or os.environ.get("KERF_API_URL", "").rstrip("/")
        or "https://kerf.sh"
    )

    if not name:
        import socket
        name = socket.gethostname()

    # Probe GPU capabilities before enrolling.
    typer.echo("Probing GPU capabilities...")
    caps = gpu_probe.probe()
    gpu_names = [g["name"] for g in caps.get("gpus", [])]
    if gpu_names:
        typer.echo(f"  Found GPUs: {', '.join(gpu_names)}")
    else:
        typer.echo("  No GPUs detected (NVIDIA/AMD ROCm/Apple Metal) — enrolling anyway (CPU-only).")

    # Call POST /api/workers/enroll.
    url = f"{base}/api/workers/enroll"
    payload = {"name": name, "capabilities": caps}
    typer.echo(f"Enrolling at {url} ...")

    try:
        resp = httpx.post(
            url,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        typer.echo(
            f"Enrollment failed: HTTP {exc.response.status_code} — {exc.response.text[:300]}",
            err=True,
        )
        raise typer.Exit(code=1)
    except httpx.RequestError as exc:
        typer.echo(f"Enrollment failed: could not reach {base} — {exc}", err=True)
        raise typer.Exit(code=1)

    data = resp.json()
    worker_id = data.get("id") or data.get("worker_id")
    if not worker_id:
        typer.echo(f"Unexpected enroll response: {data}", err=True)
        raise typer.Exit(code=1)

    # The server returns the worker ID; the token to use for subsequent API
    # calls is the one-time enrollment token itself (which was returned once
    # from the kerf.sh UI and is now being stored here).
    # The API requires Bearer <worker-token> for heartbeat/claim/complete.
    cfg = config.WorkerConfig(
        worker_id=worker_id,
        token=token,
        api_base=base,
        name=name,
        capabilities=caps,
    )
    config.save(cfg)

    typer.echo(f"Enrolled successfully!")
    typer.echo(f"  Worker ID : {worker_id}")
    typer.echo(f"  Name      : {name}")
    typer.echo(f"  Config    : {config._config_path()}")
    typer.echo("")
    typer.echo("Run `kerf-worker run` to start processing jobs.")


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------

@app.command()
def run(
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Start the worker loop — heartbeat every 30 s, long-poll for jobs.

    Press Ctrl-C or send SIGTERM to stop gracefully.
    """
    _setup_logging(verbose)
    cfg = config.load()
    if cfg is None:
        typer.echo("Not enrolled. Run `kerf-worker enroll <TOKEN>` first.", err=True)
        raise typer.Exit(code=1)

    try:
        asyncio.run(runner.run_loop())
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@app.command()
def status() -> None:
    """Print enrollment info, last heartbeat, GPU capabilities, and current job."""
    cfg = config.load()
    if cfg is None:
        typer.echo("Not enrolled. Run `kerf-worker enroll <TOKEN>` first.")
        raise typer.Exit(code=0)

    typer.echo("=== kerf-worker status ===")
    typer.echo(f"Worker ID      : {cfg.worker_id}")
    typer.echo(f"Name           : {cfg.name or '(unnamed)'}")
    typer.echo(f"API base       : {cfg.api_base}")
    typer.echo(f"Last heartbeat : {cfg.last_heartbeat or '(never)'}")
    typer.echo(f"Current job    : {cfg.current_job or '(none)'}")

    gpus = cfg.capabilities.get("gpus", [])
    if gpus:
        typer.echo("GPUs:")
        for g in gpus:
            mem = g.get("memory_total_mib", 0)
            typer.echo(f"  {g['name']} ({mem} MiB)")
    else:
        typer.echo("GPUs          : (none detected at enroll time)")

    workloads = cfg.capabilities.get("supported_workloads", [])
    typer.echo(f"Workloads      : {', '.join(workloads) or '(none)'}")
    typer.echo(f"Config path    : {config._config_path()}")


# ---------------------------------------------------------------------------
# revoke
# ---------------------------------------------------------------------------

@app.command()
def revoke(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
    api_url: str = typer.Option("", "--api-url", help="Kerf API base URL override."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Revoke the worker token on the server and remove local config."""
    _setup_logging(verbose)

    cfg = config.load()
    if cfg is None:
        typer.echo("No enrolled worker found. Nothing to revoke.")
        raise typer.Exit(code=0)

    if not yes:
        confirmed = typer.confirm(
            f"Revoke worker '{cfg.name or cfg.worker_id}' ({cfg.worker_id})?"
        )
        if not confirmed:
            typer.echo("Aborted.")
            raise typer.Exit(code=0)

    base = (
        api_url.rstrip("/")
        or os.environ.get("KERF_API_URL", "").rstrip("/")
        or cfg.api_base.rstrip("/")
    )

    url = f"{base}/api/workers/{cfg.worker_id}"
    try:
        resp = httpx.delete(
            url,
            headers={"Authorization": f"Bearer {cfg.token}"},
            timeout=15,
        )
        if resp.status_code == 404:
            typer.echo("Worker not found on server (may already be revoked). Removing local config.")
        elif resp.status_code >= 400:
            typer.echo(
                f"Server returned {resp.status_code}: {resp.text[:200]}. Removing local config anyway.",
                err=True,
            )
        else:
            typer.echo("Worker revoked on server.")
    except httpx.RequestError as exc:
        typer.echo(
            f"Could not reach server ({exc}). Removing local config anyway.",
            err=True,
        )

    config.delete()
    typer.echo("Local config removed.")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    app()


if __name__ == "__main__":
    main()
