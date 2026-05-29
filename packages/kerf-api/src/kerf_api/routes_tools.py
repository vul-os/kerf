"""POST /api/tools/call — dispatch an LLM tool from the frontend.

Tools registered in `app.state.tools` (the `ToolRegistry`) are exposed to the
LLM chat flow; this endpoint lets the SPA invoke the same tools directly
(e.g. LadderEditor Import/Export → import_plcopen_xml / export_plcopen_xml).

Request:
    POST /api/tools/call
    { "tool": "<name>", "args": {...}, "project_id": "<uuid?>" }

Tools whose handlers don't need a project (pure parsers / serialisers like
PLCopen IO) work with project_id omitted — a stateless ProjectCtx is built
with a NIL UUID. Tools that DO need a project (anything that reads/writes
files, runs CAM, etc.) must receive a project_id; the user's workspace role
on the owning workspace is enforced before dispatch.

Response: the raw JSON the tool returned (parsed). On error: 4xx/5xx with
`{ "error": "<message>", "code": "<code>" }`.
"""
import json
import uuid

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from kerf_core.config import Settings
from kerf_core.db.connection import get_pool_required
from kerf_core.dependencies import require_auth
from kerf_core.storage import get_storage_required
from kerf_core.utils.context import ProjectCtx

router = APIRouter()

_NIL_UUID = uuid.UUID("00000000-0000-0000-0000-000000000000")


class ToolCallRequest(BaseModel):
    tool: str
    args: dict = {}
    project_id: str | None = None


async def _resolve_project_role(
    conn: asyncpg.Connection, pid: str, user_id: str
) -> tuple[uuid.UUID, str]:
    proj = await conn.fetchrow(
        "SELECT workspace_id FROM projects WHERE id = $1", uuid.UUID(pid)
    )
    if not proj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="project not found")

    # Same role-lookup the chat flow uses.
    from kerf_api.routes import get_user_workspace_role

    role = await get_user_workspace_role(conn, str(proj["workspace_id"]), user_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    return uuid.UUID(pid), role


@router.post("/tools/call")
async def call_tool(
    req: ToolCallRequest,
    request: Request,
    payload: dict = Depends(require_auth),
):
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unauthorized")

    registry = getattr(request.app.state, "tools", None)
    if registry is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="tool registry not ready")

    entry = registry.get(req.tool)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"unknown tool: {req.tool}")
    _spec, handler = entry

    pool = await get_pool_required()
    settings = Settings.load()

    if req.project_id:
        async with pool.acquire() as conn:
            project_uuid, role = await _resolve_project_role(conn, req.project_id, user_id)
    else:
        # Stateless dispatch — for tools that don't touch a project. Tools
        # that DO need one will get NIL UUID and surface their own error.
        project_uuid = _NIL_UUID
        role = "owner"

    # The chat flow builds a fresh httpx.AsyncClient per request; mirror that.
    async with httpx.AsyncClient(timeout=30.0) as http_client:
        ctx = ProjectCtx(
            pool=pool,
            storage=get_storage_required(),
            project_id=project_uuid,
            user_id=uuid.UUID(user_id),
            role=role,
            http_client=http_client,
            file_revisions_max=settings.file_revisions_max,
        )
        args_bytes = json.dumps(req.args).encode("utf-8")
        try:
            result_str = await handler(ctx, args_bytes)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"tool '{req.tool}' raised: {exc}",
            )

    try:
        return json.loads(result_str)
    except (json.JSONDecodeError, TypeError):
        # Tool returned a plain string — wrap it so the SPA gets JSON.
        return {"result": result_str}
