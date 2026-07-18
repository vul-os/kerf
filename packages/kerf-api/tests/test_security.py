"""T-121 — Security suite: IDOR / authz / input-validation / token single-use+expiry.

Five assertion categories (per spec):

  (a) IDOR — user A cannot GET/PATCH/DELETE user B's project or workspace.
  (b) Cross-workspace authz — workspace member cannot access a project
      that lives in a different workspace.
  (c) Token single-use — a used password-reset / email-verification token
      is rejected on a second use.
  (d) Token expiry — an expired token is rejected.
  (e) Bootstrap-local is blocked in cloud mode.
  (f) Unauthenticated requests to protected endpoints are rejected.

Design constraints
------------------
* Talks to a REAL shared Postgres (DATABASE_URL env var).
  Never DROP / CREATE / TRUNCATE.  Each run creates its own isolated
  users (A, B) and workspaces with uuid-suffixed emails, then deletes
  them in fixture teardown.
* All negative cases must return 403 or 404 — not 500.
* If DATABASE_URL is absent, all live-DB tests are skipped cleanly.
* A FastAPI app with a lifespan fixture creates the pool inside
  Starlette/anyio's own event loop (correct pool-loop affinity).
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import pathlib
import secrets
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _uuid_email(tag: str) -> str:
    """Collision-free email for one test run."""
    return f"sec-test-{tag}-{uuid.uuid4().hex[:12]}@test.invalid"


DATABASE_URL = os.environ.get("DATABASE_URL", "")


def _skip_no_db():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set — skipping live-DB security tests")


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _make_jwt(user_id: str, expired: bool = False) -> str:
    """Mint a valid (or expired) HS256 JWT using the app's configured secret."""
    import jwt as pyjwt
    from kerf_core.config import get_settings
    s = get_settings()
    now = datetime.now(timezone.utc)
    if expired:
        exp = now - timedelta(hours=1)
        iat = now - timedelta(hours=2)
    else:
        exp = now + timedelta(minutes=60)
        iat = now
    return pyjwt.encode({"sub": user_id, "exp": exp, "iat": iat}, s.jwt_secret, algorithm="HS256")


def _make_jwt_wrong_secret(user_id: str) -> str:
    import jwt as pyjwt
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=1)
    return pyjwt.encode({"sub": user_id, "exp": exp, "iat": now},
                        "wrong-secret-key", algorithm="HS256")


# ---------------------------------------------------------------------------
# Live-DB scenario — isolated rows created/deleted per test module
# ---------------------------------------------------------------------------

# Shared state for the module-scoped scenario.
_SCENARIO: dict = {}


def _setup_scenario_sync():
    """Create isolated users, workspaces, and a project using a dedicated event loop."""
    import asyncpg

    async def _run():
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                email_a = _uuid_email("alice")
                email_b = _uuid_email("bob")

                user_a = await conn.fetchrow(
                    "INSERT INTO users (email, name, password_hash) "
                    "VALUES ($1, 'Alice Sec', 'x') RETURNING id, email",
                    email_a,
                )
                user_b = await conn.fetchrow(
                    "INSERT INTO users (email, name, password_hash) "
                    "VALUES ($1, 'Bob Sec', 'x') RETURNING id, email",
                    email_b,
                )

                uid_a = str(user_a["id"])
                uid_b = str(user_b["id"])

                slug_a = f"ws-a-{uuid.uuid4().hex[:8]}"
                ws_a = await conn.fetchrow(
                    "INSERT INTO workspaces (slug, name, created_by) "
                    "VALUES ($1, 'WS-A', $2) RETURNING id, slug",
                    slug_a, user_a["id"],
                )
                await conn.execute(
                    "INSERT INTO workspace_members (workspace_id, user_id, role) "
                    "VALUES ($1, $2, 'owner')",
                    ws_a["id"], user_a["id"],
                )

                slug_b = f"ws-b-{uuid.uuid4().hex[:8]}"
                ws_b = await conn.fetchrow(
                    "INSERT INTO workspaces (slug, name, created_by) "
                    "VALUES ($1, 'WS-B', $2) RETURNING id, slug",
                    slug_b, user_b["id"],
                )
                await conn.execute(
                    "INSERT INTO workspace_members (workspace_id, user_id, role) "
                    "VALUES ($1, $2, 'owner')",
                    ws_b["id"], user_b["id"],
                )

                proj_a = await conn.fetchrow(
                    "INSERT INTO projects (workspace_id, name, visibility) "
                    "VALUES ($1, 'Project-A', 'private') RETURNING id",
                    ws_a["id"],
                )

                return {
                    "uid_a": uid_a,
                    "uid_b": uid_b,
                    "email_a": email_a,
                    "email_b": email_b,
                    "ws_a_id": str(ws_a["id"]),
                    "ws_a_slug": slug_a,
                    "ws_b_id": str(ws_b["id"]),
                    "ws_b_slug": slug_b,
                    "proj_a_id": str(proj_a["id"]),
                }
        finally:
            await pool.close()

    return asyncio.run(_run())


def _teardown_scenario_sync(data: dict):
    import asyncpg

    async def _run():
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM projects WHERE id = $1",
                    uuid.UUID(data["proj_a_id"]),
                )
                await conn.execute(
                    "DELETE FROM workspace_members WHERE workspace_id IN ($1, $2)",
                    uuid.UUID(data["ws_a_id"]), uuid.UUID(data["ws_b_id"]),
                )
                await conn.execute(
                    "DELETE FROM workspaces WHERE id IN ($1, $2)",
                    uuid.UUID(data["ws_a_id"]), uuid.UUID(data["ws_b_id"]),
                )
                await conn.execute(
                    "DELETE FROM email_tokens WHERE user_id IN ($1, $2)",
                    uuid.UUID(data["uid_a"]), uuid.UUID(data["uid_b"]),
                )
                await conn.execute(
                    "DELETE FROM refresh_tokens WHERE user_id IN ($1, $2)",
                    uuid.UUID(data["uid_a"]), uuid.UUID(data["uid_b"]),
                )
                await conn.execute(
                    "DELETE FROM users WHERE id IN ($1, $2)",
                    uuid.UUID(data["uid_a"]), uuid.UUID(data["uid_b"]),
                )
        finally:
            await pool.close()

    asyncio.run(_run())


@pytest.fixture(scope="module")
def scenario():
    """Module-scoped fixture: two isolated users + workspaces + one project."""
    _skip_no_db()
    data = _setup_scenario_sync()
    _SCENARIO.update(data)
    yield data
    _teardown_scenario_sync(data)


# ---------------------------------------------------------------------------
# App factory — pool created inside Starlette/anyio's own event loop via
# the lifespan hook (avoids cross-loop asyncpg pool issues with TestClient).
# ---------------------------------------------------------------------------

def _make_app():
    """Build a minimal FastAPI app wiring kerf_api + kerf_auth routers."""
    import asyncpg
    import kerf_api.routes as api_routes
    import kerf_auth.routes as auth_routes
    import kerf_core.db.connection as db_conn
    from fastapi import FastAPI

    _pool_ref: list = []  # mutable cell for the pool created in lifespan

    @asynccontextmanager
    async def lifespan(app):
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=4,
                                          command_timeout=30)
        db_conn._pool = pool
        _pool_ref.append(pool)
        try:
            yield
        finally:
            db_conn._pool = None
            await pool.close()

    app = FastAPI(lifespan=lifespan)
    app.include_router(api_routes.router, prefix="/api")
    app.include_router(auth_routes.router, prefix="/auth")
    return app


def _make_auth_app():
    """Minimal auth-only app (no pool needed for pure-validation tests)."""
    import kerf_auth.routes as auth_routes
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(auth_routes.router, prefix="/auth")
    return app


# ===========================================================================
# (a) IDOR — User B cannot GET / PATCH / DELETE User A's project/workspace
# ===========================================================================

class TestIDOR:

    def test_get_project_as_nonmember_returns_404(self, scenario):
        """GET /api/projects/{pid} as user B (not a workspace_a member) → 404."""
        from fastapi.testclient import TestClient
        token_b = _make_jwt(scenario["uid_b"])
        with TestClient(_make_app()) as client:
            r = client.get(
                f"/api/projects/{scenario['proj_a_id']}",
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert r.status_code in (403, 404), (
            f"IDOR: user B got project A — expected 403/404, got {r.status_code}: {r.text}"
        )

    def test_patch_project_as_nonmember_denied(self, scenario):
        """PATCH /api/projects/{pid} as user B → 403 or 404."""
        from fastapi.testclient import TestClient
        token_b = _make_jwt(scenario["uid_b"])
        with TestClient(_make_app()) as client:
            r = client.patch(
                f"/api/projects/{scenario['proj_a_id']}",
                json={"name": "HACKED"},
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert r.status_code in (403, 404), (
            f"IDOR: user B patched project A — expected 403/404, got {r.status_code}: {r.text}"
        )

    def test_delete_project_as_nonmember_denied(self, scenario):
        """DELETE /api/projects/{pid} as user B → 403 or 404."""
        from fastapi.testclient import TestClient
        token_b = _make_jwt(scenario["uid_b"])
        with TestClient(_make_app()) as client:
            r = client.delete(
                f"/api/projects/{scenario['proj_a_id']}",
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert r.status_code in (403, 404), (
            f"IDOR: user B deleted project A — expected 403/404, got {r.status_code}: {r.text}"
        )

    def test_get_workspace_as_nonmember_returns_404(self, scenario):
        """GET /api/workspaces/{slug} as user B (not a workspace_a member) → 404."""
        from fastapi.testclient import TestClient
        token_b = _make_jwt(scenario["uid_b"])
        with TestClient(_make_app()) as client:
            r = client.get(
                f"/api/workspaces/{scenario['ws_a_slug']}",
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert r.status_code in (403, 404), (
            f"IDOR: user B saw workspace A — expected 403/404, got {r.status_code}: {r.text}"
        )

    def test_patch_workspace_as_nonmember_denied(self, scenario):
        """PATCH /api/workspaces/{slug} as user B → 403 or 404."""
        from fastapi.testclient import TestClient
        token_b = _make_jwt(scenario["uid_b"])
        with TestClient(_make_app()) as client:
            r = client.patch(
                f"/api/workspaces/{scenario['ws_a_slug']}",
                json={"name": "HACKED"},
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert r.status_code in (403, 404), (
            f"IDOR: user B patched workspace A — expected 403/404, got {r.status_code}: {r.text}"
        )


# ===========================================================================
# (a-ext) File IDOR — files in user A's project not accessible to user B
# ===========================================================================

class TestFileIDOR:

    def test_list_files_nonmember_denied(self, scenario):
        """GET /api/projects/{pid}/files as nonmember → 403/404."""
        from fastapi.testclient import TestClient
        token_b = _make_jwt(scenario["uid_b"])
        with TestClient(_make_app()) as client:
            r = client.get(
                f"/api/projects/{scenario['proj_a_id']}/files",
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert r.status_code in (403, 404), (
            f"IDOR files: user B listed files in project A — got {r.status_code}: {r.text}"
        )

    def test_create_file_nonmember_denied(self, scenario):
        """POST /api/projects/{pid}/files as nonmember → 403/404."""
        from fastapi.testclient import TestClient
        token_b = _make_jwt(scenario["uid_b"])
        with TestClient(_make_app()) as client:
            r = client.post(
                f"/api/projects/{scenario['proj_a_id']}/files",
                json={"name": "evil.txt", "kind": "file", "content": "x"},
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert r.status_code in (403, 404), (
            f"IDOR files: user B created file in project A — got {r.status_code}: {r.text}"
        )


# ===========================================================================
# (b) Cross-workspace authz
# ===========================================================================

class TestCrossWorkspaceAuthz:

    def test_ws_b_member_cannot_read_ws_a_project(self, scenario):
        """User B (workspace_b owner, NOT workspace_a member) cannot GET project_a."""
        from fastapi.testclient import TestClient
        token_b = _make_jwt(scenario["uid_b"])
        with TestClient(_make_app()) as client:
            r = client.get(
                f"/api/projects/{scenario['proj_a_id']}",
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert r.status_code in (403, 404), (
            f"Cross-ws authz: member of ws_b read project in ws_a — "
            f"got {r.status_code}: {r.text}"
        )

    def test_ws_b_member_cannot_list_ws_a_project_files(self, scenario):
        """User B cannot list files in workspace_a's project."""
        from fastapi.testclient import TestClient
        token_b = _make_jwt(scenario["uid_b"])
        with TestClient(_make_app()) as client:
            r = client.get(
                f"/api/projects/{scenario['proj_a_id']}/files",
                headers={"Authorization": f"Bearer {token_b}"},
            )
        assert r.status_code in (403, 404), (
            f"Cross-ws authz: member of ws_b listed files in ws_a project — "
            f"got {r.status_code}: {r.text}"
        )


# ===========================================================================
# (f) Unauthenticated requests to protected endpoints are rejected
# ===========================================================================

class TestUnauthenticated:

    def test_me_without_token_is_401(self, scenario):
        """GET /api/me with no token → 401."""
        from fastapi.testclient import TestClient
        with TestClient(_make_app()) as client:
            r = client.get("/api/me")
        assert r.status_code == 401, (
            f"Unauthenticated /me should be 401, got {r.status_code}: {r.text}"
        )

    def test_get_project_without_token_is_401(self, scenario):
        """GET /api/projects/{pid} with no token → 401."""
        from fastapi.testclient import TestClient
        with TestClient(_make_app()) as client:
            r = client.get(f"/api/projects/{scenario['proj_a_id']}")
        assert r.status_code == 401, (
            f"Unauthenticated project GET should be 401, got {r.status_code}: {r.text}"
        )

    def test_list_projects_without_token_is_401(self):
        """GET /api/projects with no token → 401."""
        _skip_no_db()
        from fastapi.testclient import TestClient
        with TestClient(_make_app()) as client:
            r = client.get("/api/projects")
        assert r.status_code == 401, (
            f"Unauthenticated project list should be 401, got {r.status_code}: {r.text}"
        )

    def test_get_workspace_without_token_is_401(self, scenario):
        """GET /api/workspaces/{slug} with no token → 401."""
        from fastapi.testclient import TestClient
        with TestClient(_make_app()) as client:
            r = client.get(f"/api/workspaces/{scenario['ws_a_slug']}")
        assert r.status_code == 401, (
            f"Unauthenticated workspace GET should be 401, got {r.status_code}: {r.text}"
        )

    def test_expired_jwt_is_rejected(self):
        """An expired JWT must be rejected with 401."""
        _skip_no_db()
        from fastapi.testclient import TestClient
        token = _make_jwt("nobody", expired=True)
        with TestClient(_make_app()) as client:
            r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, (
            f"Expired JWT should be 401, got {r.status_code}: {r.text}"
        )

    def test_invalid_jwt_signature_is_rejected(self):
        """A JWT signed with a wrong secret must be rejected with 401."""
        _skip_no_db()
        from fastapi.testclient import TestClient
        token = _make_jwt_wrong_secret("nobody")
        with TestClient(_make_app()) as client:
            r = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, (
            f"Invalid signature JWT should be 401, got {r.status_code}: {r.text}"
        )


# ===========================================================================
# (c) Input validation at system boundaries
# ===========================================================================

class TestInputValidation:

    def test_create_project_visibility_must_be_valid(self, scenario):
        """PATCH /api/projects/{pid} with invalid visibility → 400."""
        from fastapi.testclient import TestClient
        token_a = _make_jwt(scenario["uid_a"])
        with TestClient(_make_app()) as client:
            r = client.patch(
                f"/api/projects/{scenario['proj_a_id']}",
                json={"visibility": "SUPER_PUBLIC"},
                headers={"Authorization": f"Bearer {token_a}"},
            )
        assert r.status_code == 400, (
            f"Invalid visibility should be 400, got {r.status_code}: {r.text}"
        )

    def test_patch_workspace_invalid_slug_is_400(self, scenario):
        """PATCH /api/workspaces/{slug} with invalid slug chars → 400."""
        from fastapi.testclient import TestClient
        token_a = _make_jwt(scenario["uid_a"])
        with TestClient(_make_app()) as client:
            r = client.patch(
                f"/api/workspaces/{scenario['ws_a_slug']}",
                json={"slug": "INVALID SLUG WITH SPACES!!!"},
                headers={"Authorization": f"Bearer {token_a}"},
            )
        assert r.status_code == 400, (
            f"Invalid slug should be 400, got {r.status_code}: {r.text}"
        )

    def test_reset_password_too_short_is_400(self):
        """POST /auth/reset-password with password < 8 chars → 400 (no DB hit)."""
        from fastapi.testclient import TestClient
        import kerf_auth.routes as auth_routes
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(auth_routes.router, prefix="/auth")
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/auth/reset-password",
            json={"token": "sometoken", "password": "short"},
        )
        assert r.status_code == 400, (
            f"Short password in reset should be 400, got {r.status_code}: {r.text}"
        )

    def test_reset_password_empty_token_is_400(self):
        """POST /auth/reset-password with empty token → 400."""
        from fastapi.testclient import TestClient
        import kerf_auth.routes as auth_routes
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(auth_routes.router, prefix="/auth")
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/auth/reset-password",
            json={"token": "", "password": "longenoughpw"},
        )
        assert r.status_code == 400, (
            f"Empty token in reset should be 400, got {r.status_code}: {r.text}"
        )

    def test_register_weak_password_is_400(self, scenario):
        """POST /auth/register with < 8 char password → 400."""
        from fastapi.testclient import TestClient

        with TestClient(_make_app()) as client:
            r = client.post(
                "/auth/register",
                json={"email": _uuid_email("weak"), "password": "abc", "name": "Weak"},
            )
        assert r.status_code == 400, (
            f"Weak password should be 400, got {r.status_code}: {r.text}"
        )


# ===========================================================================
# (c-ext) No secret / PII leakage in responses
# ===========================================================================

class TestNoPIILeakage:

    def test_me_response_has_no_password_hash(self, scenario):
        """GET /api/me must NOT include password_hash in the response."""
        from fastapi.testclient import TestClient
        token_a = _make_jwt(scenario["uid_a"])
        with TestClient(_make_app()) as client:
            r = client.get("/api/me", headers={"Authorization": f"Bearer {token_a}"})
        assert r.status_code == 200, f"/api/me failed: {r.status_code} {r.text}"
        body = r.json()
        assert "password_hash" not in body, (
            "PII leakage: /api/me returned password_hash in response"
        )
        assert "password" not in body, (
            "PII leakage: /api/me returned a 'password' field"
        )

    def test_me_response_has_no_jwt_secret(self, scenario):
        """GET /api/me response must not contain the JWT secret."""
        from fastapi.testclient import TestClient
        from kerf_core.config import get_settings
        token_a = _make_jwt(scenario["uid_a"])
        with TestClient(_make_app()) as client:
            r = client.get("/api/me", headers={"Authorization": f"Bearer {token_a}"})
        assert r.status_code == 200
        s = get_settings()
        assert s.jwt_secret not in r.text, (
            "PII leakage: /api/me returned the JWT secret in response body"
        )

    def test_project_response_does_not_leak_user_b_id(self, scenario):
        """GET /api/projects/{pid} by owner must NOT leak uid_b anywhere."""
        from fastapi.testclient import TestClient
        token_a = _make_jwt(scenario["uid_a"])
        with TestClient(_make_app()) as client:
            r = client.get(
                f"/api/projects/{scenario['proj_a_id']}",
                headers={"Authorization": f"Bearer {token_a}"},
            )
        assert r.status_code == 200
        assert scenario["uid_b"] not in r.text, (
            "PII leakage: project_a response leaked user_b's id"
        )


# ===========================================================================
# (d) Token single-use — password-reset / email-verify token rejected on
#     second use (real DB)
# ===========================================================================

def _insert_email_token_sync(
    user_id: str,
    kind: str,
    *,
    raw: Optional[str] = None,
    expire_in: timedelta = timedelta(hours=1),
    already_used: bool = False,
) -> str:
    """Insert an email_token row; return the raw (pre-hash) token."""
    import asyncpg

    raw = raw or secrets.token_urlsafe(32)
    token_hash = _hash_token(raw)
    expires_at = datetime.now(timezone.utc) + expire_in
    used_at = datetime.now(timezone.utc) if already_used else None

    async def _run():
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO email_tokens (user_id, kind, token_hash, expires_at, used_at) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    uuid.UUID(user_id), kind, token_hash, expires_at, used_at,
                )
        finally:
            await pool.close()

    asyncio.run(_run())
    return raw


class TestTokenSingleUse:

    def test_reset_token_second_use_rejected(self, scenario):
        """After a reset token is consumed once, a second POST → 400."""
        from fastapi.testclient import TestClient

        raw = _insert_email_token_sync(scenario["uid_a"], "reset")

        with TestClient(_make_app()) as client:
            # First use — should succeed (200)
            r1 = client.post(
                "/auth/reset-password",
                json={"token": raw, "password": "ValidPassword1!"},
            )
            assert r1.status_code == 200, (
                f"First reset should succeed (200), got {r1.status_code}: {r1.text}"
            )
            # Second use — token consumed (used_at IS NOT NULL) → must be 400
            r2 = client.post(
                "/auth/reset-password",
                json={"token": raw, "password": "AnotherPassword2@"},
            )
        assert r2.status_code == 400, (
            f"TOKEN SINGLE-USE FAILURE: second reset returned {r2.status_code} "
            f"instead of 400 — the app accepted the same reset token twice. "
            f"REAL VULNERABILITY."
        )

    def test_pre_consumed_reset_token_rejected(self, scenario):
        """A token row with used_at already set is immediately rejected."""
        from fastapi.testclient import TestClient

        raw = _insert_email_token_sync(scenario["uid_a"], "reset", already_used=True)

        with TestClient(_make_app()) as client:
            r = client.post(
                "/auth/reset-password",
                json={"token": raw, "password": "ValidPassword1!"},
            )
        assert r.status_code == 400, (
            f"Pre-consumed reset token should be 400, got {r.status_code}: {r.text}"
        )

    # test_verify_token_second_use_redirects_invalid removed 2026-07-18:
    # /auth/verify-email no longer exists. Kerf sends no email, so new
    # accounts are auto-verified at registration instead of via an emailed
    # token — see kerf_auth.routes.register() and decisions.md 2026-07-18
    # "accounts shrink to the box". Single-use-token coverage for the
    # 'reset' kind (the only email_tokens kind still issued) remains above.


# ===========================================================================
# (e) Token expiry — expired token rejected
# ===========================================================================

class TestTokenExpiry:

    def test_expired_reset_token_is_400(self, scenario):
        """POST /auth/reset-password with expired token → 400."""
        from fastapi.testclient import TestClient

        raw = _insert_email_token_sync(
            scenario["uid_a"], "reset",
            expire_in=timedelta(hours=-2),  # already expired
        )

        with TestClient(_make_app()) as client:
            r = client.post(
                "/auth/reset-password",
                json={"token": raw, "password": "ValidPassword1!"},
            )
        assert r.status_code == 400, (
            f"Expired reset token should be 400, got {r.status_code}: {r.text}"
        )

    # test_expired_verify_token_redirects_invalid removed 2026-07-18:
    # /auth/verify-email no longer exists — see the note in
    # TestTokenSingleUse above.


# ===========================================================================
# (e-ext) Bootstrap-local blocked in cloud mode (no DB needed)
# ===========================================================================

class TestBootstrapLocalCloudGuard:

    def test_bootstrap_local_blocked_when_cloud_mode(self):
        """POST /auth/bootstrap-local must return 404 when local_mode=False."""
        import kerf_auth.routes as auth_routes
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        fake_settings = MagicMock()
        fake_settings.local_mode = False

        app = FastAPI()
        app.include_router(auth_routes.router, prefix="/auth")

        with patch.object(auth_routes, "settings", fake_settings):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.post("/auth/bootstrap-local")

        assert r.status_code == 404, (
            f"bootstrap-local should be 404 in cloud mode, got {r.status_code}: {r.text}"
        )

    def test_bootstrap_local_cloud_guard_exists_in_source(self):
        """Source contract: bootstrap-local route checks local_mode."""
        import kerf_auth.routes as auth_routes
        src = pathlib.Path(auth_routes.__file__).read_text()
        assert "if not settings.local_mode:" in src, (
            "Missing cloud guard in bootstrap-local: 'if not settings.local_mode:' not found"
        )
        assert "HTTP_404_NOT_FOUND" in src, (
            "bootstrap-local must raise 404 when cloud guard triggers"
        )
