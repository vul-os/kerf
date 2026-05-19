# File revisions

Every text file in Kerf has automatic, fine-grained version history. This is an OSS feature — it is present in every install, cloud or self-hosted, with no configuration required.

`file_revisions` is **invisible plumbing** — it runs automatically behind every save. You interact with it through the History drawer and Cmd+Z; you never need to manage it directly for normal use. For crash recovery and the load-time Restore banner, see [save-and-recovery.md](/docs/save-and-recovery). For the cloud git layer (named commits, branches, GitHub sync), see the [Git tab documentation](/docs/commit-and-branches).

---

## How it works

Every write to a text file — whether from the editor, an LLM tool call, or a restore — appends a row to the `file_revisions` table. Each row records:

| Field | Description |
|---|---|
| `id` | UUID |
| `file_id` | The file this revision belongs to |
| `source` | `user`, `llm`, `tool`, or `restore` |
| `user_id` | Who triggered the write (null for system ops) |
| `created_at` | Timestamp |
| `content_gz` | Gzipped content (Phase 4+; preferred) |
| `content` | Plaintext content (legacy; still readable) |
| `sha256` | Content hash for deduplication |
| `content_preview` | First 200 chars for the History drawer |

### Storage efficiency (Phase 4)

Revision storage uses gzip + SHA-256 deduplication. If two writes produce identical content, only one blob is stored. The read path reconstructs content on demand — the list endpoint returns lightweight previews; the full content is loaded lazily via a separate endpoint.

A `file_revisions_max` limit (default 200 rows per file) trims the oldest rows on each write so the table does not grow unbounded.

---

## Undo and redo

`Cmd+Z` in the editor calls:

```
POST /api/projects/:pid/files/:fid/revisions/:rid/restore
```

This writes a new revision with `source='restore'` pointing at the previous content — rather than mutating the history. The full revision chain is always readable; nothing is ever overwritten.

`Cmd+Shift+Z` re-applies the most recent `restore`-sourced revision in the same way.

---

## History drawer

The History drawer in the UI lists revisions for the currently-open file:

```
GET /api/projects/:pid/files/:fid/revisions?limit=50
```

Returns revisions ordered by `created_at DESC` with previews. Full content for a specific revision is fetched on demand:

```
GET /api/projects/:pid/files/:fid/revisions/:rid/content
```

Response: `{id, content}` — the full reconstructed text for that revision.

---

## Restoring a deleted file

Files are soft-deleted (`deleted_at` flag). The revision chain is kept intact. Restoring a deleted file via:

```
POST /api/projects/:pid/files/:fid/revisions/:rid/restore
```

clears `deleted_at` and resurfaces the file with the content from the specified revision.

---

## Sources

| Source value | When it appears |
|---|---|
| `user` | Editor PATCH — the user typed and saved |
| `llm` | LLM assistant wrote the file |
| `tool` | An LLM tool call edited the file (e.g. `edit_file`) |
| `restore` | A previous revision was restored (undo/redo) |

---

## File revisions vs cloud git

These are two different, coexisting layers:

| Layer | Granularity | Automatic | Branches |
|---|---|---|---|
| `file_revisions` | Every save | Yes | No |
| Cloud git | Deliberate commits | No (user clicks Commit) | Yes |

File revisions are the undo stack. Cloud git is the snapshot/collaboration layer. See [github-sync.md](./github-sync.md) for the cloud git layer.

---

## Maintenance (self-hosted operators)

### Repack legacy rows

Phase 4 migrated revision storage to gzip. Existing plaintext rows continue to read via the legacy `content` column. To backfill:

```sh
# Dry run — reports rows that would be touched
kerf-server revisions repack --dry-run

# Compress all legacy rows (leaves content column populated as a safety net)
kerf-server revisions repack

# Compress and remove the legacy column once verified on a non-prod replica first
kerf-server revisions repack --prune-legacy
```

The command is idempotent and processes rows in batches of 500 (tunable with `--batch=N`). It does not run on server boot — schedule it explicitly.

### Retention limit

The limit is configurable in `kerf.toml`:

```toml
[limits]
file_revisions_max = 200
```

Lowering this trims on the next write to each file. Raising it keeps more history but increases storage.

---

## Related pages

- [save-and-recovery.md](/docs/save-and-recovery) — crash recovery, IndexedDB autosave, and the load-time Restore banner
- [concurrent-editing.md](/docs/concurrent-editing) — OCC conflict detection and the "Someone else edited this file" banner
- [purge-revisions.md](/docs/purge-revisions) — trimming old revision rows to reclaim storage
- [commit-and-branches.md](/docs/commit-and-branches) — deliberate git commits and the Git tab
- [projects.md](/docs/projects) — project and file model
- [github-sync.md](/docs/github-sync) — deliberate git commits (cloud)
- [local-self-host.md](/docs/local-self-host) — self-hosted maintenance commands
