"""Integration tests for GET /api/projects/{pid}/blobs/{oid} (T-140).

Proves:
  - referenced oid → 200 + exact bytes
  - unreferenced oid (no blob_refs row for this project) → 404
  - cross-project oid (valid blob, wrong project) → 404
  - missing auth on a private project → 401
  - non-member on a private project → 404
  - public project → anonymous (no auth) succeeds

Run:
    DATABASE_URL="postgres://pc@localhost:5432/kerf?sslmode=disable" \\
        python3 -m pytest packages/kerf-api/tests/test_blob_serve.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import secrets
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Generator

import asyncpg
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# sys.path bootstrap (mirrors conftest.py + test_api_smoke.py)
# ---------------------------------------------------------------------------
import pathlib

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

_DB_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgres://pc@localhost:5432/kerf?sslmode=disable",
)
_JWT_SECRET: str = "dev-secret-change-in-production"
_RUN_PREFIX: str = f"blobserve-{secrets.token_hex(4)}"

# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


def _mint_jwt(user_id: str) -> str:
    now = datetime.now(tz=timezone.utc)
    return jwt.encode(
        {"sub": user_id, "exp": now + timedelta(hours=1), "iat": now},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_mint_jwt(user_id)}"}


# ---------------------------------------------------------------------------
# Temp storage dir (module-scoped; shared across all tests)
# ---------------------------------------------------------------------------

_STORAGE_TMPDIR: tempfile.TemporaryDirectory | None = None
_STORAGE_PATH: str = ""


def _get_storage_path() -> str:
    global _STORAGE_TMPDIR, _STORAGE_PATH
    if _STORAGE_TMPDIR is None:
        _STORAGE_TMPDIR = tempfile.TemporaryDirectory(prefix="kerf-blobserve-")
        _STORAGE_PATH = _STORAGE_TMPDIR.name
    return _STORAGE_PATH


# ---------------------------------------------------------------------------
# DB fixture helpers
# ---------------------------------------------------------------------------


async def _create_fixtures(db_url: str) -> dict:
    """Insert all test rows; return their ids/values."""
    suffix = _RUN_PREFIX
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    try:
        async with pool.acquire() as conn:
            # owner user (member of the private project workspace)
            owner = await conn.fetchrow(
                "INSERT INTO users (email, name) VALUES ($1, $2) RETURNING id",
                f"{suffix}-owner@blobserve.test",
                f"BlobServe Owner {suffix}",
            )
            owner_id = str(owner["id"])

            # outsider user (NOT a member of the private workspace)
            outsider = await conn.fetchrow(
                "INSERT INTO users (email, name) VALUES ($1, $2) RETURNING id",
                f"{suffix}-outsider@blobserve.test",
                f"BlobServe Outsider {suffix}",
            )
            outsider_id = str(outsider["id"])

            # workspace
            ws = await conn.fetchrow(
                "INSERT INTO workspaces (slug, name, created_by) VALUES ($1, $2, $3) RETURNING id",
                f"{suffix}-ws",
                f"BlobServe WS {suffix}",
                owner["id"],
            )
            ws_id = str(ws["id"])

            await conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES ($1, $2, 'owner')",
                ws["id"], owner["id"],
            )

            # private project
            priv_proj = await conn.fetchrow(
                """
                INSERT INTO projects (workspace_id, name, visibility)
                VALUES ($1, $2, 'private') RETURNING id
                """,
                ws["id"],
                f"{suffix}-private-proj",
            )
            priv_pid = str(priv_proj["id"])

            # public project (for anonymous access test)
            pub_proj = await conn.fetchrow(
                """
                INSERT INTO projects (workspace_id, name, visibility)
                VALUES ($1, $2, 'public') RETURNING id
                """,
                ws["id"],
                f"{suffix}-public-proj",
            )
            pub_pid = str(pub_proj["id"])

            # blob content
            blob_payload = f"kerf-blobserve-test-payload-{suffix}".encode()
            oid = hashlib.sha256(blob_payload).hexdigest()

            # second project for cross-project isolation test
            other_proj = await conn.fetchrow(
                """
                INSERT INTO projects (workspace_id, name, visibility)
                VALUES ($1, $2, 'private') RETURNING id
                """,
                ws["id"],
                f"{suffix}-other-proj",
            )
            other_pid = str(other_proj["id"])

            # Record blob_objects row
            await conn.execute(
                """
                INSERT INTO blob_objects (oid, size_bytes, first_workspace_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (oid) DO NOTHING
                """,
                oid, len(blob_payload), ws["id"],
            )

            # blob_refs: private project owns this oid
            await conn.execute(
                """
                INSERT INTO blob_refs (oid, project_id, path)
                VALUES ($1, $2, $3)
                ON CONFLICT (oid, project_id, path) DO NOTHING
                """,
                oid, priv_proj["id"], "model/part.bin",
            )

            # blob_refs: public project also owns this oid (different path)
            await conn.execute(
                """
                INSERT INTO blob_refs (oid, project_id, path)
                VALUES ($1, $2, $3)
                ON CONFLICT (oid, project_id, path) DO NOTHING
                """,
                oid, pub_proj["id"], "model/part.bin",
            )

            # Note: other_proj does NOT have a blob_refs row for this oid.

    finally:
        await pool.close()

    return {
        "owner_id": owner_id,
        "outsider_id": outsider_id,
        "ws_id": ws_id,
        "priv_pid": priv_pid,
        "pub_pid": pub_pid,
        "other_pid": other_pid,
        "oid": oid,
        "blob_payload": blob_payload,
    }


async def _delete_fixtures(db_url: str, ids: dict) -> None:
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            for pid_key in ("priv_pid", "pub_pid", "other_pid"):
                await conn.execute(
                    "DELETE FROM blob_refs WHERE project_id = $1",
                    uuid.UUID(ids[pid_key]),
                )
            # Only delete blob_objects if no other refs remain (safe cleanup)
            await conn.execute(
                "DELETE FROM blob_objects WHERE oid = $1 "
                "AND NOT EXISTS (SELECT 1 FROM blob_refs WHERE oid = $1)",
                ids["oid"],
            )
            for pid_key in ("priv_pid", "pub_pid", "other_pid"):
                await conn.execute(
                    "DELETE FROM projects WHERE id = $1",
                    uuid.UUID(ids[pid_key]),
                )
            await conn.execute(
                "DELETE FROM workspace_members WHERE workspace_id = $1",
                uuid.UUID(ids["ws_id"]),
            )
            await conn.execute(
                "DELETE FROM workspaces WHERE id = $1",
                uuid.UUID(ids["ws_id"]),
            )
            for uid_key in ("owner_id", "outsider_id"):
                await conn.execute(
                    "DELETE FROM refresh_tokens WHERE user_id = $1",
                    uuid.UUID(ids[uid_key]),
                )
                await conn.execute(
                    "DELETE FROM email_tokens WHERE user_id = $1",
                    uuid.UUID(ids[uid_key]),
                )
                await conn.execute(
                    "DELETE FROM users WHERE id = $1",
                    uuid.UUID(ids[uid_key]),
                )
    finally:
        await pool.close()


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------

_FIXTURE_IDS: dict | None = None


def _get_fixture_ids() -> dict:
    global _FIXTURE_IDS
    if _FIXTURE_IDS is None:
        if not _DB_URL:
            pytest.skip("DATABASE_URL not set")
        _FIXTURE_IDS = asyncio.run(_create_fixtures(_DB_URL))
    return _FIXTURE_IDS


@pytest.fixture(scope="session", autouse=True)
def session_fixtures() -> Generator[dict, None, None]:
    ids = _get_fixture_ids()
    yield ids
    asyncio.run(_delete_fixtures(_DB_URL, ids))
    if _STORAGE_TMPDIR is not None:
        _STORAGE_TMPDIR.cleanup()


# ---------------------------------------------------------------------------
# Test app + TestClient
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    import kerf_core.db.connection as _conn
    from kerf_core.storage.factory import create_storage as _cs
    from kerf_core.storage import set_storage as _ss
    from kerf_core.storage.materialize import blob_storage_key

    pool = await asyncpg.create_pool(_DB_URL, min_size=2, max_size=5)
    _conn._pool = pool

    storage_path = _get_storage_path()
    storage = _cs(backend="local", local_storage_path=storage_path)
    _ss(storage)

    # Pre-populate the blob in local storage so get() succeeds.
    ids = _get_fixture_ids()
    payload = ids["blob_payload"]
    oid = ids["oid"]
    key = blob_storage_key(oid)
    await storage.put(key, io.BytesIO(payload), "application/octet-stream", len(payload))

    yield

    _conn._pool = None
    await pool.close()


def _build_test_app() -> FastAPI:
    from kerf_api.routes import router as api_router
    app = FastAPI(lifespan=_lifespan)
    app.include_router(api_router, prefix="/api")
    return app


@pytest.fixture(scope="session")
def client(session_fixtures) -> Generator[TestClient, None, None]:
    if not _DB_URL:
        pytest.skip("DATABASE_URL not set")
    app = _build_test_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _ids() -> dict:
    return _get_fixture_ids()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_referenced_oid_returns_200_with_correct_bytes(client: TestClient):
    """Owner fetches a blob the private project references — must get exact bytes."""
    ids = _ids()
    r = client.get(
        f"/api/projects/{ids['priv_pid']}/blobs/{ids['oid']}",
        headers=_auth_headers(ids["owner_id"]),
    )
    assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
    assert r.content == ids["blob_payload"], "body mismatch"


def test_unreferenced_oid_returns_404(client: TestClient):
    """A valid oid that has no blob_refs row for this project → 404."""
    ids = _ids()
    phantom_oid = hashlib.sha256(b"no-such-blob").hexdigest()
    r = client.get(
        f"/api/projects/{ids['priv_pid']}/blobs/{phantom_oid}",
        headers=_auth_headers(ids["owner_id"]),
    )
    assert r.status_code == 404, f"expected 404 got {r.status_code}: {r.text}"


def test_cross_project_oid_returns_404(client: TestClient):
    """Member of workspace fetches a blob via a project that doesn't reference it."""
    ids = _ids()
    # other_pid exists and owner is a member, but has no blob_refs row for this oid
    r = client.get(
        f"/api/projects/{ids['other_pid']}/blobs/{ids['oid']}",
        headers=_auth_headers(ids["owner_id"]),
    )
    assert r.status_code == 404, f"expected 404 got {r.status_code}: {r.text}"


def test_unauthenticated_private_project_returns_401(client: TestClient):
    """No auth token + private project → 401."""
    ids = _ids()
    r = client.get(f"/api/projects/{ids['priv_pid']}/blobs/{ids['oid']}")
    assert r.status_code == 401, f"expected 401 got {r.status_code}: {r.text}"


def test_non_member_private_project_returns_404(client: TestClient):
    """Authenticated but not a workspace member → 404 (no info leak)."""
    ids = _ids()
    r = client.get(
        f"/api/projects/{ids['priv_pid']}/blobs/{ids['oid']}",
        headers=_auth_headers(ids["outsider_id"]),
    )
    assert r.status_code == 404, f"expected 404 got {r.status_code}: {r.text}"


def test_public_project_anonymous_access(client: TestClient):
    """Public project: no auth header → still returns 200 + correct bytes."""
    ids = _ids()
    r = client.get(f"/api/projects/{ids['pub_pid']}/blobs/{ids['oid']}")
    assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
    assert r.content == ids["blob_payload"], "body mismatch on public access"


def test_nonexistent_project_returns_404(client: TestClient):
    """Random UUID that doesn't exist → 404."""
    ids = _ids()
    fake_pid = str(uuid.uuid4())
    r = client.get(
        f"/api/projects/{fake_pid}/blobs/{ids['oid']}",
        headers=_auth_headers(ids["owner_id"]),
    )
    assert r.status_code == 404, f"expected 404 got {r.status_code}: {r.text}"
