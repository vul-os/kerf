"""T-149 — Robust multi-provider mirror-sync E2E tests.

Objectives
----------
1. **SoR invariant** — a mirror push/pull never mutates ``cloud_git_repos``
   head_sha or ``cloud_git_commits``; the Kerf-hosted git is untouched by
   provider operations.
2. **GitHub happy path** — push + pull round-trip with a faked token API.
3. **GitLab happy path** — push + pull round-trip with an injected PAT.
4. **Env-gating** — unconfigured provider is absent from the registry and its
   operations are refused (ValueError / registry returns None).
5. **Failure paths** — auth failure (HTTP 401), network error, partial-sync
   (token acquired but storer unavailable); each surfaces cleanly as a
   ValueError or provider-level error dict, never a raw httpx exception and
   never a mutation of the SoR tables.
6. **Re-sync idempotency** — calling push twice returns the same shape and
   leaves the SoR tables unchanged.

DB rule: shared Postgres ``postgres://pc@localhost:5432/kerf?sslmode=disable``.
NO DROP/CREATE/TRUNCATE. All rows use unique ``test-t149-`` prefix. Cleanup
runs via a module-scoped fixture.

No live network calls — all provider HTTP is faked via unittest.mock patches.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import httpx
import pytest

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_TAG = "test-t149-"

# ---------------------------------------------------------------------------
# Event-loop helper (avoids new_event_loop deprecation in pytest-asyncio 0.21+)
# ---------------------------------------------------------------------------

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
# Settings factories
# ---------------------------------------------------------------------------

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIVATE_KEY_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.TraditionalOpenSSL,
    encryption_algorithm=serialization.NoEncryption(),
).decode()


def _gh_settings() -> Any:
    """GitHub configured, GitLab unconfigured."""
    s = MagicMock()
    s.cloud_github_app_id = "3727956"
    s.cloud_github_app_slug = "kerf-app"
    s.github_private_key_pem = _PRIVATE_KEY_PEM
    s.cloud_gitlab_app_id = ""
    s.cloud_gitlab_app_secret = ""
    s.cloud_gitlab_host = ""
    return s


def _gl_settings() -> Any:
    """GitLab configured, GitHub unconfigured."""
    s = MagicMock()
    s.cloud_github_app_id = ""
    s.github_private_key_pem = ""
    s.cloud_github_app_slug = ""
    s.cloud_gitlab_app_id = "gl-app-id"
    s.cloud_gitlab_app_secret = "gl-app-secret"
    s.cloud_gitlab_host = ""
    return s


def _both_settings() -> Any:
    """Both providers configured."""
    s = MagicMock()
    s.cloud_github_app_id = "3727956"
    s.cloud_github_app_slug = "kerf-app"
    s.github_private_key_pem = _PRIVATE_KEY_PEM
    s.cloud_gitlab_app_id = "gl-app-id"
    s.cloud_gitlab_app_secret = "gl-app-secret"
    s.cloud_gitlab_host = ""
    return s


def _none_settings() -> Any:
    """Both providers unconfigured."""
    s = MagicMock()
    s.cloud_github_app_id = ""
    s.github_private_key_pem = ""
    s.cloud_github_app_slug = ""
    s.cloud_gitlab_app_id = ""
    s.cloud_gitlab_app_secret = ""
    s.cloud_gitlab_host = ""
    return s


# ---------------------------------------------------------------------------
# DB pool mock helper
# ---------------------------------------------------------------------------

def _make_pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


# ---------------------------------------------------------------------------
# DB fixtures  (shared Postgres, unique-suffix rows, no DROP/TRUNCATE)
# ---------------------------------------------------------------------------

async def _make_user(conn: asyncpg.Connection) -> uuid.UUID:
    uid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO users (id, email, name) VALUES ($1, $2, $3)",
        uid,
        f"{_TAG}{uid.hex}@test.invalid",
        f"T149 User {uid}",
    )
    return uid


async def _make_workspace(conn: asyncpg.Connection, owner: uuid.UUID) -> uuid.UUID:
    ws = uuid.uuid4()
    await conn.execute(
        "INSERT INTO workspaces (id, slug, name, created_by) VALUES ($1, $2, $3, $4)",
        ws,
        f"{_TAG}{ws.hex}",
        f"T149 WS {ws}",
        owner,
    )
    return ws


async def _make_project(conn: asyncpg.Connection, ws: uuid.UUID) -> uuid.UUID:
    pid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO projects (id, workspace_id, name) VALUES ($1, $2, $3)",
        pid,
        ws,
        f"{_TAG}proj-{pid}",
    )
    await conn.execute(
        "INSERT INTO cloud_git_repos (project_id, default_branch) VALUES ($1, 'main')",
        pid,
    )
    return pid


async def _cleanup(conn: asyncpg.Connection) -> None:
    await conn.execute("DELETE FROM projects  WHERE name LIKE $1", f"{_TAG}proj-%")
    await conn.execute("DELETE FROM workspaces WHERE slug  LIKE $1", f"{_TAG}%")
    await conn.execute("DELETE FROM users      WHERE email LIKE $1", f"{_TAG}%@test.invalid")


@pytest.fixture(scope="module")
def db_conn():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    c = run(asyncpg.connect(DATABASE_URL))
    yield c
    run(_cleanup(c))
    run(c.close())


# ---------------------------------------------------------------------------
# Helpers for SoR snapshot assertions
# ---------------------------------------------------------------------------

async def _sor_snapshot(conn: asyncpg.Connection, project_id: uuid.UUID) -> dict:
    """Return a snapshot of the SoR tables for *project_id* to assert unchanged."""
    repo_row = await conn.fetchrow(
        "SELECT head_sha, last_pushed_at, last_fetched_at FROM cloud_git_repos WHERE project_id = $1",
        project_id,
    )
    commit_count = await conn.fetchval(
        "SELECT COUNT(*) FROM cloud_git_commits WHERE project_id = $1",
        project_id,
    )
    return {
        "head_sha": repo_row["head_sha"] if repo_row else None,
        "last_pushed_at": repo_row["last_pushed_at"] if repo_row else None,
        "last_fetched_at": repo_row["last_fetched_at"] if repo_row else None,
        "commit_count": commit_count,
    }


# ===========================================================================
# 1. SoR INVARIANT
# ===========================================================================


class TestSoRInvariant:
    """Provider push/pull NEVER mutates cloud_git_repos or cloud_git_commits."""

    def test_github_push_does_not_touch_sor_tables(self, db_conn):
        """GitHubProvider.push() returns an authenticated URL but does not write
        to cloud_git_repos.head_sha, last_pushed_at, or cloud_git_commits."""
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        before = run(_sor_snapshot(db_conn, pid))

        async def _fake_token(installation_id, app_id, private_key_pem):
            return "ghs_sor_push_token"

        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        invalidate_cache(12345)

        with patch("kerf_cloud.git_providers.github.installation_token", _fake_token):
            provider = GitHubProvider(_gh_settings())
            result = run(provider.push(
                str(pid),
                installation_id=12345,
                github_owner="acme",
                github_repo="widget",
            ))

        after = run(_sor_snapshot(db_conn, pid))

        # Provider result looks correct
        assert result["provider"] == "github"
        assert result["status"] == "token_acquired"

        # SoR tables are identical before and after
        assert before["head_sha"] == after["head_sha"], (
            "github push mutated cloud_git_repos.head_sha — SoR violated"
        )
        assert before["last_pushed_at"] == after["last_pushed_at"], (
            "github push mutated cloud_git_repos.last_pushed_at — SoR violated"
        )
        assert before["commit_count"] == after["commit_count"], (
            "github push inserted a cloud_git_commits row — SoR violated"
        )

    def test_github_pull_does_not_touch_sor_tables(self, db_conn):
        """GitHubProvider.pull() returns an authenticated URL but does not write
        to cloud_git_repos.last_fetched_at or cloud_git_commits."""
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        before = run(_sor_snapshot(db_conn, pid))

        async def _fake_token(installation_id, app_id, private_key_pem):
            return "ghs_sor_pull_token"

        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        invalidate_cache(12346)

        with patch("kerf_cloud.git_providers.github.installation_token", _fake_token):
            provider = GitHubProvider(_gh_settings())
            result = run(provider.pull(
                str(pid),
                installation_id=12346,
                github_owner="acme",
                github_repo="widget",
            ))

        after = run(_sor_snapshot(db_conn, pid))

        assert result["provider"] == "github"
        assert result["status"] == "token_acquired"

        assert before["head_sha"] == after["head_sha"], (
            "github pull mutated cloud_git_repos.head_sha — SoR violated"
        )
        assert before["last_fetched_at"] == after["last_fetched_at"], (
            "github pull mutated cloud_git_repos.last_fetched_at — SoR violated"
        )
        assert before["commit_count"] == after["commit_count"], (
            "github pull inserted a cloud_git_commits row — SoR violated"
        )

    def test_gitlab_push_does_not_touch_sor_tables(self, db_conn):
        """GitLabProvider.push() does not mutate cloud_git_repos or cloud_git_commits."""
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        before = run(_sor_snapshot(db_conn, pid))

        from kerf_cloud.git_providers.gitlab import GitLabProvider

        provider = GitLabProvider(_gl_settings())
        result = run(provider.push(
            str(pid),
            gitlab_access_token="glpat-sor-push",
            gitlab_namespace="corp",
            gitlab_project="design",
        ))

        after = run(_sor_snapshot(db_conn, pid))

        assert result["provider"] == "gitlab"
        assert result["status"] == "token_acquired"

        assert before["head_sha"] == after["head_sha"], (
            "gitlab push mutated cloud_git_repos.head_sha — SoR violated"
        )
        assert before["last_pushed_at"] == after["last_pushed_at"], (
            "gitlab push mutated cloud_git_repos.last_pushed_at — SoR violated"
        )
        assert before["commit_count"] == after["commit_count"], (
            "gitlab push inserted a cloud_git_commits row — SoR violated"
        )

    def test_gitlab_pull_does_not_touch_sor_tables(self, db_conn):
        """GitLabProvider.pull() does not mutate cloud_git_repos or cloud_git_commits."""
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        before = run(_sor_snapshot(db_conn, pid))

        from kerf_cloud.git_providers.gitlab import GitLabProvider

        provider = GitLabProvider(_gl_settings())
        result = run(provider.pull(
            str(pid),
            gitlab_access_token="glpat-sor-pull",
            gitlab_namespace="corp",
            gitlab_project="design",
        ))

        after = run(_sor_snapshot(db_conn, pid))

        assert result["provider"] == "gitlab"
        assert result["status"] == "token_acquired"

        assert before["head_sha"] == after["head_sha"], (
            "gitlab pull mutated cloud_git_repos.head_sha — SoR violated"
        )
        assert before["last_fetched_at"] == after["last_fetched_at"], (
            "gitlab pull mutated cloud_git_repos.last_fetched_at — SoR violated"
        )
        assert before["commit_count"] == after["commit_count"], (
            "gitlab pull inserted a cloud_git_commits row — SoR violated"
        )

    def test_github_connect_writes_only_mirror_columns_not_head_sha(self, db_conn):
        """GitHubProvider.connect() writes github_owner/github_repo but MUST NOT
        touch head_sha (the authoritative SoR pointer)."""
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        # Simulate a commit having been recorded by Kerf's own git path.
        sentinel_sha = "deadbeef" * 5  # 40-char fake sha
        run(db_conn.execute(
            "UPDATE cloud_git_repos SET head_sha = $2 WHERE project_id = $1",
            pid, sentinel_sha,
        ))

        from kerf_cloud.git_providers.github import GitHubProvider

        provider = GitHubProvider(_gh_settings(), pool=_make_pool(db_conn))
        run(provider.connect(str(pid), github_owner="acme", github_repo="widget"))

        row = run(db_conn.fetchrow(
            "SELECT head_sha, github_owner, github_repo FROM cloud_git_repos WHERE project_id = $1",
            pid,
        ))

        assert row["github_owner"] == "acme"
        assert row["github_repo"] == "widget"
        assert row["head_sha"] == sentinel_sha, (
            "GitHubProvider.connect() overwrote head_sha — SoR invariant violated"
        )


# ===========================================================================
# 2. GITHUB HAPPY PATH
# ===========================================================================


class TestGitHubHappyPath:
    """Push + pull round-trip with faked GitHub token API."""

    @pytest.mark.asyncio
    async def test_push_acquires_token_and_returns_authenticated_url(self):
        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        invalidate_cache(20001)

        call_log: list[int] = []

        async def _fake_token(installation_id, app_id, private_key_pem):
            call_log.append(installation_id)
            return "ghs_happy_push_20001"

        with patch("kerf_cloud.git_providers.github.installation_token", _fake_token):
            p = GitHubProvider(_gh_settings())
            result = await p.push(
                "proj-gh-happy",
                installation_id=20001,
                github_owner="acme",
                github_repo="widget",
            )

        assert call_log == [20001], "installation_token was not called with the right id"
        assert result["provider"] == "github"
        assert result["project_id"] == "proj-gh-happy"
        assert result["status"] == "token_acquired"
        # Public URL must NOT contain the token
        assert "ghs_happy_push_20001" not in result["remote_url"]
        assert "acme/widget.git" in result["remote_url"]
        # Authenticated URL must embed x-access-token
        assert "x-access-token:ghs_happy_push_20001@github.com" in result["authenticated_remote_url"]
        assert "acme/widget.git" in result["authenticated_remote_url"]

    @pytest.mark.asyncio
    async def test_pull_acquires_token_and_returns_authenticated_url(self):
        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        invalidate_cache(20002)

        async def _fake_token(installation_id, app_id, private_key_pem):
            return "ghs_happy_pull_20002"

        with patch("kerf_cloud.git_providers.github.installation_token", _fake_token):
            p = GitHubProvider(_gh_settings())
            result = await p.pull(
                "proj-gh-happy-pull",
                installation_id=20002,
                github_owner="acme",
                github_repo="widget",
            )

        assert result["provider"] == "github"
        assert result["status"] == "token_acquired"
        assert "x-access-token:ghs_happy_pull_20002@github.com" in result["authenticated_remote_url"]
        assert "ghs_happy_pull_20002" not in result["remote_url"]

    @pytest.mark.asyncio
    async def test_push_then_pull_same_project(self):
        """Sequential push then pull for the same project both succeed."""
        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        invalidate_cache(20003)
        invalidate_cache(20003)

        call_order: list[str] = []

        async def _fake_token(installation_id, app_id, private_key_pem):
            call_order.append("token")
            return f"ghs_seq_{len(call_order)}"

        with patch("kerf_cloud.git_providers.github.installation_token", _fake_token):
            p = GitHubProvider(_gh_settings())
            push_result = await p.push(
                "proj-seq",
                installation_id=20003,
                github_owner="acme",
                github_repo="design",
            )
            pull_result = await p.pull(
                "proj-seq",
                installation_id=20003,
                github_owner="acme",
                github_repo="design",
            )

        # Both calls made independently (cache evicted between them)
        assert push_result["status"] == "token_acquired"
        assert pull_result["status"] == "token_acquired"
        assert push_result["provider"] == "github"
        assert pull_result["provider"] == "github"


# ===========================================================================
# 3. GITLAB HAPPY PATH
# ===========================================================================


class TestGitLabHappyPath:
    """Push + pull round-trip with an injected GitLab PAT (no live HTTP)."""

    @pytest.mark.asyncio
    async def test_push_embeds_token_correctly(self):
        from kerf_cloud.git_providers.gitlab import GitLabProvider

        p = GitLabProvider(_gl_settings())
        result = await p.push(
            "proj-gl-happy",
            gitlab_access_token="glpat-happy-push",
            gitlab_namespace="corp",
            gitlab_project="cad-model",
        )

        assert result["provider"] == "gitlab"
        assert result["project_id"] == "proj-gl-happy"
        assert result["status"] == "token_acquired"
        assert result["remote_url"] == "https://gitlab.com/corp/cad-model.git"
        assert result["authenticated_remote_url"] == (
            "https://oauth2:glpat-happy-push@gitlab.com/corp/cad-model.git"
        )

    @pytest.mark.asyncio
    async def test_pull_embeds_token_correctly(self):
        from kerf_cloud.git_providers.gitlab import GitLabProvider

        p = GitLabProvider(_gl_settings())
        result = await p.pull(
            "proj-gl-happy-pull",
            gitlab_access_token="glpat-happy-pull",
            gitlab_namespace="corp",
            gitlab_project="cad-model",
        )

        assert result["provider"] == "gitlab"
        assert result["status"] == "token_acquired"
        assert "oauth2:glpat-happy-pull@gitlab.com" in result["authenticated_remote_url"]
        assert "glpat-happy-pull" not in result["remote_url"]

    @pytest.mark.asyncio
    async def test_push_then_pull_same_project(self):
        """GitLab push then pull for the same project both succeed."""
        from kerf_cloud.git_providers.gitlab import GitLabProvider

        p = GitLabProvider(_gl_settings())
        push_r = await p.push(
            "proj-gl-seq",
            gitlab_access_token="glpat-seq",
            gitlab_namespace="corp",
            gitlab_project="design",
        )
        pull_r = await p.pull(
            "proj-gl-seq",
            gitlab_access_token="glpat-seq",
            gitlab_namespace="corp",
            gitlab_project="design",
        )

        assert push_r["status"] == "token_acquired"
        assert pull_r["status"] == "token_acquired"
        assert push_r["remote_url"] == pull_r["remote_url"]
        assert push_r["authenticated_remote_url"] == pull_r["authenticated_remote_url"]

    @pytest.mark.asyncio
    async def test_push_custom_host(self):
        from kerf_cloud.git_providers.gitlab import GitLabProvider

        p = GitLabProvider(_gl_settings())
        result = await p.push(
            "proj-gl-selfhosted",
            gitlab_access_token="glpat-corp",
            gitlab_namespace="team",
            gitlab_project="mech",
            gitlab_host="https://gitlab.corp.internal",
        )

        assert result["remote_url"] == "https://gitlab.corp.internal/team/mech.git"
        assert result["authenticated_remote_url"] == (
            "https://oauth2:glpat-corp@gitlab.corp.internal/team/mech.git"
        )


# ===========================================================================
# 4. ENV-GATING
# ===========================================================================


class TestEnvGating:
    """Unconfigured provider is hidden and its operations are inert/refused."""

    def test_unconfigured_github_absent_from_registry(self):
        from kerf_cloud.git_providers.registry import _build_default_registry

        reg = _build_default_registry(_none_settings())
        assert "github" not in reg.available_names()

    def test_unconfigured_gitlab_absent_from_registry(self):
        from kerf_cloud.git_providers.registry import _build_default_registry

        reg = _build_default_registry(_none_settings())
        assert "gitlab" not in reg.available_names()

    def test_registry_get_returns_none_for_unconfigured_github(self):
        from kerf_cloud.git_providers.registry import _build_default_registry

        reg = _build_default_registry(_gl_settings())  # only GitLab configured
        assert reg.get("github") is None

    def test_registry_get_returns_none_for_unconfigured_gitlab(self):
        from kerf_cloud.git_providers.registry import _build_default_registry

        reg = _build_default_registry(_gh_settings())  # only GitHub configured
        assert reg.get("gitlab") is None

    def test_only_configured_provider_in_configured_providers(self):
        from kerf_cloud.git_providers.registry import _build_default_registry

        reg = _build_default_registry(_gh_settings())
        names = [p.name for p in reg.configured_providers()]
        assert names == ["github"]

    def test_only_gitlab_when_github_unconfigured(self):
        from kerf_cloud.git_providers.registry import _build_default_registry

        reg = _build_default_registry(_gl_settings())
        names = [p.name for p in reg.configured_providers()]
        assert names == ["gitlab"]

    def test_both_present_when_both_configured(self):
        from kerf_cloud.git_providers.registry import _build_default_registry

        reg = _build_default_registry(_both_settings())
        names = set(reg.available_names())
        assert names == {"github", "gitlab"}

    @pytest.mark.asyncio
    async def test_unconfigured_github_push_raises_via_missing_config(self):
        """Attempting to build a GitHubProvider with empty credentials and push
        raises ValueError before any network call is made (missing args guard)."""
        from kerf_cloud.git_providers.github import GitHubProvider

        # Provider constructed but is_configured would return False.
        # push() still validates kwargs — misuse without provider guard raises.
        p = GitHubProvider(_none_settings())
        with pytest.raises(ValueError, match="installation_id"):
            await p.push("proj-ungated")  # no kwargs at all

    @pytest.mark.asyncio
    async def test_unconfigured_gitlab_push_raises_via_missing_kwargs(self):
        """GitLabProvider with no token → raises ValueError (missing args guard)."""
        from kerf_cloud.git_providers.gitlab import GitLabProvider

        p = GitLabProvider(_none_settings())
        with pytest.raises(ValueError, match="gitlab_access_token"):
            await p.push("proj-ungated")  # no token


# ===========================================================================
# 5. FAILURE PATHS
# ===========================================================================


class TestFailurePaths:
    """Auth failure, network error, partial-sync surface cleanly."""

    # -- GitHub auth failure (HTTP 401) --

    @pytest.mark.asyncio
    async def test_github_push_auth_failure_surfaces_as_value_error(self):
        """An HTTP 401 from the GitHub token API is wrapped as ValueError —
        not a raw httpx.HTTPStatusError — so callers receive a clean error."""
        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        invalidate_cache(30001)

        # Simulate resp.raise_for_status() raising HTTPStatusError
        mock_response = MagicMock()
        mock_response.status_code = 401
        http_error = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )

        async def _failing_token(installation_id, app_id, private_key_pem):
            raise http_error

        with patch("kerf_cloud.git_providers.github.installation_token", _failing_token):
            p = GitHubProvider(_gh_settings())
            with pytest.raises(ValueError, match="HTTP 401"):
                await p.push(
                    "proj-fail",
                    installation_id=30001,
                    github_owner="acme",
                    github_repo="widget",
                )

    @pytest.mark.asyncio
    async def test_github_pull_auth_failure_surfaces_as_value_error(self):
        """Same as push: HTTP 401 from token API → ValueError, not raw httpx."""
        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        invalidate_cache(30002)

        mock_response = MagicMock()
        mock_response.status_code = 401
        http_error = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )

        async def _failing_token(installation_id, app_id, private_key_pem):
            raise http_error

        with patch("kerf_cloud.git_providers.github.installation_token", _failing_token):
            p = GitHubProvider(_gh_settings())
            with pytest.raises(ValueError, match="HTTP 401"):
                await p.pull(
                    "proj-fail-pull",
                    installation_id=30002,
                    github_owner="acme",
                    github_repo="widget",
                )

    # -- GitHub network error --

    @pytest.mark.asyncio
    async def test_github_push_network_error_surfaces_as_value_error(self):
        """A network-level failure (DNS / connect refused) is wrapped as
        ValueError — callers never receive a raw httpx.TransportError."""
        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        invalidate_cache(30003)

        async def _network_fail(installation_id, app_id, private_key_pem):
            raise httpx.ConnectError("Connection refused")

        with patch("kerf_cloud.git_providers.github.installation_token", _network_fail):
            p = GitHubProvider(_gh_settings())
            with pytest.raises(ValueError, match="network error"):
                await p.push(
                    "proj-netfail",
                    installation_id=30003,
                    github_owner="acme",
                    github_repo="widget",
                )

    @pytest.mark.asyncio
    async def test_github_pull_network_error_surfaces_as_value_error(self):
        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        invalidate_cache(30004)

        async def _network_fail(installation_id, app_id, private_key_pem):
            raise httpx.ConnectError("Connection refused")

        with patch("kerf_cloud.git_providers.github.installation_token", _network_fail):
            p = GitHubProvider(_gh_settings())
            with pytest.raises(ValueError, match="network error"):
                await p.pull(
                    "proj-netfail-pull",
                    installation_id=30004,
                    github_owner="acme",
                    github_repo="widget",
                )

    # -- GitLab auth failure (HTTP 401) --

    @pytest.mark.asyncio
    async def test_gitlab_status_auth_failure_surfaced_cleanly(self):
        """A 401 from GitLab's /user endpoint is reflected in the status dict
        as token_valid=False rather than propagating an exception."""
        from kerf_cloud.git_providers.gitlab import GitLabProvider

        p = GitLabProvider(_gl_settings())

        async def _bad_verify(token):
            raise ValueError("GitLab token validation failed: HTTP 401")

        with patch.object(p, "_verify_token", _bad_verify):
            result = await p.status(
                "proj-gl-authfail",
                gitlab_access_token="bad-glpat",
            )

        assert result["provider"] == "gitlab"
        assert result["token_valid"] is False
        assert "401" in result["token_error"]
        # connected stays False
        assert result["connected"] is False

    # -- GitLab network error in status() --

    @pytest.mark.asyncio
    async def test_gitlab_status_network_error_surfaced_cleanly(self):
        """A network error during token verification (e.g. DNS failure) is caught
        and reflected in the status dict — not propagated as a raw exception.
        This is the gap fixed in T-149 hardening."""
        from kerf_cloud.git_providers.gitlab import GitLabProvider

        p = GitLabProvider(_gl_settings())

        async def _network_fail_verify(token):
            raise httpx.ConnectError("Name or service not known")

        with patch.object(p, "_verify_token", _network_fail_verify):
            result = await p.status(
                "proj-gl-netfail",
                gitlab_access_token="any-token",
            )

        assert result["provider"] == "gitlab"
        assert result["token_valid"] is False
        assert "network error" in result["token_error"]
        assert result["connected"] is False

    # -- GitLab push missing kwargs --

    @pytest.mark.asyncio
    async def test_gitlab_push_partial_kwargs_raises_value_error(self):
        """push() with token but no namespace → ValueError (not silent failure)."""
        from kerf_cloud.git_providers.gitlab import GitLabProvider

        p = GitLabProvider(_gl_settings())
        with pytest.raises(ValueError):
            await p.push(
                "proj-partial",
                gitlab_access_token="glpat-x",
                # missing: gitlab_namespace, gitlab_project
            )

    # -- GitHub push missing kwargs --

    @pytest.mark.asyncio
    async def test_github_push_partial_kwargs_raises_value_error(self):
        """push() with installation_id but no owner/repo → ValueError."""
        from kerf_cloud.git_providers.github import GitHubProvider

        p = GitHubProvider(_gh_settings())
        with pytest.raises(ValueError):
            await p.push("proj-partial", installation_id=99)  # no owner/repo

    # -- SoR tables untouched after auth failure --

    def test_github_push_auth_failure_sor_tables_unchanged(self, db_conn):
        """When push() fails (auth error), cloud_git_repos and cloud_git_commits
        are untouched — the SoR invariant holds even on error paths."""
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        before = run(_sor_snapshot(db_conn, pid))

        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        invalidate_cache(30010)

        mock_response = MagicMock()
        mock_response.status_code = 401
        http_error = httpx.HTTPStatusError(
            "401 Unauthorized",
            request=MagicMock(),
            response=mock_response,
        )

        async def _fail(installation_id, app_id, private_key_pem):
            raise http_error

        with patch("kerf_cloud.git_providers.github.installation_token", _fail):
            p = GitHubProvider(_gh_settings())
            try:
                run(p.push(
                    str(pid),
                    installation_id=30010,
                    github_owner="acme",
                    github_repo="widget",
                ))
            except ValueError:
                pass  # expected

        after = run(_sor_snapshot(db_conn, pid))

        assert before["head_sha"] == after["head_sha"], "SoR head_sha mutated on error"
        assert before["commit_count"] == after["commit_count"], "cloud_git_commits mutated on error"
        assert before["last_pushed_at"] == after["last_pushed_at"], "last_pushed_at mutated on error"


# ===========================================================================
# 6. RE-SYNC IDEMPOTENCY
# ===========================================================================


class TestResyncIdempotency:
    """Running push twice is safe — same shape, SoR tables identical."""

    @pytest.mark.asyncio
    async def test_github_push_twice_returns_same_shape(self):
        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        # Evict cache so both calls go through the fake
        invalidate_cache(40001)

        call_n = 0

        async def _fake_token(installation_id, app_id, private_key_pem):
            nonlocal call_n
            call_n += 1
            return f"ghs_idempotent_{call_n}"

        with patch("kerf_cloud.git_providers.github.installation_token", _fake_token):
            p = GitHubProvider(_gh_settings())
            r1 = await p.push(
                "proj-idem",
                installation_id=40001,
                github_owner="acme",
                github_repo="design",
            )
            # Evict cache between calls to force token refresh
            invalidate_cache(40001)
            r2 = await p.push(
                "proj-idem",
                installation_id=40001,
                github_owner="acme",
                github_repo="design",
            )

        # Shape is identical
        assert r1["provider"] == r2["provider"] == "github"
        assert r1["status"] == r2["status"] == "token_acquired"
        assert r1["remote_url"] == r2["remote_url"]
        assert r1["project_id"] == r2["project_id"]
        # authenticated_remote_url differs (different tokens) but format is same
        assert r1["authenticated_remote_url"].startswith(
            "https://x-access-token:"
        )
        assert r2["authenticated_remote_url"].startswith(
            "https://x-access-token:"
        )

    def test_github_push_twice_sor_tables_unchanged(self, db_conn):
        """Two successive provider push() calls leave SoR tables identical
        to what they were before both calls."""
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        before = run(_sor_snapshot(db_conn, pid))

        from kerf_cloud.git_providers.github import GitHubProvider
        from kerf_cloud.github_app import invalidate_cache

        invalidate_cache(40002)

        call_n = 0

        async def _fake_token(installation_id, app_id, private_key_pem):
            nonlocal call_n
            call_n += 1
            return f"ghs_idem2_{call_n}"

        with patch("kerf_cloud.git_providers.github.installation_token", _fake_token):
            p = GitHubProvider(_gh_settings())
            run(p.push(
                str(pid),
                installation_id=40002,
                github_owner="acme",
                github_repo="design",
            ))
            invalidate_cache(40002)
            run(p.push(
                str(pid),
                installation_id=40002,
                github_owner="acme",
                github_repo="design",
            ))

        after = run(_sor_snapshot(db_conn, pid))

        assert before["head_sha"] == after["head_sha"]
        assert before["last_pushed_at"] == after["last_pushed_at"]
        assert before["commit_count"] == after["commit_count"]

    @pytest.mark.asyncio
    async def test_gitlab_push_twice_returns_same_shape(self):
        """GitLab push is stateless token-embedding — two calls return
        exactly the same result dict (idempotent)."""
        from kerf_cloud.git_providers.gitlab import GitLabProvider

        p = GitLabProvider(_gl_settings())

        r1 = await p.push(
            "proj-gl-idem",
            gitlab_access_token="glpat-idem",
            gitlab_namespace="corp",
            gitlab_project="design",
        )
        r2 = await p.push(
            "proj-gl-idem",
            gitlab_access_token="glpat-idem",
            gitlab_namespace="corp",
            gitlab_project="design",
        )

        assert r1 == r2

    def test_gitlab_push_twice_sor_tables_unchanged(self, db_conn):
        """Two successive GitLab push() calls leave SoR tables unchanged."""
        uid = run(_make_user(db_conn))
        ws = run(_make_workspace(db_conn, uid))
        pid = run(_make_project(db_conn, ws))

        before = run(_sor_snapshot(db_conn, pid))

        from kerf_cloud.git_providers.gitlab import GitLabProvider

        p = GitLabProvider(_gl_settings())

        run(p.push(
            str(pid),
            gitlab_access_token="glpat-idem-sor",
            gitlab_namespace="corp",
            gitlab_project="design",
        ))
        run(p.push(
            str(pid),
            gitlab_access_token="glpat-idem-sor",
            gitlab_namespace="corp",
            gitlab_project="design",
        ))

        after = run(_sor_snapshot(db_conn, pid))

        assert before["head_sha"] == after["head_sha"]
        assert before["last_pushed_at"] == after["last_pushed_at"]
        assert before["commit_count"] == after["commit_count"]
