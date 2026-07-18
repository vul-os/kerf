# Auto git init

Every Kerf project is a git repository from the moment it is created. There is no separate "initialise git" step, no checkbox to tick, and no wizard to run. The Git panel is ready to use as soon as you open a new project.

---

## What happens when a project is created

When you create a project in Kerf Cloud, the server automatically:

1. Creates a bare git repository for the project on the storage backend.
2. Registers the project in `cloud_git_repos` so the Git panel can find it.
3. Sets the default branch to `main`.

This is a non-blocking background step. If it fails (for example, due to a transient storage error), the project is still created and usable — you will just see an empty Git panel state until the repo is available. You can trigger the initialisation manually via `POST /api/projects/:pid/git/init` if needed; the endpoint is idempotent.

---

## What "auto git init" means in practice

You can open the Git panel immediately after creating a project and:

- Make edits, let autosave flush them, then click **Commit** — the first commit is created on `main`.
- Create branches right away, before any commit exists.
- Connect to a GitHub or GitLab remote without having to initialise first.

There is no "empty" state to navigate out of. The Staged Changes view, commit graph, and branch picker all work from the first edit.

---

## Relationship to file_revisions

Auto git init creates the cloud git layer (L3). It does not affect the file-revision layer (L2), which runs unconditionally on every install — cloud or self-hosted — without any git initialisation at all.

| Layer | What it is | When it starts |
|---|---|---|
| L2 — `file_revisions` | Per-file autosave and undo stack | Immediately, on every write |
| L3 — Cloud git | Named commits, branches, GitHub sync | From project creation (auto-init) |

The two layers are complementary and coexist. See [save-and-recovery.md](/docs/save-and-recovery) for a full explanation of the three-layer model.

---

## Manual init (self-hosted)

Every Kerf node — self-hosted or `kerf.sh` — runs byte-identical software and auto-initialises git unconditionally; there is no flag that turns the git layer on or off. If a project's repo failed to initialise (see above), call `POST /api/projects/:pid/git/init` to retry — the endpoint is idempotent.

---

## Common questions

### What if I create a project and the Git panel is empty?

This can happen transiently if the background init failed. Refresh the page; if the panel is still empty, navigate to the project settings and click **Initialise git** (which calls the idempotent init endpoint). This is rare under normal conditions.

### Does auto-init create an initial commit?

No. The repo is initialised as a bare repository with no commits. The first commit is created when you click **Commit** (or when the 15-minute auto-commit fires after your first edits).

### Does auto-init affect the file-revision history?

No. `file_revisions` is independent of git. Any revisions created before the auto-init are not affected.

### Can I opt out of the git layer?

No — the git layer is always active on every install, hosted or self-hosted, with no opt-out flag. The `file_revisions` layer runs alongside it regardless.

---

## Related pages

- [commit-and-branches.md](/docs/commit-and-branches) — staged changes, commit graph, and branch picker
- [save-and-recovery.md](/docs/save-and-recovery) — the three-layer save model
- [github-sync.md](/docs/github-sync) — connecting to a GitHub or GitLab remote
- [file-revisions.md](/docs/file-revisions) — the always-on file-revision layer
