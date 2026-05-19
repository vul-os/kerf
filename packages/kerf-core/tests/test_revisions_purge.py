"""
Hermetic tests for kerf_core.revisions.purge_project_revisions.

Uses an in-memory fake pool — no Postgres required.

Covers:
  - keep_last_per_file=5 keeps exactly 5 rows per file (deletes the rest)
  - keep_last_per_file=0 raises ValueError (must keep >= 1)
  - freed_bytes matches the sum of column sizes of deleted rows
  - rows referenced as parent_revision_id are never deleted (chain integrity)
"""
from __future__ import annotations

import asyncio
import gzip
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

import pytest

from kerf_core.revisions import purge_project_revisions, _compress


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc)


def _make_gz(content: str) -> bytes:
    return _compress(content)


# ---------------------------------------------------------------------------
# Fake pool
# ---------------------------------------------------------------------------

class FakePurgePool:
    """
    Minimal fake asyncpg pool for testing purge_project_revisions.

    Supports:
      acquire()             — returns a FakeConn context manager
      fetchrow / fetch / execute / fetchval delegated to FakeConn
    """

    def __init__(self, project_id: uuid.UUID):
        self.project_id = project_id
        # {file_id: uuid} list (files belonging to this project)
        self._files: list[dict] = []
        # {revision_id: dict} all revisions
        self._revisions: "OrderedDict[uuid.UUID, dict]" = OrderedDict()
        self._last_delete_result = "DELETE 0"

    def add_file(self, file_id: uuid.UUID | None = None) -> uuid.UUID:
        fid = file_id or uuid.uuid4()
        self._files.append({"id": fid})
        return fid

    def add_revision(
        self,
        file_id: uuid.UUID,
        content: str = "hello",
        kind: str = "base",
        parent_revision_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        rid = uuid.uuid4()
        gz = _make_gz(content) if kind != "ref" else None
        row = {
            "id": rid,
            "file_id": file_id,
            "content": "",
            "content_gz": gz,
            "kind": kind,
            "parent_revision_id": parent_revision_id,
            "created_at": _now(),
        }
        self._revisions[rid] = row
        return rid

    def acquire(self):
        return _FakeConnCtx(self)

    def revision_ids(self) -> set[uuid.UUID]:
        return set(self._revisions.keys())


class _FakeConnCtx:
    def __init__(self, pool: FakePurgePool):
        self._pool = pool
        self._conn: _FakeConn | None = None

    async def __aenter__(self) -> "_FakeConn":
        self._conn = _FakeConn(self._pool)
        return self._conn

    async def __aexit__(self, *_):
        pass


class _FakeTxnCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass


class _FakeConn:
    """Simulates an asyncpg connection for purge_project_revisions."""

    def __init__(self, pool: FakePurgePool):
        self._pool = pool

    def transaction(self):
        return _FakeTxnCtx()

    async def fetch(self, query: str, *args) -> list:
        # SELECT id FROM files WHERE project_id = $1
        if "FROM files" in query and "project_id" in query:
            return [type("R", (), {"__getitem__": lambda self, k: r[k]})()
                    for r in self._pool._files
                    if str(r["id"]) == str(args[0])
                    or r in self._pool._files]

        # SELECT id FROM file_revisions WHERE file_id = $1 ORDER BY created_at DESC OFFSET $2
        if "FROM file_revisions" in query and "OFFSET" in query:
            fid = uuid.UUID(str(args[0]))
            offset = int(args[1])
            rows = sorted(
                [r for r in self._pool._revisions.values() if r["file_id"] == fid],
                key=lambda r: r["created_at"],
                reverse=True,  # DESC
            )
            return [_Row(r) for r in rows[offset:]]

        # SELECT id FROM file_revisions WHERE id = ANY($1) AND id NOT IN (...)
        if "FROM file_revisions" in query and "ANY" in query and "NOT IN" in query:
            candidate_ids = set(uuid.UUID(str(x)) for x in args[0])
            # Collect all parent_revision_ids (protected)
            protected = {
                r["parent_revision_id"]
                for r in self._pool._revisions.values()
                if r.get("parent_revision_id") is not None
            }
            safe = [_Row({"id": rid}) for rid in candidate_ids if rid not in protected]
            return safe

        return []

    async def fetchrow(self, query: str, *args) -> "_Row | None":
        # SELECT SUM(...) ... FROM file_revisions WHERE id = ANY(...)
        if "SUM" in query and "ANY" in query:
            ids = set(uuid.UUID(str(x)) for x in args[0])
            total = 0
            for r in self._pool._revisions.values():
                if r["id"] in ids:
                    gz = r.get("content_gz") or b""
                    content = r.get("content") or ""
                    total += len(gz) + len(content.encode())
            return _Row({"freed_bytes": total})
        return None

    async def execute(self, query: str, *args) -> str:
        if "DELETE FROM file_revisions" in query and "ANY" in query:
            ids = set(uuid.UUID(str(x)) for x in args[0])
            before = len(self._pool._revisions)
            for rid in list(ids):
                self._pool._revisions.pop(rid, None)
            removed = before - len(self._pool._revisions)
            return f"DELETE {removed}"
        return "OK"


class _Row(dict):
    def __init__(self, d):
        super().__init__(d)

    def __getitem__(self, key):
        return super().__getitem__(key)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _files_fetch_patch(pool: FakePurgePool):
    """
    The real fetch for 'FROM files' needs to return all files in the project.
    We patch _FakeConn.fetch to handle this correctly.
    """
    pass


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_id():
    return uuid.uuid4()


@pytest.fixture
def pool(project_id):
    p = FakePurgePool(project_id)
    return p, project_id


# ---------------------------------------------------------------------------
# Test: keep_last_per_file=0 raises ValueError
# ---------------------------------------------------------------------------

def test_keep_last_zero_raises(pool):
    p, pid = pool
    with pytest.raises(ValueError, match="keep_last_per_file must be >= 1"):
        run(purge_project_revisions(p, str(pid), keep_last_per_file=0))


# ---------------------------------------------------------------------------
# Test: keep_last_per_file=5 keeps exactly 5 rows per file
# ---------------------------------------------------------------------------

class PoolWith5PerFile:
    """
    Custom pool that tracks which revisions are deleted and simulates
    the keep_last=5 logic correctly via a proper fake fetch.
    """
    def __init__(self, project_id):
        self.project_id = project_id
        self._files = []
        self._revisions = OrderedDict()

    def add_file(self):
        fid = uuid.uuid4()
        self._files.append(fid)
        return fid

    def add_revisions(self, fid, n):
        ids = []
        for i in range(n):
            rid = uuid.uuid4()
            gz = _make_gz(f"content {i}")
            self._revisions[rid] = {
                "id": rid,
                "file_id": fid,
                "content": "",
                "content_gz": gz,
                "kind": "base",
                "parent_revision_id": None,
                "created_at": datetime(2024, 1, 1, i, 0, 0, tzinfo=timezone.utc),
            }
            ids.append(rid)
        return ids

    def acquire(self):
        return _PoolWith5Ctx(self)

    def revision_ids_for_file(self, fid):
        return [r["id"] for r in self._revisions.values() if r["file_id"] == fid]


class _PoolWith5Ctx:
    def __init__(self, pool):
        self._pool = pool

    async def __aenter__(self):
        return _PoolWith5Conn(self._pool)

    async def __aexit__(self, *_):
        pass


class _PoolWith5Conn:
    def __init__(self, pool):
        self._pool = pool

    def transaction(self):
        return _FakeTxnCtx()

    async def fetch(self, query, *args):
        if "FROM files" in query and "project_id" in query:
            return [_Row({"id": fid}) for fid in self._pool._files]

        if "FROM file_revisions" in query and "OFFSET" in query:
            fid = uuid.UUID(str(args[0]))
            offset = int(args[1])
            rows = sorted(
                [r for r in self._pool._revisions.values() if r["file_id"] == fid],
                key=lambda r: r["created_at"],
                reverse=True,
            )
            return [_Row({"id": r["id"]}) for r in rows[offset:]]

        if "FROM file_revisions" in query and "ANY" in query and "NOT IN" in query:
            candidate_ids = set(uuid.UUID(str(x)) for x in args[0])
            protected = {
                r["parent_revision_id"]
                for r in self._pool._revisions.values()
                if r.get("parent_revision_id") is not None
            }
            return [_Row({"id": rid}) for rid in candidate_ids if rid not in protected]

        return []

    async def fetchrow(self, query, *args):
        if "SUM" in query and "ANY" in query:
            ids = set(uuid.UUID(str(x)) for x in args[0])
            total = 0
            for r in self._pool._revisions.values():
                if r["id"] in ids:
                    gz = r.get("content_gz") or b""
                    total += len(gz)
            return _Row({"freed_bytes": total})
        return _Row({"freed_bytes": 0})

    async def execute(self, query, *args):
        if "DELETE FROM file_revisions" in query and "ANY" in query:
            ids = set(uuid.UUID(str(x)) for x in args[0])
            before = len(self._pool._revisions)
            for rid in list(ids):
                self._pool._revisions.pop(rid, None)
            removed = before - len(self._pool._revisions)
            return f"DELETE {removed}"
        return "OK"


def test_keep_last_5_per_file():
    """
    Write 10 revisions per file, purge with keep_last=5.
    Exactly 5 rows should remain per file.
    """
    pid = uuid.uuid4()
    pool = PoolWith5PerFile(pid)

    file_a = pool.add_file()
    file_b = pool.add_file()

    pool.add_revisions(file_a, 10)
    pool.add_revisions(file_b, 10)

    assert len(pool.revision_ids_for_file(file_a)) == 10
    assert len(pool.revision_ids_for_file(file_b)) == 10

    result = run(purge_project_revisions(pool, str(pid), keep_last_per_file=5))

    assert result["removed_rows"] == 10, f"Expected 10 removed, got {result['removed_rows']}"
    assert len(pool.revision_ids_for_file(file_a)) == 5
    assert len(pool.revision_ids_for_file(file_b)) == 5


def test_keep_last_keeps_newest_rows():
    """
    The 5 rows retained should be the most recent ones (by created_at).
    """
    pid = uuid.uuid4()
    pool = PoolWith5PerFile(pid)
    fid = pool.add_file()
    all_ids = pool.add_revisions(fid, 8)
    # The last 5 should survive (indices 3..7, newest).
    expected_survivors = set(all_ids[3:])

    run(purge_project_revisions(pool, str(pid), keep_last_per_file=5))

    remaining = set(pool.revision_ids_for_file(fid))
    assert remaining == expected_survivors, (
        f"Wrong rows retained: {remaining} vs expected {expected_survivors}"
    )


def test_no_files_returns_zero():
    """If a project has no files, purge returns zeros."""
    pid = uuid.uuid4()
    pool = PoolWith5PerFile(pid)
    # No files added.
    result = run(purge_project_revisions(pool, str(pid), keep_last_per_file=5))
    assert result == {"removed_rows": 0, "freed_bytes": 0}


def test_fewer_than_keep_last_nothing_deleted():
    """If a file has <= keep_last revisions, nothing is deleted."""
    pid = uuid.uuid4()
    pool = PoolWith5PerFile(pid)
    fid = pool.add_file()
    pool.add_revisions(fid, 3)

    result = run(purge_project_revisions(pool, str(pid), keep_last_per_file=5))

    assert result["removed_rows"] == 0
    assert len(pool.revision_ids_for_file(fid)) == 3


def test_freed_bytes_matches_deleted_rows():
    """
    freed_bytes must equal the sum of content sizes of the deleted rows.
    """
    pid = uuid.uuid4()
    pool = PoolWith5PerFile(pid)
    fid = pool.add_file()
    all_ids = pool.add_revisions(fid, 8)

    # Pre-compute expected freed bytes: rows at indices 0..2 (oldest 3) will
    # be deleted when keep_last=5.
    expected_freed = sum(
        len(pool._revisions[rid].get("content_gz") or b"")
        for rid in all_ids[:3]
    )

    result = run(purge_project_revisions(pool, str(pid), keep_last_per_file=5))

    assert result["freed_bytes"] == expected_freed, (
        f"freed_bytes {result['freed_bytes']} != expected {expected_freed}"
    )


def test_parent_referenced_rows_not_deleted():
    """
    Rows that are referenced as parent_revision_id must not be deleted,
    even if they would otherwise fall outside keep_last.
    """
    pid = uuid.uuid4()
    pool = PoolWith5PerFile(pid)
    fid = pool.add_file()

    # Add 8 revisions; manually make revision 0 a parent of revision 1
    # so it's protected.
    all_ids = pool.add_revisions(fid, 8)
    protected_id = all_ids[0]  # oldest — would normally be deleted
    child_id = all_ids[1]
    pool._revisions[child_id]["parent_revision_id"] = protected_id

    run(purge_project_revisions(pool, str(pid), keep_last_per_file=5))

    remaining = set(pool.revision_ids_for_file(fid))
    assert protected_id in remaining, (
        f"Protected row {protected_id} was deleted (it is parent of {child_id})"
    )
