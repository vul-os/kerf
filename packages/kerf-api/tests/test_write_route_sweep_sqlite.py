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
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Generator

import jwt
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

_JWT_SECRET = "dev-secret-change-in-production"

# Routes whose 503 is the correct answer on a node with no OAuth client, no
# VAPID keypair and no configured LLM provider. Listed explicitly so a NEW 503
# is still a failure.
_ALLOWED_503 = {
    "/auth/google/start",
    "/auth/github/login/start",
}

# 501 is a designed answer, not a fault: a node with no mail transport cannot
# send a reset link, and says so with instructions for the operator. Listed by
# name so a new 501 still fails.
_ALLOWED_501 = {
    "/auth/forgot-password",
}

# Routes this sweep must not call, with the reason. Keep this list short and
# justified — every entry is coverage given up.
_SKIP = {
    # Would revoke the sweep's own credentials mid-run and turn every
    # subsequent call into a 401, hiding whatever they would have found.
    "/auth/logout": "revokes the sweep's own token",
    # Deletes the authenticated user, cascading away every fixture below it.
    "/api/me": "cascades away the fixtures the rest of the sweep needs",
}

_DB_PATH = pathlib.Path(tempfile.mkdtemp(prefix="kerf-write-sweep-")) / "sweep.db"
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
                "VALUES ($1, 'Sweep', 'user', false) RETURNING *",
                f"write-sweep-{uuid.uuid4().hex[:8]}@test.invalid",
            )
            ws = await conn.fetchrow(
                "INSERT INTO workspaces (slug, name, created_by) VALUES ($1, 'WS', $2) RETURNING *",
                f"write-sweep-{uuid.uuid4().hex[:8]}", user["id"],
            )
            await conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) "
                "VALUES ($1, $2, 'owner')",
                ws["id"], user["id"],
            )
            proj = await conn.fetchrow(
                "INSERT INTO projects (workspace_id, name, description, visibility, tags) "
                "VALUES ($1, 'Sweep Project', '', 'private', '[]') RETURNING *",
                ws["id"],
            )
            f = await conn.fetchrow(
                "INSERT INTO files (project_id, name, kind, content) "
                "VALUES ($1, 'main.jscad', 'script', '// sweep') RETURNING *",
                proj["id"],
            )
            rev = await conn.fetchrow(
                "INSERT INTO file_revisions (file_id, content, source, user_id, kind) "
                "VALUES ($1, '// rev', 'user', $2, 'base') RETURNING *",
                f["id"], user["id"],
            )
            thread = await conn.fetchrow(
                "INSERT INTO chat_threads (project_id, title) VALUES ($1, 'Sweep') RETURNING *",
                proj["id"],
            )
        return {
            "user_id": str(user["id"]), "uid": str(user["id"]),
            "workspace_id": str(ws["id"]), "wid": str(ws["id"]),
            "slug": ws["slug"],
            "project_id": str(proj["id"]), "pid": str(proj["id"]),
            "file_id": str(f["id"]), "fid": str(f["id"]),
            "revision_id": str(rev["id"]), "rid": str(rev["id"]),
            "thread_id": str(thread["id"]), "tid": str(thread["id"]),
        }
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


def _auth_headers() -> dict[str, str]:
    now = datetime.now(tz=timezone.utc)
    token = jwt.encode(
        {"sub": _IDS["user_id"], "exp": now + timedelta(hours=1), "iat": now},
        _JWT_SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


def _fill(path: str) -> str | None:
    """Substitute {param} placeholders from the seeded fixtures, or None."""
    out = path
    while "{" in out:
        start = out.index("{")
        end = out.index("}", start)
        name = out[start + 1:end]
        if name not in _IDS:
            return None
        out = out[:start] + _IDS[name] + out[end + 1:]
    return out


def _resolve(schema: dict, spec: dict) -> dict:
    """Follow a local $ref into the spec's component schemas."""
    ref = schema.get("$ref")
    if not ref or not ref.startswith("#/"):
        return schema
    node: Any = spec
    for part in ref[2:].split("/"):
        node = node.get(part, {})
        if not isinstance(node, dict):
            return {}
    return node


def _placeholder(prop: dict, spec: dict, depth: int = 0) -> Any:
    """A value of the right shape for one property. Not a meaningful value."""
    prop = _resolve(prop, spec)
    if depth > 3:
        return None

    # anyOf/oneOf: take the first non-null branch, which is how FastAPI spells
    # Optional[X] — anyOf: [X, null].
    for key in ("anyOf", "oneOf", "allOf"):
        if key in prop:
            branches = [b for b in prop[key] if _resolve(b, spec).get("type") != "null"]
            if branches:
                return _placeholder(branches[0], spec, depth + 1)

    if "default" in prop:
        return prop["default"]
    if prop.get("enum"):
        return prop["enum"][0]

    kind = prop.get("type")
    if kind == "string":
        fmt = prop.get("format")
        if fmt == "uuid":
            return _IDS["project_id"]
        if fmt == "date-time":
            return datetime.now(timezone.utc).isoformat()
        if fmt == "email":
            return "sweep@test.invalid"
        return "sweep"
    if kind == "integer":
        return prop.get("minimum", 1)
    if kind == "number":
        return float(prop.get("minimum", 1))
    if kind == "boolean":
        return False
    if kind == "array":
        return []
    if kind == "object":
        return _body_from_schema(prop, spec, depth + 1)
    return "sweep"


def _body_from_schema(schema: dict, spec: dict, depth: int = 0) -> dict:
    schema = _resolve(schema, spec)
    required = schema.get("required") or []
    props = schema.get("properties") or {}
    return {
        name: _placeholder(props.get(name, {}), spec, depth)
        for name in required
        if name in props or True
    }


def _request_body(operation: dict, spec: dict) -> dict | None:
    body = operation.get("requestBody")
    if not body:
        return None
    schema = ((body.get("content") or {}).get("application/json") or {}).get("schema")
    if schema is None:
        return None
    return _body_from_schema(schema, spec)


# Destructive calls last so they cannot pull fixtures out from under the rest.
_ORDER = {"post": 0, "put": 1, "patch": 2, "delete": 3}


def test_no_write_route_5xxs_on_sqlite(client: TestClient):
    spec = client.app.openapi()
    headers = _auth_headers()

    operations = []
    for path, ops in spec.get("paths", {}).items():
        for method, operation in ops.items():
            if method in _ORDER:
                operations.append((_ORDER[method], path, method, operation))
    operations.sort()

    called, skipped, failures = 0, [], []
    for _, path, method, operation in operations:
        if path in _SKIP:
            skipped.append(f"{path} ({_SKIP[path]})")
            continue
        concrete = _fill(path)
        if concrete is None:
            skipped.append(f"{method.upper()} {path} (unfillable params)")
            continue

        body = _request_body(operation, spec)
        resp = client.request(
            method.upper(), concrete, headers=headers,
            **({"json": body} if body is not None else {}),
        )
        called += 1

        if resp.status_code == 503 and path in _ALLOWED_503:
            continue
        if resp.status_code == 501 and path in _ALLOWED_501:
            continue
        if resp.status_code >= 500:
            failures.append(
                f"{resp.status_code} {method.upper()} {path} -> {resp.text[:200]}")

    assert called >= 30, f"swept only {called} write routes — did body synthesis break?"
    assert not failures, (
        f"{len(failures)} write route(s) returned 5xx on the embedded SQLite backend "
        f"({called} swept, {len(skipped)} skipped):\n  " + "\n  ".join(failures)
    )
