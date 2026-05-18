# Large-object hydration — vanilla-clone UX decision record

**Status**: decision record (T-137). Last-touched: 2026-05-18.
**Depends-on**: T-132 (LFS-format pointer module), T-127 (`kerf sync`).

---

## Problem

Kerf commits large files as Git-LFS-format pointer stubs (T-132). The
three-line stub (`version` / `oid sha256:…` / `size`) is stored in the git
tree; the real bytes live in Tigris S3. A bare `git clone` without Kerf
tooling yields a working tree full of these stubs — each one is a valid text
file, but it is not the real file.

"You can clone with plain git" is the anti-lock-in promise. That promise is
hollow if the next step after cloning is undocumented or requires side-channel
knowledge. This record specifies the documented, frictionless path from "I
cloned and have stubs" to "I have real bytes", and every design decision along
that path.

---

## What a stub looks like on disk

After a bare clone, any large file (above the `git_inline_max_bytes` threshold
— default 1 MiB, or any binary regardless of size) appears as:

```
version https://git-lfs.github.com/spec/v1
oid sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
size 14765432
```

The file is valid UTF-8, exactly these three lines, and weighs roughly 150
bytes rather than the original 14 MB. Tools that try to open it as a real CAD
file will produce a parse error or display an empty model.

### How the user is told about the stub state

The `kerf` CLI detects stubs in two places:

1. **On any command that reads a file**: if the file content matches the
   LFS pointer format, the CLI prints to stderr and exits non-zero:

   ```
   error: 'parts/housing.step' is a large-file pointer stub (14.1 MB).
   Run `kerf hydrate` (or `kerf hydrate parts/housing.step`) to fetch
   the real bytes from Kerf cloud storage.
   ```

2. **On `kerf status` / `kerf ls`**: pointer stubs are flagged with a `[stub]`
   marker and their declared `size` in human-readable form:

   ```
   parts/housing.step   [stub  14.1 MB]
   parts/gearbox.step   [stub   2.3 MB]
   src/assembly.json    ok     4.1 KB
   ```

The plain-git case is also called out in the README at the top of every
repository:

```
# Large files
Some files in this repo are stored as LFS-format pointer stubs.
To fetch real bytes: `kerf hydrate`  (requires kerf CLI + account).
Plain git clone: works. Stub files are valid text. CAD tools need the
real bytes — run kerf hydrate once.
```

---

## Primary command: `kerf hydrate`

`kerf hydrate` is the canonical one-shot command for converting stubs to real
bytes. It is idempotent: running it on a directory that is already fully
hydrated is a no-op.

### Synopsis

```
kerf hydrate [<path|glob> ...]  [--project <id>]  [--url <api-url>]
             [--concurrency <n>]  [--dry-run]  [--force]
```

### Alias

```
kerf pull-blobs [<path|glob> ...]  [same flags]
```

`kerf pull-blobs` is a full alias; both spellings are permanent. The `pull-blobs`
alias surfaces in error messages when the context is explicitly a git
checkout ("you cloned and have stubs"), while `hydrate` is used in all other
contexts. Neither is deprecated.

### Arguments

| Argument | Meaning |
|---|---|
| `<path|glob>` | One or more file paths or glob patterns (e.g. `*.step`, `parts/`). Defaults to `.` — the whole working tree. |

### Flags

| Flag | Default | Meaning |
|---|---|---|
| `--project <id>` | Inferred from `.kerf/project` or the repo remote URL | The Kerf project whose Tigris bucket holds the blobs. |
| `--url <api-url>` | `$KERF_API_URL` or `https://kerf.sh` | Override the API endpoint. |
| `--concurrency <n>` | `4` | Number of parallel blob fetches. |
| `--dry-run` | off | Print what would be fetched without writing any bytes. |
| `--force` | off | Re-fetch and overwrite files that appear already hydrated (size matches but force full replace). |

### Auth

The command reads `$KERF_API_TOKEN` (an opaque API token of the form
`kerf_sk_…`). Generate one from **Settings → API Tokens** in the web app or:

```sh
export KERF_API_TOKEN=kerf_sk_<your-token>
```

For self-hosted installs, also set:

```sh
export KERF_API_URL=http://your-server:8080
```

A `--token <value>` flag is accepted as a fallback for environments where
shell env vars are inconvenient, but `KERF_API_TOKEN` is preferred.

If no token is present the command exits with:

```
error: no API token found. Set KERF_API_TOKEN or pass --token.
To create a token: https://kerf.sh/w/<workspace>/settings#api-tokens
```

### Resolution flow

For each file path in scope:

1. **Check if stub**: read the first 200 bytes. If the content matches
   `version https://git-lfs.github.com/spec/v1\noid sha256:<64hex>\nsize <n>`,
   parse `oid` and `size`. Otherwise skip (already real bytes).
2. **Resolve project**: if `--project` is not given, look for `.kerf/project`
   in the working tree root. Fall back to parsing the `origin` remote URL for a
   known Kerf hostname pattern (`kerf.sh/<workspace>/<project-slug>`).
   If no project can be inferred, exit with an error listing what was tried.
3. **Check local cache**: look for `<oid>` in `$KERF_BLOB_CACHE_DIR`
   (default `~/.cache/kerf/blobs/`). If a file with the correct sha256
   already exists there, copy it directly without a network round-trip.
4. **Fetch from API**:
   ```
   GET /api/projects/<project-id>/blobs/<oid>
   Authorization: Bearer <token>
   ```
   The server responds with a signed Tigris pre-signed URL (302 redirect) or
   a direct stream. The CLI follows the redirect and writes the bytes to a
   temp file in the same directory as the target.
5. **Verify**: sha256 the downloaded bytes. If they do not match `oid`, delete
   the temp file and report an error for that path; continue with others.
6. **Atomic replace**: `rename(tmp, target)` — the original stub is replaced
   atomically. No partial writes are visible to other processes.
7. **Cache write**: copy the verified bytes into `~/.cache/kerf/blobs/<oid>`
   for future use.

### Partial / selective hydration

```sh
# Hydrate only STEP files
kerf hydrate '**/*.step'

# Hydrate a single file
kerf hydrate parts/housing.step

# Hydrate a subdirectory
kerf hydrate parts/

# Dry-run: show what would be fetched
kerf hydrate --dry-run
```

Selective hydration is useful when working on a large repository where only a
subset of blobs is needed locally (e.g. only the electronics assembly, not the
full mechanical tree).

### Idempotency

A file is skipped (not re-fetched) if:
- Its current content does not match the LFS pointer format (already real
  bytes), **and**
- Its size matches the declared `size` in the original pointer (i.e. we're
  not comparing against a different, real file that happens to be present).

Use `--force` to override and re-fetch unconditionally.

### Failure and retry

- **Per-file errors** are logged to stderr and do not abort the batch. The
  command exits non-zero if any file failed.
- **Network errors** are retried up to 3 times with exponential backoff
  (1 s, 2 s, 4 s) before the file is marked failed.
- **Partial batch**: if hydration is interrupted (Ctrl-C, OOM kill), the
  already-completed files remain hydrated (atomic replace ensures no corrupt
  intermediate state). Re-run `kerf hydrate` to resume — it skips already-
  hydrated files.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All targeted files are now hydrated (or were already). |
| `1` | One or more files failed to hydrate. |
| `2` | Auth failure (no token, token revoked). |
| `3` | Project not found or no blobs endpoint on this server version. |

### Progress output (non-dry-run)

```
Scanning working tree for pointer stubs...
  Found 12 stubs  (total: 847.3 MB)

Fetching blobs  [████████░░░░░░░░]  4/12  (282.4 MB / 847.3 MB)
  ✓  parts/housing.step        (14.1 MB)
  ✓  parts/gearbox.step         (2.3 MB)
  ✓  parts/motor_mount.step     (1.8 MB)
  ✓  pcb/mainboard.kicad_pcb  (264.2 MB)
  ↺  parts/casing_top.step     failed: sha256 mismatch — retrying (1/3)
  ...

Done. 11 hydrated, 1 failed.
Re-run `kerf hydrate parts/casing_top.step` to retry.
```

---

## `kerf sync` implicit hydration (T-127 interaction)

`kerf sync` is the two-way folder mirror between a cloud project and a local
directory. When `kerf sync` pulls a file that is stored as a large object
(Tigris blob) it hydrates it transparently — the user never sees a stub on
disk after a sync.

Concretely:

- `kerf sync <project-id> <local-dir>` — for each file whose server-side
  representation is a pointer (`files.storage_key` is set), the sync engine
  fetches the Tigris blob and writes the real bytes to disk, not the pointer
  text.
- The same resolution flow as `kerf hydrate` (steps 3–7 above) is used
  internally; the same local blob cache is shared.
- `kerf sync --dry-run` still shows stub files as "would fetch" entries
  with their declared byte sizes.

This means: users who work primarily through `kerf sync` never encounter
stubs. Stubs are only visible to users who cloned with plain `git clone`
without Kerf tooling. That is the exact audience `kerf hydrate` is for.

### Conflict between sync and hydrate

If a user runs `kerf hydrate` on a directory and then runs `kerf sync`, sync
treats the hydrated files as locally-present and does not re-upload them (they
match the server's declared oid). Hydration is sync-compatible.

---

## Optional: git smudge/clean filter

For users who want transparent hydration on `git checkout` — without ever
running `kerf hydrate` manually — Kerf provides an opt-in git filter.

**This is not the default.** The explicit command (`kerf hydrate`) is the
default path. The filter is opt-in for users who prefer it.

### Setup

1. Add to `.gitattributes` (committed to the repo):

   ```
   *.step  filter=kerf-lfs
   *.stp   filter=kerf-lfs
   *.iges  filter=kerf-lfs
   *.igs   filter=kerf-lfs
   *.stl   filter=kerf-lfs
   *.f3d   filter=kerf-lfs
   ```

   This tells git to run the kerf filter when smudging (checkout) and cleaning
   (staging) files matching these patterns. Adjust the glob list for your
   project's large-file types.

2. Configure the filter locally (one-time, per clone):

   ```sh
   kerf git-filter install
   ```

   This runs:

   ```sh
   git config filter.kerf-lfs.smudge  "kerf smudge-filter -- %f"
   git config filter.kerf-lfs.clean   "kerf clean-filter  -- %f"
   git config filter.kerf-lfs.required false
   ```

   `filter.kerf-lfs.required = false` means that if the `kerf` binary is not
   present (e.g. on a CI machine that only has git), git silently passes the
   stub through unchanged rather than failing the checkout.

   The filter config is **not** committed to the repo — it is local to each
   clone. `.gitattributes` (the routing rule) is committed; the filter
   implementation is local.

### Smudge filter (checkout → disk)

When git checks out a file that matches the `.gitattributes` pattern:

1. git pipes the file content to `kerf smudge-filter -- <path>`.
2. If the content is a valid LFS pointer, `kerf smudge-filter` fetches the
   blob from Tigris (same resolution flow as `kerf hydrate`, same auth via
   `KERF_API_TOKEN`) and writes real bytes to stdout.
3. If the content is already real bytes (not a pointer), `kerf smudge-filter`
   passes them through unchanged.
4. git writes the output to the working tree path.

If the fetch fails (no auth, network error), the behaviour depends on
`filter.kerf-lfs.required`:
- `false` (recommended default): git writes the stub to disk. The user can run
  `kerf hydrate` manually afterwards.
- `true`: git aborts the checkout. Use this only in environments where stubs
  on disk are unacceptable (e.g. a build server that must have real bytes).

### Clean filter (staging → git object)

When git stages a file that matches the `.gitattributes` pattern:

1. git pipes the file content to `kerf clean-filter -- <path>`.
2. If the file is a real large file (exceeds threshold or is binary), the
   filter uploads the bytes to Tigris, receives back the oid, and writes the
   three-line pointer to stdout.
3. git stores the pointer as the blob in the git object store (not the
   real bytes).
4. If the file is already a pointer, it is passed through unchanged.

This mirrors the behaviour of the push path in `kerf sync` (T-127).

### Trade-offs: filter vs explicit command

| | Explicit (`kerf hydrate`) | Smudge filter |
|---|---|---|
| Default | Yes — no setup | No — `kerf git-filter install` required |
| Works without Kerf | Partially (clone works; hydrate needed after) | Yes when `required=false` (stub on disk) |
| Transparent on checkout | No | Yes |
| Auth required at checkout time | No (clone works immediately) | Yes (stubs appear if no token) |
| CI compatibility | Simple: run once in setup | Requires KERF_API_TOKEN in CI env |
| Risk of slow checkout | None | Yes: large checkouts fetch many blobs serially via git filter |
| Repo portability | High: `.gitattributes` not required | Medium: .gitattributes committed; filter must be installed |
| Recommended for | Most users; all new clones | Power users; repos where stubs-on-disk are never acceptable |

The explicit-command path is the anti-lock-in path: a user with only `git`
installed gets all history and all pointer stubs. They need `kerf` (and an
account) only to materialise bytes, and that step is documented. The smudge
filter is a convenience that trades transparency for the requirement that Kerf
is configured at checkout time.

### Removing the filter

```sh
kerf git-filter uninstall
# or manually:
git config --unset filter.kerf-lfs.smudge
git config --unset filter.kerf-lfs.clean
git config --unset filter.kerf-lfs.required
```

Removing the filter does not convert any hydrated files back to stubs. Stubs
only appear in the working tree on the next fresh checkout of a file that is
stored as a pointer. Existing hydrated files are unaffected.

---

## API surface (server-side)

The hydration path calls one endpoint:

```
GET /api/projects/<project-id>/blobs/<oid>
Authorization: Bearer <token>
```

Response: `302 Location: <presigned-tigris-url>` (5-minute TTL) or `200`
with `Content-Type: application/octet-stream` for small blobs below the
redirect threshold.

The `<oid>` is the sha256 hex string from the pointer (`oid sha256:<hex>` →
`<hex>`). The server validates that the authenticated user has at least
`viewer` access to the project before issuing the presigned URL.

Error responses:

| HTTP | Meaning |
|---|---|
| `401` | Missing or invalid token. |
| `403` | Token valid but user lacks access to this project. |
| `404` | oid not found in the blob ledger for this project (T-134). |
| `410` | oid existed but has been GC'd (T-136). Retry note in body. |

The `410 Gone` case is surfaced to the user as:

```
error: 'parts/housing.step' — blob has been garbage-collected on the server.
This can happen if the project or workspace was deleted and recreated.
Contact your workspace admin or restore from a git commit that predates the GC.
```

---

## Non-goals

- **Running a Git LFS server**: Kerf does not implement the LFS batch API or
  the LFS transfer protocol. The pointer format is borrowed for its documented,
  universally-understood encoding; the transfer path is Kerf's own API + Tigris
  presigned URLs.
- **Automatic push of local blobs on `git push`**: the clean filter handles
  staging. `git push` on a Kerf-managed remote goes through the Kerf git
  storer, not a standard LFS server.
- **Anonymous hydration**: a Kerf account and token are always required to
  fetch real bytes. The anti-lock-in promise is "plain git gives you the full
  history and all pointer stubs"; materialising bytes requires the account that
  owns the storage.

---

## Summary of CLI commands specified

| Command | Effect |
|---|---|
| `kerf hydrate [path]` | Fetch blob bytes for all (or selected) pointer stubs in the working tree. Primary command. |
| `kerf pull-blobs [path]` | Alias for `kerf hydrate`. |
| `kerf hydrate --dry-run` | List stubs that would be fetched without fetching. |
| `kerf hydrate --force` | Re-fetch even already-hydrated files. |
| `kerf sync <project-id> <dir>` | Two-way mirror; hydrates large files implicitly (no stubs on disk after sync). |
| `kerf git-filter install` | Register git smudge/clean filter locally (opt-in). |
| `kerf git-filter uninstall` | Remove git smudge/clean filter. |
| `kerf status` / `kerf ls` | List files with `[stub]` markers for unhydrated pointers. |
