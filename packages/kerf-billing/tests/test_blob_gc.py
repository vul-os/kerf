"""Integration + unit tests for the BlobGCWorker (T-136).

Integration tests require a live Postgres database.  Run with:

    DATABASE_URL="postgres://pc@localhost:5432/kerf?sslmode=disable" \\
        python3 -m pytest packages/kerf-billing/tests/test_blob_gc.py -q

Each integration test inserts uniquely-suffixed rows and cleans them up via
the autouse fixture.  No DROP / CREATE / TRUNCATE — shared live DB.

Safety invariants verified:
  1. zero-ref + oracle-says-unreachable + past-grace → object deleted from
     store + row removed from blob_objects.
  2. zero-ref but within grace window → kept.
  3. zero-ref but oracle says reachable → kept.
  4. oracle absent → nothing deleted (safe default).
  5. worker is idempotent (second tick on already-deleted oid is a no-op).

Unit tests (no DB) cover:
  - GitReachabilityOracle Protocol compliance.
  - BlobGCWorker construction and stop().
  - dry_run=True default prevents deletes.
  - _dry_run_from_env() parsing.
"""
from __future__ import annotations

import asyncio
import io
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
import pytest

from kerf_billing.blob_gc import BlobGCWorker, GitReachabilityOracle, _dry_run_from_env

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_TAG = "test-blob-gc-"

# ---------------------------------------------------------------------------
# Shared event loop (asyncpg connections are loop-bound)
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
# Minimal Storage stub
# ---------------------------------------------------------------------------

class _StubStorage:
    """In-memory storage stub: tracks puts/deletes; never raises."""

    def __init__(self):
        self._objects: dict[str, bytes] = {}
        self.deleted: list[str] = []

    async def put(self, key, body, content_type, size):
        self._objects[key] = body.read() if hasattr(body, "read") else body

    async def delete(self, key: str) -> None:
        self._objects.pop(key, None)
        self.deleted.append(key)

    async def get(self, key):
        data = self._objects.get(key, b"")
        return io.BytesIO(data), "application/octet-stream"

    def has(self, key: str) -> bool:
        return key in self._objects


class _RaisingStorage(_StubStorage):
    """Storage that raises on delete (to test error handling)."""

    async def delete(self, key: str) -> None:
        raise RuntimeError("tigris unavailable")


# ---------------------------------------------------------------------------
# Oracle stubs
# ---------------------------------------------------------------------------

class _AlwaysUnreachableOracle:
    """Oracle that says every oid is unreachable (all eligible for GC)."""

    def is_oid_reachable(self, oid: str) -> bool:
        return False

    def last_unreachable_at(self, oid: str) -> Optional[datetime]:
        return datetime.now(tz=timezone.utc) - timedelta(hours=100)


class _AlwaysReachableOracle:
    """Oracle that says every oid is reachable (nothing eligible for GC)."""

    def is_oid_reachable(self, oid: str) -> bool:
        return True

    def last_unreachable_at(self, oid: str) -> Optional[datetime]:
        return None


# ---------------------------------------------------------------------------
# Pool stub for unit tests (no real DB)
# ---------------------------------------------------------------------------

class _EmptyConn:
    """Conn that returns empty candidates so _tick completes immediately."""

    async def fetch(self, sql, *args):
        return []

    async def fetchrow(self, sql, *args):
        return None

    async def fetchval(self, sql, *args):
        return False

    async def execute(self, sql, *args):
        return "UPDATE 0"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    def transaction(self):
        return self


class _EmptyPool:
    def acquire(self):
        conn = _EmptyConn()

        class _Acq:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *a):
                pass

        return _Acq()


# ---------------------------------------------------------------------------
# DB helpers (integration only)
# ---------------------------------------------------------------------------

async def _make_user(conn: asyncpg.Connection) -> uuid.UUID:
    uid = uuid.uuid4()
    email = f"{_TAG}{uid.hex}@test.invalid"
    await conn.execute(
        "INSERT INTO users (id, email, name) VALUES ($1, $2, $3)",
        uid, email, f"Test GC User {uid}",
    )
    return uid


async def _make_workspace(conn: asyncpg.Connection, owner_id: uuid.UUID) -> uuid.UUID:
    ws_id = uuid.uuid4()
    slug = f"{_TAG}{ws_id.hex}"
    await conn.execute(
        "INSERT INTO workspaces (id, slug, name, created_by) VALUES ($1, $2, $3, $4)",
        ws_id, slug, f"Test GC WS {ws_id}", owner_id,
    )
    return ws_id


async def _make_project(conn: asyncpg.Connection, ws_id: uuid.UUID) -> uuid.UUID:
    proj_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO projects (id, workspace_id, name) VALUES ($1, $2, $3)",
        proj_id, ws_id, f"{_TAG}proj-{proj_id}",
    )
    return proj_id


async def _insert_blob_past_grace(
    conn: asyncpg.Connection, oid: str, size: int = 1024
) -> None:
    """Insert a blob_objects row with timestamps already past the 72-hour window."""
    past = datetime.now(tz=timezone.utc) - timedelta(hours=80)
    await conn.execute(
        """
        INSERT INTO blob_objects (oid, size_bytes, created_at, last_unref_at)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (oid) DO NOTHING
        """,
        oid, size, past, past,
    )


async def _insert_blob_within_grace(
    conn: asyncpg.Connection, oid: str, size: int = 1024
) -> None:
    """Insert a blob_objects row with last_unref_at only 1 hour ago (within grace)."""
    past_created = datetime.now(tz=timezone.utc) - timedelta(hours=80)
    recent_unref = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    await conn.execute(
        """
        INSERT INTO blob_objects (oid, size_bytes, created_at, last_unref_at)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (oid) DO NOTHING
        """,
        oid, size, past_created, recent_unref,
    )


async def _blob_row_exists(conn: asyncpg.Connection, oid: str) -> bool:
    val = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM blob_objects WHERE oid = $1)", oid
    )
    return bool(val)


async def _cleanup(conn: asyncpg.Connection) -> None:
    await conn.execute("DELETE FROM blob_refs    WHERE oid LIKE $1", f"{_TAG}%")
    await conn.execute("DELETE FROM blob_objects WHERE oid LIKE $1", f"{_TAG}%")
    await conn.execute(
        "DELETE FROM projects   WHERE name LIKE $1", f"{_TAG}%"
    )
    await conn.execute("DELETE FROM workspaces  WHERE slug LIKE $1", f"{_TAG}%")
    await conn.execute(
        "DELETE FROM users      WHERE email LIKE $1", f"{_TAG}%@test.invalid"
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def conn():
    if not DATABASE_URL:
        pytest.skip("DATABASE_URL not set")
    connection = run(asyncpg.connect(DATABASE_URL))
    yield connection
    run(connection.close())


@pytest.fixture(autouse=True)
def cleanup(conn):
    yield
    run(_cleanup(conn))


# ---------------------------------------------------------------------------
# Pool wrapper around a single asyncpg connection (for worker)
# ---------------------------------------------------------------------------

class _SingleConnPool:
    """Wraps a bare asyncpg connection so it looks like a pool.acquire() pool."""

    def __init__(self, conn: asyncpg.Connection):
        self._conn = conn

    def acquire(self):
        conn = self._conn

        class _Acq:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *a):
                pass

        return _Acq()


# ---------------------------------------------------------------------------
# Integration: zero-ref + oracle-says-unreachable + past-grace → deleted
# ---------------------------------------------------------------------------

class TestBlobGCIntegration:
    def test_deletes_eligible_oid(self, conn):
        """The happy path: zero-ref, unreachable, past 72 h → storage + row gone."""
        oid = f"{_TAG}{uuid.uuid4().hex}"
        size = 512

        run(_insert_blob_past_grace(conn, oid, size))
        assert run(_blob_row_exists(conn, oid))

        storage = _StubStorage()
        from kerf_core.storage.materialize import blob_storage_key
        key = blob_storage_key(oid)
        run(storage.put(key, io.BytesIO(b"x" * size), "application/octet-stream", size))

        pool = _SingleConnPool(conn)
        worker = BlobGCWorker(pool, storage, interval_seconds=9999, dry_run=False)
        worker.set_oracle(_AlwaysUnreachableOracle())

        run(worker._tick())

        assert not run(_blob_row_exists(conn, oid)), "blob_objects row should be removed"
        assert key in storage.deleted, "storage.delete should have been called"

    def test_within_grace_kept(self, conn):
        """Zero-ref but last_unref_at < 72 h ago → row and object preserved."""
        oid = f"{_TAG}{uuid.uuid4().hex}"

        run(_insert_blob_within_grace(conn, oid))
        assert run(_blob_row_exists(conn, oid))

        storage = _StubStorage()
        pool = _SingleConnPool(conn)
        worker = BlobGCWorker(pool, storage, interval_seconds=9999, dry_run=False)
        worker.set_oracle(_AlwaysUnreachableOracle())

        run(worker._tick())

        # Still there.
        assert run(_blob_row_exists(conn, oid)), "within-grace oid must not be deleted"
        assert not storage.deleted, "storage.delete must not be called"

    def test_oracle_reachable_kept(self, conn):
        """Oracle says reachable → row and object preserved regardless of age."""
        oid = f"{_TAG}{uuid.uuid4().hex}"

        run(_insert_blob_past_grace(conn, oid))
        assert run(_blob_row_exists(conn, oid))

        storage = _StubStorage()
        from kerf_core.storage.materialize import blob_storage_key
        key = blob_storage_key(oid)
        run(storage.put(key, io.BytesIO(b"data"), "application/octet-stream", 4))

        pool = _SingleConnPool(conn)
        worker = BlobGCWorker(pool, storage, interval_seconds=9999, dry_run=False)
        worker.set_oracle(_AlwaysReachableOracle())

        run(worker._tick())

        assert run(_blob_row_exists(conn, oid)), "reachable oid must not be deleted"
        assert not storage.deleted

    def test_oracle_absent_nothing_deleted(self, conn):
        """No oracle registered → safe default: nothing deleted."""
        oid = f"{_TAG}{uuid.uuid4().hex}"

        run(_insert_blob_past_grace(conn, oid))
        assert run(_blob_row_exists(conn, oid))

        storage = _StubStorage()
        pool = _SingleConnPool(conn)
        worker = BlobGCWorker(pool, storage, interval_seconds=9999, dry_run=False)
        # Deliberately do NOT call set_oracle().

        run(worker._tick())

        assert run(_blob_row_exists(conn, oid)), "oracle-absent must not delete"
        assert not storage.deleted

    def test_idempotent_second_tick(self, conn):
        """Second tick after a successful delete is a clean no-op."""
        oid = f"{_TAG}{uuid.uuid4().hex}"

        run(_insert_blob_past_grace(conn, oid))
        storage = _StubStorage()
        from kerf_core.storage.materialize import blob_storage_key
        key = blob_storage_key(oid)
        run(storage.put(key, io.BytesIO(b"bytes"), "application/octet-stream", 5))

        pool = _SingleConnPool(conn)
        worker = BlobGCWorker(pool, storage, interval_seconds=9999, dry_run=False)
        worker.set_oracle(_AlwaysUnreachableOracle())

        run(worker._tick())
        assert not run(_blob_row_exists(conn, oid))
        assert key in storage.deleted

        # Second tick: the row is already gone — should not raise or re-delete.
        deleted_before = list(storage.deleted)
        run(worker._tick())
        assert storage.deleted == deleted_before, "second tick must not call delete again"

    def test_dry_run_default_no_delete(self, conn):
        """dry_run=True (default) must never touch storage or DB rows."""
        oid = f"{_TAG}{uuid.uuid4().hex}"

        run(_insert_blob_past_grace(conn, oid))

        storage = _StubStorage()
        pool = _SingleConnPool(conn)
        # dry_run defaults to True
        worker = BlobGCWorker(pool, storage, interval_seconds=9999)
        worker.set_oracle(_AlwaysUnreachableOracle())

        run(worker._tick())

        assert run(_blob_row_exists(conn, oid)), "dry_run must not delete row"
        assert not storage.deleted

    def test_storage_error_does_not_delete_row(self, conn):
        """If the storage backend raises, the blob_objects row is preserved."""
        oid = f"{_TAG}{uuid.uuid4().hex}"

        run(_insert_blob_past_grace(conn, oid))

        storage = _RaisingStorage()
        pool = _SingleConnPool(conn)
        worker = BlobGCWorker(pool, storage, interval_seconds=9999, dry_run=False)
        worker.set_oracle(_AlwaysUnreachableOracle())

        run(worker._tick())  # must not raise

        assert run(_blob_row_exists(conn, oid)), "row must survive a storage error"


# ---------------------------------------------------------------------------
# Unit tests (no DB required)
# ---------------------------------------------------------------------------

class TestGitReachabilityOracleProtocol:
    def test_protocol_satisfied_by_always_unreachable(self):
        oracle = _AlwaysUnreachableOracle()
        assert isinstance(oracle, GitReachabilityOracle)

    def test_protocol_satisfied_by_always_reachable(self):
        oracle = _AlwaysReachableOracle()
        assert isinstance(oracle, GitReachabilityOracle)

    def test_protocol_not_satisfied_by_missing_methods(self):
        class Bad:
            def is_oid_reachable(self, oid):
                return False
            # missing last_unreachable_at

        assert not isinstance(Bad(), GitReachabilityOracle)


class TestBlobGCWorkerUnit:
    def test_constructible(self):
        pool = _EmptyPool()
        storage = _StubStorage()
        w = BlobGCWorker(pool, storage, interval_seconds=60.0)
        assert w.name == "blob_gc"
        assert w.dry_run is True
        assert not w._shutdown

    def test_stoppable(self):
        pool = _EmptyPool()
        storage = _StubStorage()
        w = BlobGCWorker(pool, storage)
        w.stop()
        assert w._shutdown

    def test_set_oracle(self):
        pool = _EmptyPool()
        storage = _StubStorage()
        w = BlobGCWorker(pool, storage)
        assert w._oracle is None
        w.set_oracle(_AlwaysUnreachableOracle())
        assert w._oracle is not None

    def test_tick_no_candidates_no_error(self):
        """A tick with zero candidates completes without error."""
        pool = _EmptyPool()
        storage = _StubStorage()
        w = BlobGCWorker(pool, storage, dry_run=False)
        w.set_oracle(_AlwaysUnreachableOracle())
        run(w._tick())  # must not raise


class TestDryRunFromEnv:
    def test_default_true(self, monkeypatch):
        monkeypatch.delenv("BLOB_GC_DRY_RUN", raising=False)
        assert _dry_run_from_env() is True

    def test_true_string(self, monkeypatch):
        monkeypatch.setenv("BLOB_GC_DRY_RUN", "true")
        assert _dry_run_from_env() is True

    def test_false_string(self, monkeypatch):
        monkeypatch.setenv("BLOB_GC_DRY_RUN", "false")
        assert _dry_run_from_env() is False

    def test_zero_string(self, monkeypatch):
        monkeypatch.setenv("BLOB_GC_DRY_RUN", "0")
        assert _dry_run_from_env() is False

    def test_no_string(self, monkeypatch):
        monkeypatch.setenv("BLOB_GC_DRY_RUN", "no")
        assert _dry_run_from_env() is False

    def test_one_string(self, monkeypatch):
        monkeypatch.setenv("BLOB_GC_DRY_RUN", "1")
        assert _dry_run_from_env() is True
