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

`.github/workflows/release.yml` has five jobs. It is the *only* workflow
that attaches assets to a release: `release-artifacts.yml` used to fire on the
same tag and attach wheels, the frontend tarball, `install.sh` and the SBOMs
directly, while `SHA256SUMS` was written over the tarballs alone. Four of the
nine published assets were covered by the manifest and five were not, and
nothing said which — `verify.sh <a wheel>` failed with "no entry" on a file
Kerf really had published. Those jobs now live here, every asset is staged
into one `release-out/` directory, and the manifest covers that directory.

### 1. `docker` — Docker images (GHCR)

Builds four Docker images in parallel via a matrix and pushes them to
**GitHub Container Registry**:

| Image tag | `KERF_PERSONA` | Contents |
|-----------|----------------|---------|
| `ghcr.io/vul-os/kerf:<version>` | `full` | everything |
| `ghcr.io/vul-os/kerf:latest` | `full` | same, alias |
| `ghcr.io/vul-os/kerf:<version>-mech` | `mech` | mechanical CAD |
| `ghcr.io/vul-os/kerf:<version>-electronics` | `electronics` | EDA/PCB |
| `ghcr.io/vul-os/kerf:<version>-bim` | `bim` | BIM |

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
- `kerf-frontend-X.Y.Z.tar.gz` — the built frontend `dist/`, from the same
  `npm run build` as the bundles above (it used to be rebuilt in a second
  workflow, so nothing guaranteed the two builds agreed)
- `kerf-install-vX.Y.Z.sh` — a verbatim, tag-stamped copy of `install.sh`. It
  is *not* pinned to that tag: it resolves the latest release at run time
  unless `KERF_VERSION` is set.

`SHA256SUMS` is **not** written by this job — see `publish` below.

**Honesty note:** Kerf is Python + Node, not a compiled binary, so there is
nothing to cross-compile per platform (yet). The three OS-labeled tarballs
today have byte-identical contents — the split exists for naming-convention
parity with `wede`/`diwan` (which ship real per-OS Go binaries) and so
`install.sh` has a stable, predictable asset name to fetch. A real
single-binary build (PyInstaller/Nuitka, or a thin Go launcher that embeds a
Python runtime) is a TODO for a later release — see the "Known limitations"
entry in `CHANGELOG.md`.

Each tarball unpacks to `kerf-vX.Y.Z/` and its bundled `setup.sh` creates a
venv, editable-installs the bundled packages, and writes a default
`kerf.toml` — see `scripts/bundled-setup.sh` for the exact steps, or just run
`curl -fsSL https://vulos.org/projects/kerf/install.sh | sh`, which does the download +
unpack + `setup.sh` run for you (see root `install.sh`).

### 3. `wheels` — Python wheels

Builds a wheel for every `packages/kerf-*` with a `pyproject.toml`/`setup.py`,
except `kerf-sdk` (own PyPI cadence). A run that produces no wheel fails the
job rather than quietly shipping a release without them.

### 4. `sbom` — dependency manifests

CycloneDX SBOMs for the Python environment and the npm tree. If CycloneDX is
unavailable the job publishes a `pip freeze` / `npm ls` manifest **and says so
in a warning** — those files are named `kerf-*-deps-*` rather than
`kerf-*-sbom-*`, because a pip freeze is not an SBOM and should not be
attached under a name that claims it is.

### 5. `publish` — checksums, attestation, the GitHub Release

Needs all four jobs above, then:

- Stages every asset from `artifacts`, `wheels` and `sbom` into one
  `release-out/` directory and asserts the expected set is complete (four
  tarballs, frontend tarball, `install.sh` copy, ≥1 wheel, a Python and an npm
  dependency manifest). A build job that silently produced nothing is a red
  release.
- Writes `SHA256SUMS` over **every** file in that directory, and asserts the
  manifest has one line per staged asset — a one-line manifest "covering" a
  nine-asset release would otherwise satisfy every later check.
- Verifies the result with `scripts/verify.sh --dir`, the same script a user
  runs, and cross-checks that the staged set and the listed set are identical
  in both directions.
- Runs `scripts/verify.sh --selftest` (24 synthetic-origin cases) so the
  refusals are known to still fire on this runner, before anything is public.
- Attaches a **sigstore build provenance attestation** over every asset,
  signed with a short-lived certificate minted from the job's OIDC token — no
  long-lived key, no repository secret, nothing to rotate. This is not OS
  code-signing, and it is not load-bearing for integrity: the digest path in
  `verify.sh` needs only `curl` and `sha256sum`.

- Extracts the `## [X.Y.Z] - ...` section from `CHANGELOG.md` (strict
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) headers) and uses
  it verbatim as the release body, followed by a short Docker quick-start and
  the `curl | sh` one-liner.
- Attaches the whole `release-out/` directory — the directory, not a
  hand-listed set of names, so "published" and "covered by `SHA256SUMS`"
  cannot drift apart.

**CHANGELOG.md discipline:** because the release notes are pulled straight
from `CHANGELOG.md`, the `## [X.Y.Z] - YYYY-MM-DD` section for the version
being tagged must exist and be accurate *before* you tag — `bump-version.sh`
does not write it for you. Move the relevant `## [Unreleased]` content into a
new dated version section as part of the same commit `bump-version.sh` makes
(or a commit just before it).

## Consuming a release

**Tarball (any OS):**

```sh
curl -fsSL https://vulos.org/projects/kerf/install.sh | sh
```

`install.sh` downloads the tarball, fetches the release's `SHA256SUMS`, looks
up the **exact** entry for the asset it downloaded and compares digests. Every
way that can fail is fatal: no manifest, an empty manifest, no line for this
asset, a digest mismatch, or no SHA-256 tool on the machine. There is no skip
flag. If you need unverified bytes, download the tarball and unpack it by hand
— that is an explicit act, not a silent default.

### Verifying a download by hand

```sh
curl -fsSLO https://raw.githubusercontent.com/vul-os/kerf/vX.Y.Z/scripts/verify.sh
bash verify.sh --tag vX.Y.Z kerf-vX.Y.Z-linux-x64.tar.gz          # digests
bash verify.sh --tag vX.Y.Z --attest kerf-vX.Y.Z-linux-x64.tar.gz # + provenance
bash verify.sh --dir ~/Downloads kerf-vX.Y.Z-linux-x64.tar.gz     # already downloaded
```

`verify.sh` needs only `curl` and `sha256sum`/`shasum`. It has two outcomes:
verified, or a non-zero exit with a diagnostic naming what was wrong — a
missing manifest (3), an HTML page served where the manifest was expected (4),
an empty or malformed manifest (5), no entry for the asset (6), an
unfetchable artifact (7), a truncated download (8), a digest mismatch (9). A
missing `SHA256SUMS` is never treated as "nothing to check". `--attest` also
verifies the sigstore build provenance (needs the `gh` CLI); a run *without*
it prints that provenance was **not** checked, so a pass never implies more
than it checked.

**Docker:**

```sh
docker pull ghcr.io/vul-os/kerf:0.2.0

docker run \
  -e KERF_DATABASE_URL=postgres://user:pass@host:5432/kerf \
  -e KERF_CONFIG=/etc/kerf/config.toml \
  -v /your/kerf.toml:/etc/kerf/config.toml:ro \
  -p 8080:8080 \
  ghcr.io/vul-os/kerf:0.2.0
```

The server listens on `:8080`. Set `VITE_API_URL` (or the proxy config in
`kerf.toml`) to point your frontend at it.

## Finding a release on GitHub

After the workflow runs:

- **Releases** — <https://github.com/vul-os/kerf/releases>
- **Packages** — <https://github.com/orgs/vul-os/packages>

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
