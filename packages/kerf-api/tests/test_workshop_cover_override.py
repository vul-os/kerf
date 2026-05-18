"""Slice 4: a repo cover.* file overrides the auto-generated cover.

Files-in-repo = source of truth (GitHub-style). The generated cover
stays the DEFAULT; a project file named cover.{png,jpg,...} overrides
it. Resolved on the detail path so _project_to_workshop_row emits the
/cover URL even when no auto cover was ever generated.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from kerf_api.routes import workshop_get

_PID = str(uuid.uuid4())


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _project(cover_col):
    return {
        "id": _PID, "name": "Proj", "description": "",
        "tags": [], "workspace_slug": "w", "workspace_name": "W",
        "author_id": None, "author_name": "", "author_avatar_url": None,
        "readme": None, "thumbnail_storage_key": None,
        "cover_storage_key": cover_col, "created_at": None, "updated_at": None,
    }


def _call(cover_col, readme_file, cover_file):
    conn = AsyncMock()
    # workshop_get: fetchrow(readme) always; fetchrow(cover) only when
    # there is no generated cover_storage_key.
    conn.fetchrow = AsyncMock(side_effect=[readme_file, cover_file])
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    proj = _project(cover_col)
    cms = [
        patch("kerf_api.routes.get_pool_required", AsyncMock(return_value=pool)),
        patch("kerf_api.routes.projects_queries.get_public_project",
              AsyncMock(return_value=proj)),
        patch("kerf_api.routes._attach_workshop_media", AsyncMock(return_value=None)),
    ]
    for cm in cms:
        cm.start()
    try:
        return _run(workshop_get(_PID, auth=None))
    finally:
        for cm in reversed(cms):
            cm.stop()


def test_cover_file_surfaces_when_no_generated_cover():
    out = _call(cover_col=None, readme_file=None,
                cover_file={"storage_key": "blob/cover-key"})
    assert out["cover_storage_key"] == "blob/cover-key"
    assert out["cover_url"] == f"/api/projects/{_PID}/cover"


def test_no_cover_file_falls_back_to_thumbnail_url():
    out = _call(cover_col=None, readme_file=None, cover_file=None)
    assert out["cover_storage_key"] is None
    # No generated cover + no override + no thumbnail → cover_url is the
    # (None) thumbnail_url, never a broken /cover link.
    assert out["cover_url"] == out["thumbnail_url"]


def test_generated_cover_still_emits_cover_url_without_override_lookup():
    # cover_storage_key already set → the override branch is skipped, so
    # only the README fetchrow runs (side_effect has just one entry).
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(side_effect=[None])
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    proj = _project("auto/generated-cover")
    cms = [
        patch("kerf_api.routes.get_pool_required", AsyncMock(return_value=pool)),
        patch("kerf_api.routes.projects_queries.get_public_project",
              AsyncMock(return_value=proj)),
        patch("kerf_api.routes._attach_workshop_media", AsyncMock(return_value=None)),
    ]
    for cm in cms:
        cm.start()
    try:
        out = _run(workshop_get(_PID, auth=None))
    finally:
        for cm in reversed(cms):
            cm.stop()
    assert out["cover_url"] == f"/api/projects/{_PID}/cover"
    assert conn.fetchrow.await_count == 1  # cover lookup skipped
