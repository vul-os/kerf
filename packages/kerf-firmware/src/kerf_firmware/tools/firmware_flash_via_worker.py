"""
firmware_flash_via_worker — LLM tool that dispatches a firmware flash job
to a registered BYO worker.

When no local CLI is present the cloud relay path submits a
``firmware_flash_jobs`` row. Kerf has no billing anywhere, so no credits
are ever consumed — the job always runs on the caller's own hardware.
Any enrolled BYO worker that advertises
``capabilities.firmware_flash=true`` will pick it up, download the artifact,
run the appropriate flash tool (esptool/avrdude/openocd), and upload the log.

Schema accepted by the LLM tool
---------------------------------
{
    "project_id":           str   — UUID of the firmware project
    "firmware_artifact_key":str   — storage key of the compiled binary (R2/S3)
    "board_target":         str   — board family: "esp32" | "avr_uno" | "stm32f4" | …
}

Response
---------
{
    "ok":     true,
    "job_id": "<uuid>",
    "status": "queued",
    "billing_bucket": "byo"
}
or
{
    "ok":    false,
    "error": "<code>",
    "message": "<human-readable>"
}
"""
from __future__ import annotations

import json
import uuid


# ── ToolSpec compat ────────────────────────────────────────────────────────────

try:
    from kerf_chat.tools.registry import ToolSpec  # type: ignore
except ImportError:
    from kerf_firmware._compat import ToolSpec  # type: ignore


firmware_flash_via_worker_spec = ToolSpec(
    name="firmware_flash_via_worker",
    description=(
        "Dispatch a firmware flash job to a BYO (bring-your-own) worker machine "
        "that has the target board attached via USB. "
        "The worker downloads the compiled binary from cloud storage, runs the "
        "appropriate flash tool (esptool for ESP32/ESP8266, avrdude for AVR, "
        "openocd for STM32/ARM Cortex-M), and uploads the flash log. "
        "No credits are consumed — the job runs on the user's own hardware. "
        "Returns {job_id, status:'queued'} immediately; poll "
        "GET /api/firmware/flash-job/{job_id} for progress."
    ),
    input_schema={
        "type": "object",
        "required": ["project_id", "firmware_artifact_key", "board_target"],
        "properties": {
            "project_id": {
                "type": "string",
                "description": "UUID of the firmware project.",
            },
            "firmware_artifact_key": {
                "type": "string",
                "description": (
                    "Storage key (R2/S3) of the compiled firmware binary "
                    "(e.g. 'projects/<pid>/firmware/firmware.bin')."
                ),
            },
            "board_target": {
                "type": "string",
                "description": (
                    "Board family string used to select the flash tool. "
                    "One of: 'esp32', 'esp8266', 'avr_uno', 'avr_mega', "
                    "'stm32f4', 'stm32f1', 'rp2040'. "
                    "Unknown values default to avrdude."
                ),
            },
        },
    },
)


# ── Flash tool selection ───────────────────────────────────────────────────────

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
    """Return the flash tool name for a given board target."""
    bt = board_target.lower().strip()
    # Exact match first.
    if bt in _BOARD_TO_TOOL:
        return _BOARD_TO_TOOL[bt]
    # Prefix match.
    for prefix, tool in _BOARD_TO_TOOL.items():
        if bt.startswith(prefix):
            return tool
    return "avrdude"  # safe default


# ── DB helper (async) ─────────────────────────────────────────────────────────

async def _submit_flash_job(
    pool,
    *,
    project_id: str,
    user_id: str | None,
    artifact_key: str,
    board_target: str,
) -> str:
    """Insert a firmware_flash_jobs row and return the job UUID."""
    job_id = str(uuid.uuid4())
    uid = uuid.UUID(user_id) if user_id else None
    pid = uuid.UUID(project_id)

    await pool.execute(
        """
        INSERT INTO firmware_flash_jobs
            (id, project_id, user_id, artifact_key, board_target,
             kind, status, created_at, updated_at)
        VALUES
            ($1, $2, $3, $4, $5,
             'firmware_flash', 'queued', now(), now())
        """,
        job_id,
        pid,
        uid,
        artifact_key,
        board_target,
    )
    return job_id


# ── LLM tool handler ──────────────────────────────────────────────────────────

async def run_firmware_flash_via_worker(ctx, args: bytes) -> str:
    """Async LLM tool handler.  ``ctx`` is the PluginContext (may be None in tests)."""
    try:
        a = json.loads(args)
    except Exception as exc:
        return json.dumps({"ok": False, "error": "BAD_ARGS",
                           "message": f"invalid JSON args: {exc}"})

    project_id = (a.get("project_id") or "").strip()
    artifact_key = (a.get("firmware_artifact_key") or "").strip()
    board_target = (a.get("board_target") or "").strip()

    if not project_id:
        return json.dumps({"ok": False, "error": "BAD_ARGS",
                           "message": "'project_id' is required"})
    if not artifact_key:
        return json.dumps({"ok": False, "error": "BAD_ARGS",
                           "message": "'firmware_artifact_key' is required"})
    if not board_target:
        return json.dumps({"ok": False, "error": "BAD_ARGS",
                           "message": "'board_target' is required"})

    # Validate UUID format.
    try:
        uuid.UUID(project_id)
    except ValueError:
        return json.dumps({"ok": False, "error": "BAD_ARGS",
                           "message": f"'project_id' is not a valid UUID: {project_id}"})

    flash_tool = _flash_tool_for(board_target)

    # Obtain pool from ctx (real) or fall back to lazy import for standalone use.
    pool = None
    user_id: str | None = None
    if ctx is not None:
        pool = getattr(ctx, "pool", None)
        user_id = getattr(ctx, "user_id", None)

    if pool is None:
        # No pool wired — return a stub response so callers can integrate.
        stub_job_id = str(uuid.uuid4())
        return json.dumps({
            "ok": True,
            "job_id": stub_job_id,
            "status": "queued",
            "billing_bucket": "byo",
            "flash_tool": flash_tool,
            "_note": "No DB pool wired; job not persisted.",
        })

    try:
        job_id = await _submit_flash_job(
            pool,
            project_id=project_id,
            user_id=user_id,
            artifact_key=artifact_key,
            board_target=board_target,
        )
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"ok": False, "error": "DB_ERROR",
                           "message": f"Failed to submit flash job: {exc}"})

    return json.dumps({
        "ok": True,
        "job_id": job_id,
        "status": "queued",
        "billing_bucket": "byo",
        "flash_tool": flash_tool,
    })
