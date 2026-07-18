"""OCC (Optimistic Concurrency Control) — file version round-trip tests.

Six specs:
  1. GET /projects/{pid}/files/{fid} returns a `version` field.
  2. PATCH without expected_version succeeds (back-compat) and bumps version.
  3. PATCH with matching expected_version succeeds and bumps version.
  4. PATCH with stale expected_version returns 409 + current_version + current_content_preview.
  5. Identical-content re-PATCH within idempotency window does NOT bump version.
  6. 409 response shape is JSON-stable.

DB safety:
  - Inserts rows with a unique uuid-prefixed prefix per run.
  - Cleans up its own rows in the finally block.
  - Never DROP / CREATE / TRUNCATE / reset migrations.

Run:
    DATABASE_URL="postgres://pc@localhost:5432/kerf?sslmode=disable" \\
        python3 -m pytest packages/kerf-api/tests/test_files_occ.py -v
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import secrets
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Generator

import asyncpg
import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ── sys.path bootstrap ────────────────────────────────────────────────────────
_HERE = pathlib.Path(__file__).parent
_PACKAGES_ROOT = _HERE.parent.parent
for _entry in _PACKAGES_ROOT.iterdir():
    if not _entry.name.startswith("kerf-"):
        continue
    _src = _entry / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

# ── Constants ─────────────────────────────────────────────────────────────────
_DB_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgres://pc@localhost:5432/kerf?sslmode=disable",
)
_JWT_SECRET = "dev-secret-change-in-production"
_RUN_PREFIX = f"occ-{secrets.token_hex(4)}"


# ── JWT helpers ───────────────────────────────────────────────────────────────
def _mint_jwt(user_id: str) -> str:
    now = datetime.now(tz=timezone.utc)
    return jwt.encode(
        {"sub": user_id, "exp": now + timedelta(hours=1), "iat": now},
        _JWT_SECRET,
        algorithm="HS256",
    )


def _auth_headers(user_id: str) -> dict:
    return {"Authorization": f"Bearer {_mint_jwt(user_id)}"}


# ── Fixture creation ──────────────────────────────────────────────────────────
async def _create_fixtures(db_url: str) -> dict:
    suffix = _RUN_PREFIX
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    try:
        async with pool.acquire() as conn:
            user_row = await conn.fetchrow(
                "INSERT INTO users (email, name) VALUES ($1, $2) RETURNING id",
                f"{suffix}@occ.test", f"OCC {suffix}",
            )
            user_id = str(user_row["id"])

            ws_row = await conn.fetchrow(
                "INSERT INTO workspaces (slug, name, created_by) VALUES ($1, $2, $3) RETURNING id",
                f"ws-{suffix}", f"WS {suffix}", user_row["id"],
            )
            ws_id = str(ws_row["id"])

            await conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES ($1, $2, 'owner')",
                ws_row["id"], user_row["id"],
            )

            proj_row = await conn.fetchrow(
                "INSERT INTO projects (workspace_id, name, tags) VALUES ($1, $2, '{}') RETURNING id",
                ws_row["id"], f"Proj {suffix}",
            )
            proj_id = str(proj_row["id"])

            file_row = await conn.fetchrow(
                "INSERT INTO files (project_id, name, kind, content) VALUES ($1, $2, 'script', $3) RETURNING id, version",
                proj_row["id"], f"main-{suffix}.jscad", "// initial",
            )
            file_id = str(file_row["id"])
    finally:
        await pool.close()

    return {
        "user_id": user_id,
        "ws_id": ws_id,
        "proj_id": proj_id,
        "file_id": file_id,
    }


async def _delete_fixtures(db_url: str, ids: dict) -> None:
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM file_revisions WHERE file_id IN (SELECT id FROM files WHERE project_id = $1)", uuid.UUID(ids["proj_id"]))
            await conn.execute("DELETE FROM files WHERE project_id = $1", uuid.UUID(ids["proj_id"]))
            await conn.execute("DELETE FROM projects WHERE id = $1", uuid.UUID(ids["proj_id"]))
            await conn.execute("DELETE FROM workspace_members WHERE workspace_id = $1", uuid.UUID(ids["ws_id"]))
            await conn.execute("DELETE FROM workspaces WHERE id = $1", uuid.UUID(ids["ws_id"]))
            await conn.execute("DELETE FROM users WHERE id = $1", uuid.UUID(ids["user_id"]))
    finally:
        await pool.close()


# ── Session-scoped fixture ────────────────────────────────────────────────────
_FIXTURE_IDS: dict | None = None


def _get_fixture_ids() -> dict:
    global _FIXTURE_IDS
    if _FIXTURE_IDS is None:
        _FIXTURE_IDS = asyncio.run(_create_fixtures(_DB_URL))
    return _FIXTURE_IDS


@pytest.fixture(scope="session", autouse=True)
def session_fixtures() -> Generator[dict, None, None]:
    ids = _get_fixture_ids()
    yield ids
    asyncio.run(_delete_fixtures(_DB_URL, ids))


# ── Test app ──────────────────────────────────────────────────────────────────
@asynccontextmanager
async def _lifespan(app: FastAPI):
    import kerf_core.db.connection as _conn
    pool = await asyncpg.create_pool(_DB_URL, min_size=2, max_size=5)
    _conn._pool = pool
    try:
        from kerf_core.storage.factory import create_storage as _cs
        from kerf_core.storage import set_storage as _ss
        _ss(_cs(backend="local", local_storage_path="./.kerf-storage-occ"))
    except Exception:
        pass
    yield
    _conn._pool = None
    await pool.close()


def _build_app() -> FastAPI:
    from kerf_api.routes import router as api_router
    app = FastAPI(lifespan=_lifespan)
    app.include_router(api_router, prefix="/api")
    return app


@pytest.fixture(scope="session")
def client() -> Generator[TestClient, None, None]:
    with TestClient(_build_app(), raise_server_exceptions=False) as c:
        yield c


def _ids() -> dict:
    return _get_fixture_ids()


# ══════════════════════════════════════════════════════════════════════════════
# Tests
# ══════════════════════════════════════════════════════════════════════════════

# ── Spec 1: GET returns version ───────────────────────────────────────────────

def test_get_file_returns_version(client: TestClient):
    """GET /projects/{pid}/files/{fid} must include a 'version' field."""
    uid = _ids()["user_id"]
    pid = _ids()["proj_id"]
    fid = _ids()["file_id"]

    r = client.get(f"/api/projects/{pid}/files/{fid}", headers=_auth_headers(uid))
    assert r.status_code == 200, f"GET file failed: {r.status_code} {r.text}"
    body = r.json()
    assert "version" in body, f"'version' missing from GET response: {body}"
    assert isinstance(body["version"], int), f"version should be int, got {type(body['version'])}"
    assert body["version"] >= 1, f"version should be >= 1, got {body['version']}"


# ── Spec 2: PATCH without expected_version bumps version (back-compat) ────────

def test_patch_without_expected_version_bumps_version(client: TestClient):
    """PATCH without expected_version succeeds (backward-compat) and bumps version."""
    uid = _ids()["user_id"]
    pid = _ids()["proj_id"]
    fid = _ids()["file_id"]

    # Read current version.
    r = client.get(f"/api/projects/{pid}/files/{fid}", headers=_auth_headers(uid))
    assert r.status_code == 200
    before_version = r.json()["version"]

    # Patch with unique content but no expected_version.
    new_content = f"// no-occ-{secrets.token_hex(4)}"
    r = client.patch(
        f"/api/projects/{pid}/files/{fid}",
        json={"content": new_content},
        headers=_auth_headers(uid),
    )
    assert r.status_code == 200, f"PATCH without expected_version failed: {r.status_code} {r.text}"
    body = r.json()
    assert "version" in body, f"'version' missing from PATCH response: {body}"
    assert body["version"] == before_version + 1, (
        f"version should have incremented from {before_version} to {before_version + 1}, "
        f"got {body['version']}"
    )


# ── Spec 3: PATCH with matching expected_version succeeds and bumps version ───

def test_patch_with_matching_expected_version_bumps_version(client: TestClient):
    """PATCH with correct expected_version succeeds and increments version."""
    uid = _ids()["user_id"]
    pid = _ids()["proj_id"]
    fid = _ids()["file_id"]

    # Get current state.
    r = client.get(f"/api/projects/{pid}/files/{fid}", headers=_auth_headers(uid))
    assert r.status_code == 200
    current_version = r.json()["version"]

    new_content = f"// occ-match-{secrets.token_hex(4)}"
    r = client.patch(
        f"/api/projects/{pid}/files/{fid}",
        json={"content": new_content, "expected_version": current_version},
        headers=_auth_headers(uid),
    )
    assert r.status_code == 200, (
        f"PATCH with matching version failed: {r.status_code} {r.text}"
    )
    body = r.json()
    assert body["version"] == current_version + 1, (
        f"version should increment to {current_version + 1}, got {body['version']}"
    )


# ── Spec 4: PATCH with stale expected_version returns 409 ─────────────────────

def test_patch_with_stale_expected_version_returns_409(client: TestClient):
    """PATCH with wrong expected_version returns 409 + current_version + preview."""
    uid = _ids()["user_id"]
    pid = _ids()["proj_id"]
    fid = _ids()["file_id"]

    # Get current version, then pass a deliberately stale one.
    r = client.get(f"/api/projects/{pid}/files/{fid}", headers=_auth_headers(uid))
    assert r.status_code == 200
    current_version = r.json()["version"]
    stale_version = max(1, current_version - 5)  # definitely stale

    r = client.patch(
        f"/api/projects/{pid}/files/{fid}",
        json={"content": f"// conflict-{secrets.token_hex(4)}", "expected_version": stale_version},
        headers=_auth_headers(uid),
    )
    assert r.status_code == 409, (
        f"Expected 409 for stale expected_version, got {r.status_code}: {r.text}"
    )
    body = r.json()
    # FastAPI wraps detail in {"detail": ...}
    detail = body.get("detail", body)
    assert "current_version" in detail, f"409 body missing current_version: {body}"
    assert "current_content_preview" in detail, f"409 body missing current_content_preview: {body}"
    assert detail["current_version"] == current_version, (
        f"409 current_version should be {current_version}, got {detail['current_version']}"
    )


# ── Spec 5: Identical-content re-PATCH does NOT bump version ──────────────────

def test_identical_content_repatch_does_not_bump_version(client: TestClient):
    """Identical content re-submitted within idempotency window keeps version."""
    uid = _ids()["user_id"]
    pid = _ids()["proj_id"]
    fid = _ids()["file_id"]

    # Write a known unique content to establish a recent revision.
    unique_content = f"// idempotent-{secrets.token_hex(8)}"

    r = client.patch(
        f"/api/projects/{pid}/files/{fid}",
        json={"content": unique_content},
        headers=_auth_headers(uid),
    )
    assert r.status_code == 200, f"First write failed: {r.status_code} {r.text}"
    version_after_first = r.json()["version"]

    # Insert the revision record directly so the idempotency check sees it.
    # The route itself doesn't create revision rows (that's the LLM/user layer),
    # but the idempotency check looks at file_revisions.content_sha256.
    # We simulate the revision by writing it directly.
    import hashlib

    sha = hashlib.sha256(unique_content.encode()).hexdigest()
    asyncio.run(_insert_revision(_DB_URL, _ids()["file_id"], unique_content, sha))

    # Re-send the exact same content within the window.
    r = client.patch(
        f"/api/projects/{pid}/files/{fid}",
        json={"content": unique_content},
        headers=_auth_headers(uid),
    )
    assert r.status_code == 200, f"Re-patch failed: {r.status_code} {r.text}"
    version_after_second = r.json()["version"]

    assert version_after_second == version_after_first, (
        f"Version should NOT have bumped on identical re-patch: "
        f"{version_after_first} → {version_after_second}"
    )


async def _insert_revision(db_url: str, file_id: str, content: str, sha_hex: str) -> None:
    """Insert a revision row. content_sha256 is bytea — pass as bytes.

    Uses a single direct connection rather than asyncpg.create_pool(): the
    idempotency check this feeds (test_identical_content_repatch_does_not_bump_version)
    has only a 5s window (_IDEMPOTENCY_WINDOW_SECS in kerf_api.routes) between
    this insert and the follow-up PATCH. Under `pytest -n auto` with the full
    suite hammering the same local Postgres instance, pool bootstrap (opening
    min_size connections + health checks) adds latency that create_pool()
    doesn't need for a single INSERT — that extra time occasionally ate
    enough of the 5s window to flip the test from flaky-pass to flaky-fail.
    A bare connect() is strictly faster and removes that variance.
    """
    conn = await asyncpg.connect(db_url)
    try:
        sha_bytes = bytes.fromhex(sha_hex)
        await conn.execute(
            """
            INSERT INTO file_revisions (file_id, content, source, content_sha256)
            VALUES ($1, $2, 'user', $3)
            """,
            uuid.UUID(file_id), content, sha_bytes,
        )
    finally:
        await conn.close()


# ── Spec 6: 409 response shape is JSON-stable ─────────────────────────────────

def test_409_response_shape_is_json_stable(client: TestClient):
    """The 409 detail object always contains the three documented keys."""
    uid = _ids()["user_id"]
    pid = _ids()["proj_id"]
    fid = _ids()["file_id"]

    r = client.get(f"/api/projects/{pid}/files/{fid}", headers=_auth_headers(uid))
    assert r.status_code == 200
    current_version = r.json()["version"]

    r = client.patch(
        f"/api/projects/{pid}/files/{fid}",
        json={"content": "// shape-test", "expected_version": 0},
        headers=_auth_headers(uid),
    )
    assert r.status_code == 409
    body = r.json()
    detail = body.get("detail", body)

    # Stable contract: these three keys must always be present.
    assert "current_version" in detail, f"409 missing current_version: {detail}"
    assert "current_content_preview" in detail, f"409 missing current_content_preview: {detail}"
    assert "message" in detail, f"409 missing message: {detail}"

    # Types must be stable.
    assert isinstance(detail["current_version"], int), "current_version must be int"
    assert isinstance(detail["current_content_preview"], str), "current_content_preview must be str"
    assert isinstance(detail["message"], str), "message must be str"
