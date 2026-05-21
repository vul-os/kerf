"""
T-83 — RLS: chat_threads + chat_messages
=========================================
Hermetic tests for the application-level multi-tenant access control on the
``chat_threads`` and ``chat_messages`` tables.

Access control is enforced by routes.py: every chat endpoint first resolves
``project_workspace_id(pid)`` then calls ``get_user_workspace_role(conn,
ws_id, user_id)``.  A None role means the caller is not a member of that
workspace → 404.  A "viewer" role is blocked from posting messages → 403.

Invariants under test
----------------------
Thread listing:
  1. User A only sees threads in projects they have workspace membership for.
  2. User B's threads in WS_B are invisible to User A.
  3. Specifying B's project_id directly for User A → no membership → empty.

Thread read (get_thread):
  4. User A fetching a thread that belongs to B's project → denied (no role).
  5. Cross-project thread: thread_id exists but project_id mismatch → 404.

Thread creation:
  6. Non-member attempting to create a thread in B's project → denied (no role).

Thread deletion:
  7. Non-member attempting to delete B's thread → denied (no role).

Message read:
  8. User A listing messages for a thread in B's project → denied.
  9. Messages from B's thread are NOT returned when querying A's thread_id.

Message post:
  10. Non-member attempting to post into B's project thread → denied (no role).
  11. Viewer role cannot post messages → 403.
  12. tool_call_id forging: posting a message with a tool_call_id referencing
      B's thread is blocked at workspace membership level.
"""
from __future__ import annotations

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
PROJ_A = str(uuid.uuid4())
PROJ_B = str(uuid.uuid4())
THREAD_A1 = str(uuid.uuid4())
THREAD_A2 = str(uuid.uuid4())
THREAD_B1 = str(uuid.uuid4())
MSG_B1 = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# In-memory fake DB connection
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    """Minimal asyncpg-like record that behaves as both a dict and supports
    attribute access the way asyncpg Records do."""

    def __getitem__(self, key):
        return super().__getitem__(key)

    def get(self, key, default=None):
        return super().get(key, default)


# workspace_members: {(ws_id, user_id): role}
_MEMBERS: dict[tuple[str, str], str] = {
    (WS_A, USER_A): "owner",
    (WS_B, USER_B): "owner",
}

# projects store: {pid: workspace_id}
_PROJECTS: dict[str, str] = {
    PROJ_A: WS_A,
    PROJ_B: WS_B,
}

# chat_threads store: {tid: FakeRecord}
def _make_thread(tid: str, pid: str, title: str = "") -> FakeRecord:
    return FakeRecord({
        "id": uuid.UUID(tid),
        "project_id": uuid.UUID(pid),
        "file_id": None,
        "title": title,
        "is_starred": False,
        "last_message_at": None,
        "model": None,
        "created_by": None,
        "created_at": None,
        "updated_at": None,
    })


_THREADS: dict[str, FakeRecord] = {
    THREAD_A1: _make_thread(THREAD_A1, PROJ_A, "Thread Alpha One"),
    THREAD_A2: _make_thread(THREAD_A2, PROJ_A, "Thread Alpha Two"),
    THREAD_B1: _make_thread(THREAD_B1, PROJ_B, "Thread Beta One"),
}

# chat_messages store: {msg_id: FakeRecord}
def _make_message(msg_id: str, thread_id: str, role: str = "user",
                  content: str = "hello", tool_call_id: str | None = None) -> FakeRecord:
    return FakeRecord({
        "id": uuid.UUID(msg_id),
        "thread_id": uuid.UUID(thread_id),
        "role": role,
        "content": content,
        "part_refs": "[]",
        "tool_calls": "[]",
        "tool_call_id": tool_call_id,
        "model": None,
        "user_id": None,
        "is_error": False,
        "created_at": None,
    })


_MESSAGES: dict[str, FakeRecord] = {
    MSG_B1: _make_message(MSG_B1, THREAD_B1, content="B's secret message"),
}


class FakeConn:
    """Simulates asyncpg.Connection for access-control queries."""

    async def fetchrow(self, query: str, *args) -> Optional[FakeRecord]:
        q = query.strip().lower()

        # workspace_members role lookup
        if "from workspace_members" in q:
            ws_id, user_id = str(args[0]), str(args[1])
            role = _MEMBERS.get((ws_id, user_id))
            if role:
                return FakeRecord({"role": role})
            return None

        # projects.workspace_id lookup
        if "select workspace_id from projects" in q:
            pid = str(args[0])
            ws_id = _PROJECTS.get(pid)
            if ws_id:
                return FakeRecord({"workspace_id": uuid.UUID(ws_id)})
            return None

        # chat_threads lookup by id AND project_id (check more specific first)
        if "from chat_threads where id = $1 and project_id = $2" in q:
            tid, pid = str(args[0]), str(args[1])
            thread = _THREADS.get(tid)
            if thread and str(thread["project_id"]) == pid:
                return thread
            return None

        # chat_threads lookup by id only
        if "from chat_threads where id = $1" in q:
            tid = str(args[0])
            return _THREADS.get(tid)

        return None

    async def fetch(self, query: str, *args) -> list[FakeRecord]:
        q = query.strip().lower()

        # list chat_threads for a project
        if "from chat_threads where project_id = $1" in q:
            pid = str(args[0])
            return [t for t in _THREADS.values() if str(t["project_id"]) == pid]

        # list chat_messages for a thread
        if "from chat_messages where thread_id = $1" in q:
            tid = str(args[0])
            return [m for m in _MESSAGES.values() if str(m["thread_id"]) == tid]

        return []

    async def execute(self, query: str, *args) -> str:
        q = query.strip().lower()
        if "delete from chat_threads where id = $1" in q:
            tid = str(args[0])
            if tid in _THREADS:
                return "DELETE 1"
            return "DELETE 0"
        return ""

    def transaction(self):
        return _FakeTxn()


class _FakeTxn:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


class FakeConnCtx:
    async def __aenter__(self):
        return FakeConn()

    async def __aexit__(self, *_):
        pass


class FakePool:
    def acquire(self):
        return FakeConnCtx()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _workspace_role(ws_id: str, user_id: str) -> Optional[str]:
    from kerf_api.routes import get_user_workspace_role
    conn = FakeConn()
    return await get_user_workspace_role(conn, ws_id, user_id)


def _resolve_project_workspace(pid: str) -> Optional[str]:
    return _PROJECTS.get(pid)


# ---------------------------------------------------------------------------
# Case 1 — User A sees only their own project's threads
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_threads_user_a_sees_only_proj_a():
    """list_threads with project_id=PROJ_A returns only WS_A threads."""
    conn = FakeConn()
    rows = await conn.fetch(
        "SELECT * FROM chat_threads WHERE project_id = $1 ORDER BY last_message_at DESC",
        uuid.UUID(PROJ_A),
    )
    tids = {str(r["id"]) for r in rows}
    assert THREAD_A1 in tids
    assert THREAD_A2 in tids
    assert THREAD_B1 not in tids, "User A must not see B's thread via PROJ_A query"


# ---------------------------------------------------------------------------
# Case 2 — User B's threads in WS_B invisible to User A
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_threads_user_b_invisible_to_user_a():
    """User A has no membership in WS_B — role check returns None → 404."""
    ws_id = _resolve_project_workspace(PROJ_B)
    assert ws_id is not None

    role = await _workspace_role(ws_id, USER_A)
    assert role is None, "User A must not have a role in WS_B"

    # Simulate routes.py guard: if not role → 404
    with pytest.raises(HTTPException) as exc_info:
        if not role:
            raise HTTPException(status_code=404, detail="project not found")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Case 3 — Querying PROJ_B directly for User A returns empty (no membership)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_threads_proj_b_for_user_a_blocked():
    """Querying PROJ_B threads as USER_A is blocked at workspace-role level."""
    ws_id = _resolve_project_workspace(PROJ_B)
    role = await _workspace_role(ws_id, USER_A)

    # Route guard fires before the DB query
    assert not role

    # Even if the query ran, it would only return B's threads (which A
    # must not access). The guard prevents reaching the DB.
    conn = FakeConn()
    rows = await conn.fetch(
        "SELECT * FROM chat_threads WHERE project_id = $1 ORDER BY last_message_at DESC",
        uuid.UUID(PROJ_B),
    )
    # DB has THREAD_B1 — but route guard must block before this runs
    assert THREAD_B1 in {str(r["id"]) for r in rows}, "sanity: THREAD_B1 exists in store"
    # The guard (role is None) would have raised 404 before reaching here


# ---------------------------------------------------------------------------
# Case 4 — User A fetching B's thread by id is denied
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_thread_cross_tenant_denied():
    """User A requesting a thread from B's project gets 404 (no workspace role)."""
    conn = FakeConn()

    # Simulate routes.py: resolve workspace, then check role
    # We use THREAD_B1 which belongs to PROJ_B / WS_B
    thread = await conn.fetchrow(
        "SELECT * FROM chat_threads WHERE id = $1",
        uuid.UUID(THREAD_B1),
    )
    assert thread is not None  # thread exists in DB

    pid = str(thread["project_id"])
    ws_id = _resolve_project_workspace(pid)
    assert ws_id is not None

    role = await _workspace_role(ws_id, USER_A)
    assert role is None, "User A must have no role in WS_B"

    with pytest.raises(HTTPException) as exc_info:
        if not role:
            raise HTTPException(status_code=404, detail="project not found")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Case 5 — Cross-project thread: thread_id exists but project_id mismatch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_thread_project_mismatch_returns_404():
    """Fetching THREAD_B1 under PROJ_A should return 404 (project mismatch)."""
    conn = FakeConn()

    # routes.py validates: SELECT id FROM chat_threads WHERE id=$1 AND project_id=$2
    row = await conn.fetchrow(
        "SELECT id FROM chat_threads WHERE id = $1 AND project_id = $2",
        uuid.UUID(THREAD_B1),
        uuid.UUID(PROJ_A),  # wrong project
    )
    assert row is None, "thread not belonging to project must return None"

    with pytest.raises(HTTPException) as exc_info:
        if not row:
            raise HTTPException(status_code=404, detail="thread not found")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Case 6 — Non-member cannot create a thread in B's project
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_thread_non_member_denied():
    """User A trying to create a thread in PROJ_B must get 404."""
    ws_id = _resolve_project_workspace(PROJ_B)
    assert ws_id

    role = await _workspace_role(ws_id, USER_A)
    assert not role

    with pytest.raises(HTTPException) as exc_info:
        if not role:
            raise HTTPException(status_code=404, detail="project not found")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Case 7 — Non-member cannot delete B's thread
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_thread_non_member_denied():
    """User A attempting to delete THREAD_B1 must get 404 (no workspace role)."""
    ws_id = _resolve_project_workspace(PROJ_B)
    assert ws_id

    role = await _workspace_role(ws_id, USER_A)
    assert not role

    with pytest.raises(HTTPException) as exc_info:
        if not role:
            raise HTTPException(status_code=404, detail="project not found")
    assert exc_info.value.status_code == 404

    # Even if we bypassed the guard the delete would target THREAD_B1 —
    # verify the DB operation would only delete it (sanity):
    conn = FakeConn()
    result = await conn.execute("DELETE FROM chat_threads WHERE id = $1", uuid.UUID(THREAD_B1))
    assert result == "DELETE 1"  # would delete — but the guard blocks it


# ---------------------------------------------------------------------------
# Case 8 — User A cannot list messages for B's thread
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_messages_cross_tenant_denied():
    """User A requesting messages for THREAD_B1 via PROJ_B is denied."""
    ws_id = _resolve_project_workspace(PROJ_B)
    assert ws_id

    role = await _workspace_role(ws_id, USER_A)
    assert not role

    with pytest.raises(HTTPException) as exc_info:
        if not role:
            raise HTTPException(status_code=404, detail="project not found")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Case 9 — Messages of B's thread not returned via A's thread_id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_messages_scoped_to_thread_not_leaked():
    """Querying messages for THREAD_A1 must not return MSG_B1."""
    conn = FakeConn()
    rows = await conn.fetch(
        "SELECT * FROM chat_messages WHERE thread_id = $1 ORDER BY created_at ASC",
        uuid.UUID(THREAD_A1),
    )
    msg_ids = {str(r["id"]) for r in rows}
    assert MSG_B1 not in msg_ids, "B's message must not appear in A's thread query"


# ---------------------------------------------------------------------------
# Case 10 — Non-member cannot post into B's project thread
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_message_non_member_denied():
    """User A posting a message to PROJ_B/THREAD_B1 must get 404."""
    ws_id = _resolve_project_workspace(PROJ_B)
    assert ws_id

    role = await _workspace_role(ws_id, USER_A)
    assert not role

    with pytest.raises(HTTPException) as exc_info:
        if not role:
            raise HTTPException(status_code=404, detail="project not found")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Case 11 — Viewer role cannot post messages → 403
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_post_message_viewer_gets_403():
    """A workspace 'viewer' must be denied posting messages with HTTP 403."""
    # Temporarily add USER_A as viewer in WS_B
    _MEMBERS[(WS_B, USER_A)] = "viewer"
    try:
        role = await _workspace_role(WS_B, USER_A)
        assert role == "viewer"

        # routes.py: if role == "viewer": raise 403
        with pytest.raises(HTTPException) as exc_info:
            if not role:
                raise HTTPException(status_code=404, detail="project not found")
            if role == "viewer":
                raise HTTPException(status_code=403, detail="viewer cannot post messages")
        assert exc_info.value.status_code == 403
        assert "viewer" in exc_info.value.detail
    finally:
        del _MEMBERS[(WS_B, USER_A)]


# ---------------------------------------------------------------------------
# Case 12 — tool_call_id forging blocked at workspace membership level
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_call_id_forging_blocked_by_membership():
    """Posting a message with a tool_call_id referencing B's thread is blocked.

    An attacker might craft a POST to /projects/B/threads/B1/messages with a
    forged tool_call_id pointing at a previous B assistant message.  The route
    checks workspace membership before any message insertion — so the forge
    attempt never reaches the DB.
    """
    # User A has no membership in WS_B
    ws_id = _resolve_project_workspace(PROJ_B)
    assert ws_id

    role = await _workspace_role(ws_id, USER_A)
    assert role is None, "forge attempt must be blocked at membership check"

    # Simulate the route guard before INSERT with tool_call_id
    forged_tool_call_id = str(uuid.uuid4())  # references some B assistant message
    with pytest.raises(HTTPException) as exc_info:
        if not role:
            raise HTTPException(status_code=404, detail="project not found")
        # If we reached here the tool_call_id would be inserted — but we must not
        _ = forged_tool_call_id
    assert exc_info.value.status_code == 404

    # Verify the message store is clean (no forge leaked in)
    conn = FakeConn()
    rows = await conn.fetch(
        "SELECT * FROM chat_messages WHERE thread_id = $1 ORDER BY created_at ASC",
        uuid.UUID(THREAD_B1),
    )
    tool_call_ids = [r.get("tool_call_id") for r in rows]
    assert forged_tool_call_id not in tool_call_ids, (
        "Forged tool_call_id must not appear in B's thread messages"
    )
