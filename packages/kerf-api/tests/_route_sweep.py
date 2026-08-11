"""Shared machinery for the route sweeps.

Not a test module — the two sweeps import it.

A sweep calls every route the app exposes and fails on any 5xx. The point is
dialect coverage: Kerf runs on embedded SQLite by default and on Postgres at
scale, the SQL is written once for both, and every difference between them has
shown up as a 500 in production rather than as a test failure. Nine such bugs
have been found this way, in both directions.

The seeding, path-parameter filling and request-body synthesis are identical
whichever backend is underneath, so they live here and each sweep module
supplies only its pool.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt

JWT_SECRET = "dev-secret-change-in-production"

# Routes whose 503 is the correct answer on a node with no OAuth client and no
# VAPID keypair. Listed explicitly so an *unexpected* 503 still fails.
ALLOWED_503 = {
    "/auth/google/start",
    "/auth/google/callback",
    "/auth/github/login/start",
    "/auth/github/login/callback",
    "/.well-known/dmtap-pub/wake-key",
}

# 501 is a designed answer, not a fault: a node with no mail transport cannot
# send a reset link and says so, with instructions for the operator.
ALLOWED_501 = {
    "/auth/forgot-password",
}

# Routes a sweep must not call, with the reason. Every entry is coverage given
# up, so keep this short and justified.
SKIP = {
    "/auth/logout": "revokes the sweep's own token",
    "/api/me": "cascades away the fixtures the rest of the sweep needs",
}

# Destructive calls last, so they cannot pull fixtures out from under the rest.
WRITE_ORDER = {"post": 0, "put": 1, "patch": 2, "delete": 3}


async def seed(pool) -> dict[str, str]:
    """Insert the fixture graph every sweep needs; return its ids.

    Written in the Postgres dialect, which the SQLite backend translates — the
    same path the app itself takes, so a seed that works here is evidence the
    translation layer works too.
    """
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "INSERT INTO users (email, name, account_role, is_system) "
            "VALUES ($1, 'Sweep', 'user', false) RETURNING *",
            f"sweep-{uuid.uuid4().hex[:8]}@test.invalid",
        )
        ws = await conn.fetchrow(
            "INSERT INTO workspaces (slug, name, created_by) VALUES ($1, 'Sweep WS', $2) RETURNING *",
            f"sweep-{uuid.uuid4().hex[:8]}", user["id"],
        )
        await conn.execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role) "
            "VALUES ($1, $2, 'owner')",
            ws["id"], user["id"],
        )
        proj = await conn.fetchrow(
            # tags is bound, not inlined: it is a real text[] on Postgres and
            # JSON text on SQLite, so a literal is right for exactly one of
            # them ('[]' is a malformed array literal to asyncpg). Passing a
            # Python list lets each driver map it, which is what the app does.
            "INSERT INTO projects (workspace_id, name, description, visibility, tags) "
            "VALUES ($1, 'Sweep Project', '', 'private', $2) RETURNING *",
            ws["id"], [],
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
        # Rows that exist only to make more of the route surface reachable.
        # Without them the share, membership, submission and BYO-key routes
        # are skipped for unfillable path params — which is how a route goes
        # years without ever being called by a test.
        share = await conn.fetchrow(
            "INSERT INTO share_links (project_id, token, role, created_by) "
            "VALUES ($1, $2, 'viewer', $3) RETURNING *",
            proj["id"], f"sweep-{uuid.uuid4().hex}", user["id"],
        )
        submission = await conn.fetchrow(
            "INSERT INTO library_part_submissions "
            "(submitter_user_id, target_workspace_id, payload) "
            "VALUES ($1, $2, $3) RETURNING *",
            user["id"], ws["id"], "{}",
        )
        # A real resumable-upload session. Without one, {uid} filled with the
        # *user* id — so the four /uploads/{uid} routes were "swept" while
        # 404ing on a row that could never exist, which is coverage in name
        # only. received_chunks is int[] on Postgres and JSON text on SQLite,
        # so it is bound rather than inlined (same reason as tags above).
        upload = await conn.fetchrow(
            "INSERT INTO upload_sessions "
            "(project_id, user_id, filename, size, mime, sha256, storage_key, "
            " total_chunks, received_chunks) "
            "VALUES ($1, $2, 'sweep.bin', 1024, 'application/octet-stream', "
            "        $3, $4, 1, $5) RETURNING *",
            proj["id"], user["id"], "0" * 64,
            f"uploads/{uuid.uuid4().hex}/sweep.bin", [],
        )
    return {
        "user_id": str(user["id"]),
        "workspace_id": str(ws["id"]), "wid": str(ws["id"]),
        "slug": ws["slug"],
        "project_id": str(proj["id"]), "pid": str(proj["id"]),
        "file_id": str(f["id"]), "fid": str(f["id"]),
        "revision_id": str(rev["id"]), "rid": str(rev["id"]),
        "thread_id": str(thread["id"]), "tid": str(thread["id"]),
        "token": share["token"],
        "lid": str(share["id"]),
        "submission_id": str(submission["id"]),
        # The caller is the workspace's own owner, so member routes address a
        # real membership row rather than a stranger.
        "member_id": str(user["id"]),
        # A provider the BYO-key routes actually support.
        "provider": "anthropic",
        # /workspaces/avatar/{id} is the only bare {id} in the surface, and it
        # is a workspace. Check that before adding another.
        "id": str(ws["id"]),
        # /admin/distributors/{name} — any name reaches the handler; the
        # 403/404 that follows is a fine answer, a 500 is not.
        "name": "sweep-distributor",
        # Reached via PARAM_BY_PATH — {uid} means this under /uploads and a
        # user id under /members.
        "upload_session_id": str(upload["id"]),
        # First chunk index. The route validates the range before touching
        # storage, so 0 is enough to reach the handler.
        "n": "0",
        # Content-addressed object key. No such blob exists, which is the
        # point — a miss must be a 404, not a 500.
        "oid": "0" * 64,
    }


def auth_headers(user_id: str) -> dict[str, str]:
    now = datetime.now(tz=timezone.utc)
    token = jwt.encode(
        {"sub": user_id, "exp": now + timedelta(hours=1), "iat": now},
        JWT_SECRET, algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


# Params whose meaning depends on the route. {uid} is the honest example: it
# is a *user* id under /members and an *upload session* id under /uploads, and
# filling one with the other is not a harmless miss — it sends a well-formed
# request for a row that cannot exist, which reads as coverage while testing
# nothing. Keyed on a path fragment so a new route under the same prefix picks
# up the right fixture automatically.
PARAM_BY_PATH = {
    ("uid", "/uploads/"): "upload_session_id",
    ("uid", "/members/"): "user_id",
}


def _fixture_key(param: str, path: str) -> str:
    for (name, fragment), key in PARAM_BY_PATH.items():
        if name == param and fragment in path:
            return key
    return param


def fill(path: str, ids: dict[str, str]) -> str | None:
    """Substitute {param} placeholders from the fixtures, or None."""
    out = path
    while "{" in out:
        start = out.index("{")
        end = out.index("}", start)
        name = _fixture_key(out[start + 1:end], path)
        if name not in ids:
            return None
        out = out[:start] + ids[name] + out[end + 1:]
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


def _placeholder(prop: dict, spec: dict, ids: dict[str, str], depth: int = 0) -> Any:
    """A value of the right shape for one property. Not a meaningful value."""
    prop = _resolve(prop, spec)
    if depth > 3:
        return None

    # anyOf/oneOf: take the first non-null branch — how FastAPI spells
    # Optional[X].
    for key in ("anyOf", "oneOf", "allOf"):
        if key in prop:
            branches = [b for b in prop[key] if _resolve(b, spec).get("type") != "null"]
            if branches:
                return _placeholder(branches[0], spec, ids, depth + 1)

    if "default" in prop:
        return prop["default"]
    if prop.get("enum"):
        return prop["enum"][0]

    kind = prop.get("type")
    if kind == "string":
        fmt = prop.get("format")
        if fmt == "uuid":
            return ids["project_id"]
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
        return _body_from_schema(prop, spec, ids, depth + 1)
    return "sweep"


def _body_from_schema(schema: dict, spec: dict, ids: dict[str, str], depth: int = 0) -> dict:
    schema = _resolve(schema, spec)
    required = schema.get("required") or []
    props = schema.get("properties") or {}
    return {name: _placeholder(props.get(name, {}), spec, ids, depth) for name in required}


def request_body(operation: dict, spec: dict, ids: dict[str, str]) -> dict | None:
    body = operation.get("requestBody")
    if not body:
        return None
    schema = ((body.get("content") or {}).get("application/json") or {}).get("schema")
    if schema is None:
        return None
    return _body_from_schema(schema, spec, ids)


def _acceptable(path: str, status: int) -> bool:
    if status == 503 and path in ALLOWED_503:
        return True
    if status == 501 and path in ALLOWED_501:
        return True
    return status < 500


def sweep_reads(client, ids: dict[str, str]) -> tuple[int, list[str], list[str]]:
    """Call every GET route. Returns (called, skipped, failures)."""
    spec = client.app.openapi()
    headers = auth_headers(ids["user_id"])

    called, skipped, failures = 0, [], []
    for path, ops in sorted(spec.get("paths", {}).items()):
        if "get" not in ops:
            continue
        concrete = fill(path, ids)
        if concrete is None:
            skipped.append(path)
            continue
        resp = client.get(concrete, headers=headers)
        called += 1
        if not _acceptable(path, resp.status_code):
            failures.append(f"{resp.status_code} GET {path} -> {resp.text[:200]}")
    return called, skipped, failures


def sweep_writes(client, ids: dict[str, str]) -> tuple[int, list[str], list[str]]:
    """Call every POST/PUT/PATCH/DELETE route. Returns (called, skipped, failures)."""
    spec = client.app.openapi()
    headers = auth_headers(ids["user_id"])

    operations = []
    for path, ops in spec.get("paths", {}).items():
        for method, operation in ops.items():
            if method in WRITE_ORDER:
                operations.append((WRITE_ORDER[method], path, method, operation))
    operations.sort()

    called, skipped, failures = 0, [], []
    for _, path, method, operation in operations:
        if path in SKIP:
            skipped.append(f"{path} ({SKIP[path]})")
            continue
        concrete = fill(path, ids)
        if concrete is None:
            skipped.append(f"{method.upper()} {path} (unfillable params)")
            continue
        body = request_body(operation, spec, ids)
        resp = client.request(
            method.upper(), concrete, headers=headers,
            **({"json": body} if body is not None else {}),
        )
        called += 1
        if not _acceptable(path, resp.status_code):
            failures.append(f"{resp.status_code} {method.upper()} {path} -> {resp.text[:200]}")
    return called, skipped, failures
