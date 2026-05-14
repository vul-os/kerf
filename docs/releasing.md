# Releasing Kerf

How to cut a new monorepo release. Takes about two minutes.

## Version scheme

The monorepo uses a single version for all plugin packages (`kerf-core`,
`kerf-api`, `kerf-auth`, …) and the frontend. The canonical source of truth is
the `VERSION` file at the repo root.

**`kerf-sdk` is excluded** — it lives on PyPI with its own independent version
cadence, triggered by `sdk-v*` tags via
`packages/kerf-sdk/.github/workflows/publish.yml`. Do not bump `kerf-sdk`'s
version here.

## Two-command release flow

```sh
./scripts/bump-version.sh 0.2.0
git tag v0.2.0
git push origin v0.2.0
```

That's it. The bump script commits, the tag push triggers CI.

## What `bump-version.sh` does

1. Checks the working tree is clean (refuses to run dirty).
2. Writes the new version to `VERSION`.
3. Updates `version = "..."` in root `pyproject.toml` and every
   `packages/kerf-*/pyproject.toml` (except `kerf-sdk`).
4. Updates `"version": "..."` in `package.json`.
5. Commits everything with `chore: bump version to v<new-version>`.

## What happens in GitHub Actions

Pushing a `v*` tag fires `.github/workflows/release.yml`, which:

1. Builds four Docker images in parallel via a matrix:
   | Image tag | `KERF_PERSONA` | Contents |
   |-----------|----------------|---------|
   | `ghcr.io/kerf-sh/kerf:<version>` | `full` | everything |
   | `ghcr.io/kerf-sh/kerf:latest` | `full` | same, alias |
   | `ghcr.io/kerf-sh/kerf:<version>-mech` | `mech` | mechanical CAD |
   | `ghcr.io/kerf-sh/kerf:<version>-electronics` | `electronics` | EDA/PCB |
   | `ghcr.io/kerf-sh/kerf:<version>-bim` | `bim` | BIM |

2. Pushes all images to **GitHub Container Registry** (`ghcr.io/kerf-sh/kerf`).
   Access requires `permissions: packages: write` — already set in the workflow.

3. Creates a **GitHub Release** with:
   - Auto-generated commit notes since the previous `v*` tag.
   - A quick-start snippet showing how to pull and run the container.

## Consuming the container image

```sh
# Pull
docker pull ghcr.io/kerf-sh/kerf:0.2.0

# Run (bring your own Postgres and config file)
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

- **Packages** — <https://github.com/orgs/kerf-sh/packages>
- **Releases** — <https://github.com/kerf-sh/kerf/releases>

## Hotfix releases

Same flow, just from a hotfix branch:

```sh
git checkout -b hotfix/0.1.1 v0.1.0
# ... fix commits ...
./scripts/bump-version.sh 0.1.1
git tag v0.1.1
git push origin v0.1.1
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
