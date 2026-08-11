"""A Library part must be reachable by the slug the catalogue advertises.

WHY THIS EXISTS
---------------
``list_public_parts`` puts ``<workspace_slug>/<project_name>/<file_name>`` in
every row's ``slug``, the Library page navigates to ``/library/<that slug>``,
and the detail route could not resolve it. Two separate reasons, stacked:

  * the route was declared ``{slug}``, which matches one path segment, and the
    readable slug has two slashes — so the request never reached the handler
  * the handler parsed the slug as a UUID and 404'd on anything else, above a
    comment describing path lookup as "a future enhancement"

So every click from the catalogue into a part landed on a 404. The e2e suite
went green over it because the detail page renders the part name from the URL
before its fetch resolves; the failure only surfaced as an intermittent
server-mode flake, which is how it was found.

These tests go at the seam the e2e suite could not see: given a part that the
catalogue lists, the slug in that listing must fetch the same part.
"""
from __future__ import annotations

import asyncio
import pathlib
import sys
import tempfile
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

_DB_PATH = pathlib.Path(tempfile.mkdtemp(prefix="kerf-library-")) / "library.db"
_DB_URL = f"sqlite://{_DB_PATH}"

_IDS: dict[str, str] = {}


async def _migrate_and_seed() -> dict[str, str]:
    from kerf_core.db.migrations.runner import run_sqlite_migrations
    from kerf_core.db.sqlite_backend import create_sqlite_pool

    await run_sqlite_migrations(_DB_URL)
    pool = await create_sqlite_pool(_DB_URL, max_size=2)
    try:
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "INSERT INTO users (email, name, account_role, is_system) "
                "VALUES ($1, 'Author', 'user', false) RETURNING *",
                f"lib-{uuid.uuid4().hex[:8]}@test.invalid",
            )
            ws = await conn.fetchrow(
                "INSERT INTO workspaces (slug, name, created_by) VALUES ($1, 'WS', $2) RETURNING *",
                f"pub-{uuid.uuid4().hex[:8]}", user["id"],
            )
            public = await conn.fetchrow(
                "INSERT INTO projects (workspace_id, name, description, visibility, tags) "
                "VALUES ($1, 'Bracket Kit', '', 'public', '[]') RETURNING *",
                ws["id"],
            )
            private = await conn.fetchrow(
                "INSERT INTO projects (workspace_id, name, description, visibility, tags) "
                "VALUES ($1, 'Secret Kit', '', 'private', '[]') RETURNING *",
                ws["id"],
            )
            part = await conn.fetchrow(
                "INSERT INTO files (project_id, name, kind, content) "
                "VALUES ($1, 'M3 Standoff', 'part', $2) RETURNING *",
                public["id"], '{"manufacturer": "Acme", "mpn": "STD-M3"}',
            )
            hidden = await conn.fetchrow(
                "INSERT INTO files (project_id, name, kind, content) "
                "VALUES ($1, 'Hidden Part', 'part', '{}') RETURNING *",
                private["id"],
            )
        return {
            "workspace_slug": ws["slug"],
            "project_name": public["name"],
            "part_name": part["name"],
            "file_id": str(part["id"]),
            "private_project_name": private["name"],
            "hidden_part_name": hidden["name"],
        }
    finally:
        await pool.close()


@asynccontextmanager
async def _lifespan(app: FastAPI):
    import kerf_core.db.connection as _conn
    from kerf_core.db.sqlite_backend import create_sqlite_pool

    pool = await create_sqlite_pool(_DB_URL, max_size=4)
    _conn._pool = pool
    yield
    _conn._pool = None
    await pool.close()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    global _IDS
    _IDS = asyncio.run(_migrate_and_seed())

    from kerf_api.routes import router as api_router

    app = FastAPI(lifespan=_lifespan)
    app.include_router(api_router, prefix="/api")
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _listed_slug(client: TestClient) -> str:
    """The slug exactly as the catalogue advertises it."""
    body = client.get("/api/library/parts").json()
    rows = body["rows"] if isinstance(body, dict) else body
    row = next(r for r in rows if r["name"] == _IDS["part_name"])
    return row["slug"]


def test_the_catalogue_advertises_a_three_segment_slug(client: TestClient):
    assert _listed_slug(client) == (
        f"{_IDS['workspace_slug']}/{_IDS['project_name']}/{_IDS['part_name']}"
    )


def test_the_advertised_slug_fetches_the_part(client: TestClient):
    """The regression. This 404'd for every part in the catalogue."""
    resp = client.get(f"/api/library/parts/{_listed_slug(client)}")

    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == _IDS["part_name"]


def test_slug_and_file_id_return_the_same_part(client: TestClient):
    """Both routes exist; a caller must not be able to tell them apart."""
    by_slug = client.get(f"/api/library/parts/{_listed_slug(client)}").json()
    by_id = client.get(f"/api/library/parts/{_IDS['file_id']}").json()

    assert by_slug == by_id


def test_the_returned_slug_round_trips(client: TestClient):
    """Whatever `slug` the detail response carries must itself resolve —
    otherwise a canonical-URL rewrite built from it would 404."""
    first = client.get(f"/api/library/parts/{_IDS['file_id']}").json()
    again = client.get(f"/api/library/parts/{first['slug']}")

    assert again.status_code == 200
    assert again.json()["file_id"] == _IDS["file_id"]


def test_a_part_in_a_private_project_is_not_reachable_by_slug(client: TestClient):
    """Path lookup must not become a way around the visibility filter."""
    slug = (f"{_IDS['workspace_slug']}/{_IDS['private_project_name']}"
            f"/{_IDS['hidden_part_name']}")
    assert client.get(f"/api/library/parts/{slug}").status_code == 404


@pytest.mark.parametrize("slug", [
    "only-one-segment",
    "two/segments",
    "four/segments/here/now",
    "//",
])
def test_malformed_slugs_404_rather_than_matching_something_else(client, slug):
    assert client.get(f"/api/library/parts/{slug}").status_code == 404


def test_an_unknown_uuid_still_404s(client: TestClient):
    assert client.get(f"/api/library/parts/{uuid.uuid4()}").status_code == 404
