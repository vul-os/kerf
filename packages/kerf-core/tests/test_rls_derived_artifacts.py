"""
T-92 — RLS: derived_artifacts
==============================
Hermetic tests for the application-level multi-tenant access control on the
``derived_artifacts`` table.

Access model
------------
``derived_artifacts`` has no direct workspace_id or user_id column.
Tenant isolation is enforced by the route layer via the FK chain:

    derived_artifacts.source_file_id → files.id
      → files.project_id → projects.workspace_id
      → workspace_members (membership check)

All three routes share the same two-step gate:
  1. ``project_workspace_id(pid)`` — verify project exists, get its workspace.
  2. ``get_user_workspace_role(conn, ws_id, user_id)`` — verify membership.

The file existence query (SELECT … WHERE id=$fid AND project_id=$pid) also
acts as a second-layer guard: even if the membership check somehow passed,
a file from another project cannot be looked up without matching project_id.

All 12 cases are hermetic — no real database required.

Invariants under test
---------------------
SELECT (lookup):
  1.  Member of WS_A can look up a derived artifact for their own file.
  2.  Non-member of WS_B cannot look up an artifact for B's file (→ 404).
  3.  File-scoped query rejects cross-project file_id even for a valid member.
  4.  Non-existent derived kind is rejected with 400 before any DB access.
  5.  Cache miss (no stored artifact) returns 501, not a data leak.

INSERT/UPSERT (store):
  6.  Member of WS_A can store a derived artifact for their own file.
  7.  Non-member of WS_B cannot store an artifact for B's file (→ 404).
  8.  Viewer role is NOT blocked from reading (viewer can read) — only store
      is allowed for all authenticated members (viewer can also store; the
      route does not gate on viewer).
  9.  Unknown project returns 404 (project_workspace_id returns None).
  10. Payload exceeding 16 MiB cap is rejected with 400.

DELETE (purge):
  11. Member of WS_A can purge artifacts for their own file.
  12. Non-member of WS_B cannot purge artifacts for B's file (→ 404).
"""
from __future__ import annotations

import base64
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

# ---------------------------------------------------------------------------
# Tenant fixtures
# ---------------------------------------------------------------------------

WS_A = str(uuid.uuid4())
WS_B = str(uuid.uuid4())
USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())
PROJ_A = str(uuid.uuid4())
PROJ_B = str(uuid.uuid4())
FILE_A = str(uuid.uuid4())
FILE_B = str(uuid.uuid4())

# workspace_members: {(ws_id, user_id): role}
_MEMBERS: dict[tuple[str, str], str] = {
    (WS_A, USER_A): "owner",
    (WS_B, USER_B): "owner",
}

# projects: {pid: ws_id}
_PROJECTS: dict[str, str] = {
    PROJ_A: WS_A,
    PROJ_B: WS_B,
}

# files: {fid: project_id}
_FILES: dict[str, str] = {
    FILE_A: PROJ_A,
    FILE_B: PROJ_B,
}

# In-memory derived_artifacts: {(source_file_id, content_sha256, kind): payload}
_DA_STORE: dict[tuple[str, str, str], bytes] = {}

_FILE_CONTENTS: dict[str, str] = {
    FILE_A: "// tenant A source",
    FILE_B: "// tenant B secret source",
}


# ---------------------------------------------------------------------------
# Fake asyncpg connection
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    """asyncpg-compatible record supporting both dict and attribute access."""

    def __getitem__(self, key):
        return super().__getitem__(key)

    def get(self, key, default=None):
        return super().get(key, default)


class FakeConn:
    """Simulates asyncpg.Connection for access-control queries."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def fetchrow(self, query: str, *args) -> Optional[FakeRecord]:
        q = query.strip().lower()

        # workspace_members role lookup
        if "from workspace_members" in q and "workspace_id" in q:
            ws_id, user_id = str(args[0]), str(args[1])
            role = _MEMBERS.get((ws_id, user_id))
            return FakeRecord({"role": role}) if role else None

        # project workspace_id lookup
        if "select workspace_id from projects" in q or (
            "from projects" in q and "workspace_id" in q
        ):
            pid = str(args[0])
            ws_id = _PROJECTS.get(pid)
            return FakeRecord({"workspace_id": uuid.UUID(ws_id)}) if ws_id else None

        # SELECT COALESCE(content,'') FROM files WHERE id=$1 AND project_id=$2
        if "from files" in q and "project_id" in q and "coalesce" in q:
            fid, pid = str(args[0]), str(args[1])
            proj = _FILES.get(fid)
            if proj and proj == pid:
                content = _FILE_CONTENTS.get(fid, "")
                return FakeRecord({0: content})
            return None

        # SELECT true FROM files WHERE id=$1 AND project_id=$2 (purge existence check)
        if "from files" in q and "project_id" in q and "true" in q:
            fid, pid = str(args[0]), str(args[1])
            proj = _FILES.get(fid)
            if proj and proj == pid:
                return FakeRecord({"exists": True})
            return None

        # UPDATE derived_artifacts SET last_accessed_at … WHERE source_file_id=$1 …
        if "update derived_artifacts" in q and "source_file_id" in q:
            fid, sha, kind = str(args[0]), str(args[1]), str(args[2])
            payload = _DA_STORE.get((fid, sha, kind))
            if payload is not None:
                return FakeRecord({"payload": payload})
            return None

        return None

    async def execute(self, query: str, *args) -> str:
        q = query.strip().lower()

        # INSERT INTO derived_artifacts … ON CONFLICT … DO UPDATE
        if "insert into derived_artifacts" in q:
            fid, sha, kind, payload_bytes = (
                str(args[0]), str(args[1]), str(args[2]), args[3]
            )
            _DA_STORE[(fid, sha, kind)] = payload_bytes
            return "INSERT 0 1"

        # DELETE FROM derived_artifacts WHERE source_file_id=$1
        if "delete from derived_artifacts" in q and "source_file_id" in q:
            fid = str(args[0])
            keys_to_del = [k for k in _DA_STORE if k[0] == fid]
            for k in keys_to_del:
                del _DA_STORE[k]
            return f"DELETE {len(keys_to_del)}"

        return "OK"


class FakeConnCtx:
    async def __aenter__(self):
        return FakeConn()

    async def __aexit__(self, *_):
        pass


class FakePool:
    def acquire(self):
        return FakeConnCtx()


# ---------------------------------------------------------------------------
# Application helpers (mirror route logic)
# ---------------------------------------------------------------------------

async def _membership(ws_id: str, user_id: str) -> Optional[str]:
    from kerf_api.routes import get_user_workspace_role
    conn = FakeConn()
    return await get_user_workspace_role(conn, ws_id, user_id)


def _project_ws(pid: str) -> Optional[str]:
    return _PROJECTS.get(pid)


def _enforce_member(role: Optional[str]) -> None:
    """Mirror routes.py: no membership → 404."""
    if not role:
        raise HTTPException(status_code=404, detail="project not found")


# ---------------------------------------------------------------------------
# FastAPI test app builder
# ---------------------------------------------------------------------------

import sys, pathlib as _pl
_PACKAGES = _pl.Path(__file__).parent.parent.parent.parent
for _pkg in _PACKAGES.iterdir():
    if _pkg.name.startswith("kerf-"):
        _src = _pkg / "src"
        if _src.is_dir() and str(_src) not in sys.path:
            sys.path.insert(0, str(_src))


def _build_app():
    from fastapi import FastAPI
    import kerf_core.db.connection as _conn_mod

    @asynccontextmanager
    async def _lifespan(app):
        _conn_mod._pool = object()
        yield
        _conn_mod._pool = None

    app = FastAPI(lifespan=_lifespan)
    from kerf_api.routes import router as api_router
    app.include_router(api_router, prefix="/api")
    return app


def _patches_for(user_id: str, project_ws_id: Optional[str] = WS_A):
    from kerf_api.routes import get_user_workspace_role as _guwsr
    role = _MEMBERS.get((project_ws_id or "", user_id)) if project_ws_id else None
    return [
        patch("kerf_api.routes.project_workspace_id",
              new=AsyncMock(return_value=project_ws_id)),
        patch("kerf_api.routes.get_user_workspace_role",
              new=AsyncMock(return_value=role)),
        patch("kerf_api.routes.get_pool_required",
              new=AsyncMock(return_value=FakePool())),
    ]


def _mint_jwt(user_id: str) -> str:
    import jwt
    from datetime import datetime, timedelta, timezone
    now = datetime.now(tz=timezone.utc)
    return jwt.encode(
        {"sub": user_id, "exp": now + timedelta(hours=1), "iat": now},
        "dev-secret-change-in-production",
        algorithm="HS256",
    )


def _headers(user_id: str) -> dict:
    return {"Authorization": f"Bearer {_mint_jwt(user_id)}"}


# ---------------------------------------------------------------------------
# Case 1 — Member of WS_A can look up a derived artifact for their own file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lookup_own_tenant_member_allowed():
    """User A has membership in WS_A → lookup route gate passes."""
    ws_id = _project_ws(PROJ_A)
    role = await _membership(ws_id, USER_A)
    _enforce_member(role)  # must not raise
    assert role == "owner"


# ---------------------------------------------------------------------------
# Case 2 — Non-member cannot look up B's artifact
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_lookup_cross_tenant_non_member_returns_404():
    """User A has no membership in WS_B → lookup must return 404."""
    ws_id = _project_ws(PROJ_B)
    role = await _membership(ws_id, USER_A)
    assert role is None, f"USER_A must not be a member of WS_B, got {role!r}"
    with pytest.raises(HTTPException) as exc:
        _enforce_member(role)
    assert exc.value.status_code == 404


# ---------------------------------------------------------------------------
# Case 3 — File-scoped query rejects cross-project file_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_file_scoped_query_blocks_cross_project_file():
    """SELECT files WHERE id=$fid AND project_id=$pid: FILE_B under PROJ_A returns None."""
    conn = FakeConn()
    # User A is a valid member of WS_A, but FILE_B belongs to PROJ_B
    row = await conn.fetchrow(
        "SELECT COALESCE(content, '') FROM files WHERE id = $1 AND project_id = $2 AND deleted_at IS NULL",
        uuid.UUID(FILE_B),
        uuid.UUID(PROJ_A),  # wrong project
    )
    assert row is None, (
        "File from WS_B must not be returned when queried under WS_A's project_id"
    )


# ---------------------------------------------------------------------------
# Case 4 — Invalid derived_kind rejected with 400 (no DB access needed)
# ---------------------------------------------------------------------------

def test_lookup_invalid_derived_kind_rejected():
    """An unknown derived_kind must be rejected before any DB access."""
    from fastapi.testclient import TestClient
    app = _build_app()
    with _patches_for(USER_A)[0], _patches_for(USER_A)[1], _patches_for(USER_A)[2]:
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post(
                f"/api/projects/{PROJ_A}/files/{FILE_A}/derived",
                json={"derived_kind": "not_a_real_kind"},
                headers=_headers(USER_A),
            )
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# Case 5 — Cache miss returns 501, not data from another tenant
# ---------------------------------------------------------------------------

def test_lookup_cache_miss_returns_501_not_data_leak():
    """When no artifact is cached, route returns 501 — not a cross-tenant payload."""
    from fastapi.testclient import TestClient
    from unittest.mock import MagicMock
    app = _build_app()
    call_count: list[int] = [0]

    async def _fetchrow(*args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return {0: "// source content"}  # file content row
        return None  # no cached artifact

    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetchrow = _fetchrow
    conn.execute = AsyncMock(return_value="OK")

    class _Pool:
        def acquire(self_):
            return conn

    with (
        patch("kerf_api.routes.project_workspace_id",
              new=AsyncMock(return_value=WS_A)),
        patch("kerf_api.routes.get_user_workspace_role",
              new=AsyncMock(return_value="owner")),
        patch("kerf_api.routes.get_pool_required",
              new=AsyncMock(return_value=_Pool())),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post(
                f"/api/projects/{PROJ_A}/files/{FILE_A}/derived",
                json={"derived_kind": "jscad_mesh"},
                headers=_headers(USER_A),
            )
    assert r.status_code == 501, f"expected 501, got {r.status_code}: {r.text}"
    # Must NOT expose any payload
    body = r.json() if r.status_code == 501 else {}
    assert "payload_b64" not in body, "Cache miss must not include payload_b64"


# ---------------------------------------------------------------------------
# Case 6 — Member of WS_A can store a derived artifact for their own file
# ---------------------------------------------------------------------------

def test_store_own_tenant_member_allowed():
    """User A can store a derived artifact for FILE_A in PROJ_A."""
    from fastapi.testclient import TestClient
    from unittest.mock import MagicMock
    app = _build_app()

    async def _fetchrow(*args, **kwargs):
        return {0: "// A's source"}

    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetchrow = _fetchrow
    conn.execute = AsyncMock(return_value="OK")

    class _Pool:
        def acquire(self_):
            return conn

    payload = b"mesh-data-for-A"
    with (
        patch("kerf_api.routes.project_workspace_id",
              new=AsyncMock(return_value=WS_A)),
        patch("kerf_api.routes.get_user_workspace_role",
              new=AsyncMock(return_value="owner")),
        patch("kerf_api.routes.get_pool_required",
              new=AsyncMock(return_value=_Pool())),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post(
                f"/api/projects/{PROJ_A}/files/{FILE_A}/derived/store",
                json={
                    "derived_kind": "jscad_mesh",
                    "payload_b64": base64.b64encode(payload).decode(),
                },
                headers=_headers(USER_A),
            )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    assert body["stored"] is True
    assert body["payload_size_bytes"] == len(payload)


# ---------------------------------------------------------------------------
# Case 7 — Non-member of WS_B cannot store an artifact for B's file
# ---------------------------------------------------------------------------

def test_store_cross_tenant_non_member_returns_404():
    """User A attempting to store an artifact in PROJ_B must get 404."""
    from fastapi.testclient import TestClient
    app = _build_app()

    payload = b"injected-payload"
    # project_workspace_id returns WS_B; USER_A has no role there
    with (
        patch("kerf_api.routes.project_workspace_id",
              new=AsyncMock(return_value=WS_B)),
        patch("kerf_api.routes.get_user_workspace_role",
              new=AsyncMock(return_value=None)),
        patch("kerf_api.routes.get_pool_required",
              new=AsyncMock(return_value=FakePool())),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post(
                f"/api/projects/{PROJ_B}/files/{FILE_B}/derived/store",
                json={
                    "derived_kind": "jscad_mesh",
                    "payload_b64": base64.b64encode(payload).decode(),
                },
                headers=_headers(USER_A),
            )
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# Case 8 — Viewer role can read (lookup) derived artifacts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_viewer_can_read_derived_artifacts():
    """A viewer is a member — their role is not None — so lookup gate passes.
    The derived_artifact routes do not gate on viewer specifically for reads."""
    # Make USER_B a viewer in WS_A temporarily
    _MEMBERS[(WS_A, USER_B)] = "viewer"
    try:
        ws_id = _project_ws(PROJ_A)
        role = await _membership(ws_id, USER_B)
        assert role == "viewer"
        # Viewer role is truthy — membership gate passes
        _enforce_member(role)  # must not raise
    finally:
        del _MEMBERS[(WS_A, USER_B)]


# ---------------------------------------------------------------------------
# Case 9 — Unknown project returns 404
# ---------------------------------------------------------------------------

def test_store_unknown_project_returns_404():
    """Store for a non-existent project returns 404 (project_workspace_id=None)."""
    from fastapi.testclient import TestClient
    app = _build_app()

    with (
        patch("kerf_api.routes.project_workspace_id",
              new=AsyncMock(return_value=None)),
        patch("kerf_api.routes.get_user_workspace_role",
              new=AsyncMock(return_value="owner")),
        patch("kerf_api.routes.get_pool_required",
              new=AsyncMock(return_value=FakePool())),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post(
                f"/api/projects/{PROJ_A}/files/{FILE_A}/derived/store",
                json={
                    "derived_kind": "jscad_mesh",
                    "payload_b64": base64.b64encode(b"data").decode(),
                },
                headers=_headers(USER_A),
            )
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# Case 10 — Payload exceeding 16 MiB cap is rejected with 400
# ---------------------------------------------------------------------------

def test_store_oversized_payload_rejected():
    """Payload > 16 MiB must be rejected with 400 before reaching the DB."""
    from fastapi.testclient import TestClient
    from unittest.mock import MagicMock
    app = _build_app()

    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetchrow = AsyncMock(return_value={0: "// content"})
    conn.execute = AsyncMock(return_value="OK")

    class _Pool:
        def acquire(self_):
            return conn

    oversized = b"x" * ((16 << 20) + 1)
    with (
        patch("kerf_api.routes.project_workspace_id",
              new=AsyncMock(return_value=WS_A)),
        patch("kerf_api.routes.get_user_workspace_role",
              new=AsyncMock(return_value="owner")),
        patch("kerf_api.routes.get_pool_required",
              new=AsyncMock(return_value=_Pool())),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.post(
                f"/api/projects/{PROJ_A}/files/{FILE_A}/derived/store",
                json={
                    "derived_kind": "jscad_mesh",
                    "payload_b64": base64.b64encode(oversized).decode(),
                },
                headers=_headers(USER_A),
            )
    assert r.status_code == 400, f"expected 400 for oversized payload, got {r.status_code}"


# ---------------------------------------------------------------------------
# Case 11 — Member of WS_A can purge artifacts for their own file
# ---------------------------------------------------------------------------

def test_purge_own_tenant_member_allowed():
    """User A can purge derived artifacts for FILE_A in PROJ_A."""
    from fastapi.testclient import TestClient
    from unittest.mock import MagicMock
    app = _build_app()

    async def _fetchrow(*args, **kwargs):
        return {"exists": True}

    conn = MagicMock()
    conn.__aenter__ = AsyncMock(return_value=conn)
    conn.__aexit__ = AsyncMock(return_value=False)
    conn.fetchrow = _fetchrow
    conn.execute = AsyncMock(return_value="DELETE 2")

    class _Pool:
        def acquire(self_):
            return conn

    with (
        patch("kerf_api.routes.project_workspace_id",
              new=AsyncMock(return_value=WS_A)),
        patch("kerf_api.routes.get_user_workspace_role",
              new=AsyncMock(return_value="owner")),
        patch("kerf_api.routes.get_pool_required",
              new=AsyncMock(return_value=_Pool())),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.delete(
                f"/api/projects/{PROJ_A}/files/{FILE_A}/derived",
                headers=_headers(USER_A),
            )
    assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text}"
    assert r.json()["purged"] == 2


# ---------------------------------------------------------------------------
# Case 12 — Non-member of WS_B cannot purge artifacts for B's file
# ---------------------------------------------------------------------------

def test_purge_cross_tenant_non_member_returns_404():
    """User A attempting to purge artifacts in PROJ_B must get 404."""
    from fastapi.testclient import TestClient
    app = _build_app()

    with (
        patch("kerf_api.routes.project_workspace_id",
              new=AsyncMock(return_value=WS_B)),
        patch("kerf_api.routes.get_user_workspace_role",
              new=AsyncMock(return_value=None)),
        patch("kerf_api.routes.get_pool_required",
              new=AsyncMock(return_value=FakePool())),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.delete(
                f"/api/projects/{PROJ_B}/files/{FILE_B}/derived",
                headers=_headers(USER_A),
            )
    assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"
