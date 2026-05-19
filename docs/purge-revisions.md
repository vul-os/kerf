# Purge revision history

File revision history accumulates automatically over time — every keystroke flush creates a row. For projects with a long editing history or many files, this can grow large. The Purge Revisions feature lets you trim old revisions to reclaim storage while keeping a configurable number of recent ones per file.

---

## When to use it

Purging is appropriate when:

- The revision-history badge in the Git panel shows a size that is larger than you want to keep (e.g. hundreds of MB of compressed history on a large project).
- You are finishing a project phase and want a clean baseline — old keystroke-level history is no longer useful.
- You are approaching a storage quota and want to free space without deleting files.

You do **not** need to purge regularly. The server trims revisions automatically per the `file_revisions_max` limit (default 200 per file). Purging is for when you want to reduce below that limit, or reclaim space on an old project.

---

## What purging deletes

Purging removes the **oldest** revision rows for each file, keeping the N most recent ones you specify. Specifically:

- It keeps the N most recent revisions per file (you choose N; minimum 1).
- It removes everything older than those N rows — both the database rows and the associated gzip blobs.
- It protects rows that are the parent of a chained restore (i.e. rows that are the anchor of an undo chain in progress). These are skipped automatically.

After purging, the History drawer shows only the retained revisions. Older history is gone and cannot be recovered.

---

## What purging does NOT affect

- **Your files' current content.** Purging never touches the live content of any file — only the history rows.
- **Git commits.** The cloud git layer (commits, branches, the commit graph) is a separate store. Purging revision rows has zero effect on your git history, branches, or any connected GitHub/GitLab remote.
- **The `file_revisions_max` retention limit.** Purging is a one-time operation. New revisions will continue to accumulate up to the configured limit after the purge.

---

## How to purge

1. Open the **Git panel** (bottom-right of the editor).
2. In the revision-history section, click **Manage…** — this opens the Purge Revisions modal.
3. The modal shows the current estimated size of your revision history.
4. Choose how many recent revisions to keep per file (default shown; minimum 1).
5. Check the confirmation checkbox: **"I committed everything I want to keep"**. This gate is deliberate — purging is irreversible, and a recent git commit is the right safety net.
6. Click **Purge**. The modal shows the result: rows removed and bytes freed.

The confirmation checkbox cannot be bypassed in the UI. If you have uncommitted changes you care about, click Commit in the Git panel first.

---

## The "I committed everything" gate

The confirmation checkbox is not just a safety warning — it is a prompt to verify your intent. Purging removes history that Cmd+Z and the History drawer rely on. If you have made edits that exist only in L2 (file revisions) and not in L3 (a git commit), those edits will survive the purge only if they are within the N revisions you chose to keep.

The recommended workflow before purging:
1. Review the Staged Changes view — make sure nothing is pending.
2. Click **Commit** to create a named snapshot.
3. Then open **Manage…** and purge.

---

## Common questions

### Can I undo a purge?

No. Once revision rows are deleted, they are gone. This is why the confirmation gate asks you to commit first.

### Will purging affect my git history?

No. Git commits, branches, and any GitHub/GitLab mirror are entirely unaffected. Purge only removes `file_revision` rows.

### What happens to files that are within the keep-N window?

They are untouched. Only revisions older than the N most recent per file are removed.

### Is there a minimum value for "keep last N"?

Yes — you must keep at least 1 revision per file. The API rejects `keep_last < 1`.

### Can I automate purging?

Yes, via the API:

```
DELETE /api/projects/:pid/revisions?keep_last=N&confirm=PURGE
```

The `confirm=PURGE` token is required in addition to authentication with editor role. Omitting it returns a 400.

---

## Related pages

- [file-revisions.md](/docs/file-revisions) — how revision history works and retention limits
- [save-and-recovery.md](/docs/save-and-recovery) — the three-layer save model
- [commit-and-branches.md](/docs/commit-and-branches) — git commits and the commit graph
