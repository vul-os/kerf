"""Workshop slice 1: a project README.md file overrides the DB readme.

Files-in-repo = source of truth (GitHub-style); the auto-generated
thumbnail/cover stay the default. Resolved on the detail path only.
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from kerf_api.routes import workshop_get

_PID = str(uuid.uuid4())


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _project(readme_col):
    return {
        "id": _PID, "name": "Proj", "description": "",
        "tags": [], "workspace_slug": "w", "workspace_name": "W",
        "author_id": None, "author_name": "", "author_avatar_url": None,
        "readme": readme_col, "thumbnail_storage_key": None,
        "cover_storage_key": None, "created_at": None, "updated_at": None,
    }


def _call(readme_col, readme_file_content):
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(
        return_value=({"content": readme_file_content}
                      if readme_file_content is not None else None)
    )
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    proj = _project(readme_col)
    cms = [
        patch("kerf_api.routes.get_pool_required", AsyncMock(return_value=pool)),
        patch("kerf_api.routes.projects_queries.get_public_project",
              AsyncMock(return_value=proj)),
        patch("kerf_api.routes._enrich_with_primary_images",
              AsyncMock(return_value=[proj])),
    ]
    for cm in cms:
        cm.start()
    try:
        return _run(workshop_get(_PID, auth=None))
    finally:
        for cm in reversed(cms):
            cm.stop()


def test_readme_file_overrides_db_column():
    out = _call(readme_col="DB readme", readme_file_content="# From repo file")
    assert out["readme"] == "# From repo file"


def test_falls_back_to_db_readme_when_no_file():
    out = _call(readme_col="DB readme", readme_file_content=None)
    assert out["readme"] == "DB readme"


def test_blank_readme_file_does_not_override():
    out = _call(readme_col="DB readme", readme_file_content="   \n  ")
    assert out["readme"] == "DB readme"
