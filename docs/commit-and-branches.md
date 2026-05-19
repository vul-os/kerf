# Commits and branches

The Git panel gives you a complete version-control workflow inside the Kerf editor — staged changes, a visual commit graph, branch management, and push/pull state badges — without leaving the page.

Every Kerf project is automatically a git repository from the moment it is created. There is no "Init" step to remember.

---

## Staged changes view

Before you commit, the **Staged Changes** section shows exactly what has changed since the last commit:

- A list of every modified, added, or deleted file, with `A` / `M` / `D` status badges.
- For each file, `+N` and `-N` line counts.
- Click any row to expand an inline summary of that file's diff.

The inline **commit textarea** lives directly below the staged-changes list. Type your commit message there and click **Commit** — the button label updates to reflect the number of changed files (e.g. "Commit 3 files").

After a successful commit, the staged-changes view refreshes automatically and shows an empty state until new edits are flushed by autosave.

---

## Commit graph

Below staged changes, the **Commit Graph** is an SVG timeline of your project's history.

- Each commit appears as a dot on a lane. Multiple lanes are drawn automatically when the branch topology requires them.
- The current branch's tip is highlighted.
- **Click any commit** to open the Commit Diff Viewer: a modal that shows, for that commit, every changed file (with status badges) and an expandable unified diff for each file, with green/red line colouring.
- Click outside the modal or press Esc to close.

Auto-commits (the safety-net commits fired after 15 minutes of dirty edits) use a hollow dot (◌); manual commits use a filled dot (◯). Both appear in the graph and are equally navigable.

---

## Branch picker

The branch picker is a dropdown at the top of the Git panel showing your current branch name.

### Switching branches

Click the dropdown to see all branches. A check mark appears next to the current branch. Click any other branch to check it out.

### Ahead / behind chips

Each branch row shows chips indicating how many commits it is ahead or behind its tracking branch (the remote counterpart on GitHub or GitLab, if connected):

| Chip | Meaning |
|---|---|
| **↑ N** | N local commits not yet pushed |
| **↓ N** | N remote commits not yet pulled |
| **synced** | Local and remote are at the same commit |
| *(no chip)* | No remote configured for this branch |

The Push and Pull buttons in the footer also reflect the current branch's ahead/behind state — "Push ↑3" means you have three commits to push.

### Creating a branch

Inside the branch picker dropdown, type a name in the "New branch…" input and press Enter. The new branch is created from the current HEAD and checked out immediately.

### Deleting a branch

Each branch row has a delete button. Clicking it shows an inline confirmation row. The default branch cannot be deleted.

---

## Push and pull

The **Push** button sends your local commits to the connected GitHub or GitLab remote. The **Pull** button brings down remote commits. Both require a remote to be configured (see [github-sync.md](/docs/github-sync)).

The footer buttons show live ahead/behind counts so you always know what is pending.

---

## Connecting GitHub or GitLab

To enable push/pull, link your account from the Git panel:

1. Click **Connect GitHub** (or **Connect GitLab**) in the Git panel footer.
2. For GitHub: you are redirected through an OAuth flow (scope: `repo`). After authorising, your encrypted token is stored and push/pull are enabled.
3. For GitLab: paste your personal access token (`read_repository` + `write_repository`) and the instance URL (defaults to `https://gitlab.com`).

Once connected, use **Push** to mirror your commits to the external repo and **Pull** to bring in changes made elsewhere. Kerf is always the system of record; the external repo is a mirror.

See [github-sync.md](/docs/github-sync) for full setup details and security notes.

---

## Common questions

### Do I need to run "git init" for a new project?

No. Every project is initialised as a git repository automatically on creation. The Git panel is ready to use immediately.

### What is the difference between autosave and a commit?

Autosave (L2 file revisions) is automatic and fine-grained — every save creates a revision. A git commit is deliberate and named — it creates a snapshot you can share, branch from, or push to GitHub. The two layers coexist and complement each other. See [save-and-recovery.md](/docs/save-and-recovery).

### Can I have multiple branches?

Yes. Use the branch picker to create and switch branches. Each branch maintains its own HEAD. Merging is available via the API (`POST /api/projects/:pid/git/merge`).

### What happens if I push and there are conflicts?

Kerf reports a push error. Pull first to bring in the remote changes, resolve them (using the staged-changes view and History drawer), then push again.

---

## Related pages

- [save-and-recovery.md](/docs/save-and-recovery) — autosave, IndexedDB stash, and crash recovery
- [concurrent-editing.md](/docs/concurrent-editing) — what happens when two tabs edit the same file
- [github-sync.md](/docs/github-sync) — GitHub and GitLab connection setup
- [purge-revisions.md](/docs/purge-revisions) — managing revision history storage
- [file-revisions.md](/docs/file-revisions) — the fine-grained undo layer
