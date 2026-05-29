"""routes_model3d.py — /api/projects/{pid}/model3d endpoint.

Serves a STEP/WRL blob for a Library Part's model_3d_paths entry so the
3D viewport can substitute real component geometry.

Endpoint:
  GET /api/projects/{pid}/model3d?file_id=<uuid>&path=<relative-path>

The ``file_id`` is the Library Part's file_id (``kind='part'``).  The
``path`` is the relative path from ``model_3d_paths`` (e.g.
``Packages3D/R_THT.3dshapes/R_Axial_DIN0207.step``).

Resolution order:
  1. Look up the file row for ``file_id`` in project ``pid``.
  2. Parse its ``content`` JSON → ``model_3d_paths`` list.
  3. Verify ``path`` is in the list (prevents path-traversal by restricting
     to explicitly declared paths).
  4. Try to find the blob via project storage: ``GET /api/projects/:pid/blobs/:oid``
     where the OID is the SHA-256 of the path relative to the library project.
  5. If not found in storage, return 404 with a JSON body so the caller can
     fall through to the teal-box indicator.

Security: the path is validated against the part's declared ``model_3d_paths``
list before any file lookup — a client cannot traverse outside the declared
model paths.
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter()


def _try_get_auth_dep():
    """Return the project-auth dependency or None when kerf-auth is absent."""
    try:
        from kerf_auth.dependencies import require_project_member  # type: ignore
        return require_project_member
    except ImportError:
        return None


@router.get("/projects/{pid}/model3d")
async def get_model3d_blob(
    pid: UUID,
    file_id: str = Query(..., description="Library Part file-id (UUID)"),
    path: str = Query(..., description="Relative model path from model_3d_paths"),
):
    """Serve a STEP/WRL blob for a Library Part's 3D model path.

    Returns the raw bytes (``Content-Type: application/octet-stream``) for
    consumption by ``occt-import-js``.  Returns 404 when the blob is not yet
    seeded into project storage.
    """
    # Sanitize path — reject anything with upward traversal.
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=400, detail="invalid model path")

    # Restrict to declared STEP/STP/WRL extensions.
    lower = path.lower()
    if not (lower.endswith(".step") or lower.endswith(".stp") or lower.endswith(".wrl")):
        raise HTTPException(status_code=400, detail="unsupported model extension")

    # Resolve DB + storage — these are optional at the routes layer; we
    # degrade to 503 when the runtime context isn't wired (unit tests).
    try:
        from kerf_core.db.connection import get_pool  # type: ignore
        from kerf_core.storage import get_storage  # type: ignore
    except ImportError:
        raise HTTPException(status_code=503, detail="storage not available")

    pool = await get_pool()
    storage = await get_storage()

    # 1. Fetch the part file row.
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT content FROM files WHERE id = $1 AND project_id = $2",
            str(file_id), str(pid),
        )
    if row is None:
        raise HTTPException(status_code=404, detail="part file not found")

    # 2. Parse and validate path against declared model_3d_paths.
    try:
        doc = json.loads(row["content"] or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=422, detail="part content not valid JSON")

    declared_paths = doc.get("model_3d_paths") or []
    if not isinstance(declared_paths, list) or path not in declared_paths:
        raise HTTPException(
            status_code=403,
            detail="path not in part's declared model_3d_paths",
        )

    # 3. Attempt to serve from project storage using a deterministic blob key.
    # The blob key mirrors how the seed pipeline would store model files:
    # ``model3d/<project_id>/<file_id>/<sha256_of_path>.step``
    import hashlib
    path_hash = hashlib.sha256(path.encode()).hexdigest()
    ext = path.rsplit(".", 1)[-1].lower()
    blob_key = f"model3d/{pid}/{file_id}/{path_hash}.{ext}"

    try:
        blob_bytes = await storage.get(blob_key)
    except Exception:
        blob_bytes = None

    if not blob_bytes:
        raise HTTPException(
            status_code=404,
            detail={
                "reason": "model blob not yet seeded",
                "blob_key": blob_key,
                "hint": "Run `kerf-seed-parts` to populate model blobs.",
            },
        )

    # Return raw bytes — occt-import-js reads them directly.
    mime = "model/step" if ext in ("step", "stp") else "model/vrml"
    return Response(
        content=blob_bytes,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=86400"},
    )
