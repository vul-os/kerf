"""Every write route, on the embedded backend, asserting none of them 5xx.

WHY THIS EXISTS
---------------
``test_route_sweep_sqlite.py`` sweeps the read surface and says so in its own
docstring::

    Nor does it sweep POST/PATCH/DELETE, which need meaningful bodies. Writes
    have been the richer source of dialect bugs (the file-autosave 500 was a
    PATCH), so that is a real gap, not a claim of completeness.

This closes it. Every dialect bug found on the default backend so far has been
a write or a write-adjacent query: ``interval '1 second'`` in the file-autosave
idempotency window, ``FOR UPDATE OF j`` in every worker's job claim,
``extract(epoch from now())`` in the auth rate limiter, ``DISTINCT ON`` in the
CAM tool DB. Reads found five more only because nobody had ever called them.

HOW A BODY IS MADE
------------------
From the route's own OpenAPI ``requestBody`` schema: required properties get a
type-appropriate placeholder, optional ones are omitted. That is deliberately
dumb. The goal is not to exercise business logic — it is to get past FastAPI's
validation layer and reach the SQL, because the SQL is where the dialect bugs
are. A route that rejects the placeholder with a 422 has still proved it
doesn't 500 on the way there.

WHAT COUNTS AS A FAILURE
------------------------
Only 5xx. 4xx is a legitimate answer: not found, forbidden, wrong media type,
and above all 422, which most routes here will return. 503s from features that
are genuinely unconfigured on a bare node are allowed by name so an
*unexpected* 503 still fails.

ORDER
-----
POST, then PATCH/PUT, then DELETE — destructive calls last, so they cannot
pull the fixtures out from under the rest. Even so, a route that 404s because
an earlier DELETE removed its row has still been executed, which is the point.

Hermetic: SQLite is stdlib, so there is no service container and nothing to
skip. This runs in the default tier.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile
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

_DB_PATH = pathlib.Path(tempfile.mkdtemp(prefix="kerf-write-sweep-")) / "sweep.db"
_DB_URL = f"sqlite://{_DB_PATH}"

_IDS: dict[str, str] = {}


async def _migrate_and_seed() -> dict[str, str]:
    from kerf_core.db.migrations.runner import run_sqlite_migrations
    from kerf_core.db.sqlite_backend import create_sqlite_pool

    await run_sqlite_migrations(_DB_URL)
    pool = await create_sqlite_pool(_DB_URL, max_size=2)
    try:
        return await sweep.seed(pool)
    finally:
        await pool.close()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    import kerf_core.db.connection as _conn
    from kerf_core.db.sqlite_backend import create_sqlite_pool

    pool = await create_sqlite_pool(_DB_URL, max_size=4)
    _conn._pool = pool
    try:
        from kerf_core.storage import set_storage as _ss
        from kerf_core.storage.factory import create_storage as _cs
        _ss(_cs(backend="local", local_storage_path=str(_DB_PATH.parent / "storage")))
    except Exception:
        pass
    yield
    _conn._pool = None
    await pool.close()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    global _IDS
    _IDS = asyncio.run(_migrate_and_seed())

    from kerf_api.routes import router as api_router
    from kerf_auth.routes import router as auth_router

    app = FastAPI(lifespan=_lifespan)
    app.include_router(api_router, prefix="/api")
    app.include_router(auth_router, prefix="/auth")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_no_write_route_5xxs_on_sqlite(client: TestClient):
    called, skipped, failures = sweep.sweep_writes(client, _IDS)

    assert called >= 30, f"swept only {called} write routes — did body synthesis break?"
    assert not failures, (
        f"{len(failures)} write route(s) returned 5xx on the embedded SQLite backend "
        f"({called} swept, {len(skipped)} skipped):\n  " + "\n  ".join(failures)
    )
