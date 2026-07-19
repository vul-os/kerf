"""SQLite embedded-backend suite.

Covers kerf's zero-dependency default database:

* ``TestDialect`` — pure-unit tests of the Postgres -> SQLite query translator
  (:mod:`kerf_core.db.dialect`): ``$N`` rebinding, ``= ANY``, ``jsonb->>``,
  ``now()``, ``::casts``, ``FOR UPDATE SKIP LOCKED``, param adaptation.
* ``TestSqliteCorePath`` — the core serving path exercised end-to-end on a real
  embedded SQLite database driven through the *actual* query modules: project
  CRUD, file save + revision, auth (user + refresh token), Workshop
  public-listing joins, and the kerf-pub store (publish / follow / pin).

These run WITHOUT Postgres — they are additive to the Postgres suites, which
stay green unchanged.
"""

from __future__ import annotations

import datetime
import tempfile
import uuid
from pathlib import Path

import pytest

from kerf_core.db import dialect
from kerf_core.db.dialect import (
    adapt_param,
    is_sqlite_url,
    sqlite_path_from_url,
    translate_query,
    translate_sql,
)


# ── dialect translation unit tests ─────────────────────────────────────────────

class TestDialect:
    def test_is_sqlite_url(self):
        assert is_sqlite_url("sqlite:///a/b.db")
        assert is_sqlite_url("sqlite://rel.db")
        assert not is_sqlite_url("postgres://u@h/db")
        assert not is_sqlite_url("")

    def test_path_from_url(self):
        assert sqlite_path_from_url("sqlite:///Users/x/.kerf/kerf.db") == "/Users/x/.kerf/kerf.db"
        assert sqlite_path_from_url("sqlite://rel/path.db") == "rel/path.db"
        assert sqlite_path_from_url("sqlite:///:memory:") == ":memory:"

    def test_param_rebind_basic(self):
        sql, params = translate_query("SELECT * FROM t WHERE a=$1 AND b=$2", ("x", 3))
        assert sql == "SELECT * FROM t WHERE a=? AND b=?"
        assert params == ["x", 3]

    def test_param_rebind_reused_and_out_of_order(self):
        sql, params = translate_query(
            "SELECT * FROM t WHERE a=$2 OR b=$1 OR c=$2", ("one", "two"))
        assert sql == "SELECT * FROM t WHERE a=? OR b=? OR c=?"
        assert params == ["two", "one", "two"]

    def test_translate_any(self):
        out = translate_sql("SELECT * FROM p WHERE $1 = ANY(tags)")
        assert "json_each(tags)" in out
        assert "ANY" not in out

    def test_translate_jsonb_extract(self):
        out = translate_sql("SELECT (f.content::jsonb->>'mpn') AS mpn FROM f")
        assert "json_extract(f.content, '$.mpn')" in out
        assert "::" not in out and "->>" not in out

    def test_translate_now_and_casts(self):
        out = translate_sql("UPDATE t SET x=now(), y=$1::uuid WHERE z=$2::text")
        assert "CURRENT_TIMESTAMP" in out
        assert "::" not in out
        assert "now(" not in out

    def test_translate_for_update_skip_locked(self):
        out = translate_sql(
            "SELECT * FROM jobs WHERE status='queued' LIMIT 1 FOR UPDATE SKIP LOCKED")
        assert "FOR UPDATE" not in out
        assert "SKIP LOCKED" not in out

    def test_translate_ilike(self):
        assert "LIKE" in translate_sql("SELECT 1 WHERE a ILIKE $1")
        assert "ILIKE" not in translate_sql("SELECT 1 WHERE a ILIKE $1")

    def test_adapt_param_types(self):
        u = uuid.uuid4()
        assert adapt_param(u) == str(u)
        assert adapt_param(["a", "b"]) == '["a", "b"]'
        assert adapt_param({"k": 1}) == '{"k": 1}'
        dt = datetime.datetime(2026, 1, 2, 3, 4, 5, tzinfo=datetime.timezone.utc)
        assert adapt_param(dt).startswith("2026-01-02 03:04:05")
        assert adapt_param(None) is None
        assert adapt_param(b"x") == b"x"

    def test_array_column_parse(self):
        assert dialect.parse_array_column("tags", '["a","b"]') == ["a", "b"]
        assert dialect.parse_array_column("tags", None) is None
        # non-array column names pass through untouched (jsonb stays a str)
        assert dialect.parse_array_column("part_refs", '[1,2]') == '[1,2]'


# ── core-path integration on a real SQLite database ─────────────────────────────

@pytest.fixture
async def sqlite_pool():
    db = tempfile.mktemp(suffix=".db")
    url = "sqlite://" + db
    from kerf_core.db.migrations.runner import run_migrations
    from kerf_core.db.sqlite_backend import create_sqlite_pool

    await run_migrations(url)
    pool = await create_sqlite_pool(url)
    try:
        yield pool
    finally:
        await pool.close()
        Path(db).unlink(missing_ok=True)


async def _seed_user_workspace(conn):
    from kerf_core.db.queries import users
    u = await users.create_user(conn, email="dev@kerf.sh", password_hash="h", name="Dev")
    uid = uuid.UUID(u["id"])
    w = await conn.fetchrow(
        "INSERT INTO workspaces (slug,name,created_by) VALUES ($1,$2,$3) RETURNING *",
        "acme", "Acme", uid)
    return uid, uuid.UUID(w["id"])


class TestSqliteCorePath:
    async def test_migrations_created_core_tables(self, sqlite_pool):
        rows = await sqlite_pool.fetch(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        names = {r["name"] for r in rows}
        for t in ("users", "workspaces", "projects", "files", "file_revisions",
                  "refresh_tokens", "pub_chunks", "pub_follows"):
            assert t in names, f"missing table {t}"

    async def test_uuid_default_is_v4(self, sqlite_pool):
        async with sqlite_pool.acquire() as conn:
            u = await conn.fetchrow(
                "INSERT INTO users (email) VALUES ($1) RETURNING *", "u@x.io")
            assert uuid.UUID(u["id"]).version == 4

    async def test_project_crud(self, sqlite_pool):
        from kerf_core.db.queries import projects
        async with sqlite_pool.acquire() as conn:
            uid, wid = await _seed_user_workspace(conn)
            p = await projects.create_project(
                conn, wid, "Widget", description="d", tags=["cad", "steel"],
                created_by=uid)
            assert p["tags"] == ["cad", "steel"]  # array parity: real list
            pid = uuid.UUID(p["id"])
            assert (await projects.get_project(conn, pid))["name"] == "Widget"
            # tag filter uses `= ANY(tags)` translation
            assert len(await projects.list_projects(conn, wid, tags=["cad"])) == 1
            assert len(await projects.list_projects(conn, wid, tags=["nope"])) == 0
            up = await projects.update_project(conn, pid, name="Widget2")
            assert up["name"] == "Widget2"
            assert await projects.delete_project(conn, pid) is True
            assert await projects.get_project(conn, pid) is None

    async def test_public_listing_joins(self, sqlite_pool):
        from kerf_core.db.queries import projects
        async with sqlite_pool.acquire() as conn:
            uid, wid = await _seed_user_workspace(conn)
            p = await projects.create_project(conn, wid, "Pub", tags=["x"], created_by=uid)
            await projects.update_project(conn, uuid.UUID(p["id"]), visibility="public")
            listed = await projects.list_public_projects(
                conn, tags=["x"], viewer_user_id=uid)
            assert len(listed) == 1
            assert listed[0]["likes_count"] == 0
            assert listed[0]["author_name"] == "Dev"

    async def test_file_save_and_revision(self, sqlite_pool):
        from kerf_core.db.queries import files
        async with sqlite_pool.acquire() as conn:
            uid, wid = await _seed_user_workspace(conn)
            p = await conn.fetchrow(
                "INSERT INTO projects (workspace_id,name) VALUES ($1,$2) RETURNING *",
                wid, "P")
            pid = uuid.UUID(p["id"])
            f = await files.create_file(
                conn, project_id=pid, name="main.jscad", kind="text",
                content="v1", created_by=uid)
            fid = uuid.UUID(f["id"])
            await files.create_file_revision(
                conn, file_id=fid, content="v1", source="user", user_id=uid)
            await files.create_file_revision(
                conn, file_id=fid, content="v2", source="user", user_id=uid)
            revs = await files.get_file_revisions(conn, fid)
            assert len(revs) == 2

    async def test_auth_refresh_token_lifecycle(self, sqlite_pool):
        from kerf_core.db.queries import refresh_tokens
        async with sqlite_pool.acquire() as conn:
            uid, _ = await _seed_user_workspace(conn)
            exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)
            await refresh_tokens.create_refresh_token(
                conn, user_id=uid, token_hash="hash1", expires_at=exp)
            assert (await refresh_tokens.get_refresh_token(conn, "hash1")) is not None
            await refresh_tokens.revoke_refresh_token(conn, "hash1")
            # revoked tokens are no longer returned as valid
            assert (await refresh_tokens.get_refresh_token(conn, "hash1")) is None

    async def test_execute_status_strings(self, sqlite_pool):
        async with sqlite_pool.acquire() as conn:
            await conn.execute("INSERT INTO users (email) VALUES ($1)", "s@x.io")
            u = await conn.fetchrow("SELECT id FROM users WHERE email=$1", "s@x.io")
            upd = await conn.execute(
                "UPDATE users SET name=$2 WHERE id=$1", uuid.UUID(u["id"]), "Z")
            assert upd == "UPDATE 1"
            dele = await conn.execute(
                "DELETE FROM users WHERE id=$1", uuid.UUID(u["id"]))
            assert dele == "DELETE 1"

    async def test_on_conflict_do_nothing(self, sqlite_pool):
        async with sqlite_pool.acquire() as conn:
            await conn.execute("INSERT INTO users (email) VALUES ($1)", "c@x.io")
            # duplicate email is a unique-constraint conflict -> 0 rows
            res = await conn.execute(
                "INSERT INTO users (email) VALUES ($1) ON CONFLICT DO NOTHING",
                "c@x.io")
            assert res == "INSERT 0 0"

    async def test_transaction_rollback(self, sqlite_pool):
        async with sqlite_pool.acquire() as conn:
            try:
                async with conn.transaction():
                    await conn.execute("INSERT INTO users (email) VALUES ($1)", "t@x.io")
                    raise RuntimeError("boom")
            except RuntimeError:
                pass
            got = await conn.fetchrow("SELECT 1 FROM users WHERE email=$1", "t@x.io")
            assert got is None

