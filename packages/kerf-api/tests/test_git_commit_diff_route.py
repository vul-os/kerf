"""Tests for GET /api/projects/{pid}/git/commits/{sha}/diff (T-304).

Covers:
  - 200 + correct shape for a commit with modified files
  - 404 for an unknown sha
  - Status mapping: added / modified / deleted
  - Non-member returns 404 (membership masking)

DB safety:
  - All rows use a unique run-prefix; cleaned up in session teardown.
  - storage_backend=local (temp dir), never real S3.
  - No DROP / CREATE / TRUNCATE.

Run:
    DATABASE_URL="postgres://pc@localhost:5432/kerf?sslmode=disable" \\
        python3 -m pytest packages/kerf-api/tests/test_git_commit_diff_route.py -q
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import secrets
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Generator

import asyncpg
import jwt
import pygit2
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
_DB_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgres://pc@localhost:5432/kerf?sslmode=disable",
)
_JWT_SECRET: str = "dev-secret-change-in-production"
_RUN_PREFIX: str = f"t304-{secrets.token_hex(4)}"

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
# Storage temp dir (module-level)
# ---------------------------------------------------------------------------

_STORAGE_TMPDIR: str | None = None
_FIXTURE_DATA: dict | None = None


def _storage_root() -> str:
    global _STORAGE_TMPDIR
    if _STORAGE_TMPDIR is None:
        _STORAGE_TMPDIR = tempfile.mkdtemp(prefix="kerf-t304-test-")
    return _STORAGE_TMPDIR


# ---------------------------------------------------------------------------
# DB fixture helpers
# ---------------------------------------------------------------------------

async def _create_fixtures(db_url: str, storage_root: str) -> dict:
    """Insert minimal rows and build a bare git repo with three commits:

    sha1 — initial: adds config.py (text) + model.step (binary)
    sha2 — modifies config.py
    sha3 — deletes config.py
    """
    from kerf_core.storage.factory import create_storage
    from kerf_core.storage.materialize import materialize_and_commit, FileEntry

    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    data: dict = {}

    try:
        async with pool.acquire() as conn:
            # User
            user_row = await conn.fetchrow(
                "INSERT INTO users (email, name, account_role, is_system) "
                "VALUES ($1, $2, 'user', false) RETURNING id",
                f"{_RUN_PREFIX}@t304.test", f"T304 {_RUN_PREFIX}",
            )
            user_id = str(user_row["id"])
            data["user_id"] = user_id

            # Workspace
            ws_row = await conn.fetchrow(
                "INSERT INTO workspaces (slug, name, created_by) VALUES ($1, $2, $3) RETURNING id",
                f"ws-{_RUN_PREFIX}", f"WS {_RUN_PREFIX}", user_row["id"],
            )
            ws_id = str(ws_row["id"])
            data["ws_id"] = ws_id

            await conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES ($1, $2, 'owner')",
                ws_row["id"], user_row["id"],
            )

            # Project
            proj_row = await conn.fetchrow(
                "INSERT INTO projects (workspace_id, name, description, visibility, tags) "
                "VALUES ($1, $2, 'desc', 'private', '{}') RETURNING id",
                ws_row["id"], f"T304Proj {_RUN_PREFIX}",
            )
            project_id = str(proj_row["id"])
            data["project_id"] = project_id

            # Second user (not a member) — for 404-masking test
            other_row = await conn.fetchrow(
                "INSERT INTO users (email, name, account_role, is_system) "
                "VALUES ($1, $2, 'user', false) RETURNING id",
                f"{_RUN_PREFIX}-other@t304.test", f"Other {_RUN_PREFIX}",
            )
            data["other_user_id"] = str(other_row["id"])

        # Build real git repo via materialize_and_commit
        storage = create_storage(backend="local", local_storage_path=os.path.join(storage_root, "objs"))
        pool2 = await asyncpg.create_pool(db_url, min_size=1, max_size=2)

        try:
            async with pool2.acquire() as conn2:
                repo_dir = _repo_dir(storage_root, project_id)

                text_v1 = b"version = 1\nkey = 'hello'\n"
                binary_blob = bytes(range(256)) * 4  # 1 KiB — non-UTF-8 → binary

                # sha1: adds both files
                r1 = await materialize_and_commit(
                    repo_dir=repo_dir,
                    files=[
                        FileEntry(path="config.py", content=text_v1),
                        FileEntry(path="model.step", content=binary_blob),
                    ],
                    project_id=uuid.UUID(project_id),
                    workspace_id=uuid.UUID(ws_id),
                    storage=storage,
                    db_conn=conn2,
                    message="initial commit",
                )
                data["sha1"] = r1.commit_sha
                data["text_v1"] = text_v1

                # sha2: modifies config.py only
                text_v2 = b"version = 2\nkey = 'world'\n"
                r2 = await materialize_and_commit(
                    repo_dir=repo_dir,
                    files=[
                        FileEntry(path="config.py", content=text_v2),
                        FileEntry(path="model.step", content=binary_blob),
                    ],
                    project_id=uuid.UUID(project_id),
                    workspace_id=uuid.UUID(ws_id),
                    storage=storage,
                    db_conn=conn2,
                    message="bump version",
                )
                data["sha2"] = r2.commit_sha
                data["text_v2"] = text_v2

                # sha3: deletes config.py (only model.step remains)
                r3 = await materialize_and_commit(
                    repo_dir=repo_dir,
                    files=[
                        FileEntry(path="model.step", content=binary_blob),
                    ],
                    project_id=uuid.UUID(project_id),
                    workspace_id=uuid.UUID(ws_id),
                    storage=storage,
                    db_conn=conn2,
                    message="remove config",
                )
                data["sha3"] = r3.commit_sha
        finally:
            await pool2.close()
    finally:
        await pool.close()

    return data


def _repo_dir(storage_root: str, project_id: str) -> str:
    return os.path.join(storage_root, "objs", "workspaces", project_id, "git")


async def _delete_fixtures(db_url: str, data: dict) -> None:
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            pid = uuid.UUID(data["project_id"])
            ws = uuid.UUID(data["ws_id"])
            await conn.execute("DELETE FROM blob_refs WHERE project_id = $1", pid)
            await conn.execute("DELETE FROM blob_objects WHERE first_workspace_id = $1", ws)
            await conn.execute("DELETE FROM projects WHERE id = $1", pid)
            await conn.execute("DELETE FROM workspace_members WHERE workspace_id = $1", ws)
            await conn.execute("DELETE FROM workspaces WHERE id = $1", ws)
            for uid_str in [data.get("user_id"), data.get("other_user_id")]:
                if not uid_str:
                    continue
                uid = uuid.UUID(uid_str)
                await conn.execute("DELETE FROM refresh_tokens WHERE user_id = $1", uid)
                await conn.execute("DELETE FROM email_tokens WHERE user_id = $1", uid)
                await conn.execute("DELETE FROM users WHERE id = $1", uid)
    finally:
        await pool.close()


def _get_fixture_data() -> dict:
    global _FIXTURE_DATA
    if _FIXTURE_DATA is None:
        _FIXTURE_DATA = asyncio.run(_create_fixtures(_DB_URL, _storage_root()))
    return _FIXTURE_DATA


@pytest.fixture(scope="session", autouse=True)
def session_fixtures() -> Generator[dict, None, None]:
    data = _get_fixture_data()
    yield data
    asyncio.run(_delete_fixtures(_DB_URL, data))


# ---------------------------------------------------------------------------
# Test app
# ---------------------------------------------------------------------------

@asynccontextmanager
async def _lifespan(app: FastAPI):
    import kerf_core.db.connection as _conn
    from kerf_core.storage.local import LocalStorage
    from kerf_core.storage import set_storage as _ss

    pool = await asyncpg.create_pool(_DB_URL, min_size=2, max_size=5)
    _conn._pool = pool
    _ss(LocalStorage(root=os.path.join(_storage_root(), "objs")))
    yield
    _conn._pool = None
    await pool.close()


def _build_app() -> FastAPI:
    from kerf_cloud.routes import router

    app = FastAPI(lifespan=_lifespan)
    app.include_router(router, prefix="/api")
    return app


@pytest.fixture(scope="session")
def client(session_fixtures) -> Generator[TestClient, None, None]:
    app = _build_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests — shape and status mapping
# ---------------------------------------------------------------------------


class TestCommitDiffRoute:
    """Tests for GET /api/projects/{pid}/git/commits/{sha}/diff."""

    def test_200_and_shape_for_modified_commit(self, client: TestClient, session_fixtures):
        """sha2 modifies config.py → 200, correct shape, status=modified."""
        data = _get_fixture_data()
        pid = data["project_id"]
        uid = data["user_id"]
        sha2 = data["sha2"]

        r = client.get(
            f"/api/projects/{pid}/git/commits/{sha2}/diff",
            headers=_auth_headers(uid),
        )
        assert r.status_code == 200, f"expected 200, got {r.status_code}: {r.text[:400]}"

        body = r.json()
        assert body["sha"] == sha2
        assert "files" in body
        assert isinstance(body["files"], list)
        assert len(body["files"]) >= 1

        # Top-level keys on every file entry
        for f in body["files"]:
            assert "path" in f
            assert "status" in f
            assert "additions" in f
            assert "deletions" in f
            # hunks may be None for binary, but key must exist
            assert "hunks" in f

    def test_modified_file_has_diff_text_and_correct_status(self, client: TestClient, session_fixtures):
        """config.py is modified in sha2 → status=modified, hunks contains diff."""
        data = _get_fixture_data()
        pid = data["project_id"]
        uid = data["user_id"]
        sha2 = data["sha2"]

        r = client.get(
            f"/api/projects/{pid}/git/commits/{sha2}/diff",
            headers=_auth_headers(uid),
        )
        assert r.status_code == 200
        body = r.json()

        cfg = next((f for f in body["files"] if f["path"] == "config.py"), None)
        assert cfg is not None, f"config.py not in files: {[f['path'] for f in body['files']]}"
        assert cfg["status"] == "modified"
        assert cfg["hunks"] is not None
        assert "-version = 1" in cfg["hunks"]
        assert "+version = 2" in cfg["hunks"]
        assert cfg["additions"] > 0
        assert cfg["deletions"] > 0

    def test_status_mapping_added(self, client: TestClient, session_fixtures):
        """sha1 is the root commit — config.py status must be 'added'."""
        data = _get_fixture_data()
        pid = data["project_id"]
        uid = data["user_id"]
        sha1 = data["sha1"]

        r = client.get(
            f"/api/projects/{pid}/git/commits/{sha1}/diff",
            headers=_auth_headers(uid),
        )
        assert r.status_code == 200
        body = r.json()

        cfg = next((f for f in body["files"] if f["path"] == "config.py"), None)
        assert cfg is not None
        assert cfg["status"] == "added"

    def test_status_mapping_deleted(self, client: TestClient, session_fixtures):
        """sha3 removes config.py → status must be 'deleted'."""
        data = _get_fixture_data()
        pid = data["project_id"]
        uid = data["user_id"]
        sha3 = data["sha3"]

        r = client.get(
            f"/api/projects/{pid}/git/commits/{sha3}/diff",
            headers=_auth_headers(uid),
        )
        assert r.status_code == 200
        body = r.json()

        cfg = next((f for f in body["files"] if f["path"] == "config.py"), None)
        assert cfg is not None, f"config.py not in files: {[f['path'] for f in body['files']]}"
        assert cfg["status"] == "deleted"

    def test_404_for_unknown_sha(self, client: TestClient, session_fixtures):
        data = _get_fixture_data()
        pid = data["project_id"]
        uid = data["user_id"]

        r = client.get(
            f"/api/projects/{pid}/git/commits/deadbeef1234deadbeef1234deadbeef1234dead/diff",
            headers=_auth_headers(uid),
        )
        assert r.status_code == 404

    def test_404_for_non_member(self, client: TestClient, session_fixtures):
        data = _get_fixture_data()
        pid = data["project_id"]
        other_uid = data["other_user_id"]
        sha2 = data["sha2"]

        r = client.get(
            f"/api/projects/{pid}/git/commits/{sha2}/diff",
            headers=_auth_headers(other_uid),
        )
        assert r.status_code == 404

    def test_401_or_403_for_unauthenticated(self, client: TestClient, session_fixtures):
        data = _get_fixture_data()
        pid = data["project_id"]
        sha2 = data["sha2"]

        r = client.get(f"/api/projects/{pid}/git/commits/{sha2}/diff")
        assert r.status_code in (401, 403)
