# Security policy

## Reporting a vulnerability

If you discover a security issue in Kerf, **do not open a public GitHub
issue**. Email **`kerfcad@gmail.com`** with details. PGP key on request.

Include:

- What you found.
- A minimal reproduction (if applicable).
- The version / commit SHA you tested against.
- Whether you've shared this with anyone else (e.g. an embargo'd
  advisory you're coordinating).

We aim to:

- Acknowledge receipt within **2 business days**.
- Confirm whether it's a real issue within **7 days**.
- Ship a fix or mitigation within **30 days** for critical / high-severity
  issues, longer for low-severity. We'll keep you updated either way.

If we can't reproduce or don't think it's a real issue, we'll explain
why; if you disagree, we'll go a round and try to align.

## Disclosure

Once a fix is shipped, we'll publish a GitHub Security Advisory and
credit you (if you'd like to be credited). For coordinated disclosure
with other vendors, we're happy to follow the timeline you negotiate
with them.

## In-scope

Anything in this repository:

- The Kerf application (backend FastAPI, frontend React, plugin
  packages).
- The Dockerfile and deployment configs.
- The `kerf-sdk` Python SDK.

## Out-of-scope

- Third-party services a deployment may depend on (Anthropic or your
  chosen LLM provider, Tigris, Fly.io, Neon, etc.) — report directly to
  those vendors.
- Issues that require an attacker with physical access to a victim's
  unlocked machine.
- Social-engineering attacks against Kerf staff.
- Self-hosted deployments where the user has misconfigured something
  documented as a config requirement (e.g. running with
  `KERF_LOCAL_MODE=true` exposed to the public internet — that mode
  is for single-user installs by design).

## What gets a bounty

We don't currently run a paid bounty program. We will:

- Credit you publicly in the advisory.
- Send Kerf-branded swag for high-quality reports.

If we grow into bounty-paying territory we'll announce it here.

## Verifying a downloaded release

Every `v*` release publishes a `SHA256SUMS` manifest covering **every** asset
attached to it — tarballs, the frontend bundle, the `install.sh` copy, the
Python wheels and the dependency manifests — plus a sigstore **build
provenance attestation** minted from the release workflow's OIDC identity (a
short-lived certificate, not a long-lived key someone has to hold and rotate).

`install.sh` verifies the tarball it downloaded against that manifest before
unpacking anything, and every way that check can fail is fatal: no manifest,
an empty manifest, no line for this asset, a digest mismatch, or no SHA-256
tool on the machine. There is no skip flag. To check an asset you downloaded
by hand:

```sh
curl -fsSLO https://raw.githubusercontent.com/vul-os/kerf/vX.Y.Z/scripts/verify.sh
bash verify.sh --tag vX.Y.Z kerf-vX.Y.Z-linux-x64.tar.gz            # digest
bash verify.sh --tag vX.Y.Z --attest kerf-vX.Y.Z-linux-x64.tar.gz   # + provenance
```

`verify.sh` needs only `curl` and `sha256sum`/`shasum`, and has two outcomes:
verified, or a non-zero exit with a diagnostic naming what was wrong — a
missing manifest (3), an HTML page where the manifest was expected (4), an
empty or malformed manifest (5), no entry for the asset (6), an unfetchable
artifact (7), a truncated download (8), a digest mismatch (9). A missing
`SHA256SUMS` is never treated as "nothing to check": a verifier that shrugs at
a 404 prints a line that looks like verification while checking nothing, which
is worse than no verifier. `--attest` needs the `gh` CLI; a run without it
prints that provenance was **not** checked, so a pass never implies more than
it checked.

Container images are addressed by their own registry digest
(`docker pull ghcr.io/vul-os/kerf@sha256:...`) and are not listed in
`SHA256SUMS`.

## Known security-relevant design notes

For context, these are documented choices — not vulnerabilities — but
worth knowing if you're auditing:

- **Local mode (`KERF_LOCAL_MODE=true`, the OSS default)** auto-creates
  a singleton user account and skips login. It's intended for
  single-developer machines; **never expose a local-mode install to
  the public internet without first setting `KERF_LOCAL_MODE=false`**.
- **API tokens** for your own install are stored hashed (not reversible).
  Lost tokens can be rotated from `Profile → API Tokens`. Each token has a
  configurable daily usage cap to bound stolen-credential blast radius
  (e.g. runaway calls against your own LLM provider key).
- **Git remote credentials** (e.g. GitHub personal-access tokens used to
  sync local git to a remote) and **distributor credentials** are
  encrypted at rest with AES-GCM
  (`packages/kerf-core/src/kerf_core/utils/encrypt.py`).
- **LLM API keys** are your own. In a server deployment they should be
  supplied as environment secrets (e.g. `fly secrets set`), never
  committed or stored in the database.
- **The chat tool surface is wide.** The LLM can read project files,
  edit them, and call tools that hit storage / Postgres on behalf of
  the user. Tool calls are scoped to the calling user's projects and
  workspaces. Tools that touch admin surfaces require a matching role.

If you find a tool call that escapes the user's project scope, that's a
high-severity bug. Please report.
