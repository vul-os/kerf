# GitHub sync

Kerf Cloud provides a hosted git layer for projects. It is a deliberate-commit version control layer that sits on top of (and complements, not replaces) the always-on [file revision history](./file-revisions.md).

This feature is cloud-only by nature: it presupposes a hosted managed git remote. A self-hosted Kerf install retains full version-control capability through `file_revisions` alone.

---

## Two version-control layers

Kerf has two coexisting layers. They are not alternatives.

| Layer | Scope | When it writes | Who uses it |
|---|---|---|---|
| `file_revisions` (OSS, always-on) | Per-file | Every save (automatic) | Cmd+Z undo, History drawer |
| Cloud git (hosted, deliberate) | Project-level | When you click Commit | Branches, GitHub sync, code review |

See [file-revisions.md](./file-revisions.md) for the OSS layer.

The cloud git layer exists because customers — especially those working with large STEP files and production BOM tracking — need:
- Explicit named checkpoints ("v2 — rounded corners approved")
- Branching to explore design variants without losing the main state
- A GitHub remote to integrate with downstream CI / ERP

---

## Initialising git for a project

```
POST /api/projects/:pid/git/init
```

This creates a bare git repo for the project (stored on the server side in the configured storage backend) and registers the project in `cloud_git_repos`. Idempotent — calling it again returns the existing state.

Response:
```json
{
  "project_id": "...",
  "default_branch": "main",
  "head_sha": ""
}
```

---

## Branches

| Operation | Endpoint |
|---|---|
| List branches | `GET /api/projects/:pid/git/branches` |
| Create a branch | `POST /api/projects/:pid/git/branches` — body: `{name, from_sha?}` |
| Checkout a branch | `POST /api/projects/:pid/git/checkout` — body: `{branch, force?}` |

Branches are tracked in `cloud_git_branches`. `head_sha` is updated on every commit.

---

## Commits

```
POST /api/projects/:pid/git/commit
```

Body: `{message, branch?}`

A commit captures the current state of all project files into the git repo. The commit SHA is recorded in `cloud_git_commits` (which serves as the commit-graph index for the UI). The bare repo on the server is the source of truth; `cloud_git_commits` is a denormalised cache.

Commit log:
```
GET /api/projects/:pid/git/log?branch=main&limit=50
```

---

## Merge

```
POST /api/projects/:pid/git/merge
```

Body: `{from_branch, into_branch}`

Merges one branch into another. Conflicts surface as an error — the caller is expected to resolve and retry.

---

## GitHub sync

GitHub sync connects a Kerf project to a GitHub repository so that commits can be pushed to (and pulled from) a remote.

### Connecting a GitHub account

1. Navigate to **Settings → GitHub** in the app.
2. Click **Connect GitHub** — this starts the OAuth flow via `GET /auth/github/start` (scope `repo`).
3. After authorising in GitHub, you are redirected back and your token is stored encrypted at rest.

To disconnect: `DELETE /auth/github`

### Connecting a repo to a project

Once your GitHub account is connected, link a specific repo to a project:

```
POST /api/projects/:pid/git/connect
```

Body: `{github_owner, github_repo}`

### Import from a GitHub URL

You can also initialise git for a project from an existing GitHub repo:

```
POST /api/projects/:pid/git/import
```

Body: `{github_url, branch?}`

This registers the remote URL. The initial content import (cloning) happens on the next pull.

### Push and pull

```
POST /api/projects/:pid/git/push   — push local commits to GitHub
POST /api/projects/:pid/git/pull   — pull remote commits from GitHub
```

---

## What is stored where

| Data | Location |
|---|---|
| File content (current) | Postgres `files.content` + object storage for binaries |
| Per-file revision history | Postgres `file_revisions` |
| Git objects (commits, trees, blobs) | Server-side bare repo in the storage backend |
| Commit metadata index | Postgres `cloud_git_commits` and `cloud_git_branches` |
| GitHub OAuth token | Postgres `cloud_github_tokens` — AES-GCM encrypted |
| GitHub remote URL | Postgres `cloud_git_repos.github_remote_url` |

For stateless deployments, the git backend uses an object-storage-backed storer (`S3GitStorer`) that keeps bare repos in object storage. The consistency protocol uploads objects before updating refs so a concurrent reader never sees a ref pointing to a missing object.

---

## GitHub OAuth token security

The GitHub access token is never stored in plaintext. It is encrypted with AES-GCM using a key derived from the server's `JWT_SECRET`. Rotating `JWT_SECRET` invalidates all stored tokens — users must re-link their GitHub account on the next push or pull operation.

---

## Related pages

- [file-revisions.md](./file-revisions.md) — the OSS per-file undo layer
- [projects.md](./projects.md) — project model
- [account-and-auth.md](./account-and-auth.md) — GitHub OAuth for sign-in vs for repo connect
- [cloud-features.md](./cloud-features.md) — why git is cloud-only by nature
