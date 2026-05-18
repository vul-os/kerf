"""
Firmware build and monitor routes.

POST /firmware/build
    Body:  { "sketch_dir": "<abs-path>", "board": "uno", "framework": "arduino",
             "environment": null, "extra_flags": [] }
    Returns: BuildResult JSON or error.

POST /firmware/monitor
    Body:  { "port": "/dev/ttyUSB0", "baud": 9600, "duration_s": 10 }
    Returns: MonitorResult JSON or error.

GET /firmware/boards
    Returns: { "boards": [...] }

The routes never crash — errors are expressed as structured JSON payloads so
the frontend (FirmwareView panel) can always render a meaningful state.
"""
from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.post("/firmware/build")
async def firmware_build_route(req: dict) -> dict:
    """Compile a firmware sketch via the PlatformIO Core CLI subprocess."""
    sketch_dir = req.get("sketch_dir", "")
    board = req.get("board") or "uno"
    framework = req.get("framework") or "arduino"
    environment = req.get("environment") or None
    extra_flags: list[str] = req.get("extra_flags") or []

    if not sketch_dir or not isinstance(sketch_dir, str):
        return _err("'sketch_dir' must be a non-empty string", "BAD_ARGS")

    from kerf_firmware.build import (
        FirmwareBuildError,
        PlatformIONotInstalledError,
        build_firmware,
    )

    try:
        result = build_firmware(
            sketch_dir=sketch_dir,
            board=board,
            framework=framework,
            environment=environment,
            extra_flags=extra_flags or None,
        )
    except PlatformIONotInstalledError as exc:
        return _err(str(exc), "PIO_NOT_INSTALLED")
    except FileNotFoundError:
        return _err(f"Sketch directory not found: {sketch_dir}", "SKETCH_NOT_FOUND")
    except FirmwareBuildError as exc:
        return _err(str(exc), "BUILD_ERROR")
    except Exception as exc:  # noqa: BLE001
        return _err(f"Unexpected error: {exc}", "ERROR")

    return {
        "ok": True,
        "elf_path": result.elf_path,
        "hex_path": result.hex_path,
        "bin_path": result.bin_path,
        "build_log": result.build_log,
        "build_log_lines": result.build_log_lines,
        "artefact_bytes": result.artefact_bytes,
        "environment": result.environment,
        "warnings": result.warnings,
        "error": None,
    }


@router.post("/firmware/monitor")
async def firmware_monitor_route(req: dict) -> dict:
    """Open a PlatformIO serial monitor session."""
    port = req.get("port", "")
    baud = int(req.get("baud") or 9600)
    duration_s = float(req.get("duration_s") or 10.0)

    if not port or not isinstance(port, str):
        return _err("'port' must be a non-empty string", "BAD_ARGS")

    from kerf_firmware.monitor import open_serial_monitor

    result = open_serial_monitor(port=port, baud=baud, duration_s=duration_s)

    return {
        "ok": result.error is None,
        "lines": result.lines,
        "port": result.port,
        "baud": result.baud,
        "warnings": result.warnings,
        "error": result.error,
    }


@router.get("/firmware/boards")
async def firmware_boards_route() -> dict:
    """Return the Kerf board manifest."""
    from kerf_firmware.boards import boards_as_json_manifest
    return boards_as_json_manifest()


# ── helpers ───────────────────────────────────────────────────────────────────

def _err(message: str, code: str) -> dict:
    return {
        "ok": False,
        "elf_path": None,
        "hex_path": None,
        "bin_path": None,
        "build_log": "",
        "build_log_lines": 0,
        "artefact_bytes": 0,
        "environment": "",
        "lines": [],
        "warnings": [message],
        "error": code,
    }
