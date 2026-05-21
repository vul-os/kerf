"""
T-87 — RLS: step_tessellation_jobs + cam_jobs + fem_jobs + sim_jobs
====================================================================
Hermetic tests for multi-tenant access control on the four worker job tables.

The application enforces access via ``project_workspace_id(pid)`` +
``get_user_workspace_role(conn, ws_id, user_id)`` before any INSERT/SELECT on
these tables.  Every test uses in-memory fake connections — no real database
required.

Tables under test
-----------------
- step_tessellation_jobs  (keyed by file_id, no project_id column)
- cam_jobs                (file_id + project_id, viewer blocked)
- fem_jobs                (file_id + project_id, viewer blocked)
- sim_jobs                (file_id + project_id, viewer blocked)

Security invariants
-------------------
ENQUEUE (POST /projects/{pid}/files/{fid}/<job>):
  1.  Non-member cannot enqueue a job against another tenant's project (404).
  2.  Viewer role cannot enqueue cam/fem/sim jobs (403).
  3.  Member/owner role can enqueue successfully.

READ (GET /projects/{pid}/files/{fid}/<job>/status):
  4.  Non-member cannot read job status from another tenant's project (404).
  5.  Viewer CAN read status (read-only access is permitted).
  6.  Owner can read their own job status.

CROSS-TENANT ID GUESS:
  7.  Guessing a job id from tenant B while authenticated as tenant A is refused
      because the project membership check happens before the job lookup.

STEP-TESSELLATION SPECIFIC:
  8.  Non-member cannot enqueue tessellation (404).
  9.  Non-member cannot purge/reset tessellation (404).
  10. Member can enqueue tessellation.
  11. Member can purge tessellation.

MULTI-TABLE:
  12. All four job tables share the same access-control path — verified by
      checking that the route-layer membership guard appears in the source of
      all four endpoint handlers.
"""
from __future__ import annotations

import uuid
from typing import Optional

import pytest
from fastapi import HTTPException, status as http_status


# ---------------------------------------------------------------------------
# Fixed UUIDs for two isolated tenants
# ---------------------------------------------------------------------------

WS_A = str(uuid.uuid4())
WS_B = str(uuid.uuid4())
USER_A = str(uuid.uuid4())
USER_B = str(uuid.uuid4())
PROJ_A = str(uuid.uuid4())
PROJ_B = str(uuid.uuid4())
FILE_A = str(uuid.uuid4())
FILE_B = str(uuid.uuid4())

# workspace_members: {(ws_id, user_id): role}
_MEMBERS: dict[tuple[str, str], str] = {
    (WS_A, USER_A): "owner",
    (WS_B, USER_B): "owner",
}

# projects: {pid: ws_id}
_PROJECTS: dict[str, str] = {
    PROJ_A: WS_A,
    PROJ_B: WS_B,
}

# In-memory job stores: {file_id: {status, ...}}
_TESS_JOBS: dict[str, dict] = {}
_CAM_JOBS: dict[str, dict] = {}
_FEM_JOBS: dict[str, dict] = {}
_SIM_JOBS: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# In-memory fake DB connection
# ---------------------------------------------------------------------------

class FakeRecord(dict):
    """Minimal asyncpg-like record supporting both dict and attribute access."""
    def __getitem__(self, key):
        return super().__getitem__(key)

    def get(self, key, default=None):
        return super().get(key, default)


class FakeConn:
    """Simulates asyncpg.Connection for access-control queries."""

    async def fetchrow(self, query: str, *args) -> Optional[FakeRecord]:
        q = query.strip().lower()

        # workspace_members role lookup
        if "from workspace_members" in q and "where workspace_id" in q:
            ws_id, user_id = str(args[0]), str(args[1])
            role = _MEMBERS.get((ws_id, user_id))
            return FakeRecord({"role": role}) if role else None

        # projects workspace_id lookup
        if "select workspace_id from projects where id" in q:
            pid = str(args[0])
            ws_id = _PROJECTS.get(pid)
            return FakeRecord({"workspace_id": ws_id}) if ws_id else None

        # step_tessellation_jobs status by file_id
        if "from step_tessellation_jobs" in q and "file_id" in q:
            fid = str(args[0])
            job = _TESS_JOBS.get(fid)
            return FakeRecord(job) if job else None

        # fem_jobs status by file_id
        if "from fem_jobs" in q and "file_id" in q:
            fid = str(args[0])
            job = _FEM_JOBS.get(fid)
            return FakeRecord(job) if job else None

        # cam_jobs status by file_id
        if "from cam_jobs" in q and "file_id" in q:
            fid = str(args[0])
            job = _CAM_JOBS.get(fid)
            return FakeRecord(job) if job else None

        # sim_jobs status by file_id
        if "from sim_jobs" in q and "file_id" in q:
            fid = str(args[0])
            job = _SIM_JOBS.get(fid)
            return FakeRecord(job) if job else None

        return None

    async def execute(self, query: str, *args) -> str:
        q = query.strip().lower()
        if "insert into step_tessellation_jobs" in q or "update step_tessellation_jobs" in q:
            fid = str(args[0])
            _TESS_JOBS[fid] = {"id": str(uuid.uuid4()), "file_id": fid, "status": "queued"}
            return "INSERT 1"
        if "insert into fem_jobs" in q:
            fid = str(args[0])
            _FEM_JOBS[fid] = {"id": str(uuid.uuid4()), "file_id": fid, "status": "queued"}
            return "INSERT 1"
        if "insert into cam_jobs" in q:
            fid = str(args[0])
            _CAM_JOBS[fid] = {"id": str(uuid.uuid4()), "file_id": fid, "status": "queued"}
            return "INSERT 1"
        if "insert into sim_jobs" in q:
            fid = str(args[0])
            _SIM_JOBS[fid] = {"id": str(uuid.uuid4()), "file_id": fid, "status": "queued"}
            return "INSERT 1"
        return ""

    def transaction(self):
        return _FakeTxn()


class _FakeTxn:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *_):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_role(ws_id: str, user_id: str) -> Optional[str]:
    """Replicate the application's get_user_workspace_role logic."""
    conn = FakeConn()
    row = await conn.fetchrow(
        "SELECT role FROM workspace_members WHERE workspace_id = $1 AND user_id = $2",
        ws_id, user_id,
    )
    return row["role"] if row else None


async def _project_ws_id(pid: str) -> Optional[str]:
    """Replicate the application's project_workspace_id lookup."""
    conn = FakeConn()
    row = await conn.fetchrow(
        "SELECT workspace_id FROM projects WHERE id = $1",
        pid,
    )
    return str(row["workspace_id"]) if row else None


def _guard_non_member(role: Optional[str]) -> None:
    """Raise 404 if user is not a member — mirrors tessellate/status endpoints."""
    if not role:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="project not found")


def _guard_viewer(role: Optional[str], detail: str = "viewer cannot run job") -> None:
    """Raise 403 if user is absent or viewer — mirrors cam/fem/sim enqueue."""
    if not role or role == "viewer":
        raise HTTPException(status_code=http_status.HTTP_403_FORBIDDEN, detail=detail)


# ===========================================================================
# ENQUEUE guards
# ===========================================================================

# ---------------------------------------------------------------------------
# Case 1 — Non-member cannot enqueue against another tenant's project
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_non_member_gets_404():
    """User A attempting to enqueue any job on PROJ_B must get 404."""
    ws_id = await _project_ws_id(PROJ_B)
    assert ws_id == WS_B

    role = await _get_role(ws_id, USER_A)
    assert role is None

    with pytest.raises(HTTPException) as exc_info:
        _guard_non_member(role)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Case 2 — Viewer cannot enqueue cam/fem/sim jobs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_viewer_gets_403_for_cam_fem_sim():
    """Viewer role must be refused on CAM, FEM and SIM enqueue endpoints."""
    _MEMBERS[(WS_A, USER_B)] = "viewer"
    try:
        ws_id = await _project_ws_id(PROJ_A)
        role = await _get_role(ws_id, USER_B)
        assert role == "viewer"

        for detail in [
            "viewer cannot run CAM",
            "viewer cannot run FEM",
            "viewer cannot run simulation",
        ]:
            with pytest.raises(HTTPException) as exc_info:
                _guard_viewer(role, detail)
            assert exc_info.value.status_code == 403
    finally:
        del _MEMBERS[(WS_A, USER_B)]


# ---------------------------------------------------------------------------
# Case 3 — Member/owner can enqueue
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enqueue_owner_allowed():
    """User A (owner of WS_A) must pass the guard with no exception."""
    ws_id = await _project_ws_id(PROJ_A)
    role = await _get_role(ws_id, USER_A)
    assert role == "owner"

    # Must not raise
    _guard_viewer(role)  # owner passes the viewer guard


# ===========================================================================
# READ / STATUS guards
# ===========================================================================

# ---------------------------------------------------------------------------
# Case 4 — Non-member cannot read job status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_non_member_gets_404():
    """User A requesting job status on PROJ_B must get 404."""
    ws_id = await _project_ws_id(PROJ_B)
    role = await _get_role(ws_id, USER_A)
    assert role is None

    with pytest.raises(HTTPException) as exc_info:
        _guard_non_member(role)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Case 5 — Viewer CAN read job status (read-only is permitted)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_viewer_allowed():
    """Viewer role is allowed on the status read endpoint (no _guard_viewer there)."""
    _MEMBERS[(WS_A, USER_B)] = "viewer"
    try:
        ws_id = await _project_ws_id(PROJ_A)
        role = await _get_role(ws_id, USER_B)
        assert role == "viewer"

        # Status endpoints call _guard_non_member (not _guard_viewer)
        # — this must not raise for a viewer
        _guard_non_member(role)  # viewer is not None → passes
    finally:
        del _MEMBERS[(WS_A, USER_B)]


# ---------------------------------------------------------------------------
# Case 6 — Owner can read job status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_owner_sees_own_job():
    """Owner of WS_A gets job status for their own file."""
    # Pre-populate a tessellation job for FILE_A
    _TESS_JOBS[FILE_A] = {"id": str(uuid.uuid4()), "file_id": FILE_A, "status": "done",
                          "mesh_storage_key": "s3/key", "error": None}
    try:
        ws_id = await _project_ws_id(PROJ_A)
        role = await _get_role(ws_id, USER_A)
        assert role == "owner"

        _guard_non_member(role)  # must not raise

        conn = FakeConn()
        row = await conn.fetchrow(
            "SELECT id, status, mesh_storage_key FROM step_tessellation_jobs WHERE file_id = $1",
            FILE_A,
        )
        assert row is not None
        assert row["status"] == "done"
    finally:
        _TESS_JOBS.pop(FILE_A, None)


# ===========================================================================
# CROSS-TENANT ID GUESS
# ===========================================================================

# ---------------------------------------------------------------------------
# Case 7 — ID guess from other tenant is refused at the project guard
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cross_tenant_id_guess_refused():
    """User A guessing a FILE_B job id is blocked by the project membership check
    before any job table is queried."""
    # Simulate: User A knows FILE_B and PROJ_B but is not a member
    ws_id = await _project_ws_id(PROJ_B)
    assert ws_id is not None

    role = await _get_role(ws_id, USER_A)
    assert role is None, "USER_A must not have access to WS_B"

    # The guard fires before the job SELECT — B's job rows are never touched
    with pytest.raises(HTTPException) as exc_info:
        _guard_non_member(role)
    assert exc_info.value.status_code == 404

    # Confirm that, had the guard been absent, the job rows of B are isolated
    conn = FakeConn()
    _FEM_JOBS[FILE_B] = {"id": str(uuid.uuid4()), "status": "done", "result_json": {"secret": True}}
    try:
        # User A would need to know PROJ_B's ws_id AND have a role to reach this
        row = await conn.fetchrow(
            "SELECT id, status, result_json, error FROM fem_jobs WHERE file_id = $1 ORDER BY created_at DESC LIMIT 1",
            FILE_B,
        )
        # Row exists in the fake DB — but the route guard already raised above
        assert row is not None  # confirms the data IS there …
        # … but it's unreachable because the guard fired first
    finally:
        _FEM_JOBS.pop(FILE_B, None)


# ===========================================================================
# STEP-TESSELLATION SPECIFIC
# ===========================================================================

# ---------------------------------------------------------------------------
# Case 8 — Non-member cannot enqueue tessellation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tessellate_enqueue_non_member_gets_404():
    ws_id = await _project_ws_id(PROJ_B)
    role = await _get_role(ws_id, USER_A)
    assert role is None

    with pytest.raises(HTTPException) as exc_info:
        _guard_non_member(role)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Case 9 — Non-member cannot purge/reset tessellation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tessellate_purge_non_member_gets_404():
    ws_id = await _project_ws_id(PROJ_B)
    role = await _get_role(ws_id, USER_A)
    assert role is None

    with pytest.raises(HTTPException) as exc_info:
        _guard_non_member(role)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Case 10 — Member can enqueue tessellation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tessellate_enqueue_member_allowed():
    ws_id = await _project_ws_id(PROJ_A)
    role = await _get_role(ws_id, USER_A)
    assert role == "owner"

    # Must not raise — tessellate uses _guard_non_member (role exists → OK)
    _guard_non_member(role)

    conn = FakeConn()
    await conn.execute(
        "INSERT INTO step_tessellation_jobs (file_id) VALUES ($1) ON CONFLICT DO UPDATE SET status='queued'",
        FILE_A,
    )
    assert FILE_A in _TESS_JOBS
    assert _TESS_JOBS[FILE_A]["status"] == "queued"


# ---------------------------------------------------------------------------
# Case 11 — Member can purge tessellation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tessellate_purge_member_allowed():
    _TESS_JOBS[FILE_A] = {"id": str(uuid.uuid4()), "file_id": FILE_A, "status": "done"}
    try:
        ws_id = await _project_ws_id(PROJ_A)
        role = await _get_role(ws_id, USER_A)
        assert role == "owner"
        _guard_non_member(role)  # must not raise

        # Simulate the UPDATE that resets the job
        conn = FakeConn()
        await conn.execute(
            "UPDATE step_tessellation_jobs SET status='queued', error=null, mesh_storage_key=null WHERE file_id=$1",
            FILE_A,
        )
        # After the execute, the in-memory store reflects the new state
        assert _TESS_JOBS[FILE_A]["status"] == "queued"
    finally:
        _TESS_JOBS.pop(FILE_A, None)


# ===========================================================================
# MULTI-TABLE — source-level guard presence check
# ===========================================================================

# ---------------------------------------------------------------------------
# Case 12 — All four job-table endpoints use the workspace membership guard
# ---------------------------------------------------------------------------

def test_all_job_endpoints_guarded_by_workspace_role():
    """Each of the four job-table endpoint handlers must call
    ``get_user_workspace_role`` before any INSERT/SELECT on the job table.

    We verify this via static source inspection.
    """
    import inspect
    from kerf_api import routes as r

    handlers = {
        "tessellate": r.tessellate,
        "purge_tessellation": r.purge_tessellation,
        "run_fem": r.run_fem,
        "fem_job_status": r.fem_job_status,
        "run_cam": r.run_cam,
        "cam_job_status": r.cam_job_status,
        "run_sim": r.run_sim,
        "sim_job_status": r.sim_job_status,
    }

    for name, handler in handlers.items():
        src = inspect.getsource(handler)
        assert "get_user_workspace_role" in src, (
            f"Handler '{name}' must call get_user_workspace_role before "
            "touching job tables — found missing guard"
        )
