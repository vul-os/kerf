"""Tests for GPU worker enrollment, heartbeat, claim-job, and complete endpoints.

Tests (all hermetic — no real DB):
  1. enroll → token returned once, row inserted
  2. enroll → missing auth → 401
  3. DELETE → marks revoked
  4. DELETE unknown worker → 404
  5. heartbeat → valid token succeeds
  6. heartbeat → bad token → 401
  7. heartbeat → revoked token → 401
  8. complete → BYO billing_bucket skips charge_render → charged=False
  9. complete → error body marks job failed, no charge
 10. complete → wrong worker token → 401
"""
from __future__ import annotations

import pathlib
import sys
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# sys.path bootstrap
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
# Constants
# ---------------------------------------------------------------------------
_JWT_SECRET = "dev-secret-change-in-production"
_USER_ID = str(uuid.uuid4())
_WORKER_ID = str(uuid.uuid4())
_JOB_ID = str(uuid.uuid4())


def _mint_jwt(user_id: str) -> str:
    now = datetime.now(tz=timezone.utc)
    return jwt.encode(
        {"sub": user_id, "exp": now + timedelta(hours=1), "iat": now},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _auth(user_id: str) -> dict:
    return {"Authorization": f"Bearer {_mint_jwt(user_id)}"}


def _worker_auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_token() -> str:
    import secrets
    return "kerf_wk_" + secrets.token_hex(32)


def _hash_token(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Fake DB layer
# ---------------------------------------------------------------------------

class _FakeRow(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)


class _FakeConn:
    """asyncpg connection stub."""

    def __init__(self):
        self.executions: List[tuple] = []
        self._fetchrow_return: Optional[Dict] = None
        self._fetchrow_fn = None  # optional callable

    async def execute(self, sql: str, *args) -> str:
        self.executions.append((sql, args))
        return "UPDATE 1"

    async def fetchrow(self, sql: str, *args) -> Optional[_FakeRow]:
        if self._fetchrow_fn is not None:
            result = await self._fetchrow_fn(sql, *args)
            if isinstance(result, dict):
                return _FakeRow(result)
            return result
        if self._fetchrow_return is not None:
            return _FakeRow(self._fetchrow_return)
        return None

    async def fetch(self, sql: str, *args) -> List[_FakeRow]:
        return []

    @asynccontextmanager
    async def transaction(self):
        yield self


class _FakePool:
    def __init__(self, conn: Optional[_FakeConn] = None):
        self.conn = conn or _FakeConn()

    @asynccontextmanager
    async def acquire(self):
        yield self.conn


# ---------------------------------------------------------------------------
# App builder
# ---------------------------------------------------------------------------

def _build_app(pool: _FakePool) -> FastAPI:
    """Build a minimal FastAPI app with worker routes."""
    app = FastAPI()

    with patch("kerf_core.config.get_settings") as ms:
        ms.return_value.jwt_secret = _JWT_SECRET
        ms.return_value.usage_enabled = True
        from kerf_api.routes_workers import router
        app.include_router(router)

    return app


# Patch target for pool: the imported name inside routes_workers
_POOL_PATCH = "kerf_api.routes_workers.get_pool_required"
# Patch target for JWT secret: the settings object loaded at module level
_SETTINGS_PATCH = "kerf_core.dependencies.settings"


@contextmanager
def _client(pool: _FakePool):
    """Build TestClient with mocked DB pool + JWT secret."""
    from kerf_api.routes_workers import router

    app = FastAPI()
    app.include_router(router)

    fake_settings = type("S", (), {
        "jwt_secret": _JWT_SECRET,
        "usage_enabled": True,
        "password_pepper": "",
    })()

    with patch(_POOL_PATCH, AsyncMock(return_value=pool)), \
         patch(_SETTINGS_PATCH, fake_settings):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c, pool.conn


# ---------------------------------------------------------------------------
# 1. Enroll
# ---------------------------------------------------------------------------

class TestEnroll:
    def test_enroll_returns_token_and_id(self):
        pool = _FakePool()
        with _client(pool) as (c, conn):
            resp = c.post(
                "/api/workers/enroll",
                json={"name": "my-rig", "capabilities": {"gpu_type": "RTX 4090"}},
                headers=_auth(_USER_ID),
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "token" in data
        assert data["token"].startswith("kerf_wk_")
        assert "id" in data
        assert data["name"] == "my-rig"
        assert "cli_hint" in data

    def test_enroll_writes_insert_to_db(self):
        pool = _FakePool()
        with _client(pool) as (c, conn):
            c.post(
                "/api/workers/enroll",
                json={"name": "rig-2"},
                headers=_auth(_USER_ID),
            )
        sqls = [ex[0] for ex in conn.executions]
        assert any("INSERT INTO gpu_workers" in s for s in sqls), f"No INSERT found in: {sqls}"

    def test_enroll_requires_auth(self):
        pool = _FakePool()
        with _client(pool) as (c, _):
            resp = c.post("/api/workers/enroll", json={"name": "rig"})
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 2. Delete / revoke
# ---------------------------------------------------------------------------

class TestDeleteWorker:
    def test_delete_revokes_worker(self):
        pool = _FakePool()
        # execute returns "UPDATE 1" by default
        with _client(pool) as (c, _):
            resp = c.delete(
                f"/api/workers/{_WORKER_ID}",
                headers=_auth(_USER_ID),
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["revoked"] is True

    def test_delete_unknown_worker_returns_404(self):
        pool = _FakePool()
        # Override execute to return "UPDATE 0" for the revoke UPDATE
        async def execute_zero(sql, *args):
            if "UPDATE gpu_workers" in sql:
                pool.conn.executions.append((sql, args))
                return "UPDATE 0"
            pool.conn.executions.append((sql, args))
            return "OK"
        pool.conn.execute = execute_zero

        with _client(pool) as (c, _):
            resp = c.delete(
                f"/api/workers/{_WORKER_ID}",
                headers=_auth(_USER_ID),
            )
        assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# 3. Heartbeat
# ---------------------------------------------------------------------------

class TestHeartbeat:
    def _make_pool_with_worker(self, token: str, status: str = "online") -> _FakePool:
        token_hash = _hash_token(token)
        pool = _FakePool()

        async def fetchrow(sql, *args):
            if "gpu_workers" in sql:
                if len(args) >= 2 and str(args[0]) == _WORKER_ID and args[1] == token_hash:
                    return _FakeRow({
                        "id": _WORKER_ID, "user_id": _USER_ID,
                        "name": "rig", "status": status,
                        "capabilities": {}, "last_seen_at": None,
                    })
            return None

        pool.conn._fetchrow_fn = fetchrow
        return pool

    def test_valid_token_heartbeat_succeeds(self):
        token = _make_token()
        pool = self._make_pool_with_worker(token)

        with _client(pool) as (c, _):
            resp = c.post(
                f"/api/workers/{_WORKER_ID}/heartbeat",
                json={"status": "online"},
                headers=_worker_auth(token),
            )
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is True

    def test_bad_token_returns_401(self):
        pool = _FakePool()
        # fetchrow returns None → invalid token

        with _client(pool) as (c, _):
            resp = c.post(
                f"/api/workers/{_WORKER_ID}/heartbeat",
                json={"status": "online"},
                headers=_worker_auth("kerf_wk_bad_token"),
            )
        assert resp.status_code == 401, resp.text

    def test_revoked_token_returns_401(self):
        token = _make_token()
        pool = self._make_pool_with_worker(token, status="revoked")

        with _client(pool) as (c, _):
            resp = c.post(
                f"/api/workers/{_WORKER_ID}/heartbeat",
                json={"status": "online"},
                headers=_worker_auth(token),
            )
        assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# 4. Complete job — billing short-circuit
# ---------------------------------------------------------------------------

class TestCompleteJob:
    def _make_pool(self, token: str, billing_bucket: str) -> _FakePool:
        token_hash = _hash_token(token)
        pool = _FakePool()

        async def fetchrow(sql, *args):
            sql_l = sql.lower()
            if "from gpu_workers" in sql_l:
                if len(args) >= 2 and str(args[0]) == _WORKER_ID and args[1] == token_hash:
                    return _FakeRow({
                        "id": _WORKER_ID, "user_id": _USER_ID,
                        "name": "rig", "status": "online",
                        "capabilities": {}, "last_seen_at": None,
                    })
                return None
            if "from render_jobs" in sql_l:
                return _FakeRow({
                    "id": _JOB_ID, "user_id": _USER_ID,
                    "preset": "standard", "billing_bucket": billing_bucket,
                    "status": "running",
                })
            return None

        pool.conn._fetchrow_fn = fetchrow
        return pool

    def test_byo_billing_skips_charge(self):
        token = _make_token()
        pool = self._make_pool(token, "byo")

        with _client(pool) as (c, conn):
            resp = c.post(
                f"/api/workers/{_WORKER_ID}/jobs/{_JOB_ID}/complete",
                json={"signed_url": "https://cdn/result.png", "gpu_seconds": 30.0},
                headers=_worker_auth(token),
            )

        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["charged"] is False
        assert data["billing_bucket"] == "byo"

    def test_complete_with_error_marks_failed(self):
        token = _make_token()
        pool = self._make_pool(token, "byo")

        with _client(pool) as (c, conn):
            resp = c.post(
                f"/api/workers/{_WORKER_ID}/jobs/{_JOB_ID}/complete",
                json={"signed_url": "", "gpu_seconds": 0, "error": "CUDA OOM"},
                headers=_worker_auth(token),
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["charged"] is False
        assert resp.json()["reason"] == "job_error"

        # Verify "failed" appears in a SQL UPDATE
        sqls = [ex[0] for ex in conn.executions]
        assert any("failed" in s.lower() for s in sqls), f"No 'failed' UPDATE found in: {sqls}"

    def test_complete_wrong_token_returns_401(self):
        pool = _FakePool()
        # fetchrow returns None → bad token

        with _client(pool) as (c, _):
            resp = c.post(
                f"/api/workers/{_WORKER_ID}/jobs/{_JOB_ID}/complete",
                json={"signed_url": "https://cdn/x.png", "gpu_seconds": 10},
                headers=_worker_auth("kerf_wk_wrong_token"),
            )

        assert resp.status_code == 401, resp.text
