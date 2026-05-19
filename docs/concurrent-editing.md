# Concurrent editing

Kerf uses **optimistic concurrency control (OCC)** to keep your files consistent when more than one tab, browser, or team member edits the same file at the same time.

Kerf does not do live real-time co-editing (like Google Docs). This is a deliberate design choice: CAD files have complex interdependencies that make simultaneous cursor merging unsafe without a purpose-built operational transform layer. Instead, Kerf gives you a clear, non-destructive conflict signal and lets you decide what to do.

---

## How OCC works

Every file carries a `version` counter. Each successful save increments the counter. When your editor saves a file, it sends the version it last read (`expected_version`).

- If the server's current version matches `expected_version` → the save succeeds and the counter increments.
- If the server's current version is higher than `expected_version` → the save is rejected with a **409 Conflict** response.

Nothing is lost in either case. Your local edits remain in L1 (IndexedDB) and in the editor buffer. The server's content — the one that was saved by another tab or user — is also fully intact.

---

## The "Someone else edited this file" banner

When a 409 is returned, the **ConflictBanner** appears at the top of the editor:

> **Someone else edited this file.** Your changes are still here. [Reload to see their version]

| Action | What happens |
|---|---|
| **Reload** | Loads the server's current content into the editor. Your unsaved edits are still in the History drawer (L2) up to the point of your last successful flush. |
| Ignore / keep editing | Your edits stay in the buffer. The next save attempt will succeed if you reload first; if you keep editing without reloading, the conflict banner stays until you do. |

The banner is informational — it does not block editing or auto-overwrite anything.

---

## Usage examples

### Multi-tab editing

1. Open project file `design.json` in Tab A and Tab B.
2. Make an edit in Tab A and wait for the green "saved" dot.
3. Make a different edit in Tab B. When Tab B tries to save, it sees the version Tab A already advanced. Tab B shows the ConflictBanner.
4. Click **Reload** in Tab B to load Tab A's saved state, then re-apply Tab B's intended changes.

### Collaborator conflict

1. You open `assembly.json`. A team member has had it open since before you joined the session.
2. They save first. Your next save shows the ConflictBanner.
3. Click **Reload** to bring in their changes. Use the History drawer to review what they changed (each save is a timestamped revision).
4. Re-apply your changes on top of their version.

### Recovering your edits after a conflict

After clicking Reload, open the **History drawer** (clock icon in the toolbar). You will see your pre-conflict revision listed. Click it to preview your content; click **Restore** to re-apply it as a new revision.

---

## Common questions

### Does Kerf have real-time collaborative editing?

No. Kerf does not merge cursors or apply operational transforms in real time. This is intentional: the parametric feature graph, sketch constraints, and assembly mates create hard ordering requirements that make safe simultaneous edits difficult. The OCC model keeps the data correct and gives you full control over how to reconcile.

### Will I lose my unsaved edits when I click Reload?

No. Your edits live in L1 (IndexedDB) and L2 (file revisions up to the last flush). After clicking Reload, the History drawer shows your last-known revision. You can restore it at any time.

### What if two team members both click Reload at the same time?

The first one to save after reloading wins. The second will see the ConflictBanner again. This is intentional — OCC prevents silent overwrites regardless of how many concurrent editors are present.

### Is the `version` field visible in the API?

Yes. `GET /api/projects/:pid/files/:fid` includes `"version": N` in the response body. `PATCH` accepts an optional `expected_version` field; omitting it skips the version check (useful for headless scripting where you own the serialisation externally).

---

## Related pages

- [save-and-recovery.md](/docs/save-and-recovery) — per-keystroke autosave and crash recovery
- [file-revisions.md](/docs/file-revisions) — revision history and the History drawer
- [commit-and-branches.md](/docs/commit-and-branches) — deliberate snapshots and branches
