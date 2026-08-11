"""The same route sweeps, on Postgres. Opt-in; not part of core testing.

WHY THIS EXISTS
---------------
The SQLite sweeps have found nine 500s, and the framing of most of them was
"Postgres-only SQL reaching the embedded backend": ``interval '1 second'``,
``FOR UPDATE OF j``, ``extract(epoch from now())``, ``DISTINCT ON``. That
framing has a blind spot. Two of those nine were broken on *both* backends and
had simply never been called, and the avatar routes turned out to fail on
Postgres for a different reason than on SQLite. A sweep that only ever runs on
one backend cannot tell "works everywhere" from "works here".

So the same sweeps run against Postgres, catching the reverse class: SQL the
translation layer accepts but Postgres rejects, values that round-trip through
aiosqlite and not through asyncpg, and anything the dialect module silently
rewrites into something Postgres would never have seen.

RUNNING IT
----------
Postgres is OPTIONAL in Kerf — a default install opens an embedded SQLite file
— so this is skipped unless DATABASE_URL is set, and it is not part of core
testing::

    DATABASE_URL="postgres://postgres:postgres@localhost:5433/kerf_e2e" \\
        python -m pytest packages/kerf-api/tests/test_route_sweep_postgres.py -q

The fixtures are inserted into whatever database DATABASE_URL names and removed
afterwards, so it is safe against a scratch database and deliberately not run
against anything else.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = pathlib.Path(__file__).parent
_PACKAGES_ROOT = _HERE.parent.parent
for _entry in _PACKAGES_ROOT.iterdir():
    if not _entry.name.startswith("kerf-"):
        continue
    _src = _entry / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import _route_sweep as sweep  # noqa: E402


def _require_postgres() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url or not url.startswith("postgres"):
        pytest.skip(
            "requires DATABASE_URL (Postgres); optional, not part of core testing",
            allow_module_level=True,
        )
    return url


_DB_URL = _require_postgres()

_IDS: dict[str, str] = {}


async def _seed():
    import asyncpg
    pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=2)
    try:
        return await sweep.seed(pool)
    finally:
        await pool.close()


async def _teardown(ids: dict[str, str]) -> None:
    """Remove the fixture graph.

    Deleting the user and the workspace is enough — projects, files, revisions,
    threads and memberships all cascade from those two.
    """
    import asyncpg
    conn = await asyncpg.connect(_DB_URL)
    try:
        await conn.execute("DELETE FROM workspaces WHERE id = $1",
                           uuid.UUID(ids["workspace_id"]))
        await conn.execute("DELETE FROM users WHERE id = $1",
                           uuid.UUID(ids["user_id"]))
    finally:
        await conn.close()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    import asyncpg
    import kerf_core.db.connection as _conn

    pool = await asyncpg.create_pool(_DB_URL, min_size=1, max_size=4)
    _conn._pool = pool
    try:
        from kerf_core.storage import set_storage as _ss
        from kerf_core.storage.factory import create_storage as _cs
        _ss(_cs(backend="local", local_storage_path="/tmp/kerf-pg-sweep-storage"))
    except Exception:
        pass
    yield
    _conn._pool = None
    await pool.close()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    global _IDS
    _IDS = asyncio.run(_seed())

    from kerf_api.routes import router as api_router
    from kerf_auth.routes import router as auth_router

    app = FastAPI(lifespan=_lifespan)
    app.include_router(api_router, prefix="/api")
    app.include_router(auth_router, prefix="/auth")
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c
    finally:
        asyncio.run(_teardown(_IDS))


def test_no_get_route_500s_on_postgres(client: TestClient):
    called, skipped, failures = sweep.sweep_reads(client, _IDS)

    assert called >= 20, f"swept only {called} routes — did the fixtures stop filling params?"
    assert not failures, (
        f"{len(failures)} GET route(s) returned 5xx on Postgres "
        f"({called} swept, {len(skipped)} skipped):\n  " + "\n  ".join(failures)
    )


def test_no_write_route_5xxs_on_postgres(client: TestClient):
    called, skipped, failures = sweep.sweep_writes(client, _IDS)

    assert called >= 30, f"swept only {called} write routes — did body synthesis break?"
    assert not failures, (
        f"{len(failures)} write route(s) returned 5xx on Postgres "
        f"({called} swept, {len(skipped)} skipped):\n  " + "\n  ".join(failures)
    )
