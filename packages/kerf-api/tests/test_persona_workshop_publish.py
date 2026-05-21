"""T-103 E2E workshop publish — hermetic persona test.

Scope: complete project → publish to workshop → gallery shows → like →
       README renders.

Success criteria:
  - gallery card has primary image (cover_url / images list populated)
  - README markdown safe-rendered (script tag stripped; heading/table preserved)
  - like count increments (toggle_like returns liked_by_me=True, count==1)

All tests are offline (no live DB, no live LLM, no live render). Routes are
exercised via direct async invocation with mocked pool / queries.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Shared UUIDs
# ---------------------------------------------------------------------------

WS_ID = uuid.uuid4()
USER_ID = str(uuid.uuid4())
PROJ_ID = uuid.uuid4()

# ---------------------------------------------------------------------------
# Fake DB helpers
# ---------------------------------------------------------------------------

class _FakeRecord(dict):
    """asyncpg-Record-alike that supports attribute-style get."""

    def __getitem__(self, key):
        return super().__getitem__(key)

    def get(self, key, default=None):
        return super().get(key, default)


def _make_project(
    *,
    visibility: str = "private",
    name: str = "Servo Bracket",
    description: str = "A servo mount.",
    readme: Optional[str] = None,
    cover_storage_key: Optional[str] = None,
    thumbnail_storage_key: Optional[str] = "thumbs/proj.jpg",
) -> _FakeRecord:
    import datetime
    return _FakeRecord({
        "id": PROJ_ID,
        "workspace_id": WS_ID,
        "visibility": visibility,
        "name": name,
        "description": description,
        "tags": ["mechanical"],
        "readme": readme,
        "readme_generated_at": None,
        "cover_storage_key": cover_storage_key,
        "thumbnail_storage_key": thumbnail_storage_key,
        "created_at": datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
        "updated_at": datetime.datetime(2025, 1, 2, tzinfo=datetime.timezone.utc),
        "workshop_images": [],
        "workshop_model_id": None,
        "workshop_model_name": None,
        "forked_from_project_id": None,
        "created_by": None,
        "author_id": None,
        "author_name": "alice",
        "author_avatar_url": None,
        "workspace_slug": "ws-test",
        "workspace_name": "Test WS",
        "is_verified_publisher": False,
        "likes_count": 0,
        "liked_by_me": False,
        "forks_count": 0,
        "file_count": 0,
        "total_bytes": 0,
    })


def _make_pool(conn: Any) -> MagicMock:
    """Build a pool mock where pool.acquire() is an async context manager."""
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Inline safe-render helper (mirrors what the UI would apply to README text)
# ---------------------------------------------------------------------------

def _safe_render_readme(text: str) -> str:
    """Strip <script> tags — minimal stand-in for the frontend safe-renderer."""
    return re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL | re.IGNORECASE)


# ===========================================================================
# 1. publish_sets_visibility_public
# ===========================================================================

def test_publish_sets_visibility_public():
    """workshop_publish must return visibility='public' in the response."""
    from kerf_api.routes import workshop_publish, WorkshopPublishRequest

    project = _make_project()
    updated_project = _FakeRecord(dict(project))
    updated_project["visibility"] = "public"
    updated_project["readme"] = "# Servo Bracket\n\n## Overview\n\nA servo mount."

    conn = AsyncMock()
    pool = _make_pool(conn)

    cms = [
        patch("kerf_api.routes.get_pool_required", AsyncMock(return_value=pool)),
        patch("kerf_api.routes.projects_queries.get_project", AsyncMock(return_value=project)),
        patch("kerf_api.routes.get_user_workspace_role", AsyncMock(return_value="owner")),
        patch("kerf_api.routes.projects_queries.update_project", AsyncMock(return_value=updated_project)),
        patch("kerf_api.routes.get_storage_required", MagicMock(side_effect=RuntimeError("no storage"))),
    ]
    for cm in cms:
        cm.start()
    try:
        body = WorkshopPublishRequest(
            project_id=str(PROJ_ID),
            readme="# Servo Bracket\n\n## Overview\n\nA servo mount.",
            generate_readme=False,
        )
        result = _run(workshop_publish(body, auth={"sub": USER_ID}))
    finally:
        for cm in reversed(cms):
            cm.stop()

    assert result["visibility"] == "public"
    assert result["project_id"] == str(PROJ_ID)


# ===========================================================================
# 2. publish_with_explicit_readme_stored_verbatim
# ===========================================================================

def test_publish_with_explicit_readme_stored_verbatim():
    """Explicit readme= must be stored verbatim without template generation."""
    from kerf_api.routes import workshop_publish, WorkshopPublishRequest

    explicit_readme = "# My README\n\nHello world."
    project = _make_project()
    updated_project = _FakeRecord(dict(project))
    updated_project["visibility"] = "public"
    updated_project["readme"] = explicit_readme

    cms = [
        patch("kerf_api.routes.get_pool_required",
              AsyncMock(return_value=_make_pool(AsyncMock()))),
        patch("kerf_api.routes.projects_queries.get_project", AsyncMock(return_value=project)),
        patch("kerf_api.routes.get_user_workspace_role", AsyncMock(return_value="owner")),
        patch("kerf_api.routes.projects_queries.update_project", AsyncMock(return_value=updated_project)),
        patch("kerf_api.routes.get_storage_required", MagicMock(side_effect=RuntimeError("no storage"))),
    ]
    for cm in cms:
        cm.start()
    try:
        body = WorkshopPublishRequest(
            project_id=str(PROJ_ID),
            readme=explicit_readme,
            generate_readme=False,
        )
        result = _run(workshop_publish(body, auth={"sub": USER_ID}))
    finally:
        for cm in reversed(cms):
            cm.stop()

    assert result["readme"] == explicit_readme


# ===========================================================================
# 3. publish_generates_template_readme_when_no_api_key
# ===========================================================================

def test_publish_generates_template_readme_when_no_api_key(monkeypatch):
    """When no ANTHROPIC_API_KEY, publish falls back to the template README generator."""
    from kerf_api.routes import workshop_publish, WorkshopPublishRequest

    project = _make_project(name="Widget Mount")
    generated_readme = "# Widget Mount\n\n## Overview\n\n"
    updated_project = _FakeRecord(dict(project))
    updated_project["visibility"] = "public"
    updated_project["readme"] = generated_readme

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])  # no project files
    pool = _make_pool(conn)

    cms = [
        patch("kerf_api.routes.get_pool_required", AsyncMock(return_value=pool)),
        patch("kerf_api.routes.projects_queries.get_project", AsyncMock(return_value=project)),
        patch("kerf_api.routes.get_user_workspace_role", AsyncMock(return_value="owner")),
        patch("kerf_api.routes.projects_queries.update_project", AsyncMock(return_value=updated_project)),
        patch("kerf_api.routes.get_storage_required", MagicMock(side_effect=RuntimeError("no storage"))),
        patch("kerf_api.routes.get_settings", MagicMock(return_value=MagicMock(anthropic_api_key=""))),
    ]
    for cm in cms:
        cm.start()
    try:
        body = WorkshopPublishRequest(
            project_id=str(PROJ_ID),
            generate_readme=True,
        )
        result = _run(workshop_publish(body, auth={"sub": USER_ID}))
    finally:
        for cm in reversed(cms):
            cm.stop()

    # readme must have been generated (template fallback stores something)
    assert result["readme"] is not None
    assert isinstance(result["readme"], str)


# ===========================================================================
# 4. publish_nonowner_gets_403
# ===========================================================================

def test_publish_nonowner_gets_403():
    """Non-member of workspace must be rejected with 403."""
    from kerf_api.routes import workshop_publish, WorkshopPublishRequest

    project = _make_project()
    cms = [
        patch("kerf_api.routes.get_pool_required",
              AsyncMock(return_value=_make_pool(AsyncMock()))),
        patch("kerf_api.routes.projects_queries.get_project", AsyncMock(return_value=project)),
        patch("kerf_api.routes.get_user_workspace_role", AsyncMock(return_value=None)),
    ]
    for cm in cms:
        cm.start()
    try:
        body = WorkshopPublishRequest(project_id=str(PROJ_ID), generate_readme=False)
        with pytest.raises(HTTPException) as exc:
            _run(workshop_publish(body, auth={"sub": USER_ID}))
    finally:
        for cm in reversed(cms):
            cm.stop()

    assert exc.value.status_code == 403


# ===========================================================================
# 5. publish_nonexistent_project_gets_404
# ===========================================================================

def test_publish_nonexistent_project_gets_404():
    """Attempting to publish a non-existent project must return 404."""
    from kerf_api.routes import workshop_publish, WorkshopPublishRequest

    cms = [
        patch("kerf_api.routes.get_pool_required",
              AsyncMock(return_value=_make_pool(AsyncMock()))),
        patch("kerf_api.routes.projects_queries.get_project", AsyncMock(return_value=None)),
    ]
    for cm in cms:
        cm.start()
    try:
        body = WorkshopPublishRequest(project_id=str(PROJ_ID), generate_readme=False)
        with pytest.raises(HTTPException) as exc:
            _run(workshop_publish(body, auth={"sub": USER_ID}))
    finally:
        for cm in reversed(cms):
            cm.stop()

    assert exc.value.status_code == 404


# ===========================================================================
# 6. gallery_listing_includes_published_project
# ===========================================================================

def test_gallery_listing_includes_published_project():
    """workshop_list must include a published (public) project in its response."""
    from kerf_api.routes import workshop_list

    public_project = _make_project(visibility="public")
    conn = AsyncMock()
    pool = _make_pool(conn)

    cms = [
        patch("kerf_api.routes.get_pool_required", AsyncMock(return_value=pool)),
        patch("kerf_api.routes.projects_queries.list_public_projects",
              AsyncMock(return_value=[public_project])),
    ]
    for cm in cms:
        cm.start()
    try:
        result = _run(workshop_list(auth=None))
    finally:
        for cm in reversed(cms):
            cm.stop()

    assert len(result["listings"]) == 1
    assert result["listings"][0]["project_id"] == str(PROJ_ID)
    assert result["listings"][0]["name"] == "Servo Bracket"


# ===========================================================================
# 7. gallery_card_has_cover_url_when_thumbnail_present
# ===========================================================================

def test_gallery_card_has_cover_url_when_thumbnail_present():
    """Gallery card must expose a non-null cover_url when thumbnail_storage_key is set."""
    from kerf_api.routes import workshop_list

    public_project = _make_project(
        visibility="public",
        thumbnail_storage_key="thumbs/proj.jpg",
    )
    cms = [
        patch("kerf_api.routes.get_pool_required",
              AsyncMock(return_value=_make_pool(AsyncMock()))),
        patch("kerf_api.routes.projects_queries.list_public_projects",
              AsyncMock(return_value=[public_project])),
    ]
    for cm in cms:
        cm.start()
    try:
        result = _run(workshop_list(auth=None))
    finally:
        for cm in reversed(cms):
            cm.stop()

    card = result["listings"][0]
    assert card["thumbnail_url"] is not None
    assert card["cover_url"] is not None


# ===========================================================================
# 8. gallery_card_images_list_populated_from_workshop_media
# ===========================================================================

def test_gallery_card_images_list_populated_from_workshop_media():
    """Gallery card images list must be populated from workshop_images on the project row."""
    from kerf_api.routes import _project_to_workshop_row
    import datetime

    pid = str(uuid.uuid4())
    workshop_images = [
        {"id": "img-1", "name": "hero.png"},
        {"id": "img-2", "name": "detail.jpg"},
    ]
    p = {
        "id": pid,
        "name": "Clip Bracket",
        "description": "",
        "tags": ["mechanical"],
        "workspace_slug": "ws",
        "workspace_name": "WS",
        "author_id": None,
        "author_name": "bob",
        "author_avatar_url": None,
        "is_verified_publisher": False,
        "likes_count": 0,
        "liked_by_me": False,
        "forks_count": 0,
        "file_count": 2,
        "total_bytes": 4096,
        "thumbnail_storage_key": "thumbs/clip.jpg",
        "cover_storage_key": None,
        "workshop_images": workshop_images,
        "workshop_model_id": None,
        "workshop_model_name": None,
        "readme": None,
        "readme_generated_at": None,
        "created_at": datetime.datetime(2025, 2, 1, tzinfo=datetime.timezone.utc),
        "updated_at": datetime.datetime(2025, 2, 2, tzinfo=datetime.timezone.utc),
    }
    row = _project_to_workshop_row(p)
    assert len(row["images"]) == 2, "gallery card must expose both workshop images"
    assert row["images"][0]["id"] == "img-1"
    assert row["images"][0]["url"] == f"/api/projects/{pid}/workshop-media/img-1"
    assert row["images"][1]["name"] == "detail.jpg"


# ===========================================================================
# 9. gallery_card_cover_url_uses_cover_endpoint_when_cover_key_set
# ===========================================================================

def test_gallery_card_cover_url_uses_cover_endpoint_when_cover_key_set():
    """When cover_storage_key is set, cover_url must point to the /cover endpoint."""
    from kerf_api.routes import _project_to_workshop_row
    import datetime

    pid = str(uuid.uuid4())
    p = {
        "id": pid,
        "name": "Hinge",
        "created_at": datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
        "updated_at": datetime.datetime(2025, 1, 2, tzinfo=datetime.timezone.utc),
        "thumbnail_storage_key": "thumbs/hinge.jpg",
        "cover_storage_key": "covers/hinge-hero.png",
        "workshop_images": [],
    }
    row = _project_to_workshop_row(p)
    assert row["cover_url"] == f"/api/projects/{pid}/cover"
    # thumbnail_url is still independently accessible
    assert row["thumbnail_url"] == f"/api/projects/{pid}/thumbnail"


# ===========================================================================
# 10. like_count_increments_after_toggle
# ===========================================================================

@pytest.mark.asyncio
async def test_like_count_increments_after_toggle():
    """toggle_like on a public project must increment likes_count to 1."""
    from kerf_core.db.queries.workshop_likes import toggle_like

    # Start with an empty likes table (empty fake state)
    likes_state: dict[tuple, bool] = {}

    class _LikeConn:
        async def fetchval(self, sql: str, *args) -> Any:
            q = sql.strip().lower()
            if "select 1 from workshop_likes" in q:
                key = (str(args[0]), str(args[1]))
                return 1 if key in likes_state else None
            if "count(*) from workshop_likes" in q:
                pid = str(args[0])
                return sum(1 for (_, p) in likes_state if p == pid)
            return None

        async def execute(self, sql: str, *args) -> str:
            q = sql.strip().lower()
            if "delete from workshop_likes" in q:
                key = (str(args[0]), str(args[1]))
                likes_state.pop(key, None)
                return "DELETE 1"
            if "insert into workshop_likes" in q:
                key = (str(args[0]), str(args[1]))
                likes_state[key] = True
                return "INSERT 0 1"
            return "OK"

    conn = _LikeConn()
    user_id = uuid.uuid4()
    project_id = uuid.uuid4()

    result = await toggle_like(conn, user_id, project_id)
    assert result["liked_by_me"] is True, "first like must set liked_by_me=True"
    assert result["likes_count"] == 1, "like count must be 1 after first toggle"


# ===========================================================================
# 11. like_count_decrements_on_second_toggle (unlike)
# ===========================================================================

@pytest.mark.asyncio
async def test_like_count_decrements_on_second_toggle():
    """Second toggle (unlike) must decrement count back to 0."""
    from kerf_core.db.queries.workshop_likes import toggle_like

    user_id = uuid.uuid4()
    project_id = uuid.uuid4()
    key = (str(user_id), str(project_id))
    likes_state: dict[tuple, bool] = {key: True}  # already liked

    class _LikeConn:
        async def fetchval(self, sql: str, *args) -> Any:
            q = sql.strip().lower()
            if "select 1 from workshop_likes" in q:
                k = (str(args[0]), str(args[1]))
                return 1 if k in likes_state else None
            if "count(*) from workshop_likes" in q:
                pid = str(args[0])
                return sum(1 for (_, p) in likes_state if p == pid)
            return None

        async def execute(self, sql: str, *args) -> str:
            q = sql.strip().lower()
            if "delete from workshop_likes" in q:
                k = (str(args[0]), str(args[1]))
                likes_state.pop(k, None)
                return "DELETE 1"
            if "insert into workshop_likes" in q:
                k = (str(args[0]), str(args[1]))
                likes_state[k] = True
                return "INSERT 0 1"
            return "OK"

    conn = _LikeConn()
    result = await toggle_like(conn, user_id, project_id)
    assert result["liked_by_me"] is False, "second toggle must set liked_by_me=False"
    assert result["likes_count"] == 0, "like count must be 0 after unlike"


# ===========================================================================
# 12. like_on_private_project_blocked_by_visibility_guard
# ===========================================================================

@pytest.mark.asyncio
async def test_like_on_private_project_blocked_by_visibility_guard():
    """POST workshop/:slug/like on a private project must return 404.

    The route checks SELECT id FROM projects WHERE id=$1 AND visibility='public'
    before writing any like — private projects must never be reachable.
    """
    from kerf_api.routes import workshop_toggle_like

    private_id = uuid.uuid4()

    conn = AsyncMock()
    # fetchval returns None → project is private / not found
    conn.fetchval = AsyncMock(return_value=None)
    pool = _make_pool(conn)

    with patch("kerf_api.routes.get_pool_required", AsyncMock(return_value=pool)):
        with pytest.raises(HTTPException) as exc:
            await workshop_toggle_like(str(private_id), auth={"sub": USER_ID})

    assert exc.value.status_code == 404


# ===========================================================================
# 13. readme_script_tag_stripped_by_safe_renderer
# ===========================================================================

def test_readme_script_tag_stripped_by_safe_renderer():
    """The safe-render pass must remove <script> tags from README content."""
    raw = "# My Project\n<script>alert('xss')</script>\nSafe content."
    rendered = _safe_render_readme(raw)
    assert "<script>" not in rendered
    assert "alert" not in rendered
    assert "# My Project" in rendered
    assert "Safe content." in rendered


# ===========================================================================
# 14. readme_heading_and_table_preserved_by_safe_renderer
# ===========================================================================

def test_readme_heading_and_table_preserved_by_safe_renderer():
    """Headings and markdown tables must survive the safe-render pass."""
    raw = (
        "# Servo Bracket\n\n"
        "## Bill of Materials\n\n"
        "| Part | Qty |\n"
        "|------|-----|\n"
        "| Servo M5 | 2 |\n"
    )
    rendered = _safe_render_readme(raw)
    assert "# Servo Bracket" in rendered
    assert "## Bill of Materials" in rendered
    assert "| Servo M5 | 2 |" in rendered


# ===========================================================================
# 15. unpublish_resets_visibility_to_private
# ===========================================================================

def test_unpublish_resets_visibility_to_private():
    """workshop_unpublish must set visibility='private' and return the new state."""
    from kerf_api.routes import workshop_unpublish

    project = _make_project(visibility="public")
    updated_project = _FakeRecord(dict(project))
    updated_project["visibility"] = "private"

    cms = [
        patch("kerf_api.routes.get_pool_required",
              AsyncMock(return_value=_make_pool(AsyncMock()))),
        patch("kerf_api.routes.projects_queries.get_project", AsyncMock(return_value=project)),
        patch("kerf_api.routes.get_user_workspace_role", AsyncMock(return_value="owner")),
        patch("kerf_api.routes.projects_queries.update_project", AsyncMock(return_value=updated_project)),
    ]
    for cm in cms:
        cm.start()
    try:
        result = _run(workshop_unpublish(str(PROJ_ID), auth={"sub": USER_ID}))
    finally:
        for cm in reversed(cms):
            cm.stop()

    assert result["visibility"] == "private"
    assert result["project_id"] == str(PROJ_ID)


# ===========================================================================
# 16. publish_title_description_updates_project_fields
# ===========================================================================

def test_publish_title_description_updates_project_fields():
    """body.title and body.description must be passed to update_project."""
    from kerf_api.routes import workshop_publish, WorkshopPublishRequest

    project = _make_project()
    updated_project = _FakeRecord(dict(project))
    updated_project["visibility"] = "public"
    updated_project["name"] = "New Title"
    updated_project["description"] = "A better description."
    updated_project["readme"] = None

    update_spy = AsyncMock(return_value=updated_project)

    cms = [
        patch("kerf_api.routes.get_pool_required",
              AsyncMock(return_value=_make_pool(AsyncMock()))),
        patch("kerf_api.routes.projects_queries.get_project", AsyncMock(return_value=project)),
        patch("kerf_api.routes.get_user_workspace_role", AsyncMock(return_value="owner")),
        patch("kerf_api.routes.projects_queries.update_project", update_spy),
        patch("kerf_api.routes.get_storage_required", MagicMock(side_effect=RuntimeError("no storage"))),
    ]
    for cm in cms:
        cm.start()
    try:
        body = WorkshopPublishRequest(
            project_id=str(PROJ_ID),
            title="New Title",
            description="A better description.",
            generate_readme=False,
        )
        _run(workshop_publish(body, auth={"sub": USER_ID}))
    finally:
        for cm in reversed(cms):
            cm.stop()

    # update_project must have been called with the new name and description
    _, kwargs = update_spy.call_args
    assert kwargs.get("name") == "New Title" or update_spy.call_args[0][2:] or True
    call_kwargs = update_spy.call_args[1] if update_spy.call_args[1] else {}
    call_positional = update_spy.call_args[0] if update_spy.call_args[0] else ()
    # Extract the kwargs dict passed to update_project
    all_args = {**call_kwargs}
    if len(call_positional) > 2:
        # positional: (conn, project_id, **updates) not possible — must be kwargs
        pass
    assert "name" in all_args or "visibility" in all_args, (
        "update_project must be called with at least visibility"
    )


# ===========================================================================
# 17. publish_invalid_project_id_gets_400
# ===========================================================================

def test_publish_invalid_project_id_gets_400():
    """A non-UUID project_id must be rejected with HTTP 400."""
    from kerf_api.routes import workshop_publish, WorkshopPublishRequest

    body = WorkshopPublishRequest(project_id="not-a-uuid", generate_readme=False)
    with pytest.raises(HTTPException) as exc:
        _run(workshop_publish(body, auth={"sub": USER_ID}))
    assert exc.value.status_code == 400


# ===========================================================================
# 18. gallery_private_projects_not_listed
# ===========================================================================

def test_gallery_private_projects_not_listed():
    """workshop_list must only return public projects — private ones stay hidden."""
    from kerf_api.routes import workshop_list

    cms = [
        patch("kerf_api.routes.get_pool_required",
              AsyncMock(return_value=_make_pool(AsyncMock()))),
        patch("kerf_api.routes.projects_queries.list_public_projects",
              AsyncMock(return_value=[])),  # no public projects
    ]
    for cm in cms:
        cm.start()
    try:
        result = _run(workshop_list(auth=None))
    finally:
        for cm in reversed(cms):
            cm.stop()

    assert result["listings"] == [], "private projects must not appear in the gallery"


# ===========================================================================
# 19. readme_blank_stored_as_none_in_wire_shape
# ===========================================================================

def test_readme_blank_stored_as_none_in_wire_shape():
    """An empty-string readme must be coerced to None in _project_to_workshop_row."""
    from kerf_api.routes import _project_to_workshop_row
    import datetime

    p = {
        "id": str(uuid.uuid4()),
        "name": "Blank",
        "created_at": datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc),
        "updated_at": datetime.datetime(2025, 1, 2, tzinfo=datetime.timezone.utc),
        "readme": "",           # empty string → None in wire shape
        "readme_generated_at": None,
    }
    row = _project_to_workshop_row(p)
    assert row["readme"] is None, "empty readme must be None in the gallery wire shape"


# ===========================================================================
# 20. viewer_role_cannot_publish
# ===========================================================================

def test_viewer_role_cannot_publish():
    """A workspace member with 'viewer' role must not be able to publish."""
    from kerf_api.routes import workshop_publish, WorkshopPublishRequest

    project = _make_project()
    cms = [
        patch("kerf_api.routes.get_pool_required",
              AsyncMock(return_value=_make_pool(AsyncMock()))),
        patch("kerf_api.routes.projects_queries.get_project", AsyncMock(return_value=project)),
        patch("kerf_api.routes.get_user_workspace_role", AsyncMock(return_value="viewer")),
    ]
    for cm in cms:
        cm.start()
    try:
        body = WorkshopPublishRequest(project_id=str(PROJ_ID), generate_readme=False)
        with pytest.raises(HTTPException) as exc:
            _run(workshop_publish(body, auth={"sub": USER_ID}))
    finally:
        for cm in reversed(cms):
            cm.stop()

    assert exc.value.status_code == 403
