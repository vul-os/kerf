"""
LLM tool: build_firmware

Compiles a firmware sketch by calling the pyworker POST /firmware/build
route, which invokes the PlatformIO Core CLI as a subprocess.

Schema:
  {
    "sketch_dir": "<project-relative path to the sketch directory>",
    "board":      "uno",          # optional, default "uno"
    "framework":  "arduino",      # optional, default "arduino"
    "environment": null           # optional: named PlatformIO environment
  }

Returns:
  ok_payload({
    "elf_path": "...",
    "hex_path": "...",
    "bin_path": "...",
    "build_log_preview": "<first 80 lines>",
    "build_log_lines": N,
    "artefact_bytes": N,
    "environment": "...",
    "warnings": [...]
  })
  err_payload(...) on failure.

Error codes:
  PIO_NOT_INSTALLED  — PlatformIO Core CLI is not on the server PATH.
  SKETCH_NOT_FOUND   — The sketch directory does not exist.
  BUILD_ERROR        — PlatformIO exited non-zero.
  WORKER_ERROR       — Could not reach the pyworker.
  BAD_ARGS           — Invalid arguments.
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_firmware._compat import (  # type: ignore
        ToolSpec, err_payload, ok_payload, register, ProjectCtx,
    )


build_firmware_spec = ToolSpec(
    name="build_firmware",
    description=(
        "Compile a firmware sketch using the PlatformIO Core CLI. "
        "Provide a project-relative path to the sketch directory (must contain "
        "the .ino / .cpp source and optionally a platformio.ini). "
        "Specify the target board ID (e.g. 'uno', 'esp32dev', 'pico') and "
        "framework (e.g. 'arduino', 'espidf'). "
        "Returns the build log, artefact paths (ELF + HEX/BIN), and warnings. "
        "Returns a descriptive error when PlatformIO Core CLI is not installed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sketch_dir": {
                "type": "string",
                "description": (
                    "Absolute project path to the sketch directory "
                    "(e.g. /firmware/blink). The directory must contain at least "
                    "one .ino or .cpp source file."
                ),
            },
            "board": {
                "type": "string",
                "description": (
                    "PlatformIO board ID (e.g. 'uno', 'esp32dev', 'nodemcuv2', "
                    "'bluepill_f103c8', 'pico'). Default: 'uno'. "
                    "Use GET /firmware/boards for the full Kerf board manifest."
                ),
                "default": "uno",
            },
            "framework": {
                "type": "string",
                "description": (
                    "PlatformIO framework (e.g. 'arduino', 'espidf', 'zephyr', 'mbed'). "
                    "Default: 'arduino'."
                ),
                "default": "arduino",
            },
            "environment": {
                "type": "string",
                "description": (
                    "Named PlatformIO environment from an existing platformio.ini. "
                    "Leave null to auto-detect (or use the board ID as the environment name)."
                ),
            },
        },
        "required": ["sketch_dir"],
    },
)


@register(build_firmware_spec, write=False)
async def build_firmware_tool(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    sketch_dir = a.get("sketch_dir", "")
    board = a.get("board") or "uno"
    framework = a.get("framework") or "arduino"
    environment = a.get("environment") or None

    if not sketch_dir or not isinstance(sketch_dir, str):
        return err_payload("sketch_dir is required", "BAD_ARGS")

    # ── Call pyworker ─────────────────────────────────────────────────────────
    pyworker_url = "http://localhost:9090"
    try:
        resp = ctx.http_client.post(
            f"{pyworker_url}/firmware/build",
            json={
                "sketch_dir": sketch_dir,
                "board": board,
                "framework": framework,
                "environment": environment,
            },
            timeout=130.0,  # slightly above the 120 s PlatformIO build timeout
        )
    except Exception as exc:
        return err_payload(f"firmware worker unavailable: {exc}", "WORKER_ERROR")

    if resp.status_code != 200:
        return err_payload(
            f"firmware worker returned status {resp.status_code}",
            "WORKER_ERROR",
        )

    try:
        result = resp.json()
    except Exception:
        return err_payload("invalid firmware build response", "ERROR")

    error_code = result.get("error")
    warnings: list[str] = result.get("warnings", [])

    if error_code == "PIO_NOT_INSTALLED":
        return err_payload(
            "PlatformIO Core CLI not found on the server. "
            "Install with: pip install platformio  |  brew install platformio. "
            + "; ".join(warnings),
            "PIO_NOT_INSTALLED",
        )

    if error_code == "SKETCH_NOT_FOUND":
        return err_payload(
            f"Sketch directory not found: {sketch_dir}",
            "SKETCH_NOT_FOUND",
        )

    if error_code == "BUILD_ERROR":
        log_tail = (result.get("build_log") or "")[-600:]
        return err_payload(
            f"Firmware build failed.\n{log_tail}",
            "BUILD_ERROR",
        )

    if error_code:
        return err_payload(str(error_code), error_code)

    # Return a preview of the first 80 build log lines so the LLM doesn't
    # receive the entire stdout blob (can be several hundred KB for ESP32).
    build_log: str = result.get("build_log") or ""
    preview_lines = build_log.splitlines()[:80]
    build_log_preview = "\n".join(preview_lines)

    return ok_payload({
        "elf_path": result.get("elf_path"),
        "hex_path": result.get("hex_path"),
        "bin_path": result.get("bin_path"),
        "build_log_preview": build_log_preview,
        "build_log_lines": result.get("build_log_lines", 0),
        "artefact_bytes": result.get("artefact_bytes", 0),
        "environment": result.get("environment", board),
        "warnings": warnings,
    })
