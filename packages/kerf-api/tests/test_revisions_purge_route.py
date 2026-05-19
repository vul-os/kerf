"""
Hermetic tests for DELETE /api/projects/{pid}/revisions.

Strategy: monkey-patch the module-level helpers (get_pool_required,
project_workspace_id, get_user_workspace_role) and the purge helper so
no real DB or JWT is needed.

Covers:
  - 400 without confirm=PURGE
  - 400 with keep_last=0
  - 403 for viewer role
  - 200 with correct shape for editor role
"""
from __future__ import annotations

import sys
import os
import uuid
import pathlib
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# sys.path bootstrap — mirrors conftest.py
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).parent
_PACKAGES_ROOT = _HERE.parent.parent

for _entry in _PACKAGES_ROOT.iterdir():
    if not _entry.name.startswith("kerf-"):
        continue
    _src = _entry / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_PROJECT_ID = str(uuid.uuid4())
_WORKSPACE_ID = str(uuid.uuid4())
_OWNER_USER_ID = str(uuid.uuid4())
_VIEWER_USER_ID = str(uuid.uuid4())

# Map user_id → workspace role.
_ROLES = {
    _OWNER_USER_ID: "owner",
    _VIEWER_USER_ID: "viewer",
}

# Fake purge result returned by the mock.
_PURGE_RESULT = {"removed_rows": 42, "freed_bytes": 102400}


# ---------------------------------------------------------------------------
# Build a test FastAPI app with mocked internals
# ---------------------------------------------------------------------------

def _build_app(user_id: str):
    """
    Build a minimal FastAPI app for the purge route with all DB calls mocked.
    The `user_id` argument controls which role the authenticated user has.
    """
    import kerf_core.db.connection as _conn_mod
    import kerf_api.routes as _routes_mod

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    @asynccontextmanager
    async def lifespan(app):
        # Provide a fake pool so get_pool_required() doesn't raise.
        fake_pool = object()  # just needs to be truthy
        _conn_mod._pool = fake_pool
        yield
        _conn_mod._pool = None

    app = FastAPI(lifespan=lifespan)
    from kerf_api.routes import router as api_router
    app.include_router(api_router, prefix="/api")
    return app


def _auth_token(user_id: str) -> str:
    """Mint a JWT for the given user_id."""
    import jwt
    from datetime import datetime, timedelta, timezone
    now = datetime.now(tz=timezone.utc)
    return jwt.encode(
        {"sub": user_id, "exp": now + timedelta(hours=1), "iat": now},
        "dev-secret-change-in-production",
        algorithm="HS256",
    )


def _headers(user_id: str) -> dict:
    return {"Authorization": f"Bearer {_auth_token(user_id)}"}


# ---------------------------------------------------------------------------
# Shared patch context
# ---------------------------------------------------------------------------

def _make_patches(user_id: str, purge_result: dict = _PURGE_RESULT):
    """
    Returns a list of patch context managers that mock out the DB helpers.
    """
    role = _ROLES.get(user_id, "editor")

    patches = [
        # project_workspace_id → returns a fake workspace id
        patch(
            "kerf_api.routes.project_workspace_id",
            new=AsyncMock(return_value=_WORKSPACE_ID),
        ),
        # get_user_workspace_role → returns role based on user_id
        patch(
            "kerf_api.routes.get_user_workspace_role",
            new=AsyncMock(return_value=role),
        ),
        # pool.acquire context manager → fake conn
        patch(
            "kerf_api.routes.get_pool_required",
            new=AsyncMock(return_value=_FakePool()),
        ),
        # purge_project_revisions → returns preset result
        patch(
            "kerf_core.revisions.purge_project_revisions",
            new=AsyncMock(return_value=purge_result),
        ),
    ]
    return patches


class _FakeConn:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        pass
    async def fetchrow(self, *a, **kw):
        return None
    async def execute(self, *a, **kw):
        return "OK"


class _FakePool:
    """asyncpg-compatible fake pool. acquire() returns an async context manager."""
    def acquire(self):
        return _FakeConn()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPurgeRouteValidation:
    """Validation / guard-rail tests — no real DB needed."""

    def _call(self, user_id: str, params: str, purge_result=_PURGE_RESULT):
        from fastapi.testclient import TestClient
        app = _build_app(user_id)
        with (
            patch("kerf_api.routes.project_workspace_id",
                  new=AsyncMock(return_value=_WORKSPACE_ID)),
            patch("kerf_api.routes.get_user_workspace_role",
                  new=AsyncMock(return_value=_ROLES.get(user_id, "editor"))),
            patch("kerf_api.routes.get_pool_required",
                  new=AsyncMock(return_value=_FakePool())),
            patch("kerf_core.revisions.purge_project_revisions",
                  new=AsyncMock(return_value=purge_result)),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                return client.delete(
                    f"/api/projects/{_PROJECT_ID}/revisions{params}",
                    headers=_headers(user_id),
                )

    # ── 400: missing confirm ──────────────────────────────────────────────────

    def test_400_without_confirm_param(self):
        r = self._call(_OWNER_USER_ID, "?keep_last=5")
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        assert "PURGE" in r.text or "confirm" in r.text.lower()

    def test_400_wrong_confirm_value(self):
        r = self._call(_OWNER_USER_ID, "?keep_last=5&confirm=yes")
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"

    # ── 400: keep_last < 1 ───────────────────────────────────────────────────

    def test_400_keep_last_zero(self):
        r = self._call(_OWNER_USER_ID, "?keep_last=0&confirm=PURGE")
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"

    def test_400_keep_last_negative(self):
        r = self._call(_OWNER_USER_ID, "?keep_last=-1&confirm=PURGE")
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"

    # ── 403: viewer role ─────────────────────────────────────────────────────

    def test_403_for_viewer(self):
        r = self._call(_VIEWER_USER_ID, "?keep_last=5&confirm=PURGE")
        assert r.status_code == 403, f"Expected 403, got {r.status_code}: {r.text}"

    # ── 200: editor / owner ──────────────────────────────────────────────────

    def test_200_for_owner(self):
        r = self._call(_OWNER_USER_ID, "?keep_last=5&confirm=PURGE")
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert "removed_rows" in body, f"Missing removed_rows: {body}"
        assert "freed_bytes" in body, f"Missing freed_bytes: {body}"
        assert body["removed_rows"] == _PURGE_RESULT["removed_rows"]
        assert body["freed_bytes"] == _PURGE_RESULT["freed_bytes"]

    def test_200_shape_for_editor(self):
        # Register an editor user.
        editor_id = str(uuid.uuid4())
        _ROLES[editor_id] = "editor"
        try:
            r = self._call(editor_id, "?keep_last=5&confirm=PURGE")
            assert r.status_code == 200, f"Expected 200 for editor, got {r.status_code}: {r.text}"
            body = r.json()
            assert isinstance(body.get("removed_rows"), int)
            assert isinstance(body.get("freed_bytes"), int)
        finally:
            del _ROLES[editor_id]
