# Configuration

Kerf is configured via a TOML file (`kerf.toml`) with environment-variable
overrides. A starter file is emitted by `npm run init` (source installs) or
by `kerf-server --init`.

Full example: `kerf.example.toml` in the repo root.

## Config file search order

The server picks the first file found, in priority order:

1. `--config <path>` CLI flag
2. `KERF_CONFIG` environment variable
3. `./kerf.toml` (current working directory)
4. `~/.config/kerf/config.toml` (per-user)
5. `/etc/kerf/config.toml` (system-wide)

## Environment variable overrides

Any config value can be overridden at runtime with an environment variable. The
convention is `KERF_` prefix + the TOML path in uppercase with dots/brackets
replaced by underscores. Key specific overrides:

| Env var | Equivalent TOML key | Notes |
|---------|---------------------|-------|
| `KERF_CONFIG` | _(path to config file)_ | |
| `KERF_HOST` | `[server].host` | CLI `--host` also accepted |
| `KERF_PORT` | `[server].port` | CLI `--port` also accepted |
| `KERF_LOCAL_MODE` | `[server].local_mode` | `true` or `false` |
| `DATABASE_URL` | `[database].url` | Standard 12-factor convention |
| `ANTHROPIC_API_KEY` | `[llm.anthropic].api_key` | |
| `OPENAI_API_KEY` | `[llm.openai].api_key` | |

## [server]

```toml
[server]
port = "8080"
env = "local"              # "local" | "dev" | "main"
cors_origin = "http://localhost:5173"
local_mode = true
```

| Key | Default | Notes |
|-----|---------|-------|
| `port` | `"8080"` | HTTP port. Override with `KERF_PORT` or `--port`. |
| `env` | `"local"` | Informational label; controls some log verbosity. |
| `cors_origin` | `"http://localhost:5173"` | Single allowed CORS origin. In production set to your frontend URL. |
| `local_mode` | `true` | When `true`: no login screen, a singleton user is auto-bootstrapped. Set `false` for multi-user deploys. Override with `KERF_LOCAL_MODE`. |

## [database]

```toml
[database]
# Leave unset for the embedded SQLite default (~/.kerf/kerf.db).
# Set a postgres:// URL to opt into the Postgres scale backend.
# url = "postgres://postgres:postgres@localhost:5432/kerf?sslmode=disable"
```

When `url` is unset kerf uses an **embedded SQLite** database at `~/.kerf/kerf.db`
(created automatically, WAL mode, foreign keys on). This is the zero-dependency
default for a local install — nothing else to install or run.

Set `url` to a standard `postgres://` connection string to switch to the
**Postgres scale backend** (teams / always-on / multi-node). Override either way
with the `DATABASE_URL` environment variable — it takes precedence when set.

```
# Scale mode; if the Postgres role matches your system username:
DATABASE_URL=postgres://pc@localhost:5432/kerf?sslmode=disable
```

See [architecture/database.md](./architecture/database.md) for the two-backend
design and exactly which capabilities are Postgres-only.

## [auth]

```toml
[auth]
jwt_secret = "change-me-in-production"
access_ttl = "15m"
refresh_ttl = "720h"
password_pepper = "change-me-in-production"

  [auth.google]
  client_id = ""
  client_secret = ""
  redirect_url = "http://localhost:8080/auth/google/callback"
```

| Key | Notes |
|-----|-------|
| `jwt_secret` | Signs JWT access tokens. Use a random 32-byte string in production. |
| `access_ttl` | Access token lifetime. Short is safer. |
| `refresh_ttl` | Refresh token lifetime. |
| `password_pepper` | Static server-side pepper added to bcrypt hashes. |
| `[auth.google]` | Leave `client_id` empty to disable Google OAuth. |

## [storage]

```toml
[storage]
backend = "local"
local_path = "./.kerf-storage"
filesystem_root = "~/kerf-projects"
cdn_base_url = ""

  [storage.s3]
  bucket = ""
  region = ""
  access_key_id = ""
  secret_access_key = ""
  endpoint = ""       # for R2 / MinIO / custom
  public_url_base = ""
```

| `backend` value | Behaviour |
|-----------------|-----------|
| `"local"` | Opaque blob store under `local_path`. Default. Auth-protected `/api/blobs/{key}` serves bytes. |
| `"s3"` | AWS S3, Cloudflare R2, or MinIO. Blob downloads are presigned 302 redirects. Set `[storage.s3]` credentials. |
| `"filesystem"` | Projects mirror to `filesystem_root` as real folders. Files are editable with any tool. |
| `"git"` | Per-project git mirror in S3 — an ordinary MIT node capability, not cloud-only. Requires `[storage.s3]`. |

`cdn_base_url` — when set, `Storage.PublicURL` returns a CDN URL instead of
routing through the backend. Recommended for production S3 deployments with
a CDN in front (e.g. bunny.net). OSS-compatible; cloud not required.

## [llm]

```toml
[llm]
default_model = "claude-opus-4-7"

  [llm.anthropic]
  api_key = ""

  [llm.openai]
  api_key = ""

  [llm.moonshot]
  api_key = ""

  [llm.gemini]
  api_key = ""
```

A blank `api_key` disables that provider. At least one provider must have a
key set for the LLM agent loop to function. `default_model` is used when the
user does not specify a model. Override individual providers via their
respective env vars (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc.).

## [limits]

```toml
[limits]
max_threads_per_project = 50
file_revisions_max = 200
step_max_bytes = 200000000
upload_chunk_size = 5242880
upload_session_ttl_hours = 24
step_tessellate_workers = 2
step_tessellate_timeout_sec = 300
```

| Key | Default | Notes |
|-----|---------|-------|
| `file_revisions_max` | `200` | Per-file undo history cap. Each edit appends one row; oldest beyond this cap are pruned on next write. |
| `step_max_bytes` | `200 MB` | Maximum STEP upload size. |
| `upload_chunk_size` | `5 MB` | Chunk size for resumable uploads. Must match what the frontend sends. |
| `step_tessellate_workers` | `2` | Workers for server-side STEP → GLB tessellation. Set `-1` to disable. |

## [system_user]

```toml
[system_user]
email = "system@kerf.local"
name = "Kerf System"
password = ""
```

When `password` is non-empty, the server ensures this user exists in the
database on boot, mints a long-lived refresh token, and writes it to
`~/.config/kerf/state.json`. The frontend reads `/api/bootstrap` on first
load and silently signs in. This is the mechanism behind the
single-user local-install UX.

Leave `password` blank for multi-user deploys — bootstrap becomes a no-op.

## Node config (retired: `[cloud]` / Paystack / GitHub OAuth)

Kerf no longer has a proprietary `[cloud]` config block, Paystack billing, or
a kerf-operated GitHub OAuth app — there is no billing anywhere and no
"cloud edition." Every install is a full node whose behavior is governed by
config toggles (`publicly-reachable`, `relay-for-others`, `pin-storage`,
`offer-compute`), not by an `enabled` flag on a proprietary package. See
[node-architecture.md](./node-architecture.md) for the current toggle model.

GitHub is used as an ordinary git remote with your own SSH key or PAT — no
client ID/secret, no OAuth redirect. See
[github-sync.md](./github-sync.md).

## See also

- `kerf.example.toml` — annotated full schema in the repo root
- [local-install.md](./local-install.md) — install paths and Postgres setup
- [deployment.md](./deployment.md) — Docker and environment variable passing
