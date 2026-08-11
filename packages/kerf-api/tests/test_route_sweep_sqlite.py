"""Every GET route, on the embedded backend, asserting none of them 5xx.

WHY THIS EXISTS
---------------
Postgres is optional in Kerf — a default install opens an embedded SQLite file
— but for a long time every suite ran on Postgres, so the default path had no
coverage. When the e2e suite moved to SQLite it immediately turned up
Postgres-only SQL in the auth rate limiter, the CAM tool DB, the file-autosave
route, and every worker's job-claim query, plus timestamptz columns reading back
as ``str``. A sweep of the read surface then found five more 500s, two of which
were broken on *both* backends and had simply never been called by a test:

  * ``/projects/{pid}/files/{fid}/revisions`` referenced an undeclared ``limit``
  * ``/projects/{pid}/members`` called ``user_to_response()`` on rows from
    ``workspace_members``, which has no ``id`` column

A per-endpoint test would not have caught those, because nobody writes a test
for the endpoint they forgot exists. Enumerating the OpenAPI schema does: any
route reachable with the fixtures below is called, and a 5xx fails the build.

WHAT COUNTS AS A FAILURE
------------------------
Only 5xx. A 4xx is a legitimate answer (not found, forbidden, unsupported
media) and this sweep deliberately does not assert on bodies — it is a "does
this route survive being called on the default backend" net, not a behavioural
suite. 503s from features that are genuinely unconfigured on a bare node (OAuth,
web-push) are allowed by name, so an *unexpected* 503 still fails.

SCOPE — read this before trusting it
------------------------------------
The app here mounts kerf-api and kerf-auth only, not the plugin routers, so
plugin-owned endpoints (/compile-ifc, /run-fem, /run-cam, …) are NOT swept.
That is the price of staying hermetic — plugin discovery pulls in optional
native dependencies. A live sweep against a full server covers ~53 GET routes
where this covers ~38; the e2e suite exercises the plugin routes instead.

Nor does it sweep POST/PATCH/DELETE, which need meaningful bodies. Writes have
been the richer source of dialect bugs (the file-autosave 500 was a PATCH), so
that is a real gap, not a claim of completeness.

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

_DB_PATH = pathlib.Path(tempfile.mkdtemp(prefix="kerf-sweep-")) / "sweep.db"
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


def test_no_get_route_500s_on_sqlite(client: TestClient):
    called, skipped, failures = sweep.sweep_reads(client, _IDS)

    assert called >= 20, f"swept only {called} routes — did the fixtures stop filling params?"
    assert not failures, (
        f"{len(failures)} GET route(s) returned 5xx on the embedded SQLite backend "
        f"({called} swept, {len(skipped)} skipped for unfillable params):\n  "
        + "\n  ".join(failures)
    )
