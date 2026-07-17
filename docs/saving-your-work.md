# Your work is safe in three places

Kerf protects your work at three independent layers. You don't need to think
about them — they run automatically — but understanding them will give you
confidence that nothing is ever lost.

---

## L1 — Local stash (browser storage)

The moment you type anything, Kerf saves it locally in your browser's IndexedDB.
This happens **silently and continuously** — every keystroke, every nudge of a
slider, every change to a parameter.

**What it protects against:** browser tab crashes, power loss, accidental page
refreshes, or closing the tab without thinking. When you reopen the project, your
last edit is waiting exactly as you left it.

**What it does not cover:** L1 lives on one device, in one browser. If you switch
to a laptop or open an incognito window, L1 has nothing to offer. That is what L2
is for.

**The "unsaved changes" warning:** the `beforeunload` browser dialog fires only
when edits in L1 have not yet been flushed to the server (L2). Once L2 confirms
receipt the warning goes away, even though you have not manually saved anything.

---

## L2 — Server autosave (file revisions)

After about two seconds of idle time, Kerf sends your edits to the server. Each
flush creates a `file_revision` row — a timestamped snapshot of the full file
content. The **History** drawer (the clock icon in the toolbar) lets you scroll
back through every revision and restore any of them with one click.

**Toolbar dot states** tell you exactly what is happening:

| Dot colour / label | Meaning |
|---|---|
| Grey — *dirty* | You have typed something; L1 has it, L2 does not yet |
| Animated — *saving* | The flush request is in flight |
| Green — *saved* | L2 confirmed; local and server are in sync |
| Red — *error* | The request failed; Kerf is retrying automatically |

**What it covers:** any device, any browser, as long as you have an internet
connection. File revisions are stored server-side and are never deleted by normal
use (operators control the retention limit; the default is 200 revisions per
file).

**What it is not:** L2 is a fine-grained undo stack, not a collaboration or
branching tool. For branches, sharing, and snapshots you can point others to, see
L3.

See [file-revisions.md](./file-revisions.md) for the full technical reference.

---

## L3 — Git commit (deliberate snapshot)

When you click **Commit** in the Git panel, you write a short message and Kerf
stores a `cloud_git_commits` row. This is the only step that requires a conscious
decision from you, and it is the layer that gives you named, browseable,
share-able history.

**The commit graph** uses two dot styles to distinguish your intent:

| Symbol | Meaning |
|---|---|
| **◯** (filled circle) | A manual commit — you described what changed |
| **◌** (hollow circle) | An auto-saved safety-net commit — fired automatically after 15 minutes of dirty edits with no manual commit, so the graph never has a gap longer than 15 minutes |

**GitHub and GitLab sync** — optional. If you configure GitHub (or GitLab) as a
remote in the Git panel (using your own SSH key or PAT — Kerf brokers no
OAuth), Kerf will push commits to it when you click **Push**, exactly like
`git push` to any remote. The remote is opt-in and can be disconnected at
any time. See [github-sync.md](./github-sync.md) for setup instructions.

---

## How the three layers work together

```
Typing → L1 (instant, device-local)
               ↓ ~2 s idle
         L2 (automatic, cross-device, full history)
               ↓ when you click Commit (or after 15 min)
         L3 (deliberate snapshot, shareable, branchable)
```

You can think of L1 as the crash net, L2 as the time machine, and L3 as the
project diary.

---

## Frequently asked questions

### Is my work safe if the browser tab crashes?

Yes. L1 captured every keystroke. When you reopen the project, it will be
exactly as you left it. L2 will have the most recent server-confirmed state, and
Kerf will reconcile the two automatically.

### Will I lose work if I never click Commit?

No. The autosave commit (L3, hollow dot ◌) fires after 15 minutes of dirty
edits. Even if you close the laptop, the last auto-commit is never more than 15
minutes behind your most recent edits in L2.

### Can I get my data out?

Yes, via two routes:

- **`kerf export` CLI** — exports a project as a zip archive of all its files
  in their current state.
- **GitHub / GitLab sync** — once linked, every commit is a standard git commit
  on a standard remote. You can clone it, fork it, or hand the URL to anyone.

### What if I'm offline?

L1 keeps accumulating your edits locally. L2 will queue the flush and retry as
soon as the network returns. You will see the toolbar dot stay in the *dirty*
or *error* state while offline; it will go green once the connection is
restored. L3 commits require an active connection.
