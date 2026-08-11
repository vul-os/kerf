# API reference

All routes are mounted under `/api` by `kerf-core`. The router is defined in
`packages/kerf-api/src/kerf_api/routes.py`; auth routes live in
`packages/kerf-auth/src/kerf_auth/routes.py`.

## Authentication

A Kerf install is **one node, one password**. There is no central account
system, no sign-up service, and no Google/OAuth login. You set the password on
first load — the browser shows a "Set a password" screen — and exchange it for
a session.

It used to be that `local_mode` (the default, and the only mode a desktop
install has ever used) handed out a full session from `/auth/bootstrap-local`
with **no credential whatsoever**: anything that could reach the port was
signed in. "Bound to loopback" is not on its own a credential, because a
hostile page can point a browser at loopback — DNS rebinding is the usual
route. That endpoint is gone.

Recovery is `kerf admin set-password`, not a reset email: a self-hosted node
has no mail transport, and pretending otherwise is how `/auth/forgot-password`
ended up returning 501.

The session uses two token types:

| Cookie | Type | TTL |
|--------|------|-----|
| `access_token` | HS256 JWT (`sub` = user UUID) | `jwt_access_ttl_minutes` (default 15 min) |
| `refresh_token` | opaque `secrets.token_urlsafe(64)` | `jwt_refresh_ttl_days` (default 30 days) |

For SDK / headless access, long-lived opaque **API tokens** are issued per
workspace and carried in the `Authorization: Bearer <token>` header.

Every endpoint that requires auth is guarded by `require_auth` from
`kerf_core.dependencies`. Endpoints that accept anonymous access for public
projects use `optional_auth`.

---

## Setup endpoints (`/api/setup/…`)

The whole of sign-in. Three routes, no accounts.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/setup/state` | none | Has this node been claimed, and may it be claimed from here? What the first-run screen branches on. Reveals nothing else. |
| POST | `/api/setup/password` | none | Claim an unconfigured node. Succeeds exactly once (409 after). **403 on a non-loopback bind** — claiming a node a stranger can reach is a race with that stranger, so the operator uses `kerf admin set-password` instead. Rate limited: 10/hour per IP. |
| POST | `/api/setup/signin` | none | Exchange the password for a session. Rate limited: 10/minute per IP. An unclaimed node and a wrong password return the identical 401, because which of the two it is tells an attacker whether the node is still claimable. |

## Auth endpoints (`/api/auth/…`)

What is left once sign-in moved: token lifecycle only.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/refresh` | refresh token | Issue a new access token from a valid refresh token. |
| POST | `/api/auth/logout` | any | Revoke the current refresh token. |

`register`, `login`, `forgot-password`, `reset-password`, `bootstrap-local`,
and the Google and GitHub OAuth routes are gone. So are the pages that drove
them: there is no `/login` and no `/signup`.

---

## Bootstrap / config

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/config` | none | Public feature flags: `local_mode`. No secrets returned. |
| GET | `/api/bootstrap` | none | Local-mode only. Returns persisted `refresh_token` from `~/.config/kerf/state.json`. |
| GET | `/api/models` | none | Available LLM models (`claude-sonnet-4`, `claude-opus-4`, …). |

---

## Current user

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/me` | required | Authenticated user profile + default workspace. |
| PATCH | `/api/me` | required | Update `name`. |
| POST | `/api/me/avatar` | required | Upload avatar image. |
| DELETE | `/api/me/avatar` | required | Remove avatar. |

**GET /api/me response**

```json
{
  "id": "uuid",
  "email": "user@example.com",
  "name": "Jane Smith",
  "avatar_url": "",
  "account_role": "user",
  "is_system": false,
  "created_at": "2025-01-01T00:00:00Z",
  "default_workspace": { "id": "uuid", "slug": "my-ws", "name": "My Workspace" }
}
```

---

## Workspaces

Workspaces are the multi-member containers that own projects. Every user gets
a personal workspace on first login.

Roles: `owner` > `admin` > `member`.

| Method | Path | Auth | Min role |
|--------|------|------|----------|
| GET | `/api/workspaces` | required | self |
| POST | `/api/workspaces` | required | — (creates) |
| GET | `/api/workspaces/{slug}` | required | member |
| PATCH | `/api/workspaces/{slug}` | required | admin |
| DELETE | `/api/workspaces/{slug}` | required | owner |
| POST | `/api/workspaces/accept` | required | — (invite token) |
| GET | `/api/workspaces/avatar/{id}` | none | — |
| POST | `/api/workspaces/{slug}/avatar` | required | admin |
| DELETE | `/api/workspaces/{slug}/avatar` | required | admin |
| POST | `/api/workspaces/{slug}/members` | required | admin |
| PATCH | `/api/workspaces/{slug}/members/{member_id}` | required | admin |
| DELETE | `/api/workspaces/{slug}/members/{member_id}` | required | admin |

**Workspace object**

```json
{
  "id": "uuid",
  "slug": "my-org",
  "name": "My Org",
  "avatar_url": "/api/workspaces/avatar/uuid",
  "my_role": "owner",
  "member_count": 3,
  "project_count": 12,
  "created_at": "…"
}
```

---

## Projects

Projects belong to a workspace. Visibility: `private` | `unlisted` | `public`.

| Method | Path | Auth | Min role |
|--------|------|------|----------|
| GET | `/api/projects` | required | member |
| POST | `/api/projects` | required | member |
| GET | `/api/projects/{pid}` | required | member |
| PATCH | `/api/projects/{pid}` | required | member |
| DELETE | `/api/projects/{pid}` | required | owner |
| GET | `/api/projects/{pid}/bom` | required | member |
| GET | `/api/projects/{pid}/export` | required | member |
| POST | `/api/projects/{pid}/thumbnail` | required | member |
| GET | `/api/projects/{pid}/cover` | required | member |

**POST /api/projects body**

```json
{
  "workspace_id": "uuid",
  "name": "My Part",
  "description": "",
  "tags": ["mech", "prototype"],
  "starter": "jscad"
}
```

`starter` accepts `"jscad"` (seeds a default `.jscad` script), `"circuit"`, or
`"blank"`.

**GET /api/projects — query params**

- `workspace_id` or `workspace_slug` — filter to one workspace
- `tag` — filter by tag (array-contains)

**GET /api/projects/{pid}/bom response**

```json
{
  "rows": [
    {
      "part": { "name": "M3×10 cap screw", "mpn": "…", "distributors": [] },
      "file_id": "uuid",
      "path": "/hardware/m3_cap_screw.part",
      "count": 12,
      "unit_price_usd": 0.08,
      "total_price_usd": 0.96
    }
  ],
  "total_price_usd": 4.20,
  "warnings": []
}
```

---

## Files

Files are the leaf nodes of the project tree. A `folder` is a file with
`kind='folder'` and no content. Files are soft-deleted (`deleted_at`); bytes
are retained until a purge pass.

| Method | Path | Auth | Min role |
|--------|------|------|----------|
| GET | `/api/projects/{pid}/files` | required | member |
| POST | `/api/projects/{pid}/files` | required | member |
| GET | `/api/projects/{pid}/files/{fid}` | required | member |
| PATCH | `/api/projects/{pid}/files/{fid}` | required | member |
| DELETE | `/api/projects/{pid}/files/{fid}` | required | member |
| GET | `/api/projects/{pid}/files/{fid}/download` | required | member |

Valid kinds for POST: `file`, `folder`, `assembly`, `drawing`, `sketch`,
`part`, `feature`, `circuit`, `equations`, `script`, `fem`, `cam`.

**File object (list response)**

```json
{
  "id": "uuid",
  "project_id": "uuid",
  "parent_id": null,
  "name": "bracket.feature",
  "kind": "feature",
  "extension": null,
  "storage_key": null,
  "download_url": null,
  "tessellation_status": null,
  "created_at": "…",
  "updated_at": "…"
}
```

---

## Async jobs (FEM, CAM, simulation, tessellation)

All heavy compute runs as an async job. Submit → poll for status.

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/projects/{pid}/files/{fid}/tessellate` | Queue STEP → glTF tessellation |
| DELETE | `/api/projects/{pid}/files/{fid}/tessellate` | Re-queue (purge cached mesh) |
| POST | `/api/projects/{pid}/files/{fid}/fem` | Submit FEA job |
| GET | `/api/projects/{pid}/files/{fid}/fem/status` | Poll FEA: `queued` / `running` / `done` / `error` |
| POST | `/api/projects/{pid}/files/{fid}/cam` | Submit CAM job |
| GET | `/api/projects/{pid}/files/{fid}/cam/status` | Poll CAM |
| POST | `/api/projects/{pid}/files/{fid}/sim` | Submit dynamics simulation |
| GET | `/api/projects/{pid}/files/{fid}/sim/status` | Poll simulation |

**Status response**

```json
{ "job_id": "uuid", "status": "done", "result": { … }, "error": null }
```

---

## Assembly, tolerance, derived artifacts

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/projects/{pid}/files/{fid}/solve-mates` | Solve assembly mate constraints. Body: `{ "fixed_component_id": "uuid" }` |
| POST | `/api/projects/{pid}/files/{fid}/tolerance/run` | Run tolerance stack-up. Body: `{ "method": "monte_carlo", "samples": 10000, "rss_k": 3.0 }` |
| POST | `/api/projects/{pid}/files/{fid}/derived` | Compute or fetch a derived artifact (thumbnail, glTF, PDF) |
| POST | `/api/projects/{pid}/files/{fid}/derived/store` | Store a derived artifact key |
| DELETE | `/api/projects/{pid}/files/{fid}/derived` | Purge derived artifact |
| GET | `/api/projects/{pid}/files/{fid}/diff` | Diff two revisions of a file |

---

## Uploads (chunked)

Large binary files (STEP, renders) use a chunked upload protocol.

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/projects/{pid}/uploads` | Initiate; returns `upload_id` |
| PUT | `/api/projects/{pid}/uploads/{uid}/chunks/{n}` | Upload chunk `n` |
| GET | `/api/projects/{pid}/uploads/{uid}` | Check upload status |
| POST | `/api/projects/{pid}/uploads/{uid}/finalize` | Finalize and create file record |
| DELETE | `/api/projects/{pid}/uploads/{uid}` | Abort upload |

---

## Chat threads and messages

| Method | Path | Auth | Notes |
|--------|------|------|-------|
| GET | `/api/projects/{pid}/threads` | required | List threads for project |
| POST | `/api/projects/{pid}/threads` | required | Create thread |
| PATCH | `/api/projects/{pid}/threads/{tid}` | required | Update title / model |
| DELETE | `/api/projects/{pid}/threads/{tid}` | required | Delete thread |
| GET | `/api/projects/{pid}/threads/{tid}/messages` | required | List messages |
| POST | `/api/projects/{pid}/threads/{tid}/messages` | member+ | Send message and run agent loop |

**POST message body**

```json
{
  "content": "Make the boss 6 mm tall",
  "model": "claude-sonnet-4-20250514",
  "part_refs": []
}
```

**POST message response**

```json
{
  "user_message": { "id": "uuid", "role": "user", "content": "…" },
  "assistant_message": { "id": "uuid", "role": "assistant", "content": "Done — I updated the pad depth to 6 mm." },
  "tool_messages": [
    { "id": "uuid", "role": "tool", "content": "{\"ok\":true}" }
  ]
}
```

The agent loop runs up to 10 tool-call iterations inside the single HTTP
request. Viewer role cannot post messages.

---

## Revisions (undo history)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/projects/{pid}/files/{fid}/revisions` | List revisions. Query: `limit` (max 200) |
| GET | `/api/projects/{pid}/files/{fid}/revisions/{rid}` | Get one revision metadata |
| GET | `/api/projects/{pid}/files/{fid}/revisions/{rid}/content` | Get revision full content |
| POST | `/api/projects/{pid}/files/{fid}/revisions/{rid}/restore` | Restore file to this revision |

**Revision object**

```json
{
  "id": "uuid",
  "file_id": "uuid",
  "source": "llm",
  "user_id": "uuid",
  "user_name": "Jane",
  "content_preview": "{ \"version\": 3, \"features\": [ …",
  "created_at": "…"
}
```

`source` is `user` | `llm` | `tool` | `restore`.

---

## Members

Local project collaboration. Publishing or sharing a project *outside* your
box is not done with hosted share links — it goes through the decentralised,
key-signed **Workshop** (DMTAP-PUB); see the Workshop section below and
[distributed-workshop.md](./distributed-workshop.md).

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/projects/{pid}/members` | List members |
| POST | `/api/projects/{pid}/members` | Add member |
| PATCH | `/api/projects/{pid}/members/{uid}` | Change member role |
| DELETE | `/api/projects/{pid}/members/{uid}` | Remove member |

---

## Imports

| Method | Path | Notes |
|--------|------|-------|
| POST | `/api/projects/{pid}/imports/kicad` | Import a KiCad `.kicad_pcb` file. Multipart form. |
| POST | `/api/projects/{pid}/files/{fid}/distributors/refresh` | Re-fetch distributor pricing for a `.part` file |

---

## Workshop

Decentralised, key-signed publishing and following, backed by DMTAP-PUB
(see [distributed-workshop.md](./distributed-workshop.md)) — not a hosted
catalog or gallery. No license or config flag gates it — every node mounts
these endpoints; whether anything is actually published or fetched depends
on the node's own toggles and the user's explicit publish/follow actions.

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/workshop/` | optional |
| GET | `/api/workshop/parts` | optional |
| GET | `/api/workshop/{slug}` | optional |
| POST | `/api/workshop/publish` | required |
| POST | `/api/workshop/regenerate-readme` | required |
| DELETE | `/api/workshop/{slug}` | required |
| POST | `/api/workshop/{slug}/like` | required |
| POST | `/api/workshop/{slug}/fork` | required |

---

## Library (parts catalog)

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/library/parts` | Search community parts. Query: `q`, `page`, `per_page` |
| GET | `/api/library/parts/{slug}` | Get one part |
| POST | `/api/library/submissions` | Submit a new part |
| GET | `/api/admin/library/submissions` | Admin: list pending submissions |
| PUT | `/api/admin/library/submissions/{id}` | Admin: approve / reject |

---

## Blobs

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/blobs/{path}` | Fetch a storage blob by key. Returns bytes (local backend) or 302 to presigned URL (S3). Requires auth on the project that owns the blob. |

---

## Operating the node (`/api/admin/…`)

Configuring supplier feeds and moderating this node's library. Authenticated —
that is the whole check, because there is one user and they own the node.

These asked for `users.account_role in ('admin', 'system')` until recently.
Nothing in Kerf writes that column: it defaults to `'user'`, and no route,
migration or seed changes it. So every endpoint here answered 403 to the only
user who can exist, on every install.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/admin/distributors` | Configured supplier feeds (Digi-Key and friends) that price `.part` files |
| PUT | `/api/admin/distributors/{name}` | Enable, rate-limit, or set the credential for one |
| DELETE | `/api/admin/distributors/{name}` | Remove one |
| GET | `/api/admin/library/submissions` | This node's submission queue |
| PUT | `/api/admin/library/submissions/{id}` | Approve or reject a submission |

`/api/admin/publishers` is gone. It marked a user `is_verified_publisher`,
which a node cannot meaningfully assert about itself — whose parts you trust is
decided by whose feed you follow, not by a flag the publisher sets.

---

## Health and capabilities

Mounted by `kerf-core`, not `kerf-api`.

| Method | Path | Notes |
|--------|------|-------|
| GET | `/health` | `{"status":"ok"}` |
| GET | `/health/capabilities` | Union of all loaded plugin `provides` lists + per-plugin metadata |

---

## Status codes

| Code | Meaning |
|------|---------|
| 200 | OK |
| 201 | Created |
| 204 | No content (DELETE success) |
| 400 | Bad request — malformed input, validation failure |
| 401 | Unauthenticated — missing or expired token |
| 403 | Forbidden — authenticated but insufficient role |
| 404 | Not found (also returned instead of 403 on resource isolation) |
| 409 | Conflict — slug collision, duplicate entry |
| 410 | Gone — resource retired or no longer available |
| 500 | Unexpected server error |

Tool-call errors inside the agent loop never return 500 — they return
`{"error": "…", "code": "…"}` JSON that the LLM can inspect.

---

See also: [data-model.md](./data-model.md) · [v1-rpc.md](./v1-rpc.md) · [architecture.md](./architecture.md)
