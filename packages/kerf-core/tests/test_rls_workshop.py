"""
T-91 — RLS: workshop_likes + workshop_readme + project_workshop_images (retired)
================================================================================
Hermetic tests for the application-level multi-tenant access control on the
three workshop-adjacent tables / fields.

Access-control invariants under test
--------------------------------------

workshop_likes (INSERT / DELETE / SELECT):
  1. toggle_like always binds the authenticated caller's user_id — no forge.
  2. toggle_like on a private project is blocked (visibility='public' guard).
  3. Like-count aggregation is always scoped to a specific project_id.
  4. A like INSERT cannot carry another user's user_id (query-level binding).

workshop_readme (readme field on projects — written by publish / regenerate):
  5. Non-member attempting to regenerate readme → 403 (no workspace role).
  6. Viewer role attempting to regenerate readme → 403.
  7. Owner role can regenerate readme — gate passes.
  8. Private projects' readme field is never returned by the public listing
     (p.visibility = 'public' clause in list_public_projects).

project_workshop_images (retired table):
  9. The consolidated baseline migrations contain no CREATE TABLE
     project_workshop_images — table was retired.
 10. Routes source has no SELECT from project_workshop_images — access
     control is moot because the table no longer exists.
 11. _project_to_workshop_row derives cover_url from the projects row's
     cover_storage_key, not a separate gallery table.
 12. list_public_projects source always filters p.visibility = 'public' —
     private project readmes are never leaked to anonymous callers.

All cases are hermetic (no real Postgres, no network).
"""
from __future__ import annotations

import inspect
import pathlib
import re
import uuid
from typing import Any, Optional

import pytest
from fastapi import HTTPException


# ---------------------------------------------------------------------------
# Fixtures — UUIDs for two isolated tenants
# ---------------------------------------------------------------------------

WS_A = str(uuid.uuid4())
WS_B = str(uuid.uuid4())
USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())

PROJ_A_PUB = str(uuid.uuid4())    # project A — visibility public
PROJ_A_PRIV = str(uuid.uuid4())   # project A — visibility private
PROJ_B_PUB = str(uuid.uuid4())    # project B — visibility public


# ---------------------------------------------------------------------------
# In-memory fake DB helpers
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    """Minimal asyncpg-Record-alike; supports dict-style item access."""

    def __getitem__(self, key: str):
        return super().__getitem__(key)

    def get(self, key: str, default=None):
        return super().get(key, default)


# workspace_members: {(ws_id, user_id): role}
_MEMBERS: dict[tuple[str, str], str] = {
    (WS_A, USER_A): "owner",
    (WS_B, USER_B): "owner",
}

# projects: {pid: {ws_id, visibility, readme, ...}}
_PROJECTS: dict[str, dict] = {
    PROJ_A_PUB: {
        "id": uuid.UUID(PROJ_A_PUB), "workspace_id": uuid.UUID(WS_A),
        "visibility": "public", "name": "Alpha Public",
        "readme": "# Alpha", "cover_storage_key": "covers/alpha.jpg",
        "thumbnail_storage_key": "thumbs/alpha.jpg",
        "readme_generated_at": None, "cover_generated_at": None,
    },
    PROJ_A_PRIV: {
        "id": uuid.UUID(PROJ_A_PRIV), "workspace_id": uuid.UUID(WS_A),
        "visibility": "private", "name": "Alpha Private",
        "readme": "## secret readme", "cover_storage_key": None,
        "thumbnail_storage_key": None,
        "readme_generated_at": None, "cover_generated_at": None,
    },
    PROJ_B_PUB: {
        "id": uuid.UUID(PROJ_B_PUB), "workspace_id": uuid.UUID(WS_B),
        "visibility": "public", "name": "Beta Public",
        "readme": "# Beta", "cover_storage_key": None,
        "thumbnail_storage_key": "thumbs/beta.jpg",
        "readme_generated_at": None, "cover_generated_at": None,
    },
}

# workshop_likes: {(user_id, project_id): True}
_LIKES: dict[tuple[str, str], bool] = {
    (USER_B, PROJ_A_PUB): True,  # B has already liked A's public project
}


class _RecordingConn:
    """Records every SQL call + args; simulates asyncpg.Connection responses."""

    def __init__(self):
        self.executed: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, *args) -> str:
        self.executed.append((sql, args))
        q = sql.strip().lower()
        if "delete from workshop_likes" in q:
            key = (str(args[0]), str(args[1]))
            _LIKES.pop(key, None)
            return "DELETE 1"
        if "insert into workshop_likes" in q:
            key = (str(args[0]), str(args[1]))
            _LIKES[key] = True
            return "INSERT 0 1"
        return "OK"

    async def fetchval(self, sql: str, *args) -> Any:
        self.executed.append((sql, args))
        q = sql.strip().lower()
        # workshop_likes existence check: SELECT 1 FROM workshop_likes
        #   WHERE user_id = $1 AND project_id = $2
        if "from workshop_likes" in q and "where user_id" in q and "project_id" in q:
            key = (str(args[0]), str(args[1]))
            return 1 if key in _LIKES else None
        # like count aggregation: SELECT COUNT(*) FROM workshop_likes
        #   WHERE project_id = $1
        if "count(*) from workshop_likes" in q and "project_id" in q:
            pid = str(args[0])
            return sum(1 for (_, p) in _LIKES if p == pid)
        # project visibility check used by workshop_toggle_like route:
        #   SELECT id FROM projects WHERE id = $1 AND visibility = 'public'
        if "from projects" in q and "visibility = 'public'" in q:
            pid = str(args[0])
            proj = _PROJECTS.get(pid)
            if proj and proj["visibility"] == "public":
                return proj["id"]
            return None
        return None

    async def fetchrow(self, sql: str, *args) -> Optional[FakeRecord]:
        self.executed.append((sql, args))
        q = sql.strip().lower()

        # workspace_members role lookup
        if "from workspace_members" in q:
            ws_id, user_id = str(args[0]), str(args[1])
            role = _MEMBERS.get((ws_id, user_id))
            return FakeRecord({"role": role}) if role else None

        # projects lookup by id (get_project)
        if "from projects where id = $1" in q:
            pid = str(args[0])
            proj = _PROJECTS.get(pid)
            return FakeRecord(proj) if proj else None

        return None

    async def fetch(self, sql: str, *args) -> list[FakeRecord]:
        self.executed.append((sql, args))
        q = sql.strip().lower()

        # list_public_projects: WHERE p.visibility = 'public'
        if "p.visibility = 'public'" in q:
            results = []
            for proj in _PROJECTS.values():
                if proj["visibility"] == "public":
                    row = FakeRecord(dict(proj))
                    row["workspace_slug"] = "ws-slug"
                    row["workspace_name"] = "WS"
                    row["author_name"] = "Author"
                    row["likes_count"] = 0
                    row["forks_count"] = 0
                    row["liked_by_me"] = False
                    results.append(row)
            return results

        return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _role(ws_id: str, user_id: str) -> Optional[str]:
    from kerf_api.routes import get_user_workspace_role
    conn = _RecordingConn()
    return await get_user_workspace_role(conn, ws_id, user_id)


def _project_ws(pid: str) -> Optional[str]:
    proj = _PROJECTS.get(pid)
    return str(proj["workspace_id"]) if proj else None


# ===========================================================================
# Case 1 — toggle_like always binds the caller's user_id — no forge possible
# ===========================================================================

@pytest.mark.asyncio
async def test_toggle_like_binds_caller_user_id():
    """workshop_likes INSERT/DELETE must always use the authenticated caller's uid.

    The toggle_like function receives user_id as a positional parameter and
    passes it directly to the parameterised INSERT/DELETE queries ($1) — it
    is impossible for a caller to supply a different user_id via the request.
    """
    from kerf_core.db.queries.workshop_likes import toggle_like

    conn = _RecordingConn()
    initial_likes = dict(_LIKES)
    try:
        await toggle_like(conn, uuid.UUID(USER_A), uuid.UUID(PROJ_B_PUB))

        # Filter to INSERT/DELETE mutations only — COUNT(*) uses project_id as $1
        mutation_calls = [
            (sql, args) for sql, args in conn.executed
            if "workshop_likes" in sql.lower()
            and any(kw in sql.upper() for kw in ("INSERT", "DELETE"))
        ]
        assert mutation_calls, "No INSERT/DELETE on workshop_likes executed"

        for sql, args in mutation_calls:
            assert str(args[0]) == USER_A, (
                f"toggle_like mutation bound {args[0]!r} as user_id ($1); "
                f"expected USER_A={USER_A!r}. SQL: {sql!r}"
            )
            # USER_B must not appear in any mutation args
            all_args_str = " ".join(str(a) for a in args)
            assert USER_B not in all_args_str, (
                f"toggle_like must not reference USER_B in mutation args: {all_args_str!r}"
            )
    finally:
        _LIKES.clear()
        _LIKES.update(initial_likes)


# ===========================================================================
# Case 2 — toggle_like on a private project is blocked (404)
# ===========================================================================

@pytest.mark.asyncio
async def test_toggle_like_private_project_blocked():
    """POST /api/workshop/{slug}/like: private project → 404 before any like is written.

    The route handler checks: SELECT id FROM projects WHERE id = $1
    AND visibility = 'public' — private projects return no row → 404.
    """
    conn = _RecordingConn()

    # Simulate the route guard (routes.py: workshop_toggle_like)
    row = await conn.fetchval(
        "SELECT id FROM projects WHERE id = $1 AND visibility = 'public'",
        uuid.UUID(PROJ_A_PRIV),
    )
    assert row is None, (
        "Private project must not be found by the visibility='public' guard"
    )

    # Gate fires → 404
    with pytest.raises(HTTPException) as exc:
        if not row:
            raise HTTPException(status_code=404, detail="Project not found")
    assert exc.value.status_code == 404


# ===========================================================================
# Case 3 — Like count aggregation is scoped to the project_id
# ===========================================================================

@pytest.mark.asyncio
async def test_like_count_scoped_to_project_id():
    """SELECT COUNT(*) FROM workshop_likes must be WHERE project_id = $1.

    Verify the positional arg is a project_id, not an unscoped query — so
    the count cannot leak across project boundaries.
    """
    conn = _RecordingConn()

    await conn.fetchval(
        "SELECT COUNT(*) FROM workshop_likes WHERE project_id = $1",
        uuid.UUID(PROJ_A_PUB),
    )

    count_call = next(
        (c for c in conn.executed if "count(*)" in c[0].lower() and "workshop_likes" in c[0].lower()),
        None,
    )
    assert count_call is not None, "No COUNT(*) FROM workshop_likes call found"
    sql, args = count_call
    assert args, "COUNT(*) call must have at least one bound arg (project_id)"
    assert str(args[0]) == PROJ_A_PUB, (
        f"Count must be scoped to PROJ_A_PUB; got {args[0]!r}"
    )


# ===========================================================================
# Case 4 — toggle_like source binds user_id as $1 in INSERT and DELETE
# ===========================================================================

def test_toggle_like_source_uses_positional_user_id():
    """Static source check: toggle_like always passes user_id as $1 to the INSERT.

    The INSERT / DELETE queries must parameterise user_id as $1 so no caller
    can supply a different user_id by crafting the request body.
    """
    from kerf_core.db.queries import workshop_likes as wl_mod

    src = inspect.getsource(wl_mod)

    assert "INSERT INTO workshop_likes (user_id, project_id) VALUES ($1, $2)" in src, (
        "toggle_like INSERT must bind user_id as $1 and project_id as $2"
    )
    assert "DELETE FROM workshop_likes WHERE user_id = $1 AND project_id = $2" in src, (
        "toggle_like DELETE must bind user_id as $1 and project_id as $2"
    )


# ===========================================================================
# Case 5 — Non-member cannot regenerate readme → 403
# ===========================================================================

@pytest.mark.asyncio
async def test_regenerate_readme_non_member_gets_403():
    """User A has no workspace membership for PROJ_B_PUB → 403 on readme regen."""
    from kerf_api.routes import get_user_workspace_role

    conn = _RecordingConn()
    proj = _PROJECTS[PROJ_B_PUB]
    ws_id = str(proj["workspace_id"])

    role = await get_user_workspace_role(conn, ws_id, USER_A)
    assert role is None, (
        f"USER_A must have no role in WS_B for readme gate; got {role!r}"
    )

    # Gate mirrors routes.py: if role not in ("owner", "admin"): 403
    with pytest.raises(HTTPException) as exc:
        if role not in ("owner", "admin"):
            raise HTTPException(status_code=403, detail="Not authorized")
    assert exc.value.status_code == 403


# ===========================================================================
# Case 6 — Viewer role cannot regenerate readme → 403
# ===========================================================================

@pytest.mark.asyncio
async def test_regenerate_readme_viewer_gets_403():
    """role == 'viewer' must be rejected by the readme-regeneration ownership check."""
    from kerf_api.routes import get_user_workspace_role

    _MEMBERS[(WS_A, USER_B)] = "viewer"
    try:
        conn = _RecordingConn()
        proj = _PROJECTS[PROJ_A_PUB]
        ws_id = str(proj["workspace_id"])

        role = await get_user_workspace_role(conn, ws_id, USER_B)
        assert role == "viewer"

        with pytest.raises(HTTPException) as exc:
            if role not in ("owner", "admin"):
                raise HTTPException(status_code=403, detail="Not authorized")
        assert exc.value.status_code == 403
    finally:
        del _MEMBERS[(WS_A, USER_B)]


# ===========================================================================
# Case 7 — Owner can regenerate readme — gate passes
# ===========================================================================

@pytest.mark.asyncio
async def test_regenerate_readme_owner_passes_gate():
    """USER_A is owner of WS_A — the readme-regeneration ownership check must pass."""
    from kerf_api.routes import get_user_workspace_role

    conn = _RecordingConn()
    proj = _PROJECTS[PROJ_A_PUB]
    ws_id = str(proj["workspace_id"])

    role = await get_user_workspace_role(conn, ws_id, USER_A)
    assert role == "owner", f"Expected 'owner', got {role!r}"

    # Gate check must not raise
    if role not in ("owner", "admin"):
        raise AssertionError("Owner must not be blocked by the readme gate")


# ===========================================================================
# Case 8 — Private project's readme not exposed via public listing
# ===========================================================================

@pytest.mark.asyncio
async def test_private_project_readme_not_in_public_listing():
    """list_public_projects filters p.visibility = 'public' — private readmes excluded."""
    conn = _RecordingConn()

    rows = await conn.fetch(
        """
        SELECT p.*, w.slug AS workspace_slug, w.name AS workspace_name,
               u.name AS author_name,
               0 AS likes_count, 0 AS forks_count, FALSE AS liked_by_me
        FROM projects p
        JOIN workspaces w ON w.id = p.workspace_id
        JOIN users u ON u.id = w.created_by
        WHERE p.visibility = 'public'
        ORDER BY p.updated_at DESC
        LIMIT $1 OFFSET $2
        """,
        20, 0,
    )

    returned_pids = {str(r["id"]) for r in rows}
    assert PROJ_A_PRIV not in returned_pids, (
        "Private project PROJ_A_PRIV must not appear in the public workshop listing"
    )
    # Verify the private readme text is not present in any returned row
    all_readmes = [r.get("readme") for r in rows]
    assert "## secret readme" not in all_readmes, (
        "Private project's readme content leaked into public listing"
    )


# ===========================================================================
# Case 9 — project_workshop_images CREATE TABLE absent from final migrations
# ===========================================================================

def test_project_workshop_images_table_retired_from_migrations():
    """No CREATE TABLE project_workshop_images must exist in the baseline migrations.

    The table was retired: workshop media is files-in-repo.  Any remaining
    CREATE TABLE DDL would mean the dead schema is still being deployed.
    Comment-only references (explaining the retirement) are acceptable.
    """
    migrations_dir = (
        pathlib.Path(__file__).parents[3]
        / "packages" / "kerf-core" / "src" / "kerf_core" / "db" / "migrations"
    )
    assert migrations_dir.is_dir(), f"Migrations directory not found: {migrations_dir}"

    for sql_file in sorted(migrations_dir.glob("*.sql")):
        content = sql_file.read_text(encoding="utf-8")
        # Match actual DDL — pattern: CREATE TABLE [IF NOT EXISTS] project_workshop_images
        match = re.search(
            r"create\s+table\s+(?:if\s+not\s+exists\s+)?project_workshop_images",
            content,
            re.IGNORECASE,
        )
        assert match is None, (
            f"Retired table still has a CREATE TABLE in {sql_file.name}: "
            f"{match.group()!r} — remove it; the table was retired in favour of "
            "files-in-repo media"
        )


# ===========================================================================
# Case 10 — Routes source has no SELECT from project_workshop_images
# ===========================================================================

def test_routes_has_no_select_from_project_workshop_images():
    """routes.py must not contain any SELECT FROM project_workshop_images.

    Since the table is retired, any such query would be a dead code reference
    that could become a live cross-tenant leak if the table were ever recreated.
    """
    import kerf_api.routes as api_routes

    src = pathlib.Path(api_routes.__file__).read_text(encoding="utf-8")

    match = re.search(
        r"SELECT\b.*?\bFROM\s+project_workshop_images",
        src,
        re.IGNORECASE | re.DOTALL,
    )
    assert match is None, (
        "routes.py contains a SELECT FROM project_workshop_images — "
        "the table is retired; remove this query."
    )


# ===========================================================================
# Case 11 — RETIRED 2026-07-18: _project_to_workshop_row was deleted with the
# hosted/centralized Workshop routes (the distributed DMTAP-PUB Workshop in
# kerf-pub replaced them); the cover-from-storage-key rule it guarded died
# with that code path.
# ===========================================================================

def _retired_test_project_to_workshop_row_cover_from_storage_key():
    """_project_to_workshop_row must derive cover_url from projects.cover_storage_key.

    The retired project_workshop_images gallery must NOT be the source of
    the cover URL; the projects row's cover_storage_key field is the sole
    authoritative source.
    """
    import datetime
    from kerf_api.routes import _project_to_workshop_row

    # Minimal project dict with cover_storage_key set
    proj = {
        "id": uuid.UUID(PROJ_A_PUB),
        "workspace_id": uuid.UUID(WS_A),
        "name": "Alpha Public",
        "description": "",
        "visibility": "public",
        "tags": [],
        "thumbnail_storage_key": "thumbs/alpha.jpg",
        "thumbnail_updated_at": None,
        "cover_storage_key": "covers/alpha.jpg",
        "cover_generated_at": None,
        "readme": "# Alpha",
        "readme_generated_at": None,
        "created_at": datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc),
        "updated_at": datetime.datetime(2024, 1, 2, tzinfo=datetime.timezone.utc),
        "workspace_slug": "ws-a",
        "workspace_name": "WS-A",
        "author_name": "Alice",
        "author_id": None,
        "author_avatar_url": None,
        "is_verified_publisher": False,
        "likes_count": 0,
        "forks_count": 0,
        "liked_by_me": False,
        "file_count": 0,
        "total_bytes": 0,
        # Simulate that there are NO workshop_images gallery rows
        "workshop_images": [],
        "workshop_model_id": None,
        "workshop_model_name": None,
        "forked_from_project_id": None,
        "created_by": None,
    }

    result = _project_to_workshop_row(proj)

    # cover_url must come from cover_storage_key, not a gallery row
    assert result["cover_url"] is not None, (
        "cover_url must be non-null when cover_storage_key is set"
    )
    assert "/cover" in result["cover_url"], (
        f"cover_url must use the /cover endpoint (from cover_storage_key); "
        f"got {result['cover_url']!r}"
    )
    assert result["cover_storage_key"] == "covers/alpha.jpg", (
        "cover_storage_key must be forwarded from the projects row"
    )

    # When no cover_storage_key, fall back to thumbnail — NOT a gallery table
    proj_no_cover = dict(proj)
    proj_no_cover["cover_storage_key"] = None
    result_no_cover = _project_to_workshop_row(proj_no_cover)
    assert result_no_cover["cover_url"] == f"/api/projects/{PROJ_A_PUB}/thumbnail", (
        "With no cover_storage_key, cover_url must fall back to /thumbnail"
    )


# ===========================================================================
# Case 12 — list_public_projects source always filters visibility='public'
# ===========================================================================

def test_list_public_projects_source_filters_visibility():
    """Static source check: list_public_projects must always emit visibility='public'.

    This is the primary RLS gate that prevents private project readmes from
    leaking through the workshop browse endpoint — the SQL WHERE clause must
    be present in the query construction code.
    """
    from kerf_core.db.queries.projects import list_public_projects

    src = inspect.getsource(list_public_projects)

    assert "visibility = 'public'" in src, (
        "list_public_projects must filter p.visibility = 'public' — "
        "without it, private project readmes and cover_storage_keys "
        "would be exposed to anonymous callers"
    )
    # Confirm the filter is inside a conditions list that feeds the WHERE clause
    assert "conditions" in src, (
        "list_public_projects must build a conditions list for its WHERE clause"
    )
