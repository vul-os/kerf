"""
import_dxf.py — LLM tool: import_dxf.

Reads an uploaded DXF file (R12 or R2000+ ASCII) and creates:
  - One ``.sketch`` file containing all geometry entities (LINE, LWPOLYLINE,
    POLYLINE, CIRCLE, ARC) mapped to Kerf's Geom2 format.
  - One ``.drawing`` file containing all annotation entities (TEXT, MTEXT,
    entities on annotation layers) mapped to Kerf's drawing sheet format.

Both files are created inside a folder (``import_folder``) in the target
project.  If a file would be empty (no entities / no annotations) it is
omitted from the output.

The tool is pure-Python and requires no external dependencies.  It calls
the pyworker ``/import-dxf`` endpoint for the actual file parsing; if
pyworker is unreachable the tool returns a ``PYWORKER_UNREACHABLE`` error.

Returns::

    {
      "created_files": [
        {"file_id": "...", "name": "import.sketch", "kind": "sketch"},
        {"file_id": "...", "name": "import.drawing", "kind": "drawing"}
      ],
      "stats": {
        "entities": N,
        "annotations": N,
        "blocks": N,
        "warnings": N,
        "loops": N
      },
      "warnings": [...],
      "import_folder": "/dxf_import"
    }
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

import_dxf_spec = ToolSpec(
    name="import_dxf",
    description=(
        "Import a DXF (R12 or R2000+) file into a Kerf project.  "
        "Creates a .sketch file for geometry (lines, arcs, circles, "
        "polylines) and a .drawing file for text annotations. "
        "Supports LINE, LWPOLYLINE, POLYLINE, CIRCLE, ARC, TEXT, MTEXT, "
        "and INSERT (block references).  "
        "Returns the list of created files and any translation warnings."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {
                "type": "string",
                "description": "UUID of the target Kerf project.",
            },
            "file_blob_id_or_storage_key": {
                "type": "string",
                "description": "Blob ID or storage key for the uploaded .dxf file.",
            },
            "import_folder": {
                "type": "string",
                "description": (
                    "Folder path inside the project tree for imported files. "
                    "Defaults to /dxf_import."
                ),
            },
            "expand_inserts": {
                "type": "boolean",
                "description": (
                    "When true (default) INSERT block references are expanded "
                    "inline.  When false they are emitted as insert placeholder "
                    "entities."
                ),
            },
        },
        "required": ["project_id", "file_blob_id_or_storage_key"],
    },
)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------

@register(import_dxf_spec, write=True)
async def import_dxf(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args: {exc}", "BAD_ARGS")

    project_id = a.get("project_id", "").strip()
    blob_ref   = a.get("file_blob_id_or_storage_key", "").strip()
    import_folder = (a.get("import_folder") or "/dxf_import").strip() or "/dxf_import"
    expand_inserts = bool(a.get("expand_inserts", True))

    if not project_id:
        return err_payload("project_id is required", "BAD_ARGS")
    if not blob_ref:
        return err_payload("file_blob_id_or_storage_key is required", "BAD_ARGS")

    # ── Resolve blob → bytes ─────────────────────────────────────────────────
    if ctx.storage is None:
        return err_payload("storage backend not configured", "NO_STORAGE")

    try:
        blob_bytes = await ctx.storage.get(blob_ref)
    except Exception as exc:
        return err_payload(f"failed to fetch blob {blob_ref!r}: {exc}", "STORAGE_ERROR")

    if not blob_bytes:
        return err_payload(f"blob not found: {blob_ref}", "NOT_FOUND")

    # ── Call pyworker /import-dxf ────────────────────────────────────────────
    import httpx

    pyworker_url = os.getenv("PYWORKER_URL", "http://localhost:8090")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            resp = await client.post(
                f"{pyworker_url}/import-dxf",
                files={
                    "file": (
                        "upload.dxf",
                        blob_bytes,
                        "application/octet-stream",
                    )
                },
                params={
                    "import_folder": import_folder,
                    "expand_inserts": "1" if expand_inserts else "0",
                },
            )
        if resp.status_code == 422:
            detail = resp.json().get("detail", resp.text[:400])
            return err_payload(f"DXF format error: {detail}", "DXF_FORMAT_ERROR")
        if resp.status_code != 200:
            return err_payload(
                f"pyworker error {resp.status_code}: {resp.text[:400]}", "PYWORKER_ERROR"
            )
        data = resp.json()
    except Exception as exc:
        return err_payload(f"failed to reach pyworker: {exc}", "PYWORKER_UNREACHABLE")

    pyworker_warnings: list[str] = data.get("warnings") or []
    files: list[dict] = data.get("created_files") or []
    stats: dict = data.get("stats") or {}

    # ── Ensure import folder exists ─────────────────────────────────────────
    folder_path = import_folder.rstrip("/")
    if not folder_path.startswith("/"):
        folder_path = "/" + folder_path

    folder_id = await _ensure_folder(ctx, folder_path)

    _kind_to_db = {
        "sketch": "sketch",
        "drawing": "drawing",
        "file": "file",
    }

    created_files: list[dict[str, Any]] = []
    warnings: list[str] = list(pyworker_warnings)

    for f in files:
        name     = f.get("name", "unnamed")
        kerf_kind = f.get("kind", "file")
        payload  = f.get("payload", {})
        db_kind  = _kind_to_db.get(kerf_kind, "file")
        content_str = json.dumps(payload) if isinstance(payload, dict) else str(payload)

        try:
            new_id = await ctx.pool.fetchval(
                """INSERT INTO files(id, project_id, parent_id, name, kind, content)
                   VALUES ($1, $2, $3, $4, $5, $6)
                   RETURNING id""",
                uuid.uuid4(),
                ctx.project_id,
                folder_id,
                name,
                db_kind,
                content_str,
            )
            created_files.append({
                "file_id": str(new_id),
                "name": name,
                "kind": db_kind,
            })
        except Exception as exc:
            warnings.append(f"failed to insert {name!r}: {exc}")
            created_files.append({
                "file_id": None,
                "name": name,
                "kind": db_kind,
                "error": str(exc),
            })

    return ok_payload({
        "created_files": created_files,
        "stats": stats,
        "warnings": warnings,
        "import_folder": folder_path,
    })


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ensure_folder(ctx: ProjectCtx, folder_path: str) -> Any:
    """Create the folder hierarchy and return the leaf folder id."""
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
# TOOLS registration list
# ---------------------------------------------------------------------------

TOOLS = [
    (
        "import_dxf",
        import_dxf_spec,
        import_dxf,
    ),
]
