# Contributing

How to set up Kerf locally, run dev, and land changes. Kerf is 100% MIT —
there is no proprietary/cloud plugin split (see the "Final form" ADR in
`decisions.md`, 2026-07-17).

## Quickstart

```sh
git clone https://github.com/vul-os/kerf
cd kerf

# Postgres on the default port
createdb kerf

# Pick a persona — see docs/capabilities.md
pip install -e .[full]

npm install
npm run init               # writes kerf.toml from the example
# Edit kerf.toml: set [auth].optional = true and one [llm.<provider>].api_key

kerf-server --migrate      # apply migrations
npm run dev                # vite :5173 + kerf-server :8080
```

Open <http://localhost:5173>. Hot reload runs on the frontend; the Python server
restarts on file change via `uvicorn --reload` (handled by `npm run dev`).

## Repo layout

```
packages/                One package per plugin. All under MIT.
  kerf-core/               core: FastAPI app, plugin loader, DB, storage
  kerf-auth/               JWT + API tokens + sessions
  kerf-api/                REST + LLM-tool surface for projects/files
  kerf-chat/               LLM clients + agent loop + doc search
  kerf-v1/                 /v1/rpc JSON-RPC endpoint
  kerf-cad-core/           pythonOCC helpers: sketch, BREP, surfacing
  kerf-tess/               STEP → glTF tessellation
  kerf-fem/                Linear-static + modal + thermal FEA
  kerf-cam/                CNC toolpaths
  kerf-topo/               SIMP topology optimization
  kerf-mates/              Assembly mate solvers
  kerf-bim/                Revit-parity BIM (categories, families, …)
  kerf-electronics/        ngspice, scikit-rf, autoroute, copper pour
  kerf-imports/            KiCad, 3DM, FreeCAD, OpenSCAD, mesh, draft, graph
  kerf-render/             Blender Cycles renders
  kerf-workers/            Background-worker harness
  kerf-sdk/                Python SDK (PyPI: kerf-sdk) for scripting
  kerf-pub/                DMTAP-PUB object model, feeds, publish/fetch/resolve/submit

src/                    React + Vite frontend (MIT)
  components/             shared UI
  routes/                 page-level routes
  lib/                    JSCAD runner, geom helpers, exporters, projection
  store/                  Zustand stores
docs/                   Markdown docs (you're here)
scripts/                npm helper scripts (init-config, etc.)
pyproject.toml          Root meta-package: persona optional-dependency groups
```

## One license, one node type

Kerf is 100% MIT. There is no proprietary tree, no dual license, and no
"cloud edition" versus "local edition" — every install (a laptop, a homelab
box, or a Vulos-hosted instance like `kerf.sh`) runs byte-identical
software. A node's behavior is governed entirely by config toggles
(`publicly-reachable`, `relay-for-others`, `pin-storage`, `offer-compute`),
never by which build you installed or a license gate. See
[node-architecture.md](./node-architecture.md).

PRs that change any file in this repo are welcome under the standard MIT
contributor flow — there is no separate license arrangement to negotiate.

## npm scripts

| Script                   | What it does                                                          |
|--------------------------|-----------------------------------------------------------------------|
| `npm run dev`            | Vite (:5173) + kerf-server (:8080), both with hot reload              |
| `npm run init`           | Copy `kerf.example.toml` → `kerf.toml` (idempotent)                  |
| `npm run migrate`        | Apply pending migrations via `python3 -m kerf_core.db.migrations.runner` |
| `npm run migrate:reset`  | Drop schema + re-apply all migrations from scratch                    |
| `npm run build`          | Alias for `build:web` — compiles the Vite SPA into `dist/`            |
| `npm run build:web`      | Frontend bundle only (runs `build-docs-manifest.mjs` first)           |
| `npm run start`          | Run `kerf-server` serving the pre-built `dist/` on `:8080`            |
| `npm run lint`           | ESLint                                                                |
| `npm run test`           | Vitest unit tests                                                     |
| `npm run test:e2e`       | Playwright end-to-end tests                                           |

## Config

Single TOML file. Search order: `--config <path>` → `KERF_CONFIG` env →
`./kerf.toml` → `~/.config/kerf/config.toml` → `/etc/kerf/config.toml`.
Schema in `kerf.example.toml`. Notable knobs:

- `[auth].optional = true` — single-user mode; no signup screen.
- `[storage].backend = "local" | "s3" | "filesystem"` — pick where binary
  assets live.
- `[llm.<provider>].api_key` — non-empty key activates that provider.
- `[limits].file_revisions_max` — cap revision history per file (default 200).

## Testing

Tests are split into tiers. A bare `pytest` runs the **default tier** — the
load-bearing product packages — which is expected to be green and is what CI
gates on:

```sh
make test                              # default tier — expected GREEN (~5.0k tests, ~3 min)
pytest packages/kerf-api/tests/        # one plugin
make test-kernel                       # kerf-cad-core geometry kernel (~38.8k tests, ~75 min)
make test-domains                      # the 22 engineering domains — experimental, currently RED
```

The kernel and domain tiers have known, documented failures and must not be
used as a release gate. Before assuming a failure there is yours, read
[TESTING.md](./TESTING.md) — it records the real numbers and the handful of
shared root causes behind them.

One rule worth internalising: **never assign to `sys.modules` at test-module
scope without restoring it.** `sys.modules` is process-global, and a stub left
behind by one test file silently corrupts every file collected after it. That
single mistake accounted for the bulk of a 1563-failure full-suite run.

Frontend has no automated test suite yet — assume manual smoke testing
plus the OpenSCAD vitest suite (`vitest run src/lib/openscadToJscad.test.js`).

## Code style

- **Python:** `ruff format` for formatting, `ruff check` for linting. No custom rules beyond the defaults.
- **JS:** `npm run lint` is ESLint with the React + hooks rules. Tailwind
  utility-classes only — no custom CSS modules.
- **Commits:** small and well-scoped. Plugin contract changes (`packages/kerf-core/src/kerf_core/plugin.py`)
  need matching updates across every plugin in the same PR.

## What to work on

The roadmap ([ROADMAP.md](../ROADMAP.md)) flags every shipped, in-flight,
next, and planned item. Anything marked `📋 next` or `🔮 planned` is fair
game for a PR — there's no proprietary tree to route around.

Bug reports → GitHub Issues. Feature discussions → GitHub Discussions.

## Branch and PR conventions

- Branch from `main`. Name branches `feat/<short-description>`,
  `fix/<short-description>`, or `chore/<short-description>`.
- One logical change per PR. Refactors and features in separate PRs.
- PR title: imperative mood, ≤ 72 chars. Examples:
  - `feat(electronics): add IPC-D-356A netlist export`
  - `fix(conftest): update tools.routing shim after plugin migration`
  - `chore: retire backend/ + pyworker/ residuals`
- PR description must include: what changed, why, and how to test.
- Plugin contract changes (`packages/kerf-core/src/kerf_core/plugin.py`
  — `PluginContext`, `PluginManifest`, `ToolSpec`) need matching updates
  across every plugin in the same PR. The CI will catch missing updates
  via the integration tests.

## Test conventions

Tests live in `packages/kerf-<name>/tests/`. The root `pytest` discovers them
all. Per-plugin test runs: `pytest packages/kerf-electronics/tests/`.

**File layout** inside a plugin's `tests/`:

```
tests/
  conftest.py    # plugin-local fixtures (DB pool mock, etc.)
  test_<module>.py
```

**Test rules**:

1. New tools require at least one happy-path test and one error-path test
   (invalid input → `{"error": …, "code": …}` JSON).
2. Tests must not make real network calls. Mock LLM clients with the in-memory
   stub from `kerf_chat.llm_stub` (if it exists) or `unittest.mock.AsyncMock`.
3. Tests must not require a live Postgres instance. Use `pytest.mark.db` for
   DB tests and mock the pool for pure-logic tests.
4. The root `conftest.py` installs a `tools.*` shim and the asyncio
   compatibility shim. Do not reproduce either in a plugin's `conftest.py`.
5. If a test asserts `code == "BAD_ARGS"` for a specific argument value,
   document why that value is invalid. Stale sentinels (where another commit
   made the value valid) are a common source of spurious failures — see
   [troubleshooting.md § Stale BAD_ARGS sentinel](./troubleshooting.md).

## Plugin layout conventions

Every plugin in `packages/kerf-<name>/` follows this structure:

```
packages/kerf-<name>/
├── pyproject.toml
│   # name, version, dependencies, entry-point:
│   # [project.entry-points."kerf.plugins"]
│   # <name> = "kerf_<name>.plugin:register"
│
├── src/kerf_<name>/
│   ├── __init__.py
│   ├── plugin.py          # register(app, ctx) → PluginManifest
│   ├── routes*.py         # FastAPI routers (optional)
│   ├── tools/             # LLM-tool modules
│   │   └── *.py           # each decorated with @register(ToolSpec(…))
│   └── llm_docs/          # markdown corpus for search_kerf_docs (optional)
│       └── *.md
│
└── tests/
    ├── conftest.py        # plugin-local fixtures
    └── test_*.py
```

`plugin.py` minimum shape:

```python
from fastapi import FastAPI
from kerf_core.plugin import PluginContext, PluginManifest

def register(app: FastAPI, ctx: PluginContext) -> PluginManifest:
    from .routes import router
    app.include_router(router, prefix="/api")

    from .tools import my_tool  # registers via @register decorator
    _ = my_tool                 # ensure module is imported

    return PluginManifest(
        name="kerf-<name>",
        version="0.1.0",
        provides=["domain.capability-tag"],
        depends=["kerf-core"],
    )
```

Library-only plugins (no routes, no tools) still register and return a
`PluginManifest` — they just omit the router and tool registration steps.

## Commit attribution policy

- Commits from humans: standard `git commit` with the author's name and email.
- Commits generated by automated agents: include a `Co-Authored-By:` trailer
  line identifying the tool. Example:
  ```
  feat(jewelry): add eternity-band builder

  Co-Authored-By: claude-sonnet-4 <noreply@anthropic.com>
  ```
- Never use `--no-verify` or `--no-gpg-sign` without a documented reason.
- Commit messages in imperative mood, ≤ 72 char subject, blank line before
  body. Conventional Commits prefix (`feat`, `fix`, `chore`, `docs`,
  `refactor`, `test`) + optional scope `(plugin-name)`.
- Do not amend published commits. Create a new fixup commit instead.

Next: [architecture.md](./architecture.md) · [capabilities.md](./capabilities.md) · [releasing.md](./releasing.md) · [troubleshooting.md](./troubleshooting.md)
