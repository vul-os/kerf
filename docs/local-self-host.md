<!-- no-broker-dep:allow-file: names Ephor once, as the optional reachability broker a user may
     arrange for themselves — no dependency edge. This page is also republished verbatim into
     public/docs-manifest.json by scripts/build-docs-manifest.mjs; the marker is placed on this
     source file, not hand-added to the generated JSON, so regeneration carries it forward. -->

# Local / self-host install

Kerf can run entirely on your own machine. This page covers what you get, what you need, and how to configure it.

---

## What you get

Kerf is 100% MIT and there is only one node type — there is no separate
"Kerf Cloud" product to compare against, and no feature is gated behind a
paid tier or a cloud-only build:

- Every CAD tool: JSCAD, OCCT B-rep, sketcher, assemblies, drawings, GD&T
- Electronics / PCB design
- FEM, CAM, 3D-print slicing, topology optimisation
- All LLM agent tools (~150 tools across 19 plugins)
- [File revision history and undo](./file-revisions.md)
- Parts library capability (you fetch the data yourself — see [Parts library](#parts-library) below)
- The distributed Workshop — publish, follow, pin over DMTAP-PUB (see [distributed-workshop.md](./distributed-workshop.md)); no account needed
- Git — every project is a plain local git repo; add GitHub/GitLab/Gitea/any remote yourself (see [github-sync.md](./github-sync.md))

There is no billing anywhere in kerf, no usage metering sold by kerf, and
no transactional email tied to an account system (there are no kerf
accounts beyond what a shared multi-user box defines locally). Kerf itself
never bills for anything. The only optional external services you might
arrange yourself are reachability through the **Ephor** broker (rented
uptime for an always-on node) and backup storage buckets — neither is sold
by kerf, and neither is required.

---

## Requirements

- **Python 3.11+**
- **Nothing else to install for the database** — Kerf opens an embedded
  SQLite file at `~/.kerf/kerf.db` the first time it runs, with no setup
  step. Postgres 14+ is an optional scale backend for a team / always-on
  install; see [local-install.md](./local-install.md#database-embedded-sqlite-by-default-postgres-optional).
- **Node 22+** (only needed if you build the frontend from source — it lives
  in `web/`, not the repo root)

---

## Install

Kerf is not published on PyPI (only the separate `kerf-sdk` scripting client
is). The supported paths are the install script, Docker, or from source — see
[local-install.md](./local-install.md#how-kerf-is-actually-distributed) for
the full breakdown. From source:

```sh
git clone https://github.com/vul-os/kerf
cd kerf
./scripts/dev-install.sh mech   # or another persona — plain `pip install -e .[mech]` does not work, see local-install.md
cd web && npm install && npm run build  # build the frontend
```

Persona options: `api-only`, `mech`, `electronics`, `bim`, `full`, `compute-only`.

---

## Configuration

Copy the example config and edit it:

```sh
cp kerf.example.toml kerf.toml
```

Minimum config for a local single-user install — this is already the
default in `kerf.example.toml`, so for SQLite you don't need to add
anything; shown here for clarity, and with Postgres opted into explicitly:

```toml
[server]
local_mode = true            # skip all auth — single-user; the default

[auth]
jwt_secret = "change-me-random-string"

[database]
# Omit this entirely for the embedded SQLite default. Set it only to opt
# into Postgres as a scale backend:
url = "postgres://your_pg_user@localhost:5432/kerf?sslmode=disable"

[storage]
backend = "filesystem"
filesystem_root = "~/kerf-projects"
```

(`[server].port` exists in `kerf.example.toml` but nothing in `kerf_core`
reads it for the actual bind address — the socket `kerf-server` listens on
is always set via the `--host`/`--port` CLI flags or `KERF_HOST`/`KERF_PORT`
env vars; see [getting-started.md#cli-flags](./getting-started.md#cli-flags).)

With `local_mode = true`:
- All requests resolve to the node's single owner.
- The marketing landing is skipped: opening the app takes you to your projects.

Authentication is *not* bypassed, in either mode. It used to be — local mode
handed out a session to anything that could reach the port — and that is what
the password set on first load replaced. See
[api-reference.md#authentication](./api-reference.md#authentication).

---

## The `filesystem` storage backend

Turn it on in `kerf.toml`:

```toml
[storage]
backend = "filesystem"
filesystem_root = "~/kerf-projects"   # the default
```

Every object the server stores then lands under `filesystem_root` as a tree
you can `cd` into — one directory per project, files under the names they
were uploaded with, so your JSCAD / STEP files are real files you can open,
grep, and `git init` on from outside the app:

```
~/kerf-projects/
  projects/<project-id>/
    assets/bracket-3f2a91c40b7e.step   # your upload; the short suffix keeps
    assets/bracket-8b44c1de2f90.step   # two "bracket.step" uploads apart
    renders/front.png
    thumbnail.jpg
  .kerf/objects/…                      # content-addressed blobs — hex names,
  .kerf/uploads/…                      # nothing to read; in-flight chunks
```

Project directories are named by project id, not by title: a title can change
or collide, the id is what the rest of the system uses.

What it is **not**:

- **Not a sync engine.** The tree is written, never read back for changes.
  Edit `bracket-3f2a91c40b7e.step` with your own tools and the app keeps
  serving whatever is on disk — but the app never notices the edit, and it
  produces no revision. Renaming or moving files there hides them from the
  app entirely.
- **Not the index.** The database still holds projects, files, revision
  history and who owns what; this tree holds bytes. Copying it to another
  machine without the database gives you files, not an install.
- **Not `"local"` with a nicer name.** `backend = "local"` writes the same
  objects flat under `local_path` named by their raw storage key. Switching
  backends does not migrate existing objects — point a fresh install at
  `filesystem`, or move the bytes yourself.

---

## Database setup

**SQLite (default) — nothing to do.** Leaving `[database].url` unset (or
omitting `DATABASE_URL`) is enough; the file and schema are created on first
run.

**Postgres (opt-in scale backend):**

```sh
createdb kerf                                            # create the database once
python -m kerf_core.db.migrations.runner "$DATABASE_URL"  # apply all migrations
```

`kerf-server` has no `--migrate` flag — this migration runner (also wrapped
by `npm run migrate` when you have the frontend checked out; see
[getting-started.md](./getting-started.md#5-run-database-migrations)) is the
actual command, and it is idempotent — safe to re-run after every upgrade,
against either backend.

---

## Starting the server

```sh
kerf-server --config ./kerf.toml
```

Or with env vars:

```sh
DATABASE_URL="postgres://..." kerf-server --host 0.0.0.0 --port 8080
```

The bind address comes from `--host`/`--port` (or `KERF_HOST`/`KERF_PORT`),
defaulting to `0.0.0.0:8080` — not from `kerf.toml` (see the config note
above). To also serve the built frontend from the same port, set
`KERF_FRONTEND_DIST` to the built `web/dist/` directory first (its built-in
default, `/app/dist`, is the path used inside the Docker image, not a source
checkout):

```sh
KERF_FRONTEND_DIST=web/dist kerf-server
```

Open `http://localhost:8080` in your browser.

---

## LLM provider keys

There is no Kerf billing layer anywhere — every install uses provider API keys directly.

Set keys in `kerf.toml`:

```toml
[llm.anthropic]
api_key = "sk-ant-..."

[llm.openai]
api_key = "sk-..."
```

Or leave them blank in `kerf.toml` and set `ANTHROPIC_API_KEY` /
`OPENAI_API_KEY` / `MOONSHOT_API_KEY` / `GEMINI_API_KEY` as environment
variables instead.

Independently of the operator's configured key above, a signed-in user can
save their own provider key via `POST /api/provider-keys`; when present, the
server uses that user's key instead of the operator's for their requests
(`_prefer_byo_provider` in `kerf_api/routes.py`) — a convenience preference,
not a credit or billing bucket (Kerf has none).

---

## Parts library

The parts library works self-hosted. You populate it yourself.

### Standard mechanical parts (MIT, no external data)

```sh
pip install -e packages/kerf-partsgen
kerf-partsgen enumerate    # deterministic, zero-token build into ./.parts-out/
kerf-partsgen seed         # promote [x]-approved families into the Parts Library project
```

### Third-party libraries (KiCad, BOLTS, FreeCAD-library)

```sh
pip install -e "packages/kerf-parts[seed]"
kerf-parts-fetch            # fetch from upstream into ./.parts-cache/ (gitignored)
kerf-parts-fetch --heavy    # also pull kicad-packages3D (multi-GB, opt-in)
kerf-seed-parts             # convert + upsert
```

Consult each upstream project's own licence for the attribution requirements that travel with its data.

---

## Persona bundles

A persona is a named set of plugin packages. Select one at install time:

| Persona | Plugins included |
|---|---|
| `api-only` | Core API + auth |
| `mech` | CAD, imports, mates, tess, parts, render, workers |
| `electronics` | Everything in mech + electronics, PCB, wiring, EDA |
| `bim` | Everything in mech + BIM, structural |
| `full` | Everything in the other personas |
| `compute-only` | Heavy compute plugins only (FEM, CAM, topo, render) — for a sidecar deploy |

---

## Maintenance commands

```sh
python -m kerf_core.db.migrations.runner "$DATABASE_URL"   # run pending migrations
```

`kerf-server` itself takes no maintenance subcommands — see
[getting-started.md#5-run-database-migrations](./getting-started.md#5-run-database-migrations)
for the migration command, and
[file-revisions.md#maintenance-self-hosted-operators](./file-revisions.md#maintenance-self-hosted-operators)
for how revision-chain compaction works (automatic, server-mode only —
nothing to run by hand).

---

## Hero Render — GPU Cycles worker (T-106e)

The Hero Render pipeline (viewport "Hero Render…" button) dispatches high-sample Blender Cycles render jobs to a dedicated worker. There is no billed hosted option — point it at a worker on your own GPU machine, in one of two ways:

### Option A — Self-hosted Docker worker (own GPU box)

Build and run the containerised cycles worker against your local kerf-server:

```sh
# GPU build (CUDA; requires nvidia-container-toolkit)
docker build \
  -f packages/kerf-render/Dockerfile.cycles-worker \
  --build-arg GPU=true \
  -t kerf/cycles-worker:gpu .

# CPU-only build (falls back to CPU rendering in Blender)
docker build \
  -f packages/kerf-render/Dockerfile.cycles-worker \
  --build-arg GPU=false \
  -t kerf/cycles-worker:cpu .

# Run against a local kerf-server
docker run --gpus all \
  -e KERF_API_URL=http://host.docker.internal:8080 \
  -e KERF_API_TOKEN=<your-api-token> \
  kerf/cycles-worker:gpu
```

The container bundles Blender 4.1. For a CPU-only host, drop `--gpus all` and use the `:cpu` image.

### Option B — BYO Blender (point to an existing install)

If you already have Blender installed, set `KERF_BLENDER_PATH` and skip the Docker image entirely:

```sh
# macOS example
export KERF_BLENDER_PATH="/Applications/Blender.app/Contents/MacOS/Blender"

# Linux example
export KERF_BLENDER_PATH="/opt/blender-4.1.1/blender"

# Launch the worker directly (no Docker)
python -m kerf_render.cycles_worker
```

`KERF_BLENDER_PATH` overrides the bundled `/opt/blender/blender` in both the Docker entrypoint and the bare Python worker. Leave it unset to use `blender` on `PATH`.

### Browser fallback (free preview / offline)

When the worker is unreachable (server returns 503 or the request fails), the viewport automatically falls back to an in-browser path-traced preview using `three-gpu-pathtracer`. This delivers caustics, dispersion, and SSS directly on the user's GPU via WebGL2 — no server required. The fallback banner reads "Rendering in browser (free preview)".

### Worker environment variables

| Variable | Default | Description |
|---|---|---|
| `KERF_BLENDER_PATH` | (empty — use `blender` on PATH or bundled) | Path to a user-supplied Blender binary |
| `KERF_API_URL` | (empty — standalone / test mode) | Base URL of the Kerf API this worker reports to |
| `KERF_API_TOKEN` | (empty) | Auth token for the Kerf API |
| `KERF_WORKER_CONCURRENCY` | `1` | Parallel render jobs; GPU boxes typically use 1 |

---

## GitHub / GitLab / Gitea remotes

There is no kerf-operated OAuth app and no server-held token for any git
host. A Kerf project is a plain local git repo; GitHub, GitLab, Gitea, or
any other remote is added and authenticated the same way you'd do it from
the `git` CLI — your own SSH key or Personal Access Token, configured
through the Git panel. See [github-sync.md](./github-sync.md) for the
practical walkthrough. Kerf's internal git history is always present
regardless of whether any remote is configured.

---

## Related pages

- [file-revisions.md](./file-revisions.md) — revision history maintenance
- [github-sync.md](./github-sync.md) — GitHub/GitLab/Gitea as ordinary git remotes
- [distributed-workshop.md](./distributed-workshop.md) — publish, follow, pin over DMTAP-PUB
- [node-architecture.md](./node-architecture.md) — one node type; behaviour governed by config, not build
- [architecture.md](./architecture.md) — full stack overview and plugin system
