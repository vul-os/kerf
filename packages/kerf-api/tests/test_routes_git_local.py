"""Integration tests for the local git API (packages/kerf_api/routes_git_local.py).

Covers the full contract:
  GET  /api/git/{pid}/status
  POST /api/git/{pid}/init
  POST /api/git/{pid}/commit
  GET  /api/git/{pid}/log
  GET/POST /api/git/{pid}/remotes, DELETE /api/git/{pid}/remotes/{name}
  POST /api/git/{pid}/push, POST /api/git/{pid}/pull

Push/pull are exercised against a second, plain on-disk bare repo (a `file://`
style local remote) — this is real subprocess git end-to-end, no SSH/network
needed, matching the "ambient credentials" contract (a local path remote
needs no credential at all, same as SSH-agent / credential-helper paths the
production code takes for a real remote).

DB safety:
  - All rows are written with a unique run-prefix and cleaned up in a
    finally block.  No DROP / CREATE / TRUNCATE.
  - storage_backend=local (temp dir), never real S3.

Run:
    DATABASE_URL="postgres://pc@localhost:5432/kerf?sslmode=disable" \\
        python3 -m pytest packages/kerf-api/tests/test_routes_git_local.py -q
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import secrets
import subprocess
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
_RUN_PREFIX: str = f"gitlocal-{secrets.token_hex(4)}"


def _mint_jwt(user_id: str) -> str:
    now = datetime.now(tz=timezone.utc)
    return jwt.encode(
        {"sub": user_id, "exp": now + timedelta(hours=1), "iat": now},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_mint_jwt(user_id)}"}


_STORAGE_TMPDIR: str | None = None


def _storage_root() -> str:
    global _STORAGE_TMPDIR
    if _STORAGE_TMPDIR is None:
        _STORAGE_TMPDIR = tempfile.mkdtemp(prefix="kerf-gitlocal-test-")
    return _STORAGE_TMPDIR


def _repo_dir(storage_root: str, project_id: str) -> str:
    """Mirror the LocalStorage path that resolve_project_repo produces."""
    return os.path.join(storage_root, "objs", "workspaces", project_id, "git")


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

_FIXTURE_DATA: dict | None = None


async def _create_fixtures(db_url: str) -> dict:
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    data: dict = {}
    try:
        async with pool.acquire() as conn:
            user_row = await conn.fetchrow(
                "INSERT INTO users (email, name, account_role, is_system) "
                "VALUES ($1, $2, 'user', false) RETURNING id",
                f"{_RUN_PREFIX}@gitlocal.test", f"GitLocal {_RUN_PREFIX}",
            )
            data["user_id"] = str(user_row["id"])

            ws_row = await conn.fetchrow(
                "INSERT INTO workspaces (slug, name, created_by) VALUES ($1, $2, $3) RETURNING id",
                f"ws-{_RUN_PREFIX}", f"WS {_RUN_PREFIX}", user_row["id"],
            )
            data["ws_id"] = str(ws_row["id"])

            await conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES ($1, $2, 'owner')",
                ws_row["id"], user_row["id"],
            )

            proj_row = await conn.fetchrow(
                "INSERT INTO projects (workspace_id, name, description, visibility, tags) "
                "VALUES ($1, $2, 'desc', 'private', '{}') RETURNING id",
                ws_row["id"], f"GitLocalProj {_RUN_PREFIX}",
            )
            data["project_id"] = str(proj_row["id"])

            other_row = await conn.fetchrow(
                "INSERT INTO users (email, name, account_role, is_system) "
                "VALUES ($1, $2, 'user', false) RETURNING id",
                f"{_RUN_PREFIX}-other@gitlocal.test", f"Other {_RUN_PREFIX}",
            )
            data["other_user_id"] = str(other_row["id"])
    finally:
        await pool.close()
    return data


async def _delete_fixtures(db_url: str, data: dict) -> None:
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM files WHERE project_id = $1", uuid.UUID(data["project_id"]))
            await conn.execute("DELETE FROM blob_refs WHERE project_id = $1", uuid.UUID(data["project_id"]))
            await conn.execute("DELETE FROM blob_objects WHERE first_workspace_id = $1", uuid.UUID(data["ws_id"]))
            await conn.execute("DELETE FROM projects WHERE id = $1", uuid.UUID(data["project_id"]))
            await conn.execute("DELETE FROM workspace_members WHERE workspace_id = $1", uuid.UUID(data["ws_id"]))
            await conn.execute("DELETE FROM workspaces WHERE id = $1", uuid.UUID(data["ws_id"]))
            for uid in (data.get("user_id"), data.get("other_user_id")):
                if not uid:
                    continue
                uid_u = uuid.UUID(uid)
                await conn.execute("DELETE FROM refresh_tokens WHERE user_id = $1", uid_u)
                await conn.execute("DELETE FROM email_tokens WHERE user_id = $1", uid_u)
                await conn.execute("DELETE FROM users WHERE id = $1", uid_u)
    finally:
        await pool.close()


def _get_fixture_data() -> dict:
    global _FIXTURE_DATA
    if _FIXTURE_DATA is None:
        _FIXTURE_DATA = asyncio.run(_create_fixtures(_DB_URL))
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
    from kerf_api.routes_git_local import router

    app = FastAPI(lifespan=_lifespan)
    app.include_router(router, prefix="/api")
    return app


@pytest.fixture(scope="session")
def client(session_fixtures) -> Generator[TestClient, None, None]:
    app = _build_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGitLocalLifecycle:
    """End-to-end: status -> init -> commit -> log -> remotes -> push -> pull.

    Deliberately ONE test method covering the whole sequence (rather than one
    method per step) — pytest-xdist's default `-n auto` load-balances
    individual test *items* across worker processes with no ordering or
    co-location guarantee, so splitting a stateful sequence across separate
    test methods is not safe under `-n auto` (each worker has its own
    process-local `_FIXTURE_DATA`/mutable-dict state). A single test method
    is one atomic xdist work item, so the sequence always runs in order in
    one process.
    """

    def test_full_lifecycle(self, client: TestClient):
        data = _get_fixture_data()
        pid = data["project_id"]

        # -- status before init --
        r = client.get(f"/api/git/{pid}/status", headers=_auth_headers(data["user_id"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["initialized"] is False
        assert body["branch"] is None
        assert body["dirty"] is False
        assert body["remotes"] == []

        # -- 404 for a user who isn't a workspace member --
        other_r = client.get(f"/api/git/{pid}/status", headers=_auth_headers(data["other_user_id"]))
        assert other_r.status_code == 404

        # -- init creates a bare repo, is idempotent --
        init_r = client.post(f"/api/git/{pid}/init", headers=_auth_headers(data["user_id"]))
        assert init_r.status_code == 200, init_r.text
        init_body = init_r.json()
        assert init_body["initialized"] is True
        assert init_body["branch"] == "main"
        assert init_body["dirty"] is False
        repo_dir = _repo_dir(_storage_root(), pid)
        assert os.path.isdir(os.path.join(repo_dir, "objects"))

        init_again_r = client.post(f"/api/git/{pid}/init", headers=_auth_headers(data["user_id"]))
        assert init_again_r.status_code == 200

        # -- dirty reflects an uncommitted file in the `files` table --
        async def _add_file():
            pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=1)
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO files (project_id, parent_id, name, kind, content) "
                        "VALUES ($1, NULL, 'main.txt', 'file', 'hello world')",
                        uuid.UUID(pid),
                    )
            finally:
                await pool.close()

        asyncio.run(_add_file())
        dirty_r = client.get(f"/api/git/{pid}/status", headers=_auth_headers(data["user_id"]))
        assert dirty_r.json()["dirty"] is True

        # -- commit requires a message --
        empty_msg_r = client.post(
            f"/api/git/{pid}/commit", json={"message": "  "}, headers=_auth_headers(data["user_id"]),
        )
        assert empty_msg_r.status_code == 400

        # -- commit returns a sha and clears dirty --
        commit_r = client.post(
            f"/api/git/{pid}/commit",
            json={"message": "initial commit"},
            headers=_auth_headers(data["user_id"]),
        )
        assert commit_r.status_code == 200, commit_r.text
        sha1 = commit_r.json()["sha"]
        assert isinstance(sha1, str) and len(sha1) == 40

        clean_r = client.get(f"/api/git/{pid}/status", headers=_auth_headers(data["user_id"]))
        assert clean_r.json()["dirty"] is False

        # -- log returns the expected shape --
        log_r = client.get(f"/api/git/{pid}/log?limit=10", headers=_auth_headers(data["user_id"]))
        assert log_r.status_code == 200, log_r.text
        commits = log_r.json()
        assert len(commits) >= 1
        top = commits[0]
        assert set(top.keys()) == {"sha", "message", "author", "ts"}
        assert top["message"] == "initial commit"
        assert isinstance(top["ts"], int)
        assert "@" in top["author"]

        # -- remotes: validation, add, list --
        bad_remote_r = client.post(
            f"/api/git/{pid}/remotes", json={"name": "", "url": ""}, headers=_auth_headers(data["user_id"]),
        )
        assert bad_remote_r.status_code == 400

        # Second bare repo on disk acts as the "remote" — a plain filesystem
        # path needs no credential at all, exercising the real push/pull
        # subprocess path without SSH.
        remote_dir = tempfile.mkdtemp(prefix="kerf-gitlocal-remote-")
        subprocess.run(["git", "init", "--bare", remote_dir], check=True, capture_output=True)

        add_remote_r = client.post(
            f"/api/git/{pid}/remotes",
            json={"name": "origin", "url": remote_dir},
            headers=_auth_headers(data["user_id"]),
        )
        assert add_remote_r.status_code == 200, add_remote_r.text

        list_remotes_r = client.get(f"/api/git/{pid}/remotes", headers=_auth_headers(data["user_id"]))
        assert list_remotes_r.status_code == 200
        assert "origin" in [rem["name"] for rem in list_remotes_r.json()]

        # -- push, verify the remote actually received the commit --
        push_r = client.post(
            f"/api/git/{pid}/push",
            json={"remote": "origin", "branch": "main"},
            headers=_auth_headers(data["user_id"]),
        )
        assert push_r.status_code == 200, push_r.text
        remote_log = subprocess.run(
            ["git", "-C", remote_dir, "log", "--format=%H"], check=True, capture_output=True, text=True,
        )
        assert sha1 in remote_log.stdout

        # -- a clean error for pushing to an unknown remote --
        bad_push_r = client.post(
            f"/api/git/{pid}/push",
            json={"remote": "does-not-exist", "branch": "main"},
            headers=_auth_headers(data["user_id"]),
        )
        assert bad_push_r.status_code == 502
        assert bad_push_r.json()["detail"]  # non-empty, cleaned stderr

        # -- pull: a collaborator pushes directly to the "remote", we pull it in --
        work = tempfile.mkdtemp(prefix="kerf-gitlocal-work-")
        subprocess.run(["git", "clone", remote_dir, work], check=True, capture_output=True)
        subprocess.run(["git", "-C", work, "config", "user.email", "collab@test"], check=True)
        subprocess.run(["git", "-C", work, "config", "user.name", "Collab"], check=True)
        (pathlib.Path(work) / "collab.txt").write_text("from collaborator")
        subprocess.run(["git", "-C", work, "add", "collab.txt"], check=True, capture_output=True)
        subprocess.run(["git", "-C", work, "commit", "-m", "collaborator commit"], check=True, capture_output=True)
        subprocess.run(["git", "-C", work, "push", "origin", "HEAD:main"], check=True, capture_output=True)

        pull_r = client.post(
            f"/api/git/{pid}/pull",
            json={"remote": "origin", "branch": "main"},
            headers=_auth_headers(data["user_id"]),
        )
        assert pull_r.status_code == 200, pull_r.text

        after_pull_log_r = client.get(f"/api/git/{pid}/log?limit=10", headers=_auth_headers(data["user_id"]))
        messages = [c["message"] for c in after_pull_log_r.json()]
        assert "collaborator commit" in messages

        # -- delete remote --
        del_unknown_r = client.delete(
            f"/api/git/{pid}/remotes/does-not-exist", headers=_auth_headers(data["user_id"]),
        )
        assert del_unknown_r.status_code == 404

        del_r = client.delete(f"/api/git/{pid}/remotes/origin", headers=_auth_headers(data["user_id"]))
        assert del_r.status_code == 200, del_r.text
        final_remotes_r = client.get(f"/api/git/{pid}/remotes", headers=_auth_headers(data["user_id"]))
        assert "origin" not in [rem["name"] for rem in final_remotes_r.json()]


class TestGitLocalOnFreshProject:
    """A project with no git repo yet: log/remotes must degrade gracefully."""

    def test_log_on_uninitialized_project_is_empty(self, client: TestClient):
        data = _get_fixture_data()

        async def _make_project():
            pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=1)
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "INSERT INTO projects (workspace_id, name, description, visibility, tags) "
                        "VALUES ($1, $2, 'desc', 'private', '{}') RETURNING id",
                        uuid.UUID(data["ws_id"]), f"Fresh {_RUN_PREFIX}",
                    )
                    return str(row["id"])
            finally:
                await pool.close()

        fresh_pid = asyncio.run(_make_project())
        data["fresh_project_id"] = fresh_pid

        r = client.get(f"/api/git/{fresh_pid}/log", headers=_auth_headers(data["user_id"]))
        assert r.status_code == 200
        assert r.json() == []

        remotes_r = client.get(f"/api/git/{fresh_pid}/remotes", headers=_auth_headers(data["user_id"]))
        assert remotes_r.status_code == 200
        assert remotes_r.json() == []
