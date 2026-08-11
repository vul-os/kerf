# Workspaces

A **workspace** is the container above projects: every project
belongs to exactly one. Created in migration
`1746577400000_workspaces.sql`, which folded `project_members` into
`workspace_members` and replaced `projects.owner_id` with
`projects.workspace_id`.

**There is nobody to share one with.** Kerf is one node, one
password, one user — that user owns every workspace on the node.
Members, invites and roles are removed: the routes are gone, the
Members page is gone, and the flow behind them never worked (adding
someone looked their account up by email, found none because none
can be created, and wrote nothing).

So if the user asks "how do I invite someone to this workspace",
the answer is that you cannot, and it is not a missing feature —
sharing happens between *nodes*, by publishing a project or handing
out a share link, not by adding people to yours. A workspace is a
folder, not a team.

## `workspaces` table

```sql
workspaces (
  id          uuid pk,
  slug        text unique,           -- URL-safe; '/w/<slug>/...' routes
  name        text,                  -- display name
  avatar_storage_key text,           -- S3 / localfs key (POST /avatar)
  created_by  uuid → users(id),
  created_at  timestamptz,
  updated_at  timestamptz
)
```

The `slug` is the user-visible identifier. All workspace-scoped
routes are keyed off it: `/w/<slug>/projects` and
`/w/<slug>/settings`. The slug must be unique
across the install. Renaming the slug breaks bookmarks — the
Settings panel disables it after creation.

## `workspace_members` table

```sql
workspace_members (
  workspace_id  uuid → workspaces(id) on delete cascade,
  user_id       uuid → users(id) on delete cascade,
  role          text check (role in ('owner', 'admin', 'member')),
  created_at    timestamptz,
  primary key (workspace_id, user_id)
)
```

**Vestigial.** The CHECK still admits `owner`/`admin`/`member`,
and in practice every row is the node's single user as `owner`:
they are seeded on workspace create and there is no route left that
adds, removes or re-roles anyone. `get_user_workspace_role` still
reads the table, so it stays.

## `workspace_invites` table

**Dead.** Nothing writes to it and the endpoint that read it is
removed. The table survives because these migrations do not drop
tables. Never suggest it.

## Routes

```
/w/:workspaceSlug/projects   — project list (Projects.jsx)
/w/:workspaceSlug/settings   — workspace meta + avatar (WorkspaceSettings.jsx)
```

Inside a project the URL is
`/p/:projectId/...` — projects do **not** carry the workspace slug
in the URL because the project row holds the `workspace_id`
directly. The Layout component derives the active workspace from
the project on those routes.

## API summary

```
GET    /api/workspaces                            — list mine
POST   /api/workspaces                            — create   { name, slug }
GET    /api/workspaces/:slug                      — fetch one
PATCH  /api/workspaces/:slug                      — { name?, slug? }
DELETE /api/workspaces/:slug                      — owner-only
POST   /api/workspaces/:slug/avatar               — multipart upload
```

The member routes that used to sit under this list — invite,
remove, promote/demote, and the `/api/workspaces/accept` that
consumed an invite — are all removed and return 404.

The `lib/api.js` wrappers (`listWorkspaces`, `createWorkspace`, …)
are the canonical client surface.

## Stores — a confusing pair

There are **two** zustand stores with overlapping names. Don't
confuse them:

- `src/store/workspaces.js` — the **workspaces list** store
  (`useWorkspaces`). Holds the user's full workspace list and the
  active `currentSlug` (persisted to `localStorage` under
  `kerf:currentWorkspaceSlug`). Used by the WorkspaceSwitcher and
  the Projects route.

- `src/store/workspace.js` — the **editor-side workspace** store
  (`useWorkspace`). Holds the *currently open project's* in-editor
  state: the open file, dirty bytes, feature selection, viewport
  camera, history, etc. Has nothing to do with the workspaces
  table — it's named for "the user's open editor workspace" in the
  general sense.

When the LLM needs to "find which workspace a project belongs to",
the answer is on the project row (`workspace_id`), not in either
store. From the API, `GET /api/projects/:id` returns the project
JSON which includes the resolved workspace slug.

## Project ownership

Every `projects` row carries `workspace_id` (NOT NULL). When the
user asks "move this project to another workspace", that's a
backend mutation on `projects.workspace_id` — there's no LLM tool
for it today (the user does it via the Settings UI). The Layout
component looks up `workspace_id → slug` to render the breadcrumb.

## Billing attachment (cloud only)

In the cloud build, billing is attached **per workspace**, not per
user or per project: a single Stripe customer maps to one workspace
row, and storage charges (the `$0.20/GB-month` line) bill the
workspace. The OSS build leaves the cloud billing tables empty —
storage is whatever Postgres + your disk allow.

## Examples

### "Which workspace does project X belong to?"

```js
const proj = await api.getProject(projectId)
proj.workspace_slug   // → 'acme'
```

Or directly from the database side: the `projects.workspace_id`
column is the source of truth.

## Known limits

- **No transfer-project tool.** Moving a project between workspaces
  is UI-only today; the LLM can't do it via tools.
- **Slug is final after creation.** The Settings panel disables
  slug editing once the workspace exists; rename = create new +
  manual move.
- **Multiple workspaces are folders, not teams.** A node supports
  as many as you like; they are all owned by the same single user.
