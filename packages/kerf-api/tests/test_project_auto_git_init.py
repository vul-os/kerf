"""Regression: every new project must be auto-initialised as a git repo.

Bug: a project was created via POST /api/projects but the cloud git repo
was only initialised when the user manually clicked "Init" in the git
panel. New users never saw git history without that manual step.

Fix: create_project calls ensure_git_repo when settings.cloud_enabled=True
(fire-and-forget; failure is logged WARNING but does NOT block creation).
Local-only installs skip this entirely.

Tests pin:
1. cloud_enabled=True  → ensure_git_repo is called with the new project id.
2. cloud_enabled=False → ensure_git_repo is NOT called.
3. ensure_git_repo raising → project creation still succeeds (non-fatal).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from kerf_api.routes import CreateProjectRequest, create_project


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _Tx:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *a):
        return False


def _conn():
    c = AsyncMock()
    c.fetchrow = AsyncMock(return_value={"name": "User", "email": "u@x.com"})
    c.transaction = MagicMock(return_value=_Tx())
    return c


def _pool(conn):
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _base_patches(*, cloud_enabled: bool, ensure_git_repo_side_effect=None):
    """Return (patch list, captured dict) for create_project tests."""
    conn = _conn()
    projects_q = MagicMock()
    projects_q.create_project = AsyncMock(return_value={"id": "proj-new", "name": "Test"})
    files_q = MagicMock()
    files_q.create_file = AsyncMock()
    fake_settings = MagicMock()
    fake_settings.cloud_enabled = cloud_enabled

    ensure_git = AsyncMock(side_effect=ensure_git_repo_side_effect)

    cms = [
        patch("kerf_api.routes.get_pool_required", AsyncMock(return_value=_pool(conn))),
        patch("kerf_api.routes.get_default_workspace", AsyncMock(return_value=({"id": "ws-1"}, True))),
        patch("kerf_api.routes.get_user_workspace_role", AsyncMock(return_value="owner")),
        patch("kerf_api.routes.get_workspace_by_slug", AsyncMock(return_value=None)),
        patch("kerf_api.routes.projects_queries", projects_q),
        patch("kerf_api.routes.files_queries", files_q),
        patch("kerf_api.routes.settings", fake_settings),
        # Patch the lazy import path used inside create_project
        patch("kerf_cloud.routes.ensure_git_repo", ensure_git),
    ]
    return cms, {"ensure_git": ensure_git, "projects_q": projects_q}


def _call(req):
    return _run(create_project(req, payload={"sub": "user-1"}))


def test_auto_git_init_called_when_cloud_enabled():
    cms, cap = _base_patches(cloud_enabled=True)
    for cm in cms:
        cm.start()
    try:
        result = _call(CreateProjectRequest(name="Cloud Project"))
    finally:
        for cm in reversed(cms):
            cm.stop()

    assert result["id"] == "proj-new"
    cap["ensure_git"].assert_awaited_once()
    call_args = cap["ensure_git"].call_args
    # Second positional arg is the project_id
    assert call_args.args[1] == "proj-new" or str(call_args.args[1]) == "proj-new"


def test_auto_git_init_skipped_when_cloud_disabled():
    cms, cap = _base_patches(cloud_enabled=False)
    for cm in cms:
        cm.start()
    try:
        result = _call(CreateProjectRequest(name="Local Project"))
    finally:
        for cm in reversed(cms):
            cm.stop()

    assert result["id"] == "proj-new"
    cap["ensure_git"].assert_not_awaited()


def test_auto_git_init_failure_does_not_block_project_creation():
    cms, cap = _base_patches(
        cloud_enabled=True,
        ensure_git_repo_side_effect=RuntimeError("git backend unavailable"),
    )
    for cm in cms:
        cm.start()
    try:
        result = _call(CreateProjectRequest(name="Resilient Project"))
    finally:
        for cm in reversed(cms):
            cm.stop()

    # Project creation must succeed despite the git init failure
    assert result["id"] == "proj-new"
    cap["ensure_git"].assert_awaited_once()
