# Getting started

From a fresh clone to a running Kerf server in about five minutes.

## Prerequisites

| Tool | Minimum version |
|------|-----------------|
| Python | 3.11 |
| Node.js | 22 |
| npm | 10 (ships with Node 22) |

> **No database to install.** kerf uses an embedded **SQLite** database by
> default (`~/.kerf/kerf.db`, created automatically) — there is nothing to set
> up for a local install. Postgres is an optional **scale backend** for teams
> and always-on nodes; see [Scale mode: Postgres](#scale-mode-postgres) below.

## 1. Clone the repo

```sh
git clone https://github.com/vul-os/kerf
cd kerf
```

## 2. Install Python dependencies

Choose the smallest persona that covers your work. `mech` is a good default for
mechanical CAD; use `full` if you want everything.

The repo is a [`uv`](https://docs.astral.sh/uv/) workspace, so the install path
depends on your tooling:

```sh
# uv users — resolves the workspace automatically:
uv sync --extra mech        # or --extra full

# pip users — installs every workspace package a persona needs, editable:
./scripts/dev-install.sh mech      # or: full | electronics | bim | api-only
```

> **Heads up:** a bare `pip install -e .[mech]` does **not** work. `[tool.uv.sources]`
> maps the `kerf-*` requirements to the local `packages/*` dirs, but only `uv`
> understands that mapping — plain pip tries to fetch `kerf-core` etc. from PyPI
> (where they are unpublished) and fails. Use `uv sync` or `./scripts/dev-install.sh`.

> **Solvers:** the `mech`/`full` compute extras — pythonOCC and FEniCSx/dolfinx —
> are conda-forge-only and are not installed by either command above. See
> [local-install.md](./local-install.md#solver-dependencies-dolfinx--pythonocc)
> for the conda setup. The server boots without them; solver-backed tools just
> report themselves unavailable.

See [persona-bundles.md](./persona-bundles.md) for the full menu and what each persona installs.

## 3. Install Node dependencies

```sh
npm install
```

## 4. Initialise configuration

```sh
npm run init    # writes kerf.toml from kerf.example.toml (skip if it already exists)
```

Open `kerf.toml` and set at least one LLM API key:

```toml
[llm.anthropic]
api_key = "sk-ant-..."   # or [llm.openai], [llm.moonshot], [llm.gemini]
```

The config defaults (`local_mode = true`, `storage.backend = "local"`, embedded
SQLite database) are correct for a local dev run — you do not need to change
anything else.

## 5. Run database migrations

```sh
kerf-server --migrate
# or equivalently:
npm run migrate
```

With no `DATABASE_URL` set this creates `~/.kerf/kerf.db` and applies the SQLite
migration set (`packages/kerf-core/src/kerf_core/db/migrations_sqlite/`). If
you have pointed kerf at Postgres (see [Scale mode](#scale-mode-postgres)), it
applies the Postgres set (`.../migrations/`) instead. Either way the command is
idempotent — safe to re-run.

## 6. Start the server

**Development mode** (Vite dev server on `:5173` + kerf-server on `:8080`,
both with hot-reload):

```sh
npm run dev
```

Open <http://localhost:5173>.

**Production / single-binary mode** (serves the pre-built SPA from `:8080`):

```sh
npm run build      # compile the Vite SPA into dist/
kerf-server        # serves dist/ + API on http://localhost:8080
```

On first load `local_mode = true` auto-creates a singleton user and signs you
in without a login screen.

## Verifying the server is healthy

```sh
curl http://localhost:8080/healthz
# → {"status":"ok"}

curl http://localhost:8080/health/capabilities
# → {"plugins":[...], "capabilities":["api.rest","cad.brep-mesh",...]}
```

The capabilities endpoint shows every loaded plugin and its provided tags.

## Configuration quick reference

The full schema is in `kerf.example.toml`. The most useful knobs for local dev:

| Setting | Default | Notes |
|---------|---------|-------|
| `[server].local_mode` | `true` | Auto-login; no register/login screen |
| `[server].port` | `8080` | HTTP port |
| `[database].url` | _(unset → embedded `~/.kerf/kerf.db`)_ | Set to `postgres://…` for scale mode; override via `DATABASE_URL` env var |
| `[llm.anthropic].api_key` | _(empty)_ | Set this to activate the default model |
| `[storage].backend` | `"local"` | `"local"` / `"s3"` / `"filesystem"` |
| `[limits].file_revisions_max` | `200` | Per-file undo history cap |

Config is read from the first file found in this order:
`--config` flag → `KERF_CONFIG` env → `./kerf.toml` → `~/.config/kerf/config.toml` → `/etc/kerf/config.toml`.

## CLI flags

```
kerf-server [--config PATH] [--host HOST] [--port PORT] [--reload] [--workers N]
```

| Flag | Default | Env override |
|------|---------|-------------|
| `--config` | `""` (uses search order above) | `KERF_CONFIG` |
| `--host` | `0.0.0.0` | `KERF_HOST` |
| `--port` | `8080` | `KERF_PORT` |
| `--reload` | off | — |
| `--workers` | `1` | — |

## Scale mode: Postgres

The embedded SQLite default is ideal for a local, single-user install. Switch to
Postgres when you need a **team / always-on / multi-node** deployment — it adds
multi-worker job-queue fan-out (`FOR UPDATE SKIP LOCKED`), `LISTEN/NOTIFY`
instant worker wakeups, and horizontal scale.

It is a one-line change — set `DATABASE_URL` (or `[database].url`) to a
`postgres://` DSN before running migrations:

```sh
# Postgres must be running; create the database once:
createdb kerf
export DATABASE_URL=postgres://postgres:postgres@localhost:5432/kerf?sslmode=disable
# (if your local role differs, e.g. `pc`: postgres://pc@localhost:5432/kerf?sslmode=disable)

kerf-server --migrate   # applies the Postgres migration set
kerf-server             # now serving on Postgres
```

Everything else — the API, the frontend, every plugin — is identical across the
two backends; only the `DATABASE_URL` scheme differs. On SQLite the Postgres-only
capabilities degrade gracefully (job queues run single-writer, `LISTEN/NOTIFY`
wakeups fall back to polling); kerf logs a one-line notice naming them at
startup. See [architecture/database.md](./architecture/database.md) for the full
design.

## Next steps

- Persona bundles explained — [persona-bundles.md](./persona-bundles.md)
- Local self-hosting in depth — [local-install.md](./local-install.md)
- Config file schema — [configuration.md](./configuration.md)
- Docker / production deployment — [deployment.md](./deployment.md)
- Writing a plugin — [plugins-development.md](./plugins-development.md)
- Scripting with the Python SDK — [sdk.md](./sdk.md)
