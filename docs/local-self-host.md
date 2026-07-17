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
- Parts library capability (you fetch the data yourself — see [oss-cloud-separation.md §4](./oss-cloud-separation.md))
- The distributed Workshop — publish, follow, pin over DMTAP-PUB (see [distributed-workshop.md](./distributed-workshop.md)); no account needed
- Git — every project is a plain local git repo; add GitHub/GitLab/Gitea/any remote yourself (see [github-sync.md](./github-sync.md))

There is no billing anywhere in kerf, no usage metering sold by kerf, and
no transactional email tied to an account system (there are no kerf
accounts beyond what a shared multi-user box defines locally). The only
things anyone pays for, in this whole stack, are Vulos-standard Relay
(rented uptime) and backup buckets (durable storage) — optional, sold at
the Vulos layer, not by kerf.

---

## Requirements

- **Python 3.11+** (in a virtualenv)
- **Postgres 14+** — Kerf uses Postgres even locally. No SQLite path exists.
- **Node 20+** (only needed if you build the frontend from source)

---

## Install

### From PyPI (recommended)

```sh
pip install kerf[mech]          # mechanical CAD stack
# or
pip install kerf[electronics]   # EDA stack
# or
pip install kerf[full]          # everything
```

Persona options: `api-only`, `mech`, `electronics`, `bim`, `full`, `compute-only`.

### From source

```sh
git clone https://github.com/kerf-design/kerf
cd kerf
pip install -e .[mech]       # or another persona
npm install && npm run build  # build the frontend
```

---

## Configuration

Copy the example config and edit it:

```sh
cp kerf.example.toml kerf.toml
```

Minimum config for a local single-user install:

```toml
[server]
host = "127.0.0.1"
port = 8080

[database]
url = "postgres://your_pg_user@localhost:5432/kerf?sslmode=disable"

[auth]
local_mode = true            # skip all auth — single-user
jwt_secret = "change-me-random-string"

[storage]
backend = "filesystem"
filesystem_root = "~/kerf-projects"
```

With `local_mode = true`:
- All authentication is bypassed. The login UI is hidden.
- `POST /auth/bootstrap-local` issues a session for the configured local user.
- All requests resolve to that user.
- The `filesystem` storage backend writes each project as a directory under `filesystem_root`, so your JSCAD / STEP files are real files you can open, grep, and git from outside the app.

---

## Database setup

```sh
createdb kerf                # create the database
kerf-server --migrate        # apply all migrations
```

---

## Starting the server

```sh
kerf-server --config ./kerf.toml
```

Or with env vars:

```sh
KERF_DATABASE_URL="postgres://..." kerf-server
```

The server binds to `host:port` as configured. The frontend SPA is served from the same port. Open `http://localhost:8080` in your browser.

---

## LLM provider keys

There is no Kerf billing layer anywhere — every install uses provider API keys directly.

Set keys in `kerf.toml`:

```toml
[llm]
anthropic_api_key = "sk-ant-..."
openai_api_key    = "sk-..."
```

Or via environment variables:

```toml
[llm]
# leave blank — the server reads ANTHROPIC_API_KEY, OPENAI_API_KEY from env
```

With `local_mode = true` and `AUTH_OPTIONAL = true`, you can also let users paste their own keys through the settings panel (`prefer_byo` in the BYO model) — there is no billing behind this, it's simply which key is used for the request.

---

## Parts library

The parts library works self-hosted. You populate it yourself.

### Standard mechanical parts (MIT, no external data)

```sh
pip install -e packages/kerf-partsgen
python -m kerf_partsgen.cli enumerate    # generate geometry into ./.parts-out/
python -m kerf_partsgen.cli seed         # upsert into the Parts Library project
```

### Third-party libraries (KiCad, BOLTS, FreeCAD-library)

```sh
pip install -e "packages/kerf-parts[seed]"
kerf-parts-fetch            # fetch from upstream into ./.parts-cache/ (gitignored)
kerf-parts-fetch --heavy    # also pull kicad-packages3D (multi-GB, opt-in)
kerf-seed-parts             # convert + upsert
```

See [oss-cloud-separation.md §4](./oss-cloud-separation.md) for the attribution requirements.

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
kerf-server --migrate                   # run pending migrations
kerf-server revisions repack            # backfill gzip storage for file revisions
kerf-server revisions repack --dry-run  # preview without writing
kerf-server library-import --manifest samples/libraries/adafruit-sensors.yaml
```

---

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
- [oss-cloud-separation.md](./oss-cloud-separation.md) — canonical OSS/cloud model (historical)
- [architecture.md](./architecture.md) — full stack overview and plugin system
