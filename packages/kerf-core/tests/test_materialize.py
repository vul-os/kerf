"""Integration tests for the git-as-substrate core write-loop (T-124).

Proves the full pipeline against a live Postgres + a local (temp-dir)
object-storage backend + a real pygit2 bare repo:

  * a >1 MiB file and a binary file are offloaded: bytes land in the object
    store under their sha256-derived key, ``blob_objects`` + ``blob_refs``
    rows are written, and the git tree at that path holds the *exact*
    canonical Git-LFS pointer text (not the bytes);
  * a small UTF-8 file is inlined: the git tree holds the verbatim content;
  * ``read_path`` round-trips both kinds back to their original bytes;
  * nested directory paths are preserved in the tree;
  * re-committing identical large content is idempotent (dedup: one ledger
    row, one object key) — the cheap-fork property.

Requires a live database. Run with:

    DATABASE_URL="postgres://pc@localhost:5432/kerf?sslmode=disable" \
        python3 -m pytest packages/kerf-core/tests/test_materialize.py -q
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import uuid

import asyncpg
import pygit2
import pytest

from kerf_core.storage.factory import create_storage
from kerf_core.storage.lfs_pointer import serialize as serialize_pointer
from kerf_core.storage.materialize import (
    FileEntry,
    blob_storage_key,
    materialize_and_commit,
    read_path,
)

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_TAG = "test-materialize-"

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
# DB fixtures (mirrors test_blob_objects.py conventions; self-cleaning)
# ---------------------------------------------------------------------------

async def _make_user(conn: asyncpg.Connection) -> uuid.UUID:
    uid = uuid.uuid4()
    await conn.execute(
        "INSERT INTO users (id, email, name) VALUES ($1, $2, $3)",
        uid, f"{_TAG}{uid.hex}@test.invalid", f"Test Mat User {uid}",
    )
    return uid


async def _make_workspace(conn: asyncpg.Connection, owner_id: uuid.UUID) -> uuid.UUID:
    ws_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO workspaces (id, slug, name, created_by) VALUES ($1, $2, $3, $4)",
        ws_id, f"{_TAG}{ws_id.hex}", f"Test WS {ws_id}", owner_id,
    )
    return ws_id


async def _make_project(conn: asyncpg.Connection, ws_id: uuid.UUID) -> uuid.UUID:
    proj_id = uuid.uuid4()
    await conn.execute(
        "INSERT INTO projects (id, workspace_id, name) VALUES ($1, $2, $3)",
        proj_id, ws_id, f"test-materialize-proj-{proj_id}",
    )
    return proj_id


async def _make_fixtures(conn: asyncpg.Connection):
    owner_id = await _make_user(conn)
    ws_id = await _make_workspace(conn, owner_id)
    proj_id = await _make_project(conn, ws_id)
    return ws_id, proj_id


async def _cleanup(conn: asyncpg.Connection) -> None:
    await conn.execute(
        "DELETE FROM blob_refs WHERE project_id IN "
        "(SELECT id FROM projects WHERE name LIKE $1)",
        "test-materialize-proj-%",
    )
    await conn.execute(
        "DELETE FROM blob_objects WHERE first_workspace_id IN "
        "(SELECT id FROM workspaces WHERE slug LIKE $1)",
        f"{_TAG}%",
    )
    await conn.execute("DELETE FROM projects  WHERE name LIKE $1", "test-materialize-proj-%")
    await conn.execute("DELETE FROM workspaces WHERE slug LIKE $1", f"{_TAG}%")
    await conn.execute("DELETE FROM users      WHERE email LIKE $1", f"{_TAG}%@test.invalid")


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


@pytest.fixture()
def workdir():
    with tempfile.TemporaryDirectory(prefix="kerf-mat-") as d:
        yield d


@pytest.fixture()
def storage(workdir):
    return create_storage(backend="local", local_storage_path=os.path.join(workdir, "objs"))


def _repo_dir(workdir: str) -> str:
    return os.path.join(workdir, "repo.git")


# ---------------------------------------------------------------------------
# Helpers to peek at the committed git tree
# ---------------------------------------------------------------------------

def _tree_bytes_at(repo_dir: str, path: str, ref: str = "HEAD") -> bytes:
    repo = pygit2.Repository(repo_dir)
    commit = repo.revparse_single(ref)
    tree = commit.tree if isinstance(commit, pygit2.Commit) else commit.peel(pygit2.Commit).tree
    entry = tree[path]
    return bytes(repo[entry.id].data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_large_file_offloaded_to_blob(conn, storage, workdir):
    ws_id, proj_id = run(_make_fixtures(conn))
    repo_dir = _repo_dir(workdir)

    big = b"A" * (1_048_576 + 10)  # > git_inline_max_bytes (1 MiB)
    oid = hashlib.sha256(big).hexdigest()

    result = run(materialize_and_commit(
        repo_dir=repo_dir,
        files=[FileEntry(path="models/big.step", content=big)],
        project_id=proj_id,
        workspace_id=ws_id,
        storage=storage,
        db_conn=conn,
        message="add big step",
    ))

    assert result.blobs == {"models/big.step": oid}
    assert result.inlined == []

    # Bytes are in the object store under the sha256-derived key.
    obj_path = os.path.join(workdir, "objs", blob_storage_key(oid))
    assert os.path.isfile(obj_path)
    with open(obj_path, "rb") as f:
        assert f.read() == big

    # Ledger rows exist.
    bo = run(conn.fetchrow(
        "SELECT size_bytes, first_workspace_id FROM blob_objects WHERE oid = $1", oid
    ))
    assert bo is not None
    assert bo["size_bytes"] == len(big)
    assert bo["first_workspace_id"] == ws_id

    refcount = run(conn.fetchval(
        "SELECT COUNT(*) FROM blob_refs WHERE oid = $1 AND project_id = $2 AND path = $3",
        oid, proj_id, "models/big.step",
    ))
    assert int(refcount) == 1

    # Git tree at the path holds the EXACT canonical LFS pointer, not bytes.
    tree_blob = _tree_bytes_at(repo_dir, "models/big.step")
    assert tree_blob == serialize_pointer(oid, len(big))
    assert tree_blob != big


def test_binary_file_offloaded_even_when_small(conn, storage, workdir):
    ws_id, proj_id = run(_make_fixtures(conn))
    repo_dir = _repo_dir(workdir)

    # Small but non-UTF-8 → classify forces a blob.
    binary = bytes(range(256)) * 4  # 1 KiB, invalid UTF-8
    oid = hashlib.sha256(binary).hexdigest()

    result = run(materialize_and_commit(
        repo_dir=repo_dir,
        files=[FileEntry(path="assets/icon.bin", content=binary)],
        project_id=proj_id,
        workspace_id=ws_id,
        storage=storage,
        db_conn=conn,
        message="add binary",
    ))

    assert result.blobs == {"assets/icon.bin": oid}

    obj_path = os.path.join(workdir, "objs", blob_storage_key(oid))
    with open(obj_path, "rb") as f:
        assert f.read() == binary

    tree_blob = _tree_bytes_at(repo_dir, "assets/icon.bin")
    assert tree_blob == serialize_pointer(oid, len(binary))


def test_small_utf8_file_inlined_verbatim(conn, storage, workdir):
    ws_id, proj_id = run(_make_fixtures(conn))
    repo_dir = _repo_dir(workdir)

    src = "def main():\n    return 'hello kerf'\n".encode("utf-8")

    result = run(materialize_and_commit(
        repo_dir=repo_dir,
        files=[FileEntry(path="src/main.py", content=src)],
        project_id=proj_id,
        workspace_id=ws_id,
        storage=storage,
        db_conn=conn,
        message="add source",
    ))

    assert result.inlined == ["src/main.py"]
    assert result.blobs == {}

    # Verbatim content in the git tree — no pointer, no blob row.
    tree_blob = _tree_bytes_at(repo_dir, "src/main.py")
    assert tree_blob == src

    count = run(conn.fetchval("SELECT COUNT(*) FROM blob_refs WHERE project_id = $1", proj_id))
    assert int(count) == 0


def test_round_trip_reads_reconstruct_both(conn, storage, workdir):
    ws_id, proj_id = run(_make_fixtures(conn))
    repo_dir = _repo_dir(workdir)

    big = os.urandom(1_500_000)          # > 1 MiB, binary → blob
    small = "small text payload\n".encode("utf-8")  # → inline

    run(materialize_and_commit(
        repo_dir=repo_dir,
        files=[
            FileEntry(path="cad/model.step", content=big),
            FileEntry(path="README.md", content=small),
        ],
        project_id=proj_id,
        workspace_id=ws_id,
        storage=storage,
        db_conn=conn,
        message="mixed commit",
    ))

    got_big = run(read_path(repo_dir=repo_dir, path="cad/model.step", storage=storage))
    got_small = run(read_path(repo_dir=repo_dir, path="README.md", storage=storage))

    assert got_big == big
    assert got_small == small


def test_nested_dirs_preserved_and_history_chained(conn, storage, workdir):
    ws_id, proj_id = run(_make_fixtures(conn))
    repo_dir = _repo_dir(workdir)

    r1 = run(materialize_and_commit(
        repo_dir=repo_dir,
        files=[FileEntry(path="a/b/c/deep.txt", content=b"depth ok\n")],
        project_id=proj_id,
        workspace_id=ws_id,
        storage=storage,
        db_conn=conn,
        message="commit 1",
    ))
    r2 = run(materialize_and_commit(
        repo_dir=repo_dir,
        files=[FileEntry(path="a/b/c/deep.txt", content=b"depth ok v2\n")],
        project_id=proj_id,
        workspace_id=ws_id,
        storage=storage,
        db_conn=conn,
        message="commit 2",
    ))

    assert r1.commit_sha != r2.commit_sha
    assert _tree_bytes_at(repo_dir, "a/b/c/deep.txt") == b"depth ok v2\n"

    repo = pygit2.Repository(repo_dir)
    head = repo.revparse_single("HEAD").peel(pygit2.Commit)
    assert str(head.id) == r2.commit_sha
    assert len(head.parents) == 1
    assert str(head.parents[0].id) == r1.commit_sha


def test_identical_large_content_is_deduped(conn, storage, workdir):
    """Cheap-fork property: same bytes at two paths → one object, one oid row."""
    ws_id, proj_id = run(_make_fixtures(conn))
    repo_dir = _repo_dir(workdir)

    payload = b"\x00\x01\x02" * 600_000  # ~1.8 MiB binary
    oid = hashlib.sha256(payload).hexdigest()

    run(materialize_and_commit(
        repo_dir=repo_dir,
        files=[
            FileEntry(path="dup/one.bin", content=payload),
            FileEntry(path="dup/two.bin", content=payload),
        ],
        project_id=proj_id,
        workspace_id=ws_id,
        storage=storage,
        db_conn=conn,
        message="two refs one blob",
    ))

    # Exactly one blob_objects row for the shared oid.
    bo_count = run(conn.fetchval("SELECT COUNT(*) FROM blob_objects WHERE oid = $1", oid))
    assert int(bo_count) == 1

    # Two refs (distinct paths), same oid.
    ref_count = run(conn.fetchval(
        "SELECT COUNT(*) FROM blob_refs WHERE oid = $1 AND project_id = $2", oid, proj_id
    ))
    assert int(ref_count) == 2

    # One physical object on disk.
    obj_path = os.path.join(workdir, "objs", blob_storage_key(oid))
    assert os.path.isfile(obj_path)

    # Both tree paths carry the same pointer.
    ptr = serialize_pointer(oid, len(payload))
    assert _tree_bytes_at(repo_dir, "dup/one.bin") == ptr
    assert _tree_bytes_at(repo_dir, "dup/two.bin") == ptr


def test_threshold_override_forces_inline_or_blob(conn, storage, workdir):
    ws_id, proj_id = run(_make_fixtures(conn))
    repo_dir = _repo_dir(workdir)

    payload = b"x" * 2048  # valid UTF-8, 2 KiB

    # threshold=1024 → 2 KiB exceeds it → blob even though it's text.
    result = run(materialize_and_commit(
        repo_dir=repo_dir,
        files=[FileEntry(path="cfg/data.txt", content=payload)],
        project_id=proj_id,
        workspace_id=ws_id,
        storage=storage,
        db_conn=conn,
        message="thresholded",
        threshold=1024,
    ))
    assert "cfg/data.txt" in result.blobs
    assert result.inlined == []
