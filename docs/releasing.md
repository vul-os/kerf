# Releasing Kerf

How to cut a new monorepo release. Takes about two minutes locally; CI does
the rest.

## Version scheme

The monorepo uses a single version for all plugin packages (`kerf-core`,
`kerf-api`, `kerf-auth`, …) and the frontend. The canonical source of truth is
the `VERSION` file at the repo root.

**`kerf-sdk` is excluded** — it lives on PyPI with its own independent version
cadence, triggered by `sdk-v*` tags via
`packages/kerf-sdk/.github/workflows/publish.yml`. Do not bump `kerf-sdk`'s
version here.

## One-command release flow

```sh
make release VERSION=0.2.0
```

This:

1. Runs `./scripts/bump-version.sh 0.2.0`, which refuses to run on a dirty
   tree, then bumps `VERSION`, root `pyproject.toml`, every
   `packages/kerf-*/pyproject.toml` (except `kerf-sdk`), and `package.json`,
   and commits `chore: bump version to v0.2.0`.
2. Tags `v0.2.0`.
3. Pushes `main` and the tag.

Pushing the tag fires `.github/workflows/release.yml`.

## What happens in GitHub Actions

`.github/workflows/release.yml` has three jobs:

### 1. `docker` — Docker images (GHCR)

Builds four Docker images in parallel via a matrix and pushes them to
**GitHub Container Registry**:

| Image tag | `KERF_PERSONA` | Contents |
|-----------|----------------|---------|
| `ghcr.io/kerf-sh/kerf:<version>` | `full` | everything |
| `ghcr.io/kerf-sh/kerf:latest` | `full` | same, alias |
| `ghcr.io/kerf-sh/kerf:<version>-mech` | `mech` | mechanical CAD |
| `ghcr.io/kerf-sh/kerf:<version>-electronics` | `electronics` | EDA/PCB |
| `ghcr.io/kerf-sh/kerf:<version>-bim` | `bim` | BIM |

Access requires `permissions: packages: write` — already set in the workflow.

### 2. `artifacts` — installable tarballs

Builds the frontend once (`npm ci && npm run build`) and assembles a
self-contained release bundle: the pre-built `dist/`, every
`packages/kerf-*` plugin's Python source (except `kerf-sdk`), repo metadata
(`pyproject.toml`, `kerf.example.toml`, `README.md`, `LICENSE`,
`CHANGELOG.md`, `VERSION`), and `scripts/bundled-setup.sh` copied in as
`setup.sh`.

That bundle is packed into four files and a checksum manifest, uploaded to
the release:

- `kerf-vX.Y.Z-macos-arm64.tar.gz`
- `kerf-vX.Y.Z-macos-x64.tar.gz`
- `kerf-vX.Y.Z-linux-x64.tar.gz`
- `kerf-vX.Y.Z-src.tar.gz` — universal `git archive` of the tag (full
  monorepo, including `kerf-sdk` and tests — for anyone building from source
  on an unlisted platform, e.g. Linux/arm64)
- `SHA256SUMS`

**Honesty note:** Kerf is Python + Node, not a compiled binary, so there is
nothing to cross-compile per platform (yet). The three OS-labeled tarballs
today have byte-identical contents — the split exists for naming-convention
parity with `wede`/`ofisi` (which ship real per-OS Go binaries) and so
`install.sh` has a stable, predictable asset name to fetch. A real
single-binary build (PyInstaller/Nuitka, or a thin Go launcher that embeds a
Python runtime) is a TODO for a later release — see the "Known limitations"
entry in `CHANGELOG.md`.

Each tarball unpacks to `kerf-vX.Y.Z/` and its bundled `setup.sh` creates a
venv, editable-installs the bundled packages, and writes a default
`kerf.toml` — see `scripts/bundled-setup.sh` for the exact steps, or just run
`curl -fsSL https://kerf.sh/install.sh | sh`, which does the download +
unpack + `setup.sh` run for you (see root `install.sh`).

### 3. `publish` — the GitHub Release

Needs both jobs above, then:

- Extracts the `## [X.Y.Z] - ...` section from `CHANGELOG.md` (strict
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) headers) and uses
  it verbatim as the release body, followed by a short Docker quick-start and
  the `curl | sh` one-liner.
- Attaches all four tarballs + `SHA256SUMS`.

**CHANGELOG.md discipline:** because the release notes are pulled straight
from `CHANGELOG.md`, the `## [X.Y.Z] - YYYY-MM-DD` section for the version
being tagged must exist and be accurate *before* you tag — `bump-version.sh`
does not write it for you. Move the relevant `## [Unreleased]` content into a
new dated version section as part of the same commit `bump-version.sh` makes
(or a commit just before it).

## Consuming a release

**Tarball (any OS):**

```sh
curl -fsSL https://kerf.sh/install.sh | sh
```

**Docker:**

```sh
docker pull ghcr.io/kerf-sh/kerf:0.2.0

docker run \
  -e KERF_DATABASE_URL=postgres://user:pass@host:5432/kerf \
  -e KERF_CONFIG=/etc/kerf/config.toml \
  -v /your/kerf.toml:/etc/kerf/config.toml:ro \
  -p 8080:8080 \
  ghcr.io/kerf-sh/kerf:0.2.0
```

The server listens on `:8080`. Set `VITE_API_URL` (or the proxy config in
`kerf.toml`) to point your frontend at it.

## Finding a release on GitHub

After the workflow runs:

- **Releases** — <https://github.com/vul-os/kerf/releases>
- **Packages** — <https://github.com/orgs/kerf-sh/packages>

## Hotfix releases

Same flow, just from a hotfix branch:

```sh
git checkout -b hotfix/0.1.1 v0.1.0
# ... fix commits, including the CHANGELOG.md [0.1.1] section ...
make release VERSION=0.1.1
```

## Version in the codebase

| Location | How it's set |
|----------|-------------|
| `VERSION` | canonical source, plain text `0.1.0\n` |
| `pyproject.toml` (root) | `version = "0.1.0"` |
| `packages/kerf-*/pyproject.toml` | `version = "0.1.0"` (except kerf-sdk) |
| `package.json` | `"version": "0.1.0"` |
| Frontend at runtime | Vite `define.__APP_VERSION__` reads `package.json` at build time |
| `/health` API response | `importlib.metadata.version("kerf-core")` at runtime |
