# kerf-parts

Contributor-run, **MIT-clean** pipeline that fetches pinned open-source CAD
parts repositories into a **gitignored local cache** and converts them into
Kerf's native library parts.

> **No third-party parts data is ever committed.** This package commits only
> code, the `parts-sources.toml` manifest, and `LICENSES.md`. Everything
> fetched/converted lives under `<repo_root>/.parts-cache/` which is
> gitignored. See [`LICENSES.md`](./LICENSES.md) for the licensing model.

## The licensing model in one paragraph

KiCad's official libraries are CC-BY-SA-4.0 + the KiCad Library Exception;
BOLTS is LGPL; FreeCAD-library is mixed. All of those are fine to **fetch
and use locally**, but must not be **bundled** into Kerf's MIT repo. So this
pipeline keeps the data out of git entirely: each contributor clones the
upstreams onto their own machine on demand, the conversion writes the parts
into their local database, and an attribution NOTICE is emitted into the
gitignored output (never the repo).

## What's in the manifest

`parts-sources.toml` pins each upstream to a specific tag for
reproducibility:

| name | upstream | heavy |
| --- | --- | --- |
| `kicad-symbols` | KiCad symbols (`9.0.9`) | no |
| `kicad-footprints` | KiCad footprints (`9.0.9`) | no |
| `kicad-packages3D` | KiCad 3D models (`9.0.9`) | **yes** (multi-GB, opt-in) |
| `bolts` | BOLTS (`v0.4.1`) | no — adapter scaffold |
| `freecad-library` | FreeCAD-library (`master`) | no — adapter scaffold |

## Usage

From the repo root (the workspace declares this package as a uv member):

```bash
# 1. Fetch the non-heavy sources into .parts-cache/ (idempotent)
python -m kerf_parts.fetch
#   or, if installed:  kerf-parts-fetch

# Fetch a subset
python -m kerf_parts.fetch --only kicad-symbols,kicad-footprints

# Opt in to the multi-GB 3D models
python -m kerf_parts.fetch --heavy

# Override a pin for one run (without editing the manifest)
python -m kerf_parts.fetch --ref kicad-symbols=9.0.10

# 2. Fetch + convert + seed into the system-owned "Parts Library" project
python -m kerf_parts.seed
#   or, if installed:  kerf-seed-parts

# Just convert + write the NOTICE, don't touch the DB
python -m kerf_parts.seed --dry-run

# Caches already populated? convert + seed only
python -m kerf_parts.seed --skip-fetch
```

The seed step needs a reachable Postgres (same `KERF_DATABASE_URL` /
`.env` the rest of Kerf uses). It resolves the system user
(`KERF_SYSTEM_USER_EMAIL`, default `local@kerf.local`), finds/creates its
workspace and a `Parts Library` project, and upserts each part as a
`kind='part'` file. It is **idempotent + content-hash incremental**:
re-running skips unchanged parts and updates changed ones; it never deletes.

### The `--heavy` opt-in

`kicad-packages3D` is several GB of STEP/WRL geometry. It is `heavy=true` in
the manifest and **skipped unless you pass `--heavy`** (or name it
explicitly with `--only kicad-packages3D`). The footprints adapter already
records each footprint's 3D-model *reference*; resolving those to real
geometry is an on-demand STEP import, not a seed-time bulk conversion.

## How to bump a pin

See the header comment in [`parts-sources.toml`](./parts-sources.toml).
Short version: find the new upstream tag (`git ls-remote --tags <url>`),
edit that source's `ref`, re-run fetch + seed, and commit **only** the
manifest change.

## Status — what's real vs scaffolded

| Piece | Status |
| --- | --- |
| Manifest + pinning + per-source ref override | **done** |
| Fetcher (clone/refresh/skip, `--only/--heavy/--cache-dir/--ref`) | **done** |
| KiCad symbols + footprints adapter | **done** — reuses `kerf_imports.kicad_library`, no reparsing |
| Automatic embedded per-part attribution (provenance) | **done** — see below |
| Seed into system `Parts Library` project (idempotent, hash-incremental) | **done** |
| Gitignored attribution NOTICE (regenerated from the embedded data) | **done** |
| `kicad-packages3D` (3D bodies) | intentionally no-op at seed time (refs only); fetch wired |
| `bolts` adapter | **scaffold** — fetch wired, conversion is a documented TODO |
| `freecad-library` adapter | **scaffold** — fetch + file discovery wired; conversion reuses `kerf_imports.freecad` (TODO) |

## Automatic attribution (provenance)

Every part Kerf ingests **automatically states its original author** —
derived from the cloned upstream git repo, never typed by hand. A structured
`attribution` block is embedded in **every** emitted part's `kind='part'`
JSON `metadata` (so it travels with the part into Workshop / library / BOM),
alongside a one-line human `attribution_text`. The single reusable extractor
is [`provenance.py`](./src/kerf_parts/provenance.py); every adapter (real and
scaffold) goes through it — no adapter parses `git log` itself and no part
can be emitted without provenance.

`attribution` fields:

| field | source |
| --- | --- |
| `source_project` / `manifest_url` / `upstream_ref` / `license` / `license_url` | the `parts-sources.toml` manifest |
| `source_url` | the clone's `git remote get-url origin` (reconciled with the manifest) |
| `upstream_commit` | the clone's real `git rev-parse HEAD` (falls back to the pinned ref) |
| `source_file` | the exact upstream file the part derives from, relative to the clone |
| `original_author` / `original_author_date` | the file's **creating** commit (`git log --diff-filter=A --follow -- <file>`) |
| `contributors` | every distinct `%an <%ae>` that touched that file, deduped |
| `last_author` / `last_author_date` | the most recent commit for that file |
| `author_source` | which rung of the fallback chain produced the author |
| `history_truncated` | true if a shallow clone couldn't be deepened |
| `in_file_metadata` | extra signal only (e.g. KiCad `(generator ...)`) — never the sole author |
| `retrieved_at` | UTC ISO-8601 timestamp of this run |

**Fallback chain** (a blank author is a bug): per-file git author →
repo `AUTHORS`/`CONTRIBUTORS`/`LICENSE` copyright holder → manifest
`source_project` + `license` with `original_author: "unknown — see source
repository"`.

**Shallow-clone caveat:** the fetcher clones `--depth 1`, which would
truncate per-file history and wrongly blame the pinned-ref committer as the
"original author". Before scoping `git log` to a file, the provenance helper
runs `git fetch --unshallow` (falling back to repeated `--deepen`). If the
repo genuinely can't be deepened (offline), the per-file result is flagged
`history_truncated` and the chain falls back to repo/manifest authorship
rather than emitting a misleading author.

## Tests

Fully hermetic (no network, no DB):

```bash
python -m pytest packages/kerf-parts/tests/ -q
```
