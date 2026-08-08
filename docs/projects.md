# Projects

A project is the top-level container for your work in Kerf. Everything — files, chat history, version history, and sharing — lives inside a project.

---

## Data model

```
workspace
└── project
    ├── files            (the design files: .jscad, .feature, .sketch, .assembly, …)
    │   └── file_revisions   (per-file undo/redo history)
    ├── chat_threads
    │   └── messages     (LLM conversation turns + tool calls)
    └── share_links      (access invitation tokens)
```

### Projects

A project belongs to a **workspace** (the box owner gets a personal workspace created on first run). Projects have:

| Field | Description |
|---|---|
| `name` | Display name |
| `description` | Optional description |
| `visibility` | `private`, `unlisted`, or `public` (see [Visibility](#visibility)) |
| `tags` | Free-form labels for search and filtering |
| `readme` | Markdown description shown in the [Workshop](./workshop.md) when the project is public |

### Files

Files are the individual design artefacts inside a project. Each file has a `kind` (`.jscad`, `.feature`, `.sketch`, `.assembly`, `.drawing`, `.circuit.tsx`, and [40+ other kinds](./architecture.md#file-kinds)), optional binary content in storage, and text content in the database for text-based kinds.

Large binary files (≥ 5 MB STEP files) are stored as a pointer (`kind='step-ref'`) with the binary in object storage and a JSON pointer in the database row.

### File revisions

Every write to a text file appends a row to `file_revisions`. This is the OSS-layer undo/redo history. See [file-revisions.md](./file-revisions.md) for the full model.

### Chat threads and messages

Each project has one or more chat threads. A thread is a conversation between a user and the LLM agent. Messages alternate between user turns and assistant turns; tool calls (file reads, edits, creates) appear as `role=tool` rows within assistant turns. The agent loop caps at 10 tool-call iterations per user message.

---

## Visibility

Projects have three visibility levels:

| Level | Who can see it |
|---|---|
| `private` | Only workspace members (owner + anyone with a share link) |
| `unlisted` | Anyone with a direct link; not listed in the Workshop |
| `public` | Listed in the [Workshop](./workshop.md) public gallery |

**Default visibility**: every project — self-hosted or on a Vulos-hosted node like `vulos.org/projects/kerf` — starts `private`. Kerf has no paid tiers, so default visibility is not tier-dependent; publishing to the Workshop is always an explicit, deliberate act (see [node-architecture.md](./node-architecture.md#the-zero-socket-invariant)).

Setting a project to `public` is done via [Workshop publish](./workshop.md#publishing). To revert, use unpublish (`DELETE /api/workshop/:slug`) — this sets visibility back to `private`.

---

## Sharing model

Projects are access-controlled through **workspaces** and **share links**.

### Workspace membership

Workspace members (owner, admin, editor, viewer) have access to all projects in that workspace. Membership is managed through the workspace settings.

### Share links

A share link lets you invite someone to a specific project without adding them to your workspace. Share links:

- Are generated per-project via `POST /api/projects/:pid/share/links`
- Carry a role (`editor` for owners/admins generating them; otherwise the generator's role)
- Can be revoked at any time via `DELETE /api/projects/:pid/share/links/:lid`
- Are looked up via `GET /api/share/:token` (no auth required — token is the credential)
- Can have an optional expiry (`expires_at`) and use count cap (`max_uses`)

Share links grant access to the specific project only, not the whole workspace. For persistent multi-user collaboration on a workspace, add workspace members instead.

To publish a project for anyone to fetch (decentralised, key-signed, no account needed), see [distributed-workshop.md](./distributed-workshop.md).

---

## API

```
GET    /api/projects              — list your projects
POST   /api/projects              — create a project
GET    /api/projects/:pid         — get a project
PATCH  /api/projects/:pid         — update name / description / visibility / tags
DELETE /api/projects/:pid         — delete a project

GET    /api/projects/:pid/files   — list files
POST   /api/projects/:pid/files   — create a file
GET    /api/projects/:pid/files/:fid           — get a file
PATCH  /api/projects/:pid/files/:fid           — update content
DELETE /api/projects/:pid/files/:fid           — soft-delete a file
GET    /api/projects/:pid/files/:fid/download  — download binary

GET    /api/projects/:pid/files/:fid/revisions              — list revisions
GET    /api/projects/:pid/files/:fid/revisions/:rid/content — get full content for a revision
POST   /api/projects/:pid/files/:fid/revisions/:rid/restore — restore a revision

POST   /api/projects/:pid/share/links          — create a share link
GET    /api/projects/:pid/share/links          — list share links
DELETE /api/projects/:pid/share/links/:lid     — revoke a share link
```

---

## Related pages

- [distributed-workshop.md](./distributed-workshop.md) — publish, follow, pin over DMTAP-PUB
- [file-revisions.md](./file-revisions.md) — fine-grained undo
- [github-sync.md](./github-sync.md) — project-level git commits; add any git remote yourself (local git only)
- [workshop.md](./workshop.md) — publishing and forking public projects
- [node-architecture.md](./node-architecture.md) — the single-owner box model, workspaces, local API tokens
