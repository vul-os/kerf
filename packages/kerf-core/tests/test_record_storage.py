"""Tests for kerf_core.db.queries.usage_events.record_storage (T-402 R8).

Covers:
- record_storage calls create_usage_event with kind='storage'
- bytes_delta is forwarded verbatim
- user_id and project_id strings are converted to UUID objects
- Zero bytes_delta is accepted (no-op row)
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# Fake asyncpg connection that captures the INSERT
# ---------------------------------------------------------------------------


class _FakeConn:
    """Records calls to fetchrow() so tests can inspect the inserted row."""

    def __init__(self, returned_row: Optional[Dict[str, Any]] = None):
        self.calls: List[tuple] = []
        self._returned_row = returned_row

    async def fetchrow(self, sql: str, *args: Any):
        self.calls.append((sql, args))
        if self._returned_row is not None:
            return self._returned_row
        # Build a minimal fake row that create_usage_event returns as dict(row).
        user_id = args[0] if args else None
        project_id = args[1] if len(args) > 1 else None
        kind = args[2] if len(args) > 2 else None
        bytes_delta = args[6] if len(args) > 6 else 0
        return {
            "id": str(uuid.uuid4()),
            "user_id": user_id,
            "project_id": project_id,
            "kind": kind,
            "model": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "bytes_delta": bytes_delta,
            "usd_cost": 0.0,
            "created_at": "now",
        }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_storage_kind_is_storage():
    """record_storage must insert a row with kind='storage'."""
    from kerf_core.db.queries.usage_events import record_storage

    uid = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    conn = _FakeConn()

    result = await record_storage(conn, uid, pid, 1024)

    assert result["kind"] == "storage"


@pytest.mark.asyncio
async def test_record_storage_bytes_delta_forwarded():
    """bytes_delta must be forwarded verbatim to create_usage_event."""
    from kerf_core.db.queries.usage_events import record_storage

    uid = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    conn = _FakeConn()

    result = await record_storage(conn, uid, pid, 512_000)

    assert result["bytes_delta"] == 512_000


@pytest.mark.asyncio
async def test_record_storage_user_and_project_ids_are_uuids():
    """record_storage must convert str IDs to uuid.UUID before the DB call."""
    from kerf_core.db.queries.usage_events import record_storage

    uid = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    conn = _FakeConn()

    await record_storage(conn, uid, pid, 100)

    assert len(conn.calls) == 1
    _, args = conn.calls[0]
    # create_usage_event passes user_id as first positional arg
    assert isinstance(args[0], uuid.UUID), f"expected UUID, got {type(args[0])}"
    assert str(args[0]) == uid
    assert isinstance(args[1], uuid.UUID), f"expected UUID, got {type(args[1])}"
    assert str(args[1]) == pid


@pytest.mark.asyncio
async def test_record_storage_zero_bytes_accepted():
    """Zero bytes_delta is accepted and produces a row with bytes_delta=0."""
    from kerf_core.db.queries.usage_events import record_storage

    uid = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    conn = _FakeConn()

    result = await record_storage(conn, uid, pid, 0)

    assert result["bytes_delta"] == 0


@pytest.mark.asyncio
async def test_record_storage_negative_bytes_accepted():
    """Negative bytes_delta (deletion) is accepted unchanged."""
    from kerf_core.db.queries.usage_events import record_storage

    uid = str(uuid.uuid4())
    pid = str(uuid.uuid4())
    conn = _FakeConn()

    result = await record_storage(conn, uid, pid, -4096)

    assert result["bytes_delta"] == -4096
