# Save and recovery

Kerf saves your work automatically at every layer — from the moment you type a character to the moment you click Commit. You should never need to reach for Ctrl+S or worry about losing work to a browser crash.

This page explains how the three layers work together and what to do when the load-time Restore prompt appears.

---

## How autosave works

### L1 — Per-keystroke local stash (IndexedDB)

Every change you make is written to your browser's IndexedDB storage **immediately** — before it reaches the server. This happens silently in the background, with no network round-trip required.

**What it protects against:** browser tab crashes, unexpected page refreshes, power loss mid-session, or closing the tab by accident. When you reopen the project, the IndexedDB stash is read and reconciled against the last server-confirmed state.

**What it does not cover:** L1 lives in one browser on one device. Switching to another machine or browser means L1 has nothing there. That's L2's job.

### L2 — Server autosave (file revisions)

After a short idle period (roughly two seconds), Kerf flushes your L1 stash to the server. Each flush creates a `file_revision` row — a timestamped snapshot stored durably in the database.

The **toolbar dot** tells you where your edits stand:

| Dot state | Meaning |
|---|---|
| Grey — *dirty* | L1 has your changes; L2 does not yet |
| Animated — *saving* | The flush request is in flight |
| Green — *saved* | L2 confirmed; local and server are in sync |
| Red — *error* | The flush failed; Kerf is retrying automatically |

### L3 — Git commit (deliberate snapshot)

When you click **Commit** in the Git panel, you create a named, shareable snapshot. This is the only layer that requires a conscious decision. See [commit-and-branches.md](/docs/commit-and-branches) for the full Git UX.

---

## The load-time Restore prompt

If your browser or tab closed before a flush completed, IndexedDB has content that is **newer** than what the server knows about.

When you reopen the project, Kerf detects this automatically:

1. It compares the locally-stashed content against the server's latest revision.
2. If they differ, a **Restore banner** appears at the top of the editor.

The banner gives you two choices:

| Button | What it does |
|---|---|
| **Restore** | Applies the local stash as a new edit. The editor loads the stash content and queues an immediate flush to L2. |
| **Discard** | Clears the IndexedDB entry. The editor loads the server's last-known content. |

If you close the banner without choosing, Kerf does nothing — the stash is preserved so you can decide later.

---

## Cmd+Z undo

`Cmd+Z` (undo) and `Cmd+Shift+Z` (redo) walk the L2 file-revision chain. Each undo writes a new revision with the previous content — the chain grows forward; nothing is ever deleted.

The History drawer (clock icon in the toolbar) shows the full revision list and lets you restore any past state with one click.

For the technical reference, see [file-revisions.md](/docs/file-revisions).

---

## Common questions

### Is my work safe if my browser crashes?

Yes. L1 captured every keystroke into IndexedDB. When you reopen the project you will see the Restore banner — choose **Restore** to get your work back.

### What if I close the tab and forget to commit?

L2 has a continuous history of every save. The History drawer lets you restore any previous version. L3 also fires an automatic "safety-net" commit after 15 minutes of dirty edits, so the commit graph never falls more than 15 minutes behind your L2 history.

### Can I undo after restoring a crash recovery?

Yes. The restore is itself a revision. After a Restore, the History drawer shows the full chain including the restored state, and Cmd+Z walks back from there.

### Does autosave affect performance?

The keystroke stash (L1) is a local IndexedDB write — sub-millisecond, off the main thread. The server flush (L2) is debounced and runs at most once every two seconds, and only when your edits have changed.

---

## Related pages

- [file-revisions.md](/docs/file-revisions) — technical reference for L2 revision history
- [commit-and-branches.md](/docs/commit-and-branches) — deliberate git commits and the branch picker
- [concurrent-editing.md](/docs/concurrent-editing) — what happens when two tabs edit the same file
