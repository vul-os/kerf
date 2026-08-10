# Desktop build

A one-file native binary: `kerf-desktop`. One process, one binary — no
sidecar. The FastAPI app runs on uvicorn in a background thread inside the
same process; a native OS webview (WebView2 on Windows, WebKit on
macOS/Linux — **not** a bundled Chromium) opens a window pointed at it. The
built frontend is embedded in the binary as data.

This is a different distribution channel from everything in
[local-install.md](./local-install.md) — no install script, no Docker, no
`pip install`. Build it yourself:

```sh
make desktop
# or:
./scripts/build-desktop.sh
```

Output: `packages/kerf-desktop/dist/kerf-desktop` — a single executable.
Run it directly; it opens a window.

## How it's wired

- `packages/kerf-desktop/src/kerf_desktop/main.py` — the entrypoint. It
  binds `127.0.0.1:0` to get an OS-assigned free port (never a hardcoded
  one), starts `kerf_core.app:create_app` on uvicorn in a daemon thread,
  polls `/health` until it answers (30s+ timeout, a clear error if the
  server never comes up), opens a pywebview window titled "Kerf" at that
  URL, and shuts the server down when the window closes.
- `packages/kerf-desktop/kerf-desktop.spec` — the PyInstaller spec.
  `--add-data`-embeds `web/dist` into the binary under `web_dist/`; at
  runtime `main.py` points `KERF_FRONTEND_DIST` at
  `sys._MEIPASS/web_dist`. Serving itself is unchanged, existing code:
  `kerf_core.app._mount_frontend` already serves a built frontend from
  `KERF_FRONTEND_DIST` (that's how the Docker image serves `/app/dist`
  today) — including its path-traversal guard, which this build leaves
  untouched. This was wiring, not new architecture.
- `scripts/build-desktop.sh` — builds `web/dist` (`npm run build`), creates
  a build venv, installs the packages below into it, and runs PyInstaller.

## What's actually IN the binary — the lean persona

`packages/kerf-desktop/pyproject.toml` lists the exact dependency set:
`kerf-core`, `kerf-auth`, `kerf-api`, `kerf-chat` (server stack) plus
`kerf-cad-core`, `kerf-tess`, `kerf-fem`, `kerf-cam`, `kerf-topo`,
`kerf-mates` (compute plugins) plus `pywebview`. That is the **same package
list as the `mech` persona** in the root `pyproject.toml` — but only its
*base*, pip-installable dependencies. It includes:

- JSCAD / SDF / NURBS-adjacent geometry helpers, tessellation (Node-sidecar
  fallback via `occt-import-js`, not pythonOCC), sketching (planegcs, WASM,
  ships in the frontend bundle), drawings, mates/assembly solving, CAM
  toolpaths, topology optimisation scaffolding.
- Electronics/BIM/etc are **not** in this binary — only what `mech`
  installs. A `kerf-desktop-electronics` or `-bim` variant would be a
  separate spec / persona choice, not built here.

## What's deliberately NOT in the binary, and why

**OCCT B-rep (pythonOCC) and real FEM (FEniCSx/dolfinx) are excluded.**
Both are distributed through **conda-forge only** — neither is on PyPI for
any Python version, so neither can be `pip install`-ed, and PyInstaller can
only freeze what's importable in the build venv's site-packages. There is
no way to get either into a `pip`-built, `PyInstaller`-frozen single file
today. See [local-install.md#solver-dependencies-dolfinx--pythonocc](./local-install.md#solver-dependencies-dolfinx--pythonocc)
for the same constraint on every other install path.

This is not silent degradation baked in without notice — it is exactly how
the `mech` persona already behaves everywhere else it runs without a conda
env (`./scripts/dev-install.sh mech`, a plain venv, CI): `kerf-cad-core` and
`kerf-fem` still **register** (their `kerf.plugins` entry points load, so
the app boots and every other route works), but they log a startup warning
and report their OCCT-dependent / real-FEM tools as unavailable rather than
crash the process. Concretely, in the desktop binary:

- `kerf-cad-core`: OCCT B-rep operations (STEP/IGES import-export, real
  B-rep booleans, fillets/chamfers on B-rep solids) are unavailable.
  Tessellation of STEP files falls back to the Node sidecar
  (`occt-import-js`, a WASM build already shipped in the frontend bundle) —
  good enough for viewing, not for boolean CAD operations.
- `kerf-fem`: register, but numeric solves that depend on dolfinx
  (`fem.*` tools backed by FEniCSx) are unavailable; the CalculiX bridge
  (`kerf-fem[calculix]`) additionally needs the external `ccx` binary
  present on `PATH`, which this binary does not vendor either.

**If you need OCCT B-rep or real FEM**, this binary is not the path —
`pip install`/`./scripts/dev-install.sh mech` (or `full`) into a **conda**
environment that has `pythonocc-core` and `fenics-dolfinx` installed
alongside it remains the only way to get them, exactly as documented in
[local-install.md](./local-install.md#solver-dependencies-dolfinx--pythonocc).
There is no plan to make the desktop binary carry a bundled conda runtime —
that would make it a very different (and much larger) kind of artifact than
"one file."

## Database

No setup required. With `DATABASE_URL` unset (the default — nothing in the
binary sets it), `kerf_core` opens an embedded SQLite file at
`~/.kerf/kerf.db` (WAL, foreign keys on, auto-created on first run). No
Postgres server, and no Docker, is needed to run this binary.

## Verifying a build works without your dev environment

The whole point of a one-file binary is that it does not assume a Python
install, a repo checkout, or an active venv on `PATH`. To check that:

```sh
cd /tmp                       # anywhere outside the repo, venv deactivated
/path/to/packages/kerf-desktop/dist/kerf-desktop &
sleep 2
curl -s http://127.0.0.1:<port>/health   # port is logged to stdout on boot
```

(The binary logs its chosen port and the health-check result to stdout —
`console=True` in the spec, deliberately, so a build can be diagnosed from
the terminal even though the day-to-day experience is "double-click, a
window opens.")

## Known limits beyond the OCCT/FEM exclusion

- The binary is built for the machine's own OS/arch (this repo's build was
  verified on macOS/arm64). Cross-compiling a Windows or Linux binary from
  macOS is not set up — build on each target OS, or wire up CI matrix
  builds later.
- `console=True` in the spec means the binary currently opens (or is
  attached to) a terminal/console alongside the webview window. Flipping to
  `console=False` for a quieter release build is a follow-up, not done here
  — this build prioritizes being diagnosable.
- No code signing / notarization is configured. An unsigned macOS binary
  will be Gatekeeper-blocked on another machine (`xattr -d
  com.apple.quarantine` works around it locally); Windows SmartScreen has
  the equivalent friction. Distributing this beyond your own machine needs
  a signing identity, which is out of scope here.
