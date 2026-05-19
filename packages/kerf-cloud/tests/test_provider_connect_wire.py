"""Regression tests for GitHub/GitLab provider connect/disconnect wiring bugs.

Bugs fixed in the audit commit (2026-05-19):

1. GET /git/providers returned plain strings instead of {id, name} objects.
   Frontend ConnectForm treated providers as objects — provider selector was
   always empty.

2. POST /provider/connect read body.get("provider") but frontend sent
   provider_id → always 400.

3. POST /provider/connect received remote_url but provider.connect() expected
   structured github_owner/github_repo (or gitlab_namespace/gitlab_project).
   The _parse_remote_url helper now bridges this gap.

4. POST /provider/disconnect required "provider" in body but frontend sent
   no body → always 400.

5. GitHub callback called /installation/token (non-existent) instead of /user.
   Graceful but logged no login; now hits the correct endpoint.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
from fastapi import HTTPException

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_TAG = "test-wire-"

_LOOP: asyncio.AbstractEventLoop | None = None


def _loop() -> asyncio.AbstractEventLoop:
    global _LOOP
    if _LOOP is None or _LOOP.is_closed():
        _LOOP = asyncio.new_event_loop()
        asyncio.set_event_loop(_LOOP)
    return _LOOP


def run(coro):
    return _loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_KEY_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
).decode()


def _gh_settings():
    s = MagicMock()
    s.cloud_github_app_id = "3727956"
    s.cloud_github_app_slug = "kerf-app"
    s.github_private_key_pem = _PRIVATE_KEY_PEM
    s.cloud_gitlab_app_id = ""
    s.cloud_gitlab_app_secret = ""
    s.cloud_gitlab_host = ""
    return s


def _gl_settings():
    s = MagicMock()
    s.cloud_github_app_id = ""
    s.github_private_key_pem = ""
    s.cloud_github_app_slug = ""
    s.cloud_gitlab_app_id = "gl-app-id"
    s.cloud_gitlab_app_secret = "gl-app-secret"
    s.cloud_gitlab_host = ""
    return s


def _both_settings():
    s = MagicMock()
    s.cloud_github_app_id = "3727956"
    s.cloud_github_app_slug = "kerf-app"
    s.github_private_key_pem = _PRIVATE_KEY_PEM
    s.cloud_gitlab_app_id = "gl-app-id"
    s.cloud_gitlab_app_secret = "gl-app-secret"
    s.cloud_gitlab_host = ""
    return s


def _make_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


# ---------------------------------------------------------------------------
# DB fixtures
# ---------------------------------------------------------------------------

async def _make_user(conn):
    uid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO users (id, email, name) VALUES ($1, $2, $3)",
        uid, f"{_TAG}{uid.hex}@test.invalid", f"Wire User {uid}",
    )
    return uid


async def _make_workspace(conn, owner):
    ws = uuid.uuid4()
    await conn.execute(
        "INSERT INTO workspaces (id, slug, name, created_by) VALUES ($1, $2, $3, $4)",
        ws, f"{_TAG}{ws.hex}", f"Wire WS {ws}", owner,
    )
    return ws


async def _make_project(conn, ws):
    pid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO projects (id, workspace_id, name) VALUES ($1, $2, $3)",
        pid, ws, f"{_TAG}proj-{pid}",
    )
    await conn.execute(
        "INSERT INTO cloud_git_repos (project_id, default_branch) VALUES ($1, 'main')",
        pid,
    )
    return pid


async def _cleanup(conn):
    await conn.execute("DELETE FROM projects  WHERE name LIKE $1", f"{_TAG}proj-%")
    await conn.execute("DELETE FROM workspaces WHERE slug LIKE $1", f"{_TAG}%")
    await conn.execute("DELETE FROM users      WHERE email LIKE $1", f"{_TAG}%@test.invalid")


@pytest.fixture(scope="module")
def db_conn():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    c = run(asyncpg.connect(DATABASE_URL))
    yield c
    run(_cleanup(c))
    run(c.close())


def _patches(conn, *, uid, registry=None, role="owner"):
    pool = _make_pool(conn)
    ps = [
        patch("kerf_cloud.routes.get_pool_required", AsyncMock(return_value=pool)),
        patch("kerf_cloud.routes.require_editor", AsyncMock(return_value=uid)),
        patch("kerf_cloud.routes.require_role", AsyncMock(return_value=(uid, role))),
    ]
    if registry is not None:
        ps.append(patch("kerf_cloud.routes._provider_registry", return_value=registry))
    return ps


# ===========================================================================
# Bug 1: GET /git/providers returns {id, name} objects, not plain strings
# ===========================================================================

class TestProvidersListShape:
    """GET /git/providers must return objects with id field."""

    def test_providers_are_objects_not_strings(self):
        from kerf_cloud.git_providers.registry import _build_default_registry
        import kerf_cloud.routes as routes

        registry = _build_default_registry(_gh_settings())

        with patch("kerf_cloud.routes._provider_registry", return_value=registry):
            result = run(routes.list_git_providers(payload={"sub": "uid-1"}))

        providers = result["providers"]
        assert len(providers) > 0, "expected at least one provider"
        first = providers[0]
        assert isinstance(first, dict), f"provider should be dict, got {type(first)}"
        assert "id" in first, "provider dict must have 'id' key"
        assert "name" in first, "provider dict must have 'name' key"
        assert first["id"] == "github"

    def test_both_providers_are_objects(self):
        from kerf_cloud.git_providers.registry import _build_default_registry
        import kerf_cloud.routes as routes

        registry = _build_default_registry(_both_settings())

        with patch("kerf_cloud.routes._provider_registry", return_value=registry):
            result = run(routes.list_git_providers(payload={"sub": "uid-1"}))

        ids = {p["id"] for p in result["providers"]}
        assert ids == {"github", "gitlab"}


# ===========================================================================
# Bug 2 + 3: provider_id alias + remote_url parsing in connect
# ===========================================================================

class TestProviderConnectAlias:
    """Backend accepts both 'provider' and 'provider_id' field names."""

    def test_connect_with_provider_field(self, db_conn):
        import kerf_cloud.routes as routes
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        from kerf_cloud.git_providers.registry import _build_default_registry
        registry = _build_default_registry(_gh_settings())

        req = MagicMock()
        req.json = AsyncMock(return_value={
            "provider": "github",
            "github_owner": "acme",
            "github_repo": "widget",
        })
        req.body = AsyncMock(return_value=b"x")

        ps = _patches(db_conn, uid=str(uid), registry=registry)
        for p in ps: p.start()
        try:
            result = run(routes.git_provider_connect(req, payload={"sub": str(uid)}, pid=str(pid)))
        finally:
            for p in reversed(ps): p.stop()

        assert result["provider"] == "github"
        assert result["kerf_git_retained"] is True

    def test_connect_with_provider_id_field(self, db_conn):
        """provider_id is accepted as alias for provider — was the frontend bug."""
        import kerf_cloud.routes as routes
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        from kerf_cloud.git_providers.registry import _build_default_registry
        registry = _build_default_registry(_gh_settings())

        req = MagicMock()
        req.json = AsyncMock(return_value={
            "provider_id": "github",  # old frontend field name
            "github_owner": "acme",
            "github_repo": "widget",
        })
        req.body = AsyncMock(return_value=b"x")

        ps = _patches(db_conn, uid=str(uid), registry=registry)
        for p in ps: p.start()
        try:
            result = run(routes.git_provider_connect(req, payload={"sub": str(uid)}, pid=str(pid)))
        finally:
            for p in reversed(ps): p.stop()

        assert result["provider"] == "github"
        assert result["kerf_git_retained"] is True


class TestRemoteUrlParsing:
    """_parse_remote_url correctly extracts structured kwargs."""

    def test_github_https_url(self):
        from kerf_cloud.routes import _parse_remote_url
        r = _parse_remote_url("github", "https://github.com/acme/widget.git")
        assert r == {"github_owner": "acme", "github_repo": "widget"}

    def test_github_https_url_no_git_suffix(self):
        from kerf_cloud.routes import _parse_remote_url
        r = _parse_remote_url("github", "https://github.com/acme/widget")
        assert r == {"github_owner": "acme", "github_repo": "widget"}

    def test_github_ssh_url(self):
        from kerf_cloud.routes import _parse_remote_url
        r = _parse_remote_url("github", "git@github.com:acme/widget.git")
        assert r == {"github_owner": "acme", "github_repo": "widget"}

    def test_github_shorthand(self):
        from kerf_cloud.routes import _parse_remote_url
        r = _parse_remote_url("github", "acme/widget")
        assert r == {"github_owner": "acme", "github_repo": "widget"}

    def test_gitlab_https_url(self):
        from kerf_cloud.routes import _parse_remote_url
        r = _parse_remote_url("gitlab", "https://gitlab.com/corp/design.git")
        assert r == {"gitlab_namespace": "corp", "gitlab_project": "design"}

    def test_gitlab_https_url_no_host_key_when_default(self):
        from kerf_cloud.routes import _parse_remote_url
        r = _parse_remote_url("gitlab", "https://gitlab.com/corp/design.git")
        assert "gitlab_host" not in r, "default gitlab.com host should not be sent"

    def test_gitlab_custom_host(self):
        from kerf_cloud.routes import _parse_remote_url
        r = _parse_remote_url("gitlab", "https://gitlab.corp.internal/ns/proj.git")
        assert r["gitlab_namespace"] == "ns"
        assert r["gitlab_project"] == "proj"
        assert r["gitlab_host"] == "https://gitlab.corp.internal"

    def test_gitlab_shorthand(self):
        from kerf_cloud.routes import _parse_remote_url
        r = _parse_remote_url("gitlab", "corp/design")
        assert r == {"gitlab_namespace": "corp", "gitlab_project": "design"}

    def test_empty_url_returns_empty_dict(self):
        from kerf_cloud.routes import _parse_remote_url
        assert _parse_remote_url("github", "") == {}
        assert _parse_remote_url("gitlab", "") == {}

    def test_connect_via_remote_url_github(self, db_conn):
        """Connect round-trip using remote_url field (frontend ConnectForm path)."""
        import kerf_cloud.routes as routes
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        from kerf_cloud.git_providers.registry import _build_default_registry
        registry = _build_default_registry(_gh_settings())

        req = MagicMock()
        req.json = AsyncMock(return_value={
            "provider": "github",
            "remote_url": "https://github.com/acme/my-design.git",
        })
        req.body = AsyncMock(return_value=b"x")

        ps = _patches(db_conn, uid=str(uid), registry=registry)
        for p in ps: p.start()
        try:
            result = run(routes.git_provider_connect(req, payload={"sub": str(uid)}, pid=str(pid)))
        finally:
            for p in reversed(ps): p.stop()

        assert result["github_owner"] == "acme"
        assert result["github_repo"] == "my-design"
        assert result["kerf_git_retained"] is True

    def test_connect_via_remote_url_gitlab(self, db_conn):
        """GitLab connect via remote_url."""
        import kerf_cloud.routes as routes
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        from kerf_cloud.git_providers.registry import _build_default_registry
        registry = _build_default_registry(_gl_settings())

        req = MagicMock()
        req.json = AsyncMock(return_value={
            "provider": "gitlab",
            "remote_url": "https://gitlab.com/corp/cad.git",
        })
        req.body = AsyncMock(return_value=b"x")

        ps = _patches(db_conn, uid=str(uid), registry=registry)
        for p in ps: p.start()
        try:
            result = run(routes.git_provider_connect(req, payload={"sub": str(uid)}, pid=str(pid)))
        finally:
            for p in reversed(ps): p.stop()

        assert result["gitlab_namespace"] == "corp"
        assert result["gitlab_project"] == "cad"
        assert result["kerf_git_retained"] is True


# ===========================================================================
# Bug 4: Disconnect with empty body (no "provider" field)
# ===========================================================================

class TestProviderDisconnectNobody:
    """Disconnect with no body disconnects all mirrors — was always 400 before fix."""

    def test_disconnect_no_body_succeeds(self, db_conn):
        """Empty body → disconnect all configured providers (no 400)."""
        import kerf_cloud.routes as routes
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        # First connect so there is something to disconnect.
        from kerf_cloud.git_providers.github import GitHubProvider
        provider = GitHubProvider(_gh_settings(), pool=_make_pool(db_conn))
        run(provider.connect(str(pid), github_owner="acme", github_repo="widget"))

        from kerf_cloud.git_providers.registry import _build_default_registry
        registry = _build_default_registry(_gh_settings())

        req = MagicMock()
        req.json = AsyncMock(return_value={})
        req.body = AsyncMock(return_value=b"")  # empty body

        ps = _patches(db_conn, uid=str(uid), registry=registry)
        for p in ps: p.start()
        try:
            result = run(routes.git_provider_disconnect(req, payload={"sub": str(uid)}, pid=str(pid)))
        finally:
            for p in reversed(ps): p.stop()

        assert result["disconnected"] is True
        assert result["kerf_git_retained"] is True

        # DB should be cleared.
        row = run(db_conn.fetchrow(
            "SELECT github_owner, github_repo FROM cloud_git_repos WHERE project_id = $1", pid
        ))
        assert row["github_owner"] is None
        assert row["github_repo"] is None

    def test_disconnect_provider_id_alias(self, db_conn):
        """provider_id is accepted as alias for provider in disconnect body."""
        import kerf_cloud.routes as routes
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        from kerf_cloud.git_providers.github import GitHubProvider
        provider = GitHubProvider(_gh_settings(), pool=_make_pool(db_conn))
        run(provider.connect(str(pid), github_owner="acme", github_repo="widget"))

        from kerf_cloud.git_providers.registry import _build_default_registry
        registry = _build_default_registry(_gh_settings())

        req = MagicMock()
        req.json = AsyncMock(return_value={"provider_id": "github"})  # old field name
        req.body = AsyncMock(return_value=b"x")

        ps = _patches(db_conn, uid=str(uid), registry=registry)
        for p in ps: p.start()
        try:
            result = run(routes.git_provider_disconnect(req, payload={"sub": str(uid)}, pid=str(pid)))
        finally:
            for p in reversed(ps): p.stop()

        assert result["disconnected"] is True
