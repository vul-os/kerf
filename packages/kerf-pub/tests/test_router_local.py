"""Node-local convenience API (kerf_pub.router_local) — /api/pub/*.

Identity / follows / workshop / pin are exercised purely against
InMemoryPubStore (no DB, no network) per the zero-socket design. ``publish``
is project-scoped and needs a real project's files, so it gets its own
Postgres-backed integration tests mirroring the pattern used by
packages/kerf-api/tests/test_routes_git_local.py.
"""
from __future__ import annotations

import asyncio
import base64
import os
import pathlib
import secrets
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from kerf_core.dependencies import require_auth

from kerf_pub import Identity, InMemoryPubStore, PubClient
from kerf_pub.hashing import mhash
from kerf_pub.objects import (
    ArtifactFormat, ArtifactMetadata, FMT_NATIVE, KIND_PART, ROLE_CANONICAL, Units,
)
from kerf_pub.router_local import router as local_router


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _fake_user(sub: str = "local-test-user") -> dict:
    return {"sub": sub}


def _app(store) -> TestClient:
    app = FastAPI()
    app.state.pub_store = store
    app.include_router(local_router, prefix="/api")
    app.dependency_overrides[require_auth] = lambda: _fake_user()
    return TestClient(app)


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

class TestIdentity:
    def test_get_identity_none_before_creation(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_DATA_DIR", str(tmp_path))
        tc = _app(InMemoryPubStore())
        r = tc.get("/api/pub/identity")
        assert r.status_code == 200
        assert r.json() == {"pub": None}

    def test_post_creates_and_get_reflects_it(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_DATA_DIR", str(tmp_path))
        tc = _app(InMemoryPubStore())

        created = tc.post("/api/pub/identity")
        assert created.status_code == 200
        pub1 = created.json()["pub"]
        assert isinstance(pub1, str) and pub1

        fetched = tc.get("/api/pub/identity")
        assert fetched.status_code == 200
        assert fetched.json()["pub"] == pub1

    def test_post_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KERF_DATA_DIR", str(tmp_path))
        tc = _app(InMemoryPubStore())
        r1 = tc.post("/api/pub/identity")
        r2 = tc.post("/api/pub/identity")
        assert r1.json()["pub"] == r2.json()["pub"]


# ---------------------------------------------------------------------------
# follows
# ---------------------------------------------------------------------------

class TestFollows:
    def test_add_list_delete_roundtrip(self):
        tc = _app(InMemoryPubStore())
        target = Identity.generate()
        pub_b64 = _b64(target.pub)

        add_r = tc.post("/api/pub/follows", json={
            "pub": pub_b64, "label": "Alice", "gateway_url": "",
        })
        assert add_r.status_code == 200, add_r.text
        assert add_r.json()["pub"] == pub_b64
        assert add_r.json()["label"] == "Alice"

        list_r = tc.get("/api/pub/follows")
        assert list_r.status_code == 200
        rows = list_r.json()
        assert len(rows) == 1
        assert rows[0]["pub"] == pub_b64
        assert rows[0]["gateway_url"] == ""
        assert isinstance(rows[0]["added_ts"], int)

        del_r = tc.delete(f"/api/pub/follows/{pub_b64}")
        assert del_r.status_code == 200
        assert tc.get("/api/pub/follows").json() == []

    def test_bad_pub_length_rejected(self):
        tc = _app(InMemoryPubStore())
        r = tc.post("/api/pub/follows", json={"pub": _b64(b"short"), "label": "", "gateway_url": ""})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# workshop aggregation
# ---------------------------------------------------------------------------

class TestWorkshopFeed:
    def test_empty_with_no_follows(self):
        tc = _app(InMemoryPubStore())
        r = tc.get("/api/pub/workshop")
        assert r.status_code == 200
        assert r.json() == []

    def test_zero_socket_with_no_gateway_serves_local_store(self):
        store = InMemoryPubStore()
        publisher = Identity.generate()
        client = PubClient(store=store, identity=publisher)

        artifact = ArtifactMetadata(
            name="Bracket",
            description="A simple bracket",
            artifact_kind=KIND_PART,
            formats=[ArtifactFormat(format_id=FMT_NATIVE, manifest_root=mhash(b"placeholder"), role=ROLE_CANONICAL)],
            units=Units(length_unit="mm"),
            license="MIT",
            tags=["bracket", "mechanical"],
        )
        # formats[0].manifest_root is a placeholder — publish() recomputes
        # real manifests from `files`; only the embedded ArtifactMetadata
        # bytes (name/description/license/units/tags) matter for this test.
        aid = asyncio.run(client.publish({"part.native": b"geometry bytes"}, artifact))

        follow_pub_b64 = _b64(publisher.pub)
        tc = _app(store)
        tc.post("/api/pub/follows", json={"pub": follow_pub_b64, "label": "Publisher", "gateway_url": ""})

        r = tc.get("/api/pub/workshop")
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["announce_id"] == _b64(aid)
        assert row["pub"] == follow_pub_b64
        assert row["meta"]["name"] == "Bracket"
        assert row["meta"]["license"] == "MIT"
        # Wire-format §23.3.3 integer keys are translated to friendly names
        # for this UI-facing endpoint.
        assert row["meta"]["units"] == {"length_unit": "mm", "angle_unit": None, "mass_unit": None}
        assert row["meta"]["tags"] == ["bracket", "mechanical"]
        # publish() always pins the author's own announce locally.
        assert row["pinned"] is True
        assert row["availability"]["status"] == "on-node"

    def test_non_artifact_announce_is_filtered_out(self):
        store = InMemoryPubStore()
        publisher = Identity.generate()
        client = PubClient(store=store, identity=publisher)
        # No artifact_metadata — a plain public blob, not a Workshop listing.
        asyncio.run(client.publish({"readme.txt": b"just some bytes"}))

        tc = _app(store)
        tc.post("/api/pub/follows", json={"pub": _b64(publisher.pub), "label": "", "gateway_url": ""})
        r = tc.get("/api/pub/workshop")
        assert r.status_code == 200
        assert r.json() == []


# ---------------------------------------------------------------------------
# pin / unpin / hydrate — durable pinning (§22.5.3 swarm fetch)
# ---------------------------------------------------------------------------
#
# Deeper swarm-fetch scenarios (multi-gateway rotate, partial hydration,
# retry, IPFS fallback) are exercised directly against
# kerf_pub.client.PubClient.hydrate_pin in test_pin_hydration.py; these are
# the node-local /api/pub/pin/* HTTP-endpoint-level tests.

class TestPin:
    def test_pin_already_local_content_hydrates_with_zero_gateways(self):
        # Content published on THIS node is already fully local — pinning it
        # needs no network call at all, even with zero follows/gateways
        # configured (the zero-socket path that still succeeds).
        store = InMemoryPubStore()
        publisher = Identity.generate()
        client = PubClient(store=store, identity=publisher)
        aid = asyncio.run(client.publish({"native": b"already-local-bytes" * 10}))
        # publish() pins as a side effect; reset so the endpoint has real work.
        asyncio.run(store.set_pinned(aid, False))

        tc = _app(store)
        aid_b64 = _b64(aid)
        pin_r = tc.post(f"/api/pub/pin/{aid_b64}")
        assert pin_r.status_code == 200, pin_r.text
        body = pin_r.json()
        assert body == {
            "announce_id": aid_b64, "pinned": True, "hydrated": True, "missing_chunks": 0,
        }

        avail = asyncio.run(store.get_availability(aid))
        assert avail.local_pinned is True

        unpin_r = tc.delete(f"/api/pub/pin/{aid_b64}")
        assert unpin_r.status_code == 200
        assert unpin_r.json()["pinned"] is False
        avail2 = asyncio.run(store.get_availability(aid))
        assert avail2.local_pinned is False

    def test_pin_zero_socket_unknown_announce_is_a_clear_400(self):
        # No follows (so no gateways at all) and an announce that is neither
        # local nor fetchable anywhere: MUST fail loudly, never a silent
        # 200 {"pinned": true} no-op (the pre-hydration behavior this
        # replaces).
        store = InMemoryPubStore()
        tc = _app(store)
        fake_aid = b"\x12" + secrets.token_bytes(32)
        aid_b64 = _b64(fake_aid)

        pin_r = tc.post(f"/api/pub/pin/{aid_b64}")
        assert pin_r.status_code == 400
        assert "gateway" in pin_r.json()["detail"].lower()

        avail = asyncio.run(store.get_availability(fake_aid))
        assert avail.local_pinned is False

    def test_hydrate_endpoint_retries_and_reuses_follow_gateway_ordering(self, monkeypatch):
        # A follow's own gateway_url is what a real pin would swarm-fetch
        # through; here it is configured but never actually serves anything
        # (monkeypatched to simulate every request 404-ing), so the
        # /hydrate retry endpoint still surfaces a structured (non-200-lying)
        # result for a locally-unknown announce — exercising
        # _ordered_gateways_for's follow-lookup path without opening a real
        # socket in this test.
        from kerf_pub.client import PubClient
        monkeypatch.setattr(PubClient, "_http_get", staticmethod(lambda url: None))

        store = InMemoryPubStore()
        publisher = Identity.generate()
        pub_b64 = _b64(publisher.pub)
        tc = _app(store)
        tc.post("/api/pub/follows", json={
            "pub": pub_b64, "label": "Alice", "gateway_url": "https://nowhere.invalid",
        })

        fake_aid = b"\x12" + secrets.token_bytes(32)
        aid_b64 = _b64(fake_aid)
        r = tc.post(f"/api/pub/pin/{aid_b64}/hydrate")
        # A configured-but-unresponsive gateway is a network failure per
        # object, not a zero-socket condition — PubClient.online is True
        # (len(gateways) > 0), so hydrate_pin resolves nothing and raises
        # ERR_PUB_NOT_SERVED ("not found on any configured gateway"), which
        # the endpoint still reports as a clear 400, not a fabricated 200.
        assert r.status_code == 400


# ===========================================================================
# publish — project-scoped, needs a real project + files, so real Postgres.
# ===========================================================================

_HERE = pathlib.Path(__file__).parent
_PACKAGES_ROOT = _HERE.parent.parent
for _entry in _PACKAGES_ROOT.iterdir():
    if not _entry.name.startswith("kerf-"):
        continue
    _src = _entry / "src"
    if _src.is_dir() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

_DB_URL = os.environ.get("DATABASE_URL", "postgres://pc@localhost:5432/kerf?sslmode=disable")
_JWT_SECRET = "dev-secret-change-in-production"
_RUN_PREFIX = f"publocal-{secrets.token_hex(4)}"


def _mint_jwt(user_id: str) -> str:
    import jwt
    now = datetime.now(tz=timezone.utc)
    return jwt.encode({"sub": user_id, "exp": now + timedelta(hours=1), "iat": now}, _JWT_SECRET, algorithm="HS256")


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_mint_jwt(user_id)}"}


_STORAGE_TMPDIR: str | None = None


def _storage_root() -> str:
    global _STORAGE_TMPDIR
    if _STORAGE_TMPDIR is None:
        _STORAGE_TMPDIR = tempfile.mkdtemp(prefix="kerf-publocal-test-")
    return _STORAGE_TMPDIR


_FIXTURE_DATA: dict | None = None


async def _create_fixtures(db_url: str) -> dict:
    import asyncpg
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=3)
    data: dict = {}
    try:
        async with pool.acquire() as conn:
            user_row = await conn.fetchrow(
                "INSERT INTO users (email, name, account_role, is_system) "
                "VALUES ($1, $2, 'user', false) RETURNING id",
                f"{_RUN_PREFIX}@publocal.test", f"PubLocal {_RUN_PREFIX}",
            )
            data["user_id"] = str(user_row["id"])

            ws_row = await conn.fetchrow(
                "INSERT INTO workspaces (slug, name, created_by) VALUES ($1, $2, $3) RETURNING id",
                f"ws-{_RUN_PREFIX}", f"WS {_RUN_PREFIX}", user_row["id"],
            )
            data["ws_id"] = str(ws_row["id"])

            await conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES ($1, $2, 'owner')",
                ws_row["id"], user_row["id"],
            )

            proj_row = await conn.fetchrow(
                "INSERT INTO projects (workspace_id, name, description, visibility, tags) "
                "VALUES ($1, $2, 'desc', 'private', '{}') RETURNING id",
                ws_row["id"], f"PubLocalProj {_RUN_PREFIX}",
            )
            data["project_id"] = str(proj_row["id"])

            await conn.execute(
                "INSERT INTO files (project_id, parent_id, name, kind, content) "
                "VALUES ($1, NULL, 'part.jscad', 'file', 'cube([10,10,10])')",
                proj_row["id"],
            )

            other_row = await conn.fetchrow(
                "INSERT INTO users (email, name, account_role, is_system) "
                "VALUES ($1, $2, 'user', false) RETURNING id",
                f"{_RUN_PREFIX}-other@publocal.test", f"Other {_RUN_PREFIX}",
            )
            data["other_user_id"] = str(other_row["id"])
    finally:
        await pool.close()
    return data


async def _delete_fixtures(db_url: str, data: dict) -> None:
    import asyncpg
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM files WHERE project_id = $1", uuid.UUID(data["project_id"]))
            await conn.execute("DELETE FROM projects WHERE id = $1", uuid.UUID(data["project_id"]))
            await conn.execute("DELETE FROM workspace_members WHERE workspace_id = $1", uuid.UUID(data["ws_id"]))
            await conn.execute("DELETE FROM workspaces WHERE id = $1", uuid.UUID(data["ws_id"]))
            for uid in (data.get("user_id"), data.get("other_user_id")):
                if not uid:
                    continue
                await conn.execute("DELETE FROM refresh_tokens WHERE user_id = $1", uuid.UUID(uid))
                await conn.execute("DELETE FROM email_tokens WHERE user_id = $1", uuid.UUID(uid))
                await conn.execute("DELETE FROM users WHERE id = $1", uuid.UUID(uid))
    finally:
        await pool.close()


def _get_fixture_data() -> dict:
    global _FIXTURE_DATA
    if _FIXTURE_DATA is None:
        _FIXTURE_DATA = asyncio.run(_create_fixtures(_DB_URL))
    return _FIXTURE_DATA


@pytest.fixture(scope="module", autouse=True)
def session_fixtures() -> Generator[dict, None, None]:
    data = _get_fixture_data()
    yield data
    asyncio.run(_delete_fixtures(_DB_URL, data))


@asynccontextmanager
async def _lifespan(app: FastAPI):
    import asyncpg
    import kerf_core.db.connection as _conn
    from kerf_core.storage.local import LocalStorage
    from kerf_core.storage import set_storage as _ss

    pool = await asyncpg.create_pool(_DB_URL, min_size=2, max_size=5)
    _conn._pool = pool
    _ss(LocalStorage(root=os.path.join(_storage_root(), "objs")))
    yield
    _conn._pool = None
    await pool.close()


def _build_publish_app() -> FastAPI:
    app = FastAPI(lifespan=_lifespan)
    app.state.pub_store = InMemoryPubStore()
    app.include_router(local_router, prefix="/api")
    return app


@pytest.fixture(scope="module")
def publish_client(session_fixtures) -> Generator[TestClient, None, None]:
    app = _build_publish_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestPublish:
    def test_missing_license_and_units_rejected(self, publish_client: TestClient, tmp_path_factory, monkeypatch):
        data = _get_fixture_data()
        r = publish_client.post(
            "/api/pub/publish",
            json={
                "project_id": data["project_id"],
                "metadata": {
                    "name": "Bracket",
                    "description": "desc",
                    "artifact_kind": "part",
                    # license and units omitted on purpose
                },
            },
            headers=_auth_headers(data["user_id"]),
        )
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "license" in detail
        assert "units.length_unit" in detail

    def test_publish_happy_path(self, publish_client: TestClient):
        data = _get_fixture_data()
        r = publish_client.post(
            "/api/pub/publish",
            json={
                "project_id": data["project_id"],
                "metadata": {
                    "name": "Bracket",
                    "description": "A bracket",
                    "artifact_kind": "part",
                    "license": "MIT",
                    "units": {"length_unit": "mm"},
                    "tags": ["bracket"],
                },
            },
            headers=_auth_headers(data["user_id"]),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert isinstance(body["announce_id"], str) and body["announce_id"]

    def test_publish_404_for_non_member(self, publish_client: TestClient):
        data = _get_fixture_data()
        r = publish_client.post(
            "/api/pub/publish",
            json={
                "project_id": data["project_id"],
                "metadata": {
                    "name": "Bracket", "description": "d", "artifact_kind": "part",
                    "license": "MIT", "units": {"length_unit": "mm"},
                },
            },
            headers=_auth_headers(data["other_user_id"]),
        )
        assert r.status_code == 404

    def test_publish_assembly_happy_path_with_track_child(self, publish_client: TestClient):
        # Children MUST already be published (§23.6.1) before the parent
        # assembly can reference them — publish a part first, then track it.
        data = _get_fixture_data()
        part_r = publish_client.post(
            "/api/pub/publish",
            json={
                "project_id": data["project_id"],
                "metadata": {
                    "name": "Bolt", "description": "d", "artifact_kind": "part",
                    "license": "MIT", "units": {"length_unit": "mm"},
                },
            },
            headers=_auth_headers(data["user_id"]),
        )
        assert part_r.status_code == 200, part_r.text
        part_announce_id = part_r.json()["announce_id"]

        asm_r = publish_client.post(
            "/api/pub/publish",
            json={
                "project_id": data["project_id"],
                "metadata": {
                    "name": "Assy", "description": "d", "artifact_kind": "assembly",
                    "license": "MIT", "units": {"length_unit": "mm"},
                },
                "children": [
                    {"ref_kind": "track", "announce_id": part_announce_id, "quantity": 4},
                ],
            },
            headers=_auth_headers(data["user_id"]),
        )
        assert asm_r.status_code == 200, asm_r.text
        assert isinstance(asm_r.json()["announce_id"], str) and asm_r.json()["announce_id"]

        bom_r = publish_client.get(
            f"/api/pub/bom/{asm_r.json()['announce_id']}",
            headers=_auth_headers(data["user_id"]),
        )
        assert bom_r.status_code == 200, bom_r.text
        body = bom_r.json()
        assert body["cycles"] == []
        assert len(body["parts"]) == 1
        assert body["parts"][0]["ref_kind"] == "track"
        assert body["parts"][0]["resolved_announce"] == part_announce_id
        assert body["parts"][0]["quantity_total"] == 4

    def test_publish_assembly_unresolvable_ref_rejected(self, publish_client: TestClient):
        data = _get_fixture_data()
        fake_announce_id = _b64(b"\x12" + secrets.token_bytes(32))
        r = publish_client.post(
            "/api/pub/publish",
            json={
                "project_id": data["project_id"],
                "metadata": {
                    "name": "Assy", "description": "d", "artifact_kind": "assembly",
                    "license": "MIT", "units": {"length_unit": "mm"},
                },
                "children": [
                    {"ref_kind": "track", "announce_id": fake_announce_id, "quantity": 1},
                ],
            },
            headers=_auth_headers(data["user_id"]),
        )
        assert r.status_code == 400
        assert fake_announce_id in r.json()["detail"]

    def test_publish_assembly_requires_children(self, publish_client: TestClient):
        data = _get_fixture_data()
        r = publish_client.post(
            "/api/pub/publish",
            json={
                "project_id": data["project_id"],
                "metadata": {
                    "name": "Assy", "description": "d", "artifact_kind": "assembly",
                    "license": "MIT", "units": {"length_unit": "mm"},
                },
            },
            headers=_auth_headers(data["user_id"]),
        )
        assert r.status_code == 400
