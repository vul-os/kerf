# Local install

How to self-host Kerf on your own machine or a private server. Kerf is fully
open-source (MIT); no account, sign-up, or network access is required — the
config toggles that make a node single-user vs. multi-user are covered under
[Single-user vs multi-user](#single-user-vs-multi-user) below.

## How Kerf is actually distributed

Kerf is **not** on PyPI (only the standalone [`kerf-sdk`](./sdk.md) client
package is — that's for scripting against a running Kerf server, not for
installing Kerf itself). `pip install kerf` will not find anything. There are
three real install paths:

### 1. The install script (recommended for most people)

```sh
curl -fsSL https://vulos.org/projects/kerf/install.sh | sh
```

Downloads the latest tagged release tarball from GitHub Releases, verifies
its checksum, unpacks it under `~/.local/share/kerf/<version>/`, and runs the
bundled `setup.sh`: creates a Python venv, editable-installs the bundled
`packages/kerf-*` plugins, and writes a starter `kerf.toml`. No Docker, no
`git clone`, no PyPI. Requires `bash`, `curl`, `tar`, and Python 3.11+.
`KERF_VERSION=vX.Y.Z sh` pins a specific release instead of the latest.

Release tarballs today ship the **`full`** persona only (every plugin) — a
persona-scoped tarball is a TODO; see [persona-bundles.md](./persona-bundles.md#quick-reference)
for how to get a smaller install today (from source or Docker).

### 2. Docker

```sh
git clone https://github.com/vul-os/kerf
cd kerf
docker compose up
```

Builds the `full` persona image and starts Kerf alongside its own Postgres
and Redis containers (see [deployment.md](./deployment.md) for the image
matrix and `--build-arg KERF_PERSONA=...` to build a smaller persona).

### 3. From source (for development, or an unsupported platform)

```sh
git clone https://github.com/vul-os/kerf
cd kerf

# installs the persona's workspace packages editable, with plain pip:
./scripts/dev-install.sh mech    # choose your persona

cd web && npm install
```

> A bare `pip install -e .[mech]` does **not** work: the repo is a `uv`
> workspace and `[tool.uv.sources]` (which maps `kerf-*` to `packages/*`) is
> only understood by `uv`. Plain pip tries PyPI and fails. `scripts/dev-install.sh`
> works around that by installing every persona package editable in one `pip
> install` call.
>
> **`uv sync` does not currently work, for any persona.** `kerf-cad-core`,
> `kerf-cam`, `kerf-fem`, and `kerf-topo` each declare a conda-forge-only extra
> (pythonOCC, FEniCSx/dolfinx — see below), and uv resolves a single lockfile
> for the entire workspace, so it always tries to satisfy those extras no
> matter which `--extra` you request. `uv sync --extra mech`, `--extra full`,
> `--extra api-only`, and even a bare `uv sync` all fail with "No solution
> found ... requirements are unsatisfiable." Use `./scripts/dev-install.sh`
> until that's untangled.

See [getting-started.md](./getting-started.md) for the full from-source walkthrough,
and [solver dependencies](#solver-dependencies-dolfinx--pythonocc) below for the
conda-only compute stack.

## Persona bundles

Pick the persona that covers your domain. Smaller personas install faster and
have lighter runtime footprints.

| Persona | Use when | Heavy deps added |
|---------|----------|-----------------|
| `api-only` | You need just the REST + RPC surface (e.g. a headless API pod) | none |
| `mech` | Mechanical CAD, FEM, CAM, topology optimisation | pythonOCC, FEniCSx, OpenCAMlib |
| `electronics` | PCB, schematics, SPICE, RF | ngspice, scikit-rf |
| `bim` | Building modelling, IFC export | IfcOpenShell |
| `full` | Every domain plugin on top of the personas above | everything |
| `compute-only` | Heavy workers behind an internal load balancer; no auth or REST | all compute deps |

Distributor sync and the production-ops extras (job traveler, share links,
PLM: 150% BOM / ECO / SysML trace / where-used) live in `kerf-api` itself,
so they ship with every persona above, not just `full` — there is no
separate "cloud" plugin gating them and no hosted service behind them.

Full breakdown: [persona-bundles.md](./persona-bundles.md).

## Solver dependencies (dolfinx + pythonOCC)

The `mech`, `full`, and `compute-only` personas list heavy compute extras —
pythonOCC (B-rep CAD, `kerf-cad-core[occ]`) and FEniCSx/dolfinx (FEM,
`kerf-fem[fenicsx]`). **These are distributed through conda-forge only — they are
not on PyPI for any Python version**, so `pip install` cannot provide them. The
server still boots without them; the CAD and FEM plugins detect the missing
solver and register a reduced capability set.

To get the solvers, install them into a conda environment and install the Kerf
packages into that same environment:

```sh
# 1. A conda env with the solver stack (conda-forge builds target Python 3.12):
conda create -n kerf -c conda-forge \
  python=3.12 fenics-dolfinx pythonocc-core python-gmsh meshio slepc4py scipy pygit2
conda activate kerf

# 2. The Kerf workspace packages, editable, into that env:
PIP="$(command -v pip)" ./scripts/dev-install.sh mech
```

Notes:

- conda-forge splits gmsh: the Python binding is `python-gmsh`, separate from the
  `gmsh` app package.
- `scipy` is needed by several `kerf-cad-core` geometry tools.
- `pygit2` is only required if you use the S3-backed git storer (per-project
  bare repos on top of S3-compatible storage); it is harmless to include and
  keeps `[full]` happy.

## Database: embedded SQLite by default, Postgres optional

Kerf needs **no database setup for a local install** — with `DATABASE_URL`
unset it opens an embedded SQLite file at `~/.kerf/kerf.db` (WAL mode,
auto-created) the first time it runs. Postgres 14+ is an opt-in **scale
backend** for a team / always-on / multi-node deployment — see
[getting-started.md#scale-mode-postgres](./getting-started.md#scale-mode-postgres)
for what it adds. To switch, set `DATABASE_URL` before running migrations:

```sh
# macOS (Homebrew)
brew install postgresql@16
brew services start postgresql@16
createdb kerf

# Ubuntu / Debian
sudo apt install postgresql
sudo -u postgres createdb kerf
sudo -u postgres psql -c "CREATE USER myuser WITH PASSWORD 'mypass';"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE kerf TO myuser;"
```

Set the database URL in `kerf.toml`:

```toml
[database]
url = "postgres://myuser:mypass@localhost:5432/kerf?sslmode=disable"
```

Or via environment variable:

```sh
export DATABASE_URL=postgres://myuser:mypass@localhost:5432/kerf?sslmode=disable
```

## First-run setup

From a source checkout (see [getting-started.md](./getting-started.md) for
the full walkthrough):

```sh
cp kerf.example.toml kerf.toml   # from the repo root
cd web
npm run migrate    # applies migrations against $DATABASE_URL, or SQLite if unset
npm run dev         # serves the editor at http://localhost:5173
```

From an `install.sh` or Docker install, migrations run via
`python -m kerf_core.db.migrations.runner` (`install.sh`'s bundled `setup.sh`
prints the exact venv path to use) — `kerf-server` itself has no `--migrate`
flag. See [deployment.md](./deployment.md#migrations-on-boot).

On first load with `local_mode = true` (the default), the server auto-creates
a system user and signs you in without a login screen.

## Single-user vs multi-user

| Setting | Behaviour |
|---------|-----------|
| `[server].local_mode = true` (default) | No login screen. A singleton user is bootstrapped automatically. Ideal for a personal workstation install. |
| `[server].local_mode = false` | Login required. Local users are provisioned on the box for a shared team install. No central account system or public sign-up is involved. |

A shared multi-user node (a team box, or any install you run for more than
just yourself) sets `[server].local_mode = false` explicitly — there is no
separate proprietary package or license gate involved. Kerf is 100% MIT and
every install runs the same software; the config toggle is the only thing
that changes. (`vulos.org/projects/kerf` is the project's marketing site and
docs — not a running, multi-tenant Kerf instance; there is no hosted tier.)

## Config layering

Kerf reads configuration from the first file found, in priority order:

1. `--config <path>` CLI flag
2. `KERF_CONFIG` environment variable
3. `./kerf.toml` (current working directory)
4. `~/.config/kerf/config.toml`
5. `/etc/kerf/config.toml`

A starter `kerf.toml` is copied from `kerf.example.toml` for you by the
`install.sh` / Docker `setup.sh` path; on a source checkout, copy it yourself
(`cp kerf.example.toml kerf.toml` — see
[getting-started.md](./getting-started.md#4-initialise-configuration) for why
`npm run init` doesn't do this on its own today). Full schema:
`kerf.example.toml` in the repo root, or [configuration.md](./configuration.md).

## Environment variables

Any `kerf.toml` key can be overridden with an environment variable. The
mapping follows the TOML path with underscores and a `KERF_` prefix:

| Env var | Equivalent TOML key |
|---------|---------------------|
| `KERF_CONFIG` | path to config file (meta) |
| `KERF_HOST` | `[server].host` |
| `KERF_PORT` | `[server].port` |
| `DATABASE_URL` | `[database].url` |
| `LOCAL_MODE` | `[server].local_mode` (no `KERF_` prefix) |
| `ANTHROPIC_API_KEY` | `[llm.anthropic].api_key` |
| `OPENAI_API_KEY` | `[llm.openai].api_key` |

## Storage backends

Three backends are available:

| Backend | Config key | Notes |
|---------|------------|-------|
| `local` | `[storage].backend = "local"` | Opaque blob store under `[storage].local_path`. Default for dev. |
| `s3` | `[storage].backend = "s3"` | AWS S3, Cloudflare R2, or MinIO. Configure `[storage.s3]`. |
| `filesystem` | `[storage].backend = "filesystem"` | Projects mirror to disk under `[storage].filesystem_root`. Each project is a real folder — edit files with your own tools. |

The `git` backend sits above S3 and adds a per-project bare repo. It is an
ordinary MIT node capability, not a cloud-only feature — a node MAY serve
its own repos over standard git HTTP/SSH if you configure it to.

## Upgrading

Migrations are safe to re-run — always run them after upgrading.

**Install-script install:** re-run the one-liner; it re-downloads the latest
release and re-runs `setup.sh` (reuses the existing venv, updates packages,
leaves an existing `kerf.toml` alone):

```sh
curl -fsSL https://vulos.org/projects/kerf/install.sh | sh
```

**From source:**

```sh
git pull
./scripts/dev-install.sh mech    # uv sync doesn't currently work, see above
cd web && npm run migrate
```

## Uninstall

**Install-script install** — everything lives under one version directory:

```sh
rm -rf ~/.local/share/kerf/<version>   # or ~/.local/share/kerf/current (symlink)
dropdb kerf                             # only if you switched to Postgres
```

**From-source / editable install:**

```sh
pip uninstall kerf-core kerf-api kerf-chat kerf-auth  # + any other kerf-* you installed
dropdb kerf                                             # only if you switched to Postgres
rm -rf ~/.config/kerf                                   # config + auth state, if used
rm -rf ./.kerf-storage                                  # local blob store, if used
rm -f kerf.toml                                          # repo-root config
```

## Project git CLI

Every Kerf project is a cloneable git repository. The `kerf` CLI exposes
folder-level sync and large-file management:

```sh
kerf sync      # two-way folder ↔ project sync
kerf export    # snapshot export to a local directory
kerf import    # import a local directory into a new or existing project
kerf hydrate   # resolve large-file pointers and download binary assets
```

GitHub and GitLab mirror connections are configured per-project in Settings →
Git. See [github-sync.md](./github-sync.md) for the full mirror setup.

## See also

- [getting-started.md](./getting-started.md) — step-by-step first run
- [configuration.md](./configuration.md) — full config schema
- [persona-bundles.md](./persona-bundles.md) — which plugins each persona includes
- [deployment.md](./deployment.md) — Docker + production deploy
- [github-sync.md](./github-sync.md) — git mirror + CLI sync commands
