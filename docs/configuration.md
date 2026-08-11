# Configuration

Kerf is configured via a TOML file (`kerf.toml`) with environment-variable
overrides. There is a starter at `kerf.example.toml` in the repo root — copy it
yourself. (`npm run init` is meant to do this, but it resolves
`kerf.example.toml` relative to the working directory and npm runs it from
`web/`, so it finds nothing and silently does nothing.)

Full example: `kerf.example.toml` in the repo root.

## Config file search order

Nothing is required — most installs never create a `kerf.toml` at all, and a
missing one is not an error. When one is wanted, the server takes the first of:

1. `--config <path>` CLI flag (`kerf serve` and `kerf-server` both set
   `KERF_CONFIG` from it, so it beats anything already in the environment)
2. `KERF_CONFIG` environment variable
3. `./kerf.toml` (current working directory)
4. `~/.kerf/kerf.toml` (per-user)

A file that is present but does not parse raises immediately, naming the path —
it is never silently skipped in favour of defaults.

## Environment variable overrides

Config values are overridable at runtime with environment variables. **The
variable name is the flat setting name in uppercase, without a `KERF_`
prefix** — `LOCAL_MODE`, not `KERF_LOCAL_MODE`. The handful of `KERF_`-prefixed
variables below are read separately, by the entry point rather than by the
config loader.

| Env var | Affects | Notes |
|---------|---------|-------|
| `KERF_CONFIG` | _(path to config file)_ | See search order above |
| `KERF_HOST` | the bind address | Entry-point only; there is no `[server].host` TOML key. CLI `--host` also accepted |
| `KERF_PORT` | the bind port | Entry-point only. Resolution: `--port` > `KERF_PORT` > `[server].port` > 8080 |
| `LOCAL_MODE` | `[server].local_mode` | `true` or `false` |
| `PORT` | `[server].port` | What `Settings.port` itself reads |
| `DATABASE_URL` | `[database].url` | Standard 12-factor convention |
| `ANTHROPIC_API_KEY` | `[llm.anthropic].api_key` | |
| `OPENAI_API_KEY` | `[llm.openai].api_key` | |

Environment variables and `.env` sit **above** `kerf.toml`, which sits above the
built-in defaults — so a `docker run -e …` override wins over anything baked
into a config file.

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
| `local_mode` | `true` | Skips the marketing landing and opens straight into your projects; also lets the expensive compute endpoints run without a token. **Not an auth switch** — sign-in goes through the node password either way. Override with `LOCAL_MODE`. |

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

```ini
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
```

These knobs cover a Kerf install's **own local** auth — the owner's session
tokens and long-lived API tokens for the SDK / headless access. There is no
central account system, no sign-up service, and no Google/OAuth login: a
Kerf install is single-owner on your own box. Accounts shrink to the box.

| Key | Notes |
|-----|-------|
| `jwt_secret` | Signs JWT access tokens. Use a random 32-byte string in production. |
| `access_ttl` | Access token lifetime. Short is safer. |
| `refresh_ttl` | Refresh token lifetime. |
| `password_pepper` | Static server-side pepper added to bcrypt hashes. |

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

Those three are the whole set — any other value raises at startup. Per-project
git repos are not a `backend` choice: they are an ordinary node capability that
works under whichever of the three is configured.

`cdn_base_url` — when set, `Storage.PublicURL` returns a CDN URL instead of
routing through the backend. Recommended for production S3 deployments with
a CDN in front (e.g. bunny.net).

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

**You do not have to edit this file.** Every key here can also be set per user
from **Settings** in the app, where it is encrypted before storage and can be
changed without a restart. The keys configured here are the fallback for users
who have not set their own — which is what you want for a headless or
multi-user deployment, and unnecessary for a single-user install.

Settings also offers a **base URL** per provider. Point it at a LiteLLM proxy,
an OpenAI-compatible endpoint, or any gateway; leave it blank for the
provider's own API. Requests go through [LiteLLM](https://docs.litellm.ai/),
so a model the built-in catalogue does not list can still be reached through a
gateway by naming it with a provider prefix (`openrouter/meta/llama-4`).

## [rate_limits]

```toml
[rate_limits]
"setup:signin" = 60      # default 10 per minute
"api:export" = 100       # default 20 per hour
"api:blobs" = 0          # 0 disables the limiter for this bucket
```

Each key is a rate-limiter bucket name; the value replaces the limit that
bucket declares in code, and `0` disables it entirely. Keys are free text, so a
limiter added later is tunable without a config change — and an unrecognised
key is simply never consulted.

The buckets that exist today:

| Bucket | Default | Guards |
|--------|---------|--------|
| `setup:claim` | 10 / hour | Claiming an unconfigured node |
| `setup:signin` | 10 / minute | Exchanging the password for a session |
| `api:messages` | 30 / minute | Posting a chat message (runs the agent loop) |
| `api:messages_stream` | 30 / minute | The streaming variant |
| `api:export` | 20 / hour | Whole-project export |
| `api:blobs` | 120 / minute | Blob fetches |
| `api:photos` | 60 / minute | Photo upload on a file |

**The `setup:*` limiters key on IP, because the requests they guard are
unauthenticated by definition.** That is what you want for a node on a network
— they are the only thing standing between a stranger and password guesses —
and it is worth leaving alone.

Also settable as an environment variable, as JSON:

```
RATE_LIMIT_OVERRIDES='{"api:export": 100}'
```

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
| `upload_chunk_size` | `5 MB` | Chunk size for resumable uploads. The server returns it in the initiate response, so the browser follows whatever is set here. |
| `upload_session_ttl_hours` | `24` | How long an unfinished chunked upload stays resumable. |

`max_threads_per_project`, `step_tessellate_workers` and
`step_tessellate_timeout_sec` are accepted by the loader but read by nothing —
setting them changes no behaviour today.

## [system_user]

```toml
[system_user]
email = "system@kerf.local"
name = "Kerf System"
password = ""
```

`email` and `name` set the identity of the singleton user (default:
`local@kerf.local` / "Local"). The row is created lazily, the first time
someone signs in through `POST /api/setup/signin` — not on boot.

`password` is inert: nothing reads it. The node's password is set on first
load through the setup screen, or from the machine with
`kerf admin set-password`. See [api-reference.md](./api-reference.md#authentication).

`GET /api/bootstrap` still reads a refresh token from
`~/.config/kerf/state.json` (or `$KERF_STATE_PATH`) when `local_mode` is on, but
no code writes that file any more — it returns `{"has_state": false}` unless
you put one there yourself.

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
