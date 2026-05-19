"""Tests for GET /api/projects/{pid}/revisions/size.

Uses the mock-pool pattern from test_activity_route.py — no real database
needed. Four specs:
  1. 200 + correct shape for an empty project (zeros across the board)
  2. 200 + summed bytes for a project with N revisions across M files
  3. 404 when the project doesn't exist
  4. 404 when the caller is not a workspace member
"""
from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from kerf_api.routes import get_revisions_size


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _pool(rows=None):
    """Build a minimal asyncpg pool mock that returns `rows` from fetch()."""
    if rows is None:
        rows = []
    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=rows)
    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


def _call(pid="proj-1", rows=None, ws_id="ws-1", role="owner"):
    """Call get_revisions_size with patched DB dependencies."""
    cms = [
        patch("kerf_api.routes.get_pool_required",
              AsyncMock(return_value=_pool(rows))),
        patch("kerf_api.routes.project_workspace_id",
              AsyncMock(return_value=ws_id)),
        patch("kerf_api.routes.get_user_workspace_role",
              AsyncMock(return_value=role)),
    ]
    for cm in cms:
        cm.start()
    try:
        return _run(get_revisions_size(pid=pid, payload={"sub": "u-1"}))
    finally:
        for cm in reversed(cms):
            cm.stop()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Empty project — zeros across the board
# ─────────────────────────────────────────────────────────────────────────────

def test_empty_project_returns_200_shape():
    """An empty project returns the three required top-level keys."""
    result = _call(rows=[])
    assert isinstance(result, dict)
    assert "total_bytes" in result
    assert "revision_count" in result
    assert "by_file" in result


def test_empty_project_zeros():
    """An empty project has total_bytes=0 and revision_count=0."""
    result = _call(rows=[])
    assert result["total_bytes"] == 0
    assert result["revision_count"] == 0
    assert result["by_file"] == []


# ─────────────────────────────────────────────────────────────────────────────
# 2. Project with N revisions across M files — bytes are summed correctly
# ─────────────────────────────────────────────────────────────────────────────

def _make_row(file_id, file_name, bytes_val, count_val):
    """Build a mock asyncpg Record-like dict for a by-file result row."""
    return {
        "file_id": uuid.UUID(file_id) if isinstance(file_id, str) else file_id,
        "file_name": file_name,
        "bytes": bytes_val,
        "count": count_val,
    }


def test_summed_bytes_single_file():
    """A single file with revisions: total_bytes = file bytes, count propagated."""
    fid = "11111111-1111-1111-1111-111111111111"
    rows = [_make_row(fid, "main.jscad", 1_234_567, 87)]
    result = _call(rows=rows)
    assert result["total_bytes"] == 1_234_567
    assert result["revision_count"] == 87
    assert len(result["by_file"]) == 1
    entry = result["by_file"][0]
    assert entry["file_id"] == fid
    assert entry["file_name"] == "main.jscad"
    assert entry["bytes"] == 1_234_567
    assert entry["count"] == 87


def test_summed_bytes_multiple_files():
    """Multiple files: total_bytes and revision_count are the sum of all files."""
    fid1 = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    fid2 = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    rows = [
        _make_row(fid1, "bracket.step", 2_000_000, 50),
        _make_row(fid2, "assembly.jscad", 500_000, 30),
    ]
    result = _call(rows=rows)
    assert result["total_bytes"] == 2_500_000
    assert result["revision_count"] == 80
    assert len(result["by_file"]) == 2
    # Verify the first entry (assumed already ordered by the DB)
    assert result["by_file"][0]["file_id"] == fid1
    assert result["by_file"][1]["file_id"] == fid2


def test_by_file_entry_has_all_keys():
    """Each by_file entry must carry file_id, file_name, bytes, count."""
    fid = "cccccccc-cccc-cccc-cccc-cccccccccccc"
    rows = [_make_row(fid, "part.jscad", 999, 3)]
    result = _call(rows=rows)
    entry = result["by_file"][0]
    assert set(entry.keys()) == {"file_id", "file_name", "bytes", "count"}


# ─────────────────────────────────────────────────────────────────────────────
# 3. 404 when the project does not exist
# ─────────────────────────────────────────────────────────────────────────────

def test_404_when_project_not_found():
    """project_workspace_id returning None raises HTTP 404."""
    cms = [
        patch("kerf_api.routes.get_pool_required",
              AsyncMock(return_value=_pool())),
        patch("kerf_api.routes.project_workspace_id",
              AsyncMock(return_value=None)),
        patch("kerf_api.routes.get_user_workspace_role",
              AsyncMock(return_value=None)),
    ]
    for cm in cms:
        cm.start()
    try:
        with pytest.raises(HTTPException) as exc_info:
            _run(get_revisions_size(pid="missing-project", payload={"sub": "u-1"}))
    finally:
        for cm in reversed(cms):
            cm.stop()
    assert exc_info.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# 4. 404 when the caller is not a workspace member
# ─────────────────────────────────────────────────────────────────────────────

def test_404_when_not_workspace_member():
    """get_user_workspace_role returning None raises HTTP 404 (project hidden)."""
    cms = [
        patch("kerf_api.routes.get_pool_required",
              AsyncMock(return_value=_pool())),
        patch("kerf_api.routes.project_workspace_id",
              AsyncMock(return_value="ws-1")),
        patch("kerf_api.routes.get_user_workspace_role",
              AsyncMock(return_value=None)),
    ]
    for cm in cms:
        cm.start()
    try:
        with pytest.raises(HTTPException) as exc_info:
            _run(get_revisions_size(pid="proj-1", payload={"sub": "outsider"}))
    finally:
        for cm in reversed(cms):
            cm.stop()
    assert exc_info.value.status_code == 404
