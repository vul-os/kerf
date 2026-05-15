"""
import_ifc.py — LLM tool: import_ifc.

Mirrors the shape of import_freecad_project (kerf-imports):
  1. Fetch the .ifc blob from storage.
  2. POST multipart to pyworker POST /import-ifc.
  3. Walk the response: create a .bim file in PG.
  4. Return { created_file, stats, warnings, import_folder }.

Spec parameters:
    project_id      UUID of the target Kerf project.
    file_blob_id    Blob ID or storage key for the uploaded .ifc file.
    mode            "project" | "library"  (default: "project")
    import_folder   Path inside project tree.  (default: /ifc_import)
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any

from kerf_core.utils.context import ProjectCtx
from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register

# ---------------------------------------------------------------------------
# Spec
# ---------------------------------------------------------------------------

import_ifc_spec = ToolSpec(
    name="import_ifc",
    description=(
        "Import an IFC (.ifc) file into a Kerf project as a .bim architecture file. "
        "Tier 1 support: walls, slabs, spaces, levels, and site metadata. "
        "Tier 2 (families, schedules, views, curtain walls) is not yet supported. "
        "Requires IfcOpenShell on the pyworker sidecar. "
        "Returns the created .bim file id, import stats, and any translation warnings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "UUID of the target Kerf project.",
            },
            "file_blob_id": {
                "type": "string",
                "description": "Blob ID or storage key for the uploaded .ifc file.",
            },
            "import_folder": {
                "type": "string",
                "description": (
                    "Path inside the project tree where the imported .bim file "
                    "will be placed. Defaults to /ifc_import."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["project", "library"],
                "description": (
                    "Import mode: 'project' (default) creates the .bim file inside "
                    "the project, 'library' imports as a Library entry."
                ),
            },
        },
        "required": ["project_id", "file_blob_id"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register(import_ifc_spec, write=True)
async def import_ifc(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    project_id    = a.get("project_id", "").strip()
    blob_ref      = a.get("file_blob_id", "").strip()
    import_folder = (a.get("import_folder", "") or "").strip() or "/ifc_import"
    mode          = (a.get("mode", "") or "").strip() or "project"

    if not project_id:
        return err_payload("project_id is required", "BAD_ARGS")
    if not blob_ref:
        return err_payload("file_blob_id is required", "BAD_ARGS")
    if mode not in ("project", "library"):
        return err_payload("mode must be 'project' or 'library'", "BAD_ARGS")

    # ── Resolve blob → bytes ─────────────────────────────────────────────────
    if ctx.storage is None:
        return err_payload("storage backend not configured", "NO_STORAGE")

    try:
        blob_bytes = await ctx.storage.get(blob_ref)
    except Exception as exc:
        return err_payload(f"failed to fetch blob {blob_ref!r}: {exc}", "STORAGE_ERROR")

    if not blob_bytes:
        return err_payload(f"blob not found: {blob_ref}", "NOT_FOUND")

    # ── POST to pyworker /import-ifc ─────────────────────────────────────────
    import httpx

    pyworker_url = os.getenv("PYWORKER_URL", "http://localhost:8090")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            resp = await client.post(
                f"{pyworker_url}/import-ifc",
                files={
                    "file": (
                        "upload.ifc",
                        blob_bytes,
                        "application/octet-stream",
                    )
                },
            )
        if resp.status_code == 503:
            detail = resp.json().get("detail", resp.text[:400])
            return err_payload(
                f"IFC import unavailable: {detail}", "IFC_UNAVAILABLE"
            )
        if resp.status_code == 400:
            detail = resp.json().get("detail", resp.text[:400])
            return err_payload(
                f"IFC parse error: {detail}", "IFC_PARSE_ERROR"
            )
        if resp.status_code != 200:
            return err_payload(
                f"pyworker error {resp.status_code}: {resp.text[:400]}", "PYWORKER_ERROR"
            )
        data = resp.json()
    except Exception as exc:
        return err_payload(f"failed to reach pyworker: {exc}", "PYWORKER_UNREACHABLE")

    bim_payload: dict   = data.get("bim_payload") or {}
    stats: dict         = data.get("stats") or {}
    pyworker_warnings: list[str] = data.get("warnings") or []

    warnings: list[str] = list(pyworker_warnings)

    # ── Ensure import folder exists ──────────────────────────────────────────
    folder_path = import_folder.rstrip("/")
    if not folder_path.startswith("/"):
        folder_path = "/" + folder_path

    folder_id = await _ensure_folder(ctx, folder_path)

    # ── Derive .bim filename from project name ────────────────────────────────
    project_name = bim_payload.get("name", "") or "import"
    # Sanitise: keep alphanumeric, dashes, underscores; replace spaces with _
    safe_name = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in project_name
    ).strip("_") or "import"
    bim_filename = f"{safe_name}.bim"
    content_str = json.dumps(bim_payload, indent=2)

    # ── Insert .bim file into PG ─────────────────────────────────────────────
    try:
        new_id = await ctx.pool.fetchval(
            """INSERT INTO files(id, project_id, parent_id, name, kind, content)
               VALUES ($1, $2, $3, $4, 'bim', $5)
               RETURNING id""",
            uuid.uuid4(),
            ctx.project_id,
            folder_id,
            bim_filename,
            content_str,
        )
        created_file: dict[str, Any] = {
            "file_id": str(new_id),
            "name": bim_filename,
            "kind": "bim",
        }
    except Exception as exc:
        warnings.append(f"failed to insert .bim file: {exc}")
        created_file = {
            "file_id": None,
            "name": bim_filename,
            "kind": "bim",
            "error": str(exc),
        }

    return ok_payload({
        "created_file": created_file,
        "stats": stats,
        "warnings": warnings,
        "import_folder": folder_path,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_folder(ctx: ProjectCtx, folder_path: str) -> Any:
    """Create folder hierarchy and return the leaf folder id."""
    parts = [p for p in folder_path.strip("/").split("/") if p]
    if not parts:
        return None

    parent_id = None
    for part in parts:
        existing = await ctx.pool.fetchrow(
            """SELECT id FROM files
               WHERE project_id = $1 AND name = $2
                 AND parent_id IS NOT DISTINCT FROM $3
                 AND kind = 'folder'
                 AND deleted_at IS NULL""",
            ctx.project_id, part, parent_id,
        )
        if existing:
            parent_id = existing["id"]
        else:
            new_id = await ctx.pool.fetchval(
                """INSERT INTO files(id, project_id, parent_id, name, kind, content)
                   VALUES ($1, $2, $3, $4, 'folder', '{}')
                   RETURNING id""",
                uuid.uuid4(), ctx.project_id, parent_id, part,
            )
            parent_id = new_id

    return parent_id


# ---------------------------------------------------------------------------
# TOOLS registration list (plugin.py pattern)
# ---------------------------------------------------------------------------

TOOLS = [
    (
        "import_ifc",
        import_ifc_spec,
        import_ifc,
    ),
]
