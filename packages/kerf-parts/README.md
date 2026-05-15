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
| Seed into system `Parts Library` project (idempotent, hash-incremental) | **done** |
| Gitignored attribution NOTICE | **done** |
| `kicad-packages3D` (3D bodies) | intentionally no-op at seed time (refs only); fetch wired |
| `bolts` adapter | **scaffold** — fetch wired, conversion is a documented TODO |
| `freecad-library` adapter | **scaffold** — fetch + file discovery wired; conversion reuses `kerf_imports.freecad` (TODO) |

## Tests

Fully hermetic (no network, no DB):

```bash
python -m pytest packages/kerf-parts/tests/ -q
```
